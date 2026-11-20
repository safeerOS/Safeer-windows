"""mesh.route ovije sporocilo v `msg`: drugo JSON ubeganje ne sme preseci okvira soseda (CodeRabbit Linux, 19. 11. 2026)."""
import json
import unittest


class MeshUbeganjeTests(unittest.TestCase):
    """mesh.route ovije sporocilo v `msg`: drugo JSON ubeganje ne sme preseci okvira soseda (CodeRabbit Linux)."""

    class _Povezava:
        naslov = "127.0.0.1"

        def __init__(self):
            self.poslano = []

        def poslji(self, besedilo):
            self.poslano.append(besedilo)
            return True

    def test_sporocilo_z_veliko_narekovaji_se_ne_poslje_in_povezava_ostane(self):
        from core import link_hub_streznik as hs
        povezava = self._Povezava()
        n = hs._Namestnik("sosed", povezava, "naprava")
        sporocilo = json.dumps({"type": "sync.data", "payload": {"data": '"' * 550000}})
        self.assertLess(len(sporocilo), hs.NAJVEC_MESH_SPOROCILO)   # vhodni limit ga sprejme
        self.assertFalse(n.poslji(sporocilo))
        self.assertEqual(povezava.poslano, [])
        # Zavrnitev vsebine ni napaka povezave: isti posrednik takoj nato normalno posreduje (CodeRabbit st6).
        self.assertTrue(n.poslji(json.dumps({"type": "sync.data", "payload": {"data": "x" * 100000}})))
        self.assertEqual(len(povezava.poslano), 1)

    def test_navadno_sporocilo_se_poslje(self):
        from core import link_hub_streznik as hs
        povezava = self._Povezava()
        n = hs._Namestnik("sosed", povezava, "naprava")
        self.assertTrue(n.poslji(json.dumps({"type": "sync.data", "payload": {"data": "x" * 100000}})))
        self.assertEqual(len(povezava.poslano), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
