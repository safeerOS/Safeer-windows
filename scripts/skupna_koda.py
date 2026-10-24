#!/usr/bin/env python3
"""Skupna koda Linux -> Windows (lastnik, 25. 10. 2026: »Linux je vir za skupno kodo«).

Safeer-windows je nastal kot kopija Safeer-linux; mapa core/ je skupna, a sta se kopiji razsli (25. 10. 2026: 70 od 86
datotek). Vir resnice je Safeer-linux. Datoteka skupna-koda.json pove:
  - "ref": commit Safeer-linux, iz katerega so skupne datoteke prenesene,
  - "skupne": datoteke, ki morajo biti ENAKE kot v Safeer-linux@ref (preveri CI),
  - "zacasno_razlicne": skupne datoteke, ki se se razlikujejo in cakajo na uskladitev (seznam se sme samo krajsati),
  - "samo_windows": datoteke, ki jih Linux nima (namerno).

Ukazi (LINUX = pot do kopije Safeer-linux na commitu ref ali novejsem):
  preveri LINUX      - napaka, ce se skupna datoteka razlikuje ali je v core/ datoteka brez razvrstitve (CI)
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


def _datoteke_core() -> set:
    return {str(p.relative_to(KOREN)).replace("\\", "/") for p in (KOREN / "core").rglob("*.py") if "__pycache__" not in p.parts}


def preveri(linux: Path) -> int:
    s = _beri()
    napake = []
    for f in s["skupne"]:
        a, b = KOREN / f, linux / f
        if not b.is_file():
            napake.append("%s: ni v Safeer-linux" % f)
        elif not a.is_file() or a.read_bytes() != b.read_bytes():
            napake.append("%s: razlikuje se od Safeer-linux (popravi v Safeer-linux in prenesi s skupna_koda.py prenesi)" % f)
    znane = set(s["skupne"]) | set(s["zacasno_razlicne"]) | set(s["samo_windows"])
    for f in sorted(_datoteke_core() - znane):
        napake.append("%s: nova datoteka v core/ - dodaj jo v Safeer-linux (skupne) ali v samo_windows" % f)
    for f in s["zacasno_razlicne"]:
        if (KOREN / f).is_file() and (linux / f).is_file() and (KOREN / f).read_bytes() == (linux / f).read_bytes():
            napake.append("%s: je ze enaka - premakni jo iz zacasno_razlicne v skupne" % f)
    for n in napake:
        print("NAPAKA " + n)
    print("skupne: %d, zacasno razlicne: %d, samo Windows: %d" % (len(s["skupne"]), len(s["zacasno_razlicne"]), len(s["samo_windows"])))
    return 1 if napake else 0


def prenesi(linux: Path, ref: str) -> int:
    s = _beri()
    for f in s["skupne"]:
        (KOREN / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(linux / f, KOREN / f)
    s["ref"] = ref
    SEZNAM.write_text(json.dumps(s, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("prenesenih %d datotek iz %s" % (len(s["skupne"]), ref))
    return 0


def porocilo(linux: Path) -> int:
    s = _beri()
    vrstice = []
    for f in s["zacasno_razlicne"]:
        a = (KOREN / f).read_text(encoding="utf-8", errors="replace").splitlines() if (KOREN / f).is_file() else []
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
