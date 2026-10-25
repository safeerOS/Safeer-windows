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
from concurrent.futures import Future
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


def klic(naslov: str, kljuc: Optional[str], metoda: str = "GET", obrazec: Optional[list] = None,
         rok: float = 20.0, telo: Optional[tuple] = None) -> Odgovor:
    """Klic s kljucem v glavi (nikoli v naslovu); [obrazec] gre kot application/x-www-form-urlencoded, [telo] je
    (bajti, Content-Type) - npr. multipart z NZB za Usenet. Odgovor najvec P.NAJVEC_ODGOVORA bajtov (vecji je napaka)."""
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
        with urllib.request.urlopen(zahteva, timeout=rok) as o:
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


def torbox_predpomnjeni(kljuc: str, hashi: Sequence[str], rok: float = 4.0) -> set:
    """Kateri hashi so pri TorBoxu ze pripravljeni: en klic checkcached (do 100), nic ne doda v racun. Ob napaki prazno."""
    h = P.hashi_za_preverbo(hashi)
    if not h:
        return set()
    try:
        o = klic(P.torbox_naslov_predpomnjenih(h), kljuc, rok=rok)
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
    return Izid(napaka=P.rd_vrsta_napake(o.koda, koda), opis=str(j.get("error") or "")[:200], ponudnik=P.REAL_DEBRID)


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


def usenet_isci(osn: str, kljuc_ix: str, ident: str, rok: float = 8.0) -> list:
    """Zadetki indeksatorja za id Stremio (film tt… ali epizoda tt…:S:E); ob napaki prazno. Naslov (s kljucem) ne gre v dnevnik."""
    naslov = U.naslov_iskanja(osn, kljuc_ix, ident)
    if not naslov:
        return []
    try:
        zahteva = urllib.request.Request(naslov, headers={"Accept": "application/rss+xml, application/xml, text/xml",
                                                          "User-Agent": "SafeerOS/1.0"})
        try:
            with urllib.request.urlopen(zahteva, timeout=rok) as o:
                koda, telo = o.status, _beri_do(o, U.NAJVEC_ODGOVORA_BAJTOV)
        except urllib.error.HTTPError as e:
            koda, telo = e.code, _beri_do(e, 64 * 1024) if e.fp else b""
        besedilo = telo.decode("utf-8", "replace")
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


def usenet_nzb(povezava: str, rok: float = 30.0) -> tuple:
    """NZB z indeksatorja: (bajti, "") ali (None, napaka). Povezava vsebuje kljuc - ne gre v dnevnik."""
    try:
        zahteva = urllib.request.Request(povezava, headers={"User-Agent": "SafeerOS/1.0"})
        try:
            with urllib.request.urlopen(zahteva, timeout=rok) as o:
                koda, telo = o.status, _beri_do(o, U.NAJVEC_NZB_BAJTOV + 1)
        except urllib.error.HTTPError as e:
            koda, telo = e.code, _beri_do(e, 64 * 1024) if e.fp else b""
        if len(telo) > U.NAJVEC_NZB_BAJTOV:
            return None, U.NAPAKA_INDEKSATOR
        zacetek = telo[:4096].decode("utf-8", "replace")
        if 200 <= koda < 300 and U.je_nzb(zacetek):
            return telo, ""
        n = U.napaka(zacetek) or (P.NAPAKA_KLJUC if koda in (401, 403) else P.NAPAKA_MEJA if koda == 429 else U.NAPAKA_INDEKSATOR)
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

class Debrid:
    """Kljuci, nastavitve in izbira storitve. [beri]/[pisi] berejo in zapisejo razdelek »debrid« nastavitev Medijskega
    centra; [sifriraj]/[desifriraj] sta sifrirnik gesel streznikov (sistemska zbirka skrivnosti)."""

    def __init__(self, beri: Callable[[], dict], pisi: Callable[[dict], None],
                 sifriraj: Callable[[str], str], desifriraj: Callable[[str], str]):
        self._beri, self._pisi = beri, pisi
        self._sifriraj, self._desifriraj = sifriraj, desifriraj
        self._zaklep = threading.Lock()
        self._kljuci: dict = {}          # predpomnilnik desifriranih kljucev (samo v pomnilniku)
        self._povezave_nzb: dict = {}    # id toka »usenet:…« -> povezava NZB s kljucem (samo v pomnilniku)
        # Zadnji prenesen NZB (id toka -> (cas, bajti)): preverba »pripravljen« in nato poskus s cakanjem za isto izdajo
        # ne preneseta NZB dvakrat (indeksatorji stejejo prenose NZB na dan).
        self._nzb: "OrderedDict[str, tuple]" = OrderedDict()

    def _nastavitve(self) -> dict:
        d = self._beri()
        return d if isinstance(d, dict) else {}

    def _spremeni(self, fn: Callable[[dict], None]) -> None:
        with self._zaklep:
            d = dict(self._nastavitve())
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

    def nastavi_kljuc(self, p: str, vnos: str) -> bool:
        k = P.ocisti_kljuc(vnos)
        if p not in P.VSI or k is None:
            return False
        enc = self._sifriraj(k)
        if not enc:
            return False
        self._spremeni(lambda d: d.setdefault("kljuci", {}).__setitem__(p, enc))
        return True

    def pozabi_kljuc(self, p: str) -> None:
        self._spremeni(lambda d: (d.setdefault("kljuci", {}).pop(p, None), d.setdefault("meritve", {}).pop(p, None)))

    # ---- Usenet: uporabnikov indeksator Newznab (naslov in kljuc samo sifrirana, kot kljuci storitev)
    def indeksator(self) -> Optional[tuple]:
        """(osnova, kljuc) ali None. Naslov je lahko zaseben (streznik v domacem omrezju), zato je tudi sifriran."""
        u = self._nastavitve().get("usenet") or {}
        if not isinstance(u, dict) or not u.get("url") or not u.get("kljuc"):
            return None
        try:
            osn = U.osnova(self._desifriraj(str(u["url"])))
            k = U.ocisti_kljuc(self._desifriraj(str(u["kljuc"])))
        except Exception:  # noqa: BLE001 - zapisa ni mogoce prebrati: kot da ga ni
            return None
        return (osn, k) if osn and k else None

    def nastavi_indeksator(self, naslov: str, kljuc: str) -> bool:
        osn, k = U.osnova(naslov), U.ocisti_kljuc(kljuc)
        if not osn or not k:
            return False
        enc_u, enc_k = self._sifriraj(osn), self._sifriraj(k)
        if not enc_u or not enc_k:
            return False
        self._spremeni(lambda d: d.__setitem__("usenet", {"url": enc_u, "kljuc": enc_k}))
        return True

    def pozabi_indeksator(self) -> None:
        self._spremeni(lambda d: d.pop("usenet", None))

    def gostitelj_indeksatorja(self) -> str:
        ix = self.indeksator()
        return (urllib.parse.urlsplit(ix[0]).hostname or "") if ix else ""

    def usenet_na_voljo(self) -> bool:
        """Indeksator, kljuc TorBox (prenese in pretaka TorBox) in uporabnik ni izbral »Brez debrida«."""
        return self.indeksator() is not None and bool(self.kljuc(P.TORBOX)) and self.aktivna() is not None

    def usenet_isci(self, ident: str) -> list:
        """Tokovi Usenet za id Stremio: [{"url": "usenet:…", "opis": …, "gb": …}]. Povezave NZB ostanejo v pomnilniku."""
        ix = self.indeksator()
        if not ix or not self.usenet_na_voljo() or not U.iscemo(ident):
            return []
        tokovi = []
        for z in usenet_isci(ix[0], ix[1], ident):
            idt = U.id_toka(z.povezava)
            with self._zaklep:
                self._povezave_nzb[idt] = z.povezava
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

    def usenet_tok(self, id_toka: str, ime_izdaje: str, indeks: Optional[int] = None,
                   samo_takoj: bool = False, rok_cakanja: float = U.CAKAJ_PRENOSA_S,
                   preklic: Optional[threading.Event] = None) -> Izid:
        """NZB od indeksatorja (ta racunalnik), nato TorBox. Napaka indeksatorja je U.NAPAKA_INDEKSATOR."""
        k = self.kljuc(P.TORBOX)
        if not k:
            return Izid(napaka=P.NAPAKA_KLJUC, ponudnik=P.TORBOX)
        with self._zaklep:
            povezava = self._povezave_nzb.get(id_toka)
        if not povezava:
            return Izid(napaka=U.NAPAKA_INDEKSATOR, ponudnik=P.TORBOX)
        nzb = self._nzb_zapomnjen(id_toka)
        if nzb is None:
            nzb, _napaka = usenet_nzb(povezava)
            if nzb is None:
                return Izid(napaka=U.NAPAKA_INDEKSATOR, ponudnik=P.TORBOX)
            self._zapomni_nzb(id_toka, nzb)
        return torbox_usenet(k, nzb, ime_izdaje, indeks, samo_takoj, rok_cakanja=rok_cakanja, preklic=preklic)

    def usenet_takoj(self, tokovi: Sequence[dict], rok: float = U.TAKOJ_ROK_S) -> Optional[tuple]:
        """Lastnik 25. 10. 2026: Usenet, ki ga ima TorBox ze pripravljenega, gre pred vse druge vire. Prve U.TAKOJ_IZDAJ izdaj
        [tokovi] (po kakovosti, najboljsa prva) preverimo hkrati (add_only_if_cached) z rokom [rok]; zmaga najboljsa
        pripravljena. Vrne (indeks v [tokovi], Izid) ali None. Kar zamudi rok, ne doda nicesar (preklic)."""
        izbrani = U.za_takojsnjo([float(t.get("gb") or 0.0) for t in tokovi])
        if not izbrani:
            return None
        konec = time.monotonic() + max(0.1, rok)
        preklic = threading.Event()
        niti = [(i, v_ozadju(self.usenet_tok, str(tokovi[i].get("url") or ""), str(tokovi[i].get("naslov") or ""),
                             None, True, P.CAKAJ_NOVEGA_S, preklic)) for i in izbrani]
        try:
            pripravljene = []
            for _i, f in niti:
                izid = _izid_do(f, konec)
                pripravljene.append(izid if isinstance(izid, Izid) and izid.url else None)
                if pripravljene[-1] is not None:
                    break           # najboljsa pripravljena po kakovosti: slabsih ne cakamo
        finally:
            preklic.set()
        k = U.najboljsa_pripravljena([x is not None for x in pripravljene])
        _log.info("usenet takoj: %s", "izdaja %d pripravljena" % k if k >= 0 else "nobena pripravljena")
        return (izbrani[k], pripravljene[k]) if k >= 0 else None

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
            storitve.append({"id": p, "ime": P.ime(p), "kljuc": bool(self.kljuc(p)), "kje": P.kje_kljuc(p),
                             "meritev": P.opis_meritve(m) if m else ""})
        return {"storitve": storitve, "aktivna": self.aktivna() or "", "samo_takoj": self.samo_takoj(),
                "oznaka": P.OZNAKA_PREDPOMNJEN,
                "usenet": {"gostitelj": self.gostitelj_indeksatorja(), "torbox": bool(self.kljuc(P.TORBOX))}}

    # ---- predvajanje
    def predpomnjeni(self, hashi: Sequence[str]) -> set:
        """Hashi, ki jih ima storitev pripravljene (⚡). Prava preverba je samo pri TorBoxu."""
        k = self.kljuc(P.TORBOX)
        if self.aktivna() is None or not k:
            return set()
        return torbox_predpomnjeni(k, hashi)

    def _poskus(self, p: str, hash_: str, indeks: Optional[int], magnet: str, samo_pred: bool,
                preklic: Optional[threading.Event] = None) -> Izid:
        k = self.kljuc(p)
        if not k:
            return Izid(napaka=P.NAPAKA_KLJUC, ponudnik=p)
        if p == P.TORBOX:
            casi = list(self._nastavitve().get("torbox_novi") or [])
            izid = torbox_tok(k, hash_, indeks, magnet, samo_pred, casi, preklic=preklic)
            zdaj = time.time()
            self._spremeni(lambda d: d.__setitem__("torbox_novi", [c for c in casi if 0 <= zdaj - c < P.URA_S]))
        elif p == P.REAL_DEBRID:
            izid = rd_tok(k, magnet, indeks, samo_pred, preklic=preklic)
        else:
            izid = ad_tok(k, hash_, indeks, samo_pred, preklic=preklic)
        # Izid vedno nosi storitev, ki je odgovorila (sporocilo napake jo imenuje).
        return izid if izid.ponudnik else Izid(izid.url, izid.napaka, izid.opis, p)

    def _zapomni_meritev(self, m: P.Meritev) -> None:
        self._spremeni(lambda d: d.setdefault("meritve", {}).__setitem__(
            m.ponudnik, {"ping_ms": m.ping_ms, "bajtov": m.bajtov, "cas_ms": m.cas_ms, "kdaj": time.time()}))

    def tok(self, hash_: str, indeks: Optional[int] = None, ime_datoteke: str = "", sledilniki: Sequence[str] = (),
            samo_takoj: Optional[bool] = None) -> Izid:
        """Povezava za torrent prek storitev s kljucem. Vec storitev: vse hkrati (samo pripravljeno), med uspesnimi
        izmerimo ping in hitrost do tega racunalnika - predvaja najhitrejsa. Nikoli tiho na neposreden torrent."""
        red = self.vrstni_red()
        if not red:
            return Izid(napaka=P.NAPAKA_KLJUC)
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
    ["kljuc", p, vnos] -> {"ok": bool, ...stanje}; ["pozabi", p]; ["samo_takoj", da]; ["usenet", naslov, kljuc];
    ["pozabi_usenet"]. Vrne stanje brez kljucev (pri Usenetu samo gostitelja indeksatorja)."""
    ukaz = str(a[0]) if a else ""
    ok = True
    if ukaz == "aktivna":
        p = str(a[1]) if len(a) > 1 else ""
        dbr.nastavi_aktivno(p if p in P.VSI else None)
    elif ukaz == "kljuc":
        ok = len(a) > 2 and dbr.nastavi_kljuc(str(a[1]), str(a[2]))
    elif ukaz == "pozabi" and len(a) > 1 and str(a[1]) in P.VSI:
        dbr.pozabi_kljuc(str(a[1]))
    elif ukaz == "samo_takoj":
        dbr.nastavi_samo_takoj(bool(a[1]) if len(a) > 1 else True)
    elif ukaz == "usenet":
        ok = len(a) > 2 and dbr.nastavi_indeksator(str(a[1]), str(a[2]))
    elif ukaz == "pozabi_usenet":
        dbr.pozabi_indeksator()
    return dict(dbr.stanje(), ok=bool(ok))
