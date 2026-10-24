"""Global Link na racunalniku: hub je dosegljiv svojim napravam tudi zunaj domacega omrezja.

Agent se prijavi na link.safeer.si (podpis s kljucem te naprave, brez gesla), objavi, katere naprave
ga smejo doseci (clani kroga zaupanja), in caka na kanale. Ko se naprava iz kroga poveze, agent odpre
kanal in ga poveze z lokalnim hubom (127.0.0.1:vrata). Skozi kanal tece TLS Safeer Linka od naprave do
huba, zato rele (Cloudflare) vidi samo sifrirane bajte. Drug uporabnik do tega huba ne pride: Worker
spusti samo naprave s seznama `allow`.
"""
from __future__ import annotations

import atexit
import base64
import hashlib
import json
import os
import select
import socket
import ssl
import struct
import threading
import time
import urllib.request
from typing import Callable, List, Optional

from core import gneca
from core import link_vticnik
from core import os_deskriptorji

GOSTITELJ = "link.safeer.si"
OBJAVA_VSAKIH_S = 60
PING_VSAKIH_S = 30
KOS = 16 * 1024
#: Najvecje sporocilo releja (okvir in vsi nadaljevalni okvirji skupaj); prej 4 MiB samo na okvir.
NAJVECJE_SPOROCILO = 4 * 1024 * 1024
#: Cloudflare (Browser Integrity Check) zavrne privzeti "Python-urllib" z 403; Safeer se predstavi z imenom.
UA = "SafeerLink/1.0"
#: Topla povezava (vnaprej odprt TLS do releja) se drzi, dokler je bila v tem casu zeljena ali uporabljena.
TOPLA_ZELJA_S = 600.0
#: Najdaljsa starost tople povezave. Izmerjeno 9. 10. 2026 (lastnikov PC, rele_topla.py zivljenje): Cloudflare povezavo
#: TLS, po kateri ni prisla nobena zahteva, zapre po 10-15 s (3/3). Zato jo zamenjamo z novo ze prej.
TOPLA_STAROST_S = 8.0
#: `vzemi` jo da kanalu se do te starosti (med redno zamenjavo, ko nova se ni odprta); 1 s pod najkrajsim izmerjenim zaprtjem.
TOPLA_NAJVEC_S = 9.0


# ------------------------------------------------------------------ podpis zahtev (kot worker.mjs)

def podpisane_glave(metoda: str, pot: str, telo: bytes = b"",
                    kljuc: Optional[Callable[[], str]] = None, podpisi: Optional[Callable[[bytes], str]] = None,
                    cas: Optional[int] = None) -> dict:
    """Glave X-Safeer-*: podpis nad METODA\\nPOT\\nCAS\\nhex(SHA-256(telo)) s kljucem te naprave."""
    if kljuc is None or podpisi is None:
        from core import link_krog
        kljuc = kljuc or link_krog.javni_kljuc_b64
        podpisi = podpisi or link_krog.podpisi
    t = str(int(time.time() if cas is None else cas))
    sporocilo = f"{metoda}\n{pot}\n{t}\n{hashlib.sha256(telo).hexdigest()}".encode()
    return {"X-Safeer-Key": kljuc(), "X-Safeer-Time": t, "X-Safeer-Signature": podpisi(sporocilo)}


def id_iz_kljuca(kljuc_b64: str) -> str:
    return "n-" + hashlib.sha256(base64.b64decode(kljuc_b64)).hexdigest()[:16]


def dovoljeni_iz_kroga(krog_json: dict, nas_id: str) -> List[str]:
    """Id-ji (iz kljuca) clanov kroga brez umaknjenih in brez nas: samo ti smejo do tega huba."""
    umiki = krog_json.get("umiki") or {}
    out = []
    for i, c in (krog_json.get("clani") or {}).items():
        u = umiki.get(i)
        if u and u.get("umaknjeno", 0) > c.get("dodano", 0):
            continue
        try:
            d = id_iz_kljuca(c["kljuc"])
        except Exception:
            continue
        if d != nas_id and d not in out:
            out.append(d)
    return out[:256]


# ------------------------------------------------------------------ najmanjsi WebSocket odjemalec

def _maskiraj(podatki: bytes, maska: bytes) -> bytes:
    """XOR z masko prek celih stevil (hitro tudi za 16 KiB kose)."""
    n = len(podatki)
    if not n:
        return b""
    m = (maska * (n // 4 + 1))[:n]
    return (int.from_bytes(podatki, "big") ^ int.from_bytes(m, "big")).to_bytes(n, "big")


class WsOdjemalec:
    """WebSocket prek TLS (preverjeno potrdilo link.safeer.si) z dvojiskimi okvirji."""

    def __init__(self, pot: str, glave: dict, gostitelj: str = GOSTITELJ, rok_s: float = 15.0,
                 tls: Optional[ssl.SSLSocket] = None) -> None:
        """`tls`: ze odprta povezava TLS do releja (topla); brez nje odpremo novo."""
        self.s = tls if tls is not None else _nova_tls(gostitelj, rok_s)
        self.s.settimeout(rok_s)
        try:
            self._rokovanje(pot, glave, gostitelj)
        except Exception:
            self.s.close()
            raise
        self.s.settimeout(None)
        # Bere ena nit, pisejo druge (cev: obe smeri; agent: ping): vticnica TLS tega sama ne prenese
        # (core/link_vticnik.py).
        self.s = link_vticnik.zavaruj(self.s)
        self._pisi = threading.Lock()

    def _rokovanje(self, pot: str, glave: dict, gostitelj: str) -> None:
        kljuc = base64.b64encode(os.urandom(16)).decode()
        zahteva = [f"GET {pot} HTTP/1.1", f"Host: {gostitelj}", f"User-Agent: {UA}", "Upgrade: websocket", "Connection: Upgrade",
                   f"Sec-WebSocket-Key: {kljuc}", "Sec-WebSocket-Version: 13"]
        zahteva += [f"{k}: {v}" for k, v in glave.items()]
        odgovor = b""
        try:
            self.s.sendall(("\r\n".join(zahteva) + "\r\n\r\n").encode())
            while b"\r\n\r\n" not in odgovor:
                kos = self.s.recv(4096)
                if not kos:
                    raise ConnectionError("rele je zaprl povezavo")
                odgovor += kos
                if len(odgovor) > 16384:
                    raise ConnectionError("predolga glava")
        except (OSError, ConnectionError) as e:
            if not odgovor:
                raise BrezOdgovora(str(e) or type(e).__name__) from e
            raise
        glava, _, self._ostanek = odgovor.partition(b"\r\n\r\n")
        vrstica = glava.split(b"\r\n", 1)[0].decode(errors="replace")
        if " 101 " not in vrstica + " ":
            raise ConnectionError("rele zavrnil: " + vrstica)
        pricakovano = base64.b64encode(hashlib.sha1((kljuc + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode(), usedforsecurity=False).digest()).decode()
        if pricakovano.encode() not in glava:
            raise ConnectionError("napacen odgovor rokovanja")

    def _beri(self, n: int) -> bytes:
        out = self._ostanek[:n]
        self._ostanek = self._ostanek[n:]
        while len(out) < n:
            kos = self.s.recv(max(n - len(out), 4096))
            if not kos:
                raise ConnectionError("konec")
            out += kos
            if len(out) > n:
                self._ostanek = out[n:] + self._ostanek
                out = out[:n]
        return out

    def poslji(self, podatki: bytes, opkoda: int = 0x2) -> None:
        dolzina = len(podatki)
        glava = bytes([0x80 | opkoda])
        if dolzina < 126:
            glava += bytes([0x80 | dolzina])
        elif dolzina < 65536:
            glava += bytes([0x80 | 126]) + struct.pack(">H", dolzina)
        else:
            glava += bytes([0x80 | 127]) + struct.pack(">Q", dolzina)
        maska = os.urandom(4)
        telo = _maskiraj(podatki, maska)
        with self._pisi:
            self.s.sendall(glava + maska + telo)

    def besedilo(self, niz: str) -> None:
        self.poslji(niz.encode(), 0x1)

    def prejmi(self):
        """Vrne (opkoda, podatki); na ping odgovori sam, zaprtje dvigne ConnectionError.

        Meja NAJVECJE_SPOROCILO velja za celo sporocilo, ne le za okvir: prej so se nadaljevalni okvirji lepili brez
        meje in rele (ali kdor se zanj izdaja) je lahko porabil ves pomnilnik (pregled 19. 10. 2026, kot link_ws)."""
        podatki, prva = bytearray(), None
        while True:
            b0, b1 = self._beri(2)
            op, dolzina = b0 & 0x0F, b1 & 0x7F
            if dolzina == 126:
                dolzina = struct.unpack(">H", self._beri(2))[0]
            elif dolzina == 127:
                dolzina = struct.unpack(">Q", self._beri(8))[0]
            if dolzina > NAJVECJE_SPOROCILO:
                raise ConnectionError("prevelik okvir")
            if op == 0x0 and len(podatki) + dolzina > NAJVECJE_SPOROCILO:
                raise ConnectionError("preveliko sporocilo")       # pred branjem telesa: nic se ne kopici
            maska = self._beri(4) if b1 & 0x80 else None
            telo = self._beri(dolzina)
            if maska:
                telo = _maskiraj(telo, maska)
            if op == 0x8:
                raise ConnectionError("zaprto")
            if op == 0x9:
                self.poslji(telo, 0xA)
                continue
            if op == 0xA:
                continue
            if op != 0x0:
                prva = op
                podatki = bytearray()          # novo sporocilo (podatkovni okvir brez nadaljevanja) zacne znova
            podatki += telo
            if b0 & 0x80:
                return prva, bytes(podatki)

    def zapri(self) -> None:
        """Konca povezavo (okvir zaprtja + shutdown), ne sprosti pa vticnice.

        Druga nit morda se bere ali pise; ce bi vticnico zaprli, bi sistem njeno stevilko takoj dal
        naslednji povezavi (npr. novemu kanalu), stara nit pa bi brala njene bajte - TLS nato pade
        (WRONG_VERSION_NUMBER). shutdown obe niti le zbudi; vticnico sprosti `sprosti()` ali Python,
        ko je nihce vec ne uporablja.
        """
        if getattr(self, "_koncana", False):
            return
        self._koncana = True
        try:
            self.poslji(b"", 0x8)
        except Exception:
            pass
        _ustavi(self.s)

    def sprosti(self) -> None:
        """Zapre vticnico; klic samo, ko nobena druga nit vec ne dela z njo."""
        self.zapri()
        try:
            self.s.close()
        except Exception:
            pass


class BrezOdgovora(ConnectionError):
    """Rele na zahtevo ni odgovoril niti z enim bajtom (povezava je bila mrtva): ponovitev na novi je varna."""


def _nova_tls(gostitelj: str = GOSTITELJ, rok_s: float = 15.0, kontekst: Optional[ssl.SSLContext] = None,
              seja: Optional[ssl.SSLSession] = None) -> ssl.SSLSocket:
    """Nova povezava TLS do releja (preverjeno potrdilo). `seja`: obnova prejsnje seje TLS istega `kontekst`."""
    surovi = socket.create_connection((gostitelj, 443), timeout=rok_s)
    # Skozi kanal tece TLS Safeer Linka v majhnih kosih (sporocila, potrditve tokov): vsak naj gre takoj.
    link_vticnik.brez_zamika(surovi)
    try:
        return (kontekst or ssl.create_default_context()).wrap_socket(surovi, server_hostname=gostitelj, session=seja)
    except Exception:
        surovi.close()
        raise


def _seja_za_obnovo(s) -> Optional[ssl.SSLSession]:
    """Seja TLS, s katero lahko naslednjo povezavo obnovimo (TLS 1.3: le, ce je ze prisla vstopnica)."""
    try:
        seja = s.session
        return seja if seja is not None and seja.has_ticket else None
    except (AttributeError, ValueError, OSError):
        return None


def _mirna(s) -> bool:
    """Neuporabljena povezava je ziva, ce rele ni poslal ne podatkov ne zaprtja.

    Berljiva je lahko tudi samo zaradi notranjih zapisov TLS 1.3 (vstopnica seje po rokovanju): te prebere
    recv brez cakanja in javi SSLWantReadError - povezava je ziva."""
    try:
        berljiva, _, _ = select.select([s], [], [], 0)
        if not berljiva and not s.pending():
            return True
        rok = s.gettimeout()
        s.settimeout(0)
        try:
            s.recv(1)
            return False            # podatki ali konec (b"") na neuporabljeni povezavi: ni za kanal
        except ssl.SSLWantReadError:
            return True
        finally:
            s.settimeout(rok)
    except (OSError, ValueError):
        return False


class TopleTls:
    """Ena vnaprej odprta povezava TLS do releja, da nov kanal ne caka na TCP in TLS (~2 obhoda, ~100 ms).

    Na rele ne posljemo nicesar, dokler povezave ne vzamemo, zato ne steje v kvoto Workerja. Drzimo jo le,
    dokler jo kdo zeli (`zelim`, `vzemi`) - po TOPLA_ZELJA_S brez zelje je ne obnavljamo vec. Ker jo Cloudflare
    brez zahteve zapre po 10-15 s, jo vsakih TOPLA_STAROST_S zamenjamo z novo; ta obnovi sejo TLS prejsnje
    (krajse rokovanje, brez verige potrdil). Nova se odpre, preden staro zapremo, zato med zamenjavo kanal ni hladen.

    Vse cakanje (TCP, TLS, select) je v svoji niti `safeer-rele-topla`; `zelim`, `vzemi` in `ustavi` drzijo zaklep
    le za hip (brez omrezja), zato jih glavna zanka GTK ne obcuti. Ob izhodu procesa nit ustavi `ustavi` (atexit).
    """

    def __init__(self, gostitelj: str = GOSTITELJ, rok_s: float = 15.0,
                 nova: Optional[Callable[[], ssl.SSLSocket]] = None) -> None:
        self._gostitelj, self._rok_s = gostitelj, rok_s
        self._kontekst: Optional[ssl.SSLContext] = None
        self._seja: Optional[ssl.SSLSession] = None
        self._nova = nova or self._odpri
        self._zaklep = threading.Lock()
        self._budilka: Optional[tuple] = None
        self._s: Optional[ssl.SSLSocket] = None
        self._odprta = 0.0
        self._zelja = 0.0
        self._nit: Optional[threading.Thread] = None
        self._ustavljena = False
        self._ne_pred = 0.0         # premor po neuspehu ali hitrem zaprtju: nove povezave ne prej
        self._cakaj = 5.0           # naslednji premor (podvaja se do 300 s; redna zamenjava ga ponastavi)

    def zelim(self) -> None:
        """Naj bo topla povezava pripravljena (in ostane, dokler zelja ne potece)."""
        with self._zaklep:
            self._zelja = time.monotonic()
            if self._ustavljena:
                return
            if self._budilka is None:
                self._budilka = socket.socketpair()
                for b in self._budilka:
                    b.setblocking(False)        # zbujanje nikoli ne blokira klicatelja
            if self._nit is None:
                self._nit = threading.Thread(target=self._teci, name="safeer-rele-topla", daemon=True)
                self._nit.start()
        self._zbudi()

    def _odpri(self) -> ssl.SSLSocket:
        """Nova povezava z istim kontekstom TLS; ce imamo sejo prejsnje povezave, jo obnovimo."""
        if self._kontekst is None:
            self._kontekst = ssl.create_default_context()
        seja = self._seja
        try:
            return _nova_tls(self._gostitelj, self._rok_s, self._kontekst, seja)
        except ValueError:
            if seja is None:
                raise
            # Seje ni mogoce uporabiti (npr. drug kontekst): brez nje, sicer bi vsak poskus padel (in podvajal premor).
            self._seja = None
            return _nova_tls(self._gostitelj, self._rok_s, self._kontekst)

    def _shrani_sejo(self, s) -> None:
        seja = _seja_za_obnovo(s)
        if seja is not None:
            self._seja = seja

    def vzemi(self) -> Optional[ssl.SSLSocket]:
        """Topla povezava ali None (je ni ali ni vec ziva); takoj zacne pripravljati naslednjo."""
        with self._zaklep:
            s, self._s = self._s, None
            starost = time.monotonic() - self._odprta
        self.zelim()
        if s is None:
            return None
        if starost > TOPLA_NAJVEC_S or not _mirna(s):
            _zapri_tiho(s)
            return None
        self._shrani_sejo(s)        # po _mirna: vstopnica TLS 1.3 je prebrana
        return s

    def ustavi(self) -> None:
        """Ustavi nit in zapre toplo povezavo; po tem `zelim` nima ucinka (izhod procesa)."""
        with self._zaklep:
            self._ustavljena = True
            s, self._s = self._s, None
            budilka = None
            if self._nit is None:
                budilka, self._budilka = self._budilka, None    # niti ni: budilko zapremo tu, sicer jo nit
        if s is not None:
            _zapri_tiho(s)
        if budilka is not None:
            for b in budilka:
                _zapri_tiho(b)
        else:
            self._zbudi()

    def _zbudi(self) -> None:
        try:
            self._budilka[1].send(b"z")
        except (OSError, TypeError, AttributeError):
            pass

    def _pocakaj(self, s, cas: float) -> None:
        """Do `cas` sekund ali do zbujanja ali do berljive `s` (rele jo je zaprl)."""
        bralni = [self._budilka[0]] + ([s] if s is not None else [])
        try:
            select.select(bralni, [], [], cas)
        except (OSError, ValueError):
            time.sleep(min(cas, 0.05))      # `s` je med tem vzel in zaprl nekdo drug
        try:
            while self._budilka[0].recv(64):
                pass
        except OSError:
            pass

    def _premor(self) -> None:
        """Po neuspehu ali zgodnjem zaprtju: naslednje povezave ne prej kot cez `_cakaj` (podvaja se)."""
        self._ne_pred = time.monotonic() + self._cakaj
        self._cakaj = min(self._cakaj * 2, 300.0)

    def _teci(self) -> None:
        while True:
            with self._zaklep:
                if self._ustavljena or time.monotonic() - self._zelja > TOPLA_ZELJA_S:
                    s, self._s, self._nit = self._s, None, None
                    budilka = None
                    if self._ustavljena:
                        budilka, self._budilka = self._budilka, None
                    break
                s, odprta = self._s, self._odprta
                zelja_ostane = TOPLA_ZELJA_S - (time.monotonic() - self._zelja)
                # Pod zaklepom: ko jo `vzemi` odnese, je ta nit ne bere vec (TLS ne prenese dveh bralcev).
                ziva = s is not None and _mirna(s)
                if ziva:
                    self._shrani_sejo(s)
            if s is None:
                premor = self._ne_pred - time.monotonic()
                if premor > 0:
                    self._pocakaj(None, min(premor, max(0.01, zelja_ostane)))
                    continue
                nova = self._odpri_novo()
                if nova is not None:
                    with self._zaklep:
                        if not self._ustavljena and self._s is None:
                            nova, self._s, self._odprta = None, nova, time.monotonic()
                    if nova is not None:
                        _zapri_tiho(nova)
                continue
            starost = time.monotonic() - odprta
            if not ziva:
                # Rele jo je zaprl (ali poslal kaj nepricakovanega), preden smo jo hoteli zamenjati.
                with self._zaklep:
                    if self._s is not s:
                        continue            # medtem jo je vzel `vzemi`
                    self._s = None
                _zapri_tiho(s)
                if starost < TOPLA_STAROST_S:
                    self._premor()          # ne odpiramo takoj nove (rele zapira hitreje, kot smo izmerili)
                continue
            ostane = TOPLA_STAROST_S - starost
            if ostane > 0:
                self._pocakaj(s, max(0.01, min(ostane, zelja_ostane, 60.0)))
                continue
            # Redna zamenjava (brez premora): najprej nova (obnovi sejo stare), nato stara ven - brez vrzeli.
            self._cakaj = 5.0               # stara je dozivela redno zamenjavo: rele je zdrav
            nova = self._odpri_novo()
            with self._zaklep:
                stara = None
                if self._ustavljena:
                    pass
                elif self._s is s:
                    stara, self._s = s, nova
                    if nova is not None:
                        nova, self._odprta = None, time.monotonic()
                elif self._s is None and nova is not None:
                    nova, self._s, self._odprta = None, nova, time.monotonic()
            for odvecna in (stara, nova):
                if odvecna is not None:
                    _zapri_tiho(odvecna)
        if s is not None:
            _zapri_tiho(s)
        if budilka is not None:
            for b in budilka:
                _zapri_tiho(b)

    def _odpri_novo(self) -> Optional[ssl.SSLSocket]:
        """Nova povezava ali None (in premor). Premor ponastavi sele redna zamenjava, ne uspesno odpiranje:
        rele, ki povezavo sprejme in takoj zapre, mora cakati vedno dlje."""
        try:
            return self._nova()
        except Exception:
            self._premor()
            return None


def _zapri_tiho(s) -> None:
    try:
        s.close()
    except Exception:
        pass


#: Skupna topla povezava procesa (agent huba in vsi LokalniRele gredo na isti rele).
_topla = TopleTls()
atexit.register(_topla.ustavi)


def _tls_za_oddajo(gostitelj: str = GOSTITELJ, rok_s: float = 15.0) -> Optional[ssl.SSLSocket]:
    """Ob gneci na domaci liniji: TLS do releja skozi mobilno omrezje telefona (core/gneca.py); sicer None."""
    surovi = gneca.tcp_za_oddajo(gostitelj, 443, rok_s)
    if surovi is None:
        return None
    try:
        surovi.settimeout(rok_s)
        return ssl.create_default_context().wrap_socket(surovi, server_hostname=gostitelj)
    except Exception as e:  # noqa: BLE001 - tiho neposredno
        print("[Global Link] kanal skozi telefon ni uspel: %r" % (e,), flush=True)
        _zapri_tiho(surovi)
        return None


def odpri_kanal(pot: str, glave: Callable[[], dict], topla: Optional[TopleTls] = None,
                oddaja: bool = False) -> WsOdjemalec:
    """WebSocket do releja: najprej po topli povezavi; ce je bila mrtva (brez odgovora), po novi.

    `oddaja`: kanal nosi veliko oddajo Safeerja - ob gneci gre skozi telefon (topla povezava je na domaci liniji)."""
    if oddaja:
        tls = _tls_za_oddajo()
        if tls is not None:
            try:
                return WsOdjemalec(pot, glave(), tls=tls)
            except Exception as e:  # noqa: BLE001 - tiho neposredno
                print("[Global Link] kanal skozi telefon ni uspel: %r" % (e,), flush=True)
    topla = _topla if topla is None else topla
    s = topla.vzemi()
    if s is not None:
        try:
            return WsOdjemalec(pot, glave(), tls=s)
        except BrezOdgovora:
            pass
    return WsOdjemalec(pot, glave())


def _ustavi(s: socket.socket) -> None:
    try:
        s.shutdown(socket.SHUT_RDWR)
    except Exception:
        pass


def cev(ws: WsOdjemalec, tcp: socket.socket) -> None:
    """Bajti v obe smeri, dokler ena stran ne konca; nato zapre obe (sele ko obe niti koncata)."""
    # Sporocilo Linka pride iz releja pogosto v dveh okvirjih (dva `sendall` na krajevno vticnico). Z Naglovim
    # algoritmom drugi kos caka na potrditev prvega - na zanki do 40 ms (izmerjeno v krogu 106: 41 ms proti 0,2 ms).
    link_vticnik.brez_zamika(tcp)

    def iz_tcp():
        try:
            while True:
                kos = tcp.recv(KOS)
                if not kos:
                    break
                ws.poslji(kos)
        except Exception:
            pass
        ws.zapri()

    nit = threading.Thread(target=iz_tcp, name="safeer-rele-tcp", daemon=True)
    nit.start()
    try:
        while True:
            op, podatki = ws.prejmi()
            if op == 0x2 and podatki:
                tcp.sendall(podatki)
    except Exception:
        pass
    _ustavi(tcp)
    ws.zapri()
    nit.join(15)
    if not nit.is_alive():
        try:
            tcp.close()
        except Exception:
            pass
        ws.sprosti()


# ------------------------------------------------------------------ agent huba

class AgentHuba:
    """Drzi hub dosegljiv prek link.safeer.si, dokler je `vrata()` > 0 in je Global Link vklopljen."""

    def __init__(self, vrata: Callable[[], int], vklopljen: Callable[[], bool],
                 krog_json: Callable[[], dict], dnevnik: Callable[[str], None] = print,
                 namigi: Optional[Callable[[], List[str]]] = None) -> None:
        self.vrata, self.vklopljen, self.krog_json, self.dnevnik = vrata, vklopljen, krog_json, dnevnik
        #: `candidate_hints` prisotnosti: podpisan oglas neposredne poti od zunaj (core/link_neposredno) ali [].
        self.namigi = namigi
        self._nit: Optional[threading.Thread] = None
        self._ws: Optional[WsOdjemalec] = None
        self.stanje = "izklopljen"

    def zazeni(self) -> None:
        if self._nit is None:
            self._nit = threading.Thread(target=self._zanka, name="safeer-global-link", daemon=True)
            self._nit.start()

    def objavi(self) -> None:
        from core import link_krog
        nas = id_iz_kljuca(link_krog.javni_kljuc_b64())
        prisotnost = {"allow": dovoljeni_iz_kroga(self.krog_json(), nas), "ttl": 120}
        try:
            namigi = [str(n)[:512] for n in (self.namigi() if self.namigi is not None else [])][:4]
        except Exception:  # noqa: BLE001 - brez oglasa ostane prisotnost kot doslej
            namigi = []
        if namigi:
            prisotnost["candidate_hints"] = namigi
        telo = json.dumps(prisotnost).encode()
        z = urllib.request.Request(f"https://{GOSTITELJ}/v1/presence", data=telo, method="POST",
                                   headers=dict(podpisane_glave("POST", "/v1/presence", telo), **{"Content-Type": "application/json", "User-Agent": UA}))
        with urllib.request.urlopen(z, timeout=15) as r:
            r.read()

    def _kanal(self, kanal: str) -> None:
        pot = f"/v1/accept?kanal={kanal}"
        tcp = None
        try:
            tcp = socket.create_connection(("127.0.0.1", self.vrata()), timeout=10)
            tcp.settimeout(None)
            ws = odpri_kanal(pot, lambda: podpisane_glave("GET", pot))
        except Exception as e:
            self.dnevnik(f"[Global Link] kanala ni bilo mogoce odpreti: {e}")
            if tcp is not None:
                tcp.close()
            return
        try:
            cev(ws, tcp)
        except BaseException:
            # cev zapre obe strani sama; ce je padla prej, ju zapremo tu (kanal ne sme ostati odprt).
            _ustavi(tcp)
            ws.zapri()
            raise

    def _vzdrzuj(self, ws: WsOdjemalec) -> None:
        """Ping in ponovna objava; ob izklopu ali ustavitvi huba zapre povezavo (glavna zanka se vrne)."""
        zadnja_objava = time.time()
        while self._ws is ws:
            time.sleep(PING_VSAKIH_S)
            if self._ws is not ws:
                return
            try:
                if not (self.vklopljen() and self.vrata() > 0):
                    ws.zapri()
                    return
                ws.besedilo("ping")
                if time.time() - zadnja_objava > OBJAVA_VSAKIH_S:
                    self.objavi()
                    zadnja_objava = time.time()
            except Exception:
                ws.zapri()
                return

    def _zanka(self) -> None:
        cakaj = 5
        while True:
            if not (self.vklopljen() and self.vrata() > 0):
                self.stanje = "izklopljen"
                time.sleep(15)
                continue
            try:
                self.objavi()
                ws = WsOdjemalec("/v1/listen", podpisane_glave("GET", "/v1/listen"))
                # Toplo povezavo hub drzi le TOPLA_ZELJA_S po zadnjem kanalu (odpri_kanal -> vzemi): prvi kanal po
                # mirovanju je hladen, naslednji (npr. zaslon po povezavi v mrezo) gredo brez TCP in TLS.
                self._ws, self.stanje, cakaj = ws, "povezan", 5
                self.dnevnik("[Global Link] hub je dosegljiv prek link.safeer.si")
                threading.Thread(target=self._vzdrzuj, args=(ws,), name="safeer-global-link-ping", daemon=True).start()
                try:
                    while True:
                        op, podatki = ws.prejmi()
                        if op == 0x1 and podatki.startswith(b"{"):
                            s = json.loads(podatki)
                            if s.get("type") == "incoming" and len(str(s.get("kanal", ""))) == 32:
                                threading.Thread(target=self._kanal, args=(str(s["kanal"]),), daemon=True).start()
                finally:
                    self._ws = None
                    ws.zapri()
            except Exception as e:
                self.stanje = "napaka"
                self.dnevnik(f"[Global Link] {e}; znova cez {cakaj} s")
                time.sleep(cakaj)
                cakaj = min(cakaj * 2, 300)


# ------------------------------------------------------------------ odjemalec: lokalna vrata do oddaljenega huba

def _uid_lokalne_povezave(vrata_odjemalca: int, nasa_vrata: int, tabela: str = "/proc/net/tcp") -> Optional[int]:
    """Uporabnik (uid) procesa, ki se je na 127.0.0.1 povezal z nasimi vrati; None, ce se ne da ugotoviti.

    TCP nima SO_PEERCRED (ta velja le za Unix vticnice), zato na Linuxu pogledamo tabelo jedra: vrstica, kjer
    je lokalni konec odjemalceva vrata in oddaljeni konec nasa vrata, ima v 8. stolpcu uid lastnika."""
    try:
        with open(tabela, "r", encoding="ascii") as d:
            vrstice = d.read().splitlines()[1:]
    except OSError:
        return None
    for v in vrstice:
        polja = v.split()
        if len(polja) < 8:
            continue
        try:
            if int(polja[1].rsplit(":", 1)[1], 16) == vrata_odjemalca and int(polja[2].rsplit(":", 1)[1], 16) == nasa_vrata:
                return int(polja[7])
        except ValueError:
            continue
    return None


class LokalniRele:
    """127.0.0.1:vrata, ki vodijo do huba `cilj` prek link.safeer.si (za naprave zunaj domacega omrezja).

    Vsaka lokalna TCP povezava dobi svoj kanal; TLS do huba (s pripetim odtisom) teče skozi nespremenjen.
    """

    def __init__(self, cilj: str, kljuc: Optional[Callable[[], str]] = None,
                 podpisi: Optional[Callable[[bytes], str]] = None, poslusaj: bool = True) -> None:
        """`poslusaj=False`: brez lastnih krajevnih vrat - povezave mu preda klicatelj (`kanal`), npr.
        core/link_neposredno.LokalniOdZunaj, ko neposredna pot ni na voljo."""
        self.cilj, self.kljuc, self.podpisi = cilj, kljuc, podpisi
        self.zadnja_napaka = ""       # za dnevnik: zakaj zadnji kanal ni uspel (npr. 404, 429)
        self.streznik = None
        self.vrata = 0
        self._tece = True
        if poslusaj:
            self.streznik = socket.create_server(("127.0.0.1", 0))
            self.vrata = self.streznik.getsockname()[1]
            threading.Thread(target=self._sprejemaj, name="safeer-rele-lokalno", daemon=True).start()

    def _sprejemaj(self) -> None:
        while self._tece:
            try:
                tcp, naslov = self.streznik.accept()
            except OSError as e:
                if self._tece and os_deskriptorji.prehodna_napaka_accept(e):
                    time.sleep(os_deskriptorji.PREMOR_PO_NAPAKI_ACCEPT_S)
                    continue
                return
            if not self._tece:
                tcp.close()             # zaprt: povezava, ki je prisla tik pred tem, ne dobi kanala releja
                return
            if not self._nas_proces(naslov):
                # Drug uporabnik tega racunalnika ne sme uporabljati kanala, podpisanega z nasim kljucem.
                self.zadnja_napaka = "tuj_uporabnik"
                try:
                    tcp.close()
                except Exception:
                    pass
                continue
            oddaja = gneca.vzemi_oddajo(naslov[1]) if isinstance(naslov, tuple) and len(naslov) > 1 else False
            threading.Thread(target=self._kanal, args=(tcp, oddaja), daemon=True).start()

    def _nas_proces(self, naslov) -> bool:
        """Na Linuxu sprejmemo samo povezave procesov istega uporabnika (uid). Drugje (Windows) ali kadar
        tabele ni, velja kot prej: vrata so le na 127.0.0.1, hub pa zahteva TLS s pripetim odtisom."""
        if not hasattr(os, "getuid") or not isinstance(naslov, tuple) or len(naslov) < 2:
            return True
        uid = _uid_lokalne_povezave(int(naslov[1]), self.vrata)
        return uid is None or uid == os.getuid()

    def kanal(self, tcp: socket.socket, oddaja: bool = False) -> None:
        """Ena krajevna povezava skozi en kanal releja (blokira do konca povezave). `oddaja`: velika oddaja."""
        self._kanal(tcp, oddaja)

    def _kanal(self, tcp: socket.socket, oddaja: bool = False) -> None:
        kanal = os.urandom(16).hex()
        pot = f"/v1/connect?to={self.cilj}&kanal={kanal}"
        ws = None
        try:
            ws = odpri_kanal(pot, lambda: podpisane_glave("GET", pot, kljuc=self.kljuc, podpisi=self.podpisi),
                             oddaja=oddaja)
            ws.s.settimeout(20)
            op, podatki = ws.prejmi()
            if op != 0x1 or podatki != b"ready":
                raise ConnectionError("hub ni sprejel kanala")
            ws.s.settimeout(None)
        except Exception as e:
            self.zadnja_napaka = str(e)[:120] or type(e).__name__
            if ws is not None:
                ws.sprosti()
            try:
                tcp.close()
            except Exception:
                pass
            return
        cev(ws, tcp)

    def zapri(self) -> None:
        """Samo close() na Linuxu ne zbudi niti v accept(): vrata bi poslusala naprej in naslednja krajevna povezava
        bi dobila kanal releja, podpisan z nasim kljucem (preverjeno 18. 10. 2026, kot link_neposredno). shutdown()
        accept() takoj prekine."""
        self._tece = False
        if self.streznik is None:
            return
        try:
            self.streznik.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.streznik.close()
        except Exception:
            pass


# ------------------------------------------------------------------ odjemalec: kateri hub je doma (prek releja)

# Clani kroga, ki se prek releja niso odzvali kot hub: minuto jih ne klicemo (dnevna kvota Workerja).
_ODSOTNI: dict = {}
PREMOR_ODSOTNEGA_S = 60.0


def najdi_hub_prek_releja(krog_json: dict, nas_id: str, prednost: Optional[List[str]] = None,
                          kljuc: Optional[Callable[[], str]] = None,
                          podpisi: Optional[Callable[[bytes], str]] = None,
                          rok_s: float = 15.0, zdaj: Optional[float] = None):
    """Domaci hub, ko ga v LAN ni: po vrsti poskusi clane kroga prek link.safeer.si.

    Worker spusti samo do clana, ki nas ima na seznamu dovoljenih (in samo, ce gosti hub). Zaupanje:
    hubovo potrdilo mora nositi natanko kljuc tega clana iz kroga. Vrne (id, LokalniRele, odtis) ali None.
    """
    from core import link_tls
    zdaj = time.time() if zdaj is None else zdaj
    kljuci = {}
    for c in (krog_json.get("clani") or {}).values():
        try:
            kljuci[id_iz_kljuca(c["kljuc"])] = c["kljuc"]
        except Exception:
            continue
    kandidati = dovoljeni_iz_kroga(krog_json, nas_id)
    naprej = [p for p in (prednost or []) if p in kandidati]
    for cilj in naprej + [k for k in kandidati if k not in naprej]:
        if zdaj - _ODSOTNI.get(cilj, 0.0) < PREMOR_ODSOTNEGA_S:
            continue
        rele = LokalniRele(cilj, kljuc=kljuc, podpisi=podpisi)
        odtis, javni = link_tls.potrdilo_huba("wss://127.0.0.1:%d/" % rele.vrata, timeout=rok_s)
        if odtis and link_tls.isti(javni, kljuci.get(cilj)):
            _ODSOTNI.pop(cilj, None)
            return cilj, rele, odtis
        rele.zapri()
        _ODSOTNI[cilj] = zdaj
    return None
