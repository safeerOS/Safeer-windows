"""Meritev poti do sosednjega sredisca (Link Mesh): zamik, nihanje in izgube iz pingov WebSocket.

Ping (0x9) nosi 12 bajtov '>IQ': zaporedno stevilko in nas cas v mikrosekundah. Vsak obstojeci sosed tovor
pinga vrne nespremenjen v pongu (link_ws.py, link_hub.WsOdjemalec._pong, HubStreznik.kt, OkHttp, Windows), zato
ura druge strani ni potrebna: cas meri samo nasa monotona ura. Prazen ping (stari utrip, tisina) se ne razclenjuje.

Cist modul: brez vticnic in niti, ura je vstavljena (preizkusi tecejo brez cakanja), stanje pod eno kljucavnico -
pong pride iz bralne niti, ping gre iz pisalne, stanje bere Hub.

Na povezavo:
  rtt_ms          EWMA zamika (alfa 0,25)
  min_ms          najmanjsi zamik; vzorci, poslani med polno pisalno vrsto, ne stejejo (cakali so za sporocili do 1 MiB)
  jitter_ms       EWMA |razlike zaporednih zamikov|
  izgube          sonde brez odgovora med zadnjimi 20; zgresena je sele po ROK = max(5 s, 4 * EWMA)
  zaporedno_brez  zgresene zapored
  odgovoril       ali je povezava kdaj odgovorila
  pot             'lan', 'rele' (naslov je zanka - krajevni konec Global Linka) ali 'neposredno' (zanka, ki je
                  krajevni konec neposredne poti od zunaj - core/link_neposredno.py jo oznaci po vratih)

`mrtva` je tu definirana, uporablja pa jo sele 4. faza: v 1. fazi povezave zaradi meritve nikoli ne zapremo.
"""

from __future__ import annotations

import collections
import struct
import threading
import time
from typing import Callable, Optional, Tuple

#: Oblika tovora: zaporedna stevilka (32 bitov) in cas posiljatelja v mikrosekundah (64 bitov).
OBLIKA = ">IQ"
DOLZINA = struct.calcsize(OBLIKA)
_MASKA_SEQ = 0xFFFFFFFF
_MASKA_US = 0xFFFFFFFFFFFFFFFF
#: Utez novega vzorca v EWMA zamika in nihanja.
ALFA = 0.25
#: Sonda je zgresena sele, ko odgovora ni toliko casa (in vsaj stirikratnik obicajnega zamika).
ROK_NAJMANJ_S = 5.0
#: Okno sond, v katerem stejemo izgube.
OKNO_SOND = 20
#: Povezava, ki je ze odgovarjala in je zgresila toliko sond zapored, je mrtva (uporablja 4. faza).
MRTVA_PO = 3
#: Najvec hkrati odprtih sond (ce sosed molci, vrsta ne raste v nedogled).
NAJVEC_ODPRTIH = 64


def paket(seq: int, t_us: int) -> bytes:
    """Tovor pinga: '>IQ' (zaporedna stevilka, cas v mikrosekundah)."""
    return struct.pack(OBLIKA, int(seq) & _MASKA_SEQ, int(t_us) & _MASKA_US)


def razpakiraj(podatki) -> Optional[Tuple[int, int]]:
    """(seq, t_us) iz tovora ponga; None za vse, kar ni natanko 12 bajtov (prazen ping, tuj tovor)."""
    try:
        podatki = bytes(podatki)
    except (TypeError, ValueError):
        return None
    if len(podatki) != DOLZINA:
        return None
    seq, t_us = struct.unpack(OBLIKA, podatki)
    return seq, t_us


def _us(t: float) -> int:
    return int(round(t * 1_000_000)) & _MASKA_US


#: Krajevne povezave (127.0.0.1) neposredne poti od zunaj in releja, po vratih druge strani zanke: obe sta zanka,
#: razlikuje ju samo ta zapis (core/link_neposredno.py). Brez zapisa je zanka 'rele' kot doslej.
#: Brez stevilske meje (prej 4096: pri vec kot 4096 hkratnih tunelih - podjetje, tisoc naprav po ~6 povezav - bi
#: najstarejsi tunel dobil napacno oznako »rele« in Hub bi izbiral slabso pot). Kljuc so vrata zanke, zato zapisov
#: nikoli ni vec kot 65536; vsak tunel ob koncu svoj zapis odstrani (odznaci_zanko).
_ZANKE: dict = {}
_ZANKE_ZAKLEP = threading.Lock()
#: Vrstni red poti (vecje = boljse): domace omrezje, neposredno od zunaj, rele.
RANG_POTI = {"rele": 0, "neposredno": 1, "lan": 2}


def oznaci_zanko(vrata: int, pot: str) -> None:
    if not vrata:
        return
    with _ZANKE_ZAKLEP:
        _ZANKE[int(vrata)] = pot


def odznaci_zanko(vrata: int) -> None:
    with _ZANKE_ZAKLEP:
        _ZANKE.pop(int(vrata or 0), None)


def pot_zanke(vrata: int) -> str:
    """Oznaka krajevne povezave po vratih druge strani zanke ('' = ni oznacena)."""
    with _ZANKE_ZAKLEP:
        return _ZANKE.get(int(vrata or 0), "")


def pot_vticnika(naslov: str, vticnik=None, konec: str = "getpeername") -> str:
    """Kot pot_naslova, le da zanko z oznako (neposredna pot od zunaj) prepozna po vratih vticnice: `konec` je
    "getpeername" (dohodna povezava: druga stran zanke je vhod ali krajevni konec) ali "getsockname" (odhodna)."""
    pot = pot_naslova(naslov)
    if pot != "rele" or vticnik is None:
        return pot
    try:
        vrata = getattr(vticnik, konec)()[1]
    except Exception:  # noqa: BLE001 - zaprta ali lazna vticnica
        return pot
    return pot_zanke(vrata) or pot


def pot_naslova(naslov: str) -> str:
    """'rele', ce naslov kaze na to napravo (127.x, ::1, localhost: krajevni konec releja), sicer 'lan'.

    Isto pravilo kot link_mesh._je_zanka; tu brez uvoza, ker je modul cist in ga uporablja tudi link_ws."""
    naslov = str(naslov or "").strip()
    if "://" in naslov:
        from urllib.parse import urlparse
        try:
            gostitelj = urlparse(naslov).hostname or ""
        except ValueError:
            gostitelj = ""
    else:
        gostitelj = naslov.strip("[]")
    if gostitelj.startswith("::ffff:"):
        gostitelj = gostitelj[7:]                # IPv4 v naslovu IPv6 (dvojni sklad)
    zanka = gostitelj == "localhost" or gostitelj == "::1" or gostitelj.startswith("127.")
    return "rele" if zanka else "lan"


class MeritevPoti:
    """Meritev ene sosednje povezave."""

    def __init__(self, pot: str = "lan", ura: Callable[[], float] = time.monotonic) -> None:
        self.pot = pot
        self.ura = ura
        self._zaklep = threading.Lock()
        self._seq = 0
        #: Odprte sonde: seq -> (cas poslanja, cas v us iz tovora, ali je pisalna vrsta takrat cakala).
        self._odprti: "collections.OrderedDict[int, tuple]" = collections.OrderedDict()
        #: Izid zadnjih OKNO_SOND sond: True = odgovor, False = zgresena.
        self._izidi: collections.deque = collections.deque(maxlen=OKNO_SOND)
        self.rtt_ms: Optional[float] = None
        self.min_ms: Optional[float] = None
        self.jitter_ms: Optional[float] = None
        self._zadnji_rtt: Optional[float] = None
        self.zaporedno_brez = 0
        self.odgovoril = False
        self.sond = 0
        self.odgovorov = 0
        self._zadnji_odgovor: Optional[float] = None
        #: Delez ponovno poslanega (TCP_INFO, tcp()), samo na povezavah v domacem omrezju.
        self.delez_retrans: Optional[float] = None
        self._tcp_prvi: Optional[dict] = None

    # ------------------------------------------------------------------ sonde

    def rok_s(self) -> float:
        """Kdaj je sonda zgresena: vsaj ROK_NAJMANJ_S, na pocasni poti stirikratnik obicajnega zamika."""
        ewma = self.rtt_ms
        return max(ROK_NAJMANJ_S, 4.0 * ewma / 1000.0) if ewma is not None else ROK_NAJMANJ_S

    def poslano(self, seq: int, t: Optional[float] = None, zaseden: bool = False) -> None:
        """Sonda `seq` je odsla ob `t` (nasa ura). Tovor mora biti paket(seq, t v us) - kot ga sestavi sonda().
        `zaseden`: v pisalni vrsti so cakala sporocila; zamik te sonde ne steje v min_ms."""
        t = self.ura() if t is None else float(t)
        with self._zaklep:
            self._odprti[int(seq) & _MASKA_SEQ] = (t, _us(t), bool(zaseden))
            self.sond += 1
            while len(self._odprti) > NAJVEC_ODPRTIH:
                self._odprti.popitem(last=False)
                self._zgresena()

    def sonda(self, zaseden: bool = False) -> bytes:
        """Nova sonda: zabelezi jo in vrne tovor pinga."""
        t = self.ura()
        with self._zaklep:
            self._seq = (self._seq + 1) & _MASKA_SEQ
            seq = self._seq
        self.poslano(seq, t, zaseden)
        return paket(seq, _us(t))

    def pong(self, podatki, t: Optional[float] = None) -> Optional[float]:
        """Pong s tovorom nase sonde: vrne izmerjeni zamik v ms. Neznano, podvojeno ali prepozno ter prazen ali tuj
        tovor ne spremeni zamika in vrne None.

        Prepozen (po ROK) je zgresen, tudi ce ga preveri() se ni prestel: zgresena pomeni »brez odgovora v ROK«, ne
        glede na to, kdaj pogledamo. Vecsekundni zamik bi sicer napihnil EWMA in nihanje ter z njima ROK."""
        r = razpakiraj(podatki)
        if r is None:
            return None
        t = self.ura() if t is None else float(t)
        seq, t_us = r
        with self._zaklep:
            self._preveri(t)
            odprta = self._odprti.get(seq)
            if odprta is None or odprta[1] != t_us:
                return None
            del self._odprti[seq]
            rtt = max(0.0, (t - odprta[0]) * 1000.0)
            if self._zadnji_rtt is not None:
                razlika = abs(rtt - self._zadnji_rtt)
                self.jitter_ms = razlika if self.jitter_ms is None else self.jitter_ms + ALFA * (razlika - self.jitter_ms)
            self._zadnji_rtt = rtt
            self.rtt_ms = rtt if self.rtt_ms is None else self.rtt_ms + ALFA * (rtt - self.rtt_ms)
            if not odprta[2] and (self.min_ms is None or rtt < self.min_ms):
                self.min_ms = rtt
            self._izidi.append(True)
            self.zaporedno_brez = 0
            self.odgovoril = True
            self.odgovorov += 1
            self._zadnji_odgovor = t
            return rtt

    def preveri(self, t: Optional[float] = None) -> int:
        """Sonde brez odgovora dlje od ROK so zgresene. Vrne, koliko jih je zgresenih na novo."""
        t = self.ura() if t is None else float(t)
        with self._zaklep:
            return self._preveri(t)

    def _preveri(self, t: float) -> int:
        """Klice se pod kljucavnico."""
        rok = self.rok_s()
        zgresene = [s for s, o in self._odprti.items() if t - o[0] >= rok]
        for seq in zgresene:
            del self._odprti[seq]
            self._zgresena()
        return len(zgresene)

    def _zgresena(self) -> None:
        """Klice se pod kljucavnico."""
        self._izidi.append(False)
        self.zaporedno_brez += 1

    def tcp(self, podatki: Optional[dict]) -> None:
        """Meritev TCP_INFO vticnice te povezave (link_vticnik.tcp_info). Delez ponovno poslanega od prve meritve
        dalje; samo v domacem omrezju - prek releja je vticnica zanka in jedro ne vidi poti."""
        if not podatki or self.pot != "lan":
            return
        from core.link_vticnik import delez_retrans
        with self._zaklep:
            if self._tcp_prvi is None:
                self._tcp_prvi = dict(podatki)
                return
            d = delez_retrans(self._tcp_prvi, podatki)
            if d is not None:
                self.delez_retrans = d

    # ------------------------------------------------------------------ stanje

    @property
    def izgube(self) -> int:
        with self._zaklep:
            return sum(1 for i in self._izidi if not i)

    @property
    def mrtva(self) -> bool:
        """Povezava je odgovarjala, zdaj pa je zgresila MRTVA_PO sond zapored. (Uporablja sele 4. faza.)"""
        with self._zaklep:
            return self.odgovoril and self.zaporedno_brez >= MRTVA_PO

    def stanje(self) -> dict:
        def ms(v):
            return None if v is None else round(v, 1)
        with self._zaklep:
            zdaj = self.ura()
            return {"pot": self.pot, "rtt_ms": ms(self.rtt_ms), "min_ms": ms(self.min_ms),
                    "jitter_ms": ms(self.jitter_ms), "izgube": sum(1 for i in self._izidi if not i),
                    "sond": len(self._izidi), "zaporedno_brez": self.zaporedno_brez, "odgovoril": self.odgovoril,
                    "odprtih": len(self._odprti),
                    "zadnji_odgovor_s": None if self._zadnji_odgovor is None else round(zdaj - self._zadnji_odgovor, 1),
                    "delez_retrans": None if self.delez_retrans is None else round(self.delez_retrans, 4)}


__all__ = ["paket", "razpakiraj", "pot_naslova", "pot_vticnika", "oznaci_zanko", "odznaci_zanko", "pot_zanke",
           "RANG_POTI", "MeritevPoti"]
