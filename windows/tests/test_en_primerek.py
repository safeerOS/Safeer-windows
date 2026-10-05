"""Safeer OS na Windows tece v eni sami kopiji (27. 9. se jih je ob hkratnem zagonu pognalo sest)."""
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

KOREN = Path(__file__).resolve().parents[1]


def _pozeni(koda: str, okolje: dict) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", textwrap.dedent(koda)], cwd=str(KOREN), env=okolje,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def _okolje(tmp: str) -> dict:
    """Okolje podprocesov. Ime primerka je enolicno in ga podproces nastavi sam (IME_PRIMERKA): na USER/USERNAME se
    ne zanasamo - v seji ssh na Windows je nastavljen LOGNAME, ki ga getpass uposteva prvega, in preizkus je
    5. 10. 2026 govoril s PRAVIM Safeer OS na tistem racunalniku (in ga z »novo razlicico« zaprl)."""
    return {**os.environ, "QT_QPA_PLATFORM": "offscreen", "TMPDIR": tmp, "TEMP": tmp, "TMP": tmp,
            "SAFEER_PREIZKUS_IME": "SafeerOS-preizkus-%d-%s" % (os.getpid(), os.path.basename(tmp)), "PYTHONPATH": str(KOREN)}



def test_druga_kopija_preda_razdelek_prvi_in_se_konca():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        okolje = _okolje(tmp)
        prva = _pozeni("""
            import sys
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication
            from safeer_windows import en_primerek as os_app
            os_app.ime = lambda: __import__('os').environ['SAFEER_PREIZKUS_IME']
            app = QApplication(sys.argv)
            zaklep = os_app.zakleni()
            assert zaklep is not None
            class Okno:
                def prebudi(self, r):
                    print("PREBUJENO", r, flush=True); QTimer.singleShot(500, app.quit)
            from PySide6.QtCore import QObject
            okno = QObject(); okno.prebudi = Okno().prebudi
            s = os_app.streznik(okno)
            print("PRIPRAVLJENA", flush=True)
            QTimer.singleShot(15000, app.quit)
            app.exec()
        """, okolje)
        assert prva.stdout.readline().strip() == "PRIPRAVLJENA"
        druga = subprocess.run([sys.executable, "-c", textwrap.dedent("""
            import sys
            from PySide6.QtWidgets import QApplication
            from safeer_windows import en_primerek as os_app
            os_app.ime = lambda: __import__('os').environ['SAFEER_PREIZKUS_IME']
            app = QApplication(sys.argv)
            assert os_app.zakleni() is None, "druga kopija ne sme dobiti zaklepa"
            print("PREDANO" if os_app.predaj_prvemu("naprave", False) else "NI")
        """)], cwd=str(KOREN), env=okolje, capture_output=True, text=True, timeout=30)
        assert "PREDANO" in druga.stdout, druga.stdout + druga.stderr
        izpis, _ = prva.communicate(timeout=20)
        assert "PREBUJENO naprave" in izpis




def _druga(koda: str, okolje: dict, cas: int = 40) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", textwrap.dedent(koda)], cwd=str(KOREN), env=okolje,
                          capture_output=True, text=True, timeout=cas)


def test_nova_razlicica_staro_kopijo_umakne():
    """Po posodobitvi: nova kopija (drug odtis kode) dobi »umik«, stara se zapre, nova prevzame zaklep."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        okolje = _okolje(tmp)
        prva = _pozeni("""
            import sys
            from PySide6.QtCore import QObject, QTimer
            from PySide6.QtWidgets import QApplication
            from safeer_windows import en_primerek
            en_primerek.ime = lambda: __import__('os').environ['SAFEER_PREIZKUS_IME']
            en_primerek.ZAGNANA_KODA = "stara"
            app = QApplication(sys.argv)
            zaklep = en_primerek.zakleni()
            assert zaklep is not None
            okno = QObject()
            def konec():
                print("UMIK", flush=True); zaklep.unlock(); app.quit()
            okno.koncaj_za_posodobitev = konec
            okno.prebudi = lambda r: print("PREBUJENO", r, flush=True)
            s = en_primerek.streznik(okno)
            print("PRIPRAVLJENA", flush=True)
            QTimer.singleShot(20000, app.quit)
            app.exec()
        """, okolje)
        assert prva.stdout.readline().strip() == "PRIPRAVLJENA"
        druga = _druga("""
            import sys
            from PySide6.QtWidgets import QApplication
            from safeer_windows import en_primerek
            en_primerek.ime = lambda: __import__('os').environ['SAFEER_PREIZKUS_IME']
            en_primerek.ZAGNANA_KODA = "nova"
            app = QApplication(sys.argv)
            assert en_primerek.zakleni() is None
            izid = en_primerek.vprasaj_prvo("naprave", False)
            odlocitev, zaklep = en_primerek.odloci_brez_prevzema(izid)
            print("IZID", izid, odlocitev, zaklep is not None)
        """, okolje)
        assert "IZID umik prevzeto True" in druga.stdout, druga.stdout + druga.stderr
        izpis, _ = prva.communicate(timeout=20)
        assert "UMIK" in izpis and "PREBUJENO" not in izpis, izpis


def test_prva_kopija_ki_ne_odgovarja_ne_ustavi_druge():
    """Prva kopija se zapira ali je zasedena: poslusa, a ne bere. Nova ne sme obviseti (5. 10. 2026 je za vedno)
    in ne sme sklepati, da je prva zagon prevzela."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        okolje = _okolje(tmp)
        prva = _pozeni("""
            import sys, time
            from PySide6.QtNetwork import QLocalServer
            from PySide6.QtWidgets import QApplication
            from safeer_windows import en_primerek
            en_primerek.ime = lambda: __import__('os').environ['SAFEER_PREIZKUS_IME']
            app = QApplication(sys.argv)
            zaklep = en_primerek.zakleni()
            QLocalServer.removeServer(en_primerek.ime())
            s = QLocalServer()
            assert s.listen(en_primerek.ime()), s.errorString()
            print("PRIPRAVLJENA", flush=True)
            sys.stdin.readline()        # brez zanke dogodkov: povezavo sprejme sistem, bere je nihce (do konca preizkusa)
        """, okolje)
        assert prva.stdout.readline().strip() == "PRIPRAVLJENA"
        zacetek = __import__("time").monotonic()
        druga = _druga("""
            import sys, time
            from PySide6.QtWidgets import QApplication
            from safeer_windows import en_primerek
            en_primerek.ime = lambda: __import__('os').environ['SAFEER_PREIZKUS_IME']
            app = QApplication(sys.argv)
            assert en_primerek.zakleni() is None
            t = time.monotonic()
            izid = en_primerek.vprasaj_prvo("naprave", False)
            print("IZID", izid, "%.1f" % (time.monotonic() - t))
            # Prva kopija zaklepa ne spusti (ziva, zasedena): druge kopije ne zaganjamo.
            print("ODLOCITEV", en_primerek.odloci_brez_prevzema(izid, prevzemi=lambda: en_primerek.prevzemi_zaklep(1500))[0])
            print("STARO", en_primerek.predaj_prvemu("naprave", False))
        """, okolje)
        trajalo = __import__("time").monotonic() - zacetek
        assert "IZID brez_odgovora" in druga.stdout, druga.stdout + druga.stderr
        assert "ODLOCITEV zasedena" in druga.stdout, druga.stdout + druga.stderr
        assert "STARO False" in druga.stdout, druga.stdout + druga.stderr
        assert trajalo < 25, "druga kopija je cakala %.0f s" % trajalo
        prva.kill()
        prva.communicate(timeout=10)


def test_brez_prve_kopije_je_odgovor_hiter():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        druga = _druga("""
            import sys, time
            from PySide6.QtWidgets import QApplication
            from safeer_windows import en_primerek
            en_primerek.ime = lambda: __import__('os').environ['SAFEER_PREIZKUS_IME']
            app = QApplication(sys.argv)
            t = time.monotonic()
            izid = en_primerek.vprasaj_prvo("naprave", False, cakaj_ms=600)
            print("IZID", izid, time.monotonic() - t < 5)
            print("ODLOCITEV", en_primerek.odloci_brez_prevzema(izid, prevzemi=lambda: None)[0])
        """, _okolje(tmp))
        assert "IZID ni True" in druga.stdout, druga.stdout + druga.stderr
        assert "ODLOCITEV neodzivna" in druga.stdout, druga.stdout + druga.stderr


def test_odjemalec_ne_uporablja_blokirajocih_cakanj_qt():
    for ime in ("en_primerek.py", "browser.py", "krajevna_povezava.py"):
        vir = (KOREN / "safeer_windows" / ime).read_text(encoding="utf-8")
        koda = "\n".join(v for v in vir.splitlines() if not v.strip().startswith("#"))
        assert "QLocalSocket(" not in koda, ime
        for klic in ("waitForReadyRead(", "waitForBytesWritten(", "waitForConnected("):
            assert klic not in koda, ime + ": " + klic


def test_brskalnik_preda_naslove_prvi_kopiji():
    """SafeerBrowser.exe: druga kopija preda naslove prvi po isti poti (brez QLocalSocket)."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        okolje = _okolje(tmp)
        prva = _pozeni("""
            import os, sys
            from PySide6.QtCore import QTimer
            from PySide6.QtNetwork import QLocalServer
            from PySide6.QtWidgets import QApplication
            app = QApplication(sys.argv)
            ime = os.environ["SAFEER_PREIZKUS_IME"]
            QLocalServer.removeServer(ime)
            s = QLocalServer()
            def povezava():
                v = s.nextPendingConnection()
                def beri():
                    print("PREJETO", bytes(v.readAll()).decode().strip(), flush=True); QTimer.singleShot(200, app.quit)
                v.readyRead.connect(beri)
            s.newConnection.connect(povezava)
            assert s.listen(ime), s.errorString()
            print("PRIPRAVLJENA", flush=True)
            QTimer.singleShot(20000, app.quit)
            app.exec()
        """, okolje)
        assert prva.stdout.readline().strip() == "PRIPRAVLJENA"
        druga = _druga("""
            import os
            from safeer_windows import krajevna_povezava
            ime = os.environ["SAFEER_PREIZKUS_IME"]
            print("POSLANO", krajevna_povezava.pogovor(ime, b'{"urls": ["https://safeer.si/"]}\\n', 1.5, odgovor=False) is not None)
            print("NI", krajevna_povezava.pogovor(ime + "-ni", b"x\\n", 0.5, odgovor=False) is None)
        """, okolje)
        assert "POSLANO True" in druga.stdout and "NI True" in druga.stdout, druga.stdout + druga.stderr
        izpis, _ = prva.communicate(timeout=20)
        assert 'PREJETO {"urls": ["https://safeer.si/"]}' in izpis, izpis
