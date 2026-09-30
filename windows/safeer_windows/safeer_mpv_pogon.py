"""Safeer mpv pogon — vzporedni predvajalni motor na libmpv (LGPL gradnja).

Ima ISTI javni API kot safeer_qt_pogon.SafeerQtPogon, da ju je mogoce primerjati v
istem vmesniku (dodaj/predvajaj/premor/skok, glasnost, utisaj, hitrost, steze,
nastavi_zvok, nastavi_podnapis, nalozi_podnapis, ponovi, nakljucno, naslednja/
prejsnja, podatki, posnetek). Podnapise praviloma izrisuje mpv sam (sid/sub-add);
lasten prekrivnik ostane le za posebne potrebe.

Video se vgradi prek rocaja okna (wid) — na Windows ustvari podrejeno okno; fokus,
prekrivniki in celozaslon je treba preveriti v zivem prototipu. libmpv NI priloten
v tem modulu: knjiznica mora biti na voljo (uradni paket jo mora vsebovati, sicer
je to napaka pakiranja, ki jo mora ujeti test).

MSVC runtime (pravilo 6): paket libmpv prilaga runtime/ (msvcp140, vcruntime140, vcruntime140_1)
iz iste orodjarne. Aplikacija naj poklice predpripravi_runtime() PRED uvozom PySide6, da se v
proces nalozi runtime iz paketa (novejsi je zdruzljiv s Qt); ce je v procesu ze starejsi
msvcp140 od zahtevanega (manifest.json -> runtime), libmpv_na_voljo() vrne False z razlogom
v STANJE["napaka"] in aplikacija ostane na Qt pogonu — namesto sesutja v MSVCP140.dll.
"""
from __future__ import annotations

import json
import logging
import os
import struct
import sys
import threading
from typing import Optional

PONOVI_BREZ, PONOVI_ENA, PONOVI_VSE = "brez", "ena", "vse"
_DOVOLJENE_PRIPONE_PODNAPISOV = (".srt", ".vtt", ".ass", ".ssa", ".sub")


# Diagnoza izbire pogona (pravilo: izbrani pogon in runtime morata biti razvidna iz dnevnika).
STANJE: dict = {"mapa": None, "runtime": {}, "msvcp140": None, "msvcp140_razlicica": None,
                "zahtevana_razlicica": None, "napaka": None}
_log = logging.getLogger("safeer.mpv")
_pripravljeno = False


def libmpv_na_voljo() -> bool:
    """True, ce je mogoce uvoziti python-mpv in nalozi libmpv. Ne ustvari predvajalnika.

    Ce je MSVC runtime v procesu starejsi od tistega, s katerim je bil libmpv zgrajen
    (manifest.json -> runtime), vrne False Z RAZLOGOM v STANJE['napaka'] — namesto sesutja
    v MSVCP140.dll (videno 2026-09-30 s sistemskim 14.32).
    """
    try:
        _pripravi_pot()
        import mpv  # noqa: F401
        if os.name == "nt" and not STANJE["msvcp140"]:
            STANJE["msvcp140"] = _nalozena_pot("msvcp140.dll")
            if STANJE["msvcp140"]:
                STANJE["msvcp140_razlicica"] = _razlicica_datoteke(STANJE["msvcp140"])
            _log.info("po uvozu mpv: msvcp140=%s razlicica=%s", STANJE["msvcp140"], STANJE["msvcp140_razlicica"])
        return True
    except Exception as e:  # pragma: no cover - odvisno od okolja
        STANJE["napaka"] = repr(e)
        _log.warning("libmpv ni na voljo: %s", e)
        return False


def _razlicica_datoteke(pot: str) -> Optional[tuple]:
    """FileVersion (a, b, c, d) iz PE vira; None, ce ni na voljo."""
    try:
        import ctypes
        from ctypes import wintypes
        ver = ctypes.WinDLL("version")
        size = ver.GetFileVersionInfoSizeW(pot, None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(pot, 0, size, buf):
            return None
        ptr = ctypes.c_void_p(); ln = wintypes.UINT()
        if not ver.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(ln)):
            return None
        raw = ctypes.string_at(ptr.value, ln.value)
        ms, ls = struct.unpack_from("<II", raw, 8)
        return (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)
    except Exception:
        return None


def _nalozena_pot(ime: str) -> Optional[str]:
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetModuleHandleW.restype = wintypes.HMODULE
        k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        h = k32.GetModuleHandleW(ime)
        if not h:
            return None
        buf = ctypes.create_unicode_buffer(1024)
        k32.GetModuleFileNameW(wintypes.HMODULE(h), buf, 1024)
        return buf.value
    except Exception:
        return None


def _pripravi_runtime(d: str) -> None:
    """App-local MSVC runtime: <d>/runtime/{msvcp140,vcruntime140,vcruntime140_1}.dll.

    Nalozi le tiste, ki jih v procesu se ni (dvojna kopija iste knjiznice bi bila napaka).
    Nato preveri, da je msvcp140 v procesu vsaj razlicice iz manifest.json (runtime.msvcp140.dll);
    ce je starejsi (npr. sistemski 14.32), dvigne RuntimeError -> nadzorovan preklop na Qt pogon.
    """
    import ctypes
    rt = os.path.join(d, "runtime")
    for ime in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"):
        if _nalozena_pot(ime):
            STANJE["runtime"][ime] = "ze-nalozen"
            continue
        pot = os.path.join(rt, ime)
        if os.path.isfile(pot):
            ctypes.WinDLL(pot)
            STANJE["runtime"][ime] = "nalozen:" + pot
        else:
            STANJE["runtime"][ime] = "ni-v-runtime"
    zahtevana = None
    manifest = os.path.join(d, "manifest.json")
    if os.path.isfile(manifest):
        try:
            with open(manifest, encoding="utf-8-sig") as f:
                r = json.load(f).get("runtime") or {}
            v = r.get("msvcp140.dll")
            if v:
                zahtevana = tuple(int(x) for x in v.split(".")[:4])
        except Exception:
            zahtevana = None
    STANJE["zahtevana_razlicica"] = zahtevana
    if not _nalozena_pot("msvcp140.dll"):
        pot = os.path.join(rt, "msvcp140.dll")
        if os.path.isfile(pot):
            ctypes.WinDLL(pot)
    msvcp = _nalozena_pot("msvcp140.dll")
    STANJE["msvcp140"] = msvcp
    if msvcp:
        STANJE["msvcp140_razlicica"] = _razlicica_datoteke(msvcp)
    if zahtevana and msvcp:
        imamo = STANJE["msvcp140_razlicica"]
        if imamo and imamo < zahtevana:
            raise RuntimeError(
                f"MSVC runtime prestar: msvcp140 {'.'.join(map(str, imamo))} ({msvcp}), "
                f"libmpv zahteva >= {'.'.join(map(str, zahtevana))}; runtime/ ni prilozen ali ni nalozen")
    _log.info("libmpv mapa=%s msvcp140=%s razlicica=%s zahtevana=%s runtime=%s",
              d, msvcp, STANJE["msvcp140_razlicica"], zahtevana, STANJE["runtime"])


def predpripravi_runtime() -> dict:
    """Javni vstop: najde libmpv, nalozi runtime iz paketa in vrne STANJE. Brez izjem."""
    try:
        _pripravi_pot()
    except Exception as e:
        STANJE["napaka"] = repr(e)
        _log.warning("predpriprava libmpv runtime ni uspela: %s", e)
    return STANJE


def _pripravi_pot() -> None:
    """Doda mapo z libmpv-2.dll na PATH (Windows), ce je prilozena ob aplikaciji, in poskrbi za runtime."""
    global _pripravljeno
    if os.name != "nt" or _pripravljeno:
        return
    tu = os.path.dirname(__file__)
    kandidati = [
        os.path.join(tu, "vendor", "mpv"),                       # ob modulu (izdaja)
        os.path.join(tu, "libmpv"),
        os.path.join(os.path.dirname(os.path.dirname(tu)), "vendor", "mpv"),   # koren aplikacije
        os.path.join(os.environ.get("USERPROFILE", ""), "Desktop", "vendor", "safeer-r1"),  # prototip r1
        os.path.join(os.environ.get("USERPROFILE", ""), "Desktop", "vendor", "mpv"),  # prototip
        os.path.join(os.environ.get("USERPROFILE", ""), "Desktop", "libmpv"),          # prototip (stari)
    ]
    for d in kandidati:
        if d and os.path.isfile(os.path.join(d, "libmpv-2.dll")):
            STANJE["mapa"] = d
            _pripravi_runtime(d)          # pred PATH/add_dll_directory: runtime mora biti v procesu prej
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            try:
                os.add_dll_directory(d)
            except Exception:
                pass
            _pripravljeno = True
            return
    _log.warning("libmpv-2.dll ni najden v nobeni od map: %s", kandidati)


_HWDEC_KODEKI_PRIVZETO = "h264,vc1,hevc,vp8,vp9,av1,prores"


def _ffmpeg_major(razlicica) -> Optional[int]:
    """'6.1.1-3ubuntu5' -> 6; None, ce ni razpoznavno."""
    try:
        return int(str(razlicica or "").strip().split(".")[0].split("-")[0])
    except Exception:
        return None


def hwdec_kodeki_za(ffmpeg_version, platforma: str = sys.platform) -> tuple[str, Optional[str]]:
    """Kateri kodeki smejo strojno dekodirati in zakaj je kaj izkljuceno (razlog za dnevnik).

    Znana napaka (potrjena 2026-09-30 tudi s samostojnim mpv 0.37): Linux, FFmpeg 6.x + VAAPI (Intel iHD 24.1)
    se pri AV1 sesuje v avcodec_send_packet. Dokler sistemski FFmpeg ni >= 7, gre AV1 programsko (dav1d);
    ostali kodeki ostanejo strojni. Na Windows (d3d11va) ni izkljucitev - preverja se posebej.
    """
    major = _ffmpeg_major(ffmpeg_version)
    if platforma.startswith("linux") and major is not None and major < 7:
        kodeki = ",".join(k for k in _HWDEC_KODEKI_PRIVZETO.split(",") if k != "av1")
        return kodeki, f"AV1 programsko (dav1d): FFmpeg {ffmpeg_version} + VAAPI AV1 se sesuje (avcodec_send_packet)"
    return _HWDEC_KODEKI_PRIVZETO, None


class SafeerMpvPogon:
    """Ovojnica okrog libmpv z istim API kot SafeerQtPogon."""
    HWDEC = os.environ.get("SAFEER_MPV_HWDEC", "auto")   # "no" za diagnostiko

    def __init__(self, sprememba=None, konec=None, napaka=None):
        _pripravi_pot()
        import mpv
        self._mpv_modul = mpv
        self._wid: Optional[int] = None
        self._cb_sprememba = sprememba
        self._cb_konec = konec
        self._cb_napaka = napaka
        self._seznam: list[dict] = []
        self._indeks: int = -1
        self._ponovi: str = PONOVI_BREZ
        self._nakljucno: bool = False
        self._glasnost: int = 80
        self._mpv = None
        self._zapiranje = False
        self._konec_cakajoc = False
        self._koncan_uri: str = ""
        # Nadaljuj tam, kjer si koncal: gostitelj nastavi `nadaljevanje(uri) -> sekunde` (0 = od zacetka)
        # in `ob_koncu_datoteke(uri)` (datoteka je bila predvajana do konca; polozaj se pozabi).
        self.nadaljevanje = None
        self.ob_koncu_datoteke = None
        self.zacel_pri: float = 0.0   # kje se je zacelo zadnje predvajanje (0 = od zacetka)
        self._kljuc = threading.RLock()   # scitil: podatki()/_sporoci (mpv nit) proti _unici (GUI nit)
        # Instanca se ustvari lazno: ob povezi_video(wid) ali ob prvem ukazu (vo=null, brez slike).
        # Tako ni uničevanja instance sredi opazovalnih klicev (segfault 2026-09-30 na Linuxu).

    # ---- ustvarjanje / video ----
    def _ustvari(self) -> None:
        mpv = self._mpv_modul
        # Samo splosno prisotne moznosti ob ustvarjanju; ostalo nastavimo obrambno spodaj,
        # ker LGPL gradnja nima skriptanja (npr. moznost "osc" ne obstaja).
        opts = dict(hwdec=self.HWDEC, keep_open="yes", idle="yes")
        if self._wid is not None:
            opts["vo"] = "gpu-next"
            opts["wid"] = str(int(self._wid))
        else:
            opts["vo"] = "null"
        self._zapiranje = False
        self._mpv = mpv.MPV(**opts)
        for k, v in (("input_default_bindings", "no"), ("input_vo_keyboard", "no"),
                     ("ao", "wasapi" if os.name == "nt" else None)):
            if v is None:
                continue
            try:
                setattr(self._mpv, k, v)
            except Exception:
                pass
        self._mpv.volume = self._glasnost
        try:
            kodeki, razlog = hwdec_kodeki_za(getattr(self._mpv, "ffmpeg_version", None))
            self._mpv.hwdec_codecs = kodeki
            STANJE["hwdec_codecs"] = kodeki
            if razlog:
                STANJE["hwdec_opomba"] = razlog
                _log.warning("hwdec: %s (hwdec-codecs=%s)", razlog, kodeki)
        except Exception as e:  # pragma: no cover
            _log.debug("hwdec-codecs: %s", e)

        @self._mpv.property_observer("time-pos")
        def _op(_n, _v):
            # mpv nit: NE beremo lastnosti tukaj (get_property iz tuje niti med menjavo datoteke/hwdec
            # se je na Linuxu sesul); le sporocimo GUI-ju, ki podatke prebere v svoji niti.
            if self._zapiranje or self._mpv is None:
                return
            if self._cb_sprememba:
                try:
                    self._cb_sprememba(None)
                except Exception:
                    pass

        @self._mpv.event_callback("end-file")
        def _ef(dogodek):
            if self._zapiranje or self._mpv is None:
                return
            try:
                razlog = dogodek.get("event", {}).get("reason", "")
            except Exception:
                razlog = ""
            if str(razlog) in ("eof", "EndFile.EOF", "0"):
                # mpv nit: samo oznacimo; GUI nit poklice obdelaj_konec() (prek sprememba-sporocila).
                vnos = self._seznam[self._indeks] if 0 <= self._indeks < len(self._seznam) else {}
                self._koncan_uri = vnos.get("uri", "")
                self._konec_cakajoc = True
                if self._cb_sprememba:
                    try:
                        self._cb_sprememba(None)
                    except Exception:
                        pass

    def povezi_video(self, wid: int) -> None:
        """Poda rocaj okna (winId). mpv se vzpostavi znova z gpu-next izrisom v to okno."""
        self._wid = int(wid)
        if self._mpv is not None:
            self._unici()
        self._ustvari()

    def _unici(self) -> None:
        """Ustavi opazovalce, nato unici instanco; klici iz mpv niti se prej prekinejo prek _zapiranje."""
        # Pod kljucem pocakamo, da se morebitni klic iz mpv niti konca, in oznacimo zapiranje;
        # terminate() (ki pridruzi mpv nit) je IZVEN kljuca, sicer bi bil mrtvi tek.
        with self._kljuc:
            m, self._mpv = self._mpv, None
            self._zapiranje = True
        if m is None:
            return
        try:
            m.command("stop")
        except Exception:
            pass
        try:
            m.terminate()
        except Exception:
            pass

    def _zagotovi(self):
        if self._mpv is None:
            self._ustvari()
        return self._mpv

    # ---- seznam / predvajanje ----
    def dodaj(self, uri: str, predvajaj: bool = False, vrsta: str = "medij", naslov: str = "") -> int:
        self._seznam.append({"uri": uri, "vrsta": vrsta, "naslov": naslov or _ime_iz_uri(uri)})
        i = len(self._seznam) - 1
        if predvajaj:
            self.predvajaj(i)
        else:
            self._sporoci()
        return i

    def zamenjaj_vrsto(self, vnosi: list[dict]) -> bool:
        self._seznam = [
            {"uri": v.get("uri", ""), "vrsta": v.get("vrsta", "medij"),
             "naslov": v.get("naslov") or _ime_iz_uri(v.get("uri", ""))}
            for v in (vnosi or []) if v.get("uri")
        ]
        self._indeks = -1
        self._sporoci()
        return True

    def nastavi_glave(self, referer: str = "", user_agent: str = "", glave: Optional[dict] = None) -> None:
        """Spletne glave za naslednje predvajanje (mpv jih pošlje sam — brez posrednika)."""
        try:
            if referer:
                self._zagotovi().referrer = referer
            if user_agent:
                self._zagotovi().user_agent = user_agent
            if glave:
                self._zagotovi().http_header_fields = [f"{k}: {v}" for k, v in glave.items()]
        except Exception:
            pass

    def predvajaj(self, indeks: int, zacetek: float = 0.0) -> bool:
        """[zacetek] > 0: predvajanje se zacne pri tem casu (nadaljuj tam, kjer si koncal)."""
        if not (0 <= indeks < len(self._seznam)):
            return False
        self._indeks = indeks
        uri = self._seznam[indeks]["uri"]
        if (not zacetek or zacetek <= 0) and self.nadaljevanje is not None:
            try:
                zacetek = float(self.nadaljevanje(uri) or 0.0)
            except Exception:
                zacetek = 0.0
        self.zacel_pri = float(zacetek) if zacetek and zacetek > 0 else 0.0
        try:
            m = self._zagotovi()
            try:
                m.start = ("%.2f" % float(zacetek)) if zacetek and zacetek > 0 else "none"
            except Exception:
                pass
            m.play(self._seznam[indeks]["uri"])
            m.pause = False
        except Exception as e:
            if self._cb_napaka:
                self._cb_napaka(str(e))
            return False
        self._sporoci()
        return True

    def premor(self) -> None:
        try:
            self._zagotovi().pause = not bool(self._zagotovi().pause)
        except Exception:
            pass

    def skok(self, sekunde: float) -> bool:
        try:
            self._zagotovi().command("seek", sekunde, "relative")
            return True
        except Exception:
            return False

    def pojdi_na(self, delez: float) -> bool:
        try:
            traj = self._zagotovi().duration or 0
            if traj <= 0:
                return False
            self._zagotovi().command("seek", max(0.0, min(1.0, delez)) * traj, "absolute")
            return True
        except Exception:
            return False

    def trajanje(self) -> float:
        return float(self._zagotovi().duration or 0.0)

    def naslednja(self) -> bool:
        i = self._naslednji_indeks()
        return self.predvajaj(i) if i is not None else False

    def prejsnja(self) -> bool:
        if not self._seznam:
            return False
        i = self._indeks - 1
        if i < 0:
            i = len(self._seznam) - 1 if self._ponovi == PONOVI_VSE else 0
        return self.predvajaj(i)

    def ustavi(self) -> None:
        try:
            self._zagotovi().command("stop")
        except Exception:
            pass
        self._sporoci()

    def zapri(self) -> None:
        self._unici()

    # ---- zvok / hitrost ----
    def nastavi_glasnost(self, v) -> bool:
        try:
            self._glasnost = max(0, min(100, int(round(float(v)))))
            self._zagotovi().volume = self._glasnost
        except Exception:
            return False
        self._sporoci()
        return True

    def utisaj(self, tiho=None) -> bool:
        try:
            self._zagotovi().mute = (not bool(self._zagotovi().mute)) if tiho is None else bool(tiho)
        except Exception:
            return False
        self._sporoci()
        return True

    def nastavi_hitrost(self, hitrost) -> bool:
        try:
            self._zagotovi().speed = max(0.25, min(4.0, float(hitrost)))
        except (TypeError, ValueError):
            return False
        self._sporoci()
        return True

    # ---- steze ----
    def steze(self) -> dict:
        zvok, podnapisi = [], [{"indeks": -1, "ime": "Brez"}]
        trenutni_zvok, trenutni_pod = -1, -1
        try:
            for t in (self._mpv.track_list or []):
                tip = t.get("type")
                ime = (t.get("title") or t.get("lang") or "").strip()
                tid = t.get("id")
                if tip == "audio":
                    zvok.append({"indeks": tid, "ime": ime or f"Zvok {tid}"})
                    if t.get("selected"):
                        trenutni_zvok = tid
                elif tip == "sub":
                    podnapisi.append({"indeks": tid, "ime": ime or f"Podnapis {tid}"})
                    if t.get("selected"):
                        trenutni_pod = tid
        except Exception:
            pass
        return {"zvok": zvok, "trenutniZvok": trenutni_zvok,
                "podnapisi": podnapisi, "trenutniPodnapis": trenutni_pod}

    def nastavi_zvok(self, indeks) -> bool:
        try:
            self._zagotovi().aid = int(indeks)
        except Exception:
            return False
        self._sporoci()
        return True

    def nastavi_podnapis(self, indeks) -> bool:
        try:
            self._zagotovi().sid = "no" if int(indeks) < 0 else int(indeks)
        except Exception:
            return False
        self._sporoci()
        return True

    def nalozi_podnapis(self, uri) -> bool:
        pot = uri
        if uri.startswith("file:"):
            from urllib.request import url2pathname
            from urllib.parse import urlsplit
            pot = url2pathname(urlsplit(uri).path)
        if not (os.path.isfile(pot) and pot.lower().endswith(_DOVOLJENE_PRIPONE_PODNAPISOV)):
            return False
        try:
            self._zagotovi().command("sub-add", pot, "select")   # mpv sam izrise
        except Exception:
            return False
        self._sporoci()
        return True

    # ---- ponovi / nakljucno ----
    def nastavi_ponovi(self, nacin) -> bool:
        if nacin not in (PONOVI_BREZ, PONOVI_ENA, PONOVI_VSE):
            return False
        self._ponovi = nacin
        try:
            self._zagotovi().loop_file = "inf" if nacin == PONOVI_ENA else "no"
        except Exception:
            pass
        self._sporoci()
        return True

    def preklopi_nakljucno(self, vklop=None) -> bool:
        self._nakljucno = (not self._nakljucno) if vklop is None else bool(vklop)
        self._sporoci()
        return True

    # ---- zamiki (podnapisi, zvok) ----
    def zamik_podnapisov(self, sekunde: Optional[float] = None, delta: float = 0.0) -> float:
        """Nastavi (sekunde) ali premakne (delta) zamik podnapisov; vrne trenutni zamik v sekundah."""
        try:
            m = self._zagotovi()
            z = float(sekunde) if sekunde is not None else float(m.sub_delay or 0.0) + float(delta)
            m.sub_delay = round(z, 3)
            return round(float(m.sub_delay or 0.0), 3)
        except Exception:
            return 0.0

    def zamik_zvoka(self, sekunde: Optional[float] = None, delta: float = 0.0) -> float:
        try:
            m = self._zagotovi()
            z = float(sekunde) if sekunde is not None else float(m.audio_delay or 0.0) + float(delta)
            m.audio_delay = round(z, 3)
            return round(float(m.audio_delay or 0.0), 3)
        except Exception:
            return 0.0

    # ---- poglavja ----
    def poglavja(self) -> list:
        """[{"indeks", "naslov", "cas"}] iz mpv chapter-list (prazno, ce jih datoteka nima)."""
        try:
            sez = self._zagotovi().chapter_list or []
        except Exception:
            return []
        izid = []
        for i, c in enumerate(sez):
            izid.append({"indeks": i, "naslov": str(c.get("title") or f"Poglavje {i + 1}"), "cas": float(c.get("time") or 0.0)})
        return izid

    def poglavje(self, indeks: int) -> bool:
        try:
            self._zagotovi().chapter = int(indeks)
            self._sporoci()
            return True
        except Exception:
            return False

    def naslednje_poglavje(self, smer: int = 1) -> bool:
        try:
            self._zagotovi().command("add", "chapter", int(smer))
            return True
        except Exception:
            return False

    # ---- slicica po slicico ----
    def slicica(self, smer: int = 1) -> bool:
        try:
            self._zagotovi().command("frame-step" if smer >= 0 else "frame-back-step")
            self._sporoci()
            return True
        except Exception:
            return False

    # ---- OSD ----
    def osd(self, besedilo: str, ms: int = 1200) -> None:
        """Kratko sporocilo v sliki (mpv-jev OSD prek libass; deluje tudi v LGPL gradnji brez skript)."""
        try:
            self._zagotovi().command("show-text", str(besedilo), int(ms))
        except Exception:
            pass

    # ---- posnetek ----
    def posnetek(self, pot: str) -> bool:
        try:
            self._zagotovi().command("screenshot-to-file", pot, "video")
            return os.path.isfile(pot)
        except Exception:
            return False

    # ---- stanje ----
    def podatki(self) -> dict:
        with self._kljuc:
            return self._podatki_brez_kljuca()

    def _podatki_brez_kljuca(self) -> dict:
        vnos = self._seznam[self._indeks] if 0 <= self._indeks < len(self._seznam) else {}
        try:
            pavza = bool(self._mpv.pause)
            polozaj = float(self._mpv.time_pos or 0.0)
            trajanje = float(self._mpv.duration or 0.0)
            glasnost = int(self._mpv.volume or 0)
            utisan = bool(self._mpv.mute)
            hitrost = float(self._mpv.speed or 1.0)
            # core_idle je True tudi med premorom (napacno "ustavljeno"); keep-open po koncu datoteke = ustavljeno
            idle = bool(self._mpv.idle_active) or bool(self._mpv.eof_reached)
        except Exception:
            pavza = True; polozaj = trajanje = 0.0; glasnost = self._glasnost; utisan = False; hitrost = 1.0; idle = True
        stanje = "ustavljeno" if idle else ("premor" if pavza else "predvaja")
        try:
            zamik_p = float(self._mpv.sub_delay or 0.0); zamik_z = float(self._mpv.audio_delay or 0.0)
            poglavje = self._mpv.chapter; n_poglavij = int(self._mpv.chapters or 0)
            poglavje = int(poglavje) if poglavje is not None else -1
        except Exception:
            zamik_p = zamik_z = 0.0; poglavje = -1; n_poglavij = 0
        s = self.steze()
        return {
            "stanje": stanje, "indeks": self._indeks, "nSeznam": len(self._seznam),
            "naslov": vnos.get("naslov", ""), "vrsta": vnos.get("vrsta", ""),
            "polozaj": polozaj, "trajanje": trajanje, "glasnost": glasnost,
            "utisan": utisan, "hitrost": hitrost, "ponovi": self._ponovi, "nakljucno": self._nakljucno,
            "nZvok": len(s["zvok"]), "trenutniZvok": s["trenutniZvok"],
            "nPodnapis": len(s["podnapisi"]) - 1, "trenutniPodnapis": s["trenutniPodnapis"],
            "steze": s,
            "zamikPodnapisov": zamik_p, "zamikZvoka": zamik_z, "poglavje": poglavje, "nPoglavij": n_poglavij,
            "uri": vnos.get("uri", ""),
        }

    # ---- notranje ----
    def _naslednji_indeks(self):
        import random
        if not self._seznam:
            return None
        if self._ponovi == PONOVI_ENA:
            return self._indeks
        if self._nakljucno and len(self._seznam) > 1:
            return random.choice([i for i in range(len(self._seznam)) if i != self._indeks])
        if self._indeks + 1 < len(self._seznam):
            return self._indeks + 1
        if self._ponovi == PONOVI_VSE:
            return 0
        return None

    def obdelaj_konec(self) -> bool:
        """GUI nit: ce je datoteka koncana, izbere naslednjo (ponovi/nakljucno) ali javi konec. True, ce je bilo kaj."""
        if not self._konec_cakajoc:
            return False
        self._konec_cakajoc = False
        if self.ob_koncu_datoteke is not None and self._koncan_uri:
            try:
                self.ob_koncu_datoteke(self._koncan_uri)
            except Exception:
                pass
        self._koncan_uri = ""
        self._po_koncu()
        return True

    def _po_koncu(self) -> None:
        i = self._naslednji_indeks()
        if i is None:
            if self._cb_konec:
                self._cb_konec()
        else:
            self.predvajaj(i)

    def _sporoci(self) -> None:
        with self._kljuc:
            if self._zapiranje or self._mpv is None:
                return
            if self._cb_sprememba:
                try:
                    self._cb_sprememba(self.podatki())
                except Exception:
                    pass


def _ime_iz_uri(uri: str) -> str:
    if not uri:
        return ""
    if uri.startswith("file:"):
        from urllib.request import url2pathname
        from urllib.parse import urlsplit
        uri = url2pathname(urlsplit(uri).path)
    return os.path.basename(uri.rstrip("/")) or uri
