"""Prostori (Safeer Link Spaces) na Windows - port Linux MVP (Safeer-linux 6241c32): most os_app._prostori /
_prostor_odpri, navidezna namizja Windows (namizja_win.py), bliznjica Ctrl+Win+Tab, besedila v 6 jezikih, vmesnik v
oknu Safeer OS (os.js, index.html) in na namizju QML (Prostori.qml)."""
import json
import os
import re
import sys
import types
import unittest
import uuid
from unittest import mock

KOREN = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, KOREN)
sys.path.insert(0, os.path.join(KOREN, "windows"))

from core import link_prostori  # noqa: E402
from safeer_windows import namizja_win, varnostna_vrata  # noqa: E402

try:
    from safeer_windows import os_app
except Exception:  # pragma: no cover - brez QtWebEngine
    os_app = None

JEZIKI = ("sl", "en", "de", "es", "fr", "it")


def beri(*pot):
    with open(os.path.join(KOREN, *pot), encoding="utf-8") as f:
        return f.read()


class NavideznaNamizja(unittest.TestCase):
    def test_register(self):
        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        ids = a.bytes_le + b.bytes_le + c.bytes_le + b"\x01\x02"            # odvecni bajti se prezrejo
        namizja, tren = namizja_win.seznam_iz(ids, b.bytes_le, {"{%s}" % str(c).upper(): "Delo"}, "sl")
        self.assertEqual([n["ime"] for n in namizja], ["Namizje 1", "Namizje 2", "Delo"])
        self.assertEqual(tren, 1)
        self.assertTrue(namizja[1]["trenutno"])
        self.assertEqual(namizja_win.seznam_iz(None, None, {})[0], [])
        self.assertEqual(namizja_win.seznam_iz(ids, b"", {}, "en")[1], -1)

    def test_koraki_preklopa(self):
        self.assertEqual(namizja_win.koraki(0, 2), (namizja_win.VK_RIGHT, 2))
        self.assertEqual(namizja_win.koraki(3, 1), (namizja_win.VK_LEFT, 2))
        self.assertEqual(namizja_win.koraki(1, 1), (0, 0))
        self.assertEqual(namizja_win.koraki(-1, 1), (0, 0))

    def test_brez_windows(self):
        if sys.platform != "win32":
            self.assertEqual(namizja_win.seznam(), ([], -1))
            self.assertFalse(namizja_win.preklopi(1))


def _naprava(id_, ime, zm, platforma="", ozji=True, ta=False):
    return {"id": id_, "ime": ime, "zmoznosti": zm, "platforma": platforma, "vrsta": "", "ta": ta, "ozji": ozji}


@unittest.skipIf(os_app is None, "os_app se ne uvozi (brez QtWebEngine)")
class Most(unittest.TestCase):
    def setUp(self):
        self.shramba = {}
        self.cb = mock.Mock()
        self.cb.je_povezan.return_value = True
        self.cb.vse_naprave.return_value = [
            _naprava("pc-1-control", "Pisarna", ["desktop"], "windows"),
            _naprava("tel-1", "Samsung", ["zaslon.deli", "apps"], "phone"),
            _naprava("tuj", "Tuj", ["zaslon.deli"], "phone", ozji=False),
            _naprava("jaz", "Ta", ["desktop"], "windows", ta=True)]
        self.cb.odpri_tukaj.return_value = {"ok": True, "tu": True}
        self.okno = types.SimpleNamespace(control_backend=self.cb, dispatcher=mock.Mock())
        self.p = [mock.patch.object(os_app.os_backend_win, "nalozi_shrambo", side_effect=lambda: dict(self.shramba)),
                  mock.patch.object(os_app.os_backend_win, "shrani_shrambo",
                                    side_effect=lambda s: self.shramba.update(s) or True)]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()

    def test_prostori_samo_ozji_krog_in_zapis(self):
        r = os_app.SafeerOsWindow._prostori(self.okno)
        self.assertTrue(r["ok"])
        self.assertEqual(sorted(p["ime"] for p in r["prostori"]), ["Pisarna", "Samsung"])   # brez tujega in sebe
        self.assertEqual(len(self.shramba["prostori"]), 2)
        self.assertEqual(r["namizja"], [] if sys.platform != "win32" else r["namizja"])
        # Naprava odide iz Linka: ostane na svojem mestu, »ni povezana«.
        self.cb.vse_naprave.return_value = self.cb.vse_naprave.return_value[:1]
        r2 = os_app.SafeerOsWindow._prostori(self.okno)
        self.assertEqual([(p["ime"], p["povezana"]) for p in r2["prostori"]],
                         [(p["ime"], p["ime"] == "Pisarna") for p in r["prostori"]])

    def test_odpiranje(self):
        r = os_app.SafeerOsWindow._prostor_odpri(self.okno, "tel-1")
        self.cb.odpri_tukaj.assert_called_once_with("tel-1", link_prostori.CEL_ZASLON)
        self.assertEqual((r["ok"], r["nacin"]), (True, "zaslon"))
        r = os_app.SafeerOsWindow._prostor_odpri(self.okno, "pc-1")          # sorodnik racunalnika
        self.assertEqual((r["ok"], r["nacin"]), (True, "racunalnik"))
        self.okno.dispatcher.dispatch.assert_called_once()                    # oddaljeni zaslon v glavni niti
        for slab in ("tuj", "jaz", "neznan", ""):
            self.assertEqual(os_app.SafeerOsWindow._prostor_odpri(self.okno, slab)["koda"], "ni_prostora", slab)
        self.cb.je_povezan.return_value = False
        self.assertEqual(os_app.SafeerOsWindow._prostor_odpri(self.okno, "tel-1")["koda"], "ni_povezave")

    def test_metode_mostu(self):
        vir = beri("windows", "safeer_windows", "os_app.py")
        for m in ('if metoda == "prostori":', 'if metoda == "prostorOdpri":', 'if metoda == "namizjeWindows":'):
            self.assertIn(m, vir)
        self.assertIn("vv.zazeni_bliznjico(ob_pritisku, lambda: self.dispatcher.dispatch(self.odpri_prostore))", vir)


class Vmesnik(unittest.TestCase):
    def test_besedila_v_vseh_jezikih(self):
        js = beri("assets", "os", "besedila.js")
        rabljeni = set(re.findall(r't\("(prostor[A-Za-z_]*)"', beri("assets", "os", "os.js")))
        rabljeni |= set(re.findall(r'tp\("(prostor[A-Za-z_]*)"', beri("windows", "safeer_windows", "qml", "Prostori.qml")))
        rabljeni.discard("prostorVrsta_")
        rabljeni |= {"prostorVrsta_" + v for v in link_prostori.VRSTE} | {"prostori", "prostoriNamig", "prostoriPod"}
        po = {}
        for m in re.finditer(r'^Object\.assign\(BESEDILA_OS\.([a-z]{2}), (\{"prostori".*\})\);$', js, re.M):
            po[m.group(1)] = json.loads(m.group(2))
        self.assertEqual(set(po), set(JEZIKI))
        for j in JEZIKI:
            self.assertFalse(rabljeni - set(po[j]), j)
            self.assertIn("Strg+Win+Tab" if j == "de" else "Ctrl+Win+Tab", po[j]["prostoriNamig"])
            self.assertNotIn("Super+Tab", json.dumps(po[j], ensure_ascii=False))
        # Lastnik, 25. 10. 2026 (09:01): uporabniško ime je »Zasloni« (identifikatorji v kodi ostanejo »prostori«).
        imena = {"sl": "Zasloni", "en": "Screens", "de": "Bildschirme", "es": "Pantallas", "fr": "Écrans", "it": "Schermi"}
        self.assertEqual({j: po[j]["prostori"] for j in JEZIKI}, {j: imena[j] for j in JEZIKI})
        self.assertNotIn('"Prostori"', beri("windows", "safeer_windows", "qml", "Namizje.qml"))

    def test_okno_safeer_os(self):
        html = beri("assets", "os", "index.html")
        self.assertIn('id="gumbProstori"', html)
        self.assertIn('id="slojProstori"', html)
        js = beri("assets", "os", "os.js")
        self.assertIn("poveziProstore();", js)
        self.assertIn('klic("prostorOdpri", [p.id])', js)
        self.assertIn('klic("namizjeWindows", [p.indeks])', js)
        self.assertIn('if (vrsta === "prostori") odpriProstore(', js)
        self.assertIn(".prostori-trak", beri("assets", "os", "os.css"))

    def test_namizje_qml(self):
        qml = beri("windows", "safeer_windows", "qml", "Namizje.qml")
        self.assertIn("Prostori { id: prostori", qml)
        self.assertIn("onClicked: prostori.odpri(0)", qml)
        self.assertIn('if (vrsta === "prostori") prostori.odpri(', qml)
        from safeer_windows import namizje_qml
        b = namizje_qml.besedila_prostorov(beri("assets", "os", "besedila.js"), "de")
        self.assertEqual(b["prostori"], "Bildschirme")
        self.assertEqual(namizje_qml.besedila_prostorov("", "sl"), {})

    def test_bliznjica_ni_win_tab(self):
        self.assertEqual(varnostna_vrata.BLIZNJICA_PROSTORI, "Ctrl+Win+Tab")
        self.assertNotEqual(varnostna_vrata.ID_PROSTORI, varnostna_vrata.ID_BLIZNJICE)

    def test_skupna_koda(self):
        s = json.loads(beri("skupna-koda.json"))
        self.assertIn("core/link_prostori.py", s["zacasno_razlicne"] + s["skupne"])


if __name__ == "__main__":
    unittest.main()
