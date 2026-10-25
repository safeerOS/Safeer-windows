"""Program, odprt od tu na locenem zaslonu racunalnika, je ze odprt na njegovem namizju (»ni okna«, 25. 10. 2026).

Lastnik je iz Safeer OS na Windows odprl Claude na prenosniku z Linuxom. Claude je program ene same instance: nov zagon
na locenem zaslonu je samo predal besedo oknu, ki je bilo ze odprto na namizju prenosnika, in koncal. Racunalnik je to
prepoznal (izid "na_namizju"), a gledalec Windows v `screen.start` ni povedal, da zna preklop (`caps: ["handoff"]`),
zato je dobil "ni_okna" - in okno je pokazalo golo oznako. Zdaj gledalec preklop zna (kot televizor): preklopi na
namizje racunalnika, ta pa okno programa postavi v ospredje.
"""
import os
import sys
import threading
import time
import types

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402
from safeer_windows import oddaljeni_zaslon as oz  # noqa: E402
from safeer_windows.oddaljeni_zaslon_protokol import OKVIR_OBVESTILO, Seja  # noqa: E402

ODTIS = "12" * 32


@pytest.fixture(autouse=True)
def _slovenscina():
    oz.nastavi_jezik("sl")
    yield
    oz.nastavi_jezik("sl")


class _LaznaPovezava:
    def __init__(self, obvestila):
        self._okvirji = [(OKVIR_OBVESTILO, o.encode("utf-8")) for o in obvestila]

    def povezi(self):
        return {"w": 1920, "h": 1080}

    def okvirji(self):
        return iter(self._okvirji)

    def zapri(self):
        pass

    def poslji(self, dogodek):
        pass


def _tek_niti(monkeypatch, obvestila):
    """Dekodirna nit z laznima povezavo in dekoderjem (av na Linuxu ni namescen): kaj pove oknu."""
    dekoder = types.SimpleNamespace(thread_type=None, parse=lambda telo: [], decode=lambda paket: [])
    monkeypatch.setitem(sys.modules, "av", types.SimpleNamespace(
        CodecContext=types.SimpleNamespace(create=lambda *a: dekoder)))
    signali = oz._TokSignali()
    stanja, predaje = [], []
    signali.stanje.connect(lambda stanje, besedilo: stanja.append((stanje, besedilo)))
    signali.predaja.connect(lambda program: predaje.append(program))
    nit = oz._DekodirnaNit(Seja("192.168.0.50", 4567, ODTIS, "enkraten"), signali, "Prenosnik")
    nit._povezava = _LaznaPovezava(obvestila)
    nit.run()
    return stanja, predaje


def test_program_na_namizju_preklopi_namesto_napake(monkeypatch):
    stanja, predaje = _tek_niti(monkeypatch, ['{"program": "caka", "name": "Claude"}',
                                              '{"konec": "na_namizju", "name": "Claude"}'])
    assert predaje == ["Claude"]
    assert ("caka", "Odpiram Claude ...") in stanja
    assert not [s for s in stanja if s[0] == "napaka"], stanja


def test_ni_okna_je_stavek_ne_oznaka(monkeypatch):
    stanja, predaje = _tek_niti(monkeypatch, ['{"konec": "ni_okna"}'])
    assert predaje == []
    assert stanja[-1] == ("napaka", "Program se na računalniku ni odprl.")


def test_neznan_razlog_pokaze_stavek_naprave_ali_splosno(monkeypatch):
    stanja, _ = _tek_niti(monkeypatch, ['{"konec": "prevzeto", "sporocilo": "Zaslon zdaj gleda druga naprava."}'])
    assert stanja[-1] == ("napaka", "Zaslon zdaj gleda druga naprava.")
    stanja, _ = _tek_niti(monkeypatch, ['{"konec": "nekaj_novega"}'])
    assert stanja[-1] == ("napaka", "Naprava je končala povezavo.")


def test_program_odprt_po_cakanju(monkeypatch):
    stanja, _ = _tek_niti(monkeypatch, ['{"program": "caka"}', '{"program": "odprt"}'])
    caka = ("caka", "Odpiram program ...")
    assert caka in stanja
    assert ("tece", "Povezano") in stanja[stanja.index(caka):]


class _LazniBackend:
    def __init__(self):
        self.naprave = [{"id": "n-1-control", "naslov": "192.168.0.50", "ime": "Prenosnik"}]
        self.klici = []
        self._kljuc = threading.Lock()

    def ukaz_pocakaj(self, id_naprave, akcija, parametri, cas=0.0):
        with self._kljuc:
            self.klici.append((akcija, dict(parametri)))
        if akcija == "screen.start":
            return {"ok": True, "data": {"port": 4567, "fp": ODTIS, "token": "enkraten", "v": 2}}
        return {"ok": True}

    def zacetki(self):
        with self._kljuc:
            return [p for a, p in self.klici if a == "screen.start"]


class _LaznaNit:
    def __init__(self, seja, signali, ime=""):
        self.seja = seja
        self.prikaz_prost = threading.Event()

    def start(self):
        pass

    def ustavi(self):
        pass


def _pocakaj(pogoj, rok=5.0):
    konec = time.monotonic() + rok
    while time.monotonic() < konec:
        QApplication.processEvents()
        if pogoj():
            return True
        time.sleep(0.02)
    return False


def test_okno_po_na_namizju_odpre_namizje_s_prosnjo_za_okno(monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(oz, "_DekodirnaNit", _LaznaNit)
    backend = _LazniBackend()
    okno = oz.OddaljeniZaslon(backend, "n-1-control", "Prenosnik", zaslon="apps")
    try:
        assert _pocakaj(lambda: len(backend.zacetki()) == 1)
        # Zahteva ima poleg tega se platno, omrezje, kodeke in ping (ostrina gledalca, oddaljeni_zaslon_prikaz).
        prvi = backend.zacetki()[0]
        assert (prvi["quality"], prvi["screen"]) == ("najvisja", "apps")
        assert "handoff" in prvi["caps"] and "handoff" not in prvi
        okno._na_namizju("Claude")
        assert _pocakaj(lambda: len(backend.zacetki()) == 2)
        drugi = backend.zacetki()[1]
        assert (drugi["quality"], drugi["screen"], drugi["handoff"]) == ("najvisja", "desktop", True)
        assert "handoff" in drugi["caps"]
        assert okno.zaslon_cilj == "desktop"
        assert "Claude" in okno.stanje.text()
        # Drugega preklopa ni (ne vrtimo se v krogu); »Povezi znova« ostane na namizju.
        okno._na_namizju("Claude")
        time.sleep(0.2)
        assert len(backend.zacetki()) == 2
    finally:
        okno._zapiram = True
        okno.close()
        okno.deleteLater()
        QApplication.processEvents()
