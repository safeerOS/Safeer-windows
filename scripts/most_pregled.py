#!/usr/bin/env python3
"""Pregled mostu Safeer OS: katere metode klice vmesnik (HTML in QML) in katere pozna zaledje - Linux in Windows.

Skupni vmesnik (nacrt 25. 10. 2026: »kar velja za eno okolje, mora veljati za drugo«) bo isti na obeh platformah;
gumb za metodo, ki je zaledje platforme (se) nima, mora biti skrit prek ima() v assets/os/most.js. Ta skripta je
samo branje (ast in regularni izrazi, nic se ne uvozi ali zazene) in jo uporabljajo:
  - tests/test_os_most_metode.py: vsak klic("x") vmesnika ima metodo v zaledju ali je na seznamu MANJKA;
  - meritev skupnega vmesnika (Linux vmesnik proti Windows zaledju in obratno).

Uporaba:  most_pregled.py KOREN            - porocilo za eno drevo (JSON)
          most_pregled.py LINUX WINDOWS    - vmesnik vsake platforme proti zaledju druge (JSON)
Ista datoteka je v Safeer-linux in Safeer-windows (skupna-koda.json).
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from typing import Dict, Set

KLIC = re.compile(r"\bklic\(\s*[\"']([A-Za-z_]\w*)[\"']")

#: Klici vmesnika, ki jih zaledje platforme (se) nima - vmesnik jih mora skriti prek ima() (assets/os/most.js).
#: Izmerjeno 25. 10. 2026 (Linux delo-133 d13659b, Windows delo-windows 45ba26a). Seznam se sme samo krajsati:
#: ko zaledje metodo dobi, jo test zahteva odstraniti s seznama (tests/test_os_most_metode.py).
MANJKA: Dict[str, Dict[str, frozenset]] = {
    "linux": {"html": frozenset(), "delovna": frozenset(), "qml": frozenset()},
    "windows": {
        # Okno Safeer OS (os.js): okna, nedavne, Wi-Fi, svetlost, nocna luc, mesalnik zvoka - na Windows brez zaledja.
        "html": frozenset({
            "aktivirajOkno", "domov", "glasnost", "jblVklop", "nedavnePocisti", "nedavnePozabi", "nocna",
            "odpriRazdelek", "omrezjeAktiviraj", "omrezjeOdklopi", "omrezjePovezi", "omrezjePozabi", "preklopiOkno",
            "skrijPloscoSporocil", "svetlost", "utisaj", "wifi", "zapriOkno", "zvokGlasnostIzhoda",
            "zvokGlasnostPrograma", "zvokGlasnostVhoda", "zvokIzhod", "zvokNaNapravo", "zvokPremakniProgram",
            "zvokUstavi", "zvokUtisajIzhod", "zvokUtisajProgram", "zvokUtisajVhod", "zvokVhod"}),
        # delovna.html na Windows (namizje_win.py): govor, GitHub programi, pretvorbe, shramba, viri programov.
        "delovna": frozenset({
            "dodajVir", "githubIsci", "githubIzdaje", "githubShrani", "githubStanje", "govorNamesti",
            "govorPoslusaj", "govorPreklici", "govorPrekliciNamestitev", "govorUstavi", "igreOblakNamesti",
            "izberiMapo", "knjiznicaMedijev", "mediaTokovi", "napraveZaMedij", "odpriLokalniMedij", "odpriMedijNa",
            "ponudnikNamesti", "ponudnikOdpri", "ponudnikPodrobnosti", "posljiStanje", "predvajajZNaprave",
            "predvajalnikStanje", "predvajalnikUkaz", "pretvorbaDatotekeStanje", "pretvorbaMoznosti",
            "pretvorbaPrenesi", "pretvorbaPrenesiSkupino", "pretvorbaPusti", "pretvorbaPustiSkupino",
            "pretvorbaSkupina", "pretvorbaStanje", "pretvoriDatoteko", "pretvoriVec", "pretvoriVideo",
            "shrambaIzbrisi", "shrambaObdrzi", "shrambaStanje", "shraniNaNapravo", "virPodrobnosti"}),
        "qml": frozenset(),
    },
}


def _beri(pot: Path) -> str:
    try:
        return pot.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def vrsta(koren: Path) -> str:
    """»linux« (Safeer-linux: safeer_os.py), »windows« (Safeer-windows: windows/safeer_windows/os_app.py) ali »«."""
    koren = Path(koren)
    if (koren / "windows" / "safeer_windows" / "os_app.py").is_file():
        return "windows"
    if (koren / "safeer_os.py").is_file():
        return "linux"
    return ""


#: Vrste vmesnika: okno Safeer OS (HTML), delovna povrsina (delovna.html - na Windows jo gosti namizje_win.py z
#: lastnimi metodami) in namizje QML.
VRSTE = ("html", "delovna", "qml")


def _datoteke_ui(koren: Path) -> Dict[str, list]:
    koren = Path(koren)
    js = sorted((koren / "assets" / "os").glob("*.js"))
    if vrsta(koren) == "windows":
        qml_mapa = koren / "windows" / "safeer_windows" / "qml"
    else:
        qml_mapa = koren / "assets" / "os" / "qml"
    qml = sorted(list(qml_mapa.glob("*.qml")) + list(qml_mapa.glob("*.js")))
    # most.js je most sam: klic("zmoznosti") brez zaledja (starejse) obravnava sam (ima() je tedaj vedno true).
    js = [d for d in js if d.name != "most.js"]
    return {"html": [d for d in js if d.name != "delovna.js"], "delovna": [d for d in js if d.name == "delovna.js"],
            "qml": qml}


def ui_klici(koren: Path) -> Dict[str, Set[str]]:
    """Imena metod, ki jih vmesnik klice s klic("ime", ...) - HTML (assets/os/*.js) in namizje QML."""
    izid: Dict[str, Set[str]] = {}
    for kaj, datoteke in _datoteke_ui(koren).items():
        izid[kaj] = set()
        for d in datoteke:
            izid[kaj] |= set(KLIC.findall(_beri(d)))
    return izid


def _imena_primerjav(drevo: ast.AST, funkcije: Set[str]) -> Set[str]:
    """Imena iz `metoda == "x"` in `metoda in ("x", "y")` v danih funkcijah."""
    imena: Set[str] = set()
    for n in ast.walk(drevo):
        if not (isinstance(n, ast.FunctionDef) and n.name in funkcije):
            continue
        for m in ast.walk(n):
            if isinstance(m, ast.Compare) and isinstance(m.left, ast.Name) and m.left.id == "metoda":
                for c in m.comparators:
                    if isinstance(c, ast.Constant) and isinstance(c.value, str):
                        imena.add(c.value)
                    elif isinstance(c, (ast.Tuple, ast.List, ast.Set)):
                        imena |= {e.value for e in c.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return imena


def _kljuci_slovarjev(drevo: ast.AST, funkcije: Set[str]) -> Set[str]:
    """Kljuci slovarjev (niz) v danih funkcijah - npr. glavna/ozadje/asinhrono v safeer_os._obdelaj_klic."""
    imena: Set[str] = set()
    for n in ast.walk(drevo):
        if isinstance(n, ast.FunctionDef) and n.name in funkcije:
            for m in ast.walk(n):
                if isinstance(m, ast.Dict):
                    imena |= {k.value for k in m.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    return imena


def _drevo(pot: Path) -> ast.AST:
    try:
        return ast.parse(_beri(pot))
    except SyntaxError:
        return ast.parse("")


def _skupne(koren: Path) -> Set[str]:
    """Metode skupnega dispecerja core/os_most_metode.py (SKUPNE), ce ga zaledje ze uporablja (VKLJUCENO)."""
    t = _beri(Path(koren) / "core" / "os_most_metode.py")
    return set(re.findall(r'^\s*_m\(\s*"(\w+)"', t, re.M)) if t else set()


def zaledje(koren: Path, s_skupnimi: bool = False) -> Dict[str, Set[str]]:
    """Metode, ki jih zaledje pozna. HTML: glavno okno Safeer OS; QML: gostitelj namizja (+ glavno okno).
    s_skupnimi=True doda metode core/os_most_metode.py (ko ju gostitelja klicata - korak 2 nacrta)."""
    koren = Path(koren)
    v = vrsta(koren)
    if v == "linux":
        so = _drevo(koren / "safeer_os.py")
        html = _kljuci_slovarjev(so, {"_obdelaj_klic"}) | _imena_primerjav(so, {"_obdelaj_klic"})
        html |= set(re.findall(r'"(media\w+)":\s*"_', _beri(koren / "core" / "os_katalog.py")))
        delovna = html
        # Lupina v svojem procesu (core/lupina_proces.py) streze sama varuhZnova in zazeni brez Safeer OS.
        qml = html | _imena_primerjav(_drevo(koren / "core" / "os_lupina.py"), {"_lastna"}) | \
            _imena_primerjav(_drevo(koren / "core" / "lupina_proces.py"), {"klic"})
    elif v == "windows":
        w = koren / "windows" / "safeer_windows"
        html = _imena_primerjav(_drevo(w / "os_app.py"), {"_izvedi_metodo", "_sporocila", "_magnet_metoda"})
        delovna = html | _kljuci_slovarjev(_drevo(w / "namizje_win.py"), {"metode"})
        qml = delovna | _imena_primerjav(_drevo(w / "namizje_qml.py"), {"izvedi"})
    else:
        return {k: set() for k in VRSTE}
    izid = {"html": html, "delovna": delovna, "qml": qml}
    if s_skupnimi:
        s = _skupne(koren) | {"zmoznosti"}
        izid = {k: v | s for k, v in izid.items()}
    return izid


def manjka(vmesnik_koren: Path, zaledje_koren: Path, s_skupnimi: bool = False) -> Dict[str, Set[str]]:
    """Klici vmesnika iz enega drevesa, ki jih zaledje drugega (ali istega) drevesa ne pozna."""
    ui, z = ui_klici(vmesnik_koren), zaledje(zaledje_koren, s_skupnimi)
    return {k: ui[k] - z[k] for k in VRSTE}


def porocilo(koren: Path) -> dict:
    ui, z = ui_klici(koren), zaledje(koren)
    return {"vrsta": vrsta(koren), "ui": {k: len(v) for k, v in ui.items()}, "zaledje": {k: len(v) for k, v in z.items()},
            "manjka": {k: sorted(ui[k] - z[k]) for k in ui}}


def navzkriz(linux: Path, windows: Path) -> dict:
    """Skupni vmesnik: vmesnik Linuxa na zaledju Windows in obratno (s skupnimi metodami in brez njih)."""
    izid = {}
    for ime, ui, zal in (("linux_vmesnik_na_windows", linux, windows), ("windows_vmesnik_na_linux", windows, linux)):
        brez, s = manjka(ui, zal), manjka(ui, zal, s_skupnimi=True)
        izid[ime] = {k: {"manjka": len(brez[k]), "manjka_s_skupnimi": len(s[k]), "imena": sorted(s[k])} for k in brez}
    return izid


if __name__ == "__main__":
    if len(sys.argv) == 2:
        print(json.dumps(porocilo(Path(sys.argv[1])), ensure_ascii=False, indent=1))
    elif len(sys.argv) == 3:
        print(json.dumps(navzkriz(Path(sys.argv[1]), Path(sys.argv[2])), ensure_ascii=False, indent=1))
    else:
        print(__doc__)
        sys.exit(2)
