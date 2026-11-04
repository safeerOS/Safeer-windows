"""Scit za Safeer OS na Windows: filtriranje DNS za ves racunalnik - ISTA pravila kot na Linuxu in Androidu.

Lastnik 4. 11. 2026: »ni optimalno delati vec Scitov za razlicne OS«. Odlocanje (kaj Scit ustavi, izjeme uporabnika,
krajevna imena, zasciteni gostitelji, kanarcek, streznik naprej, SERVFAIL brez krajevnega DNS, roki) je DOBESEDNO
prepisano iz Safeer-linux core/os_scit.py - deli med oznakama »SKUPNO Z LINUXOM«. Preverja ga
tests/skupni-primeri/scit-pravila.json (bajt za bajt ista datoteka kot v Safeer-linux in Android-tv) v
windows/tests/test_scit_skupni_primeri_win.py. Pravila telemetrije storitev so v core/scit_pravila.py (skupna datoteka).

Razlicno od Linuxa je samo prestrezanje DNS (systemd-resolved na Windows ni):
  - razresevalnik poslusa na 127.0.0.1:53 in [::1]:53 - DNS odjemalec Windows drugih vrat ne pozna (5354-5357 na
    Windows ne delujejo). Ce so vrata 53 zasedena, Scit ne filtrira in to pove (napaka »vrata«), nikoli tiho;
  - vmesnik dobi SAMO Scit (127.0.0.1, ::1). DNS usmerjevalnika NI drugi streznik vmesnika: Windows bi ga vprasal,
    kadar Scit ne odgovori dovolj hitro ali po svoje - mimo Scita (porocilo 4. 11. 2026). Kam Scit poslje dovoljena
    imena: privzeto krajevni DNS (kar je imel vmesnik pred Scitom, DHCP), uporabnik izbere sam (DoH ali svoj streznik);
    brez krajevnega DNS SERVFAIL takoj, nikoli tuj rezervni razresevalnik (prej 1.1.1.1, 9.9.9.9, 8.8.8.8);
  - straza v procesu vsakih PREGLED_S preveri, da Scit odgovarja (kanarcek); ce ne in ga ne more znova zagnati, vrne
    vmesnikom krajevni DNS. Ce proces Safeer OS pade, vrne DNS straza ob padcu (skrit PowerShell, ki caka na konec
    procesa) - racunalnik ne ostane brez DNS.
Ukazi PowerShell gredo kot -EncodedCommand z absolutno potjo iz System32; imena vmesnikov kot niz z ubeznico (ps_niz).
"""

from __future__ import annotations

import base64
import bisect
import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import weakref
from array import array
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from core import webtor
from core.signed_feed import _atomic_write, isti_gostitelj

NASLOV = "127.0.0.1"
NASLOV6 = "::1"
#: Windows: DNS odjemalec vprasa samo vrata 53 (streznika z drugimi vrati ni mogoce nastaviti).
VRATA = (53,)
#: Najvec, kar vmesnikov Scit nastavi (straza ob padcu jih nosi v ukazni vrstici).
NAJVEC_VMESNIKOV = 16
#: Straza preveri Scit in vmesnike vsakih toliko sekund (prej enako, 20 s).
PREGLED_S = 20.0

# >>> SKUPNO Z LINUXOM (Safeer-linux 746f975 core/os_scit.py: konstante) - ne spreminjaj samo tu
CAS_UPSTREAM = 2.5
#: Toliko najvec caka nas odgovor na sifriran streznik naprej (DoH), preden isto ime vprasamo usmerjevalnik. systemd-resolved
#: na nas caka ~750 ms (DNS_TIMEOUT_MIN_USEC), nato vprasa naslednji streznik - usmerjevalnik, MIMO Scita - in pri njem
#: ostane: do naslednjega pregleda straze (PREGLED_S) bi se blokirane strani razresevale. CI 8ac36e9 (Flatpak, brez
#: interneta): DoH je cakal 2,5 s, resolved je presel na usmerjevalnik in »Blokiraj spet« ni veljal. Odgovor zato
#: vedno v ROK_NAPREJ + cas usmerjevalnika (LAN); DoH tece naprej v ozadju in odloci, ali gremo za nekaj casa mimo njega.
ROK_NAPREJ = 0.4
#: Varovalo niti: toliko poizvedb sme hkrati cakati na DoH. DoH, ki visi, zazna _naprej_visi po STAROSTI najstarejse
#: cakajoce poizvedbe; stevilo samo ne pomeni nic - ena stran (5 imen x A in AAAA) jih hkrati vprasa 10 in vec.
#: Prej (meja 8, 19. 10. 2026) je navadno nalaganje strani za 30 s preklopilo DNS na nesifrirano (neodvisni pregled).
NAJVEC_CAKAJOCIH_NAPREJ = 64
#: Strezniki naprej (isti kljuci kot core/doh_proxy.IZBIRE_NAPREJ; tu, da modul ne potrebuje libsoup ob uvozu).
IZBIRE_NAPREJ = ("router", "cloudflare", "quad9", "google", "adguard", "opendns", "custom")
#: Privzeto krajevni DNS (lastnik 4. 11. 2026): velja, dokler uporabnik ne izbere (shranjena izbira ostane).
PRIVZETI_NAPREJ = "router"

#: Seznami domen - isti kot pri Scitu na televizorju (ThreatFeedsUpdater). Kategorija je kljuc za besedila.
VIRI: Tuple[Tuple[str, str, str], ...] = (
    ("hagezi-pro", "https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/wildcard/pro-onlydomains.txt", "oglasi"),
    ("hagezi-tif", "https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/wildcard/tif.mini-onlydomains.txt", "groznje"),
    ("hagezi-fake", "https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/wildcard/fake-onlydomains.txt", "prevare"),
    ("urlhaus", "https://urlhaus.abuse.ch/downloads/hostfile/", "malware"),
    ("phishing-army", "https://phishing.army/download/phishing_army_blocklist_extended.txt", "phishing"),
    ("si-cert", "https://www.cert.si/misp/rpz/last.txt", "phishing"),
)
KATEGORIJE = ("oglasi", "groznje", "prevare", "malware", "phishing", "botnet")
#: Premor ustavi samo to kategorijo (oglasi in sledenje); vse druge so nevarne strani in ostanejo blokirane.
KATEGORIJA_PREMORA = "oglasi"
KATEGORIJA_SEZNAMA_GROZNJ = {"botnet_c2": "botnet", "malware": "malware", "phishing": "phishing", "scam": "prevare"}
NAJVEC_BAJTOV = 24 * 1024 * 1024
NAJMANJ_DOMEN = 1000
PRVA_OSVEZITEV = 5.0
OSVEZITEV = 6 * 3600.0
PONOVNI_POSKUS = 30 * 60.0
# <<< SKUPNO Z LINUXOM (konstante)
# >>> SKUPNO Z LINUXOM (Safeer-linux 746f975 core/os_scit.py: pravila) - ne spreminjaj samo tu
#: Krajevna imena (RFC 6761, 6762, 8375; .internal): Scit jih nikoli ne ustavi, niti seznam grozenj - v javnem DNS jih
#: ni. Isto pravilo na Androidu (ScitOdlocitev.kt), skupni primeri tests/skupni-primeri/scit-pravila.json.
KRAJEVNA = ("localhost",)
KRAJEVNE_KONCNICE = (".localhost", ".local", ".lan", ".home", ".internal", ".arpa")
#: Firefox (in podobni) vprasa to ime, preden sam vklopi DoH; NXDOMAIN = ostane pri sistemskem DNS, torej pri Scitu.
KANAREK_DOH = "use-application-dns.net"


def je_krajevno(ime: str) -> bool:
    return ime in KRAJEVNA or ime.endswith(KRAJEVNE_KONCNICE)
#: Posodobitve sistema in Safeerja: pot do popravka mora ostati odprta, tudi ce bi seznam s
#: preusmeritvijo ali okvaro na CDN-ju dobil napacne vnose. Velja tudi za poddomene (zrcala).
POSODOBITVE = ("archive.ubuntu.com", "security.ubuntu.com", "ports.ubuntu.com", "ppa.launchpadcontent.net",
               "packages.linuxmint.com", "deb.debian.org", "security.debian.org", "flathub.org",
               "github.com", "api.github.com", "objects.githubusercontent.com",
               "release-assets.githubusercontent.com")

#: Strani s preverjanjem »ali si clovek« (Cloudflare Turnstile, hCaptcha, reCAPTCHA): ce bi jih seznam blokiral, se
#: prijave in nakupi ne bi dali dokoncati (lastnik, 16. 10. 2026). Velja tudi za poddomene.
PREVERJANJE = ("cloudflare.com", "hcaptcha.com", "recaptcha.net", "www.google.com", "www.gstatic.com")


def je_preverjanje(ime: str) -> bool:
    return any(ime == d or ime.endswith("." + d) for d in PREVERJANJE)


#: Posrednik systemd-resolved (stub): vse, kar dobi, poslje Scitu - streznik naprej tja bi bil zanka.
RESOLVED_STUB = ("127.0.0.53", "127.0.0.54")


def je_zanka_naprej(vrednost: str) -> bool:
    """Streznik naprej po meri (»naslov«, »naslov:vrata«, »[v6]:vrata«), ki bi poizvedbo vrnil Scitu ali Spletu:
    Scit sam (127.0.0.1:5354-5357), posrednik systemd-resolved (ta sprasuje Scit) ali lokalni posrednik DoH Spleta
    v tem procesu (ta ni streznik DNS; pregled 18. 10. 2026: zanka DoH). Domaci Pi-hole ali dnscrypt-proxy na
    127.0.0.1:5053 je dovoljen."""
    v = str(vrednost or "").strip()
    naslov, vrata = v, 53
    if v.startswith("["):
        naslov, _, ostalo = v[1:].partition("]")
        vrata = int(ostalo[1:]) if ostalo.startswith(":") and ostalo[1:].isdigit() else 53
    elif v.count(":") == 1:
        naslov, _, del_vrat = v.partition(":")
        vrata = int(del_vrat) if del_vrat.isdigit() else 53
    try:
        ip = ipaddress.ip_address(naslov)
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped
    if not ip.is_loopback:
        return False
    if str(ip) in RESOLVED_STUB or vrata in VRATA:
        return True
    try:
        import sys
        doh = sys.modules.get("core.doh_proxy")
        posrednik = getattr(doh, "_global_proxy", None) if doh is not None else None
        return bool(posrednik is not None and vrata == getattr(posrednik, "actual_port", 0))
    except Exception:  # noqa: BLE001
        return False


#: Najvec domen, ki jih uporabnik dovoli sam (izjeme), in najdaljsi premor Scita.
NAJVEC_IZJEM = 50
#: Uporabnikova izjema velja 30 dni (kot Android ScitPregled.IZJEMA_MS), potem Scit ime spet ustavi.
IZJEMA_S = 30 * 24 * 3600
NAJDALJSI_PREMOR_MIN = 60
_DOMENA = re.compile(r"^(?=.{4,253}$)[a-z0-9_]([a-z0-9_-]{0,61}[a-z0-9_])?(\.[a-z0-9_]([a-z0-9_-]{0,61}[a-z0-9_])?)+$")


def cista_domena(besedilo) -> str:
    """Ime domene z malimi crkami in brez pike na koncu; '' ce to ni ime domene."""
    d = str(besedilo or "").strip().lower().rstrip(".")
    return d if _DOMENA.match(d) else ""


def _je_telemetrija(ime: str) -> bool:
    """Gostitelj, ki ga storitev uporablja samo za telemetrijo ali oglase (core/scit_pravila.py, »telemetrija«: npr.
    dit.whatsapp.net, spade.twitch.tv) - Scit ga zavrne za ves racunalnik, tudi za namizne programe. Sledilcev tretjih
    (»sledilci«) DNS ne blokira: tu ni mogoce locit tretje strani od obiska njihove strani (to naredi filter WebKit)."""
    try:
        from core import scit_pravila
        return any(ime == t or ime.endswith("." + t) for t in scit_pravila.trenutna().telemetrija)
    except Exception:  # noqa: BLE001
        return False


def je_posodobitev(ime: str) -> bool:
    return any(ime == d or ime.endswith("." + d) for d in POSODOBITVE)


#: Zasciteni gostitelji (s poddomenami): posodobitve, preverjanje cloveka in Safeer. Seznami OGLASOV jih ne ustavijo
#: (zastrupljen ali preobsiren seznam ne sme zapreti popravkov in prijav); seznam GROZENJ jih ustavi vedno - tudi
#: Safeerjeva stran ali zrcalo, ki ga nekdo prevzame (lastnik 4. 11. 2026; prej so bili spuscani tudi kot groznja).
ZASCITENI = POSODOBITVE + PREVERJANJE + ("safeer.si",)


def je_zasciten(ime: str) -> bool:
    return any(ime == d or ime.endswith("." + d) for d in ZASCITENI)
# <<< SKUPNO Z LINUXOM (pravila)


# ---------------------------------------------------------------------- Windows: pomocno
#: Windows: podprocesi brez konzolnega okna (lastnik 27. 10. 2026: Straza Scita je vsakih 20 s za trenutek odprla okno
#: PowerShella, ker je SafeerOS.exe zgrajen brez konzole); drugod 0.
_BREZ_OKNA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _sistemski(*deli: str) -> str:
    """Absolutna pot programa v System32. CreateProcess ime brez poti isce tudi v mapi programa in trenutni mapi -
    podtaknjen powershell.exe bi tekel s pravicami Safeer OS (za DNS je to skrbnik)."""
    koren = os.environ.get("SystemRoot") or os.environ.get("windir") or "C:\\Windows"
    return "\\".join([koren.rstrip("\\/")] + ["System32"] + list(deli))


POWERSHELL = ("WindowsPowerShell", "v1.0", "powershell.exe")
NETSH = ("netsh.exe",)


def podatkovna_mapa() -> str:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "SafeerOS", "scit")
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "safeer-mint", "scit")


# >>> SKUPNO Z LINUXOM (Safeer-linux 746f975 core/os_scit.py: dns) - ne spreminjaj samo tu
# ---------------------------------------------------------------------- DNS
def ime_poizvedbe(paket: bytes) -> str:
    """Ime iz vprasanja DNS (malo, brez pike na koncu); '' ce paket ni vprasanje."""
    try:
        if len(paket) < 17 or (paket[2] & 0x80):
            return ""
        i, deli = 12, []
        while i < len(paket):
            d = paket[i]
            if d == 0:
                break
            if d & 0xC0:
                return ""
            deli.append(paket[i + 1:i + 1 + d].decode("ascii", "replace"))
            i += 1 + d
        return ".".join(deli).lower().rstrip(".")
    except Exception:
        return ""


def _odgovor_z(paket: bytes, zastavice: int) -> bytes:
    konec = 12
    while konec < len(paket) and paket[konec] != 0:
        konec += 1 + paket[konec]
    konec += 5
    glava = paket[:2] + struct.pack("!HHHHH", zastavice, 1, 0, 0, 0)
    return glava + paket[12:konec]


def odgovor_zavrnjeno(paket: bytes) -> bytes:
    """NXDOMAIN z istim id in vprasanjem: racunalnik takoj ve, da imena ni."""
    return _odgovor_z(paket, 0x8183)


def odgovor_napaka(paket: bytes) -> bytes:
    """SERVFAIL z istim id in vprasanjem: ni krajevnega DNS - odgovor takoj, ne molk (molk caka rok odjemalca)."""
    return _odgovor_z(paket, 0x8182)


#: Najvecji odgovor prek UDP (priporocilo DNS Flag Day 2020); vecji gre s TC, odjemalec vprasa prek TCP.
NAJVEC_UDP = 1232


def prirezan(paket: bytes) -> bytes:
    """Odgovor s TC (prirezano) in istim vprasanjem: odjemalec ponovi poizvedbo prek TCP."""
    konec = 12
    while konec < len(paket) and paket[konec] != 0:
        konec += 1 + paket[konec]
    konec += 5
    return paket[:2] + struct.pack("!HHHHH", 0x8380, 1, 0, 0, 0) + paket[12:konec]
# <<< SKUPNO Z LINUXOM (dns)


def za_vticnico(streznik: str, vmesnik: str) -> str:
    """Naslov za nase posredovanje: povezavno-lokalni IPv6 (fe80::) potrebuje se vmesnik (na Windows njegov indeks)."""
    try:
        if ":" in streznik and "%" not in streznik and ipaddress.ip_address(streznik).is_link_local:
            return streznik + "%" + vmesnik
    except ValueError:
        pass
    return streznik


# >>> SKUPNO Z LINUXOM (Safeer-linux 746f975 core/os_scit.py: razresevalnik) - ne spreminjaj samo tu
class Razresevalnik:
    """Razresevalnik DNS (UDP in TCP) na 127.0.0.1: blokirana imena zavrne, ostala posreduje."""

    def __init__(self, blokiraj: Callable[[str], Optional[str]], upstream: Callable[[], List[str]],
                 naprej: Optional[Callable[[bytes], Optional[bytes]]] = None,
                 zagonsko: Optional[Callable[[str], bool]] = None) -> None:
        self.blokiraj = blokiraj
        self.upstream = upstream
        #: Sifriran streznik naprej (DoH); None ali odpoved (cas, SERVFAIL) = strezniki usmerjevalnika (upstream).
        self.naprej = naprej
        #: Ime streznika DoH naprej (npr. dns.quad9.net): knjiznica TLS ga razresi prek sistemskega DNS, ta pa je Scit
        #: sam - ce bi ga poslali naprej prek DoH, bi se zavrtela zanka (vsako gnezdenje caka CAS_UPSTREAM in na koncu
        #: tiho preide na usmerjevalnik). Ta imena gredo zato vedno naravnost usmerjevalniku (ime streznika ni skrivnost).
        self.zagonsko = zagonsko
        self.rezerv = 0
        #: time.time() zadnje poizvedbe, ki je zaradi odpovedi DoH sla nesifrirano usmerjevalniku (0 = se nobene).
        self.nesifrirano_cas = 0.0
        self.vrata = 0
        self.blokiranih = 0
        self.poizvedb = 0
        self.zadnje: List[dict] = []
        self._udp: Optional[socket.socket] = None
        self._tcp: Optional[socket.socket] = None
        self._tece = False
        self._kljuc = threading.Lock()
        self._proste = threading.BoundedSemaphore(self.NAJVEC_HKRATI)
        self._proste_tcp = threading.BoundedSemaphore(self.NAJVEC_TCP)
        self.zavrzenih = 0

    #: Najvec hkrati obdelanih poizvedb UDP. Prej je vsak paket dobil svojo nit brez meje: nevihta poizvedb (ali
    #: zataknjen DoH) je lahko ustvarila tisoce niti in podrla proces z vmesnikom vred. Cez mejo paket zavrzemo -
    #: systemd-resolved ga ponovi (20. 10. 2026, odpornost 1.0.129).
    NAJVEC_HKRATI = 256
    #: TCP ima svojo, manjso mejo in kratek rok za glavo: povezava, ki ne poslje nicesar, bi sicer mesto drzala 10 s -
    #: vsak lokalni program bi s 300 odprtimi povezavami zasedel vsa mesta in utisal Scit za ves racunalnik
    #: (neodvisni pregled 1.0.129: oglasi mimo, kanarcek brez odgovora, varuh bi Scit zamenjeval do obupa).
    NAJVEC_TCP = 32
    ROK_GLAVE_TCP_S = 2.0

    def _zacni(self, u: socket.socket, t: socket.socket, vrata: int) -> int:
        self._udp, self._tcp, self.vrata, self._tece = u, t, vrata, True
        _AKTIVNA_VRATA.add(vrata)
        _AKTIVNI.add(self)
        threading.Thread(target=self._zanka_udp, name="safeer-scit-udp", daemon=True).start()
        threading.Thread(target=self._zanka_tcp, name="safeer-scit-tcp", daemon=True).start()
        return vrata

    def zazeni_z_vticnicama(self, u: socket.socket, t: socket.socket) -> int:
        """Zazene na vticnicah, ki jih je odprl in podedoval varuh (core/scit_proces): med ponovnim zagonom procesa
        Scit vrata ostanejo odprta in poizvedbe cakajo v cakalni vrsti jedra, namesto da bi resolved presel na
        usmerjevalnik mimo Scita."""
        if self._tece:
            return self.vrata
        naslov, vrata = u.getsockname()[:2]
        if naslov != NASLOV or vrata not in VRATA or t.getsockname()[:2] != (naslov, vrata):
            raise ValueError("podedovani vticnici nista na %s:%s" % (NASLOV, "/".join(map(str, VRATA))))
        return self._zacni(u, t, vrata)

    def zazeni(self) -> int:
        if self._tece:
            return self.vrata
        if _PODEDOVANE is not None:
            # Proces Scit pod varuhom: vrata drzi varuh. Kopiji (dup) - ob izklopu zapremo svojo, varuhova ostane.
            u, t = _PODEDOVANE
            return self.zazeni_z_vticnicama(u.dup(), t.dup())
        for vrata in VRATA:
            u = t = None
            try:
                u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                u.bind((NASLOV, vrata))
                t = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                t.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                t.bind((NASLOV, vrata))
                t.listen(16)
            except OSError:
                # Zasedena vrata: ze odprte vticnice zapremo, preden poskusimo naslednja.
                for s in (u, t):
                    if s is not None:
                        s.close()
                continue
            return self._zacni(u, t, vrata)
        return 0

    def _zasedi(self, semafor: Optional[threading.BoundedSemaphore] = None) -> bool:
        """Prosto mesto za novo poizvedbo (brez cakanja); False = meja dosezena, poizvedbo zavrzi."""
        if (semafor or self._proste).acquire(blocking=False):
            return True
        with self._kljuc:
            self.zavrzenih += 1
        return False

    def ustavi(self) -> None:
        self._tece = False
        _AKTIVNA_VRATA.discard(self.vrata)
        for s in (self._udp, self._tcp):
            try:
                if s is not None:
                    s.close()
            except OSError:
                pass
        self._udp = self._tcp = None
        self.vrata = 0

    def _odgovori(self, paket: bytes, tcp: bool) -> Optional[bytes]:
        ime = ime_poizvedbe(paket)
        if ime and ime.lower().rstrip(".") == KANAREK_DOH:
            # Firefox vprasa to ime, preden sam vklopi DNS prek HTTPS. Ce ga ni, ostane pri sistemskem DNS - pri
            # Scitu. Sicer bi oglase in nevarne strani razresil mimo nas (support.mozilla.org: canary domain).
            # Ne steje kot blokirano: ni oglas. Tudi ne kot poizvedba: utrip procesa Scit ga vprasa vsako sekundo.
            return odgovor_zavrnjeno(paket)
        with self._kljuc:
            self.poizvedb += 1
        if ime:
            kategorija = self.blokiraj(ime)
            if kategorija:
                with self._kljuc:
                    self.blokiranih += 1
                    if not self.zadnje or self.zadnje[0]["ime"] != ime:
                        self.zadnje = ([{"ime": ime, "kategorija": kategorija, "cas": time.time()}] + self.zadnje)[:20]
                return odgovor_zavrnjeno(paket)
            if self.naprej is not None and self.zagonsko is not None and self.zagonsko(ime):
                return self._vprasaj_usmerjevalnik(paket, tcp)
        return self._posreduj(paket, tcp)

    #: Koliko casa po zadnji nesifrirani poizvedbi stanje kaze, da DNS ni sifriran (straza in strani osvezujejo na
    #: nekaj sekund; ko DoH spet odgovarja, oznaka izgine sama).
    NESIFRIRANO_S = 120.0

    def nesifrirano(self) -> bool:
        """Ali je Scit nazadnje (v NESIFRIRANO_S) moral imena poslati nesifrirano, ker DoH ni odgovoril."""
        return bool(self.nesifrirano_cas) and time.time() - self.nesifrirano_cas < self.NESIFRIRANO_S

    #: Ko sifriran streznik naprej ne odgovori, gredo poizvedbe toliko sekund naravnost na usmerjevalnik (nato spet
    #: poskusimo naprej). Brez tega je vsako ime cakalo rok DoH - v omrezju, ki 1.1.1.1 ne spusti, vec sekund na ime
    #: (CI, Flatpak, 17. 10. 2026: imena se v 12 s niso razresila).
    PREMOR_NAPREJ_S = 30.0

    def _vprasaj_naprej(self, paket: bytes, rok: Optional[float] = None) -> Optional[bytes]:
        """Odgovor sifriranega streznika naprej, ce pride v `rok` (privzeto ROK_NAPREJ), sicer None - klicatelj takrat
        vprasa usmerjevalnik. Poizvedba tece naprej v ozadju: ce DoH ne odgovori niti v polnem roku (CAS_UPSTREAM znotraj
        self.naprej) ali visi, gremo PREMOR_NAPREJ_S naravnost na usmerjevalnik (kot prej)."""
        izid: list = []

        def delo() -> None:
            try:
                odgovor = self.naprej(paket)
            except Exception:  # noqa: BLE001
                odgovor = None
            with self._kljuc:
                self._naprej_zacetki.pop(st, None)
                if not odgovor:
                    self._brez_naprej_do = time.monotonic() + self.PREMOR_NAPREJ_S
                    self.nesifrirano_cas = time.time()
            izid.append(odgovor)

        with self._kljuc:
            # Zacetek vsake cakajoce poizvedbe posebej: prej je cas cakanja tekel od prve poizvedbe, dokler niso vse
            # koncale - pri neprekinjenem prekrivanju (brskanje) je po 2,5 s sprozil premor, ceprav je DoH delal.
            if not hasattr(self, "_naprej_zacetki"):
                self._naprej_zacetki = {}
            self._st_naprej = getattr(self, "_st_naprej", 0) + 1
            st = self._st_naprej
            self._naprej_zacetki[st] = time.monotonic()
            if len(self._naprej_zacetki) > NAJVEC_CAKAJOCIH_NAPREJ:
                self._brez_naprej_do = time.monotonic() + self.PREMOR_NAPREJ_S
        nit = threading.Thread(target=delo, name="safeer-scit-naprej", daemon=True)
        nit.start()
        nit.join(min(ROK_NAPREJ, CAS_UPSTREAM) if rok is None else rok)
        return izid[0] if izid else None

    def _naprej_visi(self) -> bool:
        """DoH ima poizvedbo, ki caka dlje od CAS_UPSTREAM (knjiznica TLS roka ni spostovala): kot odpoved."""
        with self._kljuc:
            zacetki = getattr(self, "_naprej_zacetki", None)
            najstarejsa = min(zacetki.values()) if zacetki else None
        return najstarejsa is not None and time.monotonic() - najstarejsa >= CAS_UPSTREAM

    #: Ali je streznik naprej sifriran (False: uporabnik je izbral »DNS usmerjevalnika« - takrat nesifrirana pot ni
    #: odpoved in je ne stejemo ne kazemo kot izgubo sifriranja).
    sifrirano_naprej: Callable[[], bool] = staticmethod(lambda: True)

    def _posreduj(self, paket: bytes, tcp: bool) -> Optional[bytes]:
        if self.naprej is not None and not self.sifrirano_naprej():
            return self._vprasaj_usmerjevalnik(paket, tcp)
        if self.naprej is not None and self._naprej_visi():
            with self._kljuc:
                self._brez_naprej_do = max(getattr(self, "_brez_naprej_do", 0.0), time.monotonic() + self.PREMOR_NAPREJ_S)
                # Premor je zacet; po njem DoH poskusimo znova (visece poizvedbe ne stejejo vec).
                getattr(self, "_naprej_zacetki", {}).clear()
        if self.naprej is not None and time.monotonic() >= getattr(self, "_brez_naprej_do", 0.0):
            odgovor = self._vprasaj_naprej(paket)
            if odgovor:
                return odgovor if tcp or len(odgovor) <= NAJVEC_UDP else prirezan(paket)
            with self._kljuc:
                self.rezerv += 1          # samo stetje, brez imen
                self.nesifrirano_cas = time.time()
            # Premor mimo DoH (PREMOR_NAPREJ_S) doloci poizvedba v ozadju, ko res ne odgovori (_vprasaj_naprej).
        elif self.naprej is not None:
            with self._kljuc:
                self.rezerv += 1
                self.nesifrirano_cas = time.time()
        return self._vprasaj_usmerjevalnik(paket, tcp)

    def _vprasaj_usmerjevalnik(self, paket: bytes, tcp: bool) -> Optional[bytes]:
        """Strezniki DNS usmerjevalnika (NetworkManager) - nesifrirano, kot brez Scita. Brez njih SERVFAIL takoj
        (4. 11. 2026, kot Android): prej molk - odjemalec je cakal svoj rok, tujega razresevalnika ne izberemo."""
        strezniki = list(self.upstream() or [])
        if not strezniki:
            return odgovor_napaka(paket)
        for streznik in strezniki:
            try:
                if tcp:
                    with socket.create_connection((streznik, 53), timeout=CAS_UPSTREAM) as s:
                        s.sendall(struct.pack("!H", len(paket)) + paket)
                        glava = self._preberi(s, 2)
                        return self._preberi(s, struct.unpack("!H", glava)[0])
                druzina = socket.AF_INET6 if ":" in streznik else socket.AF_INET
                cilj = socket.getaddrinfo(streznik, 53, druzina, socket.SOCK_DGRAM, 0, socket.AI_NUMERICHOST)[0][4]
                s = socket.socket(druzina, socket.SOCK_DGRAM)
                s.settimeout(CAS_UPSTREAM)
                try:
                    s.sendto(paket, cilj)
                    odgovor, _ = s.recvfrom(4096)
                finally:
                    s.close()
                if odgovor[:2] == paket[:2]:
                    return odgovor
            except (OSError, struct.error):
                continue
        return None

    @staticmethod
    def _preberi(s: socket.socket, n: int) -> bytes:
        b = b""
        while len(b) < n:
            d = s.recv(n - len(b))
            if not d:
                raise OSError("prekinjeno")
            b += d
        return b

    #: Zanki branja preverita vsakih toliko sekund, ali razresevalnik se tece (ustavi() ju konca brez shutdown -
    #: podedovane vticnice si deli z varuhom, shutdown bi ustavil tudi njegovo kopijo).
    ZANKA_S = 1.0

    def _zanka_udp(self) -> None:
        u = self._udp
        if u is not None:
            u.settimeout(self.ZANKA_S)
        while self._tece and u is not None and self._udp is u:
            try:
                paket, od = u.recvfrom(4096)
            except TimeoutError:
                continue
            except ConnectionResetError:
                # Windows: ce odjemalec odide, preden dobi odgovor, sistem ob naslednjem branju javi napako 10054
                # (ICMP »vrata zaprta«). To ni konec razresevalnika - prej se je zanka tu koncala in Scit je utihnil:
                # Windows je nato vsako ime cakal ~1 s in ga razresil mimo filtra (izmerjeno 9. 10. 2026).
                continue
            except OSError:
                break

            if ime_poizvedbe(paket).lower().rstrip(".") == KANAREK_DOH:
                # Kanarcek (utrip procesa Scit, Firefox) odgovorimo takoj, brez niti in mimo meje: polna vrsta ne
                # sme utisati preverbe, ali Scit zivi.
                try:
                    u.sendto(odgovor_zavrnjeno(paket), od)
                except OSError:
                    pass
                continue
            if not self._zasedi():
                continue

            def delo(p=paket, o=od):
                try:
                    odgovor = self._odgovori(p, False)
                    if odgovor and self._udp is not None:
                        try:
                            self._udp.sendto(odgovor, o)
                        except OSError:
                            pass
                finally:
                    self._proste.release()
            self._zazeni_delo(delo)

    def _zanka_tcp(self) -> None:
        t = self._tcp
        if t is not None:
            t.settimeout(self.ZANKA_S)
        while self._tece and t is not None and self._tcp is t:
            try:
                s, _ = t.accept()
            except TimeoutError:
                continue
            except OSError:
                break

            if not self._zasedi(self._proste_tcp):
                try:
                    s.close()
                except OSError:
                    pass
                continue

            def delo(s=s):
                try:
                    s.settimeout(self.ROK_GLAVE_TCP_S)
                    n = struct.unpack("!H", self._preberi(s, 2))[0]
                    s.settimeout(10)
                    odgovor = self._odgovori(self._preberi(s, n), True)
                    if odgovor:
                        s.sendall(struct.pack("!H", len(odgovor)) + odgovor)
                except (OSError, struct.error):
                    pass
                finally:
                    try:
                        s.close()
                    except OSError:
                        pass
                    self._proste_tcp.release()
            self._zazeni_delo(delo, self._proste_tcp)

    def _zazeni_delo(self, delo: Callable[[], None], semafor: Optional[threading.BoundedSemaphore] = None) -> None:
        try:
            threading.Thread(target=delo, name="safeer-scit-poizvedba", daemon=True).start()
        except RuntimeError:
            # Sistem ne da nove niti (meja procesa): poizvedbo zavrzemo, mesto sprostimo - zanka tece naprej.
            (semafor or self._proste).release()
            with self._kljuc:
                self.zavrzenih += 1
# <<< SKUPNO Z LINUXOM (razresevalnik)
# >>> SKUPNO Z LINUXOM (Safeer-linux 746f975 core/os_scit.py: aktivni) - ne spreminjaj samo tu
_AKTIVNA_VRATA: set = set()
_AKTIVNI = weakref.WeakSet()
#: (UDP, TCP) vticnici, ki ju je odprl varuh (core/scit_proces.py) - Razresevalnik.zazeni ju uporabi namesto svojih.
_PODEDOVANE: Optional[Tuple[socket.socket, socket.socket]] = None
#: Scit v svojem procesu (core/scit_odjemalec.py): ali je nazadnje posiljal nesifrirano - zadnje znano stanje.
zunanje_nesifrirano: Optional[Callable[[], bool]] = None


def uporabi_podedovane(u: socket.socket, t: socket.socket) -> None:
    """Razresevalniki tega procesa naj poslusajo na vticnicah varuha (ostanejo odprte med ponovnimi zagoni)."""
    global _PODEDOVANE
    _PODEDOVANE = (u, t)


def nesifrirano_v_procesu() -> bool:
    """Ali je Scit (v tem procesu ali v svojem, ki ga ta proces vprasa) nazadnje moral imena poslati nesifrirano
    (Splet to pokaze ob svojem scitu)."""
    if any(r.vrata and r.naprej is not None and r.sifrirano_naprej() and r.nesifrirano() for r in list(_AKTIVNI)):
        return True
    zunanje = zunanje_nesifrirano
    try:
        return bool(zunanje is not None and zunanje())
    except Exception:  # noqa: BLE001
        return False


def _odgovori_kanarcku(vrata: int, cas: float) -> bool:
    """Na vratih je res Scit: ime, ki ga Scit vedno zavrne sam (KANAREK_DOH, brez poizvedbe naprej), dobi NXDOMAIN z
    istim ID."""
    ident = os.urandom(2)
    vprasanje = ident + b"\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00" + b"".join(
        bytes([len(d)]) + d.encode() for d in KANAREK_DOH.split(".")) + b"\x00\x00\x01\x00\x01"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as u:
            u.settimeout(cas)
            u.connect((NASLOV, vrata))
            u.send(vprasanje)
            odgovor = u.recv(512)
    except OSError:
        return False
    return odgovor[:2] == ident and len(odgovor) >= 12 and odgovor[3] & 0x0F == 3
# <<< SKUPNO Z LINUXOM (aktivni)


class RazresevalnikWin(Razresevalnik):
    """Isti razresevalnik kot na Linuxu (odlocanje, posredovanje naprej, roki); drugacno je samo poslusanje:
    127.0.0.1:53 in [::1]:53, vrata samo zase (SO_EXCLUSIVEADDRUSE). Na Windows SO_REUSEADDR dovoli DRUGEMU programu,
    da se veze na ista vrata in prestreza poizvedbe (Microsoft: »socket hijacking«) - prej ga je Scit nastavil sam."""

    def __init__(self, *argumenti, **kljucni) -> None:
        super().__init__(*argumenti, **kljucni)
        self._udp6: Optional[socket.socket] = None
        self._tcp6: Optional[socket.socket] = None

    def ima_ipv6(self) -> bool:
        return self._udp6 is not None

    @staticmethod
    def vezi(druzina: int, naslov: str, vrata: int) -> Optional[Tuple[socket.socket, socket.socket]]:
        u = t = None
        try:
            u = socket.socket(druzina, socket.SOCK_DGRAM)
            t = socket.socket(druzina, socket.SOCK_STREAM)
            izkljucno = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
            if izkljucno is not None:
                for s in (u, t):
                    s.setsockopt(socket.SOL_SOCKET, izkljucno, 1)
            u.bind((naslov, vrata))
            t.bind((naslov, vrata))
            t.listen(16)
            brez_10054 = getattr(socket, "SIO_UDP_CONNRESET", None)
            if brez_10054 is not None:
                try:
                    u.ioctl(brez_10054, False)      # odjemalec, ki odide pred odgovorom, ne pokvari branja
                except (OSError, ValueError):
                    pass
            return u, t
        except OSError:
            for s in (u, t):
                if s is not None:
                    s.close()
            return None

    def zazeni(self) -> int:
        if self._tece:
            return self.vrata
        for vrata in VRATA:
            par = self.vezi(socket.AF_INET, NASLOV, vrata)
            if par is None:
                continue
            # IPv6 ni nujen: brez njega vmesnik dobi samo 127.0.0.1, IPv6 strezniki omrezja pa se pokazejo kot »mimo«.
            par6 = self.vezi(socket.AF_INET6, NASLOV6, vrata) if socket.has_ipv6 else None
            self._udp, self._tcp = par
            self._udp6, self._tcp6 = par6 if par6 else (None, None)
            self.vrata, self._tece = vrata, True
            _AKTIVNA_VRATA.add(vrata)
            _AKTIVNI.add(self)
            for u, t in ((self._udp, self._tcp), (self._udp6, self._tcp6)):
                if u is not None:
                    threading.Thread(target=self._zanka_udp_win, args=(u,), name="safeer-scit-udp", daemon=True).start()
                    threading.Thread(target=self._zanka_tcp_win, args=(t,), name="safeer-scit-tcp", daemon=True).start()
            return vrata
        return 0

    def ustavi(self) -> None:
        for s in (self._udp6, self._tcp6):
            try:
                if s is not None:
                    s.close()
            except OSError:
                pass
        self._udp6 = self._tcp6 = None
        super().ustavi()

    def _odprta(self, s: socket.socket) -> bool:
        return self._tece and s is not None and any(s is x for x in (self._udp, self._tcp, self._udp6, self._tcp6))

    def _zanka_udp_win(self, u: socket.socket) -> None:
        """Kot Razresevalnik._zanka_udp, za eno od vticnic (127.0.0.1 ali ::1)."""
        u.settimeout(self.ZANKA_S)
        while self._odprta(u):
            try:
                paket, od = u.recvfrom(4096)
            except TimeoutError:
                continue
            except ConnectionResetError:
                # Napaka 10054 (ICMP »vrata zaprta«) ni konec razresevalnika (izmerjeno 9. 10. 2026: zanka se je
                # koncala, Scit je utihnil).
                continue
            except OSError:
                break
            if ime_poizvedbe(paket).lower().rstrip(".") == KANAREK_DOH:
                try:
                    u.sendto(odgovor_zavrnjeno(paket), od)
                except OSError:
                    pass
                continue
            if not self._zasedi():
                continue

            def delo(p=paket, o=od):
                try:
                    odgovor = self._odgovori(p, False)
                    if odgovor and self._odprta(u):
                        try:
                            u.sendto(odgovor, o)
                        except OSError:
                            pass
                finally:
                    self._proste.release()
            self._zazeni_delo(delo)

    def _zanka_tcp_win(self, t: socket.socket) -> None:
        """Kot Razresevalnik._zanka_tcp, za eno od vticnic (127.0.0.1 ali ::1)."""
        t.settimeout(self.ZANKA_S)
        while self._odprta(t):
            try:
                s, _ = t.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            if not self._zasedi(self._proste_tcp):
                try:
                    s.close()
                except OSError:
                    pass
                continue

            def delo(s=s):
                try:
                    s.settimeout(self.ROK_GLAVE_TCP_S)
                    n = struct.unpack("!H", self._preberi(s, 2))[0]
                    s.settimeout(10)
                    odgovor = self._odgovori(self._preberi(s, n), True)
                    if odgovor:
                        s.sendall(struct.pack("!H", len(odgovor)) + odgovor)
                except (OSError, struct.error):
                    pass
                finally:
                    try:
                        s.close()
                    except OSError:
                        pass
                    self._proste_tcp.release()
            self._zazeni_delo(delo, self._proste_tcp)


# >>> SKUPNO Z LINUXOM (Safeer-linux 746f975 core/os_scit.py: nabor) - ne spreminjaj samo tu
# ---------------------------------------------------------------------- nabor domen
def _zgoscenka(ime: str) -> int:
    return int.from_bytes(hashlib.blake2b(ime.encode("utf-8", "replace"), digest_size=8).digest(), "big")


def razcleni_seznam(besedilo: str) -> Iterable[str]:
    """Domene iz seznama v obliki hosts (0.0.0.0 ime), RPZ (ime CNAME .) ali golih domen; komentarji stran."""
    for v in besedilo.splitlines():
        v = v.strip()
        if not v or v[0] in "#!;$@[":
            continue
        deli = v.split()
        ime = deli[0]
        if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}|::1?|0\.0\.0\.0", ime):
            if len(deli) < 2:
                continue
            ime = deli[1]
        ime = ime.lower().rstrip(".").lstrip("*.")
        if "." not in ime or not re.fullmatch(r"[a-z0-9._-]{3,253}", ime):
            continue
        if ime in ("localhost", "localhost.localdomain", "broadcasthost"):
            continue
        yield ime


class Nabor:
    """Urejeno polje zgoscenk blokiranih domen s kategorijo; poddomene blokirane domene so tudi blokirane."""

    GLAVA = b"SAFEER-SCIT-NABOR-1\n"

    def __init__(self) -> None:
        self.zgoscenke = array("Q")
        self.kategorije = array("B")

    def __len__(self) -> int:
        return len(self.zgoscenke)

    @classmethod
    def iz_domen(cls, domene: Iterable[Tuple[str, str]]) -> "Nabor":
        pari: Dict[int, int] = {}
        for ime, kategorija in domene:
            k = KATEGORIJE.index(kategorija) if kategorija in KATEGORIJE else 0
            z = _zgoscenka(ime)
            # Nevarnejsa kategorija (visji indeks) prevlada, ce je domena na vec seznamih.
            if k >= pari.get(z, -1):
                pari[z] = k
        n = cls()
        for z in sorted(pari):
            n.zgoscenke.append(z)
            n.kategorije.append(pari[z])
        return n

    def kategorija(self, ime: str) -> Optional[str]:
        deli = ime.split(".")
        for i in range(len(deli) - 1):
            z = _zgoscenka(".".join(deli[i:]))
            j = bisect.bisect_left(self.zgoscenke, z)
            if j < len(self.zgoscenke) and self.zgoscenke[j] == z:
                return KATEGORIJE[self.kategorije[j]]
        return None

    def vse_kategorije(self, ime: str) -> List[str]:
        """Kategorije imena in vseh nadrejenih domen (kategorija() vrne samo najbolj natancno ujemanje)."""
        izid = []
        deli = ime.split(".")
        for i in range(len(deli) - 1):
            z = _zgoscenka(".".join(deli[i:]))
            j = bisect.bisect_left(self.zgoscenke, z)
            if j < len(self.zgoscenke) and self.zgoscenke[j] == z:
                izid.append(KATEGORIJE[self.kategorije[j]])
        return izid

    def shrani(self, pot: str) -> None:
        """Atomsko, z edinstveno zacasno datoteko: sezname osvezujeta lahko dva procesa (Scit in Splet ali Safeer
        Browser) hkrati - prej sta pisala v isti domene.bin.tmp."""
        import tempfile
        mapa = os.path.dirname(pot)
        os.makedirs(mapa, exist_ok=True)
        fd, zacasna = tempfile.mkstemp(prefix="." + os.path.basename(pot) + ".", dir=mapa)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(self.GLAVA + struct.pack("<Q", len(self.zgoscenke)))
                self.zgoscenke.tofile(f)
                self.kategorije.tofile(f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(zacasna, pot)
        except BaseException:
            try:
                os.unlink(zacasna)
            except OSError:
                pass
            raise

    @classmethod
    def nalozi(cls, pot: str) -> Optional["Nabor"]:
        try:
            with open(pot, "rb") as f:
                if f.read(len(cls.GLAVA)) != cls.GLAVA:
                    return None
                n = struct.unpack("<Q", f.read(8))[0]
                nabor = cls()
                nabor.zgoscenke.fromfile(f, n)
                nabor.kategorije.fromfile(f, n)
                return nabor
        except (OSError, EOFError, struct.error):
            return None


def prenesi(url: str, etag: str, cas: float = 60.0) -> Tuple[int, bytes, str]:
    """Pogojni GET; (304, b'', etag) kadar je seznam nespremenjen."""
    z = urllib.request.Request(url, headers={"User-Agent": "Safeer", "Accept": "text/plain"})
    if etag:
        z.add_header("If-None-Match", etag)
    try:
        with urllib.request.urlopen(z, timeout=cas) as o:  # noqa: S310 - fiksni naslovi https
            if not o.geturl().lower().startswith("https://") or not isti_gostitelj(url, o.geturl()):
                return 0, b"", etag  # preusmeritev drugam: seznama ne vzamemo, ostane prejsnji
            return o.status, o.read(NAJVEC_BAJTOV + 1), o.headers.get("ETag", "") or ""
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return 304, b"", etag
        raise


class Seznami:
    """Seznami domen na disku (kot ThreatFeedsUpdater na televizorju) + Safeerjev podpisani seznam groznj."""

    def __init__(self, mapa: str, prenesi_fn=prenesi) -> None:
        self.mapa = mapa
        self.prenesi = prenesi_fn
        self.nabor: Nabor = Nabor.nalozi(os.path.join(mapa, "domene.bin")) or Nabor()
        self.meta: dict = self._preberi_meta()
        self.napaka = ""
        self.storitev = None
        self._nit: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._kljuc = threading.Lock()
        #: Kdo potrebuje osvezevanje (Scit, brskalnik): skupni seznami se ustavijo sele, ko ga ne potrebuje nihce.
        self._lastniki: set = set()

    # -- datoteke
    def _meta_pot(self) -> str:
        return os.path.join(self.mapa, "seznami.json")

    def _preberi_meta(self) -> dict:
        try:
            with open(self._meta_pot(), encoding="utf-8") as f:
                m = json.load(f)
            return m if isinstance(m, dict) else {}
        except (OSError, ValueError):
            return {}

    def _zapisi_meta(self) -> None:
        from core import shramba_json
        shramba_json.zapisi_atomsko(self._meta_pot(), self.meta, indent=None, nacin=0o644)

    # -- zivljenje
    def na_voljo(self) -> bool:
        """Ali je nabor ze tu (z diska ali prenesen) - sicer Scit se ne more presoditi."""
        s = self.storitev
        return bool(len(self.nabor)) or bool(s is not None and s.loaded.is_set())

    def zazeni(self, lastnik: str = "scit") -> None:
        self._lastniki.add(lastnik)
        if self.storitev is None:
            try:
                from core.threat_intel import default_data_dir, skupna
                self.storitev = skupna(default_data_dir("safeer-mint"))   # ista kot v Spletu (en proces, ena kopija)
            except Exception as e:  # noqa: BLE001
                print("[SafeerOS] scit: seznam groznj:", e)
        if self._nit is None:
            self._stop.clear()
            self._nit = threading.Thread(target=self._tek, name="safeer-scit-seznami", daemon=True)
            self._nit.start()

    def ustavi(self, lastnik: str = "scit") -> None:
        self._lastniki.discard(lastnik)
        if self._lastniki:
            return
        self._stop.set()
        self._nit = None

    def _tek(self) -> None:
        jaz = threading.current_thread()
        if self._stop.wait(PRVA_OSVEZITEV if not len(self.nabor) else min(OSVEZITEV, self._do_naslednje())):
            return
        while not self._stop.is_set() and self._nit is jaz:
            try:
                ok = self.osvezi()
            except Exception as e:  # noqa: BLE001 - nit se ne sme koncati (_nit ostane nastavljen, zazeni je ne obnovi)
                print("[SafeerOS] scit: osvezitev seznamov:", type(e).__name__, e)
                ok = False
            if self._stop.wait(OSVEZITEV if ok else PONOVNI_POSKUS):
                return

    def _do_naslednje(self) -> float:
        return max(PRVA_OSVEZITEV, OSVEZITEV - (time.time() - float(self.meta.get("cas", 0) or 0)))

    def osvezi(self) -> bool:
        """Prenese spremenjene sezname in na novo zgradi nabor; ob napaki ostane prejsnji."""
        os.makedirs(self.mapa, exist_ok=True)
        spremenjeno, napake = False, []
        for oznaka, url, _kat in VIRI:
            m = self.meta.get(oznaka, {})
            try:
                koda, telo, etag = self.prenesi(url, m.get("etag", ""))
            except Exception as e:  # noqa: BLE001
                napake.append("%s: %s" % (oznaka, e.__class__.__name__))
                continue
            if koda == 304 and os.path.exists(os.path.join(self.mapa, oznaka + ".txt")):
                continue
            if koda != 200 or len(telo) > NAJVEC_BAJTOV:
                napake.append("%s: %s" % (oznaka, koda))
                continue
            glava = telo[:2048].decode("utf-8", "replace").lower()
            if "<html" in glava or "<!doctype" in glava:
                napake.append("%s: html" % oznaka)
                continue
            domen = sum(1 for _ in razcleni_seznam(telo.decode("utf-8", "replace")))
            if domen < (NAJMANJ_DOMEN if oznaka.startswith("hagezi") else 1):
                napake.append("%s: %d domen" % (oznaka, domen))
                continue
            _atomic_write(Path(self.mapa, oznaka + ".txt"), telo)
            self.meta[oznaka] = {"etag": etag, "cas": time.time(), "domen": domen}
            spremenjeno = True
        if spremenjeno or not len(self.nabor):
            self._zgradi()
        self.meta["cas"] = time.time()
        self.napaka = "; ".join(napake)
        self.meta["napaka"] = self.napaka
        try:
            self._zapisi_meta()
        except OSError:
            pass
        return not napake

    def _zgradi(self) -> None:
        def domene():
            for oznaka, _url, kat in VIRI:
                try:
                    with open(os.path.join(self.mapa, oznaka + ".txt"), encoding="utf-8", errors="replace") as f:
                        besedilo = f.read()
                except OSError:
                    continue
                for ime in razcleni_seznam(besedilo):
                    yield ime, kat
        nabor = Nabor.iz_domen(domene())
        if len(nabor):
            with self._kljuc:
                self.nabor = nabor
            try:
                nabor.shrani(os.path.join(self.mapa, "domene.bin"))
            except OSError:
                pass

    # -- preverjanje
    def kategorija(self, ime: str) -> Optional[str]:
        if not ime or "." not in ime or je_krajevno(ime):
            return None
        if je_zasciten(ime):
            return self.kategorija_groznje(ime)     # oglasi ne, groznja vedno (4. 11. 2026)
        with self._kljuc:
            k = self.nabor.kategorija(ime)
        if k:
            return k
        if _je_telemetrija(ime):
            return KATEGORIJA_PREMORA       # telemetrija storitev s podpisanega seznama Scita (premor jo spusti)
        s = self.storitev
        if s is not None and s.loaded.is_set():
            try:
                k = s.store.match_host(ime)
            except Exception:
                k = None
            if k in KATEGORIJA_SEZNAMA_GROZNJ:
                return KATEGORIJA_SEZNAMA_GROZNJ[k]
        return None

    def kategorija_groznje(self, ime: str) -> Optional[str]:
        """Kategorija GROZNJE (ne oglasov) imena ali katere nadrejene domene - v naboru ali v podpisanem seznamu
        grozenj; None, ce ni groznja."""
        with self._kljuc:
            for k in self.nabor.vse_kategorije(ime):
                if k != KATEGORIJA_PREMORA:
                    return k
        s = self.storitev
        if s is not None and s.loaded.is_set():
            try:
                k = s.store.match_host(ime)
            except Exception:  # noqa: BLE001 - seznam groženj ni berljiv: raje blokirano (fail-closed)
                return "groznje"
            if k in KATEGORIJA_SEZNAMA_GROZNJ:
                return KATEGORIJA_SEZNAMA_GROZNJ[k]
        return None

    def groznja(self, ime: str) -> bool:
        """Ime ali nadrejena domena je na seznamu GROZENJ. Izjema (Webtor, uporabnik) nikoli ne umakne groznje
        (pregled Grok N15; uporabnik 4. 11. 2026)."""
        return self.kategorija_groznje(ime) is not None

    def stanje(self) -> dict:
        st = {"domen": len(self.nabor), "posodobljeno": float(self.meta.get("cas", 0) or 0), "napakaSeznamov": self.napaka,
              "seznami": {o: int(self.meta.get(o, {}).get("domen", 0) or 0) for o, _u, _k in VIRI}}
        if self.storitev is not None:
            try:
                st["pravil"] = int(self.storitev.status().get("rules") or 0)
            except Exception:
                st["pravil"] = 0
        return st
# <<< SKUPNO Z LINUXOM (nabor)


# ---------------------------------------------------------------------- Windows: DNS vmesnikov (PowerShell DnsClient)
#: PowerShell za narekovaj steje tudi tipografske (U+2018-U+201B): v nizu jih podvojimo vse.
_NAREKOVAJI = ("'", "\u2018", "\u2019", "\u201a", "\u201b")


def ps_niz(besedilo) -> str:
    """Besedilo kot niz PowerShell v enojnih narekovajih. Prej je bilo ime vmesnika v ukaz vstavljeno brez ubeznice:
    ime z narekovajem je niz koncalo, ostanek imena se je izvedel kot ukaz (s pravicami Safeer OS)."""
    s = str(besedilo)
    for z in _NAREKOVAJI:
        s = s.replace(z, z + z)
    return "'" + s + "'"


def veljavno_ime_vmesnika(ime) -> bool:
    v = str(ime or "")
    return 0 < len(v) <= 256 and not any(ord(c) < 32 or ord(c) == 127 for c in v)


def _powershell(skripta: str, cas: float = 8.0) -> Tuple[int, str]:
    """Skripta kot -EncodedCommand (UTF-16LE, base64): brez se ene plasti narekovajev ukazne vrstice. Izpis UTF-8."""
    if sys.platform != "win32":
        return 127, ""
    uvod = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n$ProgressPreference = 'SilentlyContinue'\n"
    kodirano = base64.b64encode((uvod + skripta).encode("utf-16-le")).decode("ascii")
    try:
        r = subprocess.run([_sistemski(*POWERSHELL), "-NoProfile", "-NonInteractive", "-EncodedCommand", kodirano],
                           capture_output=True, timeout=cas, creationflags=_BREZ_OKNA)
        return r.returncode, (r.stdout or b"").decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - brez PowerShella: kot napaka
        return 1, ""


#: Povezani vmesniki z vsem, kar Scit potrebuje, v enem klicu (prej trije do pet klicev PowerShell na pregled):
#: trenutni strezniki IPv4 in IPv6, DNS iz DHCP (register; ostane, tudi ko je na vmesniku Scit) in rocni strezniki.
BERI_VMESNIKE = r"""
$ErrorActionPreference = 'SilentlyContinue'
$izid = @()
foreach ($a in @(Get-NetAdapter | Where-Object { $_.Status -eq 'Up' })) {
  $g = [string]$a.InterfaceGuid
  $p4 = Get-ItemProperty -LiteralPath ('HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\' + $g)
  $p6 = Get-ItemProperty -LiteralPath ('HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip6\Parameters\Interfaces\' + $g)
  $d6 = ''
  if ($p6 -and $p6.Dhcpv6DNSServers) { $d6 = (($p6.Dhcpv6DNSServers | ForEach-Object { $_.ToString('x2') }) -join '') }
  $izid += [pscustomobject]@{
    ime = [string]$a.Name; indeks = [int]$a.ifIndex
    v4 = @((Get-DnsClientServerAddress -InterfaceIndex $a.ifIndex -AddressFamily IPv4).ServerAddresses)
    v6 = @((Get-DnsClientServerAddress -InterfaceIndex $a.ifIndex -AddressFamily IPv6).ServerAddresses)
    dhcp4 = [string]$p4.DhcpNameServer; staticni4 = [string]$p4.NameServer
    dhcp6 = $d6; staticni6 = [string]$p6.NameServer
  }
}
'SAFEER-VMESNIKI ' + (ConvertTo-Json -InputObject @($izid) -Compress -Depth 3)
"""
_OZNAKA_VMESNIKOV = "SAFEER-VMESNIKI "
#: Tuji javni razresevalniki, ki jih je starejsi Scit za Windows (do 1.0.153) sam vpisal na vmesnik za 127.0.0.1, kadar
#: ni nasel DNS usmerjevalnika. Niso krajevni DNS: ob prevzemu takega vmesnika jih ne vzamemo za streznike naprej.
STARI_TUJI = ("1.1.1.1", "9.9.9.9", "8.8.8.8")


def _surovi(vrednost) -> List[str]:
    if isinstance(vrednost, str):
        vrednost = [vrednost]
    return [str(v).strip() for v in (vrednost or []) if isinstance(v, str) and v.strip()]


def naslovi_dns(vrednosti, indeks: int = 0) -> List[str]:
    """Veljavni strezniki DNS omrezja (brez zanke, nedolocenega in vecvrocnega). Povezavno-lokalni IPv6 dobi %indeks
    vmesnika - brez njega ga vticnica ne doseze (prej je Scit IPv6 DNS omrezja izpustil)."""
    if isinstance(vrednosti, str):
        vrednosti = re.split(r"[\s,;]+", vrednosti)
    izid: List[str] = []
    for v in vrednosti or []:
        if not isinstance(v, str) or not v.strip():
            continue
        try:
            ip = ipaddress.ip_address(v.strip().split("%", 1)[0])
        except ValueError:
            continue
        if ip.is_loopback or ip.is_unspecified or ip.is_multicast:
            continue
        n = str(ip)
        if ip.version == 6 and ip.is_link_local and indeks:
            n = za_vticnico(n, str(int(indeks)))
        if n not in izid:
            izid.append(n)
    return izid


def _dhcp6(hex_niz: str) -> List[str]:
    h = re.sub(r"[^0-9a-fA-F]", "", str(hex_niz or ""))
    return [str(ipaddress.IPv6Address(bytes.fromhex(h[i:i + 32]))) for i in range(0, len(h) - len(h) % 32, 32)]


def razcleni_vmesnike(izpis: str) -> Optional[List[dict]]:
    """Izpis BERI_VMESNIKE -> [{ime, indeks, v4, v6, dhcp, staticni}]; None, ce izpisa ni mogoce prebrati."""
    for vrstica in str(izpis or "").splitlines():
        if vrstica.startswith(_OZNAKA_VMESNIKOV):
            try:
                podatki = json.loads(vrstica[len(_OZNAKA_VMESNIKOV):])
            except ValueError:
                return None
            break
    else:
        return None
    if isinstance(podatki, dict):
        podatki = [podatki]
    izid: List[dict] = []
    for p in podatki if isinstance(podatki, list) else []:
        if not isinstance(p, dict) or not veljavno_ime_vmesnika(p.get("ime")):
            continue
        try:
            indeks = max(0, int(p.get("indeks") or 0))
        except (TypeError, ValueError):
            indeks = 0
        try:
            dhcp6 = _dhcp6(p.get("dhcp6") or "")
        except ValueError:
            dhcp6 = []
        izid.append({"ime": str(p["ime"]), "indeks": indeks, "v4": _surovi(p.get("v4")), "v6": _surovi(p.get("v6")),
                     "dhcp": naslovi_dns(str(p.get("dhcp4") or ""), indeks) + naslovi_dns(dhcp6, indeks),
                     "staticni": naslovi_dns(str(p.get("staticni4") or ""), indeks)
                     + naslovi_dns(str(p.get("staticni6") or ""), indeks)})
        if len(izid) >= NAJVEC_VMESNIKOV:
            break
    return izid


def beri_vmesnike() -> Optional[List[dict]]:
    koda, izpis = _powershell(BERI_VMESNIKE, 20.0)
    return razcleni_vmesnike(izpis) if koda == 0 else None


def krajevni_dns(v: dict, spomin: Optional[dict]) -> Tuple[List[str], Optional[dict]]:
    """(strezniki naprej za vmesnik, nov zapis spomina ali None). Krajevni DNS je, kar je imel vmesnik pred Scitom:
      - na vmesniku so strezniki omrezja, ne Scit: ti; zapomnimo si jih (in ali so rocni, za povrnitev);
      - na vmesniku je Scit (tudi starejsi, z rezervo za sabo): rocni od prej (spomin), sicer DHCP iz registra (velja
        tudi po menjavi omrezja), sicer zadnji zapomnjeni. Nikoli tuj javni razresevalnik, ki ga je vpisal Scit sam."""
    indeks = int(v.get("indeks") or 0)
    nas = NASLOV in v.get("v4", [])
    tuji = naslovi_dns(list(v.get("v4", [])) + list(v.get("v6", [])), indeks)
    spomin = spomin if isinstance(spomin, dict) else {}
    if tuji and not nas:
        zapis = {"strezniki": tuji, "staticni": list(v.get("staticni") or [])}
        return tuji, (zapis if zapis != spomin else None)
    staticni = naslovi_dns(spomin.get("staticni") or [], indeks)
    if staticni:
        return staticni, None
    if v.get("dhcp"):
        return list(v["dhcp"]), None
    zapomnjeni = naslovi_dns(spomin.get("strezniki") or [], indeks)
    if zapomnjeni:
        return zapomnjeni, None
    return [s for s in tuji if s not in STARI_TUJI], None


def na_scitu(v: dict, z_ipv6: bool) -> Tuple[bool, bool]:
    """(IPv4 vmesnika je samo Scit, IPv6 vmesnika ima streznike mimo Scita)."""
    return set(v.get("v4", [])) == {NASLOV}, bool(naslovi_dns(v.get("v6", [])))


def _ukaz_usmeri(vmesnik: str, strezniki: List[str]) -> str:
    return "Set-DnsClientServerAddress -InterfaceAlias %s -ServerAddresses @(%s) -ErrorAction Stop" % (
        ps_niz(vmesnik), ", ".join(ps_niz(s) for s in strezniki))


def usmeri(vmesnik: str, z_ipv6: bool = True) -> str:
    """DNS vmesnika SAMO na Scit (127.0.0.1, z IPv6 se ::1): "ok", "brez_ipv6" (IPv6 ni slo, IPv4 je) ali "" (ni slo).
    Brez DNS usmerjevalnika za Scitom: Windows bi ga vprasal mimo Scita (prej drugi streznik, rok 2,5 s)."""
    if not veljavno_ime_vmesnika(vmesnik):
        return ""
    if z_ipv6 and _powershell(_ukaz_usmeri(vmesnik, [NASLOV, NASLOV6]))[0] == 0:
        return "ok"
    if _powershell(_ukaz_usmeri(vmesnik, [NASLOV]))[0] == 0:
        return "brez_ipv6" if z_ipv6 else "ok"
    if sys.platform == "win32" and '"' not in vmesnik:
        try:
            r = subprocess.run([_sistemski(*NETSH), "interface", "ipv4", "set", "dnsservers", "name=" + vmesnik,
                                "static", NASLOV, "primary"], capture_output=True, timeout=8, creationflags=_BREZ_OKNA)
            if r.returncode == 0:
                return "brez_ipv6" if z_ipv6 else "ok"
        except Exception:  # noqa: BLE001
            pass
    return ""


def _ukaz_povrni(vmesnik: str, staticni: Iterable[str] = ()) -> str:
    """Vmesnik spet dobi DNS sistema (DHCP); ce je imel rocne streznike, se te (samo veljavni naslovi IP)."""
    ukaz = "Set-DnsClientServerAddress -InterfaceAlias %s -ResetServerAddresses -ErrorAction Stop" % ps_niz(vmesnik)
    rocni: List[str] = []
    for s in staticni or ():
        try:
            n = str(ipaddress.ip_address(str(s).split("%", 1)[0]))
        except ValueError:
            continue
        if n not in rocni and n not in (NASLOV, NASLOV6):
            rocni.append(n)
    if rocni:
        ukaz += "; " + _ukaz_usmeri(vmesnik, rocni)
    return ukaz


def povrni(vmesnik: str, staticni: Iterable[str] = ()) -> bool:
    if not veljavno_ime_vmesnika(vmesnik):
        return False
    return _powershell(_ukaz_povrni(vmesnik, staticni))[0] == 0


def izprazni_predpomnilnik() -> None:
    """Windows razresena imena hrani; po spremembi (vklop, izjema, premor) naj vprasa znova."""
    _powershell("Clear-DnsClientCache", 10.0)


def skripta_straze_padca(pid: int, vmesniki: Iterable[Tuple[str, Iterable[str]]]) -> str:
    """PowerShell, ki caka na konec procesa `pid` in vmesnikom, na katerih je se Scit, vrne DNS (_ukaz_povrni)."""
    deli = ["$ErrorActionPreference = 'SilentlyContinue'", "$p = Get-Process -Id %d" % int(pid),
            "if ($p) { $p.WaitForExit() }"]
    for ime, staticni in list(vmesniki)[:NAJVEC_VMESNIKOV]:
        if not veljavno_ime_vmesnika(ime):
            continue
        deli.append("if (@((Get-DnsClientServerAddress -InterfaceAlias %s -AddressFamily IPv4).ServerAddresses) "
                    "-contains %s) { %s }" % (ps_niz(ime), ps_niz(NASLOV),
                                              _ukaz_povrni(ime, staticni).replace(" -ErrorAction Stop", "")))
    if len(deli) > 3:
        deli.append("Clear-DnsClientCache")      # samo, ce je kaj vrnila (brez vmesnikov se ne dotakne nicesar)
    return "\n".join(deli)


def zazeni_strazo_padca(pid: int, vmesniki: Iterable[Tuple[str, Iterable[str]]]) -> Optional[subprocess.Popen]:
    """Straza ob padcu: locen skrit proces. Ob rednem izklopu ga Scit sam ustavi (po PID, ki ga hrani Popen)."""
    if sys.platform != "win32":
        return None
    kodirano = base64.b64encode(skripta_straze_padca(pid, vmesniki).encode("utf-16-le")).decode("ascii")
    try:
        return subprocess.Popen([_sistemski(*POWERSHELL), "-NoProfile", "-NonInteractive", "-EncodedCommand", kodirano],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                close_fds=True, creationflags=_BREZ_OKNA)
    except Exception as e:  # noqa: BLE001
        print("[SafeerOS] scit: straza ob padcu:", type(e).__name__, e)
        return None


# ---------------------------------------------------------------------- Windows: streznik naprej (DoH ali svoj)
#: Isti naslovi kot core/doh_proxy.DOH_PROVIDERS v Safeer-linux (doh_proxy na Windows potrebuje libsoup in tu ne tece).
DOH_NAPREJ = {
    "cloudflare": "https://1.1.1.1/dns-query",
    "quad9": "https://dns.quad9.net/dns-query",
    "google": "https://dns.google/dns-query",
    "adguard": "https://dns.adguard-dns.com/dns-query",
    "opendns": "https://doh.opendns.com/dns-query",
}
NAJVEC_ODGOVORA = 65535


class _BrezPreusmeritev(urllib.request.HTTPRedirectHandler):
    """DoH ne sledi preusmeritvam: poizvedba gre samo na streznik, ki ga je izbral uporabnik."""

    def redirect_request(self, *argumenti, **kljucni):  # noqa: D401
        return None


_ODPIRAC = urllib.request.build_opener(_BrezPreusmeritev, urllib.request.HTTPSHandler(context=ssl.create_default_context()))


def doh_paket(url: str, paket: bytes, cas: float) -> Optional[bytes]:
    """Poizvedba prek DoH (RFC 8484, POST, ID 0); odgovor z izvirnim ID ali None (ni odgovora, SERVFAIL)."""
    if len(paket) < 12 or not str(url).lower().startswith("https://"):
        return None
    z = urllib.request.Request(url, data=b"\x00\x00" + paket[2:], method="POST",
                               headers={"Content-Type": "application/dns-message", "Accept": "application/dns-message",
                                        "User-Agent": "Safeer"})
    try:
        with _ODPIRAC.open(z, timeout=cas) as o:  # noqa: S310 - samo https (preverjeno zgoraj)
            if o.status != 200 or o.headers.get_content_type() != "application/dns-message":
                return None
            data = o.read(NAJVEC_ODGOVORA + 1)
    except (OSError, ValueError, http.client.HTTPException):
        return None
    if len(data) < 12 or len(data) > NAJVEC_ODGOVORA or data[3] & 0x0F == 2:
        return None
    return paket[:2] + data[2:]


def _naslov_in_vrata(vrednost: str) -> Tuple[str, int]:
    if vrednost.startswith("["):
        naslov, _, vrata = vrednost[1:].partition("]:")
        return naslov, int(vrata or 53)
    if vrednost.count(":") == 1:
        naslov, vrata = vrednost.split(":")
        return naslov, int(vrata)
    return vrednost, 53


def navaden_paket(streznik: str, vrata: int, paket: bytes, cas: float) -> Optional[bytes]:
    """Navadna poizvedba (UDP, prirezan odgovor prek TCP) z nakljucnim ID na uporabnikov streznik (npr. Pi-hole)."""
    if len(paket) < 12:
        return None
    ident = os.urandom(2)
    vprasanje = ident + paket[2:]
    druzina = socket.AF_INET6 if ":" in streznik else socket.AF_INET
    try:
        with socket.socket(druzina, socket.SOCK_DGRAM) as s:
            s.settimeout(cas)
            s.connect((streznik, vrata))
            s.send(vprasanje)
            konec = time.monotonic() + cas
            while True:
                s.settimeout(max(0.05, konec - time.monotonic()))
                odgovor = s.recv(4096)
                if odgovor[:2] == ident and len(odgovor) >= 12:
                    break
        if odgovor[2] & 0x02:
            with socket.create_connection((streznik, vrata), timeout=cas) as s:
                s.sendall(struct.pack("!H", len(vprasanje)) + vprasanje)
                n = struct.unpack("!H", Razresevalnik._preberi(s, 2))[0]
                odgovor = Razresevalnik._preberi(s, n)
                if odgovor[:2] != ident:
                    return None
    except (OSError, struct.error):
        return None
    if len(odgovor) < 12 or odgovor[3] & 0x0F == 2:
        return None
    return paket[:2] + odgovor[2:]


def razcleni_po_meri(besedilo: str) -> Tuple[str, str]:
    """Streznik naprej po meri (kot doh_proxy.razcleni_po_meri v Safeer-linux): ("doh", "https://..."), ("ip", "naslov"
    ali "naslov:vrata" / "[v6]:vrata") ali ("", kljuc napake). Gol ime streznika postane https://ime/dns-query.
    Lokalni naslovi (Pi-hole, usmerjevalnik) so dovoljeni; povezavno-lokalni, vecvrocni in nedolocen ne."""
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
        if not p.hostname or p.username or p.password:
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
        if "/" in t or ":" in t or not cista_domena(t):
            return "", "doh_po_meri_oblika"
        return "doh", "https://%s/dns-query" % t.lower()
    if vrata and not (vrata.isdigit() and 0 < int(vrata) <= 65535):
        return "", "doh_po_meri_oblika"
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified or (ip.is_reserved and not ip.is_loopback):
        return "", "doh_po_meri_naslov"
    if not vrata:
        return "ip", str(ip)
    return "ip", ("[%s]:%s" % (ip, vrata)) if ip.version == 6 else "%s:%s" % (ip, vrata)


# ---------------------------------------------------------------------- Scit
class Scit:
    def __init__(self, shramba, mapa: Optional[str] = None) -> None:
        self.shramba = shramba
        self.mapa = mapa or podatkovna_mapa()
        self.seznami: Optional[Seznami] = None
        self.razresevalnik: Optional[Razresevalnik] = None
        self.vmesniki: List[str] = []
        #: Vmesniki, kjer IPv6 DNS omrezja ostane mimo Scita (IPv6 ni bilo mogoce nastaviti).
        self.mimo_ipv6: List[str] = []
        # Neuspela preusmeritev DNS (npr. brez skrbniskih pravic): ne poskusamo vsakih 20 s znova.
        self._neuspehi: Dict[str, int] = {}
        self._naslednji_poskus: Dict[str, float] = {}
        self.strezniki: List[str] = []
        self.napaka = ""
        self._straza: Optional[threading.Thread] = None
        self._straza_padca: Optional[subprocess.Popen] = None
        self._kljuc = threading.Lock()
        #: Imena, ki jih je uporabnik spustil sam (ime -> velja do, time.time), in konec premora (time.monotonic).
        self._izjeme: Dict[str, float] = self._preberi_izjeme()
        self._premor_do = 0.0

    #: Ura za izjeme (preizkusi jo zamenjajo).
    _ura = staticmethod(time.time)

    # >>> SKUPNO Z LINUXOM (Safeer-linux 746f975 core/os_scit.py: metode1) - ne spreminjaj samo tu
    def _preberi_izjeme(self) -> Dict[str, float]:
        """Shranjene izjeme ({"ime", "do"}). Starejsa oblika (samo ime, brez poteka) dobi 30 dni od zdaj in se zapise na
        novo - izjema ne izgine nenadoma, a tudi ne velja vec za vedno (4. 11. 2026)."""
        shranjene = self.shramba.get("scit_izjeme", [])
        zdaj = self._ura()
        izid: Dict[str, float] = {}
        preseljeno = False
        for v in shranjene if isinstance(shranjene, list) else []:
            if isinstance(v, dict):
                d = cista_domena(v.get("ime"))
                try:
                    do = float(v.get("do"))
                except (TypeError, ValueError):
                    continue
            else:
                d, do, preseljeno = cista_domena(v), zdaj + IZJEMA_S, True
            if d and d not in izid and do > zdaj and len(izid) < NAJVEC_IZJEM:
                izid[d] = do
        if preseljeno:
            self._zapisi_izjeme(izid)
        return izid

    def _zapisi_izjeme(self, izjeme: Dict[str, float]) -> None:
        self.shramba.set("scit_izjeme", [{"ime": d, "do": int(do)} for d, do in izjeme.items()])

    def _veljavne_izjeme(self) -> Dict[str, float]:
        zdaj = self._ura()
        return {d: do for d, do in self._izjeme.items() if do > zdaj}

    # -- streznik naprej
    def naprej(self) -> Tuple[str, str]:
        """(izbira, naslov po meri): kam Scit posreduje dovoljena imena. Privzeto Cloudflare prek DoH."""
        izbira = str(self.shramba.get("scit_naprej", PRIVZETI_NAPREJ) or PRIVZETI_NAPREJ)
        return (izbira if izbira in IZBIRE_NAPREJ else PRIVZETI_NAPREJ), str(self.shramba.get("scit_naprej_po_meri", "") or "")
    # <<< SKUPNO Z LINUXOM (metode1)

    def nastavi_naprej(self, izbira, po_meri="") -> dict:
        """Uporabnik izbere streznik naprej. Naslov po meri (DoH ali IP, tudi Pi-hole) se preveri samo po obliki."""
        izbira = str(izbira or "")
        po_meri = str(po_meri or "").strip()
        self.napaka = ""
        if izbira not in IZBIRE_NAPREJ:
            self.napaka = "naprej"
            return self.stanje()
        if izbira == "custom":
            vrsta, vrednost = razcleni_po_meri(po_meri)
            if vrsta == "ip" and je_zanka_naprej(vrednost):
                self.napaka = "naprej_zanka"       # Scit ne sme posredovati sam sebi
                return self.stanje()
            if not vrsta:
                self.napaka = "naprej"
                return self.stanje()
            self.shramba.set("scit_naprej_po_meri", po_meri)
        self.shramba.set("scit_naprej", izbira)
        self._zagonska_imena = None
        self._osvezi_predpomnilnik()
        return self.stanje()

    def _naprej(self, paket: bytes) -> Optional[bytes]:
        """Streznik naprej po izbiri uporabnika; None = krajevni DNS (izbira »router« ali DoH ne odgovori)."""
        izbira, po_meri = self.naprej()
        if izbira == "router":
            return None
        if izbira == "custom":
            vrsta, vrednost = razcleni_po_meri(po_meri)
            if vrsta == "ip":
                if je_zanka_naprej(vrednost):
                    return None        # stara nastavitev iz casa pred varovalom: krajevni DNS namesto zanke
                streznik, vrata = _naslov_in_vrata(vrednost)
                return navaden_paket(streznik, vrata, paket, CAS_UPSTREAM)
            return doh_paket(vrednost, paket, CAS_UPSTREAM) if vrsta == "doh" else None
        url = DOH_NAPREJ.get(izbira)
        return doh_paket(url, paket, CAS_UPSTREAM) if url else None

    _zagonska_imena: Optional[Tuple[Tuple[str, str], frozenset]] = None

    def _zagonsko(self, ime: str) -> bool:
        """Ime streznika DoH naprej: knjiznica TLS ga razresi prek sistemskega DNS - torej prek Scita; poslano naprej
        prek DoH bi bilo zanka. Gre naravnost krajevnemu DNS (ime streznika ni skrivnost). Strezniki z IP ga nimajo."""
        nastavitev = self.naprej()
        shranjeno = self._zagonska_imena
        if shranjeno is None or shranjeno[0] != nastavitev:
            izbira, po_meri = nastavitev
            url = DOH_NAPREJ.get(izbira, "")
            if izbira == "custom":
                vrsta, vrednost = razcleni_po_meri(po_meri)
                url = vrednost if vrsta == "doh" else ""
            imena: set = set()
            gostitelj = (urllib.parse.urlsplit(url).hostname or "").lower().rstrip(".") if url else ""
            try:
                ipaddress.ip_address(gostitelj)
            except ValueError:
                if gostitelj:
                    imena.add(gostitelj)
            shranjeno = self._zagonska_imena = (nastavitev, frozenset(imena))
        return ime in shranjeno[1]

    # >>> SKUPNO Z LINUXOM (Safeer-linux 746f975 core/os_scit.py: metode2) - ne spreminjaj samo tu
    def _kategorija(self, ime: str) -> Optional[str]:
        """Kar razresevalnik vprasa za vsako ime. Uporabnikove izjeme (natanko to ime, 30 dni) in premor spustijo samo
        oglase in sledilce (to je tisto, zaradi cesar kaksna stran ne dela) - nevarne strani ostanejo blokirane."""
        kategorija = self.seznami.kategorija(ime) if self.seznami is not None else None
        if kategorija == KATEGORIJA_PREMORA and self._izjeme and self._izjeme.get(ime, 0) > self._ura():
            groznja = getattr(self.seznami, "groznja", None)
            try:
                if groznja is not None and not groznja(ime):     # tudi nadrejena domena in podpisani seznam
                    return None
            except Exception:  # noqa: BLE001 - fail-closed
                return kategorija
        if kategorija == KATEGORIJA_PREMORA and self._premor_do and time.monotonic() < self._premor_do:
            return None
        if kategorija == KATEGORIJA_PREMORA and webtor.je_stalna_izjema_scita(ime):
            # Webtor rezerva (25. 10. 2026): oglasni seznam ne sme ustaviti toka (API in gostitelj toka, natancno -
            # core/webtor.py). Izmerjeno 25. 10.: nasi seznami jih ne blokirajo. Seznami grozenj imajo vedno prednost -
            # tudi za nadrejeno domeno in podpisani seznam (Grok N15); brez te preverbe ostane blokirano.
            groznja = getattr(self.seznami, "groznja", None)
            try:
                if groznja is not None and not groznja(ime):
                    return None
            except Exception:  # noqa: BLE001 - fail-closed
                return kategorija
        return kategorija

    def dovoli(self, domena, dovoli: bool = True) -> dict:
        """Uporabnik spusti ime, ki ga je Scit pravkar blokiral (natanko to ime, IZJEMA_S), ali izjemo odstrani.
        Dovoliti je mogoce samo ime s seznama nazadnje blokiranih (stran ne more vnaprej dovoliti poljubne domene) in
        nikoli ime s seznama grozenj (»Nevarno«, kot Android ScitPregled.dodajIzjemo; prej je Linux spustil tudi
        groznjo). Brez seznamov ali ob napaki: ne vem ni da."""
        d = cista_domena(domena)
        izjeme = self._veljavne_izjeme()
        r = self.razresevalnik
        if d and dovoli:
            nedavne = {z["ime"] for z in (r.zadnje if r is not None else [])}
            groznja = getattr(self.seznami, "groznja", None)
            try:
                nevarno = groznja is None or bool(groznja(d))
            except Exception:  # noqa: BLE001
                nevarno = True
            if d in nedavne and not nevarno and (d in izjeme or len(izjeme) < NAJVEC_IZJEM):
                izjeme.pop(d, None)
                izjeme[d] = self._ura() + IZJEMA_S
                with r._kljuc:
                    r.zadnje = [z for z in r.zadnje if z["ime"] != d]
        elif d and not dovoli:
            izjeme.pop(d, None)
        if izjeme != self._izjeme:
            self._izjeme = izjeme
            self._zapisi_izjeme(izjeme)
            self._osvezi_predpomnilnik()
        return self.stanje()

    def premor(self, minut) -> dict:
        """Premor: Scit toliko minut (najvec 60) ne blokira oglasov in sledilcev, potem nadaljuje sam; 0 nadaljuje
        takoj. Nevarne strani ostanejo blokirane tudi med premorom."""
        try:
            m = max(0.0, min(float(minut), float(NAJDALJSI_PREMOR_MIN)))
        except (TypeError, ValueError):
            m = 0.0
        self._premor_do = konec = time.monotonic() + m * 60.0 if m > 0 else 0.0
        if m > 0:
            # Ko premor potece, naj imena, razresena med premorom, ne ostanejo v predpomnilniku.
            casovnik = threading.Timer(m * 60.0 + 0.2, self._po_premoru, args=(konec,))
            casovnik.daemon = True
            casovnik.start()
        self._osvezi_predpomnilnik()
        return self.stanje()

    def _po_premoru(self, konec: float) -> None:
        if self._premor_do == konec:      # premor ni bil medtem koncan ali nastavljen na novo
            self._premor_do = 0.0
            self._osvezi_predpomnilnik()

    def premor_se(self) -> int:
        """Koliko sekund premora je se ostalo (0 = Scit blokira)."""
        ostane = self._premor_do - time.monotonic() if self._premor_do else 0.0
        return int(ostane) + 1 if ostane > 0 else 0

    @property
    def vklopljen(self) -> bool:
        return bool(self.shramba.get("scit", False))
    # <<< SKUPNO Z LINUXOM (metode2)

    def _osvezi_predpomnilnik(self) -> None:
        """Po spremembi (izjema, premor, streznik naprej) Windows pozabi razresena imena. V ozadju: klic PowerShell
        traja okoli sekunde, vmesnik ne sme cakati."""
        r = self.razresevalnik
        if r is not None and r.vrata:
            threading.Thread(target=izprazni_predpomnilnik, name="safeer-scit-predpomnilnik", daemon=True).start()

    def mozno(self) -> bool:
        return True

    def stanje(self) -> dict:
        """Brez podprocesov: vmesnik ga bere vsakih 5 s."""
        r = self.razresevalnik
        izbira, po_meri = self.naprej()
        s = {"vklop": self.vklopljen, "mozno": True, "razlog": "", "tece": bool(r and r.vrata), "napaka": self.napaka,
             "vrata": r.vrata if r else 0, "vmesniki": list(self.vmesniki), "mimoIpv6": list(self.mimo_ipv6),
             "strezniki": list(self.strezniki), "blokiranih": r.blokiranih if r else 0,
             "poizvedb": r.poizvedb if r else 0, "zadnje": list(r.zadnje) if r else [], "pravilo": True,
             "domen": 0, "pravil": 0, "izjeme": list(self._veljavne_izjeme()), "premor": self.premor_se(),
             "naprej": izbira, "naprejPoMeri": po_meri,
             # Uporabnik je streznik naprej ze izbral sam (shranjena izbira); sicer ga vmesnik ob vklopu vprasa.
             "naprejIzbran": self.shramba.get("scit_naprej") is not None, "rezerv": getattr(r, "rezerv", 0),
             "nesifrirano": bool(r is not None and r.vrata and r.sifrirano_naprej() and r.nesifrirano())}
        if self.seznami is not None:
            s.update(self.seznami.stanje())
        return s

    # -- spomin krajevnega DNS (shramba): kaj je imel vmesnik pred Scitom, za posredovanje in povrnitev
    def _spomin(self) -> Dict[str, dict]:
        s = self.shramba.get("scit_krajevni_dns", {})
        return {k: v for k, v in s.items() if isinstance(k, str) and isinstance(v, dict)} if isinstance(s, dict) else {}

    def _zapisi_spomin(self, spomin: Dict[str, dict]) -> None:
        self.shramba.set("scit_krajevni_dns", dict(list(spomin.items())[-NAJVEC_VMESNIKOV * 2:]))

    def _rocni(self, vmesnik: str) -> List[str]:
        return list((self._spomin().get(vmesnik) or {}).get("staticni") or [])

    def zacni_ce_vklopljen(self) -> None:
        """Ob zagonu Safeer OS: Scit, ki je bil vklopljen, tece naprej; izklopljen pospravi, kar je ostalo po padcu."""
        threading.Thread(target=self._zagon, name="safeer-scit-zagon", daemon=True).start()

    def _zagon(self) -> None:
        if self.vklopljen:
            self._zazeni()
        else:
            self.pospravi_ostanke()

    def pospravi_ostanke(self) -> List[str]:
        """Vmesnikom, ki jim je Scit pustil samo sebe (padec, ki ga straza ob padcu ni ujela), vrne krajevni DNS.
        Samo vmesnikom, ki smo jih nastavili mi (spomin), in samo, ce na 127.0.0.1:53 ne odgovori noben Scit."""
        spomin = self._spomin()
        if not spomin or _odgovori_kanarcku(VRATA[0], 0.5):
            return []
        popravljeni: List[str] = []
        for v in beri_vmesnike() or []:
            if v["ime"] in spomin and NASLOV in v["v4"] and povrni(v["ime"], self._rocni(v["ime"])):
                popravljeni.append(v["ime"])
        return popravljeni

    def nastavi(self, vklop: bool) -> dict:
        self.napaka = ""
        if vklop:
            self._zazeni()
            if self.napaka in ("", "ni_omrezja", "ni_krajevnega", "ipv6"):
                # Brez omrezja ob vklopu nastavitev vseeno velja: straza zacne filtrirati, ko se racunalnik poveze.
                self.shramba.set("scit", True)
            else:
                # Vrata zasedena ali brez pravic: ne pustimo napol vklopljenega (prej je razresevalnik tekel naprej,
                # stikalo pa je kazalo izklop).
                napaka = self.napaka
                self._ustavi()
                self.napaka = napaka
        else:
            self.shramba.set("scit", False)
            self._ustavi()
        return self.stanje()

    def _zazeni(self) -> bool:
        try:
            from core import scit_pravila
            scit_pravila.skupna()           # podpisan seznam pravil Scita se osvezuje tudi brez odprtega Spleta
        except Exception as e:  # noqa: BLE001
            print("[SafeerOS] scit: pravila:", type(e).__name__, e)
        with self._kljuc:
            if self.seznami is None:
                self.seznami = Seznami(self.mapa)
            self.seznami.zazeni()
            if self.razresevalnik is None:
                self.razresevalnik = RazresevalnikWin(self._kategorija, lambda: self.strezniki, self._naprej,
                                                      zagonsko=self._zagonsko)
                self.razresevalnik.sifrirano_naprej = lambda: self.naprej()[0] != "router"
            if not self.razresevalnik.zazeni():
                self.napaka = "vrata"           # vrata 53 ima drug program: povemo, ne filtriramo tiho
                return False
            self._uporabi()
            if self._straza is None:
                self._straza = threading.Thread(target=self._strazi, name="safeer-scit-straza", daemon=True)
                self._straza.start()
            return bool(self.vmesniki)

    def _uporabi(self) -> None:
        """DNS vseh povezanih vmesnikov SAMO na Scit (tudi po menjavi omrezja); strezniki naprej (krajevni DNS) se
        preberejo tu, ne ob vsaki poizvedbi. Brez krajevnega DNS ostane seznam prazen: SERVFAIL, nic tujega."""
        r = self.razresevalnik
        if r is None or not r.vrata:
            return
        stanje = beri_vmesnike()
        if stanje is None:
            return          # branje ni uspelo: nic ne spreminjamo (prej je izmislil vmesnika »Ethernet« in »Wi-Fi«)
        z6 = isinstance(r, RazresevalnikWin) and r.ima_ipv6()
        spomin = self._spomin()
        nov_spomin = dict(spomin)
        strezniki: List[str] = []
        vmesniki: List[str] = []
        mimo6: List[str] = []
        novo = zavrnjeno = False
        for v in stanje:
            ime = v["ime"]
            lastni, zapis = krajevni_dns(v, spomin.get(ime))
            if zapis is not None:
                nov_spomin[ime] = zapis
            for s in lastni:
                if s not in strezniki:
                    strezniki.append(s)
            scit4, tuji6 = na_scitu(v, z6)
            if (not scit4 or (z6 and tuji6)) and time.monotonic() >= self._naslednji_poskus.get(ime, 0.0):
                izid = usmeri(ime, z6)
                if izid:
                    novo, scit4 = True, True
                    tuji6 = tuji6 and izid != "ok"
                    if izid == "ok":
                        self._neuspehi.pop(ime, None)
                        self._naslednji_poskus.pop(ime, None)
                if izid != "ok":
                    # Ni slo (ali IPv6 ni slo): naslednji poskus cez 40 s, 80 s ... najvec 30 min - ne vsakih 20 s.
                    n = self._neuspehi.get(ime, 0) + 1
                    self._neuspehi[ime] = n
                    self._naslednji_poskus[ime] = time.monotonic() + min(1800.0, 20.0 * (2 ** n))
                    zavrnjeno = zavrnjeno or not izid
            elif not scit4:
                zavrnjeno = True
            if scit4:
                vmesniki.append(ime)
                if tuji6:
                    mimo6.append(ime)
        if nov_spomin != spomin:
            self._zapisi_spomin(nov_spomin)
        self.strezniki = strezniki       # brez tujega rezervnega razresevalnika (prej 1.1.1.1, 9.9.9.9)
        self.mimo_ipv6 = mimo6
        if set(vmesniki) != set(self.vmesniki) or (vmesniki and self._straza_padca is None):
            self._ustavi_strazo_padca()
            if vmesniki:
                self._straza_padca = zazeni_strazo_padca(os.getpid(), [(x, self._rocni(x)) for x in vmesniki])
        self.vmesniki = vmesniki
        if self.napaka in ("", "ni_omrezja", "pravice", "ipv6", "ni_krajevnega"):
            if not vmesniki:
                self.napaka = "pravice" if zavrnjeno else "ni_omrezja"
            elif mimo6:
                self.napaka = "ipv6"
            elif not strezniki and self.naprej()[0] == "router":
                self.napaka = "ni_krajevnega"
            else:
                self.napaka = ""
        if novo:
            izprazni_predpomnilnik()     # ze razresena (zdaj blokirana) imena naj ne ostanejo v predpomnilniku

    def _ustavi_strazo_padca(self) -> None:
        p, self._straza_padca = self._straza_padca, None
        if p is not None:
            try:
                p.kill()
                p.wait(timeout=5)
            except Exception:  # noqa: BLE001 - ze koncan
                pass

    def _ozivi(self) -> None:
        """Razresevalnik ne odgovarja: zazenemo ga znova; ce ne gre (vrata je vzel drug program), vmesnikom vrnemo
        krajevni DNS - racunalnik ne sme ostati brez DNS - in to povemo (napaka »vrata«)."""
        r = self.razresevalnik
        if r is None:
            return
        r.ustavi()
        if r.zazeni():
            if self.napaka == "vrata":
                self.napaka = ""
            return
        for v in list(self.vmesniki):
            povrni(v, self._rocni(v))
        self.vmesniki = []
        self._ustavi_strazo_padca()
        self.napaka = "vrata"

    def _strazi(self) -> None:
        jaz = threading.current_thread()
        tihih = 0
        while self._straza is jaz:
            time.sleep(PREGLED_S)
            if self._straza is not jaz or not self.vklopljen or self.razresevalnik is None:
                return
            try:
                with self._kljuc:
                    r = self.razresevalnik
                    if r.vrata and _odgovori_kanarcku(r.vrata, 0.5):
                        tihih = 0
                    else:
                        tihih += 1
                        if tihih >= 2 or not r.vrata:
                            self._ozivi()
                    self._uporabi()
            except Exception as e:  # noqa: BLE001 - straza ne sme umreti
                print("[SafeerOS] scit: straza:", type(e).__name__, e)

    def _ustavi(self) -> None:
        with self._kljuc:
            self._straza = None
            for v in list(self.vmesniki):
                povrni(v, self._rocni(v))
            self.vmesniki = []
            self.mimo_ipv6 = []
            self._ustavi_strazo_padca()
            if self.razresevalnik is not None:
                self.razresevalnik.ustavi()
            if self.seznami is not None:
                self.seznami.ustavi()

    def koncaj(self) -> None:
        """Ob izhodu iz Safeer OS: brez razresevalnika bi racunalnik ostal brez DNS, zato povrnemo."""
        r = self.razresevalnik
        if self.vmesniki or self._straza_padca is not None or (r is not None and r.vrata):
            self._ustavi()
