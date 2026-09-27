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


def zakleni() -> Optional[QLockFile]:
    """Vrne zaklep, ce je ta proces prva kopija; sicer None. Zapusceni zaklep (mrtev proces) prevzame."""
    zaklep = QLockFile(os.path.join(QDir.tempPath(), ime() + ".lock"))
    zaklep.setStaleLockTime(0)
    if zaklep.tryLock(0):
        return zaklep
    if zaklep.removeStaleLockFile() and zaklep.tryLock(0):
        return zaklep
    return None


def predaj_prvemu(razdelek: str, ozadje: bool, cakaj_ms: int = 4000) -> bool:
    """Tece ze druga kopija: ji predamo razdelek (prva se lahko se zaganja, zato nekaj casa poskusamo)."""
    import time
    konec = time.monotonic() + cakaj_ms / 1000.0
    while True:
        vticnica = QLocalSocket()
        vticnica.connectToServer(ime())
        if vticnica.waitForConnected(300):
            vticnica.write(json.dumps({"razdelek": razdelek, "ozadje": ozadje}).encode("utf-8") + b"\n")
            vticnica.waitForBytesWritten(1000)
            vticnica.disconnectFromServer()
            return True
        if time.monotonic() >= konec:
            return False
        time.sleep(0.2)


def streznik(okno) -> QLocalServer:
    QLocalServer.removeServer(ime())
    streznik = QLocalServer(okno)
    streznik.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)

    def ob_povezavi() -> None:
        while streznik.hasPendingConnections():
            v = streznik.nextPendingConnection()
            v.readyRead.connect(lambda v=v: ob_podatkih(v))

    def ob_podatkih(v: QLocalSocket) -> None:
        try:
            sporocilo = json.loads(bytes(v.readAll()).decode("utf-8", "replace").strip().splitlines()[0])
        except (ValueError, IndexError):
            sporocilo = {}
        v.disconnectFromServer()
        if sporocilo.get("ozadje"):
            return  # samodejni zagon v ozadju: prva kopija ze tece, okna ne vsiljujemo
        okno.prebudi(str(sporocilo.get("razdelek") or ""))

    streznik.newConnection.connect(ob_povezavi)
    streznik.listen(ime())
    return streznik
