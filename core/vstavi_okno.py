"""Vstavljanje okna drugega programa v gradnik Safeer (X11 XReparentWindow) - ena izvedba za Safeer DRM (okno Chromiuma
v zavihku Spleta) in Sporocila (Viber, Signal Desktop ... kot kanal; lastnik, 15. 10. 2026).

Samo Xlib prek ctypes (libX11, ki je na vsakem namizju X11) - brez dodatnih paketov. GTK4 nima X okna na gradnik: tuje
okno postane otrok X okna vrhnjega okna na mestu in v velikosti gradnika (Mesto), ki mu sledi ob vsaki spremembi.

Brez X11 (Wayland) okna ni mogoce vstaviti: X11() sprozi OSError in klicatelj okno pusti samostojno (nikoli lazna
vgradnja). Ob koncu se vstavljeno okno vrne na namizje (vrni_na_namizje), program se ne ubije.
"""
from __future__ import annotations

import ctypes
from typing import Callable, List, Optional, Tuple

# X11 konstante (X.h)
_ENTER_MASK, _LEAVE_MASK, _STRUCTURE_MASK, _PROPERTY_MASK = 1 << 4, 1 << 5, 1 << 17, 1 << 22
ENTER_NOTIFY, LEAVE_NOTIFY, DESTROY_NOTIFY, UNMAP_NOTIFY, PROPERTY_NOTIFY = 7, 8, 17, 18, 28
_REVERT_TO_PARENT = 2
#: Button1Mask .. Button5Mask (X.h)
_GUMBI_MASKA = 0x1F00
_ANY_PROPERTY_TYPE = 0


IS_UNMAPPED = 0
_CONFIGURE_NOTIFY = 22


class _XClassHint(ctypes.Structure):
    # c_void_p (ne c_char_p): kazalca mora sprostiti Xlib (XFree); c_char_p bi vrnil kopijo in XFree bi padel.
    _fields_ = [("res_name", ctypes.c_void_p), ("res_class", ctypes.c_void_p)]


class _XWindowAttributes(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int), ("width", ctypes.c_int), ("height", ctypes.c_int),
                ("border_width", ctypes.c_int), ("depth", ctypes.c_int), ("visual", ctypes.c_void_p),
                ("root", ctypes.c_ulong), ("class_", ctypes.c_int), ("bit_gravity", ctypes.c_int),
                ("win_gravity", ctypes.c_int), ("backing_store", ctypes.c_int), ("backing_planes", ctypes.c_ulong),
                ("backing_pixel", ctypes.c_ulong), ("save_under", ctypes.c_int), ("colormap", ctypes.c_ulong),
                ("map_installed", ctypes.c_int), ("map_state", ctypes.c_int), ("all_event_masks", ctypes.c_long),
                ("your_event_mask", ctypes.c_long), ("do_not_propagate_mask", ctypes.c_long),
                ("override_redirect", ctypes.c_int), ("screen", ctypes.c_void_p)]


class _XConfigureEvent(ctypes.Structure):
    """XConfigureEvent, dopolnjen na velikost XEvent (24 long) za XSendEvent."""
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p), ("event", ctypes.c_ulong), ("window", ctypes.c_ulong),
                ("x", ctypes.c_int), ("y", ctypes.c_int), ("width", ctypes.c_int), ("height", ctypes.c_int),
                ("border_width", ctypes.c_int), ("above", ctypes.c_ulong), ("override_redirect", ctypes.c_int),
                ("_dopolnilo", ctypes.c_long * 12)]


class X11:
    """Najmanj Xlib za vstavitev tujega okna in branje njegovih lastnosti (razred, naslov, PID)."""

    def __init__(self, zaslon: Optional[bytes] = None) -> None:
        self.lib = ctypes.cdll.LoadLibrary("libX11.so.6")
        L = self.lib
        L.XOpenDisplay.restype = ctypes.c_void_p
        L.XOpenDisplay.argtypes = [ctypes.c_char_p]
        dpy, win, ul, i, ui = ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int, ctypes.c_uint
        for ime, args, vrne in (
                ("XReparentWindow", [dpy, win, win, i, i], i),
                ("XMapWindow", [dpy, win], i), ("XUnmapWindow", [dpy, win], i),
                ("XMoveResizeWindow", [dpy, win, i, i, ui, ui], i),
                ("XFlush", [dpy], i), ("XSync", [dpy, i], i), ("XCloseDisplay", [dpy], i),
                ("XDefaultRootWindow", [dpy], win), ("XInternAtom", [dpy, ctypes.c_char_p, i], ul),
                ("XGetWindowProperty", [dpy, win, ul, ctypes.c_long, ctypes.c_long, i, ul,
                                        ctypes.POINTER(ul), ctypes.POINTER(i), ctypes.POINTER(ctypes.c_ulong),
                                        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p)], i),
                ("XFree", [ctypes.c_void_p], i),
                ("XGetClassHint", [dpy, win, ctypes.POINTER(_XClassHint)], i),
                ("XSetInputFocus", [dpy, win, i, ul], i),
                ("XSelectInput", [dpy, win, ctypes.c_long], i),
                ("XPending", [dpy], i), ("XNextEvent", [dpy, ctypes.c_void_p], i),
                ("XConnectionNumber", [dpy], i),
                ("XDefaultScreen", [dpy], i), ("XWithdrawWindow", [dpy, win, i], i),
                ("XRaiseWindow", [dpy, win], i),
                ("XGetWindowAttributes", [dpy, win, ctypes.POINTER(_XWindowAttributes)], i),
                ("XTranslateCoordinates", [dpy, win, win, i, i, ctypes.POINTER(i), ctypes.POINTER(i),
                                           ctypes.POINTER(ul)], i),
                ("XSendEvent", [dpy, win, i, ctypes.c_long, ctypes.c_void_p], i),
                ("XQueryTree", [dpy, win, ctypes.POINTER(ul), ctypes.POINTER(ul), ctypes.POINTER(ctypes.c_void_p),
                                ctypes.POINTER(ctypes.c_uint)], i),
                ("XChangeSaveSet", [dpy, win, i], i),
                ("XQueryPointer", [dpy, win, ctypes.POINTER(ul), ctypes.POINTER(ul), ctypes.POINTER(i),
                                   ctypes.POINTER(i), ctypes.POINTER(i), ctypes.POINTER(i), ctypes.POINTER(ctypes.c_uint)], i),
                ("XGetInputFocus", [dpy, ctypes.POINTER(ul), ctypes.POINTER(i)], i)):
            f = getattr(L, ime)
            f.argtypes = args
            f.restype = vrne
        # Rokovalnika napak Xlib ne menjamo: velja za ves proces in ga uporablja GDK (pasti napak GTK).
        self.dpy = L.XOpenDisplay(zaslon)
        if not self.dpy:
            raise OSError("X11 ni na voljo")
        self._atomi: dict = {}

    # ------------------------------------------------------------------ vstavljanje (kot Safeer DRM)
    def vstavi(self, otrok: int, stars: int, x: int, y: int, sirina: int, visina: int) -> None:
        self.lib.XReparentWindow(self.dpy, otrok, stars, x, y)
        self.lib.XMoveResizeWindow(self.dpy, otrok, x, y, max(1, sirina), max(1, visina))
        self.lib.XMapWindow(self.dpy, otrok)
        self.lib.XRaiseWindow(self.dpy, otrok)
        self.lib.XFlush(self.dpy)
        self.sporoci_polozaj(otrok)

    def velikost(self, okno: int, x: int, y: int, sirina: int, visina: int) -> None:
        self.lib.XMoveResizeWindow(self.dpy, okno, x, y, max(1, sirina), max(1, visina))
        self.lib.XFlush(self.dpy)
        self.sporoci_polozaj(okno)

    def v_shrambo(self, dpy_starsa: int, okno: int, dodaj: bool = True) -> bool:
        """Okno v »save-set« povezave, ki je ustvarila starsa (GDK): ce Safeer OS pade ali se konca brez vrni(), X
        streznik tuje okno vrne korenskemu oknu in ga prikaze, namesto da ga unici skupaj z nasim oknom (izmerjeno
        15. 10. 2026 v Xvfb: brez tega je okno izginilo in lazni program GTK4 je padel). Save-set velja samo za okna
        povezave, ki je ustvarila starsa, zato ga nastavimo na povezavi GDK (dpy_starsa), ne na nasi."""
        if not dpy_starsa:
            return False
        self.lib.XChangeSaveSet(ctypes.c_void_p(dpy_starsa), okno, 0 if dodaj else 1)   # SetModeInsert / Delete
        self.lib.XFlush(ctypes.c_void_p(dpy_starsa))
        return True

    def umakni(self, okno: int) -> None:
        """Okno odvzame upravljalniku oken (XWithdrawWindow). Na testnem PC (Muffin, 15. 10. 2026) je samo
        XReparentWindow upravljanega okna Muffin takoj vrnil v svoj okvir; po umiku in IsUnmapped vstavitev obvelja."""
        self.lib.XWithdrawWindow(self.dpy, okno, self.lib.XDefaultScreen(self.dpy))
        self.lib.XSync(self.dpy, 0)

    def stanje_prikaza(self, okno: int) -> int:
        """map_state okna (0 IsUnmapped, 1 IsUnviewable, 2 IsViewable); -1, ce okna ni."""
        a = _XWindowAttributes()
        if not self.lib.XGetWindowAttributes(self.dpy, okno, ctypes.byref(a)):
            return -1
        return int(a.map_state)

    def sporoci_polozaj(self, okno: int) -> None:
        """Sinteticni ConfigureNotify s polozajem na zaslonu (ICCCM 4.1.5, kot ga poslje upravljalnik oken): program
        brez tega ne ve, kje je njegovo okno na zaslonu, in odpre spustne menije (pojavna okna override-redirect) na
        napacnem mestu."""
        a = _XWindowAttributes()
        if not self.lib.XGetWindowAttributes(self.dpy, okno, ctypes.byref(a)):
            return
        rx, ry, otrok = ctypes.c_int(), ctypes.c_int(), ctypes.c_ulong()
        self.lib.XTranslateCoordinates(self.dpy, okno, self.koren(), 0, 0, ctypes.byref(rx), ctypes.byref(ry),
                                       ctypes.byref(otrok))
        d = _XConfigureEvent(type=_CONFIGURE_NOTIFY, send_event=1, display=self.dpy, event=okno, window=okno,
                             x=rx.value, y=ry.value, width=a.width, height=a.height, border_width=0, above=0,
                             override_redirect=0)
        self.lib.XSendEvent(self.dpy, okno, 0, _STRUCTURE_MASK, ctypes.byref(d))
        self.lib.XFlush(self.dpy)

    def pokazi(self, okno: int, vidno: bool) -> None:
        (self.lib.XMapWindow if vidno else self.lib.XUnmapWindow)(self.dpy, okno)
        self.lib.XFlush(self.dpy)

    def vrni_na_namizje(self, okno: int, x: int = 40, y: int = 40) -> None:
        """Okno spet postane samostojno (otrok korenskega okna): upravljalnik oken mu doda okvir, program tece naprej
        (XUnmapWindow + XReparentWindow na koren + XMapWindow, preverjeno na testnem PC 15. 10. 2026)."""
        self.lib.XUnmapWindow(self.dpy, okno)
        self.lib.XReparentWindow(self.dpy, okno, self.koren(), x, y)
        self.lib.XMapWindow(self.dpy, okno)
        self.lib.XSync(self.dpy, 0)

    def fokus(self, okno: int) -> None:
        self.lib.XSetInputFocus(self.dpy, okno, _REVERT_TO_PARENT, 0)
        self.lib.XFlush(self.dpy)

    def gumbi_miske(self) -> int:
        """Pritisnjeni gumbi miske (maska Button1..5 iz XQueryPointer); 0, ce nobeden."""
        koren, otrok = ctypes.c_ulong(), ctypes.c_ulong()
        rx, ry, x, y, maska = ctypes.c_int(), ctypes.c_int(), ctypes.c_int(), ctypes.c_int(), ctypes.c_uint()
        if not self.lib.XQueryPointer(self.dpy, self.koren(), ctypes.byref(koren), ctypes.byref(otrok), ctypes.byref(rx),
                                      ctypes.byref(ry), ctypes.byref(x), ctypes.byref(y), ctypes.byref(maska)):
            return 0
        return int(maska.value) & _GUMBI_MASKA

    def fokus_v(self, okno: int) -> bool:
        """Ali je fokus tipkovnice v oknu `okno` ali v katerem od njegovih podoken."""
        f, nazaj = ctypes.c_ulong(), ctypes.c_int()
        self.lib.XGetInputFocus(self.dpy, ctypes.byref(f), ctypes.byref(nazaj))
        w, koren, korak = int(f.value), self.koren(), 0
        while w and w != koren and korak < 32:
            if w == okno:
                return True
            w, korak = self.stars(w), korak + 1
        return False

    def zapri(self) -> None:
        if self.dpy:
            self.lib.XCloseDisplay(self.dpy)
            self.dpy = None

    # ------------------------------------------------------------------ lastnosti oken
    def koren(self) -> int:
        return int(self.lib.XDefaultRootWindow(self.dpy))

    def atom(self, ime: str) -> int:
        if ime not in self._atomi:
            self._atomi[ime] = int(self.lib.XInternAtom(self.dpy, ime.encode(), 0))
        return self._atomi[ime]

    def _lastnost(self, okno: int, ime: str, dolzina: int = 65536) -> Tuple[int, int, bytes]:
        """(oblika, stevilo elementov, surovi bajti) lastnosti; (0, 0, b'') ce je ni."""
        tip, oblika = ctypes.c_ulong(), ctypes.c_int()
        n, ostane, podatki = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
        r = self.lib.XGetWindowProperty(self.dpy, okno, self.atom(ime), 0, dolzina, 0, _ANY_PROPERTY_TYPE,
                                        ctypes.byref(tip), ctypes.byref(oblika), ctypes.byref(n),
                                        ctypes.byref(ostane), ctypes.byref(podatki))
        if r != 0 or not podatki.value:
            return 0, 0, b""
        try:
            velikost = {8: 1, 16: ctypes.sizeof(ctypes.c_short), 32: ctypes.sizeof(ctypes.c_long)}.get(oblika.value, 1)
            return oblika.value, n.value, ctypes.string_at(podatki.value, n.value * velikost)
        finally:
            self.lib.XFree(podatki)

    def _cela_stevila(self, okno: int, ime: str) -> List[int]:
        oblika, n, b = self._lastnost(okno, ime)
        if oblika != 32 or not n:
            return []
        return list((ctypes.c_ulong * n).from_buffer_copy(b))

    def okna_odjemalcev(self) -> List[int]:
        """Okna, ki jih vodi upravljalnik oken (_NET_CLIENT_LIST korenskega okna); brez upravljalnika oken (seja brez
        namizja, preizkusi v Xvfb) otroci korenskega okna."""
        return self._cela_stevila(self.koren(), "_NET_CLIENT_LIST") or self.otroci(self.koren())

    def otroci(self, okno: int) -> List[int]:
        koren, stars = ctypes.c_ulong(), ctypes.c_ulong()
        otroci, n = ctypes.c_void_p(), ctypes.c_uint()
        if not self.lib.XQueryTree(self.dpy, okno, ctypes.byref(koren), ctypes.byref(stars), ctypes.byref(otroci),
                                   ctypes.byref(n)):
            return []
        try:
            return list((ctypes.c_ulong * n.value).from_address(otroci.value)) if otroci.value and n.value else []
        finally:
            if otroci.value:
                self.lib.XFree(otroci)

    def stars(self, okno: int) -> int:
        koren, stars = ctypes.c_ulong(), ctypes.c_ulong()
        otroci, n = ctypes.c_void_p(), ctypes.c_uint()
        if not self.lib.XQueryTree(self.dpy, okno, ctypes.byref(koren), ctypes.byref(stars), ctypes.byref(otroci),
                                   ctypes.byref(n)):
            return 0
        if otroci.value:
            self.lib.XFree(otroci)
        return int(stars.value)

    def razred(self, okno: int) -> Tuple[str, str]:
        """WM_CLASS (ime, razred) - npr. ("signal", "Signal")."""
        h = _XClassHint()
        if not self.lib.XGetClassHint(self.dpy, okno, ctypes.byref(h)):
            return "", ""
        try:
            return tuple((ctypes.string_at(k) if k else b"").decode("utf-8", "replace") for k in (h.res_name, h.res_class))
        finally:
            for kazalec in (h.res_name, h.res_class):
                if kazalec:
                    self.lib.XFree(kazalec)

    def naslov(self, okno: int) -> str:
        _o, _n, b = self._lastnost(okno, "_NET_WM_NAME")
        if not b:
            _o, _n, b = self._lastnost(okno, "WM_NAME")
        return b.decode("utf-8", "replace")

    def pid(self, okno: int) -> int:
        v = self._cela_stevila(okno, "_NET_WM_PID")
        return int(v[0]) if v else 0

    def najdi(self, razredi, okna: Optional[List[int]] = None,
              sprejmi: Optional[Callable[[int], bool]] = None) -> int:
        """Prvo glavno okno odjemalca, katerega WM_CLASS (ime ali razred, brez velikosti crk) je med `razredi`; 0, ce
        ga ni. Pogovorna okna (WM_TRANSIENT_FOR) niso glavno okno. sprejmi(pid): ali okno s tem _NET_WM_PID res pripada
        programu (core/namizni_programi.pripada_programu) - WM_CLASS si lahko nastavi vsak program."""
        iskani = {str(r).casefold() for r in razredi if r}
        for okno in (okna if okna is not None else self.okna_odjemalcev()):
            ime, razred = self.razred(okno)
            if ime.casefold() not in iskani and razred.casefold() not in iskani:
                continue
            if self._lastnost(okno, "WM_TRANSIENT_FOR")[1]:
                continue
            if sprejmi is not None and not sprejmi(self.pid(okno)):
                continue
            return okno
        return 0

    # ------------------------------------------------------------------ dogodki (vstop miske, zaprtje okna)
    def spremljaj(self, okno: int) -> None:
        """Vstop in izstop miske, unicenje okna in sprememba lastnosti (naslov) - za fokus in stevilo neprebranih."""
        self.lib.XSelectInput(self.dpy, okno, _ENTER_MASK | _LEAVE_MASK | _STRUCTURE_MASK | _PROPERTY_MASK)
        self.lib.XFlush(self.dpy)

    def dogodki(self) -> List[Tuple[int, int]]:
        """Prebrani dogodki [(vrsta, okno)] (XAnyEvent: type na zacetku, window na 4. besedi)."""
        izid = []
        dogodek = (ctypes.c_long * 24)()
        while self.dpy and self.lib.XPending(self.dpy) > 0:
            self.lib.XNextEvent(self.dpy, ctypes.byref(dogodek))
            vrsta = int(ctypes.c_int.from_buffer(dogodek).value)
            izid.append((vrsta, int(ctypes.c_ulong(dogodek[4]).value)))
        return izid

    def vticnica(self) -> int:
        return int(self.lib.XConnectionNumber(self.dpy))


class Mesto:
    """Kje je gradnik GTK4 v X oknu svojega vrhnjega okna."""

    def __init__(self, Gtk, gradnik) -> None:
        self.Gtk, self.gradnik = Gtk, gradnik

    def dpy_gdk(self) -> int:
        """Kazalec Display* povezave GDK (ta je ustvarila X okno starsa); 0 brez X11."""
        try:
            prikaz = self.gradnik.get_display()
            import gi
            gi.require_version("GdkX11", "4.0")
            from gi.repository import GdkX11
            if not isinstance(prikaz, GdkX11.X11Display):
                return 0
            api = ctypes.pythonapi
            api.PyCapsule_GetPointer.restype = ctypes.c_void_p
            api.PyCapsule_GetPointer.argtypes = [ctypes.py_object, ctypes.c_char_p]
            gdk = ctypes.CDLL("libgtk-4.so.1")
            gdk.gdk_x11_display_get_xdisplay.restype = ctypes.c_void_p
            gdk.gdk_x11_display_get_xdisplay.argtypes = [ctypes.c_void_p]
            return int(gdk.gdk_x11_display_get_xdisplay(api.PyCapsule_GetPointer(prikaz.__gpointer__, None)) or 0)
        except Exception:  # noqa: BLE001 - Wayland ali GDK brez X11
            return 0

    def xid_starsa(self) -> int:
        try:
            koren = self.gradnik.get_native()
            povrsina = koren.get_surface() if koren is not None else None
            if povrsina is None:
                return 0
            import gi
            gi.require_version("GdkX11", "4.0")
            from gi.repository import GdkX11
            if not isinstance(povrsina, GdkX11.X11Surface):
                return 0
            return int(povrsina.get_xid())
        except Exception:  # noqa: BLE001 - Wayland: ni X11 okna
            return 0

    def pravokotnik(self):
        """(x, y, sirina, visina) gradnika v X pikah povrsine vrhnjega okna; None, ce ni prikazan."""
        koren = self.gradnik.get_native()
        if koren is None:
            return None
        from gi.repository import Graphene
        ok, tocka = self.gradnik.compute_point(koren, Graphene.Point().init(0, 0))
        if not ok:
            return None
        try:
            dx, dy = koren.get_surface_transform()   # senca/okvir odjemalca (CSD)
        except Exception:  # noqa: BLE001
            dx = dy = 0.0
        m = self.gradnik.get_scale_factor() or 1
        return (int(round((tocka.x + dx) * m)), int(round((tocka.y + dy) * m)),
                self.gradnik.get_width() * m, self.gradnik.get_height() * m)


class VstavljenoOkno:
    """Okno drugega programa nad gradnikom GTK4 (namestnik v Sporocilih). Sledi mestu in velikosti gradnika, se skrije,
    ko gradnik ni prikazan (drug kanal ali razdelek), in se ob koncu vrne na namizje.

    Fokus tipkovnice: vstavljeno okno ga od upravljalnika oken ne dobi (upravlja le vrhnja okna). Dobi ga ob KLIKU vanj,
    Safeer ga dobi nazaj ob kliku na svoj del okna ali ko se kanal skrije; sam premik miske fokusa ne premakne (prej je
    izhod miske programu vzel fokus sredi tipkanja; pregled 15. 10. 2026). Klika v tuje okno ne prestrezamo (brez
    zgrabitve gumba, ki bi ob zastoju Safeerja zamrznila misko na vsem namizju): dokler je miska v oknu, na 30 ms beremo
    stanje gumbov (XQueryPointer).

    Omejitev X11 (izmerjeno v Xvfb 15. 10. 2026): ko ima fokus Safeer (vrhnje okno, ki je STARS vstavljenega okna) in je
    miska nad vstavljenim oknom, X tipke dostavi oknu pod misko. To bi resilo le posredovanje tipk po XEmbed ali
    vstavljanje v loceno vrhnje okno - ni narejeno."""

    def __init__(self, Gtk, GLib, gradnik, x11: Optional[X11] = None,
                 ob_naslovu: Optional[Callable[[str], None]] = None, ob_koncu: Optional[Callable[[], None]] = None) -> None:
        self.Gtk, self.GLib, self.gradnik = Gtk, GLib, gradnik
        self.mesto = Mesto(Gtk, gradnik)
        self.x11 = x11
        self.okno = 0
        self._zadnje = None
        self._stars = 0
        self._vir = 0
        self.ob_naslovu, self.ob_koncu = ob_naslovu, ob_koncu
        self._miska = 0              # casovnik branja gumbov, dokler je miska v vstavljenem oknu
        self._pritisnjeno = False
        self._klik_vrha = None       # (vrhnje okno, kretnja) - klik na Safeer vrne fokus
        gradnik.connect("map", lambda *_: self.vidno(True))
        gradnik.connect("unmap", lambda *_: self.vidno(False))
        if Gtk.get_major_version() != 3:
            gradnik.connect("resize", lambda *_: self.prilagodi())

    BRANJE_MS = 150
    #: Branje gumbov miske, dokler je miska v vstavljenem oknu (klik je navadno 80-150 ms).
    KLIK_MS = 30
    #: Najdlje cakanje, da upravljalnik oken izpusti umaknjeno okno (izmerjeno na testnem PC: do ~2,5 s).
    UMIK_MS, UMIK_KORAK_MS = 3000, 50

    def vstavi(self, okno: int) -> bool:
        """Vstavi okno: najprej ga upravljalnik oken izpusti (umakni), nato postane otrok vrhnjega okna na mestu gradnika
        (ce je gradnik prikazan; sicer ob prikazu). False brez X11."""
        if self.x11 is None:
            try:
                self.x11 = X11()
            except OSError:
                return False
        self.okno = int(okno)
        self._stars = 0
        self.x11.umakni(self.okno)
        rok = [self.UMIK_MS // self.UMIK_KORAK_MS]

        def cakaj():
            if not self.okno:
                return False
            rok[0] -= 1
            if self.x11.stanje_prikaza(self.okno) not in (IS_UNMAPPED, -1) and rok[0] > 0:
                return True
            self._umaknjeno()
            return False
        if self.x11.stanje_prikaza(self.okno) in (IS_UNMAPPED, -1):
            self._umaknjeno()
        else:
            self.GLib.timeout_add(self.UMIK_KORAK_MS, cakaj)
        return True

    def _umaknjeno(self) -> None:
        if not self.okno:
            return
        self.x11.spremljaj(self.okno)
        if not self._vir:
            # Dogodke (vstop miske, naslov, zaprtje) beremo s casovnikom, ne z opazovanjem vticnice: Xlib jih pri nasih
            # klicih z odgovorom (XGetWindowAttributes ...) prebere v svojo vrsto in vticnica potem molci - v preizkusu
            # 15. 10. 2026 je zato fokus izostal. XPending je neblokirajoc; 150 ms je pod pragom zaznave.
            self._vir = self.GLib.timeout_add(self.BRANJE_MS, lambda: (self._beri(), True)[1])
        if self.gradnik.get_mapped():
            self._v_starsa()
        return True

    def _v_starsa(self) -> None:
        stars = self.mesto.xid_starsa()
        mesto = self.mesto.pravokotnik()
        if not stars or mesto is None or not self.okno:
            return
        if stars != self._stars:
            self.x11.v_shrambo(self.mesto.dpy_gdk(), self.okno)
            self.x11.vstavi(self.okno, stars, *mesto)
            self._stars = stars
            self._poslusaj_vrh()
        else:
            self.x11.velikost(self.okno, *mesto)
            self.x11.pokazi(self.okno, True)
        self._zadnje = mesto

    def prilagodi(self) -> None:
        if self.x11 is None or not self.okno or not self.gradnik.get_mapped():
            return
        mesto = self.mesto.pravokotnik()
        if mesto is None or mesto == self._zadnje:
            return
        if self._stars != self.mesto.xid_starsa():
            self._v_starsa()      # gradnik je v drugem vrhnjem oknu (Sporocila v drugem oknu)
            return
        self._zadnje = mesto
        self.x11.velikost(self.okno, *mesto)

    def vidno(self, vidno: bool) -> None:
        if self.x11 is None or not self.okno:
            return
        if vidno:
            self._zadnje = None
            self._v_starsa()
        else:
            self._fokus_nazaj()
            self._miska_ven()
            self.x11.pokazi(self.okno, False)

    # ------------------------------------------------------------------ fokus tipkovnice (klik)
    def _poslusaj_vrh(self) -> None:
        """Klik kamorkoli v Safeer (vrhnje okno gradnika) vrne fokus Safeerju, ce ga ima vstavljeni program."""
        vrh = self.gradnik.get_root() if hasattr(self.gradnik, "get_root") else self.gradnik.get_toplevel()
        if vrh is None or (self._klik_vrha is not None and self._klik_vrha[0] is vrh):
            return
        self._odklopi_vrh()
        try:
            kretnja = self.Gtk.GestureClick()
            kretnja.set_button(0)
            kretnja.set_propagation_phase(self.Gtk.PropagationPhase.CAPTURE)
            kretnja.connect("pressed", lambda *_: self._fokus_nazaj())
            vrh.add_controller(kretnja)
            self._klik_vrha = (vrh, kretnja)
        except Exception:  # noqa: BLE001 - GTK3 (brez kontrolerjev na oknu): fokus vrne skrivanje kanala
            self._klik_vrha = None

    def _odklopi_vrh(self) -> None:
        if self._klik_vrha is not None:
            try:
                self._klik_vrha[0].remove_controller(self._klik_vrha[1])
            except Exception:  # noqa: BLE001
                pass
            self._klik_vrha = None

    def _fokus_nazaj(self) -> None:
        if self.x11 is not None and self.okno and self._stars and self.x11.fokus_v(self.okno):
            self.x11.fokus(self._stars)

    def _miska_noter(self) -> None:
        if not self._miska:
            self._pritisnjeno = bool(self.x11.gumbi_miske())
            self._miska = self.GLib.timeout_add(self.KLIK_MS, self._preveri_klik)

    def _miska_ven(self) -> None:
        if self._miska:
            self.GLib.source_remove(self._miska)
            self._miska = 0

    def _preveri_klik(self) -> bool:
        if self.x11 is None or not self.okno:
            self._miska = 0
            return False
        dol = bool(self.x11.gumbi_miske())
        if dol and not self._pritisnjeno and not self.x11.fokus_v(self.okno):
            self.x11.fokus(self.okno)
        self._pritisnjeno = dol
        return True

    def _beri(self) -> None:
        if self.x11 is None:
            return
        for vrsta, okno in self.x11.dogodki():
            if okno != self.okno:
                continue
            if vrsta == ENTER_NOTIFY:
                self._miska_noter()
            elif vrsta == LEAVE_NOTIFY:
                self._miska_ven()
            elif vrsta == PROPERTY_NOTIFY and self.ob_naslovu is not None:
                self.ob_naslovu(self.x11.naslov(self.okno))
            elif vrsta == DESTROY_NOTIFY:
                self._miska_ven()
                self.okno, self._stars = 0, 0
                if self.ob_koncu is not None:
                    self.ob_koncu()

    def naslov(self) -> str:
        return self.x11.naslov(self.okno) if self.x11 is not None and self.okno else ""

    def vrni(self) -> None:
        """Okno nazaj na namizje (konec Safeer OS, izklop kanala): program tece naprej v svojem oknu."""
        self._miska_ven()
        self._odklopi_vrh()
        if self.x11 is not None and self.okno:
            try:
                self.x11.vrni_na_namizje(self.okno)
            except Exception as e:  # noqa: BLE001
                print("[Safeer] vrnitev okna:", e, flush=True)
        self.okno, self._stars = 0, 0

    def unici(self) -> None:
        self.vrni()
        if self._vir:
            self.GLib.source_remove(self._vir)
            self._vir = 0
        if self.x11 is not None:
            self.x11.zapri()
            self.x11 = None
