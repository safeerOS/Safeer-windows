"""Safeer Link: glasba in video z druge naprave, predvajana sproti v lokalnem predvajalniku.

Naprava (TV, telefon, tablica, racunalnik) da v odgovoru na `files.list` svoj streznik datotek
`{base_url, fp, token}`. Lokalni predvajalniki (GStreamer, VLC, <audio> v strani) ne znajo pripeti
odtisa samopodpisanega potrdila niti poslati zetona v glavi. Zato ta modul na 127.0.0.1 odpre
majhen streznik: vsak vir dobi nakljucno, neuganljivo pot `/m/<32 hex>`, zahtevo (z `Range`) pa
preda naprej po HTTPS - s pripetim odtisom in zetonom v glavi `X-Safeer-Token`.

- Nic se ne shrani na disk: predvajanje se zacne takoj, previjanje dela z `Range`.
- Zeton ne gre nikoli v naslov (ostal bi v dnevnikih predvajalnika).
- Streznik sprejema samo povezave s te naprave (127.0.0.1).

Pot do naprave: najprej neposredno (`base_url` v domacem omrezju). Ce ta ni dosegljiva (npr. zunaj
doma), gre tok prek Global Linka: lokalna vrata releja do naprave (id iz njenega kljuca) in pot
`/cast/d/<id>` na njenem Hubu. Zaupanje prek releja da kljuc: kljuc v potrdilu mora biti kljuc te
naprave iz kroga zaupanja. Rele (link.safeer.si) vidi samo sifrirane bajte.
"""
from __future__ import annotations

import http.client
import http.server
import ipaddress
import os
import re
import secrets
import threading
import time
import urllib.parse
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

from core import link_tls

KOS = 256 * 1024
NAJVEC_VIROV = 512
#: Koliko casa velja odlocitev o poti (neposredno / rele), preden jo preverimo znova.
POT_VELJA_S = 60.0
#: Kratek poskus neposredne povezave: doma odgovori v nekaj ms, zunaj doma pa sploh ne.
NEPOSREDNO_CAKAJ_S = 2.5
#: Glave odgovora, ki jih predvajalnik potrebuje (vse druge ostanejo pri napravi).
GLAVE_NAPREJ = ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "Last-Modified", "ETag")


@dataclass(frozen=True)
class Vir:
    """Ena datoteka na drugi napravi. `kljuc` = javni kljuc naprave iz kroga (za pot prek releja)."""
    base_url: str
    odtis: str
    zeton: str
    id_datoteke: str
    kljuc: str = ""
    mime: str = ""
    #: Tok torrenta (`magnet.stream`): natancna pot na strezniku naprave (/m/... ali /magnet/...) namesto /d/<id>.
    pot: str = ""


def vir_iz_streznika(streznik: dict, id_datoteke: str, kljuc: str = "", mime: str = "") -> Optional[Vir]:
    """Vir iz polja `server` odgovora na `files.list`; None, ce streznik ni HTTPS s pripetim odtisom
    na naslovu v domacem omrezju (naprava ne more poslati racunalnika nekam na internet)."""
    if not isinstance(streznik, dict):
        return None
    osnova = str(streznik.get("base_url") or "").rstrip("/")
    odtis = str(streznik.get("fp") or "")
    zeton = str(streznik.get("token") or "")
    if not osnova.startswith("https://") or not odtis or not zeton or not id_datoteke:
        return None
    try:
        ip = ipaddress.ip_address(urllib.parse.urlparse(osnova).hostname or "")
    except ValueError:
        return None
    if not (ip.is_private or ip.is_link_local or ip.is_loopback):
        return None
    # Vrsta gre v glavo odgovora: samo "vrsta/podvrsta", brez presledkov in novih vrstic.
    mime = str(mime or "")
    if not re.fullmatch(r"[\w.+-]+/[\w.+-]+", mime):
        mime = ""
    return Vir(osnova, odtis, zeton, str(id_datoteke), str(kljuc or ""), mime)


#: Poti tokov torrenta na strezniku datotek: racunalnik `/m/<skrivnost>/<ime>`, Android `/magnet/<skrivnost>`.
_POT_TOKA = re.compile(r"/(m|magnet)/[A-Za-z0-9_\-]{8,200}(/[^/?#\\]{1,300})?")


def vir_toka(streznik: dict, pot: str, mime: str = "") -> Optional[Vir]:
    """Vir za tok torrenta, ki ga pretaka druga naprava (odgovor `magnet.stream`: `server` + `path`). Ista pravila kot
    pri datotekah (HTTPS s pripetim odtisom, zeton, naslov v domacem omrezju); pot mora biti pot toka, nic drugega."""
    pot = str(pot or "")
    if not _POT_TOKA.fullmatch(pot) or pot.rsplit("/", 1)[-1] in (".", ".."):
        return None
    vir = vir_iz_streznika(streznik, pot, "", mime)
    return None if vir is None else Vir(vir.base_url, vir.odtis, vir.zeton, pot, "", vir.mime, pot)


@dataclass
class _Pot:
    gostitelj: str
    vrata: int
    predpona: str       # "/d/" neposredno ali "/cast/d/" prek Huba (rele)
    odtis: str
    rele: bool
    velja_do: float


class LokalniPretok:
    """Lokalni streznik tokov (127.0.0.1). En na proces: `pretok()`."""

    def __init__(self, rele_za: Optional[Callable[[str], object]] = None,
                 potrdilo: Optional[Callable[[str, float], Tuple[str, str]]] = None) -> None:
        self._viri: Dict[str, Vir] = {}
        self._poti: Dict[tuple, _Pot] = {}
        self._releji: Dict[str, object] = {}
        #: Preverjen odtis Huba prek releja (id iz kljuca -> odtis): kljuc preverimo enkrat, nato pripnemo odtis.
        self._odtisi_releja: Dict[str, str] = {}
        self._zaklep = threading.Lock()
        self._rele_za = rele_za
        self._potrdilo = potrdilo or (lambda naslov, rok: link_tls.potrdilo_huba(naslov, timeout=rok))
        self._streznik: Optional[http.server.ThreadingHTTPServer] = None
        self.vrata = 0

    # -- streznik

    def zazeni(self) -> int:
        with self._zaklep:
            if self._streznik is None:
                s = _Streznik(("127.0.0.1", 0), _Obravnava)
                s.pretok = self  # type: ignore[attr-defined]
                self._streznik = s
                self.vrata = s.server_address[1]
                threading.Thread(target=s.serve_forever, name="safeer-pretok", daemon=True).start()
        return self.vrata

    def ustavi(self) -> None:
        with self._zaklep:
            s, self._streznik = self._streznik, None
            releji = list(self._releji.values())
            self._releji.clear()
            self._viri.clear()
            self._poti.clear()
        if s is not None:
            try:
                s.shutdown()
                s.server_close()
            except Exception:
                pass
        for r in releji:
            try:
                r.zapri()  # type: ignore[attr-defined]
            except Exception:
                pass
        self.vrata = 0

    def dodaj(self, vir: Vir) -> str:
        """Naslov http://127.0.0.1:<vrata>/m/<skrivnost> za lokalni predvajalnik."""
        vrata = self.zazeni()
        skrivnost = secrets.token_hex(16)
        with self._zaklep:
            self._viri[skrivnost] = vir
            while len(self._viri) > NAJVEC_VIROV:
                self._viri.pop(next(iter(self._viri)))
        return "http://127.0.0.1:%d/m/%s" % (vrata, skrivnost)

    def vir(self, skrivnost: str) -> Optional[Vir]:
        with self._zaklep:
            return self._viri.get(skrivnost)

    # -- pot do naprave

    def pot(self, vir: Vir, zdaj: Optional[float] = None, osvezi: bool = False) -> Optional[_Pot]:
        """Neposredno, ce je naprava dosegljiva; sicer prek releja (samo z znanim kljucem)."""
        zdaj = time.time() if zdaj is None else zdaj
        with self._zaklep:
            p = self._poti.get(_kljuc_poti(vir))
        if p is not None and p.velja_do > zdaj and not osvezi:
            return p
        u = urllib.parse.urlparse(vir.base_url)
        gostitelj, vrata = u.hostname or "", u.port or 443
        # Neposredno samo, ce na tem naslovu res odgovori ta naprava (pripet odtis): zunaj doma je na
        # istem zasebnem naslovu lahko cisto druga naprava.
        if gostitelj and self._potrdilo("wss://%s:%d/" % (gostitelj, vrata), NEPOSREDNO_CAKAJ_S)[0] == vir.odtis:
            p = _Pot(gostitelj, vrata, "/d/", vir.odtis, False, zdaj + POT_VELJA_S)
        else:
            p = self._pot_prek_releja(vir, zdaj)
        with self._zaklep:
            if p is None:
                self._poti.pop(_kljuc_poti(vir), None)
            else:
                self._poti[_kljuc_poti(vir)] = p
        return p

    def _pot_prek_releja(self, vir: Vir, zdaj: float) -> Optional[_Pot]:
        if not vir.kljuc or os.environ.get("SAFEER_GLOBAL_LINK", "1").strip() == "0":
            return None
        from core import link_rele
        try:
            cilj = link_rele.id_iz_kljuca(vir.kljuc)
        except Exception:
            return None
        with self._zaklep:
            rele = self._releji.get(cilj)
            if rele is None:
                rele = (self._rele_za or link_rele.LokalniRele)(cilj)
                self._releji[cilj] = rele
        vrata = int(getattr(rele, "vrata", 0) or 0)
        with self._zaklep:
            odtis = self._odtisi_releja.get(cilj, "")
        if not odtis:
            # Zaupanje: kljuc v potrdilu Huba = kljuc naprave iz kroga (odtis prek releja je lahko drug
            # kot odtis streznika datotek v LAN, kljuc pa je isti). Nato velja pripet odtis.
            odtis, kljuc = self._potrdilo("wss://127.0.0.1:%d/" % vrata, 15.0)
            if not odtis or not kljuc or kljuc != vir.kljuc:
                return None
            with self._zaklep:
                self._odtisi_releja[cilj] = odtis
        return _Pot("127.0.0.1", vrata, "/cast/d/", odtis, True, zdaj + POT_VELJA_S)

    def odpri(self, vir: Vir, metoda: str, obseg: str = "") -> Tuple[http.client.HTTPSConnection, http.client.HTTPResponse]:
        """Zahteva do naprave (neposredno ali prek releja); ob izpadu neposredne poti enkrat znova."""
        zadnja: Optional[BaseException] = None
        for poskus in range(2):
            p = self.pot(vir, osvezi=poskus > 0)
            if p is None:
                break
            povezava = link_tls._PripetaHttps(p.gostitelj, p.vrata, p.odtis, 20.0)
            glave = {"X-Safeer-Token": vir.zeton}
            if obseg:
                glave["Range"] = obseg
            try:
                if vir.pot and p.rele:
                    raise ConnectionError("tok torrenta samo v domacem omrezju")
                povezava.request(metoda, vir.pot or (p.predpona + urllib.parse.quote(vir.id_datoteke, safe="")), headers=glave)
                odgovor = povezava.getresponse()
                # Pot dela: dokler tok tece, je ne preverjamo znova (brez premora in brez dodatnih kanalov releja).
                p.velja_do = time.time() + POT_VELJA_S
                return povezava, odgovor
            except Exception as e:  # noqa: BLE001 - naprava je izginila ali odtis ni pravi
                zadnja = e
                povezava.close()
                with self._zaklep:
                    self._poti.pop(_kljuc_poti(vir), None)
                    if p.rele:
                        # Rele ali Hub se je zamenjal (nov odtis?): kljuc ob naslednjem klicu preverimo znova.
                        for cilj, o in list(self._odtisi_releja.items()):
                            if o == p.odtis:
                                self._odtisi_releja.pop(cilj, None)
        raise ConnectionError("naprava ni dosegljiva" + (" (%s)" % zadnja if zadnja else ""))


def _kljuc_poti(vir: Vir) -> tuple:
    """Odlocitev o poti velja samo za isto napravo (naslov + odtis + kljuc iz kroga), nikoli za tujo."""
    return (vir.base_url, vir.odtis, vir.kljuc)


class _Streznik(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _Obravnava(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "SafeerPretok"
    sys_version = ""

    def log_message(self, *_a) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        self._tok(False)

    def do_HEAD(self) -> None:  # noqa: N802
        self._tok(True)

    def _prazen(self, koda: int) -> None:
        self.send_response(koda)
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    def _tok(self, samo_glava: bool) -> None:
        pretok: LokalniPretok = self.server.pretok  # type: ignore[attr-defined]
        naslov = self.client_address[0] if self.client_address else ""
        if not naslov.startswith("127.") and naslov not in ("::1", "::ffff:127.0.0.1"):
            self._prazen(403)
            return
        pot = urllib.parse.urlparse(self.path).path
        vir = pretok.vir(pot[3:]) if pot.startswith("/m/") else None
        if vir is None:
            self._prazen(404)
            return
        obseg = self.headers.get("Range") or ""
        try:
            povezava, odgovor = pretok.odpri(vir, "HEAD" if samo_glava else "GET", obseg)
        except Exception:
            self._prazen(502)
            return
        try:
            self.send_response(odgovor.status)
            for ime in GLAVE_NAPREJ:
                vrednost = odgovor.getheader(ime)
                if vrednost:
                    if ime == "Content-Type" and vir.mime and vrednost.startswith("application/octet-stream"):
                        vrednost = vir.mime
                    self.send_header(ime, vrednost)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            if samo_glava:
                return
            while True:
                kos = odgovor.read(KOS)
                if not kos:
                    break
                self.wfile.write(kos)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass            # predvajalnik je previl ali zaprl; naprava dobi zaprtje
        finally:
            povezava.close()


_PRETOK: Optional[LokalniPretok] = None
_PRETOK_ZAKLEP = threading.Lock()


def pretok() -> LokalniPretok:
    global _PRETOK
    with _PRETOK_ZAKLEP:
        if _PRETOK is None:
            _PRETOK = LokalniPretok()
        return _PRETOK
