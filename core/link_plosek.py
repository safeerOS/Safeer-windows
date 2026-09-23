"""Navidezni igralni plosek racunalnika (Safeer Desktop Stream).

Ko uporabnik na televizorju upravlja racunalnik, so gumbi njegovega plosecka doslej postali
tipke in miska. Za vmesnike je to prav, za igre pa ne: igra, ki hoce plosek, ga ni videla, ker
tipkovnica pac ni plosek.

Tu naredimo na racunalniku **navidezni plosek** prek jedrnega vmesnika `uinput`. Za sistem je to
navaden igralni plosek (Linux ga vidi kot `/dev/input/eventN` in `/dev/input/jsN`), zato ga vidi
vsaka igra, SDL, Steam, Wine - brez posebne podpore v igri in brez tuje kode.

Zavestno brez zunanjih knjiznic: uinput je nekaj struktur in trije ioctli, odvisnost pa bi
moral vsak uporabnik namestiti. Vse, kar pride z omrezja, gre skozi seznam dovoljenega: televizor
poslje **oznako** gumba ali osi (`a`, `start`, `leva_x` ...), nikoli stevilke jedra.

Dostop: `/dev/uinput` je pri vecini distribucij dostopen samo rootu. Safeer Control ga zato
uporabi le, kadar je dostopen (glej `Plosek.mozno()`); pravilo udev, ki napravo odpre skupini
`input`, je v packaging/99-safeer-uinput.rules in ga namesti uporabnik sam.
"""

from __future__ import annotations

import fcntl
import os
import struct
import time
from typing import Dict, Optional

POT = "/dev/uinput"

# ------------------------------------------------------------------ jedrne oznake (linux/input-event-codes.h)
EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
SYN_REPORT = 0
ABS_CNT = 0x40


def _iow(vrsta: str, st: int, velikost: int) -> int:
    """_IOW iz linux/ioctl.h za 32-bitno celo stevilo."""
    return (1 << 30) | (velikost << 16) | (ord(vrsta) << 8) | st


def _io(vrsta: str, st: int) -> int:
    return (ord(vrsta) << 8) | st


UI_DEV_CREATE = _io("U", 1)
UI_DEV_DESTROY = _io("U", 2)
UI_SET_EVBIT = _iow("U", 100, 4)
UI_SET_KEYBIT = _iow("U", 101, 4)
UI_SET_ABSBIT = _iow("U", 103, 4)

#: Gumbi, ki jih televizor sme poslati, in njihove kode v jedru. Imena so nasa in enaka tistim,
#: ki jih poslje Safeer OS (os/ZaslonVnos.kt).
GUMBI: Dict[str, int] = {
    "a": 0x130,          # BTN_SOUTH
    "b": 0x131,          # BTN_EAST
    "x": 0x134,          # BTN_WEST
    "y": 0x133,          # BTN_NORTH
    "l1": 0x136,         # BTN_TL
    "r1": 0x137,         # BTN_TR
    "l2": 0x138,         # BTN_TL2
    "r2": 0x139,         # BTN_TR2
    "izbira": 0x13A,     # BTN_SELECT
    "zacni": 0x13B,      # BTN_START
    "domov": 0x13C,      # BTN_MODE
    "palica_l": 0x13D,   # BTN_THUMBL
    "palica_r": 0x13E,   # BTN_THUMBR
}

#: Osi: oznaka -> (koda, najmanj, najvec). Palice so simetricne, sprozilca gresta od nic.
OSI: Dict[str, tuple] = {
    "leva_x": (0x00, -32767, 32767),     # ABS_X
    "leva_y": (0x01, -32767, 32767),     # ABS_Y
    "desna_x": (0x03, -32767, 32767),    # ABS_RX
    "desna_y": (0x04, -32767, 32767),    # ABS_RY
    "sprozilec_l": (0x02, 0, 255),       # ABS_Z
    "sprozilec_r": (0x05, 0, 255),       # ABS_RZ
    "krizec_x": (0x10, -1, 1),           # ABS_HAT0X
    "krizec_y": (0x11, -1, 1),           # ABS_HAT0Y
}

IME = "Safeer plosek"
#: Izmisljen, a stalen par vendor/product, da si ga igre zapomnijo med sejami.
VENDOR, PRODUCT, VERSION, BUSTYPE = 0x5AFE, 0x0001, 0x0001, 0x03  # BUS_USB

_DOGODEK = struct.Struct("@llHHi")


class Plosek:
    """Navidezni plosek; brez dostopa do /dev/uinput ne naredi nicesar in to tudi pove."""

    def __init__(self, pot: str = POT) -> None:
        self.pot = pot
        self._fd: Optional[int] = None
        self.napaka = ""
        self._drzani: Dict[str, bool] = {}

    # ------------------------------------------------------------------ stanje

    def mozno(self) -> bool:
        """Ali smemo pisati v /dev/uinput (sicer plosecka ne obljubljamo)."""
        return os.path.exists(self.pot) and os.access(self.pot, os.W_OK)

    @property
    def odprt(self) -> bool:
        return self._fd is not None

    # ------------------------------------------------------------------ zivljenje naprave

    def odpri(self) -> bool:
        """Naredi navidezni plosek. Vrne True, kadar ga sistem res vidi."""
        if self._fd is not None:
            return True
        if not self.mozno():
            self.napaka = "uinput ni dostopen"
            return False
        try:
            fd = os.open(self.pot, os.O_WRONLY | os.O_NONBLOCK)
        except OSError as e:
            self.napaka = "uinput ni bilo mogoce odpreti: %s" % e
            return False
        try:
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_ABS)
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
            for koda in GUMBI.values():
                fcntl.ioctl(fd, UI_SET_KEYBIT, koda)
            najvec = [0] * ABS_CNT
            najmanj = [0] * ABS_CNT
            for koda, spodaj, zgoraj in OSI.values():
                fcntl.ioctl(fd, UI_SET_ABSBIT, koda)
                najmanj[koda] = spodaj
                najvec[koda] = zgoraj
            opis = struct.pack("@80sHHHHI" + "i" * (4 * ABS_CNT),
                               IME.encode("ascii", "replace")[:79],
                               BUSTYPE, VENDOR, PRODUCT, VERSION, 0,
                               *(najvec + najmanj + [0] * ABS_CNT + [0] * ABS_CNT))
            os.write(fd, opis)
            fcntl.ioctl(fd, UI_DEV_CREATE)
        except OSError as e:
            os.close(fd)
            self.napaka = "navideznega plosecka ni bilo mogoce narediti: %s" % e
            return False
        self._fd = fd
        self.napaka = ""
        # Sistem potrebuje trenutek, da napravo objavi (udev); brez tega prvi dogodki padejo v nic.
        time.sleep(0.1)
        self._sredina()
        return True

    def zapri(self) -> None:
        """Spusti vse in odstrani navidezni plosek. Klicemo ob koncu seje."""
        # Zapreta ga lahko hkrati dve niti (konec slike in konec vnosa); kdor prvi vzame
        # opisnik, ga zapre, drugi nima vec cesa - prej je to padlo s TypeError.
        if self._fd is None:
            return
        try:
            self.sprosti_vse()
        except (OSError, TypeError):
            pass
        fd, self._fd = self._fd, None
        self._drzani = {}
        if fd is None:
            return
        try:
            fcntl.ioctl(fd, UI_DEV_DESTROY)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass

    # ------------------------------------------------------------------ dogodki

    def gumb(self, oznaka: str, pritisnjen: bool) -> bool:
        koda = GUMBI.get(str(oznaka or "").strip().lower())
        if koda is None or not self._zagotovi():
            return False
        if not self._poslji(EV_KEY, koda, 1 if pritisnjen else 0):
            return False
        self._drzani[str(oznaka).strip().lower()] = bool(pritisnjen)
        return self._sinhroniziraj()

    def os(self, oznaka: str, vrednost) -> bool:
        """Odklon osi kot ulomek: palice od -1.0 do 1.0, sprozilca od 0.0 do 1.0."""
        podatki = OSI.get(str(oznaka or "").strip().lower())
        if podatki is None or not self._zagotovi():
            return False
        koda, spodaj, zgoraj = podatki
        try:
            delez = float(vrednost)
        except (TypeError, ValueError):
            return False
        if delez != delez:            # NaN z omrezja
            return False
        delez = max(-1.0, min(1.0, delez))
        surovo = int(round(delez * zgoraj)) if spodaj < 0 else int(round(max(0.0, delez) * zgoraj))
        surovo = max(spodaj, min(zgoraj, surovo))
        if not self._poslji(EV_ABS, koda, surovo):
            return False
        return self._sinhroniziraj()

    def sprosti_vse(self) -> None:
        """Spusti vse gumbe in postavi osi na sredino - konec seje ne sme pustiti pritisnjenega gumba."""
        if self._fd is None:
            return
        for oznaka, drzan in list(self._drzani.items()):
            if drzan:
                self._poslji(EV_KEY, GUMBI[oznaka], 0)
        self._drzani = {}
        self._sredina()

    def _sredina(self) -> None:
        for koda, spodaj, zgoraj in OSI.values():
            self._poslji(EV_ABS, koda, 0 if spodaj < 0 else 0)
        self._sinhroniziraj()

    # ------------------------------------------------------------------ pisanje

    def _zagotovi(self) -> bool:
        return self._fd is not None or self.odpri()

    def _poslji(self, vrsta: int, koda: int, vrednost: int) -> bool:
        if self._fd is None:
            return False
        zdaj = time.time()
        zapis = _DOGODEK.pack(int(zdaj), int((zdaj % 1) * 1_000_000), vrsta, koda, vrednost)
        try:
            os.write(self._fd, zapis)
        except OSError as e:
            self.napaka = "plosecku ni bilo mogoce pisati: %s" % e
            return False
        return True

    def _sinhroniziraj(self) -> bool:
        return self._poslji(EV_SYN, SYN_REPORT, 0)


__all__ = ["Plosek", "GUMBI", "OSI", "POT"]
