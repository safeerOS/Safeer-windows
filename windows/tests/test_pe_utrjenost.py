"""Utrjenost datotek PE v paketu Windows (ustreznica readelf, lastnik 21. 10. 2026; korak CI 25. 10. 2026).

ASLR, DEP in HEVA mora imeti vsaka datoteka; nasi programi se CFG, /GS in CET; tuja knjiznica brez katere od teh samo z
zapisano izjemo in razlogom (windows/tools/pe_izjeme.json). Manjkajoca zascita brez izjeme ustavi gradnjo."""
import json
import os
import sys
import unittest
from pathlib import Path

KOREN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KOREN / "windows" / "tools"))

import pe_utrjenost as pe  # noqa: E402

IZJEME = json.loads((KOREN / "windows" / "tools" / "pe_izjeme.json").read_text(encoding="utf-8"))["izjeme"]
POPOLNO = {"x64": True, "ASLR": True, "HEVA": True, "DEP": True, "CFG": True, "GS": True, "CET": True}


class Odlocitev(unittest.TestCase):
    def test_nas_program_brez_cfg_ustavi_gradnjo(self):
        napake, _ = pe.odlocitev("SafeerNovo.exe", dict(POPOLNO, CFG=False), False, IZJEME)
        self.assertEqual(napake, ["CFG"])                           # tuja: CFG brez izjeme
        napake, izjeme = pe.odlocitev("SafeerBrowser.exe", dict(POPOLNO, CFG=False), False, IZJEME)
        self.assertEqual(napake, ["CFG"])                           # nas: izjema dovoli samo CET
        napake, izjeme = pe.odlocitev("SafeerBrowser.exe", dict(POPOLNO, CET=False), False, IZJEME)
        self.assertEqual((napake, izjeme[0]["manjka"]), ([], ["CET"]))
        self.assertTrue(izjeme[0]["razlog"])

    def test_aslr_dep_heva_nikoli_izjema(self):
        for z in ("ASLR", "DEP", "HEVA"):
            napake, _ = pe.odlocitev("python3.dll", dict(POPOLNO, **{z: False}), False, IZJEME)
            self.assertIn(z, napake)
        napake, _ = pe.odlocitev("SafeerOS.exe", dict(POPOLNO, ASLR=False), True, IZJEME)
        self.assertEqual(napake, ["ASLR"])                          # tudi Go mora imeti ASLR
        napake, _ = pe.odlocitev("star32.exe", dict(POPOLNO, x64=False, HEVA=False), False, IZJEME)
        self.assertEqual(napake, [])                                # HEVA samo za 64-bitne

    def test_tuje_z_izjemo_in_potjo(self):
        izid = dict(POPOLNO, CFG=False, GS=False, CET=False)
        pot = "SafeerBrowser/_internal/av.libs/avcodec-62-abc.dll"
        napake, izjeme = pe.odlocitev("avcodec-62-abc.dll", izid, False, IZJEME, pot)
        self.assertEqual(napake, [])
        self.assertIn("MinGW", izjeme[0]["razlog"])
        napake, _ = pe.odlocitev("avcodec-62-abc.dll", izid, False, IZJEME, pot.replace("av.libs", "drugje"))
        self.assertEqual(sorted(napake), ["CET", "CFG", "GS"])     # zunaj av.libs ni izjeme

    def test_go_razlog(self):
        napake, izjeme = pe.odlocitev("SafeerOS.exe", dict(POPOLNO, CFG=False, GS=False, CET=False), True, IZJEME)
        self.assertEqual(napake, [])
        self.assertIn("Go", izjeme[0]["razlog"])


class DatotekeVRepozitoriju(unittest.TestCase):
    """Programi v repozitoriju (namestitev iz izvorne kode): izmerjeno 25. 10. 2026."""

    def test_zaganjalnik_in_webview2(self):
        poti = [str(KOREN / "windows" / ime) for ime in ("SafeerOS.exe", "SafeerControl.exe", "SafeerMediaWebView.exe")]
        if not all(os.path.isfile(p) for p in poti):
            self.skipTest("programov ni v tej kopiji")
        porocilo, napak = pe.preveri(poti, IZJEME)
        self.assertEqual(napak, 0, porocilo)
        wv = porocilo[poti[2]]
        self.assertTrue(all(wv[z] for z in ("ASLR", "HEVA", "DEP", "CFG", "GS")))
        self.assertTrue(porocilo[poti[0]]["go"])

    def test_korak_v_ci(self):
        ci = (KOREN / ".github" / "workflows" / "windows-package.yml").read_text(encoding="utf-8")
        self.assertIn("windows/tools/pe_utrjenost.py build/windows/dist", ci)
        self.assertIn("--preveri", ci)


if __name__ == "__main__":
    unittest.main()
