#!/usr/bin/env python3
"""Skupna koda Linux -> Windows (lastnik, 25. 10. 2026: »Linux je vir za skupno kodo«).

Safeer-windows je nastal kot kopija Safeer-linux; mapa core/ je skupna, a sta se kopiji razsli (25. 10. 2026: 70 od 86
datotek). Vir resnice je Safeer-linux. Datoteka skupna-koda.json pove:
  - "ref": commit Safeer-linux, iz katerega so skupne datoteke prenesene,
  - "skupne": datoteke, ki morajo biti ENAKE kot v Safeer-linux@ref (preveri CI),
  - "zacasno_razlicne": skupne datoteke, ki se se razlikujejo in cakajo na uskladitev (seznam se sme samo krajsati),
  - "samo_windows": datoteke, ki jih Linux nima (namerno),
  - "preslikave": predpona poti v Safeer-linux -> predpona v Safeer-windows, kjer sta mapi razlicni (namizje QML:
    Linux assets/os/qml/, Windows windows/safeer_windows/qml/). Vse poti v seznamih so poti Safeer-linux.
Razvrscene morajo biti vse datoteke Windows v core/ (*.py), assets/os/ in v mapi namizja QML (skupni vmesnik, nacrt
25. 10. 2026: vmesnik Linux in Windows iz ene kode).

Ukazi (LINUX = pot do kopije Safeer-linux na commitu ref ali novejsem):
  preveri LINUX      - napaka, ce se skupna datoteka razlikuje ali je datoteka brez razvrstitve (CI)
  prenesi LINUX REF  - skupne datoteke prepise iz LINUX in zapise REF (rocno, pred commitom na Windows)
  porocilo LINUX     - koliko vrstic se razlikuje pri zacasno razlicnih (za uskladitev po vrsti)
"""

from __future__ import annotations

import difflib
import json
import shutil
import sys
from pathlib import Path

KOREN = Path(__file__).resolve().parents[1]
SEZNAM = KOREN / "skupna-koda.json"


def _beri() -> dict:
    return json.loads(SEZNAM.read_text(encoding="utf-8"))


def _preslikave(s: dict) -> dict:
    return dict(s.get("preslikave") or {})


def pot_windows(pot: str, s: dict) -> str:
    """Pot Safeer-linux -> pot v Safeer-windows (preslikava predpone, sicer ista pot)."""
    for linux, windows in sorted(_preslikave(s).items(), key=lambda p: -len(p[0])):
        if pot.startswith(linux):
            return windows + pot[len(linux):]
    return pot


def pot_linux(pot: str, s: dict) -> str:
    """Obratno: pot v Safeer-windows -> pot, kot jo pisejo seznami (Safeer-linux)."""
    for linux, windows in sorted(_preslikave(s).items(), key=lambda p: -len(p[1])):
        if pot.startswith(windows):
            return linux + pot[len(windows):]
    return pot


def _rel(p: Path) -> str:
    return str(p.relative_to(KOREN)).replace("\\", "/")


def datoteke_razvrstitve(s: dict) -> set:
    """Datoteke Windows, ki morajo biti razvrscene (poti Safeer-linux): core/**.py, assets/os/*, namizje QML."""
    izid = {_rel(p) for p in (KOREN / "core").rglob("*.py") if "__pycache__" not in p.parts}
    vmesnik = KOREN / "assets" / "os"
    if vmesnik.is_dir():
        izid |= {_rel(p) for p in vmesnik.iterdir() if p.is_file()}
    for windows in _preslikave(s).values():
        mapa = KOREN / windows
        if mapa.is_dir():
            izid |= {pot_linux(_rel(p), s) for p in mapa.iterdir() if p.is_file()}
    return izid


def preveri(linux: Path) -> int:
    s = _beri()
    napake = []
    for f in s["skupne"]:
        a, b = KOREN / pot_windows(f, s), linux / f
        if not b.is_file():
            napake.append("%s: ni v Safeer-linux" % f)
        elif not a.is_file() or a.read_bytes() != b.read_bytes():
            napake.append("%s: razlikuje se od Safeer-linux (popravi v Safeer-linux in prenesi s skupna_koda.py prenesi)"
                          % pot_windows(f, s))
    znane = set(s["skupne"]) | set(s["zacasno_razlicne"]) | set(s["samo_windows"])
    for f in sorted(datoteke_razvrstitve(s) - znane):
        napake.append("%s: nova datoteka - dodaj jo v Safeer-linux (skupne) ali v samo_windows" % pot_windows(f, s))
    for f in s["zacasno_razlicne"]:
        a, b = KOREN / pot_windows(f, s), linux / f
        if a.is_file() and b.is_file() and a.read_bytes() == b.read_bytes():
            napake.append("%s: je ze enaka - premakni jo iz zacasno_razlicne v skupne" % f)
    for n in napake:
        print("NAPAKA " + n)
    print("skupne: %d, zacasno razlicne: %d, samo Windows: %d"
          % (len(s["skupne"]), len(s["zacasno_razlicne"]), len(s["samo_windows"])))
    return 1 if napake else 0


def prenesi(linux: Path, ref: str) -> int:
    s = _beri()
    for f in s["skupne"]:
        cilj = KOREN / pot_windows(f, s)
        cilj.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(linux / f, cilj)
    s["ref"] = ref
    SEZNAM.write_text(json.dumps(s, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("prenesenih %d datotek iz %s" % (len(s["skupne"]), ref))
    return 0


def porocilo(linux: Path) -> int:
    s = _beri()
    vrstice = []
    for f in s["zacasno_razlicne"]:
        w = KOREN / pot_windows(f, s)
        a = w.read_text(encoding="utf-8", errors="replace").splitlines() if w.is_file() else []
        b = (linux / f).read_text(encoding="utf-8", errors="replace").splitlines() if (linux / f).is_file() else []
        d = list(difflib.unified_diff(b, a, lineterm="", n=0))
        vrstice.append((sum(1 for x in d if x.startswith("+") and not x.startswith("+++")),
                        sum(1 for x in d if x.startswith("-") and not x.startswith("---")), f))
    for win, lin, f in sorted(vrstice):
        print("%-40s samo Windows %5d   samo Linux %5d" % (f, win, lin))
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("preveri", "prenesi", "porocilo"):
        print(__doc__)
        sys.exit(2)
    pot = Path(sys.argv[2])
    if sys.argv[1] == "preveri":
        sys.exit(preveri(pot))
    if sys.argv[1] == "prenesi":
        sys.exit(prenesi(pot, sys.argv[3] if len(sys.argv) > 3 else ""))
    sys.exit(porocilo(pot))
