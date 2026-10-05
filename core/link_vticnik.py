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

Pisanje ima lahko svojo casovno omejitev (`nastavi_rok_pisanja`): pri pretoku v zivo (slika, zvok) sme
bralna nit cakati poljubno dolgo - televizor med gledanjem ne posilja nicesar -, pisanje pa ne: kdor
toliko casa ne vzame nobenega bajta, ga ni vec.

Ce se `sendall` konca z napako ali omejitvijo, vticnica ne pise vec: OpenSSL ima takrat zapis ze
pripravljen (in morda na pol poslan), drugacni podatki za njim bi se zlepili z njegovim ostankom in
prejemnik bi dobil pokvarjen tok. Naslednji `sendall` zato takoj javi napako povezave.

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
#: Oznaka: pisanje nima svoje omejitve in uporablja isto kot branje.
_KOT_BRANJE = object()
#: Klici, ki bi brali ali pisali naravnost na oviti vticnici - mimo kljucavnice in v neblokirajocem nacinu.
#: Namesto tihe tekme (ali `makefile`, ki vrne napako sredi branja) jih zavrnemo takoj.
_MIMO_KLJUCAVNICE = frozenset((
    "makefile", "read", "write", "recvfrom", "recvfrom_into", "recvmsg", "recvmsg_into",
    "sendto", "sendmsg", "sendfile", "do_handshake", "unwrap", "detach", "dup"))


class VarnaTls:
    """`ssl.SSLSocket` za eno bralno in eno ali vec pisalnih niti."""

    def __init__(self, vticnik: ssl.SSLSocket) -> None:
        self._s = vticnik
        #: Casovna omejitev kot pri navadni vticnici: None = brez, sicer sekunde za en klic.
        self._cas: Optional[float] = vticnik.gettimeout()
        #: Omejitev za en `sendall`; dokler je klicatelj ne nastavi posebej, velja ista kot za branje.
        self._cas_pisanja = _KOT_BRANJE
        vticnik.setblocking(False)
        self._zaklep = threading.Lock()      # en klic OpenSSL naenkrat (klic in njegova napaka skupaj)
        self._pisanje = threading.Lock()     # cel sendall: okvirja dveh niti se ne prepleteta
        self._zaprta = False
        #: `sendall` se ni koncal (napaka ali omejitev): zapis TLS je ostal na pol, pisati ne smemo vec.
        self._nedokoncan_zapis = False

    # ------------------------------------------------------------------ casovna omejitev

    def settimeout(self, cas: Optional[float]) -> None:
        self._cas = None if cas is None else float(cas)

    def gettimeout(self) -> Optional[float]:
        return self._cas

    def setblocking(self, blokira: bool) -> None:
        self._cas = None if blokira else 0.0

    def nastavi_rok_pisanja(self, cas: Optional[float]) -> None:
        """Svoja omejitev za en `sendall` (sekunde; None = brez omejitve). Branje obdrzi svojo."""
        self._cas_pisanja = None if cas is None else float(cas)

    def _rok(self, pisanje: bool = False) -> Optional[float]:
        cas = self._cas_pisanja if pisanje and self._cas_pisanja is not _KOT_BRANJE else self._cas
        return None if cas is None else time.monotonic() + cas

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

    def _beri(self, klic):
        rok = self._rok()
        while True:
            with self._zaklep:
                if self._zaprta:
                    raise ConnectionError("vticnica je zaprta")
                try:
                    return klic()
                except ssl.SSLWantReadError:
                    pisanje = False
                except ssl.SSLWantWriteError:
                    pisanje = True          # TLS mora najprej kaj poslati (npr. zamenjava kljucev)
            self._pocakaj(pisanje, rok)

    def recv(self, koliko: int, zastavice: int = 0) -> bytes:
        return self._beri(lambda: self._s.recv(koliko))

    def recv_into(self, medpomnilnik, koliko: int = 0, zastavice: int = 0) -> int:
        return self._beri(lambda: self._s.recv_into(medpomnilnik, koliko or None))

    def sendall(self, podatki, zastavice: int = 0) -> None:
        pogled = memoryview(podatki).cast("B")
        with self._pisanje:
            if self._nedokoncan_zapis:
                raise ConnectionError("prejsnje pisanje se ni koncalo; povezava ni vec uporabna")
            rok = self._rok(pisanje=True)
            try:
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
            except BaseException:
                self._nedokoncan_zapis = True
                raise

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
        if ime in _MIMO_KLJUCAVNICE:
            raise AttributeError("VarnaTls ne podpira `%s`: beri z recv(), pisi s sendall()" % ime)
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
