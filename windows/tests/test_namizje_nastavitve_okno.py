"""Namizje QML po povratni informaciji lastnika (25. 10. 2026):

- desni klik -> »Nastavitve sistema« odpre okno Nastavitve Safeer OS (samo ta razdelek, brez stranske vrstice in glave
  cele lupine, kot na Linuxu), ne celega glavnega okna, ki je spominjalo na staro aplikacijo Safeer Link;
- »O tem racunalniku« (strojna in programska oprema, diski s prostim prostorom) na namizju in na vrhu Nastavitev;
- varnostna vrata: en klik / bliznjica nazaj na obicajno namizje Windows, samodejno po sesutjih ob zagonu.
"""
import json
import os
import re
import sys
import unittest

KOREN = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, KOREN)
sys.path.insert(0, os.path.join(KOREN, "windows"))

from safeer_windows import okno_razdelka, varnostna_vrata  # noqa: E402

SW = os.path.join(KOREN, "windows", "safeer_windows")
JEZIKI = ("sl", "en", "de", "es", "fr", "it")


def beri(*pot):
    with open(os.path.join(*pot), encoding="utf-8") as f:
        return f.read()


class OknoRazdelka(unittest.TestCase):
    def test_kateri_razdelki_v_svojem_oknu(self):
        self.assertEqual(okno_razdelka.okno_za("nastavitve"), ("nastavitve", "nastavitve"))
        self.assertEqual(okno_razdelka.okno_za("nastavitve#blokScit"), ("nastavitve", "nastavitve#blokScit"))
        self.assertEqual(okno_razdelka.okno_za("omrezje"), ("nastavitve", "omrezje"))
        self.assertEqual(okno_razdelka.okno_za("vodnik"), ("nastavitve", "nastavitve"))
        self.assertEqual(okno_razdelka.okno_za("naprave"), ("naprave", "naprave"))
        self.assertEqual(okno_razdelka.okno_za("zapisek:abc"), ("zapiski", "zapisek:abc"))
        self.assertEqual(okno_razdelka.okno_za("pogovor:k1:p1"), ("sporocila", "pogovor:k1:p1"))
        for ostane in ("media", "splet", "datoteke", "control", "", "domov"):
            self.assertEqual(okno_razdelka.okno_za(ostane)[0], "", ostane)

    def test_stran_in_naslov(self):
        self.assertEqual(okno_razdelka.naslov_strani("nastavitve", "sl"), "os/index.html?razdelek=nastavitve&jezik=sl")
        self.assertEqual(okno_razdelka.naslov_strani("naprave", "xx"), "os/index.html?razdelek=naprave&jezik=en")
        for j in JEZIKI:
            for ime in okno_razdelka.RAZDELKI_V_OKNU:
                self.assertTrue(okno_razdelka.naslov_okna(ime, j))
        self.assertEqual(okno_razdelka.naslov_okna("nastavitve", "sl"), "Nastavitve Safeer OS")

    def test_os_js_pozna_iste_razdelke(self):
        js = beri(KOREN, "assets", "os", "os.js")
        m = re.search(r"\[\?&\]razdelek=\(([a-z|]+)\)", js)
        self.assertIsNotNone(m)
        self.assertEqual(set(m.group(1).split("|")), set(okno_razdelka.RAZDELKI_V_OKNU))
        self.assertIn('document.body.classList.add("en-razdelek", "razdelek-" + RAZDELEK)', js)
        self.assertIn('if (!vTemOknu(osnova)) { klic("odpriRazdelek", [razdelek]); return; }', js)
        css = beri(KOREN, "assets", "os", "os.css")
        self.assertIn("body.en-razdelek #stranska", css)
        self.assertIn("body.en-razdelek #vrh", css)

    def test_namizje_odpre_okno_razdelka_ne_glavnega_okna(self):
        for ime in ("namizje_qml.py", "namizje_win.py"):
            koda = beri(SW, ime)
            self.assertIn("self.os_okno.odpri_razdelek_namizja(razdelek)", koda, ime)
            self.assertNotIn("lambda: self.os_okno.prebudi(razdelek)", koda, ime)
        app = beri(SW, "os_app.py")
        self.assertIn("okno_razdelka.odpri(self, razdelek, SafeerOsPage, most_js, _jezik_oken())", app)
        qml = beri(SW, "qml", "Namizje.qml")
        self.assertIn('text: koren.t("nastavitveSistema")', qml)
        self.assertIn('onTriggered: koren.klic("odpriRazdelek", ["nastavitve"])', qml)


class ORacunalniku(unittest.TestCase):
    def test_na_vrhu_nastavitev(self):
        html = beri(KOREN, "assets", "os", "index.html")
        r = html.index('id="r-nastavitve"')
        self.assertLess(html.index('id="blokORacunalniku"', r), html.index('data-t="temaNaslov"', r))
        self.assertEqual(html.count('id="oRacunalniku"'), 1)

    def test_namizje_ima_o_tem_racunalniku_in_diske(self):
        qml = beri(SW, "qml", "Namizje.qml")
        self.assertIn("ORacunalniku { id: oRacunalniku", qml)
        self.assertIn("onTriggered: oRacunalniku.odpri()", qml)
        o = beri(SW, "qml", "ORacunalniku.qml")
        self.assertIn('koren.klic("sistemPodatki"', o)
        self.assertIn("malo_prostora", o)
        nq = beri(SW, "namizje_qml.py")
        self.assertIn('if metoda == "diskiNamizja":', nq)
        self.assertIn("sistem_podatki.diski()", nq)

    def test_nova_besedila_v_vseh_jezikih(self):
        qml = beri(SW, "qml", "Namizje.qml")
        uporabljeni = set()
        for ime in ("Namizje.qml", "Datoteke.qml", "ORacunalniku.qml"):
            uporabljeni |= set(re.findall(r'koren\.t\("(\w+)"', beri(SW, "qml", ime)))
        novi = ("diski", "diskSistem", "diskProsto", "diskMalo", "poImenu", "poDatumu", "poVelikosti", "datumNastanka",
                "vseObdobje", "danes", "taTeden", "taMesec", "letos", "izberiObdobje", "od", "do", "uporabi",
                "obdobjeNapaka", "pogledSeznam", "pogledMreza", "fotografijeNaprave", "naloziVec", "nastanek",
                "niVObdobju", "oRacunalniku", "oRacunalnikuMeni", "racRacunalnik", "racSistem", "racJedro",
                "racProcesor", "racJeder", "racPomnilnik", "racPomnilnikVr", "racGraficna", "racCas", "racMin",
                "racUr", "racDni", "racSafeer", "vseNastavitve", "nastavitveSistema", "razvrsti", "obicajnoNamizje")
        for k in novi:
            self.assertEqual(len(re.findall(r"[{ ,]%s: \"" % k, qml)), 6, k)
        # Vsak kljuc, ki ga QML uporabi, je vsaj v anglescini (t() pade na en).
        en = qml[qml.index("        en: {"):qml.index("        de: {")]
        for k in uporabljeni:
            self.assertRegex(en, r"[{ ,]%s: \"" % k, k)
        self.assertIn("koren.jezik = koren.besedila[z.jezik] ? z.jezik : \"en\"", qml)


class VarnostnaVrata(unittest.TestCase):
    def test_po_sesutjih_obicajno_namizje(self):
        z, t = {}, 1000.0
        for i in range(varnostna_vrata.NAJVEC_ZAGONOV):
            pokazi, z = varnostna_vrata.ob_zagonu(z, t + i)
            self.assertTrue(pokazi)
        pokazi, z = varnostna_vrata.ob_zagonu(z, t + 10)
        self.assertFalse(pokazi)
        self.assertEqual(z["razlog"], "sesutja")
        # Po izklopu se steje znova (vklop v Nastavitvah da namizju novo priloznost).
        self.assertTrue(varnostna_vrata.ob_zagonu(z, t + 20)[0])

    def test_stabilen_zagon_pocisti_in_stari_zagoni_ne_stejejo(self):
        z = {"zacetki": [1.0, 2.0]}
        self.assertEqual(varnostna_vrata.stabilno(z), {"zacetki": []})
        pokazi, z2 = varnostna_vrata.ob_zagonu({"zacetki": [0.0, 1.0, 2.0]}, 2.0 + varnostna_vrata.OKNO_S + 5)
        self.assertTrue(pokazi)
        self.assertEqual(len(z2["zacetki"]), 1)
        self.assertTrue(varnostna_vrata.ob_zagonu({"zacetki": ["x", None]}, 5.0)[0])

    def test_vrata_so_povezana(self):
        app = beri(SW, "os_app.py")
        self.assertIn("window.zacni_varnostna_vrata()", app)
        self.assertIn("window.zacni_namizje_ob_zagonu()", app)
        self.assertIn("if not self.namizje.nalozeno():", app)
        qml = beri(SW, "qml", "Namizje.qml")
        self.assertIn('onTriggered: koren.klic("namizjeSafeer", [false])', qml)
        self.assertIn("Ctrl+Alt+Shift+W", qml)
        self.assertEqual(varnostna_vrata.BLIZNJICA, "Ctrl+Alt+Shift+W")
        if sys.platform != "win32":
            self.assertFalse(varnostna_vrata.zazeni_bliznjico(lambda: None))


class NalaganjeQml(unittest.TestCase):
    """Namizje se nalozi brez napak QML (z laznim mostom), tudi novi paneli."""

    def test_namizje_brez_napak(self):
        try:
            from PySide6.QtCore import QObject, Signal, Slot, QUrl
            from PySide6.QtQuick import QQuickView
        except ImportError:
            self.skipTest("brez QtQuick")
        if not os.environ.get("QT_QPA_PLATFORM"):
            os.environ["QT_QPA_PLATFORM"] = "offscreen"

        class Most(QObject):
            odgovor = Signal(int, bool, str)
            dogodek = Signal(str, str)

            @Slot(str, str, result=int)
            def klic(self, m, a):
                return 1

            @Slot(str, result=str)
            def datotekaUrl(self, p):
                return ""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])     # QApplication: drugi preizkusi rabijo pripomocke
        v = QQuickView()
        most = Most()
        v.rootContext().setContextProperty("Most", most)
        v.setSource(QUrl.fromLocalFile(os.path.join(SW, "qml", "Namizje.qml")))
        napake = [e.toString() for e in v.errors()]
        self.assertEqual(napake, [])
        self.assertIsNotNone(v.rootObject())
        self.assertIsNotNone(app)


if __name__ == "__main__":
    unittest.main()
