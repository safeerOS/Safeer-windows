"""Odjemalec oddaljenega namizja Safeer Link za Windows."""

from __future__ import annotations

import json
import socket
import threading
from typing import Optional

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from .oddaljeni_zaslon_povezava import NiDosegljiva, PovezavaGledalca, PrekinjenaPovezava
from .oddaljeni_zaslon_protokol import (
    OKVIR_OBVESTILO, OKVIR_SLIKA,
    RazclenjevalnikOkvirjev, Seja, ZavrnjenaSeja, preslikaj_tipko_ime,
    obvestilo_naprave, parametri_zacetka,
    ima_naslov,
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
           "koncala": "Naprava je končala povezavo.",
           "ni_doma": "{ime} zdaj ni dosegljiv neposredno. Slika zaslona deluje samo v istem omrežju (doma), "
                      "prek Global Linka ne.",
           "ni_dosegljiv": "{ime} ni dosegljiv. Preveri, ali sta obe napravi v istem omrežju.",
           "odpiram": "Odpiram {program} ...", "odpiram_brez": "Odpiram program ...",
           "na_namizju": "{program} je že odprt na namizju računalnika – prikazujem namizje ...",
           "na_namizju_brez": "Program je že odprt na namizju računalnika – prikazujem namizje ...",
           "ni_okna": "Program se na računalniku ni odprl.", "zaprto": "Program na računalniku je zaprt."},
    "en": {"naslov": "Remote screen – {ime}", "pripravljam": "Preparing the connection ...", "znova": "Reconnect",
           "cel": "Full screen", "okno": "Window", "dovoljenje": "Asking the device for permission ...",
           "povezujem": "Connecting ...", "povezano": "Connected", "prekinjeno": "The connection was interrupted.",
           "koncala": "The device ended the connection.",
           "ni_doma": "{ime} cannot be reached directly right now. Screen viewing works only on the same network "
                      "(at home), not over Global Link.",
           "ni_dosegljiv": "{ime} cannot be reached. Check that both devices are on the same network.",
           "odpiram": "Opening {program} ...", "odpiram_brez": "Opening the program ...",
           "na_namizju": "{program} is already open on the computer's desktop – showing the desktop ...",
           "na_namizju_brez": "The program is already open on the computer's desktop – showing the desktop ...",
           "ni_okna": "The program did not open on the computer.", "zaprto": "The program on the computer was closed."},
    "de": {"naslov": "Entfernter Bildschirm – {ime}", "pripravljam": "Verbindung wird vorbereitet ...", "znova": "Neu verbinden",
           "cel": "Vollbild", "okno": "Fenster", "dovoljenje": "Gerät wird um Erlaubnis gebeten ...",
           "povezujem": "Verbinde ...", "povezano": "Verbunden", "prekinjeno": "Die Verbindung wurde unterbrochen.",
           "koncala": "Das Gerät hat die Verbindung beendet.",
           "ni_doma": "{ime} ist gerade nicht direkt erreichbar. Die Bildschirmansicht funktioniert nur im selben "
                      "Netzwerk (zu Hause), nicht über Global Link.",
           "ni_dosegljiv": "{ime} ist nicht erreichbar. Prüfe, ob beide Geräte im selben Netzwerk sind.",
           "odpiram": "{program} wird geöffnet ...", "odpiram_brez": "Das Programm wird geöffnet ...",
           "na_namizju": "{program} ist auf dem Desktop des Computers bereits geöffnet – der Desktop wird "
                         "angezeigt ...",
           "na_namizju_brez": "Das Programm ist auf dem Desktop des Computers bereits geöffnet – der Desktop wird "
                              "angezeigt ...",
           "ni_okna": "Das Programm hat sich auf dem Computer nicht geöffnet.",
           "zaprto": "Das Programm auf dem Computer wurde geschlossen."},
    "es": {"naslov": "Pantalla remota – {ime}", "pripravljam": "Preparando la conexión ...", "znova": "Reconectar",
           "cel": "Pantalla completa", "okno": "Ventana", "dovoljenje": "Pidiendo permiso al dispositivo ...",
           "povezujem": "Conectando ...", "povezano": "Conectado", "prekinjeno": "La conexión se interrumpió.",
           "koncala": "El dispositivo terminó la conexión.",
           "ni_doma": "{ime} no está accesible directamente en este momento. La vista de pantalla solo funciona en "
                      "la misma red (en casa), no a través de Global Link.",
           "ni_dosegljiv": "{ime} no está accesible. Comprueba que ambos dispositivos estén en la misma red.",
           "odpiram": "Abriendo {program} ...", "odpiram_brez": "Abriendo el programa ...",
           "na_namizju": "{program} ya está abierto en el escritorio del ordenador: mostrando el escritorio ...",
           "na_namizju_brez": "El programa ya está abierto en el escritorio del ordenador: mostrando el escritorio ...",
           "ni_okna": "El programa no se abrió en el ordenador.", "zaprto": "El programa del ordenador se ha cerrado."},
    "fr": {"naslov": "Écran distant – {ime}", "pripravljam": "Préparation de la connexion ...", "znova": "Reconnecter",
           "cel": "Plein écran", "okno": "Fenêtre", "dovoljenje": "Demande d’autorisation à l’appareil ...",
           "povezujem": "Connexion ...", "povezano": "Connecté", "prekinjeno": "La connexion a été interrompue.",
           "koncala": "L’appareil a mis fin à la connexion.",
           "ni_doma": "{ime} n’est pas joignable directement pour le moment. L’affichage de l’écran ne fonctionne "
                      "que sur le même réseau (à la maison), pas via Global Link.",
           "ni_dosegljiv": "{ime} est injoignable. Vérifiez que les deux appareils sont sur le même réseau.",
           "odpiram": "Ouverture de {program} ...", "odpiram_brez": "Ouverture du programme ...",
           "na_namizju": "{program} est déjà ouvert sur le bureau de l’ordinateur – affichage du bureau ...",
           "na_namizju_brez": "Le programme est déjà ouvert sur le bureau de l’ordinateur – affichage du bureau ...",
           "ni_okna": "Le programme ne s’est pas ouvert sur l’ordinateur.",
           "zaprto": "Le programme sur l’ordinateur a été fermé."},
    "it": {"naslov": "Schermo remoto – {ime}", "pripravljam": "Preparazione della connessione ...", "znova": "Riconnetti",
           "cel": "Schermo intero", "okno": "Finestra", "dovoljenje": "Richiesta di autorizzazione al dispositivo ...",
           "povezujem": "Connessione ...", "povezano": "Connesso", "prekinjeno": "La connessione si è interrotta.",
           "koncala": "Il dispositivo ha chiuso la connessione.",
           "ni_doma": "{ime} al momento non è raggiungibile direttamente. La visualizzazione dello schermo funziona "
                      "solo sulla stessa rete (a casa), non tramite Global Link.",
           "ni_dosegljiv": "{ime} non è raggiungibile. Controlla che entrambi i dispositivi siano sulla stessa rete.",
           "odpiram": "Apertura di {program} ...", "odpiram_brez": "Apertura del programma ...",
           "na_namizju": "{program} è già aperto sul desktop del computer – mostro il desktop ...",
           "na_namizju_brez": "Il programma è già aperto sul desktop del computer – mostro il desktop ...",
           "ni_okna": "Il programma non si è aperto sul computer.",
           "zaprto": "Il programma sul computer è stato chiuso."},
}
_JEZIK = "sl"


def nastavi_jezik(jezik: str) -> None:
    global _JEZIK
    k = str(jezik or "")[:2].lower()
    _JEZIK = k if k in _BESEDILA else "en"


def _b(kljuc: str, **zamenjave) -> str:
    besedilo = _BESEDILA.get(_JEZIK, _BESEDILA["en"]).get(kljuc) or _BESEDILA["en"][kljuc]
    return besedilo.format(**zamenjave) if zamenjave else besedilo


def besedilo_obvestila(vrsta: str, razlog: str, program: str = "", sporocilo: str = "") -> str:
    """Obvestilo naprave (oddaljeni_zaslon_protokol.obvestilo_naprave) kot stavek v jeziku uporabnika.

    Prej je okno pokazalo golo oznako naprave (»ni_okna«), ki uporabniku ne pove nicesar."""
    if vrsta == "program":
        if razlog == "caka":
            return _b("odpiram", program=program) if program else _b("odpiram_brez")
        return _b("povezano")
    if razlog == "na_namizju":
        return _b("na_namizju", program=program) if program else _b("na_namizju_brez")
    if razlog in ("ni_okna", "zaprto"):
        return _b(razlog)
    # Neznan razlog: stavek naprave, ce ga je poslala (starejsi ali novejsi racunalnik), sicer splosno »koncala«.
    return sporocilo or _b("koncala")



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
    #: Program, odprt od tu, je na namizju racunalnika (obvestilo "na_namizju"): ime programa ali prazno.
    predaja = Signal(str)


class _DekodirnaNit(threading.Thread):
    def __init__(self, seja: Seja, signali: _TokSignali, ime: str = ""):
        super().__init__(name="safeer-oddaljeni-zaslon", daemon=True)
        self.seja = seja
        self.ime = str(ime or "")
        self.signali = signali
        self._tece = threading.Event()
        self._tece.set()
        # Ta nit bere okvirje, glavna nit okna posilja vnos: povezava mora prenesti obe hkrati
        # (oddaljeni_zaslon_povezava.py). S surovo vticnico TLS se je seja prekinila med premikanjem miske.
        self._povezava = PovezavaGledalca(seja)
        # Prikaz sme zaostajati za dekodiranjem, nikoli pa se ne sme nabirati: dokler okno prejsnje slike
        # se ni narisalo, naslednjo sliko samo dekodiramo (H.264 jo potrebuje) in je ne pretvarjamo.
        # Prej je pri igrah (60 slik/s) pretvorba v BGRA zaostala in slika je obvisela, igra pa je tekla.
        self.prikaz_prost = threading.Event()
        self.prikaz_prost.set()

    def ustavi(self) -> None:
        self._tece.clear()
        self._povezava.zapri()

    def poslji(self, dogodek: dict) -> None:
        if not self._tece.is_set():
            return
        try:
            self._povezava.poslji(dogodek)
        except OSError:
            # Sistemske napake ("[WinError 10054] ...") uporabniku ne povedo nicesar: pokazemo svoj stavek.
            if self._tece.is_set():
                self.signali.stanje.emit("napaka", _b("prekinjeno"))
            self.ustavi()

    def run(self) -> None:
        try:
            self.signali.stanje.emit("povezujem", _b("povezujem"))
            glava = self._povezava.povezi()
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
            for vrsta, telo in self._povezava.okvirji():
                if not self._tece.is_set():
                    break
                if vrsta == OKVIR_OBVESTILO:
                    vrsta_ob, razlog, program, sporocilo = obvestilo_naprave(json.loads(telo.decode("utf-8")))
                    if vrsta_ob == "konec" and razlog == "na_namizju":
                        # Program ene same instance (npr. Claude) je bil ze odprt na namizju racunalnika in se na
                        # locenem zaslonu ni odprl: okno preklopi na namizje (kot televizor), napake ne pokaze.
                        self._tece.clear()
                        self.signali.predaja.emit(program)
                        return
                    if vrsta_ob == "konec":
                        raise ConnectionError(besedilo_obvestila(vrsta_ob, razlog, program, sporocilo))
                    if vrsta_ob == "program":
                        self.signali.stanje.emit("caka" if razlog == "caka" else "tece",
                                                 besedilo_obvestila(vrsta_ob, razlog, program))
                elif vrsta == OKVIR_SLIKA:
                    for paket in dekoder.parse(telo):
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
                # Prekinitev in casovna omejitev dobita nas stavek v jeziku uporabnika (ne "timed out").
                tiho = isinstance(exc, (PrekinjenaPovezava, socket.timeout))
                if isinstance(exc, NiDosegljiva):
                    besedilo = _b("ni_dosegljiv", ime=self.ime or self.seja.naslov)
                else:
                    besedilo = _b("prekinjeno") if tiho else (str(exc) or _b("prekinjeno"))
                self.signali.stanje.emit("napaka", besedilo)
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
        #: Okno je ze preklopilo na namizje (obvestilo "na_namizju"): seja prosi racunalnik, naj okno programa
        #: postavi v ospredje, drugega preklopa pa ni.
        self._predano = False
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
        self.signali.predaja.connect(self._na_namizju)
        QTimer.singleShot(0, self.povezi)

    def _poisci_napravo(self) -> dict:
        return next((n for n in self.backend.naprave if n.get("id") == self.id_naprave), {})

    def povezi(self) -> bool:
        """Zacne sejo; False, kadar je ne moremo (naprava brez naslova - sporocilo je ze na zaslonu)."""
        if self._nit is not None:
            self._nit.ustavi()
        self.znova.hide()
        # Svez zapis iz seznama naprav: okno, odprto zunaj doma, bi sicer za vedno drzalo zapis brez naslova.
        naprava = self._poisci_napravo() or self.naprava or {}
        if not ima_naslov(naprava):
            # Slika gre neposredno z naprave. Brez njenega naslova (dosegljiva je samo prek Global Linka) je ne
            # prosimo: naprava bi zaman odprla vrata in cakala na nas.
            self._spremeni_stanje("napaka", _b("ni_doma", ime=self.ime))
            return False
        self.stanje.setText(_b("dovoljenje"))
        # Kaj zna ta gledalec (handoff); po preklopu na namizje se prosnja, naj racunalnik pokaze okno programa.
        parametri = parametri_zacetka(self.zaslon_cilj, self._predano)

        def zahteva() -> None:
            try:
                odgovor = self.backend.ukaz_pocakaj(self.id_naprave, "screen.start", parametri, cas=15.0)
                seja = razcleni_odgovor(odgovor, naprava)
                self._igra = je_igra(odgovor)
                if self._zapiram:
                    self.backend.ukaz_pocakaj(self.id_naprave, "screen.stop", {}, cas=5.0)
                    return
                nit = _DekodirnaNit(seja, self.signali, self.ime)
                self.slika._ob_prikazu = nit.prikaz_prost.set
                self._nit = nit
                nit.start()
            except Exception as exc:
                if not self._zapiram:
                    self.signali.stanje.emit("napaka", str(exc))
        threading.Thread(target=zahteva, name="safeer-screen-start", daemon=True).start()
        return True

    def _na_namizju(self, program: str) -> None:
        """Program, odprt od tu, se je odprl na namizju racunalnika in ne na locenem zaslonu (program ene same
        instance, npr. Claude ali brskalnik, je bil tam ze odprt). Kot televizor preklopimo na namizje racunalnika,
        ta pa okno programa postavi v ospredje (`handoff` v screen.start). Prej je okno pokazalo »ni_okna«."""
        if self._zapiram or self._predano:
            return
        self._predano = True
        self.zaslon_cilj = "desktop"
        if self.povezi():
            self.stanje.setText(besedilo_obvestila("konec", "na_namizju", program))

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
