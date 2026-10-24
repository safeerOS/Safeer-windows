"""Safeer OS v Flatpaku: programi, ikone in zagon na racunalniku (gostitelju), ne v peskovniku.

Flatpak je glavna pot distribucije (lastnik, 12. 10. 2026). V peskovniku je /usr runtime GNOME, sistem
racunalnika pa je (z dovoljenjem --filesystem=host-os:ro) pod /run/host/usr. Zato:
  - zaganjalnike in ikone programov beremo tudi iz /run/host/usr/...,
  - program zazenemo na gostitelju (flatpak-spawn --host gio launch <pot na gostitelju>), s potjo, kot jo vidi
    gostitelj (/run/host/usr/... -> /usr/...).
Zunaj Flatpaka so vse funkcije brez ucinka (vrnejo izvirne poti).

Safeer Browser v Flatpaku (od 1.0.127) teh dovoljenj nima: sme_na_gostitelja()/v_peskovniku() povesta skupni kodi
(Splet, Safeer DRM), da gre vse prek portalov (odpri_prek_portala, Gtk.UriLauncher/FileLauncher) in v peskovniku.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import List, Sequence

PREDPONA = "/run/host"


def v_flatpaku() -> bool:
    return bool(os.environ.get("FLATPAK_ID")) and os.path.exists("/.flatpak-info")


def podatki_gostitelja() -> str:
    """Uporabnikova mapa s podatki NA RACUNALNIKU (Smeti, zaganjalniki, ikone): v Flatpaku je XDG_DATA_HOME
    zasebna mapa peskovnika (~/.var/app/<id>/data), zato bi Safeer OS gledal v prazne Smeti, medtem ko gio trash
    datoteke odlozi v prave (preizkus na testnem PC 15. 10. 2026: »Smeti so prazne«, Razveljavi ni nasel nicesar).
    Flatpak hrani gostiteljevo vrednost v HOST_XDG_DATA_HOME."""
    if v_flatpaku():
        return os.environ.get("HOST_XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


def sme_na_gostitelja(info: str = "/.flatpak-info") -> bool:
    """Ali ta Flatpak sme zaganjati programe na gostitelju (dovoljenje org.freedesktop.Flatpak=talk)?

    Safeer OS (lupina namizja) ga ima, Safeer Browser od 1.0.127 ne vec (lastnik, 15. 10. 2026: brskalnik brez izhoda
    iz peskovnika). Skupna koda (Splet, Safeer DRM) se po tem odloci: brez dovoljenja gre vse prek portalov in v
    peskovniku. Vir je /.flatpak-info, ki ga napise Flatpak ob zagonu (program ga ne more spremeniti)."""
    if not os.path.exists(info):
        return False
    try:
        import configparser
        p = configparser.ConfigParser(interpolation=None, strict=False)
        p.optionxform = str
        p.read(info, encoding="utf-8")
        return p.get("Session Bus Policy", "org.freedesktop.Flatpak", fallback="") in ("talk", "own")
    except Exception:  # noqa: BLE001 - neberljivo: ravnaj kot brez dovoljenja (varneje)
        return False


def v_peskovniku() -> bool:
    """Flatpak brez dostopa do gostitelja (Safeer Browser): odpiranje prek portala, Safeer DRM prek zypaka."""
    return os.path.exists("/.flatpak-info") and not sme_na_gostitelja()


def mape_gostitelja(podmapa: str) -> List[str]:
    """Npr. podmapa "applications" -> ["/run/host/usr/share/applications", "/run/host/usr/local/share/applications"]."""
    if not v_flatpaku():
        return []
    return [os.path.join(PREDPONA, "usr", "share", podmapa), os.path.join(PREDPONA, "usr", "local", "share", podmapa)]


def na_gostitelju(pot: str) -> str:
    """Pot, kot jo vidi gostitelj: /run/host/usr/x -> /usr/x; druge poti (domaca mapa, /var/lib/flatpak) enake."""
    pot = str(pot or "")
    if pot == PREDPONA or pot.startswith(PREDPONA + "/"):
        return pot[len(PREDPONA):] or "/"
    return pot


def app_na_gostitelju(pot: str, info: str = "/.flatpak-info") -> str:
    """Pot do datoteke paketa (/app/...), kot jo vidi gostitelj: [Instance] app-path iz /.flatpak-info (»the absolute
    path on the host system of the app's app files, as mounted at /app«, flatpak-metadata(5), od Flatpaka 0.6.10).
    Safeer DRM iz paketa Safeer OS tako tece na gostitelju (flatpak-spawn --host). Druge poti ostanejo; brez app-path ""."""
    pot = str(pot or "")
    if pot != "/app" and not pot.startswith("/app/"):
        return pot
    try:
        import configparser
        p = configparser.ConfigParser(interpolation=None, strict=False)
        p.optionxform = str
        if not p.read(info, encoding="utf-8"):
            return ""
        koren = p.get("Instance", "app-path", fallback="").rstrip("/")
    except Exception:  # noqa: BLE001 - neberljivo: pot ni znana
        return ""
    return (koren + pot[len("/app"):]) if koren.startswith("/") else ""


def env_zaslona() -> List[str]:
    """--env za `flatpak-spawn --host`: zaslon peskovnika (DISPLAY, WAYLAND_DISPLAY), a samo NEPRAZNE vrednosti.

    Seja Wayland: Flatpak s fallback-x11 v peskovniku nima DISPLAY. Prej je slo na gostitelja `--env=DISPLAY=` (prazno),
    kar je programom XWayland na gostitelju (stari programi, igre) prepisalo pravi DISPLAY iz okolja seje - ostali so brez
    okna. Brez prazne vrednosti gostitelj uporabi svojo. Ime vticnice Wayland je v peskovniku enako kot na gostitelju."""
    return ["--env=%s=%s" % (k, os.environ[k]) for k in ("DISPLAY", "WAYLAND_DISPLAY") if os.environ.get(k)]


def zazeni_vnos(pot: str, datoteke: Sequence[str] = ()) -> bool:
    """Zazene zaganjalnik (.desktop) na gostitelju, po zelji z datotekami. Samo v Flatpaku."""
    if not v_flatpaku() or not shutil.which("flatpak-spawn"):
        return False
    ukaz = ["flatpak-spawn", "--host"] + env_zaslona() + [
            "gio", "launch", na_gostitelju(pot)] + [na_gostitelju(d) for d in datoteke]
    try:
        subprocess.Popen(ukaz, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except Exception:
        return False


PORTAL = ("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop", "org.freedesktop.portal.OpenURI")


def odpri_prek_portala(uri: str, vprasaj: bool = True, vodilo=None, ob_koncu=None) -> bool:
    """Naslov preda programu racunalnika prek portala xdg-desktop-portal (OpenURI) - brez zagona na gostitelju.

    `vprasaj`: portal pokaze izbiro programa (rezervni brskalnik z Widevine: privzeti brskalnik je lahko Safeer sam).
    `ob_koncu(uspeh)` se poklice, ko portal odgovori. Vrne False, ce zahteve ni bilo mogoce poslati."""
    try:
        from gi.repository import Gio, GLib
        vodilo = vodilo or Gio.bus_get_sync(Gio.BusType.SESSION, None)
        moznosti = {"ask": GLib.Variant("b", bool(vprasaj))}

        def odgovor(v, rezultat):
            uspeh = True
            try:
                v.call_finish(rezultat)
            except Exception as napaka:  # noqa: BLE001
                print("[Safeer] portal OpenURI:", napaka, flush=True)
                uspeh = False
            if ob_koncu is not None:
                ob_koncu(uspeh)
        vodilo.call(PORTAL[0], PORTAL[1], PORTAL[2], "OpenURI", GLib.Variant("(ssa{sv})", ("", str(uri), moznosti)),
                    None, Gio.DBusCallFlags.NONE, 30000, None, odgovor)
        return True
    except Exception as napaka:  # noqa: BLE001
        print("[Safeer] portal OpenURI:", napaka, flush=True)
        return False


def tema_ikon(Gtk):
    """Privzeta tema ikon zaslona (GTK4); None, ce zaslona ni."""
    from gi.repository import Gdk
    zaslon = Gdk.Display.get_default()
    return Gtk.IconTheme.get_for_display(zaslon) if zaslon is not None else None


def nalozen_gtk():
    """Modul Gtk 4 (vsi programi Safeer; GTK3 je umaknjen 18. 10. 2026)."""
    import gi
    if gi.get_required_version("Gtk") is None:
        gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    return Gtk


def ikona_iz_teme(ime: str, velikost: int) -> str:
    """Pot do datoteke ikone v temi ikon (kot jo najde namizje); '' ce je ni. Samo glavna nit."""
    try:
        Gtk = nalozen_gtk()
        tema = tema_ikon(Gtk)
        if tema is None:
            return ""
        # GTK4 namesto manjkajoce vrne ikono »image-missing«, zato najprej has_icon.
        if not tema.has_icon(ime):
            return ""
        slika = tema.lookup_icon(ime, None, velikost, 1, Gtk.TextDirection.NONE, 0)
        datoteka = slika.get_file() if slika is not None else None
        pot = (datoteka.get_path() or "") if datoteka is not None else ""
        return pot if pot and os.path.isfile(pot) else ""
    except Exception:
        return ""


def osvezi_temo_ikon() -> bool:
    """Tema ikon GTK4 naj znova prebere mape ikon (samo glavna nit). GTK4 novih ikon sam ne opazi: program, namescen,
    medtem ko Safeer OS tece, je imel v Programih do ponovnega zagona prazno ikono (testni PC 20. 10. 2026, Claude;
    izmerjeno: has_icon ostane False tudi po 6 s, po set_search_path je True). Ponovna nastavitev iste poti iskanja
    sprozi ponovno branje teme (vkljucno z ikonami gostitelja v Flatpaku, ki so ze v poti)."""
    try:
        tema = tema_ikon(nalozen_gtk())
        if tema is None:
            return False
        tema.set_search_path(tema.get_search_path())
        return True
    except Exception:  # noqa: BLE001
        return False


def dodaj_ikone_gostitelja(Gtk) -> None:
    """Tema ikon GTK naj najde tudi ikone programov, namescenih na racunalniku."""
    if not v_flatpaku():
        return
    try:
        tema = tema_ikon(Gtk)
        if tema is None:
            return
        for m in mape_gostitelja("icons") + mape_gostitelja("pixmaps"):
            if os.path.isdir(m):
                tema.add_search_path(m)
    except Exception:
        pass
