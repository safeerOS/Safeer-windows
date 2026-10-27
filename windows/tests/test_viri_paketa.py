"""Namesceni paket (PyInstaller) uporablja samo svojo kodo, ne stare mape %LOCALAPPDATA%\\SafeerOS\\app
(27. 10. 2026, naloga 41: 1.0.52 je tekel s kodo zaganjalnika 1.0.51 z 25. 10.)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

from safeer_windows import policy


class ViriPaketa(unittest.TestCase):
    def test_zamrznjen_paket_ne_vzame_stare_mape_app(self):
        with tempfile.TemporaryDirectory() as d:
            app = os.path.join(d, "SafeerOS", "app")
            os.makedirs(os.path.join(app, "core"))
            open(os.path.join(app, "core", "threat_intel.py"), "w").close()
            paket = os.path.join(d, "paket")
            os.makedirs(os.path.join(paket, "shared", "core"))
            open(os.path.join(paket, "shared", "core", "threat_intel.py"), "w").close()
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": d}), mock.patch.object(sys, "_MEIPASS", paket, create=True):
                self.assertNotIn(app, policy.resource_roots())
                self.assertEqual(policy.shared_path("core/threat_intel.py"),
                                 os.path.join(paket, "shared", "core", "threat_intel.py"))

    def test_izvorna_koda_pod_starim_zaganjalnikom_vzame_mapo_app(self):
        with tempfile.TemporaryDirectory() as d:
            app = os.path.join(d, "SafeerOS", "app")
            os.makedirs(app)
            prej = getattr(sys, "_MEIPASS", None)
            if prej is not None:
                self.skipTest("tece zamrznjeno")
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": d}):
                self.assertEqual(policy.resource_roots()[0], app)


if __name__ == "__main__":
    unittest.main()
