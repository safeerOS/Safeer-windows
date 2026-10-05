"""Link Mesh (docs/LINK-MESH.md): vsaka naprava gosti svoj Hub, Hubi so sosedje vsak z vsakim.

Preizkus brez omrezja: pravi Hub.obdelaj na vseh straneh, sosednja povezava je lazna cev, ki
sporocilo takoj preda drugemu Hubu. Preverjamo prav tisto, kar mora drzati v hisi: vsaka naprava
vidi vsako, izpad enega vozlisca podre samo njegove naprave, ni zank, ni ponarejanja posiljatelja.
"""
import json
import unittest
from unittest import mock

from core import link_hub_streznik as lhs

TUJCI = {"tujec"}


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

    def vrste(self, tip):
        return [s for s in self.poslano if s.get("type") == tip]

    def zadnje(self, tip):
        v = self.vrste(tip)
        return v[-1] if v else None


class Cev:
    """Ena stran sosednje povezave: kar poslje ta stran, obdela Hub na drugi strani."""

    def __init__(self, cilj_hub):
        self.cilj_hub = cilj_hub
        self.druga = None
        self.podatki = {}
        self.naslov = "192.168.0.9"
        self.zaprta = False
        self.poslano = []
        # Dokler druga stran povezave se ni sprejela (kot TCP: bajti cakajo v vrsti).
        self.vrsta = []
        self.zadrzi = True

    def poslji(self, besedilo):
        if self.zaprta:
            return False
        self.poslano.append(json.loads(besedilo))
        if self.zadrzi:
            self.vrsta.append(besedilo)
            return True
        self.cilj_hub.obdelaj(self.druga, besedilo)
        return True

    def spusti(self):
        self.zadrzi = False
        vrsta, self.vrsta = self.vrsta, []
        for b in vrsta:
            self.cilj_hub.obdelaj(self.druga, b)

    def zapri(self, koda=1000, razlog=""):
        self.zaprta = True


def povezi(a, b, zacel=None):
    """Sosednja povezava med Huboma a in b (kot da jo je odprl `zacel`)."""
    zacel = zacel or a.nas_id
    a_proti_b = Cev(b)          # a poslje -> obdela b
    b_proti_a = Cev(a)          # b poslje -> obdela a
    a_proti_b.druga = b_proti_a   # b vidi povezavo od a kot b_proti_a
    b_proti_a.druga = a_proti_b
    a.dodaj_soseda(b.nas_id, a_proti_b, zacel)
    b.dodaj_soseda(a.nas_id, b_proti_a, zacel)
    a_proti_b.spusti()
    b_proti_a.spusti()
    return a_proti_b, b_proti_a


def prijava(hub, did, zmoznosti=("url", "remote", "text", "chat")):
    p = LaznaPovezava()
    p.podatki["id"] = did
    odgovor = json.loads(hub.obdelaj(p, json.dumps({
        "id": "r", "type": "cast.register",
        "payload": {"device_id": did, "name": did.upper(), "role": "receiver",
                    "capabilities": list(zmoznosti), "platform": "tv"}})))
    assert odgovor["status"] == "accepted", odgovor
    return p


def ids(povezava):
    return sorted(d["id"] for d in povezava.zadnje("cast.devices")["devices"])


class Mesh(unittest.TestCase):
    def setUp(self):
        krog = mock.MagicMock()
        krog.json.return_value = {"v": 1, "clani": {}, "umiki": {}}
        krog.zdruzi.return_value = False
        krog.clan_za_id.return_value = None
        self._krog = mock.patch.object(lhs.link_krog, "krog", return_value=krog)
        self._krog.start()
        self._clan = mock.patch.object(lhs.Hub, "_je_clan", lambda self, i: i not in TUJCI)
        self._clan.start()
        self.a = lhs.Hub(odtis="aa" * 32, nas_id="hub-a")
        self.b = lhs.Hub(odtis="bb" * 32, nas_id="hub-b")
        self.c = lhs.Hub(odtis="cc" * 32, nas_id="hub-c")

    def tearDown(self):
        self._clan.stop()
        self._krog.stop()

    def test_vsaka_naprava_vidi_vsako(self):
        tv = prijava(self.a, "tv")
        pc = prijava(self.b, "pc")
        povezi(self.a, self.b)
        self.assertEqual(ids(tv), ["pc", "tv"])
        self.assertEqual(ids(pc), ["pc", "tv"])

    def test_sosed_ni_naprava(self):
        tv = prijava(self.a, "tv")
        povezi(self.a, self.b)
        self.assertNotIn("hub-b", ids(tv))

    def test_usmerjanje_s_ciljem_prek_soseda(self):
        tv = prijava(self.a, "tv")
        pc = prijava(self.b, "pc")
        povezi(self.a, self.b)
        odgovor = json.loads(self.b.obdelaj(pc, json.dumps(
            {"id": "u1", "type": "control.command", "target": "tv", "payload": {"action": "pause"}})))
        self.assertEqual(odgovor["status"], "accepted")
        prejeto = tv.zadnje("control.command")
        self.assertIsNotNone(prejeto)
        self.assertEqual(prejeto["sender"], "pc")
        # odgovor gre nazaj isto pot
        self.a.obdelaj(tv, json.dumps({"id": "u2", "type": "control.result", "target": "pc", "ref_id": "u1"}))
        self.assertIsNotNone(pc.zadnje("control.result"))

    def test_oddaja_natanko_enkrat_v_polni_mrezi(self):
        tv = prijava(self.a, "tv")
        pc = prijava(self.b, "pc")
        tel = prijava(self.c, "tel")
        povezi(self.a, self.b)
        povezi(self.b, self.c)
        povezi(self.a, self.c)
        self.assertEqual(ids(tv), ["pc", "tel", "tv"])
        self.a.obdelaj(tv, json.dumps({"id": "o1", "type": "share.text", "payload": {"text": "zivjo"}}))
        self.assertEqual(len(pc.vrste("share.text")), 1)
        self.assertEqual(len(tel.vrste("share.text")), 1)
        self.assertEqual(len(tv.vrste("share.text")), 0)

    def test_izpad_soseda_podre_samo_njegove_naprave(self):
        tv = prijava(self.a, "tv")
        pc = prijava(self.b, "pc")
        tel = prijava(self.c, "tel")
        ab, _ = povezi(self.a, self.b)
        povezi(self.a, self.c)
        povezi(self.b, self.c)
        self.a.odklopi(ab)                 # povezava a->b pade na strani a
        # b je se vedno dosegljiv prek c (en vmesni skok)
        self.assertEqual(ids(tv), ["pc", "tel", "tv"])
        self.assertEqual(ids(tel), ["pc", "tel", "tv"])   # c se vedno vidi oba
        self.assertEqual(self.a.sosedje(), ["hub-c"])

    def test_lokalna_prijava_ima_prednost(self):
        prijava(self.b, "tel")
        povezi(self.a, self.b)
        tel_lokalno = prijava(self.a, "tel")
        tv = prijava(self.a, "tv")
        self.a.obdelaj(tv, json.dumps({"id": "x", "type": "share.text", "target": "tel", "payload": {"text": "a"}}))
        self.assertEqual(len(tel_lokalno.vrste("share.text")), 1)
        # nov seznam soseda ga ne sme prepisati nazaj na oddaljenega
        self.b.objavi_naprave()
        self.a.obdelaj(tv, json.dumps({"id": "y", "type": "share.text", "target": "tel", "payload": {"text": "b"}}))
        self.assertEqual(len(tel_lokalno.vrste("share.text")), 2)

    def test_mesh_od_navadne_naprave_zavrnjen(self):
        tv = prijava(self.a, "tv")
        odgovor = json.loads(self.a.obdelaj(tv, json.dumps(
            {"id": "m", "type": "mesh.route", "payload": {"to": "tv", "msg": "{}"}})))
        self.assertEqual(odgovor["status"], "rejected")
        self.assertEqual(odgovor["error_code"], "ni_sosed")

    def test_route_na_nelokalno_napravo_se_ne_posreduje(self):
        tv = prijava(self.a, "tv")
        prijava(self.c, "tel")
        ab, ba = povezi(self.a, self.b)
        povezi(self.a, self.c)
        # b (sosed a) poskusi skozi a doseci napravo, ki je pri c: a tega ne sme posredovati naprej
        self.a.obdelaj(ab, json.dumps({"type": "mesh.route", "payload": {
            "to": "tel", "msg": json.dumps({"type": "share.text", "sender": "hub-b"})}}))
        self.assertEqual(len(tv.vrste("share.text")), 0)
        c_cev = self.a._sosedje["hub-c"]
        self.assertFalse(any(s.get("type") == "mesh.route" and s["payload"]["to"] == "tel"
                             and "hub-b" in s["payload"]["msg"] for s in c_cev.poslano))

    def test_sosed_ne_more_ponarediti_posiljatelja(self):
        tv = prijava(self.a, "tv")
        prijava(self.b, "pc")
        ab, _ = povezi(self.a, self.b)
        self.a.obdelaj(ab, json.dumps({"type": "mesh.route", "payload": {
            "to": "tv", "msg": json.dumps({"type": "control.command", "sender": "tv-drugje"})}}))
        self.assertIsNone(tv.zadnje("control.command"))
        self.a.obdelaj(ab, json.dumps({"type": "mesh.route", "payload": {
            "to": "tv", "msg": json.dumps({"type": "control.command", "sender": "pc"})}}))
        self.assertIsNotNone(tv.zadnje("control.command"))

    def test_sosed_samo_s_podpisom_clana(self):
        p = LaznaPovezava()
        p.podatki = {"id": "hub-x", "podpis": False}
        prijava_huba = json.dumps({"id": "h", "type": "cast.register", "payload": {
            "device_id": "hub-x", "role": "hub", "capabilities": ["mesh1"]}})
        self.assertEqual(json.loads(self.a.obdelaj(p, prijava_huba))["status"], "rejected")
        p.podatki = {"id": "hub-x", "podpis": True}
        self.assertEqual(json.loads(self.a.obdelaj(p, prijava_huba))["status"], "accepted")
        self.assertEqual(self.a.sosedje(), ["hub-x"])
        t = LaznaPovezava()
        t.podatki = {"id": "tujec", "podpis": True}
        self.assertEqual(json.loads(self.a.obdelaj(t, json.dumps({"id": "h", "type": "cast.register", "payload": {
            "device_id": "tujec", "role": "hub", "capabilities": ["mesh1"]}})))["status"], "rejected")

    def test_zavrnjen_sosed_se_zapre(self):
        p = LaznaPovezava()
        p.podatki = {"id": "hub-x", "podpis": False}
        lhs._na_sporocilo(self.a, p, json.dumps({"id": "h", "type": "cast.register", "payload": {
            "device_id": "hub-x", "role": "hub", "capabilities": ["mesh1"]}}))
        self.assertEqual(p.zadnje("cast.ack")["status"], "rejected")
        self.assertIsNotNone(p.zaprta_z, "zavrnjena sosednja povezava ne sme ostati odprta")

    def test_tujec_ne_pride_cez_mejo_huba(self):
        tv = prijava(self.a, "tv")
        prijava(self.b, "tujec")
        prijava(self.b, "pc")
        povezi(self.a, self.b)
        self.assertEqual(ids(tv), ["pc", "tv"])

    def test_podvojena_povezava_ostane_ena(self):
        tv = prijava(self.a, "tv")
        prijava(self.b, "pc")
        povezi(self.a, self.b, zacel="hub-a")
        prva_a = self.a._sosedje["hub-b"]
        # b hkrati poklice a: nova povezava, ki jo je zacel vecji id, se zavrne na obeh straneh
        povezi(self.b, self.a, zacel="hub-b")
        self.assertIs(self.a._sosedje["hub-b"], prva_a)
        self.assertEqual(ids(tv), ["pc", "tv"])

    def test_vecji_id_poklice_prvi_nato_se_manjsi_ostane_povezava_manjsega(self):
        # Po zagonu Hub poklice znane sosede sam, tudi ce ima vecji id. Ce medtem poklice se sosed z manjsim id,
        # mora na obeh straneh obveljati ista povezava (manjsega), naprave pa ostati v seznamu.
        tv = prijava(self.a, "tv")
        pc = prijava(self.b, "pc")
        povezi(self.b, self.a, zacel="hub-b")
        self.assertEqual(ids(tv), ["pc", "tv"])
        prva_a, prva_b = self.a._sosedje["hub-b"], self.b._sosedje["hub-a"]
        druga_a, druga_b = povezi(self.a, self.b, zacel="hub-a")
        self.assertIs(self.a._sosedje["hub-b"], druga_a)
        self.assertIs(self.b._sosedje["hub-a"], druga_b)
        self.assertIsNot(self.a._sosedje["hub-b"], prva_a)
        self.assertIsNot(self.b._sosedje["hub-a"], prva_b)
        self.assertEqual(ids(tv), ["pc", "tv"])
        self.assertEqual(ids(pc), ["pc", "tv"])

    def test_klepet_pocaka_in_pride_prek_soseda(self):
        tv = prijava(self.a, "tv")
        prijava(self.b, "tel")
        ab, _ = povezi(self.a, self.b)
        self.a.odklopi(ab)                 # telefon (pri b) je zdaj nedosegljiv
        odgovor = json.loads(self.a.obdelaj(tv, json.dumps(
            {"id": "k", "type": "chat.send", "target": "tel", "payload": {"text": "pridi"}})))
        self.assertEqual(odgovor["status"], "queued")
        tel2 = prijava(self.c, "tel")      # telefon se pojavi pri c
        povezi(self.a, self.c)
        self.assertEqual(len(tel2.vrste("chat.send")), 1)
        self.assertEqual(tel2.zadnje("chat.send")["sender"], "tv")

    def test_seznam_sosedu_samo_ob_spremembi(self):
        prijava(self.a, "tv")
        ab, _ = povezi(self.a, self.b)
        pred = len([s for s in ab.poslano if s["type"] == "mesh.devices"])
        self.a.objavi_naprave()
        self.a.objavi_naprave()
        po = len([s for s in ab.poslano if s["type"] == "mesh.devices"])
        self.assertEqual(pred, po)
        prijava(self.a, "tablica")
        self.assertEqual(len([s for s in ab.poslano if s["type"] == "mesh.devices"]), po + 1)

    def test_brez_posiljatelja_samo_seznanitev(self):
        tv = prijava(self.a, "tv")
        prijava(self.b, "pc")
        ab, _ = povezi(self.a, self.b)
        self.a.obdelaj(ab, json.dumps({"type": "mesh.route", "payload": {
            "to": "tv", "msg": json.dumps({"type": "control.command"})}}))
        self.assertIsNone(tv.zadnje("control.command"))
        self.a.obdelaj(ab, json.dumps({"type": "mesh.route", "payload": {
            "to": "tv", "msg": json.dumps({"type": "pair.code", "payload": {"code": "123456"}})}}))
        self.assertIsNotNone(tv.zadnje("pair.code"))

    # -- dostava prek vmesnega vozlisca (relay, en skok)

    def test_relay_vidi_in_usmeri(self):
        tv = prijava(self.a, "tv")
        prijava(self.b, "pc")
        tel = prijava(self.c, "tel")
        povezi(self.a, self.b)
        bc, cb = povezi(self.b, self.c)          # a in c se ne dosezeta
        self.assertEqual(ids(tv), ["pc", "tel", "tv"])
        self.assertEqual(ids(tel), ["pc", "tel", "tv"])
        self.a.obdelaj(tv, json.dumps({"id": "r1", "type": "control.command", "target": "tel", "payload": {}}))
        ukaz = tel.zadnje("control.command")
        self.assertIsNotNone(ukaz)
        self.assertEqual(ukaz["sender"], "tv")
        self.c.obdelaj(tel, json.dumps({"id": "r2", "type": "control.result", "target": "tv", "ref_id": "r1"}))
        self.assertIsNotNone(tv.zadnje("control.result"))

    def test_neposredna_pot_ima_prednost(self):
        tv = prijava(self.a, "tv")
        prijava(self.b, "pc")
        tel = prijava(self.c, "tel")
        ab, _ = povezi(self.a, self.b)
        povezi(self.b, self.c)
        povezi(self.a, self.c)
        pred = len([s for s in ab.poslano if s["type"] == "mesh.route"])
        self.a.obdelaj(tv, json.dumps({"id": "d", "type": "share.text", "target": "tel", "payload": {"text": "x"}}))
        self.assertEqual(len(tel.vrste("share.text")), 1)
        self.assertEqual(len([s for s in ab.poslano if s["type"] == "mesh.route"]), pred, "ne prek b")

    def test_izpad_neposredne_pot_prek_vmesnega(self):
        tv = prijava(self.a, "tv")
        prijava(self.b, "pc")
        tel = prijava(self.c, "tel")
        povezi(self.a, self.b)
        povezi(self.b, self.c)
        ac, _ = povezi(self.a, self.c)
        self.a.odklopi(ac)                        # a izgubi c, b pa ga se vidi
        self.assertEqual(ids(tv), ["pc", "tel", "tv"])
        self.a.obdelaj(tv, json.dumps({"id": "e", "type": "share.text", "target": "tel", "payload": {"text": "x"}}))
        self.assertEqual(len(tel.vrste("share.text")), 1)

    def test_relay_ni_verige_in_ne_ponareja(self):
        prijava(self.a, "tv")
        prijava(self.b, "pc")
        tel = prijava(self.c, "tel")
        ab, _ = povezi(self.a, self.b)
        povezi(self.b, self.c)
        # b dobi prosnjo za posredovanje v imenu naprave, ki ni lokalno pri a: zavrzeno
        self.b.obdelaj(self.b._sosedje["hub-a"], json.dumps({"type": "mesh.route", "payload": {
            "to": "tel", "relay": True, "msg": json.dumps({"type": "share.text", "sender": "pc"})}}))
        self.assertEqual(len(tel.vrste("share.text")), 0)
        # relay na napravo, ki je pri b posredna (ali lokalna), se ne posreduje dalje
        d = lhs.Hub(odtis="dd" * 32, nas_id="hub-d")
        tab = prijava(d, "tablica")
        povezi(self.c, d)
        self.b.obdelaj(self.b._sosedje["hub-a"], json.dumps({"type": "mesh.route", "payload": {
            "to": "tablica", "relay": True, "msg": json.dumps({"type": "share.text", "sender": "tv"})}}))
        self.assertEqual(len(tab.vrste("share.text")), 0, "najvec en vmesni skok")

    def test_izpad_vmesnega(self):
        tv = prijava(self.a, "tv")
        prijava(self.b, "pc")
        prijava(self.c, "tel")
        ab, _ = povezi(self.a, self.b)
        povezi(self.b, self.c)
        self.a.odklopi(ab)
        self.assertEqual(ids(tv), ["tv"])


class Klicanje(unittest.TestCase):
    """Koga nas Hub poklice: samo clane kroga z mesh1; manjsi id prvi."""

    def setUp(self):
        from core import link_mesh
        self.link_mesh = link_mesh
        krog = mock.MagicMock()
        krog.clan_za_id.side_effect = lambda i: None if i in TUJCI else {"kljuc": "k-" + i}
        self._krog = mock.patch.object(link_mesh.link_krog, "krog", return_value=krog)
        self._krog.start()
        self.hub = lhs.Hub(odtis="aa" * 32, nas_id="n-m")

    def tearDown(self):
        self._krog.stop()

    def oglas(self, hid, mesh="mesh1"):
        return {"id": hid, "naslov": "wss://10.0.0.1:8990/cast/ws", "tls": True, "mesh": mesh}

    def test_izbira(self):
        m = self.link_mesh.MeshPovezovalec(self.hub, "n-m")
        izbrani = [h["id"] for h in m.kandidati(
            [self.oglas("n-z"), self.oglas("n-a"), self.oglas("tujec"), self.oglas("n-y", mesh=""),
             self.oglas("n-m")], zdaj=100.0)]
        # n-z je vecji: klicemo mi; n-a je manjsi: pocakamo; tujec in star Hub ne; sebe ne.
        self.assertEqual(izbrani, ["n-z"])
        # Ce nas manjsi dolgo ne poklice, klicemo sami.
        izbrani = [h["id"] for h in m.kandidati([self.oglas("n-a")], zdaj=100.0 + self.link_mesh.VECJI_CAKA_S + 1)]
        self.assertEqual(izbrani, ["n-a"])

    def test_zapomnjeni_naslov_brez_mdns(self):
        import tempfile, os
        pot = os.path.join(tempfile.mkdtemp(), "znani.json")
        m = self.link_mesh.MeshPovezovalec(self.hub, "n-m", pot_znanih=pot, poisci=lambda: [])
        m.zapomni("n-z", "192.168.0.220")          # samo IP iz dohodne povezave
        m2 = self.link_mesh.MeshPovezovalec(lhs.Hub(odtis="bb" * 32, nas_id="n-m"), "n-m", pot_znanih=pot,
                                            poisci=lambda: [])
        self.assertEqual(m2._znani["n-z"]["naslov"], "wss://192.168.0.220:8990/cast/ws")
        klicani = []
        m2._klici = lambda h: klicani.append(h["id"])
        import threading
        stari = threading.Thread
        class Takoj:
            def __init__(self, target=None, args=(), **_k): self.t, self.a = target, args
            def start(self): self.t(*self.a)
        threading.Thread = Takoj
        try:
            m2.en_krog()
        finally:
            threading.Thread = stari
        self.assertEqual(klicani, ["n-z"])

    def _po_ponovnem_zagonu(self, znani, nas="n-m"):
        """Povezovalec, ki je v prejsnjem teku poznal sosede `znani` (id -> IP), po ponovnem zagonu."""
        import os
        import tempfile
        pot = os.path.join(tempfile.mkdtemp(), "znani.json")
        prej = self.link_mesh.MeshPovezovalec(lhs.Hub(odtis="cc" * 32, nas_id=nas), nas, pot_znanih=pot, poisci=lambda: [])
        for hid, ip in znani.items():
            prej.zapomni(hid, ip)
        return self.link_mesh.MeshPovezovalec(self.hub, nas, pot_znanih=pot, poisci=lambda: [])

    def _en_krog_takoj(self, m):
        """en_krog brez niti: vrne id-je sosedov, ki bi jih poklical."""
        import threading
        klicani = []
        m._klici = lambda h: klicani.append(h["id"])
        stari = threading.Thread

        class Takoj:
            def __init__(self, target=None, args=(), **_k): self.t, self.a = target, args
            def start(self): self.t(*self.a)
        threading.Thread = Takoj
        try:
            m.en_krog()
        finally:
            threading.Thread = stari
        return klicani

    def test_po_zagonu_poklicemo_znanega_soseda_z_manjsim_id(self):
        # Sosed za nas ponovni zagon ne ve: nasel bi nas sele v svojem naslednjem krogu iskanja.
        m = self._po_ponovnem_zagonu({"n-a": "192.168.0.10", "n-z": "192.168.0.20"})
        self.assertEqual(sorted(self._en_krog_takoj(m)), ["n-a", "n-z"])

    def test_po_zagonu_ne_cakamo_na_oglase(self):
        # Zanka najprej poklice zapomnjene sosede - brez iskanja oglasov mDNS (to vzame sekunde).
        m = self._po_ponovnem_zagonu({"n-a": "192.168.0.10"})
        iskanj = []
        m.poisci = lambda: iskanj.append(1) or []
        import threading
        klicani = []
        m._klici = lambda h: klicani.append(h["id"])
        stari = threading.Thread

        class Takoj:
            def __init__(self, target=None, args=(), **_k): self.t, self.a = target, args
            def start(self): self.t(*self.a)
        m._ustavljen.set()                  # zanka naredi samo zacetni klic in se konca
        threading.Thread = Takoj
        try:
            m._zanka()
        finally:
            threading.Thread = stari
        self.assertEqual(klicani, ["n-a"])
        self.assertEqual(iskanj, [], "zacetni klic znanih sosedov ne isce oglasov")
        self.assertEqual(m._po_zagonu, set())

    def test_brez_znanih_sosedov_zanka_zacne_kot_prej(self):
        m = self.link_mesh.MeshPovezovalec(self.hub, "n-m", poisci=lambda: [])
        klici = []
        pravi = m.en_krog
        m.en_krog = lambda isci=True: klici.append(isci) or pravi(isci)
        m._ustavljen.set()
        m._zanka()
        self.assertEqual(klici, [], "brez zapomnjenih sosedov ni zacetnega klica; ustavljena zanka ne isce")

    def test_prednost_po_zagonu_velja_en_krog(self):
        m = self._po_ponovnem_zagonu({"n-a": "192.168.0.10"})
        self.assertEqual(self._en_krog_takoj(m), ["n-a"])
        with m._zaklep:
            m._klicem.clear()               # klic ni uspel (soseda ni)
        # Naslednji krog: obicajno pravilo - manjsi id klice prvi, mi pocakamo.
        self.assertEqual(self._en_krog_takoj(m), [])
        self.assertEqual(m.kandidati([self.oglas("n-a")]), [])
        import time as _time
        self.assertEqual([h["id"] for h in m.kandidati([self.oglas("n-a")], zdaj=_time.time() + self.link_mesh.VECJI_CAKA_S + 1)],
                         ["n-a"])

    def test_neznanega_soseda_z_manjsim_id_po_zagonu_pocakamo(self):
        m = self._po_ponovnem_zagonu({"n-z": "192.168.0.20"})
        izbrani = [h["id"] for h in m.kandidati([self.oglas("n-a"), self.oglas("n-z")], zdaj=100.0)]
        self.assertEqual(izbrani, ["n-z"])

    def test_po_zagonu_tujca_in_starega_huba_ne_klicemo(self):
        m = self._po_ponovnem_zagonu({"tujec": "192.168.0.30", "n-a": "192.168.0.10"})
        self.assertEqual(self._en_krog_takoj(m), ["n-a"])

    def test_brez_zapomnjenih_sosedov_ostane_po_starem(self):
        m = self.link_mesh.MeshPovezovalec(self.hub, "n-m")
        self.assertEqual(m._po_zagonu, set())
        self.assertEqual(m.kandidati([self.oglas("n-a")], zdaj=100.0), [])

    def test_premor_po_zavrnitvi(self):
        m = self.link_mesh.MeshPovezovalec(self.hub, "n-m")
        m._zavrnjeni["n-z"] = (1000.0, 30.0)
        self.assertEqual(m.kandidati([self.oglas("n-z")], zdaj=999.0), [])
        self.assertEqual([h["id"] for h in m.kandidati([self.oglas("n-z")], zdaj=1001.0)], ["n-z"])

    def test_premor_se_podvoji_in_izbrise_sele_ob_sprejemu(self):
        import json as _json
        m = self.link_mesh.MeshPovezovalec(self.hub, "n-m")

        class Ws:
            def __init__(self, sporocila): self.sporocila = list(sporocila)
            def prejmi(self): return self.sporocila.pop(0) if self.sporocila else None

        class Pov:
            def __init__(self, sporocila): self.ws, self.zaprta = Ws(sporocila), False
            def zapri(self): self.zaprta = True
            def poslji(self, _s): pass

        zavrnitev = _json.dumps({"type": "cast.ack", "status": "rejected", "error_code": "podvojeno"})
        self.hub.odklopi = lambda _p: None
        m._beri("n-z", Pov([zavrnitev]))
        self.assertEqual(m._zavrnjeni["n-z"][1], 30.0)
        m._beri("n-z", Pov([zavrnitev]))
        self.assertEqual(m._zavrnjeni["n-z"][1], 60.0)
        # Sosed nas sprejme (prvo sporocilo ni zavrnitev): premor izgine.
        self.hub.obdelaj = lambda _p, _s: None
        m._beri("n-z", Pov([_json.dumps({"type": "mesh.devices", "payload": {}})]))
        self.assertNotIn("n-z", m._zavrnjeni)


class GlobalLinkMesh(unittest.TestCase):
    """Sosed zunaj doma: po neuspelih neposrednih klicih ga klicemo prek releja link.safeer.si."""

    def setUp(self):
        import base64, hashlib, os
        from core import link_mesh, link_rele
        self.link_mesh = link_mesh
        self.kljuc = base64.b64encode(os.urandom(32)).decode()
        self.hid = link_rele.id_iz_kljuca(self.kljuc)
        krog = mock.MagicMock()
        krog.clan_za_id.side_effect = lambda i: {"kljuc": self.kljuc} if i in (self.hid, "n-drug") else None
        self._krog = mock.patch.object(link_mesh.link_krog, "krog", return_value=krog)
        self._krog.start()
        self._okolje = mock.patch.dict(os.environ, {"SAFEER_MESH_RELE": "", "SAFEER_GLOBAL_LINK": "1"})
        self._okolje.start()
        self.hub = lhs.Hub(odtis="aa" * 32, nas_id="n-m")
        self.m = link_mesh.MeshPovezovalec(self.hub, "n-m")
        self.naslovi = []

        class Rele:
            vrata, zadnja_napaka = 45678, "404"
            def zapri(self): pass
        self.m._releji[self.hid] = Rele()

    def tearDown(self):
        self._okolje.stop()
        self._krog.stop()

    def oglas(self):
        return {"id": self.hid, "naslov": "wss://192.168.0.77:8990/cast/ws", "tls": True, "mesh": "mesh1"}

    def odpri(self, doma: bool, rele: bool):
        def f(h):
            self.naslovi.append(h["naslov"])
            return rele if h["naslov"].startswith("wss://127.0.0.1:") else doma
        self.m._odpri = f

    def test_rele_sele_po_dveh_neuspehih(self):
        self.odpri(doma=False, rele=True)
        self.m._klici(self.oglas())
        self.assertEqual(self.naslovi, ["wss://192.168.0.77:8990/cast/ws"])
        self.m._klici(self.oglas())
        self.assertEqual(self.naslovi[1:], ["wss://192.168.0.77:8990/cast/ws", "wss://127.0.0.1:45678/cast/ws"])
        # Doma spet dosegljiv: stevec neuspehov se pobrise, rele ni vec potreben.
        self.odpri(doma=True, rele=True)
        self.naslovi.clear()
        self.m._klici(self.oglas())
        self.assertEqual(self.naslovi, ["wss://192.168.0.77:8990/cast/ws"])
        self.assertNotIn(self.hid, self.m._neuspehi)

    def test_zavrnitev_ni_neuspeh(self):
        # Sosed je dosegljiv, a nas zavrne (ze ima povezavo): to ni razlog za rele.
        self.odpri(doma=True, rele=True)
        for _ in range(3):
            self.m._klici(self.oglas())
        self.assertTrue(all(n.startswith("wss://192.168.0.77") for n in self.naslovi))

    def test_premor_releja_raste(self):
        self.odpri(doma=False, rele=False)
        self.m._neuspehi[self.hid] = 5
        self.m._klici(self.oglas())
        self.assertEqual(self.m._premor_releja[self.hid][1], self.link_mesh.PREMOR_RELEJA_S)
        self.naslovi.clear()
        self.m._klici(self.oglas())           # v premoru: rele ne klicemo (kvota)
        self.assertEqual(self.naslovi, ["wss://192.168.0.77:8990/cast/ws"])
        self.m._premor_releja[self.hid] = (0.0, self.link_mesh.PREMOR_RELEJA_S)
        self.m._klici(self.oglas())
        self.assertEqual(self.m._premor_releja[self.hid][1], 2 * self.link_mesh.PREMOR_RELEJA_S)

    def test_preizkusno_samo_prek_releja(self):
        import os
        self.odpri(doma=True, rele=True)
        with mock.patch.dict(os.environ, {"SAFEER_MESH_RELE": self.hid}):
            self.m._klici(self.oglas())
        self.assertEqual(self.naslovi, ["wss://127.0.0.1:45678/cast/ws"])

    def test_izklopljen_global_link(self):
        import os
        self.odpri(doma=False, rele=True)
        self.m._neuspehi[self.hid] = 5
        with mock.patch.dict(os.environ, {"SAFEER_GLOBAL_LINK": "0"}):
            self.m._klici(self.oglas())
        self.assertEqual(self.naslovi, ["wss://192.168.0.77:8990/cast/ws"])

    def test_rele_samo_za_id_iz_kljuca(self):
        # Rele pozna napravo samo po id-ju iz njenega kljuca; id, ki ne izhaja iz kljuca, ne gre prek releja.
        self.assertIsNone(self.m._rele("n-drug"))
        # Hub z id-jem s pripono (n-...-control): cilj releja je id iz kljuca.
        from core import link_rele
        ustvarjeni = []

        class Lazni:
            def __init__(self, cilj): self.cilj, self.vrata = cilj, 1; ustvarjeni.append(cilj)
        krog = self.link_mesh.link_krog.krog()
        krog.clan_za_id.side_effect = lambda i: {"kljuc": self.kljuc}
        with mock.patch.object(link_rele, "LokalniRele", Lazni):
            self.assertIsNotNone(self.m._rele(self.hid + "-control"))
        self.assertEqual(ustvarjeni, [self.hid])

    def test_naslov_releja_si_ne_zapomnimo(self):
        self.m.zapomni(self.hid, "127.0.0.1")
        self.m.zapomni(self.hid, "wss://127.0.0.1:45678/cast/ws")
        self.m.zapomni(self.hid, "::1")
        self.assertNotIn(self.hid, self.m._znani)
        self.m.zapomni(self.hid, "192.168.0.77")
        self.assertEqual(self.m._znani[self.hid]["naslov"], "wss://192.168.0.77:8990/cast/ws")

    def test_agent_samo_z_vrati_in_vklopljen(self):
        import os
        zagnani = []

        class Agent:
            def __init__(self, **k): self.k = k
            def zazeni(self): zagnani.append(self)
        from core import link_rele
        with mock.patch.object(link_rele, "AgentHuba", Agent), mock.patch.object(self.link_mesh, "_agent", None):
            self.m._zazeni_agenta()                         # brez vrat (npr. preizkus): nic
            self.assertEqual(zagnani, [])
            with mock.patch.dict(os.environ, {"SAFEER_GLOBAL_LINK": "0"}):
                self.link_mesh.MeshPovezovalec(self.hub, "n-m", vrata=lambda: 8990)._zazeni_agenta()
            self.assertEqual(zagnani, [])
            prvi = self.link_mesh.MeshPovezovalec(self.hub, "n-m", vrata=lambda: 8990)
            prvi._zazeni_agenta()
            drugi = self.link_mesh.MeshPovezovalec(self.hub, "n-m", vrata=lambda: 9001)
            drugi._zazeni_agenta()
            self.assertEqual(len(zagnani), 1)              # en agent na proces
            self.assertEqual(zagnani[0].k["vrata"](), 9001)  # vrata trenutnega Huba
            drugi.ustavi()
            self.assertEqual(zagnani[0].k["vrata"](), 0)     # Hub ustavljen: agent ne sprejema kanalov


class ReleCev(unittest.TestCase):
    """Kanal releja: vticnici se sprostita sele, ko obe niti koncata (sicer TLS bere tuje bajte)."""

    def test_sprostitev_po_koncu_obeh_niti(self):
        import socket, threading
        from core import link_rele
        dogodki = []
        a, b = socket.socketpair()

        class Ws:
            def __init__(self): self.konec = threading.Event()
            def prejmi(self):
                self.konec.wait(5)
                raise ConnectionError("zaprto")
            def poslji(self, _p): pass
            def zapri(self): dogodki.append("ws.zapri"); self.konec.set()
            def sprosti(self): dogodki.append("ws.sprosti")

        b.sendall(b"x")
        b.close()                     # lokalna stran konca: iz_tcp zapre kanal, glavna nit se vrne
        link_rele.cev(Ws(), a)
        self.assertEqual(dogodki[-1], "ws.sprosti")
        self.assertEqual(a.fileno(), -1)   # tcp zaprt sele na koncu


if __name__ == "__main__":
    unittest.main()
