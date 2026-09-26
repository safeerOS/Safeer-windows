"""Pravi WebView2 predvajalnik, vdelan v okno Safeer OS na Windows."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class WebView2MediaWidget(QWidget):
    def __init__(self, on_home: Callable[[], None], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.on_home = on_home
        self.executable = Path(__file__).resolve().parents[1] / "SafeerMediaWebView.exe"
        self.process: Optional[subprocess.Popen] = None
        self.session_dir = ""
        self.command_path = ""
        self.state_path = ""
        self.variants: list[dict] = []
        self.variant_index = 0
        self.opened_at = 0.0
        self.media_detected = False

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
        home.clicked.connect(self.close_and_home)
        for button in (back, reload_button, fullscreen, home):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                "QPushButton{padding:8px 14px;border:1px solid #315262;border-radius:10px;"
                "background:#14222d;color:#f4f7f5;font-weight:700}"
                "QPushButton:hover{border-color:#4de6ba;background:#18332f}"
            )
            row.addWidget(button)
        self.status_label = QLabel("Zasebno predvajanje v Safeer Media · WebView2", self.bar)
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

    @property
    def available(self) -> bool:
        return sys.platform == "win32" and self.executable.is_file()

    def open_url(self, url: str) -> bool:
        if not self.available or not url.startswith("https://"):
            return False
        self.variants = [{"url": url, "vir": "Spletni vir"}]
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
        self.variants = variants
        self.variant_index = 0
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
            shutil.rmtree(self.session_dir, ignore_errors=True)
        self.session_dir = ""
        self.command_path = ""
        self.state_path = ""

    def _open_variant(self) -> bool:
        if not self.available or self.variant_index >= len(self.variants):
            return False
        self._stop_process()
        variant = self.variants[self.variant_index]
        url = str(variant.get("url") or "")
        if not url.startswith("https://"):
            return False
        root = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "SafeerOS/WebView2Sessions"
        root.mkdir(parents=True, exist_ok=True)
        self.session_dir = tempfile.mkdtemp(prefix="session-", dir=str(root))
        profile = str(Path(self.session_dir) / "profile")
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
        if self.state_path and not self.media_detected:
            try:
                events = Path(self.state_path).read_text(encoding="utf-8")
                self.media_detected = '"MEDIA_RESPONSE"' in events or '"PLAYBACK_STARTED"' in events
            except OSError:
                pass
            if self.media_detected:
                provider = str(self.variants[self.variant_index].get("vir") or "Spletni vir")
                self.status_label.setText(f"Predvaja se prek {provider}")
        exited = self.process.poll() is not None
        timed_out = not self.media_detected and time.monotonic() - self.opened_at >= 18.0
        if (exited or timed_out) and self.variant_index + 1 < len(self.variants):
            self.variant_index += 1
            self.status_label.setText("Prvi vir se ni odzval · preklapljam …")
            self._open_variant()
        elif exited:
            self.watchdog.stop()
            self.status_label.setText("Predvajalnik se je zaprl")
        elif timed_out:
            self.watchdog.stop()
            self.status_label.setText("Predvajalnik je odprt · če ni slike, osveži ali se vrni")

    def stop(self) -> None:
        self._stop_process()
        self.variants = []
        self.variant_index = 0
        self.opened_at = 0.0
        self.media_detected = False

    def close_and_home(self) -> None:
        self.stop()
        self.on_home()

    def closeEvent(self, event) -> None:
        self.stop()
        super().closeEvent(event)
