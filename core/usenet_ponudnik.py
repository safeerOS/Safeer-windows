"""Splosna nastavitev ponudnika NNTP (Usenet korak 3, del A; lastnik 26. 10. 2026).

Usenet se v vmesniku pokaze sele, ko uporabnik vpise SVOJEGA ponudnika: Safeer ne priporoca in ne vsebuje imen
ponudnikov. Uporabnik vir shrani in nanj pozabi; vprasa se ga samo ob resni spremembi (zavrnjena prijava, zapah).

- Geslo ni nikoli v nastavitvah, repr, izjemi ali dnevniku: samo v sistemski zbirki skrivnosti (skrivnosti.py) pod
  kljucem iz odtisa SHA-256 (gostitelj, uporabnik) - goli niz bi uporabnika pokazal v atributih zbirke.
- Zaklep racuna je prednost lastnika: preverba uporablja vrata prijave in zapah iz usenet_nntp (Bazen._pred_prijavo,
  _po_prijavi, _ustavi) - novih pravil tu ni. Zavrnjeno geslo gre k strezniku enkrat; nov poskus odklene samo vpis
  DRUGEGA gesla ali racuna (shrani_ponudnika). Ponovni vpis istega zavrnjenega gesla zapaha ne odklene in ne ponastavi
  omejitve 1/min; ime in stevilo povezav se spremenita brez gesla (posodobi_nastavitve).
- Brez omrezja na glavni niti in nic v ozadju: preverba je samo uporabnikov gumb, najvec 1 na minuto na racun.
- Trda meja racuna je najvec_povezav (vpise jo uporabnik); naprava, ki predvaja, dobi vse, delitve po napravah ni.
  Meja velja na RACUN: en zivi bazen na racun, preverba med predvajanjem ne odpre dodatne povezave.
- TLS privzeto. Brez TLS samo z izrecnim nevarno_brez_tls=True in naslovom IP v domacem omrezju; usenet_nntp zna
  samo TLS, zato tak ponudnik ostane shranjen, povezava pa se jasno zavrne (brez omrezja).
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import ssl
import tempfile
import threading
import time
import weakref
from typing import Optional

from . import usenet_nntp as nntp
from .sporocila import skrivnosti

_log = logging.getLogger("safeer.usenet")

VRATA = nntp.VRATA
PRIVZETO_POVEZAV = nntp.PRIVZETO_POVEZAV
NAJVEC_POVEZAV_RACUNA = 100  # meja vnosa; Bazen sam ne gre cez nntp.NAJVEC_POVEZAV
NAJVEC_IME = 80
PREVERBA_NA_S = 60.0  # 1 preverba na minuto na racun (gumb »Preveri«)
NAJVEC_NASTAVITEV_BAJTOV = 64 * 1024  # datoteka nastavitev je majhna - vec je tuja ali pokvarjena
_VERZIJA = 1
_PREDPONA_KLJUCA = "usenet-ponudnik-"

# Izidi preverbe.
VELJA = "VELJA"
NE_VELJA = "NE_VELJA"
ZAKLENJEN = "ZAKLENJEN"
NI_ODGOVORA = "NI_ODGOVORA"
PREVEC_POVEZAV = "PREVEC_POVEZAV"
PREPOGOSTO = "PREPOGOSTO"  # gumb znova pred iztekom minute: brez omrezja
V_UPORABI = "V_UPORABI"  # racun ima zivi bazen: nova povezava bi presegla trdo mejo racuna, brez omrezja
NEPREVERJEN = "NEPREVERJEN"  # samo stanje_za_vmesnik

# Razlogi NapakaPonudnika (brez vrednosti).
NI_GESLA = "ni_gesla"
BREZ_TLS = "brez_tls_ni_podprt"
RACUN_ZAKLENJEN = "racun_zaklenjen"
GESLO_ZAVRNJENO = "geslo_ze_zavrnjeno"  # vpis gesla, ki ga je ponudnik ze zavrnil: nic se ne spremeni
NI_PONUDNIKA = "ni_ponudnika"  # posodobi_nastavitve brez veljavnega shranjenega ponudnika
PREVERBA_TECE = "preverba_tece"  # meja racuna 1 in prav tece preverba: bazen bi jo presegel

_POLJA = ("gostitelj", "uporabnik", "vrata", "tls", "najvec_povezav", "ime", "nevarno_brez_tls")
_OZNAKA = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class NapakaPonudnika(Exception):
    """Jasna napaka brez omrezja. Nosi samo razlog - nikoli gesla, uporabnika ali gostitelja."""

    def __init__(self, razlog: str):
        super().__init__(razlog)
        self.razlog = razlog

    def __str__(self) -> str:
        return "usenet ponudnik: %s" % self.razlog

    def __repr__(self) -> str:
        return "NapakaPonudnika(%r)" % self.razlog


# ------------------------------------------------------------------ validacija

def _naslov_ip(g: str):
    try:
        return ipaddress.ip_address(g)
    except ValueError:
        return None


def _veljaven_gostitelj(g: object) -> bool:
    """Ime ali IP brez sheme, poti, vrat in presledkov. Najprej pravila usenet_nntp, nato oznake DNS."""
    try:
        nntp._preveri_gostitelja(g, VRATA)
    except ValueError:
        return False
    g = str(g)
    if _naslov_ip(g) is not None:
        return True
    try:
        ascii_ime = g.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return False
    oznake = ascii_ime.split(".")
    if len(ascii_ime) > 253 or not all(_OZNAKA.match(o) for o in oznake):
        return False  # tudi »news.x:563«, »x://y« in koncna pika
    return not all(o.isdigit() for o in oznake)  # »999.1.1.1« ni IP in ni ime


#: Domace omrezje: RFC 1918, lokalni in povezavni naslovi, IPv6 ULA. ipaddress.is_private bi spustil tudi
#: dokumentacijske in rezervirane obsege (npr. 203.0.113.0/24), zato izrecen seznam.
_DOMACA = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16", "::1/128", "fc00::/7",
    "fe80::/10"))


def domace_omrezje(gostitelj: str) -> bool:
    """Samo naslov IP v domacem obsegu. Ime ne velja: brez DNS (omrezje) ne vemo, kam kaze."""
    ip = _naslov_ip(gostitelj)
    if ip is None:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return any(ip.version == n.version and ip in n for n in _DOMACA)


def _je_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)  # True ni stevilo vrat


@dataclasses.dataclass(frozen=True, repr=False)
class Ponudnik:
    """Nastavitev ponudnika brez gesla. Neveljavne vrednosti ne morejo obstajati (ValueError brez vrednosti)."""

    gostitelj: str
    uporabnik: str
    vrata: int = VRATA
    tls: bool = True
    najvec_povezav: int = PRIVZETO_POVEZAV
    ime: str = ""
    nevarno_brez_tls: bool = False

    def __post_init__(self) -> None:
        if not _veljaven_gostitelj(self.gostitelj):
            raise ValueError("usenet ponudnik: neveljaven gostitelj")
        if not _je_int(self.vrata) or not 1 <= self.vrata <= 65535:
            raise ValueError("usenet ponudnik: neveljavna vrata")
        if not nntp.varna_poverilnica(self.uporabnik):
            raise ValueError("usenet ponudnik: neveljavno uporabnisko ime")
        if not _je_int(self.najvec_povezav) or not 1 <= self.najvec_povezav <= NAJVEC_POVEZAV_RACUNA:
            raise ValueError("usenet ponudnik: najvec_povezav mora biti 1-100")
        if (not isinstance(self.ime, str) or len(self.ime) > NAJVEC_IME
                or any(z < " " or z == "\x7f" for z in self.ime)):
            raise ValueError("usenet ponudnik: neveljavno ime")
        if not isinstance(self.tls, bool) or not isinstance(self.nevarno_brez_tls, bool):
            raise ValueError("usenet ponudnik: tls mora biti bool")
        if not self.tls:
            # Geslo v golem besedilu: samo izrecna odlocitev in samo doma (lastnik: TLS privzeto).
            if not self.nevarno_brez_tls:
                raise ValueError("usenet ponudnik: brez TLS samo z nevarno_brez_tls=True")
            if not domace_omrezje(self.gostitelj):
                raise ValueError("usenet ponudnik: brez TLS samo do naslova IP v domacem omrezju")

    def __repr__(self) -> str:
        # Uporabnik nikoli v celoti (pregledi: dnevnik in porocila o napakah gredo ven).
        return "Ponudnik(ime=%r, %s:%d, tls=%s, povezav=%d, uporabnik=<skrit>)" % (
            self.ime, self.gostitelj, self.vrata, self.tls, self.najvec_povezav)

    __str__ = __repr__

    @property
    def kljuc_gesla(self) -> str:
        """Kljuc v zbirki: odtis, ker so atributi zbirke berljivi brez odklepa."""
        h = hashlib.sha256()
        for x in (self.gostitelj.lower(), self.uporabnik):
            b = x.encode("utf-8")
            h.update(len(b).to_bytes(4, "big") + b)  # dolzina: »ab|c« in »a|bc« nista isti kljuc
        return _PREDPONA_KLJUCA + h.hexdigest()

    def v_slovar(self) -> dict:
        return {"gostitelj": self.gostitelj, "uporabnik": self.uporabnik, "vrata": self.vrata, "tls": self.tls,
                "najvec_povezav": self.najvec_povezav, "ime": self.ime, "nevarno_brez_tls": self.nevarno_brez_tls}

    @classmethod
    def iz_slovarja(cls, d: object) -> "Ponudnik":
        if not isinstance(d, dict) or set(d) - set(_POLJA):
            raise ValueError("usenet ponudnik: neveljaven zapis")  # neznano polje: tuj ali spremenjen zapis
        try:
            return cls(**{k: d[k] for k in _POLJA if k in d})
        except TypeError:
            raise ValueError("usenet ponudnik: neveljaven zapis") from None  # TypeError bi nosil ime polja


# ------------------------------------------------------------------ geslo (samo zbirka; brez nje samo pomnilnik)

#: Brez sistemske zbirke ostane geslo samo v pomnilniku procesa (kot priloga 2) - nikoli na disk.
_V_POMNILNIKU: dict = {}
_POMNILNIK_ZAKLEP = threading.Lock()


def _shrani_geslo(kljuc: str, geslo: str) -> bool:
    trajno = bool(skrivnosti.shrani(kljuc, geslo))
    with _POMNILNIK_ZAKLEP:
        if trajno:
            _V_POMNILNIKU.pop(kljuc, None)
        else:
            _V_POMNILNIKU[kljuc] = geslo
    return trajno


def _preberi_geslo(kljuc: str) -> Optional[str]:
    with _POMNILNIK_ZAKLEP:
        g = _V_POMNILNIKU.get(kljuc)
    if g is None:
        g = skrivnosti.preberi(kljuc)
    return g if nntp.varna_poverilnica(g) else None  # pokvarjen vnos zbirke ne gre v ukaz


def _pozabi_geslo(kljuc: str) -> None:
    with _POMNILNIK_ZAKLEP:
        _V_POMNILNIKU.pop(kljuc, None)
    skrivnosti.pozabi(kljuc)


# ------------------------------------------------------------------ nastavitve (JSON, atomarno, 0600)

def _beri_json(pot: str) -> Optional[dict]:
    try:
        with open(pot, "rb") as f:
            surovo = f.read(NAJVEC_NASTAVITEV_BAJTOV + 1)
    except FileNotFoundError:
        return None
    except OSError as e:
        _log.info("usenet ponudnik: nastavitev ni mogoce prebrati (%s)", type(e).__name__)
        return None
    if len(surovo) > NAJVEC_NASTAVITEV_BAJTOV:
        _log.info("usenet ponudnik: nastavitve so prevelike")
        return None
    try:
        d = json.loads(surovo.decode("utf-8"))
    except (UnicodeError, ValueError, RecursionError):
        # RecursionError ni ValueError: globoko gnezden JSON (do 64 KiB) bi sicer podrl tudi shrani in pozabi,
        # s katerima uporabnik pokvarjeno datoteko popravi (pregled 77 G2).
        _log.info("usenet ponudnik: nastavitve niso veljaven JSON")
        return None
    return d if isinstance(d, dict) and d.get("verzija") == _VERZIJA else None


def _pisi_json(pot: str, podatki: dict) -> None:
    """Atomarno (mkstemp 0600 + fsync + os.replace): sesutje ne pusti pol datoteke, drugi uporabniki je ne berejo."""
    mapa = os.path.dirname(os.path.abspath(pot))
    os.makedirs(mapa, mode=0o700, exist_ok=True)
    besedilo = json.dumps(podatki, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    fd, zacasna = tempfile.mkstemp(prefix=".usenet-ponudnik-", dir=mapa)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(besedilo)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(zacasna, 0o600)
        os.replace(zacasna, pot)
    except BaseException:
        try:
            os.unlink(zacasna)
        except OSError:
            pass
        raise


def _ponudnik_iz(d: Optional[dict]) -> Optional[Ponudnik]:
    if d is None:
        return None
    try:
        return Ponudnik.iz_slovarja(d.get("ponudnik"))
    except ValueError:
        _log.info("usenet ponudnik: shranjen ponudnik ni veljaven")
        return None


# Vse branje-sprememba-pisanje nastavitev (shrani, pozabi, posodobi, zapis izida) je pod enim zaklepom: brez njega
# zapis izida z delovne niti povozi socasen nov vpis s starim ponudnikom (pregled 77 G5). RLock, ker se klici gnezdijo.
_NASTAVITVE_ZAKLEP = threading.RLock()
_KLJUC_ZBIRKE = re.compile(r"^" + re.escape(_PREDPONA_KLJUCA) + r"[0-9a-f]{64}$")


def _pot_kljucev(pot_nastavitev: str) -> str:
    return pot_nastavitev + ".kljuci"


def _beri_kljuce(pot_nastavitev: str) -> set:
    """Kljuci zbirke, pod katere je ta naprava kdaj zapisala geslo. Samo odtisi (gostitelj, uporabnik), nikoli geslo.

    Locena datoteka zato, ker pokvarjena datoteka nastavitev ne sme izgubiti poti do gesla v zbirki (pregled 77 G6)."""
    d = _beri_json(_pot_kljucev(pot_nastavitev))
    kljuci = d.get("kljuci") if d is not None else None
    if not isinstance(kljuci, list):
        return set()
    return {k for k in kljuci if isinstance(k, str) and _KLJUC_ZBIRKE.match(k)}


def _pisi_kljuce(pot_nastavitev: str, kljuci: set) -> None:
    _pisi_json(_pot_kljucev(pot_nastavitev), {"verzija": _VERZIJA, "kljuci": sorted(kljuci)})


# skrivnosti.shrani/preberi/pozabi po pogodbi ne vrzejo: napako zbirke (zaklenjena, ni D-Bus, GLib.Error) ujamejo same
# in vrnejo False/None. Zato tu ni lovljenja izjem - izjema od tam je napaka programa in mora biti vidna, ne pa
# skrita kot »zbirka ni dosegljiva« (naloga 116, ruff BLE001). Vrstni red v shrani_ponudnika (seznam kljucev,
# zbirka, JSON) poskrbi, da tudi taka izjema ne izgubi starega ponudnika (G5).

def _pozabi_kljuce(kljuci) -> set:
    """Zbrise gesla pod kljuci. Vrne kljuce, ki jih ni bilo mogoce zbrisati (zdaj vedno prazno: pozabi ne vrze)."""
    for k in kljuci:
        _pozabi_geslo(k)
    return set()


def _povrni_geslo(kljuc: str, prejsnje: Optional[str]) -> None:
    """Po neuspelem zapisu JSON: zbirka mora spet ustrezati nastavitvam, ki so ostale na disku."""
    if prejsnje is not None:
        _shrani_geslo(kljuc, prejsnje)
    else:
        _pozabi_geslo(kljuc)  # novo geslo brez nastavitev bi bila osirotela skrivnost


# ------------------------------------------------------------------ zavrnjena gesla (G1)

# Odtisi gesel, ki jih je ponudnik v tem procesu zavrnil. HMAC s kljucem samo v pomnilniku: gesla ni in ga brez
# kljuca ni mogoce preizkusati; nikoli na disk. Pokrije primere, ko zapah usenet_nntp tega gesla ne kaze vec
# (vmesni vpis drugega gesla, »Pozabi«), streznik pa bi isto zavrnjeno geslo dobil znova.
# Naloga 116: odtis vsebuje tudi pot nastavitev. Zavrnitev velja za nastavitve, v katerih je bila (tam je tudi
# izid preverbe in seznam kljucev); druga, neodvisna nastavitev istega racuna je prej podedovala zavrnitev in
# dobila ZAKLENJEN brez omrezja. Preverba brez poti (pot None) velja za vse nastavitve procesa - varneje.
_ZAVRNJENA_KLJUC = os.urandom(32)
_ZAVRNJENA: dict = {}
_ZAVRNJENA_NAJVEC = 64
_ZAVRNJENA_ZAKLEP = threading.Lock()


def _odtis_gesla(p: "Ponudnik", geslo: str) -> str:
    return hmac.new(_ZAVRNJENA_KLJUC, ("%s\x00%s" % (_kljuc_racuna(p), geslo)).encode("utf-8"),
                    hashlib.sha256).hexdigest()


def _obseg(pot_nastavitev: Optional[str]) -> str:
    return "" if pot_nastavitev is None else os.path.abspath(pot_nastavitev)


def _odtis_zavrnjenega(p: "Ponudnik", geslo: str, pot_nastavitev: Optional[str]) -> str:
    # Dolzina pred potjo: pot z \x00 ne more ponarediti drugega para (pot, geslo).
    obseg = _obseg(pot_nastavitev)
    return _odtis_gesla(p, "%d\x00%s\x00%s" % (len(obseg), obseg, geslo))


def _zapomni_zavrnjeno(p: "Ponudnik", geslo: str, pot_nastavitev: Optional[str]) -> None:
    o = _odtis_zavrnjenega(p, geslo, pot_nastavitev)
    with _ZAVRNJENA_ZAKLEP:
        _ZAVRNJENA.pop(o, None)
        _ZAVRNJENA[o] = None
        while len(_ZAVRNJENA) > _ZAVRNJENA_NAJVEC:
            del _ZAVRNJENA[next(iter(_ZAVRNJENA))]  # omejena velikost, najstarejsi prvi


def _znano_zavrnjeno(p: "Ponudnik", geslo: str, pot_nastavitev: Optional[str]) -> bool:
    odtisi = {_odtis_zavrnjenega(p, geslo, pot_nastavitev), _odtis_zavrnjenega(p, geslo, None)}
    with _ZAVRNJENA_ZAKLEP:
        return any(o in _ZAVRNJENA for o in odtisi)


def _geslo_ze_zavrnjeno(p: "Ponudnik", geslo: str, shranjeno: Optional[str], pot_nastavitev: str) -> bool:
    """Ali bi vpis tega gesla pomenil, da streznik znova dobi geslo, ki ga je ze zavrnil."""
    if _znano_zavrnjeno(p, geslo, pot_nastavitev):
        return True
    if not nntp.prijava_zavrnjena(p.gostitelj, p.uporabnik, geslo):
        return False
    if shranjeno is None or shranjeno == geslo:
        return True
    # Zapah kaze za to geslo. Ce kaze tudi za drugo, shranjeno geslo, je zapah na racunu (ne na geslu) in vpis
    # drugega gesla je prav sprememba, ki sme odkleniti; sicer je ponudnik zavrnil prav to geslo.
    return not nntp.prijava_zavrnjena(p.gostitelj, p.uporabnik, shranjeno)


# ------------------------------------------------------------------ javne funkcije nastavitev

def shrani_ponudnika(ponudnik: Ponudnik, geslo: str, pot_nastavitev: str) -> bool:
    """Izrecni vpis uporabnika. Vrne True, ce je geslo v sistemski zbirki (False = samo do konca procesa).

    Zapah racuna odklene samo vpis DRUGEGA gesla ali racuna (dovoli_prijavo_znova). Geslo, ki ga je ponudnik ze
    zavrnil: NapakaPonudnika(GESLO_ZAVRNJENO), nic se ne spremeni. Enako geslo ne ponastavi omejitve 1/min.
    Ime in stevilo povezav brez gesla: posodobi_nastavitve."""
    if not isinstance(ponudnik, Ponudnik):
        raise ValueError("usenet ponudnik: pricakovan Ponudnik")
    if not nntp.varna_poverilnica(geslo):
        raise ValueError("usenet ponudnik: neveljavno geslo")  # brez vrednosti
    with _NASTAVITVE_ZAKLEP:
        star = _ponudnik_iz(_beri_json(pot_nastavitev))
        nov_kljuc = ponudnik.kljuc_gesla
        shranjeno = _preberi_geslo(nov_kljuc)
        if _geslo_ze_zavrnjeno(ponudnik, geslo, shranjeno, pot_nastavitev):
            _log.info("usenet ponudnik: vpis zavrnjen, ponudnik je to geslo ze zavrnil")
            raise NapakaPonudnika(GESLO_ZAVRNJENO)
        # Samo dejanska sprememba gesla ali racuna sme odkleniti zapah in ponastaviti minuto (pregled 77 G1).
        spremenjen = shranjeno != geslo or (star is not None and _kljuc_racuna(star) != _kljuc_racuna(ponudnik))
        stari_kljuci = _beri_kljuce(pot_nastavitev)
        if star is not None:
            stari_kljuci.add(star.kljuc_gesla)
        # Vrstni red: seznam kljucev, zbirka, JSON, sele nato brisanje starih gesel. Ob napaki na kateremkoli
        # koraku ostane star ponudnik s svojim geslom, ob sesutju pa seznam pove, katero geslo pobrisati (G5, G6).
        _pisi_kljuce(pot_nastavitev, stari_kljuci | {nov_kljuc})
        trajno = _shrani_geslo(nov_kljuc, geslo)
        try:
            _pisi_json(pot_nastavitev, {"verzija": _VERZIJA, "ponudnik": ponudnik.v_slovar(), "preverba": None})
        except BaseException:
            _povrni_geslo(nov_kljuc, shranjeno)
            raise
        # Zamenjan racun ali osirotela gesla iz pokvarjene datoteke: v zbirki ostane samo vpisano geslo.
        ostali = _pozabi_kljuce(stari_kljuci - {nov_kljuc})
        try:
            _pisi_kljuce(pot_nastavitev, ostali | {nov_kljuc})
        except OSError as e:
            _log.info("usenet ponudnik: seznama kljucev ni mogoce shraniti (%s)", type(e).__name__)
        if spremenjen:
            nntp.dovoli_prijavo_znova(ponudnik.gostitelj, ponudnik.uporabnik, geslo)
            with _PREVERBE_ZAKLEP:
                _PREVERBE.pop(_kljuc_racuna(ponudnik), None)  # novo geslo sme takoj na »Preveri«
    return trajno


def posodobi_nastavitve(pot_nastavitev: str, *, ime: Optional[str] = None,
                        najvec_povezav: Optional[int] = None) -> Ponudnik:
    """Spremeni ime ali stevilo povezav BREZ gesla. Zapaha, omejitve 1/min in zadnjega izida ne spremeni.

    Brez tega bi vmesnik za vsako spremembo znova podal geslo, kar je zapah tiho odklenilo (pregled 77 G1).
    Ni veljavnega ponudnika: NapakaPonudnika(NI_PONUDNIKA); neveljavna vrednost: ValueError brez vrednosti."""
    spremembe = {}
    if ime is not None:
        spremembe["ime"] = ime
    if najvec_povezav is not None:
        spremembe["najvec_povezav"] = najvec_povezav
    with _NASTAVITVE_ZAKLEP:
        d = _beri_json(pot_nastavitev)
        p = _ponudnik_iz(d)
        if p is None:
            raise NapakaPonudnika(NI_PONUDNIKA)
        nov = dataclasses.replace(p, **spremembe)  # __post_init__ preveri nove vrednosti
        d["ponudnik"] = nov.v_slovar()  # racun in geslo sta ista, zato izid preverbe ostane
        _pisi_json(pot_nastavitev, d)
    _nastavi_mejo_racuna(nov)  # zivi bazen takoj upostevaj novo trdo mejo
    return nov


#: Pregled 118 N3: koliko pozabljenih racunov si zapomnimo (odtisi, ne imena), da jih uskladitev iz kroga ne vrne.
NAJVEC_POZABLJENIH = 32


def _pot_pozabljenih(pot_nastavitev: str) -> str:
    return pot_nastavitev + ".pozabljeni"


def _odtis_pozabljenega(gostitelj: str, uporabnik: str) -> str:
    """Odtis racuna (gostitelj in uporabnik, brez gesla) - z dolzino pred gostiteljem, da ga ni mogoce ponarediti."""
    g = (gostitelj or "").strip().lower()
    return hashlib.sha256(("%d:%s|%s" % (len(g), g, uporabnik or "")).encode("utf-8")).hexdigest()


def _pozabljeni(pot_nastavitev: str) -> list:
    d = _beri_json(_pot_pozabljenih(pot_nastavitev))
    v = d.get("odtisi") if isinstance(d, dict) else None
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


def shrani_iz_kroga(ponudnik: Ponudnik, pot_nastavitev: str) -> bool:
    """Ponudnik z naprave v ozjem krogu (naloga 114, core/usenet_vezava.prejmi_iz_kroga): BREZ gesla in samo, ce tu se
    ni ponudnika. Vrne True, ce je zapisan.

    Ne prepise lokalnega ponudnika (ta ima svoje geslo, zapah in izid preverbe), ne odklene zapaha in ne ponastavi
    omejitve 1/min - prejem ni uporabnikov vpis. Geslo vpise uporabnik na tej napravi (shrani_ponudnika), ker namizje
    nima sifriranega usklajevanja skrivnosti (secrets.sync); do takrat stanje pove NI_GESLA. Brez TLS ne sprejmemo:
    izjema »samo doma« velja za omrezje naprave, ki jo je vpisala, ne za to."""
    if not isinstance(ponudnik, Ponudnik):
        raise ValueError("usenet ponudnik: pricakovan Ponudnik")
    if not ponudnik.tls:
        raise ValueError("usenet ponudnik: brez TLS samo z nevarno_brez_tls=True")
    with _NASTAVITVE_ZAKLEP:
        if _ponudnik_iz(_beri_json(pot_nastavitev)) is not None:
            return False
        # Pregled 118 N3: racun, ki ga je uporabnik tu pozabil, uskladitev z druge naprave ne vrne.
        if _odtis_pozabljenega(ponudnik.gostitelj, ponudnik.uporabnik) in _pozabljeni(pot_nastavitev):
            return False
        _pisi_json(pot_nastavitev, {"verzija": _VERZIJA, "ponudnik": ponudnik.v_slovar(), "preverba": None,
                                    "iz_kroga": True})
    return True


def je_iz_kroga(pot_nastavitev: str) -> bool:
    """Shranjen ponudnik je prisel z druge naprave in uporabnik tu se ni vpisal gesla (shrani_ponudnika oznako zbrise).
    Tak zapis ne gre naprej v ozji krog te naprave: ozji krog je na vsaki napravi svoj (kot viri, pregled 51 E4)."""
    d = _beri_json(pot_nastavitev)
    return _ponudnik_iz(d) is not None and d.get("iz_kroga") is True


def preveri_shranjenega(pot_nastavitev: str, *, kontekst: Optional[ssl.SSLContext] = None) -> str:
    """»Preveri« za shranjenega ponudnika z geslom iz zbirke (naloga 114): vmesnik gesla nikoli ne dobi nazaj in ga ne
    posilja znova. Ni ponudnika: NapakaPonudnika(NI_PONUDNIKA); ni gesla: NapakaPonudnika(NI_GESLA) - brez omrezja.
    Ostala pravila (glavna nit, TLS, zapah, 1/min, meja racuna) so v preveri_ponudnika."""
    p = preberi_ponudnika(pot_nastavitev)
    if p is None:
        raise NapakaPonudnika(NI_PONUDNIKA)
    _ne_na_glavni_niti()  # pred zbirko: branje zbirke je lahko klic D-Bus, ki caka na odklep
    geslo = _preberi_geslo(p.kljuc_gesla)
    if geslo is None:
        raise NapakaPonudnika(NI_GESLA)
    return preveri_ponudnika(p, geslo, pot_nastavitev=pot_nastavitev, kontekst=kontekst)


def preberi_ponudnika(pot_nastavitev: str) -> Optional[Ponudnik]:
    """Shranjen ponudnik ali None (ni vpisan ali je zapis pokvarjen). Gesla ne bere."""
    return _ponudnik_iz(_beri_json(pot_nastavitev))


def pozabi_ponudnika(pot_nastavitev: str) -> None:
    """Zbrise nastavitev, geslo in trajni zapah racuna (uporabnik je racun odstranil).

    Gesla zbrise tudi, ce je datoteka nastavitev pokvarjena ali tuja: kljuce pozna seznam kljucev (pregled 77 G6)."""
    with _NASTAVITVE_ZAKLEP:
        p = preberi_ponudnika(pot_nastavitev)
        kljuci = _beri_kljuce(pot_nastavitev)
        if p is not None:
            # Pregled 118 N3: odtis pozabljenega racuna - ponudnik z druge naprave v krogu se ne vrne sam.
            odtis = _odtis_pozabljenega(p.gostitelj, p.uporabnik)
            odtisi = [x for x in _pozabljeni(pot_nastavitev) if x != odtis] + [odtis]
            try:
                _pisi_json(_pot_pozabljenih(pot_nastavitev), {"verzija": _VERZIJA, "odtisi": odtisi[-NAJVEC_POZABLJENIH:]})
            except OSError as e:
                _log.info("usenet ponudnik: pozabljenega racuna ni mogoce zapomniti (%s)", type(e).__name__)
            kljuci.add(p.kljuc_gesla)
            geslo = _preberi_geslo(p.kljuc_gesla)
            nntp.dovoli_prijavo_znova(p.gostitelj, p.uporabnik, geslo)  # zapah v procesu in na disku
            with _PREVERBE_ZAKLEP:
                _PREVERBE.pop(_kljuc_racuna(p), None)
        ostali = _pozabi_kljuce(kljuci)
        with _POMNILNIK_ZAKLEP:
            _V_POMNILNIKU.clear()  # gesla samo v pomnilniku ne smejo preziveti »Pozabi«, tudi brez kljuca
        try:
            os.unlink(pot_nastavitev)
        except FileNotFoundError:
            pass
        if ostali:
            _pisi_kljuce(pot_nastavitev, ostali)  # zbirka ni zbrisala: naslednji »Pozabi« poskusi znova
        else:
            try:
                os.unlink(_pot_kljucev(pot_nastavitev))
            except FileNotFoundError:
                pass


def _zapisi_preverbo(pot_nastavitev: str, ponudnik: Ponudnik, izid: str) -> None:
    with _NASTAVITVE_ZAKLEP:  # branje in pisanje skupaj: socasen nov vpis ne sme biti povozen (G5)
        d = _beri_json(pot_nastavitev)
        p = _ponudnik_iz(d)
        if d is None or p is None or p.kljuc_gesla != ponudnik.kljuc_gesla:
            return  # medtem zamenjan ponudnik: izid ne velja zanj
        d["preverba"] = {"izid": izid, "cas": int(time.time())}
        try:
            _pisi_json(pot_nastavitev, d)
        except OSError as e:
            _log.info("usenet ponudnik: izida ni mogoce shraniti (%s)", type(e).__name__)


# ------------------------------------------------------------------ preverba (gumb »Preveri«)

_PREVERBE: dict = {}  # kljuc racuna -> monotonic zadnje preverbe z omrezjem
_PREVERBE_ZAKLEP = threading.Lock()
_ura = time.monotonic  # preizkusi jo zamenjajo


def _kljuc_racuna(p: Ponudnik) -> str:
    # Racun pri ponudniku (kot vrata prijave v usenet_nntp): drugo ime streznika ne da nove preverbe.
    return hashlib.sha256(("%s\x00%s" % (nntp.ponudnik(p.gostitelj), p.uporabnik)).encode("utf-8")).hexdigest()


def _rezerviraj_preverbo(p: Ponudnik) -> bool:
    """Pod zaklepom: dva hkratna klika ne odpreta dveh povezav."""
    zdaj = _ura()
    k = _kljuc_racuna(p)
    with _PREVERBE_ZAKLEP:
        zadnja = _PREVERBE.get(k)
        if zadnja is not None and zdaj - zadnja < PREVERBA_NA_S:
            return False
        _PREVERBE[k] = zdaj
        for x in [x for x, t in _PREVERBE.items() if zdaj - t >= PREVERBA_NA_S and x != k]:
            del _PREVERBE[x]  # omejena velikost
    return True


def _ne_na_glavni_niti() -> None:
    if threading.current_thread() is threading.main_thread():
        raise RuntimeError("usenet ponudnik: omrezje ni dovoljeno na glavni niti")


def _samo_tls(p: Ponudnik) -> None:
    if not p.tls:
        raise NapakaPonudnika(BREZ_TLS)  # usenet_nntp zna samo TLS - brez omrezja


def preveri_ponudnika(ponudnik: Ponudnik, geslo: str, *, pot_nastavitev: Optional[str] = None,
                      kontekst: Optional[ssl.SSLContext] = None) -> str:
    """ENA povezava, ena prijava, QUIT. Samo na uporabnikov klik, nikoli na glavni niti ali v ozadju.

    Izid: VELJA, NE_VELJA, ZAKLENJEN, NI_ODGOVORA, PREVEC_POVEZAV ali PREPOGOSTO (manj kot minuta od zadnje).
    Zapah racuna NE odklene (to naredi samo nov vpis): po NE_VELJA je naslednja preverba ZAKLENJEN brez omrezja."""
    if not isinstance(ponudnik, Ponudnik):
        raise ValueError("usenet ponudnik: pricakovan Ponudnik")
    if not nntp.varna_poverilnica(geslo):
        raise ValueError("usenet ponudnik: neveljavno geslo")
    _ne_na_glavni_niti()
    _samo_tls(ponudnik)
    kontekst = nntp.varen_kontekst(kontekst)  # brez preverbe potrdila: ValueError pred omrezjem
    if (nntp.prijava_zavrnjena(ponudnik.gostitelj, ponudnik.uporabnik, geslo)
            or _znano_zavrnjeno(ponudnik, geslo, pot_nastavitev)):  # tudi ko zapah usenet_nntp vmes izgine, G1
        izid = ZAKLENJEN
    elif not _zacni_preverbo(ponudnik):
        # Zivi bazen racuna ima vse povezave do trde meje; preverba bi odprla eno cez (pregled 77 G4).
        # Minuta se ne porabi, ker gesla nismo poslali.
        _log.info("usenet ponudnik: preverba %s", V_UPORABI)
        return V_UPORABI
    else:
        try:
            if not _rezerviraj_preverbo(ponudnik):
                return PREPOGOSTO
            izid = _preveri_z_omrezjem(ponudnik, geslo, kontekst, pot_nastavitev)
        finally:
            _koncaj_preverbo(ponudnik)
    _log.info("usenet ponudnik: preverba %s", izid)  # samo izid
    if pot_nastavitev is not None and izid in (VELJA, NE_VELJA, ZAKLENJEN):
        _zapisi_preverbo(pot_nastavitev, ponudnik, izid)
    return izid


def _preveri_z_omrezjem(p: Ponudnik, geslo: str, kontekst: ssl.SSLContext, pot_nastavitev: Optional[str]) -> str:
    # Bazen z eno povezavo da samo obstojeca pravila (vrata prijave, zapah, ustavitev drugih bazenov racuna);
    # povezavo odpremo sami, ker Bazen._izvedi po napaki omrezja odpre drugo (spec: ENA povezava).
    bazen = nntp.Bazen(p.gostitelj, p.vrata, p.uporabnik, geslo, povezav=1, kontekst=kontekst)
    pov = nntp.Povezava(p.gostitelj, p.vrata, p.uporabnik, geslo, kontekst,
                        pred_prijavo=bazen._pred_prijavo, po_prijavi=bazen._po_prijavi)
    try:
        pov.odpri()
        return VELJA
    except nntp.NapakaNntp as e:
        return _izid_napake(bazen, p, geslo, e, pov.faza, pot_nastavitev)
    finally:
        pov.zapri(vljudno=True)  # QUIT
        bazen.zapri()


def _izid_napake(bazen: "nntp.Bazen", p: Ponudnik, geslo: str, e: "nntp.NapakaNntp", faza: str,
                 pot_nastavitev: Optional[str] = None) -> str:
    if e.izid == nntp.ZASEDEN or (faza == nntp.FAZA_POVEZAVA and e.izid == nntp.DOSTOP):
        return PREVEC_POVEZAV  # 502 v pozdravu ali jasno besedilo o meji; geslo ni zavrnjeno
    if faza == nntp.FAZA_PRIJAVA:
        # _po_prijavi je izid ze zapisal (zapah ali stevec neznanih prijav) pred sprostitvijo vrat prijave.
        if nntp.prijava_zavrnjena(p.gostitelj, p.uporabnik, geslo):
            if e.izid == nntp.PRIJAVA:
                _zapomni_zavrnjeno(p, geslo, pot_nastavitev)  # ponovni vpis istega gesla ga ne odklene (G1)
            bazen._ustavi(nntp.PRIJAVA, racun=True)  # ustavi tudi zive bazene istega racuna (Grok 43 C3)
            return NE_VELJA if e.izid == nntp.PRIJAVA else ZAKLENJEN
        return NI_ODGOVORA  # geslo je morda prislo do streznika, odgovora ni (prvic: brez zapaha)
    if nntp.prijava_zavrnjena(p.gostitelj, p.uporabnik, geslo):
        return ZAKLENJEN  # zapah je medtem postavil drug bazen; geslo ni bilo poslano
    return NI_ODGOVORA  # omrezje, TLS, rok, tuj pozdrav


# ------------------------------------------------------------------ bazen za predvajanje

# Trda meja povezav velja na RACUN (lastnik), zato en zivi bazen na racun: drugi ustvari_bazen dobi istega, preverba
# pa med predvajanjem ne odpre dodatne povezave (pregled 77 G4). Sibka referenca: bazena, ki ga nihce vec ne drzi,
# register ne ohranja pri zivljenju.
_RACUNI: dict = {}  # kljuc racuna -> {"bazen": weakref ali None, "preverbe": stevilo tekocih preverb}
_RACUNI_ZAKLEP = threading.RLock()  # RLock: zapri() starega bazena se odjavi pod istim zaklepom


def _racun(k: str) -> dict:
    return _RACUNI.setdefault(k, {"bazen": None, "preverbe": 0})


def _zivi_bazen(r: Optional[dict]):
    b = r["bazen"]() if r is not None and r["bazen"] is not None else None
    return b if b is not None and not b._zaprt else None


def _pospravi(k: str) -> None:
    r = _RACUNI.get(k)
    if r is not None and r["preverbe"] <= 0 and _zivi_bazen(r) is None:
        del _RACUNI[k]  # omejena velikost


def _povezav_bazena(b) -> int:
    """Vse povezave bazena (proste, v rabi in v odpiranju) - kot jih steje Bazen sam (sme_odpreti)."""
    with b._pogoj:
        return len(b._proste) + len(b._v_rabi)


def _zacni_preverbo(p: Ponudnik) -> bool:
    """Preverba zasede eno povezavo racuna. Zivi bazen najprej odstopi eno mesto (meja - 1, odvecne proste povezave
    zapre); False samo, ce ima bazen se vedno vec povezav (vse v rabi) - takrat bi preverba presegla trdo mejo.

    Naloga 116: prej je bil vsak zivi bazen razlog za V_UPORABI, tudi brez ene same odprte povezave. Tako uporabnik z
    odprtim, a nedejavnim predvajalnikom ni mogel preveriti gesla, zapah po zavrnjeni prijavi pa ni ustavil zivega
    bazena (lastnikov test_zapah_ustavi_ziv_bazen_racuna, Grok 43 C3)."""
    k = _kljuc_racuna(p)
    with _RACUNI_ZAKLEP:
        r = _racun(k)
        b = _zivi_bazen(r)
        if b is not None:
            meja = b._meja_polna - r["preverbe"] - 1
            if meja < 1:
                return False  # bazen mora obdrzati vsaj eno povezavo, preverba je ne sme vzeti
            b._nastavi_mejo(meja)  # od tu bazen ne odpre vec kot [meja]; odvecne proste zapre
            if _povezav_bazena(b) > meja:
                b._nastavi_mejo(meja + 1)  # vse v rabi: mesto nazaj, preverba ne gre
                return False
        r["preverbe"] += 1
        return True


def _koncaj_preverbo(p: Ponudnik) -> None:
    k = _kljuc_racuna(p)
    with _RACUNI_ZAKLEP:
        r = _RACUNI.get(k)
        if r is None:
            return
        r["preverbe"] = max(0, r["preverbe"] - 1)
        b = _zivi_bazen(r)
        if b is not None:
            b._nastavi_mejo(b._meja_polna - r["preverbe"])  # bazen, ustvarjen med preverbo, dobi povezavo nazaj
        _pospravi(k)


def _nastavi_mejo_racuna(p: Ponudnik) -> None:
    with _RACUNI_ZAKLEP:
        r = _RACUNI.get(_kljuc_racuna(p))
        b = _zivi_bazen(r)
        if b is not None:
            b._meja_polna = min(p.najvec_povezav, nntp.NAJVEC_POVEZAV)
            b._nastavi_mejo(b._meja_polna - r["preverbe"])


class _BazenRacuna(nntp.Bazen):
    """Bazen s trdo mejo racuna: tudi nastavi_najvec od zunaj ne gre cez uporabnikovo stevilo povezav."""

    def __init__(self, *a, meja_racuna: int, meja_polna: Optional[int] = None, kljuc_racuna: str = "",
                 podpis: str = "", **k):
        self._meja_racuna = max(1, int(meja_racuna))
        self._meja_polna = max(self._meja_racuna, int(meja_polna or meja_racuna))
        self._kljuc_racuna = kljuc_racuna
        self._podpis = podpis  # HMAC (streznik, vrata, geslo): primerjava brez hranjenja gesla tu
        self._zaprt = False
        super().__init__(*a, **k)

    def nastavi_najvec(self, povezav: int) -> None:
        super().nastavi_najvec(min(int(povezav), self._meja_racuna))

    def _nastavi_mejo(self, meja: int) -> None:
        self._meja_racuna = max(1, int(meja))
        super().nastavi_najvec(self._meja_racuna)

    def zapri(self, *a, **k):
        try:
            return super().zapri(*a, **k)
        finally:
            self._zaprt = True  # zaprt bazen ne zaseda vec racuna
            with _RACUNI_ZAKLEP:
                r = _RACUNI.get(self._kljuc_racuna)
                if r is not None and r["bazen"] is not None and r["bazen"]() is self:
                    r["bazen"] = None
                _pospravi(self._kljuc_racuna)


def ustvari_bazen(ponudnik: Ponudnik, *, kontekst: Optional[ssl.SSLContext] = None) -> "nntp.Bazen":
    """Bazen za predvajanje (povezave odpira sele zahteva). Geslo iz zbirke sele tu; brez gesla ali z zapahom
    NapakaPonudnika brez omrezja - Bazen bi sicer obstajal, a vsaka zahteva bi koncala z napako.

    Za isti racun vrne obstojeci zivi bazen (trda meja na racun); kdor ga zapre, ga zapre za vse. Med tekoco
    preverbo dobi bazen eno povezavo manj in jo dobi nazaj, ko se preverba konca."""
    if not isinstance(ponudnik, Ponudnik):
        raise ValueError("usenet ponudnik: pricakovan Ponudnik")
    _samo_tls(ponudnik)
    # Kot pri preverbi: CERT_NONE ali brez preverbe imena je ValueError pred zbirko in omrezjem (pregled 77 G3).
    kontekst = nntp.varen_kontekst(kontekst)
    geslo = _preberi_geslo(ponudnik.kljuc_gesla)
    if geslo is None:
        raise NapakaPonudnika(NI_GESLA)
    if nntp.prijava_zavrnjena(ponudnik.gostitelj, ponudnik.uporabnik, geslo):
        raise NapakaPonudnika(RACUN_ZAKLENJEN)
    meja = min(ponudnik.najvec_povezav, nntp.NAJVEC_POVEZAV)
    k = _kljuc_racuna(ponudnik)
    podpis = _odtis_gesla(ponudnik, "%s\x00%d\x00%s" % (ponudnik.gostitelj.lower(), ponudnik.vrata, geslo))
    with _RACUNI_ZAKLEP:
        b = _zivi_bazen(_racun(k))
        if b is not None and b._podpis == podpis:
            b._meja_polna = meja
            b._nastavi_mejo(meja - _racun(k)["preverbe"])
            return b
        if b is not None:
            _racun(k)["bazen"] = None
            b.zapri()  # drugo geslo ali streznik istega racuna: stari bazen ne sme teci poleg novega
        r = _racun(k)  # zapri() je lahko pospravil vnos
        prosto = meja - r["preverbe"]
        if prosto < 1:
            _pospravi(k)
            raise NapakaPonudnika(PREVERBA_TECE)
        novi = _BazenRacuna(ponudnik.gostitelj, ponudnik.vrata, ponudnik.uporabnik, geslo, povezav=prosto,
                            kontekst=kontekst, meja_racuna=prosto, meja_polna=meja, kljuc_racuna=k, podpis=podpis)
        r["bazen"] = weakref.ref(novi)
        return novi


# ------------------------------------------------------------------ vmesnik

_BESEDILA = {
    None: "Usenet se pokaže, ko v nastavitvah vpišeš svojega ponudnika NNTP.",
    NEPREVERJEN: "Ponudnik je shranjen. Klikni »Preveri«, če želiš preizkusiti prijavo.",
    NI_GESLA: "Geslo za ponudnika ni shranjeno. Vpiši ga znova v nastavitvah Useneta.",
    VELJA: "Prijava pri ponudniku deluje.",
    NE_VELJA: "Ponudnik je zavrnil prijavo. Preveri uporabniško ime in geslo in ju vpiši znova - "
              "do takrat Safeer gesla ne pošilja (zaščita pred zaklepom računa).",
    ZAKLENJEN: "Prijava je bila zavrnjena, zato Safeer gesla ne pošilja več. Ko poverilnice preveriš pri "
               "ponudniku, jih vpiši znova.",
}


#: Besedila za izide in razloge ob kliku (niso trajno stanje). Brez gesla, uporabnika in gostitelja.
BESEDILA_IZIDOV = {
    GESLO_ZAVRNJENO: "Ponudnik je to geslo že zavrnil. Vpiši drugo geslo - Safeer istega gesla ne pošlje znova "
                     "(zaščita pred zaklepom računa).",
    V_UPORABI: "Račun se trenutno uporablja za predvajanje. Preveri znova, ko se predvajanje konča - dodatna "
               "povezava bi presegla mejo povezav računa.",
    PREVERBA_TECE: "Preverba prijave še teče. Poskusi znova čez nekaj sekund.",
    NI_PONUDNIKA: _BESEDILA[None],
}


def stanje_za_vmesnik(pot_nastavitev: str) -> dict:
    """Stanje za nastavitve in prikaz Useneta - brez gesla in uporabnika. Usenet je viden samo z vpisanim ponudnikom.

    Bere geslo iz zbirke samo za preverbo zapaha (odtis vsebuje geslo); brez omrezja."""
    d = _beri_json(pot_nastavitev)
    p = _ponudnik_iz(d)
    if p is None:
        return {"vpisan": False, "usenet_viden": False, "ime": None, "gostitelj": None, "vrata": None,
                "tls": None, "najvec_povezav": None, "geslo_shranjeno": False, "stanje": None,
                "besedilo": _BESEDILA[None]}
    pr = d.get("preverba") if isinstance(d.get("preverba"), dict) else {}
    zadnji = pr.get("izid") if pr.get("izid") in (VELJA, NE_VELJA, ZAKLENJEN) else None
    geslo = _preberi_geslo(p.kljuc_gesla)
    if geslo is not None and nntp.prijava_zavrnjena(p.gostitelj, p.uporabnik, geslo):
        stanje = NE_VELJA if zadnji == NE_VELJA else ZAKLENJEN  # zapah ima prednost pred staro VELJA
    elif zadnji == VELJA:
        stanje = VELJA
    else:
        stanje = NEPREVERJEN
    besedilo = _BESEDILA[NI_GESLA] if geslo is None and stanje == NEPREVERJEN else _BESEDILA[stanje]
    return {"vpisan": True, "usenet_viden": True, "ime": p.ime, "gostitelj": p.gostitelj, "vrata": p.vrata,
            "tls": p.tls, "najvec_povezav": p.najvec_povezav, "geslo_shranjeno": geslo is not None,
            "stanje": stanje, "besedilo": besedilo}
