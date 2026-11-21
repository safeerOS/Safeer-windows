"""Samodejno usklajevanje kljucev in dodatkov v ozjem krogu (secrets.sync) - ciste odlocitve.

Lastnik, 25. 10. 2026: kljuce in dodatke vneses enkrat (npr. na telefonu), veljajo na vseh napravah ozjega kroga.
Protokol je Androidov (UskladitevKljucevPravila.kt, veja zaganjalnik-beta-k42) - namizje ga mora govoriti bit za bitom
enako (outputs/nacrti/uskladitev-kljucev.md): debrid kljuci, indeksator Usenet, dodatki s poverilnico in ponudnik Usenet
(NNTP) gredo po sifrirani poti od naprave do naprave (Link, dejanje `secrets.sync`) samo napravam v ozjem krogu TE
naprave. Vrednosti nikoli v dnevnik.

Zapis = kljuc + cas spremembe (ms) + izvor (id naprave, ki je spremenila) + izbrisan (grob). Velja novejsi po (cas,
izvor, izbrisan) - vse naprave pridejo do istega stanja ne glede na vrstni red sporocil. Potrditev enkrat na NOVO
napravo na obeh straneh; povabilo nese samo imena kljucev; posljemo samo lastne zapise; prejmemo samo zapise, katerih
izvor je posiljatelj sam. Preizkus: tests/test_uskladitev_kljucev_pravila.py (scenariji Androidovega preizkusa).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

DEJANJE = "secrets.sync"
ZMOZNOST = "secrets"
VERZIJA = 1
NAJVEC_ZAPISOV = 64
#: Cas zapisa za vrednost, ki je obstajala pred tem usklajevanjem (»uvoz«): vsaka kasnejsa sprememba jo preglasi.
CAS_UVOZA = 1
#: Cas iz prihodnosti (napacna ura druge naprave) sprejmemo najvec toliko naprej (pregled U1).
NAJVEC_NAPREJ_MS = 10 * 60 * 1000
#: Prejeto od nepotrjene naprave caka na potrditev najvec toliko (pregled U3, U11).
CAKA_VELJA_MS = 10 * 60 * 1000

PREDPONA_DEBRID = "debrid:"
KLJUC_USENET = "usenet"
PREDPONA_DODATKA = "dodatek:"
#: Vir z racunom IPTV (Android od 26. 10. 2026). Namizje ga se ne usklajuje: kljuc pozna (ni »neznan«), a ga ne sprejme.
PREDPONA_IPTV = "iptv:"
#: »Vedno dovoli« za deljenje zaslona (Android naloga 42 D). Namizje ga ne usklajuje (ni sprejeto).
PREDPONA_ZAUPANJA = "zaupanje:"
#: Ponudnik Usenet (NNTP): JSON {"ponudnik": {...}, "geslo": "..."} (Android naloga 42 G).
KLJUC_USENET_PONUDNIK = "usenet_ponudnik"

_RX_ODTIS = re.compile(r"^[0-9a-f]{16}$")

POVABLJENA, POTRJENA, CAKA, ZAVRNJENA, STARA = "POVABLJENA", "POTRJENA", "CAKA", "ZAVRNJENA", "STARA"
STANJA = (POVABLJENA, POTRJENA, CAKA, ZAVRNJENA, STARA)
SPREJMI, VPRASAJ, ZAVRNI = "SPREJMI", "VPRASAJ", "ZAVRNI"
VREDNOST, NEZNAN, BREZ = "VREDNOST", "NEZNAN", "BREZ"


def kljuc_debrid(ponudnik: str) -> str:
    return PREDPONA_DEBRID + ponudnik


def kljuc_dodatka(odtis: str) -> str:
    return PREDPONA_DODATKA + odtis


def veljaven_kljuc(k: str, ponudniki: Iterable[str], zaupanje: bool = False, iptv: bool = False) -> bool:
    """Kljuc, ki ga ta naprava zna. Namizje privzeto ne usklajuje zaupanja zaslona in virov IPTV (`zaupanje`, `iptv`):
    taki zapisi se prezrejo, kot pri starejsi razlicici Androida."""
    k = str(k or "")
    if k.startswith(PREDPONA_DEBRID):
        return k[len(PREDPONA_DEBRID):] in set(ponudniki)
    if k in (KLJUC_USENET, KLJUC_USENET_PONUDNIK):
        return True
    if k.startswith(PREDPONA_DODATKA):
        return bool(_RX_ODTIS.match(k[len(PREDPONA_DODATKA):]))
    if k.startswith(PREDPONA_IPTV):
        return iptv and bool(_RX_ODTIS.match(k[len(PREDPONA_IPTV):]))
    if k.startswith(PREDPONA_ZAUPANJA):
        return zaupanje
    return False


@dataclass(frozen=True)
class Meta:
    """Stanje kljuca na tej napravi (brez vrednosti); `odtis` = lokalni odtis vrednosti, "" pri grobu."""
    cas: int
    izvor: str
    izbrisan: bool
    odtis: str


@dataclass(frozen=True)
class Zapis:
    """Zapis v sporocilu; `vrednost` samo, ce ni izbrisan in je prejemnik potrjen. `gostitelj`: pri dodatku (za okno
    potrditve), tudi v povabilu brez vrednosti."""
    kljuc: str
    cas: int
    izvor: str
    izbrisan: bool
    vrednost: str
    gostitelj: str = ""


def novejsi(cas: int, izvor: str, izbrisan: bool, star: Optional[Meta]) -> bool:
    if star is None:
        return True
    if cas != star.cas:
        return cas > star.cas
    if izvor != star.izvor:
        return izvor > star.izvor
    return izbrisan and not star.izbrisan


def nov_cas(ura: int, prejsnji: int) -> int:
    return max(ura, prejsnji + 1)


def lokalne_spremembe(meta: Dict[str, Meta], trenutni: Dict[str, str], neznani: Set[str], jaz: str, ura: int,
                      uvoz: bool) -> Dict[str, Meta]:
    """Lastne spremembe: `trenutni` = kljuc -> odtis trenutne vrednosti, `neznani` = kljuci, ki jih ta hip ni mogoce
    prebrati (zbirka zaklenjena) - zanje ni ne spremembe ne groba. `uvoz` = prvi zagon: obstojece dobijo CAS_UVOZA."""
    izid: Dict[str, Meta] = {}
    for k, odtis in trenutni.items():
        if k in neznani:
            continue
        m = meta.get(k)
        if m is None:
            izid[k] = Meta(CAS_UVOZA if uvoz else ura, jaz, False, odtis)
        elif m.izbrisan or m.odtis != odtis:
            izid[k] = Meta(nov_cas(ura, m.cas), jaz, False, odtis)
    for k, m in meta.items():
        if k in trenutni or k in neznani or m.izbrisan:
            continue
        izid[k] = Meta(nov_cas(ura, m.cas), jaz, True, "")
    return izid


def oddaja(prebran: bool, shranjen: bool, velja: bool) -> str:
    """Z vrednostjo gre samo kljuc, ki ga je storitev potrdila; shranjen, a nepreverjen ali neberljiv je neznan."""
    if prebran and velja:
        return VREDNOST
    if prebran or shranjen:
        return NEZNAN
    return BREZ


def izbris_v_krog(velja: bool) -> bool:
    """Izbris gre drugim napravam samo, ce je kljuc TU veljal (Grok 33, F1)."""
    return velja


def po_odstranitvi(meta: Dict[str, Meta], kljuc: str, v_krog: bool) -> Dict[str, Meta]:
    if v_krog or (meta.get(kljuc) is None or meta[kljuc].izbrisan):
        return meta
    return {k: v for k, v in meta.items() if k != kljuc}


def veljaven_zapis(z: Zapis, ura: int, ponudniki: Iterable[str], veljavna_vrednost: Callable[[str, str], bool],
                   **znani) -> bool:
    if not veljaven_kljuc(z.kljuc, ponudniki, **znani):
        return False
    if not isinstance(z.cas, int) or isinstance(z.cas, bool) or z.cas < CAS_UVOZA or z.cas > ura + NAJVEC_NAPREJ_MS:
        return False
    if not z.izvor or not z.izvor.strip() or len(z.izvor) > 128 or any(c < " " for c in z.izvor):
        return False
    if z.izbrisan:
        return z.vrednost == ""
    if not z.vrednost or len(z.vrednost) > 4096 or any(c < " " and c != "\n" for c in z.vrednost):
        return False
    try:
        return bool(veljavna_vrednost(z.kljuc, z.vrednost))
    except Exception:  # noqa: BLE001 - preverba vrednosti ne sme podreti prejema
        return False


def za_uporabo(meta: Dict[str, Meta], prejeti: Sequence[Zapis], ura: int, ponudniki: Iterable[str],
               veljavna_vrednost: Callable[[str, str], bool], izvor_dovoljen: Callable[[str], bool], **znani) -> List[Zapis]:
    """Prejeti zapisi -> tisti, ki jih je treba uporabiti tu (novejsi od lokalnih); najvec NAJVEC_ZAPISOV; za isti kljuc
    velja najnovejsi; izvor mora biti posiljatelj sam (pregled U1)."""
    ponudniki = set(ponudniki)
    najnovejsi: Dict[str, Zapis] = {}
    for z in list(prejeti)[:NAJVEC_ZAPISOV]:
        if not veljaven_zapis(z, ura, ponudniki, veljavna_vrednost, **znani):
            continue
        try:
            dovoljen = bool(izvor_dovoljen(z.izvor))
        except Exception:  # noqa: BLE001
            dovoljen = False
        if not dovoljen:
            continue
        prej = najnovejsi.get(z.kljuc)
        if prej is None or novejsi(z.cas, z.izvor, z.izbrisan, Meta(prej.cas, prej.izvor, prej.izbrisan, "")):
            najnovejsi[z.kljuc] = z
    return [z for z in najnovejsi.values() if novejsi(z.cas, z.izvor, z.izbrisan, meta.get(z.kljuc))]


def se_vedno_novejsi(meta: Dict[str, Meta], zapisi: Sequence[Zapis]) -> List[Zapis]:
    return [z for z in zapisi if novejsi(z.cas, z.izvor, z.izbrisan, meta.get(z.kljuc))]


def za_poslati(meta: Dict[str, Meta], vrednosti: Dict[str, str], jaz: str) -> List[Zapis]:
    """Samo LASTNI zapisi (izvor `jaz`, pregled U2) z vrednostmi; brez vrednosti izpadejo, grob ostane."""
    izid: List[Zapis] = []
    if not jaz or not jaz.strip():
        return izid
    for k, m in meta.items():
        if m.izvor != jaz:
            continue
        if m.izbrisan:
            izid.append(Zapis(k, m.cas, m.izvor, True, ""))
        elif k in vrednosti:
            izid.append(Zapis(k, m.cas, m.izvor, False, vrednosti[k]))
    return izid[:NAJVEC_ZAPISOV]


def vrednost_za_odtis(prejeta: str, prebrana: Optional[str]) -> str:
    """Odtis prejetega zapisa iz vrednosti, kot jo ta naprava po shranitvi PREBERE (pregled 96, V1)."""
    return prebrana if prebrana is not None else prejeta


def za_povabilo(zapisi: Sequence[Zapis]) -> List[Zapis]:
    return [replace(z, vrednost="") for z in zapisi]


def vrednosti_za(stanje: Optional[str]) -> bool:
    # Lastnik 9. 11. 2026 (kot Android): naprava v ozjem krogu TE naprave je ze potrjena - dodal jo je uporabnik sam; kar dovoli
    # na eni svoji napravi, velja na vseh brez ponovne potrditve (27. 10. 2026). Samo zavrnjena ne dobi vrednosti.
    return stanje != ZAVRNJENA


def izvor_posiljatelja(izvor_naprava: str, od_naprava: str) -> bool:
    return bool(izvor_naprava) and bool(izvor_naprava.strip()) and izvor_naprava == od_naprava


def caka_velja(prejeto: int, zdaj: int) -> bool:
    return 0 <= zdaj - prejeto < CAKA_VELJA_MS


def brez_neberljivih(zapisi: Sequence[Zapis], neberljivi: Set[str]) -> List[Zapis]:
    return [z for z in zapisi if z.kljuc not in neberljivi]


def zdruzi_spremembi(stari_kljuci: Sequence[str], stare_prejsnje: Dict[str, Optional[str]], novi_kljuci: Sequence[str],
                     nove_prejsnje: Dict[str, Optional[str]]) -> Tuple[List[str], Dict[str, Optional[str]]]:
    kljuci: List[str] = []
    for k in list(stari_kljuci) + list(novi_kljuci):
        if k not in kljuci:
            kljuci.append(k)
    vrednosti = {k: (stare_prejsnje.get(k) if k in stari_kljuci else nove_prejsnje.get(k)) for k in kljuci}
    return kljuci, vrednosti


def prehod_koncan(obstojeci: Set[str], neberljivi: Set[str]) -> bool:
    return not any(k in neberljivi for k in obstojeci)


def samo_ime_gostitelja(g: str) -> str:
    return "".join(c for c in str(g or "").lower() if ("a" <= c <= "z") or ("0" <= c <= "9") or c in ".-")[:253]


def prikaz_gostitelja(vrednost: str, trditev: str, iz_vrednosti: str) -> str:
    return iz_vrednosti if (vrednost.strip() and iz_vrednosti.strip()) else samo_ime_gostitelja(trditev)


def zamenjave(meta: Dict[str, Meta], uporabljeni: Sequence[Zapis]) -> List[Zapis]:
    return [z for z in uporabljeni if meta.get(z.kljuc) is not None and not meta[z.kljuc].izbrisan]


def sprejem(vklopljeno: bool, v_krogu: bool, stanje: Optional[str]) -> str:
    if not vklopljeno or not v_krogu:
        return ZAVRNI
    if stanje == ZAVRNJENA:
        return ZAVRNI
    # Lastnik 9. 11. 2026: ozji krog je potrditev; prejsnji »potrdi tukaj« (CAKA) velja kot potrjen.
    return SPREJMI


def sme_poslati(vklopljeno: bool, v_krogu: bool, zascita: bool, povezan: bool, zmoznost: bool,
                stanje: Optional[str]) -> bool:
    return (vklopljeno and v_krogu and zascita and povezan and zmoznost
            and stanje != ZAVRNJENA)


# ------------------------------------------------------------------ sporocilo (JSON kot na Androidu)
def v_json(zapisi: Sequence[Zapis]) -> List[dict]:
    izid = []
    for z in zapisi:
        d = {"k": z.kljuc, "c": z.cas, "i": z.izvor, "d": z.izbrisan}
        if not z.izbrisan and z.vrednost:
            d["v"] = z.vrednost
        if z.gostitelj.strip():
            d["g"] = z.gostitelj
        izid.append(d)
    return izid


def _int(v) -> int:
    if isinstance(v, bool):
        return 0
    if isinstance(v, int):
        return v
    try:
        return int(str(v))
    except (TypeError, ValueError):
        return 0


def iz_json(a) -> List[Zapis]:
    if not isinstance(a, list):
        return []
    izid = []
    for o in a[:NAJVEC_ZAPISOV]:
        if not isinstance(o, dict):
            continue
        izbrisan = o.get("d") is True
        izid.append(Zapis(str(o.get("k") or ""), _int(o.get("c")), str(o.get("i") or ""), izbrisan,
                          "" if izbrisan else str(o.get("v") or ""), samo_ime_gostitelja(str(o.get("g") or ""))))
    return izid


# ------------------------------------------------------------------ dnevnik in razlog za vmesnik
def kratek_id(ident: str) -> str:
    """ID naprave za dnevnik: prva 2 in zadnji 4 znaki (kot core/link_dostop.py, »naprava %s…%s«). Kratek ID se ne
    pokaze cel - tudi deloma bi bil cel ID, zato samo »…«."""
    s = str(ident or "")
    return s[:2] + "…" + s[-4:] if len(s) > 8 else "…"


#: Izid zadnje izmenjave z napravo v ozjem krogu (samo v pomnilniku; vir za razlog_brez_kljucev).
IZID_SPREJETO, IZID_ZAVRNJENO, IZID_CAKA, IZID_NEDOSEGLJIVO, IZID_STARA = (
    "sprejeto", "zavrnjeno", "caka", "nedosegljivo", "stara")

RAZLOG_NI_NAPRAV, RAZLOG_NEDOSEGLJIVE, RAZLOG_BREZ_KLJUCEV, RAZLOG_CAKA, RAZLOG_V_REDU = (
    "ni_naprav_v_krogu", "naprave_niso_dosegljive", "naprave_nimajo_kljucev", "caka_potrditev", "v_redu")
RAZLOGI = (RAZLOG_NI_NAPRAV, RAZLOG_NEDOSEGLJIVE, RAZLOG_BREZ_KLJUCEV, RAZLOG_CAKA, RAZLOG_V_REDU)

#: Besedila za vmesnik (vse jezike, ki jih ima Safeer OS); kratko, brez tehnicnih izrazov. Izrazi za ozji krog so isti
#: kot v core/link_dostop.py (»ozji krog«, »engen Kreis«, »círculo de confianza«, »cercle de confiance«, »cerchia ristretta«).
BESEDILA_RAZLOGA: Dict[str, Dict[str, str]] = {
    RAZLOG_NI_NAPRAV: {
        "sl": "V ožjem krogu ni nobene druge naprave.",
        "en": "There is no other device in your inner circle.",
        "de": "In deinem engen Kreis ist kein anderes Gerät.",
        "es": "No hay ningún otro dispositivo en tu círculo de confianza.",
        "fr": "Aucun autre appareil dans ton cercle de confiance.",
        "it": "Nella tua cerchia ristretta non c'è nessun altro dispositivo.",
    },
    RAZLOG_NEDOSEGLJIVE: {
        "sl": "Naprave v ožjem krogu trenutno niso dosegljive.",
        "en": "The devices in your inner circle can't be reached right now.",
        "de": "Die Geräte in deinem engen Kreis sind gerade nicht erreichbar.",
        "es": "Los dispositivos de tu círculo de confianza no están disponibles ahora.",
        "fr": "Les appareils de ton cercle de confiance sont injoignables pour le moment.",
        "it": "I dispositivi della tua cerchia ristretta non sono raggiungibili ora.",
    },
    RAZLOG_BREZ_KLJUCEV: {
        "sl": "Nobena naprava v ožjem krogu nima ključev.",
        "en": "No device in your inner circle has keys.",
        "de": "Kein Gerät in deinem engen Kreis hat Schlüssel.",
        "es": "Ningún dispositivo de tu círculo de confianza tiene claves.",
        "fr": "Aucun appareil de ton cercle de confiance n'a de clés.",
        "it": "Nessun dispositivo della tua cerchia ristretta ha chiavi.",
    },
    RAZLOG_CAKA: {
        "sl": "Uskladitev ključev čaka na potrditev.",
        "en": "Key sync is waiting for confirmation.",
        "de": "Der Schlüsselabgleich wartet auf Bestätigung.",
        "es": "La sincronización de claves espera una confirmación.",
        "fr": "La synchronisation des clés attend une confirmation.",
        "it": "La sincronizzazione delle chiavi attende una conferma.",
    },
    RAZLOG_V_REDU: {
        "sl": "Ključi so usklajeni.",
        "en": "Keys are in sync.",
        "de": "Die Schlüssel sind abgeglichen.",
        "es": "Las claves están sincronizadas.",
        "fr": "Les clés sont synchronisées.",
        "it": "Le chiavi sono sincronizzate.",
    },
}


def razlog_brez_kljucev(v_krogu: int, potrdile: int, zapisov: int, zadnji_izid: str) -> Tuple[str, Dict[str, str]]:
    """Zakaj (ni) kljucev z drugih naprav - koda in besedila. Izmerjeno 10. 11. 2026 na testnem PC: naprave s kljuci
    niso bile v ozjem krogu, vmesnik pa je bil prazen in brez razlage.

    Vhod so samo podatki o napravah v ozjem krogu TE naprave (klicatelj steje samo te; core/link_dostop odloca o krogu):
    naprava zunaj kroga ne spremeni razloga, zato iz njega ni mogoce sklepati, katere naprave so zunaj.
    `v_krogu`: druge naprave v ozjem krogu; `potrdile`: koliko jih je izmenjavo sprejelo; `zapisov`: koliko zapisov je
    prislo z njih; `zadnji_izid`: IZID_* zadnje izmenjave ("" = se je ni bilo)."""
    if int(v_krogu or 0) <= 0:
        koda = RAZLOG_NI_NAPRAV
    elif zadnji_izid == IZID_CAKA:
        koda = RAZLOG_CAKA
    elif int(potrdile or 0) <= 0:
        koda = RAZLOG_NEDOSEGLJIVE
    elif int(zapisov or 0) <= 0:
        koda = RAZLOG_BREZ_KLJUCEV
    else:
        koda = RAZLOG_V_REDU
    return koda, dict(BESEDILA_RAZLOGA[koda])
