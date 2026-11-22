"""Spotify v Medijskem centru: predvajanje v skritem Safeer DRM, seznami, Vseckane pesmi in podkasti racuna.

Lastnik 17. 10. 2026: Spotify se predvaja ZNOTRAJ Medijskega centra z nasim Safeer DRM (Chromium z Widevine,
core/safeer_drm.py). Gumb »Prijava v Spotify« odpre Safeer DRM z open.spotify.com v vidnem oknu (prijavo opravi
uporabnik sam, na strani Spotifyja); po prijavi okno izgine, Safeer DRM tece skrit, Medijski center pa pokaze nas
vmesnik: sezname, Vseckane pesmi, oddaje (podkaste), trenutno skladbo, upravljanje predvajanja.

Upravljanje: CDP (Chrome DevTools Protocol) prek webContents.debugger v Safeer DRM (assets/safeer_drm/main.js) - brez
--remote-debugging-port. Tista vrata bi bila odprta vsakemu lokalnemu procesu (tudi drugim uporabnikom racunalnika) in
bi z njimi kdorkoli prevzel prijavo; zeton na vratih Chromium ne pozna. Ukazi gredo po ze obstojecem zasebnem kanalu
seje (command.txt v mapi seje, 0700, ki jo pise samo Safeer OS); odgovor vsake zahteve je v svoji datoteki
cdp-<id>.json, ki jo Kanal takoj po branju izbrise (vsebina strani ne ostane na disku). Dovoljen je le Runtime.evaluate.

Podatki: isti klici kot spletna aplikacija, iz strani in z zetonom strani (window.__safeerSpotify, main.js): GraphQL
(api-partner.spotify.com/pathfinder) z vzorcem, ki ga je stran ze poslala sama; rezerva je spletni API
(api.spotify.com/v1). Zeton ostane v strani - nikoli v datoteko, dnevnik ali Safeer Link. Seznami, ki jih uporabnik
shrani, so v Medijskem centru oznaceni "zaseben" (ostanejo na tej napravi).

Scit (privzeto vklopljen, nastavitev v Scitu): pravila core/scit_pravila (del »spotify«) v Safeer DRM, rezerva je zaznava
oglasa v predvajalniku. Oglas se SAMO utisa (lastnik 18. 10. 2026): nic preskakovanja, pospesevanja ali samodejne
»Naslednje« med oglasom.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Optional

from . import safeer_drm, uporabniske_skripte
from core import otroci, shramba_json

IZVOR = "https://open.spotify.com/"
#: Prijava v Spotify poteka v Spletu (WebKit Safeer OS), ne v Safeer DRM: Google prijavo v vgrajenih brskalnikih
#: aplikacij (Electron) zavrne s »Prijava ni bila mogoca - brskalnik morda ni varen«, kar bi uporabnika prestrasilo
#: (lastnik 17. 10. 2026). Po prijavi piskotke spotify.com prenesemo v profil Safeer DRM.
PRIJAVA_SPLET = "https://accounts.spotify.com/login?continue=https%3A%2F%2Fopen.spotify.com%2F"


def piskotki_spleta(pot: Optional[str] = None) -> list:
    """Piskotki *.spotify.com iz shrambe Spleta (samo branje) s polji za Electron cookies.set; [] brez prijave."""
    import sqlite3
    if pot is None:
        from .config import CONFIG_DIR
        pot = os.path.join(CONFIG_DIR, "cookies.sqlite")
    if not os.path.isfile(pot):
        return []
    try:
        povezava = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(os.path.abspath(pot)), uri=True, timeout=2)
        try:
            vrstice = povezava.execute("SELECT name, value, host, path, expiry, isSecure, isHttpOnly FROM moz_cookies "
                                       "WHERE host = 'spotify.com' OR host LIKE '%.spotify.com'").fetchall()
        finally:
            povezava.close()
    except sqlite3.Error:
        return []
    zdaj = time.time()
    return [{"name": str(i), "value": str(v), "domain": str(h), "path": str(p or "/"), "expirationDate": int(e or 0),
             "secure": bool(sec), "httpOnly": bool(ho)}
            for i, v, h, p, e, sec, ho in vrstice if i and v is not None and (not e or int(e) > zdaj)]


def prijavljen_v_spletu(piskotki: list) -> bool:
    return any(c["name"] == "sp_dc" and c["value"] for c in piskotki)
NAJVEC = 400                   # kot uvoz_seznama.NAJVEC: seznam Medijskega centra
_STRAN = 100                   # vnosov na klic
_KROGOV = 8
CAS_MIROVANJA = 600.0          # skrit Safeer DRM brez predvajanja in brez klicev se po 10 min ustavi (pomnilnik)


def _sled(besedilo: str) -> None:
    """Odlocitve strazarja v sled.log (stderr), brez naslovov skladb: po zastoju vemo, kaj se je zgodilo (18. 10. 2026
    se je predvajanje ustavilo, dnevnik seje pa je bil ob koncu Safeer DRM izbrisan)."""
    print("[Spotify]", time.strftime("%H:%M:%S"), besedilo, file=sys.stderr, flush=True)
VSECKANE = "vseckane"

URI = re.compile(r"^spotify:(track|episode|playlist|show|album|artist|user|collection)(?::[A-Za-z0-9]+)+$")
ID = re.compile(r"^[A-Za-z0-9]{10,40}$")


class NiDrm(Exception):
    """Safeer DRM ni prenesen (ali ga ni mogoce zagnati)."""


class NiOdziva(Exception):
    """Safeer DRM ne tece ali ni odgovoril v casu."""


class PoteklaPrijava(Exception):
    """Spotify zahteve ne sprejme vec (odjava drugje, potekla seja)."""


class SpremenjenaStran(Exception):
    """Stran ali njen odgovor nista vec taka, kot ju poznamo."""


# ---------------------------------------------------------------------------------------------- razclenjevanje (cisto)

def _niz(x: Any) -> str:
    return str(x).strip() if isinstance(x, (str, int, float)) else ""


def _uri(d: dict) -> str:
    u = _niz(d.get("uri") or d.get("_uri"))
    return u if URI.match(u) else ""


def _slika(d: Any, globina: int = 0) -> str:
    """Najvecji naslov slike (images / sources / coverArt / albumOfTrack ...), tudi globoko v odgovoru GraphQL."""
    if globina > 5:
        return ""
    if isinstance(d, list):
        kandidati = []
        for x in d:
            if isinstance(x, dict) and isinstance(x.get("url"), str) and x["url"].startswith("https://"):
                kandidati.append((int(x.get("width") or 0) if str(x.get("width") or "").isdigit() else 0, x["url"]))
        if kandidati:
            return max(kandidati)[1] if any(k[0] for k in kandidati) else kandidati[0][1]
        for x in d:
            s = _slika(x, globina + 1)
            if s:
                return s
        return ""
    if not isinstance(d, dict):
        return ""
    for k in ("images", "sources", "coverArt", "image", "visualIdentity", "album", "albumOfTrack", "squareCoverImage",
              "items", "data"):
        if k in d:
            s = _slika(d[k], globina + 1)
            if s:
                return s
    return ""


def _izvajalci(d: dict) -> str:
    """Imena izvajalcev (v1: artists[].name; GraphQL: artists.items[].profile.name) ali zalozba oddaje."""
    a = d.get("artists")
    if isinstance(a, dict):
        a = a.get("items")
    imena = []
    for x in a if isinstance(a, list) else []:
        if isinstance(x, dict):
            profil = x.get("profile") if isinstance(x.get("profile"), dict) else {}
            ime = _niz(x.get("name") or profil.get("name"))
            if ime:
                imena.append(ime)
    if imena:
        return ", ".join(imena)
    for k in ("publisher", "podcastV2", "show"):
        v = d.get(k)
        if isinstance(v, dict):
            v = v.get("name") or ((v.get("data") or {}).get("name") if isinstance(v.get("data"), dict) else "")
        if _niz(v):
            return _niz(v)
    return ""


def _ms(d: dict) -> int:
    for k in ("duration_ms",):
        if isinstance(d.get(k), (int, float)):
            return int(d[k])
    for k in ("duration", "trackDuration"):
        v = d.get(k)
        if isinstance(v, dict) and isinstance(v.get("totalMilliseconds"), (int, float)):
            return int(v["totalMilliseconds"])
    return 0


def entitete(o: Any, vrste: tuple = ("track", "episode")) -> list[dict]:
    """Vse entitete danih vrst v odgovoru (spletni API ali GraphQL - oblika se spreminja, zato hodimo po drevesu in
    prepoznamo predmet po naslovu spotify:<vrsta>:<id> in imenu). Vrstni red kot v odgovoru, brez ponovitev."""
    izid: list[dict] = []
    videni: set = set()

    def hodi(x: Any, globina: int) -> None:
        if globina > 14 or len(izid) >= NAJVEC * 2:
            return
        if isinstance(x, list):
            for y in x:
                hodi(y, globina + 1)
            return
        if not isinstance(x, dict):
            return
        uri = _uri(x)
        podatki = x.get("data") if isinstance(x.get("data"), dict) else x
        ime = _niz(podatki.get("name"))
        vrsta = uri.split(":")[1] if uri else ""
        if uri and vrsta in vrste and ime and uri not in videni:
            if podatki.get("__typename") not in (None, "Track", "Episode", "Playlist", "Podcast", "Show", "Album") \
                    and vrsta in ("track", "episode"):
                return            # npr. NotFound / RestrictedContent
            videni.add(uri)
            izid.append({"uri": uri, "vrsta": vrsta, "ime": ime, "podatki": podatki, "ovoj": x})
            return
        for k, v in x.items():
            if k in ("artists", "albumOfTrack", "album", "owner", "ownerV2", "coverArt", "images"):
                continue
            hodi(v, globina + 1)

    hodi(o, 0)
    return izid


def skladba(e: dict) -> dict:
    """Entiteta (track/episode) -> skladba seznama Medijskega centra (kot uvoz_seznama; youtube prazen: brez prijave
    v Spotify Medijski center skladbo poisce na YouTubu, kot pri uvozu javnega seznama)."""
    d = e["podatki"]
    return {"naslov": e["ime"][:300], "izvajalec": _izvajalci(d)[:200], "youtube": "", "slika": _slika(d)[:2048],
            "sekund": _ms(d) // 1000, "spotify": e["uri"]}


def skladbe_iz(o: Any) -> list[dict]:
    return [skladba(e) for e in entitete(o, ("track", "episode"))]


def seznami_iz(o: Any) -> list[dict]:
    """Seznami predvajanja racuna (GraphQL libraryV3 ali v1 me/playlists): [{id, ime, slika, stevilo}]."""
    izid = []
    for e in entitete(o, ("playlist",)):
        d = e["podatki"]
        stevilo = 0
        for k in ("tracks", "items", "content"):
            v = d.get(k)
            if isinstance(v, dict) and isinstance(v.get("total", v.get("totalCount")), int):
                stevilo = int(v.get("total", v.get("totalCount")))
        izid.append({"id": e["uri"].split(":")[-1], "ime": e["ime"][:120], "slika": _slika(d)[:2048], "stevilo": stevilo})
    return izid


def oddaje_iz(o: Any) -> list[dict]:
    """Oddaje (podkasti), ki jim uporabnik sledi: [{id, ime, avtor, slika}]."""
    izid = []
    for e in entitete(o, ("show",)):
        d = e["podatki"]
        izid.append({"id": e["uri"].split(":")[-1], "ime": e["ime"][:120], "avtor": _izvajalci(d)[:120],
                     "slika": _slika(d)[:2048]})
    return izid


def cas_v_sekunde(besedilo: Any) -> int:
    """»3:07«, »1:02:03« ali »-0:42« (preostanek) -> sekunde; neznano 0."""
    m = re.fullmatch(r"-?(\d{1,2}:)?(\d{1,2}):(\d{2})", _niz(besedilo))
    if not m:
        return 0
    ure = int((m.group(1) or "0:")[:-1])
    return ure * 3600 + int(m.group(2)) * 60 + int(m.group(3))


#: Besede, s katerimi Spotify oglas oznaci v predvajalniku (jezik vmesnika je uporabnikov).
_OGLAS = re.compile(r"(?i)^(advertisement|ad|oglas|werbung|anzeige|anuncio|publicidad|publicité|annonce|pubblicità|annuncio)$")


def je_oglas(s: dict) -> bool:
    """Ali predvajalnik ta trenutek predvaja oglas (stanje iz STANJE_JS). Rajsi zgresimo oglas kot utisamo pesem:
    navadne skladbe in epizode imajo povezavo /track/ ali /episode/."""
    if not isinstance(s, dict):
        return False
    if s.get("oglas_oznaka"):
        return True
    povezava = _niz(s.get("povezava"))
    if re.search(r"(^|/)ad(s)?(/|$)|adclick|doubleclick", povezava):
        return True
    if povezava.startswith(("http://", "https://")) and not re.match(r"https://open\.spotify\.com/", povezava):
        return True
    naslov, izvajalec = _niz(s.get("naslov")), _niz(s.get("izvajalec"))
    if _OGLAS.match(naslov) or _OGLAS.match(izvajalec):
        return True
    if naslov and izvajalec == "Spotify" and not povezava:
        return True
    return False


def stanje_iz(s: Any) -> dict:
    """Surovo stanje strani -> stanje za Medijski center (brez naslovov strani in zetonov)."""
    s = s if isinstance(s, dict) else {}
    nap = s.get("napredek") if isinstance(s.get("napredek"), dict) else {}
    gl = s.get("glasnost") if isinstance(s.get("glasnost"), dict) else {}

    def delez(r: dict) -> Optional[float]:
        try:
            lo, hi, v = float(r.get("min") or 0), float(r.get("max") or 0), float(r.get("v"))
        except (TypeError, ValueError):
            return None
        return max(0.0, min(1.0, (v - lo) / (hi - lo))) if hi > lo else None

    trajanje = cas_v_sekunde(s.get("trajanje"))
    polozaj = cas_v_sekunde(s.get("polozaj"))
    if _niz(s.get("trajanje")).startswith("-"):
        trajanje += polozaj            # prikaz preostanka: trajanje = polozaj + preostanek
    d = delez(nap)
    if not polozaj and d is not None and trajanje:
        polozaj = int(round(d * trajanje))
    slika = _niz(s.get("slika"))
    return {
        "naslov": _niz(s.get("naslov"))[:300], "izvajalec": _niz(s.get("izvajalec"))[:200],
        "slika": slika if slika.startswith("https://") else "",
        "igra": bool(s.get("igra")), "polozaj": polozaj, "trajanje": trajanje,
        "glasnost": delez(gl), "oglas": je_oglas(s), "utisano": bool(s.get("utisano")),
    }


def je_oglasna_zahteva(url: str, pravila: dict) -> bool:
    """Ista pravila kot oglasnaZahteva v assets/safeer_drm/main.js (za preizkuse in pregled pravil)."""
    try:
        u = urllib.parse.urlsplit(str(url or ""))
    except ValueError:
        return False
    h = (u.hostname or "").lower()
    if not h:
        return False
    if any(h == d or h.endswith("." + d) for d in pravila.get("gostitelji") or []):
        return True
    pot = (u.path or "/") + ("?" + u.query if u.query else "")      # kot main.js: pathname + search
    return any((h == d or h.endswith("." + d)) and pot.startswith(p) for d, p in pravila.get("poti") or [])


def pravila_scita() -> dict:
    """Pravila Scita za sejo Spotify v Safeer DRM: oglasi Spotifyja ter sledilci in telemetrija tretjih - iz seznama
    Scita (core/scit_pravila.py: vgrajen ali novejsi podpisan)."""
    from . import scit_pravila
    return scit_pravila.trenutna().za_drm(spotify=True)


# ---------------------------------------------------------------------------------------------- JavaScript v strani

#: Stanje predvajalnika (gumbi in oznake data-testid spletnega predvajalnika, preverjeno 17. 10. 2026; Media Session).
STANJE_JS = r"""(() => {
  const S = window.__safeerSpotify, q = s => document.querySelector(s), tx = e => e ? (e.textContent || '').trim() : '';
  const md = navigator.mediaSession && navigator.mediaSession.metadata;
  const m = S ? S.mediji() : [];
  const obseg = s => { const i = q(s + ' input[type="range"]'); return i ? { v: Number(i.value), min: Number(i.min || 0), max: Number(i.max || 0) } : null; };
  const pov = q('[data-testid="context-item-info-title"] a') || q('[data-testid="context-item-link"]');
  const slike = md && md.artwork ? Array.from(md.artwork) : [];
  const slika = slike.length ? slike[slike.length - 1].src : ((q('[data-testid="now-playing-widget"] img') || {}).src || '');
  const uporabnik = q('[data-testid="user-widget-link"]');
  return {
    skripta: Boolean(S), zeton: Boolean(S && S.imaZeton()), prijava: Boolean(q('[data-testid="login-button"]')),
    uporabnik: Boolean(uporabnik), ime: uporabnik ? (uporabnik.getAttribute('aria-label') || '') : '',
    predvajalnik: Boolean(q('[data-testid="control-button-playpause"]')),
    naslov: (md && md.title) || tx(q('[data-testid="context-item-info-title"]')),
    izvajalec: (md && md.artist) || tx(q('[data-testid="context-item-info-artist"]')),
    slika, povezava: pov ? (pov.getAttribute('href') || '') : '',
    igra: m.some(x => !x.paused && !x.ended),
    polozaj: tx(q('[data-testid="playback-position"]')), trajanje: tx(q('[data-testid="playback-duration"]')),
    napredek: obseg('[data-testid="playback-progressbar"]'), glasnost: obseg('[data-testid="volume-bar"]'),
    oglas_oznaka: Boolean(q('[data-testid="context-item-info-ad-subtitle"], [data-testid="ad-type-label"], [data-testid="advertisement-label"], [data-testid="now-playing-bar"] a[href*="/ad/"]')),
    utisano: Boolean(S && S.jeUtisano())
  };
})()"""

#: Klik na gumb predvajalnika (data-testid); vrne, ali je gumb obstajal.
GUMB_JS = r"""((id) => { const b = document.querySelector('[data-testid="' + id + '"]'); if (!b || b.disabled) return false; b.click(); return true; })(%s)"""

#: Preklopni gumb Predvajaj/Premor s preverbo v ISTEM izrazu (brez tekme med branjem stanja in klikom - gumb je
#: preklopni, zastarelo stanje bi ga sprozilo v napacno smer). zelja: "igraj" (klik samo, ce ne igra), "ustavi" (klik
#: samo, ce igra) ali "preklopi". Vrne "igra" | "premor" (stanje PO izrazu) ali false (gumba ni).
PREKLOP_JS = r"""((zelja) => {
  const b = document.querySelector('[data-testid="control-button-playpause"]');
  if (!b || b.disabled) return false;
  const igra = (window.__safeerSpotify ? window.__safeerSpotify.mediji() : []).some(x => !x.paused && !x.ended);
  if ((zelja === 'igraj' && igra) || (zelja === 'ustavi' && !igra)) return igra ? 'igra' : 'premor';
  b.click();
  return igra ? 'premor' : 'igra';
})(%s)"""

#: Drsnik (cas ali glasnost) na delez 0..1: vrednost vnosa (React) in klik kazalca na isto mesto.
DRSNIK_JS = r"""((id, delez) => {
  const okvir = document.querySelector('[data-testid="' + id + '"]');
  if (!okvir) return false;
  const i = okvir.querySelector('input[type="range"]');
  if (i) {
    const lo = Number(i.min || 0), hi = Number(i.max || 0);
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(i, String(lo + (hi - lo) * delez));
    i.dispatchEvent(new Event('input', { bubbles: true })); i.dispatchEvent(new Event('change', { bubbles: true }));
  }
  const r = okvir.getBoundingClientRect(), x = r.left + r.width * delez, y = r.top + r.height / 2;
  for (const t of ['pointerdown', 'mousedown', 'pointerup', 'mouseup']) {
    const E = t.startsWith('pointer') ? PointerEvent : MouseEvent;
    okvir.dispatchEvent(new E(t, { bubbles: true, clientX: x, clientY: y, button: 0, buttons: t.endsWith('down') ? 1 : 0 }));
  }
  return true;
})(%s, %s)"""

#: Gumb Predvajaj strani: vrstica dejanj (seznam, Vseckane); na strani epizode ali skladbe prvi gumb v vsebini
#: (preverjeno 17. 10. 2026: stran oddaje vrstice dejanj nima, prvi gumb tam je najnovejsa epizoda).
_GUMB = r"""() => document.querySelector('[data-testid="action-bar-row"] [data-testid="play-button"]')
    || (/^\/(episode|track)\//.test(location.pathname) ? document.querySelector('main [data-testid="play-button"]') : null)"""

#: Premik strani v spletni aplikaciji (history + popstate, brez ponovnega nalaganja; izmerjeno 1 s), nato caka na gumb
#: Predvajaj ali (vzorec) na klic GraphQL, ki ga stran ob tem poslje sama.
POJDI_JS = r"""(async (pot, vzorec) => {
  const cakaj = ms => new Promise(r => setTimeout(r, ms)), gumb = """ + _GUMB + r""";
  if (location.pathname !== pot) {
    history.pushState({}, '', pot);
    window.dispatchEvent(new PopStateEvent('popstate', { state: {} }));
  }
  for (let i = 0; i < 40; i++) {
    await cakaj(200);
    if (vzorec ? window.__safeerSpotify && window.__safeerSpotify.vzorci().includes(vzorec) : gumb()) return 'ok';
  }
  return 'ni';
})(%s, %s)"""

#: Predvajanje: vrstica s skladbo (dvoklik) ali gumb Predvajaj v vrstici dejanj.
PREDVAJAJ_JS = r"""(async (cilj) => {
  const cakaj = ms => new Promise(r => setTimeout(r, ms)), gumb = """ + _GUMB + r""";
  if (cilj) {
    for (let i = 0; i < 10; i++) {
      const a = document.querySelector('[data-testid="tracklist-row"] a[href$="' + cilj + '"]');
      const vr = a && a.closest('[data-testid="tracklist-row"]');
      if (vr) { vr.dispatchEvent(new MouseEvent('dblclick', { bubbles: true })); return 'vrstica'; }
      await cakaj(200);
    }
  }
  const b = gumb();
  if (!b) return 'ni';
  // Ta seznam ze igra (gumb kaze premor): klik bi ga ustavil.
  const igra = (window.__safeerSpotify ? window.__safeerSpotify.mediji() : []).some(x => !x.paused);
  if (!(igra && /paus|premor/i.test(b.getAttribute('aria-label') || ''))) b.click();
  return cilj ? 'zacetek' : 'ok';
})(%s)"""


def _js(x: Any) -> str:
    return json.dumps(x, ensure_ascii=True)


# ---------------------------------------------------------------------------------------------- kanal do Safeer DRM

class Kanal:
    """En proces Safeer DRM za Spotify (skrit ali v oknu za prijavo) in zasebni kanal ukazov CDP do njega."""

    def __init__(self, zazeni: Optional[Callable[[list, dict], Any]] = None, mapa: Optional[str] = None) -> None:
        self._zazeni = zazeni or self._popen
        self._mapa = mapa
        self._zaklep = threading.Lock()
        self.proces = None
        self.seja = self.stanje = self.ukazi = ""
        self.vidno = False
        self.nalozeno = False          # NAVIGATION_OK (stran naloze)
        self._id = 0
        self._cakajo: dict[int, list] = {}
        self._odmik = 0
        self._bralec: Optional[threading.Thread] = None
        self.konec_cb: Optional[Callable[[], None]] = None

    @staticmethod
    def _popen(args: list, okolje: Optional[dict]) -> Any:
        # Brskalnik prijave s svojimi procesi v svoji skupini; ustavi() in izhod procesa koncata vse (naloga 41).
        return otroci.zazeni(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                             env=okolje, dolgoziv=True)

    @staticmethod
    def profil() -> Path:
        """Svoj stalen profil (ne skupni profil storitev): skrit Spotify in Netflix v zavihku hkrati ne pisete v iste
        baze Chromiuma."""
        return safeer_drm.koren() / "profil-spotify"

    def tece(self) -> bool:
        return self.proces is not None and self.proces.poll() is None

    def zacni(self, vidno: bool, scit: bool, piskotki: Optional[list] = None) -> str:
        """»ok«, »ni_drm« (Safeer DRM ni v tej namestitvi) ali »napaka«."""
        with self._zaklep:
            if self.tece():
                if vidno != self.vidno:
                    self.ukaz("pokazi" if vidno else "skrij")
                    self.vidno = vidno
                return "ok"
            exe = safeer_drm.izvrsljiva()
            if exe is None:
                return "ni_drm"
            mapa = Path(self._mapa) if self._mapa else safeer_drm.mapa_sej()
            mapa.mkdir(parents=True, exist_ok=True)
            self.seja = tempfile.mkdtemp(prefix="spotify-", dir=str(mapa))
            self.stanje = os.path.join(self.seja, "events.jsonl")
            self.ukazi = os.path.join(self.seja, "command.txt")
            args = [str(exe), "--url=" + IZVOR, "--profile=" + str(self.profil()), "--state=" + self.stanje,
                    "--command=" + self.ukazi, "--storitev=1", "--spotify=1"]
            if not vidno:
                args.append("--skrit=1")
            if piskotki:
                pot_p = os.path.join(self.seja, "piskotki.json")
                with open(pot_p, "w", encoding="utf-8") as f:
                    json.dump(piskotki, f)
                os.chmod(pot_p, 0o600)
                args.append("--cookies=" + pot_p)
            if scit:
                pot = os.path.join(self.seja, "scit.json")
                with open(pot, "w", encoding="utf-8") as f:
                    json.dump(pravila_scita(), f)
                args.append("--scit=" + pot)
            skripte = uporabniske_skripte.aktivne_js()
            if skripte:
                pot_s = os.path.join(self.seja, "skripte.json")
                with open(pot_s, "w", encoding="utf-8") as f:
                    json.dump(skripte, f)
                os.chmod(pot_s, 0o600)
                args.append("--skripte=" + pot_s)
            peskovnik = safeer_drm.v_peskovniku()
            na_gostitelju = safeer_drm.v_flatpaku() and not peskovnik
            if not na_gostitelju:
                args.append("--lastnik=%d" % os.getpid())     # Safeer OS se konca: Spotify ne igra naprej sam
            ukaz = safeer_drm.ukaz_zagona(args, peskovnik=peskovnik, gostitelj=na_gostitelju)
            if ukaz is None:
                self._pospravi()
                return "napaka"
            try:
                self.proces = self._zazeni(ukaz, safeer_drm.okolje_zagona(peskovnik))
            except OSError as e:
                print("[Spotify] zagon Safeer DRM ni uspel:", type(e).__name__, flush=True)
                self._pospravi()
                return "napaka"
            self.vidno, self.nalozeno, self._odmik = vidno, False, 0
            self._bralec = threading.Thread(target=self._beri_zanka, name="spotify-drm", daemon=True)
            self._bralec.start()
            return "ok"

    def ukaz(self, vrstica: str) -> bool:
        if not self.ukazi or "\n" in vrstica:
            return False
        try:
            with open(self.ukazi, "a", encoding="utf-8") as f:
                f.write(vrstica + "\n")
            return True
        except OSError:
            return False

    def izvedi(self, izraz: str, cas: float = 15.0) -> Any:
        """Runtime.evaluate v strani (obljuba se pocaka, vrednost kot JSON). NiOdziva ali SpremenjenaStran (izjema)."""
        if not self.tece():
            raise NiOdziva()
        with self._zaklep:
            self._id += 1
            ident = self._id
            cakanje = [threading.Event(), None]
            self._cakajo[ident] = cakanje
        zahteva = base64.b64encode(json.dumps({"expression": izraz, "timeout": int(cas * 1000)}).encode("utf-8")).decode("ascii")
        if not self.ukaz("cdp:%d:%s" % (ident, zahteva)):
            self._cakajo.pop(ident, None)
            raise NiOdziva()
        dobil = cakanje[0].wait(cas + 2.0)
        self._cakajo.pop(ident, None)
        if not dobil or not isinstance(cakanje[1], dict):
            raise NiOdziva()
        odgovor = cakanje[1]
        if odgovor.get("napaka") == "izjema":
            raise SpremenjenaStran()
        if odgovor.get("napaka"):
            raise NiOdziva()
        return odgovor.get("vrednost")

    def obdelaj(self, vrstica: str) -> None:
        """Ena vrstica events.jsonl (main.js). Odgovor CDP v dnevniku je le se za starejsi main.js."""
        try:
            d = json.loads(vrstica)
        except ValueError:
            return
        if not isinstance(d, dict):
            return
        vrsta = d.get("type")
        if vrsta == "NAVIGATION_OK":
            self.nalozeno = True
        elif vrsta == "CDP":
            self._odgovor(str(d.get("detail") or ""))

    def _odgovor(self, besedilo: str) -> None:
        """Odgovor CDP ({"id", "vrednost" | "napaka"}) gre cakajocemu klicu."""
        try:
            o = json.loads(besedilo)
            cakanje = self._cakajo.get(int(o.get("id")))
        except (ValueError, TypeError, AttributeError):
            return
        if cakanje is not None:
            cakanje[1] = o
            cakanje[0].set()

    _ODGOVOR = re.compile(r"^cdp-([0-9]{1,12})\.json$")

    def _beri_odgovore(self) -> None:
        """Datoteke odgovorov cdp-<id>.json (main.js odgovorCdp): preberemo in takoj izbrisemo - vsebina strani ne
        ostane na disku. Odgovor, na katerega nihce vec ne caka (cas je potekel), se samo izbrise."""
        seja = self.seja
        if not seja:
            return
        try:
            vnosi = list(os.scandir(seja))
        except OSError:
            return
        for v in vnosi:
            m = self._ODGOVOR.match(v.name)
            if not m:
                continue
            besedilo = ""
            if int(m.group(1)) in self._cakajo:
                try:
                    with open(v.path, "r", encoding="utf-8") as f:
                        besedilo = f.read(8 * 1024 * 1024)
                except OSError:
                    continue
            try:
                os.unlink(v.path)
            except OSError:
                pass
            if besedilo:
                self._odgovor(besedilo)

    def _preberi_dnevnik(self, f: Any) -> None:
        f.seek(self._odmik)
        novo = f.read()
        # samo cele vrstice: zadnja je lahko se v pisanju
        konec = novo.rfind(b"\n") + 1
        self._odmik += konec
        for vrstica in novo[:konec].decode("utf-8", "replace").splitlines():
            self.obdelaj(vrstica)

    def _beri_dnevnik(self, ino: Optional[int]) -> Optional[int]:
        """events.jsonl od zadnjega odmika. main.js ga pri ~1 MB zamenja (events.jsonl -> events.jsonl.1): ce se je
        datoteka zamenjala, najprej preberemo se konec stare, nato novo od zacetka. Beremo iz iste odprte datoteke,
        katere inode smo preverili (zamenjava vmes ne pomesa odmikov). Vrne inode trenutne datoteke."""
        try:
            f = open(self.stanje, "rb")
        except OSError:
            f = None
        try:
            zdaj = os.fstat(f.fileno()).st_ino if f is not None else None
            if ino is not None and zdaj != ino:
                try:
                    with open(self.stanje + ".1", "rb") as stara:
                        if os.fstat(stara.fileno()).st_ino == ino:
                            self._preberi_dnevnik(stara)
                except OSError:
                    pass
                self._odmik = 0
            if f is not None:
                self._preberi_dnevnik(f)
        finally:
            if f is not None:
                f.close()
        return zdaj

    def _beri_zanka(self) -> None:
        proces = self.proces
        ino: Optional[int] = None
        while proces is not None and proces is self.proces:
            try:
                ino = self._beri_dnevnik(ino)
            except OSError:
                pass
            self._beri_odgovore()
            if proces.poll() is not None:
                break
            time.sleep(0.05)
        if proces is self.proces:
            with self._zaklep:
                self._pospravi()
            for c in list(self._cakajo.values()):
                c[0].set()
            if self.konec_cb:
                self.konec_cb()

    def _pospravi(self) -> None:
        if self.seja:
            shutil.rmtree(self.seja, ignore_errors=True)
        self.seja = self.stanje = self.ukazi = ""
        self.proces = None
        self.nalozeno = False

    def ustavi(self) -> None:
        with self._zaklep:
            p = self.proces
            self.proces = None
        if p is not None and p.poll() is None:
            otroci.ustavi(p, rok=5)
        with self._zaklep:
            self._pospravi()
        for c in list(self._cakajo.values()):
            c[0].set()


# ---------------------------------------------------------------------------------------------- racun

class Racun:
    """Spotify racun za Medijski center (en primerek, klici iz delovnih niti Medijskega centra)."""

    def __init__(self, mapa_nastavitev: str, kanal: Optional[Kanal] = None, ura: Callable[[], float] = time.monotonic,
                 na_voljo: Optional[Callable[[], bool]] = None, straza: bool = True) -> None:
        self.pot = Path(mapa_nastavitev) / "spotify.json"
        self.kanal = kanal or Kanal()
        self.kanal.konec_cb = self._ob_koncu
        self._ura = ura
        self._na_voljo = na_voljo or (lambda: safeer_drm.izvrsljiva() is not None)
        self._zaklep = threading.Lock()
        self._ustavljam = threading.Lock()
        self._predvajanje: dict = {}
        self._prijavljen = False
        self._ime = ""
        self._dotik = ura()
        self._utisal = False
        self._zastoj_od = 0.0             # od kdaj predvajalnik stoji v oglasu (po utisanju), 0 = ne stoji
        self._zastoj_korak = 0
        # Ali uporabnik zeli, da Spotify igra: True ob njegovem Predvajaj (ali ko opazimo, da pesem igra), False ob
        # njegovem Premoru/Ustavi (tudi »ustavi« iz Medijskega centra ob drugi vsebini) ali ko pesem obstane brez oglasa.
        # Strazar zastoja po oglasu pritisne Predvajaj SAMO, ce je True - uporabnikovega premora nikoli ne razveljavi.
        self._uporabnik_igra = False
        self._ukaz_st = 0                 # stevec ukazov uporabnika: zastarelo branje stanja ne povozi zadnjega ukaza
        self._pesem_stoji_od = 0.0        # od kdaj pesem (ne oglas) stoji; 0 = igra ali ni znano
        self._oglas_konec_od = 0.0        # kdaj se je zadnji oglas koncal (okno za zastoj po oglasu); 0 = ni
        self._straza: Optional[threading.Thread] = None
        self._z_strazo = straza
        self._preverjeno = False          # stran je ze povedala, ali je uporabnik prijavljen
        #: Klic ob spremembi vidnega stanja (skladba, igra, oglas): namizje in MPRIS jo pokazeta takoj (safeer_os
        #: _sp_spremenjeno), ne sele ob naslednjem branju. Klice ga nit strazarja.
        self.ob_spremembi: Optional[Callable[[], None]] = None

    #: Polja stanja, ki jih kazejo pripomocki (namizje, MPRIS); njihova sprememba gre takoj naprej (ob_spremembi).
    VIDNA_POLJA = ("naslov", "izvajalec", "slika", "igra", "oglas")

    def _nastavi_predvajanje(self, stanje: dict) -> None:
        prej, self._predvajanje = self._predvajanje, stanje
        if self.ob_spremembi is not None and any(prej.get(k) != stanje.get(k) for k in self.VIDNA_POLJA):
            try:
                self.ob_spremembi()
            except Exception:  # noqa: BLE001 - pripomocek ne sme ustaviti strazarja
                pass

    # -- nastavitve (samo stikala, nikoli prijava ali zetoni)
    def _nastavitve(self) -> dict:
        try:
            d = json.loads(self.pot.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _shrani(self, **sprememba: Any) -> None:
        d = dict(self._nastavitve(), **sprememba)
        try:
            self.pot.parent.mkdir(parents=True, exist_ok=True)
            shramba_json.zapisi_atomsko(self.pot, d, indent=None)
        except OSError:
            pass

    def scit(self) -> bool:
        return bool(self._nastavitve().get("scit", True))

    def nastavi_scit(self, vklop: bool) -> dict:
        self._shrani(scit=bool(vklop))
        if not vklop and self._utisal:
            self._utisaj(False)
        # Pravila veljajo ob zagonu Safeer DRM: ob spremembi skrit predvajalnik, ki ne igra, zazenemo znova ob potrebi.
        if self.kanal.tece() and not self._predvajanje.get("igra") and not self.kanal.vidno:
            self.kanal.ustavi()
        return {"scit": self.scit()}

    # -- zivljenjski krog
    def _ob_koncu(self) -> None:
        self._nastavi_predvajanje({})
        self._utisal = self._preverjeno = False
        self._uporabnik_igra = False
        self._pesem_stoji_od = 0.0

    def _uporabnik(self, igra: bool) -> None:
        self._ukaz_st += 1
        self._uporabnik_igra = igra
        if not igra:
            self._zastoj_od, self._zastoj_korak = 0.0, 0

    def _dotakni(self) -> None:
        self._dotik = self._ura()

    def _zagotovi(self) -> None:
        """Skrit Safeer DRM tece in stran je nalozena (ali NiDrm / NiOdziva)."""
        self._dotakni()
        if not self._na_voljo():
            raise NiDrm()
        izid = self.kanal.zacni(False, self.scit()) if not self.kanal.tece() else "ok"
        if izid == "ni_drm":
            raise NiDrm()
        if izid != "ok":
            raise NiOdziva()
        self._zazeni_strazo()
        konec = self._ura() + 30
        while not self.kanal.nalozeno and self._ura() < konec and self.kanal.tece():
            time.sleep(0.2)
        if not self.kanal.nalozeno:
            raise NiOdziva()
        if self._preverjeno:
            return
        # skripta strani potrebuje trenutek, da dobi zeton prve zahteve strani
        for _ in range(40):
            s = self.kanal.izvedi(STANJE_JS, 5)
            if isinstance(s, dict) and s.get("zeton") and s.get("predvajalnik"):
                self._posodobi_prijavo(s)
                return
            time.sleep(0.25)
        raise SpremenjenaStran()

    def _posodobi_prijavo(self, s: dict) -> None:
        # Med prijavo (accounts.spotify.com) ni predvajalnika: o prijavi odloca sele spletna aplikacija.
        if not s.get("predvajalnik"):
            return
        self._preverjeno = True
        prijavljen = bool(s.get("zeton")) and not s.get("prijava")
        if prijavljen:
            self._ime = _niz(s.get("ime"))[:80]
            if not self._nastavitve().get("prijavljen"):
                self._shrani(prijavljen=True)
            if self.kanal.vidno:
                self.kanal.zacni(False, self.scit())          # prijava je koncana: okno izgine, predvajalnik ostane
        self._prijavljen = prijavljen

    def _zazeni_strazo(self) -> None:
        if not self._z_strazo:
            return
        if self._straza is not None and self._straza.is_alive():
            return
        self._straza = threading.Thread(target=self._straza_zanka, name="spotify-straza", daemon=True)
        self._straza.start()

    def _straza_zanka(self) -> None:
        """Vsako sekundo: stanje predvajanja (za vmesnik), rezerva Scita (oglas samo utisa), konec prijave v oknu in
        mirovanje (skrit Safeer DRM brez predvajanja se po CAS_MIROVANJA ustavi)."""
        while self.kanal.tece():
            st = self._ukaz_st
            try:
                surovo = self.kanal.izvedi(STANJE_JS, 5)
            except (NiOdziva, SpremenjenaStran):
                surovo = None
            if isinstance(surovo, dict):
                self.straza_korak(surovo, st)
            if not self.kanal.vidno and not self._predvajanje.get("igra") and self._ura() - self._dotik > CAS_MIROVANJA:
                _sled("mirovanje %.0f min brez predvajanja: Safeer DRM ustavljen" % (CAS_MIROVANJA / 60))
                self.kanal.ustavi()
                break
            # Med oglasom pogosteje: utisanje takoj, ko se oglas zacne, in zvok takoj, ko se konca.
            time.sleep(0.4 if self._predvajanje.get("oglas") else 1.0)

    def straza_korak(self, surovo: dict, ukaz_st: Optional[int] = None) -> dict:
        """ukaz_st: stevec ukazov uporabnika PRED branjem stanja; ce se je medtem spremenil, je stanje zastarelo za
        odlocitev, ali uporabnik zeli predvajanje."""
        stanje = stanje_iz(surovo)
        if surovo.get("zeton"):
            self._posodobi_prijavo(surovo)
        if stanje["igra"]:
            self._dotakni()
        sveze = ukaz_st is None or ukaz_st == self._ukaz_st
        prej_oglas = bool(self._predvajanje.get("oglas"))
        if stanje["oglas"] and not prej_oglas:
            _sled("oglas se je zacel (utisam)" if self.scit() else "oglas se je zacel")
        elif prej_oglas and not stanje["oglas"]:
            self._oglas_konec_od = self._ura()
            _sled("oglas se je koncal, pesem %s" % ("igra" if stanje["igra"] else "stoji"))
        if stanje["igra"]:
            self._oglas_konec_od = 0.0
        if stanje["oglas"] or stanje["igra"]:
            self._pesem_stoji_od = 0.0
        if sveze and not stanje["oglas"] and stanje["naslov"]:
            # Pesem (ne oglas): igra -> uporabnik jo poslusa; stoji dlje od PREMOR_PESMI_S -> premor (uporabnik s
            # sistemskimi tipkami ali konec seznama). Kratek postanek med pesmijo in oglasom (konec pesmi, oglas se
            # nalaga) ni premor. Med oglasom ne sklepamo nic: oglas sam ni uporabnikova odlocitev.
            if stanje["igra"]:
                self._uporabnik_igra = True
            elif not self._pesem_stoji_od:
                self._pesem_stoji_od = self._ura()
            elif self._ura() - self._pesem_stoji_od >= self.PREMOR_PESMI_S and not self._po_oglasu():
                # Takoj po oglasu pesem, ki stoji, ni uporabnikov premor, temvec zastoj Spotifyja (ga popravi strazar);
                # premor iz Safeerja (upravljaj) uporabnikovo zeljo nastavi sam.
                if self._uporabnik_igra:
                    _sled("pesem stoji %.0f s brez oglasa: premor" % (self._ura() - self._pesem_stoji_od))
                self._uporabnik_igra = False
        if self.scit() and stanje["oglas"]:
            # Samo utisamo (lastnik 18. 10. 2026): brez preskoka, pospesevanja ali »Naslednje« med oglasom.
            if not self._utisal:
                self._utisaj(True)
        elif self._utisal and not stanje["oglas"]:
            self._utisaj(False)
        self._popravi_zastoj(stanje)
        self._nastavi_predvajanje(stanje)
        return stanje

    #: Po utisanem oglasu Spotify predvajalnik vcasih obstoji (oglas, premor, naslednje pesmi ni; preizkus 18. 10. 2026):
    #: poslusalec bi moral sam pritisniti Predvajaj. Strazar pritisne SAMO Predvajaj (nikoli Naslednja) in samo, ce je
    #: uporabnik pred tem poslusal - njegovega premora ali ustavitve ne razveljavi. Sekunde od zacetka zastoja.
    ZASTOJ_KORAKI = (2.0, 12.0, 30.0, 60.0)
    #: Pesem, ki toliko sekund stoji brez oglasa, je v premoru (ne prehod v oglas).
    PREMOR_PESMI_S = 3.0
    #: Okno po koncu oglasa, v katerem pesem, ki stoji, velja za zastoj (Spotify po utisanem oglasu pesmi ne zacne).
    PO_OGLASU_S = 90.0

    def _po_oglasu(self) -> bool:
        return bool(self._oglas_konec_od) and self._ura() - self._oglas_konec_od < self.PO_OGLASU_S

    def _popravi_zastoj(self, stanje: dict) -> None:
        stoji = not stanje.get("igra") and (stanje.get("oglas") or (self._po_oglasu() and stanje.get("naslov")))
        if not (self.scit() and stoji and self._uporabnik_igra):
            self._zastoj_od, self._zastoj_korak = 0.0, 0
            return
        zdaj = self._ura()
        if not self._zastoj_od:
            self._zastoj_od = zdaj
            return
        if self._zastoj_korak >= len(self.ZASTOJ_KORAKI):
            return
        if zdaj - self._zastoj_od >= self.ZASTOJ_KORAKI[self._zastoj_korak]:
            self._zastoj_korak += 1
            st = self._ukaz_st
            try:
                # preverba (ne igra) in klik v istem izrazu: ce je medtem zaigral, klik ne bi ga ustavil
                if st == self._ukaz_st and self._uporabnik_igra:
                    _sled("zastoj %s: Predvajaj (korak %d)" % ("v oglasu" if stanje.get("oglas") else "po oglasu",
                                                               self._zastoj_korak))
                    self.kanal.izvedi(PREKLOP_JS % _js("igraj"), 3)
            except (NiOdziva, SpremenjenaStran):
                pass

    def _utisaj(self, da: bool) -> None:
        try:
            self.kanal.izvedi("window.__safeerSpotify && window.__safeerSpotify.utisaj(%s)" % ("true" if da else "false"), 3)
            self._utisal = da
        except (NiOdziva, SpremenjenaStran):
            pass

    # -- za Medijski center
    def stanje(self) -> dict:
        """Brez zagona Safeer DRM: kar vemo (zagon sprozi sele seznami() ali prijava())."""
        nast = self._nastavitve()
        bil = bool(nast.get("prijavljen"))
        tece = self.kanal.tece()
        znano = tece and self._preverjeno
        prijavljen = self._prijavljen if znano else bil
        obvestilo = bool(prijavljen and tece and not nast.get("obvestilo_scit"))
        if obvestilo:
            self._shrani(obvestilo_scit=True)
        return {"drm": self._na_voljo(), "tece": tece, "okno": tece and self.kanal.vidno,
                "prijavljen": prijavljen, "potekla": bool(bil and znano and not self._prijavljen and not self.kanal.vidno),
                "ime": self._ime if prijavljen else "", "scit": self.scit(), "obvestilo_scit": obvestilo and self.scit(),
                "predvajanje": self._predvajanje if tece else {}}

    def prijava(self) -> dict:
        """Prijavo opravi uporabnik v Spletu (stran Spotifyja); Medijski center nato klice prijava_iz_spleta()."""
        if not self._na_voljo():
            return {"napaka": "ni_drm"}
        return {"ok": True, "splet": PRIJAVA_SPLET}

    def prijava_iz_spleta(self) -> dict:
        """Ce je uporabnik v Spletu prijavljen v Spotify: piskotke prenesemo v profil skritega Safeer DRM."""
        piskotki = piskotki_spleta()
        if not prijavljen_v_spletu(piskotki):
            return {"prijavljen": False}
        self.kanal.ustavi()
        self._preverjeno = False
        izid = self.kanal.zacni(False, self.scit(), piskotki)
        if izid != "ok":
            return {"napaka": izid}
        self._dotakni()
        self._zazeni_strazo()
        self._shrani(prijavljen=True)
        self._prijavljen = True
        return {"prijavljen": True}

    def _odpri_prijavo(self) -> None:
        konec = self._ura() + 30
        while self._ura() < konec and self.kanal.tece() and not self.kanal.nalozeno:
            time.sleep(0.3)
        try:
            time.sleep(1.5)
            self.kanal.izvedi(GUMB_JS % _js("login-button"), 5)
        except (NiOdziva, SpremenjenaStran):
            pass

    def odjava(self) -> dict:
        """Odjava na tej napravi: Safeer DRM se ustavi, profil Spotifyja (piskotki prijave) se izbrise. Na drugih
        napravah uporabnik ostane prijavljen."""
        self.kanal.ustavi()
        shutil.rmtree(self.kanal.profil(), ignore_errors=True)
        self._prijavljen, self._ime = False, ""
        self._nastavi_predvajanje({})
        self._shrani(prijavljen=False)
        return {"ok": True}

    def ustavi(self) -> None:
        self.kanal.ustavi()
        self._ob_koncu()

    def _klic_strani(self, izraz: str, cas: float = 20.0) -> dict:
        o = self.kanal.izvedi(izraz, cas)
        if not isinstance(o, dict):
            raise SpremenjenaStran()
        if o.get("napaka") == "ni_skripte":
            raise SpremenjenaStran()
        if o.get("status") == 401:
            self._prijavljen = False
            raise PoteklaPrijava()
        return o

    def _pf(self, ime: str, zamenjave: dict) -> Optional[dict]:
        """Klic GraphQL kot spletna aplikacija ali None (vzorca ni ali ga Spotify ne sprejme)."""
        o = self._klic_strani("(async () => { const S = window.__safeerSpotify; if (!S) return { napaka: 'ni_skripte' };"
                              " return await S.pf(%s, %s); })()" % (_js(ime), _js(zamenjave)))
        return o.get("podatki") if o.get("status") == 200 and isinstance(o.get("podatki"), dict) \
            and not o["podatki"].get("errors") else None

    def _api(self, pot: str) -> Optional[dict]:
        o = self._klic_strani("(async () => { const S = window.__safeerSpotify; if (!S) return { napaka: 'ni_skripte' };"
                              " return await S.klic(%s); })()" % _js(pot))
        return o.get("podatki") if o.get("status") == 200 and isinstance(o.get("podatki"), dict) else None

    def _pojdi(self, pot: str, vzorec: str = "") -> bool:
        try:
            return self.kanal.izvedi(POJDI_JS % (_js(pot), _js(vzorec)), 15) == "ok"
        except SpremenjenaStran:
            return False

    def _strani(self, ime: str, zamenjave: dict, api: str, razcleni: Callable[[Any], list],
                pot_strani: str = "", kljuc: str = "uri") -> list:
        """Vsi vnosi (do NAJVEC): GraphQL z zamiki, sicer spletni API (next), sicer stran odpremo, da vzorec poslje
        sama, in poskusimo znova. Nic od tega: SpremenjenaStran."""
        for poskus in range(2):
            izid: list = []
            videni: set = set()
            prva = self._pf(ime, dict(zamenjave, offset=0, limit=_STRAN))
            if prva is not None:
                stran, zamik = prva, 0
                for _ in range(_KROGOV):
                    vsi = razcleni(stran)
                    novi = self._novi(vsi, videni, kljuc)
                    if not novi:
                        break
                    izid.extend(novi)
                    zamik += len(vsi)        # streznik lahko vrne manj, kot smo prosili: naprej od tega, kar je dal
                    if len(izid) >= NAJVEC:
                        break
                    stran = self._pf(ime, dict(zamenjave, offset=zamik, limit=_STRAN)) or {}
                return izid[:NAJVEC]
            if api:
                pot = api
                for _ in range(_KROGOV):
                    o = self._api(pot)
                    if o is None:
                        break
                    izid.extend(self._novi(razcleni(o), videni, kljuc))
                    naslednja = _niz(o.get("next"))
                    if len(izid) >= NAJVEC or not naslednja.startswith("https://api.spotify.com/v1/"):
                        break
                    pot = naslednja[len("https://api.spotify.com/v1/"):]
                if izid:
                    return izid[:NAJVEC]
            if poskus or not pot_strani:
                break
            self._pojdi(pot_strani, ime)
            time.sleep(1.0)
        raise SpremenjenaStran()

    @staticmethod
    def _novi(vnosi: list, videni: set, kljuc: str) -> list:
        izid = []
        for x in vnosi:
            if x.get(kljuc) not in videni:
                videni.add(x.get(kljuc))
                izid.append(x)
        return izid

    def seznami(self) -> dict:
        """{"prijavljen", "ime", "seznami": [...], "oddaje": [...]} ali {"napaka": ni_drm|potekla|ni_prijave|stran|ni_odziva}."""
        try:
            self._zagotovi()
            if not self._prijavljen:
                return {"napaka": "potekla" if self._nastavitve().get("prijavljen") else "ni_prijave"}
            knjiznica = self._pf("libraryV3", {"offset": 0, "limit": 50})
            if knjiznica is None:
                self._pojdi("/collection/playlists", "libraryV3")
                knjiznica = self._pf("libraryV3", {"offset": 0, "limit": 50})
            seznami = seznami_iz(knjiznica) if knjiznica else []
            oddaje = oddaje_iz(knjiznica) if knjiznica else []
            if not seznami:
                seznami = seznami_iz(self._api("me/playlists?limit=50") or {})
            if not oddaje:
                oddaje = oddaje_iz(self._api("me/shows?limit=50") or {})
            return {"prijavljen": True, "ime": self._ime, "seznami": seznami, "oddaje": oddaje}
        except NiDrm:
            return {"napaka": "ni_drm"}
        except PoteklaPrijava:
            return {"napaka": "potekla"}
        except SpremenjenaStran:
            return {"napaka": "stran"}
        except NiOdziva:
            return {"napaka": "ni_odziva"}

    def seznam(self, ident: str) -> dict:
        """{"ime", "vir": "Spotify", "skladbe", "kontekst"} - Vseckane pesmi (VSECKANE), seznam ali oddaja (show:<id>)."""
        ident = str(ident or "")
        oddaja = ident.startswith("show:")
        cisti = ident[5:] if oddaja else ident
        if ident != VSECKANE and not ID.match(cisti):
            return {"napaka": "neveljavno"}
        try:
            self._zagotovi()
            if not self._prijavljen:
                return {"napaka": "potekla"}
            if ident == VSECKANE:
                skladbe = self._strani("fetchLibraryTracks", {}, "me/tracks?limit=50", skladbe_iz,
                                       pot_strani="/collection/tracks", kljuc="spotify")
                return {"ime": "", "vseckane": True, "vir": "Spotify", "skladbe": skladbe, "kontekst": "collection"}
            if oddaja:
                skladbe = self._strani("queryPodcastEpisodes", {"uri": "spotify:show:" + cisti},
                                       "shows/%s/episodes?limit=50" % cisti, skladbe_iz, pot_strani="/show/" + cisti,
                                       kljuc="spotify")
                return {"ime": "", "vir": "Spotify", "skladbe": skladbe, "kontekst": "spotify:show:" + cisti}
            skladbe = self._strani("fetchPlaylist", {"uri": "spotify:playlist:" + cisti},
                                   "playlists/%s/tracks?limit=100" % cisti, skladbe_iz,
                                   pot_strani="/playlist/" + cisti, kljuc="spotify")
            return {"ime": "", "vir": "Spotify", "skladbe": skladbe, "kontekst": "spotify:playlist:" + cisti}
        except NiDrm:
            return {"napaka": "ni_drm"}
        except PoteklaPrijava:
            return {"napaka": "potekla"}
        except SpremenjenaStran:
            return {"napaka": "stran"}
        except NiOdziva:
            return {"napaka": "ni_odziva"}

    @staticmethod
    def pot_strani(uri: str) -> str:
        """spotify:playlist:ID -> /playlist/ID; "collection" -> /collection/tracks."""
        if uri == "collection":
            return "/collection/tracks"
        d = uri.split(":")
        if len(d) == 3 and d[0] == "spotify" and d[1] in ("track", "episode", "playlist", "show", "album") and ID.match(d[2]):
            return "/%s/%s" % (d[1], d[2])
        return ""

    def predvajaj(self, uri: str, kontekst: str = "") -> dict:
        """Skladba (v kontekstu seznama, Vseckanih ali oddaje, da Spotify igra naprej) ali cel kontekst."""
        cilj_pot = self.pot_strani(uri) if uri else ""
        pot = self.pot_strani(kontekst) if kontekst else cilj_pot
        if kontekst.startswith("spotify:show:") and cilj_pot.startswith("/episode/"):
            pot = cilj_pot          # epizoda: njena stran ima svoj gumb Predvajaj
        if not pot or (uri and not cilj_pot):
            return {"napaka": "neveljavno"}
        try:
            self._zagotovi()
            if not self._prijavljen:
                return {"napaka": "potekla"}
            if not self._pojdi(pot):
                return {"napaka": "stran"}
            cilj = cilj_pot if uri and pot != cilj_pot else ""
            self._uporabnik(True)
            izid = self.kanal.izvedi(PREDVAJAJ_JS % _js(cilj), 10)
            if izid == "ni":
                return {"napaka": "stran"}
            return {"ok": True, "delno": izid == "zacetek"}
        except NiDrm:
            return {"napaka": "ni_drm"}
        except PoteklaPrijava:
            return {"napaka": "potekla"}
        except SpremenjenaStran:
            return {"napaka": "stran"}
        except NiOdziva:
            return {"napaka": "ni_odziva"}

    UKAZI = {"premor": "control-button-playpause", "naprej": "control-button-skip-forward",
             "nazaj": "control-button-skip-back"}

    def upravljaj(self, ukaz: str, vrednost: Any = None) -> dict:
        """premor | naprej | nazaj | cas (delez 0..1) | glasnost (0..1) | ustavi."""
        if not self.kanal.tece():
            return {"napaka": "ne_tece"}
        self._dotakni()
        try:
            if ukaz == "premor":
                # preklop: preverba in klik v istem izrazu, uporabnikova zelja je stanje PO kliku
                izid = self.kanal.izvedi(PREKLOP_JS % _js("preklopi"), 5)
                if izid in ("igra", "premor"):
                    self._uporabnik(izid == "igra")
                ok = bool(izid)
            elif ukaz in self.UKAZI:
                if ukaz in ("naprej", "nazaj"):
                    self._uporabnik(True)     # izbral je drugo pesem: zeli poslusati
                ok = self.kanal.izvedi(GUMB_JS % _js(self.UKAZI[ukaz]), 5)
            elif ukaz in ("cas", "glasnost"):
                try:
                    delez = max(0.0, min(1.0, float(vrednost)))
                except (TypeError, ValueError):
                    return {"napaka": "neveljavno"}
                ok = self.kanal.izvedi(DRSNIK_JS % (_js("playback-progressbar" if ukaz == "cas" else "volume-bar"),
                                                    _js(round(delez, 4))), 5)
            elif ukaz == "ustavi":
                # Gumb je preklopni: preverba (igra?) in klik sta v ISTEM izrazu strani (brez tekme), klici pa zvrsceni,
                # sicer bi dva hkratna »ustavi« (Medijski center in druga vsebina) Spotify spet zagnala. Uporabnikova
                # ustavitev velja tudi za strazarja zastoja po oglasu (ne pritisne vec Predvajaj).
                with self._ustavljam:
                    self._uporabnik(False)
                    self.kanal.izvedi(PREKLOP_JS % _js("ustavi"), 5)
                    self._nastavi_predvajanje(dict(self._predvajanje, igra=False))
                return {"ok": True}
            else:
                return {"napaka": "neveljavno"}
        except SpremenjenaStran:
            return {"napaka": "stran"}
        except NiOdziva:
            return {"napaka": "ni_odziva"}
        return {"ok": True} if ok else {"napaka": "stran"}

    def predvajanje(self) -> dict:
        return dict(self._predvajanje) if self.kanal.tece() else {}
