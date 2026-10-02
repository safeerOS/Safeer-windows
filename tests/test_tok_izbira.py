"""Izbira najboljsega toka: ista pravila kot na Androidu (tests/TokIzbiraTest.kt v repozitoriju Android-tv)."""
from core import tok_izbira as T

TOKOVI = [
    "4KHDHub 4K [FSL] [12.66 GB] UNABOMBER.2026.2160p.REPACK.NF.WEB-DL.MULTi.DDP5.1.Atmos.DV.HDR.H.265-4kHdHub.Com.mkv HDR DV FSL",
    "HdHub 2160p [FSL] [18.61 GB] UNABOMBER.2026.2160p.NF.WEB-DL.MULTi.DDP5.1.Atmos.H.265-4kHdHub.Com.mkv FSL",
    "HdHub 1080p [3.1 GB] UNABOMBER.2026.1080p.WEB-DL.AAC.H.264.mkv",
    "HdHub 720p [1.2 GB] UNABOMBER.2026.720p.WEB-DL.AAC.H.264.mkv",
    "CAM 1080p [1.9 GB] UNABOMBER.2026.1080p.HDCAM.AAC.mkv",
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
