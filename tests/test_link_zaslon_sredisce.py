"""Deljenje zaslona iz racunalnika v Link Meshu: zacne se pri sredisci CILJNE naprave.

Izmerjeno 5. 10. 2026: na Windows je plosca »Deli z« → »Zaslon« odgovorila »Središče tega še ne zna; posodobi Safeer
na napravi, ki je središče« - sredisce je bil racunalnik sam, ki zaslona ne posreduje. Na Linuxu Safeer Control z
lastnim srediscem nima zetona seznanitve in je deljenje koncal ze pred klicem. Sredisce telefona pa klic racunalnika
s sejo s podpisom sprejme (krog108/sonda-zaslon.py: HTTP 200). Zato: kot datoteko, tudi zaslon oddamo sredisci naprave.
"""
import importlib.util
import os
import types
import unittest
from unittest import mock

from core import link_deljenje

KOREN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: Zaledje Safeer Controla za Linux (GTK); v repozitoriju Safeer OS za Windows ga ni.
JE_CONTROL_ZA_LINUX = (os.path.isfile(os.path.join(KOREN, "safeer_control.py"))
                       and importlib.util.find_spec("gi") is not None)

SOSED = ("wss://10.0.0.7:8990/cast/ws", "odtis-telefona")


class IzbiraSredisca(unittest.TestCase):
    def _izberi(self, sredisce_naprave, seja=None, lastno=None):
        seja = seja or mock.Mock(return_value=("seja-pri-sosedu", "n-moj-control"))
        lastno = lastno or mock.Mock(return_value=(None, "zaslon_ni_na_voljo"))
        izid = link_deljenje.sredisce_za_zaslon(mock.Mock(return_value=sredisce_naprave), seja, lastno, "n-tel")
        return izid, seja, lastno

    def test_naprava_s_svojim_srediscem_dobi_deljenje_tam(self):
        (izbrano, napaka), seja, lastno = self._izberi((SOSED, ""))
        self.assertEqual(izbrano, ("wss://10.0.0.7:8990/cast/ws", "seja-pri-sosedu", "odtis-telefona", "n-moj-control"))
        self.assertEqual(napaka, {})
        seja.assert_called_once_with("wss://10.0.0.7:8990/cast/ws", "odtis-telefona")
        lastno.assert_not_called()

    def test_sredisce_naprave_ne_da_seje(self):
        (izbrano, napaka), _, _ = self._izberi((SOSED, ""), seja=mock.Mock(return_value=(None, "n-moj-control")))
        self.assertIsNone(izbrano)
        self.assertEqual(napaka["koda"], "sredisce_naprave_ni_dosegljivo")
        self.assertTrue(napaka["sporocilo"])

    def test_naprava_dva_skoka_dalec(self):
        (izbrano, napaka), seja, lastno = self._izberi((None, "naprava_pri_drugem_srediscu"))
        self.assertIsNone(izbrano)
        self.assertEqual(napaka["koda"], "naprava_pri_drugem_srediscu")
        self.assertIn("zaslona", napaka["sporocilo"])
        self.assertNotIn("datotek", napaka["sporocilo"])
        seja.assert_not_called()
        lastno.assert_not_called()

    def test_naprava_pri_nasem_sredisci_ki_zaslona_ne_posreduje(self):
        (izbrano, napaka), _, lastno = self._izberi((None, ""))
        self.assertIsNone(izbrano)
        self.assertEqual(napaka["koda"], "zaslon_ni_na_voljo")
        self.assertEqual(napaka["sporocilo"], link_deljenje.SPOROCILA_ZASLONA["zaslon_ni_na_voljo"])
        lastno.assert_called_once_with()

    def test_prijavljeni_na_tuje_sredisce_delimo_prek_njega(self):
        tuje = ("wss://10.0.0.9:8990/cast/ws", "zeton", "odtis-tv", "n-moj-control")
        (izbrano, napaka), _, _ = self._izberi((None, ""), lastno=mock.Mock(return_value=(tuje, "")))
        self.assertEqual((izbrano, napaka), (tuje, {}))

    def test_brez_zetona_pri_tujem_sredisci(self):
        (izbrano, napaka), _, _ = self._izberi((None, ""), lastno=mock.Mock(return_value=(None, "hub_ni_znan")))
        self.assertIsNone(izbrano)
        self.assertEqual(napaka["koda"], "hub_ni_znan")


class _Deljenje(link_deljenje.DeljenjeZaslona):
    """Brez zajema zaslona: dva okvirja, nato konec."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._okvirji = [b"JPEG-1", b"JPEG-22"]

    def _okvir(self):
        if not self._okvirji:
            self._ustavi.set()
            return None
        return self._okvirji.pop(0)


class DeljenjeGreNaIzbranoSredisce(unittest.TestCase):
    def setUp(self):
        self.stanja = []

    def _deljenje(self, sredisce):
        return _Deljenje("wss://127.0.0.1:8990/cast/ws", "", "odtis-nas", "n-moj-control", "n-tel", "Telefon",
                         ob_spremembi=lambda s: self.stanja.append(dict(s)), sredisce=sredisce)

    def test_napaka_izbire_konca_brez_klica_sredisca(self):
        napaka = {"sporocilo": "Ta naprava še ne more prikazati zaslona tega računalnika.", "koda": "zaslon_ni_na_voljo",
                  "zasedenaOd": ""}
        d = self._deljenje(lambda: (None, napaka))
        with mock.patch.object(link_deljenje.link_tls, "zahteva") as zahteva:
            d._tok()
        zahteva.assert_not_called()
        self.assertEqual(len(self.stanja), 1, "eno obvestilo, ne dve")
        self.assertEqual((self.stanja[0]["tece"], self.stanja[0]["koda"], self.stanja[0]["napaka"]),
                         (False, "zaslon_ni_na_voljo", napaka["sporocilo"]))

    def test_zacetek_gre_na_sredisce_naprave_s_sejo(self):
        d = self._deljenje(lambda: (("wss://10.0.0.7:8990/cast/ws", "seja", "odtis-telefona", "n-moj-control"), {}))
        zasedena = (409, {"koda": "naprava_zasedena", "busy_by_name": "Tablica", "napaka": "Naprava je zasedena."}, None)
        with mock.patch.object(link_deljenje.link_tls, "zahteva", return_value=zasedena) as zahteva:
            d._tok()
        (naslov, telo), dodatno = zahteva.call_args[0], zahteva.call_args[1]
        self.assertEqual(naslov, "https://10.0.0.7:8990/cast/share/screen/start")
        self.assertEqual(telo, {"device_id": "n-moj-control", "target": "n-tel"})
        self.assertEqual((dodatno["zeton"], dodatno["pripeti"]), ("seja", "odtis-telefona"))
        self.assertEqual((self.stanja[-1]["tece"], self.stanja[-1]["koda"], self.stanja[-1]["zasedenaOd"]),
                         (False, "naprava_zasedena", "Tablica"))

    def test_okvirji_in_konec_pri_istem_sredisci(self):
        d = self._deljenje(lambda: (("wss://10.0.0.7:8990/cast/ws", "seja", "odtis-telefona", "n-moj-control"), {}))
        poslano = []
        vticnik = types.SimpleNamespace(settimeout=lambda *_: None, sendall=poslano.append, close=lambda: None)
        odgovori = [(200, {"id": "abc", "push_path": "/cast/screen/abc?k=KLJUC"}, None), (200, {"stopped": True}, None)]
        with mock.patch.object(link_deljenje.link_tls, "zahteva", side_effect=odgovori) as zahteva, \
                mock.patch.object(link_deljenje.socket, "create_connection", return_value=mock.Mock()) as povezi, \
                mock.patch.object(link_deljenje.link_tls, "ovij", return_value=(vticnik, None)) as ovij:
            d._tok()
        self.assertEqual(povezi.call_args[0][0], ("10.0.0.7", 8990))
        self.assertEqual(ovij.call_args[0][1:], ("10.0.0.7", "odtis-telefona"))
        glava = poslano[0].decode("ascii")
        self.assertTrue(glava.startswith("POST /cast/screen/abc?k=KLJUC HTTP/1.1\r\nHost: 10.0.0.7\r\n"), glava)
        self.assertIn("x-safeer-token: seja\r\n", glava)
        self.assertEqual(poslano[1:], [(6).to_bytes(4, "big") + b"JPEG-1", (7).to_bytes(4, "big") + b"JPEG-22"])
        konec = zahteva.call_args_list[1]
        self.assertEqual(konec[0], ("https://10.0.0.7:8990/cast/share/screen/stop", {"id": "abc"}))
        self.assertEqual((konec[1]["zeton"], konec[1]["pripeti"]), ("seja", "odtis-telefona"))
        self.assertEqual([s["tece"] for s in self.stanja], [True, False])
        self.assertEqual(self.stanja[-1]["napaka"], "")

    def test_brez_izbire_sredisca_kot_doslej(self):
        d = _Deljenje("wss://10.0.0.9:8990/cast/ws", "zeton", "odtis-tv", "n-moj", "n-tv", "TV")
        with mock.patch.object(link_deljenje.link_tls, "zahteva", return_value=(404, {}, None)) as zahteva:
            d._tok()
        self.assertEqual(zahteva.call_args[0][0], "https://10.0.0.9:8990/cast/share/screen/start")
        self.assertEqual(d.koda, "sredisce_ne_zna")


@unittest.skipUnless(JE_CONTROL_ZA_LINUX, "zaledje Safeer Controla za Linux (GTK)")
class SafeerControlZaLinux(unittest.TestCase):
    def setUp(self):
        from core import safeer_link
        self.safeer_link = safeer_link
        self.odzivi = []
        self.gostitelj = types.SimpleNamespace(nas_id="n-moj-control", gostimo=lambda: True)
        self.link = types.SimpleNamespace(
            _hub_gostitelj=self.gostitelj, _id=lambda: "n-moj-control", _ime=lambda: "Safeer Control (pisarna)",
            _hub=lambda: "wss://127.0.0.1:8990/cast/ws", _odtis=lambda: "odtis-nas", _zeton=lambda: None,
            _zeton_http=mock.Mock(return_value="zeton-http"), _sredisce_naprave=mock.Mock(return_value=(SOSED, "")),
            deljenje_zaslona=None, _odziv=lambda vrsta, podatki: self.odzivi.append((vrsta, podatki)))
        razred = safeer_link.SafeerLink
        self.link._deljenje = lambda *a, **k: razred._deljenje(self.link, *a, **k)
        self.link._na_spremembo_zaslona = lambda s: razred._na_spremembo_zaslona(self.link, s)
        self.link._sredisce_za_zaslon = lambda i: razred._sredisce_za_zaslon(self.link, i)

    def test_seja_pri_sredisci_naprave(self):
        with mock.patch.object(self.safeer_link.link_hub, "seja_s_podpisom", return_value="seja") as seja:
            izbrano, napaka = self.link._sredisce_za_zaslon("n-tel")
        seja.assert_called_once_with("wss://10.0.0.7:8990/cast/ws", "n-moj-control", "odtis-telefona", "Safeer Control (pisarna)")
        self.assertEqual((izbrano, napaka), (("wss://10.0.0.7:8990/cast/ws", "seja", "odtis-telefona", "n-moj-control"), {}))

    def test_naprava_pri_nasem_sredisci(self):
        self.link._sredisce_naprave.return_value = (None, "")
        izbrano, napaka = self.link._sredisce_za_zaslon("n-x")
        self.assertIsNone(izbrano)
        self.assertEqual(napaka["koda"], "zaslon_ni_na_voljo")
        self.link._zeton_http.assert_not_called()

    def test_tuje_sredisce_kot_doslej(self):
        self.link._sredisce_naprave.return_value = (None, "")
        self.link._hub = lambda: "wss://10.0.0.9:8990/cast/ws"
        self.gostitelj.gostimo = lambda: False
        izbrano, napaka = self.link._sredisce_za_zaslon("n-tv")
        self.assertEqual(izbrano, ("wss://10.0.0.9:8990/cast/ws", "zeton-http", "odtis-nas", "n-moj-control"))

    def test_zacetek_brez_zetona_seznanitve_ne_obupa(self):
        """Control z lastnim srediscem zetona seznanitve nima; prej je deljenje koncal z »Hub ni znan«."""
        ustvarjeno = {}

        class Deljenje:
            tece = False

            def __init__(self, *a, **k):
                ustvarjeno.update(a=a, k=k)

            def zacni(self):
                ustvarjeno["zagnano"] = True

            @staticmethod
            def zajem_na_voljo():
                return True, ""

        with mock.patch.object(self.safeer_link.link_deljenje, "DeljenjeZaslona", Deljenje):
            self.safeer_link.SafeerLink._zacni_deljenje_zaslona(self.link, "n-tel", "Telefon")
        self.assertTrue(ustvarjeno.get("zagnano"), self.odzivi)
        self.assertEqual(self.odzivi, [])
        self.assertEqual(ustvarjeno["a"][4:6], ("n-tel", "Telefon"))
        with mock.patch.object(self.safeer_link.link_hub, "seja_s_podpisom", return_value="seja"):
            self.assertEqual(ustvarjeno["k"]["sredisce"]()[0][1], "seja")

    def test_brez_sredisca_pove_na_plosci(self):
        self.link._odtis = lambda: None
        self.safeer_link.SafeerLink._zacni_deljenje_zaslona(self.link, "n-tel", "Telefon")
        self.assertEqual(len(self.odzivi), 1)
        vrsta, p = self.odzivi[0]
        self.assertEqual((vrsta, p["vrsta"], p["stanje"], p["koda"]), ("deljenje", "zaslon", "napaka", "hub_ni_znan"))


if __name__ == "__main__":
    unittest.main()
