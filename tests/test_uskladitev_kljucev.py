"""secrets.sync na namizju - storitev (core/uskladitev_kljucev.py) z dvema napravama v istem procesu: povabilo brez
vrednosti, potrditev na obeh straneh, izmenjava kljucev, izbris, ozji krog, zascita, zavrnitev, starejsa razlicica,
razveljavitev in shramba (0600, brez vrednosti)."""
import json
import os
import stat
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import uskladitev_kljucev as U  # noqa: E402
from core import uskladitev_kljucev_pravila as P  # noqa: E402


class Vir:
    """Vrednosti naprave v pomnilniku (debrid in dodatek); `velja` = storitev je kljuc potrdila."""

    def __init__(self):
        self.vrednosti = {}
        self.neveljavni = set()
        self.pripravljenih = 0

    def ponudniki(self):
        return {"torbox", "realdebrid", "alldebrid"}

    def trenutne(self):
        return ({k: v for k, v in self.vrednosti.items() if k not in self.neveljavni},
                {k for k in self.vrednosti if k in self.neveljavni})

    def veljavna_vrednost(self, k, v):
        return v != "slab"

    def pripravi(self, z):
        self.pripravljenih += 1

        def shrani():
            if z.izbrisan:
                self.vrednosti.pop(z.kljuc, None)
            else:
                self.vrednosti[z.kljuc] = z.vrednost
            return True
        return shrani

    def obnovi(self, k, v):
        if v is None:
            self.vrednosti.pop(k, None)
        else:
            self.vrednosti[k] = v
        return True

    def preveri_nepreverjene(self):
        pass

    def gostitelj(self, v):
        return "primer.test"

    def ime_kljuca(self, k, v, g):
        return k


class Mreza:
    """Link med napravami v istem procesu: ukaz gre neposredno v prejmi() druge naprave."""

    def __init__(self):
        self.naprave = {}
        self.krog = {}              # id -> set id-jev v njegovem ozjem krogu
        self.zascita = True
        self.brez_zmoznosti = set()

    def link(self, ident):
        return Link(self, ident)


class Link:
    def __init__(self, mreza, ident):
        self.m, self.id = mreza, ident

    def jaz(self):
        return self.id

    def jedro(self, ident):
        return ident.split("-os")[0]

    def v_krogu(self, ident):
        return self.jedro(ident) in {self.jedro(x) for x in self.m.krog.get(self.id, set())}

    def naprave(self):
        return [{"id": i, "ime": i, "zmoznosti": [] if i in self.m.brez_zmoznosti else [P.ZMOZNOST]}
                for i in self.m.naprave if i != self.id]

    def ujema_zascito(self, ident, zascita):
        return self.jedro(ident) == zascita

    def zna_zascito(self, ident):
        return self.m.zascita

    def povezan(self):
        return True

    def ukaz(self, ident, dejanje, parametri, cas):
        if ident in self.m.brez_zmoznosti:
            return {"ok": False, "koda": "neznano_dejanje"}
        data = self.m.naprave[ident].prejmi(self.id, self.id, json.loads(json.dumps(parametri)),
                                            zascita=self.jedro(self.id))
        return {"ok": True, "data": data}


def pocakaj(pogoj, rok=3.0):
    konec = time.time() + rok
    while time.time() < konec:
        if pogoj():
            return True
        time.sleep(0.02)
    return pogoj()


class Storitev(unittest.TestCase):
    def setUp(self):
        self.mapa = tempfile.mkdtemp()
        self.m = Mreza()
        self.ura = [1_000_000]

    def naprava(self, ident):
        vir = Vir()
        u = U.Uskladitev(U.Shramba(os.path.join(self.mapa, ident + ".json")), vir, self.m.link(ident),
                         ura=lambda: self.ura[0])
        self.m.naprave[ident] = u
        return u, vir

    def krog(self, a, b):
        self.m.krog.setdefault(a, set()).add(b)
        self.m.krog.setdefault(b, set()).add(a)

    def test_povabilo_potrditev_izmenjava(self):
        pc, vir_pc = self.naprava("pc")
        tel, vir_tel = self.naprava("tel")
        self.krog("pc", "tel")
        vir_pc.vrednosti["debrid:torbox"] = "KLJUC-PC"
        vprasanja = []
        tel.ob_vprasanju = vprasanja.append
        self.assertEqual(pc.uskladi_zdaj(), 1)
        # Povabilo: telefon caka na potrditev in NE vidi vrednosti.
        self.assertEqual(len(vprasanja), 1)
        self.assertTrue(all(z.vrednost == "" for z in vprasanja[0].zapisi))
        self.assertEqual(pc.stanje_naprave("tel"), P.POVABLJENA)
        self.assertEqual(tel.stanje_naprave("pc"), P.CAKA)
        self.assertNotIn("debrid:torbox", vir_tel.vrednosti)
        # Uporabnik na telefonu potrdi -> telefon poslje svoje stanje; PC je telefon povabil, a ga mora potrditi tudi sam (U1).
        pc_vprasanja = []
        pc.ob_vprasanju = pc_vprasanja.append
        tel.potrdi("pc", True)
        self.assertTrue(pocakaj(lambda: tel.stanje_naprave("pc") == P.POTRJENA))
        self.assertTrue(pocakaj(lambda: len(pc_vprasanja) == 1))
        pc.potrdi("tel", True)
        self.assertTrue(pocakaj(lambda: pc.stanje_naprave("tel") == P.POTRJENA))
        # Zdaj gredo vrednosti: PC poslje kljuc, telefon ga uporabi.
        pc.uskladi_zdaj()
        self.assertTrue(pocakaj(lambda: vir_tel.vrednosti.get("debrid:torbox") == "KLJUC-PC"
                                and "debrid:torbox" in tel.shramba.meta()))
        # Telefon prejetega ne poslje naprej kot svojega (U2).
        meta_tel = tel.shramba.meta()
        self.assertEqual(meta_tel["debrid:torbox"].izvor, "pc")
        self.assertEqual(P.za_poslati(meta_tel, vir_tel.trenutne()[0], "tel"), [])
        # Izbris na PC gre v krog kot grob.
        del vir_pc.vrednosti["debrid:torbox"]
        self.ura[0] += 10
        pc.uskladi_zdaj()
        self.assertTrue(pocakaj(lambda: "debrid:torbox" not in vir_tel.vrednosti))

    def test_zunaj_kroga_nic(self):
        pc, vir_pc = self.naprava("pc")
        tuj, vir_tuj = self.naprava("tuj")
        self.m.krog["tuj"] = {"pc"}         # tuj misli, da je PC v njegovem krogu; PC tujca nima v svojem
        vir_pc.vrednosti["debrid:torbox"] = "KLJUC"
        self.assertEqual(pc.uskladi_zdaj(), 0, "naprava zunaj ozjega kroga ne dobi nicesar")
        odg = pc.prejmi("tuj", "tuj", {"v": 1, "items": [{"k": "debrid:torbox", "c": 5, "i": "tuj", "d": False, "v": "X"}]},
                        zascita="tuj")
        self.assertEqual(odg, {"accepted": False, "reason": "ni_krog"})
        self.assertEqual(vir_pc.vrednosti["debrid:torbox"], "KLJUC")

    def test_brez_zascite_zavrnjeno(self):
        pc, _ = self.naprava("pc")
        self.naprava("tel")
        self.krog("pc", "tel")
        self.assertEqual(pc.prejmi("tel", "tel", {"items": []}, zascita=""), {"accepted": False, "reason": "zascita"})
        self.assertEqual(pc.prejmi("tel", "tel", {"items": []}, zascita="drug"), {"accepted": False, "reason": "zascita"})
        self.m.zascita = False
        self.assertEqual(pc.uskladi_zdaj(), 0, "brez zascite od naprave do naprave se ne poslje")

    def test_zavrnitev_in_stara(self):
        pc, vir_pc = self.naprava("pc")
        tel, _ = self.naprava("tel")
        star, _ = self.naprava("star")
        self.krog("pc", "tel")
        self.krog("pc", "star")
        self.m.brez_zmoznosti.add("star")
        vir_pc.vrednosti["debrid:torbox"] = "K"
        pc.uskladi_zdaj()
        self.assertEqual(pc.stanje_naprave("star"), P.STARA)
        tel.potrdi("pc", False)
        self.assertEqual(tel.stanje_naprave("pc"), P.ZAVRNJENA)
        pc.uskladi_zdaj()
        self.assertEqual(pc.stanje_naprave("tel"), P.ZAVRNJENA)
        self.assertEqual(pc.uskladi_zdaj(), 0, "zavrnjena naprava ne dobi vec nicesar")

    def test_razveljavitev(self):
        pc, vir_pc = self.naprava("pc")
        tel, vir_tel = self.naprava("tel")
        self.krog("pc", "tel")
        for a, b in (("pc", "tel"), ("tel", "pc")):
            self.m.naprave[a]._zapomni(b, b, P.POTRJENA, True)
        vir_tel.vrednosti["debrid:torbox"] = "MOJ"
        tel.uskladi_zdaj()                          # telefon zapise svoj kljuc (uvoz) in ga poslje PC-ju
        self.assertTrue(pocakaj(lambda: "debrid:torbox" in pc.shramba.meta()))
        vir_pc.vrednosti["debrid:torbox"] = "NOV"
        self.ura[0] += 1000
        spremembe = []
        tel.ob_spremembi = spremembe.append
        pc.uskladi_zdaj()
        self.assertTrue(pocakaj(lambda: vir_tel.vrednosti.get("debrid:torbox") == "NOV"))
        self.assertTrue(pocakaj(lambda: len(spremembe) == 1))
        self.assertEqual(spremembe[0].prejsnje, {"debrid:torbox": "MOJ"})
        tel.potrdi_spremembo(spremembe[0], razveljavi=True)
        self.assertTrue(pocakaj(lambda: vir_tel.vrednosti.get("debrid:torbox") == "MOJ"))

    def test_shramba_brez_vrednosti_in_0600(self):
        pc, vir_pc = self.naprava("pc")
        self.naprava("tel")
        self.krog("pc", "tel")
        vir_pc.vrednosti["debrid:torbox"] = "SKRIVNI-KLJUC-123"
        pc.uskladi_zdaj()
        pot = os.path.join(self.mapa, "pc.json")
        with open(pot, encoding="utf-8") as f:
            besedilo = f.read()
        self.assertNotIn("SKRIVNI-KLJUC-123", besedilo)
        self.assertEqual(stat.S_IMODE(os.stat(pot).st_mode), 0o600)
        self.assertEqual(pc.shramba.meta()["debrid:torbox"].cas, P.CAS_UVOZA, "prvi zagon: uvoz s casom 1")

    def test_izklopljeno(self):
        pc, vir_pc = self.naprava("pc")
        self.naprava("tel")
        self.krog("pc", "tel")
        pc.nastavi_vklopljeno(False)
        vir_pc.vrednosti["debrid:torbox"] = "K"
        self.assertEqual(pc.uskladi_zdaj(), 0)
        self.assertEqual(pc.prejmi("tel", "tel", {"items": []}, zascita="tel"), {"accepted": False, "reason": "izklopljeno"})


if __name__ == "__main__":
    unittest.main()
