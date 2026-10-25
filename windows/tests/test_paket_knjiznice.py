"""Knjiznice programa so v uradnem paketu (25. 10. 2026).

PyAV ni bil v windows/requirements.txt, Pillow pa je gradnja SafeerOS.exe izpustila (--exclude-module PIL): v paketu
iz CI 176a7ac SafeerOS.exe nima ne av ne PIL (izmerjeno v PYZ), zato deljenje zaslona napravi vrne »manjka kodirnik
slike (PyAV)«, gledalec ne dekodira. Preizkusi iz izvora tega niso videli, ker je tam vse namesceno. Ti preizkusi
padejo na kodi pred popravkom; v zgrajenem paketu isto preveri korak CI kodek-frozen (preveri_kodek.py).
"""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

KOREN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KOREN / "windows"))

from safeer_windows import knjiznice, preveri_kodek  # noqa: E402

WIN = KOREN / "windows"
#: qrcode je prilozen v windows/qrcode (glej requirements.txt), ne pride iz pip.
PRILOZENI = {"qrcode"}


def _ime(paket: str) -> str:
    return re.sub(r"[-_.]+", "-", paket).lower()


def _zahteve() -> dict:
    """Ime paketa (normalizirano) -> vrstica iz windows/requirements.txt."""
    zahteve = {}
    for vrstica in (WIN / "requirements.txt").read_text(encoding="utf-8").splitlines():
        vrstica = vrstica.split("#", 1)[0].strip()
        m = re.match(r"^([A-Za-z0-9_.\-]+)", vrstica)
        if m:
            zahteve[_ime(m.group(1))] = vrstica
    return zahteve


def _ukaz_safeeros() -> str:
    """Besedilo seznama command_os (gradnja SafeerOS.exe) v build_windows.py."""
    s = (WIN / "build_windows.py").read_text(encoding="utf-8")
    zacetek = s.index("command_os = [")
    return s[zacetek:s.index("\n        ]\n", zacetek)]


class KnjizniceVPaketu(unittest.TestCase):
    def test_vsaka_knjiznica_programa_je_v_requirements(self):
        zahteve = _zahteve()
        manjka = [paket for modul, paket in knjiznice.PAKETI.items()
                  if modul not in PRILOZENI and _ime(paket) not in zahteve]
        self.assertEqual(manjka, [], "paketi, ki jih program rabi, CI pa jih ne namesti za gradnjo")

    def test_pyav_in_pillow_pripeta(self):
        zahteve = _zahteve()
        self.assertRegex(zahteve.get("av", ""), r"^av==\d+\.\d+\.\d+$")
        self.assertRegex(zahteve.get("pillow", ""), r"^Pillow==\d+\.\d+\.\d+$")

    def test_gradnja_safeeros_ne_izpusti_knjiznic(self):
        ukaz = _ukaz_safeeros()
        izpusceni = set(re.findall(r'"--exclude-module",\s*"([^"]+)"', ukaz))
        vrhnji = {modul.split(".")[0] for modul in knjiznice.PAKETI}
        self.assertEqual(izpusceni & vrhnji, set())

    def test_izjema_pe_za_pyav_je_za_isto_razlicico(self):
        av = _zahteve()["av"].split("==")[1]
        izjeme = json.loads((WIN / "tools" / "pe_izjeme.json").read_text(encoding="utf-8"))["izjeme"]
        izjema = izjeme["*/av.libs/*.dll"]
        self.assertTrue(izjema.get("tuja"))
        self.assertIn("av %s " % av, izjema["razlicica"])
        self.assertGreaterEqual(len(izjema["sha256"]), 20)
        pyd = izjeme["*.pyd"]["sha256"]
        self.assertTrue(any(k.startswith("_imaging.") for k in pyd), "Pillow _imaging*.pyd ni pripet")
        self.assertIn("codeccontext.pyd", pyd)

    def test_ci_preveri_kodek_v_zgrajenem_paketu(self):
        ci = (KOREN / ".github" / "workflows" / "windows-package.yml").read_text(encoding="utf-8")
        self.assertIn("build_windows.py kodek-frozen", ci)
        self.assertIn('"--preveri-kodek"', (WIN / "safeer_windows" / "os_app.py").read_text(encoding="utf-8"))
        self.assertIn('"kodek-frozen"', (WIN / "build_windows.py").read_text(encoding="utf-8"))


class PreveriKodek(unittest.TestCase):
    def test_brez_pyav_porocilo_pove_in_ni_ok(self):
        with tempfile.TemporaryDirectory() as mapa, mock.patch.dict(sys.modules, {"av": None}):
            pot = Path(mapa) / "kodek.json"
            izid = preveri_kodek.preveri(str(pot))
            zapisano = json.loads(pot.read_text(encoding="utf-8"))
        self.assertFalse(izid["ok"])
        self.assertFalse(izid["koraki"]["pyav"]["ok"])
        self.assertNotIn("zajem", izid["koraki"])
        self.assertEqual(zapisano, izid)

    def test_brez_pillow_ni_ok(self):
        with mock.patch.dict(sys.modules, {"PIL": None, "av": None}):
            izid = preveri_kodek.preveri("")
        self.assertFalse(izid["koraki"]["pillow"]["ok"])
        self.assertFalse(izid["ok"])


if __name__ == "__main__":
    unittest.main()
