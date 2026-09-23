"""Predvajalniki na locenem zaslonu: daljinec jih upravlja kot predvajalnik, ne kot namizje.

Televizor za predvajalnik (VLC, Celluloid, Rhythmbox, Totem, Kodi ...) ne posilja tipk, ampak
pomen: "predvajaj/pavza", "10 s naprej". Racunalnik ga izvede prek MPRIS
(org.mpris.MediaPlayer2 na sejnem vodilu D-Bus), ki ga ima skoraj vsak predvajalnik na Linuxu -
tako ukaz deluje ne glede na to, katere tipke program pricakuje. Kjer MPRIS ni, pade na tipke.

Istim vmesnikom preberemo stanje (naslov, cas, predvaja/pavza), da ga televizor pokaze v svojem
pasu za predvajanje: program da vsebino, Safeer pa upravljanje, prilagojeno daljincu.

Upravljamo samo predvajalnik, ki tece na locenem zaslonu (v okolju ima WAYLAND_DISPLAY swaya ali je
potomec swaya), nikoli glasbe, ki jo uporabnik za racunalnikom predvaja na svojem namizju.
"""

from __future__ import annotations

import os
from typing import Callable, Dict, Iterable, List, Optional

#: Profil programa, ki ga racunalnik javi televizorju v `screen.start`.
PROFIL_PREDVAJALNIK = "predvajalnik"
#: Program za televizor (Kodi, Plex HTPC): narejen za daljinec, zato dobi tipke, ne kazalca in ne
#: pasu predvajalnika - ima svoj meni, po katerem se premikas s puscicami.
PROFIL_TV = "tv"
#: Imena vnosov/programov za televizor (v imenu datoteke .desktop ali ukazu, male crke).
PROGRAMI_ZA_TV = ("kodi", "plexhtpc", "plex-htpc")
#: Koliko casa ima predvajalnik po zagonu, da se oglasi na MPRIS; sicer televizor ne ostane v
#: nacinu predvajalnika (Hypnotix, mpv brez MPRIS: OK bi bil presledek, seznam kanalov neuporaben).
CAKAJ_MPRIS_S = 8.0

#: Kategorije XDG, po katerih program ni predvajalnik, ceprav je "AudioVideo" (urejevalniki, snemalniki).
NI_PREDVAJALNIK = {"AudioVideoEditing", "Recorder", "Mixer", "Sequencer", "Midi", "Graphics",
                   "Game", "Development", "Music Education", "Settings", "Office"}

#: Ukazi, ki jih televizor sme poslati (dogodek {"vrsta": "medij", "ukaz": ...}).
UKAZI = {"predvajaj_pavza", "predvajaj", "pavza", "naprej", "nazaj", "premik", "ustavi"}
#: Najvec, kolikor se sme en premik premakniti (sekunde).
NAJVEC_PREMIK_S = 600

#: Ce MPRIS ni: tipke, ki jih pozna vecina predvajalnikov (oznake iz link_vnos.TIPKE).
TIPKE_NAMESTO = {"predvajaj_pavza": "presledek", "predvajaj": "presledek", "pavza": "presledek",
                 "naprej": "naprej", "nazaj": "prejsnja", "ustavi": "ustavi"}

_MPRIS = "org.mpris.MediaPlayer2."
_POT = "/org/mpris/MediaPlayer2"
_PREDVAJALNIK = "org.mpris.MediaPlayer2.Player"


def je_predvajalnik(kategorije: Iterable[str]) -> bool:
    """Ali je program po kategorijah XDG predvajalnik.

    "Player" odloci (VLC ima tudi "Recorder", pa je predvajalnik); sicer mora biti AudioVideo z
    videom ali TV in ne urejevalnik ali snemalnik."""
    k = {str(x) for x in (kategorije or ()) if x}
    if "Player" in k:
        return True
    # Nastavitve kamere (Cameractrls) so "AudioVideo;Video", pa niso predvajalnik.
    return "AudioVideo" in k and bool(k & {"Video", "TV"}) and not (k & NI_PREDVAJALNIK)


def profil_programa(kategorije: Iterable[str], ime_vnosa: str = "", ukaz: str = "") -> str:
    """Kako naj televizor upravlja program: "tv", "predvajalnik" ali "" (kazalec/tipke po izbiri)."""
    oznaka = (os.path.basename(str(ime_vnosa or "")) + " " + os.path.basename(str(ukaz or "").split(" ")[0])).lower()
    if any(p in oznaka for p in PROGRAMI_ZA_TV):
        return PROFIL_TV
    return PROFIL_PREDVAJALNIK if je_predvajalnik(kategorije) else ""


def je_potomec(pid: int, prednik: int, starsi: Callable[[int], int]) -> bool:
    """Ali je proces `pid` potomec procesa `prednik` (ali on sam)."""
    videni = set()
    while pid > 1 and pid not in videni:
        if pid == prednik:
            return True
        videni.add(pid)
        pid = starsi(pid)
    return pid == prednik


def stars(pid: int) -> int:
    """Starsevski proces iz /proc (0, ce ga ni vec)."""
    try:
        with open("/proc/%d/stat" % pid, encoding="utf-8", errors="replace") as f:
            vsebina = f.read()
        # Ime programa je v oklepajih in sme vsebovati presledke: beremo za zadnjim ")".
        return int(vsebina.rsplit(")", 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        return 0


def okolje(pid: int) -> Dict[str, str]:
    """Okolje procesa iz /proc (prazno, ce ga ne moremo prebrati)."""
    try:
        with open("/proc/%d/environ" % pid, "rb") as f:
            vsebina = f.read()
    except OSError:
        return {}
    o: Dict[str, str] = {}
    for kv in vsebina.split(b"\0"):
        if b"=" in kv:
            k, v = kv.decode("utf-8", "replace").split("=", 1)
            o[k] = v
    return o


def stanje_iz_lastnosti(lastnosti: Dict) -> dict:
    """Stanje za pas na televizorju iz lastnosti MPRIS (slovar, kot ga vrne GetAll)."""
    meta = lastnosti.get("Metadata") or {}
    izvajalec = meta.get("xesam:artist") or []
    if isinstance(izvajalec, (list, tuple)):
        izvajalec = ", ".join(str(x) for x in izvajalec if x)
    dolzina = meta.get("mpris:length") or 0
    polozaj = lastnosti.get("Position") or 0
    naslov = str(meta.get("xesam:title") or "")
    if not naslov:
        # Brez oznak (npr. datoteka brez metapodatkov) je ime datoteke boljse kot nic.
        url = str(meta.get("xesam:url") or "")
        naslov = os.path.basename(url.split("?", 1)[0]).replace("%20", " ") if url else ""
    try:
        dolzina_s = max(0, int(dolzina) // 1_000_000)
        polozaj_s = max(0, int(polozaj) // 1_000_000)
    except (TypeError, ValueError):
        dolzina_s, polozaj_s = 0, 0
    return {"naslov": naslov[:200], "izvajalec": str(izvajalec or "")[:200],
            "dolzina": dolzina_s, "polozaj": min(polozaj_s, dolzina_s) if dolzina_s else polozaj_s,
            "predvaja": str(lastnosti.get("PlaybackStatus") or "") == "Playing",
            "premik": bool(lastnosti.get("CanSeek", True))}


class Mpris:
    """Predvajalnik na locenem zaslonu prek D-Bus.

    `koren` vrne pid swaya (0 = ni locenega zaslona), `wayland` ime njegove vticnice Wayland. Sway
    programe zazene z dvojnim razcepom (niso njegovi potomci), zato proces prepoznamo predvsem po
    WAYLAND_DISPLAY v njegovem okolju - to ima samo program na locenem zaslonu."""

    def __init__(self, koren: Callable[[], int], wayland: Callable[[], str] = lambda: "") -> None:
        self._koren = koren
        self._wayland = wayland
        self._vodilo = None

    # ------------------------------------------------------------------ D-Bus
    def _bus(self):
        if self._vodilo is None:
            from gi.repository import Gio  # Gio je varen tudi zunaj glavne niti (ne GTK)
            self._vodilo = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        return self._vodilo

    def _klic(self, ime: str, pot: str, vmesnik: str, metoda: str, argumenti=None, odgovor: str = ""):
        from gi.repository import Gio, GLib
        tip = GLib.VariantType(odgovor) if odgovor else None
        izid = self._bus().call_sync(ime, pot, vmesnik, metoda, argumenti, tip,
                                     Gio.DBusCallFlags.NONE, 1500, None)
        return izid.unpack() if izid is not None else None

    def _imena(self) -> List[str]:
        izid = self._klic("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                          "ListNames", None, "(as)")
        return [i for i in (izid[0] if izid else []) if i.startswith(_MPRIS)]

    def _pid(self, ime: str) -> int:
        from gi.repository import GLib
        izid = self._klic("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                          "GetConnectionUnixProcessID", GLib.Variant("(s)", (ime,)), "(u)")
        return int(izid[0]) if izid else 0

    def predvajalnik(self) -> Optional[str]:
        """Ime MPRIS predvajalnika, ki tece na locenem zaslonu (ali None)."""
        koren = self._koren()
        if not koren:
            return None
        wayland = self._wayland()
        try:
            for ime in self._imena():
                pid = self._pid(ime)
                if (wayland and okolje(pid).get("WAYLAND_DISPLAY") == wayland) or je_potomec(pid, koren, stars):
                    return ime
        except Exception:
            return None
        return None

    # ------------------------------------------------------------------ za televizor
    def stanje(self) -> Optional[dict]:
        ime = self.predvajalnik()
        if ime is None:
            return None
        try:
            from gi.repository import GLib
            izid = self._klic(ime, _POT, "org.freedesktop.DBus.Properties", "GetAll",
                              GLib.Variant("(s)", (_PREDVAJALNIK,)), "(a{sv})")
            return stanje_iz_lastnosti(izid[0] if izid else {})
        except Exception:
            return None

    def ukaz(self, ukaz: str, sekund: float = 0) -> bool:
        """Izvede ukaz prek MPRIS; False, ce predvajalnika ali ukaza ni (klicatelj pade na tipke)."""
        if ukaz not in UKAZI:
            return False
        ime = self.predvajalnik()
        if ime is None:
            return False
        metoda = {"predvajaj_pavza": "PlayPause", "predvajaj": "Play", "pavza": "Pause",
                  "naprej": "Next", "nazaj": "Previous", "ustavi": "Stop", "premik": "Seek"}[ukaz]
        try:
            argumenti = None
            if ukaz == "premik":
                from gi.repository import GLib
                s = max(-NAJVEC_PREMIK_S, min(NAJVEC_PREMIK_S, float(sekund)))
                argumenti = GLib.Variant("(x)", (int(s * 1_000_000),))
            self._klic(ime, _POT, _PREDVAJALNIK, metoda, argumenti)
            return True
        except Exception:
            return False


def dogodek_v_tipko(dogodek: dict) -> Optional[dict]:
    """Ce MPRIS ni: dogodek za predvajalnik kot navaden pritisk tipke (ali None, ce ga ni)."""
    ukaz = str(dogodek.get("ukaz", "") or "")
    if ukaz == "premik":
        try:
            s = float(dogodek.get("s", 0))
        except (TypeError, ValueError):
            return None
        return {"vrsta": "tipka", "tipka": "desno" if s > 0 else "levo"} if s else None
    tipka = TIPKE_NAMESTO.get(ukaz)
    return {"vrsta": "tipka", "tipka": tipka} if tipka else None
