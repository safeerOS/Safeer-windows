"""Scit za Windows proti skupnim primerom (tests/skupni-primeri/scit-pravila.json - bajt za bajt ISTA datoteka kot v
Safeer-linux in Android-tv; tam jo preverjata tests/test_scit_skupni_primeri.py in tests/ScitSkupniPrimeriTest.kt).
Lastnik 4. 11. 2026: »ni optimalno delati vec Scitov za razlicne OS«. Preizkus je prepis linuxovega (isti klici, ista
pot razresevalnika Razresevalnik._odgovori brez omrezja); razlika je samo PLATFORMA in pot do primerov.

Primer z »neujemanje« in »windows« v »razlicno_na« bi bil znana razlika: preskocen z izpisom; ce Windows postane enak,
preizkus pade, da se oznaka umakne. Do 4. 11. 2026 se je Windows razlikoval v 5 od 29 primerov (svoja stara koda)."""
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core import os_scit  # noqa: E402

KOREN = Path(__file__).resolve().parents[2]
PRIMERI = KOREN / "tests" / "skupni-primeri" / "scit-pravila.json"
PLATFORMA = "windows"
#: SHA-256 skupnih primerov v2 (Safeer-linux 746f975). Ko je Safeer-linux s to datoteko na refu iz skupna-koda.json,
#: gre datoteka v »skupne« (CI jo tedaj primerja z Linuxom sam) in ta vsota ni vec potrebna.
SHA_PRIMEROV = "18be3d259f65a5b3da62b282b91e7ec2a2ad64f3ba5500f0e56f4e3444118f44"


def poizvedba(ime: str) -> bytes:
    """Poizvedba DNS, kot jo poslje aplikacija: oznake med pikami (prazne izpuscene), bajti UTF-8."""
    telo = b"".join(struct.pack("B", len(o)) + o for o in (d.encode("utf-8") for d in ime.split(".") if d)) + b"\x00"
    return struct.pack("!HHHHHH", 0x1234, 0x0100, 1, 0, 0, 0) + telo + struct.pack("!HH", 1, 1)


class Shramba(dict):
    def get(self, k, d=None):
        return dict.get(self, k, d)

    def set(self, k, v):
        self[k] = v


class ScitSkupniPrimeri(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = json.loads(PRIMERI.read_text(encoding="utf-8"))

    def setUp(self):
        self._mapa = tempfile.TemporaryDirectory()
        self.addCleanup(self._mapa.cleanup)

    def _scit(self):
        """Pravi Scit in Seznami (NIKOLI, posodobitve, preverjanje, Webtor, groznje) z naborom iz skupnih seznamov."""
        sc = os_scit.Scit(Shramba(), mapa=self._mapa.name)
        s = os_scit.Seznami(self._mapa.name)
        sez = self.d["seznami"]
        s.nabor = os_scit.Nabor.iz_domen(
            [(d, "oglasi") for d in os_scit.razcleni_seznam("\n".join(sez["oglasi"]))]
            + [(d, "groznje") for d in os_scit.razcleni_seznam("\n".join(sez["groznje"]))])
        sc.seznami = s
        sc.razresevalnik = os_scit.Razresevalnik(sc._kategorija, lambda: [])
        return sc

    @staticmethod
    def _izid(sc, ime: str) -> str:
        odgovor = sc.razresevalnik._odgovori(poizvedba(ime), False)
        rcode = odgovor[3] & 0x0F if odgovor else None
        if rcode in (None, 2):
            return "spuscen"                      # poslano naprej (streznikov naprej v preizkusu ni: SERVFAIL)
        return "ustavljeno" if rcode == 3 else "rcode %d" % rcode

    def _preveri(self, p: dict, dobljeno, pricakovano, opis: str):
        if p.get("neujemanje") and PLATFORMA in p.get("razlicno_na", ["android", "linux", "windows"]):
            print("  PRESKOCENO (neujemanje) %s: %s; Windows da %s" % (opis, p["neujemanje"], dobljeno))
            self.assertNotEqual(dobljeno, pricakovano, "neujemanje odpravljeno - umakni oznako: " + opis)
            return
        self.assertEqual(dobljeno, pricakovano, opis)

    def test_primeri_so_isti_kot_na_linuxu(self):
        import hashlib
        # CRLF -> LF: git na Windows (core.autocrlf) datoteko ob prevzemu lahko pretvori; vsebina je ista.
        self.assertEqual(hashlib.sha256(PRIMERI.read_bytes().replace(b"\r\n", b"\n")).hexdigest(), SHA_PRIMEROV,
                         "skupni primeri se razlikujejo od Safeer-linux: spremeni jih tam in prenesi bajt za bajt")

    def test_verzija_in_seznami_pravila(self):
        """Krajevna imena, kanarcek, zasciteni gostitelji in trajanje izjeme so v kodi ISTI kot v skupnih primerih."""
        self.assertEqual(self.d["verzija"], 2)
        self.assertEqual(list(os_scit.KRAJEVNA), self.d["krajevna"])
        self.assertEqual(list(os_scit.KRAJEVNE_KONCNICE), self.d["krajevne_koncnice"])
        self.assertEqual(os_scit.KANAREK_DOH, self.d["kanarek_doh"])
        self.assertEqual(list(os_scit.ZASCITENI), self.d["zasciteni"])
        self.assertEqual(os_scit.IZJEMA_S, self.d["izjema_dni"] * 24 * 3600)

    def test_ustavljeno(self):
        sc = self._scit()
        for p in self.d["ustavljeno"]:
            with self.subTest(p["opis"]):
                self._preveri(p, self._izid(sc, p["ime"]), p["izid"], p["opis"])

    def test_izjeme(self):
        for p in self.d["izjeme"]:
            with self.subTest(p["opis"]):
                sc = self._scit()
                ura = [1_800_000_000.0]
                sc._ura = lambda: ura[0]
                # Dovoliti je mogoce samo nazadnje ustavljeno ime: najprej ga vprasa aplikacija, potem uporabnik spusti.
                self._izid(sc, p["izjema"])
                cista = os_scit.cista_domena(p["izjema"])
                sprejeta = bool(cista) and cista in sc.dovoli(p["izjema"])["izjeme"]
                ura[0] += p["dan"] * 24 * 3600
                self._preveri(p, (sprejeta, self._izid(sc, p["poizvedba"])), (p["sprejeta"], p["izid"]), p["opis"])

    def test_razresevalci_naprej(self):
        for p in self.d["razresevalci_naprej"]:
            with self.subTest(p["opis"]):
                sc = os_scit.Scit(Shramba(), mapa=self._mapa.name)      # uporabnik se ni izbral
                izbira, _ = sc.naprej()
                if izbira != "router":
                    izid = "tuj"                  # DoH k zunanjemu ponudniku
                elif p["krajevni"]:
                    izid = "krajevni"             # samo strezniki omrezja (v preizkusu jih ne vprasamo)
                else:
                    r = os_scit.Razresevalnik(lambda _i: None, lambda: [], sc._naprej)
                    r.sifrirano_naprej = lambda: sc.naprej()[0] != "router"
                    o = r._odgovori(poizvedba("a.example"), False)
                    izid = "brez_odgovora" if o is None else ("servfail" if (o[3] & 0x0F) == 2 else "rcode %d" % (o[3] & 0x0F))
                self._preveri(p, izid, p["izid"], p["opis"])


if __name__ == "__main__":
    unittest.main()
