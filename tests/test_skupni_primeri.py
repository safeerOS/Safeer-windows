"""Naloga 134: skupni preizkusni primeri za Safeer OS Android (tests/SkupniPrimeriTest.kt) in namizje (ta datoteka).

Datoteka tests/skupni-primeri/debrid-serije.json je ista v repozitorijih Android-tv, Safeer-linux in Safeer-windows:
pravilo, spremenjeno samo na eni strani, tu ali tam pade. null v primeru = ni vrednosti (None ali prazen niz).
"""
import json
import unittest
from pathlib import Path

from core import debrid_pravila as P, media_servers

PRIMERI = Path(__file__).resolve().parent / "skupni-primeri" / "debrid-serije.json"


def _meritev(m):
    return P.Meritev(m["ponudnik"], m["ping_ms"], m["bajtov"], m["cas_ms"])


def _ali_none(v):
    return v if v not in ("",) else None


def izracunaj(f, v):
    """Isto ime pravila kot v primerih (in v Kotlinu preslikano)."""
    if f == "vrstni_red":
        return P.vrstni_red(set(v["z_kljucem"]), v["prednostna"])
    if f == "aktivna":
        return P.aktivna(set(v["z_kljucem"]), v["prednostna"], v["izklopljeno"])
    if f == "ocisti_kljuc":
        return P.ocisti_kljuc(v["vnos"])
    if f == "razlog_za_uporabnika":
        return P.razlog_za_uporabnika(v["napake"])
    if f == "poskusi_s_cakanjem":
        return P.poskusi_s_cakanjem(v["samo_predpomnjeno"], v["napake"])
    if f == "rd_vrsta_napake":
        return P.rd_vrsta_napake(v["http"], v["koda"])
    if f == "ad_vrsta_napake":
        return P.ad_vrsta_napake(v["http"], v["koda"])
    if f == "torbox_vrsta_napake":
        return P.torbox_vrsta_napake(v["http"], v["koda"])
    if f == "hashi_za_preverbo":
        return P.hashi_za_preverbo(v["hashi"])
    if f == "predpomnjeni_naprej":
        return P.predpomnjeni_naprej(v["hashi"], set(v["predpomnjeni"]))
    if f == "samodejni_torrent":
        return P.samodejni_torrent(v["aktivna"], v["hashi"], set(v["predpomnjeni"]))
    if f == "najhitrejsa":
        return P.najhitrejsa([_meritev(m) for m in v["meritve"]])
    if f == "opis_meritve":
        return P.opis_meritve(_meritev(v))
    if f == "izberi_datoteko":
        d = P.izberi_datoteko([P.Datoteka(x["id"], x["ime"], x["velikost"]) for x in v["datoteke"]], v["indeks"])
        return d.ime if d else None
    if f == "je_epizoda":
        return media_servers.stremio_je_epizoda(v["id"])
    if f == "id_epizode_imdb":
        return _ali_none(media_servers.stremio_id_epizode_imdb(v["imdb"] or "", v["id_epizode"], v["sezona"], v["epizoda"]))
    if f == "imdb_iz_meta":
        return _ali_none(media_servers.stremio_imdb_iz_meta({"imdb_id": v["imdb_polje"]}, v["id"]))
    raise KeyError("neznano pravilo: " + f)


class SkupniPrimeri(unittest.TestCase):
    def test_vsi_primeri(self):
        koren = json.loads(PRIMERI.read_text(encoding="utf-8"))
        napake = []
        for p in koren["primeri"]:
            try:
                dobljeno = izracunaj(p["f"], p["vhod"])
            except Exception as e:  # noqa: BLE001 - izjema je napaka primera, ne konec preizkusa
                dobljeno = "izjema %s: %s" % (type(e).__name__, e)
            if dobljeno != p["izhod"]:
                napake.append("%s %s: pricakovano %r, dobljeno %r" % (p["f"], p["vhod"], p["izhod"], dobljeno))
        self.assertEqual(napake, [], "\n".join(napake))
        self.assertGreaterEqual(len(koren["primeri"]), 60)


if __name__ == "__main__":
    unittest.main()
