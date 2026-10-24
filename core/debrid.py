"""Naloga 131: debrid storitve (TorBox, Real-Debrid, AllDebrid) - odjemalci in izbira, kot Safeer OS za Android.

Pravila brez omrezja so v core/debrid_pravila.py. Kljuci so v nastavitvah Medijskega centra samo sifrirani (isti
sifrirnik kot gesla streznikov - sistemska zbirka skrivnosti); nikoli v dnevniku ali naslovu. Edina izjema je TorBox
requestdl, ki kljuc zahteva kot parameter `token`: tak naslov se uporabi samo za en klic in se ne zapise nikamor.
Klici so blokirajoci - samo z delovne niti.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from . import debrid_pravila as P

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
    koda: int
    telo: str

    @property
    def json(self):
        try:
            return json.loads(self.telo)
        except ValueError:
            return None

    @property
    def uspeh(self) -> bool:
        return 200 <= self.koda < 300


def klic(naslov: str, kljuc: Optional[str], metoda: str = "GET", obrazec: Optional[list] = None,
         rok: float = 20.0) -> Odgovor:
    """Klic s kljucem v glavi (nikoli v naslovu); [obrazec] gre kot application/x-www-form-urlencoded."""
    glave = {"Accept": "application/json", "User-Agent": "SafeerOS/1.0"}
    if kljuc:
        glave["Authorization"] = P.glava_avtorizacije(kljuc)
    podatki = None
    if obrazec is not None:
        podatki = urllib.parse.urlencode(obrazec).encode("utf-8")
        glave["Content-Type"] = "application/x-www-form-urlencoded"
    zahteva = urllib.request.Request(naslov, data=podatki, headers=glave, method=metoda)
    try:
        with urllib.request.urlopen(zahteva, timeout=rok) as o:
            return Odgovor(o.status, o.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return Odgovor(e.code, (e.read() or b"").decode("utf-8", "replace"))


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
               casi_novih: list, cakaj: Callable[[float], None] = time.sleep) -> Izid:
    """checkcached -> (createtorrent) -> requestdl. Nepredpomnjen: meja 60/uro ([casi_novih] se dopolni) in cakanje do 3 min."""
    try:
        pred = klic(P.TORBOX_OSNOVA + "/checkcached?hash=%s&format=object&list_files=true" % hash_, kljuc)
        if not _tb_uspeh(pred):
            return _tb_napaka(pred)
        vnos = ((pred.json or {}).get("data") or {}).get(hash_) if isinstance((pred.json or {}).get("data"), dict) else None
        predpomnjen = vnos is not None
        if not predpomnjen and samo_predpomnjeno:
            return Izid(napaka=P.NAPAKA_NI_PREDPOMNJENO, ponudnik=P.TORBOX)
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
    except Exception as e:  # noqa: BLE001
        _log.warning("TorBox: %s", type(e).__name__)
        return Izid(napaka=P.NAPAKA_STREZNIK, ponudnik=P.TORBOX)


# ---------------------------------------------------------------------- Real-Debrid

def _rd_napaka(o: Odgovor) -> Izid:
    j = o.json if isinstance(o.json, dict) else {}
    koda = j.get("error_code") if isinstance(j.get("error_code"), int) else None
    return Izid(napaka=P.rd_vrsta_napake(o.koda, koda), opis=str(j.get("error") or "")[:200], ponudnik=P.REAL_DEBRID)


def rd_tok(kljuc: str, magnet: str, indeks: Optional[int], samo_predpomnjeno: bool,
           cakaj: Callable[[float], None] = time.sleep) -> Izid:
    """addMagnet -> info -> selectFiles -> info (»downloaded«) -> unrestrict/link. Ni takoj pripravljen in »samo
    predpomnjeno«: torrent izbrisemo iz uporabnikovega racuna (ne pustimo ga za sabo)."""
    tid = ""

    def izbrisi() -> None:
        try:
            klic(P.RD_OSNOVA + "/torrents/delete/" + tid, kljuc, "DELETE")
        except Exception:  # noqa: BLE001
            pass

    try:
        dodaj = klic(P.RD_OSNOVA + "/torrents/addMagnet", kljuc, "POST", [("magnet", magnet)])
        if not dodaj.uspeh:
            return _rd_napaka(dodaj)
        tid = str((dodaj.json or {}).get("id") or "")
        if not tid:
            return _rd_napaka(dodaj)
        info = klic(P.RD_OSNOVA + "/torrents/info/" + tid, kljuc)
        for _ in range(10):
            j = info.json or {}
            if not info.uspeh or (j.get("files") or []) or P.rd_koncna_napaka(str(j.get("status") or "")):
                break
            cakaj(1.0)
            info = klic(P.RD_OSNOVA + "/torrents/info/" + tid, kljuc)
        if not info.uspeh:
            izbrisi()
            return _rd_napaka(info)
        datoteke = [P.Datoteka(int(f.get("id") or 0), str(f.get("path") or "").rsplit("/", 1)[-1], int(f.get("bytes") or 0))
                    for f in ((info.json or {}).get("files") or []) if isinstance(f, dict)]
        d = P.izberi_datoteko(datoteke, indeks)
        if d is None:
            izbrisi()
            return Izid(napaka=P.NAPAKA_NI_DATOTEKE, ponudnik=P.REAL_DEBRID)
        izberi = klic(P.RD_OSNOVA + "/torrents/selectFiles/" + tid, kljuc, "POST", [("files", str(d.id))])
        if not izberi.uspeh:
            izbrisi()
            return _rd_napaka(izberi)
        rok = 4.0 if samo_predpomnjeno else P.CAKAJ_NOVEGA_S
        korak = 1.0 if samo_predpomnjeno else P.CAKAJ_KORAK_S
        cakano = 0.0
        info = klic(P.RD_OSNOVA + "/torrents/info/" + tid, kljuc)
        while info.uspeh and not P.rd_pripravljen(str((info.json or {}).get("status") or "")) and cakano < rok:
            if P.rd_koncna_napaka(str((info.json or {}).get("status") or "")):
                break
            cakaj(korak)
            cakano += korak
            info = klic(P.RD_OSNOVA + "/torrents/info/" + tid, kljuc)
        stanje = str((info.json or {}).get("status") or "")
        if not P.rd_pripravljen(stanje):
            izbrisi()
            napaka = (P.NAPAKA_NI_DATOTEKE if P.rd_koncna_napaka(stanje)
                      else P.NAPAKA_NI_PREDPOMNJENO if samo_predpomnjeno else P.NAPAKA_PRENASA)
            return Izid(napaka=napaka, ponudnik=P.REAL_DEBRID)
        povezava = next(iter((info.json or {}).get("links") or []), "")
        if not povezava:
            return Izid(napaka=P.NAPAKA_NI_DATOTEKE, ponudnik=P.REAL_DEBRID)
        odklep = klic(P.RD_OSNOVA + "/unrestrict/link", kljuc, "POST", [("link", povezava)])
        url = str((odklep.json or {}).get("download") or "")
        if not odklep.uspeh or not url.startswith("https://"):
            return _rd_napaka(odklep)
        _log.info("Real-Debrid: tok pripravljen")
        return Izid(url=url, ponudnik=P.REAL_DEBRID)
    except Exception as e:  # noqa: BLE001
        _log.warning("Real-Debrid: %s", type(e).__name__)
        return Izid(napaka=P.NAPAKA_STREZNIK, ponudnik=P.REAL_DEBRID)


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


def ad_tok(kljuc: str, hash_: str, indeks: Optional[int], samo_predpomnjeno: bool,
           cakaj: Callable[[float], None] = time.sleep) -> Izid:
    """magnet/upload (`ready`) -> magnet/files -> link/unlock (link ali delayed). Ni pripravljen in »samo
    predpomnjeno«: magnet izbrisemo (magnet/delete)."""
    try:
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
        pripravljen = bool(m.get("ready"))
        if not pripravljen and samo_predpomnjeno:
            try:
                klic(P.AD_OSNOVA + "/magnet/delete", kljuc, "POST", [("id", str(mid))])
            except Exception:  # noqa: BLE001
                pass
            return Izid(napaka=P.NAPAKA_NI_PREDPOMNJENO, ponudnik=P.ALLDEBRID)
        cakano = 0.0
        while not pripravljen and cakano <= P.CAKAJ_NOVEGA_S:
            cakaj(P.CAKAJ_KORAK_S)
            cakano += P.CAKAJ_KORAK_S
            st = klic("https://api.alldebrid.com/v4.1/magnet/status", kljuc, "POST", [("id", str(mid))])
            if not _ad_uspeh(st):
                return _ad_napaka(st)
            d = (st.json or {}).get("data") or {}
            mm = d.get("magnets") if isinstance(d.get("magnets"), dict) else next(iter(d.get("magnets") or []), {})
            koda = int((mm or {}).get("statusCode") or 0)
            if koda >= 5:
                return Izid(napaka=P.NAPAKA_NI_DATOTEKE, ponudnik=P.ALLDEBRID)
            pripravljen = koda == 4
        if not pripravljen:
            return Izid(napaka=P.NAPAKA_PRENASA, ponudnik=P.ALLDEBRID)
        dat = klic(P.AD_OSNOVA + "/magnet/files", kljuc, "POST", [("id[]", str(mid))])
        if not _ad_uspeh(dat):
            return _ad_napaka(dat)
        seznam: list = []
        _ad_razvij((next(iter(((dat.json or {}).get("data") or {}).get("magnets") or []), {}) or {}).get("files"), seznam)
        d = P.izberi_datoteko([s[0] for s in seznam], indeks)
        if d is None:
            return Izid(napaka=P.NAPAKA_NI_DATOTEKE, ponudnik=P.ALLDEBRID)
        odklep = klic(P.AD_OSNOVA + "/link/unlock", kljuc, "POST", [("link", seznam[d.id][1])])
        if not _ad_uspeh(odklep):
            return _ad_napaka(odklep)
        data = (odklep.json or {}).get("data") or {}
        url = str(data.get("link") or "")
        zamik = data.get("delayed")
        for _ in range(30):
            if url or not zamik:
                break
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
    except Exception as e:  # noqa: BLE001
        _log.warning("AllDebrid: %s", type(e).__name__)
        return Izid(napaka=P.NAPAKA_STREZNIK, ponudnik=P.ALLDEBRID)


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
                "oznaka": P.OZNAKA_PREDPOMNJEN}

    # ---- predvajanje
    def predpomnjeni(self, hashi: Sequence[str]) -> set:
        """Hashi, ki jih ima storitev pripravljene (⚡). Prava preverba je samo pri TorBoxu."""
        k = self.kljuc(P.TORBOX)
        if self.aktivna() is None or not k:
            return set()
        return torbox_predpomnjeni(k, hashi)

    def _poskus(self, p: str, hash_: str, indeks: Optional[int], magnet: str, samo_pred: bool) -> Izid:
        k = self.kljuc(p)
        if not k:
            return Izid(napaka=P.NAPAKA_KLJUC, ponudnik=p)
        if p == P.TORBOX:
            casi = list(self._nastavitve().get("torbox_novi") or [])
            izid = torbox_tok(k, hash_, indeks, magnet, samo_pred, casi)
            zdaj = time.time()
            self._spremeni(lambda d: d.__setitem__("torbox_novi", [c for c in casi if 0 <= zdaj - c < P.URA_S]))
            return izid
        if p == P.REAL_DEBRID:
            return rd_tok(k, magnet, indeks, samo_pred)
        return ad_tok(k, hash_, indeks, samo_pred)

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
            with ThreadPoolExecutor(max_workers=len(red)) as bazen:
                niti = [(p, bazen.submit(self._poskus, p, h, indeks, mag, True)) for p in red]
                konec = time.monotonic() + P.VZPOREDNO_ROK_S
                izidi = []
                for p, f in niti:
                    try:
                        izidi.append((p, f.result(timeout=max(0.01, konec - time.monotonic()))))
                    except Exception:  # noqa: BLE001 - kar ne odgovori v roku, ne steje
                        izidi.append((p, Izid(napaka=P.NAPAKA_STREZNIK, ponudnik=p)))
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
        napake = [i.napaka for _, i in izidi]
        if P.poskusi_s_cakanjem(samo, napake):
            p = red[0]
            i = self._poskus(p, h, indeks, mag, False)
            return Izid(i.url, i.napaka, i.opis, p)
        opis = next((P.ime(p) + ": " + i.opis for p, i in reversed(izidi) if i.opis), "")
        return Izid(napaka=P.razlog_za_uporabnika(napake), opis=opis)


def most(dbr: Debrid, a: list) -> dict:
    """Metoda mostu »mediaDebrid« (Linux os_katalog, Windows os_app): [] -> stanje; ["aktivna", p | ""];
    ["kljuc", p, vnos] -> {"ok": bool, ...stanje}; ["pozabi", p]; ["samo_takoj", da]. Vrne stanje brez kljucev."""
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
    return dict(dbr.stanje(), ok=bool(ok))
