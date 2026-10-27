"""Naloga 131: debrid storitve (TorBox, Real-Debrid, AllDebrid) - odjemalci in izbira, kot Safeer OS za Android.

Pravila brez omrezja so v core/debrid_pravila.py. Kljuci so v nastavitvah Medijskega centra samo sifrirani (isti
sifrirnik kot gesla streznikov - sistemska zbirka skrivnosti); nikoli v dnevniku ali naslovu. Edina izjema je TorBox
requestdl, ki kljuc zahteva kot parameter `token`: tak naslov se uporabi samo za en klic in se ne zapise nikamor.
Klici so blokirajoci - samo z delovne niti.
"""

from __future__ import annotations

import email.utils
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import OrderedDict
from concurrent.futures import FIRST_COMPLETED, Future
from concurrent.futures import wait as futures_wait
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from . import debrid_pravila as P
from . import usenet_pravila as U

_log = logging.getLogger("safeer.debrid")


@dataclass
class Izid:
    """[url] povezava CDN za predvajanje ali [napaka] (P.NAPAKA_*) z [opis] storitve; [ponudnik] = storitev."""
    url: Optional[str] = None
    napaka: str = ""
    opis: str = ""
    ponudnik: str = ""


@dataclass
class Odgovor:
    """[datum] = glava Date odgovora (ura streznika, ms; 0 = je ni) - za »nas torrent« pri pospravljanju."""
    koda: int
    telo: str
    datum: int = 0

    @property
    def json(self):
        try:
            return json.loads(self.telo)
        except ValueError:
            return None

    @property
    def uspeh(self) -> bool:
        return 200 <= self.koda < 300


def v_ozadju(fn: Callable, *a, **k) -> Future:
    """[fn] na locenem demonu: izid prek Future. Ne ThreadPoolExecutor - njegove niti ob izhodu programa caka atexit (klic,
    ki je zamudil rok, bi do 30 s zadrzal zapiranje Safeer OS)."""
    f: Future = Future()

    def delo() -> None:
        if not f.set_running_or_notify_cancel():
            return
        try:
            f.set_result(fn(*a, **k))
        except BaseException as e:  # noqa: BLE001 - napaka gre klicatelju prek Future
            f.set_exception(e)

    threading.Thread(target=delo, name="safeer-debrid", daemon=True).start()
    return f


def _izid_do(f: Future, konec: float):
    """Izid [f] do monotonega casa [konec]; None ob roku ali napaki."""
    try:
        return f.result(timeout=max(0.01, konec - time.monotonic()))
    except Exception:  # noqa: BLE001 - kar ne odgovori v roku, ne steje
        return None


class Preklicano(Exception):
    """Poskus je preklican (rok vzporednega kroga je potekel ali nov poskus): ne ustvari nicesar vec v racunu."""


def preveri_preklic(preklic: Optional[threading.Event]) -> None:
    """Grokov pregled 25. 10. 2026 (kot Android Debrid.preveriPreklic): pred vsakim klicem, ki v uporabnikovem racunu kaj
    ustvari (addMagnet, selectFiles, magnet/upload, createtorrent, createusenetdownload, odklep). Blokirajoc klic HTTP
    preklica ne vidi; nit, ki je zamudila rok, bi sicer po odgovoru nadaljevala in pustila torrent v racunu."""
    if preklic is not None and preklic.is_set():
        raise Preklicano()


def _datum_ms(glave) -> int:
    try:
        d = email.utils.parsedate_to_datetime(str(glave.get("Date") or ""))
        return int(d.timestamp() * 1000) if d is not None else 0
    except (TypeError, ValueError, IndexError, OverflowError):
        return 0


def _beri_omejeno(o, meja: int = P.NAJVEC_ODGOVORA) -> bytes:
    """Najvec [meja] bajtov; vecji odgovor je napaka (ne odrezemo ga - odrezan JSON bi bil napacen)."""
    try:
        dolzina = int(o.headers.get("Content-Length") or -1) if getattr(o, "headers", None) is not None else -1
    except ValueError:
        dolzina = -1
    if dolzina > meja:
        raise OSError("odgovor prevelik")
    podatki = o.read(meja + 1) or b""
    if len(podatki) > meja:
        raise OSError("odgovor prevelik")
    return podatki


class _BrezPreusmeritve(urllib.request.HTTPRedirectHandler):
    """Zahteva s kljucem (v glavi ali v naslovu) ne sledi preusmeritvi (AGENTS.md: omrezje s kljucem). urllib.urlopen
    ob 3xx kopira glavo Authorization tudi v zahtevo drugemu gostitelju (izmerjeno 25. 10. 2026, Python 3.12.3, dva
    lokalna streznika): 302 storitve ali vmesnega posrednika bi odnesel kljuc. Odgovor 3xx je zato napaka storitve."""

    def redirect_request(self, *_a, **_k):
        return None


def _odpri_s_kljucem(zahteva: urllib.request.Request, rok: float):
    """urlopen brez sledenja preusmeritvam: 3xx pride kot urllib.error.HTTPError s kodo odgovora."""
    return urllib.request.build_opener(_BrezPreusmeritve()).open(zahteva, timeout=rok)  # nosec B310 - naslovi storitev


class _SkokNzb(urllib.request.HTTPRedirectHandler):
    """Prenos NZB (kljuc indeksatorja v naslovu) sledi preusmeritvi samo, ce skok dovoli U.dovoljen_skok - Android
    (Usenet.nzb) preusmeritvam NZB sledi, zato jih ne zavrnemo vseh; nikoli s https na http in ne na tuj http."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not U.dovoljen_skok(req.full_url, newurl):
            _log.info("usenet nzb: preusmeritev zavrnjena")
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def klic(naslov: str, kljuc: Optional[str], metoda: str = "GET", obrazec: Optional[list] = None,
         rok: float = 20.0, telo: Optional[tuple] = None) -> Odgovor:
    """Klic s kljucem v glavi (ali, samo pri requestdl, v naslovu); [obrazec] gre kot application/x-www-form-urlencoded,
    [telo] je (bajti, Content-Type) - npr. multipart z NZB za Usenet. Odgovor najvec P.NAJVEC_ODGOVORA bajtov (vecji je
    napaka). Preusmeritvi ne sledi (_BrezPreusmeritve): 3xx je Odgovor s to kodo, kljuc ne gre drugam."""
    glave = {"Accept": "application/json", "User-Agent": "SafeerOS/1.0"}
    if kljuc:
        glave["Authorization"] = P.glava_avtorizacije(kljuc)
    podatki = None
    if obrazec is not None:
        podatki = urllib.parse.urlencode(obrazec).encode("utf-8")
        glave["Content-Type"] = "application/x-www-form-urlencoded"
    elif telo is not None:
        podatki, glave["Content-Type"] = telo[0], telo[1]
    zahteva = urllib.request.Request(naslov, data=podatki, headers=glave, method=metoda)
    try:
        with _odpri_s_kljucem(zahteva, rok) as o:
            return Odgovor(o.status, _beri_omejeno(o).decode("utf-8", "replace"), _datum_ms(o.headers))
    except urllib.error.HTTPError as e:
        telo_n = _beri_omejeno(e) if e.fp is not None else b""
        return Odgovor(e.code, telo_n.decode("utf-8", "replace"), _datum_ms(e.headers) if e.headers is not None else 0)


# ---------------------------------------------------------------------- TorBox

def _tb_napaka(o: Odgovor) -> Izid:
    j = o.json if isinstance(o.json, dict) else {}
    koda = j.get("error") if j.get("error") not in (None, "null") else None
    return Izid(napaka=P.torbox_vrsta_napake(o.koda, koda), opis=str(j.get("detail") or "")[:300], ponudnik=P.TORBOX)


def _tb_uspeh(o: Odgovor) -> bool:
    j = o.json
    return o.uspeh and isinstance(j, dict) and j.get("success") is True


def _tb_datoteke(a) -> list:
    return [P.Datoteka(int(d.get("id") or 0), str(d.get("short_name") or d.get("name") or ""), int(d.get("size") or 0),
                       str(d.get("mimetype") or "")) for d in (a or []) if isinstance(d, dict)]


def torbox_predpomnjeni(kljuc: str, hashi: Sequence[str], rok: float = 4.0,
                        ob_napaki: Optional[Callable[[str], None]] = None) -> set:
    """Kateri hashi so pri TorBoxu ze pripravljeni: en klic checkcached (do 100), nic ne doda v racun. Ob napaki prazno;
    [ob_napaki] dobi vrsto napake storitve (Debrid.ob_izidu: zavrnjen kljuc ze ob preverbi ⚡ - kot Android)."""
    h = P.hashi_za_preverbo(hashi)
    if not h:
        return set()
    try:
        o = klic(P.torbox_naslov_predpomnjenih(h), kljuc, rok=rok)
        if not _tb_uspeh(o) and ob_napaki is not None:
            _javi(lambda n, _u: ob_napaki(n), _tb_napaka(o).napaka, False)     # napaka zapisa stanja ne podre ⚡
        data = (o.json or {}).get("data") if _tb_uspeh(o) else None
        izid = P.predpomnjeni(data.keys() if isinstance(data, dict) else (), h)
        _log.info("checkcached: %d od %d pripravljenih", len(izid), len(h))
        return izid
    except Exception as e:  # noqa: BLE001 - brez oznake ⚡, predvajanje dela naprej
        _log.warning("checkcached: %s", type(e).__name__)
        return set()


def torbox_tok(kljuc: str, hash_: str, indeks: Optional[int], magnet: str, samo_predpomnjeno: bool,
               casi_novih: list, cakaj: Callable[[float], None] = time.sleep,
               preklic: Optional[threading.Event] = None) -> Izid:
    """checkcached -> (createtorrent) -> requestdl. Nepredpomnjen: meja 60/uro ([casi_novih] se dopolni) in cakanje do 3 min.
    Preklican poskus ([preklic]) torrenta ne doda in ga ne steje v mejo."""
    try:
        pred = klic(P.TORBOX_OSNOVA + "/checkcached?hash=%s&format=object&list_files=true" % hash_, kljuc)
        if not _tb_uspeh(pred):
            return _tb_napaka(pred)
        vnos = ((pred.json or {}).get("data") or {}).get(hash_) if isinstance((pred.json or {}).get("data"), dict) else None
        predpomnjen = vnos is not None
        if not predpomnjen and samo_predpomnjeno:
            return Izid(napaka=P.NAPAKA_NI_PREDPOMNJENO, ponudnik=P.TORBOX)
        preveri_preklic(preklic)
        if not predpomnjen:
            zdaj = time.time()
            if not P.meja_novih_dovoli(casi_novih, zdaj):
                return Izid(napaka=P.NAPAKA_MEJA, ponudnik=P.TORBOX)
            casi_novih.append(zdaj)
        _log.info("createtorrent %s… predpomnjen=%s", hash_[:8], predpomnjen)
        ust = klic(P.TORBOX_OSNOVA + "/createtorrent", kljuc, "POST", [("magnet", magnet), ("allow_zip", "false")])
        tid = int((((ust.json or {}).get("data") or {}) if isinstance((ust.json or {}).get("data"), dict) else {}).get("torrent_id") or -1)
        if not _tb_uspeh(ust) and (ust.json or {}).get("error") == "DUPLICATE_ITEM":
            vsi = klic(P.TORBOX_OSNOVA + "/mylist?bypass_cache=true", kljuc)
            tid = next((int(t.get("id")) for t in ((vsi.json or {}).get("data") or [])
                        if isinstance(t, dict) and str(t.get("hash") or "").lower() == hash_), -1)
        elif not _tb_uspeh(ust):
            return _tb_napaka(ust)
        if tid < 0:
            return _tb_napaka(ust)
        datoteke = _tb_datoteke((vnos or {}).get("files") if isinstance(vnos, dict) else None)
        if not predpomnjen or not datoteke:
            cakano = 0.0
            while True:
                o = klic(P.TORBOX_OSNOVA + "/mylist?id=%d&bypass_cache=true" % tid, kljuc)
                if not _tb_uspeh(o):
                    return _tb_napaka(o)
                t = (o.json or {}).get("data") or {}
                datoteke = _tb_datoteke(t.get("files"))
                if P.torbox_pripravljen(str(t.get("download_state") or ""), bool(t.get("download_finished")),
                                        bool(t.get("download_present"))) and datoteke:
                    break
                if cakano >= P.CAKAJ_NOVEGA_S:
                    return Izid(napaka=P.NAPAKA_PRENASA, ponudnik=P.TORBOX)
                preveri_preklic(preklic)
                cakaj(P.CAKAJ_KORAK_S)
                cakano += P.CAKAJ_KORAK_S
        d = P.izberi_datoteko(datoteke, indeks)
        if d is None:
            return Izid(napaka=P.NAPAKA_NI_DATOTEKE, ponudnik=P.TORBOX)
        # requestdl: kljuc je v naslovu (token) - ta naslov se ne zapise nikamor.
        dl = klic(P.TORBOX_OSNOVA + "/requestdl?" + urllib.parse.urlencode(
            {"token": kljuc, "torrent_id": tid, "file_id": d.id}), None)
        url = str((dl.json or {}).get("data") or "")
        if not _tb_uspeh(dl) or not url.startswith("https://"):
            return _tb_napaka(dl)
        _log.info("TorBox: tok pripravljen")
        return Izid(url=url, ponudnik=P.TORBOX)
    except Preklicano:
        _log.info("TorBox: preklicano")
        return Izid(napaka=P.NAPAKA_STREZNIK, ponudnik=P.TORBOX)
    except Exception as e:  # noqa: BLE001
        _log.warning("TorBox: %s", type(e).__name__)
        return Izid(napaka=P.NAPAKA_STREZNIK, ponudnik=P.TORBOX)


# ---------------------------------------------------------------------- Real-Debrid

#: Kratki roki za pospravljanje po neuspehu (kot Android POSPRAVI_*): okno z napako ne caka 20 s na brisanje.
POSPRAVI_ROK_S = 5.0


class _Cakani:
    """Torrenti (storitev:id), na katere uporabnik na tem racunalniku caka (»samo takoj« izklopljen): poskus »samo takoj«
    (tudi zapuscena nit preklicanega poskusa) jih ne izbrise. Samo v pomnilniku procesa, najvec 500 vnosov."""

    def __init__(self) -> None:
        self._zaklep = threading.Lock()
        self._vnosi: set = set()

    def oznaci(self, p: str, ident: str) -> None:
        with self._zaklep:
            if len(self._vnosi) < 500:
                self._vnosi.add("%s:%s" % (p, ident))

    def je(self, p: str, ident: str) -> bool:
        with self._zaklep:
            return "%s:%s" % (p, ident) in self._vnosi


CAKANI = _Cakani()


def _rd_napaka(o: Odgovor) -> Izid:
    j = o.json if isinstance(o.json, dict) else {}
    koda = j.get("error_code") if isinstance(j.get("error_code"), int) else None
    return Izid(napaka=P.rd_vrsta_napake_uporabe(o.koda, koda), opis=str(j.get("error") or "")[:200], ponudnik=P.REAL_DEBRID)


def _rd_izbrisi(kljuc: str, tid: str, dodano_ob: Optional[int], samo_predpomnjeno: bool) -> None:
    """Pospravi torrent [tid], ki ga je dodal ta poskus ([dodano_ob] = glava Date odgovora addMagnet, ura streznika).
    Ne izbrisemo torrenta, ki je bil v racunu ze prej (addMagnet za isti hash morda vrne obstojeci id): samo, ce »added«
    iz torrents/info ni starejsi od [dodano_ob] (P.dodal_smo_mi) in ga pri »samo takoj« ne caka drug poskus. Neznano = ne."""
    if samo_predpomnjeno and CAKANI.je(P.REAL_DEBRID, tid):
        _log.info("Real-Debrid: torrent ni izbrisan (nanj caka drug poskus)")
        return
    try:
        info = klic(P.RD_OSNOVA + "/torrents/info/" + tid, kljuc, rok=POSPRAVI_ROK_S)
        dodano = P.rd_dodano_ms((info.json or {}).get("added") if isinstance(info.json, dict) else None)
        if not P.dodal_smo_mi(dodano, dodano_ob):
            _log.info("Real-Debrid: torrent ni izbrisan (ni dokaza, da ga je dodal ta poskus)")
            return
        klic(P.RD_OSNOVA + "/torrents/delete/" + tid, kljuc, "DELETE", rok=POSPRAVI_ROK_S)
    except Exception as e:  # noqa: BLE001 - pospravljanje ne sme podreti izida
        _log.info("Real-Debrid: pospravljanje %s", type(e).__name__)


def rd_tok(kljuc: str, magnet: str, indeks: Optional[int], samo_predpomnjeno: bool,
           cakaj: Callable[[float], None] = time.sleep, preklic: Optional[threading.Event] = None) -> Izid:
    """addMagnet -> info -> selectFiles -> info (»downloaded«) -> unrestrict/link. Ni takoj pripravljen in »samo
    predpomnjeno«: torrent, ki ga je dodal ta poskus, izbrisemo v `finally` - tudi ob napaki omrezja, roku, preklicu in
    praznih povezavah (Grokov pregled 25. 10. 2026; prej samo na dveh mestih, mrtev prenos je ostal v racunu). Pri
    cakanju ostane (prenasa se naprej, naslednji poskus je takoj); pokvarjen se izbrise."""
    stanje = {"tid": "", "dodano_ob": None, "pripravljen": False}

    def pospravi() -> None:
        if stanje["tid"]:
            _rd_izbrisi(kljuc, stanje["tid"], stanje["dodano_ob"], samo_predpomnjeno)
            stanje["tid"] = ""

    try:
        preveri_preklic(preklic)
        dodaj = klic(P.RD_OSNOVA + "/torrents/addMagnet", kljuc, "POST", [("magnet", magnet)])
        if not dodaj.uspeh:
            return _rd_napaka(dodaj)
        tid = str((dodaj.json or {}).get("id") or "") if isinstance(dodaj.json, dict) else ""
        if not tid:
            return _rd_napaka(dodaj)
        stanje.update(tid=tid, dodano_ob=dodaj.datum or None)
        if not samo_predpomnjeno:
            CAKANI.oznaci(P.REAL_DEBRID, tid)
        info = klic(P.RD_OSNOVA + "/torrents/info/" + tid, kljuc)
        for _ in range(10):
            j = info.json or {}
            if not info.uspeh or (j.get("files") or []) or P.rd_koncna_napaka(str(j.get("status") or "")):
                break
            preveri_preklic(preklic)
            cakaj(1.0)
            info = klic(P.RD_OSNOVA + "/torrents/info/" + tid, kljuc)
        if not info.uspeh:
            pospravi()
            return _rd_napaka(info)
        datoteke = [P.Datoteka(int(f.get("id") or 0), str(f.get("path") or "").rsplit("/", 1)[-1], int(f.get("bytes") or 0))
                    for f in ((info.json or {}).get("files") or []) if isinstance(f, dict)]
        d = P.izberi_datoteko(datoteke, indeks)
        if d is None:
            pospravi()
            return Izid(napaka=P.NAPAKA_NI_DATOTEKE, ponudnik=P.REAL_DEBRID)
        preveri_preklic(preklic)
        izberi = klic(P.RD_OSNOVA + "/torrents/selectFiles/" + tid, kljuc, "POST", [("files", str(d.id))])
        if not izberi.uspeh:
            pospravi()
            return _rd_napaka(izberi)
        rok = 4.0 if samo_predpomnjeno else P.CAKAJ_NOVEGA_S
        korak = 1.0 if samo_predpomnjeno else P.CAKAJ_KORAK_S
        cakano = 0.0
        info = klic(P.RD_OSNOVA + "/torrents/info/" + tid, kljuc)
        while info.uspeh and not P.rd_pripravljen(str((info.json or {}).get("status") or "")) and cakano < rok:
            if P.rd_koncna_napaka(str((info.json or {}).get("status") or "")):
                break
            preveri_preklic(preklic)
            cakaj(korak)
            cakano += korak
            info = klic(P.RD_OSNOVA + "/torrents/info/" + tid, kljuc)
        status = str((info.json or {}).get("status") or "")
        if not P.rd_pripravljen(status):
            # Pri cakanju ostane v racunu (prenasa se naprej); izbrisemo nepredpomnjenega (»samo takoj«) in pokvarjenega.
            if samo_predpomnjeno or P.rd_koncna_napaka(status):
                pospravi()
            napaka = (P.NAPAKA_NI_DATOTEKE if P.rd_koncna_napaka(status)
                      else P.NAPAKA_NI_PREDPOMNJENO if samo_predpomnjeno else P.NAPAKA_PRENASA)
            return Izid(napaka=napaka, ponudnik=P.REAL_DEBRID)
        povezava = next(iter((info.json or {}).get("links") or []), "")
        if not povezava:
            return Izid(napaka=P.NAPAKA_NI_DATOTEKE, ponudnik=P.REAL_DEBRID)
        # Pripravljen (»downloaded« s povezavo): ostane v racunu - predpomnjen ne zaseda aktivnega mesta.
        stanje["pripravljen"] = True
        preveri_preklic(preklic)
        odklep = klic(P.RD_OSNOVA + "/unrestrict/link", kljuc, "POST", [("link", povezava)])
        url = str((odklep.json or {}).get("download") or "") if isinstance(odklep.json, dict) else ""
        if not odklep.uspeh or not url.startswith("https://"):
            return _rd_napaka(odklep)
        _log.info("Real-Debrid: tok pripravljen")
        return Izid(url=url, ponudnik=P.REAL_DEBRID)
    except Preklicano:
        _log.info("Real-Debrid: preklicano")
        return Izid(napaka=P.NAPAKA_STREZNIK, ponudnik=P.REAL_DEBRID)
    except Exception as e:  # noqa: BLE001
        _log.warning("Real-Debrid: %s", type(e).__name__)
        return Izid(napaka=P.NAPAKA_STREZNIK, ponudnik=P.REAL_DEBRID)
    finally:
        # »Samo takoj«: torrent, ki ni pripravljen, ne ostane v racunu ne glede na izhod (preklic, napaka, rok).
        if samo_predpomnjeno and not stanje["pripravljen"]:
            pospravi()


# ---------------------------------------------------------------------- AllDebrid

def _ad_uspeh(o: Odgovor) -> bool:
    return o.uspeh and isinstance(o.json, dict) and o.json.get("status") == "success"


def _ad_napaka(o: Odgovor, e: Optional[dict] = None) -> Izid:
    e = e if e is not None else ((o.json or {}).get("error") if isinstance(o.json, dict) else None) or {}
    return Izid(napaka=P.ad_vrsta_napake(o.koda, e.get("code")), opis=str(e.get("message") or "")[:200], ponudnik=P.ALLDEBRID)


def _ad_razvij(a, izid: list) -> None:
    for n in a or []:
        if not isinstance(n, dict):
            continue
        if isinstance(n.get("e"), list):
            _ad_razvij(n["e"], izid)
        elif n.get("l"):
            izid.append((P.Datoteka(len(izid), str(n.get("n") or ""), int(n.get("s") or 0)), str(n["l"])))


AD_STANJE = "https://api.alldebrid.com/v4.1/magnet/status"


def _ad_magnet_stanja(st: Odgovor) -> dict:
    d = (st.json or {}).get("data") if isinstance(st.json, dict) else None
    d = d if isinstance(d, dict) else {}
    mm = d.get("magnets") if isinstance(d.get("magnets"), dict) else next(iter(d.get("magnets") or []), {})
    return mm if isinstance(mm, dict) else {}


def _ad_izbrisi(kljuc: str, mid: int, dodano_ob: Optional[int], samo_predpomnjeno: bool) -> None:
    """Pospravi magnet [mid], ki ga je dodal ta poskus (kot _rd_izbrisi): samo, ce »uploadDate« (magnet/status) ni
    starejsi od glave Date odgovora magnet/upload in ga pri »samo takoj« ne caka drug poskus. Neznano = ne izbrisemo."""
    if samo_predpomnjeno and CAKANI.je(P.ALLDEBRID, str(mid)):
        _log.info("AllDebrid: magnet ni izbrisan (nanj caka drug poskus)")
        return
    try:
        st = klic(AD_STANJE, kljuc, "POST", [("id", str(mid))], rok=POSPRAVI_ROK_S)
        if not P.dodal_smo_mi(P.ad_dodano_ms(_ad_magnet_stanja(st).get("uploadDate")), dodano_ob):
            _log.info("AllDebrid: magnet ni izbrisan (ni dokaza, da ga je dodal ta poskus)")
            return
        klic(P.AD_OSNOVA + "/magnet/delete", kljuc, "POST", [("id", str(mid))], rok=POSPRAVI_ROK_S)
    except Exception as e:  # noqa: BLE001 - pospravljanje ne sme podreti izida
        _log.info("AllDebrid: pospravljanje %s", type(e).__name__)


def ad_tok(kljuc: str, hash_: str, indeks: Optional[int], samo_predpomnjeno: bool,
           cakaj: Callable[[float], None] = time.sleep, preklic: Optional[threading.Event] = None) -> Izid:
    """magnet/upload (`ready`) -> magnet/files -> link/unlock (link ali delayed). Ni pripravljen in »samo
    predpomnjeno«: magnet, ki ga je dodal ta poskus, izbrisemo v `finally` (tudi ob napaki in preklicu)."""
    stanje = {"mid": -1, "dodano_ob": None, "pripravljen": False}

    def pospravi() -> None:
        if stanje["mid"] >= 0:
            _ad_izbrisi(kljuc, stanje["mid"], stanje["dodano_ob"], samo_predpomnjeno)
            stanje["mid"] = -1

    try:
        preveri_preklic(preklic)
        nalozi = klic(P.AD_OSNOVA + "/magnet/upload", kljuc, "POST", [("magnets[]", hash_)])
        if not _ad_uspeh(nalozi):
            return _ad_napaka(nalozi)
        m = next(iter((((nalozi.json or {}).get("data") or {}).get("magnets") or [])), None)
        if not isinstance(m, dict):
            return _ad_napaka(nalozi)
        if isinstance(m.get("error"), dict):
            return _ad_napaka(nalozi, m["error"])
        mid = int(m.get("id") or -1)
        if mid < 0:
            return _ad_napaka(nalozi)
        stanje.update(mid=mid, dodano_ob=nalozi.datum or None)
        if not samo_predpomnjeno:
            CAKANI.oznaci(P.ALLDEBRID, str(mid))
        pripravljen = bool(m.get("ready"))
        if not pripravljen and samo_predpomnjeno:
            pospravi()
            return Izid(napaka=P.NAPAKA_NI_PREDPOMNJENO, ponudnik=P.ALLDEBRID)
        cakano = 0.0
        while not pripravljen and cakano <= P.CAKAJ_NOVEGA_S:
            preveri_preklic(preklic)
            cakaj(P.CAKAJ_KORAK_S)
            cakano += P.CAKAJ_KORAK_S
            st = klic(AD_STANJE, kljuc, "POST", [("id", str(mid))])
            if not _ad_uspeh(st):
                return _ad_napaka(st)
            koda = int(_ad_magnet_stanja(st).get("statusCode") or 0)
            if koda >= 5:
                pospravi()
                return Izid(napaka=P.NAPAKA_NI_DATOTEKE, ponudnik=P.ALLDEBRID)
            pripravljen = koda == 4
        if not pripravljen:
            return Izid(napaka=P.NAPAKA_PRENASA, ponudnik=P.ALLDEBRID)
        stanje["pripravljen"] = True
        dat = klic(P.AD_OSNOVA + "/magnet/files", kljuc, "POST", [("id[]", str(mid))])
        if not _ad_uspeh(dat):
            return _ad_napaka(dat)
        seznam: list = []
        _ad_razvij((next(iter(((dat.json or {}).get("data") or {}).get("magnets") or []), {}) or {}).get("files"), seznam)
        d = P.izberi_datoteko([s[0] for s in seznam], indeks)
        if d is None:
            return Izid(napaka=P.NAPAKA_NI_DATOTEKE, ponudnik=P.ALLDEBRID)
        preveri_preklic(preklic)
        odklep = klic(P.AD_OSNOVA + "/link/unlock", kljuc, "POST", [("link", seznam[d.id][1])])
        if not _ad_uspeh(odklep):
            return _ad_napaka(odklep)
        data = (odklep.json or {}).get("data") or {}
        url = str(data.get("link") or "")
        zamik = data.get("delayed")
        for _ in range(30):
            if url or not zamik:
                break
            preveri_preklic(preklic)
            cakaj(2.0)
            z = klic(P.AD_OSNOVA + "/link/delayed", kljuc, "POST", [("id", str(zamik))])
            if not _ad_uspeh(z):
                return _ad_napaka(z)
            zd = (z.json or {}).get("data") or {}
            if zd.get("status") == 2:
                url = str(zd.get("link") or "")
            elif zd.get("status") == 3:
                return Izid(napaka=P.NAPAKA_STREZNIK, ponudnik=P.ALLDEBRID)
        if not url.startswith("https://"):
            return Izid(napaka=P.NAPAKA_STREZNIK, ponudnik=P.ALLDEBRID)
        _log.info("AllDebrid: tok pripravljen")
        return Izid(url=url, ponudnik=P.ALLDEBRID)
    except Preklicano:
        _log.info("AllDebrid: preklicano")
        return Izid(napaka=P.NAPAKA_STREZNIK, ponudnik=P.ALLDEBRID)
    except Exception as e:  # noqa: BLE001
        _log.warning("AllDebrid: %s", type(e).__name__)
        return Izid(napaka=P.NAPAKA_STREZNIK, ponudnik=P.ALLDEBRID)
    finally:
        if samo_predpomnjeno and not stanje["pripravljen"]:
            pospravi()


# ---------------------------------------------------------------------- meritev

def izmeri(ponudnik: str, url: str) -> Optional[P.Meritev]:
    """Ping (cas do odgovora) in hitrost (do MERITEV_BAJTOV ali MERITEV_S, Range). Naslova ne zapisemo (vsebuje zeton)."""
    zacetek = time.monotonic()
    try:
        zahteva = urllib.request.Request(url, headers={"Range": "bytes=0-%d" % (P.MERITEV_BAJTOV - 1), "User-Agent": "SafeerOS/1.0"})
        with urllib.request.urlopen(zahteva, timeout=4) as o:
            if not 200 <= o.status < 300:
                return None
            odziv = time.monotonic()
            bajtov = 0
            while bajtov < P.MERITEV_BAJTOV and time.monotonic() - odziv < P.MERITEV_S:
                kos = o.read(64 * 1024)
                if not kos:
                    break
                bajtov += len(kos)
        return P.Meritev(ponudnik, int((odziv - zacetek) * 1000), bajtov, max(1, int((time.monotonic() - odziv) * 1000)))
    except Exception as e:  # noqa: BLE001
        _log.warning("meritev %s: %s", P.ime(ponudnik), type(e).__name__)
        return None


# ---------------------------------------------------------------------- preverba kljuca ob vnosu

def torbox_preveri(kljuc: str, rok: float = 8.0) -> tuple:
    """(P.PREVERBA_*, paket) - TorBox »user/me« s kljucem v glavi. Odgovor nosi e-naslov racuna: iz njega vzamemo samo
    paket; odgovora ne zapisemo nikamor. Brez povezave P.PREVERBA_NI_ODGOVORA."""
    try:
        o = klic(P.TORBOX_UPORABNIK, kljuc, rok=rok)
    except Exception as e:  # noqa: BLE001 - brez povezave kljuca ne zavrnemo
        _log.info("torbox preverba: %s", type(e).__name__)
        return P.PREVERBA_NI_ODGOVORA, None
    izid, paket = P.torbox_preverba(o.koda, o.json)
    _log.info("torbox preverba: HTTP %d, %s", o.koda, izid)
    return izid, paket


def _preveri_racun(ime: str, naslov: str, kljuc: str, pravilo: Callable[[int, object], str], rok: float) -> tuple:
    """(P.PREVERBA_*, None) za Real-Debrid ali AllDebrid »/user« (kljuc v glavi, nic ne doda v racun). Odgovor nosi
    uporabnisko ime in e-naslov: iz njega vzamemo SAMO izid, odgovora ne zapisemo nikamor."""
    try:
        o = klic(naslov, kljuc, rok=rok)
    except Exception as e:  # noqa: BLE001 - brez povezave kljuca ne zavrnemo
        _log.info("preverba %s: %s", ime, type(e).__name__)
        return P.PREVERBA_NI_ODGOVORA, None
    izid = pravilo(o.koda, o.json)
    _log.info("preverba %s: HTTP %d, %s", ime, o.koda, izid)
    return izid, None


def rd_preveri(kljuc: str, rok: float = 8.0) -> tuple:
    return _preveri_racun("Real-Debrid", P.RD_UPORABNIK, kljuc, P.rd_preverba, rok)


def ad_preveri(kljuc: str, rok: float = 8.0) -> tuple:
    return _preveri_racun("AllDebrid", P.AD_UPORABNIK, kljuc, P.ad_preverba, rok)


def preveri_kljuc(p: str, kljuc: str) -> tuple:
    """(P.PREVERBA_*, paket) pri storitvi [p] - blokirajoce (do 8 s), samo z delovne niti. Funkcije se poiscejo ob klicu
    (preizkusi jih zamenjajo)."""
    if p == P.TORBOX:
        return torbox_preveri(kljuc)
    return rd_preveri(kljuc) if p == P.REAL_DEBRID else ad_preveri(kljuc)


def indeksator_preveri(osn: str, kljuc: str, rok: float = 8.0) -> str:
    """P.PREVERBA_* za kljuc indeksatorja Newznab: eno iskanje z enim zadetkom (izmerjeno 25. 10. 2026 na nzbfinder.ws:
    napacen kljuc -> HTTP 401 in `<error code="100">`, t=caps kljuca ne preveri). Naslov s kljucem ne gre v dnevnik."""
    zahteva = urllib.request.Request(U.naslov_preverbe(osn, kljuc),
                                     headers={"Accept": "application/rss+xml, application/xml, text/xml",
                                              "User-Agent": "SafeerOS/1.0"})
    try:
        try:
            with _odpri_s_kljucem(zahteva, rok) as o:
                koda, telo = o.status, _beri_do(o, 64 * 1024)
        except urllib.error.HTTPError as e:
            koda, telo = e.code, _beri_do(e, 64 * 1024) if e.fp else b""
    except Exception as e:  # noqa: BLE001 - brez povezave kljuca ne zavrnemo
        _log.info("preverba indeksatorja: %s", type(e).__name__)
        return P.PREVERBA_NI_ODGOVORA
    izid = U.preverba_indeksatorja(koda, telo.decode("utf-8", "replace"))
    _log.info("preverba indeksatorja: HTTP %d, %s", koda, izid)
    return izid


# ---------------------------------------------------------------------- Usenet (indeksator Newznab + TorBox)

def _beri_do(o, najvec: int) -> bytes:
    deli, skupaj = [], 0
    while skupaj < najvec:
        kos = o.read(min(64 * 1024, najvec - skupaj))
        if not kos:
            break
        deli.append(kos)
        skupaj += len(kos)
    return b"".join(deli)


def _javi(ob_izidu: Optional[Callable[[str, bool], None]], napaka: str, uspeh: bool) -> None:
    """Izid klica s kljucem za stanje kljuca (Debrid.ob_izidu); napaka pri zapisu stanja ne podre klica."""
    if ob_izidu is None:
        return
    try:
        ob_izidu(napaka, uspeh)
    except Exception as e:  # noqa: BLE001
        _log.info("stanje kljuca: %s", type(e).__name__)


def usenet_isci(osn: str, kljuc_ix: str, ident: str, rok: float = 8.0,
                ob_izidu: Optional[Callable[[str, bool], None]] = None) -> list:
    """Zadetki indeksatorja za id Stremio (film tt… ali epizoda tt…:S:E); ob napaki prazno. Naslov (s kljucem) ne gre v
    dnevnik in ne sledi preusmeritvi (kot preverba ob vnosu)."""
    naslov = U.naslov_iskanja(osn, kljuc_ix, ident)
    if not naslov:
        return []
    try:
        zahteva = urllib.request.Request(naslov, headers={"Accept": "application/rss+xml, application/xml, text/xml",
                                                          "User-Agent": "SafeerOS/1.0"})
        try:
            with _odpri_s_kljucem(zahteva, rok) as o:
                koda, telo = o.status, _beri_do(o, U.NAJVEC_ODGOVORA_BAJTOV)
        except urllib.error.HTTPError as e:
            koda, telo = e.code, _beri_do(e, 64 * 1024) if e.fp else b""
        besedilo = telo.decode("utf-8", "replace")
        # Stanje kljuca po istem pravilu kot preverba ob vnosu: RSS potrdi kljuc, 401 ali Newznab 100-102 ga zavrne
        # (403 brez napake je lahko Cloudflare, stran HTML ni potrditev).
        izid = U.preverba_indeksatorja(koda, besedilo)
        _javi(ob_izidu, {P.PREVERBA_NEVELJAVEN: P.NAPAKA_KLJUC, P.PREVERBA_ZAKLENJEN: P.NAPAKA_ZAKLENJEN}.get(izid, ""),
              izid == P.PREVERBA_VELJAVEN)
        if not 200 <= koda < 300:
            _log.info("usenet iskanje: HTTP %d", koda)
            return []
        n = U.napaka(besedilo)
        if n:
            _log.info("usenet iskanje: napaka indeksatorja (%s)", n)
            return []
        z = U.zadetki(besedilo, osn)
        _log.info("usenet iskanje: %d zadetkov", len(z))
        return z
    except Exception as e:  # noqa: BLE001 - brez Useneta, ostali viri delajo naprej
        _log.warning("usenet iskanje: %s", type(e).__name__)
        return []


def _isti_gostitelj(a: str, b: str) -> bool:
    try:
        return (urllib.parse.urlsplit(a).hostname or "") == (urllib.parse.urlsplit(b).hostname or "")
    except ValueError:
        return False


def usenet_nzb(povezava: str, rok: float = 30.0) -> tuple:
    """NZB z indeksatorja: (bajti, "") ali (None, napaka). Povezava vsebuje kljuc - ne gre v dnevnik; vsak skok
    preusmeritve preveri U.dovoljen_skok (_SkokNzb)."""
    try:
        zahteva = urllib.request.Request(povezava, headers={"User-Agent": "SafeerOS/1.0"})
        try:
            with urllib.request.build_opener(_SkokNzb()).open(zahteva, timeout=rok) as o:  # nosec B310 - skoki preverjeni
                koda, telo, koncni = o.status, _beri_do(o, U.NAJVEC_NZB_BAJTOV + 1), o.geturl()
        except urllib.error.HTTPError as e:
            koda, telo, koncni = e.code, _beri_do(e, 64 * 1024) if e.fp else b"", e.geturl()
        if len(telo) > U.NAJVEC_NZB_BAJTOV:
            return None, U.NAPAKA_INDEKSATOR
        zacetek = telo[:4096].decode("utf-8", "replace")
        if 200 <= koda < 300 and U.je_nzb(zacetek):
            return telo, ""
        # 401/403 brez napake Newznab je lahko Cloudflare ali posrednik (U.preverba_indeksatorja) - ni zavrnjen kljuc.
        n = U.napaka(zacetek) or (P.NAPAKA_MEJA if koda == 429 else U.NAPAKA_INDEKSATOR)
        if n in (P.NAPAKA_KLJUC, P.NAPAKA_ZAKLENJEN) and not _isti_gostitelj(povezava, koncni or povezava):
            # Grokov pregled 36, D2: 401 drugega gostitelja po preusmeritvi (CDN, potekel podpisan naslov) ni odgovor
            # indeksatorja o kljucu - kljuca indeksatorja ne oznacimo »ne velja«.
            n = U.NAPAKA_INDEKSATOR
        _log.info("usenet nzb: HTTP %d, napaka %s", koda, n)
        return None, n
    except Exception as e:  # noqa: BLE001
        _log.warning("usenet nzb: %s", type(e).__name__)
        return None, U.NAPAKA_INDEKSATOR


def torbox_usenet(kljuc: str, nzb: bytes, ime_izdaje: str, indeks: Optional[int], samo_takoj: bool,
                  cakaj: Callable[[float], None] = time.sleep, rok_cakanja: float = U.CAKAJ_PRENOSA_S,
                  preklic: Optional[threading.Event] = None) -> Izid:
    """NZB -> TorBox createusenetdownload -> (cakanje na prenos) -> requestdl. Izid nosi ponudnika TorBox. Preklican
    poskus ([preklic], npr. zamujen rok preverbe »Usenet pripravljen«) prenosa ne doda."""
    try:
        preveri_preklic(preklic)
        meja = "safeer" + uuid.uuid4().hex
        ime = " ".join(str(ime_izdaje or "safeer").split())[:120] or "safeer"
        obrazec = U.vecdelni_obrazec([("name", ime), ("add_only_if_cached", "true" if samo_takoj else "false"),
                                      ("post_processing", "-1")], ("file", "safeer.nzb", nzb), meja)
        ust = klic(U.OSNOVA_TORBOX + "/createusenetdownload", kljuc, "POST", rok=60.0,
                   telo=(obrazec, "multipart/form-data; boundary=" + meja))
        j = ust.json if isinstance(ust.json, dict) else {}
        data = j.get("data") if isinstance(j.get("data"), dict) else {}
        uid = int(data.get("usenetdownload_id") or -1)
        if not _tb_uspeh(ust):
            if j.get("error") == "DUPLICATE_ITEM":
                if uid < 0:
                    vsi = klic(U.OSNOVA_TORBOX + "/mylist?bypass_cache=true", kljuc)
                    uid = next((int(t.get("id")) for t in ((vsi.json or {}).get("data") or [])
                                if isinstance(t, dict) and str(t.get("name") or "") == ime), -1)
            else:
                n = _tb_napaka(ust)
                if U.ni_predpomnjeno(samo_takoj, n.napaka):
                    return Izid(napaka=P.NAPAKA_NI_PREDPOMNJENO, ponudnik=P.TORBOX)
                return n
        if uid < 0:
            return _tb_napaka(ust)
        _log.info("usenet: prenos %d samo_takoj=%s", uid, samo_takoj)
        cakano, datoteke = 0.0, []
        while True:
            o = klic(U.naslov_seznam(uid), kljuc)
            if not _tb_uspeh(o):
                return _tb_napaka(o)
            t = (o.json or {}).get("data") or {}
            if not isinstance(t, dict):
                return Izid(napaka=P.NAPAKA_STREZNIK, ponudnik=P.TORBOX)
            datoteke = _tb_datoteke(t.get("files"))
            if P.torbox_pripravljen(str(t.get("download_state") or ""), bool(t.get("download_finished")),
                                    bool(t.get("download_present"))) and datoteke:
                break
            if str(t.get("download_state") or "").lower().startswith("failed"):
                return Izid(napaka=P.NAPAKA_NI_DATOTEKE, ponudnik=P.TORBOX)
            if cakano >= rok_cakanja:
                return Izid(napaka=P.NAPAKA_PRENASA, ponudnik=P.TORBOX)
            preveri_preklic(preklic)
            cakaj(P.CAKAJ_KORAK_S)
            cakano += P.CAKAJ_KORAK_S
        d = P.izberi_datoteko(datoteke, indeks)
        if d is None:
            return Izid(napaka=P.NAPAKA_NI_DATOTEKE, ponudnik=P.TORBOX)
        dl = klic(U.naslov_prenosa(kljuc, uid, d.id), None)      # kljuc v naslovu (token) - ne zapisemo
        url = str((dl.json or {}).get("data") or "")
        if not _tb_uspeh(dl) or not url.startswith("https://"):
            return _tb_napaka(dl)
        _log.info("usenet: tok pripravljen")
        return Izid(url=url, ponudnik=P.TORBOX)
    except Preklicano:
        _log.info("usenet TorBox: preklicano")
        return Izid(napaka=P.NAPAKA_STREZNIK, ponudnik=P.TORBOX)
    except Exception as e:  # noqa: BLE001
        _log.warning("usenet TorBox: %s", type(e).__name__)
        return Izid(napaka=P.NAPAKA_STREZNIK, ponudnik=P.TORBOX)


# ---------------------------------------------------------------------- storitev za Medijski center

#: Naloga 114: lasten pogon Usenet z uporabnikovim ponudnikom NNTP (core/usenet_vezava.py) - Izid.ponudnik.
LASTNI_USENET = "nntp"
NAPAKA_LASTNI_POGON = "lastni_pogon"


class Debrid:
    """Kljuci, nastavitve in izbira storitve. [beri]/[pisi] berejo in zapisejo razdelek »debrid« nastavitev Medijskega
    centra; [sifriraj]/[desifriraj] sta sifrirnik gesel streznikov (sistemska zbirka skrivnosti)."""

    def __init__(self, beri: Callable[[], dict], pisi: Callable[[dict], None],
                 sifriraj: Callable[[str], str], desifriraj: Callable[[str], str],
                 pozabi: Optional[Callable[[str], None]] = None):
        self._beri, self._pisi = beri, pisi
        self._sifriraj, self._desifriraj = sifriraj, desifriraj
        # Odstranjen ali zamenjan kljuc izbrisemo tudi iz zbirke skrivnosti (ne samo oznako iz nastavitev).
        self._pozabi_skrivnost = pozabi or (lambda _enc: None)
        self._zaklep = threading.Lock()
        self._kljuci: dict = {}          # predpomnilnik desifriranih kljucev (samo v pomnilniku)
        self._povezave_nzb: dict = {}    # id toka »usenet:…« -> povezava NZB s kljucem (samo v pomnilniku)
        # Naloga 114: lasten pogon (usenet_vezava.Vezava: na_voljo(), predvajaj(nzb, ime)); None = samo TorBox.
        # Nastavi ga os_katalog na Linuxu; Windows in preizkusi brez njega delajo kot prej.
        self.lastni_usenet = None
        # Zadnji prenesen NZB (id toka -> (cas, bajti)): preverba »pripravljen« in nato poskus s cakanjem za isto izdajo
        # ne preneseta NZB dvakrat (indeksatorji stejejo prenose NZB na dan).
        self._nzb: "OrderedDict[str, tuple]" = OrderedDict()
        # Zadnja preverba kljuca po storitvi (samo v pomnilniku - po zagonu se nepreverjen preveri znova, kot Android).
        self._zadnja_preverba: dict = {}
        # Odtis kljuca, ki ga je ta zadnja preverba preverila: zamenjan kljuc se preveri takoj (P.preveri_zdaj po kljucu).
        self._preverjen_odtis: dict = {}
        self._preverjam = threading.Lock()      # ena preverba nepreverjenih naenkrat (okno odprto veckrat zapored)
        # (storitev, odtis) -> zadnji »Preveri« ali vpis tega kljuca (time.monotonic): najvec 1 na minuto (S8).
        self._rocna: "OrderedDict[tuple, float]" = OrderedDict()
        self._zaklep_rocne = threading.Lock()
        # Grokov pregled 40, S3: (storitev, odtis) -> »ne velja« ali »zaklenjen« v pomnilniku, ZE PRED zapisom v
        # nastavitve - zapora velja tudi, ce zapis ne uspe (poln disk, nastavitve samo za branje, zbirka zaklenjena).
        # Grokov pregled 47: velja po kljucu, »Odstrani« in zamenjava je ne odpravita (U1); bere in pise se samo pod
        # _zaklep_zapor (U4) - pise ga vec niti (⚡, predvajanje, »Preveri« v niti mostu, samodejna preverba).
        self._zaprti: dict = {}
        self._odtisa_ix: dict = {}       # (oznaka naslova, oznaka kljuca) -> (stari, novi) odtis indeksatorja (O1; samo v pomnilniku)
        self._zaklep_zapor = threading.Lock()   # notranji: pod njim se ne klice nic drugega (zaklep nastavitev je zunanji)

    def _rocna_cez(self, p: str, odtis: str) -> int:
        """Grokov pregled 40, S8: 0 = »Preveri« ali vpis kljuca z [odtis] sme k storitvi (cas se zabelezi), sicer sekunde
        do naslednjega. Prej ni bilo meje - vsak klik na »Preveri« ali Enter z istim kljucem je bil nov poskus prijave."""
        zdaj = time.monotonic()
        with self._zaklep_rocne:
            zadnjic = self._rocna.get((p, odtis))
            if zadnjic is not None and not P.rocna_preverba_dovoljena(zadnjic, zdaj):
                return min(int(P.ROCNA_PREVERBA_S), int(P.ROCNA_PREVERBA_S - (zdaj - zadnjic)) + 1)
            self._rocna.pop((p, odtis), None)
            self._rocna[(p, odtis)] = zdaj
            while len(self._rocna) > 64:
                self._rocna.popitem(last=False)
        return 0

    def _nastavitve(self) -> dict:
        d = self._beri()
        return d if isinstance(d, dict) else {}

    def _spremeni(self, fn: Callable[[dict], None]) -> None:
        with self._zaklep:
            d = self._z_novim_odtisom(dict(self._nastavitve()))     # O1: stanje pod starim odtisom gre z naslednjim zapisom na novega
            fn(d)
            self._pisi(d)

    # ---- kljuci
    def kljuc(self, p: str) -> Optional[str]:
        enc = str((self._nastavitve().get("kljuci") or {}).get(p) or "")
        if not enc:
            return None
        if enc not in self._kljuci:
            try:
                self._kljuci[enc] = self._desifriraj(enc)
            except Exception:  # noqa: BLE001 - kljuca ni mogoce prebrati: kot da ga ni
                self._kljuci[enc] = ""
        return P.ocisti_kljuc(self._kljuci[enc])

    def z_kljucem(self) -> list:
        return [p for p in P.VSI if self.kljuc(p)]

    def _pozabi(self, *zapisi: str) -> None:
        """Sifrirane zapise (oznake v zbirki skrivnosti), ki jih nastavitve ne uporabljajo vec, izbrisi."""
        for enc in zapisi:
            if enc:
                self._kljuci.pop(enc, None)
                try:
                    self._pozabi_skrivnost(enc)
                except Exception:  # noqa: BLE001 - zbirka zaklenjena: oznaka v nastavitvah je ze odstranjena
                    _log.info("brisanje skrivnosti ni uspelo")

    @staticmethod
    def _zapis_stanja(stanje: Optional[str], odtis: str) -> Optional[dict]:
        """Stanje kljuca v nastavitvah: {"s", "odtis", "ob"} - odtis (P.odtis_stanja), nikoli kljuc."""
        return {"s": stanje, "odtis": odtis, "ob": time.time()} if stanje else None

    @staticmethod
    def _postavi_zaporo(d: dict, p: str, odtis: Optional[str], s: Optional[str]) -> None:
        """Grokov pregled 47, U1 (kot Android a15fb57): zapora po KLJUCU v nastavitvah (d["zapore"][p] = {odtis: stanje},
        zadnjih P.NAJVEC_ZAPOR) - prezivi zamenjavo kljuca, »Odstrani« in ponovni zagon; odpravi jo samo »velja«."""
        if not odtis:
            return
        zs = d.get("zapore")
        if not isinstance(zs, dict):
            if zs is not None:
                Debrid._zapri_druge(d, p)          # pokvarjen razdelek zapor (U2)
            zs = d["zapore"] = {}
        zs[p] = P.z_zaporo(P.zapore_iz_zapisa(zs.get(p)) or {}, odtis, s)

    @staticmethod
    def _ima_kljuc(d: dict, q: str) -> bool:
        if q == P.INDEKSATOR:
            u = d.get("usenet")
            return isinstance(u, dict) and bool(u.get("url")) and bool(u.get("kljuc"))
        k = d.get("kljuci")
        return isinstance(k, dict) and bool(k.get(q))

    @staticmethod
    def _zapri_druge(d: dict, p: str) -> None:
        """Grokov pregled 47, U2: razdelek stanj ali zapor, ki ni slovar (pokvarjena datoteka, druga razlicica), je do
        zapisa zaprl vse kljuce (S3), prvi zapis stanja katere koli storitve pa ga je zamenjal s praznim - zapore DRUGIH
        storitev so izginile in njihovi kljuci so spet sli storitvam (odpove odprto). Zdaj vsaka druga storitev s
        shranjenim kljucem brez dokoncnega stanja dobi zapis »ne velja« brez odtisa (P.stanje_iz_zapisa: velja za kateri
        koli kljuc) - nazaj ga vrne samo »Preveri« ali vpis, ki ga storitev potrdi."""
        st = d.get("stanja")
        st = d["stanja"] = dict(st) if isinstance(st, dict) else {}
        for q in P.VSI + (P.INDEKSATOR,):
            z = st.get(q)
            dokoncno = (isinstance(z, dict) and bool(z.get("odtis"))
                        and z.get("s") in (P.STANJE_VELJA, P.STANJE_NE_VELJA, P.STANJE_ZAKLENJEN))
            if q != p and Debrid._ima_kljuc(d, q) and not dokoncno:
                st[q] = {"s": P.STANJE_NE_VELJA, "ob": time.time()}
        _log.warning("stanja kljucev ni mogoce prebrati - druge storitve ostanejo zaprte do »Preveri«")

    @staticmethod
    def _postavi_stanje(d: dict, p: str, zapis: Optional[dict]) -> None:
        """Stanje kljuca na mestu storitve [p] in zapora po kljucu (U1). [zapis] None (»Odstrani«) pobrise samo mesto
        storitve - zapora kljuca ostane."""
        if d.get("stanja") is not None and not isinstance(d.get("stanja"), dict):
            Debrid._zapri_druge(d, p)              # pokvarjen razdelek stanj ne odpre drugih storitev (U2)
        st = d.setdefault("stanja", {})
        if zapis is None:
            st.pop(p, None)
        else:
            st[p] = zapis
            Debrid._postavi_zaporo(d, p, zapis.get("odtis"), zapis.get("s"))

    def nastavi_kljuc(self, p: str, vnos: str, paket: Optional[int] = None, stanje: Optional[str] = None) -> bool:
        """Shrani kljuc (sifriran) s paketom in stanjem preverbe (None = nepreverjen). Brez preverbe in zavrnitve
        vzorca - vnos uporabnika gre skozi vpisi_kljuc."""
        k = P.ocisti_kljuc(vnos)
        if p not in P.VSI or k is None:
            return False
        enc = self._sifriraj(k)
        if not enc:
            return False
        staro: list = []
        odtis = P.odtis_stanja(k)

        def f(d: dict) -> None:
            staro.append(str((d.get("kljuci") or {}).get(p) or ""))
            d.setdefault("kljuci", {})[p] = enc
            pak = d.setdefault("paketi", {})
            if paket is None:
                pak.pop(p, None)
            else:
                pak[p] = int(paket)
            # Grokov pregled 40, S3: ISTI kljuc brez stanja (uvoz, selitev, uskladitev) ohrani svoje stanje - prej je tiho
            # pobrisal »zaklenjen« in kljuc je spet sel storitvi. Grokov pregled 47, U2: zapis na mestu storitve je vedno
            # zapis SHRANJENEGA kljuca (tudi zapora po kljucu gre nanj) - prej je ostal zapis prejsnjega kljuca in
            # popravilo pokvarjenega razdelka zapor (_zapri_druge) bi ga vzelo za dokoncno stanje.
            s = stanje if stanje is not None else self._stanje_v(d, p, odtis)
            self._postavi_stanje(d, p, self._zapis_stanja(s, odtis))
        self._spomni_zaporo(p, odtis, stanje)
        self._spremeni(f)
        self._pozabi(*[x for x in staro if x != enc])
        return True

    def vpisi_kljuc(self, p: str, vnos: str, preveri: Optional[Callable[[str], tuple]] = None) -> dict:
        """Vnos v oknu »Debrid storitve«: oblika in vzorec (P.kljuc_iz_vnosa - brez klica storitve), preverba pri
        storitvi (TorBox user/me, Real-Debrid in AllDebrid /user), shranjevanje s stanjem.
        {"ok", "preverba": P.PREVERBA_*, "paket", "stanje"}. Zavrnjen kljuc se ne shrani; izpad ga shrani kot nepreverjen."""
        k = P.kljuc_iz_vnosa(vnos, p)
        if p not in P.VSI or k is None:
            return {"ok": False, "preverba": P.PREVERBA_OBLIKA, "paket": None, "stanje": None}
        odtis = P.odtis_stanja(k)
        cez = self._rocna_cez(p, odtis)
        if cez:
            return {"ok": False, "preverba": P.PREVERBA_POCAKAJ, "paket": None, "stanje": None, "cez_s": cez}
        # Grokov pregled 47, U1 (kot Android a15fb57): stanje TEGA kljuca, tudi ce ni vec shranjen (zapora po kljucu).
        # Prej samo shranjenega: prej zaprt kljuc je po zamenjavi, »Odstrani« ali ponovnem zagonu ob izpadu storitve
        # postal »nepreverjen« in ⚡, predvajanje in samodejna preverba so ga spet posiljali zaklenjenemu racunu.
        prej = self._stanje_v(self._nastavitve(), p, odtis)
        izid, paket = preveri(k) if preveri is not None else preveri_kljuc(p, k)
        s = P.stanje_po_vpisu(prej, izid)
        if s is None:
            return {"ok": False, "preverba": izid, "paket": None, "stanje": None}
        self._zadnja_preverba[p], self._preverjen_odtis[p] = time.time(), P.odtis_stanja(k)
        return {"ok": self.nastavi_kljuc(p, k, paket, s), "preverba": izid, "paket": paket, "stanje": s}

    # ---- stanje kljuca (lastnik 25. 10. 2026, kot Android Debrid.stanjeKljuca/obIzidu/preveriNepreverjene)
    def _oznaka(self, d: dict, p: str) -> tuple:
        """Sifrirani zapisi kljuca [p] v nastavitvah [d]: zapis stanja velja samo, ce se med preverbo niso spremenili."""
        if p == P.INDEKSATOR:
            u = d.get("usenet") if isinstance(d.get("usenet"), dict) else {}
            return str(u.get("url") or ""), str(u.get("kljuc") or "")
        return (str((d.get("kljuci") or {}).get(p) or ""),)

    def _odtis(self, p: str) -> Optional[str]:
        """Odtis kljuca [p] (indeksator: naslov in kljuc) ali None, ce kljuca ni."""
        if p == P.INDEKSATOR:
            ix = self.indeksator()
            return P.odtis_indeksatorja(ix[0], ix[1]) if ix else None
        k = self.kljuc(p)
        return P.odtis_stanja(k) if k else None

    def _odtisa_indeksatorja(self, d: dict) -> Optional[tuple]:
        """(stari, novi) odtis shranjenega indeksatorja v [d]: stari je odtis naslova, kot je shranjen (do U5, 9ea51fe), novi
        P.odtis_indeksatorja. Desifriranje samo enkrat na par zapisov (zbirka skrivnosti je klic D-Bus); None = ni
        indeksatorja ali ga ni mogoce prebrati."""
        u = d.get("usenet")
        if not isinstance(u, dict) or not u.get("url") or not u.get("kljuc"):
            return None
        oznaki = (str(u["url"]), str(u["kljuc"]))
        par = self._odtisa_ix.get(oznaki)
        if par is None:
            ix = self._indeksator_iz(d)
            if not ix:
                return None
            if len(self._odtisa_ix) >= 16:
                self._odtisa_ix.clear()
            par = self._odtisa_ix[oznaki] = (P.odtis_stanja(ix[0] + "|" + ix[1]), P.odtis_indeksatorja(ix[0], ix[1]))
        return par

    def _z_novim_odtisom(self, d: dict) -> dict:
        """Grokov pregled 49, O1: U5 (9ea51fe) je odtis indeksatorja izracunal iz poenotenega naslova, stanje in zapore
        iz prejsnje razlicice pa so pod odtisom naslova, kot je bil vpisan (»www.«, velike crke …): zaklenjen indeksator je
        bil »brez stanja« in ga je samodejna preverba klicala (zaklep racuna). Vrne [d] z odtisom shranjenega indeksatorja
        prenesenim na novega (stanje na mestu storitve in zapora v seznamu; ob dveh zaporah velja strozja) ali [d] samega."""
        st, zs = d.get("stanja"), d.get("zapore")
        mesto = isinstance(st, dict) and isinstance(st.get(P.INDEKSATOR), dict)
        seznam = isinstance(zs, dict) and isinstance(zs.get(P.INDEKSATOR), dict)
        if not mesto and not seznam:
            return d
        par = self._odtisa_indeksatorja(d)
        if not par or par[0] == par[1]:
            return d
        star, nov = par
        mesto = mesto and st[P.INDEKSATOR].get("odtis") == star
        seznam = seznam and star in zs[P.INDEKSATOR]
        if not mesto and not seznam:
            return d
        d = dict(d)
        if mesto:
            d["stanja"] = dict(st, **{P.INDEKSATOR: dict(st[P.INDEKSATOR], odtis=nov)})
        if seznam:
            z, novi = zs[P.INDEKSATOR], {}
            for o, s in z.items():
                if o == star:
                    if nov not in z:                # sicer pride na vrsto pri vnosu novega odtisa
                        novi[nov] = s
                elif o == nov:
                    novi[o] = P.strozja_zapora(s, z[star])
                else:
                    novi[o] = s
            d["zapore"] = dict(zs, **{P.INDEKSATOR: novi})
        return d

    def _stanje_v(self, d: dict, p: str, odtis: Optional[str]) -> Optional[str]:
        """Stanje kljuca z [odtis] (P.STANJE_*), tudi kljuca, ki ni (vec) shranjen: P.stanje_z_zaporo iz zapore v
        pomnilniku (S3), zapisa na mestu storitve v nastavitvah [d] (P.stanje_iz_zapisa: neberljiv zapis je »ne velja«) in
        zapore po kljucu (Grokov pregled 47, U1). None = ni zapisa ali je zapis drugega kljuca."""
        if not odtis:
            return None
        if p == P.INDEKSATOR:
            d = self._z_novim_odtisom(d)           # Grokov pregled 49, O1: stanje in zapora pod odtisom pred U5 veljata
        st = d.get("stanja")
        na_mestu = (P.STANJE_NE_VELJA if st is not None and not isinstance(st, dict)    # pokvarjen razdelek stanj (S3)
                    else P.stanje_iz_zapisa((st or {}).get(p), odtis))
        zs = d.get("zapore")
        zapore = P.zapore_iz_zapisa(zs.get(p) if isinstance(zs, dict) else zs)
        zapora = P.STANJE_NE_VELJA if zapore is None else zapore.get(odtis)    # pokvarjen razdelek zapor: zaprto (U2)
        with self._zaklep_zapor:
            v_pomnilniku = self._zaprti.get((p, odtis))
        return P.stanje_z_zaporo(v_pomnilniku, na_mestu, zapora)

    def _spomni_zaporo(self, p: str, odtis: Optional[str], s: Optional[str]) -> None:
        """Grokov pregled 40, S3: »ne velja« in »zaklenjen« v pomnilnik pred zapisom; potrjeno stanje zaporo odpravi."""
        if not odtis or s is None:
            return
        with self._zaklep_zapor:
            if s in (P.STANJE_NE_VELJA, P.STANJE_ZAKLENJEN):
                self._zaprti[(p, odtis)] = s
            elif s == P.STANJE_VELJA:               # U1: »nepreverjen« zapore ne odpravi (kot Android)
                self._zaprti.pop((p, odtis), None)

    def stanje_kljuca(self, p: str) -> Optional[str]:
        """P.STANJE_* shranjenega kljuca [p]; None = ni kljuca ali ga se nihce ni preveril (stanje drugega kljuca ne velja)."""
        return self._stanje_v(self._nastavitve(), p, self._odtis(p))

    def sme_klicati(self, p: str) -> bool:
        """Ali storitev [p] s shranjenim kljucem sploh klicemo (P.sme_klicati: ne »ne velja« in ne »zaklenjen«)."""
        return P.sme_klicati(self.stanje_kljuca(p))

    def kljuc_velja(self, p: str) -> bool:
        """Kljuc, ki ga je storitev potrdila - samo tak bo sel med naprave (P.za_uskladitev), ko bo namizje usklajevalo."""
        return P.za_uskladitev(self.stanje_kljuca(p))

    def _zapisi_stanje(self, p: str, oznaka: tuple, odtis: str, s: str, paket: Optional[int] = None,
                       samo_iz: Optional[tuple] = None) -> bool:
        """Zapis stanja za kljuc z [odtis], ce je kljuc se isti kot ob zacetku preverbe ([oznaka]) in - z [samo_iz] - ce je
        stanje TA trenutek (pod zaklepom nastavitev) eno od [samo_iz]; True = zapisano."""
        zapisano: list = []

        def f(d: dict) -> None:
            if self._oznaka(d, p) != oznaka:
                # Kljuc je bil medtem zamenjan ali odstranjen: mesto storitve je novega kljuca, zapora pa velja za kljuc
                # zahteve (Grokov pregled 47, U1) - ponoven vpis ga brez odgovora storitve ne odklene.
                if s in (P.STANJE_NE_VELJA, P.STANJE_ZAKLENJEN):
                    self._postavi_zaporo(d, p, odtis, s)
                return
            if samo_iz is not None and self._stanje_v(d, p, odtis) not in samo_iz:
                return                              # druga nit je medtem zapisala novejse stanje (Grok 40, S6)
            self._postavi_stanje(d, p, self._zapis_stanja(s, odtis))
            if paket is not None and p == P.TORBOX:
                d.setdefault("paketi", {})[p] = int(paket)
            zapisano.append(True)
        if s in (P.STANJE_NE_VELJA, P.STANJE_ZAKLENJEN):
            self._spomni_zaporo(p, odtis, s)        # S3: zapora velja, tudi ce zapis spodaj ne uspe
        try:
            self._spremeni(f)
        except Exception as e:  # noqa: BLE001 - zapora ostane v pomnilniku, klic se ne podre
            _log.warning("%s: stanja ni bilo mogoce zapisati (%s)", P.ime(p), type(e).__name__)
            return False
        if zapisano and s not in (P.STANJE_NE_VELJA, P.STANJE_ZAKLENJEN):
            self._spomni_zaporo(p, odtis, s)
        return bool(zapisano)

    def _vezava(self, p: str) -> tuple:
        """(oznaka, odtis) kljuca [p] ob ZACETKU zahteve - preberi jo, preden preberes kljuc za zahtevo. Grokov pregled
        36, D2: ob_izidu je oznako in odtis bral sele po odgovoru - 401 starega kljuca je oznacil »ne velja« kljuc, ki ga je
        uporabnik vpisal med zahtevo (uspeh starega pa novega »velja«)."""
        return self._oznaka(self._nastavitve(), p), self._odtis(p)

    def ob_izidu(self, p: str, napaka: str, uspeh: bool, vezava: Optional[tuple] = None) -> None:
        """Med uporabo: zavrnjen kljuc (P.NAPAKA_KLJUC, npr. 401) -> »ne velja«; zaklenjen racun (P.NAPAKA_ZAKLENJEN) ->
        »zaklenjen«; odgovor s povezavo ali zadetki -> velja. Zapise samo spremembo. [p] je storitev ali P.INDEKSATOR.
        Po »ne velja« ali »zaklenjen« storitve ne klicemo vec (P.sme_klicati), dokler uporabnik ne pritisne »Preveri«.
        [vezava] = _vezava(p) pred zahtevo: ce je bil kljuc medtem zamenjan, se izid ne zapise (_zapisi_stanje)."""
        oznaka, odtis = vezava if vezava is not None else self._vezava(p)
        if not odtis:
            return
        if p == P.INDEKSATOR and napaka in (P.NAPAKA_KLJUC, P.NAPAKA_ZAKLENJEN):
            self._pozabi_povezave(lambda o: o != odtis)     # Grok 40, S1: zavrnjen kljuc ne ostane v povezavah NZB
        prej = self._stanje_v(self._nastavitve(), p, odtis)     # stanje kljuca zahteve, tudi ce je zamenjan (U1)
        novo = P.stanje_po_uporabi(prej, napaka, uspeh)
        if novo == P.STANJE_VELJA:
            # Grokov pregled 40, S6: »velja« samo iz »nepreverjen« ali brez stanja - preverjeno pod zaklepom nastavitev,
            # da pozen uspeh ne prepise zapore, ki jo je druga nit zapisala po branju [prej].
            self._zapisi_stanje(p, oznaka, odtis, novo, samo_iz=(None, P.STANJE_NEPREVERJEN))
        elif novo is not None:
            if self._zapisi_stanje(p, oznaka, odtis, novo):
                _log.info("%s: med uporabo - stanje »%s«, storitve ne klicemo vec", P.ime(p), novo)
        elif uspeh and prej in (P.STANJE_NE_VELJA, P.STANJE_ZAKLENJEN):
            _log.info("%s: pozen uspeh ne odpravi stanja »%s« (samo »Preveri«)", P.ime(p), prej)

    def _preveri_eno(self, p: str) -> tuple:
        """(P.PREVERBA_*, paket) za shranjen kljuc [p] - blokirajoce. Shranjen ne-kljuc (vzorec iz navodil ali oblika iz
        prejsnje razlicice) ne gre storitvi (Grokov pregled 36, D7): »ne velja« brez klica - zavrnjen vpis manj."""
        if p == P.INDEKSATOR:
            ix = self.indeksator()
            if not ix:
                return P.PREVERBA_OBLIKA, None
            if P.kljuc_iz_vnosa(ix[1], P.INDEKSATOR) is None:
                return P.PREVERBA_NEVELJAVEN, None
            return indeksator_preveri(ix[0], ix[1]), None
        k = self.kljuc(p)
        if not k:
            return P.PREVERBA_OBLIKA, None
        if P.kljuc_iz_vnosa(k, p) is None:
            return P.PREVERBA_NEVELJAVEN, None
        return preveri_kljuc(p, k)

    def preveri_nepreverjene(self) -> bool:
        """Kljuci brez stanja (shranjeni pred to razlicico) ali nepreverjeni: preverba pri storitvi, nepreverjen najvec na
        P.PREVERI_ZNOVA_S. Zavrnjen ostane shranjen z oznako »ne velja« (vrstica pove, da ga je treba vpisati znova).
        Blokirajoce (do 8 s na kljuc) - samo z delovne niti. True = stanje katerega se je spremenilo."""
        if not self._preverjam.acquire(blocking=False):
            return False                            # preverba ze tece (okno odprto znova)
        try:
            spremenjeno = False
            for p in P.VSI + (P.INDEKSATOR,):
                oznaka, odtis = self._oznaka(self._nastavitve(), p), self._odtis(p)
                if not odtis:
                    continue
                prej, zdaj = self.stanje_kljuca(p), time.time()
                # Omejitev je po kljucu in v pomnilniku: tudi ce se stanje ne zapise, isti kljuc najvec na 10 min.
                zadnjic = float(self._zadnja_preverba.get(p, 0.0)) if self._preverjen_odtis.get(p) == odtis else 0.0
                if not P.preveri_zdaj(prej, zadnjic, zdaj):
                    continue
                self._zadnja_preverba[p], self._preverjen_odtis[p] = zdaj, odtis
                izid, paket = self._preveri_eno(p)
                if izid == P.PREVERBA_OBLIKA:
                    continue
                s = P.stanje_po_preverbi(izid) or P.STANJE_NE_VELJA
                if s != prej or (paket is not None and paket != self.paket(p)):
                    spremenjeno = self._zapisi_stanje(p, oznaka, odtis, s, paket) or spremenjeno
            return spremenjeno
        finally:
            self._preverjam.release()

    def preveri_izrecno(self, p: str) -> dict:
        """Uporabnik je pritisnil »Preveri« pri kljucu [p] (storitev ali P.INDEKSATOR): ena preverba ne glede na stanje -
        edina pot, po kateri se kljuc »ne velja« ali »zaklenjen« znova poskusi (lastnik 26. 10. 2026). Gumb je med
        preverbo zaklenjen. {"ok", "preverba", "stanje"[, "cez_s"]}.
        Grokov pregled 40, S8: isti kljuc najvec enkrat na minuto (P.PREVERBA_POCAKAJ, brez klica) in brez cakanja na
        tekoco samodejno preverbo (do 4 x 8 s v niti mostu) - P.PREVERBA_TECE."""
        if not self._preverjam.acquire(blocking=False):
            return {"ok": False, "preverba": P.PREVERBA_TECE, "stanje": self.stanje_kljuca(p)}
        try:
            oznaka, odtis = self._oznaka(self._nastavitve(), p), self._odtis(p)
            if not odtis:
                return {"ok": False, "preverba": P.PREVERBA_OBLIKA, "stanje": None}
            cez = self._rocna_cez(p, odtis)
            if cez:
                return {"ok": False, "preverba": P.PREVERBA_POCAKAJ, "stanje": self.stanje_kljuca(p), "cez_s": cez}
            self._zadnja_preverba[p], self._preverjen_odtis[p] = time.time(), odtis
            izid, paket = self._preveri_eno(p)
            s = P.stanje_po_rocni_preverbi(izid)
            if s is None:
                # Grokov pregled 40, S2: storitev ni odgovorila - zaprt kljuc ostane zaprt (vmesnik to pove).
                _log.info("%s: »Preveri« brez odgovora storitve - stanje ostane", P.ime(p))
            else:
                self._zapisi_stanje(p, oznaka, odtis, s, paket)
            return {"ok": True, "preverba": izid, "stanje": self.stanje_kljuca(p)}
        finally:
            self._preverjam.release()

    def paket(self, p: str) -> Optional[int]:
        """Paket ob zadnji preverbi kljuca (TorBox: P.TORBOX_PAKETI) ali None, ce ga ne poznamo."""
        v = (self._nastavitve().get("paketi") or {}).get(p)
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    def pozabi_kljuc(self, p: str) -> None:
        staro: list = []

        def f(d: dict) -> None:
            staro.append(str((d.get("kljuci") or {}).get(p) or ""))
            d.setdefault("kljuci", {}).pop(p, None)
            d.setdefault("meritve", {}).pop(p, None)
            d.setdefault("paketi", {}).pop(p, None)
            self._postavi_stanje(d, p, None)
        self._spremeni(f)
        # Grokov pregled 47, U4: skrivnost se izbrise takoj po zapisu nastavitev. Prej je bil vmes pregled _zaprti brez
        # zaklepa - zapora, ki jo je druga nit dodala med pregledom, je vrgla RuntimeError in sifriran kljuc je ostal v
        # zbirki, ceprav je vmesnik rekel »odstranjen«. Zapora po kljucu ostane (U1, kot Android).
        self._pozabi(*staro)
        self._zadnja_preverba.pop(p, None)
        self._preverjen_odtis.pop(p, None)

    # ---- Usenet: uporabnikov indeksator Newznab (naslov in kljuc samo sifrirana, kot kljuci storitev)
    def indeksator(self) -> Optional[tuple]:
        """(osnova, kljuc) ali None. Naslov je lahko zaseben (streznik v domacem omrezju), zato je tudi sifriran."""
        return self._indeksator_iz(self._nastavitve())

    def _indeksator_iz(self, d: dict) -> Optional[tuple]:
        u = d.get("usenet") or {}
        if not isinstance(u, dict) or not u.get("url") or not u.get("kljuc"):
            return None
        try:
            osn = U.osnova(self._desifriraj(str(u["url"])))
            k = U.ocisti_kljuc(self._desifriraj(str(u["kljuc"])))
        except Exception:  # noqa: BLE001 - zapisa ni mogoce prebrati: kot da ga ni
            return None
        return (osn, k) if osn and k else None

    def _zamenjaj_indeksator(self, nov: Optional[dict], stanje: Optional[dict] = None, odtis: Optional[str] = None) -> None:
        staro: list = []

        def f(d: dict) -> None:
            u = d.get("usenet")
            if isinstance(u, dict):
                staro.extend([str(u.get("url") or ""), str(u.get("kljuc") or "")])
            if nov is None:
                d.pop("usenet", None)
            else:
                d["usenet"] = nov
            # Grokov pregled 40, S3: isti naslov in kljuc brez stanja ohrani svoje stanje; U2: zapis na mestu je vedno
            # zapis shranjenega indeksatorja (kot nastavi_kljuc).
            if nov is None:
                self._postavi_stanje(d, P.INDEKSATOR, None)
            else:
                self._postavi_stanje(d, P.INDEKSATOR, stanje if stanje is not None
                                     else self._zapis_stanja(self._stanje_v(d, P.INDEKSATOR, odtis), odtis))
        if nov is not None:                         # odstranitev: zapora po kljucu ostane (U1), brez pregleda _zaprti (U4)
            self._spomni_zaporo(P.INDEKSATOR, odtis, (stanje or {}).get("s"))
        self._spremeni(f)
        self._pozabi(*[x for x in staro if x not in (nov or {}).values()])     # U4: takoj po zapisu nastavitev
        self._zadnja_preverba.pop(P.INDEKSATOR, None)
        self._preverjen_odtis.pop(P.INDEKSATOR, None)
        # Grokov pregled 40, S1: povezave NZB s prejsnjim kljucem (v naslovu) ne ostanejo v pomnilniku.
        nov_odtis = self._odtis(P.INDEKSATOR)
        self._pozabi_povezave(lambda o: o is not None and o == nov_odtis)

    def nastavi_indeksator(self, naslov: str, kljuc: str, stanje: Optional[str] = None) -> bool:
        osn, k = U.osnova(naslov), U.ocisti_kljuc(kljuc)
        if not osn or not k:
            return False
        enc_u, enc_k = self._sifriraj(osn), self._sifriraj(k)
        if not enc_u or not enc_k:
            return False
        odtis = P.odtis_indeksatorja(osn, k)
        self._zamenjaj_indeksator({"url": enc_u, "kljuc": enc_k}, self._zapis_stanja(stanje, odtis), odtis)
        return True

    def vpisi_indeksator(self, naslov: str, kljuc: str, preveri: Optional[Callable[[str, str], str]] = None) -> dict:
        """Vnos indeksatorja (npr. NZBFinder: kljuc s strani profila): oblika in vzorec (P.kljuc_iz_vnosa), preverba z
        enim iskanjem, shranjevanje s stanjem. {"ok", "preverba": P.PREVERBA_*, "stanje"}. Zavrnjen kljuc se ne shrani.
        Grokov pregled 31, H1: kljuc v polju za naslov (U.naslov_je_kljuc) se ne shrani in ne gre nikamor - tudi ne v DNS."""
        if U.naslov_je_kljuc(naslov):
            return {"ok": False, "preverba": U.PREVERBA_NASLOV_JE_KLJUC, "stanje": None}
        osn, k = U.osnova(naslov), P.kljuc_iz_vnosa(kljuc, P.INDEKSATOR)
        if not osn or not k:
            return {"ok": False, "preverba": P.PREVERBA_OBLIKA, "stanje": None}
        # Grokov pregled 47, U5: meja, zapora in stanje po poenotenem naslovu (P.odtis_indeksatorja).
        odtis = P.odtis_indeksatorja(osn, k)
        cez = self._rocna_cez(P.INDEKSATOR, odtis)
        if cez:
            return {"ok": False, "preverba": P.PREVERBA_POCAKAJ, "stanje": None, "cez_s": cez}
        # Grokov pregled 47, U1: stanje tega naslova in kljuca, tudi ce ni vec shranjen (zapora po kljucu, kot Android).
        prej = self._stanje_v(self._nastavitve(), P.INDEKSATOR, odtis)
        izid = (preveri or indeksator_preveri)(osn, k)
        s = P.stanje_po_vpisu(prej, izid)
        if s is None:
            return {"ok": False, "preverba": izid, "stanje": None}
        ok = self.nastavi_indeksator(osn, k, s)
        self._zadnja_preverba[P.INDEKSATOR] = time.time()
        self._preverjen_odtis[P.INDEKSATOR] = odtis
        return {"ok": ok, "preverba": izid, "stanje": s}

    def pozabi_indeksator(self) -> None:
        self._zamenjaj_indeksator(None)

    def gostitelj_indeksatorja(self) -> str:
        ix = self.indeksator()
        return (urllib.parse.urlsplit(ix[0]).hostname or "") if ix else ""

    def usenet_na_voljo(self) -> bool:
        """Indeksator, kljuc TorBox (prenese in pretaka TorBox) in uporabnik ni izbral »Brez debrida«. Iskanje in prenos
        NZB tecejo sama ob seznamu virov: s kljucem, ki ga je indeksator ali TorBox zavrnil, ali z zaklenjenim racunom ne
        (P.sme_klicati - vsak klic bi bil se en zavrnjen poskus prijave; indeksatorji stejejo klice API na dan)."""
        if (self.indeksator() is not None and bool(self.kljuc(P.TORBOX)) and self.aktivna() is not None
                and self.sme_klicati(P.INDEKSATOR) and self.sme_klicati(P.TORBOX)):
            return True
        # Naloga 114: z lastnim ponudnikom NNTP TorBox ni potreben; »Brez debrida« ga ne izklopi, ker ni debrid.
        return self.indeksator() is not None and self.sme_klicati(P.INDEKSATOR) and self.lastni_usenet_na_voljo()

    def lastni_usenet_na_voljo(self) -> bool:
        """Lasten pogon z uporabnikovim ponudnikom (brez omrezja); napaka pomeni ne."""
        l = self.lastni_usenet
        try:
            return bool(l is not None and l.na_voljo())
        except Exception:  # noqa: BLE001
            return False

    def usenet_isci(self, ident: str) -> list:
        """Tokovi Usenet za id Stremio: [{"url": "usenet:…", "opis": …, "gb": …}]. Povezave NZB ostanejo v pomnilniku."""
        vezava = self._vezava(P.INDEKSATOR)
        ix = self.indeksator()
        if not ix or not self.usenet_na_voljo() or not U.iscemo(ident):
            return []
        tokovi = []
        for z in usenet_isci(ix[0], ix[1], ident, ob_izidu=lambda n, u: self.ob_izidu(P.INDEKSATOR, n, u, vezava)):
            idt = U.id_toka(z.povezava)
            with self._zaklep:
                self._povezave_nzb[idt] = (z.povezava, vezava)
                while len(self._povezave_nzb) > 500:
                    self._povezave_nzb.pop(next(iter(self._povezave_nzb)))
            tokovi.append({"url": idt, "opis": U.opis(z), "naslov": z.naslov, "gb": z.velikost / 1073741824.0,
                           "vir": "Usenet", "usenet": True})
        return tokovi

    #: Predpomnilnik NZB: najvec toliko izdaj, bajtov skupaj in sekund (NZB filma je obicajno 1-5 MB).
    NZB_NAJVEC = 3
    NZB_NAJVEC_BAJTOV = 30 * 1024 * 1024
    NZB_VELJA_S = 900.0

    def _nzb_zapomnjen(self, id_toka: str) -> Optional[bytes]:
        with self._zaklep:
            v = self._nzb.get(id_toka)
            if v is None:
                return None
            if time.monotonic() - v[0] > self.NZB_VELJA_S:
                self._nzb.pop(id_toka, None)
                return None
            return v[1]

    def _zapomni_nzb(self, id_toka: str, nzb: bytes) -> None:
        with self._zaklep:
            self._nzb.pop(id_toka, None)
            self._nzb[id_toka] = (time.monotonic(), nzb)
            while self._nzb and (len(self._nzb) > self.NZB_NAJVEC
                                 or sum(len(b) for _c, b in self._nzb.values()) > self.NZB_NAJVEC_BAJTOV):
                self._nzb.popitem(last=False)

    @staticmethod
    def _odtis_povezave(v: object) -> Optional[str]:
        """Odtis kljuca indeksatorja, s katerim je bila povezava NZB najdena (vezava ob iskanju), ali None."""
        vezava = v[1] if isinstance(v, tuple) and len(v) == 2 else None
        return vezava[1] if isinstance(vezava, tuple) and len(vezava) == 2 and vezava[1] else None

    def _pozabi_povezave(self, ostane: Callable[[Optional[str]], bool]) -> None:
        """Povezave NZB (in NZB iz njih), katerih kljuc indeksatorja ne ostane v rabi, odstrani iz pomnilnika (Grokov
        pregled 40, S1: povezava nosi kljuc v naslovu - zamenjan, odstranjen ali zavrnjen kljuc ne sme ostati v njej)."""
        with self._zaklep:
            for idt in [i for i, v in self._povezave_nzb.items() if not ostane(self._odtis_povezave(v))]:
                self._povezave_nzb.pop(idt, None)
                self._nzb.pop(idt, None)

    def usenet_tok(self, id_toka: str, ime_izdaje: str, indeks: Optional[int] = None,
                   samo_takoj: bool = False, rok_cakanja: float = U.CAKAJ_PRENOSA_S,
                   preklic: Optional[threading.Event] = None, lastni: Optional[bool] = None) -> Izid:
        """NZB od indeksatorja (ta racunalnik), nato TorBox. Napaka indeksatorja je U.NAPAKA_INDEKSATOR.
        Naloga 114: [lastni] True = samo lasten pogon; False = samo TorBox; None = lasten pogon, ce je na voljo, razen pri
        [samo_takoj] (vzporedna preverba »pripravljen« v usenet_takoj ne sme odpreti treh lokalnih streznikov)."""
        if lastni is True or (lastni is None and not samo_takoj and self.lastni_usenet_na_voljo()):
            return self._usenet_lastni(id_toka, ime_izdaje)
        vezava_tb = self._vezava(P.TORBOX)
        k = self.kljuc(P.TORBOX)
        if not k:
            return Izid(napaka=P.NAPAKA_KLJUC, ponudnik=P.TORBOX)
        for p in (P.TORBOX, P.INDEKSATOR):
            if not self.sme_klicati(p):         # zavrnjen ali zaklenjen: brez prenosa NZB in brez klica TorBoxa
                return Izid(napaka=self._napaka_stanja(p), ponudnik=P.TORBOX)
        nzb, napaka = self._nzb_toka(id_toka, P.TORBOX)
        if nzb is None:
            return napaka
        izid = torbox_usenet(k, nzb, ime_izdaje, indeks, samo_takoj, rok_cakanja=rok_cakanja, preklic=preklic)
        # Lastnik 25. 10. 2026 (kot Android Usenet.tok): stanje kljuca TorBox sledi uporabi (401 -> »ne velja«).
        _javi(lambda n, u: self.ob_izidu(P.TORBOX, n, u, vezava_tb), izid.napaka, bool(izid.url))
        return izid

    def _usenet_lastni(self, id_toka: str, ime_izdaje: str) -> Izid:
        """Naloga 114: NZB od indeksatorja, predvaja lasten pogon (127.0.0.1 z zetonom) z uporabnikovim ponudnikom.
        Pravila indeksatorja (stanje kljuca, odtis povezave, predpomnjen NZB) so ista kot pri TorBoxu."""
        l = self.lastni_usenet
        if l is None or not self.lastni_usenet_na_voljo():
            return Izid(napaka=NAPAKA_LASTNI_POGON, ponudnik=LASTNI_USENET)
        if not self.sme_klicati(P.INDEKSATOR):
            return Izid(napaka=self._napaka_stanja(P.INDEKSATOR), ponudnik=LASTNI_USENET)
        nzb, napaka = self._nzb_toka(id_toka, LASTNI_USENET)
        if nzb is None:
            return napaka
        url, koda = l.predvajaj(nzb, ime_izdaje)
        if not url:
            _log.info("usenet: lasten pogon ni predvajal (%s)", koda)   # koda je stalen niz brez imen in id-jev
            return Izid(napaka=NAPAKA_LASTNI_POGON, opis=str(koda), ponudnik=LASTNI_USENET)
        return Izid(url=url, ponudnik=LASTNI_USENET)

    def _nzb_toka(self, id_toka: str, ponudnik: str) -> tuple:
        """(NZB, None) ali (None, Izid z napako) - skupno za TorBox in lasten pogon."""
        with self._zaklep:
            v = self._povezave_nzb.get(id_toka)
        # Povezava NZB nosi kljuc indeksatorja iz casa iskanja: izid velja za tisti kljuc (vezava ob iskanju).
        povezava, vezava_ix = v if isinstance(v, tuple) else (v, None)
        if not povezava:
            return None, Izid(napaka=U.NAPAKA_INDEKSATOR, ponudnik=ponudnik)
        # Grokov pregled 40, S1: sme_klicati zgoraj pove stanje TRENUTNEGA kljuca. Povezava iz prejsnjega iskanja je po
        # zamenjavi ali odstranitvi zaklenjenega kljuca poslala STARI kljuc indeksatorju - klicemo samo s kljucem, ki je
        # se shranjen (isti odtis), in torej z njegovim stanjem.
        odtis_ix, trenutni = self._odtis_povezave(v), self._odtis(P.INDEKSATOR)
        if not odtis_ix or odtis_ix != trenutni:
            self._pozabi_povezave(lambda o: o is not None and o == trenutni)
            _log.info("usenet: povezava NZB je iz iskanja s prejsnjim kljucem indeksatorja - brez klica, iskanje znova")
            return None, Izid(napaka=U.NAPAKA_INDEKSATOR, ponudnik=ponudnik)
        nzb = self._nzb_zapomnjen(id_toka)
        if nzb is None:
            nzb, napaka = usenet_nzb(povezava)
            # Stanje kljuca indeksatorja sledi uporabi (401 ali Newznab 100-102 -> »ne velja«, NZB -> velja).
            _javi(lambda n, u: self.ob_izidu(P.INDEKSATOR, n, u, vezava_ix), napaka, nzb is not None)
            if nzb is None:
                return None, Izid(napaka=U.NAPAKA_INDEKSATOR, ponudnik=ponudnik)
            self._zapomni_nzb(id_toka, nzb)
        return nzb, None

    def usenet_takoj(self, tokovi: Sequence[dict], rok: float = U.TAKOJ_ROK_S) -> Optional[tuple]:
        """Lastnik 25. 10. 2026: Usenet, ki ga ima TorBox ze pripravljenega, gre pred vse druge vire. Prve U.TAKOJ_IZDAJ izdaj
        [tokovi] (po kakovosti, najboljsa prva) preverimo hkrati (add_only_if_cached) z rokom [rok]; zmaga najboljsa
        pripravljena. Vrne (indeks v [tokovi], Izid) ali None. Kar zamudi rok, ne doda nicesar (preklic)."""
        izbrani = U.za_takojsnjo([float(t.get("gb") or 0.0) for t in tokovi])
        if not izbrani:
            return None
        konec = time.monotonic() + max(0.1, rok)
        preklic = threading.Event()
        niti = [v_ozadju(self.usenet_tok, str(tokovi[i].get("url") or ""), str(tokovi[i].get("naslov") or ""),
                         None, True, P.CAKAJ_NOVEGA_S, preklic) for i in izbrani]

        def pripravljen(f: Future) -> Optional[bool]:
            if not f.done():
                return None
            izid = _izid_do(f, 0.0)
            return isinstance(izid, Izid) and bool(izid.url)
        try:
            # Skupno pravilo izbire (U.izberi_usenet, isti primeri kot Android): najboljsa pripravljena zmaga, ko so
            # boljse odgovorile »ne«; dokler boljsa se caka, cakamo do roka.
            while True:
                k = U.izberi_usenet([pripravljen(f) for f in niti], time.monotonic() >= konec)
                if k != U.CAKAJ:
                    break
                futures_wait([f for f in niti if not f.done()], timeout=max(0.01, konec - time.monotonic()),
                             return_when=FIRST_COMPLETED)
        finally:
            preklic.set()
        _log.info("usenet takoj: %s", "izdaja %d pripravljena" % k if k >= 0 else "nobena pripravljena")
        return (izbrani[k], niti[k].result()) if k >= 0 else None

    # ---- nastavitve
    def samo_takoj(self) -> bool:
        return bool(self._nastavitve().get("samo_takoj", True))

    def nastavi_samo_takoj(self, da: bool) -> None:
        self._spremeni(lambda d: d.__setitem__("samo_takoj", bool(da)))

    def vrstni_red(self) -> list:
        return P.vrstni_red(self.z_kljucem(), self._nastavitve().get("prednostna"))

    def aktivna(self) -> Optional[str]:
        n = self._nastavitve()
        return P.aktivna(self.z_kljucem(), n.get("prednostna"), bool(n.get("izklopljeno")))

    def nastavi_aktivno(self, p: Optional[str]) -> None:
        """[p] = storitev (postane prednostna), None = »Brez debrida«."""
        def f(d: dict) -> None:
            d["izklopljeno"] = p is None
            if p in P.VSI:
                d["prednostna"] = p
        self._spremeni(f)

    def zadnja_meritev(self, p: str) -> Optional[P.Meritev]:
        z = (self._nastavitve().get("meritve") or {}).get(p)
        if not isinstance(z, dict) or not P.meritev_velja(float(z.get("kdaj") or 0), time.time()):
            return None
        return P.Meritev(p, int(z.get("ping_ms") or 0), int(z.get("bajtov") or 0), int(z.get("cas_ms") or 0))

    def stanje(self) -> dict:
        """Za vmesnik: storitve s stanjem kljuca in zadnjo meritvijo, aktivna in »samo takoj« (brez kljucev)."""
        storitve = []
        for p in P.VSI:
            m = self.zadnja_meritev(p)
            kljuc = bool(self.kljuc(p))
            # stanje: velja / ne_velja / nepreverjen (tudi kljuc brez zapisa stanja); "" = ni kljuca. Nikoli kljuc.
            storitve.append({"id": p, "ime": P.ime(p), "kljuc": kljuc, "kje": P.kje_kljuc(p),
                             "meritev": P.opis_meritve(m) if m else "",
                             "paket": P.ime_paketa(self.paket(p)) if kljuc else "",
                             "stanje": (self.stanje_kljuca(p) or P.STANJE_NEPREVERJEN) if kljuc else ""})
        tb = self.paket(P.TORBOX) if self.kljuc(P.TORBOX) else None
        gost = self.gostitelj_indeksatorja()
        return {"storitve": storitve, "aktivna": self.aktivna() or "", "samo_takoj": self.samo_takoj(),
                "oznaka": P.OZNAKA_PREDPOMNJEN,
                # torbox_pro: None = paketa ne poznamo (kljuc ni bil preverjen) - Usenet ima samo Pro.
                "usenet": {"gostitelj": gost, "torbox": bool(self.kljuc(P.TORBOX)),
                           "torbox_pro": None if tb is None else tb == P.TORBOX_PRO,
                           "stanje": (self.stanje_kljuca(P.INDEKSATOR) or P.STANJE_NEPREVERJEN) if gost else ""}}

    # ---- predvajanje
    def predpomnjeni(self, hashi: Sequence[str]) -> set:
        """Hashi, ki jih ima storitev pripravljene (⚡). Prava preverba je samo pri TorBoxu."""
        vezava = self._vezava(P.TORBOX)
        k = self.kljuc(P.TORBOX)
        if self.aktivna() is None or not k or not self.sme_klicati(P.TORBOX):
            return set()                        # zavrnjen kljuc: ⚡ ob vsakem seznamu virov bi bil nov zavrnjen klic
        # Zavrnjen kljuc ze ob preverbi ⚡ (kot Android TorBox.predpomnjeni): vrstica v »Debrid storitve« pove »ne velja«.
        return torbox_predpomnjeni(k, hashi, ob_napaki=lambda napaka: self.ob_izidu(P.TORBOX, napaka, False, vezava))

    def _napaka_stanja(self, p: str) -> str:
        """Napaka za uporabnika, ko storitve [p] ne klicemo (P.sme_klicati)."""
        return P.NAPAKA_ZAKLENJEN if self.stanje_kljuca(p) == P.STANJE_ZAKLENJEN else P.NAPAKA_KLJUC

    def _poskus(self, p: str, hash_: str, indeks: Optional[int], magnet: str, samo_pred: bool,
                preklic: Optional[threading.Event] = None) -> Izid:
        vezava = self._vezava(p)                # pred kljucem: izid zahteve velja samo za ta kljuc (Grok 36, D2)
        k = self.kljuc(p)
        if not k:
            return Izid(napaka=P.NAPAKA_KLJUC, ponudnik=p)
        if not self.sme_klicati(p):
            return Izid(napaka=self._napaka_stanja(p), ponudnik=p)
        if p == P.TORBOX:
            casi = list(self._nastavitve().get("torbox_novi") or [])
            izid = torbox_tok(k, hash_, indeks, magnet, samo_pred, casi, preklic=preklic)
            zdaj = time.time()
            self._spremeni(lambda d: d.__setitem__("torbox_novi", [c for c in casi if 0 <= zdaj - c < P.URA_S]))
        elif p == P.REAL_DEBRID:
            izid = rd_tok(k, magnet, indeks, samo_pred, preklic=preklic)
        else:
            izid = ad_tok(k, hash_, indeks, samo_pred, preklic=preklic)
        # Lastnik 25. 10. 2026 (kot Android Debrid.obIzidu): stanje kljuca sledi uporabi (401 -> »ne velja«, povezava -> velja).
        _javi(lambda n, u: self.ob_izidu(p, n, u, vezava), izid.napaka, bool(izid.url))
        if izid.napaka == P.NAPAKA_DOVOLJENJE:
            # Grokov pregled 40, S4: RD 9 - potrjen kljuc ostane, uporabnik izve, da racun tega ne omogoca (paket);
            # kljuc, ki ga storitev se ni potrdila, ne velja za to rabo.
            izid = Izid(izid.url, P.NAPAKA_PAKET if self.stanje_kljuca(p) == P.STANJE_VELJA else P.NAPAKA_KLJUC,
                        izid.opis, izid.ponudnik)
        # Izid vedno nosi storitev, ki je odgovorila (sporocilo napake jo imenuje).
        return izid if izid.ponudnik else Izid(izid.url, izid.napaka, izid.opis, p)

    def _zapomni_meritev(self, m: P.Meritev) -> None:
        self._spremeni(lambda d: d.setdefault("meritve", {}).__setitem__(
            m.ponudnik, {"ping_ms": m.ping_ms, "bajtov": m.bajtov, "cas_ms": m.cas_ms, "kdaj": time.time()}))

    def tok(self, hash_: str, indeks: Optional[int] = None, ime_datoteke: str = "", sledilniki: Sequence[str] = (),
            samo_takoj: Optional[bool] = None) -> Izid:
        """Povezava za torrent prek storitev s kljucem. Vec storitev: vse hkrati (samo pripravljeno), med uspesnimi
        izmerimo ping in hitrost do tega racunalnika - predvaja najhitrejsa. Nikoli tiho na neposreden torrent."""
        vsi = self.vrstni_red()
        if not vsi:
            return Izid(napaka=P.NAPAKA_KLJUC)
        # Lastnik 26. 10. 2026 (zaklep racuna): storitve s kljucem »ne velja« ali »zaklenjen« ne klicemo - tudi ob
        # predvajanju ne. Ce ni nobene druge, uporabnik dobi napako (nikoli tiho na neposreden torrent).
        red = [p for p in vsi if self.sme_klicati(p)]
        if not red:
            napake = [(p, self._napaka_stanja(p)) for p in vsi]
            return Izid(napaka=P.razlog_po_storitvah(napake), ponudnik=P.ponudnik_napake(napake))
        h = str(hash_ or "").strip().lower()
        if not P.je_hash(h):
            return Izid(napaka=P.NAPAKA_NI_DATOTEKE)
        mag = P.magnet(h, ime_datoteke, sledilniki)
        samo = self.samo_takoj() if samo_takoj is None else bool(samo_takoj)
        if len(red) >= 2:
            # Vse hkrati, rok VZPOREDNO_ROK_S velja zares (prej je `with ThreadPoolExecutor` ob izhodu cakal na vse niti).
            # Niti, ki zamudijo rok, so preklicane: po odgovoru ne ustvarijo nicesar vec in pospravijo svoje (Grok).
            preklic = threading.Event()
            niti = [(p, v_ozadju(self._poskus, p, h, indeks, mag, True, preklic)) for p in red]
            konec = time.monotonic() + P.VZPOREDNO_ROK_S
            izidi = []
            try:
                for p, f in niti:
                    izid = _izid_do(f, konec)
                    izidi.append((p, izid if isinstance(izid, Izid) else Izid(napaka=P.NAPAKA_STREZNIK, ponudnik=p)))
            finally:
                preklic.set()
        else:
            izidi = [(red[0], self._poskus(red[0], h, indeks, mag, True))]
        uspesni = [(p, i) for p, i in izidi if i.url]
        if len(uspesni) == 1:
            return Izid(url=uspesni[0][1].url, ponudnik=uspesni[0][0])
        if uspesni:
            # Zaporedno, ne hkrati: hkratne meritve bi si delile pasovno sirino.
            meritve = [m for m in (izmeri(p, i.url) for p, i in uspesni) if m]
            for m in meritve:
                self._zapomni_meritev(m)
            _log.info("meritve: %s", ", ".join("%s %s" % (P.ime(m.ponudnik), P.opis_meritve(m)) for m in meritve))
            izbrana = P.najhitrejsa(meritve)
            p, i = next(((p, i) for p, i in uspesni if p == izbrana), uspesni[0])
            return Izid(url=i.url, ponudnik=p)
        po_storitvah = [(p, i.napaka) for p, i in izidi]
        for p, n in po_storitvah:
            _log.info("%s: %s", P.ime(p), n)
        # Grokov pregled 25. 10. 2026: caka prva storitev po vrstnem redu, ki je rekla »ni predpomnjeno« - tudi, ce je
        # prednostna padla na roku ali kljucu (prej je cakala samo prva, in ce je ta padla, ni cakal nihce).
        cakalna = P.cakalna_storitev(samo, po_storitvah)
        if cakalna is not None:
            i = self._poskus(cakalna, h, indeks, mag, False)
            return Izid(i.url, i.napaka, i.opis, cakalna)
        opis = next((P.ime(p) + ": " + i.opis for p, i in reversed(izidi) if i.opis), "")
        return Izid(napaka=P.razlog_po_storitvah(po_storitvah), opis=opis, ponudnik=P.ponudnik_napake(po_storitvah))


def most(dbr: Debrid, a: list) -> dict:
    """Metoda mostu »mediaDebrid« (Linux os_katalog, Windows os_app): [] -> stanje; ["aktivna", p | ""];
    ["kljuc", p, vnos] -> {"ok": bool, "preverba": P.PREVERBA_*, "paket": ime, ...stanje}; ["pozabi", p];
    ["samo_takoj", da]; ["usenet", naslov, kljuc] -> {"ok", "preverba", ...stanje}; ["pozabi_usenet"];
    ["preveri"] -> preverba kljucev brez stanja ali nepreverjenih (okno »Debrid storitve« jo poklice po odprtju) in stanje;
    ["preveri", p | "usenet"] -> uporabnik je pritisnil »Preveri« (edina pot za »ne velja« in »zaklenjen«).
    Vrne stanje brez kljucev (pri Usenetu samo gostitelja indeksatorja). Klic s preverbo je blokirajoc (do 8 s na
    kljuc) - most tece v delovni niti (os_katalog.izvedi)."""
    ukaz = str(a[0]) if a else ""
    izid: dict = {"ok": True}
    if ukaz == "aktivna":
        p = str(a[1]) if len(a) > 1 else ""
        dbr.nastavi_aktivno(p if p in P.VSI else None)
    elif ukaz == "kljuc":
        # Preverba ob vnosu (TorBox user/me, Real-Debrid in AllDebrid /user): vmesnik dobi samo izid in ime paketa -
        # nikoli kljuca, uporabniskega imena ali e-naslova.
        izid = dbr.vpisi_kljuc(str(a[1]), str(a[2])) if len(a) > 2 else {"ok": False, "preverba": P.PREVERBA_OBLIKA}
        izid = dict(izid, paket=P.ime_paketa(izid.get("paket")))
    elif ukaz == "pozabi" and len(a) > 1 and str(a[1]) in P.VSI:
        dbr.pozabi_kljuc(str(a[1]))
    elif ukaz == "samo_takoj":
        dbr.nastavi_samo_takoj(bool(a[1]) if len(a) > 1 else True)
    elif ukaz == "usenet":
        izid = dbr.vpisi_indeksator(str(a[1]), str(a[2])) if len(a) > 2 else {"ok": False, "preverba": P.PREVERBA_OBLIKA}
    elif ukaz == "pozabi_usenet":
        dbr.pozabi_indeksator()
    elif ukaz == "preveri" and len(a) > 1:
        p = str(a[1])
        p = P.INDEKSATOR if p == "usenet" else p
        izid = dbr.preveri_izrecno(p) if p in P.VSI + (P.INDEKSATOR,) else {"ok": False, "preverba": P.PREVERBA_OBLIKA}
    elif ukaz == "preveri":
        dbr.preveri_nepreverjene()
    return dict(dbr.stanje(), ok=bool(izid.get("ok")), preverba=str(izid.get("preverba") or ""),
                paket=str(izid.get("paket") or ""), cez_s=int(izid.get("cez_s") or 0))
