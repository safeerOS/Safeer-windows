"""Safeer DRM (Widevine prek castLabs ECS) vdelan v Splet Safeer OS in Safeer Browserja na Linuxu.

WebKitGTK nima Widevine. Prej (11. 10. 2026) se je stran z Widevine odprla v drugem brskalniku (Brave ...). Lastnik,
13. 10. 2026: zasciten video naj se predvaja v Spletu in v nasem predvajalniku, kot en predvajalnik - uporabnik ne sme
opaziti menjave. Zato: ko stran zaprosi za Widevine, se ista stran odpre v Safeer DRM, katerega okno je vstavljeno
(X11 XReparentWindow) v isti zavihek Spleta. Zavihek, naslovna vrstica in gumbi ostanejo; Nazaj in Osvezi delujeta.

Od 1.0.127 (lastnik, 18. 10. 2026) je Safeer DRM del paketa kot vse drugo: pripet castLabs ECS (SHA-256) je ob gradnji
namescen samo za branje v <tovor>/safeer-drm (deb: /usr/lib/safeer-os/safeer-drm, /usr/lib/safeer-browser/safeer-drm;
Flatpak: /app/lib/...; packaging/safeer_drm_paket.py) in se med delovanjem ne prenasa vec. Widevine CDM NI v paketu
(lastnik po FAQ castLabs: CDM, ki ga ECS prenese z Googlovih streznikov, pokriva licenca Googla): ECS ga ob prvi
zasciteni vsebini sam namesti in posodablja v mapa_widevine() - uporabnik ne namesca nicesar (assets/safeer_drm/main.js;
izmerjeno 18. 10. 2026, peskovnik Chromiuma, svez profil: prenos CDM in EME ok v ~2 s ob istem zagonu).
Star, ob zagonu prenesen paket (koren()/X.Y.Z, ~280 MB) pospravi pospravi_staro(); profili s prijavami ostanejo.

Safeer OS v Flatpaku Safeer DRM zazene na gostitelju (flatpak-spawn --host, pot programa v /app prevedena v pot na
gostitelju), da ostane peskovnik Chromiuma v celoti vklopljen. Safeer Browser v Flatpaku (od 1.0.127 brez dostopa do
gostitelja, lastnik 15. 10. 2026) ga zazene v svojem peskovniku prek zypak-wrapper (packaging/zypak, kot Electron
programi na Flathubu): Chromium svoje procese (zygote, strani, CDM) zapre v podpeskovnike portala Flatpak
(flatpak-spawn --sandbox) - peskovnik ostane vklopljen, brez --no-sandbox.
Brez X11 (Wayland) okna ni mogoce vstaviti: Safeer DRM se odpre v svojem oknu.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Callable, List, Optional

from core import otroci, vstavi_okno

#: Mapa Safeer DRM v tovoru paketa (<tovor>/safeer-drm, zraven core/). SAFEER_DRM_MAPA jo zamenja (preizkusi, razvoj).
SPREMENLJIVKA_MAPE = "SAFEER_DRM_MAPA"


def v_peskovniku() -> bool:
    """Flatpak brez dostopa do gostitelja (Safeer Browser): Safeer DRM tece v istem peskovniku prek zypaka."""
    from core import gostitelj
    return gostitelj.v_peskovniku()


def _xdg(ime: str, privzeto: str) -> Path:
    return Path(os.environ.get(ime) or os.path.expanduser(privzeto))


def vgrajena_mapa() -> Path:
    """Safeer DRM, namescen s paketom (samo za branje)."""
    return Path(os.environ.get(SPREMENLJIVKA_MAPE) or Path(__file__).resolve().parent.parent / "safeer-drm")


def izvrsljiva() -> Optional[Path]:
    """Program Safeer DRM iz paketa (Widevine CDM namesti ECS sam ob prvi zasciteni vsebini)."""
    exe = vgrajena_mapa() / "safeer-drm"
    if exe.is_file() and os.access(exe, os.X_OK):
        return exe
    return None


def koren() -> Path:
    """Uporabnikovi podatki Safeer DRM: profili s prijavami (profil, profil-spotify). Programa tu ni vec (je v paketu);
    stare prenesene verzije pospravi pospravi_staro()."""
    if v_peskovniku():
        # Zasebna mapa programa (~/.var/app/<ID>/data): edina, kamor sme peskovnik pisati brez dodatnih dovoljenj.
        return _xdg("XDG_DATA_HOME", "~/.local/share") / "safeer-drm"
    # Pot na gostitelju (ne ~/.var/app/...): Safeer DRM v Flatpaku Safeer OS tece na gostitelju.
    return Path(os.path.expanduser("~/.local/share/safeer-drm"))


def mapa_sej() -> Path:
    if v_peskovniku():
        return _xdg("XDG_CACHE_HOME", "~/.cache") / "safeer-drm"
    return Path(os.path.expanduser("~/.cache/safeer-drm"))


def mapa_widevine() -> Path:
    """Kamor castLabs ECS sam prenese in posodablja Widevine CDM: <userData>/WidevineCdm, userData =
    $XDG_CONFIG_HOME/<productName> (package.json: »Safeer DRM«). zypak mapo izpostavi podpeskovnikom
    (ZYPAK_EXPOSE_WIDEVINE_PATH), sicer se CDM prenese, naloziti pa ga ne more (README zypaka)."""
    return _xdg("XDG_CONFIG_HOME", "~/.config") / "Safeer DRM" / "WidevineCdm"


ZYPAK = "/app/bin/zypak-wrapper"


def ukaz_zagona(argumenti: list, peskovnik: Optional[bool] = None, gostitelj: Optional[bool] = None,
                zypak: str = ZYPAK) -> Optional[list]:
    """Ukaz, s katerim se zazene Safeer DRM (argumenti[0] je program).

    - Safeer Browser v Flatpaku (peskovnik): zypak-wrapper v istem peskovniku; brez zypaka None (nikoli brez
      peskovnika Chromiuma in nikoli na gostitelju).
    - Safeer OS v Flatpaku (gostitelj): flatpak-spawn --host; program iz /app po poti, kot jo vidi gostitelj.
    - Zunaj Flatpaka: neposredno."""
    peskovnik = v_peskovniku() if peskovnik is None else peskovnik
    gostitelj = (v_flatpaku() and not peskovnik) if gostitelj is None else gostitelj
    if peskovnik:
        if not (os.path.isfile(zypak) and os.access(zypak, os.X_OK)):
            print("[SafeerDRM] zypak-wrapper manjka - Safeer DRM ne tece brez peskovnika", flush=True)
            return None
        return [zypak] + list(argumenti)
    if gostitelj:
        from core import gostitelj as gost
        program = gost.app_na_gostitelju(str(argumenti[0])) if argumenti else None
        if not program:
            print("[SafeerDRM] pot programa na gostitelju ni znana (/.flatpak-info)", flush=True)
            return None
        # --watch-bus: konca se s Safeer OS. Zaslon izrecno (kot core/os_dock.py): sicer okno Safeer DRM nastane le,
        # ce je DISPLAY v okolju aktivacije D-Bus seje (pregled paketa 14. 10. 2026).
        return ["flatpak-spawn", "--host", "--watch-bus"] + gost.env_zaslona() + [program] + list(argumenti[1:])
    return list(argumenti)


def okolje_zagona(peskovnik: Optional[bool] = None) -> Optional[dict]:
    """V peskovniku: zypak mora poznati mapo Widevine (ustvarimo jo vnaprej, ker zypak izpostavi samo obstojeco - sicer
    bi prvo predvajanje po prenosu CDM odpovedalo). Program je v /app, ki ga podpeskovniki vidijo brez dodatnih poti."""
    peskovnik = v_peskovniku() if peskovnik is None else peskovnik
    if not peskovnik:
        return None
    wv = mapa_widevine()
    try:
        wv.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return dict(os.environ, ZYPAK_EXPOSE_WIDEVINE_PATH=str(wv))


#: Ime mape ene verzije prej prenesenega paketa v koren() (druge mape tam so profili s prijavami).
_VERZIJA_MAPE = re.compile(r"\d+\.\d+\.\d+")


def pospravi_staro(mapa: Optional[Path] = None) -> List[str]:
    """Selitev na paket (1.0.127): odstrani SAMO tisto, kar je prej prenesla in upravljala ta koda - mape verzij paketa
    (X.Y.Z s programom safeer-drm ali oznako .preverjeno), nedokoncane prenose (prenos-*.part) in razpakiranja (*.nova).
    Profili s prijavami (profil, profil-spotify) in vse drugo ostanejo. Widevine CDM v mapa_widevine() ostane - ECS ga
    uporablja in posodablja naprej (ni ga treba prenesti znova)."""
    mapa = Path(mapa) if mapa else koren()
    odstranjeno: List[str] = []
    try:
        vnosi = list(mapa.iterdir())
    except OSError:
        return odstranjeno
    for pot in vnosi:
        try:
            if pot.is_symlink():
                continue
            if pot.is_dir() and _VERZIJA_MAPE.fullmatch(pot.name) and (
                    (pot / "safeer-drm").is_file() or (pot / ".preverjeno").is_file()):
                shutil.rmtree(pot)
            elif pot.is_dir() and pot.name.endswith(".nova") and _VERZIJA_MAPE.fullmatch(pot.name[:-5]):
                shutil.rmtree(pot)
            elif pot.is_file() and pot.name.startswith("prenos-") and pot.name.endswith(".part"):
                pot.unlink()
            else:
                continue
            odstranjeno.append(pot.name)
        except OSError as e:
            print(f"[SafeerDRM] stare kopije {pot.name} ni bilo mogoce pospraviti: {e}", flush=True)
    if odstranjeno:
        print("[SafeerDRM] pospravljeno, kar je bilo prej preneseno:", ", ".join(sorted(odstranjeno)), flush=True)
    return odstranjeno


def pospravi_staro_v_ozadju() -> None:
    def delo():
        try:
            pospravi_staro()
        except Exception:  # noqa: BLE001 - selitev ne sme ustaviti zagona
            pass
    threading.Thread(target=delo, name="safeer-drm-selitev", daemon=True).start()


#: Storitve z narocnino: stalen profil (prijava ostane), brez samodejnega klika, prosto premikanje po https.
STORITVE = (
    "netflix.com", "primevideo.com", "amazon.com", "disneyplus.com", "max.com", "hbomax.com", "skyshowtime.com",
    "tv.apple.com", "voyo.si", "paramountplus.com", "dazn.com", "crunchyroll.com", "mubi.com", "rakuten.tv",
    "spotify.com", "tidal.com", "deezer.com",
)


def je_storitev(url: str) -> bool:
    import urllib.parse
    try:
        gost = (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    return any(gost == d or gost.endswith("." + d) for d in STORITVE)


def v_flatpaku() -> bool:
    return os.path.exists("/.flatpak-info")


#: Xlib za vstavitev okna je skupen s Sporocili (vgrajeni namizni programi): core/vstavi_okno.py - ena izvedba.
_X11 = vstavi_okno.X11


class Gostitelj:
    """Gradnik GTK4, nad katerim je okno Safeer DRM. En gostitelj = ena seja (en zavihek).

    GTK4 nima X okna na gradnik: okno Safeer DRM postane otrok X okna vrhnjega okna (Safeer OS / Splet) na mestu in
    v velikosti tega gradnika; mesto se preveri ob vsaki spremembi velikosti in ob branju stanja (200 ms)."""

    def __init__(self, Gtk, Gdk, GLib, ob_celozaslonu: Optional[Callable[[bool], None]] = None,
                 ob_koncu: Optional[Callable[[], None]] = None) -> None:
        self.Gtk, self.Gdk, self.GLib = Gtk, Gdk, GLib
        self.ob_celozaslonu, self.ob_koncu = ob_celozaslonu, ob_koncu
        self.gradnik = Gtk.DrawingArea()
        self.gradnik.set_name("safeer-drm")
        self.gradnik.set_hexpand(True); self.gradnik.set_vexpand(True)
        self.gradnik.set_focusable(True)
        self.gradnik.connect("resize", lambda *_: self._prilagodi())
        self.gradnik.set_draw_func(lambda _g, cr, *_: self._risi(_g, cr))
        self._mesto = None
        self._mesto_gradnika = vstavi_okno.Mesto(Gtk, self.gradnik)
        # Okno DRM je otrok vrhnjega okna, zato ga ob skritju gradnika (drug zavihek, Splet skrit) skrijemo sami.
        self.gradnik.connect("map", lambda *_: self._vidno(True))
        self.gradnik.connect("unmap", lambda *_: self._vidno(False))
        self.proces: Optional[subprocess.Popen] = None
        self.seja = ""
        self.stanje = ""
        self.ukazi = ""
        self._odmik = 0
        self._okno = 0
        self._x11: Optional[_X11] = None
        self._casovnik = 0
        self.url = ""

    def _risi(self, _g, cr) -> bool:
        cr.set_source_rgb(0, 0, 0)
        cr.paint()
        return False

    @staticmethod
    def na_voljo() -> bool:
        return izvrsljiva() is not None

    def _xid_starsa(self) -> int:
        return self._mesto_gradnika.xid_starsa()

    def _pravokotnik(self):
        """(x, y, sirina, visina) gradnika v X pikah povrsine vrhnjega okna (core/vstavi_okno.Mesto)."""
        return self._mesto_gradnika.pravokotnik()

    def zacni(self, url: str, storitev: bool = False) -> bool:
        exe = izvrsljiva()
        if exe is None or not url.startswith("https://"):
            return False
        self.ustavi()
        self.url = url
        stars = self._xid_starsa()
        seje = mapa_sej()
        seje.mkdir(parents=True, exist_ok=True)
        self.seja = tempfile.mkdtemp(prefix="seja-", dir=str(seje))
        self.stanje = os.path.join(self.seja, "events.jsonl")
        self.ukazi = os.path.join(self.seja, "command.txt")
        profil = str(koren() / "profil") if storitev else os.path.join(self.seja, "profil")
        args = [str(exe), f"--parent={stars or 1}", f"--url={url}", f"--profile={profil}",
                f"--state={self.stanje}", f"--command={self.ukazi}"]
        if storitev:
            args.append("--storitev=1")
        # Scit tudi v Safeer DRM (Netflix, Disney+ ...): sledilci in telemetrija tretjih (core/scit_pravila.py) - v
        # zasebni mapi seje, kot pravila Spotifyja.
        try:
            from core import scit_pravila
            pot_scita = os.path.join(self.seja, "scit.json")
            with open(pot_scita, "w", encoding="utf-8") as f:
                json.dump(scit_pravila.trenutna().za_drm(spotify=False), f)
            args.append("--scit=" + pot_scita)
        except (OSError, ImportError) as e:
            print("[Safeer DRM] pravila Scita:", type(e).__name__, flush=True)
        if not stars:
            args = [str(exe), url]   # brez X11: lastno okno (samostojni nacin)
        peskovnik = v_peskovniku()
        na_gostitelju = v_flatpaku() and not peskovnik
        if stars and not na_gostitelju:
            args.append(f"--lastnik={os.getpid()}")   # v peskovniku isti imenski prostor PID kot brskalnik
        args = ukaz_zagona(args, peskovnik=peskovnik, gostitelj=na_gostitelju)
        if args is None:
            return False
        try:
            # Electron (zygote, GPU, upodabljalniki) v svoji skupini; ustavi() in izhod procesa koncata vse (naloga 41).
            self.proces = otroci.zazeni(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        stdin=subprocess.DEVNULL, env=okolje_zagona(peskovnik), dolgoziv=True)
        except OSError as e:
            print("[SafeerDRM] zagon ni uspel:", e, flush=True)
            return False
        self._odmik, self._okno = 0, 0
        self._casovnik = self.GLib.timeout_add(200, self._beri)
        self.gradnik.grab_focus()
        return True

    def ukaz(self, ime: str) -> None:
        if self.proces is None or not self.ukazi:
            return
        try:
            with open(self.ukazi, "a", encoding="utf-8") as f:   # vec ukazov hitro zapored (tipke) se ne izgubi
                f.write(ime + "\n")
        except OSError:
            pass

    _TIPKE = {"Escape": "Escape", "space": "Space", "Left": "Left", "Right": "Right", "Up": "Up", "Down": "Down",
              "Return": "Enter", "KP_Enter": "Enter", "BackSpace": "Backspace", "Home": "Home", "End": "End",
              "Page_Up": "PageUp", "Page_Down": "PageDown", "Tab": "Tab", "Delete": "Delete"}

    def tipka(self, dogodek) -> bool:
        """Tipka, ki jo dobi Safeer OS, gre v Safeer DRM (vstavljeno okno X11 tipkovnice ne dobi samo)."""
        ime = self.Gdk.keyval_name(dogodek.keyval) or ""
        koda = self._TIPKE.get(ime) or (ime if len(ime) == 1 and ime.isalnum() else "")
        if not koda or self.proces is None:
            return False
        self.ukaz("key:" + koda)
        return True

    def _beri(self) -> bool:
        if self.proces is None:
            self._casovnik = 0
            return False
        if self.proces.poll() is not None:
            self._casovnik = 0
            self._pospravi()
            if self.ob_koncu:
                self.ob_koncu()
            return False
        try:
            with open(self.stanje, "r", encoding="utf-8") as f:
                f.seek(self._odmik)
                novo = f.read()
                self._odmik = f.tell()
        except OSError:
            return True
        for vrstica in novo.splitlines():
            try:
                d = json.loads(vrstica)
            except ValueError:
                continue
            vrsta = d.get("type")
            if vrsta == "WINDOW_HANDLE" and not self._okno:
                try:
                    self._vstavi(int(str(d.get("detail") or "0")))
                except (ValueError, OSError) as e:
                    print("[SafeerDRM] vstavitev okna:", e, flush=True)
            elif vrsta in ("FULLSCREEN_ON", "FULLSCREEN_OFF") and self.ob_celozaslonu:
                self.ob_celozaslonu(vrsta == "FULLSCREEN_ON")
                self.GLib.timeout_add(300, lambda: (self._prilagodi(), False)[1])
        self._prilagodi()   # gradnik se premakne tudi brez spremembe velikosti (vrstica zavihkov skrita/prikazana)
        return True

    def _vstavi(self, okno: int) -> None:
        stars = self._xid_starsa()
        if not okno or not stars:
            return
        mesto = self._pravokotnik()
        if mesto is None:
            return
        if self._x11 is None:
            self._x11 = _X11()
        self._x11.vstavi(okno, stars, *mesto)
        self._okno, self._mesto = okno, mesto

    def _vidno(self, vidno: bool) -> None:
        if self._x11 is not None and self._okno:
            self._mesto = None
            self._x11.pokazi(self._okno, vidno)
            if vidno:
                self._prilagodi()

    def _prilagodi(self) -> None:
        if self._x11 is None or not self._okno:
            return
        mesto = self._pravokotnik()
        if mesto is None or mesto == self._mesto:
            return
        self._mesto = mesto
        self._x11.velikost(self._okno, *mesto)

    def _pospravi(self) -> None:
        if self.seja:
            shutil.rmtree(self.seja, ignore_errors=True)
        self.seja = self.stanje = self.ukazi = ""
        self._okno = 0
        self.proces = None

    def ustavi(self) -> None:
        if self._casovnik:
            self.GLib.source_remove(self._casovnik)
            self._casovnik = 0
        if self.proces is not None and self.proces.poll() is None:
            otroci.ustavi(self.proces)
        self._pospravi()

    def unici(self) -> None:
        self.ustavi()
        if self._x11 is not None:
            self._x11.zapri()
            self._x11 = None
