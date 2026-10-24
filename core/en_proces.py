"""Safeer OS in Safeer Control v enem procesu (lastnik, 11. in 12. 10. 2026: »vse mora biti en proces«, manj RAM-a).

Control je bil locen proces (67-117 MiB PSS: svoj Python, GTK, WebKit). Kadar tece Safeer OS, zdaj Control tece
v njegovem procesu: Safeer OS ustvari aplikacijo Control (isti GApplication ID in isti vmesniki D-Bus za zunanje
odjemalce, npr. safeerctl in zagon iz menija), med seboj pa se klicata neposredno - klic D-Bus samemu sebi z glavne
niti bi cakal na glavno zanko, ki jo isti klic blokira.

Brez Safeer OS (samostojni paket safeer-control, Windows ...) Control tece kot prej, v svojem procesu.
"""
from __future__ import annotations

import os
import threading
from typing import Any, Callable, Optional

_os = None
_control = None
_control_bo_vgrajen = False
_os_klic: Optional[Callable[[str, list], Optional[dict]]] = None


def nastavi_os(app, klic: Optional[Callable[[str, list], Optional[dict]]] = None) -> None:
    """Safeer OS se javi; `klic(metoda, argumenti)` streze vmesnik Predvajanje brez D-Bus."""
    global _os, _os_klic
    _os, _os_klic = app, klic


def nastavi_control(app) -> None:
    global _control
    _control = app


def os_app():
    return _os


def control_app():
    return _control


def vgradi_control() -> None:
    """Safeer OS to poklice pred uvozom safeer_control: Control bo v tem procesu Gio.Application (safeer_control._OSNOVA).
    Prej je to povedala okoljska spremenljivka SAFEER_CONTROL_VGRAJEN, ki jo je Safeer OS nastavil in odstranil, ko so v
    procesu ze tekle niti (GDBus, WebKit) - setenv med getenv druge niti je v glibc nedefiniran (19. 10. 2026)."""
    global _control_bo_vgrajen
    _control_bo_vgrajen = True


def control_bo_vgrajen() -> bool:
    return _control_bo_vgrajen


def vgrajen() -> bool:
    """Ali Control tece v procesu Safeer OS."""
    return _os is not None and _control is not None


def klic_os(metoda: str, argumenti: list) -> Optional[dict]:
    if _os_klic is None:
        return None
    return _os_klic(metoda, list(argumenti))


def _je_glavna(GLib) -> bool:
    """Glavna nit ali nit, ki zdaj vrti privzeto zanko GLib (cakanje nase bi jo zamrznilo za ves rok)."""
    if threading.current_thread() is threading.main_thread():
        return True
    try:
        return bool(GLib.MainContext.default().is_owner())
    except Exception:  # noqa: BLE001 - brez GLib velja samo glavna nit
        return False


def na_glavni(fn: Callable[[], Any], cas: float = 10.0, privzeto: Any = None, prednost: Optional[int] = None) -> Any:
    """Izvede `fn` na glavni niti (GTK) in vrne izid. Z glavne niti takoj; iz druge niti prek GLib.idle_add in caka
    najvec `cas` sekund (potem vrne `privzeto`). Izjema v `fn` gre klicatelju.

    Edini pomocnik za glavno nit (naloga 42): link_teamwork.na_glavni_niti ga klice s prednostjo dogodkov
    (GLib.PRIORITY_DEFAULT), da zasedena zanka Safeer OS klica ne zadrzuje."""
    if threading.current_thread() is threading.main_thread():
        return fn()
    from gi.repository import GLib
    if _je_glavna(GLib):
        return fn()
    izid: dict = {}
    konec = threading.Event()

    def tek() -> bool:
        try:
            izid["v"] = fn()
        except Exception as e:  # noqa: BLE001 - napako vrnemo klicatelju
            izid["e"] = e
        finally:
            konec.set()
        return False
    if prednost is None:
        GLib.idle_add(tek)
    else:
        GLib.idle_add(tek, priority=prednost)
    if not konec.wait(cas):
        return privzeto
    if "e" in izid:
        raise izid["e"]
    return izid.get("v")


def mapa_nastavitev_racunalnika() -> str:
    """~/.config racunalnika. V Flatpaku XDG_CONFIG_HOME kaze v peskovnik (~/.var/app/...), safeer-cinnamon in
    samozagoni pa so v ~/.config racunalnika (kot core/os_dock.mapa_launcherjev)."""
    return (None if os.environ.get("FLATPAK_ID") else os.environ.get("XDG_CONFIG_HOME")) or \
        os.path.join(os.path.expanduser("~"), ".config")


def delovna_safeer_cinnamon() -> bool:
    """Ali je vklopljena postavitev »delovna« Safeer Cinnamon: ob prijavi seja safeer-cinnamon (autostart/
    safeer-cinnamon.desktop) zazene Safeer OS z delovno povrsino, ta pa Control v svojem procesu. Lastna samozagona
    safeer-os.desktop in safeer-control.desktop sta med tem skrita (TUJI_ZAGONI v packaging/tema-cinnamon/safeer-cinnamon)
    in shranjena v safeer-cinnamon/zagoni/, od koder ju izklop vrne."""
    mapa = mapa_nastavitev_racunalnika()
    return os.path.isfile(os.path.join(mapa, "safeer-cinnamon", "vklopljeno")) and \
        os.path.isfile(os.path.join(mapa, "autostart", "safeer-cinnamon.desktop"))
