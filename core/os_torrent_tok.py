"""Film ali epizoda iz torrenta (tok `infoHash` dodatka Stremio) v Medijskem centru na racunalniku.

Safeer OS za Android take tokove predvaja (sam ali s pomocjo racunalnika v Linku); Medijski center na racunalniku
jih do 3. 10. 2026 ni - naslov, ki ga ponujajo samo torrenti, se je na racunalniku skril kot "ni na voljo". Tu je
manjkajoci del: torrent prenasa motor Safeer OS (core/os_torrent.py, rqbit), predvajalnik dobi lokalni tok ze med
prenosom. Modul je skupen za Linux in Windows.

Pravila (ista kot pri pomoci napravam, core/link_datoteke.py):
  * kar je na tem racunalniku ze v celoti preneseno (Safeer OS ali Control za naprave), gre z diska - brez torrenta;
  * disku pustimo rezervo; ce prostora ni, najprej odstranimo, cesar nihce vec ne gleda;
  * kar se je preneslo zaradi gledanja in tega 48 ur nihce ni predvajal, se odstrani samo. Torrenta, ki ga je
    uporabnik dodal sam (zaslon Magnet povezave), se ciscenje nikoli ne dotakne.
"""

from __future__ import annotations

import os
import re
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from core import link_datoteke, os_torrent

#: Po toliko casu brez predvajanja se prenos, ki je nastal zaradi gledanja, odstrani sam.
RABA_VELJA_S = 48 * 3600
#: Ob pomanjkanju prostora odstranimo tudi mlajse, a ne tistih, ki jih je kdo gledal v zadnjih urah.
RABA_V_TEKU_S = 6 * 3600

_HASH = re.compile(r"[0-9a-fA-F]{40}")


def podprto() -> bool:
    """Ali ta racunalnik zna prenasati torrente (rqbit obstaja za to platformo)."""
    try:
        return bool(os_torrent.platforma())
    except Exception:  # noqa: BLE001
        return False


def magnet(hash_: str, ime: str = "", sledilniki: Iterable[str] = ()) -> str:
    """Magnet povezava iz podatkov toka dodatka (infoHash, behaviorHints.filename, sources: "tracker:...")."""
    if not _HASH.fullmatch(str(hash_ or "")):
        return ""
    uri = "magnet:?xt=urn:btih:" + str(hash_).lower()
    if ime:
        uri += "&dn=" + urllib.parse.quote(str(ime)[:300], safe="")
    for s in list(sledilniki or ())[:20]:
        uri += "&tr=" + urllib.parse.quote(str(s), safe="")
    return uri


def pot_rabe() -> str:
    return os.path.join(os.path.dirname(os_torrent.mapa_stanja()), "raba-gledanje.json")


def zabelezi(hash_: str, pot: Optional[str] = None, zdaj: Optional[float] = None) -> None:
    """Naslov so pravkar predvajali: od zdaj tece rok do samodejne odstranitve."""
    link_datoteke.zabelezi_rabo(hash_, pot or pot_rabe(), zdaj)


def obdrzi(hash_: str, pot: Optional[str] = None) -> None:
    """Uporabnik je torrent dodal sam (Magnet povezave): ni vec "prenos zaradi gledanja", ciscenje ga pusti."""
    if not _HASH.fullmatch(str(hash_ or "")):
        return
    pot = pot or pot_rabe()
    with link_datoteke._RABA_ZAKLEP:
        raba = link_datoteke._beri_rabo(pot)
        if raba.pop(str(hash_).lower(), None) is not None:
            link_datoteke._pisi_rabo(pot, raba)


def pocisti(torrenti, pot: Optional[str] = None, zdaj: Optional[float] = None,
            dovolj: Optional[Callable[[], bool]] = None, obdrzi_hash: str = "") -> List[str]:
    """Odstrani prenose, ki so nastali zaradi gledanja in jih [RABA_VELJA_S] nihce ni predvajal. Vrne njihove hashe.

    Odstrani SAMO torrente, zapisane v datoteki rabe - torrenta, ki ga je uporabnik dodal sam, tam ni.
    `dovolj` (klic -> bool): prostora zmanjkuje - dokler ne vrne True, gredo tudi mlajsi, najdlje negledani prvi,
    a ne tisti, ki so jih gledali v zadnjih [RABA_V_TEKU_S], in ne `obdrzi_hash`. Motorja zaradi ciscenja ne zaganjamo."""
    pot = pot or pot_rabe()
    zdaj = float(time.time() if zdaj is None else zdaj)
    obdrzi_hash = str(obdrzi_hash or "").lower()
    if not link_datoteke._beri_rabo(pot):
        return []
    try:
        if not torrenti.tece():
            return []
        vsi = torrenti.seznam()
    except Exception:  # noqa: BLE001
        return []
    po_hashu = {link_datoteke._hash_torrenta(torrenti, t): t for t in vsi}
    odstranjeni: List[str] = []
    with link_datoteke._RABA_ZAKLEP:
        raba = link_datoteke._beri_rabo(pot)
        spremenjeno = False

        def odstrani(h: str) -> None:
            nonlocal spremenjeno
            t = po_hashu.get(h)
            if t is None:
                if link_datoteke.v_seji_motorja(torrenti, h):
                    return                 # motor ga ima, a ga (takoj po zagonu) se ne nasteje: zapis ostane za naslednjic
                raba.pop(h, None)          # torrenta ni vec (uporabnik ga je odstranil sam): zapis ne ostaja
                spremenjeno = True
                return
            if t.get("lastna"):
                return                     # uporabnikova datoteka, ki jo deli: nikoli
            try:
                ok = bool(torrenti.odstrani(int(t["id"]), z_datotekami=True))
            except Exception:  # noqa: BLE001
                ok = False
            if ok:
                raba.pop(h, None)
                odstranjeni.append(h)
                spremenjeno = True

        vrsta = sorted(raba.items(), key=lambda p: p[1])
        for h, cas in vrsta:
            if h != obdrzi_hash and (zdaj - cas > RABA_VELJA_S or h not in po_hashu):
                odstrani(h)
        if dovolj is not None:
            for h, cas in vrsta:
                if dovolj():
                    break
                if h in odstranjeni or h not in raba or h == obdrzi_hash or zdaj - cas < RABA_V_TEKU_S:
                    continue
                odstrani(h)
        if spremenjeno:
            link_datoteke._pisi_rabo(pot, raba)
    return odstranjeni


def _izberi(datoteke: List[dict], indeks: Optional[int], ime: str) -> Optional[dict]:
    """Datoteka za predvajanje: zahtevani indeks dodatka, sicer datoteka z imenom iz dodatka, sicer najvecji video.
    Programov (nevarno) nikoli."""
    predvajljive = [d for d in datoteke if d.get("vrsta") in ("video", "audio")]
    if indeks is not None:
        izbrana = next((d for d in predvajljive if d["i"] == int(indeks)), None)
        if izbrana is not None:
            return izbrana
    if ime:
        iskano = os.path.basename(str(ime).replace("\\", "/")).lower()
        izbrana = next((d for d in predvajljive
                        if os.path.basename(str(d.get("ime") or "").replace("\\", "/")).lower() == iskano), None)
        if izbrana is not None:
            return izbrana
    videi = [d for d in predvajljive if d.get("vrsta") == "video"]
    return max(videi, key=lambda d: int(d.get("velikost") or 0)) if videi else None


def pripravi(hash_: str, indeks: Optional[int] = None, ime: str = "", sledilniki: Iterable[str] = (),
             torrenti=None, zmogljivost=None, mape_stanja=None, pot: Optional[str] = None) -> dict:
    """Tok za predvajalnik: {url, ime, indeks, velikost, podnapisi[, pot]} ali os_torrent.NapakaTorrenta(koda).

    Kode: ni_magnet, ni_predvajljivo, ni_prostora, malo_pomnilnika in kode motorja (npr. metapodatkov ni)."""
    uri = magnet(hash_, ime, sledilniki)
    if not uri or os_torrent.razcleni_magnet(uri) is None:
        raise os_torrent.NapakaTorrenta("ni_magnet")
    hash_ = str(hash_).lower()
    preizkus = torrenti is not None
    if pot is None and not preizkus:
        pot = pot_rabe()
    # Ze v celoti na disku (Safeer OS ali prenos za naprave): takoj, brez motorja.
    global _ZADNJA_PRIPRAVA
    _ZADNJA_PRIPRAVA = time.time()
    obstojeca, i = link_datoteke.ze_preneseno(hash_, indeks, mape_stanja)
    if obstojeca and indeks is None and ime and \
            os.path.basename(obstojeca).lower() != os.path.basename(str(ime).replace("\\", "/")).lower():
        obstojeca = ""      # paket z vec videi brez indeksa: najvecji video ni nujno zahtevana epizoda
    if obstojeca:
        # Prenos zaradi gledanja, ki ga kdo se gleda (zdaj z diska), ne potece: rok tece od zadnjega predvajanja.
        if pot and hash_ in link_datoteke._beri_rabo(pot):
            zabelezi(hash_, pot)
        return {"url": Path(obstojeca).as_uri(), "pot": obstojeca, "ime": os.path.basename(obstojeca), "indeks": i,
                "velikost": os.path.getsize(obstojeca), "podnapisi": []}
    if torrenti is None:
        if not os_torrent.program_na_voljo():
            os_torrent.prenesi_program()
        torrenti = os_torrent.torrenti()
    torrenti.zazeni()
    opis = torrenti.preberi(uri)
    izbrana = _izberi(opis["datoteke"], indeks, ime)
    if izbrana is None:
        raise os_torrent.NapakaTorrenta("ni_predvajljivo")
    velikost = int(izbrana.get("velikost") or 0)
    # Torrent, ki ga motor ze ima in ni med "prenosi zaradi gledanja", je uporabnik dodal sam: ne belezimo ga,
    # da ga ciscenje ne odstrani.
    ze_v_motorju = False
    try:
        ze_v_motorju = any(link_datoteke._hash_torrenta(torrenti, t) == hash_ for t in torrenti.seznam())
    except Exception:  # noqa: BLE001
        pass
    belezi = bool(pot) and (not ze_v_motorju or hash_ in link_datoteke._beri_rabo(pot))
    if pot:
        pocisti(torrenti, pot, obdrzi_hash=hash_)
    mapa_diska = str(getattr(torrenti, "mapa_prenosov", "") or "") or os.path.expanduser("~")
    preveri = zmogljivost or link_datoteke.zmogljivost_za_tok
    razlog = "" if ze_v_motorju else preveri(mapa_diska, velikost)
    if razlog == "ni_prostora" and pot:
        pocisti(torrenti, pot, dovolj=lambda: preveri(mapa_diska, velikost) != "ni_prostora", obdrzi_hash=hash_)
        razlog = preveri(mapa_diska, velikost)
    if razlog:
        raise os_torrent.NapakaTorrenta(razlog)
    tid = torrenti.dodaj(uri, [izbrana["i"]])
    url = torrenti.tok(tid, izbrana["i"])
    if belezi:
        zabelezi(hash_, pot)
    podnapisi = []
    try:
        from core import podnapisi as _pn
        ime_videa = str(izbrana.get("ime") or "")
        for j, pot_p in torrenti.podnapisi_za(tid, izbrana["i"]):
            jezik, oznaka = _pn.jezik(ime_videa, pot_p)
            podnapisi.append({"uri": torrenti.tok(tid, j), "ime": os.path.basename(pot_p), "jezik": jezik, "oznaka": oznaka})
    except Exception:  # noqa: BLE001 - podnapisi niso nujni za predvajanje
        pass
    # "zacasen": prenos je nastal zaradi gledanja (zapisan v rabi) - samo tak gre na polico »Na tvojih napravah«.
    return {"url": url, "ime": os.path.basename(str(izbrana.get("ime") or "")), "indeks": izbrana["i"],
            "velikost": velikost, "podnapisi": podnapisi, "zacasen": bool(belezi)}


_CISCENJE_TECE = False
#: Kdaj je kdo nazadnje zahteval tok (ciscenje motorja ne ugasne, ce ga je medtem kdo zacel uporabljati).
_ZADNJA_PRIPRAVA = 0.0


def zazeni_ciscenje(razmik_s: float = 3 * 3600, zamik_s: float = 240) -> None:
    """Safeer OS: prenose zaradi gledanja pregleda kmalu po zagonu in nato vsake tri ure. Ce je motor ugasnjen in
    je kaj za odstraniti, ga za pregled prizge in potem spet ugasne (ne ostane v ozadju samo zaradi ciscenja)."""
    global _CISCENJE_TECE
    if _CISCENJE_TECE or not podprto():
        return
    _CISCENJE_TECE = True

    def zanka() -> None:
        time.sleep(zamik_s)
        while True:
            try:
                raba = link_datoteke._beri_rabo(pot_rabe())
                if any(time.time() - cas > RABA_VELJA_S for cas in raba.values()):
                    t = os_torrent.torrenti()
                    tekel = t.tece()
                    zacetek = time.time()
                    if not tekel:
                        t.seznam()          # zazene motor le, ce ima shranjeno stanje
                    pocisti(t)
                    if not tekel and t.tece() and _ZADNJA_PRIPRAVA < zacetek:
                        t.ustavi()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(razmik_s)
    threading.Thread(target=zanka, name="safeer-ciscenje-gledanja", daemon=True).start()
