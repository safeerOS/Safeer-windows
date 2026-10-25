"""Programi racunalnika za Safeer OS na Linuxu.

Safeer OS je preobleka cez Linux Mint: pokaze VSE programe, ki jih ima uporabnik v meniju svojega
namizja (sistemske, svoje, Flatpak, Snap, nastavitve Cinnamona), in jih zazene natanko tako, kot bi
jih kliknil v meniju - v njihovih lastnih oknih. Nicesar ne namesca in nicesar ne spreminja.

Poleg seznama si zapomni, kaj uporabnik odpira (za »Pogosto uporabljeno« na domacem zaslonu) in
katere programe je pripel. Oboje je v ~/.config/safeer-os/os.json in ne zapusti racunalnika.
"""

from __future__ import annotations

import configparser
import hashlib
import os
import re
import shutil
import subprocess
import time
from typing import Dict, List, Optional, Tuple

from core import gostitelj, link_programi, os_oblak_igre, shramba_json, zasebni_webkit

NAJVEC = 400
IKONA_VELIKOST = 96
MAPA_NASTAVITEV = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "safeer-os")
MAPA_IKON = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "safeer-os", "ikone")

#: Nastavitve sistema (Cinnamon, Mint) dobijo svojo skupino, da se ne mesajo med programe.
SISTEM = {"Settings", "System", "DesktopSettings", "HardwareSettings", "PackageManager", "Monitor", "Security"}
#: Orodja, ki upravljajo nastavitve sistema (iskalna lupa jih pokaze v svoji skupini »Nastavitve«).
NASTAVITVE = {"Settings", "DesktopSettings", "HardwareSettings"}
#: Besede, po katerih uporabnik isce nastavitev, pa jih vnos sam nima (ne v svojem jeziku ne v anglescini).
#: Kljuc je ime vnosa .desktop; iskanje ne gleda na sumnike.
SOPOMENKE = {
    "cinnamon-settings-power.desktop": "napajanje baterija energija varcevanje poraba spanje pokrov",
    "cinnamon-settings-display.desktop": "monitor zaslon locljivost resolucija",
    "cinnamon-display-panel.desktop": "monitor zaslon locljivost resolucija",
    "cinnamon-settings-sound.desktop": "zvocnik slusalke mikrofon glasnost",
    "cinnamon-settings-mouse.desktop": "miska touchpad sledilna ploscica kazalec",
    "cinnamon-settings-keyboard.desktop": "tipke bliznjice razporeditev",
    "cinnamon-settings-backgrounds.desktop": "ozadje slika namizja",
    "cinnamon-settings-themes.desktop": "videz tema barve ikone kazalec",
    "cinnamon-network-panel.desktop": "wifi brezzicno internet ethernet vpn",
    "cinnamon-settings-notifications.desktop": "obvestila motnje",
    "cinnamon-settings-startup.desktop": "samozagon zagon ob prijavi",
    "cinnamon-settings-users.desktop": "racun geslo",
    "cinnamon-settings-user.desktop": "racun geslo profil slika",
    "cinnamon-settings-nightlight.desktop": "nocni nacin modra svetloba",
    "cinnamon-settings-privacy.desktop": "zgodovina nedavne datoteke",
    "blueberry.desktop": "bluetooth slusalke brezzicno",
    "mintupdate.desktop": "posodobitve nadgradnja",
    "system-config-printer.desktop": "tiskalnik tiskanje",
}
#: Vrstni red skupin v pogledu »Programi«.
SKUPINE = ("splet", "pisarna", "predstavnost", "igre", "ucenje", "programiranje", "orodja", "sistem", "drugo")
#: Programi, ki so del Safeerja samega (Safeer OS ne ponuja sebe; Safeer Player je njegov Medijski center).
IZPUSTI = {"safeer-os.desktop", "io.github.memelandfaner.SafeerOS.desktop",
           "safeer-os.Player.desktop", "io.github.memelandfaner.SafeerOS.Player.desktop"}


#: Programi za Medijski center: predvajalniki po XDG ali programi za radio/glasbo/podcaste po opisu.
PREDVAJALNIK = {"Player", "TV"}
_MEDIJSKI_OPIS = re.compile(r"radio|podcast|music player|predvajalnik", re.I)


def je_predvajalnik(kategorije, besedilo: str = "") -> bool:
    """Ali program sodi v Medijski center (ne pa urejevalniki slik, skenerji, zvočni učinki ...)."""
    nabor = set(kategorije or ())
    if nabor & PREDVAJALNIK:
        return True
    return bool(nabor & {"Audio", "AudioVideo", "Video"}) and bool(_MEDIJSKI_OPIS.search(besedilo or ""))


def skupina(kategorije) -> str:
    nabor = set(kategorije or ())
    osnovna = link_programi.skupina(nabor)
    if osnovna in ("igre",):
        return osnovna
    if nabor & SISTEM:
        return "sistem"
    return osnovna


def trenutna_namizja() -> List[str]:
    namizja = [d for d in (os.environ.get("XDG_CURRENT_DESKTOP") or "").split(":") if d]
    # Safeer OS tece v seji Cinnamona; brez spremenljivke (zagon iz storitve) velja Cinnamon.
    return namizja or ["X-Cinnamon"]


def _seznam(vrednost: str) -> List[str]:
    return [d for d in (vrednost or "").split(";") if d]


def preberi_vnos(pot: str, namizja: Optional[List[str]] = None) -> Optional[dict]:
    """En namizni vnos (.desktop) v obliki za Safeer OS ali None, ce ga meni ne bi pokazal."""
    razclen = configparser.RawConfigParser(strict=False, interpolation=None)
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
    for kljuc in ("NoDisplay", "Hidden", "Terminal"):
        if (vnos.get(kljuc, "") or "").strip().lower() == "true":
            return None
    namizja = namizja if namizja is not None else trenutna_namizja()
    samo = _seznam(vnos.get("OnlyShowIn", ""))
    if samo and not set(samo) & set(namizja):
        return None
    ne = _seznam(vnos.get("NotShowIn", ""))
    if ne and set(ne) & set(namizja):
        return None
    poskusi = (vnos.get("TryExec", "") or "").strip()
    if poskusi and not (os.path.isabs(poskusi) and os.access(poskusi, os.X_OK)) and not shutil.which(poskusi):
        return None
    ime = link_programi._vrednost(vnos, "Name").strip()
    if not ime:
        return None
    kategorije = _seznam(vnos.get("Categories", ""))
    # Kljucne besede v jeziku uporabnika in anglesko (ime, splosno ime, kljucne): »display« najde »Zaslon«.
    kljucne = _seznam(link_programi._vrednost(vnos, "Keywords")) + _seznam(vnos.get("Keywords", "") or "")
    for kljuc in ("Name", "GenericName"):
        osnovno = (vnos.get(kljuc, "") or "").strip()
        if osnovno and osnovno != ime:
            kljucne.append(osnovno)
    kljucne += SOPOMENKE.get(os.path.basename(pot), "").split()
    if set(kategorije) & NASTAVITVE:
        # »nastavitve zaslona«: splosna beseda za vsa orodja nastavitev (jeziki Safeer OS in iskanja z glasom).
        kljucne += ["nastavitve", "settings", "Einstellungen", "configuración", "configurações", "paramètres", "impostazioni"]
    videne = set()
    kljucne = [k.strip() for k in kljucne if k.strip() and not (k.strip().lower() in videne or videne.add(k.strip().lower()))]
    return {
        "pot": pot,
        "ime": ime,
        "opis": (link_programi._vrednost(vnos, "Comment") or link_programi._vrednost(vnos, "GenericName")).strip(),
        "splosno": link_programi._vrednost(vnos, "GenericName").strip(),
        "ikona": (vnos.get("Icon", "") or "").strip(),
        "skupina": skupina(kategorije),
        "medij": je_predvajalnik(kategorije, ime + " " + link_programi._vrednost(vnos, "Comment") + " " +
                                 link_programi._vrednost(vnos, "GenericName")),
        "zvok": "Audio" in kategorije and "Video" not in kategorije and "TV" not in kategorije,
        "kljucne": kljucne[:40],
        "nastavitev": bool(set(kategorije) & NASTAVITVE),
    }


def oblika_namestitve(pot: str) -> str:
    """Kako je program namescen, po poti vnosa .desktop: Flatpak, Snap ali AppImage; prazno za navaden paket."""
    p = pot.replace("\\", "/")
    if "/flatpak/" in p:
        return "Flatpak"
    if "/snapd/" in p or "/snap/" in p:
        return "Snap"
    if "appimage" in p.lower():
        return "AppImage"
    return ""


class Shramba(shramba_json.Shramba):
    """os.json: uporaba programov, pripeti programi in nastavitve Safeer OS.

    Pisejo jo Safeer OS in Scit v svojem procesu (core/scit_proces.py): zapis samo spremenjenih kljucev pod zaklepom,
    atomsko s fsync (core/shramba_json.py). Prej je vsak zapis zapisal celo kopijo procesa in pokvarjena datoteka je
    tiho pomenila prazne nastavitve."""

    def __init__(self, pot: Optional[str] = None) -> None:
        super().__init__(pot or os.path.join(MAPA_NASTAVITEV, "os.json"))


class Programi:
    """Vsi programi iz menija; oznaka programa je ime njegovega .desktop vnosa."""

    def __init__(self, shramba: Shramba, mape: Optional[List[str]] = None,
                 namizja: Optional[List[str]] = None) -> None:
        self.shramba = shramba
        self._mape = mape
        self._namizja = namizja
        self._vnosi: Dict[str, dict] = {}

    # ------------------------------------------------------------------ seznam
    def mape(self) -> List[str]:
        """Mape z zaganjalniki (.desktop), iz katerih je seznam - iste spremlja [NadzorProgramov]."""
        return list(self._mape if self._mape is not None else link_programi._mape_vnosov())

    def kandidati(self) -> List[str]:
        """Mape, v katerih so lahko zaganjalniki - tudi tiste, ki jih se ni (prvi program Flatpak jo sele ustvari)."""
        return list(self._mape if self._mape is not None else link_programi._kandidati_map())

    def preberi(self) -> Dict[str, dict]:
        najdeni: Dict[str, dict] = {}
        videna = set()
        for mapa in self.mape():
            try:
                imena = sorted(os.listdir(mapa))
            except OSError:
                continue
            for ime in imena:
                if not ime.endswith(".desktop") or ime in najdeni or ime in IZPUSTI:
                    continue
                podatki = preberi_vnos(os.path.join(mapa, ime), self._namizja)
                if podatki is None:
                    continue
                # Isti program dvakrat (sistemsko in Flatpak) je v meniju samo zmeda: prvi obvelja.
                kljuc = (podatki["ime"].lower(), podatki["ikona"])
                if kljuc in videna:
                    continue
                videna.add(kljuc)
                najdeni[ime] = podatki
                if len(najdeni) >= NAJVEC:
                    break
        self._vnosi = najdeni
        return najdeni

    def seznam(self, ikone=None) -> List[dict]:
        """Seznam za stran: id, ime, opis, skupina, ikona (file:// ali ''), uporaba, pripet."""
        vnosi = self.preberi()
        uporaba = self.shramba.get("uporaba", {}) or {}
        pripeti = list(self.shramba.get("pripeti", []) or [])
        skriti = set(self.shramba.get("skriti_domov", []) or [])
        izhod = []
        # Isti program v dveh oblikah (npr. paket in Flatpak): obe kartici imata isto ime - oblika pove, katera je katera
        # (lastnik, 11. 10. 2026: »zakaj imam 2 Safeer Browserja«).
        imena: dict = {}
        for v in vnosi.values():
            imena[v["ime"].casefold()] = imena.get(v["ime"].casefold(), 0) + 1
        for oznaka, v in sorted(vnosi.items(), key=lambda p: p[1]["ime"].lower()):
            if imena.get(v["ime"].casefold(), 0) > 1:
                oblika = oblika_namestitve(str(v.get("pot") or ""))
                if oblika:
                    v = dict(v, ime="%s (%s)" % (v["ime"], oblika))
            u = uporaba.get(oznaka) or {}
            # Igre v oblaku (core/os_oblak_igre.py): program tece na ponudnikovih streznikih - to mora biti vidno.
            oblak = (os_oblak_igre.oblak_za(oznaka) or {}).get("ponudnik", "")
            izhod.append({
                "id": oznaka, "ime": v["ime"], "opis": v["opis"], "splosno": v["splosno"],
                "skupina": "igre" if oblak else v["skupina"], "kljucne": v["kljucne"], "oblak": oblak,
                "medij": bool(v.get("medij")), "zvok": bool(v.get("zvok")), "nastavitev": bool(v.get("nastavitev")),
                "ikona": ikone(v["ikona"]) if ikone else "",
                "uporaba": int(u.get("n", 0) or 0), "zadnjic": float(u.get("t", 0) or 0),
                "pripet": oznaka in pripeti,
                "skrit": oznaka in skriti,
            })
        return izhod

    def pot(self, oznaka: str) -> Optional[str]:
        ime = str(oznaka or "")
        if "/" in ime or not ime.endswith(".desktop"):
            return None
        if ime not in self._vnosi:
            self.preberi()
        v = self._vnosi.get(ime)
        return v["pot"] if v else None

    # ------------------------------------------------------------------ zagon
    def zabelezi(self, oznaka: str) -> None:
        uporaba = dict(self.shramba.get("uporaba", {}) or {})
        u = dict(uporaba.get(oznaka) or {})
        u["n"] = int(u.get("n", 0) or 0) + 1
        u["t"] = time.time()
        uporaba[oznaka] = u
        # Ne raste v nedogled: obdrzimo 200 zadnjih.
        if len(uporaba) > 200:
            uporaba = dict(sorted(uporaba.items(), key=lambda p: -float(p[1].get("t", 0)))[:200])
        self.shramba.set("uporaba", uporaba)

    def zazeni(self, oznaka: str, zaganjalnik=None) -> bool:
        """Zazene program s seznama tako, kot ga zazene meni. Nic drugega."""
        pot = self.pot(oznaka)
        if pot is None:
            return False
        ok = False
        if zaganjalnik is not None:
            try:
                ok = bool(zaganjalnik(pot))
            except Exception:
                ok = False
        if not ok and gostitelj.v_flatpaku():
            ok = gostitelj.zazeni_vnos(pot)
        if not ok:
            from core import varuh_procesov
            for ukaz in (["gio", "launch", pot], ["gtk-launch", oznaka]):
                if shutil.which(ukaz[0]) is None:
                    continue
                try:
                    pid = varuh_procesov.zazeni_program(ukaz, zasebni_webkit.okolje_za_zunanje())
                    if pid:
                        ok = True
                        break
                except Exception:
                    pass
                try:
                    # Brez nasih zasebnih poti (WebKit, AppImage): program dobi sistemske knjiznice in typelibe.
                    subprocess.Popen(ukaz, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True, env=zasebni_webkit.okolje_za_zunanje())
                    ok = True
                    break
                except Exception:
                    continue
        if ok:
            self.zabelezi(oznaka)
        return ok

    def pripni(self, oznaka: str, pripet: bool) -> List[str]:
        pripeti = [p for p in (self.shramba.get("pripeti", []) or []) if p != oznaka]
        if pripet and self.pot(oznaka):
            pripeti.append(oznaka)
            self.skrij_domov(oznaka, False)      # pripet program je na domacem zaslonu vedno
        self.shramba.set("pripeti", pripeti[:24])
        return pripeti

    def skrij_domov(self, oznaka: str, skrij: bool = True) -> List[str]:
        """»Odstrani z zacetnega zaslona«: program ostane v Programih, na domacem ga ni vec (tudi ce je
        pogosto rabljen ali privzet). Ponovno ga pripelje pripenjanje."""
        skriti = [p for p in (self.shramba.get("skriti_domov", []) or []) if p != oznaka]
        if skrij and self.pot(oznaka):
            skriti.append(oznaka)
        self.shramba.set("skriti_domov", skriti[:200])
        return skriti


# ---------------------------------------------------------------------- ikone
class NadzorProgramov:
    """Pove, ko se na racunalniku namesti ali odstrani program: v mapi z zaganjalniki se pojavi ali izgine vnos
    .desktop. Stran, ki kaze seznam programov, ga takrat prebere znova (4. 10. 2026: program, namescen ob odprti
    delovni povrsini, se v plosci Programi ni pokazal do ponovnega zagona).

    Namestitev paketa sprozi vec sprememb zapored (zacasne datoteke upravljalnika paketov), zato pride eno obvestilo,
    [zamik_ms] po zadnji spremembi. Tece v glavni zanki GLib (ustvari se v njeni niti).

    Mapa z zaganjalniki, ki je ob zagonu se ni (prvi program Flatpak na svezem racunalniku, prvi zaganjalnik v
    ~/.local/share/applications), ne sme ostati spregledana: namesto nje spremljamo najblizjo obstojeco nadrejeno
    mapo in, ko manjkajoca nastane, zacnemo spremljati njo. [mape] je zato seznam kandidatov ali funkcija, ki ga vrne."""

    #: Po nastanku cakane mape pocakamo trenutek (namestitev ustvari vec map zapored), nato nadzor preuredimo.
    ZAMIK_MAP_MS = 300

    def __init__(self, mape, ob_spremembi, zamik_ms: int = 1500) -> None:
        self._mape = mape if callable(mape) else (lambda seznam=list(mape): seznam)
        self._ob_spremembi = ob_spremembi
        self._zamik_ms = zamik_ms
        self._nadzori: list = []
        self._spremljane: List[str] = []          # mape z zaganjalniki, ki jih spremljamo
        self._cakane: Dict[str, set] = {}         # obstojeca nadrejena mapa -> imena podmap, na katere cakamo
        self._casovnik = 0
        self._casovnik_map = 0

    @staticmethod
    def razporedi(mape: List[str], obstaja=os.path.isdir) -> Tuple[List[str], Dict[str, set]]:
        """Kaj spremljati: (mape z zaganjalniki, ki obstajajo; obstojeca nadrejena mapa -> imena podmap, ki jih se
        ni in vodijo do mape z zaganjalniki). Brez GLib - za preizkus."""
        spremljane: List[str] = []
        cakane: Dict[str, set] = {}
        for mapa in mape:
            mapa = os.path.abspath(mapa)
            if obstaja(mapa):
                if mapa not in spremljane:
                    spremljane.append(mapa)
                continue
            otrok, nadrejena = mapa, os.path.dirname(mapa)
            while nadrejena != otrok and not obstaja(nadrejena):
                otrok, nadrejena = nadrejena, os.path.dirname(nadrejena)
            if nadrejena != otrok:
                cakane.setdefault(nadrejena, set()).add(os.path.basename(otrok))
        return spremljane, cakane

    def zacni(self) -> int:
        """Zacne spremljati; vrne stevilo map z zaganjalniki, ki jih spremlja (0 = brez GLib ali se nobene mape)."""
        if self._nadzori:
            return len(self._spremljane)
        try:
            from gi.repository import Gio
        except Exception:  # noqa: BLE001
            return 0
        # Mapa lahko nastane med razporejanjem in nastavitvijo nadzora: po nastavitvi pogledamo se enkrat.
        for _ in range(4):
            spremljane, cakane = self.razporedi(self._mape())
            self._ustavi_nadzore()
            for mapa, obdelava in ([(m, self._sprememba) for m in spremljane]
                                   + [(m, self._sprememba_nadrejene) for m in cakane]):
                try:
                    nadzor = Gio.File.new_for_path(mapa).monitor_directory(Gio.FileMonitorFlags.NONE, None)
                    nadzor.connect("changed", obdelava)
                    self._nadzori.append(nadzor)
                except Exception:  # noqa: BLE001
                    continue
            self._spremljane, self._cakane = spremljane, cakane
            if self.razporedi(self._mape()) == (spremljane, cakane):
                break
        return len(self._spremljane)

    @staticmethod
    def zadeva(ime: str) -> bool:
        """Ali sprememba datoteke s tem imenom lahko spremeni seznam programov (vnos .desktop, tudi zacasni)."""
        return ".desktop" in (ime or "")

    def _nacrtuj(self) -> None:
        from gi.repository import GLib
        if self._casovnik:
            GLib.source_remove(self._casovnik)
        self._casovnik = GLib.timeout_add(self._zamik_ms, self._poslji)

    def _sprememba(self, _nadzor, datoteka, _druga, _vrsta) -> None:
        try:
            ime = datoteka.get_basename() or ""
        except Exception:  # noqa: BLE001
            ime = ""
        if self.zadeva(ime):
            self._nacrtuj()

    def _sprememba_nadrejene(self, _nadzor, datoteka, _druga, _vrsta) -> None:
        """V nadrejeni mapi se je nekaj spremenilo: zanima nas samo nastanek podmape, na katero cakamo (v
        ~/.local/share se datoteke spreminjajo ves cas)."""
        try:
            ime = datoteka.get_basename() or ""
            mapa = datoteka.get_parent().get_path() or ""
        except Exception:  # noqa: BLE001
            return
        if ime not in self._cakane.get(mapa, ()):
            return
        from gi.repository import GLib
        if self._casovnik_map:
            GLib.source_remove(self._casovnik_map)
        self._casovnik_map = GLib.timeout_add(self.ZAMIK_MAP_MS, self._preuredi)

    def _preuredi(self) -> bool:
        """Cakana mapa je nastala: nadzor postavimo znova (zdaj spremljamo njo ali naslednjo na poti)."""
        self._casovnik_map = 0
        prej = set(self._spremljane)
        self._ustavi_nadzore()
        try:
            self.zacni()
        except Exception:  # noqa: BLE001
            return False
        if set(self._spremljane) - prej:
            # Nova mapa z zaganjalniki: program, zaradi katerega je nastala, je lahko ze v njej.
            self._nacrtuj()
        return False

    def _poslji(self) -> bool:
        self._casovnik = 0
        # Nov program prinese tudi svojo ikono: tema ikon GTK jo vidi sele, ko mape prebere znova (core/gostitelj).
        try:
            from core import gostitelj
            gostitelj.osvezi_temo_ikon()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._ob_spremembi()
        except Exception:  # noqa: BLE001
            pass
        return False

    def _ustavi_nadzore(self) -> None:
        for nadzor in self._nadzori:
            try:
                nadzor.cancel()
            except Exception:  # noqa: BLE001
                pass
        self._nadzori = []

    def koncaj(self) -> None:
        self._ustavi_nadzore()
        self._spremljane, self._cakane = [], {}
        for ime in ("_casovnik", "_casovnik_map"):
            if getattr(self, ime):
                try:
                    from gi.repository import GLib
                    GLib.source_remove(getattr(self, ime))
                except Exception:  # noqa: BLE001
                    pass
                setattr(self, ime, 0)


def pot_ikone(ime: str, velikost: int = IKONA_VELIKOST) -> str:
    """Ikona programa kot PNG v predpomnilniku; vrne pot ali ''. Klicati na glavni niti (tema ikon GTK)."""
    if not ime:
        return ""
    cilj = os.path.join(MAPA_IKON, hashlib.sha1(("%s|%d" % (ime, velikost)).encode(), usedforsecurity=False).hexdigest() + ".png")
    if os.path.isfile(cilj) and os.path.getsize(cilj) > 0:
        return cilj
    izvor = ""
    if os.path.isabs(ime) and os.path.isfile(ime):
        izvor = ime
    try:
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        if not izvor:
            # Tema ikon prek core/gostitelj.py: GTK4 (Safeer OS) ali GTK3, kar proces ze uporablja.
            from core import gostitelj
            ime_teme = ime[:-4] if ime.endswith((".png", ".svg", ".xpm")) else ime
            izvor = gostitelj.ikona_iz_teme(ime_teme, velikost)
            if not izvor:
                return ""
        slika = GdkPixbuf.Pixbuf.new_from_file_at_size(izvor, velikost, velikost)
        if slika is None:
            return ""
        os.makedirs(MAPA_IKON, exist_ok=True)
        slika.savev(cilj, "png", [], [])
        return cilj
    except Exception:
        return ""
