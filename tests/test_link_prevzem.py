"""Prejeta datoteka: pri katerem sredisci jo prevzamemo (link_deljenje.prevzemi_pri_srediscih).

Pot v `share.file` (/cast/file/<id>?k=<kljuc>) je relativna na sredisce, ki je datoteko sprejelo. To je lahko
  - NASE sredisce: racunalnik (Linux, Windows) datoteko odda sredisci ciljne naprave, torej nam;
  - sredisce POSILJATELJA: naprava jo odda svojemu sredisci, sporocilo pa pride do nas cez sosede.
Iz sporocila se tega ne vidi. Do 2.1.53 (Linux) je prejemnik vprasal samo sredisce posiljatelja, kadar je bil ta
prijavljen pri sosedu - racunalnik z lastnim srediscem je pri nas vedno tak (njegov id je id njegovega sredisca),
zato datoteke, ki jo je oddal nam, nismo nasli. Windows je vprasal samo svoje sredisce.

Preizkus tece na dveh pravih srediscih (TLS, HTTP) na tem racunalniku, z loceno identiteto in zalogo v zacasni mapi.
"""
import hashlib
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from core import link_deljenje, link_hub, link_hub_deljenje, link_hub_streznik, link_krog

POSILJATELJ = "n-aaaaaaaaaaaaaaaa-control"
CILJ = "n-bbbbbbbbbbbbbbbb"


class _Sredisce:
    """Pravo sredisce na zanki: svoja identiteta TLS, zaloga datotek v zacasni mapi, cilj prijavljen z zetonom."""

    def __init__(self, mapa: str, ime: str) -> None:
        self.streznik = link_hub_streznik.HubStreznik(tls_mapa=os.path.join(mapa, ime, "tls"))
        if not self.streznik.zazeni():
            raise unittest.SkipTest("sredisca ni bilo mogoce zagnati")
        self.hub = self.streznik.hub
        self.zaloga = os.path.join(mapa, ime, "zaloga")
        self.hub.deljenje = link_hub_deljenje.Deljenje(mapa=lambda: self.zaloga)
        self.naslov = "wss://127.0.0.1:%d%s" % (self.streznik.vrata, link_hub_streznik.POT_WS)
        self.odtis = self.streznik.odtis
        self.par = (self.naslov, self.odtis)
        self.sporocila = []
        self.prislo = threading.Event()
        self.zeton_posiljatelja = self.hub.zeton_lastne_naprave(POSILJATELJ, "Drugi računalnik")
        self.cilj = link_hub.Povezava(self.naslov, self.hub.zeton_lastne_naprave(CILJ, "Ta računalnik"), CILJ,
                                      "Ta računalnik", odtis=self.odtis, v_krog=False)
        self.cilj.ob_sporocilu = self._sporocilo
        if not self.cilj.poveži():
            self.streznik.ustavi()
            raise unittest.SkipTest("cilj se ni mogel prijaviti na sredisce")
        konec = time.monotonic() + 5
        while time.monotonic() < konec and (self.hub.najdi(CILJ) is None or self.hub.najdi(CILJ).povezava is None):
            time.sleep(0.02)

    def _sporocilo(self, s: dict) -> None:
        if s.get("type") == "share.file":
            self.sporocila.append(s)
            self.prislo.set()

    def oddaj(self, pot: str) -> dict:
        """Posiljatelj odda datoteko TEMU sredisci; vrne tovor sporocila share.file, ki ga dobi cilj."""
        self.prislo.clear()
        ok, napaka = link_deljenje.poslji_datoteko(self.naslov, self.zeton_posiljatelja, self.odtis, POSILJATELJ,
                                                   CILJ, pot)
        if not ok:
            raise AssertionError(napaka)
        if not self.prislo.wait(5):
            raise AssertionError("cilj ni izvedel za datoteko")
        return self.sporocila[-1]

    def ustavi(self) -> None:
        try:
            self.cilj.zapri()
        except Exception:
            pass
        self.streznik.ustavi()


class PrevzemPriSrediscih(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.popravki = [
            mock.patch.object(link_krog, "_mapa_nastavitev", return_value=os.path.join(cls.tmp.name, "nastavitve")),
            mock.patch.object(link_hub_streznik.HubStreznik, "_ze_gosti_lokalno", staticmethod(lambda: False)),
            mock.patch.dict(os.environ, {"SAFEER_HUB_DRUGI": "1"}),
            mock.patch.object(link_hub_streznik, "_obvestilo", lambda *a, **k: None),
            mock.patch.object(link_hub_streznik, "_obvestilo_kode", lambda *a, **k: None),
        ]
        os.makedirs(os.path.join(cls.tmp.name, "nastavitve"))
        for p in cls.popravki:
            p.start()
        cls.sredisca = []
        try:
            cls.nase = cls._novo("nase")
            cls.posiljateljevo = cls._novo("posiljateljevo")
        except BaseException:
            cls._pospravi()
            raise
        cls.vsebina = os.urandom(200_000) + "čšž\r\n\n".encode("utf-8")
        cls.odtis_vsebine = hashlib.sha256(cls.vsebina).hexdigest()
        cls.pot = os.path.join(cls.tmp.name, "Račun 2026.bin")
        with open(cls.pot, "wb") as f:
            f.write(cls.vsebina)

    @classmethod
    def _novo(cls, ime: str) -> _Sredisce:
        s = _Sredisce(cls.tmp.name, ime)
        cls.sredisca.append(s)
        return s

    @classmethod
    def _pospravi(cls) -> None:
        for s in cls.sredisca:
            s.ustavi()
        for p in reversed(cls.popravki):
            p.stop()
        cls.tmp.cleanup()

    @classmethod
    def tearDownClass(cls):
        cls._pospravi()

    def setUp(self):
        self.mapa = tempfile.mkdtemp(dir=self.tmp.name, prefix="prejeto-")

    def _prevzemi(self, sredisca, tovor, odtis=None):
        return link_deljenje.prevzemi_pri_srediscih(sredisca, tovor["path"], tovor["name"],
                                                    tovor["sha256"] if odtis is None else odtis, mapa=self.mapa)

    def _je_cela(self, cilj):
        self.assertTrue(cilj)
        self.assertEqual(os.path.basename(cilj), "Račun 2026.bin")
        with open(cilj, "rb") as f:
            self.assertEqual(f.read(), self.vsebina)

    def test_sredisci_sta_razlicni(self):
        self.assertNotEqual(self.nase.par, self.posiljateljevo.par)
        self.assertNotEqual(self.nase.odtis, self.posiljateljevo.odtis)

    def test_datoteka_oddana_nasemu_sredisci_se_prevzame_pri_nas(self):
        """Racunalnik z lastnim srediscem odda datoteko NAM; posiljatelj je pri nas viden kot naprava pri sosedu."""
        sporocilo = self.nase.oddaj(self.pot)
        self.assertEqual(sporocilo["sender"], POSILJATELJ)
        tovor = sporocilo["payload"]
        # Staro pravilo na Linuxu (samo sredisce posiljatelja): datoteke tam ni.
        staro, razlog = link_deljenje.prevzemi_datoteko(*self.posiljateljevo.par, tovor["path"], tovor["name"],
                                                        tovor["sha256"], mapa=self.mapa)
        self.assertIsNone(staro)
        self.assertEqual(razlog, "Hub je odgovoril 404")
        self.assertEqual(os.listdir(self.mapa), [])
        cilj, razlog = self._prevzemi([self.nase.par, self.posiljateljevo.par], tovor)
        self.assertEqual(razlog, "")
        self._je_cela(cilj)
        self.assertEqual(os.listdir(self.nase.zaloga), [], "prevzeta datoteka na sredisci ne ostane")

    def test_datoteka_pri_sredisci_posiljatelja_se_prevzame_tam(self):
        """Naprava odda datoteko SVOJEMU sredisci, sporocilo pride cez sosede: nase sredisce je nima (404)."""
        tovor = self.posiljateljevo.oddaj(self.pot)["payload"]
        # Staro pravilo na Windows (samo nase sredisce): datoteke tu ni.
        staro, razlog = link_deljenje.prevzemi_datoteko(*self.nase.par, tovor["path"], tovor["name"], tovor["sha256"],
                                                        mapa=self.mapa)
        self.assertEqual((staro, razlog), (None, "Hub je odgovoril 404"))
        cilj, razlog = self._prevzemi([self.nase.par, self.posiljateljevo.par], tovor)
        self.assertEqual(razlog, "")
        self._je_cela(cilj)
        self.assertEqual(os.listdir(self.posiljateljevo.zaloga), [])

    def test_ni_je_nikjer(self):
        tovor = {"path": "/cast/file/0123456789abcdef?k=" + "0" * 32, "name": "ni.bin", "sha256": ""}
        self.assertEqual(self._prevzemi([self.nase.par, self.posiljateljevo.par], tovor), (None, "Hub je odgovoril 404"))
        self.assertEqual(os.listdir(self.mapa), [])

    def test_samo_nase_sredisce(self):
        tovor = self.nase.oddaj(self.pot)["payload"]
        cilj, razlog = self._prevzemi([self.nase.par], tovor)
        self._je_cela(cilj)

    def test_brez_sredisc_ali_brez_odtisa(self):
        tovor = self.nase.oddaj(self.pot)["payload"]
        self.assertEqual(self._prevzemi([], tovor)[0], None)
        self.assertEqual(self._prevzemi([("", ""), (self.nase.naslov, "")], tovor)[0], None)
        # Datoteka je se na sredisci: prazni vnosi je niso prevzeli.
        self._je_cela(self._prevzemi([("", ""), self.nase.par], tovor)[0])

    def test_druga_napaka_je_koncna(self):
        """Napacen odtis vsebine pri nasem sredisci: naslednjega ne sprasujemo (datoteka pri njem ostane)."""
        pri_nas = self.nase.oddaj(self.pot)["payload"]
        pri_njem = self.posiljateljevo.oddaj(self.pot)["payload"]
        cilj, razlog = self._prevzemi([self.nase.par, self.posiljateljevo.par], pri_nas, odtis="00" * 32)
        self.assertEqual((cilj, razlog), (None, "prstni odtis se ne ujema"))
        self.assertEqual(os.listdir(self.mapa), [], "pokvarjena datoteka ne ostane v mapi prenosov")
        self.assertEqual(len(os.listdir(self.posiljateljevo.zaloga)), 1)
        self._je_cela(self._prevzemi([self.posiljateljevo.par], pri_njem)[0])

    def test_nedosegljivo_prvo_sredisce_je_koncna_napaka(self):
        """Do odgovora ni prislo (tuje potrdilo): to ni »datoteke ni«, zato naslednjega ne sprasujemo."""
        tovor = self.posiljateljevo.oddaj(self.pot)["payload"]
        cilj, razlog = self._prevzemi([(self.nase.naslov, "ab" * 32), self.posiljateljevo.par], tovor)
        self.assertIsNone(cilj)
        self.assertNotEqual(razlog, "")
        self.assertEqual(len(os.listdir(self.posiljateljevo.zaloga)), 1)
        self._je_cela(self._prevzemi([self.posiljateljevo.par], tovor)[0])

    def test_prevzemi_datoteko_ostane_enak(self):
        tovor = self.nase.oddaj(self.pot)["payload"]
        cilj, razlog = link_deljenje.prevzemi_datoteko(*self.nase.par, tovor["path"], tovor["name"], tovor["sha256"],
                                                       mapa=self.mapa)
        self.assertEqual(razlog, "")
        self._je_cela(cilj)


class ZacasnaMapaSredisca(unittest.TestCase):
    def test_linux_predpomnilnik_uporabnika(self):
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": "/dom/.predpomnilnik"}):
            self.assertEqual(link_hub_deljenje.privzeta_mapa(windows=False).replace("\\", "/"),
                             "/dom/.predpomnilnik/safeer-link/deljenje")

    def test_windows_mapa_programa(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": "C:/Users/U/AppData/Local"}):
            self.assertEqual(link_hub_deljenje.privzeta_mapa(windows=True).replace("\\", "/"),
                             "C:/Users/U/AppData/Local/SafeerOS/deljenje")

    def test_privzeto_po_sistemu(self):
        self.assertEqual(link_hub_deljenje.privzeta_mapa(), link_hub_deljenje.privzeta_mapa(windows=os.name == "nt"))


if __name__ == "__main__":
    unittest.main()
