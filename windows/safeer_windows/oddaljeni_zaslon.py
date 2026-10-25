"""Odjemalec oddaljenega namizja Safeer Link za Windows."""

from __future__ import annotations

import collections
import json
import socket
import threading
import time
from typing import Optional

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from . import oddaljeni_zaslon_prikaz as prikaz
from .oddaljeni_zaslon_povezava import NiDosegljiva, PovezavaGledalca, PrekinjenaPovezava
from .oddaljeni_zaslon_protokol import (
    OKVIR_OBVESTILO, OKVIR_SLIKA,
    RazclenjevalnikOkvirjev, Seja, ZavrnjenaSeja, preslikaj_tipko_ime,
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
           "ni_dosegljiv": "{ime} ni dosegljiv. Preveri, ali sta obe napravi v istem omrežju."},
    "en": {"naslov": "Remote screen – {ime}", "pripravljam": "Preparing the connection ...", "znova": "Reconnect",
           "cel": "Full screen", "okno": "Window", "dovoljenje": "Asking the device for permission ...",
           "povezujem": "Connecting ...", "povezano": "Connected", "prekinjeno": "The connection was interrupted.",
           "koncala": "The device ended the connection.",
           "ni_doma": "{ime} cannot be reached directly right now. Screen viewing works only on the same network "
                      "(at home), not over Global Link.",
           "ni_dosegljiv": "{ime} cannot be reached. Check that both devices are on the same network."},
    "de": {"naslov": "Entfernter Bildschirm – {ime}", "pripravljam": "Verbindung wird vorbereitet ...", "znova": "Neu verbinden",
           "cel": "Vollbild", "okno": "Fenster", "dovoljenje": "Gerät wird um Erlaubnis gebeten ...",
           "povezujem": "Verbinde ...", "povezano": "Verbunden", "prekinjeno": "Die Verbindung wurde unterbrochen.",
           "koncala": "Das Gerät hat die Verbindung beendet.",
           "ni_doma": "{ime} ist gerade nicht direkt erreichbar. Die Bildschirmansicht funktioniert nur im selben "
                      "Netzwerk (zu Hause), nicht über Global Link.",
           "ni_dosegljiv": "{ime} ist nicht erreichbar. Prüfe, ob beide Geräte im selben Netzwerk sind."},
    "es": {"naslov": "Pantalla remota – {ime}", "pripravljam": "Preparando la conexión ...", "znova": "Reconectar",
           "cel": "Pantalla completa", "okno": "Ventana", "dovoljenje": "Pidiendo permiso al dispositivo ...",
           "povezujem": "Conectando ...", "povezano": "Conectado", "prekinjeno": "La conexión se interrumpió.",
           "koncala": "El dispositivo terminó la conexión.",
           "ni_doma": "{ime} no está accesible directamente en este momento. La vista de pantalla solo funciona en "
                      "la misma red (en casa), no a través de Global Link.",
           "ni_dosegljiv": "{ime} no está accesible. Comprueba que ambos dispositivos estén en la misma red."},
    "fr": {"naslov": "Écran distant – {ime}", "pripravljam": "Préparation de la connexion ...", "znova": "Reconnecter",
           "cel": "Plein écran", "okno": "Fenêtre", "dovoljenje": "Demande d’autorisation à l’appareil ...",
           "povezujem": "Connexion ...", "povezano": "Connecté", "prekinjeno": "La connexion a été interrompue.",
           "koncala": "L’appareil a mis fin à la connexion.",
           "ni_doma": "{ime} n’est pas joignable directement pour le moment. L’affichage de l’écran ne fonctionne "
                      "que sur le même réseau (à la maison), pas via Global Link.",
           "ni_dosegljiv": "{ime} est injoignable. Vérifiez que les deux appareils sont sur le même réseau."},
    "it": {"naslov": "Schermo remoto – {ime}", "pripravljam": "Preparazione della connessione ...", "znova": "Riconnetti",
           "cel": "Schermo intero", "okno": "Finestra", "dovoljenje": "Richiesta di autorizzazione al dispositivo ...",
           "povezujem": "Connessione ...", "povezano": "Connesso", "prekinjeno": "La connessione si è interrotta.",
           "koncala": "Il dispositivo ha chiuso la connessione.",
           "ni_doma": "{ime} al momento non è raggiungibile direttamente. La visualizzazione dello schermo funziona "
                      "solo sulla stessa rete (a casa), non tramite Global Link.",
           "ni_dosegljiv": "{ime} non è raggiungibile. Controlla che entrambi i dispositivi siano sulla stessa rete."},
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
    obvestilo = Signal(dict)


class _Stevci:
    """Kaj gledalec izmeri (vrstica s podatki, odmev pinga izvoru, povzetek seje v dnevniku). Pisejo niti toka,
    berejo glavna nit in odmev - stevila brez kljucavnice zadoscajo (en pisec na polje)."""

    def __init__(self) -> None:
        self.zacetek = time.monotonic()
        self.bajtov = 0
        self.slik = 0               # dekodiranih
        self.prikazanih = 0
        self.izpusceno = 0          # dekodiranih, ki niso prisle na zaslon (prikaz je zaostajal)
        self.zastoji = 0            # premori med slikami nad ZASTOJ_S, ko je tok tekel
        self.zadnja_slika = 0.0
        self.pretvorba_ms = 0.0     # drseče povprecje pretvorbe (in pomanjsevanja) ene slike
        self.rtt: list = []         # zamiki, ki jih izvor sporoci v pingu (z)
        self._okno = collections.deque(maxlen=240)   # (cas, bajtov, prikazanih)

    ZASTOJ_S = 0.25

    def sekunda(self) -> tuple:
        """(fps prikaza, Mb/s) v zadnji sekundi."""
        zdaj = time.monotonic()
        self._okno.append((zdaj, self.bajtov, self.prikazanih))
        while len(self._okno) > 2 and zdaj - self._okno[0][0] > 1.0:
            self._okno.popleft()
        t0, b0, p0 = self._okno[0]
        dt = zdaj - t0
        if dt <= 0.2:
            return 0.0, 0.0
        return (self.prikazanih - p0) / dt, (self.bajtov - b0) * 8 / dt / 1e6


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
        #: Velikost slike za prikaz v fizicnih pikah (glavna nit jo nastavi po platnu); None = izvorna.
        self.cilj: Optional[tuple] = None
        self.stevci = _Stevci()
        self.glava: dict = {}
        # Pretvorba (in pomanjsevanje Lanczos) tece v svoji niti: swscale sprosti GIL, dekoder medtem dekodira naprej.
        self._okvir = None
        self._pogoj = threading.Condition()

    def ustavi(self) -> None:
        self._tece.clear()
        with self._pogoj:
            self._pogoj.notify_all()
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

    def _pretvarjaj(self) -> None:
        """Nit pretvorbe: vedno najnovejsa dekodirana slika, ko je prikaz prost (starejse se izpustijo)."""
        while self._tece.is_set():
            with self._pogoj:
                while self._tece.is_set() and (self._okvir is None or not self.prikaz_prost.is_set()):
                    self._pogoj.wait(0.05)
                if not self._tece.is_set():
                    return
                okvir, self._okvir = self._okvir, None
                self.prikaz_prost.clear()
            zacetek = time.perf_counter()
            cilj = self.cilj
            if cilj and tuple(cilj) != (okvir.width, okvir.height):
                bgra = okvir.reformat(width=int(cilj[0]), height=int(cilj[1]), format="bgra",
                                      interpolation=prikaz.POMANJSEVANJE)
            else:
                bgra = okvir.reformat(format="bgra")
            # Brez numpy (ni ga na vseh racunalnikih): surova ravnina BGRA iz PyAV.
            ravnina = bgra.planes[0]
            slika = QImage(bytes(ravnina), bgra.width, bgra.height,
                           int(ravnina.line_size), QImage.Format.Format_ARGB32).copy()
            ms = (time.perf_counter() - zacetek) * 1000
            st = self.stevci
            st.pretvorba_ms = ms if not st.pretvorba_ms else st.pretvorba_ms * 0.9 + ms * 0.1
            self.signali.slika.emit(slika)

    def _oddaj(self, okvir) -> None:
        with self._pogoj:
            if self._okvir is not None:
                self.stevci.izpusceno += 1
            self._okvir = okvir
            self._pogoj.notify()

    def _odmev(self, ping: dict) -> None:
        st = self.stevci
        fps, mbps = st.sekunda()
        odmev = prikaz.odmev_rtt(ping, {
            "r": int(time.monotonic() * 1000), "b": st.bajtov, "fps": round(fps, 1), "mbps": round(mbps, 2),
            "dek": round(st.pretvorba_ms, 1), "zastoji": st.zastoji, "izpusceno": st.izpusceno,
            "pot": "neposredno" if not st.rtt else None})
        z = ping.get("z") if isinstance(ping, dict) else None
        if isinstance(z, (int, float)) and not isinstance(z, bool) and z > 0:
            st.rtt.append(float(z))
            del st.rtt[:-20000]
        if odmev:
            self.poslji(odmev)

    def run(self) -> None:
        try:
            self.signali.stanje.emit("povezujem", _b("povezujem"))
            glava = self._povezava.povezi()
            self.glava = glava if isinstance(glava, dict) else {}
            sirina, visina = int(glava.get("w") or 0), int(glava.get("h") or 0)
            if sirina <= 0 or visina <= 0:
                raise ValueError("Naprava je poslala neveljavne mere slike.")
            self.signali.mere.emit(sirina, visina)
            self.signali.stanje.emit("tece", _b("povezano"))

            import av
            kodek = "hevc" if str(glava.get("kodek") or "").lower() in ("hevc", "h265") else "h264"
            dekoder = av.CodecContext.create(kodek, "r")
            try:
                dekoder.thread_type = "AUTO"
            except Exception:
                pass
            threading.Thread(target=self._pretvarjaj, name="safeer-oddaljeni-zaslon-pretvorba", daemon=True).start()
            st = self.stevci
            for vrsta, telo in self._povezava.okvirji():
                if not self._tece.is_set():
                    break
                st.bajtov += 5 + len(telo)
                if vrsta == OKVIR_OBVESTILO:
                    obvestilo = json.loads(telo.decode("utf-8"))
                    if not isinstance(obvestilo, dict):
                        continue
                    if obvestilo.get("konec"):
                        raise ConnectionError(str(obvestilo["konec"]))
                    if isinstance(obvestilo.get("rtt"), dict):
                        self._odmev(obvestilo["rtt"])
                        continue
                    self.signali.obvestilo.emit(obvestilo)
                elif vrsta == OKVIR_SLIKA:
                    for paket in dekoder.parse(telo):
                        for okvir in dekoder.decode(paket):
                            zdaj = time.monotonic()
                            if st.zadnja_slika and zdaj - st.zadnja_slika > st.ZASTOJ_S:
                                st.zastoji += 1
                            st.zadnja_slika = zdaj
                            st.slik += 1
                            self._oddaj(okvir)
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
            self._povzetek()

    def _povzetek(self) -> None:
        """Ena vrstica v dnevnik Safeer OS ob koncu seje (meritve na testnem racunalniku, brez kljuca seje)."""
        st = self.stevci
        trajanje = max(0.001, time.monotonic() - st.zacetek)
        if not st.slik:
            return
        med, p95 = prikaz.percentil(st.rtt, 50), prikaz.percentil(st.rtt, 95)
        print("[Gledalec] seja %s: %sx%s %s, %.0f s, dekodiranih %.1f/s, prikazanih %.1f/s, izpusceno %d, zastojev %d, "
              "%.1f Mb/s, pretvorba %.1f ms, zamik mediana %s ms p95 %s ms (%d meritev)"
              % (self.ime, self.glava.get("w"), self.glava.get("h"), self.glava.get("kodek") or "h264", trajanje,
                 st.slik / trajanje, st.prikazanih / trajanje, st.izpusceno, st.zastoji,
                 st.bajtov * 8 / trajanje / 1e6, st.pretvorba_ms,
                 "-" if med is None else "%.0f" % med, "-" if p95 is None else "%.0f" % p95, len(st.rtt)), flush=True)


class _Slika(QOpenGLWidget):
    """Platno: slika v fizicnih pikah 1:1 (dekoder jo pripravi v velikosti, ki jo pove `velikost_za_dekoder`),
    vnos preracunan v pike izvora. Nikoli raztezanja z najblizjim sosedom (prej: neostro besedilo)."""

    def __init__(self, poslji, parent=None):
        super().__init__(parent)
        self._poslji = poslji
        self._ob_prikazu = None
        self._ob_velikosti = None
        self._slika = QImage()
        self._mere = (0, 0)              # izvor (pike izvora)
        self._kot = (0, 0)               # levi zgornji kot slike na platnu (fizicne pike)
        self._velikost = (0, 0)          # velikost slike na platnu (fizicne pike)
        self._miska: Optional[tuple] = None
        self.nacin = "prilagodi"
        #: Izvor rise kazalec v sliko (Linux, -draw_mouse): lokalni kazalec je nad sliko skrit - en kazalec.
        #: Ko izvor poslje obliko (Windows), kazalca v sliki ni in lokalni dobi to obliko.
        self.kazalec_v_sliki = True
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.BlankCursor)

    # ------------------------------------------------------------------ mere
    def dpr(self) -> float:
        try:
            return float(self.devicePixelRatioF() or 1.0)
        except Exception:  # noqa: BLE001
            return 1.0

    def platno(self) -> tuple:
        """Velikost platna v fizicnih pikah."""
        d = self.dpr()
        return prikaz.fizicno(self.width(), d), prikaz.fizicno(self.height(), d)

    def velikost_za_dekoder(self) -> Optional[tuple]:
        if not self._mere[0]:
            return None
        return prikaz.velikost_slike(self._mere, self.platno(), self.nacin)

    def nastavi_sliko(self, slika: QImage) -> None:
        self._slika = slika
        self.update()
        if self._ob_prikazu is not None:
            self._ob_prikazu()

    def nastavi_mere(self, sirina: int, visina: int) -> None:
        self._mere = (sirina, visina)
        self._sporoci_velikost()

    def nastavi_nacin(self, nacin: str) -> None:
        self.nacin = "1:1" if nacin == "1:1" else "prilagodi"
        self._sporoci_velikost()
        self.update()

    def nastavi_kazalec(self, oblika: Optional[str]) -> None:
        if not oblika:
            return
        self.kazalec_v_sliki = False
        self.setCursor(getattr(Qt.CursorShape, oblika, Qt.CursorShape.ArrowCursor))

    def _sporoci_velikost(self) -> None:
        if self._ob_velikosti is not None:
            self._ob_velikosti(self.velikost_za_dekoder())

    def resizeEvent(self, dogodek) -> None:  # noqa: N802 - Qt
        super().resizeEvent(dogodek)
        self._sporoci_velikost()

    # ------------------------------------------------------------------ risanje
    def paintGL(self) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#05070b"))
        if self._slika.isNull():
            self._velikost = (0, 0)
            return
        d = self.dpr()
        platno = self.platno()
        slika = (self._slika.width(), self._slika.height())
        zeleno = self.velikost_za_dekoder() or slika
        if slika != tuple(zeleno):
            # Prehod (okno se je ravnokar spremenilo): do naslednje slike prave velikosti zgladimo, ne izpuscamo pik.
            velikost = tuple(zeleno)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        else:
            velikost = slika
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        kot = prikaz.polozaj_slike(velikost, platno, self._miska if self.nacin == "1:1" else None)
        self._kot, self._velikost = kot, velikost
        # Logicne tocke tako, da se kot in velikost ujemata s celimi fizicnimi pikami (1:1, brez glajenja).
        p.drawImage(QRectF(kot[0] / d, kot[1] / d, velikost[0] / d, velikost[1] / d), self._slika)
        p.end()
        st = getattr(self.parent(), "_stevci", lambda: None)()
        if st is not None:
            st.prikazanih += 1

    def _tocka(self, dogodek: QMouseEvent) -> Optional[tuple[int, int]]:
        if not self._velikost[0] or not self._mere[0]:
            return None
        d = self.dpr()
        tocka = (dogodek.position().x() * d, dogodek.position().y() * d)
        return prikaz.v_izvor(tocka, self._kot, self._velikost, self._mere)

    def mouseMoveEvent(self, dogodek: QMouseEvent) -> None:
        if self.nacin == "1:1":
            d = self.dpr()
            self._miska = (dogodek.position().x() * d, dogodek.position().y() * d)
            self.update()
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
        self._omrezje: dict = {}
        self._naslov = ""
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(_b("naslov", ime=self.ime))
        self.resize(1280, 760)

        self.signali = _TokSignali(self)
        self.slika = _Slika(self._poslji, self)
        self.slika._ob_velikosti = self._nova_velikost
        self.stanje = QLabel(_b("pripravljam"))
        self.stanje.setStyleSheet("color:#d8e2f0;padding:0 8px")
        self.podatki = QLabel("")
        self.podatki.setStyleSheet("color:#9fb0c8;padding:0 8px")
        self.znova = QPushButton(_b("znova"))
        self.znova.clicked.connect(self.povezi)
        self.znova.hide()
        self.en_na_en = QPushButton(prikaz.besedilo(_JEZIK, "en_na_en"))
        self.en_na_en.setCheckable(True)
        self.en_na_en.setToolTip(prikaz.besedilo(_JEZIK, "en_na_en_namig"))
        self.en_na_en.toggled.connect(self._preklopi_1_1)
        self.cel = QPushButton(_b("cel"))
        self.cel.clicked.connect(self._preklopi_celozaslonsko)
        vrstica = QWidget(self)
        # Visina je veckratnik 4: platno pod njo je tudi pri 125/150/175 % na celi fizicni piki (brez glajenja).
        vrstica.setFixedHeight(prikaz.VISINA_VRSTICE)
        vrstica.setStyleSheet("background:#111827")
        pas = QHBoxLayout(vrstica)
        pas.setContentsMargins(0, 0, 4, 0)
        pas.addWidget(self.stanje, 1)
        pas.addWidget(self.podatki)
        pas.addWidget(self.znova)
        pas.addWidget(self.en_na_en)
        pas.addWidget(self.cel)
        postavitev = QVBoxLayout(self)
        postavitev.setContentsMargins(0, 0, 0, 0)
        postavitev.setSpacing(0)
        postavitev.addWidget(vrstica)
        postavitev.addWidget(self.slika, 1)
        self.signali.slika.connect(self.slika.nastavi_sliko)
        self.signali.mere.connect(self.slika.nastavi_mere)
        self.signali.stanje.connect(self._spremeni_stanje)
        self.signali.obvestilo.connect(self._obvestilo)
        self._ura = QTimer(self)
        self._ura.setInterval(1000)
        self._ura.timeout.connect(self._osvezi_podatke)
        QTimer.singleShot(0, self.povezi)

    def _stevci(self) -> Optional[_Stevci]:
        return self._nit.stevci if self._nit is not None else None

    def _poisci_napravo(self) -> dict:
        return next((n for n in self.backend.naprave if n.get("id") == self.id_naprave), {})

    def _platno_ob_zahtevi(self) -> tuple:
        """Fizicna velikost platna ob zahtevi seje. Okno je lahko se brez koncne velikosti (showMaximized se ni
        prisel do postavitve): takrat razpolozljivi del zaslona brez vrstice."""
        sirina, visina = self.slika.platno()
        if sirina >= 320 and visina >= 240:
            return sirina, visina
        zaslon = self.screen() or QApplication.primaryScreen()
        g = zaslon.availableGeometry()
        d = float(zaslon.devicePixelRatio() or 1.0)
        return prikaz.fizicno(g.width(), d), prikaz.fizicno(g.height() - prikaz.VISINA_VRSTICE - 32, d)

    def povezi(self) -> None:
        if self._nit is not None:
            self._nit.ustavi()
        self.znova.hide()
        # Svez zapis iz seznama naprav: okno, odprto zunaj doma, bi sicer za vedno drzalo zapis brez naslova.
        naprava = self._poisci_napravo() or self.naprava or {}
        if not ima_naslov(naprava):
            # Slika gre neposredno z naprave. Brez njenega naslova (dosegljiva je samo prek Global Linka) je ne
            # prosimo: naprava bi zaman odprla vrata in cakala na nas.
            self._spremeni_stanje("napaka", _b("ni_doma", ime=self.ime))
            return
        self.stanje.setText(_b("dovoljenje"))
        platno, dpr = self._platno_ob_zahtevi(), self.slika.dpr()

        def zahteva() -> None:
            try:
                naslov = str(naprava.get("naslov") or naprava.get("address") or naprava.get("host") or "")
                self._omrezje = prikaz.omrezje_do(naslov) if naslov else {}
                # Kot Android: velikost platna (izvor naredi loceni zaslon natanko te velikosti), omrezje in
                # zmoznosti; starejsi izvor neznana polja prezre.
                parametri = prikaz.zahteva_seje("najvisja", self.zaslon_cilj, platno, dpr,
                                                str(self._omrezje.get("vrsta") or ""))
                print("[Gledalec] %s: platno %dx%d (dpr %.2f, DPI %s), omrezje %s"
                      % (self.ime, platno[0], platno[1], dpr, prikaz.zavedanje_dpi(), self._omrezje or "?"),
                      flush=True)
                odgovor = self.backend.ukaz_pocakaj(self.id_naprave, "screen.start", parametri, cas=15.0)
                seja = razcleni_odgovor(odgovor, naprava)
                self._igra = je_igra(odgovor)
                if self._zapiram:
                    self.backend.ukaz_pocakaj(self.id_naprave, "screen.stop", {}, cas=5.0)
                    return
                self._naslov = str(getattr(seja, "naslov", "") or "")
                nit = _DekodirnaNit(seja, self.signali, self.ime)
                nit.cilj = self.slika.velikost_za_dekoder()
                self.slika._ob_prikazu = nit.prikaz_prost.set
                self._nit = nit
                nit.start()
            except Exception as exc:
                if not self._zapiram:
                    self.signali.stanje.emit("napaka", str(exc))
        threading.Thread(target=zahteva, name="safeer-screen-start", daemon=True).start()

    def _nova_velikost(self, velikost: Optional[tuple]) -> None:
        if self._nit is not None:
            self._nit.cilj = velikost

    def _preklopi_1_1(self, vklop: bool) -> None:
        self.slika.nastavi_nacin("1:1" if vklop else "prilagodi")
        self.en_na_en.setText(prikaz.besedilo(_JEZIK, "prilagodi" if vklop else "en_na_en"))
        self.en_na_en.setToolTip(prikaz.besedilo(_JEZIK, "prilagodi_namig" if vklop else "en_na_en_namig"))
        self._osvezi_podatke()

    def _obvestilo(self, obvestilo: dict) -> None:
        oblika = prikaz.oblika_kazalca(obvestilo)
        if oblika:
            self.slika.nastavi_kazalec(oblika)

    def _osvezi_podatke(self) -> None:
        st = self._stevci()
        if st is None or not self.slika._mere[0]:
            return
        fps, mbps = st.sekunda()
        zamik = st.rtt[-1] if st.rtt else None
        self.podatki.setText(prikaz.vrstica_podatkov(
            _JEZIK, self._naslov, False, self._omrezje, self.slika._mere,
            self.slika.velikost_za_dekoder() or self.slika._mere, fps, mbps, zamik, self.slika.nacin))

    def _poslji(self, dogodek: dict) -> None:
        if self._nit is not None:
            self._nit.poslji(dogodek)

    def _spremeni_stanje(self, stanje: str, sporocilo: str) -> None:
        self.stanje.setText(sporocilo)
        self.znova.setVisible(stanje == "napaka")
        if stanje == "tece":
            self._ura.start()
            self.slika.setFocus()
            # Igra na drugem racunalniku: takoj cez cel zaslon, kot na televizorju (gumb "V okno" vrne okno).
            if getattr(self, "_igra", False) and not self._je_celozaslonsko():
                self._preklopi_celozaslonsko()
        elif stanje == "napaka":
            self._ura.stop()

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
        self._ura.stop()
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
