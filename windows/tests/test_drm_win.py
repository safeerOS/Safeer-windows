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


_NODE_DRM = r"""
const posts = [], poslusalci = {};
globalThis.window = globalThis; window.top = window;
globalThis.document = { addEventListener(t, f) { (poslusalci[t] = poslusalci[t] || []).push(f); },
                        dispatchEvent(e) { (poslusalci[e.type] || []).forEach(f => f(e)); } };
globalThis.CustomEvent = class { constructor(t, o) { this.type = t; this.detail = o && o.detail; } };
globalThis.DOMException = class extends Error { constructor(m, n) { super(m); this.name = n; } };
globalThis.__safeerPost = m => posts.push(m.sistem);
const podprti = new Set(JSON.parse(process.argv[1]));
Object.defineProperty(globalThis, "navigator", { configurable: true, writable: true, value: {
  requestMediaKeySystemAccess: s => podprti.has(s) ? Promise.resolve({})
                                                  : Promise.reject(new DOMException("x", "NotSupportedError")) } });
(0, eval)(require("fs").readFileSync(0, "utf8"));
(async () => {
  for (const s of ["com.widevine.alpha", "com.microsoft.playready", "com.apple.fps.1_0", "com.widevine.alpha"]) {
    try { await navigator.requestMediaKeySystemAccess(s, []); } catch (e) {}
  }
  await new Promise(r => setTimeout(r, 50));
  console.log(JSON.stringify(posts));
})();
"""


@pytest.mark.skipif(not shutil.which("node"), reason="brez node")
def test_ponudba_samo_ce_webview2_sistema_nima():
    """WebView2 ima Widevine in PlayReady (testni PC 25. 10.: vzorec Widevine je v Spletu predvajal): ponudba Safeer
    DRM samo za sistem, ki ga pogon zavrne (FairPlay), vsak sistem najvec enkrat; brez EME vsi."""
    import json

    def tek(podprti):
        r = subprocess.run(["node", "-e", _NODE_DRM, json.dumps(podprti)], input=policy.DRM_SCRIPT,
                           capture_output=True, text=True, timeout=20)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout.strip().splitlines()[-1])
    assert tek(["com.widevine.alpha", "com.microsoft.playready"]) == ["com.apple.fps.1_0"]
    assert tek([]) == ["com.widevine.alpha", "com.microsoft.playready", "com.apple.fps.1_0"]


_NODE_ZETON = r"""
const ujeto = [], ukradeno = [];
globalThis.location = { href: "https://napad.example/" };
globalThis.window = globalThis; window.top = window;
console.log = (x) => ujeto.push(String(x));          // most Safeer (BridgeScript) je nalozen pred skripto
new Function(require("fs").readFileSync(0, "utf8"))();
// Stran po nalaganju: zamenja console.log in JSON.stringify ter doda nastavljalnik »t« na Object.prototype.
console.log = (x) => ukradeno.push(String(x));
const json = JSON.stringify; JSON.stringify = (o) => { ukradeno.push(json(o)); return json(o); };
Object.defineProperty(Object.prototype, "t", { set(v) { ukradeno.push("t=" + v); }, configurable: true });
setTimeout(() => console.error(JSON.parse(json({ ujeto, ukradeno })) && json({ ujeto, ukradeno })), 30);
"""


@pytest.mark.skipif(not shutil.which("node"), reason="brez node")
def test_zeton_mostu_ne_uide_strani():
    """Pregled Grok W8: stran, ki po nalaganju zamenja console.log, JSON.stringify ali doda nastavljalnik »t«, zetona
    mostu ne dobi; sporocilo z zetonom gre se vedno v most Safeer."""
    import json
    vir = policy.wrap_script("setTimeout(function () { __safeerPost({action: 'drm_zahteva', sistem: 'x'}); }, 5);",
                             None, None)
    r = subprocess.run(["node", "-e", _NODE_ZETON], input=vir, capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    izid = json.loads(r.stderr.strip().splitlines()[-1])
    assert izid["ukradeno"] == []
    assert len(izid["ujeto"]) == 1 and policy.STEVEC_ZETON in izid["ujeto"][0]
    sporocilo = policy.parse_bridge_message(izid["ujeto"][0][len(policy.BRIDGE_PREFIX):]) or \
        json.loads(izid["ujeto"][0][len(policy.BRIDGE_PREFIX):])
    assert sporocilo["action"] == "drm_zahteva" and policy.zeton_veljaven(sporocilo)


_NODE_X2 = r"""
// Grok X2: stran po nastanku dokumenta (ali pred DOMContentLoaded) zamenja Function.prototype.call/apply,
// String.prototype.slice/charAt in console.log, ali doda Object.prototype.toJSON. Zeton ne sme uiti, sporocila z
// zetonom stran ne sme ponarediti. Skripta se vbrizga ob nastanku (pred stranjo), telo ob DOMContentLoaded.
const ujeto = [], ukradeno = [], poslusalci = [];
const napad = process.argv[1];
globalThis.location = { href: "https://napad.example/" };
globalThis.window = globalThis; window.top = window;
globalThis.document = { readyState: "loading" };
window.addEventListener = (ime, f) => { if (ime === "DOMContentLoaded") poslusalci.push(f); };
console.log = (x) => ujeto.push(String(x));
const json = JSON.stringify;
new Function(require("fs").readFileSync(0, "utf8"))();
// Stran:
console.log = (x) => ukradeno.push("log:" + String(x));
if (napad === "call") {
  Function.prototype.call = function (t, ...r) {
    ukradeno.push("call:" + r.map(String).join("|")); return Reflect.apply(this, t, r); };
  Function.prototype.apply = function (t, r) {
    ukradeno.push("apply:" + Array.from(r || []).map(String).join("|")); return Reflect.apply(this, t, r || []); };
}
if (napad === "niz") {
  String.prototype.slice = function () { return '{"action":"ponaredek"'; };
  String.prototype.charAt = function () { return "}"; };
}
if (napad === "tojson") {
  Object.defineProperty(Object.prototype, "toJSON", { value: function () { return { action: "ponaredek" }; },
                                                       configurable: true, writable: true });
}
document.readyState = "interactive";
for (const f of poslusalci) f({});
setTimeout(() => { delete Object.prototype.toJSON; process.stderr.write(json({ ujeto, ukradeno }) + "\n"); }, 30);
"""


@pytest.mark.skipif(not shutil.which("node"), reason="brez node")
@pytest.mark.parametrize("napad", ["call", "niz", "tojson"])
def test_x2_zeton_ne_uide_in_sporocila_ni_mogoce_ponarediti(napad):
    """Pregled Grok 20, X2: __safeerLog.call je sel skozi Function.prototype.call strani (zeton v drugem argumentu),
    s.slice/s.charAt skozi String.prototype (stran je zamenjala vsebino sporocila, zeton pa je ostal pravi),
    Object.prototype.toJSON je zamenjal sporocilo. Skripta »ob nalaganju« je bila vbrizgana sele ob DocumentReady."""
    vir = policy.wrap_script("setTimeout(function () { __safeerPost({action: 'drm_zahteva', sistem: 'x'}); }, 5);",
                             None, None)
    _x2_preveri(vir, napad, poslano=napad != "tojson")


def _x2_preveri(vir, napad, poslano=True):
    import json
    r = subprocess.run(["node", "-e", _NODE_X2, napad], input=vir, capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    izid = json.loads(r.stderr.strip().splitlines()[-1])
    assert not [u for u in izid["ukradeno"] if policy.STEVEC_ZETON in u], izid["ukradeno"]
    for sporocilo in izid["ujeto"]:
        sporocilo = json.loads(sporocilo[len(policy.BRIDGE_PREFIX):])
        assert sporocilo["action"] == "drm_zahteva" and sporocilo.get("sistem") == "x", sporocilo
    if poslano:
        assert len(izid["ujeto"]) == 1
        assert policy.zeton_veljaven(json.loads(izid["ujeto"][0][len(policy.BRIDGE_PREFIX):]))


@pytest.mark.skipif(not shutil.which("node"), reason="brez node")
def test_x2_telo_ob_nalaganju_po_zamenjavi_console_log():
    """Skripta »ob nalaganju« (prej DocumentReady): stran pred DOMContentLoaded zamenja console.log - most je bil
    vzet ob nastanku dokumenta, sporocilo gre v Safeer, stran zetona ne dobi."""
    _x2_preveri(policy.wrap_script("__safeerPost({action: 'drm_zahteva', sistem: 'x'});", None, None,
                                   ob_nalaganju=True), "log")


def test_x2_skripte_z_mostom_ob_nastanku_dokumenta():
    """Skripta, ki poslje v most (__safeerPost), mora biti vbrizgana ob nastanku dokumenta: ob DocumentReady je stran
    console.log ze lahko zamenjala (safeer-cosmetic je tako posiljal increment_ads z zetonom na vsaki strani)."""
    from safeer_windows.policy import SettingsStore
    nastavitve = SettingsStore.__new__(SettingsStore)
    nastavitve.get = lambda k, d=None: True
    specs = policy.script_specs(nastavitve)
    assert any(s["name"] == "safeer-cosmetic" for s in specs)
    for s in specs:
        if "__safeerPost(" in s["source"].split("function __safeerPost", 1)[1].split("\n", 1)[1]:
            assert s["at_start"], s["name"]


def test_zaprta_ponudba_velja_za_gostitelja_v_zavihku():
    """Grok W8: zaprte ponudbe stran ne prikaze znova z drugo poizvedbo istega gostitelja."""
    lastnosti = {}
    stran = object()
    trenutni = ["https://napad.example/video?x=1"]
    pogled = types.SimpleNamespace(page=lambda: stran, property=lambda k: lastnosti.get(k),
                                   setProperty=lambda k, v: lastnosti.__setitem__(k, v),
                                   url=lambda: types.SimpleNamespace(toString=lambda: trenutni[0]))
    okno = types.SimpleNamespace(views=lambda: [pogled], _osvezi_video_vrstico=lambda: None,
                                 _brez_sidra=browser.BrowserWindow._brez_sidra,
                                 _gostitelj=browser.BrowserWindow._gostitelj)
    lastnosti["safeer_drm_zaprto"] = "napad.example"
    trenutni[0] = "https://napad.example/video?x=2"
    browser.BrowserWindow.drm_ponudi(okno, stran, "com.widevine.alpha")
    assert not lastnosti.get("safeer_drm")
    trenutni[0] = "https://druga.example/film"
    browser.BrowserWindow.drm_ponudi(okno, stran, "com.widevine.alpha")
    assert lastnosti.get("safeer_drm") == "https://druga.example/film"

