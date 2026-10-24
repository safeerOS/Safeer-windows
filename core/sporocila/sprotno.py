"""Niti kanalov v realnem casu: vsak kanal svojo nit, kar se da s potiskom namesto periodicnega branja.

- e-posta: IMAP IDLE (core/sporocila/imap_sprotno.py)
- Matrix: dolgi /sync (timeout 30 s) v zanki
- Telegram bot: dolgi getUpdates (timeout 25 s) v zanki
- ostalo (Chatwoot - spletni kljuki potrebujejo javni streznik, ki ga nimamo): poizvedba vsakih 30 s

Prej (do 15. 10. 2026) je ena nit vse kanale brala zaporedoma vsakih 120 s.
"""

from __future__ import annotations

import socket
import ssl
import threading
import time
from typing import Optional
from urllib.parse import urlsplit

#: Zamiki po napaki (s), kot pri IDLE.
ZAMIKI_S = (1, 2, 5, 10, 30, 60)
#: Dolga poizvedba, ki se vrne prehitro (streznik ne podpira cakanja): vsaj toliko med zacetki, da nit ne vrti.
NAJMANJ_MED_DOLGIMI_S = 0.5
POIZVEDBA_S = 30


def dolga_zahteva(nosilec, url: str, metoda: str = "GET", telo: Optional[bytes] = None, glave: Optional[dict] = None,
                  timeout: float = 60) -> bytes:
    """HTTP(S) zahteva, ki jo streznik zadrzi (dolga poizvedba). Povezava je shranjena v nosilcu (adapterju), da jo
    prekini_zahtevo() zapre takoj - izklop kanala ne caka do 30 s. Brez sledenja preusmeritvam (zeton v glavi ne sme
    na drug naslov), potrdilo TLS se preverja."""
    from http.client import HTTPConnection, HTTPSConnection
    from urllib.error import HTTPError
    deli = urlsplit(url)
    if deli.scheme == "https":
        povezava = HTTPSConnection(deli.hostname, deli.port or 443, timeout=timeout, context=ssl.create_default_context())
    elif deli.scheme == "http":
        povezava = HTTPConnection(deli.hostname, deli.port or 80, timeout=timeout)
    else:
        raise ValueError("Nepodprt naslov")
    if getattr(nosilec, "_prekinjeno", False):
        raise ConnectionAbortedError("kanal izklopljen")
    nosilec._tekoca = povezava
    try:
        povezava.request(metoda, (deli.path or "/") + ("?" + deli.query if deli.query else ""), body=telo, headers=glave or {})
        odgovor = povezava.getresponse()
        podatki = odgovor.read()
        if odgovor.status >= 300:
            raise HTTPError(url, odgovor.status, odgovor.reason, odgovor.headers, None)
        return podatki
    finally:
        nosilec._tekoca = None
        povezava.close()


def prekini_zahtevo(nosilec) -> None:
    """Zapre tekoco dolgo zahtevo nosilca (iz druge niti); nit, ki caka nanjo, dobi napako in se konca."""
    nosilec._prekinjeno = True
    povezava = getattr(nosilec, "_tekoca", None)
    vticnica = getattr(povezava, "sock", None)
    if vticnica is not None:
        try:
            vticnica.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


class Delavec:
    """Nit enega kanala. Podrazredi dolocijo _korak() (vrne True ob uspehu) in cas do naslednjega koraka."""

    vrsta = "poizvedba"

    def __init__(self, storitev, kanal_id: str, adapter, interval: float = POIZVEDBA_S):
        self.storitev, self.kanal_id, self.adapter = storitev, kanal_id, adapter
        self.interval = float(interval)
        self._ustavi = threading.Event()
        self._zbudi = threading.Event()
        self._nit: Optional[threading.Thread] = None
        self.stevci = {"korakov": 0, "napak": 0}

    def zazeni(self) -> None:
        if self.tece():
            return
        self._ustavi.clear()
        self._nit = threading.Thread(target=self._teci, name="safeer-sporocila-" + self.vrsta, daemon=True)
        self._nit.start()

    def tece(self) -> bool:
        return self._nit is not None and self._nit.is_alive()

    def zbudi(self) -> None:
        self._zbudi.set()

    ponovno_povezi = zbudi

    def ustavi(self, cakaj: float = 2.0) -> None:
        self._ustavi.set()
        self._zbudi.set()
        if self._nit is not None and self._nit is not threading.current_thread():
            self._nit.join(timeout=cakaj)

    def _korak(self) -> bool:
        return self.storitev.sinhroniziraj_kanal(self.kanal_id)

    def _premor(self, uspeh: bool, trajalo: float) -> float:
        return self.interval

    def _teci(self) -> None:
        poskus = 0
        while not self._ustavi.is_set():
            self._zbudi.clear()
            zacetek = time.monotonic()
            try:
                uspeh = bool(self._korak())
            except Exception:  # noqa: BLE001 - storitev napako zapise v stanje kanala
                uspeh = False
            self.stevci["korakov"] += 1
            if self._ustavi.is_set():
                break
            if uspeh:
                poskus = 0
                premor = self._premor(True, time.monotonic() - zacetek)
            else:
                self.stevci["napak"] += 1
                premor = ZAMIKI_S[min(poskus, len(ZAMIKI_S) - 1)]
                poskus += 1
            if premor > 0:
                self._zbudi.wait(premor)


class DelavecDolgaPoizvedba(Delavec):
    """Matrix /sync in Telegram getUpdates: streznik zahtevo zadrzi, dokler ni novic (ali poteka cakanja), zato
    med koraki ni premora - novo sporocilo pride v trenutku, med cakanjem pa nit spi v branju vticnice."""

    vrsta = "dolga"

    def __init__(self, storitev, kanal_id: str, adapter, cakanje_s: float):
        super().__init__(storitev, kanal_id, adapter, 0)
        self.cakanje_s = float(cakanje_s)
        adapter.dolgo_cakanje_s = self.cakanje_s
        adapter._prekinjeno = False

    def ponovno_povezi(self) -> None:
        """Novo omrezje: zahteva na stari povezavi je mrtva - zapremo jo, zanka takoj odpre novo."""
        povezava = getattr(self.adapter, "_tekoca", None)
        vticnica = getattr(povezava, "sock", None)
        if vticnica is not None:
            try:
                vticnica.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.zbudi()

    def ustavi(self, cakaj: float = 2.0) -> None:
        # Tekoco zahtevo zapremo takoj (izklop kanala ali Sporocil ne caka do 30 s).
        self.adapter.dolgo_cakanje_s = 0
        self._ustavi.set()
        prekini_zahtevo(self.adapter)
        super().ustavi(cakaj)

    def _premor(self, uspeh: bool, trajalo: float) -> float:
        return max(0.0, NAJMANJ_MED_DOLGIMI_S - trajalo)


def ustvari(storitev, kanal_id: str, adapter, interval: float = POIZVEDBA_S):
    """Pravi delavec za vrsto kanala."""
    vrsta = getattr(adapter, "vrsta", "")
    if vrsta == "email" and hasattr(adapter, "imap_streznik"):
        from .imap_sprotno import DelavecImap
        return DelavecImap(storitev, kanal_id, adapter)
    if vrsta == "matrix":
        return DelavecDolgaPoizvedba(storitev, kanal_id, adapter, 30)
    if vrsta == "telegram_bot":
        return DelavecDolgaPoizvedba(storitev, kanal_id, adapter, 25)
    return Delavec(storitev, kanal_id, adapter, interval)
