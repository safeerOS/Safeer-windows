"""Magnet povezave, podnapisi in DVD na Windows: Link ukaz magnet.open, registracija protokola magnet: (s
laznim registrom), samodejna izbira podnapisov in DVD v medijski knjiznici. Brez omrezja in brez Qt."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

KOREN = Path(__file__).resolve().parents[2]
for pot in (str(KOREN / "windows"), str(KOREN)):
    if pot not in sys.path:
        sys.path.insert(0, pot)

from safeer_windows import control_backend, magnet_win, podnapisi_izbira as pi  # noqa: E402
from core import os_dvd, os_media  # noqa: E402

HASH = "dd8255ecdc7ca55fb0bbf81323d87062db1f6d1c"
MAGNET = "magnet:?xt=urn:btih:%s&dn=Big+Buck+Bunny" % HASH
# Motor dobi očiščeno povezavo (samo xt, dn in javni sledilniki) - core/os_torrent.razcleni_magnet.
CIST = "magnet:?xt=urn:btih:dd8255ecdc7ca55fb0bbf81323d87062db1f6d1c&dn=Big%20Buck%20Bunny"


class _Povezava:
    tece = True

    def __init__(self):
        self.poslana = []

    def poslji(self, sporocilo):
        self.poslana.append(sporocilo)
        return True


class LinkMagnet(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.backend = control_backend.SafeerControlBackend(config_pot=os.path.join(self.td, "link.json"))
        self.backend.povezava = _Povezava()

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def _ukaz(self, dejanje, parametri, posiljatelj="tv-1"):
        self.backend._na_sporocilo({"id": "u-" + dejanje, "type": "control.command", "sender": posiljatelj,
                                    "payload": {"action": dejanje, "params": parametri}})
        return self.backend.povezava.poslana[-1]["payload"]

    def test_magnet_odpre_safeer_os_v_istem_procesu(self):
        odprti = []
        self.backend.ob_magnetu = odprti.append
        self.assertTrue(self._ukaz("magnet.open", {"uri": MAGNET})["ok"])
        self.assertEqual(odprti, [CIST])
        # Karkoli drugega (ukaz, pot, spletni naslov) naprava ne more podtakniti.
        for slab in ("--help", "https://x.si", "magnet:?xt=urn:btih:abc; rm -rf ~", "", "C:\\Windows\\notepad.exe"):
            odgovor = self._ukaz("magnet.open", {"uri": slab})
            self.assertFalse(odgovor["ok"], slab)
            self.assertEqual(odgovor["code"], "ni_magnet")
        self.assertEqual(len(odprti), 1)

    def test_magnet_brez_okna_zazene_safeer_os(self):
        zagnani = []
        with mock.patch.object(magnet_win, "zaganjalnik", lambda: ["C:\\Safeer\\SafeerOS.exe"]), \
                mock.patch("subprocess.Popen", lambda ukaz, **_k: zagnani.append(ukaz)):
            self.assertTrue(self._ukaz("magnet.open", {"uri": MAGNET})["ok"])
        self.assertEqual(zagnani, [["C:\\Safeer\\SafeerOS.exe", "--magnet-naprava", CIST]])
        with mock.patch.object(magnet_win, "zaganjalnik", lambda: []):
            self.assertEqual(self._ukaz("magnet.open", {"uri": MAGNET})["code"], "ni_safeer_os")

    def test_brez_dovoljenja_ni_magneta(self):
        odprti = []
        self.backend.ob_magnetu = odprti.append
        self.backend.nastavi_dovoljenje("tv-2", "zaslon")
        self.assertFalse(self._ukaz("magnet.open", {"uri": MAGNET}, posiljatelj="tv-2")["ok"])
        self.assertEqual(odprti, [])

    def test_zmoznost_v_stanju(self):
        self.backend.ob_magnetu = lambda _u: None
        self.assertIn("magnet.open", self._ukaz("status", {})["data"]["actions"])
        with mock.patch.object(magnet_win, "zaganjalnik", lambda: []):
            self.backend.ob_magnetu = None
            self.assertNotIn("magnet.open", self._ukaz("status", {})["data"]["actions"])

    def test_naprave_za_magnet_in_posiljanje(self):
        self.backend.naprave = [
            {"id": "tv-1", "ime": "TV", "zmoznosti": ["magnet", "files"]},
            {"id": "tel-1", "ime": "Telefon", "zmoznosti": ["files"]},
            {"id": self.backend.device_id, "ime": "Ta", "zmoznosti": ["magnet"], "ta": True},
        ]
        self.assertEqual([n["id"] for n in self.backend.naprave_za_magnet()], ["tv-1"])
        self.assertEqual(self.backend.poslji_magnet("tv-1", "https://x.si")["koda"], "ni_magnet")
        with mock.patch.object(self.backend, "ukaz_pocakaj", lambda n, d, p, cas=0: {"ok": True, "n": n, "d": d, "p": p}):
            r = self.backend.poslji_magnet("tv-1", MAGNET)
        self.assertEqual((r["n"], r["d"], r["p"]), ("tv-1", "magnet.open", {"uri": CIST}))


class LinkTokTorrenta(unittest.TestCase):
    """magnet.stream / magnet.list / magnet.remove: Windows Control pomaga napravam pri torrentih kot Linux Control."""

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.backend = control_backend.SafeerControlBackend(config_pot=os.path.join(self.td, "link.json"))
        self.backend.povezava = _Povezava()

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def _ukaz(self, dejanje, parametri, posiljatelj="tv-1", cakaj=True):
        prej = len(self.backend.povezava.poslana)
        self.backend._na_sporocilo({"id": "u-" + dejanje, "type": "control.command", "sender": posiljatelj,
                                    "payload": {"action": dejanje, "params": parametri}})
        for _ in range(200 if cakaj else 1):          # odgovor pride iz svoje niti
            if len(self.backend.povezava.poslana) > prej:
                break
            import time
            time.sleep(0.02)
        self.assertGreater(len(self.backend.povezava.poslana), prej, "ni odgovora na " + dejanje)
        return self.backend.povezava.poslana[-1]["payload"]

    def test_stanje_oglasa_samo_kar_zna(self):
        from core import os_torrent
        with mock.patch.object(os_torrent, "platforma", lambda: "windows-amd64"):
            self.assertTrue({"magnet.stream", "magnet.list", "magnet.remove"} <= set(self._ukaz("status", {})["data"]["actions"]))
        with mock.patch.object(os_torrent, "platforma", lambda: ""):
            self.assertNotIn("magnet.stream", self._ukaz("status", {})["data"]["actions"])

    def test_tok_za_napravo(self):
        klici = []

        class Datoteke:
            def tok_torrenta(self, uri, naprava, hub, datoteka):
                klici.append((uri, naprava, datoteka))
                return {"server": {"base_url": "https://192.168.0.2:5000", "fp": "ab", "token": "z"}, "path": "/m/s/film.mkv",
                        "name": "film.mkv", "file": 2, "size": 10}

        with mock.patch.object(self.backend, "_datoteke_torrenta", lambda: Datoteke()), \
                mock.patch.object(control_backend.os_backend_win, "zmogljivost", lambda: {"pomoc": {"lahko": True, "razlog": ""}}):
            o = self._ukaz("magnet.stream", {"uri": MAGNET, "file": 2})
        self.assertTrue(o["ok"], o)
        self.assertEqual((o["action"], o["data"]["path"], o["data"]["file"]), ("magnet.stream", "/m/s/film.mkv", 2))
        self.assertEqual(klici, [(MAGNET, "tv-1", 2)])

    def test_napake_so_kratke_kode(self):
        from core import os_torrent
        self.assertEqual(self._ukaz("magnet.stream", {"uri": "ni magnet"})["code"], "ni_magnet")
        self.assertEqual(self._ukaz("magnet.remove", {"id": "x"})["code"], "ni_prenosa")

        class Polno:
            def tok_torrenta(self, *_a):
                raise os_torrent.NapakaTorrenta("ni_prostora")

        with mock.patch.object(self.backend, "_datoteke_torrenta", lambda: Polno()), \
                mock.patch.object(control_backend.os_backend_win, "zmogljivost", lambda: {"pomoc": {"lahko": True, "razlog": ""}}):
            o = self._ukaz("magnet.stream", {"uri": MAGNET})
        self.assertEqual((o["ok"], o["code"]), (False, "ni_prostora"))

    def test_obremenjen_procesor_ni_razlog_baterija_je(self):
        class Datoteke:
            def tok_torrenta(self, *_a):
                return {"server": {}, "path": "/m/s/f.mkv", "name": "f.mkv", "file": 0, "size": 1}

        with mock.patch.object(self.backend, "_datoteke_torrenta", lambda: Datoteke()):
            with mock.patch.object(control_backend.os_backend_win, "zmogljivost", lambda: {"pomoc": {"lahko": False, "razlog": "preobremenjen"}}):
                self.assertTrue(self._ukaz("magnet.stream", {"uri": MAGNET})["ok"])
            with mock.patch.object(control_backend.os_backend_win, "zmogljivost", lambda: {"pomoc": {"lahko": False, "razlog": "baterija"}}):
                o = self._ukaz("magnet.stream", {"uri": MAGNET})
            self.assertEqual((o["ok"], o["code"]), (False, "baterija"))

    def test_solidarnost_tudi_z_omejenimi_pravicami_brez_pravic_ne(self):
        class Datoteke:
            def prenosi_za_naprave(self):
                return {"items": []}

        self.backend.nastavi_dovoljenje("tv-2", "zaslon")
        with mock.patch.object(self.backend, "_datoteke_torrenta", lambda: Datoteke()):
            self.assertTrue(self._ukaz("magnet.list", {}, posiljatelj="tv-2")["ok"])


class _LazniRegister:
    """Dovolj winreg za registracijo: HKCR = HKCU\\Software\\Classes prek HKLM\\Software\\Classes."""
    HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE, HKEY_CLASSES_ROOT = "HKCU", "HKLM", "HKCR"
    REG_SZ = 1

    def __init__(self):
        self.kljuci = {}

    class _Kljuc:
        def __init__(self, reg, pot):
            self.reg, self.pot = reg, pot

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def _najdi(self, koren, pot):
        pot = pot.lower()
        if koren == "HKCR":
            for dejanski in (("HKCU", "software\\classes\\" + pot), ("HKLM", "software\\classes\\" + pot)):
                if dejanski in self.kljuci:
                    return dejanski
            return None
        return (koren, pot) if (koren, pot) in self.kljuci else None

    def OpenKey(self, koren, pot):  # noqa: N802
        k = self._najdi(koren, pot)
        if k is None:
            raise FileNotFoundError(pot)
        return self._Kljuc(self, k)

    def CreateKey(self, koren, pot):  # noqa: N802
        k = (koren, pot.lower())
        self.kljuci.setdefault(k, {})
        return self._Kljuc(self, k)

    def QueryValueEx(self, kljuc, ime):  # noqa: N802
        vrednosti = self.kljuci[kljuc.pot]
        if ime not in vrednosti:
            raise FileNotFoundError(ime)
        return vrednosti[ime], self.REG_SZ

    def SetValueEx(self, kljuc, ime, _r, _t, vrednost):  # noqa: N802
        self.kljuci[kljuc.pot][ime] = vrednost


class Protokol(unittest.TestCase):
    def setUp(self):
        self.zaganjalnik = mock.patch.object(magnet_win, "zaganjalnik",
                                             lambda: ["C:\\Program Files\\Safeer\\SafeerOS.exe"])
        self.zaganjalnik.start()

    def tearDown(self):
        self.zaganjalnik.stop()

    def test_ukaz_je_citiran(self):
        self.assertEqual(magnet_win.ukaz_za_magnet(),
                         '"C:\\Program Files\\Safeer\\SafeerOS.exe" --magnet "%1"')

    def test_registracija_samo_hkcu(self):
        reg = _LazniRegister()
        self.assertFalse(magnet_win.je_privzeto(reg))
        odprto = []
        self.assertTrue(magnet_win.nastavi_privzeto(reg, odprto.append))
        self.assertEqual(odprto, [])
        self.assertTrue(all(koren == "HKCU" for koren, _p in reg.kljuci))
        ukaz = reg.kljuci[("HKCU", "software\\classes\\magnet\\shell\\open\\command")][""]
        self.assertEqual(ukaz, magnet_win.ukaz_za_magnet())
        self.assertEqual(reg.kljuci[("HKCU", "software\\classes\\magnet")]["URL Protocol"], "")
        self.assertTrue(magnet_win.je_privzeto(reg))

    def test_izbira_uporabnika_ima_prednost(self):
        reg = _LazniRegister()
        with reg.CreateKey("HKCU", magnet_win.KLJUC_IZBIRE) as k:
            reg.SetValueEx(k, "ProgId", 0, 1, "qBittorrent.magnet")
        odprto = []
        self.assertFalse(magnet_win.nastavi_privzeto(reg, odprto.append))
        self.assertTrue(odprto and odprto[0].startswith("ms-settings:defaultapps"))
        # Ko uporabnik v Nastavitvah izbere Safeer OS (ProgID), velja nas ukaz.
        with reg.CreateKey("HKCU", magnet_win.KLJUC_IZBIRE) as k:
            reg.SetValueEx(k, "ProgId", 0, 1, magnet_win.PROGID)
        self.assertTrue(magnet_win.je_privzeto(reg))

    def test_tuj_program_v_hklm_ni_nas(self):
        reg = _LazniRegister()
        with reg.CreateKey("HKLM", "Software\\Classes\\magnet\\shell\\open\\command") as k:
            reg.SetValueEx(k, "", 0, 1, '"C:\\drug.exe" "%1"')
        self.assertFalse(magnet_win.je_privzeto(reg))


class IzbiraPodnapisov(unittest.TestCase):
    P = [{"jezik": "en"}, {"jezik": "sl"}, {"jezik": ""}]

    def test_samodejno_kot_vlc(self):
        prazno = {"izklop": None, "jezik": ""}
        self.assertEqual(pi.samodejna_zunanja(self.P, prazno, "sl"), 1)       # jezik sistema
        self.assertEqual(pi.samodejna_zunanja(self.P, prazno, "de"), -1)      # vec datotek, nobena v jeziku
        self.assertEqual(pi.samodejna_zunanja(self.P[:1], prazno, "de"), 0)   # edina datoteka
        self.assertEqual(pi.samodejna_zunanja(self.P, {"izklop": None, "jezik": "en"}, "sl"), 0)  # zadnja izbira
        self.assertEqual(pi.samodejna_zunanja(self.P, {"izklop": True, "jezik": "sl"}, "sl"), -1)
        self.assertEqual(pi.samodejna_zunanja(self.P, {"izklop": False, "jezik": ""}, "de"), 0)

    def test_vgrajeni_samo_v_jeziku_ali_ce_vklopljeni(self):
        vgrajeni = [(3, "en"), (4, "sl")]
        self.assertEqual(pi.samodejni_vgrajeni(vgrajeni, {"izklop": None, "jezik": ""}, "sl"), 4)
        self.assertIsNone(pi.samodejni_vgrajeni(vgrajeni, {"izklop": None, "jezik": ""}, "de"))
        self.assertEqual(pi.samodejni_vgrajeni(vgrajeni, {"izklop": False, "jezik": ""}, "de"), 3)
        self.assertIsNone(pi.samodejni_vgrajeni(vgrajeni, {"izklop": True, "jezik": "sl"}, "sl"))

    def test_izbira_se_zapomni_in_tipka_v(self):
        self.assertEqual(pi.po_izbiri({"izklop": None, "jezik": "en"}, "izklop"), {"izklop": True, "jezik": "en"})
        self.assertEqual(pi.po_izbiri({"izklop": True, "jezik": "en"}, "z:1", "sl"), {"izklop": False, "jezik": "sl"})
        self.assertEqual(pi.naslednji_kljuc(["izklop", "z:0", "v:3"], "izklop"), "z:0")
        self.assertEqual(pi.naslednji_kljuc(["izklop", "z:0", "v:3"], "v:3"), "izklop")
        self.assertEqual(pi.koda_jezika("eng"), "en")
        self.assertEqual(pi.koda_jezika("Track 1 - [Slovenian]"), "sl")
        self.assertEqual(pi.koda_jezika("Track 1"), "")


class DvdKnjiznica(unittest.TestCase):
    def test_mapa_video_ts_je_film_z_naslovom_dvd(self):
        td = tempfile.mkdtemp()
        try:
            disk = os.path.join(td, "Počitnice 2003")
            os.makedirs(os.path.join(disk, "VIDEO_TS"))
            open(os.path.join(disk, "VIDEO_TS", "VIDEO_TS.IFO"), "wb").close()
            open(os.path.join(disk, "VIDEO_TS", "VTS_01_1.VOB"), "wb").close()
            with open(os.path.join(td, "podatki.iso"), "wb") as d:
                d.write(b"\0" * 4096)                         # ni DVD: ne sodi v knjiznico
            center = os_media.MediaCenter(os.path.join(td, "cfg"))
            center.roots = [Path(td)]
            vnosi = [v for v in center._local_items() if v.get("dvd")]
            self.assertEqual(len(vnosi), 1)
            self.assertEqual(vnosi[0]["naslov"], "Počitnice 2003")
            self.assertEqual(vnosi[0]["vrsta"], "film")
            self.assertEqual(vnosi[0]["url"], os_dvd.uri(os.path.join(disk, "VIDEO_TS", "VIDEO_TS.IFO")))
            with mock.patch.object(os_dvd, "_windows", lambda: True):
                self.assertTrue(os_dvd.uri(disk).startswith("dvd:///"))
                self.assertIn("Po%C4%8Ditnice%202003", os_dvd.uri(disk))
        finally:
            shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
