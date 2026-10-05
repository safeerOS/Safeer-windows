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

from core import link_vticnik
from core.link_datoteke import TLS_MAPA, zagotovi_potrdilo

LINK_IZHOD = "safeer_link_zvok"
ZMOZNOST = "audio"
ZVOK_HZ, ZVOK_KANALI = 48000, 2
OKVIR_ZVOK, OKVIR_OBVESTILO = 2, 3
#: 10 ms zvoka v enem okvirju: dovolj majhno za kratko zakasnitev, dovolj veliko za malo glav.
KOS = ZVOK_HZ * ZVOK_KANALI * 2 // 100
#: Toliko casa naprava dobi, da se poveze, preden sejo opustimo in vrnemo zvok racunalniku.
CAKANJE_S = 20
#: Najdlje sme pisanje enega okvirja cakati na napravo. Zvok tece ves cas in naprava ga bere sproti; kdor toliko
#: casa ne vzame nobenega bajta, ga ni vec (ugasnjen, brez omrezja). Brez te omejitve je seja visela, dokler ni
#: obupalo jedro (cetrt ure ali nikoli) - racunalnik je bil ves ta cas brez zvoka.
ROK_PISANJA_S = 20.0


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


#: Najvec naslovov, ki jih nastejemo drugi napravi - vsakega poskusi posebej, vsak neuspeh stane nekaj sekund.
NAJVEC_NASLOVOV = 4
#: Vmesniki, prek katerih druge naprave v omrezju do nas ne pridejo: vsebniki, navidezni stroji, njihovi mostovi.
#: Uporabnikov most "br0" (naslov omrezja je na njem) ni med njimi - Docker svoje imenuje "br-<oznaka>".
NAVIDEZNI_VMESNIKI = ("docker", "br-", "veth", "virbr", "vmnet", "vboxnet", "lxc", "lxd", "podman", "cni",
                      "flannel", "cali", "kube", "dummy")
_IFF_UP, _IFF_LOOPBACK, _IFF_POINTOPOINT = 0x1, 0x8, 0x10


def naslovi_vmesnikov() -> List[tuple]:
    """(ime, naslov IPv4, zastavice) omreznih vmesnikov tega racunalnika.

    Linux pove ime in zastavice (predor VPN ima POINTOPOINT). Windows da samo naslove, ki jih ima ime
    racunalnika - ime je takrat prazno, zastavica samo "vklopljen"."""
    try:
        import fcntl
        import struct
    except ImportError:
        try:
            return [("", n, _IFF_UP) for n in socket.gethostbyname_ex(socket.gethostname())[2]]
        except Exception:
            return []
    izid: List[tuple] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError:
        return izid
    try:
        for _st, ime in socket.if_nameindex():
            zahteva = struct.pack("256s", ime.encode("utf-8", "replace")[:15])
            try:
                naslov = socket.inet_ntoa(fcntl.ioctl(s.fileno(), 0x8915, zahteva)[20:24])           # SIOCGIFADDR
                zastavice = struct.unpack("H", fcntl.ioctl(s.fileno(), 0x8913, zahteva)[16:18])[0]   # SIOCGIFFLAGS
            except OSError:
                continue                    # vmesnik brez naslova IPv4
            izid.append((ime, naslov, zastavice))
    except OSError:
        pass
    finally:
        s.close()
    return izid


def naslov_na_poti(cilj: str) -> str:
    """Nas naslov na poti do `cilj`. Vticnica UDP ob connect() ne poslje nicesar - jedro samo izbere pot."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((cilj, 9))
            return str(s.getsockname()[0])
        finally:
            s.close()
    except Exception:
        return ""


def _stevilcni(gostitelj: str) -> bool:
    try:
        socket.inet_aton(gostitelj)
        return gostitelj.count(".") == 3
    except (OSError, TypeError, ValueError):
        return False


def lastni_naslovi(hub_url: str = "", vmesniki=None, na_poti=None) -> List[str]:
    """Naslovi IPv4, na katerih nas druga naprava v omrezju doseze - najverjetnejsi najprej, najvec NAJVEC_NASLOVOV.

    1. naslov na poti do huba (kadar hub tece drugje);
    2. naslovi vmesnikov krajevnega omrezja, tisti na privzeti poti prvi;
    3. naslov na privzeti poti in naslovi predorov (VPN) - nazadnje.

    Prej smo nasteli samo naslov na privzeti poti. Racunalnik, ki ves promet posilja skozi VPN, je napravi v
    istem omrezju tako povedal naslov predora, do katerega ta ne pride (zvok na napravo, zaslon racunalnika).
    `vmesniki` in `na_poti` sta za preizkuse."""
    vmesniki = naslovi_vmesnikov if vmesniki is None else vmesniki
    na_poti = naslov_na_poti if na_poti is None else na_poti
    gostitelj = ""
    if hub_url:
        try:
            from urllib.parse import urlparse
            gostitelj = urlparse(hub_url).hostname or ""
        except Exception:
            gostitelj = ""
    kandidati: List[str] = []
    # Samo stevilcni naslov huba: ime (rele Global Linka) bi pomenilo poizvedbo DNS, pot do njega pa je privzeta.
    if _stevilcni(gostitelj):
        kandidati.append(na_poti(gostitelj))
    try:
        znani = list(vmesniki() or [])
    except Exception:
        znani = []
    privzeti = na_poti("192.0.2.1")         # naslov iz dokumentacijskega obsega: pot do njega je privzeta pot
    krajevni, predori = [], []
    for zapis in znani:
        try:
            ime, naslov, zastavice = str(zapis[0] or ""), str(zapis[1] or ""), int(zapis[2])
        except (IndexError, TypeError, ValueError):
            continue
        if not zastavice & _IFF_UP or zastavice & _IFF_LOOPBACK or ime.startswith(NAVIDEZNI_VMESNIKI):
            continue
        (predori if zastavice & _IFF_POINTOPOINT else krajevni).append(naslov)
    if privzeti in krajevni:
        kandidati.append(privzeti)
    kandidati += krajevni
    kandidati.append(privzeti)
    kandidati += predori
    if not znani:
        # Sistem vmesnikov ne pove: kot prej naslova na poti do dveh pogostih domacih omrezij.
        kandidati += [na_poti("192.168.0.1"), na_poti("10.0.0.1")]
    naslovi: List[str] = []
    for n in kandidati:
        if n and _stevilcni(n) and not n.startswith("127.") and n != "0.0.0.0" and n not in naslovi:
            naslovi.append(n)
    return naslovi[:NAJVEC_NASLOVOV]


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
            # Zvok pise ta nit, konec seje pa na isti povezavi caka bralna nit (_bdi): vticnica TLS dveh niti
            # sama ne prenese (core/link_vticnik.py). Branje caka poljubno dolgo, pisanje ne.
            odjemalec = link_vticnik.zavaruj(odjemalec)
            if isinstance(odjemalec, link_vticnik.VarnaTls):
                odjemalec.nastavi_rok_pisanja(ROK_PISANJA_S)
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
                # Okvir zvoka (10 ms) naj gre takoj, ne sele po potrditvi prejsnjega (Naglov algoritem).
                link_vticnik.brez_zamika(surov)
                odjemalec = ctx.wrap_socket(surov, server_side=True)
                pozdrav = self._preberi_vrstico(odjemalec)
                # Primerjamo bajte: compare_digest z nizom, ki ni cisti ASCII, vrze TypeError - tuj pozdrav bi
                # tako koncal sejo, namesto da bi bil le zavrnjen.
                if pozdrav.startswith("SAFEER-ZVOK ") and self._zeton and secrets.compare_digest(
                        pozdrav.split(" ", 1)[1].strip().encode("utf-8"), self._zeton.encode("utf-8")):
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
