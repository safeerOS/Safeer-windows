"""Knjiznica kroga na racunalniku: polica »Na tvojih napravah« v Medijskem centru Safeer OS za Linux in Windows.

Kar je katera koli naprava v Safeer Linku prenesla iz torrenta (racunalnik, telefon, tablica, televizor), se na vseh
napravah pokaze kot polica s plakati; predvaja naprava, ki film hrani. Safeer OS za Android to zna od 0.5.43
(os/KnjiznicaKroga.kt) - tu je isti del za racunalnik, da med napravami ni razlik. Modul je skupen za Linux in Windows
in ne pozna ne okna ne Linka: naprave, ukaze in predvajanje dobi kot funkcije.

Pravila (ista kot na Androidu):
  * zasebnega naslova ni na polici nikjer; racunalnik si ga zapomni brez naslova in plakata (samo oznaka);
  * kadar ne vemo, ali je dodatek zaseben (manifesta ni bilo mogoce prebrati), velja kot zaseben;
  * vnos brez naslova (prenesen pred to razlicico ali za starejso napravo) se ne pokaze;
  * isti film pri vec napravah je en vnos: prednost ima ta racunalnik, nato drugi racunalniki, nato naprave.

Protokol Linka: `magnet.list` (vnosi s `title`, `poster`, `kind`, `ref`, `keep`), `magnet.stream` (`server`, `path`,
`subs`), `magnet.remove`, `magnet.keep` - glej core/link_datoteke.py.

»Obdrži« (krog 85): prenos, ki ga uporabnik oznaci, ne potece po 48 urah; odstrani ga samo on. Oznako hrani naprava,
ki film hrani. Naprava, ki `magnet.keep` ne pozna (starejsa razlicica), v `magnet.list` ne poslje polja `keep` - pri
njej moznosti ne ponudimo.
"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Callable, Dict, List, Optional

from core import link_datoteke

_HASH = re.compile(r"[0-9a-fA-F]{40}")
_BTIH = re.compile(r"btih:([0-9a-fA-F]{40})")

#: Najvec toliko vnosov na polici.
NAJVEC_NA_POLICI = 60
#: Toliko casa cakamo na sezname naprav (naprava, ki ne odgovori, police ne zadrzuje).
CAKANJE_SEZNAMA_S = 4.0
#: Najdlje toliko casa cakamo, da naprava pripravi tok (branje torrenta na pomocniku traja).
CAKANJE_TOKA_S = 150.0
RAZMIK_TOKA_S = 0.7
#: Oznaka naprave za prenose motorja Safeer OS na tem racunalniku.
TUKAJ = "tukaj"
#: Najvec toliko podnapisov vzamemo od naprave, ki film pretaka.
NAJVEC_PODNAPISOV = 12


def hash_magneta(uri: str) -> str:
    m = _BTIH.search(str(uri or ""))
    return m.group(1).lower() if m else ""


# ---------------------------------------------------------------------------------------------- opis lastnih prenosov

def opis_vnosa(item: dict, zaseben: Optional[bool]) -> dict:
    """Kaj si racunalnik zapomni o filmu, ki ga je zaradi gledanja prenesel sam: naslov in plakat iz dodatka ali -
    pri zasebnem dodatku (ali kadar tega ne vemo) - samo oznako, da je zaseben."""
    if zaseben is not False:
        return {"private": True}
    naslov = str(item.get("naslov") or "").strip()
    sezona, epizoda = int(item.get("sezona") or 0), int(item.get("epizoda") or 0)
    serija = str(item.get("vrsta") or "") == "serija"
    if serija and sezona and epizoda and not re.search(r"(?i)\bS\d{1,2}\s*E\d{1,3}\b", naslov):
        naslov = ("%s S%02dE%02d" % (naslov, sezona, epizoda)).strip()
    plakat = str(item.get("slika") or "").strip()
    return {"title": naslov[:200], "poster": plakat[:600] if plakat.startswith("https://") else "",
            "kind": "series" if serija else "movie", "ref": str(item.get("id") or "")[:400], "private": False}


def pot_opisov(pot_rabe: Optional[str] = None) -> str:
    """Opisi prenosov motorja Safeer OS stojijo ob zapisu rabe (raba-gledanje.json) - loceno od opisov Controla."""
    if pot_rabe is None:
        from core import os_torrent_tok
        pot_rabe = os_torrent_tok.pot_rabe()
    return os.path.join(os.path.dirname(pot_rabe), "opisi-gledanje.json") if pot_rabe else ""


def zabelezi(hash_: str, opis: Optional[dict], datoteka: Optional[int] = None, pot: Optional[str] = None) -> None:
    """Zapomni si opis prenosa zaradi gledanja. Kar je enkrat zasebno, ostane zasebno."""
    pot = pot_opisov() if pot is None else pot
    if not pot or not opis or not _HASH.fullmatch(str(hash_ or "")):
        return
    with link_datoteke._RABA_ZAKLEP:
        opisi = link_datoteke._beri_opise(pot)
        vnos = dict(opisi.get(hash_.lower()) or {})
        drzimo = bool(vnos.get("keep"))
        if opis.get("private") or vnos.get("private"):
            vnos = {"private": True}
        else:
            for k in ("title", "poster", "kind", "ref"):
                if opis.get(k):
                    vnos[k] = opis[k]
            vnos["private"] = False
            if isinstance(datoteka, int) and not isinstance(datoteka, bool) and datoteka >= 0:
                vnos["file"] = datoteka
        if drzimo:
            vnos["keep"] = True
        opisi[hash_.lower()] = vnos
        link_datoteke._pisi_rabo(pot, opisi)


def nastavi_obdrzi(hash_: str, obdrzi: bool, pot: Optional[str] = None) -> bool:
    """»Obdrži« za prenos motorja Safeer OS na tem racunalniku (tudi na zahtevo naprave, `magnet.keep` prek Controla)."""
    pot = pot_opisov() if pot is None else pot
    return link_datoteke.nastavi_obdrzi(pot, hash_, bool(obdrzi))


def pozabi(hash_: str, pot: Optional[str] = None, pot_rabe: Optional[str] = None) -> None:
    """Prenos je odstranjen: zapis o opisu in o rabi ne ostaja."""
    hash_ = str(hash_ or "").lower()
    pot = pot_opisov(pot_rabe) if pot is None else pot
    with link_datoteke._RABA_ZAKLEP:
        if pot:
            opisi = link_datoteke._beri_opise(pot)
            if opisi.pop(hash_, None) is not None:
                link_datoteke._pisi_rabo(pot, opisi)
        if pot_rabe:
            raba = link_datoteke._beri_rabo(pot_rabe)
            if raba.pop(hash_, None) is not None:
                link_datoteke._pisi_rabo(pot_rabe, raba)


def lokalni(pot_rabe: Optional[str] = None, pot: Optional[str] = None, mape_stanja=None) -> List[dict]:
    """Prenosi zaradi gledanja na tem racunalniku (motor Safeer OS) v obliki vnosov `magnet.list`.

    Motorja zaradi police ne zaganjamo: seznam je iz zapisa rabe in opisov, ali je film ze v celoti na disku, pove
    stanje motorja na disku (link_datoteke.ze_preneseno). Zasebnih in tistih brez naslova ni; opisi prenosov, ki jih
    ni vec med zapisi rabe (odstranjeni ali obdrzani kot uporabnikov torrent), se pobrisejo."""
    if pot_rabe is None:
        from core import os_torrent_tok
        pot_rabe = os_torrent_tok.pot_rabe()
    pot = pot_opisov(pot_rabe) if pot is None else pot
    raba = link_datoteke._beri_rabo(pot_rabe) if pot_rabe else {}
    opisi = link_datoteke._beri_opise(pot) if pot else {}
    odvec = [h for h in opisi if h not in raba]
    if odvec and pot:
        with link_datoteke._RABA_ZAKLEP:
            sveze = link_datoteke._beri_opise(pot)
            for h in odvec:
                sveze.pop(h, None)
            link_datoteke._pisi_rabo(pot, sveze)
    izid = []
    for h, cas in sorted(raba.items(), key=lambda p: -p[1]):
        opis = opisi.get(h) or {}
        if opis.get("private") or not opis.get("title"):
            continue
        datoteka = opis.get("file") if isinstance(opis.get("file"), int) else None
        try:
            na_disku, indeks = link_datoteke.ze_preneseno(h, datoteka, mape_stanja)
        except Exception:  # noqa: BLE001
            na_disku, indeks = "", -1
        vnos = {"hash": h, "magnet": "magnet:?xt=urn:btih:" + h, "file": indeks if na_disku else datoteka,
                "finished": bool(na_disku), "size": os.path.getsize(na_disku) if na_disku else 0,
                "name": os.path.basename(na_disku) if na_disku else "", "keep": bool(opis.get("keep"))}
        vnos.update({k: opis[k] for k in ("title", "poster", "kind", "ref") if opis.get(k)})
        izid.append(vnos)
    return izid


# ---------------------------------------------------------------------------------------------- polica

def _zna_seznam(naprava: dict) -> bool:
    """Naprava, ki zna `magnet.list`: Safeer OS za Android z zmoznostjo "torrent" ali racunalnik (Control) z "magnet"."""
    zmoznosti = naprava.get("zmoznosti") or naprava.get("capabilities") or []
    if "remote" not in zmoznosti:
        return False
    return "torrent" in zmoznosti or (_je_racunalnik(naprava) and "magnet" in zmoznosti)


def _je_racunalnik(naprava: dict) -> bool:
    return str(naprava.get("vrsta") or "") == "control" or str(naprava.get("platforma") or "") in ("linux", "windows")


def polica(tukaj: List[dict], naprave: List[dict]) -> List[dict]:
    """Zdruzi prenose tega racunalnika in drugih naprav v vnose police (brez dvojnikov, zasebnih in brez naslova).

    `naprave`: [{"id", "ime", "racunalnik", "ta", "items"}] - `items` kot jih vrne `magnet.list`.
    Vnos police: {"kljuc", "naslov", "slika", "vrsta", "naprava": {"id", "ime", "tukaj"}, "velikost", "koncano",
    "obdrzi" (True/False; None = naprava »Obdrži« ne pozna), + za predvajanje in odstranitev: "magnet", "datoteka",
    "id", "ref"}."""
    viri = [{"id": TUKAJ, "ime": "", "racunalnik": True, "ta": True, "items": tukaj or []}]
    viri += sorted([n for n in naprave or [] if isinstance(n, dict)],
                   key=lambda n: (not n.get("ta"), not n.get("racunalnik")))
    videni: set = set()
    izid: List[dict] = []
    for vir in viri:
        for x in vir.get("items") or []:
            if not isinstance(x, dict) or x.get("private") is True:
                continue
            naslov = str(x.get("title") or "").strip()
            magnet = str(x.get("magnet") or "")
            h = str(x.get("hash") or "").lower() or hash_magneta(magnet)
            if not naslov or not _HASH.fullmatch(h) or h in videni:
                continue
            videni.add(h)
            plakat = str(x.get("poster") or "")
            datoteka = x.get("file")
            tid = x.get("id")
            izid.append({
                "kljuc": h, "naslov": naslov[:200], "slika": plakat if plakat.startswith("https://") else "",
                "vrsta": "serija" if x.get("kind") == "series" else "film",
                "naprava": {"id": str(vir.get("id") or ""), "ime": str(vir.get("ime") or ""),
                            "tukaj": bool(vir.get("ta"))},
                "velikost": int(x.get("size") or 0), "koncano": bool(x.get("finished")),
                "obdrzi": bool(x.get("keep")) if isinstance(x.get("keep"), bool) else None,
                "magnet": magnet or "magnet:?xt=urn:btih:" + h,
                "datoteka": datoteka if isinstance(datoteka, int) and not isinstance(datoteka, bool) else None,
                "id": tid if isinstance(tid, int) and not isinstance(tid, bool) else None,
                "ref": str(x.get("ref") or "")[:400]})
            if len(izid) >= NAJVEC_NA_POLICI:
                return izid
    return izid


class Knjiznica:
    """Polica na racunalniku: zbere prenose, predvaja z naprave, ki film hrani, in prenos odstrani.

    naprave() -> [{"id", "ime", "zmoznosti", "vrsta", "platforma", "ta"}]      naprave v Safeer Linku (tudi ta racunalnik)
    ukaz(id, dejanje, parametri, cas) -> {"ok", "data", "koda", "message"}     ukaz napravi s cakanjem na odgovor
    lokalni() -> vnosi motorja Safeer OS na tem racunalniku (privzeto [lokalni]).
    """

    def __init__(self, naprave: Callable[[], List[dict]], ukaz: Callable[[str, str, dict, float], dict],
                 lokalni: Optional[Callable[[], List[dict]]] = None, spanec: Callable[[float], None] = time.sleep) -> None:
        self._naprave = naprave
        self._ukaz = ukaz
        self._lokalni = lokalni or globals()["lokalni"]
        self._spanec = spanec
        self._zaklep = threading.Lock()
        self._vnosi: Dict[str, dict] = {}

    def seznam(self) -> List[dict]:
        """Vnosi police (klic iz delovne niti: naprave vprasa hkrati in caka najvec [CAKANJE_SEZNAMA_S])."""
        try:
            tukaj = self._lokalni()
        except Exception:  # noqa: BLE001
            tukaj = []
        try:
            kandidati = [n for n in self._naprave() or [] if isinstance(n, dict) and n.get("id") and _zna_seznam(n)]
        except Exception:  # noqa: BLE001
            kandidati = []
        odgovori: Dict[str, list] = {}

        def vprasaj(n: dict) -> None:
            try:
                r = self._ukaz(str(n["id"]), "magnet.list", {}, CAKANJE_SEZNAMA_S)
            except Exception:  # noqa: BLE001
                return
            d = r.get("data") if isinstance(r, dict) and r.get("ok") and isinstance(r.get("data"), dict) else None
            if d and isinstance(d.get("items"), list):
                odgovori[str(n["id"])] = d["items"]
        niti = [threading.Thread(target=vprasaj, args=(n,), name="safeer-knjiznica", daemon=True) for n in kandidati[:16]]
        for t in niti:
            t.start()
        rok = time.monotonic() + CAKANJE_SEZNAMA_S + 0.5
        for t in niti:
            t.join(max(0.0, rok - time.monotonic()))
        naprave = [{"id": str(n["id"]), "ime": str(n.get("ime") or ""), "racunalnik": _je_racunalnik(n),
                    "ta": bool(n.get("ta")), "items": odgovori.get(str(n["id"])) or []} for n in kandidati]
        vnosi = polica(tukaj, naprave)
        with self._zaklep:
            self._vnosi = {v["kljuc"]: v for v in vnosi}
        # Stran dobi samo, kar pokaze: magnet povezave in oznake prenosov ostanejo tukaj.
        return [{k: v[k] for k in ("kljuc", "naslov", "slika", "vrsta", "naprava", "velikost", "koncano", "obdrzi")}
                for v in vnosi]

    def vnos(self, kljuc: str) -> Optional[dict]:
        with self._zaklep:
            v = self._vnosi.get(str(kljuc or "").lower())
            return dict(v) if v else None

    def tok_z_naprave(self, v: dict) -> dict:
        """Naprava, ki film hrani, ga pretaka sem: vrne {"server", "path", "name"} (za core/link_pretok.vir_toka) ali
        {"koda": ...}. Android odgovori najprej `pending` - vprasamo znova, dokler tok ni pripravljen."""
        id_naprave = str(v["naprava"]["id"])
        parametri = {"uri": v["magnet"], "title": v["naslov"]}
        if v.get("datoteka") is not None:
            parametri["file"] = v["datoteka"]
        if v.get("slika"):
            parametri["poster"] = v["slika"]
        parametri["kind"] = "series" if v.get("vrsta") == "serija" else "movie"
        if v.get("ref"):
            parametri["ref"] = v["ref"]
        rok = time.monotonic() + CAKANJE_TOKA_S
        while True:
            try:
                r = self._ukaz(id_naprave, "magnet.stream", parametri, 20.0)
            except Exception:  # noqa: BLE001
                r = {"ok": False, "koda": "napaka"}
            r = r if isinstance(r, dict) else {}
            d = r.get("data") if isinstance(r.get("data"), dict) else {}
            if r.get("ok") and isinstance(d.get("server"), dict) and d.get("path"):
                return {"server": d["server"], "path": str(d["path"]), "name": str(d.get("name") or ""),
                        "subs": [{"path": str(p.get("path") or ""), "name": str(p.get("name") or "")[:200]}
                                 for p in (d.get("subs") if isinstance(d.get("subs"), list) else [])[:NAJVEC_PODNAPISOV]
                                 if isinstance(p, dict) and p.get("path")]}
            koda = str(r.get("koda") or r.get("code") or "")
            caka = (r.get("ok") and d.get("pending")) or (not r.get("ok") and koda == "cas")
            if not caka or time.monotonic() >= rok:
                return {"koda": koda or "napaka"}
            self._spanec(RAZMIK_TOKA_S)

    def predvajaj(self, kljuc: str) -> dict:
        """Kaj naj klicatelj predvaja: prenos motorja Safeer OS -> {"ok": True, "tukaj": vnos} (prek kataloga, naravnost
        iz torrenta); film na drugi napravi -> {"ok": True, "vnos": vnos, "tok": {"server", "path", "name"}} (skozi
        lokalni pretok, core/link_pretok.vir_toka); sicer {"ok": False, "koda": ...}."""
        v = self.vnos(kljuc)
        if v is None:
            return {"ok": False, "koda": "ni_prenosa"}
        if v["naprava"]["id"] == TUKAJ:
            return {"ok": True, "tukaj": v}
        tok = self.tok_z_naprave(v)
        if "koda" in tok:
            return {"ok": False, "koda": tok["koda"]}
        return {"ok": True, "vnos": v, "tok": tok}

    def obdrzi(self, kljuc: str, obdrzi: bool, obdrzi_tukaj: Optional[Callable[[str, bool], bool]] = None) -> bool:
        """»Obdrži« (ali ne vec): oznako nastavi naprava, ki film hrani. False, ce je ne pozna ali ne odgovori."""
        v = self.vnos(kljuc)
        if v is None or v.get("obdrzi") is None:
            return False
        if v["naprava"]["id"] == TUKAJ:
            ok = bool((obdrzi_tukaj or nastavi_obdrzi)(v["kljuc"], bool(obdrzi)))
        else:
            if v.get("id") is None:
                return False
            try:
                r = self._ukaz(str(v["naprava"]["id"]), "magnet.keep", {"id": v["id"], "keep": bool(obdrzi)}, 15.0)
            except Exception:  # noqa: BLE001
                r = {}
            ok = bool(isinstance(r, dict) and r.get("ok"))
        if ok:
            with self._zaklep:
                if v["kljuc"] in self._vnosi:
                    self._vnosi[v["kljuc"]]["obdrzi"] = bool(obdrzi)
        return ok

    def odstrani(self, kljuc: str, odstrani_tukaj: Optional[Callable[[dict], bool]] = None) -> bool:
        """Prenos odstrani z naprave, ki ga hrani (z datotekami). Prenos tega racunalnika odstrani `odstrani_tukaj`."""
        v = self.vnos(kljuc)
        if v is None:
            return False
        if v["naprava"]["id"] == TUKAJ:
            ok = bool(odstrani_tukaj(v)) if odstrani_tukaj is not None else odstrani_lokalnega(v["kljuc"])
        else:
            if v.get("id") is None:
                return False
            try:
                r = self._ukaz(str(v["naprava"]["id"]), "magnet.remove", {"id": v["id"]}, 15.0)
            except Exception:  # noqa: BLE001
                r = {}
            ok = bool(isinstance(r, dict) and r.get("ok"))
        if ok:
            with self._zaklep:
                self._vnosi.pop(v["kljuc"], None)
        return ok


def podnapisi_toka(tok: dict, dodaj: Optional[Callable[[object], str]] = None) -> List[tuple]:
    """Podnapisi iz torrenta za film, ki ga pretaka druga naprava (`subs` v odgovoru `magnet.stream`): vsak dobi svoj
    lokalni tok skozi core/link_pretok (pripeto potrdilo in zeton, kot film). Vrne [(naslov, ime, jezik, oznaka)]."""
    from core import link_pretok, os_torrent, podnapisi as pn
    if dodaj is None:
        dodaj = link_pretok.pretok().dodaj
    izid: List[tuple] = []
    for p in (tok.get("subs") or [])[:NAJVEC_PODNAPISOV]:
        ime = os.path.basename(str(p.get("name") or "").replace("\\", "/"))
        if not ime or os_torrent.vrsta_datoteke(ime) != "podnapisi":
            continue
        vir = link_pretok.vir_toka(tok.get("server"), p.get("path"), "text/plain")
        if vir is None:
            continue
        try:
            izid.append((dodaj(vir), ime) + tuple(pn.jezik(str(tok.get("name") or ""), ime)))
        except Exception:  # noqa: BLE001 - podnapisi niso nujni za predvajanje
            continue
    return izid


#: Toliko casa po zagonu motorja cakamo, da nasteje torrent, ki ga ima v svoji seji (pocasen disk). Manj kot 20 s:
#: toliko naprava caka na odgovor `magnet.remove`.
CAKANJE_MOTORJA_S = 12.0


def odstrani_lokalnega(hash_: str, torrenti=None, pot_rabe: Optional[str] = None,
                       spanec: Callable[[float], None] = time.sleep) -> bool:
    """Prenos zaradi gledanja odstrani iz motorja Safeer OS (z datotekami) in pozabi zapis. Samo prenosi iz zapisa rabe:
    torrenta, ki ga je uporabnik dodal sam, se polica ne dotika. Zapis pozabi sele, ko torrenta v motorju res ni vec."""
    hash_ = str(hash_ or "").lower()
    if not _HASH.fullmatch(hash_):
        return False
    if pot_rabe is None:
        from core import os_torrent_tok
        pot_rabe = os_torrent_tok.pot_rabe()
    if hash_ not in link_datoteke._beri_rabo(pot_rabe):
        return False
    if torrenti is None:
        from core import os_torrent
        torrenti = os_torrent.torrenti()
    try:
        if not torrenti.tece():
            torrenti.seznam()           # zazene motor, ce ima shranjeno stanje
        rok = time.monotonic() + CAKANJE_MOTORJA_S
        while True:
            t = next((x for x in torrenti.seznam() if link_datoteke._hash_torrenta(torrenti, x) == hash_), None)
            # Takoj po zagonu motor svojega stanja se ne nasteje: torrent, ki je v seji, pocakamo.
            if t is not None or not link_datoteke.v_seji_motorja(torrenti, hash_) or time.monotonic() >= rok:
                break
            spanec(1.0)
        if t is None:
            if link_datoteke.v_seji_motorja(torrenti, hash_):
                return False            # motor ga ima, a ga ne pokaze: nic ne pozabimo, datoteke ne ostanejo brez zapisa
        elif t.get("lastna") or not torrenti.odstrani(int(t["id"]), z_datotekami=True):
            return False
    except Exception:  # noqa: BLE001
        return False
    pozabi(hash_, pot_rabe=pot_rabe)
    return True
