"""Zakon solidarnosti, korak 5 na racunalniku: sprotno pretvarjanje za napravo, ki videa ne zna predvajati.

Naprava (televizor s Full HD dekodirnikom, telefon brez AV1 ...) poslje `video.stream` {url, fp?, token?, name,
mime?, width?, height?, seek_ms?, duration_ms?, size?}. Racunalnik izvirnik bere sproti (pripeto TLS s
potrdilom naprave ali racunalnika, ki video deli), ga s ffmpeg pretvori v H.264/AAC (strojno VAAPI, sicer
x264) v fragmentiran MP4, ki raste v predpomnilniku, in ga streze na `/live/<id>` streznika datotek
(link_datoteke): {id, url, fp, token}. Ko ga nihce ne bere vec ali ko bi zmanjkalo prostora, se ustavi.
`video.stream_stop` {id} ustavi takoj. Isti protokol kot Pretok.kt na Androidu. (link_pretok.py je nekaj drugega:
krajevni posrednik za predvajanje datotek z drugih naprav v lokalnem predvajalniku.)

ffmpeg izvirnika ne bere sam (pripetega potrdila ne zna preveriti): bere ga prek krajevnega posrednika
(127.0.0.1, skrivna pot, `Range` gre naprej), ki edini govori s pripetim virom.
"""
from __future__ import annotations

import http.client
import http.server
import os
import secrets
import shutil
import subprocess
import threading
import time
import urllib.parse
import uuid
from typing import Callable, Dict, List, Optional

MB = 1024 * 1024
VISINA = 1080
BREZ_BRALCA_S = 60.0
NAJVEC_TOKOV = 8
VELIKOST_KOSA = 256 * 1024


class NapakaPretoka(Exception):
    """Kratka koda za napravo (napacna_zahteva, ni_ffmpeg, preobremenjen, ni_prostora, napaka)."""


WINDOWS = os.name == "nt"


def mapa_predpomnilnika() -> str:
    if WINDOWS:
        return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "SafeerOS", "pretok")
    return os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "safeer-control", "pretok")


def _disk(mapa: str):
    """(skupaj, prosto) diska, na katerem je mapa (ali njen prvi obstojeci nadrejeni)."""
    pot = mapa
    while pot and not os.path.exists(pot):
        nad = os.path.dirname(pot)
        if nad == pot:
            break
        pot = nad
    u = shutil.disk_usage(pot or os.sep)
    return u.total, u.free


def rezerva(mapa: str) -> int:
    """Prostor, ki ga racunalnik vedno obdrzi zase: 10 % diska, 512 MB-2 GB (kot Pretvorba na Androidu)."""
    try:
        skupaj, _ = _disk(mapa)
        return max(512 * MB, min(2048 * MB, skupaj // 10))
    except OSError:
        return 2048 * MB


def prosto(mapa: str) -> int:
    try:
        return _disk(mapa)[1]
    except OSError:
        return -1


def ffmpeg_windows() -> str:
    """ffmpeg.exe na Windows: paket Safeer OS (LOCALAPPDATA/SafeerOS/ffmpeg, ffmpeg_win.py), winget, C:/ffmpeg."""
    import glob
    lokalno = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    kandidati = [os.path.join(lokalno, "SafeerOS", "ffmpeg", "bin", "ffmpeg.exe"),
                 os.path.join(lokalno, "Microsoft", "WinGet", "Links", "ffmpeg.exe"),
                 os.path.join("C:\\", "ffmpeg", "bin", "ffmpeg.exe")]
    kandidati += glob.glob(os.path.join(lokalno, "Microsoft", "WinGet", "Packages", "*FFmpeg*", "*", "bin", "ffmpeg.exe"))
    for k in kandidati:
        if os.path.isfile(k):
            return k
    return ""


#: Strojni kodirniki H.264, ki jih na Windows preizkusimo (nvenc/amf delujeta zanesljivo; QSV in MF "hw_encoding" na
#: starih Intelovih gonilnikih dajeta pokvarjen izhod ali napako - preizkus 2. 10. 2026, i5-4590 + HD 4600).
STROJNI_WINDOWS = ("h264_nvenc", "h264_amf")


def bitna_hitrost(velikost: int, trajanje_ms: int, sirina: int, visina: int) -> int:
    """Bitna hitrost izhoda (b/s) kot Pretvorba.bitnaHitrost: izvirnik x 1,6, 2-8 Mb/s pri 1080p; 0 = neznano."""
    if velikost <= 0 or trajanje_ms <= 0:
        return 0
    vir = velikost * 8000.0 / trajanje_ms
    izhod_visina = VISINA if visina > VISINA else max(1, visina)
    izhod_sirina = sirina * VISINA / visina if (visina > VISINA and sirina > 0) else max(1.0, float(sirina))
    delez = min(1.0, max(0.1, (izhod_sirina * izhod_visina) / (1920.0 * 1080.0)))
    return int(min(8_000_000.0 * delez, max(2_000_000.0 * delez, vir * 1.6)))


# ----------------------------------------------------------------------------- krajevni posrednik vira

def glave_zahteve(o) -> dict:
    """Glave zahteve za izvirnik, kot jih poslje naprava (Stremio proxyHeaders): najvec 16, brez prelomov vrstic,
    brez Range/Host/Content-Length (te doloca posrednik)."""
    if not isinstance(o, dict):
        return {}
    glave = {}
    for k, v in o.items():
        k, v = str(k or ""), str(v if v is not None else "")
        if not k or len(k) > 64 or len(v) > 2048 or any(c < " " for c in k) or "\r" in v or "\n" in v:
            continue
        if k.lower() in ("range", "host", "content-length"):
            continue
        glave[k] = v
        if len(glave) >= 16:
            break
    return glave


class _Vir:
    """Izvirnik: pripeto HTTPS (odtis + zeton) ali navaden HTTP; vsaka zahteva nova povezava (Range gre naprej)."""

    def __init__(self, url: str, odtis: str, zeton: str, glave: Optional[dict] = None) -> None:
        self.url = url
        self.odtis = odtis
        self.zeton = zeton
        #: Glave zahteve za izvirnik (Stremio behaviorHints.proxyHeaders): brez njih streznik toka vrne 403.
        self.glave = dict(glave or {})

    def povezava(self) -> http.client.HTTPConnection:
        u = urllib.parse.urlparse(self.url)
        if u.scheme == "https":
            from core import link_tls
            if self.odtis:
                return link_tls._PripetaHttps(u.hostname or "", u.port or 443, self.odtis, 30.0)
            return http.client.HTTPSConnection(u.hostname or "", u.port or 443, timeout=30.0)
        return http.client.HTTPConnection(u.hostname or "127.0.0.1", u.port or 80, timeout=30.0)

    def pot(self) -> str:
        u = urllib.parse.urlparse(self.url)
        return (u.path or "/") + ("?" + u.query if u.query else "")


class _Posrednik(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # noqa: D401
        return

    def do_HEAD(self):  # noqa: N802
        self._naprej(True)

    def do_GET(self):  # noqa: N802
        self._naprej(False)

    def _naprej(self, samo_glava: bool) -> None:
        sprotno: Sprotno = self.server.sprotno  # type: ignore[attr-defined]
        vir = sprotno.vir_za(self.path.split("?")[0].strip("/"))
        if vir is None:
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers()
            return
        glave = {"User-Agent": "Safeer Control"}
        glave.update(vir.glave)                      # glave toka (tudi svoj User-Agent) imajo prednost
        if vir.zeton:
            glave["X-Safeer-Token"] = vir.zeton
        if self.headers.get("Range"):
            glave["Range"] = self.headers["Range"]
        p = None
        try:
            p = vir.povezava()
            p.request("HEAD" if samo_glava else "GET", vir.pot(), headers=glave)
            r = p.getresponse()
            self.send_response(r.status)
            for ime in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
                if r.getheader(ime):
                    self.send_header(ime, r.getheader(ime))
            self.send_header("Connection", "close")
            self.end_headers()
            if samo_glava:
                return
            while True:
                kos = r.read(VELIKOST_KOSA)
                if not kos:
                    break
                self.wfile.write(kos)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            if p is not None:
                try:
                    p.close()
                except Exception:  # noqa: BLE001
                    pass


class _PosrednikStreznik(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


# ----------------------------------------------------------------------------- tok

class Tok:
    def __init__(self, ime: str, datoteka: str) -> None:
        self.id = str(uuid.uuid4())
        self.ime = ime
        self.datoteka = datoteka
        self.skrivnost = secrets.token_urlsafe(18)
        self.proces: Optional[subprocess.Popen] = None
        self.koncano = False
        self.napaka = ""
        self.zadnji_bralec = time.time()
        self.bralcev = 0
        self.zacetek = time.time()
        self.strojno = False
        self.kljucavnica = threading.Lock()

    def json(self) -> dict:
        return {"id": self.id, "name": self.ime, "done": self.koncano, "error": self.napaka,
                "bytes": os.path.getsize(self.datoteka) if os.path.exists(self.datoteka) else 0,
                "readers": self.bralcev, "hw": self.strojno}


class Sprotno:
    """Vsi sprotni tokovi tega racunalnika (en pretvornik naenkrat) in krajevni posrednik za ffmpeg."""

    def __init__(self, mapa: Optional[str] = None, ffmpeg: Optional[str] = None,
                 vaapi: Optional[Callable[[], Optional[str]]] = None,
                 strojni: Optional[Callable[[], Optional[str]]] = None) -> None:
        self.mapa = mapa or mapa_predpomnilnika()
        self._ffmpeg = ffmpeg
        self._vaapi = vaapi
        self._strojni = strojni          # Windows: ime strojnega kodirnika (h264_nvenc/h264_amf) ali None; preizkus se predpomni
        self._strojni_predpomnjen: Optional[str] = None
        self._strojni_preizkusen_za = ""
        self.tokovi: Dict[str, Tok] = {}
        self._viri: Dict[str, _Vir] = {}
        self._kljucavnica = threading.Lock()
        self._posrednik: Optional[_PosrednikStreznik] = None
        self._straza_tece = False

    # ---- orodja

    def ffmpeg(self) -> str:
        pot = self._ffmpeg or shutil.which("ffmpeg") or (ffmpeg_windows() if WINDOWS else "") or ""
        return pot if pot and os.path.isfile(pot) else ""

    def ffprobe(self) -> str:
        f = self.ffmpeg()
        ob = os.path.join(os.path.dirname(f), "ffprobe.exe" if WINDOWS else "ffprobe") if f else ""
        return ob if ob and os.path.isfile(ob) else (shutil.which("ffprobe") or ob)

    def programski_kodirnik(self) -> str:
        """Kodirnik brez posebne strojne opreme: x264 (Linux) ali Media Foundation (Windows, v sistemu)."""
        return "h264_mf" if WINDOWS else "libx264"

    def strojni_kodirnik(self) -> Optional[str]:
        """Windows: prvi od STROJNI_WINDOWS, ki dejansko kodira (kratek preizkus z lavfi; rezultat se predpomni za ta
        ffmpeg). Linux: None (strojno je VAAPI, glej vaapi())."""
        if self._strojni is not None:
            return self._strojni()
        if not WINDOWS:
            return None
        f = self.ffmpeg()
        if not f:
            return None
        if self._strojni_preizkusen_za == f:
            return self._strojni_predpomnjen
        najden = None
        for k in STROJNI_WINDOWS:
            try:
                r = subprocess.run([f, "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                                    "color=c=black:s=64x64:r=5", "-frames:v", "3", "-c:v", k, "-f", "null", "-"],
                                   capture_output=True, timeout=25, creationflags=_BREZ_OKNA)
            except (OSError, subprocess.TimeoutExpired):
                continue
            if r.returncode == 0:
                najden = k
                break
        self._strojni_predpomnjen, self._strojni_preizkusen_za = najden, f
        _zapisi(f"sprotno: strojni kodirnik {najden or 'ni'} (ffmpeg {f})")
        return najden

    def vaapi(self) -> Optional[str]:
        """Naprava za strojno kodiranje (Intel/AMD, kot link_zaslon.vaapi_naprava - brez uvoza, ker paket Safeer OS link_zaslon nima)."""
        if self._vaapi is not None:
            return self._vaapi()
        for ime in ("renderD128", "renderD129"):
            pot = os.path.join("/dev/dri", ime)
            if os.path.exists(pot):
                return pot
        return None

    def kodirniki(self) -> dict:
        """Za host.info: {strojno, kodirniki:[{vrsta, sirina, visina}], dekodirniki:[...]} ali {} brez ffmpeg."""
        if not self.ffmpeg():
            return {}
        strojno = bool(self.vaapi()) if not WINDOWS else bool(self.strojni_kodirnik())
        return {"strojno": strojno, "ffmpeg": True,
                "kodirniki": [{"vrsta": "avc", "sirina": 4096, "visina": 2304}],
                "dekodirniki": [{"vrsta": v, "sirina": 8192, "visina": 4320}
                                for v in ("avc", "hevc", "vp9", "vp8", "av1", "mpeg4", "mpeg2video", "h263")]}

    # ---- posrednik

    def _zazeni_posrednik(self) -> int:
        with self._kljucavnica:
            if self._posrednik is None:
                s = _PosrednikStreznik(("127.0.0.1", 0), _Posrednik)
                s.sprotno = self  # type: ignore[attr-defined]
                threading.Thread(target=s.serve_forever, name="safeer-pretok-posrednik", daemon=True).start()
                self._posrednik = s
            return self._posrednik.server_address[1]

    def vir_za(self, skrivnost: str) -> Optional[_Vir]:
        with self._kljucavnica:
            for k, v in self._viri.items():
                if secrets.compare_digest(k, skrivnost):
                    return v
        return None

    # ---- ukazi

    def zacni(self, p: dict, posiljatelj: str, streznik) -> dict:
        """`video.stream` -> {id, url, fp, token}; `streznik` je link_datoteke.StreznikDatotek (zazenemo ga, ce ne tece)."""
        url = str(p.get("url") or "")
        odtis = str(p.get("fp") or "")
        zeton = str(p.get("token") or "")
        ime = os.path.basename(str(p.get("name") or "")).strip()[:120] or "video"
        glave = glave_zahteve(p.get("headers"))
        if not (url.startswith("https://") or url.startswith("http://")):
            raise NapakaPretoka("napacna_zahteva")
        if odtis and len(odtis) != 64:
            raise NapakaPretoka("napacna_zahteva")
        if not self.ffmpeg():
            raise NapakaPretoka("ni_ffmpeg")
        trajanje_ms = int(p.get("duration_ms") or 0)
        velikost = int(p.get("size") or 0)
        sirina = int(p.get("width") or 0)
        visina = int(p.get("height") or 0)
        seek_ms = max(0, int(p.get("seek_ms") or 0))
        os.makedirs(self.mapa, exist_ok=True)
        # En tok naenkrat: drugi bi oba zatikala. Tok, ki ga nihce ne bere vec, umaknemo.
        with self._kljucavnica:
            zivi = [t for t in self.tokovi.values() if not t.koncano and not t.napaka]
        for t in zivi:
            if time.time() - t.zadnji_bralec < BREZ_BRALCA_S:
                raise NapakaPretoka("preobremenjen")
            self.ustavi(t)
        # Prostor: ocena izhoda (najvec 8 Mb/s) + rezerva racunalnika.
        ocena = (8_000_000 // 8) * max(0, trajanje_ms - seek_ms) // 1000 * 12 // 10
        pr = prosto(self.mapa)
        if 0 <= pr < ocena + rezerva(self.mapa):
            raise NapakaPretoka("ni_prostora")
        for f in os.listdir(self.mapa):
            pot = os.path.join(self.mapa, f)
            if all(t.datoteka != pot for t in self.tokovi.values()):
                try:
                    os.remove(pot)
                except OSError:
                    pass
        t = Tok(ime, os.path.join(self.mapa, uuid.uuid4().hex + ".mp4"))
        vrata = self._zazeni_posrednik()
        with self._kljucavnica:
            self._viri[t.skrivnost] = _Vir(url, odtis, zeton, glave)
            self.tokovi[t.id] = t
            while len(self.tokovi) > NAJVEC_TOKOV:
                star = next(iter(self.tokovi))
                self.ustavi(self.tokovi.pop(star))
        streznik.sprotno = self   # streznik datotek streze /live/<id> iz tega Sprotno (v testih svoj primerek)
        streznik.zazeni()
        from core.link_datoteke import krajevni_naslov
        osnova = streznik.osnova(krajevni_naslov())
        bitna = bitna_hitrost(velikost, trajanje_ms, sirina, visina)
        threading.Thread(target=self._pretvarjaj, args=(t, f"http://127.0.0.1:{vrata}/{t.skrivnost}", seek_ms, bitna, visina,
                                                         max(0, trajanje_ms - seek_ms)),
                         name="safeer-pretok", daemon=True).start()
        self._zazeni_strazo()
        return {"id": t.id, "url": f"{osnova}/live/{t.id}", "fp": streznik.odtis, "token": streznik.zeton_za(posiljatelj or "naprava")}

    def ustavi_ukaz(self, id_toka: str) -> bool:
        with self._kljucavnica:
            t = self.tokovi.pop(str(id_toka or ""), None)
        if t is None:
            return False
        self.ustavi(t)
        return True

    def stanje(self, id_toka: str) -> Optional[dict]:
        t = self.tokovi.get(str(id_toka or ""))
        return t.json() if t else None

    def ustavi(self, t: Tok) -> None:
        t.koncano = True
        pr = t.proces
        if pr is not None and pr.poll() is None:
            try:
                pr.terminate()
                try:
                    pr.wait(3)
                except subprocess.TimeoutExpired:
                    pr.kill()
            except OSError:
                pass
        with self._kljucavnica:
            self._viri.pop(t.skrivnost, None)
        if t.bralcev == 0:
            try:
                os.remove(t.datoteka)
            except OSError:
                pass

    # ---- ffmpeg

    def ukaz(self, vhod: str, izhod: str, seek_ms: int, bitna: int, visina_vira: int, vaapi: Optional[str],
             kodirnik: str = "") -> List[str]:
        """Ukaz ffmpeg: strojno (VAAPI dekodiranje + kodiranje, CQP - edini nacin na Intelovem LP vhodu; na Windows
        h264_nvenc/h264_amf) ali programsko (x264; na Windows Media Foundation h264_mf, ki je v sistemu).
        Najvec 1080p, manjsega ne povecujemo; fragmentiran MP4 (2 s), da ga naprava bere sproti."""
        u = [self.ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
        if seek_ms > 0:
            u += ["-ss", f"{seek_ms / 1000:.3f}"]
        lestvica = visina_vira <= 0 or visina_vira > VISINA
        kodirnik = kodirnik or self.programski_kodirnik()
        if vaapi:
            u += ["-hwaccel", "vaapi", "-hwaccel_device", vaapi, "-hwaccel_output_format", "vaapi", "-i", vhod]
            u += ["-vf", (f"scale_vaapi=w=-2:h={VISINA}:format=nv12" if lestvica else "scale_vaapi=format=nv12")]
            u += ["-c:v", "h264_vaapi", "-rc_mode", "CQP", "-qp", "23", "-profile:v", "high"]
        else:
            u += ["-i", vhod]
            if lestvica:
                u += ["-vf", f"scale=-2:'min(ih,{VISINA})'"]
            # Brez podatka o izvirniku: 5 Mb/s pri 1080p, 3 Mb/s pri 720p, 2 Mb/s manj (kot bitna_hitrost zgoraj).
            privzeta = 5_000_000 if (visina_vira <= 0 or visina_vira >= 1080) else (3_000_000 if visina_vira >= 720 else 2_000_000)
            if kodirnik == "libx264":
                u += ["-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high", "-pix_fmt", "yuv420p"]
                if bitna > 0:
                    u += ["-b:v", str(bitna), "-maxrate", str(int(bitna * 1.5)), "-bufsize", str(bitna * 2)]
                else:
                    u += ["-crf", "22"]
            elif kodirnik == "h264_nvenc":
                u += ["-c:v", "h264_nvenc", "-preset", "p4", "-profile:v", "high", "-pix_fmt", "yuv420p"]
                u += (["-rc", "vbr", "-b:v", str(bitna), "-maxrate", str(int(bitna * 1.5)), "-bufsize", str(bitna * 2)]
                      if bitna > 0 else ["-rc", "vbr", "-cq", "23", "-b:v", "0"])
            elif kodirnik == "h264_amf":
                u += ["-c:v", "h264_amf", "-quality", "speed", "-profile:v", "high", "-pix_fmt", "yuv420p"]
                u += (["-rc", "vbr_peak", "-b:v", str(bitna), "-maxrate", str(int(bitna * 1.5))]
                      if bitna > 0 else ["-rc", "cqp", "-qp_i", "23", "-qp_p", "23"])
            else:
                # Media Foundation (Windows): programski kodirnik sistema; strojnega (hw_encoding) ne uporabljamo.
                u += ["-c:v", "h264_mf", "-rate_control", "cbr", "-b:v", str(bitna if bitna > 0 else privzeta),
                      "-pix_fmt", "nv12"]
        u += ["-c:a", "aac", "-b:a", "160k", "-ac", "2", "-sn", "-dn", "-map", "0:v:0", "-map", "0:a:0?",
              "-f", "mp4", "-movflags", "frag_keyframe+empty_moov+default_base_moof", "-frag_duration", "2000000", izhod]
        return u

    def _cel(self, datoteka: str, velikost: int, pricakovano_ms: int) -> bool:
        if velikost <= MB:
            return False
        if pricakovano_ms <= 0:
            return True
        ffprobe = self.ffprobe()
        try:
            izpis = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", datoteka],
                                   capture_output=True, text=True, timeout=15, creationflags=_BREZ_OKNA).stdout.strip()
            return float(izpis) * 1000 >= pricakovano_ms * 0.95
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return False

    def _pretvarjaj(self, t: Tok, vhod: str, seek_ms: int, bitna: int, visina_vira: int, pricakovano_ms: int = 0) -> None:
        # Poskusi: (vaapi naprava, ime kodirnika) - najprej strojno, nato programsko.
        if WINDOWS:
            strojni = self.strojni_kodirnik()
            poskusi = ([(None, strojni)] if strojni else []) + [(None, self.programski_kodirnik())]
        else:
            vaapi = self.vaapi()
            poskusi = ([(vaapi, "h264_vaapi")] if vaapi else []) + [(None, self.programski_kodirnik())]
        for naprava, kodirnik in poskusi:
            if t.koncano:
                return
            t.strojno = naprava is not None or kodirnik in STROJNI_WINDOWS
            try:
                t.proces = subprocess.Popen(self.ukaz(vhod, t.datoteka, seek_ms, bitna, visina_vira, naprava, kodirnik),
                                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=_BREZ_OKNA)
            except OSError as e:
                t.napaka = "napaka"; t.koncano = True
                _zapisi(f"pretok {t.ime}: ffmpeg se ni zagnal ({e})")
                return
            _, err = t.proces.communicate()
            koda = t.proces.returncode
            velikost = os.path.getsize(t.datoteka) if os.path.exists(t.datoteka) else 0
            if t.koncano:
                return
            # VAAPI ob koncu vira javi "Cannot allocate memory" (koda 244), ceprav je izhod cel: izhod stejemo za
            # uspeh, ce je dolg vsaj 95 % pricakovanega (ffprobe) ali - brez podatka o trajanju - vecji od 1 MB.
            if koda == 0 or self._cel(t.datoteka, velikost, pricakovano_ms):
                _zapisi(f"pretok {t.ime}: koncan ({velikost} B, {kodirnik}, koda {koda})")
                t.koncano = True
                return
            _zapisi(f"pretok {t.ime}: {kodirnik} ni uspel (koda {koda}): {(err or b'').decode('utf-8', 'replace').strip()[:300]}")
            try:
                os.remove(t.datoteka)
            except OSError:
                pass
        t.napaka = "napaka"
        t.koncano = True

    # ---- strezba /live/<id> (klice link_datoteke)

    def postrezi(self, obravnava, id_toka: str, samo_glava: bool) -> None:
        t = self.tokovi.get(str(id_toka or ""))
        if t is None:
            telo = b"ni takega toka"
            obravnava.send_response(404); obravnava.send_header("Content-Type", "text/plain")
            obravnava.send_header("Content-Length", str(len(telo))); obravnava.end_headers(); obravnava.wfile.write(telo)
            return
        obravnava.send_response(200)
        obravnava.send_header("Content-Type", "video/mp4")
        obravnava.send_header("Transfer-Encoding", "chunked")
        obravnava.send_header("Cache-Control", "no-store")
        obravnava.send_header("Connection", "close")
        obravnava.end_headers()
        if samo_glava:
            return
        with t.kljucavnica:
            t.bralcev += 1
        poslano = 0
        cakam = 0
        try:
            while True:
                t.zadnji_bralec = time.time()
                dolzina = os.path.getsize(t.datoteka) if os.path.exists(t.datoteka) else 0
                if dolzina > poslano:
                    with open(t.datoteka, "rb") as d:
                        d.seek(poslano)
                        while poslano < dolzina:
                            kos = d.read(min(VELIKOST_KOSA, dolzina - poslano))
                            if not kos:
                                break
                            obravnava.wfile.write(b"%x\r\n" % len(kos) + kos + b"\r\n")
                            poslano += len(kos)
                    obravnava.wfile.flush()
                    cakam = 0
                    continue
                if t.koncano:
                    break
                cakam += 1
                if cakam > 600:   # 60 s brez novih podatkov: pretvornik je obstal
                    break
                time.sleep(0.1)
            obravnava.wfile.write(b"0\r\n\r\n")
            obravnava.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with t.kljucavnica:
                t.bralcev -= 1
            t.zadnji_bralec = time.time()
            if t.koncano and t.bralcev == 0 and t.napaka:
                try:
                    os.remove(t.datoteka)
                except OSError:
                    pass

    # ---- straza

    def _zazeni_strazo(self) -> None:
        with self._kljucavnica:
            if self._straza_tece:
                return
            self._straza_tece = True
        threading.Thread(target=self._straza, name="safeer-pretok-straza", daemon=True).start()

    def _straza(self) -> None:
        while True:
            time.sleep(5)
            with self._kljucavnica:
                tokovi = list(self.tokovi.values())
            if not any(not t.koncano for t in tokovi):
                with self._kljucavnica:
                    self._straza_tece = False
                return
            for t in tokovi:
                if t.koncano:
                    continue
                if t.bralcev == 0 and time.time() - t.zadnji_bralec > BREZ_BRALCA_S:
                    _zapisi(f"pretok {t.ime}: nihce ga ne bere, ustavljam")
                    self.ustavi(t)
                elif 0 <= prosto(self.mapa) < rezerva(self.mapa):
                    _zapisi(f"pretok {t.ime}: zmanjkalo prostora, ustavljam")
                    t.napaka = "ni_prostora"
                    self.ustavi(t)


#: Podprocesi na Windows brez konzolnega okna (CREATE_NO_WINDOW); drugje 0.
_BREZ_OKNA = 0x08000000 if WINDOWS else 0


def _zapisi(besedilo: str) -> None:
    try:
        from core import os_stabilnost
        os_stabilnost.zapisi("safeer-control", besedilo)
    except Exception:  # noqa: BLE001
        pass
    if WINDOWS:
        try:
            print("[SafeerSprotno] " + besedilo, flush=True)
        except Exception:  # noqa: BLE001
            pass


_SPROTNO: Optional[Sprotno] = None
_SPROTNO_KLJUC = threading.Lock()


def sprotno() -> Sprotno:
    """En Sprotno na proces (Control)."""
    global _SPROTNO
    with _SPROTNO_KLJUC:
        if _SPROTNO is None:
            _SPROTNO = Sprotno()
        return _SPROTNO
