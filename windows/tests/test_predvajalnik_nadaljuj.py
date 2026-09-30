import os
import sys

_WINDOWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _WINDOWS not in sys.path:
    sys.path.insert(0, _WINDOWS)

from safeer_windows import predvajalnik_nadaljuj as R  # noqa: E402


def test_zabelezi_in_polozaj():
    d = {}
    assert R.zabelezi(d, "a.mp4", 5.0, 100.0) is False          # premalo predvajanega -> nic
    assert R.zabelezi(d, "a.mp4", 42.4, 100.0) and R.polozaj_za(d, "a.mp4") == 42.4
    assert R.zabelezi(d, "a.mp4", 95.0, 100.0) and R.polozaj_za(d, "a.mp4") == 0.0   # blizu konca -> izbrisano
    assert R.zabelezi(d, "b.mp4", 20.0, 0) is False


def test_omejitev_stevila(monkeypatch):
    monkeypatch.setattr(R, "MAX", 3)
    d = {}
    for i in range(5):
        R.zabelezi(d, f"{i}.mp4", 20.0, 100.0); d[f"{i}.mp4"]["cas"] = i
    assert sorted(d) == ["2.mp4", "3.mp4", "4.mp4"]


def test_shrani_nalozi(tmp_path):
    p = str(tmp_path / "nadaljuj.json")
    d = {}; R.zabelezi(d, "x.mkv", 33.3, 200.0)
    assert R.shrani(d, p) and R.polozaj_za(R.nalozi(p), "x.mkv") == 33.3
    assert R.nalozi(str(tmp_path / "ni.json")) == {}


def test_razclleni_cas():
    assert R.razclleni_cas("1:23:45") == 5025
    assert R.razclleni_cas("23:45") == 1425
    assert R.razclleni_cas("90") == 90
    assert R.razclleni_cas("12,5") == 12.5
    assert R.razclleni_cas("1h5m") == 3900
    assert R.razclleni_cas("2m30s") == 150
    assert R.razclleni_cas("abc") is None and R.razclleni_cas("") is None and R.razclleni_cas("1:2:3:4") is None


def test_sledilec(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path)); monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("SAFEER_NADALJUJ", raising=False)
    from safeer_windows import predvajalnik_nadaljuj as NJ

    class Pogon:
        nadaljevanje = None; ob_koncu_datoteke = None

    pg = Pogon(); s = NJ.Sledilec(); s.povezi(pg)
    assert pg.nadaljevanje("x") == 0.0
    p = {"stanje": "predvaja", "uri": "/a.mkv", "polozaj": 100.0, "trajanje": 3600.0}
    s.ob_podatkih(p)                       # prvi tik: zabelezi
    assert pg.nadaljevanje("/a.mkv") == 100.0
    s.ob_podatkih(dict(p, polozaj=101.0))  # < 5 s pozneje: se ne zapise
    assert pg.nadaljevanje("/a.mkv") == 100.0
    s.ob_podatkih(dict(p, polozaj=102.0, stanje="premor"))  # prehod v premor: takoj
    assert pg.nadaljevanje("/a.mkv") == 102.0
    assert NJ.nalozi()["/a.mkv"]["polozaj"] == 102.0  # tudi na disku
    pg.ob_koncu_datoteke("/a.mkv")           # do konca: pozabi
    assert pg.nadaljevanje("/a.mkv") == 0.0 and "/a.mkv" not in NJ.nalozi()
    izklop = NJ.Sledilec(vklop=False); pg2 = Pogon(); izklop.povezi(pg2)
    assert pg2.nadaljevanje is None


def test_sledilec_ustavitev(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path)); monkeypatch.setenv("APPDATA", str(tmp_path))
    from safeer_windows import predvajalnik_nadaljuj as NJ
    s = NJ.Sledilec(vklop=True)
    s.ob_podatkih({"stanje": "predvaja", "uri": "/b.mkv", "polozaj": 50.0, "trajanje": 600.0})
    s.ob_podatkih({"stanje": "predvaja", "uri": "/b.mkv", "polozaj": 53.0, "trajanje": 600.0})   # < 5 s: le v spominu
    s.ob_podatkih({"stanje": "ustavljeno", "uri": "/b.mkv", "polozaj": 0.0, "trajanje": 0.0})    # Stop -> zadnji znani
    assert NJ.nalozi()["/b.mkv"]["polozaj"] == 53.0
    s.ob_podatkih({"stanje": "ustavljeno", "uri": "/b.mkv", "polozaj": 0.0, "trajanje": 0.0})    # ponovno: nic
    assert NJ.nalozi()["/b.mkv"]["polozaj"] == 53.0
