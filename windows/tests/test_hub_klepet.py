"""Hub na racunalniku: kdo sme noter, kam gre sporocilo in kaj dobi posiljatelj nazaj.

Tu je vsa logika, ki mora biti pravilna, zato je preizkusena brez vticnikov in TLS. Posebej
pazimo na sondo prijave, ki jo uporablja Safeer Control: prijavljena naprava mora dobiti
`isti_naprava`, osirotela vticnica pa `naprava_ni_povezana` - po tem odjemalec loci zivo povezavo
od mrtve in se po potrebi vrne.
"""
import json
import unittest
from unittest import mock

from core import link_hub_streznik, link_krog



class LaznaPovezava:
    def __init__(self, naslov="192.168.0.50"):
        self.naslov = naslov
        self.poslano = []
        self.podatki = {}
        self.zaprta_z = None

    def poslji(self, besedilo):
        self.poslano.append(json.loads(besedilo))
        return True

    def zapri(self, koda=1000, razlog=""):
        self.zaprta_z = (koda, razlog)

    def zadnje(self, tip):
        for s in reversed(self.poslano):
            if s.get("type") == tip:
                return s
        return None


def _prijava(id_naprave, ime="Naprava", vloga="receiver", zmoznosti=("url", "remote")):
    return json.dumps({"id": "r1", "type": "cast.register",
                       "payload": {"device_id": id_naprave, "name": ime, "role": vloga,
                                   "capabilities": list(zmoznosti), "platform": "tv",
                                   "protocol": "1", "kind": "tv", "version": "2.1.119"}})


class Klepet(unittest.TestCase):
    """Safeer Chat: hub posreduje, vpise posiljatelja in pocaka na nepovezano napravo."""

    def setUp(self):
        self.cas = 1_000_000.0
        self.hub = link_hub_streznik.Hub(odtis="ab" * 32, nas_id="n-racunalnik", ura=lambda: self.cas)
        self.tv, self.fon = LaznaPovezava(), LaznaPovezava("192.168.0.60")
        self.hub.obdelaj(self.tv, _prijava("tv1", "Televizor"))
        self.hub.obdelaj(self.fon, _prijava("fon1", "Telefon", "sender", ("url", "chat")))

    def _poslji(self, od, cilj, besedilo, sid="c1"):
        return json.loads(self.hub.obdelaj(od, json.dumps({"id": sid, "type": "chat.send", "target": cilj,
                                                            "payload": {"text": besedilo}})))

    def test_posredovano_z_imenom(self):
        self.assertEqual(self._poslji(self.fon, "tv1", "Živjo")["status"], "accepted")
        s = self.tv.zadnje("chat.send")
        self.assertEqual((s["sender"], s["sender_name"], s["payload"]["text"]), ("fon1", "Telefon", "Živjo"))

    def test_nepovezana_naprava_dobi_ob_prijavi(self):
        self.hub.odklopi(self.fon)
        self.assertEqual(self._poslji(self.tv, "fon1", "Ko prideš")["status"], "queued")
        self.assertEqual(self.hub.steviloCakajocihKlepetov("fon1"), 1)
        nov = LaznaPovezava("192.168.0.60")
        self.hub.obdelaj(nov, _prijava("fon1", "Telefon", "sender", ("url", "chat")))
        self.assertEqual(nov.zadnje("chat.send")["payload"]["text"], "Ko prideš")
        self.assertEqual(self.hub.steviloCakajocihKlepetov("fon1"), 0)

    def test_zastarelo_se_zavrze(self):
        self.hub.odklopi(self.fon)
        self._poslji(self.tv, "fon1", "staro")
        self.cas += 8 * 24 * 3600
        nov = LaznaPovezava("192.168.0.60")
        self.hub.obdelaj(nov, _prijava("fon1", "Telefon", "sender", ("url", "chat")))
        self.assertIsNone(nov.zadnje("chat.send"))

    def test_prazno_in_neznano_zavrnjeno(self):
        self.assertEqual(self._poslji(self.fon, "tv1", "")["status"], "rejected")
        self.assertEqual(self._poslji(self.fon, "nihce", "x")["status"], "rejected")


class KlepetPoNapravi(unittest.TestCase):
    """Cilj je fizicna naprava (kljuc): dobi jo tista njena aplikacija, ki zna klepet."""

    def test_kljuc_izbere_aplikacijo_s_klepetom_in_caka(self):
        kljuci = {"fon-zaslon": "n-fon", "fon-os": "n-fon", "pc": "n-pc"}
        with mock.patch.object(link_hub_streznik.Hub, "naprava_iz_kljuca", staticmethod(lambda i: kljuci.get(i))):
            hub = link_hub_streznik.Hub(odtis="ab" * 32, nas_id="n-racunalnik")
            pc, zaslon, os_ = LaznaPovezava(), LaznaPovezava(), LaznaPovezava()
            hub.obdelaj(pc, _prijava("pc", "Racunalnik", "sender", ("url", "chat")))
            hub.obdelaj(zaslon, _prijava("fon-zaslon", "Telefon", "receiver", ("url",)))
            hub.obdelaj(os_, _prijava("fon-os", "Telefon", "sender", ("url", "chat")))
            r = json.loads(hub.obdelaj(pc, json.dumps({"id": "k1", "type": "chat.send", "target": "n-fon",
                                                        "payload": {"text": "zdravo"}})))
            self.assertEqual(r["status"], "accepted")
            self.assertIsNone(zaslon.zadnje("chat.send"))
            s = os_.zadnje("chat.send")
            self.assertEqual((s["sender"], s["sender_device"]), ("pc", "n-pc"))
            # aplikacija s klepetom se odklopi: sporocilo za napravo pocaka
            hub.odklopi(os_)
            r = json.loads(hub.obdelaj(pc, json.dumps({"id": "k2", "type": "chat.send", "target": "n-fon",
                                                        "payload": {"text": "pozneje"}})))
            self.assertEqual(r["status"], "queued")
            nov = LaznaPovezava()
            hub.obdelaj(nov, _prijava("fon-os", "Telefon", "sender", ("url", "chat")))
            self.assertEqual(nov.zadnje("chat.send")["payload"]["text"], "pozneje")
            # sam sebi (ista fizicna naprava) ne gre
            r = json.loads(hub.obdelaj(pc, json.dumps({"id": "k3", "type": "chat.send", "target": "n-pc",
                                                        "payload": {"text": "x"}})))
            self.assertEqual(r["status"], "rejected")
