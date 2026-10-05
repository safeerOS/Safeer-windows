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
from core.spake2 import Spake2


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


class Register(unittest.TestCase):
    def setUp(self):
        self.hub = link_hub_streznik.Hub(odtis="ab" * 32, nas_id="n-racunalnik")

    def test_prijava_in_seznam(self):
        p = LaznaPovezava()
        odgovor = json.loads(self.hub.obdelaj(p, _prijava("tv1", "Televizor")))
        self.assertEqual(odgovor["type"], "cast.ack")
        self.assertEqual(odgovor["status"], "accepted")
        self.assertEqual(odgovor["ref_id"], "r1")
        seznam = p.zadnje("cast.devices")
        self.assertIsNotNone(seznam)
        self.assertEqual([d["id"] for d in seznam["devices"]], ["tv1"])
        naprava = seznam["devices"][0]
        self.assertEqual(naprava["name"], "Televizor")
        self.assertEqual(naprava["platform"], "tv")
        self.assertEqual(naprava["ip"], "192.168.0.50")

    def test_brez_device_id_zavrnjeno(self):
        p = LaznaPovezava()
        odgovor = json.loads(self.hub.obdelaj(p, json.dumps({"id": "r1", "type": "cast.register", "payload": {}})))
        self.assertEqual(odgovor["status"], "rejected")
        self.assertEqual(odgovor["error_code"], "manjka_device_id")

    def test_nova_povezava_iste_naprave_zamenja_staro(self):
        stara, nova = LaznaPovezava(), LaznaPovezava()
        self.hub.obdelaj(stara, _prijava("tv1"))
        self.hub.obdelaj(nova, _prijava("tv1"))
        self.assertEqual(stara.zaprta_z, (1000, "nova povezava iste naprave"))
        self.assertEqual(self.hub.stevilo(), 1, "naprava ostane ena, ne dve")
        self.assertIs(self.hub.najdi("tv1").povezava, nova)

    def test_vstopnica_velja_samo_za_svojo_napravo(self):
        p = LaznaPovezava()
        p.podatki["id"] = "tv1"
        odgovor = json.loads(self.hub.obdelaj(p, _prijava("tablica")))
        self.assertEqual(odgovor["status"], "rejected")
        self.assertEqual(odgovor["error_code"], "vstopnica_ni_za_to_napravo")

    def test_odklop_osvezi_seznam(self):
        a, b = LaznaPovezava(), LaznaPovezava("192.168.0.60")
        self.hub.obdelaj(a, _prijava("tv1"))
        self.hub.obdelaj(b, _prijava("tablica"))
        self.hub.odklopi(a)
        seznam = b.zadnje("cast.devices")
        self.assertEqual([d["id"] for d in seznam["devices"]], ["tablica"])

    def test_ping_vrne_pong(self):
        p = LaznaPovezava()
        odgovor = json.loads(self.hub.obdelaj(p, json.dumps({"id": "p1", "type": "cast.ping"})))
        self.assertEqual(odgovor["type"], "cast.pong")
        self.assertEqual(odgovor["id"], "p1")

    def test_pokvarjeno_sporocilo_ne_podre_nicesar(self):
        p = LaznaPovezava()
        for smeti in ("{", "[]", "ni json", '"niz"'):
            odgovor = json.loads(self.hub.obdelaj(p, smeti))
            self.assertEqual(odgovor["status"], "rejected")


class Usmerjanje(unittest.TestCase):
    def setUp(self):
        self.hub = link_hub_streznik.Hub(odtis="ab" * 32)
        self.tv = LaznaPovezava("192.168.0.77")
        self.pc = LaznaPovezava("192.168.0.10")
        self.hub.obdelaj(self.tv, _prijava("tv1", "Televizor"))
        self.hub.obdelaj(self.pc, _prijava("pc1", "Racunalnik", vloga="sender"))

    def test_ukaz_pride_do_cilja_s_posiljateljem(self):
        odgovor = json.loads(self.hub.obdelaj(self.pc, json.dumps(
            {"id": "u1", "type": "control.command", "target": "tv1",
             "payload": {"action": "apps.launch"}})))
        self.assertEqual(odgovor["type"], "control.ack")
        self.assertEqual(odgovor["status"], "accepted")
        prejeto = self.tv.zadnje("control.command")
        self.assertEqual(prejeto["sender"], "pc1", "Hub mora vpisati posiljatelja")
        self.assertEqual(prejeto["payload"]["action"], "apps.launch")
        self.assertEqual(prejeto["id"], "u1", "id ukaza ostane isti (ref za odgovor)")

    def test_odgovora_hub_ne_potrjuje(self):
        self.assertIsNone(self.hub.obdelaj(self.tv, json.dumps(
            {"id": "o1", "type": "control.result", "target": "pc1", "payload": {"ok": True}})))
        self.assertIsNotNone(self.pc.zadnje("control.result"))

    def test_neznan_cilj_zavrnjen(self):
        odgovor = json.loads(self.hub.obdelaj(self.pc, json.dumps(
            {"id": "u1", "type": "control.command", "target": "telefon"})))
        self.assertEqual(odgovor["status"], "rejected")
        self.assertEqual(odgovor["error_code"], "ni_naprave")

    def test_sonda_prijavljene_naprave_dobi_isti_naprava(self):
        """Safeer Control po tem loci zivo prijavo od osirotele - mora biti natanko tako."""
        odgovor = json.loads(self.hub.obdelaj(self.pc, json.dumps(
            {"id": "sonda-prijave-1", "type": "control.command", "target": "pc1",
             "payload": {"action": "status"}})))
        self.assertEqual(odgovor["status"], "rejected")
        self.assertEqual(odgovor["error_code"], "isti_naprava")
        self.assertEqual(odgovor["ref_id"], "sonda-prijave-1")

    def test_sonda_osirotele_vticnice_dobi_naprava_ni_povezana(self):
        osirotela = LaznaPovezava()
        odgovor = json.loads(self.hub.obdelaj(osirotela, json.dumps(
            {"id": "sonda-prijave-2", "type": "control.command", "target": "tv1"})))
        self.assertEqual(odgovor["error_code"], "naprava_ni_povezana")

    def test_deljenje_je_v_svojem_prostoru(self):
        odgovor = json.loads(self.hub.obdelaj(self.pc, json.dumps(
            {"id": "d1", "type": "share.text", "target": "tv1", "payload": {"text": "zivjo"}})))
        self.assertEqual(odgovor["type"], "share.ack", "potrditev mora biti v prostoru share")
        self.assertEqual(self.tv.zadnje("share.text")["payload"]["text"], "zivjo")

    def test_brez_cilja_gre_vsem_drugim(self):
        self.hub.obdelaj(self.pc, json.dumps(
            {"id": "s1", "type": "sync.data", "payload": {"category": "bookmarks"}}))
        self.assertIsNotNone(self.tv.zadnje("sync.data"))
        self.assertIsNone(self.pc.zadnje("sync.data"), "posiljatelj sam sebi ne posilja")

    def test_katalog_aplikacij_se_objavi(self):
        self.hub.obdelaj(self.tv, json.dumps(
            {"id": "a1", "type": "apps.announce", "payload": {"apps": {"x": {"name": "X"}}}}))
        seznam = self.pc.zadnje("cast.devices")
        tv = [d for d in seznam["devices"] if d["id"] == "tv1"][0]
        self.assertEqual(tv["apps"], {"x": {"name": "X"}})


class PrijavaSPodpisom(unittest.TestCase):
    def setUp(self):
        self.hub = link_hub_streznik.Hub(odtis="AB" * 32)
        self.kljuc = link_krog.javni_kljuc_b64()
        self.clan = {"kljuc": self.kljuc, "ime": "Tablica", "platforma": "tablet"}

    def _izziv_in_podpis(self, device_id="n-0123456789abcdef"):
        izziv = self.hub.izziv(device_id)
        podatki = link_krog.podatki_za_podpis(izziv["fp"], izziv["nonce"], device_id)
        return izziv, link_krog.podpisi(podatki)

    def test_pravi_podpis_da_vstopnico(self):
        izziv, podpis = self._izziv_in_podpis()
        with mock.patch.object(link_krog, "krog") as k:
            k.return_value.clan_za_id.return_value = self.clan
            k.return_value.json.return_value = {"v": 1, "clani": {}}
            odgovor = self.hub.vstopnica_s_podpisom("n-0123456789abcdef", izziv["nonce"], podpis)
        self.assertIsNotNone(odgovor)
        self.assertTrue(odgovor["ticket"])
        self.assertTrue(odgovor["session_token"], "podpisana naprava potrebuje tudi HTTP sejo")
        self.assertEqual(odgovor["fp"], "ab" * 32, "odtis je vedno z malimi crkami")
        self.assertIn("ring", odgovor, "naprava mora dobiti krog, da pozna ostale")
    def test_vstopnica_velja_enkrat(self):
        izziv, podpis = self._izziv_in_podpis()
        with mock.patch.object(link_krog, "krog") as k:
            k.return_value.clan_za_id.return_value = self.clan
            k.return_value.json.return_value = {}
            odgovor = self.hub.vstopnica_s_podpisom("n-0123456789abcdef", izziv["nonce"], podpis)
        self.assertEqual(self.hub.porabi_vstopnico(odgovor["ticket"]), "n-0123456789abcdef")
        self.assertIsNone(self.hub.porabi_vstopnico(odgovor["ticket"]), "drugic ne velja")

    def test_izziv_velja_enkrat_tudi_ob_napacnem_podpisu(self):
        """Sicer bi lahko kdo na istem izzivu poskusal podpise, dokler eden ne bi ustrezal."""
        izziv, _ = self._izziv_in_podpis()
        with mock.patch.object(link_krog, "krog") as k:
            k.return_value.clan_za_id.return_value = self.clan
            self.assertIsNone(self.hub.vstopnica_s_podpisom("n-0123456789abcdef", izziv["nonce"], "napacen"))
        izziv2, podpis = self._izziv_in_podpis()
        with mock.patch.object(link_krog, "krog") as k:
            k.return_value.clan_za_id.return_value = self.clan
            k.return_value.json.return_value = {}
            self.assertIsNone(self.hub.vstopnica_s_podpisom("n-0123456789abcdef", izziv["nonce"], podpis),
                              "porabljen izziv ne sme vec veljati")

    def test_naprava_zunaj_kroga_ne_dobi_vstopnice(self):
        izziv, podpis = self._izziv_in_podpis()
        with mock.patch.object(link_krog, "krog") as k:
            k.return_value.clan_za_id.return_value = None
            self.assertIsNone(self.hub.vstopnica_s_podpisom("n-0123456789abcdef", izziv["nonce"], podpis))

    def test_tuj_nonce_ne_velja(self):
        self.hub.izziv("n-0123456789abcdef")
        with mock.patch.object(link_krog, "krog") as k:
            k.return_value.clan_za_id.return_value = self.clan
            self.assertIsNone(self.hub.vstopnica_s_podpisom("n-0123456789abcdef", "izmisljen", "x"))

    def test_izziv_za_drugo_napravo_ne_velja(self):
        izziv, podpis = self._izziv_in_podpis("n-0123456789abcdef")
        with mock.patch.object(link_krog, "krog") as k:
            k.return_value.clan_za_id.return_value = self.clan
            self.assertIsNone(self.hub.vstopnica_s_podpisom("n-ffffffffffffffff", izziv["nonce"], podpis))


class Seznanitev(unittest.TestCase):
    def setUp(self):
        self.odtis = "ab" * 32
        self.hub = link_hub_streznik.Hub(odtis=self.odtis)

    def test_sestmestna_koda_spake2_izda_zeton(self):
        zacetek = self.hub.zacni_seznanitev("telefon-1", "Telefon")
        self.assertIsNotNone(zacetek)
        pair_id = zacetek["pair_id"]
        koda = self.hub._prijave[pair_id]["pin"]
        self.assertRegex(koda, r"^\d{6}$")
        odjemalec = Spake2.odjemalec(koda, "telefon-1", link_hub_streznik.IDENTITETA_HUBA,
                                     self.odtis.encode(), pair_id.encode())
        pa, ca, napaka = self.hub.spake_korak1(pair_id, "telefon-1", odjemalec.sporocilo())
        self.assertIsNone(napaka)
        _kljuc, cb = odjemalec.zakljuci(pa)
        self.assertTrue(odjemalec.preveri(ca))
        zeton, napaka = self.hub.spake_korak2(pair_id, "telefon-1", cb)
        self.assertIsNone(napaka)
        self.assertTrue(zeton.startswith("saf_pc_"))
        self.assertEqual(self.hub.naprava_zetona(zeton), ("telefon-1", "Telefon"))
        self.assertNotIn(pair_id, self.hub._prijave)

    def test_napacna_koda_ne_izda_zetona(self):
        zacetek = self.hub.zacni_seznanitev("telefon-2", "Telefon")
        pair_id = zacetek["pair_id"]
        odjemalec = Spake2.odjemalec("000000", "telefon-2", link_hub_streznik.IDENTITETA_HUBA,
                                     self.odtis.encode(), pair_id.encode())
        pa, _ca, napaka = self.hub.spake_korak1(pair_id, "telefon-2", odjemalec.sporocilo())
        self.assertIsNone(napaka)
        _kljuc, cb = odjemalec.zakljuci(pa)
        zeton, napaka = self.hub.spake_korak2(pair_id, "telefon-2", cb)
        self.assertIsNone(zeton)
        self.assertEqual(napaka, "napacna_koda")

    def test_qr_vabilo_pokaze_kdo_se_je_pridruzil(self):
        qr_id, skrivnost = self.hub.ustvari_pridruzitev()
        self.assertTrue(self.hub.stanje_pridruzitve(qr_id)["pending"])
        zeton, napaka = self.hub.pridruzi(qr_id, skrivnost, "tablica-1", "Tablica")
        self.assertIsNone(napaka)
        self.assertTrue(zeton)
        stanje = self.hub.stanje_pridruzitve(qr_id)
        self.assertFalse(stanje["pending"])
        self.assertTrue(stanje["joined"])
        self.assertEqual(stanje["name"], "Tablica")

    def test_koda_vabila_seznani_novo_napravo(self):
        """»Poveži naprave« na racunalniku: vabilo ima 6-mestno kodo, nova naprava se seznani prav z njo
        (vtipka jo s tega zaslona), po seznanitvi koda ne velja vec."""
        qr_id, _skrivnost = self.hub.ustvari_pridruzitev()
        koda = self.hub.pin_pridruzitve(qr_id)
        self.assertRegex(koda, r"^[1-9][0-9]{5}$")
        self.assertTrue(self.hub.ima_odprto_kodo())
        zacetek = self.hub.zacni_seznanitev("telefon-3", "Telefon")
        pair_id = zacetek["pair_id"]
        self.assertEqual(self.hub._prijave[pair_id]["pin"], koda)
        odjemalec = Spake2.odjemalec(koda, "telefon-3", link_hub_streznik.IDENTITETA_HUBA,
                                     self.odtis.encode(), pair_id.encode())
        pa, _ca, napaka = self.hub.spake_korak1(pair_id, "telefon-3", odjemalec.sporocilo())
        self.assertIsNone(napaka)
        _kljuc, cb = odjemalec.zakljuci(pa)
        zeton, napaka = self.hub.spake_korak2(pair_id, "telefon-3", cb)
        self.assertIsNone(napaka)
        self.assertTrue(zeton)
        self.assertEqual(self.hub.pin_pridruzitve(qr_id), "")
        self.assertFalse(self.hub.ima_odprto_kodo())
        # Naslednja naprava brez odprtega vabila dobi novo, nakljucno kodo.
        drugi = self.hub.zacni_seznanitev("telefon-4", "Telefon 2")
        self.assertNotEqual(self.hub._prijave[drugi["pair_id"]]["pin"], koda)

    def test_sorodni_program_dobi_svoj_zeton(self):
        with self.hub._zaklep:
            prvi = self.hub._nov_zeton("n-primer", "Safeer Browser")
        drugi, napaka = self.hub.sorodni_zeton(prvi, "n-primer-control", "Safeer Control")
        self.assertIsNone(napaka)
        self.assertEqual(self.hub.naprava_zetona(drugi), ("n-primer-control", "Safeer Control"))
        zavrnjen, napaka = self.hub.sorodni_zeton(prvi, "tuja-naprava", "Tujec")
        self.assertIsNone(zavrnjen)
        self.assertEqual(napaka, "ni_sorodnik")


class Zdravje(unittest.TestCase):
    def test_steje_prejemnike_in_posiljatelje(self):
        hub = link_hub_streznik.Hub(odtis="ab" * 32)
        hub.obdelaj(LaznaPovezava(), _prijava("tv1", vloga="receiver"))
        hub.obdelaj(LaznaPovezava(), _prijava("pc1", vloga="sender", zmoznosti=("sync",)))
        z = hub.zdravje()
        self.assertEqual((z["receivers"], z["senders"], z["sync_peers"]), (1, 1, 1))
        self.assertEqual(z["status"], "ok")


class Razsirljivost(unittest.TestCase):
    """Naprava iz leta 2028 se mora znati pogovarjati z Hubom iz leta 2026 in obratno.

    Pogoj je, da neznana polja nikogar ne podrejo: nova zmoznost se doda kot novo polje, stara
    stran ga preskoci in dela naprej s tistim, kar pozna. To je isto, kar je pri BitTorrentu
    razsiritev v rokovanju - le da tu ni treba nicesar dodajati, ker protokol to ze prenese.
    """

    def setUp(self):
        self.hub = link_hub_streznik.Hub(odtis="ab" * 32)

    def test_neznana_polja_v_prijavi_ne_motijo(self):
        p = LaznaPovezava()
        prijava = json.dumps({
            "id": "r1", "type": "cast.register", "nekaj_novega": {"x": 1},
            "payload": {"device_id": "novost", "name": "Naprava 2028", "role": "receiver",
                        "capabilities": ["url", "files", "neznana_zmoznost"],
                        "capability_versions": {"files": 3, "screen": 2},
                        "prihodnje_polje": [1, 2, 3]},
        })
        odgovor = json.loads(self.hub.obdelaj(p, prijava))
        self.assertEqual(odgovor["status"], "accepted", "neznana polja ne smejo zavrniti prijave")
        naprava = p.zadnje("cast.devices")["devices"][0]
        self.assertIn("neznana_zmoznost", naprava["capabilities"],
                      "neznano zmoznost posredujemo naprej, da jo razume, kdor jo pozna")

    def test_neznana_vrsta_sporocila_se_posreduje_naprej(self):
        """Hub ni razsodnik vsebine: sporocilo, ki ga ne pozna, mora priti do cilja."""
        a, b = LaznaPovezava(), LaznaPovezava("192.168.0.60")
        self.hub.obdelaj(a, _prijava("a1"))
        self.hub.obdelaj(b, _prijava("b1"))
        odgovor = json.loads(self.hub.obdelaj(a, json.dumps(
            {"id": "n1", "type": "prihodnost.novost", "target": "b1", "payload": {"kaj": "novo"}})))
        self.assertEqual(odgovor["status"], "accepted")
        self.assertEqual(odgovor["type"], "prihodnost.ack")
        prejeto = b.zadnje("prihodnost.novost")
        self.assertIsNotNone(prejeto, "neznano sporocilo mora priti do cilja nespremenjeno")
        self.assertEqual(prejeto["payload"], {"kaj": "novo"})

    def test_stara_naprava_brez_novih_polj_dela_naprej(self):
        """Naprava protokola 0.2 ne poslje platform/kind/version - to ne sme biti tezava."""
        p = LaznaPovezava()
        odgovor = json.loads(self.hub.obdelaj(p, json.dumps(
            {"id": "r1", "type": "cast.register",
             "payload": {"device_id": "stara", "name": "Naprava 2024", "role": "receiver"}})))
        self.assertEqual(odgovor["status"], "accepted")
        naprava = p.zadnje("cast.devices")["devices"][0]
        self.assertNotIn("platform", naprava, "praznih polj ne izmisljujemo")
        self.assertEqual(naprava["capabilities"], [])


class KrogPoHttp(unittest.TestCase):
    """Krog zaupanja gospodinjstva ni za vsakogar v omrezju: brez prijave ga ne da."""

    def test_krog_brez_prijave_ni_dostopen(self):
        o = link_hub_streznik._Obravnava.__new__(link_hub_streznik._Obravnava)
        o.path = "/cast/trust/ring"
        o._je_krajevni = lambda: True
        odgovori = []
        o._odgovori = lambda koda, telo: odgovori.append((koda, telo))
        o._napaka = lambda koda, sporocilo, oznaka: odgovori.append((koda, oznaka))
        with mock.patch.object(link_krog, "krog") as k:
            k.return_value.json.return_value = {"clani": {"skrivno": {}}}
            o.do_GET()
            k.assert_not_called()
        self.assertEqual(odgovori, [(401, "naprava_ni_seznanjena")])


if __name__ == "__main__":
    unittest.main()


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
