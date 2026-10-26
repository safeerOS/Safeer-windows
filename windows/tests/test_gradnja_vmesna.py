"""Naloga 37 (CI 40364712707, 26. 10. 2026): korak »PE hardening« pregleda cel build/windows/dist in je padel na FFmpeg
iz PySide6 (avcodec-61 ...) v vmesni gradnji dist/SafeerOS. Ta ni v paketu (vse nadaljnje vzame SafeerBrowser, ki ga
prune_bundle obreze); po zdruzitvi jo gradnja odstrani, da v dist ostane samo, kar gre uporabniku."""
import os
import re
import sys
from pathlib import Path

WIN = Path(__file__).resolve().parents[1]
if str(WIN) not in sys.path:
    sys.path.insert(0, str(WIN))

import build_windows as b  # noqa: E402

FFMPEG = ("avcodec-61.dll", "avformat-61.dll", "avutil-59.dll", "swresample-5.dll", "swscale-8.dll")


def _dist(tmp_path, s_exe=True):
    dist = tmp_path / "dist"
    pyside = dist / "SafeerOS" / "_internal" / "PySide6"
    (pyside / "plugins" / "multimedia").mkdir(parents=True)
    for ime in FFMPEG:
        (pyside / ime).write_bytes(b"MZ")
    (pyside / "plugins" / "multimedia" / "ffmpegmediaplugin.dll").write_bytes(b"MZ")
    (dist / "SafeerOS" / "SafeerOS.exe").write_bytes(b"MZ")
    (dist / "SafeerBrowser" / "_internal").mkdir(parents=True)
    if s_exe:
        (dist / "SafeerBrowser" / "SafeerOS.exe").write_bytes(b"MZ")
    return dist


def test_vmesna_gradnja_safeeros_ne_ostane_v_dist(tmp_path):
    dist = _dist(tmp_path)
    assert b.pospravi_vmesno_gradnjo(str(dist))
    ostale = [p.name for p in dist.rglob("*") if p.is_file()]
    assert not any(ime in ostale for ime in FFMPEG + ("ffmpegmediaplugin.dll",)), ostale
    assert (dist / "SafeerBrowser" / "SafeerOS.exe").is_file(), "paket ostane"


def test_brez_safeeros_v_paketu_vmesna_ostane(tmp_path):
    # Ce SafeerOS.exe se ni v SafeerBrowser (zdruzitev ni uspela), vmesne gradnje ne brisemo - ni izgube dela.
    dist = _dist(tmp_path, s_exe=False)
    assert not b.pospravi_vmesno_gradnjo(str(dist))
    assert (dist / "SafeerOS" / "_internal" / "PySide6" / "avcodec-61.dll").is_file()


def test_pyinstaller_pospravi_po_zdruzitvi_in_pred_obrezom():
    besedilo = (WIN / "build_windows.py").read_text(encoding="utf-8")
    telo = besedilo[besedilo.index("def pyinstaller() -> None:"):besedilo.index("\ndef ", besedilo.index("def pyinstaller() -> None:") + 1)]
    zdruzi = telo.index("merge_internal(")
    pospravi = telo.index("pospravi_vmesno_gradnjo(DIST)")
    assert zdruzi < pospravi < telo.index("prune_bundle()"), "vmesna gradnja se odstrani po zdruzitvi v SafeerBrowser"
    # Nobena kasnejsa pot (package, *-frozen, install-test) ne bere dist/SafeerOS.
    ostalo = besedilo.replace(telo, "")
    assert not re.search(r"""os\.path\.join\(DIST,\s*["']SafeerOS["']""", ostalo)


def test_zgrajen_dist_brez_ffmpeg_pyside():
    # Ko je paket zgrajen na tem PC (python windows/build_windows.py pyinstaller): v dist ni FFmpeg iz PySide6.
    dist = Path(b.DIST)
    if not (dist / "SafeerBrowser" / "SafeerOS.exe").is_file():
        import pytest
        pytest.skip("paket ni zgrajen")
    najdene = [str(p.relative_to(dist)) for p in dist.rglob("*.dll") if b.FFMPEG_PYSIDE.match(p.name)
               or p.name.lower() == "ffmpegmediaplugin.dll"]
    assert najdene == []
