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
    # Ime je nevtralno (ne uporabnisko ime iz poti profila; Safeer-linux eebfe57).
    assert m.koren() == [{"id": "dom:", "name": "Home", "type": "folder"}]
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


# ------------------------------------------------------------------ Safeer-linux eebfe57 (pregled 6, U9) na Windows
def test_skrivnosti_po_vsebini_in_imenu(dom):
    (dom / "Dokumenti" / "beleska.txt").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nx", encoding="utf-8")
    (dom / "Dokumenti" / "github_rsa").write_text("x", encoding="utf-8")
    (dom / "Dokumenti" / "Passwords.csv").write_text("url,user,pass", encoding="utf-8")
    (dom / "Dokumenti" / "github_rsa.pub").write_text("ssh-ed25519 AAAA", encoding="utf-8")
    m = ld.DeljeneMape([], dom=True)
    imena = {v["name"] for v in m.seznam("dom:Dokumenti")}
    assert {"beleska.txt", "github_rsa", "Passwords.csv"}.isdisjoint(imena)
    assert "github_rsa.pub" in imena                               # javni kljuc ni skrivnost
    for ime in ("beleska.txt", "github_rsa", "Passwords.csv"):
        assert m.razresi("dom:Dokumenti/" + ime) is None, ime


def test_izbrana_mapa_brez_skrivnosti(dom):
    (dom / "Dokumenti" / "Login Data").write_text("x", encoding="utf-8")
    m = ld.DeljeneMape([str(dom / "Dokumenti")])
    imena = {v["name"] for v in m.seznam("share:0:")}
    assert "Login Data" not in imena and "kljuc.pem" not in imena and "porocilo.txt" in imena
    assert m.razresi("share:0:Login Data") is None and m.razresi("share:0:kljuc.pem") is None


def test_ime_domace_mape_po_jeziku(dom):
    m = ld.DeljeneMape([], dom=True)
    m.jezik = "sl"
    assert m.koren()[0]["name"] == "Domača mapa"                  # ne uporabnisko ime (ime mape profila)
    m.jezik = "de"
    assert m.koren()[0]["name"] == "Persönlicher Ordner"


def test_urejanje_doma(dom, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(dom))
    monkeypatch.setenv("USERPROFILE", str(dom))
    d = ld.Datoteke([], tls_mapa=str(tmp_path / "tls"), dom=True)
    try:
        u = d.streznik.uredi
        assert u("dom:Dokumenti", {"op": "delete"})[0] == 403          # mapa uporabnika ostane
        assert u("dom:Dokumenti", {"op": "rename", "name": "X"})[0] == 403
        assert u("dom:Dokumenti/porocilo.txt", {"op": "rename", "name": ".bashrc"})[0] == 403
        assert u("dom:Dokumenti/porocilo.txt", {"op": "rename", "name": "kljuc.pem"})[0] == 403
        assert u("dom:Dokumenti/porocilo.txt", {"op": "move", "folder": "dom:"})[0] == 403
        assert u("dom:Dokumenti/porocilo.txt", {"op": "rename", "name": "porocilo-2.txt"})[0] == 200
    finally:
        d.ustavi()


class _Obravnava:
    def __init__(self):
        import io
        self.headers = {}
        self.wfile = io.BytesIO()
        self.close_connection = False

    def send_response(self, *_a):
        pass

    def send_header(self, *_a):
        pass

    def end_headers(self):
        pass


def test_prenos_se_prekine_ob_odvzemu(tmp_path, monkeypatch):
    """U9: odvzem dostopa konca tudi prenos, ki ze tece (preverba najvec enkrat na sekundo)."""
    monkeypatch.setattr(ld, "PREVERI_MED_POSILJANJEM_S", 0.0)
    monkeypatch.setattr(ld, "VELIKOST_KOSA", 1024)
    f = tmp_path / "film.bin"
    f.write_bytes(b"x" * 10240)
    klici = []
    o = _Obravnava()
    ld._poslji_datoteko(o, str(f), False, se_velja=lambda: klici.append(1) or len(klici) < 3)
    assert 0 < len(o.wfile.getvalue()) < 10240 and o.close_connection
    o2 = _Obravnava()
    ld._poslji_datoteko(o2, str(f), False)
    assert len(o2.wfile.getvalue()) == 10240


def test_preklic_vseh_oznak_naprave(tmp_path):
    d = ld.Datoteke([str(tmp_path)], tls_mapa=str(tmp_path / "tls"))
    try:
        s = d.streznik
        z1, z2, z3 = (s.zeton_za(n) for n in ("n-0123456789abcdef", "n-0123456789abcdef-os", "n-ffffffffffffffff"))
        assert d.preklici_napravo("n-0123456789abcdef") == 2
        assert not s.zeton_velja(z1) and not s.zeton_velja(z2) and s.zeton_velja(z3)
    finally:
        d.ustavi()

