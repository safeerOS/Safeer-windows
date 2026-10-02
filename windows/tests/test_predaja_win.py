"""»Nadaljuj z druge naprave« z Windows racunalnika: play.state / play.stop (control_backend + core/link_predvajanje)."""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import pytest

pytest.importorskip("PySide6")
from core import link_datoteke, link_predvajanje  # noqa: E402
from safeer_windows import control_backend as CB  # noqa: E402
from safeer_windows import predvajalnik_nadaljuj  # noqa: E402


class _Zaslon:
    def __init__(self, tls_mapa):
        self.tls_mapa = tls_mapa

    def stanje_naprave(self):
        return {"actions": ["status", "key"], "keys": ["ok"]}


class _Povezava:
    def __init__(self):
        self.poslano = []

    def poslji(self, m):
        self.poslano.append(m)


@pytest.fixture
def okolje(tmp_path, monkeypatch):
    deljena = tmp_path / "Filmi"
    deljena.mkdir()
    film = deljena / "film.mkv"
    film.write_bytes(b"x" * 100)
    zunaj = tmp_path / "zasebno.mkv"
    zunaj.write_bytes(b"y")
    monkeypatch.setattr(predvajalnik_nadaljuj, "pot", lambda: str(tmp_path / "nadaljuj.json"))
    stanje = {"stanje": "predvaja", "uri": str(film), "naslov": "Film", "vrsta": "film", "pozicija": 61.5, "trajanje": 2400.0}
    klici = []

    def medij(ukaz, params):
        klici.append(ukaz)
        if ukaz == "state":
            return {"ok": True, "data": dict(stanje)}
        if ukaz == "pause":
            return {"ok": True, "data": {"status": "playing" if stanje["stanje"] == "predvaja" else "paused"}}
        if ukaz == "status":
            return {"ok": True, "data": {"active": True, "status": "playing", "title": "Film"}}
        return None

    b = object.__new__(CB.SafeerControlBackend)
    b.navidezni_zaslon = _Zaslon(str(tmp_path / "tls")); b.povezava = _Povezava(); b.ob_mediju = medij; b.ob_magnetu = None
    b.magnet_na_voljo = lambda: False
    b._oddaj_dogodek = lambda *_a, **_k: None
    b.nastavitve = {"dovoljenja_naprav": {"tel": "izbrano", "tv": "zaslon"}, "deljene_mape": [str(deljena)]}
    b.naprave = [{"id": "tel", "ime": "Telefon"}, {"id": "tv", "ime": "TV"}]
    b.deljene_mape = lambda: [str(deljena)]
    b.hub_url = lambda: ""
    b._sprotno = lambda: type("S", (), {"ffmpeg": lambda self: ""})()
    b._datoteke = {}
    try:
        yield b, stanje, klici, film, zunaj
    finally:
        for d in list(b._datoteke.values()):
            d.ustavi()


def _ukaz(b, akcija, posiljatelj="tel", params=None):
    b._obdelaj_nadzorni_ukaz({"sender": posiljatelj, "id": "1", "payload": {"action": akcija, "params": params or {}}})
    return b.povezava.poslano[-1]["payload"]


def test_play_state_datoteka_iz_deljene_mape(okolje):
    b, stanje, klici, film, _ = okolje
    r = _ukaz(b, "play.state")
    assert r["ok"] and r["data"]["playing"] and r["data"]["is_playing"]
    d = r["data"]
    assert (d["position_ms"], d["duration_ms"]) == (61500, 2400000)
    assert d["item"]["id"] == "share:0:film.mkv" and d["item"]["video"] and d["item"]["naslov"] == "Film"
    assert d["item"]["zvok"] == d["server"]["base_url"] + "/d/share%3A0%3Afilm.mkv"
    assert d["server"]["fp"] and d["server"]["token"] and d["item"]["povezava"] == ""
    # Streznik za profil "izbrano" je tisti brez celega diska in zeton velja.
    assert b._datoteke[False].streznik.zeton_velja(d["server"]["token"])
    r = _ukaz(b, "status")
    assert "play.state" in r["data"]["actions"]


def test_play_state_zunaj_deljenih_in_brez_pravic(okolje):
    b, stanje, klici, _, zunaj = okolje
    stanje["uri"] = str(zunaj)
    r = _ukaz(b, "play.state")
    assert r["ok"] and r["data"] == {"shared": True, "playing": False, "reason": "ni_deljeno"}
    # Naprava samo z zaslonom ne izve, kaj racunalnik predvaja.
    r = _ukaz(b, "play.state", posiljatelj="tv")
    assert not r["ok"] and r["code"] == "dovoljenje_potrebno"


def test_play_stop_je_premor(okolje):
    b, stanje, klici, _, _ = okolje
    r = _ukaz(b, "play.stop")
    assert r["ok"] and r["data"] == {"stopped": True} and klici[-1] == "pause"
    stanje["stanje"] = "premor"
    r = _ukaz(b, "play.stop")
    assert r["data"] == {"stopped": False}


def test_nic_ne_igra_pove_zadnji_video(okolje, tmp_path):
    b, stanje, klici, film, zunaj = okolje
    stanje.clear(); stanje["stanje"] = "ustavljeno"
    predvajalnik_nadaljuj.shrani({str(zunaj): {"polozaj": 500, "trajanje": 1000, "cas": 200},
                                  str(film): {"polozaj": 300.5, "trajanje": 2400, "cas": 100},
                                  "https://primer.si/x.mp4": {"polozaj": 5, "trajanje": 10, "cas": 300}})
    r = _ukaz(b, "play.state")
    d = r["data"]
    # zunaj deljenih map je najnovejsi, a ga ni mogoce deliti -> zadnji ostane "nic"; film v deljeni mapi ni zadnji.
    assert d["playing"] is False and "last" not in d
    predvajalnik_nadaljuj.shrani({str(film): {"polozaj": 300.5, "trajanje": 2400, "cas": 100}})
    d = _ukaz(b, "play.state")["data"]
    assert d["last"] and d["position_ms"] == 300500 and d["item"]["id"] == "share:0:film.mkv" and d["when"] == 100000


def test_brez_medijskega_centra(okolje):
    b, *_ = okolje
    b.ob_mediju = None
    d = _ukaz(b, "play.state")["data"]
    assert d == {"shared": True, "playing": False}
    assert _ukaz(b, "play.stop")["data"] == {"stopped": False}


def test_play_offer_ponudba_caka(okolje):
    b, stanje, klici, film, _ = okolje
    dogodki = []
    b._oddaj_dogodek = lambda v, d: dogodki.append((v, d))
    r = _ukaz(b, "play.offer", params={"item": {"id": "media:video:5", "naslov": "Film", "zvok": "https://192.168.0.87:4433/d/media%3Avideo%3A5", "video": True},
                                       "position_ms": 754000, "duration_ms": 5400000,
                                       "server": {"base_url": "https://192.168.0.87:4433", "fp": "ab", "token": "t"}, "from": "Tablica"})
    assert r["ok"] and r["data"] == {"queued": True}
    ponudbe = [d for v, d in dogodki if v == "predajaPonudba"]
    assert ponudbe and ponudbe[-1]["od_ime"] == "Telefon"  # ime iz seznama naprav
    assert ponudbe[-1]["opis"] == "Film (12:34)"
    p = b.vzemi_ponudbo()
    assert p["od"] == "tel" and p["server"]["token"] == "t" and b.vzemi_ponudbo() is None
    # izklopljeno deljenje -> ponudba odpade; naprava samo z zaslonom je ne sme poslati
    b.nastavitve["predvajanje_za_naprave"] = False
    assert _ukaz(b, "play.offer", params={"item": {"id": "x", "zvok": "https://primer.si/a"}})["data"]["reason"] == "izklopljeno"
    b.nastavitve["predvajanje_za_naprave"] = True
    assert _ukaz(b, "play.offer", posiljatelj="tv", params={"item": {"id": "x", "zvok": "https://primer.si/a"}})["code"] == "dovoljenje_potrebno"
