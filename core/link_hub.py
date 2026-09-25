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
import struct
import threading
import time
import sys
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from core import link_krog, link_tls, spake2

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
        try:
            os.makedirs(os.path.dirname(self.pot), exist_ok=True)
            zacasna = self.pot + ".tmp"
            with open(zacasna, "w", encoding="utf-8") as d:
                json.dump(self.podatki, d, ensure_ascii=False, indent=2)
            os.chmod(zacasna, 0o600)
            os.replace(zacasna, self.pot)
        except Exception:
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
            naslov = f"{shema}://{naslovi[0]}:{info.port}{pot}"
            if all(n["naslov"] != naslov for n in najdeno):
                najdeno.append({"naslov": naslov, "fp": str(fp).lower(), "tls": str(tls) == "1", "ime": str(ime_h),
                                "id": str(id_h), "prio": prio})

        def update_service(self, zc, vrsta, ime):
            pass

        def remove_service(self, zc, vrsta, ime):
            pass

    zc = None
    try:
        zc = Zeroconf()
        ServiceBrowser(zc, "_safeercast._tcp.local.", Poslusalec())
        konec = time.time() + cas
        # Pocakamo cel cas: vec Hubov se oglasa vsak ob svojem casu, izbrati hocemo pravega.
        while time.time() < konec:
            time.sleep(0.1)
    except Exception:
        return []
    finally:
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


def poisci_hub_z_odtisom(znani: str = "", odtis: Optional[str] = None) -> Optional[dict]:
    """Kot poisci_hub, a vrne {"naslov", "fp", "isti", "krog", "id"}: isti = to je Hub, s katerim smo seznanjeni
    (isti naslov, ki se oglasa, ali isti odtis potrdila na drugem naslovu). Med vec Hubi ima
    prednost tisti z nasim odtisom, nato hub, ki je clan kroga zaupanja (krog=True: njegovo potrdilo
    nosi kljuc iz kroga, zato mu zaupamo brez seznanitve - prijava gre s podpisom), nato TLS Hubi po vrsti.
    """
    if znani:
        osnova = _osnova(znani)
        if je_hub(osnova, odtis=odtis):
            return {"naslov": znani if znani.startswith("wss://") else f"wss://{osnova.split('://', 1)[1]}{POT_WS}",
                    "fp": odtis or "", "isti": True}
    hubi = [h for h in poisci_hube_mdns() if h["tls"]]
    if odtis:
        for h in hubi:
            if h["fp"] == odtis.lower() and je_hub(_osnova(h["naslov"]), odtis=odtis):
                return {"naslov": h["naslov"], "fp": h["fp"], "isti": True}
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
        if videni and kljuc and kljuc == clan["kljuc"] and je_hub(_osnova(h["naslov"]), odtis=videni):
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


def zacni_seznanitev(ws_naslov: str, device_id: str, ime: str) -> Optional[dict]:
    """Odpre prijavo na Hubu. Vrne {"pair_id", "nacin", "hub_id", "odtis"} ali None.

    Samo prek TLS: odtis potrdila, ki ga vidimo zdaj, se vplete v seznanitev, zato ga
    napadalec v sredini ne more zamenjati, ne da bi seznanitev padla. Kode Hub ne
    poslje in je od nas ne dobi - pokaze jo na svojem zaslonu, uporabnik jo vtipka tu.
    """
    osnova = _osnova(ws_naslov)
    if not osnova.startswith("https://"):
        return {"napaka": "hub_brez_tls"}
    koda, odgovor, videni = link_tls.zahteva(osnova + "/cast/pair/start",
                                             {"device_id": device_id, "name": ime})
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
    prevec_poskusov, prijava_ne_obstaja, povezava_ni_uspela.
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
QR_POVEZAVA = "https://safeer.si/p#i={qr_id}&s={skrivnost}&f={odtis}"
QR_ODTIS_ZNAKOV = 16


def zacni_qr(ws_naslov: str, device_id: str, ime: str, platforma: str = "linux") -> Optional[dict]:
    """Odpre prijavo s QR kodo. Vrne {"qr_id", "odtis", "skrivnost", "prevzem", "povezava", "velja"},
    {"napaka": ...} ali None, ce se hub ne oglasi.

    V QR gre skrivnost (hub dobi samo njen SHA-256) in zacetek odtisa potrdila, ki ga vidimo zdaj -
    telefon ga primerja s hubom, ki mu zaupa, zato vsiljivec v sredini ne more dobiti potrditve.
    Za prevzem zetona je druga skrivnost, ki je v QR ni.
    """
    import hashlib
    import secrets
    osnova = _osnova(ws_naslov)
    if not osnova.startswith("https://"):
        return {"napaka": "hub_brez_tls"}
    skrivnost = secrets.token_hex(16)
    prevzem = secrets.token_hex(24)
    koda, odgovor, videni = link_tls.zahteva(osnova + "/cast/pair/qr/start", {
        "device_id": device_id, "name": ime, "platform": platforma,
        "secret_sha256": hashlib.sha256(skrivnost.encode("utf-8")).hexdigest(), "poll_secret": prevzem})
    if koda == 404 or koda == 405:
        return {"napaka": "hub_star"}
    if koda != 200 or not videni:
        if koda == 429:
            return {"napaka": "prevec_prijav"}
        return None
    qr_id = str(odgovor.get("qr_id", "") or "")
    if not qr_id:
        return None
    odtis = videni.lower()
    return {
        "qr_id": qr_id, "odtis": odtis, "skrivnost": skrivnost, "prevzem": prevzem,
        "povezava": QR_POVEZAVA.format(qr_id=qr_id, skrivnost=skrivnost, odtis=odtis[:QR_ODTIS_ZNAKOV]),
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

def vzemi_vstopnico_s_podpisom(ws_naslov: str, device_id: str, odtis: str, ime: str = "") -> Tuple[Optional[str], int]:
    """(vstopnica, koda HTTP) s podpisom kljuca naprave (core/link_krog.py).

    Hub poslje enkratni izziv, naprava podpise izziv + odtis huba + svoj id; hub preveri podpis
    s kljucem iz kroga zaupanja. Zeton pri tem ni potreben - tako prezivimo zamenjavo huba.
    Koda 401 pomeni, da hub te naprave (s tem kljucem) v krogu nima.
    """
    osnova = _osnova(ws_naslov)
    koda, izziv = _zahteva(osnova + "/cast/auth/challenge", {"device_id": device_id}, odtis=odtis)
    if koda != 200:
        return None, koda
    nonce = str(izziv.get("nonce", "") or "")
    odtis_huba = str(izziv.get("fp", "") or "") or odtis
    if not nonce:
        return None, koda
    try:
        podpis = link_krog.podpisi(link_krog.podatki_za_podpis(odtis_huba, nonce, device_id))
    except Exception:
        return None, 0
    # Ime in platforma: ce hub nov id (iz kljuca) sele vpisuje kot alias starega, naj ima pravo ime.
    koda, odgovor = _zahteva(osnova + "/cast/auth/ticket",
                             {"device_id": device_id, "nonce": nonce, "signature": podpis,
                              "name": ime or "", "platform": "linux"}, odtis=odtis)
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
    koda, izziv = _zahteva(osnova + "/cast/auth/challenge", {"device_id": device_id}, odtis=odtis)
    nonce = str(izziv.get("nonce", "") or "") if koda == 200 else ""
    if not nonce:
        return None
    try:
        podpis = link_krog.podpisi(link_krog.podatki_za_podpis(str(izziv.get("fp", "") or "") or odtis, nonce, device_id))
    except Exception:
        return None
    koda, odgovor = _zahteva(osnova + "/cast/auth/ticket", {"device_id": device_id, "nonce": nonce, "signature": podpis,
                                                            "name": ime or "", "platform": "linux"}, odtis=odtis)
    seja = odgovor.get("session_token") if koda == 200 else None
    return seja if isinstance(seja, str) and seja else None


def povabi(ws_naslov: str, zeton: str, odtis: str, preklici: str = "") -> dict:
    """»Poveži novo napravo«: sredisce ustvari enkratno kodo za pridruzitev (kot jo pokaze na svojem zaslonu).
    Vrne {"qr_id", "povezava", "velja"} ali {"napaka": "hub_star" | "ni_huba" | "ni_seznanjena"}.

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
    return {"qr_id": qr_id, "velja": int(odgovor.get("expires_in_seconds") or 300),
            "povezava": povezava_vabila(u.hostname or "", int(odgovor.get("web_port") or 0), qr_id, skrivnost, fp, naslov)}


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
                             {"pubkey": kljuc, "name": ime, "platform": "linux"}, zeton=zeton, odtis=odtis)
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
        self._zaklep = threading.Lock()

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
        s.settimeout(self.bralni_timeout)
        self.vticnik = s

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

    def _preberi(self, koliko: int) -> bytes:
        while len(self._medpomnilnik) < koliko:
            s = self.vticnik
            if s is None:
                raise ConnectionError("Povezava je zaprta.")
            kos = s.recv(4096)
            if not kos:
                raise ConnectionError("Hub je zaprl povezavo.")
            self._medpomnilnik += kos
        vzeto, self._medpomnilnik = self._medpomnilnik[:koliko], self._medpomnilnik[koliko:]
        return vzeto

    def prejmi(self) -> Optional[str]:
        """Vrne naslednje besedilno sporocilo ali None, ko je povezava zaprta.

        Dolgo sporocilo sme priti v vec okvirjih (FIN=0 + nadaljevalni okvirji);
        sestavimo ga, sicer bi ga vrnili odsekanega in ga json.loads tiho zavrgel.
        Napovedano dolzino preverimo, preden karkoli preberemo.
        """
        deli: List[bytes] = []
        vrsta_sporocila = 0
        while True:
            glava = self._preberi(2)
            fin = bool(glava[0] & 0x80)
            vrsta = glava[0] & 0x0F
            dolzina = glava[1] & 0x7F
            maskirano = bool(glava[1] & 0x80)
            if dolzina == 126:
                dolzina = struct.unpack("!H", self._preberi(2))[0]
            elif dolzina == 127:
                dolzina = struct.unpack("!Q", self._preberi(8))[0]
            if dolzina > NAJVECJE_SPOROCILO:
                self.zapri()
                raise ConnectionError(
                    f"Hub je napovedal okvir {dolzina} B, dovoljeno je "
                    f"{NAJVECJE_SPOROCILO} B.")
            maska = self._preberi(4) if maskirano else b""
            telo = self._preberi(dolzina) if dolzina else b""
            if maskirano:
                telo = _maskiraj(telo, maska)

            # Nadzorni okvirji smejo priti sredi razdeljenega sporocila in ga ne
            # prekinejo.
            if vrsta == 0x8:
                return None
            if vrsta == 0x9:
                self._pong(telo)
                continue
            if vrsta == 0xA:  # pong na nas ping
                continue

            if vrsta in (0x1, 0x2):
                deli = [telo]
                vrsta_sporocila = vrsta
            elif vrsta == 0x0:
                if not deli:
                    continue  # nadaljevanje brez zacetka -- zavrzemo
                deli.append(telo)
            else:
                continue

            if sum(len(d) for d in deli) > NAJVECJE_SPOROCILO:
                self.zapri()
                raise ConnectionError("Sporocilo s Huba je preveliko.")

            if fin:
                if vrsta_sporocila == 0x1:
                    return b"".join(deli).decode("utf-8", "replace")
                deli = []  # binarnega ne razumemo; mirno spregledamo

    def ping(self) -> bool:
        """Poslje ping. Vrne False, ce povezave ni vec -- to je nas srcni utrip."""
        s = self.vticnik
        if s is None:
            return False
        maska = os.urandom(4)
        try:
            with self._zaklep:
                s.sendall(bytes([0x89, 0x80]) + maska)
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
        try:
            s.close()
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
    polja = {"protocol": PROTOKOL_V1, "platform": "linux",
             "kind": "control" if device_id.endswith("-control") else "computer"}
    razlicica = _razlicica_aplikacije()
    if razlicica:
        polja["version"] = razlicica
    return polja


# ----------------------------------------------------------------------
# Povezava z Hubom v svoji niti
# ----------------------------------------------------------------------

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
        # Zapiranje je namerno dejanje; vse drugo je izpad, po katerem se vrnemo.
        self._ustavljen = False
        self._budilka = threading.Event()
        # Zahteva za takojsen nov poskus (prebudi): locena od budilke, ker cakata dve niti.
        self._prebuditev = threading.Event()

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
        if not vstopnica and not self.zeton:
            # Brez zetona ni druge poti. Zavrnitev je samo izrecen 401/403 na podpis (hub nas v krogu nima);
            # neuspel podpis zaradi casa (hub se ravno zaganja, rele zamudi) ni - sicer bi _pozabi_zeton
            # izbrisal odtis in naprava bi ostala brez povezave, dokler je kdo ne poveze znova.
            self.zavrnjena = s_podpisom and koda in (401, 403)
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
                    self.poslji({"id": SONDA_PREDPONA + str(int(time.time() * 1000)), "type": "control.command",
                                 "target": self.device_id, "payload": {"action": "status", "params": {}}})

    def _zanka(self) -> None:
        """Poslusa in se po izpadu sama vrne. Konca samo, ko klicatelj zapre."""
        poskus = 0
        while not self._ustavljen:
            self._poslusaj()
            self.tece = False
            if self._ustavljen:
                break
            if self.ob_stanju:
                self.ob_stanju(False)
            zamik = ZAMIKI_PONOVNEGA_POSKUSA[
                min(poskus, len(ZAMIKI_PONOVNEGA_POSKUSA) - 1)]
            izid = self._cakaj_na_poskus(zamik)
            if izid == "zaprto":
                break
            if izid == "prebudi":
                # Spanje ali drugo omrezje: poskusimo takoj in spet od zacetka zamikov.
                poskus = 0
            if self._odpri():
                poskus = 0
                if self.ob_stanju:
                    self.ob_stanju(True)
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
                except json.JSONDecodeError:
                    continue
                if isinstance(sporocilo, dict) and str(sporocilo.get("ref_id") or "").startswith(SONDA_PREDPONA):
                    if sporocilo.get("error_code") == "naprava_ni_povezana":
                        # Hub nas ne vodi vec (druga povezava iste naprave je prisla in odsla): vticnico
                        # zapremo, zanka se prijavi znova.
                        break
                    continue
                if isinstance(sporocilo, dict) and sporocilo.get("type") == "trust.update":
                    # Hub razposlje krog zaupanja ob prijavi in ob vsaki spremembi; shranimo ga,
                    # da nas pozna tudi naslednji hub. Naprej ga ne dajemo.
                    try:
                        link_krog.sprejmi(sporocilo.get("payload"))
                    except Exception:
                        pass
                    continue
                if isinstance(sporocilo, dict) and sporocilo.get("type") == "pair.code":
                    # Nova naprava se pridruzuje Linku: kodo pokaze tudi ta racunalnik (obvestilo).
                    tovor = sporocilo.get("payload") if isinstance(sporocilo.get("payload"), dict) else {}
                    koda = str(tovor.get("code") or "")
                    if len(koda) == 6 and koda.isdigit():
                        from core.link_hub_streznik import _obvestilo_kode
                        _obvestilo_kode(str(tovor.get("name") or "")[:64], koda)
                    continue
                if self.ob_sporocilu:
                    self.ob_sporocilu(sporocilo)
        except Exception:
            pass
        finally:
            odjemalec = self.odjemalec
            self.odjemalec = None
            if odjemalec is not None:
                try:
                    odjemalec.zapri()
                except Exception:
                    pass

    def poslji(self, sporocilo: dict) -> bool:
        if not self.tece or self.odjemalec is None:
            return False
        try:
            self.odjemalec.poslji(json.dumps(sporocilo))
            return True
        except Exception:
            return False

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
        return self.poslji({
            "id": str(int(time.time() * 1000)),
            "type": "sync.data",
            "target": "all",
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
