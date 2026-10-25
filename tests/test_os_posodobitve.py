"""Posodobitve s safeer.si: podpis seznama razlicic (Ed25519), samo https, obvezen SHA-256, primerjava razlicic,
izbira datoteke po nacinu namestitve, prenos s SHA-256, namestitev brez znizanja razlicice, AppImage zamenjava."""
import base64
import hashlib
import http.server
import json
import os
import shutil
import socketserver
import sys
import tempfile
import threading
import unittest
from unittest import mock
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import os_posodobitve as op  # noqa: E402
from core import signed_feed  # noqa: E402

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except Exception:  # pragma: no cover - CI in razvoj imata python3-cryptography
    Ed25519PrivateKey = None

MANIFEST = {
    "android": {"si.safeer.phone": {"razlicica": "0.5.28", "koda": 53, "url": "https://safeer.si/os/a.apk", "sha256": "0" * 64, "velikost": 5}},
    "linux": {"safeer-os": {"razlicica": "0.4.23", "deb": {"url": "https://safeer.si/os/safeer-os_0.4.23_all.deb", "sha256": "a" * 64, "velikost": 1},
                            "tema_deb": {"url": "https://safeer.si/os/safeer-os-tema_0.4.23_all.deb", "sha256": "b" * 64, "velikost": 1},
                            "flatpak": {"url": "https://safeer.si/os/Safeer-OS-0.4.23-x86_64.flatpak", "sha256": "c" * 64, "velikost": 1},
                            "appimage": {"url": "https://github.com/x/Safeer-OS-0.4.23-x86_64.AppImage", "sha256": "d" * 64, "velikost": 1}},
              "safeer-control": {"razlicica": "2.1.21", "deb": {"url": "https://safeer.si/os/safeer-control_2.1.21_all.deb", "sha256": "e" * 64, "velikost": 1}}},
    "windows": {"safeer-os": {"razlicica": "1.0.18", "url": "https://github.com/x/SafeerOS-Windows-1.0.18.exe", "sha256": "f" * 64, "velikost": 1},
                "novo": {"sl": "Posodobitve z enim pritiskom.", "en": "One-press updates."}},
    "stran": "https://safeer.si/os/",
}


def _svez_manifest(izdano="2026-09-01T00:00:00Z", potece="2030-01-01T00:00:00Z"):
    """Kopija MANIFEST s svezino (izdano/potece) za preizkuse prenosa seznama."""
    m = json.loads(json.dumps(MANIFEST))
    m["izdano"], m["potece"] = izdano, potece
    return m


def _kljuc():
    k = Ed25519PrivateKey.generate()
    javni = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return k, base64.b64encode(javni).decode("ascii")


def _podpis(k, podatki: bytes, kljuc_id: str = "preizkus", kontekst: bytes = None) -> bytes:
    sig = k.sign((op.KONTEKST if kontekst is None else kontekst) + podatki)
    return json.dumps([{"alg": "ed25519", "key_id": kljuc_id, "sig": base64.b64encode(sig).decode("ascii")}]).encode("ascii")


class _Streznik:
    """Lokalni http streznik za preizkuse: datoteke iz mape, preusmeritve po poti, steje zahteve."""

    def __init__(self, mapa: str, preusmeritve: dict = None) -> None:
        self.zahteve = []
        zahteve, preusm = self.zahteve, dict(preusmeritve or {})

        class Obdelava(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **k):
                super().__init__(*a, directory=mapa, **k)

            def do_GET(self):
                zahteve.append(self.path)
                if self.path in preusm:
                    self.send_response(302)
                    self.send_header("Location", preusm[self.path])
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                super().do_GET()

            def log_message(self, *a):
                pass
        self.s = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Obdelava)
        self.s.daemon_threads = True
        self.vrata = self.s.server_address[1]
        self.preusmeritve = preusm
        threading.Thread(target=self.s.serve_forever, daemon=True).start()

    def url(self, pot: str, gostitelj: str = "127.0.0.1") -> str:
        return f"http://{gostitelj}:{self.vrata}{pot}"

    def ustavi(self) -> None:
        self.s.shutdown()
        self.s.server_close()


class Razlicice(unittest.TestCase):
    def test_novejsa(self):
        self.assertTrue(op.novejsa("0.4.23", "0.4.22"))
        self.assertTrue(op.novejsa("0.5.0", "0.4.99"))
        self.assertTrue(op.novejsa("1.0.18", "1.0.9"))
        self.assertFalse(op.novejsa("0.4.22", "0.4.22"))
        self.assertFalse(op.novejsa("0.4.21", "0.4.22"))
        self.assertFalse(op.novejsa("", "0.4.22"))

    def test_preveri_linux_deb(self):
        i = op.preveri("linux", {"safeer-os": "0.4.22", "safeer-control": "2.1.21"}, MANIFEST, nacin="deb")
        self.assertEqual([n["kljuc"] for n in i["nove"]], ["safeer-os"])
        n = i["nove"][0]
        self.assertEqual((n["ime"], n["nasa"], n["razlicica"], n["datoteka"]["url"].rsplit("/", 1)[1]), ("Safeer OS", "0.4.22", "0.4.23", "safeer-os_0.4.23_all.deb"))
        self.assertEqual(n["tema"]["url"].rsplit("/", 1)[1], "safeer-os-tema_0.4.23_all.deb")
        self.assertEqual(op.opis(i), "Safeer OS 0.4.23")

    def test_preveri_flatpak_appimage_windows(self):
        f = op.preveri("linux", {"safeer-os": "0.4.22"}, MANIFEST, nacin="flatpak")["nove"][0]
        self.assertTrue(f["datoteka"]["url"].endswith(".flatpak") and "tema" not in f)
        a = op.preveri("linux", {"safeer-os": "0.4.22"}, MANIFEST, nacin="appimage")["nove"][0]
        self.assertTrue(a["datoteka"]["url"].endswith(".AppImage"))
        w = op.preveri("windows", {"safeer-os": "1.0.17"}, MANIFEST, nacin="windows")
        self.assertEqual((w["nove"][0]["razlicica"], w["nove"][0]["datoteka"]["url"].rsplit("/", 1)[1]), ("1.0.18", "SafeerOS-Windows-1.0.18.exe"))
        self.assertEqual((w["novo"]["sl"], w["novo"]["en"]), ("Posodobitve z enim pritiskom.", "One-press updates."))
        self.assertEqual(op.preveri("windows", {"safeer-os": "1.0.18"}, MANIFEST, nacin="windows")["nove"], [])
        self.assertEqual(op.preveri("linux", {"safeer-os": "0.4.22"}, MANIFEST, nacin="deb")["novo"], {})
        # neznan nacin: nova razlicica brez datoteke (vmesnik odpre stran)
        n = op.preveri("linux", {"safeer-os": "0.4.22"}, MANIFEST, nacin="neznano")["nove"][0]
        self.assertIsNone(n["datoteka"])

    def test_datoteka_brez_veljavnega_sha256_ali_https_ni_za_namestitev(self):
        """Paket brez 64-mestnega SHA-256 ali z naslovom, ki ni https, se ne ponudi za namestitev v programu (samo stran)."""
        for slabo in ({"sha256": ""}, {"sha256": None}, {"sha256": "a" * 63}, {"sha256": "g" * 64}, {"sha256": "a" * 65},
                      {"url": "http://safeer.si/os/safeer-os_0.4.23_all.deb"}, {"url": "file:///tmp/safeer-os_0.4.23_all.deb"},
                      {"url": "ftp://safeer.si/os/safeer-os_0.4.23_all.deb"}):
            m = json.loads(json.dumps(MANIFEST))
            m["linux"]["safeer-os"]["deb"].update(slabo)
            n = op.preveri("linux", {"safeer-os": "0.4.22"}, m, nacin="deb")["nove"][0]
            self.assertIsNone(n["datoteka"], slabo)
        m = json.loads(json.dumps(MANIFEST))
        del m["linux"]["safeer-os"]["deb"]["sha256"]
        self.assertIsNone(op.preveri("linux", {"safeer-os": "0.4.22"}, m, nacin="deb")["nove"][0]["datoteka"])
        m = json.loads(json.dumps(MANIFEST))
        m["windows"]["safeer-os"]["sha256"] = ""
        self.assertIsNone(op.preveri("windows", {"safeer-os": "1.0.17"}, m, nacin="windows")["nove"][0]["datoteka"])

    def test_tema_brez_veljavnega_sha256_ustavi_namestitev_paketa(self):
        """Paket videza gre v isti apt-get: ce njegov vnos ni veljaven, programa ne namestimo napol (samo stran)."""
        m = json.loads(json.dumps(MANIFEST))
        m["linux"]["safeer-os"]["tema_deb"]["sha256"] = ""
        n = op.preveri("linux", {"safeer-os": "0.4.22"}, m, nacin="deb")["nove"][0]
        self.assertIsNone(n["datoteka"])
        self.assertNotIn("tema", n)

    def test_aplikacija_dobi_svoj_paket(self):
        """Od 20. 10. 2026 sta namizno okolje (safeer-os) in aplikacija (safeer-os-app) loceni paketi, ki se med sabo
        zamenjata: posodobitev aplikacije mora prenesti "deb_app", nikoli namiznega okolja (to bi aplikacijo zamenjalo z
        namizjem); brez "deb_app" nic (stran). Namizno okolje ostane pri "deb"."""
        m = json.loads(json.dumps(MANIFEST))
        app = {"url": "https://github.com/x/safeer-os-app_0.4.23_amd64.deb", "sha256": "3" * 64, "velikost": 9}
        with mock.patch.object(op, "je_aplikacija_deb", return_value=True):
            self.assertIsNone(op.preveri("linux", {"safeer-os": "0.4.22"}, m, nacin="deb")["nove"][0]["datoteka"])
            m["linux"]["safeer-os"]["deb_app"] = app
            n = op.preveri("linux", {"safeer-os": "0.4.22"}, m, nacin="deb")["nove"][0]
            self.assertEqual(n["datoteka"], app)
        with mock.patch.object(op, "je_aplikacija_deb", return_value=False):
            n = op.preveri("linux", {"safeer-os": "0.4.22"}, m, nacin="deb")["nove"][0]
            self.assertTrue(n["datoteka"]["url"].endswith("safeer-os_0.4.23_all.deb"))

    def test_odstranjena_aplikacija_ne_steje(self):
        """Pomocnik 20. 10. 2026: po menjavi aplikacija -> namizje ostane safeer-os-app.list (stanje rc/ic) - posodobitev
        je zato namestila APLIKACIJO in odstranila namizno okolje. Steje samo stanje dpkg »ii«."""
        def dpkg(stanja):
            def tek(ukaz, **_k):
                return mock.Mock(returncode=0, stdout=stanja.get(ukaz[-1], "un "))
            return tek
        with mock.patch.object(op.shutil, "which", return_value="/usr/bin/dpkg-query"), \
                mock.patch.object(op.subprocess, "run", side_effect=dpkg({"safeer-os": "ii ", "safeer-os-app": "rc "})), \
                mock.patch.object(op.os.path, "exists", return_value=True):
            self.assertFalse(op.je_aplikacija_deb())
            self.assertTrue(op.namescen_deb("safeer-os"))
        with mock.patch.object(op.shutil, "which", return_value="/usr/bin/dpkg-query"), \
                mock.patch.object(op.subprocess, "run", side_effect=dpkg({"safeer-os-app": "ii "})):
            self.assertTrue(op.je_aplikacija_deb())
            self.assertFalse(op.namescen_deb("safeer-os"))
        with mock.patch.object(op.shutil, "which", return_value=None):
            self.assertFalse(op.je_aplikacija_deb())

    def test_skupni_webkit_v_istem_apt_get(self):
        """safeer-os in safeer-browser (.deb) zahtevata safeer-webkit iz iste izdaje (od 19. 10. 2026): program ga prenese
        in namesti v istem apt-get, sicer posodobitev pade (apt-get odvisnosti ne razresi). Seznam za razlicice do 1.0.126
        ga nosi tudi kot "tema_deb" (te ga tako ze namestijo) - novejsi program ga ne prenese dvakrat."""
        webkit = {"url": "https://github.com/x/safeer-webkit_1.0.127_amd64.deb", "sha256": "1" * 64, "velikost": 9}
        m = json.loads(json.dumps(MANIFEST))
        m["linux"]["safeer-os"]["webkit_deb"] = webkit
        m["linux"]["safeer-os"]["tema_deb"] = webkit
        m["linux"]["safeer-browser"] = {"razlicica": "1.0.127", "webkit_deb": webkit,
                                        "deb": {"url": "https://github.com/x/safeer-browser_1.0.127_amd64.deb", "sha256": "2" * 64}}
        n = op.preveri("linux", {"safeer-os": "0.4.22"}, m, nacin="deb")["nove"][0]
        self.assertEqual(n["webkit"], webkit)
        self.assertEqual([d["url"].rsplit("/", 1)[1] for d in op.datoteke_namestitve(n)],
                         ["safeer-os_0.4.23_all.deb", "safeer-webkit_1.0.127_amd64.deb"])
        b = op.preveri("linux", {"safeer-browser": "1.0.126"}, m, nacin="deb")["nove"][0]
        self.assertEqual([d["url"].rsplit("/", 1)[1] for d in op.datoteke_namestitve(b)],
                         ["safeer-browser_1.0.127_amd64.deb", "safeer-webkit_1.0.127_amd64.deb"])
        # Brez veljavnega vnosa WebKita nic napol (samo stran).
        m["linux"]["safeer-os"]["webkit_deb"] = dict(webkit, sha256="")
        self.assertIsNone(op.preveri("linux", {"safeer-os": "0.4.22"}, m, nacin="deb")["nove"][0]["datoteka"])
        # Flatpak in AppImage imata svoj WebKit; Flatpak z .deb (sistemski deli) dobi safeer-webkit ob .deb.
        m["linux"]["safeer-os"]["webkit_deb"] = webkit
        for nacin in ("flatpak", "appimage"):
            self.assertNotIn("webkit", op.preveri("linux", {"safeer-os": "0.4.22"}, m, nacin=nacin)["nove"][0], nacin)
        h = op.preveri("linux", {"safeer-os": "0.4.22"}, m, nacin="flatpak+deb")["nove"][0]
        self.assertEqual([d["url"].rsplit("/", 1)[1] for d in op.datoteke_namestitve(h)],
                         ["Safeer-OS-0.4.23-x86_64.flatpak", "safeer-os_0.4.23_all.deb", "safeer-webkit_1.0.127_amd64.deb"])
        # Seznam brez polja (pred to izdajo): kot prej.
        n = op.preveri("linux", {"safeer-os": "0.4.22"}, MANIFEST, nacin="deb")["nove"][0]
        self.assertNotIn("webkit", n)
        self.assertEqual(len(op.datoteke_namestitve(n)), 2)

    def test_posodobitev_uporabi_vse_datoteke(self):
        """Safeer OS in Safeer Control preneseta datoteke iz op.datoteke_namestitve (program, videz, .deb, WebKit)."""
        koren = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        imena = [i for i in ("safeer_os.py", "safeer_control.py") if os.path.isfile(os.path.join(koren, i))]
        if not imena:
            self.skipTest("zaganjalnika Linux nista v tem repozitoriju (Safeer-windows; preizkus je skupen z Linuxom)")
        for ime in imena:
            with open(os.path.join(koren, ime), encoding="utf-8") as f:
                vir = f.read()
            self.assertIn("for d in os_posodobitve.datoteke_namestitve(n):", vir, ime)
            self.assertNotIn('[n["datoteka"]] + (', vir, ime)


@unittest.skipIf(Ed25519PrivateKey is None, "brez python3-cryptography")
class Podpis(unittest.TestCase):
    def setUp(self):
        self.k, self.javni = _kljuc()
        self.kljuci = {"preizkus": self.javni}
        self.podatki = json.dumps(MANIFEST, ensure_ascii=False, indent=1).encode("utf-8") + b"\n"

    def test_veljaven_podpis(self):
        op.preveri_podpis(self.podatki, _podpis(self.k, self.podatki), self.kljuci)

    def test_spremenjen_seznam_zavrne(self):
        sig = _podpis(self.k, self.podatki)
        drugi = self.podatki.replace(b"a" * 64, b"9" * 64, 1)
        self.assertNotEqual(drugi, self.podatki)
        with self.assertRaises(op.NapakaPodpisa):
            op.preveri_podpis(drugi, sig, self.kljuci)

    def test_tuj_kljuc_z_istim_imenom_zavrne(self):
        tuj, _ = _kljuc()
        with self.assertRaises(op.NapakaPodpisa):
            op.preveri_podpis(self.podatki, _podpis(tuj, self.podatki), self.kljuci)

    def test_neznan_kljuc_zavrne(self):
        with self.assertRaises(op.NapakaPodpisa):
            op.preveri_podpis(self.podatki, _podpis(self.k, self.podatki, kljuc_id="drug"), self.kljuci)

    def test_podpis_seznamov_grozenj_ne_velja_za_razlicice(self):
        """Locena domena: podpis z drugim kontekstom (manifest seznamov grozenj) tudi z zaupanja vrednim kljucem ne velja."""
        with self.assertRaises(op.NapakaPodpisa):
            op.preveri_podpis(self.podatki, _podpis(self.k, self.podatki, kontekst=signed_feed.MANIFEST_CONTEXT), self.kljuci)
        with self.assertRaises(op.NapakaPodpisa):
            op.preveri_podpis(self.podatki, _podpis(self.k, self.podatki, kontekst=b""), self.kljuci)

    def test_pokvarjen_podpis_zavrne(self):
        for slab in (b"", b"{}", b"[]", b"ni json", b"[{}]", b'[{"alg": "ed25519", "key_id": "preizkus", "sig": "AAAA"}]',
                     b"\xff\xfe", json.dumps({"alg": "ed25519", "key_id": "preizkus", "sig": "x"}).encode()):
            with self.assertRaises(op.NapakaPodpisa, msg=slab):
                op.preveri_podpis(self.podatki, slab, self.kljuci)

    def test_eden_od_vec_podpisov_zadostuje(self):
        """Menjava kljuca: seznam je lahko podpisan s starim in novim kljucem; velja, ce je vsaj en podpis nas."""
        tuj, _ = _kljuc()
        dva = json.loads(_podpis(tuj, self.podatki, kljuc_id="drug")) + json.loads(_podpis(self.k, self.podatki))
        op.preveri_podpis(self.podatki, json.dumps(dva).encode(), self.kljuci)

    def test_vgrajen_kljuc(self):
        self.assertIn("safeer-razlicice-2026-10", op.KLJUCI)
        for javni in op.KLJUCI.values():
            self.assertEqual(len(base64.b64decode(javni, validate=True)), 32)


@unittest.skipIf(Ed25519PrivateKey is None, "brez python3-cryptography")
class PrenosSeznama(unittest.TestCase):
    def setUp(self):
        self.k, javni = _kljuc()
        self.kljuci = {"preizkus": javni}
        self.mapa = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.mapa, "os"))
        self.podatki = json.dumps(_svez_manifest(), ensure_ascii=False, indent=1).encode("utf-8") + b"\n"
        self._zapisi("os/razlicice.json", self.podatki)
        self._zapisi("os/razlicice.json.sig", _podpis(self.k, self.podatki))
        self.st = _Streznik(self.mapa)
        p = mock.patch.object(op, "_LOKALNI_HTTP", True)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.st.ustavi)
        s = mock.patch.dict(os.environ, {"SAFEER_POSODOBITVE_STANJE": os.path.join(self.mapa, "posodobitve.json")})
        s.start()
        self.addCleanup(s.stop)

    def _zapisi(self, ime: str, vsebina: bytes) -> None:
        with open(os.path.join(self.mapa, ime), "wb") as f:
            f.write(vsebina)

    def test_podpisan_seznam_se_prebere(self):
        m = op.prenesi_manifest(self.st.url("/os/razlicice.json"), kljuci=self.kljuci)
        self.assertEqual(m["linux"]["safeer-os"]["razlicica"], "0.4.23")
        self.assertEqual(self.st.zahteve, ["/os/razlicice.json", "/os/razlicice.json.sig"])

    def test_privzeti_kljuci_ne_sprejmejo_preizkusnega_podpisa(self):
        with self.assertRaises(op.NapakaPodpisa):
            op.prenesi_manifest(self.st.url("/os/razlicice.json"))

    def test_brez_podpisa_zavrne(self):
        os.remove(os.path.join(self.mapa, "os/razlicice.json.sig"))
        with self.assertRaises(op.NapakaPodpisa) as e:
            op.prenesi_manifest(self.st.url("/os/razlicice.json"), kljuci=self.kljuci)
        self.assertIn("manjka", str(e.exception))

    def test_zamenjan_seznam_zavrne(self):
        """Kdor zamenja seznam (in v njem SHA-256), brez zasebnega kljuca ne more narediti veljavnega podpisa."""
        ponarejen = self.podatki.replace(b"a" * 64, b"1" * 64, 1)
        self._zapisi("os/razlicice.json", ponarejen)
        with self.assertRaises(op.NapakaPodpisa):
            op.prenesi_manifest(self.st.url("/os/razlicice.json"), kljuci=self.kljuci)

    def test_preusmeritev_na_drugega_gostitelja_zavrne(self):
        self.st.preusmeritve["/os/razlicice.json"] = self.st.url("/os/drugi.json", gostitelj="localhost")
        self._zapisi("os/drugi.json", self.podatki)
        with self.assertRaises(Exception):
            op.prenesi_manifest(self.st.url("/os/razlicice.json"), kljuci=self.kljuci)
        self.assertNotIn("/os/drugi.json", self.st.zahteve)

    def test_preusmeritev_na_istega_gostitelja_dovoli(self):
        self.st.preusmeritve["/os/star.json"] = "/os/razlicice.json"
        m = op.prenesi_manifest(self.st.url("/os/star.json"), kljuci=self.kljuci)
        self.assertIn("linux", m)

    def test_preusmeritev_na_file_zavrne(self):
        self.st.preusmeritve["/os/razlicice.json"] = "file:///etc/hostname"
        with self.assertRaises(Exception):
            op.prenesi_manifest(self.st.url("/os/razlicice.json"), kljuci=self.kljuci)

    def test_http_v_izdaji_zavrne_brez_zahteve(self):
        """V izdaji (brez preizkusnega nacina) se naslov, ki ni https, sploh ne odpre."""
        with mock.patch.object(op, "_LOKALNI_HTTP", False):
            with self.assertRaises(ValueError):
                op.prenesi_manifest(self.st.url("/os/razlicice.json"), kljuci=self.kljuci)
        self.assertEqual(self.st.zahteve, [])

    def test_file_in_drugi_naslovi_zavrne(self):
        for url in ("file:///etc/hostname", "ftp://127.0.0.1/os/razlicice.json", "data:,{}", "http://192.0.2.1/os/razlicice.json",
                    "https:///os/razlicice.json", "/os/razlicice.json"):
            with self.assertRaises(ValueError, msg=url):
                op.prenesi_manifest(url, kljuci=self.kljuci)

    def test_prevelik_seznam_zavrne(self):
        self._zapisi("os/razlicice.json", b" " * (op.NAJVEC_SEZNAM + 1))
        with self.assertRaises(ValueError):
            op.prenesi_manifest(self.st.url("/os/razlicice.json"), kljuci=self.kljuci)


    def test_pretekel_seznam_zavrne(self):
        """Pretekel seznam (potece v preteklosti) se zavrne, tudi ce je pravilno podpisan."""
        pretekel = _svez_manifest("2020-01-01T00:00:00Z", "2020-02-01T00:00:00Z")
        p = json.dumps(pretekel, ensure_ascii=False, indent=1).encode("utf-8") + b"\n"
        self._zapisi("os/razlicice.json", p)
        self._zapisi("os/razlicice.json.sig", _podpis(self.k, p))
        with self.assertRaises(op.NapakaSvezine):
            op.prenesi_manifest(self.st.url("/os/razlicice.json"), kljuci=self.kljuci)

    def test_brez_svezine_zavrne(self):
        """Pristno podpisan STAR seznam brez polj izdano/potece (napad s ponovitvijo) se zavrne."""
        p = json.dumps(MANIFEST, ensure_ascii=False, indent=1).encode("utf-8") + b"\n"
        self._zapisi("os/razlicice.json", p)
        self._zapisi("os/razlicice.json.sig", _podpis(self.k, p))
        with self.assertRaises(op.NapakaSvezine):
            op.prenesi_manifest(self.st.url("/os/razlicice.json"), kljuci=self.kljuci)

    def test_anti_rollback_zavrne_starejso_izdajo(self):
        """Ko smo ze videli novejsi seznam, se pristno podpisan STAREJSI (ponovljen) zavrne."""
        sveze = _svez_manifest("2026-09-01T00:00:00Z", "2030-01-01T00:00:00Z")
        ps = json.dumps(sveze, ensure_ascii=False, indent=1).encode("utf-8") + b"\n"
        self._zapisi("os/razlicice.json", ps)
        self._zapisi("os/razlicice.json.sig", _podpis(self.k, ps))
        op.prenesi_manifest(self.st.url("/os/razlicice.json"), kljuci=self.kljuci)
        stara = _svez_manifest("2026-05-01T00:00:00Z", "2030-01-01T00:00:00Z")
        pst = json.dumps(stara, ensure_ascii=False, indent=1).encode("utf-8") + b"\n"
        self._zapisi("os/razlicice.json", pst)
        self._zapisi("os/razlicice.json.sig", _podpis(self.k, pst))
        with self.assertRaises(op.NapakaSvezine):
            op.prenesi_manifest(self.st.url("/os/razlicice.json"), kljuci=self.kljuci)


class Svezina(unittest.TestCase):
    """Cista pravila svezine/anti-rollback (brez omrezja)."""

    def test_svez_sprejet(self):
        m = {"izdano": "2026-10-01T00:00:00Z", "potece": "2026-12-01T00:00:00Z"}
        zdaj = datetime(2026, 10, 15, tzinfo=timezone.utc)
        self.assertEqual(op.preveri_svezino(m, "", zdaj), "2026-10-01T00:00:00Z")

    def test_pretekel_zavrnjen(self):
        m = {"izdano": "2026-01-01T00:00:00Z", "potece": "2026-02-01T00:00:00Z"}
        with self.assertRaises(op.NapakaSvezine):
            op.preveri_svezino(m, "", datetime(2026, 10, 1, tzinfo=timezone.utc))

    def test_starejsi_od_videnega_zavrnjen(self):
        m = {"izdano": "2026-05-01T00:00:00Z", "potece": "2026-12-01T00:00:00Z"}
        with self.assertRaises(op.NapakaSvezine):
            op.preveri_svezino(m, "2026-09-01T00:00:00Z", datetime(2026, 10, 1, tzinfo=timezone.utc))

    def test_enak_izdano_sprejet(self):
        m = {"izdano": "2026-09-01T00:00:00Z", "potece": "2026-12-01T00:00:00Z"}
        zdaj = datetime(2026, 10, 1, tzinfo=timezone.utc)
        self.assertEqual(op.preveri_svezino(m, "2026-09-01T00:00:00Z", zdaj), "2026-09-01T00:00:00Z")

    def test_brez_polj_ali_slab_cas_zavrnjen(self):
        zdaj = datetime(2026, 10, 10, tzinfo=timezone.utc)
        for m in ({}, {"izdano": "2026-10-01T00:00:00Z"}, {"potece": "2026-12-01T00:00:00Z"},
                  {"izdano": "ni cas", "potece": "2026-12-01T00:00:00Z"},
                  {"izdano": "2026-10-01T00:00:00Z", "potece": "2026-10-01"},
                  {"izdano": "2026-10-01T00:00:00Z", "potece": "2026-10-01T00:00:00Z"}):
            with self.assertRaises(op.NapakaSvezine, msg=repr(m)):
                op.preveri_svezino(m, "", zdaj)


class Prenos(unittest.TestCase):
    def setUp(self):
        self.mapa = tempfile.mkdtemp()
        self.vsebina = os.urandom(200_000)
        self.sha = hashlib.sha256(self.vsebina).hexdigest()
        with open(os.path.join(self.mapa, "paket.deb"), "wb") as f:
            f.write(self.vsebina)
        self.st = _Streznik(self.mapa)
        self.vrata = self.st.vrata
        p = mock.patch.object(op, "_LOKALNI_HTTP", True)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.st.ustavi)

    def test_prenos_sha_in_napredek(self):
        cilj = os.path.join(self.mapa, "dol", "paket.deb")
        napredki = []
        pot = op.prenesi(f"http://127.0.0.1:{self.vrata}/paket.deb", cilj, self.sha, len(self.vsebina),
                         napredek=lambda a, b: napredki.append((a, b)))
        self.assertEqual(pot, cilj)
        with open(cilj, "rb") as f:
            self.assertEqual(f.read(), self.vsebina)
        self.assertEqual(napredki[-1], (len(self.vsebina), len(self.vsebina)))
        self.assertFalse(os.path.exists(cilj + ".del"))

    def test_velike_crke_v_vsoti(self):
        cilj = os.path.join(self.mapa, "dol", "paket1.deb")
        self.assertEqual(op.prenesi(f"http://127.0.0.1:{self.vrata}/paket.deb", cilj, self.sha.upper()), cilj)

    def test_napacna_vsota_zavrze(self):
        cilj = os.path.join(self.mapa, "dol", "paket2.deb")
        with self.assertRaises(ValueError):
            op.prenesi(f"http://127.0.0.1:{self.vrata}/paket.deb", cilj, "0" * 64)
        self.assertFalse(os.path.exists(cilj))
        self.assertFalse(os.path.exists(cilj + ".del"))

    def test_brez_veljavne_vsote_ni_prenosa(self):
        """Prazen ali ne-64-mestni SHA-256 ne izklopi preverjanja: prenos se sploh ne zacne."""
        for slaba in ("", None, "abc", "a" * 63, "g" * 64, " " + "a" * 63):
            cilj = os.path.join(self.mapa, "dol", "paket6.deb")
            with self.assertRaises(ValueError, msg=repr(slaba)):
                op.prenesi(f"http://127.0.0.1:{self.vrata}/paket.deb", cilj, slaba)
            self.assertFalse(os.path.exists(cilj))
        self.assertEqual(self.st.zahteve, [])

    def test_naslov_ki_ni_https_v_izdaji_zavrne(self):
        cilj = os.path.join(self.mapa, "dol", "paket7.deb")
        with mock.patch.object(op, "_LOKALNI_HTTP", False):
            for url in (f"http://127.0.0.1:{self.vrata}/paket.deb", "file://" + os.path.join(self.mapa, "paket.deb")):
                with self.assertRaises(ValueError, msg=url):
                    op.prenesi(url, cilj, self.sha)
        self.assertEqual(self.st.zahteve, [])
        self.assertFalse(os.path.exists(cilj))

    def test_preusmeritev_na_file_ali_tuj_http_zavrne(self):
        """Po preusmeritvi velja isto pravilo: nikoli file:, nikoli navaden http drugam (v izdaji samo https)."""
        for i, cilj_preusm in enumerate(("file://" + os.path.join(self.mapa, "paket.deb"), "http://192.0.2.1/paket.deb")):
            self.st.preusmeritve[f"/p{i}.deb"] = cilj_preusm
            cilj = os.path.join(self.mapa, "dol", f"paket8-{i}.deb")
            with self.assertRaises(Exception, msg=cilj_preusm):
                op.prenesi(f"http://127.0.0.1:{self.vrata}/p{i}.deb", cilj, self.sha)
            self.assertFalse(os.path.exists(cilj))
            self.assertFalse(os.path.exists(cilj + ".del"))

    def test_preusmeritev_na_drug_streznik_dovoli(self):
        """Paketi z GitHuba se prenesejo z drugega gostitelja (CDN); celovitost zagotavlja podpisan SHA-256."""
        self.st.preusmeritve["/gh/paket.deb"] = f"http://localhost:{self.vrata}/paket.deb"
        cilj = os.path.join(self.mapa, "dol", "paket9.deb")
        self.assertEqual(op.prenesi(f"http://127.0.0.1:{self.vrata}/gh/paket.deb", cilj, self.sha), cilj)

    def test_prekinitev(self):
        cilj = os.path.join(self.mapa, "dol", "paket3.deb")
        with self.assertRaises(InterruptedError):
            op.prenesi(f"http://127.0.0.1:{self.vrata}/paket.deb", cilj, self.sha, prekini=lambda: True)
        self.assertFalse(os.path.exists(cilj))
        self.assertFalse(os.path.exists(cilj + ".del"), "preklican prenos je pustil delno datoteko")

    def test_prekinitev_sredi_prenosa_ne_pusti_delne_datoteke(self):
        cilj = os.path.join(self.mapa, "dol", "paket4.deb")
        prebrano = []

        def prekini():
            return len(prebrano) >= 2

        with self.assertRaises(InterruptedError):
            op.prenesi(f"http://127.0.0.1:{self.vrata}/paket.deb", cilj, self.sha, napredek=lambda a, b: prebrano.append(a), prekini=prekini)
        self.assertGreater(prebrano[-1], 0)
        self.assertEqual(os.listdir(os.path.dirname(cilj)), [])

    def test_napaka_povezave_ne_pusti_delne_datoteke(self):
        cilj = os.path.join(self.mapa, "dol", "paket5.deb")
        with self.assertRaises(Exception):
            op.prenesi(f"http://127.0.0.1:{self.vrata}/ni-je.deb", cilj, self.sha)
        self.assertEqual(os.listdir(os.path.dirname(cilj)), [])

    def test_appimage_zamenja_samega_sebe(self):
        star = os.path.join(self.mapa, "Safeer-OS-0.4.22-x86_64.AppImage")
        nov = os.path.join(self.mapa, "dol", "Safeer-OS-0.4.23-x86_64.AppImage")
        os.makedirs(os.path.dirname(nov))
        open(star, "wb").write(b"star")
        open(nov, "wb").write(b"nov")
        os.environ["APPIMAGE"] = star
        try:
            r = op.namesti_linux("appimage", [nov])
        finally:
            del os.environ["APPIMAGE"]
        self.assertEqual(r.returncode, 0)
        # ista pot kot prej (bliznjice ostanejo), vsebina nova, izvedljiva
        self.assertTrue(os.access(star, os.X_OK))
        with open(star, "rb") as f:
            self.assertEqual(f.read(), b"nov")
        self.assertFalse(os.path.exists(nov))

    def test_posodabljanje_stanje(self):
        p = op.Posodabljanje()
        self.assertFalse(p.tece())
        konec = threading.Event()

        def delo(x):
            x.odstotek = 50
            konec.wait(5)
        self.assertTrue(p.zacni(delo))
        self.assertFalse(p.zacni(delo))
        self.assertTrue(p.stanje()["tece"])
        konec.set()
        p.nit.join(5)
        self.assertEqual(p.stanje()["faza"], "koncano")

        def pade(x):
            raise ValueError("ni")
        p.zacni(pade)
        p.nit.join(5)
        self.assertEqual((p.faza, p.sporocilo), ("napaka", "ni"))


class Namestitev(unittest.TestCase):
    A, B = "a" * 64, "b" * 64

    def test_deb_brez_znizanja_razlicice(self):
        """Posodobitev nikoli ne namesti starejse razlicice (brez --allow-downgrades)."""
        with mock.patch.object(op.subprocess, "run", return_value=op.subprocess.CompletedProcess([], 0, "", "")) as run:
            op.namesti_linux("deb", ["/tmp/a.deb", "/tmp/b.deb"], [self.A, self.B])
        argv = run.call_args[0][0]
        self.assertEqual(argv, ["/usr/bin/pkexec", "/bin/sh", "-c", op.NAMESTI_DEB_KOT_ROOT, "safeer-posodobitev",
                                self.A, "/tmp/a.deb", self.B, "/tmp/b.deb"])
        self.assertNotIn("--allow-downgrades", " ".join(argv))

    def test_deb_samo_z_vsotami_iz_seznama(self):
        """Brez SHA-256 iz podpisanega seznama (ali z neveljavno) se root sploh ne vprasa."""
        with mock.patch.object(op.subprocess, "run") as run:
            for vsote in (None, [self.A], ["ni-vsota"], [self.A, "x" * 64]):
                with self.assertRaises(ValueError):
                    op.namesti_linux("deb", ["/tmp/a.deb", "/tmp/b.deb"], vsote)
        run.assert_not_called()

    def _root_skripta(self, vsebina: bytes, vsota: str):
        """NAMESTI_DEB_KOT_ROOT z laznim apt-get (zapise, katere poti in vsebine je dobil); vrne (izhod, klic apt)."""
        d = tempfile.mkdtemp(prefix="safeer-root-namestitev-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)     # vsak preizkus za sabo pospravi (AGENTS.md)
        paket = os.path.join(d, "safeer-os_9.9.9_amd64.deb")
        with open(paket, "wb") as f:
            f.write(vsebina)
        bin_ = os.path.join(d, "bin")
        os.mkdir(bin_)
        zapis = os.path.join(d, "apt.txt")
        with open(os.path.join(bin_, "apt-get"), "w") as f:
            # Lazni apt najprej (kot napadalec, ki tece kot uporabnik) prepise uporabnikovo datoteko, nato prebere,
            # kar je dobil: namesti se mora preverjena kopija, ne prepisana datoteka.
            f.write('#!/bin/sh\nprintf podtaknjeno > "%s"\nfor a in "$@"; do case "$a" in /*) '
                    'printf "%%s %%s\\n" "$a" "$(sha256sum < "$a" | cut -c1-64)" >> "%s";; esac; done\n' % (paket, zapis))
        os.chmod(os.path.join(bin_, "apt-get"), 0o755)
        okolje = dict(os.environ, PATH=bin_ + os.pathsep + os.environ.get("PATH", ""))
        r = op.subprocess.run(["/bin/sh", "-c", op.NAMESTI_DEB_KOT_ROOT, "safeer-posodobitev", vsota, paket],
                              env=okolje, capture_output=True, text=True, timeout=30)
        klic = open(zapis).read().split() if os.path.exists(zapis) else []
        return r, klic, paket

    def test_root_namesti_preverjeno_kopijo(self):
        """Neodvisni pregled 19. 10. 2026: apt-get ne sme brati datoteke v ~/.cache (uporabnik bi jo zamenjal po
        preverbi in po vpisanem geslu). Root jo prekopira k sebi, preveri SHA-256 kopije in namesti kopijo."""
        vsebina = b"pravi paket"
        r, klic, paket = self._root_skripta(vsebina, hashlib.sha256(vsebina).hexdigest())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(klic), 2, klic)
        self.assertNotEqual(klic[0], paket, "apt-get ne bere uporabnikove datoteke")
        self.assertEqual(klic[1], hashlib.sha256(vsebina).hexdigest(), "namescena vsebina je preverjena kopija")
        self.assertFalse(os.path.exists(klic[0]), "kopija se po namestitvi pospravi")

    def test_root_zavrne_napacno_vsoto(self):
        r, klic, _ = self._root_skripta(b"podtaknjen paket", hashlib.sha256(b"pravi paket").hexdigest())
        self.assertEqual(r.returncode, 3)
        self.assertIn("SHA-256 se ne ujema", r.stderr)
        self.assertEqual(klic, [], "apt-get se ne zazene")

    def test_root_ne_bere_povezave_ali_fifo(self):
        """Pregled 19. 10. 2026: podtaknjena povezava (npr. na /dev/zero - poln disk) ali FIFO (root caka do roka)
        mora takoj pasti, apt-get se ne zazene."""
        import time
        for vrsta in ("povezava", "fifo"):
            d = tempfile.mkdtemp(prefix="safeer-root-podtaknjeno-")
            try:
                paket = os.path.join(d, "safeer-os_9.9.9_amd64.deb")
                if vrsta == "povezava":
                    os.symlink("/dev/zero", paket)
                else:
                    os.mkfifo(paket)
                bin_ = os.path.join(d, "bin")
                os.mkdir(bin_)
                with open(os.path.join(bin_, "apt-get"), "w") as f:
                    f.write('#!/bin/sh\ntouch "%s"\n' % os.path.join(d, "apt-klican"))
                os.chmod(os.path.join(bin_, "apt-get"), 0o755)
                okolje = dict(os.environ, PATH=bin_ + os.pathsep + os.environ.get("PATH", ""))
                zacetek = time.monotonic()
                r = op.subprocess.run(["/bin/sh", "-c", op.NAMESTI_DEB_KOT_ROOT, "safeer-posodobitev", "a" * 64, paket],
                                      capture_output=True, text=True, timeout=60, env=okolje)
                self.assertEqual(r.returncode, 2, (vrsta, r.stderr))
                self.assertLess(time.monotonic() - zacetek, 10, vrsta)
                self.assertFalse(os.path.exists(os.path.join(d, "apt-klican")), vrsta)
            finally:
                shutil.rmtree(d, ignore_errors=True)

    def test_v_izdaji_ni_lokalnega_http(self):
        self.assertFalse(op._LOKALNI_HTTP)
        self.assertTrue(op.MANIFEST.startswith("https://") or os.environ.get("SAFEER_MANIFEST_URL"))


if __name__ == "__main__":
    unittest.main()
