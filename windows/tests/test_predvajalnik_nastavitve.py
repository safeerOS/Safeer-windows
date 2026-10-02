"""Nastavitve predvajalnika: jasno oznacen vnos Stremio dodatkov (dodatkov Kodi ne ponujamo: Safeer jih ne more poganjati), brez prilozenih katalogov."""
import os
import sys

_WINDOWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _WINDOWS not in sys.path:
    sys.path.insert(0, _WINDOWS)

from safeer_windows import predvajalnik_nastavitve as N  # noqa: E402


def test_privzeto_brez_dodatkov():
    n = N.nalozi("/ne/obstaja/predvajalnik.json")
    assert n["stremio_dodatki"] == [] and "kodi_dodatki" not in n   # nic vgrajenega, Kodi ni vec ponujen


def test_stremio_naslov_in_pretvorba_sheme():
    assert N.normaliziraj_stremio("stremio://primer.si/dodatek/manifest.json")[0] == "https://primer.si/dodatek/manifest.json"
    assert N.normaliziraj_stremio("https://primer.si/dodatek/manifest.json#x")[0] == "https://primer.si/dodatek/manifest.json"
    assert N.normaliziraj_stremio("https://primer.si/dodatek/")[0] is None
    assert N.normaliziraj_stremio("ftp://primer.si/manifest.json")[0] is None
    assert N.normaliziraj_stremio("")[0] is None


def test_kodi_dodatkov_ne_ponujamo(tmp_path):
    """Cesar Safeer ne more poganjati, ne ponuja: vrsta 'kodi' je zavrnjena, stari vnosi se ob shranjevanju opustijo."""
    import json
    assert not hasattr(N, "normaliziraj_kodi")
    assert not any("kodi" in k.lower() or "Kodi" in v for k, v in N.BESEDILA.items())
    p = tmp_path / "predvajalnik.json"
    p.write_text(json.dumps({"stremio_dodatki": [{"naslov": "https://primer.si/a/manifest.json", "ime": ""}],
                             "kodi_dodatki": [{"naslov": "https://primer.si/repo.zip", "ime": ""}]}), encoding="utf-8")
    n = N.nalozi(str(p))
    assert "kodi_dodatki" not in n and len(n["stremio_dodatki"]) == 1
    assert N.dodaj(n, "kodi", "https://primer.si/repo.zip") == (False, "Neznana vrsta dodatka.")
    assert N.shrani(n, str(p))
    assert "kodi" not in p.read_text(encoding="utf-8")


def test_dodaj_odstrani_shrani(tmp_path):
    p = str(tmp_path / "predvajalnik.json")
    n = N.nalozi(p)
    ok, s = N.dodaj(n, "stremio", "stremio://primer.si/a/manifest.json", "Moj")
    assert ok and s.startswith("https://")
    assert N.dodaj(n, "stremio", "https://primer.si/a/manifest.json")[1] == "Ta naslov je že dodan."
    assert N.shrani(n, p)
    m = N.nalozi(p)
    assert [x["naslov"] for x in m["stremio_dodatki"]] == ["https://primer.si/a/manifest.json"]
    assert m["stremio_dodatki"][0]["ime"] == "Moj"
    assert N.odstrani(m, "stremio", "https://primer.si/a/manifest.json") and m["stremio_dodatki"] == []


def test_besedila_jasno_oznacena():
    assert "Stremio" in N.BESEDILA["stremio_naslov"] and "manifest.json" in N.BESEDILA["stremio_naslov"]
