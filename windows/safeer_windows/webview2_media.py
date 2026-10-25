"""Pravi WebView2 predvajalnik, vdelan v okno Safeer OS na Windows."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import json
import urllib.parse
from pathlib import Path
from typing import Callable, Optional

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import safeer_drm_prenos
from .media_diagnostics import source_rejection


def _koren_sej() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "SafeerOS/WebView2Sessions"


def pocisti_seje(koren: Optional[Path] = None, razen: str = "", starejse_od_s: float = 0.0) -> int:
    """Pobrise zacasne profile WebView2, ki jih nihce vec ne uporablja; vrne stevilo pobrisanih.

    Takoj po zaprtju predvajalnika msedgewebview2.exe se nekaj trenutkov drzi datotek, zato je
    rmtree prej tiho spodletel in seje so se kopicile (47 map, 680 MB). Zaklenjene mape preskocimo
    in jih pobrisemo ob naslednjem ciscenju.
    """
    koren = koren or _koren_sej()
    pobrisanih = 0
    try:
        mape = list(koren.iterdir())
    except OSError:
        return 0
    zdaj = time.time()
    for mapa in mape:
        if not mapa.is_dir() or not mapa.name.startswith("session-"):
            continue
        if razen and os.path.normcase(str(mapa)) == os.path.normcase(razen):
            continue
        try:
            if starejse_od_s and zdaj - mapa.stat().st_mtime < starejse_od_s:
                continue
        except OSError:
            continue
        shutil.rmtree(mapa, ignore_errors=True)
        if not mapa.exists():
            pobrisanih += 1
    return pobrisanih


def predvajalnik_na_voljo() -> bool:
    """Ali se predvajalnik (Safeer DRM ali rezerva WebView2) sploh lahko odpre - brez ustvarjanja okna."""
    if sys.platform != "win32":
        return False
    koren_paketa = Path(__file__).resolve().parents[1]
    if (koren_paketa / "SafeerMediaWebView.exe").is_file() or (koren_paketa / "SafeerDRM" / "safeer-drm.exe").is_file():
        return True
    try:
        return safeer_drm_prenos.izvrsljiva() is not None
    except Exception:  # noqa: BLE001
        return False


def https_naslov(url: str) -> str:
    """Predvajalnik odpre samo https: http:// se prepise v https://, drugo ostane prazno."""
    url = str(url or "").strip()
    if url.lower().startswith("http://"):
        url = "https://" + url[7:]
    return url if url.lower().startswith("https://") else ""


class WebView2MediaWidget(QWidget):
    def __init__(self, on_home: Callable[[], None], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.on_home = on_home
        koren_paketa = Path(__file__).resolve().parents[1]
        # Safeer DRM (castLabs ECS, Widevine) je prvi predvajalnik, WebView2 rezerva. Oba govorita isti dogovor
        # (--parent/--url/--profile/--state/--command), zato uporabnik vidi en sam predvajalnik.
        self._koren_paketa = koren_paketa
        self.webview2_executable = koren_paketa / "SafeerMediaWebView.exe"
        self._drm_onemogocen = False
        self.executable = self._izberi_izvrsljivo()
        self._vdelano_okno = 0
        self._dogodki_odmik = 0
        self.process: Optional[subprocess.Popen] = None
        self.session_dir = ""
        self.command_path = ""
        self.state_path = ""
        self.variants: list[dict] = []
        self.variant_index = 0
        self.opened_at = 0.0
        self.media_detected = False
        self._last_rejection = ""
        self._failed_variants: list[str] = []
        # Stran, ki jo je uporabnik sam poslal iz Spleta (zapis, ki ga Qt nima): brez roka za video tok in brez
        # preklapljanja virov - uporabnik sam pritisne predvajaj, kadar stran tega ne naredi.
        self.page_mode = False
        self.storitev = False

        self.setStyleSheet("background:#070b12;color:#f4f7f5;")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.bar = QWidget(self)
        self.bar.setFixedHeight(48)
        self.bar.setStyleSheet("background:#0d151f;border-bottom:1px solid #203644;")
        row = QHBoxLayout(self.bar)
        row.setContentsMargins(12, 6, 12, 6)
        row.setSpacing(8)
        back = QPushButton("← Nazaj", self.bar)
        back.clicked.connect(self.close_and_home)
        reload_button = QPushButton("↻ Osveži", self.bar)
        reload_button.clicked.connect(lambda: self._command("reload"))
        fullscreen = QPushButton("⛶ Celozaslonsko", self.bar)
        fullscreen.clicked.connect(lambda: self.window().preklopi_celozaslonsko())
        home = QPushButton("Safeer OS Domov", self.bar)
        self.gumb_domov = home        # v oknu brskalnika ga ni (tam »Nazaj« vrne na zavihke)
        home.clicked.connect(self.close_and_home)
        for button in (back, reload_button, fullscreen, home):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                "QPushButton{padding:8px 14px;border:1px solid #315262;border-radius:10px;"
                "background:#14222d;color:#f4f7f5;font-weight:700}"
                "QPushButton:hover{border-color:#4de6ba;background:#18332f}"
            )
            row.addWidget(button)
        self.status_label = QLabel("Zasebno predvajanje v Safeer Media", self.bar)
        self.status_label.setStyleSheet("color:#9eb5ad;padding-left:8px;")
        row.addWidget(self.status_label, 1)
        outer.addWidget(self.bar)
        self.surface = QWidget(self)
        self.surface.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.surface.setStyleSheet("background:#000;")
        outer.addWidget(self.surface, 1)

        self.watchdog = QTimer(self)
        self.watchdog.setInterval(500)
        self.watchdog.timeout.connect(self._check_process)

    def set_fullscreen_ui(self, enabled: bool) -> None:
        """V celozaslonskem filmu skrije tudi Safeerjevo orodno vrstico."""
        self.bar.setVisible(not enabled)
        if not enabled and self.uporablja_drm:
            # Safeer OS je zapustil celozaslonski nacin (Esc, F11, gumb): tudi stran naj zapre svoj celozaslonski video.
            self._command("exitfullscreen")
        QTimer.singleShot(0, self._prilagodi_okno)
        QTimer.singleShot(300, self._prilagodi_okno)

    def _izberi_izvrsljivo(self) -> Path:
        """Safeer DRM, ce je na voljo (ob paketu za razvoj ali prenesen ob prvem zagonu), sicer WebView2."""
        if not self._drm_onemogocen:
            ob_paketu = self._koren_paketa / "SafeerDRM" / "safeer-drm.exe"
            if ob_paketu.is_file():
                return ob_paketu
            prenesen = safeer_drm_prenos.izvrsljiva()
            if prenesen is not None:
                safeer_drm_prenos.uskladi_logiko(prenesen, self._koren_paketa / "safeer_drm")
                return prenesen
        return self.webview2_executable

    def ima_drm(self) -> bool:
        """Ali bo naslednje predvajanje v Safeer DRM (tudi ce se je paket pravkar prenesel)."""
        return self._izberi_izvrsljivo() != self.webview2_executable

    @property
    def uporablja_drm(self) -> bool:
        return self.executable != self.webview2_executable

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._prilagodi_okno)

    def _vstavi_okno(self, rocaj: int) -> None:
        """Okno Safeer DRM vstavi v ploskev predvajalnika (isto kot WebView2 gostitelj naredi sam)."""
        if sys.platform != "win32" or not rocaj:
            return
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
        user32.SetParent.restype = wintypes.HWND
        gwl_style, ws_child, ws_popup, ws_caption, ws_thickframe = -16, 0x40000000, 0x80000000, 0x00C00000, 0x00040000
        slog = user32.GetWindowLongPtrW(rocaj, gwl_style)
        slog = (slog | ws_child) & ~ws_popup & ~ws_caption & ~ws_thickframe
        user32.SetWindowLongPtrW(rocaj, gwl_style, slog)
        user32.SetParent(rocaj, int(self.surface.winId()))
        self._vdelano_okno = rocaj
        self._prilagodi_okno()
        user32.ShowWindow(rocaj, 5)  # SW_SHOW

    def _prilagodi_okno(self) -> None:
        if sys.platform != "win32" or not self._vdelano_okno:
            return
        razmerje = self.surface.devicePixelRatioF() or 1.0
        sirina = max(1, round(self.surface.width() * razmerje))
        visina = max(1, round(self.surface.height() * razmerje))
        ctypes.windll.user32.MoveWindow(self._vdelano_okno, 0, 0, sirina, visina, True)

    def _beri_dogodke_drm(self) -> None:
        """Safeer DRM v dnevnik zapise rocaj svojega okna in celozaslonske zahteve strani."""
        if not self.uporablja_drm or not self.state_path:
            return
        try:
            with open(self.state_path, "r", encoding="utf-8") as datoteka:
                datoteka.seek(self._dogodki_odmik)
                novo = datoteka.read()
                self._dogodki_odmik = datoteka.tell()
        except OSError:
            return
        for vrstica in novo.splitlines():
            try:
                dogodek = json.loads(vrstica)
            except ValueError:
                continue
            vrsta = dogodek.get("type")
            if vrsta == "WINDOW_HANDLE" and not self._vdelano_okno:
                try:
                    self._vstavi_okno(int(str(dogodek.get("detail") or "0")))
                except ValueError:
                    pass
            elif vrsta in ("FULLSCREEN_ON", "FULLSCREEN_OFF"):
                okno = self.window()
                zeli = vrsta == "FULLSCREEN_ON"
                if hasattr(okno, "preklopi_celozaslonsko") and okno.isFullScreen() != zeli:
                    okno.preklopi_celozaslonsko()
                QTimer.singleShot(300, self._prilagodi_okno)

    @property
    def available(self) -> bool:
        return sys.platform == "win32" and self.executable.is_file()

    def open_url(self, url: str, stran: bool = False, storitev: bool = False) -> bool:
        url = https_naslov(url)
        if not self.available or not url:
            return False
        self.stop()
        self.page_mode = bool(stran or storitev)
        # Storitev z DRM (Netflix ...): stalen profil, da prijava ostane, in prosto premikanje po https.
        self.storitev = bool(storitev) and self.ima_drm()
        self.variants = [{"url": url, "vir": urllib.parse.urlsplit(url).hostname or "Spletni vir"}]
        self.variant_index = 0
        return self._open_variant()

    def open_item(self, item: dict) -> bool:
        if not self.available:
            return False
        rows = list(item.get("razlicice") or [])
        selected = str(item.get("url") or "")
        if selected:
            selected_row = next((row for row in rows if str(row.get("url") or "") == selected), None)
            rows = ([selected_row] if selected_row else [{"url": selected, "vir": item.get("vir", "")}]) + [
                row for row in rows if str(row.get("url") or "") != selected
            ]
        seen, variants = set(), []
        for row in rows:
            url = str(row.get("url") or "")
            if not url.startswith("https://") or url in seen:
                continue
            seen.add(url)
            variants.append(dict(row, url=url))
        if not variants:
            return False
        self.stop()
        self.page_mode = False
        self.variants = variants
        self.variant_index = 0
        self._failed_variants = []
        return self._open_variant()

    def _stop_process(self) -> None:
        self.watchdog.stop()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
        if self.session_dir:
            stara = self.session_dir
            shutil.rmtree(stara, ignore_errors=True)
            if os.path.exists(stara):
                # WebView2 se zapira v ozadju: poskusimo znova, ko sprosti datoteke.
                for zamik in (1500, 5000, 15000):
                    QTimer.singleShot(zamik, lambda m=stara: shutil.rmtree(m, ignore_errors=True))
        self.session_dir = ""
        self.command_path = ""
        self.state_path = ""
        self._vdelano_okno = 0
        self._dogodki_odmik = 0

    def _open_variant(self) -> bool:
        if self.variant_index >= len(self.variants):
            return False
        self._stop_process()
        self.executable = self._izberi_izvrsljivo()   # Safeer DRM se je morda prenesel med tem
        if not self.available:
            return False
        variant = self.variants[self.variant_index]
        url = str(variant.get("url") or "")
        if not url.startswith("https://"):
            return False
        root = _koren_sej()
        root.mkdir(parents=True, exist_ok=True)
        # Ostanki prejsnjih zagonov (npr. po sesutju ali prisilnem zaprtju) - samo starejsi od ure.
        pocisti_seje(root, starejse_od_s=3600)
        self.session_dir = tempfile.mkdtemp(prefix="session-", dir=str(root))
        profile = str(_koren_sej().parent / "SafeerDRMProfil") if self.storitev else str(Path(self.session_dir) / "profile")
        self.command_path = str(Path(self.session_dir) / "command.txt")
        self.state_path = str(Path(self.session_dir) / "events.jsonl")
        args = [
            str(self.executable),
            f"--parent={int(self.surface.winId())}",
            f"--url={url}",
            f"--profile={profile}",
            f"--state={self.state_path}",
            f"--command={self.command_path}",
        ]
        if self.storitev:
            args.append("--storitev=1")
        if self.uporablja_drm:
            args.append(f"--lastnik={os.getpid()}")   # Safeer DRM se konca tudi, ce se Safeer OS sesuje
        self.process = subprocess.Popen(args, close_fds=True)
        self.opened_at = time.monotonic()
        self.media_detected = False
        provider = str(variant.get("vir") or urllib.parse.urlsplit(url).hostname or "Spletni vir")
        suffix = f" · vir {self.variant_index + 1}/{len(self.variants)}" if len(self.variants) > 1 else ""
        self.status_label.setText(f"Nalagam {provider}{suffix} …")
        self.watchdog.start()
        return True

    def _command(self, name: str) -> None:
        if self.process is None or self.process.poll() is not None or not self.command_path:
            return
        try:
            Path(self.command_path).write_text(name, encoding="utf-8")
        except OSError:
            pass

    def _check_process(self) -> None:
        if self.process is None:
            self.watchdog.stop()
            return
        self._beri_dogodke_drm()
        if self.state_path and not self.media_detected:
            try:
                events = Path(self.state_path).read_text(encoding="utf-8")
                self.media_detected = '"MEDIA_RESPONSE"' in events or '"PLAYBACK_STARTED"' in events
                if not self.media_detected and time.monotonic() - self.opened_at >= 8:
                    self._last_rejection = source_rejection(
                        events, str(self.variants[self.variant_index].get("url") or "")
                    )
            except OSError:
                pass
            if self.media_detected and self.storitev:
                # Uporabnik brska po storitvi (lahko tudi drugam): brez imena prvega gostitelja.
                self.status_label.setText("Safeer predvajalnik")
            elif self.media_detected:
                provider = str(self.variants[self.variant_index].get("vir") or "Spletni vir")
                self.status_label.setText(f"Predvaja se prek {provider}")
        exited = self.process.poll() is not None
        if exited and self.uporablja_drm and not self._vdelano_okno and self.webview2_executable.is_file():
            # Safeer DRM se ni zagnal (okna ni bilo): ista stran takoj v rezervnem predvajalniku WebView2.
            print("[SafeerMedia] Safeer DRM se ni zagnal - rezerva WebView2", flush=True)
            self._drm_onemogocen = True
            self.executable = self.webview2_executable
            self.storitev = False
            self._open_variant()
            return
        if self.page_mode:
            if exited:
                self.watchdog.stop()
                self.status_label.setText("Predvajalnik se je zaprl")
            elif not self.storitev and not self.media_detected and time.monotonic() - self.opened_at >= 6:
                self.status_label.setText("Safeer predvajalnik · če se film ne začne sam, pritisni predvajaj")
            return
        timed_out = not self.media_detected and time.monotonic() - self.opened_at >= 18.0
        if self._last_rejection and not self.media_detected:
            self._next_or_report_failure(self._last_rejection)
            return
        if (exited or timed_out) and self.variant_index + 1 < len(self.variants):
            self.variant_index += 1
            self.status_label.setText("Prvi vir se ni odzval · preklapljam …")
            self._open_variant()
        elif exited:
            self.watchdog.stop()
            self._next_or_report_failure("povezava se je zaprla")
        elif timed_out:
            self.watchdog.stop()
            self._next_or_report_failure("v 18 sekundah ni bilo video toka")

    def _next_or_report_failure(self, reason: str) -> None:
        current = self.variants[self.variant_index] if self.variant_index < len(self.variants) else {}
        provider = str(current.get("vir") or urllib.parse.urlsplit(str(current.get("url") or "")).hostname or "vir")
        self._failed_variants.append(f"{provider}: {reason}")
        if self.variant_index + 1 < len(self.variants):
            self.variant_index += 1
            self._last_rejection = ""
            self.status_label.setText(f"Vir zavrnil predvajanje ({reason}) · preklapljam …")
            self._open_variant()
            return
        self._stop_process()
        summary = " · ".join(self._failed_variants[-5:])
        self.status_label.setText(f"Tega toka ni mogoče predvajati · {summary or reason}")

    def stop(self) -> None:
        self._stop_process()
        self.variants = []
        self.variant_index = 0
        self.opened_at = 0.0
        self.media_detected = False
        self.page_mode = False
        self.storitev = False

    def close_and_home(self) -> None:
        self.stop()
        self.on_home()

    def closeEvent(self, event) -> None:
        self.stop()
        super().closeEvent(event)
