# -*- mode: python ; coding: utf-8 -*-
"""Samostojni Safeer Predvajalnik za Windows (SafeerPredvajalnik.exe).

Isti pogon in widget kot Medijski center v Safeer OS (safeer_windows.safeer_predvajalnik), brez namizja QML,
Splet/WebView2, Qt WebEngine in Linka. libmpv iz windows/safeer_windows/vendor/mpv (python windows/fetch_libmpv.py).

Gradnja (iz korena repozitorija):
    python -m PyInstaller --noconfirm --clean windows/SafeerPredvajalnik.spec \
        --distpath build/predvajalnik/dist --workpath build/predvajalnik/work
"""
import json
import os

WINDOWS = os.path.abspath(SPECPATH)  # noqa: F821 - PyInstaller
ROOT = os.path.dirname(WINDOWS)
BUILD = os.path.join(ROOT, "build", "predvajalnik")
VENDOR_MPV = os.path.join(WINDOWS, "safeer_windows", "vendor", "mpv")

# libmpv je obvezen (predvajalnik brez njega ne predvaja): nepopoln paket ustavi gradnjo (pravilo 6).
_MPV_OBVEZNO = ("libmpv-2.dll", "libEGL.dll", "libGLESv2.dll", "manifest.json", "safeer-capabilities.json",
                os.path.join("runtime", "msvcp140.dll"), os.path.join("runtime", "vcruntime140.dll"),
                os.path.join("runtime", "vcruntime140_1.dll"), os.path.join("licenses", "COPYING.LGPL-2.1"))
_manjka = [f for f in _MPV_OBVEZNO if not os.path.isfile(os.path.join(VENDOR_MPV, f))]
if _manjka:
    raise SystemExit("libmpv: windows/safeer_windows/vendor/mpv je nepopoln, manjka: " + ", ".join(_manjka)
                     + " (python windows/fetch_libmpv.py)")
_man = json.load(open(os.path.join(VENDOR_MPV, "manifest.json"), encoding="utf-8-sig"))
print(f"libmpv: prilozen {_man.get('release')} ({_man.get('arch')})")


def _ikona() -> str:
    """Ikona predvajalnika: znak Safeer (assets/icon.png) z oznako predvajanja; brez Pillow ikona Safeer."""
    cilj = os.path.join(BUILD, "safeer_predvajalnik.ico")
    os.makedirs(BUILD, exist_ok=True)
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return os.path.join(WINDOWS, "safeer.ico")
    slika = Image.open(os.path.join(ROOT, "assets", "icon.png")).convert("RGBA").resize((256, 256))
    risba = ImageDraw.Draw(slika)
    risba.ellipse((132, 132, 252, 252), fill=(20, 20, 24, 255), outline=(255, 255, 255, 255), width=8)
    risba.polygon([(172, 160), (172, 224), (228, 192)], fill=(255, 255, 255, 255))
    slika.save(cilj, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return cilj


# SMTC (sistemske medijske kontrole): winrt je izbiren - brez njega predvajalnik dela, tipke le s fokusom okna.
from PyInstaller.utils.hooks import collect_submodules  # noqa: E402

try:
    import winrt.windows.media.playback  # noqa: F401
    _smtc = ["safeer_windows.predvajalnik_smtc"] + collect_submodules("winrt")
    print("SMTC: winrt prisoten -> sistemske medijske kontrole prilozene")
except Exception as e:  # noqa: BLE001
    _smtc = []
    print(f"SMTC: winrt ni namescen ({e}) -> brez sistemskih medijskih kontrol")

a = Analysis(  # noqa: F821
    [os.path.join(WINDOWS, "launcher_predvajalnik.py")],
    pathex=[WINDOWS],
    binaries=[],
    datas=[(VENDOR_MPV, os.path.join("safeer_windows", "vendor", "mpv"))],
    hiddenimports=["mpv", "safeer_windows.safeer_mpv_pogon", "safeer_windows.safeer_mpv_okno",
                   "safeer_windows.predvajalnik_dodatki_okno", "safeer_windows.predvajalnik_stremio_okno",
                   "safeer_windows.predvajalnik_nadaljuj", "safeer_windows.budnost_win"] + _smtc,
    hookspath=[],
    runtime_hooks=[],
    # Predvajalnik ne rabi namizja, brskalnika, WebView2, QML, QtMultimedia (samostojni nima rezerve Qt) ne PIL.
    excludes=["tkinter", "PIL", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
              "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtMultimedia",
              "PySide6.QtMultimediaWidgets", "PySide6.QtNetwork", "PySide6.QtPdf", "PySide6.QtSvg",
              "safeer_windows.os_app", "safeer_windows.browser", "safeer_windows.namizje_qml",
              "safeer_windows.splet_webview2", "safeer_windows.webview2_media", "safeer_windows.safeer_qt_pogon",
              "safeer_windows.vlc_player", "vlc"],
    noarchive=False,
)
# MSVC runtime: pyi_rth_pyside6 nalozi shiboken6 PRED launcherjem, zato se v proces nalozi msvcp140 iz paketa
# PySide6/shiboken6 (14.44), libmpv pa zahteva >= razlicico iz manifest.json -> brez tega pogon ne steče
# (izmerjeno 25. 10. 2026: »MSVC runtime prestar«). Vse kopije zamenjamo z novejsimi iz vendor/mpv/runtime.
# Samo podpisan Microsoftov runtime in nikoli starejsi od kopije, ki jo zamenja (Grok X3) - isto kot build_windows.
import sys  # noqa: E402
sys.path.insert(0, WINDOWS)
import build_windows as _gradnja  # noqa: E402
_RUNTIME = {ime: os.path.join(VENDOR_MPV, "runtime", ime) for ime in _gradnja.MSVC_RUNTIME}
_NOVE = _gradnja.preveri_vir_runtime(_RUNTIME)


def _runtime_za(cilj, vir):
    ime = os.path.basename(cilj).lower()
    if ime in _RUNTIME and _gradnja.razlicica_pe(vir) <= _NOVE[ime]:
        return _RUNTIME[ime]
    return vir


a.binaries = [(cilj, _runtime_za(cilj, vir), vrsta) for cilj, vir, vrsta in a.binaries]
print("MSVC runtime iz vendor/mpv/runtime:", sorted(c for c, v, _t in a.binaries if v in _RUNTIME.values()))

pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SafeerPredvajalnik",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=_ikona(),
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="SafeerPredvajalnik",
)
