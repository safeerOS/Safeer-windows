"""SMTC (Windows): zunaj Windows nadzorovan preskok (aktiven=False, brez izjem); ukazi se preslikajo na pogon."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from safeer_windows import predvajalnik_smtc as smtc  # noqa: E402


class LazenPogon:
    def __init__(self): self.klici = []
    def predvajaj(self, i): self.klici.append(("predvajaj", i))
    def premor(self): self.klici.append(("premor",))
    def ustavi(self): self.klici.append(("ustavi",))
    def naslednja(self): self.klici.append(("naslednja",))
    def prejsnja(self): self.klici.append(("prejsnja",))


class Smtc(unittest.TestCase):
    def test_preskok_zunaj_windows(self):
        if sys.platform == "win32":
            self.skipTest("na Windows je odvisno od paketov winrt")
        self.assertFalse(smtc.na_voljo())
        s = smtc.SafeerSmtc(LazenPogon(), ime="Test")
        self.assertFalse(s.aktiven)
        s.ob_podatkih({"stanje": "predvaja"}); s.oddaj_seeked(); s.zapri()   # brez izjem

    def test_ukazi(self):
        s = smtc.SafeerSmtc.__new__(smtc.SafeerSmtc); pg = LazenPogon()
        s.pogon, s._zadnji, s.aktiven = pg, {"stanje": "ustavljeno", "nSeznam": 2, "indeks": 1}, False
        s._ukaz("play"); s._zadnji["stanje"] = "predvaja"; s._ukaz("pause"); s._zadnji["stanje"] = "premor"; s._ukaz("play")
        s._ukaz("next"); s._ukaz("previous"); s._ukaz("stop")
        self.assertEqual(pg.klici, [("predvajaj", 1), ("premor",), ("premor",), ("naslednja",), ("prejsnja",), ("ustavi",)])
        self.assertEqual(smtc._status({"stanje": "premor"}), "Paused")


if __name__ == "__main__":
    unittest.main()
