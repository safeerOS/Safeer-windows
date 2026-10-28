"""Spletni klepeti v Sporocilih na Windows (lastnik 27. in 28. 10. 2026: »Windows naj ima Sporocila kot Linux«).

Logika windows/safeer_windows/kanali_sporocil_win.KanaliSporocilWin brez Qt: pogledi so ponaredek. Preverja: nic ni
vklopljeno privzeto, dodaj/odstrani, lasten profil na kanal, neprebrano iz naslova strani, pravokotnik v merilu
strani, skrij/pokazi, namizni programi niso ponujeni, vklop/izklop sprosti pogled.
"""
import sys
import unittest
from pathlib import Path

KOREN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KOREN))
sys.path.insert(0, str(KOREN / "windows"))

from safeer_windows import kanali_sporocil_win as K

from core import spletni_klepeti


class Shramba(dict):
    def set(self, k, v):
        self[k] = v


class Pogledi:
    def __init__(self):
        self.ustvarjeni, self.uniceni, self.prikazi, self.skriti, self.ukazi, self.izbrisani = [], [], [], [], [], []
        self.naslovi, self.nalozeno, self.url = {}, {}, {}
        self.zakasnjeni = []

    def ustvari(self, kid, url, ob_naslovu, ob_nalozeno):
        p = {"kid": kid, "profil": K.ime_profila(kid)}
        self.ustvarjeni.append(p)
        self.naslovi[kid], self.nalozeno[kid], self.url[kid] = ob_naslovu, ob_nalozeno, url
        return p

    def pokazi(self, pogled, gostitelj, p):
        self.prikazi.append((pogled["kid"], p))

    def skrij(self, pogled):
        self.skriti.append(pogled["kid"])

    def unici(self, pogled):
        self.uniceni.append(pogled["kid"])

    def izbrisi_podatke(self, pogled, ob_koncu):
        self.izbrisani.append(pogled["kid"])

    def ukaz(self, pogled, ukaz, url):
        self.ukazi.append((pogled["kid"], ukaz))
        return True

    def merilo(self, gostitelj):
        return 1.5

    def naslov(self, pogled):
        return self.url.get(pogled["kid"], "")

    def zakasni(self, ms, fn):
        self.zakasnjeni.append(fn)


class KanaliWin(unittest.TestCase):
    def setUp(self):
        self.s, self.p, self.dogodki = Shramba(), Pogledi(), []
        self.k = K.KanaliSporocilWin(self.p, self.s, lambda: "sl", lambda v, d: self.dogodki.append(v))

    def test_privzeto_nic(self):
        self.assertEqual(self.k.seznam(), [])
        self.k.zazeni_vse()
        self.assertEqual(self.p.ustvarjeni, [])

    def test_katalog_brez_namiznih_programov(self):
        kat = self.k.katalog()
        self.assertTrue(any(v["id"] == "whatsapp" for v in kat))
        self.assertFalse(any(spletni_klepeti.je_program(v) for v in kat))
        self.assertGreaterEqual(len(kat), 10)       # izmerjeni katalog (kot carovnik na Linuxu), brez programov

    def test_dodaj_lasten_profil_in_odstrani(self):
        s = self.k.dodaj("whatsapp")
        s = self.k.dodaj("telegram")
        self.assertEqual([x["katalog"] for x in s], ["whatsapp", "telegram"])
        profili = {p["profil"] for p in self.p.ustvarjeni}
        self.assertEqual(len(profili), 2)                    # vsak kanal svoj profil (piskotki, prijava)
        self.assertTrue(all(p.startswith("SafeerKanal-") for p in profili))
        wid = s[0]["id"]
        self.k.odstrani(wid, True)
        self.assertIn(wid, self.p.izbrisani)
        self.assertIn(wid, self.p.uniceni)
        self.assertEqual([x["katalog"] for x in self.k.seznam()], ["telegram"])
        self.assertIn("kanaliSporocil", self.dogodki)

    def test_namizni_program_zavrnjen(self):
        program = next((v for v in spletni_klepeti.KATALOG if spletni_klepeti.je_program(v)), None)
        if program is None:
            self.skipTest("katalog nima namiznih programov")
        with self.assertRaises(ValueError):
            self.k.dodaj(program["id"])
        with self.assertRaises(ValueError):
            self.k.dodaj("", "https://chat.example.org", "x", "C:/program.exe")

    def test_neprebrano_iz_naslova(self):
        kid = self.k.dodaj("whatsapp")[0]["id"]
        self.p.naslovi[kid]("(3) WhatsApp")
        self.assertEqual(self.k.neprebrano_skupaj(), 3)
        self.assertEqual(self.k.seznam()[0]["neprebrano"], 3)
        self.p.naslovi[kid]("WhatsApp")
        self.assertEqual(self.k.neprebrano_skupaj(), 0)

    def test_pokazi_v_merilu_in_skrij(self):
        kid = self.k.dodaj("whatsapp")[0]["id"]
        gost = object()
        r = self.k.pokazi(gost, kid, {"x": 100, "y": 50, "w": 600, "h": 400})
        self.assertEqual(r, {"ok": True, "vgrajeno": True})
        self.assertEqual(self.p.prikazi[-1], (kid, (150, 75, 900, 600)))
        self.assertTrue(self.k.polozaj(gost, {"x": 0, "y": 0, "w": 10, "h": 10}))
        self.assertTrue(self.k.skrij(gost))
        self.assertIn(kid, self.p.skriti)
        self.assertFalse(self.k.polozaj(gost, {"x": 0, "y": 0, "w": 10, "h": 10}))   # skrit kanal se ne premika

    def test_napacen_pravokotnik(self):
        kid = self.k.dodaj("whatsapp")[0]["id"]
        self.assertEqual(self.k.pokazi(object(), kid, {"x": "nan", "y": 0, "w": 1, "h": 1})["ok"], False)
        self.assertIsNone(K.pravokotnik(None, 1))
        self.assertIsNone(K.pravokotnik({"x": 1e9}, 1))

    def test_izklop_sprosti_vklop_nalozi(self):
        kid = self.k.dodaj("whatsapp")[0]["id"]
        self.k.vklopi(kid, False)
        self.assertIn(kid, self.p.uniceni)
        self.assertEqual(self.k.pokazi(object(), kid, {"x": 0, "y": 0, "w": 1, "h": 1})["razlog"], "kanal")
        n = len(self.p.ustvarjeni)
        self.k.vklopi(kid, True)
        self.assertEqual(len(self.p.ustvarjeni), n + 1)

    def test_zagon_po_dva(self):
        for kat in ("whatsapp", "telegram", "discord"):
            self.k.dodaj(kat)
        k2 = K.KanaliSporocilWin(Pogledi(), self.s, lambda: "sl", lambda v, d: None)
        k2.zazeni_vse()
        self.assertEqual(len(k2.pogledi.ustvarjeni), K.HKRATI_OB_ZAGONU)
        prvi = k2.pogledi.ustvarjeni[0]["kid"]
        k2.pogledi.nalozeno[prvi](True)
        self.assertEqual(len(k2.pogledi.ustvarjeni), 3)

    def test_ime_profila_varno(self):
        self.assertEqual(K.ime_profila("../a b"), "SafeerKanal-___a_b")
        self.assertEqual(K.ime_profila(""), "SafeerKanal-kanal")

    def test_ukaz(self):
        kid = self.k.dodaj("whatsapp")[0]["id"]
        self.assertTrue(self.k.ukaz(kid, "osvezi"))
        self.assertFalse(self.k.ukaz(kid, "rm -rf"))
        self.assertFalse(self.k.ukaz("ni", "osvezi"))


if __name__ == "__main__":
    unittest.main()
