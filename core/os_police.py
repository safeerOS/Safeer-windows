"""Osebne police Medijskega centra: Nadaljuj, Nazadnje dodano, Najveckrat predvajano, Priljubljene; ogledano in
naslednja epizoda (lastnik, 14. 10. 2026: najboljse iz Jellyfina, Kodija, Stremia, Ampacha in Serviia).

Cista pravila (brez okna in omrezja) in majhne datoteke JSON v mapi podatkov Medijskega centra, ob napredek.json:

  priljubljene.json  {"v": [{"k": kljuc, "t": cas, "m": opis}]}       najvec NAJVEC_PRILJUBLJENIH, najnovejse prve
  predvajanja.json   {kljuc: {"n": stevilo, "t": cas, "m": opis}}       najvec NAJVEC_PREDVAJANJ (izpade najstarejse)
  ogledano.json      {kljuc: cas}                                    najvec NAJVEC_OGLEDANIH (izpade najstarejse)

Zapis je atomaren (zacasna datoteka v isti mapi + os.replace): izpad elektrike med pisanjem ne pusti pol datoteke.
Krajevne datoteke stejeta predvajanja in ogledano v knjiznici (SQLite, core/os_knjiznica.py) ob poti; priljubljene
vseh vrst (datoteka, vnos kataloga, postaja, skladba s seznama) so tu, da je srcek povsod enak.

Kljuc vnosa (enak v assets/os/os.js, funkcija kljucVnosa - enakost varuje preizkus):
  "pot:<pot>"                 datoteka v krajevni knjiznici
  "tok:<url>"                 shranjena TV ali radijska postaja (Dodaj > TV/radio tok)
  "tmdb:tv:<id>:<s>:<e>"      epizoda serije s TMDB (ista epizoda iz kateregakoli vira)
  "tmdb:tv:<id>"              serija s TMDB
  "tmdb:film:<id>"            film s TMDB
  "id:<id>"                   vse drugo iz kataloga (postaja, skladba, video, skladba s seznama)
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from core.iskalni_kljuc import kljuc as kljuc_imena
from core.viri_sink import brez_prijave, ima_prijavo
from core import shramba_json

NAJVEC_PRILJUBLJENIH = 500
NAJVEC_PREDVAJANJ = 400
NAJVEC_OGLEDANIH = 3000
NA_POLICI = 20
#: Odstotek, pri katerem je video ogledan (kot Jellyfin: odjavna spica ne steje).
OGLEDANO_PRI = 0.90
#: Predvajanje steje, ko je preteklo 30 s - kratka skladba pa, ko je odigrana polovica (preskok po 3 s ni poslusanje).
PRAG_STETJA_S = 30.0
#: Najveckrat predvajano: vsaj dvakrat (enkrat predvajano je samo »nazadnje«, ne priljubljeno po navadi).
NAJMANJ_ZA_NAJVEC = 2
#: Zvok, daljsi od 20 min (podcast, zvocna knjiga), si zapomni mesto kot film; skladba ne.
DOLG_ZVOK_S = 20 * 60
#: Naslednja epizoda se ponudi le za serije, gledane v zadnjih 180 dneh.
NASLEDNJA_DNI = 180

#: Kateri zavihek kaze katere vrste (krajevne: filmi/serije/glasba/slike, katalog: film/serija/..., postaje: tv/radio).
VRSTE_ZAVIHKA = {
    "filmi": frozenset({"filmi", "film"}),
    "serije": frozenset({"serije", "serija"}),
    "video": frozenset({"filmi", "serije", "film", "serija", "video"}),
    "glasba": frozenset({"glasba", "podcast", "podkast"}),
    "radio": frozenset({"radio"}),
    "tv": frozenset({"tv", "tv-v-zivo"}),
    "slike": frozenset({"slike"}),
    # Domov (lastnik, 14. 10. 2026: zacetna stran Medijskega centra): vse vrste razen slik, ki imajo svoj zavihek.
    "domov": frozenset({"filmi", "serije", "film", "serija", "video", "glasba", "podcast", "podkast", "radio", "tv", "tv-v-zivo"}),
}
#: Vrste na polici »Nazadnje predvajana glasba« (samo Domov).
ZVOCNE = frozenset({"glasba", "podcast", "podkast"})
#: Police na zavihku in njihov vrstni red. Radio in TV nimata »nadaljuj« (prenos v zivo) ne »nazadnje dodano«
#: (postaj ne dodajamo kot datotek); slike imajo samo priljubljene. Iskanje (»vse«) nima polic.
#: »Nadaljuj z ogledom« je samo na Domov (lastnik, 17. 10. 2026) - na zavihkih videa ga ni (ena vrstica, ne tri).
POLICE_ZAVIHKOV = {
    "filmi": ("nazadnje", "priljubljene"),
    "serije": ("nazadnje", "priljubljene"),
    "video": ("nazadnje", "priljubljene"),
    "glasba": ("nadaljuj", "najvec", "nazadnje", "priljubljene"),
    "radio": ("priljubljene", "najvec"),
    "tv": ("priljubljene", "najvec"),
    "slike": ("priljubljene",),
    "domov": ("nadaljuj", "nazadnje", "glasba", "najvec", "priljubljene"),
}
#: Vrste, pri katerih ima »ogledano« smisel (video); glasba in postaje ga nimajo.
OGLEDLJIVE = frozenset({"filmi", "serije", "film", "serija", "video"})


# ---------------------------------------------------------------------------------------------- cista pravila

def _celo(v: Any) -> int:
    try:
        return max(0, int(v or 0))
    except (TypeError, ValueError):
        return 0


def kljuc_vnosa(item: dict) -> str:
    """Kljuc vnosa kataloga (glej opis modula). Prazen niz, ce vnos nima ne TMDB ne id."""
    if not isinstance(item, dict):
        return ""
    tmdb = _celo(item.get("tmdb_id"))
    vrsta = str(item.get("vrsta") or "")
    if tmdb and vrsta == "serija":
        s, e = _celo(item.get("sezona")), _celo(item.get("epizoda"))
        return "tmdb:tv:%d:%d:%d" % (tmdb, s, e) if s and e else "tmdb:tv:%d" % tmdb
    if tmdb and vrsta == "film":
        return "tmdb:film:%d" % tmdb
    ident = str(item.get("id") or "")
    return ("id:" + ident)[:400] if ident else ""


def veljaven_kljuc(k: Any) -> bool:
    k = str(k or "")
    vrsta, _, ostalo = k.partition(":")
    return bool(ostalo) and len(k) <= 2100 and vrsta in ("pot", "tok", "tmdb", "id") and "\n" not in k


def prag_stetja(trajanje: float) -> float:
    """Kdaj predvajanje steje: po 30 s, pri kratkem posnetku po polovici (tok v zivo nima dolzine: 30 s)."""
    t = float(trajanje or 0)
    return min(PRAG_STETJA_S, t * 0.5) if t > 0 else PRAG_STETJA_S


def je_ogledano(pozicija: float, trajanje: float) -> bool:
    return float(trajanje or 0) > 0 and float(pozicija or 0) >= OGLEDANO_PRI * float(trajanje)


# vir, ozadje in zanr (prva zvrst TMDB) za junaka na Domov: samo resnicni podatki vnosa, nic izmisljenega.
_POLJA_BESEDILA = ("naslov", "vrsta", "izvajalec", "podnaslov", "vir")
_POLJA_NASLOVA = ("slika", "url", "pot", "id", "ozadje")
_POLJA_STEVIL = ("tmdb_id", "sezona", "epizoda", "leto", "zanr")


def cisti_opis(m: Any) -> dict:
    """Opis vnosa za polico (kar stran pokaze na kartici): samo znana polja, omejene dolzine, slika le http(s)/file."""
    if not isinstance(m, dict):
        return {}
    izhod: dict = {}
    for p in _POLJA_BESEDILA:
        if m.get(p):
            izhod[p] = str(m[p]).replace("\n", " ")[:200]
    for p in _POLJA_NASLOVA:
        if m.get(p):
            izhod[p] = str(m[p])[:2048]
    for p in _POLJA_STEVIL:
        if _celo(m.get(p)):
            izhod[p] = min(_celo(m.get(p)), 2_147_483_647)
    for p in ("slika", "ozadje"):
        if not str(izhod.get(p, "")).startswith(("https://", "http://", "file://")):
            izhod.pop(p, None)
    if not str(izhod.get("url", "")).startswith(("https://", "http://")):
        izhod.pop("url", None)
    # Prijava osebnega streznika (api_key, u/t/s, geslo v naslovu) ne gre v predvajanja.json in priljubljene.json:
    # Medijski center jo doda ob predvajanju (MediaCenter.s_prijavo; pregled 14. 10. 2026).
    for p in ("url", "slika", "ozadje"):
        if p in izhod:
            izhod[p] = brez_prijave(izhod[p])
    return izhod


def ustreza_zavihku(zavihek: str, vrsta: str) -> bool:
    return str(vrsta or "") in VRSTE_ZAVIHKA.get(str(zavihek or ""), frozenset())


def sestavi_police(zavihek: str, viri: dict, iskanje: str = "") -> list:
    """Police za zavihek: samo tiste, ki jih zavihek ima, samo vnosi njegovih vrst, brez dvojnikov, najvec NA_POLICI,
    prazne police izpadejo (lastnik: brez praznih polic). Med iskanjem ni polic - iskanje pokaze zadetke."""
    if str(iskanje or "").strip():
        return []
    izhod = []
    for ime in POLICE_ZAVIHKOV.get(str(zavihek or ""), ()):
        videni, vnosi = set(), []
        for v in viri.get(ime) or []:
            if not isinstance(v, dict) or not v.get("kljuc") or v["kljuc"] in videni:
                continue
            if not ustreza_zavihku(zavihek, v.get("vrsta")):
                continue
            videni.add(v["kljuc"])
            vnosi.append(v)
            if len(vnosi) >= NA_POLICI:
                break
        if vnosi:
            izhod.append({"id": ime, "vnosi": vnosi})
    return izhod


# ---------------------------------------------------------------------------------------------- odkrivanje (Domov)
# Lastnik, 17. 10. 2026: »Domov v Medijskem centru deluje zelo prazno.« Pod osebnimi policami so police odkrivanja iz
# virov, ki jih Medijski center ze ima (katalog, seznami racunov, Twitch, radio). Vsaka ima »Vse →« na svoj zavihek.
# Pravila: ista vsebina samo enkrat (prva polica jo obdrzi), zasebni dodatki nikoli, prazna polica izpade.

#: (id police, zavihek za »Vse →«) v vrstnem redu prikaza.
POLICE_ODKRIVANJA = (("odkrij_filmi", "filmi"), ("odkrij_serije", "serije"), ("odkrij_glasba", "glasba"),
                     ("odkrij_youtube", "glasba"), ("odkrij_spotify", "glasba"), ("odkrij_twitch", "twitch"),
                     ("odkrij_radio", "radio"))
NA_POLICI_ODKRIVANJA = 20
#: Polja vnosa kataloga, ki jih kartica in klik (odpriKatalogPodrobnosti, odpriKatalogVnos, odpriTwitchKanal) rabita.
_POLJA_ODKRIVANJA = ("id", "naslov", "vrsta", "slika", "ozadje", "leto", "izvajalec", "tmdb_id", "login", "kanal", "igra",
                     "gledalcev", "ocena", "zanri", "stran", "v_zivo", "peertube_uuid")


def kartica_odkrivanja(item: Any) -> Optional[dict]:
    """Kartica police odkrivanja iz vnosa kataloga (film, serija, skladba, postaja, prenos) ali seznama racuna
    (tip "yt-seznam" / "sp-seznam"). None, ce vnos nima ne kljuca ne naslova."""
    if not isinstance(item, dict) or not str(item.get("naslov") or "").strip():
        return None
    tip = str(item.get("tip") or "")
    if tip in ("yt-seznam", "sp-seznam"):
        ident = str(item.get("id") or "")
        if not ident:
            return None
        k = ("yt:%d:%s" % (_celo(item.get("racun")), ident)) if tip == "yt-seznam" else "sp:" + ident
        d = {p: item[p] for p in ("id", "naslov", "slika", "podnaslov", "posebni", "racun", "stevilo") if item.get(p) not in (None, "")}
        return dict(d, tip=tip, kljuc=k[:400])
    k = kljuc_vnosa(item)
    if not k:
        return None
    d = {p: item[p] for p in _POLJA_ODKRIVANJA if item.get(p) not in (None, "", [])}
    return dict(d, tip="odkrij", kljuc=k)


def _kljuci_enakosti(k: dict) -> list:
    """Kljuca, po katerih je kartica ista: kljuc vnosa in ime + vrsta + leto (isti naslov iz dveh dodatkov z
    razlicnim id, ki ga katalog ni zdruzil)."""
    izid = [k["kljuc"]]
    if k.get("tip") == "odkrij":
        ime = kljuc_imena(str(k.get("naslov") or ""))
        if ime:
            izid.append("ime:%s:%s:%s" % (k.get("vrsta") or "", ime, _celo(k.get("leto"))))
    return izid


def sestavi_odkrivanje(viri: dict, izkljuci: Iterable[str] = (), zaseben: Optional[Callable[[dict], bool]] = None) -> list:
    """Police odkrivanja za Domov: [{"id", "zavihek", "vnosi"}].

    viri: {id police: [vnosi kataloga ali seznamov]}. izkljuci: kljuci, ki so ze na osebnih policah (Nadaljuj ...).
    zaseben(vnos): True za vsebino zasebnih dodatkov - ta na Domov ne pride nikoli. Ista vsebina je samo na prvi polici;
    prazne police izpadejo; najvec NA_POLICI_ODKRIVANJA na polico."""
    videni = {str(x) for x in (izkljuci or ()) if x}
    izhod = []
    for ime, zavihek in POLICE_ODKRIVANJA:
        vnosi = []
        for item in viri.get(ime) or []:
            if zaseben is not None and isinstance(item, dict):
                try:
                    if zaseben(item):
                        continue
                except Exception:  # noqa: BLE001 - dvom: vnos izpade (zasebno nikoli na Domov)
                    continue
            k = kartica_odkrivanja(item)
            if k is None:
                continue
            enakost = _kljuci_enakosti(k)
            # Glasba: ena kartica na ovitek - skladbe z istega albuma bi bile sicer na polici videti enake
            # (lastnik 17. 10. 2026: »pri razlicnih pesmih enak poster uporabnika zmede«).
            if zavihek == "glasba" and k.get("slika"):
                enakost = list(enakost) + ["slika:" + str(k["slika"])]
            if any(x in videni for x in enakost):
                continue
            videni.update(enakost)
            vnosi.append(k)
            if len(vnosi) >= NA_POLICI_ODKRIVANJA:
                break
        if vnosi:
            izhod.append({"id": ime, "zavihek": zavihek, "vnosi": vnosi})
    return izhod


# ---------------------------------------------------------------------------------------------- epizode

_EPIZODA = re.compile(r"(?i)(?:^|[^a-z0-9])(?:S(\d{1,2})E(\d{1,2})|(\d{1,2})x(\d{1,2}))(?:$|[^a-z0-9])")
_MAPA_SEZONE = re.compile(r"(?i)^(?:season|sezona|staffel|saison|temporada|stagione|series|s)[ ._-]*\d{1,2}$")


def _ime_serije(besedilo: str) -> str:
    ime = re.sub(r"[._\-\[\]()]+", " ", besedilo)
    ime = re.sub(r"\b(?:19|20)\d{2}\b", " ", ime)          # »Serija.2019.S01E01« in »Serija S01E02« sta ista serija
    return " ".join(kljuc_imena(ime).split())


def epizoda_datoteke(pot: str) -> Optional[tuple]:
    """(serija, sezona, epizoda) iz imena datoteke (S01E02 ali 1x02, kot core/os_knjiznica.vrsta_datoteke) ali None.

    Serija je del imena pred oznako; ce ga ni (»S01E02.mkv«), ime mape - mapa »Season 1« pa pove le sezono, zato
    takrat ime mape nad njo."""
    p = Path(str(pot or ""))
    m = _EPIZODA.search(p.stem)
    if not m:
        return None
    s, e = int(m.group(1) or m.group(3)), int(m.group(2) or m.group(4))
    ime = _ime_serije(p.stem[:m.start()])
    if not ime:
        mapa = p.parent
        if _MAPA_SEZONE.match(mapa.name):
            mapa = mapa.parent
        ime = _ime_serije(mapa.name) or str(mapa)
    return ime, s, e


def naslednja_lokalna(pot: str, poti: Iterable[str]) -> Optional[str]:
    """Naslednja epizoda iste serije za datoteko `pot` med `poti`: najmanjsa (sezona, epizoda) za trenutno, zato
    se za zadnjo epizodo sezone nadaljuje s prvo naslednje sezone (S01E10 -> S02E01)."""
    ta = epizoda_datoteke(pot)
    if ta is None:
        return None
    najboljsa = None
    for druga in poti:
        if druga == pot:
            continue
        ep = epizoda_datoteke(druga)
        if ep is None or ep[0] != ta[0] or (ep[1], ep[2]) <= (ta[1], ta[2]):
            continue
        if najboljsa is None or (ep[1], ep[2], druga) < najboljsa[0]:
            najboljsa = ((ep[1], ep[2], druga), druga)
    return najboljsa[1] if najboljsa else None


def naslednje_lokalne(vrstice: list, zdaj: Optional[float] = None) -> list:
    """»Naslednja epizoda« za polico Nadaljuj iz krajevnih serij.

    vrstice: [{"pot", "ogledano" (cas ali 0), "pozicija", "naVoljo", ...}]. Za vsako serijo vzame nazadnje ogledano
    epizodo in ponudi prvo naslednjo neogledano. Epizoda z nedokoncanim ogledom je ze na polici kot »Nadaljuj«,
    zato je tu ni. Vrne [(vrstica, cas_zadnjega_ogleda)] po casu, najnovejse prve."""
    zdaj = time.time() if zdaj is None else zdaj
    serije: dict = {}
    for v in vrstice:
        ep = epizoda_datoteke(v.get("pot", ""))
        if ep is not None:
            serije.setdefault(ep[0], []).append(((ep[1], ep[2], v.get("pot", "")), v))
    izhod = []
    for epizode in serije.values():
        epizode.sort(key=lambda x: x[0])
        ogledane = [(int(v.get("ogledano") or 0), red) for red, v in epizode if int(v.get("ogledano") or 0) > 0]
        if not ogledane:
            continue
        cas, zadnja = max(ogledane)
        if zdaj - cas > NASLEDNJA_DNI * 86400:
            continue
        for red, v in epizode:
            if red <= zadnja or int(v.get("ogledano") or 0) > 0:
                continue
            if v.get("naVoljo", True) and not int(v.get("pozicija") or 0):
                izhod.append((v, cas))
            break
    izhod.sort(key=lambda x: -x[1])
    return izhod


def naslednja_kataloga(sezona: int, epizoda: int, epizod: Callable[[int], int]) -> Optional[tuple]:
    """Naslednja epizoda serije iz kataloga: naslednja v sezoni, sicer prva v naslednji sezoni (ce je ze izsla).
    `epizod(s)` vrne stevilo ze predvajanih (izslih) epizod sezone s (0 = sezone ni)."""
    s, e = _celo(sezona), _celo(epizoda)
    if s <= 0 or e <= 0:
        return None
    if e < epizod(s):
        return s, e + 1
    if epizod(s + 1) > 0:
        return s + 1, 1
    return None


def razcleni_kljuc_epizode(k: str) -> Optional[tuple]:
    """"tmdb:tv:<id>:<s>:<e>" -> (id, s, e); sicer None."""
    m = re.fullmatch(r"tmdb:tv:(\d{1,10}):(\d{1,3}):(\d{1,4})", str(k or ""))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


# ---------------------------------------------------------------------------------------------- shramba

class Police:
    """Priljubljene, stevci predvajanj in ogledano v mapi podatkov Medijskega centra (varno za vec niti)."""

    PRILJUBLJENE, PREDVAJANJA, OGLEDANO = "priljubljene.json", "predvajanja.json", "ogledano.json"

    def __init__(self, mapa: str | Path) -> None:
        self.mapa = Path(mapa)
        self._zaklep = threading.RLock()

    def _beri(self, ime: str, privzeto: Any) -> Any:
        try:
            d = json.loads((self.mapa / ime).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return privzeto
        return d if isinstance(d, type(privzeto)) else privzeto

    def _pisi(self, ime: str, podatki: Any) -> bool:
        """Atomaren zapis: najprej zacasna datoteka v isti mapi, nato zamenjava (os.replace je atomaren)."""
        try:
            self.mapa.mkdir(parents=True, exist_ok=True)
            shramba_json.zapisi_atomsko(self.mapa / ime, podatki, indent=None)
            return True
        except OSError:  # zapisi_atomsko pobrise zacasno datoteko sam
            return False

    def _ocisti_prijave(self) -> None:
        """Enkratna selitev (14. 10. 2026): starejse razlicice so v opis skladbe s streznika zapisale naslov s prijavo
        (api_key, u/t/s). Datoteki prepisemo z opisi brez nje; ce ni cesa cistiti, ne pisemo."""
        with self._zaklep:
            if getattr(self, "_prijave_ociscene", False):
                return
            self._prijave_ociscene = True

            def umazan(m: Any) -> bool:
                return isinstance(m, dict) and any(ima_prijavo(m.get(p)) for p in ("url", "slika", "ozadje")
                                                   if isinstance(m.get(p), str))
            pr = self._beri(self.PREDVAJANJA, {})
            if any(isinstance(v, dict) and umazan(v.get("m")) for v in pr.values()):
                self._pisi(self.PREDVAJANJA, {k: dict(v, m=cisti_opis(v["m"])) if isinstance(v, dict) and umazan(v.get("m")) else v
                                              for k, v in pr.items()})
            pl = self._beri(self.PRILJUBLJENE, {})
            v = pl.get("v")
            if isinstance(v, list) and any(isinstance(x, dict) and umazan(x.get("m")) for x in v):
                self._pisi(self.PRILJUBLJENE, dict(pl, v=[dict(x, m=cisti_opis(x["m"])) if isinstance(x, dict) and umazan(x.get("m"))
                                                          else x for x in v]))

    # ------------------------------------------------------------------ priljubljene
    def _seznam_priljubljenih(self) -> list:
        self._ocisti_prijave()
        v = self._beri(self.PRILJUBLJENE, {}).get("v")
        return [x for x in v if isinstance(x, dict) and veljaven_kljuc(x.get("k"))] if isinstance(v, list) else []

    def priljubljene(self) -> list:
        """[{"k", "t", "m"}], nazadnje dodane prve."""
        with self._zaklep:
            return sorted(self._seznam_priljubljenih(), key=lambda x: -_celo(x.get("t")))

    def kljuci_priljubljenih(self) -> list:
        return [x["k"] for x in self.priljubljene()]

    def je_priljubljena(self, k: str) -> bool:
        return any(x["k"] == k for x in self.priljubljene())

    def nastavi_priljubljeno(self, k: str, da: bool, opis: Optional[dict] = None) -> bool:
        """Doda ali odstrani srcek; vrne novo stanje (False tudi ob neveljavnem kljucu)."""
        if not veljaven_kljuc(k):
            return False
        with self._zaklep:
            seznam = [x for x in self._seznam_priljubljenih() if x.get("k") != k]
            if da:
                seznam.insert(0, {"k": k, "t": int(time.time()), "m": cisti_opis(opis)})
                seznam = sorted(seznam, key=lambda x: -_celo(x.get("t")))[:NAJVEC_PRILJUBLJENIH]
            self._pisi(self.PRILJUBLJENE, {"v": seznam})
            return bool(da)

    # ------------------------------------------------------------------ predvajanja
    def _predvajanja(self) -> dict:
        self._ocisti_prijave()
        return {k: v for k, v in self._beri(self.PREDVAJANJA, {}).items() if veljaven_kljuc(k) and isinstance(v, dict)}

    def _shrani_predvajanja(self, d: dict) -> None:
        if len(d) > NAJVEC_PREDVAJANJ:
            for k, _ in sorted(d.items(), key=lambda kv: _celo(kv[1].get("t")))[:len(d) - NAJVEC_PREDVAJANJ]:
                d.pop(k, None)
        self._pisi(self.PREDVAJANJA, d)

    def zapomni(self, k: str, opis: Optional[dict]) -> None:
        """Ob zacetku predvajanja: opis za kartico na polici (stevec se ne spremeni)."""
        if not veljaven_kljuc(k):
            return
        with self._zaklep:
            d = self._predvajanja()
            v = d.get(k) or {"n": 0}
            v.update(t=int(time.time()), m=cisti_opis(opis) or v.get("m") or {})
            d[k] = v
            self._shrani_predvajanja(d)

    def stej(self, k: str, opis: Optional[dict] = None) -> int:
        """Eno predvajanje vec; vrne novo stevilo."""
        if not veljaven_kljuc(k):
            return 0
        with self._zaklep:
            d = self._predvajanja()
            v = d.get(k) or {"n": 0, "m": {}}
            v["n"] = _celo(v.get("n")) + 1
            v["t"] = int(time.time())
            if opis:
                v["m"] = cisti_opis(opis)
            d[k] = v
            self._shrani_predvajanja(d)
            return v["n"]

    def predvajanja(self) -> dict:
        with self._zaklep:
            return self._predvajanja()

    def opis(self, k: str) -> dict:
        """Opis vnosa: iz predvajanj (zapisal ga je Safeer sam), sicer iz priljubljenih."""
        v = self.predvajanja().get(k)
        if v and v.get("m"):
            return dict(v["m"])
        return next((dict(x.get("m") or {}) for x in self.priljubljene() if x["k"] == k), {})

    def kljuc_za_id(self, ident: str) -> Optional[tuple]:
        """(kljuc, opis) predvajanega vnosa kataloga z id `ident` (za napredek.json, ki je po id)."""
        for k, v in self.predvajanja().items():
            if isinstance(v.get("m"), dict) and v["m"].get("id") == ident:
                return k, dict(v["m"])
        return None

    # ------------------------------------------------------------------ ogledano
    def ogledano(self) -> dict:
        with self._zaklep:
            return {k: _celo(v) for k, v in self._beri(self.OGLEDANO, {}).items() if veljaven_kljuc(k)}

    def nastavi_ogledano(self, k: str, da: bool) -> bool:
        if not veljaven_kljuc(k):
            return False
        with self._zaklep:
            d = self.ogledano()
            if da:
                d[k] = int(time.time())
                if len(d) > NAJVEC_OGLEDANIH:
                    for star, _ in sorted(d.items(), key=lambda kv: kv[1])[:len(d) - NAJVEC_OGLEDANIH]:
                        d.pop(star, None)
            else:
                d.pop(k, None)
            self._pisi(self.OGLEDANO, d)
            return bool(da)
