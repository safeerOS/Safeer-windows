"""Plosca »Deli z …« na Windows pove, kaj se je zgodilo; prejeto besedilo se pokaze.

Stran Safeer Controla (assets/link/link.js) je ista kot na Linuxu in bere dogodke v obliki Safeer Controla za Linux.
Zaledje za Windows je oddajalo druga polja ali nic. Videno 5. 10. 2026 na testnem racunalniku: datoteka je prisla na
telefon, plosca pa ni pokazala ne napredka ne »Poslano«; po »Poslji besedilo« je ostalo »Pošiljam …«; besedilo, ki ga
je racunalniku poslala druga naprava, se ni pokazalo nikjer.
"""
import inspect
import io
import os
import sys
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
SOSED_NASLOV = "wss://10.0.0.7:8990/cast/ws"


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

    def test_deljenje_izbere_sredisce_v_delovni_niti(self):
        """Klic z mostu ne caka na omrezje: sejo pri sredisci naprave dobi sele nit deljenja."""
        ustvarjen = {}

        class Deljenje:
            def __init__(self, hub, zeton, odtis, moj_id, cilj, ime, ob_spremembi=None, sredisce=None):
                ustvarjen.update(zeton=zeton, cilj=cilj, ob_spremembi=ob_spremembi, sredisce=sredisce)

            @staticmethod
            def zajem_na_voljo():
                return True, ""

            def zacni(self):
                pass

            def ustavi(self):
                pass

        with mock.patch.object(CB, "_WindowsDeljenjeZaslona", Deljenje), \
                mock.patch.object(CB.link_hub, "seja_s_podpisom") as seja, \
                mock.patch.object(self.b, "_sredisce_naprave") as sredisce_naprave:
            self.assertTrue(self.b.zacni_deljenje_zaslona("n-tv", "Televizor"))
            seja.assert_not_called()
            sredisce_naprave.assert_not_called()
        self.assertEqual((ustvarjen["zeton"], ustvarjen["cilj"]), ("", "n-tv"))
        ustvarjen["ob_spremembi"]({"tece": True, "cilj": "n-tv", "ime": "Televizor", "napaka": ""})
        self.assertEqual(self._deljenja()[-1]["stanje"], "tece")
        with mock.patch.object(self.b, "_sredisce_naprave", return_value=((SOSED_NASLOV, "odtis-tv"), "")), \
                mock.patch.object(CB.link_hub, "seja_s_podpisom", return_value="seja-pri-tv"):
            self.assertEqual(ustvarjen["sredisce"](), ((SOSED_NASLOV, "seja-pri-tv", "odtis-tv", self.b.device_id),
                                                       {"pri_napravi": True}))

    def test_sredisce_naprave_dobi_sejo_s_podpisom(self):
        with mock.patch.object(self.b, "_sredisce_naprave", return_value=((SOSED_NASLOV, "odtis-tv"), "")), \
                mock.patch.object(CB.link_hub, "seja_s_podpisom", return_value="seja-pri-tv") as seja:
            izbrano, napaka = self.b._sredisce_za_zaslon("n-tv")
        seja.assert_called_once_with(SOSED_NASLOV, self.b.device_id, "odtis-tv", self.b.device_ime)
        self.assertEqual((izbrano, napaka), ((SOSED_NASLOV, "seja-pri-tv", "odtis-tv", self.b.device_id), {"pri_napravi": True}))

    def test_sredisce_naprave_brez_seje_je_napaka(self):
        with mock.patch.object(self.b, "_sredisce_naprave", return_value=((SOSED_NASLOV, "odtis-tv"), "")), \
                mock.patch.object(CB.link_hub, "seja_s_podpisom", return_value=None):
            izbrano, napaka = self.b._sredisce_za_zaslon("n-tv")
        self.assertIsNone(izbrano)
        self.assertEqual(napaka["koda"], "sredisce_naprave_ni_dosegljivo")

    def test_naprava_pri_lastnem_sredisci_dobi_zaslon_od_njega(self):
        """Naprava brez svojega sredisca (prijavljena pri nasem): od 1.0.40 ji zaslon pokaze nase sredisce - do
        1.0.39 ga sredisce racunalnika ni posredovalo (»Ta naprava še ne more prikazati zaslona ...«)."""
        with mock.patch.object(self.b, "_sredisce_naprave", return_value=(None, "")), \
                mock.patch.object(self.b, "_gostimo_lokalno", return_value=True):
            izbrano, napaka = self.b._sredisce_za_zaslon("n-x")
        self.assertEqual((izbrano, napaka), ((HUB, "saf_pc_moj", ODTIS, self.b.device_id), {}))

    def test_brez_zetona_pri_lastnem_sredisci(self):
        self._zaplata_zetona.stop()
        try:
            with mock.patch.object(self.b, "_sredisce_naprave", return_value=(None, "")), \
                    mock.patch.object(self.b, "_zeton_http", return_value=None):
                izbrano, napaka = self.b._sredisce_za_zaslon("n-x")
        finally:
            self._zaplata_zetona.start()
        self.assertIsNone(izbrano)
        self.assertEqual(napaka["koda"], "hub_ni_znan")

    def test_prijavljeni_na_tuje_sredisce_delimo_prek_njega(self):
        with mock.patch.object(self.b, "_sredisce_naprave", return_value=(None, "")), \
                mock.patch.object(self.b, "_gostimo_lokalno", return_value=False):
            izbrano, napaka = self.b._sredisce_za_zaslon("n-tv")
        self.assertEqual((izbrano, napaka), ((HUB, "saf_pc_moj", ODTIS, self.b.device_id), {}))

    def test_naprava_dva_skoka_dalec(self):
        with mock.patch.object(self.b, "_sredisce_naprave", return_value=(None, "naprava_pri_drugem_srediscu")):
            izbrano, napaka = self.b._sredisce_za_zaslon("n-tv")
        self.assertIsNone(izbrano)
        self.assertEqual(napaka["koda"], "naprava_pri_drugem_srediscu")

    def _okvir(self, velikost, barva=(10, 120, 200)):
        from PIL import Image
        d = CB._WindowsDeljenjeZaslona(HUB, "", ODTIS, "n-moj", "n-tv", "TV")
        with mock.patch("PIL.ImageGrab.grab", return_value=Image.new("RGB", velikost, barva)) as zajem:
            okvir = d._okvir()
        zajem.assert_called_once_with()
        return Image.open(io.BytesIO(okvir))

    def test_deli_pravi_zaslon_pomanjsan(self):
        """Gledalec dobi zaslon racunalnika (zajem), ne narisane slike navideznega namizja."""
        slika = self._okvir((2560, 1440))
        self.assertEqual((slika.format, slika.size), ("JPEG", (1280, 720)))
        r, g, m = slika.convert("RGB").getpixel((640, 360))
        self.assertTrue(abs(r - 10) < 12 and abs(g - 120) < 12 and abs(m - 200) < 12, (r, g, m))

    def test_manjsi_zaslon_ostane_pokoncen_se_pomanjsa_po_visini(self):
        self.assertEqual(self._okvir((1024, 768)).size, (1024, 768))
        self.assertEqual(self._okvir((1440, 2560)).size, (720, 1280))

    def test_narisanega_namizja_ne_posilja_vec(self):
        vir = inspect.getsource(CB._WindowsDeljenjeZaslona)
        self.assertNotIn("zajemi_posnetek(", vir.split('"""')[2])
        self.assertIn("ImageGrab.grab()", vir)

    def test_brez_pillow_pove_da_zajema_ni(self):
        with mock.patch.dict(sys.modules, {"PIL": None}):
            self.assertEqual(CB._WindowsDeljenjeZaslona.zajem_na_voljo(), (False, "Zajem zaslona na tem računalniku ni na voljo."))
            self.assertFalse(self.b.zacni_deljenje_zaslona("n-tv", "Televizor"))
        d = self._deljenja()[-1]
        self.assertEqual((d["vrsta"], d["stanje"], d["koda"], d["tece"]), ("zaslon", "napaka", "ni_zajema", False))
        self.assertEqual(CB._WindowsDeljenjeZaslona.zajem_na_voljo(), (True, ""))


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



class _TakojNit:
    """Namesto niti: delo opravi ob start(), da preizkus vidi izid brez cakanja."""

    def __init__(self, target=None, **_k):
        self._delo = target

    def start(self):
        self._delo()


class SprejemZaslona(_Osnova):
    """share.screen z druge naprave: stran gledalca je pri sredisci, ki je deljenje sprejelo.

    Izmerjeno 5. 10. 2026 (1.0.39): telefon je deljenje zacel pri SVOJEM sredisci, racunalnik je stran iskal pri svojem
    in v Spletu odprl {"error": "Ni te poti."}; konec, ki je prisel takoj za zacetkom, zavihka ni zaprl."""

    POT = "/cast/screen/abc/view?k=KLJUC"
    PRI_TELEFONU = ("https://10.0.0.7:8990" + POT, "odtis-telefona")

    def _sporocilo(self, dejanje="start", id_="abc", **tovor):
        telo = {"action": dejanje, "id": id_}
        if dejanje == "start":
            telo["path"] = self.POT
        telo.update(tovor)
        return {"type": "share.screen", "sender": "n-tel", "sender_name": "Telefon", "payload": telo}

    def _prejmi(self, sporocilo, najdeno=PRI_TELEFONU, ob_iskanju=None, sredisce=((SOSED_NASLOV, "odtis-telefona"), "")):
        self.iskano = None

        def najdi(sredisca, pot):
            self.iskano = (list(sredisca), pot)
            if ob_iskanju:
                ob_iskanju()
            return najdeno
        with mock.patch.object(CB.link_deljenje, "gledalec_pri_srediscih", side_effect=najdi), \
                mock.patch.object(self.b, "_sredisce_naprave", return_value=sredisce) as sredisce_naprave, \
                mock.patch.object(CB.threading, "Thread", _TakojNit):
            self.b._prejmi_deljenje("share.screen", sporocilo)
        return sredisce_naprave

    def _zasloni(self):
        return [p for v, p in self.dogodki if v == "zaslon"]

    def test_stran_gledalca_isce_pri_nasem_in_pri_posiljateljevem_sredisci(self):
        sredisce_naprave = self._prejmi(self._sporocilo())
        sredisce_naprave.assert_called_once_with("n-tel")
        self.assertEqual(self.iskano, ([(HUB, ODTIS), (SOSED_NASLOV, "odtis-telefona")], self.POT))
        self.assertEqual(self._zasloni(), [{"od": "Telefon", "dejanje": "start", "url": self.PRI_TELEFONU[0],
                                            "odtis": "odtis-telefona", "id": "abc"}])

    def test_posiljatelj_brez_svojega_sredisca(self):
        self._prejmi(self._sporocilo(), najdeno=("https://127.0.0.1:45678" + self.POT, ODTIS), sredisce=(None, ""))
        self.assertEqual(self.iskano[0], [(HUB, ODTIS)])
        self.assertEqual(self._zasloni()[-1]["url"], "https://127.0.0.1:45678" + self.POT)

    def test_strani_ni_nikjer_ne_odda_zacetka(self):
        self._prejmi(self._sporocilo(), najdeno=("", ""))
        self.assertEqual(self._zasloni(), [], "prazna stran z napako je slabsa kot nic")

    def test_konec_med_iskanjem_zacetka_ne_odda(self):
        self._prejmi(self._sporocilo(), ob_iskanju=lambda: self.b._prejmi_deljenje("share.screen", self._sporocilo("stop")))
        self.assertEqual([z["dejanje"] for z in self._zasloni()], ["stop"])

    def test_novo_deljenje_med_iskanjem_starega(self):
        self._prejmi(self._sporocilo(), ob_iskanju=lambda: setattr(self.b, "_gledani_zaslon_id", "novejse"))
        self.assertEqual(self._zasloni(), [])

    def test_konec_drugega_deljenja_gledalca_ne_zapre(self):
        self._prejmi(self._sporocilo())
        self._prejmi(self._sporocilo("stop", id_="drugo"))
        self.assertEqual([z["dejanje"] for z in self._zasloni()], ["start"])
        self._prejmi(self._sporocilo("stop"))
        self.assertEqual(self._zasloni()[-1], {"od": "Telefon", "dejanje": "stop", "url": "", "odtis": "", "id": "abc"})
        self.assertEqual(self.b._gledani_zaslon_id, "")

    def test_konec_brez_gledanja_se_vseeno_odda(self):
        """Safeer OS zna konec brez odprtega gledalca prezreti; zaledje ga ne skriva."""
        self._prejmi(self._sporocilo("stop", id_="karkoli"))
        self.assertEqual([z["dejanje"] for z in self._zasloni()], ["stop"])

    def test_zacetek_brez_poti_ali_brez_sredisca(self):
        self._prejmi(self._sporocilo(path=""))
        self._prejmi(self._sporocilo(path="https://zlobno.example/stran"))
        self.b.nastavitve["hub_url"] = ""
        self._prejmi(self._sporocilo())
        self.assertEqual((self._zasloni(), self.iskano), ([], None))


if __name__ == "__main__":
    unittest.main()
