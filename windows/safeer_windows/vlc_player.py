"""Vgrajeni LibVLC predvajalnik za Safeer Media.

LibVLC riše neposredno v Qt gradnik znotraj glavnega okna Safeer OS. Zunanji VLC
se ne odpre. Modul je opcijski: kadar LibVLC ni nameščen, spletni vmesnik uporabi
vgrajeni HTML5 predvajalnik za formate, ki jih podpira Qt WebEngine.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QSlider, QVBoxLayout, QWidget)

_DLL_HANDLES = []


def _load_vlc():
    if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
        candidates = [
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "VideoLAN", "VLC"),
            os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "VideoLAN", "VLC"),
        ]
        for path in candidates:
            if os.path.isfile(os.path.join(path, "libvlc.dll")):
                _DLL_HANDLES.append(os.add_dll_directory(path))
                os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")
                break
    try:
        import vlc  # type: ignore
        return vlc
    except (ImportError, OSError):
        return None


VLC = _load_vlc()


class VlcPlayerWidget(QWidget):
    nazaj = Signal()
    ozadje = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.instance = None
        self.player = None
        self.current_item: dict = {}
        self.seeking = False
        self._build_ui()
        self._init_vlc()
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._update_state)

    @property
    def available(self) -> bool:
        return self.player is not None

    def _build_ui(self) -> None:
        self.setObjectName("safeerMediaPlayer")
        self.setStyleSheet("""
            QWidget#safeerMediaPlayer { background: #090d15; color: #f0f4f3; }
            QLabel#brand { color: #54d6a5; font-weight: 700; font-size: 15px; }
            QLabel#title { font-size: 24px; font-weight: 650; }
            QLabel#meta { color: #b0bdc4; font-size: 13px; }
            QLabel#audioVisual { background: qradialgradient(cx:.5, cy:.45, radius:.7,
                stop:0 #203f3a, stop:.55 #111d24, stop:1 #090d15); color: #54d6a5;
                border: 1px solid #263945; border-radius: 14px; font-size: 120px; }
            QPushButton, QComboBox { background: #151e2a; border: 1px solid #34414c;
                border-radius: 10px; padding: 9px 14px; color: #f0f4f3; }
            QPushButton:hover { border-color: #54d6a5; }
            QSlider::groove:horizontal { height: 5px; background: #29333d; border-radius: 2px; }
            QSlider::handle:horizontal { width: 16px; margin: -6px 0; background: #54d6a5; border-radius: 8px; }
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 22)
        root.setSpacing(14)

        header = QHBoxLayout()
        labels = QVBoxLayout()
        brand = QLabel("SAFEER OS · MEDIA")
        brand.setObjectName("brand")
        self.title = QLabel("Safeer Media")
        self.title.setObjectName("title")
        self.meta = QLabel("")
        self.meta.setObjectName("meta")
        labels.addWidget(brand)
        labels.addWidget(self.title)
        labels.addWidget(self.meta)
        header.addLayout(labels, 1)
        back = QPushButton("←  Nazaj v Safeer OS")
        back.clicked.connect(self.close_player)
        fullscreen = QPushButton("⛶  Celozaslonsko")
        fullscreen.clicked.connect(lambda: self.window().preklopi_celozaslonsko())
        header.addWidget(fullscreen)
        header.addWidget(back)
        root.addLayout(header)
        self._fullscreen_header_widgets = [brand, self.title, self.meta, fullscreen, back]

        self.video = QFrame()
        self.video.setStyleSheet("background:#000;border-radius:14px;")
        self.video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.video.setMinimumSize(640, 360)
        root.addWidget(self.video, 1)

        self.audio_visual = QLabel("♫")
        self.audio_visual.setObjectName("audioVisual")
        self.audio_visual.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.audio_visual.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.audio_visual.setMinimumSize(640, 360)
        self.audio_visual.hide()
        root.addWidget(self.audio_visual, 1)

        controls = QHBoxLayout()
        self.play_button = QPushButton("▶ / ❚❚")
        self.play_button.clicked.connect(self.toggle_play)
        stop = QPushButton("■")
        stop.clicked.connect(self.stop)
        self.position = QSlider(Qt.Orientation.Horizontal)
        self.position.setRange(0, 1000)
        self.position.sliderPressed.connect(lambda: setattr(self, "seeking", True))
        self.position.sliderReleased.connect(self._seek)
        self.time_label = QLabel("00:00 / 00:00")
        volume_label = QLabel("🔊")
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(80)
        self.volume.setMaximumWidth(130)
        self.volume.valueChanged.connect(self._set_volume)
        self.variants = QComboBox()
        self.variants.currentIndexChanged.connect(self._change_variant)
        self.subtitles = QComboBox()
        self.subtitles.addItem("CC  Podnapisi izklopljeni", -1)
        self.subtitles.currentIndexChanged.connect(self._change_subtitle)
        self.background = QPushButton("♫  Ozadje")
        self.background.setToolTip("Nadaljuj predvajanje v ozadju (Ctrl+Shift+M odpre upravljanje)")
        self.background.clicked.connect(self.ozadje.emit)
        self.background.setVisible(False)
        controls.addWidget(self.play_button)
        controls.addWidget(stop)
        controls.addWidget(self.position, 1)
        controls.addWidget(self.time_label)
        controls.addWidget(volume_label)
        controls.addWidget(self.volume)
        controls.addWidget(self.variants)
        controls.addWidget(self.subtitles)
        controls.addWidget(self.background)
        root.addLayout(controls)
        self._fullscreen_control_widgets = [
            self.play_button, stop, self.position, self.time_label, volume_label,
            self.volume, self.variants, self.subtitles, self.background,
        ]
        self._player_layout = root

    def set_fullscreen_ui(self, enabled: bool) -> None:
        for widget in self._fullscreen_header_widgets + self._fullscreen_control_widgets:
            widget.setVisible(not enabled)
        self._player_layout.setContentsMargins(0 if enabled else 24, 0 if enabled else 20,
                                               0 if enabled else 24, 0 if enabled else 22)
        self.video.setStyleSheet("background:#000;border-radius:0;" if enabled else "background:#000;border-radius:14px;")

    def _init_vlc(self) -> None:
        if VLC is None:
            return
        try:
            self.instance = VLC.Instance("--quiet", "--no-video-title-show", "--network-caching=1500")
            self.player = self.instance.media_player_new()
            self.player.audio_set_volume(self.volume.value())
        except Exception:
            self.instance = None
            self.player = None

    def _attach_video(self) -> None:
        if not self.player:
            return
        handle = int(self.video.winId())
        if sys.platform == "win32":
            self.player.set_hwnd(handle)
        elif sys.platform == "darwin":
            self.player.set_nsobject(handle)
        else:
            self.player.set_xwindow(handle)

    def play_item(self, item: dict, variant_index: int = 0) -> bool:
        if not self.player or not self.instance:
            return False
        variants = item.get("razlicice") or [{"url": item.get("url", ""), "vir": item.get("vir", ""),
                                               "kakovost": item.get("kakovost", "")}]
        if not variants:
            return False
        variant_index = min(max(0, variant_index), len(variants) - 1)
        self.current_item = dict(item)
        self.title.setText(str(item.get("naslov") or "Safeer Media"))
        self.meta.setText(" · ".join(filter(None, (str(item.get("izvajalec") or ""),
                                                    str(item.get("leto") or ""),
                                                    str(variants[variant_index].get("vir") or "")))))
        self.variants.blockSignals(True)
        self.variants.clear()
        for variant in variants:
            self.variants.addItem(" · ".join(filter(None, (str(variant.get("kakovost") or "Samodejno"),
                                                             str(variant.get("vir") or "Vir")))))
        self.variants.setCurrentIndex(variant_index)
        self.variants.setVisible(len(variants) > 1)
        self.variants.blockSignals(False)
        is_audio = item.get("vrsta") in ("glasba", "radio")
        self.video.setVisible(not is_audio)
        self.audio_visual.setVisible(is_audio)
        self.background.setVisible(is_audio)
        variant = variants[variant_index]
        media = self.instance.media_new(str(variant.get("url") or ""))
        headers = variant.get("glave") if isinstance(variant.get("glave"), dict) else {}
        lowered = {str(key).casefold(): str(value) for key, value in headers.items()}
        referer = str(variant.get("referer") or lowered.get("referer")
                      or lowered.get("referrer") or item.get("referer") or "").strip()
        user_agent = str(lowered.get("user-agent") or lowered.get("user_agent") or "").strip()
        if referer and "\n" not in referer and "\r" not in referer:
            media.add_option(f":http-referrer={referer}")
        if user_agent and "\n" not in user_agent and "\r" not in user_agent:
            media.add_option(f":http-user-agent={user_agent}")
        self.player.set_media(media)
        # Podnapisi so vedno privzeto izklopljeni. Ko uporabnik izbere jezik,
        # LibVLC uporabi izvorne časovne oznake, zato ostanejo usklajeni s filmom.
        self.player.video_set_spu(-1)
        self.subtitles.blockSignals(True)
        self.subtitles.clear()
        self.subtitles.addItem("CC  Podnapisi izklopljeni", -1)
        self.subtitles.setCurrentIndex(0)
        self.subtitles.blockSignals(False)
        if not is_audio:
            self._attach_video()
        result = self.player.play()
        QTimer.singleShot(1800, self._load_subtitles)
        self.timer.start()
        return result != -1

    def _change_variant(self, index: int) -> None:
        if index >= 0 and self.current_item:
            self.play_item(self.current_item, index)

    def _load_subtitles(self) -> None:
        if not self.player:
            return
        try:
            tracks = self.player.video_get_spu_description() or []
        except Exception:
            tracks = []
        self.subtitles.blockSignals(True)
        existing = {self.subtitles.itemData(i) for i in range(self.subtitles.count())}
        for track in tracks:
            track_id = getattr(track, "id", track[0] if isinstance(track, tuple) else -1)
            name = getattr(track, "name", track[1] if isinstance(track, tuple) and len(track) > 1 else "Podnapisi")
            if track_id is None or int(track_id) < 0 or int(track_id) in existing:
                continue
            if isinstance(name, bytes):
                name = name.decode("utf-8", "replace")
            self.subtitles.addItem(f"CC  {name}", int(track_id))
            existing.add(int(track_id))
        self.subtitles.blockSignals(False)

    def _change_subtitle(self, index: int) -> None:
        if self.player and index >= 0:
            track_id = self.subtitles.itemData(index)
            self.player.video_set_spu(int(track_id) if track_id is not None else -1)

    def toggle_play(self) -> None:
        if not self.player:
            return
        if self.player.is_playing():
            self.player.pause()
        else:
            self.player.play()

    def stop(self) -> None:
        if self.player:
            self.player.stop()
        self.timer.stop()

    def _set_volume(self, value: int) -> None:
        if self.player:
            self.player.audio_set_volume(value)

    def close_player(self) -> None:
        self.stop()
        self.nazaj.emit()

    def _seek(self) -> None:
        if self.player:
            self.player.set_position(self.position.value() / 1000.0)
        self.seeking = False

    @staticmethod
    def _format_time(milliseconds: int) -> str:
        seconds = max(0, milliseconds // 1000)
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _update_state(self) -> None:
        if not self.player:
            return
        if not self.seeking:
            self.position.setValue(max(0, int(self.player.get_position() * 1000)))
        current, length = self.player.get_time(), self.player.get_length()
        self.time_label.setText(f"{self._format_time(current)} / {self._format_time(length)}")

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space:
            self.toggle_play()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right) and self.player:
            offset = -10_000 if event.key() == Qt.Key.Key_Left else 10_000
            self.player.set_time(max(0, self.player.get_time() + offset))
            event.accept()
            return
        super().keyPressEvent(event)
