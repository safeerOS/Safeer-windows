"""Magnet povezave na Windows: zaganjalnik Safeer OS in registracija protokola magnet: za tega uporabnika.

Protokol registriramo SAMO, ko uporabnik v Safeer OS pritisne »Odpiraj magnet povezave v Safeer«
(magnetPrivzeto), nikoli tiho. Vse gre v HKEY_CURRENT_USER (brez skrbniških pravic):

- ``Software\\Classes\\magnet`` - protokol magnet: z ukazom ``"<Safeer OS>" --magnet "%1"``;
- ``Software\\Classes\\Safeer.Magnet`` - isti ukaz kot ProgID, da se Safeer OS pokaže v Nastavitvah
  (Privzete aplikacije -> magnet), in ``Software\\SafeerOS\\Capabilities`` + ``RegisteredApplications``.

Ce je uporabnik v Nastavitvah Windows za magnet izbral drug program (UserChoice), tega ne moremo in
ne smemo povoziti (Windows to namerno preprecuje); odpremo mu stran Privzete aplikacije, kjer izbere sam.
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import List, Optional

PROGID = "Safeer.Magnet"
KLJUC_PROTOKOLA = r"Software\Classes\magnet"
KLJUC_PROGID = "Software\\Classes\\" + PROGID
KLJUC_ZMOZNOSTI = r"Software\SafeerOS\Capabilities"
KLJUC_REGISTRIRANIH = r"Software\RegisteredApplications"
KLJUC_IZBIRE = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\magnet\UserChoice"
IME_APLIKACIJE = "Safeer OS"


def _koren_repozitorija() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def zaganjalnik() -> List[str]:
    """Ukaz, ki zažene Safeer OS (brez argumentov); [] če ga ni mogoče najti.

    Vrstni red: zapakiran SafeerOS.exe (PyInstaller), zaganjalnik, ki nas je zagnal (SAFEER_OS_EXE),
    namescen SafeerOS.exe, nazadnje Python z windows/safeer_os_windows.py (zagon iz izvorne kode)."""
    if getattr(sys, "frozen", False) and os.path.isfile(sys.executable):
        return [sys.executable]
    kandidati = [os.environ.get("SAFEER_OS_EXE", "")]
    lokalno = os.environ.get("LOCALAPPDATA", "")
    if lokalno:
        kandidati.append(os.path.join(lokalno, "SafeerOS", "SafeerOS.exe"))
    for programi in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")):
        if programi:
            kandidati += [os.path.join(programi, "Safeer Browser", "SafeerOS.exe"),
                          os.path.join(programi, "Safeer", "SafeerOS.exe")]
    if lokalno:
        kandidati.append(os.path.join(lokalno, "Programs", "Safeer Browser", "SafeerOS.exe"))
    for pot in kandidati:
        if pot and pot.lower().endswith(".exe") and os.path.isfile(pot):
            return [os.path.abspath(pot)]
    skripta = os.path.join(_koren_repozitorija(), "windows", "safeer_os_windows.py")
    if os.path.isfile(skripta) and sys.executable:
        python = sys.executable
        # pythonw.exe: brez okna ukazne vrstice ob odpiranju povezave.
        brez_okna = os.path.join(os.path.dirname(python), "pythonw.exe")
        if os.path.basename(python).lower() == "python.exe" and os.path.isfile(brez_okna):
            python = brez_okna
        return [python, skripta]
    return []


def ukaz_za_magnet() -> str:
    """Ukaz za register: "<zaganjalnik>" --magnet "%1" (pravilno citiran tudi pri poteh s presledki)."""
    ukaz = zaganjalnik()
    if not ukaz:
        return ""
    return subprocess.list2cmdline(ukaz + ["--magnet"]) + ' "%1"'


def _preberi(winreg, koren, pot: str, ime: str = "") -> Optional[str]:
    try:
        with winreg.OpenKey(koren, pot) as kljuc:
            vrednost, _ = winreg.QueryValueEx(kljuc, ime)
        return str(vrednost)
    except OSError:
        return None


def _zapisi(winreg, pot: str, vrednosti: dict) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, pot) as kljuc:
        for ime, vrednost in vrednosti.items():
            winreg.SetValueEx(kljuc, ime, 0, winreg.REG_SZ, vrednost)


def _nas_ukaz(ukaz: Optional[str], nas: str) -> bool:
    return bool(ukaz and nas and ukaz.strip().lower() == nas.strip().lower())


def je_privzeto(winreg=None) -> bool:
    """Ali Windows magnet povezave res odpre s Safeer OS."""
    if winreg is None:
        if sys.platform != "win32":
            return False
        import winreg  # type: ignore[no-redef]
    nas = ukaz_za_magnet()
    if not nas:
        return False
    izbira = _preberi(winreg, winreg.HKEY_CURRENT_USER, KLJUC_IZBIRE, "ProgId") or ""
    if izbira and izbira.lower() == PROGID.lower():
        return _nas_ukaz(_preberi(winreg, winreg.HKEY_CURRENT_USER, KLJUC_PROGID + r"\shell\open\command"), nas)
    if izbira and izbira.lower() != "magnet":
        return False          # uporabnik je v Nastavitvah izbral drug program
    # Brez izbire (ali izbira "magnet") velja HKCR\magnet: HKCU prekrije HKLM.
    return _nas_ukaz(_preberi(winreg, winreg.HKEY_CLASSES_ROOT, r"magnet\shell\open\command"), nas)


def nastavi_privzeto(winreg=None, odpri_nastavitve=None) -> bool:
    """Registrira protokol magnet: za tega uporabnika (samo na izrecno željo uporabnika).

    Vrne je_privzeto(). Kadar ima prednost uporabnikova prejšnja izbira v Nastavitvah, odpre stran
    Privzete aplikacije, da Safeer OS izbere sam."""
    if winreg is None:
        if sys.platform != "win32":
            return False
        import winreg  # type: ignore[no-redef]
    ukaz = ukaz_za_magnet()
    if not ukaz:
        return False
    ikona = zaganjalnik()[0] + ",0"
    try:
        for pot, ime in ((KLJUC_PROTOKOLA, "URL:Magnet"), (KLJUC_PROGID, "Magnet (Safeer OS)")):
            _zapisi(winreg, pot, {"": ime, "URL Protocol": ""})
            _zapisi(winreg, pot + r"\DefaultIcon", {"": ikona})
            _zapisi(winreg, pot + r"\shell\open\command", {"": ukaz})
        _zapisi(winreg, KLJUC_ZMOZNOSTI, {"ApplicationName": IME_APLIKACIJE,
                                          "ApplicationDescription": "Safeer OS Media: magnet povezave"})
        _zapisi(winreg, KLJUC_ZMOZNOSTI + r"\URLAssociations", {"magnet": PROGID})
        _zapisi(winreg, KLJUC_REGISTRIRANIH, {IME_APLIKACIJE: KLJUC_ZMOZNOSTI})
    except OSError as e:
        print(f"[SafeerOS] Protokola magnet ni bilo mogoče registrirati: {e}", flush=True)
        return False
    if je_privzeto(winreg):
        return True
    # Drug program ima prednost po uporabnikovi izbiri: izbere naj sam (Windows ne dovoli povoziti izbire).
    try:
        if odpri_nastavitve is not None:
            odpri_nastavitve("ms-settings:defaultapps?registeredAppUser=" + IME_APLIKACIJE.replace(" ", "%20"))
        elif sys.platform == "win32":
            os.startfile("ms-settings:defaultapps?registeredAppUser=" + IME_APLIKACIJE.replace(" ", "%20"))  # noqa: S606
    except OSError:
        pass
    return False
