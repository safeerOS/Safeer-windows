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
        # Samostojni predvajalnik (naloga 13) se zgradi in preveri v CI.
        self.assertIn("windows/SafeerPredvajalnik.spec", ci)
        self.assertIn("pe_utrjenost.py build/predvajalnik/dist --preveri", ci)
        self.assertTrue(IZJEME["safeerpredvajalnik.exe"].get("rok"))
        self.assertIn("--preveri", ci)



class PripetaIzjema(unittest.TestCase):
    """Tuja knjiznica brez CFG/CET (FFmpeg v PySide6, OpenBLAS v numpy): izjema velja samo za pripeto SHA-256 - nova
    razlicica ustavi gradnjo in v dnevniku pove vsoto (CI 40200508307, 25. 10. 2026)."""
    BREZ = dict(POPOLNO, CFG=False, CET=False)

    def test_libmpv_nasa_gradnja_z_rokom_in_vsoto(self):
        """libmpv gradimo sami (milutv-libmpv): izjema za CFG/CET samo z rokom IN pripeto vsoto (25. 10. 2026)."""
        izj = IZJEME["libmpv-2.dll"]
        pot = "SafeerBrowser\\_internal\\safeer_windows\\vendor\\mpv\\libmpv-2.dll"
        napake, izjeme = pe.odlocitev("libmpv-2.dll", self.BREZ, False, IZJEME, pot,
                                      sha=lambda: izj["sha256"]["libmpv-2.dll"], danes="2026-10-25")
        self.assertEqual((napake, izjeme[0]["manjka"], izjeme[0]["rok"]), ([], ["CFG", "CET"], "2026-12-31"))
        napake, _ = pe.odlocitev("libmpv-2.dll", self.BREZ, False, IZJEME, pot, sha=lambda: "ab" * 32,
                                 danes="2026-10-25")
        self.assertIn("ab" * 32, napake[-1])                      # nova vsota je v dnevniku CI
        napake, _ = pe.odlocitev("libmpv-2.dll", self.BREZ, False, IZJEME, pot,
                                 sha=lambda: izj["sha256"]["libmpv-2.dll"], danes="2027-01-01")
        self.assertIn("potekla", napake[-1])
        # FFmpeg iz PySide6 ni vec v paketu (build_windows.odstrani_ffmpeg_pyside): izjeme zanj ni.
        self.assertNotIn("*/pyside6/[as][vw]*.dll", IZJEME)

    def test_openblas_numpy(self):
        ime = "libscipy_openblas64_-ed4f167a5330424524f45258e7ca2c8d.dll"
        izj = IZJEME["*/numpy.libs/libscipy_openblas64_*.dll"]
        brez = dict(self.BREZ, GS=False)
        pot = "SafeerOS\\_internal\\numpy.libs\\" + ime
        napake, izjeme = pe.odlocitev(ime, brez, False, IZJEME, pot, sha=lambda: izj["sha256"][ime])
        self.assertEqual(napake, [])
        self.assertIn("dxcam", izjeme[0]["razlog"])
        napake, _ = pe.odlocitev(ime, brez, False, IZJEME, pot, sha=lambda: "00" * 32)
        self.assertTrue(napake and "ni pripeta" in napake[-1])

    def test_vsota_datoteke_samo_ko_jo_izjema_rabi(self):
        klici = []
        pe.odlocitev("Qt6Core.dll", dict(POPOLNO, CET=False), False, IZJEME, "x/Qt6Core.dll",
                     sha=lambda: klici.append(1) or "")
        pe.odlocitev("avcodec-61.dll", POPOLNO, False, IZJEME, "x/PySide6/avcodec-61.dll",
                     sha=lambda: klici.append(1) or "")
        self.assertEqual(klici, [])                                # brez pripete izjeme ali brez manjkajoce zascite



def _pe(odsek=b"", prekrivek=b""):
    """Najmanjsa datoteka PE32+ z enim odsekom (0x200-0x400) in poljubnim prekrivkom za njim."""
    import struct
    p = bytearray(0x400)
    p[0:2] = b"MZ"
    struct.pack_into("<I", p, 0x3C, 0x40)
    p[0x40:0x44] = b"PE\0\0"
    struct.pack_into("<HHH", p, 0x44, 0x8664, 1, 0)
    struct.pack_into("<H", p, 0x40 + 20, 0xF0)
    struct.pack_into("<H", p, 0x40 + 24, 0x20B)
    struct.pack_into("<IIII", p, 0x40 + 24 + 0xF0 + 8, 0x200, 0x1000, 0x200, 0x200)
    p[0x200:0x200 + len(odsek)] = odsek
    return bytes(p) + prekrivek


class PregledGrok(unittest.TestCase):
    """Pregled Grok 7 (25. 10. 2026): W14 izjema za nas program samo z rokom, W15 Go samo v odsekih, W16 PE po glavi,
    W17 izjema brez razloga."""

    def test_w14_nas_program_samo_z_rokom(self):
        brez_cet = dict(POPOLNO, CET=False)
        brez_roka = {"safeerbrowser.exe": {"dovoli": ["CET"], "razlog": "bootloader"}}
        napake, _ = pe.odlocitev("SafeerBrowser.exe", brez_cet, False, brez_roka)
        self.assertEqual(napake[0], "CET")
        self.assertIn("nima roka", napake[1])
        z_rokom = {"safeerbrowser.exe": {"dovoli": ["CET"], "razlog": "bootloader", "rok": "2026-12-31"}}
        napake, izjeme = pe.odlocitev("SafeerBrowser.exe", brez_cet, False, z_rokom, danes="2026-10-25")
        self.assertEqual((napake, izjeme[0]["rok"]), ([], "2026-12-31"))
        napake, _ = pe.odlocitev("SafeerBrowser.exe", brez_cet, False, z_rokom, danes="2027-01-01")
        self.assertIn("potekla", napake[-1])
        # Lastna razsiritev safeer_*.pyd ne gre skozi pod splosno izjemo *.pyd (W17).
        napake, _ = pe.odlocitev("safeer_x.pyd", dict(POPOLNO, CFG=False), False, IZJEME)
        self.assertIn("CFG", napake)
        # Vse izjeme za nase programe v pe_izjeme.json imajo rok.
        for ime in ("safeerbrowser.exe", "safeeros.exe", "safeercontrol.exe", "safeermediawebview.exe"):
            self.assertTrue(IZJEME[ime].get("rok"), ime)

    def test_w15_go_samo_v_odsekih(self):
        import tempfile
        with tempfile.TemporaryDirectory() as mapa:
            go = os.path.join(mapa, "go.exe")
            with open(go, "wb") as f:
                f.write(_pe(odsek=b"\xff Go buildinf:\x08\x02"))
            arhiv = os.path.join(mapa, "pyinst.exe")
            with open(arhiv, "wb") as f:
                f.write(_pe(prekrivek=b"MEI\x0c\x0b\n\x0b\x0e" + b"Go build ID: x" * 3))
            self.assertTrue(pe.je_go(go))
            self.assertFalse(pe.je_go(arhiv))                     # niz v arhivu PyInstaller ni program Go

    def test_w16_pe_po_glavi(self):
        import tempfile
        with tempfile.TemporaryDirectory() as mapa:
            for ime in ("kontrolnik.ocx", "brez_koncnice"):
                with open(os.path.join(mapa, ime), "wb") as f:
                    f.write(_pe())
            with open(os.path.join(mapa, "besedilo.txt"), "wb") as f:
                f.write(b"MZ to ni program")
            porocilo, _ = pe.preveri([mapa], IZJEME)
            self.assertEqual(sorted(os.path.basename(k) for k in porocilo), ["brez_koncnice", "kontrolnik.ocx"])
        ci = (KOREN / ".github" / "workflows" / "windows-package.yml").read_text(encoding="utf-8")
        self.assertIn("pe_utrjenost.py build/windows/out --porocilo", ci)   # namestitveni program (meritev)

    def test_w17_izjema_brez_razloga(self):
        self.assertEqual(pe.napake_izjem(IZJEME), [])
        self.assertTrue(pe.napake_izjem({"x.dll": {"dovoli": ["CFG"], "razlog": " "}}))
        self.assertTrue(pe.napake_izjem({"x.dll": {"razlog": "zakaj"}}))


if __name__ == "__main__":
    unittest.main()
