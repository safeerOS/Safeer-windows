"""Stremio odjemalec proti lažnemu dodatku na 127.0.0.1 (protokol: manifest, catalog s search/skip, meta, stream)."""
import json, os, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import unquote
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest
from safeer_windows import stremio_dodatki as S

MANIFEST = {"id": "si.test", "name": "Testni dodatek", "version": "1.0.0", "resources": ["catalog", {"name": "meta", "types": ["movie"]}, "stream"],
            "types": ["movie", "series"],
            "catalogs": [{"type": "movie", "id": "filmi", "name": "Filmi", "extra": [{"name": "search"}, {"name": "skip"}]},
                         {"type": "series", "id": "isk", "name": "Iskanje serij", "extra": [{"name": "search", "isRequired": True}]}]}


class _H(BaseHTTPRequestHandler):
    zahteve = []

    def log_message(self, *a): pass

    def do_GET(self):
        pot = unquote(self.path); _H.zahteve.append(pot); d = None
        if pot == "/manifest.json": d = MANIFEST
        elif pot.startswith("/catalog/movie/filmi"):
            metas = [{"id": "tt1", "type": "movie", "name": "Prvi film", "poster": "http://x/p.jpg", "releaseInfo": "2020", "description": "Opis 1"},
                     {"id": "tt2", "type": "movie", "name": "Drugi film"}]
            if "search=drugi" in pot: metas = metas[1:]
            if "skip=2" in pot: metas = []
            d = {"metas": metas}
        elif pot.startswith("/catalog/series/isk/search="): d = {"metas": [{"id": "s1", "type": "series", "name": "Serija"}]}
        elif pot == "/meta/series/s1.json": d = {"meta": {"id": "s1", "type": "series", "name": "Serija", "description": "O seriji",
                                                         "videos": [{"id": "s1:1:1", "title": "Pilot", "season": 1, "episode": 1}, {"id": "s1:1:2", "title": "Druga", "season": 1, "episode": 2}]}}
        elif pot == "/meta/movie/tt1.json": d = {"meta": {"id": "tt1", "type": "movie", "name": "Prvi film"}}
        elif pot == "/stream/movie/tt1.json":
            d = {"streams": [{"name": "HD", "title": "1080p", "url": "https://primer.si/v.m3u8", "behaviorHints": {"proxyHeaders": {"request": {"Referer": "https://primer.si/"}}},
                              "subtitles": [{"url": "https://primer.si/sl.srt", "lang": "slv"}]},
                             {"name": "Zunanji", "externalUrl": "https://primer.si/stran"},
                             {"name": "🌟 Donation needed", "title": "Click here to donate to keep the project alive", "externalUrl": "https://ko-fi.com/x"},
                             {"name": "💬 Join the Discord server", "url": "https://discord.gg/abc"},
                             {"name": "❌ No streams found", "title": "No streams found for this title", "url": "https://primer.si/info"},
                             {"name": "Discord.2012.1080p", "title": "Discord.2012.1080p.mkv", "url": "https://primer.si/d.mkv"},
                             {"name": "Torrent", "infoHash": "abc123", "fileIdx": 0},
                             {"name": "YT", "ytId": "xyz"},
                             {"name": "Čuden", "url": "ftp://primer.si/x"}]}
        if d is None:
            self.send_response(404); self.end_headers(); return
        b = json.dumps(d).encode(); self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)


@pytest.fixture(scope="module")
def streznik():
    s = HTTPServer(("127.0.0.1", 0), _H); t = threading.Thread(target=s.serve_forever, daemon=True); t.start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


def test_osnova():
    assert S.osnova_iz_manifesta("stremio://x.si/d/manifest.json") == "https://x.si/d"
    assert S.osnova_iz_manifesta("https://x.si/d/manifest.json") == "https://x.si/d"
    assert S.osnova_iz_manifesta("https://x.si/d/") == "https://x.si/d"


def test_manifest_katalogi_tokovi(streznik):
    d = S.StremioDodatek(streznik + "/manifest.json"); d.nalozi_manifest()
    assert d.ime == "Testni dodatek" and d.viri() == {"catalog", "meta", "stream"}
    k = d.katalogi()
    assert [(x["id"], x["iskanje"], x["obvezniFiltri"]) for x in k] == [("filmi", True, []), ("isk", True, ["search"])]
    v = d.katalog("movie", "filmi")
    assert [x["ime"] for x in v] == ["Prvi film", "Drugi film"] and v[0]["leto"] == "2020" and v[0]["opis"] == "Opis 1"
    assert [x["ime"] for x in d.katalog("movie", "filmi", iskanje="drugi")] == ["Drugi film"]
    assert d.katalog("movie", "filmi", preskoci=2) == []
    assert "/catalog/movie/filmi/search=drugi.json" in _H.zahteve
    m = d.meta("series", "s1")
    assert m["opis"] == "O seriji" and [(e["sezona"], e["epizoda"], e["ime"]) for e in m["videi"]] == [(1, 1, "Pilot"), (1, 2, "Druga")]
    t = d.tokovi("movie", "tt1")
    # Zunanje povezave in obvestila dodatka (donacije, Discord, "No streams found") niso tokovi; film z imenom
    # "Discord" s pravo datoteko ostane.
    assert [x["vrsta"] for x in t] == ["url", "url", "torrent", "napovednik", "neznano"]
    assert t[0]["glave"] == {"Referer": "https://primer.si/"} and t[0]["podnapisi"] == [{"url": "https://primer.si/sl.srt", "jezik": "slv"}]
    assert t[1]["url"] == "https://primer.si/d.mkv"
    assert t[2]["url"] == "magnet:?xt=urn:btih:abc123" and t[3]["url"].endswith("v=xyz")
    assert [S.predvajljiv(x) for x in t] == [True, True, False, False, False]
    assert not any("discord.gg" in x["url"] or "ko-fi" in x["url"] or "primer.si/info" in x["url"] or "primer.si/stran" in x["url"] for x in t)


def test_zavrne_ne_http():
    with pytest.raises(ValueError):
        S._json("file:///etc/passwd")
