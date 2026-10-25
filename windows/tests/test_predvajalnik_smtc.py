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


    def test_zaprt_pred_uvozom_winrt(self):
        """Naloga 13 (pomocnik): okno zaprto pred koncem uvoza winrt - _po_uvozu ne naredi nicesar (prej
        AttributeError in sesutje procesa)."""
        s = smtc.SafeerSmtc.__new__(smtc.SafeerSmtc)
        s.pogon, s.aktiven, s._zadnji_p = LazenPogon(), False, {"stanje": "predvaja"}
        s._zaprto, s._priprava = False, None
        zagnan = []
        s._zazeni = lambda: zagnan.append(1)
        s.zapri()
        s._po_uvozu(True)
        self.assertEqual(zagnan, [])
        prazen = smtc.SafeerSmtc.__new__(smtc.SafeerSmtc)      # brez atributov (pospravljen predmet)
        prazen._po_uvozu(True)


class PredvajalnikVir(unittest.TestCase):
    def test_naslov_brez_poizvedbe(self):
        """Naslov okna in SMTC: samo ime datoteke - poizvedba lahko nosi zeton (naloga 13)."""
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from safeer_windows import safeer_predvajalnik as p
        self.assertEqual(p.naslov_vira("https://x.example/film.mkv?token=skrivno#t=1"), "film.mkv")
        self.assertEqual(p.naslov_vira("https://x.example/"), "x.example")
        self.assertEqual(p.naslov_vira("http://h/pot/ime%20datoteke.mp4?x=1"), "ime datoteke.mp4")

    def test_libmpv_z_namizja_samo_za_razvoj(self):
        vir = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "safeer_windows",
                                "safeer_mpv_pogon.py"), encoding="utf-8").read()
        zacetek = vir.index("def _pripravi_pot")
        telo = vir[zacetek:vir.index("for d in kandidati", zacetek)]
        self.assertLess(telo.index('SAFEER_RAZVOJ'), telo.index('"Desktop"'))   # Namizje samo pod zastavico


    def test_napaka_vira_se_pokaze(self):
        """Naloga 13 (NIZKO 5): vir s HTTP 403 - okno pove napako, stanje se osvezi (SMTC ne ostane »predvaja«)."""
        from safeer_windows import safeer_mpv_pogon as mp
        p = mp.SafeerMpvPogon.__new__(mp.SafeerMpvPogon)
        napake, spremembe = [], []
        p._zapiranje, p._mpv, p._seznam, p._indeks = False, object(), [{"uri": "https://x/f.mkv"}], 0
        p._cb_napaka, p._cb_sprememba = napake.append, spremembe.append
        p._konec_datoteke({"event": {"reason": "error", "error": -13}})
        self.assertEqual((napake, spremembe), ([mp.SafeerMpvPogon.NAPAKA_VIRA], [None]))
        p._konec_datoteke({"event": {"reason": "eof"}})
        self.assertTrue(p._konec_cakajoc and p._koncan_uri == "https://x/f.mkv")
        p._konec_datoteke({"event": {"reason": "stop"}})              # uporabnik ustavil: nic
        self.assertEqual(len(spremembe), 2)


if __name__ == "__main__":
    unittest.main()
