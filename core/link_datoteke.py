"""Deljene mape Safeer Controla za televizor (Safeer OS) in druge naprave v Safeer Linku.

Uporabnik na racunalniku izbere mape, ki jih sme videti televizor (privzeto nobene). Seznam map
gre prek Safeer Linka (ukaz daljinca `files.list`), same datoteke pa neposredno z racunalnika po
HTTPS: Control ima majhen streznik datotek s samopodpisanim potrdilom, katerega odtis dobi
naprava skupaj z naslovom in enkratnim zetonom v odgovoru na `files.list`. Streznik se zazene
sele ob prvi zahtevi in poslusa na nakljucnih vratih; brez zetona ne vrne nicesar.

Naprava nikoli ne vidi poti na racunalniku: mape in datoteke imajo navidezne oznake
`share:<st. mape>:<relativna pot>` (zamisel iz PoC-ja Safeer OS). Pot se vedno razresi znotraj
izbrane mape (simbolne povezave navzven ne pridejo skozi), skrite datoteke se ne kazejo.
"""

from __future__ import annotations

import hashlib
import hmac
import http.server
import json
import mimetypes
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import threading
import time
import unicodedata
import urllib.parse
from typing import Dict, List, Optional, Tuple

from core import link_urejanje

NAJVEC_VNOSOV = 500
NAJVEC_TELESA = 64 * 1024
#: Kaj naprava sme narediti z datoteko racunalnika (POST /d/<id>, telo JSON {"op": ...}).
UKAZI = ("delete", "rename", "move", "rotate")
VELIKOST_KOSA = 256 * 1024
TLS_MAPA = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "safeer-control", "tls")

# Kaj televizor zna predvajati ali pokazati; drugo se kaze kot navadna datoteka.
VRSTE = {
    "video": {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".ts", ".m2ts", ".mpg", ".mpeg", ".3gp"},
    "audio": {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wav", ".wma"},
    "image": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic"},
}


def vrsta_datoteke(ime: str) -> str:
    k = os.path.splitext(ime)[1].lower()
    for vrsta, koncnice in VRSTE.items():
        if k in koncnice:
            return vrsta
    return "file"


def _besede(s: str) -> List[str]:
    """Besede za iskanje: male crke brez sumnikov in locil (»Čudežna_Šola« -> ["cudezna", "sola"])."""
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return [b for b in "".join(c if c.isalnum() else " " for c in s).split() if b]


def _xdg_mape_medijev() -> List[str]:
    """Uporabnikove mape Glasba, Videoposnetki in Prejemi (~/.config/user-dirs.dirs, kot jih ima Mint)."""
    doma = os.path.expanduser("~")
    mape = {"XDG_MUSIC_DIR": "Music", "XDG_VIDEOS_DIR": "Videos", "XDG_DOWNLOAD_DIR": "Downloads"}
    najdene = {}
    try:
        with open(os.path.join(doma, ".config", "user-dirs.dirs"), encoding="utf-8") as d:
            for vrstica in d:
                k, _, v = vrstica.strip().partition("=")
                if k in mape:
                    najdene[k] = v.strip().strip('"').replace("$HOME", doma)
    except OSError:
        pass
    poti = [najdene.get(k) or os.path.join(doma, privzeto) for k, privzeto in mape.items()]
    return [os.path.realpath(p) for p in poti if os.path.isdir(p) and os.path.realpath(p) != doma]


def _ujema(beseda: str, besede: List[str]) -> bool:
    return any(b == beseda or (len(beseda) >= 3 and b.startswith(beseda)) for b in besede)


def _skrita(pot: str) -> bool:
    """Ali pot vodi skozi skrito mapo ali do skrite datoteke (`.ssh`, `.gnupg`, `.mozilla` ...).

    Seznam jih ne kaze; tudi ce naprava ime ugane, jih ne damo: tam so kljuci, gesla in piskotki."""
    return any(del_.startswith(".") for del_ in pot.replace(os.sep, "/").split("/") if del_)


class DeljeneMape:
    """Izbrane mape (absolutne poti) in navidezne oznake.

    Poleg izbranih map zna - **samo ce uporabnik to izrecno vklopi** - pokazati tudi cel
    datotecni sistem tega racunalnika (oznake `disk:<absolutna pot>`). Privzeto je izklopljeno:
    televizor brez te izbire vidi natanko tiste mape, ki mu jih je uporabnik dal.
    """

    #: Mape, ki na korenu niso za uporabnika (jedro, naprave) in jih ne kazemo.
    SISTEMSKE = {"proc", "sys", "dev", "run", "lost+found"}

    def __init__(self, poti: Optional[List[str]] = None, ves_disk: bool = False) -> None:
        self.poti: List[str] = []
        self.ves_disk = bool(ves_disk)
        self.nastavi(poti or [])

    def nastavi(self, poti: List[str]) -> None:
        cista: List[str] = []
        for p in poti:
            p = os.path.realpath(os.path.expanduser(str(p)))
            if os.path.isdir(p) and p not in cista:
                cista.append(p)
        self.poti = cista

    def koren(self) -> List[dict]:
        vnosi = [{"id": f"share:{i}:", "name": os.path.basename(p) or p, "type": "folder"}
                 for i, p in enumerate(self.poti)]
        if self.ves_disk:
            dom = os.path.realpath(os.path.expanduser("~"))
            vnosi.append({"id": "disk:" + dom, "name": os.path.basename(dom) or dom, "type": "folder"})
            vnosi.append({"id": "disk:/", "name": "/", "type": "folder"})
        return vnosi

    def razresi(self, oznaka: str) -> Optional[Tuple[int, str]]:
        """`share:<i>:<rel>` -> (i, absolutna pot) ali None, ce oznaka ni veljavna ali kaze ven iz mape.

        `disk:<absolutna pot>` -> (-1, pot), a samo kadar je brskanje po celem racunalniku
        vklopljeno; sicer oznaka ne pomeni nicesar.
        """
        oznaka = str(oznaka or "")
        if oznaka.startswith("disk:"):
            if not self.ves_disk:
                return None
            pot = os.path.realpath(oznaka[len("disk:"):] or "/")
            if _skrita(pot):
                return None
            return (-1, pot) if os.path.exists(pot) else None
        deli = str(oznaka or "").split(":", 2)
        if len(deli) != 3 or deli[0] != "share":
            return None
        try:
            i = int(deli[1])
            koren = self.poti[i]
        except (ValueError, IndexError):
            return None
        rel = deli[2].replace("\\", "/").lstrip("/")
        pot = os.path.realpath(os.path.join(koren, rel)) if rel else koren
        if pot != koren and not pot.startswith(koren + os.sep):
            return None
        if pot != koren and _skrita(os.path.relpath(pot, koren)):
            return None
        return (i, pot) if os.path.exists(pot) else None

    def oznaka_poti(self, pot: str) -> str:
        """Obratno od `razresi`: absolutna pot -> `share:<i>:<rel>` (ali `disk:<pot>`, ce je ves disk vklopljen)."""
        pot = os.path.realpath(pot)
        for i, koren in enumerate(self.poti):
            if pot == koren:
                return f"share:{i}:"
            if pot.startswith(koren + os.sep):
                return f"share:{i}:" + os.path.relpath(pot, koren).replace(os.sep, "/")
        return "disk:" + pot if self.ves_disk else ""

    def seznam(self, oznaka: str) -> Optional[List[dict]]:
        if oznaka in ("", "root"):
            return self.koren()
        r = self.razresi(oznaka)
        if r is None:
            return None
        i, pot = r
        if not os.path.isdir(pot):
            return None
        if i < 0:
            return self._seznam_diska(pot)
        koren = self.poti[i]
        try:
            imena = sorted(os.listdir(pot), key=lambda s: s.lower())
        except OSError:
            return None
        vnosi: List[dict] = []
        for ime in imena:
            if ime.startswith("."):
                continue
            cela = os.path.join(pot, ime)
            try:
                mapa = os.path.isdir(cela)
                if not mapa and not os.path.isfile(cela):
                    continue
                rel = os.path.relpath(os.path.realpath(cela), koren).replace(os.sep, "/")
                if rel.startswith(".."):
                    continue  # simbolna povezava ven iz deljene mape
                v = {"id": f"share:{i}:{rel}", "name": ime, "type": "folder" if mapa else vrsta_datoteke(ime)}
                if not mapa:
                    v["size"] = os.path.getsize(cela)
                    v["mime"] = mimetypes.guess_type(ime)[0] or "application/octet-stream"
                vnosi.append(v)
            except OSError:
                continue
        # Mape najprej, potem datoteke; najvec NAJVEC_VNOSOV.
        vnosi.sort(key=lambda v: (v["type"] != "folder", v["name"].lower()))
        return vnosi[:NAJVEC_VNOSOV]

    def isci(self, poizvedba: str, najvec: int = 30, rok_s: float = 3.0, najvec_pregledanih: int = 60000) -> List[dict]:
        """Glasba in videi v deljenih mapah, v katerih poti (mape + ime) so vse besede poizvedbe.

        Enotno iskanje Safeer Media (`files.search`): televizor isce »Pink Floyd Time« in najde
        `Glasba/Pink Floyd/04 - Time.flac`. Samo deljene mape (ne ves disk), brez skritih map in
        povezav ven; omejeno s casom in stevilom pregledanih datotek, da racunalnik ne obremeni.
        Najboljsi najprej: besede v imenu datoteke stejejo vec kot besede v imenih map.
        """
        iscem = [b for b in _besede(str(poizvedba or ""))]
        # Ves racunalnik za TV: poleg deljenih map se uporabnikove mape z mediji (ne cel disk - prepocasno).
        korenine = [(i, k) for i, k in enumerate(self.poti)]
        if self.ves_disk:
            korenine += [(-1, k) for k in _xdg_mape_medijev() if not any(k == p or k.startswith(p + os.sep) for p in self.poti)]
        if not iscem or not korenine:
            return []
        konec = time.monotonic() + rok_s
        pregledanih = 0
        zadetki = []
        for i, koren in korenine:
            for mapa, podmape, datoteke in os.walk(koren, followlinks=False):
                podmape[:] = [d for d in podmape if not d.startswith(".")]
                rel_mapa = os.path.relpath(mapa, koren)
                rel_mapa = "" if rel_mapa == "." else rel_mapa.replace(os.sep, "/")
                besede_mape = _besede(rel_mapa)
                for ime in datoteke:
                    pregledanih += 1
                    if pregledanih > najvec_pregledanih or time.monotonic() > konec:
                        break
                    if ime.startswith("."):
                        continue
                    vrsta = vrsta_datoteke(ime)
                    if vrsta not in ("audio", "video"):
                        continue
                    besede_imena = _besede(os.path.splitext(ime)[0])
                    if not all(_ujema(b, besede_imena) or _ujema(b, besede_mape) for b in iscem):
                        continue
                    cela = os.path.join(mapa, ime)
                    rel = os.path.relpath(os.path.realpath(cela), koren).replace(os.sep, "/")
                    if rel.startswith("..") or _skrita(rel):
                        continue  # simbolna povezava ven iz deljene mape ali v skrito mapo
                    ocena = sum(1.0 if _ujema(b, besede_imena) else 0.8 for b in iscem)
                    try:
                        velikost = os.path.getsize(cela)
                    except OSError:
                        continue
                    zadetki.append((-ocena, ime.lower(), {
                        "id": f"share:{i}:{rel}" if i >= 0 else "disk:" + os.path.realpath(cela), "name": ime, "type": vrsta, "size": velikost,
                        "mime": mimetypes.guess_type(ime)[0] or "application/octet-stream", "path": rel_mapa}))
                else:
                    continue
                break
        zadetki.sort(key=lambda z: (z[0], z[1]))
        return [z[2] for z in zadetki[:najvec]]

    def _seznam_diska(self, pot: str) -> Optional[List[dict]]:
        """Vsebina mape kjerkoli na racunalniku (oznake `disk:`). Skrite datoteke ostanejo skrite,
        na korenu pa izpustimo mape jedra in naprav - tam za uporabnika ni nicesar."""
        try:
            imena = sorted(os.listdir(pot), key=lambda s: s.lower())
        except OSError:
            return None
        na_korenu = os.path.realpath(pot) == os.sep
        vnosi: List[dict] = []
        for ime in imena:
            if ime.startswith("."):
                continue
            if na_korenu and ime in self.SISTEMSKE:
                continue
            cela = os.path.join(pot, ime)
            try:
                mapa = os.path.isdir(cela)
                if not mapa and not os.path.isfile(cela):
                    continue
                v = {"id": "disk:" + os.path.realpath(cela), "name": ime,
                     "type": "folder" if mapa else vrsta_datoteke(ime)}
                if not mapa:
                    v["size"] = os.path.getsize(cela)
                    v["mime"] = mimetypes.guess_type(ime)[0] or "application/octet-stream"
                vnosi.append(v)
            except OSError:
                continue
        vnosi.sort(key=lambda v: (v["type"] != "folder", v["name"].lower()))
        return vnosi[:NAJVEC_VNOSOV]


# ------------------------------------------------------------------ TLS

def zagotovi_potrdilo(mapa: str = TLS_MAPA) -> Tuple[str, str, str]:
    """Samopodpisano potrdilo Controla (kljuc, potrdilo, odtis SHA-256 DER). Ustvari ga z openssl ob prvi rabi."""
    os.makedirs(mapa, exist_ok=True)
    try:
        os.chmod(mapa, 0o700)
    except OSError:
        pass
    kljuc, potrdilo = os.path.join(mapa, "kljuc.pem"), os.path.join(mapa, "potrdilo.pem")
    if not (os.path.isfile(kljuc) and os.path.isfile(potrdilo)):
        ime = socket.gethostname().split(".")[0] or "safeer-control"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                        "-nodes", "-days", "3650", "-subj", f"/CN=Safeer Control {ime}",
                        "-keyout", kljuc, "-out", potrdilo], check=True, capture_output=True)
        os.chmod(kljuc, 0o600)
    with open(potrdilo, "rb") as d:
        der = ssl.PEM_cert_to_DER_cert(d.read().decode("ascii"))
    return kljuc, potrdilo, hashlib.sha256(der).hexdigest()


# ------------------------------------------------------------------ streznik

class _Obravnava(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "SafeerControl"
    sys_version = ""

    def log_message(self, oblika, *argumenti):  # noqa: D401 - tiho
        return

    def _zeton(self) -> Optional[str]:
        # Samo glava: zeton v naslovu (?t=) bi ostal v dnevnikih, zgodovini in glavi Referer.
        z = self.headers.get("X-Safeer-Token")
        return z.strip() if z else None

    def do_HEAD(self):  # noqa: N802
        self._datoteka(samo_glava=True)

    def do_GET(self):  # noqa: N802
        self._datoteka(samo_glava=False)

    def do_POST(self):  # noqa: N802
        """Urejanje datoteke z naprave: `{"op": "delete"|"rename"|"move"|"rotate", ...}` z istim zetonom kot prenos."""
        streznik: StreznikDatotek = self.server.streznik  # type: ignore[attr-defined]
        u = urllib.parse.urlparse(self.path)
        if not u.path.startswith("/d/"):
            self._napaka(404, "ni take poti")
            return
        if not streznik.zeton_velja(self._zeton()):
            self._napaka(401, "manjka ali napacen zeton")
            return
        try:
            dolzina = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            dolzina = -1
        if dolzina < 0 or dolzina > NAJVEC_TELESA:
            self._napaka(413, "predolgo telo")
            return
        try:
            zahteva = json.loads(self.rfile.read(dolzina).decode("utf-8") or "{}")
            if not isinstance(zahteva, dict):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            self._napaka(400, "telo ni JSON")
            return
        oznaka = urllib.parse.unquote(u.path[3:])
        koda, odgovor = streznik.uredi(oznaka, zahteva)
        telo = json.dumps(odgovor).encode("utf-8")
        self.send_response(koda)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(telo)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(telo)

    def _napaka(self, koda: int, besedilo: str) -> None:
        telo = json.dumps({"napaka": besedilo}).encode("utf-8")
        self.send_response(koda)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(telo)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(telo)

    def _datoteka(self, samo_glava: bool) -> None:
        streznik: StreznikDatotek = self.server.streznik  # type: ignore[attr-defined]
        u = urllib.parse.urlparse(self.path)
        if not u.path.startswith("/d/"):
            self._napaka(404, "ni take poti")
            return
        if not streznik.zeton_velja(self._zeton()):
            self._napaka(401, "manjka ali napacen zeton")
            return
        oznaka = urllib.parse.unquote(u.path[3:])
        r = streznik.mape.razresi(oznaka)
        if r is None or not os.path.isfile(r[1]):
            self._napaka(404, "datoteke ni")
            return
        pot = r[1]
        velikost = os.path.getsize(pot)
        vrsta = mimetypes.guess_type(pot)[0] or "application/octet-stream"
        zacetek, konec = 0, velikost - 1
        obseg = self.headers.get("Range")
        delni = False
        if obseg and obseg.startswith("bytes="):
            try:
                a, b = obseg[6:].split("-", 1)
                if a == "" and b:
                    zacetek = max(0, velikost - int(b))
                else:
                    zacetek = int(a)
                    if b:
                        konec = min(velikost - 1, int(b))
                delni = True
            except ValueError:
                delni = False
            if delni and (zacetek > konec or zacetek >= velikost):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{velikost}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        dolzina = konec - zacetek + 1
        self.send_response(206 if delni else 200)
        self.send_header("Content-Type", vrsta)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(dolzina))
        if delni:
            self.send_header("Content-Range", f"bytes {zacetek}-{konec}/{velikost}")
        self.send_header("Cache-Control", "private, max-age=0")
        self.end_headers()
        if samo_glava:
            return
        try:
            with open(pot, "rb") as d:
                d.seek(zacetek)
                ostane = dolzina
                while ostane > 0:
                    kos = d.read(min(VELIKOST_KOSA, ostane))
                    if not kos:
                        break
                    self.wfile.write(kos)
                    ostane -= len(kos)
        except (BrokenPipeError, ConnectionResetError):
            pass


class _Streznik(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class StreznikDatotek:
    """HTTPS streznik datotek Controla: zazene se ob prvi rabi, na nakljucnih vratih, samo za naprave z zetonom."""

    def __init__(self, mape: DeljeneMape, tls_mapa: str = TLS_MAPA) -> None:
        self.mape = mape
        self.tls_mapa = tls_mapa
        self.odtis = ""
        self.vrata = 0
        self._zetoni: Dict[str, str] = {}   # zeton -> id naprave
        self._streznik: Optional[_Streznik] = None
        self._nit: Optional[threading.Thread] = None
        self._kljucavnica = threading.Lock()

    def tece(self) -> bool:
        return self._streznik is not None

    def zazeni(self) -> None:
        with self._kljucavnica:
            if self._streznik is not None:
                return
            kljuc, potrdilo, self.odtis = zagotovi_potrdilo(self.tls_mapa)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(potrdilo, kljuc)
            s = _Streznik(("0.0.0.0", 0), _Obravnava)
            s.socket = ctx.wrap_socket(s.socket, server_side=True)
            s.streznik = self  # type: ignore[attr-defined]
            self.vrata = s.server_address[1]
            self._streznik = s
            self._nit = threading.Thread(target=s.serve_forever, name="safeer-datoteke", daemon=True)
            self._nit.start()

    def ustavi(self) -> None:
        with self._kljucavnica:
            s = self._streznik
            self._streznik = None
        if s is not None:
            try:
                s.shutdown()
                s.server_close()
            except Exception:
                pass
        self._zetoni.clear()
        self.vrata = 0

    def zeton_za(self, id_naprave: str) -> str:
        """Isti zeton za isto napravo, dokler Control tece; nov Control = novi zetoni."""
        for z, n in self._zetoni.items():
            if n == id_naprave:
                return z
        z = secrets.token_urlsafe(24)
        self._zetoni[z] = id_naprave
        return z

    def zeton_velja(self, zeton: Optional[str]) -> bool:
        # Primerjava v stalnem casu: iz casa odgovora se ne da uganiti, koliko znakov se ujema.
        return bool(zeton) and any(hmac.compare_digest(zeton.encode(), z.encode()) for z in list(self._zetoni))

    def osnova(self, naslov_racunalnika: str) -> str:
        return f"https://{naslov_racunalnika}:{self.vrata}"

    def uredi(self, oznaka: str, zahteva: dict) -> Tuple[int, dict]:
        """Izvede ukaz nad datoteko; vrne (HTTP koda, odgovor). Napake so kratke kode za napravo."""
        ukaz = str(zahteva.get("op") or "")
        if ukaz not in UKAZI:
            return 400, {"ok": False, "napaka": "neznan_ukaz"}
        r = self.mape.razresi(oznaka)
        if r is None:
            return 404, {"ok": False, "napaka": "ni_datoteke"}
        i, pot = r
        if i >= 0 and pot == self.mape.poti[i]:
            return 403, {"ok": False, "napaka": "ni_dovoljeno"}  # deljene mape same ne brisemo in ne preimenujemo
        if i < 0 and pot in (os.sep, os.path.realpath(os.path.expanduser("~"))):
            return 403, {"ok": False, "napaka": "ni_dovoljeno"}
        try:
            if ukaz == "delete":
                link_urejanje.v_smeti(pot)
                return 200, {"ok": True, "op": ukaz}
            if ukaz == "rename":
                nova = link_urejanje.preimenuj(pot, str(zahteva.get("name") or ""))
            elif ukaz == "move":
                cilj = self.mape.razresi(str(zahteva.get("folder") or ""))
                if cilj is None:
                    return 404, {"ok": False, "napaka": "ni_mape"}
                nova = link_urejanje.premakni(pot, cilj[1])
            else:
                if os.path.isdir(pot) or vrsta_datoteke(pot) != "image":
                    return 400, {"ok": False, "napaka": "ni_slike"}
                nacin = link_urejanje.zavrti(pot, int(zahteva.get("degrees") or 0))
                return 200, {"ok": True, "op": ukaz, "id": oznaka, "how": nacin, "size": os.path.getsize(pot)}
        except link_urejanje.NapakaUrejanja as e:
            return 409 if str(e) == "obstaja" else 400, {"ok": False, "napaka": str(e)}
        except (ValueError, TypeError):
            return 400, {"ok": False, "napaka": "napacna_zahteva"}
        return 200, {"ok": True, "op": ukaz, "id": self.mape.oznaka_poti(nova), "name": os.path.basename(nova)}


class Datoteke:
    """Vse, kar Safeer Control potrebuje za deljenje datotek: izbrane mape, streznik, odgovor na `files.list`."""

    ZMOZNOST = "files"

    def __init__(self, poti: Optional[List[str]] = None, tls_mapa: str = TLS_MAPA,
                 ves_disk: bool = False) -> None:
        self.mape = DeljeneMape(poti, ves_disk=ves_disk)
        self.streznik = StreznikDatotek(self.mape, tls_mapa)
        # Klicatelj (Control) ga nastavi, da spremembo map shrani in stran osvezi.
        self.ob_spremembi: Optional[callable] = None

    def poti(self) -> List[str]:
        return list(self.mape.poti)

    def nastavi(self, poti: List[str]) -> None:
        self.mape.nastavi(poti)
        if self.ob_spremembi is not None:
            try:
                self.ob_spremembi(self.poti())
            except Exception:
                pass

    def dodaj(self, pot: str) -> None:
        self.nastavi(self.poti() + [pot])

    def odstrani(self, i: int) -> None:
        p = self.poti()
        if 0 <= i < len(p):
            del p[i]
            self.nastavi(p)

    def odpri(self, oznaka: str) -> bool:
        """Odpre datoteko ali mapo **na racunalniku**, s programom, ki ga ima uporabnik zanjo
        (xdg-open). Dovoljene so samo oznake, ki jih naprava ze sme videti - drugega ne odpremo,
        in nikoli ne izvajamo ukazov, ki bi jih naprava poslala."""
        r = self.mape.razresi(str(oznaka or ""))
        if r is None:
            return False
        pot = r[1]
        if not os.path.exists(pot):
            return False
        odpiralnik = shutil.which("xdg-open") or shutil.which("gio")
        if not odpiralnik:
            return False
        ukaz = [odpiralnik, pot] if odpiralnik.endswith("xdg-open") else [odpiralnik, "open", pot]
        try:
            subprocess.Popen(ukaz, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            return True
        except Exception:
            return False

    def nastavi_ves_disk(self, vklopljeno: bool) -> None:
        """Televizor sme (ali ne sme vec) brskati po celem racunalniku. Velja takoj."""
        self.mape.ves_disk = bool(vklopljeno)

    def ustavi(self) -> None:
        self.streznik.ustavi()

    def seznam(self, oznaka: str, id_naprave: str, hub_url: str = "") -> dict:
        """Odgovor na ukaz `files.list` (podatki v `control.result`).

        `items` je seznam vnosov (mape najprej), `folder` oznaka mape, `shared` pove, ali je
        na racunalniku sploh izbrana kaksna mapa; `server` (naslov, odtis, zeton) je tu samo,
        ce je kaj datotek za prenasati - streznik se zazene sele takrat.
        """
        oznaka = str(oznaka or "")
        # Brez izbranih map in brez dovoljenja za cel racunalnik ni kaj pokazati.
        if not self.mape.poti and not self.mape.ves_disk:
            return {"items": [], "folder": "", "shared": False}
        vnosi = self.mape.seznam(oznaka)
        if vnosi is None:
            raise FileNotFoundError("Te mape ni (vec) med deljenimi")
        # `edit`: naprava sme datoteke te mape brisati (v Smeti), preimenovati, premakniti in vrteti slike (POST /d/<id>).
        o: dict = {"items": vnosi, "folder": oznaka if oznaka != "root" else "", "shared": True, "edit": oznaka not in ("", "root")}
        if any(v.get("type") != "folder" for v in vnosi):
            return _odgovor_z_streznikom(self, o, id_naprave, hub_url)
        return o

    def isci(self, poizvedba: str, id_naprave: str, hub_url: str = "") -> dict:
        """Odgovor na `files.search`: ista oblika kot `files.list` (items, shared, server)."""
        if not self.mape.poti and not self.mape.ves_disk:
            return {"items": [], "shared": False}
        o: dict = {"items": self.mape.isci(poizvedba), "shared": True}
        if o["items"]:
            return _odgovor_z_streznikom(self, o, id_naprave, hub_url)
        return o


def _odgovor_z_streznikom(datoteke: "Datoteke", o: dict, id_naprave: str, hub_url: str) -> dict:
    datoteke.streznik.zazeni()
    naslov = naslov_do_huba(hub_url) if hub_url else krajevni_naslov()
    o["server"] = {"base_url": datoteke.streznik.osnova(naslov), "fp": datoteke.streznik.odtis,
                   "token": datoteke.streznik.zeton_za(id_naprave or "naprava")}
    return o


def krajevni_naslov() -> str:
    """Naslov tega racunalnika v domacem omrezju (tisti, prek katerega pridemo do sredisca)."""
    for cilj in ("192.0.2.1", "10.255.255.255"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((cilj, 9))
            naslov = s.getsockname()[0]
            s.close()
            if naslov and not naslov.startswith("127."):
                return naslov
        except OSError:
            continue
    return "127.0.0.1"


def naslov_do_huba(hub_url: str) -> str:
    """Naslov tega racunalnika, kot ga vidi sredisce: vticnica proti hubu pove, kateri vmesnik je pravi."""
    try:
        u = urllib.parse.urlparse(hub_url)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((u.hostname or "127.0.0.1", u.port or 443))
        naslov = s.getsockname()[0]
        s.close()
        if naslov and not naslov.startswith("127."):
            return naslov
    except OSError:
        pass
    return krajevni_naslov()
