"""HEVC v Windows seji (navidezni_zaslon.zacni_sejo -> zajem_zaslona.izberi_kodek -> H264Zajem) z laznim PyAV,
brez Windows in brez GPU. Pravilo kot Linux Zaslon.zacni: HEVC samo ob izrecni izjavi TV in uspesnem preizkusu
kodirnika; 4K samo s HEVC; sicer H.264 1080p in vse kot prej."""

import glob
import importlib.util
import json
import os
import sys
import threading
import types

import pytest

KOREN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pot(ime):
    # Pot modula v repozitoriju NEPREVERJENO: najprej windows/safeer_windows/<ime>, sicer prvi zadetek.
    poti = [os.path.join(KOREN, "safeer_windows", ime), os.path.join(KOREN, "windows", "safeer_windows", ime)]
    poti += sorted(glob.glob(os.path.join(KOREN, "**", ime), recursive=True))
    for pot in poti:
        if os.path.isfile(pot):
            return pot
    pytest.skip(f"{ime} ni najden")


def _nalozi(ime_modula, pot):
    spec = importlib.util.spec_from_file_location(ime_modula, pot)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


zz = _nalozi("win_zajem_zaslona_hevc_seja", _pot("zajem_zaslona.py"))


def _nalozi_navidezni():
    """navidezni_zaslon z laznimi core.* in safeer_windows.* (pravi zajem_zaslona zz)."""
    stari = {k: sys.modules.get(k) for k in ("core", "core.link_vticnik", "core.link_datoteke",
                                             "safeer_windows", "safeer_windows.os_backend_win",
                                             "safeer_windows.policy", "safeer_windows.zajem_zaslona")}
    core = types.ModuleType("core")
    vt = types.ModuleType("core.link_vticnik")

    class VarnaTls:
        pass

    vt.VarnaTls = VarnaTls
    vt.brez_zamika = lambda s: None
    vt.zavaruj = lambda s: s
    dat = types.ModuleType("core.link_datoteke")
    dat.TLS_MAPA = "tls"
    dat.zagotovi_potrdilo = lambda mapa: ("kljuc.pem", "potrdilo.pem", "odtis")
    core.link_vticnik, core.link_datoteke = vt, dat
    sw = types.ModuleType("safeer_windows")
    sw.os_backend_win = types.ModuleType("safeer_windows.os_backend_win")
    sw.policy = types.ModuleType("safeer_windows.policy")
    sw.zajem_zaslona = zz
    sys.modules.update({"core": core, "core.link_vticnik": vt, "core.link_datoteke": dat, "safeer_windows": sw,
                        "safeer_windows.os_backend_win": sw.os_backend_win, "safeer_windows.policy": sw.policy,
                        "safeer_windows.zajem_zaslona": zz})
    try:
        return _nalozi("win_navidezni_zaslon_hevc_seja", _pot("navidezni_zaslon.py"))
    finally:
        for k, v in stari.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


nz = _nalozi_navidezni()

# H.265 / H.264 enote NAL
VPS = b"\x00\x00\x00\x01\x40\x01\x0c\x01"
SPS = b"\x00\x00\x00\x01\x42\x01\x01\x01"
PPS = b"\x00\x00\x00\x01\x44\x01\xc1\x72"
IDR = b"\x00\x00\x01\x26\x01\xaf\x00"
H_SPS = b"\x00\x00\x00\x01\x67\x64\x00\x28"
H_IDR = b"\x00\x00\x01\x65\x88\x84\x00"

IZVOR_4K = (3840, 2160)
DA = lambda w, h: True   # noqa: E731
NE = lambda w, h: False  # noqa: E731


# ------------------------------------------------------------------ lazni PyAV

class _Ctx:
    def __init__(self, av, ime):
        self.av, self.ime, self.extradata = av, ime, av.extradata

    def open(self):
        if self.ime in self.av.ne_odpre:
            raise RuntimeError("ni naprave")

    def encode(self, okvir):
        return [] if okvir is None else [self.av.paket]

    def close(self):
        pass


def _lazni_av(na_voljo=("h264_nvenc", "h264_mf", "libx264", "hevc_nvenc", "hevc_amf", "libx265"),
              paket=VPS + SPS + PPS + IDR, ne_odpre=(), extradata=b""):
    av = types.SimpleNamespace(codecs_available=set(na_voljo), paket=paket, ne_odpre=set(ne_odpre),
                               extradata=extradata, ustvarjeni=[])

    def create(ime, nacin):
        c = _Ctx(av, ime)
        av.ustvarjeni.append(c)
        return c

    av.CodecContext = types.SimpleNamespace(create=create)
    av.VideoFrame = lambda w, h, f: types.SimpleNamespace(width=w, height=h, format=f, pts=None)
    return av


@pytest.fixture(autouse=True)
def _okolje(monkeypatch):
    zz._HEVC_PREIZKUS.clear()
    monkeypatch.setattr(zz, "_velikost_zaslona", lambda: IZVOR_4K)
    pil = types.ModuleType("PIL")
    pil.ImageGrab = object()
    monkeypatch.setitem(sys.modules, "PIL", pil)
    yield
    zz._HEVC_PREIZKUS.clear()


# ------------------------------------------------------------------ izberi_kodek

def test_brez_zmoznosti_h264_1080p():
    assert zz.izberi_kodek(None, None, DA, IZVOR_4K) == ("h264", (1920, 1080))


def test_hevc_s_preizkusom_in_izjavo_4k():
    assert zz.izberi_kodek(["hevc", "h264"], {"hevc": [3840, 2160]}, DA, IZVOR_4K) == ("hevc", (3840, 2160))


def test_hevc_brez_izjave_1080p():
    assert zz.izberi_kodek(["hevc"], None, DA, IZVOR_4K) == ("hevc", (1920, 1080))


def test_preizkus_ne_uspe_h264():
    assert zz.izberi_kodek(["hevc"], {"hevc": [3840, 2160]}, NE, IZVOR_4K) == ("h264", (1920, 1080))


def test_napaka_preizkusa_h264():
    def pade(w, h):
        raise OSError("gonilnik")
    assert zz.izberi_kodek(["hevc"], {"hevc": [3840, 2160]}, pade, IZVOR_4K) == ("h264", (1920, 1080))


def test_ne_polna_kakovost_brez_4k():
    assert zz.izberi_kodek(["hevc"], {"hevc": [3840, 2160]}, DA, IZVOR_4K, polna=False) == ("hevc", (1920, 1080))


def test_h264_pred_hevc_ostane_h264():
    assert zz.izberi_kodek(["h264", "hevc"], {"hevc": [3840, 2160]}, DA, IZVOR_4K) == ("h264", (1920, 1080))


@pytest.mark.parametrize("kodeki", ["hevc", [1, 2], {"hevc": 1}, ["h265"], []])
def test_neznano_h264(kodeki):
    assert zz.izberi_kodek(kodeki, {"hevc": [3840, 2160]}, DA, IZVOR_4K) == ("h264", (1920, 1080))


def test_meja_izjave_samo_za_hevc():
    assert zz.izberi_kodek(["h264"], {"hevc": [3840, 2160], "h264": [3840, 2160]}, DA, IZVOR_4K) == ("h264", (1920, 1080))


def test_preizkus_dobi_velikost_seje():
    klici = []
    zz.izberi_kodek(["hevc"], {"hevc": [3840, 2160]}, lambda w, h: klici.append((w, h)) or True, (2560, 1440))
    assert klici == [(2560, 1440)]


def test_hevc_preizkus_brez_pyav(monkeypatch):
    monkeypatch.setitem(sys.modules, "av", None)
    assert zz.hevc_preizkus(1920, 1080) is False


def test_hevc_preizkus_z_laznim_pyav(monkeypatch):
    monkeypatch.setitem(sys.modules, "av", _lazni_av())
    assert zz.hevc_preizkus(3840, 2160) is True
    zz._HEVC_PREIZKUS.clear()
    monkeypatch.setitem(sys.modules, "av", _lazni_av(na_voljo=("h264_nvenc", "libx265")))
    assert zz.hevc_preizkus(3840, 2160) is False


# ------------------------------------------------------------------ H264Zajem s kodekom

def test_zajem_privzeto_h264_kot_prej(monkeypatch):
    av = _lazni_av()
    monkeypatch.setitem(sys.modules, "av", av)
    z = zz.H264Zajem(fps=60)
    assert (z.kodek, z.kodirnik, z.sirina, z.visina) == ("h264", "h264_nvenc", 1920, 1080)
    assert [c.ime for c in av.ustvarjeni] == ["h264_nvenc"]     # brez preizkusa HEVC


def test_zajem_hevc_4k(monkeypatch):
    av = _lazni_av(ne_odpre=("hevc_nvenc",))
    monkeypatch.setitem(sys.modules, "av", av)
    z = zz.H264Zajem(fps=60, kodek="hevc", velikost=(3840, 2160))
    assert (z.kodek, z.kodirnik, z.sirina, z.visina) == ("hevc", "hevc_amf", 3840, 2160)
    assert z._c.pix_fmt == "nv12"
    assert "libx265" not in [c.ime for c in av.ustvarjeni]


def test_zajem_hevc_brez_kodirnika(monkeypatch):
    monkeypatch.setitem(sys.modules, "av", _lazni_av(na_voljo=("h264_nvenc", "libx265")))
    with pytest.raises(RuntimeError, match="HEVC"):
        zz.H264Zajem(fps=60, kodek="hevc", velikost=(1920, 1080))


def _zajem_brez_init(kodek, extradata):
    z = object.__new__(zz.H264Zajem)
    if kodek is not None:
        z.kodek = kodek
    z._c = types.SimpleNamespace(extradata=extradata)
    return z


def test_z_nastavitvami_hevc_doda_vps_sps_pps():
    z = _zajem_brez_init("hevc", VPS + SPS + PPS)
    assert z._z_nastavitvami(IDR) == VPS + SPS + PPS + IDR
    assert z._z_nastavitvami(VPS + SPS + PPS + IDR) == VPS + SPS + PPS + IDR


def test_z_nastavitvami_h264_kot_prej():
    z = _zajem_brez_init(None, H_SPS)          # star objekt brez atributa kodek
    assert z._z_nastavitvami(H_IDR) == H_SPS + H_IDR
    assert z._z_nastavitvami(H_SPS + H_IDR) == H_SPS + H_IDR


# ------------------------------------------------------------------ zacni_sejo

class _Nit:
    ustvarjene: list = []

    def __init__(self, target=None, args=(), name="", daemon=None):
        self.target, self.args, self.name = target, args, name
        _Nit.ustvarjene.append(self)

    def start(self):
        pass

    def is_alive(self):
        return True


def _lazni_ssl():
    class Ctx:
        def __init__(self, protokol):
            pass

        def set_ciphers(self, s):
            pass

        def load_cert_chain(self, p, k):
            pass

    return types.SimpleNamespace(SSLContext=Ctx, PROTOCOL_TLS_SERVER=1, SSLError=Exception,
                                 TLSVersion=types.SimpleNamespace(TLSv1_2=2), SSLSocket=object)


def _lazni_socket():
    class Sock:
        def setsockopt(self, *a):
            pass

        def bind(self, a):
            pass

        def listen(self, n):
            pass

        def settimeout(self, t):
            pass

        def getsockname(self):
            return ("0.0.0.0", 5555)

    return types.SimpleNamespace(socket=lambda *a: Sock(), AF_INET=2, SOCK_STREAM=1, SOL_SOCKET=1, SO_REUSEADDR=2,
                                 SHUT_RDWR=2)


@pytest.fixture
def zaslon(monkeypatch):
    _Nit.ustvarjene = []
    monkeypatch.setattr(nz, "ssl", _lazni_ssl())
    monkeypatch.setattr(nz, "socket", _lazni_socket())
    monkeypatch.setattr(nz, "threading", types.SimpleNamespace(Thread=_Nit, RLock=threading.RLock, Lock=threading.Lock,
                                                           Event=threading.Event))
    monkeypatch.setattr(zz, "dxgi_na_voljo", lambda: True)
    monkeypatch.setattr(zz, "zvok_na_voljo", lambda: False)
    z = object.__new__(nz.NavidezniZaslon)
    z._kljuc = threading.RLock()
    z._odjemalec, z._posiljatelj_seje, z._prevzete, z._seja_st, z.tls_mapa = None, "", {}, 0, "tls"
    z.ustavi_sejo = lambda *a, **k: None
    return z


def test_seja_brez_zmoznosti_kot_prej(zaslon, monkeypatch):
    monkeypatch.setattr(zz, "hevc_preizkus", lambda w, h: pytest.fail("preizkus brez zmoznosti"))
    odg = zaslon.zacni_sejo("tv")
    assert (odg["codec"], odg["width"], odg["height"], odg["fps"]) == ("h264", 1920, 1080, 60)
    assert len(_Nit.ustvarjene[-1].args) == 4            # isti argumenti niti kot prej


def test_seja_hevc_4k(zaslon, monkeypatch):
    monkeypatch.setattr(zz, "hevc_preizkus", DA)
    odg = zaslon.zacni_sejo("tv", "najvisja", kodeki=["hevc", "h264"], najvecja={"hevc": [3840, 2160]})
    assert (odg["codec"], odg["width"], odg["height"]) == ("hevc", 3840, 2160)
    assert _Nit.ustvarjene[-1].args[4:] == ("hevc", (3840, 2160))


def test_seja_hevc_srednja_brez_4k(zaslon, monkeypatch):
    monkeypatch.setattr(zz, "hevc_preizkus", DA)
    odg = zaslon.zacni_sejo("tv", "srednja", kodeki=["hevc"], najvecja={"hevc": [3840, 2160]})
    assert (odg["codec"], odg["width"], odg["height"]) == ("hevc", 1920, 1080)


def test_seja_hevc_preizkus_ne_uspe(zaslon, monkeypatch):
    monkeypatch.setattr(zz, "hevc_preizkus", NE)
    brez = zaslon.zacni_sejo("tv")
    odg = zaslon.zacni_sejo("tv", kodeki=["hevc"], najvecja={"hevc": [3840, 2160]})
    for k in ("codec", "width", "height", "fps", "v", "audio"):
        assert odg[k] == brez[k]
    assert len(_Nit.ustvarjene[-1].args) == 4


# ------------------------------------------------------------------ _streci_sejo: glava in zig slike

class _Odjemalec:
    def __init__(self):
        self.poslano = b""

    def sendall(self, b):
        self.poslano += b

    def settimeout(self, t):
        pass

    def close(self):
        pass


def _streci(zaslon, monkeypatch, kodek):
    klici = []

    class Zajem:
        def __init__(self, **kw):
            klici.append(kw)
            self.kodek = kw.get("kodek", "h264")
            self.sirina, self.visina = kw.get("velikost") or (1920, 1080)
            self.fps, self.izvor, self.kodirnik = kw["fps"], IZVOR_4K, "lazni"

        def okvirji_z_zigi(self, tece):
            yield 1234.0, b"\x00\x00\x01\x26slika"

        def zapri(self):
            pass

    odj = _Odjemalec()
    monkeypatch.setattr(zz, "H264Zajem", Zajem)
    monkeypatch.setattr(zz, "WindowsVnos", lambda izvor, slika: types.SimpleNamespace(sprosti_vse=lambda: None))
    posluh = object()
    zaslon._sprejmi = lambda p, c: odj
    zaslon._tece, zaslon._seja_st, zaslon._posluh = True, 1, posluh
    args = (posluh, None, 60, 1) + ((kodek, (3840, 2160)) if kodek == "hevc" else ())
    zaslon._streci_sejo(*args)
    vrstica, ostalo = odj.poslano.split(b"\n", 1)
    return klici, json.loads(vrstica), vrstica, ostalo


def test_streci_h264_glava_bajt_za_bajtom_in_zig(zaslon, monkeypatch):
    klici, glava, vrstica, ostalo = _streci(zaslon, monkeypatch, "h264")
    assert klici == [{"fps": 60}]
    stara = {"v": 2, "w": 1920, "h": 1080, "fps": 60, "zvok": None, "vnos": True, "plosek": False,
             "au": True, "zig": dict(nz.ZIG_GLAVA)}
    assert vrstica == json.dumps(stara).encode("utf-8")
    assert ostalo[0] == nz.OKVIR_ZIG                     # zig slike ostane pri H.264


def test_streci_hevc_kodek_in_brez_ziga_slike(zaslon, monkeypatch):
    klici, glava, vrstica, ostalo = _streci(zaslon, monkeypatch, "hevc")
    assert klici == [{"fps": 60, "kodek": "hevc", "velikost": (3840, 2160)}]
    assert (glava["kodek"], glava["w"], glava["h"]) == ("hevc", 3840, 2160)
    assert ostalo[0] == nz.OKVIR_SLIKA                   # brez okvirja OKVIR_ZIG pred sliko
    assert ostalo[5:] == b"\x00\x00\x01\x26slika"
