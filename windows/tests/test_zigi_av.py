"""Zigi zajema A/V na Windows (zajem_zaslona.py + navidezni_zaslon.py) z laznimi moduli - brez Windows,
brez dxcam, soundcard in PyAV.

Kaj mora veljati:
- zig zvoka je iz stetja vzorcev (razmik tocno 10 ms), tudi cez izpusceno tisino;
- zig slike je cas zajema te slike, ne cas izhoda iz kodirnika (kodirnik, ki sliko zadrzi);
- pts gredo v kodirnik zaporedno, tudi ko vrsta slike zavrze;
- pocasen kodirnik: polna vrsta zavrze NAJSTAREJSO sliko, zamik zajem -> kodiranje ne raste;
- okvir ZIG gre v istem sendall pred svojim okvirjem; stari bralnik (preskoci neznano vrsto) dobi enake bajte;
- glava ima kljuc "zig"; brez *_z_zigi (stari ali lazni zajem) tok ostane brez okvirjev 4.
"""
import json
import queue
import sys
import threading
import time
import types
from unittest import mock

import pytest

from safeer_windows import zajem_zaslona as zz


# ------------------------------------------------------------------ lazni zvok (soundcard)

class _Polje:
    """Dovolj numpy-ja za kosi_zvoka_z_zigi: shape, size, any, clip, astype, tobytes."""

    def __init__(self, n, tiho):
        self.shape = (n, 2)
        self.size = n * 2
        self._tiho = tiho

    def any(self):
        return not self._tiho

    def clip(self, *_a):
        return self

    def __mul__(self, _x):
        return self

    def astype(self, _t):
        return self

    def tobytes(self):
        return bytes(self.size * 2)


def _lazni_soundcard(kosi, ura):
    """kosi: seznam True (tih) / False; vsak record premakne lazno uro za 10 ms (+ tresenje)."""
    stanje = {"i": 0}

    class _Zapis:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def record(self, numframes):
            i = stanje["i"]
            stanje["i"] += 1
            ura[0] += 10.0 + (3.0 if i % 2 else -3.0)     # tresenje branja +-3 ms
            return _Polje(numframes, kosi[i])

    mik = types.SimpleNamespace(recorder=lambda **k: _Zapis())
    sc = types.SimpleNamespace(default_speaker=lambda: types.SimpleNamespace(name="z"),
                               get_microphone=lambda **k: mik)
    return sc, stanje


def test_zvok_zig_iz_stetja_vzorcev_tudi_cez_tisino():
    tihi = [False] * 3 + [True] * 38 + [False] * 9          # 38 tihih: 30 gre ven, 8 izpustimo
    ura = [1000.0]
    sc, stanje = _lazni_soundcard(tihi, ura)
    with mock.patch.dict(sys.modules, {"soundcard": sc}), mock.patch.object(zz, "ura_ms", lambda: ura[0]):
        zigi = [z for z, _ in zz.kosi_zvoka_z_zigi(lambda: stanje["i"] < len(tihi))]
    assert len(zigi) == 3 + 30 + 9
    assert zigi[0] is None                                   # prvi kos: brez primerjave ni znano, ali je cakal (WK-11)
    zigi = zigi[1:]
    assert None not in zigi
    razmiki = [round(b - a, 6) for a, b in zip(zigi, zigi[1:])]
    assert razmiki[:31] == [10.0] * 31                      # brez tresenja branja
    assert razmiki[31] == 90.0                               # 8 izpuscenih + 1: stetje tudi neposlanih
    assert razmiki[32:] == [10.0] * 8


def test_zvok_brez_zigov_ostane_isti_vmesnik():
    tihi = [False] * 5
    ura = [0.0]
    sc, stanje = _lazni_soundcard(tihi, ura)
    with mock.patch.dict(sys.modules, {"soundcard": sc}), mock.patch.object(zz, "ura_ms", lambda: ura[0]):
        kosi = list(zz.kosi_zvoka(lambda: stanje["i"] < len(tihi)))
    assert all(isinstance(k, bytes) and len(k) == zz.ZVOK_KOS * 4 for k in kosi)


# ------------------------------------------------------------------ lazna slika (dxcam + PyAV)

class _Okvir:
    def __init__(self, st):
        self.st = st
        self.pts = None


class _Paket:
    def __init__(self, pts, st):
        self.pts = pts
        self._b = b"\x00\x00\x00\x01\x67" + bytes([st % 256])

    def __bytes__(self):
        return self._b


class _Kodirnik:
    """Zadrzi `zadrzi` slik; vsak encode traja `traja_s`. Belezi pts, ki jih dobi."""

    def __init__(self, zadrzi=0, traja_s=0.0):
        self.zadrzi, self.traja_s = zadrzi, traja_s
        self.notri = []
        self.prejeti_pts = []
        self.extradata = b""
        self.pix_fmt = "nv12"

    def encode(self, okvir):
        if okvir is None:
            return []
        if self.traja_s:
            time.sleep(self.traja_s)
        self.prejeti_pts.append(okvir.pts)
        self.notri.append(okvir)
        ven = []
        while len(self.notri) > self.zadrzi:
            o = self.notri.pop(0)
            ven.append(_Paket(o.pts, o.st))
        return ven


class _Dxgi:
    """Vsak klic da novo sliko; zabelezi uro zajema za vsako sliko (po st)."""

    def __init__(self):
        self.st = 0
        self.ure = {}

    def slika_nova(self):
        self.st += 1
        self.ure[self.st] = zz.ura_ms()
        return self.st, True

    def zapri(self):
        pass


def _zajem(kodirnik, fps=60):
    z = object.__new__(zz.H264Zajem)
    z._c = kodirnik
    z._dxgi = _Dxgi()
    z.fps = fps
    z._st = 0
    z._zigi = {}
    z._iz_bgra = lambda surova: _Okvir(surova)
    return z


def _teci(z, slik):
    izhod = []
    for zig, podatki in z.okvirji_z_zigi(lambda: len(izhod) < slik):
        izhod.append((zig, podatki[-1], zz.ura_ms()))
    return izhod


def test_slika_zig_je_cas_zajema_tudi_ko_kodirnik_zadrzi():
    k = _Kodirnik(zadrzi=1)
    z = _zajem(k)
    izhod = _teci(z, 20)
    for zig, st, _ven in izhod:
        assert zig is not None
        assert abs(zig - z._dxgi.ure[st]) < 2.0, "zig mora biti zajem slike st=%d" % st
    assert len(z._zigi) <= 2                                  # le slike, ki so se v kodirniku


def test_pts_v_kodirnik_zaporedni():
    k = _Kodirnik(zadrzi=0, traja_s=0.03)                    # pocasen: vrsta zavraca slike
    z = _zajem(k)
    _teci(z, 15)
    assert k.prejeti_pts == list(range(len(k.prejeti_pts)))


def test_pocasen_kodirnik_zavrze_najstarejso_zamik_ne_raste():
    """Kodiranje 50 ms, zajem do 60/s. Ce zajem caka na prostor (stara koda), gre v kodirnik slika, ki je cakala v
    polni vrsti - zamik zajem->izhod ~200 ms (zigi2 brez zavrzenja). Z zavrzenjem najstarejse ostane ~1 kodiranje
    + manj kot interval."""
    k = _Kodirnik(zadrzi=0, traja_s=0.05)
    z = _zajem(k)
    izhod = _teci(z, 12)[3:]                                  # prve slike: vrsta se se polni
    zamiki = sorted(ven - zig for zig, _st, ven in izhod)
    mediana = zamiki[len(zamiki) // 2]
    assert mediana < 100.0, "zamik zajem->izhod %.1f ms" % mediana


def test_v_vrsto_obdrzi_najnovejsa():
    v = queue.Queue(maxsize=2)
    for i in range(5):
        zz._v_vrsto(v, i)
    assert [v.get_nowait(), v.get_nowait()] == [3, 4]


# ------------------------------------------------------------------ klicatelj: okvirji na vticnici

def _uvozi_nz():
    """navidezni_zaslon brez Windows: os_backend_win in policy zamenjamo, core je pravi."""
    lazni = {"safeer_windows.os_backend_win": types.ModuleType("safeer_windows.os_backend_win"),
             "safeer_windows.policy": types.ModuleType("safeer_windows.policy")}
    with mock.patch.dict(sys.modules, lazni):
        sys.modules.pop("safeer_windows.navidezni_zaslon", None)
        import safeer_windows.navidezni_zaslon as nz
    return nz


def _stari_bralnik(tok: bytes):
    """Kot ZaslonOdjemalec.crpaj in oddaljeni_zaslon: vrsta, dolzina, telo; neznano vrsto preskoci."""
    slike, zvok, zigi = [], [], []
    i = 0
    while i < len(tok):
        vrsta, dolzina = tok[i], int.from_bytes(tok[i + 1:i + 5], "big")
        assert 0 < dolzina <= 8 * 1024 * 1024
        telo = tok[i + 5:i + 5 + dolzina]
        i += 5 + dolzina
        if vrsta == 1:
            slike.append(telo)
        elif vrsta == 2:
            zvok.append(telo)
        elif vrsta == 4:
            zigi.append(json.loads(telo))
    return slike, zvok, zigi


class _Vticnica:
    def __init__(self):
        self.klici = []

    def sendall(self, b):
        self.klici.append(bytes(b))

    def settimeout(self, _t):
        pass


def test_okvir_zig_v_istem_sendall_in_stari_bralnik_dobi_iste_bajte():
    nz = _uvozi_nz()
    kosi = [bytes([7]) * n for n in (100, 3, 50)]
    zigi = iter([1000.4, 1010.4, 1020.6])
    lazni = types.SimpleNamespace(kosi_zvoka_z_zigi=lambda tece: ((next(zigi), k) for k in kosi))
    z = object.__new__(nz.NavidezniZaslon)
    z._tece, z._seja_st = True, 1
    v = _Vticnica()
    with mock.patch.object(nz, "zajem_zaslona", lazni):
        z._posiljaj_zvok(v, 1)
    assert len(v.klici) == 3                                  # en sendall na kos, ZIG v njem
    for klic in v.klici:
        assert klic[0] == nz.OKVIR_ZIG
    slike, zvok, zz_ = _stari_bralnik(b"".join(v.klici))
    assert zvok == kosi and slike == []
    assert zz_ == [{"vrsta": 2, "zig_ms": 1000, "bajt": 0}, {"vrsta": 2, "zig_ms": 1010, "bajt": 100},
                   {"vrsta": 2, "zig_ms": 1021, "bajt": 103}]


def test_brez_z_zigi_tok_kot_prej():
    nz = _uvozi_nz()
    lazni = types.SimpleNamespace(kosi_zvoka=lambda tece: iter([b"ab", b"c"]))
    z = object.__new__(nz.NavidezniZaslon)
    z._tece, z._seja_st = True, 1
    v = _Vticnica()
    with mock.patch.object(nz, "zajem_zaslona", lazni):
        z._posiljaj_zvok(v, 1)
    assert v.klici == [b"\x02\x00\x00\x00\x02ab", b"\x02\x00\x00\x00\x01c"]


def test_glava_ima_zig_in_slika_ima_zige():
    nz = _uvozi_nz()

    class _Zajem:
        fps, izvor, sirina, visina, kodirnik = 60, (1920, 1080), 1920, 1080, "lazni"

        def __init__(self, fps=60):
            pass

        def okvirji_z_zigi(self, tece):
            yield 500.0, b"\x00\x00\x00\x01\x65" + b"x" * 10
            yield None, b"\x00\x00\x00\x01\x41" + b"y" * 4     # neznan zig: brez okvirja 4

        def zapri(self):
            pass

    v = _Vticnica()
    z = object.__new__(nz.NavidezniZaslon)
    z._tece, z._seja_st, z._kljuc, z._prevzete = True, 1, threading.Lock(), {}
    posluh = object()
    z._posluh = posluh
    lazni = types.SimpleNamespace(H264Zajem=_Zajem, zvok_na_voljo=lambda: False, ZVOK_HZ=48000, ZVOK_KANALI=2, glava_toka=zz.glava_toka,
                                  WindowsVnos=lambda izvor, slika: types.SimpleNamespace(sprosti_vse=lambda: None))
    with mock.patch.object(nz, "zajem_zaslona", lazni), \
            mock.patch.object(nz.NavidezniZaslon, "_sprejmi", lambda self, p, c: v), \
            mock.patch.object(nz.NavidezniZaslon, "_beri_povratni_vnos", lambda self, *a: time.sleep(0.5)), \
            mock.patch.object(nz.NavidezniZaslon, "_posiljaj_kazalec", lambda self, *a: None), \
            mock.patch.object(nz.NavidezniZaslon, "ustavi_sejo", lambda self, s=None: None), \
            mock.patch.object(nz, "_zapri", lambda s: None), \
            mock.patch.object(nz.link_vticnik, "zavaruj", lambda o: o):
        z._streci_sejo(posluh, None, 60, 1)
    glava = json.loads(v.klici[0].decode("utf-8"))
    assert glava["zig"] == {"okvir": 4, "ura": "monotonic_ms"} and glava["au"] is True
    slike, _zvok, zigi = _stari_bralnik(b"".join(v.klici[1:]))
    assert len(slike) == 2
    assert zigi == [{"vrsta": 1, "zig_ms": 500, "bajt": 0}]
    assert v.klici[1][0] == 4 and v.klici[2][0] == 1          # drugi paket: brez ziga, samo okvir 1
