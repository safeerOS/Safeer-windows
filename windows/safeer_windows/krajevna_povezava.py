"""Pogovor s QLocalServer druge kopije programa - brez QLocalSocket.

Blokirajoca cakanja QLocalSocket (waitForConnected, waitForBytesWritten, waitForReadyRead) se na Windows lahko
zataknejo za vedno: 5. 10. 2026 je nova kopija Safeer OS po posodobitvi obvisela v
QWindowsPipeWriter::consumePendingAndEmit (notranja kljucavnica Qt, PySide6 6.11.2); casovna omejitev klica ni
pomagala, stara kopija se je medtem zaprla in Safeer OS ni tekel vec.

Tu zato govorimo naravnost z operacijskim sistemom - QLocalServer poslusa na imenovani cevi (Windows) oziroma na
vticnici Unix v zacasni mapi (drugje) - v pomozni niti, z omejitvijo, ki drzi. Nit, ki obvisi na neodzivni drugi
kopiji, je ozadna in programa ne ustavi.
"""
from __future__ import annotations

import os
import threading
from typing import Optional


def pot(ime: str) -> str:
    """Kje poslusa QLocalServer z imenom `ime`."""
    if os.name == "nt":
        return "\\\\.\\pipe\\" + ime
    from PySide6.QtCore import QDir
    return os.path.join(QDir.tempPath(), ime)


def pogovor(ime: str, sporocilo: bytes, cakaj_s: float, odgovor: bool = True) -> Optional[bytes]:
    """Drugi kopiji poslje sporocilo in vrne njen odgovor (do 64 bajtov).

    None: druge kopije ni mogoce doseci (ne poslusa ali je cev zasedena).
    b"":  sporocilo je prejela, odgovora ni (zasedena, se zapira) - ali pa ga nismo cakali (`odgovor=False`).
    """
    izid: dict = {}
    naslov = pot(ime)

    def delo() -> None:
        try:
            if os.name == "nt":
                with open(naslov, "r+b", buffering=0) as cev:
                    # Povezani smo, ko se cev odpre. Zapis lahko obvisi, dokler druga stran ne bere (cev Qt nima
                    # medpomnilnika) - tudi to je »povezana, a se ne odziva«, ne »ni je«.
                    izid["povezan"] = True
                    cev.write(sporocilo)
                    if odgovor:
                        izid["odgovor"] = cev.read(64) or b""
            else:
                import socket
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as vticnica:
                    vticnica.settimeout(cakaj_s)
                    vticnica.connect(naslov)
                    izid["povezan"] = True
                    vticnica.sendall(sporocilo)
                    if odgovor:
                        izid["odgovor"] = vticnica.recv(64)
        except OSError:
            pass        # nihce ne poslusa, cev je zasedena ali prekinjena, cas je potekel: velja, kar je ze v izidu

    nit = threading.Thread(target=delo, name="safeer-krajevna-povezava", daemon=True)
    nit.start()
    nit.join(cakaj_s + 0.5)
    if not izid.get("povezan"):
        return None
    return izid.get("odgovor", b"")
