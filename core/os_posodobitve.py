"""Posodobitve Safeer OS s safeer.si (os/razlicice.json) - skupno Linuxu in Windows.

Aplikacija sama pove, da je na voljo nova razlicica, in jo na zeljo uporabnika prenese ter preda namescanju. Seznam
razlicic je podpisan (Ed25519, razlicice.json.sig z istega gostitelja) in brez veljavnega podpisa se zavrne; paket se
preveri s SHA-256 iz podpisanega seznama (obvezen); vse gre samo prek https. Namescanje: Linux .deb prek `pkexec apt-get install` (polkit vprasa za geslo), Flatpak prek `flatpak install --user`,
AppImage zamenja sam sebe; Windows zazene nov SafeerOS-Windows-<ver>.exe (zaganjalnik razpakira novo razlicico).
Nic se ne namesti brez uporabnika; preverba je tiha (najvec na 6 ur) in brez posledic, ce omrezja ni.

Beta kanal (lastnik, 18. 10. 2026: »Beta kanal za navdusence, manjse in pogostejse izdaje«; privzeto izklopljen): poleg
stabilnega seznama se prebere se razlicice-beta.json z istega gostitelja. Podpisan je z istim kljucem, a z DRUGIM
kontekstom (KONTEKST_BETA), zato ga noben odjemalec - tudi ze namesceni starejsi, ki polja "kanal" ne poznajo - ne more
sprejeti kot stabilni seznam. Paket se preveri enako strogo (podpisan SHA-256, samo https). Stabilni kanal predizdaj
(1.0.128-beta.1) ne vidi nikoli, tudi ce bi pomotoma zasle v stabilni seznam. Izklop bete nicesar ne zamenja navzdol:
ostane namescena beta, dokler stabilna ni enaka ali novejsa (1.0.128-beta.2 < 1.0.128).
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

from core import root_ukaz

from .signed_feed import _signature_ok

MANIFEST = os.environ.get("SAFEER_MANIFEST_URL") or "https://safeer.si/os/razlicice.json"   # okoljska spremenljivka za preizkuse
MANIFEST_BETA = os.environ.get("SAFEER_MANIFEST_BETA_URL") or "https://safeer.si/os/razlicice-beta.json"
STRAN = "https://safeer.si/os/"
KANAL_STABILNO = "stabilno"
KANAL_BETA = "beta"
KANALI = (KANAL_STABILNO, KANAL_BETA)
PREVERBA_S = 6 * 3600
IMENA = {"safeer-os": "Safeer OS", "safeer-control": "Safeer Control", "safeer-browser": "Safeer Browser"}
# Javni kljuci Ed25519 za podpis razlicice.json (zasebni kljuc je samo na racunalniku, ki gradi stran safeer.si).
# Kontekst loci ta podpis od podpisov seznamov grozenj (core/signed_feed.py), tudi ce bi bil kljuc isti.
KLJUCI: Dict[str, str] = {"safeer-razlicice-2026-10": "yx7oxoDdoscufSxSOLf9JuDo0uIajPsUNmUjJEqUVjE="}
KONTEKST = b"safeer-razlicice-v1\n"
# Beta seznam: lasten kontekst podpisa (glej opis modula) - pristen beta seznam ni nikoli veljaven stabilni seznam.
KONTEKST_BETA = b"safeer-razlicice-beta-v1\n"
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


def preveri_podpis(podatki: bytes, podpis: bytes, kljuci: Optional[Dict[str, str]] = None,
                   kontekst: bytes = KONTEKST) -> None:
    """Vrze NapakaPodpisa, ce `podatki` (natanko bajti razlicice.json) ni podpisal kljuc, ki mu zaupamo.

    `podpis` je JSON seznam [{"alg": "ed25519", "key_id": ..., "sig": base64}] - ob menjavi kljuca podpiseta oba.
    `kontekst` loci stabilni seznam (KONTEKST) od beta seznama (KONTEKST_BETA).
    """
    try:
        vnosi = json.loads(podpis.decode("ascii"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise NapakaPodpisa("podpis seznama različic ni berljiv") from None
    zaupani = KLJUCI if kljuci is None else kljuci
    if not isinstance(vnosi, list) or not any(_signature_ok(v, zaupani, kontekst, podatki) for v in vnosi[:8]):
        raise NapakaPodpisa("podpis seznama različic ni veljaven")


# 1.0.128, 0.4.86-beta.2 (oznaka in packaging/VERSION*), 0.4.86~beta.2 (Version paketa .deb, glej packaging/deb_razlicica.sh)
_RAZLICICA = re.compile(r"\s*v?(\d+(?:\.\d+){0,3})(?:[-~.]?(alpha|beta|rc)(?:\.?(\d+))?)?", re.IGNORECASE)
_FAZE = {"alpha": 0, "beta": 1, "rc": 2}
_KONCNA = 9   # koncna izdaja je za vsemi predizdajami iste stevilke


def kljuc_razlicice(v) -> tuple:
    """Kljuc za urejanje: 1.0.128-beta.1 < 1.0.128-beta.2 < 1.0.128-rc.1 < 1.0.128 < 1.0.129-beta.1.

    Do 18. 10. 2026 so stele samo stevilke, zato bi bila 1.0.128-beta.2 (1,0,128,2) novejsa od 1.0.128 in uporabnik bete
    koncne izdaje ne bi dobil nikoli. Neberljiva razlicica ni novejsa od nobene prave.
    """
    m = _RAZLICICA.match(str(v or ""))
    if not m:
        return ((0, 0, 0, 0), -1, 0)
    st = tuple(int(x) for x in m.group(1).split("."))
    st += (0,) * (4 - len(st))
    if m.group(2):
        return (st, _FAZE[m.group(2).lower()], int(m.group(3) or 0))
    return (st, _KONCNA, 0)


def je_predizdaja(v) -> bool:
    """1.0.128-beta.1 (ali ~beta.1, -rc.1) da; 1.0.128 in neberljivo ne."""
    return 0 <= kljuc_razlicice(v)[1] < _KONCNA


def novejsa(nova: str, nasa: str) -> bool:
    """Ali je razlicica `nova` ("0.4.23", "0.4.24-beta.1") novejsa od `nasa` ("0.4.22")."""
    return kljuc_razlicice(nova) > kljuc_razlicice(nasa)


def _privzeta_stanje_pot() -> str:
    """Datoteka z najvisjo ze videno izdajo seznama (anti-rollback) in kanalom. Okoljska spremenljivka jo prepise (preizkusi)."""
    p = os.environ.get("SAFEER_POSODOBITVE_STANJE")
    if p:
        return p
    baza = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(baza, "safeer-os", "posodobitve.json")


# Stanje beremo in pisemo iz niti preverbe (Safeer OS, Control v istem procesu) in iz vmesnika (kanal): ena datoteka,
# zato branje-sprememba-zapis pod zaklepom, sicer bi preverba z zapisom 'izdano' izbrisala ravnokar izbrani kanal.
_ZAKLEP_STANJA = threading.Lock()


def _beri_stanje(pot: str) -> dict:
    try:
        with open(pot, "r", encoding="ascii") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _zadnje_izdano(pot: str, kljuc: str = "izdano") -> str:
    """Najvisja ze videna vrednost 'izdano' (RFC3339) ali prazen niz (ni datoteke ali ni berljiva)."""
    v = _beri_stanje(pot).get(kljuc, "")
    return v if isinstance(v, str) else ""


def _shrani_stanje(pot: str, spremembe: dict) -> bool:
    """Atomarno doda `spremembe` v datoteko stanja (ostala polja ostanejo); False, ce ni mogoce."""
    with _ZAKLEP_STANJA:
        d = _beri_stanje(pot)
        d.update(spremembe)
        try:
            os.makedirs(os.path.dirname(pot) or ".", exist_ok=True)
            zac = "%s.%d.%d.del" % (pot, os.getpid(), threading.get_ident())
            with open(zac, "w", encoding="ascii") as f:
                json.dump(d, f)
            os.replace(zac, pot)
            return True
        except OSError:
            return False


def _shrani_izdano(pot: str, izdano: str, kljuc: str = "izdano") -> None:
    """Shrani najvisjo videno izdajo; ce ni mogoce, anti-rollback tiho odpove (svezina se velja)."""
    _shrani_stanje(pot, {kljuc: izdano})


def izbrani_kanal(pot: Optional[str] = None) -> str:
    """Izbrani kanal posodobitev: "beta" samo, ce ga je uporabnik vklopil; sicer (privzeto) "stabilno"."""
    return KANAL_BETA if _beri_stanje(pot or _privzeta_stanje_pot()).get("kanal") == KANAL_BETA else KANAL_STABILNO


def nastavi_kanal(novi: str, pot: Optional[str] = None) -> str:
    """Shrani kanal ("beta" | "stabilno") in vrne tistega, ki zdaj velja. Nicesar ne namesti in ne odstrani."""
    if novi not in KANALI:
        raise ValueError("kanal: beta | stabilno")
    _shrani_stanje(pot or _privzeta_stanje_pot(), {"kanal": novi})
    return izbrani_kanal(pot)


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


def prenesi_manifest(url: str = "", cas: float = 8.0, agent: str = "SafeerOS",
                     kljuci: Optional[Dict[str, str]] = None, stanje_pot: Optional[str] = None,
                     zdaj: Optional[datetime] = None, kanal: str = KANAL_STABILNO) -> dict:
    """Prenese razlicice.json in podpis (razlicice.json.sig) z istega gostitelja; brez veljavnega podpisa vrze izjemo.

    Po podpisu preveri se svezino: 'potece' mora biti v prihodnosti in 'izdano' ne sme biti starejse od ze videnega
    (anti-rollback), da kdor obvlada gostitelja (ne kljuca), ne more ponoviti pristne stare (ranljive) razlicice.
    kanal="beta": razlicice-beta.json s kontekstom KONTEKST_BETA, poljem "kanal": "beta" in svojim anti-rollbackom.
    """
    beta = kanal == KANAL_BETA
    url = url or (MANIFEST_BETA if beta else MANIFEST)
    podatki, koncni = _beri(url, cas, agent, NAJVEC_SEZNAM)
    try:
        podpis, _ = _beri(_naslov_podpisa(koncni), cas, agent, NAJVEC_PODPIS)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NapakaPodpisa("podpis seznama različic manjka") from None
        raise
    preveri_podpis(podatki, podpis, kljuci, KONTEKST_BETA if beta else KONTEKST)
    m = json.loads(podatki.decode("utf-8"))
    if beta:
        if not isinstance(m, dict) or m.get("kanal") != KANAL_BETA or not isinstance(m.get("linux"), dict):
            raise ValueError("seznam beta ni pravi")
    elif not isinstance(m, dict) or "android" not in m or m.get("kanal", KANAL_STABILNO) != KANAL_STABILNO:
        raise ValueError("manifest ni pravi")
    pot = stanje_pot or _privzeta_stanje_pot()
    kljuc = "izdano_beta" if beta else "izdano"
    izdano = preveri_svezino(m, _zadnje_izdano(pot, kljuc), zdaj)
    _shrani_izdano(pot, izdano, kljuc)
    return m


def nacin_namestitve() -> str:
    """Kako je Safeer OS namescen na tem racunalniku: deb | flatpak | appimage | windows | neznano."""
    if sys.platform.startswith("win"):
        return "windows"
    if os.environ.get("FLATPAK_ID"):
        # Flatpak je glavna pot; ob njem je lahko namescen se paket .deb (sistemski deli: prijava, zagon, Cinnamon),
        # ki ga zaganjalnik .deb preda Flatpaku. Posodobita se oba, sicer bi sistemski deli zaostajali.
        return "flatpak+deb" if gostitelj_ima_deb() else "flatpak"
    if os.environ.get("APPIMAGE"):
        return "appimage"
    if shutil.which("dpkg") and (namescen_deb("safeer-os") or je_aplikacija_deb()):
        return "deb"
    return "neznano"


def namescen_deb(paket: str) -> bool:
    """Paket je namescen (dpkg »ii«). Datoteka /var/lib/dpkg/info/<paket>.list ostane tudi po odstranitvi (stanje rc/ic,
    pomocnik 20. 10. 2026: po menjavi aplikacija -> namizje je safeer-os-app.list ostal, 0 B) - zato ne steje."""
    if not shutil.which("dpkg-query"):
        return False
    try:
        r = subprocess.run(["dpkg-query", "-W", "-f", "${db:Status-Abbrev}", paket], capture_output=True, text=True,
                           timeout=10)
    except Exception:  # noqa: BLE001
        return False
    return r.returncode == 0 and r.stdout.startswith("ii")


def je_aplikacija_deb() -> bool:
    """Ali je namescen paket safeer-os-app (aplikacija v oknu, od 20. 10. 2026) namesto namiznega okolja safeer-os.
    Posodobitev mora prenesti isti paket - namizno okolje bi aplikacijo zamenjalo z namizjem (in obratno)."""
    return namescen_deb("safeer-os-app")


def gostitelj_ima_deb() -> bool:
    """V Flatpaku: ali je na racunalniku namescen paket safeer-os (.deb)."""
    if not os.environ.get("FLATPAK_ID") or not shutil.which("flatpak-spawn"):
        return False
    try:
        r = subprocess.run(["flatpak-spawn", "--host", "dpkg-query", "-W", "-f", "${Status}", "safeer-os"],
                           capture_output=True, text=True, timeout=10)
        return r.returncode == 0 and r.stdout.strip().endswith("installed")
    except Exception:
        return False


def _vnos_datoteke(paket: dict, nacin: str) -> Optional[dict]:
    """Datoteka za namestitev v programu ali None (nova razlicica brez nje: vmesnik odpre stran)."""
    if nacin == "windows":
        d = {k: paket.get(k) for k in ("url", "sha256", "velikost")}
    else:
        kljuc = {"deb": "deb", "flatpak": "flatpak", "flatpak+deb": "flatpak", "appimage": "appimage"}.get(nacin, "")
        # Aplikacija (safeer-os-app) dobi svoj paket "deb_app"; brez njega nic (stran), ne namizno okolje namesto nje.
        if kljuc == "deb" and je_aplikacija_deb():
            kljuc = "deb_app"
        d = paket.get(kljuc)
    return d if veljavna_datoteka(d) else None


def _skupina(m: Optional[dict], platforma: str) -> dict:
    return m.get(platforma) if isinstance(m, dict) and isinstance(m.get(platforma), dict) else {}


def _izberi(stabilni, beta) -> tuple:
    """(paket, iz_bete): novejsi od obeh vnosov. Predizdaje iz stabilnega seznama ne veljajo (stabilni kanal jih ne vidi
    nikoli, tudi ce bi pomotoma zasle tja); ob enaki razlicici ima prednost stabilni vnos."""
    s = stabilni if isinstance(stabilni, dict) and not je_predizdaja(stabilni.get("razlicica", "")) else None
    b = beta if isinstance(beta, dict) and beta.get("razlicica") else None
    if b is not None and (s is None or novejsa(b.get("razlicica", ""), s.get("razlicica", ""))):
        return b, True
    return s, False


def preveri(platforma: str, razlicice: Dict[str, str], manifest: Optional[dict] = None, nacin: Optional[str] = None,
            kanal: Optional[str] = None, beta_manifest: Optional[dict] = None) -> dict:
    """Primerja nase razlicice ({"safeer-os": "0.4.22", "safeer-control": "2.1.20"}) z manifestom.

    Vrne {"nove": [{"kljuc", "ime", "nasa", "razlicica", "datoteka": {url, sha256, velikost} ali None, "tema": {...},
          "beta": bool}], "nacin": deb|flatpak|appimage|windows|neznano, "stran": url, "preverjeno": cas, "kanal",
          "na_beti": tece predizdaja, "beta_napaka": zakaj beta seznama ni bilo}. Brez omrezja vrze izjemo.
    kanal=None: izbira uporabnika (izbrani_kanal()); s podanim manifestom (preizkusi) stabilno. V beta kanalu je ponujena
    novejsa od stabilne in beta razlicice; ce beta seznama ni ali ni veljaven, ostane stabilni (nikoli nic slabsega).
    """
    if kanal is None:
        kanal = KANAL_STABILNO if manifest is not None else izbrani_kanal()
    m = manifest if manifest is not None else prenesi_manifest()
    mb, beta_napaka = None, ""
    if kanal == KANAL_BETA:
        try:
            mb = beta_manifest if beta_manifest is not None else prenesi_manifest(kanal=KANAL_BETA)
        except Exception as e:  # noqa: BLE001 - brez bete ostane stabilni seznam (ze preverjen)
            beta_napaka = str(e) or e.__class__.__name__
    nacin = nacin or ("windows" if platforma == "windows" else nacin_namestitve())
    skupina, skupina_b = _skupina(m, platforma), _skupina(mb, platforma)
    nove: List[dict] = []
    iz_bete_kaj = False
    for kljuc, nasa in razlicice.items():
        paket, iz_bete = _izberi(skupina.get(kljuc), skupina_b.get(kljuc))
        if paket is None or not novejsa(paket.get("razlicica", ""), nasa):
            continue
        iz_bete_kaj = iz_bete_kaj or iz_bete
        vnos = {"kljuc": kljuc, "ime": IMENA.get(kljuc, kljuc), "nasa": nasa, "razlicica": str(paket.get("razlicica")),
                "datoteka": _vnos_datoteke(paket, nacin), "beta": iz_bete}
        if kljuc == "safeer-os" and nacin == "flatpak+deb":
            # Oba paketa v enem koraku; brez veljavnega .deb nic napol (samo stran).
            if veljavna_datoteka(paket.get("deb")):
                vnos["deb"] = paket["deb"]
            else:
                vnos["datoteka"] = None
        if kljuc == "safeer-os" and nacin == "deb" and "tema_deb" in paket:
            if veljavna_datoteka(paket["tema_deb"]):
                vnos["tema"] = paket["tema_deb"]
            else:
                vnos["datoteka"] = None   # paket videza gre v isti apt-get: brez veljavnega vnosa nic napol (samo stran)
        # Skupni WebKit (paket safeer-webkit, od 19. 10. 2026): safeer-os in safeer-browser (.deb) ga zahtevata v
        # razlicici izdaje, zato gre v isti apt-get kot program (sicer apt-get odvisnosti ne razresi in posodobitev pade).
        # Brez veljavnega vnosa nic napol (samo stran). Flatpak in AppImage imata svoj WebKit.
        if "webkit_deb" in paket and (nacin == "deb" or "deb" in vnos):
            if veljavna_datoteka(paket["webkit_deb"]):
                vnos["webkit"] = paket["webkit_deb"]
            else:
                vnos["datoteka"] = None
        nove.append(vnos)
    # Besedilo »kaj je novo« in stran izdaje sta od seznama, iz katerega je ponujena razlicica.
    vir, vir_m = (skupina_b, mb) if iz_bete_kaj else (skupina, m)
    novo = vir.get("novo") if isinstance(vir.get("novo"), dict) else {}
    # Ponudbe »hitrejsi Splet: preklopi na Flatpak« ni vec (19. 10. 2026): od 15. 10. ima .deb nas WebKit, od 1.0.127 v
    # paketu safeer-webkit s PGO in BOLT (Flatpak brez BOLT) - trditev »hitrejsi« nima podlage v meritvi, uporabnik pa bi
    # prenesel ~420 MB. Kljuc ostane (vmesnik gumb skrije), namestitev Flatpaka (namesti_flatpak) ostane za rocni preklop.
    preklop = None
    # Nova razlicica brez datoteke za ta nacin namestitve (npr. AppImage od 1.0.132 ni v izdaji): samo stran s prenosi,
    # nikoli polovicne posodobitve; vmesnik pove, kaj je na voljo (posodobitevAppImagePod / posodobitevRocnoPod).
    rocno = bool(nove) and not any(n.get("datoteka") for n in nove)
    return {"nove": nove, "nacin": nacin, "rocno": rocno, "flatpak_preklop": preklop, "stran": str(vir_m.get("stran") or STRAN),
            "preverjeno": int(time.time()), "novo": {k: str(v) for k, v in novo.items() if isinstance(v, str)},
            "kanal": kanal, "na_beti": any(je_predizdaja(v) for v in razlicice.values()), "beta_napaka": beta_napaka}


def datoteke_namestitve(n: dict) -> List[dict]:
    """Datoteke ene nove razlicice za prenos in en klic namestitve: program, paket videza, .deb ob Flatpaku in skupni
    WebKit (safeer-webkit) - vsaka samo enkrat. Stabilni seznam nosi safeer-webkit tudi kot "tema_deb" (izdane
    razlicice do 1.0.126 ga tako namestijo v istem apt-get), novejsi program ga zato ne prenese dvakrat."""
    izid: List[dict] = []
    for kljuc in ("datoteka", "tema", "deb", "webkit"):
        d = n.get(kljuc)
        if isinstance(d, dict) and all(str(d.get("url")) != str(x.get("url")) for x in izid):
            izid.append(d)
    return izid


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


#: Namestitev .deb kot root (pkexec). Paket v ~/.cache je v lasti uporabnika: ce bi apt-get bral kar njega, bi ga lahko
#: program, ki ze tece kot uporabnik, zamenjal PO preverbi SHA-256 in po vpisanem geslu - in dobil root (neodvisni
#: pregled 19. 10. 2026). Zato root vsak paket najprej prekopira v svojo mapo (0700, samo root), preveri SHA-256 KOPIJE
#: proti vsoti iz podpisanega seznama (argument, ki ga uporabnik ne more spremeniti) in namesti samo kopije.
#: Brez --allow-downgrades: posodobitev nikoli ne namesti starejse razlicice, kot je namescena.
NAMESTI_DEB_KOT_ROOT = r"""set -eu
d="$(mktemp -d /var/cache/safeer-posodobitev.XXXXXX 2>/dev/null || mktemp -d)"
trap 'rm -rf "$d"' EXIT
i=0
datoteke=""
while [ "$#" -ge 2 ]; do
    i=$((i + 1))
    k="$d/$i.deb"
    # Samo navadna datoteka, brez sledenja povezavi in brez cakanja na FIFO (nonblock), najvec 2 GiB in 10 min:
    # program uporabnika bi sicer lahko podtaknil /dev/zero (poln disk) ali FIFO (root caka). Vsebino preveri SHA-256.
    [ -f "$2" ] && [ ! -L "$2" ] || { echo "ni navadna datoteka: $2" >&2; exit 2; }
    timeout 600 dd if="$2" of="$k" bs=1M count=2048 iflag=nofollow,nonblock status=none || {
        echo "kopiranje ni uspelo: $2" >&2; exit 2; }
    printf '%s  %s\n' "$1" "$k" | sha256sum -c --quiet - || { echo "SHA-256 se ne ujema: $2" >&2; exit 3; }
    datoteke="$datoteke $k"
    shift 2
done
[ "$#" -eq 0 ] && [ -n "$datoteke" ] || { echo "manjka paket ali SHA-256" >&2; exit 2; }
apt-get install -y $datoteke
"""


def _ukaz_deb(poti: List[str], vsote: Optional[List[str]]) -> List[str]:
    """pkexec /bin/sh -c NAMESTI_DEB_KOT_ROOT safeer-posodobitev SHA POT [SHA POT ...]."""
    if vsote is None or len(vsote) != len(poti):
        raise ValueError("SHA-256 paketov manjka")
    pari: List[str] = []
    for pot, vsota in zip(poti, vsote):
        vsota = str(vsota or "").lower()
        if _SHA256.fullmatch(vsota) is None:
            raise ValueError("SHA-256 paketa ni veljaven")
        pari += [vsota, os.path.abspath(pot)]
    # /usr/bin/pkexec tudi v Flatpaku: ta ukaz tece na gostitelju (flatpak-spawn --host) - glej core/root_ukaz.py.
    return [root_ukaz.PKEXEC, root_ukaz.SH, "-c", NAMESTI_DEB_KOT_ROOT, "safeer-posodobitev", *pari]


def namesti_linux(nacin: str, poti: List[str], vsote: Optional[List[str]] = None) -> subprocess.CompletedProcess:
    """Namestitev prenesenih datotek: deb -> kot root (pkexec, polkit geslo) iz preverjene kopije, flatpak -> --user.

    `vsote`: SHA-256 vsake datoteke iz `poti` (isti vrstni red) iz podpisanega seznama - za .deb obvezne.
    """
    if nacin == "deb":
        return subprocess.run(_ukaz_deb(poti, vsote), capture_output=True, text=True, timeout=900)
    if nacin == "flatpak":
        return subprocess.run(["flatpak", "install", "--user", "-y", "--reinstall", *poti], capture_output=True, text=True, timeout=900)
    if nacin == "flatpak+deb":
        # Najprej .deb na racunalniku (pkexec vprasa za geslo), nato Flatpak. Poti so v ~/.cache - enake na racunalniku.
        debi = [p for p in poti if p.endswith(".deb")]
        flatpaki = [p for p in poti if not p.endswith(".deb")]
        if debi:
            vsote_debov = None if vsote is None else [v for p, v in zip(poti, vsote) if p.endswith(".deb")]
            r = subprocess.run(["flatpak-spawn", "--host", *_ukaz_deb(debi, vsote_debov)],
                               capture_output=True, text=True, timeout=900)
            if r.returncode != 0:
                return r
        return subprocess.run(["flatpak", "install", "--user", "-y", "--reinstall", *flatpaki],
                              capture_output=True, text=True, timeout=900)
    if nacin == "appimage":
        # Nova datoteka zamenja tekoco NA ISTI POTI (ime ostane): bliznjice, meni in AppImageLauncher kazejo nanjo se naprej.
        zdajsnji = os.environ.get("APPIMAGE") or ""
        if not zdajsnji or not poti:
            raise RuntimeError("AppImage ni znan")
        shutil.move(poti[0], zdajsnji)
        os.chmod(zdajsnji, 0o755)
        return subprocess.CompletedProcess(["appimage", zdajsnji], 0, zdajsnji, "")
    raise RuntimeError("neznan nacin namestitve")


FLATPAK_ID = "io.github.memelandfaner.SafeerOS"


def flatpak_namescen() -> bool:
    """Ali je Safeer OS kot Flatpak ze namescen (za uporabnika ali za vse)."""
    if not shutil.which("flatpak"):
        return False
    try:
        return subprocess.run(["flatpak", "info", FLATPAK_ID], capture_output=True, timeout=15).returncode == 0
    except Exception:
        return False


def namesti_flatpak(pot: str) -> subprocess.CompletedProcess:
    """Paket Flatpak za uporabnika (brez gesla); runtime GNOME pride s Flathuba (--runtime-repo v paketu)."""
    return subprocess.run(["flatpak", "install", "--user", "-y", "--noninteractive", pot],
                          capture_output=True, text=True, timeout=3600)


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
