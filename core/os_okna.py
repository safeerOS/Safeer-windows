"""Odprta okna programov za Safeer OS na racunalniku (EWMH prek Xlib, samo X11).

Do GTK4 je seznam dajal libwnck. libwnck je knjiznica GTK3 in se v procesu GTK4 ne da naloziti, zato isto preberemo
neposredno iz lastnosti, ki jih vodi upravitelj oken (EWMH: _NET_CLIENT_LIST_STACKING, _NET_ACTIVE_WINDOW,
_NET_WM_STATE, _NET_WM_NAME, WM_CLASS, _NET_WM_ICON) in mu dejanja posljemo kot sporocila (_NET_ACTIVE_WINDOW,
_NET_CLOSE_WINDOW, _NET_SHOWING_DESKTOP, WM_CHANGE_STATE). Brez libwnck tudi ni vec njegovega sesutja
(20. 9. 2026: SIGSEGV v g_object_unref po force_update()).

Pravila, ki jih ta modul uveljavlja (enaka kot prej):

  1. Navzven gre samo stevilka (xid) in nizi. Okno se vedno poisce znova po xid, tik pred dejanjem.
  2. Vse samo iz glavne niti (povezava z X je ena). Klic iz druge niti vrne prazen seznam in se zabelezi.
  3. Vsaka napaka je ujeta: seznam oken ni nikoli razlog, da Safeer OS pade (napake X, ko okno izgine med branjem,
     pogoltne core/x11.py).
"""

from __future__ import annotations

import os
import threading
from typing import Callable, List, Optional

from core import x11

#: Kadar je nastavljeno (varni nacin po ponovljenem sesutju), seznama oken ni - vse ostalo dela.
IZKLOP = "SAFEER_OS_BREZ_OKEN"

_opozorilo_nit = False
_narocniki: list = []
_spremljam = False
#: Lastnosti korena, ob katerih spremembi so se okna spremenila (odprtje, zaprtje, menjava aktivnega).
_LASTNOSTI_SPREMEMBE = ("_NET_CLIENT_LIST", "_NET_CLIENT_LIST_STACKING", "_NET_ACTIVE_WINDOW")


def _dnevnik(*a) -> None:
    print("[SafeerOS okna]", *a)


def na_voljo() -> bool:
    """Ali imamo seznam oken (X11 z upraviteljem oken EWMH, brez varnega nacina)."""
    p = _pridobi()
    return p is not None and bool(p.stevila(p.koren, "_NET_SUPPORTED"))


def _glavna_nit() -> bool:
    global _opozorilo_nit
    if threading.current_thread() is threading.main_thread():
        return True
    if not _opozorilo_nit:
        _opozorilo_nit = True
        _dnevnik("klic iz niti", threading.current_thread().name, "- seznam oken je samo za glavno nit; preskocim")
    return False


_izklopljeno = False


def izklopi() -> None:
    """Varni nacin Safeer OS: brez seznama oken v tem procesu (prej okoljska spremenljivka IZKLOP, nastavljena v main(),
    ko so niti ze tekle)."""
    global _izklopljeno
    _izklopljeno = True


def izklopljen() -> bool:
    return _izklopljeno or bool(os.environ.get(IZKLOP))


def _pridobi():
    """Povezava z X (core/x11.py) ali None (varni nacin, druga nit, ni X11, seja Wayland).

    Wayland: tudi z GDK prek XWaylanda bi seznam pokazal samo programe XWayland - vrstica bi bila lazno nepopolna.
    Wayland seznama oken odjemalcu ne da (GNOME ga nima niti v razsiritvi), zato ga ni."""
    if izklopljen():
        return None
    from core import seja_prikaza
    if seja_prikaza.je_wayland():
        return None
    if not _glavna_nit():
        return None
    return x11.povezava()


def _ob_dogodku(*_a) -> bool:
    p = _pridobi()
    if p is None:
        return True
    try:
        spremembe = p.dogodki()
    except Exception as e:  # noqa: BLE001
        _dnevnik("dogodki:", e)
        return True
    if any(s in _LASTNOSTI_SPREMEMBE for s in spremembe):
        for f in list(_narocniki):
            try:
                f()
            except Exception as e:  # noqa: BLE001
                _dnevnik("narocnik:", e)
    return True


def spremljaj(ob_spremembi: Callable[[], None]) -> bool:
    """Naroci se na odprtje, zaprtje in menjavo aktivnega okna. Vrne, ali je narocilo uspelo."""
    global _spremljam
    p = _pridobi()
    if p is None:
        return False
    try:
        _narocniki.append(ob_spremembi)
        if not _spremljam:
            from gi.repository import GLib
            for ime in _LASTNOSTI_SPREMEMBE:      # ime_atoma pozna samo ze internirane atome
                p.atom(ime)
            opisnik = p.spremljaj_koren()
            GLib.io_add_watch(opisnik, GLib.PRIORITY_DEFAULT, GLib.IOCondition.IN, _ob_dogodku)
            # Xlib dogodke bere tudi med drugimi klici (odgovori na branje lastnosti) in jih hrani v vrsti -
            # takrat opisnik ni vec bralen. Zato vrsto pregledamo se vsako sekundo.
            GLib.timeout_add_seconds(1, _ob_dogodku)
            _spremljam = True
        return True
    except Exception as e:  # noqa: BLE001
        _dnevnik("narocilo na dogodke:", e)
        return False


def _stanja(p, xid: int) -> set:
    return set(p.stevila(xid, "_NET_WM_STATE"))


def _je_program(p, xid: int, nasi_xid: set) -> bool:
    """Navadno okno programa, ki sodi v opravilno vrstico (kot Wnck: vrsta NORMAL, brez skip_tasklist)."""
    if xid in nasi_xid:
        return False
    try:
        vrste = p.stevila(xid, "_NET_WM_WINDOW_TYPE")
        if vrste and vrste[0] != p.atom("_NET_WM_WINDOW_TYPE_NORMAL"):
            return False
        return p.atom("_NET_WM_STATE_SKIP_TASKBAR") not in _stanja(p, xid)
    except Exception:  # noqa: BLE001
        return False


def _okna(p) -> List[int]:
    """Okna po vrstnem redu zlaganja (spodaj -> zgoraj)."""
    return p.stevila(p.koren, "_NET_CLIENT_LIST_STACKING") or p.stevila(p.koren, "_NET_CLIENT_LIST")


def _aktivno(p) -> int:
    a = p.stevila(p.koren, "_NET_ACTIVE_WINDOW")
    return a[0] if a else 0


def _pomanjsano(p, xid: int) -> bool:
    return p.atom("_NET_WM_STATE_HIDDEN") in _stanja(p, xid)


def seznam(nasi_xid: Optional[set] = None, mapa_ikon: str = "", najvec_ikon: int = 200) -> List[dict]:
    """Odprta okna programov, najnovejse najprej. Samo podatki - noben objekt ne gre ven."""
    p = _pridobi()
    if p is None:
        return []
    nasi = set(nasi_xid or ())
    izhod: List[dict] = []
    try:
        aktivni_xid = _aktivno(p)
    except Exception:  # noqa: BLE001
        aktivni_xid = 0
    try:
        okna = _okna(p)
    except Exception as e:  # noqa: BLE001
        _dnevnik("seznam oken:", e)
        return []
    for xid in okna:
        if not _je_program(p, xid, nasi):
            continue
        try:
            ime = p.besedilo(xid, "_NET_WM_NAME") or p.besedilo(xid, "WM_NAME")
            izhod.append({
                "id": xid,
                "ime": ime or "",
                "program": p.razred(xid)[1] or "",
                "ikona": _ikona(p, xid, mapa_ikon) if mapa_ikon else "",
                "pomanjsano": _pomanjsano(p, xid),
                "aktivno": xid == aktivni_xid,
            })
        except Exception:  # noqa: BLE001
            continue     # okno je izginilo med branjem; to ni napaka
    izhod.reverse()
    if mapa_ikon:
        _pocisti_ikone(mapa_ikon, {o["id"] for o in izhod}, najvec_ikon)
    return izhod


def _izberi_ikono(podatki: list, zelena: int = 48):
    """Iz _NET_WM_ICON (sirina, visina, ARGB ...)* izbere velikost, najblizjo zeleni; (s, v, zacetek) ali None."""
    i, najboljsa = 0, None
    while i + 2 <= len(podatki):
        s, v = int(podatki[i]), int(podatki[i + 1])
        if s <= 0 or v <= 0 or i + 2 + s * v > len(podatki):
            break
        if najboljsa is None or abs(s - zelena) < abs(najboljsa[0] - zelena):
            najboljsa = (s, v, i + 2)
        i += 2 + s * v
    return najboljsa


def _ikona(p, xid: int, mapa: str) -> str:
    """Ikona okna, shranjena v datoteko (stran je ne more dobiti iz pomnilnika)."""
    pot = os.path.join(mapa, "okno-%d.png" % xid)
    if os.path.isfile(pot):
        return "file://" + pot
    try:
        podatki = p.stevila(xid, "_NET_WM_ICON")
        izbor = _izberi_ikono(podatki) if podatki else None
        if izbor is None:
            return ""
        s, v, zacetek = izbor
        rgba = bytearray(s * v * 4)
        for j, argb in enumerate(podatki[zacetek:zacetek + s * v]):
            k = j * 4
            rgba[k] = (argb >> 16) & 0xFF
            rgba[k + 1] = (argb >> 8) & 0xFF
            rgba[k + 2] = argb & 0xFF
            rgba[k + 3] = (argb >> 24) & 0xFF
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf, GLib
        pb = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(rgba)), GdkPixbuf.Colorspace.RGB, True, 8, s, v, s * 4)
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


def _pomanjsaj(p, xid: int) -> None:
    p.L.XIconifyWindow(p.dpy, xid, p.zaslon)


def _aktiviraj(p, xid: int, cas: int) -> None:
    # Vir 2 = pult/preklopnik (uporabnikovo dejanje): upravitelj oken okno res pokaze, ne le oznaci.
    p.sporocilo(xid, "_NET_ACTIVE_WINDOW", 2, cas & 0xFFFFFFFF, 0)


def dejanje(xid, kaj: str, cas: int = 0) -> bool:
    """Aktiviraj, pomanjsaj ali zapri okno. Okno poiscemo sveze - shranjenih podatkov ne uporabljamo."""
    p = _pridobi()
    if p is None:
        return False
    try:
        iskani = int(xid)
    except (TypeError, ValueError):
        return False
    try:
        if iskani not in _okna(p):
            return False
        if kaj == "zapri":
            p.sporocilo(iskani, "_NET_CLOSE_WINDOW", cas & 0xFFFFFFFF, 2)
        elif kaj == "preklopi" and _aktivno(p) == iskani and not _pomanjsano(p, iskani):
            _pomanjsaj(p, iskani)
        elif kaj == "pomanjsaj":
            if not _pomanjsano(p, iskani):
                _pomanjsaj(p, iskani)
        else:
            _aktiviraj(p, iskani, cas)
        p.poslji()
        return True
    except Exception as e:  # noqa: BLE001
        _dnevnik(kaj, e)
        return False


def pomanjsaj_vse(nasi_xid: Optional[set] = None, cas: int = 0) -> int:
    """Pomanjsa vsa okna programov (gumb Domov). Vrne, koliko jih je bilo pomanjsanih."""
    p = _pridobi()
    if p is None:
        return 0
    nasi = set(nasi_xid or ())
    koliko = 0
    try:
        okna = _okna(p)
    except Exception:  # noqa: BLE001
        return 0
    for xid in okna:
        if not _je_program(p, xid, nasi):
            continue
        try:
            if not _pomanjsano(p, xid):
                _pomanjsaj(p, xid)
                koliko += 1
        except Exception:  # noqa: BLE001
            continue
    try:
        p.poslji()
    except Exception:  # noqa: BLE001
        pass
    return koliko


def pokazi_namizje() -> bool:
    """Pokaze namizje (okna se umaknejo kot pri Super+D), da je iskalna lupa vidna; klicati na glavni niti.
    False, ce seznama oken ni (ni X11, varni nacin)."""
    p = _pridobi()
    if not p:
        return False
    try:
        p.sporocilo(p.koren, "_NET_SHOWING_DESKTOP", 1)
        p.poslji()
        return True
    except Exception:  # noqa: BLE001
        return False
