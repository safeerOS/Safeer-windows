"""Zivi preizkus mostu lupine v QtWebEngine s pravo kodo (os_app.SafeerOsPage, most_js, _preveri_most, assets/os).

Pozene ga test_most_lupine.py v lastnem procesu (QT_QPA_PLATFORM=offscreen: brez oken, zasebno odlozisce).
Izhod: 0 = vse preverbe uspele, 1 = preverba padla, 77 = QtWebEngine v tem okolju ne nalozi strani (preskok).

Preveri: most ob nalaganju, zavrnitev klica brez zetona, meni polja (Kopiraj / Prilepi skozi most), konec procesa
strani + ponovno nalaganje (most mora ostati) in stran brez skripte mostu (Safeer OS jo vstavi, vmesnik pocaka).
"""
import functools
import http.server
import json
import os
import secrets
import sys
import threading

KOREN = sys.argv[1]

from PySide6.QtCore import QObject, Qt, QTimer, QUrl  # noqa: E402
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineScript  # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from safeer_windows import os_app  # noqa: E402


class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


streznik = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H, directory=os.path.join(KOREN, "assets")))
threading.Thread(target=streznik.serve_forever, daemon=True).start()
NASLOV = "http://127.0.0.1:%d/os/index.html" % streznik.server_address[1]

app = QApplication(sys.argv)
app.setApplicationName("SafeerPreizkusMostu")
izidi = []
stanje = {"nalaganj": 0, "po_koncu": False, "koda": 77, "okna": []}


def izpis(*a):
    print(*a, flush=True)


def preveri(ime, pogoj, podrobno=""):
    izidi.append((ime, bool(pogoj)))
    izpis("  %s %s%s" % ("OK    " if pogoj else "NAPAKA", ime, (" | " + str(podrobno)[:200]) if podrobno != "" else ""))


class Okno(QObject):
    """Prave metode SafeerOsWindow nad laznim zaledjem: odlozisce deluje, vse drugo zavrne."""
    zeton_mostu_velja = os_app.SafeerOsWindow.zeton_mostu_velja
    zavrnjen_klic_mostu = os_app.SafeerOsWindow.zavrnjen_klic_mostu
    _preveri_most = os_app.SafeerOsWindow._preveri_most
    _na_glavni_niti = os_app.SafeerOsWindow._na_glavni_niti
    _kopiraj = os_app.SafeerOsWindow._kopiraj
    _odlozisce_beri = os_app.SafeerOsWindow._odlozisce_beri
    vrni_odgovor = os_app.SafeerOsWindow.vrni_odgovor

    def __init__(self, ime, z_mostom=True):
        super().__init__()
        self.klici = []
        self.dispatcher = os_app.GuiDispatcher(self)
        self._zeton_mostu = secrets.token_urlsafe(24)
        self._most_js = os_app.most_js(self._zeton_mostu)
        self._zavrnjeni_klici_mostu = 0
        self.profile = QWebEngineProfile(self)          # brez imena: nic se ne shrani na disk
        self.view = QWebEngineView()
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.page_obj = os_app.SafeerOsPage(self.profile, self)
        if z_mostom:
            s = QWebEngineScript()
            s.setName("SafeerOsBridge")
            s.setSourceCode(self._most_js)
            s.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
            s.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            s.setRunsOnSubFrames(False)
            self.page_obj.scripts().insert(s)
        self.page_obj.loadFinished.connect(self._preveri_most)
        self.view.setPage(self.page_obj)
        self.view.resize(1280, 800)
        self.view.show()

    def obdelaj_klic(self, sporocilo):
        self.klici.append(sporocilo.get("m"))
        klic_id, metoda, a = sporocilo.get("id", 0), sporocilo.get("m", ""), sporocilo.get("a", [])

        def delo():
            try:
                if metoda == "kopiraj":
                    self.vrni_odgovor(klic_id, True, self._kopiraj(str(a[0]) if a else ""))
                elif metoda == "odlozisceBeri":
                    self.vrni_odgovor(klic_id, True, self._odlozisce_beri())
                else:
                    self.vrni_odgovor(klic_id, False, "ni v preizkusu")
            except Exception as e:  # noqa: BLE001
                self.vrni_odgovor(klic_id, False, str(e))
        threading.Thread(target=delo, daemon=True).start()


okno = Okno("glavno")
stran = okno.page_obj


def js(koda, naprej, s=None):
    (s or stran).runJavaScript(koda, lambda r: naprej(r))


def po(ms, fn):
    QTimer.singleShot(ms, fn)


# Desni klik na polje in izbira vrstice menija - z dogodki strani (brez koordinat zaslona).
MENI_JS = """(function (id, vrstica) {
  var p = document.getElementById(id); p.focus();
  var r = p.getBoundingClientRect();
  p.dispatchEvent(new MouseEvent("contextmenu", {bubbles: true, cancelable: true, clientX: r.left + 20, clientY: r.top + r.height / 2, button: 2}));
  var m = document.querySelector(".meni-polja");
  if (!m) return JSON.stringify({meni: null});
  var gumbi = [].slice.call(m.querySelectorAll("button"));
  var izid = {meni: gumbi.map(function (g) { return g.textContent + (g.disabled ? "(-)" : ""); })};
  var g = gumbi.filter(function (x) { return x.textContent === vrstica && !x.disabled; })[0];
  if (g) { g.click(); izid.kliknjeno = true; }
  return JSON.stringify(izid);
})"""


def k1():
    izpis("== 1. most ob nalaganju")
    js("typeof (window.SafeerOS && window.SafeerOS.klic)", lambda r: (
        preveri("window.SafeerOS.klic obstaja", r == "function", r),
        preveri("vmesnik je ob zagonu klical most (zacetek)", "zacetek" in okno.klici, okno.klici[:6]),
        k2()))


def k2():
    izpis("== 2. klic brez zetona (kot iz tuje strani v okvirju)")
    QApplication.clipboard().setText("NEDOTAKNJENO")
    pred = len(okno.klici)
    js("console.log('__safeer_os_bridge__:' + JSON.stringify({id: 9001, m: 'kopiraj', a: ['PONAREJENO']}));"
       "console.log('__safeer_os_bridge__:' + JSON.stringify({id: 9002, m: 'kopiraj', a: ['PONAREJENO'], z: 'napacen-zeton-napacen-zeton'})); 1",
       lambda r: po(800, lambda: (
           preveri("klica brez veljavnega zetona nista izvedena", len(okno.klici) == pred and okno._zavrnjeni_klici_mostu == 2,
                   "klici +%d, zavrnjeni %d" % (len(okno.klici) - pred, okno._zavrnjeni_klici_mostu)),
           preveri("odlozisce je nedotaknjeno", QApplication.clipboard().text() == "NEDOTAKNJENO"),
           k3())))


def k3():
    izpis("== 3. meni polja: Kopiraj v polju Splet, Prilepi v iskanju")
    QApplication.clipboard().setText("")
    js("window.safeerOsPojdi('splet'); var v = document.getElementById('spletVnos'); v.value = 'defrag windows'; v.focus(); v.select(); 1",
       lambda r: po(600, lambda: js(MENI_JS + "('spletVnos', 'Kopiraj')", k3a)))


def k3a(r):
    podatki = json.loads(r or "{}")
    preveri("meni polja v jeziku vmesnika", podatki.get("meni") == ["Izreži", "Kopiraj", "Prilepi", "Izberi vse"], podatki)
    po(900, lambda: (
        preveri("Kopiraj: besedilo je v odloziscu", QApplication.clipboard().text() == "defrag windows", repr(QApplication.clipboard().text())),
        js(MENI_JS + "('iskanje', 'Prilepi')", lambda r2: po(900, lambda: js(
            "document.getElementById('iskanje').value + '|' + document.getElementById('slojIskanje').classList.contains('viden')",
            lambda r3: (preveri("Prilepi: besedilo je v polju, zadetki odprti", r3 == "defrag windows|true", r3), k4()))))))


def k4():
    izpis("== 4. konec procesa strani (kot straza pomnilnika) in ponovno nalaganje")
    okno.klici.clear()
    stanje["po_koncu"] = True
    os.kill(int(stran.renderProcessPid()), 9)


def k4a():
    js("typeof (window.SafeerOS && window.SafeerOS.klic)", lambda r: (
        preveri("po ponovnem nalaganju: window.SafeerOS.klic obstaja", r == "function", r),
        preveri("po ponovnem nalaganju: vmesnik je spet klical most", "zacetek" in okno.klici, okno.klici[:6]),
        k4b()))


def k4b():
    QApplication.clipboard().setText("po koncu procesa")
    js(MENI_JS + "('iskanje', 'Prilepi')", lambda r: po(900, lambda: js(
        "document.getElementById('iskanje').value",
        lambda r2: (preveri("po ponovnem nalaganju: Prilepi deluje", r2 == "po koncu procesa", repr(r2)), k5()))))


def k5():
    izpis("== 5. stran brez skripte mostu: Safeer OS jo vstavi sam, vmesnik nanjo pocaka")
    drugo = Okno("drugo", z_mostom=False)
    stanje["okna"].append(drugo)

    def konec(ok):
        po(4000, lambda: js("typeof (window.SafeerOS && window.SafeerOS.klic)", lambda r: (
            preveri("most je bil vstavljen po nalaganju", r == "function", r),
            preveri("vmesnik je pocakal in nato klical most", "zacetek" in drugo.klici, drugo.klici[:6]),
            zakljuci()), drugo.page_obj))
    drugo.page_obj.loadFinished.connect(konec)
    drugo.page_obj.load(QUrl(NASLOV))


def zakljuci():
    padli = [i for i, ok in izidi if not ok]
    izpis("== IZID: %d preverb, padlih %d %s" % (len(izidi), len(padli), padli if padli else ""))
    stanje["koda"] = 1 if padli else 0
    app.quit()


def nalozeno(ok):
    stanje["nalaganj"] += 1
    izpis("[loadFinished #%d ok=%s]" % (stanje["nalaganj"], ok))
    if not ok:
        return
    if stanje["nalaganj"] == 1:
        stanje["koda"] = 1          # stran se nalozi: od tu naprej je vsak zastoj napaka, ne okolje
        po(1500, k1)
    elif stanje["po_koncu"] and stanje["nalaganj"] == 2:
        po(1500, k4a)


stran.loadFinished.connect(nalozeno)
stran.renderProcessTerminated.connect(lambda s, k: (izpis("[renderProcessTerminated %s]" % s),
                                                    po(1000, lambda: stran.triggerAction(stran.WebAction.Reload))))
stran.load(QUrl(NASLOV))
po(100000, lambda: (izpis("[rok]"), app.quit()))
app.exec()
izpis("KODA", stanje["koda"])
# Brez urejenega zapiranja Qt: os._exit, da proces ne obvisi ob sproscanju profilov.
sys.stdout.flush()
os._exit(stanje["koda"])
