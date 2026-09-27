"""Kriptografija Safeer Linka brez openssl (Windows) in navzkrizna zdruzljivost z openssl (Linux/Android)."""
import base64
import os
import shutil
import ssl
import subprocess
import tempfile
import unittest
from unittest import mock

from core import link_kripto

IMA_OPENSSL = shutil.which("openssl") is not None


def _brez_openssl(*args, **kwargs):
    raise FileNotFoundError("openssl ni namescen (kot na Windows)")


class TestLinkKripto(unittest.TestCase):
    def setUp(self):
        self.mapa = tempfile.mkdtemp()
        self.k1, self.p1 = os.path.join(self.mapa, "k1.pem"), os.path.join(self.mapa, "p1.pem")
        self.k2, self.p2 = os.path.join(self.mapa, "k2.pem"), os.path.join(self.mapa, "p2.pem")

    def tearDown(self):
        shutil.rmtree(self.mapa, ignore_errors=True)

    def test_brez_openssl_deluje_vse(self):
        with mock.patch("subprocess.run", side_effect=_brez_openssl):
            link_kripto.ustvari_kljuc_in_potrdilo(self.k1, self.p1, "test")
            link_kripto.ustvari_kljuc_in_potrdilo(self.k2, self.p2, "test2")
            j1, j2 = link_kripto.javni_kljuc_der(self.k1), link_kripto.javni_kljuc_der(self.k2)
            podpis = link_kripto.podpisi(self.k1, b"prijava")
            self.assertTrue(link_kripto.preveri(j1, b"prijava", podpis))
            self.assertFalse(link_kripto.preveri(j1, b"ponarejeno", podpis))
            self.assertFalse(link_kripto.preveri(j2, b"prijava", podpis))
            s12, s21 = link_kripto.ecdh(self.k1, j2), link_kripto.ecdh(self.k2, j1)
            self.assertEqual(s12, s21)
            self.assertEqual(len(s12), 32)
        # potrdilo je veljaven PEM X.509 (odtis ga bere ssl)
        with open(self.p1) as d:
            self.assertTrue(ssl.PEM_cert_to_DER_cert(d.read()))
        if os.name != "nt":
            self.assertEqual(os.stat(self.k1).st_mode & 0o077, 0)

    @unittest.skipUnless(IMA_OPENSSL, "openssl ni na voljo za navzkrizni preizkus")
    def test_navzkrizno_z_openssl(self):
        link_kripto.ustvari_kljuc_in_potrdilo(self.k1, self.p1, "crypto")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                        "-nodes", "-days", "1", "-subj", "/CN=o", "-keyout", self.k2, "-out", self.p2],
                       check=True, capture_output=True)
        # javni kljuc: enak kot ga izpise openssl
        spki_o = subprocess.run(["openssl", "pkey", "-in", self.k1, "-pubout", "-outform", "DER"],
                                check=True, capture_output=True).stdout
        self.assertEqual(link_kripto.javni_kljuc_der(self.k1), spki_o)
        # podpis cryptography -> preveri openssl
        podpis = link_kripto.podpisi(self.k1, b"krog")
        pot_j, pot_p = os.path.join(self.mapa, "j.der"), os.path.join(self.mapa, "s.bin")
        open(pot_j, "wb").write(spki_o); open(pot_p, "wb").write(podpis)
        r = subprocess.run(["openssl", "dgst", "-sha256", "-verify", pot_j, "-keyform", "DER", "-signature", pot_p],
                           input=b"krog", capture_output=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # podpis openssl (kljuc iz openssl) -> preveri cryptography
        podpis_o = subprocess.run(["openssl", "dgst", "-sha256", "-sign", self.k2], input=b"krog",
                                  check=True, capture_output=True).stdout
        spki2 = subprocess.run(["openssl", "pkey", "-in", self.k2, "-pubout", "-outform", "DER"],
                               check=True, capture_output=True).stdout
        self.assertTrue(link_kripto.preveri(spki2, b"krog", podpis_o))
        # ECDH: cryptography == openssl pkeyutl -derive
        pot_j2 = os.path.join(self.mapa, "j2.der"); open(pot_j2, "wb").write(spki2)
        s_o = subprocess.run(["openssl", "pkeyutl", "-derive", "-inkey", self.k1, "-peerkey", pot_j2, "-peerform", "DER"],
                             check=True, capture_output=True).stdout
        self.assertEqual(link_kripto.ecdh(self.k1, spki2), s_o)
        self.assertEqual(link_kripto.ecdh(self.k2, link_kripto.javni_kljuc_der(self.k1)), s_o)

    def test_krog_zaupanja_brez_openssl(self):
        """link_krog (podpis prijave, preverjanje) na Windows brez openssl."""
        from core import link_krog
        link_kripto.ustvari_kljuc_in_potrdilo(self.k1, self.p1, "krog")
        with mock.patch.object(link_krog, "_pot_kljuca", return_value=self.k1), \
             mock.patch.object(link_krog, "_javni", None), \
             mock.patch("subprocess.run", side_effect=_brez_openssl):
            kljuc = link_krog.javni_kljuc_b64()
            podpis = link_krog.podpisi(b"izziv")
            self.assertTrue(link_krog.preveri_podpis(kljuc, b"izziv", podpis))
            self.assertFalse(link_krog.preveri_podpis(kljuc, b"drugo", podpis))


if __name__ == "__main__":
    unittest.main()
