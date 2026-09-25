"""Daljinec Safeer Controla po Safeer Linku (sporocilo `control.command`) za linuxov brskalnik.

Seznanjena naprava (racunalnik s Safeer Controlom, telefon) sme brskalniku narocati samo
to, kar brskalnik sme narediti sam: tipke nazaj/domov/osvezi, drsenje, odpiranje strani,
predvajaj/pavza, glasnost racunalnika, ponovni zagon, ciscenje predpomnilnika, stanje in
posnetek odprtega zavihka. Enak nabor dejanj kot na televizorju in telefonu
(link/Daljinec.kt); kar na racunalniku ni smiselno (zagon aplikacij, D-pad), vrne
razumljivo napako.

Vse se izvaja na glavni niti GTK; klicatelj (core/safeer_link.py) poskrbi za GLib.idle_add.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import uuid
from typing import Callable, Dict, Optional

ZMOZNOST = "remote"

DEJANJA = ["key", "scroll", "open_url", "volume", "restart", "clear_cache", "status", "screenshot"]

TIPKE = ["back", "home", "reload", "forward", "up", "down", "page_up", "page_down",
         "play_pause", "play", "pause", "stop", "mute", "unmute"]


def izid(ok: bool, sporocilo: str, podatki: Optional[dict] = None, koda: str = "") -> dict:
    d = {"ok": ok, "message": sporocilo}
    if koda:
        d["code"] = koda
    if podatki is not None:
        d["data"] = podatki
    return d


def sporocilo_izida(cilj: str, ref_id: str, dejanje: str, izid_: dict) -> dict:
    """`control.result`, ki gre prek sredisca nazaj posiljatelju ukaza."""
    telo = dict(izid_)
    telo["action"] = dejanje
    return {
        "id": str(uuid.uuid4()),
        "type": "control.result",
        "target": cilj,
        "ref_id": ref_id,
        "payload": telo,
    }


def _razlicica() -> str:
    glavni = sys.modules.get("__main__")
    return str(getattr(glavni, "APP_VERSION", "") or "")


def _js_video(telo: str) -> str:
    return ("(function(){try{var m=document.querySelectorAll('video,audio');"
            "for(var i=0;i<m.length;i++){var v=m[i];" + telo + "}}catch(e){}})()")


def izvedi(app, dejanje: str, parametri: dict, odpri_naslov: Callable[[str], None],
           koncaj: Callable[[dict], None]) -> None:
    """Izvede ukaz in izid vrne prek `koncaj` (posnetek je asinhron, vse drugo takoj).

    `app` je glavno okno brskalnika (get_active_webview, load_homepage, new_tab).
    """
    d = (dejanje or "").strip().lower()
    parametri = parametri if isinstance(parametri, dict) else {}
    if d not in DEJANJA:
        koncaj(izid(False, f"Neznano dejanje: {d}" if d else "Manjka dejanje", koda="neznano_dejanje"))
        return
    try:
        if d == "key":
            koncaj(_tipka(app, str(parametri.get("key", "")).strip().lower()))
        elif d == "scroll":
            koncaj(_drsenje(app, str(parametri.get("direction", "down")).strip().lower()))
        elif d == "open_url":
            koncaj(_odpri(app, str(parametri.get("url", "")).strip(), odpri_naslov))
        elif d == "volume":
            koncaj(_glasnost(parametri))
        elif d == "restart":
            koncaj(_znova_zazeni(app))
        elif d == "clear_cache":
            koncaj(_pocisti(app))
        elif d == "status":
            koncaj(izid(True, "Stanje", stanje(app)))
        elif d == "screenshot":
            _posnetek(app, koncaj)
    except Exception as e:  # noqa: BLE001 - izid mora vedno priti nazaj
        koncaj(izid(False, f"Ukaz ni uspel: {e}"))


DEJANJA_CONTROL = ["open_url", "volume", "status", "key", "key_down", "key_up",
                   "gamepad.button", "gamepad.axis", "gamepad.release"]
DEJANJA_DATOTEKE = ["files.list", "files.open", "files.search"]
DEJANJA_PROGRAMI = ["apps.list", "apps.launch", "apps.close", "apps.running"]
DEJANJA_HOST = ["host.info"]
DEJANJA_ZASLON = ["screen.start", "screen.stop", "screen.status"]


def izvedi_control(dejanje: str, parametri: dict, odpri_naslov: Callable[[str], None],
                   koncaj: Callable[[dict], None], datoteke=None, posiljatelj: str = "",
                   hub_url: str = "", programi=None, zaslon=None) -> None:
    """Safeer Control (namizna aplikacija brez brskalnika): kar zna racunalnik brez brskalnika --
    glasnost, odpiranje strani v sistemskem brskalniku, stanje in seznam deljenih map
    (`files.list`, core/link_datoteke.py, ce je `datoteke` podan). Vse drugo vrne razumljivo napako."""
    d = (dejanje or "").strip().lower()
    parametri = parametri if isinstance(parametri, dict) else {}
    try:
        if d == "files.list":
            if datoteke is None:
                koncaj(izid(False, "Deljenje datotek tu ni na voljo", koda="ni_na_racunalniku"))
                return
            try:
                podatki = datoteke.seznam(str(parametri.get("folder", "") or ""), posiljatelj, hub_url)
            except FileNotFoundError as e:
                koncaj(izid(False, str(e), koda="ni_mape"))
                return
            if not podatki.get("shared"):
                koncaj(izid(True, "Na računalniku ni izbrane nobene mape", podatki))
            else:
                koncaj(izid(True, f"{len(podatki['items'])} vnosov", podatki))
        elif d == "files.search":
            # Enotno iskanje Safeer Media: glasba in videi deljenih map, ki ustrezajo poizvedbi.
            if datoteke is None:
                koncaj(izid(False, "Deljenje datotek tu ni na voljo", koda="ni_na_racunalniku"))
                return
            podatki = datoteke.isci(str(parametri.get("q", "") or "")[:200], posiljatelj, hub_url)
            koncaj(izid(True, f"{len(podatki['items'])} zadetkov", podatki))
        elif d == "files.open":
            # Datoteko odpre racunalnik s svojim programom; televizor jo nato vidi prek zaslona.
            if datoteke is None:
                koncaj(izid(False, "Deljenje datotek tu ni na voljo", koda="ni_na_racunalniku"))
                return
            if datoteke.odpri(str(parametri.get("id", "") or "")):
                koncaj(izid(True, "Datoteka se odpira na računalniku"))
            else:
                koncaj(izid(False, "Te datoteke ni mogoče odpreti", koda="ni_datoteke"))
        elif d in DEJANJA_ZASLON:
            # Zaslon racunalnika na televizorju. Brez uporabnikovega dovoljenja v Controlu ne gre.
            if zaslon is None:
                koncaj(izid(False, "Deljenje zaslona tu ni na voljo", koda="ni_na_racunalniku"))
                return
            if d == "screen.status":
                koncaj(izid(True, "Stanje zaslona", {**zaslon.na_voljo(), **zaslon.stanje()}))
                return
            if d == "screen.stop":
                # Uporabnik je na televizorju koncal program: zapremo ga tudi na racunalniku
                # (samo okna na locenem zaslonu - kar je odprto na namizju, ostane).
                drugi = getattr(zaslon, "drugi", None)
                if parametri.get("close_apps") and drugi is not None and hasattr(drugi, "zapri_okna"):
                    drugi.zapri_okna()
                zaslon.ustavi()
                koncaj(izid(True, "Deljenje zaslona je koncano"))
                return
            na_voljo = zaslon.na_voljo()
            if not na_voljo.get("dovoljeno"):
                koncaj(izid(False, "Uporabnik deljenja zaslona ni vklopil", koda="ni_dovoljeno"))
                return
            if not na_voljo.get("mozno"):
                koncaj(izid(False, "Tega zaslona ni mogoce zajeti", koda="ni_zajema"))
                return
            try:
                seja = zaslon.zacni(posiljatelj, str(parametri.get("quality", "") or "srednja"),
                                    str(parametri.get("screen", "") or "").strip().lower())
            except RuntimeError as e:
                # ProgramaNi: televizor je hotel program, ki ga ni vec - pove to in gre domov.
                koncaj(izid(False, str(e), koda="ni_programa" if type(e).__name__ == "ProgramaNi" else "ni_zajema"))
                return
            koncaj(izid(True, "Zaslon se deli", seja))
        elif d == "host.info":
            # Kaj ima ta racunalnik (host): procesor, pomnilnik, prostor. Samo stevilke o zmogljivosti,
            # nic o vsebini - televizor mora vedeti, koliko moci ima na voljo.
            koncaj(izid(True, "Podatki o računalniku", podatki_hosta()))
        elif d == "apps.list":
            # Programi racunalnika za televizor; brez dovoljenja uporabnika vrne prazen seznam.
            if programi is None:
                koncaj(izid(False, "Programi tu niso na voljo", koda="ni_na_racunalniku"))
                return
            # Po kosih: cel seznam z ikonami preseze omejitev sporocila (256 kB).
            koliko = parametri.get("limit")
            koliko = int(koliko) if isinstance(koliko, (int, float)) and koliko else 0
            od = parametri.get("offset")
            od = int(od) if isinstance(od, (int, float)) else 0
            z_ikonami = parametri.get("icons") is not False
            podatki = programi.seznam(z_ikonami=z_ikonami, od=od, koliko=max(0, min(koliko, 60)))
            if not podatki.get("enabled"):
                koncaj(izid(True, "Računalnik programov ne deli", podatki))
            else:
                koncaj(izid(True, f"{len(podatki['items'])} programov", podatki))
        elif d == "apps.launch":
            if programi is None:
                koncaj(izid(False, "Programi tu niso na voljo", koda="ni_na_racunalniku"))
                return
            oznaka = str(parametri.get("app", "") or "")
            if programi.zazeni(oznaka):
                koncaj(izid(True, "Program se zaganja"))
            else:
                koncaj(izid(False, "Tega programa ni na seznamu", koda="ni_programa"))
        elif d == "apps.running":
            # Kateri od teh programov res tece: televizor krizec v vrstici Nadaljuj pokaze samo pri
            # odprtih (prej je bil tudi pri programih, ki jih je konec seje ze zaprl).
            if programi is None:
                koncaj(izid(False, "Programi tu niso na voljo", koda="ni_na_racunalniku"))
                return
            oznake = parametri.get("apps") if isinstance(parametri.get("apps"), list) else []
            tecejo = [str(o) for o in oznake[:50] if isinstance(o, str) and programi.tece(o)]
            koncaj(izid(True, "Odprti programi", {"running": tecejo}))
        elif d == "apps.close":
            # Program, zagnan s televizorja, je doslej ostal odprt in jemal pomnilnik;
            # zdaj ga je mogoce zapreti z istega mesta, kjer si ga zagnal.
            if programi is None:
                koncaj(izid(False, "Programi tu niso na voljo", koda="ni_na_racunalniku"))
                return
            koliko = programi.zapri(str(parametri.get("app", "") or ""))
            if koliko > 0:
                koncaj(izid(True, "Program se zapira", {"closed": koliko}))
            else:
                koncaj(izid(False, "Ta program ne teče", koda="ne_tece"))
        elif d in ("gamepad.button", "gamepad.axis", "gamepad.release"):
            # Gamepad je samo dodaten nacin istega telefonskega daljinca. Ne odpira seje,
            # ne prestavlja dela in ob izhodu sprosti vse pritisnjene gumbe/osi.
            if zaslon is None or not zaslon.stanje().get("tece"):
                koncaj(izid(False, "Ni aktivne oddaljene seje", koda="ni_seje"))
                return
            if d == "gamepad.release":
                zaslon.sprosti_oddaljeni_plosek()
                koncaj(izid(True, "Igralni plošček sproščen"))
                return
            if d == "gamepad.button":
                g = str(parametri.get("button", "") or "").strip().lower()
                dovoljeni = {"a","b","x","y","l1","r1","l2","r2","izbira","zacni","domov","palica_l","palica_r"}
                if g not in dovoljeni:
                    koncaj(izid(False, "Gumb ni dovoljen", koda="nedovoljen_gumb")); return
                dog = {"vrsta":"plosek_gumb", "gumb":g, "dol":bool(parametri.get("down"))}
            else:
                o = str(parametri.get("axis", "") or "").strip().lower()
                dovoljene = {"leva_x","leva_y","desna_x","desna_y","sprozilec_l","sprozilec_r","krizec_x","krizec_y"}
                if o not in dovoljene:
                    koncaj(izid(False, "Os ni dovoljena", koda="nedovoljena_os")); return
                try: v = max(-1.0, min(1.0, float(parametri.get("value", 0))))
                except (TypeError, ValueError):
                    koncaj(izid(False, "Neveljavna vrednost osi", koda="napacna_vrednost")); return
                dog = {"vrsta":"plosek_os", "os":o, "vrednost":v}
            if zaslon.oddaljeni_plosek(dog):
                koncaj(izid(True, "Vnos igralnega ploščka poslan", {"controller":"phone-gamepad"}))
            else:
                koncaj(izid(False, "Igralni plošček ni na voljo", koda="plosek_ni_na_voljo"))
        elif d in ("key", "key_down", "key_up"):
            # Telefon je lahko opcijski kontroler Linux aplikacije, ki jo uporabnik
            # trenutno gleda na TV. To NI sinhronizacija in ne prevzame nobene naprave.
            if zaslon is None or not zaslon.stanje().get("tece"):
                koncaj(izid(False, "Ni aktivne oddaljene seje", koda="ni_seje"))
                return
            k = str(parametri.get("key", "") or "").strip().lower()
            preslikava = {
                "up":"gor", "down":"dol", "left":"levo", "right":"desno",
                "ok":"vnasalka", "center":"vnasalka", "back":"ubezna",
                "play_pause":"predvajaj", "stop":"ustavi",
            }
            tipka = preslikava.get(k)
            if not tipka:
                koncaj(izid(False, "Tipka ni dovoljena", koda="nedovoljena_tipka"))
                return
            vrsta = "tipka" if d == "key" else ("tipka_dol" if d == "key_down" else "tipka_gor")
            if zaslon.oddaljeni_vnos({"vrsta": vrsta, "tipka": tipka}):
                koncaj(izid(True, "Vnos poslan", {"controller": "phone-compatible"}))
            else:
                koncaj(izid(False, "Vnosa ni bilo mogoče poslati", koda="vnos_ni_na_voljo"))
        elif d == "open_url":
            url = str(parametri.get("url", "")).strip()
            if not (url.startswith("http://") or url.startswith("https://")):
                koncaj(izid(False, "Dovoljeni so samo naslovi http(s)"))
                return
            odpri_naslov(url)
            koncaj(izid(True, "Stran se odpira"))
        elif d == "volume":
            koncaj(_glasnost(parametri))
        elif d == "status":
            s = {"app": "safeer-control-linux", "version": _razlicica_control(), "foreground": True,
                 "actions": DEJANJA_CONTROL + DEJANJA_HOST + (DEJANJA_DATOTEKE if datoteke is not None else [])
                            + (DEJANJA_PROGRAMI if programi is not None and programi.vklopljeno else [])
                            + (DEJANJA_ZASLON if zaslon is not None and zaslon.na_voljo().get("dovoljeno") else []),
                 "keys": (["up", "down", "left", "right", "ok", "back", "play_pause", "stop"]
                          if zaslon is not None and zaslon.stanje().get("tece") else []),
                 "title": "Safeer Control"}
            if datoteke is not None:
                s["shared_folders"] = len(datoteke.poti())
            try:
                s["hostname"] = os.uname().nodename
            except Exception:
                pass
            g = _glasnost({})
            if g.get("ok") and g.get("data"):
                s["volume"] = g["data"].get("level")
                s["muted"] = g["data"].get("muted")
            koncaj(izid(True, "Stanje", s))
        elif d in DEJANJA:
            koncaj(izid(False, "Na Safeer Controlu to ni na voljo (ni brskalnika)", koda="ni_v_ospredju"))
        else:
            koncaj(izid(False, f"Neznano dejanje: {d}" if d else "Manjka dejanje", koda="neznano_dejanje"))
    except Exception as e:  # noqa: BLE001
        koncaj(izid(False, f"Ukaz ni uspel: {e}"))


def podatki_hosta() -> dict:
    """Procesor, pomnilnik in prostor tega racunalnika (Linux: /proc in os.statvfs)."""
    p: Dict[str, object] = {}
    try:
        p["hostname"] = os.uname().nodename
        p["sistem"] = _ime_sistema()
    except Exception:
        pass
    # Procesor: ime, stevilo jeder, povprecna obremenitev zadnje minute
    cpu: Dict[str, object] = {}
    try:
        cpu["jedra"] = os.cpu_count() or 0
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
            for vrstica in f:
                if vrstica.lower().startswith("model name"):
                    cpu["model"] = vrstica.split(":", 1)[1].strip()
                    break
        cpu["obremenitev"] = round(os.getloadavg()[0], 2)
    except Exception:
        pass
    if cpu:
        p["cpu"] = cpu
    # Pomnilnik: skupaj in res na voljo (MemAvailable, ne le prosti)
    ram: Dict[str, object] = {}
    try:
        with open("/proc/meminfo", encoding="utf-8", errors="replace") as f:
            for vrstica in f:
                kljuc, _, vrednost = vrstica.partition(":")
                if kljuc == "MemTotal":
                    ram["skupaj"] = int(vrednost.split()[0]) * 1024
                elif kljuc == "MemAvailable":
                    ram["prosto"] = int(vrednost.split()[0]) * 1024
    except Exception:
        pass
    if ram:
        p["ram"] = ram
    # Prostor: disk, na katerem je domaca mapa uporabnika
    try:
        st = os.statvfs(os.path.expanduser("~"))
        p["disk"] = {"skupaj": st.f_blocks * st.f_frsize, "prosto": st.f_bavail * st.f_frsize}
    except Exception:
        pass
    # Graficna kartica: od nje je odvisno, kako tekoca je slika racunalnika na televizorju
    gpu = _graficna()
    if gpu:
        p["gpu"] = gpu
    return p


def _graficna() -> Dict[str, object]:
    """Ime graficne kartice, gonilnik jedra in ali zna strojno kodirati sliko (VA-API).

    Beremo samo tisto, kar je na Linuxu pri roki: `lspci` za ime in /sys/class/drm za gonilnik.
    Nicesar ne namescamo in nic ne gre v splet; ce cesa ni, tisti podatek preprosto izpustimo."""
    g: Dict[str, object] = {}
    lspci = shutil.which("lspci")
    if lspci:
        try:
            izpis = subprocess.run([lspci, "-mm"], capture_output=True, text=True, timeout=3).stdout
            for vrstica in izpis.splitlines():
                if not any(razred in vrstica for razred in
                           ('"VGA compatible controller"', '"3D controller"', '"Display controller"')):
                    continue
                deli = re.findall(r'"([^"]*)"', vrstica)
                if len(deli) >= 3:
                    ime = (deli[1] + " " + deli[2]).strip()
                    g["model"] = re.sub(r"\s*\((rev|prog-if)[^)]*\)", "", ime).strip()
                break
        except Exception:
            pass
    try:
        for kartica in sorted(os.listdir("/sys/class/drm")):
            if not re.fullmatch(r"card\d+", kartica):
                continue
            gonilnik = os.path.basename(os.path.realpath(
                os.path.join("/sys/class/drm", kartica, "device", "driver")))
            if gonilnik and gonilnik != "driver":
                g["gonilnik"] = gonilnik
                break
    except Exception:
        pass
    try:
        from . import link_zaslon
        g["strojno"] = bool(link_zaslon.vaapi_naprava())
    except Exception:
        pass
    return g


def _ime_sistema() -> str:
    try:
        with open("/etc/os-release", encoding="utf-8", errors="replace") as f:
            for vrstica in f:
                if vrstica.startswith("PRETTY_NAME="):
                    return vrstica.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    return "Linux"


def _razlicica_control() -> str:
    try:
        tu = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(tu, "packaging", "VERSION_CONTROL"), encoding="utf-8") as d:
            return d.read().strip()
    except Exception:
        return ""


def _webview(app):
    try:
        return app.get_active_webview()
    except Exception:
        return None


def _tipka(app, ime: str) -> dict:
    wv = _webview(app)
    if ime == "home":
        app.load_homepage()
        return izid(True, "Domov")
    if wv is None:
        return izid(False, "Ni odprtega zavihka")
    if ime == "back":
        if wv.can_go_back():
            wv.go_back()
            return izid(True, "Nazaj")
        return izid(False, "Ni strani za nazaj")
    if ime == "forward":
        if wv.can_go_forward():
            wv.go_forward()
            return izid(True, "Naprej")
        return izid(False, "Ni strani za naprej")
    if ime == "reload":
        wv.reload()
        return izid(True, "Osvezeno")
    if ime in ("up", "page_up"):
        return _drsenje(app, "up")
    if ime in ("down", "page_down"):
        return _drsenje(app, "down")
    if ime in ("play_pause", "play", "pause", "stop", "mute", "unmute"):
        telo = {
            "play_pause": "if(v.paused){v.play();}else{v.pause();}",
            "play": "v.play();",
            "pause": "v.pause();",
            "stop": "v.pause();v.currentTime=0;",
            "mute": "v.muted=true;",
            "unmute": "v.muted=false;",
        }[ime]
        wv.run_javascript(_js_video(telo), None, None, None)
        return izid(True, f"Tipka {ime}")
    if ime in ("left", "right", "ok", "center", "menu"):
        return izid(False, "Tipke daljinca na racunalniku ni; uporabi misko ali tipkovnico", koda="ni_na_racunalniku")
    return izid(False, f"Neznana tipka: {ime}", koda="neznana_tipka")


def _drsenje(app, smer: str) -> dict:
    wv = _webview(app)
    if wv is None:
        return izid(False, "Ni odprtega zavihka")
    js = {
        "up": "window.scrollBy({top:-Math.round(window.innerHeight*0.8),behavior:'smooth'})",
        "down": "window.scrollBy({top:Math.round(window.innerHeight*0.8),behavior:'smooth'})",
        "top": "window.scrollTo({top:0,behavior:'smooth'})",
        "bottom": "window.scrollTo({top:document.documentElement.scrollHeight,behavior:'smooth'})",
    }.get(smer)
    if not js:
        return izid(False, f"Neznana smer: {smer}")
    wv.run_javascript(js, None, None, None)
    return izid(True, f"Drsenje {smer}")


def _odpri(app, url: str, odpri_naslov: Callable[[str], None]) -> dict:
    if url in ("home", "safeer://home"):
        app.load_homepage()
        return izid(True, "Domov")
    if not (url.startswith("http://") or url.startswith("https://")):
        return izid(False, "Dovoljeni so samo naslovi http(s)")
    odpri_naslov(url)
    return izid(True, "Stran se odpira")


def _pactl(*argumenti: str) -> subprocess.CompletedProcess:
    return subprocess.run(["pactl", *argumenti], capture_output=True, text=True, timeout=3)


def _glasnost(parametri: dict) -> dict:
    """Glasnost racunalnika prek PulseAudio/PipeWire (pactl); brez njega dejanja ni."""
    if not shutil.which("pactl"):
        return izid(False, "Glasnosti tu ni mogoce nastaviti (ni pactl)")
    smer = str(parametri.get("direction", "")).strip().lower()
    raven = parametri.get("level")
    try:
        if isinstance(raven, (int, float)) and 0 <= int(raven) <= 100:
            _pactl("set-sink-volume", "@DEFAULT_SINK@", f"{int(raven)}%")
        elif smer == "up":
            _pactl("set-sink-volume", "@DEFAULT_SINK@", "+5%")
        elif smer == "down":
            _pactl("set-sink-volume", "@DEFAULT_SINK@", "-5%")
        elif smer == "mute":
            _pactl("set-sink-mute", "@DEFAULT_SINK@", "1")
        elif smer == "unmute":
            _pactl("set-sink-mute", "@DEFAULT_SINK@", "0")
        elif smer == "toggle_mute":
            _pactl("set-sink-mute", "@DEFAULT_SINK@", "toggle")
        elif smer:
            return izid(False, f"Neznana smer glasnosti: {smer}")
        trenutno = _pactl("get-sink-volume", "@DEFAULT_SINK@").stdout
        utisano = "yes" in _pactl("get-sink-mute", "@DEFAULT_SINK@").stdout.lower()
    except Exception as e:  # noqa: BLE001
        return izid(False, f"Glasnosti ni bilo mogoce nastaviti: {e}")
    odstotki = None
    for kos in trenutno.replace("/", " ").split():
        if kos.endswith("%") and kos[:-1].isdigit():
            odstotki = int(kos[:-1])
            break
    podatki = {"level": odstotki, "muted": utisano}
    return izid(True, f"Glasnost {odstotki if odstotki is not None else '?'} %", podatki)


def _znova_zazeni(app) -> dict:
    """Zazene nov primerek istega programa in ta konca. Odprti zavihki se obnovijo iz seje."""
    ukaz = [sys.executable] + list(sys.argv)
    try:
        subprocess.Popen(ukaz, start_new_session=True, close_fds=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:  # noqa: BLE001
        return izid(False, f"Ponovnega zagona ni bilo mogoce zaceti: {e}")
    from gi.repository import GLib

    def koncaj():
        try:
            app.close()
        except Exception:
            pass
        try:
            from gi.repository import Gtk
            Gtk.main_quit()
        except Exception:
            pass
        return False
    GLib.timeout_add(600, koncaj)
    return izid(True, "Safeer se znova zaganja")


def _pocisti(app) -> dict:
    """Pocisti predpomnilnik WebKita (ne piskotkov in ne gesel)."""
    try:
        import gi
        gi.require_version("WebKit2", "4.1")
        from gi.repository import WebKit2
        wv = _webview(app)
        kontekst = wv.get_context() if wv is not None else WebKit2.WebContext.get_default()
        upravitelj = kontekst.get_website_data_manager()
        vrste = (WebKit2.WebsiteDataTypes.DISK_CACHE | WebKit2.WebsiteDataTypes.MEMORY_CACHE
                 | WebKit2.WebsiteDataTypes.OFFLINE_APPLICATION_CACHE)
        upravitelj.clear(vrste, 0, None, None, None)
        return izid(True, "Predpomnilnik pociscen")
    except Exception as e:  # noqa: BLE001
        return izid(False, f"Predpomnilnika ni bilo mogoce pocistiti: {e}")


def stanje(app) -> dict:
    wv = _webview(app)
    s = {
        "app": "safeer-browser-linux",
        "version": _razlicica(),
        "foreground": True,
        "actions": DEJANJA,
        "keys": TIPKE,
        "url": (wv.get_uri() if wv is not None else "") or "",
        "title": (wv.get_title() if wv is not None else "") or "",
    }
    try:
        s["hostname"] = os.uname().nodename
    except Exception:
        pass
    return s


def _posnetek(app, koncaj: Callable[[dict], None]) -> None:
    """Posnetek vidnega dela dejavnega zavihka, pomanjsan na 640 px, kot JPEG (data URL)."""
    wv = _webview(app)
    if wv is None:
        koncaj(izid(False, "Ni odprtega zavihka"))
        return
    import gi
    gi.require_version("WebKit2", "4.1")
    gi.require_version("Gdk", "3.0")
    from gi.repository import WebKit2, Gdk, GdkPixbuf  # noqa: F401
    import base64

    def gotovo(pogled, rezultat):
        try:
            povrsina = pogled.get_snapshot_finish(rezultat)
            sirina, visina = povrsina.get_width(), povrsina.get_height()
            if sirina <= 0 or visina <= 0:
                koncaj(izid(False, "Zaslon se ni pripravljen"))
                return
            slika = Gdk.pixbuf_get_from_surface(povrsina, 0, 0, sirina, visina)
            merilo = min(1.0, 640.0 / sirina)
            if merilo < 1.0:
                slika = slika.scale_simple(max(1, int(sirina * merilo)), max(1, int(visina * merilo)),
                                           GdkPixbuf.InterpType.BILINEAR)
            ok, bajti = slika.save_to_bufferv("jpeg", ["quality"], ["55"])
            if not ok:
                koncaj(izid(False, "Posnetka ni bilo mogoce zakodirati"))
                return
            koncaj(izid(True, "Posnetek zaslona", {
                "image": "data:image/jpeg;base64," + base64.b64encode(bytes(bajti)).decode("ascii"),
                "width": slika.get_width(), "height": slika.get_height(),
            }))
        except Exception as e:  # noqa: BLE001
            koncaj(izid(False, f"Posnetka ni bilo mogoce narediti: {e}"))

    try:
        wv.get_snapshot(WebKit2.SnapshotRegion.VISIBLE, WebKit2.SnapshotOptions.NONE, None, gotovo)
    except Exception as e:  # noqa: BLE001
        koncaj(izid(False, f"Posnetka ni bilo mogoce narediti: {e}"))


__all__ = ["ZMOZNOST", "DEJANJA", "TIPKE", "izvedi", "izid", "sporocilo_izida", "stanje"]
