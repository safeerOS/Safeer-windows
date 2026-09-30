"""Vgrajeni libmpv predvajalnik za Safeer Media (Medijski center) — ISTI vmesnik kot VlcPlayerWidget.

Dodatek, ne zamenjava: vlc_player.py ostane; os_app izbere pogon prek safeer_pogon_izbira (mpv, ce je
paket libmpv prilozen in nalozljiv, sicer dosedanja pot). Slika: mpv (gpu-next) rise v nativno povrsino
SafeerMpvVideo znotraj glavnega okna; podnapisi (datoteke ob videu in vgrajeni) jih izrise mpv sam.
Javni vmesnik (uporablja os_app): available, player.is_playing(), current_item, jezik_vmesnika,
set_fullscreen_ui, play_item, stop, toggle_play, close_player, izberi_podnapise, naslednji_podnapisi,
signala nazaj/ozadje.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider,
                               QVBoxLayout, QWidget)

from .predvajalnik_nadaljuj import Sledilec
from .safeer_mpv_okno import SafeerMpvVideo
from .vlc_player import _BESEDILA, _dovoljen_podnapis

_log = logging.getLogger("safeer.media.mpv")


class _PlayerShim:
    """os_app klice self.media_player.player.is_playing(); ohranimo to obliko."""
    def __init__(self, lastnik):
        self._l = lastnik

    def is_playing(self) -> bool:
        p = self._l.pogon
        if not p:
            return False
        try:
            return p.podatki().get("stanje") == "predvaja"
        except Exception:
            return False


class MpvPlayerWidget(QWidget):
    nazaj = Signal()
    ozadje = Signal()
    stanje_spremenjeno = Signal(dict)   # podatki pogona (nit vmesnika): os_app jih posreduje daljincu (Link)
    _sprememba = Signal(dict)     # iz mpv niti v nit vmesnika
    _napaka = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.pogon = None
        self._nadaljuj = Sledilec(vklop=False)   # pravi sledilec se poveze v _init_mpv
        self.player = None            # _PlayerShim, ko je pogon ustvarjen
        self.current_item: dict = {}
        self.seeking = False
        self.jezik_vmesnika = lambda: "sl"
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
        self._zunanji: list = []       # datoteke podnapisov trenutnega videa (dict: uri, jezik, oznaka, ime)
        self._zunanji_id: dict = {}    # indeks datoteke -> mpv sid
        self._samodejno_vgrajeni = False
        self._rod = 0
        self._sprememba.connect(self._ob_spremembi, Qt.QueuedConnection)
        self._napaka.connect(self._pokazi_napako, Qt.QueuedConnection)
        self._build_ui()
        QTimer.singleShot(0, self._init_mpv)

    @property
    def available(self) -> bool:
        return self.pogon is not None

    # ------------------------------------------------------------------ UI (enak videz kot VLC razlicica)
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
        root = QVBoxLayout(self); root.setContentsMargins(24, 20, 24, 22); root.setSpacing(14)
        header = QHBoxLayout(); labels = QVBoxLayout()
        brand = QLabel("SAFEER OS · MEDIA"); brand.setObjectName("brand")
        self.title = QLabel("Medijski center"); self.title.setObjectName("title")
        self.meta = QLabel(""); self.meta.setObjectName("meta")
        labels.addWidget(brand); labels.addWidget(self.title); labels.addWidget(self.meta)
        header.addLayout(labels, 1)
        dodatki = QPushButton("⚙  Dodatki"); dodatki.setToolTip("Stremio in Kodi dodatki — vnesi naslove svojih dodatkov")
        dodatki.clicked.connect(self.odpri_dodatke)
        back = QPushButton("←  Nazaj v Safeer OS"); back.clicked.connect(self.close_player)
        fullscreen = QPushButton("⛶  Celozaslonsko"); fullscreen.clicked.connect(lambda: self.window().preklopi_celozaslonsko())
        header.addWidget(dodatki); header.addWidget(fullscreen); header.addWidget(back); root.addLayout(header)
        self._fullscreen_header_widgets = [brand, self.title, self.meta, dodatki, fullscreen, back]

        # Nativna povrsina za mpv (brez zaobljenih robov: nativno okno jih ne pozna).
        self.video = SafeerMpvVideo(self)
        self.video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.video.setMinimumSize(640, 360)
        self.video.dvoklik.connect(lambda: self.window().preklopi_celozaslonsko())
        root.addWidget(self.video, 1)

        self.audio_visual = QLabel("♫"); self.audio_visual.setObjectName("audioVisual")
        self.audio_visual.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.audio_visual.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.audio_visual.setMinimumSize(640, 360); self.audio_visual.hide(); root.addWidget(self.audio_visual, 1)

        controls = QHBoxLayout()
        self.play_button = QPushButton("▶ / ❚❚"); self.play_button.clicked.connect(self.toggle_play)
        stop = QPushButton("■"); stop.clicked.connect(self.stop)
        self.position = QSlider(Qt.Orientation.Horizontal); self.position.setRange(0, 1000)
        self.position.sliderPressed.connect(lambda: setattr(self, "seeking", True)); self.position.sliderReleased.connect(self._seek)
        self.time_label = QLabel("00:00 / 00:00")
        volume_label = QLabel("🔊")
        self.volume = QSlider(Qt.Orientation.Horizontal); self.volume.setRange(0, 100); self.volume.setValue(80)
        self.volume.setMaximumWidth(130); self.volume.valueChanged.connect(self._set_volume)
        self.variants = QComboBox(); self.variants.currentIndexChanged.connect(self._change_variant)
        self.subtitles = QComboBox(); self.subtitles.addItem("CC  Podnapisi izklopljeni", "izklop")
        self.subtitles.currentIndexChanged.connect(self._change_subtitle)
        self.background = QPushButton("♫  Ozadje")
        self.background.setToolTip("Nadaljuj predvajanje v ozadju (Ctrl+Shift+M odpre upravljanje)")
        self.background.clicked.connect(self.ozadje.emit); self.background.setVisible(False)
        for w in (self.play_button, stop): controls.addWidget(w)
        controls.addWidget(self.position, 1)
        for w in (self.time_label, volume_label, self.volume, self.variants, self.subtitles, self.background): controls.addWidget(w)
        root.addLayout(controls)
        self._fullscreen_control_widgets = [self.play_button, stop, self.position, self.time_label, volume_label,
                                            self.volume, self.variants, self.subtitles, self.background]
        self._player_layout = root

    def odpri_dodatke(self) -> None:
        from .predvajalnik_dodatki_okno import DodatkiOkno
        DodatkiOkno(self).exec()

    def set_fullscreen_ui(self, enabled: bool) -> None:
        for widget in self._fullscreen_header_widgets + self._fullscreen_control_widgets:
            widget.setVisible(not enabled)
        m = 0 if enabled else 24
        self._player_layout.setContentsMargins(m, 0 if enabled else 20, m, 0 if enabled else 22)

    # ------------------------------------------------------------------ pogon
    def _init_mpv(self) -> None:
        try:
            from .safeer_mpv_pogon import SafeerMpvPogon
            self.pogon = SafeerMpvPogon(lambda p=None: self._sprememba.emit(p or {}), None,
                                        lambda s="": self._napaka.emit(str(s)))
            self.pogon.povezi_video(self.video.wid())
            self._nadaljuj = Sledilec(); self._nadaljuj.povezi(self.pogon)   # nadaljuj tam, kjer si koncal
            self._pripravi_mpris()
            self.pogon.nastavi_glasnost(self.volume.value())
            self.player = _PlayerShim(self)
            _log.info("Medijski center: libmpv pogon povezan (wid=%s)", self.video.wid())
        except Exception as e:  # noqa: BLE001
            self.pogon = None; self.player = None
            _log.error("Medijski center: libmpv pogon ni na voljo: %s", e)

    def _pripravi_mpris(self) -> None:
        """MPRIS2 (Linux): medijske tipke in zvocni aplet upravljajo Medijski center."""
        self.mpris = None
        if os.environ.get("SAFEER_MPRIS", "1") == "0":
            return
        try:
            from .predvajalnik_mpris import SafeerMpris
            m = SafeerMpris(self.pogon, ime="Safeer OS — Medijski center", okno=self.window(), storitev="safeeros")
            self.mpris = m if m.aktiven else None
        except Exception as e:  # noqa: BLE001
            _log.debug("mpris: %s", e)

    def _m(self):
        return self.pogon._zagotovi() if self.pogon else None

    # ------------------------------------------------------------------ predvajanje
    def play_item(self, item: dict, variant_index: int = 0) -> bool:
        if not self.pogon:
            return False
        variants = item.get("razlicice") or [{"url": item.get("url", ""), "vir": item.get("vir", ""),
                                               "kakovost": item.get("kakovost", "")}]
        if not variants:
            return False
        variant_index = min(max(0, variant_index), len(variants) - 1)
        self.current_item = dict(item)
        self.title.setText(str(item.get("naslov") or "Medijski center"))
        self.meta.setText(" · ".join(filter(None, (str(item.get("izvajalec") or ""), str(item.get("leto") or ""),
                                                    str(variants[variant_index].get("vir") or "")))))
        self.variants.blockSignals(True); self.variants.clear()
        for variant in variants:
            self.variants.addItem(" · ".join(filter(None, (str(variant.get("kakovost") or "Samodejno"), str(variant.get("vir") or "Vir")))))
        self.variants.setCurrentIndex(variant_index); self.variants.setVisible(len(variants) > 1); self.variants.blockSignals(False)
        is_audio = item.get("vrsta") in ("glasba", "radio")
        self.video.setVisible(not is_audio); self.audio_visual.setVisible(is_audio); self.background.setVisible(is_audio)
        variant = variants[variant_index]
        headers = variant.get("glave") if isinstance(variant.get("glave"), dict) else {}
        lowered = {str(k).casefold(): str(v) for k, v in headers.items()}
        referer = str(variant.get("referer") or lowered.get("referer") or lowered.get("referrer") or item.get("referer") or "").strip()
        user_agent = str(lowered.get("user-agent") or lowered.get("user_agent") or "").strip()
        ostale = {k: v for k, v in headers.items() if str(k).casefold() not in ("referer", "referrer", "user-agent", "user_agent")
                  and "\n" not in str(v) and "\r" not in str(v)}
        self.pogon.nastavi_glave(referer if "\n" not in referer and "\r" not in referer else "",
                                 user_agent if "\n" not in user_agent and "\r" not in user_agent else "", ostale or None)
        from . import podnapisi_izbira as _pi
        self._zunanji = [p for p in (item.get("podnapisi") or []) if isinstance(p, dict)
                         and _dovoljen_podnapis(str(p.get("uri") or ""))][:24] if not is_audio else []
        self._zunanji_id = {}
        self._rod += 1
        m = self._m()
        try:
            m.sub_auto = "no"                      # datoteke ob videu dodamo sami (kot na Linuxu)
            jeziki = _pi.zeleni_jeziki(self._nastavitve_podnapisov, self._jezik_sistema)
            m.slang = ",".join(jeziki) if jeziki and self._nastavitve_podnapisov.get("izklop") is not True else ""
        except Exception as e:  # noqa: BLE001
            _log.debug("moznosti podnapisov: %s", e)
        zunanji = _pi.samodejna_zunanja(self._zunanji, self._nastavitve_podnapisov, self._jezik_sistema)
        self._samodejno_vgrajeni = zunanji < 0
        ok = self.pogon.zamenjaj_vrsto([{"uri": str(variant.get("url") or ""), "vrsta": str(item.get("vrsta") or "medij"),
                                         "naslov": str(item.get("naslov") or "")}])
        if ok:
            self.pogon.predvajaj(0)
        try:
            m.sid = "no"
        except Exception:
            pass
        self._napolni_podnapise()
        if zunanji >= 0:
            QTimer.singleShot(300, lambda rod=self._rod: self._dodaj_zunanji(zunanji, True, rod))
        QTimer.singleShot(1800, lambda rod=self._rod: self._load_subtitles(rod))
        return bool(ok)

    def toggle_play(self) -> None:
        if self.pogon:
            self.pogon.premor()

    def _shrani_polozaj(self) -> None:
        try:
            self._nadaljuj.zabelezi(getattr(self, "_zadnji_podatki", {}) or {}, takoj=True)
        except Exception as e:  # noqa: BLE001
            _log.debug("nadaljuj shrani: %s", e)

    def stop(self) -> None:
        if self.pogon:
            self._shrani_polozaj()
            self.pogon.ustavi()

    def close_player(self) -> None:
        self.stop()
        self.nazaj.emit()

    def _set_volume(self, value: int) -> None:
        if self.pogon:
            self.pogon.nastavi_glasnost(value)

    def _seek(self) -> None:
        if self.pogon:
            self.pogon.pojdi_na(self.position.value() / 1000.0)
        self.seeking = False

    def _change_variant(self, index: int) -> None:
        if index >= 0 and self.current_item:
            self.play_item(self.current_item, index)

    # ------------------------------------------------------------------ stanje
    @staticmethod
    def _format_time(sekunde: float) -> str:
        s = max(0, int(sekunde or 0))
        return f"{s // 60:02d}:{s % 60:02d}"

    def _ob_spremembi(self, p: dict) -> None:
        if not self.pogon:
            return
        try:
            if self.pogon.obdelaj_konec():
                p = {}
            if not p:
                p = self.pogon.podatki()
        except Exception as e:  # noqa: BLE001
            _log.debug("podatki: %s", e); return
        self._zadnji_podatki = p
        try:
            self._nadaljuj.ob_podatkih(p)
        except Exception as e:  # noqa: BLE001
            _log.debug("nadaljuj: %s", e)
        if getattr(self, "mpris", None):
            self.mpris.ob_podatkih(p)
        self.stanje_spremenjeno.emit(p)
        if not self.seeking and p.get("trajanje"):
            self.position.setValue(max(0, int(1000 * float(p.get("polozaj") or 0) / float(p["trajanje"]))))
        self.time_label.setText(f"{self._format_time(p.get('polozaj', 0))} / {self._format_time(p.get('trajanje', 0))}")

    def _t(self, kljuc: str) -> str:
        try:
            jezik = str(self.jezik_vmesnika() or "sl")
        except Exception:  # noqa: BLE001
            jezik = "sl"
        return _BESEDILA.get(jezik, _BESEDILA["en"]).get(kljuc, _BESEDILA["en"][kljuc])

    def _pokazi_napako(self, _s: str = "") -> None:
        dvd = str(self.current_item.get("url") or "").startswith("dvd:")
        self.meta.setText(self._t("dvd" if dvd else "napaka"))

    # ------------------------------------------------------------------ podnapisi (mpv: sid; zunanji prek sub-add)
    def _sledi_podnapisov(self) -> list:
        """[(sid, ime, koda_jezika, zunanji)] iz mpv track-list."""
        from . import podnapisi_izbira as _pi
        m = self._m()
        if m is None:
            return []
        try:
            tl = m.track_list or []
        except Exception:  # noqa: BLE001
            return []
        izid = []
        for t in tl:
            if t.get("type") != "sub":
                continue
            ime = str(t.get("title") or "")
            koda = _pi.koda_jezika(str(t.get("lang") or "")) or _pi.koda_jezika(ime)
            izid.append((int(t.get("id")), ime, koda, bool(t.get("external"))))
        return izid

    def _vgrajeni(self) -> list:
        return [(i, ime, koda) for i, ime, koda, zun in self._sledi_podnapisov() if not zun and i not in self._zunanji_id.values()]

    def _ime_zunanjega(self, p: dict) -> str:
        from core import podnapisi as _pn
        jezik = str(p.get("jezik") or "")
        ime_jezika = _pn.ime_jezika(jezik, str(self.jezik_vmesnika() or "sl")) if jezik else ""
        return " · ".join(x for x in (ime_jezika, str(p.get("oznaka") or "")) if x) or str(p.get("ime") or "")

    def _trenutni_sid(self) -> int:
        m = self._m()
        try:
            v = m.sid if m is not None else None
            return int(v) if v not in (None, False, "no") else -1
        except Exception:  # noqa: BLE001
            return -1

    def _izbran_kljuc(self) -> str:
        sid = self._trenutni_sid()
        if sid < 0:
            return "izklop"
        k = next((k for k, i in self._zunanji_id.items() if i == sid), None)
        return "z:%d" % k if k is not None else "v:%d" % sid

    def _kljuci_podnapisov(self) -> list:
        return (["izklop"] + ["z:%d" % k for k in range(len(self._zunanji))] + ["v:%d" % i for i, _ime, _k in self._vgrajeni()])

    def _napolni_podnapise(self) -> None:
        from core import podnapisi as _pn
        self.subtitles.blockSignals(True); self.subtitles.clear()
        self.subtitles.addItem("CC  " + self._t("izklop"), "izklop")
        for k, p in enumerate(self._zunanji):
            self.subtitles.addItem("CC  " + self._ime_zunanjega(p), "z:%d" % k)
        for ident, ime, koda in self._vgrajeni():
            napis = ime or (_pn.ime_jezika(koda, str(self.jezik_vmesnika() or "sl")) if koda else self._t("v_videu"))
            self.subtitles.addItem("CC  " + napis + " · " + self._t("vgrajeni"), "v:%d" % ident)
        indeks = self.subtitles.findData(self._izbran_kljuc())
        self.subtitles.setCurrentIndex(max(0, indeks)); self.subtitles.blockSignals(False)

    def _dodaj_zunanji(self, k: int, izberi: bool, rod: int = -1, poskus: int = 0) -> None:
        """sub-add je sinhron in vrne novo sled; datoteko dodamo, ko je video odprt (poskusi do 10 s)."""
        rod = self._rod if rod < 0 else rod
        if not self.pogon or rod != self._rod or not 0 <= k < len(self._zunanji):
            return
        if k in self._zunanji_id:
            if izberi:
                try: self._m().sid = self._zunanji_id[k]
                except Exception: pass
            self._napolni_podnapise(); return
        m = self._m()
        try:
            odprt = bool(m.video_params and m.video_params.get("w")) or bool(m.duration)
        except Exception:  # noqa: BLE001
            odprt = False
        if not odprt and poskus < 40:
            QTimer.singleShot(250, lambda: self._dodaj_zunanji(k, izberi, rod, poskus + 1)); return
        znani = {i for i, _n, _k, _z in self._sledi_podnapisov()}
        uri = str(self._zunanji[k]["uri"])
        if uri.startswith("file:"):
            from urllib.parse import urlsplit
            from urllib.request import url2pathname
            uri = url2pathname(urlsplit(uri).path)
        try:
            m.command("sub-add", uri, "select" if izberi else "auto")
        except Exception as e:  # noqa: BLE001
            print(f"[SafeerMedia] podnapisi niso dodani: {e}", flush=True); return
        nov = sorted({i for i, _n, _k, _z in self._sledi_podnapisov()} - znani)
        if nov:
            self._zunanji_id[k] = nov[0]
        self._napolni_podnapise()

    def _load_subtitles(self, rod: int = -1) -> None:
        if not self.pogon or (rod >= 0 and rod != self._rod):
            return
        if self._samodejno_vgrajeni:
            from . import podnapisi_izbira as _pi
            self._samodejno_vgrajeni = False
            ident = _pi.samodejni_vgrajeni([(i, koda) for i, _ime, koda in self._vgrajeni()],
                                           self._nastavitve_podnapisov, self._jezik_sistema)
            try:
                self._m().sid = ident if ident is not None else "no"
            except Exception:  # noqa: BLE001
                pass
        self._napolni_podnapise()

    def izberi_podnapise(self, kljuc: str) -> bool:
        from . import podnapisi_izbira as _pi
        if not self.pogon:
            return False
        kljuc = str(kljuc or ""); jezik = ""; m = self._m()
        if kljuc == "izklop":
            m.sid = "no"
        elif kljuc.startswith("z:"):
            k = int(kljuc[2:])
            if not 0 <= k < len(self._zunanji):
                return False
            self._dodaj_zunanji(k, True)
            jezik = str(self._zunanji[k].get("jezik") or "")
        elif kljuc.startswith("v:"):
            ident = int(kljuc[2:]); m.sid = ident
            jezik = next((koda for i, _ime, koda in self._vgrajeni() if i == ident), "")
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
        from . import podnapisi_izbira as _pi
        kljuci = self._kljuci_podnapisov()
        if len(kljuci) < 2:
            return False
        return self.izberi_podnapise(_pi.naslednji_kljuc(kljuci, self._izbran_kljuc()))

    def _change_subtitle(self, index: int) -> None:
        if self.pogon and index >= 0:
            kljuc = self.subtitles.itemData(index)
            if isinstance(kljuc, str):
                self.izberi_podnapise(kljuc)

    # ------------------------------------------------------------------ tipke (kot VLC razlicica)
    def keyPressEvent(self, event) -> None:
        k = event.key()
        if k in (Qt.Key.Key_Space, Qt.Key.Key_MediaPlay, Qt.Key.Key_MediaPause, Qt.Key.Key_MediaTogglePlayPause):
            self.toggle_play(); event.accept(); return
        if k == Qt.Key.Key_MediaStop:
            self.stop(); event.accept(); return
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Right) and self.pogon:
            self.pogon.skok(-10 if k == Qt.Key.Key_Left else 10); event.accept(); return
        if k == Qt.Key.Key_V and not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.naslednji_podnapisi(); event.accept(); return
        if self.pogon and k in (Qt.Key.Key_Z, Qt.Key.Key_X, Qt.Key.Key_K, Qt.Key.Key_L, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown,
                                Qt.Key.Key_BracketLeft, Qt.Key.Key_BracketRight, Qt.Key.Key_Backspace):
            self._napredna_tipka(k, bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)); event.accept(); return
        super().keyPressEvent(event)

    def _napredna_tipka(self, k, shift: bool) -> None:
        """Z/X zamik podnapisov, K/L zamik zvoka (0,1 s; Shift 1 s), PgUp/PgDn poglavje, [ ] hitrost, Backspace 1x."""
        korak = 1.0 if shift else 0.1
        if k in (Qt.Key.Key_Z, Qt.Key.Key_X):
            z = self.pogon.zamik_podnapisov(delta=korak if k == Qt.Key.Key_X else -korak); self.pogon.osd(f"Podnapisi: {z:+.1f} s")
        elif k in (Qt.Key.Key_K, Qt.Key.Key_L):
            z = self.pogon.zamik_zvoka(delta=korak if k == Qt.Key.Key_L else -korak); self.pogon.osd(f"Zvok: {z:+.1f} s")
        elif k in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
            p = getattr(self, "_zadnji_podatki", {}) or {}
            if not int(p.get("nPoglavij") or 0):
                self.pogon.osd("Ni poglavij"); return
            self.pogon.naslednje_poglavje(1 if k == Qt.Key.Key_PageDown else -1)
        elif k in (Qt.Key.Key_BracketLeft, Qt.Key.Key_BracketRight, Qt.Key.Key_Backspace):
            p = getattr(self, "_zadnji_podatki", {}) or {}
            h = 1.0 if k == Qt.Key.Key_Backspace else float(p.get("hitrost") or 1.0) + (0.1 if k == Qt.Key.Key_BracketRight else -0.1)
            h = max(0.25, min(4.0, round(h, 2))); self.pogon.nastavi_hitrost(h); self.pogon.osd(f"Hitrost {h:g}×")

    def zapri_pogon(self) -> None:
        if getattr(self, "mpris", None):
            try:
                self.mpris.zapri()
            except Exception:  # noqa: BLE001
                pass
            self.mpris = None
        if self.pogon:
            self._shrani_polozaj()
            self.pogon.zapri(); self.pogon = None; self.player = None
