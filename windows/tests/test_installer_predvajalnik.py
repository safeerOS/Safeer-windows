"""Namestitveni program Safeer Player (naloga 103): windows/installer.iss z /DPredvajalnik.

Zakaj ta preizkus: Player in Browser sta isti skript Inno Setup. Ce bi Player podedoval AppId Browserja, bi namestitev
Playerja prepisala ali odstranila Browser; ce bi podedoval bliznjice ali registracijo, bi uporabnik, ki je hotel samo
predvajalnik, dobil brskalnik kot privzeti program. Inno Setup v CI tece sele po ~uri gradnje, ta preizkus pa takoj,
brez ISCC: preprost predprocesor (samo #ifdef/#ifndef/#else/#endif/#define, ki jih skript uporablja) da obe razlicici.
"""
from __future__ import annotations

import re
from pathlib import Path

ISS = Path(__file__).resolve().parents[1] / "installer.iss"
APPID_BROWSER = "{{6D1F3A52-8C4B-4E27-9B61-5A0E7C3D9F14}"


def predprocesiraj(besedilo: str, definirano: dict[str, str]) -> list[str]:
    definicije = dict(definirano)
    sklad: list[bool] = []
    izhod: list[str] = []
    for vrstica in besedilo.splitlines():
        ukaz = vrstica.strip()
        aktivno = all(sklad)
        if ukaz.startswith("#ifdef ") or ukaz.startswith("#ifndef "):
            ime = ukaz.split()[1]
            sklad.append((ime in definicije) == ukaz.startswith("#ifdef "))
        elif ukaz == "#else":
            sklad[-1] = not sklad[-1]
        elif ukaz == "#endif":
            sklad.pop()
        elif ukaz.startswith("#define "):
            if aktivno:
                m = re.match(r'#define\s+(\w+)\s+"(.*)"\s*$', ukaz)
                assert m, ukaz
                definicije[m.group(1)] = m.group(2)
        elif ukaz.startswith("#"):
            raise AssertionError(f"predprocesor tega preizkusa ne pozna: {ukaz}")
        elif aktivno:
            izhod.append(re.sub(r"\{#(\w+)\}", lambda m: definicije[m.group(1)], vrstica))
    assert not sklad, "neuravnotezen #ifdef/#endif"
    return izhod


def razdelki(vrstice: list[str]) -> dict[str, list[str]]:
    izhod: dict[str, list[str]] = {}
    trenutni = ""
    for vrstica in vrstice:
        v = vrstica.strip()
        if not v or v.startswith(";"):
            continue
        if v.startswith("[") and v.endswith("]"):
            trenutni = v[1:-1]
            izhod.setdefault(trenutni, [])
        else:
            izhod.setdefault(trenutni, []).append(v)
    return izhod


def _setup(r: dict[str, list[str]]) -> dict[str, str]:
    return dict(v.split("=", 1) for v in r["Setup"])


def _player():
    return razdelki(predprocesiraj(ISS.read_text(encoding="utf-8"), {"AppVersion": "1.0.0", "Predvajalnik": ""}))


def _browser():
    return razdelki(predprocesiraj(ISS.read_text(encoding="utf-8"), {"AppVersion": "1.0.0"}))


def test_player_ima_svoj_appid_ime_in_datoteko():
    s = _setup(_player())
    assert s["AppId"] != APPID_BROWSER
    assert re.fullmatch(r"\{\{[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\}", s["AppId"])
    assert s["AppName"] == "Safeer Player"
    assert s["DefaultDirName"] == r"{autopf}\Safeer Player"
    assert s["OutputBaseFilename"] == "SafeerPlayer-1.0.0-windows-x64-setup"
    assert s["UninstallDisplayIcon"] == r"{app}\SafeerOS.exe"
    assert s["ChangesAssociations"] == "no"


def test_player_ima_samo_bliznjico_safeer_player_s_predvajalnikom():
    ikone = _player()["Icons"]
    assert ikone, "Player brez bliznjice"
    for ikona in ikone:
        assert r'\Safeer Player"' in ikona, ikona
        assert r'Filename: "{app}\SafeerOS.exe"' in ikona, ikona
        assert 'Parameters: "--predvajalnik"' in ikona, ikona
    assert any(i.startswith(r'Name: "{autoprograms}\Safeer Player"') for i in ikone)
    assert not any("SafeerBrowser.exe" in i or r"\Safeer OS" in i for i in ikone)


def test_player_ne_registrira_brskalnika_in_zazene_predvajalnik():
    r = _player()
    assert not r.get("Registry"), r.get("Registry")
    assert r["Run"] and all('Parameters: "--predvajalnik"' in v and "SafeerOS.exe" in v for v in r["Run"])
    # Isti zgrajeni paket (isti _internal) kot Browser: [Files] se ne razlikuje.
    assert r["Files"] == _browser()["Files"]


def test_browser_ostane_nespremenjen():
    r = _browser()
    s = _setup(r)
    assert s["AppId"] == APPID_BROWSER
    assert s["OutputBaseFilename"] == "SafeerBrowser-1.0.0-windows-x64-setup"
    assert s["AppSupportURL"] == "https://safeer.si/browser/"
    assert s["ChangesAssociations"] == "yes"
    assert len(r["Icons"]) == 4 and not any("--predvajalnik" in i for i in r["Icons"])
    assert any("StartMenuInternet" in v for v in r["Registry"])
    assert r["Run"] == [r'Filename: "{app}\SafeerBrowser.exe"; Description: "{cm:LaunchProgram,Safeer Browser}"; Flags: nowait postinstall skipifsilent']


def test_main_preusmeri_predvajalnik():
    # SafeerOS.exe --predvajalnik odpre samo predvajalnik (windows/safeer_windows/__main__.py); bliznjica je odvisna od tega.
    main = (ISS.parent / "safeer_windows" / "__main__.py").read_text(encoding="utf-8")
    assert 'if "--predvajalnik" in sys.argv:' in main
    assert "from safeer_windows.safeer_predvajalnik import main as predvajalnik_main" in main


def test_safeeros_exe_pozna_zastavico_predvajalnik():
    """CI 40371933757: bliznjica Safeer Player zazene SafeerOS.exe --predvajalnik; vstopna tocka SafeerOS.exe
    (launcher_os.py) mora zastavico odstraniti in zagnati predvajalnik, sicer argparse os_app konca s kodo 2."""
    import pathlib
    vir = (pathlib.Path(__file__).resolve().parents[1] / "launcher_os.py").read_text(encoding="utf-8")
    assert 'if "--predvajalnik" in sys.argv:' in vir
    assert "sys.argv.remove(\"--predvajalnik\")" in vir
    assert "from safeer_windows.safeer_predvajalnik import main" in vir
