"""Prikaz oddaljenega zaslona na Windows: velikost slike v fizicnih pikah, kazalec, vrstica s podatki, omrezje.

Lastnik, 25. 10. 2026 (09:01-09:13): pri gledanju Linux prenosnika z Windows je bilo besedilo neostro in kazalca sta
bila dva; isti zaslon na telefonu je bil ostrejsi. Vzrok na strani gledalca (izmerjeno na testnem PC 1440x900 pri
100 %): slika 1920x1080 se je v okno risala pomanjsana z najblizjim sosedom (QPainter brez glajenja) - vsak cetrti
stolpec in vrstica sta izpadla (PSNR 29 dB proti 44 dB z Lanczosom) -, v zahtevi seje pa ni bilo ne velikosti
platna ne omrezja (Android televizor posilje view, net, caps, codecs).

Pravila (ciste funkcije, preizkusi v windows/tests/test_oddaljeni_zaslon_ostrina.py):
- vse mere so v FIZICNIH pikah platna (logicne tocke Qt x devicePixelRatio): pri 125 / 150 % ni bitnega raztega;
- slika, ki gre v platno, se pokaze 1:1 (pika izvora = pika zaslona); vecja se pomanjsa kakovostno (Lanczos v
  swscale, ne v risanju), nikoli ne poveca; nacin »1:1« pokaze izvorne pike in sliko premika za misko;
- izvoru povemo velikost platna in gostoto (view), omrezje (net) in kaj znamo (caps): loceni zaslon naredi natanko
  te velikosti, da pomanjsevanja sploh ni;
- en kazalec: dokler izvor kazalec rise v sliko (Linux), je lokalni nad sliko skrit; ko izvor poslje obliko
  kazalca (Windows od 1.0.49), slike kazalca ni in lokalni kazalec dobi to obliko.
"""

from __future__ import annotations

import ctypes
import ipaddress
import math
import socket
import struct
import sys
from typing import Dict, Optional, Sequence, Tuple

#: Kar gledalec Windows zna (screen.start »caps«): ping v toku (meritve zamika, core/link_zaslon_meritve.py) in
#: dolga skupina slik (kljucne slike vsako sekundo ne potrebuje - dekodira vse enote).
ZMOZNOSTI = ("rtt", "gop")
#: Kodeki, ki jih dekoder gledalca (PyAV) zna; izvor izbere prvega, ki ga zmore.
KODEKI = ("h264",)
#: Vrsta naprave v »view« (izvor po njej izbere merilo locenega zaslona; televizor ostane pri 1).
VRSTA_POGLEDA = "racunalnik"
#: Vrstica nad sliko je visoka toliko logicnih tock: veckratnik 4, da je platno pri 125, 150, 175 in 200 % na celi
#: fizicni piki (pol pike odmika bi sestavljalnik Windows sliko zgladil - spet neostro).
VISINA_VRSTICE = 36
#: Pomanjsevanje v swscale (izmerjeno 25. 10. 2026 na besedilu 1920x1080 -> 1413x795, PSNR proti idealnemu
#: Lanczosu izvirnika: najblizji sosed 29,4 dB, bilinearno 36,4, AREA 37,5, bikubicno 42,1, Lanczos 44,5 dB).
POMANJSEVANJE = "LANCZOS"

#: Oblike kazalca izvora (zajem_zaslona._OBLIKE_KAZALCA na Windows) -> ime Qt.CursorShape.
OBLIKE_KAZALCA = {
    "puscica": "ArrowCursor", "besedilo": "IBeamCursor", "cakanje": "WaitCursor", "kriz": "CrossCursor",
    "velikost_nwse": "SizeFDiagCursor", "velikost_nesw": "SizeBDiagCursor", "velikost_we": "SizeHorCursor",
    "velikost_ns": "SizeVerCursor", "premik": "SizeAllCursor", "roka": "PointingHandCursor",
    "puscica_cakanje": "BusyCursor", "ne": "ForbiddenCursor",
}

BESEDILA = {
    "sl": {"lan": "LAN", "internet": "internet", "neposredno": "neposredno", "posrednik": "prek posrednika",
           "pomanjsano": "pomanjšano na {w}×{h}", "zamik": "zamik {ms} ms", "en_na_en": "1:1",
           "prilagodi": "Prilagodi", "en_na_en_namig": "Izvorne pike 1:1 (slika sledi miški)",
           "prilagodi_namig": "Cela slika v oknu", "kabel": "kabel", "wifi": "Wi-Fi"},
    "en": {"lan": "LAN", "internet": "internet", "neposredno": "direct", "posrednik": "via relay",
           "pomanjsano": "scaled to {w}×{h}", "zamik": "latency {ms} ms", "en_na_en": "1:1",
           "prilagodi": "Fit", "en_na_en_namig": "Native pixels 1:1 (the image follows the mouse)",
           "prilagodi_namig": "Whole image in the window", "kabel": "cable", "wifi": "Wi-Fi"},
    "de": {"lan": "LAN", "internet": "Internet", "neposredno": "direkt", "posrednik": "über Relay",
           "pomanjsano": "verkleinert auf {w}×{h}", "zamik": "Latenz {ms} ms", "en_na_en": "1:1",
           "prilagodi": "Einpassen", "en_na_en_namig": "Originalpixel 1:1 (das Bild folgt der Maus)",
           "prilagodi_namig": "Ganzes Bild im Fenster", "kabel": "Kabel", "wifi": "WLAN"},
    "es": {"lan": "LAN", "internet": "internet", "neposredno": "directa", "posrednik": "mediante relé",
           "pomanjsano": "reducido a {w}×{h}", "zamik": "latencia {ms} ms", "en_na_en": "1:1",
           "prilagodi": "Ajustar", "en_na_en_namig": "Píxeles originales 1:1 (la imagen sigue al ratón)",
           "prilagodi_namig": "Imagen completa en la ventana", "kabel": "cable", "wifi": "Wi-Fi"},
    "fr": {"lan": "LAN", "internet": "internet", "neposredno": "directe", "posrednik": "via relais",
           "pomanjsano": "réduit à {w}×{h}", "zamik": "latence {ms} ms", "en_na_en": "1:1",
           "prilagodi": "Ajuster", "en_na_en_namig": "Pixels d’origine 1:1 (l’image suit la souris)",
           "prilagodi_namig": "Image entière dans la fenêtre", "kabel": "câble", "wifi": "Wi-Fi"},
    "it": {"lan": "LAN", "internet": "internet", "neposredno": "diretta", "posrednik": "tramite relay",
           "pomanjsano": "ridotto a {w}×{h}", "zamik": "latenza {ms} ms", "en_na_en": "1:1",
           "prilagodi": "Adatta", "en_na_en_namig": "Pixel originali 1:1 (l’immagine segue il mouse)",
           "prilagodi_namig": "Immagine intera nella finestra", "kabel": "cavo", "wifi": "Wi-Fi"},
}


def besedilo(jezik: str, kljuc: str, **zamenjave) -> str:
    b = BESEDILA.get(jezik, BESEDILA["en"]).get(kljuc) or BESEDILA["en"].get(kljuc, kljuc)
    for k, v in zamenjave.items():
        b = b.replace("{" + k + "}", str(v))
    return b


# ------------------------------------------------------------------ velikost in polozaj slike (fizicne pike)
def fizicno(logicno: float, dpr: float) -> int:
    """Logicne tocke Qt -> cele fizicne pike (Qt pri delnem merilu zaokrozi enako)."""
    return int(round(float(logicno) * float(dpr or 1.0)))


def velikost_slike(izvor: Tuple[int, int], platno: Tuple[int, int], nacin: str = "prilagodi") -> Tuple[int, int]:
    """V kateri velikosti (fizicne pike) naj dekoder pripravi sliko: izvorna, ce gre v platno ali je nacin »1:1«,
    sicer pomanjsana z istim razmerjem (nikoli povecana - povecava zmehca, pike platna so takrat pac crne)."""
    iw, ih = max(1, int(izvor[0])), max(1, int(izvor[1]))
    pw, ph = max(1, int(platno[0])), max(1, int(platno[1]))
    if nacin == "1:1" or (iw <= pw and ih <= ph):
        return iw, ih
    f = min(pw / iw, ph / ih)
    return max(2, int(math.floor(iw * f))), max(2, int(math.floor(ih * f)))


def polozaj_slike(slika: Tuple[int, int], platno: Tuple[int, int], miska: Optional[Tuple[float, float]] = None
                  ) -> Tuple[int, int]:
    """Levi zgornji kot slike v platnu (cele fizicne pike). Manjsa slika je na sredini; vecja (1:1) se premika za
    misko: miska na levem robu platna pokaze levi rob slike, na desnem desni."""
    izid = []
    for i in (0, 1):
        s, p = int(slika[i]), int(platno[i])
        if s <= p:
            izid.append((p - s) // 2)
        else:
            delez = 0.5 if miska is None else min(1.0, max(0.0, float(miska[i]) / max(1, p - 1)))
            izid.append(-int(round((s - p) * delez)))
    return izid[0], izid[1]


def v_izvor(tocka: Tuple[float, float], kot: Tuple[int, int], slika: Tuple[int, int],
            izvor: Tuple[int, int]) -> Optional[Tuple[int, int]]:
    """Fizicna tocka platna -> tocka izvora (pike izvora) ali None zunaj slike."""
    x, y = float(tocka[0]) - kot[0], float(tocka[1]) - kot[1]
    if x < 0 or y < 0 or x >= slika[0] or y >= slika[1]:
        return None
    return (min(izvor[0] - 1, int(x * izvor[0] / slika[0])), min(izvor[1] - 1, int(y * izvor[1] / slika[1])))


def pogled_za_izvor(platno: Tuple[int, int], dpr: float) -> dict:
    """»view« za screen.start (kot Android ZaslonActivity.pogledZaRacunalnik): velikost platna v fizicnih pikah in
    gostota; izvor naredi loceni zaslon natanko te velikosti (1:1, brez pomanjsevanja) in pri 125 / 150 % povecavi
    Windows nastavi isto merilo (scale), da so pisava in gumbi enako veliki kot na tem racunalniku."""
    dpr = float(dpr or 1.0)
    return {"w": int(platno[0]) // 2 * 2, "h": int(platno[1]) // 2 * 2,
            # gostota kot na Androidu (1,0 = 160 dpi); Windows 100 % = 96 dpi
            "density": round(dpr * 96.0 / 160.0, 3), "dpi": int(round(96 * dpr)), "scale": round(dpr, 3),
            "touch": False, "kind": VRSTA_POGLEDA}


def zahteva_seje(kakovost: str, zaslon: str, platno: Tuple[int, int], dpr: float, omrezje: str = "",
                 predano: bool = False) -> dict:
    """Parametri screen.start gledalca Windows (starejsi izvor neznana polja prezre): osnova iz
    oddaljeni_zaslon_protokol.parametri_zacetka (zaslon, handoff) + platno, kodeki, omrezje in ping."""
    from .oddaljeni_zaslon_protokol import parametri_zacetka
    z = parametri_zacetka(zaslon, predano)
    z["quality"] = kakovost
    z["caps"] = list(dict.fromkeys(list(z.get("caps") or []) + list(ZMOZNOSTI)))
    z["view"] = pogled_za_izvor(platno, dpr)
    z["codecs"] = list(KODEKI)
    if omrezje:
        z["net"] = omrezje
    return z


# ------------------------------------------------------------------ kazalec
def oblika_kazalca(obvestilo: dict) -> Optional[str]:
    """Ime Qt.CursorShape iz obvestila izvora {"kazalec": [x, y], "oblika": ..., "viden": ...} ali None, ce
    obvestilo ni o kazalcu. Neviden kazalec -> »BlankCursor«, neznana oblika -> puscica."""
    if not isinstance(obvestilo, dict) or "oblika" not in obvestilo:
        return None
    if obvestilo.get("viden") is False:
        return "BlankCursor"
    return OBLIKE_KAZALCA.get(str(obvestilo.get("oblika") or ""), "ArrowCursor")


# ------------------------------------------------------------------ vrstica s podatki
def je_lan(naslov: str) -> bool:
    try:
        ip = ipaddress.ip_address(str(naslov or "").strip("[]").split("%", 1)[0])
    except ValueError:
        return False
    return ip.is_private or ip.is_link_local


def hitrost_povezave(bps: int) -> str:
    """1000000000 -> »1 Gb/s«, 100000000 -> »100 Mb/s«, 2500000000 -> »2,5 Gb/s«."""
    bps = int(bps or 0)
    if bps <= 0:
        return ""
    if bps >= 1_000_000_000:
        g = bps / 1_000_000_000
        return ("%d" % g if abs(g - round(g)) < 0.05 else ("%.1f" % g).replace(".", ",")) + " Gb/s"
    return "%d Mb/s" % int(round(bps / 1_000_000))


def vrstica_podatkov(jezik: str, naslov: str, prek_posrednika: bool, omrezje: Dict, izvor: Tuple[int, int],
                     slika: Tuple[int, int], fps: float, mbps: float = 0.0, zamik_ms: Optional[float] = None,
                     nacin: str = "prilagodi") -> str:
    """»LAN · kabel 1 Gb/s · neposredno · 1920×1080 · 60 fps« (+ pomanjsano / 1:1, Mb/s, zamik)."""
    deli = [besedilo(jezik, "lan") if je_lan(naslov) else besedilo(jezik, "internet")]
    hitrost = hitrost_povezave(int((omrezje or {}).get("hitrost_bps") or 0))
    vrsta = (omrezje or {}).get("vrsta") or ""
    medij = besedilo(jezik, "kabel") if vrsta == "ethernet" else besedilo(jezik, "wifi") if vrsta == "wifi" else ""
    if hitrost or medij:
        deli.append(" ".join(x for x in (medij, hitrost) if x))
    deli.append(besedilo(jezik, "posrednik") if prek_posrednika else besedilo(jezik, "neposredno"))
    if izvor[0] and izvor[1]:
        mere = "%d×%d" % (izvor[0], izvor[1])
        if nacin == "1:1" or tuple(slika) == tuple(izvor):
            mere += " 1:1"
        deli.append(mere)
        if nacin != "1:1" and tuple(slika) != tuple(izvor) and slika[0] and slika[1]:
            deli.append(besedilo(jezik, "pomanjsano", w=slika[0], h=slika[1]))
    if fps:
        deli.append("%d fps" % int(round(fps)))
    if mbps:
        deli.append(("%.1f" % mbps).replace(".", ",") + " Mb/s" if mbps < 10 else "%d Mb/s" % int(round(mbps)))
    if zamik_ms is not None:
        deli.append(besedilo(jezik, "zamik", ms=int(round(zamik_ms))))
    return " · ".join(deli)


def percentil(vrednosti: Sequence[float], p: float) -> Optional[float]:
    """p-ti percentil (najblizji rang), kot core/link_zaslon_meritve._percentil."""
    s = sorted(float(v) for v in vrednosti)
    if not s:
        return None
    return s[max(0, min(len(s) - 1, int(math.ceil(p / 100.0 * len(s))) - 1))]


def odmev_rtt(ping: dict, stevci: dict) -> Optional[dict]:
    """Odmev pinga izvora {"rtt": {"n", "t", "z"}} -> {"vrsta": "rtt", "n", "t", ...} (core/link_zaslon_meritve.pong:
    n in t vrnemo nespremenjena, r in b sta ura in bajti gledalca, ostalo nase stanje). None za neveljaven ping."""
    if not isinstance(ping, dict):
        return None
    n = ping.get("n")
    if isinstance(n, bool) or not isinstance(n, (int, float)) or n != int(n):
        return None
    odmev = {"vrsta": "rtt", "n": int(n)}
    if isinstance(ping.get("t"), (int, float)) and not isinstance(ping.get("t"), bool):
        odmev["t"] = ping["t"]
    for k in ("r", "b", "fps", "mbps", "dek", "zastoji", "izpusceno", "pot"):
        if stevci.get(k) is not None:
            odmev[k] = stevci[k]
    return odmev


# ------------------------------------------------------------------ omrezje do naprave (Windows)
class _VrsticaVmesnika(ctypes.Structure):
    """MIB_IF_ROW2 (netioapi.h, 1352 bajtov) do hitrosti povezave; nizi kot UTF-16 (enako na vseh sistemih)."""
    _fields_ = [("InterfaceLuid", ctypes.c_uint64), ("InterfaceIndex", ctypes.c_uint32),
                ("InterfaceGuid", ctypes.c_ubyte * 16), ("Alias", ctypes.c_uint16 * 257),
                ("Description", ctypes.c_uint16 * 257), ("PhysicalAddressLength", ctypes.c_uint32),
                ("PhysicalAddress", ctypes.c_ubyte * 32), ("PermanentPhysicalAddress", ctypes.c_ubyte * 32),
                ("Mtu", ctypes.c_uint32), ("Type", ctypes.c_uint32), ("TunnelType", ctypes.c_int32),
                ("MediaType", ctypes.c_int32), ("PhysicalMediumType", ctypes.c_int32), ("AccessType", ctypes.c_int32),
                ("DirectionType", ctypes.c_int32), ("Zastavice", ctypes.c_ubyte), ("OperStatus", ctypes.c_int32),
                ("AdminStatus", ctypes.c_int32), ("MediaConnectState", ctypes.c_int32),
                ("NetworkGuid", ctypes.c_ubyte * 16), ("ConnectionType", ctypes.c_int32),
                ("TransmitLinkSpeed", ctypes.c_uint64), ("ReceiveLinkSpeed", ctypes.c_uint64),
                ("Stevci", ctypes.c_uint64 * 18)]


#: IF_TYPE / NDIS_PHYSICAL_MEDIUM -> vrsta omrezja za izvor (»net«, kot Android OmrezjeNaprave.vrsta).
_IF_ETHERNET, _IF_WIFI = 6, 71
_MEDIJ_802_3, _MEDIJ_802_11 = 14, 9


def vrsta_vmesnika(tip: int, medij: int) -> str:
    if tip == _IF_WIFI or medij == _MEDIJ_802_11:
        return "wifi"
    if tip == _IF_ETHERNET or medij == _MEDIJ_802_3:
        return "ethernet"
    return ""


def gostitelj(naslov: str) -> str:
    """»https://<ip>:8990/pot«, »<ip>:8990« ali »<ip>« -> »<ip>« (IPv6 brez oklepajev)."""
    n = str(naslov or "").strip()
    if "://" in n:
        import urllib.parse
        return urllib.parse.urlsplit(n).hostname or ""
    if n.startswith("["):
        return n[1:].split("]", 1)[0]
    return n.rsplit(":", 1)[0] if n.count(":") == 1 else n


def omrezje_do(naslov: str) -> dict:
    """{"vrsta": "ethernet"/"wifi"/"", "hitrost_bps": ...} vmesnika, po katerem gre promet do `naslov` (IPv4,
    GetBestInterface + GetIfEntry2). Drugje kot na Windows ali ob napaki {}."""
    if sys.platform != "win32":
        return {}
    try:
        ip = gostitelj(naslov)
        socket.inet_aton(ip)                     # samo naslov IPv4, brez poizvedbe DNS
        iph = ctypes.windll.iphlpapi
        indeks = ctypes.c_uint32(0)
        if iph.GetBestInterface(ctypes.c_uint32(struct.unpack("<I", socket.inet_aton(ip))[0]), ctypes.byref(indeks)):
            return {}
        vrstica = _VrsticaVmesnika()
        vrstica.InterfaceIndex = indeks.value
        if iph.GetIfEntry2(ctypes.byref(vrstica)):
            return {}
        return {"vrsta": vrsta_vmesnika(int(vrstica.Type), int(vrstica.PhysicalMediumType)),
                "hitrost_bps": int(vrstica.ReceiveLinkSpeed or vrstica.TransmitLinkSpeed or 0)}
    except Exception:  # noqa: BLE001 - podatek je le za vrstico in izbiro kakovosti
        return {}


def zavedanje_dpi() -> str:
    """Kako proces vidi DPI (za dnevnik): »per-monitor-v2«, »per-monitor«, »sistem«, »ne« ali »?«."""
    if sys.platform != "win32":
        return "?"
    try:
        u = ctypes.windll.user32
        u.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        u.AreDpiAwarenessContextsEqual.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        u.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        kontekst = ctypes.c_void_p(u.GetThreadDpiAwarenessContext())
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = (HANDLE)-4
        if u.AreDpiAwarenessContextsEqual(kontekst, ctypes.c_void_p(ctypes.c_size_t(-4).value)):
            return "per-monitor-v2"
        return {0: "ne", 1: "sistem", 2: "per-monitor"}.get(int(u.GetAwarenessFromDpiAwarenessContext(kontekst)), "?")
    except Exception:  # noqa: BLE001
        return "?"
