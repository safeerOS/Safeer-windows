"""Ozji krog dobi uporabnikove mape - BREZ AppData, skritih map in skrivnosti
(DeljeneMape.dom, kot Safeer-linux a26daa2).

Lastnik 25. 10. 2026 10:49 (ena privolitev) in koordinator 25. 10.: na Windows uporabniski profil (Namizje, Dokumenti,
Slike, Prenosi ...) brez AppData, map z zacetno piko, datotek in map z atributom Skrito ali Sistem in znanih skrivnosti.
Zavrnjeno mora biti: pot z .., povezava (simbolna ali junction) iz vidne mape v AppData in skrita datoteka.
"""
import os
import sys
from pathlib import Path

import pytest

KOREN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KOREN))

from core import link_datoteke as ld  # noqa: E402


def _povezava(cilj: str, ime: str) -> bool:
    """Junction na Windows (brez skrbniskih pravic), simbolna povezava drugje. False, ce ni mogoce."""
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(cilj, ime)
        else:
            os.symlink(cilj, ime)
        return True
    except OSError:
        return False


@pytest.fixture
def dom(tmp_path, monkeypatch):
    d = tmp_path / "Uporabnik"
    (d / "Dokumenti" / "podmapa").mkdir(parents=True)
    (d / "Dokumenti" / "porocilo.txt").write_text("vsebina", encoding="utf-8")
    (d / "Dokumenti" / "podmapa" / "slika.jpg").write_bytes(b"\xff\xd8\xff")
    (d / "Dokumenti" / "kljuc.pem").write_text("-----", encoding="utf-8")
    (d / "Dokumenti" / "gesla.kdbx").write_bytes(b"x")
    (d / ".ssh").mkdir()
    (d / ".ssh" / "id_rsa").write_text("x", encoding="utf-8")
    (d / "id_ed25519").write_text("x", encoding="utf-8")
    (d / "AppData" / "Local" / "Brskalnik").mkdir(parents=True)
    (d / "AppData" / "Local" / "Brskalnik" / "Cookies").write_text("x", encoding="utf-8")
    (tmp_path / "zunaj.txt").write_text("zunaj", encoding="utf-8")
    monkeypatch.setattr(ld.DeljeneMape, "_domaca", staticmethod(lambda: os.path.realpath(str(d))))
    return d


def test_samo_ozji_krog_in_samo_dom(dom):
    assert ld.DeljeneMape([], dom=False).razresi("dom:Dokumenti/porocilo.txt") is None
    m = ld.DeljeneMape([], dom=True)
    assert m.koren() == [{"id": "dom:", "name": "Uporabnik", "type": "folder"}]
    i, pot = m.razresi("dom:Dokumenti/porocilo.txt")
    assert i == -2 and pot.endswith("porocilo.txt")
    assert m.oznaka_poti(pot) == "dom:Dokumenti/porocilo.txt"


def test_seznam_brez_skritih_appdata_in_skrivnosti(dom):
    m = ld.DeljeneMape([], dom=True)
    imena = {v["name"] for v in m.seznam("dom:")}
    assert imena == {"Dokumenti"}                               # brez .ssh, AppData, id_ed25519
    imena = {v["name"] for v in m.seznam("dom:Dokumenti")}
    assert imena == {"podmapa", "porocilo.txt"}                 # brez kljuc.pem, gesla.kdbx


@pytest.mark.parametrize("oznaka", [
    "dom:../zunaj.txt", "dom:Dokumenti/../../zunaj.txt", "dom:.ssh/id_rsa", "dom:id_ed25519",
    "dom:Dokumenti/kljuc.pem", "dom:Dokumenti/gesla.kdbx", "dom:AppData/Local/Brskalnik/Cookies",
    "dom://streznik/deljeno/x", "dom:C:/Windows/win.ini",
    # Pregled Grok W7: imena, ki jih Windows tiho preslika (8.3, koncna pika ali presledek, tok ADS).
    "dom:APPDAT~1/Local/Brskalnik/Cookies", "dom:AppData./Local/Brskalnik/Cookies", "dom:AppData /Local",
    "dom:Dokumenti/porocilo.txt:skrito", "dom:Dokumenti/porocilo.txt::$DATA", "dom:DOKUME~1/porocilo.txt",
])
def test_zavrnjeno(dom, oznaka):
    assert ld.DeljeneMape([], dom=True).razresi(oznaka) is None


def test_povezava_iz_vidne_mape_v_appdata(dom):
    vir = str(dom / "AppData" / "Local" / "Brskalnik")
    povezava = str(dom / "Dokumenti" / "bliznjica")
    if not _povezava(vir, povezava):
        pytest.skip("povezave ni mogoce ustvariti")
    m = ld.DeljeneMape([], dom=True)
    assert m.razresi("dom:Dokumenti/bliznjica/Cookies") is None
    assert m.razresi("dom:Dokumenti/bliznjica") is None
    assert "bliznjica" not in {v["name"] for v in m.seznam("dom:Dokumenti")}


def test_povezava_ven_iz_profila(dom, tmp_path):
    if not _povezava(str(tmp_path), str(dom / "Dokumenti" / "ven")):
        pytest.skip("povezave ni mogoce ustvariti")
    m = ld.DeljeneMape([], dom=True)
    assert m.razresi("dom:Dokumenti/ven/zunaj.txt") is None
    assert "ven" not in {v["name"] for v in m.seznam("dom:Dokumenti")}


@pytest.mark.skipif(os.name != "nt", reason="atribut Skrito ima samo Windows")
def test_skrita_datoteka_in_mapa(dom):
    import ctypes
    skrita = dom / "Dokumenti" / "skrita.txt"
    skrita.write_text("x", encoding="utf-8")
    mapa = dom / "Dokumenti" / "SkritaMapa"
    mapa.mkdir()
    (mapa / "v.txt").write_text("x", encoding="utf-8")
    for p in (skrita, mapa):
        assert ctypes.windll.kernel32.SetFileAttributesW(str(p), 0x2)
    m = ld.DeljeneMape([], dom=True)
    assert m.razresi("dom:Dokumenti/skrita.txt") is None
    assert m.razresi("dom:Dokumenti/SkritaMapa/v.txt") is None
    assert {"skrita.txt", "SkritaMapa"}.isdisjoint({v["name"] for v in m.seznam("dom:Dokumenti")})


def test_ozji_krog_na_windows_dobi_dom_ne_diska():
    vir = (KOREN / "windows" / "safeer_windows" / "control_backend.py").read_text(encoding="utf-8")
    assert "tls_mapa=self.navidezni_zaslon.tls_mapa, dom=polno)" in vir
    assert "ves_disk=polno)" not in vir


def test_dolgo_ime_s_tildo_ostane(dom):
    """Pravo ime s tildo, ki ni kratko ime 8.3, ostane dosegljivo."""
    (dom / "Dokumenti" / "kopija~1 porocila.txt").write_text("x", encoding="utf-8")
    m = ld.DeljeneMape([], dom=True)
    assert m.razresi("dom:Dokumenti/kopija~1 porocila.txt") is not None
    assert m.razresi("share:0:x.txt") is None


@pytest.mark.skipif(os.name != "nt", reason="kratka imena 8.3 ima samo Windows")
def test_pravo_kratko_ime_skrite_mape(dom):
    import ctypes
    mapa = dom / "Dokumenti" / "SkritaMapaDolga"
    mapa.mkdir()
    (mapa / "v.txt").write_text("x", encoding="utf-8")
    assert ctypes.windll.kernel32.SetFileAttributesW(str(mapa), 0x2)
    buf = ctypes.create_unicode_buffer(520)
    if not ctypes.windll.kernel32.GetShortPathNameW(str(mapa), buf, 520) or "~" not in buf.value:
        pytest.skip("nosilec nima kratkih imen 8.3")
    kratko = os.path.basename(buf.value)
    m = ld.DeljeneMape([], dom=True)
    assert m.razresi("dom:Dokumenti/" + kratko + "/v.txt") is None
    assert m.razresi("dom:Dokumenti/SkritaMapaDolga/v.txt") is None

