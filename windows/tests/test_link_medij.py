"""Daljinec (Link) -> Medijski center: control_backend preda medijske tipke/ukaz 'media' os_app-u (ob_mediju)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest

pytest.importorskip("PySide6")
from safeer_windows import control_backend as CB  # noqa: E402


class _Zaslon:
    def __init__(self):
        self.tipke = []

    def stanje_naprave(self):
        return {"actions": ["status", "key"], "keys": ["ok", "play_pause"]}

    def obdelaj_tipko(self, k):
        self.tipke.append(k); return True


class _Povezava:
    def __init__(self):
        self.poslano = []

    def poslji(self, m):
        self.poslano.append(m)


def _backend(ob_mediju):
    b = object.__new__(CB.SafeerControlBackend)
    b.navidezni_zaslon = _Zaslon(); b.povezava = _Povezava(); b.ob_mediju = ob_mediju; b.ob_magnetu = None
    b._dejanje_dovoljeno = lambda *_a: True
    b.magnet_na_voljo = lambda: False
    b._oddaj_dogodek = lambda *_a, **_k: None
    return b


def _ukaz(b, akcija, params=None):
    b._obdelaj_nadzorni_ukaz({"sender": "tel", "id": "1", "payload": {"action": akcija, "params": params or {}}})
    return b.povezava.poslano[-1]["payload"]


def test_medijske_tipke_gredo_v_predvajalnik():
    klici = []

    def medij(ukaz, params):
        klici.append(ukaz)
        if ukaz == "status":
            return {"ok": True, "data": {"active": True, "status": "playing", "title": "Film"}}
        return {"ok": True, "message": "Premor", "data": {"status": "paused"}}

    b = _backend(medij)
    r = _ukaz(b, "key", {"key": "play_pause"})
    assert r["ok"] and r["message"] == "Premor" and b.navidezni_zaslon.tipke == []
    r = _ukaz(b, "key", {"key": "ok"})            # ni medijska tipka -> navidezni zaslon
    assert b.navidezni_zaslon.tipke == ["ok"] and "ok" not in klici
    r = _ukaz(b, "media", {"cmd": "seek", "seconds": 30})
    assert r["ok"] and klici[-1] == "seek"
    r = _ukaz(b, "status")
    assert r["data"]["media"]["title"] == "Film" and "media" in r["data"]["actions"] and "next" in r["data"]["keys"]


def test_brez_predvajanja_pade_na_navidezni_zaslon(monkeypatch):
    # Brez prave medijske tipke sistema (ni Windows ali je ni bilo mogoce poslati) gre tipka navideznemu zaslonu.
    # Na Windows CI bi sicer sla prava tipka (_sistemska_medijska_tipka vrne True) - to preverja naslednji preizkus.
    monkeypatch.setattr(CB, "_sistemska_medijska_tipka", lambda k: False)
    b = _backend(lambda u, p: {"ok": False, "code": "ni_predvajanja"} if u != "status" else None)
    r = _ukaz(b, "key", {"key": "play_pause"})
    assert r["ok"] and b.navidezni_zaslon.tipke == ["play_pause"]
    r = _ukaz(b, "media", {"cmd": "play_pause"})
    assert not r["ok"] and r["code"] == "ni_predvajanja"


def test_brez_medijskega_centra():
    b = _backend(None)
    r = _ukaz(b, "media", {"cmd": "play_pause"})
    assert not r["ok"] and r["code"] == "ni_medija"
    r = _ukaz(b, "status")
    assert "media" not in r["data"]


def test_brez_predvajanja_prava_medijska_tipka_windows(monkeypatch):
    """Windows: ce Medijski center ne predvaja, gre prava medijska tipka sistemu (Splet, Spotify ...), ne navideznemu zaslonu."""
    poslano = []
    monkeypatch.setattr(CB, "_sistemska_medijska_tipka", lambda k: poslano.append(k) or True)
    b = _backend(lambda u, p: {"ok": False, "code": "ni_predvajanja"} if u != "status" else None)
    b._gleda_navidezni = lambda *_a: False
    r = _ukaz(b, "key", {"key": "play_pause"})
    assert r["ok"] and poslano == ["play_pause"] and b.navidezni_zaslon.tipke == []
