"""Lasten ponudnik Usenet v Safeer OS za Windows (naloga 44; kot Linux naloga 114, material Grok naloga 112).

Okno Nastavitve -> Viri medijskega centra -> »Usenet ponudnik« (most mediaUsenetPonudnik v os_app), geslo samo v sistemski
zbirki (core/sporocila/skrivnosti.py = Upravitelj poverilnic; tu lazna zbirka), predvajanje NZB z lastnim pogonom
(Debrid.lastni_usenet, os_media). Jedro (core/usenet_*) je skupno z Linuxom in ima tam svoje preizkuse. Brez omrezja;
poverilnice so izmisljene.
"""
import io
import json
import os
import re
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import pytest

KOREN = Path(__file__).resolve().parents[2]
if str(KOREN) not in sys.path:
    sys.path.insert(0, str(KOREN))

pytest.importorskip("PySide6")

from core import debrid, os_media, usenet_nntp as nntp, usenet_ponudnik as up  # noqa: E402
from core import usenet_vezava as uv  # noqa: E402
from safeer_windows import os_app, usenet_win  # noqa: E402

GESLO = "Izmisljeno-Geslo-44-Qx"
UPORABNIK = "izmisljen-uporabnik-44"
JEZIKI = ("sl", "en", "de", "es", "fr", "it")
OS = KOREN / "assets" / "os"


class LaznaZbirka:
    def __init__(self):
        self.vnosi = {}

    def shrani(self, kljuc, vrednost):
        self.vnosi[kljuc] = vrednost
        return True

    def preberi(self, kljuc):
        return self.vnosi.get(kljuc)

    def pozabi(self, kljuc):
        self.vnosi.pop(kljuc, None)


def _pocisti():
    for m in (nntp._ZAVRNJENI, nntp._NEZNANE, up._PREVERBE, up._V_POMNILNIKU, up._ZAVRNJENA, up._RACUNI, uv._VEZAVE):
        m.clear()


class Okolje(unittest.TestCase):
    def setUp(self):
        self._mapa = tempfile.TemporaryDirectory()
        self.mapa = Path(self._mapa.name)
        self.zbirka = LaznaZbirka()
        self._zbirka = mock.patch.object(up, "skrivnosti", self.zbirka)
        self._zbirka.start()
        nntp.nastavi_shrambo_zapaha(str(self.mapa / "stanje" / "usenet-zapah"))
        _pocisti()
        self.mc = os_media.MediaCenter(self.mapa / "nastavitve")
        self.vezava = usenet_win.vezi(self.mc, str(self.mapa / "lokalno" / uv.IME_DATOTEKE))
        self.okno = types.SimpleNamespace(media_center=self.mc)

    def tearDown(self):
        for v in list(uv._VEZAVE.values()):
            v.ustavi_predvajanje()
        _pocisti()
        nntp.nastavi_shrambo_zapaha(None)
        self._zbirka.stop()
        self._mapa.cleanup()

    def most(self, *a):
        return os_app.SafeerOsWindow._izvedi_metodo(self.okno, "mediaUsenetPonudnik", list(a))

    def vnos(self, **k):
        return dict({"ime": "Moj ponudnik", "gostitelj": "news.primer.invalid", "vrata": "563", "tls": True,
                     "najvec_povezav": "8", "uporabnik": UPORABNIK, "nevarno_brez_tls": False}, **k)


class MostTest(Okolje):
    def test_most_pozna_mediaUsenetPonudnik_in_vrne_kodo(self):
        s = self.most("stanje")
        self.assertTrue(s["ok"])
        self.assertEqual(s["stanje"]["kljuc"], uv.NI_VPISAN)
        self.assertEqual(self.most("neznano")["koda"], uv.N_VNOS)

    def test_geslo_samo_v_zbirki_nikoli_v_odgovoru_datoteki_ali_dnevniku(self):
        with redirect_stdout(io.StringIO()) as izpis:
            r = self.most("shrani", self.vnos(), GESLO)
            s = self.most("stanje")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["koda"], uv.SHRANJENO)
        self.assertEqual(s["stanje"]["kljuc"], up.NEPREVERJEN.lower())
        self.assertIn(GESLO, self.zbirka.vnosi.values())
        for besedilo in (json.dumps(r), json.dumps(s), izpis.getvalue()):
            self.assertNotIn(GESLO, besedilo)
            self.assertNotIn(UPORABNIK, besedilo)        # tudi uporabnisko ime se ne vrne na stran
        for p in self.mapa.rglob("*"):
            if p.is_file():
                self.assertNotIn(GESLO.encode(), p.read_bytes(), p.name)

    def test_napacen_vnos_je_koda_iz_KODE(self):
        r = self.most("shrani", self.vnos(gostitelj="http://news.primer.invalid:563"), GESLO)
        self.assertFalse(r["ok"])
        self.assertIn(r["koda"], uv.KODE)
        self.assertEqual(self.zbirka.vnosi, {})

    # Meje vnosa z okna (primeri iz Grokovega preizkusa naloge 112, test_usenet_most.py): presodi jih jedro
    # (usenet_vezava.most -> usenet_ponudnik), okno dobi samo kodo; nic ne gre v zbirko, geslo ni v odgovoru.
    SOVRAZNI = [("vrata", True), ("vrata", 0), ("vrata", 65536), ("vrata", "x" * 100000),
                ("najvec_povezav", 0), ("najvec_povezav", 101), ("najvec_povezav", True), ("najvec_povezav", 8.5),
                ("najvec_povezav", 10 ** 30), ("tls", False), ("gostitelj", "a" * 254), ("gostitelj", ""),
                ("gostitelj", 5), ("gostitelj", "x" * 100000), ("gostitelj", "https://news.primer.invalid"),
                ("gostitelj", "news.primer.invalid:563"), ("uporabnik", "u" * 401), ("uporabnik", ""),
                ("uporabnik", ["uporabnik1"]), ("uporabnik", "a\r\nQUIT"), ("ime", "i" * 81), ("ime", 7),
                ("ime", "a\x00b")]

    def test_sovrazen_vnos_zavrnjen_s_kodo(self):
        for polje, vrednost in self.SOVRAZNI:
            with self.subTest(polje=polje, vrednost=str(vrednost)[:20]):
                r = self.most("shrani", self.vnos(**{polje: vrednost}), GESLO)
                self.assertFalse(r["ok"], r)
                self.assertIn(r["koda"], uv.KODE)
                self.assertNotIn(GESLO, json.dumps(r))
                self.assertEqual(self.zbirka.vnosi, {})
        for geslo in ("g" * 401, "", "a\r\nQUIT", 1234, None):
            with self.subTest(geslo=str(geslo)[:20]):
                r = self.most("shrani", self.vnos(), geslo)
                self.assertFalse(r["ok"], r)
                self.assertIn(r["koda"], uv.KODE)
                self.assertEqual(self.zbirka.vnosi, {})
        for a in ([], [1], ["shrani"], ["shrani", "niz", GESLO], ["shrani", [1, 2], GESLO], ["pozabi"]):
            with self.subTest(a=str(a)[:30]):
                r = os_app.SafeerOsWindow._izvedi_metodo(self.okno, "mediaUsenetPonudnik", a)
                self.assertFalse(r["ok"], r)
                self.assertIn(r["koda"], uv.KODE)
        self.assertFalse(Path(self.vezava.pot).exists())

    def test_pozabi_odstrani_geslo(self):
        self.most("shrani", self.vnos(), GESLO)
        r = self.most("odstrani")
        self.assertEqual(r["koda"], uv.ODSTRANJENO)
        self.assertEqual(self.zbirka.vnosi, {})
        self.assertEqual(r["stanje"]["kljuc"], uv.NI_VPISAN)


class VezavaTest(Okolje):
    def test_ista_vezava_za_okno_in_predvajanje(self):
        self.assertIs(self.mc.debrid.lastni_usenet, self.vezava)
        self.assertIs(usenet_win.vezi(self.mc, self.vezava.pot), self.vezava)
        self.assertFalse(self.mc.debrid.lastni_usenet_na_voljo())
        self.most("shrani", self.vnos(), GESLO)
        self.assertTrue(self.mc.debrid.lastni_usenet_na_voljo())

    def test_sprememba_zapise_izvoz_virov(self):
        with mock.patch.object(self.mc, "_viri_zapisi_izvoz") as izvoz:
            usenet_win.vezi(self.mc, self.vezava.pot)
            self.most("shrani", self.vnos(), GESLO)
        izvoz.assert_called()

    def test_nastavitev_v_localappdata_ne_v_roaming(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Lokalno", "APPDATA": r"C:\Roaming"}):
            pot = usenet_win.pot_nastavitev()
        self.assertEqual(pot, os.path.join(r"C:\Lokalno", "SafeerOS", uv.IME_DATOTEKE))

    def test_os_app_veze_ob_zagonu_in_klice_most(self):
        vir = Path(os_app.__file__).read_text(encoding="utf-8")
        self.assertRegex(vir, r"self\.media_center = os_media\.MediaCenter\([^\n]*\)\n(\s*#[^\n]*\n)*\s*usenet_win\.vezi\(self\.media_center\)")


class LaznDebrid:
    """Debrid z lastnim pogonom: zabelezi klice usenet_tok (brez omrezja)."""

    def __init__(self, lastni):
        self.lastni = lastni
        self.klici = []

    def lastni_usenet_na_voljo(self):
        return self.lastni

    def usenet_tok(self, url, ime, **k):
        self.klici.append(k)
        if k.get("lastni") is True:
            return debrid.Izid(url="http://127.0.0.1:5/zeton/film.mkv", ponudnik=debrid.LASTNI_USENET)
        return debrid.Izid(napaka="ni")

    def usenet_takoj(self, zadetki, rok):
        return None


class PredvajanjeTest(Okolje):
    ZADETKI = [{"url": "usenet:1", "naslov": "Film.2026.1080p", "gb": 4.0, "opis": "1080p"}]

    def test_lastni_pogon_predvaja_nzb_brez_torboxa(self):
        lazni = LaznDebrid(True)
        self.mc.debrid = lazni
        with mock.patch.object(self.mc, "_usenet_zadetki", return_value=list(self.ZADETKI)):
            r = self.mc._razresi_usenet_takoj("id1", {"naslov": "Film"}, "tt0000001", [])
        self.assertIsNotNone(r)
        self.assertEqual(r["url"], "http://127.0.0.1:5/zeton/film.mkv")
        self.assertEqual(r["razlicice"][0]["vir"], "Usenet · NNTP")
        self.assertEqual(lazni.klici, [{"lastni": True}])

    def test_drugi_korak_samo_torbox_ce_je_lastni_ze_poskusil(self):
        lazni = LaznDebrid(True)
        self.mc.debrid = lazni
        with mock.patch.object(self.mc, "_usenet_mogoc", return_value=True), \
                mock.patch.object(self.mc, "_usenet_zadetki", return_value=list(self.ZADETKI)):
            self.mc._razresi_usenet("id1", {"naslov": "Film"}, "movie", "tt0000001", [])
        self.assertTrue(lazni.klici and all(k.get("lastni") is False for k in lazni.klici))

    def test_brez_lastnega_klic_kot_prej(self):
        lazni = LaznDebrid(False)
        self.mc.debrid = lazni
        with mock.patch.object(self.mc, "_usenet_mogoc", return_value=True), \
                mock.patch.object(self.mc, "_usenet_zadetki", return_value=list(self.ZADETKI)):
            self.mc._razresi_usenet("id1", {"naslov": "Film"}, "movie", "tt0000001", [])
        self.assertTrue(lazni.klici and all("lastni" not in k for k in lazni.klici))


class OknoTest(unittest.TestCase):
    HTML = (OS / "index.html").read_text(encoding="utf-8")
    JS = (OS / "os.js").read_text(encoding="utf-8")
    BESEDILA = (OS / "besedila.js").read_text(encoding="utf-8")

    def test_okno_v_nastavitvah_z_vsemi_polji(self):
        i = self.HTML.index('id="unpSekcija"')
        self.assertLess(self.HTML.index('id="mediaDodajStreznik"'), i)
        self.assertLess(i, self.HTML.index('id="mediaNastavitveMesto"'))
        for ident in set(re.findall(r'\$\("(unp[A-Za-z]+)"\)', self.JS)):
            self.assertIn('id="%s"' % ident, self.HTML, ident)
        self.assertIn('id="unpGeslo" type="password"', self.HTML)

    def test_stran_klice_most_in_nalozi_ob_nastavitvah(self):
        self.assertEqual(sorted(set(re.findall(r'klic\("mediaUsenetPonudnik", \["(\w+)"', self.JS))), sorted(uv.DEJANJA))
        self.assertRegex(self.JS, r'razdelek === "nastavitve"\) \{\s*\n[^\n]*naloziUsenetPonudnik\(\)')
        self.assertIn('on("unpObrazec", "submit", unpShrani);', self.JS)

    def test_geslo_in_uporabnik_nikoli_iz_stanja_na_stran(self):
        self.assertIn('$("unpGeslo").value = "";', self.JS)
        self.assertIn('$("unpUporabnik").value = "";', self.JS)
        self.assertNotRegex(self.JS, r'\$\("unp(Geslo|Uporabnik)"\)\.value = s\.')

    def test_besedila_vseh_kod_v_6_jezikih(self):
        bloki = {}
        for jezik, telo in re.findall(r'Object\.assign\(BESEDILA_OS\.(\w+), (\{"unpNaslov".*?\})\);', self.BESEDILA):
            bloki[jezik] = json.loads(telo)
        self.assertEqual(sorted(bloki), sorted(JEZIKI))
        kljuci = set(bloki["sl"])
        for koda in uv.KODE:
            self.assertIn("unpKoda_" + koda, kljuci, koda)
        uporabljeni = set(re.findall(r'data-(?:t|ph)="(unp\w+)"', self.HTML)) | set(re.findall(r't\("(unp\w+)"\)', self.JS))
        self.assertTrue(uporabljeni <= kljuci, uporabljeni - kljuci)
        for jezik in JEZIKI:
            self.assertEqual(set(bloki[jezik]), kljuci, jezik)
            self.assertTrue(all(str(v).strip() for v in bloki[jezik].values()), jezik)


if __name__ == "__main__":
    unittest.main()
