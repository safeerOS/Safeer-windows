"""Pravila Scita kot seznam, ki se posodobi brez nove izdaje programa (lastnik, 18. 10. 2026: »nihce ne sme slediti
uporabnikom Safeerja«; oglase in sledilce blokiramo povsod, brez kompromisov).

Kaj je v seznamu:
  - ``sledilci``: analitika in telemetrija TRETJIH (Google Analytics, Meta Pixel, Hotjar ...). Blokirani so kot vir tretje
    strani na vsaki strani (Splet, kanali Sporocil, Medijski center, YouTube, Twitch, Safeer DRM); kdor odpre njihovo
    stran neposredno, jo dobi.
  - ``telemetrija``: gostitelji, ki jih storitev uporablja SAMO za lastno telemetrijo (WhatsApp »dit«, Twitch »spade«) -
    blokirani povsod.
  - ``poti``: zacetek poti, ki nosi samo telemetrijo ali sledenje oglasov na gostitelju, ki ga storitev sicer potrebuje
    (youtube.com/api/stats/qoe, youtube.com/youtubei/v1/log_event ...).
  - ``spotify``: oglasi brezplacnega racuna v Safeer DRM (gostitelji, poti, izbirniki CSS) - prej adblock.SPOTIFY_OGLASI.

Kaj seznam NIKOLI ne more blokirati (``NUJNO``, samo v programu): kar storitev za prijavo in predvajanje nujno
potrebuje (izmerjeno v WebKitGTK 6.0, 18. 10. 2026; glej preizkuse) in preverjanje »ali si clovek«. Pravilo, ki bi
zadelo kaj od tega, se zavrne - tako tudi napacen ali zlonameren seznam ne more pokvariti prijave ali predvajanja. Tudi
storitev ne obidemo: varnostnih preverjanj (Turnstile, reCAPTCHA, BotGuard) se seznam ne sme dotakniti.

Posodobitev: podpisan seznam z istim kljucem Ed25519 in istim preverjanjem kot vir groznj (core/threat_intel.TRUSTED_KEYS,
core/signed_feed.verify_manifest in verify_bundle_bytes: podpis, velikost, SHA-256, samo naprej, rok veljavnosti).
Streznik: https://intel.safeer.si/v1/scit/latest.json in /v1/scit/scit-<verzija>.json. Seznam se prenese ob zagonu
in vsakih 6 ur, preveri, zapise atomarno (stanje je tocka potrditve, kot SignedFeedStore) in uporabi naenkrat (nov
predmet Pravila, nikoli pol starega pol novega). Brez podpisanega seznama ali ob kakrsnikoli napaki velja vgrajeni seznam
(VGRAJENA); novejsi od obeh (po verziji) zmaga.

Brez GTK in WebKita (preizkusi: tests/test_scit_pravila.py); WebKit dobi samo besedilo JSON (webkit_json).
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from core import signed_feed
from core.signed_feed import FeedVerificationError

FEED_TYPE = "scit"
SCHEMA_VERSION = 1
POSODOBITEV_S = 6 * 3600
PONOVNO_S = 3600
PRVA_POSODOBITEV_S = 25
FILTER_ID = "safeer-sledilci"

NAJVEC_GOSTITELJEV = 5000
NAJVEC_POTI = 2000
NAJVEC_CSS = 100
_GOSTITELJ = signed_feed._HOST
#: Pot: zacetek, brez poizvedbe in sidra; »?« je dovoljen samo na koncu (»/tr?« ujame /tr?id=..., ne pa /translate).
_POT = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@%/-]{2,200}\??$")
#: Izbirnik CSS: brez { } ; @ \ < in brez url(...) - iz seznama ne more nastati drugo pravilo ali nalaganje.
_CSS = re.compile(r"""^[A-Za-z0-9 _\-\[\]="'*^$|~:.,#()>+/]{1,300}$""")

# ---------------------------------------------------------------------------------------------------- vgrajeni seznam
#: Verzija vgrajenega seznama (kot verzije streznika: LLLLMMDDUUMM). Podpisan seznam z visjo verzijo ga zamenja.
VGRAJENA_VERZIJA = 202610181200

VGRAJENA: Dict[str, object] = {
    "sledilci": [
        # Google: analitika in oglasno sledenje (ne prijava, ne reCAPTCHA - te so v NUJNO)
        "google-analytics.com", "ssl.google-analytics.com", "analytics.google.com", "googletagmanager.com",
        "googletagservices.com", "googleadservices.com", "doubleclick.net", "googlesyndication.com",
        "adservice.google.com", "app-measurement.com", "firebaselogging-pa.googleapis.com",
        # Meta, TikTok, Snap, Pinterest, LinkedIn, X, Microsoft, Reddit (piksli za oglase in konverzije)
        "pixel.facebook.com", "an.facebook.com", "analytics.tiktok.com", "analytics-sg.tiktok.com",
        "tr.snapchat.com", "sc-static.net", "ct.pinterest.com", "px.ads.linkedin.com", "snap.licdn.com",
        "analytics.twitter.com", "static.ads-twitter.com", "ads-twitter.com",
        "bat.bing.com", "clarity.ms", "c.clarity.ms", "alb.reddit.com", "pixel.reddit.com",
        # Analitika obiskov in posnetki seje
        "hotjar.com", "hotjar.io", "mouseflow.com", "fullstory.com", "luckyorange.com", "luckyorange.net",
        "crazyegg.com", "inspectlet.com", "smartlook.com", "logrocket.io", "lr-ingest.io", "quantummetric.com",
        "contentsquare.net", "heapanalytics.com", "heap.io", "mixpanel.com", "api-js.mixpanel.com",
        "amplitude.com", "api.amplitude.com", "api2.amplitude.com", "segment.io", "api.segment.io",
        "cdn.segment.com", "kissmetrics.io", "plausible.io", "static.cloudflareinsights.com",
        "cloudflareinsights.com", "stats.wp.com", "pixel.wp.com", "matomo.cloud", "statcounter.com",
        "c.statcounter.com", "histats.com", "mc.yandex.ru", "mc.yandex.com",
        # Izmerjeno 18. 10. 2026 (WebKitGTK 6.0): Spotify - Fastly RUM; Twitch - ankete Sprig, oglasi Amazon;
        # RTV 365 (Medijski center) - DotMetrics, analitika JW Player
        "fastly-insights.com", "sprig.com", "amazon-adsystem.com", "dotmetrics.net", "dotmetrics.rocks", "jwpltx.com",
        # Merjenje obcinstva (Comscore, Nielsen, Gemius, AT Internet, Chartbeat, Quantcast)
        "scorecardresearch.com", "sb.scorecardresearch.com", "comscore.com", "imrworldwide.com",
        "gemius.pl", "hit.gemius.pl", "gemius.com", "xiti.com", "ati-host.net", "chartbeat.com",
        "chartbeat.net", "quantserve.com", "quantcount.com",
        # Telemetrija napak in zmogljivosti pri tretjih (samo sprejemniki, ne knjiznice)
        "browser-intake-datadoghq.com", "browser-intake-datadoghq.eu", "browser-intake-us3-datadoghq.com",
        "browser-intake-us5-datadoghq.com", "rum.browser-intake-datadoghq.com", "bam.nr-data.net",
        "bam-cell.nr-data.net", "nr-data.net", "ingest.sentry.io", "ingest.us.sentry.io", "ingest.de.sentry.io",
        "o0.ingest.sentry.io", "bugsnag.com", "sessions.bugsnag.com", "notify.bugsnag.com",
        # Adobe in Oracle (oglasno sledenje in povezovanje identitet)
        "demdex.net", "dpm.demdex.net", "omtrdc.net", "2o7.net", "everesttech.net", "bluekai.com",
        "krxd.net", "cdn.krxd.net", "addthis.com", "adsrvr.org", "rlcdn.com", "agkn.com",
    ],
    "telemetrija": [
        # WhatsApp Web: »deidentified telemetry« in dnevniki sesutij (izmerjeno 18. 10. 2026: prijavna stran in QR
        # delata brez njiju)
        "dit.whatsapp.net", "crashlogs.whatsapp.net",
        # Twitch: analitika »Spade«, porocila dogodkov odjemalca in oglasni streznik (izmerjeno 18. 10. 2026: prenos
        # tece naprej brez njih)
        "spade.twitch.tv", "client-event-reporter.twitch.tv", "edge.ads.twitch.tv",
        # Spotify: oglasno sledenje in piksel (vec v »spotify«)
        "adeventtracker.spotify.com", "pixel.spotify.com", "pixel-static.spotify.com",
        # Discord: analitika (»science«) gre na isti gostitelj kot API - glej poti
    ],
    "poti": [
        # YouTube in youtube-nocookie (vgradni predvajalnik Medijskega centra): kakovost izkusnje, dnevnik dogodkov,
        # sledenje oglasov. Ogled in zgodovina (/api/stats/playback, /watchtime) ostaneta: to je uporabnikov racun.
        ["youtube.com", "/api/stats/qoe"], ["youtube.com", "/api/stats/ads"], ["youtube.com", "/api/stats/atr"],
        ["youtube.com", "/api/stats/delayplay"], ["youtube.com", "/youtubei/v1/log_event"], ["youtube.com", "/ptracking"],
        ["youtube.com", "/pagead/"], ["youtube.com", "/csi_204"], ["youtube.com", "/get_midroll_info"],
        ["youtube-nocookie.com", "/api/stats/qoe"], ["youtube-nocookie.com", "/api/stats/ads"],
        ["youtube-nocookie.com", "/youtubei/v1/log_event"], ["youtube-nocookie.com", "/ptracking"],
        ["youtube-nocookie.com", "/pagead/"], ["youtube-nocookie.com", "/csi_204"],
        ["play.google.com", "/log?"], ["www.google.com", "/pagead/"], ["www.google.com", "/ads/"],
        # Meta (kanali Sporocil: Messenger; drugje vgrajeni gumbi): piksel in dnevniki
        ["facebook.com", "/tr?"], ["facebook.com", "/tr/"], ["connect.facebook.net", "/signals/"],
        ["messenger.com", "/ajax/bz"], ["facebook.com", "/ajax/bz"], ["facebook.com", "/ajax/bnzai"],
        # WhatsApp Web: isti dnevnik »banzai« kot Meta (izmerjeno 18. 10. 2026 na prijavni strani)
        ["whatsapp.com", "/ajax/bz"],
        # Discord: analitika »science« in metrike odjemalca
        ["discord.com", "/api/v9/science"], ["discord.com", "/api/v10/science"], ["discord.com", "/api/v9/metrics"],
        ["discord.com", "/api/v10/metrics"],
    ],
    "spotify": {
        "gostitelji": [
            "adeventtracker.spotify.com", "ads-fa.spotify.com", "adclick.g.doubleclick.net", "pubads.g.doubleclick.net",
            "securepubads.g.doubleclick.net", "googleads.g.doubleclick.net", "pagead2.googlesyndication.com",
            "imasdk.googleapis.com", "spotify.demdex.net",
            # Zvocni oglasi (filtri AdGuard za Spotify, okt. 2026): datoteke oglasov in oglasnih partnerjev.
            "adstudio-assets.scdn.co", "creativeservice-production.scdn.co", "cf.adxcel.com", "media-us.amillionads.com",
        ],
        "poti": [["spotify.com", "/ads/"], ["spotify.com", "/ad-logic/"], ["spotify.com", "/v1/ads/"]],
        "css": [
            '[data-testid="upgrade-button"]', 'a[href*="/premium"]', '[data-testid="embedded-ad"]',
            '[data-testid="ad-slot-container"]', '[data-testid="home-ads-container"]',
            '[data-testid="leavebehind-advertisement"]', '[data-testid="sponsored-content"]',
            'a[data-context-item-type="ad"]', 'div[aria-label="Advertisement"]',
        ],
    },
}

# ---------------------------------------------------------------------------------------------------- varovalo
#: Gostitelji, ki jih storitve nujno potrebujejo (prijava, predvajanje, sporocila) ali so varnostno preverjanje. Pravilo
#: na tak gostitelj ali na njegovo nadrejeno domeno (npr. »google.com«) se zavrne. »*.« = tudi vse poddomene.
NUJNO: Tuple[str, ...] = (
    # Prijava in varnostna preverjanja (lastnik: storitev ne obidemo; BotGuard in reCAPTCHA ostaneta)
    "accounts.google.com", "accounts.youtube.com", "www.google.com", "www.gstatic.com", "ssl.gstatic.com",
    "fonts.gstatic.com", "fonts.googleapis.com", "jnn-pa.googleapis.com", "*.recaptcha.net", "*.hcaptcha.com",
    "challenges.cloudflare.com", "*.cloudflare.com",
    # YouTube (izmerjeno 18. 10. 2026: vgradni predvajalnik nalozi te gostitelje)
    "www.youtube.com", "youtube.com", "m.youtube.com", "music.youtube.com", "www.youtube-nocookie.com",
    "youtubei.googleapis.com", "*.googlevideo.com", "*.ytimg.com", "*.ggpht.com",
    # Spotify
    "open.spotify.com", "accounts.spotify.com", "api.spotify.com", "api-partner.spotify.com", "*.spclient.spotify.com",
    "spclient.wg.spotify.com", "apresolve.spotify.com", "*.dealer.spotify.com", "dealer.spotify.com",
    "audio-ak-spotify-com.akamaized.net", "audio4-ak-spotify-com.akamaized.net", "i.scdn.co", "open.spotifycdn.com",
    "encore.scdn.co", "login5.spotify.com", "clienttoken.spotify.com",
    # Twitch
    "www.twitch.tv", "twitch.tv", "gql.twitch.tv", "passport.twitch.tv", "id.twitch.tv", "irc-ws.chat.twitch.tv",
    "*.ttvnw.net", "*.twitchcdn.net", "*.jtvnw.net", "assets.twitch.tv", "usher.ttvnw.net",
    # Sporocila: WhatsApp, Telegram, Messenger, Discord, Signal (spletni klepeti)
    "web.whatsapp.com", "static.whatsapp.net", "*.whatsapp.net.media", "mmg.whatsapp.net", "pps.whatsapp.net",
    "media.whatsapp.net", "*.telegram.org", "telegram.org", "www.messenger.com", "messenger.com",
    "edge-chat.messenger.com", "www.facebook.com", "*.fbcdn.net", "discord.com", "gateway.discord.gg",
    "cdn.discordapp.com", "media.discordapp.net",
    # Safeer in posodobitve (glej tudi os_scit.POSODOBITVE)
    "safeer.si", "*.safeer.si", "github.com", "api.github.com", "objects.githubusercontent.com",
)
#: Poti, ki jih storitev nujno potrebuje: pravilo poti, ki je njihov zacetek (ali obratno), se zavrne.
NUJNE_POTI: Tuple[Tuple[str, str], ...] = (
    ("youtube.com", "/youtubei/v1/player"), ("youtube.com", "/youtubei/v1/next"), ("youtube.com", "/youtubei/v1/browse"),
    ("youtube.com", "/youtubei/v1/search"), ("youtube.com", "/youtubei/v1/account"), ("youtube.com", "/watch"),
    ("youtube.com", "/embed/"), ("youtube.com", "/s/player/"), ("youtube.com", "/api/timedtext"),
    ("youtube.com", "/api/stats/playback"), ("youtube.com", "/api/stats/watchtime"), ("youtube.com", "/generate_204"),
    ("youtube-nocookie.com", "/embed/"), ("youtube-nocookie.com", "/s/player/"), ("youtube-nocookie.com", "/generate_204"),
    ("youtube-nocookie.com", "/youtubei/v1/player"), ("spotify.com", "/api/"), ("spotify.com", "/v1/me"),
    ("spotify.com", "/connect-state/"), ("spotify.com", "/track-playback/"), ("spotify.com", "/storage-resolve/"),
    ("spotify.com", "/pathfinder/"), ("spotify.com", "/get_access_token"), ("discord.com", "/api/v9/auth"),
    ("discord.com", "/api/v9/users"), ("discord.com", "/api/v9/channels"), ("twitch.tv", "/gql"),
    ("facebook.com", "/login"), ("messenger.com", "/login"),
    # Varnostna preverjanja in prijava (storitev ne obidemo): reCAPTCHA, BotGuard, prijava Google in YouTube
    ("google.com", "/recaptcha/"), ("gstatic.com", "/recaptcha/"), ("google.com", "/js/th/"), ("google.com", "/accounts"),
    ("youtube.com", "/youtubei/v1/att/"), ("whatsapp.com", "/ajax/bootloader-endpoint/"),
)


def _zadene_nujno(gostitelj: str) -> bool:
    """Pravilo na `gostitelj` bi blokiralo nujen gostitelj: isti, njegov nadrejeni ali poddomena varovane domene."""
    for n in NUJNO:
        if n.startswith("*."):
            domena = n[2:]
            if gostitelj == domena or gostitelj.endswith("." + domena) or domena.endswith("." + gostitelj):
                return True
        elif gostitelj == n or n.endswith("." + gostitelj):
            return True
    return False


def _poti_se_prekrivata(a: str, b: str) -> bool:
    return a.startswith(b.rstrip("?")) or b.startswith(a.rstrip("?"))


def _zadene_nujno_pot(gostitelj: str, pot: str) -> bool:
    for g, p in NUJNE_POTI:
        if (gostitelj == g or gostitelj.endswith("." + g) or g.endswith("." + gostitelj)) and _poti_se_prekrivata(pot, p):
            return True
    return False


# ---------------------------------------------------------------------------------------------------- preverjanje
class Pravila:
    """Preverjen, nespremenljiv seznam (Python tuples) - zamenja se v celoti."""

    __slots__ = ("sledilci", "telemetrija", "poti", "spotify_gostitelji", "spotify_poti", "spotify_css", "verzija", "vir")

    def __init__(self, sledilci, telemetrija, poti, spotify_gostitelji, spotify_poti, spotify_css, verzija: int,
                 vir: str) -> None:
        self.sledilci: Tuple[str, ...] = tuple(sledilci)
        self.telemetrija: Tuple[str, ...] = tuple(telemetrija)
        self.poti: Tuple[Tuple[str, str], ...] = tuple(poti)
        self.spotify_gostitelji: Tuple[str, ...] = tuple(spotify_gostitelji)
        self.spotify_poti: Tuple[Tuple[str, str], ...] = tuple(spotify_poti)
        self.spotify_css: Tuple[str, ...] = tuple(spotify_css)
        self.verzija = int(verzija)
        self.vir = vir

    def stevilo(self) -> int:
        return (len(self.sledilci) + len(self.telemetrija) + len(self.poti) + len(self.spotify_gostitelji)
                + len(self.spotify_poti) + len(self.spotify_css))

    # -- uporaba
    @staticmethod
    def _gostitelj(url: str) -> str:
        import urllib.parse
        try:
            return (urllib.parse.urlsplit(url).hostname or "").lower().rstrip(".")
        except ValueError:
            return ""

    @staticmethod
    def _pod(gostitelj: str, domena: str) -> bool:
        return gostitelj == domena or gostitelj.endswith("." + domena)

    def blokira(self, url: str, stran: str = "") -> bool:
        """Ali bi pravila (kot filter WebKita) zavrnila zahtevo `url` na strani `stran` (prazno = tretja stran)."""
        import urllib.parse
        g = self._gostitelj(url)
        if not g:
            return False
        try:
            deli = urllib.parse.urlsplit(url)
            pot = deli.path + ("?" + deli.query if deli.query else "")
        except ValueError:
            return False
        if any(self._pod(g, t) for t in self.telemetrija):
            return True
        if any(self._pod(g, h) and pot.startswith(p) for h, p in self.poti):
            return True
        if any(self._pod(g, s) for s in self.sledilci):
            sg = self._gostitelj(stran) if stran else ""
            return not sg or not _ista_stran(g, sg)
        return False

    def webkit_json(self, nikoli: Iterable[str] = (), ping: bool = True) -> str:
        """Pravila za WebKitUserContentFilterStore (oblika Safari): sledilci kot vir tretje strani, telemetrija in poti
        povsod; na koncu izjema za domene pravih bank (kot pri EasyList - ne dotikamo se njihovih strani).
        ping=False: brez pravila vrste »ping« (WebKit, ki te vrste ne pozna, bi zavrnil ves filter)."""
        from core.webkit_filters import HOST_END, HOST_PREFIX, _escape
        # <a ping> je samo sledenje klikov (Firefox ga privzeto ne posilja): vsi, tudi prve strani (glej zgoraj).
        pravila: List[dict] = ([{"trigger": {"url-filter": ".*", "resource-type": ["ping"]}, "action": {"type": "block"}}]
                               if ping else [])
        for h in self.sledilci:
            pravila.append({"trigger": {"url-filter": HOST_PREFIX + _escape(h) + HOST_END, "load-type": ["third-party"]},
                            "action": {"type": "block"}})
        for h in self.telemetrija:
            pravila.append({"trigger": {"url-filter": HOST_PREFIX + _escape(h) + HOST_END}, "action": {"type": "block"}})
        for h, p in self.poti:
            pravila.append({"trigger": {"url-filter": HOST_PREFIX + _escape(h) + _escape(p)}, "action": {"type": "block"}})
        domene = sorted({str(d).lower().strip(".") for d in nikoli if d})
        if domene:
            pravila.append({"trigger": {"url-filter": ".*", "if-domain": ["*" + d for d in domene]},
                            "action": {"type": "ignore-previous-rules"}})
        return json.dumps(pravila, ensure_ascii=True, separators=(",", ":"))

    def za_drm(self, spotify: bool) -> dict:
        """Pravila za Safeer DRM (assets/safeer_drm/main.js, oglasnaZahteva): sledilci in telemetrija vedno, oglasi
        Spotify samo v seji Spotify. Izbirniki CSS kot eno pravilo (display: none)."""
        gostitelji = list(self.sledilci) + list(self.telemetrija)
        poti = [list(x) for x in self.poti]
        css = ""
        if spotify:
            gostitelji = list(self.spotify_gostitelji) + gostitelji
            poti = [list(x) for x in self.spotify_poti] + poti
            css = (", ".join(self.spotify_css) + " { display: none !important; }") if self.spotify_css else ""
        return {"gostitelji": gostitelji, "poti": poti, "css": css, "verzija": self.verzija}


def _ista_stran(a: str, b: str) -> bool:
    """Grobo: ista zadnja dva dela imena (youtube.com in www.youtube.com). Dovolj za preizkuse; WebKit uporablja
    pravi seznam javnih pripon."""
    return a.split(".")[-2:] == b.split(".")[-2:]


def _seznam(vrednost, ime: str, najvec: int) -> list:
    if vrednost is None:
        return []
    if not isinstance(vrednost, list) or len(vrednost) > najvec:
        raise FeedVerificationError("invalid %s" % ime)
    return vrednost


def _gostitelji(vrednost, ime: str, najvec: int = NAJVEC_GOSTITELJEV) -> List[str]:
    izid: List[str] = []
    for g in _seznam(vrednost, ime, najvec):
        if not isinstance(g, str) or not _GOSTITELJ.match(g):
            raise FeedVerificationError("invalid host in %s" % ime)
        if _zadene_nujno(g):
            raise FeedVerificationError("%s would block a required host: %s" % (ime, g))
        if g not in izid:
            izid.append(g)
    return izid


def _poti(vrednost, ime: str, najvec: int = NAJVEC_POTI) -> List[Tuple[str, str]]:
    izid: List[Tuple[str, str]] = []
    for par in _seznam(vrednost, ime, najvec):
        if (not isinstance(par, list) or len(par) != 2 or not all(isinstance(x, str) for x in par)
                or not _GOSTITELJ.match(par[0]) or not _POT.match(par[1])):
            raise FeedVerificationError("invalid path rule in %s" % ime)
        if _zadene_nujno_pot(par[0], par[1]):
            raise FeedVerificationError("%s would block a required path: %s%s" % (ime, par[0], par[1]))
        if (par[0], par[1]) not in izid:
            izid.append((par[0], par[1]))
    return izid


def preveri_pravila(d, verzija: int, vir: str) -> Pravila:
    """Iz razclenjenega JSON (vgrajen ali podpisan seznam) naredi Pravila ali sprozi FeedVerificationError. Neznani kljuci
    se ne uporabijo (novejsi streznik lahko doda vrsto pravil, starejsi odjemalec jo izpusti)."""
    if not isinstance(d, dict):
        raise FeedVerificationError("rules must be an object")
    sp = d.get("spotify") or {}
    if not isinstance(sp, dict):
        raise FeedVerificationError("invalid spotify rules")
    css = []
    for s in _seznam(sp.get("css"), "spotify.css", NAJVEC_CSS):
        if not isinstance(s, str) or not _CSS.match(s) or "url(" in s.lower():
            raise FeedVerificationError("invalid CSS selector")
        css.append(s)
    # Oglasni gostitelji Spotify so lahko poddomene varovanih domen (imasdk.googleapis.com, adstudio-assets.scdn.co),
    # ne pa varovani gostitelji sami.
    return Pravila(_gostitelji(d.get("sledilci"), "sledilci"), _gostitelji(d.get("telemetrija"), "telemetrija"),
                   _poti(d.get("poti"), "poti"), _gostitelji(sp.get("gostitelji"), "spotify.gostitelji", 500),
                   _poti(sp.get("poti"), "spotify.poti", 200), css, verzija, vir)


def vgrajena() -> Pravila:
    return preveri_pravila(VGRAJENA, VGRAJENA_VERZIJA, "vgrajena")


def _stevilo_pravil(d: dict) -> int:
    sp = d.get("spotify") if isinstance(d.get("spotify"), dict) else {}
    return sum(len(d.get(k) or []) for k in ("sledilci", "telemetrija", "poti")) + \
        sum(len(sp.get(k) or []) for k in ("gostitelji", "poti", "css"))


def preveri_paket(paket: bytes, manifest, kljuci: dict) -> Pravila:
    """Podpisan paket seznama: velikost, SHA-256 in podpis (signed_feed.verify_bundle_bytes), kanonicni JSON, metapodatki
    se ujemajo z manifestom, SHA-256 pravil, stevilo pravil, nato vsebina (preveri_pravila)."""
    signed_feed.verify_bundle_bytes(paket, manifest, kljuci)
    vsebina = signed_feed._strict_loads(paket)
    if not isinstance(vsebina, dict) or signed_feed.canonical_json(vsebina) != paket:
        raise FeedVerificationError("bundle is not in canonical form")
    if set(vsebina) != {"schema_version", "feed_type", "version", "generated_at", "expires_at", "rule_count", "sha256",
                        "sources", "rules"} or vsebina["schema_version"] != SCHEMA_VERSION:
        raise FeedVerificationError("unexpected bundle fields")
    if (vsebina["feed_type"] != FEED_TYPE or vsebina["version"] != manifest.version
            or signed_feed._parse_time(vsebina["generated_at"]) != manifest.generated_at
            or signed_feed._parse_time(vsebina["expires_at"]) != manifest.expires_at):
        raise FeedVerificationError("bundle metadata does not match the manifest")
    pravila = vsebina["rules"]
    if not isinstance(pravila, dict):
        raise FeedVerificationError("rules must be an object")
    sha = hashlib.sha256(signed_feed.canonical_json(pravila)).hexdigest()
    if vsebina["sha256"] != manifest.rules_sha256 or sha != vsebina["sha256"]:
        raise FeedVerificationError("rules SHA-256 mismatch")
    if vsebina["rule_count"] != manifest.rule_count or _stevilo_pravil(pravila) != vsebina["rule_count"]:
        raise FeedVerificationError("rule count mismatch")
    return preveri_pravila(pravila, manifest.version, "podpisana")


def zgradi_paket(pravila: dict, verzija: int, ustvarjeno: datetime, potece: datetime,
                 viri: Optional[list] = None) -> Tuple[bytes, dict]:
    """Paket (kanonicni JSON) in nepodpisan del manifesta za orodje, ki seznam podpise (tools/scit_pravila_podpisi.py).
    Podpis naredi lastnik s kljucem, ki ga ni v nobenem repozitoriju."""
    preveri_pravila(pravila, verzija, "orodje")            # kar odjemalec zavrne, se ne podpise
    cas = lambda t: t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    vsebina = {"schema_version": SCHEMA_VERSION, "feed_type": FEED_TYPE, "version": int(verzija),
               "generated_at": cas(ustvarjeno), "expires_at": cas(potece), "rule_count": _stevilo_pravil(pravila),
               "sha256": hashlib.sha256(signed_feed.canonical_json(pravila)).hexdigest(),
               "sources": viri or [{"id": "safeer", "name": "Safeer", "license": "MIT", "url": "https://safeer.si"}],
               "rules": pravila}
    paket = signed_feed.canonical_json(vsebina)
    manifest = {"schema_version": signed_feed.SCHEMA_VERSION, "type": "safeer-feed-manifest", "feed_type": FEED_TYPE,
                "version": int(verzija), "generated_at": vsebina["generated_at"], "expires_at": vsebina["expires_at"],
                "rule_count": vsebina["rule_count"], "rules_sha256": vsebina["sha256"],
                "bundle": {"path": "%s-%d.json" % (FEED_TYPE, verzija), "size": len(paket),
                           "sha256": hashlib.sha256(paket).hexdigest()}}
    return paket, manifest


# ---------------------------------------------------------------------------------------------------- shramba
class PodpisanSeznam:
    """Zadnji preverjen podpisan seznam na disku (isti vzorec kot signed_feed.SignedFeedStore: datoteke verzije, stanje
    kot tocka potrditve, samo naprej)."""

    def __init__(self, mapa, kljuci: dict, osnove: Iterable[str], fetch=None, cas: float = 20.0) -> None:
        self.mapa = Path(mapa)
        self.kljuci = dict(kljuci)
        self.osnove = [u.rstrip("/") for u in osnove]
        self._fetch = fetch or (lambda url, meja: signed_feed._read_limited(url, meja, cas))
        self.zadnja_napaka = ""

    def _datoteki(self, verzija: int):
        return (self.mapa / ("%s-%d-manifest.json" % (FEED_TYPE, verzija)),
                self.mapa / ("%s-%d-bundle.json" % (FEED_TYPE, verzija)))

    @property
    def _stanje(self) -> Path:
        return self.mapa / ("%s-state.json" % FEED_TYPE)

    def namescena_verzija(self) -> int:
        try:
            v = json.loads(self._stanje.read_text("ascii")).get("version", 0)
            return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0
        except (OSError, ValueError, AttributeError):
            return 0

    def nalozi(self) -> Optional[Pravila]:
        """Shranjen seznam, znova preverjen (podpis in vsebina). Pretecen se se uporabi (bolje kot nic)."""
        verzija = self.namescena_verzija()
        if verzija < 1:
            return None
        pot_m, pot_p = self._datoteki(verzija)
        try:
            manifest = signed_feed.verify_manifest(pot_m.read_bytes(), self.kljuci, FEED_TYPE, check_expiry=False)
            if manifest.version != verzija:
                raise FeedVerificationError("stored manifest does not match the recorded version")
            return preveri_paket(pot_p.read_bytes(), manifest, self.kljuci)
        except (OSError, FeedVerificationError) as e:
            self.zadnja_napaka = "shranjen seznam: %s" % e
            return None

    def posodobi(self, zdaj: Optional[datetime] = None) -> Optional[Pravila]:
        """Prenese, preveri in namesti novejsi seznam; vrne nova Pravila ali None (ni novega ali napaka)."""
        namescena = self.namescena_verzija()
        napake = []
        for osnova in self.osnove:
            try:
                m_bajti = self._fetch("%s/v1/%s/latest.json" % (osnova, FEED_TYPE), signed_feed.MAX_MANIFEST_BYTES)
                manifest = signed_feed.verify_manifest(m_bajti, self.kljuci, FEED_TYPE, installed_version=namescena,
                                                       now=zdaj)
                if manifest.version == namescena:
                    self.zadnja_napaka = ""
                    return None
                p_bajti = self._fetch("%s/v1/%s/%s" % (osnova, FEED_TYPE, manifest.bundle_path), manifest.bundle_size)
                pravila = preveri_paket(p_bajti, manifest, self.kljuci)
                pot_m, pot_p = self._datoteki(manifest.version)
                signed_feed._atomic_write(pot_p, p_bajti)
                signed_feed._atomic_write(pot_m, m_bajti)
                # Tocka potrditve: dokler stanje ni zamenjano, nalozi() uporablja stari datoteki.
                signed_feed._atomic_write(self._stanje, json.dumps({"version": manifest.version}).encode("ascii"))
                for stara in self.mapa.glob("%s-*-*.json" % FEED_TYPE):
                    deli = stara.name.split("-")
                    if len(deli) >= 3 and deli[1].isdigit() and int(deli[1]) < manifest.version:
                        try:
                            stara.unlink()
                        except OSError:
                            pass
                self.zadnja_napaka = ""
                return pravila
            except Exception as e:  # noqa: BLE001 - omrezje, preverjanje, disk: ostane dosedanji seznam
                napake.append("%s: %s: %s" % (osnova, type(e).__name__, e))
        self.zadnja_napaka = "; ".join(napake)
        return None


# ---------------------------------------------------------------------------------------------------- storitev
class StoritevPravil:
    """Trenutna pravila za ves proces in posodabljanje v ozadju. ob_spremembi(cb): cb(pravila) po vsaki zamenjavi
    (klice se iz niti - kdor dela z GTK, naj gre prek GLib.idle_add)."""

    def __init__(self, mapa, kljuci: Optional[dict] = None, osnove: Optional[Iterable[str]] = None, fetch=None,
                 interval: float = POSODOBITEV_S, ponovno: float = PONOVNO_S, prva: float = PRVA_POSODOBITEV_S) -> None:
        if kljuci is None or osnove is None:
            from core import threat_intel
            kljuci = threat_intel.TRUSTED_KEYS if kljuci is None else kljuci
            osnove = threat_intel.BASE_URLS if osnove is None else osnove
        self.seznam = PodpisanSeznam(mapa, kljuci, osnove, fetch=fetch)
        self._pravila = vgrajena()
        self._poslusalci: List[Callable[[Pravila], None]] = []
        self._kljuc = threading.Lock()
        self._stop = threading.Event()
        self._nit: Optional[threading.Thread] = None
        self.interval, self.ponovno, self.prva = interval, ponovno, prva
        self.zadnja_preverba = 0.0

    @property
    def pravila(self) -> Pravila:
        return self._pravila

    def ob_spremembi(self, cb: Callable[[Pravila], None]) -> None:
        with self._kljuc:
            self._poslusalci.append(cb)

    def _uporabi(self, nova: Optional[Pravila]) -> bool:
        """Zamenja pravila naenkrat - samo z novejsimi (po verziji). Vgrajen seznam novejse izdaje programa ostane,
        ce je novejsi od shranjenega podpisanega."""
        if nova is None:
            return False
        with self._kljuc:
            if nova.verzija <= self._pravila.verzija:
                return False
            self._pravila = nova
            poslusalci = list(self._poslusalci)
        for cb in poslusalci:
            try:
                cb(nova)
            except Exception as e:  # noqa: BLE001
                print("[Scit] pravila, poslusalec:", type(e).__name__, e, flush=True)
        return True

    def zazeni(self) -> bool:
        if self._nit is not None:
            return False
        self._nit = threading.Thread(target=self._tek, name="safeer-scit-pravila", daemon=True)
        self._nit.start()
        return True

    def ustavi(self) -> None:
        self._stop.set()

    def posodobi_zdaj(self) -> bool:
        self.zadnja_preverba = time.time()
        try:
            return self._uporabi(self.seznam.posodobi())
        except Exception as e:  # noqa: BLE001
            self.seznam.zadnja_napaka = "%s: %s" % (type(e).__name__, e)
            return False

    def _tek(self) -> None:
        try:
            self._uporabi(self.seznam.nalozi())
        except Exception:  # noqa: BLE001 - pokvarjen shranjen seznam ne sme ustaviti zagona
            pass
        if self._stop.wait(self.prva):
            return
        while not self._stop.is_set():
            self.posodobi_zdaj()
            cakaj = self.interval if not self.seznam.zadnja_napaka else self.ponovno
            if self._stop.wait(cakaj * random.uniform(0.9, 1.1)):
                return

    def stanje(self) -> dict:
        p = self._pravila
        return {"verzija": p.verzija, "vir": p.vir, "pravil": p.stevilo(), "preverjeno": self.zadnja_preverba,
                "napaka": bool(self.seznam.zadnja_napaka)}


_SKUPNA: Optional[StoritevPravil] = None
_SKUPNA_ZAKLEP = threading.Lock()


def privzeta_mapa() -> Path:
    from core.threat_intel import default_data_dir
    return default_data_dir("safeer-mint").parent / "scit-pravila"


def skupna(zazeni: bool = True) -> StoritevPravil:
    """Ena storitev na proces (Splet, Scit, Medijski center, Safeer DRM berejo ista pravila)."""
    global _SKUPNA
    with _SKUPNA_ZAKLEP:
        if _SKUPNA is None:
            _SKUPNA = StoritevPravil(privzeta_mapa())
        if zazeni:
            _SKUPNA.zazeni()
        return _SKUPNA


def trenutna() -> Pravila:
    """Pravila, ki veljajo zdaj (brez zagona posodabljanja - npr. ob zagonu Safeer DRM)."""
    s = _SKUPNA
    return s.pravila if s is not None else vgrajena()


# ---------------------------------------------------------------------------------------------------- proti prstnim odtisom
#: Funkcije WebKitGTK 6.0, ki jih zasebnost potrebuje (preverjeno z introspekcijo Settings.get_all_features, WebKitGTK
#: 2.52.6, 18. 10. 2026; vsaka se nastavi samo, ce jo WebKit pozna):
#:  - ICECandidateFiltering vklop: WebRTC strani ne pove lokalnih naslovov IP (privzeto vklopljeno - zaklenemo);
#:  - EnumeratingAllNetworkInterfaces izklop: WebRTC ne nasteje vseh vmesnikov (VPN, Docker);
#:  - NavigatorUserAgentDataJavaScriptAPI izklop: brez navigator.userAgentData (podrobnosti sistema za prstni odtis).
#: Prve tri so v 2.52 ze privzete - zaklenemo jih, da jih nova razlicica WebKita ne obrne tiho.
#: LinkDNSPrefetch ostane: s posrednikom DoH ime iz <link rel=dns-prefetch> ne gre na sistemski DNS (strace omreznega
#: procesa 18. 10. 2026: ime gre le po IPC, nobene poizvedbe na vrata 53).
FUNKCIJE_ZASEBNOSTI = (("ICECandidateFiltering", True), ("EnumeratingAllNetworkInterfaces", False),
                       ("NavigatorUserAgentDataJavaScriptAPI", False))
#: <a ping> (sledenje klikov): nastavitev enable-hyperlink-auditing je v WebKitGTK 6.0 »deprecated and does nothing«
#: (izmerjeno 18. 10. 2026: ping je sel ven tudi z izklopljeno). Zato ga ustavi pravilo filtra vrste »ping«
#: (webkit_json) - izmerjeno: ustavi <a ping>, navigator.sendBeacon pa ne (tega ustavijo pravila gostiteljev).


#: Stabilne funkcije WebKita, ki so v WebKitGTK privzeto izklopljene, strani pa jih pricakujejo (webmaster pregled
#: motorja 20. 10. 2026, testni PC, WebKitGTK 2.54.1): brez StorageAPI je navigator.storage undefined in
#: navigator.storage.estimate()/persist() v PWA in spletnih urejevalnikih vrze napako JS (status »stable«).
FUNKCIJE_SPLETA = (("StorageAPI", True), ("StorageAPIEstimate", True))


def zasebnost_pogleda(WebKit, nastavitve) -> List[str]:
    """Nastavi zasebnost pogleda (Splet, kanali Sporocil, Medijski center); vrne nastavljene funkcije."""
    return nastavi_funkcije(WebKit, nastavitve, FUNKCIJE_ZASEBNOSTI)


def funkcije_spleta(WebKit, nastavitve) -> List[str]:
    """Stabilne spletne funkcije, ki jih WebKitGTK privzeto ne vklopi (FUNKCIJE_SPLETA)."""
    return nastavi_funkcije(WebKit, nastavitve, FUNKCIJE_SPLETA)


def nastavi_funkcije(WebKit, nastavitve, pari) -> List[str]:
    """Funkcije WebKita po imenu (samo tiste, ki jih ta WebKit pozna); vrne nastavljene."""
    izid: List[str] = []
    try:
        funkcije = WebKit.Settings.get_all_features()
    except Exception:  # noqa: BLE001 - WebKit pred 2.42 nima API funkcij
        return izid
    zelene = dict(pari)
    for i in range(funkcije.get_length()):
        f = funkcije.get(i)
        ime = f.get_identifier()
        if ime in zelene:
            try:
                nastavitve.set_feature_enabled(f, zelene[ime])
                izid.append(ime)
            except Exception:  # noqa: BLE001
                pass
    return izid


# ---------------------------------------------------------------------------------------------------- filter WebKit
def _banke() -> tuple:
    try:
        from core import adblock
        return adblock.real_bank_domains()
    except Exception:  # noqa: BLE001
        return ()


class FilterSledilcev:
    """Preveden filter WebKit (vsebinski blokator v omreznem sloju, pred JavaScriptom) iz trenutnih pravil - en na
    proces za vse poglede: zavihke in kanale Spleta, vgrajene vire in predvajalnik Medijskega centra. Izmerjeno
    18. 10. 2026: 171 pravil se prevede v ~30 ms, zato ga ob zagonu in ob vsakem novem seznamu prevedemo znova.

    WebKit in GLib dobi kot argumenta (modul ostane brez GTK). Vse metode na glavni niti; nov seznam pride iz niti
    storitve prek GLib.idle_add."""

    def __init__(self, WebKit, GLib, mapa, storitev: Optional[StoritevPravil] = None) -> None:
        self.WebKit, self.GLib = WebKit, GLib
        self.filter = None
        self._sha = ""
        self._poslusalci: List[Callable] = []
        Path(mapa).mkdir(parents=True, exist_ok=True)
        self._shramba = WebKit.UserContentFilterStore.new(str(mapa))
        self.storitev = storitev or skupna()
        self.storitev.ob_spremembi(lambda pravila: GLib.idle_add(self._prevedi, pravila))
        self._prevedi(self.storitev.pravila)

    def _prevedi(self, pravila: Pravila, ping: bool = True) -> bool:
        besedilo = pravila.webkit_json(nikoli=_banke(), ping=ping)
        sha = hashlib.sha256(besedilo.encode("utf-8")).hexdigest()
        if sha != self._sha:
            self._sha = sha
            self._shramba.save(FILTER_ID, self.GLib.Bytes.new(besedilo.encode("utf-8")), None, self._prevedeno,
                               (sha, pravila, ping))
        return False

    def _prevedeno(self, shramba, rezultat, podatki) -> None:
        sha, pravila, ping = podatki
        try:
            nov = shramba.save_finish(rezultat)
        except Exception as e:  # noqa: BLE001 - ostane prejsnji filter
            print("[Scit] filter sledilcev:", type(e).__name__, e, flush=True)
            if ping and sha == self._sha:
                self._prevedi(pravila, ping=False)      # starejsi WebKit brez vrste »ping«: vsaj sledilci
            return
        if sha != self._sha:
            return          # medtem je prisel se novejsi seznam - ta se prevaja
        self.filter = nov
        for cb in list(self._poslusalci):
            try:
                cb(nov)
            except Exception as e:  # noqa: BLE001
                print("[Scit] filter sledilcev, pogled:", type(e).__name__, e, flush=True)

    def ob_novem(self, cb: Callable) -> None:
        """cb(filter) ob vsakem novem prevodu (in takoj, ce je ze preveden)."""
        self._poslusalci.append(cb)
        if self.filter is not None:
            cb(self.filter)

    def uporabi(self, pogled, vklop: bool = True) -> None:
        """Na pogled (njegov upravitelj vsebine) doda filter ali ga odstrani (uporabnik je stran izvzel)."""
        upravitelj = pogled.get_user_content_manager()
        upravitelj.remove_filter_by_id(FILTER_ID)
        if vklop and self.filter is not None:
            upravitelj.add_filter(self.filter)


_FILTER: Optional[FilterSledilcev] = None


def filter_sledilcev(WebKit, GLib) -> Optional[FilterSledilcev]:
    """Skupni filter sledilcev procesa (prvi klic ga ustvari). None, ce ga WebKit ne zmore (ne ugibamo)."""
    global _FILTER
    if _FILTER is None:
        try:
            from core.threat_intel import default_data_dir
            _FILTER = FilterSledilcev(WebKit, GLib, default_data_dir("safeer-mint").parent / "filter-lists" / "compiled")
        except Exception as e:  # noqa: BLE001
            print("[Scit] filter sledilcev:", type(e).__name__, e, flush=True)
            return None
    return _FILTER
