"""Preizkusi klicatelja screen.start -> zacni_sejo (zmoznosti televizorja) brez Windows."""

import importlib.util
import os

import pytest

_POT = os.path.join(os.path.dirname(__file__), os.pardir, "safeer_windows", "zmoznosti_zaslona.py")


def _modul():
    # Modul je ciste stdlib, nalozimo ga neposredno iz datoteke
    spec = importlib.util.spec_from_file_location("zmoznosti_zaslona_preizkus", _POT)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


class LazniNavidezni:
    """Lazni navidezni_zaslon: zapise vsak klic zacni_sejo."""

    def __init__(self):
        self.klici = []

    def zacni_sejo(self, *args, **kwargs):
        self.klici.append((args, kwargs))
        return {"port": 1}


def _klic(parametri, kakovost="najvisja"):
    z = _modul()
    lazni = LazniNavidezni()
    izid = z.zacni_sejo_s_parametri(lazni, "naprava-1", kakovost, parametri)
    assert izid == {"port": 1}
    assert len(lazni.klici) == 1
    return lazni.klici[0]


def test_brez_kljucev_klic_kot_prej():
    args, kwargs = _klic({"quality": "srednja"}, "srednja")
    assert args == ("naprava-1",)
    assert kwargs == {"kakovost": "srednja"}


def test_veljavni_kljuci_se_podata():
    args, kwargs = _klic({"codecs": ["hevc", "h264"], "maxsize": {"hevc": "3840x2160"}})
    assert args == ("naprava-1",)
    assert kwargs == {"kakovost": "najvisja", "kodeki": ["hevc", "h264"], "najvecja": {"hevc": "3840x2160"}}


def test_meja_8_nizov_po_16_znakov_velja():
    kodeki = ["k" * 16] * 8
    _, kwargs = _klic({"codecs": kodeki})
    assert kwargs == {"kakovost": "najvisja", "kodeki": kodeki}


@pytest.mark.parametrize("kodeki", [
    ["h264"] * 9,            # 9 nizov
    ["hevc", 264],           # int namesto niza
    ["k" * 17],              # niz daljsi od 16 znakov
    "hevc,h264",             # niz namesto seznama
    ("hevc", "h264"),        # terka ni seznam (enako kot Linux)
    {"hevc": 1},             # slovar namesto seznama
])
def test_neveljavni_kodeki_se_prezrejo(kodeki):
    _, kwargs = _klic({"codecs": kodeki})
    assert kwargs == {"kakovost": "najvisja"}


@pytest.mark.parametrize("najvecja", [["3840x2160"], "3840x2160", 2160, None])
def test_neveljaven_maxsize_se_prezre(najvecja):
    _, kwargs = _klic({"codecs": ["h264"], "maxsize": najvecja})
    assert kwargs == {"kakovost": "najvisja", "kodeki": ["h264"]}


def test_parametri_niso_slovar():
    _, kwargs = _klic(None)
    assert kwargs == {"kakovost": "najvisja"}


def test_kopiji_ne_delita_z_vhodom():
    vhod = {"codecs": ["hevc"], "maxsize": {"hevc": "3840x2160"}}
    _, kwargs = _klic(vhod)
    vhod["codecs"].append("h264")
    vhod["maxsize"]["h264"] = "1920x1080"
    assert kwargs["kodeki"] == ["hevc"]
    assert kwargs["najvecja"] == {"hevc": "3840x2160"}


def test_meje_enake_kot_linux():
    z = _modul()
    assert (z.KODEKI_NAJVEC, z.KODEK_NAJVEC_ZNAKOV) == (8, 16)
