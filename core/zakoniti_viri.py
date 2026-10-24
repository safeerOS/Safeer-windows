"""Javni, zakoniti katalogi za Safeer Media (PeerTube, Jamendo, Radio Browser)."""
from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait as _pocakaj_na, TimeoutError as FuturesTimeout
from typing import Any

# Vgrajeni PeerTube strezniki z urejeno vsebino. peertube.tv in peertube.uno sta 27. 9. 2026 med najbolj
# gledanimi imela celotne komercialne filme (piratske nalozbe), zato ju ne uporabljamo in ju izlocimo tudi iz iskanja.
PEERTUBE_INSTANCES = ("tilvids.com", "framatube.org", "video.blender.org")
PEERTUBE_BLOKIRANI = frozenset({"peertube.tv", "peertube.uno"})
# Znaki piratske nalozbe v naslovu (celoten film "v streamingu", rip z YouTuba ipd.).
_PEERTUBE_SUMLJIVO = re.compile(
    r"(?:film|documentario|pel[ií]cula|documental)\s+complet|full\s+movie|ganzer\s+film|film\s+complet|"
    r"streaming\s+(?:sub\s+)?ita|\bsub\s+ita\b|\b(?:hd|dvd|br|web)rip\b|\bweb-?dl\b|\bbluray\b|\bhdcam\b|"
    r"\[[A-Za-z0-9_-]{11}\]\s*$", re.I)
# Filmi v javni lasti z Internet Archive: samo vnosi z izrecno licenco javne lasti (CC PD / CC0).
# Zbirka feature_films vsebuje tudi uporabniske nalozbe, zato brez licence ne prikazemo nicesar.
ARCHIVE_PD_QUERY = "collection:feature_films AND mediatype:movies AND licenseurl:*publicdomain*"
#: Filmske zvrsti Medijskega centra (id TMDB, kot v assets/os/os.js KAT_FILMSKI_ZANRI) -> predmet (subject) v Internet Archive.
ARCHIVE_ZVRSTI = {"28": "action", "878": "science fiction", "35": "comedy", "27": "horror", "18": "drama",
                  "53": "thriller", "16": "animation", "10749": "romance"}
_ARCHIVE_SUMLJIVO = re.compile(r"torrent|\b(?:dvd|br|web|hd|bd)?rip\b|\bhdcam\b|\bx26[45]\b|\bxvid\b|\bcam\b", re.I)
# Jezik vsebine kot koda ISO 639-1 (za filter jezikov); sprejme kode, angleska in slovenska imena.
_JEZIKI = {
    "eng": "en", "english": "en", "anglescina": "en", "angleščina": "en",
    "deu": "de", "ger": "de", "german": "de", "deutsch": "de", "nemscina": "de", "nemščina": "de",
    "fra": "fr", "fre": "fr", "french": "fr", "francais": "fr", "français": "fr", "francoscina": "fr", "francoščina": "fr",
    "spa": "es", "spanish": "es", "espanol": "es", "español": "es", "spanscina": "es", "španščina": "es",
    "ita": "it", "italian": "it", "italiano": "it", "italijanscina": "it", "italijanščina": "it",
    "slv": "sl", "slovenian": "sl", "slovene": "sl", "slovenscina": "sl", "slovenščina": "sl",
    "hrv": "hr", "croatian": "hr", "hrvascina": "hr", "hrvaščina": "hr", "srp": "sr", "serbian": "sr",
    "por": "pt", "portuguese": "pt", "rus": "ru", "russian": "ru", "jpn": "ja", "japanese": "ja",
    "kor": "ko", "korean": "ko", "koreanscina": "ko", "korejščina": "ko", "zho": "zh", "chi": "zh", "chinese": "zh",
    "ara": "ar", "arabic": "ar", "arabscina": "ar", "arabščina": "ar", "tur": "tr", "turkish": "tr", "turscina": "tr", "turščina": "tr",
    "nld": "nl", "dut": "nl", "dutch": "nl", "pol": "pl", "polish": "pl", "hin": "hi", "hindi": "hi",
    "swe": "sv", "swedish": "sv", "hun": "hu", "hungarian": "hu", "ces": "cs", "cze": "cs", "czech": "cs",
}


def jezik_koda(vrednost) -> str:
    if isinstance(vrednost, list):
        vrednost = vrednost[0] if vrednost else ""
    besedilo = str(vrednost or "").strip().lower().split(",")[0].split(";")[0].strip()
    besedilo = besedilo.split("-")[0].split("_")[0]
    if not besedilo or besedilo in ("und", "zxx", "mul", "xx"):
        return ""
    if besedilo in _JEZIKI:
        return _JEZIKI[besedilo]
    return besedilo if re.fullmatch(r"[a-z]{2}", besedilo) else ""


JAMENDO_CLIENT_ID = "8d37f069"  # Javen client_id aplikacije Safeer TV.
RADIO_TAGS = ("jazz", "rock", "pop", "news", "classical", "electronic")
#: Glasbene zvrsti za Glasbo in Radio v Medijskem centru (kot zanri pri filmih):
#: kljuc -> (ime za uporabnika, oznaka Jamendo ali "", oznaka Radio Browser ali "").
GLASBENE_ZVRSTI = {
    "pop": ("Pop", "pop", "pop"),
    "rock": ("Rock", "rock", "rock"),
    "elektronska": ("Elektronska", "electronic", "electronic"),
    "hiphop": ("Hip-hop", "hiphop", "hip hop"),
    "jazz": ("Jazz", "jazz", "jazz"),
    "klasicna": ("Klasična", "classical", "classical"),
    "metal": ("Metal", "metal", "metal"),
    "plesna": ("Plesna", "dance", "dance"),
    "ljudska": ("Ljudska", "folk", "folk"),
    "reggae": ("Reggae", "reggae", "reggae"),
    "sprostitvena": ("Sprostitvena", "ambient", "chillout"),
    "filmska": ("Filmska", "soundtrack", "soundtrack"),
    "country": ("Country", "country", "country"),
    "novice": ("Novice in pogovor", "", "news"),
}


#: TV v zivo: samo uradni, javno objavljeni prenosi izdajateljev (preverjeno, da tecejo), brez posrednikov.
#: (id, ime, jezik, url HLS ali "", uradna stran, samo za drzavo ("" = za vse), drzava izdajatelja)
TV_V_ZIVO = (
    # RTV 365: vsak program na svoji strani (/programi/<kanal>); prejsnji /v-zivo je od jeseni 2026 stran 404
    # (lastnik, 14. 10. 2026). Poti preverjene na 365.rtvslo.si/programi istega dne.
    ("tvs1", "TV SLO 1", "slovenščina", "", "https://365.rtvslo.si/programi/tvs1", "SI", "SI"),
    ("tvs2", "TV SLO 2", "slovenščina", "", "https://365.rtvslo.si/programi/tvs2", "SI", "SI"),
    ("tvs3", "TV SLO 3", "slovenščina", "", "https://365.rtvslo.si/programi/tvs3", "SI", "SI"),
    ("mmctv", "MMC TV", "slovenščina", "", "https://365.rtvslo.si/programi/mmctv", "SI", "SI"),
    ("tvkp", "TV Koper", "slovenščina", "", "https://365.rtvslo.si/programi/tvkp", "SI", "SI"),
    ("tvmb", "TV Maribor", "slovenščina", "", "https://365.rtvslo.si/programi/tvmb", "SI", "SI"),
    ("dw-en", "DW News", "angleščina", "https://dwamdstream102.akamaized.net/hls/live/2015525/dwstream102/index.m3u8", "", "", "DE"),
    ("dw-de", "DW Deutsch", "nemščina", "https://dwamdstream103.akamaized.net/hls/live/2015526/dwstream103/index.m3u8", "", "", "DE"),
    ("dw-es", "DW Español", "španščina", "https://dwamdstream104.akamaized.net/hls/live/2015530/dwstream104/index.m3u8", "", "", "DE"),
    ("f24-en", "France 24 English", "angleščina", "https://live.france24.com/hls/live/2037218/F24_EN_HI_HLS/master_5000.m3u8", "", "", "FR"),
    ("f24-fr", "France 24 Français", "francoščina", "https://live.france24.com/hls/live/2037179/F24_FR_HI_HLS/master_5000.m3u8", "", "", "FR"),
    ("f24-es", "France 24 Español", "španščina", "https://live.france24.com/hls/live/2037220/F24_ES_HI_HLS/master_5000.m3u8", "", "", "FR"),
    ("aje", "Al Jazeera English", "angleščina", "https://live-hls-apps-aje-fa.getaj.net/AJE/index.m3u8", "", "", "QA"),
    ("trt-world", "TRT World", "angleščina", "https://tv-trtworld.medya.trt.com.tr/master.m3u8", "", "", "TR"),
    ("cbs-news", "CBS News 24/7", "angleščina", "https://cbsn-us.cbsnstream.cbsnews.com/out/v1/55a8648e8f134e82a470f83d562deeca/master.m3u8", "", "", "US"),
    ("arirang", "Arirang TV", "angleščina", "https://amdlive-ch01-ctnd-com.akamaized.net/arirang_1ch/smil:arirang_1ch.smil/playlist.m3u8", "", "", "KR"),
    ("tagesschau24", "tagesschau24 (ARD)", "nemščina", "https://tagesschau.akamaized.net/hls/live/2020115/tagesschau/tagesschau_1/master.m3u8", "", "", "DE"),
    ("redbull", "Red Bull TV", "angleščina", "https://rbmn-live.akamaized.net/hls/live/590964/BoRB-AT/master.m3u8", "", "", "AT"),
)


#: Domaca stran izdajatelja za logotip kanala (ikone_strani: neposredno s strani, shranjeno v predpomnilnik).
#: Lastnik 14. 10. 2026: pri TV v zivo so manjkale ikone.
DOMACE_STRANI = {"SI": "https://www.rtvslo.si/", "dw": "https://www.dw.com/", "f24": "https://www.france24.com/",
                 "aje": "https://www.aljazeera.com/", "trt-world": "https://www.trtworld.com/",
                 "cbs-news": "https://www.cbsnews.com/", "arirang": "https://www.arirang.com/",
                 "tagesschau24": "https://www.tagesschau.de/", "redbull": "https://www.redbull.com/"}


def domaca_stran(kljuc: str, izvor: str) -> str:
    if izvor == "SI":
        return DOMACE_STRANI["SI"]
    return DOMACE_STRANI.get(kljuc) or DOMACE_STRANI.get(kljuc.split("-")[0], "")


def logotip(kljuc: str, izvor: str, prenesi: bool = True) -> str:
    """Logotip kanala (data URL) iz predpomnilnika; manjkajocega prenese v ozadju (naslednji izris ga pokaze)."""
    from core import ikone_strani
    stran = domaca_stran(kljuc, izvor)
    if not stran:
        return ""
    ikona = ikone_strani.iz_predpomnilnika(stran)
    if ikona or not prenesi:
        return ikona
    if _logotip_zacni(stran):
        threading.Thread(target=_logotip_prenesi, args=(stran,), daemon=True).start()
    return ""


#: Logotipi, ki se prav zdaj prenasajo (stran -> True), in kdaj je prenos nazadnje spodletel (stran -> time.monotonic()).
_LOGOTIPI_V_TEKU: set = set()
_LOGOTIPI_NEUSPELI: dict = {}
_LOGOTIPI_ZAKLEP = threading.Lock()
#: Spodleteli logotip poskusimo znova sele cez 10 min: prej ga tv_v_zivo() ne caka (pregled 14. 10. 2026: logotip,
#: ki ni uspel, se do ponovnega zagona ni vec poskusil, katalog pa je ob vsakem izrisu cakal nanj do 4 s).
LOGOTIP_ZNOVA_S = 600.0


def _logotip_zacni(stran: str) -> bool:
    """Ali naj ta klic prenese logotip: ni ze v teku in ni nedavno spodletel (oznaci ga kot v teku)."""
    with _LOGOTIPI_ZAKLEP:
        neuspel = _LOGOTIPI_NEUSPELI.get(stran)
        if stran in _LOGOTIPI_V_TEKU or (neuspel is not None and time.monotonic() - neuspel < LOGOTIP_ZNOVA_S):
            return False
        _LOGOTIPI_V_TEKU.add(stran)
        return True


def _logotip_prenesi(stran: str) -> None:
    from core import ikone_strani
    i = None
    try:
        i = ikone_strani.ikona_strani(stran)
        if i:
            ikone_strani.shrani(stran, i)
    except Exception:  # noqa: BLE001 - logotip je okras; brez njega kartica pokaze ime
        i = None
    finally:
        with _LOGOTIPI_ZAKLEP:
            _LOGOTIPI_V_TEKU.discard(stran)
            if i:
                _LOGOTIPI_NEUSPELI.pop(stran, None)
            else:
                _LOGOTIPI_NEUSPELI[stran] = time.monotonic()


DRZAVE = {"SI": "Slovenija", "DE": "Nemčija", "FR": "Francija", "QA": "Katar", "TR": "Turčija", "US": "ZDA",
          "KR": "Južna Koreja", "AT": "Avstrija", "HR": "Hrvaška", "IT": "Italija", "GB": "Združeno kraljestvo"}


def tv_drzave(drzava_uporabnika: str = "", moji: bool = False) -> list[dict]:
    """Drzave za TV v zivo (kot zanri): najprej uporabnikova, nato druge; na koncu njegov sprejemnik."""
    drzava_uporabnika = (drzava_uporabnika or "").upper()
    prisotne = []
    for _k, _i, _j, _u, _s, samo, izvor in TV_V_ZIVO:
        if samo and samo != drzava_uporabnika:
            continue
        if izvor not in prisotne:
            prisotne.append(izvor)
    prisotne.sort(key=lambda d: (d != drzava_uporabnika, DRZAVE.get(d, d)))
    izid = [{"id": d, "ime": DRZAVE.get(d, d)} for d in prisotne]
    if moji:
        izid.append({"id": "moji", "ime": "Moji kanali"})
    return izid


def pripravi_logotipe(cas: float = 4.0) -> None:
    """Manjkajoce logotipe kanalov prenese hkrati (enkrat; nato so v predpomnilniku na disku). Katalog TV v zivo
    se namrec shrani - logotip, prenesen sele po izrisu, bi se pokazal sele ob naslednji osvezitvi (10 min)."""
    from concurrent.futures import ThreadPoolExecutor, wait
    from core import ikone_strani
    manjkajo = sorted({domaca_stran(k, izvor) for k, _i, _j, _u, _s, _samo, izvor in TV_V_ZIVO} - {""})
    # V teku ali nedavno spodleteli ne cakamo (_logotip_zacni): tv_v_zivo() caka samo na prvi poskus.
    manjkajo = [s for s in manjkajo if not ikone_strani.iz_predpomnilnika(s) and _logotip_zacni(s)]
    if not manjkajo:
        return
    pool = ThreadPoolExecutor(max_workers=8)
    wait([pool.submit(_logotip_prenesi, s) for s in manjkajo], timeout=cas)
    pool.shutdown(wait=False)


def tv_v_zivo(drzava: str = "") -> list[dict]:
    """Uradni prenosi v zivo; domaci (npr. RTV SLO) samo za uporabnike iz te drzave."""
    pripravi_logotipe()
    izid = []
    for kljuc, ime, jezik, url, stran, samo, izvor in TV_V_ZIVO:
        if samo and samo != (drzava or "").upper():
            continue
        vnos = {"id": "tv:" + kljuc, "naslov": ime, "vrsta": "tv-v-zivo", "vir": ime, "drzava": izvor,
                "opis": "Uradni prenos v živo · " + DRZAVE.get(izvor, izvor) + " · " + jezik,
                "slika": logotip(kljuc, izvor), "jezik": jezik_koda(jezik) or jezik}
        if url:
            vnos.update(url=url, mime="application/vnd.apple.mpegurl")
        else:
            vnos.update(url=stran, stran=stran, opis="Uradna stran v živo · " + jezik)
        izid.append(vnos)
    return izid


def zvrsti_za(vrsta: str) -> list[dict]:
    """Zvrsti, ki jih ima smisel pokazati za 'glasba' ali 'radio' (novice so samo na radiu)."""
    indeks = 1 if vrsta == "glasba" else 2
    return [{"id": kljuc, "ime": v[0]} for kljuc, v in GLASBENE_ZVRSTI.items() if v[indeks]]
_TTL = 30 * 60
_TIMEOUT = 10
#: Seznam videov enega streznika PeerTube: zdrav odgovori v manj kot sekundi, na pocasnega katalog ne caka dlje.
_TIMEOUT_SEZNAM = 5
#: Streznik, ki pocasi odpove, toliko casa preskakujemo (uporabnik nanj ne caka); nato ga vprasamo v ozadju.
_PREMOR_STREZNIKA = 5 * 60
#: Ko prvi streznik odgovori z videi, imajo ostali se toliko sekund; pozni odgovori ostanejo za naslednji pogled.
_PO_PRVEM_S = 1.5


def _norm(value: Any) -> str:
    raw = unicodedata.normalize("NFKD", str(value or "").casefold())
    return re.sub(r"[^\w]+", " ", "".join(c for c in raw if not unicodedata.combining(c))).strip()


class ZakonitiViri:
    """API odjemalec z omejenim casom in mehkim neuspehom posameznega vira."""

    def __init__(self, opener=None, clock=time.time):
        self._opener = opener or urllib.request.urlopen
        self._clock = clock
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = threading.RLock()
        #: Streznik -> do kdaj ga preskakujemo, ker ni odgovoril (uporabnik nanj ne caka znova in znova).
        self._nedosegljivi: dict[str, float] = {}
        self._preverjam: set[str] = set()
        #: Napaka, na katero smo cakali vsaj toliko sekund, steje kot »streznik ne odgovarja«.
        self._pocasi_s = 3.0

    def _json(self, url: str, timeout: float = _TIMEOUT) -> Any:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        with self._lock:
            do = self._nedosegljivi.get(host)
        if do is not None:
            if self._clock() >= do:
                self._preveri_v_ozadju(host, url, timeout)
            raise OSError("streznik %s trenutno ne odgovarja" % host)
        return self._zahtevaj(url, timeout, host)

    def _zahtevaj(self, url: str, timeout: float, host: str) -> Any:
        request = urllib.request.Request(url, headers={
            "User-Agent": "SafeerOS/1.0 (+https://safeer.si)",
            "Accept": "application/json",
        })
        zacetek = time.monotonic()
        try:
            with self._opener(request, timeout=timeout) as response:
                status = getattr(response, "status", 200)
                telo = response.read(5 * 1024 * 1024 + 1) if status == 200 else b""
        except urllib.error.HTTPError:
            with self._lock:
                self._nedosegljivi.pop(host, None)      # streznik je odgovoril (z napako): ni nedosegljiv
            raise
        except OSError:
            if time.monotonic() - zacetek >= self._pocasi_s:
                with self._lock:
                    self._nedosegljivi[host] = self._clock() + _PREMOR_STREZNIKA
            raise
        with self._lock:
            self._nedosegljivi.pop(host, None)
        if status != 200:
            raise OSError("HTTP %s" % status)
        return json.loads(telo.decode("utf-8"))

    def _preveri_v_ozadju(self, host: str, url: str, timeout: float) -> None:
        """Premor streznika je potekel: vprasamo ga znova, a ne v klicu, na katerega caka uporabnik."""
        with self._lock:
            if host in self._preverjam:
                return
            self._preverjam.add(host)

        def delo() -> None:
            try:
                self._zahtevaj(url, timeout, host)      # uspeh streznik vrne v rabo, pocasen neuspeh premor podaljsa
            except Exception:  # noqa: BLE001
                pass
            finally:
                with self._lock:
                    self._preverjam.discard(host)
        threading.Thread(target=delo, name="safeer-vir-preverjanje", daemon=True).start()

    def _cached(self, key: str, fn):
        now = self._clock()
        with self._lock:
            found = self._cache.get(key)
            if found and now - found[0] < _TTL:
                return found[1]
        try:
            value = fn()
        except Exception:
            return found[1] if found else []
        with self._lock:
            self._cache[key] = (now, value)
        return value

    def _video_hosts(self, configured: list[str]) -> list[str]:
        # Lastnik, 11. 10. 2026: PeerTube ni vgrajen vir - samo strezniki PeerTube, ki jih je dodal uporabnik.
        hosts: list[str] = []
        candidates = []
        for value in configured:
            try:
                parsed = urllib.parse.urlsplit(value if "://" in value else "https://" + value)
                host = (parsed.hostname or "").lower()
                if parsed.scheme == "https" and host and host not in hosts and host not in PEERTUBE_BLOKIRANI:
                    candidates.append(host)
            except ValueError:
                pass
        candidates = list(dict.fromkeys(candidates))
        with ThreadPoolExecutor(max_workers=min(12, len(candidates) or 1)) as pool:
            for host, valid in zip(candidates, pool.map(lambda candidate: self._cached(
                    "pt-config:" + candidate, lambda: self._valid_peertube(candidate)), candidates)):
                if valid:
                    hosts.append(host)
        return hosts

    def _valid_peertube(self, host: str) -> bool:
        try:
            config = self._json("https://%s/api/v1/config" % host)
            return isinstance(config, dict) and isinstance(config.get("instance"), dict)
        except Exception:
            return False

    def _peertube_video(self, row: dict, host: str, category: str) -> dict | None:
        if not isinstance(row, dict) or row.get("nsfw"):
            return None
        if str(host or "").lower() in PEERTUBE_BLOKIRANI:
            return None
        title = str(row.get("name") or "").strip()
        if _PEERTUBE_SUMLJIVO.search(title):
            return None
        video_id = str(row.get("uuid") or "")
        if not title or not video_id:
            return None
        channel = row.get("channel") if isinstance(row.get("channel"), dict) else {}
        account = row.get("account") if isinstance(row.get("account"), dict) else {}
        image = row.get("thumbnailPath") or row.get("previewPath") or ""
        if image.startswith("/"):
            image = "https://%s%s" % (host, image)
        live = bool(row.get("isLive"))
        duration = int(row.get("duration") or 0)
        # Film je le, kar avtor na PeerTube uvrsti med filme (kategorija 2 "Films") in je dolgo; dolga
        # predavanja, sestanki in podkasti so video - prej so zasuli polico Filmi.
        kategorija = row.get("category") if isinstance(row.get("category"), dict) else {}
        je_film = str(kategorija.get("id") or "") == "2" and duration > 40 * 60
        kind = "tv-v-zivo" if live else ("film" if je_film else "video")
        return {
            "id": "peertube:" + video_id, "naslov": title, "vrsta": kind,
            "url": "https://%s/videos/watch/%s" % (host, video_id),
            "slika": image, "opis": str(row.get("description") or "")[:600],
            "izvajalec": channel.get("displayName") or account.get("displayName") or host,
            "trajanje": duration, "v_zivo": live, "skupina": category,
            "vir": "PeerTube · " + host, "streznik": host,
            "jezik": jezik_koda((row.get("language") or {}).get("id") if isinstance(row.get("language"), dict) else row.get("language")),
            "peertube_uuid": video_id,
        }

    def _peer_rows(self, host: str, endpoint: str, category: str) -> list[dict]:
        key = "pt:%s:%s" % (host, endpoint)
        def fetch():
            data = self._json("https://%s%s" % (host, endpoint), _TIMEOUT_SEZNAM)
            rows = data.get("data", []) if isinstance(data, dict) else []
            return [item for row in rows if (item := self._peertube_video(row, host, category))]
        return self._cached(key, fetch)

    def _search_video(self, query: str, hosts: list[str], jezik: str = "") -> list[dict]:
        if not query:
            return []
        iskanje = {"search": query, "sort": "-match", "nsfw": "false", "count": 30}
        if jezik:
            # PeerTube vrne videe v tem jeziku IN videe s podnapisi v njem; tocno izbere katalog (os_media).
            iskanje["languageOneOf"] = jezik
        encoded = urllib.parse.urlencode(iskanje)
        if not hosts:
            # Lastnik, 11. 10. 2026: PeerTube ni vgrajen - brez streznikov, ki jih je dodal uporabnik, ga ne iscemo
            # (tudi ne prek globalnega indeksa sepiasearch.org).
            return []
        def fetch():
            result = []
            def server_search(host):
                path = "/api/v1/search/videos?" + urllib.parse.urlencode(dict(iskanje, count=20))
                return self._peer_rows(host, path, "Iskanje")
            with ThreadPoolExecutor(max_workers=min(8, len(hosts))) as pool:
                futures = [pool.submit(server_search, host) for host in hosts]
                try:
                    for future in as_completed(futures, timeout=_TIMEOUT):
                        try:
                            result.extend(future.result() or [])
                        except Exception:
                            pass
                except FuturesTimeout:
                    pass
            terms = [word for word in _norm(query).split() if len(word) > 1]
            if terms:
                result = [item for item in result if all(term in _norm(" ".join((item["naslov"], item["izvajalec"], item["opis"]))) for term in terms)]
            return result[:40]
        return self._cached("pt-search:" + query.casefold() + ("|" + jezik if jezik else ""), fetch)

    def videos(self, query: str = "", configured_hosts: list[str] | None = None, jezik: str = "") -> list[dict]:
        """`jezik` (koda ISO 639-1): izbran jezik vsebine - strezniki ze sami izberejo videe v njem."""
        jezik = jezik if re.fullmatch(r"[a-z]{2}", jezik or "") else ""
        hosts = self._video_hosts(configured_hosts or [])
        if query:
            return self._search_video(query, hosts, jezik)
        result = []
        # Izbran jezik: izbor je ozji, zato vprasamo za vec zadetkov.
        stevilo = "40&languageOneOf=" + jezik if jezik else "18"
        routes = (("trending", "/api/v1/videos?sort=-trending&count=%s&nsfw=false&isLocal=true" % stevilo),
                  ("Najbolj gledani", "/api/v1/videos?sort=-views&count=%s&nsfw=false&isLocal=true" % stevilo),
                  ("Nedavno", "/api/v1/videos?sort=-publishedAt&count=%s&nsfw=false&isLocal=true" % stevilo))
        jobs = [(host, label, path) for label, path in routes for host in hosts]
        pool = ThreadPoolExecutor(max_workers=min(15, len(jobs)))
        futures = [pool.submit(self._peer_rows, host, path, label) for host, label, path in jobs]
        # Na zadnji, pocasni streznik katalog ne caka: po prvem odgovoru z videi imajo ostali se _PO_PRVEM_S. Kar pride
        # pozneje, ostane v predpomnilniku za naslednji pogled. Dokler ni odgovoril nihce, cakamo vse (do roka zahteve).
        cakajo, rok, konec = set(futures), None, time.monotonic() + _TIMEOUT_SEZNAM + 1
        while cakajo:
            do = konec if rok is None else min(konec, rok)
            koncani, cakajo = _pocakaj_na(cakajo, timeout=max(0.0, do - time.monotonic()), return_when=FIRST_COMPLETED)
            if not koncani:
                break
            if rok is None and any(f.exception() is None and f.result() for f in koncani):
                rok = time.monotonic() + _PO_PRVEM_S
        pool.shutdown(wait=False)
        for future in futures:
            if not future.done():
                continue
            try: result.extend(future.result())
            except Exception: pass
        unique = {}
        for item in result:
            unique.setdefault(item["id"], item)
        return list(unique.values())

    def resolve_video(self, item: dict, configured_hosts: list[str] | None = None) -> dict | None:
        host = item.get("streznik", "")
        hosts = list(dict.fromkeys(([host] if host else []) + self._video_hosts(configured_hosts or [])))
        video_id = item.get("peertube_uuid", "")
        for server in hosts:
            try:
                data = self._json("https://%s/api/v1/videos/%s" % (server, urllib.parse.quote(video_id, safe="")))
                live = bool(data.get("isLive"))
                playlists = data.get("streamingPlaylists") or []
                for playlist in playlists:
                    url = playlist.get("playlistUrl")
                    if url and urllib.parse.urlsplit(url).scheme == "https":
                        return dict(item, url=url, v_zivo=live, mime="application/vnd.apple.mpegurl")
                files = []
                for file in data.get("files", []) + [f for p in playlists for f in p.get("files", [])]:
                    url = file.get("fileUrl")
                    height = int((file.get("resolution") or {}).get("id") or 0)
                    if url and urllib.parse.urlsplit(url).scheme == "https" and 0 < height <= 1080:
                        files.append((height, url))
                if files:
                    height, url = max(files)
                    return dict(item, url=url, locljivost=height, kakovost="%dp" % height, mime="video/mp4")
                for playlist in playlists:
                    url = playlist.get("playlistUrl")
                    if url and urllib.parse.urlsplit(url).scheme == "https":
                        return dict(item, url=url, mime="application/vnd.apple.mpegurl")
            except Exception:
                continue
        return None

    def _jamendo(self, path: str, params: dict) -> list[dict]:
        query = dict(params, client_id=JAMENDO_CLIENT_ID, format="json")
        url = "https://api.jamendo.com/v3.0/%s?%s" % (path, urllib.parse.urlencode(query))
        def fetch():
            for attempt in range(2):
                try:
                    data = self._json(url)
                    rows = [self._track(row) for row in data.get("results", [])
                            if row.get("audio", "").startswith("https://")]
                    if rows or attempt:
                        return rows
                except Exception:
                    if attempt:
                        raise
                time.sleep(0.3)
            return []
        return self._cached("jam:" + path + ":" + urllib.parse.urlencode(params), fetch)

    @staticmethod
    def _track(row: dict) -> dict:
        vnos = {"id": "jamendo:" + str(row.get("id")), "naslov": row.get("name", ""), "vrsta": "glasba",
                "izvajalec": row.get("artist_name", ""), "url": row.get("audio", ""),
                "slika": row.get("image") or row.get("album_image", ""),
                "zunanja_povezava": row.get("shorturl") or row.get("shareurl", ""),
                "vir": "Jamendo", "opis": "Jamendo · " + str(row.get("artist_name", ""))}
        # Jezik besedila skladbe (musicinfo); instrumentalne ga nimajo.
        info = row.get("musicinfo") if isinstance(row.get("musicinfo"), dict) else {}
        jezik = str(info.get("lang") or "")
        if re.fullmatch(r"[a-z]{2}", jezik):
            vnos["jezik"] = jezik
        return vnos

    def music(self, query: str = "", zvrst: str = "", jezik: str = "") -> list[dict]:
        """`jezik` (koda ISO 639-1): izbran jezik vsebine - Jamendo izbere skladbe z besedilom v njem."""
        oznaka = GLASBENE_ZVRSTI.get(zvrst, ("", "", ""))[1]
        if zvrst and not oznaka:
            return []
        dodatno = {"include": "musicinfo"}
        if re.fullmatch(r"[a-z]{2}", jezik or ""):
            dodatno["lang"] = jezik
        if oznaka and not query:
            # Jamendo pri nekaterih oznakah obcasno vrne prazno z `tags`; takrat poskusimo `fuzzytags`.
            zadetki = self._jamendo("tracks/", dict({"order": "popularity_total", "limit": 48, "audioformat": "mp32",
                                                     "tags": oznaka}, **dodatno))
            return zadetki or self._jamendo("tracks/", dict({"order": "popularity_total", "limit": 48, "audioformat": "mp32",
                                                              "fuzzytags": oznaka}, **dodatno))
        if not query:
            return self._jamendo("tracks/", dict({"order": "popularity_total", "limit": 36, "audioformat": "mp32"}, **dodatno))
        def fetch():
            artists = self._json("https://api.jamendo.com/v3.0/artists/?" + urllib.parse.urlencode({
                "namesearch": query, "order": "popularity_total", "limit": 8,
                "client_id": JAMENDO_CLIENT_ID, "format": "json"}))
            selected = artists.get("results", [])[:6]
            with ThreadPoolExecutor(max_workers=max(1, len(selected))) as pool:
                return [track for rows in pool.map(lambda artist: self._jamendo("tracks/", dict({
                    "artist_id": artist.get("id"), "order": "popularity_total", "limit": 8,
                    "audioformat": "mp32"}, **dodatno)), selected) for track in rows]
        return self._cached("jam-search:" + query.casefold() + ("|" + dodatno["lang"] if "lang" in dodatno else ""), fetch)

    def _radio_browser(self, pot: str, params: dict) -> Any:
        # Radio Browser ima vec zrcal; ce eno ne odgovori (11. 10. 2026: de1 vracal 503), poskusimo naslednje.
        napaka = None
        for streznik in ("de1", "de2", "fi1", "nl1", "at1"):
            try:
                return self._json("https://%s.api.radio-browser.info/json/%s?%s"
                                  % (streznik, pot, urllib.parse.urlencode(params)), 4)
            except Exception as e:  # noqa: BLE001
                napaka = e
        raise napaka or OSError("Radio Browser")

    def radio_drzave(self) -> list[dict]:
        """Drzave z delujocimi postajami v Radio Browserju ({"id": "SI", "postaj": 120}), najvec postaj najprej.
        Drzave z manj kot 3 postajami izpustimo: izbira, ki da prazen ali skoraj prazen seznam, uporabniku ne koristi."""
        def fetch():
            rows = self._radio_browser("countries", {"order": "stationcount", "reverse": "true", "hidebroken": "true"})
            izid, videne = [], set()
            for row in rows if isinstance(rows, list) else []:
                koda = str((row or {}).get("iso_3166_1") or "").upper() if isinstance(row, dict) else ""
                try:
                    stevilo = int(row.get("stationcount") or 0)
                except (TypeError, ValueError):
                    stevilo = 0
                if re.fullmatch(r"[A-Z]{2}", koda) and stevilo >= 3 and koda not in videne:
                    videne.add(koda); izid.append({"id": koda, "postaj": stevilo})
            return izid
        return self._cached("radio-drzave", fetch)

    def radio(self, query: str = "", zvrst: str = "", drzava: str = "") -> list[dict]:
        """`drzava` (ISO 3166-1 alpha-2, npr. "SI"): samo postaje iz te drzave (lastnik, 15. 10. 2026)."""
        ime, _, oznaka = GLASBENE_ZVRSTI.get(zvrst, ("", "", ""))
        if zvrst and not oznaka:
            return []
        drzava = (drzava or "").upper()
        if not re.fullmatch(r"[A-Z]{2}", drzava):
            drzava = ""
        if oznaka:
            tags = [(oznaka, ime)]
        elif drzava:
            # Izbrana drzava: vse iskanje in vse skupine samo v njej; najprej najbolj poslusane, nato po zvrsteh.
            tags = ([("ime:" + query, "Iskanje"), (query, "Iskanje")] if query else
                    [("", "Najbolj poslušane")] + [(tag, tag.title()) for tag in RADIO_TAGS])
        else:
            # Iskanje: najprej postaje s tem imenom v Sloveniji (»rock radio« = Rock Radio iz Slovenije), nato po svetu,
            # nato postaje s to oznako (zvrstjo). Prej je iskalo samo po oznaki - »rock radio« ni nasel nicesar.
            tags = ([("ime:SI:" + query, "Iskanje"), ("ime:" + query, "Iskanje"), (query, "Iskanje")] if query else
                    [("SI", "Slovenija")] + [(tag, tag.title()) for tag in RADIO_TAGS] + [("", "Najbolj poslušane")])
        def load_tag(entry):
            value, label = entry
            params = {"order": "clickcount", "reverse": "true", "hidebroken": "true",
                      "limit": "60" if (oznaka or (drzava and not value)) else "30", "is_https": "true"}
            if value == "SI": params["countrycode"] = "SI"
            elif value.startswith("ime:SI:"): params["name"] = value[len("ime:SI:"):]; params["countrycode"] = "SI"
            elif value.startswith("ime:"): params["name"] = value[len("ime:"):]
            elif value: params["tag"] = value
            if drzava:
                params["countrycode"] = drzava
            key = "radio:" + label + ":" + value + (":" + drzava if drzava else "")
            def fetch(params=params, label=label):
                rows = self._radio_browser("stations/search", params)
                return [self._station(row, label) for row in rows if isinstance(row, dict)]
            return self._cached(key, fetch)
        with ThreadPoolExecutor(max_workers=len(tags)) as pool:
            result = [station for rows in pool.map(load_tag, tags) for station in rows]
        # TuneIn ne pove drzave postaje: pri izbrani drzavi bi pomesal postaje od drugod.
        if not zvrst and not drzava:
            # TuneIn (neuradni OPML vmesnik; uporabo je izrecno dovolil lastnik izdelka): pri iskanju zadetki,
            # sicer postaje v blizini. Ce vmesnik ne odgovori, se tiho izpusti.
            try:
                if query:
                    # Kot pri spletnem iskalniku: najprej domace postaje (TuneIn »v blizini« po IP naslovu), ki se z
                    # iskanim ujemajo - »rock radio« pri lastniku najprej Rock Radio Si in Radio 1 Rock, ne nemske.
                    besede = [b for b in _norm(query).split() if len(b) > 1]
                    blizu = [p for p in self.tunein("") if besede and all(b in _norm(p.get("naslov", "")) for b in besede)]
                    fraza = _norm(query).strip()
                    blizu.sort(key=lambda p: 0 if fraza in _norm(p.get("naslov", "")) else 1)
                    result = blizu + result
                result += self.tunein(query)
            except Exception:
                pass
        seen = set()
        imena = set()
        out = []
        for station in result:
            if not station or station["id"] in seen:
                continue
            ime = _norm(station.get("naslov", ""))
            if station.get("tunein_id") and ime in imena:
                continue  # ista postaja je ze iz Radio Browserja
            seen.add(station["id"]); imena.add(ime); out.append(station)
        return out

    TUNEIN = "https://opml.radiotime.com"

    def _tunein_vnos(self, row: dict, skupina: str) -> dict | None:
        if not isinstance(row, dict) or row.get("type") != "audio" or row.get("item") != "station":
            return None
        gid = str(row.get("guide_id") or "")
        ime = str(row.get("text") or "").strip()
        if not re.fullmatch(r"s\d{1,12}", gid) or not ime:
            return None
        slika = str(row.get("image") or "")
        if slika.startswith("http://"):
            slika = "https://" + slika[len("http://"):]
        return {"id": "tunein:" + gid, "naslov": ime[:200], "vrsta": "radio",
                "url": "https://tunein.com/radio/" + gid + "/", "tunein_id": gid,
                "slika": slika, "izvajalec": str(row.get("subtext") or "")[:160],
                "opis": "TuneIn · " + str(row.get("subtext") or "")[:300], "skupina": skupina,
                "vir": "TuneIn", "vir_id": "tunein"}

    def tunein(self, query: str = "") -> list[dict]:
        """Postaje TuneIn: pri iskanju zadetki, sicer postaje v blizini (po IP naslovu)."""
        if query:
            url = self.TUNEIN + "/Search.ashx?" + urllib.parse.urlencode(
                {"query": query, "render": "json", "formats": "mp3,aac,ogg,hls"})
            kljuc, skupina = "tunein:isci:" + _norm(query), "TuneIn"
        else:
            url = self.TUNEIN + "/Browse.ashx?" + urllib.parse.urlencode({"c": "local", "render": "json"})
            kljuc, skupina = "tunein:blizu", "TuneIn · v bližini"

        def fetch():
            vrste = []
            def zberi(elementi):
                for el in elementi or []:
                    if isinstance(el, dict):
                        if el.get("children"):
                            zberi(el["children"])
                        else:
                            vrste.append(el)
            zberi((self._json(url) or {}).get("body"))
            # V blizini cel seznam (po abecedi; Rock Radio Si je bil pri lastniku 80. in ga omejitev 40 ni pustila).
            return [v for v in (self._tunein_vnos(r, skupina) for r in vrste) if v][:40 if query else 150]
        return self._cached(kljuc, fetch)

    # ------------------------------------------------------------------ tokovi postaje
    # Lastnik, 11. 10. 2026: postaja z vec programi (Rock Radio: Best Ballads, Hard & Heavy, Classics) - uporabnik
    # izbere program kot na strani postaje. Tokove najdemo na domaci strani postaje (povezave na tokove), ime toka pove
    # streznik sam (glava icy-name). Nic ni vpisano na roko za posamezno postajo.
    _TOK_VZOREC = re.compile(r"""https://[^\s"'<>\\]{6,400}""")
    _TOK_NAMIG = re.compile(r"stream|live|icecast|shoutcast|proxy|\.mp3|\.aac|\.m3u8|\.ogg|/radio|:8\d{3}/", re.I)
    _TOK_NE = re.compile(r"\.(?:jpe?g|png|gif|webp|svg|css|js|ico|woff2?|ttf|html?)(?:[?#]|$)|facebook|instagram|twitter|x\.com|youtube|google|datocms", re.I)

    def domaca_stran_postaje(self, item: dict) -> str:
        stran = str(item.get("domaca_stran") or "")
        gid = str(item.get("tunein_id") or "")
        if not stran and re.fullmatch(r"s\d{1,12}", gid):
            try:
                opis = self._json(self.TUNEIN + "/Describe.ashx?" + urllib.parse.urlencode({"id": gid, "render": "json"}), 6)
                stran = str(((opis or {}).get("body") or [{}])[0].get("url") or "")
            except Exception:
                stran = ""
        if stran.startswith("http://"):
            stran = "https://" + stran[len("http://"):]
        return stran if stran.startswith("https://") else ""

    def _glava_toka(self, url: str) -> dict | None:
        """Ali je naslov zvocni tok: preberemo samo glavo (icy-name, vrsta, bitna hitrost), telesa ne."""
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        if not host or re.fullmatch(r"[\d.]+|\[?[0-9a-f]*:[0-9a-f:]+\]?", host) or host in ("localhost",) or host.endswith(".local"):
            return None
        request = urllib.request.Request(url, headers={"User-Agent": "SafeerOS/1.0 (+https://safeer.si)", "Icy-MetaData": "1"})
        try:
            with self._opener(request, timeout=5) as response:
                glava = response.headers
                vrsta = str(glava.get("Content-Type") or "").lower()
                if not (vrsta.startswith("audio/") or "mpegurl" in vrsta or "ogg" in vrsta):
                    return None
                return {"url": url, "ime": str(glava.get("icy-name") or "").strip()[:120],
                        "bitrate": int(re.sub(r"\D", "", str(glava.get("icy-br") or "")) or 0),
                        "mime": "application/vnd.apple.mpegurl" if "mpegurl" in vrsta else vrsta.split(";")[0]}
        except Exception:
            return None

    def tokovi_postaje(self, item: dict) -> list[dict]:
        """Vsi tokovi (programi) postaje z njene domace strani: [{naslov, url, bitrate, mime}]. Prazno, ce jih ni vec."""
        stran = self.domaca_stran_postaje(item)
        if not stran:
            return []

        def fetch():
            request = urllib.request.Request(stran, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) SafeerOS/1.0",
                                                             "Accept": "text/html"})
            with self._opener(request, timeout=8) as response:
                html = response.read(1024 * 1024).decode("utf-8", "replace")
            kandidati = []
            for url in self._TOK_VZOREC.findall(html.replace("\\/", "/").replace("&amp;", "&")):
                url = url.rstrip(").,;")
                if self._TOK_NAMIG.search(url) and not self._TOK_NE.search(url) and url not in kandidati:
                    kandidati.append(url)
            kandidati = kandidati[:12]
            if not kandidati:
                return []
            with ThreadPoolExecutor(max_workers=min(6, len(kandidati))) as pool:
                glave = [g for g in pool.map(self._glava_toka, kandidati) if g]
            # Tok brez imena (npr. HLS istega glavnega programa) izpustimo, ce imajo drugi tokovi imena.
            if sum(1 for g in glave if g["ime"]) >= 2:
                glave = [g for g in glave if g["ime"]]
            tokovi, imena = [], set()
            for g in glave:
                ime = g["ime"] or str(item.get("naslov") or "")
                if ime.isupper():
                    ime = re.sub(r"\bHq\b", "HQ", ime.title())
                kljuc = _norm(ime)
                if kljuc in imena:
                    continue                 # isti program v drugi kakovosti (HLS, nizja hitrost): obdrzimo prvega
                imena.add(kljuc)
                tokovi.append({"naslov": ime, "url": g["url"], "bitrate": g["bitrate"], "mime": g["mime"]})
            return tokovi if len(tokovi) > 1 else []
        return self._cached("tokovi:" + stran, fetch)

    def resolve_tunein(self, item: dict) -> dict | None:
        gid = str(item.get("tunein_id") or "")
        if not re.fullmatch(r"s\d{1,12}", gid):
            return None
        data = self._json(self.TUNEIN + "/Tune.ashx?" + urllib.parse.urlencode(
            {"id": gid, "render": "json", "formats": "mp3,aac,ogg,hls"}))
        for row in (data or {}).get("body") or []:
            url = str((row or {}).get("url") or "")
            if (row or {}).get("element") == "audio" and url.startswith(("https://", "http://")):
                mime = "application/vnd.apple.mpegurl" if ".m3u8" in url.lower() else ""
                return dict(item, url=url, mime=mime, bitrate=int(row.get("bitrate") or 0))
        return None

    @staticmethod
    def _station(row: dict, group: str) -> dict | None:
        url = row.get("url_resolved") or ""
        if (not row.get("stationuuid") or not row.get("name") or not url.startswith("https://")
                or str(row.get("lastcheckok", "1")) == "0"):
            return None
        try: bitrate = int(row.get("bitrate") or 0)
        except (TypeError, ValueError): bitrate = 0
        codec = str(row.get("codec") or "").upper()
        return {"id": "radio:" + row["stationuuid"], "naslov": row["name"].strip(), "vrsta": "radio",
                "url": url, "slika": row.get("favicon") or "", "izvajalec": row.get("country") or "",
                "opis": " · ".join(part for part in (row.get("country"), codec, (str(bitrate) + " kb/s") if bitrate else "") if part),
                "codec": codec, "bitrate": bitrate, "drzava": row.get("countrycode", ""),
                "zanri": row.get("tags", ""), "skupina": group, "vir": "Radio Browser",
                "jezik": jezik_koda(row.get("languagecodes") or row.get("language"))}

    def _archive_datoteka(self, ident: str) -> tuple[str, int] | None:
        """Neposredna datoteka MP4 (H.264) izdelka; brez nje filma ne pokazemo."""
        data = self._json("https://archive.org/metadata/%s" % urllib.parse.quote(ident, safe=""))
        licenca = str((data.get("metadata") or {}).get("licenseurl") or "")
        if "publicdomain" not in licenca:
            return None
        kandidati = []
        for f in data.get("files") or []:
            ime = str(f.get("name") or "")
            if not ime.lower().endswith(".mp4"):
                continue
            try:
                visina = int(f.get("height") or 0)
            except (TypeError, ValueError):
                visina = 0
            kandidati.append((min(visina, 1080) if visina else 240, ime))
        if not kandidati:
            return None
        visina, ime = max(kandidati)
        return "https://archive.org/download/%s/%s" % (urllib.parse.quote(ident, safe=""), urllib.parse.quote(ime)), visina

    def resolve_archive(self, item: dict) -> dict | None:
        datoteka = self._archive_datoteka(str(item.get("archive_id") or ""))
        if not datoteka:
            return None
        url, visina = datoteka
        return dict(item, url=url, mime="video/mp4", locljivost=visina, kakovost="%dp" % visina,
                    stran="https://archive.org/details/" + urllib.parse.quote(str(item.get("archive_id")), safe=""))

    @staticmethod
    def _archive_jezik(jezik: str) -> str:
        """Pogoj za polje `language` v Internet Archive (npr. en -> "English" OR "eng"); "" = brez pogoja."""
        # Kode in angleska imena (Internet Archive), ne slovenska (»anglescina«).
        imena = sorted(k for k, v in _JEZIKI.items() if v == jezik and k.isascii() and len(k) > 2 and not k.endswith("scina"))
        return " AND language:(%s)" % " OR ".join('"%s"' % ime for ime in imena) if imena else ""

    def javna_last(self, query: str = "", jezik: str = "", zvrst: str = "") -> list[dict]:
        """Filmi v javni lasti (Internet Archive); tocno datoteko MP4 poiscemo ob kliku (resolve_archive).
        `jezik` (ISO 639-1) in `zvrst` (id filmske zvrsti) izbere ze Internet Archive: vecina filmov v javni lasti nima
        jezika v podatkih, zato izbira jezika po prejetih zadetkih ni pustila skoraj nicesar (»V tem jeziku tukaj ni
        vsebine«, lastnik 10. 10. 2026), zvrst pa se ni upostevala."""
        iskanje = re.sub(r"[^\w\s-]", " ", query or "", flags=re.UNICODE).strip()
        jezik = jezik if re.fullmatch(r"[a-z]{2}", jezik or "") else ""
        predmet = ARCHIVE_ZVRSTI.get(str(zvrst or ""), "")
        q = (ARCHIVE_PD_QUERY + (" AND title:(%s)" % iskanje if iskanje else "") + (self._archive_jezik(jezik) if jezik else "")
             + (' AND subject:("%s")' % predmet if predmet else ""))
        url = "https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(
            [("q", q), ("fl[]", "identifier"), ("fl[]", "title"), ("fl[]", "year"), ("fl[]", "description"), ("fl[]", "format"), ("fl[]", "language"),
             ("sort[]", "downloads desc"), ("rows", "40"), ("output", "json")])

        def fetch():
            vrstice = ((self._json(url) or {}).get("response") or {}).get("docs") or []
            out = []
            for v in vrstice:
                if not isinstance(v, dict) or not v.get("identifier") or not v.get("title"):
                    continue
                if _ARCHIVE_SUMLJIVO.search(str(v.get("title")) + " " + str(v.get("identifier"))):
                    continue
                formati = v.get("format") if isinstance(v.get("format"), list) else [str(v.get("format") or "")]
                # Samo izdelki z videom MP4 (H.264 / MPEG4) - te predvajalnik zna predvajati.
                if not any(f in ("h.264", "512Kb MPEG4", "MPEG4", "h.264 IA") for f in formati):
                    continue
                ident = str(v["identifier"])
                try:
                    leto = int(str(v.get("year") or "0")[:4])
                except ValueError:
                    leto = 0
                opis = v.get("description")
                opis = " ".join(opis) if isinstance(opis, list) else str(opis or "")
                out.append({
                    "id": "archive:" + ident, "naslov": str(v["title"])[:200], "vrsta": "film",
                    "url": "https://archive.org/details/" + urllib.parse.quote(ident, safe=""),
                    "archive_id": ident, "leto": leto,
                    "slika": "https://archive.org/services/img/" + urllib.parse.quote(ident, safe=""),
                    "opis": re.sub(r"<[^>]+>", " ", opis)[:600],
                    "vir": "Internet Archive · javna last", "vir_id": "archive-javna-last", "skupina": "Javna last",
                    # Internet Archive je izbral po jeziku: zadetek brez jezika v podatkih je v izbranem jeziku.
                    "jezik": jezik_koda(v.get("language")) or jezik,
                })
            return out

        return self._cached("archive-pd:" + iskanje.casefold() + (("|" + jezik) if jezik else "") + (("|z" + predmet) if predmet else ""), fetch)

    def get(self, query: str = "", configured_hosts: list[str] | None = None, zvrst: str = "", jezik: str = "",
            filmska_zvrst: str = "", vrsta: str = "", drzava_radia: str = "") -> list[dict]:
        """`jezik`: izbran jezik vsebine. PeerTube in Jamendo izbereta ze sama; pri radiu in javni lasti jezik pove
        vnos. Tocno izbiro (in vnose brez znanega jezika) opravi katalog."""
        if zvrst:
            # Glasbena zvrst velja samo za glasbo in radio (video nima teh zvrsti).
            tasks = ((self.music, (query, zvrst, jezik)), (self.radio, (query, zvrst, drzava_radia)))
        else:
            # Lastnik, 11. 10. 2026: Internet Archive (filmi v javni lasti) ni vgrajen vir.
            tasks = ((self.videos, (query, configured_hosts, jezik)), (self.music, (query, "", jezik)), (self.radio, (query, "", drzava_radia)))
        # Samo viri, ki dajo to vrsto (lastnik 14. 10. 2026: cakanje na filme - prej je katalog filmov cakal tudi na
        # radijske postaje, 1,7 s na prenosniku, ceprav jih katalog nato izloci).
        potrebni = {"film": ("videos",), "serija": ("videos",), "video": ("videos",), "glasba": ("music",),
                    "radio": ("radio",), "tv-v-zivo": ()}.get(vrsta)
        if potrebni is not None:
            tasks = tuple(t for t in tasks if t[0].__name__ in potrebni)
            if not tasks:
                return []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(fn, *args) for fn, args in tasks]
            results = []
            for future in futures:
                try: results.extend(future.result())
                except Exception: continue
            return results
