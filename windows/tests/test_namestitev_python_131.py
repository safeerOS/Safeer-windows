"""Naloga 131: namestitev Pythona v install.ps1 - prenos se ne zazene brez pripete SHA-256 in veljavnega podpisa
Python Software Foundation; korenski install.ps1 je enak windows/install.ps1 (prej mu je manjkal zeroconf)."""
import re
import unittest
from pathlib import Path

KOREN = Path(__file__).resolve().parents[2]
# SHA-256 iz uradnega paketa Sigstore na python.org (python-3.12.10-amd64.exe.sigstore), prebrano 24. 10. 2026.
SHA256_3_12_10 = "67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb"


class NamestitevPythona(unittest.TestCase):
    def test_korenski_in_windows_install_sta_enaka(self):
        self.assertEqual((KOREN / "install.ps1").read_bytes(), (KOREN / "windows" / "install.ps1").read_bytes())
        self.assertEqual((KOREN / "install.bat").read_bytes(), (KOREN / "windows" / "install.bat").read_bytes())
        self.assertIn('"zeroconf")', (KOREN / "install.ps1").read_text(encoding="utf-8"))

    def test_preverba_pred_zagonom(self):
        for pot in ("install.ps1", "windows/install.ps1"):
            s = (KOREN / pot).read_text(encoding="utf-8")
            self.assertIn('$pythonUrl = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"', s)
            self.assertIn('$pythonSha256 = "%s"' % SHA256_3_12_10, s)
            # 3.12.8: podpisni certifikat je python.org 28. 8. 2025 preklical - preverba podpisa bi vedno padla.
            self.assertNotIn("python-3.12.8-amd64.exe", s)
            prenos = s.index("Invoke-WebRequest -Uri $pythonUrl")
            zagon = s.index("Start-Process -FilePath $tempInstaller")
            for preverba in ("Get-FileHash -Path $tempInstaller -Algorithm SHA256", "Get-AuthenticodeSignature -FilePath $tempInstaller",
                             '$podpis.Status -ne "Valid"', "Python Software Foundation"):
                self.assertTrue(prenos < s.index(preverba) < zagon, (pot, preverba))
            # Ob neujemanju: datoteka izbrisana in konec, preden bi se karkoli zagnalo.
            blok = s[prenos:zagon]
            self.assertEqual(len(re.findall(r"Remove-Item \$tempInstaller -Force -ErrorAction SilentlyContinue\s+Write-Err [^\n]+\s+exit 1", blok)), 2)


if __name__ == "__main__":
    unittest.main()
