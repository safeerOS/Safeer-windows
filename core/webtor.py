"""Webtor rezerva na namizju (skupna koda Linux in Windows, brez GTK) - kar TorBox nima pripravljenega, zacne teci prek
uporabnikovega osebnega dodatka Stremio Webtor, da uporabnik ne caka na prenos (lastnik 25. 10. 2026).

Ista pravila kot Safeer OS za Android (WebtorPravila.kt, Webtor.kt na veji webtor-rezerva; skupni primeri
tests/skupni-primeri/webtor-rezerva.json): dodatek vrne tok »url« = `https://webtor.io/token/<zeton>/stremio/resolve/<JWT>`
(JWT 72 h), ki s 302 preusmeri na izvirno datoteko (progresivno, Range). Ime toka ima predpono `[⚡TB]` (pri TorBoxu v
Webtor profilu pripravljen - podvaja nas TorBox), `[⚡WT]` (Webtor ga ima pripravljenega), `[WT]` (Webtor ga prenasa
sproti) ali `[P2P]` (brezplacni racun: posnetek z oglasom za paket).

Sonda (popravki neodvisnega pregleda Androida, Grok 25. 10. 2026, U4): preusmeritvam sledimo sami (najvec 5), vsak skok
samo po https, brez uporabnika v naslovu; ime gostitelja razresimo sami in zavrnemo zanko, zasebne (RFC 1918, ULA),
link-local, CGNAT in druge nejavne naslove (vsi naslovi imena morajo biti javni), povezemo pa se na PREVERJENI naslov IP
(brez druge razresitve - DNS rebinding med preverbo in povezavo SONDE ne gre). Predvajalnik dobi KONCNI naslov, ki ga je
sonda preverila (ne /resolve/ z zetonom), in mu ne sledi vec preusmeritvam (core/os_predvajalnik: automatic-redirect=False,
brez te lastnosti se ne predvaja). Preostalo tveganje (Grok N7): predvajalnik ime razresi znova; notranja storitev bi za to
ime morala imeti veljavno potrdilo TLS (souphttpsrc ssl-strict je privzet in ga nikjer ne izklapljamo).
Koncni naslov je vezan na IP te naprave (Webtor primerja /24): ne shranjujemo ga in ne posiljamo drugim napravam.
"""
from __future__ import annotations

import base64
import binascii
import concurrent.futures
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
import urllib.parse
from dataclasses import dataclass
from typing import Callable, Optional

ID_MANIFESTA = "org.stremio.webtor.io"
GOSTITELJ = "webtor.io"
#: Oznaka vira toka (ime storitve, ne prevajamo).
IME = "Webtor"
#: Prvi bajt toka pozneje od tega: naslednji vir. Hkrati skupni rok vseh sond Webtor ene izbire.
PRVI_BAJT_MS = 15_000
#: Ena izbira toka poskusi najvec toliko tokov Webtor.
NAJVEC_POSKUSOV = 2
NAJVEC_PREUSMERITEV = 5
UPORABNISKI_AGENT = "SafeerOS/1.0"

# Vrste toka po predponi imena.
TORBOX = "TORBOX"
PREDPOMNJEN = "PREDPOMNJEN"
PRENOS = "PRENOS"
P2P = "P2P"

# Izidi sonde.
#: 2xx, a ni glavni video (naslovnica, glasba, vzorec, kodek brez dekoderja): meritev na Androidu 25. 10. popoldne -
#: Webtor je predvajal prvo datoteko torrenta (image/jpeg) in AVI brez videa. Naslednji vir.
NAPACNA_VSEBINA = "NAPACNA_VSEBINA"
PREDVAJAJ = "PREDVAJAJ"
NI_PAKETA = "NI_PAKETA"
NI_TOKA = "NI_TOKA"
OMEJITEV = "OMEJITEV"
PREPOCASI = "PREPOCASI"
NAPAKA = "NAPAKA"


def gostitelj(naslov: str) -> str:
    """Gostitelj naslova (male crke, brez vrat in uporabnika); "" = ni naslov http(s)."""
    n = str(naslov or "").strip()
    i = n.find("://")
    if i <= 0 or n[:i].lower() not in ("http", "https"):
        return ""
    g = re.split(r"[/?#]", n[i + 3:], maxsplit=1)[0].rpartition("@")[2]
    return g.split(":", 1)[0].lower().rstrip(".")


def je_webtor(id_manifesta: Optional[str]) -> bool:
    """Samo `id` manifesta (dodatek si ga izbere sam) - za odlocitev uporabi je_webtor_dodatek."""
    return str(id_manifesta or "").strip() == ID_MANIFESTA


def je_webtor_dodatek(id_manifesta: Optional[str], osnova: str) -> bool:
    """Dodatek je Webtor samo, ce ima `id` Webtorja IN je osnova (prava ali nadomestek) natanko na https://webtor.io."""
    return je_webtor(id_manifesta) and str(osnova or "").strip().lower().startswith("https://") \
        and gostitelj(osnova) == GOSTITELJ


def je_resolve_naslov(url: str) -> bool:
    """Naslov `https://webtor.io/.../resolve/...` (tok dodatka Webtor, prav ali kot nadomestek)."""
    u = str(url or "").strip()
    return u.lower().startswith("https://") and gostitelj(u) == GOSTITELJ and "/resolve/" in u.split("?", 1)[0]


_RX_PREDPONA = re.compile(r"^\s*\[\s*(⚡️?)?\s*(TB|WT|P2P)\s*]\s*", re.I)


def razcleni(ime: str) -> tuple:
    """Predpona imena toka -> (vrsta, ime brez predpone)."""
    ime = str(ime or "")
    m = _RX_PREDPONA.match(ime)
    if not m:
        return PRENOS, ime.strip()
    oznaka = m.group(2).upper()
    vrsta = TORBOX if oznaka == "TB" else P2P if oznaka == "P2P" else PREDPOMNJEN if m.group(1) else PRENOS
    return vrsta, ime[m.end():].strip()


def skrij(vrsta: str, imamo_torbox: bool) -> bool:
    """`[⚡TB]` podvaja nas TorBox (le, ce ga imamo), `[P2P]` je posnetek z oglasom za paket, ne film."""
    return vrsta == P2P or (vrsta == TORBOX and imamo_torbox)


def takoj(vrsta: str) -> bool:
    """Tok, ki se zacne takoj: `[⚡WT]` in `[⚡TB]`."""
    return vrsta in (PREDPOMNJEN, TORBOX)


_RX_HASH = re.compile(r"^[0-9a-f]{40}$")


def kljuc(hash_: Optional[str], idx: Optional[int]) -> Optional[tuple]:
    """Izdaja: (infoHash 40 hex, datoteka); -1 = datoteka ni znana."""
    h = str(hash_ or "").strip().lower()
    if not _RX_HASH.match(h):
        return None
    return h, (-1 if idx is None or idx < 0 else int(idx))


def iz_jwt(url: str) -> Optional[tuple]:
    """(hash, idx) iz JWT v naslovu `.../resolve/<JWT>` - samo za ujemanje izdaje (podpis preveri Webtor sam)."""
    pot = str(url or "").split("?", 1)[0].split("#", 1)[0]
    if "/resolve/" not in pot:
        return None
    deli = pot.split("/resolve/", 1)[1].split("/", 1)[0].split(".")
    if len(deli) != 3 or not deli[1]:
        return None
    try:
        t = deli[1].rstrip("=")
        telo = base64.urlsafe_b64decode(t + "=" * (-len(t) % 4)).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    h = re.search(r'"hash"\s*:\s*"([0-9a-fA-F]{40})"', telo)
    i = re.search(r'"idx"\s*:\s*"?(-?\d{1,6})', telo)
    return kljuc(h.group(1) if h else None, int(i.group(1)) if i else -1)


# Datoteka toka Webtor (Android WebtorPravila.datoteka, skupni primeri verzija 3).
VIDEO = "VIDEO"
NAJVECJI = "NAJVECJI"
NEGOTOVA = "NEGOTOVA"
NI_VIDEO = "NI_VIDEO"
#: Datoteka toka Webtor je samo `idx` v JWT (to /resolve predvaja). Webtor polje fileIdx 0 izpusti (omitempty), zato tok
#: BREZ fileIdx postane indeks 0 = PRVA datoteka torrenta (naslovnica). JWT brez idx: Webtor izbere najvecji video sam.
IDX_NEZNAN = -2


def kljuc_webtor(hash_toka: Optional[str], url: str) -> Optional[tuple]:
    """Izdaja toka Webtor: hash in datoteka iz JWT; brez JWT (hash toka, IDX_NEZNAN) - nikoli enaka nasi izdaji."""
    j = iz_jwt(url)
    if j is not None:
        return j
    h = str(hash_toka or "").strip().lower()
    return (h, IDX_NEZNAN) if _RX_HASH.match(h) else None


#: Koncnice, ki jih predvajalnik zanesljivo razcleni kot video (enako kot Android Media3 1.11 - skupni primeri).
VIDEO_KONCNICE = frozenset({"mkv", "webm", "mp4", "m4v", "mov", "avi", "divx", "ts", "m2ts", "mts", "mpg", "mpeg", "flv",
                            "3gp"})
_RX_VZOREC = re.compile(r"(^|[^a-z])sample([^a-z]|$)")


def je_video_ime(ime: str) -> Optional[bool]:
    """True = ime glavnega videa, False = ni (druga koncnica ali vzorec), None = ime tega ne pove."""
    n = str(ime or "").strip().lower().rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if not n:
        return None
    if _RX_VZOREC.search(n):
        return False
    k = n.rsplit(".", 1)[1] if "." in n else ""
    if not k or len(k) > 5 or not all(c.isalnum() for c in k):
        return None
    return k in VIDEO_KONCNICE


def datoteka(idx: int, ime_toka: str, nas_idx: Optional[int], nas_ime: str) -> str:
    """Kaj bo /resolve predvajal: `idx` iz JWT (IDX_NEZNAN, -1 = brez idx), `ime_toka` = behaviorHints.filename toka
    Webtor, `nas_idx`/`nas_ime` = nas tok za isti hash (None = ga nimamo)."""
    if idx == IDX_NEZNAN:
        return NEGOTOVA
    v = je_video_ime(ime_toka)
    if v is not None:
        return VIDEO if v else NI_VIDEO
    if idx < 0:
        return NAJVECJI
    if nas_idx is not None and nas_idx == idx:
        return NI_VIDEO if je_video_ime(nas_ime) is False else VIDEO
    return NEGOTOVA


def vrstni_red(nasi: list, webtor: list, imamo_torbox: bool, samo_takoj: bool = False,
               datoteke: Optional[list] = None) -> list:
    """Vrstni red tokov Webtor (indeksi v `webtor` = [(kljuc, vrsta)]): najprej tisti, ki se ujemajo z NASIMI torrenti
    (isti hash IN ista datoteka), nato ostali, `[⚡WT]` pred `[WT]`. Skriti izpadejo; `samo_takoj`: samo `[⚡WT]`/`[⚡TB]`.
    `datoteke` (datoteka(), None = vse VIDEO): NI_VIDEO izpade, NEGOTOVA ni »takoj« in je na koncu (samo s sondo vsebine)."""
    def d(i: int) -> str:
        return datoteke[i] if datoteke is not None and i < len(datoteke) else VIDEO
    vidni = [i for i, (_k, v) in enumerate(webtor) if not skrij(v, imamo_torbox) and d(i) != NI_VIDEO
             and (not samo_takoj or (takoj(v) and d(i) != NEGOTOVA))]
    izbrani: list = []
    for k in nasi:
        if k is None:
            continue
        i = next((i for i in vidni if i not in izbrani and webtor[i][0] == k and d(i) != NEGOTOVA), None)
        if i is not None:
            izbrani.append(i)
    ostali = [i for i in vidni if i not in izbrani]
    gotovi = [i for i in ostali if d(i) != NEGOTOVA]
    return (izbrani + [i for i in gotovi if takoj(webtor[i][1])] + [i for i in gotovi if not takoj(webtor[i][1])]
            + [i for i in ostali if d(i) == NEGOTOVA])


# ------------------------------------------------------------------ vsebina toka (sonda prvih bajtov)

#: Prvih toliko bajtov prebere sonda (Range 0-4095): dovolj za posodo in glavo AVI (hdrl).
GLAVA_BAJTOV = 4096
VIDEO_POSODE = frozenset({"MKV", "MP4", "TS", "PS", "AVI", "FLV"})


def posoda(g: bytes) -> str:
    """Posoda po prvih bajtih (enako kot Android WebtorPravila.posoda)."""
    g = bytes(g or b"")

    def u(i: int) -> int:
        return g[i] if i < len(g) else -1

    def ascii_(o: int, t: str) -> bool:
        return all(u(o + j) == ord(c) for j, c in enumerate(t))
    brand = "".join(chr(u(i)) if 32 <= u(i) <= 126 else "?" for i in range(8, 12))
    if (u(0), u(1), u(2), u(3)) == (0x1A, 0x45, 0xDF, 0xA3):
        return "MKV"
    if ascii_(4, "ftyp"):
        if brand in ("heic", "heix", "heim", "heis", "mif1", "msf1", "avif", "avis"):
            return "HEIF"
        return "M4A" if brand in ("M4A ", "M4B ", "M4P ") else "MP4"
    if any(ascii_(4, a) for a in ("moov", "mdat", "free", "wide", "skip")):
        return "MP4"
    if ascii_(0, "RIFF") and ascii_(8, "AVI "):
        return "AVI"
    if ascii_(0, "RIFF") and ascii_(8, "WAVE"):
        return "WAV"
    if ascii_(0, "RIFF") and ascii_(8, "WEBP"):
        return "WEBP"
    if (u(0) == 0x47 and u(188) == 0x47) or (u(4) == 0x47 and u(196) == 0x47):
        return "TS"
    if (u(0), u(1), u(2), u(3)) == (0, 0, 1, 0xBA):
        return "PS"
    if ascii_(0, "FLV"):
        return "FLV"
    if (u(0), u(1), u(2), u(3)) == (0x30, 0x26, 0xB2, 0x75):
        return "ASF"
    if u(0) == 0xFF and u(1) == 0xD8 and u(2) == 0xFF:
        return "JPEG"
    if u(0) == 0x89 and ascii_(1, "PNG"):
        return "PNG"
    if ascii_(0, "GIF8"):
        return "GIF"
    if ascii_(0, "ID3") or (u(0) == 0xFF and u(1) >= 0 and (u(1) & 0xE0) == 0xE0):
        return "ZVOK"
    for znak, ime in (("fLaC", "FLAC"), ("OggS", "OGG"), ("%PDF", "PDF"), ("Rar!", "RAR")):
        if ascii_(0, znak):
            return ime
    if ascii_(0, "PK") and u(2) == 3 and u(3) == 4:
        return "ZIP"
    if (u(0), u(1), u(2), u(3)) == (0x37, 0x7A, 0xBC, 0xAF):
        return "SEDEMZ"
    if g and all(32 <= u(i) <= 126 or u(i) in (9, 10, 13) or u(i) >= 0x80 for i in range(min(len(g), 64))):
        return "BESEDILO"
    return "NEZNANO"


def avi_kodek(g: bytes) -> str:
    """Kodek videa v glavi AVI (strf -> BITMAPINFOHEADER.biCompression za tok `vids`); "" = ga v prvih bajtih ni."""
    g = bytes(g or b"")

    def ascii_(o: int, t: str) -> bool:
        return o >= 0 and o + len(t) <= len(g) and g[o:o + len(t)] == t.encode("ascii")
    i = 12
    while i + 64 <= len(g):
        if ascii_(i, "strh") and ascii_(i + 8, "vids"):
            dolzina = int.from_bytes(g[i + 4:i + 8], "little", signed=True)
            f = i + 8 + dolzina + (dolzina & 1)
            if dolzina < 0 or f + 8 + 20 > len(g) or not ascii_(f, "strf"):
                return ""
            o = f + 8 + 16
            return "".join(chr(b) if 32 <= b <= 126 else "?" for b in g[o:o + 4])
        i += 1
    return ""


def avi_mime(fourcc: str) -> Optional[str]:
    """MIME kodeka AVI (kot Media3 StreamFormatChunk); None = predvajalnik sled izpusti (skupno pravilo z Androidom)."""
    return {"MP42": "video/mp42", "MP43": "video/mp43", "H264": "video/avc", "avc1": "video/avc", "AVC1": "video/avc",
            "MJPG": "video/mjpeg", "mjpg": "video/mjpeg"}.get(fourcc) or (
        "video/mp4v-es" if fourcc in ("3VID", "divx", "DIVX", "DX50", "FMP4", "xvid", "XVID") else None)


# Vsebina (pregled prvih bajtov).
NEPODPRTA = "NEPODPRTA"
PREMAJHNA = "PREMAJHNA"


def pregled(vrsta: Optional[str], glava: bytes, skupaj: int, pricakovano_gb: float,
            kodek_podprt: Callable[[str], bool] = lambda _m: True) -> tuple:
    """(vsebina, posoda, kodek): ali je odgovor sonde glavni video, ki ga ta naprava predvaja. `vrsta` = Content-Type,
    `skupaj` = velikost datoteke (Content-Range, -1 = neznana), `pricakovano_gb` = velikost iz opisa toka (0 = ni).
    Posoda po bajtih je odlocilna; Content-Type audio/image/text zavrne. Na namizju GStreamer z gst-libav (debian/control)."""
    p = posoda(glava)
    ct = str(vrsta or "").split(";", 1)[0].strip().lower()
    if p == "ASF":
        return NEPODPRTA, p, ""
    if p not in VIDEO_POSODE:
        return (VIDEO if p == "NEZNANO" and ct.startswith("video/") else NI_VIDEO), p, ""
    if ct.startswith(("audio/", "image/", "text/")):
        return NI_VIDEO, p, ""
    kodek = ""
    if p == "AVI":
        kodek = avi_kodek(glava)
        if kodek:
            mime = avi_mime(kodek)
            if mime is None or not kodek_podprt(mime):
                return NEPODPRTA, p, kodek
    mib = 1024 * 1024
    if 0 <= skupaj < 10 * mib:
        return PREMAJHNA, p, kodek
    # Vzorec: opis toka pove velikost filma (ne paketa nad 100 GB), datoteka je pod 10 % in pod 200 MiB.
    if skupaj > 0 and 0.0 < pricakovano_gb <= 100.0 and skupaj < 200 * mib and skupaj < pricakovano_gb * 1024.0 * mib * 0.1:
        return PREMAJHNA, p, kodek
    return VIDEO, p, kodek


def skupna_velikost(koda: int, content_range: Optional[str], content_length: int) -> int:
    """Velikost datoteke: `Content-Range: bytes 0-4095/123` (206) ali Content-Length (200); -1 = neznano."""
    if koda == 206:
        try:
            return int(str(content_range or "").rsplit("/", 1)[1].strip()) if "/" in str(content_range or "") else -1
        except ValueError:
            return -1
    return content_length if 200 <= koda <= 299 and content_length >= 0 else -1


_RX_VELIKOST = re.compile(r"(\d+(?:[.,]\d+)?)\s*(GB|GiB|MB|MiB)\b", re.I)


def pricakovana_velikost_gb(opis: str) -> float:
    """Velikost iz opisa toka (»💾 6.56 GB«); 0 = je ni."""
    m = _RX_VELIKOST.search(str(opis or ""))
    if not m:
        return 0.0
    v = float(m.group(1).replace(",", "."))
    return v if m.group(2).lower().startswith("g") else v / 1024.0


def odlocitev(koda: int, prvi_bajt_ms: Optional[int], potekel: bool, vsebina: Optional[str] = None) -> str:
    """402 = ni paketa, 404/410 = Webtor toka nima, 429 = omejitev; 2xx s sliko, glasbo, vzorcem ali kodekom, ki ga
    naprava ne zna = NAPACNA_VSEBINA. Vse razen PREDVAJAJ pomeni: naslednji vir."""
    if koda == 402:
        return NI_PAKETA
    if koda in (404, 410):
        return NI_TOKA
    if koda == 429:
        return OMEJITEV
    if potekel:
        return PREPOCASI
    if 200 <= koda <= 299 and prvi_bajt_ms is not None:
        if prvi_bajt_ms > PRVI_BAJT_MS:
            return PREPOCASI
        return NAPACNA_VSEBINA if vsebina is not None and vsebina != VIDEO else PREDVAJAJ
    return NAPAKA


#: Hitra zavrnitev vsebine ne steje kot poskus (skupno pravilo v4, pomocnik Windows 25. 10. 2026, naloga 21 B1): pri
#: torrentih YTS CDN TorBox za idx filma vrne .srt; sonda ga zavrne v ~0,3-0,7 s, a je porabila enega od 2 poskusov.
HITRA_ZAVRNITEV_MS = 3_000


def steje_kot_poskus(izid: str, trajanje_ms: int) -> bool:
    """Ali sonda steje med NAJVEC_POSKUSOV: NAPACNA_VSEBINA v manj kot HITRA_ZAVRNITEV_MS ne (skupni rok 15 s velja
    naprej - naslednji tok dobi preostanek). Vse drugo (tudi hitra 404/402/429) steje."""
    return not (izid == NAPACNA_VSEBINA and 0 <= int(trajanje_ms) < HITRA_ZAVRNITEV_MS)


def rok_sonde(zacetek_prve: Optional[int], zdaj: int, poskusov: int) -> int:
    """Koliko ms ima naslednja sonda v eni izbiri toka: skupaj najvec PRVI_BAJT_MS in najvec NAJVEC_POSKUSOV sond."""
    if poskusov >= NAJVEC_POSKUSOV:
        return 0
    if zacetek_prve is None:
        return PRVI_BAJT_MS
    return max(0, PRVI_BAJT_MS - (zdaj - zacetek_prve))


# ------------------------------------------------------------------ Scit

#: Stalne izjeme Scita za Webtor - samo pred seznami OGLASOV, nikoli pred seznami grozenj (core/os_scit._kategorija).
#: Pregled Grok U10: ozko, natancni gostitelji (Android ima tu se vse poddomene obeh domen).
_IZJEME_TOCNE = frozenset({"webtor.io", "api.webtor.io"})
_RX_GOSTITELJ_TOKA = re.compile(r"^abra--[a-z0-9-]{1,57}\.api\.cosmic-crab\.buzz$")


def je_stalna_izjema_scita(ime: str) -> bool:
    """Gostitelj API Webtorja ali gostitelj toka `abra--<id>.api.cosmic-crab.buzz` (porocilo webtor/porocilo-rezerva.md)."""
    d = str(ime or "").strip().lower().rstrip(".")
    return d in _IZJEME_TOCNE or bool(_RX_GOSTITELJ_TOKA.match(d))


def scit_dovoljena(ime: str, naucene: dict, zdaj: int) -> bool:
    """Domena je med izjemami: stalna ali naucena NATANKO in se veljavna ob `zdaj` (skupni primeri z Androidom)."""
    d = str(ime or "").strip().lower().strip(".")
    if not d:
        return False
    return je_stalna_izjema_scita(d) or int((naucene or {}).get(d) or 0) > zdaj


# ------------------------------------------------------------------ sonda

def javen_ip(naslov: str) -> bool:
    """Naslov IP je javen: ne zanka, ne zasebno omrezje (RFC 1918, ULA), ne link-local, ne CGNAT, ne vecvrocno."""
    try:
        a = ipaddress.ip_address(str(naslov).split("%", 1)[0])
    except ValueError:
        return False
    a = getattr(a, "ipv4_mapped", None) or a
    if a.version == 6:
        for vgrajen in (getattr(a, "sixtofour", None), (getattr(a, "teredo", None) or (None, None))[1]):
            if vgrajen is not None and not javen_ip(str(vgrajen)):
                return False
    return bool(a.is_global) and not a.is_multicast


class ZasebenNaslov(OSError):
    """Ime se razresi v nejaven naslov - sonda ga zavrne (ne v domace omrezje, ne v zanko)."""


def razresi(gostitelj_: str, vrata: int) -> str:
    """Prvi naslov IP imena; ce je kateri od naslovov nejaven, ZasebenNaslov (napadalec bi lahko dal javnega in
    zasebnega)."""
    naslovi = [i[4][0] for i in socket.getaddrinfo(gostitelj_, vrata, type=socket.SOCK_STREAM)]
    if not naslovi:
        raise OSError("ni naslova")
    if not all(javen_ip(n) for n in naslovi):
        raise ZasebenNaslov("nejaven naslov")
    return naslovi[0]


class _PovezavaNaIp(http.client.HTTPSConnection):
    """HTTPS na ze preverjen naslov IP; SNI in preverba potrdila za ime gostitelja."""

    def __init__(self, gostitelj_: str, ip: str, vrata: int, rok: float) -> None:
        super().__init__(gostitelj_, vrata, timeout=rok, context=ssl.create_default_context())
        self._ip = ip

    def connect(self) -> None:
        surova = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(surova, server_hostname=self.host)


#: Glave toka (behaviorHints.proxyHeaders), ki jih sonda poslje - isti seznam kot predvajalnik
#: (core/os_predvajalnik._DOVOLJENE_GLAVE): Authorization, Cookie in podobne nikoli.
DOVOLJENE_GLAVE = frozenset({"referer", "origin", "user-agent", "accept", "accept-language", "x-requested-with"})


def glave_toka(glave: Optional[dict]) -> dict:
    """Dovoljene glave toka brez prelomov vrstic (najvec 12)."""
    izid: dict = {}
    for ime, vrednost in list((glave or {}).items())[:12] if isinstance(glave, dict) else ():
        ime, vrednost = str(ime or ""), str(vrednost or "")
        if ime.lower() in DOVOLJENE_GLAVE and "\n" not in vrednost and "\r" not in vrednost:
            izid[ime[:64]] = vrednost[:2048]
    return izid


def zahteva(naslov: str, gostitelj_: str, ip: str, vrata: int, rok: float, glave: Optional[dict] = None) -> tuple:
    """GET prvih GLAVA_BAJTOV (Range) brez samodejnih preusmeritev -> (koda, Location ali None, prvi bajti,
    {"content-type", "content-range", "content-length"}). `glave`: glave toka (glave_toka) - prepisejo privzete."""
    d = urllib.parse.urlsplit(naslov)
    pot = (d.path or "/") + ("?" + d.query if d.query else "")
    c = _PovezavaNaIp(gostitelj_, ip, vrata, rok)
    konec = time.monotonic() + rok
    try:
        c.request("GET", pot, headers={"Accept-Encoding": "identity", "Accept": "*/*", "User-Agent": UPORABNISKI_AGENT,
                                       **glave_toka(glave), "Range": "bytes=0-%d" % (GLAVA_BAJTOV - 1)})
        if c.sock is not None:
            c.sock.settimeout(max(0.05, konec - time.monotonic()))   # skupni rok, ne rok vsake operacije (Grok N9)
        r = c.getresponse()
        if c.sock is not None:
            c.sock.settimeout(max(0.05, konec - time.monotonic()))
        lokacija = r.getheader("Location")
        bajti = r.read(GLAVA_BAJTOV) if 200 <= r.status <= 299 else b""
        glave = {k: str(r.getheader(k) or "") for k in ("content-type", "content-range", "content-length")}
        return int(r.status), lokacija, bajti, glave
    finally:
        c.close()


@dataclass(frozen=True)
class Sonda:
    """Izid sonde: koda HTTP (0 = ni odgovora), cas do prvega bajta (None = ga ni bilo), iztek roka, gostitelj zadnjega
    skoka, KONCNI preverjeni naslov (samo ob 2xx s prvimi bajti), razlog zavrnitve (brez naslova, za dnevnik) in pregled
    vsebine (vsebina, posoda, kodek; vsebina None = ni pregledana)."""
    koda: int = 0
    prvi_bajt_ms: Optional[int] = None
    potekel: bool = False
    gostitelj: str = ""
    koncni: Optional[str] = None
    razlog: str = ""
    vsebina: Optional[str] = None
    posoda: str = ""
    kodek: str = ""

    @property
    def izid(self) -> str:
        izid = odlocitev(self.koda, self.prvi_bajt_ms, self.potekel, self.vsebina)
        return izid if izid != PREDVAJAJ or self.koncni else NAPAKA


def _razresi_z_rokom(razresi_fn: Callable[[str, int], str], gostitelj_: str, vrata: int, rok: float) -> str:
    """Razresitev imena v najvec `rok` s (getaddrinfo nima roka - Grok N9); nit se konca sama, ko razresevalnik odgovori."""
    if razresi_fn is not razresi:
        return razresi_fn(gostitelj_, vrata)            # ponaredek v preizkusih: brez niti
    bazen = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="safeer-webtor-dns")
    try:
        return bazen.submit(razresi_fn, gostitelj_, vrata).result(timeout=max(0.05, rok))
    except concurrent.futures.TimeoutError:
        raise socket.timeout("dns") from None
    finally:
        bazen.shutdown(wait=False)          # ne cakamo: nit se konca, ko razresevalnik odgovori


def sonda(url: str, rok_ms: int = PRVI_BAJT_MS, *, razresi_fn: Callable[[str, int], str] = razresi,
          zahteva_fn: Callable[..., tuple] = zahteva, ura: Callable[[], float] = time.monotonic,
          preveri_vsebino: bool = True, pricakovano_gb: float = 0.0,
          kodek_podprt: Callable[[str], bool] = lambda _m: True, glave: Optional[dict] = None) -> Sonda:
    """Prvi bajti toka `url` (pravi naslov, ne nadomestek) v najvec `rok_ms` skupaj. Blokira - z delovne niti.
    Ni dovolj koda 206: vsebina mora biti glavni video (pregled - posoda po bajtih, Content-Type, velikost proti opisu
    toka `pricakovano_gb`; Android 25. 10.: Webtor je dal naslovnico JPEG, MP3 in AVI brez videa).
    `preveri_vsebino=False`: brez pregleda vsebine (tok dodatka s kljucem, ki je lahko tudi zvok) - preusmeritve, https
    in javni naslovi se preverijo enako. `glave` (proxyHeaders toka, Grok 19 M3): samo na gostitelja toka - po
    preusmeritvi na drug gostitelj ne gredo (strezniki tokov brez Referer vracajo 429, glej media_servers.tok_stanje)."""
    zacetek = ura()
    naslov = str(url or "")
    g = gostitelj(naslov)
    izvorni = g
    glave = glave_toka(glave)
    for skok in range(NAJVEC_PREUSMERITEV + 1):
        ostane = rok_ms / 1000.0 - (ura() - zacetek)
        if ostane <= 0:
            return Sonda(potekel=True, gostitelj=g, razlog="rok")
        try:
            d = urllib.parse.urlsplit(naslov)
            vrata = d.port or 443
        except ValueError:
            return Sonda(gostitelj=g, razlog="naslov")
        g = (d.hostname or "").lower().rstrip(".")
        if d.scheme != "https" or not g or d.username is not None or d.password is not None or "\\" in d.netloc:
            return Sonda(gostitelj=g, razlog="ni_https")
        try:
            ip = _razresi_z_rokom(razresi_fn, g, vrata, ostane)
        except ZasebenNaslov:
            return Sonda(gostitelj=g, razlog="zasebni_naslov")
        except (socket.timeout, TimeoutError):
            return Sonda(potekel=True, gostitelj=g, razlog="rok")
        except (OSError, UnicodeError, ValueError):     # UnicodeError: neveljavno ime v kodeku IDNA (Grok N9)
            return Sonda(gostitelj=g, razlog="dns")
        if not javen_ip(ip):
            return Sonda(gostitelj=g, razlog="zasebni_naslov")
        ostane = rok_ms / 1000.0 - (ura() - zacetek)
        if ostane <= 0:
            return Sonda(potekel=True, gostitelj=g, razlog="rok")
        try:
            if glave and g == izvorni:
                koda, lokacija, bajti, odgovor = zahteva_fn(naslov, g, ip, vrata, ostane, glave=glave)
            else:
                koda, lokacija, bajti, odgovor = zahteva_fn(naslov, g, ip, vrata, ostane)
        except (socket.timeout, TimeoutError):
            return Sonda(potekel=True, gostitelj=g, razlog="rok")
        except (OSError, http.client.HTTPException, ValueError):
            if rok_ms / 1000.0 - (ura() - zacetek) <= 0:
                return Sonda(potekel=True, gostitelj=g, razlog="rok")
            return Sonda(gostitelj=g, razlog="omrezje")
        if 300 <= koda <= 399:
            if not lokacija:
                return Sonda(koda=koda, gostitelj=g, razlog="preusmeritev")
            if skok >= NAJVEC_PREUSMERITEV:
                return Sonda(koda=koda, gostitelj=g, razlog="preusmeritve")
            try:
                naslov = urllib.parse.urljoin(naslov, str(lokacija).strip())
            except ValueError:
                return Sonda(koda=koda, gostitelj=g, razlog="naslov")
            continue
        if not 200 <= koda <= 299 or not bajti:
            return Sonda(koda=koda, gostitelj=g)
        ms = int((ura() - zacetek) * 1000)
        if not preveri_vsebino:
            return Sonda(koda=koda, prvi_bajt_ms=ms, gostitelj=g, koncni=naslov)
        try:
            dolzina = int(str(odgovor.get("content-length") or "-1").strip())
        except ValueError:
            dolzina = -1
        skupaj = skupna_velikost(koda, odgovor.get("content-range"), dolzina)
        vsebina, vrsta, kodek = pregled(odgovor.get("content-type"), bajti, skupaj, pricakovano_gb, kodek_podprt)
        if vsebina == VIDEO and je_video_ime(urllib.parse.unquote(urllib.parse.urlsplit(naslov).path)) is False:
            vsebina = NI_VIDEO                  # koncna datoteka je po imenu slika, glasba ali vzorec
        if vsebina != VIDEO:
            return Sonda(koda=koda, prvi_bajt_ms=ms, gostitelj=g, razlog="vsebina", vsebina=vsebina, posoda=vrsta,
                         kodek=kodek)
        return Sonda(koda=koda, prvi_bajt_ms=ms, gostitelj=g, koncni=naslov, vsebina=vsebina, posoda=vrsta, kodek=kodek)
    return Sonda(gostitelj=g, razlog="preusmeritve")


def oznaka_toka(tok: dict) -> tuple:
    """(vrsta, ime) toka dodatka Webtor iz imena, ki ga je dal dodatek (polje `vir` je prva vrstica imena)."""
    return razcleni(str(tok.get("vir") or ""))


def opis_za_dnevnik(s: Sonda) -> str:
    """Brez naslova in zetona: samo izid, koda, gostitelj in cas."""
    return json.dumps({"izid": s.izid, "koda": s.koda, "gostitelj": s.gostitelj, "ms": s.prvi_bajt_ms,
                       "razlog": s.razlog, "vsebina": s.vsebina, "posoda": s.posoda, "kodek": s.kodek}, ensure_ascii=False)
