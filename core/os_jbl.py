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

Potrdilo in kljuc JBL One nista skrivnost tega racunalnika: sta javna (v repozitoriju JBL_Soundbar), zato ne dokazujeta,
da ukaz posilja Safeer. Ob vklopu si zapomnimo odtis SHA-256 potrdila vrstice (prvi stik) in ukaz poslje samo napravi z
istim odtisom - preverjeno PRED posiljanjem ukaza (drugi neodvisni pregled, 19. 10. 2026). To ustavi lazno vrstico v
domacem omrezju (npr. ob novem naslovu DHCP); nikogar v omrezju, ki ima isti javni kljuc, pa ne ustavi pri posiljanju
ukazov vrstici sami.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import os
import re
import shutil
import ssl
import subprocess
import urllib.parse
import urllib.request

from core import https_prenos
from typing import List, Optional

VIR = ("https://raw.githubusercontent.com/MrBearPresident/JBL_Soundbar/"
       "9976c48755ad9d6725e281396c977a813cb9153b/custom_components/jbl_integration/")
ODTISI = {
    "Cert.pem": "1f85e91cc6af33a2042a0bc27dae95c6b37492d1e1e384e45a00bbb8789d1c55",
    "Key.pem": "b072d78a8b259360b679478b8bf75ee4765ce7762f5f06574bff4d1e9e450099",
}
TIPKE = {"tv": "source-tv", "bluetooth": "bluetooth"}
#: Vrata HTTPS vrstice (preizkusi jih zamenjajo).
VRATA = 443


class NapakaOdtisa(ValueError):
    """Naprava na naslovu vrstice ima drugo potrdilo, kot si ga je Safeer zapomnil ob vklopu - ukaz ni bil poslan."""


def mapa() -> str:
    return os.path.join((os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")), "safeer-os", "jbl")


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


def prenesi_potrdilo(odpri=https_prenos.odpri) -> bool:
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
    # Vrstica ima samopodpisano potrdilo brez imena: CA ga ne more potrditi. Zaupanje je odtis potrdila, ki ga _zahteva
    # preveri pred posiljanjem ukaza (zapomnjen ob vklopu).
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.load_cert_chain(os.path.join(mapa(), "Cert.pem"), os.path.join(mapa(), "Key.pem"))
    return ctx


def _zahteva(naslov: str, ukaz: str, payload: Optional[dict] = None, cas: float = 5.0,
             odtis: Optional[str] = None) -> tuple:
    """(odgovor, odtis potrdila naprave). Ce je `odtis` podan, gre ukaz samo napravi s tem odtisom (sicer NapakaOdtisa,
    brez posiljanja); brez njega (prvi stik ob vklopu) vrne odtis, ki si ga klicatelj zapomni."""
    if not re.fullmatch(r"[0-9a-fA-F:.]{3,45}", naslov or ""):
        raise ValueError("neveljaven naslov")
    povezava = http.client.HTTPSConnection(naslov, VRATA, timeout=cas, context=_kontekst())
    try:
        povezava.connect()
        der = povezava.sock.getpeercert(binary_form=True) or b""
        if not der:
            raise NapakaOdtisa("naprava ni poslala potrdila")
        dejanski = hashlib.sha256(der).hexdigest()
        if odtis is not None and not hmac.compare_digest(dejanski, str(odtis)):
            raise NapakaOdtisa("potrdilo naprave se ne ujema z zapomnjenim")
        if payload is None:
            povezava.request("GET", "/httpapi.asp?command=" + urllib.parse.quote(ukaz))
        else:
            telo = "command=%s&payload=%s" % (ukaz, json.dumps(payload, separators=(",", ":")))
            povezava.request("POST", "/httpapi.asp", body=telo.encode("utf-8"),
                             headers={"Content-Type": "application/x-www-form-urlencoded"})
        odgovor = povezava.getresponse()
        if odgovor.status >= 400:
            raise OSError("vrstica je odgovorila %d" % odgovor.status)
        return odgovor.read(4096).decode("utf-8", "replace"), dejanski
    finally:
        povezava.close()


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


def bt_naslov(naslov: str) -> tuple:
    """(naslov Bluetooth vrstice, odtis njenega potrdila) iz getStatusEx - po prvem prepoznamo izhod racunalnika,
    drugega si zapomnimo za vse nadaljnje ukaze. Brez odgovora ("", "")."""
    try:
        besedilo, odtis = _zahteva(naslov, "getStatusEx")
        m = re.search(r'"BT_MAC"\s*:\s*"([0-9A-Fa-f:]{17})"', besedilo)
        return (m.group(1).upper(), odtis) if m else ("", "")
    except Exception:
        return "", ""


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
    bt, odtis = bt_naslov(v["naslov"])
    if not bt:
        return dict(stanje(), napaka="ne_odgovori")
    n.update({"vklop": True, "ime": v["ime"], "naslov": v["naslov"], "bt": bt, "odtis": odtis})
    n.pop("napaka", None)
    _shrani(n)
    return stanje()


def stanje(isci: bool = False) -> dict:
    n = nastavitve()
    izid = {"vklop": bool(n.get("vklop")) and ima_potrdilo(), "ime": n.get("ime", ""), "bt": n.get("bt", "")}
    if izid["vklop"] and n.get("napaka") == "odtis":
        izid["napaka"] = "odtis"        # vrstica ima novo potrdilo: uporabnik jo poveze znova (izklop in vklop)
    if isci and not izid["vklop"]:
        vrstice = najdi(3.0)
        if vrstice:
            izid["ime"] = izid["ime"] or vrstice[0]["ime"]
            izid["najdena"] = True
    else:
        izid["najdena"] = bool(n.get("naslov"))
    return izid


def _mac_izhoda(ime_izhoda: str) -> str:
    """bluez_output.00_1B_44_11_3A_C5.1 -> 00:1B:44:11:3A:C5"""
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
    odtis = str(n.get("odtis") or "") or None
    if odtis is None:
        # Vklop pred 1.0.128 si odtisa ni zapomnil. Ukaz ne gre nobeni napravi pred preverjenim odtisom (AGENTS.md: TLS
        # brez CA samo s pripetim odtisom PRED posiljanjem): najprej prvi stik brez ukaza kot ob vklopu (getStatusEx),
        # naprava mora imeti zapomnjeni naslov Bluetooth; njen odtis si zapomnimo, ukaz gre nato s pripetim odtisom.
        # Prej je ukaz sel nepreverjen - ob spremembi naslova (DHCP) celo prvi napravi z istim imenom v mDNS.
        kandidati = [naslov] + [v["naslov"] for v in najdi() if v["ime"] == n.get("ime") and v["naslov"] != naslov]
        for na in kandidati:
            bt, prvi = bt_naslov(na) if na else ("", "")
            if bt and prvi and bt == str(n.get("bt") or ""):
                odtis, naslov = prvi, na
                n.update({"odtis": prvi, "naslov": na})
                n.pop("napaka", None)
                _shrani(n)
                break
        else:
            return False

    tuje_potrdilo = []

    def poslji(na: str) -> bool:
        try:
            _besedilo, dejanski = _zahteva(na, "sendAppController", {"key_pressed": TIPKE[vhod]}, odtis=odtis)
        except NapakaOdtisa:
            tuje_potrdilo.append(na)
            raise
        if n.get("napaka"):
            n.pop("napaka", None)
            _shrani(n)
        return True

    try:
        return poslji(naslov)
    except Exception:        # tudi NapakaOdtisa: na naslovu je druga naprava (DHCP) - pravo vrstico poiscemo spodaj
        pass
    # DHCP je lahko dal vrstici nov naslov: poiscemo jo znova (po imenu) in poskusimo enkrat - ukaz gre samo, ce ima
    # naprava na novem naslovu zapomnjeni odtis.
    for v in najdi():
        if v["ime"] == n.get("ime") and v["naslov"] != naslov:
            try:
                poslji(v["naslov"])
            except Exception:
                break
            n["naslov"] = v["naslov"]
            _shrani(n)
            return True
    if tuje_potrdilo and n.get("napaka") != "odtis":
        # Vrstica (ali naprava na njenem naslovu) ima drugo potrdilo: ukaza nismo poslali. Nastavitve to pokazejo,
        # sicer bi preklop tiho nehal delovati (neodvisni pregled, 19. 10. 2026).
        n["napaka"] = "odtis"
        _shrani(n)
    return False
