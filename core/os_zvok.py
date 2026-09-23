"""Zvok za Safeer OS na Linuxu: izhodi, vhodi in glasnost programov prek zvocnega streznika
(PipeWire s plastjo PulseAudio - `pactl`), ki ga uporablja tudi Linux Mint.

Namesto Mintovega okna »Zvok« pokaze Safeer OS svojo stran: kam gre zvok (zvocniki, slusalke,
HDMI, Bluetooth in - novo - naprave v Safeer Linku), glasnost vsakega izhoda in vhoda ter
glasnost in izhod vsakega programa posebej. Posebne nastavitve (profili kartic, zvoki sistema)
ostanejo v Mintovem orodju pod »Napredno«.

Zvok na napravo v Safeer Linku (televizor, tablica) zacne Safeer Control (ima potrdilo in
povezavo s hubom): ustvari navidezni izhod, nanj preusmeri programe in zvok neposredno poslje
napravi. Tu samo preberemo, katere naprave to znajo in kaj trenutno tece (datoteka stanja v
XDG_RUNTIME_DIR, ki jo pise Control).

Vsak ukaz je fiksen seznam argumentov (brez lupine); imena izhodov in stevilke tokov pridejo s
strani, zato jih pred uporabo preverimo na trenutnem seznamu.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple

#: Ime navideznega izhoda, prek katerega gre zvok na napravo v Safeer Linku (core/link_zvok.py).
LINK_IZHOD = "safeer_link_zvok"
#: Zmoznost, s katero se naprava v Safeer Linku javi, da zna predvajati zvok racunalnika.
ZMOZNOST_ZVOK = "audio"


def mapa_stanja() -> str:
    return os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid(), "safeer-link")


def _okolje() -> dict:
    """pactl izpise stevila po jeziku uporabnika (0,50 v slovenscini), kar bi pokvarilo JSON;
    besedila (imena naprav) pa morajo ostati UTF-8."""
    o = dict(os.environ)
    o.pop("LC_ALL", None)
    if not (o.get("LANG") or "").lower().endswith(("utf-8", "utf8")):
        o["LANG"] = "C.UTF-8"
    o["LC_NUMERIC"] = "C"
    return o


def _pactl(argumenti: List[str], cas: float = 4.0) -> Tuple[int, str]:
    if shutil.which("pactl") is None:
        return 127, ""
    try:
        r = subprocess.run(["pactl"] + argumenti, capture_output=True, text=True, timeout=cas, env=_okolje())
        return r.returncode, r.stdout
    except Exception:
        return 1, ""


def _json(argumenti: List[str]) -> list:
    koda, izpis = _pactl(["-f", "json"] + argumenti)
    if koda != 0 or not izpis.strip():
        return []
    try:
        podatki = json.loads(izpis)
    except ValueError:
        try:   # starejsi pactl kljub LC_NUMERIC izpise decimalno vejico
            podatki = json.loads(re.sub(r'(":\s*-?\d+),(\d+)', r"\1.\2", izpis))
        except ValueError:
            return []
    return podatki if isinstance(podatki, list) else []


def _odstotek(glasnost) -> int:
    """Povprecje kanalov v odstotkih (pactl: {"front-left": {"value_percent": "27%"}, ...})."""
    vrednosti = []
    for kanal in (glasnost or {}).values():
        m = re.match(r"\s*(\d+)", str((kanal or {}).get("value_percent", "")))
        if m:
            vrednosti.append(int(m.group(1)))
    return int(round(sum(vrednosti) / len(vrednosti))) if vrednosti else 0


def _privzeto() -> Tuple[str, str]:
    """Privzeti izhod in vhod. `pactl info` je preveden (»Privzeti ponor«), zato vprasamo naravnost."""
    return _pactl(["get-default-sink"])[1].strip(), _pactl(["get-default-source"])[1].strip()


def _vrsta(n: dict) -> str:
    """bluetooth / hdmi / usb / slusalke / zvocniki / mikrofon - za ikono in ime na strani."""
    p = n.get("properties") or {}
    ime = str(n.get("name", "")).lower()
    port = str(n.get("active_port") or "").lower()
    vrsta_porta = ""
    for v in n.get("ports") or []:
        if v.get("name") == n.get("active_port"):
            vrsta_porta = str(v.get("type") or "").lower()
    if p.get("device.bus") == "bluetooth" or ime.startswith("bluez"):
        return "bluetooth"
    if "hdmi" in ime or "hdmi" in port or vrsta_porta in ("hdmi", "displayport"):
        return "hdmi"
    if p.get("device.bus") == "usb":
        return "usb"
    if "headphone" in port or "headset" in port or vrsta_porta in ("headphones", "headset"):
        return "slusalke"
    if "mic" in port or vrsta_porta == "mic":
        return "mikrofon"
    return "zvocniki"


def _aktivni_port(n: dict) -> dict:
    for v in n.get("ports") or []:
        if v.get("name") == n.get("active_port"):
            return v
    return {}


def _ime(n: dict) -> Tuple[str, str]:
    """Kratko ime in podnapis. Bluetooth ima uporabnikovo ime naprave; vgrajena kartica pa dolgo
    ime cipa - tam je bolj povedno ime vrat (Zvocniki, Slusalke, HDMI / DisplayPort 1)."""
    p = n.get("properties") or {}
    opis = str(n.get("description") or n.get("name") or "")
    if _vrsta(n) == "bluetooth":
        return opis, "Bluetooth"
    port = str(_aktivni_port(n).get("description") or p.get("device.profile.description") or "")
    izdelek = str(p.get("device.product.name") or p.get("device.description") or "")
    if port and izdelek:
        return port, izdelek
    return opis, ""


def _dosegljiv(n: dict) -> bool:
    return str(_aktivni_port(n).get("availability") or "") != "not available"


def izhodi() -> List[dict]:
    privzeti, _ = _privzeto()
    izhod = []
    for n in _json(["list", "sinks"]):
        ime = str(n.get("name") or "")
        if not ime or ime == LINK_IZHOD:
            continue          # navidezni izhod Safeer Linka pokazemo kot napravo, ne kot kartico
        if not _dosegljiv(n) and ime != privzeti:
            continue          # HDMI brez prikljucenega zaslona ipd.
        naslov, podnapis = _ime(n)
        izhod.append({"id": ime, "ime": naslov, "podnapis": podnapis, "vrsta": _vrsta(n),
                      "privzeti": ime == privzeti, "glasnost": _odstotek(n.get("volume")),
                      "utisan": bool(n.get("mute")), "indeks": n.get("index")})
    return sorted(izhod, key=lambda i: (not i["privzeti"], i["vrsta"] != "bluetooth", i["ime"].lower()))


def vhodi() -> List[dict]:
    _, privzeti = _privzeto()
    izhod = []
    for n in _json(["list", "sources"]):
        ime = str(n.get("name") or "")
        p = n.get("properties") or {}
        if not ime or ime.endswith(".monitor") or p.get("device.class") == "monitor":
            continue
        if not _dosegljiv(n) and ime != privzeti:
            continue
        naslov, podnapis = _ime(n)
        vrsta = _vrsta(n)
        izhod.append({"id": ime, "ime": naslov, "podnapis": podnapis,
                      "vrsta": "bluetooth" if vrsta == "bluetooth" else "mikrofon",
                      "privzeti": ime == privzeti, "glasnost": _odstotek(n.get("volume")),
                      "utisan": bool(n.get("mute"))})
    return sorted(izhod, key=lambda i: (not i["privzeti"], i["ime"].lower()))


def _kljuc_programa(p: dict) -> str:
    return "%s|%s" % (p.get("application.process.binary") or "", p.get("application.name") or "")


def programi() -> List[dict]:
    """Programi, ki predvajajo zvok, zdruzeni po programu (brskalnik ima lahko vec tokov)."""
    skupine: Dict[str, dict] = {}
    indeksi_izhodov = {n.get("index"): str(n.get("name") or "") for n in _json(["list", "sinks"])}
    for t in _json(["list", "sink-inputs"]):
        p = t.get("properties") or {}
        if p.get("application.id") == "org.PulseAudio.pavucontrol":
            continue
        kljuc = _kljuc_programa(p)
        ime = str(p.get("application.name") or p.get("application.process.binary") or p.get("media.name") or "?")
        s = skupine.setdefault(kljuc, {"id": kljuc, "ime": ime, "ikona": str(p.get("application.icon_name") or ""),
                                       "tokovi": [], "glasnost": 0, "utisan": True, "predvaja": False,
                                       "izhod": ""})
        s["tokovi"].append(t.get("index"))
        s["glasnost"] = max(s["glasnost"], _odstotek(t.get("volume")))
        s["utisan"] = s["utisan"] and bool(t.get("mute"))
        if not t.get("corked"):
            s["predvaja"] = True
            s["naslov"] = str(p.get("media.name") or "")
        s["izhod"] = s["izhod"] or indeksi_izhodov.get(t.get("sink"), "")
    return sorted(skupine.values(), key=lambda s: (not s["predvaja"], s["ime"].lower()))


# ---------------------------------------------------------------------- Safeer Link
def _beri_stanje_linka() -> dict:
    try:
        with open(os.path.join(mapa_stanja(), "stanje.json"), encoding="utf-8") as f:
            podatki = json.load(f)
        return podatki if isinstance(podatki, dict) else {}
    except Exception:
        return {}


def link_naprave() -> dict:
    """Naprave v Safeer Linku, ki znajo predvajati zvok racunalnika, in tekoca seja (ce je)."""
    s = _beri_stanje_linka()
    naprave = []
    for d in (s.get("naprave") or []) if s.get("povezan") else []:
        if not isinstance(d, dict) or ZMOZNOST_ZVOK not in (d.get("zmoznosti") or []):
            continue
        naprave.append({"id": str(d.get("id") or ""), "ime": str(d.get("ime") or ""),
                        "platforma": str(d.get("platforma") or ""), "vrsta": str(d.get("vrsta") or "")})
    zvok = s.get("zvok") if isinstance(s.get("zvok"), dict) else {}
    return {"naprave": naprave, "zvok": {"naprava": str(zvok.get("naprava") or ""),
                                         "ime": str(zvok.get("ime") or ""),
                                         "stanje": str(zvok.get("stanje") or "")},
            "povezan": bool(s.get("povezan"))}


def stanje() -> dict:
    return {"izhodi": izhodi(), "vhodi": vhodi(), "programi": programi(), "link": link_naprave(),
            "napredno": shutil.which("cinnamon-settings") is not None}


# ---------------------------------------------------------------------- dejanja
def _imena(vrsta: str) -> List[str]:
    return [str(n.get("name") or "") for n in _json(["list", vrsta])]


def nastavi_izhod(ime: str) -> bool:
    """Privzeti izhod in vsi programi, ki ta trenutek predvajajo, gredo nanj (kot v Mintu)."""
    ime = str(ime or "")
    if ime not in _imena("sinks"):
        return False
    if _pactl(["set-default-sink", ime])[0] != 0:
        return False
    for t in _json(["list", "sink-inputs"]):
        _pactl(["move-sink-input", str(t.get("index")), ime])
    return True


def nastavi_vhod(ime: str) -> bool:
    ime = str(ime or "")
    if ime not in _imena("sources") or ime.endswith(".monitor"):
        return False
    return _pactl(["set-default-source", ime])[0] == 0


def _omeji(odstotek) -> int:
    return max(0, min(150, int(odstotek)))


def glasnost_izhoda(ime: str, odstotek: int) -> bool:
    ime = str(ime or "")
    if ime not in _imena("sinks"):
        return False
    ok = _pactl(["set-sink-volume", ime, "%d%%" % _omeji(odstotek)])[0] == 0
    _pactl(["set-sink-mute", ime, "0"])
    return ok


def utisaj_izhod(ime: str, utisan: bool) -> bool:
    ime = str(ime or "")
    return ime in _imena("sinks") and _pactl(["set-sink-mute", ime, "1" if utisan else "0"])[0] == 0


def glasnost_vhoda(ime: str, odstotek: int) -> bool:
    ime = str(ime or "")
    if ime not in _imena("sources"):
        return False
    ok = _pactl(["set-source-volume", ime, "%d%%" % _omeji(odstotek)])[0] == 0
    _pactl(["set-source-mute", ime, "0"])
    return ok


def utisaj_vhod(ime: str, utisan: bool) -> bool:
    ime = str(ime or "")
    return ime in _imena("sources") and _pactl(["set-source-mute", ime, "1" if utisan else "0"])[0] == 0


def _tokovi(kljuc: str) -> List[str]:
    return [str(t.get("index")) for t in _json(["list", "sink-inputs"])
            if _kljuc_programa(t.get("properties") or {}) == str(kljuc or "")]


def glasnost_programa(kljuc: str, odstotek: int) -> bool:
    tokovi = _tokovi(kljuc)
    for t in tokovi:
        _pactl(["set-sink-input-volume", t, "%d%%" % _omeji(odstotek)])
        _pactl(["set-sink-input-mute", t, "0"])
    return bool(tokovi)


def utisaj_program(kljuc: str, utisan: bool) -> bool:
    tokovi = _tokovi(kljuc)
    for t in tokovi:
        _pactl(["set-sink-input-mute", t, "1" if utisan else "0"])
    return bool(tokovi)


def premakni_program(kljuc: str, izhod: str) -> bool:
    """En program na drug izhod (npr. glasba na Bluetooth, klic ostane na slusalkah)."""
    izhod = str(izhod or "")
    if izhod not in _imena("sinks"):
        return False
    tokovi = _tokovi(kljuc)
    for t in tokovi:
        _pactl(["move-sink-input", t, izhod])
    return bool(tokovi)
