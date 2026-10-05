"""Pytest: zacasne datoteke preizkusov gredo v eno mapo, ki po koncu teka izgine.

Preizkusi ustvarjajo zacasne mape (tempfile.mkdtemp na vec kot 80 mestih) in vseh ne pobrisejo. Kjer je /tmp na disku
in se sprazni sele ob ponovnem zagonu racunalnika, se je tako v stirih dneh nabralo 5700 map (najdeno 5. 10. 2026).
Vsak tek zato dobi svojo korensko mapo (tempfile.tempdir in TMPDIR, ki ga podedujejo tudi podprocesi); pytest jo ob
koncu pobrise. Ostanke prekinjenih tekov (njihov proces ne obstaja vec) pobrise naslednji tek.
"""
import os
import re
import shutil
import tempfile

_PREDPONA = "safeer-testi-"
_stanje = {}


def _pocisti_zapuscene(koren: str) -> None:
    """Mape prejsnjih tekov, katerih proces ne obstaja vec (prekinjen tek). Samo tam, kjer je /proc."""
    if not os.path.isdir("/proc"):
        return
    for ime in os.listdir(koren):
        m = re.match(r"^%s(\d+)-" % re.escape(_PREDPONA), ime)
        if not m or os.path.exists("/proc/" + m.group(1)):
            continue
        pot = os.path.join(koren, ime)
        try:
            if os.lstat(pot).st_uid == os.getuid() and os.path.isdir(pot) and not os.path.islink(pot):
                shutil.rmtree(pot, ignore_errors=True)
        except OSError:
            pass


def pytest_configure(config):
    koren = tempfile.gettempdir()
    try:
        _pocisti_zapuscene(koren)
    except OSError:
        pass
    mapa = tempfile.mkdtemp(prefix="%s%d-" % (_PREDPONA, os.getpid()), dir=koren)
    _stanje.update(mapa=mapa, tempdir=tempfile.tempdir, okolje=os.environ.get("TMPDIR"))
    tempfile.tempdir = mapa
    os.environ["TMPDIR"] = mapa


def pytest_unconfigure(config):
    mapa = _stanje.pop("mapa", None)
    if not mapa:
        return
    tempfile.tempdir = _stanje.pop("tempdir", None)
    staro = _stanje.pop("okolje", None)
    if staro is None:
        os.environ.pop("TMPDIR", None)
    else:
        os.environ["TMPDIR"] = staro
    shutil.rmtree(mapa, ignore_errors=True)
