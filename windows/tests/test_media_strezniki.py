"""Kodi, TVHeadend, AzuraCast, Funkwhale, DLNA in Stremio dodatki v Medijskem centru (brez omrezja)."""
import json
import urllib.parse
from unittest import mock

from core import media_servers as m

SRV = {"id": "s1", "ime": "Doma", "uporabnik": "kodi"}


def _odgovori(tabela):
    def fake(url, headers=None, body=None, raw=None):
        for kljuc, vrednost in tabela.items():
            if kljuc in url and (not callable(vrednost)):
                return vrednost if isinstance(vrednost, bytes) else json.dumps(vrednost).encode()
            if kljuc in url and callable(vrednost):
                return vrednost(url, body, raw)
        raise OSError("ni odgovora za " + url)
    return fake


def test_http_samo_v_domacem_omrezju():
    assert m.dovoljen_naslov("http://192.168.0.5:8080/jsonrpc")
    assert m.dovoljen_naslov("http://kodi.local:8080/")
    assert m.dovoljen_naslov("https://primer.si/")
    assert not m.dovoljen_naslov("http://8.8.8.8/")


def test_kodi_knjiznica_in_dodatki():
    def rpc(url, body, raw):
        metoda = body["method"]
        if metoda == "VideoLibrary.GetMovies":
            return json.dumps({"result": {"movies": [{"movieid": 1, "label": "Film", "file": "/filmi/a b.mkv"}]}}).encode()
        if metoda == "VideoLibrary.GetEpisodes":
            return json.dumps({"result": {}}).encode()
        if metoda == "AudioLibrary.GetSongs":
            return json.dumps({"result": {"songs": [{"songid": 2, "label": "Pesem", "file": "/g/p.mp3",
                                                     "artist": ["A"], "genre": ["Rock"]}]}}).encode()
        if metoda == "Addons.GetAddons":
            return json.dumps({"result": {"addons": [{"addonid": "plugin.video.arte", "name": "ARTE"}]}}).encode()
        return json.dumps({"result": "ok"}).encode()
    with mock.patch.object(m, "_request", _odgovori({"/jsonrpc": rpc})):
        izid = m.catalog("kodi", "http://192.168.0.5:8080", SRV, "geslo")
    film = next(x for x in izid if x["vrsta"] == "film")
    assert film["url"].startswith("http://kodi:geslo@192.168.0.5:8080/vfs/")
    assert urllib.parse.unquote(film["url"].split("/vfs/")[1]) == "/filmi/a b.mkv"
    assert any(x["vrsta"] == "glasba" and x["zanri"] == "Rock" for x in izid)
    assert any(x["url"] == "kodi-dodatek:s1|plugin.video.arte" for x in izid)


def test_tvheadend_kanali_so_tv_v_zivo():
    kanali = {"entries": [{"uuid": "abc", "name": "SLO 1", "number": 1, "enabled": True},
                          {"uuid": "x", "name": "Izklopljen", "enabled": False}]}
    with mock.patch.object(m, "_request", _odgovori({"/api/channel/grid": kanali})):
        izid = m.catalog("tvheadend", "http://192.168.0.9:9981", SRV, "")
    assert [x["naslov"] for x in izid] == ["SLO 1"]
    assert izid[0]["vrsta"] == "tv-v-zivo" and "/stream/channel/abc" in izid[0]["url"]


def test_stremio_dodatek_katalog_in_tokovi():
    manifest = {"id": "a", "name": "Dodatek", "catalogs": [{"type": "movie", "id": "top", "extra": [{"name": "search"}]}]}
    tabela = {"/manifest.json": manifest,
              "/catalog/movie/top.json": {"metas": [{"id": "tt1", "name": "Film", "poster": "https://p/1.jpg"}]},
              "/stream/movie/tt1.json": {"streams": [{"infoHash": "abc"}, {"url": "https://cdn.primer/film.mp4", "name": "HD"}]},
              "/stream/movie/tt2.json": {"streams": [{"infoHash": "abc"}]}}
    with mock.patch.object(m, "_request", _odgovori(tabela)):
        izid = m.catalog("stremio", "https://dodatek.primer/manifest.json", SRV, "")
        assert izid[0]["url"] == "stremio:https://dodatek.primer|movie|tt1"
        tokovi = m.stremio_tokovi("https://dodatek.primer", "movie", "tt1")
        assert [t["url"] for t in tokovi if t.get("url")] == ["https://cdn.primer/film.mp4"]
        assert all(t.get("torrent") for t in m.stremio_tokovi("https://dodatek.primer", "movie", "tt2"))


def test_dlna_imenik():
    opis = (b'<root xmlns="urn:schemas-upnp-org:device-1-0"><device><friendlyName>Gerbera</friendlyName>'
            b'<serviceList><service><serviceType>urn:schemas-upnp-org:service:ContentDirectory:1</serviceType>'
            b'<controlURL>/upnp/control/cds</controlURL></service></serviceList></device></root>')
    didl_koren = ('<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"><container id="1"/></DIDL-Lite>')
    didl_mapa = ('<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" '
                 'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/"><item id="9"><dc:title>Pesem</dc:title>'
                 '<upnp:class>object.item.audioItem.musicTrack</upnp:class><upnp:genre>Jazz</upnp:genre>'
                 '<res>http://192.168.0.7:49152/content/media/9.mp3</res></item></DIDL-Lite>')

    def soap(url, body, raw):
        didl = didl_koren if b"<ObjectID>0</ObjectID>" in raw else didl_mapa
        ovoj = ('<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body><u:BrowseResponse '
                'xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1"><Result>%s</Result></u:BrowseResponse>'
                '</s:Body></s:Envelope>') % didl.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return ovoj.encode()
    with mock.patch.object(m, "_request", _odgovori({"/opis.xml": opis, "/upnp/control/cds": soap})):
        izid = m.catalog("dlna", "http://192.168.0.7:49152/opis.xml", SRV, "")
    assert izid and izid[0]["naslov"] == "Pesem" and izid[0]["vrsta"] == "glasba" and izid[0]["zanri"] == "Jazz"
