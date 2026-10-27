"""Nalaganje signed_feed za seznam groznj (27. 10. 2026: Windows 1.0.52 se ni zagnal - prazen modul v sys.modules)."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import threat_intel  # noqa: E402


class NalaganjeSignedFeed(unittest.TestCase):
    def setUp(self):
        self.prej = sys.modules.pop("safeer_signed_feed", None)
        self.addCleanup(self._obnovi)

    def _obnovi(self):
        sys.modules.pop("safeer_signed_feed", None)
        if self.prej is not None:
            sys.modules["safeer_signed_feed"] = self.prej

    def test_neuspesno_nalaganje_ne_pusti_praznega_modula(self):
        with tempfile.TemporaryDirectory() as d:
            napacna = Path(d) / "core" / "threat_intel.py"
            with mock.patch.object(threat_intel, "__file__", str(napacna)), \
                    mock.patch.object(sys, "_MEIPASS", d, create=True):
                with self.assertRaises(ImportError):
                    threat_intel._load_feed_module()
        self.assertNotIn("safeer_signed_feed", sys.modules)
        self.assertTrue(hasattr(threat_intel._load_feed_module(), "SignedFeedStore"))

    def test_zamrznjen_paket_najde_shared_core(self):
        with tempfile.TemporaryDirectory() as d:
            shared = Path(d) / "shared" / "core"
            shared.mkdir(parents=True)
            (shared / "signed_feed.py").write_text((ROOT / "core" / "signed_feed.py").read_text(encoding="utf-8"),
                                                   encoding="utf-8")
            with mock.patch.object(threat_intel, "__file__", str(Path(d) / "core" / "threat_intel.py")), \
                    mock.patch.object(sys, "_MEIPASS", d, create=True):
                modul = threat_intel._load_feed_module()
        self.assertTrue(hasattr(modul, "SignedFeedStore"))

    def test_prazen_modul_iz_prejsnjega_poskusa_se_nalozi_znova(self):
        sys.modules["safeer_signed_feed"] = type(sys)("safeer_signed_feed")
        self.assertTrue(hasattr(threat_intel._load_feed_module(), "SignedFeedStore"))


if __name__ == "__main__":
    unittest.main()
