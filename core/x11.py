"""Najmanj Xlib (ctypes) za Safeer OS na GTK4: lastnosti oken EWMH, seznam oken, zajem zaslona.

Zakaj: GTK4 nima vec set_type_hint, set_keep_below/above, stick, move, set_wmclass in set_skip_*_hint na oknu,
libwnck (GTK3) pa se v procesu GTK4 ne da naloziti. Vse to so le lastnosti X in sporocila upravitelju oken (EWMH),
zato jih nastavimo sami prek libX11 - brez dodatnih paketov (prej tudi xprop za rezervacijo vrstice).

Pravila:
  * Svoja povezava z X (ne GDK-jeva): napake na njej (okno je medtem izginilo) samo zabelezimo - privzeti Xlib bi
    ob BadWindow koncal ves proces. Napake drugih povezav (GDK) gredo naprej prejsnjemu rokovalniku.
  * Povezava `povezava()` je samo za glavno nit; nit (zajem zaslona) odpre svojo (`Povezava()`).
  * Brez X11 (Wayland, ni libX11) vse vrne False / prazno - nic ne pade.
  * Seja Wayland (core/seja_prikaza.py): povezave z X ne odpremo, tudi ce je DISPLAY nastavljen. Tam je X le XWayland
    za stare programe: seznam oken ima samo programe XWayland, GNOME 46 XWayland ob prvi povezavi sele zazene, zajem
    korena pa ne vidi namizja (izmerjeno 18. 10. 2026, brezglavi sway 1.9 z XWaylandom, ozadje #203040: XGetImage
    korena ne uspe, ffmpeg x11grab da crno sliko - 3 od 28 500 vzorcev ne-crnih, grim prek Waylanda pa ozadje).
    Izjema so nasa okna, ce GDK sam tece prek XWaylanda (GDK_BACKEND=x11) - takrat so lastnosti oken prave.
"""

from __future__ import annotations

import ctypes
import os
import threading
from ctypes import POINTER, byref, c_char_p, c_int, c_long, c_uint, c_ulong, c_void_p
from typing import Callable, List, Optional

_SUCCESS = 0
_PROP_MODE_REPLACE = 0
_ANY_PROPERTY_TYPE = 0
_XA_ATOM = 4
_XA_CARDINAL = 6
_XA_WINDOW = 33
_CLIENT_MESSAGE = 33
_PROPERTY_NOTIFY = 28
_PROPERTY_CHANGE_MASK = 1 << 22
_SUBSTRUCTURE_NOTIFY_MASK = 1 << 19
_SUBSTRUCTURE_REDIRECT_MASK = 1 << 20
_Z_PIXMAP = 2
_ALL_PLANES = 0xFFFFFFFFFFFFFFFF if ctypes.sizeof(c_ulong) == 8 else 0xFFFFFFFF


class _XClientMessageEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p),
                ("window", c_ulong), ("message_type", c_ulong), ("format", c_int), ("data", c_long * 5)]


class _XPropertyEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", c_int), ("display", c_void_p),
                ("window", c_ulong), ("atom", c_ulong), ("time", c_ulong), ("state", c_int)]


class _XEvent(ctypes.Union):
    _fields_ = [("type", c_int), ("xclient", _XClientMessageEvent), ("xproperty", _XPropertyEvent),
                ("pad", c_long * 24)]


class _XErrorEvent(ctypes.Structure):
    _fields_ = [("type", c_int), ("display", c_void_p), ("resourceid", c_ulong), ("serial", c_ulong),
                ("error_code", ctypes.c_ubyte), ("request_code", ctypes.c_ubyte), ("minor_code", ctypes.c_ubyte)]


class _XClassHint(ctypes.Structure):
    _fields_ = [("res_name", c_char_p), ("res_class", c_char_p)]


class _XImage(ctypes.Structure):
    # Samo zacetek strukture (do mask) - dovolj za branje slike; unici jo XDestroyImage.
    _fields_ = [("width", c_int), ("height", c_int), ("xoffset", c_int), ("format", c_int), ("data", c_void_p),
                ("byte_order", c_int), ("bitmap_unit", c_int), ("bitmap_bit_order", c_int), ("bitmap_pad", c_int),
                ("depth", c_int), ("bytes_per_line", c_int), ("bits_per_pixel", c_int),
                ("red_mask", c_ulong), ("green_mask", c_ulong), ("blue_mask", c_ulong)]


class _XRRMonitorInfo(ctypes.Structure):
    _fields_ = [("name", c_ulong), ("primary", c_int), ("automatic", c_int), ("noutput", c_int),
                ("x", c_int), ("y", c_int), ("width", c_int), ("height", c_int), ("mwidth", c_int), ("mheight", c_int),
                ("outputs", c_void_p)]


_ROKOVALNIK = ctypes.CFUNCTYPE(c_int, c_void_p, POINTER(_XErrorEvent))
_lib = None
_nasi_zasloni: set = set()          # povezave tega modula: njihove napake pogoltnemo
_prejsnji_rokovalnik = None
_nas_rokovalnik = None
_zaklep = threading.Lock()


def _na_napako(dpy, napaka) -> int:
    if dpy in _nasi_zasloni or _prejsnji_rokovalnik is None:
        return 0                    # okno je izginilo med branjem: to ni napaka, ki bi smela koncati proces
    return _prejsnji_rokovalnik(dpy, napaka)


_zaklep_knjiznice = threading.Lock()


def _knjiznica():
    """libX11 z nastavljenimi podpisi; None brez X11. Prvi klic naj bo v glavni niti (rokovalnik napak)."""
    if _lib is not None:
        return _lib or None
    with _zaklep_knjiznice:
        return _nalozi_knjiznico()


def _nalozi_knjiznico():
    global _lib, _prejsnji_rokovalnik, _nas_rokovalnik
    if _lib is not None:
        return _lib or None
    try:
        L = ctypes.cdll.LoadLibrary("libX11.so.6")
    except OSError:
        _lib = False
        return None
    podpisi = {
        "XOpenDisplay": (c_void_p, [c_char_p]),
        "XCloseDisplay": (c_int, [c_void_p]),
        "XDefaultRootWindow": (c_ulong, [c_void_p]),
        "XDefaultScreen": (c_int, [c_void_p]),
        "XInternAtom": (c_ulong, [c_void_p, c_char_p, c_int]),
        "XGetWindowProperty": (c_int, [c_void_p, c_ulong, c_ulong, c_long, c_long, c_int, c_ulong, POINTER(c_ulong),
                                       POINTER(c_int), POINTER(c_ulong), POINTER(c_ulong), POINTER(c_void_p)]),
        "XChangeProperty": (c_int, [c_void_p, c_ulong, c_ulong, c_ulong, c_int, c_int, c_void_p, c_int]),
        "XDeleteProperty": (c_int, [c_void_p, c_ulong, c_ulong]),
        "XSendEvent": (c_int, [c_void_p, c_ulong, c_int, c_long, POINTER(_XEvent)]),
        "XMoveWindow": (c_int, [c_void_p, c_ulong, c_int, c_int]),
        "XIconifyWindow": (c_int, [c_void_p, c_ulong, c_int]),
        "XSetClassHint": (c_int, [c_void_p, c_ulong, POINTER(_XClassHint)]),
        "XGetClassHint": (c_int, [c_void_p, c_ulong, POINTER(_XClassHint)]),
        "XSelectInput": (c_int, [c_void_p, c_ulong, c_long]),
        "XConnectionNumber": (c_int, [c_void_p]),
        "XPending": (c_int, [c_void_p]),
        "XNextEvent": (c_int, [c_void_p, POINTER(_XEvent)]),
        "XGetImage": (POINTER(_XImage), [c_void_p, c_ulong, c_int, c_int, c_uint, c_uint, c_ulong, c_int]),
        "XDestroyImage": (c_int, [POINTER(_XImage)]),
        "XGetGeometry": (c_int, [c_void_p, c_ulong, POINTER(c_ulong), POINTER(c_int), POINTER(c_int),
                                 POINTER(c_uint), POINTER(c_uint), POINTER(c_uint), POINTER(c_uint)]),
        "XFlush": (c_int, [c_void_p]),
        "XSync": (c_int, [c_void_p, c_int]),
        "XFree": (c_int, [c_void_p]),
        "XSetErrorHandler": (c_void_p, [_ROKOVALNIK]),
        "XQueryPointer": (c_int, [c_void_p, c_ulong, POINTER(c_ulong), POINTER(c_ulong), POINTER(c_int),
                                  POINTER(c_int), POINTER(c_int), POINTER(c_int), POINTER(c_uint)]),
        "XGetAtomName": (c_void_p, [c_void_p, c_ulong]),
    }
    try:
        for ime, (vrne, argumenti) in podpisi.items():
            f = getattr(L, ime)
            f.restype, f.argtypes = vrne, argumenti
    except AttributeError:
        _lib = False
        return None
    _nas_rokovalnik = _ROKOVALNIK(_na_napako)
    prejsnji = L.XSetErrorHandler(_nas_rokovalnik)
    _prejsnji_rokovalnik = _ROKOVALNIK(prejsnji) if prejsnji else None
    _lib = L
    return L


class Povezava:
    """Ena povezava z X (XOpenDisplay). OSError, ce X11 ni na voljo ali je seja Wayland.

    za_nasa_okna=True: povezava za lastnosti oken tega procesa - na Waylandu dovoljena samo, ce GDK tece prek X11."""

    def __init__(self, za_nasa_okna: bool = False) -> None:
        from core import seja_prikaza
        if seja_prikaza.je_wayland() and not (za_nasa_okna and seja_prikaza.gdk_x11()):
            raise OSError("seja Wayland: X11 je samo XWayland")
        L = _knjiznica()
        if L is None or not os.environ.get("DISPLAY"):
            raise OSError("X11 ni na voljo")
        self.L = L
        self.dpy = L.XOpenDisplay(None)
        if not self.dpy:
            raise OSError("X11 ni na voljo")
        _nasi_zasloni.add(self.dpy)
        self.koren = L.XDefaultRootWindow(self.dpy)
        self.zaslon = L.XDefaultScreen(self.dpy)
        self._atomi: dict = {}

    def zapri(self) -> None:
        if self.dpy:
            _nasi_zasloni.discard(self.dpy)
            self.L.XCloseDisplay(self.dpy)
            self.dpy = None

    def atom(self, ime: str) -> int:
        a = self._atomi.get(ime)
        if a is None:
            a = self._atomi[ime] = int(self.L.XInternAtom(self.dpy, ime.encode(), 0))
        return a

    def ime_atoma(self, atom: int) -> str:
        for ime, a in self._atomi.items():
            if a == atom:
                return ime
        return ""

    # --- lastnosti
    def _preberi(self, okno: int, ime: str, vrsta: int = _ANY_PROPERTY_TYPE, najvec: int = 1 << 20):
        """(format, surovi podatki, stevilo) ali None."""
        dejanska, fmt, n, ostane, kazalec = c_ulong(), c_int(), c_ulong(), c_ulong(), c_void_p()
        izid = self.L.XGetWindowProperty(self.dpy, okno, self.atom(ime), 0, najvec, 0, vrsta, byref(dejanska),
                                         byref(fmt), byref(n), byref(ostane), byref(kazalec))
        if izid != _SUCCESS or not kazalec.value:
            return None
        try:
            if fmt.value == 32:
                # Format 32 je v Xlib vedno tabela C long (8 bajtov na 64-bitnih sistemih).
                vrednosti = list((c_long * n.value).from_address(kazalec.value))
                return 32, vrednosti, n.value
            if fmt.value == 8:
                return 8, ctypes.string_at(kazalec.value, n.value), n.value
            return None
        finally:
            self.L.XFree(kazalec)

    def stevila(self, okno: int, ime: str) -> List[int]:
        """Lastnost formata 32 (ATOM, CARDINAL, WINDOW) kot nepredznacena stevila."""
        r = self._preberi(okno, ime)
        if not r or r[0] != 32:
            return []
        # Vrednosti formata 32 so 32-bitne; Xlib jih da v C long s predznakom (0xFFFFFFFF -> -1).
        return [v & 0xFFFFFFFF for v in r[1]]

    def besedilo(self, okno: int, ime: str) -> str:
        r = self._preberi(okno, ime)
        if not r or r[0] != 8:
            return ""
        return r[1].split(b"\0", 1)[0].decode("utf-8", "replace")

    def nastavi_stevila(self, okno: int, ime: str, vrsta: int, vrednosti: List[int]) -> None:
        tabela = (c_long * max(1, len(vrednosti)))(*[ctypes.c_long(v).value for v in vrednosti])
        self.L.XChangeProperty(self.dpy, okno, self.atom(ime), vrsta, 32, _PROP_MODE_REPLACE,
                               ctypes.cast(tabela, c_void_p), len(vrednosti))

    def razred(self, okno: int) -> tuple:
        h = _XClassHint()
        if not self.L.XGetClassHint(self.dpy, okno, byref(h)):
            return "", ""
        try:
            return ((h.res_name or b"").decode("utf-8", "replace"), (h.res_class or b"").decode("utf-8", "replace"))
        finally:
            # c_char_p je ze kopija; kazalca sprostimo prek surovih naslovov.
            for polje in ("res_name", "res_class"):
                naslov = ctypes.c_void_p.from_buffer(h, getattr(_XClassHint, polje).offset).value
                if naslov:
                    self.L.XFree(naslov)

    def nastavi_razred(self, okno: int, ime: str, razred: str) -> None:
        h = _XClassHint(ime.encode(), razred.encode())
        self.L.XSetClassHint(self.dpy, okno, byref(h))

    # --- sporocila upravitelju oken (EWMH)
    def sporocilo(self, okno: int, vrsta: str, *podatki: int) -> None:
        d = _XEvent()
        d.xclient.type = _CLIENT_MESSAGE
        d.xclient.send_event = 1
        d.xclient.window = okno
        d.xclient.message_type = self.atom(vrsta)
        d.xclient.format = 32
        for i, v in enumerate(podatki[:5]):
            d.xclient.data[i] = ctypes.c_long(v).value
        self.L.XSendEvent(self.dpy, self.koren, 0, _SUBSTRUCTURE_REDIRECT_MASK | _SUBSTRUCTURE_NOTIFY_MASK, byref(d))

    def poslji(self) -> None:
        self.L.XFlush(self.dpy)

    # --- dogodki korenskega okna (seznam oken, aktivno okno)
    def spremljaj_koren(self) -> int:
        """Narocilo na spremembe lastnosti korenskega okna; vrne datotecni opisnik povezave."""
        self.L.XSelectInput(self.dpy, self.koren, _PROPERTY_CHANGE_MASK)
        self.L.XFlush(self.dpy)
        return int(self.L.XConnectionNumber(self.dpy))

    def dogodki(self) -> List[str]:
        """Prebere vse cakajoce dogodke; vrne imena spremenjenih lastnosti korena."""
        imena = []
        d = _XEvent()
        while self.L.XPending(self.dpy) > 0:
            self.L.XNextEvent(self.dpy, byref(d))
            if d.type == _PROPERTY_NOTIFY and d.xproperty.window == self.koren:
                imena.append(self.ime_atoma(d.xproperty.atom))
        return imena

    # --- zajem zaslona
    def velikost_korena(self) -> tuple:
        koren, x, y, s, v, rob, globina = c_ulong(), c_int(), c_int(), c_uint(), c_uint(), c_uint(), c_uint()
        if not self.L.XGetGeometry(self.dpy, self.koren, byref(koren), byref(x), byref(y), byref(s), byref(v),
                                   byref(rob), byref(globina)):
            return 0, 0
        return int(s.value), int(v.value)

    def zajemi(self, obmocje: Optional[tuple] = None):
        """Slika korenskega okna kot (sirina, visina, RGB bajti) ali None (le 24/32-bitni zasloni).

        obmocje=(x, y, sirina, visina) v pikah X: samo ta del (en monitor pri vec monitorjih, glej monitorji())."""
        sk, vk = self.velikost_korena()
        if not sk or not vk:
            return None
        x0, y0, s, v = 0, 0, sk, vk
        if obmocje:
            x0, y0 = max(0, int(obmocje[0])), max(0, int(obmocje[1]))
            s, v = min(int(obmocje[2]), sk - x0), min(int(obmocje[3]), vk - y0)
            if s <= 0 or v <= 0:
                return None
        slika = self.L.XGetImage(self.dpy, self.koren, x0, y0, s, v, _ALL_PLANES, _Z_PIXMAP)
        if not slika:
            return None
        try:
            si = slika.contents
            if si.bits_per_pixel != 32 or si.byte_order != 0:
                return None             # nenavaden zaslon (16-bitni, big-endian): zajema ne ponujamo
            vrstica = si.bytes_per_line
            surovo = ctypes.string_at(si.data, vrstica * si.height)
        finally:
            self.L.XDestroyImage(slika)
        if vrstica != s * 4:
            surovo = b"".join(surovo[i * vrstica:i * vrstica + s * 4] for i in range(v))
        # BGRX (little-endian, 24-bitna globina) -> RGB; rezine so v C, zato hitro tudi za 4K.
        rgb = bytearray(s * v * 3)
        rgb[0::3] = surovo[2::4]
        rgb[1::3] = surovo[1::4]
        rgb[2::3] = surovo[0::4]
        return s, v, bytes(rgb)

    # --- monitorji in kazalec (vec monitorjev)
    def monitorji(self) -> List[dict]:
        """Monitorji RandR 1.5 v pikah X: [{"ime", "x", "y", "sirina", "visina", "primarni"}], primarni prvi.

        Prazno brez libXrandr ali razsiritve RandR (takrat je en zaslon = koren)."""
        L = _xrandr()
        if L is None:
            return []
        n = c_int()
        tabela = L.XRRGetMonitors(self.dpy, self.koren, 1, byref(n))
        if not tabela:
            return []
        izid = []
        try:
            for i in range(n.value):
                m = tabela[i]
                ime = ""
                kazalec = self.L.XGetAtomName(self.dpy, m.name) if m.name else None
                if kazalec:
                    ime = ctypes.string_at(kazalec).decode("utf-8", "replace")
                    self.L.XFree(kazalec)
                izid.append({"ime": ime, "x": int(m.x), "y": int(m.y), "sirina": int(m.width),
                             "visina": int(m.height), "primarni": bool(m.primary)})
        finally:
            L.XRRFreeMonitors(tabela)
        izid.sort(key=lambda m: (not m["primarni"], m["x"], m["y"]))
        return izid

    def kazalec(self) -> Optional[tuple]:
        """(x, y) kazalca miske na korenu v pikah X ali None."""
        koren, otrok = c_ulong(), c_ulong()
        x, y, ox, oy, maska = c_int(), c_int(), c_int(), c_int(), c_uint()
        if not self.L.XQueryPointer(self.dpy, self.koren, byref(koren), byref(otrok), byref(x), byref(y),
                                    byref(ox), byref(oy), byref(maska)):
            return None
        return int(x.value), int(y.value)


_xrandr_lib = None


def _xrandr():
    """libXrandr (XRRGetMonitors, RandR 1.5) ali None."""
    global _xrandr_lib
    if _xrandr_lib is None:
        try:
            L = ctypes.cdll.LoadLibrary("libXrandr.so.2")
            L.XRRGetMonitors.restype = POINTER(_XRRMonitorInfo)
            L.XRRGetMonitors.argtypes = [c_void_p, c_ulong, c_int, POINTER(c_int)]
            L.XRRFreeMonitors.restype = None
            L.XRRFreeMonitors.argtypes = [POINTER(_XRRMonitorInfo)]
            _xrandr_lib = L
        except (OSError, AttributeError):
            _xrandr_lib = False
    return _xrandr_lib or None


def monitor_za_tocko(monitorji: List[dict], tocka: Optional[tuple]) -> Optional[dict]:
    """Monitor, na katerem je tocka (x, y); sicer primarni (prvi). None, ce monitorjev ni."""
    if not monitorji:
        return None
    if tocka is not None:
        x, y = tocka
        # Najmanjsi, ki tocko vsebuje: navidezni monitorji (xrandr --setmonitor) lahko prekrivajo izhod.
        vsebujejo = [m for m in monitorji if m["x"] <= x < m["x"] + m["sirina"] and m["y"] <= y < m["y"] + m["visina"]]
        if vsebujejo:
            return min(vsebujejo, key=lambda m: m["sirina"] * m["visina"])
    return monitorji[0]


def primarni_monitor(povezava_: Optional["Povezava"] = None) -> Optional[dict]:
    """Primarni monitor (pike X) za zajem enega zaslona; None brez X11 ali RandR. Odpre svojo povezavo, ce je ne dobi
    (klic iz niti)."""
    p, svoja = povezava_, False
    try:
        if p is None:
            p, svoja = Povezava(), True
        return monitor_za_tocko(p.monitorji(), None)
    except OSError:
        return None
    finally:
        if svoja and p is not None:
            p.zapri()


def monitor_s_kazalcem() -> Optional[dict]:
    """Monitor (pike X), na katerem je kazalec miske - tam uporabnik dela, tja odpremo novo okno. Samo glavna nit."""
    p = povezava()
    if p is None:
        return None
    try:
        return monitor_za_tocko(p.monitorji(), p.kazalec())
    except Exception:  # noqa: BLE001
        return None


_glavna: Optional[Povezava] = None


def povezava() -> Optional[Povezava]:
    """Skupna povezava za glavno nit; None brez X11 ali ce klic ni iz glavne niti."""
    global _glavna
    if threading.current_thread() is not threading.main_thread():
        return None
    if _glavna is None:
        with _zaklep:
            try:
                _glavna = Povezava(za_nasa_okna=True)
            except OSError:
                _glavna = False   # type: ignore[assignment]
    return _glavna or None


# --------------------------------------------------------------------------- okna GTK4
def xid(okno) -> int:
    """XID vrhnjega okna GTK4 (0, ce ni realizirano ali ni X11)."""
    try:
        povrsina = okno.get_surface()
        if povrsina is None:
            return 0
        import gi
        gi.require_version("GdkX11", "4.0")
        from gi.repository import GdkX11
        return int(povrsina.get_xid()) if isinstance(povrsina, GdkX11.X11Surface) else 0
    except Exception:  # noqa: BLE001 - Wayland ali GTK3
        return 0


def povrsina_x11(okno):
    """GdkX11.X11Surface okna ali None."""
    try:
        import gi
        gi.require_version("GdkX11", "4.0")
        from gi.repository import GdkX11
        p = okno.get_surface()
        return p if isinstance(p, GdkX11.X11Surface) else None
    except Exception:  # noqa: BLE001
        return None


def ob_realizaciji(okno, delo: Callable[[int], None]) -> None:
    """delo(xid) takoj, ce je okno ze realizirano, sicer ob realizaciji (pred prikazom - upravitelj oken lastnosti
    vrste in razreda prebere ob preslikavi)."""
    x = xid(okno)
    if x:
        delo(x)
        return
    okno.connect("realize", lambda o: (lambda x2: x2 and delo(x2))(xid(o)))


def ob_prikazu(okno, delo: Callable[[int], None]) -> None:
    """delo(xid) ob vsakem prikazu okna (GTK ob preslikavi na novo zapise _NET_WM_STATE, zato stanja po njej)."""
    def preslikano(o):
        x = xid(o)
        if x:
            delo(x)
    okno.connect("map", preslikano)
    if okno.get_mapped():
        preslikano(okno)


VRSTE = {"DESKTOP", "DOCK", "DIALOG", "NORMAL", "UTILITY", "SPLASH"}


def nastavi_vrsto(okno, vrsta: str) -> bool:
    """_NET_WM_WINDOW_TYPE (GTK3 set_type_hint): DESKTOP, DOCK, DIALOG ... Klicati pred prvim prikazom."""
    if vrsta not in VRSTE:
        return False
    p = povezava()
    if p is None:
        return False

    def delo(x: int) -> None:
        p.nastavi_stevila(x, "_NET_WM_WINDOW_TYPE", _XA_ATOM, [p.atom("_NET_WM_WINDOW_TYPE_" + vrsta)])
        p.poslji()
    ob_realizaciji(okno, delo)
    return True


def nastavi_razred(okno, ime: str, razred: str) -> bool:
    """WM_CLASS (GTK3 set_wmclass): po njem pult zdruzi okna v skupino. Pred prvim prikazom."""
    p = povezava()
    if p is None:
        return False

    def delo(x: int) -> None:
        p.nastavi_razred(x, ime, razred)
        p.poslji()
    ob_realizaciji(okno, delo)
    return True


def nastavi_preskoci(okno, opravilna: bool = True, preklopnik: bool = True) -> bool:
    """GTK3 set_skip_taskbar_hint / set_skip_pager_hint: GdkX11 jih ima in jih zapise ob prikazu."""
    def delo(_x: int) -> None:
        p = povrsina_x11(okno)
        if p is not None:
            p.set_skip_taskbar_hint(bool(opravilna))
            p.set_skip_pager_hint(bool(preklopnik))
    ob_realizaciji(okno, delo)
    return True


STANJA = {"ABOVE", "BELOW", "STICKY", "SKIP_TASKBAR", "SKIP_PAGER"}


def nastavi_stanje(okno, *stanja: str, vklop: bool = True) -> bool:
    """_NET_WM_STATE prek sporocila upravitelju oken (GTK3 set_keep_below/above, stick), ob vsakem prikazu okna."""
    stanja = tuple(s for s in stanja if s in STANJA)
    p = povezava()
    if p is None or not stanja:
        return False

    def delo(x: int) -> None:
        for i in range(0, len(stanja), 2):
            par = stanja[i:i + 2]
            p.sporocilo(x, "_NET_WM_STATE", 1 if vklop else 0, p.atom("_NET_WM_STATE_" + par[0]),
                        p.atom("_NET_WM_STATE_" + par[1]) if len(par) > 1 else 0, 1)
        if "STICKY" in stanja and vklop:
            p.sporocilo(x, "_NET_WM_DESKTOP", 0xFFFFFFFF, 1)
        p.poslji()
    ob_prikazu(okno, delo)
    return True


def premakni(okno, x: int, y: int) -> bool:
    """GTK3 move(): polozaj okna na zaslonu (po prikazu; pred njim ga upravitelj oken postavi sam). x, y sta v
    logicnih tockah GDK (kot geometrija Gdk.Monitor); X jih hoce v pikah, zato ju pomnozimo z merilom (HiDPI)."""
    p = povezava()
    if p is None:
        return False
    try:
        merilo = max(1, int(okno.get_scale_factor()))
    except Exception:  # noqa: BLE001
        merilo = 1
    x, y = int(x) * merilo, int(y) * merilo
    stevec = getattr(okno, "_safeer_premik", None)
    okno._safeer_premik = (int(x), int(y))
    if stevec is None:
        def delo(xid_: int) -> None:
            mesto = getattr(okno, "_safeer_premik", None)
            if mesto is not None:
                p.L.XMoveWindow(p.dpy, xid_, mesto[0], mesto[1])
                p.poslji()
        ob_prikazu(okno, delo)
    elif okno.get_mapped():
        x_ = xid(okno)
        if x_:
            p.L.XMoveWindow(p.dpy, x_, int(x), int(y))
            p.poslji()
    return True


def rezerviraj(okno, levo: int = 0, desno: int = 0, vrh: int = 0, dno: int = 0,
               dno_od: int = 0, dno_do: int = 0) -> bool:
    """_NET_WM_STRUT in _NET_WM_STRUT_PARTIAL (rezerviran rob zaslona za vrstico); v X pikah."""
    p = povezava()
    x = xid(okno)
    if p is None or not x:
        return False
    p.nastavi_stevila(x, "_NET_WM_STRUT_PARTIAL", _XA_CARDINAL,
                      [levo, desno, vrh, dno, 0, 0, 0, 0, 0, 0, dno_od, dno_do])
    p.nastavi_stevila(x, "_NET_WM_STRUT", _XA_CARDINAL, [levo, desno, vrh, dno])
    p.poslji()
    return True


def visina_korena() -> int:
    p = povezava()
    return p.velikost_korena()[1] if p is not None else 0
