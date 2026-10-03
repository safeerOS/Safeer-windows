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
import http.client
import http.server
import json
import mimetypes
import os
import re
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

from core import link_tls, link_urejanje

NAJVEC_VNOSOV = 500
NAJVEC_TELESA = 64 * 1024
#: Kaj naprava sme narediti z datoteko racunalnika (POST /d/<id>, telo JSON {"op": ...}).
UKAZI = ("delete", "rename", "move", "rotate")
VELIKOST_KOSA = 256 * 1024
#: Zeton za prenos velja 12 ur od zadnje rabe; nato mora naprava znova po seznam.
ZETON_VELJA_S = 12 * 3600.0
NAJVEC_ZETONOV = 64
#: Zgornja meja zivljenja zetona, tudi ce ga naprava ves cas rabi.
NAJDLJE_S = 7 * 24 * 3600.0


def _umaknjena_iz_kroga(id_naprave: str) -> bool:
    try:
        from core import link_krog
        return link_krog.je_umaknjen(id_naprave)
    except Exception:
        return False


def _zeton_zivi(izdan: float, rabljen: float, zdaj: float) -> bool:
    return zdaj - rabljen < ZETON_VELJA_S and zdaj - izdan < NAJDLJE_S
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
            if os.name == "nt":
                # Windows nima enega korena: pokažemo vse dejansko priklopljene črke diskov.
                for crka in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                    disk = crka + ":\\"
                    if os.path.exists(disk) and os.path.realpath(disk) != dom:
                        vnosi.append({"id": "disk:" + disk, "name": disk, "type": "folder"})
            else:
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

    def podnapisi(self, oznaka_videa: str) -> List[dict]:
        """Podnapisi ob videu (ista mapa ali podmapa Subs), vsak s svojo oznako znotraj deljene mape."""
        from core import podnapisi as pn
        r = self.razresi(oznaka_videa)
        if r is None or not os.path.isfile(r[1]):
            return []
        izid = []
        for pot in pn.podnapisi_mape(r[1]):
            oz = self.oznaka_poti(pot)
            if oz and self.razresi(oz) is not None:
                izid.append(pn.opis(r[1], pot, oz))
        return izid

    def dodaj_podnapise(self, vnosi: List[dict]) -> List[dict]:
        """Videom v seznamu pripne `subtitles` (starejše naprave polje preprosto prezrejo)."""
        for v in vnosi:
            if v.get("type") == "video":
                try:
                    p = self.podnapisi(v["id"])
                except OSError:
                    p = []
                if p:
                    v["subtitles"] = p
        return vnosi

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
    """Samopodpisano potrdilo Controla (kljuc, potrdilo, odtis SHA-256 DER). Ustvari ga ob prvi rabi (core.link_kripto)."""
    os.makedirs(mapa, exist_ok=True)
    try:
        os.chmod(mapa, 0o700)
    except OSError:
        pass
    kljuc, potrdilo = os.path.join(mapa, "kljuc.pem"), os.path.join(mapa, "potrdilo.pem")
    if not (os.path.isfile(kljuc) and os.path.isfile(potrdilo)):
        ime = socket.gethostname().split(".")[0] or "safeer-control"
        from core import link_kripto
        link_kripto.ustvari_kljuc_in_potrdilo(kljuc, potrdilo, ime)
        try:
            os.chmod(kljuc, 0o600)
        except OSError:
            pass
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
        if u.path.startswith("/m/"):
            # Torrent, ki ga za napravo (npr. televizor) prenasa in pretaka ta racunalnik.
            posreduj_tok(self, streznik, u.path.split("/")[2] if len(u.path.split("/")) > 2 else "", samo_glava)
            return
        if u.path.startswith("/live/"):
            # Sprotno pretvorjeni tok za napravo, ki izvirnika ne zna predvajati (link_sprotno): zeton kot pri datotekah.
            z = self.headers.get("X-Safeer-Token")
            if not streznik.zeton_velja(z.strip() if z else None):
                self._napaka(401, "manjka ali napacen zeton")
                return
            from core import link_sprotno
            (getattr(streznik, "sprotno", None) or link_sprotno.sprotno()).postrezi(self, u.path[6:].split("/")[0], samo_glava)
            return
        if not u.path.startswith("/d/"):
            self._napaka(404, "ni take poti")
            return
        postrezi_datoteko(self, streznik, urllib.parse.unquote(u.path[3:]), samo_glava)


def _napaka_http(obravnava, koda: int, besedilo: str) -> None:
    telo = json.dumps({"napaka": besedilo}).encode("utf-8")
    obravnava.send_response(koda)
    obravnava.send_header("Content-Type", "application/json")
    obravnava.send_header("Content-Length", str(len(telo)))
    obravnava.send_header("Connection", "close")
    obravnava.end_headers()
    if getattr(obravnava, "command", "") != "HEAD":
        obravnava.wfile.write(telo)


def postrezi_datoteko(obravnava, streznik: "StreznikDatotek", oznaka: str, samo_glava: bool) -> None:
    """Datoteka deljene mape z zetonom v glavi in podporo za `Range` (previjanje v predvajalniku).

    Isto za lastni streznik datotek (/d/<id>) in za Hub (/cast/d/<id>), prek katerega gre tok tudi
    po Global Linku: rele prinese samo povezavo do vrat Huba."""
    z = obravnava.headers.get("X-Safeer-Token")
    if not streznik.zeton_velja(z.strip() if z else None):
        _napaka_http(obravnava, 401, "manjka ali napacen zeton")
        return
    r = streznik.mape.razresi(oznaka)
    if r is None or not os.path.isfile(r[1]):
        _napaka_http(obravnava, 404, "datoteke ni")
        return
    _poslji_datoteko(obravnava, r[1], samo_glava)


def _poslji_datoteko(obravnava, pot: str, samo_glava: bool) -> None:
    """Datoteka z diska s podporo za `Range` (zeton je ze preverjen)."""
    velikost = os.path.getsize(pot)
    vrsta = mimetypes.guess_type(pot)[0] or "application/octet-stream"
    zacetek, konec = 0, velikost - 1
    obseg = obravnava.headers.get("Range")
    delni = False
    if obseg and obseg.startswith("bytes="):
        try:
            a, b = obseg[6:].split(",", 1)[0].split("-", 1)
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
            obravnava.send_response(416)
            obravnava.send_header("Content-Range", f"bytes */{velikost}")
            obravnava.send_header("Content-Length", "0")
            obravnava.end_headers()
            return
    dolzina = konec - zacetek + 1
    obravnava.send_response(206 if delni else 200)
    obravnava.send_header("Content-Type", vrsta)
    obravnava.send_header("Accept-Ranges", "bytes")
    obravnava.send_header("Content-Length", str(dolzina))
    if delni:
        obravnava.send_header("Content-Range", f"bytes {zacetek}-{konec}/{velikost}")
    obravnava.send_header("Cache-Control", "private, max-age=0")
    obravnava.end_headers()
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
                obravnava.wfile.write(kos)
                ostane -= len(kos)
    except (BrokenPipeError, ConnectionResetError, ssl.SSLError, socket.timeout):
        # Predvajalnik na napravi med predvajanjem zapira povezave sredi obsega (nov Range): ni napaka,
        # prej je vsaka taka pustila sled v dnevniku (SSLEOFError).
        pass


def posreduj_tok(obravnava, streznik: "StreznikDatotek", skrivnost: str, samo_glava: bool) -> None:
    """Tok torrenta, ki ga prenasa racunalnik, za napravo v krogu: zeton v glavi, `Range` gre naprej.

    Naprava (televizor s sibkim pomnilnikom) tako nicesar ne prenasa in ne shranjuje: dobi le
    sproten tok, kot pri spletnem videu. Lokalni tok (127.0.0.1) je dosegljiv samo prek tega
    posrednika in samo s skrivnostjo, ki jo je racunalnik izdal za ta tok."""
    z = obravnava.headers.get("X-Safeer-Token")
    if not streznik.zeton_velja(z.strip() if z else None):
        _napaka_http(obravnava, 401, "manjka ali napacen zeton")
        return
    cilj = streznik.lokalni_tok(skrivnost)
    if cilj is None:
        _napaka_http(obravnava, 404, "toka ni")
        return
    if cilj.startswith("file://"):
        # Film je na tem racunalniku ze v celoti (npr. prenesen v Safeer OS): postrezemo ga z diska.
        pot = cilj[len("file://"):]
        if not os.path.isfile(pot):
            _napaka_http(obravnava, 404, "datoteke ni")
            return
        _poslji_datoteko(obravnava, pot, samo_glava)
        return
    u = urllib.parse.urlparse(cilj)
    glave = {"Range": obravnava.headers["Range"]} if obravnava.headers.get("Range") else {}
    povezava = http.client.HTTPConnection(u.hostname or "127.0.0.1", u.port or 80, timeout=120)
    try:
        povezava.request("HEAD" if samo_glava else "GET", u.path, headers=glave)
        r = povezava.getresponse()
        obravnava.send_response(r.status)
        for ime in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
            if r.getheader(ime):
                obravnava.send_header(ime, r.getheader(ime))
        obravnava.send_header("Cache-Control", "no-store")
        obravnava.send_header("Connection", "close")
        obravnava.end_headers()
        if samo_glava:
            return
        while True:
            kos = r.read(VELIKOST_KOSA)
            if not kos:
                break
            obravnava.wfile.write(kos)
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    finally:
        povezava.close()


class _Streznik(link_tls.RokovanjeVNiti, http.server.ThreadingHTTPServer):
    daemon_threads = True
    #: Predvajalnik, ki obstane (pavza), ne drzi niti v nedogled.
    rok_po_rokovanju = 120.0
    allow_reuse_address = True


class StreznikDatotek:
    """HTTPS streznik datotek Controla: zazene se ob prvi rabi, na nakljucnih vratih, samo za naprave z zetonom."""

    def __init__(self, mape: DeljeneMape, tls_mapa: str = TLS_MAPA) -> None:
        self.mape = mape
        self.tls_mapa = tls_mapa
        self.odtis = ""
        self.vrata = 0
        self._zetoni: Dict[str, Tuple[str, float, float]] = {}   # zeton -> (id naprave, izdan, zadnja raba)
        #: Ali je naprava umaknjena iz kroga zaupanja: njeni zetoni takoj prenehajo veljati (ne sele po 12 h).
        self.umaknjena = _umaknjena_iz_kroga
        self._streznik: Optional[_Streznik] = None
        self._nit: Optional[threading.Thread] = None
        self._kljucavnica = threading.Lock()
        #: Torrenti, ki jih racunalnik pretaka napravam: skrivnost -> lokalni naslov toka (127.0.0.1).
        self._tokovi: Dict[str, str] = {}

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
            s.socket = ctx.wrap_socket(s.socket, server_side=True, do_handshake_on_connect=False)
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
        self._tokovi.clear()
        self.vrata = 0

    def zeton_za(self, id_naprave: str, zdaj: Optional[float] = None) -> str:
        """Zeton naprave za prenos in predvajanje.

        Velja ZETON_VELJA_S od zadnje rabe (tok, ki tece, ga drzi pri zivljenju - album s ponavljanjem ali
        dolga pavza ne padeta), a najvec NAJDLJE_S od izdaje. Naprava, ki znova vpraša za seznam, po polovici
        roka dobi novega; prejsnji velja naprej do svojega roka."""
        zdaj = time.monotonic() if zdaj is None else zdaj
        with self._kljucavnica:
            for z, (n, izdan, rabljen) in list(self._zetoni.items()):
                if not _zeton_zivi(izdan, rabljen, zdaj):
                    self._zetoni.pop(z, None)
                elif n == id_naprave and zdaj - izdan < ZETON_VELJA_S / 2:
                    return z
            z = secrets.token_urlsafe(24)
            self._zetoni[z] = (id_naprave, zdaj, zdaj)
            while len(self._zetoni) > NAJVEC_ZETONOV:
                self._zetoni.pop(min(self._zetoni, key=lambda k: self._zetoni[k][2]), None)
            return z

    def zeton_velja(self, zeton: Optional[str], zdaj: Optional[float] = None) -> bool:
        # Primerjava v stalnem casu: iz casa odgovora se ne da uganiti, koliko znakov se ujema.
        if not zeton:
            return False
        zdaj = time.monotonic() if zdaj is None else zdaj
        with self._kljucavnica:
            for z, (n, izdan, rabljen) in list(self._zetoni.items()):
                if hmac.compare_digest(zeton.encode(), z.encode()) and _zeton_zivi(izdan, rabljen, zdaj):
                    if self.umaknjena(n):
                        self._zetoni.pop(z, None)
                        return False
                    self._zetoni[z] = (n, izdan, zdaj)
                    return True
        return False

    def preklici(self, id_naprave: str) -> int:
        """Preklice vse zetone naprave (npr. ko ji vzamemo dostop do celega diska). Vrne stevilo."""
        with self._kljucavnica:
            stari = [z for z, v in self._zetoni.items() if v[0] == id_naprave]
            for z in stari:
                self._zetoni.pop(z, None)
        return len(stari)

    def dodaj_tok(self, lokalni_url: str) -> str:
        """Lokalni tok (samo 127.0.0.1) objavi za naprave z zetonom; vrne pot `/m/<skrivnost>/<ime>`."""
        u = urllib.parse.urlparse(lokalni_url)
        if u.scheme != "http" or u.hostname not in ("127.0.0.1", "localhost"):
            raise ValueError("samo lokalni tok")
        skrivnost = secrets.token_urlsafe(18)
        with self._kljucavnica:
            self._tokovi[skrivnost] = lokalni_url
            while len(self._tokovi) > 64:
                self._tokovi.pop(next(iter(self._tokovi)))
        return "/m/%s/%s" % (skrivnost, u.path.rsplit("/", 1)[-1])

    def pozabi_tokove(self) -> None:
        with self._kljucavnica:
            self._tokovi.clear()

    def dodaj_datoteko_toka(self, pot: str) -> str:
        """Ze preneseno datoteko (samo pot, ki jo poda racunalnik sam) objavi kot tok `/m/<skrivnost>/<ime>`."""
        pot = os.path.realpath(pot)
        if not os.path.isfile(pot):
            raise ValueError("ni datoteke")
        skrivnost = secrets.token_urlsafe(18)
        with self._kljucavnica:
            self._tokovi[skrivnost] = "file://" + pot
            while len(self._tokovi) > 64:
                self._tokovi.pop(next(iter(self._tokovi)))
        return "/m/%s/%s" % (skrivnost, urllib.parse.quote(os.path.basename(pot)))

    def lokalni_tok(self, skrivnost: str) -> Optional[str]:
        with self._kljucavnica:
            for k, v in self._tokovi.items():
                if hmac.compare_digest(k.encode(), str(skrivnost or "").encode()):
                    return v
        return None

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
        self.mape.dodaj_podnapise(vnosi)
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


    def tok_torrenta(self, uri: str, id_naprave: str, hub_url: str = "", datoteka: Optional[int] = None,
                     torrenti=None, zmogljivost=None, mape_stanja=None, pot_rabe: Optional[str] = None) -> dict:
        """`magnet.stream`: racunalnik prenasa torrent in ga pretaka napravi (televizorju), ki tako
        nicesar ne shranjuje. Vrne {server, path, name, file} ali vrze os_torrent.NapakaTorrenta.

        Izbere zahtevano datoteko ali najvecji video; programov (nevarno) nikoli ne predvaja."""
        from core import os_torrent
        m = os_torrent.razcleni_magnet(uri)
        if m is None:
            raise os_torrent.NapakaTorrenta("ni_magnet")
        # Nadzornik: film, ki je na tem racunalniku ze v celoti prenesen (Safeer OS ali prej za drugo
        # napravo), postrezemo takoj z diska - brez zagona torrenta in brez ponovnega prenosa.
        # Zapis o zadnji rabi (za samodejno ciscenje): v preizkusih z vstavljenimi torrenti samo, ce je pot podana.
        if pot_rabe is None and torrenti is None and mape_stanja is None:
            pot_rabe = privzeta_pot_rabe()
        obstojeca, indeks = ze_preneseno(m["hash"], datoteka, mape_stanja)
        if obstojeca:
            zabelezi_rabo(m["hash"], pot_rabe)
            self.streznik.zazeni()
            naslov = naslov_do_huba(hub_url) if hub_url else krajevni_naslov()
            return {"server": {"base_url": self.streznik.osnova(naslov), "fp": self.streznik.odtis,
                               "token": self.streznik.zeton_za(id_naprave or "naprava")},
                    "path": self.streznik.dodaj_datoteko_toka(obstojeca), "name": os.path.basename(obstojeca),
                    "file": indeks, "size": os.path.getsize(obstojeca), "local": True}
        if torrenti is None:
            if not os_torrent.program_na_voljo():
                os_torrent.prenesi_program()
            torrenti = torrenti_za_naprave()
        torrenti.zazeni()
        opis = torrenti.preberi(uri)
        videi = [d for d in opis["datoteke"] if d.get("vrsta") == "video"]
        if datoteka is not None:
            izbrana = next((d for d in opis["datoteke"] if d["i"] == int(datoteka) and d.get("vrsta") in ("video", "audio")), None)
        else:
            izbrana = max(videi, key=lambda d: int(d.get("velikost") or 0)) if videi else None
        if izbrana is None:
            raise os_torrent.NapakaTorrenta("ni_predvajljivo")
        # Solidarnost brez preobremenitve: racunalnik pomaga, kolikor zmore - ce je sam zaseden ali nima
        # prostora, to pove in naprava vprasa naslednjega v Linku.
        # Pretakanje torrenta je delo omrezja in diska, ne procesorja: racunalnik ga zmore tudi med prevajanjem
        # (tablica 1. 10. 2026: med gradnjo aplikacije je dobila "preobremenjen" in filma ni bilo).
        # Kar je racunalnik prenesel za naprave in tega 48 ur nihce ni predvajal, odstranimo (lastnik, 3. 10. 2026:
        # "ce uporabnik torrenta ne uporablja vec, ga naprava samodejno odstrani"). Film, ki ga pravkar hocejo, ostane.
        pot_rabe = pot_rabe or _pot_rabe_za(torrenti)
        zabelezi_rabo(m["hash"], pot_rabe)
        pocisti_neuporabljene(torrenti, pot_rabe)
        mapa_diska = os.path.dirname(getattr(torrenti, "mapa_prenosov", "") or "") or os.path.expanduser("~")
        preveri = zmogljivost or zmogljivost_za_tok
        razlog = preveri(mapa_diska, int(izbrana.get("velikost") or 0))
        if razlog == "ni_prostora":
            # Prostor za nov film naredimo sami: najdlje neuporabljeni prenosi za naprave gredo prvi.
            pocisti_neuporabljene(torrenti, pot_rabe, dovolj=lambda: preveri(mapa_diska, int(izbrana.get("velikost") or 0)) != "ni_prostora",
                                  obdrzi=m["hash"])
            razlog = preveri(mapa_diska, int(izbrana.get("velikost") or 0))
        if razlog:
            raise os_torrent.NapakaTorrenta(razlog)
        tid = torrenti.dodaj(uri, [izbrana["i"]])
        pot = self.streznik.dodaj_tok(torrenti.tok(tid, izbrana["i"]))
        self.streznik.zazeni()
        naslov = naslov_do_huba(hub_url) if hub_url else krajevni_naslov()
        return {"server": {"base_url": self.streznik.osnova(naslov), "fp": self.streznik.odtis,
                           "token": self.streznik.zeton_za(id_naprave or "naprava")},
                "path": pot, "name": os.path.basename(str(izbrana.get("ime") or "")), "file": izbrana["i"],
                "size": int(izbrana.get("velikost") or 0)}


    def prenosi_za_naprave(self, torrenti=None, pot_rabe: Optional[str] = None) -> dict:
        """`magnet.list`: kar racunalnik hrani za naprave (da jih uporabnik z medijskega centra odstrani)."""
        torrenti = torrenti if torrenti is not None else torrenti_za_naprave()
        izid = []
        if not torrenti.tece():
            torrenti.seznam()   # zazene rqbit, ce ima shranjeno stanje
        odstranjeni = set(pocisti_neuporabljene(torrenti, pot_rabe))
        for t in torrenti.seznam():
            if str(t.get("hash") or "").lower() in odstranjeni:
                continue
            videi = [d for d in t.get("datoteke") or [] if d.get("vkljucena") and d.get("vrsta") == "video"]
            try:
                magnet = torrenti.magnet(int(t["id"]))
            except Exception:  # noqa: BLE001
                magnet = ""
            izid.append({"id": int(t["id"]), "name": t.get("ime") or "", "size": int(t.get("skupaj") or 0),
                         "done": int(t.get("preneseno") or 0), "finished": bool(t.get("koncano")),
                         "speed_mibs": t.get("hitrost_mibs") or 0, "magnet": magnet,
                         "file": videi[0]["i"] if videi else None})
        return {"items": izid}

    def odstrani_prenos(self, tid: int, torrenti=None) -> bool:
        """`magnet.remove`: torrent in njegove prenesene datoteke z racunalnika (samo iz mape prenosov za naprave)."""
        torrenti = torrenti if torrenti is not None else torrenti_za_naprave()
        if not torrenti.tece():
            torrenti.seznam()   # zazene rqbit, ce ima shranjeno stanje
        self.streznik.pozabi_tokove()
        return torrenti.odstrani(int(tid), z_datotekami=True)


def _odgovor_z_streznikom(datoteke: "Datoteke", o: dict, id_naprave: str, hub_url: str) -> dict:
    datoteke.streznik.zazeni()
    naslov = naslov_do_huba(hub_url) if hub_url else krajevni_naslov()
    o["server"] = {"base_url": datoteke.streznik.osnova(naslov), "fp": datoteke.streznik.odtis,
                   "token": datoteke.streznik.zeton_za(id_naprave or "naprava")}
    return o


def _bdekodiraj(b: bytes, i: int = 0):
    """Najmanjsi bencode bralnik (za .torrent iz stanja rqbit). Vrne (vrednost, naslednji indeks)."""
    c = b[i:i + 1]
    if c == b"i":
        k = b.index(b"e", i)
        return int(b[i + 1:k]), k + 1
    if c == b"l":
        i, izid = i + 1, []
        while b[i:i + 1] != b"e":
            v, i = _bdekodiraj(b, i)
            izid.append(v)
        return izid, i + 1
    if c == b"d":
        i, izid = i + 1, {}
        while b[i:i + 1] != b"e":
            k, i = _bdekodiraj(b, i)
            v, i = _bdekodiraj(b, i)
            izid[k] = v
        return izid, i + 1
    d = b.index(b":", i)
    n = int(b[i:d])
    return b[d + 1:d + 1 + n], d + 1 + n


def ze_preneseno(hash_: str, indeks: Optional[int], mape_stanja=None) -> Tuple[str, int]:
    """Nadzornik: pot do datoteke `indeks` torrenta `hash_`, ce jo je rqbit na tem racunalniku ze v celoti
    prenesel (Safeer OS ali pomoc napravam), sicer "". indeks None = najvecji video. Vrne (pot, indeks). Odloca bitno polje kosov (<hash>.bitv), ne velikost
    datoteke - rqbit datoteko vnaprej razsiri, zato velikost sama ne pove, da je prenos koncan."""
    from core import os_torrent
    if not re.fullmatch(r"[0-9a-fA-F]{40}", hash_ or ""):
        return "", -1
    hash_ = hash_.lower()
    if mape_stanja is None:
        osnova = os.path.dirname(os_torrent.mapa_stanja())
        mape_stanja = [os_torrent.mapa_stanja(), os.path.join(osnova, "stanje-naprave")]
    for mapa in mape_stanja:
        try:
            with open(os.path.join(mapa, "session.json"), encoding="utf-8") as d:
                seja = json.load(d)
            izhod = next((str(t.get("output_folder") or "") for t in (seja.get("torrents") or {}).values()
                          if str(t.get("info_hash") or "").lower() == hash_), "")
            if not izhod:
                continue
            with open(os.path.join(mapa, hash_ + ".torrent"), "rb") as d:
                meta, _ = _bdekodiraj(d.read())
            info = meta[b"info"]
            dolzina_kosa = int(info[b"piece length"])
            if b"files" in info:
                datoteke = [(int(f[b"length"]), [x.decode("utf-8", "replace") for x in f[b"path"]]) for f in info[b"files"]]
            else:
                datoteke = [(int(info[b"length"]), [info[b"name"].decode("utf-8", "replace")])]
            if indeks is None:
                videi = [k for k, (_, deli) in enumerate(datoteke) if os_torrent.vrsta_datoteke(deli[-1]) == "video"]
                if not videi:
                    continue
                izbran = max(videi, key=lambda k: datoteke[k][0])
            else:
                izbran = int(indeks)
            if not 0 <= izbran < len(datoteke):
                continue
            zacetek = sum(d for d, _ in datoteke[:izbran])
            dolzina, deli = datoteke[izbran]
            if dolzina <= 0 or any(x in ("", ".", "..") or "/" in x or "\\" in x for x in deli):
                continue
            with open(os.path.join(mapa, hash_ + ".bitv"), "rb") as d:
                biti = d.read()
            prvi, zadnji = zacetek // dolzina_kosa, (zacetek + dolzina - 1) // dolzina_kosa
            if zadnji // 8 >= len(biti) or not all(biti[k // 8] & (0x80 >> (k % 8)) for k in range(prvi, zadnji + 1)):
                continue
            pot = os.path.join(izhod, *deli)
            if os.path.isfile(pot) and os.path.getsize(pot) == dolzina:
                return pot, izbran
        except (OSError, ValueError, KeyError, TypeError, StopIteration):
            continue
    return "", -1


#: Meje, nad katerimi racunalnik ne prevzame novega dela za druge naprave (ostane odziven za uporabnika).
NAJVEC_OBREMENITVE_NA_JEDRO = 0.85
NAJMANJ_PROSTEGA_RAM = 512 * 1024 * 1024
REZERVA_DISKA = 2 * 1024 * 1024 * 1024


def prosti_pomnilnik() -> int:
    """Prosti pomnilnik v bajtih ali -1, ce ga sistem ne pove (Linux: MemAvailable, Windows: GlobalMemoryStatusEx)."""
    if os.name == "nt":
        try:
            import ctypes

            class _Stanje(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            stanje = _Stanje()
            stanje.dwLength = ctypes.sizeof(stanje)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stanje)):
                return int(stanje.ullAvailPhys)
        except Exception:  # noqa: BLE001 - brez podatka raje pomagamo, kot zavrnemo
            pass
        return -1
    try:
        with open("/proc/meminfo", encoding="utf-8") as d:
            for v in d:
                if v.startswith("MemAvailable:"):
                    return int(v.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    return -1


def prosta_zmogljivost(mapa: str, potrebno: int, procesor: bool = True) -> str:
    """"" ce racunalnik delo zmore brez preobremenitve, sicer kratek razlog (preobremenjen, malo_pomnilnika,
    ni_prostora). Disk: velikost datoteke + rezerva, da uporabniku nikoli ne zapolnimo diska.
    `procesor=False` preskoci obremenitev procesorja (delo, ki ga ne potrebuje: pretakanje torrenta)."""
    try:
        jedra = os.cpu_count() or 1
        if procesor and os.getloadavg()[0] / jedra > NAJVEC_OBREMENITVE_NA_JEDRO:
            return "preobremenjen"
    except (OSError, AttributeError):
        pass
    pomnilnik = prosti_pomnilnik()
    if 0 <= pomnilnik < NAJMANJ_PROSTEGA_RAM:
        return "malo_pomnilnika"
    try:
        os.makedirs(mapa, exist_ok=True)
        # shutil.disk_usage dela na Linuxu in na Windows (os.statvfs na Windows ne obstaja - brez tega bi
        # racunalnik z Windows sprejel film, ki nanj ne gre, in zapolnil disk).
        if shutil.disk_usage(mapa).free < potrebno + REZERVA_DISKA:
            return "ni_prostora"
    except OSError:
        pass
    return ""


def zmogljivost_za_tok(mapa: str, potrebno: int) -> str:
    """Zmogljivost za pretakanje torrenta napravi: samo pomnilnik in disk, procesor ni pogoj."""
    return prosta_zmogljivost(mapa, potrebno, procesor=False)


# Samodejno ciscenje prenosov za naprave: po toliko casu brez predvajanja torrent in njegove datoteke izginejo.
RABA_VELJA_S = 48 * 3600
# Ob pomanjkanju prostora odstranimo tudi mlajse, a ne tistih, ki jih je kdo predvajal v zadnjih urah (film se tece).
RABA_V_TEKU_S = 6 * 3600
_RABA_ZAKLEP = threading.Lock()


def privzeta_pot_rabe() -> str:
    from core import os_torrent
    return os.path.join(os.path.dirname(os_torrent.mapa_stanja()), "raba-naprave.json")


def _pot_rabe_za(torrenti) -> str:
    """Zapis o rabi stoji ob mapi stanja torrentov za naprave; brez nje (preizkus z nadomestkom) ga ni."""
    stanje = str(getattr(torrenti, "mapa_stanja", "") or "")
    return os.path.join(os.path.dirname(stanje), "raba-naprave.json") if stanje else ""


def _beri_rabo(pot: str) -> dict:
    try:
        with open(pot, encoding="utf-8") as d:
            raba = json.load(d)
        return {str(k).lower(): float(v) for k, v in raba.items()} if isinstance(raba, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _pisi_rabo(pot: str, raba: dict) -> None:
    try:
        os.makedirs(os.path.dirname(pot), exist_ok=True)
        zacasna = pot + ".tmp"
        with open(zacasna, "w", encoding="utf-8") as d:
            json.dump(raba, d)
        os.replace(zacasna, pot)
    except OSError:
        pass


def zabelezi_rabo(hash_: str, pot: Optional[str] = None, zdaj: Optional[float] = None) -> None:
    """Naprava je torrent pravkar zahtevala (magnet.stream): od zdaj tece rok do samodejne odstranitve."""
    if not pot or not re.fullmatch(r"[0-9a-fA-F]{40}", hash_ or ""):
        return
    with _RABA_ZAKLEP:
        raba = _beri_rabo(pot)
        raba[hash_.lower()] = float(time.time() if zdaj is None else zdaj)
        _pisi_rabo(pot, raba)


def _hash_torrenta(torrenti, t: dict) -> str:
    h = str(t.get("hash") or "").lower()
    if re.fullmatch(r"[0-9a-f]{40}", h):
        return h
    try:
        m = re.search(r"btih:([0-9a-fA-F]{40})", torrenti.magnet(int(t["id"])) or "")
    except Exception:  # noqa: BLE001
        m = None
    return m.group(1).lower() if m else ""


def pocisti_neuporabljene(torrenti, pot: Optional[str] = None, zdaj: Optional[float] = None,
                          dovolj=None, obdrzi: str = "") -> List[str]:
    """Odstrani prenose za naprave (torrent in datoteke), ki jih [RABA_VELJA_S] nihce ni predvajal. Vrne njihove hashe.

    `dovolj` (klic brez argumentov -> bool): prostora zmanjkuje - dokler ne vrne True, gredo tudi mlajsi prenosi,
    najdlje neuporabljeni prvi, a ne tisti, ki jih je kdo predvajal v zadnjih [RABA_V_TEKU_S], in ne `obdrzi`.
    Torrent, ki ga se ne poznamo (prenesen pred to razlicico), dobi rok od zdaj. Uporabnikovih datotek, ki jih deli
    (`lastna`), se ne dotikamo; rqbita samo zaradi ciscenja ne zaganjamo."""
    pot = pot or _pot_rabe_za(torrenti)
    if not pot:
        return []
    zdaj = float(time.time() if zdaj is None else zdaj)
    try:
        if not torrenti.tece():
            return []
        vsi = torrenti.seznam()
    except Exception:  # noqa: BLE001
        return []
    odstranjeni: List[str] = []
    with _RABA_ZAKLEP:
        raba = _beri_rabo(pot)
        spremenjeno = False
        znani = []
        for t in vsi:
            h = _hash_torrenta(torrenti, t)
            if not h or t.get("lastna"):
                continue
            if h not in raba:
                raba[h] = zdaj
                spremenjeno = True
            znani.append((raba[h], h, t))

        def odstrani(h: str, t: dict) -> bool:
            try:
                ok = bool(torrenti.odstrani(int(t["id"]), z_datotekami=True))
            except Exception:  # noqa: BLE001
                ok = False
            if ok:
                raba.pop(h, None)
                odstranjeni.append(h)
            return ok

        for cas, h, t in sorted(znani):
            if h != obdrzi.lower() and zdaj - cas > RABA_VELJA_S:
                spremenjeno = odstrani(h, t) or spremenjeno
        if dovolj is not None:
            for cas, h, t in sorted(znani):
                if dovolj():
                    break
                if h in odstranjeni or h == obdrzi.lower() or zdaj - cas < RABA_V_TEKU_S:
                    continue
                spremenjeno = odstrani(h, t) or spremenjeno
        # Zapisi o torrentih, ki jih ni vec (uporabnik jih je odstranil sam), ne ostajajo.
        zivi = {h for _, h, _ in znani} - set(odstranjeni)
        for h in [h for h in raba if h not in zivi and h != obdrzi.lower()]:
            if zdaj - raba[h] > RABA_VELJA_S:
                raba.pop(h)
                spremenjeno = True
        if spremenjeno:
            _pisi_rabo(pot, raba)
    return odstranjeni


_CISCENJE_TECE = False


def zazeni_ciscenje(razmik_s: float = 3 * 3600, zamik_s: float = 180) -> None:
    """Control: prenose za naprave pregleda kmalu po zagonu in nato vsake tri ure. Ce je rqbit ugasnjen in ima
    shranjene prenose, ga za pregled prizge in potem spet ugasne (ne ostane v ozadju samo zaradi ciscenja)."""
    global _CISCENJE_TECE
    if _CISCENJE_TECE:
        return
    _CISCENJE_TECE = True

    def zanka() -> None:
        time.sleep(zamik_s)
        while True:
            try:
                t = torrenti_za_naprave()
                tekel = t.tece()
                if not tekel:
                    t.seznam()      # zazene rqbit le, ce ima shranjeno stanje
                odstranjeni = pocisti_neuporabljene(t)
                if odstranjeni:
                    from core import os_stabilnost
                    os_stabilnost.zapisi("safeer-control", f"prenosi za naprave: samodejno odstranjenih {len(odstranjeni)} (48 h brez predvajanja)")
                if not tekel and t.tece():
                    t.ustavi()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(razmik_s)
    threading.Thread(target=zanka, name="safeer-ciscenje-prenosov", daemon=True).start()


_ZA_NAPRAVE = None
_ZA_NAPRAVE_ZAKLEP = threading.Lock()


def torrenti_za_naprave():
    """Lasten rqbit za pomoc napravam: svoja mapa stanja (ne deli in ne ustavlja tistega v Safeer OS)
    in svoja mapa Prejemi/Safeer/Za naprave, da je jasno, kaj je racunalnik prenesel za televizor."""
    global _ZA_NAPRAVE
    from core import os_torrent
    with _ZA_NAPRAVE_ZAKLEP:
        if _ZA_NAPRAVE is None:
            _ZA_NAPRAVE = os_torrent.Torrenti(os.path.join(os_torrent.mapa_prenosov(), "Za naprave"),
                                              os.path.join(os.path.dirname(os_torrent.mapa_stanja()), "stanje-naprave"))
            # Ob izhodu Controla ustavimo tudi rqbit (sicer ostane do naslednjega zagona, ko ga pocisti _ustavi_sirote).
            import atexit
            atexit.register(_ZA_NAPRAVE.ustavi)
        return _ZA_NAPRAVE


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
