"""Kljucni okvir (IDR) na zahtevo televizorja na Windows (zajem_zaslona.py + navidezni_zaslon.py), z laznimi
moduli - brez Windows, dxcam in PyAV.

Kaj mora veljati:
- najvec 1 sprejeta zahteva v 2 s (drsece okno), cas nazaj in neveljaven cas ne pokvarita okna;
- neveljaven JSON ali tip dogodka ne ustavi niti vnosa;
- zahteva zunaj seje (pred zacetkom ali po koncu) ne naredi nicesar;
- kodirnik, ki oznako I uposteva: IDR na naslednji sliki, SPS/PPS pred njim, brez zamenjave konteksta;
- kodirnik, ki oznake ne uposteva: po KLJUCNI_PAKETOV zamenjava konteksta, stari je izpraznjen in zaprt;
- okvir 4: zig in stevec "bajt" ostaneta pravilna po izsiljenem IDR, seja tece naprej.
"""
import json
import sys
import threading
import time
import types
from unittest import mock

import pytest

from safeer_windows import zajem_zaslona as zz

SPS_PPS = b"\x00\x00\x00\x01\x67\x64\x00\x28" + b"\x00\x00\x00\x01\x68\xee\x3c\x80"


def _lazni_av(oznaka_i="I"):
    """Lazni moduli av, av.video in av.video.frame s PictureType.I = `oznaka_i` (za sys.modules)."""
    av = types.ModuleType("av")
    video = types.ModuleType("av.video")
    okvir = types.ModuleType("av.video.frame")
    okvir.PictureType = types.SimpleNamespace(I=oznaka_i)
    av.video, video.frame = video, okvir
    return {"av": av, "av.video": video, "av.video.frame": okvir}


@pytest.fixture(autouse=True)
def _brez_pravega_av():
    """_oznaci_kljucni najprej uvozi av.video.frame. Izid preizkusa ne sme biti odvisen od tega, ali je PyAV na
    racunalniku namescen (pravi PictureType.I ni enak nizu "I"), zato vedno podtaknemo lazni av."""
    with mock.patch.dict(sys.modules, _lazni_av()):
        yield


# ------------------------------------------------------------------ lazni kodirnik

class _Okvir:
    def __init__(self, st):
        self.st = st
        self.pts = None
        self.pict_type = None


class _Paket:
    def __init__(self, pts, podatki):
        self.pts = pts
        self._podatki = podatki

    def __bytes__(self):
        return self._podatki


class _Kodirnik:
    """Paket na sliko takoj. Prvi paket konteksta: SPS, PPS in IDR; nato P (NAL 1). ``uposteva``: slika z oznako
    I postane IDR (brez SPS/PPS, kot nekateri strojni kodirniki)."""

    def __init__(self, uposteva=True, vsi=None):
        self.uposteva = uposteva
        self.extradata = b""
        self.pix_fmt = "nv12"
        self.prvi = True
        self.izpraznjen = False
        self.zaprt = False
        if vsi is not None:
            vsi.append(self)

    def encode(self, okvir):
        if okvir is None:
            self.izpraznjen = True
            return []
        st = bytes([okvir.st % 256])
        if self.prvi:
            self.prvi = False
            return [_Paket(okvir.pts, SPS_PPS + b"\x00\x00\x00\x01\x65" + st)]
        if self.uposteva and okvir.pict_type == "I":
            return [_Paket(okvir.pts, b"\x00\x00\x00\x01\x65" + st)]
        return [_Paket(okvir.pts, b"\x00\x00\x00\x01\x41" + st)]

    def close(self):
        self.zaprt = True


class _Dxgi:
    def __init__(self):
        self.st = 0
        self.ure = {}

    def slika_nova(self):
        self.st += 1
        self.ure[self.st] = zz.ura_ms()
        return self.st, True

    def zapri(self):
        pass


def _zajem(uposteva=True):
    vsi = []
    z = object.__new__(zz.H264Zajem)
    z._c = _Kodirnik(uposteva, vsi)
    z._dxgi = _Dxgi()
    z.fps = 60
    z._st = 0
    z._zigi = {}
    z._iz_bgra = lambda surova: _Okvir(surova)
    z._kljucni_zahtevan = threading.Event()
    z.kljucnih = 0
    z.obnov_kodirnika = 0
    z.kodirnik = "lazni"
    z._bitrate = 1
    z._odpri = lambda ime, br: _Kodirnik(uposteva, vsi)
    return z, vsi


def _teci(z, slik, zahteva_pri=()):
    """(zig, podatki, st slike) za `slik` paketov; pred paketom z indeksom iz `zahteva_pri` pride zahteva."""
    izhod = []
    for zig, podatki in z.okvirji_z_zigi(lambda: len(izhod) < slik):
        izhod.append((zig, podatki, podatki[-1]))
        if len(izhod) in zahteva_pri:
            z.zahtevaj_kljucni()
    return izhod


def _idr(podatki):
    return zz.H264Zajem._je_idr(podatki)


def test_kljucni_res_izsiljen_na_naslednji_sliki_z_sps():
    z, vsi = _zajem(uposteva=True)
    izhod = _teci(z, 10, zahteva_pri=(5,))
    vrste = [_idr(p) for _zig, p, _st in izhod]
    assert vrste == [True, False, False, False, False, True, False, False, False, False]
    assert izhod[5][1].startswith(SPS_PPS)                   # SPS/PPS iz prvega paketa pred izsiljenim IDR
    assert z.kljucnih == 1 and z.obnov_kodirnika == 0 and len(vsi) == 1
    for zig, _p, st in izhod:                                 # zig je se vedno cas zajema te slike
        assert zig is not None and abs(zig - z._dxgi.ure[st]) < 2.0


def test_kodirnik_brez_oznake_zamenjan_stari_zaprt():
    z, vsi = _zajem(uposteva=False)
    izhod = _teci(z, 12, zahteva_pri=(3,))
    vrste = [_idr(p) for _zig, p, _st in izhod]
    # zahteva pred paketom 3; 3, 4, 5 brez IDR (KLJUCNI_PAKETOV = 3), nato nov kontekst: paket 6 je IDR s SPS
    assert vrste == [True, False, False, False, False, False, True, False, False, False, False, False]
    assert izhod[6][1].startswith(SPS_PPS)
    assert z.obnov_kodirnika == 1 and z.kljucnih == 1 and len(vsi) == 2
    assert vsi[0].izpraznjen and vsi[0].zaprt                 # brez uhajanja: stari kontekst izpraznjen in zaprt
    assert not vsi[1].zaprt and z._c is vsi[1]


def test_vsak_stari_kontekst_zaprt_ob_vec_zahtevah():
    z, vsi = _zajem(uposteva=False)
    _teci(z, 20, zahteva_pri=(2, 10))
    assert z.obnov_kodirnika == 2 and len(vsi) == 3
    assert [k.zaprt for k in vsi] == [True, True, False]


def test_zahteva_pred_zacetkom_kodiranja_prva_slika():
    z, vsi = _zajem(uposteva=True)
    z.zahtevaj_kljucni()                                      # pred prvo sliko
    izhod = _teci(z, 3)
    assert [_idr(p) for _zig, p, _st in izhod] == [True, False, False]
    assert len(vsi) == 1 and z.obnov_kodirnika == 0


def test_zahteva_po_koncu_kodiranja_brez_ucinka():
    z, vsi = _zajem(uposteva=True)
    _teci(z, 2)
    z.zahtevaj_kljucni()                                      # generator je koncan: samo zastavica
    assert len(vsi) == 1 and z.obnov_kodirnika == 0 and z.kljucnih == 0


# ------------------------------------------------------------------ omejitev 1 na 2 s

def _uvozi_nz():
    lazni = {"safeer_windows.os_backend_win": types.ModuleType("safeer_windows.os_backend_win"),
             "safeer_windows.policy": types.ModuleType("safeer_windows.policy")}
    with mock.patch.dict(sys.modules, lazni):
        sys.modules.pop("safeer_windows.navidezni_zaslon", None)
        import safeer_windows.navidezni_zaslon as nz
    return nz


def test_omejitev_1_na_2_s_drsece_okno():
    nz = _uvozi_nz()
    casi = iter([0.0, 0.5, 1.99, 2.0, 2.1, 4.0, 1.0, float("nan")])
    o = nz.OmejevalnikKljucnih(ura=lambda: next(casi))
    assert [o.dovoli() for _ in range(8)] == [True, False, False, True, False, True, False, False]
    assert o.sprejetih == 3 and o.zavrnjenih == 5


class _Vhod:
    """Lazna vticnica vnosa: vrne kose po vrsti, nato konec (b"")."""

    def __init__(self, kosi):
        self.kosi = list(kosi)

    def recv(self, _n):
        return self.kosi.pop(0) if self.kosi else b""


def _zaslon(nz, seja=1):
    z = object.__new__(nz.NavidezniZaslon)
    z._tece, z._seja_st = True, seja
    z.kazalec_x = z.kazalec_y = 0
    return z


def test_neveljaven_json_in_tip_ne_ustavita_niti():
    nz = _uvozi_nz()
    z = _zaslon(nz)
    klici = []
    zajem = types.SimpleNamespace(zahtevaj_kljucni=lambda: klici.append(1))
    kljucni = nz.OmejevalnikKljucnih()
    vnos = types.SimpleNamespace(izvedi=lambda d: False)
    kosi = [b'{"vrsta":"kljucni"\n', b"[1,2]\n", b'"kljucni"\n', b'{"vrsta":5}\n', b"\xff\xfe\n",
            b"[" * 3000 + b"\n", b"x" * 5000 + b"\n", b"y" * (nz.NAJVEC_OSTANEK + 1),
            b'\n{"vrsta":"kljucni"}\n{"vrsta":"kljucni"}\n']
    nz.NavidezniZaslon._beri_povratni_vnos(z, _Vhod(kosi), vnos, 1, zajem, kljucni)
    assert klici == [1]                                       # prva veljavna sprejeta, druga v oknu zavrnjena
    assert kljucni.sprejetih == 1 and kljucni.zavrnjenih == 1


def test_zahteva_zunaj_seje_ne_naredi_nicesar():
    nz = _uvozi_nz()
    klici = []
    zajem = types.SimpleNamespace(zahtevaj_kljucni=lambda: klici.append(1))
    kljucni = nz.OmejevalnikKljucnih()
    z = _zaslon(nz, seja=2)
    assert z._zahteva_kljucni(zajem, kljucni, 1) is False     # po koncu: seja 1 je zamenjana
    z._tece = False
    assert z._zahteva_kljucni(zajem, kljucni, 2) is False     # pred zacetkom / po ustavi_sejo
    assert klici == [] and kljucni.sprejetih == 0 and kljucni.zavrnjenih == 0


# ------------------------------------------------------------------ okvir 4 po izsiljenem IDR

def _bralnik(tok: bytes):
    slike, zigi = [], []
    i = 0
    while i < len(tok):
        vrsta, dolzina = tok[i], int.from_bytes(tok[i + 1:i + 5], "big")
        telo = tok[i + 5:i + 5 + dolzina]
        i += 5 + dolzina
        if vrsta == 1:
            slike.append(telo)
        elif vrsta == 4:
            zigi.append(json.loads(telo))
    return slike, zigi


class _Vticnica:
    def __init__(self):
        self.klici = []

    def sendall(self, b):
        self.klici.append(bytes(b))

    def settimeout(self, _t):
        pass


def test_seja_tece_naprej_zig_in_bajt_pravilna():
    nz = _uvozi_nz()
    zahtevano = threading.Event()

    class _Zajem:
        fps, izvor, sirina, visina, kodirnik = 60, (1920, 1080), 1920, 1080, "lazni"
        kljucnih = obnov_kodirnika = 0

        def __init__(self, fps=60):
            pass

        def zahtevaj_kljucni(self):
            zahtevano.set()

        def okvirji_z_zigi(self, tece):
            yield 100.0, SPS_PPS + b"\x00\x00\x00\x01\x65" + b"a" * 10
            yield 116.0, b"\x00\x00\x00\x01\x41" + b"b" * 3
            assert zahtevano.wait(2.0)
            _Zajem.kljucnih = 1
            yield 133.0, SPS_PPS + b"\x00\x00\x00\x01\x65" + b"c" * 20
            yield 150.0, b"\x00\x00\x00\x01\x41" + b"d"

        def zapri(self):
            pass

    def _vnos(self, odjemalec, vnos, seja, zajem, kljucni):
        self._zahteva_kljucni(zajem, kljucni, seja)
        time.sleep(0.5)

    v = _Vticnica()
    z = object.__new__(nz.NavidezniZaslon)
    z._tece, z._seja_st, z._kljuc, z._prevzete = True, 1, threading.Lock(), {}
    posluh = object()
    z._posluh = posluh
    lazni = types.SimpleNamespace(H264Zajem=_Zajem, zvok_na_voljo=lambda: False, ZVOK_HZ=48000, ZVOK_KANALI=2, glava_toka=zz.glava_toka,
                                  WindowsVnos=lambda izvor, slika: types.SimpleNamespace(sprosti_vse=lambda: None))
    with mock.patch.object(nz, "zajem_zaslona", lazni), \
            mock.patch.object(nz.NavidezniZaslon, "_sprejmi", lambda self, p, c: v), \
            mock.patch.object(nz.NavidezniZaslon, "_beri_povratni_vnos", _vnos), \
            mock.patch.object(nz.NavidezniZaslon, "_posiljaj_kazalec", lambda self, *a: None), \
            mock.patch.object(nz.NavidezniZaslon, "ustavi_sejo", lambda self, s=None: None), \
            mock.patch.object(nz, "_zapri", lambda s: None), \
            mock.patch.object(nz.link_vticnik, "zavaruj", lambda o: o):
        z._streci_sejo(posluh, None, 60, 1)
    slike, zigi = _bralnik(b"".join(v.klici[1:]))
    assert len(slike) == 4                                    # seja ni prekinjena
    dolzine = [len(s) for s in slike]
    assert [g["bajt"] for g in zigi] == [0, dolzine[0], dolzine[0] + dolzine[1], sum(dolzine[:3])]
    assert [g["zig_ms"] for g in zigi] == [100, 116, 133, 150]
    assert all(g["vrsta"] == 1 for g in zigi)


# ------------------------------------------------------------------ dodatni preizkusi (pregled WK-1..WK-7)

def _zajem_z(tovarna):
    """Kot _zajem, a z drugim laznim kodirnikom: tovarna(vsi) -> kodirnik."""
    z, vsi = _zajem()
    vsi.clear()
    z._c = tovarna(vsi)
    z._odpri = lambda ime, br: tovarna(vsi)
    return z, vsi


class _ZakasnjenKodirnik(_Kodirnik):
    """Kot _Kodirnik, a paket slike vrne sele `zamik` slik pozneje (kot strojni kodirnik z vrsto)."""

    def __init__(self, zamik, uposteva=True, vsi=None):
        super().__init__(uposteva, vsi)
        self.zamik = zamik
        self.cakajo = []

    def encode(self, okvir):
        if okvir is None:
            self.izpraznjen = True
            ven, self.cakajo = self.cakajo, []
            return ven
        self.cakajo.extend(super().encode(okvir))
        ven = []
        while len(self.cakajo) > self.zamik:
            ven.append(self.cakajo.pop(0))
        return ven


# SEI pred SPS: SPS se zacne pri bajtu 1018 in konca za mejo 1024.
_SEI = b"\x00\x00\x00\x01\x06" + b"\x05" * 1013
_DOLG_SPS = b"\x00\x00\x00\x01\x67" + b"\x64" * 40
_PPS = b"\x00\x00\x00\x01\x68\xee\x3c\x80"


class _KodirnikDolgaGlava(_Kodirnik):
    """Prvi paket konteksta: dolg SEI, SPS cez mejo 1024, PPS in IDR."""

    def encode(self, okvir):
        if okvir is not None and self.prvi:
            self.prvi = False
            return [_Paket(okvir.pts, _SEI + _DOLG_SPS + _PPS + b"\x00\x00\x00\x01\x65" + bytes([okvir.st % 256]))]
        return super().encode(okvir)


class _KodirnikBrezPts(_Kodirnik):
    """Kodirnik, ki paketom ne da pts."""

    def encode(self, okvir):
        paketi = super().encode(okvir)
        for p in paketi:
            p.pts = None
        return paketi


def test_wk8_nastavitve_rstrip_tocno_brez_bajta_zacetne_kode():
    # 4-bajtna koda za PPS in IDR: prvi bajt kode (00) ne sme ostati na koncu SPS ali PPS.
    assert zz.H264Zajem._nastavitve(SPS_PPS + b"\x00\x00\x00\x01\x65\x88") == SPS_PPS
    assert zz.H264Zajem._nastavitve(SPS_PPS + b"\x00\x00" + b"\x00\x00\x00\x01\x65\x88") == SPS_PPS


def test_wk8_tribajtna_koda_in_idr_ne_na_zacetku():
    tri = b"\x00\x00\x01\x67\x64\x00\x28\x00\x00\x01\x68\xee\x3c\x80\x00\x00\x01\x65\x88"
    assert zz.H264Zajem._nastavitve(tri) == SPS_PPS
    assert zz.H264Zajem._je_idr(b"\x00\x00\x01\x09\xf0\x00\x00\x01\x06\x05\x00\x00\x01\x65\x88")
    assert not zz.H264Zajem._je_idr(b"\x00\x00\x01\x09\xf0\x00\x00\x01\x41\x9a")
    assert not zz.H264Zajem._je_idr(b"\x00\x00\x01")


def test_wk2_sps_cez_mejo_1024_ni_odrezan():
    assert zz.H264Zajem._nastavitve(_SEI + _DOLG_SPS + _PPS + b"\x00\x00\x00\x01\x65\x88") == _DOLG_SPS + _PPS
    z, vsi = _zajem_z(lambda vsi: _KodirnikDolgaGlava(True, vsi))
    izhod = _teci(z, 8, zahteva_pri=(5,))
    assert _idr(izhod[5][1]) and izhod[5][1].startswith(_DOLG_SPS + _PPS)   # cel SPS/PPS pred izsiljenim IDR
    assert z.obnov_kodirnika == 0 and len(vsi) == 1


def test_wk3_zakasnjen_kodirnik_ni_zamenjan():
    z, vsi = _zajem_z(lambda vsi: _ZakasnjenKodirnik(3, True, vsi))
    izhod = _teci(z, 12, zahteva_pri=(4,))
    vrste = [_idr(p) for _zig, p, _st in izhod]
    # zahteva po 4. paketu oznaci sliko s pts 7; paketi slik 4, 5, 6 so bili v kodirniku ze prej
    assert vrste == [True] + [False] * 6 + [True] + [False] * 4
    assert izhod[7][1].startswith(SPS_PPS)
    assert z.obnov_kodirnika == 0 and len(vsi) == 1 and z.kljucnih == 1


def test_wk3_zakasnjen_kodirnik_brez_oznake_se_vedno_zamenjan():
    z, vsi = _zajem_z(lambda vsi: _ZakasnjenKodirnik(3, False, vsi))
    _teci(z, 16, zahteva_pri=(4,))
    assert z.obnov_kodirnika == 1 and len(vsi) == 2 and vsi[0].zaprt


def test_wk6_zigi_omejeni_ce_kodirnik_ne_vraca_pts(monkeypatch):
    monkeypatch.setattr(zz, "NAJVEC_ZIGOV", 5, raising=False)
    z, _vsi = _zajem_z(lambda vsi: _KodirnikBrezPts(True, vsi))
    izhod = _teci(z, 20)
    assert all(zig is None for zig, _p, _st in izhod)
    assert 0 < len(z._zigi) <= 5
    assert sorted(z._zigi) == list(range(max(z._zigi) - len(z._zigi) + 1, max(z._zigi) + 1))   # najnovejsi


class _ZaprtKodirnik:
    """Kontekst, ki ga je nit kodiranja ze zamenjala in zaprla: branje pix_fmt pade."""

    @property
    def pix_fmt(self):
        raise RuntimeError("kontekst je zaprt")


def test_wk1_nit_zajema_ne_bere_konteksta():
    oblike = []

    class _VF:
        def __init__(self, s, v, f):
            self.width, self.height = s, v
            self.planes = [types.SimpleNamespace(line_size=s * 4, update=lambda a: None)]

        @classmethod
        def from_image(cls, slika):
            return cls(*slika.size, "rgb24")

        def reformat(self, width=None, height=None, format=None, threads=None):
            oblike.append(format)
            return self

    slika = types.SimpleNamespace(size=(4, 2))
    pil = types.ModuleType("PIL")
    pil.ImageGrab = types.SimpleNamespace(grab=lambda: slika)
    z = object.__new__(zz.H264Zajem)
    z._av = types.SimpleNamespace(VideoFrame=_VF)
    z.sirina, z.visina, z._st, z._dxgi, z._pix_fmt = 4, 2, 0, None, "nv12"
    z._c = _ZaprtKodirnik()                                   # nit kodiranja je kontekst ravno zamenjala
    surova = types.SimpleNamespace(shape=(2, 4, 4), flags={"C_CONTIGUOUS": True})
    z._iz_bgra(surova)                                        # DXGI
    with mock.patch.dict(sys.modules, {"PIL": pil}):
        z._slika()                                            # GDI
    assert oblike == ["nv12", "nv12"]


class _LazniKontekst:
    def __init__(self, ime, napaka_idr=False, napaka=False):
        self.ime, self.napaka_idr, self.napaka, self.options = ime, napaka_idr, napaka, {}

    def open(self):
        if self.napaka or (self.napaka_idr and set(self.options) & {"forced-idr", "forced_idr"}):
            raise RuntimeError("lazna napaka " + self.ime)


def test_wk1_init_nastavi_obliko_slike():
    av = types.ModuleType("av")
    av.codecs_available = ("libx264",)
    av.CodecContext = types.SimpleNamespace(create=lambda ime, n: _LazniKontekst(ime))
    pil = types.ModuleType("PIL")
    pil.ImageGrab = object()
    with mock.patch.dict(sys.modules, {"av": av, "PIL": pil}), mock.patch.object(zz.sys, "platform", "linux"):
        z = zz.H264Zajem(fps=30, bitrate=1)
    assert z._pix_fmt == "yuv420p" and z._c.pix_fmt == "yuv420p"


def test_wk4_prvi_vzrok_odpiranja_zapisan(capsys):
    z = object.__new__(zz.H264Zajem)
    z.sirina, z.visina, z.fps = 4, 2, 60
    z._av = types.SimpleNamespace(CodecContext=types.SimpleNamespace(
        create=lambda ime, n: _LazniKontekst(ime, napaka_idr=True)))
    c = z._odpri("h264_nvenc", 1)
    assert "forced-idr" not in c.options                      # rezerva brez IDR moznosti
    assert "lazna napaka h264_nvenc" in capsys.readouterr().out
    z._av = types.SimpleNamespace(CodecContext=types.SimpleNamespace(
        create=lambda ime, n: _LazniKontekst(ime, napaka=True)))
    with pytest.raises(RuntimeError):
        z._odpri("libx264", 1)                                # brez IDR moznosti: napaka gre naprej kot prej


def test_wk5_rep_predolge_vrstice_ni_dogodek():
    nz = _uvozi_nz()
    for kosi in ([b"x" * (nz.NAJVEC_OSTANEK + 1), b'{"vrsta":"kljucni"}\n', b'{"vrsta":"kljucni"}\n'],
                 [b"x" * (nz.NAJVEC_OSTANEK + 1), b"x" * 100, b'{"vrsta":"kljucni"}\n{"vrsta":"kljucni"}\n']):
        z = _zaslon(nz)
        klici = []
        zajem = types.SimpleNamespace(zahtevaj_kljucni=lambda: klici.append(1))
        kljucni = nz.OmejevalnikKljucnih()
        vnos = types.SimpleNamespace(izvedi=lambda d: False)
        nz.NavidezniZaslon._beri_povratni_vnos(z, _Vhod(kosi), vnos, 1, zajem, kljucni)
        # rep predolge vrstice se zavrze; prva cela vrstica za njim je edina sprejeta zahteva
        assert klici == [1] and kljucni.sprejetih == 1 and kljucni.zavrnjenih == 0


def test_wk7_oznaci_kljucni_s_pyav_picturetype():
    oznaka = object()
    okvir = _Okvir(0)
    with mock.patch.dict(sys.modules, _lazni_av(oznaka)):
        assert zz.H264Zajem._oznaci_kljucni(None, okvir) is True
    assert okvir.pict_type is oznaka


def test_wk7_oznaci_kljucni_brez_picturetype_niz():
    okvir = _Okvir(0)
    with mock.patch.dict(sys.modules, {"av.video.frame": None}):   # starejsi PyAV: uvoz pade
        assert zz.H264Zajem._oznaci_kljucni(None, okvir) is True
    assert okvir.pict_type == "I"

    class _Brez:
        __slots__ = ()

    with mock.patch.dict(sys.modules, {"av.video.frame": None}):
        assert zz.H264Zajem._oznaci_kljucni(None, _Brez()) is False
