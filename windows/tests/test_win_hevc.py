"""HEVC na Windows oddajniku (windows/zajem_zaslona.py), cisti del: izbira toka, vrste NAL, glava, preizkus
kodirnika z laznim PyAV (brez Windows, brez GPU). Enako pravilo kot Linux izberi_tok (D2/D3/D6)."""

import glob
import importlib.util
import json
import os
import types

import pytest


def _nalozi():
    koren = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Pot modula v repozitoriju NEPREVERJENO: najprej windows/zajem_zaslona.py, sicer prvi zadetek.
    poti = [os.path.join(koren, "windows", "zajem_zaslona.py")]
    poti += sorted(glob.glob(os.path.join(koren, "**", "zajem_zaslona.py"), recursive=True))
    for pot in poti:
        if os.path.isfile(pot):
            spec = importlib.util.spec_from_file_location("win_zajem_zaslona_hevc_test", pot)
            modul = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(modul)
            return modul
    pytest.skip("zajem_zaslona.py ni najden")


zz = _nalozi()

# H.265 enote NAL (2-bajtna glava; vrsta << 1, tid 1)
VPS = b"\x00\x00\x00\x01\x40\x01\x0c\x01"
SPS = b"\x00\x00\x00\x01\x42\x01\x01\x01"
PPS = b"\x00\x00\x00\x01\x44\x01\xc1\x72"
IDR_W_RADL = b"\x00\x00\x01\x26\x01\xaf\x00"      # vrsta 19
IDR_N_LP = b"\x00\x00\x01\x28\x01\xaf\x00"        # vrsta 20
TRAIL_R = b"\x00\x00\x01\x02\x01\xd0\x00"         # vrsta 1
STSA_N = b"\x00\x00\x01\x08\x01\xd0\x00"          # vrsta 4 (H.264 maska bi rekla PPS 8)
# H.264
H_SPS = b"\x00\x00\x00\x01\x67\x64\x00\x28"
H_PPS = b"\x00\x00\x00\x01\x68\xee\x3c\x80"
H_IDR = b"\x00\x00\x01\x65\x88\x84\x00"
H_P = b"\x00\x00\x01\x41\x9a\x00\x00"


# ------------------------------------------------------------------ vrste NAL

def test_vrsta_nal_hevc_in_h264():
    assert zz.vrsta_nal(IDR_W_RADL, 0, "hevc") == 19
    assert zz.vrsta_nal(IDR_N_LP, 0, "hevc") == 20
    assert zz.vrsta_nal(VPS, 1, "hevc") == 32
    assert zz.vrsta_nal(SPS, 1, "hevc") == 33
    assert zz.vrsta_nal(PPS, 1, "hevc") == 34
    assert zz.vrsta_nal(H_IDR, 0) == 5
    assert zz.vrsta_nal(b"\x00\x00\x01", 0, "hevc") == -1


def test_je_idr_hevc():
    assert zz.je_idr(VPS + SPS + PPS + IDR_W_RADL, "hevc")
    assert zz.je_idr(IDR_N_LP, "hevc")
    assert not zz.je_idr(TRAIL_R, "hevc")
    assert not zz.je_idr(STSA_N, "hevc")


def test_maska_h264_na_hevc_ne_najde_idr():
    """Dokaz, zakaj je razclenjevanje odvisno od kodeka: stara H.264 pot IDR-ja v H.265 ne najde."""
    assert not zz.H264Zajem._je_idr(VPS + SPS + PPS + IDR_W_RADL)
    # in rezino IDR_N_LP (0x28 & 0x1F = 8) bi imela za PPS
    assert zz.H264Zajem._nastavitve(IDR_N_LP) != b""


@pytest.mark.parametrize("paket", [H_SPS + H_PPS + H_IDR, H_P, H_IDR, H_SPS + H_PPS + H_IDR + H_P, b"", b"\x00\x00\x01"])
def test_h264_enako_kot_prej(paket):
    assert zz.je_idr(paket) == zz.H264Zajem._je_idr(paket)
    assert zz.nastavitve(paket) == zz.H264Zajem._nastavitve(paket)


def test_nastavitve_hevc_vps_sps_pps_v_redu():
    ven = zz.nastavitve(VPS + SPS + PPS + IDR_W_RADL, "hevc")
    assert ven == VPS + SPS + PPS
    assert zz.nastavitve(TRAIL_R + STSA_N, "hevc") == b""


def test_ima_nastavitve_spredaj():
    assert zz.ima_nastavitve_spredaj(VPS + SPS + PPS + IDR_W_RADL, "hevc")
    assert not zz.ima_nastavitve_spredaj(IDR_W_RADL, "hevc")
    assert zz.ima_nastavitve_spredaj(H_SPS + H_PPS + H_IDR)
    assert not zz.ima_nastavitve_spredaj(H_IDR)
    # H.264 SPS ni HEVC VPS in obratno
    assert not zz.ima_nastavitve_spredaj(H_SPS + H_IDR, "hevc")
    assert not zz.ima_nastavitve_spredaj(VPS + IDR_W_RADL)


# ------------------------------------------------------------------ izbira toka

DA = lambda w, h: True   # noqa: E731
NE = lambda w, h: False  # noqa: E731
IZVOR_4K = (3840, 2160)


def test_brez_seznama_h264_kot_prej():
    assert zz.izberi_tok(None, None, IZVOR_4K, DA) == ("h264", 1920, 1080)
    assert zz.izberi_tok("hevc", None, IZVOR_4K, DA) == ("h264", 1920, 1080)


def test_h264_pred_hevc_ostane_h264():
    assert zz.izberi_tok(["h264", "hevc"], {"hevc": [3840, 2160]}, IZVOR_4K, DA)[0] == "h264"


def test_hevc_brez_izjave_1080p():
    assert zz.izberi_tok(["hevc", "h264"], None, IZVOR_4K, DA) == ("hevc", 1920, 1080)


def test_hevc_z_izjavo_4k():
    assert zz.izberi_tok(["HEVC ", "h264"], {"hevc": [3840, 2160]}, IZVOR_4K, DA) == ("hevc", 3840, 2160)


def test_4k_samo_pri_polni_kakovosti():
    assert zz.izberi_tok(["hevc"], {"hevc": [3840, 2160]}, IZVOR_4K, DA, polna=False) == ("hevc", 1920, 1080)


def test_izjava_vecja_od_4k_omejena():
    assert zz.izberi_tok(["hevc"], {"hevc": [7680, 4320]}, (7680, 4320), DA) == ("hevc", 3840, 2160)


def test_brez_povecave():
    assert zz.izberi_tok(["hevc"], {"hevc": [3840, 2160]}, (2560, 1440), DA) == ("hevc", 2560, 1440)


def test_izjava_manjsa_od_osnove_h264():
    assert zz.izberi_tok(["hevc"], {"hevc": [1280, 720]}, IZVOR_4K, DA) == ("h264", 1920, 1080)


@pytest.mark.parametrize("izjava", [{"hevc": [True, 2160]}, {"hevc": [3840]}, {"hevc": [0, 2160]},
                                    {"hevc": [3840.0, 2160]}, {"hevc": [20000, 2160]}, [3840, 2160], {"h264": [3840, 2160]}])
def test_neveljavna_izjava_ni_4k(izjava):
    assert zz.izberi_tok(["hevc"], izjava, IZVOR_4K, DA) == ("hevc", 1920, 1080)


def test_racunalnik_ne_zmore_hevc():
    assert zz.izberi_tok(["hevc", "h264"], {"hevc": [3840, 2160]}, IZVOR_4K, NE) == ("h264", 1920, 1080)


def test_preizkus_dobi_velikost_seje():
    klici = []
    zz.izberi_tok(["hevc"], {"hevc": [3840, 2160]}, IZVOR_4K, lambda w, h: klici.append((w, h)) or True)
    assert klici == [(3840, 2160)]


def test_najvec_osem_vnosov():
    assert zz.izberi_tok(["x"] * 8 + ["hevc"], None, IZVOR_4K, DA)[0] == "h264"


def test_velikost_slike_privzeto_enako():
    assert zz.velikost_slike((3840, 2160)) == (1920, 1080)
    assert zz.velikost_slike((1366, 768)) == (1366, 768)
    assert zz.velikost_slike((3840, 2160), zz.NAJVEC_HEVC) == (3840, 2160)


# ------------------------------------------------------------------ glava

def test_glava_h264_bajt_za_bajtom():
    zig = {"okvir": 4, "ura": "monotonic_ms"}
    stara = {
        "v": 2, "w": 1920, "h": 1080, "fps": 30,
        "zvok": ({"hz": zz.ZVOK_HZ, "kanali": zz.ZVOK_KANALI, "oblika": "s16le"}),
        "vnos": True, "plosek": False, "au": True, "zig": dict(zig),
    }
    assert json.dumps(zz.glava_toka(1920, 1080, 30, True, zig)) == json.dumps(stara)
    stara["zvok"] = None
    assert json.dumps(zz.glava_toka(1920, 1080, 30, False, zig)) == json.dumps(stara)


def test_glava_hevc_ima_kodek():
    g = zz.glava_toka(3840, 2160, 30, False, {"okvir": 4, "ura": "monotonic_ms"}, "hevc")
    assert g["kodek"] == "hevc" and g["w"] == 3840
    assert len(json.dumps(g)) < 512       # meja vrstice glave na TV


# ------------------------------------------------------------------ kodirniki in preizkus z laznim PyAV

class _Paket(bytes):
    pass


class _Ctx:
    def __init__(self, av, ime):
        self.av, self.ime, self.zaprt = av, ime, False

    def open(self):
        if self.ime in self.av.ne_odpre:
            raise RuntimeError("ni naprave")

    def encode(self, okvir):
        if okvir is None:
            return []
        return [_Paket(self.av.paket)]

    def close(self):
        self.zaprt = True


def _lazni_av(na_voljo=("h264_nvenc", "hevc_nvenc", "hevc_amf", "libx265"), paket=VPS + SPS + PPS + IDR_W_RADL,
              ne_odpre=()):
    av = types.SimpleNamespace(codecs_available=set(na_voljo), paket=paket, ne_odpre=set(ne_odpre), ustvarjeni=[])

    def create(ime, nacin):
        c = _Ctx(av, ime)
        av.ustvarjeni.append(c)
        return c

    av.CodecContext = types.SimpleNamespace(create=create)
    av.VideoFrame = lambda w, h, f: types.SimpleNamespace(width=w, height=h, format=f, pts=None)
    return av


@pytest.fixture(autouse=True)
def _pocisti():
    zz._HEVC_PREIZKUS.clear()
    yield
    zz._HEVC_PREIZKUS.clear()


def test_kodirniki_hevc_brez_libx265():
    assert zz.kodirniki_hevc(_lazni_av()) == ["hevc_nvenc", "hevc_amf"]
    assert "libx265" not in zz.KODIRNIKI_HEVC
    assert zz.kodirniki_hevc(types.SimpleNamespace()) == []


def test_preizkus_uspe_z_idr_in_zapre():
    av = _lazni_av()
    assert zz.preizkusi_hevc(av, "hevc_nvenc", 3840, 2160)
    c = av.ustvarjeni[0]
    assert (c.width, c.height, c.pix_fmt, c.max_b_frames) == (3840, 2160, "nv12", 0)
    assert c.zaprt


def test_preizkus_brez_idr_ne():
    assert not zz.preizkusi_hevc(_lazni_av(paket=TRAIL_R), "hevc_nvenc", 3840, 2160)


def test_preizkus_napaka_odpiranja_ne():
    assert not zz.preizkusi_hevc(_lazni_av(ne_odpre=("hevc_qsv",)), "hevc_qsv", 1920, 1080)


def test_preizkus_enkrat_na_velikost():
    av = _lazni_av()
    zz.preizkusi_hevc(av, "hevc_nvenc", 1920, 1080)
    zz.preizkusi_hevc(av, "hevc_nvenc", 1920, 1080)
    zz.preizkusi_hevc(av, "hevc_nvenc", 3840, 2160)
    assert len(av.ustvarjeni) == 2


def test_moznosti_h264_nespremenjene_hevc_brez_look_ahead():
    assert zz._moznosti("h264_qsv")["look_ahead"] == "0"
    assert "look_ahead" not in zz._moznosti("hevc_qsv")
    assert zz._MOZNOSTI_IDR["h264_nvenc"] == {"forced-idr": "1"}
    assert zz._MOZNOSTI_IDR["h264_qsv"] == {"forced_idr": "1"}
