"""Zivi preizkus okna zaslona naprave (okno_zaslona.py) v QtWebEngine - zaganja ga test_okno_zaslona.py v svojem procesu.

Stran gledalca (kot s sredisca: <img id="zaslon">) po HTTPS s samopodpisanim potrdilom; okno sprejme samo pripeti odtis.
Klik, tipke in Enter morajo priti do control_backend.poslji_vnos kot input.tap / input.text / input.key; lazni izpis
strani (napacen zeton) in lazni dogodki strani (dispatchEvent, isTrusted = false) ne smejo. Izhod 77 = okolje brez
delujocega QtWebEngine (preizkus se preskoci)."""
import functools
import http.server
import json
import os
import ssl
import sys
import tempfile
import threading

KOREN = sys.argv[1]
NACIN = sys.argv[2] if len(sys.argv) > 2 else "prav"
sys.path.insert(0, KOREN)
sys.path.insert(0, os.path.join(KOREN, "windows"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core import link_datoteke  # noqa: E402

MAPA = tempfile.mkdtemp()
with open(os.path.join(MAPA, "view.html"), "w", encoding="utf-8") as f:
    f.write("""<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;height:100%;background:#000}
img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain}</style></head><body>
<img id="zaslon" src="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='540' height='1200'><rect width='540' height='1200' fill='%2330609a'/></svg>">
<script>var s=document.getElementById("zaslon");
setTimeout(function(){ s.dispatchEvent(new MouseEvent("mousedown",{bubbles:true,clientX:5,clientY:5}));
 s.dispatchEvent(new MouseEvent("mouseup",{bubbles:true,clientX:5,clientY:5}));
 document.dispatchEvent(new KeyboardEvent("keydown",{key:"x",bubbles:true}));
 console.log("__safeer_vnos__:"+JSON.stringify({z:"ugibam",d:"input.key",p:{key:"home"}})); }, 200);</script></body></html>""")
kljuc, potrdilo, odtis = link_datoteke.zagotovi_potrdilo(os.path.join(MAPA, "tls"))


class _Tih(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Tih, directory=MAPA))
k = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
k.load_cert_chain(potrdilo, kljuc)
srv.socket = k.wrap_socket(srv.socket, server_side=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()

try:
    from PySide6.QtCore import QObject, QPoint, Qt, QTimer, Signal
    from PySide6.QtGui import QIcon
    from PySide6.QtTest import QTest
    from PySide6.QtWebEngineCore import QWebEngineProfile
    from PySide6.QtWidgets import QApplication
except ImportError:
    print("brez QtWebEngine")
    sys.exit(77)

app = QApplication(sys.argv)
from safeer_windows import okno_zaslona  # noqa: E402


class Disp(QObject):
    sig = Signal(object)

    def __init__(self):
        super().__init__()
        self.sig.connect(lambda f: f())

    def dispatch(self, f):
        self.sig.emit(f)


class CB:
    def __init__(self):
        self.gledani_zaslon = "n-tel"
        self.naprave = [{"id": "n-tel", "ime": "Telefon"}]
        self.poslano, self.konec, self.ob_odzivu_vnosa = [], [], None

    def poslji_vnos(self, d, p):
        self.poslano.append([d, p])
        return True

    def koncaj_gledanje(self, n):
        self.konec.append(n)


class OS:
    def __init__(self):
        self.profile = QWebEngineProfile("preizkus-zaslona", app)
        self.dispatcher = Disp()
        self.control_backend = CB()

    def windowIcon(self):
        return QIcon()


os_ = OS()
okno = okno_zaslona.odpri(os_, {"url": "https://127.0.0.1:%d/view.html?k=skrivno" % srv.server_address[1],
                                "odtis": odtis if NACIN == "prav" else "00" * 32, "naprava": "n-tel", "od": "Telefon"},
                          "Kamera", "sl")
nalozeno = []
okno.stran.loadFinished.connect(lambda ok: nalozeno.append(ok))


def klik():
    if NACIN == "prav" and not any(nalozeno):
        print("stran se ni nalozila")
        app.exit(77)
        return
    w = okno.pogled.focusProxy() or okno.pogled
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(w.width() // 2, w.height() // 2))
    QTest.keyClicks(w, "ab")
    QTest.keyClick(w, Qt.Key.Key_Return)
    QTimer.singleShot(900, konec)


def konec():
    os_.control_backend.ob_odzivu_vnosa({"ok": False, "koda": "vnos_ni_vklopljen"})
    QTimer.singleShot(300, izpis)


def izpis():
    print("IZID " + json.dumps({"naslov": okno.windowTitle(), "poslano": os_.control_backend.poslano,
                                "namig": okno.vrstica_namiga.isVisible(), "gumb": okno.gumb_nastavitve.isVisible()}))
    okno.close()
    print("KONEC " + json.dumps(os_.control_backend.konec))
    app.exit(0)


QTimer.singleShot(4000, klik)
sys.exit(app.exec())
