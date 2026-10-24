"""Safeer Supervisor (varuh procesov): tretji, neodvisen proces, ki pazi na lupino namizja in Safeer OS.

Lastnik, 18. 10. 2026 (moznost B): namizje (Safeer Shell, core/lupina_proces.py) tece v svojem procesu, programi in
funkcije sistema (Medijski center, Splet, Control - core/en_proces.py) pa v procesu Safeer OS. Varuh:

  * zazna sesutje (proces se konca s signalom ali napako) IN zamrznitev: otrok vsakih UTRIP_S sekund poslje WATCHDOG=1
    iz svoje glavne zanke (GLib oziroma Qt); ce ga ZAMRZNITEV_* sekund ni, varuh poslje SIGABRT (faulthandler zapise
    sled vseh niti v sled.log) in po ABORT_DO_KILL_S SIGKILL - enako kot WatchdogSec v systemd;
  * znova zazene samo proces, ki je odpovedal (lupina ostane, ko pade Safeer OS, in obratno), s postopnim zamikom
    (1, 2, 4, 8 s ...); po NAJVEC_NAPAK napakah v OKNO_NAPAK_S odneha (brez neskoncne zanke) in uporabniku pove;
  * pazi na pomnilnik: ponovni zagon pocaka, da je prostega pomnilnika dovolj (sicer bi ga OOM takoj spet ubil - zanka),
    proces, ki preraste mejo, mirno zazene znova (s stanjem); Safeer OS (in z njim spletni procesi) ima vecji
    oom_score_adj, da OOM v stiski izbere njega - njegovo stanje se obnovi - in ne lupine ali uporabnikovih programov.

Zakaj ne enote systemd (preverjeno na testnem PC 18. 10. 2026, systemd 255): storitev ima svojo skupino cgroup in ob
ponovnem zagonu (KillMode=control-group) konca VSE procese v njej - tudi programe, ki jih je uporabnik zagnal iz Safeer OS
(poskus: enota z Restart=on-failure, otrok `setsid sleep` - po sesutju glavnega procesa je bil ubit; LibreOffice z
neshranjenim dokumentom bi bil prav tako); MemoryMax bi stel tudi njih. Flatpak (glavna oblika Safeer OS) v peskovniku
nima NOTIFY_SOCKET niti /run/user/<uid>/systemd (preverjeno istega dne). Varuh je zato isti za .deb, Flatpak in AppImage, otroci pa tecejo v seji kot
prej. Protokol obvestil je isti kot sd_notify (READY=1, WATCHDOG=1, STATUS=...), zato koda otrok dela tudi pod systemd.

Varuh je cim manjsi (izmerjeno 18. 10. 2026, Python 3.12): samo os, select, signal, socket, struct, time - brez
subprocess (otroke zazene os.posix_spawn), json in typing (+4 MB). Gtk, Qt in WebKit nikoli. Zazene ga
packaging/safeer-os-launcher za --delovna.
"""
from __future__ import annotations

import os
import sys

if __name__ == "__main__" and not __package__:
    # Zagon kot skripta (python3 core/varuh_procesov.py): koren tovora namesto mape core na sys.path.
    sys.path[0] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import select
import signal
import socket
import struct
import time

# ---------------------------------------------------------------------------------------------- odjemalec (otroci)
#: Utrip iz glavne zanke otroka. Zamrznitev = toliko sekund brez utripa (glej Proces.zamrznitev_s): pri 20-30 s je 5 s
#: se vedno 4-6 utripov v roku. Prej 2 s - meritev 19. 10. 2026 (vsebnik, mirovanje): varuh 2,5 bujenja/s, lupina in
#: Safeer OS vsak 0,5/s samo zaradi utripa.
UTRIP_S = 5
#: Lupina utripa pogosteje: zamrznjeno namizje je uporabnik videl 19,2 s (testni PC, 20. 10. 2026, SIGSTOP lupine), preden
#: ga je varuh zamenjal. Lupina nima stanja (ponoven zagon 0,4 s), zato je hitra zamenjava poceni; +0,3 bujenja/s.
UTRIP_LUPINA_S = 2

_obvestila: dict = {"vtic": None, "naslov": None, "prebrano": False, "utrip": 0}


def pripravi_obvestila() -> bool:
    """NOTIFY_SOCKET (varuh ali systemd) prebere enkrat in ga odstrani iz okolja: programi, ki jih ta proces zazene
    (Firefox iz menija, spletni procesi), ga ne smejo podedovati - njihov READY=1 bi zmedel varuha."""
    if _obvestila["prebrano"]:
        return _obvestila["vtic"] is not None
    _obvestila["prebrano"] = True
    from core import okolje_procesa      # prevzeto pred nitmi (core/okolje_procesa.py)
    pot = okolje_procesa.prevzemi("NOTIFY_SOCKET")
    if not (pot.startswith("/") or pot.startswith("@")):
        return False
    try:
        _obvestila["vtic"] = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC)
    except OSError:
        return False
    _obvestila["naslov"] = "\0" + pot[1:] if pot.startswith("@") else pot
    return True


def obvesti(*vrstice: str) -> bool:
    """sd_notify: READY=1, WATCHDOG=1, STATUS=..., SAFEER_ZNOVA=1 ... Brez varuha ne naredi nicesar."""
    if not pripravi_obvestila():
        return False
    try:
        _obvestila["vtic"].sendto("\n".join(vrstice).encode("utf-8"), _obvestila["naslov"])
        return True
    except OSError:
        return False


def pod_varuhom() -> bool:
    return pripravi_obvestila()


def zazeni_program(ukaz, okolje=None) -> int | None:
    """Zazene uporabnikov program prek varuha, tako da dobi oom_score_adj=0 in svojo sejo.
    Ce varuh ni na voljo ali odpove, vrne None (klicatelj zazene po starem in zabelezi v dnevnik)."""
    if not pod_varuhom():
        return None
    pot_vtic = _obvestila.get("naslov")
    vtic = _obvestila.get("vtic")
    if not pot_vtic or vtic is None:
        return None
    import array
    import json
    try:
        c1, c2 = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM | socket.SOCK_CLOEXEC)
    except OSError as e:
        _dnevnik("zagon prek varuha ni uspel (socketpair): %s" % e)
        return None
    try:
        c1.settimeout(2.0)
        c2.settimeout(2.0)
        anc = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [c2.fileno()]))]
        poslano = False
        try:
            vtic.sendmsg([b"SAFEER_ZAZENI=1\n"], anc, 0, pot_vtic)
            poslano = True
        except OSError as e:
            _dnevnik("zagon prek varuha ni uspel (sendmsg): %s" % e)
            return None
        finally:
            c2.close()

        telo = json.dumps({"ukaz": list(ukaz), "okolje": dict(okolje) if okolje else None},
                          ensure_ascii=False).encode("utf-8")
        c1.sendall(struct.pack(">I", len(telo)) + telo)

        glava = c1.recv(4)
        if len(glava) != 4:
            _dnevnik("zagon prek varuha ni uspel: prazen odgovor")
            return None
        dolzina = struct.unpack(">I", glava)[0]
        if dolzina <= 0 or dolzina > 1024 * 1024:
            _dnevnik("zagon prek varuha ni uspel: neveljavna dolzina odgovora %d" % dolzina)
            return None
        odg_bajti = bytearray()
        while len(odg_bajti) < dolzina:
            delcek = c1.recv(min(4096, dolzina - len(odg_bajti)))
            if not delcek:
                break
            odg_bajti += delcek
        if len(odg_bajti) < dolzina:
            _dnevnik("zagon prek varuha ni uspel: nepopoln odgovor")
            return None
        odgovor = json.loads(odg_bajti.decode("utf-8"))
        if odgovor.get("ok"):
            return int(odgovor.get("pid") or 0)
        _dnevnik("zagon prek varuha zavrnjen: %s" % odgovor.get("napaka"))
        return None
    except Exception as e:
        _dnevnik("zagon prek varuha izjema: %s" % e)
        return None
    finally:
        try:
            c1.close()
        except OSError:
            pass


def utrip_glib(GLib, vsakih_s: int = UTRIP_S) -> int:
    """Utrip iz glavne zanke GLib (Safeer OS), enkrat na proces: ce se zanka zatakne, utripa ni in varuh to vidi."""
    if not pripravi_obvestila() or _obvestila["utrip"]:
        return _obvestila["utrip"]
    obvesti("WATCHDOG=1")
    _obvestila["utrip"] = GLib.timeout_add_seconds(vsakih_s, lambda: (obvesti("WATCHDOG=1"), True)[1])
    return _obvestila["utrip"]


# ---------------------------------------------------------------------------------------------- nastavitve varuha
#: Najvec napak (sesutje, zamrznitev, preraslo mejo) v oknu; potem varuh odneha - enako kot zaganjalnik do 1.0.126.
NAJVEC_NAPAK = 5
OKNO_NAPAK_S = 600
#: Zamik pred ponovnim zagonom: zacetni * 2**(n-1), najvec NAJVEC_ZAMIK_S.
NAJVEC_ZAMIK_S = 30.0
#: Zamrznitev: toliko sekund brez utripa. Safeer OS ima vec casa - glavna nit ima kdaj kratke sinhrone posege (GStreamer,
#: nov spletni proces); lazna zamrznitev bi prekinila uporabnikovo delo. Do prvega READY=1 velja ZAGON_* (hladen zagon).
ZAMRZNITEV_OS_S = 30
ZAMRZNITEV_LUPINA_S = 8
ZAGON_OS_S = 120
ZAGON_LUPINA_S = 60
#: Scit (core/scit_proces.py) utripa vsako sekundo, ko razresevalnik odgovori: zataknjen Scit zamenjamo v nekaj sekundah
#: (prej je zamrznjen Safeer OS Scit ustavil za ~30 s, odpornost 20. 10. 2026). Vrata medtem drzi varuh. systemd-resolved
#: ob prvi neodgovorjeni poizvedbi po ~0,75 s preide na naslednji streznik (usmerjevalnik) in tam ostane, dokler ga nov
#: Scit ob zagonu ne vrne (_uporabi) - zato je meja cim krajsa, a z rezervo za tri izgubljene utripe.
ZAMRZNITEV_SCIT_S = 5
ZAGON_SCIT_S = 45
USTAVI_SCIT_S = 10
#: Scit je storitev za ves racunalnik: varuh nad njim ne obupa za vedno (lokalni program bi ga sicer lahko z nekaj
#: zaporednimi napakami izklopil do konca seje). Po obupu so vrata zaprta in DNS vrnjen usmerjevalniku; cez toliko
#: sekund varuh vrata odpre znova in Scit zazene (neodvisni pregled 1.0.129).
OBUP_SCIT_PREMOR_S = 300
#: Po SIGABRT (sled) toliko sekund do SIGKILL.
ABORT_DO_KILL_S = 5
#: Ustavljanje (SIGTERM): Safeer OS vrne DNS Scita, pospravi Splet (do 5 s za WebKit) - nato SIGKILL.
USTAVI_OS_S = 15
USTAVI_LUPINA_S = 5
#: Pred (ponovnim) zagonom mora biti vsaj toliko prostega pomnilnika (MemAvailable), sicer varuh caka.
PROST_OS_MIB = 300
PROST_LUPINA_MIB = 80
#: Meja RSS glavnega procesa (MiB; spletni procesi WebKit imajo svoje meje). Nad njo: miren ponovni zagon s stanjem.
#: Lupina ima ob mirovanju ~330 MiB RSS (Xvfb, programski OpenGL, 1920x1080; izmerjeno 18. 10. 2026), na zaslonu 4K
#: vec - meja lovi uhajanje pomnilnika, ne obicajne rabe.
MEJA_LUPINA_MIB = 1536
MEJA_OS_DELEZ = 0.5          # polovica pomnilnika racunalnika
POMNILNIK_VSAKIH_S = 10
#: Najdaljse spanje zanke varuha (s). Zanka se sicer zbudi ob obvestilu otroka, signalu (tudi SIGCHLD) ali roku
#: (zamrznitev, SIGKILL, ponovni zagon, meritev pomnilnika) - ne vec vsakih 0,5 s (2 bujenji/s v mirovanju).
NAJVEC_SPANJE_S = 10.0
#: oom_score_adj (0 = privzeto): v stiski OOM izbere Safeer OS (stanje se obnovi), ne lupine ali drugih programov.
OOM_OS = 200
#: Stanje (zavihki, okna, predvajanje) se ob ponovnem zagonu obnovi - razen ce je pravkar obnovljeni proces padel prej
#: kot v toliko sekundah: kriva je morda prav obnovljena stran, zato je naslednji zagon brez nje (brez zanke).
OBNOVA_PO_S = 30
#: Izhodna koda »nova razlicica« (core/nova_razlicica.KODA_ZNOVA).
KODA_ZNOVA = 75
NACINI = ("--namizje", "--delovna", "--okno", "--predvajalnik", "--ozadje")

BESEDILA = {
    "sl": {"os": "Safeer OS se je večkrat zapored ustavil",
           "os_opis": "Namizje ostane. Na namizju izberite »Zaženi znova« ali se znova prijavite.",
           "lupina": "Namizje Safeer se je večkrat zapored ustavilo",
           "lupina_opis": "Safeer OS teče naprej. Namizje se vrne ob naslednji prijavi."},
    "en": {"os": "Safeer OS stopped several times in a row",
           "os_opis": "The desktop stays. Choose “Start again” on the desktop or sign in again.",
           "lupina": "The Safeer desktop stopped several times in a row",
           "lupina_opis": "Safeer OS keeps running. The desktop comes back at your next sign-in."},
    "de": {"os": "Safeer OS wurde mehrmals hintereinander beendet",
           "os_opis": "Der Desktop bleibt. Wählen Sie auf dem Desktop „Erneut starten“ oder melden Sie sich neu an.",
           "lupina": "Der Safeer-Desktop wurde mehrmals hintereinander beendet",
           "lupina_opis": "Safeer OS läuft weiter. Der Desktop kommt bei der nächsten Anmeldung zurück."},
    "es": {"os": "Safeer OS se ha detenido varias veces seguidas",
           "os_opis": "El escritorio sigue. Elige «Iniciar de nuevo» en el escritorio o vuelve a iniciar sesión.",
           "lupina": "El escritorio de Safeer se ha detenido varias veces seguidas",
           "lupina_opis": "Safeer OS sigue en marcha. El escritorio vuelve en el próximo inicio de sesión."},
    "fr": {"os": "Safeer OS s'est arrêté plusieurs fois de suite",
           "os_opis": "Le bureau reste. Choisissez « Redémarrer » sur le bureau ou reconnectez-vous.",
           "lupina": "Le bureau Safeer s'est arrêté plusieurs fois de suite",
           "lupina_opis": "Safeer OS continue de fonctionner. Le bureau revient à la prochaine connexion."},
    "it": {"os": "Safeer OS si è fermato più volte di seguito",
           "os_opis": "Il desktop resta. Scegli «Avvia di nuovo» sul desktop o accedi di nuovo.",
           "lupina": "Il desktop di Safeer si è fermato più volte di seguito",
           "lupina_opis": "Safeer OS continua a funzionare. Il desktop torna al prossimo accesso."},
}


def jezik(okolje=None) -> str:
    """Isti vrstni red kot safeer_os._jezik: nastavitev Safeer Browserja, sicer jezik seje."""
    import json
    okolje = os.environ if okolje is None else okolje
    koren = okolje.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    try:
        with open(os.path.join(koren, "safeer-mint", "settings.json"), encoding="utf-8") as d:
            v = str((json.load(d) or {}).get("ui_language") or "")[:2]
        if v in BESEDILA:
            return v
    except Exception:  # noqa: BLE001
        pass
    for kljuc in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        vrednost = okolje.get(kljuc, "")
        if vrednost:
            j = vrednost.split(":")[0].replace("-", "_").split(".")[0].split("_")[0].strip().lower()[:2]
            return j if j in BESEDILA else "en"
    return "en"


# ---------------------------------------------------------------------------------------------- sistem
def mapa_izvajanja() -> str:
    """$XDG_RUNTIME_DIR/safeer-os (0700): vticnici lupine in varuha, stanje varuha. Brez XDG_RUNTIME_DIR (redko: ssh brez
    seje) mapa /tmp/safeer-os-<uid>, ki mora biti nasa in zaprta - tuja ali odprta bi drugemu uporabniku dala vticnico."""
    import stat
    koren = os.environ.get("XDG_RUNTIME_DIR") or ""
    if koren and os.path.isdir(koren):
        mapa = os.path.join(koren, "safeer-os")
    else:
        mapa = os.path.join("/tmp", "safeer-os-%d" % os.getuid())
    os.makedirs(mapa, mode=0o700, exist_ok=True)
    st = os.lstat(mapa)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise PermissionError("mapa %s ni nasa" % mapa)
    if stat.S_IMODE(st.st_mode) & 0o077:
        os.chmod(mapa, 0o700)
    return mapa


def _meminfo(kljuc: str, pot: str) -> int | None:
    try:
        with open(pot, encoding="ascii") as d:
            for vrstica in d:
                if vrstica.startswith(kljuc):
                    return int(vrstica.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def prost_pomnilnik_mib(pot: str = "/proc/meminfo") -> int | None:
    return _meminfo("MemAvailable:", pot)


def ves_pomnilnik_mib(pot: str = "/proc/meminfo") -> int:
    return _meminfo("MemTotal:", pot) or 0


def rss_mib(pid: int) -> int | None:
    return _meminfo("VmRSS:", "/proc/%d/status" % pid)


def ustavljen(pid: int) -> bool:
    """Ali je proces ustavljen (SIGSTOP, razhroscevalnik): SIGABRT tak proces ne doseze, zato takoj SIGKILL."""
    try:
        with open("/proc/%d/stat" % pid, encoding="ascii", errors="replace") as d:
            return d.read().rsplit(")", 1)[1].split()[0] in ("T", "t")
    except (OSError, IndexError):
        return False


def zaslon_na_voljo(okolje=None) -> bool:
    """Ali seja se ima zaslon. Po odjavi (Ubuntu: KillUserProcesses=no) bi varuh sicer zaganjal programe brez zaslona."""
    okolje = os.environ if okolje is None else okolje
    wl = okolje.get("WAYLAND_DISPLAY", "")
    if wl:
        pot = wl if wl.startswith("/") else os.path.join(okolje.get("XDG_RUNTIME_DIR", ""), wl)
        return os.path.exists(pot)
    d = okolje.get("DISPLAY", "")
    if d.startswith(":"):
        stevilka = d[1:].split(".")[0]
        return not stevilka.isdigit() or os.path.exists("/tmp/.X11-unix/X" + stevilka)
    return True     # oddaljen zaslon (host:0) ali brez zaslona (preizkusi): ne odlocamo mi


def _dnevnik(besedilo: str) -> None:
    """Vrstica v ~/.cache/safeer-os/dnevnik.log (isti dnevnik kot zaganjalnik in os_stabilnost.zapisi, ki ga tudi
    obrezuje). Brez uvoza os_stabilnost (re, json, datetime): varuh naj ostane majhen. Nikoli ne vrze izjeme."""
    try:
        mapa = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "safeer-os")
        os.makedirs(mapa, exist_ok=True)
        with open(os.path.join(mapa, "dnevnik.log"), "a", encoding="utf-8") as d:
            d.write("%s varuh: %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), besedilo))
    except Exception:  # noqa: BLE001
        pass


class Otrok:
    """Zagnan proces (os.posix_spawn - brez modula subprocess, ki bi varuhu dodal ~1 MB)."""

    def __init__(self, argv: list, okolje: dict, izhod_fd: int | None = None, oom: int = 0,
                 podedovani: tuple = ()) -> None:
        akcije = [(os.POSIX_SPAWN_OPEN, 0, os.devnull, os.O_RDONLY, 0)]
        if izhod_fd is not None:
            akcije += [(os.POSIX_SPAWN_DUP2, izhod_fd, 1), (os.POSIX_SPAWN_DUP2, izhod_fd, 2)]
        # Vticnice, ki jih otrok podeduje kot fd 3, 4 ... (izvor je vedno > 2 + len: dup2 ne povozi drugega izvora).
        akcije += [(os.POSIX_SPAWN_DUP2, fd, 3 + i) for i, fd in enumerate(podedovani)]
        # SIGPIPE in SIGXFSZ Python ignorira; otrok naj ju dobi privzeta (kot subprocess z restore_signals).
        self.pid = os.posix_spawn(argv[0], argv, okolje, file_actions=akcije,
                                  setsigdef=(signal.SIGPIPE, signal.SIGXFSZ))
        self.returncode: int | None = None
        if oom:
            try:
                with open("/proc/%d/oom_score_adj" % self.pid, "w", encoding="ascii") as d:
                    d.write(str(oom))
            except OSError:
                pass

    def poll(self) -> int | None:
        if self.returncode is None:
            try:
                pid, status = os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:
                self.returncode = -1
                return self.returncode
            if pid:
                self.returncode = os.waitstatus_to_exitcode(status)
        return self.returncode

    def wait(self, cas: float) -> int | None:
        rok = time.monotonic() + cas
        while self.poll() is None and time.monotonic() < rok:
            time.sleep(0.05)
        return self.returncode


# ---------------------------------------------------------------------------------------------- proces
class Proces:
    """En nadzorovan otrok (lupina ali Safeer OS) in njegova pravila."""

    def __init__(self, ime: str, argv: list, okolje: dict | None = None, *, zamrznitev_s: float, zagon_s: float,
                 prost_mib: int = 0, meja_mib: int = 0, ustavi_s: float = 5, zacetni_zamik_s: float = 1.0,
                 oom: int = 0, glavni: bool = False, storitev: bool = False, podedovani: tuple = (),
                 ob_obupu=None, pred_zagonom=None, obup_premor_s: float = 0) -> None:
        self.ime, self.argv, self.okolje = ime, list(argv), dict(okolje or {})
        self.zamrznitev_s, self.zagon_s = zamrznitev_s, zagon_s
        self.prost_mib, self.meja_mib, self.ustavi_s = prost_mib, meja_mib, ustavi_s
        self.zacetni_zamik_s, self.oom, self.glavni = zacetni_zamik_s, oom, glavni
        #: Storitev (Scit): tece neodvisno od namizja - SAFEER_BREZ_LUPINE je ne izkljuci.
        self.storitev = storitev
        #: Opisniki (fd), ki jih otrok dobi kot 3, 4 ... (vticnici Scita - ostaneta odprti med ponovnimi zagoni).
        self.podedovani = tuple(podedovani)
        #: Ob obupu (namesto obvestila): Scit zapre vrata in vrne DNS, sicer bi resolved cakal na mrtva vrata.
        self.ob_obupu = ob_obupu
        #: Pred vsakim zagonom (Scit: po obupu znova odpre vrata in nastavi podedovani/okolje).
        self.pred_zagonom = pred_zagonom
        #: >0: obup ni trajen - po toliko sekundah varuh poskusi znova sam.
        self.obup_premor_s = obup_premor_s
        self.popen: Otrok | None = None
        self.zacetek = 0.0
        self.pripravljen = False
        self.zadnji_utrip = 0.0
        self.napake: list = []
        self.naslednji_zagon = 0.0
        self.obupal = False
        self.izkljucen = False
        self.zahteva = ""            # zakaj ga varuh ustavlja: "zamrznitev", "pomnilnik", "konec"
        self.kill_ob = 0.0
        self.caka_pomnilnik = False
        self.trajanje_prej = 0.0
        self.pid_prej = 0
        self.obnova_prej = False
        self.zagonov = 0

    @property
    def pid(self) -> int:
        return self.popen.pid if self.popen is not None else 0

    def tece(self) -> bool:
        return self.popen is not None and self.popen.poll() is None

    def stanje(self) -> str:
        if self.izkljucen:
            return "izkljucen"
        if self.obupal:
            return "obupal"
        if self.caka_pomnilnik:
            return "pomnilnik"
        if self.popen is not None and self.pripravljen:
            return "tece"
        return "zaganja"


class Varuh:
    """Zanka varuha. `ura` in `meminfo` sta zamenljiva za preizkuse."""

    def __init__(self, procesi: list, mapa: str, *, izhod_fd: int | None = None, ob_obupu=None,
                 ura=time.monotonic, meminfo: str = "/proc/meminfo", dnevnik=_dnevnik, okolje_zaslona=None) -> None:
        self.procesi = list(procesi)
        self.mapa = mapa
        self.izhod_fd = izhod_fd           # sled.log za stdout/stderr otrok ali None (podedujejo varuhov)
        self.ob_obupu = ob_obupu
        self.ura = ura
        self.meminfo = meminfo
        self.dnevnik = dnevnik
        self.okolje_zaslona = okolje_zaslona
        self._koncaj = False
        self._ponovi = False
        self._zadnja_meritev = 0.0
        self._zapisano = ""
        self.pot_vtic = os.path.join(mapa, "varuh-%d.sock" % os.getpid())
        self.pot_stanja = os.path.join(mapa, "varuh.json")
        try:
            os.unlink(self.pot_vtic)
        except OSError:
            pass
        self.vtic = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC | socket.SOCK_NONBLOCK)
        self.vtic.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        stara = os.umask(0o177)
        try:
            self.vtic.bind(self.pot_vtic)
        finally:
            os.umask(stara)
        self._budilka_r, self._budilka_w = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        self._zunanji_pidi: set[int] = set()

    # ------------------------------------------------------------------ signali
    def namesti_signale(self) -> None:
        signal.set_wakeup_fd(self._budilka_w, warn_on_full_buffer=False)
        for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(s, lambda *_a: setattr(self, "_koncaj", True))
        # SIGUSR1: drug zagon `safeer-os --delovna` (ali uporabnik) prosi, naj varuh poskusi znova po tem, ko je odnehal.
        signal.signal(signal.SIGUSR1, lambda *_a: setattr(self, "_ponovi", True))
        signal.signal(signal.SIGCHLD, lambda *_a: None)     # samo zbudi zanko

    def koncaj(self) -> None:
        self._koncaj = True

    # ------------------------------------------------------------------ zagon in ustavljanje otrok
    def _okolje(self, p: Proces, obnova: bool) -> dict:
        okolje = dict(os.environ)
        okolje.pop("SAFEER_OBNOVA", None)
        okolje.update(p.okolje)
        okolje["NOTIFY_SOCKET"] = self.pot_vtic
        if obnova:
            # PID prejsnjega procesa: Safeer OS obnovi samo njegovo stanje (ne starega iz prejsnje seje varuha).
            okolje["SAFEER_OBNOVA"] = str(p.pid_prej)
        return okolje

    def _zazeni(self, p: Proces) -> None:
        obnova = p.zagonov > 0 and p.pid_prej > 0 and not (p.obnova_prej and p.trajanje_prej < OBNOVA_PO_S)
        if p.pred_zagonom is not None:
            try:
                p.pred_zagonom(p)
            except Exception as e:  # noqa: BLE001
                self.dnevnik("%s pred zagonom: %s" % (p.ime, e))
        try:
            p.popen = Otrok(p.argv, self._okolje(p, obnova), self.izhod_fd, p.oom, p.podedovani)
        except OSError as e:
            p.popen = None
            self.dnevnik("%s se ni zagnal: %s" % (p.ime, e))
            self._napaka(p, "zagon: %s" % e)
            return
        p.zagonov += 1
        p.obnova_prej = obnova
        p.zacetek = self.ura()
        p.pripravljen = False
        p.zadnji_utrip = p.zacetek
        p.zahteva, p.kill_ob, p.caka_pomnilnik = "", 0.0, False
        self.dnevnik("%s zagnan (pid %d, zagon %d%s)" % (p.ime, p.pid, p.zagonov, ", obnova stanja" if obnova else ""))

    def _poslji(self, p: Proces, sig: int) -> None:
        if p.tece():
            try:
                os.kill(p.pid, sig)
            except OSError:
                pass

    def _ustavi(self, p: Proces, zahteva: str) -> None:
        """Miren konec (SIGTERM), po p.ustavi_s sekundah SIGKILL."""
        if not p.tece() or p.zahteva:
            return
        p.zahteva = zahteva
        p.kill_ob = self.ura() + p.ustavi_s
        self._poslji(p, signal.SIGTERM)

    def ustavi_vse(self) -> None:
        """SIGTERM vsem (Safeer OS vrne DNS Scita in pospravi Link, lupina konca takoj), nato SIGKILL, kdor ostane."""
        for p in self.procesi:
            self._ustavi(p, "konec")
            if p.zahteva and p.zahteva != "konec":
                self._poslji(p, signal.SIGTERM)
        rok = time.monotonic() + max([p.ustavi_s for p in self.procesi] + [0])
        while any(p.tece() for p in self.procesi) and time.monotonic() < rok:
            time.sleep(0.05)
        for p in self.procesi:
            if p.tece():
                self._poslji(p, signal.SIGKILL)
                p.popen.wait(2)

    # ------------------------------------------------------------------ obvestila otrok
    def _beri_obvestila(self) -> None:
        while True:
            try:
                podatki, pomozni, _z, _n = self.vtic.recvmsg(
                    4096, socket.CMSG_SPACE(struct.calcsize("3i")) + socket.CMSG_SPACE(struct.calcsize("i")))
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                return
            pid = 0
            prejeti_fd = None
            for raven, vrsta, vsebina in pomozni:
                if raven == socket.SOL_SOCKET and vrsta == socket.SCM_CREDENTIALS:
                    pid, uid, _gid = struct.unpack("3i", vsebina[:12])
                    if uid != os.getuid():
                        pid = 0
                elif raven == socket.SOL_SOCKET and vrsta == socket.SCM_RIGHTS:
                    if len(vsebina) >= struct.calcsize("i"):
                        prejeti_fd = struct.unpack("i", vsebina[:struct.calcsize("i")])[0]
            p = next((x for x in self.procesi if x.tece() and x.pid == pid), None) if pid else None
            if p is None and not (getattr(self, "_dovoli_vse_otroke", False) and pid):
                if prejeti_fd is not None:
                    try:
                        os.close(prejeti_fd)
                    except OSError:
                        pass
                continue
            for vrstica in podatki.decode("utf-8", "replace").split("\n"):
                kljuc, _, vrednost = vrstica.partition("=")
                if kljuc == "READY" and vrednost == "1":
                    if p is not None and not p.pripravljen:
                        self.dnevnik("%s pripravljen v %.1f s" % (p.ime, self.ura() - p.zacetek))
                    if p is not None:
                        p.pripravljen = True
                        p.zadnji_utrip = self.ura()
                elif kljuc == "WATCHDOG" and vrednost == "1":
                    if p is not None:
                        p.zadnji_utrip = self.ura()
                elif kljuc == "SAFEER_ZNOVA" and vrednost == "1":
                    # Gumb »Zazeni znova« na namizju (lupina): Safeer OS, ki ga je varuh opustil, poskusi znova.
                    self._ponovi = True
                elif kljuc == "SAFEER_BREZ_LUPINE" and vrednost == "1" and p is not None and p.glavni:
                    # Safeer OS lupine ne more streci (vticnica) in je odprl svojo delovno povrsino: lupino ugasnemo.
                    for drug in self.procesi:
                        if drug is not p and not drug.storitev:
                            drug.izkljucen = True
                            self._ustavi(drug, "konec")
                    self.dnevnik("Safeer OS ne streze lupine: lupina izkljucena")
                elif kljuc == "SAFEER_ZAZENI" and prejeti_fd is not None and p is not None and p.glavni:
                    # Samo Safeer OS (glavni proces pod varuhom) sme zahtevati zagon uporabnikovega programa - ne Scit,
                    # ne lupina (pregled 21. 10. 2026: najmanjsa pravica, Scit je izpostavljen omrezju).
                    self._obdelaj_zagon(prejeti_fd)
                    prejeti_fd = None
            if prejeti_fd is not None:
                try:
                    os.close(prejeti_fd)
                except OSError:
                    pass

    def _obdelaj_zagon(self, fd: int) -> None:
        """Zahteva za zagon uporabnikovega programa prek varuha (oom_score_adj 0)."""
        import json
        try:
            with socket.socket(fileno=fd) as srv:
                srv.settimeout(2.0)
                glava = srv.recv(4)
                if len(glava) != 4:
                    return
                dolzina = struct.unpack(">I", glava)[0]
                if dolzina <= 0 or dolzina > 1024 * 1024:
                    return
                vsebina = bytearray()
                while len(vsebina) < dolzina:
                    delcek = srv.recv(min(4096, dolzina - len(vsebina)))
                    if not delcek:
                        break
                    vsebina += delcek
                if len(vsebina) < dolzina:
                    return
                zahteva = json.loads(vsebina.decode("utf-8"))
                ukaz = zahteva.get("ukaz") or []
                okolje = zahteva.get("okolje")
                izid = self._zazeni_uporabnikov(ukaz, okolje)
                odg = json.dumps(izid, ensure_ascii=False).encode("utf-8")
                srv.sendall(struct.pack(">I", len(odg)) + odg)
        except Exception as e:
            self.dnevnik("zagon programa napaka: %s" % e)

    def _zazeni_uporabnikov(self, ukaz: list, okolje: dict | None = None) -> dict:
        """Zazene zunanji program v svoji seji (start_new_session=True), z oom_score_adj=0 (podeduje od varuha)."""
        import shutil
        import subprocess
        if not ukaz or not ukaz[0] or any("\0" in str(d) for d in ukaz):
            return {"ok": False, "napaka": "neveljaven ukaz"}
        ukaz = [str(d) for d in ukaz]

        from core import zasebni_webkit
        cisto = zasebni_webkit.okolje_za_zunanje(os.environ if okolje is None else okolje)
        cisto.pop("NOTIFY_SOCKET", None)
        cisto.pop("SAFEER_OBNOVA", None)
        for k in list(cisto):
            if k.startswith("SAFEER_") and k != "SAFEER_DEBUG":
                cisto.pop(k, None)

        try:
            proc = subprocess.Popen(
                ukaz,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=cisto,
            )
            self._zunanji_pidi.add(proc.pid)
            self.dnevnik("uporabnikov program zagnan: %s (pid %d)" % (ukaz[0], proc.pid))
            return {"ok": True, "pid": proc.pid}
        except Exception as e:
            return {"ok": False, "napaka": str(e)}

    # ------------------------------------------------------------------ korak zanke
    def _napaka(self, p: Proces, razlog: str) -> None:
        zdaj = self.ura()
        p.napake = [t for t in p.napake if zdaj - t < OKNO_NAPAK_S] + [zdaj]
        n = len(p.napake)
        if n >= NAJVEC_NAPAK:
            p.obupal = True
            self.dnevnik("%s: %s - %d napak v %d min, varuh odneha" % (p.ime, razlog, n, OKNO_NAPAK_S // 60))
            if p.obup_premor_s:
                p.naslednji_zagon = zdaj + p.obup_premor_s
                self.dnevnik("%s: nov poskus cez %d s" % (p.ime, p.obup_premor_s))
            if p.ob_obupu is not None:
                try:
                    p.ob_obupu(p)
                except Exception as e:  # noqa: BLE001
                    self.dnevnik("%s ob obupu: %s" % (p.ime, e))
            elif self.ob_obupu is not None:
                try:
                    self.ob_obupu(p)
                except Exception as e:  # noqa: BLE001
                    self.dnevnik("obvestilo ob obupu: %s" % e)
            return
        zamik = min(NAJVEC_ZAMIK_S, p.zacetni_zamik_s * (2 ** (n - 1)))
        p.naslednji_zagon = zdaj + zamik
        self.dnevnik("%s: %s - znova cez %.1f s (napaka %d od %d)" % (p.ime, razlog, zamik, n, NAJVEC_NAPAK))

    def _ob_izhodu(self, p: Proces) -> int | None:
        """Otrok se je koncal. Vrne izhodno kodo varuha, ce mora varuh koncati (konec seje, nova razlicica)."""
        koda = p.popen.returncode
        zahteva = p.zahteva
        p.trajanje_prej = self.ura() - p.zacetek
        p.pid_prej = p.popen.pid
        p.popen, p.pripravljen, p.zahteva, p.kill_ob = None, False, "", 0.0
        if self._koncaj or p.izkljucen or zahteva == "konec":
            return None
        if p.glavni and not zahteva:
            if koda == 0:
                # Obicajen konec Safeer OS (odjava, »Nazaj na Cinnamon«, izklop delovne povrsine): konec namizja.
                self.dnevnik("Safeer OS se je koncal (0): konec namizja")
                return 0
            if koda == KODA_ZNOVA:
                self.dnevnik("Safeer OS: nova razlicica")
                return KODA_ZNOVA
        razlog = ("signal %d" % -koda) if koda is not None and koda < 0 else "izhod %s" % koda
        if zahteva:
            razlog = zahteva + ", " + razlog
        if p.glavni and koda is not None and koda < 0 and not zahteva:
            try:
                from core import os_stabilnost      # stetje sesutij za varni nacin (kot zaganjalnik)
                os_stabilnost.zabelezi_sesutje("safeer-os", 128 - koda)
            except Exception:  # noqa: BLE001
                pass
        self._napaka(p, razlog)
        return None

    def korak(self) -> int | None:
        """En obhod: obvestila, izhodi, zamrznitve, pomnilnik, zagoni. Vrne izhodno kodo, ko se mora varuh koncati."""
        self._beri_obvestila()
        # Poberi koncane zunanje procese (preprecevanje zombijev)
        for zpid in list(self._zunanji_pidi):
            try:
                rpid, _ = os.waitpid(zpid, os.WNOHANG)
                if rpid == zpid:
                    self._zunanji_pidi.discard(zpid)
            except ChildProcessError:
                self._zunanji_pidi.discard(zpid)
        zdaj = self.ura()
        if self._ponovi:
            self._ponovi = False
            for p in self.procesi:
                if p.obupal and not p.izkljucen:
                    p.obupal, p.napake, p.naslednji_zagon = False, [], 0.0
                    self.dnevnik("%s: ponoven poskus na zahtevo" % p.ime)
        for p in self.procesi:
            if p.obupal and p.obup_premor_s and not p.izkljucen and p.popen is None and zdaj >= p.naslednji_zagon:
                p.obupal, p.napake = False, []
                self.dnevnik("%s: nov poskus po obupu" % p.ime)
        for p in self.procesi:
            if p.popen is not None and p.popen.poll() is not None:
                izid = self._ob_izhodu(p)
                if izid is not None:
                    return izid
        for p in self.procesi:
            if not p.tece():
                continue
            if p.kill_ob and zdaj >= p.kill_ob:
                self._poslji(p, signal.SIGKILL)
                p.kill_ob = 0.0
                continue
            if p.zahteva:
                continue
            meja = p.zamrznitev_s if p.pripravljen else p.zagon_s
            if zdaj - p.zadnji_utrip > meja:
                stoji = ustavljen(p.pid)
                self.dnevnik("%s se ne odziva %.0f s (%s): %s" % (
                    p.ime, zdaj - p.zadnji_utrip, "zamrznitev" if p.pripravljen else "zagon", "SIGKILL" if stoji else "SIGABRT"))
                p.zahteva = "zamrznitev"
                if stoji:
                    self._poslji(p, signal.SIGKILL)
                else:
                    self._poslji(p, signal.SIGABRT)      # faulthandler: sled vseh niti v sled.log
                    p.kill_ob = zdaj + ABORT_DO_KILL_S
        if zdaj - self._zadnja_meritev >= POMNILNIK_VSAKIH_S:
            self._zadnja_meritev = zdaj
            for p in self.procesi:
                if p.tece() and p.meja_mib and not p.zahteva:
                    rss = rss_mib(p.pid)
                    if rss is not None and rss > p.meja_mib:
                        self.dnevnik("%s: %d MiB > meja %d MiB - miren ponovni zagon" % (p.ime, rss, p.meja_mib))
                        self._ustavi(p, "pomnilnik")
        for p in self.procesi:
            if p.popen is not None or p.obupal or p.izkljucen or zdaj < p.naslednji_zagon:
                continue
            if not zaslon_na_voljo(self.okolje_zaslona):
                self.dnevnik("zaslona ni vec (konec seje): varuh se konca")
                return 0
            prosto = prost_pomnilnik_mib(self.meminfo)
            if p.prost_mib and prosto is not None and prosto < p.prost_mib:
                if not p.caka_pomnilnik:
                    self.dnevnik("%s caka na pomnilnik: prostega %d MiB, potrebno %d MiB" % (p.ime, prosto, p.prost_mib))
                p.caka_pomnilnik = True
                p.naslednji_zagon = zdaj + 2
                continue
            self._zazeni(p)
        self._zapisi_stanje()
        return None

    def do_roka(self) -> float:
        """Koliko sekund zanka lahko spi: do najblizjega roka - zamrznitev (zadnji utrip + meja), SIGKILL po SIGTERM ali
        SIGABRT, (ponovni) zagon, meritev pomnilnika. Obvestila, konec otroka (SIGCHLD) in signali zbudijo zanko prej."""
        zdaj = self.ura()
        roki = [self._zadnja_meritev + POMNILNIK_VSAKIH_S]
        for p in self.procesi:
            if p.tece():
                if p.kill_ob:
                    roki.append(p.kill_ob)
                if not p.zahteva:
                    # korak() zamrznitev zazna sele, ko je cas od utripa VECJI od meje
                    roki.append(p.zadnji_utrip + (p.zamrznitev_s if p.pripravljen else p.zagon_s) + 0.05)
            elif p.popen is not None:
                roki.append(zdaj)                 # koncan, se ne pobran: takoj
            elif not (p.obupal or p.izkljucen) or (p.obupal and p.obup_premor_s and not p.izkljucen):
                roki.append(p.naslednji_zagon)
        return max(0.0, min(min(roki) - zdaj, NAJVEC_SPANJE_S))

    def _zapisi_stanje(self) -> None:
        """varuh.json za lupino (obvestilo na namizju) in drug zagon (SIGUSR1). Brez modula json (velikost varuha)."""
        deli = ['"%s": {"napak": %d, "pid": %d, "stanje": "%s"}' % (p.ime, len(p.napake), p.pid, p.stanje())
                for p in self.procesi]
        besedilo = '{"pid": %d, "procesi": {%s}}' % (os.getpid(), ", ".join(deli))
        if besedilo == self._zapisano:
            return
        self._zapisano = besedilo
        zacasna = self.pot_stanja + ".tmp"
        try:
            fd = os.open(zacasna, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_CLOEXEC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as d:
                d.write(besedilo)
            os.replace(zacasna, self.pot_stanja)
        except OSError:
            pass

    def tek(self) -> int:
        """Glavna zanka do konca seje. Vrne 0 (konec) ali KODA_ZNOVA (nova razlicica)."""
        try:
            while not self._koncaj:
                izid = self.korak()
                if izid is not None:
                    self.ustavi_vse()
                    return izid
                try:
                    select.select([self.vtic, self._budilka_r], [], [], self.do_roka())
                except InterruptedError:
                    pass
                try:
                    while os.read(self._budilka_r, 512):
                        pass
                except OSError:
                    pass
            self.dnevnik("konec seje (signal)")
            self.ustavi_vse()
            return 0
        finally:
            self.pospravi()

    def pospravi(self) -> None:
        for pot in (self.pot_vtic, self.pot_stanja):
            try:
                os.unlink(pot)
            except OSError:
                pass


# ---------------------------------------------------------------------------------------------- obvestilo uporabniku
def obvesti_uporabnika(naslov: str, besedilo: str) -> bool:
    """Obvestilo namizja brez Gtk: org.freedesktop.Notifications.Notify po vodilu seje (ista pot kot core/obvestila.py
    brez Gio.Application), klic z gdbus - Gio (gi, +MB) v varuhu ne nalagamo. Samo ob obupu (redko), zato subprocess
    tu (leni uvoz). Brez notify-send (pravilo tests/test_obvestila.py): gdbus je del GLib (libglib2.0-bin je v
    odvisnostih .deb, build_os_deb.sh; v Flatpaku ovoj /app/host-bin, packaging/flatpak_host_wrappers.sh)."""
    import shutil
    import subprocess
    if not shutil.which("gdbus"):
        return False
    ukaz = ["gdbus", "call", "--session", "--timeout", "5", "--dest", "org.freedesktop.Notifications",
            "--object-path", "/org/freedesktop/Notifications", "--method", "org.freedesktop.Notifications.Notify",
            "Safeer OS", "0", "safeer-os", naslov, besedilo, "[]", "{'urgency': <byte 2>}", "0"]
    try:
        return subprocess.run(ukaz, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# ---------------------------------------------------------------------------------------------- zagon
def lupina_mogoca(koren: str) -> bool:
    """Lupina v svojem procesu: X11 (na Waylandu --delovna nima namizja pod okni - le storitve, core/seja_prikaza.py),
    PySide6 in Namizje.qml sta na voljo, SAFEER_LUPINA ni html, SAFEER_LOCENA_LUPINA ni 0.

    PySide6 isce na istih mestih kot core/os_lupina.py (vendor paketa .deb, SAFEER_PYSIDE6 AppImage, sys.path), brez
    uvoza os_lupina (hashlib, pathlib, typing: +7 MB v varuhu)."""
    if os.environ.get("SAFEER_LOCENA_LUPINA", "1").strip() == "0":
        return False
    if os.environ.get("SAFEER_LUPINA", "qml").strip().lower() == "html":
        return False
    if not os.path.isfile(os.path.join(koren, "assets", "os", "qml", "Namizje.qml")):
        return False
    from core import seja_prikaza
    if seja_prikaza.je_wayland():
        return False
    from importlib.machinery import PathFinder
    poti = [os.path.join(koren, "vendor"), os.environ.get("SAFEER_PYSIDE6") or "/nic"] + sys.path
    return PathFinder.find_spec("PySide6", [p for p in poti if os.path.isdir(p)]) is not None


def _python(python: str) -> list:
    """Ukaz Pythona za otroka: z -s, ce ga ima varuh (zaganjalnik paketa, packaging/safeer-os-launcher) - zastavica ni v
    okolju, brez nje bi uporabnikov site-packages (pip install --user) zamenjal sistemske pakete. Kot
    core/okolje_procesa.python_ukaz, a brez uvoza (varuh ostane majhen, tests/test_varuh_procesov.py)."""
    return [python] + (["-s"] if sys.flags.no_user_site else [])


def vticnici_scita() -> tuple | None:
    """UDP in TCP vticnica na 127.0.0.1 na prvih prostih vratih Scita (core/os_scit.VRATA - isti vrstni red), z
    opisnikoma nad 9 (Otrok ju da otroku kot 3 in 4). None, ce so vsa vrata zasedena (Scit takrat poisce sam)."""
    import fcntl
    for vrata in (5354, 5355, 5356, 5357):
        u = t = None
        try:
            u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            u.bind(("127.0.0.1", vrata))
            t = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            t.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            t.bind(("127.0.0.1", vrata))
            t.listen(64)
        except OSError:
            for v in (u, t):
                if v is not None:
                    v.close()
            continue
        izid = []
        for v in (u, t):
            fd = fcntl.fcntl(v.fileno(), fcntl.F_DUPFD_CLOEXEC, 10)
            v.close()
            izid.append(socket.socket(fileno=fd))
        return tuple(izid)
    return None


def scit_v_procesu() -> bool:
    """Scit v svojem procesu (privzeto). SAFEER_SCIT_PROCES=0: kot do 1.0.128 v procesu Safeer OS (zasilni izklop)."""
    return os.environ.get("SAFEER_SCIT_PROCES", "1").strip() != "0"


class VrataScita:
    """Vticnici Scita, ki ju drzi varuh. Po obupu ju zapre (resolved takoj vprasa usmerjevalnik); pred naslednjim
    zagonom ju odpre znova - prej je nov Scit po obupu dobil SAFEER_SCIT_FDS=3,4 brez opisnikov in se ni mogel javiti
    varuhu (neodvisni pregled 1.0.129)."""

    def __init__(self, koren: str, python: str, odpri=None) -> None:
        self.koren, self.python = koren, python
        self.odpri = odpri or vticnici_scita
        self.vticnici: tuple = ()

    def pred_zagonom(self, p: Proces) -> None:
        if not self.vticnici:
            self.vticnici = self.odpri() or ()
        p.podedovani = tuple(v.fileno() for v in self.vticnici)
        if self.vticnici:
            p.okolje["SAFEER_SCIT_FDS"] = ",".join(str(3 + i) for i in range(len(self.vticnici)))
        else:
            p.okolje.pop("SAFEER_SCIT_FDS", None)       # Scit odpre svoja vrata (kot brez varuha)

    def zapri(self) -> None:
        for v in self.vticnici:
            try:
                v.close()
            except OSError:
                pass
        self.vticnici = ()

    def ob_obupu(self, p: Proces) -> None:
        # Vrata zapremo (resolved dobi »vrata zaprta« in takoj vprasa usmerjevalnika, namesto da caka na vsako ime) in
        # vmesnikom vrnemo DNS usmerjevalnika - brez filtra, a racunalnik ima DNS.
        self.zapri()
        p.podedovani = ()
        p.okolje.pop("SAFEER_SCIT_FDS", None)
        import subprocess
        try:
            subprocess.run([*_python(self.python), os.path.join(self.koren, "core", "scit_proces.py"),
                            "--pospravi"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        except (OSError, subprocess.SubprocessError):
            pass


def sestavi(argumenti: list, koren: str, python: str, mapa: str) -> list:
    """Procesi za delovno povrsino: Scit (v svojem procesu), lupina (ce je mogoca) in Safeer OS."""
    procesi = []
    okolje_os = {"SAFEER_OS_NADZOR": str(os.getpid())}
    if scit_v_procesu():
        vrata = VrataScita(koren, python)
        vtic_scita = os.path.join(mapa, "scit.sock")
        okolje_os["SAFEER_SCIT_VTIC"] = vtic_scita
        # Prvi na seznamu: zazene se pred Safeer OS, ki ga ob zagonu vprasa za stanje. Vrata odpre pred_zagonom.
        scit = Proces("safeer-scit", [*_python(python), os.path.join(koren, "core", "scit_proces.py")],
                      {"SAFEER_SCIT_VTIC": vtic_scita}, zamrznitev_s=ZAMRZNITEV_SCIT_S, zagon_s=ZAGON_SCIT_S,
                      ustavi_s=USTAVI_SCIT_S, zacetni_zamik_s=0.2, storitev=True, ob_obupu=vrata.ob_obupu,
                      pred_zagonom=vrata.pred_zagonom, obup_premor_s=OBUP_SCIT_PREMOR_S)
        scit.vrata = vrata
        procesi.append(scit)
    if lupina_mogoca(koren):
        vtic = os.environ.get("SAFEER_LUPINA_VTIC") or os.path.join(mapa, "lupina.sock")
        okolje_os["SAFEER_LUPINA_VTIC"] = vtic
        procesi.append(Proces("safeer-lupina", [*_python(python), os.path.join(koren, "core", "lupina_proces.py")],
                              {"SAFEER_LUPINA_VTIC": vtic}, zamrznitev_s=ZAMRZNITEV_LUPINA_S, zagon_s=ZAGON_LUPINA_S,
                              prost_mib=PROST_LUPINA_MIB, meja_mib=MEJA_LUPINA_MIB, ustavi_s=USTAVI_LUPINA_S,
                              zacetni_zamik_s=0.5))
    meja_os = int(ves_pomnilnik_mib() * MEJA_OS_DELEZ)
    procesi.append(Proces("safeer-os", [*_python(python), os.path.join(koren, "safeer_os.py")] + list(argumenti),
                          okolje_os,
                          zamrznitev_s=ZAMRZNITEV_OS_S, zagon_s=ZAGON_OS_S, prost_mib=PROST_OS_MIB, meja_mib=meja_os,
                          ustavi_s=USTAVI_OS_S, zacetni_zamik_s=1.0, oom=OOM_OS, glavni=True))
    return procesi


def _ob_obupu(koren: str, python: str):
    def obup(p: Proces) -> None:
        b = BESEDILA.get(jezik(), BESEDILA["en"])
        if p.glavni:
            # Mint je varnostna mreza: pult mora biti viden, tudi ce ga je Safeer OS skril (kot zaganjalnik).
            import subprocess
            try:
                subprocess.run([*_python(python), os.path.join(koren, "safeer_os.py"), "--vrni-mint"],
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
            except (OSError, subprocess.SubprocessError):
                pass
            obvesti_uporabnika(b["os"], b["os_opis"])
        else:
            obvesti_uporabnika(b["lupina"], b["lupina_opis"])
    return obup


def _zakleni(mapa: str):
    """En varuh na sejo (flock; sprosti se sam, tudi ob sesutju). None, ce ze tece drug."""
    import fcntl
    d = open(os.path.join(mapa, "varuh.zaklep"), "ab")  # noqa: SIM115 - odprta ostane do konca varuha (samo flock)
    try:
        fcntl.flock(d, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return d
    except OSError:
        d.close()
        return None


def _pid_varuha(mapa: str) -> int:
    try:
        with open(os.path.join(mapa, "varuh.json"), encoding="utf-8") as d:
            besedilo = d.read()
        return int(besedilo.split('"pid":', 1)[1].split(",", 1)[0])
    except (OSError, ValueError, IndexError):
        return 0


def main(argumenti: list | None = None) -> int:
    argumenti = list(sys.argv[1:] if argumenti is None else argumenti)
    koren = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    python = sys.executable or "/usr/bin/python3"
    mapa = mapa_izvajanja()
    zaklep = _zakleni(mapa)
    if zaklep is None:
        # Varuh ze tece (drug zagon ob prijavi ali iz safeer-cinnamon): naj poskusi znova, ce je odnehal, in konec.
        pid = _pid_varuha(mapa)
        if pid > 1:
            try:
                os.kill(pid, signal.SIGUSR1)
            except OSError:
                pass
        return 0
    izhod_fd = None
    if not sys.stderr.isatty():
        # Kot zaganjalnik: stdout in stderr otrok (print, g_warning, sled faulthandlerja) v sled.log - obrezuje ga
        # Safeer OS (os_stabilnost.vkljuci).
        try:
            mapa_sledi = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "safeer-os")
            os.makedirs(mapa_sledi, exist_ok=True)
            izhod_fd = os.open(os.path.join(mapa_sledi, "sled.log"), os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_CLOEXEC,
                               0o600)
        except OSError:
            izhod_fd = None
    varuh = Varuh(sestavi(argumenti, koren, python, mapa), mapa, izhod_fd=izhod_fd, ob_obupu=_ob_obupu(koren, python))
    varuh.namesti_signale()
    _dnevnik("varuh %d: %s" % (os.getpid(), ", ".join(p.ime for p in varuh.procesi)))
    koda = varuh.tek()
    if koda == KODA_ZNOVA:
        # Nova razlicica (core/nova_razlicica.py): zaganjalnik NOVE razlicice z istim nacinom (isti PID za sejo).
        nacin = [a for a in argumenti if a in NACINI]
        zaganjalnik = os.environ.get("SAFEER_ZAGANJALNIK", "")
        zaklep.close()
        if zaganjalnik and os.access(zaganjalnik, os.X_OK):
            os.execv(zaganjalnik, [zaganjalnik] + nacin)
        os.execv(python, _python(python) + [os.path.abspath(__file__)] + nacin)
    return koda


if __name__ == "__main__":
    sys.exit(main())
