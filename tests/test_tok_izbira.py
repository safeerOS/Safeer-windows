"""Izbira najboljsega toka: ista pravila kot na Androidu (tests/TokIzbiraTest.kt v repozitoriju Android-tv)."""
from core import tok_izbira as T

TOKOVI = [
    "Dodatek 4K [A] [12.66 GB] FILM.2020.2160p.REPACK.WEB-DL.MULTi.DDP5.1.Atmos.DV.HDR.H.265-SKUPINA.mkv HDR DV A",
    "Dodatek 2160p [A] [18.61 GB] FILM.2020.2160p.WEB-DL.MULTi.DDP5.1.Atmos.H.265-SKUPINA.mkv A",
    "Dodatek 1080p [3.1 GB] FILM.2020.1080p.WEB-DL.AAC.H.264.mkv",
    "Dodatek 720p [1.2 GB] FILM.2020.720p.WEB-DL.AAC.H.264.mkv",
    "CAM 1080p [1.9 GB] FILM.2020.1080p.HDCAM.AAC.mkv",
]


def test_opis_iz_imena():
    o = T.opisi(TOKOVI[0])
    assert (o.visina, o.hevc, o.hdr, o.dv, o.zvok) == (2160, True, True, True, "eac3") and 12.6 < o.gb < 12.7
    assert 0.68 < T.opisi("Film 700 MB 480p").gb < 0.69
    assert T.opisi("Film.2019.1080p.BluRay.DTS.x264").zvok == "dts"
    assert T.opisi("Film brez podatkov").visina == 0


def test_telefon_brez_dolby_dobi_1080p_z_zvokom():
    telefon = T.Zmoznosti(visina=1080, hevc=True, av1=False, hdr=False, dolby_vision=False, eac3=False, ac3=False, dts=False, truehd=False)
    urejeni = T.uredi(TOKOVI, str, telefon)
    assert urejeni[0] == TOKOVI[2]
    assert urejeni.index(TOKOVI[3]) < urejeni.index(TOKOVI[0])       # 720p z zvokom pred 4K brez zvoka
    assert urejeni.index(TOKOVI[4]) > urejeni.index(TOKOVI[2])       # posnetek iz kina za pravim 1080p


def test_racunalnik_predvaja_vse_izbere_po_zaslonu():
    assert T.uredi(TOKOVI, str, T.Zmoznosti(visina=2160))[:2] == [TOKOVI[0], TOKOVI[1]]   # 4K zaslon: 4K, manjsa datoteka prej
    assert T.uredi(TOKOVI, str, T.Zmoznosti(visina=1080))[0] == TOKOVI[2]                # zaslon 1080p: 1080p, ne 18 GB


def test_enaka_ocena_ohrani_vrstni_red_dodatka():
    assert T.uredi(["X 1080p", "Y 1080p"], str, T.Zmoznosti()) == ["X 1080p", "Y 1080p"]


# ---- Rok veljavnosti povezave in "prvi tok mora res odgovoriti" (krog 90) ----
ZDAJ = 1_791_054_000                                     # 3. 10. 2026 19:00:00 UTC
PODPISANA = ("https://racun.shramba.example/mapa/film.mkv?X-Amz-Algorithm=AWS4-HMAC-SHA256"
             "&X-Amz-Credential=k%2F20261003%2Fauto%2Fs3%2Faws4_request&X-Amz-Date=20261003T161807Z"
             "&X-Amz-Expires=10800&X-Amz-Signature=abc&X-Amz-SignedHeaders=host")
TRAJNA = "https://datoteke.example/api/file/AbCd1234?download"


def test_rok_podpisane_povezave():
    assert T.velja_se(PODPISANA, ZDAJ) == 1087                   # podpisana ob 16:18:07 za 3 ure
    assert not T.potekla(PODPISANA, ZDAJ) and T.potekla(PODPISANA, ZDAJ + 1030) and T.potekla(PODPISANA, ZDAJ + 1087)
    assert T.velja_se("https://storage.example/f.mp4?X-Goog-Date=20261003T180000Z&X-Goog-Expires=7200&X-Goog-Signature=x", ZDAJ) == 3600
    assert T.velja_se("https://cdn.example/f.mkv?Expires=%d&Signature=x&Key-Pair-Id=y" % (ZDAJ + 500), ZDAJ) == 500
    assert T.velja_se("https://cdn.example/f.mkv?token=abc&expires=%d" % (ZDAJ - 30), ZDAJ) == -30
    assert T.velja_se("https://cdn.example/f.m3u8?hdnts=st=1~exp=%d~hmac=ff" % (ZDAJ + 90), ZDAJ) == 90
    assert T.velja_se("https://racun.blob.example/f.mkv?sv=2022&se=2026-10-03T20%3A00%3A00Z&sr=b&sig=x", ZDAJ) == 3600
    assert T.velja_se("https://x.example/f?X-Amz-Date=20240229T120000Z&X-Amz-Expires=60", 1_709_208_000) == 60
    for naslov in (TRAJNA, "https://cdn.example/f.mkv?id=1234567890&exp=12", "https://cdn.example/f.mkv?expires=never",
                   "https://cdn.example/f.mkv?X-Amz-Date=20261003T161807Z", "", None):
        assert T.velja_se(naslov, ZDAJ) is None, naslov


def test_trajna_povezava_pred_casovno_omejeno():
    opis, naslov = (lambda t: t["opis"]), (lambda t: t["url"])
    tv4k = T.Zmoznosti(visina=2160)
    par = [{"opis": "Dodatek 2160p [A] [4.63 GB] FILM.2020.2160p.HDR.HEVC.mkv", "url": PODPISANA},
           {"opis": "Dodatek 2160p [B] [4.63 GB] FILM.2020.2160p.HDR.HEVC.mkv", "url": TRAJNA}]
    assert T.uredi(par, opis, tv4k)[0]["url"] == PODPISANA                               # brez naslova: vrstni red dodatka
    assert T.uredi(par, opis, tv4k, naslov, ZDAJ - 3600)[0]["url"] == TRAJNA
    visja = [{"opis": "Dodatek 1080p [2 GB] FILM.2020.1080p.mkv", "url": TRAJNA},
             {"opis": "Dodatek 2160p [9 GB] FILM.2020.2160p.HEVC.mkv", "url": PODPISANA}]
    assert T.uredi(visja, opis, tv4k, naslov, ZDAJ - 6000)[0]["url"] == PODPISANA         # rok je le jezicek na tehtnici
    trije = [{"opis": "Dodatek 2160p [5 GB] FILM.2020.2160p.HEVC.mkv", "url": PODPISANA},
             {"opis": "Dodatek 2160p [20 GB] FILM.2020.2160p.HEVC.mkv", "url": TRAJNA},
             {"opis": "Dodatek 1080p [2 GB] FILM.2020.1080p.mkv", "url": TRAJNA + "2"}]
    velikosti = lambda seznam: [t["opis"].split("[")[1].split("]")[0] for t in seznam]  # noqa: E731
    assert velikosti(T.uredi(trije, opis, tv4k, naslov, ZDAJ)) == ["20 GB", "5 GB", "2 GB"]          # tik pred iztekom
    assert velikosti(T.uredi(trije, opis, tv4k, naslov, ZDAJ + 5000)) == ["20 GB", "2 GB", "5 GB"]   # potekla je zadnja


def test_mrtva_povezava_ne_pride_na_prvo_mesto(tmp_path, monkeypatch):
    from core import media_servers, os_media
    mc = os_media.MediaCenter(str(tmp_path), roots=[])
    mrtvi, drugi, zivi = {"url": "https://a.example/1.mkv"}, {"url": "https://a.example/2.mkv"}, {"url": "https://b.example/3.mkv"}
    klici = []
    monkeypatch.setattr(media_servers, "tok_odgovarja", lambda url, glave=None, rok=4.0: (klici.append(url), url == zivi["url"])[1])
    assert mc._zivi_naprej([mrtvi, zivi]) == [mrtvi, zivi] and klici == []     # brez vklopa ni nobene zahteve
    mc.preveri_tokove = True
    assert mc._zivi_naprej([mrtvi, zivi]) == [zivi, mrtvi]
    assert mc._zivi_naprej([mrtvi, drugi, zivi, mrtvi]) == [zivi, mrtvi, drugi, mrtvi]
    assert mc._zivi_naprej([zivi, mrtvi]) == [zivi, mrtvi]
    assert mc._zivi_naprej([mrtvi, drugi]) == [mrtvi, drugi]                   # noben ne odgovori: vrstni red ostane
    assert mc._zivi_naprej([mrtvi, drugi, mrtvi, zivi]) == [mrtvi, drugi, mrtvi, zivi]   # cetrtega ne sprasujemo
