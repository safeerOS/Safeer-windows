"""MPRIS2 (Linux, D-Bus seja) za Safeer predvajalnik in Medijski center: medijske tipke na tipkovnici,
zvočni aplet namizja (Cinnamon/GNOME/KDE), playerctl. Windows: ta modul se ne uporablja (SMTC posebej).

Uporaba (GUI nit):
    mpris = SafeerMpris(pogon, ime="Safeer Predvajalnik", okno=okno)   # ime storitve org.mpris.MediaPlayer2.safeer
    ... ob vsakem sporocilu pogona: mpris.ob_podatkih(p)
    ... ob zaprtju: mpris.zapri()
Ce D-Bus ni na voljo (ni seje, ni QtDBus), je objekt neaktiven (`mpris.aktiven == False`), brez napake.

Omejitev: `mpris:length` je v QVariantMap celo stevilo (`i`), dokler ne preseze 2^31 µs (~35 min), potem
`x`; PySide6 QDBusArgument nima operatorja za vsiljen qlonglong. Odjemalci to prenasajo (Position je `x`).
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional

_log = logging.getLogger("safeer.mpris")

_OBJEKT = "/org/mpris/MediaPlayer2"
_IFACE_OSNOVA = "org.mpris.MediaPlayer2"
_IFACE_PRED = "org.mpris.MediaPlayer2.Player"
_SHEME = ["file", "http", "https"]
_MIME = ["video/mp4", "video/x-matroska", "video/webm", "video/mpeg", "video/x-msvideo", "video/quicktime",
         "audio/mpeg", "audio/flac", "audio/ogg", "audio/x-wav", "audio/mp4", "application/dash+xml",
         "application/vnd.apple.mpegurl"]


def na_voljo() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    if not (os.environ.get("DBUS_SESSION_BUS_ADDRESS") or os.path.exists(os.path.join(os.environ.get("XDG_RUNTIME_DIR", ""), "bus"))):
        return False
    try:
        from PySide6 import QtDBus  # noqa: F401
        return True
    except Exception:
        return False


def _status(p: dict) -> str:
    s = (p or {}).get("stanje")
    return "Playing" if s == "predvaja" else ("Paused" if s == "premor" else "Stopped")


def _url(uri: str) -> str:
    if not uri:
        return ""
    if "://" in uri:
        return uri
    from urllib.parse import quote
    return "file://" + quote(uri)


class SafeerMpris:
    def __init__(self, pogon, ime: str = "Safeer Predvajalnik", okno=None, storitev: str = "safeer"):
        self.pogon = pogon
        self.ime = ime
        self.okno = okno
        self.aktiven = False
        self._zadnji: dict = {}
        self._zadnji_kljuc = None
        self._koren = None
        self._bus = None
        self._storitev = ""
        if not na_voljo():
            return
        try:
            self._zazeni(storitev)
        except Exception as e:
            _log.warning("MPRIS ni na voljo: %s", e)
            self.aktiven = False

    # ---- zagon ----
    def _zazeni(self, storitev: str) -> None:
        from PySide6.QtCore import QObject
        from PySide6.QtDBus import QDBusConnection
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            raise RuntimeError("ni D-Bus seje")
        koren = QObject()
        koren._osnova = _Osnova(koren, self)
        koren._pred = _Predvajalnik(koren, self)
        if not bus.registerObject(_OBJEKT, koren, QDBusConnection.RegisterOption.ExportAdaptors):
            raise RuntimeError("registerObject ni uspel")
        ime = f"org.mpris.MediaPlayer2.{storitev}"
        if not bus.registerService(ime):
            ime = f"org.mpris.MediaPlayer2.{storitev}.instance{os.getpid()}"
            if not bus.registerService(ime):
                raise RuntimeError("registerService ni uspel")
        self._koren, self._bus, self._storitev = koren, bus, ime
        self.aktiven = True
        _log.info("MPRIS: %s", ime)

    def zapri(self) -> None:
        if not self.aktiven:
            return
        try:
            self._bus.unregisterService(self._storitev)
            self._bus.unregisterObject(_OBJEKT)
        except Exception:
            pass
        self.aktiven = False

    # ---- stanje iz pogona (GUI nit) ----
    def ob_podatkih(self, p: dict) -> None:
        if not self.aktiven or not p:
            return
        prej = self._zadnji
        self._zadnji = dict(p)
        kljuc = (_status(p), p.get("uri"), p.get("naslov"), int(float(p.get("trajanje") or 0)), int(p.get("glasnost") or 0), round(float(p.get("hitrost") or 1), 2))
        if kljuc == self._zadnji_kljuc:
            return
        sprem = {}
        if kljuc[0] != (self._zadnji_kljuc or (None,))[0]:
            sprem["PlaybackStatus"] = kljuc[0]
        if self._zadnji_kljuc is None or kljuc[1:4] != self._zadnji_kljuc[1:4]:
            sprem["Metadata"] = self.metadata()
        if self._zadnji_kljuc is None or kljuc[4] != self._zadnji_kljuc[4]:
            sprem["Volume"] = kljuc[4] / 100.0
        if self._zadnji_kljuc is None or kljuc[5] != self._zadnji_kljuc[5]:
            sprem["Rate"] = kljuc[5]
        self._zadnji_kljuc = kljuc
        if prej.get("uri") != p.get("uri") or sprem.get("PlaybackStatus"):
            sprem.setdefault("CanGoNext", self.lahko_naprej()); sprem.setdefault("CanGoPrevious", self.lahko_nazaj())
        self._oddaj_spremembe(sprem)

    def _oddaj_spremembe(self, sprem: dict, iface: str = _IFACE_PRED) -> None:
        if not sprem or not self.aktiven:
            return
        try:
            from PySide6.QtDBus import QDBusMessage
            msg = QDBusMessage.createSignal(_OBJEKT, "org.freedesktop.DBus.Properties", "PropertiesChanged")
            msg.setArguments([iface, sprem, []])
            self._bus.send(msg)
        except Exception as e:
            _log.debug("PropertiesChanged: %s", e)

    def oddaj_seeked(self) -> None:
        if self.aktiven:
            try:
                self._koren._pred.Seeked.emit(self.polozaj_us())
            except Exception:
                pass

    # ---- vrednosti ----
    def metadata(self) -> dict:
        p = self._zadnji
        from PySide6.QtDBus import QDBusObjectPath
        d = {"mpris:trackid": QDBusObjectPath(f"/si/safeer/predvajalnik/track/{max(0, int(p.get('indeks', 0) or 0))}")}
        if p.get("naslov"):
            d["xesam:title"] = str(p["naslov"])
        if p.get("uri"):
            d["xesam:url"] = _url(str(p["uri"]))
        t = float(p.get("trajanje") or 0)
        if t > 0:
            d["mpris:length"] = int(t * 1_000_000)
        return d

    def polozaj_us(self) -> int:
        return int(float(self._zadnji.get("polozaj") or 0) * 1_000_000)

    def lahko_naprej(self) -> bool:
        p = self._zadnji; return int(p.get("indeks", -1)) + 1 < int(p.get("nSeznam") or 0)

    def lahko_nazaj(self) -> bool:
        return int(self._zadnji.get("indeks", -1)) > 0

    # ---- ukazi (klice D-Bus v GUI niti) ----
    def _ukaz(self, kaj: str, *a) -> None:
        pg = self.pogon
        if pg is None:
            return
        try:
            p = self._zadnji
            if kaj == "playpause":
                if _status(p) == "Stopped" and int(p.get("nSeznam") or 0):
                    pg.predvajaj(max(0, int(p.get("indeks", 0))))
                else:
                    pg.premor()
            elif kaj == "play":
                if _status(p) == "Stopped" and int(p.get("nSeznam") or 0):
                    pg.predvajaj(max(0, int(p.get("indeks", 0))))
                elif _status(p) == "Paused":
                    pg.premor()
            elif kaj == "pause":
                if _status(p) == "Playing":
                    pg.premor()
            elif kaj == "stop":
                pg.ustavi()
            elif kaj == "next":
                pg.naslednja()
            elif kaj == "previous":
                pg.prejsnja()
            elif kaj == "seek":
                pg.skok(float(a[0]) / 1_000_000); self.oddaj_seeked()
            elif kaj == "setposition":
                t = float(p.get("trajanje") or 0)
                if t > 0:
                    pg.pojdi_na(max(0.0, min(1.0, float(a[0]) / 1_000_000 / t))); self.oddaj_seeked()
            elif kaj == "openuri":
                uri = str(a[0])
                if uri.startswith("file://"):
                    from urllib.parse import unquote, urlparse
                    uri = unquote(urlparse(uri).path)
                if uri.startswith(("http://", "https://")) or os.path.isfile(uri):
                    pg.dodaj(uri, predvajaj=True)
            elif kaj == "volume":
                pg.nastavi_glasnost(int(round(max(0.0, min(1.0, float(a[0]))) * 100)))
            elif kaj == "rate":
                pg.nastavi_hitrost(max(0.25, min(4.0, float(a[0]))))
            elif kaj == "raise":
                if self.okno is not None:
                    self.okno.showNormal() if self.okno.isMinimized() else None
                    self.okno.raise_(); self.okno.activateWindow()
            elif kaj == "quit":
                if self.okno is not None:
                    self.okno.close()
        except Exception as e:
            _log.warning("MPRIS ukaz %s: %s", kaj, e)


if sys.platform.startswith("linux"):
    try:
        from PySide6.QtCore import ClassInfo, Property, Signal, Slot
        from PySide6.QtDBus import QDBusAbstractAdaptor, QDBusObjectPath

        @ClassInfo({"D-Bus Interface": _IFACE_OSNOVA})
        class _Osnova(QDBusAbstractAdaptor):
            def __init__(self, parent, lastnik: SafeerMpris):
                super().__init__(parent); self._l = lastnik

            @Slot()
            def Raise(self): self._l._ukaz("raise")
            @Slot()
            def Quit(self): self._l._ukaz("quit")
            CanQuit = Property(bool, lambda self: self._l.okno is not None, constant=True)
            CanRaise = Property(bool, lambda self: self._l.okno is not None, constant=True)
            HasTrackList = Property(bool, lambda self: False, constant=True)
            Identity = Property(str, lambda self: self._l.ime, constant=True)
            DesktopEntry = Property(str, lambda self: "safeer-predvajalnik", constant=True)
            SupportedUriSchemes = Property("QStringList", lambda self: list(_SHEME), constant=True)
            SupportedMimeTypes = Property("QStringList", lambda self: list(_MIME), constant=True)

        @ClassInfo({"D-Bus Interface": _IFACE_PRED})
        class _Predvajalnik(QDBusAbstractAdaptor):
            Seeked = Signal("qlonglong")

            def __init__(self, parent, lastnik: SafeerMpris):
                super().__init__(parent); self._l = lastnik

            @Slot()
            def PlayPause(self): self._l._ukaz("playpause")
            @Slot()
            def Play(self): self._l._ukaz("play")
            @Slot()
            def Pause(self): self._l._ukaz("pause")
            @Slot()
            def Stop(self): self._l._ukaz("stop")
            @Slot()
            def Next(self): self._l._ukaz("next")
            @Slot()
            def Previous(self): self._l._ukaz("previous")
            @Slot("qlonglong")
            def Seek(self, us): self._l._ukaz("seek", us)
            @Slot(QDBusObjectPath, "qlonglong")
            def SetPosition(self, _tid, us): self._l._ukaz("setposition", us)
            @Slot(str)
            def OpenUri(self, uri): self._l._ukaz("openuri", uri)

            PlaybackStatus = Property(str, lambda self: _status(self._l._zadnji))
            Metadata = Property("QVariantMap", lambda self: self._l.metadata())
            Position = Property("qlonglong", lambda self: self._l.polozaj_us())
            Volume = Property(float, lambda self: float(self._l._zadnji.get("glasnost") or 0) / 100.0,
                              lambda self, v: self._l._ukaz("volume", v))
            Rate = Property(float, lambda self: float(self._l._zadnji.get("hitrost") or 1.0),
                            lambda self, v: self._l._ukaz("rate", v))
            MinimumRate = Property(float, lambda self: 0.25, constant=True)
            MaximumRate = Property(float, lambda self: 4.0, constant=True)
            CanPlay = Property(bool, lambda self: True, constant=True)
            CanPause = Property(bool, lambda self: True, constant=True)
            CanSeek = Property(bool, lambda self: True, constant=True)
            CanControl = Property(bool, lambda self: True, constant=True)
            CanGoNext = Property(bool, lambda self: self._l.lahko_naprej())
            CanGoPrevious = Property(bool, lambda self: self._l.lahko_nazaj())
    except Exception as _e:  # QtDBus manjka
        _log.debug("QtDBus ni na voljo: %s", _e)
