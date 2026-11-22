"""Zigi zvoka na Windows oddajniku (windows/safeer_windows/zajem_zaslona.py) z laznim modulom soundcard, brez Windows.

Enako nacelo kot tests/test_link_zaslon_zigi.py (Linux): zig None med zaostankom, zig nikoli nazaj (cele ms),
poravnava sele po ZVOK_OKNO_MS, poravnava v dnevniku.
"""

import importlib.util
import os
import sys
import types

KOS = 480          # vzorcev na kanal = 10 ms pri 48 kHz


def _nalozi():
    # Ta datoteka je v windows/tests/, modul pa v windows/safeer_windows/: samo ta pot, brez iskanja kopij
    # (build/, dist/ ali stara kopija bi sicer lahko prisla prej po abecedi).
    pot = _pot_modula(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    spec = importlib.util.spec_from_file_location("win_zajem_zaslona_test", pot)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def _pot_modula(koren):
    pot = os.path.join(koren, "safeer_windows", "zajem_zaslona.py")
    if not os.path.isfile(pot):
        raise FileNotFoundError(pot)
    return pot


zz = _nalozi()
ZigiZvoka = zz.ZigiZvoka


# ------------------------------------------------------------------ lazni soundcard

class _Polje:
    """Kar uporabi kosi_zvoka_z_zigi od polja numpy: size, shape, any, clip, *, astype, tobytes."""

    def __init__(self, n, tiho=False):
        self.n, self.tiho = n, tiho
        self.size, self.shape = n * 2, (n, 2)

    def any(self):
        return not self.tiho

    def clip(self, a, b):
        return self

    def __mul__(self, x):
        return self

    def astype(self, t):
        return self

    def tobytes(self):
        return (b"\x00" if self.tiho else b"\x01") * (self.n * 4)


def _soundcard(polja):
    zapis = types.SimpleNamespace(record=lambda numframes: polja.pop(0))

    class _Snemalnik:
        def __enter__(self):
            return zapis

        def __exit__(self, *a):
            return False

    sc = types.ModuleType("soundcard")
    sc.default_speaker = lambda: types.SimpleNamespace(name="zvocnik")
    sc.get_microphone = lambda id, include_loopback: types.SimpleNamespace(recorder=lambda **k: _Snemalnik())
    return sc


def _kosi(monkeypatch, polja, casi):
    """Pozene kosi_zvoka_z_zigi: polja gredo iz record, casi iz ura_ms (en klic na neprazen kos)."""
    polja, casi = list(polja), iter(casi)
    monkeypatch.setitem(sys.modules, "soundcard", _soundcard(polja))
    monkeypatch.setattr(zz, "ura_ms", lambda: next(casi))
    return list(zz.kosi_zvoka_z_zigi(lambda: bool(polja)))


def test_nalozi_vzame_pravi_modul_ne_kopije(tmp_path):
    for mapa in ("build/lib/safeer_windows", "safeer_windows"):
        (tmp_path / mapa).mkdir(parents=True)
        (tmp_path / mapa / "zajem_zaslona.py").write_text("")
    assert _pot_modula(str(tmp_path)) == os.path.join(str(tmp_path), "safeer_windows", "zajem_zaslona.py")


# ------------------------------------------------------------------ ZigiZvoka

def test_enakomeren_tok_zig_iz_stetja():
    z = ZigiZvoka()
    zigi = [z.zig(KOS, 1000.0 + 10 * k) for k in range(20)]
    assert zigi[0] is None                     # prvi kos: brez primerjave
    assert all(abs(zigi[k] - (990.0 + 10 * k)) < 1e-9 for k in range(1, 20))


def test_zastoj_pisanja_sunek_brez_ziga_in_brez_poravnave():
    z = ZigiZvoka()
    for k in range(30):
        z.zig(KOS, 1000.0 + 10 * k)
    # Klicatelj 80 ms ne bere (sendall), nato 9 kosov iz medpomnilnika WASAPI naenkrat.
    sunek = [z.zig(KOS, 1380.0) for _ in range(9)]
    zigi = [z.zig(KOS, 1390.0 + 10 * k) for k in range(40)]
    assert z.poravnav == 0
    assert sunek[:4] == [None] * 4             # zaostanek 80..50 ms > ZVOK_PORAVNAJ_MS
    assert all(abs(sunek[k] - (1290.0 + 10 * k)) < 1e-9 for k in range(4, 9))
    assert all(abs(zigi[k] - (1380.0 + 10 * k)) < 1e-9 for k in range(40))


def test_vrzel_poravna_po_oknu_med_zaostankom_brez_ziga():
    z = ZigiZvoka()
    for k in range(30):
        z.zig(KOS, 1000.0 + 10 * k)
    # WASAPI izpusti 100 ms: od zdaj vsak kos pride 100 ms pozneje, kot pravi stetje.
    zigi = [z.zig(KOS, 1400.0 + 10 * k) for k in range(60)]
    assert z.poravnav == 1 and z.zadnja_poravnava_ms == 100.0
    assert zigi[:20] == [None] * 20
    assert all(abs(zigi[k] - (1390.0 + 10 * k)) < 1e-9 for k in range(20, 60))


def test_zig_ms_po_zaokrozitvi_ne_gre_nazaj():
    z = ZigiZvoka()
    # 24 vzorcev = 0,5 ms: drugi kos 999,5 (na TV 1000), tretji 999,0 (na TV 999).
    zigi = [z.zig(KOS, 1000.0), z.zig(24, 1000.0), z.zig(KOS, 1009.0), z.zig(KOS, 1019.0)]
    assert zigi[0] is None
    assert abs(zigi[1] - 999.5) < 1e-9
    assert zigi[2] is None
    assert abs(zigi[3] - 1009.0) < 1e-9


def test_sunek_ob_zagonu_ne_da_prepoznega_ziga():
    z = ZigiZvoka()
    # Ob zagonu WASAPI vrne 5 kosov naenkrat (cakali so v medpomnilniku), nato enakomerno.
    zigi = [z.zig(KOS, 1000.0) for _ in range(5)] + [z.zig(KOS, 1010.0 + 10 * k) for k in range(20)]
    assert zigi[:5] == [None] * 5              # zacetek se premika nazaj za 10 ms > ZVOK_TOCNOST_MS
    # Spodnja ovojnica: sesti kos (prebran ob 1010) je zajet ob 1000, kosi sunka ob 950..990.
    assert all(abs(zigi[5 + k] - (1000.0 + 10 * k)) < 1e-9 for k in range(20))


def test_pocasno_praznjenje_zaloge_ne_da_poznih_zigov():
    z = ZigiZvoka()
    # 30 kosov enakomerno, nato bralec 100 ms obstane (sendall) in zalogo prazni po 9,5 ms na kos (10 ms zvoka).
    casi = [1000.0 + 10 * k for k in range(30)]
    casi += [1400.0 + 9.5 * (k - 30) for k in range(30, 231)]
    casi += [1000.0 + 10 * k for k in range(231, 300)]
    zigi = [z.zig(KOS, c) for c in casi]
    # Kos k je zajet ob 990 + 10 k. Brez popravka gre po lazni poravnavi (k = 49) kos 50 z zigom 1580 (90 ms pozno).
    assert all(abs(zigi[k] - (990.0 + 10 * k)) <= zz.ZVOK_TOCNOST_MS for k in range(300) if zigi[k] is not None)
    assert zigi[299] is not None


def test_neveljaven_kos_brez_ziga():
    z = ZigiZvoka()
    assert z.zig(0, 1000.0) is None
    assert z.zig(KOS, float("nan")) is None


# ------------------------------------------------------------------ kosi_zvoka_z_zigi (lazni WASAPI)

def test_generator_zastoj_pisanja_zig_ne_skoci_in_ne_gre_nazaj(monkeypatch):
    polja = [_Polje(KOS) for _ in range(39 + 10)]
    casi = [1000.0 + 10 * k for k in range(30)] + [1380.0] * 9 + [1390.0 + 10 * k for k in range(10)]
    izid = _kosi(monkeypatch, polja, casi)
    zigi = [z for z, _ in izid]
    # Brez popravka: kos 30 dobi 1370 (80 ms prepozen), kos 35 pa spet 1370 (nazaj s 1410).
    assert zigi[30:34] == [None] * 4
    poslani = [int(round(x)) for x in zigi if x is not None]
    assert poslani == sorted(poslani)
    assert all(abs(zigi[k] - (990.0 + 10 * k)) < 1e-9 for k in range(34, 49))
    assert all(len(pcm) == KOS * 4 for _, pcm in izid)     # PCM nespremenjen


def test_generator_tihi_kosi_se_stejejo(monkeypatch):
    polja = [_Polje(KOS)] * 5 + [_Polje(KOS, tiho=True)] * 40 + [_Polje(KOS)] * 3
    casi = [1000.0 + 10 * k for k in range(48)]
    izid = _kosi(monkeypatch, polja, casi)
    # 5 zvocnih + 30 tihih (rep) + 3 zvocni; izpusceni tihi se stejejo, zato je zig po tisini pravi.
    assert len(izid) == 5 + zz.ZVOK_REP_TISINE + 3
    assert abs(izid[-1][0] - (990.0 + 10 * 47)) < 1e-9


def test_generator_poravnava_v_dnevniku(monkeypatch, capsys):
    polja = [_Polje(KOS) for _ in range(51)]
    casi = [1000.0 + 10 * k for k in range(30)] + [1400.0 + 10 * k for k in range(21)]
    izid = _kosi(monkeypatch, polja, casi)
    zigi = [z for z, _ in izid]
    assert zigi[30:50] == [None] * 20 and abs(zigi[50] - 1590.0) < 1e-9
    err = capsys.readouterr().err
    assert "dogodek=zvok_poravnava" in err and " ms=100 stevilo=1" in err


def test_kosi_zvoka_brez_zigov_nespremenjen(monkeypatch):
    polja = [_Polje(KOS) for _ in range(3)]
    casi = iter([1000.0, 1010.0, 1020.0])
    monkeypatch.setitem(sys.modules, "soundcard", _soundcard(polja))
    monkeypatch.setattr(zz, "ura_ms", lambda: next(casi))
    assert list(zz.kosi_zvoka(lambda: bool(polja))) == [b"\x01" * KOS * 4] * 3
