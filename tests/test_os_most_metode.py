"""Skupni most vmesnika (core/os_most_metode.py, scripts/most_pregled.py) - Linux in Windows.

1. Skupne metode klicejo jedro z istimi argumenti kot do zdaj gostitelja (safeer_os.py, os_app.py/namizje_win.py).
2. Dispecer: zmoznosti() so skupne (s kontekstom) + gostiteljeve; metoda brez konteksta ni zmoznost.
3. Vsak klic("x") vmesnika tega drevesa (assets/os/*.js, namizje QML) ima metodo v zaledju ali je na seznamu
   most_pregled.MANJKA (vmesnik jo skrije prek ima() v assets/os/most.js); seznam se sme samo krajsati.
Ista datoteka je v Safeer-linux in Safeer-windows (skupna-koda.json); drevo prepozna sama.
"""
import importlib.util
import types
import unittest
from pathlib import Path
from unittest import mock

from core import os_most_metode as om

KOREN = Path(__file__).resolve().parents[1]


def _pregled():
    spec = importlib.util.spec_from_file_location("most_pregled", KOREN / "scripts" / "most_pregled.py")
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


mp = _pregled()


class Kontekst:
    def __init__(self):
        self.sporocila = mock.Mock()
        self.scit = mock.Mock()
        self.lupa = mock.Mock()


class SkupneMetode(unittest.TestCase):
    def test_datoteke_z_argumenti_kot_prej(self):
        from core import os_datoteke
        d = om.Dispecer(Kontekst(), platforma="linux")
        with mock.patch.object(os_datoteke, "ustvari_mapo", return_value={"ok": True}) as m:
            self.assertEqual(d.klic("novaMapa", ["/dom", "Nova"]), {"ok": True})
        m.assert_called_once_with("/dom", "Nova")
        with mock.patch.object(os_datoteke, "ustvari_datoteko") as m:
            d.klic("novaDatoteka", ["/dom", "a"])
        m.assert_called_once_with("/dom", "a", "prazna", "")
        with mock.patch.object(os_datoteke, "prilepi") as m:
            d.klic("prilepiDatoteke", [["/a"], "/b", 1])
            d.klic("prilepiDatoteke", ["ni seznam"])
        self.assertEqual(m.call_args_list, [mock.call(["/a"], "/b", True), mock.call([], "", False)])
        with mock.patch.object(os_datoteke, "preimenuj") as m:
            d.klic("preimenujDatoteko", [None, "x"])      # null iz vmesnika ni niz »None«
        m.assert_called_once_with("", "x")

    def test_iskanje_meja(self):
        from core import os_datoteke, os_iskalnik
        d = om.Dispecer(Kontekst(), platforma="linux")
        with mock.patch.object(os_iskalnik, "isci", return_value=[]) as m:
            d.klic("isciDatoteke", ["ab", 5000])
            d.klic("isciDatoteke", ["ab", True])
            d.klic("isciDatoteke", ["ab"])
        self.assertEqual(m.call_args_list, [mock.call("ab", 300), mock.call("ab", os_datoteke.NAJVEC_ZADETKOV),
                                            mock.call("ab", os_datoteke.NAJVEC_ZADETKOV)])

    def test_sporocila_pogovor_oznaci(self):
        k = Kontekst()
        d = om.Dispecer(k, platforma="windows")
        d.klic("sporocilaPogovor", ["k", "p"])
        d.klic("sporocilaPogovor", ["k", "p", False])
        self.assertEqual(k.sporocila.pogovor.call_args_list, [mock.call("k", "p", True), mock.call("k", "p", False)])
        d.klic("sporocilaZacni", ["n"])
        k.sporocila.zacni_klepet.assert_called_once_with("n", "")

    def test_magnet_napaka_kot_koda(self):
        from core import os_torrent
        torrenti = types.SimpleNamespace(nadaljuj=mock.Mock(side_effect=os_torrent.NapakaTorrenta("ni_programa")),
                                         magnet=lambda i: "magnet:?xt=urn:btih:" + "a" * 40)
        d = om.Dispecer(Kontekst(), platforma="linux")
        with mock.patch.object(os_torrent, "torrenti", return_value=torrenti):
            self.assertEqual(d.klic("magnetNadaljuj", [3]), {"ok": False, "koda": "ni_programa"})
            self.assertEqual(d.klic("magnetPovezava", [3]), {"ok": True, "uri": "magnet:?xt=urn:btih:" + "a" * 40})

    def test_nit_kot_na_linuxu(self):
        d = om.Dispecer(Kontekst(), platforma="linux")
        self.assertEqual(d.nit("sporocilaSeznam"), "glavna")
        self.assertEqual(d.nit("lupaUcenje"), "glavna")
        self.assertEqual(d.nit("novaMapa"), "ozadje")
        self.assertEqual(d.nit("neznano"), "ozadje")

    def test_spreminjajo_datoteke(self):
        for m in ("novaMapa", "novaDatoteka", "preimenujDatoteko", "prilepiDatoteke", "razveljaviDatoteke"):
            self.assertIn(m, om.SPREMINJAJO_DATOTEKE)


class Dispecer(unittest.TestCase):
    def test_zmoznosti(self):
        d = om.Dispecer(Kontekst(), platformne=["zacetek", "splet"], platforma="windows")
        z = d.zmoznosti()
        self.assertEqual(z, sorted(z))
        for m in ("zacetek", "splet", "zmoznosti", "novaMapa", "sporocilaSeznam", "scit"):
            self.assertIn(m, z)
        self.assertEqual(d.klic("zmoznosti"), {"platforma": "windows", "metode": z})

    def test_brez_konteksta_ni_metode(self):
        k = Kontekst()
        k.scit = None                     # npr. paket brez Scita
        d = om.Dispecer(k, platforma="linux")
        self.assertNotIn("scit", d.zmoznosti())
        self.assertFalse(d.zna("scit"))
        with self.assertRaises(KeyError):
            d.klic("scit")
        self.assertIn("sporocilaSeznam", d.zmoznosti())

    def test_neznana(self):
        d = om.Dispecer(None, platforma="linux")
        self.assertFalse(d.zna("formatiraj"))
        with self.assertRaises(KeyError):
            d.klic("formatiraj", [])
        self.assertTrue(d.zna("zmoznosti"))
        self.assertIn("diski", d.zmoznosti())             # brez konteksta: samo metode jedra
        self.assertNotIn("sporocilaSeznam", d.zmoznosti())

    def test_privzeta_platforma(self):
        from core import platforma
        self.assertEqual(om.Dispecer().platforma, platforma.IME)


class VmesnikInZaledje(unittest.TestCase):
    """Staticna primerjava (ast, regularni izrazi) vmesnika in zaledja TEGA drevesa."""

    @classmethod
    def setUpClass(cls):
        cls.vrsta = mp.vrsta(KOREN)
        if not cls.vrsta:
            raise unittest.SkipTest("ni drevo Safeer-linux ali Safeer-windows")
        cls.ui = mp.ui_klici(KOREN)
        cls.zaledje = mp.zaledje(KOREN)

    def test_vmesnik_najde_klice(self):
        # Varovalo pregleda: ce bi se oblika klicev spremenila (most.klic -> drugo ime), bi test molce prazno uspel.
        self.assertGreater(len(self.ui["html"]), 100)
        self.assertGreater(len(self.ui["qml"]), 20)
        self.assertGreater(len(self.zaledje["html"]), 100)

    def test_vsak_klic_ima_metodo_ali_je_skrit(self):
        manjka = mp.manjka(KOREN, KOREN)
        for vrsta_ui in mp.VRSTE:
            dovoljeno = mp.MANJKA[self.vrsta][vrsta_ui]
            self.assertEqual(sorted(manjka[vrsta_ui] - dovoljeno), [],
                             "%s/%s: vmesnik klice metodo, ki je zaledje ne pozna - dodaj jo v zaledje (ali "
                             "core/os_most_metode.py) ali jo skrij prek ima() in dodaj v most_pregled.MANJKA"
                             % (self.vrsta, vrsta_ui))

    def test_seznam_manjka_se_samo_krajsa(self):
        for vrsta_ui in mp.VRSTE:
            ze_ima = sorted(mp.MANJKA[self.vrsta][vrsta_ui] & self.zaledje[vrsta_ui])
            self.assertEqual(ze_ima, [], "%s/%s: zaledje metodo zdaj pozna - odstrani jo iz most_pregled.MANJKA"
                             % (self.vrsta, vrsta_ui))

    def test_skupne_metode_ze_obstajajo_na_tej_platformi(self):
        # Dispecer ne doda metode, ki je zaledje platforme ni imelo: vsaka skupna metoda je danes v zaledju
        # (Linux: okno Safeer OS; Windows: namizje QML) - premik v core/os_most_metode.py je samo poenotenje.
        kje = "html" if self.vrsta == "linux" else "qml"
        self.assertEqual(sorted(set(om.SKUPNE) - self.zaledje[kje]), [])

    def test_pregled_vidi_skupne(self):
        self.assertEqual(mp._skupne(KOREN), set(om.SKUPNE))

    def test_linux_isti_seznam_spreminjajo_datoteke(self):
        if self.vrsta != "linux":
            self.skipTest("samo Safeer-linux")
        import ast
        drevo = ast.parse((KOREN / "safeer_os.py").read_text(encoding="utf-8"))
        for n in ast.walk(drevo):
            if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "SPREMINJAJO_DATOTEKE" for t in n.targets):
                imena = {e.value for e in n.value.args[0].elts}
                self.assertEqual(imena, set(om.SPREMINJAJO_DATOTEKE))
                return
        self.fail("safeer_os.SPREMINJAJO_DATOTEKE ni najden")


if __name__ == "__main__":
    unittest.main()
