"""Seznami predvajanja uporabnikovega racuna YouTube (prijava v Spletu Safeer OS) za Medijski center.

Lastnik 17. 10. 2026: »Dodajmo moznost, da se uporabnik, ce zeli, prijavi v YouTube in predvaja VSE svoje sezname.«
Prijava je samo v Spletu (WebKit, Google sam vodi prijavo); tu nicesar ne vpisujemo in nic ne shranjujemo.
Ko so v shrambi piskotkov Spleta (cookies.sqlite) piskotki YouTube, jih preberemo SAMO ZA BRANJE in z njimi
vprasamo InnerTube (youtubei/v1) z glavo SAPISIDHASH - tako, kot to naredi stran youtube.com v brskalniku.

Varnost: zahteve samo na https://www.youtube.com (brez preusmeritev - piskotki ne smejo oditi drugam), piskotki
in glava Authorization nikoli v dnevnik, seznami ostanejo na napravi (Medijski center jih ne deli prek Linka).
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

from . import uvoz_seznama

IZVOR = "https://www.youtube.com"
PRIJAVA = "https://accounts.google.com/ServiceLogin?service=youtube&continue=https://www.youtube.com/"
ODJAVA = "https://www.youtube.com/logout"
#: Posebni seznami racuna (Medijski center jim da prevedeno ime): Vseckani, Oglej si pozneje, YouTube Music vseckane.
POSEBNI = ("LL", "WL", "LM")
_DOVOLJENI = ("www.youtube.com", "music.youtube.com")
_KROGOV = 12          # strani nadaljevanja (~100 posnetkov na stran) - dovolj za NAJVEC


class PoteklaPrijava(Exception):
    """Piskotki so, YouTube pa jih ne sprejme vec (odjava drugje, potekla seja) ali je InnerTube spremenil odgovor."""


def pot_piskotkov() -> str:
    """Shramba piskotkov Spleta (core/os_splet._ustvari_kontekst): <CONFIG_DIR>/cookies.sqlite. CONFIG_DIR je
    ~/.config/safeer-mint (.deb) oziroma ~/.var/app/io.github.memelandfaner.SafeerOS/config/safeer-mint (Flatpak:
    XDG_CONFIG_HOME peskovnika) - Medijski center tece v istem procesu kot Splet, zato je pot vedno prava."""
    from .config import CONFIG_DIR
    return os.path.join(CONFIG_DIR, "cookies.sqlite")


def _ujema(gostitelj: str, domena: str) -> bool:
    domena = str(domena or "").lower()
    if domena.startswith("."):
        return gostitelj == domena[1:] or gostitelj.endswith(domena)
    return gostitelj == domena


def beri_piskotke(pot: str, gostitelj: str = "www.youtube.com", zdaj: Optional[float] = None,
                  domena: str = "youtube.com") -> dict:
    """Veljavni piskotki za [gostitelj] iz shrambe WebKita (libsoup, tabela moz_cookies). Samo branje: Splet je
    lahko odprt in ima bazo v uporabi; zaklenjena ali manjkajoca baza pomeni »ni prijave«. [domena] omeji branje
    (core/twitch.py bere twitch.tv)."""
    if not os.path.isfile(pot):
        return {}
    zdaj = time.time() if zdaj is None else zdaj
    try:
        povezava = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(os.path.abspath(pot)), uri=True, timeout=2)
        try:
            vrstice = povezava.execute("SELECT name, value, host, expiry FROM moz_cookies WHERE host LIKE ?",
                                       ("%" + domena,)).fetchall()
        finally:
            povezava.close()
    except sqlite3.Error as e:
        print("[Piskotki Spleta] %s: %s" % (domena, type(e).__name__), flush=True)
        return {}
    izid: dict = {}
    for ime, vrednost, domena, potek in vrstice:
        if not ime or vrednost is None or not _ujema(gostitelj, domena):
            continue
        if potek and int(potek) < zdaj:
            continue
        # Natancnejsa domena (www.youtube.com) ima prednost pred splosno (.youtube.com), kot v brskalniku.
        if ime in izid and not str(domena).startswith("."):
            izid[ime] = str(vrednost)
        else:
            izid.setdefault(ime, str(vrednost))
    return izid


def prijavljen(piskotki: dict) -> bool:
    return bool(piskotki.get("SAPISID") or piskotki.get("__Secure-3PAPISID"))


def _zgosti(cas: int, kljuc: str, izvor: str) -> str:
    return "%d_%s" % (cas, hashlib.sha1(("%d %s %s" % (cas, kljuc, izvor)).encode("utf-8"),
                                        usedforsecurity=False).hexdigest())


def sapisidhash(piskotki: dict, cas: Optional[int] = None, izvor: str = IZVOR) -> str:
    """Glava Authorization, ki jo poslje youtube.com: SAPISIDHASH <cas>_<sha1(cas + ' ' + SAPISID + ' ' + izvor)>
    (in enaka z __Secure-1PAPISID / __Secure-3PAPISID, ce sta). Prazno, ce prijave ni."""
    cas = int(time.time()) if cas is None else int(cas)
    glavni = piskotki.get("SAPISID") or piskotki.get("__Secure-3PAPISID")
    if not glavni:
        return ""
    deli = ["SAPISIDHASH " + _zgosti(cas, glavni, izvor)]
    if piskotki.get("__Secure-1PAPISID"):
        deli.append("SAPISID1PHASH " + _zgosti(cas, piskotki["__Secure-1PAPISID"], izvor))
    if piskotki.get("__Secure-3PAPISID"):
        deli.append("SAPISID3PHASH " + _zgosti(cas, piskotki["__Secure-3PAPISID"], izvor))
    return " ".join(deli)


class _BrezPreusmeritev(urllib.request.HTTPRedirectHandler):
    """urllib bi glavi Cookie in Authorization ob preusmeritvi poslal naprej (tudi na drug streznik)."""

    def redirect_request(self, *_a, **_k):
        return None


def _poslji(naslov: str, glave: dict, telo: bytes, cas: float) -> tuple[int, str]:
    odpiralnik = urllib.request.build_opener(_BrezPreusmeritev)
    try:
        with odpiralnik.open(urllib.request.Request(naslov, data=telo, headers=glave), timeout=cas) as odgovor:
            return odgovor.status, odgovor.read(8_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


def _odjavljen(o: Any) -> bool:
    try:
        return bool(o["responseContext"]["mainAppWebResponseContext"]["loggedOut"])
    except (KeyError, TypeError):
        return False


def _besedilo(o: Any) -> str:
    return uvoz_seznama._besedilo(o) if isinstance(o, dict) else str(o or "")


def seznami_iz(d: Any) -> list[dict]:
    """Seznami iz strani knjiznice (FEplaylist_aggregation / FElibrary): stara oblika (gridPlaylistRenderer,
    playlistRenderer) in nova (lockupViewModel z vrsto PLAYLIST)."""
    najdeni: dict[str, dict] = {}

    def dodaj(ident: str, ime: str) -> None:
        ident = str(ident or "")
        if ident.startswith("VL"):
            ident = ident[2:]
        if ident and ime and ident not in najdeni and not ident.startswith("RD"):
            najdeni[ident] = {"id": ident, "ime": ime}

    def hodi(x: Any, globina: int) -> None:
        if globina > 60:
            return
        if isinstance(x, list):
            for v in x:
                hodi(v, globina + 1)
            return
        if not isinstance(x, dict):
            return
        for kljuc in ("gridPlaylistRenderer", "playlistRenderer"):
            r = x.get(kljuc)
            if isinstance(r, dict) and r.get("playlistId"):
                dodaj(r["playlistId"], _besedilo(r.get("title")))
                return
        r = x.get("lockupViewModel")
        if isinstance(r, dict) and r.get("contentId") and "PLAYLIST" in str(r.get("contentType") or ""):
            m = ((r.get("metadata") or {}).get("lockupMetadataViewModel") or {})
            dodaj(r["contentId"], _besedilo(m.get("title")))
            return
        for v in x.values():
            hodi(v, globina + 1)

    hodi(d, 0)
    return list(najdeni.values())


def ime_iz(d: Any) -> str:
    """Ime racuna iz account/account_menu (activeAccountHeaderRenderer)."""
    def hodi(x: Any, globina: int) -> str:
        if globina > 40:
            return ""
        if isinstance(x, list):
            for v in x:
                r = hodi(v, globina + 1)
                if r:
                    return r
            return ""
        if not isinstance(x, dict):
            return ""
        glava = x.get("activeAccountHeaderRenderer")
        if isinstance(glava, dict):
            return _besedilo(glava.get("accountName")) or _besedilo(glava.get("channelHandle"))
        for v in x.values():
            r = hodi(v, globina + 1)
            if r:
                return r
        return ""
    return hodi(d, 0)


class Racun:
    """Branje racuna YouTube s piskotki Spleta. [poslji] in [pot] zamenjajo preizkusi (mock InnerTube)."""

    def __init__(self, pot: Optional[str] = None, poslji: Optional[Callable[[str, dict, bytes, float], tuple]] = None):
        self._pot = pot
        self._poslji = poslji or _poslji

    @property
    def pot(self) -> str:
        return self._pot or pot_piskotkov()

    def piskotki(self) -> dict:
        return beri_piskotke(self.pot)

    def prijavljen(self) -> bool:
        return prijavljen(self.piskotki())

    def _vprasaj(self, pot: str, telo: dict, piskotki: dict, cas: float = 15.0, racun: int = 0) -> dict:
        naslov = IZVOR + "/youtubei/v1/" + pot + "?prettyPrint=false"
        razclenjen = urllib.parse.urlsplit(naslov)
        if razclenjen.scheme != "https" or razclenjen.hostname not in _DOVOLJENI:
            raise ValueError("nedovoljen naslov")
        avtorizacija = sapisidhash(piskotki)
        if not avtorizacija:
            raise PoteklaPrijava()
        glave = {
            "User-Agent": uvoz_seznama._UA, "Accept-Language": "en", "Content-Type": "application/json",
            "Origin": IZVOR, "X-Origin": IZVOR, "Referer": IZVOR + "/", "X-Goog-AuthUser": str(int(racun)),
            "X-Youtube-Client-Name": "1", "X-Youtube-Client-Version": uvoz_seznama._RAZLICICA,
            "Authorization": avtorizacija,
            "Cookie": "; ".join("%s=%s" % (k, v) for k, v in piskotki.items()),
        }
        osnova = {"context": {"client": {"clientName": "WEB", "clientVersion": uvoz_seznama._RAZLICICA, "hl": "en"}}}
        status, besedilo = self._poslji(naslov, glave, json.dumps(dict(osnova, **telo)).encode("utf-8"), cas)
        if status in (401, 403):
            raise PoteklaPrijava()
        if status != 200:
            raise OSError("InnerTube %s" % status)
        try:
            o = json.loads(besedilo)
        except ValueError:
            raise PoteklaPrijava() from None      # InnerTube je spremenil odgovor: pove enako kot potekla prijava
        if not isinstance(o, dict) or _odjavljen(o):
            raise PoteklaPrijava()
        return o

    #: Najvec racunov Google v isti prijavi (Google dovoli vec racunov hkrati; X-Goog-AuthUser 0, 1, 2 ...).
    NAJVEC_RACUNOV = 5

    def _racun(self, piskotki: dict, racun: int) -> tuple:
        ime = ime_iz(self._vprasaj("account/account_menu", {}, piskotki, racun=racun))
        seznami = seznami_iz(self._vprasaj("browse", {"browseId": "FEplaylist_aggregation"}, piskotki, racun=racun))
        if not seznami:
            seznami = seznami_iz(self._vprasaj("browse", {"browseId": "FElibrary"}, piskotki, racun=racun))
        return ime, seznami

    def stanje(self) -> dict:
        """{"prijavljen", "ime", "seznami", "racuni": [{racun, ime, seznami}], "potekla"} - brez izjem.
        Lastnik 17. 10. 2026: uporabnik je lahko prijavljen v vec racunov YouTube; vsi njihovi seznami so na voljo."""
        piskotki = self.piskotki()
        if not prijavljen(piskotki):
            return {"prijavljen": False, "ime": "", "seznami": [], "racuni": [], "potekla": False}

        def posebni(n):
            return [{"id": p, "posebni": p, "racun": n} for p in POSEBNI]
        racuni, videna = [], set()
        for n in range(self.NAJVEC_RACUNOV):
            try:
                ime, seznami = self._racun(piskotki, n)
            except PoteklaPrijava:
                if n == 0:
                    return {"prijavljen": False, "ime": "", "seznami": [], "racuni": [], "potekla": True}
                break
            except Exception as e:  # noqa: BLE001 - omrezje: Medijski center pokaze, da ni uspelo, nic se ne sesuje
                print("[YouTube racun] stanje:", type(e).__name__, flush=True)
                if n == 0:
                    return {"prijavljen": True, "ime": "", "seznami": posebni(0), "racuni": [], "potekla": False,
                            "napaka": True}
                break
            # Neobstojec indeks Google preusmeri na privzeti racun: isto ime pomeni, da racunov ni vec.
            if n > 0 and (not ime or ime in videna):
                break
            videna.add(ime)
            racuni.append({"racun": n, "ime": ime,
                           "seznami": posebni(n) + [dict(x, racun=n) for x in seznami if x["id"] not in POSEBNI]})
        prvi = racuni[0] if racuni else {"ime": "", "seznami": posebni(0)}
        return {"prijavljen": True, "ime": prvi["ime"], "potekla": False, "seznami": prvi["seznami"], "racuni": racuni}

    def seznam(self, ident: str, racun: int = 0) -> Optional[dict]:
        """{"ime", "vir": "YouTube", "skladbe"} vseh posnetkov seznama (z nadaljevanjem, do NAJVEC) ali None.
        Potekla prijava: izjema PoteklaPrijava."""
        ident = str(ident or "")
        if not ident or not all(c.isalnum() or c in "-_" for c in ident):
            return None
        piskotki = self.piskotki()
        if not prijavljen(piskotki):
            raise PoteklaPrijava()
        prva = uvoz_seznama.iz_youtube(self._vprasaj("browse", {"browseId": "VL" + ident}, piskotki, racun=racun))
        skladbe: dict[str, dict] = {}
        for v in prva["vnosi"]:
            skladbe.setdefault(v["id"], v)
        zeton, krogov = prva["nadaljevanje"], 0
        while zeton and len(skladbe) < uvoz_seznama.NAJVEC and krogov < _KROGOV:
            krogov += 1
            try:
                stran = uvoz_seznama.iz_youtube(self._vprasaj("browse", {"continuation": zeton}, piskotki, racun=racun))
            except PoteklaPrijava:
                raise
            except Exception as e:  # noqa: BLE001 - prve strani ne zavrzemo zaradi ene neuspele naslednje
                print("[YouTube racun] nadaljevanje:", type(e).__name__, flush=True)
                break
            prej = len(skladbe)
            for v in stran["vnosi"]:
                skladbe.setdefault(v["id"], v)
            if len(skladbe) == prej:
                break
            zeton = stran["nadaljevanje"]
        if not skladbe:
            return None
        vnosi = list(skladbe.values())[:uvoz_seznama.NAJVEC]
        return {"ime": prva["ime"] or ident, "vir": "YouTube", "skladbe": [uvoz_seznama._youtube_skladba(v) for v in vnosi]}
