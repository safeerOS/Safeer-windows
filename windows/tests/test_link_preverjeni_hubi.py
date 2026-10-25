"""Preverjeni oglasi Hubov in redni pregled gostovanja (Linux 86f91f9/fcffeaf, prenos na Windows 25. 10. 2026).

Oglas mDNS (id, prioriteta) je nepreverjen; steje samo clan kroga, cigar potrdilo TLS nosi njegov kljuc iz kroga.
V Meshu redni pregled ne isce tujega Huba (vec sekund mDNS in preverb). Windows samodejne rezerve nima (Control vedno
gosti svoj Hub v Meshu) - preverjamo razred in nadzor HubGostitelj.
"""
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

KOREN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KOREN))

from core import link_hub_streznik as L  # noqa: E402


class Preverjeni(unittest.TestCase):
    def _p(self, potrdila, ura=None):
        klici = []

        def potrdilo(naslov):
            klici.append(naslov)
            v = potrdila[naslov]
            if isinstance(v, Exception):
                raise v
            return v
        kljuci = {"clan": "KLJUC-A", "drug": "KLJUC-B"}
        return L.PreverjeniHubi(lambda hid: kljuci.get(hid, ""), potrdilo=potrdilo, ura=ura or (lambda: 0.0)), klici

    def test_samo_clan_s_pravim_kljucem(self):
        p, _ = self._p({"wss://a:1/cast/ws": ("fp", "KLJUC-A"), "wss://b:1/cast/ws": ("fp", "TUJ")})
        oglasi = [{"id": "clan", "naslov": "wss://a:1/cast/ws", "fp": "x"},
                  {"id": "drug", "naslov": "wss://b:1/cast/ws", "fp": "y"},       # oglasi id clana, potrdilo ni njegovo
                  {"id": "tujec", "naslov": "wss://c:1/cast/ws"},                    # ni v krogu
                  {"id": "clan", "naslov": "http://a:1/"}]                          # ni wss
        with mock.patch.object(L.link_tls, "isti", side_effect=lambda a, b: a == b):
            self.assertEqual([h["naslov"] for h in p.filtriraj(oglasi)], ["wss://a:1/cast/ws"])

    def test_preverba_se_hrani_nedosegljiv_ne(self):
        cas = [0.0]
        p, klici = self._p({"wss://a:1/cast/ws": ("fp", "KLJUC-A"), "wss://n:1/cast/ws": OSError("ni")},
                           ura=lambda: cas[0])
        oglasi = [{"id": "clan", "naslov": "wss://a:1/cast/ws"}, {"id": "clan", "naslov": "wss://n:1/cast/ws"}]
        with mock.patch.object(L.link_tls, "isti", side_effect=lambda a, b: a == b):
            p.filtriraj(oglasi)
            p.filtriraj(oglasi)
            self.assertEqual(klici.count("wss://a:1/cast/ws"), 1)               # v roku iz spomina
            self.assertEqual(klici.count("wss://n:1/cast/ws"), 2)               # nedosegljiv: znova ob pregledu
            cas[0] = L.PREVERJEN_OGLAS_VELJA_S + 1
            p.filtriraj(oglasi)
            self.assertEqual(klici.count("wss://a:1/cast/ws"), 2)


class Nadzor(unittest.TestCase):
    def test_v_meshu_brez_iskanja_tujega_huba(self):
        poisci = mock.Mock(return_value=None)
        s = mock.Mock(); s.tece.return_value = True
        g = L.HubGostitelj(poisci=poisci, streznik=s, oglas=mock.Mock(), hubi=lambda: [])
        with mock.patch.dict(os.environ, {"SAFEER_LINK_MESH": "1"}):
            self.assertTrue(g.preveri())
        poisci.assert_not_called()
        with mock.patch.dict(os.environ, {"SAFEER_LINK_MESH": "0"}):
            g.preveri()
        poisci.assert_called_once()

    def test_reden_pregled_in_konec(self):
        s = mock.Mock(); stanje = [True]
        s.tece.side_effect = lambda: stanje[0]
        g = L.HubGostitelj(poisci=lambda: None, streznik=s, oglas=mock.Mock())
        pregledov, spremembe, dovolj = [], [], threading.Event()

        def preveri():
            pregledov.append(1)
            if len(pregledov) == 2:
                stanje[0] = False
            if len(pregledov) >= 3:
                dovolj.set()
            return stanje[0]
        g.preveri = preveri
        g.zacni_nadzor(ob_spremembi=lambda prej, zdaj: spremembe.append((prej, zdaj)), razmik_s=0.02)
        self.assertTrue(dovolj.wait(5))
        g.koncaj()
        self.assertIsNone(g._nadzor)
        self.assertEqual([z[1] for _p, z in spremembe][:1], [False])


if __name__ == "__main__":
    unittest.main()
