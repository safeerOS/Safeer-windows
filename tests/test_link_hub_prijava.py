"""Odjemalec Safeer Linka (core/link_hub.py) je en za Linux in Windows: stvari, ki jih je imela samo ena veja.

Krog 108 (5. 10. 2026): datoteki sta se razsli v obe smeri; Windowsovo sredisce zaradi tega ni znalo vabila nove
naprave, Linuxov odjemalec pa ni vracal prioritete sredisca iz oglasa in je ob prehodni napaki podpisa pozabil seznanitev.
"""
import json
import sys
import types
import unittest
from unittest import mock

from core import link_hub

HUB = "wss://192.0.2.10:8990/cast/ws"
ODTIS = "ab" * 32


class _Ws:
    """Ponaredek WsOdjemalec: zapomni si, kaj je bilo poslano."""
    primerki = []

    def __init__(self, naslov, odtis=None, **_k):
        self.naslov, self.odtis, self.poslano, self.zaprt = naslov, odtis, [], False
        _Ws.primerki.append(self)

    def odpri(self):
        pass

    def poslji(self, besedilo):
        self.poslano.append(json.loads(besedilo))

    def zapri(self):
        self.zaprt = True


def _povezava(zeton="", v_krog=True):
    return link_hub.Povezava(ws_naslov=HUB, zeton=zeton, device_id="n-0123456789abcdef-control", ime="Racunalnik",
                             odtis=ODTIS, v_krog=v_krog)


class PrijavaSPodpisom(unittest.TestCase):
    """Neuspel podpis brez zetona: zavrnitev je samo izrecen 401/403."""

    def setUp(self):
        _Ws.primerki.clear()
        self.z_zetonom = []
        self._zaplate = [
            mock.patch.object(link_hub.link_krog, "lahko_s_podpisom", return_value=True),
            mock.patch.object(link_hub, "WsOdjemalec", _Ws),
            mock.patch.object(link_hub, "vzemi_vstopnico_s_kodo", self._s_kodo),
            mock.patch.object(link_hub, "vpisi_v_krog", return_value=False),
        ]
        for z in self._zaplate:
            z.start()
            self.addCleanup(z.stop)
        self.odgovor_zetona = (None, 401)

    def _s_kodo(self, naslov, zeton, odtis=None):
        self.z_zetonom.append(zeton)
        return self.odgovor_zetona

    def _podpis(self, vstopnica, koda):
        z = mock.patch.object(link_hub, "vzemi_vstopnico_s_podpisom", return_value=(vstopnica, koda))
        z.start()
        self.addCleanup(z.stop)

    def test_prehodna_napaka_podpisa_ni_zavrnitev(self):
        for koda in (0, 429, 500, 503):
            with self.subTest(koda=koda):
                self.z_zetonom.clear()
                self._podpis(None, koda)
                p = _povezava(zeton="")
                self.assertFalse(p._odpri())
                self.assertFalse(p.zavrnjena)             # prej: prazen zeton -> 401 -> seznanitev pozabljena
                self.assertEqual(self.z_zetonom, [])       # s praznim zetonom sredisca ne sprasujemo

    def test_izrecna_zavrnitev_podpisa_je_zavrnitev(self):
        for koda in (401, 403):
            with self.subTest(koda=koda):
                self._podpis(None, koda)
                p = _povezava(zeton="")
                self.assertFalse(p._odpri())
                self.assertTrue(p.zavrnjena)

    def test_z_zetonom_gre_po_neuspelem_podpisu_zeton(self):
        self._podpis(None, 500)
        self.odgovor_zetona = ("vstopnica-z", 200)
        p = _povezava(zeton="saf_pc_x")
        self.assertTrue(p._odpri())
        self.assertEqual(self.z_zetonom, ["saf_pc_x"])
        self.assertFalse(p.zavrnjena)
        self.assertFalse(p.prijava_s_podpisom)

    def test_zeton_ki_ga_sredisce_ne_pozna_je_zavrnitev(self):
        self._podpis(None, 500)
        self.odgovor_zetona = (None, 401)
        p = _povezava(zeton="saf_pc_star")
        self.assertFalse(p._odpri())
        self.assertTrue(p.zavrnjena)

    def test_brez_kroga_in_brez_zetona_kot_prej(self):
        # Naprava, ki ni v krogu: podpisa ne poskusimo; vprasamo z (praznim) zetonom in sredisce odloci.
        with mock.patch.object(link_hub.link_krog, "lahko_s_podpisom", return_value=False):
            p = _povezava(zeton="")
            self.assertFalse(p._odpri())
        self.assertEqual(self.z_zetonom, [""])
        self.assertTrue(p.zavrnjena)

    def test_uspel_podpis_poslje_prijavo_in_imena_kroga(self):
        self._podpis("vstopnica-p", 200)
        with mock.patch.object(link_hub.link_krog, "krog") as krog:
            krog.return_value.json.return_value = {"clani": [{"id": "n-1", "ime": "Dnevna soba"}]}
            p = _povezava(zeton="")
            self.assertTrue(p._odpri())
        ws = _Ws.primerki[-1]
        self.assertIn("ticket=vstopnica-p", ws.naslov)
        self.assertEqual([s["type"] for s in ws.poslano], ["cast.register", "trust.names"])
        self.assertEqual(ws.poslano[1]["payload"], {"clani": [{"id": "n-1", "ime": "Dnevna soba"}]})
        self.assertTrue(p.prijava_s_podpisom)
        self.assertFalse(p.zavrnjena)
        self.assertEqual(self.z_zetonom, [])


class _Info:
    def __init__(self, naslov, vrata, lastnosti):
        self._naslov, self.port, self.properties = naslov, vrata, lastnosti

    def parsed_addresses(self):
        return [self._naslov]


class OglasSredisca(unittest.TestCase):
    """Oglas mDNS: id, prioriteta in oznaka mesh pridejo do klicatelja."""

    OGLASI = {
        "tv": _Info("192.0.2.77", 8990, {b"tls": b"1", b"fp": b"AA11", b"name": b"Televizor", b"id": b"n-tv",
                                          b"prio": b"100", b"mesh": b"mesh1"}),
        "pc": _Info("192.0.2.135", 8990, {b"tls": b"1", b"id": b"n-pc-control", b"prio": b"80", b"mesh": b"mesh1"}),
        "star": _Info("192.0.2.20", 8990, {b"tls": b"1", b"id": b"n-star"}),
        "pokvarjen": _Info("192.0.2.21", 8990, {b"tls": b"1", b"id": b"n-x", b"prio": b"visoka"}),
        "prevelik": _Info("192.0.2.22", 8990, {b"tls": b"1", b"id": b"n-y", b"prio": b"99999"}),
    }

    def _poisci(self):
        oglasi = self.OGLASI

        class Zeroconf:
            def get_service_info(self, vrsta, ime, timeout=0):
                return oglasi[ime]

            def close(self):
                pass

        class ServiceBrowser:
            def __init__(self, zc, vrsta, poslusalec):
                for ime in oglasi:
                    poslusalec.add_service(zc, vrsta, ime)

            def cancel(self):
                pass

        lazni = types.SimpleNamespace(Zeroconf=Zeroconf, ServiceBrowser=ServiceBrowser, ServiceListener=object)
        with mock.patch.dict(sys.modules, {"zeroconf": lazni}):
            return {h["id"]: h for h in link_hub.poisci_hube_mdns(0.0)}

    def test_prioriteta_iz_oglasa(self):
        hubi = self._poisci()
        self.assertEqual(hubi["n-tv"]["prio"], 100)
        self.assertEqual(hubi["n-pc-control"]["prio"], 80)
        self.assertEqual(hubi["n-star"]["prio"], 0)            # starejse sredisce brez prioritete
        self.assertEqual(hubi["n-x"]["prio"], 0)               # neberljiva vrednost
        self.assertEqual(hubi["n-y"]["prio"], 1000)            # omejena navzgor

    def test_ostala_polja(self):
        tv = self._poisci()["n-tv"]
        self.assertEqual(tv["naslov"], "wss://192.0.2.77:8990/cast/ws")
        self.assertEqual((tv["fp"], tv["tls"], tv["ime"], tv["mesh"]), ("aa11", True, "Televizor", "mesh1"))

    def test_izvolitev_uposteva_prioriteto(self):
        from core import link_hub_streznik
        hubi = list(self._poisci().values())
        boljsi = link_hub_streznik.boljsi_hub(hubi, "n-pc-control", prioriteta=80)
        self.assertEqual(boljsi["id"], "n-y")                  # najvisja prioriteta med oglasenimi
        samo_enaki = [h for h in hubi if h["id"] in ("n-pc-control", "n-star")]
        self.assertIsNone(link_hub_streznik.boljsi_hub(samo_enaki, "n-pc-control", prioriteta=80))


class Vabilo(unittest.TestCase):
    """»Poveži novo napravo«: PIN samo, ce je res sest stevilk; lastno sredisce da v kodo domaci naslov."""

    def _povabi(self, odgovor, hub=HUB):
        with mock.patch.object(link_hub, "_zahteva", return_value=(200, odgovor)):
            return link_hub.povabi(hub, "saf_pc_x", ODTIS)

    def test_pin_sest_stevilk(self):
        osnova = {"qr_id": "q1", "secret": "s1", "fp": ODTIS, "expires_in_seconds": 300}
        self.assertEqual(self._povabi(dict(osnova, pin="474046"))["pin"], "474046")
        self.assertEqual(self._povabi(dict(osnova, code="474 046"))["pin"], "474046")
        self.assertEqual(self._povabi(dict(osnova, pin="4740"))["pin"], "")
        self.assertEqual(self._povabi(dict(osnova, pin="abcdef"))["pin"], "")
        self.assertEqual(self._povabi(osnova)["pin"], "")

    def test_lastno_sredisce_da_domaci_naslov(self):
        v = self._povabi({"qr_id": "q1", "secret": "s1", "fp": ODTIS, "address": "192.0.2.50:8990", "pin": "123456"},
                         hub="wss://127.0.0.1:8990/cast/ws")
        self.assertIn("a=192.0.2.50:8990", v["povezava"])
        self.assertNotIn("127.0.0.1", v["povezava"])

    def test_napake(self):
        for koda, napaka in ((404, "hub_star"), (405, "hub_star"), (401, "ni_seznanjena"), (500, "ni_huba")):
            with mock.patch.object(link_hub, "_zahteva", return_value=(koda, {})):
                self.assertEqual(link_hub.povabi(HUB, "z", ODTIS), {"napaka": napaka})


if __name__ == "__main__":
    unittest.main()
