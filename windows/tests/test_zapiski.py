import os
import tempfile

from safeer_windows import zapiski as zp


def _z():
    return zp.Zapiski(os.path.join(tempfile.mkdtemp(), "zapiski.json"))


def test_shrani_omembe_in_povratne():
    z = _z()
    a = z.shrani("", "Načrt", "Glej [@Poročilo](safeer:datoteka:C:/x/p.pdf) in [@RTV](https://rtvslo.si)")
    b = z.shrani("", "Drug", "Povezano z [@Načrt](safeer:zapisek:%s)" % a["id"])
    polno = z.dobi(a["id"])
    assert [o["vrsta"] for o in polno["omembe"]] == ["datoteka", "stran"]
    assert [p["id"] for p in polno["povratne"]] == [b["id"]]
    assert z.seznam("poročilo")[0]["id"] == a["id"]


def test_izrezek_s_spleta_v_zadnji_zapisek_z_virom():
    z = _z()
    a = z.shrani("", "Raziskava", "Uvod")
    z.dodaj_izrezek("https://primer.si/clanek", "Članek [1]", "Prva vrstica\nDruga")
    besedilo = z.dobi(a["id"])["besedilo"]
    assert "> Prva vrstica\n> Druga" in besedilo and "[@Članek (1)](https://primer.si/clanek)" in besedilo


def test_izrezek_brez_zapiska_ustvari_iz_spleta_in_zavrne_datoteke():
    z = _z()
    zapisek = z.dodaj_izrezek("https://primer.si", "Primer", "")
    assert zapisek["naslov"] == "Iz spleta"
    try:
        z.dodaj_izrezek("file:///C:/skrivno.txt", "x", "y")
        assert False
    except ValueError:
        pass


def test_pripni_in_izbrisi():
    z = _z()
    a = z.shrani("", "A", "")
    b = z.shrani("", "B", "", pripet=True)
    assert z.seznam()[0]["id"] == b["id"]
    assert z.izbrisi(a["id"]) and not z.izbrisi(a["id"])
