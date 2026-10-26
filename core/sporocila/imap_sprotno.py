"""E-posta v realnem casu: IMAP IDLE (RFC 2177) v svoji niti za vsak racun, uskladitev oznak (CONDSTORE, RFC 7162)
in celotno besedilo dolgih pisem.

Zakaj lasten majhen odjemalec za IDLE namesto imaplib: imaplib bere prek medpomnjene datoteke, zato select() na
vticnici ne ve za ze prebrane vrstice v medpomnilniku, cakanje s casovno omejitvijo pa po dokumentaciji pusti
medpomnilnik v nedolocenem stanju. Tu beremo sami (lasten medpomnilnik + selectors), zato nit med cakanjem spi brez
porabe procesorja in jo lahko kadarkoli zbudimo (ustavi, sprememba omrezja).

Povezava IDLE samo javlja (EXAMINE, samo za branje); prenos novih pisem in oznak gre po glavni povezavi adapterja
(core/sporocila/email.py) v isti niti, zato povezava IDLE ostane v IDLE ves cas in nic ne zamudi.

V dnevnik ne gre nic iz vsebine pisem, naslovov ali odgovorov streznika - samo vrsta napake.
"""

from __future__ import annotations

import base64
import re
import selectors
import socket
import ssl
import threading
import time
from typing import Callable, Dict, Iterable, List, Optional, Tuple

#: Ponovni IDLE vsaj na 25 min (RFC 2177: streznik sme po 30 min neaktivnosti prekiniti; priporocilo 29 min).
OBNOVI_IDLE_S = 25 * 60
#: Zamiki ponovne povezave po izgubi omrezja (s); zadnji velja naprej.
ZAMIKI_S = (1, 2, 5, 10, 30, 60)
#: Streznik brez IDLE: poizvedba vsakih 60 s.
POIZVEDBA_BREZ_IDLE_S = 60
#: Najdaljse spanje v enem kosu: ob prebujenju preverimo, ali je racunalnik vmes spal (suspend).
NAJDLJE_SPANJE_S = 60
#: Brez CONDSTORE: oznake zadnjih N znanih pisem ob vsaki uskladitvi.
OZNAKE_ZADNJIH = 500
#: Pismo vecje od tega je bilo ob sinhronizaciji prirezano (email.NAJVEC_BAJTOV).
PRIREZANO_NAD = 65536
#: Celotno besedilo: najvec toliko bajtov pisma (besedilo je v praksi v prvih 2 MB; priponke za njim ne prenasamo).
CELOTNO_NAJVEC = 2 * 1024 * 1024
CASOVNA_OMEJITEV = 20


def _cas_zbujen() -> float:
    """Cas, ki tece tudi med spanjem racunalnika (CLOCK_BOOTTIME); monotonic med spanjem stoji."""
    try:
        return time.clock_gettime(time.CLOCK_BOOTTIME)
    except (AttributeError, OSError):
        return time.time()


def _navedi(niz: str) -> str:
    return '"%s"' % niz.replace("\\", "\\\\").replace('"', '\\"')


def _ascii_navedljivo(*nizi: str) -> bool:
    try:
        for n in nizi:
            n.encode("ascii")
            if "\r" in n or "\n" in n or "\0" in n:
                return False
        return True
    except UnicodeEncodeError:
        return False


def nastavi_keepalive(sock: socket.socket) -> None:
    """TCP keepalive na povezavi IDLE: usmerjevalnik (NAT) tihe povezave ne pozabi, mrtvo (izgubljeno omrezje brez
    obvestila) pa zaznamo v ~3,5 min namesto sele ob ponovnem IDLE cez 25 min. Paketi jedra, brez prebujanja niti."""
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        for ime, vrednost in (("TCP_KEEPIDLE", 120), ("TCP_KEEPINTVL", 30), ("TCP_KEEPCNT", 3)):
            if hasattr(socket, ime):
                sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, ime), vrednost)
    except OSError:
        pass


class NapakaIdle(RuntimeError):
    pass


class PovezavaIdle:
    """Najmanjsi odjemalec IMAP za IDLE: prijava, EXAMINE, IDLE/DONE, LOGOUT. Bere sam (brez medpomnjene datoteke)."""

    def __init__(self, vticnica: socket.socket):
        self.sock = vticnica
        self._buf = b""
        self._oznaka = 0
        self.zmoznosti: set = set()
        self.uidvalidity = 0
        self.idle = False
        pozdrav = self._vrstica(CASOVNA_OMEJITEV)
        if not pozdrav.startswith(b"* OK") and not pozdrav.startswith(b"* PREAUTH"):
            raise NapakaIdle("pozdrav")
        self._zmoznosti_iz(pozdrav)

    @classmethod
    def odpri(cls, gostitelj: str, vrata: int, kontekst: Optional[ssl.SSLContext] = None) -> "PovezavaIdle":
        """TLS kot imaplib.IMAP4_SSL v adapterju (vrata 993, preverjeno potrdilo)."""
        sock = socket.create_connection((gostitelj, int(vrata)), timeout=CASOVNA_OMEJITEV)
        nastavi_keepalive(sock)
        try:
            sock = (kontekst or ssl.create_default_context()).wrap_socket(sock, server_hostname=gostitelj)
            return cls(sock)
        except Exception:
            sock.close()
            raise

    # ---------------------------------------------------------------- branje
    def _beri_kos(self, timeout: Optional[float]) -> bool:
        self.sock.settimeout(timeout)
        try:
            kos = self.sock.recv(65536)
        except (socket.timeout, BlockingIOError, ssl.SSLWantReadError):
            return False
        if not kos:
            raise NapakaIdle("zaprto")
        self._buf += kos
        return True

    def _vrstica(self, timeout: Optional[float]) -> bytes:
        konec = time.monotonic() + (timeout or 0)
        while b"\r\n" not in self._buf:
            ostane = None if timeout is None else max(0.05, konec - time.monotonic())
            if not self._beri_kos(ostane) and timeout is not None and time.monotonic() >= konec:
                raise NapakaIdle("casovna omejitev")
            if len(self._buf) > 1 << 20:
                raise NapakaIdle("predolga vrstica")
        vrstica, self._buf = self._buf.split(b"\r\n", 1)
        # Dobesedni niz {n} (redek v odgovorih, ki jih tu beremo): preberemo ga in nadaljujemo vrstico.
        m = re.search(rb"\{(\d+)\}$", vrstica)
        while m:
            n = int(m.group(1))
            while len(self._buf) < n:
                if not self._beri_kos(timeout) and timeout is not None and time.monotonic() >= konec:
                    raise NapakaIdle("casovna omejitev")
            vrstica += b"\r\n" + self._buf[:n]
            self._buf = self._buf[n:]
            nadaljevanje = self._vrstica(timeout)
            vrstica += nadaljevanje
            m = re.search(rb"\{(\d+)\}$", nadaljevanje)
        return vrstica

    def ima_medpomnjeno(self) -> bool:
        return b"\r\n" in self._buf or (isinstance(self.sock, ssl.SSLSocket) and self.sock.pending() > 0)

    def _poslji(self, vrstica: bytes) -> None:
        self.sock.settimeout(CASOVNA_OMEJITEV)
        self.sock.sendall(vrstica + b"\r\n")

    def _zmoznosti_iz(self, vrstica: bytes) -> None:
        m = re.search(rb"\[CAPABILITY ([^\]]*)\]", vrstica) or re.match(rb"\* CAPABILITY (.*)$", vrstica)
        if m:
            self.zmoznosti = {z.upper() for z in m.group(1).decode("ascii", "replace").split()}

    def ukaz(self, besedilo: str, ob_nadaljevanju: Optional[Callable[[bytes], bytes]] = None) -> Tuple[str, List[bytes]]:
        self._oznaka += 1
        oznaka = ("S%d" % self._oznaka).encode()
        self._poslji(oznaka + b" " + besedilo.encode("utf-8"))
        neoznaceni = []
        while True:
            v = self._vrstica(CASOVNA_OMEJITEV * 2)
            if v.startswith(oznaka + b" "):
                status = v[len(oznaka) + 1:].split(b" ", 1)[0].decode("ascii", "replace").upper()
                self._zmoznosti_iz(v)
                return status, neoznaceni
            if v.startswith(b"+"):
                if ob_nadaljevanju is None:
                    self._poslji(b"*")              # prekinemo nepricakovano nadaljevanje
                else:
                    self._poslji(ob_nadaljevanju(v))
                continue
            self._zmoznosti_iz(v)
            neoznaceni.append(v)

    # ---------------------------------------------------------------- ukazi
    def prijava(self, uporabnik: str, geslo: str) -> None:
        if not self.zmoznosti:
            self.ukaz("CAPABILITY")
        if _ascii_navedljivo(uporabnik, geslo):
            status, _ = self.ukaz("LOGIN %s %s" % (_navedi(uporabnik), _navedi(geslo)))
        else:
            # UTF-8 ime ali geslo: AUTHENTICATE PLAIN (RFC 4616), kot adapter.
            surovo = b"\0" + uporabnik.encode("utf-8") + b"\0" + geslo.encode("utf-8")
            status, _ = self.ukaz("AUTHENTICATE PLAIN", lambda _v: base64.b64encode(surovo))
        if status != "OK":
            from .email import NapakaPrijave
            raise NapakaPrijave("Prijava ni uspela")
        if "IDLE" not in self.zmoznosti:
            self.ukaz("CAPABILITY")     # nekateri strezniki (Gmail) vse zmoznosti oglasijo sele po prijavi

    def examine(self, mapa: str = "INBOX") -> None:
        status, odg = self.ukaz("EXAMINE " + _navedi(mapa))
        if status != "OK":
            raise NapakaIdle("examine")
        for v in odg:
            m = re.search(rb"\[UIDVALIDITY (\d+)\]", v)
            if m:
                self.uidvalidity = int(m.group(1))

    def zacni_idle(self) -> List[bytes]:
        """Vrne neoznacene vrstice, ki so prisle pred potrditvijo (+)."""
        self._oznaka += 1
        self._idle_oznaka = ("S%d" % self._oznaka).encode()
        self._poslji(self._idle_oznaka + b" IDLE")
        prej = []
        while True:
            v = self._vrstica(CASOVNA_OMEJITEV)
            if v.startswith(b"+"):
                self.idle = True
                return prej
            if v.startswith(self._idle_oznaka + b" "):
                raise NapakaIdle("idle zavrnjen")
            prej.append(v)

    def koncaj_idle(self) -> List[bytes]:
        if not self.idle:
            return []
        self._poslji(b"DONE")
        self.idle = False
        prej = []
        while True:
            v = self._vrstica(CASOVNA_OMEJITEV)
            if v.startswith(self._idle_oznaka + b" "):
                return prej
            prej.append(v)

    def preberi_cakajoce(self) -> List[bytes]:
        """Vse popolne vrstice, ki so ze prisle (brez cakanja)."""
        vrstice = []
        while True:
            if b"\r\n" in self._buf:
                vrstice.append(self._vrstica(CASOVNA_OMEJITEV))
                continue
            if not self._beri_kos(0.001):
                return vrstice

    def zapri(self) -> None:
        try:
            if self.idle:
                self._poslji(b"DONE")
            self._poslji(b"Z LOGOUT")
        except Exception:  # noqa: BLE001 - zapiramo ne glede na stanje
            pass
        try:
            self.sock.close()
        except Exception:  # noqa: BLE001
            pass


def je_sprememba(vrstica: bytes) -> bool:
    """Odgovor v IDLE, ki pomeni novo/izbrisano pismo ali spremenjene oznake."""
    return bool(re.match(rb"\* \d+ (EXISTS|EXPUNGE|FETCH)\b", vrstica, re.I)) or vrstica.upper().startswith(b"* VANISHED")


# ======================================================================= uskladitev po glavni povezavi
def _zmoznosti(imap) -> set:
    """Zmoznosti glavne povezave po prijavi (en CAPABILITY na povezavo; Gmail vse oglasi sele po prijavi)."""
    lastno = getattr(imap, "__dict__", {})
    if isinstance(lastno.get("_safeer_zmoznosti"), set):
        return lastno["_safeer_zmoznosti"]
    try:
        z = {str(x).upper() for x in (getattr(imap, "capabilities", ()) or ())}
    except TypeError:
        z = set()
    try:
        status, odg = imap.capability()
        if status == "OK" and odg and isinstance(odg[0], (bytes, str)):
            v = odg[0].decode("ascii", "replace") if isinstance(odg[0], bytes) else odg[0]
            z |= set(v.upper().split())
    except Exception:  # noqa: BLE001
        pass
    lastno["_safeer_zmoznosti"] = z
    return z


def _obmocja(uidi: Iterable[int]) -> str:
    """[1,2,3,7,9,10] -> '1:3,7,9:10' (kratek ukaz tudi za 500 UID-jev)."""
    deli, zac, prej = [], None, None
    for u in sorted(set(uidi)):
        if zac is None:
            zac = prej = u
        elif u == prej + 1:
            prej = u
        else:
            deli.append("%d" % zac if zac == prej else "%d:%d" % (zac, prej))
            zac = prej = u
    if zac is not None:
        deli.append("%d" % zac if zac == prej else "%d:%d" % (zac, prej))
    return ",".join(deli)


def _odgovori_fetch(podatki) -> List[bytes]:
    izid = []
    for kos in podatki or []:
        if isinstance(kos, tuple) and kos:
            kos = kos[0]
        if isinstance(kos, (bytes, bytearray)):
            izid.append(bytes(kos))
    return izid


def uskladi_oznake(adapter, znani_uidi: Iterable[int]) -> Dict[int, bool]:
    """{uid: prebrano} za znana pisma, ki so se morda spremenila (prebrano/neprebrano na drugi napravi).

    S CONDSTORE samo pisma, spremenjena od zadnjega HIGHESTMODSEQ (adapter.modseq, trajno v stanju kanala);
    brez njega oznake zadnjih OZNAKE_ZADNJIH znanih pisem. Klic je v niti kanala (glavna povezava adapterja)."""
    imap = adapter._imap
    znani = sorted(set(int(u) for u in znani_uidi))
    if imap is None or not znani:
        return {}
    zmoznosti = _zmoznosti(imap)
    condstore = "CONDSTORE" in zmoznosti or "QRESYNC" in zmoznosti
    najvisji = 0
    ur = getattr(imap, "untagged_responses", None) or {}
    for v in ur.pop("HIGHESTMODSEQ", None) or []:
        try:
            najvisji = max(najvisji, int(v))
        except (TypeError, ValueError):
            pass
    for kljuc in ("EXISTS", "RECENT", "EXPUNGE", "FETCH"):
        ur.pop(kljuc, None)          # nenarocene novice glavne povezave (zanje skrbi IDLE) ne smejo rasti brez meje
    if condstore and adapter.modseq:
        status, podatki = imap.uid("fetch", "%d:*" % znani[0], "(FLAGS) (CHANGEDSINCE %d)" % adapter.modseq)
    elif condstore:
        status, podatki = imap.uid("fetch", _obmocja(znani[-OZNAKE_ZADNJIH:]), "(FLAGS MODSEQ)")
    else:
        status, podatki = imap.uid("fetch", _obmocja(znani[-OZNAKE_ZADNJIH:]), "(FLAGS)")
    if status != "OK":
        return {}
    mnozica = set(znani)
    izid: Dict[int, bool] = {}
    for v in _odgovori_fetch(podatki):
        m = re.search(rb"UID (\d+)", v)
        if not m:
            continue
        uid = int(m.group(1))
        ms = re.search(rb"MODSEQ \((\d+)\)", v)
        if ms:
            najvisji = max(najvisji, int(ms.group(1)))
        z = re.search(rb"FLAGS \(([^)]*)\)", v)
        if z is not None and uid in mnozica:
            izid[uid] = b"\\seen" in z.group(1).lower()
    if condstore and najvisji:
        adapter.modseq = max(adapter.modseq, najvisji)
    return izid


def neprebrano_na_strezniku(adapter) -> Optional[int]:
    """Stevilo neprebranih v INBOX, kot ga pokaze Gmail: STATUS INBOX (UNSEEN) - en kratek odgovor ne glede na
    velikost mape (predpomnilnik ima samo zadnjih 200 pisem). Ce streznik STATUS na izbrani mapi zavrne, UID SEARCH
    UNSEEN. None: stevila ni bilo mogoce dobiti (ostane zadnje znano)."""
    imap = adapter._imap
    if imap is None:
        return None
    try:
        status, odg = imap.status("INBOX", "(UNSEEN)")
        if status == "OK" and odg:
            v = odg[0].decode("ascii", "replace") if isinstance(odg[0], bytes) else str(odg[0])
            m = re.search(r"UNSEEN (\d+)", v, re.I)
            if m:
                return int(m.group(1))
    except Exception:  # noqa: BLE001
        pass
    status, odg = imap.uid("search", None, "UNSEEN")
    if status == "OK" and odg is not None:
        return len((odg[0] or b"").split()) if odg else 0
    return None


def polna_besedila(adapter, uidi: Iterable[int]) -> Dict[int, Optional[str]]:
    """Celotno besedilo pisem, ki so bila ob sinhronizaciji prirezana na 64 KB. {uid: besedilo} za prirezana,
    {uid: None} za pisma, ki so ze cela (ni kaj prenesti). Pisem, ki jih streznik nima vec, ni v izidu.

    Po delih (BODYSTRUCTURE): prenese se samo del z besedilom (text/plain, sicer text/html) do CELOTNO_NAJVEC,
    nikoli priponke - pismo z 20 MB priponko pomeni le nekaj KB prenosa."""
    from . import priponke as _priponke_mod
    from .email import _besedilo_dela, _brez_citata, _brez_html
    uidi = sorted(set(int(u) for u in uidi))
    if not uidi:
        return {}
    adapter.povezi()
    imap = adapter._imap
    status, podatki = imap.uid("fetch", _obmocja(uidi), "(UID RFC822.SIZE BODYSTRUCTURE)")
    if status != "OK":
        return {}
    izid: Dict[int, Optional[str]] = {}
    for odg in _priponke_mod.razcleni_fetch(podatki):
        try:
            uid = int(str(odg.get("UID") or ""))
            velikost = int(str(odg.get("RFC822.SIZE") or "0"))
        except ValueError:
            continue
        bs = odg.get("BODYSTRUCTURE")
        zg = _priponke_mod.zgradba(bs) if isinstance(bs, list) else {}
        opis = zg.get("besedilo") or zg.get("html")
        # Celo: majhno pismo, brez besedila, ali del z besedilom, ki je ze v celoti prisel s prvimi 64 KB.
        if velikost <= PRIREZANO_NAD or not opis or 0 < int(opis.get("velikost") or 0) <= PRIREZANO_NAD // 2:
            izid[uid] = None
            continue
        deli: List[bytes] = []
        dolzina = [0]

        def pisi(b: bytes, deli=deli, dolzina=dolzina) -> None:
            dolzina[0] += len(b)
            if dolzina[0] > CELOTNO_NAJVEC:
                raise OverflowError
            deli.append(b)
        try:
            adapter.prenesi_del(uid, opis["del"], "", pisi)
        except OverflowError:
            pass                                      # zelo dolgo besedilo: prvih CELOTNO_NAJVEC je dovolj
        except RuntimeError:
            continue                                  # pismo je medtem izginilo
        besedilo = _besedilo_dela(b"".join(deli), opis)
        izid[uid] = _brez_citata(_brez_html(besedilo) if opis is zg.get("html") and not zg.get("besedilo")
                                 else besedilo.strip())
    return izid


# ======================================================================= nit za en racun
class DelavecImap:
    """Ena nit na e-postni racun: povezava IDLE javlja, storitev prenese (sinhroniziraj_kanal)."""

    vrsta = "imap"

    def __init__(self, storitev, kanal_id: str, adapter,
                 odpri_povezavo: Optional[Callable[[object], PovezavaIdle]] = None):
        self.storitev, self.kanal_id, self.adapter = storitev, kanal_id, adapter
        self._odpri = odpri_povezavo or (lambda a: PovezavaIdle.odpri(a.imap_streznik, a.imap_vrata))
        self._ustavi = threading.Event()
        self._zbudi_zahteva = threading.Event()
        self._na_novo = threading.Event()
        self._r, self._w = socket.socketpair()
        self._r.setblocking(False)
        self._nit: Optional[threading.Thread] = None
        self._povezava: Optional[PovezavaIdle] = None
        self.ima_idle: Optional[bool] = None
        self._sveza_glavna = False
        #: Stevci za preizkuse in meritve (brez vsebine).
        self.stevci = {"povezav": 0, "idle": 0, "sinhronizacij": 0, "napak": 0}

    # ---------------------------------------------------------------- nadzor
    def zazeni(self) -> None:
        if self._nit is not None and self._nit.is_alive():
            return
        self._ustavi.clear()
        self._nit = threading.Thread(target=self._teci, name="safeer-imap-idle", daemon=True)
        self._nit.start()

    def tece(self) -> bool:
        return self._nit is not None and self._nit.is_alive()

    def _dregni(self) -> None:
        try:
            self._w.send(b"x")
        except OSError:
            pass

    def zbudi(self) -> None:
        """Sinhroniziraj zdaj (gumb v vmesniku)."""
        self._zbudi_zahteva.set()
        self._dregni()

    def ponovno_povezi(self) -> None:
        """Omrezje se je spremenilo ali racunalnik se je zbudil: takoj nova povezava in uskladitev."""
        self._sveza_glavna = True
        self._na_novo.set()
        self._dregni()

    def ustavi(self, cakaj: float = 3.0) -> None:
        self._ustavi.set()
        self._dregni()
        p = self._povezava
        if p is not None:
            try:
                p.sock.shutdown(socket.SHUT_RDWR)   # prekine morebitno branje v niti
            except OSError:
                pass
        if self._nit is not None and self._nit is not threading.current_thread():
            self._nit.join(timeout=cakaj)
        for s in (self._r, self._w):
            try:
                s.close()
            except OSError:
                pass

    # ---------------------------------------------------------------- zanka
    def _cakaj(self, sekunde: float) -> None:
        """Spanje, ki ga prekine ustavi/zbudi/ponovno_povezi."""
        konec = time.monotonic() + sekunde
        while not self._ustavi.is_set() and not self._na_novo.is_set() and not self._zbudi_zahteva.is_set():
            ostane = konec - time.monotonic()
            if ostane <= 0:
                return
            sel = selectors.DefaultSelector()
            try:
                sel.register(self._r, selectors.EVENT_READ)
                sel.select(min(ostane, NAJDLJE_SPANJE_S))
            finally:
                sel.close()
            self._izprazni_dregljaje()

    def _izprazni_dregljaje(self) -> None:
        try:
            while self._r.recv(64):
                pass
        except (BlockingIOError, OSError):
            pass

    def _sinhroniziraj(self) -> None:
        self.stevci["sinhronizacij"] += 1
        self.storitev.sinhroniziraj_kanal(self.kanal_id)

    def _teci(self) -> None:
        poskus = 0
        while not self._ustavi.is_set():
            self._na_novo.clear()
            try:
                self._seja()
                poskus = 0
            except Exception as e:  # noqa: BLE001 - izgubljeno omrezje, prijava ...: nov poskus z zamikom
                self.stevci["napak"] += 1
                if self._ustavi.is_set():
                    break
                ime = type(e).__name__
                if ime not in ("NapakaIdle", "ConnectionResetError", "BrokenPipeError", "TimeoutError", "timeout"):
                    print("[Sporocila] IDLE:", ime, flush=True)
                self.storitev.oznaci_stanje(self.kanal_id, self.storitev._razlog(e))
                zamik = ZAMIKI_S[min(poskus, len(ZAMIKI_S) - 1)]
                poskus += 1
                self._cakaj(zamik)
            finally:
                p, self._povezava = self._povezava, None
                if p is not None:
                    p.zapri()
        if self._povezava is not None:
            self._povezava.zapri()

    def _seja(self) -> None:
        a = self.adapter
        if self._sveza_glavna:
            # Po spremembi omrezja ali spanju je tudi glavna povezava adapterja mrtva: NOOP na njej bi visel do
            # casovne omejitve (20 s). Zapremo jo brez LOGOUT; naslednja sinhronizacija odpre novo.
            self._sveza_glavna = False
            self.storitev.pozabi_povezavo(self.kanal_id)
        p = self._odpri(a)
        self._povezava = p
        self.stevci["povezav"] += 1
        p.prijava(a.uporabnik, a._skrivnost())
        p.examine("INBOX")
        self.ima_idle = "IDLE" in p.zmoznosti
        self._sinhroniziraj()                 # ob vsaki (ponovni) povezavi: kar je prislo vmes, in oznake
        if not self.ima_idle:
            p.zapri()
            self._povezava = None
            self._zanka_brez_idle()
            return
        while not self._ustavi.is_set() and not self._na_novo.is_set():
            self.stevci["idle"] += 1
            spremembe = any(je_sprememba(v) for v in p.zacni_idle())
            zacetek, zbujen = time.monotonic(), _cas_zbujen()
            while not self._ustavi.is_set() and not self._na_novo.is_set():
                if spremembe or self._zbudi_zahteva.is_set():
                    self._zbudi_zahteva.clear()
                    if spremembe:
                        # Kratek premor zdruzi niz novic (npr. 20 pisem naenkrat) v eno sinhronizacijo.
                        time.sleep(0.05)
                        p.preberi_cakajoce()
                    spremembe = False
                    self._sinhroniziraj()
                    continue
                ostane = OBNOVI_IDLE_S - (time.monotonic() - zacetek)
                if ostane <= 0:
                    break
                if p.ima_medpomnjeno():
                    pripravljeno = True
                else:
                    sel = selectors.DefaultSelector()
                    try:
                        sel.register(p.sock, selectors.EVENT_READ, "idle")
                        sel.register(self._r, selectors.EVENT_READ, "dregljaj")
                        dogodki = sel.select(min(ostane, NAJDLJE_SPANJE_S))
                    finally:
                        sel.close()
                    pripravljeno = any(k.data == "idle" for k, _ in dogodki)
                    if any(k.data == "dregljaj" for k, _ in dogodki):
                        self._izprazni_dregljaje()
                # Racunalnik je spal (CLOCK_BOOTTIME je tekel, monotonic ne): povezava je verjetno mrtva.
                zdaj_zb, zdaj_mo = _cas_zbujen(), time.monotonic()
                if (zdaj_zb - zbujen) - (zdaj_mo - zacetek) > 5:
                    self._sveza_glavna = True
                    self._na_novo.set()
                    break
                if pripravljeno:
                    for v in p.preberi_cakajoce():
                        if v.upper().startswith(b"* BYE"):
                            raise NapakaIdle("bye")
                        if je_sprememba(v):
                            spremembe = True
            if self._ustavi.is_set() or self._na_novo.is_set():
                break
            # 25 min: DONE in nov IDLE (vmesne novice ne izgubimo - pridejo pred potrditvijo DONE).
            if any(je_sprememba(v) for v in p.koncaj_idle()):
                self._sinhroniziraj()

    def _zanka_brez_idle(self) -> None:
        while not self._ustavi.is_set() and not self._na_novo.is_set():
            self._cakaj(POIZVEDBA_BREZ_IDLE_S)
            if self._ustavi.is_set() or self._na_novo.is_set():
                return
            self._zbudi_zahteva.clear()
            self._sinhroniziraj()
