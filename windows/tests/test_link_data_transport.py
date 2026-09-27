"""Preizkusi za core.link_data_transport (Safeer Data Transport v0.26, 1. korak).

Vsak preizkus dela z DVEMA zacasnima EC P-256 identitetama (openssl, v tempdir) - ne z
nastavitvami prave naprave - da preizkusi ne pustijo sledi in ne rabijo pravega kroga zaupanja.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import link_data_transport as dt  # noqa: E402
from core import link_krog  # noqa: E402


def _nov_kljuc(mapa: str, ime: str) -> str:
    """Zacasna EC P-256 identiteta; prek core.link_kripto, da preizkus tece tudi na Windows brez openssl."""
    from core import link_kripto
    pot = os.path.join(mapa, ime + ".pem")
    link_kripto.ustvari_kljuc_in_potrdilo(pot, os.path.join(mapa, ime + "-potrdilo.pem"), ime)
    return pot


class OsnovaDveIdentiteti(unittest.TestCase):
    def setUp(self):
        self.mapa = tempfile.mkdtemp(prefix="safeer-dt-test-")
        self.kljuc_a = _nov_kljuc(self.mapa, "a.pem")
        self.kljuc_b = _nov_kljuc(self.mapa, "b.pem")
        self.pub_a = dt.javni_kljuc_iz_datoteke(self.kljuc_a)
        self.pub_b = dt.javni_kljuc_iz_datoteke(self.kljuc_b)
        self.id_a = "n-aaaaaaaaaaaaaaaa"
        self.id_b = "n-bbbbbbbbbbbbbbbb"

    def tearDown(self):
        shutil.rmtree(self.mapa, ignore_errors=True)


class TestEcdh(OsnovaDveIdentiteti):
    def test_ecdh_je_simetricen(self):
        s_a = dt.ecdh_skupna_skrivnost(self.pub_b, self.kljuc_a)
        s_b = dt.ecdh_skupna_skrivnost(self.pub_a, self.kljuc_b)
        self.assertEqual(s_a, s_b)
        self.assertEqual(len(s_a), 32)

    def test_ecdh_neveljaven_kljuc(self):
        with self.assertRaises(dt.NapakaPrenosa):
            dt.ecdh_skupna_skrivnost("ni-base64!!", self.kljuc_a)


class TestHkdf(unittest.TestCase):
    def test_deterministicen_in_pravilne_dolzine(self):
        k1 = dt.izpelji_sejni_kljuc(b"\x01" * 32, "seja1", "bm9uY2Uy", "bm9uY2Uz")
        k2 = dt.izpelji_sejni_kljuc(b"\x01" * 32, "seja1", "bm9uY2Uy", "bm9uY2Uz")
        self.assertEqual(k1.kljuc, k2.kljuc)
        self.assertEqual(k1.predpona_nonca, k2.predpona_nonca)
        self.assertEqual(len(k1.kljuc), 32)
        self.assertEqual(len(k1.predpona_nonca), 4)

    def test_drug_session_id_drug_kljuc(self):
        k1 = dt.izpelji_sejni_kljuc(b"\x01" * 32, "seja1", "bm9uY2Uy", "bm9uY2Uz")
        k2 = dt.izpelji_sejni_kljuc(b"\x01" * 32, "seja2", "bm9uY2Uy", "bm9uY2Uz")
        self.assertNotEqual(k1.kljuc, k2.kljuc)

    def test_nonce_je_predpona_plus_stevec(self):
        k = dt.izpelji_sejni_kljuc(b"\x01" * 32, "seja1", "bm9uY2Uy", "bm9uY2Uz")
        n0 = k.nonce(0)
        n1 = k.nonce(1)
        self.assertEqual(len(n0), 12)
        self.assertNotEqual(n0, n1)
        self.assertTrue(n0.startswith(k.predpona_nonca))


class TestPonudbaOdgovor(OsnovaDveIdentiteti):
    def test_polni_dogovor_da_isti_kljuc_na_obeh_straneh(self):
        ponudba = dt.sestavi_ponudbo(self.id_a, self.id_b, dt.NAMEN_DATOTEKA, pot_kljuca=self.kljuc_a)
        self.assertEqual(ponudba["type"], "data.offer")
        self.assertEqual(ponudba["target"], self.id_b)

        izid = dt.sprejmi_ponudbo(ponudba, self.id_b, self.pub_a, pot_kljuca=self.kljuc_b)
        self.assertEqual(izid.tuj_id, self.id_a)
        self.assertEqual(izid.namen, dt.NAMEN_DATOTEKA)
        self.assertEqual(izid.odgovor["type"], "data.answer")
        self.assertEqual(izid.odgovor["target"], self.id_a)

        kljuc_a_stran = dt.dokoncaj_ponudbo(ponudba, izid.odgovor, self.pub_b, pot_kljuca=self.kljuc_a)
        self.assertEqual(kljuc_a_stran.kljuc, izid.sejni.kljuc)
        self.assertEqual(kljuc_a_stran.predpona_nonca, izid.sejni.predpona_nonca)

    def test_ponarejena_ponudba_pade(self):
        ponudba = dt.sestavi_ponudbo(self.id_a, self.id_b, dt.NAMEN_DATOTEKA, pot_kljuca=self.kljuc_a)
        ponudba["payload"]["session_id"] = "podtaknjen-id"  # spremeni po podpisu
        with self.assertRaises(dt.NapakaPrenosa):
            dt.sprejmi_ponudbo(ponudba, self.id_b, self.pub_a, pot_kljuca=self.kljuc_b)

    def test_ponudba_za_drugo_napravo_pade(self):
        ponudba = dt.sestavi_ponudbo(self.id_a, "n-nekdo-drug", dt.NAMEN_DATOTEKA, pot_kljuca=self.kljuc_a)
        with self.assertRaises(dt.NapakaPrenosa):
            dt.sprejmi_ponudbo(ponudba, self.id_b, self.pub_a, pot_kljuca=self.kljuc_b)

    def test_napacen_kljuc_ponudnika_pade(self):
        ponudba = dt.sestavi_ponudbo(self.id_a, self.id_b, dt.NAMEN_DATOTEKA, pot_kljuca=self.kljuc_a)
        with self.assertRaises(dt.NapakaPrenosa):
            dt.sprejmi_ponudbo(ponudba, self.id_b, self.pub_b, pot_kljuca=self.kljuc_b)  # napacen tuj kljuc

    def test_potekla_ponudba_pade(self):
        ponudba = dt.sestavi_ponudbo(self.id_a, self.id_b, dt.NAMEN_DATOTEKA, pot_kljuca=self.kljuc_a)
        ponudba["payload"]["ts"] = time.time() - dt.VELJAVNOST_PONUDBE_S - 5
        # ts je del podpisanih podatkov - spremenjen ts torej najprej podre podpis, kar je pravilno
        # (napadalec ne more "podaljsati" ponudbe brez zasebnega kljuca ponudnika).
        with self.assertRaises(dt.NapakaPrenosa):
            dt.sprejmi_ponudbo(ponudba, self.id_b, self.pub_a, pot_kljuca=self.kljuc_b)

    def test_odgovor_za_drugo_ponudbo_pade(self):
        ponudba1 = dt.sestavi_ponudbo(self.id_a, self.id_b, dt.NAMEN_DATOTEKA, pot_kljuca=self.kljuc_a)
        ponudba2 = dt.sestavi_ponudbo(self.id_a, self.id_b, dt.NAMEN_DATOTEKA, pot_kljuca=self.kljuc_a)
        izid1 = dt.sprejmi_ponudbo(ponudba1, self.id_b, self.pub_a, pot_kljuca=self.kljuc_b)
        with self.assertRaises(dt.NapakaPrenosa):
            dt.dokoncaj_ponudbo(ponudba2, izid1.odgovor, self.pub_b, pot_kljuca=self.kljuc_a)

    def test_neznan_namen_pade(self):
        with self.assertRaises(dt.NapakaPrenosa):
            dt.sestavi_ponudbo(self.id_a, self.id_b, "video-klic", pot_kljuca=self.kljuc_a)

    def test_posiljatelj_iz_huba_se_mora_ujemati(self):
        ponudba = dt.sestavi_ponudbo(self.id_a, self.id_b, dt.NAMEN_DATOTEKA, pot_kljuca=self.kljuc_a)
        with self.assertRaises(dt.NapakaPrenosa):
            dt.sprejmi_ponudbo(ponudba, self.id_b, self.pub_a, pot_kljuca=self.kljuc_b,
                               posiljatelj_iz_huba="n-nekdo-tretji")


class TestKosi(unittest.TestCase):
    def setUp(self):
        self.sejni = dt.izpelji_sejni_kljuc(os.urandom(32), "seja-x", "bm9uY2Uy", "bm9uY2Uz")

    def test_sifriraj_desifriraj_kroznica(self):
        cistopis = os.urandom(3 * 1024 * 1024 + 137)  # ni tocen veckratnik DOLZINA_KOSA
        sifrirano = dt.sifriraj_bajte(self.sejni, "seja-x", cistopis, dolzina_kosa=1024 * 1024)
        self.assertEqual(len(sifrirano), 4)
        nazaj = dt.desifriraj_bajte(self.sejni, "seja-x", sifrirano)
        self.assertEqual(nazaj, cistopis)
        self.assertEqual(dt.sha256_hex(nazaj), dt.sha256_hex(cistopis))

    def test_prazen_prenos(self):
        sifrirano = dt.sifriraj_bajte(self.sejni, "seja-x", b"")
        self.assertEqual(len(sifrirano), 1)
        self.assertEqual(dt.desifriraj_bajte(self.sejni, "seja-x", sifrirano), b"")

    def test_spremenjen_bajt_pade(self):
        sifrirano = dt.sifriraj_bajte(self.sejni, "seja-x", b"varni podatki")
        pokvarjeno = bytearray(sifrirano[0])
        pokvarjeno[-1] ^= 0xFF  # zadnji bajt je del GCM taga
        with self.assertRaises(dt.NapakaPrenosa):
            dt.desifriraj_bajte(self.sejni, "seja-x", [bytes(pokvarjeno)])

    def test_kos_iz_druge_seje_pade(self):
        sifrirano = dt.sifriraj_bajte(self.sejni, "seja-x", b"nekaj podatkov")
        with self.assertRaises(dt.NapakaPrenosa):
            dt.desifriraj_bajte(self.sejni, "druga-seja", sifrirano)  # AAD se ne ujema

    def test_premesani_kosi_padejo(self):
        sifrirano = dt.sifriraj_bajte(self.sejni, "seja-x", os.urandom(1024 * 1024 * 2),
                                       dolzina_kosa=1024 * 1024)
        zamenjano = [sifrirano[1], sifrirano[0]]
        with self.assertRaises(dt.NapakaPrenosa):
            dt.desifriraj_bajte(self.sejni, "seja-x", zamenjano)  # AAD nosi indeks kosa

    def test_drug_kljuc_ne_desifrira(self):
        drug_sejni = dt.izpelji_sejni_kljuc(os.urandom(32), "seja-x", "bm9uY2Uy", "bm9uY2Uz")
        sifrirano = dt.sifriraj_bajte(self.sejni, "seja-x", b"tajno")
        with self.assertRaises(dt.NapakaPrenosa):
            dt.desifriraj_bajte(drug_sejni, "seja-x", sifrirano)


class TestPolnKrogSVGCM(OsnovaDveIdentiteti):
    """Od data.offer do desifriranega prenosa - polna pot obeh strani skupaj."""

    def test_od_ponudbe_do_prenosa(self):
        ponudba = dt.sestavi_ponudbo(self.id_a, self.id_b, dt.NAMEN_DATOTEKA, pot_kljuca=self.kljuc_a)
        izid_b = dt.sprejmi_ponudbo(ponudba, self.id_b, self.pub_a, pot_kljuca=self.kljuc_b)
        sejni_a = dt.dokoncaj_ponudbo(ponudba, izid_b.odgovor, self.pub_b, pot_kljuca=self.kljuc_a)

        datoteka = os.urandom(2 * 1024 * 1024 + 42)
        sifrirano = dt.sifriraj_bajte(sejni_a, izid_b.session_id, datoteka)
        prejeto = dt.desifriraj_bajte(izid_b.sejni, izid_b.session_id, sifrirano)
        self.assertEqual(prejeto, datoteka)
        self.assertEqual(dt.sha256_hex(prejeto), dt.sha256_hex(datoteka))


if __name__ == "__main__":
    unittest.main(verbosity=2)
