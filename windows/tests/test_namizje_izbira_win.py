"""Lastnik 27. 10. 2026: na Windows je Safeer OS namizje (videz kot na Linuxu) ali prvotno namizje Windows - domacega
okna v starem videzu ni vec. Izbira prvotnega namizja Windows je vedno mogoca in se zapomni; ikona Safeer OS vedno
odpre namizje Safeer; sesutja in napaka QML izklopijo namizje samo do konca zagona.
"""
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

KOREN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KOREN))
sys.path.insert(0, str(KOREN / "windows"))

WIN = KOREN / "windows" / "safeer_windows"
IZVOR = (WIN / "os_app.py").read_text(encoding="utf-8")

try:
    from safeer_windows import os_app  # noqa: E402
except Exception as e:  # noqa: BLE001 - brez PySide6 ostanejo preverbe izvora
    os_app = None
    RAZLOG = str(e)


def telo(ime: str) -> str:
    return IZVOR.split(f"def {ime}", 1)[1].split("\n    def ", 1)[0]


@unittest.skipIf(os_app is None, "os_app se ne uvozi (PySide6)")
class IzbiraNamizja(unittest.TestCase):
    def setUp(self):
        self.shramba = {}
        self.okno = types.SimpleNamespace(dispatcher=types.SimpleNamespace(dispatch=lambda f: None),
                                          _skrij_namizje=lambda: None)
        W = os_app.SafeerOsWindow
        for ime in ("namizje_vklopljeno", "shrani_izbiro_namizja", "izklopi_namizje_do_konca"):
            setattr(self.okno, ime, getattr(W, ime).__get__(self.okno))
        self.okno.KLJUC_NAMIZJA = W.KLJUC_NAMIZJA
        p = mock.patch.multiple(os_app.os_backend_win, nalozi_shrambo=lambda: dict(self.shramba),
                                shrani_shrambo=lambda s: self.shramba.update(s))
        p.start(); self.addCleanup(p.stop)
        q = mock.patch.object(os_app.sys, "platform", "win32")
        q.start(); self.addCleanup(q.stop)

    def test_privzeto_namizje_safeer(self):
        self.assertTrue(self.okno.namizje_vklopljeno())

    def test_stari_zapis_namizje_false_ne_vrne_starega_videza(self):
        self.shramba["namizje"] = False          # tako je bilo pri lastniku pred 1.0.52
        self.assertTrue(self.okno.namizje_vklopljeno())

    def test_prvotno_namizje_windows_se_zapomni(self):
        self.okno.shrani_izbiro_namizja(False)
        self.assertEqual(self.shramba[os_app.SafeerOsWindow.KLJUC_NAMIZJA], "windows")
        self.assertFalse(self.okno.namizje_vklopljeno())
        self.okno.shrani_izbiro_namizja(True)
        self.assertTrue(self.okno.namizje_vklopljeno())

    def test_varnostna_vrata_samo_do_konca_zagona(self):
        self.okno.izklopi_namizje_do_konca()
        self.assertFalse(self.okno.namizje_vklopljeno())
        self.assertNotIn(os_app.SafeerOsWindow.KLJUC_NAMIZJA, self.shramba)   # izbira ostane namizje Safeer


class IzvorNamizja(unittest.TestCase):
    def test_sesutja_in_qml_ne_spremenita_izbire(self):
        self.assertIn("self.izklopi_namizje_do_konca()", telo("pokazi_namizje"))
        self.assertIn("self.izklopi_namizje_do_konca()", telo("zacni_namizje_ob_zagonu"))
        self.assertNotIn("self.nastavi_namizje(False)", telo("pokazi_namizje") + telo("zacni_namizje_ob_zagonu"))

    def test_ikona_odpre_namizje_ne_starega_okna(self):
        p = telo("prebudi")
        self.assertIn("if not razdelek and sys.platform == \"win32\"", p)
        self.assertLess(p.index("self.nastavi_namizje(True)"), p.index("self.showMaximized()"))

    def test_zagon_z_ikono_izbere_namizje_safeer(self):
        m = IZVOR.split("def main(", 1)[1]
        self.assertIn("elif not predvajalnik and not (args.ozadje or args.razdelek or args.control or magnet or args.okno):"
                      "\n        # Lastnik 27. 10. 2026", m)
        self.assertIn("window.shrani_izbiro_namizja(True)", m)

    def test_stari_kljuc_se_ne_bere(self):
        self.assertNotIn('.get("namizje", False)', IZVOR)


if __name__ == "__main__":
    unittest.main()
