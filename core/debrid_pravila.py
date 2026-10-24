"""Naloga 131: debrid storitve v Medijskem centru - TorBox, Real-Debrid, AllDebrid (kot Safeer OS za Android, naloge
119, 128, 129 in 130). Storitev torrent prenese namesto racunalnika (njegov IP ni v roju) in ga pretaka s svojega streznika.

Tu so samo ciste odlocitve brez omrezja (preizkus: tests/test_debrid_pravila.py); odjemalci in izbira so v core/debrid.py.

Iz dokumentacije (prebrano 24. 10. 2026, ne ugibano):
- TorBox: `https://api.torbox.app/v1/api`, glava `Authorization: Bearer <kljuc>`; checkcached (do 100 hashev naenkrat),
  createtorrent (60 nepredpomnjenih na uro), mylist, requestdl - SAMO ta zahteva kljuc kot parameter `token` (tak naslov se
  nikoli ne zapise in ne gre predvajalniku).
- Real-Debrid: `https://api.real-debrid.com/rest/1.0`, Bearer; addMagnet -> torrents/info -> selectFiles -> info
  (»downloaded«, links) -> unrestrict/link. Preverjanja predpomnjenja (instantAvailability) od novembra 2024 ni.
- AllDebrid: `https://api.alldebrid.com/v4`, Bearer; magnet/upload (`ready`) -> magnet/files -> link/unlock (link ali delayed).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

TORBOX = "torbox"
REAL_DEBRID = "realdebrid"
ALLDEBRID = "alldebrid"

#: Privzeti vrstni red (ce uporabnik ne izbere prednostne storitve).
VSI = (TORBOX, REAL_DEBRID, ALLDEBRID)

TORBOX_OSNOVA = "https://api.torbox.app/v1/api/torrents"
RD_OSNOVA = "https://api.real-debrid.com/rest/1.0"
AD_OSNOVA = "https://api.alldebrid.com/v4"

NAPAKA_KLJUC = "kljuc"
NAPAKA_MEJA = "meja"
NAPAKA_PAKET = "paket"
NAPAKA_NI_DATOTEKE = "ni_datoteke"
NAPAKA_PRENASA = "prenasa"
NAPAKA_STREZNIK = "streznik"
NAPAKA_NI_PREDPOMNJENO = "ni_predpomnjeno"

#: Oznaka pred imenom vira, ki ga ima storitev pripravljenega (takoj predvajljiv).
OZNAKA_PREDPOMNJEN = "⚡"


def ime(ponudnik: str) -> str:
    return {TORBOX: "TorBox", REAL_DEBRID: "Real-Debrid", ALLDEBRID: "AllDebrid"}.get(ponudnik, ponudnik)


def kje_kljuc(ponudnik: str) -> str:
    """Kje uporabnik dobi kljuc (prikaz ob vnosu)."""
    return {TORBOX: "torbox.app → Settings → API", REAL_DEBRID: "real-debrid.com/apitoken",
            ALLDEBRID: "alldebrid.com/apikeys"}.get(ponudnik, "")


_KLJUC = re.compile(r"[A-Za-z0-9_-]{16,128}")


def ocisti_kljuc(vnos: object) -> Optional[str]:
    """Kljuc, kot ga uporabnik prilepi: brez presledkov, 16-128 znakov, samo crke, stevke, '-' in '_'. Sicer None
    (prilepljena vrstica z naslovom ali presledki ni kljuc)."""
    k = str(vnos or "").strip()
    return k if _KLJUC.fullmatch(k) else None


def glava_avtorizacije(kljuc: str) -> str:
    return "Bearer " + kljuc


def vrstni_red(z_kljucem: Iterable[str], prednostna: Optional[str]) -> list[str]:
    """Storitve s kljucem; [prednostna] (ce ima kljuc) prva, ostale po VSI."""
    ima = [p for p in VSI if p in set(z_kljucem)]
    if prednostna in ima:
        return [prednostna] + [p for p in ima if p != prednostna]
    return ima


def aktivna(z_kljucem: Iterable[str], prednostna: Optional[str], izklopljeno: bool) -> Optional[str]:
    """Storitev, prek katere gredo torrenti (izbira »Debrid« ob zvrsteh). Privzeto prva s kljucem; [izklopljeno] =
    uporabnik je izbral »Brez debrida«. None = torrenti ne gredo prek debrida."""
    if izklopljeno:
        return None
    red = vrstni_red(z_kljucem, prednostna)
    return red[0] if red else None


def razlog_za_uporabnika(napake: Sequence[str]) -> str:
    """Ko nobena storitev ni dala povezave: najbolj pomenljiva napaka (kljuc > meja > paket > ni datoteke > ni
    predpomnjeno > prenasa > streznik)."""
    for n in (NAPAKA_KLJUC, NAPAKA_MEJA, NAPAKA_PAKET, NAPAKA_NI_DATOTEKE, NAPAKA_NI_PREDPOMNJENO, NAPAKA_PRENASA, NAPAKA_STREZNIK):
        if n in napake:
            return n
    return NAPAKA_STREZNIK


def poskusi_s_cakanjem(samo_predpomnjeno: bool, napake: Sequence[str]) -> bool:
    """Po neuspehu s samo predpomnjenim poskusimo s cakanjem (storitev torrent prenese) le, ce filter »samo takoj« ni
    vklopljen in je razlog povsod »ni predpomnjeno«."""
    return not samo_predpomnjeno and bool(napake) and all(n == NAPAKA_NI_PREDPOMNJENO for n in napake)


# ---------------------------------------------------------------------- napake storitev

def torbox_vrsta_napake(http: int, koda: Optional[str]) -> str:
    if koda in ("NO_AUTH", "BAD_TOKEN", "AUTH_ERROR") or http in (401, 403):
        return NAPAKA_KLJUC
    if koda in ("ACTIVE_LIMIT", "COOLDOWN_LIMIT", "MONTHLY_LIMIT") or http == 429:
        return NAPAKA_MEJA
    if koda in ("PLAN_RESTRICTED_FEATURE", "DOWNLOAD_TOO_LARGE"):
        return NAPAKA_PAKET
    if koda in ("BOZO_TORRENT", "ITEM_NOT_FOUND", "LINK_OFFLINE"):
        return NAPAKA_NI_DATOTEKE
    return NAPAKA_STREZNIK


def rd_pripravljen(stanje: str) -> bool:
    return str(stanje or "").lower() == "downloaded"


def rd_koncna_napaka(stanje: str) -> bool:
    return str(stanje or "").lower() in ("error", "virus", "dead", "magnet_error")


def rd_vrsta_napake(http: int, koda: Optional[int]) -> str:
    """Koda Real-Debrid ima prednost pred HTTP (37 »disabled endpoint« pride tudi s 403, a ni stvar paketa)."""
    if koda == 8:
        return NAPAKA_KLJUC
    if koda in (9, 14, 20, 29):
        return NAPAKA_PAKET
    if koda in (5, 21, 23, 34, 36):
        return NAPAKA_MEJA
    if koda in (24, 28, 30, 35):
        return NAPAKA_NI_DATOTEKE
    if koda is not None:
        return NAPAKA_STREZNIK
    if http == 401:
        return NAPAKA_KLJUC
    if http == 403:
        return NAPAKA_PAKET
    if http == 429:
        return NAPAKA_MEJA
    return NAPAKA_STREZNIK


def ad_vrsta_napake(http: int, koda: Optional[str]) -> str:
    k = str(koda or "")
    if k.startswith("AUTH_") or http == 401:
        return NAPAKA_KLJUC
    if k in ("MUST_BE_PREMIUM", "MAGNET_MUST_BE_PREMIUM", "FREE_TRIAL_LIMIT_REACHED"):
        return NAPAKA_PAKET
    if k in ("MAGNET_TOO_MANY_ACTIVE", "MAGNET_TOO_MANY") or http in (429, 503):
        return NAPAKA_MEJA
    if k.startswith("MAGNET_INVALID") or k in ("MAGNET_NO_URI", "LINK_DOWN"):
        return NAPAKA_NI_DATOTEKE
    return NAPAKA_STREZNIK


# ---------------------------------------------------------------------- torrent in datoteke

_HEKS = re.compile(r"[0-9a-f]{40}")


def je_hash(h: object) -> bool:
    return bool(_HEKS.fullmatch(str(h or "").strip().lower()))


def magnet(hash_: str, ime_datoteke: str = "", sledilniki: Sequence[str] = ()) -> str:
    """Magnet iz hasha dodatka (Stremio infoHash), z imenom in sledilniki, ce jih dodatek da."""
    from urllib.parse import quote
    m = "magnet:?xt=urn:btih:" + str(hash_).strip().lower()
    if ime_datoteke:
        m += "&dn=" + quote(ime_datoteke, safe="")
    for s in list(sledilniki)[:20]:
        m += "&tr=" + quote(str(s), safe="")
    return m


@dataclass(frozen=True)
class Datoteka:
    id: int
    ime: str
    velikost: int
    mime: str = ""


_VIDEO = {"mkv", "mp4", "m4v", "avi", "webm", "mov", "ts", "m2ts", "wmv", "mpg", "mpeg"}
_ZVOK = {"mp3", "flac", "m4a", "aac", "ogg", "opus", "wav"}


def je_predvajljiva(d: Datoteka) -> bool:
    konc = d.ime.rsplit(".", 1)[-1].lower() if "." in d.ime else ""
    return d.mime.startswith(("video/", "audio/")) or konc in _VIDEO or konc in _ZVOK


def izberi_datoteko(datoteke: Sequence[Datoteka], indeks: Optional[int]) -> Optional[Datoteka]:
    """Datoteka, ki jo pove dodatek (fileIdx), ce je predvajljiva; sicer najvecja predvajljiva (film, ne vzorec)."""
    if indeks is not None and 0 <= indeks < len(datoteke) and je_predvajljiva(datoteke[indeks]):
        return datoteke[indeks]
    pred = [d for d in datoteke if je_predvajljiva(d)]
    return max(pred, key=lambda d: d.velikost) if pred else None


def torbox_pripravljen(stanje: str, koncano: bool, prisoten: bool) -> bool:
    return bool(koncano or prisoten or str(stanje or "").lower() in ("cached", "completed", "uploading"))


NAJVEC_NOVIH_NA_URO = 60
URA_S = 3600.0


def meja_novih_dovoli(casi: Sequence[float], zdaj: float) -> bool:
    """TorBox: najvec 60 NEPREDPOMNJENIH torrentov na uro na kljuc (predpomnjen se ne steje)."""
    return sum(1 for c in casi if 0 <= zdaj - c < URA_S) < NAJVEC_NOVIH_NA_URO


CAKAJ_NOVEGA_S = 180.0
CAKAJ_KORAK_S = 5.0

# ---------------------------------------------------------------------- naloga 130: ⚡ in samodejna izbira

#: Najvec hashev v eni preverbi predpomnjenja TorBox (checkcached).
NAJVEC_PREVERB = 100


def hashi_za_preverbo(hashi: Iterable[object]) -> list[str]:
    """Samo veljavni hashi (40 heks), mala crka, brez ponovitev, najvec NAJVEC_PREVERB."""
    izid: list[str] = []
    for h in hashi:
        v = str(h or "").strip().lower()
        if _HEKS.fullmatch(v) and v not in izid:
            izid.append(v)
        if len(izid) >= NAJVEC_PREVERB:
            break
    return izid


def torbox_naslov_predpomnjenih(hashi: Sequence[str]) -> str:
    return TORBOX_OSNOVA + "/checkcached?hash=" + ",".join(hashi) + "&format=object&list_files=false"


def predpomnjeni(kljuci_odgovora: Iterable[str], vprasani: Sequence[str]) -> set[str]:
    """Predpomnjeni iz odgovora checkcached (kljuci objekta `data`): samo tisti, ki smo jih vprasali."""
    v = set(vprasani)
    return {str(k).lower() for k in kljuci_odgovora if str(k).lower() in v}


def _je_pred(h: object, pred: set[str]) -> bool:
    return h is not None and str(h).lower() in pred


def predpomnjeni_naprej(hashi: Sequence[object], pred: set[str]) -> list[int]:
    """Indeksi: pripravljeni najprej, sicer red ostane (kakovost, kot jo je uredila tok_izbira)."""
    return [i for i, h in enumerate(hashi) if _je_pred(h, pred)] + [i for i, h in enumerate(hashi) if not _je_pred(h, pred)]


def samodejni_torrent(aktivna_storitev: Optional[str], hashi: Sequence[object], pred: set[str]) -> int:
    """Samodejno predvajanje: z aktivno storitvijo gre najboljsi pripravljen torrent pred neposrednimi povezavami.
    Vrne indeks v [hashi] ali -1 (obstojeca izbira)."""
    if aktivna_storitev is None:
        return -1
    return next((i for i, h in enumerate(hashi) if _je_pred(h, pred)), -1)


# ---------------------------------------------------------------------- najhitrejsa storitev (vec kljucev)

@dataclass(frozen=True)
class Meritev:
    """Meritev povezave storitve do tega racunalnika: [ping_ms] do prvega odgovora, [bajtov] v [cas_ms] po njem."""
    ponudnik: str
    ping_ms: int
    bajtov: int
    cas_ms: int

    @property
    def bitov_na_sekundo(self) -> int:
        return 0 if self.cas_ms <= 0 or self.bajtov <= 0 else self.bajtov * 8000 // self.cas_ms


MERITEV_BAJTOV = 3 * 1024 * 1024
MERITEV_S = 2.0
VZPOREDNO_ROK_S = 15.0
PODOBNA_HITROST = 0.85
MERITEV_VELJA_S = 7 * 24 * 3600.0


def najhitrejsa(meritve: Sequence[Meritev]) -> Optional[str]:
    """Najvisja hitrost prenosa; pri razliki pod 15 % odloci manjsi ping. None = nobena meritev ni uspela."""
    ok = [m for m in meritve if m.bitov_na_sekundo > 0]
    if not ok:
        return None
    najvec = max(m.bitov_na_sekundo for m in ok)
    return min((m for m in ok if m.bitov_na_sekundo >= najvec * PODOBNA_HITROST), key=lambda m: m.ping_ms).ponudnik


def opis_meritve(m: Meritev) -> str:
    mb = m.bitov_na_sekundo / 1_000_000
    hitrost = ("%.1f" % mb) if mb < 10 else str(int(mb))
    return "%s Mb/s · %d ms" % (hitrost, m.ping_ms)


def meritev_velja(kdaj: float, zdaj: float) -> bool:
    return 0 <= zdaj - kdaj < MERITEV_VELJA_S
