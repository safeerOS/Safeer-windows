"""Nastavitve predvajalnika: jasno oznacen vnos Stremio/Kodi dodatkov, brez prilozenih katalogov."""
import os
import sys

_WINDOWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _WINDOWS not in sys.path:
    sys.path.insert(0, _WINDOWS)

from safeer_windows import predvajalnik_nastavitve as N  # noqa: E402


def test_privzeto_brez_dodatkov():
    n = N.nalozi("/ne/obstaja/predvajalnik.json")
    assert n["stremio_dodatki"] == [] and n["kodi_dodatki"] == []   # nic vgrajenega


def test_stremio_naslov_in_pretvorba_sheme():
    assert N.normaliziraj_stremio("stremio://primer.si/dodatek/manifest.json")[0] == "https://primer.si/dodatek/manifest.json"
    assert N.normaliziraj_stremio("https://primer.si/dodatek/manifest.json#x")[0] == "https://primer.si/dodatek/manifest.json"
    assert N.normaliziraj_stremio("https://primer.si/dodatek/")[0] is None
    assert N.normaliziraj_stremio("ftp://primer.si/manifest.json")[0] is None
    assert N.normaliziraj_stremio("")[0] is None


def test_kodi_naslov():
    assert N.normaliziraj_kodi("https://primer.si/repository.x-1.0.0.zip")[0] == "https://primer.si/repository.x-1.0.0.zip"
    assert N.normaliziraj_kodi("primer.si/x.zip")[0] is None


def test_dodaj_odstrani_shrani(tmp_path):
    p = str(tmp_path / "predvajalnik.json")
    n = N.nalozi(p)
    ok, s = N.dodaj(n, "stremio", "stremio://primer.si/a/manifest.json", "Moj")
    assert ok and s.startswith("https://")
    assert N.dodaj(n, "stremio", "https://primer.si/a/manifest.json")[1] == "Ta naslov je že dodan."
    assert N.dodaj(n, "kodi", "https://primer.si/repo.zip")[0]
    assert N.shrani(n, p)
    m = N.nalozi(p)
    assert [x["naslov"] for x in m["stremio_dodatki"]] == ["https://primer.si/a/manifest.json"]
    assert m["stremio_dodatki"][0]["ime"] == "Moj"
    assert N.odstrani(m, "kodi", "https://primer.si/repo.zip") and m["kodi_dodatki"] == []


def test_besedila_jasno_oznacena():
    assert "Stremio" in N.BESEDILA["stremio_naslov"] and "manifest.json" in N.BESEDILA["stremio_naslov"]
    assert "Kodi" in N.BESEDILA["kodi_naslov"] and ".zip" in N.BESEDILA["kodi_naslov"]
