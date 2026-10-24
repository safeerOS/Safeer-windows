"""Pomoc ob gneci: zaznava zasicene domace linije in odpiralnik povezav za velike oddaje Safeerja.

Izmerjeno na lastnikovi liniji 18. 10. 2026 (zicno, ~116 Mbit/s dol, ~62 Mbit/s gor), zamik do 1.1.1.1:
    v mirovanju          mediana 33 ms
    med polnim prenosom  31 ms               (dol ni vrste)
    med polno oddajo     mediana 203 ms, p95 418 ms
Zamik do usmerjevalnika je med oddajo ostal 0,4 ms: vrsta (bufferbloat) je v modemu ponudnika na poti
gor, ne v domacem omrezju. Zato merimo oboje: zamik do privzetega prehoda (usmerjevalnik) in do stalnega
cilja v internetu. Gneca je, ko se zamik ZA usmerjevalnikom (internet - prehod) dvigne dalec nad
obicajnega, prehod pa ostane hiter. Ce se dvigne ze zamik do prehoda (Wi-Fi, domace omrezje), telefon ne
pomaga - tudi tunel do njega gre po istem domacem omrezju - zato tak vzorec ne steje.

Ob gneci gredo NOVE povezave skozi telefon v Safeer Linku, samo po njegovem mobilnem omrezju (Wi-Fi
telefona je na istem domacem usmerjevalniku). Obstojece povezave ostanejo, kjer so. To odloca
core/link_internet_posrednik.py (InternetUpravitelj); tu so detektor, merilnik in vmesnik za module, ki
odpirajo velike oddaje (core/link_deljenje.py, core/link_rele.py, core/link_neposredno.py).

Obremenitev: en paket ICMP (ali eno rokovanje TCP, ce ICMP ni dovoljen) do prehoda in en do cilja vsakih
INTERVAL_S - priblizno 100 B/s. Meri samo, kadar je pomoc ob gneci vklopljena in je telefon doma.
"""

from __future__ import annotations

import collections
import ipaddress
import os
import socket
import struct
import sys
import threading
import time
from typing import Callable, Deque, Dict, List, Optional, Tuple

#: Stalni cilj v internetu (isti kot pri meritvi 18. 10. 2026) in nadomestni, ce prvi ne odgovarja.
CILJI_INTERNETA = ("1.1.1.1", "9.9.9.9")
#: Vrata za meritev s TCP, kadar ICMP brez pravic ni dovoljen (net.ipv4.ping_group_range).
VRATA_INTERNETA = 443
VRATA_PREHODA = (53, 80, 443)
#: En vzorec vsaki 2 s: gneca se zazna v ~8-10 s, obremenitev ostane zanemarljiva.
INTERVAL_S = 2.0
ROK_PREHODA_S = 0.5
#: Med oddajo je bil p95 418 ms; vzorec brez odgovora v 1,5 s steje kot zelo visok (ce prehod odgovarja).
ROK_INTERNETA_S = 1.5
#: Prehod pocasnejsi od tega: tezava je v domacem omrezju (Wi-Fi), telefon ne pomaga. Vzorec ne steje.
#: Izmerjeno: zicno 0,4 ms tudi med polno oddajo; Wi-Fi obicajno nekaj ms.
PREHOD_NAJVEC_MS = 30.0
#: Osnova = 10. percentil zamika za usmerjevalnikom v zadnjih OSNOVA_VZORCEV vzorcih brez gneci (5 min).
OSNOVA_PERCENTIL = 10
OSNOVA_VZORCEV = 150
#: Pred toliko vzorci (20 s) osnove ni in gnece ne razglasimo.
OSNOVA_NAJMANJ = 10
#: Visok vzorec: vsaj osnova + 80 ms in vsaj 3 x osnova. Pri osnovi 33 ms je to 113 ms - mediana med
#: oddajo (203 ms) je dalec nad, mirovanje (33 ms) in prenos (31 ms) dalec pod. +80 ms varuje hitre linije
#: (osnova 10 ms: x3 bi bil samo 30 ms, kar doseze ze nihanje), x3 pocasne (osnova 60 ms -> 180 ms).
PRIRASTEK_VSTOP_MS = 80.0
FAKTOR_VSTOP = 3.0
#: Nizek vzorec (za konec gnece): pod osnova + 40 ms oziroma 2 x osnova (pri 33 ms: 73 ms). Med pragovoma
#: stanje ostane, kakrsno je (histereza) - zamik okoli 90 ms gnece ne zacne in je ne konca.
PRIRASTEK_IZSTOP_MS = 40.0
FAKTOR_IZSTOP = 2.0
#: Gneca se zacne, ko je v zadnjih VSTOP_OKNO vzorcih vsaj VSTOP_VISOKIH visokih (en sunek je ne sprozi).
VSTOP_OKNO = 5
VSTOP_VISOKIH = 4
#: Gneca se konca po toliko zaporednih nizkih vzorcih (16 s): kratek premor v oddaji je ne konca.
IZSTOP_ZAPOREDNIH = 8
#: Oznaka oddaje (krajevna izvorna vrata) velja toliko casa - do sprejema na krajevnem koncu releja.
OZNAKA_ODDAJE_S = 60.0


def _dnevnik(besedilo: str) -> None:
    """Napake in spremembe stanja samo v dnevnik (stderr -> sled.log), uporabniku nic."""
    try:
        print("[SafeerInternet] " + besedilo, file=sys.stderr, flush=True)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------- detektor (brez omrezja)

def percentil(vrednosti, p: float) -> float:
    urejene = sorted(vrednosti)
    if not urejene:
        raise ValueError("ni vrednosti")
    i = min(len(urejene) - 1, max(0, int(round((p / 100.0) * (len(urejene) - 1)))))
    return urejene[i]


def pragova(osnova_ms: float) -> Tuple[float, float]:
    """(prag za visok vzorec, prag za nizek vzorec) pri dani osnovi - oba za zamik za usmerjevalnikom."""
    vstop = max(osnova_ms + PRIRASTEK_VSTOP_MS, osnova_ms * FAKTOR_VSTOP)
    izstop = max(osnova_ms + PRIRASTEK_IZSTOP_MS, osnova_ms * FAKTOR_IZSTOP)
    return vstop, izstop


class Detektor:
    """Iz zaporedja vzorcev (zamik do prehoda, zamik do interneta) presodi, ali je domaca linija zasicena.

    Cist razred: brez vticnic, niti in ure - preizkusi mu podajo sinteticna zaporedja."""

    def __init__(self) -> None:
        self.gneca = False
        self._osnova: Deque[float] = collections.deque(maxlen=OSNOVA_VZORCEV)
        self._zadnji: Deque[bool] = collections.deque(maxlen=VSTOP_OKNO)
        self._nizkih = 0
        self.od = 0.0
        self.zadnji_internet_ms: Optional[float] = None
        self.zadnji_prehod_ms: Optional[float] = None
        self.vzorcev = 0

    def ponastavi(self) -> None:
        """Drugo omrezje (drug prehod): stara osnova ne velja vec."""
        self.gneca = False
        self._osnova.clear()
        self._zadnji.clear()
        self._nizkih = 0

    def osnova(self) -> Optional[float]:
        if len(self._osnova) < OSNOVA_NAJMANJ:
            return None
        return max(1.0, percentil(self._osnova, OSNOVA_PERCENTIL))

    def dodaj(self, prehod_ms: Optional[float], internet_ms: Optional[float], zdaj: float = 0.0) -> bool:
        """En vzorec. `None` = brez odgovora v roku. Vrne, ali je zdaj gneca."""
        self.vzorcev += 1
        self.zadnji_prehod_ms, self.zadnji_internet_ms = prehod_ms, internet_ms
        if prehod_ms is not None and prehod_ms > PREHOD_NAJVEC_MS:
            return self.gneca                 # pocasno je ze domace omrezje: vzorec ne pove nic o liniji
        if internet_ms is None and prehod_ms is None:
            return self.gneca                 # nic ne odgovarja (izpad omrezja): to presodi Sonda, ne mi
        zunaj = max(0.0, (ROK_INTERNETA_S * 1000.0 if internet_ms is None else internet_ms) - (prehod_ms or 0.0))
        osnova = self.osnova()
        if osnova is None:
            if internet_ms is not None:
                self._osnova.append(zunaj)
            return self.gneca
        vstop, izstop = pragova(osnova)
        if not self.gneca:
            if internet_ms is not None:
                self._osnova.append(zunaj)
            self._zadnji.append(zunaj >= vstop)
            if sum(self._zadnji) >= VSTOP_VISOKIH:
                self.gneca = True
                self.od = zdaj
                self._nizkih = 0
        else:
            # Med gneco osnova miruje: dolga oddaja bi jo sicer dvignila in gneca bi »izginila«.
            self._nizkih = self._nizkih + 1 if zunaj < izstop else 0
            if self._nizkih >= IZSTOP_ZAPOREDNIH:
                self.gneca = False
                self._zadnji.clear()
                self._nizkih = 0
        return self.gneca

    def stanje(self) -> dict:
        osnova = self.osnova()
        return {"gneca": self.gneca,
                "osnova_ms": None if osnova is None else round(osnova, 1),
                "internet_ms": None if self.zadnji_internet_ms is None else round(self.zadnji_internet_ms, 1),
                "prehod_ms": None if self.zadnji_prehod_ms is None else round(self.zadnji_prehod_ms, 1),
                "vzorcev": self.vzorcev}


# ---------------------------------------------------------------------- merilnik

def privzeti_prehod(pot: str = "/proc/net/route") -> Optional[str]:
    """Naslov privzetega prehoda IPv4 (usmerjevalnik) iz tabele jedra; None, ce ga ni (npr. samo VPN brez prehoda)."""
    try:
        with open(pot, "r", encoding="ascii", errors="replace") as f:
            vrstice = f.read().splitlines()[1:]
    except OSError:
        return None
    najboljsi: Optional[Tuple[int, str]] = None
    for v in vrstice:
        p = v.split()
        if len(p) < 8:
            continue
        try:
            cilj, prehod, zastavice, metrika = int(p[1], 16), int(p[2], 16), int(p[3], 16), int(p[6])
        except ValueError:
            continue
        # RTF_UP (1) in RTF_GATEWAY (2), cilj 0.0.0.0
        if cilj != 0 or not prehod or (zastavice & 3) != 3:
            continue
        naslov = socket.inet_ntoa(struct.pack("<I", prehod))
        if najboljsi is None or metrika < najboljsi[0]:
            najboljsi = (metrika, naslov)
    return najboljsi[1] if najboljsi else None


class Merilnik:
    """Zamik do naslova: ICMP odmev brez pravic (SOCK_DGRAM), sicer cas rokovanja TCP (tudi zavrnitev je odgovor)."""

    def __init__(self, cilji=CILJI_INTERNETA, pot_poti: str = "/proc/net/route") -> None:
        self.cilji = tuple(cilji)
        self.pot_poti = pot_poti
        self.icmp: Optional[bool] = None       # None = se ne vemo; False = jedro ga ne dovoli
        self._zap = int.from_bytes(os.urandom(2), "big")
        self._vrata_prehoda: Dict[str, int] = {}
        self._cilj = 0
        self._brez_odgovora = 0

    @property
    def metoda(self) -> str:
        return "" if self.icmp is None else ("icmp" if self.icmp else "tcp")

    def prehod(self) -> Optional[str]:
        return privzeti_prehod(self.pot_poti)

    @staticmethod
    def _icmp_vticnica() -> Optional[socket.socket]:
        """Vticnica ICMP brez pravic; None, ce je jedro ne dovoli (EACCES - skupina ni v ping_group_range)."""
        try:
            return socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_ICMP)
        except OSError:
            return None

    def _icmp(self, naslov: str, rok: float) -> Optional[float]:
        s = self._icmp_vticnica()
        if s is None:
            self.icmp = False
            return None
        try:
            s.settimeout(rok)
            self._zap = (self._zap + 1) & 0xFFFF
            tovor = os.urandom(8)
            # Identifikator in kontrolno vsoto vpise jedro (ping socket).
            zacetek = time.monotonic()
            try:
                s.sendto(struct.pack("!BBHHH", 8, 0, 0, 0, self._zap) + tovor, (naslov, 0))
            except OSError:
                return None                     # npr. omrezje nedosegljivo: ta vzorec brez odgovora
            konec = zacetek + rok
            while True:
                ostane = konec - time.monotonic()
                if ostane <= 0:
                    return None
                s.settimeout(ostane)
                try:
                    podatki, _od = s.recvfrom(256)
                except OSError:
                    return None
                if len(podatki) >= 16 and podatki[0] == 0 and struct.unpack("!H", podatki[6:8])[0] == self._zap \
                        and podatki[8:16] == tovor:
                    return (time.monotonic() - zacetek) * 1000.0
        finally:
            s.close()

    @staticmethod
    def _tcp(naslov: str, vrata: int, rok: float) -> Optional[float]:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Takojsen RST ob zaprtju: brez TIME_WAIT in brez FIN izmenjave na vsak vzorec.
            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            s.settimeout(rok)
            zacetek = time.monotonic()
            try:
                s.connect((naslov, vrata))
            except ConnectionRefusedError:
                pass                            # RST je odgovor: pot do naslova dela
            except OSError:
                return None
            return (time.monotonic() - zacetek) * 1000.0
        finally:
            s.close()

    def rtt(self, naslov: str, rok: float, vrata: Tuple[int, ...]) -> Optional[float]:
        if self.icmp is not False:
            ms = self._icmp(naslov, rok)
            if ms is not None:
                self.icmp = True
                return ms
            if self.icmp:
                return None                     # ICMP sicer dela: to je pravi vzorec brez odgovora
        for v in vrata:
            ms = self._tcp(naslov, v, rok)
            if ms is not None:
                if self.icmp is None:
                    self.icmp = False           # ICMP je na poti filtriran, TCP odgovarja - odslej TCP
                return ms
        return None

    def rtt_prehoda(self, naslov: str) -> Optional[float]:
        if self.icmp is not False:
            ms = self.rtt(naslov, ROK_PREHODA_S, ())
            if ms is not None or self.icmp:
                return ms
        # Usmerjevalnik: najprej vrata, ki so ze odgovorila (53 - DNS ima skoraj vsak).
        znana = self._vrata_prehoda.get(naslov)
        vrstni = ((znana,) if znana else ()) + tuple(v for v in VRATA_PREHODA if v != znana)
        for v in vrstni:
            ms = self._tcp(naslov, v, ROK_PREHODA_S)
            if ms is not None:
                self._vrata_prehoda[naslov] = v
                return ms
        return None

    def rtt_interneta(self) -> Optional[float]:
        cilj = self.cilji[self._cilj % len(self.cilji)]
        ms = self.rtt(cilj, ROK_INTERNETA_S, (VRATA_INTERNETA,))
        if ms is None:
            self._brez_odgovora += 1
            if self._brez_odgovora >= 3 and len(self.cilji) > 1:
                # Cilj morda ICMP blokira: poskusimo drugega (gneca ali izpad se tako ali tako pokazeta na obeh).
                self._cilj += 1
                self._brez_odgovora = 0
        else:
            self._brez_odgovora = 0
        return ms


class Nadzornik:
    """Nit, ki vsakih INTERVAL_S izmeri vzorec in ob spremembi stanja poklice `ob_spremembi(gneca)`.

    `dovoljeno()`: ali naj zdaj sploh merimo (pomoc vklopljena, telefon doma, domaci internet dela)."""

    def __init__(self, ob_spremembi: Callable[[bool], None], merilnik: Optional[Merilnik] = None,
                 dovoljeno: Callable[[], bool] = lambda: True, ura: Callable[[], float] = time.monotonic) -> None:
        self.ob_spremembi = ob_spremembi
        self.merilnik = merilnik or Merilnik()
        self.dovoljeno = dovoljeno
        self.ura = ura
        self.detektor = Detektor()
        self._prehod: Optional[str] = None
        self._tece = False
        self._budilka = threading.Event()
        self._zaklep = threading.Lock()
        #: Detektor spreminja nit nadzornika, stanje bere vmesnik iz drugih niti.
        self._zaklep_detektorja = threading.Lock()

    @property
    def gneca(self) -> bool:
        return self.detektor.gneca

    def korak(self) -> bool:
        """En vzorec in presoja (klice ga zanka; preizkusi tudi neposredno)."""
        prehod = self.merilnik.prehod()
        if prehod != self._prehod:
            if self._prehod is not None:
                _dnevnik("gneca: drugo omrezje, nova osnova")
            self._prehod = prehod
            with self._zaklep_detektorja:
                prej = self.detektor.gneca
                self.detektor.ponastavi()
            if prej:
                self._javi(False)
        prehod_ms = self.merilnik.rtt_prehoda(prehod) if prehod else None
        internet_ms = self.merilnik.rtt_interneta()
        with self._zaklep_detektorja:
            prej = self.detektor.gneca
            zdaj = self.detektor.dodaj(prehod_ms, internet_ms, self.ura())
            st = self.detektor.stanje()
        if zdaj != prej:
            _dnevnik("gneca: %s (osnova %s ms, internet %s ms, prehod %s ms, %s)"
                     % ("zacetek" if zdaj else "konec", st["osnova_ms"], st["internet_ms"], st["prehod_ms"],
                        self.merilnik.metoda or "?"))
            self._javi(zdaj)
        return zdaj

    def _javi(self, gneca: bool) -> None:
        try:
            self.ob_spremembi(gneca)
        except Exception as e:  # noqa: BLE001
            _dnevnik("gneca: obravnava spremembe: %r" % (e,))

    def zazeni(self) -> None:
        with self._zaklep:
            if self._tece:
                return
            self._tece = True
            self._budilka.clear()
        threading.Thread(target=self._zanka, name="safeer-internet-gneca", daemon=True).start()

    def ustavi(self) -> None:
        with self._zaklep:
            self._tece = False
        self._budilka.set()
        with self._zaklep_detektorja:
            prej = self.detektor.gneca
            if prej:
                self.detektor.ponastavi()
        if prej:
            self._javi(False)

    @property
    def tece(self) -> bool:
        return self._tece

    def _zanka(self) -> None:
        while self._tece:
            try:
                if self.dovoljeno():
                    self.korak()
            except Exception as e:  # noqa: BLE001
                _dnevnik("gneca: meritev: %r" % (e,))
            self._budilka.wait(INTERVAL_S)
        self._budilka.clear()

    def stanje(self) -> dict:
        with self._zaklep_detektorja:
            st = self.detektor.stanje()
        st["metoda"] = self.merilnik.metoda
        st["meri"] = self._tece
        return st


# ---------------------------------------------------------------------- velike oddaje Safeerja

#: (host, vrata, rok) -> povezana vticnica skozi telefon ali None. Nastavi ga InternetUpravitelj, ko je pomoc
#: ob gneci vklopljena; vrne vticnico samo, ce je gneca zdaj in telefon to omogoca.
_odpiralnik: Optional[Callable[[str, int, float], Optional[socket.socket]]] = None
_oznake: Dict[int, float] = {}
_zaklep = threading.Lock()


def nastavi_odpiralnik(f: Optional[Callable[[str, int, float], Optional[socket.socket]]]) -> None:
    global _odpiralnik
    with _zaklep:
        _odpiralnik = f
        if f is None:
            _oznake.clear()


def odpiralnik() -> Optional[Callable[[str, int, float], Optional[socket.socket]]]:
    with _zaklep:
        return _odpiralnik


def _je_zanka(host: str) -> bool:
    try:
        return ipaddress.ip_address(str(host).strip("[]")).is_loopback
    except ValueError:
        return str(host).lower() == "localhost"


def _je_domaci(host: str) -> bool:
    h = str(host or "").strip("[]").lower().rstrip(".")
    if h == "localhost" or h.endswith(".local") or h.endswith(".localhost"):
        return True
    try:
        a = ipaddress.ip_address(h.split("%", 1)[0])
    except ValueError:
        return "." not in h
    return a.is_private or a.is_loopback or a.is_link_local


def oznaci_oddajo(vrata: int) -> None:
    zdaj = time.monotonic()
    with _zaklep:
        for k in [k for k, do in _oznake.items() if do <= zdaj]:
            del _oznake[k]
        _oznake[int(vrata)] = zdaj + OZNAKA_ODDAJE_S


def vzemi_oddajo(vrata: int) -> bool:
    """Ali je krajevna povezava z izvornimi vrati `vrata` velika oddaja (oznaka se porabi)."""
    with _zaklep:
        do = _oznake.pop(int(vrata or 0), 0.0)
    return do > time.monotonic()


def tcp_za_oddajo(host: str, port: int, rok: float) -> Optional[socket.socket]:
    """Vticnica skozi telefon za veliko oddajo, ce je zdaj gneca; sicer None (klicatelj gre neposredno)."""
    f = odpiralnik()
    if f is None or _je_domaci(host):
        return None
    try:
        return f(host, int(port), rok)
    except Exception as e:  # noqa: BLE001
        _dnevnik("gneca: oddaja skozi telefon: %r" % (e,))
        return None


def odpri_oddajo(naslov: Tuple[str, int], timeout: Optional[float] = None) -> socket.socket:
    """Kot socket.create_connection, za veliko oddajo Safeerja (podpis enak, da ga sprejme link_tls).

    Cilj v internetu: ob gneci skozi telefon. Krajevni konec Global Linka (127.x - rele ali neposredna pot do
    sredisca zunaj doma): povezavo oznacimo, da krajevni konec ob gneci kanal odpre skozi telefon."""
    host, port = naslov[0], int(naslov[1])
    rok = 30.0 if timeout is None else float(timeout)
    if _je_zanka(host):
        if odpiralnik() is None:
            return socket.create_connection((host, port), timeout)
        s = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("::1" if ":" in host else "127.0.0.1", 0))
            oznaci_oddajo(s.getsockname()[1])
            s.settimeout(timeout)
            s.connect((host, port))
        except Exception:
            s.close()
            raise
        return s
    t = tcp_za_oddajo(host, port, rok)
    if t is not None:
        try:
            t.settimeout(timeout)
        except OSError:
            pass
        return t
    return socket.create_connection((host, port), timeout)


def odpri_tcp_za_oddajo(host: str, port: int, rok: float) -> socket.socket:
    """Za krajevni konec Global Linka: oznacena oddaja ob gneci skozi telefon, sicer neposredno."""
    t = tcp_za_oddajo(host, port, rok)
    if t is not None:
        return t
    return socket.create_connection((host, port), rok)


__all__: List[str] = ["Detektor", "Merilnik", "Nadzornik", "pragova", "privzeti_prehod", "nastavi_odpiralnik",
                      "odpri_oddajo", "odpri_tcp_za_oddajo", "oznaci_oddajo", "vzemi_oddajo", "tcp_za_oddajo"]
