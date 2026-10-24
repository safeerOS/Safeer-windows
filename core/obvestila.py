"""Obvestila namizja za vse dele Safeerja - ena pot (lastnik, 15. 10. 2026: »vse je en proces, vsi nasi dodatki delujejo
kot del namiznega okolja«).

Prej je bilo pet poti: Gio.Application.send_notification (Safeer OS, prosnje za dostop), surovi D-Bus Notify (sredisce
Linka) in notify-send s tremi imeni programa (»Safeer«, »Safeer Control«, »Safeer OS«). Obvestila so se v namizju
zdruzevala pod razlicnimi programi z razlicnimi ikonami, v Flatpaku (brez notify-send) so se tiho izgubila, vsako je
zagnalo svoj proces.

Zdaj:
  - kadar v procesu tece Safeer OS (core/en_proces.os_app), gre obvestilo prek njegove Gio.Application: eno ime
    (Safeer OS), ena ikona, stalen id (novo obvestilo z istim id zamenja starega), gumbi kot dejanja aplikacije;
  - sicer prek aplikacije, ki jo poda klicatelj (samostojni Safeer Control), ali neposredno po D-Busu
    (org.freedesktop.Notifications) z imenom Safeer Control. Nikoli notify-send.

Gumbi so klici (Python): `gumbi=[(kljuc, napis, klic)]`, `privzeto=klic` (klik na obvestilo). Vse dela tudi iz niti.
"""
from __future__ import annotations

import os
import threading
from typing import Callable, Dict, List, Optional, Tuple

IKONA_OS = "safeer-os"
IKONA_CONTROL = "safeer-control"
IME_CONTROL = "Safeer Control"
IME_OS = "Safeer OS"
#: Dejanje aplikacije, ki izvede gumb obvestila; parameter "id|kljuc".
DEJANJE = "safeer-obvestilo"
NAJVEC_OBVESTIL_Z_GUMBI = 32
PRIORITETE = ("low", "normal", "high", "urgent")

Gumb = Tuple[str, str, Callable[[], None]]

# ---------------------------------------------------------------------------------------------- dejanja (gumbi)
#: Pot Gio.Application: id obvestila -> {kljuc: klic}.
_klici_app: Dict[str, Dict[str, Callable[[], None]]] = {}
#: Pot D-Bus: stevilka obvestila streznika -> {kljuc: klic}. Pritisk sporoci streznik s signalom ActionInvoked.
_dejanja: Dict[int, Dict[str, Callable[[], None]]] = {}
_dejanja_zaklep = threading.Lock()
_dejanja_narocena = False
#: Povezava z vodilom seje, na kateri poslusamo pritiske gumbov. Drzimo jo, dokler proces zivi: Gio.bus_get_sync vrne
#: skupno povezavo, ki se zapre, ko jo spusti zadnji lastnik - z njo bi tiho izginilo tudi narocilo na signal.
_vodilo_dejanj = None
#: Pot D-Bus: nas id -> stevilka streznika (za zamenjavo in umik obvestila z istim id).
_stevilke: Dict[str, int] = {}


def _omeji(slovar: dict) -> None:
    while len(slovar) >= NAJVEC_OBVESTIL_Z_GUMBI:
        slovar.pop(next(iter(slovar)), None)


def _izvedi(klic: Optional[Callable[[], None]]) -> None:
    if klic is None:
        return
    try:
        klic()
    except Exception as e:  # noqa: BLE001 - gumb obvestila ne sme podreti glavne zanke
        print("[Safeer] dejanje obvestila ni uspelo:", e, flush=True)


def _zapomni_dejanja(stevilka: int, klici: Dict[str, Callable[[], None]]) -> None:
    with _dejanja_zaklep:
        _omeji(_dejanja)
        _dejanja[int(stevilka)] = dict(klici)


def _ob_signalu_obvestila(_vodilo, _posiljatelj, _pot, _vmesnik, signal, parametri, *_ostalo) -> None:
    """ActionInvoked(stevilka, kljuc): izvede dejanje gumba.

    Signala NotificationClosed ne poslusamo: namizje ga poslje ze, ko oblacek obvestila izgine, obvestilo pa z
    gumbom ostane v pladnju - gumb bi bil takrat mrtev (videno v Cinnamonu). Gumbi se pozabijo ob pritisku ali ko jih
    izrine novejse obvestilo.
    """
    if signal != "ActionInvoked":
        return
    try:
        stevilka, kljuc = parametri.unpack()
    except Exception:  # noqa: BLE001
        return
    with _dejanja_zaklep:
        klici = _dejanja.pop(int(stevilka), None)
    _izvedi((klici or {}).get(str(kljuc)))


def _naroci_dejanja(vodilo) -> None:
    global _dejanja_narocena, _vodilo_dejanj
    if _dejanja_narocena:
        return
    from gi.repository import Gio
    vodilo.signal_subscribe("org.freedesktop.Notifications", "org.freedesktop.Notifications", "ActionInvoked",
                            "/org/freedesktop/Notifications", None, Gio.DBusSignalFlags.NONE, _ob_signalu_obvestila)
    _vodilo_dejanj = vodilo
    _dejanja_narocena = True


def _ob_dejanju_app(_dejanje, parameter) -> None:
    """Dejanje app.safeer-obvestilo("id|kljuc"): klic gumba, ki ga je zapomnilo nase obvestilo - nic drugega."""
    try:
        niz = parameter.get_string() if hasattr(parameter, "get_string") else str(parameter)
        ident, kljuc = niz.rsplit("|", 1)
    except Exception:  # noqa: BLE001
        return
    with _dejanja_zaklep:
        klic = (_klici_app.get(ident) or {}).get(kljuc)
    _izvedi(klic)


# ---------------------------------------------------------------------------------------------- izbira poti
def cilj(app=None):
    """Aplikacija, prek katere gre obvestilo: Safeer OS v tem procesu, sicer `app` (lahko None -> D-Bus)."""
    try:
        from core import en_proces
        os_app = en_proces.os_app()
    except Exception:  # noqa: BLE001
        os_app = None
    for a in (os_app, app):
        if a is None:
            continue
        try:
            if a.get_is_registered():
                return a
        except Exception:  # noqa: BLE001 - nadomestek v preizkusih nima get_is_registered
            return a
    return None


def _na_glavni(fn: Callable[[], None]) -> None:
    if threading.current_thread() is threading.main_thread():
        fn()
        return
    from gi.repository import GLib
    GLib.idle_add(lambda: (fn(), False)[1])


def _poslji_app(app, ident: str, naslov: str, besedilo: str, ikona: str, prioriteta: str,
                gumbi: List[Gumb], privzeto: Optional[Callable[[], None]]) -> None:
    from gi.repository import Gio, GLib
    if (gumbi or privzeto) and app.lookup_action(DEJANJE) is None:
        dejanje = Gio.SimpleAction.new(DEJANJE, GLib.VariantType.new("s"))
        dejanje.connect("activate", _ob_dejanju_app)
        app.add_action(dejanje)
    klici = {str(k): klic for k, _n, klic in gumbi}
    if privzeto is not None:
        klici["default"] = privzeto
    with _dejanja_zaklep:
        _klici_app.pop(ident, None)
        if klici:
            _omeji(_klici_app)
            _klici_app[ident] = klici
    o = Gio.Notification.new(naslov)
    o.set_body(besedilo)
    o.set_icon(Gio.ThemedIcon.new(ikona))
    o.set_priority(getattr(Gio.NotificationPriority, prioriteta.upper()))
    if privzeto is not None:
        o.set_default_action_and_target("app." + DEJANJE, GLib.Variant("s", ident + "|default"))
    for kljuc, napis, _klic in gumbi:
        o.add_button_with_target(str(napis), "app." + DEJANJE, GLib.Variant("s", ident + "|" + str(kljuc)))
    app.send_notification(ident, o)


def _poslji_dbus(ident: str, naslov: str, besedilo: str, cas_ms: int, prioriteta: str, gumbi: List[Gumb],
                 privzeto: Optional[Callable[[], None]], ime: str = IME_CONTROL, ime_ikone: str = IKONA_CONTROL) -> bool:
    try:
        from gi.repository import Gio, GLib
        vodilo = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        dejanja: List[str] = []
        klici = {str(k): klic for k, _n, klic in gumbi}
        if privzeto is not None:
            dejanja += ["default", ""]
            klici["default"] = privzeto
        for kljuc, napis, _klic in gumbi:
            dejanja += [str(kljuc), str(napis)]
        if dejanja:
            _naroci_dejanja(vodilo)
        namigi = {"urgency": GLib.Variant("y", min(2, PRIORITETE.index(prioriteta))),
                  "desktop-entry": GLib.Variant("s", os.environ.get("FLATPAK_ID") or "safeer-control")}
        with _dejanja_zaklep:
            zamenjaj = _stevilke.get(ident, 0)
        odgovor = vodilo.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                                   "org.freedesktop.Notifications", "Notify",
                                   GLib.Variant("(susssasa{sv}i)", (ime, zamenjaj, ime_ikone, naslov,
                                                                    besedilo, dejanja, namigi, int(cas_ms))),
                                   GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, 3000, None)
        stevilka = int(odgovor.unpack()[0])
        with _dejanja_zaklep:
            _omeji(_stevilke)
            _stevilke[ident] = stevilka
        if klici:
            _zapomni_dejanja(stevilka, klici)
        return True
    except Exception as e:  # noqa: BLE001 - brez streznika obvestil (ni namizja) obvestila ni
        print("[Safeer] obvestilo:", e, flush=True)
        return False


_stevec = 0


def poslji(naslov: str, besedilo: str = "", ident: str = "", *, gumbi: Optional[List[Gumb]] = None,
           privzeto: Optional[Callable[[], None]] = None, prioriteta: str = "normal", cas_ms: int = -1,
           app=None, dbus: bool = False) -> str:
    """Poslje obvestilo namizja; vrne njegov id. Novo obvestilo z istim `ident` zamenja starega.

    `app`: Gio.Application klicatelja (samostojni Control), ce Safeer OS v procesu ne tece. `cas_ms` velja samo za
    pot D-Bus (-1: kot namizje). Z glavne niti ali iz katerekoli druge - nikoli ne caka na namizje.

    `dbus=True`: vedno pot org.freedesktop.Notifications (z imenom in ikono Safeer OS, ce ta tece), da je stevilka
    obvestila znana (stevilka()) - tako ga lahko umakne tudi naslednji proces (npr. nova razlicica, zapri_stevilko)."""
    global _stevec
    if not ident:
        _stevec += 1
        ident = "safeer-%d-%d" % (os.getpid(), _stevec)
    prioriteta = prioriteta if prioriteta in PRIORITETE else "normal"
    gumbi = list(gumbi or [])
    naslov, besedilo = str(naslov or ""), str(besedilo or "")
    a = cilj(app)
    if dbus:
        os_tece = a is not None and ikona(app) == IKONA_OS
        threading.Thread(target=_poslji_dbus, args=(ident, naslov, besedilo, cas_ms, prioriteta, gumbi, privzeto,
                                                     IME_OS if os_tece else IME_CONTROL,
                                                     IKONA_OS if os_tece else IKONA_CONTROL),
                         name="safeer-obvestilo", daemon=True).start()
        return ident
    if a is not None:
        ime_ikone = ikona(app)

        def zdaj() -> None:
            try:
                _poslji_app(a, ident, naslov, besedilo, ime_ikone, prioriteta, gumbi, privzeto)
            except Exception as e:  # noqa: BLE001
                print("[Safeer] obvestilo:", e, flush=True)
        _na_glavni(zdaj)
        return ident
    threading.Thread(target=_poslji_dbus, args=(ident, naslov, besedilo, cas_ms, prioriteta, gumbi, privzeto),
                     name="safeer-obvestilo", daemon=True).start()
    return ident


def ikona(app=None) -> str:
    """Ikona obvestila za pot, ki jo izbere cilj(app): Safeer OS ali Safeer Control."""
    try:
        from core import en_proces
        a = cilj(app)
        return IKONA_OS if a is not None and a is en_proces.os_app() else IKONA_CONTROL
    except Exception:  # noqa: BLE001
        return IKONA_CONTROL


def poslji_gio(ident: str, obvestilo, app=None) -> None:
    """Ze sestavljeno Gio.Notification (z lastnimi dejanji app.*) - prek Safeer OS, ce tece, sicer prek `app`.
    Dejanja morajo biti na obeh aplikacijah (glej registriraj_na)."""
    a = cilj(app) or app
    if a is not None:
        a.send_notification(ident, obvestilo)


def registriraj_na(app) -> list:
    """Aplikacije, na katere klicatelj registrira dejanja svojih obvestil: `app` in Safeer OS, ce tece v procesu."""
    izid = [app]
    o = cilj(None)
    if o is not None and o is not app:
        izid.append(o)
    return izid


def umakni(ident: str, app=None) -> None:
    """Umakne obvestilo z id `ident` (obe poti)."""
    with _dejanja_zaklep:
        _klici_app.pop(ident, None)
        stevilka = _stevilke.pop(ident, 0)
    for a in {id(x): x for x in (cilj(app), app) if x is not None}.values():
        try:
            a.withdraw_notification(ident)
        except Exception:  # noqa: BLE001
            pass
    if stevilka:
        try:
            from gi.repository import Gio, GLib
            Gio.bus_get_sync(Gio.BusType.SESSION, None).call(
                "org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
                "CloseNotification", GLib.Variant("(u)", (stevilka,)), None, Gio.DBusCallFlags.NONE, 3000, None, None)
        except Exception:  # noqa: BLE001
            pass


def stevilka(ident: str) -> int:
    """Stevilka obvestila na streznik obvestil (samo pot D-Bus; 0 = ni znana)."""
    with _dejanja_zaklep:
        return int(_stevilke.get(ident, 0) or 0)


def zapri_stevilko(stevilka_obvestila: int) -> bool:
    """Zapre obvestilo po stevilki, ki jo je dal streznik obvestil - tudi obvestilo prejsnjega procesa (nova
    razlicica: »... je namescen - Znova zazeni zdaj« po samodejnem zagonu ne sme ostati, stresni preizkus 20. 10.)."""
    try:
        n = int(stevilka_obvestila)
    except (TypeError, ValueError):
        return False
    if n <= 0:
        return False
    try:
        from gi.repository import Gio, GLib
        # Brez cakanja na odgovor (kot umakni): klicatelj je lahko glavna nit, streznik obvestil pa ne sme zadrzati zagona.
        Gio.bus_get_sync(Gio.BusType.SESSION, None).call(
            "org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
            "CloseNotification", GLib.Variant("(u)", (n,)), None, Gio.DBusCallFlags.NONE, 3000, None, None)
        return True
    except Exception as e:  # noqa: BLE001 - obvestila ze ni ali ni streznika obvestil
        print("[Safeer] zapiranje obvestila %d: %s" % (n, e), flush=True)
        return False


__all__ = ["poslji", "poslji_gio", "umakni", "cilj", "ikona", "registriraj_na", "stevilka", "zapri_stevilko"]
