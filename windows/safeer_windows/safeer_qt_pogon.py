"""Safeer Qt pogon — licencno cist predvajalnik medijev na QtMultimedia (FFmpeg, LGPL).

Brez libVLC/GPL in brez zunanje namestitve VLC. Ista koda poganja Medijski center v
Safeer OS (Windows) in samostojno aplikacijo "Safeer Player" za prenos s spletne strani.

API je namenoma vzporeden kandidatovemu GStreamer pogonu (core/os_predvajalnik.py),
da je vkljucitev v obstojeci vmesnik enostavna: dodaj/predvajaj/premor/skok, glasnost,
utisaj, hitrost, steze, nastavi_zvok, nastavi_podnapis, nalozi_podnapis (zunanji),
ponovi, nakljucno, naslednja/prejsnja, podatki, posnetek.
"""
from __future__ import annotations

import os
import random
from typing import Callable, Optional
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, QUrl, QTimer, Signal
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

PONOVI_BREZ, PONOVI_ENA, PONOVI_VSE = "brez", "ena", "vse"
_DOVOLJENE_PRIPONE_PODNAPISOV = (".srt", ".vtt", ".ass", ".ssa", ".sub")


def _je_lokalna(uri: str) -> bool:
    try:
        s = urlsplit(uri)
    except ValueError:
        return False
    return s.scheme in ("", "file")


class SafeerQtPogon(QObject):
    """Ovojnica okrog QMediaPlayer + QAudioOutput z upravljanjem seznama predvajanja.

    Video izhod (QVideoWidget/QVideoSink) in prekrivnik podnapisov nastavi vmesnik prek
    povezi_video() in bere trenutni podnapis prek signala podnapis_besedilo.
    """

    stanje_spremenjeno = Signal(dict)     # ob vsaki pomembni spremembi -> podatki()
    koncano = Signal()                    # ko se seznam v celoti zavrti (brez ponovi vse)
    podnapis_besedilo = Signal(str)       # trenutna vrstica zunanjega podnapisa ("" = brez)
    napaka = Signal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._zvok = QAudioOutput(self)
        self._player.setAudioOutput(self._zvok)

        self._seznam: list[dict] = []
        self._indeks: int = -1
        self._ponovi: str = PONOVI_BREZ
        self._nakljucno: bool = False
        self._glasnost: int = 80
        self._zvok.setVolume(self._glasnost / 100.0)

        # zunanji podnapisi (QMediaPlayer podpira le vgrajene steze)
        self._zun_cue: list[tuple[int, int, str]] = []   # (start_ms, end_ms, besedilo)
        self._zun_zadnji: str = ""

        self._player.playbackStateChanged.connect(self._ob_stanju)
        self._player.mediaStatusChanged.connect(self._ob_statusu_medija)
        self._player.positionChanged.connect(self._ob_poziciji)
        self._player.durationChanged.connect(lambda _=0: self.stanje_spremenjeno.emit(self.podatki()))
        self._player.tracksChanged.connect(lambda: self.stanje_spremenjeno.emit(self.podatki()))
        self._player.errorOccurred.connect(lambda e, s: self.napaka.emit(str(s)))

    # ---- video izhod ----
    def povezi_video(self, video_izhod) -> None:
        """Sprejme QVideoWidget ali QVideoSink; vmesnik ga poda, pogon ne ustvarja okna."""
        self._player.setVideoOutput(video_izhod)

    # ---- seznam / predvajanje ----
    def dodaj(self, uri: str, predvajaj: bool = False, vrsta: str = "medij", naslov: str = "") -> int:
        self._seznam.append({"uri": uri, "vrsta": vrsta, "naslov": naslov or _ime_iz_uri(uri)})
        i = len(self._seznam) - 1
        if predvajaj:
            self.predvajaj(i)
        else:
            self.stanje_spremenjeno.emit(self.podatki())
        return i

    def zamenjaj_vrsto(self, vnosi: list[dict]) -> bool:
        self._seznam = [
            {"uri": v.get("uri", ""), "vrsta": v.get("vrsta", "medij"),
             "naslov": v.get("naslov") or _ime_iz_uri(v.get("uri", ""))}
            for v in (vnosi or []) if v.get("uri")
        ]
        self._indeks = -1
        self.stanje_spremenjeno.emit(self.podatki())
        return True

    def predvajaj(self, indeks: int) -> bool:
        if not (0 <= indeks < len(self._seznam)):
            return False
        self._indeks = indeks
        self._zun_cue = []
        self._zun_zadnji = ""
        self.podnapis_besedilo.emit("")
        self._player.setSource(QUrl(self._seznam[indeks]["uri"]))
        self._player.play()
        self.stanje_spremenjeno.emit(self.podatki())
        return True

    def premor(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def skok(self, sekunde: float) -> bool:
        nova = max(0, self._player.position() + int(sekunde * 1000))
        traj = self._player.duration()
        if traj > 0:
            nova = min(nova, traj)
        self._player.setPosition(int(nova))
        return True

    def pojdi_na(self, delez: float) -> bool:
        """delez 0..1 znotraj trajanja (za vrstico napredka)."""
        traj = self._player.duration()
        if traj <= 0:
            return False
        self._player.setPosition(int(max(0.0, min(1.0, delez)) * traj))
        return True

    def trajanje(self) -> float:
        return self._player.duration() / 1000.0

    def naslednja(self) -> bool:
        i = self._naslednji_indeks()
        return self.predvajaj(i) if i is not None else False

    def prejsnja(self) -> bool:
        if not self._seznam:
            return False
        i = self._indeks - 1
        if i < 0:
            i = len(self._seznam) - 1 if self._ponovi == PONOVI_VSE else 0
        return self.predvajaj(i)

    def ustavi(self) -> None:
        self._player.stop()
        self.stanje_spremenjeno.emit(self.podatki())

    def zapri(self) -> None:
        try:
            self._player.stop()
            self._player.setSource(QUrl())
        except Exception:
            pass

    # ---- zvok / hitrost ----
    def nastavi_glasnost(self, v) -> bool:
        try:
            self._glasnost = max(0, min(100, int(round(float(v)))))
        except (TypeError, ValueError):
            return False
        self._zvok.setVolume(self._glasnost / 100.0)
        self.stanje_spremenjeno.emit(self.podatki())
        return True

    def utisaj(self, tiho=None) -> bool:
        nov = (not self._zvok.isMuted()) if tiho is None else bool(tiho)
        self._zvok.setMuted(nov)
        self.stanje_spremenjeno.emit(self.podatki())
        return True

    def nastavi_hitrost(self, hitrost) -> bool:
        try:
            h = max(0.25, min(4.0, float(hitrost)))
        except (TypeError, ValueError):
            return False
        self._player.setPlaybackRate(h)
        self.stanje_spremenjeno.emit(self.podatki())
        return True

    # ---- steze (vgrajene) ----
    def steze(self) -> dict:
        zvok = []
        for i, md in enumerate(self._player.audioTracks()):
            zvok.append({"indeks": i, "ime": _ime_steze(md, i, "Zvok")})
        podnapisi = [{"indeks": -1, "ime": "Brez"}]
        for i, md in enumerate(self._player.subtitleTracks()):
            podnapisi.append({"indeks": i, "ime": _ime_steze(md, i, "Podnapis")})
        return {
            "zvok": zvok, "trenutniZvok": self._player.activeAudioTrack(),
            "podnapisi": podnapisi, "trenutniPodnapis": self._player.activeSubtitleTrack(),
            "zunanji": bool(self._zun_cue),
        }

    def nastavi_zvok(self, indeks) -> bool:
        try:
            i = int(indeks)
        except (TypeError, ValueError):
            return False
        if 0 <= i < len(self._player.audioTracks()):
            self._player.setActiveAudioTrack(i)
            self.stanje_spremenjeno.emit(self.podatki())
            return True
        return False

    def nastavi_podnapis(self, indeks) -> bool:
        try:
            i = int(indeks)
        except (TypeError, ValueError):
            return False
        # zunanji podnapis izklopimo, ce izbiramo vgrajeno stezo / izklop
        if self._zun_cue:
            self._zun_cue = []
            self.podnapis_besedilo.emit("")
        self._player.setActiveSubtitleTrack(i)  # -1 = izklop
        self.stanje_spremenjeno.emit(self.podatki())
        return True

    def nalozi_podnapis(self, uri) -> bool:
        """Zunanji podnapis (.srt/.vtt): QMediaPlayer ga ne podpira, zato ga razclenimo
        in prikazujemo prek prekrivnika (signal podnapis_besedilo)."""
        pot = uri
        if uri.startswith("file:"):
            pot = QUrl(uri).toLocalFile()
        if not (os.path.isfile(pot) and pot.lower().endswith(_DOVOLJENE_PRIPONE_PODNAPISOV)):
            return False
        try:
            with open(pot, "r", encoding="utf-8", errors="replace") as f:
                vsebina = f.read()
        except OSError:
            return False
        cue = _razclleni_srt_vtt(vsebina)
        if not cue:
            return False
        self._player.setActiveSubtitleTrack(-1)  # ugasni vgrajene
        self._zun_cue = cue
        self._zun_zadnji = ""
        self.stanje_spremenjeno.emit(self.podatki())
        return True

    # ---- ponovi / nakljucno ----
    def nastavi_ponovi(self, nacin) -> bool:
        if nacin not in (PONOVI_BREZ, PONOVI_ENA, PONOVI_VSE):
            return False
        self._ponovi = nacin
        self.stanje_spremenjeno.emit(self.podatki())
        return True

    def preklopi_nakljucno(self, vklop=None) -> bool:
        self._nakljucno = (not self._nakljucno) if vklop is None else bool(vklop)
        self.stanje_spremenjeno.emit(self.podatki())
        return True

    # ---- posnetek ----
    def posnetek(self, pot: str) -> bool:
        sink = self._player.videoSink() if hasattr(self._player, "videoSink") else None
        if sink is None:
            return False
        frame = sink.videoFrame()
        if not frame.isValid():
            return False
        slika = frame.toImage()
        if slika.isNull():
            return False
        return bool(slika.save(pot))

    # ---- stanje ----
    def podatki(self) -> dict:
        vnos = self._seznam[self._indeks] if 0 <= self._indeks < len(self._seznam) else {}
        st = self._player.playbackState()
        stanje = {QMediaPlayer.PlayingState: "predvaja",
                  QMediaPlayer.PausedState: "premor"}.get(st, "ustavljeno")
        s = self.steze()
        return {
            "stanje": stanje,
            "indeks": self._indeks,
            "nSeznam": len(self._seznam),
            "naslov": vnos.get("naslov", ""),
            "vrsta": vnos.get("vrsta", ""),
            "polozaj": self._player.position() / 1000.0,
            "trajanje": self._player.duration() / 1000.0,
            "glasnost": self._glasnost,
            "utisan": self._zvok.isMuted(),
            "hitrost": self._player.playbackRate(),
            "ponovi": self._ponovi,
            "nakljucno": self._nakljucno,
            "nZvok": len(s["zvok"]),
            "trenutniZvok": s["trenutniZvok"],
            "nPodnapis": len(s["podnapisi"]) - 1,
            "trenutniPodnapis": s["trenutniPodnapis"],
            "zunanjiPodnapis": s["zunanji"],
            "steze": s,
        }

    # ---- notranje ----
    def _naslednji_indeks(self):
        if not self._seznam:
            return None
        if self._ponovi == PONOVI_ENA:
            return self._indeks
        if self._nakljucno and len(self._seznam) > 1:
            moznosti = [i for i in range(len(self._seznam)) if i != self._indeks]
            return random.choice(moznosti)
        if self._indeks + 1 < len(self._seznam):
            return self._indeks + 1
        if self._ponovi == PONOVI_VSE:
            return 0
        return None

    def _po_koncu(self) -> None:
        i = self._naslednji_indeks()
        if i is None:
            self.koncano.emit()
        else:
            self.predvajaj(i)

    def _ob_statusu_medija(self, status) -> None:
        if status == QMediaPlayer.EndOfMedia:
            self._po_koncu()

    def _ob_stanju(self, _=0) -> None:
        self.stanje_spremenjeno.emit(self.podatki())

    def _ob_poziciji(self, ms) -> None:
        if self._zun_cue:
            besedilo = _cue_ob(self._zun_cue, ms)
            if besedilo != self._zun_zadnji:
                self._zun_zadnji = besedilo
                self.podnapis_besedilo.emit(besedilo)
        # pozicijo osvezujemo redkeje prek vmesnika; tu ne oddajamo celega podatki()


def _ime_iz_uri(uri: str) -> str:
    if not uri:
        return ""
    pot = QUrl(uri).toLocalFile() if uri.startswith("file:") else uri
    return os.path.basename(pot.rstrip("/")) or uri


def _ime_steze(md, i: int, privzeto: str) -> str:
    try:
        from PySide6.QtMultimedia import QMediaMetaData
        jezik = md.stringValue(QMediaMetaData.Key.Language) if md else ""
        naslov = md.stringValue(QMediaMetaData.Key.Title) if md else ""
    except Exception:
        jezik = naslov = ""
    ime = (naslov or jezik or "").strip()
    return ime if ime else f"{privzeto} {i + 1}"


def _tc_v_ms(tc: str) -> int:
    tc = tc.strip().replace(",", ".")
    d = tc.split(":")
    try:
        if len(d) == 3:
            h, m, s = d
        elif len(d) == 2:
            h, m, s = "0", d[0], d[1]
        else:
            return 0
        return int((int(h) * 3600 + int(m) * 60 + float(s)) * 1000)
    except ValueError:
        return 0


def _razclleni_srt_vtt(vsebina: str) -> list:
    """Zelo tolerantno razclenjevanje SRT in WebVTT casovnic v (start_ms, end_ms, besedilo)."""
    import re
    vsebina = vsebina.replace("\r\n", "\n").replace("\r", "\n")
    cue = []
    vzorec = re.compile(r"(\d{1,2}:\d{2}(?::\d{2})?[.,]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}(?::\d{2})?[.,]\d{1,3})")
    bloki = re.split(r"\n\s*\n", vsebina)
    for blok in bloki:
        vrstice = [v for v in blok.split("\n") if v.strip() != ""]
        if not vrstice:
            continue
        cas_idx = None
        for idx, v in enumerate(vrstice):
            m = vzorec.search(v)
            if m:
                cas_idx = idx
                start, konec = _tc_v_ms(m.group(1)), _tc_v_ms(m.group(2))
                break
        if cas_idx is None:
            continue
        besedilo = "\n".join(vrstice[cas_idx + 1:]).strip()
        besedilo = re.sub(r"<[^>]+>", "", besedilo)  # odstrani preproste oznake
        if besedilo and konec > start:
            cue.append((start, konec, besedilo))
    cue.sort(key=lambda c: c[0])
    return cue


def _cue_ob(cue: list, ms: int) -> str:
    for start, konec, besedilo in cue:
        if start <= ms <= konec:
            return besedilo
    return ""
