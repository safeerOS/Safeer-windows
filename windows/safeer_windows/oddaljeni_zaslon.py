"""Odjemalec oddaljenega namizja Safeer Link za Windows."""

from __future__ import annotations

import hashlib
import json
import socket
import ssl
import threading
from typing import Optional

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from .oddaljeni_zaslon_protokol import (
    NAJVECJI_OKVIR, OKVIR_OBVESTILO, OKVIR_SLIKA, OKVIR_ZVOK,
    RazclenjevalnikOkvirjev, Seja, ZavrnjenaSeja, preslikaj_tipko_ime,
    je_igra,
    razcleni_odgovor,
)

_QT_IMENA = {
    int(Qt.Key.Key_Up): "up", int(Qt.Key.Key_Down): "down",
    int(Qt.Key.Key_Left): "left", int(Qt.Key.Key_Right): "right",
    int(Qt.Key.Key_Return): "return", int(Qt.Key.Key_Enter): "enter",
    int(Qt.Key.Key_Escape): "escape", int(Qt.Key.Key_Backspace): "backspace",
    int(Qt.Key.Key_Delete): "delete", int(Qt.Key.Key_Tab): "tab",
    int(Qt.Key.Key_Space): "space", int(Qt.Key.Key_PageUp): "pageup",
    int(Qt.Key.Key_PageDown): "pagedown", int(Qt.Key.Key_Home): "home",
    int(Qt.Key.Key_End): "end", int(Qt.Key.Key_Control): "control",
    int(Qt.Key.Key_Alt): "alt", int(Qt.Key.Key_Shift): "shift", int(Qt.Key.Key_Meta): "meta",
    **{int(Qt.Key.Key_F1) + i: f"f{i + 1}" for i in range(12)},
}

# Besedila okna oddaljenega zaslona (jezik nastavi Safeer OS z nastavi_jezik()).
_BESEDILA = {
    "sl": {"naslov": "Oddaljeni zaslon – {ime}", "pripravljam": "Pripravljam povezavo ...", "znova": "Poveži znova",
           "cel": "Celozaslonsko", "okno": "V okno", "dovoljenje": "Napravo prosim za dovoljenje ...",
           "povezujem": "Povezujem se ...", "povezano": "Povezano", "prekinjeno": "Povezava se je prekinila.",
           "koncala": "Naprava je končala povezavo."},
    "en": {"naslov": "Remote screen – {ime}", "pripravljam": "Preparing the connection ...", "znova": "Reconnect",
           "cel": "Full screen", "okno": "Window", "dovoljenje": "Asking the device for permission ...",
           "povezujem": "Connecting ...", "povezano": "Connected", "prekinjeno": "The connection was interrupted.",
           "koncala": "The device ended the connection."},
    "de": {"naslov": "Entfernter Bildschirm – {ime}", "pripravljam": "Verbindung wird vorbereitet ...", "znova": "Neu verbinden",
           "cel": "Vollbild", "okno": "Fenster", "dovoljenje": "Gerät wird um Erlaubnis gebeten ...",
           "povezujem": "Verbinde ...", "povezano": "Verbunden", "prekinjeno": "Die Verbindung wurde unterbrochen.",
           "koncala": "Das Gerät hat die Verbindung beendet."},
    "es": {"naslov": "Pantalla remota – {ime}", "pripravljam": "Preparando la conexión ...", "znova": "Reconectar",
           "cel": "Pantalla completa", "okno": "Ventana", "dovoljenje": "Pidiendo permiso al dispositivo ...",
           "povezujem": "Conectando ...", "povezano": "Conectado", "prekinjeno": "La conexión se interrumpió.",
           "koncala": "El dispositivo terminó la conexión."},
    "fr": {"naslov": "Écran distant – {ime}", "pripravljam": "Préparation de la connexion ...", "znova": "Reconnecter",
           "cel": "Plein écran", "okno": "Fenêtre", "dovoljenje": "Demande d’autorisation à l’appareil ...",
           "povezujem": "Connexion ...", "povezano": "Connecté", "prekinjeno": "La connexion a été interrompue.",
           "koncala": "L’appareil a mis fin à la connexion."},
    "it": {"naslov": "Schermo remoto – {ime}", "pripravljam": "Preparazione della connessione ...", "znova": "Riconnetti",
           "cel": "Schermo intero", "okno": "Finestra", "dovoljenje": "Richiesta di autorizzazione al dispositivo ...",
           "povezujem": "Connessione ...", "povezano": "Connesso", "prekinjeno": "La connessione si è interrotta.",
           "koncala": "Il dispositivo ha chiuso la connessione."},
}
_JEZIK = "sl"


def nastavi_jezik(jezik: str) -> None:
    global _JEZIK
    k = str(jezik or "")[:2].lower()
    _JEZIK = k if k in _BESEDILA else "en"


def _b(kljuc: str, **zamenjave) -> str:
    besedilo = _BESEDILA.get(_JEZIK, _BESEDILA["en"]).get(kljuc) or _BESEDILA["en"][kljuc]
    return besedilo.format(**zamenjave) if zamenjave else besedilo



def _stevilo(vrednost) -> int:
    """Qt enum/flag v int. PySide6 6.11 ne dovoli int() na KeyboardModifier (TypeError) - zato je bila
    tipkovnica v oddaljenem zaslonu mrtva: vsak pritisk je padel, preden je bil poslan."""
    try:
        return int(vrednost)
    except TypeError:
        return int(getattr(vrednost, "value", 0) or 0)


def preslikaj_tipko(koda: int, besedilo: str = "", dol: bool = True,
                    modifikatorji: int = 0) -> Optional[dict]:
    """Prevede Qt tipko v strogo omejen dogodek povratnega vnosa."""
    koda = _stevilo(koda)
    ime = _QT_IMENA.get(koda, "")
    if int(Qt.Key.Key_A) <= koda <= int(Qt.Key.Key_Z):
        ime = chr(ord("a") + koda - int(Qt.Key.Key_A))
    elif int(Qt.Key.Key_0) <= koda <= int(Qt.Key.Key_9):
        ime = chr(ord("0") + koda - int(Qt.Key.Key_0))
    ctrl_alt = _stevilo(Qt.KeyboardModifier.ControlModifier) | _stevilo(Qt.KeyboardModifier.AltModifier)
    return preslikaj_tipko_ime(ime, besedilo, dol, bool(_stevilo(modifikatorji) & ctrl_alt))


class _TokSignali(QObject):
    slika = Signal(QImage)
    stanje = Signal(str, str)
    mere = Signal(int, int)


class _DekodirnaNit(threading.Thread):
    def __init__(self, seja: Seja, signali: _TokSignali):
        super().__init__(name="safeer-oddaljeni-zaslon", daemon=True)
        self.seja = seja
        self.signali = signali
        self._tece = threading.Event()
        self._tece.set()
        self._vticnica: Optional[ssl.SSLSocket] = None
        self._pisalo = threading.Lock()
        # Prikaz sme zaostajati za dekodiranjem, nikoli pa se ne sme nabirati: dokler okno prejsnje slike
        # se ni narisalo, naslednjo sliko samo dekodiramo (H.264 jo potrebuje) in je ne pretvarjamo.
        # Prej je pri igrah (60 slik/s) pretvorba v BGRA zaostala in slika je obvisela, igra pa je tekla.
        self.prikaz_prost = threading.Event()
        self.prikaz_prost.set()

    def ustavi(self) -> None:
        self._tece.clear()
        if self._vticnica is not None:
            try:
                self._vticnica.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._vticnica.close()
            except OSError:
                pass

    def poslji(self, dogodek: dict) -> None:
        vticnica = self._vticnica
        if vticnica is None or not self._tece.is_set():
            return
        podatki = (json.dumps(dogodek, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            with self._pisalo:
                vticnica.sendall(podatki)
        except OSError as exc:
            self.signali.stanje.emit("napaka", str(exc) or _b("prekinjeno"))
            self.ustavi()

    @staticmethod
    def _vrstica(vhod, meja: int = 4096) -> bytes:
        vrstica = vhod.readline(meja + 1)
        if not vrstica.endswith(b"\n") or len(vrstica) > meja:
            raise ValueError("Neveljavna glava oddaljenega zaslona.")
        return vrstica[:-1]

    def run(self) -> None:
        try:
            self.signali.stanje.emit("povezujem", _b("povezujem"))
            goli = socket.create_connection((self.seja.naslov, self.seja.vrata), timeout=8)
            goli.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            kontekst = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            kontekst.minimum_version = ssl.TLSVersion.TLSv1_2
            kontekst.check_hostname = False
            kontekst.verify_mode = ssl.CERT_NONE
            tls = kontekst.wrap_socket(goli, server_hostname=self.seja.naslov)
            dejanski = hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest()
            if dejanski != self.seja.odtis:
                tls.close()
                raise ssl.SSLError("Odtis potrdila se ne ujema.")
            tls.settimeout(10)
            self._vticnica = tls
            tls.sendall(("SAFEER-ZASLON " + self.seja.zeton + "\n").encode("utf-8"))
            vhod = tls.makefile("rb", buffering=0)
            glava = json.loads(self._vrstica(vhod).decode("utf-8"))
            sirina, visina = int(glava.get("w") or 0), int(glava.get("h") or 0)
            if sirina <= 0 or visina <= 0:
                raise ValueError("Naprava je poslala neveljavne mere slike.")
            self.signali.mere.emit(sirina, visina)
            self.signali.stanje.emit("tece", _b("povezano"))

            import av
            dekoder = av.CodecContext.create("h264", "r")
            try:
                dekoder.thread_type = "AUTO"
            except Exception:
                pass
            while self._tece.is_set():
                glava_okvirja = vhod.read(5)
                if not glava_okvirja:
                    break
                while len(glava_okvirja) < 5:
                    kos = vhod.read(5 - len(glava_okvirja))
                    if not kos:
                        raise ConnectionError("Povezava se je prekinila.")
                    glava_okvirja += kos
                vrsta = glava_okvirja[0]
                dolzina = int.from_bytes(glava_okvirja[1:], "big")
                if dolzina <= 0 or dolzina > NAJVECJI_OKVIR:
                    raise ValueError("Pokvarjen okvir oddaljenega zaslona.")
                telo = bytearray()
                while len(telo) < dolzina:
                    kos = vhod.read(dolzina - len(telo))
                    if not kos:
                        raise ConnectionError("Povezava se je prekinila.")
                    telo.extend(kos)
                if vrsta == OKVIR_OBVESTILO:
                    obvestilo = json.loads(bytes(telo).decode("utf-8"))
                    if obvestilo.get("konec"):
                        raise ConnectionError(str(obvestilo["konec"]))
                elif vrsta == OKVIR_SLIKA:
                    for paket in dekoder.parse(bytes(telo)):
                        for okvir in dekoder.decode(paket):
                            if not self.prikaz_prost.is_set():
                                continue
                            self.prikaz_prost.clear()
                            # Brez numpy (ni ga na vseh racunalnikih): surova ravnina BGRA iz PyAV.
                            bgra = okvir.reformat(format="bgra")
                            ravnina = bgra.planes[0]
                            podatki = bytes(ravnina)
                            slika = QImage(podatki, bgra.width, bgra.height,
                                           int(ravnina.line_size), QImage.Format.Format_ARGB32).copy()
                            self.signali.slika.emit(slika)
            if self._tece.is_set():
                raise ConnectionError(_b("koncala"))
        except Exception as exc:
            if self._tece.is_set():
                self.signali.stanje.emit("napaka", str(exc) or _b("prekinjeno"))
        finally:
            self.ustavi()


class _Slika(QOpenGLWidget):
    def __init__(self, poslji, parent=None):
        super().__init__(parent)
        self._poslji = poslji
        self._ob_prikazu = None
        self._slika = QImage()
        self._mere = (1, 1)
        self._cilj = QRectF()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def nastavi_sliko(self, slika: QImage) -> None:
        self._slika = slika
        self.update()
        if self._ob_prikazu is not None:
            self._ob_prikazu()

    def nastavi_mere(self, sirina: int, visina: int) -> None:
        self._mere = (sirina, visina)

    def paintGL(self) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#05070b"))
        if self._slika.isNull():
            self._cilj = QRectF()
            return
        iw, ih = self._slika.width(), self._slika.height()
        faktor = min(self.width() / iw, self.height() / ih)
        w, h = iw * faktor, ih * faktor
        self._cilj = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.drawImage(self._cilj, self._slika)

    def _tocka(self, dogodek: QMouseEvent) -> Optional[tuple[int, int]]:
        if self._cilj.isEmpty() or not self._cilj.contains(dogodek.position()):
            return None
        x = (dogodek.position().x() - self._cilj.left()) * self._mere[0] / self._cilj.width()
        y = (dogodek.position().y() - self._cilj.top()) * self._mere[1] / self._cilj.height()
        return int(x), int(y)

    def mouseMoveEvent(self, dogodek: QMouseEvent) -> None:
        tocka = self._tocka(dogodek)
        if tocka:
            self._poslji({"vrsta": "tocka", "x": tocka[0], "y": tocka[1]})

    def mousePressEvent(self, dogodek: QMouseEvent) -> None:
        self.setFocus()
        tocka = self._tocka(dogodek)
        if tocka:
            self._poslji({"vrsta": "tocka", "x": tocka[0], "y": tocka[1]})
        gumb = "desni" if dogodek.button() == Qt.MouseButton.RightButton else "levi"
        self._poslji({"vrsta": "gumb", "gumb": gumb, "dol": True})

    def mouseReleaseEvent(self, dogodek: QMouseEvent) -> None:
        gumb = "desni" if dogodek.button() == Qt.MouseButton.RightButton else "levi"
        self._poslji({"vrsta": "gumb", "gumb": gumb, "dol": False})

    def wheelEvent(self, dogodek: QWheelEvent) -> None:
        koraki = dogodek.angleDelta().y() / 120
        if koraki:
            self._poslji({"vrsta": "kolesce", "smer": "gor" if koraki > 0 else "dol",
                          "koliko": min(10, max(1, int(abs(koraki))))})

    def keyPressEvent(self, dogodek: QKeyEvent) -> None:
        if dogodek.isAutoRepeat():
            return
        vnos = preslikaj_tipko(dogodek.key(), dogodek.text(), True, _stevilo(dogodek.modifiers()))
        if vnos:
            self._poslji(vnos)

    def keyReleaseEvent(self, dogodek: QKeyEvent) -> None:
        if dogodek.isAutoRepeat():
            return
        vnos = preslikaj_tipko(dogodek.key(), dogodek.text(), False, _stevilo(dogodek.modifiers()))
        if vnos:
            self._poslji(vnos)


class OddaljeniZaslon(QWidget):
    """Samostojno okno gledalca z zagonom seje prek Safeer Linka."""

    def __init__(self, backend, id_naprave: str, ime: str, naprava: Optional[dict] = None,
                 zaslon: str = "desktop"):
        super().__init__(None)
        self.backend = backend
        # "desktop" = celo namizje (Upravljaj ta racunalnik); "apps" = locen zaslon, kjer tecejo programi,
        # odprti od tu (kot na televizorju) - uporabnik vidi program, ne svojega namizja.
        self.zaslon_cilj = zaslon if zaslon in ("desktop", "apps") else "desktop"
        self.id_naprave = id_naprave
        self.ime = ime or id_naprave
        self.naprava = naprava or self._poisci_napravo()
        self._nit: Optional[_DekodirnaNit] = None
        self._zapiram = False
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(_b("naslov", ime=self.ime))
        self.resize(1280, 760)

        self.signali = _TokSignali(self)
        self.slika = _Slika(self._poslji, self)
        self.stanje = QLabel(_b("pripravljam"))
        self.stanje.setStyleSheet("color:#d8e2f0;padding:8px;background:#111827")
        self.znova = QPushButton(_b("znova"))
        self.znova.clicked.connect(self.povezi)
        self.znova.hide()
        self.cel = QPushButton(_b("cel"))
        self.cel.clicked.connect(self._preklopi_celozaslonsko)
        pas = QHBoxLayout()
        pas.addWidget(self.stanje, 1)
        pas.addWidget(self.znova)
        pas.addWidget(self.cel)
        postavitev = QVBoxLayout(self)
        postavitev.setContentsMargins(0, 0, 0, 0)
        postavitev.setSpacing(0)
        postavitev.addLayout(pas)
        postavitev.addWidget(self.slika, 1)
        self.signali.slika.connect(self.slika.nastavi_sliko)
        self.signali.mere.connect(self.slika.nastavi_mere)
        self.signali.stanje.connect(self._spremeni_stanje)
        QTimer.singleShot(0, self.povezi)

    def _poisci_napravo(self) -> dict:
        return next((n for n in self.backend.naprave if n.get("id") == self.id_naprave), {})

    def povezi(self) -> None:
        if self._nit is not None:
            self._nit.ustavi()
        self.znova.hide()
        self.stanje.setText(_b("dovoljenje"))

        def zahteva() -> None:
            try:
                odgovor = self.backend.ukaz_pocakaj(
                    self.id_naprave, "screen.start", {"quality": "najvisja", "screen": self.zaslon_cilj}, cas=15.0)
                seja = razcleni_odgovor(odgovor, self.naprava or self._poisci_napravo())
                self._igra = je_igra(odgovor)
                if self._zapiram:
                    self.backend.ukaz_pocakaj(self.id_naprave, "screen.stop", {}, cas=5.0)
                    return
                nit = _DekodirnaNit(seja, self.signali)
                self.slika._ob_prikazu = nit.prikaz_prost.set
                self._nit = nit
                nit.start()
            except Exception as exc:
                if not self._zapiram:
                    self.signali.stanje.emit("napaka", str(exc))
        threading.Thread(target=zahteva, name="safeer-screen-start", daemon=True).start()

    def _poslji(self, dogodek: dict) -> None:
        if self._nit is not None:
            self._nit.poslji(dogodek)

    def _spremeni_stanje(self, stanje: str, sporocilo: str) -> None:
        self.stanje.setText(sporocilo)
        self.znova.setVisible(stanje == "napaka")
        if stanje == "tece":
            self.slika.setFocus()
            # Igra na drugem racunalniku: takoj cez cel zaslon, kot na televizorju (gumb "V okno" vrne okno).
            if getattr(self, "_igra", False) and not self._je_celozaslonsko():
                self._preklopi_celozaslonsko()

    def _je_celozaslonsko(self) -> bool:
        return bool(getattr(self, "_celozaslonsko", False))

    def _preklopi_celozaslonsko(self) -> None:
        """Celozaslonsko brez showFullScreen(): okno z OpenGL ploscico, ki natanko pokrije zaslon, Windows
        (DWM) preklopi v izkljucni celozaslonski nacin - okno je zmrznilo na "Povezujem se ..." z belimi
        robovi. Brezrobno okno, eno slikovno piko visje od zaslona, ostane v obicajnem sestavljanju."""
        if self._je_celozaslonsko():
            self._celozaslonsko = False
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, False)
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
            self.showMaximized()
            self.cel.setText(_b("cel"))
            return
        zaslon = self.screen() or QApplication.primaryScreen()
        g = zaslon.geometry()
        self._celozaslonsko = True
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.showNormal()
        self.setGeometry(g.x(), g.y(), g.width(), g.height() + 1)
        self.show()
        self.cel.setText(_b("okno"))

    def closeEvent(self, dogodek) -> None:
        self._zapiram = True
        if self._nit is not None:
            self._nit.ustavi()
        threading.Thread(target=lambda: self.backend.ukaz_pocakaj(
            self.id_naprave, "screen.stop", {}, cas=5.0), name="safeer-screen-stop", daemon=True).start()
        dogodek.accept()


_ODPRTA_OKNA: set[OddaljeniZaslon] = set()


def odpri(backend, id_naprave: str, ime: str = "", zaslon: str = "desktop") -> OddaljeniZaslon:
    naprava = next((n for n in backend.naprave if n.get("id") == id_naprave), {})
    okno = OddaljeniZaslon(backend, id_naprave, ime or naprava.get("ime") or naprava.get("name") or id_naprave,
                           naprava, zaslon=zaslon)
    _ODPRTA_OKNA.add(okno)
    okno.destroyed.connect(lambda: _ODPRTA_OKNA.discard(okno))
    okno.showMaximized()
    okno.raise_()
    okno.activateWindow()
    return okno


__all__ = ["OddaljeniZaslon", "RazclenjevalnikOkvirjev", "Seja", "ZavrnjenaSeja",
           "odpri", "preslikaj_tipko", "razcleni_odgovor"]
