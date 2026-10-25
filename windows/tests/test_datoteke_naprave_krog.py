"""Datoteke naprav v Safeer Linku na Windows (lastnik, 25. 10. 2026): samo naprave v ozjem krogu zaupanja (kot Linux),
nalaganje velike mape (galerija telefona) po delih z `offset`/`next_offset` in polje »ozji« v seznamu naprav."""
import os
import sys
import unittest
from unittest import mock

KOREN = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, KOREN)
sys.path.insert(0, os.path.join(KOREN, "windows"))

try:
    from safeer_windows import control_backend
except Exception:  # pragma: no cover - na sistemu brez Qt
    control_backend = None


@unittest.skipIf(control_backend is None, "control_backend se ne uvozi")
class DatotekeNaprave(unittest.TestCase):
    def setUp(self):
        b = control_backend.SafeerControlBackend.__new__(control_backend.SafeerControlBackend)
        b.naprave = [{"id": "n-tel", "ime": "Telefon", "platforma": "android", "zmoznosti": ["files"]},
                     {"id": "n-tuj", "ime": "Tuj", "platforma": "android", "zmoznosti": ["files"]}]
        b.device_id = "n-ta"
        self.klici = []

        def ukaz(id_n, akcija, parametri, cas=0):
            self.klici.append((id_n, akcija, dict(parametri)))
            return {"ok": True, "data": {"items": [{"id": "media:image:1", "name": "a.jpg"}], "shared": True,
                                         "next_offset": 500, "total": "1234"}}
        b.ukaz_pocakaj = ukaz
        self.b = b
        self.krog = mock.patch.object(control_backend.SafeerControlBackend, "v_ozjem_krogu",
                                      staticmethod(lambda i: i == "n-tel"))
        self.krog.start()

    def tearDown(self):
        self.krog.stop()

    def test_samo_ozji_krog(self):
        r = self.b.datoteke_naprave("n-tuj", "")
        self.assertEqual((r["ok"], r["koda"]), (False, "ni_ozji_krog"))
        self.assertEqual(self.klici, [])                      # naprave izven kroga sploh ne vprasamo
        self.assertTrue(self.b.datoteke_naprave("n-tel", "")["ok"])

    def test_po_delih(self):
        r = self.b.datoteke_naprave("n-tel", "media:image", 500)
        self.assertEqual(self.klici[-1], ("n-tel", "files.list", {"folder": "media:image", "offset": 500}))
        self.assertEqual((r["next_offset"], r["total"]), (500, 1234))
        self.b.datoteke_naprave("n-tel", "media:image")
        self.assertEqual(self.klici[-1][2], {"folder": "media:image"})   # starejse naprave: brez novega parametra
        self.b.datoteke_naprave("n-tel", "media:image", "x")
        self.assertEqual(self.klici[-1][2], {"folder": "media:image"})

    def test_seznam_naprav_ima_ozji(self):
        z = {n["id"]: n["ozji"] for n in self.b.naprave_s_datotekami()}
        self.assertEqual(z, {"n-tel": True, "n-tuj": False})
        self.assertEqual({n["id"]: n["ozji"] for n in self.b.vse_naprave()}, {"n-tel": True, "n-tuj": False})

    def test_stevilo(self):
        self.assertEqual(control_backend.stevilo_ali_nic("7"), 7)
        self.assertEqual(control_backend.stevilo_ali_nic(-3), 0)
        self.assertEqual(control_backend.stevilo_ali_nic(True), 0)
        self.assertEqual(control_backend.stevilo_ali_nic(None), 0)

    def test_namizje_pokaze_samo_ozji_krog(self):
        from safeer_windows import namizje_qml

        class Cb:
            def naprave_s_programi(self):
                return []

            def naprave_s_datotekami(self):
                return [{"id": "n-tel", "ime": "Telefon", "ozji": True}, {"id": "n-tuj", "ime": "Tuj", "ozji": False}]

            def vse_naprave(self):
                return [{"id": "n-tel", "ime": "Telefon"}, {"id": "n-tuj", "ime": "Tuj"}]
        self.assertEqual([n["kljuc"] for n in namizje_qml.naprave_za_izbiro(Cb())], ["n-tel"])


if __name__ == "__main__":
    unittest.main()
