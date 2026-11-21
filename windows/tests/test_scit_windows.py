"""Scit na Windows: prestrezanje DNS po pravilih Linuxa (lastnik 4. 11. 2026). Porocilo 4. 11. 2026 (07:40): tuj
rezervni razresevalnik 1.1.1.1/9.9.9.9/8.8.8.8, DNS usmerjevalnika kot drugi streznik vmesnika (obvoz Scita), IPv6
krajevni DNS izpuscen, ime vmesnika v PowerShell brez ubeznice, vrata 5354-5357 na Windows ne delujejo.

Preizkusi s pravim PowerShellom in pravimi vticnicami tecejo samo na Windows in NE spreminjajo DNS ali nastavitev
(samo branje in -WhatIf). Vsak varnostni popravek ima preizkus, ki brez popravka pade."""
import base64
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core import os_scit  # noqa: E402

NA_WINDOWS = sys.platform == "win32"


class Shramba(dict):
    def get(self, k, d=None):
        return dict.get(self, k, d)

    def set(self, k, v):
        self[k] = v


def poizvedba(ime: str, ident: bytes = b"\x12\x34") -> bytes:
    telo = b"".join(bytes([len(d)]) + d.encode() for d in ime.split(".") if d) + b"\x00"
    return ident + b"\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00" + telo + b"\x00\x01\x00\x01"


def prosta_vrata() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as u:
        u.bind(("127.0.0.1", 0))
        return u.getsockname()[1]


def vmesnik(ime="Ethernet", v4=(), v6=(), dhcp=(), staticni=(), indeks=7):
    return {"ime": ime, "indeks": indeks, "v4": list(v4), "v6": list(v6), "dhcp": list(dhcp), "staticni": list(staticni)}


class Ubeznica(unittest.TestCase):
    IMENA = ("Ethernet", "Wi-Fi 2", "Povezava ž", "x' ; Write-Output VDOR ; '", "a\u2019; Write-Output VDOR; \u2019b",
             "c\u2018\u201a\u201b'")

    def test_ps_niz_podvoji_vse_narekovaje(self):
        self.assertEqual(os_scit.ps_niz("a'b"), "'a''b'")
        self.assertEqual(os_scit.ps_niz("a\u2019b"), "'a\u2019\u2019b'")

    def test_usmeri_ime_vmesnika_z_ubeznico(self):
        skripte = []
        with mock.patch.object(os_scit, "_powershell", side_effect=lambda s, cas=8.0: (skripte.append(s), (0, ""))[1]):
            self.assertEqual(os_scit.usmeri("x' ; Write-Output VDOR ; '", True), "ok")
        self.assertIn("-InterfaceAlias 'x'' ; Write-Output VDOR ; '''", skripte[0])

    def test_neveljavno_ime_se_ne_uporabi(self):
        with mock.patch.object(os_scit, "_powershell") as ps:
            self.assertEqual(os_scit.usmeri("a\nb", True), "")
            self.assertFalse(os_scit.povrni("", []))
        ps.assert_not_called()

    @unittest.skipUnless(NA_WINDOWS, "pravi PowerShell samo na Windows")
    def test_pravi_powershell_vrne_ime_nespremenjeno(self):
        # Brez ubeznice bi ime z narekovajem koncalo niz in »Write-Output VDOR« bi se izvedel kot ukaz.
        for ime in self.IMENA:
            with self.subTest(ime):
                koda, izpis = os_scit._powershell("Write-Output " + os_scit.ps_niz(ime))
                self.assertEqual(koda, 0)
                self.assertEqual(izpis.strip("\r\n"), ime)


class SamoScit(unittest.TestCase):
    """Vmesnik dobi samo Scit; DNS usmerjevalnika ni drugi streznik; nikoli tuj rezervni razresevalnik."""

    def setUp(self):
        self.mapa = tempfile.TemporaryDirectory()
        self.addCleanup(self.mapa.cleanup)
        self.skripte = []
        p = mock.patch.object(os_scit, "_powershell", side_effect=lambda s, cas=8.0: (self.skripte.append(s), (0, ""))[1])
        p.start()
        self.addCleanup(p.stop)
        p2 = mock.patch.object(os_scit, "zazeni_strazo_padca", return_value=None)
        p2.start()
        self.addCleanup(p2.stop)

    def _scit(self, stanje, z6=True):
        sc = os_scit.Scit(Shramba(), mapa=self.mapa.name)
        r = os_scit.RazresevalnikWin(sc._kategorija, lambda: sc.strezniki, sc._naprej, zagonsko=sc._zagonsko)
        r.vrata = 53
        r._udp6 = mock.Mock() if z6 else None
        sc.razresevalnik = r
        self.stanje = stanje
        p = mock.patch.object(os_scit, "beri_vmesnike", side_effect=lambda: self.stanje)
        p.start()
        self.addCleanup(p.stop)
        return sc

    def test_usmerjevalnik_ni_drugi_streznik(self):
        sc = self._scit([vmesnik(v4=["192.0.2.1"], dhcp=["192.0.2.1"])])
        sc._uporabi()
        usmeri = [s for s in self.skripte if "-ServerAddresses" in s]
        self.assertEqual(len(usmeri), 1)
        self.assertIn("-ServerAddresses @('127.0.0.1', '::1')", usmeri[0])
        self.assertNotIn("192.0.2.1", usmeri[0])
        self.assertEqual(sc.strezniki, ["192.0.2.1"])       # naprej gre krajevni DNS - prek Scita
        self.assertEqual(sc.vmesniki, ["Ethernet"])

    def test_brez_krajevnega_dns_ni_tujega(self):
        sc = self._scit([vmesnik(v4=["127.0.0.1"], v6=["::1"])])
        sc._uporabi()
        self.assertEqual(sc.strezniki, [])
        self.assertEqual(sc.napaka, "ni_krajevnega")

    def test_ostanek_starega_scita_s_tujimi_rezervami(self):
        # Do 1.0.153 je Scit za 127.0.0.1 vpisal 1.1.1.1, 9.9.9.9, 8.8.8.8: to ni krajevni DNS.
        sc = self._scit([vmesnik(v4=["127.0.0.1", "1.1.1.1", "9.9.9.9", "8.8.8.8"])])
        sc._uporabi()
        self.assertEqual(sc.strezniki, [])
        sc = self._scit([vmesnik(v4=["127.0.0.1", "192.0.2.1"], dhcp=["192.0.2.1"])])
        sc._uporabi()
        self.assertEqual(sc.strezniki, ["192.0.2.1"])
        self.assertEqual(sc._spomin(), {})                   # stara rezerva ni »rocni DNS uporabnika«

    def test_ipv6_krajevni_dns_s_kazalom_vmesnika(self):
        sc = self._scit([vmesnik(v4=["192.0.2.1"], v6=["fe80::1", "2001:db8::53"], indeks=7)])
        sc._uporabi()
        self.assertEqual(sc.strezniki, ["192.0.2.1", "fe80::1%7", "2001:db8::53"])

    def test_dhcp6_iz_registra(self):
        self.assertEqual(os_scit._dhcp6("20010db8000000000000000000000053fe800000000000000000000000000001"),
                         ["2001:db8::53", "fe80::1"])

    def test_spomin_rocnega_dns_in_povrnitev(self):
        sc = self._scit([vmesnik(v4=["192.0.2.2"], staticni=["192.0.2.2"])])
        sc._uporabi()
        self.assertEqual(sc._spomin()["Ethernet"]["staticni"], ["192.0.2.2"])
        self.stanje = [vmesnik(v4=["127.0.0.1"], v6=["::1"], dhcp=["192.0.2.1"])]
        sc._uporabi()
        self.assertEqual(sc.strezniki, ["192.0.2.2"])         # rocni DNS uporabnika ima prednost pred DHCP
        self.skripte.clear()
        sc._ustavi()
        povrnitev = [s for s in self.skripte if "-ResetServerAddresses" in s]
        self.assertEqual(len(povrnitev), 1)
        self.assertIn("-ResetServerAddresses -ErrorAction Stop; Set-DnsClientServerAddress -InterfaceAlias 'Ethernet' "
                      "-ServerAddresses @('192.0.2.2')", povrnitev[0])

    def test_ipv6_mimo_scita_se_pove(self):
        sc = self._scit([vmesnik(v4=["127.0.0.1"], v6=["2001:db8::53"])], z6=False)
        sc._uporabi()
        self.assertEqual(sc.mimo_ipv6, ["Ethernet"])
        self.assertEqual(sc.napaka, "ipv6")

    def test_brez_pravic_ne_pusti_napol_vklopljenega(self):
        sc = self._scit([vmesnik(v4=["192.0.2.1"])])
        with mock.patch.object(os_scit, "usmeri", return_value=""):
            sc._uporabi()
        self.assertEqual(sc.vmesniki, [])
        self.assertEqual(sc.napaka, "pravice")

    def test_branje_ne_uspe_nic_ne_spremeni(self):
        sc = self._scit(None)
        sc._uporabi()
        self.assertEqual([s for s in self.skripte if "-ServerAddresses" in s], [])


class Vrata(unittest.TestCase):
    def test_vrata_samo_53(self):
        self.assertEqual(os_scit.VRATA, (53,))

    def test_zasedena_vrata_scit_pove_in_se_ne_vklopi(self):
        vrata = prosta_vrata()
        zaseda = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        izkljucno = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if izkljucno is not None:
            zaseda.setsockopt(socket.SOL_SOCKET, izkljucno, 1)
        zaseda.bind(("127.0.0.1", vrata))
        self.addCleanup(zaseda.close)
        with tempfile.TemporaryDirectory() as mapa, mock.patch.object(os_scit, "VRATA", (vrata,)), \
                mock.patch("core.scit_pravila.skupna"), mock.patch.object(os_scit.Seznami, "zazeni"), \
                mock.patch.object(os_scit, "beri_vmesnike", return_value=[]):
            shramba = Shramba()
            sc = os_scit.Scit(shramba, mapa=mapa)
            st = sc.nastavi(True)
            self.assertEqual(st["napaka"], "vrata")
            self.assertFalse(st["tece"])
            self.assertNotIn("scit", shramba)

    def test_vrata_samo_zase(self):
        # Na Windows SO_REUSEADDR dovoli drugemu programu, da se veze na ista vrata in prestreza poizvedbe.
        vrata = prosta_vrata()
        r = os_scit.RazresevalnikWin(lambda _i: None, lambda: [])
        with mock.patch.object(os_scit, "VRATA", (vrata,)):
            self.assertEqual(r.zazeni(), vrata)
        self.addCleanup(r.ustavi)
        if not NA_WINDOWS:
            self.skipTest("SO_EXCLUSIVEADDRUSE je samo na Windows")
        for vrsta in (socket.SOCK_DGRAM, socket.SOCK_STREAM):
            with self.subTest(vrsta=vrsta), socket.socket(socket.AF_INET, vrsta) as vsiljivec:
                vsiljivec.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                with self.assertRaises(OSError):
                    vsiljivec.bind(("127.0.0.1", vrata))


class PraviRazresevalnik(unittest.TestCase):
    """Prave vticnice: 127.0.0.1 in ::1, kanarcek, ustavljeno ime, SERVFAIL takoj brez krajevnega DNS."""

    def setUp(self):
        self.vrata = prosta_vrata()
        self.r = os_scit.RazresevalnikWin(lambda ime: "oglasi" if ime == "ads.example" else None, lambda: [],
                                          lambda _p: None)
        self.r.sifrirano_naprej = lambda: False
        with mock.patch.object(os_scit, "VRATA", (self.vrata,)):
            if self.r.zazeni() != self.vrata:
                self.skipTest("vrata niso prosta")
        self.addCleanup(self.r.ustavi)

    def _vprasaj(self, naslov, druzina, ime):
        with socket.socket(druzina, socket.SOCK_DGRAM) as u:
            u.settimeout(2.0)
            u.sendto(poizvedba(ime), (naslov, self.vrata))
            return u.recv(4096)

    def test_odgovori(self):
        druzine = [("127.0.0.1", socket.AF_INET)] + ([("::1", socket.AF_INET6)] if self.r.ima_ipv6() else [])
        for naslov, druzina in druzine:
            with self.subTest(naslov):
                self.assertEqual(self._vprasaj(naslov, druzina, os_scit.KANAREK_DOH)[3] & 0x0F, 3)
                self.assertEqual(self._vprasaj(naslov, druzina, "ads.example")[3] & 0x0F, 3)
                zacetek = time.monotonic()
                self.assertEqual(self._vprasaj(naslov, druzina, "a.example")[3] & 0x0F, 2)   # SERVFAIL
                self.assertLess(time.monotonic() - zacetek, 0.5)                             # takoj, ne molk
        self.assertTrue(os_scit._odgovori_kanarcku(self.vrata, 1.0))


class StrazaObPadcu(unittest.TestCase):
    def test_skripta(self):
        s = os_scit.skripta_straze_padca(4321, [("Wi-Fi 'x'", ["192.0.2.2"])])
        self.assertIn("Get-Process -Id 4321", s)
        self.assertIn("WaitForExit()", s)
        self.assertIn("-InterfaceAlias 'Wi-Fi ''x''' -AddressFamily IPv4).ServerAddresses) -contains '127.0.0.1'", s)
        self.assertIn("-ResetServerAddresses; Set-DnsClientServerAddress -InterfaceAlias 'Wi-Fi ''x''' "
                      "-ServerAddresses @('192.0.2.2')", s)
        self.assertNotIn("-ErrorAction Stop", s)
        self.assertNotIn("Clear-DnsClientCache", os_scit.skripta_straze_padca(1, []))

    @unittest.skipUnless(NA_WINDOWS, "pravi proces samo na Windows")
    def test_straza_konca_s_procesom_in_ob_izklopu(self):
        # Brez vmesnikov: straza se ne dotakne DNS, preverimo samo, da ne ostane visela.
        otrok = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"],
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        straza = os_scit.zazeni_strazo_padca(otrok.pid, [])
        self.assertIsNotNone(straza)
        try:
            otrok.wait(timeout=20)
            self.assertIsNotNone(straza.wait(timeout=30))
        finally:
            for p in (otrok, straza):
                if p.poll() is None:
                    p.kill()
                    p.wait(timeout=10)
        sc = os_scit.Scit(Shramba(), mapa=tempfile.gettempdir())
        sc._straza_padca = os_scit.zazeni_strazo_padca(os.getpid(), [])
        p = sc._straza_padca
        sc._ustavi_strazo_padca()
        self.assertIsNotNone(p.poll())


class PowerShell(unittest.TestCase):
    def test_absolutna_pot_in_kodiran_ukaz(self):
        klici = []

        def run(argv, **kw):
            klici.append((argv, kw))
            return subprocess.CompletedProcess(argv, 0, b"ok", b"")
        with mock.patch.object(os_scit.sys, "platform", "win32"), mock.patch.dict(os.environ, {"SystemRoot": "C:\\Windows"}), \
                mock.patch.object(os_scit.subprocess, "run", side_effect=run):
            self.assertEqual(os_scit._powershell("Write-Output 1"), (0, "ok"))
        argv, kw = klici[0]
        self.assertEqual(argv[0], "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe")
        self.assertEqual(argv[-2], "-EncodedCommand")
        self.assertTrue(base64.b64decode(argv[-1]).decode("utf-16-le").endswith("Write-Output 1"))
        self.assertEqual(kw.get("creationflags"), os_scit._BREZ_OKNA)

    def test_razcleni_vmesnike(self):
        izpis = ('opozorilo\nSAFEER-VMESNIKI [{"ime":"Povezava \\u017e","indeks":12,"v4":["192.0.2.1"],"v6":null,'
                 '"dhcp4":"192.0.2.1 192.0.2.9","staticni4":"","dhcp6":"fe800000000000000000000000000001",'
                 '"staticni6":""},{"ime":"slabo\\u0007","indeks":1,"v4":[],"v6":[]}]')
        v = os_scit.razcleni_vmesnike(izpis)
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0]["ime"], "Povezava ž")
        self.assertEqual(v[0]["v6"], [])
        self.assertEqual(v[0]["dhcp"], ["192.0.2.1", "192.0.2.9", "fe80::1%12"])
        self.assertIsNone(os_scit.razcleni_vmesnike("brez oznake"))
        one = os_scit.razcleni_vmesnike('SAFEER-VMESNIKI {"ime":"E","indeks":3,"v4":"127.0.0.1","v6":[]}')
        self.assertEqual(one[0]["v4"], ["127.0.0.1"])

    @unittest.skipUnless(NA_WINDOWS, "pravi PowerShell samo na Windows")
    def test_pravo_branje_in_whatif(self):
        # Samo branje in -WhatIf: DNS testnega racunalnika ostane, kot je.
        vmesniki = os_scit.beri_vmesnike()
        self.assertIsNotNone(vmesniki)
        for v in vmesniki[:2]:
            with self.subTest(v["ime"]):
                for ukaz in (os_scit._ukaz_usmeri(v["ime"], [os_scit.NASLOV, os_scit.NASLOV6]),
                             os_scit._ukaz_povrni(v["ime"], ["192.0.2.2"])):
                    koda, izpis = os_scit._powershell(ukaz.replace("-ErrorAction Stop", "-ErrorAction Stop -WhatIf"))
                    self.assertEqual(koda, 0, izpis)


class Naprej(unittest.TestCase):
    def test_privzeto_krajevni_in_izbira_ostane(self):
        sc = os_scit.Scit(Shramba(), mapa=tempfile.gettempdir())
        self.assertEqual(sc.naprej(), ("router", ""))
        self.assertFalse(sc.stanje()["naprejIzbran"])
        sc.nastavi_naprej("quad9")
        self.assertEqual(sc.naprej()[0], "quad9")
        self.assertTrue(sc.stanje()["naprejIzbran"])
        self.assertTrue(sc._zagonsko("dns.quad9.net"))      # ime streznika DoH gre krajevnemu DNS, ne v zanko

    def test_zanka_na_scit_zavrnjena(self):
        sc = os_scit.Scit(Shramba(), mapa=tempfile.gettempdir())
        self.assertEqual(sc.nastavi_naprej("custom", "127.0.0.1")["napaka"], "naprej_zanka")
        self.assertEqual(sc.nastavi_naprej("custom", "http://x.example/dns-query")["napaka"], "naprej")
        self.assertEqual(sc.nastavi_naprej("custom", "192.0.2.53")["napaka"], "")

    def test_doh_ne_sledi_preusmeritvi(self):
        self.assertIsNone(os_scit._BrezPreusmeritev().redirect_request(None, None, 302, "", {}, "https://drugam.example"))
        self.assertIsNone(os_scit.doh_paket("http://1.1.1.1/dns-query", poizvedba("a.example"), 1.0))


if __name__ == "__main__":
    unittest.main()
