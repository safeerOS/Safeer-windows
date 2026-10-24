"""Moji viri so enaki na vseh napravah v Safeer Linku - cista pravila za racunalnik (brez omrezja in diska).

Safeer OS za Android to zna od 3. 10. 2026 (SeznamiSink.kt, MedijskiViri.kt): vir, ki ga uporabnik doda na eni napravi
(dodatek, podkast, seznam, tok ...), se pojavi na vseh; izbris se prenese enako. Racunalnik (Linux, Windows) je bil do
kroga 85 izven tega - dodatek, dodan na telefonu, je bilo treba na racunalniku dodati se enkrat. Modul je skupen za
Linux in Windows; nic ne gre v oblak, samo med napravami v Linku.

Protokol (del odgovora na `lists.get {}`; glej core/seznami_sink.py):
  "sources":         [{"tip", "ime", "naslov", "cas"}]     cas = kdaj je bil vir dodan (ms; 0 = pred usklajevanjem)
  "sources_deleted": {"tip|naslov": cas}                    izbrisi, da se vir ne vrne z naprave, ki ga se ima

Vrste (kot na Androidu): stremio, peertube, splet, api, seznam, podkast, tok, tok-hls, tok-video, tok-hls-video.
Racunalnik doda se vrsto "url": naslov, ki ga je uporabnik dodal na racunalniku in mu vrsto doloci naprava sama (starejsa
razlicica Androida take vrste ne pozna in vnos preskoci).

Pravila:
  * zaseben dodatek (manifest `behaviorHints.adult`) ostane na napravi, kjer ga je uporabnik dodal - ne gre ven in ga
    ne prevzamemo; dokler ne vemo, ali je zaseben, velja kot zaseben;
  * racunalnik prevzame samo, kar zna predvajati (preveri ob prevzemu); cesar ne zna, si zapomni in ne poskusa znova
    ob vsakem usklajevanju; spletnih strani, streznikov PeerTube in virov API ne prevzema;
  * isti vir: dodatek po korenu (brez /manifest.json), drugo po naslovu - ne glede na vrsto, ki mu jo je dala naprava.
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Optional

#: Vrsta vira, ki ga je uporabnik dodal na racunalniku (vrsto doloci naprava, ki ga prevzame).
URL = "url"
STREMIO = "stremio"
_VRSTE = re.compile(r"^(stremio|peertube|splet|api|seznam|podkast|tok(-hls)?(-video)?|url)$")
#: Kar racunalnik zna prevzeti: dodatke in naslove, ki jih prebere Medijski center. Strezniki PeerTube in viri API imajo
#: na Androidu svoj zapis, ki ga racunalnik ne pozna. Spletna stran ("splet": youtube.com, open.spotify.com) je na
#: Androidu bliznjica do strani v brskalniku; Medijski center na racunalniku bi iz nje pobral nakljucne vnose s prve
#: strani (preizkus v zivo, 3. 10. 2026), zato je ne prevzamemo - za strani ima racunalnik Spletne aplikacije.
PREVZEMLJIVE = frozenset({STREMIO, "seznam", "podkast", "tok", "tok-hls", "tok-video", "tok-hls-video", URL})
NAJVEC_VIROV = 200
NAJVEC_IZBRISANIH = 300
#: Vir, ki ga racunalnik ni mogel prevzeti (ni predvajljiv, zaseben, nedosegljiv), poskusimo znova sele cez toliko.
ZAVRNJEN_VELJA_MS = 24 * 3600 * 1000
NEDOSEGLJIV_VELJA_MS = 10 * 60 * 1000


def stremio_osnova(naslov: str) -> str:
    """Koren dodatka: brez stremio://, /manifest.json in koncne posevnice (kot Stremio.osnova na Androidu)."""
    n = str(naslov or "").strip()
    if n.startswith("stremio://"):
        n = "https://" + n[len("stremio://"):]
    if n.endswith("/manifest.json"):
        n = n[:-len("/manifest.json")]
    return n.rstrip("/")


def stremio_naslov(naslov: str) -> str:
    """Naslov dodatka, kot ga hrani Android: naslov manifesta."""
    return stremio_osnova(naslov) + "/manifest.json"


def kljuc(tip: str, naslov: str) -> str:
    return str(tip or "") + "|" + str(naslov or "")


def istovetnost(tip: str, naslov: str) -> str:
    """Po cem je vir isti na vseh napravah: dodatek po korenu, drugo po naslovu (vrsta je lahko na napravah razlicna)."""
    if tip == STREMIO:
        return "s:" + stremio_osnova(naslov).lower()
    return "u:" + str(naslov or "").strip().rstrip("/")


def istovetnost_kljuca(k: str) -> str:
    tip, _, naslov = str(k or "").partition("|")
    return istovetnost(tip, naslov)


def cist_vir(o: object) -> Optional[dict]:
    """Vir z druge naprave: znana vrsta, javen naslov, razumna dolzina - nic drugega ne prevzamemo."""
    if not isinstance(o, dict):
        return None
    tip, ime, naslov = str(o.get("tip") or ""), str(o.get("ime") or ""), str(o.get("naslov") or "")
    cas = o.get("cas")
    if not _VRSTE.fullmatch(tip) or not 4 <= len(naslov) <= 2048 or len(ime) > 200:
        return None
    if any(c < " " for c in naslov) or any(c < " " for c in ime):
        return None
    if tip != "peertube" and not naslov.startswith(("http://", "https://")):
        return None
    return {"tip": tip, "ime": ime, "naslov": naslov,
            "cas": int(cas) if isinstance(cas, (int, float)) and not isinstance(cas, bool) and cas > 0 else 0}


def vir_prevzamemo(imam: bool, moj_izbris: Optional[int], tuj_cas: int) -> bool:
    """Vir z druge naprave prevzamemo, ce ga tu ni in ga tu nismo izbrisali pozneje (ali hkrati), kot je bil tam dodan
    (SeznamiPravila.virPrevzamemo)."""
    return not imam and (-1 if moj_izbris is None else int(moj_izbris)) < int(tuj_cas or 0)


def izbris_vira_velja(moj_cas: int, tuj_izbris: int) -> bool:
    """Izbris vira na drugi napravi velja tudi tukaj, ce vira tu nismo dodali pozneje (SeznamiPravila.izbrisViraVelja)."""
    return int(tuj_izbris or 0) > 0 and int(tuj_izbris) > int(moj_cas or 0)


def nov_cas(zdaj: int, prej: int = 0, izbrisan: int = 0) -> int:
    """Cas krajevne spremembe: nikoli starejsi od prejsnjega stanja in znanega izbrisa (ure naprav niso enake)."""
    return max(int(zdaj), int(prej or 0) + 1, int(izbrisan or 0) + 1)


def cas_izbrisa(izbrisani: dict, tip: str, naslov: str) -> Optional[int]:
    """Kdaj smo ta vir tukaj izbrisali (ne glede na vrsto v kljucu); None = nikoli."""
    i = istovetnost(tip, naslov)
    casi = [int(c) for k, c in (izbrisani or {}).items() if isinstance(c, (int, float)) and istovetnost_kljuca(k) == i]
    return max(casi) if casi else None


def cisti_izbrisi(d: object) -> dict:
    """`sources_deleted` z druge naprave: {"tip|naslov": cas} z znano vrsto in pozitivnim casom."""
    if not isinstance(d, dict):
        return {}
    izid = {}
    for k, c in list(d.items())[:NAJVEC_IZBRISANIH]:
        if not isinstance(k, str) or len(k) > 2100 or not isinstance(c, (int, float)) or isinstance(c, bool) or c <= 0:
            continue
        if _VRSTE.fullmatch(k.partition("|")[0]):
            izid[k] = int(c)
    return izid


def obrezi_izbrisane(izbrisani: dict) -> dict:
    """Najvec [NAJVEC_IZBRISANIH] zadnjih izbrisov."""
    return dict(sorted(izbrisani.items(), key=lambda kv: kv[1], reverse=True)[:NAJVEC_IZBRISANIH])


# ------------------------------------------------------------------ prijava osebnih streznikov v naslovih
# Skladbe osebnih streznikov imajo prijavo v naslovu toka in ovitka: Jellyfin `ApiKey=<zeton>` (prej `api_key`), Emby
# `api_key`, Navidrome/Subsonic `u=…&t=md5(geslo+sol)&s=…`, Plex `X-Plex-Token`, Funkwhale `token`, Kodi in TVHeadend
# `uporabnik:geslo@`. Taki naslovi ne smejo v sezname, police ali na druge naprave (pregled 14. 10. 2026: »Shrani kot
# seznam« jih je pisal v seznami.json, lists.get pa jih je dal napravam v Linku). Shranimo naslov brez prijave;
# Medijski center jo doda ob predvajanju iz zbirke skrivnosti (MediaCenter.s_prijavo).

#: Parametri, ki so prijava ne glede na pot (male crke).
PARAMETRI_PRIJAVE = frozenset({"api_key", "apikey", "x-emby-token", "x-mediabrowser-token", "token", "access_token",
                               "x-plex-token"})
#: Parametri Subsonic API (Navidrome, Airsonic …): kratka imena, zato samo na poti /rest/ ali *.view - drugje (npr.
#: `t=` cas v posnetku) jih ne odstranimo.
PARAMETRI_SUBSONIC = frozenset({"u", "t", "s", "p"})


def je_subsonic(pot: str) -> bool:
    pot = str(pot or "").lower()
    return "/rest/" in pot or pot.startswith("rest/") or pot.endswith(".view")


def brez_prijave(url: object) -> str:
    """Naslov brez prijave: brez uporabnika in gesla pred gostiteljem in brez parametrov prijave. Drugo ostane enako."""
    besedilo = str(url or "")
    if not besedilo.lower().startswith(("http://", "https://")):
        return besedilo
    try:
        d = urllib.parse.urlsplit(besedilo)
    except ValueError:
        return ""
    gostitelj = d.netloc.rpartition("@")[2]
    subsonic = je_subsonic(d.path)
    deli = [x for x in d.query.split("&") if x]
    ostali = [x for x in deli if not (urllib.parse.unquote_plus(x.partition("=")[0]).lower() in PARAMETRI_PRIJAVE
                                     or (subsonic and urllib.parse.unquote_plus(x.partition("=")[0]).lower() in PARAMETRI_SUBSONIC))]
    if gostitelj == d.netloc and len(ostali) == len(deli):
        return besedilo
    return urllib.parse.urlunsplit((d.scheme, gostitelj, d.path, "&".join(ostali), d.fragment))


def ima_prijavo(url: object) -> bool:
    """Ali ima naslov prijavo (zeton, geslo ali uporabnika pred gostiteljem)."""
    return brez_prijave(url) != str(url or "")


def cista_skladba(s: object) -> object:
    """Skladba seznama (ali opis police) brez prijave v `url`, `slika` in `ozadje`. Ce je bila prijava odstranjena,
    dobi oznako `prijava`: Medijski center jo ob predvajanju doda s streznika (MediaCenter.s_prijavo)."""
    if not isinstance(s, dict):
        return s
    izid = dict(s)
    for polje in ("url", "slika", "ozadje"):
        if isinstance(izid.get(polje), str) and izid[polje]:
            cist = brez_prijave(izid[polje])
            if cist != izid[polje]:
                izid[polje] = cist
                izid["prijava"] = True
    return izid
