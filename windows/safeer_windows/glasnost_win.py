"""Prava sistemska glasnost Windows (Core Audio IAudioEndpointVolume prek ctypes, brez dodatnih paketov).

Safeer Agent in daljinec (Link `volume`) sta prej spreminjala samo stevilko navideznega zaslona - zvok racunalnika se
ni spremenil. Lastnik, 13. 10. 2026: naprava je privzeto pripravljena na upravljanje z agentom, zato ukaz zares deluje.
Vse funkcije vrnejo None, ce glasnosti ni mogoce brati (ni Windows, ni zvocne naprave)."""
from __future__ import annotations

import ctypes
import sys
from typing import Optional

_WIN = sys.platform == "win32"


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, besedilo: str) -> None:
        super().__init__()
        h = besedilo.strip("{}").replace("-", "")
        self.Data1, self.Data2, self.Data3 = int(h[0:8], 16), int(h[8:12], 16), int(h[12:16], 16)
        for i in range(8):
            self.Data4[i] = int(h[16 + 2 * i:18 + 2 * i], 16)


_CLSID_ENUM = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
_IID_ENUM = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
_IID_GLASNOST = "{5CDF2C82-841E-4546-9722-0CF74078229A}"
_CLSCTX_ALL = 23
_HR = ctypes.c_long


def _metoda(obj: ctypes.c_void_p, indeks: int, *tipi):
    """Metoda COM objekta po mestu v tabeli (vtable)."""
    tabela = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(_HR, ctypes.c_void_p, *tipi)(tabela[indeks])


def _sprosti(obj: ctypes.c_void_p) -> None:
    if obj:
        tabela = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(tabela[2])(obj)


def _z_glasnostjo(delo, vmesnik: str = ""):
    """Odpre privzeto izhodno napravo, poklice delo(glasnost) in vse sprosti."""
    if not _WIN:
        return None
    ole = ctypes.windll.ole32
    ole.CoInitializeEx(None, 0)          # vecnitno; ce je nit ze inicializirana drugace, COM vseeno deluje
    enum, naprava, glasnost = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    try:
        clsid, iid = _GUID(_CLSID_ENUM), _GUID(_IID_ENUM)
        if ole.CoCreateInstance(ctypes.byref(clsid), None, _CLSCTX_ALL, ctypes.byref(iid), ctypes.byref(enum)) != 0:
            return None
        # IMMDeviceEnumerator::GetDefaultAudioEndpoint(eRender, eMultimedia)
        if _metoda(enum, 4, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(
                enum, 0, 1, ctypes.byref(naprava)) != 0:
            return None
        iid_g = _GUID(vmesnik or _IID_GLASNOST)
        # IMMDevice::Activate
        if _metoda(naprava, 3, ctypes.POINTER(_GUID), ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
                naprava, ctypes.byref(iid_g), _CLSCTX_ALL, None, ctypes.byref(glasnost)) != 0:
            return None
        return delo(glasnost)
    except Exception:  # noqa: BLE001
        return None
    finally:
        for o in (glasnost, naprava, enum):
            _sprosti(o)


def _beri(g) -> dict:
    raven, utisano = ctypes.c_float(), ctypes.c_int()
    _metoda(g, 9, ctypes.POINTER(ctypes.c_float))(g, ctypes.byref(raven))           # GetMasterVolumeLevelScalar
    _metoda(g, 15, ctypes.POINTER(ctypes.c_int))(g, ctypes.byref(utisano))          # GetMute
    return {"level": int(round(raven.value * 100)), "muted": bool(utisano.value)}


def stanje() -> Optional[dict]:
    """{"level": 0-100, "muted": bool} ali None."""
    return _z_glasnostjo(_beri)


def nastavi(smer: str = "", raven: Optional[int] = None, korak: int = 5) -> Optional[dict]:
    """Enako kot Link `volume`: raven 0-100 ali smer up/down/mute/unmute/toggle_mute. Vrne novo stanje ali None."""
    def delo(g):
        zdaj = _beri(g)
        nova, utisaj = None, None
        if raven is not None:
            try:
                nova, utisaj = max(0, min(100, int(raven))), False
            except (TypeError, ValueError):
                return zdaj
        elif smer == "up":
            nova, utisaj = min(100, zdaj["level"] + korak), False
        elif smer == "down":
            nova = max(0, zdaj["level"] - korak)
        elif smer == "mute":
            utisaj = True
        elif smer == "unmute":
            utisaj = False
        elif smer == "toggle_mute":
            utisaj = not zdaj["muted"]
        if nova is not None:
            _metoda(g, 7, ctypes.c_float, ctypes.c_void_p)(g, ctypes.c_float(nova / 100.0), None)  # SetMasterVolumeLevelScalar
        if utisaj is not None:
            _metoda(g, 14, ctypes.c_int, ctypes.c_void_p)(g, int(utisaj), None)                   # SetMute
        return _beri(g)
    return _z_glasnostjo(delo)


_IID_MERILNIK = "{C02216F6-8C67-4B5B-9D00-D008E73E0064}"


def zveni(vzorcev: int = 6, razmik: float = 0.05) -> Optional[bool]:
    """Ali iz racunalnika zdaj prihaja zvok (IAudioMeterInformation::GetPeakValue). Locuje »pavza« od »nadaljuj«,
    ker ima Windows samo eno tipko predvajaj/pavza. None, ce merilnika ni."""
    import time

    def delo(m):
        vrh = ctypes.c_float()
        for i in range(vzorcev):
            if _metoda(m, 3, ctypes.POINTER(ctypes.c_float))(m, ctypes.byref(vrh)) == 0 and vrh.value > 0.0005:
                return True
            if i + 1 < vzorcev:
                time.sleep(razmik)
        return False
    return _z_glasnostjo(delo, _IID_MERILNIK)
