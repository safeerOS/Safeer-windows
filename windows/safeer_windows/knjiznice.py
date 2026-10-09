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
import time

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
    "cryptography": "cryptography",
    "PIL": "Pillow",
    "dxcam": "dxcam",
    "soundcard": "soundcard",
}
POTREBNE = tuple(PAKETI)
#: Brez teh program tece, a brez dela zmoznosti: brez cryptography Safeer Link ne more narediti svoje identitete
#: (kljuc in potrdilo; rezerva je program openssl, ki ga Windows nima), brez Pillow racunalnik ne zajame zaslona za
#: oddaljeni zaslon, brez dxcam ga zajame poceni GDI (~21 namesto ~58 slik/s, izmerjeno 9. 10. 2026), brez soundcard je oddaljeni zaslon brez zvoka. Do 1.0.38 ju ni preveril ne program ne namestil zaganjalnik (izmerjeno 5. 10. 2026 z izracunom
#: odvisnosti: pip jih na cistem racunalniku ne prinese z nobenim drugim paketom).
#: Ce namestitev ne uspe (ni povezave), uporabnika ne ustavljamo ob vsakem zagonu: nov poskus najvec enkrat na
#: POSKUS_MEHKIH_S.
MEHKE = ("cryptography", "PIL", "dxcam", "soundcard")
POSKUS_MEHKIH_S = 24 * 3600


def pot_poskusa() -> str:
    """Kdaj je program zadnjic prosil zaganjalnik za mehke knjiznice (sekunde od 1970, besedilo)."""
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "SafeerOS", "knjiznice-poskus.txt")


def _poskus_dovoljen(pot: str, zdaj: float, manjka=()) -> bool:
    """Zapis je »cas [knjiznice,...]«. Nova mehka knjiznica (prisla s posodobitvijo) sme takoj na vrsto, tudi ce
    je druga pred kratkim odpovedala - prej je en sam cas zadrzal vse (izmerjeno 9. 10. 2026: soundcard v 1.0.51 se
    po posodobitvi ni namestil, ker je bil zapis star nekaj ur). Star zapis (samo cas) velja kot »brez knjiznic«."""
    try:
        with open(pot, encoding="ascii") as d:
            deli = d.read().split()
        zadnjic = float(deli[0]) if deli else 0.0
    except (OSError, ValueError):
        return True
    prej = set(deli[1].split(",")) if len(deli) > 1 else set()
    if set(manjka) - prej:
        return True
    return not (0 <= zdaj - zadnjic < POSKUS_MEHKIH_S)


def _zabelezi_poskus(pot: str, zdaj: float, manjka=()) -> None:
    try:
        os.makedirs(os.path.dirname(pot), exist_ok=True)
        with open(pot, "w", encoding="ascii") as d:
            d.write("%d %s" % (zdaj, ",".join(sorted(manjka))) if manjka else "%d" % zdaj)
    except OSError:
        pass


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


def preveri_ob_zagonu(okolje=None, izpis=None, izhod=sys.exit, moduli=POTREBNE, najdi=najdi,
                      mehke=MEHKE, poskus=None, ura=time.time) -> bool:
    """Ce zaganjalnik to naroci, preveri knjiznice: ob manjkajocih konca program s kodo KODA_MANJKAJO.

    Kadar manjkajo samo mehke knjiznice (MEHKE) in je program zaganjalnik zanje ze prosil pred manj kot
    POSKUS_MEHKIH_S (namestitev takrat ni uspela), tece naprej brez njih. `poskus` je pot zapisa o zadnji prosnji.

    Vrne, ali je preverjal."""
    okolje = os.environ if okolje is None else okolje
    if okolje.get(OKOLJE) != "1":
        return False
    pisi = izpis or (lambda vrstica: print(vrstica, flush=True))
    manjka = manjkajoce(moduli, najdi)
    if manjka:
        samo_mehke = all(m in mehke for m in manjka)
        poskus = pot_poskusa() if poskus is None else poskus
        if samo_mehke and not _poskus_dovoljen(poskus, ura(), manjka):
            pisi(OZNAKA_OK + " (brez: " + ", ".join(manjka) + "; namestitev ni uspela, nov poskus pozneje)")
            return True
        if samo_mehke:
            _zabelezi_poskus(poskus, ura(), manjka)
        pisi(OZNAKA_MANJKAJO + " " + ", ".join(manjka))
        izhod(KODA_MANJKAJO)
        return True
    pisi(OZNAKA_OK)
    return True
