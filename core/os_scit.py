"""Scit za Safeer OS na Linuxu: filtriranje DNS za ves racunalnik (kot Scit na televizorju in tablici).

Safeer OS tece majhen razresevalnik DNS na 127.0.0.1 (vrata nad 1024, brez pravic). Vsako ime, ki ga
racunalnik hoce razresiti, najprej preveri v naboru blokiranih domen - isti seznami kot pri Scitu na
televizorju (hagezi PRO in TIF, Fake, URLhaus, Phishing Army, SI-CERT) in Safeerjev podpisani seznam
groznj - in ga, ce je na seznamu, zavrne (NXDOMAIN); vse drugo posreduje strezniku DNS, ki ga je dal
usmerjevalnik (NetworkManager). Nic ne gre v oblak, noben tuj streznik ne vidi poizvedb.

Da racunalnik ta razresevalnik uporablja, Safeer OS systemd-resolved za povezano omrezje pove:
»DNS je 127.0.0.1:<vrata>« (resolvectl). To je sistemska nastavitev in polkit zanjo zahteva geslo;
zato ob prvem vklopu enkrat (pkexec) namestimo pravilo polkit, ki skrbniku dovoli te tri klice brez
gesla - kot namestitev programa: geslo enkrat, potem dela samo. Ob izklopu se nastavitev povrne
(resolvectl revert); ob zagonu Safeer OS se, ce je Scit vklopljen, uporabi znova.

Nabor domen je urejeno polje 64-bitnih zgoscenk (blake2b) - pol milijona domen v nekaj MB, iskanje z
bisekcijo; shranjen je na disku, da je ob zagonu takoj tu. Seznami se osvezujejo v ozadju (pogojni GET).
Zunanjih vhodov ne sprejema (samo 127.0.0.1); vsak ukaz je fiksen seznam argumentov.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from array import array
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from core.signed_feed import _atomic_write, isti_gostitelj

NASLOV = "127.0.0.1"
VRATA = (5354, 5355, 5356, 5357)
PRAVILO_POT = "/etc/polkit-1/rules.d/49-safeer-os-scit.rules"
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
KATEGORIJA_SEZNAMA_GROZNJ = {"botnet_c2": "botnet", "malware": "malware", "phishing": "phishing", "scam": "prevare"}
NAJVEC_BAJTOV = 24 * 1024 * 1024
NAJMANJ_DOMEN = 1000
PRVA_OSVEZITEV = 5.0
OSVEZITEV = 6 * 3600.0
PONOVNI_POSKUS = 30 * 60.0
#: Imena, ki jih Scit nikoli ne blokira: domace omrezje in Safeer sam.
NIKOLI = ("localhost", "safeer.si")
NIKOLI_KONCNICE = (".local", ".lan", ".home", ".arpa", ".internal", ".safeer.si")
#: Posodobitve sistema in Safeerja: pot do popravka mora ostati odprta, tudi ce bi seznam s
#: preusmeritvijo ali okvaro na CDN-ju dobil napacne vnose. Velja tudi za poddomene (zrcala).
POSODOBITVE = ("archive.ubuntu.com", "security.ubuntu.com", "ports.ubuntu.com", "ppa.launchpadcontent.net",
               "packages.linuxmint.com", "deb.debian.org", "security.debian.org", "flathub.org",
               "github.com", "api.github.com", "objects.githubusercontent.com",
               "release-assets.githubusercontent.com")


def je_posodobitev(ime: str) -> bool:
    return any(ime == d or ime.endswith("." + d) for d in POSODOBITVE)


def _zazeni(ukaz: List[str], cas: float = 8.0) -> Tuple[int, str]:
    if not ukaz or shutil.which(ukaz[0]) is None:
        return 127, ""
    try:
        r = subprocess.run(ukaz, capture_output=True, text=True, timeout=cas)
        return r.returncode, r.stdout
    except Exception:
        return 1, ""


def podatkovna_mapa() -> str:
    try:
        from core.threat_intel import default_data_dir
        return os.path.join(str(default_data_dir("safeer-mint")), "scit")
    except Exception:
        return os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "safeer-mint", "scit")


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


def odgovor_zavrnjeno(paket: bytes) -> bytes:
    """NXDOMAIN z istim id in vprasanjem: racunalnik takoj ve, da imena ni."""
    konec = 12
    while konec < len(paket) and paket[konec] != 0:
        konec += 1 + paket[konec]
    konec += 5
    glava = paket[:2] + struct.pack("!HHHHH", 0x8183, 1, 0, 0, 0)
    return glava + paket[12:konec]


def upstream_strezniki(vmesnik: str) -> List[str]:
    """Strezniki DNS, ki jih je za ta vmesnik dal usmerjevalnik (NetworkManager), ne glede na to, kaj je
    trenutno nastavljeno v systemd-resolved."""
    koda, izpis = _zazeni(["nmcli", "-g", "IP4.DNS", "device", "show", vmesnik])
    strezniki = []
    if koda == 0:
        for v in izpis.replace("|", "\n").splitlines():
            v = v.strip()
            if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", v) and not v.startswith("127."):
                strezniki.append(v)
    return strezniki


class Razresevalnik:
    """Razresevalnik DNS (UDP in TCP) na 127.0.0.1: blokirana imena zavrne, ostala posreduje."""

    def __init__(self, blokiraj: Callable[[str], Optional[str]], upstream: Callable[[], List[str]]) -> None:
        self.blokiraj = blokiraj
        self.upstream = upstream
        self.vrata = 0
        self.blokiranih = 0
        self.poizvedb = 0
        self.zadnje: List[dict] = []
        self._udp: Optional[socket.socket] = None
        self._tcp: Optional[socket.socket] = None
        self._tece = False
        self._kljuc = threading.Lock()

    def zazeni(self) -> int:
        if self._tece:
            return self.vrata
        for vrata in VRATA:
            try:
                u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                u.bind((NASLOV, vrata))
                t = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                t.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                t.bind((NASLOV, vrata))
                t.listen(16)
            except OSError:
                continue
            self._udp, self._tcp, self.vrata, self._tece = u, t, vrata, True
            threading.Thread(target=self._zanka_udp, name="safeer-scit-udp", daemon=True).start()
            threading.Thread(target=self._zanka_tcp, name="safeer-scit-tcp", daemon=True).start()
            return vrata
        return 0

    def ustavi(self) -> None:
        self._tece = False
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
        return self._posreduj(paket, tcp)

    def _posreduj(self, paket: bytes, tcp: bool) -> Optional[bytes]:
        for streznik in self.upstream() or []:
            try:
                if tcp:
                    with socket.create_connection((streznik, 53), timeout=CAS_UPSTREAM) as s:
                        s.sendall(struct.pack("!H", len(paket)) + paket)
                        glava = self._preberi(s, 2)
                        return self._preberi(s, struct.unpack("!H", glava)[0])
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(CAS_UPSTREAM)
                try:
                    s.sendto(paket, (streznik, 53))
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

    def _zanka_udp(self) -> None:
        u = self._udp
        while self._tece and u is not None:
            try:
                paket, od = u.recvfrom(4096)
            except OSError:
                break

            def delo(p=paket, o=od):
                odgovor = self._odgovori(p, False)
                if odgovor and self._udp is not None:
                    try:
                        self._udp.sendto(odgovor, o)
                    except OSError:
                        pass
            threading.Thread(target=delo, daemon=True).start()

    def _zanka_tcp(self) -> None:
        t = self._tcp
        while self._tece and t is not None:
            try:
                s, _ = t.accept()
            except OSError:
                break

            def delo(s=s):
                try:
                    s.settimeout(10)
                    n = struct.unpack("!H", self._preberi(s, 2))[0]
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
            threading.Thread(target=delo, daemon=True).start()


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

    def shrani(self, pot: str) -> None:
        os.makedirs(os.path.dirname(pot), exist_ok=True)
        zacasna = pot + ".tmp"
        with open(zacasna, "wb") as f:
            f.write(self.GLAVA + struct.pack("<Q", len(self.zgoscenke)))
            self.zgoscenke.tofile(f)
            self.kategorije.tofile(f)
        os.replace(zacasna, pot)

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
        os.makedirs(self.mapa, exist_ok=True)
        zacasna = self._meta_pot() + ".tmp"
        with open(zacasna, "w", encoding="utf-8") as f:
            json.dump(self.meta, f)
        os.replace(zacasna, self._meta_pot())

    # -- zivljenje
    def zazeni(self) -> None:
        if self.storitev is None:
            try:
                from core.threat_intel import ThreatIntelService, default_data_dir
                self.storitev = ThreatIntelService(default_data_dir("safeer-mint"))
                self.storitev.start()
            except Exception as e:  # noqa: BLE001
                print("[SafeerOS] scit: seznam groznj:", e)
        if self._nit is None:
            self._stop.clear()
            self._nit = threading.Thread(target=self._tek, name="safeer-scit-seznami", daemon=True)
            self._nit.start()

    def ustavi(self) -> None:
        self._stop.set()
        self._nit = None

    def _tek(self) -> None:
        jaz = threading.current_thread()
        if self._stop.wait(PRVA_OSVEZITEV if not len(self.nabor) else min(OSVEZITEV, self._do_naslednje())):
            return
        while not self._stop.is_set() and self._nit is jaz:
            ok = self.osvezi()
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
        if not ime or "." not in ime or ime in NIKOLI or ime.endswith(NIKOLI_KONCNICE) or je_posodobitev(ime):
            return None
        with self._kljuc:
            k = self.nabor.kategorija(ime)
        if k:
            return k
        s = self.storitev
        if s is not None and s.loaded.is_set():
            try:
                k = s.store.match_host(ime)
            except Exception:
                k = None
            if k in KATEGORIJA_SEZNAMA_GROZNJ:
                return KATEGORIJA_SEZNAMA_GROZNJ[k]
        return None

    def stanje(self) -> dict:
        st = {"domen": len(self.nabor), "posodobljeno": float(self.meta.get("cas", 0) or 0), "napakaSeznamov": self.napaka,
              "seznami": {o: int(self.meta.get(o, {}).get("domen", 0) or 0) for o, _u, _k in VIRI}}
        if self.storitev is not None:
            try:
                st["pravil"] = int(self.storitev.status().get("rules") or 0)
            except Exception:
                st["pravil"] = 0
        return st


# ---------------------------------------------------------------------- systemd-resolved
def vmesniki_povezani() -> List[str]:
    koda, izpis = _zazeni(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device"])
    izhod = []
    if koda != 0:
        return izhod
    for v in izpis.splitlines():
        d = v.split(":")
        if len(d) >= 3 and d[1] in ("ethernet", "wifi") and d[2] == "connected":
            izhod.append(d[0])
    return izhod


def dns_vmesnika(vmesnik: str) -> str:
    koda, izpis = _zazeni(["resolvectl", "dns", vmesnik])
    return izpis.split(":", 1)[1].strip() if koda == 0 and ":" in izpis else ""


def trenutni_streznik(vmesnik: str) -> str:
    """Streznik, ki ga systemd-resolved za ta vmesnik trenutno uporablja (»Current DNS Server«)."""
    koda, izpis = _zazeni(["resolvectl", "status", vmesnik])
    if koda != 0:
        return ""
    m = re.search(r"Current DNS Server:\s*(\S+)", izpis)
    return m.group(1) if m else ""


def pravilo_namesceno() -> bool:
    """Ali smemo nastaviti DNS brez gesla. Mape /etc/polkit-1/rules.d uporabnik ne more brati (0750
    root:polkitd), zato pravila ne iscemo po datoteki, ampak polkit vprasamo naravnost (pkcheck brez
    interakcije: 0 = dovoljeno, sicer bi zahteval geslo)."""
    try:
        with open(PRAVILO_POT, encoding="utf-8") as f:
            if "org.freedesktop.resolve1.set-dns-servers" in f.read():
                return True
    except OSError:
        pass
    if shutil.which("pkcheck") is None:
        return False
    koda, _ = _zazeni(["pkcheck", "--action-id", "org.freedesktop.resolve1.set-dns-servers",
                       "--process", str(os.getpid())], cas=10.0)
    return koda == 0


def _znak_pravila() -> str:
    return os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "safeer-os", "scit-pravilo")


def namesti_pravilo() -> bool:
    """Enkrat, z geslom (pkexec): pravilo polkit, ki skrbniku dovoli nastaviti DNS brez gesla.
    Uspeh si zapomnimo v uporabnikovi mapi (znak), ker same datoteke pravila ne moremo brati."""
    if os.path.exists(_znak_pravila()) and pravilo_namesceno():
        return True
    if shutil.which("pkexec") is None:
        return False
    with tempfile.NamedTemporaryFile("w", suffix=".rules", delete=False, encoding="utf-8") as f:
        f.write(PRAVILO)
        zacasna = f.name
    try:
        os.chmod(zacasna, 0o644)
        koda, _ = _zazeni(["pkexec", "install", "-m", "644", "-o", "root", "-g", "root", zacasna, PRAVILO_POT], cas=180.0)
        if koda != 0:
            return False
        try:
            os.makedirs(os.path.dirname(_znak_pravila()), mode=0o700, exist_ok=True)
            with open(_znak_pravila(), "w", encoding="utf-8") as f:
                f.write(hashlib.sha256(PRAVILO.encode()).hexdigest() + "\n")
        except OSError:
            pass
        return True
    finally:
        try:
            os.unlink(zacasna)
        except OSError:
            pass


def usmeri(vmesnik: str, vrata: int, rezerva: Optional[List[str]] = None) -> bool:
    """DNS vmesnika: nas razresevalnik prvi, strezniki usmerjevalnika za njim kot rezerva. Rezerva je
    nujna: Docker in podobni bereta /run/systemd/resolve/resolv.conf, kjer resolved nas 127.0.0.1 izpusti
    (loopback brez vrat) - brez rezerve bi vsebniki ostali brez DNS. resolved uporablja prvi streznik,
    na rezervo preide sele, ce nas ne odgovori; straza ga vrne nazaj."""
    ok1, _ = _zazeni(["resolvectl", "dns", vmesnik, "%s:%d" % (NASLOV, vrata)] + list(rezerva or []), cas=30.0)
    ok2, _ = _zazeni(["resolvectl", "domain", vmesnik, "~."], cas=30.0)
    return ok1 == 0 and ok2 == 0


def povrni(vmesnik: str) -> bool:
    return _zazeni(["resolvectl", "revert", vmesnik], cas=30.0)[0] == 0


# ---------------------------------------------------------------------- Scit
class Scit:
    def __init__(self, shramba, mapa: Optional[str] = None) -> None:
        self.shramba = shramba
        self.mapa = mapa or podatkovna_mapa()
        self.seznami: Optional[Seznami] = None
        self.razresevalnik: Optional[Razresevalnik] = None
        self.vmesniki: List[str] = []
        self.strezniki: List[str] = []
        self.napaka = ""
        self._straza: Optional[threading.Thread] = None
        self._kljuc = threading.Lock()

    @property
    def vklopljen(self) -> bool:
        return bool(self.shramba.get("scit", False))

    def mozno(self) -> bool:
        return shutil.which("resolvectl") is not None and shutil.which("nmcli") is not None and \
            _zazeni(["systemctl", "is-active", "systemd-resolved"])[1].strip() == "active"

    def stanje(self) -> dict:
        r = self.razresevalnik
        s = {"vklop": self.vklopljen, "mozno": self.mozno(), "tece": bool(r and r.vrata), "napaka": self.napaka,
             "vmesniki": list(self.vmesniki), "strezniki": list(self.strezniki), "blokiranih": r.blokiranih if r else 0,
             "poizvedb": r.poizvedb if r else 0, "zadnje": list(r.zadnje) if r else [],
             "pravilo": pravilo_namesceno(), "domen": 0, "pravil": 0}
        if self.seznami is not None:
            s.update(self.seznami.stanje())
        return s

    def zacni_ce_vklopljen(self) -> None:
        """Ob zagonu Safeer OS: Scit, ki je bil vklopljen, tece naprej (brez gesla - pravilo je namesceno)."""
        if self.vklopljen:
            threading.Thread(target=self._zazeni, name="safeer-scit-zagon", daemon=True).start()

    def nastavi(self, vklop: bool) -> dict:
        self.napaka = ""
        if vklop:
            if not self.mozno():
                self.napaka = "ni_resolved"
                return self.stanje()
            if not namesti_pravilo():
                self.napaka = "pravilo"
                return self.stanje()
            if self._zazeni():
                self.shramba.set("scit", True)
        else:
            self.shramba.set("scit", False)
            self._ustavi()
        return self.stanje()

    def _zazeni(self) -> bool:
        with self._kljuc:
            if self.seznami is None:
                self.seznami = Seznami(self.mapa)
            self.seznami.zazeni()
            if self.razresevalnik is None:
                self.razresevalnik = Razresevalnik(self.seznami.kategorija, lambda: self.strezniki)
            vrata = self.razresevalnik.zazeni()
            if not vrata:
                self.napaka = "vrata"
                return False
            self._uporabi()
            if not self.vmesniki:
                self.napaka = "ni_omrezja"
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
        strezniki: List[str] = []
        for v in povezani:
            lastni = upstream_strezniki(v)
            for s in lastni:
                if s not in strezniki:
                    strezniki.append(s)
            # Nastavimo (znova), ce nas ni na prvem mestu ali ce je resolved presel na rezervo.
            if not dns_vmesnika(v).startswith(cilj) or (self.vmesniki and trenutni_streznik(v) not in ("", cilj, NASLOV)):
                if usmeri(v, r.vrata, lastni) and v not in self.vmesniki:
                    self.vmesniki.append(v)
            elif v not in self.vmesniki:
                self.vmesniki.append(v)
        self.vmesniki = [v for v in self.vmesniki if v in povezani]
        self.strezniki = strezniki or ["1.1.1.1", "9.9.9.9"]

    def _strazi(self) -> None:
        jaz = threading.current_thread()
        while self._straza is jaz:
            time.sleep(20)
            if self._straza is not jaz or not self.vklopljen or self.razresevalnik is None or not self.razresevalnik.vrata:
                return
            try:
                with self._kljuc:
                    self._uporabi()
            except Exception:
                pass

    def _ustavi(self) -> None:
        with self._kljuc:
            self._straza = None
            for v in list(self.vmesniki):
                povrni(v)
            self.vmesniki = []
            if self.razresevalnik is not None:
                self.razresevalnik.ustavi()
            if self.seznami is not None:
                self.seznami.ustavi()

    def koncaj(self) -> None:
        """Ob izhodu iz Safeer OS: brez razresevalnika bi racunalnik ostal brez DNS, zato povrnemo."""
        if self.vmesniki:
            self._ustavi()
