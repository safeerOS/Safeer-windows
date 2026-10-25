"""scripts/skupna_koda.py pozna skupni vmesnik (25. 10. 2026): assets/os in namizje QML sta razvrscena, QML Linuxa
(assets/os/qml/) je na Windows v windows/safeer_windows/qml/ (preslikava). Preverjanje proti Safeer-linux naredi CI
(posel skupna-koda); tu brez Linuxa: razvrstitev, preslikava in da so skupne datoteke na svojih mestih."""
import importlib.util
import json
import unittest
from pathlib import Path

KOREN = Path(__file__).resolve().parents[2]


def _skupna_koda():
    spec = importlib.util.spec_from_file_location("skupna_koda", KOREN / "scripts" / "skupna_koda.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class SkupnaKodaVmesnik(unittest.TestCase):
    def setUp(self):
        self.sk = _skupna_koda()
        self.s = json.loads((KOREN / "skupna-koda.json").read_text(encoding="utf-8"))

    def test_preslikava_qml(self):
        self.assertEqual(self.sk.pot_windows("assets/os/qml/Lupa.qml", self.s), "windows/safeer_windows/qml/Lupa.qml")
        self.assertEqual(self.sk.pot_linux("windows/safeer_windows/qml/Lupa.qml", self.s), "assets/os/qml/Lupa.qml")
        self.assertEqual(self.sk.pot_windows("core/x.py", self.s), "core/x.py")

    def test_vse_datoteke_vmesnika_razvrscene(self):
        znane = set(self.s["skupne"]) | set(self.s["zacasno_razlicne"]) | set(self.s["samo_windows"])
        self.assertEqual(sorted(self.sk.datoteke_razvrstitve(self.s) - znane), [])
        vse = self.sk.datoteke_razvrstitve(self.s)
        self.assertIn("assets/os/os.js", vse)
        self.assertIn("assets/os/qml/Namizje.qml", vse)

    def test_seznami_brez_podvajanja(self):
        vse = self.s["skupne"] + self.s["zacasno_razlicne"] + self.s["samo_windows"]
        self.assertEqual(len(vse), len(set(vse)))

    def test_skupne_obstajajo(self):
        for f in self.s["skupne"]:
            self.assertTrue((KOREN / self.sk.pot_windows(f, self.s)).is_file(), f)
        for f in ("assets/os/most.js", "assets/os/teme.json", "assets/os/qml/Lupa.qml", "core/platforma.py"):
            self.assertIn(f, self.s["skupne"])


if __name__ == "__main__":
    unittest.main()
