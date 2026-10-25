"""Locen zaslon za televizor: programi, zagnani s televizorja, tecejo na drugem, nevidnem zaslonu.

Racunalnik ima svoj zaslon (X11, Cinnamon) in ta ostane nedotaknjen: kar televizor zazene, se odpre
v brezglavem (headless) sestavljalniku sway, ki riše z grafično kartico, a ne na noben monitor.
Televizor dobi sliko samo tega drugega zaslona, njegova miska in tipke gredo samo vanj, zvok gre na
lasten navidezni izhod. Uporabnik za racunalnikom medtem dela naprej, kot da televizorja ni.

Deli:
  * `DrugiZaslon` - zazene in ustavi sway, zaganja programe vanj, pripravi ukaz za zajem slike
    (wf-recorder, strojno kodiranje VAAPI) in navidezni zvocni izhod `safeer_tv`.
  * `SwayVnos` - miska in tipkovnica samo za drugi zaslon. Govori protokol Wayland neposredno
    (navidezna miska wlr in navidezna tipkovnica), zato tipke lahko ostanejo pritisnjene (igre)
    in nic ne gre skozi X na glavni zaslon.

Nic ne tece, dokler televizor ne zazene programa; vse se ustavi z `ustavi()`.
"""

from __future__ import annotations

import array
import glob
import json
import os
import re
import secrets
import shutil
import signal
import socket
import struct
import subprocess
import threading
import time
from typing import Dict, List, Optional, Tuple

from core import otroci, root_ukaz, zasebni_webkit
from core.link_vnos import NAJVEC_BESEDILA, NAJVEC_DRZANJA_S, NAJVEC_PREMIK, TIPKE

#: Ime navideznega zvocnega izhoda, na katerega igrajo programi drugega zaslona.
ZVOCNI_IZHOD = "safeer_tv"


def nasi_zvocni_moduli(izpis: str) -> List[str]:
    """Stevilke nasih navideznih izhodov v izpisu `pactl list short modules`.

    Vrstica je `<st>\t<modul>\t<argumenti>`; nas je module-null-sink z sink_name=safeer_tv
    (PipeWire argumente lahko vrne v narekovajih)."""
    ids: List[str] = []
    for vrstica in izpis.splitlines():
        deli = vrstica.split("\t")
        if len(deli) < 3 or deli[1].strip() != "module-null-sink":
            continue
        if "sink_name=" + ZVOCNI_IZHOD in (t.replace('"', "").replace("'", "") for t in deli[2].split()):
            ids.append(deli[0].strip())
    return ids


def pocisti_zvok() -> int:
    """Odstrani VSE nase navidezne izhode, tudi tiste, ki jih je pustil prejsnji Control
    (ubit, sesut, ponovno zagnan ob posodobitvi). Sicer se v zvocnih napravah kopicijo
    izhodi Safeer-TV. Vrne, koliko jih je odstranil."""
    if not shutil.which("pactl"):
        return 0
    try:
        izpis = subprocess.run(["pactl", "list", "short", "modules"], capture_output=True, text=True,
                               timeout=5).stdout
    except Exception:
        return 0
    n = 0
    for modul in nasi_zvocni_moduli(izpis):
        try:
            if subprocess.run(["pactl", "unload-module", modul], capture_output=True, timeout=5).returncode == 0:
                n += 1
        except Exception:
            pass
    return n

#: Koliko casa po zagonu programa izhoda Safeer-TV ne pospravimo: okno se se odpira, program pa
#: ze isce izhod, na katerega naj igra.
ZVOK_PO_ZAGONU_S = 15.0
#: Ime izhoda v brezglavem swayu (prvi in edini).
IZHOD = "HEADLESS-1"


def _run_mapa() -> str:
    return os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()


def _konfiguracija(sirina: int, visina: int) -> str:
    # Brez robov in bliznjic: drugi zaslon ni namizje, je platno za programe s televizorja.
    # Zavihki: vec programov hkrati je kot zavihki v brskalniku, vsak cez cel zaslon.
    return "\n".join([
        "output %s resolution %dx%d@60Hz position 0 0" % (IZHOD, sirina, visina),
        "output %s bg #101418 solid_color" % IZHOD,
        "xwayland enable",
        "default_border none",
        "default_floating_border none",
        "focus_follows_mouse no",
        "workspace_layout tabbed",
        # Vrstica zavihkov je na televizorju samo motnja (programe menjas z Naslednji program):
        # najmanjsa pisava in barve ozadja - ostane le tanek temen rob.
        "titlebar_padding 1",
        "titlebar_border_thickness 0",
        "client.focused #101418 #101418 #101418 #101418 #101418",
        "client.focused_inactive #101418 #101418 #101418 #101418 #101418",
        "client.unfocused #101418 #101418 #101418 #101418 #101418",
        "seat seat0 xcursor_theme Adwaita 32",
        # Navidezna miska in tipkovnica morata ostati na sedezu tudi, ce sedez dobi se kak ukaz: sway naprave,
        # ki niso izrecno pripete, sicer odklopi (izmerjeno: po ukazu `seat seat0 ...` med tekom vnosa ni bilo vec).
        "seat seat0 fallback true",
        # Program si kazalca ne sme zakleniti. Igra cez cel zaslon s skritim kazalcem (SFML/SDL prek XWaylanda)
        # ga sicer ujame in sway po zaklepu absolutnega premika ne izvede vec: dotik na telefonu ali tablici
        # pride do igre kot relativni premik od zaklenjene lege in zgresi gumb. Relativni premiki (daljinec,
        # plosek) do programa pridejo tudi brez zaklepa.
        "seat seat0 pointer_constraint disable",
        "font pango:Sans 1",
        # Edina bliznjica: preklop med programi (daljinec: meni seje -> Naslednji program).
        # Celozaslonski program (igra) bi sicer zakril ostale, zato ga ob preklopu pomanjsamo v zavihek.
        "bindsym Mod1+Tab fullscreen disable, focus right",
        "",
    ])


# ---------------------------------------------------------------------------------- Wayland

def _niz(besedilo: str) -> bytes:
    b = besedilo.encode("utf-8") + b"\0"
    return struct.pack("=I", len(b)) + b + b"\0" * ((4 - len(b) % 4) % 4)


def _fiksno(v: float) -> int:
    return int(round(v * 256.0))


class _Wayland:
    """Najmanjsi odjemalec Wayland: zahteve pise sam, dogodke bere v ozadju in jih zavrze
    (razen napak in registra ob zacetku). Dovolj za navidezno misko in tipkovnico."""

    def __init__(self, pot: str) -> None:
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.settimeout(5)
        self.s.connect(pot)
        self._naslednji = 2          # 1 je wl_display
        self._pisalo = threading.Lock()
        self._ostanek = b""
        self.napaka = ""
        self.globali: Dict[str, Tuple[int, int]] = {}

    def nov(self) -> int:
        i = self._naslednji
        self._naslednji += 1
        return i

    def poslji(self, obj: int, op: int, argumenti: bytes = b"", fd: Optional[int] = None) -> None:
        sporocilo = struct.pack("=II", obj, ((8 + len(argumenti)) << 16) | op) + argumenti
        with self._pisalo:
            if fd is None:
                self.s.sendall(sporocilo)
            else:
                self.s.sendmsg([sporocilo], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [fd]))])

    def _dogodki(self, podatki: bytes):
        self._ostanek += podatki
        while len(self._ostanek) >= 8:
            obj, glava = struct.unpack("=II", self._ostanek[:8])
            velikost, op = glava >> 16, glava & 0xFFFF
            if velikost < 8 or len(self._ostanek) < velikost:
                break
            telo = self._ostanek[8:velikost]
            self._ostanek = self._ostanek[velikost:]
            yield obj, op, telo

    def _preberi(self) -> List[tuple]:
        podatki, _, _, _ = self.s.recvmsg(65536, socket.CMSG_SPACE(16 * 4))
        if not podatki:
            raise OSError("Wayland je zaprl povezavo")
        izid = []
        for obj, op, telo in self._dogodki(podatki):
            if obj == 1 and op == 0:          # wl_display.error
                _, koda = struct.unpack("=II", telo[:8])
                dolzina = struct.unpack("=I", telo[8:12])[0]
                self.napaka = "%d: %s" % (koda, telo[12:12 + dolzina - 1].decode("utf-8", "replace"))
            izid.append((obj, op, telo))
        return izid

    def pripravi(self) -> None:
        """Prebere register (kateri vmesniki obstajajo) in pocaka, da streznik odgovori."""
        register = self.nov()
        self.poslji(1, 1, struct.pack("=I", register))       # wl_display.get_registry
        klic = self.nov()
        self.poslji(1, 0, struct.pack("=I", klic))           # wl_display.sync
        self.register = register
        konec = time.monotonic() + 5
        while time.monotonic() < konec:
            for obj, op, telo in self._preberi():
                if obj == register and op == 0:              # wl_registry.global
                    ime = struct.unpack("=I", telo[:4])[0]
                    dolzina = struct.unpack("=I", telo[4:8])[0]
                    vmesnik = telo[8:8 + dolzina - 1].decode("utf-8", "replace")
                    zamik = 8 + ((dolzina + 3) // 4) * 4
                    razlicica = struct.unpack("=I", telo[zamik:zamik + 4])[0]
                    self.globali.setdefault(vmesnik, (ime, razlicica))
                elif obj == klic and op == 0:                # wl_callback.done
                    return
            if self.napaka:
                break
        raise OSError("Wayland se ni odzval: %s" % (self.napaka or "brez odgovora"))

    def pripni(self, vmesnik: str, najvec: int) -> int:
        ime, razlicica = self.globali[vmesnik]
        i = self.nov()
        self.poslji(self.register, 0, struct.pack("=I", ime) + _niz(vmesnik)
                    + struct.pack("=II", min(najvec, razlicica), i))
        return i

    def odtekaj(self) -> None:
        """V ozadju: sproti prebere dogodke, da se vticnica ne zamasi."""
        self.s.settimeout(None)
        try:
            while True:
                self._preberi()
        except OSError:
            pass

    def zapri(self) -> None:
        try:
            self.s.close()
        except OSError:
            pass


#: Tipke za Wayland (kode evdev iz linux/input-event-codes.h), po imenih, ki jih uporablja link_vnos.
KODE: Dict[str, int] = {
    "Up": 103, "Down": 108, "Left": 105, "Right": 106, "Return": 28, "Escape": 1, "super": 125,
    "Menu": 127, "space": 57, "BackSpace": 14, "Delete": 111, "Tab": 15, "Page_Up": 104,
    "Page_Down": 109, "Home": 102, "End": 107, "XF86AudioPlay": 164, "XF86AudioStop": 166,
    "XF86AudioNext": 163, "XF86AudioPrev": 165, "XF86AudioRaiseVolume": 115,
    "XF86AudioLowerVolume": 114, "XF86AudioMute": 113,
    "F1": 59, "F2": 60, "F3": 61, "F4": 62, "F5": 63, "F6": 64, "F7": 65, "F8": 66, "F9": 67,
    "F10": 68, "F11": 87, "F12": 88,
    "ctrl": 29, "shift": 42, "alt": 56,
    "Control_L": 29, "Shift_L": 42, "Alt_L": 56, "Super_L": 125,
    "a": 30, "b": 48, "c": 46, "f": 33, "i": 23, "p": 25, "s": 31, "t": 20, "u": 22, "v": 47, "w": 17,
    "x": 45, "y": 21, "z": 44,
    # Ostale crke in stevke (link_vnos.TIPKE): drug racunalnik poslje vsako tipko posebej (linux/input-event-codes.h).
    "d": 32, "e": 18, "g": 34, "h": 35, "j": 36, "k": 37, "l": 38, "m": 50, "n": 49, "o": 24, "q": 16, "r": 19,
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10, "0": 11,
}
#: Maske krmilk v razporedu (Shift, Control, Mod1 = Alt, Mod4 = Super).
MASKE = {29: 4, 42: 1, 56: 8, 125: 64}
GUMBI_EVDEV = {"levi": 0x110, "desni": 0x111, "srednji": 0x112}

#: Razpored tipkovnice: prevede ga sway sam (xkbcommon), mi ga samo opisemo.
RAZPORED = ('xkb_keymap {\n'
            ' xkb_keycodes { include "evdev+aliases(qwerty)" };\n'
            ' xkb_types { include "complete" };\n'
            ' xkb_compat { include "complete" };\n'
            ' xkb_symbols { include "pc+us+inet(evdev)" };\n'
            '};\n')


class SwayVnos:
    """Miska in tipkovnica samo za drugi zaslon. Enak vmesnik kot link_vnos.Vnos."""

    def __init__(self, drugi: "DrugiZaslon") -> None:
        self.drugi = drugi
        self.stevec = 0
        self._wl: Optional[_Wayland] = None
        self._miska = 0
        self._tipkovnica = 0
        self._krmilke = 0
        self._drzane: Dict[int, float] = {}
        self._kljuc = threading.Lock()
        self._straza: Optional[threading.Thread] = None
        self._konec = threading.Event()
        #: Levi gumb, drzan za vlecenje (meni seje na televizorju); ob koncu ga spustimo.
        self._gumb_drzan: Optional[int] = None
        #: Televizor ima vklopljeno povecavo in hoce vedeti, kje je kazalec.
        self.porocaj_kazalec = False

    @property
    def mozno(self) -> bool:
        return self.drugi.tece()

    # ----------------------------------------------------------------- povezava
    def _povezi(self) -> bool:
        if self._wl is not None:
            return True
        pot = self.drugi.wayland_pot()
        if not pot:
            return False
        try:
            wl = _Wayland(pot)
            wl.pripravi()
            sedez = wl.pripni("wl_seat", 1)
            upravitelj_m = wl.pripni("zwlr_virtual_pointer_manager_v1", 1)
            upravitelj_t = wl.pripni("zwp_virtual_keyboard_manager_v1", 1)
            miska, tipkovnica = wl.nov(), wl.nov()
            wl.poslji(upravitelj_m, 0, struct.pack("=II", sedez, miska))       # create_virtual_pointer
            wl.poslji(upravitelj_t, 0, struct.pack("=II", sedez, tipkovnica))  # create_virtual_keyboard
            razpored = RAZPORED.encode("utf-8") + b"\0"
            fd = os.memfd_create("safeer-razpored", 0)
            try:
                os.write(fd, razpored)
                wl.poslji(tipkovnica, 0, struct.pack("=II", 1, len(razpored)), fd=fd)  # keymap, XKB_V1
            finally:
                os.close(fd)
        except (OSError, KeyError) as e:
            print("[drugi zaslon] vnos ni mogoc: %s" % e, flush=True)
            return False
        threading.Thread(target=wl.odtekaj, name="safeer-sway-vnos", daemon=True).start()
        # Sway mora novo tipkovnico in njen razpored najprej sprejeti; tipka, poslana takoj,
        # se izgubi (izmerjeno: prvi Enter po zagonu ni prisel do programa).
        time.sleep(0.15)
        self._wl, self._miska, self._tipkovnica = wl, miska, tipkovnica
        return True

    def zapri(self) -> None:
        self.sprosti_vse()
        wl, self._wl = self._wl, None
        if wl is not None:
            wl.zapri()

    @staticmethod
    def _cas() -> int:
        return int(time.monotonic() * 1000) & 0xFFFFFFFF

    def _poslji(self, obj_fn, op: int, argumenti: bytes = b"") -> bool:
        with self._kljuc:
            if not self._povezi():
                return False
            obj = self._miska if obj_fn == "m" else self._tipkovnica
            try:
                self._wl.poslji(obj, op, argumenti)
            except OSError:
                self._wl = None
                return False
        return True

    # ----------------------------------------------------------------- tipke
    def _tipko(self, koda: int, dol: bool) -> bool:
        if not self._poslji("t", 1, struct.pack("=III", self._cas(), koda, 1 if dol else 0)):
            return False
        if koda in MASKE:
            self._krmilke = (self._krmilke | MASKE[koda]) if dol else (self._krmilke & ~MASKE[koda])
            self._poslji("t", 2, struct.pack("=IIII", self._krmilke, 0, 0, 0))
        return True

    @staticmethod
    def _kode(oznaka: str) -> Optional[List[int]]:
        ime = TIPKE.get(oznaka.strip().lower())
        if ime is None:
            return None
        kode = [KODE.get(d) for d in ime.split("+")]
        return None if any(k is None for k in kode) else kode

    def izvedi(self, dogodek: dict) -> bool:
        if not isinstance(dogodek, dict) or not self.drugi.tece():
            return False
        vrsta = str(dogodek.get("vrsta", "") or "")
        ok = False
        if vrsta == "tipka":
            oznaka = str(dogodek.get("tipka", "") or "")
            fokus = getattr(self.drugi, "fokus", None)
            if oznaka.strip().lower() == "nazaj" and fokus is not None and fokus.brskalnik_na_strani():
                # Nazaj na daljincu v brskalniku: prejsnja stran, kot v brskalniku na televizorju.
                oznaka = "brskalnik_nazaj"
            kode = self._kode(oznaka)
            if kode:
                for k in kode:
                    self._tipko(k, True)
                for k in reversed(kode):
                    ok = self._tipko(k, False)
        elif vrsta in ("tipka_dol", "tipka_gor"):
            kode = self._kode(str(dogodek.get("tipka", "") or ""))
            if kode and len(kode) == 1:
                ok = self._drzi(kode[0], vrsta == "tipka_dol")
        elif vrsta == "besedilo":
            ok = self._besedilo(str(dogodek.get("besedilo", "") or ""))
        elif vrsta == "premik":
            try:
                x = max(-NAJVEC_PREMIK, min(NAJVEC_PREMIK, int(dogodek.get("dx"))))
                y = max(-NAJVEC_PREMIK, min(NAJVEC_PREMIK, int(dogodek.get("dy"))))
            except (TypeError, ValueError):
                return False
            if x or y:
                ok = self._poslji("m", 0, struct.pack("=Iii", self._cas(), _fiksno(x), _fiksno(y))) \
                    and self._poslji("m", 4)
                t = self.drugi.fokus.tocka
                if t is not None:
                    self.drugi.fokus.tocka = (min(max(t[0] + x, 0), self.drugi.sirina - 1),
                                              min(max(t[1] + y, 0), self.drugi.visina - 1))
                self.drugi.fokus.izbira = None
        elif vrsta == "fokus":
            # Krizec: na naslednji gumb/polje v smeri. Kjer program o sebi nic ne pove (igra),
            # gre kot navadna smerna tipka.
            smer = str(dogodek.get("smer", "") or "").strip().lower()
            if smer in ("gor", "dol", "levo", "desno"):
                ok = self.drugi.fokus.premakni(smer)
                e = self.drugi.fokus.izbira
                if ok and self.drugi.fokus.na_robu and smer in ("gor", "dol") \
                        and not (e is not None and len(e) > 8 and e[8]):
                    # Spodaj (ali zgoraj) ni vec vidnega gumba: stran se premakne, kot na Androidu -
                    # sicer bi bila vsebina pod robom (dolga spletna stran) nedosegljiva.
                    self.izvedi({"vrsta": "kolesce", "smer": smer, "koliko": 3})
                    self.drugi.fokus.pozabi()
                    self.drugi.fokus.izbira = None
                    return True
                if not ok and str(dogodek.get("sicer", "") or "") == "kazalec":
                    # Daljinec: program o sebi nic ne pove, zato kratek pritisk kazalec le rahlo
                    # premakne - natancno, namesto da bi odletel mimo cilja.
                    k = KORAK_KAZALCA
                    dx, dy = {"levo": (-k, 0), "desno": (k, 0), "gor": (0, -k), "dol": (0, k)}[smer]
                    return self.izvedi({"vrsta": "premik", "dx": dx, "dy": dy})
                if not ok:
                    kode = self._kode(smer)
                    if kode:
                        self._tipko(kode[0], True)
                        ok = self._tipko(kode[0], False)
        elif vrsta == "gumb":
            # Vlecenje iz menija seje: levi gumb dol, premik, gumb gor.
            gumb = GUMBI_EVDEV.get(str(dogodek.get("gumb", "levi") or "levi").strip().lower())
            if gumb is not None:
                dol = bool(dogodek.get("dol"))
                ok = self._poslji("m", 2, struct.pack("=III", self._cas(), gumb, 1 if dol else 0)) \
                    and self._poslji("m", 4)
                self._gumb_drzan = gumb if dol else None
                self.drugi.fokus.pozabi()
        elif vrsta == "tocka":
            # Dotik na tablici: kazalec natanko tja, kamor je prst pokazal.
            try:
                x, y = int(dogodek.get("x")), int(dogodek.get("y"))
            except (TypeError, ValueError):
                return False
            ok = self.absolutno(x, y)
            self.drugi.fokus.tocka = (float(min(max(x, 0), self.drugi.sirina - 1)),
                                      float(min(max(y, 0), self.drugi.visina - 1)))
            self.drugi.fokus.izbira = None
        elif vrsta == "barva":
            # Barvne tipke daljinca: v brskalniku nazaj, naprej, osvezi, nov zavihek. Drugod nic -
            # tipka brez dogovorjenega pomena ne sme narediti nicesar nepricakovanega.
            barva = str(dogodek.get("barva", "") or "").strip().lower()
            oznaka = BARVE_BRSKALNIK.get(barva)
            if oznaka and self.drugi.fokus.profil() == "brskalnik":
                kode = self._kode(oznaka)
                if kode:
                    for k in kode:
                        self._tipko(k, True)
                    for k in reversed(kode):
                        ok = self._tipko(k, False)
                self.drugi.fokus.pozabi()
                self.drugi.fokus.izbira = None
        elif vrsta == "povecava":
            self.porocaj_kazalec = bool(dogodek.get("vkljuceno"))
            if self.porocaj_kazalec and self.drugi.fokus.tocka is None:
                # Povecava mora vedeti, kje je kazalec: postavimo ga na sredino.
                sredina = (self.drugi.sirina // 2, self.drugi.visina // 2)
                self.absolutno(*sredina)
                self.drugi.fokus.tocka = (float(sredina[0]), float(sredina[1]))
            ok = True
        elif vrsta == "klik":
            # Izbire tu ne pozabimo: link_zaslon po kliku preveri, ali je gumb se tam (okvir ostane).
            self.drugi.fokus.pozabi()
            gumb = GUMBI_EVDEV.get(str(dogodek.get("gumb", "levi") or "levi").strip().lower())
            if gumb is not None:
                for _ in range(2 if dogodek.get("dvojni") else 1):
                    for stanje in (1, 0):
                        ok = self._poslji("m", 2, struct.pack("=III", self._cas(), gumb, stanje)) \
                            and self._poslji("m", 4)
                        time.sleep(0.02)
        elif vrsta == "kolesce":
            smer = str(dogodek.get("smer", "") or "").strip().lower()
            if smer in ("gor", "dol"):
                try:
                    n = max(1, min(10, int(dogodek.get("koliko") or 1)))
                except (TypeError, ValueError):
                    n = 1
                n = -n if smer == "gor" else n
                ok = self._poslji("m", 5, struct.pack("=I", 0)) \
                    and self._poslji("m", 7, struct.pack("=IIii", self._cas(), 0, _fiksno(15 * n), n)) \
                    and self._poslji("m", 4)
        if ok:
            self.stevec += 1
        return ok

    def absolutno(self, x: int, y: int) -> bool:
        """Kazalec natanko na (x, y) drugega zaslona."""
        s, v = max(1, self.drugi.sirina), max(1, self.drugi.visina)
        x, y = min(max(0, x), s - 1), min(max(0, y), v - 1)
        return self._poslji("m", 1, struct.pack("=IIIII", self._cas(), x, y, s, v)) and self._poslji("m", 4)

    def _besedilo(self, besedilo: str) -> bool:
        # Poljubni znaki (č, š, ž ...) niso v nasem razporedu; wtype si razpored sestavi sam.
        besedilo = besedilo[:NAJVEC_BESEDILA]
        if not besedilo or any(ord(z) < 32 for z in besedilo) or not shutil.which("wtype"):
            return False
        try:
            subprocess.run(["wtype", "-s", "60", "-d", "12", "--", besedilo], env=self.drugi.okolje(),
                           timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            return False
        return True

    # ----------------------------------------------------------------- drzanje
    def _drzi(self, koda: int, dol: bool) -> bool:
        if dol:
            self.sprosti_pozabljene()
            if koda in self._drzane:
                self._drzane[koda] = time.monotonic()
                return True
            if not self._tipko(koda, True):
                return False
            self._drzane[koda] = time.monotonic()
            self._zbudi_strazo()
            return True
        self._drzane.pop(koda, None)
        return self._tipko(koda, False)

    def drzane(self) -> List[int]:
        return sorted(self._drzane)

    def sprosti_vse(self) -> None:
        if self._gumb_drzan is not None:
            gumb, self._gumb_drzan = self._gumb_drzan, None
            self._poslji("m", 2, struct.pack("=III", self._cas(), gumb, 0))
            self._poslji("m", 4)
        self.porocaj_kazalec = False
        for koda in list(self._drzane):
            self._drzane.pop(koda, None)
            self._tipko(koda, False)
        self._konec.set()

    def sprosti_pozabljene(self, zdaj: Optional[float] = None) -> None:
        sedaj = time.monotonic() if zdaj is None else zdaj
        for koda, ko in list(self._drzane.items()):
            if sedaj - ko > NAJVEC_DRZANJA_S:
                self._drzane.pop(koda, None)
                self._tipko(koda, False)

    def _zbudi_strazo(self) -> None:
        if self._straza is not None and self._straza.is_alive():
            return
        self._konec.clear()

        def tece() -> None:
            while self._drzane and not self._konec.wait(1.0):
                self.sprosti_pozabljene()

        self._straza = threading.Thread(target=tece, name="safeer-sway-straza", daemon=True)
        self._straza.start()


# ---------------------------------------------------------------------------------- namestitev

#: Kar drugi zaslon potrebuje: izvrsljiva datoteka -> paket (Debian, Ubuntu, Linux Mint).
#: Barvne tipke daljinca v brskalniku (oznake iz link_vnos.TIPKE).
BARVE_BRSKALNIK = {"rdeca": "brskalnik_nazaj", "zelena": "brskalnik_naprej",
                   "rumena": "osvezi", "modra": "nov_zavihek"}

#: Za koliko tock kratek pritisk smerne tipke premakne kazalec, kadar program polj ne pozna.
KORAK_KAZALCA = 24

BRSKALNIKI = ("brave", "chrome", "chromium", "msedge", "microsoft-edge", "vivaldi", "opera")
#: Druzina Firefox: ni med BRSKALNIKI (ti dobijo zastavice Chromiuma in se ob koncu seje zaprejo
#: posebej), je pa spletni brskalnik - barvne tipke in Nazaj v njem delujejo enako.
FIREFOXI = ("firefox", "librewolf", "waterfox", "floorp")


def _ime_brskalnika(pot: str, imena=BRSKALNIKI) -> bool:
    ime = os.path.basename(str(pot or "")).lower()
    return any(b in ime for b in imena)


def _je_spletni_brskalnik(pid: int) -> bool:
    """Katerikoli spletni brskalnik (Chromium ali Firefox) - za profil daljinca."""
    return _je_brskalnik(pid, BRSKALNIKI + FIREFOXI)


def _je_brskalnik(pid: int, imena=BRSKALNIKI) -> bool:
    # Chromium si ukazno vrstico prepise v en niz s presledki, zato najprej pogledamo izvrsljivo
    # datoteko, sele nato prvo besedo ukazne vrstice.
    try:
        if _ime_brskalnika(os.readlink("/proc/%d/exe" % pid), imena):
            return True
    except OSError:
        pass
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            prvi = f.read().split(b"\0")[0].decode("utf-8", "replace").split(" ")[0]
    except OSError:
        return False
    return _ime_brskalnika(prvi, imena)


def _namizje_x11() -> bool:
    """Ali je namizje uporabnika X11 (core/seja_prikaza): samo tam wmctrl vidi in premika vsa okna."""
    from core import seja_prikaza
    return seja_prikaza.je_x11()


def _pidi_na_namizju() -> Optional[set]:
    """PID-i oken na namizju racunalnika (X); None, kadar tega ne moremo ugotoviti.

    Wayland: wmctrl vidi samo okna XWayland - nepopoln seznam bi lazno rekel »program ni odprt na namizju«."""
    if not _namizje_x11() or not shutil.which("wmctrl"):
        return None
    try:
        r = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    pidi = set()
    for vrstica in r.stdout.splitlines():
        deli = vrstica.split()
        if len(deli) > 2 and deli[2].isdigit():
            pidi.add(int(deli[2]))
    return pidi


#: Toliko casa po zagonu ne sodimo, ali se je program odprl: proces se sele rojeva. Izjema: rod zagona smo ze
#: videli ziv (`_opazuj_zagon`) - potem je njegov konec zanesljiv tudi prej.
ZAGON_NAJMANJ_S = 2.0
#: Kako pogosto ta cas gledamo, ali je rod zagona zazivel.
ZAGON_OPAZUJ_S = 0.1
#: Konec rodu potrdimo z drugim pogledom: proces, ki se ravno zamenjuje (exec), za hip nima ne ukazne vrstice ne okolja.
ZAGON_POTRDI_S = 0.05
#: Oznaka zagona: v ukazni vrstici lupine, ki program zazene, in v okolju vsega njegovega rodu.
ZAGON_SPREMENLJIVKA = "SAFEER_ZAGON"


def zivi_zagon(zeton: str, proc: str = "/proc") -> bool:
    """Ali se tece kak proces tega uporabnika iz zagona z oznako `zeton` (tudi odcepljeni otroci in vsebniki).

    Kadar tega ne moremo ugotoviti, vrnemo True: raje cakamo, kot da program, ki se sele odpira, razglasimo za
    koncanega."""
    if not zeton:
        return False
    iskano = ("%s=%s" % (ZAGON_SPREMENLJIVKA, zeton)).encode("ascii")
    jaz = os.getuid()
    try:
        vnosi = os.listdir(proc)
    except OSError:
        return True
    for vnos in vnosi:
        if not vnos.isdigit():
            continue
        pot = os.path.join(proc, vnos)
        try:
            if os.stat(pot).st_uid != jaz:
                continue
        except OSError:
            continue
        for ime in ("cmdline", "environ"):
            try:
                with open(os.path.join(pot, ime), "rb") as f:
                    if iskano in f.read():
                        return True
            except OSError:
                continue
    return False


def razberi_okna(izpis: str) -> List[dict]:
    """Izpis `wmctrl -lpx` v seznam oken: [{"id", "pid", "razred"}] (razred z malimi crkami, npr. `gimp.gimp`)."""
    okna: List[dict] = []
    for vrstica in izpis.splitlines():
        deli = vrstica.split(None, 4)
        if len(deli) < 4 or not deli[2].lstrip("-").isdigit():
            continue
        okna.append({"id": deli[0], "pid": int(deli[2]), "razred": deli[3].lower()})
    return okna


def _okna_namizja() -> Optional[List[dict]]:
    """Okna na namizju racunalnika (X); None, kadar tega ne moremo ugotoviti (tudi Wayland, glej _pidi_na_namizju)."""
    if not _namizje_x11() or not shutil.which("wmctrl"):
        return None
    try:
        r = subprocess.run(["wmctrl", "-lpx"], capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    return razberi_okna(r.stdout) if r.returncode == 0 else None


def _ujema_razred(razred: str, kandidati) -> bool:
    """Razred okna (`primerek.razred`) proti imenom programa: cel, eden od delov ali z imenom na zacetku/koncu."""
    razred = str(razred or "").lower()
    for k in kandidati or ():
        k = str(k or "").strip().lower()
        if len(k) < 3:
            continue
        if razred == k or razred.startswith(k + ".") or razred.endswith("." + k):
            return True
    return False


def okno_programa(okna: List[dict], pidi, razredi, nova=None) -> str:
    """Id okna na namizju, ki pripada programu: po procesu ali po razredu okna. Okna, ki so nastala ob tem zagonu
    (`nova`), imajo prednost; med enakovrednimi zadnje (najnovejse). Prazno, ce takega okna ni."""
    pidi = set(pidi or ())
    moja = [o for o in okna if o.get("pid") in pidi or _ujema_razred(o.get("razred", ""), razredi)]
    if not moja:
        return ""
    if nova:
        sveza = [o for o in moja if o.get("id") in nova]
        if sveza:
            return str(sveza[-1]["id"])
    return str(moja[-1]["id"])


PAKETI = {"sway": "sway", "swaymsg": "sway", "wf-recorder": "wf-recorder", "wtype": "wtype"}
_WF: Optional[Dict[str, bool]] = None


def wf_zmoznosti(osvezi: bool = False) -> Dict[str, bool]:
    """Kaj zna namesceni wf-recorder (iz --help). Starejse razlicice nimajo vseh zastavic."""
    global _WF
    if _WF is None or osvezi:
        pomoc = ""
        if shutil.which("wf-recorder"):
            try:
                r = subprocess.run(["wf-recorder", "--help"], capture_output=True, text=True, timeout=5)
                pomoc = r.stdout + r.stderr
            except Exception:
                pomoc = ""
        _WF = {"muxer": "--muxer" in pomoc, "no_damage": "--no-damage" in pomoc,
               "codec_param": "--codec-param" in pomoc, "framerate": "--framerate" in pomoc}
    return _WF


def apt_razlicici(paket: str) -> Tuple[str, str]:
    """(namescena, na voljo) po apt-cache policy; prazno, kadar apt ne ve."""
    try:
        r = subprocess.run(["apt-cache", "policy", paket], capture_output=True, text=True, timeout=15,
                           env=dict(os.environ, LANG="C", LC_ALL="C"))
    except Exception:
        return "", ""
    namescena = kandidat = ""
    for vrstica in r.stdout.splitlines():
        v = vrstica.strip()
        if v.startswith("Installed:"):
            namescena = v.split(":", 1)[1].strip()
        elif v.startswith("Candidate:"):
            kandidat = v.split(":", 1)[1].strip()
    return ("" if namescena == "(none)" else namescena), ("" if kandidat == "(none)" else kandidat)


def stanje_namestitve() -> dict:
    """Kaj manjka za drugi zaslon in ali se da to urediti s paketi distribucije."""
    manjka = sorted({p for b, p in PAKETI.items() if not shutil.which(b)})
    prestar = bool(shutil.which("wf-recorder")) and not wf_zmoznosti()["muxer"]
    posodobitev = False
    if prestar:
        namescena, kandidat = apt_razlicici("wf-recorder")
        posodobitev = bool(kandidat) and kandidat != namescena
    return {"manjka": manjka, "prestar": prestar, "posodobitev": posodobitev,
            "graficna": bool(DrugiZaslon.graficna()),
            "orodja": bool(root_ukaz.na_voljo() and shutil.which("apt-get"))}


def _za_sway(argv: List[str]) -> str:
    """Ukazna vrstica za `swaymsg exec`: vsak argument v enojnih narekovajih. shlex.join vejice ne da v narekovaje,
    sway pa ob vejici (in podpicju) ukaz razdeli - ime datoteke »film.mkv,exit« bi izvedlo sway ukaz exit (neodvisni
    pregled, 19. 10. 2026). Znotraj narekovajev sway ne deli."""
    return " ".join("'" + str(a).replace("'", "'\"'\"'") + "'" for a in argv)


def paketi_za_namestitev(stanje: dict) -> List[str]:
    paketi = list(stanje.get("manjka") or [])
    if stanje.get("posodobitev") and "wf-recorder" not in paketi:
        paketi.append("wf-recorder")
    # Samo nasi paketi s stalnega seznama - nic, kar bi prislo od drugod.
    return [p for p in paketi if p in set(PAKETI.values())]


def opis_napake(izid, najvec: int = 400) -> str:
    """Konec izpisa neuspele namestitve (stderr, sicer stdout) za sporocilo uporabniku - prej se je zavrgel in ni bilo
    vidno, zakaj namestitev ni uspela (neodvisni pregled 19. 10. 2026)."""
    besedilo = (getattr(izid, "stderr", "") or getattr(izid, "stdout", "") or "")
    if isinstance(besedilo, bytes):
        besedilo = besedilo.decode("utf-8", "replace")
    besedilo = besedilo.strip()
    return besedilo[-najvec:] if besedilo else ""


def ukaz_namestitve(stanje: dict) -> Optional[List[str]]:
    """Namestitev ali posodobitev s sistemskim vprasanjem za geslo (pkexec). Zazene se samo, kadar
    uporabnik v Controlu to izrecno potrdi; geslo vpise sam v sistemsko okno."""
    paketi = paketi_za_namestitev(stanje)
    if not paketi or not stanje.get("orodja"):
        return None
    return [root_ukaz.pkexec(), root_ukaz.SH, "-c", "apt-get update -q; DEBIAN_FRONTEND=noninteractive apt-get install -y "
            + " ".join(paketi)]


# ---------------------------------------------------------------------------------- sway

def fiksno_platno(okno: dict) -> Optional[Tuple[int, int]]:
    """Naravna velikost okna, ki riše na nespremenljivo platno (stare igre GLUT/SDL1 prek XWaylanda).

    Tak program dobi okno cez cel zaslon, a slike ne raztegne: igra je bila v kotu, ostalo crno.
    Prepoznamo ga po tem, da je okno X11 brez razreda WM_CLASS - vsak sodoben gradnik (GTK, Qt,
    SDL2, Electron, brskalniki) ga nastavi, freeglut ga ne. Majhna okna (meniji, pogovorna okna) ne stejejo."""
    if not isinstance(okno, dict) or okno.get("shell") != "xwayland":
        return None
    lastnosti = okno.get("window_properties") or {}
    if lastnosti.get("class") or lastnosti.get("instance"):
        return None
    g = okno.get("geometry") or {}
    w, h = int(g.get("width") or 0), int(g.get("height") or 0)
    if w < 200 or h < 150:
        return None
    return w, h


def _ze_urejeno(okno: dict, platno: Tuple[int, int]) -> bool:
    """Okno ze lebdi v naravni velikosti (sway rect je v logicnih tockah, po merilu)."""
    r = okno.get("rect") or {}
    return okno.get("type") == "floating_con" and (int(r.get("width") or 0), int(r.get("height") or 0)) == platno


def merilo_platna(sirina: int, visina: int, w: int, h: int) -> float:
    """Koliko povecati platno, da zapolni zaslon brez obrezovanja (sway zna ulomke po 1/120)."""
    if w <= 0 or h <= 0:
        return 1.0
    m = min(sirina / w, visina / h, 6.0)
    return max(1.0, round(m * 120) / 120)


class DrugiZaslon:
    """Brezglavi sway kot drugi zaslon racunalnika, samo za televizor."""

    def __init__(self, mapa: Optional[str] = None) -> None:
        self.mapa = mapa or os.path.join(os.path.expanduser("~"), ".cache", "safeer", "drugi-zaslon")
        self.sirina, self.visina = 1920, 1080
        self._sway: Optional[subprocess.Popen] = None
        self._wayland = ""
        self._ipc = ""
        self._zvocni_modul = ""
        self._zadnji_zagon = 0.0
        self._kljuc = threading.RLock()
        #: Skupina zadnjega programa, ki ga je televizor zagnal ("igre" -> televizor zacne v nacinu tipk).
        self.zadnja_skupina = ""
        #: Profil zadnjega programa ("predvajalnik" -> televizor ga upravlja kot predvajalnik).
        self.zadnji_profil = ""
        self.vnos = SwayVnos(self)
        from core.link_mediji import Mpris
        #: Predvajalnik na tem zaslonu prek MPRIS (samo procesi, ki so potomci tega swaya).
        self.mediji = Mpris(lambda: self._sway.pid if self.tece() else 0,
                            lambda: self._wayland if self.tece() else "")
        from core.link_fokus import Fokus
        self.fokus = Fokus(self)
        self._merilo = 1.0
        #: Merilo za navadne programe (po napravi, ki gleda); igra s fiksnim platnom ima svoje.
        self._osnova = 1.0
        self._urejena_platna: Dict[int, int] = {}
        self._opazovalec: Optional[subprocess.Popen] = None
        #: Zadnji zagon programa: oznaka, cas, okna namizja pred zagonom in opis programa (link_programi).
        self._zagon: Optional[dict] = None

    # ----------------------------------------------------------------- zmoznosti
    @staticmethod
    def graficna() -> Optional[str]:
        for ime in ("renderD128", "renderD129"):
            pot = os.path.join("/dev/dri", ime)
            if os.path.exists(pot) and os.access(pot, os.R_OK | os.W_OK):
                return pot
        return None

    @classmethod
    def wf_recorder_zna(cls) -> bool:
        """Brez --muxer (gol H.264 na stdout) zajema ni; --no-damage in --codec-param sta dobrodosla,
        a ne nujna - starejsi wf-recorder brez njiju sliko se vedno poslje (samo ob spremembah)."""
        return wf_zmoznosti()["muxer"]

    @classmethod
    def mozno(cls) -> bool:
        """Ali ta racunalnik zna drugi zaslon: sway, dovolj nov wf-recorder in grafična kartica."""
        return bool(shutil.which("sway") and shutil.which("swaymsg") and shutil.which("wf-recorder")
                    and cls.graficna() and cls.wf_recorder_zna())

    def tece(self) -> bool:
        return self._sway is not None and self._sway.poll() is None

    def wayland_pot(self) -> str:
        return os.path.join(_run_mapa(), self._wayland) if self.tece() and self._wayland else ""

    def okolje(self) -> dict:
        # Programi na drugem zaslonu so zunanji programi: brez nasih zasebnih poti (core/zasebni_webkit.py).
        o = {k: v for k, v in zasebni_webkit.okolje_za_zunanje().items()
             if k not in ("DISPLAY", "WAYLAND_DISPLAY", "SWAYSOCK")}
        o.update({"XDG_RUNTIME_DIR": _run_mapa(), "WAYLAND_DISPLAY": self._wayland, "SWAYSOCK": self._ipc})
        return o

    # ----------------------------------------------------------------- zagon
    def zazeni(self, sirina: int = 1920, visina: int = 1080) -> bool:
        with self._kljuc:
            if self.tece():
                self.velikost(sirina, visina)
                self._zvok_pripravi()   # med sejama je bil lahko pospravljen
                return True
            if not self.mozno():
                return False
            os.makedirs(self.mapa, exist_ok=True)
            konf = os.path.join(self.mapa, "config")
            # Ostanek prejsnjega Controla (ubit brez pospravljanja) bi tekel v prazno.
            # pkill -f vzame regularni izraz: pot (XDG_CONFIG_HOME) je lahko z znaki, ki so v izrazu posebni - brez
            # re.escape bi signal dobil drug proces istega uporabnika (drugi neodvisni pregled, 19. 10. 2026).
            subprocess.run(["pkill", "-TERM", "-u", str(os.getuid()), "-f", "^sway -c " + re.escape(konf) + "$"],
                           capture_output=True, timeout=5)
            with open(konf, "w", encoding="utf-8") as f:
                f.write(_konfiguracija(sirina, visina))
            self.sirina, self.visina = sirina, visina
            self._zvok_pripravi()
            run = _run_mapa()
            pred = set(glob.glob(os.path.join(run, "wayland-*")))
            # Sway in vsi programi, ki jih zazene (exec), dobijo okolje brez nasih zasebnih poti (WebKit, AppImage).
            okolje = {k: v for k, v in zasebni_webkit.okolje_za_zunanje().items()
                      if k not in ("WAYLAND_DISPLAY", "DISPLAY", "SWAYSOCK")}
            okolje.update({"XDG_RUNTIME_DIR": run, "WLR_BACKENDS": "headless",
                           "WLR_RENDER_DRM_DEVICE": self.graficna() or "",
                           "WLR_LIBINPUT_NO_DEVICES": "1", "PULSE_SINK": ZVOCNI_IZHOD,
                           # programi na drugem zaslonu naj ne silijo na glavnega
                           "GDK_BACKEND": "wayland,x11", "QT_QPA_PLATFORM": "wayland;xcb",
                           "SDL_VIDEODRIVER": "wayland,x11", "MOZ_ENABLE_WAYLAND": "1",
                           # Skok po poljih (link_fokus) bere dostopnost. Brskalniki na osnovi
                           # Chromiuma (Brave, Chrome, Electron) in Qt je brez tega ne ponudijo;
                           # velja samo za programe na tem zaslonu, sistemske nastavitve ostanejo.
                           "ACCESSIBILITY_ENABLED": "1", "GNOME_ACCESSIBILITY": "1",
                           "QT_ACCESSIBILITY": "1", "QT_LINUX_ACCESSIBILITY_ALWAYS_ON": "1"})
            dnevnik = open(os.path.join(self.mapa, "sway.log"), "wb")     # samo za stdout/stderr programa sway
            # Skupina sway: swaybg in Xwayland (sway ju zazene brez setsid). Programi na zaslonu (exec) imajo svojo sejo
            # (sway/commands/exec_always.c: setsid) in jih ustavitev skupine ne konca (naloga 41).
            self._sway = otroci.zazeni(["sway", "-c", konf], env=okolje, stdout=dnevnik, stderr=dnevnik,
                                       stdin=subprocess.DEVNULL, dolgoziv=True)
            dnevnik.close()
            konec = time.monotonic() + 8
            while time.monotonic() < konec and self._sway.poll() is None:
                novi = [n for n in sorted(set(glob.glob(os.path.join(run, "wayland-*"))) - pred)
                        if not n.endswith(".lock")]
                ipc = glob.glob(os.path.join(run, "sway-ipc.%d.%d.sock" % (os.getuid(), self._sway.pid)))
                if novi and ipc:
                    self._wayland, self._ipc = os.path.basename(novi[0]), ipc[0]
                    print("[drugi zaslon] tece (%s, %dx%d)" % (self._wayland, sirina, visina), flush=True)
                    self._merilo = 1.0
                    self._osnova = 1.0
                    self._urejena_platna = {}
                    self._opazuj_okna()
                    return True
                time.sleep(0.1)
            print("[drugi zaslon] sway se ni zagnal", flush=True)
            self.ustavi()
            return False

    def velikost(self, sirina: int, visina: int) -> None:
        if (sirina, visina) != (self.sirina, self.visina) and self.tece():
            self._msg(["output", IZHOD, "resolution", "%dx%d@60Hz" % (sirina, visina)])
            self.sirina, self.visina = sirina, visina
            self._urejena_platna = {}
            self.uredi_platno()

    def osnovno_merilo(self, merilo: float) -> None:
        """Merilo izhoda za navadne programe: naprava z gostim majhnim zaslonom (telefon) dobi vecje gumbe.
        Fizicna locljivost in s tem slika, ki jo posiljamo, ostaneta enaki - programi so le narisani vecje."""
        try:
            merilo = min(3.0, max(1.0, float(merilo)))
        except (TypeError, ValueError):
            merilo = 1.0
        if abs(merilo - self._osnova) > 1e-6:
            self._osnova = merilo
            self._urejena_platna = {}
            self.uredi_platno()

    # ----------------------------------------------------------------- igre cez cel zaslon
    def _opazuj_okna(self) -> None:
        """Ob vsakem novem/fokusiranem/zaprtem oknu preveri, ali je spredaj igra s fiksnim platnom."""
        try:
            self._opazovalec = subprocess.Popen(["swaymsg", "-t", "subscribe", "-m", '["window"]'],
                                                env=self.okolje(), stdout=subprocess.PIPE,
                                                stderr=subprocess.DEVNULL, text=True)
        except Exception:
            self._opazovalec = None
            return
        opazovalec = self._opazovalec

        def tece() -> None:
            for vrstica in opazovalec.stdout:
                if '"change"' in vrstica and any(k in vrstica for k in ('"new"', '"focus"', '"close"')):
                    try:
                        self.uredi_platno()
                    except Exception as e:  # opazovalec ne sme nikoli pasti
                        print("[drugi zaslon] platno: %s" % e, flush=True)
        threading.Thread(target=tece, name="safeer-sway-okna", daemon=True).start()

    def _spredaj(self) -> Optional[dict]:
        try:
            drevo = json.loads(self._msg([], "get_tree") or "{}")
        except ValueError:
            return None
        najden: List[dict] = []

        def hodi(n):
            if n.get("focused") and (n.get("pid") or n.get("window")):
                najden.append(n)
            for o in n.get("nodes", []) + n.get("floating_nodes", []):
                hodi(o)
        hodi(drevo)
        return najden[0] if najden else None

    def uredi_platno(self) -> None:
        """Igra s fiksnim platnom (npr. Crack Attack) se na daljincu pokaze cez cel zaslon: izhod dobi
        merilo, okno pa lebdi v svoji naravni velikosti na sredini - sway ga raztegne brez obrezovanja.
        Zajem ostane enak (fizicna locljivost se ne spremeni), zato seja tece naprej. Ko je spredaj
        navaden program, se merilo vrne na osnovno (1 ali merilo naprave, ki gleda - osnovno_merilo)."""
        if not self.tece():
            return
        with self._kljuc:
            okno = self._spredaj()
            platno = fiksno_platno(okno) if okno else None
            merilo = merilo_platna(self.sirina, self.visina, *platno) if platno else self._osnova
            if okno is None and self._merilo != self._osnova and self.okna() > 0:
                return   # trenutek brez fokusa med preklopom - ne utripaj
            if abs(merilo - self._merilo) > 1e-6:
                self._msg(["output", IZHOD, "scale", "%.6f" % merilo])
                self._merilo = merilo
            if platno and not _ze_urejeno(okno, platno):
                self._msg(["[con_id=%d]" % int(okno["id"]), "floating enable, resize set %d %d, move position center"
                           % platno])
                # Stara igra si okno pogosto takoj po prikazu sama poveca nazaj (na velikost, ki jo je
                # dobila kot zavihek) - brez novega dogodka okna. Zato preverimo se nekajkrat.
                if self._urejena_platna.get(okno.get("id"), 0) < 4:
                    self._urejena_platna[okno.get("id")] = self._urejena_platna.get(okno.get("id"), 0) + 1
                    for zamik in (0.4, 1.5, 4.0):
                        t = threading.Timer(zamik, self._preveri_platno)
                        t.daemon = True
                        t.start()

    def _preveri_platno(self) -> None:
        try:
            self.uredi_platno()
        except Exception as e:
            print("[drugi zaslon] platno: %s" % e, flush=True)

    def _msg(self, argumenti: List[str], vrsta: Optional[str] = None) -> str:
        ukaz = ["swaymsg"] + (["-t", vrsta] if vrsta else []) + argumenti
        try:
            r = subprocess.run(ukaz, env=self.okolje(), capture_output=True, text=True, timeout=5)
            return r.stdout
        except Exception:
            return ""

    def zazeni_program(self, argv: List[str], opis: Optional[dict] = None) -> bool:
        """Zazene program na drugem zaslonu. argv pride iz nasega seznama programov, ne s televizorja.

        `opis` (link_programi): ime programa ter kako prepoznamo njegove procese in okna - za primer, ko se program
        ne odpre tu, ampak preda besedo oknu, ki je ze odprto na namizju racunalnika (program ene same instance)."""
        if not argv or not self.zazeni(self.sirina, self.visina):
            return False
        self._zadnji_zagon = time.monotonic()
        argv = list(argv)
        # Chromium (Brave, Chrome, Edge ...) polj brez tega dostopnosti ne pokaze, skok po poljih
        # z daljincem pa jo potrebuje. Velja samo za ta zagon.
        if _ime_brskalnika(argv[0]) and "--force-renderer-accessibility" not in argv:
            argv.insert(1, "--force-renderer-accessibility")
        zeton = secrets.token_hex(6)
        okna_pred = _okna_namizja()
        # Oznaka zagona je v ukazni vrstici lupine (sway pozene `sh -c`) in v okolju programa in njegovih otrok.
        izid = self._msg(["exec", "%s=%s %s" % (ZAGON_SPREMENLJIVKA, zeton, _za_sway(argv))])
        uspeh = '"success": true' in izid
        self._zagon = dict(opis or {}, zeton=zeton, cas=time.monotonic(),
                           okna_pred=None if okna_pred is None else {o["id"] for o in okna_pred}) if uspeh else None
        if uspeh:
            threading.Thread(target=self._opazuj_zagon, args=(self._zagon,), name="safeer-zagon", daemon=True).start()
        return uspeh

    def _opazuj_zagon(self, z: dict) -> None:
        """Opazi, da je rod zagona zazivel. Sway ukaz `exec` izvede z zamikom, zato »ne tece« tik po zagonu se ne
        pomeni »je koncal«; ko smo rod enkrat videli ziv, pa je njegov konec zanesljiv tudi pred ZAGON_NAJMANJ_S.
        Program ene same instance (preda besedo ze odprtemu oknu in konca) tako prepoznamo v sekundi namesto v treh."""
        rok = z["cas"] + ZAGON_NAJMANJ_S
        while self._zagon is z and time.monotonic() < rok:
            if zivi_zagon(z["zeton"]):
                z["videl"] = True
                return
            time.sleep(ZAGON_OPAZUJ_S)

    def izid_zagona(self) -> str:
        """Kaj se je zgodilo z zadnjim zagonom, kadar na drugem zaslonu NI okna (to preveri klicatelj):
        "" = se zaganja ali ne vemo; "koncan" = njegov rod je koncal brez okna; "na_namizju" = program ima okno
        na namizju racunalnika (bil je ze odprt in je zagon samo predal besedo, ali pa se je odprl tam)."""
        z = self._zagon
        if not z or not z.get("zeton"):
            return ""
        if not z.get("videl") and time.monotonic() - z["cas"] < ZAGON_NAJMANJ_S:
            return ""
        if zivi_zagon(z["zeton"]):
            z["videl"] = True
            return ""
        time.sleep(ZAGON_POTRDI_S)
        if zivi_zagon(z["zeton"]):
            return ""
        okna = _okna_namizja()
        if okna:
            pidi = set()
            najdi = z.get("pidi")
            if callable(najdi):
                try:
                    pidi = set(najdi())
                except Exception:
                    pidi = set()
            pred = z.get("okna_pred")
            nova = None if pred is None else {o["id"] for o in okna} - pred
            okno = okno_programa(okna, pidi, z.get("razredi") or [], nova)
            if okno:
                z["okno"] = okno
                return "na_namizju"
        return "koncan"

    def opis_zagona(self) -> dict:
        """Ime zadnjega zagnanega programa za napravo, ki gleda ({"name": ...}); prazno, ce ga ne poznamo."""
        ime = str((self._zagon or {}).get("ime") or "")
        return {"name": ime[:80]} if ime else {}

    def pokazi_na_namizju(self) -> bool:
        """Okno programa, ki se je namesto tu odprl (ali je ze bil odprt) na namizju, postavi v ospredje."""
        okno = str((self._zagon or {}).get("okno") or "")
        if not okno or not shutil.which("wmctrl") or not _namizje_x11():
            return False
        try:
            return subprocess.run(["wmctrl", "-ia", okno], capture_output=True, timeout=5).returncode == 0
        except Exception:
            return False

    def pokazi(self, pidi: List[int]) -> bool:
        """Postavi v ospredje okno enega od teh procesov, ce je na drugem zaslonu."""
        if not self.tece():
            return False
        for pid in pidi:
            if '"success": true' in self._msg(["[pid=%d]" % int(pid), "focus"]):
                return True
        return False

    def _okna_pidi(self) -> List[int]:
        """PID-i programov, ki imajo okno na drugem zaslonu."""
        if not self.tece():
            return []
        try:
            drevo = json.loads(self._msg([], "get_tree") or "{}")
        except ValueError:
            return []
        pidi: List[int] = []

        def hodi(n):
            if n.get("pid"):
                pidi.append(int(n["pid"]))
            for o in n.get("nodes", []) + n.get("floating_nodes", []):
                hodi(o)
        hodi(drevo)
        return pidi

    def zapri_okna(self) -> int:
        """Zapre programe na drugem zaslonu, ko uporabnik na televizorju konca sejo.

        Najprej vljudno, kot klik na X. Program z neshranjenim delom se lahko se vprasa - takrat
        ostane odprt in ga uporabnik najde v vrstici Nadaljuj. Brskalniki na osnovi Chromiuma
        (Brave, Chrome ...) prek XWaylanda X ne upostevajo; njih po treh sekundah zapremo s SIGTERM,
        kar je pri njih obicajen konec (zavihki se ob naslednjem zagonu obnovijo). Nikoli, kadar
        ima isti proces okno tudi na namizju racunalnika."""
        pidi = self._okna_pidi()
        if not pidi:
            return 0
        self._msg(["[all]", "kill"])
        threading.Thread(target=self._dokoncaj_zapiranje, daemon=True).start()
        return len(pidi)

    def _dokoncaj_zapiranje(self) -> None:
        time.sleep(3)
        ostali = set(self._okna_pidi())
        if not ostali:
            return
        namizje = _pidi_na_namizju()
        if namizje is None:
            return
        for pid in ostali:
            if pid in namizje or not _je_brskalnik(pid):
                continue
            try:
                os.kill(pid, signal.SIGTERM)
                print("[drugi zaslon] brskalnik %d zaprt" % pid, flush=True)
            except OSError:
                pass

    def okna(self) -> int:
        """Koliko oken je odprtih na drugem zaslonu."""
        if not self.tece():
            return 0
        drevo = self._msg([], "get_tree")
        return drevo.count('"pid":')

    # ----------------------------------------------------------------- slika in zvok
    def ukaz_zajema(self, fps: int, qp: int, bitrate: str, kodek: str = "h264", gop: int = 0) -> List[str]:
        """Gol H.264 ali HEVC (Annex-B) na stdout, kot ga pricakuje link_zaslon; vsak kader, tudi brez sprememb.

        `kodek`: "hevc" samo strojno (VAAPI); brez graficne kartice vedno H.264. `gop`: razmik kljucnih slik v
        slikah; 0 = vsako sekundo (starejsi gledalec)."""
        z = wf_zmoznosti()
        gpu = self.graficna()
        hevc = kodek == "hevc" and bool(gpu)
        skupina = gop if gop > 0 else max(1, fps)
        u = ["wf-recorder", "-o", IZHOD] + (["-D"] if z["no_damage"] else []) + \
            (["-r", str(max(1, fps))] if z["framerate"] else []) + ["-m", "hevc" if hevc else "h264", "-f", "/dev/stdout"]
        if gpu:
            parametri = ["rc_mode=CQP", "qp=%d" % qp, "profile=%s" % ("main" if hevc else "high"), "bf=0",
                         "g=%d" % skupina]
            u += ["-c", "hevc_vaapi" if hevc else "h264_vaapi", "-d", gpu]
        else:
            parametri = ["preset=veryfast", "tune=zerolatency", "b=%s" % bitrate, "bf=0", "g=%d" % skupina]
            u += ["-c", "libx264", "-x", "yuv420p"]
        if z["codec_param"]:
            for p in parametri:
                u += ["-p", p]
        return u

    def zvok_vir(self) -> Optional[str]:
        """Vir zvoka za sejo. Ce je izhod Safeer-TV med sejama pospravljen, ga spet ustvarimo."""
        with self._kljuc:
            if self.tece():
                self._zvok_pripravi()
            return ZVOCNI_IZHOD + ".monitor" if self._zvocni_modul else None

    def pospravi_zvok(self) -> bool:
        """Odstrani izhod Safeer-TV, ko na drugem zaslonu ni nobenega programa vec: takrat nanj nihce
        ne igra, med zvocnimi napravami uporabnika pa ne sme viseti. Dokler je kak program odprt
        (ali se sele odpira), izhod ostane - sicer bi PipeWire njegov zvok preusmeril na zvocnike
        racunalnika. Vrne, ali je izhod odstranil."""
        with self._kljuc:
            if not self._zvocni_modul or time.monotonic() - self._zadnji_zagon < ZVOK_PO_ZAGONU_S:
                return False
            if self.okna() > 0:
                return False
            pocisti_zvok()
            self._zvocni_modul = ""
            print("[drugi zaslon] izhod Safeer-TV pospravljen", flush=True)
            return True

    def _zvok_pripravi(self) -> None:
        """Navidezni zvocni izhod: kar igrajo programi drugega zaslona, gre samo na televizor."""
        if self._zvocni_modul or not shutil.which("pactl"):
            return
        try:
            pocisti_zvok()
            privzeti = subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True,
                                      timeout=3).stdout.strip()
            r = subprocess.run(["pactl", "load-module", "module-null-sink", "sink_name=" + ZVOCNI_IZHOD,
                                "sink_properties=device.description=Safeer-TV"],
                               capture_output=True, text=True, timeout=5)
            self._zvocni_modul = r.stdout.strip() if r.returncode == 0 else ""
            # Uporabnikov zvok ostane, kjer je bil.
            if privzeti and subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True,
                                           timeout=3).stdout.strip() != privzeti:
                subprocess.run(["pactl", "set-default-sink", privzeti], capture_output=True, timeout=3)
        except Exception:
            self._zvocni_modul = ""

    # ----------------------------------------------------------------- konec
    def ustavi(self) -> None:
        """Zapre drugi zaslon in vse programe na njem ter odstrani navidezni zvocni izhod."""
        with self._kljuc:
            self.vnos.zapri()
            self.fokus.ustavi()
            sway, self._sway = self._sway, None
            if sway is not None:
                otroci.ustavi(sway, rok=5)       # tudi ce je sway ze koncal, swaybg/Xwayland v skupini ne ostaneta
            self._wayland = self._ipc = ""
            if self._zvocni_modul:
                pocisti_zvok()
                self._zvocni_modul = ""


__all__ = ["DrugiZaslon", "SwayVnos", "ZVOCNI_IZHOD"]
