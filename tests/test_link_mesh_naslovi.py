"""Link Mesh: naslov naprave cez mejo Huba ni nikoli 127.0.0.1.

Z Link Mesh se vsak program poveze na Hub svoje naprave, zato mu ta pripise 127.0.0.1. Ta naslov velja samo tam.
5. 10. 2026 ga je telefon dobil od sosednjega Huba za Safeer Control na racunalniku in se za sliko zaslona
povezal sam nase ("failed to connect to /127.0.0.1"). Cez mejo Huba zato potuje naslov racunalnika, na katerem
naprava je - na obeh straneh meje, da je dovolj ena posodobljena naprava.

Brez omrezja: pravi Hub.obdelaj na vseh straneh, sosednja povezava je lazna cev (kot tests/test_link_mesh.py).
"""
import json
import unittest
from unittest import mock

from core import link_hub_streznik as lhs

PC = "192.168.0.135"
TV = "192.168.0.77"
TABLICA = "192.168.0.87"


class Odjemalec:
    """Program, prijavljen pri Hubu: `naslov` je to, kar Hub vidi kot drugi konec povezave."""

    def __init__(self, naslov):
        self.naslov = naslov
        self.poslano = []
        self.podatki = {}

    def poslji(self, besedilo):
        self.poslano.append(json.loads(besedilo))
        return True

    def zapri(self, koda=1000, razlog=""):
        pass

    def naprave(self):
        seznami = [s for s in self.poslano if s.get("type") == "cast.devices"]
        return {d["id"]: d for d in seznami[-1]["devices"]}


class Vticnica:
    """Kar Hub prebere iz prave vticnice sosednje povezave."""

    def __init__(self, nas, sosed):
        self._nas, self._sosed = nas, sosed

    def getsockname(self):
        if self._nas is None:
            raise OSError("zaprta")
        return (self._nas, 40000)

    def getpeername(self):
        if self._sosed is None:
            raise OSError("zaprta")
        return (self._sosed, 8765)


class Cev:
    """Ena stran sosednje povezave: kar poslje ta stran, obdela Hub na drugi strani."""

    def __init__(self, cilj_hub, naslov, vticnik=None):
        self.cilj_hub = cilj_hub
        self.druga = None
        self.podatki = {}
        self.naslov = naslov
        if vticnik is not None:
            self.vticnik = vticnik
        self.poslano = []
        self.vrsta = []
        self.zadrzi = True

    def poslji(self, besedilo):
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
        pass

    def zadnji_seznam(self):
        return [s for s in self.poslano if s.get("type") == "mesh.devices"][-1]["payload"]


def povezi(a, b, a_vidi_b, b_vidi_a, vticnici=None):
    """Sosednja povezava: `a_vidi_b` je naslov, ki si ga a zapomni za b (IP dohodne ali wss:// odhodne povezave)."""
    va, vb = vticnici or (None, None)
    a_proti_b = Cev(b, a_vidi_b, va)
    b_proti_a = Cev(a, b_vidi_a, vb)
    a_proti_b.druga = b_proti_a
    b_proti_a.druga = a_proti_b
    a.dodaj_soseda(b.nas_id, a_proti_b, a.nas_id)
    b.dodaj_soseda(a.nas_id, b_proti_a, a.nas_id)
    a_proti_b.spusti()
    b_proti_a.spusti()
    return a_proti_b, b_proti_a


def prijava(hub, did, naslov="127.0.0.1"):
    p = Odjemalec(naslov)
    p.podatki["id"] = did
    odgovor = json.loads(hub.obdelaj(p, json.dumps({
        "id": "r", "type": "cast.register",
        "payload": {"device_id": did, "name": did.upper(), "role": "receiver",
                    "capabilities": ["desktop", "remote"], "platform": "linux"}})))
    assert odgovor["status"] == "accepted", odgovor
    return p


class NaslovCezMejo(unittest.TestCase):
    def setUp(self):
        krog = mock.MagicMock()
        krog.json.return_value = {"v": 1, "clani": {}, "umiki": {}}
        krog.zdruzi.return_value = False
        krog.clan_za_id.return_value = None
        self._krog = mock.patch.object(lhs.link_krog, "krog", return_value=krog)
        self._krog.start()
        self._clan = mock.patch.object(lhs.Hub, "_je_clan", lambda self, i: True)
        self._clan.start()
        self.pc = lhs.Hub(odtis="aa" * 32, nas_id="hub-pc")
        self.tv = lhs.Hub(odtis="bb" * 32, nas_id="hub-tv")
        self.tretji = lhs.Hub(odtis="cc" * 32, nas_id="hub-tretji")

    def tearDown(self):
        self._clan.stop()
        self._krog.stop()

    # ---------------------------------------------------------------- uvoz

    def test_sosedov_program_dobi_naslov_sosedovega_racunalnika(self):
        """Prav to je padlo: Safeer Control na racunalniku je bil na televizorju in telefonu »127.0.0.1«."""
        control = prijava(self.pc, "control")            # na racunalniku: pri svojem Hubu prek zanke
        os_tv = prijava(self.tv, "os-tv")                # na televizorju: enako
        povezi(self.pc, self.tv, a_vidi_b="wss://%s:8765/cast/ws" % TV, b_vidi_a=PC)
        self.assertEqual(os_tv.naprave()["control"]["ip"], PC)
        self.assertEqual(control.naprave()["os-tv"]["ip"], TV)

    def test_svoj_program_ostane_na_zanki(self):
        """Na ISTI napravi je 127.0.0.1 pravi naslov; po njem programi vedo, kaj tece na njihovi napravi."""
        control = prijava(self.pc, "control")
        prijava(self.tv, "os-tv")
        povezi(self.pc, self.tv, a_vidi_b=TV, b_vidi_a=PC)
        self.assertEqual(control.naprave()["control"]["ip"], "127.0.0.1")

    def test_starejsi_sosed_poslje_zanko(self):
        """Sosed, ki popravka se nima, poslje 127.0.0.1 - prevedemo ga pri sebi."""
        control = prijava(self.pc, "control")
        k_tv, _ = povezi(self.pc, self.tv, a_vidi_b=TV, b_vidi_a=PC)
        self.pc.obdelaj(k_tv, json.dumps({"id": "m", "type": "mesh.devices", "payload": {
            "hub": "hub-tv", "relay": {},
            "devices": {"os-tv": {"name": "TV", "role": "receiver", "capabilities": ["remote"], "ip": "127.0.0.1"},
                        "brskalnik": {"name": "B", "role": "receiver", "capabilities": [], "ip": "::1"},
                        "brez": {"name": "X", "role": "receiver", "capabilities": []}}}}))
        naprave = control.naprave()
        self.assertEqual(naprave["os-tv"]["ip"], TV)
        self.assertEqual(naprave["brskalnik"]["ip"], TV)
        self.assertEqual(naprave["brez"]["ip"], TV)

    def test_pravi_naslov_ostane(self):
        """Naprava, ki je pri sosedu prijavljena iz omrezja, obdrzi svoj naslov - ni na sosedovem racunalniku."""
        control = prijava(self.pc, "control")
        prijava(self.tv, "tablica", naslov=TABLICA)
        k_tv, _ = povezi(self.pc, self.tv, a_vidi_b=TV, b_vidi_a=PC)
        self.assertEqual(control.naprave()["tablica"]["ip"], TABLICA)
        self.assertEqual(self.tv.najdi("tablica").naslov, TABLICA)
        # ... in tako tudi odide: sosed dobi isti naslov.
        k_pc = k_tv.druga                                # povezava, po kateri televizor posilja racunalniku
        self.assertEqual(k_pc.zadnji_seznam()["devices"]["tablica"]["ip"], TABLICA)

    def test_ipv4_v_zapisu_ipv6(self):
        control = prijava(self.pc, "control")
        prijava(self.tv, "os-tv")
        povezi(self.pc, self.tv, a_vidi_b="::ffff:" + TV, b_vidi_a="::ffff:" + PC)
        self.assertEqual(control.naprave()["os-tv"]["ip"], TV)

    def test_prek_releja_naslova_ni(self):
        """Global Link: drugi konec sosednje povezave je 127.0.0.1 (krajevni konec releja). Naprave v domacem
        omrezju ni - prazen naslov pove resnico, 127.0.0.1 bi kazal na nas same."""
        control = prijava(self.pc, "control")
        os_tv = prijava(self.tv, "os-tv")
        povezi(self.pc, self.tv, a_vidi_b="wss://127.0.0.1:45555/cast/ws", b_vidi_a="127.0.0.1",
               vticnici=(Vticnica("127.0.0.1", "127.0.0.1"), Vticnica("127.0.0.1", "127.0.0.1")))
        self.assertEqual(control.naprave()["os-tv"]["ip"], "")
        self.assertEqual(os_tv.naprave()["control"]["ip"], "")

    def test_naslov_iz_prave_vticnice_ima_prednost(self):
        """Odhodna povezava si zapomni ime, na katerega je klicala; velja IP, s katerim je res povezana."""
        control = prijava(self.pc, "control")
        prijava(self.tv, "os-tv")
        povezi(self.pc, self.tv, a_vidi_b="wss://safeer-tv.local:8765/cast/ws", b_vidi_a=PC,
               vticnici=(Vticnica(PC, TV), None))
        self.assertEqual(control.naprave()["os-tv"]["ip"], TV)

    def test_zaprta_vticnica_ne_podre_uvoza(self):
        control = prijava(self.pc, "control")
        prijava(self.tv, "os-tv")
        povezi(self.pc, self.tv, a_vidi_b=TV, b_vidi_a=PC, vticnici=(Vticnica(None, None), Vticnica(None, None)))
        self.assertEqual(control.naprave()["os-tv"]["ip"], TV)

    # ---------------------------------------------------------------- izvoz

    def test_izvoz_nosi_nas_naslov_na_poti_do_soseda(self):
        """Dovolj je posodobljen racunalnik: televizor in telefon s starejso razlicico dobita pravi naslov."""
        prijava(self.pc, "control")
        k_tv, _ = povezi(self.pc, self.tv, a_vidi_b=TV, b_vidi_a=PC, vticnici=(Vticnica(PC, TV), Vticnica(TV, PC)))
        self.assertEqual(k_tv.zadnji_seznam()["devices"]["control"]["ip"], PC)

    def test_izvoz_brez_znanega_naslova_ne_poslje_zanke(self):
        prijava(self.pc, "control")
        k_tv, _ = povezi(self.pc, self.tv, a_vidi_b=TV, b_vidi_a=PC)          # lazna cev: vticnice ni
        self.assertEqual(k_tv.zadnji_seznam()["devices"]["control"]["ip"], "")

    def test_vsak_sosed_dobi_naslov_svoje_poti(self):
        """Racunalnik z dvema omrezjema: vsak sosed dobi naslov, prek katerega racunalnik res doseze."""
        prijava(self.pc, "control")
        k_tv, _ = povezi(self.pc, self.tv, a_vidi_b=TV, b_vidi_a=PC, vticnici=(Vticnica(PC, TV), None))
        k_3, _ = povezi(self.pc, self.tretji, a_vidi_b="10.0.0.7", b_vidi_a="10.0.0.2",
                        vticnici=(Vticnica("10.0.0.2", "10.0.0.7"), None))
        prijava(self.pc, "os-pc")                        # sprememba: seznam gre obema sosedoma
        self.assertEqual(k_tv.zadnji_seznam()["devices"]["os-pc"]["ip"], PC)
        self.assertEqual(k_3.zadnji_seznam()["devices"]["os-pc"]["ip"], "10.0.0.2")

    def test_seznam_sosedu_se_vedno_samo_ob_spremembi(self):
        prijava(self.pc, "control")
        k_tv, _ = povezi(self.pc, self.tv, a_vidi_b=TV, b_vidi_a=PC, vticnici=(Vticnica(PC, TV), None))
        prej = len([s for s in k_tv.poslano if s.get("type") == "mesh.devices"])
        self.pc.objavi_naprave()
        self.pc.objavi_naprave()
        self.assertEqual(len([s for s in k_tv.poslano if s.get("type") == "mesh.devices"]), prej)

    # ---------------------------------------------------------------- dva skoka

    def test_dva_skoka_naslov_prevede_vmesni_hub(self):
        """pc - tv - tretji (pc in tretji nimata svoje poti): program s tretjega pride do pc z naslovom tretjega."""
        control = prijava(self.pc, "control")
        prijava(self.tretji, "os-3")
        povezi(self.tv, self.tretji, a_vidi_b="192.168.0.30", b_vidi_a=TV)
        povezi(self.pc, self.tv, a_vidi_b=TV, b_vidi_a=PC)
        self.assertEqual(control.naprave()["os-3"]["ip"], "192.168.0.30")

    def test_dva_skoka_zanka_starejsega_vmesnega_huba_ni_naslov(self):
        control = prijava(self.pc, "control")
        k_tv, _ = povezi(self.pc, self.tv, a_vidi_b=TV, b_vidi_a=PC)
        self.pc.obdelaj(k_tv, json.dumps({"id": "m", "type": "mesh.devices", "payload": {
            "hub": "hub-tv", "devices": {},
            "relay": {"os-3": {"name": "T", "role": "receiver", "capabilities": [], "ip": "127.0.0.1",
                               "hub": "hub-tretji"}}}}))
        self.assertEqual(control.naprave()["os-3"]["ip"], "")


class Pomozne(unittest.TestCase):
    def test_gostitelj_naslova(self):
        g = lhs._gostitelj_naslova
        self.assertEqual(g("192.168.0.77"), "192.168.0.77")
        self.assertEqual(g("wss://192.168.0.77:8765/cast/ws"), "192.168.0.77")
        self.assertEqual(g("wss://[fd00::7]:8765/cast/ws"), "fd00::7")
        self.assertEqual(g("::ffff:192.168.0.77"), "192.168.0.77")
        self.assertEqual(g("fe80::1%enp1s0"), "fe80::1")
        self.assertEqual(g(None), "")

    def test_samo_tukaj(self):
        for n in ("", None, "127.0.0.1", "127.0.1.1", "::1", "localhost", "wss://127.0.0.1:4/cast/ws", "fe80::1%eth0",
                  "::ffff:127.0.0.1"):
            self.assertTrue(lhs._samo_tukaj(n), n)
        for n in ("192.168.0.77", "10.0.0.2", "fd00::7", "wss://192.168.0.77:8765/cast/ws", "safeer-tv.local"):
            self.assertFalse(lhs._samo_tukaj(n), n)

    def test_naslov_za_druge(self):
        f = lhs._naslov_za_druge
        self.assertEqual(f("127.0.0.1", PC), PC)
        self.assertEqual(f("", PC), PC)
        self.assertEqual(f(TABLICA, PC), TABLICA)
        self.assertEqual(f("127.0.0.1", ""), "")
        self.assertEqual(f("127.0.0.1", "127.0.0.1"), "")
        self.assertEqual(f("::1", "wss://%s:8765/cast/ws" % PC), PC)

    def test_vticnica_ki_ne_vrne_niza(self):
        """Lazni predmeti v drugih preizkusih (MagicMock) ne smejo postati »naslov«."""
        povezava = mock.MagicMock()
        povezava.naslov = "192.168.0.9"
        self.assertEqual(lhs._nas_naslov_proti(povezava), "")
        self.assertEqual(lhs._gostitelj_soseda(povezava), "192.168.0.9")


if __name__ == "__main__":
    unittest.main()
