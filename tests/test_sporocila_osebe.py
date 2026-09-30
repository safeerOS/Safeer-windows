"""Osebe v Sporocilih: lastno ime (sinhronizacija ga ne prepise), zdruzevanje identitet (pogovori se preselijo),
razdruzitev, oznake pogovorov, iskanje po imenu/oznaki."""
import os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.sporocila.storitev import StoritevSporocil  # noqa: E402
from core.sporocila.model import Kanal, Pogovor, Sporocilo  # noqa: E402
from core import os_sporocila  # noqa: E402


class Lazen:
    def __init__(self, vrsta, pog, spor, imena): self.vrsta, self._p, self._s, self._i = vrsta, pog, spor, imena
    def povezi(self): pass
    def pogovori(self): return self._p
    def sporocila(self, pid, najvec=50): return self._s.get(pid, [])
    def ime_osebe(self, oid): return self._i.get(oid, "")


class Osebe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.st = StoritevSporocil(Path(self.tmp) / "s.sqlite3")
        C = "2026-09-30T10:00:00+00:00"
        self.st.registriraj(Kanal("e1", "email", "jaz@primer.si", "povezan"), Lazen("email",
            [Pogovor("mama@gmail.com", "e1", "mama@gmail.com", "Kosilo", "Prideš v nedeljo?", 1, C)],
            {"mama@gmail.com": [Sporocilo("m1", "mama@gmail.com", "noter", "Prideš v nedeljo?", C, [])]},
            {"mama@gmail.com": "Marija Novak"}))
        self.st.registriraj(Kanal("c1", "chatwoot", "Podpora", "povezan"), Lazen("chatwoot",
            [Pogovor("42", "c1", "kupec-42", "", "Živjo", 0, C)],
            {"42": [Sporocilo("c1a", "42", "noter", "Živjo", C, [])]}, {"kupec-42": "M. Novak"}))
        self.st.sinhroniziraj()
        self.os = os_sporocila.SporocilaOS.__new__(os_sporocila.SporocilaOS); self.os.storitev = self.st

    def tearDown(self): self.st.zapri()

    def _oseba(self, ime):
        return next(s for s in self.os.seznam()["skupine"] if s["oseba"]["ime"] == ime)

    def test_lastno_ime_prezivi_sinhronizacijo(self):
        o = self._oseba("Marija Novak")["oseba"]
        self.os.preimenuj_osebo(o["id"], "Mama")
        self.st.sinhroniziraj()
        s = self._oseba("Mama")
        self.assertEqual(s["oseba"]["privzeto_ime"], "Marija Novak"); self.assertEqual(s["oseba"]["lastno_ime"], "Mama")
        self.os.preimenuj_osebo(o["id"], "")   # nazaj na ime iz kanala
        self.assertTrue(self._oseba("Marija Novak"))

    def test_zdruzi_in_razdruzi(self):
        a = self._oseba("Marija Novak")["oseba"]; b = self._oseba("M. Novak")["oseba"]
        self.os.preimenuj_osebo(a["id"], "Mama")
        self.os.zdruzi_osebi(a["id"], b["id"])
        s = self._oseba("Mama")
        self.assertEqual(sorted(p["kanal_id"] for p in s["pogovori"]), ["c1", "e1"])
        self.assertEqual(len(self.os.seznam()["skupine"]), 1)
        self.st.sinhroniziraj()                                     # po sinhronizaciji ostane zdruzeno
        self.assertEqual(len(self.os.seznam()["skupine"]), 1)
        self.os.razdruzi_osebo(a["id"], ["chatwoot", "kupec-42"])
        self.assertEqual(len(self.os.seznam()["skupine"]), 2)

    def test_oznake_in_iskanje(self):
        self.os.nastavi_oznake("e1", "mama@gmail.com", ["Družina", "Kosilo", "družina", ""])
        s = self.os.seznam()
        self.assertEqual(s["oznake"], ["Družina", "Kosilo"])
        self.assertEqual(self._oseba("Marija Novak")["pogovori"][0]["oznake"], ["Družina", "Kosilo"])
        self.assertEqual([x["oseba"]["ime"] for x in self.os.isci("družina")], ["Marija Novak"])
        self.os.preimenuj_osebo(self._oseba("Marija Novak")["oseba"]["id"], "Mama")
        self.assertEqual([x["oseba"]["ime"] for x in self.os.isci("mama")], ["Mama"])


if __name__ == "__main__":
    unittest.main()
