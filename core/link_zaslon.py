"""Zaslon racunalnika na televizorju (Safeer Desktop Stream, faza 1: slika).

Racunalnik zajame svoj zaslon, ga kodira v H.264 in ga poslje televizorju po **neposredni**
povezavi v domacem omrezju - nic ne gre skozi sredisce in nic v oblak. Povezava je TLS s
samopodpisanim potrdilom Controla, katerega odtis televizor dobi skupaj z enkratnim zetonom v
odgovoru na ukaz `screen.start` (ista pot in isto potrdilo kot pri datotekah).

Format je namenoma preprost: po pozdravu tece gol pretok H.264 (Annex-B), ki ga Android dekodira
strojno (MediaCodec). Brez vsebnika in brez medpomnilnika, ker je cilj cim manjsa zakasnitev.

Pozdrav (prvi vrstici, UTF-8):
    SAFEER-ZASLON <zeton>\\n        <- televizor
    {"w":1920,"h":1080,"fps":30}\\n <- racunalnik, nato gol H.264

Zvok in vnos (tipkovnica, daljinec) v tej fazi nista vkljucena; kar ni narejeno, tudi ne
obljubljamo.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import secrets
import ssl
import subprocess
import threading
import time
from typing import Dict, List, Optional

from core.link_datoteke import TLS_MAPA, zagotovi_potrdilo
from core.link_mediji import CAKAJ_MPRIS_S, dogodek_v_tipko
from core.link_plosek import Plosek
from core.link_vnos import Vnos

#: Vrste okvirjev v pretoku.
OKVIR_SLIKA, OKVIR_ZVOK = 1, 2
#: Obvestilo racunalnika (JSON), npr. {"konec": "zaprto"}: na drugem zaslonu ni vec nobenega
#: programa. Starejsi televizorji okvir te vrste preskocijo.
OKVIR_OBVESTILO = 3
#: Koliko casa program na locenem zaslonu caka na televizor, ki je izginil, preden ga zapremo.
OSIROTELO_S = 90
#: Kako pogosto po koncu seje preverimo, ali je drugi zaslon prazen in lahko pospravimo zvok.
ZVOK_POSPRAVI_S = 5.0


class ProgramaNi(RuntimeError):
    """Televizor je zahteval locen zaslon s programi, a tam ni nicesar vec."""
#: Koliko casa sme biti drugi zaslon prazen, preden sejo koncamo: po zaprtju zadnjega programa
#: in (ce se program sploh ni odprl) od zacetka seje. Temen prazen zaslon je slepa ulica.
PRAZNO_PO_ZAPRTJU_S, PRAZNO_OD_ZACETKA_S = 1.5, 30.0
#: Zvok: surov PCM, ker je najpreprostejsi in brez zakasnitve (1,5 Mb/s je v domacem omrezju nic).
ZVOK_HZ, ZVOK_KANALI = 48000, 2
#: Kolikor casa cakamo, da se televizor javi, preden sejo zavrzemo.
CAKANJE_S = 30
#: Najvecja slika, ki jo posiljamo (televizor je 4K, a 1080p je za namizje dovolj in hitreje).
NAJVEC_SIRINA, NAJVEC_VISINA = 1920, 1080
# Kvantizator (qp) je pri tem kodirniku edini vzvod kakovosti - gonilnik zna samo CQP. Izmerjeno na
# mirnem namizju: qp 28 = 0,6 Mb/s, qp 24 = 0,8, qp 20 = 0,9, qp 18 = 1,0, qp 16 = 1,3 Mb/s, in
# procesor je pri vseh enak (strosek je zajem, ne kodiranje). Ker je pasovne sirine v domacem
# omrezju na pretek, so privzete vrednosti izdatne - drobno besedilo mora biti ostro.
KAKOVOSTI = {
    "nizka": {"fps": 30, "bitrate": "4M", "qp": 26, "sirina": 1280, "visina": 720},
    "srednja": {"fps": 30, "bitrate": "8M", "qp": 20, "sirina": 1920, "visina": 1080},
    "visoka": {"fps": 60, "bitrate": "16M", "qp": 18, "sirina": 1920, "visina": 1080},
    "najvisja": {"fps": 60, "bitrate": "24M", "qp": 16, "sirina": 1920, "visina": 1080},
}
# Privzeto posljemo najboljse, kar zmoreta racunalnik in omrezje: ostrejsa slika je po meritvah
# skoraj zastonj (strosek je zajem, ne kodiranje), pasovne sirine v domacem omrezju pa je na pretek.
# Nizje stopnje ostajajo v dogovoru zato, da se bo mogoce samodejno umakniti, kadar povezava ali
# racunalnik tega ne bosta zmogla - ne zato, da bi uporabnik izbiral.
PRIVZETA_KAKOVOST = "najvisja"


def _zaslon_geometrija(display: str) -> Optional[tuple]:
    """Velikost zaslona (xdotool); brez njega ne ugibamo, ampak vrnemo None."""
    if not shutil.which("xdotool"):
        return None
    try:
        okolje = dict(os.environ, DISPLAY=display)
        r = subprocess.run(["xdotool", "getdisplaygeometry"], text=True, capture_output=True,
                           timeout=5, env=okolje)
        deli = r.stdout.split()
        if len(deli) == 2:
            return int(deli[0]), int(deli[1])
    except Exception:
        pass
    return None


def vaapi_naprava() -> Optional[str]:
    """Naprava za strojno kodiranje (Intel/AMD); None, kadar je ni."""
    for ime in ("renderD128", "renderD129"):
        pot = os.path.join("/dev/dri", ime)
        if os.path.exists(pot):
            return pot
    return None


def ukaz_ffmpeg(display: str, sirina: int, visina: int, izvor_sirina: int, izvor_visina: int,
                fps: int, bitrate: str, vaapi: Optional[str], ffmpeg: str = "ffmpeg",
                qp: int = 24) -> List[str]:
    """Ukaz za zajem in kodiranje. Strojno (VAAPI), ce je mogoce, sicer x264 brez zamika.

    Locen od zagona, da ga je mogoce preveriti v testu brez kamere in zaslona.
    """
    u = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
         "-f", "x11grab", "-draw_mouse", "1", "-framerate", str(fps),
         "-video_size", f"{izvor_sirina}x{izvor_visina}", "-i", display]
    # Kadar je slika ze prave velikosti, je ne prevzorcimo: vsako skaliranje zmehca besedilo in
    # nekaj stane. To je najpogostejsi primer (zaslon 1920x1080 -> 1920x1080).
    lestvica = (sirina, visina) != (izvor_sirina, izvor_visina)
    filter_lestvica = f"scale={sirina}:{visina}:flags=lanczos," if lestvica else ""
    if vaapi:
        # Intelov gonilnik ima na tem prenosniku samo nizkoenergijski vhod (EncSliceLP), ta pa
        # podpira le CQP - z -b:v kodirnik sploh ne odpre ("no RC mode compatible"). Zato kakovost
        # dolocimo s kvantizatorjem, hitrost pa omejimo z velikostjo slike in sliko na sekundo.
        # Profil high (CABAC, transformacija 8x8) je za besedilo opazno boljsi od main in
        # televizor ga strojno dekodira (OMX.MTK.VIDEO.DECODER.AVC).
        #
        # Varcnega nacina (low_power) namenoma ne vsiljujemo: na tem prenosniku (Intel Gen12) drug
        # nacin sploh ne obstaja - izmerjeno je z low_power 0 in 1 izid enak do decimalke - na
        # drugih racunalnikih pa lahko gonilnik izbere boljso pot, ce mu je ne zvezemo.
        # CQP je edini nacin hitrosti, ki ga ta gonilnik zna (CBR, VBR, ICQ in QVBR so preizkuseni
        # in vsi padejo), obenem pa ga zna vsak - zato kakovost dolocimo s kvantizatorjem.
        u += ["-vaapi_device", vaapi,
              "-vf", f"{filter_lestvica}format=nv12,hwupload",
              "-c:v", "h264_vaapi", "-profile:v", "high",
              "-rc_mode", "CQP", "-qp", str(qp)]
    else:
        u += ["-vf", f"{filter_lestvica}format=yuv420p",
              "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-profile:v", "high",
              "-b:v", bitrate, "-maxrate", bitrate, "-bufsize", "1M"]
    # Brez B-slik in z rednim kljucnim okvirjem: televizor se lahko prikljuci hitro,
    # izguba paketa pa se popravi v eni sekundi.
    u += ["-g", str(max(1, fps)), "-bf", "0", "-flags", "+low_delay",
          "-f", "h264", "-"]
    return u


def privzeti_monitor() -> Optional[str]:
    """Kar racunalnik ta trenutek predvaja (monitor privzetega izhoda).

    Ime izhoda vprasamo `pactl`; ce ga ni ali ce se ne more povezati (to se zgodi procesu, ki ne
    tece v uporabnikovi seji), uporabimo `@DEFAULT_MONITOR@` - to ime razresi zvocni streznik sam.
    None vrnemo samo, kadar zvocnega streznika ocitno ni.
    """
    if shutil.which("pactl"):
        try:
            r = subprocess.run(["pactl", "get-default-sink"], text=True, capture_output=True, timeout=3)
            ime = (r.stdout or "").strip()
            if ime:
                return ime + ".monitor"
        except Exception:
            pass
    zvocni_vticnik = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid()), "pulse", "native")
    if os.path.exists(zvocni_vticnik) or os.environ.get("PULSE_SERVER"):
        return "@DEFAULT_MONITOR@"
    return None


def ukaz_zvok(vir: str, ffmpeg: str = "ffmpeg") -> List[str]:
    """Zajem zvoka racunalnika kot surov PCM. Majhni koscki (10 ms), da zvok ne zaostaja za sliko."""
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "pulse", "-fragment_size", "1920", "-i", vir,
            "-ac", str(ZVOK_KANALI), "-ar", str(ZVOK_HZ), "-f", "s16le", "-"]


class Zaslon:
    """Deljenje zaslona racunalnika s televizorjem: ena seja naenkrat, samo na uporabnikov ukaz."""

    ZMOZNOST = "desktop"

    def __init__(self, tls_mapa: str = TLS_MAPA, ffmpeg: Optional[str] = None,
                 vklopljeno: bool = False) -> None:
        self.tls_mapa = tls_mapa
        #: Uporabnik mora deljenje zaslona vklopiti v Safeer Controlu; privzeto je izklopljeno.
        self.vklopljeno = bool(vklopljeno)
        #: Klicatelj (Control) ga nastavi, da si izbiro zapomni in pokaze stanje v pladnju.
        self.ob_spremembi = None
        self.ffmpeg = ffmpeg or (shutil.which("ffmpeg") or "")
        self.odtis = ""
        self.vrata = 0
        self._zeton = ""
        self._naprava = ""
        self._kakovost = PRIVZETA_KAKOVOST
        self._slika: Dict[str, int] = {}
        #: Stevec sej: straza osirotelih programov ve, ali se je medtem zacela nova seja.
        self._seja_st = 0
        self._izvor = (1920, 1080)
        self._zvok_vir: Optional[str] = None
        self._posluh: Optional[socket.socket] = None
        self._proces: Optional[subprocess.Popen] = None
        self._zvocni: Optional[subprocess.Popen] = None
        self._nit: Optional[threading.Thread] = None
        self._pisalo = threading.Lock()
        self._vnos = Vnos()
        # Navidezni igralni plosek racunalnika: nastane sele, ko televizor res poslje plosek.
        self._plosek = Plosek()
        #: Locen zaslon za televizor (core.link_sway.DrugiZaslon) ali None.
        self.drugi = None
        self._cilj = "desktop"
        #: Okolje za zajem slike (drugi zaslon potrebuje svoj WAYLAND_DISPLAY); None = nase.
        self._okolje_zajema: Optional[dict] = None
        self._vnosov = 0
        self._tece_od = 0.0
        self._povezan = False
        self._kljucavnica = threading.Lock()

    # ------------------------------------------------------------------ stanje

    def na_voljo(self) -> dict:
        """Ali ta racunalnik sploh zna deliti zaslon in s cim."""
        display = os.environ.get("DISPLAY", "")
        vaapi = vaapi_naprava()
        return {
            "dovoljeno": self.vklopljeno,
            "mozno": bool(self.ffmpeg) and bool(display),
            "ffmpeg": bool(self.ffmpeg),
            "zaslon": display,
            "strojno": bool(vaapi),
            "zvok": bool(privzeti_monitor()),
            "vnos": self._vnos.mozno,
            "plosek": self._plosek.mozno(),
            "kakovosti": sorted(KAKOVOSTI),
            "locen_zaslon": self.drugi is not None,
        }

    def stanje(self) -> dict:
        s = {"tece": self._proces is not None or self._posluh is not None,
             "povezan": self._povezan, "naprava": self._naprava, "kakovost": self._kakovost,
             "screen": self._cilj}
        if self._slika:
            s.update(self._slika)
        if self._tece_od:
            s["sekund"] = int(time.time() - self._tece_od)
        s["vnosov"] = self._vnosov
        return s

    def oddaljeni_vnos(self, dogodek: dict) -> bool:
        """Vnos druge zaupanja vredne Safeer naprave v trenutno deljeno sejo.

        Namenjeno opcijskemu telefonu-kontrolerju: telefon ne prevzame seje in ne
        spreminja Continuity/Workspace stanja. Dogodek je sprejet samo, ko zaslon
        dejansko tece, in gre skozi isti strogi allow-list kot vnos gledalca.
        """
        if not self.stanje().get("tece") or not isinstance(dogodek, dict):
            return False
        ok = bool(self._vnos.izvedi(dogodek))
        if ok:
            self._vnosov += 1
        return ok

    # ------------------------------------------------------------------ zagon

    def nastavi(self, vklopljeno: bool) -> None:
        """Uporabnik je deljenje zaslona vklopil ali izklopil. Izklop takoj konca tekoco sejo."""
        self.vklopljeno = bool(vklopljeno)
        if not self.vklopljeno:
            self.ustavi()
        if self.ob_spremembi is not None:
            try:
                self.ob_spremembi(self.vklopljeno)
            except Exception:
                pass

    def _na_drugem(self, cilj: str) -> bool:
        """Ali ta seja kaze drugi zaslon (programe s televizorja) namesto uporabnikovega namizja.

        `apps` = da, ce drugi zaslon tece; `desktop` = nikoli; brez navedbe (starejsi televizor) =
        da, kadar so na drugem zaslonu odprta okna - sicer bi jih televizor sploh ne videl."""
        if self.drugi is None or not self.drugi.tece():
            return False
        if cilj == "desktop":
            return False
        return cilj == "apps" or self.drugi.okna() > 0

    def zacni(self, id_naprave: str, kakovost: str = PRIVZETA_KAKOVOST, cilj: str = "") -> dict:
        """Pripravi sejo: odpre TLS vrata in caka televizor. Zajem se zacne sele, ko se ta javi."""
        if not self.vklopljeno:
            raise RuntimeError("Deljenje zaslona ni vklopljeno")
        if not self.ffmpeg:
            raise RuntimeError("Na tem racunalniku ni ffmpeg")
        display = os.environ.get("DISPLAY", "")
        if not display:
            raise RuntimeError("Zaslona ni mogoce zajeti (seja ni na voljo)")
        k = KAKOVOSTI.get(kakovost) or KAKOVOSTI[PRIVZETA_KAKOVOST]
        self._seja_st += 1
        if cilj == "apps" and self.drugi is not None and not self.drugi.tece():
            # Televizor hoce program, locenega zaslona pa ni vec (Control je bil znova zagnan,
            # programi so zaprti). Prej je dobil namizje racunalnika - tega ni zahteval in tam
            # je lahko karkoli zasebnega. Zdaj pove, da programa ni vec.
            raise ProgramaNi("Program na racunalniku ni vec odprt")
        self.ustavi()
        na_drugem = self._na_drugem(cilj)
        if na_drugem:
            # Drugi zaslon je natanko tako velik, kot ga televizor dobi: brez prevzorcenja.
            izvor = (k["sirina"], k["visina"])
            self.drugi.velikost(*izvor)
        else:
            izvor = _zaslon_geometrija(display) or (NAJVEC_SIRINA, NAJVEC_VISINA)
        sirina, visina = self._prilagodi(izvor, k["sirina"], k["visina"])
        with self._kljucavnica:
            self._kakovost = kakovost if kakovost in KAKOVOSTI else PRIVZETA_KAKOVOST
            self._naprava = id_naprave
            self._zeton = secrets.token_urlsafe(24)
            self._slika = {"width": sirina, "height": visina, "fps": int(k["fps"])}
            self._izvor = (int(izvor[0]), int(izvor[1]))
            kljuc, potrdilo, self.odtis = zagotovi_potrdilo(self.tls_mapa)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(potrdilo, kljuc)
            posluh = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            posluh.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            posluh.bind(("0.0.0.0", 0))
            posluh.listen(1)
            posluh.settimeout(CAKANJE_S)
            self.vrata = posluh.getsockname()[1]
            self._posluh = posluh
            self._tece_od = time.time()
            self._povezan = False
            if na_drugem:
                self._cilj = "apps"
                self._zvok_vir = self.drugi.zvok_vir()
                self._vnos = self.drugi.vnos
                self._okolje_zajema = self.drugi.okolje()
                ukaz = self.drugi.ukaz_zajema(int(k["fps"]), int(k["qp"]), str(k["bitrate"]))
            else:
                self._cilj = "desktop"
                self._okolje_zajema = None
                self._zvok_vir = privzeti_monitor()
                self._vnos = Vnos(display=display)
                ukaz = ukaz_ffmpeg(display, sirina, visina, izvor[0], izvor[1], int(k["fps"]),
                                   str(k["bitrate"]), vaapi_naprava(), self.ffmpeg, int(k["qp"]))
            self._nit = threading.Thread(target=self._streci, args=(posluh, ctx, ukaz),
                                         name="safeer-zaslon", daemon=True)
            self._nit.start()
        return {"port": self.vrata, "fp": self.odtis, "token": self._zeton, "v": 2,
                "codec": "h264", **self._slika, "quality": self._kakovost,
                "audio": {"hz": ZVOK_HZ, "channels": ZVOK_KANALI, "format": "s16le"} if self._zvok_vir else None,
                "input": self._vnos.mozno, "gamepad": self._plosek.mozno(), "screen": self._cilj,
                # Igra: puscice daljinca morajo biti puscice, ne miska.
                "game": self._cilj == "apps" and getattr(self.drugi, "zadnja_skupina", "") == "igre",
                # Racunalnik zna skok po gumbih (dogodek "fokus"); starejsi Control tega ne zna.
                "focus": self._cilj == "apps" and hasattr(self.drugi, "fokus"),
                # Predvajalnik: televizor ga upravlja kot predvajalnik in narise svoj pas za predvajanje.
                "profile": getattr(self.drugi, "zadnji_profil", "") if self._cilj == "apps" else "",
                "media": self._cilj == "apps" and hasattr(self.drugi, "mediji")}

    @staticmethod
    def _prilagodi(izvor, najvec_sirina, najvec_visina) -> tuple:
        """Ohrani razmerje zaslona in ne povecuj cez izvirnik; sirina in visina morata biti sodi."""
        s, v = izvor
        if s <= 0 or v <= 0:
            return najvec_sirina, najvec_visina
        merilo = min(najvec_sirina / s, najvec_visina / v, 1.0)
        return (max(2, int(s * merilo) // 2 * 2), max(2, int(v * merilo) // 2 * 2))

    def _streci(self, posluh: socket.socket, ctx: ssl.SSLContext, ukaz: List[str]) -> None:
        odjemalec = None
        try:
            surov, _ = posluh.accept()
            odjemalec = ctx.wrap_socket(surov, server_side=True)
            odjemalec.settimeout(10)
            pozdrav = self._preberi_vrstico(odjemalec)
            if not pozdrav.startswith("SAFEER-ZASLON ") or pozdrav.split(" ", 1)[1].strip() != self._zeton:
                odjemalec.close()
                return
            glava = {"v": 2, "w": self._slika["width"], "h": self._slika["height"],
                     "fps": self._slika["fps"],
                     "zvok": {"hz": ZVOK_HZ, "kanali": ZVOK_KANALI, "oblika": "s16le"} if self._zvok_vir else None,
                     "vnos": self._vnos.mozno, "plosek": self._plosek.mozno()}
            odjemalec.sendall((json.dumps(glava) + "\n").encode("utf-8"))
            odjemalec.settimeout(None)
            self._povezan = True

            slika = subprocess.Popen(ukaz, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     stdin=subprocess.DEVNULL, bufsize=0, env=self._okolje_zajema)
            self._proces = slika
            niti = [threading.Thread(target=self._crpaj, args=(slika, OKVIR_SLIKA, odjemalec, 32 * 1024),
                                     name="safeer-zaslon-slika", daemon=True)]
            if self._zvok_vir:
                try:
                    zvok = subprocess.Popen(ukaz_zvok(self._zvok_vir, self.ffmpeg), stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, bufsize=0)
                    self._zvocni = zvok
                    # Zvok beremo v majhnih koscih (10 ms), da ne caka za veliko sliko.
                    niti.append(threading.Thread(target=self._crpaj, args=(zvok, OKVIR_ZVOK, odjemalec, 1920),
                                                 name="safeer-zaslon-zvok", daemon=True))
                except Exception:
                    self._zvocni = None
            # Vnos tece nazaj po isti povezavi; brati ga moramo sproti, sicer se vticnica zamasi.
            niti.append(threading.Thread(target=self._beri_vnos, args=(odjemalec,),
                                         name="safeer-zaslon-vnos", daemon=True))
            if self._cilj == "apps" and self.drugi is not None:
                niti.append(threading.Thread(target=self._strazi_prazno, args=(odjemalec, slika),
                                             name="safeer-zaslon-prazno", daemon=True))
                if hasattr(self.drugi, "mediji"):
                    niti.append(threading.Thread(target=self._porocaj_medij, args=(odjemalec, slika),
                                                 name="safeer-zaslon-medij", daemon=True))
            for n in niti:
                n.start()
            niti[0].join()          # dokler tece slika, tece seja
        except (OSError, ssl.SSLError, ValueError):
            pass
        finally:
            self._povezan = False
            try:
                if odjemalec is not None:
                    # Najprej shutdown: druge niti (zvok, vnos) drzijo vticnico in sam close televizorju
                    # ne bi poslal konca - ta bi gledal zamrznjeno sliko.
                    try:
                        odjemalec.shutdown(socket.SHUT_RDWR)
                    except (OSError, ValueError):
                        pass
                    odjemalec.close()
            except Exception:
                pass
            if self._cilj == "apps" and self.drugi is not None:
                self._strazi_osirotele(self._seja_st)
                self._pospravi_zvok_po_seji(self._seja_st)
            self.ustavi()

    def _strazi_osirotele(self, seja: int) -> None:
        """Televizor je izginil sredi seje (ugasnjen, aplikacija zaprta ali posodobljena) in se ne
        vrne: program na locenem zaslonu bi tekel naprej nevidno, dokler ga kdo ne zapre na
        racunalniku. Ce v OSIROTELO_S ni nove seje, ga zapremo - kot bi uporabnik koncal sejo."""
        def straza() -> None:
            time.sleep(OSIROTELO_S)
            if self._seja_st != seja or self._povezan:
                return
            drugi = self.drugi
            if drugi is not None and hasattr(drugi, "zapri_okna") and drugi.okna() > 0:
                print("[zaslon] televizorja ni vec, programi na locenem zaslonu se zapirajo", flush=True)
                drugi.zapri_okna()
        threading.Thread(target=straza, name="safeer-zaslon-osiroteli", daemon=True).start()

    def _pospravi_zvok_po_seji(self, seja: int) -> None:
        """Po koncu seje odstrani navidezni izhod Safeer-TV, ko na drugem zaslonu ni vec programov
        (zaprl jih je uporabnik ali straza osirotelih). Ce program ostane odprt, ostane tudi izhod."""
        drugi = self.drugi
        if drugi is None or not hasattr(drugi, "pospravi_zvok"):
            return

        def straza() -> None:
            konec = time.monotonic() + OSIROTELO_S + 30
            while time.monotonic() < konec:
                time.sleep(ZVOK_POSPRAVI_S)
                if self._seja_st != seja or self._povezan:
                    return
                if drugi.okna() == 0 and drugi.pospravi_zvok():
                    return
        threading.Thread(target=straza, name="safeer-zaslon-zvok-pospravi", daemon=True).start()

    def _strazi_prazno(self, odjemalec, slika: subprocess.Popen) -> None:
        """Ko se zadnji program na drugem zaslonu zapre (igra ob Esc, uporabnik jo zapre), televizor
        sicer gleda temen prazen zaslon. Zato mu to povemo in sejo koncamo - vrne se v Safeer OS."""
        videl = False
        zacetek = time.monotonic()
        prazno_od: Optional[float] = None
        while self._proces is slika and slika.poll() is None:
            time.sleep(0.5)
            zdaj = time.monotonic()
            if self.drugi.okna() > 0:
                videl, prazno_od = True, None
                continue
            prazno_od = zdaj if prazno_od is None else prazno_od
            if videl and zdaj - prazno_od >= PRAZNO_PO_ZAPRTJU_S:
                razlog = "zaprto"
            elif not videl and zdaj - zacetek >= PRAZNO_OD_ZACETKA_S:
                razlog = "ni_okna"
            else:
                continue
            if self._proces is not slika:
                return
            vsebina = json.dumps({"konec": razlog}).encode("utf-8")
            try:
                with self._pisalo:
                    odjemalec.sendall(bytes([OKVIR_OBVESTILO]) + len(vsebina).to_bytes(4, "big") + vsebina)
            except (OSError, ssl.SSLError, ValueError):
                pass
            print("[zaslon] drugi zaslon je prazen (%s), seja koncana" % razlog, flush=True)
            self.ustavi()
            return

    def _crpaj(self, proces: subprocess.Popen, vrsta: int, odjemalec, kos: int) -> None:
        """Bere en vir (slika ali zvok) in ga v okvirjih poslje televizorju. Pisanje je pod kljucem,
        da se okvirja dveh virov nikoli ne prepletata."""
        try:
            while True:
                podatki = proces.stdout.read(kos)
                if not podatki:
                    break
                glava = bytes([vrsta]) + len(podatki).to_bytes(4, "big")
                with self._pisalo:
                    odjemalec.sendall(glava + podatki)
        except (OSError, ssl.SSLError, ValueError, AttributeError):
            pass

    def _v_zaslon(self, dogodek: dict) -> dict:
        """Tocka iz slike (kot jo vidi tablica) v tocko zaslona: slika je lahko pomanjsana."""
        try:
            x, y = float(dogodek.get("x")), float(dogodek.get("y"))
        except (TypeError, ValueError):
            return dogodek
        sw, sv = max(1, self._slika.get("width", 1)), max(1, self._slika.get("height", 1))
        iw, iv = self._izvor
        return {"vrsta": "tocka", "x": int(min(max(x, 0), sw - 1) * iw / sw),
                "y": int(min(max(y, 0), sv - 1) * iv / sv)}

    def _obvesti(self, odjemalec, podatki: dict) -> None:
        """Obvestilo televizorju po isti povezavi kot slika (okvir izbire, kazalec za povecavo ...)."""
        vsebina = json.dumps(podatki).encode("utf-8")
        try:
            with self._pisalo:
                odjemalec.sendall(bytes([OKVIR_OBVESTILO]) + len(vsebina).to_bytes(4, "big") + vsebina)
        except (OSError, ssl.SSLError, ValueError):
            pass

    def _fokus(self):
        drugi = getattr(self._vnos, "drugi", None)
        return getattr(drugi, "fokus", None) if self._cilj == "apps" else None

    def _odpre_tipkovnico(self, dogodek) -> bool:
        """OK (klik) na polju za besedilo, izbranem s skokom: televizor naj odpre tipkovnico."""
        f = self._fokus()
        if f is None or not isinstance(dogodek, dict) or dogodek.get("vrsta") != "klik":
            return False
        if str(dogodek.get("gumb", "levi") or "levi") != "levi" or dogodek.get("dvojni"):
            return False
        e, t = f.izbira, f.tocka
        return bool(e is not None and len(e) > 7 and e[7] and t is not None
                    and abs(t[0] - e[0]) < 1 and abs(t[1] - e[1]) < 1)

    def _po_vnosu(self, odjemalec, dogodek, tipkovnica: bool, imel_izbiro: bool = False) -> None:
        f = self._fokus()
        if f is None or not isinstance(dogodek, dict):
            return
        vrsta = dogodek.get("vrsta")
        if vrsta == "klik" and imel_izbiro:
            def potrdi() -> None:
                time.sleep(0.35)
                if f.izbira is None:          # uporabnik je medtem ze premaknil kazalec
                    return
                e = f.osvezi_izbiro()
                self._obvesti(odjemalec, {"izbira": [int(e[2]), int(e[3]), int(e[4]), int(e[5])]
                                          if e is not None else None})
            threading.Thread(target=potrdi, name="safeer-izbira", daemon=True).start()
        if vrsta == "fokus":
            e = f.izbira
            self._obvesti(odjemalec, {
                "izbira": [int(e[2]), int(e[3]), int(e[4]), int(e[5])] if e is not None else None,
                "brez_gumbov": bool(f.brez_gumbov), "profil": f.profil()})
        if tipkovnica:
            self._obvesti(odjemalec, {"tipkovnica": True})
        if getattr(self._vnos, "porocaj_kazalec", False) and vrsta in ("premik", "fokus", "povecava") \
                and f.tocka is not None:
            self._obvesti(odjemalec, {"kazalec": [int(f.tocka[0]), int(f.tocka[1])]})

    def _beri_vnos(self, odjemalec) -> None:
        """Dogodki televizorja (ena vrstica JSON na dogodek). Kar ni na seznamu dovoljenega, pade."""
        ostanek = b""
        try:
            while True:
                kos = odjemalec.recv(4096)
                if not kos:
                    break
                ostanek += kos
                while b"\n" in ostanek:
                    vrstica, ostanek = ostanek.split(b"\n", 1)
                    if len(vrstica) > 4096:
                        continue
                    try:
                        dogodek = json.loads(vrstica.decode("utf-8", "replace"))
                    except ValueError:
                        continue
                    if isinstance(dogodek, dict) and dogodek.get("vrsta") == "tocka":
                        dogodek = self._v_zaslon(dogodek)
                    if isinstance(dogodek, dict) and dogodek.get("vrsta") == "medij":
                        self._medij(odjemalec, dogodek)
                        continue
                    tipkovnica = self._odpre_tipkovnico(dogodek)
                    f = self._fokus()
                    imel_izbiro = f is not None and f.izbira is not None
                    if self._plosek_dogodek(dogodek) or self._vnos.izvedi(dogodek):
                        self._po_vnosu(odjemalec, dogodek, tipkovnica, imel_izbiro)
                        self._vnosov += 1
                        # Redko, a dovolj, da se v dnevniku vidi, da vnos res prihaja skozi.
                        if self._vnosov in (1, 10, 100) or self._vnosov % 500 == 0:
                            print("[zaslon] vnos #%d: %s" % (self._vnosov, dogodek.get("vrsta")), flush=True)
                if len(ostanek) > 8192:
                    ostanek = b""
        except (OSError, ssl.SSLError, ValueError):
            pass
        finally:
            # Povezava je padla ali se koncala: kar je televizor drzal, mora zdaj gor.
            self._vnos.sprosti_vse()
            self._plosek.zapri()

    @staticmethod
    def _preberi_vrstico(s: socket.socket, najvec: int = 256) -> str:
        zbrano = b""
        while len(zbrano) < najvec:
            b = s.recv(1)
            if not b or b == b"\n":
                break
            zbrano += b
        return zbrano.decode("utf-8", "replace")

    def _mediji(self):
        return getattr(self.drugi, "mediji", None) if self._cilj == "apps" and self.drugi is not None else None

    def _medij(self, odjemalec, dogodek: dict) -> None:
        """Ukaz za predvajalnik (predvajaj/pavza, previj). Najprej MPRIS; kjer ga ni, tipka."""
        m = self._mediji()
        ukaz = str(dogodek.get("ukaz", "") or "")
        try:
            sekund = float(dogodek.get("s", 0) or 0)
        except (TypeError, ValueError):
            sekund = 0.0
        if m is not None and m.ukaz(ukaz, sekund):
            # Pas na televizorju naj takoj pokaze novo stanje, ne sele ob naslednjem porocilu.
            stanje = m.stanje()
            if stanje is not None:
                self._obvesti(odjemalec, {"medij": stanje})
            return
        tipka = dogodek_v_tipko(dogodek)
        if tipka is not None:
            self._vnos.izvedi(tipka)

    def _porocaj_medij(self, odjemalec, slika: subprocess.Popen) -> None:
        """Vsako sekundo: stanje predvajalnika na locenem zaslonu (samo ko se spremeni)."""
        zadnje: Optional[dict] = None
        poslano = False
        zacetek, najden = time.monotonic(), False
        while self._proces is slika and slika.poll() is None:
            m = self._mediji()
            stanje = m.stanje() if m is not None else None
            if stanje is not None:
                najden = True
            elif not najden and time.monotonic() - zacetek > CAKAJ_MPRIS_S:
                # Predvajalnik se ni oglasil na MPRIS: televizor naj ne ostane v nacinu predvajalnika.
                najden = True
                self._obvesti(odjemalec, {"mpris": False})
            if stanje != zadnje or not poslano:
                if stanje is not None or poslano:
                    self._obvesti(odjemalec, {"medij": stanje})
                    poslano = True
                zadnje = stanje
            time.sleep(1.0)

    def _plosek_dogodek(self, dogodek: dict) -> bool:
        """Gumb ali os igralnega plosecka s televizorja. Vse drugo pusti vnosu (tipke, miska)."""
        if not isinstance(dogodek, dict):
            return False
        vrsta = str(dogodek.get("vrsta", "") or "")
        if vrsta == "plosek_gumb":
            return self._plosek.gumb(str(dogodek.get("gumb", "") or ""), bool(dogodek.get("dol")))
        if vrsta == "plosek_os":
            return self._plosek.os(str(dogodek.get("os", "") or ""), dogodek.get("vrednost"))
        return False

    def oddaljeni_plosek(self, dogodek: dict) -> bool:
        """Opcijski telefonski gamepad uporablja isti uinput kot TV seja.

        Ne zaganja seje in ne spreminja Continuity/Workspace stanja. Dogodek je dovoljen
        samo, ko oddaljena seja ze tece; zato telefon nikoli ne prevzame racunalnika sam.
        """
        if not self.stanje().get("tece"):
            return False
        return self._plosek_dogodek(dogodek)

    def sprosti_oddaljeni_plosek(self) -> None:
        """Ob preklopu nazaj na navadni daljinec spusti gumbe in osi."""
        self._plosek.sprosti_vse()

    def ustavi(self) -> None:
        """Konca zajem in zapre vrata; zeton takoj ne velja vec."""
        self._vnos.sprosti_vse()
        self._plosek.zapri()
        with self._kljucavnica:
            proces, zvocni, posluh = self._proces, self._zvocni, self._posluh
            self._proces = None
            self._zvocni = None
            self._posluh = None
            self._zeton = ""
            self.vrata = 0
            self._tece_od = 0.0
        for p in (proces, zvocni):
            if p is None:
                continue
            try:
                p.terminate()
                p.wait(timeout=3)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        if posluh is not None:
            # Nit visi v accept(); samo close() je ne prebudi vedno, shutdown() pa jo.
            try:
                posluh.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                posluh.close()
            except Exception:
                pass


__all__ = ["Zaslon", "ukaz_ffmpeg", "vaapi_naprava", "KAKOVOSTI", "PRIVZETA_KAKOVOST"]
