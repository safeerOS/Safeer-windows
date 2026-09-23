"""Zvok racunalnika na napravi v Safeer Linku (televizor, tablica) - »predvajaj tukaj«.

Kot zvocnik Bluetooth, le da je zvocnik televizor v domacem omrezju:

1. Safeer Control ustvari navidezni izhod `safeer_link_zvok` (PipeWire/PulseAudio null-sink) z
   imenom naprave, ga nastavi za privzetega in nanj preusmeri vse programe.
2. Odpre TLS vrata s svojim potrdilom (isto kot pri zaslonu in datotekah) in napravi po hubu
   poslje ukaz `audio.play` z vrati, odtisom, enkratnim zetonom in naslovi racunalnika.
3. Naprava se poveze naravnost na racunalnik; zvok tece kot surov PCM (48 kHz, stereo, s16le) v
   istih okvirjih kot pri deljenju zaslona - nic ne gre skozi hub in nic v oblak.
4. Konec (uporabnik izbere drug izhod, naprava prekine ali izgine): prejsnji izhod dobi nazaj
   privzetost in vse programe, navidezni izhod izgine.

Pozdrav (prva vrstica, UTF-8):
    SAFEER-ZVOK <zeton>\\n                              <- naprava
    {"v":1,"zvok":{"hz":48000,"kanali":2,"oblika":"s16le"}}\\n  <- racunalnik, nato okvirji
Okvir: 1 bajt vrste (2 = zvok, 3 = obvestilo JSON), 4 bajti dolzine (big-endian), vsebina.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import threading
import time
from typing import Callable, List, Optional

from core.link_datoteke import TLS_MAPA, zagotovi_potrdilo

LINK_IZHOD = "safeer_link_zvok"
ZMOZNOST = "audio"
ZVOK_HZ, ZVOK_KANALI = 48000, 2
OKVIR_ZVOK, OKVIR_OBVESTILO = 2, 3
#: 10 ms zvoka v enem okvirju: dovolj majhno za kratko zakasnitev, dovolj veliko za malo glav.
KOS = ZVOK_HZ * ZVOK_KANALI * 2 // 100
#: Toliko casa naprava dobi, da se poveze, preden sejo opustimo in vrnemo zvok racunalniku.
CAKANJE_S = 20


def _okolje() -> dict:
    o = dict(os.environ)
    o.pop("LC_ALL", None)
    o["LC_NUMERIC"] = "C"
    return o


def _pactl(*argumenti: str, cas: float = 4.0) -> subprocess.CompletedProcess:
    return subprocess.run(["pactl"] + list(argumenti), capture_output=True, text=True, timeout=cas, env=_okolje())


def _vrstice(*argumenti: str) -> List[List[str]]:
    try:
        r = _pactl(*argumenti)
        return [v.split("\t") for v in r.stdout.splitlines() if v.strip()] if r.returncode == 0 else []
    except Exception:
        return []


def privzeti_izhod() -> str:
    try:
        return _pactl("get-default-sink").stdout.strip()
    except Exception:
        return ""


def izhodi() -> List[str]:
    return [v[1] for v in _vrstice("list", "sinks", "short") if len(v) > 1]


def premakni_vse(izhod: str) -> None:
    for v in _vrstice("list", "sink-inputs", "short"):
        if v and v[0].isdigit():
            try:
                _pactl("move-sink-input", v[0], izhod)
            except Exception:
                pass


def lastni_naslovi(hub_url: str = "") -> List[str]:
    """Naslovi IPv4, prek katerih nas naprava doseze. Najprej tisti, ki gleda proti hubu."""
    naslovi: List[str] = []
    gostitelj = ""
    if hub_url:
        try:
            from urllib.parse import urlparse
            gostitelj = urlparse(hub_url).hostname or ""
        except Exception:
            gostitelj = ""
    for cilj in ([gostitelj] if gostitelj else []) + ["192.168.0.1", "10.0.0.1"]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((cilj, 9))
            n = s.getsockname()[0]
            s.close()
            if n and not n.startswith("127.") and n not in naslovi:
                naslovi.append(n)
        except Exception:
            continue
    return naslovi


def ukaz_zajema(vir: str, ffmpeg: str = "ffmpeg") -> List[str]:
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "pulse", "-fragment_size", str(KOS), "-i", vir,
            "-ac", str(ZVOK_KANALI), "-ar", str(ZVOK_HZ), "-f", "s16le", "-"]


def _zapri(s) -> None:
    """shutdown pred close: nit, ki na vticnici caka v recv, se zbudi in druga stran dobi konec -
    samo close() na Linuxu vticnice ne zapre, dokler jo kdo bere."""
    if s is None:
        return
    try:
        s.shutdown(socket.SHUT_RDWR)
    except Exception:
        pass
    try:
        s.close()
    except Exception:
        pass


class ZvokNaNapravo:
    """Ena seja naenkrat: zvok racunalnika na eni napravi v Safeer Linku."""

    def __init__(self, tls_mapa: str = TLS_MAPA, ffmpeg: Optional[str] = None) -> None:
        self.tls_mapa = tls_mapa
        self.ffmpeg = ffmpeg or (shutil.which("ffmpeg") or "")
        self.naprava = ""
        self.ime = ""
        self.stanje = ""           # "" / "caka" / "tece"
        self.ob_spremembi: Optional[Callable[[dict], None]] = None
        self._zeton = ""
        self._prejsnji = ""
        self._modul = ""
        self._posluh: Optional[socket.socket] = None
        self._odjemalec = None
        self._zajem: Optional[subprocess.Popen] = None
        self._seja = 0
        self._kljuc = threading.Lock()

    # ------------------------------------------------------------------ stanje
    def mozno(self) -> bool:
        return bool(self.ffmpeg) and shutil.which("pactl") is not None

    def opis(self) -> dict:
        return {"naprava": self.naprava, "ime": self.ime, "stanje": self.stanje}

    def _sporoci(self) -> None:
        if self.ob_spremembi is not None:
            try:
                self.ob_spremembi(self.opis())
            except Exception:
                pass

    # ------------------------------------------------------------------ zacetek
    def zacni(self, id_naprave: str, ime: str, hub_url: str = "") -> dict:
        """Pripravi izhod in vrata; vrne parametre za ukaz `audio.play` napravi."""
        if not self.mozno():
            raise RuntimeError("Na tem racunalniku ni ffmpeg ali pactl")
        self.ustavi(obnovi=False)       # prejsnja seja (druga naprava): izhod ostane nas
        with self._kljuc:
            self._seja += 1
            seja = self._seja
            if not self._prejsnji:
                zdaj = privzeti_izhod()
                self._prejsnji = "" if zdaj == LINK_IZHOD else zdaj
            self._pripravi_izhod(ime)
            kljuc, potrdilo, odtis = zagotovi_potrdilo(self.tls_mapa)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(potrdilo, kljuc)
            posluh = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            posluh.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            posluh.bind(("0.0.0.0", 0))
            posluh.listen(1)
            posluh.settimeout(CAKANJE_S)
            self._posluh = posluh
            self._zeton = secrets.token_urlsafe(24)
            self.naprava, self.ime, self.stanje = id_naprave, ime, "caka"
            threading.Thread(target=self._streci, args=(posluh, ctx, seja), name="safeer-zvok", daemon=True).start()
        self._sporoci()
        return {"port": posluh.getsockname()[1], "fp": odtis, "token": self._zeton,
                "hosts": lastni_naslovi(hub_url), "name": socket.gethostname(),
                "audio": {"hz": ZVOK_HZ, "channels": ZVOK_KANALI, "format": "s16le"}}

    def _pripravi_izhod(self, ime: str) -> None:
        opis = (ime or "Safeer Link").replace('"', "").replace("\\", "")[:60] + " (Safeer Link)"
        if LINK_IZHOD not in izhodi():
            r = _pactl("load-module", "module-null-sink", "sink_name=" + LINK_IZHOD,
                       'sink_properties=device.description="%s" device.icon_name=video-display' % opis)
            if r.returncode != 0:
                raise RuntimeError("Navideznega izhoda ni bilo mogoce ustvariti")
            self._modul = r.stdout.strip()
            for _ in range(20):          # PipeWire ga objavi z majhno zamudo
                if LINK_IZHOD in izhodi():
                    break
                time.sleep(0.05)
        _pactl("set-default-sink", LINK_IZHOD)
        premakni_vse(LINK_IZHOD)

    # ------------------------------------------------------------------ tok
    def _streci(self, posluh: socket.socket, ctx: ssl.SSLContext, seja: int) -> None:
        odjemalec = None
        try:
            odjemalec = self._sprejmi(posluh, ctx)
            if odjemalec is None:
                return
            glava = {"v": 1, "zvok": {"hz": ZVOK_HZ, "kanali": ZVOK_KANALI, "oblika": "s16le"},
                     "ime": socket.gethostname()}
            odjemalec.sendall((json.dumps(glava) + "\n").encode("utf-8"))
            odjemalec.settimeout(None)
            zajem = subprocess.Popen(ukaz_zajema(LINK_IZHOD + ".monitor", self.ffmpeg), stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, bufsize=0, env=_okolje())
            with self._kljuc:
                if seja != self._seja:
                    zajem.kill()
                    return
                self._zajem, self._odjemalec, self.stanje = zajem, odjemalec, "tece"
            self._sporoci()
            # Naprava lahko sejo konca tudi sama (zapre povezavo): to zazna bralec.
            threading.Thread(target=self._bdi, args=(odjemalec, seja), name="safeer-zvok-bdi", daemon=True).start()
            while True:
                podatki = zajem.stdout.read(KOS)
                if not podatki:
                    break
                odjemalec.sendall(bytes([OKVIR_ZVOK]) + len(podatki).to_bytes(4, "big") + podatki)
        except (OSError, ssl.SSLError, ValueError, AttributeError):
            pass
        finally:
            _zapri(odjemalec)
            if seja == self._seja:
                print("[zvok] seja z napravo koncana, zvok gre nazaj na racunalnik", flush=True)
                self.ustavi()

    def _sprejmi(self, posluh: socket.socket, ctx: ssl.SSLContext):
        """Caka napravo s pravim zetonom. Kdor pride s napacnim (ali brez TLS), ne dobi nicesar in
        seje tudi ne podre - naprava, ki ji je zvok namenjen, se lahko se vedno poveze."""
        konec = time.monotonic() + CAKANJE_S
        while time.monotonic() < konec:
            posluh.settimeout(max(0.1, konec - time.monotonic()))
            surov, _ = posluh.accept()
            odjemalec = None
            try:
                surov.settimeout(10)
                odjemalec = ctx.wrap_socket(surov, server_side=True)
                pozdrav = self._preberi_vrstico(odjemalec)
                if pozdrav.startswith("SAFEER-ZVOK ") and secrets.compare_digest(
                        pozdrav.split(" ", 1)[1].strip(), self._zeton):
                    return odjemalec
            except (OSError, ssl.SSLError, ValueError):
                pass
            _zapri(odjemalec if odjemalec is not None else surov)
        return None

    def _bdi(self, odjemalec, seja: int) -> None:
        try:
            while seja == self._seja:
                if not odjemalec.recv(64):
                    break
        except (OSError, ssl.SSLError, ValueError):
            pass
        if seja == self._seja:
            z = self._zajem
            if z is not None:
                try:
                    z.kill()
                except Exception:
                    pass

    @staticmethod
    def _preberi_vrstico(s, najvec: int = 256) -> str:
        b = b""
        while len(b) < najvec:
            c = s.recv(1)
            if not c or c == b"\n":
                break
            b += c
        return b.decode("utf-8", "replace")

    # ------------------------------------------------------------------ konec
    def ustavi(self, obnovi: bool = True) -> bool:
        """Konca sejo. obnovi=True vrne zvok prejsnjemu izhodu in odstrani navidezni izhod."""
        with self._kljuc:
            imel = bool(self.naprava)
            self._seja += 1
            zajem = self._zajem
            if zajem is not None:
                try:
                    zajem.kill()
                    zajem.wait(timeout=2)
                except Exception:
                    pass
                try:
                    zajem.stdout.close()
                except Exception:
                    pass
            for s in (self._odjemalec, self._posluh):
                _zapri(s)
            self._zajem = self._odjemalec = self._posluh = None
            self.naprava, self.ime, self.stanje = "", "", ""
            if obnovi:
                self._obnovi_izhod()
        if imel:
            self._sporoci()
        return imel

    def _obnovi_izhod(self) -> None:
        cilj = self._prejsnji if self._prejsnji in izhodi() else ""
        try:
            if cilj:
                _pactl("set-default-sink", cilj)
                premakni_vse(cilj)
            if self._modul.isdigit():
                _pactl("unload-module", self._modul)
            else:
                for v in _vrstice("list", "modules", "short"):
                    if len(v) > 2 and v[1] == "module-null-sink" and ("sink_name=" + LINK_IZHOD) in v[2]:
                        _pactl("unload-module", v[0])
        except Exception:
            pass
        self._prejsnji, self._modul = "", ""
