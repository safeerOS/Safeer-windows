"""Plosca »Deli z …« na Windows pove, kaj se je zgodilo; prejeto besedilo se pokaze.

Stran Safeer Controla (assets/link/link.js) je ista kot na Linuxu in bere dogodke v obliki Safeer Controla za Linux.
Zaledje za Windows je oddajalo druga polja ali nic. Videno 5. 10. 2026 na testnem racunalniku: datoteka je prisla na
telefon, plosca pa ni pokazala ne napredka ne »Poslano«; po »Poslji besedilo« je ostalo »Pošiljam …«; besedilo, ki ga
je racunalniku poslala druga naprava, se ni pokazalo nikjer.
"""
import os
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from safeer_windows import control_backend as CB
from safeer_windows import os_app

KOREN = Path(__file__).resolve().parents[2]
ODTIS = "ab" * 32
HUB = "wss://127.0.0.1:45678/cast/ws"


def _backend(td: str) -> "CB.SafeerControlBackend":
    b = CB.SafeerControlBackend(config_pot=os.path.join(td, "link.json"))
    b.nastavitve.clear()
    b.nastavitve.update({"hub_url": HUB, "hub_fp": ODTIS, "control_token": "saf_pc_moj"})
    return b


def _pocakaj(pogoj, najvec: float = 5.0) -> bool:
    konec = time.monotonic() + najvec
    while time.monotonic() < konec:
        if pogoj():
            return True
        time.sleep(0.01)
    return bool(pogoj())


class _Osnova(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.b = _backend(self._td.name)
        self.dogodki = []
        self.b.dodaj_poslusalca(lambda vrsta, podatki: self.dogodki.append((vrsta, podatki)))
        self._zaplata_zetona = mock.patch.object(self.b, "_zeton_http", return_value="saf_pc_moj")
        self._zaplata_zetona.start()

    def tearDown(self):
        self._zaplata_zetona.stop()
        self._td.cleanup()

    def _deljenja(self):
        return [p for v, p in self.dogodki if v == "deljenje"]


class Besedilo(_Osnova):
    """»Poslji besedilo«: prek sredisca, z izidom na plosci."""

    def _poslji(self, besedilo="Živjo", cilj="n-tel"):
        self.assertTrue(self.b.poslji_besedilo(cilj, besedilo))
        self.assertTrue(_pocakaj(lambda: bool(self._deljenja()) and self._deljenja()[-1]["stanje"] != "posiljam"))
        return self._deljenja()

    def test_poslano(self):
        with mock.patch.object(CB.link_deljenje, "poslji_besedilo", return_value=(True, {})) as klic:
            d = self._poslji("  Živjo, telefon  ")
        klic.assert_called_once_with(HUB, "saf_pc_moj", ODTIS, self.b.device_id, "n-tel", "Živjo, telefon")
        self.assertEqual(d, [
            {"vrsta": "besedilo", "stanje": "posiljam", "cilj": "n-tel", "ime": "", "sporocilo": "", "koda": "", "zasedenaOd": ""},
            {"vrsta": "besedilo", "stanje": "poslano", "cilj": "n-tel", "ime": "", "sporocilo": "", "koda": "", "zasedenaOd": ""},
        ])

    def test_napaka_pove_razlog(self):
        napaka = {"sporocilo": "Ciljna naprava ni povezana.", "koda": "naprava_ni_povezana", "zasedenaOd": ""}
        with mock.patch.object(CB.link_deljenje, "poslji_besedilo", return_value=(False, napaka)):
            d = self._poslji()
        self.assertEqual((d[-1]["stanje"], d[-1]["koda"], d[-1]["sporocilo"]),
                         ("napaka", "naprava_ni_povezana", "Ciljna naprava ni povezana."))

    def test_starejse_sredisce_dobi_sporocilo_po_povezavi(self):
        """Sredisce brez poti /cast/share/text (starejsi Safeer na napravi, ki je sredisce): kot doslej po povezavi."""
        ne_zna = {"sporocilo": "Središče tega še ne zna.", "koda": "sredisce_ne_zna", "zasedenaOd": ""}
        self.b.povezava = types.SimpleNamespace(tece=True, poslji=mock.Mock(return_value=True))
        with mock.patch.object(CB.link_deljenje, "poslji_besedilo", return_value=(False, ne_zna)):
            d = self._poslji("Živjo")
        self.assertEqual(d[-1]["stanje"], "poslano")
        sporocilo = self.b.povezava.poslji.call_args[0][0]
        self.assertEqual((sporocilo["type"], sporocilo["target"], sporocilo["payload"]), ("share.text", "n-tel", {"text": "Živjo"}))

    def test_starejse_sredisce_brez_povezave_je_napaka(self):
        ne_zna = {"sporocilo": "Središče tega še ne zna.", "koda": "sredisce_ne_zna", "zasedenaOd": ""}
        with mock.patch.object(CB.link_deljenje, "poslji_besedilo", return_value=(False, ne_zna)):
            d = self._poslji()
        self.assertEqual((d[-1]["stanje"], d[-1]["koda"]), ("napaka", "sredisce_ne_zna"))

    def test_brez_sredisca(self):
        self.b.nastavitve.pop("hub_fp")
        with mock.patch.object(CB.link_deljenje, "poslji_besedilo") as klic:
            d = self._poslji()
        klic.assert_not_called()
        self.assertEqual((d[-1]["stanje"], d[-1]["koda"]), ("napaka", "hub_ni_znan"))

    def test_prazno_besedilo_ali_brez_cilja_ne_zacne(self):
        self.assertFalse(self.b.poslji_besedilo("n-tel", "   "))
        self.assertFalse(self.b.poslji_besedilo("", "Živjo"))
        time.sleep(0.05)
        self.assertEqual(self.dogodki, [])
        self.assertEqual(self.b.poslji_besedilo_napravi("n-tel", " ")[1]["koda"], "prazno_besedilo")


class Preimenovanje(_Osnova):
    def test_uspeh_pove_strani(self):
        self.b.naprave = [{"id": "n-moj-control", "ime": "Staro"}]
        with mock.patch.object(CB.link_deljenje, "preimenuj_napravo", return_value=(True, "Pisarna", {})):
            izid = self.b.preimenuj_napravo("n-moj-control", "Pisarna")
        self.assertEqual(izid, {"ok": True, "ime": "Pisarna", "message": ""})
        self.assertEqual([v for v, _ in self.dogodki], ["naprave", "preimenovano"])
        self.assertEqual(self.dogodki[-1][1], {"id": "n-moj-control", "ime": "Pisarna"})
        self.assertEqual(self.b.naprave[0]["ime"], "Pisarna")

    def test_neuspeh_pove_razlog(self):
        napaka = {"sporocilo": "Naprava ni v krogu zaupanja.", "koda": "naprava_ni_v_krogu", "zasedenaOd": ""}
        with mock.patch.object(CB.link_deljenje, "preimenuj_napravo", return_value=(False, "", napaka)):
            izid = self.b.preimenuj_napravo("n-x", "Pisarna")
        self.assertFalse(izid["ok"])
        self.assertEqual(self.dogodki, [("napaka", {"koda": "preimenovanje_ni_uspelo",
                                                     "sporocilo": "Naprava ni v krogu zaupanja."})])


class Zaslon(_Osnova):
    def test_stanje_v_obliki_strani(self):
        self.b._na_spremembo_zaslona({"tece": True, "cilj": "n-tv", "ime": "Televizor", "napaka": "", "koda": "", "zasedenaOd": ""})
        self.b._na_spremembo_zaslona({"tece": False, "cilj": "n-tv", "ime": "Televizor", "napaka": "Naprava je zasedena.",
                                      "koda": "naprava_zasedena", "zasedenaOd": "Telefon"})
        d = self._deljenja()
        self.assertEqual((d[0]["vrsta"], d[0]["stanje"], d[0]["tece"], d[0]["ime"]), ("zaslon", "tece", True, "Televizor"))
        self.assertEqual((d[1]["stanje"], d[1]["tece"], d[1]["sporocilo"], d[1]["napaka"], d[1]["koda"], d[1]["zasedenaOd"]),
                         ("koncano", False, "Naprava je zasedena.", "Naprava je zasedena.", "naprava_zasedena", "Telefon"))

    def test_brez_sredisca_je_napaka_ne_cakanje(self):
        self.b.nastavitve.pop("hub_fp")
        self.assertFalse(self.b.zacni_deljenje_zaslona("n-tv", "Televizor"))
        d = self._deljenja()
        self.assertEqual((d[-1]["vrsta"], d[-1]["stanje"], d[-1]["tece"]), ("zaslon", "napaka", False))
        self.assertTrue(d[-1]["sporocilo"])

    def test_deljenje_dobi_zeton_za_klice_http(self):
        ustvarjen = {}

        class Deljenje:
            def __init__(self, hub, zeton, odtis, moj_id, cilj, ime, ob_spremembi=None, navidezni_zaslon=None):
                ustvarjen.update(zeton=zeton, ob_spremembi=ob_spremembi)

            def zacni(self):
                pass

            def ustavi(self):
                pass

        self._zaplata_zetona.stop()
        try:
            with mock.patch.object(CB, "_WindowsDeljenjeZaslona", Deljenje), \
                    mock.patch.object(self.b, "_zeton_http", return_value="saf_seja_nova"):
                self.assertTrue(self.b.zacni_deljenje_zaslona("n-tv", "Televizor"))
        finally:
            self._zaplata_zetona.start()
        self.assertEqual(ustvarjen["zeton"], "saf_seja_nova")
        ustvarjen["ob_spremembi"]({"tece": True, "cilj": "n-tv", "ime": "Televizor", "napaka": ""})
        self.assertEqual(self._deljenja()[-1]["stanje"], "tece")


class PrejetoBesedilo(_Osnova):
    def _prejmi(self, **sporocilo):
        self.b._na_sporocilo(dict({"type": "share.text"}, **sporocilo))
        return [p for v, p in self.dogodki if v == "prejeto"]

    def test_ime_iz_sporocila(self):
        p = self._prejmi(sender="n-tel", sender_name="Telefon", payload={"text": "https://example.org/a"})
        self.assertEqual(p, [{"vrsta": "besedilo", "od": "Telefon", "besedilo": "https://example.org/a"}])
        self.assertEqual(self.dogodki[0], ("besedilo", {"text": "https://example.org/a"}), "stari dogodek ostane")

    def test_ime_iz_seznama_naprav_ali_id(self):
        self.b.naprave = [{"id": "n-tel", "ime": "Telefon Ana"}]
        self.assertEqual(self._prejmi(sender="n-tel", payload={"text": "a"})[-1]["od"], "Telefon Ana")
        self.assertEqual(self._prejmi(sender="n-neznan", payload={"text": "a"})[-1]["od"], "n-neznan")
        self.assertEqual(self._prejmi(payload={"text": "a"})[-1]["od"], "naprava")

    def test_prazno_se_ne_pokaze_dolgo_se_skrajsa(self):
        self.assertEqual(self._prejmi(sender="n-tel", payload={"text": "   "}), [])
        self.assertEqual(self._prejmi(sender="n-tel", payload="ni slovar"), [])
        dolgo = self._prejmi(sender="n-tel", payload={"text": "a" * 9000})[-1]["besedilo"]
        self.assertEqual(len(dolgo), CB.NAJVEC_PREJETEGA_BESEDILA)


class DogovorSStranjo(unittest.TestCase):
    """Imena polj in stanj, ki jih zaledje oddaja, so tista, ki jih stran bere (assets/link/link.js)."""

    def test_stran_bere_ta_polja(self):
        js = (KOREN / "assets" / "link" / "link.js").read_text(encoding="utf-8")
        for kos in ('vrsta === "deljenje"', 'vrsta === "prejeto"', 'vrsta === "preimenovano"',
                    'p.stanje === "posiljam"', 'p.stanje === "poslano"', 'p.stanje === "napaka"',
                    'p.vrsta === "zaslon"', 'p.stanje === "tece"', 'p.vrsta === "datoteka"', 'p.vrsta === "besedilo"',
                    "p.odstotek", "p.sporocilo", "p.koda", "p.zasedenaOd", "p.cilj"):
            self.assertIn(kos, js, "stran tega ne bere vec: " + kos)

    def test_safeer_os_izid_posiljanja_samo_za_datoteke(self):
        vir = (KOREN / "windows" / "safeer_windows" / "os_app.py").read_text(encoding="utf-8")
        blok = vir[vir.index('if (vrsta == "deljenje"'):vir.index('self.poslji_dogodek("posiljanjeKoncano"')]
        self.assertIn('podatki.get("vrsta", "datoteka") == "datoteka"', blok)


class OknoPrejetegaBesedila(unittest.TestCase):
    """Safeer OS: besedilo z druge naprave v majhnem oknu v kotu (Kopiraj, Odpri za povezavo, Zapri)."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        okno = os_app.SafeerOsWindow
        self.odprto = []
        self.s = types.SimpleNamespace(_pasica_besedila=None, _BESEDILO_GUMBI=okno._BESEDILO_GUMBI,
                                       NAJVEC_PRIKAZANEGA_BESEDILA=okno.NAJVEC_PRIKAZANEGA_BESEDILA,
                                       _odpri_notranji_splet=self.odprto.append)
        self.s._umakni_besedilo = lambda o=None: okno._umakni_besedilo(self.s, o)
        self._pokazi = lambda od, besedilo: okno._pokazi_besedilo(self.s, od, besedilo)

    def tearDown(self):
        os_app.SafeerOsWindow._umakni_besedilo(self.s)
        self.app.processEvents()

    def _gumb(self, ime):
        return self.s._pasica_besedila.findChild(QPushButton, ime)

    def test_besedilo_in_gumbi(self):
        with mock.patch.object(os_app, "_jezik_oken", return_value="sl"):
            self._pokazi("Telefon", "Kupi mleko <b>in</b> kruh")
        okno = self.s._pasica_besedila
        self.assertIsNotNone(okno)
        self.assertEqual(okno.findChild(QLabel, "od").text(), "Telefon")
        self.assertEqual(okno.findChild(QLabel, "besedilo").text(), "Kupi mleko <b>in</b> kruh")
        self.assertEqual((self._gumb("kopiraj").text(), self._gumb("zapri").text()), ("Kopiraj", "Zapri"))
        self.assertIsNone(self._gumb("odpri"), "navadno besedilo ni povezava")

    def test_povezava_ima_odpri(self):
        with mock.patch.object(os_app, "_jezik_oken", return_value="en"):
            self._pokazi("Phone", "https://example.org/pot?a=1")
        self.assertEqual(self._gumb("odpri").text(), "Open")
        self._gumb("odpri").click()
        self.assertEqual(self.odprto, ["https://example.org/pot?a=1"])
        self.assertIsNone(self.s._pasica_besedila, "po kliku se okno umakne")

    def test_besedilo_s_presledkom_ni_povezava(self):
        self._pokazi("Telefon", "https://example.org in se kaj")
        self.assertIsNone(self._gumb("odpri"))

    def test_kopiraj_vzame_celo_besedilo(self):
        dolgo = "vrstica " * 200
        self._pokazi("Telefon", dolgo)
        prikazano = self.s._pasica_besedila.findChild(QLabel, "besedilo").text()
        self.assertLess(len(prikazano), len(dolgo.strip()))
        self.assertTrue(prikazano.endswith("…"))
        self._gumb("kopiraj").click()
        self.assertEqual(QApplication.clipboard().text(), dolgo.strip())
        self.assertIsNone(self.s._pasica_besedila)

    def test_novo_besedilo_zamenja_prejsnje_prazno_ne_odpre(self):
        self._pokazi("Telefon", "prvo")
        prvo = self.s._pasica_besedila
        self._pokazi("Tablica", "drugo")
        self.assertIsNot(self.s._pasica_besedila, prvo)
        self.assertEqual(self.s._pasica_besedila.findChild(QLabel, "besedilo").text(), "drugo")
        self._pokazi("Tablica", "   ")
        self.assertIsNone(self.s._pasica_besedila)

    def test_gumbi_v_sestih_jezikih(self):
        self.assertEqual(sorted(os_app.SafeerOsWindow._BESEDILO_GUMBI), ["de", "en", "es", "fr", "it", "sl"])
        self.assertTrue(all(len(v) == 3 and all(v) for v in os_app.SafeerOsWindow._BESEDILO_GUMBI.values()))

    def test_okno_ne_vzame_fokusa(self):
        from PySide6.QtCore import Qt
        self._pokazi("Telefon", "besedilo")
        okno = self.s._pasica_besedila
        self.assertTrue(okno.windowFlags() & Qt.WindowDoesNotAcceptFocus)
        self.assertTrue(okno.testAttribute(Qt.WA_ShowWithoutActivating))


class DogodekDoOkna(unittest.TestCase):
    """os_app: dogodek »prejeto« z besedilom gre v okno; izid posiljanja besedila ni »datoteka je poslana«."""

    def _okno(self):
        poslano, razporejeno = [], []
        s = types.SimpleNamespace(poslji_dogodek=lambda vrsta, podatki: poslano.append((vrsta, podatki)),
                                  dispatcher=types.SimpleNamespace(dispatch=lambda fn: razporejeno.append(fn)),
                                  _pokazi_besedilo=mock.Mock())
        return s, poslano, razporejeno

    def test_prejeto_besedilo(self):
        s, poslano, razporejeno = self._okno()
        os_app.SafeerOsWindow._na_dogodek_linka(s, "prejeto", {"vrsta": "besedilo", "od": "Telefon", "besedilo": "Živjo"})
        self.assertEqual(len(razporejeno), 1)
        razporejeno[0]()
        s._pokazi_besedilo.assert_called_once_with("Telefon", "Živjo")

    def test_prejeta_datoteka_ne_odpre_okna_z_besedilom(self):
        s, poslano, razporejeno = self._okno()
        os_app.SafeerOsWindow._na_dogodek_linka(s, "prejeto", {"vrsta": "datoteka", "od": "Telefon", "ime": "a.txt", "mapa": "x"})
        self.assertEqual(razporejeno, [])

    def test_izid_samo_za_datoteke(self):
        s, poslano, _ = self._okno()
        d = os_app.SafeerOsWindow._na_dogodek_linka
        d(s, "deljenje", {"vrsta": "besedilo", "stanje": "poslano", "cilj": "n-tel", "ime": ""})
        d(s, "deljenje", {"vrsta": "zaslon", "stanje": "koncano", "cilj": "n-tv", "ime": "TV", "tece": False})
        d(s, "deljenje", {"vrsta": "datoteka", "stanje": "posiljam", "cilj": "n-tel", "ime": "a.txt", "tece": True})
        self.assertEqual(poslano, [])
        d(s, "deljenje", {"vrsta": "datoteka", "stanje": "poslano", "cilj": "n-tel", "ime": "a.txt", "tece": False,
                          "uspeh": True, "napaka": ""})
        self.assertEqual(poslano, [("posiljanjeKoncano", {"ime": "a.txt", "cilj": "n-tel", "uspeh": True, "napaka": ""})])


if __name__ == "__main__":
    unittest.main()
