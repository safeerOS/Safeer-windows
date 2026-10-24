"""Povezava z domacim Safeer Hubom za linuxov brskalnik.

Brez zunanjih knjiznic: paket safeer-browser zahteva samo GTK in WebKit, zato bi
vsaka nova odvisnost otezila namestitev in flatpak. WebSocket je zato napisan tu,
s standardno knjiznico -- gre za majhen del protokola RFC 6455 (besedilni okvirji,
maskiranje, ping/pong, zapiranje).

Vse ostalo (seznanitev, vstopnica, odkrivanje) je navaden HTTP prek urllib.

Nacela so ista kot v Androidu:
 - brskalnik deluje brez Huba; ce ga ni, se ne zgodi nic,
 - zeton naprave ostane v datoteki z dovoljenji 0600 in nikoli ne gre v stran,
 - povezava se odpre sele z enokratno vstopnico.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import ssl
import struct
import threading
import time
import sys
import urllib.error
import urllib.request
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from core import link_krog, link_spremembe, link_tls, link_vticnik, spake2

# Kaj ta racunalnik pove srediscu: Windows in Linux imata isto kodo, platforma pa mora biti prava
# (Windows se je predstavljal kot "linux").
PLATFORMA = "windows" if sys.platform.startswith("win") else "linux"

PRIVZETA_VRATA = 8990
# Uporabnik naj vidi kratko domace ime, ne naslova IP. Staro ime ostane takoj za njim,
# ker ga imajo ze seznanjene naprave shranjeno in jim ne sme nic odpasti.
PRIVZETI_GOSTITELJ = "safeer.local"
STARO_IME_GOSTITELJA = "safeer-hub.local"
POT_VSTOPNICE = "/cast/ticket"
POT_WS = "/cast/ws"
POT_ZDRAVJA = "/cast/health"

# Zgornja meja sporocila s Huba. Brez nje lahko streznik (ali kdor se zanj izdaja)
# napove 4 GiB in nam napolni pomnilnik.
NAJVECJE_SPOROCILO = 1024 * 1024

# Koliko tisine prenesemo, preden povezavo razglasimo za mrtvo. Sami posiljamo
# ping pogosteje od tega, zato tisina pomeni, da Huba res ni vec.
BRALNI_TIMEOUT = 70.0
SONDA_VSAKIH_UTRIPOV = 4          # vsak 4. ping (~100 s) preveri, da smo na hubu se prijavljeni
DOKAZ_KLJUCA_NAJVEC_NA_S = 60.0   # dogovor zascite z napravo, s katero nimamo seje: najvec en poskus na minuto
# Seznam naprav pise sredisce. Z dolgim seznamom ali z veliko oznakami iste naprave (isto jedro, izmisljene pripone) ne
# sme sproziti veliko podpisov s kljucem naprave na bralni niti (drugi neodvisni pregled, 7. 10. 2026).
# Zmoznosti si zapomnimo za VSE clane kroga v seznamu (lastnik, 18. 10. 2026: prej prvih 512 - v vecjem krogu naprava
# cez mejo ni bila znana kot naprava z zascito in ukaz bi sel nezascito). Tuje oznake (ne iz nasega kroga - te si
# sredisce lahko izmisli) samo do te meje.
NAJVEC_NAPRAV_V_SEZNAMU = 512
NAJVEC_DOKAZOV_NA_SEZNAM = 16     # najvec dogovorov zascite, ki jih sprozi en seznam naprav
NAJVEC_DOKAZOV_NA_JEDRO = 4       # najvec dogovorov na minuto z oznakami ene naprave (jedra)
# Zapisov o zadnjem poskusu dokaza ne omejuje stevilka: nastanejo samo za clane kroga (pozna_kljuc), najvec
# NAJVEC_DOKAZOV_NA_JEDRO na minuto na napravo, in izpadejo po 10 minutah (prej meja 512).
VPRASANJE_VELJA_S = 300.0         # kako dolgo za zasciten ukaz pricakujemo odgovor iz iste seje (ukazi potecejo prej)
# Oznaka sporocila (id, ref_id) je kratka (nasi programi: do ~50 znakov). Daljse ne sprejmemo: odgovor ali potrditev
# oznako ukaza ponovi, z zelo dolgo pa je naprava brez pravic polnila pomnilnik prejemnika (cetrti pregled, 7. 10. 2026).
NAJVEC_OZNAKE_SPOROCILA = 128
NAJVEC_VPRASANJ = 4096
#: Ukazi, ki so sli zasciteni: oznaka ukaza -> (oznaka naprave, ki smo jo vprasali, kdaj). Skupno vsem povezavam tega
#: programa: zapis mora preziveti ponovno povezavo s srediscem (nov objekt Povezava), sicer bi nezasciten odgovor na
#: se cakajoc ukaz spet veljal. Glej Povezava.velja_odgovor.
_VPRASANJA: Dict[str, Tuple[str, float]] = {}
_ZAKLEP_VPRASANJ = threading.Lock()
SONDA_PREDPONA = "sonda-prijave-"
PING_VSAKIH = 25.0
ZAMIKI_PONOVNEGA_POSKUSA = (2.0, 5.0, 10.0, 20.0, 40.0, 60.0)
# Koliko zamude pri utripu ze pomeni, da je racunalnik spal (pokrov zaprt, pripravljenost).
# Po prebujenju je vticnica praviloma mrtva, a tega ne pove nihce: pisanje se zatakne, branje
# caka do BRALNI_TIMEOUT. Zato jo takrat zapremo sami in se povezemo znova.
SKOK_UTRIPA = 20.0

NASTAVITVE_MAPA = os.path.expanduser("~/.config/safeer-browser")
NASTAVITVE_POT = os.path.join(NASTAVITVE_MAPA, "link.json")


# ----------------------------------------------------------------------
# Nastavitve naprave
# ----------------------------------------------------------------------

def _ime_naprave() -> str:
    try:
        return socket.gethostname() or "racunalnik"
    except Exception:
        return "racunalnik"


def stari_id_naprave() -> str:
    """Id po imenu racunalnika (`pc-<ime>`), kot je veljal pred prehodom na id iz kljuca."""
    ime = _ime_naprave().split(".")[0].lower()
    cisto = "".join(z if (z.isalnum() or z in "-_") else "-" for z in ime)
    return "pc-" + (cisto or "safeer")


_id_iz_kljuca: Optional[str] = None


def id_naprave() -> str:
    """Id te naprave: iz njenega kljuca (`n-<16 hex>`, link_krog.id_iz_kljuca) - isti na vseh hubih in po
    menjavi huba; Control doda pripono `-control`. Stari `pc-<ime>` ostane v krogih kot alias: hub ga ob prvi
    prijavi s podpisom sam poveze z novim. Ce kljuca ni mogoce dobiti, ostane stari id."""
    global _id_iz_kljuca
    if _id_iz_kljuca:
        return _id_iz_kljuca
    try:
        _id_iz_kljuca = link_krog.id_iz_kljuca(link_krog.javni_kljuc_b64())
        return _id_iz_kljuca
    except Exception:
        return stari_id_naprave()


def je_id_iz_kljuca(device_id: str) -> bool:
    return link_krog.je_id_iz_kljuca(device_id)


class Nastavitve:
    """Majhna shramba ob brskalniku. Zeton je dostopen samo uporabniku (0600)."""

    def __init__(self, pot: str = NASTAVITVE_POT) -> None:
        self.pot = pot
        self.podatki: Dict[str, object] = {}
        self.nalozi()

    def nalozi(self) -> None:
        try:
            with open(self.pot, "r", encoding="utf-8") as d:
                self.podatki = json.load(d)
        except Exception:
            self.podatki = {}

    naloži = nalozi  # staro ime s sumnikom; jedro uporablja ASCII

    def shrani(self) -> None:
        # Zeton Huba in zetoni seznanitev: datoteka 0600 ze ob nastanku (prej po umask 0644, chmod sele po zapisu) in
        # mapa 0700; ob napaki zacasna datoteka ne ostane (neodvisni pregled, 19. 10. 2026).
        zacasna = self.pot + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.pot), mode=0o700, exist_ok=True)
            # Modul je skupen z Windows: tam O_NOFOLLOW ni, os.fchmod pa pred Pythonom 3.13 tudi ne. AttributeError je
            # prej tiho koncal shranjevanje in link.json se ni nikoli zapisal - seznanitev se je izgubila.
            fd = os.open(zacasna, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with open(fd, "w", encoding="utf-8") as d:
                if hasattr(os, "fchmod"):
                    os.fchmod(d.fileno(), 0o600)   # zacasna, ki je ostala od prej, je imela lahko druge pravice
                json.dump(self.podatki, d, ensure_ascii=False, indent=2)
            os.replace(zacasna, self.pot)
        except Exception:
            try:
                os.unlink(zacasna)
            except OSError:
                pass

    def get(self, kljuc: str, privzeto=None):
        return self.podatki.get(kljuc, privzeto)

    def set(self, kljuc: str, vrednost) -> None:
        self.podatki[kljuc] = vrednost
        self.shrani()


# ----------------------------------------------------------------------
# Odkrivanje in seznanitev (navaden HTTP)
# ----------------------------------------------------------------------

def _osnova(naslov: str) -> str:
    """Iz ws:// ali http:// naredi osnovo http://gostitelj:vrata."""
    u = urlparse(naslov)
    shema = "https" if u.scheme in ("wss", "https") else "http"
    gostitelj = u.netloc or u.path
    return f"{shema}://{gostitelj}"


def _zahteva(url: str, telo: Optional[dict] = None, zeton: Optional[str] = None,
             timeout: float = 5.0, odtis: Optional[str] = None) -> Tuple[int, dict]:
    """HTTP(S) do Huba. Pri https preveri odtis potrdila (None = se ne poznamo, samo
    med odkrivanjem in seznanitvijo); zeton gre samo po https (glej link_tls)."""
    koda, odgovor, _ = link_tls.zahteva(url, telo, zeton, timeout, pripeti=odtis)
    return koda, odgovor


def _poisci_z_mdns(cas: float = 1.5) -> Optional[str]:
    """Prvi Hub prek mDNS (TLS ima prednost) ali None."""
    hubi = poisci_hube_mdns(cas)
    return hubi[0]["naslov"] if hubi else None


def poisci_hube_mdns(cas: float = 2.0) -> List[dict]:
    """Vsi Hubi, ki se oglasajo prek mDNS: [{"naslov", "fp", "tls", "ime"}], TLS najprej.

    Knjiznica zeroconf NI obvezna: paket safeer-browser ostaja odvisen samo od GTK in WebKita.
    Ce je ni, vrnemo prazen seznam in odkrivanje gre po HTTP poti. V hisi je lahko vec Hubov
    (televizor, telefon, racunalnik); odtis potrdila (fp) pove, kateri je kateri.
    """
    try:
        from zeroconf import ServiceBrowser, ServiceListener, Zeroconf  # type: ignore
    except Exception:
        return []

    najdeno: List[dict] = []

    class Poslusalec(ServiceListener):  # type: ignore[misc]
        def add_service(self, zc, vrsta, ime):
            try:
                info = zc.get_service_info(vrsta, ime, timeout=1000)
            except Exception:
                return
            if info is None:
                return
            naslovi = []
            try:
                naslovi = info.parsed_addresses()
            except Exception:
                pass
            if not naslovi:
                return
            lastnosti = info.properties or {}
            pot = lastnosti.get(b"ws") or lastnosti.get("ws") or POT_WS.encode()
            if isinstance(pot, bytes):
                pot = pot.decode("utf-8", "replace")
            # Hub s TLS oglasi tls=1; povezava je potem wss/https. Odtis v oglasu je
            # samo informativen - zaupanje vzpostavi seznanitev, ne mDNS.
            tls = lastnosti.get(b"tls") or lastnosti.get("tls") or b""
            if isinstance(tls, bytes):
                tls = tls.decode("utf-8", "replace")
            shema = "wss" if str(tls) == "1" else "ws"
            fp = lastnosti.get(b"fp") or lastnosti.get("fp") or b""
            if isinstance(fp, bytes):
                fp = fp.decode("utf-8", "replace")
            ime_h = lastnosti.get(b"name") or lastnosti.get("name") or b""
            if isinstance(ime_h, bytes):
                ime_h = ime_h.decode("utf-8", "replace")
            # Izvolitev huba: id in prioriteta iz oglasa (IzvolitevHuba na Androidu).
            id_h = lastnosti.get(b"id") or lastnosti.get("id") or b""
            if isinstance(id_h, bytes):
                id_h = id_h.decode("utf-8", "replace")
            prio = lastnosti.get(b"prio") or lastnosti.get("prio") or b""
            if isinstance(prio, bytes):
                prio = prio.decode("utf-8", "replace")
            try:
                prio = max(0, min(1000, int(str(prio).strip())))
            except ValueError:
                prio = 0     # starejsi hub brez prioritete steje kot najnizja (kot na Androidu)
            mesh = lastnosti.get(b"mesh") or lastnosti.get("mesh") or b""
            if isinstance(mesh, bytes):
                mesh = mesh.decode("utf-8", "replace")
            naslov = f"{shema}://{naslovi[0]}:{info.port}{pot}"
            if all(n["naslov"] != naslov for n in najdeno):
                najdeno.append({"naslov": naslov, "fp": str(fp).lower(), "tls": str(tls) == "1", "ime": str(ime_h),
                                "id": str(id_h), "prio": prio, "mesh": str(mesh)})

        def update_service(self, zc, vrsta, ime):
            pass

        def remove_service(self, zc, vrsta, ime):
            pass

    zc = None
    brskalnik = None
    try:
        zc = Zeroconf()
        brskalnik = ServiceBrowser(zc, "_safeercast._tcp.local.", Poslusalec())
        konec = time.time() + cas
        # Pocakamo cel cas: vec Hubov se oglasa vsak ob svojem casu, izbrati hocemo pravega.
        while time.time() < konec:
            time.sleep(0.1)
    except Exception:
        return []
    finally:
        # Brskalnik ima svojo nit, ki je zc.close() NE ustavi (zeroconf 0.151): brez cancel() je vsako iskanje
        # pustilo eno nit za vedno - Control, ki isce sosede vsakih 15 s, jih je v enem dnevu nabral vec tisoc.
        if brskalnik is not None:
            try:
                brskalnik.cancel()
            except Exception:
                pass
        if zc is not None:
            try:
                zc.close()
            except Exception:
                pass

    return sorted(najdeno, key=lambda n: (not n["tls"], n["naslov"]))


def je_hub(osnova: str, timeout: float = 2.0, odtis: Optional[str] = None) -> bool:
    """Ali na tem naslovu res odgovarja Safeer Hub?

    Ne zadosca, da se nekaj oglasi: na istih vratih je lahko cisto drug streznik.
    Preverimo zato dvoje, kar zna samo Hub:
      - /cast/health vrne 200 ali 401 (zahteva zeton), nikoli 404,
      - /cast/ticket obstaja, a ne kot GET (Hub odgovori 405 ali 401).
    Zetona pri tem ne posiljamo -- to je preverba pred zaupanjem, ne po njem.
    """
    koda, _ = _zahteva(osnova + POT_ZDRAVJA, timeout=timeout, odtis=odtis)
    if koda not in (200, 401, 403):
        return False
    koda_vstopnice, _ = _zahteva(osnova + POT_VSTOPNICE, timeout=timeout, odtis=odtis)
    if koda_vstopnice in (0, 404):
        return False
    return True


def poisci_hub(znani: str = "", odtis: Optional[str] = None) -> Optional[str]:
    """Vrne naslov WebSocketa Huba ali None.

    Vrstni red je vprasanje zaupanja, ne udobja. Zadnji znani (torej ze potrjeni)
    Hub je vedno prvi: dokler se oglasa, ne pogledamo nikamor drugam. Sele ko ga ni,
    poskusimo mDNS in privzeta imena -- ta so nepreverjena, zato jih klicatelj, ce
    ima zeton, ne sme kar sprejeti (glej `naslov_je_isti`).
    """
    kandidati: List[str] = []
    if znani:
        kandidati.append(_osnova(znani))

    z_mdns = _poisci_z_mdns()
    if z_mdns:
        kandidati.append(_osnova(z_mdns))

    # Najprej TLS (nov Hub), nato se navaden http, da starejsega Huba vsaj najdemo in
    # uporabniku povemo, naj ga posodobi.
    for ime in (PRIVZETI_GOSTITELJ, STARO_IME_GOSTITELJA, "127.0.0.1"):
        kandidati.append(f"https://{ime}:{PRIVZETA_VRATA}")
        kandidati.append(f"http://{ime}:{PRIVZETA_VRATA}")

    videni = set()
    for osnova in kandidati:
        if osnova in videni:
            continue
        videni.add(osnova)
        # Odtis velja samo za ze potrjeni Hub; neznane kandidate preverimo brez njega
        # (zaupanja jim s tem se ne damo - to naredi sele seznanitev).
        pripeti = odtis if (znani and osnova == _osnova(znani)) else None
        if je_hub(osnova, odtis=pripeti):
            shema, gostitelj = osnova.split("://", 1)
            return f"{'wss' if shema == 'https' else 'ws'}://{gostitelj}{POT_WS}"
    return None


def poisci_hub_z_odtisom(znani: str = "", odtis: Optional[str] = None, seznanjeni: tuple = ()) -> Optional[dict]:
    """Kot poisci_hub, a vrne {"naslov", "fp", "isti", "krog", "id"}: isti = to je Hub, s katerim smo seznanjeni
    (isti naslov, ki se oglasa, ali isti odtis potrdila na drugem naslovu). Med vec Hubi ima
    prednost tisti z nasim odtisom, nato hub, ki je clan kroga zaupanja (krog=True: njegovo potrdilo
    nosi kljuc iz kroga, zato mu zaupamo brez seznanitve - prijava gre s podpisom), nato TLS Hubi po vrsti.
    `seznanjeni`: odtisi Hubov, s katerimi je ta naprava ze seznanjena (ima zeton). Imajo prednost pred izvoljenim
    hubom kroga: nezaupan racunalnik se je 11. 10. 2026 preselil na hub telefona, kjer zetona nima, in ostal na
    prijavnem oknu, ceprav je bil televizor, s katerim je bil seznanjen, dosegljiv.
    """
    if znani:
        osnova = _osnova(znani)
        if je_hub(osnova, odtis=odtis):
            return {"naslov": znani if znani.startswith("wss://") else f"wss://{osnova.split('://', 1)[1]}{POT_WS}",
                    "fp": odtis or "", "isti": True}
    hubi = [h for h in poisci_hube_mdns() if h["tls"]]
    if odtis:
        for h in hubi:
            if link_tls.isti(h["fp"], odtis) and je_hub(_osnova(h["naslov"]), odtis=odtis):
                return {"naslov": h["naslov"], "fp": h["fp"], "isti": True}
    znani_odtisi = {str(o).lower() for o in seznanjeni if o}
    for h in hubi:
        if h["fp"] in znani_odtisi and je_hub(_osnova(h["naslov"]), odtis=h["fp"]):
            return {"naslov": h["naslov"], "fp": h["fp"], "isti": False}
    # Izvoljeni hub (drug clan kroga zaupanja): oglas mDNS ne dobi zaupanja; da ga sele kljuc v
    # potrdilu, ki se ujema s kljucem tega clana v krogu.
    try:
        krog = link_krog.krog()
    except Exception:
        krog = None
    for h in hubi:
        clan = krog.clan(h.get("id") or "") if (krog and h.get("id")) else None
        if clan is None:
            continue
        videni, kljuc = link_tls.potrdilo_huba(h["naslov"])
        if videni and link_tls.isti(kljuc, clan["kljuc"]) and je_hub(_osnova(h["naslov"]), odtis=videni):
            return {"naslov": h["naslov"], "fp": videni, "isti": False, "krog": True, "id": h["id"]}
    for h in hubi:
        if je_hub(_osnova(h["naslov"])):
            return {"naslov": h["naslov"], "fp": h["fp"], "isti": False}
    # Brez zeroconfa: privzeta imena (samo TLS).
    for ime in (PRIVZETI_GOSTITELJ, STARO_IME_GOSTITELJA):
        osnova = f"https://{ime}:{PRIVZETA_VRATA}"
        if je_hub(osnova):
            return {"naslov": f"wss://{ime}:{PRIVZETA_VRATA}{POT_WS}", "fp": "", "isti": False}
    return None


# Imeni, pod katerima se javlja isti nas Hub. Preimenovanje ne sme nikogar odklopiti.
IMENA_HUBA = (PRIVZETI_GOSTITELJ, STARO_IME_GOSTITELJA)


def naslov_je_isti(a: str, b: str) -> bool:
    """Ali gre za isti Hub? Primerjamo gostitelja in vrata, ne sheme ne poti.

    Nasi dve imeni (safeer.local in staro safeer-hub.local) stejeta za isti Hub --
    sicer bi preimenovanje vsem napravam javilo, da se je Hub preselil.
    """
    if not a or not b:
        return False
    ua, ub = urlparse(_osnova(a)), urlparse(_osnova(b))
    ga, gb = (ua.hostname or "").lower(), (ub.hostname or "").lower()
    if ga in IMENA_HUBA and gb in IMENA_HUBA:
        ga = gb = IMENA_HUBA[0]
    return (ga, ua.port or PRIVZETA_VRATA) == (gb, ub.port or PRIVZETA_VRATA)


NACIN_SPAKE2 = "spake2"
IDENTITETA_HUBA = "safeer-link-hub"
#: Sredisce seznanitve (koda, QR) ne izda zetona za id, ki je ze v krogu (link_hub_streznik.Hub._id_ze_v_krogu, 409).
ID_ZASEDEN = "id_zaseden"


def _id_zaseden(koda: int, odgovor) -> bool:
    return koda == 409 and isinstance(odgovor, dict) and \
        ID_ZASEDEN in (str(odgovor.get("code") or ""), str(odgovor.get("error_code") or ""))


def zacni_seznanitev(ws_naslov: str, device_id: str, ime: str) -> Optional[dict]:
    """Odpre prijavo na Hubu. Vrne {"pair_id", "nacin", "hub_id", "odtis"}, {"napaka": ...} ali None.

    Samo prek TLS: odtis potrdila, ki ga vidimo zdaj, se vplete v seznanitev, zato ga
    napadalec v sredini ne more zamenjati, ne da bi seznanitev padla. Kode Hub ne
    poslje in je od nas ne dobi - pokaze jo na svojem zaslonu, uporabnik jo vtipka tu.
    """
    osnova = _osnova(ws_naslov)
    if not osnova.startswith("https://"):
        return {"napaka": "hub_brez_tls"}
    koda, odgovor, videni = link_tls.zahteva(osnova + "/cast/pair/start",
                                             {"device_id": device_id, "name": ime})
    if koda == 429 and str(odgovor.get("code") or "") == "seznanitev_zaprta":
        # Sredisce je povezovanje s kodo zaprlo (nekdo je ugibal kodo): uporabniku povemo, kaj naj naredi.
        return {"napaka": "seznanitev_zaprta"}
    if _id_zaseden(koda, odgovor):
        return {"napaka": ID_ZASEDEN}
    if koda != 200 or not videni:
        return None
    pair_id = str(odgovor.get("pair_id", "") or "")
    if not pair_id:
        return None
    nacin = str(odgovor.get("nacin", "") or "")
    if nacin != NACIN_SPAKE2:
        # Starejsi Hub bi kodo prejel po omrezju. Ne sodelujemo; Hub naj se posodobi.
        return {"napaka": "hub_star", "nacin": nacin}
    return {
        "pair_id": pair_id,
        "nacin": nacin,
        "hub_id": str(odgovor.get("hub_id", "") or "") or IDENTITETA_HUBA,
        "odtis": videni,
    }


def potrdi_kodo(ws_naslov: str, prijava: dict, device_id: str, koda: str) -> Tuple[Optional[str], str]:
    """Dokaze Hubu, da poznamo kodo z njegovega zaslona (SPAKE2, RFC 9382), ne da bi
    jo poslali. Vrne (zeton, "") ob uspehu, sicer (None, razlog): napacna_koda,
    prevec_poskusov, prijava_ne_obstaja, povezava_ni_uspela, id_zaseden (naprava je ze v krogu).
    """
    osnova = _osnova(ws_naslov)
    odtis = str(prijava.get("odtis", "") or "")
    pair_id = str(prijava.get("pair_id", "") or "")
    hub_id = str(prijava.get("hub_id", "") or "") or IDENTITETA_HUBA
    vnos = "".join(z for z in str(koda) if z.isdigit())
    if not odtis or not pair_id or len(vnos) < 4:
        return None, "napacna_koda"
    s = spake2.Spake2.odjemalec(vnos, device_id, hub_id, odtis.encode("utf-8"), pair_id.encode("utf-8"))
    # Ves cas seznanitve govorimo z natanko tistim potrdilom, ki smo ga videli na zacetku.
    k1, o1 = _zahteva(osnova + "/cast/pair/spake",
                      {"pair_id": pair_id, "device_id": device_id, "pb": s.sporocilo().hex()},
                      odtis=odtis)
    if k1 != 200:
        return None, str(o1.get("code", "") or "") or "povezava_ni_uspela"
    try:
        pa = bytes.fromhex(str(o1.get("pa", "")))
        ca = bytes.fromhex(str(o1.get("ca", "")))
        _, cb = s.zakljuci(pa)
    except (ValueError, TypeError):
        return None, "povezava_ni_uspela"
    if not s.preveri(ca):
        # Hub ne pozna iste kode ali pa je vmes kdo z drugim potrdilom. Nase potrditve
        # mu ne posljemo; poskus pri njem vseeno steje.
        return None, "napacna_koda"
    k2, o2 = _zahteva(osnova + "/cast/pair/finish",
                      {"pair_id": pair_id, "device_id": device_id, "cb": cb.hex()},
                      odtis=odtis)
    zeton = o2.get("token")
    if k2 != 200 or not isinstance(zeton, str) or not zeton:
        return None, str(o2.get("code", "") or "") or "napacna_koda"
    return zeton, ""


# ----------------------------------------------------------------------
# Prijava s QR kodo (prijavno okno Safeer OS / Safeer Control)
# ----------------------------------------------------------------------

# Povezava v QR: kamera telefona jo odpre v Safeer (aplikacija jo prestreze) ali na strani safeer.si/p,
# ki ponudi »Odpri v Safeer«. Skrivnost je v delu za #, zato je streznik strani nikoli ne vidi.
QR_POVEZAVA = "https://safeer.si/p#i={qr_id}&s={skrivnost}&f={odtis}&a={naslov}"
# Cel odtis (64 znakov): naprava, ki kodo poskenira, potrdilo primerja v celoti. Prej je slo v kodo prvih 16 znakov -
# predpona je sibkejsa od enakosti, Android pa je zahteval cel odtis, zato se prijava s tako kodo ni koncala
# (zunanji pregled kode 8. 10. 2026).
QR_ODTIS_ZNAKOV = 64


def zacni_qr(ws_naslov: str, device_id: str, ime: str, platforma: str = PLATFORMA,
             koda: Optional[str] = None) -> Optional[dict]:
    """Odpre prijavo s QR kodo. Vrne {"qr_id", "odtis", "skrivnost", "prevzem", "naslov", "povezava", "velja"},
    {"napaka": ...} ali None, ce se hub ne oglasi.

    V QR gre skrivnost (hub dobi samo njen SHA-256), zacetek odtisa potrdila, ki ga vidimo zdaj, in
    naslov Huba, ki je kodo izdal - telefon se poveze neposredno nanj (peer-to-peer), ne na huba, ki
    mu je morda ze zaupal prej (ta je lahko medtem ze druga naprava). Vsiljivec v sredini kljub temu
    ne more dobiti potrditve, ker se mora odtis v QR ujemati z zivim potrdilom na tem istem naslovu.
    Za prevzem zetona je druga skrivnost, ki je v QR ni.
    """
    import hashlib
    import secrets
    osnova = _osnova(ws_naslov)
    if not osnova.startswith("https://"):
        return {"napaka": "hub_brez_tls"}
    skrivnost = secrets.token_hex(16)
    prevzem = secrets.token_hex(24)
    # Ista prijava ima se 6-mestno kodo te naprave: kdor nima kamere, jo vpise na napravi v Linku (»Vpiši kodo
    # z druge naprave«). Hub dobi samo njen SHA-256; dovoli jo lahko samo ze seznanjena naprava, Hub pa omeji
    # ugibanje (NAJVEC_KODA_NAPAK na minuto). Skrivnost QR ostane dolga - aplikacije na telefonu jo preverjajo.
    koda_naprave = koda if koda and len(koda) == 6 and koda.isdigit() else "%06d" % secrets.randbelow(1000000)
    koda, odgovor, videni = link_tls.zahteva(osnova + "/cast/pair/qr/start", {
        "device_id": device_id, "name": ime, "platform": platforma,
        "secret_sha256": hashlib.sha256(skrivnost.encode("utf-8")).hexdigest(), "poll_secret": prevzem,
        "code_sha256": hashlib.sha256(koda_naprave.encode("utf-8")).hexdigest()})
    if koda == 404 or koda == 405:
        return {"napaka": "hub_star"}
    if _id_zaseden(koda, odgovor):
        # Prej None (kot da sredisca ni): prijavno okno je kodo QR iskalo znova vsakih 8 s in pisalo »ni Safeer Linka«.
        return {"napaka": ID_ZASEDEN}
    if koda != 200 or not videni:
        if koda == 429:
            return {"napaka": "prevec_prijav"}
        return None
    qr_id = str(odgovor.get("qr_id", "") or "")
    if not qr_id:
        return None
    odtis = videni.lower()
    u = urlparse(ws_naslov)
    naslov = "%s:%d" % (u.hostname, u.port or 443)
    # Prijava na lastni Hub (wss://127.0.0.1): v QR gre naslov v domacem omrezju, ki ga sporoci Hub - sicer telefon
    # isce sredisce na samem sebi (testni racunalnik 12. 10. 2026: »Safeer Link se ne oglasi«, koda je delovala).
    domaci = str(odgovor.get("address") or "").strip()
    if u.hostname in ("127.0.0.1", "localhost", "::1") and ":" in domaci and not domaci.startswith("127."):
        naslov = domaci
    return {
        "qr_id": qr_id, "odtis": odtis, "skrivnost": skrivnost, "koda": koda_naprave, "prevzem": prevzem, "naslov": naslov,
        "povezava": QR_POVEZAVA.format(qr_id=qr_id, skrivnost=skrivnost, odtis=odtis[:QR_ODTIS_ZNAKOV], naslov=naslov),
        "velja": int(odgovor.get("expires_in_seconds", 300) or 300),
    }


def stanje_qr(ws_naslov: str, prijava: dict, device_id: str) -> Tuple[Optional[str], str]:
    """(zeton, "") ko je prijavo dovolil clan Safeer Linka; (None, "caka"), (None, "qr_ne_obstaja")
    ali (None, "povezava_ni_uspela"). Govorimo samo s potrdilom, ki smo ga videli ob zacetku."""
    koda, odgovor = _zahteva(_osnova(ws_naslov) + "/cast/pair/qr/status",
                             {"qr_id": prijava.get("qr_id", ""), "device_id": device_id,
                              "poll_secret": prijava.get("prevzem", "")}, odtis=prijava.get("odtis"))
    if koda == 404:
        return None, "qr_ne_obstaja"
    if koda != 200:
        return None, "povezava_ni_uspela"
    zeton = odgovor.get("token")
    if odgovor.get("approved") and isinstance(zeton, str) and zeton:
        return zeton, ""
    return None, "caka"


def ima_odprto_kodo(ws_naslov: str) -> Optional[bool]:
    """Ali to sredisce ravno kaze 6-mestno kodo povabila (»Poveži naprave«)? None: ne ve (star Hub, napaka)."""
    try:
        st, odgovor = _zahteva(_osnova(ws_naslov) + "/cast/pair/qr/odprto", {}, timeout=3.0)
    except Exception:
        return None
    if st != 200 or not isinstance(odgovor, dict) or "open" not in odgovor:
        return None
    return bool(odgovor.get("open"))


def odobri_kodo(ws_naslov: str, zeton: str, odtis: str, koda: str) -> dict:
    """Clan Linka dovoli napravo, ki kaze svojo 6-mestno kodo (prijava s QR kodo, brez skeniranja).
    Vrne {"ok": True, "ime": ...} ali {"ok": False, "razlog": "qr_ne_obstaja" | "prevec_poskusov" |
    "ista_naprava" | "ni_seznanjena" | "ni_huba"}. Star Hub kode brez qr_id ne pozna: odgovori kot za neznano kodo."""
    koda = "".join(z for z in str(koda or "") if z.isdigit())
    if len(koda) != 6:
        return {"ok": False, "razlog": "qr_ne_obstaja"}
    st, odgovor = _zahteva(_osnova(ws_naslov) + "/cast/pair/qr/approve", {"qr_id": "", "secret": koda},
                           zeton=zeton, odtis=odtis)
    if st == 200 and odgovor.get("approved"):
        return {"ok": True, "ime": str(odgovor.get("name") or "")}
    razlog = str(odgovor.get("code") or odgovor.get("koda") or "") if isinstance(odgovor, dict) else ""
    if st in (401, 403):
        razlog = "ni_seznanjena"
    elif st == 429:
        razlog = "prevec_poskusov"
    elif st == 409:
        razlog = "ista_naprava" if razlog == "ista_naprava" else (razlog or "qr_ne_obstaja")
    elif st in (400, 404):
        razlog = "qr_ne_obstaja"
    elif st != 200:
        razlog = "ni_huba"
    return {"ok": False, "razlog": razlog or "qr_ne_obstaja"}


def preklici_qr(ws_naslov: str, prijava: dict, device_id: str) -> None:
    """Stara koda ne sme veljati do poteka, ko je okno zaprto ali koda zamenjana."""
    try:
        _zahteva(_osnova(ws_naslov) + "/cast/pair/qr/cancel",
                 {"qr_id": prijava.get("qr_id", ""), "device_id": device_id,
                  "poll_secret": prijava.get("prevzem", "")}, odtis=prijava.get("odtis"), timeout=3.0)
    except Exception:
        pass


def qr_svg(besedilo: str) -> str:
    """QR koda kot SVG (python3-qrcode). Prazen niz, ce knjiznice ni - stran takrat ponudi samo kodo."""
    try:
        import qrcode  # type: ignore
        import qrcode.image.svg  # type: ignore
    except Exception:
        return ""
    import io
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2, box_size=10)
    qr.add_data(besedilo)
    qr.make(fit=True)
    slika = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    izhod = io.BytesIO()
    slika.save(izhod)
    return izhod.getvalue().decode("utf-8")


def vzemi_vstopnico_s_kodo(ws_naslov: str, zeton: str, odtis: Optional[str] = None) -> Tuple[Optional[str], int]:
    """(vstopnica, koda HTTP). Koda 401 pomeni: Hub tega zetona ne pozna vec (npr. gostitelj
    je bil ponastavljen ali je napravo odstranil) - naprava se mora znova seznaniti."""
    koda, odgovor = _zahteva(_osnova(ws_naslov) + POT_VSTOPNICE, {}, zeton=zeton, odtis=odtis)
    if koda != 200:
        return None, koda
    vstopnica = odgovor.get("ticket")
    return (vstopnica if isinstance(vstopnica, str) and vstopnica else None), koda


def vzemi_vstopnico(ws_naslov: str, zeton: str, odtis: Optional[str] = None) -> Optional[str]:
    return vzemi_vstopnico_s_kodo(ws_naslov, zeton, odtis)[0]


# ----------------------------------------------------------------------
# Krog zaupanja: prijava s podpisom kljuca naprave namesto zetona
# ----------------------------------------------------------------------

def _odtis_za_podpis(osnova: str, odtis: str) -> str:
    """Odtis, ki ga naprava podpise ob prijavi s kljucem: samo https s pripetim odtisom, sicer prazen niz."""
    return str(odtis or "").lower() if osnova.startswith("https://") and odtis else ""


def vzemi_vstopnico_s_podpisom(ws_naslov: str, device_id: str, odtis: str, ime: str = "") -> Tuple[Optional[str], int]:
    """(vstopnica, koda HTTP) s podpisom kljuca naprave (core/link_krog.py).

    Hub poslje enkratni izziv, naprava podpise izziv + odtis huba + svoj id; hub preveri podpis
    s kljucem iz kroga zaupanja. Zeton pri tem ni potreben - tako prezivimo zamenjavo huba.
    Koda 401 pomeni, da hub te naprave (s tem kljucem) v krogu nima.
    """
    osnova = _osnova(ws_naslov)
    # Samo prek TLS s pripetim odtisom in podpis samo tega odtisa: po http (star ws:// v nastavitvah) bi napadalec v LAN
    # posredoval izziv pravega sredisca in z nasim podpisom dobil sejo (neodvisni pregled, 19. 10. 2026).
    odtis_huba = _odtis_za_podpis(osnova, odtis)
    if not odtis_huba:
        return None, 0
    koda, izziv = _zahteva(osnova + "/cast/auth/challenge", {"device_id": device_id}, odtis=odtis)
    if koda != 200:
        return None, koda
    nonce = str(izziv.get("nonce", "") or "")
    if not nonce or (izziv.get("fp") and not link_tls.isti(izziv.get("fp"), odtis_huba)):
        return None, koda
    try:
        podpis = link_krog.podpisi(link_krog.podatki_za_podpis(odtis_huba, nonce, device_id))
    except Exception:
        return None, 0
    # Ime in platforma: ce hub nov id (iz kljuca) sele vpisuje kot alias starega, naj ima pravo ime.
    koda, odgovor = _zahteva(osnova + "/cast/auth/ticket",
                             {"device_id": device_id, "nonce": nonce, "signature": podpis,
                              "name": ime or "", "platform": PLATFORMA}, odtis=odtis)
    if koda != 200:
        return None, koda
    krog = odgovor.get("ring")
    if isinstance(krog, dict):
        link_krog.sprejmi(krog)
    vstopnica = odgovor.get("ticket")
    return (vstopnica if isinstance(vstopnica, str) and vstopnica else None), koda


def seja_s_podpisom(ws_naslov: str, device_id: str, odtis: str, ime: str = "") -> Optional[str]:
    """Sejni zeton za HTTP (vabilo, odhod) za napravo v krogu zaupanja, ki nima zetona seznanitve."""
    osnova = _osnova(ws_naslov)
    odtis_huba = _odtis_za_podpis(osnova, odtis)
    if not odtis_huba:
        return None
    koda, izziv = _zahteva(osnova + "/cast/auth/challenge", {"device_id": device_id}, odtis=odtis)
    nonce = str(izziv.get("nonce", "") or "") if koda == 200 else ""
    if not nonce or (izziv.get("fp") and not link_tls.isti(izziv.get("fp"), odtis_huba)):
        return None
    try:
        podpis = link_krog.podpisi(link_krog.podatki_za_podpis(odtis_huba, nonce, device_id))
    except Exception:
        return None
    koda, odgovor = _zahteva(osnova + "/cast/auth/ticket", {"device_id": device_id, "nonce": nonce, "signature": podpis,
                                                            "name": ime or "", "platform": PLATFORMA}, odtis=odtis)
    seja = odgovor.get("session_token") if koda == 200 else None
    return seja if isinstance(seja, str) and seja else None


def povabi(ws_naslov: str, zeton: str, odtis: str, preklici: str = "") -> dict:
    """»Poveži novo napravo«: sredisce ustvari enkratno kodo za pridruzitev (kot jo pokaze na svojem zaslonu).
    Vrne {"qr_id", "povezava", "velja", "pin"} ali
    {"napaka": "hub_star" | "ni_huba" | "ni_seznanjena"}.

    Povezava je ista kot na televizorju: https://safeer.si/p#j=<id>&s=<skrivnost>&f=<odtis>&a=<naslov:vrata>
    - skrivnost je za #, zato je streznik strani nikoli ne vidi; telefon se pripne na odtis."""
    koda, odgovor = _zahteva(_osnova(ws_naslov) + "/cast/pair/qr/invite", {"qr_id": preklici}, zeton=zeton, odtis=odtis)
    if koda in (404, 405):
        return {"napaka": "hub_star"}
    if koda in (401, 403):
        return {"napaka": "ni_seznanjena"}
    if koda != 200:
        return {"napaka": "ni_huba"}
    qr_id, skrivnost = str(odgovor.get("qr_id") or ""), str(odgovor.get("secret") or "")
    fp = str(odgovor.get("fp") or odtis or "").lower()
    if not qr_id or not skrivnost:
        return {"napaka": "ni_huba"}
    u = urlparse(ws_naslov)
    naslov = "%s:%d" % (u.hostname, u.port or 443)
    gostitelj = u.hostname or ""
    # Vabilo lastnega Huba (wss://127.0.0.1): v QR mora iti naslov v domacem omrezju, ki ga sporoci Hub,
    # sicer bi telefon iskal sredisce na samem sebi.
    domaci = str(odgovor.get("address") or "").strip()
    if gostitelj in ("127.0.0.1", "localhost", "::1") and ":" in domaci and not domaci.startswith("127."):
        naslov = domaci
        gostitelj = domaci.rsplit(":", 1)[0]
    # Nova sredisca vrnejo isti PIN, ki pripada QR vabilu. Pri starem srediscu
    # polja ni; prazen niz strani pove, naj pokaze samo rocni vnos kode.
    pin = str(odgovor.get("pin") or odgovor.get("code") or "")
    pin = "".join(znak for znak in pin if znak.isdigit())
    if len(pin) != 6:
        pin = ""
    return {"qr_id": qr_id, "velja": int(odgovor.get("expires_in_seconds") or 300), "pin": pin,
            "povezava": povezava_vabila(gostitelj, int(odgovor.get("web_port") or 0), qr_id, skrivnost, fp, naslov)}


def povezava_vabila(gostitelj: str, spletna_vrata: int, qr_id: str, skrivnost: str, fp: str, naslov: str) -> str:
    """Koda za novo napravo: stran spletnega odjemalca na srediscu (http://<sredisce>:<vrata>/#...), da dela tudi
    telefon brez Safeerja; telefon s Safeerjem jo odpre v aplikaciji. Brez spletnih vrat (staro sredisce)
    ostane https://safeer.si/p#..., ki jo razume samo aplikacija. Skrivnost je za # - streznik je ne vidi."""
    rep = "#j=%s&s=%s&f=%s&a=%s" % (qr_id, skrivnost, fp, naslov)
    if spletna_vrata > 0 and gostitelj and ":" not in gostitelj:
        return "http://%s:%d/%s" % (gostitelj, spletna_vrata, rep)
    return "https://safeer.si/p" + rep


def stanje_vabila(ws_naslov: str, zeton: str, odtis: str, qr_id: str) -> dict:
    """{"caka": bool, "pridruzen": ime ali ""} - ali se je z vabilom ze kdo pridruzil."""
    koda, odgovor = _zahteva(_osnova(ws_naslov) + "/cast/pair/qr/invite/status", {"qr_id": qr_id},
                             zeton=zeton, odtis=odtis, timeout=4.0)
    if koda != 200:
        return {"caka": False, "pridruzen": "", "napaka": koda}
    return {"caka": bool(odgovor.get("pending")),
            "pridruzen": str(odgovor.get("name") or "") if odgovor.get("joined") else ""}


def preklici_vabilo(ws_naslov: str, zeton: str, odtis: str, qr_id: str) -> None:
    try:
        _zahteva(_osnova(ws_naslov) + "/cast/pair/qr/invite/cancel", {"qr_id": qr_id}, zeton=zeton, odtis=odtis, timeout=3.0)
    except Exception:
        pass


def odidi(ws_naslov: str, zeton: str, odtis: str) -> bool:
    """Ta naprava zapusti Safeer Link: sredisce pozabi njen zeton in jo umakne iz kroga zaupanja."""
    try:
        koda, _ = _zahteva(_osnova(ws_naslov) + "/cast/devices/leave", {}, zeton=zeton, odtis=odtis, timeout=4.0)
    except Exception:
        return False
    return koda == 200


def vpisi_v_krog(ws_naslov: str, zeton: str, odtis: str, ime: str) -> bool:
    """Z veljavnim zetonom vpise kljuc te naprave v krog zaupanja huba (enkrat; potem gre s podpisom)."""
    try:
        kljuc = link_krog.javni_kljuc_b64()
    except Exception:
        return False
    koda, odgovor = _zahteva(_osnova(ws_naslov) + "/cast/trust/enroll",
                             {"pubkey": kljuc, "name": ime, "platform": PLATFORMA}, zeton=zeton, odtis=odtis)
    if koda != 200:
        return False
    krog = odgovor.get("ring")
    if isinstance(krog, dict):
        link_krog.sprejmi(krog)
    return True


# ----------------------------------------------------------------------
# Majhen odjemalec WebSocket (RFC 6455, samo kar potrebujemo)
# ----------------------------------------------------------------------

def _maskiraj(telo: bytes, maska: bytes) -> bytes:
    """XOR z masko po RFC 6455. Celostevilska pot je bistveno hitrejsa od zanke."""
    if not telo:
        return telo
    ponovljena = (maska * ((len(telo) + 3) // 4))[:len(telo)]
    return (int.from_bytes(telo, "big")
            ^ int.from_bytes(ponovljena, "big")).to_bytes(len(telo), "big")


class WsOdjemalec:
    """Besedilni WebSocket odjemalec na navadnem vticniku.

    Namenoma zna malo: odpre povezavo, poslje in prejme besedilne okvirje,
    odgovori na ping in se mirno zapre. To je vse, kar Safeer Hub potrebuje.
    """

    def __init__(self, naslov: str, timeout: float = 10.0,
                 bralni_timeout: float = BRALNI_TIMEOUT, odtis: Optional[str] = None) -> None:
        self.naslov = naslov
        self.timeout = timeout
        # Odtis Hubovega potrdila; pri wss:// je obvezen (drugo potrdilo = napaka).
        self.odtis = odtis
        # Rokovanje mora biti hitro, tisina med pogovorom pa ne pomeni napake:
        # zato dve razlicni meji. Prej je ena sama ubijala mirne povezave.
        self.bralni_timeout = bralni_timeout
        self.vticnik: Optional[socket.socket] = None
        self._medpomnilnik = b""
        #: Deli sporocila, ki prihaja v vec okvirjih (prezivijo casovno omejitev med okvirjema).
        self._deli: List[bytes] = []
        self._vrsta_sporocila = 0
        self._zaklep = threading.Lock()
        #: Klice se s tovorom vsakega ponga (bralna nit), npr. meritev poti soseda (core/link_pot.py); None = nic.
        self.ob_pongu: Optional[Callable[[bytes], None]] = None

    def odpri(self) -> None:
        u = urlparse(self.naslov)
        varno = u.scheme == "wss"
        gostitelj = u.hostname or "127.0.0.1"
        vrata = u.port or (443 if varno else 80)
        pot = u.path or "/"
        if u.query:
            pot += "?" + u.query

        if varno and not self.odtis:
            raise ConnectionError("Naprava s tem Hubom ni seznanjena (ni odtisa potrdila).")
        s = socket.create_connection((gostitelj, vrata), timeout=self.timeout)
        if varno:
            try:
                s, _ = link_tls.ovij(s, gostitelj, self.odtis)
            except Exception:
                try:
                    s.close()
                except Exception:
                    pass
                raise

        kljuc = base64.b64encode(os.urandom(16)).decode()
        zahteva = (
            f"GET {pot} HTTP/1.1\r\n"
            f"Host: {gostitelj}:{vrata}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {kljuc}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        s.sendall(zahteva.encode())

        glava = b""
        s.settimeout(self.timeout)
        while b"\r\n\r\n" not in glava:
            kos = s.recv(1024)
            if not kos:
                s.close()
                raise ConnectionError("Hub je zaprl povezavo med rokovanjem.")
            glava += kos
        prva = glava.split(b"\r\n", 1)[0].decode("latin-1")
        if "101" not in prva:
            s.close()
            raise ConnectionError(f"Hub je zavrnil povezavo: {prva}")

        self._medpomnilnik = glava.split(b"\r\n\r\n", 1)[1]
        self._deli = []
        s.settimeout(self.bralni_timeout)
        link_vticnik.brez_zamika(s)
        # Bere ena nit, pisejo druge: vticnica TLS tega sama ne prenese (core/link_vticnik.py).
        self.vticnik = link_vticnik.zavaruj(s)

    def poslji(self, besedilo: str) -> None:
        s = self.vticnik
        if s is None:
            raise ConnectionError("Povezava ni odprta.")
        podatki = besedilo.encode("utf-8")
        okvir = bytearray()
        okvir.append(0x81)  # FIN + besedilni okvir
        maska = os.urandom(4)
        dolzina = len(podatki)
        if dolzina < 126:
            okvir.append(0x80 | dolzina)
        elif dolzina < 65536:
            okvir.append(0x80 | 126)
            okvir += struct.pack("!H", dolzina)
        else:
            okvir.append(0x80 | 127)
            okvir += struct.pack("!Q", dolzina)
        okvir += maska
        okvir += _maskiraj(podatki, maska)
        with self._zaklep:
            s.sendall(bytes(okvir))

    def _napolni(self, koliko: int) -> None:
        """Bere, dokler medpomnilnik nima vsaj `koliko` bajtov. Iz njega ne vzame nicesar: ce branje
        prekine casovna omejitev, naslednji klic nadaljuje tam, kjer je ta ostal."""
        while len(self._medpomnilnik) < koliko:
            s = self.vticnik
            if s is None:
                raise ConnectionError("Povezava je zaprta.")
            kos = s.recv(65536)
            if not kos:
                raise ConnectionError("Hub je zaprl povezavo.")
            self._medpomnilnik += kos

    def _preberi(self, koliko: int) -> bytes:
        self._napolni(koliko)
        vzeto, self._medpomnilnik = self._medpomnilnik[:koliko], self._medpomnilnik[koliko:]
        return vzeto

    def _okvir(self) -> Tuple[bool, int, bytes]:
        """Naslednji cel okvir: (zadnji, vrsta, telo). Iz medpomnilnika ga vzame sele, ko je cel."""
        self._napolni(2)
        prvi, drugi = self._medpomnilnik[0], self._medpomnilnik[1]
        dolzina = drugi & 0x7F
        glava = 2
        if dolzina == 126:
            self._napolni(4)
            dolzina = struct.unpack("!H", self._medpomnilnik[2:4])[0]
            glava = 4
        elif dolzina == 127:
            self._napolni(10)
            dolzina = struct.unpack("!Q", self._medpomnilnik[2:10])[0]
            glava = 10
        if dolzina > NAJVECJE_SPOROCILO:
            self.zapri()
            raise ConnectionError(
                f"Hub je napovedal okvir {dolzina} B, dovoljeno je "
                f"{NAJVECJE_SPOROCILO} B.")
        maskirano = bool(drugi & 0x80)
        if maskirano:
            glava += 4
        self._napolni(glava + dolzina)
        okvir, self._medpomnilnik = self._medpomnilnik[:glava + dolzina], self._medpomnilnik[glava + dolzina:]
        telo = okvir[glava:]
        if maskirano:
            telo = _maskiraj(telo, okvir[glava - 4:glava])
        return bool(prvi & 0x80), prvi & 0x0F, telo

    def prejmi(self) -> Optional[str]:
        """Vrne naslednje besedilno sporocilo ali None, ko je povezava zaprta.

        Dolgo sporocilo sme priti v vec okvirjih (FIN=0 + nadaljevalni okvirji);
        sestavimo ga, sicer bi ga vrnili odsekanega in ga json.loads tiho zavrgel.
        Napovedano dolzino preverimo, preden karkoli preberemo.

        Casovna omejitev (TimeoutError) toka ne pokvari: delno prebrani okvir in ze prejeti deli
        sporocila pocakajo na naslednji klic. Prej je klicatelj po njej bral sredi okvirja.
        """
        while True:
            fin, vrsta, telo = self._okvir()

            # Nadzorni okvirji smejo priti sredi razdeljenega sporocila in ga ne
            # prekinejo.
            if vrsta == 0x8:
                return None
            if vrsta == 0x9:
                self._pong(telo)
                continue
            if vrsta == 0xA:  # pong na nas ping
                ob_pongu = self.ob_pongu
                if ob_pongu is not None:
                    try:
                        ob_pongu(telo)
                    except Exception:  # noqa: BLE001 - meritev ne sme ustaviti branja
                        pass
                continue

            if vrsta in (0x1, 0x2):
                self._deli = [telo]
                self._vrsta_sporocila = vrsta
            elif vrsta == 0x0:
                if not self._deli:
                    continue  # nadaljevanje brez zacetka -- zavrzemo
                self._deli.append(telo)
            else:
                continue

            if sum(len(d) for d in self._deli) > NAJVECJE_SPOROCILO:
                self.zapri()
                raise ConnectionError("Sporocilo s Huba je preveliko.")

            if fin:
                deli, self._deli = self._deli, []
                if self._vrsta_sporocila == 0x1:
                    return b"".join(deli).decode("utf-8", "replace")
                # binarnega ne razumemo; mirno spregledamo

    def ping(self, podatki: bytes = b"") -> bool:
        """Poslje ping. Vrne False, ce povezave ni vec -- to je nas srcni utrip.

        `podatki`: tovor (najvec 125 bajtov, meja nadzornega okvirja), ki ga druga stran vrne v pongu - npr.
        zaporedna stevilka in cas za meritev poti (core/link_pot.py). Brez njega je okvir enak kot doslej."""
        s = self.vticnik
        if s is None:
            return False
        tovor = bytes(podatki or b"")[:125]
        maska = os.urandom(4)
        try:
            with self._zaklep:
                s.sendall(bytes([0x89, 0x80 | len(tovor)]) + maska + _maskiraj(tovor, maska))
            return True
        except Exception:
            return False

    def _pong(self, telo: bytes) -> None:
        s = self.vticnik
        if s is None:
            return
        maska = os.urandom(4)
        okvir = bytearray([0x8A, 0x80 | min(len(telo), 125)])
        okvir += maska
        okvir += _maskiraj(telo[:125], maska)
        try:
            with self._zaklep:
                s.sendall(bytes(okvir))
        except Exception:
            pass

    def zapri(self) -> None:
        s = self.vticnik
        self.vticnik = None
        if s is None:
            return
        try:
            with self._zaklep:
                s.sendall(b"\x88\x80" + os.urandom(4))
        except Exception:
            pass
        # Samo shutdown, brez close: druga nit morda se bere (TLS). Zaprta stevilka vticnice bi takoj
        # pripadla naslednji povezavi, OpenSSL v stari niti pa bi bral njene bajte. Vticnico zapre
        # Python, ko je nobena nit vec ne uporablja.
        try:
            s.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass


# ----------------------------------------------------------------------
# Protocol v1: model naprave v prijavi (cast.register)
# ----------------------------------------------------------------------

PROTOKOL_V1 = "1.0"


def _razlicica_aplikacije() -> str:
    glavni = sys.modules.get("__main__")
    return str(getattr(glavni, "APP_VERSION", "") or "")


def model_naprave_v1(device_id: str) -> dict:
    """Polja Protocol v1 v tovoru cast.register: protocol, platform, kind, version (HubUsmerjevalnik.PROTOKOL_V1).

    kind: "control" za Safeer Control (id se konca na -control), sicer "computer" (brskalnik).
    Prioritete ne posljemo - racunalnik huba (se) ne gosti. Hub 0.2 ta polja prezre.
    """
    polja = {"protocol": PROTOKOL_V1, "platform": PLATFORMA,
             "kind": "control" if device_id.endswith("-control") else "computer"}
    razlicica = _razlicica_aplikacije()
    if razlicica:
        polja["version"] = razlicica
    return polja


# ----------------------------------------------------------------------
# Povezava z Hubom v svoji niti
# ----------------------------------------------------------------------

#: Oznaka sporocila je lahko tudi stevilo (nasi programi posiljajo niz): celo do te velikosti ali obicajna decimalka.
NAJVECJE_STEVILO_OZNAKE = 2 ** 63


def _predolga_oznaka(sporocilo: dict) -> bool:
    """Ali ima sporocilo oznako (`id`, `ref_id`), ki je ne sprejmemo. Tako sporocilo zavrzemo.

    Oznako programi ponavljajo v odgovorih in potrditvah, zato sme biti samo: niz do NAJVEC_OZNAKE_SPOROCILA znakov,
    obicajno stevilo ali nic (polja ni, null). Seznam, slovar, logicna vrednost ali ogromno stevilo na tem mestu bi se
    ponovilo v poljubni velikosti (peti neodvisni pregled, 7. 10. 2026)."""
    for polje in ("id", "ref_id"):
        vrednost = sporocilo.get(polje)
        if vrednost is None:
            continue
        if isinstance(vrednost, str):
            if len(vrednost) > NAJVEC_OZNAKE_SPOROCILA:
                return True
        elif isinstance(vrednost, bool):
            return True
        elif isinstance(vrednost, int):
            if abs(vrednost) >= NAJVECJE_STEVILO_OZNAKE:
                return True
        elif isinstance(vrednost, float):
            if vrednost != vrednost or abs(vrednost) >= NAJVECJE_STEVILO_OZNAKE:
                return True
        else:
            return True
    return False


def _zasciteni_tipi() -> frozenset:
    from core import link_e2e
    return link_e2e.ZASCITENI_TIPI


def _zmoznost_zascite() -> str:
    from core import link_e2e
    return link_e2e.ZMOZNOST


def _ura() -> float:
    """Ura za roke zascite (zapis vprasanj, dokaz kljuca): tece tudi med spanjem racunalnika (link_e2e.ura_sistema)."""
    from core import link_e2e
    return link_e2e.ura_sistema()


def _jedro_oznake(device_id: str) -> str:
    """Naprava, ki ji oznaka pripada, za stetje poskusov: jedro oznake iz kljuca, sicer oznaka sama."""
    return device_id[:link_krog.DOLZINA_ID_IZ_KLJUCA] if link_krog.je_id_iz_kljuca(device_id) else device_id


def kljuc_naprave_za_zascito(device_id: str) -> Optional[str]:
    """Javni kljuc naprave iz NASEGA kroga zaupanja, s katerim preverimo njen podpis v dogovoru zascite. Oznaka iz kljuca
    (`n-<16 hex>...`) je vezana na kljuc: velja samo kljuc, ki da njeno jedro - vzamemo ga, kjerkoli v krogu je (vnos
    naprave same, sorodnika ali stare oznake). Vnos s to oznako in DRUGIM kljucem ne steje: tujega kljuca tako ne more
    podtakniti niti sredisce, od katerega dobivamo krog, in s takim vnosom pravi napravi zascite ne more onemogociti.
    Stara oznaka (ni iz kljuca) ima kljuc svojega vnosa; njeno jedro je potem jedro TEGA kljuca."""
    try:
        from core import link_e2e
        if not link_e2e.veljavna_oznaka(device_id):
            return None             # oznaka, ki ne sme v podpisane bajte dogovora: zanjo kljuca ni
        krog = link_krog.krog()
        if link_krog.je_id_iz_kljuca(device_id):
            return krog.kljuc_za_jedro(device_id[:link_krog.DOLZINA_ID_IZ_KLJUCA])
        clan = krog.clan(device_id)
        return str((clan or {}).get("kljuc") or "") or None
    except Exception:  # noqa: BLE001
        return None


class Povezava:
    """Odpre povezavo s Hubom in v svoji niti posluša sporočila.

    Odzivi se vracajo prek `ob_sporocilu`; klicatelj poskrbi, da jih prenese
    na glavno nit (v GTK z GLib.idle_add).
    """

    def __init__(self, ws_naslov: str, zeton: str, device_id: str, ime: str,
                 sinhronizira: bool = False, odtis: Optional[str] = None,
                 dodatne_zmoznosti: Optional[List[str]] = None,
                 katalog: Optional[Callable[[], dict]] = None, v_krog: bool = True) -> None:
        self.ws_naslov = ws_naslov
        # False za racunalnik, ki mu uporabnik ni zaupal (core/link_seja.py): brez prijave s podpisom
        # in brez vpisa v krog zaupanja - povezava velja samo z zetonom te prijave.
        self.v_krog = v_krog
        # Protocol v1: katalog aplikacij te naprave ({"<id>": {"name", "kind"}}), ki gre v prijavo.
        # Klic, ne vrednost: katalog se prebere ob vsaki (ponovni) povezavi, da je svez.
        self.katalog = katalog
        # Zmoznosti, ki jih doda klicatelj (Safeer Control: "files" - deljene mape za televizor).
        self.dodatne_zmoznosti = list(dodatne_zmoznosti or [])
        self.zeton = zeton
        self.odtis = odtis
        self.device_id = device_id
        self.ime = ime
        # True, ko je Hub zeton zavrnil (401/403): naprava ni vec seznanjena.
        self.zavrnjena = False
        # True, ko je zadnja prijava sla s podpisom kljuca naprave (krog zaupanja), ne z zetonom.
        self.prijava_s_podpisom = False
        # True, ko je ta povezava kljuc naprave ravnokar vpisala v krog huba.
        self.vpisana_v_krog = False
        self.sinhronizira = sinhronizira
        self.odjemalec: Optional[WsOdjemalec] = None
        self.nit: Optional[threading.Thread] = None
        self.nit_utripa: Optional[threading.Thread] = None
        self.tece = False
        self.ob_sporocilu: Optional[Callable[[dict], None]] = None
        self.ob_stanju: Optional[Callable[[bool], None]] = None
        # Zascita ukazov od naprave do naprave (core/link_e2e): upravitelj sej nastane ob prvi rabi; zmoznosti naprav
        # iz zadnjega seznama sredisca povedo, katera naprava zascito zna.
        self._zascita = None
        self._zmoznosti_naprav: Dict[str, frozenset] = {}
        self._dokazi_kljucev: Dict[str, float] = {}     # oznaka naprave -> kdaj smo nazadnje zaceli dogovor z njo
        # Ukazi, ki so sli zasciteni: skupni zapis programa (_VPRASANJA). Glej velja_odgovor.
        self._vprasanja = _VPRASANJA
        self._zaklep_vprasanj = _ZAKLEP_VPRASANJ
        # Zapiranje je namerno dejanje; vse drugo je izpad, po katerem se vrnemo.
        self._ustavljen = False
        self._budilka = threading.Event()
        # Zahteva za takojsen nov poskus (prebudi): locena od budilke, ker cakata dve niti.
        self._prebuditev = threading.Event()
        # Seznam naprav iz posnetka in sprememb (core/link_spremembe.py); nov ob vsaki povezavi - prvo je vedno posnetek.
        self._seznam = link_spremembe.Prejemnik()

    def _odpri(self) -> bool:
        """Ena vzpostavitev: vstopnica, rokovanje, prijava. Brez cakanja."""
        # Samo TLS z odtisom: zeton in vse, kar posljemo, ne sme nikoli potovati v
        # cistem besedilu. Hub brez TLS naj se posodobi; naprava brez odtisa naj se
        # znova seznani.
        if not self.ws_naslov.startswith("wss://") or not self.odtis:
            return False
        vstopnica: Optional[str] = None
        # Najprej s podpisom kljuca naprave (krog zaupanja): zeton ni potreben, zato ta pot
        # prezivi tudi zamenjavo huba. Ce hub kroga se ne pozna (starejsi hub: 404) ali nas v
        # njem nima, gre po stari poti z zetonom.
        s_podpisom = False
        koda = 0
        try:
            # Tudi ce je nas kljuc v krogu pod starim id-jem: hub nov id sam vpise kot alias.
            s_podpisom = self.v_krog and link_krog.lahko_s_podpisom(self.device_id)
        except Exception:
            s_podpisom = False
        if s_podpisom:
            vstopnica, koda = vzemi_vstopnico_s_podpisom(self.ws_naslov, self.device_id, self.odtis, self.ime)
            if vstopnica:
                self.prijava_s_podpisom = True
        if not vstopnica and not self.zeton and s_podpisom:
            # Podpis ni uspel, zetona pa nimamo: druge poti ni. Zavrnitev je samo izrecen 401/403 (hub nas v krogu
            # nima). Neuspel podpis zaradi casa (hub se ravno zaganja, rele zamudi, prevec prijav) ni zavrnitev:
            # prej smo takrat poskusili se s praznim zetonom, dobili 401 in klicatelj (safeer_link._pozabi_zeton)
            # je izbrisal odtis - naprava je ostala brez povezave, dokler je kdo ni povezal znova.
            self.zavrnjena = koda in (401, 403)
            return False
        if not vstopnica:
            self.prijava_s_podpisom = False
            vstopnica, koda = vzemi_vstopnico_s_kodo(self.ws_naslov, self.zeton, self.odtis)
            # Hub nas ne pozna vec: brez nove seznanitve ne bo slo, zato tega ne poskusamo v krogu.
            self.zavrnjena = koda in (401, 403)
            if vstopnica and not s_podpisom and self.v_krog:
                # Zeton je veljaven: vpisemo kljuc naprave v krog, da gre naslednjic s podpisom.
                # Starejsi hub brez kroga vrne 404 - nic hudega, ostanemo pri zetonu.
                try:
                    if vpisi_v_krog(self.ws_naslov, self.zeton, self.odtis, self.ime):
                        self.vpisana_v_krog = True
                except Exception:
                    pass
        else:
            self.zavrnjena = False
        if not vstopnica or self._ustavljen:
            return False
        locilo = "&" if "?" in self.ws_naslov else "?"
        naslov = f"{self.ws_naslov}{locilo}ticket={vstopnica}"
        odjemalec = WsOdjemalec(naslov, odtis=self.odtis)
        try:
            odjemalec.odpri()
        except Exception:
            return False
        if self._ustavljen:
            # zapri() je prisel med odpiranjem: hub ne sme dobiti prijave, ki bi jo takoj zapustili.
            try:
                odjemalec.zapri()
            except Exception:
                pass
            return False

        prijava = {
            "id": str(int(time.time() * 1000)),
            "type": "cast.register",
            "payload": {
                "device_id": self.device_id,
                "name": self.ime,
                "role": "sender",
                **model_naprave_v1(self.device_id),
            },
        }
        if self.katalog is not None:
            try:
                katalog = self.katalog()
            except Exception:
                katalog = None
            if isinstance(katalog, dict) and katalog:
                prijava["payload"]["apps"] = katalog
        # Racunalnik sprejema besedilo, datoteke in zaslon; sync samo, ce je vklopljen.
        # "remote": Safeer Control sme temu racunalniku posiljati ukaze daljinca (core/link_daljinec.py).
        zmoznosti = ["url", "text", "file", "screen", "remote"]
        if self.sinhronizira:
            zmoznosti.append("sync")
        for z in self.dodatne_zmoznosti:
            if z not in zmoznosti:
                zmoznosti.append(z)
        if self._upravitelj_zascite() is not None:
            zmoznosti.append("e2e1")        # link_e2e.ZMOZNOST; zapisano z besedo, da ga preizkus registra zmoznosti vidi
        # Seznam naprav: po posnetku samo spremembe (link_spremembe.ZMOZNOST, zapisano z besedo kot zgoraj).
        zmoznosti.append("devdelta1")
        prijava["payload"]["capabilities"] = zmoznosti
        try:
            odjemalec.poslji(json.dumps(prijava))
        except Exception:
            odjemalec.zapri()
            return False
        # Imena naprav iz nasega kroga (dana na drugem hubu): hub vzame samo imena znanih clanov.
        try:
            odjemalec.poslji(json.dumps({"id": str(int(time.time() * 1000)), "type": "trust.names",
                                         "payload": link_krog.krog().json()}))
        except Exception:
            pass

        self._seznam = link_spremembe.Prejemnik()
        self.odjemalec = odjemalec
        self.tece = True
        return True

    def povezi(self) -> bool:
        """Prvi poskus. Ce uspe, povezavo od tu naprej vzdrzujemo sami."""
        self._ustavljen = False
        self._budilka.clear()
        self._prebuditev.clear()
        if not self._odpri():
            return False

        self.nit = threading.Thread(target=self._zanka, daemon=True)
        self.nit.start()
        self.nit_utripa = threading.Thread(target=self._srcni_utrip, daemon=True)
        self.nit_utripa.start()
        if self.ob_stanju:
            self.ob_stanju(True)
        return True

    poveži = povezi  # staro ime s sumnikom; jedro uporablja ASCII

    def _cakaj(self, sekunde: float) -> bool:
        """Prekinljivo cakanje. Vrne True, ce je medtem prislo zaprtje."""
        return self._budilka.wait(timeout=sekunde)

    def _cakaj_na_poskus(self, sekunde: float) -> str:
        """Cakanje pred novim poskusom povezave.

        Vrne "zaprto" (konec), "prebudi" (nekdo zeli takojsen poskus) ali "potek" (zamik je minil).
        Prebuditev ima svoj dogodek, ne budilke: sicer bi si jo srcni utrip in ta zanka odzirala,
        saj oba cakata - in prebuditev bi se izgubila prav takrat, ko je najbolj potrebna.
        """
        konec = time.monotonic() + sekunde
        while True:
            preostanek = konec - time.monotonic()
            if preostanek <= 0:
                return "potek"
            if self._budilka.wait(timeout=min(0.25, preostanek)):
                return "zaprto"
            if self._prebuditev.is_set():
                self._prebuditev.clear()
                return "prebudi"

    def prebudi(self, razlog: str = "") -> None:
        """Takoj preveri povezavo, brez cakanja na utrip ali zamik.

        Poklicemo jo, kadar vemo, da se je pod povezavo nekaj spremenilo: racunalnik je spal ali
        pa je dobil drugo omrezje. Takrat vticnica ni zaprta, le mrtva - zato jo zapremo sami,
        zanka pa se povezanje zacne takoj in brez zamika.
        """
        if self._ustavljen:
            return
        if razlog:
            print("[SafeerLink] prebujam povezavo:", razlog)
        odjemalec = self.odjemalec
        self.odjemalec = None
        self.tece = False
        if odjemalec is not None:
            try:
                odjemalec.zapri()
            except Exception:
                pass
        self._prebuditev.set()

    def _krajevni_naslov(self) -> str:
        """Nas IP na tej povezavi ('' ce ga ni): sprememba pomeni drugo omrezje."""
        odjemalec = self.odjemalec
        vticnik = getattr(odjemalec, "vticnik", None) if odjemalec is not None else None
        if vticnik is None:
            return ""
        try:
            return str(vticnik.getsockname()[0])
        except Exception:
            return ""

    def _srcni_utrip(self) -> None:
        """Redni ping. Brez njega tisina ni locljiva od prekinjenega omrezja.

        Ob vsakem utripu pogledamo tudi, ali je racunalnik vmes spal in ali smo se v istem
        omrezju. Oboje pomeni, da povezave najbrz ni vec, cetudi vticnica se ni zaprta.
        """
        utrip = 0
        naslov = self._krajevni_naslov()
        while not self._ustavljen:
            pred = time.time()
            if self._cakaj(PING_VSAKIH):
                return
            zamuda = time.time() - pred - PING_VSAKIH
            if zamuda > SKOK_UTRIPA:
                self.prebudi("racunalnik je spal %d s" % int(zamuda))
                naslov = ""
                continue
            zdajsnji = self._krajevni_naslov()
            if zdajsnji and naslov and zdajsnji != naslov:
                self.prebudi("drugo omrezje (%s -> %s)" % (naslov, zdajsnji))
                naslov = ""
                continue
            if zdajsnji:
                naslov = zdajsnji
            odjemalec = self.odjemalec
            if odjemalec is not None and self.tece:
                if not odjemalec.ping():
                    # Povezave ni vec; bralec bo to opazil in se povezal znova.
                    try:
                        odjemalec.zapri()
                    except Exception:
                        pass
                    continue
                utrip += 1
                if utrip % SONDA_VSAKIH_UTRIPOV == 0:
                    # Ali nas hub sploh se vodi kot prijavljene? Ukaz sami sebi: prijavljeni dobimo
                    # zavrnitev isti_naprava, osirotela vticnica pa naprava_ni_povezana (glej _poslusaj).
                    self._poslji_surovo({"id": SONDA_PREDPONA + str(int(time.time() * 1000)), "type": "control.command",
                                         "target": self.device_id, "payload": {"action": "status", "params": {}}})

    def _zanka(self) -> None:
        """Poslusa in se po izpadu sama vrne. Konca samo, ko klicatelj zapre."""
        poskus = 0
        while not self._ustavljen:
            self._poslusaj()
            self.tece = False
            if self._ustavljen:
                break
            self._javi_stanje(False)
            zamik = ZAMIKI_PONOVNEGA_POSKUSA[
                min(poskus, len(ZAMIKI_PONOVNEGA_POSKUSA) - 1)]
            izid = self._cakaj_na_poskus(zamik)
            if izid == "zaprto":
                break
            if izid == "prebudi":
                # Spanje ali drugo omrezje: poskusimo takoj in spet od zacetka zamikov.
                poskus = 0
            try:
                odprto = self._odpri()
            except Exception as e:  # noqa: BLE001 - zanka ponovnega povezovanja se ne sme koncati
                print("[SafeerLink] povezovanje: %s: %s" % (type(e).__name__, str(e)[:160]), flush=True)
                odprto = False
            if odprto:
                poskus = 0
                self._javi_stanje(True)
            else:
                poskus += 1
        self.tece = False
        odjemalec = self.odjemalec
        self.odjemalec = None
        if odjemalec is not None:
            try:
                odjemalec.zapri()
            except Exception:
                pass

    def _javi_stanje(self, povezan: bool) -> None:
        if self.ob_stanju:
            try:
                self.ob_stanju(povezan)
            except Exception as e:  # noqa: BLE001 - napaka klicatelja ne sme ustaviti ponovnega povezovanja
                print("[SafeerLink] ob_stanju: %s: %s" % (type(e).__name__, str(e)[:160]), flush=True)

    @property
    def aktivna(self) -> bool:
        """Povezava se vzdrzuje sama (tudi med ponovnim poskusom), dokler je klicatelj ne zapre."""
        return not self._ustavljen

    def _poslusaj(self) -> None:
        try:
            while self.tece and self.odjemalec is not None:
                besedilo = self.odjemalec.prejmi()
                if besedilo is None:
                    break
                try:
                    sporocilo = json.loads(besedilo)
                except (ValueError, RecursionError):
                    # Tudi predolgo stevilo (ValueError) in pregloboko gnezdenje (RecursionError): sporocilo zavrzemo,
                    # povezava s srediscem ostane.
                    continue
                if not isinstance(sporocilo, dict) or _predolga_oznaka(sporocilo):
                    continue        # sporocilo Linka je slovar s kratko oznako; drugo ne gre ne zasciti ne programu
                if sporocilo.get("type") in (link_spremembe.POSNETEK, link_spremembe.SPREMEMBE):
                    # Seznam naprav: posnetek ali spremembe. Program dobi vedno cel `cast.devices`; ob vrzeli ali dvomu
                    # zahtevamo posnetek, do takrat ostane zadnji pravi seznam.
                    sporocilo, zahtevaj = self._seznam.sprejmi(sporocilo)
                    if zahtevaj:
                        self._poslji_surovo({"id": str(int(time.time() * 1000)), "type": link_spremembe.ZAHTEVA})
                    if sporocilo is None:
                        continue
                zascita = self._zascita
                if zascita is not None:
                    # Kar predolgo caka na dogovor, klicatelj izve ob vsakem prejetem sporocilu - ne sele, ko spet kaj
                    # poslje (cistopis cakajocega sporocila sicer ostane v pomnilniku).
                    zascita.pospravi()
                if isinstance(sporocilo, dict) and str(sporocilo.get("ref_id") or "").startswith(SONDA_PREDPONA):
                    if sporocilo.get("sender"):
                        continue        # potrditev sonde poslje sredisce samo (brez posiljatelja), ne naprava
                    if sporocilo.get("error_code") == "naprava_ni_povezana":
                        # Hub nas ne vodi vec (druga povezava iste naprave je prisla in odsla): vticnico
                        # zapremo, zanka se prijavi znova.
                        break
                    continue
                if isinstance(sporocilo, dict) and sporocilo.get("type") == "cast.ack" \
                        and sporocilo.get("error_code") == "ni_virov":
                    # Sredisce nas je overilo, a nima virov za novo napravo (core/link_viri.py): uporabnik to izve.
                    try:
                        from core import link_viri
                        from urllib.parse import urlparse
                        link_viri.zavrnila_druga(urlparse(self.ws_naslov).hostname or self.ws_naslov)
                    except Exception:  # noqa: BLE001
                        pass
                if isinstance(sporocilo, dict) and sporocilo.get("type") == "trust.update":
                    # Hub razposlje krog zaupanja ob prijavi in ob vsaki spremembi; shranimo ga,
                    # da nas pozna tudi naslednji hub. Naprej ga ne dajemo.
                    try:
                        link_krog.sprejmi(sporocilo.get("payload"))
                    except Exception:
                        pass
                    continue
                if isinstance(sporocilo, dict):
                    # Oznako zascite vpisemo samo sami (spodaj, za sporocilo iz preverjene seje): kar pride po omrezju z
                    # njo, jo izgubi.
                    sporocilo.pop("_zascita", None)
                    tip = sporocilo.get("type")
                    try:
                        if tip == "cast.devices":
                            self._zapomni_zmoznosti(sporocilo.get("devices"))
                            self._dokazi_kljuce()
                        elif isinstance(tip, str) and tip.startswith("data."):
                            zascita = self._upravitelj_zascite()
                            if zascita is not None and zascita.prejmi(sporocilo):
                                continue
                        elif tip == "control.result" and not self.velja_odgovor(sporocilo):
                            print("[SafeerLink] odgovor na zasciten ukaz ni prisel iz seje vprasane naprave - zavrzen", flush=True)
                            continue
                    except Exception as e:  # noqa: BLE001 - eno sporocilo ne sme prekiniti povezave s srediscem
                        print("[SafeerLink] sporocila zascite ni bilo mogoce obdelati: %s" % type(e).__name__, flush=True)
                        continue
                if self.ob_sporocilu:
                    try:
                        self.ob_sporocilu(sporocilo)
                    except Exception as e:  # noqa: BLE001 - enako: napaka pri enem sporocilu ni razlog za novo povezavo
                        print("[SafeerLink] sporocila ni bilo mogoce obdelati: %s: %s" % (type(e).__name__, str(e)[:160]),
                              flush=True)
        except Exception as e:  # noqa: BLE001
            # Navaden odhod (sredisce je zaprlo, mi smo zaprli) ni napaka; vse drugo naj se vidi.
            if self.tece and not self._ustavljen and not isinstance(e, ConnectionError):
                print("[SafeerLink] povezava s srediscem se je koncala: %s: %s" % (type(e).__name__, str(e)[:160]),
                      flush=True)
        finally:
            odjemalec = self.odjemalec
            self.odjemalec = None
            if odjemalec is not None:
                try:
                    odjemalec.zapri()
                except Exception:
                    pass

    def poslji(self, sporocilo: dict) -> bool:
        """Poslje sporocilo srediscu. Ukaz, odgovor nanj, stran in nadzor predvajanja gredo napravi, ki zascito zna,
        samo zasciteno (core/link_e2e) - ce zascite ni mogoce vzpostaviti, sporocilo NE gre (nezascitenega nadomestka
        ni: prejemnik bi ga zavrnil, sredisce pa prebralo)."""
        cilj = str(sporocilo.get("target") or "")
        if cilj and cilj != "all" and cilj != self.device_id and sporocilo.get("type") in _zasciteni_tipi():
            zascita = self._upravitelj_zascite()
            if zascita is not None and self._naprava_zna_zascito(cilj):
                notranje = {k: v for k, v in sporocilo.items() if k not in ("target", "allow", "_zascita")}
                if not self.tece or self.odjemalec is None:
                    return False
                # Zapomnimo si PRED posiljanjem: odgovor lahko pride, se preden se posiljanje vrne.
                oznaka = str(sporocilo.get("id") or "")
                ukaz = bool(oznaka) and sporocilo.get("type") == "control.command"
                if ukaz:
                    self._zapomni_vprasanje(oznaka, cilj)
                poslano = bool(zascita.poslji(cilj, notranje))
                if not poslano and ukaz:
                    with self._zaklep_vprasanj:
                        self._vprasanja.pop(oznaka, None)
                return poslano
        return self._poslji_surovo(sporocilo)

    def _zapomni_vprasanje(self, oznaka: str, cilj: str) -> None:
        zdaj = _ura()
        with self._zaklep_vprasanj:
            if len(self._vprasanja) >= NAJVEC_VPRASANJ // 2:
                for stara in [o for o, v in self._vprasanja.items() if zdaj - v[1] > VPRASANJE_VELJA_S]:
                    self._vprasanja.pop(stara, None)
            while len(self._vprasanja) >= NAJVEC_VPRASANJ:
                self._vprasanja.pop(min(self._vprasanja, key=lambda o: self._vprasanja[o][1]), None)
            self._vprasanja[oznaka] = (cilj, zdaj)

    def velja_odgovor(self, sporocilo: dict) -> bool:
        """Ali odgovor na ukaz (`control.result`) velja. Na ukaz, ki je sel zasciten, velja samo odgovor iz preverjene
        seje naprave, ki smo jo vprasali: oznako posiljatelja takemu sporocilu vpise zascita (oznaka seje, katere kljuc je
        preverjen), ne sredisce. Odgovor, ki pride nezasciten ali iz seje druge naprave, ni njen - tudi ce mu je sredisce
        vpisalo oznako naprave, ki zascite ne zna, ali oznake sploh ni. Za ukaze, ki niso sli zasciteni (starejsa
        naprava), velja pravilo posiljatelja (link_dostop.zahteva_zascito) kot za druga sporocila."""
        with self._zaklep_vprasanj:
            vprasanje = self._vprasanja.get(str(sporocilo.get("ref_id") or ""))
        if vprasanje is None or _ura() - vprasanje[1] > VPRASANJE_VELJA_S:
            # Zapisa ni: ukaz ni sel zasciten (starejsa naprava) ali pa je zapis ze potekel. Zasciten odgovor je pristen
            # (posiljatelja mu je vpisala seja). Nezasciten mora imeti vsaj posiljatelja, ki ga vpise sredisce - odgovor
            # brez njega ni prisel od nobene naprave.
            return bool(sporocilo.get("_zascita")) or bool(sporocilo.get("sender"))
        return bool(sporocilo.get("_zascita")) and sporocilo.get("sender") == vprasanje[0]

    def poslji_nezasciteno(self, sporocilo: dict) -> bool:
        """Samo za zavrnitev ukaza, ki je prisel brez zascite: odgovor gre tistemu, ki ga je poslal, po isti poti.
        Vsebine ne nosi (glej SafeerLink._zavrni_nezasciten_ukaz)."""
        return self._poslji_surovo(sporocilo)

    def _poslji_surovo(self, sporocilo: dict) -> bool:
        if not self.tece or self.odjemalec is None:
            return False
        try:
            self.odjemalec.poslji(json.dumps(sporocilo))
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------ zascita od naprave do naprave

    def _upravitelj_zascite(self):
        """Upravitelj sej zascite ali None (racunalnik brez kljuca v krogu, brez kriptografije). Seje prezivijo ponovno
        povezavo s srediscem: so med programoma, ne med programom in srediscem."""
        if self._zascita is not None:
            return self._zascita
        if not self.v_krog:
            return None
        try:
            from core import link_dostop, link_e2e
            if not link_e2e.na_voljo():
                return None
            self._zascita = link_e2e.Upravitelj(
                moj_id=lambda: self.device_id,
                poslji=self._poslji_surovo,
                podpisi=link_krog.podpisi,
                kljuc_za=kljuc_naprave_za_zascito,
                preveri=link_krog.preveri_podpis,
                id_iz_kljuca=link_krog.id_iz_kljuca,
                ob_sporocilu=self._zasciteno_sporocilo,
                ob_seji=link_dostop.zabelezi_zascito,
                ob_zavrnitvi=self._zasciteno_zavrnjeno,
                ob_sprejemu=self._zasciteno_sprejeto)
        except Exception as e:  # noqa: BLE001
            print("[SafeerLink] zascita od naprave do naprave ni na voljo: %s" % type(e).__name__, flush=True)
            self._zascita = None
        return self._zascita

    def _zapomni_zmoznosti(self, naprave) -> None:
        """Zmoznosti naprav iz seznama sredisca. Vnos z oznako, ki ne more biti oznaka naprave (krmilni znaki,
        predolga), se prezre - zanjo zascite ni; seznam in zmoznosti imajo mejo."""
        from core import link_e2e
        zmoznosti = {}
        try:
            jedra, idji = link_krog.krog().znani()
        except Exception:  # noqa: BLE001 - brez kroga so vse oznake tuje (meja spodaj)
            jedra, idji = set(), set()
        tujih = 0
        for d in naprave if isinstance(naprave, list) else []:
            if not isinstance(d, dict) or not link_e2e.veljavna_oznaka(d.get("id")):
                continue
            i = d["id"]
            if not (i in idji or (link_krog.je_id_iz_kljuca(i) and i[:link_krog.DOLZINA_ID_IZ_KLJUCA] in jedra)):
                if tujih >= NAJVEC_NAPRAV_V_SEZNAMU:
                    continue
                tujih += 1
            z = d.get("capabilities")
            zmoznosti[d["id"]] = frozenset(x for x in (z if isinstance(z, list) else [])[:64]
                                           if isinstance(x, str) and len(x) <= 64)
        self._zmoznosti_naprav = zmoznosti

    def _dokazi_kljuce(self) -> None:
        """Z napravami, ki zascito prijavijo, a z njimi (se ali vec) nimamo seje, se dogovorimo takoj - ne sele ob prvem
        ukazu. Po dogovoru obe strani vesta (link_dostop.zabelezi_zascito), da od druge nezascitenega ukaza ne sprejmeta
        vec: oznake naprave, ki zascito zna, potem ne more uporabiti nihce brez njenega kljuca. Program, ki se je znova
        zagnal, starih sej nima - z dogovorom ob prvem seznamu naprav jih obnovi, se preden mu kdo poslje ukaz po seji,
        ki je ne pozna vec (ponovnega posiljanja po »ni seje« ni, glej link_e2e). Seznam naprav pise sredisce, zato mu
        tu ne verjamemo nicesar - dogovor uspe samo z napravo, ki se podpise s kljucem iz kroga. Najvec en poskus na
        napravo na minuto (naprava, ki nasega kljuca nima v krogu, zavrne takoj)."""
        zascita = self._upravitelj_zascite()
        if zascita is None:
            return
        zdaj = _ura()
        znane = self._zmoznosti_naprav
        # Zapis o zadnjem poskusu zavrzemo po casu, ne takrat, ko naprava izgine s seznama: seznam pise sredisce in z
        # izmenicnim skrivanjem naprave ne sme doseci, da se dogovor (podpis s kljucem naprave) zacenja znova in znova.
        for stara in [i for i, kdaj in self._dokazi_kljucev.items() if zdaj - kdaj > 10 * DOKAZ_KLJUCA_NAJVEC_NA_S]:
            self._dokazi_kljucev.pop(stara, None)
        # Koliko dogovorov smo v zadnji minuti zaceli z oznakami posamezne naprave (jedra).
        nedavni: Dict[str, int] = {}
        for i, kdaj in self._dokazi_kljucev.items():
            if zdaj - kdaj < DOKAZ_KLJUCA_NAJVEC_NA_S:
                nedavni[_jedro_oznake(i)] = nedavni.get(_jedro_oznake(i), 0) + 1
        zaceti = 0
        for device_id, zmoznosti in list(znane.items()):
            if device_id == self.device_id or _zmoznost_zascite() not in zmoznosti:
                continue
            try:
                if zascita.znova_javi_sejo(device_id):
                    # Seja je. Zapis »zascita« pisejo vsi programi tega racunalnika v isto datoteko: ce se je kateri
                    # vpis izgubil, ga upravitelj ob tem vpise znova (ze vpisano se samo preveri).
                    continue
                if not zascita.pozna_kljuc(device_id):
                    # Naprave ni v nasem krogu (ali oznaka ni veljavna): dogovor ne more uspeti. Taka naprava ne porabi
                    # ne dogovorov tega seznama ne zapisa o poskusih - sicer bi sredisce z izmisljenimi napravami
                    # prave odrinilo od dokaza kljuca (tretji pregled, 7. 10. 2026).
                    continue
                if zdaj - self._dokazi_kljucev.get(device_id, -DOKAZ_KLJUCA_NAJVEC_NA_S) < DOKAZ_KLJUCA_NAJVEC_NA_S:
                    continue
                if zaceti >= NAJVEC_DOKAZOV_NA_SEZNAM:
                    continue        # naprej samo se obnavljamo zapis za naprave, s katerimi seja je (zgoraj)
                jedro = _jedro_oznake(device_id)
                if nedavni.get(jedro, 0) >= NAJVEC_DOKAZOV_NA_JEDRO:
                    continue
                self._dokazi_kljucev[device_id] = zdaj
                nedavni[jedro] = nedavni.get(jedro, 0) + 1
                zaceti += 1
                zascita.dogovori_se(device_id)
            except Exception:  # noqa: BLE001
                continue

    def _naprava_zna_zascito(self, cilj: str) -> bool:
        """Naprava zascito prijavi srediscu (zmoznost) ali pa jo je s tem racunalnikom ze vzpostavila. Drugo je
        pomembno, ker seznam naprav pise sredisce: s crtanjem zmoznosti nas ne sme pripraviti do nezascitenega ukaza."""
        if _zmoznost_zascite() in self._zmoznosti_naprav.get(cilj, ()):
            return True
        try:
            from core import link_dostop
            if link_dostop.zahteva_zascito(cilj):
                return True
            # Ziva preverjena seja s to oznako: naprava zascito ocitno zna, tudi ce jo sredisce v seznamu zamolci in
            # zapis »zascita« zanjo ne odgovori (drugi neodvisni pregled, 7. 10. 2026).
            zascita = self._zascita
            return zascita is not None and zascita.ima_sejo(cilj)
        except Exception:  # noqa: BLE001
            # Ce se ne da ugotoviti (zapis dovoljenj se ne prebere ...), velja varna stran: sporocilo gre samo
            # zasciteno ali pa ne gre - nikoli nezasciteno napravi, ki je kljuc morda ze dokazala.
            return True

    def _zasciteno_zavrnjeno(self, notranje: dict, napaka: str, koda: str) -> None:
        """Sredisce zascitenega sporocila ni moglo dostaviti (naprave ni v Linku ...): klicatelj dobi enako zavrnitev,
        kot bi jo za nezasciteno sporocilo (npr. control.ack), da ne caka na iztek casa."""
        tip = str(notranje.get("type") or "")
        if not self.ob_sporocilu or "." not in tip or tip.endswith(".result") or tip.endswith(".ack"):
            return
        self.ob_sporocilu({"id": str(int(time.time() * 1000)), "type": tip.split(".", 1)[0] + ".ack",
                           "ref_id": str(notranje.get("id") or ""), "status": "rejected",
                           "error": napaka, "error_code": koda})

    def _zasciteno_sprejeto(self, notranje: dict) -> None:
        """Sredisce je zasciteno sporocilo sprejelo v posredovanje: klicatelj dobi enako potrditev, kot bi jo za
        nezasciteno sporocilo (npr. control.ack »accepted«)."""
        tip = str(notranje.get("type") or "")
        if not self.ob_sporocilu or "." not in tip or tip.endswith(".result") or tip.endswith(".ack"):
            return
        self.ob_sporocilu({"id": str(int(time.time() * 1000)), "type": tip.split(".", 1)[0] + ".ack",
                           "ref_id": str(notranje.get("id") or ""), "status": "accepted"})

    def _zasciteno_sporocilo(self, notranje: dict, od: str, jedro: str) -> None:
        """Sporocilo iz preverjene seje: posiljatelj je naprava, ki je dokazala kljuc z jedrom `jedro`. Naprej gre samo
        dogovorjeni nabor tipov: sporocil, ki jih sicer poslje samo sredisce (seznam naprav, krog zaupanja, koda za
        seznanitev), naprava po zasciteni poti ne more poslati - tako kot ji jih sredisce ne posreduje po nezasciteni."""
        tip = notranje.get("type")
        if not isinstance(tip, str) or tip not in _zasciteni_tipi():
            print("[SafeerLink] zasciteno sporocilo nedogovorjenega tipa zavrzeno", flush=True)
            return
        if _predolga_oznaka(notranje):
            print("[SafeerLink] zasciteno sporocilo z neveljavno oznako zavrzeno", flush=True)
            return
        notranje.pop("target", None)
        notranje["sender"] = od
        notranje.pop("sender_name", None)       # ime za prikaz doloci program iz seznama naprav, ne sporocilo samo
        notranje["_zascita"] = jedro
        if tip == "control.result" and not self.velja_odgovor(notranje):
            print("[SafeerLink] odgovor na zasciten ukaz je prisel od druge naprave, kot smo jo vprasali - zavrzen", flush=True)
            return
        if self.ob_sporocilu:
            self.ob_sporocilu(notranje)

    def objavi_katalog(self, katalog: dict) -> bool:
        """Protocol v1: naknadno objavi (ali izprazni) katalog aplikacij brez ponovne prijave."""
        return self.poslji({"id": str(int(time.time() * 1000)), "type": "apps.announce",
                            "payload": {"apps": katalog if isinstance(katalog, dict) else {}}})

    def poslji_url(self, cilj: str, url: str, naslov: Optional[str] = None) -> bool:
        return self.poslji({
            "id": str(int(time.time() * 1000)),
            "type": "cast.url",
            "target": cilj,
            "payload": {"url": url, "title": naslov or "", "start_position": 0.0},
        })

    def nadzor(self, cilj: str, dejanje: str, polozaj: Optional[float] = None,
               glasnost: Optional[float] = None) -> bool:
        telo: Dict[str, object] = {"action": dejanje}
        if polozaj is not None:
            telo["position"] = polozaj
        if glasnost is not None:
            telo["volume"] = glasnost
        return self.poslji({
            "id": str(int(time.time() * 1000)),
            "type": "cast.control",
            "target": cilj,
            "payload": telo,
        })

    def poslji_sync(self, kategorija: str, razlicica: int, vsebina: dict) -> bool:
        # `allow`: sredisce sme usklajevanje posredovati samo napravam iz ozjega kroga tega racunalnika.
        try:
            from core import link_dostop
            smejo = sorted(link_dostop.naprave_z(link_dostop.VSE))
        except Exception:  # noqa: BLE001 - brez zapisa nihce (varna stran)
            smejo = []
        return self.poslji({
            "id": str(int(time.time() * 1000)),
            "type": "sync.data",
            "target": "all",
            "allow": smejo,
            "payload": {
                "category": kategorija,
                "version": razlicica,
                "timestamp": time.time(),
                "data": vsebina,
            },
        })

    def zahtevaj_sync(self, kategorija: str, od_razlicice: Optional[int] = None) -> bool:
        telo: Dict[str, object] = {"category": kategorija}
        if od_razlicice is not None:
            telo["since_version"] = od_razlicice
        return self.poslji({
            "id": str(int(time.time() * 1000)),
            "type": "sync.request",
            "payload": telo,
        })

    def zapri(self) -> None:
        """Namerno zaprtje: po tem se ne povezujemo vec."""
        self._ustavljen = True
        self.tece = False
        self._budilka.set()
        odjemalec = self.odjemalec
        self.odjemalec = None
        if odjemalec is not None:
            odjemalec.zapri()
