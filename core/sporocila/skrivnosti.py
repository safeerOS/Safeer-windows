"""Gesla in zetoni kanalov: samo v sistemski zbirki skrivnosti.

Linux: libsecret (GNOME Keyring / KWallet). Windows: Upravitelj poverilnic (Credential Manager).

Nikoli v nastavitveni datoteki, bazi ali dnevniku. Brez zbirke skrivnosti ostane skrivnost samo v
pomnilniku, dokler Safeer OS tece - ob naslednjem zagonu jo Sporocila vprasajo znova.
"""

from __future__ import annotations

import sys
from typing import Callable, Optional

STORITEV = "safeer-sporocila"
_SHEMA = None


def _secret():
    global _SHEMA
    import gi
    gi.require_version("Secret", "1")
    from gi.repository import Secret  # noqa: WPS433
    if _SHEMA is None:
        _SHEMA = Secret.Schema.new("si.safeer.Sporocila", Secret.SchemaFlags.NONE,
                                   {"application": Secret.SchemaAttributeType.STRING,
                                    "key": Secret.SchemaAttributeType.STRING})
    return Secret


# ------------------------------------------------------------------ Flatpak: Secret Service neposredno prek D-Bus
# libsecret v Flatpaku uporablja svojo zbirko (portal, ~/.var/app) in ne vidi gesel, ki jih je shranil Safeer OS iz
# paketa .deb (izmerjeno na testnem PC: lookup False, neposreden SearchItems pa gesla najde). Flatpak je glavna pot
# distribucije, zato v Flatpaku govorimo s sistemsko zbirko (GNOME Keyring) neposredno: isti vnosi kot libsecret.
_SHEMA_IME = "si.safeer.Sporocila"
_SS = ("org.freedesktop.secrets", "/org/freedesktop/secrets", "org.freedesktop.Secret.Service")


def _v_flatpaku() -> bool:
    import os
    return bool(os.environ.get("FLATPAK_ID")) and os.path.exists("/.flatpak-info")


def _ss():
    """(Gio, GLib, vodilo, seja) ali izjema. Seja »plain«: skrivnost potuje po lokalnem vodilu seje, kot pri libsecret
    brez sifriranja seje; vodilo je dosegljivo samo temu uporabniku."""
    from gi.repository import Gio, GLib  # noqa: WPS433
    vodilo = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    r = vodilo.call_sync(_SS[0], _SS[1], _SS[2], "OpenSession", GLib.Variant("(sv)", ("plain", GLib.Variant("s", ""))),
                         None, Gio.DBusCallFlags.NONE, 5000, None)
    return Gio, GLib, vodilo, r.unpack()[1]


def _ss_atributi(kljuc: str) -> dict:
    return {"application": STORITEV, "key": kljuc, "xdg:schema": _SHEMA_IME}


def _ss_klic(vodilo, Gio, GLib, pot, vmesnik, metoda, argumenti):
    return vodilo.call_sync(_SS[0], pot, vmesnik, metoda, argumenti, None, Gio.DBusCallFlags.NONE, 5000, None).unpack()


def _ss_poisci(kljuc: str):
    Gio, GLib, vodilo, seja = _ss()
    odklenjeni, zaklenjeni = _ss_klic(vodilo, Gio, GLib, _SS[1], _SS[2], "SearchItems",
                                     GLib.Variant("(a{ss})", (_ss_atributi(kljuc),)))
    return Gio, GLib, vodilo, seja, list(odklenjeni), list(zaklenjeni)


def _ss_preberi(kljuc: str) -> Optional[str]:
    Gio, GLib, vodilo, seja, odklenjeni, zaklenjeni = _ss_poisci(kljuc)
    if not odklenjeni and zaklenjeni:
        # Zaklenjena zbirka (samodejna prijava: GNOME Keyring se ob prijavi brez gesla ne odklene - testni PC,
        # 14. 10. 2026). libsecret zunaj Flatpaka ob branju sam vprasa za odklep; tu sprozimo isti sistemski poziv
        # (geslo za prijavo v racunalnik). Odgovor pride pozneje: naslednje branje (sinhronizacija, Poslji) uspe.
        global zbirka_zaklenjena
        zbirka_zaklenjena = True
        _ss_odkleni(vodilo, Gio, GLib, zaklenjeni)
        return None
    zbirka_zaklenjena = False
    if not odklenjeni:
        return None
    skrivnosti_ = _ss_klic(vodilo, Gio, GLib, _SS[1], _SS[2], "GetSecrets", GLib.Variant("(aoo)", (odklenjeni[:1], seja)))[0]
    for _pot, (_seja, _param, vrednost, _vrsta) in skrivnosti_.items():
        return bytes(vrednost).decode("utf-8")
    return None


#: Zadnje branje je naslo samo zaklenjene vnose (sporocilo uporabniku pove, kaj naj naredi).
zbirka_zaklenjena = False
_odklep_zahtevan = 0.0


def _ss_odkleni(vodilo, Gio, GLib, predmeti) -> None:
    """Sistemski poziv za odklep zbirke - najvec enkrat na 10 minut (ce uporabnik poziv zapre, ga ne vsiljujemo)."""
    import time
    global _odklep_zahtevan
    if time.monotonic() - _odklep_zahtevan < 600 and _odklep_zahtevan:
        return
    _odklep_zahtevan = time.monotonic()
    try:
        _odklenjeni, poziv = _ss_klic(vodilo, Gio, GLib, _SS[1], _SS[2], "Unlock", GLib.Variant("(ao)", (list(predmeti),)))
        if poziv and poziv != "/":
            vodilo.call(_SS[0], poziv, "org.freedesktop.Secret.Prompt", "Prompt", GLib.Variant("(s)", ("",)),
                        None, Gio.DBusCallFlags.NONE, -1, None, None, None)
    except Exception:  # noqa: BLE001 - brez poziva ostane rocni vnos gesla
        pass


def _ss_shrani(kljuc: str, vrednost: str) -> bool:
    Gio, GLib, vodilo, seja = _ss()
    zbirka = _ss_klic(vodilo, Gio, GLib, _SS[1], _SS[2], "ReadAlias", GLib.Variant("(s)", ("default",)))[0]
    if not zbirka or zbirka == "/":
        return False
    lastnosti = {"org.freedesktop.Secret.Item.Label": GLib.Variant("s", "Safeer Sporočila"),
                 "org.freedesktop.Secret.Item.Attributes": GLib.Variant("a{ss}", _ss_atributi(kljuc))}
    skrivnost = (seja, b"", vrednost.encode("utf-8"), "text/plain; charset=utf8")
    predmet, poziv = _ss_klic(vodilo, Gio, GLib, zbirka, "org.freedesktop.Secret.Collection", "CreateItem",
                              GLib.Variant("(a{sv}(oayays)b)", (lastnosti, skrivnost, True)))
    return bool(predmet and predmet != "/" and poziv == "/")


def _ss_pozabi(kljuc: str) -> None:
    Gio, GLib, vodilo, seja, odklenjeni, zaklenjeni = _ss_poisci(kljuc)
    for pot in odklenjeni + zaklenjeni:
        try:
            _ss_klic(vodilo, Gio, GLib, pot, "org.freedesktop.Secret.Item", "Delete", None)
        except Exception:
            pass


# ------------------------------------------------------------------ Windows: Credential Manager
def _win():
    import ctypes
    from ctypes import wintypes

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]
    return ctypes, wintypes, CREDENTIAL, ctypes.WinDLL("advapi32", use_last_error=True)


def _win_cilj(kljuc: str) -> str:
    return STORITEV + ":" + kljuc


def _win_shrani(kljuc: str, vrednost: str) -> bool:
    ctypes, wintypes, CREDENTIAL, adv = _win()
    podatki = vrednost.encode("utf-16-le")
    blob = (ctypes.c_ubyte * len(podatki)).from_buffer_copy(podatki)
    c = CREDENTIAL(Type=1, TargetName=_win_cilj(kljuc), CredentialBlobSize=len(podatki),
                   CredentialBlob=ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte)), Persist=2,
                   UserName="Safeer")
    return bool(adv.CredWriteW(ctypes.byref(c), 0))


def _win_preberi(kljuc: str) -> Optional[str]:
    ctypes, wintypes, CREDENTIAL, adv = _win()
    kazalec = ctypes.POINTER(CREDENTIAL)()
    if not adv.CredReadW(_win_cilj(kljuc), 1, 0, ctypes.byref(kazalec)):
        return None
    try:
        c = kazalec.contents
        return ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize).decode("utf-16-le")
    finally:
        adv.CredFree(kazalec)


def _win_pozabi(kljuc: str) -> None:
    ctypes, wintypes, CREDENTIAL, adv = _win()
    adv.CredDeleteW(_win_cilj(kljuc), 1, 0)


def shrani(kljuc: str, vrednost: str) -> bool:
    """True, ce je skrivnost shranjena v sistemsko zbirko; False = samo v pomnilniku."""
    if sys.platform == "win32":
        try:
            return _win_shrani(kljuc, vrednost)
        except Exception:
            return False
    if _v_flatpaku():
        try:
            return _ss_shrani(kljuc, vrednost)
        except Exception:
            return False
    try:
        Secret = _secret()
        return bool(Secret.password_store_sync(_SHEMA, {"application": STORITEV, "key": kljuc},
                                               Secret.COLLECTION_DEFAULT, "Safeer Sporočila", vrednost, None))
    except Exception:
        return False


def preberi(kljuc: str) -> Optional[str]:
    if sys.platform == "win32":
        try:
            return _win_preberi(kljuc)
        except Exception:
            return None
    if _v_flatpaku():
        try:
            return _ss_preberi(kljuc)
        except Exception:
            return None
    try:
        Secret = _secret()
        return Secret.password_lookup_sync(_SHEMA, {"application": STORITEV, "key": kljuc}, None)
    except Exception:
        return None


def pozabi(kljuc: str) -> None:
    if sys.platform == "win32":
        try:
            _win_pozabi(kljuc)
        except Exception:
            pass
        return
    if _v_flatpaku():
        try:
            _ss_pozabi(kljuc)
        except Exception:
            pass
        return
    try:
        Secret = _secret()
        Secret.password_clear_sync(_SHEMA, {"application": STORITEV, "key": kljuc}, None)
    except Exception:
        pass


class ManjkaSkrivnost(RuntimeError):
    """Kanal potrebuje geslo ali zeton, ki ga ni (ni zbirke skrivnosti ali je bil pozabljen)."""


def zahtevaj(kljuc: str, v_pomnilniku: Optional[str] = None,
             vnos: Optional[Callable[[], str]] = None) -> str:
    vrednost = v_pomnilniku or preberi(kljuc)
    if not vrednost and vnos is not None:
        vrednost = vnos()
    if not vrednost:
        if zbirka_zaklenjena:
            raise ManjkaSkrivnost("Zbirka gesel je zaklenjena. Odkleni jo v oknu, ki se je odprlo (geslo za prijavo v "
                                  "računalnik), in poskusi znova.")
        raise ManjkaSkrivnost("Za povezavo je treba vnesti geslo ali žeton.")
    return vrednost
