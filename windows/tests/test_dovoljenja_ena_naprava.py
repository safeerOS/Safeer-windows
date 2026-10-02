"""Lastnik, 2. 10. 2026: Windows je za isti telefon vprasal dvakrat (zaslon `n-…` in Safeer OS `n-…-os`),
ceprav je polni dostop ze dal. Pravica velja za FIZICNO napravo: obe identiteti delita isti profil."""
import os
import sys
import unittest

KOREN = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, KOREN)
sys.path.insert(0, os.path.join(KOREN, "windows"))

try:
    from safeer_windows import control_backend  # noqa: E402
except Exception as e:  # pragma: no cover - na sistemu brez Qt
    control_backend = None
    NAPAKA = e

TELEFON = "n-45047c17c6c9c134"
TELEFON_OS = TELEFON + "-os"
TV = "n-f1d0f648ea4e5602"


def _zaledje(dovoljenja=None, naprave=None):
    b = control_backend.SafeerControlBackend.__new__(control_backend.SafeerControlBackend)
    b.nastavitve = {"dovoljenja_naprav": dict(dovoljenja or {})}
    b.naprave = list(naprave or [])
    b._opozorjena_dovoljenja = set()
    b.shrani_nastavitve = lambda: True
    b.dogodki = []
    b._oddaj_dogodek = lambda vrsta, podatki=None: b.dogodki.append((vrsta, podatki))
    b.stanje_linka = lambda: {}
    b._preklici_zetone = lambda _id: None
    b.device_id = "n-c50805106b98fc1c-control"
    b._datoteke = {}
    return b


@unittest.skipIf(control_backend is None, "control_backend se ne uvozi")
class EnaNapravaTests(unittest.TestCase):
    def test_izbira_za_eno_identiteto_velja_za_drugo(self):
        # Stanje z lastnikovega racunalnika: polno za -os, vprasaj za zaslon istega telefona.
        b = _zaledje({TELEFON_OS: "polno", TELEFON: "vprasaj"},
                     [{"id": TELEFON, "naprava": TELEFON}, {"id": TELEFON_OS, "naprava": TELEFON}])
        self.assertEqual(b.dovoljenje_za(TELEFON), "polno")
        self.assertEqual(b.dovoljenje_za(TELEFON_OS), "polno")
        self.assertTrue(b._sme_na_streznik(TELEFON, True))

    def test_brez_polja_naprava_pomaga_pripona(self):
        b = _zaledje({TELEFON_OS: "izbrano"}, [{"id": TELEFON}, {"id": TELEFON_OS}])
        self.assertEqual(b.dovoljenje_za(TELEFON), "izbrano")
        # Drug telefon s svojim kljucem ne podeduje nicesar.
        self.assertEqual(b.dovoljenje_za("n-404fedf2ed258fd9"), "polno")   # stara namestitev, ni v seznamu
        b.naprave.append({"id": "n-404fedf2ed258fd9"})
        self.assertEqual(b.dovoljenje_za("n-404fedf2ed258fd9"), "vprasaj")

    def test_nastavitev_zapise_obema(self):
        b = _zaledje({TELEFON: "vprasaj", TELEFON_OS: "vprasaj"},
                     [{"id": TELEFON, "naprava": TELEFON}, {"id": TELEFON_OS, "naprava": TELEFON}, {"id": TV, "naprava": TV}])
        self.assertTrue(b.nastavi_dovoljenje(TELEFON_OS, "zaslon"))
        d = b.nastavitve["dovoljenja_naprav"]
        self.assertEqual(d[TELEFON], "zaslon")
        self.assertEqual(d[TELEFON_OS], "zaslon")
        self.assertEqual(d.get(TV), None)

    def test_nova_identiteta_znane_naprave_ne_vprasa(self):
        b = _zaledje({TELEFON_OS: "polno"})
        b._na_sporocilo({"type": "cast.devices", "devices": [
            {"id": TELEFON_OS, "name": "Safeer OS (SM-S931B)", "device": TELEFON},
            {"id": TELEFON, "name": "Safeer OS Mobile (SM-S931B)", "device": TELEFON},
            {"id": TV, "name": "Safeer TV", "device": TV},
        ]})
        d = b.nastavitve["dovoljenja_naprav"]
        self.assertEqual(d[TELEFON], "polno")            # podedovano, brez vprasanja
        self.assertEqual(d[TV], "vprasaj")               # nova fizicna naprava vprasa
        zahtevane = [p["id"] for v, p in b.dogodki if v == "dovoljenjeZahtevano"]
        self.assertEqual(zahtevane, [TV])


if __name__ == "__main__":
    unittest.main()
