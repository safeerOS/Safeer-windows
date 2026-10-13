"""Prenos Safeer DRM: preverjen SHA-256, varno razpakiranje, oznaka »preverjeno«, uskladitev main.js."""
import hashlib
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from safeer_windows import safeer_drm_prenos as p


def _paket(mapa: Path, datoteke: dict) -> Path:
    pot = mapa / "paket.zip"
    with zipfile.ZipFile(pot, "w") as z:
        for ime, vsebina in datoteke.items():
            z.writestr(ime, vsebina)
    return pot


class PrenosTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        okolje = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.tmp / "lad")})
        okolje.start()
        self.addCleanup(okolje.stop)

    def _url_sha(self, datoteke):
        paket = _paket(self.tmp, datoteke)
        return paket.as_uri(), hashlib.sha256(paket.read_bytes()).hexdigest()

    def test_pravilen_paket(self):
        url, sha = self._url_sha({"safeer-drm.exe": b"MZ", "resources/app/main.js": b"//"})
        self.assertIsNone(p.izvrsljiva())
        self.assertTrue(p.prenesi(url, sha))
        self.assertEqual(p.izvrsljiva(), p.mapa_verzije() / "safeer-drm.exe")
        self.assertTrue(p.prenesi(url, sha))  # drugic nic ne prenasa

    def test_napacen_sha_zavrze(self):
        url, _ = self._url_sha({"safeer-drm.exe": b"MZ"})
        self.assertFalse(p.prenesi(url, "0" * 64))
        self.assertIsNone(p.izvrsljiva())
        self.assertEqual([x.name for x in p.koren().iterdir()], [])

    def test_nevarna_pot_zavrze(self):
        url, sha = self._url_sha({"safeer-drm.exe": b"MZ", "../zunaj.txt": b"x"})
        self.assertFalse(p.prenesi(url, sha))
        self.assertIsNone(p.izvrsljiva())
        self.assertFalse((p.koren().parent / "zunaj.txt").exists())

    def test_uskladi_logiko(self):
        url, sha = self._url_sha({"safeer-drm.exe": b"MZ", "resources/app/main.js": b"staro"})
        self.assertTrue(p.prenesi(url, sha))
        vir = self.tmp / "vir"
        vir.mkdir()
        (vir / "main.js").write_text("novo", encoding="utf-8")
        p.uskladi_logiko(p.izvrsljiva(), vir)
        self.assertEqual((p.mapa_verzije() / "resources" / "app" / "main.js").read_text(encoding="utf-8"), "novo")


if __name__ == "__main__":
    unittest.main()
