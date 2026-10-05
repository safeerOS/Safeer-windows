"""Vticnica TLS, ki jo smeta hkrati uporabljati bralna in pisalna nit.

Povezave Safeer Linka berejo v eni niti (`recv`) in pisejo v drugi (`sendall`). Navaden
`ssl.SSLSocket` tega ne prenese, kadar ima casovno omejitev - in vse nase jo imajo, ker z njo
zaznamo tisino. Vticnica je takrat pod OpenSSL neblokirajoca:

    bralna nit:   SSL_read -> »ni se podatkov« (na skupnem BIO se postavi oznaka za ponovitev)
    pisalna nit:  SSL_write v isti objekt SSL -> oznako pobrise
    bralna nit:   SSL_get_error -> brez oznake vrne SSL_ERROR_SYSCALL
    Python:       SSL_ERROR_SYSCALL razume kot konec povezave in `recv()` vrne b""

Povezava je videti zaprta, ceprav ni. Sredisce jo zato zapre, kosi na poti se izgubijo, naprave se
povezejo znova. Pri redkem prometu se to zgodi enkrat na dolgo; pri tokovih Safeer Internet
Gatewaya (megabajti v eno smer, potrditve v drugo) v nekaj sekundah. Izmerjeno v krogu 102
(tests/test_link_vticnik.py to ponovi: surova vticnica lazno konca v delcku sekunde).

Tu zato vsak klic OpenSSL tece pod isto kljucavnico in v njej nikoli ne caka: vticnica je
neblokirajoca, na podatke oziroma prostor pocakamo ZUNAJ kljucavnice (poll/select). Pisalna nit tako
ne ustavi bralne in obratno, prepletata pa se samo cela klica OpenSSL. `sendall` ostane celovit:
okvirja dveh niti se ne zmesata.

Vse drugo (fileno, getpeername, version ...) gre naravnost na ovito vticnico.
"""

from __future__ import annotations

import select
import socket
import ssl
import threading
import time
from typing import Optional

_POLL = hasattr(select, "poll")
#: Najdaljse posamezno cakanje; po njem znova preverimo, ali je vticnica se odprta.
_KORAK_S = 5.0


class VarnaTls:
    """`ssl.SSLSocket` za eno bralno in eno ali vec pisalnih niti."""

    def __init__(self, vticnik: ssl.SSLSocket) -> None:
        self._s = vticnik
        #: Casovna omejitev kot pri navadni vticnici: None = brez, sicer sekunde za en klic.
        self._cas: Optional[float] = vticnik.gettimeout()
        vticnik.setblocking(False)
        self._zaklep = threading.Lock()      # en klic OpenSSL naenkrat (klic in njegova napaka skupaj)
        self._pisanje = threading.Lock()     # cel sendall: okvirja dveh niti se ne prepleteta
        self._zaprta = False

    # ------------------------------------------------------------------ casovna omejitev

    def settimeout(self, cas: Optional[float]) -> None:
        self._cas = None if cas is None else float(cas)

    def gettimeout(self) -> Optional[float]:
        return self._cas

    def setblocking(self, blokira: bool) -> None:
        self._cas = None if blokira else 0.0

    def _rok(self) -> Optional[float]:
        return None if self._cas is None else time.monotonic() + self._cas

    def _pocakaj(self, pisanje: bool, rok: Optional[float]) -> None:
        """Pocaka, da je vticnica berljiva (ali pisljiva). Brez kljucavnice - druga nit medtem dela."""
        while True:
            if self._zaprta:
                raise ConnectionError("vticnica je zaprta")
            fd = self._s.fileno()
            if fd < 0:
                raise ConnectionError("vticnica je zaprta")
            cas = _KORAK_S
            if rok is not None:
                preostalo = rok - time.monotonic()
                if preostalo <= 0:
                    raise socket.timeout("timed out")
                cas = min(cas, preostalo)
            try:
                if _POLL:
                    p = select.poll()
                    p.register(fd, select.POLLOUT if pisanje else select.POLLIN)
                    pripravljena = bool(p.poll(max(1, int(cas * 1000))))
                else:
                    b, pi, n = select.select([] if pisanje else [fd], [fd] if pisanje else [], [fd], cas)
                    pripravljena = bool(b or pi or n)
            except (OSError, ValueError):
                raise ConnectionError("vticnica je zaprta") from None
            if pripravljena:
                return

    # ------------------------------------------------------------------ branje in pisanje

    def recv(self, koliko: int, zastavice: int = 0) -> bytes:
        rok = self._rok()
        while True:
            with self._zaklep:
                if self._zaprta:
                    raise ConnectionError("vticnica je zaprta")
                try:
                    return self._s.recv(koliko)
                except ssl.SSLWantReadError:
                    pisanje = False
                except ssl.SSLWantWriteError:
                    pisanje = True          # TLS mora najprej kaj poslati (npr. zamenjava kljucev)
            self._pocakaj(pisanje, rok)

    def sendall(self, podatki, zastavice: int = 0) -> None:
        pogled = memoryview(podatki).cast("B")
        with self._pisanje:
            rok = self._rok()
            while len(pogled):
                n, pisanje = 0, True
                with self._zaklep:
                    if self._zaprta:
                        raise ConnectionError("vticnica je zaprta")
                    try:
                        # OpenSSL po »poskusi znova« zahteva isti medpomnilnik: `pogled` se do uspeha ne spremeni.
                        n = self._s.send(pogled)
                    except ssl.SSLWantWriteError:
                        pisanje = True
                    except ssl.SSLWantReadError:
                        pisanje = False
                if n:
                    pogled = pogled[n:]
                else:
                    self._pocakaj(pisanje, rok)

    def send(self, podatki, zastavice: int = 0) -> int:
        self.sendall(podatki)
        return len(memoryview(podatki).cast("B"))

    # ------------------------------------------------------------------ konec

    def shutdown(self, kako: int) -> None:
        with self._zaklep:
            self._s.shutdown(kako)

    def close(self) -> None:
        self._zaprta = True
        with self._zaklep:
            try:
                # Nit, ki caka v poll, se zbudi sele ob shutdown; samo close je ne bi zbudil.
                self._s.shutdown(socket.SHUT_RDWR)
            except (OSError, ValueError):
                pass
            self._s.close()

    def __getattr__(self, ime: str):
        return getattr(self._s, ime)


def zavaruj(vticnik):
    """Vticnico TLS ovije v VarnaTls; navadno (ali ze ovito) vrne nespremenjeno."""
    if isinstance(vticnik, ssl.SSLSocket):
        return VarnaTls(vticnik)
    return vticnik


def brez_zamika(vticnik) -> None:
    """Izklopi Naglov algoritem: sporocila Linka so kratka in vsako naj gre takoj.

    Brez tega kratek okvir pocaka na potrditev prejsnjega (do 40 ms ob zakasnjenem ACK) - pri
    potrditvah tokov je to omejilo pretok na nekaj MB/s."""
    try:
        vticnik.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except (OSError, AttributeError, ValueError):
        pass
