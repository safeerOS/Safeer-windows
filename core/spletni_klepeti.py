"""Spletni klepeti in spletna posta, vdelani v Safeer (Sporocila v Safeer OS, stranska plosca Safeer Browserja).

En vir za vse Safeerjeve brskalnike (AGENTS.md: »vsaka izboljsava spletne izkusnje gre v vse brskalnike«): katalog,
branje stevila neprebranih iz naslova strani, preverba lastnega naslova, shramba kanalov in preselitev starih naslovov.
GTK-ja ta modul ne potrebuje (uvaza ga tudi core/config.py).

Pravilo »brez receptov za strani« (CONTRIBUTING.md): storitev je SAMO podatkovni vnos (ime, naslov, vrsta, povezava za
prenos). Nobena koda tu ali drugje ne odloca po imenu gostitelja, nobenih vstavljenih skript ali izbirnikov za eno stran.
Kar ne dela, je splosna napaka (Scit, WebKit), ki jo popravimo za vse strani.

Katalog je izmeril lastnik 15. 10. 2026 na testnem PC (WebKitGTK 2.54.1 iz nasega Flatpaka, privzeti UA, cista seja, brez
prijave): vsak spodnji naslov z »splet« se nalozi do zaslona za prijavo ali kode QR. Messenger: Meta je messenger.com
ukinila 15. 4. 2026 (preusmeri na facebook.com/messages), zato je naslov tam.
"""
from __future__ import annotations

import ipaddress
import re
import urllib.parse
import uuid

KLEPET, POSTA = "klepet", "posta"

#: Razlogi, zakaj storitve ni mogoce vdelati (en stavek v vmesniku, prevodi v RAZLOGI).
BREZ_SPLETA, WEBKIT_NI_PODPRT, SAMO_RAZSIRITEV = "brez_spleta", "webkit", "razsiritev"

#: Storitve. id: stalna oznaka (shramba, preselitve), ime: lastno ime storitve, pripis: kljuc dodatka k imenu
#: (PRIPISI, preveden), splet: uradni spletni odjemalec (prazno = ga ni mogoce vdelati), prenos: uradna stran za prenos,
#: razlog: zakaj ni vdelan (samo, ce je splet prazen).
KATALOG: list = [
    {"id": "messenger", "ime": "Messenger", "vrsta": KLEPET, "splet": "https://www.facebook.com/messages/", "prenos": ""},
    {"id": "whatsapp", "ime": "WhatsApp", "vrsta": KLEPET, "splet": "https://web.whatsapp.com/",
     "prenos": "https://www.whatsapp.com/download"},
    {"id": "telegram", "ime": "Telegram", "vrsta": KLEPET, "splet": "https://web.telegram.org/a/",
     "prenos": "https://desktop.telegram.org/"},
    # SMS in RCS s telefona Android (povezava s kodo QR v aplikaciji Sporocila na telefonu).
    {"id": "google-messages", "ime": "Google Messages", "vrsta": KLEPET, "splet": "https://messages.google.com/web/",
     "prenos": "", "pripis": "sms"},
    {"id": "instagram", "ime": "Instagram", "vrsta": KLEPET, "splet": "https://www.instagram.com/direct/inbox/", "prenos": ""},
    {"id": "discord", "ime": "Discord", "vrsta": KLEPET, "splet": "https://discord.com/app",
     "prenos": "https://discord.com/download"},
    {"id": "slack", "ime": "Slack", "vrsta": KLEPET, "splet": "https://app.slack.com/client",
     "prenos": "https://slack.com/downloads"},
    {"id": "teams-osebni", "ime": "Microsoft Teams", "vrsta": KLEPET, "splet": "https://teams.live.com/", "prenos": "",
     "pripis": "osebno"},
    {"id": "teams", "ime": "Microsoft Teams", "vrsta": KLEPET, "splet": "https://teams.microsoft.com/v2/", "prenos": "",
     "pripis": "sluzba"},
    {"id": "google-chat", "ime": "Google Chat", "vrsta": KLEPET, "splet": "https://chat.google.com/", "prenos": ""},
    {"id": "element", "ime": "Element (Matrix)", "vrsta": KLEPET, "splet": "https://app.element.io/",
     "prenos": "https://element.io/download"},
    # Izmerjeno 15. 10. 2026: stran za prijavo se nalozi; klepet PO prijavi ni bil preverjen (nismo se prijavljali).
    {"id": "snapchat", "ime": "Snapchat", "vrsta": KLEPET, "splet": "https://www.snapchat.com/web", "prenos": ""},
    {"id": "x", "ime": "X", "vrsta": KLEPET, "splet": "https://x.com/i/chat", "prenos": "", "pripis": "sporocila"},
    {"id": "linkedin", "ime": "LinkedIn", "vrsta": KLEPET, "splet": "https://www.linkedin.com/messaging/", "prenos": ""},
    {"id": "threema", "ime": "Threema Web", "vrsta": KLEPET, "splet": "https://web.threema.com/", "prenos": ""},
    {"id": "wechat", "ime": "WeChat", "vrsta": KLEPET, "splet": "https://web.wechat.com/", "prenos": ""},
    {"id": "gmail", "ime": "Gmail", "vrsta": POSTA, "splet": "https://mail.google.com/mail/", "prenos": ""},
    {"id": "outlook", "ime": "Outlook", "vrsta": POSTA, "splet": "https://outlook.live.com/mail/",
     "prenos": "https://www.microsoft.com/microsoft-365/outlook/email-and-calendar-software-microsoft-outlook"},
    {"id": "proton", "ime": "Proton Mail", "vrsta": POSTA, "splet": "https://mail.proton.me/",
     "prenos": "https://proton.me/mail/download"},
    {"id": "tuta", "ime": "Tuta Mail", "vrsta": POSTA, "splet": "https://app.tuta.com/", "prenos": "https://tuta.com/#download"},
    # Namizna programa (spletnega odjemalca nimata): okno programa se vstavi v Sporocila (core/vstavi_okno.py), ce je
    # program namescen; sicer »Namesti« odpre uradno stran za prenos. Signal: uradno samo .deb iz Signalovega
    # repozitorija (signal.org/download); Flatpak org.signal.Signal je neuraden, a ga zaznamo, ce ga uporabnik ima.
    # Electron: --ozone-platform=x11, da je okno X11 in ga je mogoce vstaviti (WM_CLASS iz StartupWMClass vnosa).
    {"id": "signal", "ime": "Signal", "vrsta": KLEPET, "splet": "", "prenos": "https://signal.org/download/",
     "program": {"vnosi": ["signal-desktop.desktop", "org.signal.Signal.desktop"], "ukazi": ["signal-desktop"],
                 "appimage": ["signal*.appimage"], "razredi": ["signal", "Signal"],
                 "argumenti": ["--ozone-platform=x11"]}},
    {"id": "viber", "ime": "Viber", "vrsta": KLEPET, "splet": "", "prenos": "https://www.viber.com/en/download/",
     "program": {"vnosi": ["viber.desktop", "com.viber.Viber.desktop"], "ukazi": ["viber", "/opt/viber/Viber"],
                 "appimage": ["viber*.appimage"], "razredi": ["ViberPC", "Viber"], "argumenti": []}},
    # Ni jih mogoce vdelati (preverjeno 15. 10. 2026): ostane samo uradna stran za prenos z razlogom.
    {"id": "wire", "ime": "Wire", "vrsta": KLEPET, "splet": "", "prenos": "https://wire.com/en/download",
     "razlog": WEBKIT_NI_PODPRT},
    {"id": "line", "ime": "LINE", "vrsta": KLEPET, "splet": "", "prenos": "https://line.me/en/download",
     "razlog": SAMO_RAZSIRITEV},
]

#: Naslovi, ki jih je ponudnik ukinil, in kam so se preselili (podatek, ne koda za stran): uporabnikove shranjene
#: nastavitve se ob branju preselijo (preseli_naslov), tako v Sporocilih kot v stranski plosci brskalnika.
PRESELJENI: dict = {
    "messenger.com": "https://www.facebook.com/messages/",
    "www.messenger.com": "https://www.facebook.com/messages/",
}

PRIPISI = {
    "sl": {"osebno": "osebni", "sluzba": "službeni ali šolski", "sporocila": "sporočila", "sms": "SMS in RCS"},
    "en": {"osebno": "personal", "sluzba": "work or school", "sporocila": "messages", "sms": "SMS and RCS"},
    "de": {"osebno": "privat", "sluzba": "Arbeit oder Schule", "sporocila": "Nachrichten", "sms": "SMS und RCS"},
    "es": {"osebno": "personal", "sluzba": "trabajo o centro educativo", "sporocila": "mensajes", "sms": "SMS y RCS"},
    "fr": {"osebno": "personnel", "sluzba": "professionnel ou scolaire", "sporocila": "messages", "sms": "SMS et RCS"},
    "it": {"osebno": "personale", "sluzba": "lavoro o istituto", "sporocila": "messaggi", "sms": "SMS e RCS"},
}

RAZLOGI = {
    "sl": {BREZ_SPLETA: "Nima spletne različice – samo aplikacija za računalnik.",
           WEBKIT_NI_PODPRT: "Spletna različica našega spletnega jedra ne podpira.",
           SAMO_RAZSIRITEV: "Na računalniku je samo kot razširitev za Chrome."},
    "en": {BREZ_SPLETA: "No web version – desktop app only.",
           WEBKIT_NI_PODPRT: "Its web version does not support our web engine.",
           SAMO_RAZSIRITEV: "On computers it is only a Chrome extension."},
    "de": {BREZ_SPLETA: "Keine Webversion – nur Desktop-App.",
           WEBKIT_NI_PODPRT: "Die Webversion unterstützt unsere Web-Engine nicht.",
           SAMO_RAZSIRITEV: "Am Computer nur als Chrome-Erweiterung."},
    "es": {BREZ_SPLETA: "Sin versión web: solo aplicación de escritorio.",
           WEBKIT_NI_PODPRT: "Su versión web no admite nuestro motor web.",
           SAMO_RAZSIRITEV: "En el ordenador solo existe como extensión de Chrome."},
    "fr": {BREZ_SPLETA: "Pas de version web : application de bureau uniquement.",
           WEBKIT_NI_PODPRT: "Sa version web ne prend pas en charge notre moteur web.",
           SAMO_RAZSIRITEV: "Sur ordinateur, seulement une extension Chrome."},
    "it": {BREZ_SPLETA: "Nessuna versione web: solo app per computer.",
           WEBKIT_NI_PODPRT: "La sua versione web non supporta il nostro motore web.",
           SAMO_RAZSIRITEV: "Sul computer è solo un’estensione di Chrome."},
}

JEZIKI = ("sl", "en", "de", "es", "fr", "it")
NAJDALJSI_NASLOV = 2048
NAJDALJSE_IME = 60
NAJVEC_KANALOV = 40


def po_id(kid: str):
    """Vnos izmerjenega kataloga; ce ga ni, neizmerjen vnos razsirjenega kataloga (core/katalog_storitev - podatki iz
    ferdium-recipes, brez kode). Leni uvoz: katalog_storitev uvozi ta modul."""
    vnos = next((k for k in KATALOG if k["id"] == kid), None)
    if vnos is None and kid:
        from core import katalog_storitev
        vnos = katalog_storitev.po_id(str(kid))
    return vnos


def vdelljiv(vnos: dict) -> bool:
    """Spletni odjemalec ali namizni program, ki se vstavi v Sporocila."""
    return bool((vnos or {}).get("splet") or (vnos or {}).get("program"))


def je_program(vnos: dict) -> bool:
    return bool((vnos or {}).get("program")) and not (vnos or {}).get("splet")


def ime(vnos: dict, jezik: str = "sl") -> str:
    """Ime za vmesnik: lastno ime + preveden pripis (npr. »Microsoft Teams (osebni)«)."""
    osnova = str((vnos or {}).get("ime") or "")
    pripis = (vnos or {}).get("pripis")
    if not pripis:
        return osnova
    j = jezik if jezik in PRIPISI else "en"
    return "%s (%s)" % (osnova, PRIPISI[j].get(pripis, pripis))


def za_vmesnik(jezik: str = "sl") -> list:
    """Katalog za vmesnik: z imenom v jeziku in razlogom, zakaj storitve ni mogoce vdelati."""
    j = jezik if jezik in RAZLOGI else "en"
    izid = []
    for k in KATALOG:
        v = dict(k)
        v["ime"] = ime(k, j)
        v["razlog"] = RAZLOGI[j].get(k.get("razlog", ""), "") if not vdelljiv(k) else ""
        izid.append(v)
    return izid


# ---------------------------------------------------------------------------------------------- neprebrano iz naslova
#: Locila, ki locijo dele naslova strani (»Inbox (5) - ime@… - Gmail«, »(2) Chat | Microsoft Teams«).
_LOCILO = re.compile(r"\s[-–—|·•:]\s")
#: Stevilo s tisocicami (»1 234«, »1\u00a0234«, »1.234«, »1,234«, »1'234«) ali do pet stevk brez locil.
_STEVILO = r"(\d{1,3}(?:[ \u00a0\u202f.,'’]\d{3})+|\d{1,5})"
_SPREDAJ_OKLEPAJ = re.compile(r"^\s*[(\[]\s*" + _STEVILO + r"\s*\+?\s*[)\]]")
_SPREDAJ_STEVILO = re.compile(r"^\s*(\d{1,5})\+?\s*[-–—|·•:]\s")
_V_DELU_OKLEPAJ = re.compile(r"[(\[]\s*(\d{1,3}(?:[ \u00a0\u202f.,'’]\d{3})+|\d{1,3})\s*\+?\s*[)\]]")
_OZNAKA_BREZ_STEVILA = re.compile(r"^\s*(?:[*•●!]\s|[(\[]\s*[*•●!]\s*[)\]])")
NAJVEC_NEPREBRANIH = 9999


def _v_stevilo(besedilo: str) -> int:
    return int(re.sub(r"\D", "", besedilo))


def neprebrano(naslov) -> int:
    """Stevilo neprebranih iz naslova strani (document.title) - splosno za vse spletne aplikacije, brez znanja o
    posamezni storitvi. Pravila po vrsti:
      1. stevilo v oklepaju na zacetku: »(3) WhatsApp«, »[12] Element«, »(99+) …«, tudi s tisocicami »(1 234) …«
         (presledek, trdi presledek, pika, vejica, opuscaj - FreshRSS v naslov pise trdi presledek);
      2. stevilo na zacetku, ki mu sledi locilo: »4 · Klepet«, »7 - Posta«;
      3. stevilo v oklepaju v PRVEM delu naslova (do locila » - «, » | « …): »Inbox (5) - … - Gmail«, »Klepet (2)«
         - najvec tri stevke, da letnica v imenu sobe (»Srečanje (2026)«) ni stevilo sporocil;
      4. oznaka brez stevila na zacetku (»* Slack«, »• …«, »! …«, tudi v oklepaju »(•) …«, »(*) …«) pomeni vsaj eno
         neprebrano;
    sicer 0 (naslov brez vzorca = ni neprebranih)."""
    s = str(naslov or "").strip()
    if not s:
        return 0
    for vzorec in (_SPREDAJ_OKLEPAJ, _SPREDAJ_STEVILO):
        m = vzorec.match(s)
        if m:
            return min(_v_stevilo(m.group(1)), NAJVEC_NEPREBRANIH)
    prvi = _LOCILO.split(s, 1)[0]
    m = _V_DELU_OKLEPAJ.search(prvi)
    if m:
        return min(_v_stevilo(m.group(1)), NAJVEC_NEPREBRANIH)
    if _OZNAKA_BREZ_STEVILA.match(s):
        return 1
    return 0


# ---------------------------------------------------------------------------------------------- lasten naslov
class NeveljavenNaslov(ValueError):
    """Koda napake v args[0]: prazno, https, poverilnice, gostitelj, dolzina."""


_DOVOLJEN_GOSTITELJ = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$")


def preveri_naslov(naslov) -> str:
    """Lasten klepet (Mattermost, Rocket.Chat, Zulip, lasten Element …): samo https, brez uporabniskega imena ali gesla
    v naslovu (»https://ime:geslo@…« bi geslo shranil v nastavitve in ga pokazal v vmesniku), z veljavnim gostiteljem.
    Vrne poenoten naslov ali sprozi NeveljavenNaslov s kodo."""
    s = str(naslov or "").strip()
    if not s:
        raise NeveljavenNaslov("prazno")
    if len(s) > NAJDALJSI_NASLOV:
        raise NeveljavenNaslov("dolzina")
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in s):
        raise NeveljavenNaslov("gostitelj")
    if "://" not in s:
        shema = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", s)
        if shema and not s[shema.end():shema.end() + 1].isdigit():
            raise NeveljavenNaslov("https")     # javascript:, data:, mailto: ... (gostitelj:vrata ostane naslov)
        s = "https://" + s
    try:
        d = urllib.parse.urlsplit(s)
        vrata = d.port
    except ValueError:
        raise NeveljavenNaslov("gostitelj") from None
    if d.scheme.lower() != "https":
        raise NeveljavenNaslov("https")
    if d.username is not None or d.password is not None or "@" in d.netloc:
        raise NeveljavenNaslov("poverilnice")
    gost = (d.hostname or "").rstrip(".").lower()
    if not gost:
        raise NeveljavenNaslov("gostitelj")
    try:
        ipaddress.ip_address(gost)
    except ValueError:
        try:
            gost = gost.encode("idna").decode("ascii")
        except UnicodeError:
            raise NeveljavenNaslov("gostitelj") from None
        if not _DOVOLJEN_GOSTITELJ.match(gost):
            raise NeveljavenNaslov("gostitelj")
    else:
        if ":" in gost:
            gost = "[" + gost + "]"
    netloc = gost + (":%d" % vrata if vrata else "")
    return urllib.parse.urlunsplit(("https", netloc, d.path or "/", d.query, d.fragment))


def ista_stran(trenutni: str, kanal: str) -> bool:
    """Trenutni naslov kanala je na gostitelju kanala (https, isti gostitelj): prijava je koncana. Gmail med prijavo
    pokaze accounts.google.com (drug gostitelj) in se po njej vrne na mail.google.com."""
    try:
        a, b = urllib.parse.urlsplit(str(trenutni or "")), urllib.parse.urlsplit(str(kanal or ""))
    except ValueError:
        return False
    return a.scheme == "https" and bool(a.hostname) and (a.hostname or "").lower() == (b.hostname or "").lower()


def ime_iz_naslova(naslov: str) -> str:
    gost = (urllib.parse.urlsplit(str(naslov or "")).hostname or "").lower()
    return gost[4:] if gost.startswith("www.") else gost


def preseli_naslov(naslov: str) -> str:
    """Shranjen naslov ukinjene storitve -> njen novi naslov (PRESELJENI); drugace nespremenjen."""
    try:
        gost = (urllib.parse.urlsplit(str(naslov or "")).hostname or "").lower()
    except ValueError:
        return str(naslov or "")
    return PRESELJENI.get(gost, str(naslov or ""))


# ---------------------------------------------------------------------------------------------- shramba kanalov
class Kanali:
    """Vdelani kanali v Sporocilih: [{id, katalog, ime, url, vklopljen}] v nastavitvah Spleta (ConfigManager - ista
    shramba kot prijave Spleta). `shramba` je predmet z get(kljuc, privzeto) in set(kljuc, vrednost)."""

    KLJUC = "sporocila_spletni_klepeti"

    def __init__(self, shramba) -> None:
        self.shramba = shramba

    def seznam(self) -> list:
        surovo = self.shramba.get(self.KLJUC, []) or []
        izid, videni, spremenjeno = [], set(), False
        for k in surovo if isinstance(surovo, list) else []:
            if not isinstance(k, dict) or not k.get("id") or k.get("id") in videni:
                spremenjeno = True
                continue
            vnos = po_id(str(k.get("katalog") or ""))
            if je_program(vnos):
                nov = ""
            else:
                url = str(k.get("url") or "")
                nov = preseli_naslov(url)
                if nov != url:
                    spremenjeno = True
                try:
                    nov = preveri_naslov(nov)
                except NeveljavenNaslov:
                    spremenjeno = True
                    continue
            videni.add(k["id"])
            izid.append({"id": str(k["id"]), "katalog": str(k.get("katalog") or ""),
                         "ime": str(k.get("ime") or ime_iz_naslova(nov) or (vnos or {}).get("ime", ""))[:NAJDALJSE_IME],
                         "url": nov, "pot": str(k.get("pot") or "") if je_program(vnos) else "",
                         "vklopljen": k.get("vklopljen", True) is not False,
                         "neprebrano": max(0, min(int(k.get("neprebrano") or 0), NAJVEC_NEPREBRANIH))
                         if str(k.get("neprebrano") or "0").isdigit() else 0,
                         # Dodan, a se ne v uporabi (prijava ni koncana): »Preklici dodajanje« ga odstrani.
                         "caka": k.get("caka") is True})
        if spremenjeno:
            self._shrani(izid)
        return izid

    def _shrani(self, seznam: list) -> None:
        self.shramba.set(self.KLJUC, [dict(k) for k in seznam][:NAJVEC_KANALOV])

    def najdi(self, kid: str):
        return next((k for k in self.seznam() if k["id"] == str(kid)), None)

    def dodaj(self, katalog: str = "", url: str = "", ime_kanala: str = "", jezik: str = "sl", pot: str = "") -> dict:
        """Iz kataloga (katalog = id) ali lasten naslov (url). Vrne nov kanal (vklopljen). pot: izvrsljiva datoteka
        namiznega programa, ki jo je izbral uporabnik (AppImage drugje kot v obicajnih mapah)."""
        seznam = self.seznam()
        if len(seznam) >= NAJVEC_KANALOV:
            raise ValueError("najvec")
        if katalog:
            vnos = po_id(katalog)
            if vnos is None or not vdelljiv(vnos):
                raise ValueError("katalog")
            naslov, privzeto_ime = vnos.get("splet", ""), ime(vnos, jezik)
        else:
            naslov = preveri_naslov(url)
            privzeto_ime = ime_iz_naslova(naslov)
        kid = katalog if katalog and all(k["id"] != katalog for k in seznam) else "k-" + uuid.uuid4().hex[:10]
        kanal = {"id": kid, "katalog": katalog, "ime": (str(ime_kanala or "").strip() or privzeto_ime)[:NAJDALJSE_IME],
                 "url": naslov, "pot": str(pot or "") if je_program(po_id(katalog)) else "", "vklopljen": True,
                 "neprebrano": 0, "caka": True}
        self._shrani(seznam + [kanal])
        return kanal

    def odstrani(self, kid: str) -> bool:
        seznam = self.seznam()
        nov = [k for k in seznam if k["id"] != str(kid)]
        self._shrani(nov)
        return len(nov) != len(seznam)

    def preimenuj(self, kid: str, novo: str) -> dict:
        novo = " ".join(str(novo or "").split())[:NAJDALJSE_IME]
        if not novo:
            raise ValueError("ime")
        return self._spremeni(kid, ime=novo)

    def vklopi(self, kid: str, vklopljen: bool) -> dict:
        return self._spremeni(kid, vklopljen=bool(vklopljen))

    def potrdi(self, kid: str) -> bool:
        """Kanal je v uporabi (prijava koncana): ni vec »caka«. True, ce se je spremenilo."""
        k = self.najdi(kid)
        if k is None or not k.get("caka"):
            return False
        self._spremeni(kid, caka=False)
        return True

    def zapomni_neprebrano(self, kid: str, n: int) -> bool:
        """Zadnje znano stevilo neprebranih (znacka na namizju ga pokaze ob zagonu, se preden se kanal nalozi).
        True, ce se je spremenilo (pise se samo ob spremembi)."""
        n = max(0, min(int(n or 0), NAJVEC_NEPREBRANIH))
        k = self.najdi(kid)
        if k is None or k.get("neprebrano", 0) == n:
            return False
        self._spremeni(kid, neprebrano=n)
        return True

    def _spremeni(self, kid: str, **polja) -> dict:
        seznam = self.seznam()
        k = next((x for x in seznam if x["id"] == str(kid)), None)
        if k is None:
            raise KeyError(kid)
        k.update(polja)
        self._shrani(seznam)
        return dict(k)

    def premakni(self, kid: str, smer: int) -> list:
        """Premik za eno mesto gor (-1) ali dol (+1)."""
        seznam = self.seznam()
        i = next((n for n, k in enumerate(seznam) if k["id"] == str(kid)), -1)
        j = i + (1 if int(smer) > 0 else -1)
        if i < 0 or not 0 <= j < len(seznam):
            return seznam
        seznam[i], seznam[j] = seznam[j], seznam[i]
        self._shrani(seznam)
        return seznam


# ---------------------------------------------------------------------------------------------- stranska plosca brskalnika
IKONA = {KLEPET: "💬", POSTA: "✉️"}


def integracije(jezik: str = "sl") -> dict:
    """Vdeljive storitve kataloga kot vnosi stranske plosce brskalnika (core/config.py »integrations«); privzeto
    izklopljene - uporabnik jih vklopi v nastavitvah plosce."""
    return {k["id"]: {"name": ime(k, jezik), "url": k["splet"], "icon": IKONA.get(k["vrsta"], "🌐"), "enabled": False,
                      "color": "#00d2ff", "katalog": k["id"]}
            for k in KATALOG if k.get("splet")}


def preseli_integracije(integracije_uporabnika: dict) -> bool:
    """Naslove ukinjenih storitev v stranski plosci preseli na nove (PRESELJENI). True, ce je bilo kaj spremenjeno."""
    spremenjeno = False
    for v in (integracije_uporabnika or {}).values():
        if isinstance(v, dict) and v.get("url"):
            nov = preseli_naslov(v["url"])
            if nov != v["url"]:
                v["url"] = nov
                spremenjeno = True
    return spremenjeno
