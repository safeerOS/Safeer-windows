"""Seja prikaza (X11 ali Wayland) in kaj Safeer v njej zmore - en vir za vse module.

Zakaj: Safeer je rasel na Linux Mint/Cinnamon (X11). Paket .deb cilja tudi Ubuntu 24.04, kjer je privzet GNOME na
Waylandu (lastnik, 18. 10. 2026: »tam mora Safeer delovati enako dobro«). Na Waylandu je DISPLAY se vedno nastavljen
(XWayland za stare programe), zato preverba »ali je DISPLAY« lazno pove X11: zajem korenskega okna da crno sliko,
seznam oken samo programe XWayland, xdotool premika samo okna XWayland - vse tiho. GNOME 46 XWayland ob prvi povezavi
sele zazene (+ pomnilnik za nic). Odlocitev zato pade tu, enkrat, in moduli vprasajo `je_wayland()` / `zmoznosti()`.

Pravila:
  * Seja = okolje uporabnika (WAYLAND_DISPLAY, XDG_SESSION_TYPE), ne ozadje GDK tega procesa: GDK_BACKEND=x11 na
    Waylandu da nasim oknom XWayland, namizje uporabnika pa ostane Wayland (zajem, vnos in seznam oken so zato
    Waylandovi).
  * Nasa okna (lastnosti EWMH, premik) so stvar ozadja GDK: `gdk_x11()`.
  * Kar na Waylandu ni mogoce, `zmoznosti()` vrne False in vmesnik tega ne pokaze (AGENTS.md: brez praznih gumbov).

Na Waylandu ni mogoce (protokol tega odjemalcu namenoma ne da) - in kako je to v Safeerju (18. 10. 2026):
  * namizje pod okni in vrstica z rezerviranim robom -> Safeer OS je aplikacija v oknu, stikalo Celozaslonsko skrito;
  * seznam tujih oken (vrstica), premik in »nad vsemi« -> okna postavi sestavljalnik; ponudba »Poslji na napravo«
    je obvestilo z gumboma namesto okna v kotu;
  * vgradnja tujega okna (Sporocila, Safeer DRM v zavihek) -> program se odpre v svojem oknu;
  * zajem zaslona in vnos brez dovoljenja -> portal: prvic dialog sistema, nato izbira obnovljena (core/portal_zaslon);
  * Plank -> na GNOME dock = priljubljeni (Ubuntu Dock), drugje »Prilagodi dock« skrit (core/os_dock).
"""

from __future__ import annotations

import os
import sys

# Brez »from typing import ...«: tipi so samo v opombah (from __future__ import annotations), modul pa uvozi tudi varuh
# procesov (core/varuh_procesov.py), ki naj bo cim manjsi - typing je +1,7 MB (izmerjeno 18. 10. 2026, Python 3.12).

#: Kaj zmore katera seja (glej zmoznosti()). Kljuci so imena, ki jih uporabljajo moduli in preizkusi.
ZMOZNOSTI = ("namizje", "seznam_oken", "vstavi_okno", "premik_oken", "rezervacija_roba", "vlecenje_iz_okna",
             "zajem_x11", "zajem_portal", "vnos_xdotool", "vnos_portal")


def _okolje(okolje: Optional[dict]) -> dict:
    return os.environ if okolje is None else okolje


def vrsta(okolje: Optional[dict] = None) -> str:
    """"wayland", "x11" ali "" (brez grafične seje: storitev, SSH).

    WAYLAND_DISPLAY ali XDG_SESSION_TYPE=wayland pomeni Wayland, tudi ce je DISPLAY nastavljen (XWayland)."""
    o = _okolje(okolje)
    tip = str(o.get("XDG_SESSION_TYPE") or "").strip().lower()
    if o.get("WAYLAND_DISPLAY") or tip == "wayland":
        return "wayland"
    if o.get("DISPLAY") or tip == "x11":
        return "x11"
    return ""


def je_wayland(okolje: Optional[dict] = None) -> bool:
    return vrsta(okolje) == "wayland"


def je_x11(okolje: Optional[dict] = None) -> bool:
    return vrsta(okolje) == "x11"


def namizje(okolje: Optional[dict] = None) -> str:
    """Namizno okolje z malimi crkami: gnome, kde, cinnamon, sway, hyprland, xfce, mate, lxqt ... ali ""."""
    o = _okolje(okolje)
    if o.get("SWAYSOCK"):
        return "sway"
    if o.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return "hyprland"
    imena = str(o.get("XDG_CURRENT_DESKTOP") or o.get("XDG_SESSION_DESKTOP") or o.get("DESKTOP_SESSION") or "")
    for ime in imena.replace(";", ":").split(":"):
        ime = ime.strip().lower()
        if ime and ime not in _PREDPONE:
            return _SOPOMENKE.get(ime, ime)
    return ""


#: Ubuntu, Pop!_OS in Zorin v XDG_CURRENT_DESKTOP za svojim imenom dodajo se »GNOME« (ubuntu:GNOME).
_PREDPONE = {"ubuntu", "pop", "zorin"}
_SOPOMENKE = {"x-cinnamon": "cinnamon", "gnome-classic": "gnome", "gnome-flashback": "gnome", "plasma": "kde"}


def gdk_x11() -> bool:
    """Ali so okna TEGA procesa okna X11 (GDK z ozadjem X11). Brez GDK v procesu: po okolju."""
    gdk = sys.modules.get("gi.repository.Gdk")
    if gdk is not None:
        try:
            prikaz = gdk.Display.get_default()
            if prikaz is not None:
                ime = type(prikaz).__name__
                if "Wayland" in ime:
                    return False
                if "X11" in ime:
                    return True
                return str(prikaz.get_name() or "").startswith(":")
        except Exception:  # noqa: BLE001 - GDK se ni inicializiran
            pass
    zaledje = str(os.environ.get("GDK_BACKEND") or "").split(",")[0].strip().lower()
    if zaledje == "x11":
        return bool(os.environ.get("DISPLAY"))
    return je_x11()


def portal_na_voljo(vmesnik: str) -> bool:
    """Ali xdg-desktop-portal na vodilu seje ponuja vmesnik (npr. org.freedesktop.portal.ScreenCast)."""
    try:
        from gi.repository import Gio, GLib
        vodilo = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        izid = vodilo.call_sync("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                                "org.freedesktop.DBus.Properties", "Get",
                                GLib.Variant("(ss)", (vmesnik, "version")), GLib.VariantType("(v)"),
                                Gio.DBusCallFlags.NONE, 1500, None)
        return int(izid.unpack()[0]) >= 1
    except Exception:  # noqa: BLE001 - ni vodila, portala ali vmesnika
        return False


def zmoznosti(okolje: Optional[dict] = None, portal=None) -> Dict[str, bool]:
    """Kaj Safeer v tej seji zmore. `portal(vmesnik) -> bool` zamenja preverbo portala (preizkusi).

    X11 (EWMH): namizje pod okni, seznam in premik oken, vstavljanje tujega okna, rezervacija roba za vrstico, zajem
    korenskega okna in vnos s xdotool. Wayland: nic od tega (protokol tega odjemalcu namenoma ne da); zajem in vnos
    gresta prek portala (ScreenCast, RemoteDesktop), ki ga potrdi uporabnik."""
    v = vrsta(okolje)
    x = v == "x11"
    w = v == "wayland"
    preveri = portal if portal is not None else portal_na_voljo
    return {
        "namizje": x, "seznam_oken": x, "vstavi_okno": x, "premik_oken": x, "rezervacija_roba": x,
        "vlecenje_iz_okna": x, "zajem_x11": x, "vnos_xdotool": x,
        "zajem_portal": w and bool(preveri("org.freedesktop.portal.ScreenCast")),
        "vnos_portal": w and bool(preveri("org.freedesktop.portal.RemoteDesktop")),
    }


__all__ = ["vrsta", "je_wayland", "je_x11", "namizje", "gdk_x11", "portal_na_voljo", "zmoznosti", "ZMOZNOSTI"]
