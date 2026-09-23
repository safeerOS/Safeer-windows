"""Programi racunalnika za Safeer OS na Linuxu.

Safeer OS je preobleka cez Linux Mint: pokaze VSE programe, ki jih ima uporabnik v meniju svojega
namizja (sistemske, svoje, Flatpak, Snap, nastavitve Cinnamona), in jih zazene natanko tako, kot bi
jih kliknil v meniju - v njihovih lastnih oknih. Nicesar ne namesca in nicesar ne spreminja.

Poleg seznama si zapomni, kaj uporabnik odpira (za »Pogosto uporabljeno« na domacem zaslonu) in
katere programe je pripel. Oboje je v ~/.config/safeer-os/os.json in ne zapusti racunalnika.
"""

from __future__ import annotations

import configparser
import hashlib
import json
import os
import shutil
import subprocess
import time
from typing import Dict, List, Optional

from core import link_programi

NAJVEC = 400
IKONA_VELIKOST = 96
MAPA_NASTAVITEV = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "safeer-os")
MAPA_IKON = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "safeer-os", "ikone")

#: Nastavitve sistema (Cinnamon, Mint) dobijo svojo skupino, da se ne mesajo med programe.
SISTEM = {"Settings", "System", "DesktopSettings", "HardwareSettings", "PackageManager", "Monitor", "Security"}
#: Vrstni red skupin v pogledu »Programi«.
SKUPINE = ("splet", "pisarna", "predstavnost", "igre", "ucenje", "programiranje", "orodja", "sistem", "drugo")
#: Programi, ki so del Safeerja samega (Safeer OS ne ponuja sebe).
IZPUSTI = {"safeer-os.desktop", "io.github.memelandfaner.SafeerOS.desktop"}


def skupina(kategorije) -> str:
    nabor = set(kategorije or ())
    osnovna = link_programi.skupina(nabor)
    if osnovna in ("igre",):
        return osnovna
    if nabor & SISTEM:
        return "sistem"
    return osnovna


def trenutna_namizja() -> List[str]:
    namizja = [d for d in (os.environ.get("XDG_CURRENT_DESKTOP") or "").split(":") if d]
    # Safeer OS tece v seji Cinnamona; brez spremenljivke (zagon iz storitve) velja Cinnamon.
    return namizja or ["X-Cinnamon"]


def _seznam(vrednost: str) -> List[str]:
    return [d for d in (vrednost or "").split(";") if d]


def preberi_vnos(pot: str, namizja: Optional[List[str]] = None) -> Optional[dict]:
    """En namizni vnos (.desktop) v obliki za Safeer OS ali None, ce ga meni ne bi pokazal."""
    razclen = configparser.RawConfigParser(strict=False, interpolation=None)
    razclen.optionxform = str
    try:
        with open(pot, encoding="utf-8", errors="replace") as f:
            razclen.read_file(f)
    except Exception:
        return None
    if not razclen.has_section("Desktop Entry"):
        return None
    vnos = razclen["Desktop Entry"]
    if vnos.get("Type", "") != "Application":
        return None
    for kljuc in ("NoDisplay", "Hidden", "Terminal"):
        if (vnos.get(kljuc, "") or "").strip().lower() == "true":
            return None
    namizja = namizja if namizja is not None else trenutna_namizja()
    samo = _seznam(vnos.get("OnlyShowIn", ""))
    if samo and not set(samo) & set(namizja):
        return None
    ne = _seznam(vnos.get("NotShowIn", ""))
    if ne and set(ne) & set(namizja):
        return None
    poskusi = (vnos.get("TryExec", "") or "").strip()
    if poskusi and not (os.path.isabs(poskusi) and os.access(poskusi, os.X_OK)) and not shutil.which(poskusi):
        return None
    ime = link_programi._vrednost(vnos, "Name").strip()
    if not ime:
        return None
    kategorije = _seznam(vnos.get("Categories", ""))
    kljucne = _seznam(link_programi._vrednost(vnos, "Keywords"))
    return {
        "pot": pot,
        "ime": ime,
        "opis": (link_programi._vrednost(vnos, "Comment") or link_programi._vrednost(vnos, "GenericName")).strip(),
        "splosno": link_programi._vrednost(vnos, "GenericName").strip(),
        "ikona": (vnos.get("Icon", "") or "").strip(),
        "skupina": skupina(kategorije),
        "kljucne": [k.strip() for k in kljucne if k.strip()][:12],
    }


class Shramba:
    """os.json: uporaba programov, pripeti programi in nastavitve Safeer OS."""

    def __init__(self, pot: Optional[str] = None) -> None:
        self.pot = pot or os.path.join(MAPA_NASTAVITEV, "os.json")
        try:
            with open(self.pot, encoding="utf-8") as f:
                self.podatki = json.load(f) or {}
        except Exception:
            self.podatki = {}
        if not isinstance(self.podatki, dict):
            self.podatki = {}

    def get(self, kljuc: str, privzeto=None):
        v = self.podatki.get(kljuc)
        return privzeto if v is None else v

    def set(self, kljuc: str, vrednost) -> None:
        self.podatki[kljuc] = vrednost
        self.shrani()

    def shrani(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.pot), exist_ok=True)
            zacasna = self.pot + ".tmp"
            with open(zacasna, "w", encoding="utf-8") as f:
                json.dump(self.podatki, f, ensure_ascii=False, indent=1)
            os.replace(zacasna, self.pot)
        except Exception:
            pass


class Programi:
    """Vsi programi iz menija; oznaka programa je ime njegovega .desktop vnosa."""

    def __init__(self, shramba: Shramba, mape: Optional[List[str]] = None,
                 namizja: Optional[List[str]] = None) -> None:
        self.shramba = shramba
        self._mape = mape
        self._namizja = namizja
        self._vnosi: Dict[str, dict] = {}

    # ------------------------------------------------------------------ seznam
    def preberi(self) -> Dict[str, dict]:
        najdeni: Dict[str, dict] = {}
        videna = set()
        for mapa in (self._mape if self._mape is not None else link_programi._mape_vnosov()):
            try:
                imena = sorted(os.listdir(mapa))
            except OSError:
                continue
            for ime in imena:
                if not ime.endswith(".desktop") or ime in najdeni or ime in IZPUSTI:
                    continue
                podatki = preberi_vnos(os.path.join(mapa, ime), self._namizja)
                if podatki is None:
                    continue
                # Isti program dvakrat (sistemsko in Flatpak) je v meniju samo zmeda: prvi obvelja.
                kljuc = (podatki["ime"].lower(), podatki["ikona"])
                if kljuc in videna:
                    continue
                videna.add(kljuc)
                najdeni[ime] = podatki
                if len(najdeni) >= NAJVEC:
                    break
        self._vnosi = najdeni
        return najdeni

    def seznam(self, ikone=None) -> List[dict]:
        """Seznam za stran: id, ime, opis, skupina, ikona (file:// ali ''), uporaba, pripet."""
        vnosi = self.preberi()
        uporaba = self.shramba.get("uporaba", {}) or {}
        pripeti = list(self.shramba.get("pripeti", []) or [])
        skriti = set(self.shramba.get("skriti_domov", []) or [])
        izhod = []
        for oznaka, v in sorted(vnosi.items(), key=lambda p: p[1]["ime"].lower()):
            u = uporaba.get(oznaka) or {}
            izhod.append({
                "id": oznaka, "ime": v["ime"], "opis": v["opis"], "splosno": v["splosno"],
                "skupina": v["skupina"], "kljucne": v["kljucne"],
                "ikona": ikone(v["ikona"]) if ikone else "",
                "uporaba": int(u.get("n", 0) or 0), "zadnjic": float(u.get("t", 0) or 0),
                "pripet": oznaka in pripeti,
                "skrit": oznaka in skriti,
            })
        return izhod

    def pot(self, oznaka: str) -> Optional[str]:
        ime = str(oznaka or "")
        if "/" in ime or not ime.endswith(".desktop"):
            return None
        if ime not in self._vnosi:
            self.preberi()
        v = self._vnosi.get(ime)
        return v["pot"] if v else None

    # ------------------------------------------------------------------ zagon
    def zabelezi(self, oznaka: str) -> None:
        uporaba = dict(self.shramba.get("uporaba", {}) or {})
        u = dict(uporaba.get(oznaka) or {})
        u["n"] = int(u.get("n", 0) or 0) + 1
        u["t"] = time.time()
        uporaba[oznaka] = u
        # Ne raste v nedogled: obdrzimo 200 zadnjih.
        if len(uporaba) > 200:
            uporaba = dict(sorted(uporaba.items(), key=lambda p: -float(p[1].get("t", 0)))[:200])
        self.shramba.set("uporaba", uporaba)

    def zazeni(self, oznaka: str, zaganjalnik=None) -> bool:
        """Zazene program s seznama tako, kot ga zazene meni. Nic drugega."""
        pot = self.pot(oznaka)
        if pot is None:
            return False
        ok = False
        if zaganjalnik is not None:
            try:
                ok = bool(zaganjalnik(pot))
            except Exception:
                ok = False
        if not ok:
            for ukaz in (["gio", "launch", pot], ["gtk-launch", oznaka]):
                if shutil.which(ukaz[0]) is None:
                    continue
                try:
                    subprocess.Popen(ukaz, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
                    ok = True
                    break
                except Exception:
                    continue
        if ok:
            self.zabelezi(oznaka)
        return ok

    def pripni(self, oznaka: str, pripet: bool) -> List[str]:
        pripeti = [p for p in (self.shramba.get("pripeti", []) or []) if p != oznaka]
        if pripet and self.pot(oznaka):
            pripeti.append(oznaka)
            self.skrij_domov(oznaka, False)      # pripet program je na domacem zaslonu vedno
        self.shramba.set("pripeti", pripeti[:24])
        return pripeti

    def skrij_domov(self, oznaka: str, skrij: bool = True) -> List[str]:
        """»Odstrani z zacetnega zaslona«: program ostane v Programih, na domacem ga ni vec (tudi ce je
        pogosto rabljen ali privzet). Ponovno ga pripelje pripenjanje."""
        skriti = [p for p in (self.shramba.get("skriti_domov", []) or []) if p != oznaka]
        if skrij and self.pot(oznaka):
            skriti.append(oznaka)
        self.shramba.set("skriti_domov", skriti[:200])
        return skriti


# ---------------------------------------------------------------------- ikone
def pot_ikone(ime: str, velikost: int = IKONA_VELIKOST) -> str:
    """Ikona programa kot PNG v predpomnilniku; vrne pot ali ''. Klicati na glavni niti (Gtk)."""
    if not ime:
        return ""
    cilj = os.path.join(MAPA_IKON, hashlib.sha1(("%s|%d" % (ime, velikost)).encode()).hexdigest() + ".png")
    if os.path.isfile(cilj) and os.path.getsize(cilj) > 0:
        return cilj
    izvor = ""
    if os.path.isabs(ime) and os.path.isfile(ime):
        izvor = ime
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf, Gtk
        if izvor:
            slika = GdkPixbuf.Pixbuf.new_from_file_at_size(izvor, velikost, velikost)
        else:
            tema = Gtk.IconTheme.get_default()
            ime_teme = ime[:-4] if ime.endswith((".png", ".svg", ".xpm")) else ime
            info = tema.lookup_icon(ime_teme, velikost, Gtk.IconLookupFlags.FORCE_SIZE)
            if info is None:
                return ""
            slika = info.load_icon()
        if slika is None:
            return ""
        os.makedirs(MAPA_IKON, exist_ok=True)
        slika.savev(cilj, "png", [], [])
        return cilj
    except Exception:
        return ""
