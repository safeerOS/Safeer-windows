"""Windows zaledje klice core/platforma.py (skupni most Linux/Windows, 25. 10. 2026) - stare funkcije ostanejo, a
ne nosijo vec svoje kopije. Na pravem Windows (CI) se preveri se, da so poti in seznami isti kot prej."""
import contextlib
import os
import sys
import unittest
from unittest import mock

from core import os_datoteke, os_scit, platforma
from safeer_windows import namizje_datoteke as nd
from safeer_windows import os_backend_win, tema


class Poti(unittest.TestCase):
    def test_config_dir_iz_platforme(self):
        self.assertEqual(os_backend_win.CONFIG_DIR, platforma.mapa_nastavitev(windows=True))
        if sys.platform == "win32":
            self.assertEqual(os_backend_win.CONFIG_DIR, os.path.join(os.environ["APPDATA"], "SafeerOS"))

    def test_en_seznam_nastavitev(self):
        self.assertIs(os_backend_win.NASTAVITVE_URI, platforma.NASTAVITVE_WINDOWS)
        r = os_backend_win.razpolozljive_nastavitve()
        self.assertEqual(r, {"moduli": list(platforma.MODULI_WINDOWS), "orodja": list(platforma.ORODJA_WINDOWS)})


class Klici(unittest.TestCase):
    def test_backend_gre_v_platformo(self):
        okno = sys.platform == "win32"
        with mock.patch.object(platforma, "pokazi_v_mapi", return_value=True) as pv, \
                mock.patch.object(platforma, "odpri_nastavitve", return_value=True) as on, \
                mock.patch.object(platforma, "napajanje", return_value=True) as np_:
            self.assertTrue(os_backend_win.pokazi_v_mapi("C:/x.txt"))
            self.assertTrue(os_backend_win.odpri_nastavitve("sound"))
            self.assertTrue(os_backend_win.napajanje("zakleni"))
        pv.assert_called_once_with("C:/x.txt", windows=okno)
        on.assert_called_once_with("sound", windows=okno)
        np_.assert_called_once_with("zakleni", windows=okno)

    def test_zagon_programa_steje_in_zazene_prek_platforme(self):
        with mock.patch.object(os_backend_win, "nalozi_shrambo", return_value={}), \
                mock.patch.object(os_backend_win, "shrani_shrambo") as shrani, \
                mock.patch.object(platforma, "zazeni_program", return_value=True) as zp:
            self.assertTrue(os_backend_win.zazeni_program("C:/P/a.lnk"))
        zp.assert_called_once_with("C:/P/a.lnk", windows=sys.platform == "win32")
        self.assertEqual(shrani.call_args[0][0]["pogosti"], {"C:/P/a.lnk": 1})

    def test_datoteke_isti_pokazi_v_mapi(self):
        with mock.patch.object(platforma, "pokazi_v_mapi", return_value=True) as pv:
            self.assertTrue(nd.pokazi_v_mapi("C:/x.txt"))
            self.assertTrue(os_datoteke.pokazi_v_mapi("C:/y.txt"))
        self.assertEqual(pv.call_args_list, [mock.call("C:/x.txt", windows=True), mock.call("C:/y.txt")])

    def test_dns_scita_prek_platforme(self):
        with mock.patch("core.os_scit.sys.platform", "win32"), \
                mock.patch.object(platforma, "dns_vmesniki", return_value=["Ethernet"]) as v, \
                mock.patch.object(platforma, "dns_vmesnika", return_value="127.0.0.1") as d, \
                mock.patch.object(platforma, "dns_usmeri", return_value=True) as u, \
                mock.patch.object(platforma, "dns_povrni", return_value=True) as p:
            self.assertEqual(os_scit.vmesniki_povezani(), ["Ethernet"])
            self.assertEqual(os_scit.dns_vmesnika("Ethernet"), "127.0.0.1")
            self.assertEqual(os_scit.trenutni_streznik("Ethernet"), "127.0.0.1")
            self.assertTrue(os_scit.usmeri("Ethernet", 53, ["192.168.1.1"]))
            self.assertTrue(os_scit.povrni("Ethernet"))
        v.assert_called_once_with(windows=True)
        self.assertEqual(d.call_count, 2)
        u.assert_called_once_with("Ethernet", 53, ["192.168.1.1"], windows=True)
        p.assert_called_once_with("Ethernet", windows=True)


class Tema(unittest.TestCase):
    """tema.py bere assets/os/teme.json (iz tokens.css v Safeer-linux); barve so iste kot iz os.css do zdaj."""

    def _paleta(self, ime, teme_json):
        """teme_json=None: prava datoteka assets/os/teme.json; {}: kot da je ni (rezerva os.css)."""
        zamenjava = contextlib.nullcontext() if teme_json is None else \
            mock.patch.object(tema, "_teme_json", return_value=teme_json)
        with zamenjava, mock.patch.object(tema, "trenutna", return_value="safeer"):
            tema._predpomnilnik.clear()
            try:
                return tema.paleta(ime)
            finally:
                tema._predpomnilnik.clear()

    def test_teme_json_obstaja_in_ima_vse_teme(self):
        t = tema._teme_json()
        self.assertEqual(set(t), set(tema.TEME))

    def test_iste_barve_kot_os_css(self):
        for ime in tema.TEME:
            self.assertEqual(self._paleta(ime, None), self._paleta(ime, {}), ime)     # {} = rezerva os.css

    def test_poudarek_iz_teme(self):
        self.assertEqual(self._paleta("nord", None)["poudarek"], "#88c0d0")
        self.assertEqual(self._paleta("safeer", None)["poudarek"], "#8ac7ff")


@unittest.skipUnless(sys.platform == "win32", "pravi Windows (CI)")
class PraviWindows(unittest.TestCase):
    def test_zvok_ista_oblika_kot_linux(self):
        z = platforma.zvok()
        if z is not None:                      # racunalnik brez zvocne naprave (CI) vrne None
            self.assertEqual(set(z), {"glasnost", "utisan"})

    def test_mape_podatkov(self):
        self.assertEqual(platforma.mapa_podatkov(), os.path.join(os.environ["LOCALAPPDATA"], "SafeerOS"))


if __name__ == "__main__":
    unittest.main()
