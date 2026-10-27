"""Lastnik 27. 10. 2026: Safeer OS 1.0.52 je vsakih 20 s za trenutek odprl okno PowerShella (straza Scita: vmesniki,
DNS, strezniki). SafeerOS.exe je zgrajen brez konzole (--windowed), zato Windows za vsak konzolni podproces brez
CREATE_NO_WINDOW odpre vidno okno. »Dokler se to pojavlja, ni za v javnost.«"""
import ast
import unittest
from pathlib import Path

KOREN = Path(__file__).resolve().parents[2]
KONZOLNI = ("powershell", "netsh", "ipconfig")


def klici_brez_zastavice(pot: Path, samo_konzolni: bool) -> list:
    drevo = ast.parse(pot.read_text(encoding="utf-8"))
    slabi = []
    for v in ast.walk(drevo):
        if not (isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute) and isinstance(v.func.value, ast.Name)
                and v.func.value.id == "subprocess" and v.func.attr in ("run", "Popen", "check_output", "call")):
            continue
        if any(k.arg == "creationflags" for k in v.keywords):
            continue
        prvi = v.args[0] if v.args else None
        besedilo = ast.unparse(prvi) if prvi is not None else ""
        if samo_konzolni and not any(k in besedilo for k in KONZOLNI):
            continue
        slabi.append(f"{pot.name}:{v.lineno}: {besedilo[:60]}")
    return slabi


class BrezOknaKonzole(unittest.TestCase):
    def test_scit_vsi_podprocesi_brez_okna(self):
        # Straza Scita tece vsakih 20 s: VSAK klic (tudi _zazeni in ukaz v spremenljivki cmd) mora biti brez okna.
        self.assertEqual(klici_brez_zastavice(KOREN / "core" / "os_scit.py", samo_konzolni=False), [])

    def test_windows_konzolni_ukazi_brez_okna(self):
        pot = KOREN / "windows" / "safeer_windows" / "os_backend_win.py"
        self.assertEqual(klici_brez_zastavice(pot, samo_konzolni=True), [])


if __name__ == "__main__":
    unittest.main()
