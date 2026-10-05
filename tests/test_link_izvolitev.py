"""Izvoljeni hub na Linuxu: zaupanje po krogu, ne po seznanitvi.

 - javni kljuc iz potrdila (link_tls.javni_kljuc_potrdila) je isti kot kljuc naprave (link_krog),
 - oglas mDNS nosi id huba (poisci_hube_mdns ga vrne),
 - v zivo (ce se hub oglasa in je v krogu): potrdilo huba nosi kljuc njegovega clana v krogu,
   poisci_hub_z_odtisom ga brez seznanitve prepozna kot hub iz kroga (krog=True).
"""
import base64
import os
import ssl
import unittest

from core import link_datoteke, link_hub, link_krog, link_tls


class KljucIzPotrdila(unittest.TestCase):
    def test_kljuc_potrdila_je_kljuc_naprave(self):
        _kljuc, potrdilo, odtis = link_datoteke.zagotovi_potrdilo()
        with open(potrdilo, "rb") as d:
            der = ssl.PEM_cert_to_DER_cert(d.read().decode("ascii"))
        self.assertEqual(link_tls.odtis_potrdila(der), odtis)
        k = link_tls.javni_kljuc_potrdila(der)
        self.assertTrue(k)
        self.assertEqual(base64.b64decode(k)[:1], b"\x30")
        self.assertEqual(k, link_krog.javni_kljuc_b64(), "kljuc v potrdilu Controla je kljuc naprave v krogu")

    def test_pokvarjeno_potrdilo_da_prazno(self):
        self.assertEqual(link_tls.javni_kljuc_potrdila(b"nesmisel"), "")


class HubIzKrogaVZivo(unittest.TestCase):
    def test_hub_iz_kroga(self):
        hubi = [h for h in link_hub.poisci_hube_mdns(2.5) if h["tls"]]
        if not hubi:
            self.skipTest("noben hub se ne oglasa (ali ni zeroconf)")
        krog = link_krog.krog()
        v_krogu = [h for h in hubi if h.get("id") and krog.je_clan(h["id"])]
        print(f"\n  hubi: {[(h['id'], h['naslov']) for h in hubi]}; v krogu: {[h['id'] for h in v_krogu]}")
        if not v_krogu:
            self.skipTest("noben hub iz kroga se ne oglasa")
        h = v_krogu[0]
        videni, kljuc = link_tls.potrdilo_huba(h["naslov"])
        self.assertTrue(videni and kljuc)
        self.assertEqual(kljuc, krog.clan(h["id"])["kljuc"], "potrdilo huba nosi kljuc njegovega clana v krogu")
        # Brez znanega odtisa: hub prepoznamo po krogu.
        najden = link_hub.poisci_hub_z_odtisom("", None)
        self.assertIsNotNone(najden)
        print(f"  najden: {najden}")
        self.assertTrue(najden.get("krog") or najden.get("isti"), "hub iz kroga mora biti prepoznan brez seznanitve")


if __name__ == "__main__":
    unittest.main()
