"""Naslov ali iskanje z druge naprave (Link) je vedno »od zunaj« (revizija 4. 11. 2026).

Prej: _odpri_v_brskalniku je v novem oknu naslov nalozil z new_tab mimo resolve_input, _link_iskanje (search.query) in
lupa namizja (ki jo druga naprava lahko vpise prek isci_od_drugod) pa sta niz dala v open_input kot vpis uporabnika -
\\\\streznik\\deljeno bi se odprl kot file:// in Windows bi poslal NTLM. Zdaj vse te poti klicejo open_input(zunanji=True).
"""
import os
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

KOREN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KOREN))
sys.path.insert(0, str(KOREN / "windows"))
pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from safeer_windows import browser, os_app  # noqa: E402

UNC = r"\\streznik\deljeno\a.html"


class _Brskalnik:
    """Okno brskalnika s pravim BrowserWindow.open_input; zavihki so seznam."""

    def __init__(self):
        self.zavihki = []
        self.home_url = "safeer://home/"
        nastavitve = types.SimpleNamespace(get=lambda k, d=None: {"search_engine": "duckduckgo",
                                                                  "tracking_protection_enabled": True}.get(k, d))
        self.app = types.SimpleNamespace(settings=nastavitve)
        self.tabs = types.SimpleNamespace(count=lambda: len(self.zavihki))
        self.odpri_drm = lambda url: False
        self.prikazano = False

    def open_input(self, text, new_tab=False, page=None, zunanji=False):
        return browser.BrowserWindow.open_input(self, text, new_tab=new_tab, page=page, zunanji=zunanji)

    def new_tab(self, url=None, switch=True):
        self.zavihki.append(url)

    def load_in_current(self, url):
        self.zavihki.append(url)

    def show(self):
        self.prikazano = True

    def isMinimized(self):  # noqa: N802
        return False

    def raise_(self):
        pass

    def activateWindow(self):  # noqa: N802
        pass

    def showMaximized(self):  # noqa: N802
        self.prikazano = True

    def set_media_mode(self, _):
        pass

    def set_safeer_os_web_mode(self, _):
        pass


def _os(okno_brskalnika, vidno=False):
    sebe = types.SimpleNamespace(browser_app=types.SimpleNamespace(windows=[]), browser_window=okno_brskalnika,
                                 dispatcher=types.SimpleNamespace(dispatch=lambda f: f()), namizje=None,
                                 prebudi=lambda: None, _okno_spleta_namizja=None, _spletna_stran_odprta=False,
                                 _pokazi_spletni_nacin=lambda: None, isVisible=lambda: vidno, isMinimized=lambda: False,
                                 setWindowTitle=lambda _t: None)
    sebe._sistemsko_okno_brskalnika = lambda: okno_brskalnika
    for ime in ("odpri_spletno_iskanje", "_odpri_spletno_iskanje", "_splet_nad_namizjem", "odpri_splet",
                "_odpri_v_brskalniku"):
        setattr(sebe, ime, types.MethodType(getattr(os_app.SafeerOsWindow, ime), sebe))
    return sebe


def test_link_iskanje_unc_ne_odpre_datoteke():
    b = _Brskalnik()
    with mock.patch.object(browser.os.path, "exists", side_effect=AssertionError("exists na UNC odpre SMB")):
        assert os_app.SafeerOsWindow._link_iskanje(_os(b), UNC) is True
    assert not any(str(z).startswith("file:") for z in b.zavihki), b.zavihki


def test_lupa_namizja_unc_ne_odpre_datoteke():
    for vidno in (False, True):
        b = _Brskalnik()
        with mock.patch.object(browser.os.path, "exists", side_effect=AssertionError("exists na UNC odpre SMB")):
            os_app.SafeerOsWindow.splet_na_namizju(_os(b, vidno=vidno), UNC)
        assert not any(str(z).startswith("file:") for z in b.zavihki), (vidno, b.zavihki)


def test_link_iskanje_navadno_isce():
    b = _Brskalnik()
    os_app.SafeerOsWindow._link_iskanje(_os(b), "vreme ljubljana")
    assert b.zavihki and b.zavihki[-1].startswith("https://duckduckgo.com/?q=vreme")


def test_stran_z_druge_naprave_gre_skozi_open_input_zunanji():
    b = _Brskalnik()
    klici = []
    pravi = b.open_input
    b.open_input = lambda t, new_tab=False, page=None, zunanji=False: (klici.append(zunanji), pravi(t, new_tab, page, zunanji))
    with mock.patch.object(os_app.os_backend_win, "je_drm_storitev", return_value=False):
        os_app.SafeerOsWindow._odpri_v_brskalniku(_os(b), "https://example.com/?utm_source=x")
    assert klici == [True]
    assert b.zavihki == ["https://example.com/"]   # skozi resolve: sledilni parametri odstranjeni
    assert b.prikazano


def test_vsi_klici_open_input_v_os_app_so_razvrsceni():
    """Vsak open_input v os_app je bodisi zunanji bodisi na seznamu notranjih (vpis uporabnika v Safeer OS)."""
    vir = (KOREN / "windows" / "safeer_windows" / "os_app.py").read_text(encoding="utf-8")
    vrstice = [v.strip() for v in vir.splitlines() if ".open_input(" in v]
    notranji = {"self.browser_window.open_input(poizvedba, zunanji=zunanji)"}
    for v in vrstice:
        assert "zunanji=True" in v or v in notranji, v
