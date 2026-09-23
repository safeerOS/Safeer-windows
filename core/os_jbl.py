"""Zvocna vrstica JBL (JBL One: Bar 300/500/700/800/1000/1300, Authentics) - samodejni preklop vhoda.

Zvocna vrstica igra en vhod naenkrat. Ce je racunalnik z njo povezan po Bluetoothu, televizor pa po
HDMI eARC, mora uporabnik ob »Predvajaj na TV« na vrstici pritisniti TV in ob vrnitvi BT. Safeer OS to
naredi sam: ob izbiri televizorja poslje vrstici »vhod TV«, ob izbiri te vrstice kot izhoda (Bluetooth)
pa »vhod Bluetooth«. En ukaz na preklop, nobenega stalnega preverjanja.

Vrstica sprejme ukaze v domacem omrezju (https://<naslov>/httpapi.asp) samo od odjemalca z
potrdilom aplikacije JBL One. Potrdila ne nosimo s seboj in ga ni v repozitoriju: ko uporabnik dodatek
vklopi, ga prenesemo iz odprtokodnega projekta JBL_Soundbar (MIT, Home Assistant) na natanko dolocenem
commitu in preverimo odtis SHA-256. Hrani se samo v uporabnikovi mapi (0700). Privzeto izklopljeno.

Vrstico najdemo po mDNS (_jbl-product._tcp); naslov Bluetooth vrne sama (getStatusEx, BT_MAC), tako
da vemo, kateri izhod racunalnika je ta vrstica.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import urllib.parse
import urllib.request
from typing import List, Optional

VIR = ("https://raw.githubusercontent.com/MrBearPresident/JBL_Soundbar/"
       "9976c48755ad9d6725e281396c977a813cb9153b/custom_components/jbl_integration/")
ODTISI = {
    "Cert.pem": "1f85e91cc6af33a2042a0bc27dae95c6b37492d1e1e384e45a00bbb8789d1c55",
    "Key.pem": "b072d78a8b259360b679478b8bf75ee4765ce7762f5f06574bff4d1e9e450099",
}
TIPKE = {"tv": "source-tv", "bluetooth": "bluetooth"}


def mapa() -> str:
    return os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "safeer-os", "jbl")


def _nastavitve_pot() -> str:
    return os.path.join(mapa(), "nastavitve.json")


def nastavitve() -> dict:
    try:
        with open(_nastavitve_pot(), encoding="utf-8") as f:
            n = json.load(f)
        return n if isinstance(n, dict) else {}
    except Exception:
        return {}


def _shrani(n: dict) -> None:
    os.makedirs(mapa(), mode=0o700, exist_ok=True)
    zacasna = _nastavitve_pot() + ".tmp"
    with open(zacasna, "w", encoding="utf-8") as f:
        json.dump(n, f)
    os.replace(zacasna, _nastavitve_pot())


def ima_potrdilo() -> bool:
    for ime, odtis in ODTISI.items():
        try:
            with open(os.path.join(mapa(), ime), "rb") as f:
                if hashlib.sha256(f.read()).hexdigest() != odtis:
                    return False
        except OSError:
            return False
    return True


def prenesi_potrdilo(odpri=urllib.request.urlopen) -> bool:
    """Potrdilo JBL One z dolocenega commita; brez ujemanja odtisa ne shranimo nicesar."""
    vsebina = {}
    for ime, odtis in ODTISI.items():
        with odpri(VIR + ime, timeout=15) as o:
            b = o.read()
        if hashlib.sha256(b).hexdigest() != odtis:
            return False
        vsebina[ime] = b
    os.makedirs(mapa(), mode=0o700, exist_ok=True)
    for ime, b in vsebina.items():
        pot = os.path.join(mapa(), ime)
        with open(os.open(pot, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as f:
            f.write(b)
    return True


def _kontekst() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # Vrstica ima samopodpisano potrdilo brez imena; zaupamo ji v domacem omrezju, ukazi so nenevarni.
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.load_cert_chain(os.path.join(mapa(), "Cert.pem"), os.path.join(mapa(), "Key.pem"))
    return ctx


def _zahteva(naslov: str, ukaz: str, payload: Optional[dict] = None, cas: float = 5.0) -> str:
    if not re.fullmatch(r"[0-9a-fA-F:.]{3,45}", naslov or ""):
        raise ValueError("neveljaven naslov")
    url = "https://%s/httpapi.asp" % (("[%s]" % naslov) if ":" in naslov else naslov)
    if payload is None:
        z = urllib.request.Request(url + "?command=" + urllib.parse.quote(ukaz))
    else:
        telo = "command=%s&payload=%s" % (ukaz, json.dumps(payload, separators=(",", ":")))
        z = urllib.request.Request(url, data=telo.encode("utf-8"), method="POST")
    with urllib.request.urlopen(z, context=_kontekst(), timeout=cas) as o:
        return o.read(4096).decode("utf-8", "replace")


def najdi(cas: float = 4.0) -> List[dict]:
    """Vrstice JBL One v omrezju (mDNS _jbl-product._tcp): ime, naslov IPv4, naslov Wi-Fi."""
    if not shutil.which("avahi-browse"):
        return []
    try:
        izpis = subprocess.run(["avahi-browse", "-rpt", "-k", "_jbl-product._tcp"], capture_output=True,
                               text=True, timeout=cas + 4).stdout
    except Exception:
        return []
    najdene = {}
    for v in izpis.splitlines():
        d = v.split(";")
        if len(d) < 10 or d[0] != "=" or d[2] != "IPv4":
            continue
        ime = re.sub(r"\\(\d{3})", lambda m: chr(int(m.group(1))), d[3])
        mac = (re.search(r'"MAC=([0-9A-Fa-f:]{17})"', v) or [None, ""])[1]
        najdene[d[7]] = {"ime": ime, "naslov": d[7], "mac": mac.upper()}
    return sorted(najdene.values(), key=lambda n: n["ime"])


def bt_naslov(naslov: str) -> str:
    """Naslov Bluetooth vrstice (getStatusEx) - po njem prepoznamo izhod racunalnika."""
    try:
        m = re.search(r'"BT_MAC"\s*:\s*"([0-9A-Fa-f:]{17})"', _zahteva(naslov, "getStatusEx"))
        return m.group(1).upper() if m else ""
    except Exception:
        return ""


def vklopi(vklop: bool) -> dict:
    """Vklop: prenese in preveri potrdilo, najde vrstico in si zapomni njen Bluetooth naslov."""
    n = nastavitve()
    if not vklop:
        n["vklop"] = False
        _shrani(n)
        return stanje()
    if not ima_potrdilo():
        try:
            if not prenesi_potrdilo():
                return dict(stanje(), napaka="potrdilo")
        except Exception:
            return dict(stanje(), napaka="prenos")
    vrstice = najdi()
    if not vrstice:
        return dict(stanje(), napaka="ni_vrstice")
    v = vrstice[0]
    bt = bt_naslov(v["naslov"])
    if not bt:
        return dict(stanje(), napaka="ne_odgovori")
    n.update({"vklop": True, "ime": v["ime"], "naslov": v["naslov"], "bt": bt})
    _shrani(n)
    return stanje()


def stanje(isci: bool = False) -> dict:
    n = nastavitve()
    izid = {"vklop": bool(n.get("vklop")) and ima_potrdilo(), "ime": n.get("ime", ""), "bt": n.get("bt", "")}
    if isci and not izid["vklop"]:
        vrstice = najdi(3.0)
        if vrstice:
            izid["ime"] = izid["ime"] or vrstice[0]["ime"]
            izid["najdena"] = True
    else:
        izid["najdena"] = bool(n.get("naslov"))
    return izid


def _mac_izhoda(ime_izhoda: str) -> str:
    """bluez_output.4C_6B_B8_90_BA_65.1 -> 4C:6B:B8:90:BA:65"""
    m = re.match(r"bluez_output\.([0-9A-Fa-f_]{17})", ime_izhoda or "")
    return m.group(1).replace("_", ":").upper() if m else ""


def je_vrstica(ime_izhoda: str) -> bool:
    n = nastavitve()
    return bool(n.get("vklop") and n.get("bt")) and _mac_izhoda(ime_izhoda) == n.get("bt")


def preklopi(vhod: str) -> bool:
    """Vhod vrstice: "tv" ali "bluetooth". Samo ce je dodatek vklopljen; en ukaz, brez ponavljanja."""
    n = nastavitve()
    if vhod not in TIPKE or not n.get("vklop") or not ima_potrdilo():
        return False
    naslov = n.get("naslov", "")
    try:
        _zahteva(naslov, "sendAppController", {"key_pressed": TIPKE[vhod]})
        return True
    except Exception:
        # DHCP je lahko dal vrstici nov naslov: poiscemo jo znova (po imenu) in poskusimo enkrat.
        for v in najdi():
            if v["ime"] == n.get("ime") and v["naslov"] != naslov:
                n["naslov"] = v["naslov"]
                _shrani(n)
                try:
                    _zahteva(v["naslov"], "sendAppController", {"key_pressed": TIPKE[vhod]})
                    return True
                except Exception:
                    return False
        return False
