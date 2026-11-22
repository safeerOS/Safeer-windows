"""Twitch v Medijskem centru: prenosi v zivo, kategorije, iskanje kanalov, posnetki in (neobvezno) kanali, ki jim slediš.

Lastnik 17. 10. 2026: »Twitch gledamo ZNOTRAJ nasega predvajalnika v Medijskem centru, enako udobno kot YouTube; Safeer
Scit varuje pred vsiljivimi oglasi.« Brez prijave: javni GQL Twitcha (gql.twitch.tv, isti Client-Id kot spletna stran),
predvajanje prek zetona PlaybackAccessToken in seznama usher (HLS) v domacem predvajalniku - oglase izloci
core/twitch_hls.py.

Prijava je neobvezna in samo v Spletu (twitch.tv/login, Twitch sam vodi prijavo); tu nicesar ne vpisujemo. Ko je v
shrambi piskotkov Spleta (cookies.sqlite) piskotek auth-token, ga preberemo SAMO ZA BRANJE (kot core/youtube_racun.py)
in z njim vprasamo GQL za kanale, ki jim uporabnik sledi. Zeton gre samo na https://gql.twitch.tv (brez preusmeritev),
nikoli na usher ali CDN, nikoli v dnevnik in nikoli prek Safeer Linka. Seznam kanalov se ne shranjuje (je »zaseben«).
"""
from __future__ import annotations

import json
import os
import random
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

from . import twitch_hls, youtube_racun

GQL = "https://gql.twitch.tv/gql"
#: Javni Client-Id spletne strani twitch.tv (ga uporabljajo tudi streamlink, yt-dlp ...); ni skrivnost.
CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
PRIJAVA = "https://www.twitch.tv/login"
ODJAVA = "https://www.twitch.tv/logout"
USHER = "https://usher.ttvnw.net"
#: GQL brez prijave da najvec 30 najbolj gledanih prenosov (vec zavrne: »between 1 and 30«), v kategoriji vec.
NA_STRAN = 30
NA_KATEGORIJO = 60
NAJVEC_KATEGORIJ = 24
#: Glavni tok (igralec »site«, kot na twitch.tv) in rezerve za cas oglasa - po meritvi 17. 10. 2026 so »embed«,
#: »site« na platformi android in »popout« brez oglasa dali polno kakovost, »autoplay« najvec 360p (zadnja rezerva).
GLAVNI = ("site", "web")
REZERVE = (("embed", "web"), ("site", "android"), ("popout", "web"), ("autoplay", "web"))
KAKOVOSTI = ("auto", "1080", "720", "480", "360", "160", "audio_only")
_LOGIN = re.compile(r"^[A-Za-z0-9_]{1,25}$")
_ID = re.compile(r"^\d{1,20}$")
_NADZOR = re.compile(r"[\x00-\x1f\x7f]")


class PoteklaPrijava(Exception):
    """Piskotek auth-token je, Twitch ga ne sprejme vec (odjava drugje, potekla seja)."""


class _BrezPreusmeritev(urllib.request.HTTPRedirectHandler):
    """urllib bi glavo Authorization ob preusmeritvi poslal naprej (tudi na drug streznik)."""

    def redirect_request(self, *_a, **_k):
        return None


def _poslji(naslov: str, glave: dict, telo: bytes, cas: float) -> tuple[int, str]:
    odpiralnik = urllib.request.build_opener(_BrezPreusmeritev)
    try:
        with odpiralnik.open(urllib.request.Request(naslov, data=telo, headers=glave), timeout=cas) as odgovor:
            return odgovor.status, odgovor.read(4_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


def _niz(x: Any, meja: int = 300) -> str:
    return _NADZOR.sub("", str(x or "")).strip()[:meja]


def _https(x: Any) -> str:
    s = str(x or "")
    return s[:2048] if s.startswith("https://") else ""


def zeton_iz(piskotki: dict) -> str:
    """auth-token iz piskotkov twitch.tv (samo crke in stevke - drugace ga ne posljemo nikamor)."""
    z = str(piskotki.get("auth-token") or "")
    return z if re.fullmatch(r"[A-Za-z0-9]{20,64}", z) else ""


# ---------------------------------------------------------------------------------------------- GQL -> vnosi

_PRENOS = ("id title viewersCount previewImageURL(width: 440, height: 248) "
           "broadcaster { id login displayName profileImageURL(width: 150) } game { name displayName }")


def vnos_prenosa(p: Any, kanal: Optional[dict] = None) -> Optional[dict]:
    """Prenos (GQL Stream) -> vnos kataloga Medijskega centra (vrsta "twitch", v zivo)."""
    if not isinstance(p, dict):
        return None
    kanal = kanal or p.get("broadcaster") or {}
    login = str(kanal.get("login") or "")
    if not _LOGIN.match(login):
        return None
    ime = _niz(kanal.get("displayName") or login, 80)
    igra = _niz((p.get("game") or {}).get("displayName") or (p.get("game") or {}).get("name"), 80)
    try:
        gledalcev = max(0, int(p.get("viewersCount") or 0))
    except (TypeError, ValueError):
        gledalcev = 0
    return {"id": "twitch:" + login.lower(), "naslov": _niz(p.get("title"), 200) or ime, "vrsta": "twitch",
            "kanal": ime, "login": login.lower(), "igra": igra, "gledalcev": gledalcev, "v_zivo": True,
            "slika": _https(p.get("previewImageURL")), "ikona": _https(kanal.get("profileImageURL")),
            "vir": "Twitch", "vir_id": "twitch"}


def vnos_kanala(u: Any) -> Optional[dict]:
    """Kanal (GQL User): v zivo -> vnos prenosa; sicer kanal brez prenosa (klik odpre njegove posnetke)."""
    if not isinstance(u, dict):
        return None
    if isinstance(u.get("stream"), dict):
        return vnos_prenosa(u["stream"], u)
    login = str(u.get("login") or "")
    if not _LOGIN.match(login):
        return None
    ime = _niz(u.get("displayName") or login, 80)
    return {"id": "twitch-kanal:" + login.lower(), "naslov": ime, "vrsta": "twitch-kanal", "kanal": ime,
            "login": login.lower(), "v_zivo": False, "slika": _https(u.get("profileImageURL")),
            "vir": "Twitch", "vir_id": "twitch"}


def vnos_posnetka(v: Any, kanal: str = "") -> Optional[dict]:
    """Posnetek (GQL Video, VOD) -> vnos (vrsta "twitch-posnetek")."""
    if not isinstance(v, dict) or not _ID.match(str(v.get("id") or "")):
        return None
    slika = _https(v.get("previewThumbnailURL"))
    if "/_404/" in slika:
        slika = ""                         # posnetek se obdeluje: Twitch da sliko »404_processing«
    try:
        trajanje = max(0, int(v.get("lengthSeconds") or 0))
    except (TypeError, ValueError):
        trajanje = 0
    return {"id": "twitch-posnetek:" + str(v["id"]), "naslov": _niz(v.get("title"), 200) or kanal, "vrsta": "twitch-posnetek",
            "kanal": kanal, "trajanje": trajanje, "objavljeno": _niz(v.get("publishedAt"), 30), "slika": slika,
            "vir": "Twitch", "vir_id": "twitch"}


def _robovi(o: Any) -> list:
    return [e.get("node") or e.get("item") for e in ((o or {}).get("edges") or []) if isinstance(e, dict)]


class Twitch:
    """Twitch za Medijski center. [poslji], [beri] in [pot] zamenjajo preizkusi (mock GQL in usher)."""

    def __init__(self, pot: Optional[str] = None, poslji: Optional[Callable[[str, dict, bytes, float], tuple]] = None,
                 beri: Optional[Callable[[str], tuple]] = None, nastavitve: Optional[str] = None):
        self._pot = pot
        self._poslji = poslji or _poslji
        self._beri = beri or twitch_hls._beri       # samo strezniki Twitcha (twitch_hls.dovoljen)
        self._nastavitve = nastavitve
        self._posrednik: Optional[twitch_hls.Posrednik] = None
        self.visina_zaslona = 1080
        #: Nastavitev Scita »Twitch brez oglasov« (core/os_scit.Scit.twitch_brez_oglasov); privzeto vklopljena.
        self.brez_oglasov: Callable[[], bool] = lambda: True
        #: Zadnja seja predvajanja (za preizkuse in statistiko izpuscenih oglasov).
        self.zadnja_seja: Optional[twitch_hls.Seja] = None

    # -- prijava (samo branje piskotkov Spleta)
    @property
    def pot(self) -> str:
        return self._pot or youtube_racun.pot_piskotkov()

    def piskotki(self) -> dict:
        return youtube_racun.beri_piskotke(self.pot, gostitelj="www.twitch.tv", domena="twitch.tv")

    def zeton(self) -> str:
        return zeton_iz(self.piskotki())

    def prijavljen(self) -> bool:
        return bool(self.zeton())

    # -- GQL
    def _gql(self, poizvedba: str, spremenljivke: Optional[dict] = None, zeton: str = "", cas: float = 12.0) -> dict:
        razclenjen = urllib.parse.urlsplit(GQL)
        if razclenjen.scheme != "https" or not (razclenjen.hostname or "").endswith(".twitch.tv"):
            raise ValueError("nedovoljen naslov")      # zeton prijave samo na *.twitch.tv
        glave = {"Client-Id": CLIENT_ID, "Content-Type": "application/json", "User-Agent": "Mozilla/5.0",
                 "Accept-Language": "en"}
        if zeton:
            glave["Authorization"] = "OAuth " + zeton
        telo = json.dumps({"query": poizvedba, "variables": spremenljivke or {}}).encode("utf-8")
        status, besedilo = self._poslji(GQL, glave, telo, cas)
        if status == 401 and zeton:
            raise PoteklaPrijava()
        if status != 200:
            raise OSError("GQL %s" % status)
        try:
            o = json.loads(besedilo)
        except ValueError:
            raise OSError("GQL odgovor") from None
        if not isinstance(o, dict) or not isinstance(o.get("data"), dict):
            if zeton and "unauthorized" in json.dumps(o.get("errors") if isinstance(o, dict) else "").lower():
                raise PoteklaPrijava()
            raise OSError("GQL brez podatkov")
        return o["data"]

    def priljubljeni(self, kategorija: str = "") -> dict:
        """Najbolj gledani prenosi v zivo (ali v izbrani kategoriji) -> {"vnosi", "skupaj_strani": 1}.

        Ena stran: listanje s kazalcem (after) Twitch brez preverjanja odjemalca (integrity) zavrne (17. 10. 2026)."""
        kategorija = _niz(kategorija, 120)
        if kategorija:
            d = self._gql("query($n: String!) { game(name: $n) { streams(first: %d) { edges { node { %s } } } } }"
                          % (NA_KATEGORIJO, _PRENOS), {"n": kategorija})
            tokovi = (d.get("game") or {}).get("streams") or {}
        else:
            d = self._gql("query { streams(first: %d) { edges { node { %s } } } }" % (NA_STRAN, _PRENOS))
            tokovi = d.get("streams") or {}
        return {"vnosi": [v for v in (vnos_prenosa(n) for n in _robovi(tokovi)) if v], "skupaj_strani": 1}

    def kategorije(self) -> list[dict]:
        """Najbolj gledane kategorije (igre) -> [{"id": ime, "ime": prikazno ime}] za gumbe zvrsti."""
        d = self._gql("query { games(first: %d) { edges { node { name displayName } } } }" % NAJVEC_KATEGORIJ)
        izid = []
        for n in _robovi(d.get("games")):
            ime = _niz((n or {}).get("name"), 120)
            if ime:
                izid.append({"id": ime, "ime": _niz(n.get("displayName"), 120) or ime})
        return izid

    def isci(self, niz: str) -> dict:
        """Iskanje kanalov: v zivo najprej (po gledalcih), nato kanali brez prenosa."""
        niz = _niz(niz, 100)
        if not niz:
            return {"vnosi": [], "skupaj_strani": 1}
        d = self._gql("query($q: String!) { searchUsers(userQuery: $q, first: %d) { edges { node { id login displayName "
                      "profileImageURL(width: 150) stream { %s } } } } }" % (NA_STRAN, _PRENOS.replace(
                          "broadcaster { id login displayName profileImageURL(width: 150) } ", "")), {"q": niz})
        vnosi = [v for v in (vnos_kanala(n) for n in _robovi(d.get("searchUsers"))) if v]
        vnosi.sort(key=lambda v: (not v["v_zivo"], -int(v.get("gledalcev") or 0)))
        return {"vnosi": vnosi, "skupaj_strani": 1}

    def posnetki(self, login: str) -> dict:
        """Zadnji posnetki (VOD) kanala -> {"ime", "vnosi"}; neznan kanal -> prazno."""
        login = str(login or "").lower()
        if not _LOGIN.match(login):
            return {"ime": "", "vnosi": []}
        d = self._gql("query($l: String!) { user(login: $l) { displayName videos(first: %d, type: ARCHIVE, sort: TIME) "
                      "{ edges { node { id title lengthSeconds previewThumbnailURL(width: 320, height: 180) publishedAt } } } } }"
                      % NA_STRAN, {"l": login})
        u = d.get("user") or {}
        ime = _niz(u.get("displayName") or login, 80)
        return {"ime": ime, "vnosi": [v for v in (vnos_posnetka(n, ime) for n in _robovi(u.get("videos"))) if v]}

    def stanje(self) -> dict:
        """{"prijavljen", "ime", "kanali", "potekla"} - kanali, ki jim uporabnik sledi (v zivo najprej). Brez izjem."""
        zeton = self.zeton()
        if not zeton:
            return {"prijavljen": False, "ime": "", "kanali": [], "potekla": False}
        try:
            d = self._gql("query { currentUser { login displayName follows(first: 100) { edges { node { id login "
                          "displayName profileImageURL(width: 150) stream { %s } } } } } }"
                          % _PRENOS.replace("broadcaster { id login displayName profileImageURL(width: 150) } ", ""),
                          zeton=zeton)
        except PoteklaPrijava:
            return {"prijavljen": False, "ime": "", "kanali": [], "potekla": True}
        except Exception as e:  # noqa: BLE001 - omrezje: Medijski center pove, da ni uspelo, nic se ne sesuje
            print("[Twitch] racun:", type(e).__name__, flush=True)
            return {"prijavljen": True, "ime": "", "kanali": [], "potekla": False, "napaka": True}
        jaz = d.get("currentUser")
        if not isinstance(jaz, dict):
            return {"prijavljen": False, "ime": "", "kanali": [], "potekla": True}
        kanali = [v for v in (vnos_kanala(n) for n in _robovi(jaz.get("follows"))) if v]
        kanali.sort(key=lambda v: (not v["v_zivo"], -int(v.get("gledalcev") or 0), v["naslov"].lower()))
        return {"prijavljen": True, "ime": _niz(jaz.get("displayName") or jaz.get("login"), 80), "kanali": kanali,
                "potekla": False, "zaseben": True}

    # -- kakovost (nastavitev uporabnika, brez zasebnih podatkov)
    def kakovost(self) -> str:
        try:
            with open(self._nastavitve or "", encoding="utf-8") as f:
                k = str(json.load(f).get("kakovost") or "auto")
        except (OSError, ValueError, AttributeError):
            k = "auto"
        return k if k in KAKOVOSTI else "auto"

    def nastavi_kakovost(self, k: str) -> str:
        k = k if k in KAKOVOSTI else "auto"
        if self._nastavitve:
            try:
                os.makedirs(os.path.dirname(self._nastavitve), exist_ok=True)
                from core import shramba_json
                with shramba_json.atomsko_odpri(self._nastavitve) as f:
                    json.dump({"kakovost": k}, f)
            except OSError:
                pass
        return k

    # -- predvajanje
    def _zeton_predvajanja(self, login: str = "", posnetek: str = "", igralec: tuple = GLAVNI) -> Optional[dict]:
        """PlaybackAccessToken (javni, brez prijave). Prijavljen uporabnik ga dobi s svojim zetonom (narocniki in
        Turbo tako ne vidijo oglasov); ce prijava ne velja, brez nje."""
        tip, platforma = igralec
        if posnetek:
            poizvedba = ('query($v: ID!, $t: String!, $p: String!) { videoPlaybackAccessToken(id: $v, params: '
                         '{platform: $p, playerBackend: "mediaplayer", playerType: $t}) { value signature } }')
            spr = {"v": posnetek, "t": tip, "p": platforma}
            kljuc = "videoPlaybackAccessToken"
        else:
            poizvedba = ('query($l: String!, $t: String!, $p: String!) { streamPlaybackAccessToken(channelName: $l, params: '
                         '{platform: $p, playerBackend: "mediaplayer", playerType: $t}) { value signature } }')
            spr = {"l": login, "t": tip, "p": platforma}
            kljuc = "streamPlaybackAccessToken"
        zeton = self.zeton() if igralec == GLAVNI else ""
        try:
            d = self._gql(poizvedba, spr, zeton=zeton)
        except PoteklaPrijava:
            d = self._gql(poizvedba, spr)
        t = d.get(kljuc)
        if not isinstance(t, dict) or not t.get("value") or not t.get("signature"):
            return None
        return {"value": str(t["value"]), "signature": str(t["signature"])}

    def _master(self, login: str = "", posnetek: str = "", igralec: tuple = GLAVNI) -> Optional[tuple[str, str]]:
        """Glavni seznam usher (besedilo, naslov) ali None (kanal ni v zivo, posnetek je zaklenjen ...)."""
        t = self._zeton_predvajanja(login, posnetek, igralec)
        if not t:
            return None
        parametri = {"sig": t["signature"], "token": t["value"], "allow_source": "true", "allow_audio_only": "true",
                     "p": str(random.randint(1, 9_999_999)), "player_backend": "mediaplayer",
                     "playlist_include_framerate": "true", "supported_codecs": "avc1"}
        naslov = (USHER + ("/vod/%s.m3u8" % posnetek if posnetek else "/api/channel/hls/%s.m3u8" % login)
                  + "?" + urllib.parse.urlencode(parametri))
        status, besedilo = self._beri(naslov)
        if status != 200 or not besedilo.lstrip().startswith("#EXTM3U"):
            return None
        return besedilo, naslov

    @property
    def posrednik(self) -> twitch_hls.Posrednik:
        if self._posrednik is None:
            self._posrednik = twitch_hls.Posrednik()
        return self._posrednik

    def predvajaj(self, vnos: dict) -> Optional[dict]:
        """Vnos -> pripravljen za domaci predvajalnik ({"url", "kakovost"}) ali {"napaka_koda"}.

        Prenos v zivo gre skozi lokalni seznam (core/twitch_hls.py: izlocanje oglasov), posnetek neposredno z usher."""
        kakovost, visina = self.kakovost(), int(self.visina_zaslona or 1080)
        if vnos.get("vrsta") == "twitch-posnetek":
            ident = str(vnos.get("id") or "").split(":", 1)[-1]
            if not _ID.match(ident):
                return None
            m = self._master(posnetek=ident)
            izbrana = twitch_hls.izberi(twitch_hls.razlicice(*m), kakovost, visina) if m else None
            if not izbrana or not twitch_hls.dovoljen(izbrana["uri"]):
                return {"napaka_koda": "twitch_ni_posnetka"}
            return {"url": izbrana["uri"], "kakovost": izbrana["ime"]}
        login = str(vnos.get("login") or "")
        if not _LOGIN.match(login):
            return None
        glavni = twitch_hls.Vir("glavni", lambda: self._master(login), kakovost, visina, self._beri)
        sz = glavni.seznam()
        if sz is None:
            return {"napaka_koda": "twitch_ni_v_zivo"}
        rezerve = [twitch_hls.Vir("%s-%s" % igralec, (lambda i=igralec: self._master(login, igralec=i)), kakovost, visina,
                                  self._beri) for igralec in REZERVE]
        seja = twitch_hls.Seja(glavni, rezerve, brez_oglasov=lambda: bool(self.brez_oglasov()))
        self.zadnja_seja = seja
        return {"url": self.posrednik.dodaj(seja), "kakovost": glavni.razlicica}
