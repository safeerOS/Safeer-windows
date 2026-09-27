"""TuneIn (OPML): samo postaje v zivo, tok ob kliku, brez podvojenih z Radio Browserjem."""
from core import zakoniti_viri as z


def test_samo_postaje_in_razresitev():
    v = z.ZakonitiViri()
    odgovori = {
        "Search": {"body": [
            {"type": "audio", "item": "station", "guide_id": "s25581", "text": "Val 202", "image": "http://x/logo.jpg"},
            {"type": "link", "item": "show", "guide_id": "p1", "text": "Oddaja"},
            {"type": "audio", "item": "topic", "guide_id": "t2", "text": "Epizoda"}]},
        "Tune": {"body": [{"element": "audio", "url": "https://mp3.rtvslo.si/val202", "bitrate": 128}]},
    }
    v._json = lambda url: odgovori["Search" if "Search.ashx" in url else "Tune"]
    r = v.tunein("val")
    assert [x["id"] for x in r] == ["tunein:s25581"]
    assert r[0]["slika"].startswith("https://")
    assert v.resolve_tunein(r[0])["url"] == "https://mp3.rtvslo.si/val202"


def test_brez_toka_ni_razresitve():
    v = z.ZakonitiViri()
    v._json = lambda url: {"body": [{"element": "audio", "url": ""}]}
    assert v.resolve_tunein({"tunein_id": "s1"}) is None
