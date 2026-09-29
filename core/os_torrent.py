"""Safeer Media: magnet povezave (BitTorrent) - prejem, pošiljanje in predvajanje že med prenosom.

Motor je odprtokodni rqbit (Apache-2.0, https://github.com/ikatson/rqbit). Safeer ga ob prvi rabi prenese
z uradne izdaje na GitHubu, preveri SHA-256 in ga zažene kot lasten proces, samo na 127.0.0.1:

- API rqbita zahteva geslo (HTTP Basic, naključno ob vsakem zagonu). Spletna stran v brskalniku ga zato
  ne more upravljati (CSRF), drug program na računalniku pa ne pozna gesla.
- Predvajalnik dobi lokalni naslov `/t/<skrivnost>`, ta pa bere tok iz rqbita (`Range`, previjanje). Rqbit
  med tokom sam prenaša najprej kose okoli mesta predvajanja: film se začne v nekaj sekundah.
- Predvajamo samo glasbo in video, nikoli ne odpremo ali poženemo druge datoteke. Programi in skripte v
  torrentu (.exe, .scr, .lnk, .apk ...) so privzeto izključeni in označeni kot nevarni.
- Oddajanje drugim (upload) je med prenosom omejeno. Po koncu prenosa se ustavi, razen če uporabnik
  izrecno izbere »Deli naprej«. Tako Safeer ne deli vsebine brez njegove vednosti.
- Hitrost brez pretirane obremenitve: omejeno število povezav in niti, DHT si zapomni vozlišča (hitrejše
  iskanje ob naslednjem zagonu), fastresume (brez ponovnega preverjanja), nekaj zanesljivih javnih
  sledilnikov, kadar jih magnet nima.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import http.server
import json
import os
import platform
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from typing import Iterable, Callable, Dict, List, Optional, Tuple

RQBIT_RAZLICICA = "9.0.1"
#: Uradne izdaje (github.com/ikatson/rqbit/releases/tag/v9.0.1) in njihov SHA-256 iz GitHubovega "digest".
RQBIT_PAKETI: Dict[str, Tuple[str, str, int]] = {
    "linux-x86_64": ("rqbit-linux-amd64", "82ed2c23f4c7b91bb2c92eaab92e4a850d386cdf337bcdf9e0971c8ce3da4335", 28696960),
    "linux-aarch64": ("rqbit-linux-arm64", "9ac50a7d1917cd458111265a12346a924b4f7cea7520327782ed5bd6f423b561", 25826632),
    "windows-amd64": ("rqbit.exe", "2ed683203beca628e0c45f62f99feeef4242cecc3444c8422dfe5b1b6aa38cea", 12706816),
}
RQBIT_URL = "https://github.com/ikatson/rqbit/releases/download/v{razlicica}/{ime}"

#: Hitrost brez pretirane obremenitve (glej docstring).
NAJVEC_POVEZAV = 80
NITI = 2
ODDAJA_MED_PRENOSOM_BPS = 512 * 1024
#: Nekaj zanesljivih javnih sledilnikov: dodamo jih samo, kadar magnet nima nobenega (hitrejše iskanje).
SLEDILNIKI = (
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://tracker.torrent.eu.org:451/announce",
)
NAJDALJSI_MAGNET = 8192
KOS = 256 * 1024

VIDEO = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".ts", ".m2ts", ".mpg", ".mpeg", ".wmv", ".flv", ".3gp", ".ogv"}
ZVOK = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wav", ".wma", ".alac", ".ape"}
PODNAPISI = {".srt", ".vtt", ".ass", ".ssa", ".sub"}
SLIKE = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
#: Kar bi se dalo pognati ali namestiti: tega Safeer nikoli ne odpre in privzeto ne prenese.
NEVARNE = {".exe", ".msi", ".scr", ".com", ".bat", ".cmd", ".ps1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".hta",
           ".lnk", ".pif", ".cpl", ".jar", ".apk", ".xapk", ".dll", ".sys", ".reg", ".sh", ".run", ".bin",
           ".appimage", ".desktop", ".deb", ".rpm", ".dmg", ".pkg", ".iso", ".img", ".url", ".chm", ".docm",
           ".xlsm", ".pptm"}


# ------------------------------------------------------------------ magnet

_BTIH = re.compile(r"urn:btih:([0-9a-fA-F]{40}|[A-Za-z2-7]{32})$")
_BTMH = re.compile(r"urn:btmh:1220[0-9a-fA-F]{64}$")


def razcleni_magnet(besedilo: str) -> Optional[dict]:
    """{"hash", "ime", "sledilniki", "uri"} ali None, če to ni veljavna magnet povezava za BitTorrent."""
    uri = str(besedilo or "").strip()
    if not uri.lower().startswith("magnet:?") or len(uri) > NAJDALJSI_MAGNET or any(c in uri for c in "\r\n\t "):
        return None
    parametri = urllib.parse.parse_qs(uri[len("magnet:?"):], keep_blank_values=False)
    hash_ = ""
    for xt in parametri.get("xt", []):
        m = _BTIH.match(xt)
        if m:
            h = m.group(1)
            hash_ = h.lower() if len(h) == 40 else base64.b32decode(h.upper()).hex()
            break
        if _BTMH.match(xt):
            hash_ = xt.split(":")[-1].lower()
            break
    if not hash_:
        return None
    sledilniki = [t for t in parametri.get("tr", []) if t.startswith(("udp://", "http://", "https://"))]
    ime = (parametri.get("dn") or [""])[0][:200]
    return {"hash": hash_, "ime": ime, "sledilniki": sledilniki, "uri": uri}


def z_sledilniki(uri: str) -> str:
    """Magnet brez sledilnikov dobi nekaj zanesljivih (hitrejše iskanje); ostalih ne spreminjamo."""
    m = razcleni_magnet(uri)
    if m is None or m["sledilniki"]:
        return uri
    return uri + "".join("&tr=" + urllib.parse.quote(t, safe="") for t in SLEDILNIKI)


def vrsta_datoteke(ime: str) -> str:
    k = os.path.splitext(str(ime or "").lower())[1]
    if k in VIDEO:
        return "video"
    if k in ZVOK:
        return "audio"
    if k in PODNAPISI:
        return "podnapisi"
    if k in SLIKE:
        return "slika"
    if k in NEVARNE:
        return "nevarno"
    return "drugo"


def razvrsti_datoteke(datoteke: List[dict]) -> List[dict]:
    """Datoteke torrenta za prikaz: indeks, ime, velikost, vrsta, ali se da predvajati in ali je privzeto izbrana.

    Privzeto izberemo samo predvajljive in podnapise; nevarne nikoli."""
    izid = []
    for i, d in enumerate(datoteke or []):
        if not isinstance(d, dict):
            continue
        attr = d.get("attributes") or {}
        if attr.get("padding"):
            continue
        ime = str(d.get("name") or "")
        vrsta = "nevarno" if attr.get("executable") or attr.get("symlink") else vrsta_datoteke(ime)
        izid.append({"i": i, "ime": ime, "velikost": int(d.get("length") or 0), "vrsta": vrsta,
                     "predvajljivo": vrsta in ("video", "audio"),
                     "izbrana": vrsta in ("video", "audio", "podnapisi")})
    return izid


def sumljiv(datoteke: List[dict]) -> bool:
    """Torrent, ki se predstavlja kot film ali glasba, a nosi program: klasična past z zlonamerno kodo."""
    vrste = {d["vrsta"] for d in datoteke}
    return "nevarno" in vrste


# ------------------------------------------------------------------ program rqbit

def platforma() -> str:
    stroj = platform.machine().lower()
    if sys.platform.startswith("win"):
        return "windows-amd64" if stroj in ("amd64", "x86_64") else ""
    if sys.platform.startswith("linux"):
        return {"x86_64": "linux-x86_64", "amd64": "linux-x86_64", "aarch64": "linux-aarch64",
                "arm64": "linux-aarch64"}.get(stroj, "")
    return ""


def _mapa_podatkov() -> str:
    if sys.platform.startswith("win"):
        return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Safeer")
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "safeer")


def mapa_programa() -> str:
    return os.path.join(_mapa_podatkov(), "rqbit", RQBIT_RAZLICICA)


def mapa_stanja() -> str:
    return os.path.join(_mapa_podatkov(), "rqbit", "stanje")


def mapa_prenosov() -> str:
    """Mapa Prejemi (XDG_DOWNLOAD_DIR, kot jo ima Mint) / Safeer; na Windows Downloads/Safeer."""
    doma = os.path.expanduser("~")
    prejemi = ""
    if not sys.platform.startswith("win"):
        try:
            with open(os.path.join(doma, ".config", "user-dirs.dirs"), encoding="utf-8") as d:
                for vrstica in d:
                    k, _, v = vrstica.strip().partition("=")
                    if k == "XDG_DOWNLOAD_DIR":
                        prejemi = v.strip().strip('"').replace("$HOME", doma)
        except OSError:
            pass
    return os.path.join(prejemi or os.path.join(doma, "Downloads"), "Safeer")


def pot_programa() -> str:
    paket = RQBIT_PAKETI.get(platforma())
    if not paket:
        return ""
    return os.path.join(mapa_programa(), "rqbit.exe" if paket[0].endswith(".exe") else "rqbit")


def _sha256(pot: str) -> str:
    h = hashlib.sha256()
    with open(pot, "rb") as d:
        for kos in iter(lambda: d.read(1 << 20), b""):
            h.update(kos)
    return h.hexdigest()


def program_na_voljo() -> bool:
    pot = pot_programa()
    paket = RQBIT_PAKETI.get(platforma())
    return bool(pot and paket and os.path.isfile(pot) and os.path.getsize(pot) == paket[2])


def prenesi_program(napredek: Optional[Callable[[int, int], None]] = None,
                    odpri: Callable = urllib.request.urlopen) -> str:
    """Prenese rqbit za to platformo z uradne izdaje in preveri SHA-256. Vrne pot ali dvigne napako."""
    paket = RQBIT_PAKETI.get(platforma())
    if not paket:
        raise RuntimeError("Ta platforma ni podprta")
    ime, pricakovan, velikost = paket
    cilj = pot_programa()
    os.makedirs(os.path.dirname(cilj), exist_ok=True)
    zacasna = cilj + ".part"
    h = hashlib.sha256()
    prebrano = 0
    zahteva = urllib.request.Request(RQBIT_URL.format(razlicica=RQBIT_RAZLICICA, ime=ime),
                                     headers={"User-Agent": "Safeer/1.0"})
    with odpri(zahteva, timeout=60) as odgovor, open(zacasna, "wb") as d:
        while True:
            kos = odgovor.read(KOS)
            if not kos:
                break
            prebrano += len(kos)
            if prebrano > velikost:
                break
            h.update(kos)
            d.write(kos)
            if napredek:
                napredek(prebrano, velikost)
    if prebrano != velikost or h.hexdigest() != pricakovan:
        os.remove(zacasna)
        raise RuntimeError("Preneseni program se ne ujema z uradno izdajo (SHA-256)")
    os.chmod(zacasna, 0o755)
    os.replace(zacasna, cilj)
    return cilj


# ------------------------------------------------------------------ motor

def _prosta_vrata() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class NapakaTorrenta(Exception):
    pass


class Torrenti:
    """Upravlja proces rqbit (samo 127.0.0.1, z geslom) in lokalni tok za predvajalnik."""

    def __init__(self, mapa_prenosov_: str = "", mapa_stanja_: str = "", program: str = "",
                 nastavitve: str = "") -> None:
        self.mapa_prenosov = mapa_prenosov_ or mapa_prenosov()
        self.mapa_stanja = mapa_stanja_ or mapa_stanja()
        self.program = program
        self._pot_nastavitev = nastavitve or os.path.join(os.path.dirname(self.mapa_stanja), "safeer.json")
        self._proces: Optional[subprocess.Popen] = None
        self.vrata = 0
        self._geslo = ""
        self._zaklep = threading.RLock()
        self._tokovi: Dict[str, Tuple[int, int]] = {}
        self._streznik: Optional[http.server.ThreadingHTTPServer] = None
        self.vrata_toka = 0
        self._deli_naprej: set = set(self._nalozi_nastavitve().get("deli_naprej", []))
        self._nadzor: Optional[threading.Thread] = None

    # -- nastavitve (katere torrente uporabnik izrecno deli naprej)

    def _nalozi_nastavitve(self) -> dict:
        try:
            with open(self._pot_nastavitev, encoding="utf-8") as d:
                p = json.load(d)
            return p if isinstance(p, dict) else {}
        except Exception:
            return {}

    def _shrani_nastavitve(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._pot_nastavitev), exist_ok=True)
            zacasna = self._pot_nastavitev + ".tmp"
            with open(zacasna, "w", encoding="utf-8") as d:
                json.dump({"deli_naprej": sorted(self._deli_naprej)}, d)
            os.replace(zacasna, self._pot_nastavitev)
        except OSError:
            pass

    # -- proces

    def tece(self) -> bool:
        return self._proces is not None and self._proces.poll() is None

    def zazeni(self) -> None:
        with self._zaklep:
            if self.tece():
                return
            program = self.program or pot_programa()
            if not program or not os.path.isfile(program):
                raise NapakaTorrenta("ni_programa")
            os.makedirs(self.mapa_prenosov, exist_ok=True)
            os.makedirs(self.mapa_stanja, exist_ok=True)
            self.vrata = _prosta_vrata()
            self._geslo = secrets.token_urlsafe(24)
            okolje = dict(os.environ, RQBIT_HTTP_BASIC_AUTH_USERPASS="safeer:" + self._geslo)
            ukaz = [program, "--http-api-listen-addr", "127.0.0.1:%d" % self.vrata, "--http-api-allow-create",
                    # Brez odpiranja vrat na usmerjevalniku (UPnP) in brez spletnega vmesnika navzven.
                    "--disable-upnp-port-forward",
                    "--peer-limit", str(NAJVEC_POVEZAV), "-t", str(NITI),
                    "--ratelimit-upload", str(ODDAJA_MED_PRENOSOM_BPS),
                    "server", "start", "--persistence-location", self.mapa_stanja, "--fastresume",
                    self.mapa_prenosov]
            dodatno = {}
            if sys.platform.startswith("win"):
                dodatno["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            else:
                dodatno["start_new_session"] = True
            self._proces = subprocess.Popen(ukaz, env=okolje, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL, **dodatno)
            for _ in range(100):
                time.sleep(0.1)
                if self._proces.poll() is not None:
                    raise NapakaTorrenta("program_se_je_ustavil")
                try:
                    koda, _ = self._api("GET", "/torrents", cas=2)
                    if koda == 200:
                        break
                except OSError:
                    continue
            else:
                self.ustavi()
                raise NapakaTorrenta("program_ne_odgovori")
            if self._nadzor is None:
                self._nadzor = threading.Thread(target=self._nadzoruj, name="safeer-torrent-nadzor", daemon=True)
                self._nadzor.start()

    def ustavi(self) -> None:
        with self._zaklep:
            p, self._proces = self._proces, None
            s, self._streznik = self._streznik, None
            self._tokovi.clear()
        if p is not None and p.poll() is None:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
        if s is not None:
            try:
                s.shutdown()
                s.server_close()
            except Exception:
                pass

    def _api(self, metoda: str, pot: str, telo: Optional[bytes] = None, cas: float = 30,
             glave: Optional[dict] = None) -> Tuple[int, bytes]:
        povezava = http.client.HTTPConnection("127.0.0.1", self.vrata, timeout=cas)
        try:
            g = {"Authorization": "Basic " + base64.b64encode(("safeer:" + self._geslo).encode()).decode()}
            g.update(glave or {})
            povezava.request(metoda, pot, body=telo, headers=g)
            r = povezava.getresponse()
            return r.status, r.read()
        finally:
            povezava.close()

    def _json(self, metoda: str, pot: str, telo: Optional[bytes] = None, cas: float = 30, **k) -> dict:
        self.zazeni()
        koda, podatki = self._api(metoda, pot, telo, cas, **k)
        if koda != 200:
            raise NapakaTorrenta("api_%d" % koda)
        try:
            return json.loads(podatki.decode("utf-8") or "{}")
        except ValueError:
            return {"besedilo": podatki.decode("utf-8", "replace")}

    # -- uporaba

    def preberi(self, magnet: str) -> dict:
        """Metapodatki magneta (ime in datoteke), brez prenosa vsebine."""
        m = razcleni_magnet(magnet)
        if m is None:
            raise NapakaTorrenta("ni_magnet")
        d = self._json("POST", "/torrents?overwrite=true&list_only=true", z_sledilniki(m["uri"]).encode(), cas=90)
        podrobno = d.get("details") or {}
        datoteke = razvrsti_datoteke(podrobno.get("files") or [])
        return {"hash": str(podrobno.get("info_hash") or m["hash"]), "ime": str(podrobno.get("name") or m["ime"]),
                "datoteke": datoteke, "sumljiv": sumljiv(datoteke), "uri": m["uri"]}

    def dodaj(self, magnet: str, izbrane: List[int], potrjene_nevarne: Iterable[int] = ()) -> int:
        """Začne prenos izbranih datotek; če torrent že teče, doda datoteke. Vrne id.

        Datoteko, ki je videti kot program, prenesemo samo, če jo je uporabnik po opozorilu izrecno
        potrdil (potrjene_nevarne): prepoznava je samodejna in se lahko zmoti, odločitev je njegova.
        Predvajamo je nikoli (tok() jo zavrne)."""
        opis = self.preberi(magnet)
        potrjene = {int(i) for i in potrjene_nevarne}
        dovoljene = {d["i"] for d in opis["datoteke"] if d["vrsta"] != "nevarno" or d["i"] in potrjene}
        izbrane = sorted({int(i) for i in izbrane} & dovoljene)
        if not izbrane:
            raise NapakaTorrenta("ni_izbranih")
        obstojeci = self._poisci(opis["hash"])
        if obstojeci is not None:
            tid, trenutne = obstojeci
            self._json("POST", "/torrents/%d/update_only_files" % tid,
                       json.dumps({"only_files": sorted(set(trenutne) | set(izbrane))}).encode(),
                       glave={"Content-Type": "application/json"})
            self._api("POST", "/torrents/%d/start" % tid)
            return tid
        pot = "/torrents?overwrite=true&only_files=" + ",".join(str(i) for i in izbrane)
        d = self._json("POST", pot, z_sledilniki(opis["uri"]).encode(), cas=90)
        if d.get("id") is None:
            raise NapakaTorrenta("ni_dodan")
        return int(d["id"])

    def _poisci(self, hash_: str) -> Optional[Tuple[int, List[int]]]:
        for t in self._json("GET", "/torrents").get("torrents") or []:
            if str(t.get("info_hash") or "").lower() == hash_.lower():
                tid = int(t.get("id"))
                podrobno = self._json("GET", "/torrents/%d" % tid)
                vkljucene = [i for i, f in enumerate(podrobno.get("files") or []) if f.get("included")]
                return tid, vkljucene
        return None

    def seznam(self) -> List[dict]:
        if not self.tece():
            # Prejšnji prenosi (fastresume) se pokažejo in nadaljujejo, ko uporabnik odpre magnet povezave.
            ima_stanje = os.path.isdir(self.mapa_stanja) and any(os.scandir(self.mapa_stanja))
            if not (ima_stanje and (self.program or program_na_voljo())):
                return []
            try:
                self.zazeni()
            except NapakaTorrenta:
                return []
        izid = []
        for t in self._json("GET", "/torrents").get("torrents") or []:
            tid = int(t.get("id"))
            try:
                s = self._json("GET", "/torrents/%d/stats/v1" % tid)
                podrobno = self._json("GET", "/torrents/%d" % tid)
            except NapakaTorrenta:
                continue
            ziv = (s.get("live") or {})
            hitrost = (ziv.get("download_speed") or {}).get("mbps") or 0
            oddaja = (ziv.get("upload_speed") or {}).get("mbps") or 0
            povezave = ((ziv.get("snapshot") or {}).get("peer_stats") or {}).get("live") or 0
            hash_ = str(t.get("info_hash") or "")
            datoteke = [f if isinstance(f, dict) else {} for f in (podrobno.get("files") or [])]
            izid.append({"id": tid, "hash": hash_, "ime": str(podrobno.get("name") or t.get("name") or ""),
                         "stanje": str(s.get("state") or ""), "koncano": bool(s.get("finished")),
                         "preneseno": int(s.get("progress_bytes") or 0), "skupaj": int(s.get("total_bytes") or 0),
                         "oddano": int(s.get("uploaded_bytes") or 0),
                         "hitrost_mibs": round(float(hitrost), 2), "oddaja_mibs": round(float(oddaja), 2),
                         "povezave": int(povezave), "deli_naprej": hash_ in self._deli_naprej,
                         "napaka": str(s.get("error") or ""),
                         "datoteke": [dict(d, vkljucena=bool(datoteke[d["i"]].get("included")))
                                      for d in razvrsti_datoteke(datoteke)],
                         "mapa": str(podrobno.get("output_folder") or ""),
                         # Lastna datoteka, ki jo uporabnik deli: je izven mape prenosov in je nikoli ne brišemo.
                         "lastna": not self._v_prenosih(str(podrobno.get("output_folder") or ""))})
        return izid

    def premor(self, tid: int) -> bool:
        return self._api("POST", "/torrents/%d/pause" % int(tid))[0] == 200 if self.tece() else False

    def nadaljuj(self, tid: int) -> bool:
        self.zazeni()
        return self._api("POST", "/torrents/%d/start" % int(tid))[0] == 200

    def _v_prenosih(self, mapa: str) -> bool:
        koren = os.path.realpath(self.mapa_prenosov)
        pot = os.path.realpath(os.path.join(koren, mapa)) if mapa else ""
        return bool(pot) and (pot == koren or pot.startswith(koren + os.sep))

    def odstrani(self, tid: int, z_datotekami: bool = False) -> bool:
        if not self.tece():
            return False
        if z_datotekami:
            # Brišemo samo prenesene datoteke v mapi prenosov - nikoli uporabnikovih izvirnikov, ki jih deli.
            podrobno = self._json("GET", "/torrents/%d" % int(tid))
            if not self._v_prenosih(str(podrobno.get("output_folder") or "")):
                return False
        return self._api("POST", "/torrents/%d/%s" % (int(tid), "delete" if z_datotekami else "forget"))[0] == 200

    def deli_naprej(self, hash_: str, vklop: bool) -> None:
        """Uporabnikova izrecna odločitev, da torrent po koncu prenosa oddaja drugim."""
        if vklop:
            self._deli_naprej.add(hash_.lower())
        else:
            self._deli_naprej.discard(hash_.lower())
        self._shrani_nastavitve()

    def magnet(self, tid: int) -> str:
        """Magnet povezava za pošiljanje (na drugo napravo ali drugim)."""
        for t in self._json("GET", "/torrents").get("torrents") or []:
            if int(t.get("id")) == int(tid):
                podrobno = self._json("GET", "/torrents/%d" % int(tid))
                ime = urllib.parse.quote(str(podrobno.get("name") or ""), safe="")
                return z_sledilniki("magnet:?xt=urn:btih:%s%s" % (t.get("info_hash"), "&dn=" + ime if ime else ""))
        raise NapakaTorrenta("ni_torrenta")

    def deli_datoteko(self, pot: str) -> str:
        """Iz uporabnikove datoteke ali mape naredi torrent, ga začne oddajati in vrne magnet povezavo."""
        pot = os.path.realpath(os.path.expanduser(str(pot or "")))
        if not os.path.exists(pot) or any(d.startswith(".") for d in pot.split(os.sep) if d):
            raise NapakaTorrenta("ni_datoteke")
        d = self._json("POST", "/torrents/create", pot.encode("utf-8"), cas=600)
        uri = str(d.get("magnet") or d.get("besedilo") or "").strip()
        m = razcleni_magnet(uri)
        if m is None:
            raise NapakaTorrenta("ni_magnet")
        self.deli_naprej(m["hash"], True)        # uporabnik ga je izrecno dal v deljenje
        return z_sledilniki(uri)

    # -- tok za predvajalnik

    def podnapisi_za(self, tid: int, i: int) -> List[Tuple[int, str]]:
        """Podnapisi iz istega torrenta, ki sodijo k videu `i` (ista mapa ali podmapa Subs): [(indeks, pot)]."""
        from core import podnapisi as pn
        datoteke = self._json("GET", "/torrents/%d" % int(tid)).get("files") or []

        def pot(f: dict) -> str:
            deli = f.get("components")
            return "/".join(str(x) for x in deli) if isinstance(deli, list) and deli else str(f.get("name") or "")
        poti = [pot(f) for f in datoteke]
        if not 0 <= int(i) < len(poti):
            return []
        mapa = poti[int(i)].rpartition("/")[0]
        predpona = mapa + "/" if mapa else ""
        relativno = {p[len(predpona):]: j for j, p in enumerate(poti) if p.startswith(predpona)}
        videov = sum(1 for r in relativno if "/" not in r and vrsta_datoteke(r) == "video")
        return [(relativno[r], predpona + r) for r in pn.ujemajoci(poti[int(i)], list(relativno), videov == 1)][:24]

    def tok(self, tid: int, i: int) -> str:
        """Lokalni naslov za predvajalnik: datoteka `i` torrenta `tid`, predvaja se že med prenosom."""
        self.zazeni()
        podrobno = self._json("GET", "/torrents/%d" % int(tid))
        datoteke = podrobno.get("files") or []
        if not 0 <= int(i) < len(datoteke) or vrsta_datoteke(datoteke[int(i)].get("name", "")) not in ("video", "audio", "podnapisi"):
            raise NapakaTorrenta("ni_predvajljivo")
        if not datoteke[int(i)].get("included"):
            vkljucene = [j for j, f in enumerate(datoteke) if f.get("included")] + [int(i)]
            self._json("POST", "/torrents/%d/update_only_files" % int(tid),
                       json.dumps({"only_files": sorted(set(vkljucene))}).encode(),
                       glave={"Content-Type": "application/json"})
        self._api("POST", "/torrents/%d/start" % int(tid))
        with self._zaklep:
            if self._streznik is None:
                s = _Streznik(("127.0.0.1", 0), _Obravnava)
                s.torrenti = self  # type: ignore[attr-defined]
                self._streznik = s
                self.vrata_toka = s.server_address[1]
                threading.Thread(target=s.serve_forever, name="safeer-torrent-tok", daemon=True).start()
            skrivnost = secrets.token_hex(16)
            self._tokovi[skrivnost] = (int(tid), int(i))
            while len(self._tokovi) > 256:
                self._tokovi.pop(next(iter(self._tokovi)))
        ime = str(datoteke[int(i)].get("name") or "")
        return "http://127.0.0.1:%d/t/%s/%s" % (self.vrata_toka, skrivnost, urllib.parse.quote(os.path.basename(ime)))

    # -- nadzor: po koncu prenosa ne oddajamo, razen če uporabnik tako izbere

    def _nadzoruj(self) -> None:
        while True:
            time.sleep(10)
            if not self.tece():
                continue
            try:
                for t in self._json("GET", "/torrents").get("torrents") or []:
                    hash_ = str(t.get("info_hash") or "").lower()
                    if hash_ in self._deli_naprej:
                        continue
                    s = self._json("GET", "/torrents/%d/stats/v1" % int(t.get("id")))
                    if s.get("finished") and s.get("state") == "live":
                        self._api("POST", "/torrents/%d/pause" % int(t.get("id")))
            except Exception:  # noqa: BLE001 - nadzor ne sme pasti
                continue


class _Streznik(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _Obravnava(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "SafeerTorrent"
    sys_version = ""

    def log_message(self, *_a) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        self._tok(False)

    def do_HEAD(self) -> None:  # noqa: N802
        self._tok(True)

    def _prazen(self, koda: int) -> None:
        self.send_response(koda)
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    def _tok(self, samo_glava: bool) -> None:
        torrenti: Torrenti = self.server.torrenti  # type: ignore[attr-defined]
        naslov = self.client_address[0] if self.client_address else ""
        if not naslov.startswith("127.") and naslov != "::1":
            self._prazen(403)
            return
        deli = urllib.parse.urlparse(self.path).path.split("/")
        cilj = torrenti._tokovi.get(deli[2]) if len(deli) >= 3 and deli[1] == "t" else None
        if cilj is None:
            self._prazen(404)
            return
        tid, i = cilj
        glave = {"Range": self.headers["Range"]} if self.headers.get("Range") else {}
        povezava = http.client.HTTPConnection("127.0.0.1", torrenti.vrata, timeout=120)
        try:
            glave["Authorization"] = "Basic " + base64.b64encode(("safeer:" + torrenti._geslo).encode()).decode()
            povezava.request("HEAD" if samo_glava else "GET", "/torrents/%d/stream/%d" % (tid, i), headers=glave)
            r = povezava.getresponse()
            self.send_response(r.status)
            for ime in ("Content-Length", "Content-Range", "Accept-Ranges"):
                if r.getheader(ime):
                    self.send_header(ime, r.getheader(ime))
            vrsta = "video/mp4"
            k = os.path.splitext(deli[-1].lower())[1]
            vrsta = {".mkv": "video/x-matroska", ".webm": "video/webm", ".mp3": "audio/mpeg", ".flac": "audio/flac",
                     ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".opus": "audio/ogg", ".wav": "audio/wav",
                     ".avi": "video/x-msvideo", ".mov": "video/quicktime"}.get(k, vrsta if k in VIDEO else "application/octet-stream")
            self.send_header("Content-Type", vrsta)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            if samo_glava:
                return
            while True:
                kos = r.read(KOS)
                if not kos:
                    break
                self.wfile.write(kos)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            povezava.close()


_TORRENTI: Optional[Torrenti] = None
_TORRENTI_ZAKLEP = threading.Lock()


def torrenti() -> Torrenti:
    global _TORRENTI
    with _TORRENTI_ZAKLEP:
        if _TORRENTI is None:
            _TORRENTI = Torrenti()
        return _TORRENTI
