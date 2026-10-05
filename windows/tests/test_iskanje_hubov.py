"""Iskanje Safeer Hubov na Windows ne zadrzuje vmesnika in ne pozna hisnih naslovov.

Izmerjeno 5. 10. 2026 z isto kodo, racunalnik brez seznanitve: `stanje_povezave()` je trajal 17,2 s - VSAK klic, ker
je bilo iskanje daljse od veljavnosti seznama (10 s). Stanje bere `zacetek` (zacetni podatki domace strani: jezik,
ozadje, ime, programi), zato je nov uporabnik brez Safeer Linka ob vsakem zagonu toliko casa gledal prazno stran.
Del casa so vzeli v kodo zapisani naslovi razvijalcevega doma (pet naslovov, dve shemi, 0,8 s vsak).
"""
import os
import re
import tempfile
import threading
import time
import unittest
from unittest import mock

from safeer_windows import control_backend as CB


def _backend(td: str) -> "CB.SafeerControlBackend":
    b = CB.SafeerControlBackend(config_pot=os.path.join(td, "link.json"))
    b.nastavitve.clear()                # brez seznanitve: ni zetona, ni huba
    return b


class StanjeNeCaka(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.b = _backend(self._td.name)
        self.iskanj = 0
        self.sprosti = threading.Event()
        self.izid = [{"ime": "Dnevna soba", "naslov": "wss://192.0.2.7:8990/cast/ws", "tls": True, "fp": ""}]
        pravo = CB.SafeerControlBackend.hubi_v_omrezju

        def pocasno(backend, osvezi=False):
            # Pravo iskanje (mDNS, pregled omrezja) nadomesti cakanje; izid zapise prava koda prek ponaredkov.
            self.iskanj += 1
            self.sprosti.wait(5)
            with mock.patch.object(CB.link_hub, "poisci_hube_mdns", return_value=list(self.izid)), \
                    mock.patch.object(backend, "_preisci_subnet_8990", return_value=[]), \
                    mock.patch.object(CB.link_hub, "je_hub", return_value=False), \
                    mock.patch.object(CB, "_se_razresi", return_value=False):
                return pravo(backend, osvezi=True)

        self._zaplata = mock.patch.object(CB.SafeerControlBackend, "hubi_v_omrezju", pocasno)
        self._zaplata.start()
        self.dogodki = []
        self.b.dodaj_poslusalca(lambda vrsta, podatki: self.dogodki.append(vrsta))

    def tearDown(self):
        self.sprosti.set()
        self._pocakaj(lambda: not self.b._hubi_isce)
        self._zaplata.stop()
        self._td.cleanup()

    @staticmethod
    def _pocakaj(pogoj, najvec: float = 3.0) -> bool:
        konec = time.monotonic() + najvec
        while time.monotonic() < konec:
            if pogoj():
                return True
            time.sleep(0.01)
        return pogoj()

    def test_stanje_se_vrne_takoj_in_pove_da_iskanje_tece(self):
        zacetek = time.monotonic()
        stanje = self.b.stanje_povezave()
        self.assertLess(time.monotonic() - zacetek, 0.5, "stanje ne sme cakati na iskanje hubov")
        self.assertEqual(stanje["stanje"], "nov")
        self.assertIsNone(stanje["hubi"], "None = prvo iskanje se tece (stran pokaze nevtralno besedilo)")
        self.assertEqual(self.dogodki, [])

    def test_po_iskanju_dogodek_in_seznam(self):
        self.b.stanje_povezave()
        self.sprosti.set()
        self.assertTrue(self._pocakaj(lambda: "povezava" in self.dogodki), "stran mora izvedeti, da je iskanje koncano")
        zacetek = time.monotonic()
        stanje = self.b.stanje_povezave()
        self.assertLess(time.monotonic() - zacetek, 0.5)
        self.assertEqual([h["ime"] for h in stanje["hubi"]], ["Dnevna soba"])
        self.assertEqual(self.iskanj, 1, "svez seznam ne sprozi novega iskanja")

    def test_brez_najdbe_je_seznam_prazen_ne_none(self):
        self.izid = []
        self.b.stanje_povezave()
        self.sprosti.set()
        self.assertTrue(self._pocakaj(lambda: "povezava" in self.dogodki))
        self.assertEqual(self.b.stanje_povezave()["hubi"], [], "[] = iskali smo in huba ni")
        self.assertEqual(self.iskanj, 1)

    def test_eno_iskanje_naenkrat(self):
        for _ in range(8):
            self.b.stanje_povezave()
        time.sleep(0.1)
        self.assertEqual(self.iskanj, 1)
        self.sprosti.set()
        self.assertTrue(self._pocakaj(lambda: not self.b._hubi_isce))
        self.assertEqual(self.iskanj, 1)

    def test_zastarel_seznam_se_osvezi_v_ozadju_stari_pa_ostane_na_voljo(self):
        self.sprosti.set()
        self.b.stanje_povezave()
        self.assertTrue(self._pocakaj(lambda: self.b._hubi_iskani and not self.b._hubi_isce))
        self.sprosti.clear()
        self.b._cas_hubi -= CB.HUBI_VELJAJO_S + 1
        zacetek = time.monotonic()
        stanje = self.b.stanje_povezave()
        self.assertLess(time.monotonic() - zacetek, 0.5)
        self.assertEqual([h["ime"] for h in stanje["hubi"]], ["Dnevna soba"], "med osvezevanjem velja stari seznam")
        self.assertTrue(self._pocakaj(lambda: self.iskanj == 2))
        self.sprosti.set()
        self.assertTrue(self._pocakaj(lambda: not self.b._hubi_isce))
        self.assertEqual(self.dogodki.count("povezava"), 1, "enak seznam ne poslje novega dogodka")

    def test_prazen_seznam_velja_dlje(self):
        self.izid = []
        self.sprosti.set()
        self.b.stanje_povezave()
        self.assertTrue(self._pocakaj(lambda: self.b._hubi_iskani and not self.b._hubi_isce))
        self.b._cas_hubi -= CB.HUBI_VELJAJO_S + 1          # 11 s star prazen seznam se velja
        self.b.stanje_povezave()
        time.sleep(0.1)
        self.assertEqual(self.iskanj, 1)
        self.b._cas_hubi -= CB.HUBI_PRAZNI_VELJAJO_S       # zdaj je zastarel
        self.b.stanje_povezave()
        self.assertTrue(self._pocakaj(lambda: self.iskanj == 2))

    def test_seznanjen_racunalnik_hubov_ne_isce(self):
        self.b.nastavitve.update({"control_token": "zeton", "hub_url": "wss://192.0.2.7:8990/cast/ws"})
        with mock.patch.object(self.b, "povezi_se"):
            stanje = self.b.stanje_povezave()
        self.assertEqual((stanje["stanje"], stanje["hubi"]), ("povezan", []))
        time.sleep(0.05)
        self.assertEqual(self.iskanj, 0)


class KandidatiIskanja(unittest.TestCase):
    def _isci(self, hub_url: str = "", pregled=(), razresi=lambda ime: False):
        vprasani = []

        def je_hub(osnova, timeout=0.8, odtis=None):
            vprasani.append(osnova)
            return False

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            b = _backend(td)
            if hub_url:
                b.nastavitve["hub_url"] = hub_url
            with mock.patch.object(CB.link_hub, "poisci_hube_mdns", return_value=[]), \
                    mock.patch.object(b, "_preisci_subnet_8990", return_value=list(pregled)), \
                    mock.patch.object(b, "_lokalni_ip", return_value="192.0.2.50"), \
                    mock.patch.object(CB.link_hub, "je_hub", je_hub), \
                    mock.patch.object(CB.socket, "getaddrinfo", lambda ime, *_a, **_k: [1] if razresi(ime) else (_ for _ in ()).throw(OSError())):
                najdeni = b.hubi_v_omrezju(osvezi=True)
        return vprasani, najdeni

    def test_vprasa_samo_ta_racunalnik_svoj_hub_in_najdene_v_omrezju(self):
        vprasani, najdeni = self._isci(hub_url="wss://192.0.2.9:8990/cast/ws", pregled=["192.0.2.31"])
        gostitelji = sorted({re.sub(r"^\w+://|:\d+.*$", "", o) for o in vprasani})
        self.assertEqual(gostitelji, ["127.0.0.1", "192.0.2.31", "192.0.2.9"])
        self.assertEqual(najdeni, [])

    def test_nov_uporabnik_brez_huba_vprasa_samo_ta_racunalnik(self):
        vprasani, _ = self._isci()
        self.assertEqual(sorted({re.sub(r"^\w+://|:\d+.*$", "", o) for o in vprasani}), ["127.0.0.1"])
        self.assertLessEqual(len(vprasani), 2, "dve shemi za en naslov")

    def test_privzeto_ime_huba_samo_ce_ga_omrezje_pozna(self):
        vprasani, _ = self._isci(razresi=lambda ime: ime == CB.link_hub.PRIVZETI_GOSTITELJ)
        gostitelji = {re.sub(r"^\w+://|:\d+.*$", "", o) for o in vprasani}
        self.assertIn(CB.link_hub.PRIVZETI_GOSTITELJ, gostitelji)

    def test_huba_ki_ga_je_nasel_mdns_ne_vprasa_znova(self):
        vprasani = []
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            b = _backend(td)
            mdns = [{"ime": "Dnevna soba", "naslov": "wss://192.0.2.31:8990/cast/ws", "tls": True, "fp": ""}]
            with mock.patch.object(CB.link_hub, "poisci_hube_mdns", return_value=mdns), \
                    mock.patch.object(b, "_preisci_subnet_8990", return_value=["192.0.2.31", "192.0.2.32"]), \
                    mock.patch.object(b, "_lokalni_ip", return_value="192.0.2.50"), \
                    mock.patch.object(CB.link_hub, "je_hub", lambda osnova, timeout=0.8, odtis=None: vprasani.append(osnova) or False), \
                    mock.patch.object(CB, "_se_razresi", lambda g: g != CB.link_hub.PRIVZETI_GOSTITELJ):
                najdeni = b.hubi_v_omrezju(osvezi=True)
        self.assertEqual([h["ime"] for h in najdeni], ["Dnevna soba"])
        self.assertFalse([o for o in vprasani if "192.0.2.31" in o], "najdeni hub smo vprasali se enkrat")
        self.assertTrue([o for o in vprasani if "192.0.2.32" in o])

    def test_kandidate_vprasa_hkrati(self):
        def pocasen(osnova, timeout=0.8, odtis=None):
            time.sleep(0.3)
            return False
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            b = _backend(td)
            with mock.patch.object(CB.link_hub, "poisci_hube_mdns", return_value=[]), \
                    mock.patch.object(b, "_preisci_subnet_8990", return_value=["192.0.2.%d" % i for i in range(31, 37)]), \
                    mock.patch.object(b, "_lokalni_ip", return_value="192.0.2.50"), \
                    mock.patch.object(CB.link_hub, "je_hub", pocasen), \
                    mock.patch.object(CB, "_se_razresi", lambda g: g != CB.link_hub.PRIVZETI_GOSTITELJ):
                zacetek = time.monotonic()
                b.hubi_v_omrezju(osvezi=True)
                trajalo = time.monotonic() - zacetek
        # 7 kandidatov x 2 shemi x 0,3 s = 4,2 s zaporedoma; hkrati 0,6 s.
        self.assertLess(trajalo, 2.0)

    def test_najdeni_hub_dobi_nevtralno_ime(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            b = _backend(td)
            with mock.patch.object(CB.link_hub, "poisci_hube_mdns", return_value=[]), \
                    mock.patch.object(b, "_preisci_subnet_8990", return_value=["192.168.0.135", "192.168.0.77"]), \
                    mock.patch.object(b, "_lokalni_ip", return_value="192.168.0.50"), \
                    mock.patch.object(CB.link_hub, "je_hub", lambda osnova, timeout=0.8, odtis=None: osnova.startswith("https")), \
                    mock.patch.object(CB, "_se_razresi", lambda g: g != CB.link_hub.PRIVZETI_GOSTITELJ):
                najdeni = b.hubi_v_omrezju(osvezi=True)
        imena = {h["naslov"]: h["ime"] for h in najdeni}
        self.assertEqual(imena.get("wss://192.168.0.135:8990/cast/ws"), "Safeer Hub (192.168.0.135)")
        self.assertEqual(imena.get("wss://192.168.0.77:8990/cast/ws"), "Safeer Hub (192.168.0.77)")
        # Vrstni red je vrstni red najdbe - noben naslov nima prednosti.
        naslovi = [h["naslov"] for h in najdeni]
        self.assertLess(naslovi.index("wss://192.168.0.135:8990/cast/ws"), naslovi.index("wss://192.168.0.77:8990/cast/ws"))


class BrezHisnihNaslovov(unittest.TestCase):
    def test_v_kodi_ni_zasebnih_naslovov_omrezja(self):
        """V izdelek ne sodi naslov nobenega domacega omrezja: tak naslov vsak uporabnik caka, najdeno napravo na
        njem pa bi imenovali po razvijalcevi."""
        koren = os.path.dirname(os.path.abspath(CB.__file__))
        vzorec = re.compile(r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b")
        dovoljeni = {"192.168.0.1", "192.168.1.1", "10.0.0.1"}        # splosni primeri usmerjevalnikov v pomoci
        najdeni = []
        for ime in sorted(os.listdir(koren)):
            if not ime.endswith(".py"):
                continue
            with open(os.path.join(koren, ime), encoding="utf-8") as f:
                for st, vrstica in enumerate(f, 1):
                    for naslov in vzorec.findall(vrstica):
                        if naslov not in dovoljeni:
                            najdeni.append("%s:%d %s" % (ime, st, naslov))
        self.assertEqual(najdeni, [])


if __name__ == "__main__":
    unittest.main()
