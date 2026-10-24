"""Odprti deskriptorji dolgotrajnega procesa: straza, ki pove, kaj raste, in omejitev prostih povezav strezniku.

Safeer OS (namizje, Control, Link, mediji, sporocila in splet v enem procesu) je 16. in 17. 10. 2026 po 11-14 h dela
koncal s SIGTRAP: zmanjkalo je deskriptorjev (meja 1024), GLib/WebKit ni dobil ne eventfd ne memfd. Meritev na zivem
procesu (0.4.84, 17. 10. 2026): v 7 minutah 100 vticnikov, od tega 40 dohodnih povezav na Hub (8990) z dveh naprav -
vsaka po eni zahtevi tiho odprta (keep-alive), nove pa so prihajale ~1,3 na minuto. Dvig meje (os_stabilnost) samo
odlozi padec; vzrok je kopicenje povezav, ki jih nihce ne zapre.

  * `ProsteZveze`: streznik ve, katere povezave samo cakajo na naslednjo zahtevo; ko jih ima ena naprava prevec,
    najstarejso zapre (tako ena naprava, ki povezave odpira in jih ne zapira, ne napolni procesa).
  * `Straza`: na nekaj minut presteje /proc/self/fd po vrstah in ob rasti zapise opozorilo z razclenitvijo v dnevnik
    (brez naslovov in podatkov uporabnika: samo vrste, stanja TCP in nasa vrata).
"""

from __future__ import annotations

import collections
import errno
import os
import socket
import threading
import time
from typing import Callable, Dict, Optional

# ---------------------------------------------------------------------------- stetje

_STANJA_TCP = {"01": "ESTAB", "02": "SYN_SENT", "03": "SYN_RECV", "04": "FIN_WAIT1", "05": "FIN_WAIT2",
               "06": "TIME_WAIT", "07": "CLOSE", "08": "CLOSE_WAIT", "09": "LAST_ACK", "0A": "LISTEN",
               "0B": "CLOSING"}


def stevilo(pid: str = "self") -> int:
    """Stevilo odprtih deskriptorjev procesa (-1, ce /proc ni berljiv)."""
    try:
        return len(os.listdir("/proc/%s/fd" % pid))
    except OSError:
        return -1


def _vrsta(cilj: str) -> str:
    if cilj.startswith("socket:"):
        return "socket"
    if cilj.startswith("anon_inode:"):
        return cilj[len("anon_inode:"):].strip("[]") or "anon_inode"
    if cilj.startswith("pipe:"):
        return "pipe"
    if cilj.startswith("/memfd:"):
        return "memfd"
    if cilj.startswith("/dev/"):
        return "dev"
    return "datoteka"


def _vticniki_tcp(inode: set) -> Dict[str, int]:
    """'stanje vrata' -> stevilo za vticnike TCP tega procesa. Vrata so nasa (poslusalna/streznikova) ali oddaljena
    za odhodne povezave; naslovov ne belezimo."""
    poslusa = set()
    vrstice = []
    for ime in ("tcp", "tcp6"):
        try:
            with open("/proc/self/net/" + ime, encoding="ascii") as d:
                next(d, None)
                for vrstica in d:
                    deli = vrstica.split()
                    if len(deli) > 9 and deli[9] in inode:
                        vrstice.append(deli)
                        if deli[3] == "0A":
                            poslusa.add(int(deli[1].rsplit(":", 1)[1], 16))
        except OSError:
            continue
    izid: Dict[str, int] = collections.Counter()
    for deli in vrstice:
        stanje = _STANJA_TCP.get(deli[3], deli[3])
        nasa = int(deli[1].rsplit(":", 1)[1], 16)
        njihova = int(deli[2].rsplit(":", 1)[1], 16)
        if stanje == "LISTEN":
            kljuc = "LISTEN"
        elif nasa in poslusa:
            kljuc = "%s v:%d" % (stanje, nasa)          # dohodna na nas streznik
        else:
            kljuc = "%s ->%d" % (stanje, njihova)       # odhodna
        izid[kljuc] += 1
    return dict(izid)


def razclenitev(pid: str = "self") -> dict:
    """{'skupaj': n, 'vrste': {vrsta: n}, 'tcp': {'stanje vrata': n}} za odprte deskriptorje procesa."""
    mapa = "/proc/%s/fd" % pid
    vrste: Dict[str, int] = collections.Counter()
    vticniki = set()
    try:
        imena = os.listdir(mapa)
    except OSError:
        return {"skupaj": -1, "vrste": {}, "tcp": {}}
    for ime in imena:
        try:
            cilj = os.readlink(os.path.join(mapa, ime))
        except OSError:
            continue
        v = _vrsta(cilj)
        vrste[v] += 1
        if v == "socket":
            vticniki.add(cilj[len("socket:["):-1])
    tcp = _vticniki_tcp(vticniki) if pid == "self" else {}
    return {"skupaj": len(imena), "vrste": dict(vrste), "tcp": tcp}


def besedilo(r: dict) -> str:
    """Ena vrstica za dnevnik."""
    vrste = ", ".join("%s=%d" % kv for kv in sorted(r.get("vrste", {}).items(), key=lambda kv: -kv[1]))
    tcp = ", ".join("%s=%d" % kv for kv in sorted(r.get("tcp", {}).items(), key=lambda kv: -kv[1])[:12])
    return "deskriptorjev %d (%s; niti %d)%s" % (r.get("skupaj", -1), vrste, threading.active_count(),
                                                ("; tcp: " + tcp) if tcp else "")


# ---------------------------------------------------------------------------- straza

#: Ob zagonu ima Safeer OS 55-70 vticnikov in ~150 deskriptorjev; nad tem pragom se rast zapise.
PRAG_OPOZORILA = 400
#: Naslednje opozorilo sele, ko jih je toliko vec kot ob zadnjem (dnevnik ne raste z vsakim pregledom).
KORAK_OPOZORILA = 100
PREGLED_VSAKIH_S = 300.0


class Straza:
    """Nit, ki vsakih `vsakih_s` presteje deskriptorje in ob rasti nad `prag` poklice `zapisi(besedilo)`."""

    def __init__(self, zapisi: Callable[[str], None], prag: int = PRAG_OPOZORILA, korak: int = KORAK_OPOZORILA,
                 vsakih_s: float = PREGLED_VSAKIH_S) -> None:
        self.zapisi = zapisi
        self.prag = prag
        self.korak = korak
        self.vsakih_s = vsakih_s
        self.zadnje_opozorilo = 0
        self._ustavi = threading.Event()
        self._nit: Optional[threading.Thread] = None

    def preglej(self) -> Optional[str]:
        """En pregled; vrne zapisano besedilo ali None."""
        n = stevilo()
        if n < self.prag or (self.zadnje_opozorilo and n < self.zadnje_opozorilo + self.korak):
            if n < self.prag // 2:
                self.zadnje_opozorilo = 0      # padlo je dalec pod prag: ob ponovni rasti spet opozori
            return None
        self.zadnje_opozorilo = n
        vrstica = "OPOZORILO: " + besedilo(razclenitev())
        try:
            self.zapisi(vrstica)
        except Exception:  # noqa: BLE001
            pass
        return vrstica

    def _zanka(self) -> None:
        while not self._ustavi.wait(self.vsakih_s):
            try:
                self.preglej()
            except Exception:  # noqa: BLE001 - straza ne sme nikoli ustaviti programa
                pass

    def zazeni(self) -> "Straza":
        if self._nit is None:
            self._nit = threading.Thread(target=self._zanka, name="safeer-straza-fd", daemon=True)
            self._nit.start()
        return self

    def ustavi(self) -> None:
        self._ustavi.set()


# ---------------------------------------------------------------------------- proste povezave streznika

#: Brez omejitve stevila povezav na napravo (lastnik 17. 10. 2026: naprave ne omejujemo) - prosta povezava se zapre
#: sama po roku cakanja na naslednjo zahtevo, nedelujoca takoj. Omejitev je mozna samo izrecno (preizkusi).
NAJVEC_PROSTIH_NA_VIR = None


class ProsteZveze:
    """Povezave streznika HTTP/1.1, ki cakajo na naslednjo zahtevo (keep-alive), po virih.

    Obravnava poklice `caka(vir, vticnik)` pred branjem zahteve in `dela(vticnik)`, ko je zahteva prisla ali je
    povezave konec. Ko ima vir vec kot `najvec` cakajocih, se najstarejsa zapre (shutdown zbudi nit, ki nanjo caka,
    in ta pospravi povezavo kot ob navadnem koncu)."""

    def __init__(self, najvec: Optional[int] = NAJVEC_PROSTIH_NA_VIR) -> None:
        self.najvec = najvec
        self._zaklep = threading.Lock()
        self._po_viru: Dict[str, "collections.OrderedDict[int, tuple]"] = {}
        self._vir_vticnika: Dict[int, str] = {}
        #: Koliko odvecnih povezav smo zaprli (za dnevnik in preizkuse).
        self.zaprtih = 0

    def caka(self, vir: str, vticnik) -> None:
        odvec = []
        with self._zaklep:
            kljuc = id(vticnik)
            if kljuc in self._vir_vticnika:
                return
            vrsta = self._po_viru.setdefault(vir, collections.OrderedDict())
            vrsta[kljuc] = (vticnik, time.monotonic())
            self._vir_vticnika[kljuc] = vir
            while self.najvec is not None and len(vrsta) > self.najvec:
                k, (stari, _) = vrsta.popitem(last=False)
                self._vir_vticnika.pop(k, None)
                odvec.append(stari)
            self.zaprtih += len(odvec)
        for stari in odvec:
            zapri_vticnik(stari)

    def dela(self, vticnik) -> None:
        with self._zaklep:
            kljuc = id(vticnik)
            vir = self._vir_vticnika.pop(kljuc, None)
            if vir is None:
                return
            vrsta = self._po_viru.get(vir)
            if vrsta is not None:
                vrsta.pop(kljuc, None)
                if not vrsta:
                    del self._po_viru[vir]

    def cakajocih(self, vir: Optional[str] = None) -> int:
        with self._zaklep:
            if vir is not None:
                return len(self._po_viru.get(vir, ()))
            return len(self._vir_vticnika)


def zapri_vticnik(vticnik) -> None:
    """Prekine povezavo, na kateri morda caka druga nit: shutdown na surovem vticniku (tudi pod TLS) zbudi recv,
    nit nato povezavo zapre sama. close() iz druge niti bi lahko zaprl ze ponovno uporabljeno stevilko."""
    try:
        socket.socket.shutdown(vticnik, socket.SHUT_RDWR)
    except (OSError, TypeError, ValueError):
        pass


class BrezBujenja:
    """Mesanica za socketserver streznik (pred ThreadingHTTPServer): serve_forever caka na povezavo brez roka.

    Privzeti serve_forever se zbudi vsakih 0,5 s samo zato, da pogleda, ali ga kdo ustavlja - Hub Safeer Linka, ki tece
    ves dan, je zato v mirovanju 2,0-krat na sekundo zbudil proces Safeer OS (izmerjeno 18. 10. 2026, Xvfb, 300 s), in
    enako vsak posrednik toka, ki je nekoc tekel (torrent, Twitch, pretok). Tu zanka spi, dokler ne pride povezava;
    shutdown() postavi zahtevo za konec in zanko zbudi s prazno povezavo na lastna vrata (zanka jo zapusti, ne da bi
    jo sprejela)."""

    def serve_forever(self, poll_interval=None) -> None:
        super().serve_forever(poll_interval)  # type: ignore[misc]

    def shutdown(self) -> None:
        # Najprej zahteva za konec (zastavica socketserver.BaseServer), sele nato bujenje: sicer bi zanka prazno
        # povezavo sprejela kot zahtevo in znova zaspala.
        if hasattr(self, "_BaseServer__shutdown_request"):
            self._BaseServer__shutdown_request = True
        konec = threading.Event()

        def zbujaj() -> None:
            # Bujenje, dokler se zanka ne konca (ce bi prvo prehitelo zastavico v starejsem Pythonu, pride naslednje).
            while True:
                self._zbudi()
                if konec.wait(0.2):
                    return
        nit = threading.Thread(target=zbujaj, name="safeer-streznik-konec", daemon=True)
        nit.start()
        try:
            super().shutdown()  # type: ignore[misc]
        finally:
            konec.set()

    def _zbudi(self) -> None:
        naslov = getattr(self, "server_address", None)
        if not naslov or len(naslov) < 2:
            return
        gostitelj = {"0.0.0.0": "127.0.0.1", "": "127.0.0.1", "::": "::1"}.get(str(naslov[0]), str(naslov[0]))
        try:
            with socket.create_connection((gostitelj, int(naslov[1])), timeout=1.0):
                pass
        except OSError:
            pass


class SledenjePovezav:
    """Mesanica za socketserver.ThreadingMixIn streznik (pred ThreadingHTTPServer): ve za vsako odprto povezavo
    zahteve, da jih `zapri_povezave()` ob ustavitvi prekine. shutdown()/server_close() streznika zapreta samo
    poslusalni vticnik - povezava toka (zvocnik v premoru ne bere, brez roka po glavah) je sicer z nitjo, cevjo
    ffmpeg in odprto datoteko ostala za vedno (pregled 18. 10. 2026). Po zapri_povezave() novih ne sprejme vec."""

    def __init__(self, *a, **k) -> None:
        self._povezave_zaklep = threading.Lock()
        self._povezave: set = set()
        self._povezave_zaprte = False
        super().__init__(*a, **k)  # type: ignore[call-arg]

    def process_request(self, request, client_address) -> None:
        with self._povezave_zaklep:
            sprejmi = not self._povezave_zaprte
            if sprejmi:
                self._povezave.add(request)
        if not sprejmi:
            self.shutdown_request(request)  # type: ignore[attr-defined]
            return
        super().process_request(request, client_address)  # type: ignore[misc]

    def shutdown_request(self, request) -> None:
        with self._povezave_zaklep:
            self._povezave.discard(request)
        super().shutdown_request(request)  # type: ignore[misc]

    def odprtih_povezav(self) -> int:
        with self._povezave_zaklep:
            return len(self._povezave)

    def zapri_povezave(self, rok_s: float = 2.0) -> None:
        """shutdown(SHUT_RDWR) zbudi nit, ki pise ali bere, in ta povezavo pospravi sama (shutdown_request); kar v
        roku ne odide, se zapre tu. close() Pythonovega vticnika je varen: deskriptor zapre samo enkrat (in sele, ko
        so zaprte tudi datoteke makefile niti), nikoli tuje, ze ponovno uporabljene stevilke."""
        with self._povezave_zaklep:
            self._povezave_zaprte = True
            povezave = list(self._povezave)
        for v in povezave:
            zapri_vticnik(v)
        konec = time.monotonic() + rok_s
        while self.odprtih_povezav() and time.monotonic() < konec:
            time.sleep(0.02)
        with self._povezave_zaklep:
            ostale, self._povezave = list(self._povezave), set()
        for v in ostale:
            try:
                v.close()
            except OSError:
                pass


# ---------------------------------------------------------------------------- sprejemanje povezav

#: Napake accept(), po katerih poslusalec ostane uporaben: zmanjkalo je deskriptorjev ali pomnilnika (mine, ko se
#: povezave zaprejo) ali pa je odjemalec odnehal pred sprejemom.
PREHODNE_NAPAKE_ACCEPT = frozenset(getattr(errno, ime) for ime in ("EMFILE", "ENFILE", "ENOBUFS", "ENOMEM",
                                                                    "ECONNABORTED", "EINTR", "EPROTO")
                                   if hasattr(errno, ime))
#: Premor po prehodni napaki (da zanka ne vrti procesorja, dokler deskriptorjev ni).
PREMOR_PO_NAPAKI_ACCEPT_S = 0.2


def prehodna_napaka_accept(napaka: BaseException) -> bool:
    """Ali naj poslusalna zanka po tej napaki accept() pocaka in nadaljuje (namesto da za vedno konca)?
    Ob 1024 deskriptorjih (16./17. 10. 2026) so poslusalci, ki so ob vsaki OSError koncali, ostali mrtvi tudi,
    ko so se deskriptorji sprostili."""
    return isinstance(napaka, OSError) and getattr(napaka, "errno", None) in PREHODNE_NAPAKE_ACCEPT


# ---------------------------------------------------------------------------- rok cakanja na zahtevo

#: Kako dolgo sme povezava cakati na (naslednjo) zahtevo, preden jo streznik zapre.
ROK_CAKANJA_ZAHTEVE_S = 10.0          # tiha povezava (lastnik 17. 10. 2026)


class RokCakanjaZahteve:
    """Mesanica za http.server.BaseHTTPRequestHandler: povezava, ki ne poslje zahteve (ali po keep-alive ne poslje
    naslednje), se po `ROK_CAKANJA_ZAHTEVE_S` zapre. Brez roka je vsaka taka povezava za vedno drzala nit in
    deskriptor. Ko je vrstica zahteve prebrana, velja spet prejsnji rok vticnika - tok (zvok, video) med pavzo
    predvajalnika ne izpade."""

    ROK_CAKANJA_ZAHTEVE_S = ROK_CAKANJA_ZAHTEVE_S

    def handle_one_request(self) -> None:
        try:
            self._rok_po_zahtevi = self.connection.gettimeout()
            self.connection.settimeout(self.ROK_CAKANJA_ZAHTEVE_S)
        except OSError:
            pass
        super().handle_one_request()  # type: ignore[misc]

    def parse_request(self) -> bool:
        # Glave se berejo se z rokom cakanja: odjemalec, ki po vrstici zahteve utihne (telefon izgubi Wi-Fi), bi
        # sicer drzal nit in deskriptor za vedno. Sele po glavah velja prejsnji rok (tok med pavzo ne izpade).
        try:
            return super().parse_request()  # type: ignore[misc]
        finally:
            try:
                self.connection.settimeout(getattr(self, "_rok_po_zahtevi", None))
            except OSError:
                pass
