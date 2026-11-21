"""Atomski zapis JSON brez stalnega zacasnega imena `<pot>.tmp` (revizija 4. 11. 2026).

Dve niti, ki sta hkrati shranjevali isto datoteko, sta pisali v ISTO `<pot>.tmp`: ena je drugi datoteko odnesla
(os.replace FileNotFoundError - shramba ni shranjena) ali v cilj zapisala mesanico. Zdaj zapis_atomski.zapisi_json
(mkstemp v isti mapi, os.replace, na Windows ponovitve ob PermissionError).
"""
import glob
import json
import os
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

from safeer_windows import (control_backend, os_backend_win, policy, predvajalnik_nadaljuj, predvajalnik_nastavitve,
                            varnostna_vrata, zapiski)
from safeer_windows import zapis_atomski

MODULI = ("policy.py", "os_backend_win.py", "control_backend.py", "zapiski.py", "predvajalnik_nastavitve.py",
          "varnostna_vrata.py", "predvajalnik_nadaljuj.py")
PONOVITEV = 300


def _dve_niti(zapisi):
    """Dve niti hkrati PONOVITEV-krat poklicejo zapisi(i, n); vrne seznam napak (izjeme ali False)."""
    napake, start = [], threading.Barrier(2)

    def delo(n):
        start.wait()
        for i in range(PONOVITEV):
            try:
                if zapisi(i, n) is False:
                    napake.append("False")
            except Exception as e:  # noqa: BLE001
                napake.append(repr(e))

    niti = [threading.Thread(target=delo, args=(n,)) for n in (1, 2)]
    for t in niti:
        t.start()
    for t in niti:
        t.join(60)
    return napake


class ZapisAtomski(unittest.TestCase):
    def setUp(self):
        self._mapa = tempfile.TemporaryDirectory()
        self.mapa = self._mapa.name

    def tearDown(self):
        self._mapa.cleanup()

    def _preveri(self, pot, napake):
        self.assertEqual(napake, [])
        with open(pot, encoding="utf-8") as f:
            json.load(f)
        self.assertEqual(glob.glob(os.path.join(self.mapa, "*.tmp")) + glob.glob(os.path.join(self.mapa, ".*.tmp")), [])

    def test_skupna_funkcija_dve_niti(self):
        pot = os.path.join(self.mapa, "a.json")
        self._preveri(pot, _dve_niti(lambda i, n: zapis_atomski.zapisi_json(pot, {"n": n, "i": i, "x": "š" * 500})))

    def test_policy_settings_dve_niti(self):
        pot = os.path.join(self.mapa, "settings.json")
        a, b = policy.SettingsStore(pot), policy.SettingsStore(pot)
        self._preveri(pot, _dve_niti(lambda i, n: (a if n == 1 else b).save()))

    def test_os_backend_shramba_dve_niti(self):
        pot = os.path.join(self.mapa, "os.json")
        with mock.patch.object(os_backend_win, "CONFIG_FILE", pot), mock.patch.object(os_backend_win, "CONFIG_DIR", self.mapa):
            self._preveri(pot, _dve_niti(lambda i, n: os_backend_win.shrani_shrambo({"i": i, "n": n})))

    def test_control_backend_dve_niti(self):
        pot = os.path.join(self.mapa, "control.json")
        sebe = types.SimpleNamespace(config_pot=pot, nastavitve={"a": "b" * 300})
        self._preveri(pot, _dve_niti(lambda i, n: control_backend.SafeerControlBackend.shrani_nastavitve(sebe)))

    def test_zapiski_dve_niti(self):
        pot = os.path.join(self.mapa, "zapiski.json")
        z = zapiski.Zapiski(pot)
        self._preveri(pot, _dve_niti(lambda i, n: z._shrani({"zapiski": [{"i": i, "n": n}], "zadnji": ""})))

    def test_predvajalnik_nastavitve_dve_niti(self):
        pot = os.path.join(self.mapa, "predvajalnik.json")
        self._preveri(pot, _dve_niti(lambda i, n: predvajalnik_nastavitve.shrani(dict(predvajalnik_nastavitve.PRIVZETO), pot)))

    def test_varnostna_vrata_dve_niti(self):
        pot = os.path.join(self.mapa, "namizje-zagoni.json")
        with mock.patch.object(varnostna_vrata, "_pot", return_value=pot):
            self._preveri(pot, _dve_niti(lambda i, n: varnostna_vrata.pisi({"i": i, "n": n})))

    def test_predvajalnik_nadaljuj_dve_niti(self):
        pot = os.path.join(self.mapa, "nadaljuj.json")
        self._preveri(pot, _dve_niti(lambda i, n: predvajalnik_nadaljuj.shrani({"i": i, "n": n, "x": "y" * 400}, pot)))

    def test_brez_stalnega_imena_tmp(self):
        koren = Path(__file__).resolve().parents[1] / "safeer_windows"
        for ime in MODULI:
            with self.subTest(ime=ime):
                self.assertFalse('+ ".tmp"' in (koren / ime).read_text(encoding="utf-8"), ime + ": stalno ime <pot>.tmp")

    def test_napaka_pusti_staro_datoteko_in_pobrise_zacasno(self):
        pot = os.path.join(self.mapa, "b.json")
        zapis_atomski.zapisi_json(pot, {"staro": 1})
        with self.assertRaises(TypeError):
            zapis_atomski.zapisi_json(pot, {"ne-json": object()})
        with open(pot, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"staro": 1})
        self._preveri(pot, [])

    def test_windows_ponovi_ob_permissionerror(self):
        pot = os.path.join(self.mapa, "c.json")
        pravi = os.replace
        klici = []

        def zaseden(a, b):
            klici.append(1)
            if len(klici) < 3:
                raise PermissionError(32, "datoteko uporablja drug proces")
            return pravi(a, b)

        with mock.patch.object(zapis_atomski, "_WINDOWS", True), mock.patch.object(zapis_atomski.os, "replace", zaseden), \
                mock.patch.object(zapis_atomski, "PREMORI_PONOVITEV", (0.001,) * 5):
            zapis_atomski.zapisi_json(pot, {"ok": True})
        self.assertEqual(len(klici), 3)
        with open(pot, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"ok": True})

    def test_windows_po_ponovitvah_napaka_in_pocisceno(self):
        pot = os.path.join(self.mapa, "d.json")
        with mock.patch.object(zapis_atomski, "_WINDOWS", True), \
                mock.patch.object(zapis_atomski.os, "replace", side_effect=PermissionError(32, "zaseden")), \
                mock.patch.object(zapis_atomski, "PREMORI_PONOVITEV", (0.001,) * 5):
            with self.assertRaises(PermissionError):
                zapis_atomski.zapisi_json(pot, {"ok": True})
        self.assertFalse(os.path.exists(pot))
        self.assertEqual(os.listdir(self.mapa), [])


if __name__ == "__main__":
    unittest.main()
