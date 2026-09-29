"""Safeer OS na Windows tece v eni sami kopiji.

Safeer OS drzi Link, streznik zaslona in medijski center: dve kopiji hkrati bi se prepirali za
vrata in podvojili RAM (27. 9. se jih je ob hkratnem zagonu pognalo sest). Prva kopija drzi
zaklep in lokalni streznik; vsaka naslednja ji preda razdelek in se takoj konca.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from PySide6.QtCore import QDir, QLockFile
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def ime() -> str:
    try:
        import getpass
        uporabnik = getpass.getuser()
    except Exception:
        uporabnik = "user"
    return "SafeerOS-" + re.sub(r"[^A-Za-z0-9_.-]", "_", uporabnik)


def razlicica_kode() -> str:
    """Odtis namescene kode (zaganjalnik ob vsaki novi razlicici zapise .version); prazen, ce ga ni."""
    from pathlib import Path
    try:
        return (Path(__file__).resolve().parents[2] / ".version").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


# Odtis kode, s katero je ta proces zagnan (datoteko zaganjalnik ob posodobitvi prepise).
ZAGNANA_KODA = razlicica_kode()


def zakleni() -> Optional[QLockFile]:
    """Vrne zaklep, ce je ta proces prva kopija; sicer None. Zapusceni zaklep (mrtev proces) prevzame."""
    zaklep = QLockFile(os.path.join(QDir.tempPath(), ime() + ".lock"))
    zaklep.setStaleLockTime(0)
    if zaklep.tryLock(0):
        return zaklep
    if zaklep.removeStaleLockFile() and zaklep.tryLock(0):
        return zaklep
    return None


def predaj_prvemu(razdelek: str, ozadje: bool, cakaj_ms: int = 4000, magnet: str = "") -> bool:
    """Tece ze druga kopija: ji predamo razdelek (prva se lahko se zaganja, zato nekaj casa poskusamo).

    `magnet`: magnet povezava (brskalnik, druga naprava v Linku), ki jo prva kopija odpre v Medijskem centru.

    Vrne True, ce je prva kopija prevzela zagon. False pomeni, da se ne odziva ALI da je bila zagnana
    s starejso kodo in se je zato umaknila - v tem primeru pokliči prevzemi_zaklep().
    """
    import time
    konec = time.monotonic() + cakaj_ms / 1000.0
    while True:
        vticnica = QLocalSocket()
        vticnica.connectToServer(ime())
        if vticnica.waitForConnected(300):
            sporocilo = {"razdelek": razdelek, "ozadje": ozadje, "koda": ZAGNANA_KODA}
            if magnet:
                sporocilo["magnet"] = magnet
            vticnica.write(json.dumps(sporocilo).encode("utf-8") + b"\n")
            vticnica.waitForBytesWritten(1000)
            odgovor = b""
            if vticnica.waitForReadyRead(1500):
                odgovor = bytes(vticnica.readAll())
            vticnica.disconnectFromServer()
            return not odgovor.startswith(b"umikam")
        if time.monotonic() >= konec:
            return False
        time.sleep(0.2)


def prevzemi_zaklep(cakaj_ms: int = 15000) -> Optional[QLockFile]:
    """Po posodobitvi se stara kopija zapre; pocakamo, da sprosti zaklep, in ga prevzamemo."""
    import time
    konec = time.monotonic() + cakaj_ms / 1000.0
    while time.monotonic() < konec:
        zaklep = zakleni()
        if zaklep is not None:
            return zaklep
        time.sleep(0.3)
    return None


def streznik(okno) -> QLocalServer:
    QLocalServer.removeServer(ime())
    streznik = QLocalServer(okno)
    streznik.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)

    medpomnilniki: dict = {}

    def ob_povezavi() -> None:
        while streznik.hasPendingConnections():
            v = streznik.nextPendingConnection()
            v.readyRead.connect(lambda v=v: ob_podatkih(v))
            v.disconnected.connect(lambda v=v: medpomnilniki.pop(id(v), None))

    def ob_podatkih(v: QLocalSocket) -> None:
        # Sporocilo je ena vrstica JSON; magnet povezava (do 8 kB) lahko pride v vec kosih.
        podatki = medpomnilniki.get(id(v), b"") + bytes(v.readAll())
        if b"\n" not in podatki and len(podatki) < 64 * 1024:
            medpomnilniki[id(v)] = podatki
            return
        medpomnilniki.pop(id(v), None)
        try:
            sporocilo = json.loads(podatki.decode("utf-8", "replace").strip().splitlines()[0])
        except (ValueError, IndexError):
            sporocilo = {}
        if not isinstance(sporocilo, dict):
            sporocilo = {}
        nova = str(sporocilo.get("koda") or "")
        if nova and ZAGNANA_KODA and nova != ZAGNANA_KODA:
            # Namescena je nova razlicica: umaknemo se, da uporabnik dobi posodobljen Safeer OS
            # (prej je zagon predal staremu procesu in posodobitev je obvelja sele po ponovnem zagonu).
            v.write(b"umikam\n")
            v.waitForBytesWritten(1000)
            v.disconnectFromServer()
            print("[SafeerOS] Namescena je nova razlicica; ta kopija se zapira.", flush=True)
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, okno.koncaj_za_posodobitev)
            return
        v.write(b"ok\n")          # odgovor, da nova kopija ne caka po nepotrebnem
        v.waitForBytesWritten(500)
        v.disconnectFromServer()
        if sporocilo.get("ozadje"):
            return  # samodejni zagon v ozadju: prva kopija ze tece, okna ne vsiljujemo
        magnet = str(sporocilo.get("magnet") or "")
        if magnet and hasattr(okno, "odpri_magnet"):
            okno.odpri_magnet(magnet)      # preveri jo sam (os_torrent.razcleni_magnet)
            return
        okno.prebudi(str(sporocilo.get("razdelek") or ""))

    streznik.newConnection.connect(ob_povezavi)
    streznik.listen(ime())
    return streznik
