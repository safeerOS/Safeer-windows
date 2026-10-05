"""Deljen zaslon druge naprave v Safeer OS za Windows: svoj zavihek Spleta, ki se ob koncu deljenja zapre.

Izmerjeno 5. 10. 2026 na testnem Windows (1.0.39): konec deljenja, ki je prisel pred nalozeno stranjo, zavihka ni
zaprl - na zaslonu je ostala stran z napako; gledalec je zamenjal stran v zavihku, ki ga je imel uporabnik odprtega.
"""
import inspect
import types
import unittest
from unittest import mock

from safeer_windows import gledalec_zaslona, os_app

GLEDALEC = "https://10.0.0.7:8990/cast/screen/abc/view?k=KLJUC"


class Okno:
    """Nadomestek okna Safeer OS: zavihki Spleta, razdelek in kar je gledalec z njim naredil."""

    def __init__(self, razdelek="datoteke", v_spletu=False):
        self.zavihki = []
        self.trenutni = None
        self.v_spletu = v_spletu
        self.razdelek = razdelek
        self.vrnitve = []
        self.branja = []          # povratni klici, ki cakajo na odgovor strani
        self.odgovori_takoj = True
        self.g = gledalec_zaslona.GledalecZaslona(
            nov_zavihek=self.nov, zapri_zavihek=self.zapri, je_trenutni=lambda z: self.trenutni is z,
            naslov=lambda z: z.naslov(), v_spletu=lambda: self.v_spletu, preberi_razdelek=self.preberi,
            pokazi_splet=self.pokazi, vrni_v_os=self.vrni)

    def nov(self, url):
        z = types.SimpleNamespace(url=url, naslov=lambda: z.url)
        self.zavihki.append(z)
        self.trenutni = z
        return z

    def zapri(self, z):
        if z not in self.zavihki:
            return False
        self.zavihki.remove(z)
        if self.trenutni is z:
            self.trenutni = self.zavihki[-1] if self.zavihki else None
        return True

    def preberi(self, nadaljuj):
        if self.odgovori_takoj:
            nadaljuj(self.razdelek)
        else:
            self.branja.append(nadaljuj)

    def pokazi(self):
        self.v_spletu = True

    def vrni(self, razdelek):
        self.vrnitve.append(razdelek)
        self.v_spletu = False

    def naslovi(self):
        return [z.url for z in self.zavihki]


class Gledalec(unittest.TestCase):
    def test_gledalec_dobi_svoj_zavihek_in_po_koncu_se_vrnemo_kjer_smo_bili(self):
        o = Okno(razdelek="datoteke")
        mojo = o.nov("https://example.org/clanek")       # zavihek, ki ga ima uporabnik odprt v Spletu (ni na zaslonu)
        o.g.odpri(GLEDALEC)
        self.assertEqual(o.naslovi(), ["https://example.org/clanek", GLEDALEC], "uporabnikova stran ostane nedotaknjena")
        self.assertTrue(o.v_spletu and o.g.odprt())
        self.assertTrue(o.g.zapri())
        self.assertEqual(o.zavihki, [mojo])
        self.assertEqual(o.vrnitve, ["datoteke"])
        self.assertFalse(o.g.odprt())

    def test_uporabnik_v_spletu_ostane_v_spletu(self):
        o = Okno(v_spletu=True)
        o.nov("https://example.org/clanek")
        o.preberi = mock.Mock()
        o.g.odpri(GLEDALEC)
        o.preberi.assert_not_called()
        self.assertTrue(o.g.zapri())
        self.assertEqual((o.naslovi(), o.vrnitve, o.v_spletu), (["https://example.org/clanek"], [], True))

    def test_konec_pred_odgovorom_strani_zavihka_ne_odpre(self):
        o = Okno()
        o.odgovori_takoj = False
        o.g.odpri(GLEDALEC)
        self.assertFalse(o.g.zapri())
        o.branja[0]("datoteke")                  # stran odgovori sele po koncu deljenja
        self.assertEqual((o.zavihki, o.v_spletu, o.vrnitve), ([], False, []))

    def test_brez_odgovora_strani_se_vrnemo_na_domov(self):
        o = Okno(razdelek="")
        o.g.odpri(GLEDALEC)
        o.g.zapri()
        self.assertEqual(o.vrnitve, ["domov"])

    def test_zavihka_s_cim_drugim_ne_zapremo(self):
        o = Okno()
        o.g.odpri(GLEDALEC)
        o.zavihki[0].url = "https://example.org/moje"      # uporabnik je v istem zavihku odprl svojo stran
        self.assertFalse(o.g.zapri())
        self.assertEqual((o.naslovi(), o.vrnitve), (["https://example.org/moje"], []))

    def test_zavihek_ki_ga_je_uporabnik_zaprl_sam(self):
        o = Okno()
        o.g.odpri(GLEDALEC)
        o.zapri(o.zavihki[0])
        self.assertFalse(o.g.zapri())
        self.assertEqual(o.vrnitve, [])

    def test_unicen_pogled_ni_napaka(self):
        o = Okno()
        o.g.odpri(GLEDALEC)

        def unicen():
            raise RuntimeError("Internal C++ object (WvView) already deleted.")
        o.zavihki[0].naslov = unicen
        self.assertFalse(o.g.zapri())
        self.assertEqual(o.vrnitve, [])

    def test_gledalec_v_ozadju_se_zapre_brez_vrnitve(self):
        o = Okno()
        o.g.odpri(GLEDALEC)
        o.nov("https://example.org/drugo")         # uporabnik je preklopil na svoj zavihek
        self.assertTrue(o.g.zapri())
        self.assertEqual((o.naslovi(), o.vrnitve), (["https://example.org/drugo"], []))

    def test_uporabnik_je_medtem_odsel_iz_spleta(self):
        o = Okno()
        o.g.odpri(GLEDALEC)
        o.v_spletu = False                           # kliknil je npr. Domov; zavihek gledalca je ostal odprt
        self.assertTrue(o.g.zapri())
        self.assertEqual((o.zavihki, o.vrnitve), ([], []), "ne vlecemo ga drugam, kot je sel sam")

    def test_novo_deljenje_zamenja_gledalca_in_ohrani_razdelek(self):
        o = Okno(razdelek="media")
        o.g.odpri(GLEDALEC)
        drugi = GLEDALEC.replace("abc", "def")
        o.g.odpri(drugi)
        self.assertEqual(o.naslovi(), [drugi])
        o.g.zapri()
        self.assertEqual(o.vrnitve, ["media"], "velja razdelek pred prvim deljenjem, ne »splet«")

    def test_dvojni_konec(self):
        o = Okno()
        o.g.odpri(GLEDALEC)
        self.assertTrue(o.g.zapri())
        self.assertFalse(o.g.zapri())
        self.assertEqual(o.vrnitve, ["datoteke"])

    def test_stran_gledalca_po_naslovu(self):
        self.assertTrue(gledalec_zaslona.je_gledalec(GLEDALEC))
        self.assertTrue(gledalec_zaslona.je_gledalec("https://127.0.0.1:8990/cast/screen/x/view?k=y"))
        for naslov in ("", None, "about:blank", "https://example.org/cast/screens"):
            self.assertFalse(gledalec_zaslona.je_gledalec(naslov))


class SafeerOs(unittest.TestCase):
    def test_dogodek_zaslon_odpre_in_zapre_gledalca(self):
        vir = inspect.getsource(os_app.SafeerOsWindow._na_dogodek_linka)
        self.assertIn("self.gledalec_zaslona.odpri(url)", vir)
        self.assertIn("self.dispatcher.dispatch(self.gledalec_zaslona.zapri)", vir)
        self.assertNotIn("_odpri_notranji_splet(url)", vir, "gledalec ne zamenja vec strani v uporabnikovem zavihku")
        self.assertNotIn("about:blank", vir)

    def test_gledalec_odpre_nov_zavihek(self):
        okno = types.SimpleNamespace(_browser_media_active=True, browser_window=mock.Mock())
        okno.browser_window.new_tab.return_value = "pogled"
        self.assertEqual(os_app.SafeerOsWindow._nov_zavihek_gledalca(okno, GLEDALEC), "pogled")
        okno.browser_window.new_tab.assert_called_once_with(GLEDALEC, switch=True)
        okno.browser_window.set_media_mode.assert_called_once_with(False)
        okno.browser_window.set_safeer_os_web_mode.assert_called_once_with(True)
        self.assertFalse(okno._browser_media_active)

    def test_zapre_natanko_zavihek_gledalca(self):
        okno = types.SimpleNamespace(browser_window=mock.Mock())
        okno.browser_window.tabs.indexOf.return_value = 2
        self.assertTrue(os_app.SafeerOsWindow._zapri_zavihek_gledalca(okno, "pogled"))
        okno.browser_window.close_tab.assert_called_once_with(2)
        okno.browser_window.tabs.indexOf.return_value = -1
        self.assertFalse(os_app.SafeerOsWindow._zapri_zavihek_gledalca(okno, "pogled"))
        okno.browser_window.close_tab.assert_called_once_with(2)

    def test_razdelek_se_prebere_enkrat_tudi_ce_stran_ne_odgovori(self):
        odgovori = []
        okno = types.SimpleNamespace(view=mock.Mock())
        with mock.patch.object(os_app.QTimer, "singleShot") as pozneje:
            os_app.SafeerOsWindow._preberi_razdelek(okno, odgovori.append)
        js, povratni = okno.view.page.return_value.runJavaScript.call_args[0]
        self.assertIn("safeerOsRazdelek", js)
        rok, po_roku = pozneje.call_args[0]
        self.assertLessEqual(rok, 1500)
        po_roku()                      # stran ni odgovorila
        povratni("datoteke")           # ... in odgovori prepozno
        self.assertEqual(odgovori, [""])
        odgovori.clear()
        with mock.patch.object(os_app.QTimer, "singleShot") as pozneje:
            os_app.SafeerOsWindow._preberi_razdelek(okno, odgovori.append)
        okno.view.page.return_value.runJavaScript.call_args[0][1]("datoteke")
        pozneje.call_args[0][1]()
        self.assertEqual(odgovori, ["datoteke"])


if __name__ == "__main__":
    unittest.main()
