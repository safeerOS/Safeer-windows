"""core/platforma.py: tanek most Linux / Windows (skupni vmesnik, 25. 10. 2026).

Obe veji vsake funkcije se preizkusita na Linuxu: veja Windows z laznim subprocess in os.startfile (brez pravih
programov), veja Linux z laznim jedrom (os_sistem, os_scit, varuh procesov). Ista datoteka je v Safeer-linux in
Safeer-windows (skupna-koda.json).
"""
import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

from core import platforma


class Zapis:
    """Lazen subprocess.Popen / subprocess.run: zapise ukaze, ne zazene nicesar."""

    def __init__(self, koda=0, izpis=""):
        self.ukazi = []
        self.koda, self.izpis = koda, izpis

    def popen(self, ukaz, **kw):
        self.ukazi.append((list(ukaz), kw))
        return mock.Mock(pid=4242)

    def run(self, ukaz, **kw):
        self.ukazi.append((list(ukaz), kw))
        koda = self.koda(ukaz) if callable(self.koda) else self.koda
        return subprocess.CompletedProcess(ukaz, koda, self.izpis, "")


class Ime(unittest.TestCase):
    def test_ime_in_konstanta(self):
        self.assertEqual(platforma.IME, "windows" if sys.platform == "win32" else "linux")
        self.assertEqual(platforma.JE_WINDOWS, sys.platform == "win32")
        self.assertEqual(platforma.ime(windows=True), "windows")
        self.assertEqual(platforma.ime(windows=False), "linux")


class Poti(unittest.TestCase):
    def test_linux_xdg_kot_do_zdaj(self):
        o = {"XDG_CONFIG_HOME": "/n", "XDG_DATA_HOME": "/p", "XDG_CACHE_HOME": "/c"}
        self.assertEqual(platforma.mapa_nastavitev(False, o), os.path.join("/n", "safeer-os"))
        self.assertEqual(platforma.mapa_podatkov(False, o), os.path.join("/p", "safeer-os"))
        self.assertEqual(platforma.mapa_predpomnilnika(False, o), os.path.join("/c", "safeer-os"))

    def test_linux_privzeto_v_domaci_mapi(self):
        self.assertEqual(platforma.mapa_nastavitev(False, {}), os.path.join(os.path.expanduser("~/.config"), "safeer-os"))
        self.assertEqual(platforma.mapa_podatkov(False, {}),
                         os.path.join(os.path.expanduser("~/.local/share"), "safeer-os"))
        self.assertEqual(platforma.mapa_predpomnilnika(False, {}), os.path.join(os.path.expanduser("~/.cache"), "safeer-os"))

    def test_linux_enako_kot_obstojeci_moduli(self):
        # Iste mape kot moduli, ki jih bodo klicali (podatki uporabnika se ne premaknejo).
        from core import os_programi
        self.assertEqual(platforma.mapa_nastavitev(False), os_programi.MAPA_NASTAVITEV)

    def test_windows_appdata(self):
        o = {"APPDATA": r"C:\U\R", "LOCALAPPDATA": r"C:\U\L"}
        self.assertEqual(platforma.mapa_nastavitev(True, o), os.path.join(r"C:\U\R", "SafeerOS"))
        self.assertEqual(platforma.mapa_podatkov(True, o), os.path.join(r"C:\U\L", "SafeerOS"))
        self.assertEqual(platforma.mapa_predpomnilnika(True, o), os.path.join(r"C:\U\L", "SafeerOS"))

    def test_windows_brez_appdata_kot_os_backend_win(self):
        # os_backend_win.CONFIG_DIR: APPDATA, sicer XDG_CONFIG_HOME, sicer ~/.config (preizkusi Windows kode na Linuxu).
        self.assertEqual(platforma.mapa_nastavitev(True, {"XDG_CONFIG_HOME": "/x"}), os.path.join("/x", "SafeerOS"))
        self.assertEqual(platforma.mapa_podatkov(True, {}), os.path.join(os.path.expanduser("~"), "SafeerOS"))


class PokaziVMapi(unittest.TestCase):
    def setUp(self):
        self.mapa = tempfile.mkdtemp()
        self.dat = os.path.join(self.mapa, "a b.txt")
        open(self.dat, "w").close()

    def tearDown(self):
        os.unlink(self.dat)
        os.rmdir(self.mapa)

    def test_windows_raziskovalec_z_oznako(self):
        z = Zapis()
        with mock.patch("subprocess.Popen", z.popen):
            self.assertTrue(platforma.pokazi_v_mapi(self.dat, windows=True))
        self.assertEqual(z.ukazi[0][0], ["explorer.exe", "/select," + os.path.abspath(self.dat)])
        self.assertTrue(z.ukazi[0][1].get("close_fds"))

    def test_neobstojeca_pot_nic_ne_zazene(self):
        z = Zapis()
        with mock.patch("subprocess.Popen", z.popen):
            self.assertFalse(platforma.pokazi_v_mapi(self.dat + ".ni", windows=True))
            self.assertFalse(platforma.pokazi_v_mapi("", windows=False))
            self.assertFalse(platforma.pokazi_v_mapi("  ", windows=True))      # ne trenutna mapa (abspath(""))
        self.assertEqual(z.ukazi, [])

    def test_linux_nemo_prek_varuha_s_cistim_okoljem(self):
        from core import varuh_procesov, zasebni_webkit
        z = Zapis()
        with mock.patch("shutil.which", return_value="/usr/bin/nemo"), \
                mock.patch.object(zasebni_webkit, "okolje_za_zunanje", return_value={"CISTO": "1"}), \
                mock.patch.object(varuh_procesov, "zazeni_program", return_value=0) as mz, \
                mock.patch("subprocess.Popen", z.popen):
            self.assertTrue(platforma.pokazi_v_mapi(self.dat, windows=False))
        mz.assert_called_once_with(["nemo", os.path.abspath(self.dat)], {"CISTO": "1"})
        # varuh ni vrnil procesa -> rezerva Popen v novi seji, z istim cistim okoljem
        self.assertEqual(z.ukazi[0][0], ["nemo", os.path.abspath(self.dat)])
        self.assertEqual(z.ukazi[0][1]["env"], {"CISTO": "1"})
        self.assertTrue(z.ukazi[0][1]["start_new_session"])

    def test_linux_brez_nema(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(platforma.pokazi_v_mapi(self.dat, windows=False))

    def test_os_datoteke_gre_prek_platforme(self):
        from core import os_datoteke
        with mock.patch.object(platforma, "pokazi_v_mapi", return_value=True) as m:
            self.assertTrue(os_datoteke.pokazi_v_mapi("/x"))
        m.assert_called_once_with("/x")


class Zagon(unittest.TestCase):
    def test_windows_startfile(self):
        klici = []
        with mock.patch.object(os, "startfile", klici.append, create=True):
            self.assertTrue(platforma.zazeni_program(r"C:\P\x.lnk", windows=True))
        self.assertEqual(klici, [r"C:\P\x.lnk"])

    def test_windows_napaka_startfile(self):
        def napaka(_):
            raise OSError("ni")
        with mock.patch.object(os, "startfile", napaka, create=True):
            self.assertFalse(platforma.zazeni_program("x", windows=True))

    def test_linux_desktop_gio_launch(self):
        with mock.patch("shutil.which", return_value="/usr/bin/gio"), \
                mock.patch.object(platforma, "zazeni_locen", return_value=True) as m:
            self.assertTrue(platforma.zazeni_program("/u/a.desktop", windows=False))
        m.assert_called_once_with(["gio", "launch", "/u/a.desktop"], windows=False)

    def test_prazno(self):
        self.assertFalse(platforma.zazeni_program("", windows=True))
        self.assertFalse(platforma.zazeni_locen([], windows=False))


class Nastavitve(unittest.TestCase):
    def test_windows_ms_settings_in_orodja(self):
        z, odprto = Zapis(), []
        with mock.patch("subprocess.Popen", z.popen), mock.patch.object(os, "startfile", odprto.append, create=True):
            self.assertTrue(platforma.odpri_nastavitve("sound", windows=True))
            self.assertTrue(platforma.odpri_nastavitve("neznano", windows=True))
            self.assertTrue(platforma.odpri_nastavitve("screensaver", windows=True))
            self.assertTrue(platforma.odpri_nastavitve("opravila", windows=True))
            self.assertTrue(platforma.odpri_nastavitve("diski", windows=True))
        self.assertEqual(odprto, ["ms-settings:sound", "ms-settings:", "diskmgmt.msc"])
        self.assertEqual([u for u, _ in z.ukazi], [["control.exe", "desk.cpl,,1"], ["taskmgr.exe"]])

    def test_windows_moduli_imajo_stran(self):
        r = platforma.razpolozljive_nastavitve(windows=True)
        for kljuc in r["moduli"] + r["orodja"]:
            self.assertIn(kljuc, platforma.NASTAVITVE_WINDOWS)

    def test_linux_gre_v_os_sistem(self):
        from core import os_sistem
        with mock.patch.object(os_sistem, "odpri_nastavitve", return_value=True) as m, \
                mock.patch.object(os_sistem, "napajanje", return_value=True) as n:
            self.assertTrue(platforma.odpri_nastavitve("sound", windows=False))
            self.assertTrue(platforma.napajanje("Zakleni", windows=False))
        m.assert_called_once_with("sound")
        n.assert_called_once_with("zakleni")

    def test_windows_napajanje(self):
        z = Zapis()
        with mock.patch("subprocess.Popen", z.popen):
            self.assertTrue(platforma.napajanje("zakleni", windows=True))
            self.assertTrue(platforma.napajanje("ponovni-zagon", windows=True))
            self.assertFalse(platforma.napajanje("format c:", windows=True))
        self.assertEqual([u for u, _ in z.ukazi], [["rundll32.exe", "user32.dll,LockWorkStation"],
                                                   ["shutdown.exe", "/r", "/t", "0"]])


class Bliznjice(unittest.TestCase):
    def test_win_tab_ni_zasloni_na_windows(self):
        # Win+Tab je Pogled opravil Windows - Zasloni (Safeer Link Spaces) so tam Ctrl+Win+Tab (varnostna_vrata.py).
        self.assertEqual(platforma.bliznjice(windows=True)["zasloni"], "Ctrl+Win+Tab")
        self.assertEqual(platforma.bliznjice(windows=False)["zasloni"], "Super+Tab")
        self.assertEqual(platforma.bliznjice(windows=True)["tipka"], "Win")
        self.assertEqual(platforma.bliznjice(windows=False)["tipka"], "Super")

    def test_kopija(self):
        b = platforma.bliznjice(windows=False)
        b["zasloni"] = "x"
        self.assertEqual(platforma.bliznjice(windows=False)["zasloni"], "Super+Tab")


class Zvok(unittest.TestCase):
    def _lazen_glasnost_win(self, stanje):
        modul = types.ModuleType("safeer_windows.glasnost_win")
        modul.stanje = lambda: stanje
        modul.klici = []
        modul.nastavi = lambda smer="", raven=None: modul.klici.append((smer, raven)) or stanje
        paket = types.ModuleType("safeer_windows")
        paket.glasnost_win = modul
        return mock.patch.dict(sys.modules, {"safeer_windows": paket, "safeer_windows.glasnost_win": modul}), modul

    def test_windows_ista_oblika_kot_linux(self):
        zamenjava, _ = self._lazen_glasnost_win({"level": 37, "muted": True})
        with zamenjava:
            self.assertEqual(platforma.zvok(windows=True), {"glasnost": 37, "utisan": True})

    def test_windows_brez_naprave(self):
        zamenjava, _ = self._lazen_glasnost_win(None)
        with zamenjava:
            self.assertIsNone(platforma.zvok(windows=True))

    def test_windows_nastavi(self):
        zamenjava, modul = self._lazen_glasnost_win({"level": 10, "muted": False})
        with zamenjava:
            self.assertTrue(platforma.nastavi_glasnost(140, windows=True))
            self.assertTrue(platforma.preklopi_utisaj(windows=True))
        self.assertEqual(modul.klici, [("", 100), ("toggle_mute", None)])

    def test_linux_os_sistem(self):
        from core import os_sistem
        with mock.patch.object(os_sistem, "zvok", return_value={"glasnost": 5, "utisan": False}):
            self.assertEqual(platforma.zvok(windows=False), {"glasnost": 5, "utisan": False})


class DnsScita(unittest.TestCase):
    def test_windows_ime_vmesnika_v_narekovajih(self):
        # Ime vmesnika gre v PowerShell kot niz: ' se podvoji, ; in $() ne postaneta ukaz.
        z = Zapis()
        with mock.patch("subprocess.run", z.run):
            self.assertTrue(platforma.dns_usmeri("Wi'Fi; Remove-Item $(x)", 53, ["192.168.1.1", "ni-ip", "127.0.0.1"],
                                                 windows=True))
        ukaz = z.ukazi[0][0]
        self.assertEqual(ukaz[:4], ["powershell", "-NoProfile", "-NonInteractive", "-Command"])
        self.assertEqual(ukaz[4], "Set-DnsClientServerAddress -InterfaceAlias 'Wi''Fi; Remove-Item $(x)' "
                                  "-ServerAddresses @('127.0.0.1', '192.168.1.1')")
        self.assertEqual(z.ukazi[0][1]["creationflags"], platforma.CREATE_NO_WINDOW)

    def test_windows_rezerva_netsh(self):
        z = Zapis(koda=lambda u: 1 if u[0] == "powershell" else 0)
        with mock.patch("subprocess.run", z.run):
            self.assertTrue(platforma.dns_usmeri("Ethernet", 53, None, windows=True))
            self.assertTrue(platforma.dns_povrni("Ethernet", windows=True))
        self.assertEqual(z.ukazi[1][0], ["netsh", "interface", "ip", "set", "dns", "name=Ethernet", "static", "127.0.0.1"])
        self.assertEqual(z.ukazi[3][0], ["netsh", "interface", "ip", "set", "dns", "name=Ethernet", "dhcp"])

    def test_windows_neveljavno_ime(self):
        z = Zapis()
        with mock.patch("subprocess.run", z.run):
            self.assertFalse(platforma.dns_usmeri("a\nb", 53, None, windows=True))
            self.assertFalse(platforma.dns_povrni("", windows=True))
            self.assertEqual(platforma.dns_vmesnika("x" * 300, windows=True), "")
        self.assertEqual(z.ukazi, [])

    def test_windows_vmesniki_in_strezniki(self):
        z = Zapis(izpis="Ethernet\r\nWi-Fi\r\nEthernet\r\n")
        with mock.patch("subprocess.run", z.run):
            self.assertEqual(platforma.dns_vmesniki(windows=True), ["Ethernet", "Wi-Fi"])
        z = Zapis(izpis="127.0.0.1\r\n192.168.1.1\r\n")
        with mock.patch("subprocess.run", z.run):
            self.assertEqual(platforma.dns_vmesnika("Ethernet", windows=True), "127.0.0.1 192.168.1.1")
        z = Zapis(koda=1)
        with mock.patch("subprocess.run", z.run):
            self.assertEqual(platforma.dns_vmesniki(windows=True), ["Ethernet", "Wi-Fi"])   # rezerva kot prej

    def test_linux_gre_v_os_scit(self):
        lazen = types.SimpleNamespace(vmesniki_povezani=lambda: ["eth0"], dns_vmesnika=lambda v: "127.0.0.1:5353",
                                      usmeri=mock.Mock(return_value=True), povrni=mock.Mock(return_value=True))
        with mock.patch.dict(sys.modules, {"core.os_scit": lazen}), mock.patch("core.os_scit", lazen, create=True):
            self.assertEqual(platforma.dns_vmesniki(windows=False), ["eth0"])
            self.assertEqual(platforma.dns_vmesnika("eth0", windows=False), "127.0.0.1:5353")
            self.assertTrue(platforma.dns_usmeri("eth0", 5353, ["10.0.0.1"], windows=False))
            self.assertTrue(platforma.dns_povrni("eth0", windows=False))
        lazen.usmeri.assert_called_once_with("eth0", 5353, ["10.0.0.1"])
        lazen.povrni.assert_called_once_with("eth0")


class Diski(unittest.TestCase):
    def test_windows_priklop_ni_podprt(self):
        self.assertEqual(platforma.priklopi_disk("C:", windows=True), {"ok": False, "napaka": "ni_podprto"})

    def test_diski_iz_sistem_podatki(self):
        from core import sistem_podatki
        with mock.patch.object(sistem_podatki, "diski", return_value=[{"ime": "x"}]):
            self.assertEqual(platforma.diski(), [{"ime": "x"}])


if __name__ == "__main__":
    unittest.main()
