"""Okolje procesa (os.environ) med tekom: samo zamenjava vrednosti, ki ze obstajajo - nikoli dodajanje ali brisanje.

Ze uvoz GTK zazene niti (gmain, pool-spawner, llvmpipe - izmerjeno 19. 10. 2026: 1 nit pred `from gi.repository import
Gtk`, 9 po njem), pozneje se GDBus, WebKit in nase. glibc setenv/unsetenv pri dodajanju ali brisanju tabelo environ
prestavi ali realocira, getenv v drugi niti pa jo bere brez zaklepa - to je lahko sesutje (polni tek preizkusov se je
19. 10. 2026 sesul ob Gio.TestDBus, ki dela isto). Zamenjava vrednosti obstojece spremenljivke pa tabele ne premakne:
glibc na mestu zamenja kazalec in stare vrednosti ne sprosti.

Zato: kar bo proces med tekom zacasno spreminjal, mora obstajati ze pred prvo nitjo (pred_nitmi(), klice ga safeer_os.py
pred `import gi`). Prazna vrednost je za Qt enaka nenastavljeni (qEnvironmentVariableIsEmpty), zato je mesto rezervirano
brez spremembe obnasanja; programom, ki jih zazenemo, prazne ne damo (core/zasebni_webkit.okolje_za_zunanje).
"""
from __future__ import annotations

import os
import sys
from typing import List, MutableMapping, Optional

#: Qt jih bere ob ustvarjanju QApplication. V procesu Safeer OS se to zgodi na zahtevo (okno aplikacije, delovna
#: povrsina brez varuha - core/os_lupina.pripravi), ko niti ze tecejo.
QT = ("QT_QPA_PLATFORMTHEME", "QT_QPA_PLATFORM", "QT_XCB_GL_INTEGRATION")

#: Proces jih prebere enkrat in jih programom, ki jih zazene, ne da naprej (varuh: vticnica obvestil, vticnica lupine,
#: obnova po sesutju; ponovni zagon Controla z oknom). Prej so se odstranile iz okolja v main() ali ob uvozu
#: safeer_control v procesu Safeer OS, ko so niti ze tekle.
PREVZETE = ("NOTIFY_SOCKET", "SAFEER_LUPINA_VTIC", "SAFEER_OBNOVA", "SAFEER_CONTROL_ODPRI", "SAFEER_SCIT_VTIC")

#: Oddaljeni inspektor WebKita (WEBKIT_INSPECTOR_SERVER, WEBKIT_INSPECTOR_HTTP_SERVER):
#: sme teci samo na lokalni zanki (127.0.0.1, ::1). Ce je v okolju nastavljen na omrezni vmesnik,
#: ga pred prvo nitjo odstranimo z opozorilom (S4 pregled 132).
ODDALJENI_INSPEKTOR = ("WEBKIT_INSPECTOR_SERVER", "WEBKIT_INSPECTOR_HTTP_SERVER")


def je_loopback_naslov(vrednost: str) -> bool:
    """Preveri, ali naslov oddaljenega inspektorja kaze izkljucno na lokalno zanko (loopback)."""
    if not vrednost or not isinstance(vrednost, str):
        return False
    v = vrednost.strip()
    host = ""
    if v.startswith("["):
        konec = v.find("]")
        if konec != -1:
            host = v[1:konec]
    elif ":" in v:
        deli = v.rsplit(":", 1)
        if deli[0].count(":") == 0:
            host = deli[0]
        else:
            host = v
    else:
        host = v

    host = host.strip().lower()
    if host in ("127.0.0.1", "localhost", "::1", "ip6-localhost", "ip6-loopback"):
        return True
    import ipaddress
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback
    except ValueError:
        return False


def preveri_oddaljeni_inspektor(okolje: Optional[MutableMapping[str, str]] = None) -> None:
    """Odstrani ne-loopback WEBKIT_INSPECTOR_SERVER / WEBKIT_INSPECTOR_HTTP_SERVER iz okolja z opozorilom."""
    env = os.environ if okolje is None else okolje
    for ime in ODDALJENI_INSPEKTOR:
        if ime in env:
            vrednost = env[ime]
            if not je_loopback_naslov(vrednost):
                sys.stderr.write(
                    f"[Safeer] Opozorilo: {ime}={vrednost!r} ni loopback (127.0.0.1 ali ::1) - "
                    "odstranjeno iz okolja pred zagonom.\n"
                )
                del env[ime]


_pripravljeno = False
_prevzeto: dict = {}


def pred_nitmi(okolje: Optional[MutableMapping[str, str]] = None) -> None:
    """Rezervira mesta za spremenljivke, ki jih bomo med tekom zamenjevali, in prevzame PREVZETE. Klicati samo, dokler
    tece ena nit."""
    global _pripravljeno
    preveri_oddaljeni_inspektor(okolje=okolje)
    env = os.environ if okolje is None else okolje
    for ime in QT:
        env.setdefault(ime, "")
    for ime in PREVZETE:
        if ime in env:
            _prevzeto[ime] = env.pop(ime)
    _pripravljeno = True


def prevzemi(ime: str) -> str:
    """Vrednost spremenljivke iz PREVZETE (prevzete pred nitmi); ce je takrat ni bilo, jo prebere in odstrani zdaj
    (proces brez pred_nitmi(), npr. locena lupina z eno nitjo)."""
    if ime in _prevzeto:
        return _prevzeto.pop(ime)
    return os.environ.pop(ime, "") if ime in os.environ else ""


def pripravljeno() -> bool:
    return _pripravljeno


def zamenjaj(ime: str, vrednost: str) -> Optional[str]:
    """Nastavi vrednost in vrne prejsnjo (None, ce spremenljivke ni bilo). Ce obstaja, je to zamenjava na mestu."""
    prej = os.environ.get(ime)
    os.environ[ime] = vrednost
    return prej


def povrni(ime: str, prej: Optional[str]) -> None:
    """Vrne vrednost, ki jo je vrnil zamenjaj(). Spremenljivko izbrise samo, ce je prej res ni bilo (proces brez
    pred_nitmi(), npr. locena lupina, kjer tece ena nit)."""
    if prej is None:
        os.environ.pop(ime, None)
    else:
        os.environ[ime] = prej


def python_ukaz(python: Optional[str] = None) -> List[str]:
    """Ukaz za nov proces Pythona (otrok, ponovni zagon): z -s, ce ta proces tece z -s. Zaganjalniki paketov zazenejo
    Python z -s (packaging/*-launcher): uporabnikov site-packages (pip install --user) ne sme zamenjati sistemskih
    paketov (cryptography, zeroconf, gi ...). Zastavica -s ni v okolju, zato jo otrok dobi samo, ce mu jo damo."""
    return [python or sys.executable or "/usr/bin/python3"] + (["-s"] if sys.flags.no_user_site else [])


def python_niz(skripta: str, python: Optional[str] = None) -> str:
    """Isto kot python_ukaz za vrstico Exec (samodejni zagon): '"python" -s "skripta"'."""
    return " ".join('"%s"' % d if not d.startswith("-") else d for d in python_ukaz(python) + [skripta])


def prazne_rezervacije(okolje: dict) -> dict:
    """Okolje za program, ki ga zazenemo: brez praznih rezervacij iz pred_nitmi() (enako kot pred njimi)."""
    for ime in QT:
        if okolje.get(ime) == "":
            del okolje[ime]
    return okolje
