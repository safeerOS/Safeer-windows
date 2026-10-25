"""Naloga 134: skupni preizkusni primeri za Safeer OS Android (tests/SkupniPrimeriTest.kt) in namizje (ta datoteka).

Datoteka tests/skupni-primeri/debrid-serije.json je ista v repozitorijih Android-tv, Safeer-linux in Safeer-windows:
pravilo, spremenjeno samo na eni strani, tu ali tam pade. null v primeru = ni vrednosti (None ali prazen niz).
"""
import json
import unittest
from pathlib import Path

from core import debrid_pravila as P, media_servers, usenet_pravila as U

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
    # Grokov pregled 25. 10. 2026: (storitev, napaka) po vrstnem redu poskusov, pospravljanje samo svojih, meja odgovora.
    if f == "razlog_po_storitvah":
        return P.razlog_po_storitvah([tuple(x) for x in v["napake"]])
    if f == "cakalna_storitev":
        return P.cakalna_storitev(v["samo_predpomnjeno"], [tuple(x) for x in v["napake"]])
    if f == "ponudnik_napake":
        return P.ponudnik_napake([tuple(x) for x in v["napake"]])
    if f == "rd_dodano_ms":
        return P.rd_dodano_ms(v["added"])
    if f == "ad_dodano_ms":
        return P.ad_dodano_ms(v["upload_date"])
    if f == "dodal_smo_mi":
        return P.dodal_smo_mi(v["dodano_ms"], v["odgovor_ms"])
    if f == "najvec_odgovora":
        return P.NAJVEC_ODGOVORA
    # Vrstni red virov (lastnik 25. 10. 2026 07:25): Usenet, ki ga ima TorBox pripravljenega, gre prvi.
    if f == "vrstni_red_virov":
        return U.vrstni_red_virov(v["usenet"], v["webtor"])
    if f == "usenet_za_takojsnjo":
        return U.za_takojsnjo(v["gb"])
    if f == "usenet_za_samodejno":
        return U.za_samodejno(v["gb"])
    if f == "usenet_najboljsa_pripravljena":
        return U.najboljsa_pripravljena(v["pripravljene"])
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
