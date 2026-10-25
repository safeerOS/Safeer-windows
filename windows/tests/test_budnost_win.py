"""Windows: racunalnik ne zaspi sam med filmom (budnost_win, SAFEER-ZNANJE Z4608, zapisnik 25. 10. W3).

Logika z laznim kernel32 (tece tudi na Linuxu); na pravem Windows se zahteva res ustvari in, ce je powercfg dosegljiv
s skrbniskimi pravicami (izvajalnik CI), se preveri, da jo sistem vidi in da po sprostitvi izgine.
"""
import ctypes
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from safeer_windows import budnost_win as B  # noqa: E402
from safeer_windows import safeer_mpv_pogon as P  # noqa: E402


class _Jedro:
    """Lazni kernel32: belezi klice, zna odpovedati PowerCreateRequest."""

    def __init__(self, zahteve_delajo=True):
        self.zahteve_delajo = zahteve_delajo
        self.klici = []
        self.odprte = {}      # rocaj -> set tipov
        self.nit = B.ES_CONTINUOUS
        self._naslednji = 100

    def ustvari_zahtevo(self, opis):
        self.klici.append(("ustvari", opis))
        if not self.zahteve_delajo:
            raise OSError(1, "PowerCreateRequest ni uspel")
        self._naslednji += 1
        self.odprte[self._naslednji] = set()
        return self._naslednji

    def nastavi_zahtevo(self, rocaj, tip):
        self.klici.append(("nastavi", rocaj, tip)); self.odprte[rocaj].add(tip)

    def pocisti_zahtevo(self, rocaj, tip):
        self.klici.append(("pocisti", rocaj, tip)); self.odprte[rocaj].discard(tip)

    def zapri(self, rocaj):
        self.klici.append(("zapri", rocaj)); del self.odprte[rocaj]

    def stanje_niti(self, es):
        self.klici.append(("nit", es)); prej, self.nit = self.nit, es
        return prej or 1


VIDEO = B.SPANJE | B.ZASLON


class ZahteveMoci(unittest.TestCase):
    def test_video_zadrzi_spanje_in_zaslon_premor_sprosti(self):
        j = _Jedro(); b = B.Budnost(jedro=j)
        self.assertTrue(b.nastavi("predvajanje", VIDEO, "Safeer predvaja"))
        self.assertEqual(j.klici[0], ("ustvari", "Safeer predvaja"))
        (rocaj, tipi), = j.odprte.items()
        self.assertEqual(tipi, {B.ZAHTEVA_SISTEM, B.ZAHTEVA_ZASLON})
        self.assertEqual(b.stanje(), {"predvajanje": VIDEO})
        n = len(j.klici)
        self.assertTrue(b.nastavi("predvajanje", VIDEO, "Safeer predvaja"))   # vsak tik: nic novega
        self.assertEqual(len(j.klici), n)
        self.assertFalse(b.nastavi("predvajanje", 0))
        self.assertEqual(j.odprte, {})
        self.assertIn(("zapri", rocaj), j.klici)
        self.assertEqual(b.stanje(), {})

    def test_glasba_samo_spanje(self):
        j = _Jedro(); b = B.Budnost(jedro=j)
        b.nastavi("predvajanje", B.SPANJE)
        self.assertEqual(list(j.odprte.values()), [{B.ZAHTEVA_SISTEM}])

    def test_menjava_video_v_glasbo_zamenja_zahtevo(self):
        j = _Jedro(); b = B.Budnost(jedro=j)
        b.nastavi("predvajanje", VIDEO); b.nastavi("predvajanje", B.SPANJE)
        self.assertEqual(list(j.odprte.values()), [{B.ZAHTEVA_SISTEM}])

    def test_razlogi_so_neodvisni_in_sprosti_vse(self):
        j = _Jedro(); b = B.Budnost(jedro=j)
        b.nastavi("predvajanje", VIDEO); b.nastavi("predvajalnik", B.SPANJE)
        b.nastavi("predvajanje", 0)
        self.assertEqual(b.stanje(), {"predvajalnik": B.SPANJE})
        self.assertEqual(len(j.odprte), 1)
        b.sprosti_vse()
        self.assertEqual((b.stanje(), j.odprte), ({}, {}))


class RezervaStanjeNiti(unittest.TestCase):
    def test_brez_zahtev_moci_set_thread_execution_state(self):
        j = _Jedro(zahteve_delajo=False); b = B.Budnost(jedro=j)
        self.assertTrue(b.nastavi("predvajanje", VIDEO))
        self.assertEqual(j.nit, B.ES_CONTINUOUS | B.ES_SYSTEM_REQUIRED | B.ES_DISPLAY_REQUIRED)
        self.assertEqual(b.stanje(), {"predvajanje": VIDEO})
        b.nastavi("predvajanje", 0)
        self.assertEqual(j.nit, B.ES_CONTINUOUS)
        self.assertEqual(b.stanje(), {})

    def test_rezerva_je_unija_razlogov(self):
        """SetThreadExecutionState velja za nit: sprostitev enega razloga ne sme sprostiti drugega."""
        j = _Jedro(zahteve_delajo=False); b = B.Budnost(jedro=j)
        b.nastavi("predvajanje", VIDEO); b.nastavi("pomoc", B.SPANJE)
        b.nastavi("predvajanje", 0)
        self.assertEqual(j.nit, B.ES_CONTINUOUS | B.ES_SYSTEM_REQUIRED)
        self.assertEqual(b.stanje(), {"pomoc": B.SPANJE})
        b.sprosti_vse()
        self.assertEqual(j.nit, B.ES_CONTINUOUS)

    def test_po_prvi_napaki_ne_poskusa_znova(self):
        j = _Jedro(zahteve_delajo=False); b = B.Budnost(jedro=j)
        b.nastavi("a", VIDEO); b.nastavi("b", VIDEO)
        self.assertEqual(sum(1 for k in j.klici if k[0] == "ustvari"), 1)


class ZastavicePredvajanja(unittest.TestCase):
    def test_stanja(self):
        z = B.zastavice_predvajanja
        self.assertEqual(z({"stanje": "predvaja", "steze": {"slika": True}}), VIDEO)
        self.assertEqual(z({"stanje": "predvaja", "steze": {"slika": False}}), B.SPANJE)
        self.assertEqual(z({"stanje": "predvaja", "vrsta": "video"}), VIDEO)
        self.assertEqual(z({"stanje": "premor", "steze": {"slika": True}}), 0)
        self.assertEqual(z({"stanje": "ustavljeno"}), 0)
        self.assertEqual(z(None), 0)

    def test_naslovnica_albuma_ni_slika(self):
        class _Mpv:
            track_list = [{"id": 1, "type": "video", "selected": True, "albumart": True},
                          {"id": 1, "type": "audio", "selected": True}]
        p = object.__new__(P.SafeerMpvPogon); p._mpv = _Mpv()
        self.assertFalse(p.steze()["slika"])
        _Mpv.track_list = [{"id": 1, "type": "video", "selected": True}, {"id": 1, "type": "audio", "selected": True}]
        self.assertTrue(p.steze()["slika"])

    def test_brez_windows_ne_naredi_nicesar(self):
        with mock.patch.object(B, "_je_windows", return_value=False):
            b = B.Budnost()
            self.assertFalse(b.nastavi("predvajanje", VIDEO))
            self.assertEqual(b.stanje(), {})


class Povezave(unittest.TestCase):
    """Predvajalniki poklicejo budnost ob spremembi stanja in jo sprostijo ob ustavitvi/zaprtju."""

    def _beri(self, ime):
        with open(os.path.join(os.path.dirname(__file__), "..", "safeer_windows", ime), encoding="utf-8") as f:
            return f.read()

    def test_medijski_center_mpv(self):
        s = self._beri("mpv_player.py")
        self.assertIn('_budnost(p, "predvajanje")', s)
        self.assertEqual(s.count('_budnost(None, "predvajanje")'), 2)   # stop in zapri_pogon

    def test_samostojni_predvajalnik(self):
        s = self._beri("safeer_mpv_okno.py")
        self.assertIn("_budnost(p)", s)
        self.assertIn("_budnost(None)", s)

    def test_vlc(self):
        s = self._beri("vlc_player.py")
        self.assertIn("self._budnost(igra)", s)
        self.assertIn("self._budnost(False)", s)


class Struktura(unittest.TestCase):
    def test_reason_context(self):
        T = B.tip_reason_context()
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            self.assertEqual(ctypes.sizeof(T), 32)
        k = T(); k.Flags = 1; k.Reason.SimpleReasonString = "Safeer predvaja"
        self.assertEqual(k.Reason.SimpleReasonString, "Safeer predvaja")


@unittest.skipUnless(sys.platform == "win32", "samo na Windows")
class PraviWindows(unittest.TestCase):
    RAZLOG = "Safeer preizkus budnosti"

    def _zahteve(self):
        try:
            r = subprocess.run(["powercfg", "/requests"], capture_output=True, timeout=30)
        except Exception:  # noqa: BLE001
            return None
        return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None   # brez skrbnika: ni podatka

    def test_zahteva_res_velja_in_izgine(self):
        b = B.Budnost(jedro=B.Kernel32())
        self.assertTrue(b.nastavi("preizkus", VIDEO, self.RAZLOG))
        self.assertEqual(b.stanje(), {"preizkus": VIDEO})
        pred = self._zahteve()
        b.nastavi("preizkus", 0)
        po = self._zahteve()
        if pred is None:
            self.skipTest("powercfg /requests potrebuje skrbniske pravice")
        self.assertIn(self.RAZLOG, pred)
        self.assertNotIn(self.RAZLOG, po or "")

    def test_rezerva_set_thread_execution_state(self):
        j = B.Kernel32()
        self.assertNotEqual(j.stanje_niti(B.ES_CONTINUOUS | B.ES_SYSTEM_REQUIRED), 0)
        self.assertNotEqual(j.stanje_niti(B.ES_CONTINUOUS), 0)


if __name__ == "__main__":
    unittest.main()
