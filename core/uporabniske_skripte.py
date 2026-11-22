"""Skripte, ki jih uporabnik sam uvozi v Medijski center (JavaScript v strani Spotify, shell na zahtevo).

Safeer skript ne dostavlja, ne prenasa in ne priporoca: kar uporabnik uvozi in vklopi, je njegova odlocitev in njegova
odgovornost (lastnik, 18. 10. 2026). Uvozi jih izrecno iz datoteke, ki jo izbere, po opozorilu v vmesniku.

- JavaScript (.js): teče v strani Spotify v Safeer DRM, pred skriptami strani (kot uporabniske skripte v brskalniku).
  Uporabi se ob naslednjem zagonu Spotifyja v Medijskem centru. Nima dostopa do mosta Safeer OS (Python), samo do strani.
- Shell (.sh): teče samo na uporabnikov ukaz (gumb Zazeni), z njegovimi pravicami (bash, brez sudo), najvec 60 s;
  izpis in izhodna koda se pokazeta v vmesniku.

Shramba: <XDG_DATA_HOME>/safeer-os/skripte/ (kazalo.json in datoteke <id>.js / <id>.sh), samo za uporabnika (0700/0600).

Ena shramba za vse skripte (18. 10. 2026, ob umiku GTK3 brskalnika): tudi uporabniske skripte Spleta in GTK4 Safeer
Browserja (core/splet_skripte.py) so tu, z istim jedrom za glavo ==UserScript== (core/userscripts.py). Kje skripta tece,
pove njena glava: skripta brez glave tece kot doslej samo v strani Spotify; skripta z glavo (@match/@include) tece v
Spletu na teh straneh in v strani Spotify samo, ce jo glava zajame. Vrednosti GM_setValue so v <id>.vrednosti.json.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import threading
import weakref
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import userscripts

from core import zasebni_webkit
from core import shramba_json

NAJVEC_SKRIPT = 50
NAJVEC_BAJTOV = 256 * 1024
NAJVEC_IMEN = 80
CAS_SHELL_S = 60
NAJVEC_IZPISA = 4000
VRSTE = ("js", "sh")
_ID = re.compile(r"^[0-9a-f]{12}$")
_zaklep = threading.RLock()

#: Stran Spotify v Medijskem centru (core/spotify_racun.IZVOR): skripta z glavo tam tece, ce jo glava zajame.
SPOTIFY = "https://open.spotify.com/"
#: Most shrambe GM_setValue v Spletu (core/splet_skripte.py) - isto ime kot v GTK3 brskalniku.
MOST_GM = "safeer_gm"
#: Meje shrambe vrednosti ene skripte (kot v GTK3 brskalniku) in skupna meja datoteke (vsak zapis jo prepise celo).
NAJVEC_KLJUCEV = 200
NAJVEC_BAJTOV_VREDNOSTI = 64 * 1024
NAJVEC_BAJTOV_SHRAMBE = 1024 * 1024
#: Poslusalci sprememb seznama (Splet v istem procesu osvezi zavihke, ko Medijski center vklopi skripto).
_poslusalci: List[Any] = []


def mapa() -> Path:
    """Mapa s skriptami (SAFEER_SKRIPTE_MAPA prepise pot, za preizkuse)."""
    pot = os.environ.get("SAFEER_SKRIPTE_MAPA")
    if pot:
        return Path(pot)
    osnova = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(osnova) / "safeer-os" / "skripte"


def _kazalo_pot() -> Path:
    return mapa() / "kazalo.json"


def _beri() -> List[Dict[str, Any]]:
    try:
        podatki = json.loads(_kazalo_pot().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    izid = []
    for s in podatki if isinstance(podatki, list) else []:
        if (isinstance(s, dict) and _ID.match(str(s.get("id", ""))) and s.get("vrsta") in VRSTE
                and isinstance(s.get("ime"), str)):
            izid.append({"id": s["id"], "ime": s["ime"][:NAJVEC_IMEN], "vrsta": s["vrsta"], "vklopljena": bool(s.get("vklopljena"))})
    return izid[:NAJVEC_SKRIPT]


def _zapisi(seznam: List[Dict[str, Any]]) -> None:
    m = mapa()
    m.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(m, 0o700)
    except OSError:
        pass
    shramba_json.zapisi_atomsko(_kazalo_pot(), seznam, indent=None)


def _pot_skripte(s: Dict[str, Any]) -> Path:
    return mapa() / ("%s.%s" % (s["id"], s["vrsta"]))


def _ime(ime: Any, vrsta: str) -> str:
    ime = re.sub(r"[\x00-\x1f\x7f]", " ", str(ime or "")).strip()
    ime = os.path.basename(ime.replace("\\", "/")).strip() or ("skripta." + vrsta)
    return ime[:NAJVEC_IMEN]


def vrsta_iz_imena(ime: str) -> str:
    k = str(ime or "").lower().rsplit(".", 1)[-1]
    return k if k in VRSTE else ""


def primer_poti() -> str:
    """Celotna pot za primer v polju (lastnik, 18. 10. 2026: »~« uporabniku nic ne pove) - mapa Prejemi tega uporabnika
    (XDG_DOWNLOAD_DIR iz ~/.config/user-dirs.dirs, sicer ~/Downloads) in ime skripta.js."""
    dom = os.path.expanduser("~")
    mapa_prejemov = os.path.join(dom, "Downloads")
    try:
        with open(os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(dom, ".config"), "user-dirs.dirs"),
                  encoding="utf-8") as f:
            for vrstica in f:
                m = re.match(r'\s*XDG_DOWNLOAD_DIR="([^"]+)"', vrstica)
                if m:
                    mapa_prejemov = m.group(1).replace("$HOME", dom)
                    break
    except OSError:
        pass
    return os.path.join(mapa_prejemov, "skripta.js")


def preberi_pot(pot: Any) -> Dict[str, Any]:
    """Prebere skripto s poti, ki jo uporabnik vpise v vmesnik (npr. ~/Prejemi/skripta.js) - za tiste, ki datoteke v
    oknu za izbiro ne najdejo (lastnik, 18. 10. 2026). Samo branje: uvoz gre se vedno skozi opozorilo in uvozi().
    Dovoljena je samo navadna datoteka .js/.sh v domaci mapi, ne v skritih mapah (~/.ssh, ~/.config ...)."""
    besedilo = str(pot or "").strip()
    if not besedilo or len(besedilo) > 4096 or "\x00" in besedilo:
        return {"ok": False, "napaka": "pot"}
    dom = os.path.realpath(os.path.expanduser("~"))
    polna = os.path.realpath(os.path.expanduser(besedilo) if besedilo.startswith("~") else
                             (besedilo if os.path.isabs(besedilo) else os.path.join(dom, besedilo)))
    if not polna.startswith(dom + os.sep):
        return {"ok": False, "napaka": "pot"}
    if any(d.startswith(".") for d in os.path.relpath(polna, dom).split(os.sep)):
        return {"ok": False, "napaka": "pot"}
    if not vrsta_iz_imena(polna):
        return {"ok": False, "napaka": "vrsta"}
    try:
        if not os.path.isfile(polna):
            return {"ok": False, "napaka": "ni_datoteke"}
        if os.path.getsize(polna) > NAJVEC_BAJTOV:
            return {"ok": False, "napaka": "velikost"}
        with open(polna, "rb") as f:
            bajti = f.read(NAJVEC_BAJTOV + 1)
        vsebina = bajti.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return {"ok": False, "napaka": "ni_datoteke"}
    if len(bajti) > NAJVEC_BAJTOV or "\x00" in vsebina:
        return {"ok": False, "napaka": "velikost"}
    return {"ok": True, "ime": os.path.basename(polna), "vsebina": vsebina}


def ob_spremembi(poslusalec: Callable[[], Any]) -> None:
    """Klic ob vsaki spremembi seznama (uvoz, vklop, sprememba, odstranitev) - iz niti, kjer se je zgodila.
    Metoda predmeta se hrani sibko (zaprt Splet ne ostane v pomnilniku)."""
    _poslusalci.append(weakref.WeakMethod(poslusalec) if hasattr(poslusalec, "__self__") else poslusalec)


def _sporoci() -> None:
    for p in list(_poslusalci):
        fn = p() if isinstance(p, weakref.WeakMethod) else p
        if fn is None:
            try:
                _poslusalci.remove(p)
            except ValueError:
                pass
            continue
        try:
            fn()
        except Exception as napaka:  # noqa: BLE001 - poslusalec ne sme podreti shrambe
            print("[Skripte] poslusalec:", napaka, flush=True)


def _koda(x: Dict[str, Any]) -> str:
    try:
        return _pot_skripte(x).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return ""


def _koren() -> str:
    return str(Path(__file__).resolve().parent.parent)


def pripravi(x: Dict[str, Any], koda: str, koren: str = "") -> Dict[str, Any]:
    """Skripta JavaScript iz shrambe, pripravljena za WebKit (core/userscripts.pripravi) z njenimi vrednostmi."""
    return userscripts.pripravi({"id": x["id"], "code": koda}, vrednosti(x["id"]), koren or _koren(), MOST_GM)


def kje(koda: str, pripravljeno: Optional[Dict[str, Any]] = None) -> str:
    """Kje skripta JavaScript tece: »spotify« (brez glave - kot doslej samo stran Spotify), »splet« (glava z @match),
    »oboje« (glava zajame tudi stran Spotify) ali »ne« (glava zahteva, cesar Safeer nima, ali nima uporabnega vzorca)."""
    if not userscripts.razclenii_glavo(koda)["ima_glavo"]:
        return "spotify"
    p = pripravljeno if pripravljeno is not None else userscripts.pripravi({"id": "x", "code": koda}, {}, _koren())
    if p.get("napaka"):
        return "ne"
    return "oboje" if userscripts.velja(p, SPOTIFY) else "splet"


def seznam() -> List[Dict[str, Any]]:
    """Vse skripte; skripta JavaScript ima se »kje« (glej kje()) - Medijski center pove, kje tece."""
    with _zaklep:
        izid = _beri()
        for x in izid:
            if x["vrsta"] == "js":
                x["kje"] = kje(_koda(x))
        return izid


def skripte_js(koren: str = "") -> List[Dict[str, Any]]:
    """Skripte JavaScript za Splet: [{id, ime, naslov, vklopljena, pot, koda, kje, pripravljeno}] (tudi izklopljene,
    za seznam v Spletu). naslov je @name iz glave ali ime datoteke; pot je celotna pot do datoteke v shrambi."""
    izid = []
    with _zaklep:
        for x in _beri():
            if x["vrsta"] != "js":
                continue
            koda = _koda(x)
            p = pripravi(x, koda, koren)
            izid.append(dict(x, naslov=(p.get("glava") or {}).get("name") or x["ime"], pot=str(_pot_skripte(x)),
                             koda=koda, kje=kje(koda, p), pripravljeno=p))
    return izid


def uvozi(ime: Any, vsebina: Any, vrsta: Any = "") -> Dict[str, Any]:
    """Uvozi skripto (privzeto izklopljeno). {"ok": True, "skripta": {...}} ali {"ok": False, "napaka": ...}."""
    if not isinstance(vsebina, str) or not vsebina.strip():
        return {"ok": False, "napaka": "prazno"}
    vrsta = str(vrsta or "") or vrsta_iz_imena(str(ime))
    if vrsta not in VRSTE:
        return {"ok": False, "napaka": "vrsta"}
    bajti = vsebina.encode("utf-8")
    if len(bajti) > NAJVEC_BAJTOV or b"\x00" in bajti:
        return {"ok": False, "napaka": "velikost"}
    with _zaklep:
        s = _beri()
        if len(s) >= NAJVEC_SKRIPT:
            return {"ok": False, "napaka": "preveliko_stevilo"}
        nova = {"id": secrets.token_hex(6), "ime": _ime(ime, vrsta), "vrsta": vrsta, "vklopljena": False}
        m = mapa()
        m.mkdir(parents=True, exist_ok=True)
        pot = _pot_skripte(nova)
        pot.write_bytes(bajti)
        os.chmod(pot, 0o600)
        _zapisi(s + [nova])
    _sporoci()
    return {"ok": True, "skripta": nova}


def _najdi(s: List[Dict[str, Any]], id_: Any) -> Optional[Dict[str, Any]]:
    return next((x for x in s if x["id"] == str(id_)), None)


def vklopi(id_: Any, da: Any) -> Dict[str, Any]:
    with _zaklep:
        s = _beri()
        x = _najdi(s, id_)
        if x is None:
            return {"ok": False, "napaka": "ni_skripte"}
        x["vklopljena"] = bool(da)
        _zapisi(s)
    _sporoci()
    return {"ok": True, "skripta": x}


def posodobi(id_: Any, vsebina: Any) -> Dict[str, Any]:
    """Nova koda obstojece skripte (urejevalnik v Spletu); vklop in ime ostaneta."""
    if not isinstance(vsebina, str) or not vsebina.strip():
        return {"ok": False, "napaka": "prazno"}
    bajti = vsebina.encode("utf-8")
    if len(bajti) > NAJVEC_BAJTOV or b"\x00" in bajti:
        return {"ok": False, "napaka": "velikost"}
    with _zaklep:
        x = _najdi(_beri(), id_)
        if x is None:
            return {"ok": False, "napaka": "ni_skripte"}
        pot = _pot_skripte(x)
        shramba_json.zapisi_besedilo_atomsko(str(pot), bytes(bajti))
    _sporoci()
    return {"ok": True, "skripta": x}


def odstrani(id_: Any) -> Dict[str, Any]:
    with _zaklep:
        s = _beri()
        x = _najdi(s, id_)
        if x is None:
            return {"ok": False, "napaka": "ni_skripte"}
        for pot in (_pot_skripte(x), _pot_vrednosti(x["id"])):
            try:
                pot.unlink()
            except OSError:
                pass
        _zapisi([y for y in s if y["id"] != x["id"]])
    _sporoci()
    return {"ok": True}


# ---------------------------------------------------------------- vrednosti GM_setValue (samo skripte JavaScript)
def _pot_vrednosti(id_: str) -> Path:
    return mapa() / ("%s.vrednosti.json" % id_)


def vrednosti(id_: Any) -> Dict[str, Any]:
    """Shranjene vrednosti ene skripte (GM_getValue); skripta drugih ne vidi."""
    if not _ID.match(str(id_ or "")):
        return {}
    try:
        podatki = json.loads(_pot_vrednosti(str(id_)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return podatki if isinstance(podatki, dict) else {}


def _zapisi_vrednosti(id_: str, podatki: Dict[str, Any]) -> bool:
    besedilo = json.dumps(podatki, ensure_ascii=False)
    if len(besedilo.encode("utf-8")) > NAJVEC_BAJTOV_SHRAMBE:
        return False
    pot = _pot_vrednosti(id_)
    shramba_json.zapisi_besedilo_atomsko(str(pot), besedilo)
    return True


def _sme_pisati(id_: Any, kljuc: Any) -> bool:
    """Sporocilo pride iz skripte na tuji strani: pisemo samo v predal vklopljene skripte JavaScript, ki obstaja."""
    if not isinstance(kljuc, str) or not kljuc or len(kljuc) > 200:
        return False
    x = _najdi(_beri(), id_)
    return x is not None and x["vrsta"] == "js" and x["vklopljena"]


def shrani_vrednost(id_: Any, kljuc: Any, vrednost: Any) -> bool:
    try:
        if len(json.dumps(vrednost, ensure_ascii=False)) > NAJVEC_BAJTOV_VREDNOSTI:
            return False
    except (TypeError, ValueError):
        return False
    with _zaklep:
        if not _sme_pisati(id_, kljuc):
            return False
        podatki = vrednosti(id_)
        if kljuc not in podatki and len(podatki) >= NAJVEC_KLJUCEV:
            return False
        podatki[kljuc] = vrednost
        try:
            return _zapisi_vrednosti(str(id_), podatki)
        except OSError:
            return False


def izbrisi_vrednost(id_: Any, kljuc: Any) -> bool:
    with _zaklep:
        if not _sme_pisati(id_, kljuc):
            return False
        podatki = vrednosti(id_)
        if kljuc not in podatki:
            return False
        del podatki[kljuc]
        try:
            return _zapisi_vrednosti(str(id_), podatki)
        except OSError:
            return False


def aktivne_js() -> List[Dict[str, str]]:
    """Vklopljene skripte JavaScript za stran Spotify: [{ime, koda}].

    Skripta brez glave ==UserScript== gre v stran Spotify kot doslej (koda nespremenjena). Skripta z glavo gre tja
    samo, ce jo glava zajame (npr. @match *://*/* ali https://open.spotify.com/*) - skripta za YouTube v strani
    Spotify ne tece. Taka skripta dobi svoje funkcije GM_ (predpona) in cas zagona iz @run-at."""
    izid = []
    with _zaklep:
        for x in _beri():
            if x["vrsta"] != "js" or not x["vklopljena"]:
                continue
            koda = _koda(x)
            if not koda:
                continue
            if not userscripts.razclenii_glavo(koda)["ima_glavo"]:
                izid.append({"ime": x["ime"], "koda": koda})
                continue
            p = pripravi(x, koda)
            if not userscripts.velja(p, SPOTIFY):
                continue
            vir = p["vir"]
            if p["run_at"] != "document-start":
                # Safeer DRM vstavi skripte pred dokumentom (Page.addScriptToEvaluateOnNewDocument): document-end pocaka.
                vir = ("(function () { var f = function () {\n" + vir + "\n}; if (document.readyState === 'loading') "
                       "document.addEventListener('DOMContentLoaded', f, { once: true }); else f(); })();")
            izid.append({"ime": x["ime"], "koda": vir})
    return izid


def _glava_iz_starega(s: Dict[str, Any]) -> str:
    """Glava za skripto GTK3 brskalnika brez glave: ime, vzorec in cas zagona iz njegovih polj (isti pomen)."""
    cisto = lambda v: re.sub(r"[\x00-\x1f\x7f]", " ", str(v or "")).strip()  # noqa: E731
    return ("// ==UserScript==\n// @name %s\n// @include %s\n// @run-at %s\n// ==/UserScript==\n"
            % (cisto(s.get("name")) or "skripta", cisto(s.get("pattern")) or "*",
               "document-start" if s.get("run_at") == "start" else "document-end"))


def preseli_iz_nastavitev(config) -> int:
    """Enkratna selitev skript GTK3 brskalnika (nastavitev user_scripts in user_script_values) v to shrambo, da ob
    umiku GTK3 (18. 10. 2026) nobena ne izgine. Skripta brez glave dobi glavo iz svojih polj (vzorec, cas zagona),
    vklop in shranjene vrednosti ostanejo. Vzorcna skripta (sample_banner_cleaner) se ne seli. Vrne stevilo skript.

    Oznaka »preseljeno« je v mapi shrambe, ne v nastavitvah: settings.json si delita paket .deb in Flatpak brskalnika,
    shrambi pa sta locene (Flatpak ima svoj XDG_DATA_HOME) - vsaka shramba dobi skripte enkrat. Brez skript za selitev
    se ne zapise nic (preizkus z zacasnimi nastavitvami tako ne oznaci prave shrambe)."""
    if config is None:
        return 0
    stare = config.get("user_scripts") or []
    stare = [s for s in (stare if isinstance(stare, list) else [])
             if isinstance(s, dict) and s.get("id") != "sample_banner_cleaner"
             and isinstance(s.get("code"), str) and s["code"].strip()]
    oznaka = mapa() / "preseljeno-gtk3"
    if not stare or oznaka.exists():
        return 0
    vrednosti_vse = config.get("user_script_values") or {}
    stevilo = 0
    for s in stare:
        koda = s["code"]
        if not userscripts.razclenii_glavo(koda)["ima_glavo"]:
            koda = _glava_iz_starega(s) + koda
        r = uvozi(s.get("name") or "skripta", koda, "js")
        if not r.get("ok"):
            print("[Skripte] selitev skripte ni uspela:", r.get("napaka"), flush=True)
            continue
        nova = r["skripta"]["id"]
        stare_vrednosti = vrednosti_vse.get(s.get("id")) if isinstance(vrednosti_vse, dict) else None
        if isinstance(stare_vrednosti, dict) and stare_vrednosti:
            with _zaklep:
                try:
                    _zapisi_vrednosti(nova, {str(k): v for k, v in list(stare_vrednosti.items())[:NAJVEC_KLJUCEV]})
                except OSError:
                    pass
        if s.get("enabled", True):
            vklopi(nova, True)
        stevilo += 1
    oznaka.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(oznaka.parent, 0o700)
    except OSError:
        pass
    oznaka.write_text("1\n", encoding="utf-8")
    return stevilo


def zazeni_shell(id_: Any, cas: float = CAS_SHELL_S) -> Dict[str, Any]:
    """Zazene shell skripto na uporabnikov ukaz: bash <datoteka>, brez sudo, z mejo casa. Izpis (stdout+stderr) je okrnjen."""
    with _zaklep:
        x = _najdi(_beri(), id_)
        if x is None or x["vrsta"] != "sh":
            return {"ok": False, "napaka": "ni_skripte"}
        pot = _pot_skripte(x)
    if not pot.is_file():
        return {"ok": False, "napaka": "ni_skripte"}
    try:
        # Skripta uporabnika tece v njegovem okolju, brez nasih zasebnih poti (WebKit, AppImage).
        r = subprocess.run(["bash", str(pot)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           cwd=os.path.expanduser("~"), timeout=cas, text=True, errors="replace",
                           env=zasebni_webkit.okolje_za_zunanje())
        izpis, koda = r.stdout or "", r.returncode
    except subprocess.TimeoutExpired as e:
        izpis = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return {"ok": False, "napaka": "cas", "izpis": izpis[-NAJVEC_IZPISA:]}
    except OSError:
        return {"ok": False, "napaka": "ni_bash"}
    return {"ok": koda == 0, "koda": koda, "izpis": izpis[-NAJVEC_IZPISA:]}
