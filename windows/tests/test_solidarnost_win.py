"""Zakon solidarnosti na Windows: host.info v enotnem zapisu in pravila pomoci (os_backend_win)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from safeer_windows import os_backend_win as w  # noqa: E402

GB = 1024 ** 3


def setup_function(_f):
    w._POMAGA["zadnje"] = True


def test_preobremenjen_pomnilnik_prostor():
    assert w.odlocitev_pomoci(90, 8 * GB, 100 * GB, {}) == {"lahko": False, "razlog": "preobremenjen"}
    assert w.odlocitev_pomoci(10, 100 * 1024 * 1024, 100 * GB, {}) == {"lahko": False, "razlog": "malo_pomnilnika"}
    assert w.odlocitev_pomoci(10, 8 * GB, GB, {}) == {"lahko": False, "razlog": "ni_prostora"}
    assert w.odlocitev_pomoci(-1, -1, -1, {}) == {"lahko": True, "razlog": ""}   # neznano ne blokira


def test_baterija_z_mejama():
    ok = lambda r, polni=False: w.odlocitev_pomoci(10, 8 * GB, 100 * GB, {"raven": r, "polni": polni})["lahko"]  # noqa: E731
    assert ok(45) and ok(35)          # med 30 in 40 ostane prejsnje
    assert not ok(29)
    assert not ok(35)                 # pod 40 se se ne vrne
    assert ok(35, polni=True)         # na omrezju vedno
    assert ok(41)
    assert w.odlocitev_pomoci(10, 8 * GB, 100 * GB, {"raven": 80, "polni": False, "varcevanje": True})["razlog"] == "varcevanje"


def test_zmogljivost_zapis():
    p = w.zmogljivost()
    assert p["vrsta"] == "racunalnik"
    assert p["cpu"]["jedra"] >= 1
    assert "disk" in p and p["disk"]["prosto"] >= 0
    assert set(p["pomoc"]) == {"lahko", "razlog"}
