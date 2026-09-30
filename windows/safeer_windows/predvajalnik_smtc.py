"""Windows SMTC (System Media Transport Controls) za Safeer predvajalnik.

Windows pokaže medijsko ploščico (glasnostni meni, zaklenjen zaslon, Bluetooth slušalke, tipkovnične medijske
tipke tudi brez fokusa okna). Uporabljamo uradno projekcijo Python/WinRT (paketi `winrt-runtime`,
`winrt-Windows.Media`, `winrt-Windows.Media.Playback`, `winrt-Windows.Foundation`, `winrt-Windows.Storage.Streams`;
Microsoft, MIT). Za Win32 (Qt) okno SMTC dobimo prek `MediaPlayer().system_media_transport_controls` z izklopljenim
CommandManagerjem – preverjeno 30. 9. 2026 na Windows 11 (Python 3.14): sistem vidi sejo z naslovom in stanjem.

Isti vmesnik kot predvajalnik_mpris.SafeerMpris: `aktiven`, `ob_podatkih(p)`, `oddaj_seeked()`, `zapri()`.
Brez paketov ali zunaj Windows je `aktiven=False` in predvajalnik dela naprej (nadzorovan preskok, zabeležen v dnevnik).
Gumbi iz sistema pridejo v WinRT niti -> Qt signal -> GUI nit.
"""
from __future__ import annotations

import logging
import sys

_log = logging.getLogger("safeer.predvajalnik.smtc")


def na_voljo() -> bool:
    """Ali so paketi winrt namesceni - BREZ uvoza: uvoz winrt (+asyncio) na Windows traja 4-6 s, zato ga
    SafeerSmtc opravi v ozadju (glej __init__), ne ob zagonu okna."""
    if sys.platform != "win32":
        return False
    try:
        import importlib.util
        return importlib.util.find_spec("winrt.windows.media") is not None and importlib.util.find_spec("winrt.windows.media.playback") is not None
    except Exception:
        return False


def _status(p: dict) -> str:
    s = (p or {}).get("stanje")
    return "Playing" if s == "predvaja" else ("Paused" if s == "premor" else "Stopped")


class SafeerSmtc:
    def __init__(self, pogon, ime: str = "Safeer Predvajalnik", okno=None):
        self.pogon = pogon
        self.ime = ime
        self.okno = okno
        self.aktiven = False
        self._zadnji: dict = {}
        self._zadnji_kljuc = None
        self._zadnji_polozaj = -1
        self._mp = None
        self._smtc = None
        self._most = None
        self._zeton = None
        self._zadnji_p: dict = {}
        if not na_voljo():
            _log.info("SMTC ni na voljo (ni Windows ali manjkajo paketi winrt) - medijske tipke delujejo le s fokusom okna")
            return
        # Uvoz winrt je pocasen (merjeno 4-6 s na Windows 11); gre v nit v ozadju, SMTC se prijavi, ko je pripravljen.
        # Do takrat predvajalnik dela normalno (medijske tipke s fokusom okna), stanje se ob prijavi prenese.
        import threading
        from PySide6.QtCore import QObject, Signal

        class _Pripravljeno(QObject):
            koncano = Signal(bool)

        self._priprava = _Pripravljeno(okno)
        self._priprava.koncano.connect(self._po_uvozu)

        def uvozi():
            try:
                import winrt.windows.media  # noqa: F401
                import winrt.windows.media.playback  # noqa: F401
                ok = True
            except Exception as e:  # noqa: BLE001
                _log.warning("SMTC: uvoz winrt ni uspel: %s", e); ok = False
            try:
                self._priprava.koncano.emit(ok)
            except Exception:
                pass
        threading.Thread(target=uvozi, name="safeer-smtc-uvoz", daemon=True).start()

    def _po_uvozu(self, ok: bool) -> None:
        """GUI nit: winrt je uvozen - prijava v SMTC in prenos zadnjega znanega stanja."""
        if not ok or self.pogon is None:
            return
        try:
            self._zazeni()
        except Exception as e:  # noqa: BLE001
            _log.warning("SMTC ni na voljo: %s", e); self.aktiven = False; return
        if self._zadnji_p:
            self.ob_podatkih(self._zadnji_p)

    # ---- zagon ----
    def _zazeni(self) -> None:
        from PySide6.QtCore import QObject, Signal, Qt
        from winrt.windows.media import MediaPlaybackStatus, MediaPlaybackType, SystemMediaTransportControlsButton
        from winrt.windows.media.playback import MediaPlayer

        class _Most(QObject):
            gumb = Signal(str)

        most = _Most(self.okno)
        most.gumb.connect(self._ukaz, Qt.ConnectionType.QueuedConnection)
        mp = MediaPlayer()
        mp.command_manager.is_enabled = False       # gumbe obravnavamo sami (mpv), ne MediaPlayer
        s = mp.system_media_transport_controls
        s.is_enabled = True
        s.is_play_enabled = s.is_pause_enabled = s.is_stop_enabled = True
        s.is_next_enabled = s.is_previous_enabled = False
        s.playback_status = MediaPlaybackStatus.CLOSED
        imena = {SystemMediaTransportControlsButton.PLAY: "play", SystemMediaTransportControlsButton.PAUSE: "pause",
                 SystemMediaTransportControlsButton.STOP: "stop", SystemMediaTransportControlsButton.NEXT: "next",
                 SystemMediaTransportControlsButton.PREVIOUS: "previous"}

        def ob_gumbu(_s, args):
            ime = imena.get(args.button)
            if ime:
                most.gumb.emit(ime)

        self._zeton = s.add_button_pressed(ob_gumbu)
        self._mp, self._smtc, self._most = mp, s, most
        self._MediaPlaybackStatus, self._MediaPlaybackType = MediaPlaybackStatus, MediaPlaybackType
        self.aktiven = True
        _log.info("SMTC: aktiven (%s)", self.ime)

    def zapri(self) -> None:
        if not self.aktiven:
            return
        try:
            if self._zeton is not None:
                self._smtc.remove_button_pressed(self._zeton)
            self._smtc.is_enabled = False
            self._mp.close()
        except Exception:
            pass
        self.aktiven = False

    def oddaj_seeked(self) -> None:
        self._zadnji_polozaj = -1
        self._casovnica(self._zadnji)

    # ---- stanje iz pogona (GUI nit) ----
    def ob_podatkih(self, p: dict) -> None:
        if p:
            self._zadnji_p = dict(p)   # za prijavo, ko bo winrt uvozen
        if not self.aktiven or not p:
            return
        self._zadnji = dict(p)
        kljuc = (_status(p), p.get("uri"), p.get("naslov"), int(p.get("indeks", -1)), int(p.get("nSeznam") or 0))
        if kljuc != self._zadnji_kljuc:
            self._zadnji_kljuc = kljuc
            try:
                self._posodobi_prikaz(p, kljuc[0])
            except Exception as e:
                _log.debug("SMTC prikaz: %s", e)
        self._casovnica(p)

    def _posodobi_prikaz(self, p: dict, status: str) -> None:
        S = self._MediaPlaybackStatus
        s = self._smtc
        s.playback_status = {"Playing": S.PLAYING, "Paused": S.PAUSED}.get(status, S.STOPPED)
        s.is_next_enabled = int(p.get("indeks", -1)) + 1 < int(p.get("nSeznam") or 0)
        s.is_previous_enabled = int(p.get("indeks", -1)) > 0
        du = s.display_updater
        du.type = self._MediaPlaybackType.VIDEO
        du.video_properties.title = str(p.get("naslov") or self.ime)[:200]
        du.video_properties.subtitle = self.ime
        du.update()

    def _casovnica(self, p: dict) -> None:
        if not self.aktiven or not p:
            return
        polozaj = int(float(p.get("polozaj") or 0))
        if polozaj == self._zadnji_polozaj:
            return
        self._zadnji_polozaj = polozaj
        try:
            from datetime import timedelta
            from winrt.windows.media import SystemMediaTransportControlsTimelineProperties
            t = SystemMediaTransportControlsTimelineProperties()
            trajanje = float(p.get("trajanje") or 0)
            t.start_time = timedelta(0); t.min_seek_time = timedelta(0)
            t.end_time = timedelta(seconds=trajanje); t.max_seek_time = timedelta(seconds=trajanje)
            t.position = timedelta(seconds=min(float(p.get("polozaj") or 0), trajanje if trajanje else 1e9))
            self._smtc.update_timeline_properties(t)
        except Exception as e:
            _log.debug("SMTC casovnica: %s", e)

    # ---- gumbi iz sistema (GUI nit prek signala) ----
    def _ukaz(self, kaj: str) -> None:
        pg = self.pogon
        if pg is None:
            return
        try:
            p = self._zadnji
            st = _status(p)
            if kaj == "play":
                if st == "Stopped" and int(p.get("nSeznam") or 0):
                    pg.predvajaj(max(0, int(p.get("indeks", 0))))
                elif st == "Paused":
                    pg.premor()
            elif kaj == "pause":
                if st == "Playing":
                    pg.premor()
            elif kaj == "stop":
                pg.ustavi()
            elif kaj == "next":
                pg.naslednja()
            elif kaj == "previous":
                pg.prejsnja()
            _log.info("SMTC gumb: %s", kaj)
        except Exception as e:
            _log.warning("SMTC ukaz %s: %s", kaj, e)
