"""Odprta okna programov za Safeer OS na racunalniku (libwnck, samo X11).

Zakaj svoj modul: 20. 9. 2026 se je Safeer OS sesul (SIGSEGV v g_object_unref -> g_hash_table_remove)
med obdelavo sporocila iz strani. Vzrok je bila raba libwnck:

  * `Wnck.Screen.force_update()` se je klical ob vsakem branju seznama oken. Ta klic sinhrono
    prebere stanje iz X in pri tem unici objekte oken, ki so medtem izginila. PyGObject na vsak
    vrnjen objekt doda svojo referenco; ko jo pozneje spusti, libwnck ze unicen objekt odstrani
    iz svoje razpredelnice - in prav to je pot, po kateri se je proces sesul.
  * Objekti oken so bili uporabljeni po tem, ko jih je libwnck ze zavrgel.

Pravila, ki jih ta modul uveljavlja:

  1. `force_update()` samo enkrat, ob prvi uporabi. Potem se Wnck osvezuje sam iz dogodkov X
     (glavna zanka tece), kar je tudi edina podprta raba.
  2. Navzven ne gre noben objekt libwnck - samo stevilke in nizi. Okno se vedno poisce znova
     po xid, tik pred dejanjem.
  3. Vse samo iz glavne niti. Klic iz druge niti vrne prazen seznam in se zabelezi, namesto da
     bi tvegal sesutje.
  4. Vsaka napaka je ujeta: seznam oken ni nikoli razlog, da Safeer OS pade.
"""

from __future__ import annotations

import os
import threading
from typing import Callable, List, Optional

#: Kadar je nastavljeno (varni nacin po ponovljenem sesutju), seznama oken ni - vse ostalo dela.
IZKLOP = "SAFEER_OS_BREZ_OKEN"

_zaslon = None            # Wnck.Screen ali False, ce ga ni
_wnck = None              # modul gi.repository.Wnck
_osvezen = False          # force_update() smo naredili natanko enkrat
_opozorilo_nit = False


def _dnevnik(*a) -> None:
    print("[SafeerOS okna]", *a)


def na_voljo() -> bool:
    """Ali imamo seznam oken (X11 z libwnck, brez varnega nacina)."""
    return _pridobi() is not None


def _glavna_nit() -> bool:
    global _opozorilo_nit
    if threading.current_thread() is threading.main_thread():
        return True
    if not _opozorilo_nit:
        _opozorilo_nit = True
        _dnevnik("klic iz niti", threading.current_thread().name, "- libwnck je samo za glavno nit; preskocim")
    return False


def _pridobi():
    """Wnck.Screen ali None. Prvi klic naredi force_update(), pozneje nikoli vec."""
    global _zaslon, _wnck, _osvezen
    if os.environ.get(IZKLOP):
        return None
    if not _glavna_nit():
        return None
    if _zaslon is None:
        try:
            import gi
            gi.require_version("Wnck", "3.0")
            from gi.repository import Wnck
            Wnck.set_client_type(Wnck.ClientType.PAGER)
            _wnck = Wnck
            _zaslon = Wnck.Screen.get_default()
        except Exception as e:  # noqa: BLE001
            _dnevnik("libwnck ni na voljo:", e)
            _zaslon = False
    if _zaslon in (False, None):
        return None
    if not _osvezen:
        # Edini force_update v zivljenju procesa: da imamo seznam ze pred prvim dogodkom X.
        try:
            _zaslon.force_update()
        except Exception as e:  # noqa: BLE001
            _dnevnik("force_update:", e)
        _osvezen = True
    return _zaslon


def spremljaj(ob_spremembi: Callable[[], None]) -> bool:
    """Naroci se na odprtje, zaprtje in menjavo aktivnega okna. Vrne, ali je narocilo uspelo."""
    zaslon = _pridobi()
    if zaslon is None:
        return False
    try:
        for signal in ("window-opened", "window-closed", "active-window-changed"):
            zaslon.connect(signal, lambda *_a: ob_spremembi())
        return True
    except Exception as e:  # noqa: BLE001
        _dnevnik("narocilo na dogodke:", e)
        return False


def _je_program(okno, nasi_xid: set) -> bool:
    try:
        return (okno.get_window_type() == _wnck.WindowType.NORMAL
                and not okno.is_skip_tasklist()
                and okno.get_xid() not in nasi_xid)
    except Exception:  # noqa: BLE001
        return False


def seznam(nasi_xid: Optional[set] = None, mapa_ikon: str = "", najvec_ikon: int = 200) -> List[dict]:
    """Odprta okna programov, najnovejse najprej. Samo podatki - noben objekt libwnck ne gre ven."""
    zaslon = _pridobi()
    if zaslon is None:
        return []
    nasi = set(nasi_xid or ())
    izhod: List[dict] = []
    try:
        aktivno = zaslon.get_active_window()
        aktivni_xid = aktivno.get_xid() if aktivno is not None else 0
    except Exception:  # noqa: BLE001
        aktivni_xid = 0
    try:
        okna = list(zaslon.get_windows_stacked() or [])
    except Exception as e:  # noqa: BLE001
        _dnevnik("seznam oken:", e)
        return []
    for okno in okna:
        if not _je_program(okno, nasi):
            continue
        try:
            xid = okno.get_xid()
            izhod.append({
                "id": xid,
                "ime": okno.get_name() or "",
                "program": okno.get_class_group_name() or "",
                "ikona": _ikona(okno, xid, mapa_ikon) if mapa_ikon else "",
                "pomanjsano": bool(okno.is_minimized()),
                "aktivno": xid == aktivni_xid,
            })
        except Exception:  # noqa: BLE001
            continue     # okno je izginilo med branjem; to ni napaka
    izhod.reverse()
    if mapa_ikon:
        _pocisti_ikone(mapa_ikon, {o["id"] for o in izhod}, najvec_ikon)
    return izhod


def _ikona(okno, xid: int, mapa: str) -> str:
    """Ikona okna, shranjena v datoteko (stran je ne more dobiti iz pomnilnika)."""
    pot = os.path.join(mapa, "okno-%d.png" % xid)
    if os.path.isfile(pot):
        return "file://" + pot
    try:
        pb = okno.get_icon()
        if pb is None:
            return ""
        os.makedirs(mapa, exist_ok=True)
        zacasna = pot + ".tmp"
        pb.savev(zacasna, "png", [], [])
        os.replace(zacasna, pot)
        return "file://" + pot
    except Exception:  # noqa: BLE001
        return ""


def _pocisti_ikone(mapa: str, zivi: set, najvec: int) -> None:
    """Ikone zaprtih oken se ne smejo nabirati brez konca."""
    try:
        imena = [i for i in os.listdir(mapa) if i.startswith("okno-") and i.endswith(".png")]
        if len(imena) <= najvec:
            return
        for ime in imena:
            try:
                xid = int(ime[5:-4])
            except ValueError:
                continue
            if xid not in zivi:
                try:
                    os.remove(os.path.join(mapa, ime))
                except OSError:
                    pass
    except OSError:
        pass


def dejanje(xid, kaj: str, cas: int = 0) -> bool:
    """Aktiviraj, pomanjsaj ali zapri okno. Okno poiscemo sveze - shranjenih objektov ne uporabljamo."""
    zaslon = _pridobi()
    if zaslon is None:
        return False
    try:
        iskani = int(xid)
    except (TypeError, ValueError):
        return False
    try:
        okna = list(zaslon.get_windows() or [])
    except Exception as e:  # noqa: BLE001
        _dnevnik("dejanje:", e)
        return False
    for okno in okna:
        try:
            if okno.get_xid() != iskani:
                continue
            if kaj == "zapri":
                okno.close(cas)
            elif kaj == "preklopi" and okno.is_active() and not okno.is_minimized():
                okno.minimize()
            elif kaj == "pomanjsaj":
                if not okno.is_minimized():
                    okno.minimize()
            else:
                okno.activate(cas)
            return True
        except Exception as e:  # noqa: BLE001
            _dnevnik(kaj, e)
            return False
    return False


def pomanjsaj_vse(nasi_xid: Optional[set] = None, cas: int = 0) -> int:
    """Pomanjsa vsa okna programov (gumb Domov). Vrne, koliko jih je bilo pomanjsanih."""
    zaslon = _pridobi()
    if zaslon is None:
        return 0
    nasi = set(nasi_xid or ())
    koliko = 0
    try:
        okna = list(zaslon.get_windows_stacked() or [])
    except Exception:  # noqa: BLE001
        return 0
    for okno in okna:
        if not _je_program(okno, nasi):
            continue
        try:
            if not okno.is_minimized():
                okno.minimize()
                koliko += 1
        except Exception:  # noqa: BLE001
            continue
    return koliko
