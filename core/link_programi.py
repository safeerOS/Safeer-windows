"""Programi racunalnika za televizor (Safeer OS) prek Safeer Linka.

Uporabnik na racunalniku enkrat dovoli, da televizor vidi njegove programe (privzeto NE).
Takrat Control prebere namizne vnose XDG (`.desktop`: sistemski, uporabnikovi, Flatpak, Snap)
in televizorju poslje samo to, kar potrebuje za ploscico: oznako, ime, opis in ikono.

Televizor nikoli ne poslje ukaza ali poti - poslje samo **oznako** s tega seznama
(`app:<ime datoteke>.desktop`). Control jo poisce med svojimi vnosi in program zazene z
`gio launch` (ali `gtk-launch`), torej natanko tako, kot bi ga uporabnik kliknil v svojem meniju.
Lupine ni; kar ni na seznamu, se ne zazene.

Seznam programov je oseben podatek, zato gre samo napravam v Safeer Linku, ki jih je uporabnik
seznanil, in samo, dokler je moznost vklopljena.
"""

from __future__ import annotations

import base64
import configparser
import os
import shlex
import shutil
import signal
import subprocess
from typing import Dict, List, Optional

from core.link_mediji import profil_programa

NAJVEC = 200
IKONA_VELIKOST = 128
PREDPONA = "app:"

# Kategorije, ki na televizorju nimajo smisla (nastavitve sistema, konzolna orodja).
IZPUSTI_KATEGORIJE = {"Settings", "System", "ConsoleOnly", "Screensaver"}

# Skupine, po katerih televizor razvrsti programe (na sto programih je abecedni seznam prevec).
# Kljuc je nasa oznaka, vrednost so kategorije XDG, ki vanjo sodijo - isto delitev pozna uporabnik
# ze iz menija svojega namizja. Vrstni red steje: prva skupina, ki se ujame, obvelja, zato je
# Igra pred vsem drugim (igra z glasbo je se vedno igra).
SKUPINE = (
    ("igre", {"Game", "ActionGame", "AdventureGame", "ArcadeGame", "BoardGame", "BlocksGame",
              "CardGame", "KidsGame", "LogicGame", "RolePlaying", "Shooter", "Simulation",
              "SportsGame", "StrategyGame", "Emulator"}),
    ("programiranje", {"Development", "IDE", "Building", "Debugger", "GUIDesigner", "Profiling",
                       "RevisionControl", "Translation", "WebDevelopment"}),
    ("pisarna", {"Office", "WordProcessor", "Spreadsheet", "Presentation", "Calendar", "Finance",
                 "ContactManagement", "Database", "Dictionary", "Publishing",
                 "ProjectManagement", "TextEditor"}),
    ("predstavnost", {"AudioVideo", "Audio", "Video", "Graphics", "Photography", "Music",
                      "Player", "Recorder", "TV", "Midi", "Mixer", "Sequencer", "Tuner",
                      "RasterGraphics", "VectorGraphics", "3DGraphics", "Scanning", "OCR"}),
    ("splet", {"Network", "WebBrowser", "Email", "InstantMessaging", "Chat", "IRCClient",
               "FileTransfer", "News", "P2P", "RemoteAccess", "Telephony", "VideoConference",
               "WebSearch", "Feed"}),
    ("ucenje", {"Education", "Science", "Math", "NumericalAnalysis", "Astronomy", "Biology",
                "Chemistry", "ComputerScience", "Geography", "Geology", "History", "Languages",
                "Literature", "Music Education", "Physics", "Sports"}),
    ("orodja", {"Utility", "Accessibility", "Archiving", "Compression", "FileTools",
                "FileManager", "TerminalEmulator", "Monitor", "Security", "Printing",
                "PackageManager", "Calculator", "Clock", "Documentation"}),
)
#: Program brez uporabne kategorije: raje posteno "drugo" kot napacna skupina.
PRIVZETA_SKUPINA = "drugo"


def skupina(kategorije) -> str:
    """Nasa skupina za kategorije XDG enega namiznega vnosa."""
    nabor = set(kategorije or ())
    for oznaka, kategorije_skupine in SKUPINE:
        if nabor & kategorije_skupine:
            return oznaka
    return PRIVZETA_SKUPINA
# Vnosi, ki jih ne ponujamo, ker so del Safeerja samega ali brez okna.
IZPUSTI_OZNAKE = {"safeer-control.desktop"}


def _mape_vnosov() -> List[str]:
    doma = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    sistem = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    mape = [os.path.join(doma, "applications")]
    for d in sistem.split(":"):
        if d:
            mape.append(os.path.join(d, "applications"))
    # Flatpak in Snap nista vedno v XDG_DATA_DIRS (npr. pri zagonu iz seje brez profila).
    mape.append("/var/lib/flatpak/exports/share/applications")
    mape.append(os.path.join(doma, "flatpak/exports/share/applications"))
    mape.append("/var/lib/snapd/desktop/applications")
    vidne: List[str] = []
    for m in mape:
        p = os.path.realpath(m)
        if p not in vidne and os.path.isdir(p):
            vidne.append(p)
    return vidne


def _jezik() -> List[str]:
    """Kljuci imen po jeziku okolja: Name[sl_SI], Name[sl], Name."""
    lang = (os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or "").split(".")[0]
    kljuci = []
    if lang:
        kljuci.append(lang)
        if "_" in lang:
            kljuci.append(lang.split("_")[0])
    return kljuci


def _vrednost(vnos: configparser.SectionProxy, kljuc: str) -> str:
    for jezik in _jezik():
        v = vnos.get(f"{kljuc}[{jezik}]")
        if v:
            return v
    return vnos.get(kljuc, "") or ""


class Programi:
    """Namizni vnosi racunalnika; brez dovoljenja uporabnika prazno."""

    def __init__(self, vklopljeno: bool = False, mape: Optional[List[str]] = None) -> None:
        self.vklopljeno = bool(vklopljeno)
        self._mape = list(mape) if mape is not None else None   # None = poisci sam (testi jih podajo)
        self.ob_spremembi = None          # klicatelj shrani nastavitev
        self._vnosi: Dict[str, dict] = {}  # oznaka -> {"pot", "ime", "opis", "ikona"}
        #: Locen zaslon za televizor (core.link_sway.DrugiZaslon) ali None: potem se program odpre
        #: na uporabnikovem namizju, kot doslej.
        self.drugi = None

    # ------------------------------------------------------------------ nastavitev
    def nastavi(self, vklopljeno: bool) -> None:
        self.vklopljeno = bool(vklopljeno)
        if not self.vklopljeno:
            self._vnosi = {}
        if self.ob_spremembi is not None:
            try:
                self.ob_spremembi(self.vklopljeno)
            except Exception:
                pass

    # ------------------------------------------------------------------ branje vnosov
    def _preberi(self) -> Dict[str, dict]:
        najdeni: Dict[str, dict] = {}
        # Dvakrat isti napis je na televizorju uganka, ne izbira: en program je pogosto namescen
        # dvakrat (sistemsko in kot Flatpak), vcasih pa imata dva razlicna programa isto ime
        # ("Archive Manager", "Help"). Obdrzimo prvega - mape beremo po vrsti, kot jih gleda
        # namizje, torej uporabnikove pred sistemskimi in te pred Flatpakom.
        videna_imena = set()
        for mapa in (self._mape if self._mape is not None else _mape_vnosov()):
            try:
                imena = sorted(os.listdir(mapa))
            except OSError:
                continue
            for ime in imena:
                if not ime.endswith(".desktop") or ime in IZPUSTI_OZNAKE or ime in najdeni:
                    continue
                pot = os.path.join(mapa, ime)
                podatki = self._vnos(pot)
                if podatki is not None:
                    kljuc_imena = podatki["ime"].strip().lower()
                    if kljuc_imena in videna_imena:
                        continue
                    videna_imena.add(kljuc_imena)
                    najdeni[ime] = podatki
                if len(najdeni) >= NAJVEC:
                    break
        return najdeni

    def _vnos(self, pot: str) -> Optional[dict]:
        razclen = configparser.RawConfigParser(strict=False)
        razclen.optionxform = str
        try:
            with open(pot, encoding="utf-8", errors="replace") as f:
                razclen.read_file(f)
        except Exception:
            return None
        if not razclen.has_section("Desktop Entry"):
            return None
        vnos = razclen["Desktop Entry"]
        if vnos.get("Type", "") != "Application":
            return None
        if (vnos.get("NoDisplay", "") or "").lower() == "true":
            return None
        if (vnos.get("Hidden", "") or "").lower() == "true":
            return None
        if (vnos.get("Terminal", "") or "").lower() == "true":
            return None          # konzolna orodja na televizorju nimajo smisla
        kategorije = {k for k in (vnos.get("Categories", "") or "").split(";") if k}
        if kategorije & IZPUSTI_KATEGORIJE:
            return None
        poskusi = vnos.get("TryExec", "") or ""
        if poskusi and not (os.path.isabs(poskusi) and os.access(poskusi, os.X_OK)) and not shutil.which(poskusi):
            return None          # program ni namescen
        ime = _vrednost(vnos, "Name").strip()
        if not ime:
            return None
        return {"pot": pot, "ime": ime, "opis": _vrednost(vnos, "Comment").strip(),
                "ikona": (vnos.get("Icon", "") or "").strip(), "skupina": skupina(kategorije),
                "profil": profil_programa(kategorije, pot, vnos.get("Exec", "") or "")}

    # ------------------------------------------------------------------ za Safeer Link
    def seznam(self, z_ikonami: bool = True, od: int = 0, koliko: int = 0) -> dict:
        """Odgovor na `apps.list`: {"enabled", "items", "total", "offset"}.

        Ikone so PNG v base64 in seznam je lahko dolg (na tem racunalniku 84 programov), sporocila
        v Safeer Linku pa so omejena na 256 kB - cel seznam z ikonami je bil prevelik in je padel
        skozi. Zato ga posiljamo po kosih: [od, od+koliko). `koliko = 0` pomeni vse (za teste in
        odjemalce brez strani).
        """
        if not self.vklopljeno:
            return {"enabled": False, "items": [], "total": 0, "offset": 0}
        self._vnosi = self._preberi()
        urejeni = sorted(self._vnosi.items(), key=lambda p: p[1]["ime"].lower())
        skupaj = len(urejeni)
        od = max(0, int(od or 0))
        kos = urejeni[od:od + koliko] if koliko else urejeni[od:]
        vnosi = []
        for oznaka, v in kos:
            element = {"id": PREDPONA + oznaka, "name": v["ime"], "comment": v["opis"],
                       "group": v.get("skupina", PRIVZETA_SKUPINA)}
            if z_ikonami:
                ikona = self._ikona(v["ikona"])
                if ikona:
                    element["icon_png"] = ikona
            vnosi.append(element)
        return {"enabled": True, "items": vnosi, "total": skupaj, "offset": od}

    def katalog_v1(self) -> dict:
        """Protocol v1: katalog za prijavo v Safeer Link - {"app:<vnos>.desktop": {"name", "kind"}}.

        Brez ikon in opisov (hub hrani najvec 200 vnosov in 32 KiB); ikone da `apps.list`, ko jih
        odjemalec res potrebuje. Prazen, dokler uporabnik programov za televizor ne dovoli.
        """
        if not self.vklopljeno:
            return {}
        katalog: Dict[str, dict] = {}
        velikost = 2
        for e in self.seznam(z_ikonami=False).get("items", [])[:NAJVEC]:
            vnos = {"name": str(e.get("name", ""))[:64], "kind": "linux"}
            dodatek = len(e["id"]) + len(vnos["name"]) + 40
            if velikost + dodatek > 30 * 1024:
                break
            katalog[e["id"][:64]] = vnos
            velikost += dodatek
        return katalog

    def zazeni(self, oznaka: str) -> bool:
        """Zazene program z oznako s seznama. Nic drugega; ukaza z omrezja ne izvajamo."""
        if not self.vklopljeno:
            return False
        ime = str(oznaka or "")
        if not ime.startswith(PREDPONA):
            return False
        ime = ime[len(PREDPONA):]
        if "/" in ime or not ime.endswith(".desktop"):
            return False
        if ime not in self._vnosi:
            self._vnosi = self._preberi()
        vnos = self._vnosi.get(ime)
        if vnos is None:
            return False
        pot = vnos["pot"]
        if self.drugi is not None:
            # Na drugi zaslon ukaz iz vnosa pozenemo neposredno: `gio launch` bi program z D-Bus
            # zagonom odprl na uporabnikovem zaslonu, mimo drugega.
            self.drugi.zadnja_skupina = vnos.get("skupina", "")
            # Predvajalnik (OK pavza, levo/desno previjanje) ali program za televizor (tipke).
            self.drugi.zadnji_profil = vnos.get("profil", "")
            # Ce program na drugem zaslonu ze tece, ga samo pokazemo - drugo okno bi bilo odvec.
            if self.drugi.pokazi(self._procesi(self._iskani_vzorci(ime))):
                return True
            ukaz = self._ukaz_vnosa(ime)
            if ukaz and self.drugi.zazeni_program(ukaz):
                return True
        for ukaz in (["gio", "launch", pot], ["gtk-launch", ime]):
            if shutil.which(ukaz[0]) is None:
                continue
            try:
                subprocess.Popen(ukaz, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
                return True
            except Exception:
                continue
        return False

    # ------------------------------------------------------------------ zapiranje
    # Program, ki ga uporabnik zazene s televizorja, ostane odprt, dokler ga kdo ne zapre -
    # in tega z daljincem doslej ni bilo mogoce narediti, zato so se programi kopicili in
    # jemali pomnilnik. Zapremo ga tako, kot bi uporabnik kliknil X: SIGTERM, nikoli KILL,
    # in samo procese tega uporabnika, ki se ujemajo z ukazom iz njegovega namiznega vnosa.
    _LUPINE = {"sh", "bash", "zsh", "env", "sudo", "pkexec", "gio", "gtk-launch",
               "dbus-run-session", "python", "python2", "python3", "perl", "ruby", "node",
               "wine", "xdg-open"}

    def _ime_iz_oznake(self, oznaka: str) -> Optional[str]:
        """Iz oznake `app:<ime>.desktop` dobimo ime vnosa; karkoli drugega zavrnemo."""
        ime = str(oznaka or "")
        if not ime.startswith(PREDPONA):
            return None
        ime = ime[len(PREDPONA):]
        if "/" in ime or not ime.endswith(".desktop"):
            return None
        if ime not in self._vnosi:
            self._vnosi = self._preberi()
        return ime if ime in self._vnosi else None

    def _ukaz_vnosa(self, ime: str) -> List[str]:
        """Ukaz iz .desktop brez oznak %f, %U ...; prazen seznam, ce ga ne znamo prebrati."""
        vnos = self._vnosi.get(ime)
        if vnos is None:
            return []
        try:
            b = configparser.RawConfigParser(interpolation=None, strict=False)
            b.read(vnos["pot"], encoding="utf-8")
            ukaz = _vrednost(b["Desktop Entry"], "Exec")
        except Exception:
            return []
        try:
            deli = shlex.split(str(ukaz))
        except ValueError:
            deli = str(ukaz).split()
        return [d for d in deli if not (d.startswith("%") and len(d) == 2)]

    def _iskani_vzorci(self, ime: str) -> List[str]:
        """Po cem prepoznamo proces tega programa: izvrsljiva datoteka ali id Flatpaka."""
        deli = self._ukaz_vnosa(ime)
        vzorci: List[str] = []
        prek_vsebnika = any(os.path.basename(d) in ("flatpak", "snap") for d in deli)
        if not prek_vsebnika:
            for del_ in deli:
                osnova = os.path.basename(del_)
                if osnova.startswith("-") or osnova in self._LUPINE:
                    continue
                vzorci.append(osnova)
                break
        for i, del_ in enumerate(deli):
            if os.path.basename(del_) == "flatpak":
                for kandidat in deli[i + 1:]:
                    if not kandidat.startswith("-") and "." in kandidat:
                        vzorci.append(kandidat)
                        break
        return vzorci

    def _procesi(self, vzorci: List[str]) -> List[int]:
        """PID-i procesov tega uporabnika, ki se ujemajo z vzorci (nas samih ne)."""
        if not vzorci:
            return []
        jaz = os.getpid()
        moj_uid = os.getuid()
        najdeni: List[int] = []
        for vnos in os.listdir("/proc"):
            if not vnos.isdigit():
                continue
            pid = int(vnos)
            if pid in (jaz, 1):
                continue
            try:
                if os.stat("/proc/%d" % pid).st_uid != moj_uid:
                    continue
                with open("/proc/%d/cmdline" % pid, "rb") as f:
                    surovo = f.read().decode("utf-8", "replace")
            except Exception:
                continue
            argumenti = [a for a in surovo.split("\0") if a]
            if not argumenti:
                continue
            prvi = os.path.basename(argumenti[0])
            cel = " ".join(argumenti)
            for v in vzorci:
                if prvi == v or ("." in v and v in cel):
                    najdeni.append(pid)
                    break
        return najdeni

    def tece(self, oznaka: str) -> bool:
        """Ali ta program na racunalniku res tece."""
        ime = self._ime_iz_oznake(oznaka)
        return bool(self._procesi(self._iskani_vzorci(ime))) if ime else False

    def zapri(self, oznaka: str) -> int:
        """Vljudno zapre program (SIGTERM). Vrne, koliko procesov smo prosili, naj koncajo."""
        if not self.vklopljeno:
            return 0
        ime = self._ime_iz_oznake(oznaka)
        if ime is None:
            return 0
        koliko = 0
        for pid in self._procesi(self._iskani_vzorci(ime)):
            try:
                os.kill(pid, signal.SIGTERM)
                koliko += 1
            except Exception:
                continue
        return koliko

    # ------------------------------------------------------------------ ikone
    def _ikona(self, ime: str) -> str:
        """Ikona kot PNG v base64 (televizor ne zna SVG). Prazno, ce je ne najdemo."""
        if not ime:
            return ""
        pot = ""
        if os.path.isabs(ime):
            pot = ime if os.path.isfile(ime) else ""
        else:
            # Debianovi vnosi imajo pogosto »Icon=igra.xpm«: datoteko iscemo z imenom vred, temo pa
            # brez koncnice (GTK ikone s koncnico ne najde).
            steblo = ime[:-4] if ime.lower().endswith((".png", ".svg", ".xpm")) else ime
            pot = self._poisci_ikono(ime, samo_pixmaps=True) or self._iz_teme(steblo) or self._poisci_ikono(steblo)
        if not pot:
            return ""
        try:
            import gi
            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import GdkPixbuf
            slika = GdkPixbuf.Pixbuf.new_from_file_at_size(pot, IKONA_VELIKOST, IKONA_VELIKOST)
            ok, bajti = slika.save_to_bufferv("png", [], [])
            if ok:
                return base64.b64encode(bytes(bajti)).decode("ascii")
        except Exception:
            pass
        if pot.endswith(".png"):
            try:
                with open(pot, "rb") as f:
                    return base64.b64encode(f.read()).decode("ascii")
            except OSError:
                return ""
        return ""

    @staticmethod
    def _iz_teme(ime: str) -> str:
        """Ikono najprej poiscemo tako, kot jo namizje: prek teme ikon (GTK). Brez GTK (testi) prazno."""
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk
            tema = Gtk.IconTheme.get_default()
            if tema is None:
                return ""
            najdena = tema.lookup_icon(ime, IKONA_VELIKOST, 0)
            if najdena is not None:
                pot = najdena.get_filename() or ""
                if pot and os.path.isfile(pot):
                    return pot
        except Exception:
            pass
        return ""

    def _poisci_ikono(self, ime: str, samo_pixmaps: bool = False) -> str:
        doma = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        korenine = [os.path.join(doma, "icons"), os.path.expanduser("~/.icons"),
                    "/usr/share/icons", "/usr/local/share/icons",
                    # Flatpak: sistemski in tisti, ki jih je uporabnik namestil zase (--user).
                    "/var/lib/flatpak/exports/share/icons",
                    os.path.join(doma, "flatpak/exports/share/icons")]
        velikosti = ["128x128", "96x96", "64x64", "256x256", "48x48", "scalable"]
        teme = ["hicolor", "Papirus", "Adwaita", "breeze"]
        for koren in ([] if samo_pixmaps else korenine):
            for tema in teme:
                for velikost in velikosti:
                    for konec in (".png", ".svg"):
                        pot = os.path.join(koren, tema, velikost, "apps", ime + konec)
                        if os.path.isfile(pot):
                            return pot
        for mapa in ("/usr/share/pixmaps", os.path.join(doma, "pixmaps")):
            for konec in ("", ".png", ".svg", ".xpm"):
                pot = os.path.join(mapa, ime + konec)
                if os.path.isfile(pot) and (konec or ime.lower().endswith((".png", ".svg", ".xpm"))):
                    return pot
        return ""
