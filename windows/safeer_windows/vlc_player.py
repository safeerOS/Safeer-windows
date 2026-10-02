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

#: Besedila predvajalnika za podnapise in DVD v jezikih vmesnika Safeer OS.
_BESEDILA = {
    "sl": {"izklop": "Podnapisi izklopljeni", "vgrajeni": "Vgrajeni", "v_videu": "Podnapisi v videu",
           "dvd": "Diska ni mogoče prebrati. Zaščitenih diskov (CSS) Safeer ne odklepa.",
           "napaka": "Predvajanje se je ustavilo zaradi napake."},
    "en": {"izklop": "Subtitles off", "vgrajeni": "Built-in", "v_videu": "Subtitles in the video",
           "dvd": "The disc can't be read. Safeer doesn't unlock protected (CSS) discs.",
           "napaka": "Playback stopped because of an error."},
    "de": {"izklop": "Untertitel aus", "vgrajeni": "Eingebettet", "v_videu": "Untertitel im Video",
           "dvd": "Die Disc kann nicht gelesen werden. Geschützte Discs (CSS) entsperrt Safeer nicht.",
           "napaka": "Die Wiedergabe wurde wegen eines Fehlers beendet."},
    "es": {"izklop": "Subtítulos desactivados", "vgrajeni": "Integrados", "v_videu": "Subtítulos del vídeo",
           "dvd": "No se puede leer el disco. Safeer no desbloquea discos protegidos (CSS).",
           "napaka": "La reproducción se detuvo por un error."},
    "fr": {"izklop": "Sous-titres désactivés", "vgrajeni": "Intégrés", "v_videu": "Sous-titres de la vidéo",
           "dvd": "Impossible de lire le disque. Safeer ne déverrouille pas les disques protégés (CSS).",
           "napaka": "La lecture s'est arrêtée à cause d'une erreur."},
    "it": {"izklop": "Sottotitoli disattivati", "vgrajeni": "Integrati", "v_videu": "Sottotitoli nel video",
           "dvd": "Impossibile leggere il disco. Safeer non sblocca i dischi protetti (CSS).",
           "napaka": "La riproduzione si è interrotta a causa di un errore."},
}


def _dovoljen_podnapis(uri: str) -> bool:
    """Samo lokalne datoteke in naslovi http(s) (tudi 127.0.0.1 za tok z naprave ali iz torrenta)."""
    from urllib.parse import urlsplit
    try:
        return urlsplit(str(uri or "")).scheme in ("file", "http", "https")
    except ValueError:
        return False


class VlcPlayerWidget(QWidget):
    nazaj = Signal()
    ozadje = Signal()
    #: Napaka LibVLC (klic iz niti VLC; signal jo prenese v nit vmesnika).
    _vlc_napaka = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.instance = None
        self.player = None
        self.current_item: dict = {}
        self.seeking = False
        #: Jezik vmesnika Safeer OS (os_app ga nastavi); za besedila podnapisov in napak.
        self.jezik_vmesnika = lambda: "sl"
        # Podnapisi: izbira velja za vse videe (core/podnapisi.py), jezik sistema za samodejno izbiro.
        try:
            from core import podnapisi as _pn
            from . import podnapisi_izbira as _pi
            self._nastavitve_podnapisov = _pn.nalozi_nastavitve()
            self._shrani_podnapise = _pn.shrani_nastavitve
            self._jezik_sistema = _pi.jezik_sistema()
        except Exception:  # noqa: BLE001
            self._nastavitve_podnapisov = {"izklop": None, "jezik": ""}
            self._shrani_podnapise = lambda _n: None
            self._jezik_sistema = ""
        self._zunanji: list = []          # datoteke podnapisov trenutnega videa
        self._zunanji_id: dict = {}       # indeks datoteke -> id toka SPU v LibVLC
        self._cakajoci_zunanji = None     # (indeks, znani id-ji, poskusi, izberi)
        self._samodejno_vgrajeni = False
        self._rod = 0                     # stevec videov: zakasnjeno dodajanje ne sme zadeti naslednjega videa
        self._vlc_napaka.connect(self._pokazi_napako)
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
            QLabel { color: #b0bdc4; }
            QLabel#brand { color: #54d6a5; font-weight: 700; font-size: 15px; }
            QLabel#title { color: #f2f6f8; font-size: 24px; font-weight: 650; }
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
        self.title = QLabel("Medijski center")
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
        self.subtitles.addItem("CC  Podnapisi izklopljeni", "izklop")
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
            try:
                self._ob_napaki = lambda _dogodek: self._vlc_napaka.emit()
                self.player.event_manager().event_attach(VLC.EventType.MediaPlayerEncounteredError, self._ob_napaki)
            except Exception:  # noqa: BLE001 - brez sporocila o napaki predvajalnik se vedno deluje
                pass
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
        self.title.setText(str(item.get("naslov") or "Medijski center"))
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
        # Podnapisi (kot na Linuxu): datoteke ob videu dodamo sami, zato jih VLC ne isce se enkrat.
        # Vgrajene podnapise VLC samodejno izbere le v zelenem jeziku; _load_subtitles to preveri.
        from . import podnapisi_izbira as _pi
        self._zunanji = [p for p in (item.get("podnapisi") or []) if isinstance(p, dict)
                         and _dovoljen_podnapis(str(p.get("uri") or ""))][:24] if not is_audio else []
        self._zunanji_id = {}
        self._cakajoci_zunanji = None
        self._rod += 1
        jeziki = _pi.zeleni_jeziki(self._nastavitve_podnapisov, self._jezik_sistema)
        media.add_option(":no-sub-autodetect-file")
        if jeziki and self._nastavitve_podnapisov.get("izklop") is not True:
            media.add_option(":sub-language=" + ",".join(jeziki))
        zunanji = _pi.samodejna_zunanja(self._zunanji, self._nastavitve_podnapisov, self._jezik_sistema)
        self._samodejno_vgrajeni = zunanji < 0
        self.player.set_media(media)
        self.player.video_set_spu(-1)
        self._napolni_podnapise()
        if not is_audio:
            self._attach_video()
        result = self.player.play()
        if zunanji >= 0:
            self._dodaj_zunanji(zunanji, True)
        QTimer.singleShot(1800, self._load_subtitles)
        self.timer.start()
        return result != -1

    # ------------------------------------------------------------------ podnapisi
    def _t(self, kljuc: str) -> str:
        try:
            jezik = str(self.jezik_vmesnika() or "sl")
        except Exception:  # noqa: BLE001
            jezik = "sl"
        return _BESEDILA.get(jezik, _BESEDILA["en"]).get(kljuc, _BESEDILA["en"][kljuc])

    def _spu_tokovi(self) -> list:
        """[(id, ime)] podnapisov, ki jih LibVLC trenutno pozna (brez »Onemogoci« z id -1)."""
        if not self.player:
            return []
        try:
            tokovi = self.player.video_get_spu_description() or []
        except Exception:  # noqa: BLE001
            return []
        izid = []
        for tok in tokovi:
            ident = getattr(tok, "id", tok[0] if isinstance(tok, tuple) else -1)
            ime = getattr(tok, "name", tok[1] if isinstance(tok, tuple) and len(tok) > 1 else "")
            if isinstance(ime, bytes):
                ime = ime.decode("utf-8", "replace")
            if ident is not None and int(ident) >= 0:
                izid.append((int(ident), str(ime or "")))
        return izid

    def _jeziki_tokov(self) -> dict:
        """id toka SPU -> ISO 639-1 (iz podatkov medija, sicer iz imena toka)."""
        from . import podnapisi_izbira as _pi
        izid = {}
        try:
            media = self.player.get_media() if self.player else None
            for sled in (media.tracks_get() if media is not None else None) or []:
                if getattr(sled, "type", None) == VLC.TrackType.text:
                    jezik = getattr(sled, "language", b"") or b""
                    if isinstance(jezik, bytes):
                        jezik = jezik.decode("utf-8", "replace")
                    koda = _pi.koda_jezika(jezik)
                    if koda:
                        izid[int(sled.id)] = koda
        except Exception:  # noqa: BLE001
            pass
        for ident, ime in self._spu_tokovi():
            if ident not in izid:
                koda = _pi.koda_jezika(ime)
                if koda:
                    izid[ident] = koda
        return izid

    def _vgrajeni(self) -> list:
        zunanji = set(self._zunanji_id.values())
        return [(i, ime) for i, ime in self._spu_tokovi() if i not in zunanji]

    def _ime_zunanjega(self, p: dict) -> str:
        from core import podnapisi as _pn
        jezik = str(p.get("jezik") or "")
        ime_jezika = _pn.ime_jezika(jezik, str(self.jezik_vmesnika() or "sl")) if jezik else ""
        return " · ".join(x for x in (ime_jezika, str(p.get("oznaka") or "")) if x) or str(p.get("ime") or "")

    def _izbran_kljuc(self) -> str:
        try:
            trenutni = int(self.player.video_get_spu()) if self.player else -1
        except Exception:  # noqa: BLE001
            trenutni = -1
        if trenutni < 0:
            return "izklop"
        k = next((k for k, i in self._zunanji_id.items() if i == trenutni), None)
        return "z:%d" % k if k is not None else "v:%d" % trenutni

    def _kljuci_podnapisov(self) -> list:
        return (["izklop"] + ["z:%d" % k for k in range(len(self._zunanji))]
                + ["v:%d" % i for i, _ime in self._vgrajeni()])

    def _napolni_podnapise(self) -> None:
        """Izbira CC: izklop, datoteke ob videu (z imenom jezika) in vgrajeni tokovi."""
        from core import podnapisi as _pn  # noqa: F401 - ime jezika v _ime_zunanjega
        jeziki = self._jeziki_tokov() if self.player else {}
        self.subtitles.blockSignals(True)
        self.subtitles.clear()
        self.subtitles.addItem("CC  " + self._t("izklop"), "izklop")
        for k, p in enumerate(self._zunanji):
            self.subtitles.addItem("CC  " + self._ime_zunanjega(p), "z:%d" % k)
        for ident, ime in self._vgrajeni():
            koda = jeziki.get(ident, "")
            napis = ime or (_pn.ime_jezika(koda, str(self.jezik_vmesnika() or "sl")) if koda else self._t("v_videu"))
            self.subtitles.addItem("CC  " + napis + " · " + self._t("vgrajeni"), "v:%d" % ident)
        indeks = self.subtitles.findData(self._izbran_kljuc())
        self.subtitles.setCurrentIndex(max(0, indeks))
        self.subtitles.blockSignals(False)

    def _dodaj_zunanji(self, k: int, izberi: bool, poskus: int = 0, rod: int = -1) -> None:
        """Datoteko podnapisov doda kot »slave« LibVLC, ko je video odprt (takrat so vgrajeni tokovi znani)."""
        rod = self._rod if rod < 0 else rod
        if not self.player or rod != self._rod or not 0 <= k < len(self._zunanji):
            return
        stanje = self.player.get_state()
        odprt = stanje in (VLC.State.Playing, VLC.State.Paused)
        # Po eno datoteko naenkrat: nov tok SPU tako zanesljivo pripada tej datoteki.
        if (not odprt or self._cakajoci_zunanji is not None) and poskus < 40:
            QTimer.singleShot(250, lambda: self._dodaj_zunanji(k, izberi, poskus + 1, rod))
            return
        znani = {i for i, _ime in self._spu_tokovi()}
        try:
            self.player.add_slave(VLC.MediaSlaveType.subtitle, str(self._zunanji[k]["uri"]), bool(izberi))
        except Exception as e:  # noqa: BLE001
            print(f"[SafeerMedia] podnapisi niso dodani: {e}", flush=True)
            return
        self._cakajoci_zunanji = (k, znani, 0, bool(izberi))
        QTimer.singleShot(300, self._preveri_zunanji)

    def _preveri_zunanji(self) -> None:
        """Nov tok SPU po dodajanju datoteke je ta datoteka (dodajamo jih po eno)."""
        if self._cakajoci_zunanji is None:
            return
        k, znani, poskusi, izberi = self._cakajoci_zunanji
        nov = sorted({i for i, _ime in self._spu_tokovi()} - znani - set(self._zunanji_id.values()))
        if nov:
            self._zunanji_id[k] = nov[0]
            self._cakajoci_zunanji = None
            if izberi:
                self.player.video_set_spu(nov[0])
            self._napolni_podnapise()
            return
        if poskusi >= 30:
            self._cakajoci_zunanji = None   # datoteke ni bilo mogoce prebrati (npr. se ni prenesena)
            return
        self._cakajoci_zunanji = (k, znani, poskusi + 1, izberi)
        QTimer.singleShot(300, self._preveri_zunanji)

    def izberi_podnapise(self, kljuc: str) -> bool:
        """Izbira uporabnika (izklop, datoteka, vgrajeni tok) - velja tudi za naslednje videe."""
        from . import podnapisi_izbira as _pi
        if not self.player:
            return False
        kljuc = str(kljuc or "")
        jezik = ""
        if kljuc == "izklop":
            self.player.video_set_spu(-1)
        elif kljuc.startswith("z:"):
            k = int(kljuc[2:])
            if not 0 <= k < len(self._zunanji):
                return False
            if k in self._zunanji_id:
                self.player.video_set_spu(self._zunanji_id[k])
            elif self._cakajoci_zunanji is None or self._cakajoci_zunanji[0] != k:
                self._dodaj_zunanji(k, True)
            jezik = str(self._zunanji[k].get("jezik") or "")
        elif kljuc.startswith("v:"):
            ident = int(kljuc[2:])
            self.player.video_set_spu(ident)
            jezik = self._jeziki_tokov().get(ident, "")
        else:
            return False
        self._samodejno_vgrajeni = False
        self._nastavitve_podnapisov = _pi.po_izbiri(self._nastavitve_podnapisov, kljuc, jezik)
        try:
            self._shrani_podnapise(dict(self._nastavitve_podnapisov))
        except Exception:  # noqa: BLE001
            pass
        QTimer.singleShot(200, self._napolni_podnapise)
        return True

    def naslednji_podnapisi(self) -> bool:
        """Tipka V: izklop -> prvi -> drugi ... -> izklop (kot v VLC)."""
        from . import podnapisi_izbira as _pi
        kljuci = self._kljuci_podnapisov()
        if len(kljuci) < 2:
            return False
        return self.izberi_podnapise(_pi.naslednji_kljuc(kljuci, self._izbran_kljuc()))

    def _pokazi_napako(self) -> None:
        """Napaka LibVLC: pri DVD razumljivo sporocilo o zasciti, sicer splosno."""
        dvd = str(self.current_item.get("url") or "").startswith("dvd:")
        self.meta.setText(self._t("dvd" if dvd else "napaka"))

    def _change_variant(self, index: int) -> None:
        if index >= 0 and self.current_item:
            self.play_item(self.current_item, index)

    def _load_subtitles(self) -> None:
        """Ko so tokovi znani: vgrajene podnapise pokazemo le v zelenem jeziku ali ce jih je uporabnik vklopil."""
        if not self.player:
            return
        if self._samodejno_vgrajeni:
            from . import podnapisi_izbira as _pi
            self._samodejno_vgrajeni = False
            jeziki = self._jeziki_tokov()
            ident = _pi.samodejni_vgrajeni([(i, jeziki.get(i, "")) for i, _ime in self._vgrajeni()],
                                           self._nastavitve_podnapisov, self._jezik_sistema)
            self.player.video_set_spu(ident if ident is not None else -1)
        self._napolni_podnapise()

    def _change_subtitle(self, index: int) -> None:
        if self.player and index >= 0:
            kljuc = self.subtitles.itemData(index)
            if isinstance(kljuc, str):
                self.izberi_podnapise(kljuc)

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
        if event.key() == Qt.Key.Key_V and not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.naslednji_podnapisi()
            event.accept()
            return
        super().keyPressEvent(event)
