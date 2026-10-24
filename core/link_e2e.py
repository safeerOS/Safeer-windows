"""Safeer Link: zascita ukazov od naprave do naprave (E2E v1). Ista pravila kot cast/E2e.kt na Androidu.

Zakaj. Naprava, ki vsebino hrani, je posiljatelja doslej prepoznala po oznaki, ki jo sporocilu vpise sredisce. Oznaka,
ki je le podobna oznaki druge naprave, je dobila njen dostop (izmerjeno 7. 10. 2026 krajevno); sredisce pa ta sporocila
posreduje nesifrirana in posiljatelja vpise samo - kdor ga gosti, bi jih lahko bral in ponarejal (sledi iz zgradbe).
Tu napravi dokazeta KLJUC: vsaka podpise svoj del dogovora s kljucem naprave, druga ga preveri s kljucem iz SVOJEGA
kroga zaupanja. Dostop se potem veze na ta kljuc, ne na oznako; sredisce vidi samo podpisan dogovor in sifrirane kose.

Prenos. Sporocila potujejo v ze obstojecih `data.offer` / `data.answer` / `data.chunk` / `data.error`, ki jih vsa
sredisca (tudi starejsa) samo posredujejo po polju `target` in tovora ne razlagajo. Namen (`purpose`) je "link".

Dogovor (A zacne, B odgovori):
    data.offer   {session_id, purpose:"link", v:2, from:A, to:B, nonce, epk, ts, sig}
                 sig = podpis A nad  "safeer-link-e2e-offer-v1\\n<session_id>\\n<A>\\n<B>\\n<nonce>\\n<epk>"
    data.answer  {session_id, purpose:"link", v:2, from:B, to:A, offer_nonce, nonce, epk, ts, sig}
                 sig = podpis B nad  "safeer-link-e2e-answer-v1\\n<session_id>\\n<B>\\n<A>\\n<offer_nonce>\\n<nonce>\\n<epk A>\\n<epk B>"
    epk je ENKRATNI javni kljuc P-256 (base64 SPKI DER) - kljuc naprave samo podpisuje (na Androidu drugega ne zna in
    ne sme), skupna skrivnost pa je ECDH med enkratnima kljucema. `ts` je samo za dnevnik: svezost dajeta nonca, zato
    zascita ni odvisna od ure naprav.
    Z = ECDH(enkratni A, enkratni B);  gradivo = HKDF-SHA256(Z, sol = SHA-256(session_id),
        info = "safeer-link-e2e-v1\\n" + nonce A + nonce B + "\\n<A>\\n<B>", 72 bajtov)
        = kljuc A->B (32) | predpona nonca A->B (4) | kljuc B->A (32) | predpona nonca B->A (4)

Sporocilo (v obe smeri, vsaka smer s svojim kljucem in stevcem):
    data.chunk   {session_id, seq, m, i, n, data}
                 data = AES-256-GCM(kljuc smeri, nonce = predpona | seq (8 bajtov), del cistopisa,
                                    aad = "safeer-link-e2e-msg-v1\\n<session_id>\\n<smer>\\n<seq>\\n<m>\\n<i>\\n<n>")
    Cistopis je JSON notranjega sporocila ({type, id, ref_id, payload ...}); dolgo sporocilo gre v vec delih
    (m = stevilka sporocila, i = del, n = stevilo delov). seq mora v vsaki smeri strogo narascati.
    data.error   {session_id, code:"ni_seje", seq}  - prejemnik seje ne pozna (znova se je zagnal). Posiljatelj sejo
                 zavrze, klicatelju javi zavrnitev svezih sporocil in se ob naslednjem sporocilu dogovori znova.
                 Sporocila NE poslje se enkrat: obvestilo ni podpisano, sredisce bi z njim sicer doseglo, da se ze
                 izveden ukaz izvede znova. Vsako notranje sporocilo se sifrira natanko enkrat.
                 {session_id, code:"ni_kljuca"}  - prejemnik ponudbe ne more preveriti, ker posiljatelja nima v svojem
                 krogu: dogovor ne more uspeti, klicatelj izve takoj.

Oblika polj. Polja so v podpisanih bajtih locena z znakom nove vrstice, zato NOBENO polje ne sme vsebovati krmilnega
znaka: oznaka naprave je 1-128 vidnih znakov ASCII (veljavna_oznaka), oznaka seje crke, stevke, `-` in `_`, nonce,
enkratni kljuc in podpis pa standardni base64. To se preveri, PREDEN se karkoli podpise ali preveri. Brez tega je
oznaka s prelomom vrstice iste podpisane bajte razdelila na dva nacina in sredisce je sejo ene naprave prevezalo na
drugo (drugi neodvisni pregled, 7. 10. 2026; krog120/n1-napad.py).
    data.ack     potrditev SREDISCA za nase sporocilo prenosa (ref_id "e2e-..."). Zavrnitev (naprave ni v Linku ...)
                 prevedemo v zavrnitev notranjega sporocila, da klicatelj izve takoj in ne caka na iztek casa; sprejem
                 sporocila (ne ponudbe dogovora) javimo kot sprejem notranjega sporocila.

Ta modul ne pozna sredisca, datotek ali kroga: podpis, preverbo, posiljanje in uro dobi od klicatelja, zato tece v
preizkusih brez omrezja. Kriptografija: cryptography (ECDH, AES-GCM); brez nje zascite ni in `poslji` vrne False -
nesifriranega nadomestka ni.
"""
from __future__ import annotations

import base64
import hashlib
import hmac as _hmac
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

NAMEN = "link"
RAZLICICA = 2
#: Zmoznost, ki jo naprava prijavi srediscu: zna zascito od naprave do naprave.
ZMOZNOST = "e2e1"
#: Sporocila, ki med napravama z zascito nikoli ne gredo nezascitena: ukazi, njihovi odgovori in vse, kar na napravi samo
#: odpre stran ali predvajanje (stran, nadzor predvajanja, »nadaljuj na napravi«). `cast.media` danes ne obdela noben
#: sprejemnik (sredisca ga se usmerjajo); je v naboru, da bo zasciten, ce ga kdaj kdo bo.
ZASCITENI_TIPI = frozenset({"control.command", "control.result", "cast.url", "cast.media", "cast.control",
                            "handoff.request"})
TIPI_PRENOSA = frozenset({"data.offer", "data.answer", "data.chunk", "data.error"})
#: Predpona oznak nasih sporocil prenosa: po njej prepoznamo potrditev sredisca (data.ack) zanje.
PREDPONA_OZNAK = "e2e-"
NAJVEC_IZHODNIH = 1024            # za koliko zadnjih sporocil prenosa (vsak kos posebej) vemo, katero sporocilo nosijo
IZHODNA_VELJAJO_S = 30.0          # potrditev sredisca pride v milisekundah; po tem casu zapis zavrzemo

# Cistopis enega dela. Sredisce na Androidu sprejme sporocilo do 256 KiB in ima za vsako povezavo vrsto 512 KiB: del z
# base64 in ovojnico meri ~64 KiB, sporocilo, ki je doslej slo v enem kosu (do 256 KiB), pa tudi v delih ostane pod vrsto.
DOLZINA_DELA = 48 * 1024
NAJVEC_DELOV = 24                 # najvec ~1,1 MiB za eno notranje sporocilo (vec, kot je slo doslej nezasciteno)
DOGOVOR_CAKA_S = 8.0              # po tem casu brez odgovora se ob naslednjem sporocilu dogovor zacne znova
DOGOVOR_VELJA_S = 60.0            # po tem casu cakajocega dogovora ni vec (pozen odgovor ne ustvari seje)
V_VRSTI_VELJA_S = DOGOVOR_CAKA_S  # sporocilo, ki je na dogovor cakalo dlje, ne gre vec: klicatelj je ze javil napako
NAJVEC_V_VRSTI = 64               # sporocil, ki cakajo na dogovor z eno napravo
# Cakajocih dogovorov hkrati: meja velja za dogovore BREZ sporocila (dokaz kljuca ob seznamu naprav, ki ga pise
# sredisce). Dogovor, na katerega caka sporocilo tega racunalnika, drugega takega ne izrine - stevilske meje zanje ni
# (lastnik, 18. 10. 2026: ukaz tisoc napravam podjetja hkrati); izrine samo ob pomanjkanju pomnilnika (core/link_viri).
NAJVEC_DOGOVOROV = 64
SEJA_VELJA_S = 12 * 3600.0
# Skupna meja sej velja za NEPOTRJENE seje (nastanejo iz prejetih ponudb, ki jih sredisce lahko ponavlja). Potrjenih
# (druga stran je dokazala kljuc iz kroga) ne omejuje stevilka - v krogu s tisoc napravami bi se sicer seje izrinjale
# in vsak ukaz bi zahteval nov dogovor; izpade najstarejsa le ob pomanjkanju pomnilnika (core/link_viri). Meja na
# napravo (NAJVEC_SEJ_NA_NAPRAVO) ostane: naprava izrine samo svoje seje.
NAJVEC_SEJ = 256
#: Pomnilnik nad rezervo (link_viri), ki ga mora imeti racunalnik, da ohrani se eno potrjeno sejo ali dogovor.
POMNILNIK_SEJE = 64 * 1024


def _dovolj_pomnilnika() -> bool:
    """Ali ima racunalnik nad rezervo (core/link_viri) se pomnilnik za eno sejo ali dogovor; brez podatka da."""
    try:
        from core import link_viri
        prostega = link_viri.prostega_pomnilnika()
    except Exception:  # noqa: BLE001 - brez meritve ne izrinjamo
        return True
    return prostega is None or prostega >= POMNILNIK_SEJE
NAJVEC_SEJ_NA_NAPRAVO = 16        # sej z ENO napravo (jedrom, vsi njeni programi): naprava izrine le svoje seje
HRANI_ZADNJIH = 16                # zadnja poslana sporocila: po "ni_seje" jih javimo klicatelju kot zavrnjena
NEPOTRJENA_VELJAJO_S = 5.0        # starejsih ne javljamo: klicatelj je zanje ze dobil odgovor ali iztek casa
NEDOKONCANA_VELJAJO_S = 30.0
NAJVEC_NEDOKONCANIH = 4           # sporocil v vec delih, ki jih ena seja sestavlja hkrati
NAJVEC_OZNAKE = 128               # najdaljsa oznaka naprave v dogovoru
# Pomnilnik za sporocila v vec delih, ki se se sestavljajo. Vsako steje s polno napovedano velikostjo (n delov).
NAJVEC_REZERVIRANO_NA_NAPRAVO_B = 8 * 1024 * 1024     # ena naprava (jedro), cez vse njene seje
NAJVEC_REZERVIRANO_B = 32 * 1024 * 1024               # vse naprave skupaj
BESEDILO_CAS = "Naprava ni odgovorila pravočasno. Poskusi znova."
BESEDILO_NI_POSLANO = "Ukaza ni bilo mogoče poslati."
# Podpisi s kljucem naprave za ENO napravo (jedro, vsi njeni programi) v enem oknu - posebej za ponudbe, ki jih zacnemo
# mi, in posebej za odgovore na prejete ponudbe. Vsak dogovor je podpis: brez meje je seznanjena naprava s ponudbo za
# ponudbo - ali sredisce s ponavljanjem ene same ponudbe - to napravo prisilila v neomejeno podpisovanje (cetrti
# neodvisni pregled, 7. 10. 2026; izmerjeno: 500 ponudb = 500 podpisov). Meja je na napravo: kdor jo izcrpa, zadrzi samo
# dogovore s seboj. Meji sta loceni, da naprava s svojimi ponudbami ne zapre nasih dogovorov z njo, in veljata za PROGRAM,
# ne za upravitelj (glej _PODPISI; peti pregled).
NAJVEC_PODPISOV_NA_NAPRAVO = 32
OKNO_PODPISOV_S = 60.0
NAJVEC_ZAPISOV_PODPISOV = 1024    # za koliko naprav hranimo case zadnjih podpisov
# Po dogovoru, ki ni uspel (ponudba ni sla, sredisce jo je zavrnilo, naprava nas nima v krogu), s to oznako toliko casa
# ne zacnemo novega. Tipka daljinca ob napravi, ki je ni v Linku, je sicer z vsakim ukazom porabila en podpis in po 32
# ukazih zaprla mejo podpisov se za minuto po tem, ko se je naprava vrnila (peti neodvisni pregled, 7. 10. 2026).
NEUSPEL_DOGOVOR_CAKA_S = 3.0
NAJVEC_NEUSPELIH = 256            # za koliko oznak si zapomnimo zadnji neuspeli dogovor
# Sporocila, ki cakajo na dogovor, drzijo pomnilnik: meja v bajtih za eno napravo (jedro) in za vse skupaj.
NAJVEC_CAKAJOCIH_NA_NAPRAVO_B = 4 * 1024 * 1024
NAJVEC_CAKAJOCIH_B = 16 * 1024 * 1024
NAJVEC_OPISA = 128                # najdaljsa oznaka ali tip sporocila, ki si ju zapomnimo za potrditve (glej _opis)
# Zapis enega kosa v base64: najvec toliko znakov (del cistopisa + znacka AES-GCM). Daljsega niti ne dekodiramo.
NAJVEC_ZAPISA_KOSA = 4 * ((DOLZINA_DELA + 16 + 2) // 3)
#: Zavrnitev SREDISCA pride klicatelju s kodo sredisca - razen kadar bi ta pomenila nekaj nasega (»ni bilo poslano«,
#: »seje ni« ...): sredisce, ki kos dostavi in ga nato »zavrne« s tako kodo, klicatelja ne sme prepricati, da ukaz ni
#: sel. Takrat dobi to splosno kodo.
KODA_ZAVRNITVE_SREDISCA = "zavrnjeno"
LASTNE_KODE = frozenset({"cas", "ni_poslano", "ni_seje", "ni_kljuca", "zascita", KODA_ZAVRNITVE_SREDISCA})
NAJVEC_BESEDILA_NAPAKE = 200      # besedila napake sredisca ne podajamo naprej v poljubni dolzini
NAJVEC_KODE_SREDISCA = 64         # daljsa koda napake sredisca dobi splosno kodo
# Casi podpisov s kljucem naprave: (nas id, vloga, jedro druge naprave) -> casi v zadnjem oknu. Vloga "a" = ponudbe, ki
# jih zacnemo mi, "b" = odgovori na prejete ponudbe. Zapis je skupen programu: ob novi povezavi s srediscem nastane nov
# upravitelj, in s prekinjanjem povezave bi sredisce mejo sicer ponastavljalo.
_ZAKLEP_PODPISOV = threading.Lock()
_PODPISI: Dict[Tuple[str, str, str], List[float]] = {}
# Kdaj dogovor nazadnje ni uspel: (nas id, id druge naprave) -> cas (glej NEUSPEL_DOGOVOR_CAKA_S). Iz istega razloga
# skupno programu: sredisce, ki ponudbo zavrne in prekine povezavo, bi z vsakim novim upraviteljem sicer dobilo nov podpis
# brez premora (sesti pregled).
_NEUSPELI: Dict[Tuple[str, str], float] = {}


class Napaka(Exception):
    """Neveljaven dogovor ali sporocilo (podpis, cilj, stevec, sifropis). Vzrok je v besedilu."""


# ---------------------------------------------------------------------------------------------- kriptografija

def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _iz_b64(s: str, kaj: str) -> bytes:
    if not _veljaven_b64(s, 1 << 30):
        raise Napaka(f"neveljaven zapis ({kaj})")
    try:
        return base64.b64decode(s, validate=True)
    except Exception as e:  # noqa: BLE001
        raise Napaka(f"neveljaven zapis ({kaj})") from e


_ABECEDA_B64 = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")
_ABECEDA_SEJE = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def veljavna_oznaka(oznaka: object) -> bool:
    """Ali sme oznaka naprave v podpisane bajte dogovora: niz 1-128 vidnih znakov ASCII (brez presledka, krmilnih
    znakov in locil vrstic). Vse oznake, ki jih Safeer izdela sam, so take. Glej »Oblika polj« v opisu modula."""
    return isinstance(oznaka, str) and 0 < len(oznaka) <= NAJVEC_OZNAKE and all("!" <= z <= "~" for z in oznaka)


def _veljavna_oznaka_seje(oznaka: object) -> bool:
    return isinstance(oznaka, str) and 0 < len(oznaka) <= 64 and all(z in _ABECEDA_SEJE for z in oznaka)


def _veljaven_b64(zapis: object, najvec: int) -> bool:
    """Standardni base64 s polnilom in nicimer drugim (brez presledkov in prelomov vrstic)."""
    if not isinstance(zapis, str) or not (0 < len(zapis) <= najvec) or len(zapis) % 4:
        return False
    jedro = zapis.rstrip("=")
    return 0 < len(jedro) and len(zapis) - len(jedro) <= 2 and all(z in _ABECEDA_B64 for z in jedro)


def _opis(sporocilo: dict) -> dict:
    """Kar si o poslanem sporocilu zapomnimo, da klicatelju javimo sprejem ali zavrnitev: samo tip in oznaka, in samo
    kratka. Celega sporocila NE hranimo: odgovor, ki ponovi dolgo oznako ukaza ali nosi velik seznam, je sicer ostal v
    pomnilniku za vsako sejo (zadnja sporocila) in vsako potrditev sredisca - naprava brez pravic je s tem lahko
    napolnila pomnilnik (cetrti neodvisni pregled, 7. 10. 2026; izmerjeno: eno 600 kB sporocilo = 1,2 MB hranjenega)."""
    opis: Dict[str, str] = {}
    for polje in ("id", "type"):
        vrednost = sporocilo.get(polje)
        if isinstance(vrednost, str) and 0 < len(vrednost) <= NAJVEC_OPISA:
            opis[polje] = vrednost
    return opis


def ura_sistema() -> float:
    """Ura za roke sej, dogovorov in cakajocih sporocil. Tece tudi med spanjem racunalnika (CLOCK_BOOTTIME), kjer jo
    sistem ima: ukaz, ki je cakal na dogovor, ko je uporabnik zaprl pokrov, po prebujenju ne sme vec veljati za
    svezega. Drugje navadna monotona ura."""
    try:
        return time.clock_gettime(time.CLOCK_BOOTTIME)
    except (AttributeError, OSError, ValueError):
        return time.monotonic()


def _dnevnik(besedilo: str) -> None:
    """Vrstica v dnevnik. Izpis ne sme nikoli vreci (zaprt izhod, znak, ki ga izhod ne zna zapisati): sicer bi
    sporocilo iz omrezja prek dnevnika prekinilo obdelavo."""
    try:
        print(besedilo, flush=True)
    except Exception:  # noqa: BLE001
        pass


def nov_par() -> Tuple[object, str]:
    """Enkratni par P-256: (zasebni kljuc, javni kljuc kot base64 SPKI DER)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    zasebni = ec.generate_private_key(ec.SECP256R1())
    der = zasebni.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return zasebni, _b64(der)


def ecdh(zasebni: object, tuj_javni_b64: str) -> bytes:
    """Skupna skrivnost (koordinata x, 32 bajtov) med nasim enkratnim zasebnim in tujim enkratnim javnim kljucem."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    try:
        tuj = serialization.load_der_public_key(_iz_b64(tuj_javni_b64, "epk"))
        if not isinstance(tuj, ec.EllipticCurvePublicKey) or tuj.curve.name != "secp256r1":
            raise Napaka("enkratni kljuc ni P-256")
        return zasebni.exchange(ec.ECDH(), tuj)  # type: ignore[attr-defined]
    except Napaka:
        raise
    except Exception as e:  # noqa: BLE001
        raise Napaka("ECDH ni uspel") from e


def hkdf(ikm: bytes, sol: bytes, info: bytes, dolzina: int) -> bytes:
    """HKDF-SHA256 (RFC 5869)."""
    prk = _hmac.new(sol if sol else b"\x00" * 32, ikm, hashlib.sha256).digest()
    izhod, blok, i = b"", b"", 1
    while len(izhod) < dolzina:
        blok = _hmac.new(prk, blok + info + bytes([i]), hashlib.sha256).digest()
        izhod += blok
        i += 1
    return izhod[:dolzina]


@dataclass(frozen=True)
class Kljuci:
    """Gradivo ene seje. Smer "ab" je od zacetnika (A) k odgovarjajocemu (B), "ba" nazaj."""
    k_ab: bytes
    p_ab: bytes
    k_ba: bytes
    p_ba: bytes

    def smer(self, smer: str) -> Tuple[bytes, bytes]:
        return (self.k_ab, self.p_ab) if smer == "ab" else (self.k_ba, self.p_ba)


def izpelji(skrivnost: bytes, session_id: str, nonce_a_b64: str, nonce_b_b64: str, a_id: str, b_id: str) -> Kljuci:
    info = (b"safeer-link-e2e-v1\n" + _iz_b64(nonce_a_b64, "nonce") + _iz_b64(nonce_b_b64, "nonce")
            + ("\n%s\n%s" % (a_id, b_id)).encode("utf-8"))
    g = hkdf(skrivnost, hashlib.sha256(session_id.encode("utf-8")).digest(), info, 72)
    return Kljuci(k_ab=g[0:32], p_ab=g[32:36], k_ba=g[36:68], p_ba=g[68:72])


def podatki_ponudbe(session_id: str, od_id: str, do_id: str, nonce_b64: str, epk_b64: str) -> bytes:
    return ("safeer-link-e2e-offer-v1\n%s\n%s\n%s\n%s\n%s" % (session_id, od_id, do_id, nonce_b64, epk_b64)).encode("utf-8")


def podatki_odgovora(session_id: str, od_id: str, do_id: str, nonce_ponudbe_b64: str, nonce_b64: str,
                     epk_a_b64: str, epk_b_b64: str) -> bytes:
    return ("safeer-link-e2e-answer-v1\n%s\n%s\n%s\n%s\n%s\n%s\n%s"
            % (session_id, od_id, do_id, nonce_ponudbe_b64, nonce_b64, epk_a_b64, epk_b_b64)).encode("utf-8")


def aad(session_id: str, smer: str, seq: int, m: int, i: int, n: int) -> bytes:
    return ("safeer-link-e2e-msg-v1\n%s\n%s\n%d\n%d\n%d\n%d" % (session_id, smer, seq, m, i, n)).encode("utf-8")


def _nonce(predpona: bytes, seq: int) -> bytes:
    if seq < 0 or seq > 0xFFFFFFFFFFFFFFFF:
        raise Napaka("neveljaven stevec")
    return predpona + seq.to_bytes(8, "big")


def sifriraj(kljuc: bytes, predpona: bytes, seq: int, cistopis: bytes, dodatno: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(kljuc).encrypt(_nonce(predpona, seq), cistopis, dodatno)


def desifriraj(kljuc: bytes, predpona: bytes, seq: int, sifropis: bytes, dodatno: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        return AESGCM(kljuc).decrypt(_nonce(predpona, seq), sifropis, dodatno)
    except Napaka:
        raise
    except Exception as e:  # noqa: BLE001
        raise Napaka("sporocilo se ni desifriralo (pokvarjeno ali podtaknjeno)") from e


def na_voljo() -> bool:
    """Ali je kriptografija na voljo (brez nje zascite ni - in tudi nezascitenega nadomestka ne)."""
    try:
        from cryptography.hazmat.primitives.asymmetric import ec  # noqa: F401
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------------------------- seja

@dataclass
class Seja:
    session_id: str
    moj_id: str
    tuj_id: str
    vloga: str                      # "a" = zaceli smo mi, "b" = zacela je druga naprava
    kljuci: Kljuci
    jedro: str                      # jedro naprave iz PREVERJENEGA kljuca (na to se veze dostop)
    nastala: float
    # Ali je druga stran dokazala, da kljuc seje ima ZDAJ. Seja, ki smo jo zaceli mi, je potrjena z odgovorom (podpis
    # veze nas svezi nonce). Seja iz prejete ponudbe se ne - ponudbo lahko sredisce ponovi; potrdi jo sele prvi kos, ki
    # se pod njenim kljucem desifrira.
    potrjena: bool = True
    seq_ven: int = 0
    st_sporocila: int = 0
    zadnji_noter: int = -1
    # (prvi seq, zadnji seq, cas, opis sporocila - _opis): po »seje ni« jih javimo klicatelju kot zavrnjena
    zadnja: List[Tuple[int, int, float, dict]] = field(default_factory=list)
    deli: Dict[int, Tuple[float, int, Dict[int, bytes]]] = field(default_factory=dict)   # m -> (cas, n, {i: del})

    @property
    def smer_ven(self) -> str:
        return "ab" if self.vloga == "a" else "ba"

    @property
    def smer_noter(self) -> str:
        return "ba" if self.vloga == "a" else "ab"


@dataclass
class _Dogovor:
    session_id: str
    tuj_id: str
    zasebni: object
    epk: str
    nonce: str
    zacet: float
    # Sporocila, ki cakajo na ta dogovor: (kdaj je prislo v vrsto, opis sporocila, cistopis - ze zapisan JSON).
    vrsta: List[Tuple[float, dict, bytes]] = field(default_factory=list)
    jedro: str = ""                 # jedro naprave iz kljuca v nasem krogu (meje na napravo)


class Upravitelj:
    """Seje zascite z drugimi napravami za EN program te naprave (en id v Linku).

    moj_id        -> id, pod katerim je ta program prijavljen v Link
    poslji        -> poslje sporocilo (dict) srediscu; True, ce je slo v vrsto
    podpisi       -> podpis bajtov s kljucem TE naprave (base64, SHA256withECDSA DER)
    kljuc_za      -> javni kljuc naprave z danim id-jem iz NASEGA kroga zaupanja (base64 SPKI DER) ali None
    preveri       -> (kljuc, bajti, podpis) -> bool
    id_iz_kljuca  -> jedro naprave iz kljuca (n-<16 hex>)
    ob_sporocilu  -> (notranje sporocilo, id posiljatelja, jedro iz preverjenega kljuca): sporocilo je prislo zasciteno
    ob_seji       -> (jedro): z napravo je vzpostavljena preverjena seja (klicatelj si zapomni, da naprava zascito zna)
    ob_zavrnitvi  -> (opis sporocila, besedilo, koda): sporocilo do naprave ni prislo ali ga ta ni mogla sprejeti
                     (naprave ni v Linku, seje ne pozna vec, nasega kljuca nima, dogovor je trajal predolgo)
    ob_sprejemu   -> (opis sporocila): sredisce je sporocilo sprejelo v posredovanje ciljni napravi
                     Opis je {"id", "type"} poslanega sporocila (glej _opis) - celega sporocila upravitelj ne hrani.
    """

    def __init__(self, moj_id: Callable[[], str], poslji: Callable[[dict], bool], podpisi: Callable[[bytes], str],
                 kljuc_za: Callable[[str], Optional[str]], preveri: Callable[[str, bytes, str], bool],
                 id_iz_kljuca: Callable[[str], str], ob_sporocilu: Callable[[dict, str, str], None],
                 ob_seji: Optional[Callable[[str], None]] = None, ura: Optional[Callable[[], float]] = None,
                 ob_zavrnitvi: Optional[Callable[[dict, str, str], None]] = None,
                 ob_sprejemu: Optional[Callable[[dict], None]] = None) -> None:
        self._moj_id = moj_id
        self._poslji = poslji
        self._podpisi = podpisi
        self._kljuc_za = kljuc_za
        self._preveri = preveri
        self._id_iz_kljuca = id_iz_kljuca
        self._ob_sporocilu = ob_sporocilu
        self._ob_seji = ob_seji
        self._ob_zavrnitvi = ob_zavrnitvi
        self._ob_sprejemu = ob_sprejemu
        self._ura = ura or ura_sistema
        # oznaka sporocila prenosa -> (cas, ali je ponudba dogovora, opisi sporocil, ki jih nosi ali nanj cakajo,
        #                              ali »sprejeto« pomeni sprejem sporocila, oznake VSEH kosov istega sporocila)
        self._izhodna: Dict[str, Tuple[float, bool, list, bool, Tuple[str, ...]]] = {}
        self._zaklep = threading.RLock()
        self._seje: Dict[str, Seja] = {}            # session_id -> seja
        self._za: Dict[str, str] = {}               # id druge naprave -> session_id seje, po kateri posiljamo
        self._dogovori: Dict[str, _Dogovor] = {}    # id druge naprave -> dogovor, ki ga cakamo

    # ------------------------------------------------------------------ posiljanje

    def ima_sejo(self, tuj_id: str) -> bool:
        with self._zaklep:
            return self._seja_za(tuj_id) is not None

    def jedro_seje(self, tuj_id: str) -> str:
        with self._zaklep:
            s = self._seja_za(tuj_id)
            return s.jedro if s is not None else ""

    def pozna_kljuc(self, tuj_id: str) -> bool:
        """Ali z napravo dogovor sploh lahko uspe: oznaka sme v podpisane bajte in njen kljuc je v nasem krogu. Brez
        podpisovanja - za odlocitev, ali se dogovor splaca zaceti (seznam naprav pise sredisce)."""
        try:
            return veljavna_oznaka(tuj_id) and bool(self._kljuc_za(tuj_id))
        except Exception:  # noqa: BLE001
            return False

    def znova_javi_sejo(self, tuj_id: str) -> bool:
        """Ce z napravo imamo sejo, klicatelju se enkrat sporoci njeno jedro (`ob_seji`) in vrne True. Zapis o tem, katere
        naprave zascito znajo, pise vec programov iste naprave - ce se je kateri vpis izgubil, ga klicatelj tako obnovi."""
        with self._zaklep:
            s = self._seja_za(tuj_id)
        if s is None:
            return False
        self._javi_sejo(s)
        return True

    def dogovori_se(self, tuj_id: str) -> bool:
        """Zacne dogovor z napravo, ne da bi zanjo imeli sporocilo: napravi si dokazeta kljuc, se preden je poslan prvi
        ukaz (klicatelj si prek `ob_seji` zapomni, da naprava zascito zna). True: seja ze obstaja ali je dogovor na poti."""
        if not tuj_id or not na_voljo():
            return False
        izrinjena: List[dict] = []
        try:
            with self._zaklep:
                if self._seja_za(tuj_id) is not None:
                    return True
                d = self._dogovori.get(tuj_id)
                if d is not None and self._ura() - d.zacet <= DOGOVOR_CAKA_S:
                    return True
                return self._zacni_dogovor(tuj_id, None, izrinjena)
        finally:
            self._zavrni(izrinjena, BESEDILO_CAS, "cas")        # zunaj zaklepa

    def _velja_se(self, s: Seja) -> bool:
        """Seja velja, dokler ji ni potekel rok IN dokler je kljuc, s katerim se je naprava izkazala, se veljaven clan
        nasega kroga. Naprava, ki jo uporabnik odstrani iz Linka, tako izgubi tudi ze vzpostavljeno sejo."""
        if self._ura() - s.nastala > SEJA_VELJA_S:
            return False
        try:
            kljuc = self._kljuc_za(s.tuj_id)
            return bool(kljuc) and self._id_iz_kljuca(kljuc) == s.jedro
        except Exception:  # noqa: BLE001
            return False

    def _seja_za(self, tuj_id: str) -> Optional[Seja]:
        sid = self._za.get(tuj_id)
        s = self._seje.get(sid) if sid else None
        if s is None or s.tuj_id != tuj_id:
            # Kazalec brez seje ali na sejo DRUGE naprave ne velja (seja pripada napravi, s katero je bila dogovorjena).
            if sid:
                self._za.pop(tuj_id, None)
            return None
        if not self._velja_se(s):
            self._odstrani(s)
            return None
        return s

    def _odstrani(self, s: Seja) -> None:
        if self._seje.get(s.session_id) is s:
            self._seje.pop(s.session_id, None)
        for tuj_id in [t for t, sid in self._za.items() if sid == s.session_id]:
            self._za.pop(tuj_id, None)

    def pozabi(self, tuj_id: str) -> None:
        """Naprava je odsla ali se zamenjala: njene seje in cakajoci dogovor ne veljajo vec. Sporocila, ki so cakala na
        dogovor, klicatelj izve (kot iztek casa) - prej so izginila brez sledu, cistopis pa je ostal v zapisu o ponudbi."""
        izrinjena: List[dict] = []
        with self._zaklep:
            for s in [s for s in self._seje.values() if s.tuj_id == tuj_id]:
                self._odstrani(s)
            self._za.pop(tuj_id, None)
            d = self._dogovori.pop(tuj_id, None)
            if d is not None:
                self._opusti_dogovor(d, izrinjena)
        self._zavrni(izrinjena, BESEDILO_CAS, "cas")        # zunaj zaklepa

    def pozabi_vse(self) -> None:
        """Vse seje in cakajoci dogovori ne veljajo vec. Sporocila, ki so cakala na dogovor, klicatelj izve."""
        izrinjena: List[dict] = []
        with self._zaklep:
            for d in self._dogovori.values():
                izrinjena.extend(vnos[1] for vnos in d.vrsta)
                d.vrsta[:] = []
            self._seje.clear()
            self._za.clear()
            self._dogovori.clear()
            self._izhodna.clear()
        self._zavrni(izrinjena, BESEDILO_CAS, "cas")        # zunaj zaklepa

    def _opusti_dogovor(self, d: "_Dogovor", izrinjena: List[dict]) -> None:
        """Cakajoci dogovor ne velja vec (klice se POD zaklepom, dogovor je ze vzet iz zapisa): zapis o poslani ponudbi
        gre, opisi sporocil iz vrste pridejo med `izrinjena` (klicatelj jih javi zunaj zaklepa), cistopisi se sprostijo."""
        self._izhodna.pop(PREDPONA_OZNAK + d.session_id[:10], None)
        izrinjena.extend(vnos[1] for vnos in d.vrsta)
        d.vrsta[:] = []

    def pospravi(self) -> None:
        """Sporocila, ki predolgo cakajo na dogovor, javi klicatelju kot zavrnjena in sprosti njihov pomnilnik. Klicatelj
        to poklice ob vsakem prejetem sporocilu: prej se je to zgodilo sele ob naslednjem POSILJANJU - program, ki ni
        vec posiljal, je cistopis drzal naprej. Nikoli ne vrze."""
        izrinjena: List[dict] = []
        # Brez cakanja: klice jo bralna nit ob VSAKEM sporocilu. Ce zaklep drzi nit, ki podpisuje ali posilja, bi
        # branje sicer stalo pri vsakem sporocilu, ne le pri sporocilih zascite - pospravimo ob naslednjem (sesti pregled).
        if not self._zaklep.acquire(blocking=False):
            return
        try:
            if any(d.vrsta for d in self._dogovori.values()):
                self._pospravi_vrste(self._ura(), izrinjena)
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._zaklep.release()
        self._zavrni(izrinjena, BESEDILO_CAS, "cas")        # zunaj zaklepa

    def poslji(self, tuj_id: str, sporocilo: dict) -> bool:
        """Poslje notranje sporocilo napravi `tuj_id` zasciteno. Ce seje se ni, zacne dogovor in sporocilo pocaka nanj.
        False: zascita ni mogoca (ni kriptografije, kljuca naprave ne poznamo, sporocilo je predolgo, vrsta ali meja
        podpisov je polna) - klicatelj NE sme poslati nezasciteno, razen ce naprava zascite sploh ne zna."""
        if not tuj_id or not na_voljo():
            return False
        try:
            cistopis = json.dumps(sporocilo, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except Exception:  # noqa: BLE001
            return False
        if len(cistopis) > NAJVEC_DELOV * DOLZINA_DELA:
            return False            # predolgo za zasciteno pot: klicatelj izve takoj, v vrsto ne gre
        opis = _opis(sporocilo)
        izrinjena: List[dict] = []
        try:
            with self._zaklep:
                s = self._seja_za(tuj_id)
                if s is not None:
                    return self._poslji_po_seji(s, opis, cistopis)
                zdaj = self._ura()
                self._pospravi_vrste(zdaj, izrinjena)
                d = self._dogovori.get(tuj_id)
                if d is not None and zdaj - d.zacet <= DOGOVOR_CAKA_S:
                    if len(d.vrsta) >= NAJVEC_V_VRSTI or not self._je_prostor_v_vrstah(d.jedro, len(cistopis)):
                        return False
                    d.vrsta.append((zdaj, opis, cistopis))
                    return True
                # Dogovora se ni ali pa nanj cakamo predolgo: zacnemo znova (glej _zacni_dogovor, kaj se zgodi s
                # sporocili, ki so cakala na starega).
                return self._zacni_dogovor(tuj_id, (opis, cistopis), izrinjena)
        finally:
            self._zavrni(izrinjena, BESEDILO_CAS, "cas")        # zunaj zaklepa

    def _sme_podpisati(self, jedro: str, zdaj: float, porabi: bool = True, vloga: str = "a") -> bool:
        """Ali smemo za napravo s tem jedrom se enkrat podpisati s kljucem naprave. `vloga` "a" je ponudba, ki jo
        zacnemo mi, "b" odgovor na prejeto ponudbo - vsaka ima svojo mejo. Ce vrne True in je `porabi`, je podpis ze
        stet; z `porabi=False` samo pogleda. Zapis je skupen programu (glej _PODPISI in NAJVEC_PODPISOV_NA_NAPRAVO)."""
        if not jedro:
            return False
        try:
            kljuc = (str(self._moj_id()), vloga, jedro)
        except Exception:  # noqa: BLE001
            return False
        with _ZAKLEP_PODPISOV:
            casi = [c for c in _PODPISI.get(kljuc, ()) if zdaj - c < OKNO_PODPISOV_S]
            dovoljeno = len(casi) < NAJVEC_PODPISOV_NA_NAPRAVO
            if dovoljeno and porabi:
                casi.append(zdaj)
            if casi:
                _PODPISI[kljuc] = casi
            else:
                _PODPISI.pop(kljuc, None)
            if len(_PODPISI) > NAJVEC_ZAPISOV_PODPISOV:
                for staro in [k for k, c in _PODPISI.items() if not c or zdaj - c[-1] >= OKNO_PODPISOV_S]:
                    _PODPISI.pop(staro, None)
                while len(_PODPISI) > NAJVEC_ZAPISOV_PODPISOV:
                    _PODPISI.pop(next(iter(_PODPISI)))
        return dovoljeno

    def _kljuc_premora(self, tuj_id: str) -> Tuple[str, str]:
        try:
            return (str(self._moj_id()), tuj_id)
        except Exception:  # noqa: BLE001
            return ("", tuj_id)

    def _v_premoru(self, tuj_id: str, zdaj: float) -> bool:
        """Ali dogovor s to oznako pravkar ni uspel in novega se ne zacnemo. Zapis je skupen programu (_NEUSPELI)."""
        kljuc = self._kljuc_premora(tuj_id)
        with _ZAKLEP_PODPISOV:
            kdaj = _NEUSPELI.get(kljuc)
            if kdaj is None:
                return False
            if 0 <= zdaj - kdaj < NEUSPEL_DOGOVOR_CAKA_S:
                return True
            _NEUSPELI.pop(kljuc, None)
            return False

    def _zabelezi_neuspeh(self, tuj_id: str, zdaj: float) -> None:
        """Dogovor s to oznako ni uspel: glej NEUSPEL_DOGOVOR_CAKA_S."""
        kljuc = self._kljuc_premora(tuj_id)
        with _ZAKLEP_PODPISOV:
            if kljuc not in _NEUSPELI and len(_NEUSPELI) >= NAJVEC_NEUSPELIH:
                for stara in [k for k, kdaj in _NEUSPELI.items() if not 0 <= zdaj - kdaj < NEUSPEL_DOGOVOR_CAKA_S]:
                    _NEUSPELI.pop(stara, None)
                while len(_NEUSPELI) >= NAJVEC_NEUSPELIH:
                    _NEUSPELI.pop(next(iter(_NEUSPELI)))
            _NEUSPELI[kljuc] = zdaj

    def _konec_premora(self, tuj_id: str) -> None:
        """Naprava je tu in nas pozna (dogovor je uspel): premora po neuspelem dogovoru ni vec."""
        kljuc = self._kljuc_premora(tuj_id)
        with _ZAKLEP_PODPISOV:
            _NEUSPELI.pop(kljuc, None)

    def _omeji_izhodna(self) -> None:
        """Najvec NAJVEC_IZHODNIH zapisov o poslanem (klice se pod zaklepom). Z najstarejsim izpadejo VSI kosi istega
        sporocila: zavrnitve kosa, katerega zapis je izpadel, ne bi opazili in klicatelj bi za sporocilo dobil »sprejeto«
        (sesti pregled) - tako ne dobi izida (iztek casa)."""
        while len(self._izhodna) > NAJVEC_IZHODNIH:
            vnos = self._izhodna.pop(next(iter(self._izhodna)))
            for druga in vnos[4]:
                self._izhodna.pop(druga, None)

    def _cakajocih_bajtov(self, jedro: Optional[str] = None) -> int:
        return sum(len(cistopis) for d in self._dogovori.values() if jedro is None or d.jedro == jedro
                   for _cas, _opis_sporocila, cistopis in d.vrsta)

    def _je_prostor_v_vrstah(self, jedro: str, novo: int) -> bool:
        """Ali sme v vrsto cakajocega dogovora z napravo `jedro` se sporocilo z `novo` bajti (pod zaklepom)."""
        return (self._cakajocih_bajtov(jedro) + novo <= NAJVEC_CAKAJOCIH_NA_NAPRAVO_B
                and self._cakajocih_bajtov() + novo <= NAJVEC_CAKAJOCIH_B)

    def _pospravi_vrste(self, zdaj: float, izrinjena: List[dict]) -> None:
        """Iz vrst VSEH cakajocih dogovorov vzame sporocila, ki cakajo predolgo (ne gredo vec - glej V_VRSTI_VELJA_S):
        pomnilnik se sprosti, njihovi opisi gredo med `izrinjena` (klicatelj izve). Klice se pod zaklepom."""
        for d in self._dogovori.values():
            if d.vrsta and zdaj - d.vrsta[0][0] > V_VRSTI_VELJA_S:
                sveza = []
                for vnos in d.vrsta:
                    if zdaj - vnos[0] > V_VRSTI_VELJA_S:
                        izrinjena.append(vnos[1])
                    else:
                        sveza.append(vnos)
                d.vrsta[:] = sveza          # na mestu: isti seznam drzi tudi zapis o poslani ponudbi (_izhodna)

    def _zacni_dogovor(self, tuj_id: str, sporocilo: Optional[Tuple[dict, bytes]], izrinjena: List[dict]) -> bool:
        """Zacne dogovor z napravo (klice se POD zaklepom). `sporocilo` je (opis, cistopis) sporocila, ki nanj caka;
        None pomeni dogovor brez sporocila (dokaz kljuca). V `izrinjena` pridejo OPISI sporocil, ki zaradi tega dogovora
        NE bodo poslana - klicatelj jih javi kot zavrnjena zunaj zaklepa:
        - kar je na katerikoli dogovor cakalo dlje kot V_VRSTI_VELJA_S (ukaz, ki bi se izvedel z zamudo, je slabsi od
          ukaza, ki se ne izvede); sveze caka naprej - tudi na novi dogovor z isto napravo;
        - sporocila dogovora z DRUGO napravo, ki je moral narediti prostor."""
        moj = self._moj_id()
        if not veljavna_oznaka(tuj_id) or not veljavna_oznaka(moj):
            return False            # oznaka, ki ne sme v podpisane bajte dogovora (glej veljavna_oznaka)
        kljuc = self._kljuc_za(tuj_id)
        if not kljuc:
            return False            # naprave ni v nasem krogu: nimamo s cim preveriti njenega odgovora
        try:
            jedro = self._id_iz_kljuca(kljuc)
        except Exception:  # noqa: BLE001
            return False
        zdaj = self._ura()
        self._pospravi_vrste(zdaj, izrinjena)
        if self._v_premoru(tuj_id, zdaj):
            return False            # dogovor s to oznako pravkar ni uspel: kratek premor (NEUSPEL_DOGOVOR_CAKA_S)
        if sporocilo is not None and not self._je_prostor_v_vrstah(jedro, len(sporocilo[1])):
            return False            # cakajoca sporocila te naprave (ali vseh skupaj) ze drzijo ves dovoljeni pomnilnik
        if not self._sme_podpisati(jedro, zdaj, porabi=False):
            return False            # prevec dogovorov s to napravo v kratkem casu (vsak je podpis s kljucem naprave)
        for star in [t for t, d in self._dogovori.items() if t != tuj_id and zdaj - d.zacet > DOGOVOR_VELJA_S]:
            self._opusti_dogovor(self._dogovori.pop(star), izrinjena)
        while tuj_id not in self._dogovori and len(self._dogovori) >= NAJVEC_DOGOVOROV:
            # Prostor naredi najprej dogovor, na katerega ne caka nobeno sporocilo (dokaz kljuca ob seznamu naprav).
            # Seznam naprav pise sredisce: z izmisljenimi napravami ne sme izriniti dogovora, na katerega caka ukaz.
            prazni = [t for t, d in self._dogovori.items() if not d.vrsta]
            if prazni:
                self._opusti_dogovor(self._dogovori.pop(min(prazni, key=lambda t: self._dogovori[t].zacet)), izrinjena)
                continue
            if sporocilo is None:
                return False
            if _dovolj_pomnilnika():
                break               # vsi nosijo sporocila tega racunalnika in pomnilnika je dovolj: brez izrinjanja
            self._opusti_dogovor(self._dogovori.pop(min(self._dogovori, key=lambda t: self._dogovori[t].zacet)), izrinjena)
        self._sme_podpisati(jedro, zdaj)        # podpis stejemo tik pred njim (zgoraj smo samo pogledali)
        try:
            zasebni, epk = nov_par()
            session_id = base64.urlsafe_b64encode(os.urandom(16)).decode("ascii").rstrip("=")
            nonce = _b64(os.urandom(16))
            podpis = self._podpisi(podatki_ponudbe(session_id, moj, tuj_id, nonce, epk))
        except Exception:  # noqa: BLE001
            return False
        if not podpis:
            return False
        vrsta: List[Tuple[float, dict, bytes]] = []
        prejsnji = self._dogovori.get(tuj_id)
        if prejsnji is not None:
            self._izhodna.pop(PREDPONA_OZNAK + prejsnji.session_id[:10], None)
            vrsta.extend(prejsnji.vrsta)        # zastarela je odstranil ze _pospravi_vrste zgoraj
            prejsnji.vrsta = []
        if sporocilo is not None:
            vrsta.append((zdaj, sporocilo[0], sporocilo[1]))
        while len(vrsta) > NAJVEC_V_VRSTI:
            izrinjena.append(vrsta.pop(0)[1])
        dogovor = _Dogovor(session_id, tuj_id, zasebni, epk, nonce, zdaj, vrsta, jedro)
        self._dogovori[tuj_id] = dogovor
        self._zapomni_izhodno(PREDPONA_OZNAK + session_id[:10], dogovor.vrsta, dogovor=True)
        ok = self._poslji({"id": PREDPONA_OZNAK + session_id[:10], "type": "data.offer", "target": tuj_id,
                           "payload": {"session_id": session_id, "purpose": NAMEN, "v": RAZLICICA, "from": moj,
                                       "to": tuj_id, "nonce": nonce, "epk": epk, "ts": round(time.time(), 3),
                                       "sig": podpis}})
        if not ok:
            self._dogovori.pop(tuj_id, None)
            self._izhodna.pop(PREDPONA_OZNAK + session_id[:10], None)
            # Kar je cakalo se od prej, klicatelj izve; za novo sporocilo dobi False.
            prenesena = dogovor.vrsta[:-1] if sporocilo is not None else list(dogovor.vrsta)
            izrinjena.extend(vnos[1] for vnos in prenesena)
            dogovor.vrsta[:] = []
            self._zabelezi_neuspeh(tuj_id, zdaj)
        return ok

    def _poslji_po_seji(self, s: Seja, opis: dict, cistopis: bytes) -> bool:
        """Cistopis sporocila sifrira in poslje. Vsako notranje sporocilo gre skozi to funkcijo NATANKO ENKRAT -
        ponovnega posiljanja ni (glej _prejmi_napako), zato ga prejemnik ne more dobiti dvakrat. Zapomnimo si samo
        `opis` sporocila (za sprejem ali zavrnitev), ne sporocila."""
        deli = [cistopis[i:i + DOLZINA_DELA] for i in range(0, len(cistopis), DOLZINA_DELA)] or [b""]
        if len(deli) > NAJVEC_DELOV:
            return False
        kljuc, predpona = s.kljuci.smer(s.smer_ven)
        m = s.st_sporocila
        s.st_sporocila += 1
        prvi = s.seq_ven
        s.seq_ven += len(deli)
        # Zapomnimo si PRED posiljanjem: obvestilo »ni seje« lahko pride, se preden se posiljanje vrne.
        zdaj = self._ura()
        s.zadnja[:] = [z for z in s.zadnja if zdaj - z[2] <= NEPOTRJENA_VELJAJO_S]
        zapis = (prvi, prvi + len(deli) - 1, zdaj, opis)
        s.zadnja.append(zapis)
        del s.zadnja[:-HRANI_ZADNJIH]
        # Potrditve sredisca: VSAK kos ima svoj zapis. Sporocilo je SPREJETO, ko je sprejet njegov zadnji kos in pred
        # njim ni bil zavrnjen noben; ZAVRNJENO, ko je zavrnjen katerikoli (javimo enkrat). Prej smo spremljali samo
        # prvega in zadnjega: zavrnjen srednji kos je ostal neopazen in klicatelj je dobil »sprejeto« (peti pregled).
        oznake = tuple("%s%s-%d" % (PREDPONA_OZNAK, s.session_id[:8], prvi + i) for i in range(len(deli)))
        nosi = [opis]
        self._pocisti_izhodna(zdaj)
        for i, oznaka in enumerate(oznake):
            self._izhodna[oznaka] = (zdaj, False, nosi, i == len(oznake) - 1, oznake)
        self._omeji_izhodna()
        for i, kos in enumerate(deli):
            seq = prvi + i
            try:
                podatki = sifriraj(kljuc, predpona, seq, kos, aad(s.session_id, s.smer_ven, seq, m, i, len(deli)))
                poslano = bool(self._poslji({"id": oznake[i], "type": "data.chunk", "target": s.tuj_id,
                                             "payload": {"session_id": s.session_id, "seq": seq, "m": m, "i": i,
                                                         "n": len(deli), "data": _b64(podatki)}}))
            except Exception:  # noqa: BLE001 - izjema pri posiljanju je isto kot »ni slo«: zapisi se pospravijo
                poslano = False
            if not poslano:
                # Sporocilo ni slo (povezave s srediscem ni): klicatelj dobi False ali »ni poslano«. Zapisov o njem ne
                # pustimo - poznejsa potrditev ze poslanega kosa ali »seje ni« ga ne sme javiti se enkrat.
                for oznaka in oznake:
                    self._izhodna.pop(oznaka, None)
                self._pozabi_zadnje(nosi)
                return False
        return True

    def _pozabi_zadnje(self, nosi: list) -> None:
        """Iz zapisov »zadnja poslana« (za obvestilo »seje ni«) vzame sporocilo, katerega izid je klicatelj ze dobil
        (klice se pod zaklepom). Sporocilo prepoznamo po istem opisu (isti predmet kot v zapisu o poslanih kosih)."""
        for opis in nosi:
            for seja in self._seje.values():
                seja.zadnja[:] = [z for z in seja.zadnja if z[3] is not opis]

    def _pocisti_izhodna(self, zdaj: float) -> None:
        for stara in [o for o, v in self._izhodna.items() if zdaj - v[0] > IZHODNA_VELJAJO_S]:
            self._izhodna.pop(stara, None)

    def _zapomni_izhodno(self, oznaka: str, notranja: list, dogovor: bool = False, sprejem: bool = True,
                         vsi: Tuple[str, ...] = ()) -> None:
        zdaj = self._ura()
        self._pocisti_izhodna(zdaj)
        self._izhodna[oznaka] = (zdaj, dogovor, notranja, sprejem, vsi)
        self._omeji_izhodna()

    def _zavrni(self, sporocila: List[dict], besedilo: str, koda: str) -> None:
        """Klicatelju javi, da sporocila s temi opisi do naprave niso prisla (klice se ZUNAJ zaklepa)."""
        if self._ob_zavrnitvi is None:
            return
        for sporocilo in sporocila:
            try:
                self._ob_zavrnitvi(sporocilo, besedilo, koda)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ prejem

    def _prejmi_potrditev(self, sporocilo: dict) -> bool:
        """Potrditev sredisca za nase sporocilo prenosa. Sprejeto: notranje sporocilo je na poti - javimo sprejem (za
        ponudbo dogovora nic: sporocila se cakajo na odgovor naprave; pri sporocilu v vec delih sele ob zadnjem kosu).
        Zavrnjeno: sporocila, ki jih je nosilo ali so nanj cakala, javimo klicatelju kot zavrnjena."""
        oznaka = _niz(sporocilo.get("ref_id"))
        if not oznaka.startswith(PREDPONA_OZNAK) or sporocilo.get("sender"):
            return False
        stanje = _niz(sporocilo.get("status"))
        sprejeto = stanje in ("accepted", "queued")
        with self._zaklep:
            vnos = self._izhodna.pop(oznaka, None)
            if vnos is None:
                return True
            _cas, je_dogovor, vsebina, sprejem, vsi = vnos
            notranja = [n[1] if isinstance(n, tuple) else n for n in vsebina]
            if not sprejeto or sprejem:
                for druga in vsi:
                    self._izhodna.pop(druga, None)      # drugi kosi istega sporocila: izid javimo enkrat
            if not sprejeto:
                if not je_dogovor:
                    self._pozabi_zadnje(vsebina)        # ze javljeno: poznejsi »seje ni« ga ne javi se enkrat
                zdaj = self._ura()
                for tuj_id, d in list(self._dogovori.items()):
                    if PREDPONA_OZNAK + d.session_id[:10] == oznaka:
                        self._dogovori.pop(tuj_id, None)
                        d.vrsta[:] = []                 # opisi so ze v `notranja`; cistopisi se sprostijo
                        self._zabelezi_neuspeh(tuj_id, zdaj)
        if sprejeto:
            if stanje == "accepted" and not je_dogovor and sprejem and self._ob_sprejemu is not None:
                for n in notranja:
                    try:
                        self._ob_sprejemu(n)
                    except Exception:  # noqa: BLE001
                        pass
            return True
        koda = _niz(sporocilo.get("error_code"))
        if koda in LASTNE_KODE or len(koda) > NAJVEC_KODE_SREDISCA:
            koda = KODA_ZAVRNITVE_SREDISCA      # glej KODA_ZAVRNITVE_SREDISCA; predolge kode ne podajamo naprej
        self._zavrni(notranja, _niz(sporocilo.get("error"))[:NAJVEC_BESEDILA_NAPAKE], koda)
        return True

    def prejmi(self, sporocilo: dict) -> bool:
        """Obdela prejeto data.offer / data.answer / data.chunk / data.error z namenom "link" in potrditev sredisca
        (data.ack) za nasa sporocila prenosa. True: sporocilo je bilo nase (klicatelj ga ne obravnava naprej); False:
        ni del zascite Linka (npr. prenos datoteke). Nikoli ne vrze izjeme: karkoli pride po omrezju, sme sporocilo
        kvecjemu zavreci, ne pa prekiniti povezave s srediscem."""
        tip = sporocilo.get("type")
        if not isinstance(tip, str):
            return False
        self.pospravi()
        try:
            if tip == "data.ack":
                return self._prejmi_potrditev(sporocilo)
            if tip not in TIPI_PRENOSA:
                return False
            tovor = sporocilo.get("payload")
            if not isinstance(tovor, dict):
                return False
        except Exception:  # noqa: BLE001
            return False
        posiljatelj = _niz(sporocilo.get("sender"))
        try:
            if tip == "data.offer":
                if tovor.get("purpose") != NAMEN:
                    return False
                self._prejmi_ponudbo(tovor, posiljatelj)
                return True
            if tip == "data.answer":
                if tovor.get("purpose") != NAMEN:
                    return False
                self._prejmi_odgovor(tovor, posiljatelj)
                return True
            sid = _niz(tovor.get("session_id"))
            if tip == "data.chunk":
                with self._zaklep:
                    s = self._seje.get(sid)
                    if s is not None and not self._velja_se(s):
                        self._odstrani(s)       # rok je potekel ali pa naprave ni vec v krogu: kot da seje ni
                        s = None
                if s is None:
                    if _celo(tovor.get("m"), -1) < 0:
                        return False            # kos drugega prenosa (datoteka), ne nase seje
                    self._javi_napako(posiljatelj, sid, "ni_seje", tovor.get("seq"))
                    return True
                self._prejmi_kos(s, tovor, posiljatelj)
                return True
            if tip == "data.error":
                return self._prejmi_napako(tovor, posiljatelj)
        except Napaka as e:
            _dnevnik("[SafeerE2E] zavrnjeno (%s od %s): %s" % (tip, _zakrij(posiljatelj), e))
            return True
        except Exception as e:  # noqa: BLE001 - nepricakovana oblika ali napaka v obdelavi: sporocilo zavrzemo
            _dnevnik("[SafeerE2E] sporocila ni bilo mogoce obdelati (%s od %s): %s"
                     % (tip, _zakrij(posiljatelj), type(e).__name__))
            return True
        return False

    def _prejmi_ponudbo(self, t: dict, posiljatelj: str) -> None:
        if not na_voljo():
            raise Napaka("kriptografija ni na voljo")
        session_id, od_id, do_id = _niz(t.get("session_id")), _niz(t.get("from")), _niz(t.get("to"))
        nonce, epk, sig = _niz(t.get("nonce")), _niz(t.get("epk")), _niz(t.get("sig"))
        moj = self._moj_id()
        if not (session_id and od_id and nonce and epk and sig) or _celo(t.get("v")) != RAZLICICA:
            raise Napaka("ponudbi manjka polje ali ima drugo razlicico")
        if not (veljavna_oznaka(od_id) and _veljavna_oznaka_seje(session_id) and _veljaven_b64(nonce, 64)
                and _veljaven_b64(epk, 400) and _veljaven_b64(sig, 400)):
            raise Napaka("ponudba ima polje, ki ne sme v podpisane bajte (oblika ali dolzina)")
        if do_id != moj or not veljavna_oznaka(moj):
            raise Napaka("ponudba ni namenjena temu programu")
        if posiljatelj and posiljatelj != od_id:
            raise Napaka("posiljatelj sredisca se ne ujema s podpisano ponudbo")
        with self._zaklep:
            # Ponovljena ponudba (sredisce jo lahko ponavlja v nedogled) je zavrnjena, PREDEN karkoli preverimo ali
            # podpisemo. Ista preverba je spodaj se enkrat - za ponudbi, ki prideta hkrati.
            if session_id in self._seje or any(d.session_id == session_id for d in self._dogovori.values()):
                raise Napaka("seja s to oznako ze obstaja ali jo ravno dogovarjamo")
        kljuc = self._kljuc_za(od_id)
        if not kljuc:
            # Posiljatelj naj izve takoj (sicer njegov ukaz tiho caka na iztek casa): dogovor z nami ne more uspeti.
            self._javi_napako(posiljatelj or od_id, session_id, "ni_kljuca")
            raise Napaka("naprave ni v krogu zaupanja")
        if not self._preveri(kljuc, podatki_ponudbe(session_id, od_id, do_id, nonce, epk), sig):
            raise Napaka("podpis ponudbe se ne ujema s kljucem naprave v krogu")
        jedro = self._id_iz_kljuca(kljuc)
        with self._zaklep:
            # Odgovor je podpis s kljucem naprave: za eno napravo jih je v oknu omejeno stevilo (PO preverbi podpisa -
            # mejo naprave tako porabijo samo njene prave ponudbe, ne ponaredki v njenem imenu).
            if not self._sme_podpisati(jedro, self._ura(), vloga="b"):
                raise Napaka("prevec dogovorov s to napravo v kratkem casu")
        zasebni, moj_epk = nov_par()
        moj_nonce = _b64(os.urandom(16))
        podpis = self._podpisi(podatki_odgovora(session_id, moj, od_id, nonce, moj_nonce, epk, moj_epk))
        if not podpis:
            raise Napaka("odgovora ni bilo mogoce podpisati")
        kljuci = izpelji(ecdh(zasebni, epk), session_id, nonce, moj_nonce, od_id, moj)
        seja = Seja(session_id, moj, od_id, "b", kljuci, jedro, self._ura(), potrjena=False)
        with self._zaklep:
            # Oznako seje izbere posiljatelj ponudbe in je srediscu vidna: ne sme se ujeti z nobeno naso sejo ne z
            # dogovorom, ki ga ravno cakamo (sicer bi odgovor nanj sejo pod to oznako zamenjal).
            if session_id in self._seje or any(d.session_id == session_id for d in self._dogovori.values()):
                raise Napaka("seja s to oznako ze obstaja ali jo ravno dogovarjamo")
            self._omeji_seje(seja.jedro)
            self._seje[session_id] = seja
            # Odgovor gre ven PRED kazalcem posiljanja: druga nit po tej seji ne sme poslati nicesar, dokler odgovor
            # ni na poti (druga stran bi kos dobila pred odgovorom in javila, da seje ne pozna).
            self._poslji({"id": "e2e-" + session_id[:10] + "-o", "type": "data.answer", "target": od_id,
                          "payload": {"session_id": session_id, "purpose": NAMEN, "v": RAZLICICA, "from": moj, "to": od_id,
                                      "offer_nonce": nonce, "nonce": moj_nonce, "epk": moj_epk,
                                      "ts": round(time.time(), 3), "sig": podpis}})
            # Po tej seji tudi posiljamo, razen ce ravno cakamo na odgovor na SVOJO ponudbo (takrat velja nasa).
            if od_id not in self._dogovori:
                self._za[od_id] = session_id
            self._konec_premora(od_id)
        self._javi_sejo(seja)

    def _prejmi_odgovor(self, t: dict, posiljatelj: str) -> None:
        session_id, od_id, do_id = _niz(t.get("session_id")), _niz(t.get("from")), _niz(t.get("to"))
        nonce, epk, sig = _niz(t.get("nonce")), _niz(t.get("epk")), _niz(t.get("sig"))
        pozna: List[dict] = []
        with self._zaklep:
            d = self._dogovori.get(od_id)
            if d is None or d.session_id != session_id:
                raise Napaka("odgovor ne pripada dogovoru, ki ga cakamo")
            prepozno = self._ura() - d.zacet > DOGOVOR_VELJA_S
            if prepozno:
                self._dogovori.pop(od_id, None)
                self._opusti_dogovor(d, pozna)
        if prepozno:
            self._zavrni(pozna, BESEDILO_CAS, "cas")        # zunaj zaklepa
            raise Napaka("odgovor je prisel prepozno")
        moj = self._moj_id()
        if do_id != moj or not (veljavna_oznaka(od_id) and _veljaven_b64(nonce, 64) and _veljaven_b64(epk, 400)
                                and _veljaven_b64(sig, 400)):
            raise Napaka("odgovoru manjka polje, polje nima prave oblike ali pa odgovor ni namenjen temu programu")
        if posiljatelj and posiljatelj != od_id:
            raise Napaka("posiljatelj sredisca se ne ujema s podpisanim odgovorom")
        if _niz(t.get("offer_nonce")) != d.nonce:
            raise Napaka("odgovor ne veze nase ponudbe")
        kljuc = self._kljuc_za(od_id)
        if not kljuc:
            raise Napaka("naprave ni v krogu zaupanja")
        if not self._preveri(kljuc, podatki_odgovora(session_id, od_id, moj, d.nonce, nonce, d.epk, epk), sig):
            raise Napaka("podpis odgovora se ne ujema s kljucem naprave v krogu")
        kljuci = izpelji(ecdh(d.zasebni, epk), session_id, d.nonce, nonce, moj, od_id)
        seja = Seja(session_id, moj, od_id, "a", kljuci, self._id_iz_kljuca(kljuc), self._ura(), potrjena=True)
        zastarela: List[dict] = []
        neposlana: List[dict] = []
        with self._zaklep:
            if self._dogovori.get(od_id) is not d:
                raise Napaka("dogovor se je medtem zamenjal")
            if session_id in self._seje:
                raise Napaka("seja s to oznako ze obstaja")
            self._dogovori.pop(od_id, None)
            self._izhodna.pop(PREDPONA_OZNAK + session_id[:10], None)
            self._omeji_seje(seja.jedro)
            self._seje[session_id] = seja
            self._za[od_id] = session_id
            self._konec_premora(od_id)
            vrsta, d.vrsta = d.vrsta, []
            zdaj = self._ura()
            for cas, opis, cistopis in vrsta:
                # Sporocilo, ki je na dogovor cakalo predolgo (sredisce je odgovor zadrzalo), ne gre vec: ukaz, ki bi se
                # izvedel z zamudo, je slabsi od ukaza, ki se ne izvede.
                if zdaj - cas > V_VRSTI_VELJA_S:
                    zastarela.append(opis)
                    continue
                try:
                    poslano = self._poslji_po_seji(seja, opis, cistopis)
                except Exception:  # noqa: BLE001 - eno sporocilo ne sme vzeti s seboj ostalih (vrsta je ze prazna)
                    poslano = False
                if not poslano:
                    # Povezave s srediscem ni vec: klicatelj mora izvedeti (prej je cakal na iztek casa).
                    neposlana.append(opis)
        self._zavrni(zastarela, BESEDILO_CAS, "cas")
        self._zavrni(neposlana, BESEDILO_NI_POSLANO, "ni_poslano")
        self._javi_sejo(seja)

    def _javi_sejo(self, seja: Seja) -> None:
        if self._ob_seji is not None:
            try:
                self._ob_seji(seja.jedro)
            except Exception:  # noqa: BLE001
                pass

    def _omeji_seje(self, jedro: str = "") -> None:
        """Naredi prostor za novo sejo naprave z jedrom `jedro`. Najprej izpadejo seje, ki jim je potekel rok. Potem
        velja meja NA NAPRAVO (vsi njeni programi skupaj): naprava, ki odpira sejo za sejo (in vsako potrdi), izrine
        svoje seje - ne sej drugih naprav (drugi neodvisni pregled, 7. 10. 2026). Nazadnje skupna meja.

        Vrstni red pri meji na napravo: najprej NEPOTRJENE seje (nastanejo iz prejetih ponudb, tudi ponovljenih - z
        njimi nihce ne sme izriniti seje, ki res deluje), potem NADOMESCENE (starejse od novejse potrjene seje istega
        programa in iste vloge: program se je znova zagnal in se dogovoril znova), sele nato zive, najstarejsa prva.
        Tako ziva, redko rabljena seja enega programa ne izpade zato, ker se drug program iste naprave pogosto zaganja
        (tretji pregled, 7. 10. 2026)."""
        zdaj = self._ura()
        for s in [s for s in self._seje.values() if zdaj - s.nastala > SEJA_VELJA_S]:
            self._odstrani(s)
        njene = [s for s in self._seje.values() if s.jedro == jedro] if jedro else []
        if len(njene) >= NAJVEC_SEJ_NA_NAPRAVO:
            najnovejsa: Dict[Tuple[str, str], float] = {}
            for s in njene:
                if s.potrjena:
                    par = (s.tuj_id, s.vloga)
                    najnovejsa[par] = max(najnovejsa.get(par, s.nastala), s.nastala)

            def red(s: Seja) -> int:
                if not s.potrjena:
                    return 0
                return 1 if s.nastala < najnovejsa[(s.tuj_id, s.vloga)] else 2
            njene.sort(key=lambda s: (red(s), s.nastala))
            while len(njene) >= NAJVEC_SEJ_NA_NAPRAVO:
                self._odstrani(njene.pop(0))
        while len(self._seje) >= NAJVEC_SEJ:
            nepotrjene = [s for s in self._seje.values() if not s.potrjena]
            if not nepotrjene and _dovolj_pomnilnika():
                break               # same potrjene seje in dovolj pomnilnika: brez stevilske meje
            self._odstrani(min(nepotrjene or list(self._seje.values()), key=lambda s: s.nastala))

    def _naredi_prostor_za_dele(self, seja: Seja, n: int, zdaj: float) -> None:
        """Pomnilnik za sporocila v vec delih je omejen na napravo in skupaj (drugi neodvisni pregled: ena naprava je z
        nedokoncanimi sporocili v vec sejah lahko drzala vec kot gigabajt). Vsako nedokoncano sporocilo steje s polno
        napovedano velikostjo. Ko za novo (n delov) zmanjka prostora, izpadejo najstarejsa nedokoncana - najprej ISTE
        naprave, potem katerakoli. Ob tem se zavrzejo zastarela nedokoncana sporocila vseh sej (klice se pod zaklepom)."""
        vsa: List[Tuple[float, Seja, int, int]] = []
        for s in self._seje.values():
            for m, (cas, st_delov, _zbrani) in list(s.deli.items()):
                if zdaj - cas > NEDOKONCANA_VELJAJO_S:
                    s.deli.pop(m, None)
                else:
                    vsa.append((cas, s, m, st_delov * DOLZINA_DELA))
        vsa.sort(key=lambda v: v[0])
        novo = n * DOLZINA_DELA
        njeno = novo + sum(v[3] for v in vsa if v[1].jedro == seja.jedro)
        skupaj = novo + sum(v[3] for v in vsa)
        for v in list(vsa):
            if njeno <= NAJVEC_REZERVIRANO_NA_NAPRAVO_B:
                break
            if v[1].jedro == seja.jedro:
                v[1].deli.pop(v[2], None)
                vsa.remove(v)
                njeno -= v[3]
                skupaj -= v[3]
        while skupaj > NAJVEC_REZERVIRANO_B and vsa:
            _cas, s, m, rezervirano = vsa.pop(0)
            s.deli.pop(m, None)
            skupaj -= rezervirano

    def _prejmi_kos(self, s: Seja, t: dict, posiljatelj: str) -> None:
        if posiljatelj and posiljatelj != s.tuj_id:
            raise Napaka("kos je prisel od druge naprave kot seja")
        seq, m, i, n = _celo(t.get("seq")), _celo(t.get("m")), _celo(t.get("i")), _celo(t.get("n"))
        if seq < 0 or n < 1 or n > NAJVEC_DELOV or i < 0 or i >= n or m < 0:
            raise Napaka("neveljavna delitev sporocila")
        zapis = _niz(t.get("data"))
        if len(zapis) > NAJVEC_ZAPISA_KOSA:
            raise Napaka("kos je daljsi od dogovorjenega")      # predolgega niti ne dekodiramo
        sifropis = _iz_b64(zapis, "data")
        if len(sifropis) > DOLZINA_DELA + 16:
            raise Napaka("kos je daljsi od dogovorjenega")
        kljuc, predpona = s.kljuci.smer(s.smer_noter)
        neujemanje = False
        cistopis: Optional[bytes] = None
        with self._zaklep:
            if self._seje.get(s.session_id) is not s:
                raise Napaka("seja je bila medtem zavrzena")
            if seq <= s.zadnji_noter:
                raise Napaka("stevec se ponavlja ali gre nazaj")
            try:
                kos = desifriraj(kljuc, predpona, seq, sifropis, aad(s.session_id, s.smer_noter, seq, m, i, n))
            except Napaka:
                if s.potrjena:
                    raise           # seja deluje; pokvarjen ali podtaknjen kos zavrzemo, seja ostane
                # Seja iz ponudbe, ki je druga stran se ni potrdila, in ze prvi kos se ne desifrira: kljuca se ne
                # ujemata (ponudbo je kdo ponovil ali pa ima druga stran pod to oznako drugo sejo). Zavrzemo jo in to
                # povemo, da se druga stran dogovori znova - sicer bi obe molce zavracali vse.
                self._odstrani(s)
                neujemanje = True
                kos = b""
            if not neujemanje:
                s.zadnji_noter = seq
                s.potrjena = True
                zdaj = self._ura()
                for stari in [k for k, v in s.deli.items() if zdaj - v[0] > NEDOKONCANA_VELJAJO_S]:
                    s.deli.pop(stari, None)
                if n == 1:
                    cistopis = kos
                else:
                    if m not in s.deli:
                        while len(s.deli) >= NAJVEC_NEDOKONCANIH:
                            s.deli.pop(min(s.deli, key=lambda k: s.deli[k][0]), None)
                        self._naredi_prostor_za_dele(s, n, zdaj)
                    _cas, _n, zbrani = s.deli.setdefault(m, (zdaj, n, {}))
                    if _n != n:
                        s.deli.pop(m, None)
                        raise Napaka("deli sporocila se ne ujemajo")
                    zbrani[i] = kos
                    if len(zbrani) < n:
                        return
                    s.deli.pop(m, None)
                    cistopis = b"".join(zbrani[j] for j in range(n))
        if neujemanje:
            self._javi_napako(posiljatelj or s.tuj_id, s.session_id, "ni_seje", seq)
            raise Napaka("nepotrjena seja se s posiljateljevo ne ujema - zavrzena")
        try:
            notranje = json.loads(cistopis.decode("utf-8"))  # type: ignore[union-attr]
        except Exception as e:  # noqa: BLE001
            raise Napaka("notranje sporocilo ni JSON") from e
        if not isinstance(notranje, dict) or not isinstance(notranje.get("type"), str) or notranje["type"] in TIPI_PRENOSA:
            raise Napaka("neveljavno notranje sporocilo")
        self._ob_sporocilu(notranje, s.tuj_id, s.jedro)

    def _javi_napako(self, cilj: str, session_id: str, koda: str, seq: object = None) -> None:
        if not cilj or not session_id:
            return
        tovor: Dict[str, object] = {"session_id": session_id[:64], "code": koda}
        if seq is not None:
            tovor["seq"] = _celo(seq)
        self._poslji({"id": "e2e-err-" + session_id[:8], "type": "data.error", "target": cilj, "payload": tovor})

    def _prejmi_napako(self, t: dict, posiljatelj: str) -> bool:
        """Druga naprava seje ne pozna vec (»ni_seje«) ali pa nasega kljuca nima v krogu (»ni_kljuca«). Obvestilo NI
        podpisano - lahko ga je poslalo tudi sredisce. Zato z njim dosezemo samo to, kar sredisce doseze ze s tem, da
        sporocila zavrze: sejo (ali cakajoci dogovor) opustimo in klicatelju javimo, da sveza sporocila niso prisla.
        Sporocil NE posljemo se enkrat - prejemnik jih je morda ze izvedel, in ponovitev bi jih izvedla znova."""
        sid, koda = _niz(t.get("session_id")), _niz(t.get("code"))
        zavrnjena: List[dict] = []
        besedilo = ""
        with self._zaklep:
            s = self._seje.get(sid)
            if s is None:
                d = next((d for d in self._dogovori.values() if d.session_id == sid), None)
                if d is None:
                    return False
                if (posiljatelj and posiljatelj != d.tuj_id) or koda != "ni_kljuca":
                    return True
                if self._dogovori.get(d.tuj_id) is d:
                    self._dogovori.pop(d.tuj_id, None)
                self._opusti_dogovor(d, zavrnjena)
                self._zabelezi_neuspeh(d.tuj_id, self._ura())
                besedilo = "Naprava te naprave nima v svojem krogu zaupanja."
            else:
                if (posiljatelj and posiljatelj != s.tuj_id) or koda != "ni_seje":
                    return True
                od = _celo(t.get("seq"))
                zdaj = self._ura()
                # Sporocilo v vec delih steje po ZADNJEM kosu: ce prejemnik sejo izgubi sredi sporocila, ga ni dobil.
                javljena = [z for z in s.zadnja if z[1] >= od >= 0 and zdaj - z[2] <= NEPOTRJENA_VELJAJO_S]
                zavrnjena = [z[3] for z in javljena]
                # Izid teh sporocil je s tem javljen: potrditve sredisca za njihove kose, ki pridejo pozneje, jih ne
                # smejo javiti se enkrat - ne kot sprejeta ne kot zavrnjena (sesti pregled).
                for prvi, zadnji, _cas, _opis_sporocila in javljena:
                    for seq in range(prvi, zadnji + 1):
                        self._izhodna.pop("%s%s-%d" % (PREDPONA_OZNAK, s.session_id[:8], seq), None)
                self._odstrani(s)
                besedilo = "Naprava je sejo zaščite izgubila. Poskusi znova."
        self._zavrni(zavrnjena, besedilo, koda)
        return True


def _celo(vrednost: object, privzeto: int = -1) -> int:
    """Celo stevilo iz polja sporocila; karkoli drugega (niz, None, decimalka, bool) da `privzeto`."""
    return vrednost if isinstance(vrednost, int) and not isinstance(vrednost, bool) else privzeto


def _niz(vrednost: object) -> str:
    """Niz iz polja sporocila; karkoli drugega (None, stevilo, seznam, slovar) da prazen niz."""
    return vrednost if isinstance(vrednost, str) else ""


def _zakrij(device_id: str) -> str:
    """Oznaka naprave za dnevnik: brez sredine (dnevniki se kopirajo v porocila)."""
    d = str(device_id or "")
    d = d if len(d) < 12 else d[:2] + "..." + d[14:]
    # Oznako pise sredisce: v dnevnik gre samo kot vidni ASCII in omejene dolzine.
    return d.encode("ascii", "backslashreplace").decode("ascii")[:60]
