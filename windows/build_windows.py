#!/usr/bin/env python3
"""Build and verify Safeer Browser for Windows.

Commands (run from any directory):
  icon            create build/windows/safeer.ico from assets/icon.png
  smoke-source    run the end-to-end smoke test from the Python sources
  pyinstaller     build build/windows/dist/SafeerBrowser/SafeerBrowser.exe
  smoke-frozen    run the smoke test against the built executable
  qml-frozen      load the QML desktop in the built SafeerOS.exe
  kodek-frozen    screen capture to H.264 and decode (PyAV, Pillow) in the built SafeerOS.exe
  package         portable ZIP + Inno Setup installer + SHA256SUMS in build/windows/out
  install-test    silent install, registry check, launch smoke, silent uninstall
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WINDOWS = os.path.join(ROOT, "windows")
BUILD = os.path.join(ROOT, "build", "windows")
DIST = os.path.join(BUILD, "dist")
APP_DIR = os.path.join(DIST, "SafeerBrowser")
EXE = os.path.join(APP_DIR, "SafeerBrowser.exe")
OUT = os.path.join(BUILD, "out")
ICON = os.path.join(BUILD, "safeer.ico")

SHARED_DATA = [
    ("core/adblock.py", "shared/core"),
    ("core/config.py", "shared/core"),
    ("core/bookmarks_importer.py", "shared/core"),
    ("core/reader.py", "shared/core"),
    ("core/signed_feed.py", "shared/core"),
    ("core/threat_intel.py", "shared/core"),
    ("core/bank_guard.py", "shared/core"),
    ("core/banks.json", "shared/core"),
    ("core/bank_guard_page.js", "shared/core"),
    ("ui/home.html", "shared/ui"),
    ("ui/home.css", "shared/ui"),
    ("ui/home.js", "shared/ui"),
    ("ui/splet.html", "shared/ui"),
    ("ui/splet.css", "shared/ui"),
    ("ui/splet.js", "shared/ui"),
    ("ui/splet-gore.webp", "shared/ui"),
    ("assets/safeer-mark.svg", "shared/assets"),
    ("assets/icon.png", "shared/assets"),
    # Cela mapa vmesnika Safeer OS (index.html nalozi tudi namera-iskanja.js; posamezne datoteke so prej manjkale).
    ("assets/os", "shared/assets/os"),
    # Ozadja namizja Safeer OS (namizje_qml.OZADJA, 3,4 MB).
    ("assets/ozadja", "shared/assets/ozadja"),
    # Namizje Safeer OS v Qt Quick: namizje_qml.QML = <safeer_windows>/qml/Namizje.qml (pregled 25. 10. 2026, V1).
    ("windows/safeer_windows/qml", "safeer_windows/qml"),
    ("windows/VERSION", "shared/windows"),
]

#: Moduli QML, ki jih namizje Safeer OS uvozi (windows/safeer_windows/qml/*.qml) - koreni; prune_bundle obdrzi te in
#: vse, od cesar so odvisni (vrstice »import« in »depends« v njihovih qmldir), vse drugo v PySide6/qml (Qt3D, Charts,
#: Multimedia, Quick3D, WebEngine, sloge Fusion/Material/Universal/Imagine/FluentWinUI3/Windows ...) odstrani.
#: QtQuick.Controls.Basic.impl in QtQuick.Shapes: prevedeni QML Basic (Qt6QuickControls2Basic.dll, Qt 6.11.2) ju uvozi,
#: qmldir ju ne navaja - brez njiju »Type TextField unavailable« v zamrznjenem SafeerOS.exe (CI 40204237696, 25. 10.).
QML_KORENI = ("QtQml", "QtQuick", "QtQuick.Window", "QtQuick.Controls.Basic", "QtQuick.Controls.Basic.impl",
              "QtQuick.Controls.impl", "QtQuick.Templates", "QtQuick.Shapes", "QtQuick.Layouts", "QtQuick.Effects",
              "QtQuick.Dialogs", "QtQuick.Dialogs.quickimpl", "Qt.labs.folderlistmodel")


def version() -> str:
    with open(os.path.join(WINDOWS, "VERSION"), encoding="utf-8") as handle:
        return handle.read().strip()


def run(command, **kwargs) -> None:
    print("+", " ".join(str(part) for part in command), flush=True)
    subprocess.run(command, check=True, **kwargs)


def make_icon() -> str:
    from PIL import Image

    os.makedirs(BUILD, exist_ok=True)
    image = Image.open(os.path.join(ROOT, "assets", "icon.png")).convert("RGBA")
    image.save(ICON, sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icon:", ICON)
    return ICON


def shared_imports() -> list:
    """Top-level modules the shared core files import.

    Those files ship as data and are loaded with importlib at run time, so PyInstaller never
    analyses them; a standard-library module they need is bundled only if something else happens
    to import it. urllib.request stopped being bundled that way and the packaged build crashed at
    start, so every import is named explicitly.
    """
    import ast

    names = set()
    for source, _target in SHARED_DATA:
        if not source.endswith(".py"):
            continue
        tree = ast.parse(open(os.path.join(ROOT, *source.split("/")), encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.add(node.module)
    # the shared files import each other by path, never as packages
    return sorted(n for n in names if n != "__future__" and not n.startswith("core."))


#: libmpv: kamor ga razpakira windows/fetch_libmpv.py (CILJ). Prej je gradnja iskala windows/vendor/mpv in uradni paket
#: je bil BREZ libmpv (CI 25. 10. 2026: »windows/vendor/mpv ni prisoten«; pomocnik na testnem PC, naloga 13).
VENDOR_MPV = os.path.join(WINDOWS, "safeer_windows", "vendor", "mpv")
#: MSVC runtime, ki ga libmpv potrebuje (manifest.json: novejsi od tistega, ki ga prinese PySide6).
MSVC_RUNTIME = ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll")
_MPV_OBVEZNO = ("libmpv-2.dll", "libEGL.dll", "libGLESv2.dll", "manifest.json", "safeer-capabilities.json",
                os.path.join("runtime", "msvcp140.dll"), os.path.join("runtime", "vcruntime140.dll"),
                os.path.join("runtime", "vcruntime140_1.dll"), os.path.join("licenses", "COPYING.LGPL-2.1"))


def mpv_vendor_args() -> list:
    """libmpv (lastna LGPL gradnja) je izbirna priloga: windows/vendor/mpv -> _internal/safeer_windows/vendor/mpv.

    Brez mape se zgradi kot doslej (LibVLC/HTML5). Ce mapa obstaja, mora biti POPOLNA (pravilo 6: manjkajoca
    DLL ali runtime ustavi gradnjo, ne tiho izpusti) in gradnja prilozi tudi python-mpv.
    """
    if not os.path.isdir(VENDOR_MPV):
        print("libmpv: windows/safeer_windows/vendor/mpv ni prisoten (python windows/fetch_libmpv.py) -> brez libmpv "
              "(Medijski center: LibVLC/HTML5)", flush=True)
        return []
    manjka = [f for f in _MPV_OBVEZNO if not os.path.isfile(os.path.join(VENDOR_MPV, f))]
    if manjka:
        raise SystemExit("libmpv: windows/safeer_windows/vendor/mpv je nepopoln, manjka: " + ", ".join(manjka))
    # python-mpv ob uvozu isce libmpv-2.dll na PATH (CI 40360126842, 26. 10. 2026: »Cannot find mpv-1.dll ...«) -
    # preverjamo PRILOZENO knjiznico, zato jo damo na zacetek PATH (obstojeca spremenljivka, gradnja brez niti).
    os.environ["PATH"] = VENDOR_MPV + os.pathsep + os.environ.get("PATH", "")
    try:
        import mpv  # noqa: F401
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"libmpv: paket python-mpv ni namescen v gradbenem okolju ({e}); pip install python-mpv==1.0.8")
    man = json.load(open(os.path.join(VENDOR_MPV, "manifest.json"), encoding="utf-8-sig"))
    print(f"libmpv: prilozen {man.get('release')} ({man.get('arch')}), runtime {man.get('runtime', {}).get('msvcp140.dll')}", flush=True)
    smtc = []
    try:
        import winrt.windows.media.playback  # noqa: F401
        smtc = ["--hidden-import", "safeer_windows.predvajalnik_smtc", "--collect-submodules", "winrt"]
        print("SMTC: paketi winrt prisotni -> sistemske medijske kontrole prilozene", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"SMTC: paketi winrt niso namesceni ({e}) -> predvajalnik brez sistemskih medijskih kontrol (nadzorovan preskok)", flush=True)
    return ["--add-data", VENDOR_MPV + os.pathsep + os.path.join("safeer_windows", "vendor", "mpv"),
            "--hidden-import", "mpv", "--hidden-import", "safeer_windows.mpv_player",
            "--hidden-import", "safeer_windows.safeer_mpv_pogon", "--hidden-import", "safeer_windows.safeer_pogon_izbira"] + smtc


def pyinstaller() -> None:
    make_icon()
    shutil.rmtree(DIST, ignore_errors=True)
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", "SafeerBrowser", "--icon", ICON,
        "--distpath", DIST, "--workpath", os.path.join(BUILD, "work"), "--specpath", BUILD,
        "--paths", WINDOWS,
        "--hidden-import", "safeer_windows.smoke",
        # Loaded dynamically by core/signed_feed.py; the pure-Python verifier is the fallback.
        "--hidden-import", "cryptography.hazmat.primitives.asymmetric.ed25519",
        "--hidden-import", "cryptography.exceptions",
        "--exclude-module", "tkinter",
        "--exclude-module", "PIL",  # brskalnik ga ne rabi; SafeerOS.exe ga ima (gradnja spodaj) v istem _internal
    ]
    for name in shared_imports():
        command += ["--hidden-import", name]
    for source, target in SHARED_DATA:
        command += ["--add-data", os.path.join(ROOT, *source.split("/")) + os.pathsep + target]
    command += mpv_vendor_args()
    command.append(os.path.join(WINDOWS, "launcher.py"))
    run(command)
    if not os.path.exists(EXE):
        raise SystemExit(f"missing {EXE}")
    webengine = [name for name in os.listdir(os.path.join(APP_DIR, "_internal", "PySide6"))] \
        if os.path.isdir(os.path.join(APP_DIR, "_internal", "PySide6")) else []
    print("bundled PySide6 entries:", len(webengine))
    helper = [os.path.join(dirpath, name) for dirpath, _dirs, files in os.walk(APP_DIR) for name in files
              if name.lower() == "qtwebengineprocess.exe"]
    if not helper:
        raise SystemExit("QtWebEngineProcess.exe was not bundled")
    print(f"built {EXE} ({dir_size(APP_DIR) / 1048576:.0f} MB); helper: {helper[0]}")

    # Build SafeerOS.exe in the same bundle
    os_launcher = os.path.join(WINDOWS, "launcher_os.py")
    if os.path.exists(os_launcher):
        print("🔨 Gradnja SafeerOS.exe...", flush=True)
        command_os = [
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
            "--name", "SafeerOS", "--icon", ICON,
            "--distpath", DIST, "--workpath", os.path.join(BUILD, "work_os"), "--specpath", BUILD,
            "--paths", WINDOWS,
            "--exclude-module", "tkinter",
            # Pillow ostane (25. 10. 2026): rabijo ga zajem zaslona (zajem_zaslona, »Deli z«), slicice datotek in
            # Link; prej je bil tu izpuscen in deljenje zaslona v uradnem paketu ni delalo (kodek-frozen v CI).
        ]
        for name in shared_imports():
            command_os += ["--hidden-import", name]
        for source, target in SHARED_DATA:
            command_os += ["--add-data", os.path.join(ROOT, *source.split("/")) + os.pathsep + target]
        command_os += mpv_vendor_args()
        command_os.append(os_launcher)
        run(command_os)
        os_exe = os.path.join(DIST, "SafeerOS", "SafeerOS.exe")
        if os.path.exists(os_exe):
            shutil.copy2(os_exe, os.path.join(APP_DIR, "SafeerOS.exe"))
            print(f"SafeerOS.exe uspešno dodan v {APP_DIR}")
            # SafeerOS.exe uporablja _internal brskalnika: dodaj, kar ima samo gradnja Safeer OS (QtQuick, QML ...).
            copied = merge_internal(os.path.join(DIST, "SafeerOS", "_internal"), os.path.join(APP_DIR, "_internal"))
            print(f"merge: {len(copied)} datotek iz gradnje SafeerOS v _internal brskalnika")
    zamenjane = zamenjaj_msvc_runtime(APP_DIR)
    if zamenjane:
        print(f"MSVC runtime iz vendor/mpv/runtime: {len(zamenjane)} kopij ({', '.join(sorted(set(zamenjane)))})")
    # Na koncu, ko je v _internal vse za oba exe: neuporabljeni moduli Qt in QML (QML namizja ostane).
    prune_bundle()


#: Vsa druzina runtime MSVC (VC_redist; Microsoft: v procesu iste razlicice). vendor/mpv prinese samo MSVC_RUNTIME.
MSVC_DRUZINA = re.compile(r"^(msvcp140(_\d|_atomic_wait|_codecvt_ids)?|vcruntime140(_1|_threads)?|concrt140|"
                          r"vccorlib140|vcomp140)\.dll$", re.I)
#: Podpisnik runtime MSVC (izmerjeno 25. 10. 2026 na 14.51.36247: »CN=Microsoft Windows Software Compatibility
#: Publisher, O=Microsoft Corporation«, stanje Valid).
PODPISNIK_MSVC = "O=Microsoft Corporation"


def podpis_microsoft(poti) -> dict:
    """{pot: True/False}: veljaven podpis Authenticode Microsoft Corporation (Get-AuthenticodeSignature)."""
    if sys.platform != "win32":
        raise SystemExit("podpis runtime MSVC se preveri samo na Windows")
    navedi = ",".join("'" + str(p).replace("'", "''") + "'" for p in poti)
    ukaz = ("foreach ($p in @(" + navedi + ")) { $s = Get-AuthenticodeSignature -LiteralPath $p; "
            "'{0}|{1}|{2}' -f $p, $s.Status, $s.SignerCertificate.Subject }")
    izhod = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ukaz],
                           capture_output=True, text=True, timeout=120).stdout
    izid = {str(p): False for p in poti}
    for vrstica in izhod.splitlines():
        pot, _, ostalo = vrstica.partition("|")
        stanje, _, podpisnik = ostalo.partition("|")
        if pot in izid:
            izid[pot] = stanje.strip() == "Valid" and PODPISNIK_MSVC in podpisnik
    return izid


def razlicica_pe(pot: str) -> tuple:
    """FileVersion iz VS_FIXEDFILEINFO (pefile pride s PyInstaller na Windows); () ce je ni."""
    import pefile
    pe = pefile.PE(pot, fast_load=True)
    try:
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
        info = getattr(pe, "VS_FIXEDFILEINFO", None)
        info = info[0] if isinstance(info, list) and info else info
        if info is None:
            return ()
        return (info.FileVersionMS >> 16, info.FileVersionMS & 0xFFFF, info.FileVersionLS >> 16,
                info.FileVersionLS & 0xFFFF)
    finally:
        pe.close()


def preveri_vir_runtime(viri: dict, podpis=None, razlicica=None) -> dict:
    """Runtime iz vendor/mpv/runtime gre v VSE programe paketa (Splet, Control, Safeer OS), zato mora biti podpisan
    z Microsoftovim podpisom in imeti razlicico (Grok X3, 25. 10. 2026; prej se je preverilo samo, ali obstaja).
    Vrne {ime: razlicica}; sicer ustavi gradnjo."""
    podpis, razlicica = podpis or podpis_microsoft, razlicica or razlicica_pe
    slabi = [p for p, ok in podpis(sorted(viri.values())).items() if not ok]
    if slabi:
        raise SystemExit("runtime MSVC iz vendor/mpv/runtime ni podpisan z Microsoftovim podpisom: " + ", ".join(slabi))
    razlicice = {ime: razlicica(pot) for ime, pot in viri.items()}
    brez = [ime for ime, r in razlicice.items() if not r]
    if brez:
        raise SystemExit("runtime MSVC iz vendor/mpv/runtime nima razlicice: " + ", ".join(brez))
    return razlicice


def zamenjaj_msvc_runtime(app_dir: str, vendor: str = "", podpis=None, razlicica=None) -> list:
    """Kopije msvcp140/vcruntime140(_1) v paketu zamenja z novejsimi iz vendor/mpv/runtime (runtime MSVC je nazaj
    zdruzljiv). pyi_rth_pyside6 nalozi shiboken6 PRED zaganjalnikom, zato starejsi msvcp140 iz PySide6 pride v proces
    pred predpripravi_runtime in libmpv ne stece (»MSVC runtime prestar«: 14.44 < 14.51; testni PC, naloga 13,
    25. 10. 2026). Samo podpisan Microsoftov runtime in nikoli starejsi od kopije v paketu (Grok X3). Brez libmpv v
    paketu ne naredi nicesar. Vrne imena zamenjanih datotek."""
    runtime = os.path.join(vendor or VENDOR_MPV, "runtime")
    viri = {ime: os.path.join(runtime, ime) for ime in MSVC_RUNTIME if os.path.isfile(os.path.join(runtime, ime))}
    if len(viri) != len(MSVC_RUNTIME):
        return []
    razlicica = razlicica or razlicica_pe
    nove = preveri_vir_runtime(viri, podpis, razlicica)
    zamenjane, druzina = [], set()
    for mapa, _podmape, datoteke in os.walk(app_dir):
        v_runtime = os.path.normcase(os.path.abspath(mapa)) == os.path.normcase(os.path.abspath(runtime))
        for ime in datoteke:
            vir = viri.get(ime.lower())
            cilj = os.path.join(mapa, ime)
            if v_runtime:
                continue
            if not vir:
                if MSVC_DRUZINA.match(ime):
                    druzina.add(ime.lower())
                continue
            if razlicica(cilj) > nove[ime.lower()]:
                print(f"MSVC runtime: {os.path.relpath(cilj, app_dir)} je novejsi od vendor/mpv - ostane")
                continue
            shutil.copy2(vir, cilj)
            zamenjane.append(ime.lower())
    if druzina:
        print("::warning::MSVC runtime: v paketu ostanejo clani druzine, ki jih vendor/mpv ne prinese (starejsa "
              "razlicica ob novejsem msvcp140): " + ", ".join(sorted(druzina)))
    return zamenjane


#: FFmpeg, ki ga PySide6 prinese samo za vticnik QtMultimedia (plugins/multimedia/ffmpegmediaplugin.dll - edini, ki ga
#: uvozi; izmerjeno na kolesih PySide6 6.11.2, 25. 10. 2026). prune_bundle vticnike multimedia odstrani, zato je ta
#: FFmpeg v paketu mrtva tuja koda brez CFG/CET (13+ MB).
FFMPEG_PYSIDE = re.compile(r"^(avcodec|avformat|avutil|avfilter|avdevice|swresample|swscale|postproc)-[0-9]+\.dll$",
                           re.I)


def odstrani_ffmpeg_pyside(pyside: str) -> list:
    """Odstrani FFmpeg iz korena mape PySide6, ce vticnikov multimedia ni (nihce ga ne nalozi). Vrne imena."""
    if os.path.isdir(os.path.join(pyside, "plugins", "multimedia")):
        return []
    odstranjene = []
    for ime in os.listdir(pyside) if os.path.isdir(pyside) else []:
        if FFMPEG_PYSIDE.match(ime):
            os.remove(os.path.join(pyside, ime))
            odstranjene.append(ime)
    return odstranjene


def dir_size(path: str) -> int:
    return sum(os.path.getsize(os.path.join(d, f)) for d, _s, files in os.walk(path) for f in files)


# Qt plugin folders a Qt WebEngine widgets browser never loads.
UNUSED_PLUGIN_DIRS = {
    "assetimporters", "canbus", "designer", "geometryloaders", "help", "multimedia", "platforminputcontexts",
    "qmllint", "qmltooling", "renderers", "renderplugins", "sceneparsers", "scxmldatamodel", "sensors",
    "sqldrivers", "texttospeech", "virtualkeyboard", "webview", "3dinputdevices", "generic",
}


def pe_imports(path: str) -> set:
    import pefile  # shipped with PyInstaller on Windows

    pe = pefile.PE(path, fast_load=True)
    try:
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                                               pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
        names = set()
        for attribute in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT"):
            for entry in getattr(pe, attribute, None) or []:
                names.add(entry.dll.decode("ascii", "ignore").lower())
        return names
    finally:
        pe.close()


def qmldir_odvisnosti(besedilo: str) -> list:
    """Moduli, ki jih modul QML potrebuje: vrstice »import X« in »depends X« iz qmldir (brez »optional import« in
    »default import« - to so izbirni slogi Controls, ki jih namizje ne uporablja)."""
    izid = []
    for vrstica in (besedilo or "").splitlines():
        deli = vrstica.split()
        if len(deli) >= 2 and deli[0] in ("import", "depends"):
            izid.append(deli[1])
    return izid


def potrebni_qml(qml: str, koreni=QML_KORENI) -> set:
    """Mape modulov QML (relativne, z »/«), ki ostanejo: koreni in njihove odvisnosti po qmldir."""
    potrebni, vrsta = set(), list(koreni)
    while vrsta:
        modul = vrsta.pop()
        rel = modul.replace(".", "/")
        if rel in potrebni:
            continue
        potrebni.add(rel)
        try:
            with open(os.path.join(qml, *rel.split("/"), "qmldir"), encoding="utf-8", errors="replace") as f:
                vrsta.extend(m for m in qmldir_odvisnosti(f.read()) if m.replace(".", "/") not in potrebni)
        except OSError:
            continue
    return potrebni


def ohrani_mapo_qml(rel: str, potrebni: set) -> bool:
    """Mapa v PySide6/qml ostane, ce je potreben modul ali njegova nadrejena mapa (npr. »QtQuick/Controls« za Basic)."""
    rel = rel.strip("/")
    return any(p == rel or p.startswith(rel + "/") for p in potrebni)


def prune_qml(qml: str) -> None:
    """PySide6/qml: odstrani mape modulov, ki jih nihce ne uvozi; datoteke v mapah, ki ostanejo (qmldir, vticnik,
    *.qmltypes), ostanejo cele."""
    if not os.path.isdir(qml):
        return
    potrebni = potrebni_qml(qml)
    for dirpath, dirs, _files in os.walk(qml, topdown=True):
        rel_dir = os.path.relpath(dirpath, qml).replace(os.sep, "/")
        rel_dir = "" if rel_dir == "." else rel_dir
        for name in list(dirs):
            rel = (rel_dir + "/" + name).strip("/")
            if not ohrani_mapo_qml(rel, potrebni):
                shutil.rmtree(os.path.join(dirpath, name), ignore_errors=True)
                dirs.remove(name)
    print("prune: QML ostane:", ", ".join(sorted(potrebni)))


def merge_internal(src: str, dst: str) -> list:
    """SafeerOS.exe tece iz mape SafeerBrowser in uporablja NJEN _internal: datoteke, ki jih potrebuje samo Safeer OS
    (QtQuick, moduli QML, ...), prekopiramo iz _internal gradnje SafeerOS. Obstojece datoteke ostanejo (iste verzije)."""
    copied = []
    for dirpath, _dirs, files in os.walk(src):
        rel = os.path.relpath(dirpath, src)
        for name in files:
            target = os.path.join(dst, rel, name)
            if not os.path.exists(target):
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(os.path.join(dirpath, name), target)
                copied.append(os.path.join(rel, name))
    return copied


def prune_bundle() -> None:
    """Removes Qt modules (Qt 3D, Quick Controls, QML plugins ...) that nothing in the browser loads.

    Roots are every executable, every collected PySide6 extension module (they import each other at
    runtime), every kept Qt plugin and every non-Qt library; a Qt6*.dll stays when a root reaches it
    through PE import tables, so the removals cannot break loading.
    """
    pyside = os.path.join(APP_DIR, "_internal", "PySide6")
    if not os.path.isdir(pyside):
        print("prune: PySide6 folder not found, skipped")
        return
    before = dir_size(APP_DIR)
    prune_qml(os.path.join(pyside, "qml"))
    resources = os.path.join(pyside, "resources")
    if os.path.isdir(resources):
        for name in os.listdir(resources):
            if name.lower().endswith(".debug.pak"):  # developer-build DevTools resources, never loaded
                os.remove(os.path.join(resources, name))
    plugins = os.path.join(pyside, "plugins")
    if os.path.isdir(plugins):
        for name in os.listdir(plugins):
            if name.lower() in UNUSED_PLUGIN_DIRS:
                shutil.rmtree(os.path.join(plugins, name), ignore_errors=True)
    odstranjen_ffmpeg = odstrani_ffmpeg_pyside(pyside)
    if odstranjen_ffmpeg:
        print("prune: FFmpeg PySide6 brez vticnika multimedia odstranjen:", ", ".join(sorted(odstranjen_ffmpeg)))
    binaries = {}
    for dirpath, _dirs, files in os.walk(APP_DIR):
        for name in files:
            if name.lower().endswith((".dll", ".pyd", ".exe")):
                binaries.setdefault(name.lower(), os.path.join(dirpath, name))
    roots = []
    for name, path in binaries.items():
        inside_pyside = os.path.abspath(path).lower().startswith(os.path.abspath(pyside).lower() + os.sep)
        if not inside_pyside:
            roots.append(path)
        elif name.endswith(".exe") or os.sep + "plugins" + os.sep in path.lower():
            roots.append(path)
        elif not (name.startswith("qt6") and name.endswith(".dll")):
            roots.append(path)
    needed = set()
    queue = list(roots)
    while queue:
        path = queue.pop()
        key = os.path.basename(path).lower()
        if key in needed:
            continue
        needed.add(key)
        try:
            imports = pe_imports(path)
        except Exception as error:  # keep going; an unreadable binary is simply kept
            print(f"prune: cannot read imports of {path}: {error}")
            continue
        queue.extend(binaries[name] for name in imports if name in binaries and name not in needed)
    removed = []
    for name, path in binaries.items():
        inside_pyside = os.path.abspath(path).lower().startswith(os.path.abspath(pyside).lower() + os.sep)
        if inside_pyside and name not in needed and name.startswith("qt6") and name.endswith(".dll"):
            os.remove(path)
            removed.append(name)
    after = dir_size(APP_DIR)
    print(f"prune: removed {len(removed)} binaries and unused QML/plugins, {before / 1048576:.0f} MB -> {after / 1048576:.0f} MB")
    print("prune: removed", ", ".join(sorted(removed)))
    largest = sorted(((os.path.getsize(os.path.join(d, f)), os.path.relpath(os.path.join(d, f), APP_DIR))
                      for d, _s, files in os.walk(APP_DIR) for f in files), reverse=True)[:15]
    for size, name in largest:
        print(f"  {size / 1048576:6.1f} MB  {name}")


def print_report(path: str) -> bool:
    if not os.path.exists(path):
        print(f"smoke report missing: {path}")
        return False
    with open(path, encoding="utf-8") as handle:
        report = json.load(handle)
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2, ensure_ascii=False))
    for result in report.get("results", []):
        mark = "PASS" if result["ok"] else ("FAIL" if result["required"] else "WARN")
        detail = result.get("detail")
        detail_text = json.dumps(detail, ensure_ascii=False, default=str) if not isinstance(detail, str) else detail
        print(f"{mark:4} {result['name']}: {detail_text[:600]}")
    return bool(report.get("ok"))


def smoke(command, report: str, online: bool, screenshot: str | None, env=None, timeout: int = 600) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(report)), exist_ok=True)
    if os.path.exists(report):
        os.remove(report)
    data_dir = tempfile.mkdtemp(prefix="safeer-smoke-")
    full = list(command) + ["--smoke-test", "--report", os.path.abspath(report), "--data-dir", data_dir]
    if online:
        full.append("--online")
    if screenshot:
        os.makedirs(os.path.dirname(os.path.abspath(screenshot)), exist_ok=True)
        full += ["--screenshot", os.path.abspath(screenshot)]
    print("+", " ".join(full), flush=True)
    started = time.monotonic()
    completed = subprocess.run(full, env=env, timeout=timeout)
    print(f"exit code {completed.returncode} after {time.monotonic() - started:.0f}s")
    ok = print_report(report)
    shutil.rmtree(data_dir, ignore_errors=True)
    if screenshot:
        print_screenshots(screenshot)
    if completed.returncode != 0 or not ok:
        raise SystemExit("smoke test failed")


def print_screenshots(screenshot: str) -> None:
    """Prints small JPEG previews into the CI log so the Windows UI can be reviewed without downloads."""
    try:
        import base64
        import io
        from PIL import Image
    except ImportError:
        return
    stem, ext = os.path.splitext(os.path.abspath(screenshot))
    for path in (stem + ext, stem + "-settings" + ext):
        if not os.path.exists(path):
            continue
        image = Image.open(path).convert("RGB")
        image.thumbnail((960, 960))
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=62, optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        print(f"SAFEER_SCREENSHOT_BEGIN {os.path.basename(path)} {image.size[0]}x{image.size[1]} {len(encoded)}")
        for start in range(0, len(encoded), 2000):
            print(encoded[start:start + 2000])
        print("SAFEER_SCREENSHOT_END")


def smoke_source(args) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = WINDOWS + os.pathsep + env.get("PYTHONPATH", "")
    smoke([sys.executable, "-m", "safeer_windows"], args.report, args.online, args.screenshot, env=env)


def smoke_frozen(args) -> None:
    exe = args.exe or EXE
    version_file = os.path.join(BUILD, "version.txt")
    run([exe, "--version", "--report", version_file], timeout=120)
    with open(version_file, encoding="utf-8") as handle:
        reported = handle.read().strip()
    expected = f"Safeer Browser {version()}"
    if reported != expected:
        raise SystemExit(f"--version reported {reported!r}, expected {expected!r}")
    print(reported)
    smoke([exe], args.report, args.online, args.screenshot)


def qml_frozen(args) -> None:
    """Namizje QML v zamrznjenem SafeerOS.exe (pregled V1): mapa qml in obrezani moduli Qt Quick morajo biti v paketu."""
    exe = args.exe or os.path.join(APP_DIR, "SafeerOS.exe")
    report = os.path.abspath(args.report)
    os.makedirs(os.path.dirname(report), exist_ok=True)
    if os.path.exists(report):
        os.remove(report)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    print("+", exe, "--preveri-qml", report, flush=True)
    completed = subprocess.run([exe, "--preveri-qml", report], env=env, timeout=180)
    data = {}
    if os.path.exists(report):
        with open(report, encoding="utf-8") as handle:
            data = json.load(handle)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    if completed.returncode != 0 or not data.get("ok"):
        raise SystemExit(f"Namizje.qml se v zamrznjenem SafeerOS.exe ne nalozi (izhod {completed.returncode})")


def kodek_frozen(args) -> None:
    """PyAV in Pillow v zamrznjenem SafeerOS.exe: zajem zaslona v H.264 (deljenje) in dekodiranje (gledalec).
    Do 25. 10. 2026 ju v paketu ni bilo, preizkusi iz izvora pa tega niso videli (preveri_kodek.py)."""
    exe = args.exe or os.path.join(APP_DIR, "SafeerOS.exe")
    report = os.path.abspath(args.report)
    os.makedirs(os.path.dirname(report), exist_ok=True)
    if os.path.exists(report):
        os.remove(report)
    print("+", exe, "--preveri-kodek", report, flush=True)
    completed = subprocess.run([exe, "--preveri-kodek", report], timeout=180)
    data = {}
    if os.path.exists(report):
        with open(report, encoding="utf-8") as handle:
            data = json.load(handle)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    if completed.returncode != 0 or not data.get("ok"):
        raise SystemExit(f"Zajem ali dekodiranje slike v SafeerOS.exe ne dela (izhod {completed.returncode})")


def find_iscc() -> str:
    candidates = [shutil.which("iscc"), shutil.which("ISCC"),
                  os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Inno Setup 6", "ISCC.exe"),
                  os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Inno Setup 6", "ISCC.exe"),
                  os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe")]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    raise SystemExit("Inno Setup 6 (ISCC.exe) was not found")


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def package() -> None:
    if not os.path.exists(EXE):
        raise SystemExit("run pyinstaller first")
    make_icon()
    os.makedirs(OUT, exist_ok=True)
    current = version()
    portable = os.path.join(OUT, f"SafeerBrowser-{current}-windows-x64-portable.zip")
    with zipfile.ZipFile(portable, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for dirpath, _dirs, files in os.walk(APP_DIR):
            for name in files:
                path = os.path.join(dirpath, name)
                archive.write(path, os.path.join("Safeer Browser", os.path.relpath(path, APP_DIR)))
    run([find_iscc(), f"/DAppVersion={current}", f"/DAppSourceDir={APP_DIR}", f"/DAppOutputDir={OUT}",
         f"/DAppIconFile={ICON}", os.path.join(WINDOWS, "installer.iss")])
    installer = os.path.join(OUT, f"SafeerBrowser-{current}-windows-x64-setup.exe")
    if not os.path.exists(installer):
        raise SystemExit(f"missing {installer}")
    names = [os.path.basename(portable), os.path.basename(installer)]
    with open(os.path.join(OUT, "SHA256SUMS"), "w", encoding="utf-8", newline="\n") as handle:
        for name in names:
            handle.write(f"{sha256(os.path.join(OUT, name))}  {name}\n")
    for name in names + ["SHA256SUMS"]:
        print(f"{name}: {os.path.getsize(os.path.join(OUT, name)) / 1048576:.1f} MB")


def registry_value(path: str, name: str = ""):
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def install_test(args) -> None:
    current = version()
    installer = os.path.join(OUT, f"SafeerBrowser-{current}-windows-x64-setup.exe")
    target = os.path.join(tempfile.gettempdir(), "SafeerBrowserInstallTest")
    shutil.rmtree(target, ignore_errors=True)
    log = os.path.join(OUT, "install.log")
    run([installer, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER", f"/DIR={target}", f"/LOG={log}"], timeout=600)
    exe = os.path.join(target, "SafeerBrowser.exe")
    if not os.path.exists(exe):
        raise SystemExit("installer did not create SafeerBrowser.exe")
    checks = {
        "RegisteredApplications": registry_value(r"Software\RegisteredApplications", "Safeer Browser"),
        "StartMenuInternet": registry_value(r"Software\Clients\StartMenuInternet\SafeerBrowser\Capabilities", "ApplicationName"),
        "https association": registry_value(r"Software\Clients\StartMenuInternet\SafeerBrowser\Capabilities\URLAssociations", "https"),
        "URL command": registry_value(r"Software\Classes\SafeerBrowserURL\shell\open\command"),
        "HTML command": registry_value(r"Software\Classes\SafeerBrowserHTML\shell\open\command"),
    }
    print(json.dumps(checks, indent=2))
    if not all(checks.values()) or exe.lower() not in str(checks["URL command"]).lower():
        raise SystemExit("browser registration is incomplete")
    smoke_args = argparse.Namespace(exe=exe, report=os.path.join(OUT, "smoke-installed.json"), online=False, screenshot=None)
    smoke_frozen(smoke_args)
    uninstaller = os.path.join(target, "unins000.exe")
    run([uninstaller, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=300)
    deadline = time.monotonic() + 120
    while os.path.exists(exe) and time.monotonic() < deadline:
        time.sleep(1)
    if os.path.exists(exe):
        raise SystemExit("uninstaller left SafeerBrowser.exe behind")
    if registry_value(r"Software\RegisteredApplications", "Safeer Browser") is not None:
        raise SystemExit("uninstaller left the browser registration behind")
    print("install, launch and uninstall: OK")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("icon")
    sub.add_parser("fetch-libmpv")
    sub.add_parser("pyinstaller")
    sub.add_parser("package")
    for name in ("smoke-source", "smoke-frozen"):
        smoke_parser = sub.add_parser(name)
        smoke_parser.add_argument("--report", default=os.path.join(OUT, f"{name}.json"))
        smoke_parser.add_argument("--online", action="store_true")
        smoke_parser.add_argument("--screenshot")
        smoke_parser.add_argument("--exe")
    qml_parser = sub.add_parser("qml-frozen")
    qml_parser.add_argument("--report", default=os.path.join(OUT, "qml-frozen.json"))
    qml_parser.add_argument("--exe")
    kodek_parser = sub.add_parser("kodek-frozen")
    kodek_parser.add_argument("--report", default=os.path.join(OUT, "kodek-frozen.json"))
    kodek_parser.add_argument("--exe")
    sub.add_parser("install-test")
    args = parser.parse_args()
    if args.command == "fetch-libmpv":
        import fetch_libmpv
        raise SystemExit(fetch_libmpv.main())
    if args.command == "icon":
        make_icon()
    elif args.command == "pyinstaller":
        pyinstaller()
    elif args.command == "package":
        package()
    elif args.command == "smoke-source":
        smoke_source(args)
    elif args.command == "smoke-frozen":
        smoke_frozen(args)
    elif args.command == "qml-frozen":
        qml_frozen(args)
    elif args.command == "kodek-frozen":
        kodek_frozen(args)
    elif args.command == "install-test":
        install_test(args)


if __name__ == "__main__":
    main()
