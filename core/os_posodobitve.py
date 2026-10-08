"""Posodobitve Safeer OS s safeer.si (os/razlicice.json) - skupno Linuxu in Windows.

Aplikacija sama pove, da je na voljo nova razlicica, in jo na zeljo uporabnika prenese ter preda namescanju. Seznam
razlicic je podpisan (Ed25519, razlicice.json.sig z istega gostitelja) in brez veljavnega podpisa se zavrne; paket se
preveri s SHA-256 iz podpisanega seznama (obvezen); vse gre samo prek https. Namescanje: Linux .deb prek `pkexec apt-get install` (polkit vprasa za geslo), Flatpak prek `flatpak install --user`,
AppImage zamenja sam sebe; Windows zazene nov SafeerOS-Windows-<ver>.exe (zaganjalnik razpakira novo razlicico).
Nic se ne namesti brez uporabnika; preverba je tiha (najvec na 6 ur) in brez posledic, ce omrezja ni.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

from .signed_feed import _signature_ok

MANIFEST = os.environ.get("SAFEER_MANIFEST_URL") or "https://safeer.si/os/razlicice.json"   # okoljska spremenljivka za preizkuse
STRAN = "https://safeer.si/os/"
PREVERBA_S = 6 * 3600
IMENA = {"safeer-os": "Safeer OS", "safeer-control": "Safeer Control", "safeer-browser": "Safeer Browser"}
# Javni kljuci Ed25519 za podpis razlicice.json (zasebni kljuc je samo na racunalniku, ki gradi stran safeer.si).
# Kontekst loci ta podpis od podpisov seznamov grozenj (core/signed_feed.py), tudi ce bi bil kljuc isti.
KLJUCI: Dict[str, str] = {"safeer-razlicice-2026-10": "yx7oxoDdoscufSxSOLf9JuDo0uIajPsUNmUjJEqUVjE="}
KONTEKST = b"safeer-razlicice-v1\n"
NAJVEC_SEZNAM = 256 * 1024
NAJVEC_PODPIS = 8 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CAS = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")   # RFC3339 UTC (kot core/signed_feed)
# Samo preizkusi: navaden http do tega racunalnika (127.0.0.1, localhost, ::1). V izdaji vedno False - samo https.
_LOKALNI_HTTP = False


class NapakaPodpisa(ValueError):
    """Seznam razlicic ni podpisan s kljucem, ki mu zaupamo (manjka, ni berljiv ali ni veljaven)."""


class NapakaSvezine(ValueError):
    """Seznam razlicic je pretekel ali starejsi od ze videnega (zascita pred vracanjem na staro razlicico)."""


def dovoljen_naslov(url: str) -> bool:
    """https z gostiteljem; nikoli file:, ftp:, data: ali navaden http (preizkusi: http samo do tega racunalnika)."""
    try:
        d = urlsplit(str(url))
        gostitelj = d.hostname or ""
    except ValueError:
        return False
    if d.scheme == "https" and gostitelj:
        return True
    return _LOKALNI_HTTP and d.scheme == "http" and gostitelj in ("127.0.0.1", "localhost", "::1")


def veljavna_datoteka(d) -> bool:
    """Vnos paketa, ki ga program sme prenesti in namestiti: dovoljen naslov in 64-mestni SHA-256."""
    return (isinstance(d, dict) and isinstance(d.get("url"), str) and dovoljen_naslov(d["url"])
            and isinstance(d.get("sha256"), str) and _SHA256.fullmatch(d["sha256"].lower()) is not None)


class _Preusmeritve(urllib.request.HTTPRedirectHandler):
    """Preusmeritev samo na dovoljen naslov; ce je podan gostitelj (seznam razlicic), samo nanj."""

    def __init__(self, gostitelj: str = "") -> None:
        super().__init__()
        self.gostitelj = gostitelj

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not dovoljen_naslov(newurl) or (self.gostitelj and (urlsplit(newurl).hostname or "") != self.gostitelj):
            raise urllib.error.HTTPError(req.full_url, code, "preusmeritev drugam ni dovoljena", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _odpri(url: str, glave: dict, cas: float, isti_gostitelj: bool = False):
    if not dovoljen_naslov(url):
        raise ValueError("naslov posodobitve ni varen (samo https)")
    gostitelj = (urlsplit(url).hostname or "") if isti_gostitelj else ""
    return urllib.request.build_opener(_Preusmeritve(gostitelj)).open(urllib.request.Request(url, headers=glave), timeout=cas)


def _beri(url: str, cas: float, agent: str, meja: int) -> tuple:
    """(bajti, koncni naslov po preusmeritvah - vedno na istem gostitelju)."""
    with _odpri(url, {"User-Agent": agent, "Cache-Control": "no-cache"}, cas, isti_gostitelj=True) as o:
        podatki = o.read(meja + 1)
        koncni = o.geturl() or url
    if len(podatki) > meja:
        raise ValueError("seznam različic je prevelik")
    return podatki, koncni


def _naslov_podpisa(url: str) -> str:
    d = urlsplit(url)
    return urlunsplit((d.scheme, d.netloc, d.path + ".sig", d.query, ""))


def preveri_podpis(podatki: bytes, podpis: bytes, kljuci: Optional[Dict[str, str]] = None) -> None:
    """Vrze NapakaPodpisa, ce `podatki` (natanko bajti razlicice.json) ni podpisal kljuc, ki mu zaupamo.

    `podpis` je JSON seznam [{"alg": "ed25519", "key_id": ..., "sig": base64}] - ob menjavi kljuca podpiseta oba.
    """
    try:
        vnosi = json.loads(podpis.decode("ascii"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise NapakaPodpisa("podpis seznama različic ni berljiv") from None
    zaupani = KLJUCI if kljuci is None else kljuci
    if not isinstance(vnosi, list) or not any(_signature_ok(v, zaupani, KONTEKST, podatki) for v in vnosi[:8]):
        raise NapakaPodpisa("podpis seznama različic ni veljaven")


def _stevilke(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", str(v or ""))[:4]) or (0,)


def novejsa(nova: str, nasa: str) -> bool:
    """Ali je razlicica `nova` ("0.4.23") novejsa od `nasa` ("0.4.22")."""
    return _stevilke(nova) > _stevilke(nasa)


def _privzeta_stanje_pot() -> str:
    """Datoteka z najvisjo ze videno izdajo seznama (anti-rollback). Okoljska spremenljivka jo prepise (preizkusi)."""
    p = os.environ.get("SAFEER_POSODOBITVE_STANJE")
    if p:
        return p
    baza = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(baza, "safeer-os", "posodobitve.json")


def _zadnje_izdano(pot: str) -> str:
    """Najvisja ze videna vrednost 'izdano' (RFC3339) ali prazen niz (ni datoteke ali ni berljiva)."""
    try:
        with open(pot, "r", encoding="ascii") as f:
            v = json.load(f).get("izdano", "")
        return v if isinstance(v, str) else ""
    except (OSError, ValueError):
        return ""


def _shrani_izdano(pot: str, izdano: str) -> None:
    """Atomarno shrani najvisjo videno izdajo; ce ni mogoce, anti-rollback tiho odpove (svezina se velja)."""
    try:
        os.makedirs(os.path.dirname(pot) or ".", exist_ok=True)
        zac = pot + ".del"
        with open(zac, "w", encoding="ascii") as f:
            json.dump({"izdano": izdano}, f)
        os.replace(zac, pot)
    except OSError:
        pass


def _cas(value) -> datetime:
    if not isinstance(value, str) or not _CAS.match(value) or value[:4] < "1970":
        raise NapakaSvezine("cas v seznamu razlicic ni veljaven (RFC3339 Z)")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        raise NapakaSvezine("cas v seznamu razlicic ni veljaven") from None


def preveri_svezino(m: dict, zadnje_videno: str = "", zdaj: Optional[datetime] = None) -> str:
    """Vrne 'izdano' seznama (RFC3339 Z), ce je svez in ne starejsi od ze videnega; sicer vrze NapakaSvezine.

    Napad, ki ga to ustavi: kdor obvlada gostitelja (ne zasebnega kljuca), ponovi pristno PODPISANO staro (ranljivo)
    razlicico. Brez tega bi se namestila kot "novejsa" od nase in preprecila prave posodobitve. 'izdano' in 'potece'
    sta obvezni polji - star seznam brez njiju (ceprav pristno podpisan) se zato zavrne.
    """
    izdano_s = m.get("izdano")
    izdano_t = _cas(izdano_s)
    potece = _cas(m.get("potece"))
    if potece <= izdano_t:
        raise NapakaSvezine("seznam razlicic potece pred izdajo")
    zdaj = zdaj or datetime.now(timezone.utc)
    if zdaj >= potece:
        raise NapakaSvezine("seznam razlicic je pretekel")
    if zadnje_videno:
        try:
            prej = _cas(zadnje_videno)
        except NapakaSvezine:
            prej = None
        if prej is not None and izdano_t < prej:
            raise NapakaSvezine("seznam razlicic je starejsi od ze videnega")
    return izdano_s


def prenesi_manifest(url: str = MANIFEST, cas: float = 8.0, agent: str = "SafeerOS",
                     kljuci: Optional[Dict[str, str]] = None, stanje_pot: Optional[str] = None,
                     zdaj: Optional[datetime] = None) -> dict:
    """Prenese razlicice.json in podpis (razlicice.json.sig) z istega gostitelja; brez veljavnega podpisa vrze izjemo.

    Po podpisu preveri se svezino: 'potece' mora biti v prihodnosti in 'izdano' ne sme biti starejse od ze videnega
    (anti-rollback), da kdor obvlada gostitelja (ne kljuca), ne more ponoviti pristne stare (ranljive) razlicice.
    """
    podatki, koncni = _beri(url, cas, agent, NAJVEC_SEZNAM)
    try:
        podpis, _ = _beri(_naslov_podpisa(koncni), cas, agent, NAJVEC_PODPIS)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NapakaPodpisa("podpis seznama različic manjka") from None
        raise
    preveri_podpis(podatki, podpis, kljuci)
    m = json.loads(podatki.decode("utf-8"))
    if not isinstance(m, dict) or "android" not in m:
        raise ValueError("manifest ni pravi")
    pot = stanje_pot or _privzeta_stanje_pot()
    izdano = preveri_svezino(m, _zadnje_izdano(pot), zdaj)
    _shrani_izdano(pot, izdano)
    return m


def nacin_namestitve() -> str:
    """Kako je Safeer OS namescen na tem racunalniku: deb | flatpak | appimage | windows | neznano."""
    if sys.platform.startswith("win"):
        return "windows"
    if os.environ.get("FLATPAK_ID"):
        return "flatpak"
    if os.environ.get("APPIMAGE"):
        return "appimage"
    if shutil.which("dpkg") and os.path.exists("/var/lib/dpkg/info/safeer-os.list"):
        return "deb"
    return "neznano"


def _vnos_datoteke(paket: dict, nacin: str) -> Optional[dict]:
    """Datoteka za namestitev v programu ali None (nova razlicica brez nje: vmesnik odpre stran)."""
    if nacin == "windows":
        d = {k: paket.get(k) for k in ("url", "sha256", "velikost")}
    else:
        d = paket.get({"deb": "deb", "flatpak": "flatpak", "appimage": "appimage"}.get(nacin, ""))
    return d if veljavna_datoteka(d) else None


def preveri(platforma: str, razlicice: Dict[str, str], manifest: Optional[dict] = None, nacin: Optional[str] = None) -> dict:
    """Primerja nase razlicice ({"safeer-os": "0.4.22", "safeer-control": "2.1.20"}) z manifestom.

    Vrne {"nove": [{"kljuc", "ime", "nasa", "razlicica", "datoteka": {url, sha256, velikost} ali None, "tema": {...}}],
          "nacin": deb|flatpak|appimage|windows|neznano, "stran": url, "preverjeno": cas}. Brez omrezja vrze izjemo.
    """
    m = manifest if manifest is not None else prenesi_manifest()
    nacin = nacin or ("windows" if platforma == "windows" else nacin_namestitve())
    skupina = m.get(platforma) if isinstance(m.get(platforma), dict) else {}
    nove: List[dict] = []
    for kljuc, nasa in razlicice.items():
        paket = skupina.get(kljuc)
        if not isinstance(paket, dict) or not novejsa(paket.get("razlicica", ""), nasa):
            continue
        vnos = {"kljuc": kljuc, "ime": IMENA.get(kljuc, kljuc), "nasa": nasa, "razlicica": str(paket.get("razlicica")),
                "datoteka": _vnos_datoteke(paket, nacin)}
        if kljuc == "safeer-os" and nacin == "deb" and "tema_deb" in paket:
            if veljavna_datoteka(paket["tema_deb"]):
                vnos["tema"] = paket["tema_deb"]
            else:
                vnos["datoteka"] = None   # paket videza gre v isti apt-get: brez veljavnega vnosa nic napol (samo stran)
        nove.append(vnos)
    novo = skupina.get("novo") if isinstance(skupina.get("novo"), dict) else {}
    return {"nove": nove, "nacin": nacin, "stran": str(m.get("stran") or STRAN), "preverjeno": int(time.time()),
            "novo": {k: str(v) for k, v in novo.items() if isinstance(v, str)}}


def opis(izid: dict) -> str:
    """"Safeer OS 0.4.23, Safeer Control 2.1.21" ali ""."""
    return ", ".join(f"{n['ime']} {n['razlicica']}" for n in izid.get("nove") or [])


def prenesi(url: str, cilj: str, sha256: str, velikost: int = 0, napredek: Optional[Callable[[int, int], None]] = None,
            prekini: Optional[Callable[[], bool]] = None, agent: str = "SafeerOS") -> str:
    """Prenese datoteko v `cilj` (prek zacasne), sproti racuna SHA-256 in jo ob neujemanju zavrze. Vrne pot.

    SHA-256 je obvezen (iz podpisanega seznama); brez veljavnega se prenos sploh ne zacne. Samo https, tudi po preusmeritvi.
    """
    if not isinstance(sha256, str) or _SHA256.fullmatch(sha256.lower()) is None:
        raise ValueError("SHA-256 paketa manjka ali ni veljaven")
    if not dovoljen_naslov(url):
        raise ValueError("naslov posodobitve ni varen (samo https)")
    os.makedirs(os.path.dirname(cilj) or ".", exist_ok=True)
    zacasna = cilj + ".del"
    h = hashlib.sha256()
    try:
        with _odpri(url, {"User-Agent": agent}, 30) as o, open(zacasna, "wb") as f:
            skupaj = velikost or int(o.headers.get("Content-Length") or 0)
            prebrano = 0
            while True:
                if prekini is not None and prekini():
                    raise InterruptedError("prekinjeno")
                kos = o.read(1 << 16)
                if not kos:
                    break
                f.write(kos)
                h.update(kos)
                prebrano += len(kos)
                if napredek is not None:
                    napredek(prebrano, skupaj)
        if h.hexdigest() != sha256.lower():
            raise ValueError("SHA-256 se ne ujema")
        os.replace(zacasna, cilj)
    except BaseException:
        # Preklican, prekinjen ali pokvarjen prenos ne pusti delne datoteke (paket ima vec deset MB).
        try:
            os.remove(zacasna)
        except OSError:
            pass
        raise
    return cilj


def namesti_linux(nacin: str, poti: List[str]) -> subprocess.CompletedProcess:
    """Namestitev prenesenih datotek: deb -> pkexec apt-get install (polkit geslo), flatpak -> flatpak install --user.

    Brez --allow-downgrades: posodobitev nikoli ne namesti starejse razlicice, kot je namescena.
    """
    if nacin == "deb":
        return subprocess.run(["pkexec", "apt-get", "install", "-y", *poti], capture_output=True, text=True, timeout=900)
    if nacin == "flatpak":
        return subprocess.run(["flatpak", "install", "--user", "-y", "--reinstall", *poti], capture_output=True, text=True, timeout=900)
    if nacin == "appimage":
        # Nova datoteka zamenja tekoco NA ISTI POTI (ime ostane): bliznjice, meni in AppImageLauncher kazejo nanjo se naprej.
        zdajsnji = os.environ.get("APPIMAGE") or ""
        if not zdajsnji or not poti:
            raise RuntimeError("AppImage ni znan")
        shutil.move(poti[0], zdajsnji)
        os.chmod(zdajsnji, 0o755)
        return subprocess.CompletedProcess(["appimage", zdajsnji], 0, zdajsnji, "")
    raise RuntimeError("neznan nacin namestitve")


class Posodabljanje:
    """Stanje enega posodabljanja za vmesnik: faza (prenos | namescanje | koncano | napaka), odstotek, sporocilo."""

    def __init__(self) -> None:
        self.faza = ""
        self.odstotek = 0
        self.sporocilo = ""
        self.prekinjeno = False
        self.nit: Optional[threading.Thread] = None

    def tece(self) -> bool:
        return self.nit is not None and self.nit.is_alive()

    def stanje(self) -> dict:
        return {"faza": self.faza, "odstotek": self.odstotek, "sporocilo": self.sporocilo, "tece": self.tece()}

    def zacni(self, delo: Callable[["Posodabljanje"], None]) -> bool:
        if self.tece():
            return False
        self.faza, self.odstotek, self.sporocilo, self.prekinjeno = "prenos", 0, "", False

        def ovoj() -> None:
            try:
                delo(self)
                if self.faza != "napaka":
                    self.faza = "koncano"
            except InterruptedError:
                self.faza, self.sporocilo = "napaka", "prekinjeno"
            except Exception as e:  # noqa: BLE001 - uporabnik dobi kratko sporocilo, podrobnosti v dnevnik
                self.faza, self.sporocilo = "napaka", str(e)
        self.nit = threading.Thread(target=ovoj, name="safeer-posodobitev", daemon=True)
        self.nit.start()
        return True
