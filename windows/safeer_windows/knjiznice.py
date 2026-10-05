"""Knjiznice Pythona, brez katerih Safeer OS ne tece: program jih preveri sam.

Prej jih je zaganjalnik (SafeerOS.exe) pred vsakim zagonom preveril s posebnim zagonom Pythona - okoli pol sekunde
cakanja ob vsakem odpiranju programa. Zdaj zaganjalnik program zazene takoj in mu z okoljem naroci preverbo
(OKOLJE=1): ce kaj manjka, se program konca s kodo KODA_MANJKAJO, zaganjalnik knjiznice namesti in program zazene
znova. Ko je vse na mestu, program izpise OZNAKA_OK (zaganjalnik jo prebere v dnevniku safeer_os.log).

Brez narocila (starejsi zaganjalnik, ki preverja sam; zagon iz registra za povezavo magnet; razvoj) se ne preverja nic.
Dogovor je zapisan tudi v windows/launcher_go/main.go; ujemanje preverja windows/tests/test_knjiznice.py.
"""
import importlib.machinery
import importlib.util
import os
import sys

OKOLJE = "SAFEER_OS_PREVERI_KNJIZNICE"
KODA_MANJKAJO = 86
OZNAKA_OK = "[SafeerOS] knjiznice OK"
OZNAKA_MANJKAJO = "[SafeerOS] manjkajo knjiznice:"

# Modul -> paket, ki ga namesti zaganjalnik (pip). Isti moduli kot v prejsnji preverbi zaganjalnika.
PAKETI = {
    "PySide6": "PySide6",
    "qrcode": "qrcode",
    "mutagen": "mutagen",
    "av": "av",
    "zeroconf": "zeroconf",
    "mpv": "python-mpv",
    "winrt.windows.media.playback": "winrt-Windows.Media.Playback",
}
POTREBNE = tuple(PAKETI)


def najdi(modul: str):
    """Kot importlib.util.find_spec, le da za podmodul (a.b.c) starsev NE uvozi.

    find_spec("winrt.windows.media.playback") uvozi winrt.windows.media: na toplem disku desetinka sekunde, na hladnem
    sekunde (predvajalnik zato winrt uvaza v niti v ozadju). Tu zadosca vedeti, ali je paket namescen: v mapah vrhnjega
    paketa mora obstajati paket a/b/c/__init__.py ali modul a/b/c.py (oziroma razsiritveni modul, npr. a/b/c.pyd)."""
    vrh, _, ostalo = modul.partition(".")
    spec = importlib.util.find_spec(vrh)
    if spec is None or not ostalo:
        return spec
    for mapa in spec.submodule_search_locations or ():
        cilj = os.path.join(mapa, *ostalo.split("."))
        if os.path.isfile(os.path.join(cilj, "__init__.py")):
            return spec
        if any(os.path.isfile(cilj + pripona) for pripona in importlib.machinery.all_suffixes()):
            return spec
    return None


def manjkajoce(moduli=POTREBNE, najdi=najdi) -> list:
    """Moduli, ki niso namesceni. Nicesar ne uvozi (mpv brez libmpv ob uvozu pade, a je namescen)."""
    manjka = []
    for modul in moduli:
        try:
            if najdi(modul) is None:
                manjka.append(modul)
        except (ImportError, ValueError):  # manjka ze stars paketa (winrt) ali je zapis modula pokvarjen
            manjka.append(modul)
    return manjka


def preveri_ob_zagonu(okolje=None, izpis=None, izhod=sys.exit, moduli=POTREBNE, najdi=najdi) -> bool:
    """Ce zaganjalnik to naroci, preveri knjiznice: ob manjkajocih konca program s kodo KODA_MANJKAJO.

    Vrne, ali je preverjal."""
    okolje = os.environ if okolje is None else okolje
    if okolje.get(OKOLJE) != "1":
        return False
    pisi = izpis or (lambda vrstica: print(vrstica, flush=True))
    manjka = manjkajoce(moduli, najdi)
    if manjka:
        pisi(OZNAKA_MANJKAJO + " " + ", ".join(manjka))
        izhod(KODA_MANJKAJO)
        return True
    pisi(OZNAKA_OK)
    return True
