"""Namestitveni program 1.0.52 pospravi staro namestitev 1.0.51 (naloga 43, 27. 10. 2026).

Uporabnik z install.ps1 (Go zaganjalnik v %LOCALAPPDATA%\\SafeerOS, koda v SafeerOS\\app) je po namestitvi 1.0.52 imel
dve ikoni »Safeer OS« na namizju in v Start, samozagon pa je ob prijavi zagnal staro razlicico. Preizkus brez ISCC
(predprocesor iz test_installer_predvajalnik): Browser ima [Code], ki brise SAMO bliznjice s ciljem starega zaganjalnika,
prestavi samozagon in preimenuje (ne brise) staro kodo; Player tega nima.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from test_installer_predvajalnik import ISS, predprocesiraj

KOREN = Path(__file__).resolve().parents[1]


def _koda(definirano: dict) -> str:
    vrstice = predprocesiraj(ISS.read_text(encoding="utf-8"), definirano)
    besedilo = "\n".join(vrstice)
    i = besedilo.find("[Code]")
    return besedilo[i:] if i >= 0 else ""


def _brez_komentarjev(koda: str) -> str:
    return "\n".join(v.split("//", 1)[0] for v in koda.splitlines())


def test_browser_pospravi_staro_namestitev_po_namestitvi():
    koda = _koda({})
    assert "procedure CurStepChanged" in koda
    assert "CurStep <> ssPostInstall" in koda and "JeStaraNamestitev" in koda
    assert "{localappdata}\\SafeerOS\\SafeerOS.exe" in koda
    assert "{localappdata}\\SafeerOS\\app\\windows\\VERSION" in koda


def test_player_nima_selitve():
    assert _koda({"Predvajalnik": "1"}) == ""


def test_brise_samo_bliznjice_starega_zaganjalnika():
    koda = _brez_komentarjev(_koda({}))
    # Edini DeleteFile je v OdstraniStaroBliznjico in je pod pogojem, da cilj bliznjice = stari zaganjalnik.
    assert koda.count("DeleteFile(") == 1
    telo = koda[koda.index("procedure OdstraniStaroBliznjico"):koda.index("procedure PreseliSamozagon")]
    assert "CompareText(CiljBliznjice(Pot), StariZaganjalnik) = 0" in telo and "DeleteFile(Pot)" in telo
    for klic in re.findall(r"OdstraniStaroBliznjico\(ExpandConstant\('([^']+)'\)\)", koda):
        assert klic.lower().endswith(".lnk"), klic
    # Nic se ne brise rekurzivno; nastavitve in podatki ostanejo.
    for prepovedano in ("DelTree", "{userappdata}", "{commonappdata}", "RemoveDir(ExpandConstant('{localappdata}"):
        assert prepovedano not in koda, prepovedano


def test_pokrije_bliznjice_ki_jih_naredi_install_ps1():
    koda = _koda({})
    ps = (KOREN / "install.ps1").read_text(encoding="utf-8-sig")
    imena = set(re.findall(r'"(Safeer [A-Za-z]+)\.lnk"', ps))
    assert {"Safeer OS", "Safeer Browser", "Safeer Control"} <= imena
    for ime in imena:
        assert "{userdesktop}\\%s.lnk" % ime in koda, ime
        assert "{userprograms}\\Safeer OS\\%s.lnk" % ime in koda, ime
    assert "{userprograms}\\Safeer OS.lnk" in koda


def test_stara_koda_se_preimenuje_ne_brise():
    koda = _brez_komentarjev(_koda({}))
    assert "RenameFile(Mapa, Mapa + PriponaStareMape)" in koda
    assert "PriponaStareMape = '.pred-1.0.52'" in koda
    assert "not DirExists(Mapa + PriponaStareMape)" in koda      # prejsnje kopije ne prepisemo


def test_samozagon_enak_ukazu_aplikacije():
    koda = _koda({})
    telo = koda[koda.index("procedure PreseliSamozagon"):koda.index("procedure UmakniStaroKodo")]
    assert "Pos(Lowercase(StariZaganjalnik), Lowercase(Vrednost)) > 0" in telo     # samo nas stari vpis
    assert "'\"' + ExpandConstant('{app}\\SafeerOS.exe') + '\" --ozadje'" in telo
    # Enako, kot ga zapise os_backend_win._ukaz_samozagona (list2cmdline) za pot s presledki v Program Files:
    pot = r"C:\Program Files\Safeer Browser\SafeerOS.exe"
    assert subprocess.list2cmdline([pot, "--ozadje"]) == '"%s" --ozadje' % pot
    vir = (KOREN / "safeer_windows" / "os_backend_win.py").read_text(encoding="utf-8")
    assert 'list2cmdline(list(ukaz) + ["--ozadje"])' in vir
    assert 'KljucSamozagona = \'Software\\Microsoft\\Windows\\CurrentVersion\\Run\'' in koda
    assert "ImeSamozagona = 'SafeerOS'" in koda
    assert 'KLJUC_SAMOZAGONA = r"Software\\Microsoft\\Windows\\CurrentVersion\\Run"' in vir
    assert 'IME_SAMOZAGONA = "SafeerOS"' in vir
