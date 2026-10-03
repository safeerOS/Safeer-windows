"""Racunalnik kot izvor za »Nadaljuj z druge naprave« (ukaza `play.state` in `play.stop` po Safeer Linku).

Isto kot os/Predaja.kt na Androidu (pravila 28. 9. 2026): nic samodejnega. Racunalnik le POVE, kaj predvaja in pri
kateri sekundi (ali kateri film je nazadnje gledal in kje je ostal); druga naprava si to na izrecno zahtevo
uporabnika potegne in nadaljuje. Izvor predvajanja ne ustavi sam - le, ce uporabnik na cilju izbere »nadaljuj
tukaj in ustavi tam« (`play.stop`), in tudi takrat je to samo premor.

Kaj gre ven in komu: samo napravi v krogu zaupanja (ukazi Linka) in le, ce uporabnik deljenja ni izklopil.
Datoteka tega racunalnika gre le, ce je v mapi, ki jo racunalnik deli (isti streznik, zeton in odtis kot pri
Datotekah - naprava brez dostopa do map ne dobi nicesar); spletni tok s svojim naslovom; datoteka tretje naprave
z njenim id-jem (cilj si zeton pri njej dobi sam). Kar ostane tu: lokalni posredniski tokovi (127.0.0.1), DVD
in datoteke zunaj deljenih map (`playing: false, reason: ni_deljeno`).

Skupen modul z Windows (windows/safeer_windows/control_backend.py): stanje predvajalnika pride kot slovar
{stanje, uri, naslov, vrsta, pozicija, trajanje, naprava, oznaka}, tu se iz njega sestavi odgovor za napravo.
"""

from __future__ import annotations

import mimetypes
import os
import time
import urllib.parse
from typing import Callable, Optional

#: Ukaza, ki ju naprava (telefon, televizor) poslje, ko uporabnik tam izbere »Nadaljuj z druge naprave«, in ponudba
#: »Poslji na napravo« (play.offer: izvor ponudi, kar igra; tu le tiho obvestilo Sprejmi/Zavrni - nic se ne zacne samo).
DEJANJA = ["play.state", "play.stop", "play.offer"]
#: Ponudba velja 10 minut; nova zamenja staro.
PONUDBA_VELJA_S = 600.0

#: D-Bus Safeer OS na Linuxu (safeer_os.py: VMESNIK_PREDVAJANJE).
APP_ID = "io.github.memelandfaner.SafeerOS"
POT = "/io/github/memelandfaner/SafeerOS/predvajanje"
VMESNIK = APP_ID + ".Predvajanje"

VIDEO = (".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi", ".ogv", ".ts", ".mpg", ".mpeg", ".wmv", ".flv", ".3gp", ".m2ts")
#: Vrste vnosov predvajalnikov (Linux os_predvajalnik, Windows Medijski center), ki so gotovo slika oz. gotovo zvok;
#: "medij" (Linux: splosno) in neznane gredo po koncnici ali mime.
VIDEO_VRSTE = ("video", "tv", "film", "serija", "filmi", "serije", "dvd")
ZVOK_VRSTE = ("glasba", "radio", "podcast", "podkast", "zvok", "audio")


def vnos(id_: str, naslov: str, zvok: str, video: bool, mime: str = "", radio: bool = False, kanal: str = "",
         povezava: Optional[str] = None) -> dict:
    """Skladba, kot jo bere Android (os/Predaja.kt izJson): ista polja kot Jamendo.Skladba, brez podnapisov.

    `povezava` je, kar predvajalnik pokaze kot vir: pri spletnem toku njegov naslov, pri datoteki z naprave nic
    (naslov streznika z zetonom uporabniku ne pove nicesar - kot pri Datotekah)."""
    return {"id": id_, "naslov": naslov, "izvajalec": "", "slika": "", "zvok": zvok,
            "povezava": zvok if povezava is None else povezava,
            "radio": radio, "video": video, "mime": mime, "streznik": "", "kanal": kanal, "mediaType": "",
            "genres": [], "year": 0, "season": 0, "episode": 0, "imdbId": "", "tmdbId": "", "quality": 0,
            "rating": 0.0, "language": ""}


def pot_iz_uri(uri: str) -> str:
    """`file://` ali gola pot -> pot na disku; prazno za vse drugo (http, dvd, 127.0.0.1 ...)."""
    uri = str(uri or "")
    if uri.startswith("file://"):
        u = urllib.parse.urlparse(uri)
        return urllib.parse.unquote(u.path) if not u.netloc or u.netloc == "localhost" else ""
    if uri.startswith("/") or (len(uri) > 2 and uri[1] == ":" and uri[2] in "\\/"):
        return uri
    return ""


def je_video(pot: str, vrsta: str = "", mime: str = "") -> bool:
    if vrsta in VIDEO_VRSTE:
        return True
    if vrsta in ZVOK_VRSTE:
        return False
    return mime.startswith("video/") or str(pot or "").lower().endswith(VIDEO)


def streznik_za(datoteke, posiljatelj: str, hub_url: str) -> dict:
    """Naslov, odtis in zeton streznika datotek za napravo (kot pri `files.list`; streznik se po potrebi zazene)."""
    from core import link_datoteke
    datoteke.streznik.zazeni()
    naslov = link_datoteke.naslov_do_huba(hub_url) if hub_url else link_datoteke.krajevni_naslov()
    return {"base_url": datoteke.streznik.osnova(naslov).rstrip("/"), "fp": datoteke.streznik.odtis,
            "token": datoteke.streznik.zeton_za(posiljatelj or "naprava")}


def vnos_datoteke(datoteke, pot: str, naslov: str, posiljatelj: str, hub_url: str, vrsta: str = "") -> Optional[dict]:
    """Datoteka tega racunalnika za drugo napravo: le, ce je v deljeni mapi (ali je ves disk za naprave vklopljen).

    Vrne {"item": ..., "server": {...}} ali None."""
    if datoteke is None or not pot or not os.path.isfile(pot):
        return None
    oznaka = datoteke.mape.oznaka_poti(pot)
    if not oznaka or datoteke.mape.razresi(oznaka) is None:
        return None
    s = streznik_za(datoteke, posiljatelj, hub_url)
    url = s["base_url"] + "/d/" + urllib.parse.quote(oznaka, safe="")
    mime = mimetypes.guess_type(pot)[0] or ""
    ime = naslov or os.path.splitext(os.path.basename(pot))[0]
    return {"item": vnos(oznaka, ime, url, je_video(pot, vrsta, mime), mime, povezava=""), "server": s}


def vnos_iz_stanja(st: dict, datoteke, posiljatelj: str, hub_url: str) -> Optional[dict]:
    """Iz stanja predvajalnika {uri, naslov, vrsta, naprava, oznaka} naredi, kar naprava lahko predvaja:
    {"item", "server"?, "server_device"?} ali None, ce to ostane na tem racunalniku."""
    uri = str(st.get("uri") or "")
    naslov = str(st.get("naslov") or "")
    vrsta = str(st.get("vrsta") or "")
    naprava, oznaka, izvirnik = str(st.get("naprava") or ""), str(st.get("oznaka") or ""), str(st.get("izvirnik") or "")
    if naprava and oznaka and izvirnik.startswith("https://"):
        # Datoteka tretje naprave (telefon, drug racunalnik): cilj dobi svoj zeton pri njej (files.list) in
        # predvaja isti naslov /d/<oznaka> - tu je le lokalni posrednik 127.0.0.1, ki drugje ne pomeni nic.
        mime = mimetypes.guess_type(oznaka)[0] or ""
        return {"item": vnos(oznaka, naslov, izvirnik, je_video(oznaka, vrsta, mime), mime, povezava=""),
                "server_device": naprava}
    pot = pot_iz_uri(uri)
    if pot:
        return vnos_datoteke(datoteke, pot, naslov, posiljatelj, hub_url, vrsta)
    if uri.startswith(("http://", "https://")):
        gostitelj = (urllib.parse.urlparse(uri).hostname or "").lower()
        if gostitelj in ("127.0.0.1", "localhost", "::1"):
            return None  # lokalni posrednik (tok z naprave, torrent, pretvorba) - naslov drugje ne pomeni nic
        v = vnos(uri, naslov or os.path.basename(urllib.parse.urlparse(uri).path) or uri, uri,
                 je_video(urllib.parse.urlparse(uri).path, vrsta), "", radio=vrsta == "radio",
                 kanal=naslov if vrsta == "tv" else "")
        return {"item": v}
    return None


class Predvajanje:
    """Odgovarja na `play.state` in `play.stop` za ta racunalnik.

    `stanje_predvajalnika()` vrne slovar {stanje: predvaja|premor|ustavljeno, uri, naslov, vrsta, pozicija (s),
    trajanje (s), naprava, oznaka, izvirnik} ali None (predvajalnika ni / Safeer OS ne tece); `premor()` ga ustavi in vrne
    True, ce je kaj ustavil; `zadnji()` vrne nazadnje gledani video s shranjenim mestom
    {pot, ime, pozicija, trajanje, zadnjic} ali None; `deli()` pove, ali je uporabnik deljenje pustil vklopljeno.
    """

    def __init__(self, stanje_predvajalnika: Callable[[], Optional[dict]], premor: Callable[[], bool],
                 datoteke=None, zadnji: Optional[Callable[[], Optional[dict]]] = None,
                 deli: Optional[Callable[[], bool]] = None) -> None:
        self.stanje_predvajalnika = stanje_predvajalnika
        self.premor = premor
        self.datoteke = datoteke
        self.zadnji = zadnji
        self.deli = deli or (lambda: True)

    def stanje(self, posiljatelj: str, hub_url: str = "") -> dict:
        o: dict = {"shared": bool(self.deli())}
        if not o["shared"]:
            return o
        try:
            st = self.stanje_predvajalnika() or {}
        except Exception:  # noqa: BLE001 - brez predvajalnika je kot da nic ne igra
            st = {}
        if st.get("stanje") in ("predvaja", "premor") and (st.get("uri") or st.get("oznaka")):
            v = vnos_iz_stanja(st, self.datoteke, posiljatelj, hub_url)
            if v is None:
                return dict(o, playing=False, reason="ni_deljeno")
            o.update(playing=True, is_playing=st.get("stanje") == "predvaja",
                     position_ms=int(float(st.get("pozicija") or 0) * 1000),
                     duration_ms=int(float(st.get("trajanje") or 0) * 1000))
            o.update(v)
            return o
        # Nic ne igra: zadnji video s shranjenim mestom (racunalnik je film ugasnil pri 1:02 - telefon nadaljuje).
        z = None
        if self.zadnji is not None:
            try:
                z = self.zadnji()
            except Exception:  # noqa: BLE001
                z = None
        if not z:
            return dict(o, playing=False)
        v = vnos_datoteke(self.datoteke, str(z.get("pot") or ""), str(z.get("ime") or ""), posiljatelj, hub_url, "video")
        if v is None:
            return dict(o, playing=False)
        o.update(playing=False, last=True, position_ms=int(float(z.get("pozicija") or 0) * 1000),
                 duration_ms=int(float(z.get("trajanje") or 0) * 1000),
                 when=int(float(z.get("zadnjic") or 0) * 1000) or int(time.time() * 1000))
        o.update(v)
        return o

    def ustavi(self) -> dict:
        try:
            return {"stopped": bool(self.premor())}
        except Exception:  # noqa: BLE001
            return {"stopped": False}

    # ------------------------------------------------------------------ cilj potiskanja (play.offer)

    #: Zadnja ponudba druge naprave, ki tu caka na Sprejmi/Zavrni: {od, od_ime, item, position_ms, duration_ms,
    #: server, server_device, cas} ali None.
    cakajoca: Optional[dict] = None
    #: Klicatelj (Control) jo nastavi: pokaze tiho obvestilo s Sprejmi/Zavrni.
    ob_ponudbi: Optional[Callable[[dict], None]] = None

    def ponudba(self, posiljatelj: str, od_ime: str, parametri: dict) -> dict:
        """`play.offer`: ponudbo preveri in shrani, pokaze jo klicatelj; nic se ne predvaja, dokler uporabnik ne sprejme."""
        if not self.deli():
            return {"queued": False, "reason": "izklopljeno"}
        p = ponudba_iz(posiljatelj, od_ime, parametri)
        if p is None:
            return {"queued": False, "reason": "ni_vnosa"}
        self.cakajoca = p
        if self.ob_ponudbi is not None:
            try:
                self.ob_ponudbi(p)
            except Exception:  # noqa: BLE001 - obvestilo ni razlog, da ponudba odpade
                pass
        # "shown": kako jo uporabnik vidi (banner = pasica na zaslonu zdaj; Android pozna se notification in later =
        # obvestila so izklopljena, ponudba caka na odprtje Safeer OS). Racunalnik pasico pokaze vedno.
        return {"queued": True, "shown": "banner"}


    def vzemi_ponudbo(self) -> Optional[dict]:
        p, self.cakajoca = self.cakajoca, None
        return p if p and time.time() - float(p.get("cas") or 0) < PONUDBA_VELJA_S else None

    def zavrni_ponudbo(self) -> None:
        self.cakajoca = None


def izid_ponudbe(odgovor: dict) -> dict:
    """Izid `play.offer` za posiljatelja: ok (tam je pasica ali obvestilo) s `prikaz` ("later" = tam obvestil ni, naj
    odpre Safeer OS), sicer koda: ni_vnosa / izklopljeno (cilj), stara (cilj dejanja ne pozna) ali napaka."""
    r = odgovor if isinstance(odgovor, dict) else {}
    d = r.get("data") if isinstance(r.get("data"), dict) else {}
    if r.get("ok") and d.get("queued"):
        return {"ok": True, "prikaz": str(d.get("shown") or "")}
    if r.get("ok"):
        return {"ok": False, "koda": str(d.get("reason") or "napaka")}
    koda = str(r.get("code") or r.get("koda") or "")
    return {"ok": False, "koda": "stara" if koda == "neznano_dejanje" else (koda or "napaka")}


def ponudba_iz(posiljatelj: str, od_ime: str, parametri: dict) -> Optional[dict]:
    """Ponudba `play.offer` iz parametrov ukaza: vnos (polja Skladbe), sekunda, streznik izvora (naslov, odtis, zeton
    za ta racunalnik) ali id tretje naprave. Brez predvajljivega vnosa vrne None."""
    if not isinstance(parametri, dict):
        return None
    item = parametri.get("item")
    if not isinstance(item, dict):
        return None
    zvok = str(item.get("zvok") or "")
    server = parametri.get("server") if isinstance(parametri.get("server"), dict) else None
    server_device = str(parametri.get("server_device") or "")
    if server is not None and not (str(server.get("base_url") or "").startswith("https://") and server.get("fp") and server.get("token")):
        server = None
    if not zvok.startswith(("http://", "https://")) and not server_device:
        return None
    if not zvok and not server_device:
        return None
    # Datoteka naprave (oznaka strezniku datotek) brez streznika ali id-ja naprave: naslov z zetonom izvora tu ne velja.
    if str(item.get("id") or "").startswith(("share:", "disk:", "media:")) and server is None and not server_device:
        return None
    try:
        position_ms = max(0, int(parametri.get("position_ms") or 0))
        duration_ms = max(0, int(parametri.get("duration_ms") or 0))
    except (TypeError, ValueError):
        position_ms, duration_ms = 0, 0
    return {"od": str(posiljatelj or ""), "od_ime": str(od_ime or posiljatelj or ""), "item": item,
            "position_ms": position_ms, "duration_ms": duration_ms, "server": server, "server_device": server_device,
            "cas": time.time()}


def mapa_datoteke(oznaka: str) -> str:
    """Mapa, v kateri je datoteka z oznako na njenem strezniku (`files.list` da naslov in zeton le za mapo z datotekami):
    racunalnik `disk:/pot` ali `share:<i>:<pot>`, Android `media:<zbirka>:<id>` -> zbirka (isto kot Predaja.mapaDatoteke)."""
    oznaka = str(oznaka or "")
    if oznaka.startswith("disk:"):
        pot = oznaka[len("disk:"):]
        return "disk:" + (pot.rsplit("/", 1)[0] or "/")
    if oznaka.startswith("share:"):
        d = oznaka.split(":", 2)
        return "share:%s:%s" % (d[1], d[2].rsplit("/", 1)[0] if "/" in d[2] else "") if len(d) == 3 else "root"
    if oznaka.startswith("media:"):
        d = oznaka.split(":")
        return d[1] if len(d) > 1 and d[1] else "root"
    return "root"


def opis_ponudbe(p: dict) -> str:
    """»Tablica ti posilja: Film (pri 12:34)« - naslov in sekunda za obvestilo."""
    item = p.get("item") or {}
    s = int(p.get("position_ms") or 0) // 1000
    cas = "%d:%02d:%02d" % (s // 3600, (s % 3600) // 60, s % 60) if s >= 3600 else "%d:%02d" % (s // 60, s % 60)
    return "%s (%s)" % (str(item.get("naslov") or item.get("id") or ""), cas)


# ---------------------------------------------------------------------- Linux: Safeer OS prek D-Bus

def _vodilo():
    from gi.repository import Gio
    return Gio.bus_get_sync(Gio.BusType.SESSION, None)


def safeer_os_tece(vodilo=None) -> bool:
    try:
        from gi.repository import Gio, GLib
        vodilo = vodilo or _vodilo()
        return bool(vodilo.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                     "NameHasOwner", GLib.Variant("(s)", (APP_ID,)), GLib.VariantType("(b)"),
                                     Gio.DBusCallFlags.NONE, 1500, None).unpack()[0])
    except Exception:  # noqa: BLE001
        return False


def _klic_safeer_os(metoda: str, *argumenti: str, cas_ms: int = 3000) -> Optional[dict]:
    """Metoda vmesnika Predvajanje v tekocem Safeer OS; None, ce ne tece ali ne odgovori."""
    import json
    try:
        from gi.repository import Gio, GLib
        vodilo = _vodilo()
        if not safeer_os_tece(vodilo):
            return None
        parametri = GLib.Variant("(" + "s" * len(argumenti) + ")", tuple(str(a) for a in argumenti)) if argumenti else None
        r = vodilo.call_sync(APP_ID, POT, VMESNIK, metoda, parametri, GLib.VariantType("(s)"),
                             Gio.DBusCallFlags.NONE, cas_ms, None)
        izid = json.loads(r.unpack()[0])
        return izid if isinstance(izid, dict) and izid.get("ok") else None
    except Exception:  # noqa: BLE001
        return None


def stanje_safeer_os() -> Optional[dict]:
    return _klic_safeer_os("Stanje")


def premor_safeer_os() -> bool:
    izid = _klic_safeer_os("Premor")
    return bool(izid and izid.get("stopped"))


def odstrani_prenos_safeer_os(hash_: str) -> bool:
    """Prenos zaradi gledanja odstrani tekoci Safeer OS (motor torrentov je njegov): polica »Na tvojih napravah«."""
    izid = _klic_safeer_os("OdstraniPrenos", str(hash_ or ""), cas_ms=30000)
    return bool(izid and izid.get("ok"))


def zadnji_video() -> Optional[dict]:
    """Nazadnje gledani video iz knjiznice Safeer OS (ista baza, tudi ko Safeer OS ne tece)."""
    try:
        from pathlib import Path
        from core import os_knjiznica
        xdg = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
        pot = xdg / "safeer-os" / "mediji.sqlite3"
        if not pot.is_file():
            return None
        return os_knjiznica.Knjiznica(pot).zadnji_nedokoncan()
    except Exception:  # noqa: BLE001
        return None


def za_control(datoteke, deli: Optional[Callable[[], bool]] = None) -> Predvajanje:
    """Predvajanje za Safeer Control na Linuxu: stanje in premor iz Safeer OS prek D-Bus, zadnji video iz knjiznice."""
    return Predvajanje(stanje_safeer_os, premor_safeer_os, datoteke, zadnji_video, deli)


__all__ = ["DEJANJA", "Predvajanje", "vnos", "vnos_iz_stanja", "vnos_datoteke", "pot_iz_uri", "je_video", "za_control"]
