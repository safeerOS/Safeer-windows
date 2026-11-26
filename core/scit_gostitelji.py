"""Googlovi gostitelji za Scit grozenj (brskalnik in DNS), ista zasnova kot telefon in TV (ScitGostitelji, 5. 11. 2026).

Prej je bil vsak vnos vira grozenj (vgrajen seznam, seznami Scita ali podpisani vir intel.safeer.si) veljaven za
gostitelja in vse pod njim: ena napacna ali podtaknjena vrstica »google.com« ali »sites.google.com« je vzela iskanje,
prijavo ali vso platformo vsem uporabnikom. Zdaj so Googlovi gostitelji v treh skupinah:

- koren (iskanje, prijava in njeni viri): nikoli blokiran, tudi ne kot C2/malware;
- skupni gostitelji z uporabnisko vsebino (sites.google.com, storage.googleapis.com ...): blokira se samo tocen
  naslov z vsaj dvema deloma poti, nikoli cel gostitelj - DNS zato na njih nikoli ne blokira (pozna samo ime);
- projekti (*.web.app, *.firebaseapp.com, *.appspot.com): cel projekt sme biti blokiran, koren platforme nikoli.

Skupna koda Linux in Windows (scripts/skupna_koda.py v Safeer-windows); brez uvozov iz core, ker jo uporablja tudi
core/threat_intel.py, ki se v zamrznjenem paketu Windows nalaga zgodaj.
"""

from __future__ import annotations

KOREN = "koren"
VSEBINA = "vsebina"
NAVADEN = "navaden"

#: Pripone za »google.« - izrecen seznam Googlovih domen, ne vzorec co.xx (google.co.xx lahko registrira kdorkoli in
#: bi sicer postal koren, ki ga nic ne blokira). Vir: https://www.google.com/supported_domains, prenos 5. 11. 2026
#: (187 domen, SHA-256 zacetek ba827017007f54b6), isti seznam kot GooglePravila.GOOGLE_PRIPONE na TV.
GOOGLE_PRIPONE = frozenset((
    "com", "ad", "ae", "com.af", "com.ag", "al", "am", "co.ao", "com.ar", "as", "at", "com.au", "az", "ba",
    "com.bd", "be", "bf", "bg", "com.bh", "bi", "bj", "com.bn", "com.bo", "com.br", "bs", "bt", "co.bw", "by",
    "com.bz", "ca", "cd", "cf", "cg", "ch", "ci", "co.ck", "cl", "cm", "cn", "com.co", "co.cr", "com.cu", "cv",
    "com.cy", "cz", "de", "dj", "dk", "dm", "com.do", "dz", "com.ec", "ee", "com.eg", "es", "com.et", "fi",
    "com.fj", "fm", "fr", "ga", "ge", "gg", "com.gh", "com.gi", "gl", "gm", "gr", "com.gt", "gy", "com.hk", "hn",
    "hr", "ht", "hu", "co.id", "ie", "co.il", "im", "co.in", "iq", "is", "it", "je", "com.jm", "jo", "co.jp",
    "co.ke", "com.kh", "ki", "kg", "co.kr", "com.kw", "kz", "la", "com.lb", "li", "lk", "co.ls", "lt", "lu",
    "lv", "com.ly", "co.ma", "md", "me", "mg", "mk", "ml", "com.mm", "mn", "com.mt", "mu", "mv", "mw", "com.mx",
    "com.my", "co.mz", "com.na", "com.ng", "com.ni", "ne", "nl", "no", "com.np", "nr", "nu", "co.nz", "com.om",
    "com.pa", "com.pe", "com.pg", "com.ph", "com.pk", "pl", "pn", "com.pr", "ps", "pt", "com.py", "com.qa", "ro",
    "ru", "rw", "com.sa", "com.sb", "sc", "se", "com.sg", "sh", "si", "sk", "com.sl", "sn", "so", "sm", "sr",
    "st", "com.sv", "td", "tg", "co.th", "com.tj", "tl", "tm", "tn", "to", "com.tr", "tt", "com.tw", "co.tz",
    "com.ua", "co.ug", "co.uk", "com.uy", "co.uz", "com.vc", "co.ve", "co.vi", "com.vn", "vu", "ws", "rs",
    "co.za", "co.zm", "co.zw", "cat",
))

#: Iskanje in prijava brez uporabniske vsebine; oauth2.googleapis.com in accounts.youtube.com rabi prijava.
_KOREN = frozenset(("gstatic.com", "apis.google.com", "fonts.googleapis.com", "ajax.googleapis.com",
                    "oauth2.googleapis.com", "accounts.youtube.com"))
#: Pregled 6. 11. 2026 (S1): consent.google.<pripona> je stran soglasja v EU (nanjo google.com preusmeri vsak nov brskalnik).
_PREDPONE_KORENA = ("", "www.", "accounts.", "myaccount.", "consent.")
#: Skupni gostitelji, kjer objavlja kdorkoli. www.googleapis.com streze tudi Google Cloud Storage
#: (/download/storage/v1/b/<vedro>/o/...), zato je skupni gostitelj, ne koren.
_VSEBINA = frozenset(("sites.google.com", "docs.google.com", "script.google.com", "drive.google.com",
                      "storage.googleapis.com", "firebasestorage.googleapis.com", "www.googleapis.com",
                      "googleusercontent.com"))
#: Vsak podgostitelj je en projekt (zlo.web.app): ta sme biti blokiran v celoti, koren platforme nikoli.
_NAJEMNIK = ("web.app", "firebaseapp.com", "appspot.com")
#: Domene, katerih vnos v viru nikoli ne blokira vseh gostiteljev pod njimi (poleg google.<pripona>).
_CELOTNA = frozenset(("googleapis.com", "gstatic.com", "googleusercontent.com") + _NAJEMNIK)


def _cist(ime) -> str:
    return str(ime or "").strip().lower().rstrip(".")


def _je_google_domena(h: str) -> bool:
    return h.startswith("google.") and h[len("google."):] in GOOGLE_PRIPONE


def vrsta(gostitelj) -> str:
    """KOREN, VSEBINA ali NAVADEN za ime gostitelja (male crke, brez koncne pike)."""
    h = _cist(gostitelj)
    if h in _KOREN or h.endswith(".gstatic.com"):
        return KOREN
    if any(h.startswith(p) and _je_google_domena(h[len(p):]) for p in _PREDPONE_KORENA):
        return KOREN
    # *.googleusercontent.com (lh3, doc-...): skupna infrastruktura, zato tudi tu samo pot.
    if h in _VSEBINA or h.endswith(".googleusercontent.com"):
        return VSEBINA
    if any(h == n or h.endswith("." + n) for n in _NAJEMNIK):
        return VSEBINA
    return NAVADEN


def je_najemnik(gostitelj) -> bool:
    """Gostitelj enega projekta (zlo.web.app), ne koren platforme."""
    h = _cist(gostitelj)
    return any(h.endswith("." + n) for n in _NAJEMNIK)


def je_celotna_domena(domena) -> bool:
    d = _cist(domena)
    return d in _CELOTNA or _je_google_domena(d)


def sme_gostitelj(domena) -> bool:
    """Ali sme pravilo za gostitelja ali domeno [domena] blokirati: navaden gostitelj ali projekt da; koren, skupni
    gostitelj in celotna platforma nikoli (DNS in pravila gostitelja ne poznajo poti)."""
    d = _cist(domena)
    if not d or je_celotna_domena(d):
        return False
    return vrsta(d) == NAVADEN or je_najemnik(d)


def sme_pot(url, gostitelj) -> bool:
    """Pravilo za naslov velja na skupnem gostitelju samo z vsaj dvema deloma poti (/view/ime, /macros/s/ID/exec).
    Ena raven (/forms, /view, /drive) ali koren je vstopna stran izdelka - z njo bi blokirali vse uporabnike.
    Pregled 6. 11. 2026 (S2): ena raven z neprazno poizvedbo tudi (drive.google.com/uc?export=download&id=X) - pravilo
    naslova se ujema tocno s poizvedbo, zato vstopne strani /uc ne ustavi."""
    if je_najemnik(gostitelj):
        return True
    url = str(url or "")
    i = url.find("://")
    if i < 0:
        return False
    ostanek = url[i + 3:]
    konec = next((j for j, c in enumerate(ostanek) if c in "/?#\\"), -1)
    if konec < 0 or ostanek[konec] != "/":
        return False
    brez_sidra = ostanek[konec:].split("#", 1)[0]
    pot, _, poizvedba = brez_sidra.partition("?")
    delov = sum(1 for d in pot.split("/") if d)
    return delov >= 2 or (delov == 1 and bool(poizvedba))
