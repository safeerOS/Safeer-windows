"""Izbris sporocil Safeer Chat na Windows (lastnik 23. 10. 2026, OBVEZNO; kot Linux b3c51f9 in Android).

»Izbrisi pri meni«, pri lastnem poslanem »na vseh mojih napravah« (chat.send s payload.delete napravi, ki ga je
prejela) in izbris celega pogovora; prejemnik izbrise samo prejeto sporocilo naprave, ki ga je poslala. Skupne
odlocitve so v core/sporocila/izbris_linka.py (skupna koda), tu so Windows os_sporocila, control_backend in os_app.
"""
import os
import sys
import tempfile
import threading
import types
import unittest
import uuid
from pathlib import Path

KOREN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KOREN))
sys.path.insert(0, str(KOREN / "windows"))

from core import os_sporocila  # noqa: E402
from core.sporocila import izbris_linka  # noqa: E402

TEL = "telefon-1"


class Sporocila(unittest.TestCase):
    def setUp(self):
        self.mapa = tempfile.mkdtemp()
        self.pot = Path(self.mapa) / "s.sqlite3"
        self.sp = os_sporocila.SporocilaOS(self.pot, zazeni=False)

    def tearDown(self):
        self.sp.zapri()

    def _prejeta(self):
        return [s for s in self.sp.pogovor(os_sporocila.KANAL_LINKA, TEL, oznaci=False)]

    def test_prejemnik_izbrise_samo_sporocilo_posiljatelja(self):
        skupni = str(uuid.uuid4())
        self.assertTrue(self.sp.prejmi_klepet(TEL, "Telefon", "zivjo", "", skupni))
        self.assertFalse(self.sp.prejmi_izbris("tuja-naprava", skupni))          # tuja naprava ne more
        self.assertEqual(len(self._prejeta()), 1)
        self.assertTrue(self.sp.prejmi_izbris(TEL, skupni))
        self.assertEqual(self._prejeta(), [])
        # Ponovna dostava iz vrste sredisca ga ne obudi.
        self.assertFalse(self.sp.prejmi_klepet(TEL, "Telefon", "zivjo", "", skupni))

    def test_izbris_pred_sporocilom(self):
        skupni = str(uuid.uuid4())
        self.assertFalse(self.sp.prejmi_izbris(TEL, skupni))
        self.assertFalse(self.sp.prejmi_klepet(TEL, "Telefon", "zamujeno", "", skupni))
        self.assertEqual(self._prejeta(), [])

    def test_poslano_dobi_skupni_id_in_se_izbrise_na_vseh(self):
        poslano, izbrisi = [], []
        self.sp.poslji_klepet = lambda n, b, c: (poslano.append((n, b)), {"stanje": "accepted", "id": IDENT})[1]
        IDENT = str(uuid.uuid4())
        s = self.sp.poslji(os_sporocila.KANAL_LINKA, TEL, "pozdrav")
        self.assertEqual(s["id"], izbris_linka.PREDPONA_POSLANO + IDENT)
        self.sp.izbrisi_klepet = lambda cilj, sk: (izbrisi.append((cilj, sk)), "accepted")[1]
        r = self.sp.izbrisi_sporocilo(os_sporocila.KANAL_LINKA, TEL, s["id"], na_vseh=True)
        self.assertEqual((r["izbris"], r["sporocila"], izbrisi), ("koncano", [], [(TEL, IDENT)]))
        self.assertFalse(os_sporocila.cakajo_brisanja(self.pot))

    def test_naprava_brez_povezave_izbris_pocaka(self):
        IDENT = str(uuid.uuid4())
        self.sp.poslji_klepet = lambda n, b, c: {"stanje": "queued", "id": IDENT}
        s = self.sp.poslji(os_sporocila.KANAL_LINKA, TEL, "pozdrav")
        self.sp.izbrisi_klepet = lambda cilj, sk: "ni_povezave"
        r = self.sp.izbrisi_sporocilo(os_sporocila.KANAL_LINKA, TEL, s["id"], na_vseh=True)
        self.assertEqual(r["izbris"], "caka")
        self.assertTrue(os_sporocila.cakajo_brisanja(self.pot))
        self.sp.izbrisi_klepet = lambda cilj, sk: "accepted"
        self.assertEqual(self.sp.poslji_cakajoca_brisanja(), 1)
        self.assertFalse(os_sporocila.cakajo_brisanja(self.pot))

    def test_starejsi_gostitelj_brez_id_in_samo_pri_meni(self):
        self.sp.poslji_klepet = lambda n, b, c: "accepted"                       # samo stanje (niz)
        s = self.sp.poslji(os_sporocila.KANAL_LINKA, TEL, "staro")
        self.assertTrue(s["id"].startswith(izbris_linka.PREDPONA_POSLANO))
        self.assertIsNone(izbris_linka.skupni_id(s["id"], "ven"))
        with self.assertRaises(ValueError):
            self.sp.izbrisi_sporocilo(os_sporocila.KANAL_LINKA, TEL, s["id"], na_vseh=True)
        r = self.sp.izbrisi_sporocilo(os_sporocila.KANAL_LINKA, TEL, s["id"])
        self.assertEqual((r["izbris"], r["sporocila"]), ("", []))

    def test_izbris_pogovora_samo_tukaj(self):
        self.sp.prejmi_klepet(TEL, "Telefon", "a", "", str(uuid.uuid4()))
        self.sp.prejmi_klepet(TEL, "Telefon", "b", "", str(uuid.uuid4()))
        seznam = self.sp.izbrisi_pogovor(os_sporocila.KANAL_LINKA, TEL)
        pogovori = [p for sk in seznam["skupine"] for p in sk["pogovori"] if p["kanal_id"] == os_sporocila.KANAL_LINKA]
        self.assertEqual(pogovori, [])
        # Novo sporocilo iste naprave pogovor odpre znova.
        self.assertTrue(self.sp.prejmi_klepet(TEL, "Telefon", "c", "", str(uuid.uuid4())))
        self.assertEqual([s["besedilo"] for s in self._prejeta()], ["c"])


class Control(unittest.TestCase):
    def _cb(self, zmoznosti):
        from safeer_windows import control_backend as CB
        poslano = []

        class Povezava:
            def poslji(self, sporocilo):
                poslano.append(sporocilo)
                vnos = cb._klepet_cakajoci.get(sporocilo["id"])
                vnos[1] = "accepted"
                vnos[0].set()
                return True

        cb = types.SimpleNamespace(naprave=[{"id": "t1", "naprava": TEL, "zmoznosti": zmoznosti}],
                                   _klepet_cakajoci={}, povezava=Povezava(), je_povezan=lambda: True)
        cb.poslji_klepet = lambda *a, **k: CB.SafeerControlBackend.poslji_klepet(cb, *a, **k)
        return CB, cb, poslano

    def test_izbris_samo_napravi_ki_ga_zna(self):
        CB, cb, poslano = self._cb(["chat"])
        self.assertEqual(CB.SafeerControlBackend.poslji_izbris(cb, TEL, "abc"), "ne_zna")
        self.assertEqual(poslano, [])
        CB, cb, poslano = self._cb(["chat", "chat.delete"])
        self.assertEqual(CB.SafeerControlBackend.poslji_izbris(cb, TEL, "abc"), "accepted")
        self.assertEqual(poslano[0]["payload"]["delete"], "abc")
        self.assertEqual(poslano[0]["payload"]["text"], izbris_linka.BESEDILO_IZBRISA)
        self.assertTrue(izbris_linka.je_uuid(poslano[0]["id"]))

    def test_klepet_z_id(self):
        CB, cb, poslano = self._cb(["chat"])
        r = CB.SafeerControlBackend.poslji_klepet_z_id(cb, TEL, "zivjo", "2026-10-25T10:00:00+00:00")
        self.assertEqual(r["stanje"], "accepted")
        self.assertEqual(poslano[0]["id"], r["id"])
        self.assertTrue(izbris_linka.je_uuid(r["id"]))

    def test_zmoznost_in_povezave(self):
        cb = (KOREN / "windows" / "safeer_windows" / "control_backend.py").read_text(encoding="utf-8")
        self.assertIn('"chat", "chat.delete", "lists"', cb)
        app = (KOREN / "windows" / "safeer_windows" / "os_app.py").read_text(encoding="utf-8")
        self.assertIn("self.sporocila.izbrisi_klepet = lambda n, i: self.control_backend.poslji_izbris(n, i)", app)
        self.assertIn("self.sporocila.prejmi_izbris(od, str(telo[\"delete\"]))", app)
        self.assertIn('if metoda == "sporocilaIzbrisi":', app)
        js = (KOREN / "assets" / "os" / "os.js").read_text(encoding="utf-8")
        self.assertIn('klic("sporocilaIzbrisi", [pogovor.kanal_id, pogovor.id, id, !!naVseh])', js)


if __name__ == "__main__":
    unittest.main()
