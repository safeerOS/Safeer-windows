"""Brskalnik Windows: po padcu izrisovalnika stran enkrat sama nalozi znova (kot Splet in TV, 14. 10. 2026)."""
import os
import re

KOREN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _vir():
    with open(os.path.join(KOREN, "safeer_windows", "browser.py"), encoding="utf-8") as f:
        return f.read()


def test_obnova_enkrat_brez_kroga():
    s = _vir()
    del_ = s[s.index("def on_render_terminated("):s.index("def on_fullscreen_request(")]
    assert "QTimer.singleShot(400, view.reload)" in del_
    assert "zdaj - prej[1] < 60" in del_
    assert del_.index("zdaj - prej[1] < 60") < del_.index("QTimer.singleShot")


def test_besedilo_v_obeh_jezikih():
    assert len(re.findall(r'"crashed_reloaded":', _vir())) == 2
