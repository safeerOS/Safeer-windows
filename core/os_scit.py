"""Scit za Safeer OS na Linuxu: filtriranje DNS za ves racunalnik (kot Scit na televizorju in tablici).

Safeer OS tece majhen razresevalnik DNS na 127.0.0.1 (vrata nad 1024, brez pravic). Vsako ime, ki ga
racunalnik hoce razresiti, najprej preveri v naboru blokiranih domen - isti seznami kot pri Scitu na
televizorju (hagezi PRO in TIF, Fake, URLhaus, Phishing Army, SI-CERT) in Safeerjev podpisani seznam
groznj - in ga, ce je na seznamu, zavrne (NXDOMAIN); vse drugo posreduje strezniku naprej. Privzeto je to DNS, ki
ga je dal usmerjevalnik (NetworkManager) - brez tujega razresevalnika (lastnik 4. 11. 2026, en Scit za vse naprave;
prej Cloudflare DoH). Uporabnik ob prvem vklopu izbere sam in izbiro kadarkoli spremeni: DNS usmerjevalnika ali
sifriran DoH (Cloudflare, Quad9, Google, AdGuard, OpenDNS, svoj). Brez krajevnega DNS je odgovor SERVFAIL.

Da racunalnik ta razresevalnik uporablja, Safeer OS systemd-resolved za povezano omrezje pove:
»DNS je 127.0.0.1:<vrata>« (resolvectl). To je sistemska nastavitev in polkit zanjo zahteva geslo.
V paketu .deb to naredi root pomocnik /usr/lib/safeer-os/scit-dns (packaging/scit-dns) s fiksnimi dejanji (usmeri na
Scit, vrni streznike NetworkManagerja); ob prvem vklopu enkrat z geslom (pkexec) namesti pravilo polkit, ki skrbniku
dovoli brez gesla samo tega pomocnika - kot namestitev programa: geslo enkrat, potem dela samo. V Flatpaku in
AppImage isti pomocnik ob prvem vklopu (geslo enkrat) gre na gostitelja v /usr/local/lib/safeer-os (POMOCNIK_GOSTITELJA);
sirokega pravila za resolve1 ne namescamo vec (pregled 4. 11. 2026).
Ob izklopu vmesnik spet dobi streznike, ki jih je dolocil NetworkManager; ob zagonu Safeer OS se, ce je Scit vklopljen, uporabi znova.

Spreminjamo SAMO seznam streznikov DNS vmesnika. Iskalnih domen (»lan«), privzete poti in nastavitev VPN se
ne dotikamo. Kjer programi imen ne razresujejo prek systemd-resolved (lasten streznik DNS, npr. Pi-hole),
Scit ne more filtrirati in se nastavitev ne dotakne (glej `razlog_nemoznosti`).

Vse to je preverjeno na pravem systemd-resolved + NetworkManager: `tools/scit_lab` (dva vsebnika Docker).

Nabor domen je urejeno polje 64-bitnih zgoscenk (blake2b) - pol milijona domen v nekaj MB, iskanje z
bisekcijo; shranjen je na disku, da je ob zagonu takoj tu. Seznami se osvezujejo v ozadju (pogojni GET).
Zunanjih vhodov ne sprejema (samo 127.0.0.1); vsak ukaz je fiksen seznam argumentov.
"""

from __future__ import annotations

import bisect
import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import stat as _stat
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import weakref
from array import array
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from core import scit_gostitelji

from core import root_ukaz, webtor
from core.signed_feed import _atomic_write, isti_gostitelj


def _windows():
    """Platformni sloj za Windows (PowerShell, Task Scheduler); na Linuxu se ne nalozi."""
    from core import os_scit_windows
    return os_scit_windows

NASLOV = "127.0.0.1"
#: Windows: sistemski DNS ne pozna vrat, zato razresevalnik poslusa na 127.0.0.1:53 (core/os_scit_windows.py).
VRATA = (53,) if sys.platform == "win32" else (5354, 5355, 5356, 5357)
PRAVILO_POT = "/etc/polkit-1/rules.d/49-safeer-os-scit.rules"
#: STARO siroko pravilo (do 4. 11. 2026): ne namesca se vec in ne velja kot dovoljenje; pomocnik (scit-dns dovoli) ga
#: na gostitelju odstrani. Ostane samo za prepoznavo v preizkusih.
PRAVILO = """// Safeer OS - Scit (filtriranje DNS): skrbnik sme systemd-resolved nastaviti streznik DNS brez gesla.
polkit.addRule(function (action, subject) {
    if ((action.id == "org.freedesktop.resolve1.set-dns-servers" ||
         action.id == "org.freedesktop.resolve1.set-domains" ||
         action.id == "org.freedesktop.resolve1.revert") &&
        subject.local && subject.active && subject.isInGroup("sudo")) {
        return polkit.Result.YES;
    }
});
"""
CAS_UPSTREAM = 2.5
#: Toliko najvec caka nas odgovor na sifriran streznik naprej (DoH), preden isto ime vprasamo usmerjevalnik. systemd-resolved
#: na nas caka ~750 ms (DNS_TIMEOUT_MIN_USEC), nato vprasa naslednji streznik - usmerjevalnik, MIMO Scita - in pri njem
#: ostane: do naslednjega pregleda straze (PREGLED_S) bi se blokirane strani razresevale. CI 8ac36e9 (Flatpak, brez
#: interneta): DoH je cakal 2,5 s, resolved je presel na usmerjevalnik in »Blokiraj spet« ni veljal. Odgovor zato
#: vedno v ROK_NAPREJ + cas usmerjevalnika (LAN); DoH tece naprej v ozadju in odloci, ali gremo za nekaj casa mimo njega.
ROK_NAPREJ = 0.4
#: Skupni rok za streznike usmerjevalnika prek UDP (S8, pregled 5. 11. 2026): vprasamo jih vse hkrati, prvi odgovor
#: zmaga; ce v roku ne odgovori nobeden, SERVFAIL. Prej zaporedno do CAS_UPSTREAM (2,5 s) na streznik in na koncu molk -
#: systemd-resolved je po ~750 ms presel mimo Scita. Isti rok kot DoH (ROK_NAPREJ): odgovor je vedno pod ~0,8 s.
ROK_USMERJEVALNIK = ROK_NAPREJ
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
    # Lastnik 9. 11. 2026: Scit enako dober ali boljsi kot Pi-hole - privzeti seznam Pi-hole (StevenBlack Unified). Meritev
    # 9. 11.: nabor brez njega je ustavil 79,4 % njegovih domen (~8.500 zivih ne). Enako na TV (ThreatFeedsUpdater).
    ("stevenblack", "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts", "oglasi"),
    # Lastnik 9. 11. 2026: »upostevaj vse, kar AdGuard blokira« - AdGuard DNS filter (javen, GPL-3.0); meritev 9. 11.: nas
    # nabor ga je ustavil 43,1 %. Izjeme @@ glej razcleni_seznam. Enako na TV (ThreatFeedsUpdater).
    ("adguard-dns", "https://adguardteam.github.io/AdGuardSDNSFilter/Filters/filter.txt", "oglasi"),
    # abuse.ch od 21. 10. 2026 brez kljuca vrne 410 (lastnik 9. 11. 2026): uporabnik vpise SVOJ brezplacni kljuc (Scit >
    # Seznami s kljucem); brez njega se seznam ne prenasa in ostane zadnja kopija. Enako TV (AbuseChKljuc).
    ("urlhaus", "https://urlhaus-api.abuse.ch/v2/files/exports/{KLJUC}/hostfile.txt", "malware"),
    ("phishing-army", "https://phishing.army/download/phishing_army_blocklist_extended.txt", "phishing"),
    ("si-cert", "https://www.cert.si/misp/rpz/last.txt", "phishing"),
)
#: Seznami naslovov IPv4 botnet C2 (Feodo Tracker, CC0) za blokado po IP odgovora (lastnik 26. 11. 2026, po zgledu
#: blocky; enako na TV: ScitIpSeznam.kt). Ne gredo v nabor domen. »aggressive« ima tudi starejse naslove (ok. 7600).
VIRI_IP = (("feodo", "https://feodotracker.abuse.ch/downloads/ipblocklist.txt"),
           ("feodo-aggressive", "https://feodotracker.abuse.ch/downloads/ipblocklist_aggressive.txt"))
NAJVEC_BAJTOV_IP = 1 << 20
_IPV4 = re.compile(r"^(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$")


def razcleni_ip_seznam(besedilo: str) -> frozenset:
    """Javni naslovi IPv4 (en v vrstici, # komentar). Neveljavni in ne-javni (zasebni, krajevni, rezervirani) se zavrzejo:
    zastrupljen vnos 127.0.0.1 ali 192.168.x.x ne sme ustaviti krajevnih imen (enako TV ScitIpSeznam.razclani)."""
    izhod = set()
    for vrstica in besedilo.splitlines():
        v = vrstica.split("#", 1)[0].strip()
        if v and _IPV4.match(v) and ipaddress.IPv4Address(v).is_global:
            izhod.add(v)
    return frozenset(izhod)


def naslovi4(d: bytes) -> List[str]:
    """Naslovi IPv4 iz zapisov A (razred IN, 4 bajti) v odgovoru DNS, najvec 64 zapisov; pokvarjen odgovor vrne, kar je
    do napake prebral (enako kot cname_cilji; TV DnsPaket.naslovi4)."""
    if len(d) < 12:
        return []
    qd, an = struct.unpack("!HH", d[4:8])
    i = 12
    for _ in range(min(qd, 4)):
        r = _ime_odgovora(d, i)
        if r is None:
            return []
        i = r[1] + 4
    izhod: List[str] = []
    for _ in range(min(an, 64)):
        r = _ime_odgovora(d, i)
        if r is None or r[1] + 10 > len(d):
            return izhod
        k = r[1]
        vrsta, razred, rdl = struct.unpack("!HH", d[k:k + 4]) + (struct.unpack("!H", d[k + 8:k + 10])[0],)
        if k + 10 + rdl > len(d):
            return izhod
        if vrsta == 1 and razred == 1 and rdl == 4:
            izhod.append(".".join(str(b) for b in d[k + 10:k + 14]))
        i = k + 10 + rdl
    return izhod


VIRI_URLHAUS = dict((o, u) for o, u, _k in VIRI)["urlhaus"]
KATEGORIJE = ("oglasi", "groznje", "prevare", "malware", "phishing", "botnet")
#: Premor ustavi samo to kategorijo (oglasi in sledenje); vse druge so nevarne strani in ostanejo blokirane.
KATEGORIJA_PREMORA = "oglasi"
KATEGORIJA_SEZNAMA_GROZNJ = {"botnet_c2": "botnet", "malware": "malware", "phishing": "phishing", "scam": "prevare"}
NAJVEC_BAJTOV = 24 * 1024 * 1024
NAJMANJ_DOMEN = 1000
PRVA_OSVEZITEV = 5.0
OSVEZITEV = 6 * 3600.0
PONOVNI_POSKUS = 30 * 60.0
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
    dit.whatsapp.net, spade.twitch.tv) ali cist oglasni/merilni streznik brez uporabniske strani (»oglasni_strezniki«:
    doubleclick.net ..., lastnik 5. 11. 2026) - Scit ga zavrne za ves racunalnik, tudi za namizne programe. Ostalih
    sledilcev tretjih (»sledilci«: analytics.google.com, hotjar.com) DNS ne blokira: tu ni mogoce locit tretje strani od
    obiska njihove strani (to naredi filter WebKit)."""
    try:
        from core import scit_pravila
        p = scit_pravila.trenutna()
        return any(ime == t or ime.endswith("." + t) for t in p.telemetrija + p.oglasni_strezniki)
    except Exception:  # noqa: BLE001
        return False


def je_posodobitev(ime: str) -> bool:
    return any(ime == d or ime.endswith("." + d) for d in POSODOBITVE)


#: Zasciteni gostitelji (s poddomenami): posodobitve, preverjanje cloveka in Safeer. Seznami OGLASOV jih ne ustavijo
#: (zastrupljen ali preobsiren seznam ne sme zapreti popravkov in prijav); seznam GROZENJ jih ustavi vedno - tudi
#: Safeerjeva stran ali zrcalo, ki ga nekdo prevzame (lastnik 4. 11. 2026; prej so bili spuscani tudi kot groznja).
ZASCITENI = POSODOBITVE + PREVERJANJE + ("safeer.si",)


def _sme_oglas(domena: str) -> bool:
    """Vnos seznama oglasov sme veljati za skupni gostitelj, ne pa za koren ali celotno domeno (google.com, web.app)."""
    return not scit_gostitelji.je_celotna_domena(domena) and scit_gostitelji.vrsta(domena) != scit_gostitelji.KOREN


def je_zasciten(ime: str) -> bool:
    return any(ime == d or ime.endswith("." + d) for d in ZASCITENI)


def _zazeni(ukaz: List[str], cas: float = 8.0) -> Tuple[int, str]:
    if not ukaz or shutil.which(ukaz[0]) is None:
        return 127, ""
    try:
        r = subprocess.run(ukaz, capture_output=True, text=True, timeout=cas)
        return r.returncode, r.stdout
    except Exception:
        return 1, ""


def _zazeni_z_vhodom(ukaz: List[str], vhod: str, cas: float = 8.0) -> Tuple[int, str]:
    """Kot _zazeni, z besedilom na standardnem vhodu (npr. vsebina, ki jo root zapise brez vmesne datoteke)."""
    if not ukaz or shutil.which(ukaz[0]) is None:
        return 127, ""
    try:
        r = subprocess.run(ukaz, input=vhod, capture_output=True, text=True, timeout=cas)
        return r.returncode, r.stdout
    except Exception:
        return 1, ""


def podatkovna_mapa() -> str:
    try:
        from core.threat_intel import default_data_dir
        return os.path.join(str(default_data_dir("safeer-mint")), "scit")
    except Exception:
        return os.path.join((os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")), "safeer-mint", "scit")


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


def _ime_odgovora(d: bytes, i: int) -> Optional[Tuple[str, int]]:
    """Ime v odsekih odgovorov s stiskanjem (RFC 1035 4.1.4): kazalec samo nazaj, najvec 16 skokov, najvec 255 znakov.
    Vrne (ime, odmik za imenom na mestu) ali None za pokvarjeno sporocilo (isto kot TV DnsPaket.preberiImeOdgovora)."""
    deli: List[str] = []
    dolzina = 0
    konec = -1
    skokov = 0
    while True:
        if i < 0 or i >= len(d):
            return None
        n = d[i]
        if n == 0:
            if konec < 0:
                konec = i + 1
            break
        if n & 0xC0 == 0xC0:
            if i + 1 >= len(d):
                return None
            cilj = ((n & 0x3F) << 8) | d[i + 1]
            if konec < 0:
                konec = i + 2
            skokov += 1
            if cilj >= i or skokov > 16:
                return None
            i = cilj
            continue
        if n & 0xC0 or i + 1 + n > len(d) or dolzina + n + 1 > 255:
            return None
        deli.append(d[i + 1:i + 1 + n].decode("latin-1"))
        dolzina += n + 1
        i += 1 + n
    return ".".join(deli).lower(), konec


def cname_cilji(d: bytes) -> List[str]:
    """Cilji zapisov CNAME v odgovoru DNS (najvec 64 zapisov). Lastnik 9. 11. 2026: Scit kot Pi-hole preveri verigo
    CNAME - sledilec, skrit pod poddomeno strani (stat.stran.si CNAME sledilec.net), se ustavi, ce je cilj na seznamu."""
    if len(d) < 12:
        return []
    qd, an = struct.unpack("!HH", d[4:8])
    i = 12
    # Neodvisni pregled 9. 11. 2026: pravi razresevalniki posljejo eno vprasanje; QDCOUNT 0xFFFF s kazalci je stal ~0,45 s.
    for _ in range(min(qd, 4)):
        r = _ime_odgovora(d, i)
        if r is None:
            return []
        i = r[1] + 4
    izhod: List[str] = []
    for _ in range(min(an, 64)):
        r = _ime_odgovora(d, i)
        if r is None or r[1] + 10 > len(d):
            return izhod
        k = r[1]
        vrsta, rdl = struct.unpack("!H", d[k:k + 2])[0], struct.unpack("!H", d[k + 8:k + 10])[0]
        if k + 10 + rdl > len(d):
            return izhod
        if vrsta == 5:
            c = _ime_odgovora(d, k + 10)
            if c is not None:
                izhod.append(c[0])
        i = k + 10 + rdl
    return izhod


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


def _vrednosti_nmcli(izpis: str) -> List[str]:
    """Vrednosti iz `nmcli -g`: vec vrednosti istega polja loci » | «, dvopicja naslovov IPv6 so ubezana (\\:)."""
    return [v.strip().replace("\\:", ":") for v in izpis.replace("|", "\n").splitlines() if v.strip()]


def upstream_strezniki(vmesnik: str) -> List[str]:
    """Strezniki DNS, ki jih je za ta vmesnik dolocil NetworkManager (DHCP, oglas usmerjevalnika ali rocna
    nastavitev), IPv4 in IPv6 - ne glede na to, kaj je trenutno nastavljeno v systemd-resolved."""
    if sys.platform == "win32":
        return _windows().upstream_strezniki(vmesnik)
    koda, izpis = _zazeni(["nmcli", "-g", "IP4.DNS,IP6.DNS", "device", "show", vmesnik])
    strezniki: List[str] = []
    for v in _vrednosti_nmcli(izpis) if koda == 0 else []:
        try:
            naslov = ipaddress.ip_address(v)
        except ValueError:
            continue
        if not naslov.is_loopback and not naslov.is_unspecified and v not in strezniki:
            strezniki.append(v)
    if not strezniki and koda == 0:
        # NetworkManager ima za povezavo samo 127.0.0.1 (stara nastavitev »ipv4.dns 127.0.0.1« z ignore-auto-dns): brez
        # tega bi Scit po ponovnem zagonu odgovarjal samo SERVFAIL (17. 11. 2026: ves racunalnik brez DNS). DNS, ki ga je
        # usmerjevalnik res ponudil prek DHCP, je isti »DNS usmerjevalnika«, ki ga Scit sicer privzeto uporablja.
        strezniki = _dhcp_strezniki(vmesnik)
    return strezniki


def _dhcp_strezniki(vmesnik: str) -> List[str]:
    """Strezniki DNS iz ponudbe DHCP (DHCP4.OPTION domain_name_servers), brez povratne zanke in dvojnikov."""
    koda, izpis = _zazeni(["nmcli", "-g", "DHCP4.OPTION", "device", "show", vmesnik])
    rezultat: List[str] = []
    if koda != 0:
        return rezultat
    for vrstica in izpis.replace("|", "\n").splitlines():
        ime, _, vrednost = vrstica.partition("=")
        if ime.strip() != "domain_name_servers":
            continue
        for v in vrednost.split():
            try:
                naslov = ipaddress.ip_address(v)
            except ValueError:
                continue
            if naslov.version == 4 and not naslov.is_loopback and not naslov.is_unspecified and v not in rezultat:
                rezultat.append(v)
    return rezultat


def za_vticnico(streznik: str, vmesnik: str) -> str:
    """Naslov za nase posredovanje: povezavno-lokalni IPv6 (fe80::) potrebuje se ime vmesnika."""
    if sys.platform == "win32":
        return streznik
    try:
        if ":" in streznik and ipaddress.ip_address(streznik).is_link_local:
            return streznik + "%" + vmesnik
    except ValueError:
        pass
    return streznik


def nm_domene(vmesnik: str) -> List[str]:
    """Iskalne domene, ki jih je za vmesnik dolocil NetworkManager (iz DHCP ali nastavitev povezave)."""
    if sys.platform == "win32":
        return []
    koda, izpis = _zazeni(["nmcli", "-g", "IP4.DOMAIN,IP6.DOMAIN,IP4.SEARCHES,IP6.SEARCHES", "device", "show", vmesnik])
    if koda != 0:     # starejsi NetworkManager polja SEARCHES ne pozna
        koda, izpis = _zazeni(["nmcli", "-g", "IP4.DOMAIN,IP6.DOMAIN", "device", "show", vmesnik])
    domene: List[str] = []
    for v in _vrednosti_nmcli(izpis) if koda == 0 else []:
        # Brez vezaja na zacetku (po morebitni »~«): sicer bi »--help« iz DHCP prisel v argv resolvectl kot moznost (N8).
        if re.fullmatch(r"~?[A-Za-z0-9._][A-Za-z0-9._-]{0,252}", v) and v not in domene:
            domene.append(v)
    return domene


#: Kanarcek Firefoxa: odgovor NXDOMAIN pomeni »omrezje filtrira DNS, ne vklapljaj DoH sam«.
class Razresevalnik:
    """Razresevalnik DNS (UDP in TCP) na 127.0.0.1: blokirana imena zavrne, ostala posreduje."""

    def __init__(self, blokiraj: Callable[[str], Optional[str]], upstream: Callable[[], List[str]],
                 naprej: Optional[Callable[[bytes], Optional[bytes]]] = None,
                 zagonsko: Optional[Callable[[str], bool]] = None,
                 izjema: Optional[Callable[[str], bool]] = None,
                 ip_groznje: Optional[Callable[[str], bool]] = None) -> None:
        self.blokiraj = blokiraj
        #: Ali je naslov IPv4 na seznamu groznj z naslovi (Feodo): odgovor z njim se zavrne (blokada po IP odgovora).
        self.ip_groznje = ip_groznje
        #: Uporabnikova izjema na vprasanem imenu velja tudi za njegovo verigo CNAME (kot Pi-hole).
        self.izjema = izjema
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
    #: Rok za telo poizvedbe TCP (najvec 65535 bajtov, krajevni odjemalec ga poslje naenkrat). Prej 10 s: odjemalec,
    #: ki poslje samo dolzino, je drzal mesto ~12 s in 32 takih je utisalo TCP Scita (CodeRabbit, 5. 11. 2026).
    ROK_TELESA_TCP_S = 2.0

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
        odgovor = self._posreduj(paket, tcp)
        if odgovor and ime and (self._cname_ustavi(ime, odgovor) or self._ip_ustavi(ime, odgovor)):
            return odgovor_zavrnjeno(paket)
        return odgovor

    def _ip_ustavi(self, ime: str, odgovor: bytes) -> bool:
        """Odgovor vsebuje naslov IPv4 botnet C2 (Feodo): ime menja naslove, naslov pa je na seznamu. Ne ustavi imena z
        uporabnikovo izjemo, krajevnega, zascitenega in korena skupnega gostitelja (isto kot TV ScitOdlocitev.ipUstavi);
        zabelezi se ime, da ga uporabnik lahko spusti."""
        if self.ip_groznje is None:
            return False
        try:
            d = ime.lower().rstrip(".")
            if (not d or (self.izjema is not None and self.izjema(d)) or je_krajevno(d) or je_zasciten(d)
                    or scit_gostitelji.vrsta(d) == scit_gostitelji.KOREN):
                return False
            if not any(self.ip_groznje(a) for a in naslovi4(odgovor)):
                return False
        except Exception:  # noqa: BLE001 - pokvarjen odgovor gre naprej kot doslej
            return False
        with self._kljuc:
            self.blokiranih += 1
            if not self.zadnje or self.zadnje[0]["ime"] != d:
                self.zadnje = ([{"ime": d, "kategorija": "botnet", "cas": time.time()}] + self.zadnje)[:20]
        return True

    def _cname_ustavi(self, ime: str, odgovor: bytes) -> bool:
        """Odgovor vsebuje CNAME na ustavljeno domeno (prikrit sledilec; lastnik 9. 11. 2026, Scit kot Pi-hole).
        Neodvisni pregled 9. 11.: cilj s seznama GROZENJ ustavi vedno (tudi ob izjemi ali zascitenem imenu) in zabelezi se
        cilj (ta nima izjeme); oglasni cilj ustavi samo ime brez izjeme, ki ni zasciteno, krajevno ali Googlov koren -
        zabelezi se ime, da ga uporabnik lahko spusti (isto kot TV ScitOdlocitev.cnameUstavi)."""
        try:
            cilji = cname_cilji(odgovor)
            if not cilji:
                return False
            ocene = [(c, self.blokiraj(c)) for c in cilji]
            zabelezi = next(((c, k) for c, k in ocene if k and k != KATEGORIJA_PREMORA), None)
            if zabelezi is None:
                oglas = next((k for _c, k in ocene if k), None)
                d = ime.lower().rstrip(".")
                if (not oglas or (self.izjema is not None and self.izjema(d)) or je_krajevno(d) or je_zasciten(d)
                        or scit_gostitelji.vrsta(d) == scit_gostitelji.KOREN):
                    return False
                zabelezi = (d, oglas)
        except Exception:  # noqa: BLE001 - pokvarjen odgovor gre naprej kot doslej
            return False
        with self._kljuc:
            self.blokiranih += 1
            if not self.zadnje or self.zadnje[0]["ime"] != zabelezi[0]:
                self.zadnje = ([{"ime": zabelezi[0], "kategorija": zabelezi[1], "cas": time.time()}] + self.zadnje)[:20]
        return True

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
        if not tcp:
            return self._usmerjevalnik_udp(paket, strezniki) or odgovor_napaka(paket)
        # TCP (velik odgovor po TC): po vrsti, a v skupnem roku CAS_UPSTREAM; nato SERVFAIL, ne molk.
        konec = time.monotonic() + CAS_UPSTREAM
        for streznik in strezniki:
            ostane = konec - time.monotonic()
            if ostane <= 0:
                break
            try:
                with socket.create_connection((streznik, 53), timeout=ostane) as s:
                    s.sendall(struct.pack("!H", len(paket)) + paket)
                    # CodeRabbit 5. 11. 2026: rok vsakega branja je ostanek skupnega roka, ne nov poln rok.
                    glava = self._preberi(s, 2, konec)
                    odgovor = self._preberi(s, struct.unpack("!H", glava)[0], konec)
                if odgovor[:2] == paket[:2]:
                    return odgovor
            except (OSError, struct.error):
                continue
        return odgovor_napaka(paket)

    @staticmethod
    def _usmerjevalnik_udp(paket: bytes, strezniki: List[str]) -> Optional[bytes]:
        """Vse streznike vprasa hkrati (brez niti: ena vticnica na streznik in select), prvi pravi odgovor zmaga.
        Vticnica je povezana (connect): jedro sprejme samo odgovor s tega naslova in vrat, tuj paket ne pride do nas."""
        import selectors
        vticnice = []
        izbira = selectors.DefaultSelector()
        try:
            for streznik in strezniki:
                try:
                    druzina = socket.AF_INET6 if ":" in streznik else socket.AF_INET
                    cilj = socket.getaddrinfo(streznik, 53, druzina, socket.SOCK_DGRAM, 0, socket.AI_NUMERICHOST)[0][4]
                    s = socket.socket(druzina, socket.SOCK_DGRAM)
                    vticnice.append(s)
                    s.setblocking(False)
                    s.connect(cilj)
                    s.send(paket)
                    izbira.register(s, selectors.EVENT_READ)
                except (OSError, IndexError, ValueError):
                    continue
            konec = time.monotonic() + ROK_USMERJEVALNIK
            while izbira.get_map():
                ostane = konec - time.monotonic()
                if ostane <= 0:
                    break
                for kljuc, _ in izbira.select(ostane):
                    try:
                        odgovor = kljuc.fileobj.recv(4096)
                    except BlockingIOError:
                        continue
                    except OSError:
                        izbira.unregister(kljuc.fileobj)     # ICMP »vrata zaprta«: ta streznik je mrtev
                        continue
                    if odgovor[:2] == paket[:2]:
                        return odgovor
            return None
        finally:
            izbira.close()
            for s in vticnice:
                s.close()

    @staticmethod
    def _preberi(s: socket.socket, n: int, konec: Optional[float] = None) -> bytes:
        """Natanko n bajtov; s `konec` (time.monotonic) je to skupni rok vseh branj - streznik, ki telo posilja po
        kosih, ga ne podaljsa (vsak recv bi sicer dobil poln rok vticnice znova)."""
        b = b""
        while len(b) < n:
            if konec is not None:
                ostane = konec - time.monotonic()
                if ostane <= 0:
                    raise socket.timeout("rok potekel")
                s.settimeout(ostane)
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
                    # Glava in telo vsak v svojem skupnem roku: odjemalec po bajtih ne zadrzi niti dlje (5. 11. 2026).
                    n = struct.unpack("!H", self._preberi(s, 2, time.monotonic() + self.ROK_GLAVE_TCP_S))[0]
                    odgovor = self._odgovori(self._preberi(s, n, time.monotonic() + self.ROK_TELESA_TCP_S), True)
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


# ---------------------------------------------------------------------- nabor domen
def _zgoscenka(ime: str) -> int:
    return int.from_bytes(hashlib.blake2b(ime.encode("utf-8", "replace"), digest_size=8).digest(), "big")


#: Seznami v obliki AdGuard/ABP (||ime^, izjeme @@); v drugih seznamih vrstica »||« ni ime (test_razcleni_seznam).
SEZNAMI_ABP = ("adguard-dns",)


#: Kljuc abuse.ch v sistemski zbirki skrivnosti (core/sporocila/skrivnosti.py; nikoli v datoteki ali dnevniku).
SKRIVNOST_ABUSECH = "scit_abusech"


def veljaven_kljuc(k: str) -> bool:
    """Kljuc abuse.ch: crke in stevke, 20-128 znakov - samo tako gre varno v pot naslova (isto kot TV AbuseChPravila)."""
    return 20 <= len(k) <= 128 and all(c.isascii() and c.isalnum() for c in k)


def ocisti_kljuc(vnos: str) -> str:
    """Prilepljen vnos: presledki, narekovaji in nevidni znaki stran."""
    return "".join(c for c in vnos if not c.isspace() and c not in "\"'\u200b")


def abusech_kljuc() -> Optional[str]:
    try:
        from core.sporocila import skrivnosti
        k = skrivnosti.preberi(SKRIVNOST_ABUSECH)
    except Exception:  # noqa: BLE001
        return None
    return k if k and veljaven_kljuc(k) else None


class _PreusmeritevSamoNaIstiHttps(urllib.request.HTTPRedirectHandler):
    """Preusmeritev samo na https istega gostitelja; vse drugo je napaka PRED zahtevo (neodvisni pregled 12. 11. 2026:
    urlopen je sledil preusmeritvi na http://127.0.0.1, http://192.168.x.x ... in sele nato preveril naslov)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith("https://") or not isti_gostitelj(req.full_url, newurl):
            raise urllib.error.HTTPError(req.full_url, code, "preusmeritev ni dovoljena", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _BrezPreusmeritev(urllib.request.HTTPRedirectHandler):
    """Zahteva s kljucem ne sledi preusmeritvam (AGENTS.md, pravila iz napak izdaje 1.0.127)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "preusmeritev ni dovoljena", headers, fp)


def preveri_kljuc(kljuc: str) -> str:
    """Preverba pri abuse.ch: 'velja', 'neveljaven', 'oblika' ali 'ni_odgovora'. Kljuc ne gre v dnevnik."""
    if not veljaven_kljuc(kljuc):
        return "oblika"
    z = urllib.request.Request(VIRI_URLHAUS.replace("{KLJUC}", kljuc), headers={"User-Agent": "Safeer"})
    try:
        with urllib.request.build_opener(_BrezPreusmeritev()).open(z, timeout=15) as o:  # noqa: S310 - fiksen naslov https
            return "velja" if o.status == 200 else "ni_odgovora"
    except urllib.error.HTTPError as e:
        return "neveljaven" if e.code in (401, 403) else "ni_odgovora"
    except Exception:  # noqa: BLE001
        return "ni_odgovora"


# ---------------------------------------------------------------------- filtri po meri (lastnik 9. 11. 2026)
#: Kot AdGuard »Dodaj filter po meri«: uporabnik doda naslov javnega seznama domen; gre samo v nabor Scita (oglasi).
NAJVEC_PO_MERI = 20


def napaka_naslova(url: str) -> Optional[str]:
    """Razlog, zakaj naslov filtra ni sprejemljiv, ali None (isto kot TV ScitPoMeriPravila.napaka)."""
    u = (url or "").strip()
    if not 12 <= len(u) <= 2000:
        return "dolzina"
    if not u.startswith("https://"):
        return "https"
    if any(c.isspace() or not 0x21 <= ord(c) <= 0x7E or c in "{}" for c in u):
        return "znaki"             # { } zavrnjeni: {KLJUC} je samo za vgrajeni vir (12. 11. 2026, neodvisni pregled)
    gostitelj = u[8:].split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if "@" in gostitelj or not gostitelj or "." not in gostitelj:
        return "gostitelj"
    return None


def id_po_meri(url: str) -> str:
    return "pm-" + hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:12]


def ime_po_meri(url: str) -> str:
    brez = url.strip()[8:]
    gostitelj = brez.split("/", 1)[0]
    datoteka = brez.split("?", 1)[0].rsplit("/", 1)[-1] if "/" in brez else ""
    return gostitelj if not datoteka or datoteka == gostitelj else "%s … %s" % (gostitelj, datoteka)


def po_meri(mapa: str) -> List[dict]:
    """Filtri po meri iz <mapa>/po-meri.json: [{"url", "vklop"}], samo veljavni, najvec NAJVEC_PO_MERI."""
    try:
        with open(os.path.join(mapa, "po-meri.json"), encoding="utf-8") as f:
            podatki = json.load(f)
    except (OSError, ValueError):
        return []
    izid, videni = [], set()
    for x in podatki if isinstance(podatki, list) else []:
        url = x.get("url") if isinstance(x, dict) else None
        if isinstance(url, str) and napaka_naslova(url) is None and id_po_meri(url) not in videni:
            videni.add(id_po_meri(url))
            izid.append({"url": url.strip(), "vklop": bool(x.get("vklop", True))})
    return izid[:NAJVEC_PO_MERI]


def zapisi_po_meri(mapa: str, filtri: List[dict]) -> None:
    os.makedirs(mapa, exist_ok=True)
    _atomic_write(Path(mapa, "po-meri.json"), json.dumps(filtri[:NAJVEC_PO_MERI]).encode("utf-8"))


def razcleni_seznam(besedilo: str, abp: bool = False) -> List[str]:
    """Domene iz seznama v obliki hosts (0.0.0.0 ime), RPZ (ime CNAME .), golih domen ali AdGuard/ABP (||ime^);
    komentarji stran. Lastnik 9. 11. 2026 (AdGuard DNS filter): izjema »@@||ime^« izpusti ime in nadrejene domene iz
    ISTEGA seznama (nabor je »wildcard«); tocne izjeme »@@|ime^« ostanejo blokirane (isto kot TV PlainListParser)."""
    imena: List[str] = []
    izjeme = set()
    for v in besedilo.splitlines():
        v = v.strip()
        if abp and v.startswith("@@||"):
            e = v[4:].split("^", 1)[0].split("$", 1)[0].lower().rstrip(".")
            if "." in e and re.fullmatch(r"[a-z0-9._-]{3,253}", e):
                izjeme.add(e)
            continue
        if not v or v[0] in "#!;$@[":
            continue
        if abp and v.startswith("||"):
            if not re.fullmatch(r"\|\|[A-Za-z0-9._-]+\^", v):
                continue                    # vzorci (*), modifikatorji ($important) in poti niso ime
            v = v[2:-1]
        deli = v.split()
        ime = deli[0]
        if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}|::1?|0\.0\.0\.0", ime):
            if len(deli) < 2:
                continue
            ime = deli[1]
        ime = ime.lower().rstrip(".").lstrip("*.")
        if "." not in ime or not re.fullmatch(r"[a-z0-9._-]{3,253}", ime):
            continue
        # Neodvisni pregled 9. 11. 2026: glava StevenBlack ima »0.0.0.0 0.0.0.0« - naslov ni ime (kot TV isHostName).
        if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", ime):
            continue
        if ime in ("localhost", "localhost.localdomain", "broadcasthost"):
            continue
        imena.append(ime)
    if izjeme:
        izpusti = set()
        for e in izjeme:
            d = e
            while True:
                izpusti.add(d)
                if "." not in d:
                    break
                d = d.split(".", 1)[1]
        imena = [i for i in imena if i not in izpusti]
    return imena


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

    def kategorija(self, ime: str, sme=None) -> Optional[str]:
        """[sme] (domena -> bool): samo vnosi za domene, ki jih Scit sme blokirati (core/scit_gostitelji.py)."""
        deli = ime.split(".")
        for i in range(len(deli) - 1):
            if sme is not None and not sme(".".join(deli[i:])):
                continue
            z = _zgoscenka(".".join(deli[i:]))
            j = bisect.bisect_left(self.zgoscenke, z)
            if j < len(self.zgoscenke) and self.zgoscenke[j] == z:
                return KATEGORIJE[self.kategorije[j]]
        return None

    def vse_kategorije(self, ime: str, sme=None) -> List[str]:
        """Kategorije imena in vseh nadrejenih domen (kategorija() vrne samo najbolj natancno ujemanje)."""
        izid = []
        deli = ime.split(".")
        for i in range(len(deli) - 1):
            if sme is not None and not sme(".".join(deli[i:])):
                continue
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
    return _prenesi(url, etag, cas, _PreusmeritevSamoNaIstiHttps())


def prenesi_s_kljucem(url: str, etag: str, cas: float = 60.0) -> Tuple[int, bytes, str]:
    """Kot prenesi, vendar brez sledenja preusmeritvam: naslov vsebuje uporabnikov kljuc (AGENTS.md, Omrezje s kljucem;
    neodvisni pregled 13. 11. 2026, najdba 4). Preusmeritev je napaka seznama, ne sledenje."""
    return _prenesi(url, etag, cas, _BrezPreusmeritev())


def _prenesi(url: str, etag: str, cas: float, preusmeritve: urllib.request.HTTPRedirectHandler) -> Tuple[int, bytes, str]:
    z = urllib.request.Request(url, headers={"User-Agent": "Safeer", "Accept": "text/plain"})
    if etag:
        z.add_header("If-None-Match", etag)
    try:
        with urllib.request.build_opener(preusmeritve).open(z, timeout=cas) as o:  # noqa: S310
            if not o.geturl().lower().startswith("https://") or not isti_gostitelj(url, o.geturl()):
                return 0, b"", etag  # preusmeritev drugam: seznama ne vzamemo, ostane prejsnji
            return o.status, o.read(NAJVEC_BAJTOV + 1), o.headers.get("ETag", "") or ""
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return 304, b"", etag
        if 300 <= e.code < 400:
            return 0, b"", etag  # prepovedana preusmeritev: seznama ne vzamemo, ostane prejsnji
        raise


class Seznami:
    """Seznami domen na disku (kot ThreatFeedsUpdater na televizorju) + Safeerjev podpisani seznam groznj."""

    def viri(self) -> List[Tuple[str, str, str]]:
        """Vgrajeni seznami in vklopljeni filtri po meri (oglasi; lastnik 9. 11. 2026)."""
        return list(VIRI) + [(id_po_meri(f["url"]), f["url"], "oglasi") for f in po_meri(self.mapa) if f["vklop"]]

    def dodaj_po_meri(self, url: str) -> str:
        """Prenese in preveri seznam (HTTPS, ne HTML, vsaj eno ime), nato ga doda. 'dodan', 'naslov', 'ni_seznam',
        'ze_dodan' ali 'polno'. Klic iz niti mostu (omrezje)."""
        url = (url or "").strip()
        if napaka_naslova(url):
            return "naslov"
        filtri = po_meri(self.mapa)
        if any(id_po_meri(f["url"]) == id_po_meri(url) for f in filtri):
            return "ze_dodan"
        if len(filtri) >= NAJVEC_PO_MERI:
            return "polno"
        try:
            koda, telo, _etag = self.prenesi(url, "")
        except Exception:  # noqa: BLE001
            return "ni_seznam"
        glava = telo[:2048].decode("utf-8", "replace").lower() if telo else ""
        if koda != 200 or not telo or len(telo) > NAJVEC_BAJTOV or "<html" in glava or "<!doctype" in glava:
            return "ni_seznam"
        if not razcleni_seznam(telo.decode("utf-8", "replace"), abp=True):
            return "ni_seznam"
        # CodeRabbit 9. 11. 2026: po prenosu (lahko traja) seznam znova preberemo pod zaklepom - hkratna sprememba ostane.
        with self._po_meri_kljuc:
            filtri = po_meri(self.mapa)
            if any(id_po_meri(f["url"]) == id_po_meri(url) for f in filtri):
                return "ze_dodan"
            if len(filtri) >= NAJVEC_PO_MERI:
                return "polno"
            zapisi_po_meri(self.mapa, filtri + [{"url": url, "vklop": True}])
        threading.Thread(target=self.osvezi, name="safeer-scit-po-meri", daemon=True).start()
        return "dodan"

    def nastavi_po_meri(self, ident: str, vklop: Optional[bool]) -> None:
        """vklop True/False preklopi, None odstrani; nabor se zgradi znova (brez prenosa izklopljenih)."""
        with self._po_meri_kljuc:
            filtri = po_meri(self.mapa)
            if vklop is None:
                filtri = [f for f in filtri if id_po_meri(f["url"]) != ident]
            else:
                filtri = [dict(f, vklop=bool(vklop)) if id_po_meri(f["url"]) == ident else f for f in filtri]
            zapisi_po_meri(self.mapa, filtri)
        threading.Thread(target=self.osvezi_in_zgradi, name="safeer-scit-po-meri", daemon=True).start()

    def __init__(self, mapa: str, prenesi_fn=prenesi, kljuc_fn=abusech_kljuc) -> None:
        self.mapa = mapa
        self.prenesi = prenesi_fn
        self.kljuc_fn = kljuc_fn
        self.nabor: Nabor = Nabor.nalozi(os.path.join(mapa, "domene.bin")) or Nabor()
        self.meta: dict = self._preberi_meta()
        self.napaka = ""
        #: Naslovi IPv4 groznj (Feodo) za blokado po IP odgovora; z diska, osvezi jih _osvezi_ip.
        self.ip_nabor: frozenset = self._preberi_ip()
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

    #: Branje in zapis filtrov po meri skupaj (CodeRabbit 9. 11. 2026).
    _po_meri_kljuc = threading.Lock()

    #: Ena osvezitev naenkrat (lastnik 9. 11. 2026: filter po meri sprozi osvezitev iz svoje niti, poleg redne zanke).
    _osvezi_kljuc = threading.Lock()

    def osvezi(self) -> bool:
        """Prenese spremenjene sezname in na novo zgradi nabor; ob napaki ostane prejsnji."""
        with self._osvezi_kljuc:
            return self._osvezi()

    def osvezi_in_zgradi(self) -> None:
        with self._osvezi_kljuc:
            try:
                self._osvezi()
            finally:
                self._zgradi()

    def _osvezi(self) -> bool:
        os.makedirs(self.mapa, exist_ok=True)
        spremenjeno, napake = False, []
        for oznaka, url, _kat in self.viri():
            m = self.meta.get(oznaka, {})
            if oznaka == "urlhaus" and "{KLJUC}" in url:   # samo vgrajeni vir; filter po meri ne dobi kljuca abuse.ch
                kljuc = self.kljuc_fn()
                if not kljuc or not veljaven_kljuc(kljuc):
                    continue            # brez kljuca uporabnika: zadnja kopija ostane, ni napaka
                url = url.replace("{KLJUC}", kljuc)
                prenos = prenesi_s_kljucem if self.prenesi is prenesi else self.prenesi   # preizkusi podtaknejo svoj prenos
            else:
                prenos = self.prenesi
            try:
                koda, telo, etag = prenos(url, m.get("etag", ""))
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
            domen = len(set(razcleni_seznam(telo.decode("utf-8", "replace"), abp=oznaka in SEZNAMI_ABP or oznaka.startswith("pm-"))))
            if domen < (NAJMANJ_DOMEN if oznaka.startswith("hagezi") or oznaka in ("stevenblack", "adguard-dns") else 1):
                napake.append("%s: %d domen" % (oznaka, domen))
                continue
            _atomic_write(Path(self.mapa, oznaka + ".txt"), telo)
            self.meta[oznaka] = {"etag": etag, "cas": time.time(), "domen": domen}
            spremenjeno = True
        if spremenjeno or not len(self.nabor):
            self._zgradi()
        try:
            self._osvezi_ip(napake)
        except Exception as e:  # noqa: BLE001 - seznam IP ne sme zrusiti osvezitve domen
            napake.append("ip: %s" % e.__class__.__name__)
        self.meta["cas"] = time.time()
        self.napaka = "; ".join(napake)
        self.meta["napaka"] = self.napaka
        try:
            self._zapisi_meta()
        except OSError:
            pass
        return not napake

    def _preberi_ip(self) -> frozenset:
        vsi = set()
        for oznaka, _url in VIRI_IP:
            try:
                pot = os.path.join(self.mapa, oznaka + ".ip.txt")
                if os.path.getsize(pot) > NAJVEC_BAJTOV_IP:
                    continue
                with open(pot, encoding="utf-8", errors="replace") as f:
                    vsi |= razcleni_ip_seznam(f.read())
            except OSError:
                continue
        return frozenset(vsi)

    def _osvezi_ip(self, napake: List[str]) -> bool:
        """Prenese sezname naslovov IPv4; ob napaki ostane zadnja kopija."""
        spremenjeno = False
        for oznaka, url in VIRI_IP:
            kljuc = "ip-" + oznaka
            m = self.meta.get(kljuc, {})
            try:
                koda, telo, etag = self.prenesi(url, m.get("etag", ""))
            except Exception as e:  # noqa: BLE001
                napake.append("%s: %s" % (oznaka, e.__class__.__name__))
                continue
            if koda == 304 and os.path.exists(os.path.join(self.mapa, oznaka + ".ip.txt")):
                continue
            if koda != 200 or len(telo) > NAJVEC_BAJTOV_IP:
                napake.append("%s: %s" % (oznaka, koda))
                continue
            glava = telo[:2048].decode("utf-8", "replace").lower()
            if "<html" in glava or "<!doctype" in glava:
                napake.append("%s: html" % oznaka)
                continue
            _atomic_write(Path(self.mapa, oznaka + ".ip.txt"), telo)
            self.meta[kljuc] = {"etag": etag, "cas": time.time()}
            spremenjeno = True
        if spremenjeno:
            self.ip_nabor = self._preberi_ip()
        return spremenjeno

    def ip_groznje(self, naslov: str) -> bool:
        return naslov in self.ip_nabor

    def _zgradi(self) -> None:
        def domene():
            for oznaka, _url, kat in self.viri():
                try:
                    with open(os.path.join(self.mapa, oznaka + ".txt"), encoding="utf-8", errors="replace") as f:
                        besedilo = f.read()
                except OSError:
                    continue
                for ime in razcleni_seznam(besedilo, abp=oznaka in SEZNAMI_ABP or oznaka.startswith("pm-")):
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
        # DNS pozna samo ime, ne poti (5. 11. 2026): koren Googla (iskanje, prijava) nikoli; na skupnem gostitelju z
        # uporabnisko vsebino (sites.google.com, storage.googleapis.com) noben vnos GROZNJE - en vnos bi vzel vso
        # platformo; vnos za celotno domeno (google.com, web.app) ne velja za gostitelje pod njo.
        vrsta = scit_gostitelji.vrsta(ime)
        if vrsta == scit_gostitelji.KOREN:
            return None
        if je_zasciten(ime):
            return self.kategorija_groznje(ime)     # oglasi ne, groznja vedno (4. 11. 2026)
        with self._kljuc:
            k = self.nabor.kategorija(ime, scit_gostitelji.sme_gostitelj)
            if not k and vrsta == scit_gostitelji.VSEBINA:
                # Izrecen gostitelj OGLASOV pod skupno infrastrukturo ostane blokiran (hagezi-pro 5. 11. 2026: 5 imen,
                # npr. afs.googleusercontent.com, displayads-formats.googleusercontent.com); groznja tu ne velja.
                oglas = self.nabor.kategorija(ime, _sme_oglas)
                k = oglas if oglas == KATEGORIJA_PREMORA else None
        if k:
            return k
        if _je_telemetrija(ime):
            return KATEGORIJA_PREMORA       # telemetrija storitev s podpisanega seznama Scita (premor jo spusti)
        s = self.storitev
        if s is not None and s.loaded.is_set():
            try:
                k = s.store.match_host(ime, scit_gostitelji.sme_gostitelj)
            except Exception as e:  # noqa: BLE001 - poskodovan seznam: brskanje ne zastane, seznam se popravi (13. 11. 2026)
                k = None
                s.popravi(e.__class__.__name__)
            if k in KATEGORIJA_SEZNAMA_GROZNJ:
                return KATEGORIJA_SEZNAMA_GROZNJ[k]
        return None

    def kategorija_groznje(self, ime: str) -> Optional[str]:
        """Kategorija GROZNJE (ne oglasov) imena ali katere nadrejene domene - v naboru ali v podpisanem seznamu
        grozenj; None, ce ni groznja. Koren Googla in skupni gostitelj nikoli (kot kategorija())."""
        if not scit_gostitelji.sme_gostitelj(ime):
            return None
        with self._kljuc:
            for k in self.nabor.vse_kategorije(ime, scit_gostitelji.sme_gostitelj):
                if k != KATEGORIJA_PREMORA:
                    return k
        s = self.storitev
        if s is not None and s.loaded.is_set():
            try:
                k = s.store.match_host(ime, scit_gostitelji.sme_gostitelj)
            except Exception as e:  # noqa: BLE001 - seznam groženj ni berljiv: raje blokirano (fail-closed), popravilo v ozadju
                s.popravi(e.__class__.__name__)
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
              "seznami": {o: int(self.meta.get(o, {}).get("domen", 0) or 0) for o, _u, _k in self.viri()},
              "poMeri": [{"id": id_po_meri(f["url"]), "url": f["url"], "ime": ime_po_meri(f["url"]), "vklop": f["vklop"],
                          "domen": int(self.meta.get(id_po_meri(f["url"]), {}).get("domen", 0) or 0)} for f in po_meri(self.mapa)]}
        if self.storitev is not None:
            try:
                st["pravil"] = int(self.storitev.status().get("rules") or 0)
            except Exception:
                st["pravil"] = 0
        return st


_skupni: Optional[Seznami] = None
_skupni_kljuc = threading.Lock()


def skupni_seznami(zazeni: bool = True) -> Seznami:
    """Seznami v obicajni mapi, eni za proces: Scit in brskalnik (izbira DNS »Safeer Scit«) delita isti nabor in en
    prenos (ne podvajamo seznamov). zazeni=False samo prebere nabor z diska (brez prenosov)."""
    global _skupni
    with _skupni_kljuc:
        if _skupni is None:
            _skupni = Seznami(podatkovna_mapa())
        if zazeni:
            _skupni.zazeni("brskalnik")
        return _skupni


def tekoci_scit(cas: float = 0.3) -> int:
    """Vrata Scita NASEGA uporabnika, ki tece na tem racunalniku, ali 0. Najprej razresevalnik v tem procesu; sicer
    vrata, ki jih drzi samo nas uid (lastniki_vrat) in na katerih odgovori Scit (KANAREK_DOH: NXDOMAIN z istim ID).
    Tujih vrat (drug uporabnik, proces, ki je vrata zasedel prvi) brskalnik ne uporabi: videl bi vsa imena."""
    if _AKTIVNA_VRATA:
        return min(_AKTIVNA_VRATA)
    for vrata in VRATA:
        if vrata_nasa(vrata) and _odgovori_kanarcku(vrata, cas):
            return vrata
    return 0


# ---------------------------------------------------------------------- systemd-resolved
def vmesniki_povezani() -> List[str]:
    if sys.platform == "win32":
        return _windows().vmesniki_povezani()
    koda, izpis = _zazeni(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device"])
    izhod = []
    if koda != 0:
        return izhod
    for v in izpis.splitlines():
        d = v.split(":")
        if len(d) >= 3 and d[1] in ("ethernet", "wifi") and d[2] == "connected":
            izhod.append(d[0])
    return izhod


def programi_uporabljajo_resolved(resolv_conf: str = "/etc/resolv.conf", nsswitch: str = "/etc/nsswitch.conf") -> bool:
    """Ali programi imena res razresujejo prek systemd-resolved: v /etc/resolv.conf je samo njegov posrednik
    (127.0.0.53 ali .54) ali pa je v nsswitch.conf modul »resolve«.

    Kjer ni tako - racunalnik ima svoj streznik DNS (Pi-hole, AdGuard Home, dnsmasq; `DNSStubListener=no`) ali
    resolv.conf pise kdo drug - nasa nastavitev v systemd-resolved ne bi filtrirala nicesar. Se huje: resolved bi v
    resolv.conf zapisal streznik usmerjevalnika in s tem zaobsel uporabnikov lastni filter."""
    for v in (vsebina_gostitelja(nsswitch) or "").splitlines():
        deli = v.split("#", 1)[0].split()
        if deli and deli[0] == "hosts:" and "resolve" in deli[1:]:
            return True
    besedilo = vsebina_gostitelja(resolv_conf)
    if besedilo is None:
        return False
    strezniki = [d[1] for d in (v.split("#", 1)[0].split() for v in besedilo.splitlines()) if len(d) > 1 and d[0] == "nameserver"]
    return bool(strezniki) and all(s in ("127.0.0.53", "127.0.0.54") for s in strezniki)


def vsebina_gostitelja(pot: str) -> Optional[str]:
    """Vsebina sistemske datoteke; None, ce je ni. V peskovniku Flatpak jo preberemo na gostitelju: /etc/resolv.conf je
    tam zrcalo, ki zamuja (in po menjavi simbolne povezave lahko ostane staro), /etc/nsswitch.conf pa pripada
    runtime-u, ne racunalniku."""
    if v_flatpaku():
        koda, izpis = _zazeni(["flatpak-spawn", "--host", "cat", pot])
        return izpis if koda == 0 else None
    try:
        with open(pot, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


#: Ostanki odstranjenega Pi-hole (izmerjeno na prenosniku lastnika 2. 11. 2026) in mapa, kamor jih »Popravi« premakne.
PIHOLE_OSTANKI = ("/etc/systemd/resolved.conf.d/pi-hole.conf",
                  "/etc/systemd/resolved.conf.d/90-pi-hole-disable-stub-listener.conf")
PIHOLE_ODLOZENO = "/etc/systemd/resolved-pihole-odlozeno"
#: Fiksen ukaz za root (brez podatkov iz uporabnikovih datotek, AGENTS.md »Root prek pkexec«).
POPRAVI_PIHOLE_UKAZ = ("mkdir -p " + PIHOLE_ODLOZENO + " && for f in " + " ".join(PIHOLE_OSTANKI) +
                       "; do [ -f \"$f\" ] && mv -f \"$f\" " + PIHOLE_ODLOZENO + "/; done; systemctl restart systemd-resolved")


def razlog_nemoznosti() -> str:
    """'' = Scit lahko dela; 'ni_resolved' = ni systemd-resolved ali NetworkManagerja; 'lastni_dns' = programi
    sprasujejo drug streznik DNS (ne systemd-resolved)."""
    if sys.platform == "win32":
        return _windows().razlog_nemoznosti()
    if shutil.which("resolvectl") is None or shutil.which("nmcli") is None or \
            _zazeni(["systemctl", "is-active", "systemd-resolved"])[1].strip() != "active":
        return "ni_resolved"
    if not programi_uporabljajo_resolved():
        # Lastnik 2. 11. 2026: odstranjen Pi-hole je pustil nastavitve, ki izklopijo stub resolved (DNSStubListener=no) -
        # to ni uporabnikov streznik DNS, ampak ostanek, ki ga gumb »Popravi« pospravi.
        if PIHOLE_OSTANKI and any(vsebina_gostitelja(p) is not None for p in PIHOLE_OSTANKI) and \
                _zazeni(["systemctl", "is-active", "pihole-FTL"])[1].strip() != "active":
            return "pihole_ostanek"
        return "lastni_dns"
    return ""


def dns_vmesnika(vmesnik: str) -> str:
    if sys.platform == "win32":
        return _windows().dns_vmesnika(vmesnik)
    koda, izpis = _zazeni(["resolvectl", "dns", vmesnik])
    return izpis.split(":", 1)[1].strip() if koda == 0 and ":" in izpis else ""


def domene_vmesnika(vmesnik: str) -> List[str]:
    koda, izpis = _zazeni(["resolvectl", "domain", vmesnik])
    return izpis.split(":", 1)[1].split() if koda == 0 and ":" in izpis else []


def uredi_domene(vmesnik: str) -> None:
    """Iskalne domene vmesnika naj bodo taksne, kot jih je dolocil NetworkManager. Razlicice do 0.4.42 so jih
    zamenjale z usmerjevalno domeno »~.« (kratka domaca imena, npr. »nas«, se potem niso razresila), ob izklopu pa z
    `resolvectl revert` pobrisale; kdor posodobi sredi seje, ima na vmesniku se to stanje - tu ga popravimo."""
    if sys.platform == "win32":
        return _windows().uredi_domene(vmesnik)
    trenutne = domene_vmesnika(vmesnik)
    if trenutne and trenutne != ["~."]:
        return
    if pomocnik():
        _pomocnik("domene", vmesnik)          # pomocnik domene NetworkManagerja prebere sam
        return
    zelene = nm_domene(vmesnik)
    if zelene != trenutne:
        _zazeni(NASTAVI + ["domain", vmesnik] + (zelene or [""]), cas=30.0)


#: Klici, ki spreminjajo nastavitve. resolvectl bi brez dovoljenja odprl okno za geslo (zastavice
#: --no-ask-password systemd 255 se ne pozna) - ob zagonu, ob izhodu ali iz straze vsakih 20 s. Zato jih klicemo
#: samo, kadar `pravilo_namesceno()` (polkit vprasan brez interakcije) pove, da smemo.
NASTAVI = ["resolvectl"]


#: To datoteko systemd-resolved zapise na novo ob vsaki spremembi streznikov DNS kateregakoli vmesnika.
RESOLV_UPLINK = "/run/systemd/resolve/resolv.conf"
PREGLED_S = 20.0
UTRIP_S = 2.0


def znak_dns() -> Tuple[int, int]:
    """Casa zadnje spremembe nastavitev DNS: datoteka systemd-resolved in /etc/resolv.conf (0, ce datoteke ni). V
    peskovniku Flatpak prve ni; druga je tam zrcalo gostiteljeve in se ob menjavi omrezja prav tako spremeni."""
    if sys.platform == "win32":
        return _windows().znak_dns()
    def cas(pot: str) -> int:
        try:
            return os.stat(pot).st_mtime_ns
        except OSError:
            return 0
    return cas(RESOLV_UPLINK), cas("/etc/resolv.conf")


def nekdo_poslusa(vrata: int) -> bool:
    """Ali na nasih vratih tece razresevalnik (tega ali drugega prijavljenega uporabnika)."""
    if sys.platform == "win32":
        return _windows().nekdo_poslusa(vrata)
    try:
        with socket.create_connection((NASLOV, vrata), timeout=0.5):
            return True
    except OSError:
        return False


#: Najmanjsi uid prijavljenega cloveka (login.defs UID_MIN); sistemski uporabniki in »nobody« (Flatpak tuje uid-je
#: pokaze kot 65534) Scita nikoli ne poganjajo.
UID_CLOVEKA = 1000
UID_NOBODY = 65534


def _naslov_iz_proc(hex_naslov: str) -> str:
    """Lokalni naslov iz /proc/net/{udp,tcp}[6]: jedro izpise 32-bitne besede v vrstnem redu bajtov gostitelja."""
    import sys
    try:
        surovo = bytes.fromhex(hex_naslov)
    except ValueError:
        return ""
    if sys.byteorder == "little":
        surovo = b"".join(surovo[i:i + 4][::-1] for i in range(0, len(surovo), 4))
    try:
        ip = ipaddress.ip_address(surovo)
    except ValueError:
        return ""
    preslikan = getattr(ip, "ipv4_mapped", None)
    return "::ffff:%s" % preslikan if preslikan is not None else str(ip)


#: Naslovi vticnic, ki bi dobile paket, poslan na 127.0.0.1:<vrata>: tocno ta naslov ali »vsi« (IPv4 in IPv6 brez
#: V6ONLY, ki ga /proc ne pokaze - zato steje).
_SPREJMEJO_LOOPBACK = frozenset({"127.0.0.1", "0.0.0.0", "::", "::ffff:127.0.0.1"})


def lastniki_vrat(vrata: int, mapa: str = "/proc/net") -> Optional[set]:
    """Uid-ji lastnikov vticnic (UDP in poslusajoce TCP), ki bi sprejele poizvedbo na 127.0.0.1:<vrata>; prazna
    mnozica = nihce; None = tega na tem sistemu ni mogoce ugotoviti (ni /proc/net).

    Vrata 5354-5357 lahko prvi zasede katerikoli lokalni proces (pregled 18. 10. 2026): ce bi brskalnik ali systemd-
    resolved tak »Scit« sprejel, bi tuji proces videl in ponarejal vsa imena. Zato pred uporabo preverimo lastnika."""
    izid: set = set()
    prebrano = False
    for ime, samo_poslusajoce in (("udp", False), ("udp6", False), ("tcp", True), ("tcp6", True)):
        try:
            with open(os.path.join(mapa, ime), encoding="ascii", errors="replace") as f:
                vrstice = f.read().splitlines()[1:]
        except OSError:
            continue
        prebrano = True
        for v in vrstice:
            d = v.split()
            if len(d) < 8 or ":" not in d[1]:
                continue
            naslov_hex, _, vrata_hex = d[1].rpartition(":")
            try:
                if int(vrata_hex, 16) != vrata:
                    continue
                if samo_poslusajoce and d[3].upper() != "0A":     # TCP_LISTEN
                    continue
                uid = int(d[7])
            except ValueError:
                continue
            if _naslov_iz_proc(naslov_hex) in _SPREJMEJO_LOOPBACK:
                izid.add(uid)
    return izid if prebrano else None


def vrata_nasa(vrata: int) -> bool:
    """Na vratih poslusa samo nas uporabnik (ta ali drug nas proces, npr. Safeer OS ob Safeer Browserju)."""
    if sys.platform == "win32":
        return _windows().vrata_nasa(vrata)
    lastniki = lastniki_vrat(vrata)
    return bool(lastniki) and lastniki == {os.getuid()}


#: Vrata razresevalnikov, ki tecejo v TEM procesu (en proces: Safeer OS, Splet in Safeer Control) - zanje ne
#: sprasujemo nikogar.
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


def tuj_scit(dns: str, nasa_vrata: int) -> bool:
    """Prvi streznik vmesnika je delujoc razresevalnik Scita na DRUGIH vratih - torej Scit drugega prijavljenega
    uporabnika. Tak vmesnik je ze varovan; ce bi ga prepisali, bi ga njegova straza prepisala nazaj, in tako v nedogled.

    Samo, ce vrata drzi en sam drug clovek (uid >= 1000, ne nobody) in odgovori kot Scit: proces, ki je vrata zasedel
    po sesutju Scita (ali sistemski uporabnik), vmesnika ne obdrzi - prevzamemo ga."""
    if sys.platform == "win32":
        return _windows().tuj_scit(dns, nasa_vrata)
    m = re.fullmatch(re.escape(NASLOV) + r":(\d+)", (dns.split() or [""])[0])
    if not m or int(m.group(1)) == nasa_vrata or int(m.group(1)) not in VRATA:
        return False
    vrata = int(m.group(1))
    if not nekdo_poslusa(vrata):
        return False
    lastniki = lastniki_vrat(vrata)
    if not lastniki or len(lastniki) != 1:
        return False
    uid = next(iter(lastniki))
    return uid != os.getuid() and UID_CLOVEKA <= uid != UID_NOBODY and _odgovori_kanarcku(vrata, 0.3)


def je_ostanek(vmesnik: str) -> bool:
    """Vmesnik je v stanju, ki ga je za sabo pustil Scit: brez streznikov DNS (stari `resolvectl revert`) ali z nasim
    streznikom na prvem mestu, na katerem nihce vec ne poslusa (sesutje) - ali ga je zasedel proces, ki ni Scit
    (nas ali drugega prijavljenega uporabnika): tak ne sme dobivati vseh imen racunalnika."""
    if sys.platform == "win32":
        return _windows().je_ostanek(vmesnik)
    deli = dns_vmesnika(vmesnik).split()
    if not deli:
        return True
    m = re.fullmatch(re.escape(NASLOV) + r":(\d+)", deli[0])
    if not m or int(m.group(1)) not in VRATA:
        return False
    vrata = int(m.group(1))
    if not nekdo_poslusa(vrata):
        return True
    return not (vrata_nasa(vrata) or tuj_scit(deli[0], 0))


def izprazni_predpomnilnik() -> None:
    """systemd-resolved razresena imena hrani; po spremembi (vklop, izjema, premor) naj vprasa znova."""
    if sys.platform == "win32":
        return _windows().izprazni_predpomnilnik()
    _zazeni(["resolvectl", "flush-caches"], cas=10.0)


def trenutni_streznik(vmesnik: str) -> str:
    """Streznik, ki ga systemd-resolved za ta vmesnik trenutno uporablja (»Current DNS Server«)."""
    if sys.platform == "win32":
        return _windows().trenutni_streznik(vmesnik)
    koda, izpis = _zazeni(["resolvectl", "status", vmesnik])
    if koda != 0:
        return ""
    m = re.search(r"Current DNS Server:\s*(\S+)", izpis)
    return m.group(1) if m else ""


#: Dejanje starega sirokega pravila (samo za prepoznavo; dovoljenje zanj ne velja vec).
AKCIJA_DNS = "org.freedesktop.resolve1.set-dns-servers"
#: Root pomocnik v paketu .deb (tedenski pregled 4. 11. 2026, S15): prejsnje pravilo (PRAVILO) je VSAKEMU programu
#: skrbnika dovolilo poljuben DNS brez gesla. Pomocnik sprejme samo fiksna dejanja in naslov 127.0.0.1 na vratih Scita;
#: streznike usmerjevalnika in domene prebere sam iz NetworkManagerja. Pravilo zanj dovoli samo AKCIJA_POMOCNIKA.
POMOCNIK = "/usr/lib/safeer-os/scit-dns"
AKCIJA_POMOCNIKA = "si.safeer.os.scit"
#: Flatpak in AppImage (pregled 4. 11. 2026): sirokega pravila za resolve1 NE namescamo vec. Ob prvem vklopu Scita
#: (geslo enkrat) isti pomocnik gre na gostitelja v POMOCNIK_GOSTITELJA; tam ni .policy, zato ga pravilo dovoli kot
#: pkexec TEGA programa (packaging/scit-dns, PRAVILO_GOSTITELJA). Vsebina gre rootu po standardnem vhodu, root preveri
#: SHA-256 SVOJE kopije proti SHA_POMOCNIKA (vgrajena v paket; tests/test_scit_pomocnik.py jo primerja z datoteko).
POMOCNIK_GOSTITELJA = "/usr/local/lib/safeer-os/scit-dns"
SHA_POMOCNIKA = "01225919da27251f40ef3acf2c2d61a5b3201e0abf7cb6743ee35669f08cc919"
#: Pomocnik v tovoru (packaging/install_os_payload.sh: <lib>/packaging/scit-dns; v repozitoriju packaging/scit-dns).
VIR_POMOCNIKA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packaging", "scit-dns")
AKCIJA_PKEXEC = "org.freedesktop.policykit.exec"
#: Kar root naredi ob namestitvi na gostitelja ($1 = SHA-256). Samo navadna vsebina z vhoda (najvec 256 KiB) v rootovo
#: zacasno mapo, preverba vsote KOPIJE, mapa cilja rootova 0755, zamenjava atomsko (mv), nato pomocnik sam namesti
#: svoje ozko pravilo in odstrani staro siroko (scit-dns dovoli).
NAMESTI_POMOCNIKA_KOT_ROOT = r"""set -eu
umask 022
d="$(mktemp -d)"
trap 'rm -rf "$d"' EXIT
head -c 262144 > "$d/scit-dns"
printf '%s  %s\n' "$1" "$d/scit-dns" | sha256sum -c --quiet - || { echo "SHA-256 se ne ujema" >&2; exit 3; }
cilj=/usr/local/lib/safeer-os
install -d -m 755 -o root -g root "$cilj"
[ ! -L "$cilj" ] && [ "$(stat -c '%u %a' "$cilj")" = "0 755" ] || { echo "mapa $cilj ni rootova" >&2; exit 4; }
install -m 755 -o root -g root "$d/scit-dns" "$cilj/.scit-dns.novo"
mv -f "$cilj/.scit-dns.novo" "$cilj/scit-dns"
exec "$cilj/scit-dns" dovoli
"""
#: Izhodna koda pomocnika: Scit usmerjen, rezerve ni (packaging/scit-dns usmeri).
KODA_BREZ_REZERVE = 4
#: Napaka usmeri(), ko Scit dela, rezerve pa ni (besedilo scitNapaka_brez_rezerve).
BREZ_REZERVE = "brez_rezerve"


def v_flatpaku() -> bool:
    """Safeer OS tece v peskovniku Flatpak: sistemska orodja klice na gostitelju (packaging/flatpak_host_wrappers.sh)."""
    return bool(os.environ.get("FLATPAK_ID")) or os.path.exists("/.flatpak-info")


def _predniki(pot: str) -> List[str]:
    """Vse mape nad `pot` do korena (/usr/local/lib/safeer-os, /usr/local/lib, /usr/local, /usr, /)."""
    izid: List[str] = []
    p = os.path.dirname(pot)
    while True:
        izid.append(p)
        visje = os.path.dirname(p)
        if visje == p:
            return izid
        p = visje


def _varen_vnos(uid: int, nacin: int, mapa: bool) -> bool:
    """Rootov, brez pisanja za skupino in druge, ne simbolna povezava; mapa je mapa, program navadna datoteka."""
    if uid != 0 or nacin & 0o022 or _stat.S_ISLNK(nacin):
        return False
    return _stat.S_ISDIR(nacin) if mapa else _stat.S_ISREG(nacin)


def _rootov(pot: str, mapa: bool = False) -> bool:
    try:
        st = os.lstat(pot)          # povezave ne sledimo: njen cilj bi lahko bil uporabnikov
    except OSError:
        return False
    return _varen_vnos(st.st_uid, st.st_mode, mapa) and (mapa or os.access(pot, os.X_OK))


def _rootova_pot(pot: str) -> bool:
    """Program in VSI predniki do / so rootovi in nespremenljivi za druge (pregled 4. 11. 2026, NIZKA): prej sta se
    preverjala samo datoteka in njena mapa - kdor sme pisati v /usr/local (npr. skupina staff), bi mapo zamenjal."""
    return _rootov(pot) and all(_rootov(p, mapa=True) for p in _predniki(pot))


#: Stanje pomocnika na gostitelju: »ok« (nas, varen), »star« (datoteka je, a ni nasa razlicica ali je ne smemo zagnati
#: kot root - nova namestitev jo zamenja), »nevaren« (mapa nad njim ni rootova: namestitev tega ne popravi), »ni«.
_gostitelj_pomocnik: Optional[Tuple[float, str]] = None
#: Kako dolgo velja preverba pomocnika na gostitelju (s): v Flatpaku je to podproces na gostitelju.
POMOCNIK_GOSTITELJA_S = 30.0
#: Lupina na gostitelju (Flatpak): stat brez sledenja povezavam za program in vse prednike, nato vsota. Koda 7 = ni.
_PREVERI_GOSTITELJA = '[ -e "$1" ] || [ -L "$1" ] || exit 7; stat -c "%u %f" -- "$@" && sha256sum -- "$1"'


def _stanje_gostitelja() -> str:
    global _gostitelj_pomocnik
    zdaj = time.monotonic()
    if _gostitelj_pomocnik is not None and zdaj - _gostitelj_pomocnik[0] < POMOCNIK_GOSTITELJA_S:
        return _gostitelj_pomocnik[1]
    predniki = _predniki(POMOCNIK_GOSTITELJA)
    stanje = "ni"
    if v_flatpaku():
        koda, izpis = _zazeni(["flatpak-spawn", "--host", "/bin/sh", "-c", _PREVERI_GOSTITELJA, "safeer-scit",
                               POMOCNIK_GOSTITELJA] + predniki, cas=10.0)
        vrstice = [v.split() for v in izpis.splitlines()] if koda == 0 else []
        if koda == 0 and len(vrstice) == len(predniki) + 2:
            try:
                vnosi = [(int(v[0]), int(v[1], 16)) for v in vrstice[:-1]]
            except (ValueError, IndexError):
                vnosi = []
            if len(vnosi) != len(predniki) + 1 or not all(_varen_vnos(u, n, True) for u, n in vnosi[1:]):
                stanje = "nevaren"
            elif _varen_vnos(vnosi[0][0], vnosi[0][1], False) and vrstice[-1][:1] == [SHA_POMOCNIKA]:
                stanje = "ok"
            else:
                stanje = "star"
        elif koda != 7:
            stanje = "nevaren" if koda == 0 else "ni"
    elif os.path.lexists(POMOCNIK_GOSTITELJA):
        if not all(_rootov(p, mapa=True) for p in predniki):
            stanje = "nevaren"
        else:
            stanje = "star"
            if _rootov(POMOCNIK_GOSTITELJA):
                try:
                    with open(POMOCNIK_GOSTITELJA, "rb") as f:
                        vsebina = f.read(262145)
                    if hashlib.sha256(vsebina).hexdigest() == SHA_POMOCNIKA:
                        stanje = "ok"
                except OSError:
                    pass
    _gostitelj_pomocnik = (zdaj, stanje)
    return stanje


def _pomocnik_gostitelja() -> bool:
    """Ali je na gostitelju NAS pomocnik (rootov, vsi predniki rootovi, vsebina = SHA_POMOCNIKA). Starejsa razlicica
    ne velja: Scit ponudi posodobitev (Scit.posodobi_dovoljenje, geslo enkrat)."""
    return _stanje_gostitelja() == "ok"


def pot_pomocnika() -> Optional[str]:
    """Pot root pomocnika: paket .deb, sicer (Flatpak, AppImage) pomocnik na gostitelju; None, ce ga ni."""
    if not v_flatpaku() and _rootova_pot(POMOCNIK):
        return POMOCNIK
    return POMOCNIK_GOSTITELJA if _pomocnik_gostitelja() else None


def pomocnik() -> bool:
    """Ali DNS nastavlja root pomocnik. Pomocnik mora biti rootov in nespremenljiv za druge - sicer ga ne zaganjamo kot
    root. Brez njega Scit DNS ne nastavlja (pregled 4. 11. 2026: sirokega pravila za resolve1 ni vec).

    Preostalo tveganje (posteno, neodvisni pregled 4. 11. 2026): ozko pravilo dovoli pomocnika VSAKEMU programu
    skrbnikove seje, ne samo Scitu - polkit ju ne loci. Pomocnik zahteva, da na 127.0.0.1:<vrata> (5354-5357) poslusa
    proces ISTEGA uporabnika; program tega uporabnika, ki vrata zasede (npr. ko Scit ne tece), lahko DNS racunalnika
    preusmeri nase. Poljubnega zunanjega streznika ne more nastaviti (samo 127.0.0.1 in strezniki NetworkManagerja),
    imena pa vidi. Pred programom, ki ze tece kot ta uporabnik, Scit racunalnika ne varuje."""
    return pot_pomocnika() is not None


def _pomocnik_koda(*argumenti: str, cas: float = 60.0) -> int:
    """Pomocnik kot root: pkexec in pomocnik z absolutno potjo (core/root_ukaz.py), argumenti samo fiksna dejanja."""
    pot = pot_pomocnika()
    if pot is None:
        return 127
    return _zazeni(root_ukaz.ukaz(pot, *argumenti), cas=cas)[0]


def _pomocnik(*argumenti: str, cas: float = 60.0) -> bool:
    return _pomocnik_koda(*argumenti, cas=cas) == 0


def pravilo_namesceno() -> bool:
    """Ali smemo nastaviti DNS brez gesla. Mape /etc/polkit-1/rules.d uporabnik ne more brati (0750
    root:polkitd), zato pravila ne iscemo po datoteki, ampak polkit vprasamo naravnost (pkcheck brez
    interakcije: 0 = dovoljeno, sicer bi zahteval geslo). Staro siroko pravilo za resolve1 ne velja vec."""
    if sys.platform == "win32":
        return _windows().pravilo_namesceno()
    pot = pot_pomocnika()
    if pot is None:
        return False
    if pot == POMOCNIK:
        if shutil.which("pkcheck") is None:
            return False
        return _zazeni(["pkcheck", "--action-id", AKCIJA_POMOCNIKA, "--process", str(os.getpid())], cas=10.0)[0] == 0
    # Pomocnik na gostitelju: pkexec tega programa (detail »program«, kot ga pkexec poda pravilu).
    if v_flatpaku():
        # V peskovniku pkcheck ne obstaja, nas PID pa gostitelju nic ne pomeni: polkit vprasamo na gostitelju, za
        # lupino, ki jo tam - v isti seji - zazene flatpak-spawn (exec: pkcheck dobi njen PID).
        return _zazeni(["flatpak-spawn", "--host", "/bin/sh", "-c",
                        'exec pkcheck --action-id "$0" --detail program "$1" --process $$', AKCIJA_PKEXEC, pot],
                       cas=10.0)[0] == 0
    if shutil.which("pkcheck") is None:
        return False
    return _zazeni(["pkcheck", "--action-id", AKCIJA_PKEXEC, "--detail", "program", pot,
                    "--process", str(os.getpid())], cas=10.0)[0] == 0


_siroko: Optional[Tuple[float, bool]] = None


def siroko_pravilo_velja() -> bool:
    """Ali na tem racunalniku se velja staro siroko pravilo (PRAVILO: vsak program skrbnika sme brez gesla poljuben
    DNS prek resolve1). Flatpak in AppImage sta ga namescala do 4. 11. 2026; odstrani ga sele pomocnik (`scit-dns
    dovoli`), ki ga dobi Scit ob ponovnem vklopu. Polkit vprasamo naravnost (pkcheck brez interakcije: 0 = dovoljeno
    brez gesla), ker mape pravil uporabnik ne more brati. Samo, ce nasega pomocnika ni - ta staro pravilo ze odstrani
    (.deb: postinst ga prepise z ozkim)."""
    global _siroko
    if pot_pomocnika() is not None:
        return False
    zdaj = time.monotonic()
    if _siroko is not None and zdaj - _siroko[0] < POMOCNIK_GOSTITELJA_S:
        return _siroko[1]
    if v_flatpaku():
        koda = _zazeni(["flatpak-spawn", "--host", "/bin/sh", "-c", 'exec pkcheck --action-id "$0" --process $$',
                        AKCIJA_DNS], cas=10.0)[0]
    elif shutil.which("pkcheck") is None:
        koda = 1
    else:
        koda = _zazeni(["pkcheck", "--action-id", AKCIJA_DNS, "--process", str(os.getpid())], cas=10.0)[0]
    _siroko = (zdaj, koda == 0)
    return koda == 0


def dovoljenje_za_posodobitev() -> str:
    """Kaj Scit ponudi posodobiti (geslo enkrat, Scit.posodobi_dovoljenje): »siroko« = staro siroko pravilo se velja,
    »pomocnik« = pomocnik na gostitelju je star (druga SHA_POMOCNIKA); »« = nic. Oboje resi namestitev pomocnika."""
    if sys.platform == "win32":
        return _windows().dovoljenje_za_posodobitev()
    if siroko_pravilo_velja():
        return "siroko"
    if pot_pomocnika() is None and _stanje_gostitelja() == "star":
        return "pomocnik"
    return ""


def _vsebina_pomocnika() -> Optional[str]:
    """Pomocnik iz tovora, samo ce se ujema s SHA_POMOCNIKA (sicer je paket pokvarjen - nic ne namescamo)."""
    try:
        with open(VIR_POMOCNIKA, "rb") as f:
            vsebina = f.read(262145)
    except OSError:
        return None
    if hashlib.sha256(vsebina).hexdigest() != SHA_POMOCNIKA:
        return None
    try:
        return vsebina.decode("utf-8")
    except UnicodeDecodeError:
        return None


def namesti_pravilo() -> bool:
    """Ob vklopu Scita, z geslom (pkexec), enkrat: dovoljenje, da Scit nastavlja DNS brez gesla.
    .deb: pomocnik namesti svoje ozko pravilo (`scit-dns dovoli`, vsebina je v njem): od nas ne dobi nicesar.
    Flatpak in AppImage: isti pomocnik gre na gostitelja (NAMESTI_POMOCNIKA_KOT_ROOT) in namesti svoje ozko pravilo;
    sirokega pravila za resolve1 ne namescamo vec (pregled 4. 11. 2026).

    Kaj vsota SHA-256 dokazuje: da root namesti natanko pomocnika iz tega paketa (celovitost prenosa od nas do roota,
    mimo uporabnikovih datotek). Izvora NE dokazuje - vsota je vgrajena v isti paket; izvor jamci podpis paketa
    (Flatpak, AppImage, .deb), ne ta preverba."""
    if sys.platform == "win32":
        return _windows().namesti_pravilo()
    global _gostitelj_pomocnik, _siroko
    pot = pot_pomocnika()
    if pot is not None:
        return pravilo_namesceno() or _pomocnik("dovoli", cas=180.0)
    vsebina = _vsebina_pomocnika()
    if vsebina is None or not root_ukaz.na_voljo():
        return False
    # Vsebina gre rootu po standardnem vhodu, ne iz datoteke uporabnika (AGENTS.md, »Root in datoteke uporabnika«);
    # vsota je v ukazni vrstici, ki jo polkit pokaze ob geslu. V Flatpaku vhod do gostitelja prenese flatpak-spawn.
    koda, _ = _zazeni_z_vhodom([root_ukaz.pkexec(), root_ukaz.SH, "-c", NAMESTI_POMOCNIKA_KOT_ROOT,
                                "safeer-scit", SHA_POMOCNIKA], vsebina, cas=180.0)
    _gostitelj_pomocnik = _siroko = None
    return koda == 0


def usmeri(vmesnik: str, vrata: int, rezerva: Optional[List[str]] = None) -> str:
    """DNS vmesnika: nas razresevalnik prvi, strezniki usmerjevalnika za njim kot rezerva. Rezerva je
    nujna: Docker in podobni bereta /run/systemd/resolve/resolv.conf, kjer resolved nas 127.0.0.1 izpusti
    (loopback brez vrat) - brez rezerve bi vsebniki ostali brez DNS; in ce Safeer OS nenadoma ugasne, DNS dela
    naprej. resolved uporablja nas streznik, na rezervo preide sele, ce nas ne odgovori; straza ga vrne nazaj.

    V DVEH korakih: systemd-resolved obdrzi streznik, ki ga trenutno uporablja, ce je ta tudi na novem seznamu.
    »Nas + usmerjevalnik« v enem koraku bi ga zato pustil pri usmerjevalniku in Scit ne bi dobil nobene poizvedbe.
    Najprej torej samo nas (prejsnji streznik odpade), sele potem nas z rezervo (nas ostane trenutni).

    Iskalnih domen in privzete poti se ne dotikamo.

    S pomocnikom oba koraka naredi pomocnik; rezervo prebere sam iz NetworkManagerja (isto kot `rezerva`).

    Vrne napako: "" = uspeh, "pravilo" = DNS ni nastavljen, BREZ_REZERVE = Scit je usmerjen, rezerve pa ni (drugi
    korak je padel). Prej je to vrnilo uspeh in rezerva se je tiho izgubila (pregled 4. 11. 2026)."""
    if sys.platform == "win32":
        return _windows().usmeri(vmesnik, vrata, rezerva)
    if pomocnik():
        koda = _pomocnik_koda("usmeri", vmesnik, str(int(vrata)))
        return "" if koda == 0 else BREZ_REZERVE if koda == KODA_BREZ_REZERVE else "pravilo"
    nas = "%s:%d" % (NASLOV, vrata)
    if _zazeni(NASTAVI + ["dns", vmesnik, nas], cas=30.0)[0] != 0:
        return "pravilo"
    if rezerva and _zazeni(NASTAVI + ["dns", vmesnik, nas] + list(rezerva), cas=30.0)[0] != 0:
        return BREZ_REZERVE
    return ""


def povrni(vmesnik: str) -> bool:
    """Vmesniku vrne streznike DNS, ki jih je dolocil NetworkManager.

    Samo `resolvectl revert` NI dovolj: pobrise tudi streznike, ki jih je systemd-resolved dobil od NetworkManagerja,
    ta pa jih znova poslje sele ob naslednji povezavi - racunalnik bi do takrat ostal brez DNS."""
    if sys.platform == "win32":
        return _windows().povrni(vmesnik)
    if pomocnik():
        return _pomocnik("povrni", vmesnik)
    strezniki = upstream_strezniki(vmesnik)
    if not strezniki:
        return _zazeni(NASTAVI + ["revert", vmesnik], cas=30.0)[0] == 0
    ok = _zazeni(NASTAVI + ["dns", vmesnik] + strezniki, cas=30.0)[0] == 0
    uredi_domene(vmesnik)
    return ok


# ---------------------------------------------------------------------- Scit
class Scit:
    def __init__(self, shramba, mapa: Optional[str] = None) -> None:
        self.shramba = shramba
        self.mapa = mapa or podatkovna_mapa()
        self._skupni = mapa is None          # obicajna mapa: isti seznami kot brskalnik (en prenos na proces)
        self.seznami: Optional[Seznami] = None
        self.razresevalnik: Optional[Razresevalnik] = None
        self.vmesniki: List[str] = []
        #: Vmesniki, kjer je Scit usmerjen, rezerve (strezniki usmerjevalnika) pa ni bilo mogoce dodati.
        self.brez_rezerve: set = set()
        self.strezniki: List[str] = []
        self.napaka = ""
        self._straza: Optional[threading.Thread] = None
        self._pregled_takoj = False      # po zastoju procesa (scit_proces.utripaj): straza pregleda DNS ob naslednjem utripu
        self._kljuc = threading.Lock()
        #: Imena, ki jih je uporabnik spustil sam (ime -> velja do, time.time), in konec premora (time.monotonic).
        self._izjeme: Dict[str, float] = self._preberi_izjeme()
        self._premor_do = 0.0

    #: Ura za izjeme (preizkusi jo zamenjajo).
    _ura = staticmethod(time.time)

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
        """(izbira, naslov po meri): kam Scit posreduje dovoljena imena. Privzeto krajevni DNS (PRIVZETI_NAPREJ =
        »router«: strezniki usmerjevalnika iz NetworkManagerja) - nic k tujemu strezniku, dokler uporabnik ne izbere."""
        izbira = str(self.shramba.get("scit_naprej", PRIVZETI_NAPREJ) or PRIVZETI_NAPREJ)
        return (izbira if izbira in IZBIRE_NAPREJ else PRIVZETI_NAPREJ), str(self.shramba.get("scit_naprej_po_meri", "") or "")

    def nastavi_naprej(self, izbira, po_meri="") -> dict:
        """Uporabnik izbere streznik naprej. Naslov po meri (DoH ali IP, tudi Pi-hole) se preveri samo po obliki."""
        izbira = str(izbira or "")
        po_meri = str(po_meri or "").strip()
        # Napaka oblike gre samo v odgovor. self.napaka je stanje Scita (pravilo, BREZ_REZERVE, ni_omrezja), ki ga
        # nastavi _uporabi: prej ga je ta klic pobrisal ali prepisal z »naprej«, ki je nato obvisel pod stikalom
        # (pregled 4. 11. 2026, isto kot Windows 76e8491).
        if izbira not in IZBIRE_NAPREJ:
            return dict(self.stanje(), napaka="naprej")
        if izbira == "custom":
            from core.doh_proxy import razcleni_po_meri
            vrsta, vrednost = razcleni_po_meri(po_meri)
            if vrsta == "ip" and je_zanka_naprej(vrednost):
                # Scit ne sme posredovati sam sebi (ne prek resolved, ne prek Spleta)
                return dict(self.stanje(), napaka="naprej_zanka")
            if not vrsta:
                return dict(self.stanje(), napaka="naprej")
            self.shramba.set("scit_naprej_po_meri", po_meri)
        self.shramba.set("scit_naprej", izbira)
        self._zagonska_imena = None
        self._osvezi_predpomnilnik()
        try:
            import sys
            doh = sys.modules.get("core.doh_proxy")
            if doh is not None:
                doh.osvezi_naprej()           # isti streznik naprej takoj tudi v Spletu (en vir nastavitve)
        except Exception:  # noqa: BLE001
            pass
        return self.stanje()

    def _naprej(self, paket: bytes) -> Optional[bytes]:
        izbira, po_meri = self.naprej()
        if izbira == "router":
            return None
        try:
            from core.doh_proxy import posreduj_paket, razcleni_po_meri
        except Exception:  # noqa: BLE001 - brez libsoup: usmerjevalnik
            return None
        if izbira == "custom":
            vrsta, vrednost = razcleni_po_meri(po_meri)
            if vrsta == "ip" and je_zanka_naprej(vrednost):
                return None        # stara nastavitev iz casa pred varovalom: usmerjevalnik namesto zanke
        return posreduj_paket(izbira, po_meri, paket, CAS_UPSTREAM)

    _zagonska_imena: Optional[Tuple[Tuple[str, str], frozenset]] = None

    def _zagonsko(self, ime: str) -> bool:
        """Ime streznika DoH naprej (glej Razresevalnik.zagonsko). Strezniki z naslovom IP (Cloudflare) imena nimajo."""
        nastavitev = self.naprej()
        shranjeno = self._zagonska_imena
        if shranjeno is None or shranjeno[0] != nastavitev:
            imena: set = set()
            try:
                import urllib.parse
                from core.doh_proxy import DOH_PROVIDERS, razcleni_po_meri
                izbira, po_meri = nastavitev
                url = ""
                if izbira in DOH_PROVIDERS:
                    url = DOH_PROVIDERS[izbira]["url"]
                elif izbira == "custom":
                    vrsta, vrednost = razcleni_po_meri(po_meri)
                    url = vrednost if vrsta == "doh" else ""
                gostitelj = (urllib.parse.urlsplit(url).hostname or "").lower().rstrip(".") if url else ""
                try:
                    ipaddress.ip_address(gostitelj)
                except ValueError:
                    if gostitelj:
                        imena.add(gostitelj)
            except Exception:  # noqa: BLE001 - brez libsoup ni DoH naprej, ni zagonskih imen
                pass
            shranjeno = self._zagonska_imena = (nastavitev, frozenset(imena))
        return ime in shranjeno[1]

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

    def _osvezi_predpomnilnik(self) -> None:
        r = self.razresevalnik
        if r is not None and r.vrata:
            izprazni_predpomnilnik()
            # Ce je resolved medtem presel na rezervo (nas razresevalnik mu ni odgovoril pravocasno), naj uporabnikova
            # izbira (»Blokiraj spet«, konec premora) velja takoj, ne sele ob naslednjem utripu straze (do UTRIP_S).
            try:
                with self._kljuc:
                    self._uporabi()
            except Exception as e:  # noqa: BLE001 - straza poskusi znova
                print("[Scit] ponovna nastavitev DNS po spremembi ni uspela:", e, flush=True)

    def premor_se(self) -> int:
        """Koliko sekund premora je se ostalo (0 = Scit blokira)."""
        ostane = self._premor_do - time.monotonic() if self._premor_do else 0.0
        return int(ostane) + 1 if ostane > 0 else 0

    @property
    def vklopljen(self) -> bool:
        return bool(self.shramba.get("scit", False))

    # -- Twitch brez oglasov (core/twitch_hls.py): velja za Medijski center, tudi ce DNS-filtra ni mogoce vklopiti
    def twitch_brez_oglasov(self) -> bool:
        """Lastnik 17. 10. 2026: Scit izloca oglase, ki jih Twitch vstavi v prenos; privzeto vklopljeno."""
        return self.shramba.get("scit_twitch_oglasi", True) is not False

    def nastavi_kljuc_abusech(self, vnos: str) -> dict:
        """Lastnik 9. 11. 2026: uporabnik vpise svoj kljuc abuse.ch; preveri se pri abuse.ch, sele nato se shrani."""
        kljuc = ocisti_kljuc(vnos or "")
        izid = preveri_kljuc(kljuc)
        if izid == "velja":
            try:
                from core.sporocila import skrivnosti
                if not skrivnosti.shrani(SKRIVNOST_ABUSECH, kljuc):
                    izid = "ni_shranjeno"
            except Exception:  # noqa: BLE001
                izid = "ni_shranjeno"
        if izid == "velja":
            self._ima_kljuc = True
            seznami = self.seznami
            if seznami is not None:
                threading.Thread(target=seznami.osvezi, name="safeer-scit-kljuc", daemon=True).start()
        s = self.stanje()
        s["kljucIzid"] = izid
        return s

    def dodaj_po_meri(self, url: str) -> dict:
        """Lastnik 9. 11. 2026: filter po meri (kot AdGuard); seznam se pred dodajanjem prenese in preveri."""
        seznami = self.seznami if self.seznami is not None else skupni_seznami(zazeni=False)
        izid = seznami.dodaj_po_meri(url)
        s = self.stanje()
        s["poMeriIzid"] = izid
        return s

    def nastavi_po_meri(self, ident: str, vklop: Optional[bool]) -> dict:
        seznami = self.seznami if self.seznami is not None else skupni_seznami(zazeni=False)
        seznami.nastavi_po_meri(str(ident), vklop)
        return self.stanje()

    def odstrani_kljuc_abusech(self) -> dict:
        try:
            from core.sporocila import skrivnosti
            skrivnosti.pozabi(SKRIVNOST_ABUSECH)
        except Exception as e:  # noqa: BLE001
            # Brez kljuca v izpisu: samo vrsta napake (zbirka skrivnosti nedosegljiva).
            print("[SafeerOS] scit: kljuc abuse.ch ni odstranjen:", type(e).__name__, flush=True)
        self._ima_kljuc = False
        return self.stanje()

    #: Ali je kljuc abuse.ch vpisan (zbirka skrivnosti se vprasa enkrat, nato samo ob spremembi - stanje bere pult).
    _ima_kljuc: Optional[bool] = None

    def ima_kljuc_abusech(self) -> bool:
        if self._ima_kljuc is None:
            self._ima_kljuc = abusech_kljuc() is not None
        return self._ima_kljuc

    def nastavi_twitch(self, vklop: bool) -> dict:
        self.shramba.set("scit_twitch_oglasi", bool(vklop))
        return self.stanje()

    def mozno(self) -> bool:
        return not razlog_nemoznosti()

    #: Pult (ikona Scita, safeer_os._osvezi_scit_pult) bere stanje vsakih 15 s. razlog_nemoznosti zazene systemctl (v
    #: Flatpaku se cat na gostitelju prek flatpak-spawn), pravilo_namesceno pkcheck: pult prvega potrebuje redko, drugega
    #: nikoli. Do 19. 10. 2026 je pult vsakih 15 s klical polno stanje() - 2 do 4 podprocesi na osvezitev.
    RAZLOG_PULTA_S = 300.0
    _razlog = None                       # (time.monotonic, razlog_nemoznosti()) zadnje preverbe

    def _preveri_razlog(self) -> str:
        razlog = razlog_nemoznosti()
        self._razlog = (time.monotonic(), razlog)
        return razlog

    #: Kaj Scit ponuja posodobiti (dovoljenje_za_posodobitev): »siroko«, »pomocnik« ali »«. Preveri se ob zagonu, ob
    #: pregledu straze in v stanje(); pult bere samo zadnjo vrednost (brez podprocesa).
    _dovoljenje = ""
    #: Napaka v vmesniku in pultu za posodobitev dovoljenja (besedili scitNapaka_siroko, scitNapaka_pomocnik_star).
    NAPAKA_DOVOLJENJA = {"siroko": "siroko", "pomocnik": "pomocnik_star"}

    def _preveri_dovoljenje(self) -> str:
        try:
            self._dovoljenje = dovoljenje_za_posodobitev()
        except Exception as e:  # noqa: BLE001 - preverba ne sme ustaviti Scita; zadnja vrednost ostane
            print("[SafeerOS] scit: dovoljenje:", e, flush=True)
        return self._dovoljenje

    def _napaka_vmesnika(self) -> str:
        """Napaka za vmesnik: staro siroko pravilo ali star pomocnik ni tiha - prekrije »pravilo« in praznino."""
        d = self.NAPAKA_DOVOLJENJA.get(self._dovoljenje, "")
        return d if d and self.napaka in ("", "pravilo") else self.napaka

    def _stanje_dovoljenja(self) -> dict:
        d = self._dovoljenje
        return {"dovoljenje": d, "dovoljenjePonudi": bool(d) and self.shramba.get("scit_dovoljenje_ponujeno") != d,
                "napaka": self._napaka_vmesnika()}

    def posodobi_dovoljenje(self, da: bool = True) -> dict:
        """Ponudba ob zagonu Safeer OS (enkrat) ali gumb v oknu Scita: namesti pomocnika (geslo enkrat); ta staro
        siroko pravilo odstrani, star pomocnik se zamenja. »Ne zdaj« (da=False) ponudbe ne ponovi, opozorilo v oknu
        Scita in v pultu pa ostane - nikoli tiho (neodvisni pregled 4. 11. 2026, SREDNJA)."""
        d = self._preveri_dovoljenje()
        if d:
            self.shramba.set("scit_dovoljenje_ponujeno", d)
        if da and d:
            ok = namesti_pravilo()
            self._preveri_dovoljenje()
            if not ok:
                self.napaka = "pravilo"
            elif self.vklopljen and self.mozno():
                self.napaka = ""
                self._zazeni()
            elif self.napaka == "pravilo":
                self.napaka = ""
        return self.stanje()

    def razlog_svez(self) -> bool:
        """Ali stanje_pulta() ne bo zagnalo podprocesa (zadnja preverba razloga je mlajsa od RAZLOG_PULTA_S)."""
        return self._razlog is not None and time.monotonic() - self._razlog[0] < self.RAZLOG_PULTA_S

    def stanje_pulta(self, preveri: bool = True) -> dict:
        """Kar pult potrebuje za ikono in namig (pladenj_sni.vrsta_scita, opis_scita): vklop, mozno, tece, napaka, premor,
        blokiranih. Iz pomnilnika tega procesa; razlog nemoznosti najvec vsakih RAZLOG_PULTA_S (polno stanje() ga osvezi).
        preveri=False (glavna nit): zadnji znani razlog tudi, ce je star - podproces nikoli ne tece na glavni niti."""
        r = self.razresevalnik
        razlog = self._razlog[1] if self._razlog is not None and (not preveri or self.razlog_svez()) \
            else self._preveri_razlog()
        if not razlog and self.napaka in ("ni_resolved", "lastni_dns"):
            self.napaka = ""
        return {"vklop": self.vklopljen, "mozno": not razlog, "razlog": razlog, "tece": bool(r and r.vrata),
                "blokiranih": r.blokiranih if r else 0, "poizvedb": r.poizvedb if r else 0,
                "premor": self.premor_se(), "vrata": r.vrata if r else 0, **self._stanje_dovoljenja(),
                # Splet v Safeer OS (Scit v svojem procesu) oznako »DNS nesifriran« dobi iz tega hitrega stanja.
                "nesifrirano": bool(r is not None and r.vrata and isinstance(r, Razresevalnik) and r.sifrirano_naprej()
                                    and r.nesifrirano())}

    def stanje(self) -> dict:
        r = self.razresevalnik
        razlog = self._preveri_razlog()
        if not razlog and self.napaka in ("ni_resolved", "lastni_dns", "pihole_ostanek"):
            self.napaka = ""      # razmere so se medtem spremenile (npr. /etc/resolv.conf spet kaze na resolved)
        s = {"vklop": self.vklopljen, "mozno": not razlog, "razlog": razlog, "tece": bool(r and r.vrata), "napaka": self.napaka,
             "vmesniki": list(self.vmesniki), "brezRezerve": sorted(self.brez_rezerve), "strezniki": list(self.strezniki), "blokiranih": r.blokiranih if r else 0,
             "poizvedb": r.poizvedb if r else 0, "zadnje": list(r.zadnje) if r else [],
             "pravilo": pravilo_namesceno(), "domen": 0, "pravil": 0,
             "izjeme": list(self._veljavne_izjeme()), "premor": self.premor_se(),
             "naprej": self.naprej()[0], "naprejPoMeri": self.naprej()[1],
             # Uporabnik je streznik naprej ze izbral sam (shranjena izbira); sicer ga vmesnik ob vklopu vprasa.
             "naprejIzbran": self.shramba.get("scit_naprej") is not None, "rezerv": getattr(r, "rezerv", 0),
             # DoH ni odgovoril in imena so sla nesifrirano usmerjevalniku (mirna oznaka v vmesniku, brez okna).
             "nesifrirano": bool(r is not None and r.vrata and isinstance(r, Razresevalnik) and r.sifrirano_naprej()
                                 and r.nesifrirano()),
             "twitchOglasi": self.twitch_brez_oglasov(), "kljucAbusech": self.ima_kljuc_abusech()}
        self._preveri_dovoljenje()
        s.update(self._stanje_dovoljenja())
        if self.seznami is not None:
            s.update(self.seznami.stanje())
        return s

    def zacni_ce_vklopljen(self) -> None:
        """Ob zagonu Safeer OS: Scit, ki je bil vklopljen, tece naprej (brez gesla - pravilo je namesceno). Kadar je
        izklopljen, samo pospravi, kar je morda ostalo za starejso razlicico ali po sesutju."""
        threading.Thread(target=self._zagon, name="safeer-scit-zagon", daemon=True).start()

    #: Kako pogosto Scit, ki je vklopljen, a trenutno ni mozen, preveri, ali je ovira izginila (systemctl: poceni).
    CAKAJ_MOZNO_S = 30.0
    _caka = None

    def _cakaj_mozno(self) -> None:
        """Lastnik 2. 11. 2026: Scit se mora vklopiti sam, brez terminala. Prej je ob »ni mozno« ob zagonu obstal za
        vedno; zdaj caka in se vklopi, ko ovira izgine (npr. uporabnik odstrani Pi-hole ali pritisne »Popravi«)."""
        if self._caka is not None and self._caka.is_alive():
            return

        def zanka() -> None:
            while self.vklopljen:
                razlog = razlog_nemoznosti()
                if not razlog:
                    self.napaka = ""
                    try:
                        self._zazeni()
                    except Exception as e:  # noqa: BLE001 - straza ne sme umreti, poskusi ob naslednjem krogu
                        print("[SafeerOS] scit: zagon po cakanju:", e)
                    return
                self.napaka = razlog
                time.sleep(self.CAKAJ_MOZNO_S)
        self._caka = threading.Thread(target=zanka, name="safeer-scit-caka", daemon=True)
        self._caka.start()

    def popravi(self) -> dict:
        """Gumb »Popravi«: pospravi znan ostanek (Pi-hole), potem Scit nadaljuje sam. Root samo prek root_ukaz s fiksnim ukazom."""
        if razlog_nemoznosti() == "pihole_ostanek":
            from core import root_ukaz
            koda, _ = _zazeni(root_ukaz.ukaz(root_ukaz.SH, "-c", POPRAVI_PIHOLE_UKAZ), cas=180.0)
            if koda != 0:
                self.napaka = "pravilo"
                return self.stanje()
            self.napaka = razlog_nemoznosti()
            if not self.napaka and self.vklopljen:
                self._zazeni()
        return self.stanje()

    def _zagon(self) -> None:
        # Staro siroko pravilo ali star pomocnik: pult in okno Scita to pokazeta takoj, tudi ce je Scit izklopljen.
        self._preveri_dovoljenje()
        # Kjer Scit ne more filtrirati (npr. uporabnik je medtem namestil svoj streznik DNS), se DNS ne dotikamo -
        # ce ga je uporabnik vklopil, pocakamo, da ovira izgine.
        if not self.mozno():
            if self.vklopljen:
                self._cakaj_mozno()
            return
        if self.vklopljen:
            self._zazeni()
        else:
            self.pospravi_ostanke()

    def pospravi_ostanke(self) -> List[str]:
        """Vmesnikom, ki jih je Scit pustil brez delujocega DNS, vrne streznike NetworkManagerja. Samo kadar smemo
        nastavljati brez gesla (pravilo polkit = Scit je bil na tem racunalniku ze vklopljen)."""
        popravljeni: List[str] = []
        try:
            for v in vmesniki_povezani():
                if upstream_strezniki(v) and je_ostanek(v) and pravilo_namesceno() and povrni(v):
                    popravljeni.append(v)
        except Exception as e:  # noqa: BLE001
            print("[SafeerOS] scit: ostanki:", e)
        return popravljeni

    def nastavi(self, vklop: bool) -> dict:
        self.napaka = ""
        if vklop:
            razlog = razlog_nemoznosti()
            if razlog:
                self.napaka = razlog
                if razlog == "pihole_ostanek":
                    # Ostanek (ne uporabnikov streznik DNS): izbira velja, Scit zacne, ko ga »Popravi« pospravi.
                    self.shramba.set("scit", True)
                    self._cakaj_mozno()
                return self.stanje()
            if not namesti_pravilo():
                self.napaka = "pravilo"
                return self.stanje()
            self._zazeni()
            if self.napaka in ("", "ni_omrezja", BREZ_REZERVE):
                # Brez omrezja ob vklopu nastavitev vseeno velja: straza zacne filtrirati, ko se racunalnik poveze.
                self.shramba.set("scit", True)
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
                self.seznami = skupni_seznami(zazeni=False) if self._skupni else Seznami(self.mapa)
            self.seznami.zazeni()
            if self.razresevalnik is None:
                self.razresevalnik = Razresevalnik(self._kategorija, lambda: self.strezniki, self._naprej,
                                                   zagonsko=self._zagonsko,
                                                   izjema=lambda i: self._izjeme.get(i, 0) > self._ura()
                                                   or webtor.je_stalna_izjema_scita(i),
                                                   ip_groznje=self.seznami.ip_groznje)
                self.razresevalnik.sifrirano_naprej = lambda: self.naprej()[0] != "router"
            vrata = self.razresevalnik.zazeni()
            if not vrata:
                self.napaka = "vrata"
                return False
            self._uporabi()
            if self._straza is None:
                self._straza = threading.Thread(target=self._strazi, name="safeer-scit-straza", daemon=True)
                self._straza.start()
            return bool(self.vmesniki)

    def _uporabi(self) -> None:
        """DNS vseh povezanih vmesnikov na nas razresevalnik (tudi po menjavi omrezja); strezniki upstream
        se preberejo tu, ne ob vsaki poizvedbi."""
        r = self.razresevalnik
        if r is None or not r.vrata:
            return
        cilj = "%s:%d" % (NASLOV, r.vrata)
        povezani = vmesniki_povezani()
        lastni = {v: upstream_strezniki(v) for v in povezani}
        strezniki: List[str] = []
        for v in povezani:
            for s in lastni[v]:
                s = za_vticnico(s, v)
                if s not in strezniki:
                    strezniki.append(s)
        # Kam posredujemo, mora biti znano, PREDEN resolved poslje prvo poizvedbo: brez odgovora bi takoj presel na
        # rezervo in Scit zaobsel. Brez krajevnega DNS ostane seznam prazen: razresevalnik odgovori SERVFAIL takoj,
        # tujega razresevalnika ne izberemo namesto uporabnika (lastnik; prej 1.1.1.1 in 9.9.9.9, najdba 4. 11. 2026).
        self.strezniki = strezniki
        novo = zavrnjeno = tuje = False
        smemo: Optional[bool] = None
        for v in povezani:
            dns = dns_vmesnika(v)
            if tuj_scit(dns, r.vrata):
                tuje = True          # varuje ga Scit drugega prijavljenega uporabnika: ne tekmujemo z njim
                if v in self.vmesniki:
                    self.vmesniki.remove(v)
                continue
            # Nastavimo (znova), ce nas ni na prvem mestu (NetworkManager je po novi povezavi poslal svoje) ali ce
            # je resolved presel na rezervo (nas razresevalnik mu ni odgovoril pravocasno).
            # Brez rezerve (drugi korak je zadnjic padel): poskusimo znova ob vsakem pregledu straze.
            if (not dns.startswith(cilj) or trenutni_streznik(v) not in ("", cilj, NASLOV)
                    or v in self.brez_rezerve):
                if smemo is None:
                    smemo = pravilo_namesceno()
                napaka = usmeri(v, r.vrata, lastni[v]) if smemo else "pravilo"
                if napaka == BREZ_REZERVE:
                    self.brez_rezerve.add(v)       # Scit filtrira, a ob padcu Safeer OS ali za Docker DNS ne dela
                elif napaka:
                    zavrnjeno = True
                    self.brez_rezerve.discard(v)
                    if v in self.vmesniki:
                        self.vmesniki.remove(v)
                    continue
                else:
                    self.brez_rezerve.discard(v)
                novo = True
            if v not in self.vmesniki:
                self.vmesniki.append(v)
                if smemo is None:
                    smemo = pravilo_namesceno()
                if smemo:
                    uredi_domene(v)
        self.vmesniki = [v for v in self.vmesniki if v in povezani]
        self.brez_rezerve &= set(self.vmesniki)
        if self.vmesniki or tuje:
            if self.brez_rezerve:
                if self.napaka in ("", "ni_omrezja", "pravilo"):
                    self.napaka = BREZ_REZERVE
            elif self.napaka in ("ni_omrezja", "pravilo", BREZ_REZERVE):
                self.napaka = ""
        else:
            # Povezan vmesnik, ki ga ne smemo nastaviti = ni dovoljenja (pravilo polkit); sicer ni omrezja.
            self.napaka = "pravilo" if zavrnjeno else "ni_omrezja"
        if novo:
            izprazni_predpomnilnik()     # ze razresena (zdaj blokirana) imena naj ne ostanejo v predpomnilniku

    def po_zastoju(self) -> None:
        """Proces je stal (stiska sistema): resolved je morda presel na usmerjevalnik - straza naj preveri takoj."""
        self._pregled_takoj = True

    def _strazi(self) -> None:
        jaz = threading.current_thread()
        zadnjic, znak = time.monotonic(), znak_dns()
        while self._straza is jaz:
            time.sleep(UTRIP_S)
            if self._straza is not jaz or not self.vklopljen or self.razresevalnik is None or not self.razresevalnik.vrata:
                return
            # Sprememba omrezja (NetworkManager je vmesniku poslal svoje streznike) se pozna takoj; prehod resolved na
            # rezervo pa datoteke ne spremeni, zato redni pregled ostane.
            # Znak preberemo PRED pregledom: kar se spremeni med njim ali po njem (NetworkManager po ponovnem
            # zagonu resolved poslje svoje streznike z zamikom), sprozi se en pregled ob naslednjem utripu.
            nov_znak = znak_dns()
            if nov_znak == znak and time.monotonic() - zadnjic < PREGLED_S and not self._pregled_takoj:
                continue
            self._pregled_takoj = False
            try:
                with self._kljuc:
                    self._uporabi()
            except Exception:
                pass
            self._preveri_dovoljenje()       # npr. pravilo je kdo namestil ali odstranil medtem (do 30 s predpomnjeno)
            zadnjic, znak = time.monotonic(), nov_znak

    def _ustavi(self) -> None:
        with self._kljuc:
            self._straza = None
            # Brez dovoljenja (pravilo polkit je kdo odstranil) ne sprasujemo za geslo: DNS dela naprej prek rezerve,
            # NetworkManager pa ob naslednji povezavi nastavi svoje.
            if self.vmesniki and pravilo_namesceno():
                for v in list(self.vmesniki):
                    povrni(v)
            self.vmesniki = []
            self.brez_rezerve = set()
            if self.razresevalnik is not None:
                self.razresevalnik.ustavi()
            if self.seznami is not None:
                self.seznami.ustavi()

    def koncaj(self) -> None:
        """Ob izhodu iz Safeer OS: brez razresevalnika bi racunalnik ostal brez DNS, zato povrnemo."""
        if self.vmesniki:
            self._ustavi()
