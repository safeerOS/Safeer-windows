"""Ena tema za vse Safeer OS na Windows: vmesnik, namizje (Qt Quick) in Splet (vgrajeni brskalnik).

Barve so samo na enem mestu - v assets/os/os.css (privzeta tema Safeer in teme, ki jih uporabnik izbere v
Nastavitvah). Lastnik, 13. 10. 2026: brskalnik ima isto temo kot namizje, uporabnik ne sme dobiti obcutka locene
aplikacije; vse nastavitve si prilagodi sam."""
from __future__ import annotations

import re
from typing import Dict, Optional

TEME = ("safeer", "catppuccin", "tokyonight", "gruvbox", "nord", "dracula")
_predpomnilnik: Dict[str, Dict[str, str]] = {}


def _os_css() -> str:
    try:
        from . import policy
        with open(policy.shared_path("assets/os/os.css"), encoding="utf-8") as f:
            return f.read()
    except Exception:  # noqa: BLE001
        return ""


def _bloki(css: str) -> Dict[str, Dict[str, str]]:
    """Spremenljivke iz `:root { ... }` (safeer) in `:root[data-tema="x"] { ... }`."""
    izid: Dict[str, Dict[str, str]] = {}
    for m in re.finditer(r':root(?:\[data-tema="([a-z]+)"\])?\s*\{([^}]*)\}', css):
        ime = m.group(1) or "safeer"
        spremenljivke = dict(re.findall(r"--([a-z-]+)\s*:\s*([^;]+);", m.group(2)))
        if spremenljivke and ime not in izid:
            izid[ime] = {k: v.strip() for k, v in spremenljivke.items()}
    return izid


def _rgb(vrednost: str):
    """'#090d15' ali 'rgba(17, 25, 36, .78)' -> (r, g, b, a) v 0..255 / 0..1; None, ce ni barva."""
    v = (vrednost or "").strip()
    m = re.fullmatch(r"#([0-9a-fA-F]{6})", v)
    if m:
        h = m.group(1)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0
    m = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)", v)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3)), float(m.group(4) or 1)
    return None


def _hex(c) -> str:
    return "#%02x%02x%02x" % c[:3]


PRIVZETO = {"ozadje": "#090d15", "kartica": "rgba(17, 25, 36, .78)", "rob": "rgba(120, 140, 160, .22)",
            "besedilo": "#f0f4f3", "medlo": "#b0bdc4", "zelena": "#54d6a5", "zelena-temna": "#06231a",
            "vnos": "#111b27", "rdeca": "#ff6b6b", "kartica-poudarek": "rgba(27, 42, 51, .92)"}


def paleta(ime: Optional[str] = None) -> Dict[str, object]:
    """Barve teme za Qt (QML in slog brskalnika). Neznana tema -> Safeer."""
    ime = ime if ime in TEME else trenutna()
    if not _predpomnilnik:
        _predpomnilnik.update(_bloki(_os_css()))
    surovo = dict(PRIVZETO)
    surovo.update(_predpomnilnik.get("safeer", {}))
    if ime != "safeer":
        surovo.update(_predpomnilnik.get(ime, {}))

    def barva(k: str):
        return _rgb(surovo.get(k, "")) or _rgb(PRIVZETO[k])

    kartica, rob, poud = barva("kartica"), barva("rob"), barva("zelena")
    return {
        "ime": ime,
        "ozadje": _hex(barva("ozadje")), "vnos": _hex(barva("vnos")), "besedilo": _hex(barva("besedilo")),
        "medlo": _hex(barva("medlo")), "poudarek": _hex(poud), "poudarekTemna": _hex(barva("zelena-temna")),
        "rdeca": _hex(barva("rdeca")), "kartica": _hex(kartica), "karticaPoudarek": _hex(barva("kartica-poudarek")),
        # komponente za QML Qt.rgba (0..1) in za CSS rgba()
        "karticaRgb": [round(x / 255, 4) for x in kartica[:3]], "poudarekRgb": [round(x / 255, 4) for x in poud[:3]],
        "rob": "rgba(%d,%d,%d,%.2f)" % rob, "robRgba": [round(x / 255, 4) for x in rob[:3]] + [rob[3]],
        "poudarekCss": "%d,%d,%d" % poud[:3],
    }


def trenutna() -> str:
    try:
        from . import os_backend_win
        t = str(os_backend_win.nalozi_shrambo().get("tema") or "safeer")
    except Exception:  # noqa: BLE001
        t = "safeer"
    return t if t in TEME else "safeer"


def nastavi(ime: str) -> bool:
    if ime not in TEME:
        return False
    from . import os_backend_win
    s = os_backend_win.nalozi_shrambo()
    if s.get("tema") == ime:
        return False
    s["tema"] = ime
    os_backend_win.shrani_shrambo(s)
    return True


def splet_slog(p: Optional[dict] = None) -> str:
    """Slog orodne vrstice in zavihkov Spleta v barvah teme (prej fiksno zelena na temno modrozeleni)."""
    p = p or paleta()
    a = p["poudarekCss"]
    return f"""
QWidget#chrome {{ background: {p['ozadje']}; }}
QToolBar {{ background: {p['ozadje']}; padding: 6px 14px 8px 14px; spacing: 6px; }}
QToolButton {{ padding: 6px 8px; border-radius: 10px; }}
QTabBar {{ background: {p['ozadje']}; }}
QTabBar::tab {{ background: {p['vnos']}; color: {p['medlo']}; padding: 10px 16px; margin: 8px 4px 0 0; min-width: 190px; max-width: 230px;
               border: 1px solid {p['rob']}; border-bottom: 0; border-top-left-radius: 12px; border-top-right-radius: 12px;
               font-size: 14px; }}
QTabBar::tab:first {{ margin-left: 12px; }}
QTabBar::tab:selected {{ background: {p['karticaPoudarek']}; color: {p['besedilo']}; border-color: rgba({a},.55); border-top: 2px solid {p['poudarek']}; }}
QTabBar::tab:hover:!selected {{ background: {p['kartica']}; }}
QLineEdit#address {{ background: {p['vnos']}; color: {p['besedilo']}; border: 2px solid rgba({a},.55); border-radius: 20px;
                    padding: 8px 10px; font-size: 15px; min-height: 22px; }}
QLineEdit#address:focus {{ border-color: {p['poudarek']}; }}
QLabel#povezavaZnacka {{ color: {p['besedilo']}; border: 1px solid rgba({a},.55); border-radius: 14px; padding: 5px 14px;
                        margin: 8px 18px 0 8px; font-size: 13px; font-weight: 600; background: rgba({a},.08); }}
QLabel#povezavaZnacka[ok="false"] {{ border-color: {p['rob']}; color: {p['medlo']}; background: transparent; }}
"""


def splet_css(p: Optional[dict] = None, ozadje: bool = True) -> str:
    """Zacetna stran Spleta (ui/splet.css) v barvah teme; slika ozadja = ozadje namizja (safeer://home/ozadje)."""
    p = p or paleta()
    a = p["poudarekCss"]
    k = ",".join(str(round(x * 255)) for x in p["karticaRgb"])
    css = (":root{--bg:%s;--z:%s;--z2:%s;--b:%s;--d:%s;--rob:%s;--zrgb:%s;--prgb:%s;--tz:%s;--kartica:%s;}\n"
           % (p["ozadje"], p["poudarek"], p["poudarek"], p["besedilo"], p["medlo"], p["rob"], a, k,
              p["poudarekTemna"], p["kartica"]))
    if ozadje:
        css += (".ozadje{background:linear-gradient(180deg,rgba(0,0,0,.18) 0%%,rgba(0,0,0,.30) 38%%,"
                "%s 92%%),url(\"ozadje\") center 40%% / cover no-repeat,%s !important;}\n" % (p["ozadje"] + "e0", p["ozadje"]))
    return css


def link_css(p: Optional[dict] = None) -> str:
    """Spremenljivke Safeer Control (assets/link/link.css) v barvah teme."""
    p = p or paleta()
    return (":root{--ozadje:%s;--plosca:%s;--ploscaSvetla:%s;--crta:%s;--besedilo:%s;--medlo:%s;--zelena:%s;"
            "--zelenaTemna:%s;}" % (p["ozadje"], p["kartica"], p["karticaPoudarek"], p["rob"], p["besedilo"],
                                   p["medlo"], p["poudarek"], p["poudarekTemna"]))
