"""Smoke preizkus namestitvenega programa Safeer Player (naloga 103) na Windows.

Namesti SafeerPlayer-*-setup.exe tiho za trenutnega uporabnika, preveri, da je nastala SAMO bliznjica »Safeer Player«
(SafeerOS.exe --predvajalnik) in da registracija brskalnika ni nastala, zazene bliznjico, pocaka na vidno okno iz
namescene mape (okno Player se odpre) in program na koncu odstrani. Zakaj svoj skript: build_windows.py install-test
(ni v prilogi) pozna samo namestitveni program Browserja.

Uporaba: python windows/tools/smoke_predvajalnik.py SETUP.exe --porocilo build/windows/out/smoke-predvajalnik.json
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

BLIZNJICA = "Safeer Player.lnk"
ARGUMENTI = "--predvajalnik"
KLJUC_BRSKALNIKA = r"Software\Clients\StartMenuInternet\SafeerBrowser"
# Okno z napako (PyInstaller, Qt) ni okno Playerja.
NAPAKE_V_NASLOVU = ("unhandled exception", "error", "napaka", "traceback")


def _programi() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def _bliznjice() -> set[str]:
    return {p.name for p in _programi().glob("*.lnk")}


def _kljuc_obstaja(pot: str) -> bool:
    import winreg

    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, pot))
        return True
    except OSError:
        return False


def _beri_bliznjico(pot: Path) -> tuple[str, str]:
    # WScript.Shell je v vsakem Windows; pywin32 v paketu ne pricakujemo.
    ukaz = f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{pot}'); $s.TargetPath; $s.Arguments"
    izhod = subprocess.run(["powershell", "-NoProfile", "-Command", ukaz], check=True, capture_output=True, text=True).stdout
    vrstice = izhod.splitlines() + ["", ""]
    return vrstice[0].strip(), vrstice[1].strip()


def _vidna_okna(mapa: Path) -> list[dict]:
    """Vidna okna najvisje ravni s procesom iz namescene mape (tudi ce SafeerOS.exe zazene podproces)."""
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    mapa_niz = str(mapa.resolve()).lower()
    najdena: list[dict] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def obisci(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        roka = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not roka:
            return True
        try:
            buf = ctypes.create_unicode_buffer(32768)
            dolzina = wintypes.DWORD(len(buf))
            if not kernel32.QueryFullProcessImageNameW(roka, 0, buf, ctypes.byref(dolzina)):
                return True
            if not buf.value.lower().startswith(mapa_niz):
                return True
        finally:
            kernel32.CloseHandle(roka)
        naslov = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, naslov, 512)
        razred = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, razred, 256)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        najdena.append({"hwnd": int(hwnd), "pid": pid.value, "exe": buf.value, "naslov": naslov.value,
                        "razred": razred.value, "sirina": rect.right - rect.left, "visina": rect.bottom - rect.top})
        return True

    user32.EnumWindows(obisci, 0)
    return najdena


def _je_okno_playerja(okno: dict) -> bool:
    naslov = okno["naslov"].lower()
    return bool(naslov) and not any(n in naslov for n in NAPAKE_V_NASLOVU) and okno["sirina"] >= 320 and okno["visina"] >= 240


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("setup", type=Path)
    ap.add_argument("--porocilo", type=Path, required=True)
    ap.add_argument("--cas", type=int, default=int(os.environ.get("SAFEER_SMOKE_TIMEOUT", "420")))
    a = ap.parse_args()
    porocilo: dict = {"setup": str(a.setup), "uspeh": False}
    mapa = Path(tempfile.mkdtemp(prefix="SafeerPlayer-")) / "Safeer Player"
    proces = None
    try:
        pred_bliznjice, pred_kljuc = _bliznjice(), _kljuc_obstaja(KLJUC_BRSKALNIKA)
        subprocess.run([str(a.setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER",
                        f"/DIR={mapa}", f"/LOG={a.porocilo.with_suffix('.namestitev.log')}"], check=True, timeout=600)
        nove = sorted(_bliznjice() - pred_bliznjice)
        porocilo["nove_bliznjice"] = nove
        if nove != [BLIZNJICA]:
            raise SystemExit(f"pricakovana samo bliznjica {BLIZNJICA}, nastale: {nove}")
        cilj, argumenti = _beri_bliznjico(_programi() / BLIZNJICA)
        porocilo["bliznjica"] = {"cilj": cilj, "argumenti": argumenti}
        if Path(cilj).name.lower() != "safeeros.exe" or argumenti != ARGUMENTI:
            raise SystemExit(f"bliznjica kaze na {cilj} {argumenti}, pricakovano SafeerOS.exe {ARGUMENTI}")
        if _kljuc_obstaja(KLJUC_BRSKALNIKA) != pred_kljuc:
            raise SystemExit("namestitev Playerja je spremenila registracijo brskalnika")
        if not (mapa / "_internal").is_dir():
            raise SystemExit("v namesceni mapi ni _internal (isti paket kot Browser?)")
        proces = subprocess.Popen([cilj, argumenti], cwd=str(mapa))
        konec = time.monotonic() + a.cas
        okno = None
        while time.monotonic() < konec:
            if proces.poll() is not None:
                raise SystemExit(f"SafeerOS.exe --predvajalnik se je koncal s kodo {proces.returncode} pred oknom")
            okna = _vidna_okna(mapa)
            porocilo["okna"] = okna
            okno = next((o for o in okna if _je_okno_playerja(o)), None)
            if okno:
                break
            time.sleep(1)
        if not okno:
            raise SystemExit(f"okno Safeer Player se ni odprlo v {a.cas} s")
        porocilo["okno"] = okno
        time.sleep(5)  # okno, ki se takoj zapre, ni uspeh
        if proces.poll() is not None:
            raise SystemExit(f"Player je po odprtju okna padel (koda {proces.returncode})")
        porocilo["uspeh"] = True
        print(f"Safeer Player OK: okno »{okno['naslov']}« ({okno['razred']}, {okno['sirina']}x{okno['visina']})")
        return 0
    finally:
        if proces and proces.poll() is None:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proces.pid)], capture_output=True)
            time.sleep(2)
        odstrani = mapa / "unins000.exe"
        if odstrani.exists():
            subprocess.run([str(odstrani), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=600)
            # Odstranjevalnik se kopira v TEMP in vrne takoj; pocakamo, da bliznjica izgine.
            for _ in range(120):
                if not (_programi() / BLIZNJICA).exists() and not odstrani.exists():
                    break
                time.sleep(1)
            porocilo["odstranjeno"] = not (_programi() / BLIZNJICA).exists()
            if not porocilo["odstranjeno"]:
                porocilo["uspeh"] = False
        a.porocilo.parent.mkdir(parents=True, exist_ok=True)
        a.porocilo.write_text(json.dumps(porocilo, ensure_ascii=False, indent=2), encoding="utf-8")
        # Ostanek po odstranitvi je napaka tudi, ce se je okno odprlo (SystemExit v finally prevlada nad return 0).
        if porocilo.get("odstranjeno") is False:
            raise SystemExit("bliznjica Safeer Player je ostala po odstranitvi")


if __name__ == "__main__":
    sys.exit(main())
