"""Gledalec Windows po specifikaciji izvora Linux (nacrti/zaslon-ostrina-kazalec.md, 25. 10. 2026).

Lastnik (09:09-09:13): brez obcutka zamegljenosti, en kazalec, vrstica »LAN · 1 Gb/s · neposredno · locljivost · fps«.
- zmoznosti kazalec/izvorna/brezizgubno/profil v screen.start (vir Linux delo-133 jih zna, starejsi jih prezre);
- glava »kazalec«: izvor kazalca ne rise v sliko, lokalni kazalec dobi obliko ali tocno sliko kazalca izvora;
- en preoblikovalnik (SwsContext) za vso sejo - prej 28,9 ms na sliko (prikaz 21,5 slike/s v lastnikovi seji);
- brezizgubni tok (H.264 RGB qp 0) na platnu pikselsko enak izvoru;
- nacin »1:1« si okno zapomni.
"""
import base64
import os
import sys
import threading
import time
import types
from pathlib import Path

import pytest

KOREN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KOREN))
sys.path.insert(0, str(KOREN / "windows"))
pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from safeer_windows import oddaljeni_zaslon as oz  # noqa: E402
from safeer_windows import oddaljeni_zaslon_prikaz as p  # noqa: E402
from safeer_windows.oddaljeni_zaslon_protokol import Seja  # noqa: E402

ODTIS = "12" * 32


def _app():
    return QApplication.instance() or QApplication([])


def _png(w=12, h=16, barva="#ff0000") -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    slika = QImage(w, h, QImage.Format.Format_ARGB32)
    slika.fill(QColor(barva))
    polje = QByteArray()
    medpomnilnik = QBuffer(polje)
    medpomnilnik.open(QIODevice.OpenModeFlag.WriteOnly)
    slika.save(medpomnilnik, "PNG")
    return bytes(polje)


# ------------------------------------------------------------------ screen.start
def test_zmoznosti_po_specifikaciji_izvora():
    z = p.zahteva_seje("najvisja", "apps", (1440, 801), 1.0, "ethernet")
    for zmoznost in ("handoff", "rtt", "gop", "kazalec", "izvorna", "brezizgubno", "profil"):
        assert zmoznost in z["caps"], zmoznost
    assert len(z["caps"]) == len(set(z["caps"]))
    assert z["view"]["w"] == 1440 and z["view"]["h"] == 800 and z["view"]["dpi"] == 96
    assert z["net"] == "ethernet" and z["codecs"] == ["h264"]
    # HEVC 4:4:4 samo po meritvi dekodiranja (testni PC nima strojnega HEVC): ga ne ponudimo.
    assert "444" not in z["caps"] and "hevc" not in z["codecs"]


# ------------------------------------------------------------------ slika kazalca
def test_slika_kazalca_iz_obvestila():
    _app()
    png = _png()
    ob = {"kazalec": [5, 6], "oblika": "puscica", "viden": True,
          "slika": "data:image/png;base64," + base64.b64encode(png).decode(), "vroca": [3, 4]}
    assert p.slika_kazalca(ob) == (png, 3, 4)
    assert p.slika_kazalca(dict(ob, viden=False)) is None
    assert p.slika_kazalca(dict(ob, slika="data:image/png;base64,QUJD")) is None          # ni PNG
    assert p.slika_kazalca(dict(ob, slika="data:image/gif;base64,R0lG")) is None
    assert p.slika_kazalca(dict(ob, slika="data:image/png;base64,***")) is None
    velik = b"\x89PNG\r\n\x1a\n" + b"0" * (p.NAJVEC_SLIKE_KAZALCA_B + 1)
    assert p.slika_kazalca(dict(ob, slika="data:image/png;base64," + base64.b64encode(velik).decode())) is None
    assert p.slika_kazalca(dict(ob, vroca=[True, 2]))[1:] == (0, 0)
    assert p.slika_kazalca(dict(ob, vroca=[-5, 9999]))[1:] == (0, 255)
    assert p.slika_kazalca({"kazalec": [1, 2], "oblika": "puscica"}) is None


class _Backend:
    def __init__(self, nastavitve=None):
        self.naprave = [{"id": "n-1-control", "naslov": "192.168.0.50", "ime": "Prenosnik"}]
        self.nastavitve = dict(nastavitve or {})
        self.shranjeno = 0

    def shrani_nastavitve(self):
        self.shranjeno += 1
        return True

    def ukaz_pocakaj(self, *a, **k):
        return {"ok": False, "message": "preizkus"}


class _LaznaNit:
    def __init__(self, *a, **k):
        self.prikaz_prost = threading.Event()

    def start(self):
        pass

    def ustavi(self):
        pass


def _okno(monkeypatch, backend=None):
    _app()
    monkeypatch.setattr(oz, "_DekodirnaNit", _LaznaNit)
    okno = oz.OddaljeniZaslon(backend or _Backend(), "n-1-control", "Prenosnik", zaslon="desktop")
    okno._zapiram = True                  # brez seje - preizkusamo samo okno
    return okno


def test_en_kazalec_oblika_in_slika_izvora(monkeypatch):
    okno = _okno(monkeypatch)
    try:
        # Starejsi izvor (Linux do 0.4.90) rise kazalec v sliko: lokalni nad sliko skrit.
        assert okno.slika.cursor().shape() == Qt.CursorShape.BlankCursor
        okno._glava({"w": 1920, "h": 1080, "kazalec": True,
                     "profil": {"pot": "neposredno", "kodek": "h264rgb", "zaslon": "namizje"}})
        assert okno.slika.kazalec_v_sliki is False
        assert okno.slika.cursor().shape() == Qt.CursorShape.ArrowCursor
        png = _png()
        okno._obvestilo({"kazalec": [1, 1], "oblika": "puscica", "viden": True,
                         "slika": "data:image/png;base64," + base64.b64encode(png).decode(), "vroca": [0, 0]})
        assert okno.slika.cursor().shape() == Qt.CursorShape.BitmapCursor
        # Polozaj vsakih 8 ms brez slike: tocna slika ostane.
        okno._obvestilo({"kazalec": [9, 9], "oblika": "puscica", "viden": True})
        assert okno.slika.cursor().shape() == Qt.CursorShape.BitmapCursor
        okno._obvestilo({"kazalec": [9, 9], "oblika": "besedilo", "viden": True})
        assert okno.slika.cursor().shape() == Qt.CursorShape.IBeamCursor
        okno._obvestilo({"kazalec": [9, 9], "oblika": "besedilo", "viden": False})
        assert okno.slika.cursor().shape() == Qt.CursorShape.BlankCursor
    finally:
        okno.close()


def test_vrstica_s_profilom_izvora():
    v = p.vrstica_podatkov("sl", "192.168.0.10", False, {"vrsta": "ethernet", "hitrost_bps": 1_000_000_000},
                           (1920, 1080), (1920, 1080), 60, profil={"pot": "neposredno", "kodek": "h264rgb"})
    assert v == "LAN · kabel 1 Gb/s · neposredno · 1920×1080 1:1 · 60 fps · brezizgubno"
    v = p.vrstica_podatkov("en", "192.168.0.10", False, {}, (1440, 800), (1440, 800), 60, dpi=120,
                           profil={"pot": "sredisce", "kodek": "hevc444", "zaslon": "navidezno"})
    assert v == "LAN · via relay · virtual desktop · 1440×800 1:1 · 120 DPI · 60 fps · 4:4:4"
    for j in ("sl", "en", "de", "es", "fr", "it"):
        assert p.besedilo(j, "brezizgubno") and p.besedilo(j, "navidezno")
        assert set(p.BESEDILA[j]) == set(p.BESEDILA["sl"]), j


def test_nacin_1_1_si_okno_zapomni(monkeypatch):
    backend = _Backend()
    okno = _okno(monkeypatch, backend)
    try:
        assert okno.slika.nacin == "prilagodi"
        okno.en_na_en.setChecked(True)
        assert backend.nastavitve["gledalec_nacin"] == "1:1" and backend.shranjeno == 1
    finally:
        okno.close()
    drugo = _okno(monkeypatch, backend)
    try:
        assert drugo.slika.nacin == "1:1" and drugo.en_na_en.isChecked()
        assert backend.shranjeno == 1                   # ob odprtju se nic ne zapise znova
    finally:
        drugo.close()


# ------------------------------------------------------------------ pretvorba
class _Ravnina(bytes):
    line_size = 0


def test_en_preoblikovalnik_za_vso_sejo(monkeypatch):
    """frame.reformat() za vsako sliko zgradi nov SwsContext s filtrom (28,9 ms na testnem PC); seja ima enega."""
    ustvarjeni, klici = [], []

    class Preoblikovalnik:
        def __init__(self):
            ustvarjeni.append(self)

        def reformat(self, okvir, width=None, height=None, format=None, interpolation=None):
            klici.append((width, height, format, interpolation))
            w, h = width or okvir.width, height or okvir.height
            r = _Ravnina(b"\x00" * (w * 4 * h))
            r.line_size = w * 4
            return types.SimpleNamespace(width=w, height=h, planes=[r])

    av = types.ModuleType("av")
    video = types.ModuleType("av.video")
    reformatter = types.ModuleType("av.video.reformatter")
    reformatter.VideoReformatter = Preoblikovalnik
    for ime, modul in (("av", av), ("av.video", video), ("av.video.reformatter", reformatter)):
        monkeypatch.setitem(sys.modules, ime, modul)
    nit = oz._DekodirnaNit(Seja("192.168.0.50", 4567, ODTIS, "enkraten"), oz._TokSignali(), "Prenosnik")
    slike = []

    def ob_sliki(slika):
        slike.append((slika.width(), slika.height()))
        nit.prikaz_prost.set()
    nit.signali = types.SimpleNamespace(slika=types.SimpleNamespace(emit=ob_sliki))
    nit.cilj = (4, 2)
    t = threading.Thread(target=nit._pretvarjaj, daemon=True)
    t.start()
    try:
        for _ in range(3):
            nit._oddaj(types.SimpleNamespace(width=8, height=4))
            konec = time.monotonic() + 3
            while nit._okvir is not None and time.monotonic() < konec:
                time.sleep(0.005)
        konec = time.monotonic() + 3
        while len(slike) < 3 and time.monotonic() < konec:
            time.sleep(0.005)
    finally:
        nit._tece.clear()
        t.join(2)
    assert slike == [(4, 2)] * 3
    assert len(ustvarjeni) == 1
    assert klici[0] == (4, 2, "bgra", p.POMANJSEVANJE)
    with open(oz.__file__, encoding="utf-8") as f:
        assert "okvir.reformat(" not in f.read()


def test_dekoder_samo_rezine_in_glava(monkeypatch):
    """thread_type SLICE: niti po slikah bi dodale do 3 slike zakasnitve (nacrt 5.2); glava gre oknu."""
    dekoder = types.SimpleNamespace(thread_type=None, parse=lambda telo: [], decode=lambda paket: [])
    monkeypatch.setitem(sys.modules, "av", types.SimpleNamespace(
        CodecContext=types.SimpleNamespace(create=lambda *a: dekoder)))

    class Povezava:
        def povezi(self):
            return {"v": 2, "w": 64, "h": 48, "kodek": "h264", "kazalec": True}

        def okvirji(self):
            return iter(())

        def zapri(self):
            pass

        def poslji(self, d):
            pass
    signali = oz._TokSignali()
    glave = []
    signali.glava.connect(lambda g: glave.append(g), oz.Qt.ConnectionType.DirectConnection)
    nit = oz._DekodirnaNit(Seja("192.168.0.50", 4567, ODTIS, "enkraten"), signali, "Prenosnik")
    nit._povezava = Povezava()
    nit.run()
    assert dekoder.thread_type == "SLICE"
    assert glave and glave[0]["kazalec"] is True


def test_brezizgubno_pikselsko_enako_izvoru():
    """Vir Linux na zicnem LAN: libx264rgb qp 0. Gledalec pri 1:1 vrne natanko iste pike (BGRA)."""
    av = pytest.importorskip("av")
    import io
    _app()
    w, h = 96, 64
    izvor = bytearray()
    for y in range(h):
        for x in range(w):
            izvor += bytes(((x * 37) % 256, (y * 53) % 256, ((x ^ y) * 11) % 256))
    try:
        izhod = io.BytesIO()
        kontejner = av.open(izhod, "w", format="h264")
        tok = kontejner.add_stream("libx264rgb", rate=30)
    except Exception as e:  # noqa: BLE001
        pytest.skip("libx264rgb ni na voljo: %s" % e)
    tok.width, tok.height, tok.pix_fmt = w, h, "bgr0"
    tok.options = {"qp": "0", "preset": "ultrafast", "tune": "zerolatency"}
    okvir = av.VideoFrame(w, h, "rgb24")
    if okvir.planes[0].line_size != w * 3:
        pytest.skip("poravnava vrstic")
    okvir.planes[0].update(bytes(izvor))
    # Vec enakih slik: razclenjevalnik zadnjo enoto zadrzi do naslednje (en sam paket bi ostal v njem).
    paketi = []
    for _ in range(4):
        paketi += [bytes(x) for x in tok.encode(okvir.reformat(format="bgr0"))]
    paketi += [bytes(x) for x in tok.encode(None)]
    kontejner.close()
    nit = oz._DekodirnaNit(Seja("192.168.0.50", 4567, ODTIS, "enkraten"), oz._TokSignali(), "Prenosnik")
    slike = []

    def ob_sliki(s):
        slike.append(s)
        nit.prikaz_prost.set()
    nit.signali = types.SimpleNamespace(slika=types.SimpleNamespace(emit=ob_sliki))
    t = threading.Thread(target=nit._pretvarjaj, daemon=True)
    t.start()
    try:
        dekoder = av.CodecContext.create("h264", "r")
        dekoder.thread_type = "SLICE"
        for x in paketi:
            for paket in dekoder.parse(x):
                for o in dekoder.decode(paket):
                    nit._oddaj(o)
        for o in dekoder.decode(None):
            nit._oddaj(o)
        konec = time.monotonic() + 5
        while not slike and time.monotonic() < konec:
            time.sleep(0.01)
    finally:
        nit._tece.clear()
        t.join(2)
    assert slike, "ni slike"
    s = slike[-1]
    razlike = 0
    for y in range(h):
        for x in range(w):
            c = s.pixelColor(x, y)
            i = (y * w + x) * 3
            if (c.red(), c.green(), c.blue()) != tuple(izvor[i:i + 3]):
                razlike += 1
    assert razlike == 0


# ------------------------------------------------------------------ pregled Grok 7 (W11-W13)
def test_w11_mere_iz_glave_omejene():
    assert p.veljavne_mere(1920, 1080) and p.veljavne_mere(7680, 4320)
    for w, h in ((100000, 100000), (0, 1080), (1920, -1), ("x", 2), (None, None), (8193, 10)):
        assert not p.veljavne_mere(w, h), (w, h)
    # Pretvorba nikoli ne poveca nad dekodirano sliko, tudi ce je glava (nacin 1:1) obljubila vec.
    assert p.cilj_pretvorbe((100000, 100000), 1920, 1080) is None
    assert p.cilj_pretvorbe((1920, 1080), 1920, 1080) is None
    assert p.cilj_pretvorbe((960, 540), 1920, 1080) == (960, 540)
    assert p.cilj_pretvorbe(None, 1920, 1080) is None


def test_w12_png_kazalca_po_glavi_pred_dekodiranjem():
    import struct
    import zlib

    def png(w, h):
        ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
        kos = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))  # noqa: E731
        return b"\x89PNG\r\n\x1a\n" + kos(b"IHDR", ihdr) + kos(b"IDAT", zlib.compress(b"\0" * 64)) + kos(b"IEND", b"")
    for w, h in ((16000, 4000), (257, 10), (0, 10)):
        ob = {"viden": True, "slika": "data:image/png;base64," + base64.b64encode(png(w, h)).decode()}
        assert p.slika_kazalca(ob) is None, (w, h)
    ob = {"viden": True, "slika": "data:image/png;base64," + base64.b64encode(_png(32, 32)).decode()}
    assert p.slika_kazalca(ob) is not None


def test_w13_besedilo_naprave_ni_html(monkeypatch):
    okno = _okno(monkeypatch)
    try:
        assert okno.stanje.textFormat() == Qt.TextFormat.PlainText
        assert okno.podatki.textFormat() == Qt.TextFormat.PlainText
    finally:
        okno.close()

