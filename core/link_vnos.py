"""Vnos s televizorja na racunalnik (Safeer Desktop Stream, faza 2).

Televizor poslje dogodek, racunalnik ga odigra na svojem namizju: tipka, besedilo, premik miske,
klik, kolesce. Nic drugega - ukazov z omrezja **ne** izvajamo. Vsak dogodek gre skozi seznam
dovoljenega; kar ni na njem, se tiho zavrze.

Na seji X11 to opravi `xdotool`, ki dogodke vstavi prek XTEST. Imena tipk so nasa, ne uporabnikova:
televizor poslje oznako (`gor`, `ok`, `nazaj`, `f5` ...), mi jo prevedemo v tisto, kar razume X.
Besedilo gre v `xdotool type` kot argument za `--`, nikoli skozi lupino.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from typing import Dict, List, Optional

#: Kaj televizor sme poslati kot tipko in v kaj to prevedemo za X.
TIPKE: Dict[str, str] = {
    "gor": "Up", "dol": "Down", "levo": "Left", "desno": "Right",
    "ok": "Return", "nazaj": "Escape", "domov": "super", "meni": "Menu",
    "presledek": "space", "vnasalka": "Return", "vracalka": "BackSpace",
    "brisalka": "Delete", "tabulator": "Tab", "ubezna": "Escape",
    "stran_gor": "Page_Up", "stran_dol": "Page_Down", "zacetek": "Home", "konec": "End",
    "predvajaj": "XF86AudioPlay", "ustavi": "XF86AudioStop",
    "naprej": "XF86AudioNext", "prejsnja": "XF86AudioPrev",
    "glasneje": "XF86AudioRaiseVolume", "tiseje": "XF86AudioLowerVolume", "utisaj": "XF86AudioMute",
    "celozaslonsko": "F11", "osvezi": "F5", "isci": "ctrl+f",
    "kopiraj": "ctrl+c", "prilepi": "ctrl+v", "izrezi": "ctrl+x", "razveljavi": "ctrl+z",
    "zapri_okno": "ctrl+w", "preklopi_okno": "alt+Tab",
    # Barvne tipke daljinca v brskalniku (samo locen zaslon, glej link_sway.BARVE_BRSKALNIK).
    "brskalnik_nazaj": "alt+Left", "brskalnik_naprej": "alt+Right", "nov_zavihek": "ctrl+t",
    # Delo z dokumentom: brez shranjevanja televizor ne bi bil uporaben za pisanje.
    "shrani": "ctrl+s", "shrani_kot": "ctrl+shift+s", "izberi_vse": "ctrl+a",
    "ponovi": "ctrl+y", "krepko": "ctrl+b", "lezece": "ctrl+i", "podcrtano": "ctrl+u",
    "natisni": "ctrl+p", "iskanje_naprej": "F3",
    "f1": "F1", "f2": "F2", "f3": "F3", "f4": "F4", "f5": "F5", "f6": "F6",
    "f7": "F7", "f8": "F8", "f9": "F9", "f10": "F10", "f11": "F11", "f12": "F12",
}

#: Gumbi miske: levi, srednji, desni in kolesce (4 gor, 5 dol).
GUMBI = {"levi": "1", "srednji": "2", "desni": "3"}
KOLESCE = {"gor": "4", "dol": "5"}

#: Najvec, kolikor se premaknemo z enim dogodkom, in najdaljse besedilo naenkrat.
NAJVEC_PREMIK = 400
NAJVEC_BESEDILA = 200

#: Kako dolgo sme tipka ostati pritisnjena, ne da bi televizor javil karkoli novega. Ce povezava
#: pade sredi drzanja (igra, drsenje), se tipka po tem casu sama spusti - pritisnjena tipka na
#: tujem racunalniku je huja tezava od izgubljenega pritiska.
NAJVEC_DRZANJA_S = 5.0


class Vnos:
    """Odigra dogodke televizorja na namizju. Brez xdotool ne naredi nicesar in to tudi pove."""

    def __init__(self, display: Optional[str] = None, xdotool: Optional[str] = None) -> None:
        self.display = display
        self.xdotool = xdotool if xdotool is not None else (shutil.which("xdotool") or "")
        self.stevec = 0
        # Tipke, ki jih ta trenutek drzimo: ime za X -> kdaj smo nazadnje slisali zanjo.
        self._drzane: Dict[str, float] = {}
        self._straza: Optional[threading.Thread] = None
        self._konec = threading.Event()

    @property
    def mozno(self) -> bool:
        return bool(self.xdotool)

    def izvedi(self, dogodek: dict) -> bool:
        """Vrne True, kadar smo dogodek res odigrali."""
        if not self.mozno or not isinstance(dogodek, dict):
            return False
        vrsta = str(dogodek.get("vrsta", "") or "")
        if vrsta == "tipka":
            return self._tipka(str(dogodek.get("tipka", "") or ""))
        if vrsta == "tipka_dol":
            return self._tipka_dol(str(dogodek.get("tipka", "") or ""))
        if vrsta == "tipka_gor":
            return self._tipka_gor(str(dogodek.get("tipka", "") or ""))
        if vrsta == "besedilo":
            return self._besedilo(str(dogodek.get("besedilo", "") or ""))
        if vrsta == "premik":
            return self._premik(dogodek.get("dx"), dogodek.get("dy"))
        if vrsta == "klik":
            return self._klik(str(dogodek.get("gumb", "levi") or "levi"), bool(dogodek.get("dvojni")))
        if vrsta == "kolesce":
            return self._kolesce(str(dogodek.get("smer", "") or ""), dogodek.get("koliko"))
        if vrsta == "tocka":
            # Dotik na tablici: kazalec natanko tja, kamor je prst pokazal (tocke zaslona).
            try:
                x, y = int(dogodek.get("x")), int(dogodek.get("y"))
            except (TypeError, ValueError):
                return False
            if x < 0 or y < 0 or x > 20000 or y > 20000:
                return False
            return self._pozeni(["mousemove", "--", str(x), str(y)])
        if vrsta == "gumb":
            st = GUMBI.get(str(dogodek.get("gumb", "levi") or "levi").strip().lower())
            if st is None:
                return False
            dol = bool(dogodek.get("dol"))
            self._gumb_drzan = st if dol else None
            return self._pozeni(["mousedown" if dol else "mouseup", st])
        return False

    # ------------------------------------------------------------------ posamezni dogodki

    def _tipka(self, oznaka: str) -> bool:
        tipka = TIPKE.get(oznaka.strip().lower())
        if tipka is None:
            return False
        return self._pozeni(["key", "--clearmodifiers", tipka])

    # -------------------------------------------------------------- drzanje tipke

    @staticmethod
    def _drzljiva(oznaka: str) -> Optional[str]:
        """Ime tipke za X, kadar jo je smiselno drzati.

        Bliznjice s krmilkami (ctrl+s) niso tipke, ki bi jih kdo drzal, in bi ob prekinjeni
        povezavi pustile pritisnjeno krmilko - te gredo samo kot kratek pritisk.
        """
        tipka = TIPKE.get(oznaka.strip().lower())
        if tipka is None or "+" in tipka:
            return None
        return tipka

    def _tipka_dol(self, oznaka: str) -> bool:
        tipka = self._drzljiva(oznaka)
        if tipka is None:
            return False
        self.sprosti_pozabljene()
        if tipka in self._drzane:
            self._drzane[tipka] = time.monotonic()   # televizor ponavlja, da se ve, da se drzi
            return True
        if not self._pozeni(["keydown", "--clearmodifiers", tipka]):
            return False
        self._drzane[tipka] = time.monotonic()
        self._zbudi_strazo()
        return True

    def _tipka_gor(self, oznaka: str) -> bool:
        tipka = self._drzljiva(oznaka)
        if tipka is None:
            return False
        self._drzane.pop(tipka, None)
        return self._pozeni(["keyup", "--clearmodifiers", tipka])

    def drzane(self) -> List[str]:
        """Katere tipke ta trenutek drzimo (za teste in dnevnik)."""
        return sorted(self._drzane)

    _gumb_drzan: Optional[str] = None

    def sprosti_vse(self) -> None:
        """Spusti vse drzane tipke. Klicemo ob koncu seje in ko povezava pade."""
        if self._gumb_drzan is not None:
            gumb, self._gumb_drzan = self._gumb_drzan, None
            self._pozeni(["mouseup", gumb])
        for tipka in list(self._drzane):
            self._drzane.pop(tipka, None)
            self._pozeni(["keyup", "--clearmodifiers", tipka])
        self._konec.set()

    def sprosti_pozabljene(self, zdaj: Optional[float] = None) -> None:
        """Spusti tipke, o katerih televizor predolgo ni nicesar rekel."""
        sedaj = time.monotonic() if zdaj is None else zdaj
        for tipka, ko in list(self._drzane.items()):
            if sedaj - ko > NAJVEC_DRZANJA_S:
                self._drzane.pop(tipka, None)
                self._pozeni(["keyup", "--clearmodifiers", tipka])

    def _zbudi_strazo(self) -> None:
        """Straza sama spusti pozabljene tipke tudi, kadar od televizorja ne pride nic vec."""
        if self._straza is not None and self._straza.is_alive():
            return
        self._konec.clear()

        def tece() -> None:
            while self._drzane and not self._konec.wait(1.0):
                self.sprosti_pozabljene()

        self._straza = threading.Thread(target=tece, name="safeer-vnos-straza", daemon=True)
        self._straza.start()

    def _besedilo(self, besedilo: str) -> bool:
        besedilo = besedilo[:NAJVEC_BESEDILA]
        if not besedilo or any(ord(z) < 32 for z in besedilo):
            return False
        return self._pozeni(["type", "--clearmodifiers", "--delay", "12", "--", besedilo])

    def _premik(self, dx, dy) -> bool:
        try:
            x = max(-NAJVEC_PREMIK, min(NAJVEC_PREMIK, int(dx)))
            y = max(-NAJVEC_PREMIK, min(NAJVEC_PREMIK, int(dy)))
        except (TypeError, ValueError):
            return False
        if x == 0 and y == 0:
            return False
        return self._pozeni(["mousemove_relative", "--", str(x), str(y)])

    def _klik(self, gumb: str, dvojni: bool) -> bool:
        st = GUMBI.get(gumb.strip().lower())
        if st is None:
            return False
        ukaz = ["click", "--clearmodifiers"]
        if dvojni:
            ukaz += ["--repeat", "2"]
        return self._pozeni(ukaz + [st])

    def _kolesce(self, smer: str, koliko) -> bool:
        st = KOLESCE.get(smer.strip().lower())
        if st is None:
            return False
        try:
            n = max(1, min(10, int(koliko or 1)))
        except (TypeError, ValueError):
            n = 1
        return self._pozeni(["click", "--repeat", str(n), st])

    def _pozeni(self, argumenti) -> bool:
        import os
        okolje = dict(os.environ)
        if self.display:
            okolje["DISPLAY"] = self.display
        try:
            subprocess.run([self.xdotool] + argumenti, check=False, timeout=3,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=okolje)
        except Exception:
            return False
        self.stevec += 1
        return True


__all__ = ["Vnos", "TIPKE", "GUMBI", "KOLESCE"]
