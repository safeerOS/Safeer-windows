"""Koda QR za »Poveži novo napravo« nastane s prilozeno knjiznico (windows/qrcode), brez dodatnih paketov.

Izmerjeno 5. 10. 2026 na testnem racunalniku z namescenim Safeer OS 1.0.38: prilozeni qrcode 7.4.2 je ob uvozu
zahteval modul png (paket pypng), ki ga zaganjalnik ne namesti -> "No module named 'png'", core.link_hub.qr_svg je
vrnil prazen niz in okno »Poveži naprave« je bilo brez kode QR. Preverjanje tega ni videlo, ker je imelo pypng
namescen (requirements.txt). Preizkus zato tece v svojem procesu, v katerem teh modulov NI mogoce uvoziti.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

KOREN = Path(__file__).resolve().parents[2]

KODA = r'''
import sys


class Blokada:
    """Kot na uporabnikovem racunalniku: teh knjiznic ni."""

    def find_spec(self, ime, pot=None, cilj=None):
        if ime.split(".")[0] in ("png", "typing_extensions", "PIL", "lxml"):
            raise ModuleNotFoundError("No module named %r" % ime.split(".")[0])
        return None


sys.meta_path.insert(0, Blokada())
from core import link_hub

svg = link_hub.qr_svg("https://safeer.si/p#j=0123456789abcdef&s=skrivnost&f=" + "ab" * 32 + "&a=192.168.1.20:8990")
import qrcode

print(len(svg))
print(svg[:200].replace("\n", " "))
print(qrcode.__file__)
'''


class QrPrilozen(unittest.TestCase):
    def test_qr_nastane_brez_pypng_typing_extensions_in_pil(self):
        okolje = dict(os.environ)
        okolje["PYTHONPATH"] = os.pathsep.join([str(KOREN / "windows"), str(KOREN)])
        okolje["PYTHONIOENCODING"] = "utf-8"
        p = subprocess.run([sys.executable, "-c", KODA], env=okolje, cwd=str(KOREN), capture_output=True, text=True,
                           encoding="utf-8", timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        vrstice = p.stdout.strip().splitlines()
        self.assertGreater(int(vrstice[0]), 1000, "qr_svg je vrnil prazen ali prekratek SVG")
        self.assertIn("<svg", vrstice[1])
        self.assertEqual(Path(vrstice[2]).resolve(), (KOREN / "windows" / "qrcode" / "__init__.py").resolve(),
                         "uporabljena mora biti prilozena knjiznica")

    def test_licenca_in_opis_sprememb_sta_prilozena(self):
        licenca = (KOREN / "windows" / "qrcode" / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Lincoln Loop", licenca)
        self.assertIn("Redistribution and use in source and binary forms", licenca)
        opis = (KOREN / "windows" / "qrcode" / "SAFEER.md").read_text(encoding="utf-8")
        self.assertIn("7.4.2", opis)
        self.assertIn("typing", opis)

    def test_prilozena_knjiznica_ne_uvaza_zunanjih_na_vrhu(self):
        """Na vrhu modulov, ki jih potrebuje koda SVG, ni uvoza png ali typing_extensions."""
        for ime in ("main.py", "image/svg.py", "image/base.py", "__init__.py"):
            vir = (KOREN / "windows" / "qrcode" / ime).read_text(encoding="utf-8")
            for vrstica in vir.splitlines():
                if vrstica.startswith(("import ", "from ")):
                    self.assertNotRegex(vrstica.split("#")[0], r"\b(png|typing_extensions)\b", ime + ": " + vrstica)


if __name__ == "__main__":
    unittest.main()
