"""Omrezje za Safeer OS na Linuxu: Wi-Fi in zicne povezave prek NetworkManagerja (nmcli).

Namesto Mintovega okna »Omrezne povezave« pokaze Safeer OS svojo stran: dosegljiva Wi-Fi omrezja,
povezavo z geslom, trenutno povezavo, vklop in izklop Wi-Fi ter shranjene povezave. Za posebne
nastavitve (IP, DNS, VPN) ostane Mintovo orodje pod »Napredno«.

Vse gre skozi nmcli s fiksnimi argumenti; ime omrezja in geslo sta vedno en argument, nikoli lupina.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import List, Optional, Tuple

from core.os_sistem import _razdeli

CAS = 20.0


def _nmcli(argumenti: List[str], cas: float = 6.0) -> Tuple[int, str, str]:
    if shutil.which("nmcli") is None:
        return 127, "", "nmcli ni namescen"
    try:
        r = subprocess.run(["nmcli"] + argumenti, capture_output=True, text=True, timeout=cas)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "cas je potekel"
    except Exception as e:  # noqa: BLE001
        return 1, "", str(e)


def naprave() -> List[dict]:
    """Omrezne naprave (samo ethernet in wifi): vrsta, stanje, povezava, ime naprave."""
    koda, izpis, _ = _nmcli(["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"])
    izhod = []
    if koda != 0:
        return izhod
    for vrstica in izpis.splitlines():
        d = _razdeli(vrstica)
        if len(d) >= 4 and d[1] in ("ethernet", "wifi"):
            if d[2] == "unmanaged":
                continue
            izhod.append({"naprava": d[0], "vrsta": d[1], "stanje": d[2], "povezava": d[3]})
    return izhod


def wifi_vklopljen() -> bool:
    koda, izpis, _ = _nmcli(["radio", "wifi"])
    return koda == 0 and izpis.strip() == "enabled"


def omrezja(osvezi: bool = False) -> List[dict]:
    """Dosegljiva Wi-Fi omrezja, najmocnejsa najprej; isto ime samo enkrat (najmocnejsi oddajnik)."""
    koda, izpis, _ = _nmcli(["-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
                             "--rescan", "yes" if osvezi else "auto"], cas=CAS)
    if koda != 0:
        return []
    najboljsa = {}
    for vrstica in izpis.splitlines():
        d = _razdeli(vrstica)
        if len(d) < 4 or not d[1]:
            continue
        try:
            signal = int(d[2])
        except ValueError:
            signal = 0
        o = {"ime": d[1], "signal": signal, "zasciteno": bool(d[3].strip() and d[3].strip() != "--"),
             "povezano": d[0].strip() == "*", "varnost": d[3].strip()}
        prej = najboljsa.get(o["ime"])
        if prej is None or o["povezano"] or (not prej["povezano"] and o["signal"] > prej["signal"]):
            najboljsa[o["ime"]] = o
    shranjene = {p["ime"] for p in shranjene_povezave() if p["vrsta"] == "wifi"}
    for o in najboljsa.values():
        o["shranjeno"] = o["ime"] in shranjene
    return sorted(najboljsa.values(), key=lambda o: (not o["povezano"], -o["signal"], o["ime"].lower()))


def shranjene_povezave() -> List[dict]:
    koda, izpis, _ = _nmcli(["-t", "-f", "NAME,TYPE,DEVICE,ACTIVE", "connection", "show"])
    izhod = []
    if koda != 0:
        return izhod
    for vrstica in izpis.splitlines():
        d = _razdeli(vrstica)
        if len(d) < 4:
            continue
        vrsta = {"802-11-wireless": "wifi", "802-3-ethernet": "ethernet"}.get(d[1])
        if vrsta is None:
            continue           # most, docker, vpn ... ostanejo v »Napredno«
        izhod.append({"ime": d[0], "vrsta": vrsta, "naprava": d[2], "aktivna": d[3] == "yes"})
    return izhod


def stanje(osvezi: bool = False) -> dict:
    return {"naprave": naprave(), "wifi_vklopljen": wifi_vklopljen(),
            "omrezja": omrezja(osvezi) if any(n["vrsta"] == "wifi" for n in naprave()) else [],
            "shranjene": shranjene_povezave(), "napredno": shutil.which("nm-connection-editor") is not None}


def _napaka(stderr: str) -> str:
    s = (stderr or "").lower()
    if "secrets were required" in s or "password" in s or "802-1x" in s or "psk" in s:
        return "geslo"
    if "no network with ssid" in s:
        return "ni_omrezja"
    if "timeout" in s or "cas je potekel" in s:
        return "cas"
    return "napaka"


def povezi(ime: str, geslo: str = "") -> dict:
    """Poveze se z Wi-Fi omrezjem (shranjeno ali novo z geslom)."""
    ime = str(ime or "")[:64]
    if not ime:
        return {"ok": False, "napaka": "ni_omrezja"}
    argumenti = ["device", "wifi", "connect", ime]
    if geslo:
        argumenti += ["password", str(geslo)[:128]]
    koda, _, napaka = _nmcli(argumenti, cas=45.0)
    return {"ok": koda == 0, "napaka": "" if koda == 0 else _napaka(napaka)}


def odklopi(ime: str) -> bool:
    koda, _, _ = _nmcli(["connection", "down", "id", str(ime or "")[:64]])
    return koda == 0


def aktiviraj(ime: str) -> bool:
    koda, _, _ = _nmcli(["connection", "up", "id", str(ime or "")[:64]], cas=45.0)
    return koda == 0


def pozabi(ime: str) -> bool:
    """Izbrise shranjeno povezavo (samo wifi/ethernet s seznama; ime je en argument)."""
    ime = str(ime or "")[:64]
    if ime not in {p["ime"] for p in shranjene_povezave()}:
        return False
    koda, _, _ = _nmcli(["connection", "delete", "id", ime])
    return koda == 0
