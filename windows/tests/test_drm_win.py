"""Zasciten video v Spletu Windows (WebView2) kot na Linuxu: core/drm.SKRIPTA in odlocitev uporabnika na stran.

Lastnik 25. 10. 2026 12:50: Splet na Windows ostane WebView2; zaznava DRM naj bo enaka Linuxu. Ovoj
requestMediaKeySystemAccess (skupna core/drm.py) javi zahtevo za Widevine/PlayReady takoj; Splet ponudi »Predvajaj v
Safeer DRM«, nic se ne zazene samo; ob kliku velja nastavitev strani »drm« (core/dovoljenja_strani, skupna koda).
"""
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

KOREN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KOREN))
sys.path.insert(0, str(KOREN / "windows"))
pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core import dovoljenja_strani, drm  # noqa: E402
from safeer_windows import browser, policy  # noqa: E402


class _Nastavitve(dict):
    def set(self, kljuc, vrednost, save=True):
        self[kljuc] = vrednost


def _spec():
    nast = types.SimpleNamespace(get=lambda k, d=None: False)
    return next(s for s in policy.script_specs(nast) if s["name"] == "safeer-drm")


def test_skripta_kot_linux_v_glavnem_okvirju_ob_zacetku():
    s = _spec()
    assert s["at_start"] is True and s["all_frames"] is False
    assert drm.SKRIPTA.strip()[:40] in s["source"]                  # ista skripta kot Linux (skupna koda)
    assert "drm_zahteva" in s["source"] and policy.STEVEC_ZETON in s["source"]
    if shutil.which("node"):
        r = subprocess.run(["node", "-e", "new Function(require('fs').readFileSync(0, 'utf8'))"],
                           input=s["source"], capture_output=True, text=True, timeout=20)
        assert r.returncode == 0, r.stderr


def test_most_brez_zetona_ne_ponudi():
    klici = []
    stran = types.SimpleNamespace(window_ref=types.SimpleNamespace(drm_ponudi=lambda p, s: klici.append(s)))
    browser.SafeerBrowserApp.on_bridge_message(None, stran, {"action": "drm_zahteva", "sistem": "com.widevine.alpha"})
    assert klici == []
    browser.SafeerBrowserApp.on_bridge_message(None, stran, {"action": "drm_zahteva", "sistem": "com.widevine.alpha",
                                                             "t": policy.STEVEC_ZETON})
    assert klici == ["com.widevine.alpha"]


def _okno(nastavitve, odprto):
    o = types.SimpleNamespace(app=types.SimpleNamespace(settings=nastavitve, lang="sl"))
    o.odpri_drm = lambda url, vsiljeno=False: odprto.append((url, vsiljeno)) or True
    o._drm_besedilo = types.MethodType(browser.BrowserWindow._drm_besedilo, o)
    return o


def _pogled(url):
    return types.SimpleNamespace(url=lambda: types.SimpleNamespace(toString=lambda: url))


def test_klik_po_nastavitvi_strani(monkeypatch):
    url = "https://bitmovin.com/demos/drm"
    # privzeto »dovoli« (kot Linux): klik odpre Safeer DRM tudi za stran, ki ni na seznamu DRM_DOMENE
    odprto = []
    browser.BrowserWindow._drm_klik(_okno(_Nastavitve(), odprto), _pogled(url))
    assert odprto == [(url, True)]
    # »zavrni« za to stran: nic
    n = _Nastavitve()
    dovoljenja_strani.zapomni(n, url, ["drm"], "zavrni")
    odprto = []
    browser.BrowserWindow._drm_klik(_okno(n, odprto), _pogled(url))
    assert odprto == []
    # »vprasaj«: vprasanje, odgovor se zapomni
    n = _Nastavitve(dovoljenja_privzeto={"drm": "vprasaj"})
    vprasano = []
    monkeypatch.setattr(browser.QMessageBox, "question",
                        lambda *a, **k: vprasano.append(a[2]) or browser.QMessageBox.StandardButton.Yes)
    odprto = []
    browser.BrowserWindow._drm_klik(_okno(n, odprto), _pogled(url))
    assert odprto == [(url, True)] and "bitmovin.com" in vprasano[0]
    assert dovoljenja_strani.odlocitev(n, url, ["drm"]) == "dovoli"


def test_besedila_v_6_jezikih():
    for j in ("sl", "en", "de", "es", "fr", "it"):
        assert {"drm_zahteva", "drm_predvajaj"} <= set(drm.BESEDILA[j])
        assert {"dv_zahteva", "dv_drm"} <= set(dovoljenja_strani.BESEDILA[j])


def test_javna_dejanja_webview2_so_vsa_z_zetonom():
    """Splet WebView2 (splet_webview2) spusti s tujih strani samo _JAVNA_DEJANJA; vsako mora biti v on_bridge_message
    preverjeno z zetonom, in zahteva za DRM mora skozi (sicer se ponudba Safeer DRM ne pokaze - testni PC 25. 10.)."""
    import re
    from safeer_windows import splet_webview2
    src = (KOREN / "windows" / "safeer_windows" / "browser.py").read_text(encoding="utf-8")
    telo = src[src.index("def on_bridge_message"):][:600]
    z_zetonom = re.search(r"if action in \(([^)]*)\) and not policy\.zeton_veljaven\(payload\)", telo)
    assert z_zetonom, "on_bridge_message mora preveriti zeton"
    preverjena = set(re.findall(r'"([a-z_]+)"', z_zetonom.group(1)))
    assert set(splet_webview2._JAVNA_DEJANJA) <= preverjena
    assert "drm_zahteva" in splet_webview2._JAVNA_DEJANJA

