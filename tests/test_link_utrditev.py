"""Utrditev povezave s Hubom: prebuditev po spanju racunalnika in po menjavi omrezja.

Zakaj: ob spanju (zaprt pokrov, pripravljenost) in ob menjavi omrezja vticnica ni zaprta, le
mrtva. Pisanje se zatakne, branje caka do BRALNI_TIMEOUT (70 s), zato je racunalnik za druge
naprave se cel ta cas videti prisoten, a ne odgovarja. Povezava mora to opaziti sama in se
vrniti takoj, ne sele po utripu in zamiku.
"""
import threading
import time
import unittest

from core import link_hub


class LazniOdjemalec:
    """Vticnica, ki je ni mogoce prekiniti od zunaj - tako se obnasa mrtva povezava."""

    def __init__(self, naslov="10.0.0.5"):
        self.zaprt = False
        self.poslano = []
        self._naslov = naslov

    class _Vticnik:
        def __init__(self, naslov):
            self._naslov = naslov

        def getsockname(self):
            return (self._naslov, 12345)

    @property
    def vticnik(self):
        return None if self.zaprt else self._Vticnik(self._naslov)

    def ping(self):
        return not self.zaprt

    def poslji(self, besedilo):
        self.poslano.append(besedilo)

    def zapri(self):
        self.zaprt = True


def _povezava():
    p = link_hub.Povezava("wss://primer/cast", "zeton", "n-test", "Test", odtis="ab" * 32)
    return p


class Prebuditev(unittest.TestCase):
    def test_prebudi_zapre_mrtvo_vticnico_in_sprosti_zanko(self):
        p = _povezava()
        o = LazniOdjemalec()
        p.odjemalec = o
        p.tece = True
        p.prebudi("preizkus")
        self.assertTrue(o.zaprt, "mrtvo vticnico moramo zapreti sami")
        self.assertIsNone(p.odjemalec)
        self.assertFalse(p.tece)
        self.assertEqual(p._cakaj_na_poskus(5.0), "prebudi")
        # Dogodek se porabi enkrat: naslednje cakanje gre do poteka.
        self.assertEqual(p._cakaj_na_poskus(0.3), "potek")

    def test_zaprtje_je_mocnejse_od_prebuditve(self):
        p = _povezava()
        p.prebudi("preizkus")
        p.zapri()
        self.assertEqual(p._cakaj_na_poskus(5.0), "zaprto")

    def test_prebuditev_po_zaprtju_ne_naredi_nicesar(self):
        p = _povezava()
        p.zapri()
        p.prebudi("prepozno")
        self.assertEqual(p._cakaj_na_poskus(0.3), "zaprto")

    def test_utrip_ne_poje_prebuditve(self):
        """Utrip in zanka cakata hkrati; prebuditev mora priti do zanke."""
        p = _povezava()
        p.odjemalec = LazniOdjemalec()
        p.tece = True
        izidi = []
        nit_utripa = threading.Thread(target=lambda: izidi.append(("utrip", p._cakaj(1.5))), daemon=True)
        nit_zanke = threading.Thread(target=lambda: izidi.append(("zanka", p._cakaj_na_poskus(5.0))), daemon=True)
        nit_utripa.start()
        nit_zanke.start()
        time.sleep(0.3)
        p.prebudi("preizkus")
        nit_zanke.join(6)
        nit_utripa.join(3)
        self.assertIn(("zanka", "prebudi"), izidi, izidi)
        self.assertIn(("utrip", False), izidi, "utrip prebuditve ne sme pojesti")


class Straza(unittest.TestCase):
    """Straza v srcnem utripu: spanje racunalnika in menjava omrezja."""

    def _utrip_enkrat(self, p, zamik_ure: float, naslov: str):
        """Pozene srcni utrip toliko casa, da naredi en krog, z lazno uro in danim naslovom."""
        p.odjemalec.  __dict__["_naslov"] = naslov
        pravi_cas = time.time
        stanje = {"klici": 0}

        def lazni_cas():
            stanje["klici"] += 1
            # prvi klic = pred cakanjem, drugi = po cakanju (takrat pristejemo zamik)
            return pravi_cas() + (zamik_ure if stanje["klici"] > 1 else 0.0)

        link_hub.time.time = lazni_cas
        try:
            nit = threading.Thread(target=p._srcni_utrip, daemon=True)
            nit.start()
            time.sleep(0.6)
        finally:
            link_hub.time.time = pravi_cas
            p.zapri()
            nit.join(2)

    def test_spanje_racunalnika_sprozi_prebuditev(self):
        p = _povezava()
        p.odjemalec = LazniOdjemalec("10.0.0.5")
        p.tece = True
        link_hub.PING_VSAKIH, prej = 0.1, link_hub.PING_VSAKIH
        try:
            self._utrip_enkrat(p, zamik_ure=link_hub.SKOK_UTRIPA + 5, naslov="10.0.0.5")
        finally:
            link_hub.PING_VSAKIH = prej
        self.assertIsNone(p.odjemalec, "po spanju moramo vticnico zapreti in se povezati znova")

    def test_menjava_omrezja_sprozi_prebuditev(self):
        p = _povezava()
        o = LazniOdjemalec("192.168.0.20")
        p.odjemalec = o
        p.tece = True
        prej = link_hub.PING_VSAKIH
        link_hub.PING_VSAKIH = 0.1
        try:
            nit = threading.Thread(target=p._srcni_utrip, daemon=True)
            nit.start()
            time.sleep(0.3)
            o._naslov = "10.42.0.7"          # racunalnik je presel na drugo omrezje
            time.sleep(0.6)
        finally:
            link_hub.PING_VSAKIH = prej
            p.zapri()
            nit.join(2)
        self.assertTrue(o.zaprt, "ob drugem omrezju moramo vticnico zapreti in se povezati znova")

    def test_mirno_stanje_ne_prebuja(self):
        """Brez spanja in brez menjave omrezja utrip samo pinga in nicesar ne zapira."""
        p = _povezava()
        o = LazniOdjemalec("192.168.0.20")
        p.odjemalec = o
        p.tece = True
        prej = link_hub.PING_VSAKIH
        link_hub.PING_VSAKIH = 0.1
        try:
            nit = threading.Thread(target=p._srcni_utrip, daemon=True)
            nit.start()
            time.sleep(0.8)
            # Preverimo, preden povezavo zapremo sami (zapri() vticnico seveda zapre).
            self.assertFalse(o.zaprt, "mirna povezava se ne sme zapirati")
            self.assertIs(p.odjemalec, o)
        finally:
            link_hub.PING_VSAKIH = prej
            p.zapri()
            nit.join(2)


if __name__ == "__main__":
    unittest.main()
