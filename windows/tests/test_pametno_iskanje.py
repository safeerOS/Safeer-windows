import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODUL = ROOT / "assets" / "os" / "namera-iskanja.js"


def _odloci(niz, podatki):
    if not shutil.which("node"):
        pytest.skip("Node ni nameščen")
    skripta = "const m=require(process.argv[1]); console.log(JSON.stringify(m.nameraIskanja(JSON.parse(process.argv[2]), JSON.parse(process.argv[3]))));"
    rezultat = subprocess.run(
        ["node", "-e", skripta, str(MODUL), json.dumps(niz), json.dumps(podatki)],
        check=True, capture_output=True, text=True,
    )
    return json.loads(rezultat.stdout)


@pytest.fixture
def podatki():
    return {
        "spletne": [{"ime": "YouTube", "url": "https://www.youtube.com"}, {"ime": "Gmail", "url": "https://mail.google.com"}],
        "programi": [{"ime": "Kalkulator", "id": "calc", "kljucne": ["računanje"]}],
        "datoteke": [{"ime": "Pogodba.pdf", "pot": "C:\\Dokumenti\\Pogodba.pdf"}],
        "mediji": [{"naslov": "Sintel", "vrsta": "film"}],
        "naprave": [{"ime": "Dnevna soba", "id": "tv-1", "platforma": "tv"}],
    }


@pytest.mark.parametrize("niz,vrsta", [
    ("example.org", "splet"), ("yt", "splet"), ("Kalkulator", "programi"),
    ("Pogodba.pdf", "datoteke"), ("film Sintel", "media"), ("Musik", "media"),
    ("Dnevna soba", "naprave"), ("vreme jutri", "splet"),
])
def test_namera_iskanja(niz, vrsta, podatki):
    assert _odloci(niz, podatki)["vrsta"] == vrsta


def test_yt_ujame_youtube_in_ne_spletnega_iskanja(podatki):
    rezultat = _odloci("yt", podatki)
    assert rezultat["spletna"]["ime"] == "YouTube"
    assert "iskanje" not in rezultat


def test_sporocila_ime_in_naslov_osebe(podatki):
    podatki["sporocila"] = [{"oseba": {"ime": "Ana Novak", "identitete": [["email", "ana@primer.si"]]},
                             "pogovori": [{"id": "ana@primer.si", "kanal_id": "k1"}]}]
    assert _odloci("Ana", podatki)["vrsta"] == "sporocila"
    assert _odloci("ana@primer.si", podatki)["vrsta"] == "sporocila"
    assert _odloci("neznan@primer.si", podatki)["vrsta"] == "splet"
    assert _odloci("Kalkulator", podatki)["vrsta"] == "programi"
