"""Popravki po neodvisnem pregledu a954e32..4f85c34 (25. 10. 2026): varnostna vrata iz niti bliznjice (V2), slicice
brez Pillow (V1), stevec zavrnjenih slicic (S3), ffmpeg (S6, N4), HEAD /thumb (N7), skrito okno razdelka (S7),
navigacija oken Safeer OS, besedila QML v vseh jezikih in preverjanje QML za CI (V1).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

KOREN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KOREN))
sys.path.insert(0, str(KOREN / "windows"))

from core import link_datoteke, link_hub_streznik  # noqa: E402
from safeer_windows import slicice_win, varnostna_vrata as vv  # noqa: E402

WIN = KOREN / "windows" / "safeer_windows"


class VarnostnaVrataIzNitiBliznjice(unittest.TestCase):
    def test_glavna_nit_odgovori(self):
        zapisano, koncano = [], []

        def v_glavno(potrdi):
            threading.Thread(target=potrdi).start()
        self.assertTrue(vv.vrata(lambda: zapisano.append(1), v_glavno, koncaj=lambda: koncano.append(1), cakaj_s=2))
        self.assertEqual((zapisano, koncano), ([1], []))

    def test_glavna_nit_visi_proces_se_konca(self):
        zapisano, koncano = [], []
        zacetek = time.monotonic()
        self.assertFalse(vv.vrata(lambda: zapisano.append(1), lambda potrdi: None,
                                  koncaj=lambda: koncano.append(1), cakaj_s=0.2))
        self.assertEqual((zapisano, koncano), ([1], [1]))
        self.assertLess(time.monotonic() - zacetek, 2)

    def test_zapis_najprej_tudi_ce_spodleti(self):
        vrstni_red = []

        def zapisi():
            vrstni_red.append("zapis")
            raise OSError("disk")

        def v_glavno(potrdi):
            vrstni_red.append("glavna")
            potrdi()
        self.assertTrue(vv.vrata(zapisi, v_glavno, koncaj=lambda: vrstni_red.append("konec"), cakaj_s=1))
        self.assertEqual(vrstni_red, ["zapis", "glavna"])

    def test_os_app_uporabi_vrata_in_zapise_brez_glavne_niti(self):
        izvor = (WIN / "os_app.py").read_text(encoding="utf-8")
        telo = izvor.split("def zacni_varnostna_vrata", 1)[1].split("\n    def ", 1)[0]
        self.assertIn("vv.vrata(zapisi, v_glavno)", telo)
        self.assertIn('s["namizje"] = False', telo)
        self.assertIn("os_backend_win.shrani_shrambo(s)", telo)
        self.assertNotIn("self.nastavi_namizje(False)", telo)          # ta gre skozi glavno nit

    def test_cist_izhod_in_razlog(self):
        izvor = (WIN / "os_app.py").read_text(encoding="utf-8")
        pocisti = izvor.split("def _pocisti", 1)[1].split("\n    def ", 1)[0]
        self.assertIn("vv.pisi(vv.stabilno(vv.beri()))", pocisti)
        self.assertIn('"namizjeRazlog": self._razlog_izklopa_namizja()', izvor)
        self.assertIn('"bliznjice": self._stanje_bliznjic()', izvor)
        pokazi = izvor.split("def pokazi_namizje", 1)[1].split("\n    def ", 1)[0]
        self.assertIn("except Exception as e:", pokazi)                  # S4: napaka ob ustvarjanju namizja
        self.assertIn('razlog="nalaganje"', pokazi)

    def test_razlog_ostane_po_stabilnem_zagonu(self):
        self.assertEqual(vv.stabilno({"zacetki": [1.0], "razlog": "sesutja", "izklopljeno_ob": 5.0}),
                         {"zacetki": [], "razlog": "sesutja", "izklopljeno_ob": 5.0})


class Slicice(unittest.TestCase):
    def setUp(self):
        with link_datoteke._slicice_kljuc:
            link_datoteke._slicice.clear()
            link_datoteke._brez_slicice.clear()

    def test_ffmpeg_samo_datoteke_in_meja_obeh_stranic(self):
        ukaz = link_datoteke.ukaz_slicice_videa("ffmpeg", "v.mp4", "3", 256)
        i = ukaz.index("-protocol_whitelist")
        self.assertEqual(ukaz[i + 1], "file")
        self.assertLess(i, ukaz.index("-i"))                             # velja za vhod
        self.assertIn("scale=256:256:force_original_aspect_ratio=decrease", ukaz)

    def test_rezerva_brez_pillow(self):
        with tempfile.TemporaryDirectory() as mapa:
            pot = os.path.join(mapa, "a.jpg")
            Path(pot).write_bytes(b"\xff\xd8 ni prava slika")
            klici = []
            with mock.patch.dict(sys.modules, {"PIL": None}), \
                    mock.patch.object(link_datoteke, "REZERVA_SLIKE", lambda p, r: klici.append((p, r)) or b"JPEG"):
                self.assertEqual(link_datoteke._slicica_slike(pot, 256), b"JPEG")
            self.assertEqual(klici, [(pot, 256)])
            with mock.patch.dict(sys.modules, {"PIL": None}), mock.patch.object(link_datoteke, "REZERVA_SLIKE", None):
                self.assertIsNone(link_datoteke._slicica_slike(pot, 256))   # Linux brez Pillow: kot prej

    def test_neuspela_slicica_se_ne_dela_znova(self):
        with tempfile.TemporaryDirectory() as mapa:
            pot = os.path.join(mapa, "v.mp4")
            Path(pot).write_bytes(b"x" * 100)
            with mock.patch.object(link_datoteke, "_slicica_videa", return_value=None) as video:
                self.assertIsNone(link_datoteke.naredi_slicico(pot))
                self.assertIsNone(link_datoteke.naredi_slicico(pot))
            self.assertEqual(video.call_count, 1)

    def test_ffmpeg_prek_kljuke_platforme(self):
        with tempfile.TemporaryDirectory() as mapa:
            pot = os.path.join(mapa, "v.mp4")
            Path(pot).write_bytes(b"x")
            ukazi = []
            with mock.patch.object(link_datoteke, "ZAZENI_FFMPEG", lambda u, rok: ukazi.append((u, rok)) or (0, b"j" * 300)), \
                    mock.patch.object(link_datoteke.shutil, "which", return_value="ffmpeg"):
                self.assertEqual(link_datoteke._slicica_videa(pot, 256), b"j" * 300)
            self.assertEqual(ukazi[0][1], 15)
            self.assertIn("-protocol_whitelist", ukazi[0][0])

    def test_zazeni_v_poslu(self):
        self.assertEqual(slicice_win.zazeni_v_poslu([sys.executable, "-c", "print('ok')"], 30)[0], 0)
        zacetek = time.monotonic()
        koda, izhod = slicice_win.zazeni_v_poslu([sys.executable, "-c", "import time; time.sleep(30)"], 0.5)
        self.assertEqual((koda, izhod), (-1, b""))
        self.assertLess(time.monotonic() - zacetek, 10)

    def test_stare_zacasne_datoteke_se_pocistijo(self):
        with tempfile.TemporaryDirectory() as mapa, mock.patch.dict(os.environ, {"LOCALAPPDATA": mapa}):
            m = slicice_win.mapa()
            stara, nova = os.path.join(m, "a.jpg.1.tmp"), os.path.join(m, "b.jpg.2.tmp")
            for p in (stara, nova):
                Path(p).write_bytes(b"x")
            os.utime(stara, (time.time() - 7200, time.time() - 7200))
            slicice_win.pocisti()
            self.assertEqual((os.path.exists(stara), os.path.exists(nova)), (False, True))

    def test_windows_nastavi_kljuki_streznika(self):
        izvor = (WIN / "control_backend.py").read_text(encoding="utf-8")
        self.assertIn("link_datoteke.REZERVA_SLIKE = slicice_win.slika_qt", izvor)
        self.assertIn("link_datoteke.ZAZENI_FFMPEG = slicice_win.zazeni_v_poslu", izvor)

    def test_slika_qt(self):
        try:
            from PySide6.QtGui import QColor, QImage
            from PySide6.QtWidgets import QApplication
        except ImportError:
            self.skipTest("PySide6 ni na voljo")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as mapa:
            pot = os.path.join(mapa, "a.png")
            slika = QImage(1600, 900, QImage.Format.Format_RGB32)
            slika.fill(QColor(200, 80, 40))
            self.assertTrue(slika.save(pot))
            jpeg = slicice_win.slika_qt(pot, 256)
            self.assertTrue(jpeg and jpeg[:2] == b"\xff\xd8")
            nazaj = QImage.fromData(jpeg)
            self.assertLessEqual(max(nazaj.width(), nazaj.height()), 256)
            self.assertIsNone(slicice_win.slika_qt(os.path.join(mapa, "ni.png"), 256))


class ZavrnjeneSlicice(unittest.TestCase):
    def test_en_dogodek_na_vir_na_rok(self):
        link_hub_streznik._zavrnjene_slicice.clear()
        self.assertTrue(link_hub_streznik._steje_zavrnjeno_slicico("10.0.0.5", 100.0))
        for i in range(50):                                              # mreza slicic z zastarelim zetonom
            self.assertFalse(link_hub_streznik._steje_zavrnjeno_slicico("10.0.0.5", 100.0 + i * 0.1))
        self.assertTrue(link_hub_streznik._steje_zavrnjeno_slicico("10.0.0.6", 101.0))
        self.assertTrue(link_hub_streznik._steje_zavrnjeno_slicico("10.0.0.5", 100.0 + link_hub_streznik.ROK_SLICIC_S))

    def test_samo_slicice(self):
        izvor = (KOREN / "core" / "link_hub_streznik.py").read_text(encoding="utf-8")
        self.assertIn("elif not pot.startswith(POT_SLICICE) or _steje_zavrnjeno_slicico(self._vir()):", izvor)


class HeadSlicice(unittest.TestCase):
    def test_head_brez_izdelave(self):
        poslano = []
        obravnava = types.SimpleNamespace(headers={"X-Safeer-Token": "z"}, send_response=poslano.append,
                                          send_header=lambda *a: None, end_headers=lambda: None)
        with tempfile.TemporaryDirectory() as mapa:
            video, dok = os.path.join(mapa, "v.mp4"), os.path.join(mapa, "d.pdf")
            for p in (video, dok):
                Path(p).write_bytes(b"x")
            streznik = types.SimpleNamespace(zeton_velja=lambda z: z == "z",
                                             mape=types.SimpleNamespace(razresi=lambda o: ("x", {"v": video, "d": dok}[o])))
            with mock.patch.object(link_datoteke, "naredi_slicico") as naredi:
                link_datoteke.postrezi_slicico(obravnava, streznik, "v", True)
                link_datoteke.postrezi_slicico(obravnava, streznik, "d", True)
            naredi.assert_not_called()
        self.assertEqual(poslano, [200, 404])


class OknoRazdelka(unittest.TestCase):
    def _okno(self, vidno, stanje, ime="nastavitve"):
        try:
            from PySide6.QtWebEngineCore import QWebEnginePage
        except ImportError:
            self.skipTest("QtWebEngine ni na voljo")
        from safeer_windows import okno_razdelka
        Lc = QWebEnginePage.LifecycleState
        nastavljeno = []
        stran = types.SimpleNamespace(lifecycleState=lambda: stanje[0],
                                      setLifecycleState=lambda s: (nastavljeno.append(s), stanje.__setitem__(0, s)))
        okno = types.SimpleNamespace(ime=ime, page_obj=stran, isVisible=lambda: vidno, _nalozeno=True,
                                     _zavrzi=types.SimpleNamespace(stop=lambda: None))
        return okno_razdelka.OknoRazdelka._v_stanje, okno, nastavljeno, Lc

    def test_skrito_zamrzne_in_zavrze(self):
        stanje = [None]
        v_stanje, okno, nastavljeno, Lc = self._okno(False, stanje)
        stanje[0] = Lc.Active
        v_stanje(okno, "zamrznjena")
        v_stanje(okno, "zavrzena")
        self.assertEqual(nastavljeno, [Lc.Frozen, Lc.Discarded])
        v_stanje(okno, "aktivna")
        self.assertEqual(nastavljeno[-1], Lc.Active)
        self.assertFalse(okno._nalozeno)                                 # cilj pocaka na ponovno nalaganje

    def test_vidno_in_zapiski_ostanejo(self):
        stanje = [None]
        v_stanje, okno, nastavljeno, Lc = self._okno(True, stanje)
        stanje[0] = Lc.Active
        v_stanje(okno, "zamrznjena")
        self.assertEqual(nastavljeno, [])
        v_stanje, okno, nastavljeno, Lc = self._okno(False, stanje, ime="zapiski")
        v_stanje(okno, "zavrzena")
        self.assertEqual(nastavljeno, [])                                # nezapisan zapisek ostane


class Navigacija(unittest.TestCase):
    def test_samo_lokalni_vmesnik_na_svojih_vratih(self):
        try:
            from safeer_windows.os_app import dovoljena_navigacija_vmesnika as d
        except ImportError as e:
            self.skipTest(f"os_app: {e}")
        self.assertTrue(d("http://127.0.0.1:5123/os/index.html?razdelek=nastavitve", 5123))
        for slab in ("http://127.0.0.1:5124/os/index.html", "http://127.0.0.1:5123/ozadja/a.jpg",
                     "https://tuja.stran/assets/os/index.html", "file:///C:/assets/os/index.html",
                     "http://127.0.0.1:5123@tuja.stran/os/", "http://localhost:5123/os/", "javascript:alert(1)"):
            self.assertFalse(d(slab, 5123), slab)
        self.assertFalse(d("http://127.0.0.1:5123/os/", None))


class BesedilaQml(unittest.TestCase):
    def _jeziki(self):
        izvor = (WIN / "qml" / "Namizje.qml").read_text(encoding="utf-8")
        blok = izvor.split("readonly property var besedila: ({", 1)[1].split("\n    })", 1)[0]
        deli = re.split(r"\n\s+(sl|en|de|es|fr|it): \{", "\n" + blok)
        return {deli[i]: set(re.findall(r"(\w+): \"", deli[i + 1])) for i in range(1, len(deli), 2)}

    def test_vsi_jeziki_imajo_vse_kljuce(self):
        jeziki = self._jeziki()
        self.assertEqual(set(jeziki), {"sl", "en", "de", "es", "fr", "it"})
        for j in ("sl", "de", "es", "fr", "it"):
            self.assertEqual(jeziki["en"] - jeziki[j], set(), j)

    def test_nemska_bliznjica(self):
        izvor = (WIN / "qml" / "Namizje.qml").read_text(encoding="utf-8")
        self.assertIn('bliznjicaVrata: "Strg+Alt+Umschalt+W"', izvor)
        self.assertIn('koren.bliznjice.varnostna === false', izvor)   # zasedena bliznjica se ne oglasuje

    def test_os_js_razlog_v_vseh_jezikih(self):
        izvor = (KOREN / "assets" / "os" / "os.js").read_text(encoding="utf-8")
        blok = izvor.split("var BESEDILA_VRATA = {", 1)[1].split("\n  };", 1)[0]
        for j in ("sl", "en", "de", "es", "fr", "it"):
            vrstica = re.search(r"\n    %s: \{(.*)\}" % j, blok).group(1)
            for k in ("namizjeRazlog_sesutja", "namizjeRazlog_nalaganje", "namizjeRazlog_bliznjica", "bliznjicaVrataNi"):
                self.assertIn(k + ":", vrstica, (j, k))
        self.assertIn("Strg+Alt+Umschalt+W", blok)


class PreverjanjeQml(unittest.TestCase):
    def _zazeni(self, qml):
        koda = ("import sys; from pathlib import Path; from safeer_windows import namizje_qml as n; "
                "n.QML = Path(sys.argv[1]); sys.exit(n.preveri_nalaganje(sys.argv[2]))")
        with tempfile.TemporaryDirectory() as mapa:
            porocilo = os.path.join(mapa, "qml.json")
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
                       PYTHONPATH=os.pathsep.join([str(KOREN / "windows"), str(KOREN)]))
            r = subprocess.run([sys.executable, "-c", koda, str(qml), porocilo], env=env, timeout=120,
                               capture_output=True)
            podatki = json.loads(Path(porocilo).read_text(encoding="utf-8")) if os.path.exists(porocilo) else {}
            return r.returncode, podatki

    def setUp(self):
        try:
            import PySide6.QtQuick  # noqa: F401
        except ImportError:
            self.skipTest("PySide6 ni na voljo")

    def test_namizje_se_nalozi(self):
        koda, podatki = self._zazeni(WIN / "qml" / "Namizje.qml")
        self.assertEqual((koda, podatki.get("ok"), podatki.get("napake")), (0, True, []))

    def test_napaka_qml_pade(self):
        with tempfile.TemporaryDirectory() as mapa:
            slab = Path(mapa) / "Namizje.qml"
            slab.write_text("import QtQuick\nimport NiTakegaModula 1.0\nItem {}\n", encoding="utf-8")
            koda, podatki = self._zazeni(slab)
        self.assertEqual((koda, podatki.get("ok")), (1, False))
        self.assertTrue(any("NiTakegaModula" in n for n in podatki.get("napake", [])))

    def test_ci_in_zastavica(self):
        self.assertIn("qml-frozen", (KOREN / ".github" / "workflows" / "windows-package.yml").read_text(encoding="utf-8"))
        self.assertIn('"--preveri-qml"', (WIN / "os_app.py").read_text(encoding="utf-8"))


class Paket(unittest.TestCase):
    def test_qml_in_obrezovanje(self):
        sys.path.insert(0, str(KOREN / "windows"))
        import build_windows as b
        self.assertIn(("windows/safeer_windows/qml", "safeer_windows/qml"), b.SHARED_DATA)
        for modul in ("QtQml", "QtQuick", "QtQuick.Controls.Basic", "QtQuick.Templates", "QtQuick.Layouts",
                      "QtQuick.Effects", "QtQuick.Dialogs", "Qt.labs.folderlistmodel",
                      # Uvozi jih prevedeni QML sloga Basic (TextField), qmldir ne (CI 40204237696, 25. 10. 2026).
                      "QtQuick.Controls.Basic.impl", "QtQuick.Shapes"):
            self.assertIn(modul, b.QML_KORENI)
        self.assertEqual(b.qmldir_odvisnosti("module QtQuick.Controls.Basic\nimport QtQuick.Controls.impl auto\n"
                                             "depends QtQuick.Templates\noptional import QtQuick.Controls.Fusion\n"),
                         ["QtQuick.Controls.impl", "QtQuick.Templates"])


if __name__ == "__main__":
    unittest.main()
