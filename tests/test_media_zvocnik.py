import os
import tempfile
import unittest

from core import media_zvocnik as mz


class Lazni:
    def __init__(self, stanje="STOPPED", uri=""):
        self.udn, self.ime, self.model, self.naslov = "uuid:jbl", "JBL BAR 300", "BAR 300", "192.168.0.229"
        self._stanje, self._uri, self.klici, self._glas = stanje, uri, [], 30

    def stanje(self): return self._stanje
    def polozaj(self): return {"TrackURI": self._uri}
    def predvajaj(self, url, naslov="", izvajalec="", mime=""): self.klici.append(("p", url, naslov, mime)); self._stanje = "PLAYING"
    def premor(self): self.klici.append(("premor",)); self._stanje = "PAUSED_PLAYBACK"
    def nadaljuj(self): self.klici.append(("nadaljuj",)); self._stanje = "PLAYING"
    def ustavi(self): self.klici.append(("ustavi",)); self._stanje = "STOPPED"
    def glasnost(self): return self._glas
    def nastavi_glasnost(self, v): self._glas = v


class LazniStreznik:
    odprti = []

    def __init__(self, pot, naslov):
        self.url = "http://%s:9/tok/%s" % (naslov, os.path.basename(pot)); self.zaprt = False

    def __enter__(self):
        LazniStreznik.odprti.append(self); return self

    def __exit__(self, *a):
        self.zaprt = True


class MediaZvocnikTest(unittest.TestCase):
    def _mz(self, z):
        m = mz.MediaZvocniki(najdi=lambda cas: [z], streznik=LazniStreznik, lan_naslov=lambda ip: "192.168.0.10")
        m.osvezi(pocakaj=True)
        return m

    def test_splet_radio(self):
        z = Lazni(); m = self._mz(z)
        self.assertEqual(m.seznam()[0]["id"], "uuid:jbl")
        r = m.predvajaj({"url": "https://stream.example/radio", "naslov": "Radio"}, "uuid:jbl")
        self.assertTrue(r["ok"])
        self.assertEqual(z.klici[0][1], "https://stream.example/radio")
        self.assertTrue(m.seznam()[0]["aktiven"])

    def test_lokalna_datoteka_prek_streznika(self):
        z = Lazni(); m = self._mz(z)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"ID3x")
        try:
            r = m.predvajaj({"url": "http://127.0.0.1:5000/d/1", "pot": f.name, "mime": "audio/mpeg"}, "uuid:jbl")
            self.assertTrue(r["ok"], r)
            self.assertTrue(z.klici[0][1].startswith("http://192.168.0.10:9/tok/"))
            m.dejanje("ustavi")
            self.assertTrue(LazniStreznik.odprti[-1].zaprt)
            self.assertIsNone(m.aktivni)
        finally:
            os.unlink(f.name)

    def test_zavrne_domaci_https_in_localhost_brez_datoteke(self):
        m = self._mz(Lazni())
        self.assertEqual(m.predvajaj({"url": "https://192.168.0.5:8443/x.mp3"}, "uuid:jbl")["napaka"], "vir_ni_za_zvocnik")
        self.assertEqual(m.predvajaj({"url": "http://127.0.0.1:5000/x"}, "uuid:jbl")["napaka"], "vir_ni_za_zvocnik")

    def test_tv_vir_potrebuje_potrditev(self):
        z = Lazni(stanje="PLAYING", uri="TV"); m = self._mz(z)
        r = m.predvajaj({"url": "https://x/radio"}, "uuid:jbl")
        self.assertEqual(r.get("vir"), "TV")
        self.assertEqual(z.klici, [])
        self.assertTrue(m.predvajaj({"url": "https://x/radio"}, "uuid:jbl", potrdi=True)["ok"])

    def test_dejanja(self):
        z = Lazni(); m = self._mz(z)
        m.predvajaj({"url": "https://x/r"}, "uuid:jbl")
        m.dejanje("premor"); self.assertEqual(z._stanje, "PAUSED_PLAYBACK")
        m.dejanje("premor"); self.assertEqual(z._stanje, "PLAYING")
        m.dejanje("tisje"); self.assertEqual(z._glas, 25)


if __name__ == "__main__":
    unittest.main()
