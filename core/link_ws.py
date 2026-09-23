"""Streznikova stran WebSocketa za Safeer Hub na racunalniku.

Odjemalec (WsOdjemalec v core/link_hub.py) zna govoriti s Hubom na televizorju; tu je druga stran
iste zice, da je lahko Hub tudi racunalnik. Namenoma zna malo in nima odvisnosti: rokovanje,
besedilni okvirji, ping/pong in zakljucek.

Dve pravili iz meritve na televizorju (krog 35b), ki veljata tudi tu:

  * **pisanje ima svojo nit in vrsto.** Blokirajoce pisanje na napravo, ki ne bere, je zadrzalo
    vse ostale. Vsaka povezava ima zato izhodno vrsto in enega pisca;
  * **naprava, ki ne bere, izpade.** Ko se vrsta napolni, povezavo zapremo, namesto da bi rasel
    pomnilnik.

Okvirji: odjemalec -> streznik so **maskirani** (tako zahteva standard), streznik -> odjemalec
nemaskirani. Vse drugo je enako kot pri odjemalcu.
"""

from __future__ import annotations

import base64
import collections
import hashlib
import os
import socket
import struct
import threading
from typing import Callable, Deque, Optional

CAROBNI_NIZ = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OPKODA_NADALJEVANJE = 0x0
OPKODA_BESEDILO = 0x1
OPKODA_DVOJISKO = 0x2
OPKODA_ZAPRI = 0x8
OPKODA_PING = 0x9
OPKODA_PONG = 0xA

#: Najvecje sporocilo, ki ga sprejmemo (naprava nam ne sme napolniti pomnilnika).
NAJVECJE_SPOROCILO = 1024 * 1024
#: Koliko okvirjev sme cakati v izhodni vrsti, preden napravo razglasimo za gluho.
NAJVEC_V_VRSTI = 64
NAJVEC_BAJTOV_V_VRSTI = 512 * 1024
#: Tisina, po kateri posljemo ping; po treh brez odziva povezavo zapremo.
PING_VSAKIH_S = 25.0
NAJVEC_TIHIH_KROGOV = 3
#: Koliko cakamo, da pisec odda zakljucek, preden vticnico zapremo.
ZAPIRALNI_ROK_S = 0.3


def sprejemni_kljuc(kljuc: str) -> str:
    """Vrednost glave Sec-WebSocket-Accept za dani Sec-WebSocket-Key."""
    izvlecek = hashlib.sha1((kljuc.strip() + CAROBNI_NIZ).encode("ascii")).digest()
    return base64.b64encode(izvlecek).decode("ascii")


def odgovor_rokovanja(kljuc: str) -> bytes:
    return ("HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Accept: " + sprejemni_kljuc(kljuc) + "\r\n\r\n").encode("ascii")


def okvir(opkoda: int, podatki: bytes) -> bytes:
    """Nemaskiran okvir strezniku -> odjemalcu."""
    dolzina = len(podatki)
    glava = bytes([0x80 | opkoda])
    if dolzina < 126:
        glava += bytes([dolzina])
    elif dolzina < 65536:
        glava += bytes([126]) + struct.pack(">H", dolzina)
    else:
        glava += bytes([127]) + struct.pack(">Q", dolzina)
    return glava + podatki


class Povezava:
    """Ena povezana naprava: branje v klicateljevi niti, pisanje v svoji.

    `ob_sporocilu(povezava, besedilo)` dobi vsako besedilno sporocilo; `ob_koncu(povezava)` se
    poklice natanko enkrat, ko povezave ni vec.
    """

    def __init__(self, vticnik: socket.socket, naslov: str,
                 ob_sporocilu: Callable[["Povezava", str], None],
                 ob_koncu: Optional[Callable[["Povezava"], None]] = None) -> None:
        self.vticnik = vticnik
        self.naslov = naslov
        self.ob_sporocilu = ob_sporocilu
        self.ob_koncu = ob_koncu
        self.podatki: dict = {}          # kar si o napravi zapomni Hub (id, ime, vloga ...)
        self._vrsta: Deque[bytes] = collections.deque()
        self._bajtov = 0
        self._zaklep = threading.Lock()
        self._ima_kaj = threading.Event()
        self._zaprta = False
        self._pisec: Optional[threading.Thread] = None
        self._medpomnilnik = b""

    # ------------------------------------------------------------------ pisanje

    def poslji(self, besedilo: str) -> bool:
        return self._v_vrsto(okvir(OPKODA_BESEDILO, besedilo.encode("utf-8")))

    def _v_vrsto(self, surovo: bytes) -> bool:
        with self._zaklep:
            if self._zaprta:
                return False
            if len(self._vrsta) >= NAJVEC_V_VRSTI or self._bajtov + len(surovo) > NAJVEC_BAJTOV_V_VRSTI:
                # Naprava ne bere. Ce bi cakali nanjo, bi zadrzala vse ostale.
                self._zaprta = True
                self._ima_kaj.set()
                try:
                    self.vticnik.close()
                except Exception:
                    pass
                return False
            self._vrsta.append(surovo)
            self._bajtov += len(surovo)
        self._ima_kaj.set()
        return True

    def _zanka_pisanja(self) -> None:
        while True:
            self._ima_kaj.wait()
            with self._zaklep:
                if not self._vrsta:
                    self._ima_kaj.clear()
                    if self._zaprta:
                        return
                    continue
                surovo = self._vrsta.popleft()
                self._bajtov -= len(surovo)
            try:
                self.vticnik.sendall(surovo)
            except Exception:
                with self._zaklep:
                    self._zaprta = True
                return

    # ------------------------------------------------------------------ branje

    def _preberi(self, koliko: int) -> bytes:
        while len(self._medpomnilnik) < koliko:
            kos = self.vticnik.recv(65536)
            if not kos:
                raise ConnectionError("povezava je zaprta")
            self._medpomnilnik += kos
        izhod, self._medpomnilnik = self._medpomnilnik[:koliko], self._medpomnilnik[koliko:]
        return izhod

    def zanka_branja(self) -> None:
        """Bere, dokler povezava zivi. Konca s klicem ob_koncu."""
        self._pisec = threading.Thread(target=self._zanka_pisanja, daemon=True)
        self._pisec.start()
        zbrano = b""
        zbrana_opkoda = -1
        tihih = 0
        try:
            while not self._zaprta:
                try:
                    prvi, drugi = self._preberi(2)
                except socket.timeout:
                    tihih += 1
                    if tihih > NAJVEC_TIHIH_KROGOV:
                        break
                    self._v_vrsto(okvir(OPKODA_PING, b""))
                    continue
                tihih = 0
                zakljucen = bool(prvi & 0x80)
                opkoda = prvi & 0x0F
                maskiran = bool(drugi & 0x80)
                dolzina = drugi & 0x7F
                if not maskiran:
                    break          # odjemalec mora maskirati; kdor ne, ni skladen
                if dolzina == 126:
                    dolzina = struct.unpack(">H", self._preberi(2))[0]
                elif dolzina == 127:
                    dolzina = struct.unpack(">Q", self._preberi(8))[0]
                if dolzina > NAJVECJE_SPOROCILO:
                    break
                maska = self._preberi(4)
                telo = bytes(b ^ maska[i % 4] for i, b in enumerate(self._preberi(dolzina)))
                if opkoda == OPKODA_ZAPRI:
                    break
                if opkoda == OPKODA_PING:
                    self._v_vrsto(okvir(OPKODA_PONG, telo))
                    continue
                if opkoda == OPKODA_PONG:
                    continue
                if opkoda != OPKODA_NADALJEVANJE:
                    zbrana_opkoda = opkoda
                    zbrano = b""
                zbrano += telo
                if not zakljucen:
                    continue
                if zbrana_opkoda == OPKODA_BESEDILO:
                    try:
                        sporocilo = zbrano.decode("utf-8")
                    except UnicodeDecodeError:
                        zbrano = b""
                        continue
                    try:
                        self.ob_sporocilu(self, sporocilo)
                    except Exception:
                        pass
                zbrano = b""
        except Exception:
            pass
        finally:
            self.zapri()
            if self.ob_koncu is not None:
                try:
                    self.ob_koncu(self)
                except Exception:
                    pass

    # ------------------------------------------------------------------ konec

    def zapri(self, koda: int = 1000, razlog: str = "") -> None:
        """Zapre povezavo. Zakljucek odda pisec; ce se je zataknil, po kratkem roku nehamo cakati."""
        with self._zaklep:
            if self._zaprta:
                bil_odprt = False
            else:
                bil_odprt = True
                self._zaprta = True
        if bil_odprt:
            telo = struct.pack(">H", koda) + razlog.encode("utf-8")[:120]
            try:
                self.vticnik.sendall(okvir(OPKODA_ZAPRI, telo))
            except Exception:
                pass
        self._ima_kaj.set()
        pisec = self._pisec
        if pisec is not None and pisec is not threading.current_thread():
            pisec.join(ZAPIRALNI_ROK_S)
        try:
            self.vticnik.close()
        except Exception:
            pass

    @property
    def zaprta(self) -> bool:
        return self._zaprta


def kljuc_iz_glav(glave: dict) -> str:
    """Sec-WebSocket-Key iz glav (imena glav so neobcutljiva na velikost crk)."""
    for ime, vrednost in glave.items():
        if ime.lower() == "sec-websocket-key":
            return str(vrednost).strip()
    return ""


def je_nadgradnja(glave: dict) -> bool:
    upgrade = ""
    for ime, vrednost in glave.items():
        if ime.lower() == "upgrade":
            upgrade = str(vrednost).strip().lower()
    return upgrade == "websocket" and bool(kljuc_iz_glav(glave))


def nakljucni(bajtov: int = 24) -> str:
    return base64.urlsafe_b64encode(os.urandom(bajtov)).decode("ascii").rstrip("=")
