"""Varnostna vrata namizja Safeer OS na Windows: vedno je pot nazaj na obicajno namizje Windows.

Pravilo lastnika (25. 10. 2026): vsaka tema/namizje Safeer ima »varnostna vrata«, ki vrnejo privzeto namizje naprave
- vedno dosegljiva, tudi ce namizje (QML) odpove, in samodejno po ponavljajocih sesutjih; nazaj z enim klikom.

Na Windows je namizje Safeer OS okno pod vsemi okni (Raziskovalec in opravilna vrstica tecejo naprej). Vrata:
1. Nastavitve Safeer OS -> »Safeer OS kot namizje« (stikalo, en klik tja in nazaj) in meni desnega klika na namizju
   -> »Obicajno namizje Windows«.
2. Bliznjica Ctrl+Alt+Shift+W - sistemska (RegisterHotKey v svoji niti z lastno zanko sporocil), zato dela tudi, ko
   QML ne odgovarja ali se ni nalozil.
3. Samodejno: ce se Safeer OS z namizjem NAJVEC_ZAGONOV-krat zapored zazene in ne tece STABILNO_S sekund (sesutje ob
   zagonu), se namizje izklopi in ostane obicajno namizje Windows; vklopis ga z enim klikom v Nastavitvah.
   Tudi namizje, ki se sploh ne nalozi (napaka QML), se takoj izklopi.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Callable, Tuple

NAJVEC_ZAGONOV = 3          # toliko zagonov brez stabilnega delovanja -> obicajno namizje Windows
OKNO_S = 15 * 60            # steti se samo zagoni v zadnjih 15 minutah
STABILNO_S = 90             # namizje, ki tece toliko casa, ni sesuto: stevec se pocisti

# Bliznjica: Ctrl+Alt+Shift+W (»W« kot Windows). MOD_NOREPEAT: drzanje tipk je en pritisk.
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x0001, 0x0002, 0x0004, 0x4000
VK_W = 0x57
WM_HOTKEY = 0x0312
ID_BLIZNJICE = 0x5AFE
BLIZNJICA = "Ctrl+Alt+Shift+W"


# ------------------------------------------------------------------ ciste funkcije (windows/tests/test_varnostna_vrata.py)
def ob_zagonu(zapis: dict, zdaj: float) -> Tuple[bool, dict]:
    """(pokazi_namizje, nov_zapis). Zapis hrani case zagonov z namizjem, ki se niso izkazali za stabilne."""
    zacetki = []
    for t in (zapis or {}).get("zacetki") or []:
        try:
            t = float(t)
        except (TypeError, ValueError):
            continue
        if 0 <= zdaj - t < OKNO_S:
            zacetki.append(t)
    if len(zacetki) >= NAJVEC_ZAGONOV:
        return False, {"zacetki": [], "izklopljeno_ob": zdaj, "razlog": "sesutja"}
    return True, {"zacetki": zacetki + [zdaj]}


def stabilno(zapis: dict) -> dict:
    """Namizje tece STABILNO_S: zagon ni bil sesutje - stevec se pocisti (zadnji samodejni izklop ostane zapisan)."""
    z = {"zacetki": []}
    for k in ("izklopljeno_ob", "razlog"):
        if (zapis or {}).get(k) is not None:
            z[k] = zapis[k]
    return z


# ------------------------------------------------------------------ zapis na disku
def _pot() -> str:
    mapa = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "SafeerOS")
    os.makedirs(mapa, exist_ok=True)
    return os.path.join(mapa, "namizje-zagoni.json")


def beri() -> dict:
    try:
        with open(_pot(), encoding="utf-8") as f:
            z = json.load(f)
        return z if isinstance(z, dict) else {}
    except (OSError, ValueError):
        return {}


def pisi(zapis: dict) -> None:
    pot = _pot()
    try:
        with open(pot + ".tmp", "w", encoding="utf-8") as f:
            json.dump(zapis, f)
        os.replace(pot + ".tmp", pot)
    except OSError:
        pass


# ------------------------------------------------------------------ sistemska bliznjica
def zazeni_bliznjico(ob_pritisku: Callable[[], None]) -> bool:
    """Ctrl+Alt+Shift+W kjerkoli v Windows -> ob_pritisku() (iz niti bliznjice; klicatelj preda glavni niti).
    Vrne False, ce ni Windows; ce je bliznjico ze zasedel drug program, to zapise v dnevnik."""
    if sys.platform != "win32":
        return False

    def nit() -> None:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        if not u.RegisterHotKey(None, ID_BLIZNJICE, MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_NOREPEAT, VK_W):
            print(f"[SafeerOS] Varnostna vrata: bliznjice {BLIZNJICA} ni mogoce prijaviti (zasedena?)", flush=True)
            return
        print(f"[SafeerOS] Varnostna vrata: {BLIZNJICA} vrne obicajno namizje Windows", flush=True)
        msg = wintypes.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam == ID_BLIZNJICE:
                try:
                    ob_pritisku()
                except Exception as e:  # noqa: BLE001
                    print(f"[SafeerOS] Varnostna vrata: {e}", flush=True)

    threading.Thread(target=nit, name="safeer-varnostna-vrata", daemon=True).start()
    return True


def zdaj() -> float:
    return time.time()
