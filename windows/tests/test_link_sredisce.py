"""Safeer OS za Windows kot sredisce Safeer Linka: vabilo za novo napravo, zeton za klice HTTP, datoteke.

Do 1.0.38 je imel Windows svojo, starejso vejo jedra Safeer Linka: njegovo sredisce ni poznalo poti
/cast/pair/qr/invite, /cast/devices/leave, /cast/devices/rename in PUT /cast/file. Izmerjeno 5. 10. 2026 na testnem
racunalniku z 1.0.38: »Poveži novo napravo« -> »Kode ni bilo mogoče pripraviti« (povabi: hub_star), posiljanje
datoteke -> »Hub je odgovoril 501«. Od 1.0.39 je jedro isto kot na Linuxu. Ti preizkusi pokrivajo del, ki je samo na
Windows (safeer_windows/control_backend.py), in celo pot cez pravo sredisce na zanki (razred PravoSredisce).
"""
import hashlib
import json
import os
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

from core import link_deljenje, link_hub, link_hub_deljenje, link_hub_streznik, link_krog, link_mesh
from safeer_windows import control_backend as CB

ODTIS = "ab" * 32
LASTNO = "wss://127.0.0.1:45678/cast/ws"
TUJE = "wss://192.168.1.20:8990/cast/ws"
SOSED = ("wss://192.168.1.30:8990/cast/ws", "cd" * 32)
PRAVI_POSKUSI_SREDISCA = CB.POSKUSI_SREDISCA


class _Streznik:
    """Ponaredek HubStreznik: pravi Hub (zetoni, register naprav) z uro preizkusa, brez vticnika."""

    def __init__(self, mapa: str, ura) -> None:
        self.hub = link_hub_streznik.Hub(odtis=ODTIS, ura=ura, pot_zetonov=os.path.join(mapa, "hub-zetoni.json"))
        self.vrata = 45678
        self.odtis = ODTIS
        self.datoteke = None
        self._tece = False

    def zazeni(self) -> bool:
        self._tece = True
        return True

    def tece(self) -> bool:
        return self._tece

    def ustavi(self) -> None:
        self._tece = False


def _backend(td: str) -> "CB.SafeerControlBackend":
    b = CB.SafeerControlBackend(config_pot=os.path.join(td, "link.json"))
    b.nastavitve.clear()
    return b


def _pocakaj(pogoj, najvec: float = 5.0) -> bool:
    konec = time.monotonic() + najvec
    while time.monotonic() < konec:
        if pogoj():
            return True
        time.sleep(0.01)
    return bool(pogoj())


class ZetonHttpLastnoSredisce(unittest.TestCase):
    """Sredisce v istem procesu: zeton velja 24 ur, program pa tece vec dni - pretekli se zamenja sam."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.ura = [1_000_000.0]
        self.b = _backend(self._td.name)
        self.streznik = _Streznik(self._td.name, lambda: self.ura[0])
        self._zaplate = [
            mock.patch.object(CB.link_hub_streznik, "HubStreznik", lambda *a, **k: self.streznik),
            mock.patch.object(CB.link_hub, "seja_s_podpisom", side_effect=AssertionError("lastno sredisce: brez seje")),
        ]
        for z in self._zaplate:
            z.start()
        self.assertTrue(self.b.zagotovi_lokalni_hub())
        self.prvi = self.b.zeton()

    def tearDown(self):
        for z in self._zaplate:
            z.stop()
        self._td.cleanup()

    def test_veljaven_zeton_ostane(self):
        with mock.patch.object(self.b, "shrani_nastavitve") as shrani:
            self.assertEqual(self.b._zeton_http(), self.prvi)
            self.assertEqual(self.b._zeton_http(), self.prvi)
        shrani.assert_not_called()

    def test_pretekel_zeton_se_zamenja_in_shrani(self):
        self.ura[0] += link_hub_streznik.ZETON_VELJA_S + 1
        self.assertIsNone(self.streznik.hub.naprava_zetona(self.prvi), "po 24 urah sredisce zetona ne pozna vec")
        nov = self.b._zeton_http()
        self.assertNotEqual(nov, self.prvi)
        self.assertEqual(self.streznik.hub.naprava_zetona(nov), (self.b.device_id, self.b.device_ime))
        self.assertEqual(self.b.zeton(), nov)
        with open(self.b.config_pot, encoding="utf-8") as d:
            self.assertEqual(json.load(d)["control_token"], nov)
        self.assertEqual(self.b._zeton_http(), nov, "nov zeton velja, ne menjamo ga ob vsakem klicu")

    def test_zeton_ki_ga_sredisce_ne_pozna_se_zamenja(self):
        with self.streznik.hub._zaklep:
            self.streznik.hub._zetoni.clear()
        nov = self.b._zeton_http()
        self.assertNotEqual(nov, self.prvi)
        self.assertEqual(self.streznik.hub.naprava_zetona(nov)[0], self.b.device_id)

    def test_brez_novega_zetona_ostane_stari(self):
        self.ura[0] += link_hub_streznik.ZETON_VELJA_S + 1
        with mock.patch.object(self.streznik.hub, "zeton_lastne_naprave", return_value=None):
            self.assertEqual(self.b._zeton_http(), self.prvi)

    def test_brez_sredisca_ni_zetona(self):
        self.b.nastavitve.pop("hub_url")
        self.assertEqual(self.b._zeton_http(), "")

    def test_gostimo_lokalno(self):
        self.assertTrue(self.b._gostimo_lokalno())
        self.streznik.ustavi()
        self.assertFalse(self.b._gostimo_lokalno(), "ustavljeno sredisce ni vec nase")
        self.streznik.zazeni()
        self.b.nastavitve["hub_url"] = TUJE
        self.assertFalse(self.b._gostimo_lokalno(), "prijavljeni smo na sredisce druge naprave")
        self.b._lokalni_hub = None
        self.b.nastavitve["hub_url"] = LASTNO
        self.assertFalse(self.b._gostimo_lokalno(), "naslov zanke brez nasega sredisca (npr. drug program)")

    def test_backend_brez_init_ne_pade(self):
        """Stari preizkusi (test_vabilo_pin.py) naredijo backend brez __init__ in zakrpajo samo hub_url, zeton in
        hub_fp; nove metode zato ne smejo zahtevati polj, ki jih nastavi __init__."""
        b = CB.SafeerControlBackend.__new__(CB.SafeerControlBackend)
        with mock.patch.object(b, "hub_url", return_value=TUJE), mock.patch.object(b, "zeton", return_value="zeton"), \
                mock.patch.object(b, "hub_fp", return_value=ODTIS), \
                mock.patch.object(link_mesh, "sredisce_naprave", return_value=(None, "")) as klic:
            self.assertFalse(b._gostimo_lokalno())
            self.assertEqual(b._zeton_http(), "zeton")
            self.assertEqual(b._sredisce_naprave("n-x"), (None, ""))
        self.assertEqual(klic.call_args[0], (None, None, "n-x"))


class ZetonHttpTujeSredisce(unittest.TestCase):
    """Sredisce druge naprave: racunalnik v krogu zaupanja vzame sejni zeton s podpisom in ga pol ure hrani."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.b = _backend(self._td.name)
        self.b.nastavitve.update({"hub_url": TUJE, "hub_fp": ODTIS, "control_token": "saf_pc_seznanitev"})
        self.v_krogu = True
        self.seje = []

        def seja(naslov, device_id, odtis, ime=""):
            self.seje.append((naslov, device_id, odtis, ime))
            return "saf_seja_%d" % len(self.seje)

        self._zaplate = [
            mock.patch.object(link_krog, "lahko_s_podpisom", side_effect=lambda _id: self.v_krogu),
            mock.patch.object(CB.link_hub, "seja_s_podpisom", side_effect=seja),
        ]
        for z in self._zaplate:
            z.start()

    def tearDown(self):
        for z in self._zaplate:
            z.stop()
        self._td.cleanup()

    def test_v_krogu_dobi_sejo_s_podpisom(self):
        self.assertEqual(self.b._zeton_http(), "saf_seja_1")
        self.assertEqual(self.seje, [(TUJE, self.b.device_id, ODTIS, self.b.device_ime)])

    def test_seja_se_hrani(self):
        self.assertEqual([self.b._zeton_http() for _ in range(4)], ["saf_seja_1"] * 4)
        self.assertEqual(len(self.seje), 1, "vsak klic HTTP ne sme pomeniti nove prijave s podpisom")

    def test_po_izteku_hrambe_vzame_novo(self):
        self.b._zeton_http()
        seja, _velja_do, za = self.b._seja_http
        self.b._seja_http = (seja, time.monotonic() - 1.0, za)
        self.assertEqual(self.b._zeton_http(), "saf_seja_2")
        self.assertLess(CB.SEJA_HTTP_HRANIMO_S, 12 * 3600, "hraniti jo smemo manj casa, kot velja pri sredisci")

    def test_drugo_sredisce_ne_dobi_seje_prvega(self):
        self.b._zeton_http()
        drugo = "wss://192.168.1.77:8990/cast/ws"
        self.b.nastavitve["hub_url"] = drugo
        self.assertEqual(self.b._zeton_http(), "saf_seja_2")
        self.assertEqual(self.seje[-1][0], drugo)

    def test_zunaj_kroga_ostane_zeton_seznanitve(self):
        self.v_krogu = False
        self.assertEqual(self.b._zeton_http(), "saf_pc_seznanitev")
        self.assertEqual(self.seje, [])

    def test_nezaupan_racunalnik_ne_podpisuje(self):
        self.b.nastavitve["zaupana"] = False
        self.assertEqual(self.b._zeton_http(), "saf_pc_seznanitev")
        self.assertEqual(self.seje, [])

    def test_brez_seje_ostane_zeton_seznanitve(self):
        with mock.patch.object(CB.link_hub, "seja_s_podpisom", return_value=None) as klic:
            self.assertEqual(self.b._zeton_http(), "saf_pc_seznanitev")
            self.assertEqual(self.b._zeton_http(), "saf_pc_seznanitev")
        self.assertEqual(klic.call_count, 2, "neuspele seje ne hranimo")
        with mock.patch.object(CB.link_hub, "seja_s_podpisom", side_effect=OSError("ni omrezja")):
            self.assertEqual(self.b._zeton_http(), "saf_pc_seznanitev")

    def test_vabilo_preimenovanje_in_odhod_gredo_s_sejo(self):
        with mock.patch.object(CB.link_hub, "povabi", return_value={"napaka": "ni_huba"}) as povabi, \
                mock.patch.object(CB.link_deljenje, "preimenuj_napravo", return_value=(False, "", {})) as preimenuj, \
                mock.patch.object(CB.link_hub, "odidi", return_value=True) as odidi:
            self.b._zacni_vabilo()
            self.b.preimenuj_napravo("n-tel", "Telefon")
            self.b.pozabi_napravo()
        self.assertEqual(povabi.call_args[0][:3], (TUJE, "saf_seja_1", ODTIS))
        self.assertEqual(preimenuj.call_args[0][:3], (TUJE, "saf_seja_1", ODTIS))
        self.assertEqual(odidi.call_args[0], (TUJE, "saf_seja_1", ODTIS))

    def test_preklic_vabila_tudi_brez_zetona_seznanitve(self):
        """Racunalnik, prijavljen samo s podpisom, je vabilo pustil na sredisci do izteka."""
        self.b.nastavitve.pop("control_token")
        self.b._vabilo = {"qr_id": "qr-7"}
        preklicano = threading.Event()
        with mock.patch.object(CB.link_hub, "preklici_vabilo", side_effect=lambda *a: preklicano.set()) as preklic:
            self.b.prekini_vabilo()
            self.assertTrue(preklicano.wait(3))
        self.assertEqual(preklic.call_args[0], (TUJE, "saf_seja_1", ODTIS, "qr-7"))
        self.assertIsNone(self.b._vabilo)

    def test_brez_vabila_ni_preklica(self):
        with mock.patch.object(CB.link_hub, "preklici_vabilo") as preklic:
            self.b.prekini_vabilo()
            time.sleep(0.05)
        preklic.assert_not_called()


class PosljiDatotekoNapravi(unittest.TestCase):
    """Datoteka gre sredisci CILJNE naprave (prijava s podpisom), sicer nasemu."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.b = _backend(self._td.name)
        self.b.nastavitve.update({"hub_url": LASTNO, "hub_fp": ODTIS, "control_token": "saf_pc_moj"})
        self.pot = os.path.join(self._td.name, "slika.jpg")
        with open(self.pot, "wb") as f:
            f.write(b"abc")
        self.sredisce = (None, "")
        self.oddaja = mock.Mock(return_value=(True, {}))
        self.seja = mock.Mock(return_value="saf_seja_sosed")
        self._zaplate = [
            mock.patch.object(self.b, "_sredisce_naprave", side_effect=lambda _id: self.sredisce),
            mock.patch.object(self.b, "_zeton_http", return_value="saf_pc_moj"),
            mock.patch.object(CB.link_deljenje, "poslji_datoteko", self.oddaja),
            mock.patch.object(CB.link_hub, "seja_s_podpisom", self.seja),
        ]
        for z in self._zaplate:
            z.start()

    def tearDown(self):
        for z in self._zaplate:
            z.stop()
        self._td.cleanup()

    def test_naprava_pri_nasem_srediscu(self):
        napredek = []
        self.assertEqual(self.b.poslji_datoteko_napravi("n-tel", self.pot, napredek.append), (True, {}))
        self.oddaja.assert_called_once_with(LASTNO, "saf_pc_moj", ODTIS, self.b.device_id, "n-tel", self.pot,
                                            napredek.append)
        self.seja.assert_not_called()

    def test_naprava_s_svojim_srediscem_dobi_datoteko_tja(self):
        self.sredisce = (SOSED, "")
        self.b._lokalni_hub = types.SimpleNamespace(hub=types.SimpleNamespace(nas_id="n-moje-sredisce"),
                                                    tece=lambda: True)
        self.assertEqual(self.b.poslji_datoteko_napravi("n-tel", self.pot), (True, {}))
        self.seja.assert_called_once_with(SOSED[0], "n-moje-sredisce", SOSED[1], self.b.device_ime)
        self.oddaja.assert_called_once_with(SOSED[0], "saf_seja_sosed", SOSED[1], "n-moje-sredisce", "n-tel",
                                            self.pot, None)

    def test_brez_lastnega_sredisca_se_predstavi_z_id_naprave(self):
        self.sredisce = (SOSED, "")
        self.b.poslji_datoteko_napravi("n-tel", self.pot)
        self.assertEqual(self.seja.call_args[0][1], self.b.device_id)
        self.assertEqual(self.oddaja.call_args[0][3], self.b.device_id)

    def test_sredisce_naprave_ne_da_seje(self):
        self.sredisce = (SOSED, "")
        self.seja.return_value = None
        ok, napaka = self.b.poslji_datoteko_napravi("n-tel", self.pot)
        self.assertFalse(ok)
        self.assertEqual(napaka["koda"], "sredisce_naprave_ni_dosegljivo")
        self.assertEqual(napaka["sporocilo"], link_deljenje.SPOROCILA_SREDISCA["sredisce_naprave_ni_dosegljivo"])
        self.oddaja.assert_not_called()

    def test_naprava_dva_skoka_stran(self):
        self.sredisce = (None, "naprava_pri_drugem_srediscu")
        ok, napaka = self.b.poslji_datoteko_napravi("n-tel", self.pot)
        self.assertEqual((ok, napaka["koda"]), (False, "naprava_pri_drugem_srediscu"))
        self.assertEqual(napaka["sporocilo"], link_deljenje.SPOROCILA_SREDISCA["naprava_pri_drugem_srediscu"])
        self.oddaja.assert_not_called()
        self.seja.assert_not_called()

    def test_brez_zetona(self):
        with mock.patch.object(self.b, "_zeton_http", return_value=""):
            ok, napaka = self.b.poslji_datoteko_napravi("n-tel", self.pot)
        self.assertEqual((ok, napaka["koda"]), (False, "hub_ni_znan"))
        self.oddaja.assert_not_called()

    def _dogodki_posiljanja(self):
        dogodki = []
        self.b.dodaj_poslusalca(lambda vrsta, podatki: dogodki.append(podatki) if vrsta == "deljenje" else None)
        self.assertTrue(self.b.poslji_datoteko("n-tel", self.pot))
        self.assertTrue(_pocakaj(lambda: bool(dogodki) and dogodki[-1].get("tece") is False))
        return dogodki

    def test_vmesnik_dobi_napredek_in_uspeh(self):
        def oddaj(*a):
            a[6](40)
            a[6](100)
            return True, {}

        self.oddaja.side_effect = oddaj
        dogodki = self._dogodki_posiljanja()
        self.assertEqual([d.get("odstotek") for d in dogodki], [0, 40, 100, 100])
        # Oblika, ki jo bere stran Safeer Controla (vrsta, stanje ...), in stara polja za Safeer OS (tece, uspeh, napaka).
        self.assertEqual([(d["vrsta"], d["stanje"], d["tece"]) for d in dogodki],
                         [("datoteka", "posiljam", True)] * 3 + [("datoteka", "poslano", False)])
        self.assertEqual(dogodki[-1], {"vrsta": "datoteka", "stanje": "poslano", "cilj": "n-tel", "ime": "slika.jpg",
                                       "sporocilo": "", "koda": "", "zasedenaOd": "", "odstotek": 100,
                                       "tece": False, "uspeh": True, "napaka": ""})

    def test_vmesnik_dobi_razlog_neuspeha(self):
        self.sredisce = (None, "sredisce_naprave_ni_dosegljivo")
        dogodki = self._dogodki_posiljanja()
        self.assertEqual((dogodki[-1]["uspeh"], dogodki[-1]["odstotek"]), (False, 0))
        self.assertEqual(dogodki[-1]["napaka"], "Naprava v tem omrežju ni dosegljiva.")
        self.assertEqual((dogodki[-1]["stanje"], dogodki[-1]["koda"], dogodki[-1]["sporocilo"]),
                         ("napaka", "sredisce_naprave_ni_dosegljivo", "Naprava v tem omrežju ni dosegljiva."))

    def test_brez_povezave_ali_datoteke_ne_zacne(self):
        dogodki = []
        self.b.dodaj_poslusalca(lambda vrsta, podatki: dogodki.append(podatki))
        self.assertFalse(self.b.poslji_datoteko("n-tel", os.path.join(self._td.name, "ni-je.jpg")))
        self.assertFalse(self.b.poslji_datoteko("", self.pot))
        self.b.nastavitve.pop("hub_fp")
        self.assertFalse(self.b.poslji_datoteko("n-tel", self.pot))
        self.assertEqual(len(dogodki), 3)
        self.assertTrue(all(d["napaka"] and d["tece"] is False for d in dogodki))
        self.assertTrue(all((d["vrsta"], d["stanje"], d["sporocilo"]) == ("datoteka", "napaka", d["napaka"]) for d in dogodki))
        self.oddaja.assert_not_called()


class SredisceNaprave(unittest.TestCase):
    """Backend vprasa jedro (link_mesh.sredisce_naprave) s svojim srediscem in povezovalcem sosedov."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.b = _backend(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_s_tekocim_srediscem(self):
        hub, mesh = object(), object()
        self.b._lokalni_hub = types.SimpleNamespace(hub=hub, tece=lambda: True)
        self.b._mesh = mesh
        with mock.patch.object(link_mesh, "sredisce_naprave", return_value=(SOSED, "")) as klic:
            self.assertEqual(self.b._sredisce_naprave("n-tel"), (SOSED, ""))
        klic.assert_called_once_with(hub, mesh, "n-tel")

    def test_brez_sredisca_ali_ustavljeno(self):
        with mock.patch.object(link_mesh, "sredisce_naprave", return_value=(None, "")) as klic:
            self.b._sredisce_naprave("n-tel")
            self.b._lokalni_hub = types.SimpleNamespace(hub=object(), tece=lambda: False)
            self.b._sredisce_naprave("n-tel")
        self.assertEqual([k[0][0] for k in klic.call_args_list], [None, None])

    def test_napaka_jedra_pomeni_nase_sredisce(self):
        with mock.patch.object(link_mesh, "sredisce_naprave", side_effect=RuntimeError("x")):
            self.assertEqual(self.b._sredisce_naprave("n-tel"), (None, ""))


class KodaZaNovoNapravo(unittest.TestCase):
    """pair.code: nova naprava caka na kodo - racunalnik jo pokaze, kadar je ni ze pokazalo njegovo sredisce."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.b = _backend(self._td.name)
        self.b.nastavitve.update({"hub_url": TUJE, "hub_fp": ODTIS, "control_token": "saf_pc_x"})
        self._zaplata = mock.patch.object(CB.link_hub_streznik, "_obvestilo_kode")
        self.obvestilo = self._zaplata.start()

    def tearDown(self):
        self._zaplata.stop()
        self._td.cleanup()

    def _koda(self, **tovor):
        self.b._na_sporocilo({"type": "pair.code", "payload": tovor})

    def test_tuje_sredisce_pokaze_kodo(self):
        self._koda(code="123456", name="Telefon")
        self.obvestilo.assert_called_once_with("Telefon", "123456")

    def test_lastno_sredisce_je_kodo_ze_pokazalo(self):
        self.b.nastavitve["hub_url"] = LASTNO
        self.b._lokalni_hub = types.SimpleNamespace(hub=object(), tece=lambda: True)
        self._koda(code="123456", name="Telefon")
        self.obvestilo.assert_not_called()

    def test_neveljavna_koda_se_ne_pokaze(self):
        for koda in ("", "12345", "1234567", "12a456", "１２３４５６", "12345 ", None, 123456.5):
            self._koda(code=koda, name="Telefon")
        self.b._na_sporocilo({"type": "pair.code"})
        self.b._na_sporocilo({"type": "pair.code", "payload": "123456"})
        self.obvestilo.assert_not_called()

    def test_koda_kot_stevilo_in_dolgo_ime(self):
        self._koda(code=654321, name="T" * 200)
        self.obvestilo.assert_called_once_with("T" * 64, "654321")


class PrejemDatoteke(unittest.TestCase):
    """share.file: datoteko poiscemo najprej pri nasem sredisci, nato pri sredisci posiljatelja."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.b = _backend(self._td.name)
        self.b.nastavitve.update({"hub_url": LASTNO, "hub_fp": ODTIS, "control_token": "saf_pc_x"})
        self.sredisce = (None, "")
        self.izid = (os.path.join(self._td.name, "Račun (1).pdf"), "")
        self.dogodki = []
        self.b.dodaj_poslusalca(lambda vrsta, podatki: self.dogodki.append((vrsta, podatki)))
        self._zaplate = [
            mock.patch.object(self.b, "_sredisce_naprave", side_effect=lambda _id: self.sredisce),
            mock.patch.object(CB.link_deljenje, "prevzemi_pri_srediscih", side_effect=lambda *a, **k: self.izid),
            mock.patch.object(CB.link_deljenje, "prevzemi_datoteko",
                              side_effect=AssertionError("samo eno sredisce ni dovolj")),
        ]
        self.sredisce_naprave, self.prevzem, _ = [z.start() for z in self._zaplate]

    def tearDown(self):
        for z in self._zaplate:
            z.stop()
        self._td.cleanup()

    def _sporocilo(self, **tovor):
        self.b._na_sporocilo({"type": "share.file", "sender": "n-drugi-control", "sender_name": "Pisarna",
                              "payload": tovor})
        # Ob uspehu prideta dva dogodka (za Safeer OS in za stran Safeer Controla), ob neuspehu eden.
        return _pocakaj(lambda: len(self.dogodki) >= (2 if self.izid[0] else 1))

    def test_posiljatelj_z_lastnim_srediscem(self):
        self.sredisce = (SOSED, "")
        self.assertTrue(self._sporocilo(name="Račun.pdf", path="/cast/file/ab?k=cd", sha256="ef" * 32))
        self.sredisce_naprave.assert_called_once_with("n-drugi-control")
        self.assertEqual(self.prevzem.call_args[0],
                         ([(LASTNO, ODTIS), SOSED], "/cast/file/ab?k=cd", "Račun.pdf", "ef" * 32))
        self.assertEqual(self.dogodki, [
            ("prejetaDatoteka", {"od": "Pisarna", "ime": "Račun (1).pdf", "pot": self.izid[0], "uspeh": True, "napaka": ""}),
            ("prejeto", {"vrsta": "datoteka", "od": "Pisarna", "ime": "Račun (1).pdf", "mapa": self._td.name}),
        ])

    def test_posiljatelj_pri_nasem_srediscu(self):
        self.assertTrue(self._sporocilo(name="a.txt", path="/cast/file/ab?k=cd"))
        self.assertEqual(self.prevzem.call_args[0], ([(LASTNO, ODTIS)], "/cast/file/ab?k=cd", "a.txt", ""))

    def test_neuspeh_pove_razlog(self):
        self.izid = (None, "Hub je odgovoril 404")
        self.assertTrue(self._sporocilo(name="a.txt", path="/cast/file/ab?k=cd"))
        self.assertEqual(self.dogodki, [("prejetaDatoteka", {"od": "Pisarna", "ime": "a.txt", "pot": "", "uspeh": False,
                                                             "napaka": "Hub je odgovoril 404"})])

    def test_brez_poti_ali_sredisca_nic(self):
        self.assertFalse(self._sporocilo_hitro(name="a.txt"))
        self.b.nastavitve.pop("hub_url")
        self.assertFalse(self._sporocilo_hitro(name="a.txt", path="/cast/file/ab?k=cd"))
        self.prevzem.assert_not_called()

    def _sporocilo_hitro(self, **tovor):
        self.b._na_sporocilo({"type": "share.file", "sender": "n-drugi-control", "payload": tovor})
        return _pocakaj(lambda: bool(self.dogodki), 0.3)


class ZagonSredisca(unittest.TestCase):
    """Vrata sredisca se drzi kopija programa, ki se zapira (posodobitev, hiter ponovni zagon): nova kopija pocaka.

    Na Windows si sredisce vrat ne deli vec z drugim procesom, zato HubStreznik.zazeni() v tem primeru vrne False."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.b = _backend(self._td.name)
        self.streznik = _Streznik(self._td.name, time.time)
        self.izidi = []           # kaj vrne vsak naslednji zazeni(); ko zmanjka, uspe
        self.klicev = 0
        pravi_zazeni = self.streznik.zazeni

        def zazeni():
            self.klicev += 1
            if self.izidi and not self.izidi.pop(0):
                return False
            return pravi_zazeni()

        self.streznik.zazeni = zazeni
        self._zaplate = [
            mock.patch.object(CB.link_hub_streznik, "HubStreznik", lambda *a, **k: self.streznik),
            mock.patch.object(CB, "POSKUSI_SREDISCA", (0.01, 0.02, 0.03)),
        ]
        for z in self._zaplate:
            z.start()

    def tearDown(self):
        for z in self._zaplate:
            z.stop()
        self._td.cleanup()

    def test_prosta_vrata_brez_cakanja(self):
        self.assertTrue(self.b.zagotovi_lokalni_hub())
        self.assertEqual(self.klicev, 1)

    def test_stara_kopija_sprosti_vrata_med_cakanjem(self):
        self.izidi = [False, False]
        izid = self.b.zagotovi_lokalni_hub()
        self.assertEqual(izid, {"naslov": LASTNO, "fp": ODTIS, "lokalni": True})
        self.assertEqual(self.klicev, 3)
        self.assertEqual(self.streznik.hub.naprava_zetona(self.b.zeton())[0], self.b.device_id)

    def test_vrata_ostanejo_zasedena(self):
        self.izidi = [False] * 10
        self.assertIsNone(self.b.zagotovi_lokalni_hub())
        self.assertEqual(self.klicev, 4, "prvi poskus in po eden za vsak premor")
        self.assertIsNone(self.b._lokalni_hub)
        self.assertEqual(self.b.hub_url(), "", "brez sredisca ne zapisemo naslova zanke")

    def test_cakanje_je_omejeno(self):
        self.assertTrue(all(p > 0 for p in PRAVI_POSKUSI_SREDISCA))
        self.assertLessEqual(sum(PRAVI_POSKUSI_SREDISCA), 12.0)
        self.assertGreaterEqual(sum(PRAVI_POSKUSI_SREDISCA), 5.0, "stara kopija se zapira nekaj sekund")


class PravoSredisce(unittest.TestCase):
    """Cela pot: Safeer OS za Windows gosti pravo sredisce (TLS, HTTP) in ga uporablja z istimi klici kot v programu."""

    B = "n-bbbbbbbbbbbbbbbb"

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        nastavitve = os.path.join(cls.tmp.name, "nastavitve")
        os.makedirs(nastavitve)
        pravi = link_hub_streznik.HubStreznik
        cls.popravki = [
            mock.patch.object(link_krog, "_mapa_nastavitev", return_value=nastavitve),
            mock.patch.object(link_krog, "krog", return_value=link_krog.Krog(os.path.join(nastavitve, "krog.json"))),
            mock.patch.object(pravi, "_ze_gosti_lokalno", staticmethod(lambda: False)),
            mock.patch.dict(os.environ, {"SAFEER_HUB_DRUGI": "1"}),
            mock.patch.object(link_hub_streznik, "_obvestilo", lambda *a, **k: None),
            mock.patch.object(link_hub_streznik, "_obvestilo_kode", lambda *a, **k: None),
            mock.patch.object(CB.link_hub_streznik, "HubStreznik",
                              lambda *a, **k: pravi(tls_mapa=os.path.join(cls.tmp.name, "tls"))),
        ]
        for p in cls.popravki:
            p.start()
        cls.b = _backend(cls.tmp.name)
        try:
            if not cls.b.zagotovi_lokalni_hub():
                raise unittest.SkipTest("sredisca ni bilo mogoce zagnati")
        except BaseException:
            cls._pospravi()
            raise
        cls.hub = cls.b._lokalni_hub.hub
        cls.vrata = cls.b._lokalni_hub.vrata
        cls.zaloga = os.path.join(cls.tmp.name, "zaloga")
        cls.hub.deljenje = link_hub_deljenje.Deljenje(mapa=lambda: cls.zaloga)

    @classmethod
    def _pospravi(cls):
        try:
            cls.b.koncaj()
        except Exception:
            pass
        for p in reversed(cls.popravki):
            p.stop()
        cls.tmp.cleanup()

    @classmethod
    def tearDownClass(cls):
        cls._pospravi()

    def _klic(self):
        return self.b.hub_url(), self.b._zeton_http(), self.b.hub_fp()

    def test_sredisce_je_nase(self):
        self.assertEqual(self.b.hub_url(), "wss://127.0.0.1:%d/cast/ws" % self.vrata)
        self.assertTrue(self.b._gostimo_lokalno())
        self.assertEqual(self.hub.naprava_zetona(self.b.zeton()), (self.b.device_id, self.b.device_ime))

    def test_vabilo_ima_povezavo_kodo_in_naslov_v_omrezju(self):
        """»Poveži novo napravo«: do 1.0.38 je sredisce na Windows odgovorilo 404 (povabi -> hub_star)."""
        v = link_hub.povabi(*self._klic())
        self.assertNotIn("napaka", v)
        self.assertRegex(v["pin"], r"^\d{6}$")
        self.assertGreater(v["velja"], 60)
        self.assertIn("#j=%s&s=" % v["qr_id"], v["povezava"])
        self.assertIn("&f=%s&a=" % self.b.hub_fp().lower(), v["povezava"])
        naslov = v["povezava"].rsplit("&a=", 1)[1]
        self.assertTrue(naslov.endswith(":%d" % self.vrata), naslov)
        krajevni = link_hub_streznik._krajevni_ip()
        if not krajevni.startswith("127."):
            # Nova naprava sredisca ne sme iskati na sami sebi: v kodi je naslov racunalnika v domacem omrezju.
            self.assertEqual(naslov, "%s:%d" % (krajevni, self.vrata))
        self.assertEqual(link_hub.stanje_vabila(*self._klic(), v["qr_id"]), {"caka": True, "pridruzen": ""})
        link_hub.preklici_vabilo(*self._klic(), v["qr_id"])
        self.assertFalse(link_hub.stanje_vabila(*self._klic(), v["qr_id"]).get("caka"))

    def test_backend_poslje_vabilo_vmesniku(self):
        vabila = []
        poslusalec = lambda vrsta, podatki: vabila.append(podatki) if vrsta == "vabilo" else None  # noqa: E731
        self.b.dodaj_poslusalca(poslusalec)
        try:
            self.b.zacni_vabilo()
            self.assertTrue(_pocakaj(lambda: bool(vabila)), "stran ni dobila vabila")
            self.assertEqual(sorted(vabila[0]), ["pin", "svg", "velja"], vabila[0])
            self.assertRegex(vabila[0]["pin"], r"^\d{6}$")
            self.assertIn("<svg", vabila[0]["svg"])
            qr_id = str((self.b._vabilo or {}).get("qr_id") or "")
            self.assertTrue(qr_id)
            self.assertTrue(link_hub.stanje_vabila(*self._klic(), qr_id).get("caka"))
            self.b.prekini_vabilo()
            self.assertTrue(_pocakaj(lambda: not link_hub.stanje_vabila(*self._klic(), qr_id).get("caka")),
                            "zaprto okno mora vabilo preklicati tudi na sredisci")
        finally:
            self.b.prekini_vabilo()
            self.b.odstrani_poslusalca(poslusalec)

    def test_pretekel_zeton_ne_ustavi_vabila(self):
        """Program tece dlje kot 24 ur: stari zeton sredisce zavrne, backend ga zamenja sam."""
        star = self.b.zeton()
        with self.hub._zaklep:
            lastnik = self.hub._zetoni[star]
            self.hub._zetoni[star] = (lastnik[0], lastnik[1], self.hub.ura() - link_hub_streznik.ZETON_VELJA_S - 5)
        self.assertEqual(link_hub.povabi(self.b.hub_url(), star, self.b.hub_fp()), {"napaka": "ni_seznanjena"})
        v = link_hub.povabi(*self._klic())
        self.assertRegex(v.get("pin", ""), r"^\d{6}$")
        self.assertNotEqual(self.b.zeton(), star)
        link_hub.preklici_vabilo(*self._klic(), v["qr_id"])

    def test_tuj_zeton_ne_dobi_vabila(self):
        self.assertEqual(link_hub.povabi(self.b.hub_url(), "saf_pc_izmisljen", self.b.hub_fp()),
                         {"napaka": "ni_seznanjena"})

    def test_datoteka_do_naprave_in_razlog_ce_ni_povezana(self):
        """Posiljanje datoteke: do 1.0.38 je sredisce na Windows odgovorilo 501."""
        vsebina = os.urandom(150_000) + "čšž\r\n\n".encode("utf-8")
        pot = os.path.join(self.tmp.name, "Počitnice 2026.bin")
        with open(pot, "wb") as f:
            f.write(vsebina)
        ok, napaka = self.b.poslji_datoteko_napravi(self.B, pot)
        self.assertEqual((ok, napaka.get("koda")), (False, "naprava_ni_povezana"))

        prejeto, prislo = [], threading.Event()
        p = link_hub.Povezava(self.b.hub_url(), self.hub.zeton_lastne_naprave(self.B, "Telefon"), self.B, "Telefon",
                              odtis=self.b.hub_fp(), v_krog=False)
        p.ob_sporocilu = lambda s: (prejeto.append(s), prislo.set()) if s.get("type") == "share.file" else None
        self.assertTrue(p.poveži())
        try:
            self.assertTrue(_pocakaj(lambda: getattr(self.hub.najdi(self.B), "povezava", None) is not None))
            odstotki = []
            ok, napaka = self.b.poslji_datoteko_napravi(self.B, pot, odstotki.append)
            self.assertTrue(ok, napaka)
            self.assertEqual(odstotki[-1], 100)
            self.assertTrue(prislo.wait(5), "cilj mora izvedeti za datoteko")
            sporocilo = prejeto[-1]
            tovor = sporocilo["payload"]
            self.assertEqual((sporocilo["sender"], tovor["name"], tovor["size"]),
                             (self.b.device_id, "Počitnice 2026.bin", len(vsebina)))
            self.assertEqual(tovor["sha256"], hashlib.sha256(vsebina).hexdigest())
            mapa = os.path.join(self.tmp.name, "prejeto")
            os.makedirs(mapa)
            cilj, razlog = link_deljenje.prevzemi_pri_srediscih([(self.b.hub_url(), self.b.hub_fp())], tovor["path"],
                                                                tovor["name"], tovor["sha256"], mapa=mapa)
            self.assertTrue(cilj, razlog)
            with open(cilj, "rb") as f:
                self.assertEqual(f.read(), vsebina, "datoteka mora priti cez sredisce bajt za bajtom enaka")
            self.assertEqual(os.listdir(self.zaloga), [], "prevzeta datoteka na sredisci ne ostane")
        finally:
            p.zapri()

    def test_preimenovanje_pride_do_sredisca(self):
        """Do 1.0.38: 404 brez kode (sredisce poti ni poznalo). Zdaj sredisce odgovori, da naprave ni v krogu."""
        izid = self.b.preimenuj_napravo("n-cccccccccccccccc", "Dnevna soba")
        self.assertEqual(izid, {"ok": False, "ime": "", "message": "Naprava ni v krogu zaupanja."})

    def test_odhod_pride_do_sredisca(self):
        zeton = self.hub.zeton_lastne_naprave("n-dddddddddddddddd", "Tablica")
        self.assertTrue(link_hub.odidi(self.b.hub_url(), zeton, self.b.hub_fp()))
        self.assertIsNone(self.hub.naprava_zetona(zeton), "po odhodu sredisce zetona ne pozna vec")
        self.assertFalse(link_hub.odidi(self.b.hub_url(), zeton, self.b.hub_fp()))

if __name__ == "__main__":
    unittest.main()
