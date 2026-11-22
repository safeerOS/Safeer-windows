"""Prenos Twitch v zivo brez vsiljenih oglasov: lokalni seznam predvajanja HLS za domaci predvajalnik (GStreamer).

Lastnik 17. 10. 2026: Twitch gledamo v nasem predvajalniku, Safeer Scit pa varuje pred vsiljivimi oglasi. Twitch oglase
vstavi kar v seznam predvajanja HLS (»stitched ads«): segmenti z naslovom »Amazon|...« pod oznako EXT-X-DATERANGE
CLASS="twitch-stitched-ad". Izmerjeno 17. 10. 2026: isti kanal je v istem trenutku dal predoglas igralcu »site«,
igralci »embed«, »popout«, »autoplay« in »site« na platformi android pa ne - oglas je nakljucen po seji.

Zato predvajalnik ne bere seznama Twitcha neposredno, ampak nasega (http://127.0.0.1:<vrata>/twitch/<zeton>.m3u8):
- dovoljeni segmenti glavnega toka gredo naprej nespremenjeni (segmenti so na CDN Twitcha, skozi nas gre samo seznam),
- ko glavni tok predvaja oglas, vzamemo iste trenutke (EXT-X-PROGRAM-DATE-TIME) iz rezervnega toka z drugim tipom
  igralca, ki oglasa nima; ob preklopu oznaka EXT-X-DISCONTINUITY (predvajalnik ponastavi dekodirnik, zvok tece dalje),
- ce oglas predvaja tudi zadnja rezerva, oglasnih segmentov ne damo naprej: slika obstane, dokler oglas ne mine.

Zasebnost: seznami predvajanja nosijo IP uporabnika in zeton seje - nic od tega ne gre v dnevnik; streznik poslusa
samo na 127.0.0.1, naslov ima nakljucen zeton, seja po 10 minutah brez branja izgine.
"""
from __future__ import annotations

import datetime
import http.server
import re
import secrets
import socketserver
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

from core import os_deskriptorji

#: Toliko segmentov (po 2 s) je v nasem seznamu - predvajalnik zacne 3 segmente pred koncem.
OKNO = 12
#: Seja, ki je predvajalnik 10 minut ne bere, se zapre (uporabnik je zaprl predvajalnik ali izbral drugo).
NEAKTIVNA_S = 600.0
#: Najvec hkratnih sej (vsak nov prenos jo odpre; stare ostanejo le do konca NEAKTIVNA_S).
NAJVEC_SEJ = 4
#: Seznam Twitcha vprasamo najvec enkrat na sekundo, tudi ce ga predvajalnik bere pogosteje.
OSVEZI_S = 1.0
#: Razredi EXT-X-DATERANGE, ki oznacujejo vstavljen oglas.
RAZREDI_OGLASOV = ("twitch-stitched-ad", "stitched-ad", "twitch-ad", "twitch-ads")
_GOSTITELJI = (".ttvnw.net", ".twitch.tv", ".cloudfront.net", ".live-video.net", ".jtvnw.net")


def _cas(besedilo: str) -> Optional[float]:
    """ISO 8601 (EXT-X-PROGRAM-DATE-TIME, START-DATE) -> sekunde od epohe; neveljavno -> None."""
    s = str(besedilo or "").strip()
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _lastnosti(vrstica: str) -> dict:
    """Atributi oznake HLS (KLJUC=vrednost ali KLJUC="vrednost, z vejico")."""
    izid = {}
    for m in re.finditer(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', vrstica.split(":", 1)[1] if ":" in vrstica else ""):
        izid[m.group(1)] = m.group(2).strip('"')
    return izid


def razcleni(besedilo: str, osnova: str = "") -> dict:
    """Seznam predvajanja (media playlist) -> {"cilj": s, "zaporedje": n, "konec": bool, "segmenti": [...]}.

    Segment: {"uri", "trajanje", "naslov", "pdt" (sekunde ali None), "oglas": bool}. Oglas je segment, ki ga Twitch
    oznaci z naslovom (»Amazon|...«, »ad...«) ali ki lezi v intervalu EXT-X-DATERANGE z razredom oglasa."""
    cilj, zaporedje, konec = 2.0, 0, False
    oglasni: list[tuple[float, float]] = []
    segmenti: list[dict] = []
    trajanje, naslov, pdt = None, "", None
    for surova in str(besedilo or "").splitlines():
        v = surova.strip()
        if not v:
            continue
        if v.startswith("#EXT-X-TARGETDURATION:"):
            try:
                cilj = float(v.split(":", 1)[1])
            except ValueError:
                pass
        elif v.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            try:
                zaporedje = int(v.split(":", 1)[1])
            except ValueError:
                pass
        elif v.startswith("#EXT-X-ENDLIST"):
            konec = True
        elif v.startswith("#EXT-X-DATERANGE:"):
            a = _lastnosti(v)
            razred = a.get("CLASS", "").lower()
            if razred in RAZREDI_OGLASOV or a.get("ID", "").lower().startswith("stitched-ad"):
                zacetek = _cas(a.get("START-DATE", ""))
                if zacetek is not None:
                    try:
                        dolzina = float(a.get("DURATION") or a.get("PLANNED-DURATION") or 0)
                    except ValueError:
                        dolzina = 0.0
                    konec_oglasa = _cas(a.get("END-DATE", "")) or (zacetek + dolzina if dolzina > 0 else zacetek + 30.0)
                    oglasni.append((zacetek, konec_oglasa))
        elif v.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
            pdt = _cas(v.split(":", 1)[1])
        elif v.startswith("#EXTINF:"):
            dolzina, _, ostalo = v[len("#EXTINF:"):].partition(",")
            try:
                trajanje = float(dolzina)
            except ValueError:
                trajanje = 2.0
            naslov = ostalo.strip()
        elif not v.startswith("#") and trajanje is not None:
            segmenti.append({"uri": urllib.parse.urljoin(osnova, v) if osnova else v, "trajanje": trajanje,
                             "naslov": naslov, "pdt": pdt, "oglas": False})
            trajanje, naslov, pdt = None, "", None
    for s in segmenti:
        nizko = s["naslov"].lower()
        s["oglas"] = ("amazon" in nizko or nizko.startswith(("ad", "stitched"))
                      or (s["pdt"] is not None and any(z <= s["pdt"] + 0.01 < k for z, k in oglasni)))
    return {"cilj": cilj, "zaporedje": zaporedje, "konec": konec, "segmenti": segmenti}


def je_oglas(besedilo: str) -> bool:
    """Ali seznam predvajanja trenutno predvaja oglas (vsaj en oglasni segment)."""
    return any(s["oglas"] for s in razcleni(besedilo)["segmenti"])


def razlicice(master: str, osnova: str = "") -> list[dict]:
    """Glavni seznam (master) -> [{"ime": "1080p60"|"720p60"|...|"audio_only", "visina", "pasovna", "uri"}],
    najboljsa najprej. Twitch izvorno kakovost imenuje »chunked«: ime dobi iz NAME (EXT-X-MEDIA) ali visine."""
    imena: dict[str, str] = {}
    izid: list[dict] = []
    cakajoca: Optional[dict] = None
    for surova in str(master or "").splitlines():
        v = surova.strip()
        if v.startswith("#EXT-X-MEDIA:"):
            a = _lastnosti(v)
            if a.get("GROUP-ID") and a.get("NAME"):
                imena[a["GROUP-ID"]] = a["NAME"]
        elif v.startswith("#EXT-X-STREAM-INF:"):
            cakajoca = _lastnosti(v)
        elif v and not v.startswith("#") and cakajoca is not None:
            a, cakajoca = cakajoca, None
            skupina = a.get("VIDEO", "")
            m = re.match(r"(\d+)x(\d+)", a.get("RESOLUTION", ""))
            visina = int(m.group(2)) if m else 0
            ime = imena.get(skupina) or skupina
            if ime == "chunked" or not ime:
                hz = a.get("FRAME-RATE", "")
                ime = ("%dp%s" % (visina, "60" if hz.startswith("6") else "")) if visina else "source"
            if not visina and "audio" in ime:
                ime = "audio_only"
            try:
                pasovna = int(a.get("BANDWIDTH") or 0)
            except ValueError:
                pasovna = 0
            izid.append({"ime": ime, "visina": visina, "pasovna": pasovna,
                         "uri": urllib.parse.urljoin(osnova, v) if osnova else v})
    izid.sort(key=lambda r: (r["visina"], r["pasovna"]), reverse=True)
    return izid


def izberi(variante: list[dict], kakovost: str = "auto", visina_zaslona: int = 1080) -> Optional[dict]:
    """Izbrana kakovost: "auto" = najboljsa, ki ni visja od zaslona; "audio_only" = samo zvok; "720" ... = najblizja
    nizja ali enaka (ce je ni, najnizja video). Prazen seznam -> None."""
    video = [v for v in variante if v["visina"] > 0]
    if kakovost == "audio_only":
        return next((v for v in variante if v["ime"] == "audio_only"), video[-1] if video else None)
    if not video:
        return variante[0] if variante else None
    meja = int(visina_zaslona or 1080) if kakovost in ("", "auto") else int(re.sub(r"\D", "", kakovost) or 0) or 1080
    return next((v for v in video if v["visina"] <= meja), video[-1])


def dovoljen(naslov: str) -> bool:
    """Seznami in segmenti so samo na streznikih Twitcha (https) - posrednik ne bere poljubnih naslovov."""
    p = urllib.parse.urlsplit(str(naslov or ""))
    gostitelj = (p.hostname or "").lower()
    return p.scheme == "https" and any(gostitelj.endswith(k) or gostitelj == k[1:] for k in _GOSTITELJI)


def _beri(naslov: str, cas: float = 10.0) -> tuple[int, str]:
    if not dovoljen(naslov):
        return 0, ""
    zahteva = urllib.request.Request(naslov, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.apple.mpegurl"})
    try:
        with urllib.request.urlopen(zahteva, timeout=cas) as odgovor:
            return odgovor.status, odgovor.read(4_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (OSError, ValueError):
        return 0, ""


class Vir:
    """En tok Twitcha (glavni ali rezervni): [master] da glavni seznam (nov zeton dostopa), izbere se kakovost."""

    def __init__(self, ime: str, master: Callable[[], Optional[tuple[str, str]]], kakovost: str, visina: int,
                 beri: Callable[[str], tuple[int, str]]):
        self.ime = ime
        self._master = master
        self._kakovost = kakovost
        self._visina = visina
        self._beri = beri
        self.uri = ""
        self.razlicica = ""

    def _pripravi(self) -> bool:
        try:
            m = self._master()
        except Exception as e:  # noqa: BLE001 - omrezje ali spremenjen GQL: vir ni na voljo, seja tece naprej
            print("[Twitch] vir %s: %s" % (self.ime, type(e).__name__), flush=True)
            m = None
        if not m:
            return False
        besedilo, osnova = m
        izbrana = izberi(razlicice(besedilo, osnova), self._kakovost, self._visina)
        if not izbrana or not dovoljen(izbrana["uri"]):
            return False
        self.uri, self.razlicica = izbrana["uri"], izbrana["ime"]
        return True

    def seznam(self) -> Optional[dict]:
        """Trenutni seznam (razclenjen) ali None. Potekel naslov (403/404/410) pripravi znova z novim zetonom."""
        for poskus in range(2):
            if not self.uri and not self._pripravi():
                return None
            status, besedilo = self._beri(self.uri)
            if status == 200 and besedilo.lstrip().startswith("#EXTM3U"):
                return razcleni(besedilo, self.uri)
            self.uri = ""
            if status not in (403, 404, 410) or poskus:
                return None
        return None


class Seja:
    """Nas seznam predvajanja za en prenos: glavni vir in rezervni brez oglasov, segmenti po casu (PDT)."""

    def __init__(self, glavni: Vir, rezerve: list[Vir], brez_oglasov: Callable[[], bool] = lambda: True,
                 ura: Callable[[], float] = time.monotonic):
        self.glavni = glavni
        self.rezerve = list(rezerve)
        self.brez_oglasov = brez_oglasov
        self._ura = ura
        self._okno: list[dict] = []      # izdani segmenti (z "zap" in "prekinitev")
        self._zaporedje = 0              # zaporedna stevilka prvega segmenta v oknu
        self._prekinitve = 0             # EXT-X-DISCONTINUITY-SEQUENCE: prekinitve, ki so ze izpadle iz okna
        self._zadnji_cas: Optional[float] = None
        self._zadnji_uri: set[str] = set()
        self._preskoceni: set[str] = set()   # oglasni segmenti, ki jih nismo dali naprej (ne stejemo jih dvakrat)
        self._izvor = ""                 # ime vira zadnjega izdanega segmenta
        self._cilj = 2.0
        self._osvezeno = -1e9
        self._rezerva = 0                # indeks rezerve, ki je nazadnje dala segmente brez oglasa
        self._kljuc = threading.Lock()
        self.zadnje_branje = ura()
        self.izpuscenih = 0              # oglasni segmenti, ki ob branju niso imeli nadomestka (rezerva zamuja ali ima oglas)
        self.nadomescenih = 0            # segmentov, vzetih iz rezerve namesto oglasa
        self.konec = False

    def _novi(self, segmenti: list[dict]) -> list[dict]:
        """Segmenti, ki so za zadnjim izdanim (po casu PDT; brez PDT po naslovu)."""
        izid = []
        for s in segmenti:
            if s["uri"] in self._preskoceni:
                continue
            if s["pdt"] is not None and self._zadnji_cas is not None:
                if s["pdt"] <= self._zadnji_cas + 0.05:
                    continue
            elif s["uri"] in self._zadnji_uri:
                continue
            izid.append(s)
        return izid

    def _izdaj(self, s: dict, izvor: str) -> None:
        prekinitev = bool(self._okno) and izvor != self._izvor
        self._okno.append(dict(s, prekinitev=prekinitev))
        self._izvor = izvor
        if s["pdt"] is not None:
            self._zadnji_cas = s["pdt"]
        self._zadnji_uri.add(s["uri"])
        while len(self._okno) > OKNO:
            star = self._okno.pop(0)
            self._zaporedje += 1
            self._zadnji_uri.discard(star["uri"])
            if self._okno and self._okno[0]["prekinitev"]:
                # Prvi v oknu nosi prekinitev: steje v DISCONTINUITY-SEQUENCE, oznaka sama odpade (HLS, 6.2.2).
                self._okno[0] = dict(self._okno[0], prekinitev=False)
                self._prekinitve += 1

    def _iz_rezerve(self, od_casa: Optional[float]) -> tuple[list[dict], str]:
        """Segmenti brez oglasa iz prve rezerve, ki jih ima (zacne pri zadnji uspesni)."""
        for i in list(range(self._rezerva, len(self.rezerve))) + list(range(0, self._rezerva)):
            vir = self.rezerve[i]
            sz = vir.seznam()
            if not sz:
                continue
            segmenti = [s for s in self._novi(sz["segmenti"]) if s["pdt"] is not None]
            if od_casa is not None:
                segmenti = [s for s in segmenti if s["pdt"] > od_casa + 0.05]
            if any(s["oglas"] for s in sz["segmenti"][-3:]):
                continue                 # tudi ta rezerva je pravkar v oglasu
            ciste = [s for s in segmenti if not s["oglas"]]
            if ciste:
                self._rezerva = i
                return ciste, vir.ime
        return [], ""

    def osvezi(self) -> None:
        """Prebere glavni tok (najvec enkrat na OSVEZI_S) in doda nove segmente v okno."""
        zdaj = self._ura()
        if zdaj - self._osvezeno < OSVEZI_S:
            return
        self._osvezeno = zdaj
        sz = self.glavni.seznam()
        if not sz:
            return
        self._cilj = max(1.0, sz["cilj"])
        self.konec = sz["konec"]
        novi = self._novi(sz["segmenti"])
        if not self.brez_oglasov():
            for s in novi:
                self._izdaj(s, self.glavni.ime)
            return
        oglasni = [s for s in novi if s["oglas"]]
        if not oglasni:
            for s in novi:
                self._izdaj(s, self.glavni.ime)
            return
        # Glavni tok predvaja oglas: dovoljeni segmenti pred oglasom gredo naprej, nato rezerva za cas oglasa.
        for s in novi:
            if s["oglas"]:
                break
            self._izdaj(s, self.glavni.ime)
        nadomestni, izvor = self._iz_rezerve(self._zadnji_cas)
        for s in nadomestni:
            self._izdaj(s, izvor)
        self.nadomescenih += len(nadomestni)
        # Dovoljeni segmenti glavnega toka po oglasu (oglas se je ze koncal), ce so novejsi od rezervnih.
        po_oglasu = [s for s in novi if not s["oglas"] and s["pdt"] is not None and oglasni[-1]["pdt"] is not None
                     and s["pdt"] > oglasni[-1]["pdt"]]
        for s in self._novi(po_oglasu):
            self._izdaj(s, self.glavni.ime)
        if len(self._preskoceni) > 500:
            self._preskoceni.clear()
        for s in oglasni:
            # Izpuscen je oglasni trenutek, ki ga rezerva ni pokrila (je za zadnjim izdanim segmentom).
            pokrit = s["pdt"] is not None and self._zadnji_cas is not None and s["pdt"] <= self._zadnji_cas
            if s["uri"] not in self._preskoceni and not pokrit:
                self.izpuscenih += 1
            self._preskoceni.add(s["uri"])

    def besedilo(self) -> str:
        """Nas seznam predvajanja za predvajalnik (HLS v3, brez oglasnih oznak Twitcha)."""
        with self._kljuc:
            self.zadnje_branje = self._ura()
            self.osvezi()
            cilj = max([self._cilj] + [s["trajanje"] for s in self._okno])
            vrstice = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:%d" % int(cilj + 0.999),
                       "#EXT-X-MEDIA-SEQUENCE:%d" % self._zaporedje]
            if self._prekinitve:
                vrstice.append("#EXT-X-DISCONTINUITY-SEQUENCE:%d" % self._prekinitve)
            for s in self._okno:
                if s["prekinitev"]:
                    vrstice.append("#EXT-X-DISCONTINUITY")
                if s["pdt"] is not None:
                    vrstice.append("#EXT-X-PROGRAM-DATE-TIME:" + datetime.datetime.fromtimestamp(
                        s["pdt"], datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"))
                vrstice.append("#EXTINF:%.3f,live" % s["trajanje"])
                vrstice.append(s["uri"])
            if self.konec:
                vrstice.append("#EXT-X-ENDLIST")
            return "\n".join(vrstice) + "\n"


class _Rokovalnik(os_deskriptorji.RokCakanjaZahteve, http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - ime doloca http.server
        m = re.fullmatch(r"/twitch/([A-Za-z0-9_-]{16,64})\.m3u8", urllib.parse.urlsplit(self.path).path)
        seja = self.server.posrednik.seja(m.group(1)) if m else None  # type: ignore[attr-defined]
        if seja is None:
            self.send_error(404)
            return
        try:
            telo = seja.besedilo().encode("utf-8")
        except Exception as e:  # noqa: BLE001 - napaka seje ne sme ustaviti streznika
            print("[Twitch] seznam:", type(e).__name__, flush=True)
            self.send_error(502)
            return
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(telo)))
            self.end_headers()
            self.wfile.write(telo)
        except OSError:
            pass             # predvajalnik je med odgovorom zaprl povezavo (ustavljen prenos)

    def log_message(self, *_a) -> None:
        pass                 # naslovi nosijo zeton seje - nic v dnevnik


class _Streznik(os_deskriptorji.BrezBujenja, socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, _zahteva, _naslov) -> None:
        pass                 # prekinjena povezava predvajalnika ni napaka (privzeto bi izpisal sled v dnevnik)


class Posrednik:
    """Lokalni streznik seznamov (127.0.0.1, nakljucna vrata) - zazene se ob prvem prenosu Twitch."""

    def __init__(self, ura: Callable[[], float] = time.monotonic):
        self._seje: dict[str, Seja] = {}
        self._kljuc = threading.Lock()
        self._streznik: Optional[_Streznik] = None
        self._ura = ura

    @property
    def vrata(self) -> int:
        from core import storitve_na_zahtevo as snz
        with self._kljuc:
            if self._streznik is None:
                streznik = _Streznik(("127.0.0.1", 0), _Rokovalnik)
                streznik.posrednik = self  # type: ignore[attr-defined]
                threading.Thread(target=streznik.serve_forever, name="twitch-hls", daemon=True).start()
                self._streznik = streznik
                # Na zahtevo (lastnik, 18. 10. 2026): ko nobena seja NEAKTIVNA_S ne bere (seje takrat itak potecejo),
                # ura storitev streznik ustavi; naslednji prenos ga zazene znova na novih vratih (nov naslov seje).
                snz.registriraj("twitch", snz.NA_ZAHTEVO, NEAKTIVNA_S, tece=lambda: self._streznik is not None,
                                ustavi=self._ustavi_ce_miruje, zaposlena=self._gleda)
            snz.rabi("twitch")
            return self._streznik.server_address[1]

    def _gleda(self) -> bool:
        """Ali kak predvajalnik se bere sejo (zadnje branje v NEAKTIVNA_S)."""
        zdaj = self._ura()
        with self._kljuc:
            return any(zdaj - s.zadnje_branje <= NEAKTIVNA_S for s in self._seje.values())

    def _ustavi_ce_miruje(self) -> None:
        if not self._gleda():
            self.ustavi()

    def _pocisti(self) -> None:
        zdaj = self._ura()
        for k in [k for k, s in self._seje.items() if zdaj - s.zadnje_branje > NEAKTIVNA_S]:
            del self._seje[k]
        while len(self._seje) >= NAJVEC_SEJ:
            najstarejsa = min(self._seje, key=lambda k: self._seje[k].zadnje_branje)
            del self._seje[najstarejsa]

    def dodaj(self, seja: Seja) -> str:
        """Nova seja -> naslov za predvajalnik."""
        zeton = secrets.token_urlsafe(18)
        with self._kljuc:
            self._pocisti()
            self._seje[zeton] = seja
        return "http://127.0.0.1:%d/twitch/%s.m3u8" % (self.vrata, zeton)

    def seja(self, zeton: str) -> Optional[Seja]:
        with self._kljuc:
            return self._seje.get(zeton)

    def ustavi(self) -> None:
        with self._kljuc:
            streznik, self._streznik = self._streznik, None
            self._seje.clear()
        if streznik is not None:
            streznik.shutdown()
            streznik.server_close()
