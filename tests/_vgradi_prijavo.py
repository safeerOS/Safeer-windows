"""Vgradi prijavo/Control v Safeer OS okno namesto locenega okna (Windows), po vzoru Linuxa."""
import re

# --- control_window.py: dodaj na_skritje kljuc in ga klici ob zapri/nadaljujBrezPovezave/uspesni povezavi ---
pot = "windows/safeer_windows/control_window.py"
v = open(pot, encoding="utf-8").read()

star = '''class SafeerControlWindow(QMainWindow):
    def __init__(self, backend: Optional[control_backend.SafeerControlBackend] = None, parent: Optional[QMainWindow] = None):
        super().__init__(parent, Qt.Window)
        self.backend = backend or control_backend.get_backend()'''
nov = '''class SafeerControlWindow(QMainWindow):
    def __init__(self, backend: Optional[control_backend.SafeerControlBackend] = None, parent: Optional[QMainWindow] = None,
                 na_skritje: Optional[Any] = None):
        super().__init__(parent, Qt.Window)
        self.backend = backend or control_backend.get_backend()
        #: Ko je vgrajen v Safeer OS (namesto lastnega vrha-okna): klice se ob "zapri", uspesni
        #: seznanitvi ali "nadaljuj brez povezave", da starsevsko okno preklopi nazaj na svoj pogled.
        self.na_skritje = na_skritje'''
assert star in v, "vzorec 1 ni najden"
v = v.replace(star, nov, 1)

star2 = '''    def _na_dogodek_zaledja(self, vrsta: str, podatki: Any) -> None:
        self.dispatcher.dispatch(lambda: self.osvezi_stran(vrsta, podatki))'''
nov2 = '''    def _na_dogodek_zaledja(self, vrsta: str, podatki: Any) -> None:
        self.dispatcher.dispatch(lambda: self.osvezi_stran(vrsta, podatki))
        if self.na_skritje is not None and vrsta in ("povezava", "stanje") and self.backend.stanje_linka().get("stanje") == "povezan":
            self.dispatcher.dispatch(self.na_skritje)'''
assert star2 in v, "vzorec 2 ni najden"
v = v.replace(star2, nov2, 1)

star3 = '''        elif metoda == "nadaljujBrezPovezave":
            self.backend.nadaljuj_brez_povezave()'''
nov3 = '''        elif metoda == "nadaljujBrezPovezave":
            self.backend.nadaljuj_brez_povezave()
            if self.na_skritje is not None:
                self.dispatcher.dispatch(self.na_skritje)'''
assert star3 in v, "vzorec 3 ni najden"
v = v.replace(star3, nov3, 1)

star4 = '''        elif metoda == "zapri":
            self.dispatcher.dispatch(self.close)'''
nov4 = '''        elif metoda == "zapri":
            if self.na_skritje is not None:
                self.dispatcher.dispatch(self.na_skritje)
            else:
                self.dispatcher.dispatch(self.close)'''
assert star4 in v, "vzorec 4 ni najden"
v = v.replace(star4, nov4, 1)

star5 = '''    def closeEvent(self, event) -> None:
        # Ce imamo starsevsko okno (npr. Safeer OS), okno samo skrijemo
        if self.parent():
            self.hide()
            event.ignore()'''
nov5 = '''    def closeEvent(self, event) -> None:
        # Ce je vgrajen v Safeer OS, klik na X v vgrajenem pogledu ne pride sem (ni okvirja);
        # ta pot ostane za primer, ko je (redko) se vedno pravo okno.
        if self.parent():
            self.hide()
            event.ignore()'''
assert star5 in v, "vzorec 5 ni najden"
v = v.replace(star5, nov5, 1)

open(pot, "w", encoding="utf-8").write(v)
print("control_window.py popravljen")

# --- os_app.py: QStackedWidget namesto samega self.view; vgrajen Control namesto locenega okna ---
pot2 = "windows/safeer_windows/os_app.py"
v2 = open(pot2, encoding="utf-8").read()

star6 = "from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget"
nov6 = "from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QVBoxLayout, QWidget"
assert star6 in v2, "vzorec 6 ni najden"
v2 = v2.replace(star6, nov6, 1)

star7 = '''        self.setCentralWidget(self.view)

        # Tipke za celozaslonski nacin'''
nov7 = '''        self.zaslon = QStackedWidget(self)
        self.zaslon.addWidget(self.view)
        self.setCentralWidget(self.zaslon)

        # Tipke za celozaslonski nacin'''
assert star7 in v2, "vzorec 7 ni najden"
v2 = v2.replace(star7, nov7, 1)

star8 = '''    def odpri_control(self, razdelek: str = "") -> bool:
        def _odpri():
            if self.control_window is None:
                self.control_window = control_window.SafeerControlWindow(backend=self.control_backend, parent=None)
            if razdelek:
                self.control_window.pojdi_na_razdelek(razdelek)
            self.control_window.showNormal()
            self.control_window.show()
            self.control_window.raise_()
            self.control_window.activateWindow()
        self.dispatcher.dispatch(_odpri)
        return True'''
nov8 = '''    def odpri_control(self, razdelek: str = "") -> bool:
        def _odpri():
            if self.control_window is None:
                self.control_window = control_window.SafeerControlWindow(
                    backend=self.control_backend, parent=self, na_skritje=self._na_skritje_controla)
                self.control_window.setWindowFlags(Qt.Widget)
                self.zaslon.addWidget(self.control_window)
            if razdelek:
                self.control_window.pojdi_na_razdelek(razdelek)
            self.zaslon.setCurrentWidget(self.control_window)
        self.dispatcher.dispatch(_odpri)
        return True

    def _na_skritje_controla(self) -> None:
        """Prijava/Control je koncan (zapri, uspesna povezava ali "nadaljuj brez") - nazaj na Safeer OS."""
        self.dispatcher.dispatch(lambda: self.zaslon.setCurrentWidget(self.view))'''
assert star8 in v2, "vzorec 8 ni najden"
v2 = v2.replace(star8, nov8, 1)

open(pot2, "w", encoding="utf-8").write(v2)
print("os_app.py popravljen")
