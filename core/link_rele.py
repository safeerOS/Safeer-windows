"""Global Link na racunalniku: hub je dosegljiv svojim napravam tudi zunaj domacega omrezja.

Agent se prijavi na link.safeer.si (podpis s kljucem te naprave, brez gesla), objavi, katere naprave
ga smejo doseci (clani kroga zaupanja), in caka na kanale. Ko se naprava iz kroga poveze, agent odpre
kanal in ga poveze z lokalnim hubom (127.0.0.1:vrata). Skozi kanal tece TLS Safeer Linka od naprave do
huba, zato rele (Cloudflare) vidi samo sifrirane bajte. Drug uporabnik do tega huba ne pride: Worker
spusti samo naprave s seznama `allow`.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import threading
import time
import urllib.request
from typing import Callable, List, Optional

GOSTITELJ = "link.safeer.si"
OBJAVA_VSAKIH_S = 60
PING_VSAKIH_S = 30
KOS = 16 * 1024
#: Cloudflare (Browser Integrity Check) zavrne privzeti "Python-urllib" z 403; Safeer se predstavi z imenom.
UA = "SafeerLink/1.0"


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

    def __init__(self, pot: str, glave: dict, gostitelj: str = GOSTITELJ, rok_s: float = 15.0) -> None:
        surovi = socket.create_connection((gostitelj, 443), timeout=rok_s)
        self.s = ssl.create_default_context().wrap_socket(surovi, server_hostname=gostitelj)
        try:
            self._rokovanje(pot, glave, gostitelj)
        except Exception:
            self.s.close()
            raise
        self.s.settimeout(None)
        self._pisi = threading.Lock()

    def _rokovanje(self, pot: str, glave: dict, gostitelj: str) -> None:
        kljuc = base64.b64encode(os.urandom(16)).decode()
        zahteva = [f"GET {pot} HTTP/1.1", f"Host: {gostitelj}", f"User-Agent: {UA}", "Upgrade: websocket", "Connection: Upgrade",
                   f"Sec-WebSocket-Key: {kljuc}", "Sec-WebSocket-Version: 13"]
        zahteva += [f"{k}: {v}" for k, v in glave.items()]
        self.s.sendall(("\r\n".join(zahteva) + "\r\n\r\n").encode())
        odgovor = b""
        while b"\r\n\r\n" not in odgovor:
            kos = self.s.recv(4096)
            if not kos:
                raise ConnectionError("rele je zaprl povezavo")
            odgovor += kos
            if len(odgovor) > 16384:
                raise ConnectionError("predolga glava")
        glava, _, self._ostanek = odgovor.partition(b"\r\n\r\n")
        vrstica = glava.split(b"\r\n", 1)[0].decode(errors="replace")
        if " 101 " not in vrstica + " ":
            raise ConnectionError("rele zavrnil: " + vrstica)
        pricakovano = base64.b64encode(hashlib.sha1((kljuc + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
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
        """Vrne (opkoda, podatki); na ping odgovori sam, zaprtje dvigne ConnectionError."""
        podatki, prva = b"", None
        while True:
            b0, b1 = self._beri(2)
            op, dolzina = b0 & 0x0F, b1 & 0x7F
            if dolzina == 126:
                dolzina = struct.unpack(">H", self._beri(2))[0]
            elif dolzina == 127:
                dolzina = struct.unpack(">Q", self._beri(8))[0]
            if dolzina > 4 * 1024 * 1024:
                raise ConnectionError("prevelik okvir")
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
            podatki += telo
            if b0 & 0x80:
                return prva, podatki

    def zapri(self) -> None:
        try:
            self.poslji(b"", 0x8)
        except Exception:
            pass
        try:
            self.s.close()
        except Exception:
            pass


def cev(ws: WsOdjemalec, tcp: socket.socket) -> None:
    """Bajti v obe smeri, dokler ena stran ne konca; nato zapre obe."""
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

    threading.Thread(target=iz_tcp, name="safeer-rele-tcp", daemon=True).start()
    try:
        while True:
            op, podatki = ws.prejmi()
            if op == 0x2 and podatki:
                tcp.sendall(podatki)
    except Exception:
        pass
    try:
        tcp.close()
    except Exception:
        pass
    ws.zapri()


# ------------------------------------------------------------------ agent huba

class AgentHuba:
    """Drzi hub dosegljiv prek link.safeer.si, dokler je `vrata()` > 0 in je Global Link vklopljen."""

    def __init__(self, vrata: Callable[[], int], vklopljen: Callable[[], bool],
                 krog_json: Callable[[], dict], dnevnik: Callable[[str], None] = print) -> None:
        self.vrata, self.vklopljen, self.krog_json, self.dnevnik = vrata, vklopljen, krog_json, dnevnik
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
        telo = json.dumps({"allow": dovoljeni_iz_kroga(self.krog_json(), nas), "ttl": 120}).encode()
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
            ws = WsOdjemalec(pot, podpisane_glave("GET", pot))
        except Exception as e:
            self.dnevnik(f"[Global Link] kanala ni bilo mogoce odpreti: {e}")
            if tcp is not None:
                tcp.close()
            return
        cev(ws, tcp)

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

class LokalniRele:
    """127.0.0.1:vrata, ki vodijo do huba `cilj` prek link.safeer.si (za naprave zunaj domacega omrezja).

    Vsaka lokalna TCP povezava dobi svoj kanal; TLS do huba (s pripetim odtisom) teče skozi nespremenjen.
    """

    def __init__(self, cilj: str, kljuc: Optional[Callable[[], str]] = None,
                 podpisi: Optional[Callable[[bytes], str]] = None) -> None:
        self.cilj, self.kljuc, self.podpisi = cilj, kljuc, podpisi
        self.zadnja_napaka = ""       # za dnevnik: zakaj zadnji kanal ni uspel (npr. 404, 429)
        self.streznik = socket.create_server(("127.0.0.1", 0))
        self.vrata = self.streznik.getsockname()[1]
        threading.Thread(target=self._sprejemaj, name="safeer-rele-lokalno", daemon=True).start()

    def _sprejemaj(self) -> None:
        while True:
            try:
                tcp, _ = self.streznik.accept()
            except OSError:
                return
            threading.Thread(target=self._kanal, args=(tcp,), daemon=True).start()

    def _kanal(self, tcp: socket.socket) -> None:
        kanal = os.urandom(16).hex()
        pot = f"/v1/connect?to={self.cilj}&kanal={kanal}"
        ws = None
        try:
            ws = WsOdjemalec(pot, podpisane_glave("GET", pot, kljuc=self.kljuc, podpisi=self.podpisi))
            ws.s.settimeout(20)
            op, podatki = ws.prejmi()
            if op != 0x1 or podatki != b"ready":
                raise ConnectionError("hub ni sprejel kanala")
            ws.s.settimeout(None)
        except Exception as e:
            self.zadnja_napaka = str(e)[:120] or type(e).__name__
            if ws is not None:
                ws.zapri()
            try:
                tcp.close()
            except Exception:
                pass
            return
        cev(ws, tcp)

    def zapri(self) -> None:
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
        if odtis and javni and javni == kljuci.get(cilj):
            _ODSOTNI.pop(cilj, None)
            return cilj, rele, odtis
        rele.zapri()
        _ODSOTNI[cilj] = zdaj
    return None
