#!/usr/bin/env python3
"""
Safeer Browser for Linux Mint - DNS-over-HTTPS (DoH) & Encrypted Proxy Engine
Encrypted DNS with HTTP/2 support and bounded local HTTP/CONNECT and SOCKS5 tunneling.
Public target lookups fail closed; resolver endpoint bootstrap uses the system DNS.
The local proxy only ever connects outwards to public addresses, never to the Fetch
bad-port list: loopback, private, link-local (including cloud metadata) and reserved
ranges are refused.
"""

import socket
import threading
import time
import urllib.parse
import ipaddress
import gi
gi.require_version("Soup", "3.0")
from gi.repository import Soup, Gio, GLib
from typing import Dict, Tuple, Optional, List

# Znani zanesljivi DoH ponudniki
DOH_PROVIDERS = {
    "quad9": {
        "name": "Quad9 Secure DNS (9.9.9.9)",
        "url": "https://dns.quad9.net/dns-query",
        "fallback_ip": "9.9.9.9"
    },
    "adguard": {
        "name": "AdGuard DNS (dns.adguard-dns.com)",
        "url": "https://dns.adguard-dns.com/dns-query",
        "fallback_ip": "94.140.14.14"
    },
    "cloudflare": {
        "name": "Cloudflare DNS (1.1.1.1)",
        "url": "https://1.1.1.1/dns-query",
        "fallback_ip": "1.1.1.1"
    },
    "google": {
        "name": "Google Public DNS (8.8.8.8)",
        "url": "https://dns.google/dns-query",
        "fallback_ip": "8.8.8.8"
    },
    # Preverjeno 16. 10. 2026: doh.opendns.com odgovori 200 application/dns-message, 208.67.222.222 je v SAN potrdila.
    "opendns": {
        "name": "Cisco OpenDNS (208.67.222.222)",
        "url": "https://doh.opendns.com/dns-query",
        "fallback_ip": "208.67.222.222"
    }
}

#: Izbire DNS v vrstnem redu vmesnika (lastnik, 16. 10. 2026: »DNS naj bo prevzeto od Safeer Scita; top 5 izbir«).
#: "scit" = imena najprej preveri Safeer Scit (blokirana zavrne), ostala razresi strezniki naprej (privzeto krajevni DNS).
IZBIRE_DNS = ("scit", "quad9", "cloudflare", "google", "adguard", "opendns", "custom", "disabled")
PRIVZETI_DNS = "scit"
#: Streznik naprej za Scit. "router" = DNS usmerjevalnika, nic v oblak - privzeto na vseh napravah (lastnik 4. 11. 2026;
#: prej Cloudflare). DoH ponudnika uporabnik izbere sam (ob prvem vklopu Scita ali v nastavitvah).
IZBIRE_NAPREJ = ("router", "cloudflare", "quad9", "google", "adguard", "opendns", "custom")
PRIVZETI_NAPREJ = "router"

#: Ponudniki, ki namenoma blokirajo: njihov »ni imena« je lahko blokada (lazno pozitivni zadetki). Izmerjeno 16. 10. 2026:
#: Quad9 blokirano = NXDOMAIN brez SOA (pravi NXDOMAIN ima SOA), AdGuard = 0.0.0.0, OpenDNS = 146.112.61.104-110.
BLOKIRAJO = frozenset({"quad9", "adguard", "opendns"})
_OPENDNS_BLOKADA = ipaddress.ip_network("146.112.61.104/29")
#: Rezerva, ce izbrani ponudnik odpove (SERVFAIL, cas) ali blokira ime, ki ga Scit ne blokira.
REZERVNI_PONUDNIK = {"cloudflare": "google"}

OK, NI_IMENA, NAPAKA, BLOKIRANO = "ok", "ni_imena", "napaka", "blokirano"


class Izid(tuple):
    """(naslov, ttl) kot doslej, z razlogom: ok, ni_imena, napaka (SERVFAIL, cas, prenos) ali blokirano (ponudnik)."""
    stanje = ""


def _izid(naslov, ttl, stanje) -> Izid:
    i = Izid((naslov, ttl))
    i.stanje = stanje
    return i


def stanje_izida(izid) -> str:
    s = getattr(izid, "stanje", "")
    if s:
        return s
    return OK if izid[0] else (NAPAKA if izid[1] == 15 else NI_IMENA)


def razvrsti_odgovor(data: bytes, ponudnik: str) -> str:
    """Razlog iz glave odgovora DNS (preden pogledamo zapise): SERVFAIL je napaka (Quad9 pri pokvarjenem DNSSEC),
    NXDOMAIN brez SOA ali REFUSED pri ponudniku, ki blokira, je blokada."""
    if len(data) < 12:
        return NAPAKA
    rcode = data[3] & 0x0F
    if rcode == 0:
        return OK
    if rcode == 3:
        return BLOKIRANO if ponudnik in BLOKIRAJO and data[8:10] == b"\x00\x00" else NI_IMENA
    if rcode == 5 and ponudnik in BLOKIRAJO:
        return BLOKIRANO
    return NAPAKA


def je_naslov_blokade(naslov: str) -> bool:
    """Naslov, ki ga ponudnik vrne namesto blokirane strani (0.0.0.0, ::, stran blokade OpenDNS)."""
    try:
        ip = ipaddress.ip_address(naslov)
    except ValueError:
        return False
    return ip.is_unspecified or (ip.version == 4 and ip in _OPENDNS_BLOKADA)


def razcleni_po_meri(besedilo: str) -> Tuple[str, str]:
    """DNS po meri (lastnik: »uporabnika ne omejujemo«): naslov DoH ali navaden IP streznika DNS.

    Vrne ("doh", "https://.../dns-query"), ("ip", "naslov" ali "naslov:vrata" / "[v6]:vrata") ali ("", kljuc napake).
    Gol ime streznika (dns.primer.si) postane https://dns.primer.si/dns-query. Lokalni naslovi (Pi-hole, usmerjevalnik)
    so dovoljeni; povezavno-lokalni (metapodatki oblaka), vecvrstni in nedolocen pa ne."""
    t = str(besedilo or "").strip()
    if not t or len(t) > 300 or any(c.isspace() for c in t):
        return "", "doh_po_meri_prazno" if not t else "doh_po_meri_oblika"
    if t.lower().startswith("http://"):
        return "", "doh_po_meri_https"
    if t.lower().startswith("https://"):
        try:
            p = urllib.parse.urlsplit(t)
            p.port
        except ValueError:
            return "", "doh_po_meri_oblika"
        if not p.hostname or p.username or p.password or not je_dovoljen_doh_streznik(p.hostname):
            return "", "doh_po_meri_oblika"
        return "doh", urllib.parse.urlunsplit(("https", p.netloc, p.path or "/dns-query", p.query, ""))
    naslov, vrata = t, ""
    if t.startswith("[") and "]" in t:
        naslov, _, ostalo = t[1:].partition("]")
        if ostalo:
            if not ostalo.startswith(":"):
                return "", "doh_po_meri_oblika"
            vrata = ostalo[1:]
    elif t.count(":") == 1:
        naslov, vrata = t.split(":", 1)
    try:
        ip = ipaddress.ip_address(naslov)
    except ValueError:
        if "/" in t or ":" in t or "." not in t or not je_dovoljen_doh_streznik(t):
            return "", "doh_po_meri_oblika"
        return "doh", "https://%s/dns-query" % t.lower()
    if vrata and not (vrata.isdigit() and 0 < int(vrata) <= 65535):
        return "", "doh_po_meri_oblika"
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified or (ip.is_reserved and not ip.is_loopback):
        return "", "doh_po_meri_naslov"
    if not vrata:
        return "ip", str(ip)
    return "ip", ("[%s]:%s" % (ip, vrata)) if ip.version == 6 else "%s:%s" % (ip, vrata)


def _naslov_in_vrata(vrednost: str) -> Tuple[str, int]:
    if vrednost.startswith("["):
        naslov, _, vrata = vrednost[1:].partition("]:")
        return naslov, int(vrata or 53)
    if vrednost.count(":") == 1:
        naslov, vrata = vrednost.split(":")
        return naslov, int(vrata)
    return vrednost, 53


def vprasaj_navadno(streznik: str, vrata: int, telo: bytes, timeout: float) -> Optional[bytes]:
    """Navadna poizvedba DNS (UDP, ob prirezanem odgovoru TCP) z nakljucnim ID: uporabnikov streznik po meri (Pi-hole) ali
    sistemski Scit na 127.0.0.1. Odgovor velja samo z istim ID; telo je vprasanje z ID 0 (DoH), ID tu zamenjamo."""
    import os as _os
    ident = _os.urandom(2)
    paket = ident + telo[2:]
    druzina = socket.AF_INET6 if ":" in streznik else socket.AF_INET
    try:
        with socket.socket(druzina, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            s.connect((streznik, vrata))
            s.send(paket)
            konec = time.monotonic() + timeout
            while True:
                s.settimeout(max(0.05, konec - time.monotonic()))
                odgovor = s.recv(4096)
                if odgovor[:2] == ident and len(odgovor) >= 12:
                    break
        if not odgovor[2] & 0x02:       # TC: odgovor ne gre v UDP, vprasamo prek TCP
            return b"\x00\x00" + odgovor[2:]
        with socket.create_connection((streznik, vrata), timeout=timeout) as s:
            s.sendall(len(paket).to_bytes(2, "big") + paket)
            dolzina = int.from_bytes(_preberi_tocno(s, 2), "big")
            odgovor = _preberi_tocno(s, dolzina)
        return b"\x00\x00" + odgovor[2:] if odgovor[:2] == ident else None
    except (OSError, ValueError):
        return None


def sistemski_dns(ime: str) -> Izid:
    """Ime prek sistemskega DNS (usmerjevalnik ali sistemski Scit): samo za Scit, kadar sifriran streznik naprej ne
    odgovori (lastnik: »ce DoH ne gre, DNS usmerjevalnika«)."""
    try:
        naslovi = socket.getaddrinfo(ime, 443, 0, socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        return _izid(None, 15, NAPAKA)
    v4 = [a[4][0] for a in naslovi if a[0] == socket.AF_INET]
    v6 = [a[4][0] for a in naslovi if a[0] == socket.AF_INET6]
    naslov = (v4 or v6 or [None])[0]
    return _izid(naslov, 60, OK) if naslov else _izid(None, 60, NI_IMENA)

# Vrata, na katera lokalni posrednik nikoli ne vzpostavi povezave.
# Seznam sledi seznamu "bad ports" iz standarda Fetch -- enako delajo brskalniki --
# in mu doda strezniske baze in predpomnilnike, ki jih brskanje nikoli ne potrebuje.
# Vsa druga vrata so dovoljena, da strani na nestandardnih vratih delujejo naprej.
PREPOVEDANA_VRATA = frozenset({
    1, 7, 9, 11, 13, 15, 17, 19, 20, 21, 22, 23, 25, 37, 42, 43, 53, 69, 77, 79,
    87, 95, 101, 102, 103, 104, 109, 110, 111, 113, 115, 117, 119, 123, 135, 137,
    139, 143, 161, 179, 389, 427, 465, 512, 513, 514, 515, 526, 530, 531, 532,
    540, 548, 554, 556, 563, 587, 601, 636, 989, 990, 993, 995, 1719, 1720, 1723,
    2049, 3659, 4045, 4190, 5060, 5061, 6000, 6566, 6665, 6666, 6667, 6668, 6669,
    6679, 6697, 10080,
    # baze, predpomnilniki in iskalniki
    1433, 1521, 3306, 5432, 5984, 6379, 9042, 9200, 11211, 27017, 27018,
})

# Obsegi, ki niso javni internet in jih posrednik nikoli ne sme doseči.
# ipaddress.is_private pokriva 10/8, 172.16/12, 192.168/16, 100.64/10 (CGNAT),
# 0.0.0.0/8 in podobno; povratne, povezavno-lokalne (tudi 169.254.169.254),
# večvrstne in rezervirane naslove pokrijemo posebej.
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def je_javni_naslov(naslov: str) -> bool:
    """
    True samo za naslove na javnem internetu.
    Zavrne povratne, zasebne, povezavno-lokalne (metapodatki oblaka),
    CGNAT, večvrstne, rezervirane in nedoločene naslove.
    """
    if not naslov:
        return False
    try:
        ip = ipaddress.ip_address(naslov.strip().strip("[]"))
    except ValueError:
        return False

    # IPv6, ki v resnici nosi IPv4 naslov, presodimo po tem IPv4 naslovu.
    if ip.version == 6:
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None:
            ip = mapped
        else:
            sixtofour = getattr(ip, "sixtofour", None)
            if sixtofour is not None:
                ip = sixtofour

    if (ip.is_loopback or ip.is_private or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
        return False
    if ip.version == 4 and ip in _CGNAT:
        return False
    return True


#: Domace omrezje, ki ga uporabnik lahko izrecno dovoli (stikalo »dovoli lokalno omrezje«). Povratni, povezavno-lokalni
#: (metapodatki oblaka), vecvrstni, rezervirani in nedolocen naslov NISO med njimi in ostanejo zavrnjeni.
_DOMACE_MREZE = tuple(ipaddress.ip_network(n) for n in
                      ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "fc00::/7"))


def je_dovoljen_cilj(naslov: str, dovoli_lokalno: bool = False) -> bool:
    """Javni naslov, ali (le ce je uporabnik dovolil lokalno omrezje) naslov v domacem omrezju.

    Ime, ki ga javni razreševalnik prevede v domaci naslov, je sicer znak napada (DNS rebinding); pri lastnem DoH
    (Pi-hole, usmerjevalnik) pa je to pricakovano - zato izrecno stikalo, privzeto izklopljeno."""
    if je_javni_naslov(naslov):
        return True
    if not dovoli_lokalno:
        return False
    try:
        ip = ipaddress.ip_address(str(naslov).strip().strip("[]"))
    except ValueError:
        return False
    if ip.version == 6 and getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped
    return any(ip.version == n.version and ip in n for n in _DOMACE_MREZE)


#: Imena, ki jih javni DNS ne pozna in vodijo v notranja omrezja (tudi metapodatki oblaka).
NOTRANJA_IMENA = ("localhost", ".localhost", ".local", ".internal", ".home.arpa", ".lan")


def je_dovoljen_doh_streznik(gostitelj: str) -> bool:
    """Ali sme uporabnikov lastni DoH streznik biti na tem naslovu.

    Domace omrezje je dovoljeno (Pi-hole ali AdGuard Home na usmerjevalniku), povratni,
    povezavno-lokalni (metapodatki oblaka, 169.254.169.254) in posebni naslovi pa ne:
    nastavitev ne sme postati pot do storitev, ki jih brskalnik sicer nikoli ne doseze."""
    g = str(gostitelj or "").strip().strip("[]").rstrip(".").lower()
    if not g:
        return False
    try:
        ip = ipaddress.ip_address(g)
    except ValueError:
        return not (g == "localhost" or g.endswith(NOTRANJA_IMENA))
    if ip.version == 6 and getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped
    return not (ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified)


def je_dovoljena_vrata(vrata: int) -> bool:
    """True za vsa vrata, ki jih brskanje potrebuje; nevarna so zavrnjena."""
    try:
        v = int(vrata)
    except (TypeError, ValueError):
        return False
    return 0 < v <= 65535 and v not in PREPOVEDANA_VRATA


NASLOV_SCITA = "127.0.0.1"
_scit_vrata = (0.0, 0)      # (do kdaj velja, vrata) - preverimo najvec vsakih 30 s


def sistemski_scit_vrata() -> int:
    """Vrata sistemskega Scita na 127.0.0.1 (0 = ne tece). Brskalnik ga uporabi, ce tece: ista pravila, en filter.

    Preverjanje (do 4 x 0,3 s - na 5355 je lahko LLMNR, ki ne odgovori) tece v ozadju; poizvedba ne caka nanj."""
    global _scit_vrata
    zdaj = time.monotonic()
    if zdaj >= _scit_vrata[0]:
        _scit_vrata = (zdaj + 30.0, _scit_vrata[1])       # en preverjevalec naenkrat

        def preveri() -> None:
            global _scit_vrata
            try:
                from core import os_scit
                vrata = os_scit.tekoci_scit()
            except Exception:  # noqa: BLE001
                vrata = 0
            _scit_vrata = (time.monotonic() + 30.0, vrata)
        threading.Thread(target=preveri, name="safeer-scit-vrata", daemon=True).start()
    return _scit_vrata[1]


def znana_scit_vrata(vrata: int) -> None:
    """Scit v svojem procesu (core/scit_odjemalec.py) je povedal, na katerih vratih tece: Splet ga vprasa takoj, brez
    cakanja na preverbo v ozadju. Prej je prvo ime vedno slo v scit_kategorija, ta pa je v procesu Safeer OS nalozila
    in zacela prenasati SVOJE sezname - dva nabora v pomnilniku in dva prenosa (neodvisni pregled 1.0.129)."""
    global _scit_vrata
    if vrata:
        _scit_vrata = (time.monotonic() + 30.0, int(vrata))


def scit_kategorija(ime: str, samo_z_diska: bool = False) -> Optional[str]:
    """Kategorija, ce Safeer Scit ime blokira; '' ce ga ne; None, ce nabora (se) ni. Isti nabor kot sistemski Scit
    (os_scit.skupni_seznami - en prenos seznamov na proces). samo_z_diska: brez prenasanja (rezerva pri ponudniku)."""
    try:
        from core import os_scit
        seznami = os_scit.skupni_seznami(zazeni=not samo_z_diska)
        if not seznami.na_voljo():
            return None
        return seznami.kategorija(str(ime or "").lower().rstrip(".")) or ""
    except Exception:  # noqa: BLE001
        return None


class DoHResolver:
    """
    Kriptografski razreševalnik DNS-over-HTTPS z lokalnim predpomnilnikom (In-Memory TTL Cache).
    Poizvedbe pošilja prek šifriranega TLS protokola neposredno na DoH strežnike.
    """

    def __init__(self, provider: str = "cloudflare", custom_url: str = "", naprej: str = PRIVZETI_NAPREJ,
                 naprej_po_meri: str = "", rezerva: bool = False):
        self.provider = provider if (provider in DOH_PROVIDERS or provider in ("custom", "scit")) else "cloudflare"
        self.custom_url = custom_url.strip()
        self.naprej = naprej if naprej in IZBIRE_NAPREJ else PRIVZETI_NAPREJ
        self.naprej_po_meri = str(naprej_po_meri or "").strip()
        #: Samodejna rezerva (SERVFAIL, cas, blokada brez Scita): vklopi jo get_doh_proxy po nastavitvi dns_rezerva.
        self.rezerva = bool(rezerva)
        #: Samo stetje (zasebnost: imen domen ne hranimo in ne zapisujemo).
        self.stevci = {"rezerva": 0, "scit_blokiral": 0, "sistemski_scit": 0}
        # Predpomnilnik: hostname -> (ip_address, expire_timestamp)
        self._cache: Dict[str, Tuple[str, float]] = {}
        self._pocisceno = time.time()
        self._lock = threading.Lock()
        self._pending = {}
        #: Nedavno blokirana imena (samo v pomnilniku, najvec 64): stran napake pove »blokiral Scit«.
        self._blokirana: Dict[str, str] = {}

    def _generacija(self):
        return (self.provider, self.custom_url, self.naprej, self.naprej_po_meri)

    def set_provider(self, provider: str, custom_url: str = "", naprej: Optional[str] = None,
                     naprej_po_meri: Optional[str] = None, rezerva: Optional[bool] = None):
        with self._lock:
            c_url = custom_url.strip()
            if rezerva is not None:
                self.rezerva = bool(rezerva)
            if not (provider in DOH_PROVIDERS or provider in ("custom", "scit")):
                return
            nova = (provider, c_url,
                    naprej if naprej in IZBIRE_NAPREJ else self.naprej,
                    str(naprej_po_meri).strip() if naprej_po_meri is not None else self.naprej_po_meri)
            if nova != self._generacija():
                self.provider, self.custom_url, self.naprej, self.naprej_po_meri = nova
                self._cache.clear()
                self._blokirana.clear()
                self._rezerva_do = 0.0

    def resolve(self, hostname: str, timeout: float = 3.5) -> Optional[str]:
        """
        Razreši domeno v IPv4 naslov prek DoH.
        Vrne IPv4 niz ali None, če poizvedba ne uspe.
        """
        if not hostname:
            return None

        h = hostname.lower().strip().rstrip(".")
        try:
            return str(ipaddress.ip_address(h))
        except ValueError:
            pass
        try:
            h = h.encode("idna").decode("ascii")
            if len(h) > 253 or any(not label or len(label) > 63 for label in h.split(".")):
                return None
        except UnicodeError:
            return None

        # Če je že IPv4 naslov
        parts = h.split(".")
        if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
            return h

        now = time.time()

        # 1. Preveri predpomnilnik. Pretecen zapis (do STARO_S) vrnemo takoj in ga osvezimo v ozadju (RFC 8767,
        #    "serve stale"): stran ne caka na DoH zaradi kratkih TTL-jev CDN-jev. Ce stari naslov ne deluje vec,
        #    posrednik ime pozabi in ga razresi znova (LocalDoHProxy._povezi_z_osvezitvijo).
        staro = None
        with self._lock:
            cached = self._cache.get(h)
            if cached:
                ip, exp = cached
                if now < exp:
                    return ip
                if ip and now < exp + self.STARO_S:
                    staro = ip
                else:
                    del self._cache[h]
        if staro:
            self._osvezi_v_ozadju(h, timeout)
            return staro

        # Coalesce requests for one host and never fall back to plaintext DNS.
        with self._lock:
            generation = self._generacija()
            key = (generation, h)
            event = self._pending.get(key)
            owner = event is None
            if owner:
                event = threading.Event()
                self._pending[key] = event
        if not owner:
            event.wait(timeout + 1)
            with self._lock:
                entry = self._cache.get(h)
                return entry[0] if entry and entry[1] > time.time() else None
        try:
            try:
                ip, ttl = self._query_doh(h, timeout)
            except Exception:  # noqa: BLE001 - kot neuspela poizvedba
                ip, ttl = None, 15
            with self._lock:
                if generation == self._generacija():
                    self._cache[h] = (ip, time.time() + (max(1, min(ttl, 3600)) if ip else 15))
                    self._pocisti_predpomnilnik()
            return ip
        finally:
            with self._lock:
                self._pending.pop(key, None)
                event.set()

    #: Kako dolgo po izteku TTL se sme uporabiti star naslov (medtem ko se osvezuje v ozadju).
    STARO_S = 3600
    #: Na koliko casa predpomnilnik pocisti imena, ki jih resolve tudi sam ne bi vec uporabil.
    POCISTI_S = 600

    def _pocisti_predpomnilnik(self) -> None:
        """Klicati z zaklepom. Zapis se brise ob naslednjem vprasanju po istem imenu; imena, ki jih nihce vec ne vprasa
        (oglasi, sledilci, CDN-ji), bi v dolgotrajnem procesu ostala za vedno - zato jih na nekaj minut odstranimo z
        enakim pravilom kot resolve (negativni po izteku, pozitivni po izteku + STARO_S)."""
        zdaj = time.time()
        if zdaj - self._pocisceno < self.POCISTI_S:
            return
        self._pocisceno = zdaj
        for ime in [i for i, (ip, exp) in self._cache.items() if zdaj >= exp + (self.STARO_S if ip else 0)]:
            del self._cache[ime]

    def ogrej(self) -> None:
        """Odpre (ali ohrani) povezavo do streznika DoH z vprasanjem po imenu samega streznika - nic ne izda."""
        try:
            ponudnik, lasten = self._ponudnik_za_doh()
            if ponudnik == "custom":
                vrsta, url = razcleni_po_meri(lasten)
                gostitelj = urllib.parse.urlsplit(url).hostname or "" if vrsta == "doh" else ""
            elif ponudnik:
                gostitelj = urllib.parse.urlsplit(DOH_PROVIDERS.get(ponudnik, DOH_PROVIDERS["cloudflare"])["url"]).hostname or ""
            else:
                gostitelj = ""
            try:
                ipaddress.ip_address(gostitelj)
                gostitelj = "example.com"      # streznik z IP naslovom: nevtralno ime (IANA, nic ne izda)
            except ValueError:
                pass
            if gostitelj and (ponudnik, lasten) == (self.provider, self.custom_url):
                self._poizvedba(gostitelj, 3.5, 1)
            elif gostitelj:
                self._poizvedba(gostitelj, 3.5, 1, ponudnik, lasten)
        except Exception:  # noqa: BLE001
            pass

    def _ponudnik_za_doh(self) -> Tuple[str, str]:
        """(ponudnik, naslov po meri), ki mu gre poizvedba; pri Scitu je to streznik naprej ("" = usmerjevalnik)."""
        if self.provider == "scit":
            if self.naprej == "router":
                return "", ""
            return self.naprej, self.naprej_po_meri
        return self.provider, self.custom_url

    def pozabi(self, hostname: str) -> None:
        """Pozabi naslov imena (npr. star naslov ne sprejme povezave): naslednji resolve vpraša DoH znova."""
        h = (hostname or "").lower().strip().rstrip(".")
        with self._lock:
            self._cache.pop(h, None)

    def _osvezi_v_ozadju(self, h: str, timeout: float) -> None:
        with self._lock:
            generation = self._generacija()
            key = (generation, h)
            if key in self._pending:
                return
            event = threading.Event()
            self._pending[key] = event

        def osvezi() -> None:
            try:
                ip, ttl = self._query_doh(h, timeout)
                with self._lock:
                    # Neuspela osvezitev ne izbrise delujocega starega naslova.
                    if ip and generation == self._generacija():
                        self._cache[h] = (ip, time.time() + max(1, min(ttl, 3600)))
                        self._pocisti_predpomnilnik()
            except Exception:  # noqa: BLE001
                pass
            finally:
                with self._lock:
                    self._pending.pop(key, None)
                event.set()

        threading.Thread(target=osvezi, name="safeer-doh-osvezi", daemon=True).start()

    @staticmethod
    def _build_dns_wire_query(hostname: str, qtype: int = 1) -> bytes:
        """Poizvedba tipa A (qtype 1) ali AAAA (28). ID je 0, kot priporoca RFC 8484 (DoH), odgovor pa preverimo po imenu.

        Ime mora biti ze v obliki ASCII (IDNA, "xn--"): cesar ni mogoce zapisati, zavrnemo (ValueError),
        namesto da bi tiho izpustili znake in vprasali za drugo ime."""
        return b"\x00\x00\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00" + DoHResolver._ime_v_zapis(hostname) + qtype.to_bytes(2, "big") + b"\x00\x01"

    @staticmethod
    def _ime_v_zapis(hostname: str) -> bytes:
        oznake = str(hostname or "").strip().rstrip(".").split(".")
        zapis = bytearray()
        for oznaka in oznake:
            b = oznaka.encode("ascii")  # UnicodeEncodeError je ValueError
            if not b or len(b) > 63:
                raise ValueError("neveljavno ime")
            zapis.append(len(b))
            zapis.extend(b)
        zapis.append(0)
        if len(zapis) > 255:
            raise ValueError("predolgo ime")
        return bytes(zapis)

    @staticmethod
    def _preberi_ime(data: bytes, idx: int) -> Tuple[bytes, int]:
        """Ime v sporocilu DNS po RFC 1035 4.1.4: oznake in kazalci, tudi kazalec sredi imena (»www« + kazalec).

        Vrne (ime z malimi crkami, oznake locene s piko; indeks takoj za imenom na mestu zapisa). Zanka kazalcev, kazalec
        izven sporocila, rezervirana oznaka ali ime, daljse od 255 bajtov, je napaka (ValueError)."""
        oznake = []
        konec = -1
        skokov = 0
        dolzina = 1
        while True:
            if idx >= len(data):
                raise ValueError("ime presega sporocilo")
            n = data[idx]
            if n == 0:
                idx += 1
                break
            if n & 0xC0 == 0xC0:
                if idx + 1 >= len(data):
                    raise ValueError("kazalec presega sporocilo")
                if konec < 0:
                    konec = idx + 2
                skokov += 1
                kazalec = ((n & 0x3F) << 8) | data[idx + 1]
                if skokov > 32 or kazalec >= len(data):
                    raise ValueError("zanka ali kazalec izven sporocila")
                idx = kazalec
                continue
            if n & 0xC0:
                raise ValueError("rezervirana oblika oznake")
            if idx + 1 + n > len(data):
                raise ValueError("oznaka presega sporocilo")
            dolzina += n + 1
            if dolzina > 255:
                raise ValueError("predolgo ime")
            oznake.append(bytes(data[idx + 1:idx + 1 + n]).lower())
            idx += 1 + n
        return b".".join(oznake), (konec if konec >= 0 else idx)

    @staticmethod
    def _parse_dns_wire_response(data: bytes, hostname: str, qtype: int = 1) -> Tuple[Optional[str], int]:
        """IPv4 (qtype 1) ali IPv6 (qtype 28) naslov iz odgovora - samo ce je odgovor res na nase vprasanje (ID 0, isto ime, tip A/AAAA) in samo iz zapisa A,
        katerega lastnik je vprasano ime ali ime v verigi CNAME od njega naprej (zunanji pregled kode 8. 10. 2026: prej je
        vrnil prvi zapis A ne glede na lastnika, kazalec sredi imena pa je odgovor podrl)."""
        if len(data) < 12 or not data[2] & 0x80 or data[2] & 0x02 or data[3] & 0x0f:
            return None, 300
        try:
            vprasanje = DoHResolver._ime_v_zapis(hostname) + qtype.to_bytes(2, "big") + b"\x00\x01"
        except ValueError:
            return None, 300
        # Odgovor mora ponoviti nase vprasanje: en vnos, isto ime (velikost crk ni pomembna), tip A.
        if (data[0:2] != b"\x00\x00" or int.from_bytes(data[4:6], "big") != 1
                or data[12:12 + len(vprasanje)].lower() != vprasanje.lower()):
            return None, 300
        ime = str(hostname).strip().rstrip(".").lower().encode("ascii")
        try:
            ancount = int.from_bytes(data[6:8], "big")
            idx = 12 + len(vprasanje)
            naslovi = {}   # lastnik -> (ip, ttl), prvi zapis A za lastnika
            cname = {}     # lastnik -> (cilj, ttl)
            for _ in range(ancount):
                lastnik, idx = DoHResolver._preberi_ime(data, idx)
                if idx + 10 > len(data):
                    return None, 300
                rtype = int.from_bytes(data[idx:idx + 2], "big")
                rclass = int.from_bytes(data[idx + 2:idx + 4], "big")
                ttl = int.from_bytes(data[idx + 4:idx + 8], "big")
                rdlength = int.from_bytes(data[idx + 8:idx + 10], "big")
                idx += 10
                if idx + rdlength > len(data):
                    return None, 300
                if rclass == 1 and rtype == 1 and rdlength == 4 and qtype == 1:
                    naslovi.setdefault(lastnik, (".".join(str(b) for b in data[idx:idx + 4]), ttl))
                elif rclass == 1 and rtype == 28 and rdlength == 16 and qtype == 28:
                    naslovi.setdefault(lastnik, (str(ipaddress.IPv6Address(bytes(data[idx:idx + 16]))), ttl))
                elif rclass == 1 and rtype == 5:
                    cilj, _ = DoHResolver._preberi_ime(data, idx)
                    cname.setdefault(lastnik, (cilj, ttl))
                idx += rdlength
            # Veriga od vprasanega imena: najvec 8 CNAME, TTL najkrajsi v verigi.
            trenutno, najmanj = ime, None
            for _ in range(9):
                if trenutno in naslovi:
                    ip, ttl = naslovi[trenutno]
                    return ip, ttl if najmanj is None else min(ttl, najmanj)
                if trenutno not in cname:
                    break
                trenutno, ttl = cname[trenutno]
                najmanj = ttl if najmanj is None else min(ttl, najmanj)
        except (ValueError, IndexError):
            pass
        return None, 300

    def _query_doh(self, hostname: str, timeout: float) -> Tuple[Optional[str], int]:
        """Izbrani nacin: Scit (filter, nato streznik naprej) ali ponudnik; ob odpovedi samodejna rezerva (ce je vklopljena)."""
        if self.provider == "scit":
            return self._razresi_scit(hostname, timeout)
        izid = self._vprasaj(hostname, timeout, self.provider, self.custom_url)
        stanje = stanje_izida(izid)
        if stanje == NAPAKA and self.rezerva and self.provider != "custom":
            # Samo ob pravi napaki (SERVFAIL - tudi pokvarjen DNSSEC pri Quad9 -, cas, prenos) vprasamo drugega
            # ponudnika. Blokade, ki jo je vrnil ponudnik, ki ga je uporabnik izbral zato, ker filtrira (Quad9, AdGuard,
            # OpenDNS), rezerva ne obide (pregled 18. 10. 2026: prej je ime razresila pri Cloudflaru). Nikoli za ime, ki
            # ga blokira Scit sam.
            if not scit_kategorija(hostname, samo_z_diska=True):
                rezervni = REZERVNI_PONUDNIK.get(self.provider, "cloudflare")
                self._zabelezi_rezervo(self.provider, rezervni, stanje)
                drugi = self._vprasaj(hostname, timeout, rezervni, "")
                if stanje_izida(drugi) == OK:
                    return drugi
        return izid

    def _vprasaj(self, hostname: str, timeout: float, ponudnik: str, lasten: str) -> Tuple[Optional[str], int]:
        """Najprej A. Samo ce je strezniku uspelo odgovoriti in zapisa A ni (ne gre za napako ali blokado), vprasamo se
        za AAAA: strani samo z IPv6 se tako odprejo, namesto da bi padle s tihim 502."""
        if ponudnik == self.provider and lasten == self.custom_url:
            a = self._poizvedba(hostname, timeout, 1)       # pot, ki jo preizkusi lahko zamenjajo
            vprasaj = lambda q: self._poizvedba(hostname, timeout, q)  # noqa: E731
        else:
            a = self._poizvedba(hostname, timeout, 1, ponudnik, lasten)
            vprasaj = lambda q: self._poizvedba(hostname, timeout, q, ponudnik, lasten)  # noqa: E731
        if stanje_izida(a) != NI_IMENA:
            return a
        aaaa = vprasaj(28)
        return aaaa if aaaa[0] or stanje_izida(aaaa) == BLOKIRANO else a

    def _zabelezi_rezervo(self, od: str, na: str, razlog: str) -> None:
        with self._lock:
            self.stevci["rezerva"] += 1
            n = self.stevci["rezerva"]
        if n <= 3 or n % 100 == 0:      # dnevnik brez imen domen, samo stetje
            print("[DoH] rezerva: %s -> %s (%s), skupaj %d" % (od, na, razlog, n), flush=True)

    # ---- Safeer Scit kot DNS (privzeto)
    def _razresi_scit(self, hostname: str, timeout: float) -> Tuple[Optional[str], int]:
        """Ce sistemski Scit tece (127.0.0.1:5354-5357), vprasamo njega: filtrira in posreduje sam. Sicer filtriramo tu
        (isti nabor, os_scit.skupni_seznami) in razresimo prek streznika naprej; ce ta ne odgovori, sistemski DNS."""
        vrata = sistemski_scit_vrata()
        if vrata:
            izid = self._vprasaj_scit(hostname, timeout, vrata)
            if stanje_izida(izid) != NAPAKA:
                with self._lock:
                    self.stevci["sistemski_scit"] += 1
                return izid
        kategorija = scit_kategorija(hostname)
        if kategorija:
            with self._lock:
                self.stevci["scit_blokiral"] += 1
                self._blokirana[hostname] = kategorija
                while len(self._blokirana) > 64:
                    self._blokirana.pop(next(iter(self._blokirana)))
            return _izid(None, 300, BLOKIRANO)
        ponudnik, lasten = self._ponudnik_za_doh()
        if not ponudnik:
            return sistemski_dns(hostname)
        izid = self._vprasaj(hostname, timeout, ponudnik, lasten)
        if stanje_izida(izid) == NAPAKA and self.rezerva and ponudnik != "custom":
            # Samo ob pravi napaki; blokade ponudnika (filtrirni DNS, ki ga je izbral uporabnik) ne obidemo.
            self._zabelezi_rezervo(ponudnik, "sistemski DNS", stanje_izida(izid))
            drugi = sistemski_dns(hostname)
            if drugi[0]:
                self.nesifrirano_cas = time.time()      # ime je slo nesifrirano: Splet to mirno pokaze ob scitu
                return drugi
        return izid

    #: time.time() zadnjega imena, ki ga je bilo treba zaradi odpovedi DoH razresiti nesifrirano (0 = se nobenega).
    nesifrirano_cas = 0.0
    #: Kako dolgo po tem Splet kaze, da DNS ni sifriran (ko DoH spet odgovarja, oznaka izgine sama).
    NESIFRIRANO_S = 120.0

    def nesifrirano(self) -> bool:
        return bool(self.nesifrirano_cas) and time.time() - self.nesifrirano_cas < self.NESIFRIRANO_S

    def _vprasaj_scit(self, hostname: str, timeout: float, vrata: int) -> Tuple[Optional[str], int]:
        izid = _izid(None, 15, NAPAKA)
        for qtype in (1, 28):
            try:
                odgovor = vprasaj_navadno(NASLOV_SCITA, vrata, self._build_dns_wire_query(hostname, qtype), min(timeout, 2.0))
            except ValueError:
                return izid
            if odgovor is None:
                return izid
            stanje = razvrsti_odgovor(odgovor, "scit")
            if stanje != OK:
                return _izid(None, 300 if stanje == NI_IMENA else 15, stanje)
            ip, ttl = self._parse_dns_wire_response(odgovor, hostname, qtype)
            if ip:
                return _izid(ip, ttl, OK)
            izid = _izid(None, ttl, NI_IMENA)
        return izid

    def blokiral_scit(self, hostname: str) -> str:
        """Kategorija, ce je Scit to ime pravkar blokiral (za razumljivo stran napake); sicer ''."""
        h = (hostname or "").lower().strip().rstrip(".")
        with self._lock:
            return self._blokirana.get(h, "")

    def _poizvedba(self, hostname: str, timeout: float, qtype: int = 1, ponudnik: Optional[str] = None,
                   lasten: Optional[str] = None) -> Tuple[Optional[str], int]:
        ponudnik = self.provider if ponudnik is None else ponudnik
        lasten = self.custom_url if lasten is None else lasten
        try:
            telo = self._build_dns_wire_query(hostname, qtype)
        except ValueError:
            return _izid(None, 15, NAPAKA)
        if ponudnik == "custom":
            vrsta, vrednost = razcleni_po_meri(lasten)
            if vrsta == "ip":
                streznik, vrata = _naslov_in_vrata(vrednost)
                return self._iz_odgovora(vprasaj_navadno(streznik, vrata, telo, timeout), hostname, qtype, "custom")
            if vrsta != "doh":
                return _izid(None, 15, NAPAKA)
            # Lastni DoH: kot ga je vpisal (razcleni_po_meri ga je ze preveril); stari zapisi brez https odpadejo.
            base_url = lasten.strip() if lasten.strip().lower().startswith("https://") else vrednost
        else:
            base_url = DOH_PROVIDERS.get(ponudnik, DOH_PROVIDERS["cloudflare"])["url"]
        return self._iz_odgovora(self._poslji_doh(ponudnik, base_url, telo, timeout), hostname, qtype, ponudnik)

    def _iz_odgovora(self, odgovor, hostname: str, qtype: int, ponudnik: str) -> Tuple[Optional[str], int]:
        if odgovor is None:
            return _izid(None, 15, NAPAKA)
        if isinstance(odgovor, tuple):
            status, vrsta, data = odgovor
            if status != 200 or vrsta != "application/dns-message" or len(data) > 65535:
                return _izid(None, 15, NAPAKA)
        else:
            data = odgovor
        stanje = razvrsti_odgovor(data, ponudnik)
        if stanje == NAPAKA:
            return _izid(None, 15, NAPAKA)
        if stanje != OK:
            return _izid(None, 300, stanje)
        ip, ttl = self._parse_dns_wire_response(data, hostname, qtype)
        if ip and je_naslov_blokade(ip):
            return _izid(None, 300, BLOKIRANO)
        return _izid(ip, ttl, OK if ip else NI_IMENA)

    def _poslji_doh(self, ponudnik: str, base_url: str, telo: bytes, timeout: float):
        """POST na streznik DoH (libsoup 3, HTTP/2 - Quad9 ga zahteva; obicajno preverjanje potrdil, mimo posrednika).
        Ce sistemski DNS ne razresi imena ponudnika, gre poizvedba na njegov fallback_ip. Vrne (status, vrsta, telo) ali None."""
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return None
        if ponudnik == "custom" and not je_dovoljen_doh_streznik(parsed.hostname):
            return None
        rezerva = "" if ponudnik == "custom" else DOH_PROVIDERS.get(ponudnik, {}).get("fallback_ip", "")
        if rezerva == parsed.hostname:
            rezerva = ""
        try:
            odgovor = None
            if not (rezerva and time.time() < self._rezerva_do):
                try:
                    odgovor = _zanka_doh().poslji(base_url, telo, timeout)
                except ImeNiRazreseno:
                    if not rezerva:
                        return None
                    self._rezerva_do = time.time() + self.REZERVA_S
            if odgovor is None and rezerva and time.time() < self._rezerva_do:
                odgovor = self._poslji_na_rezervo(base_url, parsed, rezerva, telo, timeout)
            return odgovor
        except Exception:  # noqa: BLE001
            return None

    #: Kako dolgo po neuspeli razresitvi imena ponudnika gremo naravnost na fallback_ip (brez novega cakanja na DNS).
    REZERVA_S = 60
    _rezerva_do = 0.0

    @staticmethod
    def _poslji_na_rezervo(base_url: str, parsed, rezerva: str, telo: bytes, timeout: float):
        """Sistemski DNS ne razresi imena ponudnika (npr. dns.quad9.net): poizvedba gre na njegov stalni naslov IP.

        libsoup 3 ne zna povezati na izbran IP in hkrati poslati SNI/Host z imenom (identiteta TLS je vedno gostitelj
        iz URL-ja; ponarejen Gio.Resolver bi veljal za ves proces). Zato gre poizvedba na https://<IP>/..., kjer libsoup
        potrdilo preveri obicajno (veriga in IP v SAN; preverjeno 16. 10. 2026: Quad9, AdGuard, Google imajo IP v SAN),
        odgovor pa sprejmemo samo, ce isto potrdilo velja tudi za ime ponudnika. HTTP/2 ostane (Quad9 HTTP/1.1 zavrne s 505)."""
        url = urllib.parse.urlunsplit((parsed.scheme, rezerva + (f":{parsed.port}" if parsed.port else ""),
                                       parsed.path, parsed.query, ""))
        try:
            return _zanka_doh().poslji(url, telo, timeout, ime_potrdila=parsed.hostname)
        except ImeNiRazreseno:
            return None


class ImeNiRazreseno(Exception):
    """Sistemski DNS ni razresil imena streznika DoH (Gio.ResolverError): smiselna je rezerva na fallback_ip."""


class _ZankaDoH:
    """Ena seja libsoup na lastni niti z zanko GLib: vse poizvedbe DoH gredo po eni topli povezavi HTTP/2
    (vzporedne poizvedbe so prepletene na njej). Meritev 13. 10. 2026: ime ~40 ms (prej ~120 ms: vsaka povezava
    brskalnika je odprla svojo sejo in svoj TLS), 20 hkratnih imen v ~95 ms.

    libsoup 3 sejo veze na nit/kontekst, v katerem je nastala, zato jo uporabljamo samo iz te niti."""

    def __init__(self) -> None:
        self._kontekst = GLib.MainContext.new()
        self._seja = None
        pripravljena = threading.Event()

        def tek() -> None:
            self._kontekst.push_thread_default()
            seja = Soup.Session()
            # Brez posrednika (sicer bi DoH sel skozi nas posrednik); obicajno preverjanje potrdil ostane.
            seja.set_proxy_resolver(Gio.SimpleProxyResolver.new(None, []))
            # libsoup privzeto zapre mirujoco povezavo po 60 s; streznik (Cloudflare) jo drzi vsaj 2 min.
            seja.set_idle_timeout(240)
            self._seja = seja
            pripravljena.set()
            GLib.MainLoop.new(self._kontekst, False).run()

        threading.Thread(target=tek, name="safeer-doh", daemon=True).start()
        pripravljena.wait(5)

    def poslji(self, url: str, telo: bytes, timeout: float, ime_potrdila: str = "") -> Optional[Tuple[int, str, bytes]]:
        """POST application/dns-message; vrne (status, vrsta vsebine, telo) ali None (napaka, cas potekel).

        ime_potrdila: odgovor velja samo, ce potrdilo streznika velja tudi za to ime (rezerva na naslov IP).
        Ce ime streznika ni razreseno, sprozi ImeNiRazreseno."""
        if self._seja is None:
            return None
        konec = threading.Event()
        izid: dict = {}
        preklic = Gio.Cancellable()

        def zacni(*_a) -> bool:
            try:
                sporocilo = Soup.Message.new("POST", url)
                # IDEMPOTENT: poizvedba DNS je varna za ponovitev, zato libsoup sme uporabiti obstojeco povezavo
                # (za POST brez te zastavice odpre novo TCP + TLS povezavo za vsako poizvedbo).
                sporocilo.set_flags(Soup.MessageFlags.NO_REDIRECT | Soup.MessageFlags.IDEMPOTENT)
                sporocilo.set_request_body_from_bytes("application/dns-message", GLib.Bytes.new(telo))
                sporocilo.get_request_headers().append("Accept", "application/dns-message")

                def koncano(seja, rezultat, *_b) -> None:
                    try:
                        podatki = seja.send_and_read_finish(rezultat)
                        if ime_potrdila and not _potrdilo_velja_za(sporocilo.get_tls_peer_certificate(), ime_potrdila):
                            konec.set()
                            return
                        vrsta = sporocilo.get_response_headers().get_content_type()[0] or ""
                        izid["o"] = (int(sporocilo.get_status()), vrsta, bytes(podatki.get_data() or b""))
                    except GLib.Error as napaka:
                        izid["ime"] = napaka.domain == "g-resolver-error-quark"
                    except Exception:  # noqa: BLE001
                        pass
                    konec.set()

                self._seja.send_and_read_async(sporocilo, GLib.PRIORITY_DEFAULT, preklic, koncano)
            except Exception:  # noqa: BLE001
                konec.set()
            return False

        vir = GLib.idle_source_new()
        vir.set_callback(zacni)
        vir.attach(self._kontekst)
        if not konec.wait(max(0.5, timeout)):
            preklic.cancel()
            return None
        if izid.get("ime"):
            raise ImeNiRazreseno(url)
        return izid.get("o")


def _potrdilo_velja_za(potrdilo, ime: str) -> bool:
    """Potrdilo (ze preverjeno za naslov IP) velja tudi za ime ponudnika. Veriga je preverjena ob rokovanju, tu samo
    identiteta: brez potrdila ali z BAD_IDENTITY odgovora ne sprejmemo."""
    if potrdilo is None:
        return False
    try:
        zastavice = potrdilo.verify(Gio.NetworkAddress.new(ime, 443), None)
    except Exception:  # noqa: BLE001
        return False
    return not (zastavice & Gio.TlsCertificateFlags.BAD_IDENTITY)


_zanka: Optional[_ZankaDoH] = None
_zanka_zaklep = threading.Lock()


def _zanka_doh() -> _ZankaDoH:
    global _zanka
    with _zanka_zaklep:
        if _zanka is None:
            _zanka = _ZankaDoH()
        return _zanka

#: Najvec hkratnih tunelov (vsak je nit; nit miruje v select, dokler ni podatkov).
NAJVEC_POVEZAV = 256


def _brez_zamika(vticnica: socket.socket) -> None:
    """TCP_NODELAY: posrednik majhnih zapisov TLS (rokovanje, glave HTTP/2) ne zadrzuje (Nagle + zakasnjen ACK)."""
    try:
        vticnica.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except Exception:   # noqa: BLE001 - ni vticnica TCP (preizkus) ali je ze zaprta
        pass


def _preberi_tocno(vticnica: socket.socket, n: int) -> bytes:
    """Prebere natanko n bajtov (SOCKS5 pozdrav in zahteva); ob prekinjeni povezavi vrze OSError."""
    podatki = b""
    while len(podatki) < n:
        kos = vticnica.recv(n - len(podatki))
        if not kos:
            raise OSError("povezava prekinjena")
        podatki += kos
    return podatki


# Odgovori SOCKS5 (RFC 1928): 0 uspeh, 2 ni dovoljeno, 4 gostitelj nedosegljiv, 5 povezava zavrnjena,
# 7 ukaz ni podprt, 8 vrsta naslova ni podprta.
def _socks5_odgovor(koda: int) -> bytes:
    return bytes([5, koda, 0, 1, 0, 0, 0, 0, 0, 0])


def socks_ima_http2() -> bool:
    """Ali libsoup prek posrednika SOCKS5 govori HTTP/2.

    libsoup HTTP/2 izklopi za vsak posrednik "http" (soup-connection.c, is_not_using_http_proxy), za SOCKS5
    pa ne. Izmerjeno 13. 10. 2026: libsoup 3.6.6 (Flatpak GNOME 50) prek SOCKS5 http-2-0, libsoup 3.4.4 (Mint)
    ostane pri HTTP/1.1. Zato SOCKS5 uporabimo samo od 3.6 naprej; starejsi ostane pri preizkusenem HTTP CONNECT.
    """
    try:
        return (Soup.get_major_version(), Soup.get_minor_version()) >= (3, 6)
    except Exception:  # noqa: BLE001
        return False


def nastavitve_posrednika(WebKit, vrata: int, izjeme: List[str]):
    """NetworkProxySettings za lokalni DoH posrednik.

    Privzeto http://127.0.0.1:vrata (navaden HTTP dobi razumljive strani napak). Kjer libsoup prek SOCKS5 zna
    HTTP/2, gre https skozi socks5:// na istih vratih: brez tega je bil github.com hladno 1171 ms namesto 600 ms
    (HTTP/1.1 namesto HTTP/2). GLib ime poslje posredniku (SOCKS5 vrsta 3), zato DNS se vedno tece prek DoH.
    """
    p = WebKit.NetworkProxySettings.new("http://127.0.0.1:%d" % vrata, izjeme)
    if socks_ima_http2():
        p.add_proxy_for_scheme("https", "socks5://127.0.0.1:%d" % vrata)
    return p


class LocalDoHProxy:
    """
    Visoko-zmogljiv lokalni posredniški strežnik (Loopback CONNECT Proxy).
    Prestreza omrežne zahteve brskalnika WebKit2 ter razrešuje vsa imena gostiteljev
    prek DoH brez puščanja DNS podatkov lokalnemu ponudniku interneta.
    Posreduje samo na javne naslove in nikoli na nevarna vrata (SSH, SMTP, baze);
    povezav v lokalno omrežje, na povratni naslov ali na metapodatkovne naslove
    oblaka ne vzpostavi.
    """

    def __init__(self, resolver: DoHResolver, bind_host: str = "127.0.0.1", port: int = 0, dovoli_lokalno: bool = False):
        self.resolver = resolver
        self.dovoli_lokalno = bool(dovoli_lokalno)
        self.bind_host = bind_host
        self.requested_port = port
        self.actual_port = 0
        self.is_running = False
        self._server_sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        # Brskalnik drzi odprte povezave HTTP/2 in jih odpre vec na stran (novicarske strani: deset in vec gostiteljev).
        # S 64 je bil posrednik na velikih straneh poln in je nove povezave zavrnil (slike so cakale).
        self._slots = threading.BoundedSemaphore(NAJVEC_POVEZAV)
        self.zavrnjenih = 0
        self._sockets = set()
        self._socket_lock = threading.Lock()

    def start(self) -> int:
        """Zažene posrednika v ločeni niti in vrne dodeljena lokalna vrata."""
        if self.is_running:
            return self.actual_port

        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.bind_host, self.requested_port))
        self.actual_port = self._server_sock.getsockname()[1]
        self._server_sock.listen(128)
        self._server_sock.settimeout(1.0)

        self.is_running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True, name="SafeerDoHProxy")
        self._thread.start()
        # Povezavo do streznika DoH odpremo takoj (TCP + TLS ~110 ms), da je prva stran ne caka: meritev 13. 10. 2026,
        # 25 novih imen hkrati s toplo povezavo ~175 ms, s hladno ~330 ms.
        ogrej = getattr(self.resolver, "ogrej", None)
        if callable(ogrej):
            threading.Thread(target=ogrej, daemon=True, name="safeer-doh-ogrej").start()

        print(f"[DoH Proxy] Lokalni posrednik aktiviran na http://{self.bind_host}:{self.actual_port} (DoH: {self.resolver.provider})")
        return self.actual_port

    def stop(self):
        """Varno ustavi posredniški strežnik."""
        self.is_running = False
        with self._socket_lock:
            for sock in list(self._sockets):
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                sock.close()
            self._sockets.clear()
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass
            self._server_sock = None

    def _accept_loop(self):
        while self.is_running:
            client_sock, mesto = None, False
            try:
                client_sock, _ = self._server_sock.accept()
                if not self._slots.acquire(blocking=False):
                    self.zavrnjenih += 1
                    client_sock.close()
                    continue
                mesto = True
                _brez_zamika(client_sock)
                with self._socket_lock:
                    self._sockets.add(client_sock)
                t = threading.Thread(target=self._handle_client, args=(client_sock,), daemon=True)
                t.start()
            except socket.timeout:
                continue
            except Exception:
                if not self.is_running:
                    break
                # Povezava, ki ni dobila niti, ne sme vzeti mesta za vedno; trajna napaka (npr. EMFILE) pa ne sme
                # vrteti zanke brez premora.
                if client_sock is not None and mesto:
                    with self._socket_lock:
                        self._sockets.discard(client_sock)
                    self._slots.release()
                    try:
                        client_sock.close()
                    except OSError:
                        pass
                time.sleep(0.2)

    @staticmethod
    def _zavrni(client_sock: socket.socket, sporocilo: bytes):
        """Odgovori s 403 in zapre povezavo (cilj je zunaj dovoljenega obsega)."""
        try:
            client_sock.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n" + sporocilo)
        except Exception:
            pass
        try:
            client_sock.close()
        except Exception:
            pass

    @staticmethod
    def _napaka_502(client_sock: socket.socket, besedilo: str):
        """Razumljiv odgovor namesto praznega 502 (besedilo je ASCII, brez vsebine iz zahtevka)."""
        # Stran v barvah Safeerja namesto golega besedila (preizkus 14. 10. 2026: http:// naslov brez DNS je pokazal
        # vrstico »Safeer: ...« v pisavi terminala). Besedilo je nase (brez vsebine iz zahtevka), CSP brez skript.
        import html as _html
        deli = [_html.escape(d.strip()) for d in besedilo.split(" / ", 1)]
        telo = ("<!doctype html><html lang=sl><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                "<meta http-equiv=Content-Security-Policy content=\"default-src 'none'; style-src 'unsafe-inline'\">"
                "<title>Safeer</title><style>html{color-scheme:dark}body{background:#0c1420;color:#eef4fa;"
                "font:18px system-ui,sans-serif;max-width:620px;margin:12vh auto;padding:28px;line-height:1.6}"
                "h1{font-size:26px}p{color:#bdcadd}</style><h1>" + deli[0] + "</h1>"
                + ("<p>" + deli[1] + "</p>" if len(deli) > 1 else "") + "</html>").encode("utf-8")
        try:
            client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Type: text/html; charset=utf-8\r\n"
                                b"Content-Length: " + str(len(telo)).encode() + b"\r\nConnection: close\r\n\r\n" + telo)
        except Exception:
            pass
        try:
            client_sock.close()
        except Exception:
            pass

    def _povezi_z_osvezitvijo(self, client_sock: socket.socket, host: str, naslov: str,
                              vrata: int) -> Optional[socket.socket]:
        """Kot _vzpostavi_povezavo; ce naslov (morda star iz predpomnilnika) ne sprejme povezave, ime razresi
        znova in poskusi se enkrat na novem naslovu."""
        try:
            povezava = socket.create_connection((naslov, vrata), timeout=10.0)
            _brez_zamika(povezava)
            return povezava
        except OSError:
            pass
        try:
            self.resolver.pozabi(host)
            nov = self.resolver.resolve(host)
        except Exception:  # noqa: BLE001
            nov = None
        if nov and nov != naslov and je_dovoljen_cilj(nov, self.dovoli_lokalno):
            return self._vzpostavi_povezavo(client_sock, nov, vrata)
        self._napaka_povezave(client_sock, naslov)   # isti naslov: ne cakamo se enkrat do 10 s
        return None

    def _vzpostavi_povezavo(self, client_sock: socket.socket, naslov: str, vrata: int) -> Optional[socket.socket]:
        """Povezava na razresen naslov; pri neuspehu (npr. stran samo z IPv6, omrezje pa IPv6 nima) razumljiva napaka."""
        try:
            povezava = socket.create_connection((naslov, vrata), timeout=10.0)
            _brez_zamika(povezava)
            return povezava
        except OSError:
            self._napaka_povezave(client_sock, naslov)
            return None

    def _napaka_povezave(self, client_sock: socket.socket, naslov: str) -> None:
        if ":" in naslov:
            self._napaka_502(client_sock, "Ta stran je dosegljiva samo prek IPv6, vaše omrežje pa IPv6 ne omogoča. / "
                                          "This site is reachable only over IPv6, and your network does not provide it.")
        else:
            self._napaka_502(client_sock, "Povezava s strežnikom ni uspela. / Could not connect to the server.")

    def _pripravi_cilj(self, client_sock: socket.socket, host: str, port: int) -> Optional[str]:
        """
        Razreši ime prek DoH in preveri, ali je cilj sploh dovoljen.
        Vrne IP niz ali None, če je bila povezava zavrnjena (odgovor je že poslan).
        """
        if not je_dovoljena_vrata(port):
            self._zavrni(client_sock, b"Safeer: ta vrata niso dovoljena.")
            return None

        resolved_ip = self.resolver.resolve(host)
        if not resolved_ip:
            blokiral = getattr(self.resolver, "blokiral_scit", None)
            if callable(blokiral) and blokiral(host):
                self._napaka_502(client_sock, "Safeer Ščit je to stran blokiral (nevarna stran, oglasi ali sledenje). / "
                                              "Safeer Shield blocked this site (dangerous site, ads or tracking).")
                return None
            self._napaka_502(client_sock, "Strani s tem imenom ni bilo mogoče najti (DNS). / The site name could not be found (DNS).")
            return None

        if not je_dovoljen_cilj(resolved_ip, self.dovoli_lokalno):
            self._zavrni(client_sock, b"Safeer: povezava v lokalno omrezje je zavrnjena.")
            return None

        return resolved_ip

    def _handle_client(self, client_sock: socket.socket):
        remote_sock = None
        try:
            client_sock.settimeout(10.0)
            if client_sock.recv(1, socket.MSG_PEEK) == b"\x05":
                remote_sock = self._socks5(client_sock)
                return
            req_data = b""
            while b"\r\n\r\n" not in req_data and len(req_data) < 8192:
                chunk = client_sock.recv(2048)
                if not chunk:
                    break
                req_data += chunk

            if b"\r\n\r\n" not in req_data:
                client_sock.close()
                return

            headers, initial_body = req_data.split(b"\r\n\r\n", 1)
            header_line = req_data.split(b"\r\n", 1)[0].decode("latin1", errors="ignore")
            parts = header_line.split()
            if len(parts) < 2:
                client_sock.close()
                return

            method, target = parts[0].upper(), parts[1]

            if method == "CONNECT":
                # HTTPS Tunel: CONNECT example.com:443 HTTP/1.1
                if ":" in target:
                    host, port_s = target.rsplit(":", 1)
                    host = host.strip("[]")
                    port = int(port_s) if port_s.isdigit() else 443
                else:
                    host = target
                    port = 443

                resolved_ip = self._pripravi_cilj(client_sock, host, port)
                if not resolved_ip:
                    return

                remote_sock = self._povezi_z_osvezitvijo(client_sock, host, resolved_ip, port)
                if remote_sock is None:
                    return
                with self._socket_lock:
                    self._sockets.add(remote_sock)
                if not self.is_running:
                    return

                # Potrdi tunel narocniku
                client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")

                # Odstrani timeoute za neomejen podatkovni prenos (streaming, web)
                client_sock.settimeout(30.0)
                remote_sock.settimeout(30.0)

                if initial_body:
                    remote_sock.sendall(initial_body)

                # Dvosmerno pretakanje bajtov med klientom in oddaljenim streznikom
                self._pipe_sockets(client_sock, remote_sock)

            elif method in ("GET", "POST", "HEAD", "PUT", "DELETE", "OPTIONS", "PATCH"):
                # Obicajni HTTP Proxy zahtevek
                parsed = urllib.parse.urlparse(target)
                host = parsed.hostname or ""
                try:
                    port = parsed.port or 80
                except ValueError:
                    port = 0

                resolved_ip = self._pripravi_cilj(client_sock, host, port)
                if not resolved_ip:
                    return

                remote_sock = self._povezi_z_osvezitvijo(client_sock, host, resolved_ip, port)
                if remote_sock is None:
                    return
                with self._socket_lock:
                    self._sockets.add(remote_sock)
                if not self.is_running:
                    return

                # Preuredi zahtevek v relativno pot za ciljni streznik
                path = parsed.path or "/"
                if parsed.query:
                    path += f"?{parsed.query}"
                new_first_line = f"{method} {path} {parts[2] if len(parts) > 2 else 'HTTP/1.1'}\r\n".encode("latin1")
                rest_of_headers = b"\r\n".join(line for line in headers.split(b"\r\n")[1:]
                    if line.split(b":", 1)[0].lower() not in (b"proxy-authorization", b"proxy-connection")) + b"\r\n\r\n" + initial_body
                remote_sock.sendall(new_first_line + rest_of_headers)

                client_sock.settimeout(30.0)
                remote_sock.settimeout(30.0)
                self._pipe_sockets(client_sock, remote_sock)

            else:
                client_sock.close()

        except Exception:
            pass
        finally:
            with self._socket_lock:
                self._sockets.discard(client_sock)
                self._sockets.discard(remote_sock)
            self._slots.release()
            try:
                client_sock.close()
            except Exception:
                pass
            if remote_sock:
                try:
                    remote_sock.close()
                except Exception:
                    pass

    def _socks5(self, client_sock: socket.socket) -> Optional[socket.socket]:
        """SOCKS5 CONNECT brez prijave (RFC 1928), z istimi pravili kot HTTP CONNECT: dovoljena vrata, ime prek
        DoH, samo javni naslovi. Vrne oddaljeno vticnico (za pospravljanje v finally) ali None."""
        _ver, n = _preberi_tocno(client_sock, 2)
        metode = _preberi_tocno(client_sock, n)
        if 0 not in metode:
            client_sock.sendall(b"\x05\xff")
            return None
        client_sock.sendall(b"\x05\x00")
        ver, ukaz, _rez, vrsta = _preberi_tocno(client_sock, 4)
        if vrsta == 1:
            host = socket.inet_ntoa(_preberi_tocno(client_sock, 4))
        elif vrsta == 3:
            host = _preberi_tocno(client_sock, _preberi_tocno(client_sock, 1)[0]).decode("ascii", errors="replace")
        elif vrsta == 4:
            host = socket.inet_ntop(socket.AF_INET6, _preberi_tocno(client_sock, 16))
        else:
            client_sock.sendall(_socks5_odgovor(8))
            return None
        port = int.from_bytes(_preberi_tocno(client_sock, 2), "big")
        if ver != 5 or ukaz != 1:
            client_sock.sendall(_socks5_odgovor(7))
            return None
        if not je_dovoljena_vrata(port):
            client_sock.sendall(_socks5_odgovor(2))
            return None
        try:
            ipaddress.ip_address(host)
            naslov: Optional[str] = host
        except ValueError:
            naslov = self.resolver.resolve(host)
            if not naslov:
                client_sock.sendall(_socks5_odgovor(4))
                return None
        if not je_dovoljen_cilj(naslov, self.dovoli_lokalno):
            client_sock.sendall(_socks5_odgovor(2))
            return None
        remote_sock = self._socks5_povezi(host, naslov, port)
        if remote_sock is None:
            client_sock.sendall(_socks5_odgovor(5))
            return None
        with self._socket_lock:
            self._sockets.add(remote_sock)
        if not self.is_running:
            return remote_sock
        try:
            client_sock.sendall(_socks5_odgovor(0))
            client_sock.settimeout(30.0)
            remote_sock.settimeout(30.0)
            self._pipe_sockets(client_sock, remote_sock)
        except BaseException:
            # Brskalnik je odsel pred odgovorom: klicatelj vticnice se nima (vrnjena ni bila) - zapremo jo tu, sicer
            # bi ostala odprta in v self._sockets do konca procesa.
            with self._socket_lock:
                self._sockets.discard(remote_sock)
            try:
                remote_sock.close()
            except OSError:
                pass
            raise
        return remote_sock

    def _socks5_povezi(self, host: str, naslov: str, vrata: int) -> Optional[socket.socket]:
        """Kot _povezi_z_osvezitvijo, a brez odgovora HTTP (napako SOCKS5 poslje klicatelj)."""
        for poskus in range(2):
            try:
                povezava = socket.create_connection((naslov, vrata), timeout=10.0)
                _brez_zamika(povezava)
                return povezava
            except OSError:
                pass
            if poskus or host == naslov:
                return None
            try:
                self.resolver.pozabi(host)
                nov = self.resolver.resolve(host)
            except Exception:  # noqa: BLE001
                nov = None
            if not nov or nov == naslov or not je_dovoljen_cilj(nov, self.dovoli_lokalno):
                return None
            naslov = nov
        return None

    def _pipe_sockets(self, s1: socket.socket, s2: socket.socket):
        """Asinhrono dvosmerno posredovanje podatkov z nicelno zakasnitvijo."""
        from core import os_deskriptorji
        sockets = [s1, s2]
        bufsize = 65536
        while self.is_running:
            try:
                # Brez meje 1024 (select): napaka ali konec povezave je berljiv dogodek, recv vrne b"" ali napako.
                readable = os_deskriptorji.berljivi(sockets, 60.0)
                if not readable:
                    break

                for s in readable:
                    data = s.recv(bufsize)
                    if not data:
                        return
                    target = s2 if s is s1 else s1
                    target.sendall(data)
            except Exception:
                break


# Globalni primerek posrednika za enojni vir resnice (Single Source of Truth)
_global_resolver: Optional[DoHResolver] = None
_global_proxy: Optional[LocalDoHProxy] = None
_proxy_lock = threading.Lock()


def get_doh_proxy(provider: str = "cloudflare", custom_url: str = "", enabled: bool = True,
                  lokalno: bool = False, naprej: str = PRIVZETI_NAPREJ, naprej_po_meri: str = "",
                  rezerva: bool = True) -> Optional[LocalDoHProxy]:
    """Pridobi ali inicializira globalni primerek DoH posrednika.

    Posrednik je skupen za ves proces (Splet v oknu, Splet na namizju s kanali Sporocil ...). enabled=False samo vrne
    None - klicatelj svojo sejo preklopi na neposredno povezavo, posrednika pa NE ustavi (pregled 18. 10. 2026: izklop
    DNS v enem Spletu je ustavil posrednika in drugi Splet je ostal na mrtvih vratih; ob ponovnem vklopu so bila vrata
    nova). Ustavi ga samo ustavi_doh_proxy() ob izhodu, zato vrata ostanejo ista ves cas procesa."""
    global _global_resolver, _global_proxy
    with _proxy_lock:
        if not enabled:
            return None

        if _global_resolver is None:
            _global_resolver = DoHResolver(provider, custom_url, naprej, naprej_po_meri, rezerva)
        else:
            _global_resolver.set_provider(provider, custom_url, naprej, naprej_po_meri, rezerva)

        if _global_proxy is None:
            _global_proxy = LocalDoHProxy(_global_resolver, dovoli_lokalno=lokalno)
            _global_proxy.start()
            # Stran safeer://procesi: sifriran DNS Spleta tece, dokler tece Splet (varuje - ni storitev na zahtevo).
            from core import storitve_na_zahtevo
            storitve_na_zahtevo.registriraj("doh", storitve_na_zahtevo.VEDNO, tece=lambda: _global_proxy is not None,
                                            razlog=storitve_na_zahtevo.VARUJE)
        else:
            _global_proxy.dovoli_lokalno = bool(lokalno)

        return _global_proxy


def dns_nesifriran() -> bool:
    """Ali so imena Spleta (ali Scita v tem procesu, ki ga Splet vprasa) nazadnje sla nesifrirano, ker sifriran DNS ni
    odgovoril. Brez okna in opozorila: Splet to mirno pokaze ob scitu v vrstici (pregled 18. 10. 2026: tiha izguba
    DoH ni bila vidna nikjer)."""
    r = _global_resolver
    if r is not None and r.nesifrirano():
        return True
    if r is not None and r.provider != "scit":
        return False
    try:
        import sys
        os_scit = sys.modules.get("core.os_scit")
        return bool(os_scit is not None and os_scit.nesifrirano_v_procesu())
    except Exception:  # noqa: BLE001
        return False


def ustavi_doh_proxy() -> None:
    """Ustavi skupni posrednik - samo ob izhodu procesa (nikoli ob spremembi nastavitev ene seje)."""
    global _global_proxy
    with _proxy_lock:
        if _global_proxy is not None:
            _global_proxy.stop()
            _global_proxy = None


_posrednik_scita: Optional["DoHResolver"] = None


def posreduj_paket(ponudnik: str, lasten: str, paket: bytes, timeout: float) -> Optional[bytes]:
    """Sistemski Scit posreduje poizvedbo (cel paket, s svojim ID) strezniku naprej: DoH ponudniku ali strezniku po meri
    (DoH ali IP). None = ni odgovora ali SERVFAIL: Scit vprasa usmerjevalnik. ID je pri DoH 0 (RFC 8484), vrnemo izvirnega."""
    global _posrednik_scita
    if len(paket) < 12:
        return None
    if _posrednik_scita is None:
        _posrednik_scita = DoHResolver("cloudflare")
    telo = b"\x00\x00" + paket[2:]
    if ponudnik == "custom":
        vrsta, vrednost = razcleni_po_meri(lasten)
        if vrsta == "ip":
            streznik, vrata = _naslov_in_vrata(vrednost)
            data = vprasaj_navadno(streznik, vrata, telo, timeout)
        elif vrsta == "doh":
            o = _posrednik_scita._poslji_doh("custom", lasten.strip() if lasten.strip().lower().startswith("https://")
                                              else vrednost, telo, timeout)
            data = o[2] if o and o[0] == 200 and o[1] == "application/dns-message" else None
        else:
            return None
    elif ponudnik in DOH_PROVIDERS:
        o = _posrednik_scita._poslji_doh(ponudnik, DOH_PROVIDERS[ponudnik]["url"], telo, timeout)
        data = o[2] if o and o[0] == 200 and o[1] == "application/dns-message" else None
    else:
        return None
    if not data or len(data) < 12 or len(data) > 65535 or data[3] & 0x0F == 2:
        return None
    if _blokada_ponudnika(data, ponudnik):
        # Ponudnik je ime blokiral (uporabnik ga je izbral zato, ker filtrira - druzinski DNS, Quad9, AdGuard): to je
        # odgovor, ne napaka, zato ne gremo k usmerjevalniku (pregled 18. 10. 2026: prej je rezerva blokado obsla).
        # Odjemalec dobi NXDOMAIN namesto 0.0.0.0 - povezava na 0.0.0.0 bi na Linuxu sla na ta racunalnik.
        return _nxdomain(paket)
    return paket[:2] + data[2:]


def _nxdomain(paket: bytes) -> bytes:
    """NXDOMAIN z ID in vprasanjem izvirne poizvedbe (kot ga vrne Scit za blokirano ime)."""
    konec = 12
    while konec < len(paket) and paket[konec] != 0:
        konec += 1 + paket[konec]
    konec += 5
    return paket[:2] + b"\x81\x83\x00\x01\x00\x00\x00\x00\x00\x00" + paket[12:konec]


def _blokada_ponudnika(data: bytes, ponudnik: str) -> bool:
    """Odgovor je blokada: NXDOMAIN brez SOA ali REFUSED pri ponudnikih, ki blokirajo, ali (pri vseh, tudi po meri)
    naslov blokade - 0.0.0.0, ::, stran blokade OpenDNS."""
    stanje = razvrsti_odgovor(data, ponudnik)
    if stanje != OK:
        return stanje == BLOKIRANO
    try:
        ime, idx = DoHResolver._preberi_ime(data, 12)
        qtype = int.from_bytes(data[idx:idx + 2], "big")
        ip, _ttl = DoHResolver._parse_dns_wire_response(b"\x00\x00" + data[2:], ime.decode("ascii"), qtype)
    except (ValueError, UnicodeError):
        return False
    return bool(ip) and je_naslov_blokade(ip)


#: Streznik naprej za izbiro »Safeer Scit« ima en sam vir (lastnik, 18. 10. 2026: nastavitve Scita na enem mestu, ki se ne
#: morejo razhajati). V procesu s Safeer OS je to Scit (core/os_scit.Scit: naprej(), nastavi_naprej()) - isti streznik
#: velja za ves racunalnik in za Splet; prej sta Splet (ConfigManager) in Scit (shramba Safeer OS) imela vsak svojega.
#: Brez vira (samostojni Safeer Browser) velja ConfigManager.
_vir_naprej = None


def nastavi_vir_naprej(vir) -> None:
    global _vir_naprej
    _vir_naprej = vir


def naprej_iz(config) -> Tuple[str, str]:
    """(izbira, naslov po meri) streznika naprej iz enega vira (Scit v Safeer OS ali nastavitve brskalnika)."""
    vir = _vir_naprej
    if vir is not None:
        try:
            izbira, po_meri = vir.naprej()
            return (izbira if izbira in IZBIRE_NAPREJ else PRIVZETI_NAPREJ), str(po_meri or "")
        except Exception:  # noqa: BLE001
            pass
    izbira = config.get("scit_naprej", PRIVZETI_NAPREJ) if config is not None else PRIVZETI_NAPREJ
    po_meri = str(config.get("scit_naprej_po_meri", "") or "") if config is not None else ""
    return (izbira if izbira in IZBIRE_NAPREJ else PRIVZETI_NAPREJ), po_meri


def shrani_naprej(config, izbira: str, po_meri: str = "") -> str:
    """Shrani streznik naprej v en vir; vrne kljuc napake (prazno = shranjeno)."""
    vir = _vir_naprej
    if vir is not None:
        stanje = vir.nastavi_naprej(izbira, po_meri) or {}
        return str(stanje.get("napaka") or "")
    config.set("scit_naprej", izbira)
    if izbira == "custom":
        config.set("scit_naprej_po_meri", po_meri)
    return ""


def osvezi_naprej() -> None:
    """Scit je dobil nov streznik naprej: Splet (skupni razresevalnik) ga uporabi takoj, s praznim predpomnilnikom."""
    r, vir = _global_resolver, _vir_naprej
    if r is not None and vir is not None:
        izbira, po_meri = naprej_iz(None)
        r.set_provider(r.provider, r.custom_url, izbira, po_meri)


def doh_iz_nastavitev(config, lokalno: Optional[bool] = None) -> Optional[LocalDoHProxy]:
    """Posrednik po nastavitvah brskalnika (ConfigManager) - ena pot za Splet in Safeer Browser."""
    izbira = config.get("doh_provider", PRIVZETI_DNS)
    if not config.get("doh_enabled", True) or izbira == "disabled":
        return get_doh_proxy(enabled=False)
    if izbira not in IZBIRE_DNS:
        izbira = PRIVZETI_DNS
    naprej, naprej_po_meri = naprej_iz(config)
    return get_doh_proxy(provider=izbira, custom_url=config.get("custom_doh_url", "") or "", enabled=True,
                         lokalno=bool(config.get("doh_lokalno_omrezje", False)) if lokalno is None else lokalno,
                         naprej=naprej, naprej_po_meri=naprej_po_meri,
                         rezerva=bool(config.get("dns_rezerva", False)))


def preizkusi_dns(besedilo: str, timeout: float = 3.5) -> Tuple[bool, str]:
    """Poskusna poizvedba (example.com) na streznik po meri: (uspeh, kljuc besedila). Za gumb »Preizkusi« v nastavitvah."""
    vrsta, vrednost = razcleni_po_meri(besedilo)
    if not vrsta:
        return False, vrednost
    r = DoHResolver("custom", besedilo)
    ip, _ttl = r._query_doh("example.com", timeout)
    return (True, "doh_po_meri_dela") if ip else (False, "doh_po_meri_ne_odgovori")
