"""Navidezna namizja Windows (Pogled opravil, Win+Ctrl+D) v preklopniku Prostori Safeer OS.

Ocena (25. 10. 2026): javni vmesnik IVirtualDesktopManager zna samo povedati, na katerem namizju je okno, in okno
premakniti - seznama namizij in preklopa nima. Nedokumentiran IVirtualDesktopManagerInternal se med gradnjami Windows
spreminja (drug GUID v 10, 11 21H2, 22H2, 24H2), zato ga ne uporabljamo. Varna pot, ki dela v Windows 10 in 11:
- seznam in trenutno namizje beremo iz registra Raziskovalca (HKCU ...\\Explorer\\VirtualDesktops: VirtualDesktopIDs,
  CurrentVirtualDesktop, Desktops\\{GUID}\\Name; v Windows 10 je trenutno pod ...\\Explorer\\SessionInfo\\<seja>);
- preklop je ista bliznjica, ki jo pritisne uporabnik: Ctrl+Win+Levo/Desno tolikokrat, kolikor je namizij do cilja.
Ce registra ni (en sam desktop, Windows Server), seznam je prazen in Prostori pokazejo samo naprave.
"""

from __future__ import annotations

import sys
import time
import uuid
from typing import Dict, List, Optional, Tuple

_KLJUC = r"Software\Microsoft\Windows\CurrentVersion\Explorer\VirtualDesktops"
NAJVEC_NAMIZIJ = 20
VK_LWIN, VK_CONTROL, VK_LEFT, VK_RIGHT = 0x5B, 0x11, 0x25, 0x27
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001


def guidi(podatki) -> List[str]:
    """REG_BINARY z zaporedjem 16-bajtnih GUID-ov (bytes_le) -> ['{...}', ...] (najvec NAJVEC_NAMIZIJ)."""
    if not isinstance(podatki, (bytes, bytearray)):
        return []
    izid = []
    for i in range(0, len(podatki) - len(podatki) % 16, 16):
        izid.append("{%s}" % str(uuid.UUID(bytes_le=bytes(podatki[i:i + 16]))).upper())
        if len(izid) >= NAJVEC_NAMIZIJ:
            break
    return izid


def seznam_iz(ids, trenutno, imena: Dict[str, str], jezik: str = "sl") -> Tuple[List[dict], int]:
    """Cisto: (namizja [{id, ime, indeks, trenutno}], indeks trenutnega ali -1). Neimenovano namizje dobi ime, kot ga
    pokaze Windows (»Namizje 2«)."""
    seznam = guidi(ids)
    tren = (guidi(trenutno) or [""])[0]
    napis = {"sl": "Namizje", "en": "Desktop", "de": "Desktop", "es": "Escritorio", "fr": "Bureau", "it": "Desktop"}.get(jezik, "Desktop")
    izid = []
    for i, g in enumerate(seznam):
        ime = str((imena or {}).get(g) or "").strip()[:60] or "%s %d" % (napis, i + 1)
        izid.append({"id": g, "ime": ime, "indeks": i, "trenutno": g == tren})
    return izid, next((n["indeks"] for n in izid if n["trenutno"]), -1)


def koraki(od: int, do: int) -> Tuple[int, int]:
    """(tipka, stevilo pritiskov) za preklop z namizja `od` na `do` (Ctrl+Win+Levo/Desno)."""
    if od < 0 or do < 0 or od == do:
        return 0, 0
    return (VK_RIGHT, do - od) if do > od else (VK_LEFT, od - do)


def _beri() -> Tuple[Optional[bytes], Optional[bytes], Dict[str, str]]:
    import winreg
    ids = tren = None
    imena: Dict[str, str] = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KLJUC) as k:
            try:
                ids = winreg.QueryValueEx(k, "VirtualDesktopIDs")[0]
            except OSError:
                pass
            try:
                tren = winreg.QueryValueEx(k, "CurrentVirtualDesktop")[0]       # Windows 11
            except OSError:
                pass
    except OSError:
        return None, None, {}
    if tren is None:                                                          # Windows 10: po seji
        try:
            import ctypes
            seja = ctypes.c_ulong()
            ctypes.windll.kernel32.ProcessIdToSessionId(ctypes.windll.kernel32.GetCurrentProcessId(), ctypes.byref(seja))
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\SessionInfo"
                                                         "\\%d\\VirtualDesktops" % seja.value) as k:
                tren = winreg.QueryValueEx(k, "CurrentVirtualDesktop")[0]
        except OSError:
            pass
    for g in guidi(ids):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KLJUC + "\\Desktops\\" + g) as k:
                imena[g] = str(winreg.QueryValueEx(k, "Name")[0])
        except OSError:
            pass
    return ids, tren, imena


def seznam(jezik: str = "sl") -> Tuple[List[dict], int]:
    """Navidezna namizja tega uporabnika; prazno, ce jih Windows ne vodi (ali je eno samo)."""
    if sys.platform != "win32":
        return [], -1
    try:
        ids, tren, imena = _beri()
    except Exception:  # noqa: BLE001
        return [], -1
    namizja, i = seznam_iz(ids, tren, imena, jezik)
    return (namizja, i) if len(namizja) > 1 else ([], -1)


def preklopi(indeks: int, jezik: str = "sl") -> bool:
    """Preklop na navidezno namizje `indeks` (Ctrl+Win+Levo/Desno, kot bi pritisnil uporabnik)."""
    if sys.platform != "win32":
        return False
    namizja, tren = seznam(jezik)
    if not namizja or not (0 <= int(indeks) < len(namizja)) or tren < 0:
        return False
    tipka, n = koraki(tren, int(indeks))
    if not n:
        return True
    import ctypes
    u = ctypes.windll.user32
    u.keybd_event(VK_CONTROL, 0, 0, 0)
    u.keybd_event(VK_LWIN, 0, KEYEVENTF_EXTENDEDKEY, 0)
    try:
        for _ in range(n):
            u.keybd_event(tipka, 0, KEYEVENTF_EXTENDEDKEY, 0)
            u.keybd_event(tipka, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)
            time.sleep(0.12)                    # animacija preklopa; brez premora Windows pritiske zdruzi
    finally:
        u.keybd_event(VK_LWIN, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)
        u.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
    return True
