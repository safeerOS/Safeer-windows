"""Naslovi, ki jih racunalnik nasteje drugi napravi (`hosts` v `audio.play` in v odgovoru na `screen.start`).

Naprava vsak naslov poskusi posebej in na vsakem caka nekaj sekund, zato je vrstni red pomemben: najprej naslov,
ki ga naprava v istem omrezju res doseze. Racunalnik, ki ves promet posilja skozi VPN, je prej nastel samo naslov
predora - zvok na telefon in zaslon racunalnika takrat nista delala, ceprav sta bili napravi v istem omrezju.
"""
import socket
import unittest

from core import link_zvok

UP, ZANKA, PREDOR = 0x1, 0x8, 0x10
HUB_TU = "wss://127.0.0.1:8990/cast/ws"


def _poti(privzeta: str, **posebne):
    """Nadomestek za naslov_na_poti: privzeta pot, razen za nastete cilje (pika v imenu cilja = podcrtaj)."""
    klici = []

    def na_poti(cilj: str) -> str:
        klici.append(cilj)
        return posebne.get(cilj.replace(".", "_"), privzeta)
    na_poti.klici = klici
    return na_poti


class VrstniRed(unittest.TestCase):
    def test_domaci_racunalnik_z_vsebniki(self):
        vmesniki = [("lo", "127.0.0.1", UP | ZANKA), ("enp1s0", "192.168.0.135", UP),
                    ("br-61befd3fbbaf", "10.83.1.1", UP), ("docker0", "172.17.0.1", UP),
                    ("veth6a3bf73", "169.254.3.4", UP), ("virbr0", "192.168.122.1", UP)]
        naslovi = link_zvok.lastni_naslovi(HUB_TU, lambda: vmesniki, _poti("192.168.0.135", **{"127_0_0_1": "127.0.0.1"}))
        self.assertEqual(naslovi, ["192.168.0.135"])

    def test_ves_promet_skozi_vpn_krajevni_naslov_je_prvi(self):
        vmesniki = [("lo", "127.0.0.1", UP | ZANKA), ("wlp2s0", "192.168.1.50", UP), ("wg0", "10.8.0.2", UP | PREDOR)]
        naslovi = link_zvok.lastni_naslovi(HUB_TU, lambda: vmesniki, _poti("10.8.0.2", **{"127_0_0_1": "127.0.0.1"}))
        self.assertEqual(naslovi, ["192.168.1.50", "10.8.0.2"])

    def test_hub_drugje_naslov_proti_njemu_je_prvi(self):
        vmesniki = [("eth0", "192.168.0.20", UP), ("wlan0", "192.168.5.20", UP)]
        na_poti = _poti("192.168.0.20", **{"192_168_5_1": "192.168.5.20"})
        naslovi = link_zvok.lastni_naslovi("wss://192.168.5.1:8990/cast/ws", lambda: vmesniki, na_poti)
        self.assertEqual(naslovi, ["192.168.5.20", "192.168.0.20"])

    def test_dve_omrezji_privzeta_pot_prva(self):
        vmesniki = [("wlan0", "192.168.5.20", UP), ("eth0", "192.168.0.20", UP)]
        naslovi = link_zvok.lastni_naslovi(HUB_TU, lambda: vmesniki, _poti("192.168.0.20"))
        self.assertEqual(naslovi, ["192.168.0.20", "192.168.5.20"])

    def test_ugasnjen_vmesnik_in_predor_na_koncu(self):
        vmesniki = [("eth0", "192.168.0.20", 0), ("wlan0", "192.168.5.20", UP), ("tailscale0", "100.64.0.7", UP | PREDOR),
                    ("tun0", "10.9.0.6", UP | PREDOR)]
        naslovi = link_zvok.lastni_naslovi(HUB_TU, lambda: vmesniki, _poti("192.168.5.20"))
        self.assertEqual(naslovi, ["192.168.5.20", "100.64.0.7", "10.9.0.6"])

    def test_uporabnikov_most_ostane(self):
        # Navidezni stroji (KVM): naslov omrezja je na mostu br0, fizicni vmesnik ga nima.
        vmesniki = [("br0", "192.168.0.60", UP), ("virbr0", "192.168.122.1", UP)]
        self.assertEqual(link_zvok.lastni_naslovi(HUB_TU, lambda: vmesniki, _poti("192.168.0.60")), ["192.168.0.60"])

    def test_privzeta_pot_na_izlocenem_vmesniku_ostane_v_seznamu(self):
        vmesniki = [("br-lan", "192.168.8.1", UP)]
        self.assertEqual(link_zvok.lastni_naslovi(HUB_TU, lambda: vmesniki, _poti("192.168.8.1")), ["192.168.8.1"])

    def test_najvec_stirje_in_vsak_enkrat(self):
        vmesniki = [("eth%d" % i, "10.1.%d.2" % i, UP) for i in range(8)] + [("eth9", "10.1.0.2", UP)]
        naslovi = link_zvok.lastni_naslovi(HUB_TU, lambda: vmesniki, _poti("10.1.3.2"))
        self.assertEqual(naslovi, ["10.1.3.2", "10.1.0.2", "10.1.1.2", "10.1.2.2"])
        self.assertEqual(link_zvok.NAJVEC_NASLOVOV, 4)

    def test_brez_omrezja_je_seznam_prazen(self):
        self.assertEqual(link_zvok.lastni_naslovi(HUB_TU, lambda: [("lo", "127.0.0.1", UP | ZANKA)], _poti("")), [])
        self.assertEqual(link_zvok.lastni_naslovi("", lambda: [], _poti("")), [])

    def test_pokvarjeni_zapisi_ne_podrejo(self):
        vmesniki = [("eth0",), None, ("eth1", None, UP), ("eth2", "ni-naslov", UP), ("eth3", "192.168.0.9", "x"),
                    ("eth4", "192.168.0.300", UP), ("eth5", "192.168.0.7", UP), ("eth6", "0.0.0.0", UP)]
        self.assertEqual(link_zvok.lastni_naslovi(HUB_TU, lambda: vmesniki, _poti("192.168.0.7")), ["192.168.0.7"])

        def pade():
            raise OSError("ni dovoljeno")
        self.assertEqual(link_zvok.lastni_naslovi(HUB_TU, pade, _poti("192.168.0.7")), ["192.168.0.7"])


class BrezVmesnikov(unittest.TestCase):
    """Sistem, ki vmesnikov ne pove: kot prej naslovi na poti do huba in do pogostih domacih omrezij."""

    def test_poti_do_huba_in_domacih_omrezij(self):
        na_poti = _poti("192.168.0.20", **{"192_168_5_1": "192.168.5.20", "10_0_0_1": "10.0.0.4"})
        naslovi = link_zvok.lastni_naslovi("wss://192.168.5.1:8990/cast/ws", lambda: [], na_poti)
        self.assertEqual(naslovi, ["192.168.5.20", "192.168.0.20", "10.0.0.4"])

    def test_windows_naslovi_brez_imen(self):
        vmesniki = [("", "192.168.0.220", UP), ("", "172.28.96.1", UP)]
        naslovi = link_zvok.lastni_naslovi(HUB_TU, lambda: vmesniki, _poti("192.168.0.220"))
        self.assertEqual(naslovi, ["192.168.0.220", "172.28.96.1"])


class HubZImenom(unittest.TestCase):
    def test_imena_huba_ne_razresujemo(self):
        na_poti = _poti("192.168.0.20")
        naslovi = link_zvok.lastni_naslovi("wss://link.example.org/r/abc", lambda: [("eth0", "192.168.0.20", UP)], na_poti)
        self.assertEqual(naslovi, ["192.168.0.20"])
        for cilj in na_poti.klici:
            socket.inet_aton(cilj)                     # samo stevilcni cilji - nobene poizvedbe DNS

    def test_neveljaven_naslov_huba(self):
        for hub in ("", "ni-naslov", "wss://[::1]:8990/cast/ws", "wss://1.2.3/x", None):
            naslovi = link_zvok.lastni_naslovi(hub, lambda: [("eth0", "192.168.0.20", UP)], _poti("192.168.0.20"))
            self.assertEqual(naslovi, ["192.168.0.20"], hub)


class PraviRacunalnik(unittest.TestCase):
    def test_vmesniki_tega_racunalnika(self):
        vmesniki = link_zvok.naslovi_vmesnikov()
        self.assertIsInstance(vmesniki, list)
        for ime, naslov, zastavice in vmesniki:
            self.assertIsInstance(ime, str)
            socket.inet_aton(naslov)
            self.assertIsInstance(zastavice, int)
        if any(ime == "lo" for ime, _n, _z in vmesniki):
            zanka = next(z for ime, _n, z in vmesniki if ime == "lo")
            self.assertTrue(zanka & ZANKA)

    def test_nasteti_naslovi(self):
        naslovi = link_zvok.lastni_naslovi(HUB_TU)
        self.assertLessEqual(len(naslovi), link_zvok.NAJVEC_NASLOVOV)
        self.assertEqual(len(naslovi), len(set(naslovi)))
        for n in naslovi:
            socket.inet_aton(n)
            self.assertFalse(n.startswith("127."), n)
        # Kar jedro izbere za privzeto pot, mora biti med nastetimi (ce omrezje je).
        privzeti = link_zvok.naslov_na_poti("192.0.2.1")
        if privzeti and not privzeti.startswith("127."):
            self.assertIn(privzeti, naslovi)


if __name__ == "__main__":
    unittest.main()
