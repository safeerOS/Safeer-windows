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
import struct
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


#: Ohranjanje zivosti tunela: po MIROVANJE_S tisine jedro poslje preizkus vsakih PRESLEDEK_S; po POSKUSI brez odgovora
#: (skupaj ~2 min) povezava pade. Ziva povezava se nic ne spremeni (preizkus je prazen paket, odgovori ga jedro druge
#: strani) - tunel, ki ga drzi WebSocket brez prometa, ostane odprt.
ZIVOST_MIROVANJE_S = 60
ZIVOST_PRESLEDEK_S = 15
ZIVOST_POSKUSI = 4


def ohrani_zivost(vticnik, mirovanje: int = ZIVOST_MIROVANJE_S, presledek: int = ZIVOST_PRESLEDEK_S,
                  poskusi: int = ZIVOST_POSKUSI) -> None:
    """TCP keepalive (in TCP_USER_TIMEOUT, kjer je): mrtva druga stran (izklopljen telefon, izgubljeno omrezje)
    zapre povezavo v ~2 min. Brez tega je tunel brez roka (settimeout(None)) za vedno drzal niti, deskriptorje in
    mesto med NAJVEC_TUNELOV."""
    moznosti = [(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)]
    for ime, vrednost in (("TCP_KEEPIDLE", mirovanje), ("TCP_KEEPINTVL", presledek), ("TCP_KEEPCNT", poskusi),
                          # Tudi neposlani podatki (druga stran ne potrjuje) ne cakajo dlje od istega roka.
                          ("TCP_USER_TIMEOUT", (mirovanje + presledek * poskusi) * 1000)):
        if hasattr(socket, ime):
            moznosti.append((socket.IPPROTO_TCP, getattr(socket, ime), vrednost))
    for raven, moznost, vrednost in moznosti:
        try:
            vticnik.setsockopt(raven, moznost, vrednost)
        except (OSError, AttributeError, ValueError):
            pass


#: struct tcp_info (Linux): polje -> (odmik, oblika). Odmiki preverjeni na jedru 6.18 (struktura ima 280 B).
#: rtt, rttvar in min_rtt so v mikrosekundah, delivery_rate v bajtih na sekundo.
_TCP_INFO_POLJA = (
    ("state", 0, "B"), ("rtt_us", 68, "I"), ("rttvar_us", 72, "I"), ("snd_cwnd", 80, "I"),
    ("total_retrans", 100, "I"), ("segs_out", 136, "I"), ("neposlano", 144, "I"), ("min_rtt_us", 148, "I"),
    ("data_segs_out", 156, "I"), ("delivery_rate", 160, "Q"), ("bytes_sent", 200, "Q"),
    ("bytes_retrans", 208, "Q"))
_TCP_INFO_DOLZINA = 280
#: Brez teh bajtov (do vkljucno total_retrans) meritev nima smisla.
_TCP_INFO_NAJMANJ = 104


def tcp_info(vticnik) -> Optional[dict]:
    """Stanje povezave TCP po jedru (TCP_INFO): zamik, okno, ponovitve, bajti, ki se cakajo v jedru.

    Samo branje (getsockopt) - na povezavi ne spremeni nicesar. Deluje tudi na VarnaTls (getsockopt gre na
    ovito vticnico). Razclenimo samo polja, ki jih vrnjena dolzina res pokrije (starejse jedro vrne manj).
    None: vticnica ni TCP (npr. AF_UNIX), sistem TCP_INFO ne pozna, buffer je prekratek ali napaka."""
    opcija = getattr(socket, "TCP_INFO", None)
    if opcija is None:
        return None
    try:
        if getattr(vticnik, "family", None) not in (socket.AF_INET, socket.AF_INET6):
            return None
        surovo = vticnik.getsockopt(socket.IPPROTO_TCP, opcija, _TCP_INFO_DOLZINA)
    except (OSError, AttributeError, ValueError, TypeError):
        return None
    if not isinstance(surovo, (bytes, bytearray)) or len(surovo) < _TCP_INFO_NAJMANJ:
        return None
    izid = {}
    for ime, odmik, oblika in _TCP_INFO_POLJA:
        konec = odmik + struct.calcsize("=" + oblika)
        if konec <= len(surovo):
            izid[ime] = struct.unpack_from("=" + oblika, surovo, odmik)[0]
    return izid


def delez_retrans(prej: Optional[dict], zdaj: Optional[dict]) -> Optional[float]:
    """Delez ponovno poslanega med dvema meritvama tcp_info: d(bytes_retrans)/d(bytes_sent).

    Kjer bajtov ni (starejse jedro), d(total_retrans)/d(data_segs_out). Nikoli segs_out: ta steje tudi gole
    potrditve (izmerjeno: segs_out 14, data_segs_out 12) in bi delez umetno znizal. None: ni podatkov ali prometa."""
    if not prej or not zdaj:
        return None
    for stevec, imenovalec in (("bytes_retrans", "bytes_sent"), ("total_retrans", "data_segs_out")):
        if all(k in prej and k in zdaj for k in (stevec, imenovalec)):
            d_imen = zdaj[imenovalec] - prej[imenovalec]
            if d_imen <= 0:
                return None
            return max(0.0, min(1.0, (zdaj[stevec] - prej[stevec]) / float(d_imen)))
    return None


# ---------------------------------------------------------------------------------------------- sprejem s pozdravom

#: Toliko povezav hkrati sme biti v rokovanju TLS in pozdravu (deljenje zaslona, zvok na napravo). Ko jih je vec, se
#: zapre NAJSTAREJSA: prava naprava rokovanje in pozdrav opravi v nekaj ms, tiha povezava pa caka - nova povezava
#: tako vedno dobi mesto, napadalec pa bi moral odpirati povezave hitreje, kot traja rokovanje prave naprave.
NAJVEC_HKRATNIH_POZDRAVOV = 8
#: Trda meja zivih niti pozdrava (tudi izrinjenih, ki se se zapirajo): cez njo se nova povezava zapre takoj, ne dobi
#: niti - poplava povezav ne sme porabiti niti in deskriptorjev celega procesa (en proces, core/en_proces.py).
NAJVEC_NITI_POZDRAVA = 2 * NAJVEC_HKRATNIH_POZDRAVOV


def _zbudi_tiho(s) -> None:
    """Samo shutdown: rokovanje ali branje v niti, ki vticnico ima, se takoj zbudi z napako, stevilka deskriptorja pa
    ostane njena, dokler je ne zapre ona - close iz druge niti bi stevilko sprostil in jedro bi jo lahko takoj dalo
    drugi povezavi ali datoteki istega procesa, ki bi jo nit nato zaprla (pregled 72d1d79)."""
    if s is None:
        return
    try:
        s.shutdown(socket.SHUT_RDWR)
    except Exception:  # noqa: BLE001
        pass


def _zapri_tiho(s) -> None:
    if s is None:
        return
    try:
        s.shutdown(socket.SHUT_RDWR)
    except Exception:  # noqa: BLE001
        pass
    try:
        s.close()
    except Exception:  # noqa: BLE001
        pass


def sprejmi_s_pozdravom(posluh, ctx, pozdrav_velja, preberi_vrstico, konec: float, rok_rokovanja: float,
                        najvec_hkrati: int = NAJVEC_HKRATNIH_POZDRAVOV, prej=None, presledek: float = 0.25,
                        ob_sprejemu=None):
    """Sprejema povezave do `konec` (time.monotonic) in vsako - rokovanje TLS in vrstica pozdrava - obdela v svoji niti,
    najvec `najvec_hkrati` hkrati (cez to se zapre najstarejsa). Vrne prvo povezavo, katere pozdrav velja
    (pozdrav_velja(vrstica)), ali None.

    Prej se je vsaka povezava obdelala po vrsti z rokom ROKOVANJE_S: dve ali tri tihe povezave v omrezju so pokrile ves
    cas cakanja in televizor se ni mogel povezati (neodvisni pregled 19. 10. 2026). Vsaka povezava ima svoj rok
    `rok_rokovanja`; povezava, sprejeta tik pred `konec`, ga dobi celega (zanka nanjo pocaka).
    `prej()`: med cakanjem, ce vrne kaj drugega kot None, se to vrne takoj (npr. povezava, ki jo je prevzel Hub).
    `ob_sprejemu(surov)`: nastavitev vticnice pred rokovanjem (npr. brez_zamika). Napaka posluha (zaprt) gre klicatelju.
    """
    zaklep = threading.Lock()
    najden = threading.Event()
    #: Povezave v rokovanju: kljuc -> [trenutna vticnica (surova, po rokovanju TLS ovita), cas sprejema].
    v_teku: dict = {}
    stanje = {"koncano": False, "izid": None, "st": 0, "niti": 0}

    def obdelaj(kljuc: int, surov) -> None:
        odjemalec = None
        try:
            rok = time.monotonic() + rok_rokovanja
            surov.settimeout(rok_rokovanja)        # rokovanje: CPython ga omeji v celoti, ne po branjih
            if ob_sprejemu is not None:
                ob_sprejemu(surov)
            # wrap_socket surovo vticnico takoj odklopi (detach), rokovanje pa tece sele potem: ovito vticnico vpisemo,
            # PREDEN se rokovanje zacne - izrinjanje mora zapreti njo, sicer povezava in nit zivita do roka
            # (koncni pregled b8e39da).
            odjemalec = ctx.wrap_socket(surov, server_side=True, do_handshake_on_connect=False)
            with zaklep:
                if kljuc not in v_teku:
                    raise OSError("izrinjena")
                v_teku[kljuc][0] = odjemalec
            odjemalec.do_handshake()
            vrstica = preberi_vrstico(odjemalec, rok=rok)
            if pozdrav_velja(vrstica):
                with zaklep:
                    if not stanje["koncano"] and stanje["izid"] is None and kljuc in v_teku:
                        odjemalec.settimeout(rok_rokovanja)   # glava seje gre ven s celim rokom, ne z ostankom
                        stanje["izid"] = odjemalec
                        v_teku.pop(kljuc, None)
                        najden.set()
                        return
        except Exception:  # noqa: BLE001 - tuja ali izrinjena povezava ne sme podreti cakanja
            pass
        finally:
            with zaklep:
                stanje["niti"] -= 1
        with zaklep:
            v_teku.pop(kljuc, None)
        _zapri_tiho(odjemalec if odjemalec is not None else surov)

    prevzeto = None
    try:
        while not najden.is_set():
            if prej is not None:
                prevzeto = prej()
                if prevzeto is not None:
                    break
            zdaj = time.monotonic()
            if zdaj >= konec:
                with zaklep:
                    ostalo = len(v_teku)
                if ostalo == 0 or zdaj >= konec + rok_rokovanja:
                    break
                najden.wait(0.05)
                continue
            posluh.settimeout(max(0.05, min(presledek, konec - zdaj)))
            try:
                surov, _ = posluh.accept()
            except socket.timeout:
                continue
            izrinjena = None
            with zaklep:
                prevec_niti = stanje["niti"] >= NAJVEC_NITI_POZDRAVA
            if prevec_niti:
                _zapri_tiho(surov)                  # izrinjene se se zapirajo: nova povezava ne dobi niti
                continue
            with zaklep:
                stanje["niti"] += 1
                if len(v_teku) >= najvec_hkrati:
                    najstarejsa = min(v_teku, key=lambda k: v_teku[k][1])
                    izrinjena = v_teku.pop(najstarejsa)[0]
                stanje["st"] += 1
                kljuc = stanje["st"]
                v_teku[kljuc] = [surov, time.monotonic()]
            if izrinjena is not None:
                _zbudi_tiho(izrinjena)              # njena nit se zbudi z napako in jo SAMA zapre
            try:
                threading.Thread(target=obdelaj, args=(kljuc, surov), name="safeer-pozdrav", daemon=True).start()
            except RuntimeError:                    # sistem niti ne da: povezava odpade, stetje ostane pravo
                with zaklep:
                    stanje["niti"] -= 1
                    v_teku.pop(kljuc, None)
                _zapri_tiho(surov)
    finally:
        with zaklep:
            stanje["koncano"] = True          # niti, ki koncajo pozneje, svojo povezavo zaprejo
            izid = stanje["izid"]
    if prevzeto is not None:
        _zapri_tiho(izid)                    # hkrati je prisla se neposredna povezava: velja prevzeta
        return prevzeto
    return izid
