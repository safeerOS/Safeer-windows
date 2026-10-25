"""Windows je privzeto pripravljen na upravljanje s Safeer Agentom (lastnik, 13. 10. 2026): ukazi agenta
(open_url, search.query) se zgodijo vidno v Safeer OS, naprava, ki gleda navidezni zaslon, pa stran dobi tam."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from safeer_windows import control_backend  # noqa: E402


class Povezava:
    tece = True

    def __init__(self):
        self.poslana = []

    def poslji(self, s):
        self.poslana.append(s)
        return True


def ukaz(akcija, params, posiljatelj="telefon-1"):
    return {"id": "u-" + akcija, "type": "control.command", "sender": posiljatelj,
            "payload": {"action": akcija, "params": params}}


class AgentPripravljen(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.b = control_backend.SafeerControlBackend(config_pot=os.path.join(self.td.name, "link.json"))
        self.p = Povezava()
        self.b.povezava = self.p
        self.strani, self.iskanja = [], []

    def tearDown(self):
        self.td.cleanup()

    def _odgovor(self):
        return self.p.poslana[-1]["payload"]

    def test_stran_se_odpre_vidno_v_safeer_os(self):
        self.b.ob_strani = lambda url: self.strani.append(url) or True
        self.b._na_sporocilo(ukaz("open_url", {"url": "https://safeer.si"}))
        self.assertTrue(self._odgovor()["ok"])
        self.assertEqual(self.strani, ["https://safeer.si"])
        self.assertNotEqual(self.b.navidezni_zaslon.aktivni_url, "https://safeer.si")

    def test_gledalec_navideznega_zaslona_dobi_stran_tam(self):
        self.b.ob_strani = lambda url: self.strani.append(url) or True
        nz = self.b.navidezni_zaslon
        nz._tece, nz._posiljatelj_seje = True, "tv-1"
        try:
            self.b._na_sporocilo(ukaz("open_url", {"url": "https://safeer.si"}, "tv-1"))
        finally:
            nz._tece = False
        self.assertEqual(self.strani, [])
        self.assertEqual(nz.aktivni_url, "https://safeer.si")

    def test_safeer_naslov_ostane_na_navideznem(self):
        self.b.ob_strani = lambda url: self.strani.append(url) or True
        self.b._na_sporocilo(ukaz("open_url", {"url": "safeer://domov"}))
        self.assertEqual(self.strani, [])

    def test_iskanje_agenta(self):
        self.b.ob_iskanju = lambda q: self.iskanja.append(q) or True
        self.b._na_sporocilo(ukaz("search.query", {"q": "  risanke   za otroke "}))
        self.assertTrue(self._odgovor()["ok"])
        self.assertEqual(self.iskanja, ["risanke za otroke"])

    def test_iskanje_brez_safeer_os_in_prazno(self):
        self.b._na_sporocilo(ukaz("search.query", {"q": "risanke"}))
        self.assertEqual(self._odgovor().get("code"), "ni_safeer_os")
        self.b.ob_iskanju = lambda q: True
        self.b._na_sporocilo(ukaz("search.query", {"q": "   "}))
        self.assertEqual(self._odgovor().get("code"), "prazno")

    def test_stanje_oglasi_iskanje(self):
        self.b._na_sporocilo(ukaz("status", {}))
        self.assertNotIn("search.query", self._odgovor()["data"].get("actions") or [])
        self.b.ob_iskanju = lambda q: True
        self.b._na_sporocilo(ukaz("status", {}))
        self.assertIn("search.query", self._odgovor()["data"]["actions"])

    def test_glasnost_je_prava(self):
        from unittest import mock
        from safeer_windows import glasnost_win
        with mock.patch.object(glasnost_win, "nastavi", return_value={"level": 35, "muted": False}) as n:
            self.b._na_sporocilo(ukaz("volume", {"direction": "down"}))
        n.assert_called_once_with("down", None)
        self.assertEqual(self._odgovor()["data"], {"level": 35, "muted": False})
        self.assertEqual(self.b.navidezni_zaslon.glasnost, 35)

    def test_glasnost_brez_zvocne_naprave(self):
        from unittest import mock
        from safeer_windows import glasnost_win
        with mock.patch.object(glasnost_win, "nastavi", return_value=None):
            self.b._na_sporocilo(ukaz("volume", {"level": 60}))
        self.assertEqual(self._odgovor()["data"]["level"], 60)


if __name__ == "__main__":
    unittest.main()
