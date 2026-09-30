"""Izbira predvajalnega pogona (mpv -> qt) mora biti nadzorovana in obrazlozena (pravilo: rezerva z zapisom)."""
import os
import sys

import pytest

_WINDOWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _WINDOWS not in sys.path:
    sys.path.insert(0, _WINDOWS)


@pytest.fixture
def izbira(monkeypatch):
    monkeypatch.delenv("SAFEER_POGON", raising=False)
    from safeer_windows import safeer_pogon_izbira as I
    I.IZBRANO.update(pogon=None, razlog=None, libmpv=None)
    return I


def test_okolje_qt_preglasi(izbira, monkeypatch):
    monkeypatch.setenv("SAFEER_POGON", "qt")
    assert izbira.izberi_pogon() == "qt"
    assert izbira.IZBRANO["razlog"] == "SAFEER_POGON=qt"


def test_rezerva_ko_libmpv_ni(izbira, monkeypatch):
    from safeer_windows import safeer_mpv_pogon as P
    monkeypatch.setattr(P, "libmpv_na_voljo", lambda: False)
    monkeypatch.setitem(P.STANJE, "napaka", "RuntimeError('MSVC runtime prestar')")
    assert izbira.izberi_pogon() == "qt"
    assert izbira.IZBRANO["pogon"] == "qt"
    assert "rezerva" in izbira.IZBRANO["razlog"] and "prestar" in izbira.IZBRANO["razlog"]


def test_mpv_ko_je_na_voljo(izbira, monkeypatch):
    from safeer_windows import safeer_mpv_pogon as P
    monkeypatch.setattr(P, "libmpv_na_voljo", lambda: True)
    monkeypatch.setitem(P.STANJE, "napaka", None)
    assert izbira.izberi_pogon() == "mpv"
    assert izbira.IZBRANO["razlog"] == "libmpv nalozen"


def test_mpv_pogon_brez_instance_pred_povezavo():
    """Lazno ustvarjanje: konstruktor ne sme ustvariti mpv instance (segfault ob povezi_video)."""
    from safeer_windows import safeer_mpv_pogon as P
    p = P.SafeerMpvPogon.__new__(P.SafeerMpvPogon)
    # __init__ brez uvoza knjiznice preverimo posredno: atributi po __init__ v modulu
    import inspect
    src = inspect.getsource(P.SafeerMpvPogon.__init__)
    assert "self._ustvari()" not in src
    assert "self._zapiranje = False" in src


def test_hwdec_kodeki_linux_ffmpeg6_brez_av1():
    from safeer_windows.safeer_mpv_pogon import hwdec_kodeki_za
    kodeki, razlog = hwdec_kodeki_za("6.1.1-3ubuntu5", "linux")
    assert "av1" not in kodeki.split(",") and "h264" in kodeki and razlog and "AV1" in razlog


def test_hwdec_kodeki_linux_ffmpeg7_privzeto():
    from safeer_windows.safeer_mpv_pogon import hwdec_kodeki_za, _HWDEC_KODEKI_PRIVZETO
    assert hwdec_kodeki_za("7.1", "linux") == (_HWDEC_KODEKI_PRIVZETO, None)


def test_hwdec_kodeki_windows_privzeto():
    from safeer_windows.safeer_mpv_pogon import hwdec_kodeki_za, _HWDEC_KODEKI_PRIVZETO
    assert hwdec_kodeki_za("6.1.1", "win32") == (_HWDEC_KODEKI_PRIVZETO, None)
    assert hwdec_kodeki_za(None, "linux") == (_HWDEC_KODEKI_PRIVZETO, None)
