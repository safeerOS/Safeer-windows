"""Samozagon Safeer OS za Windows (»Zaženi ob prijavi«) gre prek zaganjalnika, ne neposredno prek python.exe.

Ugotovljeno 5. 10. 2026 na testnem racunalniku: vpis v HKCU Run je bil `"<...>\\python.exe" <...>\\safeer_os_windows.py
--ozadje`. Tak zagon odpre crno konzolno okno z izpisom programa; ce ga uporabnik zapre, se zapre Safeer OS. Zagon
prek zaganjalnika (`SafeerOS.exe --ozadje`) okna ne odpre.
"""
import inspect
import sys
import types
import unittest
from unittest import mock

from safeer_windows import magnet_win, os_app, os_backend_win

ZAGANJALNIK = r"C:\Users\Ana Novak\AppData\Local\SafeerOS\SafeerOS.exe"
NOV = '"' + ZAGANJALNIK + '" --ozadje'
STAR = (r'"C:\Users\Ana Novak\AppData\Local\Python\pythoncore-3.14-64\python.exe" '
        r'"C:\Users\Ana Novak\AppData\Local\SafeerOS\app\windows\safeer_os_windows.py" --ozadje')


class _Kljuc:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Register:
    """Ponaredek modula winreg: ena vrednost v HKCU ...\\Run."""
    HKEY_CURRENT_USER = "HKCU"
    KEY_READ, KEY_SET_VALUE, REG_SZ = 1, 2, 1

    def __init__(self, vrednost=None):
        self.vrednosti = {} if vrednost is None else {"SafeerOS": vrednost}
        self.pisanj = 0

    def OpenKey(self, koren, pot, *a):
        assert koren == "HKCU" and pot == r"Software\Microsoft\Windows\CurrentVersion\Run", (koren, pot)
        return _Kljuc()

    CreateKey = OpenKey

    def QueryValueEx(self, kljuc, ime):
        if ime not in self.vrednosti:
            raise FileNotFoundError(ime)
        return self.vrednosti[ime], 1

    def SetValueEx(self, kljuc, ime, _rezervirano, vrsta, vrednost):
        self.pisanj += 1
        self.vrednosti[ime] = vrednost

    def DeleteValue(self, kljuc, ime):
        if ime not in self.vrednosti:
            raise FileNotFoundError(ime)
        del self.vrednosti[ime]


class Samozagon(unittest.TestCase):
    def _okolje(self, register, zaganjalnik=(ZAGANJALNIK,)):
        return [
            mock.patch.dict(sys.modules, {"winreg": register}),
            mock.patch.object(os_backend_win.sys, "platform", "win32"),
            mock.patch.object(magnet_win, "zaganjalnik", lambda: list(zaganjalnik)),
        ]

    def _z(self, register, zaganjalnik=(ZAGANJALNIK,)):
        zaplate = self._okolje(register, zaganjalnik)
        for z in zaplate:
            z.start()
            self.addCleanup(z.stop)

    def test_ukaz_gre_prek_zaganjalnika(self):
        self._z(_Register())
        ukaz = os_backend_win._ukaz_samozagona()
        self.assertEqual(ukaz, NOV)                           # pot s presledkom je v narekovajih
        self.assertNotIn("python", ukaz.lower())              # prej: python.exe neposredno -> konzolno okno

    def test_vklop_zapise_zaganjalnik(self):
        r = _Register()
        self._z(r)
        self.assertTrue(os_backend_win.nastavi_samozagon(True))
        self.assertEqual(r.vrednosti["SafeerOS"], NOV)
        self.assertTrue(os_backend_win.samozagon_vklopljen())
        self.assertTrue(os_backend_win.nastavi_samozagon(False))
        self.assertNotIn("SafeerOS", r.vrednosti)
        self.assertFalse(os_backend_win.samozagon_vklopljen())

    def test_brez_zaganjalnika_python_brez_konzole(self):
        # Zagon iz izvorne kode: zaganjalnika ni; magnet_win vrne pythonw.exe in skripto.
        self._z(_Register(), zaganjalnik=(r"C:\Python314\pythonw.exe", r"C:\safeer\windows\safeer_os_windows.py"))
        self.assertEqual(os_backend_win._ukaz_samozagona(),
                         r"C:\Python314\pythonw.exe C:\safeer\windows\safeer_os_windows.py --ozadje")

    def test_star_vpis_se_zamenja(self):
        r = _Register(STAR)
        self._z(r)
        self.assertTrue(os_backend_win.osvezi_samozagon())
        self.assertEqual(r.vrednosti["SafeerOS"], NOV)
        self.assertFalse(os_backend_win.osvezi_samozagon())   # drugic ni vec kaj zamenjati
        self.assertEqual(r.pisanj, 1)

    def test_izklopljen_samozagon_ostane_izklopljen(self):
        r = _Register()
        self._z(r)
        self.assertFalse(os_backend_win.osvezi_samozagon())
        self.assertEqual(r.vrednosti, {})

    def test_tuje_vrednosti_se_ne_dotakne(self):
        tuja = r'"D:\Orodja\moj-zagon.cmd" safeer'
        r = _Register(tuja)
        self._z(r)
        self.assertFalse(os_backend_win.osvezi_samozagon())
        self.assertEqual(r.vrednosti["SafeerOS"], tuja)

    def test_brez_zaganjalnika_starega_vpisa_ne_menja(self):
        # Zaganjalnika ni: nov ukaz bi bil spet Python neposredno - starega vpisa zato ne prepisujemo.
        r = _Register(STAR)
        self._z(r, zaganjalnik=(r"C:\Python314\pythonw.exe", r"C:\safeer\windows\safeer_os_windows.py"))
        self.assertFalse(os_backend_win.osvezi_samozagon())
        self.assertEqual(r.vrednosti["SafeerOS"], STAR)

    def test_zunaj_windows_nic(self):
        with mock.patch.object(os_backend_win.sys, "platform", "linux"):
            self.assertFalse(os_backend_win.osvezi_samozagon())

    def test_program_ob_zagonu_preveri_vpis(self):
        vir = inspect.getsource(os_app.main)
        self.assertIn("os_backend_win.osvezi_samozagon()", vir)
        self.assertLess(vir.index("os_backend_win.osvezi_samozagon()"), vir.index("app.exec()"))


if __name__ == "__main__":
    unittest.main()
