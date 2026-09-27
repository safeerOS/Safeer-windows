"""Safeer Data Transport (v0.26): sejni dogovor in sifriranje za prenos med seznanjenima napravama.

Glej docs/P2P-NACRT.md (tv-browser-2, korak "3. korak: Safeer Data Transport") - to je Python stran
istega protokola kot Kotlin cast/DataTransport.kt. Obe napravi sta ze v krogu zaupanja
(core/link_krog.py), zato kljuca ne izmenjata na novo: sejni kljuc izpeljeta iz ECDH med obstojecima
kljucema P-256 (isti kljuc, ki ga link_krog uporablja za podpisovanje) + dvema nakljucnima nemenoma
(HKDF-SHA256). Sporocili data.offer/data.answer sta podpisani na enak nacin kot vsak drug vnos v
krogu zaupanja (glej link_krog.podatki_clana).

Rele (link.safeer.si) in Hub vidita samo ti dve podpisani sporocili in nato le sifrirane kose;
sejnega kljuca ne dobita nikoli - izpelje ga lahko samo tisti, ki ima zasebni kljuc ene od dveh
naprav. Hub sporocili data.* le posreduje po polju "target" (core/link_hub_streznik.py, splosno
posredovanje - glej _na_sporocilo), tako kot pri share./control./sync.

Zunanje odvisnosti: cryptography (AES-256-GCM; ze "Recommends" v debian/control in ze uporabljena
v link_tls.py in signed_feed.py) in core.link_kripto (ECDH, podpis - cryptography, openssl le rezerva; isto kot
link_krog.podpisi/preveri_podpis). Brez cryptography sifriranje ni mogoce - noben nesifriran
nadomestek ne sme obstajati, zato sifriraj_kos/desifriraj_kos ob manjkajoci knjiznici dvigneta
NapakaPrenosa namesto tihega prehoda na sifriranje po meri.
"""
from __future__ import annotations

import base64
import hashlib
import hmac as _hmac
import os
import time
from dataclasses import dataclass
from typing import List, Optional

from core import link_krog

PROTOKOL = "data-transport-v1"
DOLZINA_KOSA = 1024 * 1024  # 1 MiB, kot v P2P-NACRT.md
NAMEN_DATOTEKA = "file"
NAMEN_ZASLON = "screen"
# Ponudba/odgovor s casovnim zigom starejsim od tega se zavrne - enako obzorje kot pri seznanitvi
# s kodo (PIN_VELJA_MS v HubUsmerjevalnik.kt) je tu prestrogo (prenos lahko caka na potrditev
# uporabnika), zato 5 minut, kot velja povsod drugod v Linku za enkratne izmenjave.
VELJAVNOST_PONUDBE_S = 300.0


class NapakaPrenosa(Exception):
    """Splosna napaka Data Transporta (neveljaven podpis, potekla ponudba, pokvarjen kos, manjka
    cryptography ...). Klicatelj jo lovi kot eno samo napako - vzrok je v sporocilu."""


# ------------------------------------------------------------------ ECDH + HKDF

def _pot_kljuca() -> str:
    """Isti kljuc, ki ga core.link_krog uporablja za podpisovanje vnosov v krogu zaupanja."""
    return link_krog._pot_kljuca()


def _podpisi_s_kljucem(pot_kljuca: str, podatki: bytes) -> str:
    from core import link_kripto
    return base64.b64encode(link_kripto.podpisi(pot_kljuca, podatki)).decode("ascii")


def javni_kljuc_iz_datoteke(pot_kljuca: str) -> str:
    """Javni kljuc (base64 SPKI DER) za dano zasebno datoteko - za preizkuse, ki delajo z zacasnimi
    identitetami, ne s pravim kljucem te naprave (link_krog.javni_kljuc_b64 bi vedno vzel pravega)."""
    from core import link_kripto
    return base64.b64encode(link_kripto.javni_kljuc_der(pot_kljuca)).decode("ascii")


def ecdh_skupna_skrivnost(tuj_kljuc_b64: str, pot_kljuca: Optional[str] = None) -> bytes:
    """ECDH P-256 med nasim zasebnim kljucem (na disku) in tujim javnim kljucem (base64 SPKI DER,
    kot je zapisan v krogu zaupanja). Prek core.link_kripto: cryptography, openssl le kot rezerva,
    zato deluje tudi na Windows. Zasebni kljuc ne zapusti datoteke. Simetricno: A.ecdh(B) == B.ecdh(A)."""
    from core import link_kripto
    pot_kljuca = pot_kljuca or _pot_kljuca()
    try:
        der = base64.b64decode(tuj_kljuc_b64, validate=True)
    except Exception as e:
        raise NapakaPrenosa(f"neveljaven tuj kljuc: {e}") from e
    try:
        skrivnost = link_kripto.ecdh(pot_kljuca, der)
    except Exception as e:
        raise NapakaPrenosa(f"ECDH ni uspel: {e}") from e
    if not skrivnost:
        raise NapakaPrenosa("ECDH ni uspel")
    return skrivnost


def _hkdf(ikm: bytes, sol: bytes, info: bytes, dolzina: int) -> bytes:
    """HKDF-SHA256 (RFC 5869); ista izpeljava kot core.spake2._hkdf, tu namenoma podvojena, da ta
    modul ni odvisen od notranjosti spake2 (drug namen, isti, ze preverjen postopek)."""
    prk = _hmac.new(sol if sol else b"\x00" * 32, ikm, hashlib.sha256).digest()
    izhod, blok, i = b"", b"", 1
    while len(izhod) < dolzina:
        blok = _hmac.new(prk, blok + info + bytes([i]), hashlib.sha256).digest()
        izhod += blok
        i += 1
    return izhod[:dolzina]


@dataclass(frozen=True)
class SejniKljuc:
    """Izpeljani material ene seje: 32-bajtni kljuc AES-256-GCM + 4-bajtna predpona za nonce."""
    kljuc: bytes
    predpona_nonca: bytes

    def nonce(self, stevec: int) -> bytes:
        """12-bajtni nonce za kos `stevec` (0-based, sirok stevec). Predpona (iz HKDF, torej
        odvisna od seje) + stevec je enolicna znotraj ene seje, ce noben stevec ni ponovljen -
        klicatelj ne sme nikoli sifrirati dveh razlicnih kosov z istim stevcem pod istim kljucem."""
        if stevec < 0 or stevec > 0xFFFFFFFFFFFFFFFF:
            raise NapakaPrenosa("neveljaven stevec kosa")
        return self.predpona_nonca + stevec.to_bytes(8, "big")


def izpelji_sejni_kljuc(skupna_skrivnost: bytes, session_id: str, nonce_ponudbe_b64: str,
                         nonce_odgovora_b64: str) -> SejniKljuc:
    """Sejni kljuc iz ECDH skrivnosti + obeh enkratnih nemenov (ponudba + odgovor). Sol = SHA-256
    session_id-ja, da razlicne seje med istima napravama (nov session_id) nikoli ne delita kljuca,
    tudi ce bi katera stran (napaka) ponovila nonce."""
    try:
        nonce_a = base64.b64decode(nonce_ponudbe_b64, validate=True)
        nonce_b = base64.b64decode(nonce_odgovora_b64, validate=True)
    except Exception as e:
        raise NapakaPrenosa(f"neveljaven nonce: {e}") from e
    material = _hkdf(skupna_skrivnost, hashlib.sha256(session_id.encode("utf-8")).digest(),
                      b"safeer-data-transport-v1\n" + nonce_a + nonce_b, 36)
    return SejniKljuc(kljuc=material[:32], predpona_nonca=material[32:36])


# ------------------------------------------------------------------ data.offer / data.answer

def _nakljucno_b64(n: int) -> str:
    return base64.b64encode(os.urandom(n)).decode("ascii")


def podatki_ponudbe(session_id: str, namen: str, od_id: str, do_id: str, nonce_b64: str, ts: float) -> bytes:
    """Kar podpise ponudnik (data.offer); domensko loceno od drugih podpisov v krogu
    (glej link_krog.podatki_clana/podatki_umika - isti vzorec)."""
    return ("safeer-data-offer-v1\n%s\n%s\n%s\n%s\n%s\n%.3f" %
             (session_id, namen, od_id, do_id, nonce_b64, ts)).encode("utf-8")


def podatki_odgovora(session_id: str, od_id: str, do_id: str, nonce_ponudbe_b64: str,
                      nonce_odgovora_b64: str, ts: float) -> bytes:
    """Kar podpise odgovarjajoci (data.answer); veze odgovor na TOCNO to ponudbo (oba nonca), zato
    napadalec ne more sestaviti odgovora iz kosov drugih sej."""
    return ("safeer-data-answer-v1\n%s\n%s\n%s\n%s\n%s\n%.3f" %
             (session_id, od_id, do_id, nonce_ponudbe_b64, nonce_odgovora_b64, ts)).encode("utf-8")


def sestavi_ponudbo(moj_id: str, tuj_id: str, namen: str, pot_kljuca: Optional[str] = None) -> dict:
    """Ustvari podpisano sporocilo data.offer, ki ga posiljatelj poslje prek huba (target=tuj_id).
    `pot_kljuca` je namenjen preizkusom z zacasno identiteto; v produkciji je None (prava naprava)."""
    if namen not in (NAMEN_DATOTEKA, NAMEN_ZASLON):
        raise NapakaPrenosa(f"neznan namen: {namen}")
    pot_kljuca = pot_kljuca or _pot_kljuca()
    session_id = base64.urlsafe_b64encode(os.urandom(16)).decode("ascii").rstrip("=")
    nonce = _nakljucno_b64(16)
    ts = time.time()
    podpis = _podpisi_s_kljucem(pot_kljuca, podatki_ponudbe(session_id, namen, moj_id, tuj_id, nonce, ts))
    return {
        "type": "data.offer",
        "target": tuj_id,
        "payload": {
            "session_id": session_id, "purpose": namen, "from": moj_id, "to": tuj_id,
            "nonce": nonce, "ts": ts, "sig": podpis,
        },
    }


def _tovor(sporocilo: dict) -> dict:
    tovor = sporocilo.get("payload")
    if not isinstance(tovor, dict):
        raise NapakaPrenosa("sporocilu manjka payload")
    return tovor


def sprejmi_ponudbo(sporocilo: dict, moj_id: str, kljuc_ponudnika_b64: str,
                     pot_kljuca: Optional[str] = None,
                     posiljatelj_iz_huba: Optional[str] = None) -> "IzidPonudbe":
    """Preveri prejeto data.offer (podpis, cilj, svezost) in pripravi podpisan data.answer ter
    sejni kljuc. Ne poslje nicesar - klicatelj odgovor poslje prek huba (isti `target` kot je bil
    `from` v ponudbi). `kljuc_ponudnika_b64` mora priti iz kroga zaupanja (link_krog.krog().clan_za_id),
    NIKOLI iz samega sporocila - drugace bi lahko kdorkoli podtaknil svoj kljuc."""
    if sporocilo.get("type") != "data.offer":
        raise NapakaPrenosa("ni data.offer")
    t = _tovor(sporocilo)
    session_id = str(t.get("session_id") or "")
    namen = str(t.get("purpose") or "")
    od_id = str(t.get("from") or "")
    do_id = str(t.get("to") or "")
    nonce = str(t.get("nonce") or "")
    sig = str(t.get("sig") or "")
    try:
        ts = float(t.get("ts"))
    except (TypeError, ValueError):
        raise NapakaPrenosa("neveljaven ts v ponudbi")
    if not (session_id and namen in (NAMEN_DATOTEKA, NAMEN_ZASLON) and od_id and nonce and sig):
        raise NapakaPrenosa("ponudbi manjka polje")
    if do_id != moj_id:
        raise NapakaPrenosa("ponudba ni namenjena tej napravi")
    if posiljatelj_iz_huba and posiljatelj_iz_huba != od_id:
        raise NapakaPrenosa("posiljatelj huba se ne ujema s podpisano ponudbo")
    if abs(time.time() - ts) > VELJAVNOST_PONUDBE_S:
        raise NapakaPrenosa("ponudba je potekla ali ima cas v prihodnosti")
    if not link_krog.preveri_podpis(kljuc_ponudnika_b64,
                                     podatki_ponudbe(session_id, namen, od_id, do_id, nonce, ts), sig):
        raise NapakaPrenosa("podpis ponudbe se ne ujema")

    pot_kljuca = pot_kljuca or _pot_kljuca()
    moj_nonce = _nakljucno_b64(16)
    ts2 = time.time()
    podpis2 = _podpisi_s_kljucem(
        pot_kljuca, podatki_odgovora(session_id, od_id, do_id, nonce, moj_nonce, ts2))
    odgovor = {
        "type": "data.answer",
        "target": od_id,
        "payload": {
            "session_id": session_id, "from": moj_id, "to": od_id,
            "offer_nonce": nonce, "nonce": moj_nonce, "ts": ts2, "sig": podpis2,
        },
    }
    skrivnost = ecdh_skupna_skrivnost(kljuc_ponudnika_b64, pot_kljuca)
    sejni = izpelji_sejni_kljuc(skrivnost, session_id, nonce, moj_nonce)
    return IzidPonudbe(sejni=sejni, odgovor=odgovor, session_id=session_id, namen=namen, tuj_id=od_id)


@dataclass(frozen=True)
class IzidPonudbe:
    sejni: SejniKljuc
    odgovor: dict
    session_id: str
    namen: str
    tuj_id: str


def dokoncaj_ponudbo(ponudba: dict, odgovor_sporocilo: dict, kljuc_prejemnika_b64: str,
                      pot_kljuca: Optional[str] = None,
                      posiljatelj_iz_huba: Optional[str] = None) -> SejniKljuc:
    """Stran ponudnika: iz prejetega data.answer (in svoje poslane ponudbe) izpelje isti sejni
    kljuc. `kljuc_prejemnika_b64` spet mora priti iz kroga zaupanja, ne iz sporocila."""
    if odgovor_sporocilo.get("type") != "data.answer":
        raise NapakaPrenosa("ni data.answer")
    tp = _tovor(ponudba)
    ta = _tovor(odgovor_sporocilo)
    session_id = str(tp.get("session_id") or "")
    moj_id = str(tp.get("from") or "")
    tuj_id = str(tp.get("to") or "")
    nonce_ponudbe = str(tp.get("nonce") or "")
    if str(ta.get("session_id") or "") != session_id:
        raise NapakaPrenosa("odgovor se ne ujema s to ponudbo (session_id)")
    if str(ta.get("from") or "") != tuj_id or str(ta.get("to") or "") != moj_id:
        raise NapakaPrenosa("odgovor ima napacnega posiljatelja ali prejemnika")
    if posiljatelj_iz_huba and posiljatelj_iz_huba != tuj_id:
        raise NapakaPrenosa("posiljatelj huba se ne ujema s podpisanim odgovorom")
    if str(ta.get("offer_nonce") or "") != nonce_ponudbe:
        raise NapakaPrenosa("odgovor ne veze pravega nonca ponudbe")
    nonce_odgovora = str(ta.get("nonce") or "")
    sig = str(ta.get("sig") or "")
    try:
        ts2 = float(ta.get("ts"))
    except (TypeError, ValueError):
        raise NapakaPrenosa("neveljaven ts v odgovoru")
    if not nonce_odgovora or not sig:
        raise NapakaPrenosa("odgovoru manjka polje")
    if abs(time.time() - ts2) > VELJAVNOST_PONUDBE_S:
        raise NapakaPrenosa("odgovor je potekel ali ima cas v prihodnosti")
    if not link_krog.preveri_podpis(
            kljuc_prejemnika_b64,
            podatki_odgovora(session_id, moj_id, tuj_id, nonce_ponudbe, nonce_odgovora, ts2), sig):
        raise NapakaPrenosa("podpis odgovora se ne ujema")

    pot_kljuca = pot_kljuca or _pot_kljuca()
    skrivnost = ecdh_skupna_skrivnost(kljuc_prejemnika_b64, pot_kljuca)
    return izpelji_sejni_kljuc(skrivnost, session_id, nonce_ponudbe, nonce_odgovora)


# ------------------------------------------------------------------ AES-256-GCM kosi

def _aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore
    except Exception as e:
        raise NapakaPrenosa(
            "manjka python3-cryptography: brez nje Data Transport ne sme sifrirati "
            "(noben nesifriran nadomestek ni dovoljen)"
        ) from e
    return AESGCM


def aad_kosa(session_id: str, stevec: int, skupaj_kosov: int, zadnji: bool) -> bytes:
    """Dodatni podpisani (a nesifrirani) podatki enega kosa: vezejo sifrobesedilo na TO sejo IN
    na njegov polozaj/skupno stevilo kosov, da premikanje, podvajanje ali obrezovanje kosov med
    prenosom (tudi na relejem, ki jih sicer samo prenasa) pade pri desifriranju."""
    return ("safeer-data-chunk-v1\n%s\n%d\n%d\n%d" %
             (session_id, stevec, skupaj_kosov, 1 if zadnji else 0)).encode("utf-8")


def sifriraj_kos(sejni: SejniKljuc, stevec: int, cistopis: bytes, aad: bytes = b"") -> bytes:
    return _aesgcm()(sejni.kljuc).encrypt(sejni.nonce(stevec), cistopis, aad)


def desifriraj_kos(sejni: SejniKljuc, stevec: int, sifropis: bytes, aad: bytes = b"") -> bytes:
    try:
        return _aesgcm()(sejni.kljuc).decrypt(sejni.nonce(stevec), sifropis, aad)
    except NapakaPrenosa:
        raise
    except Exception as e:
        raise NapakaPrenosa(f"kos {stevec} se ni desifriral (pokvarjen ali podtaknjen): {e}") from e


def sifriraj_bajte(sejni: SejniKljuc, session_id: str, cistopis: bytes,
                    dolzina_kosa: int = DOLZINA_KOSA) -> List[bytes]:
    """Razdeli na kose po `dolzina_kosa` in vsak kos sifrira posebej (glej aad_kosa). Vrne seznam
    sifropisov (vsak ze vkljucuje 16-bajtni GCM tag); prazen cistopis da en prazen kos, da tudi
    prenos dolzine 0 preverimo enako kot vsakega drugega."""
    deli = [cistopis[i:i + dolzina_kosa] for i in range(0, len(cistopis), dolzina_kosa)] or [b""]
    skupaj = len(deli)
    return [sifriraj_kos(sejni, i, kos, aad_kosa(session_id, i, skupaj, i == skupaj - 1))
            for i, kos in enumerate(deli)]


def desifriraj_bajte(sejni: SejniKljuc, session_id: str, sifropisi: List[bytes]) -> bytes:
    skupaj = len(sifropisi)
    deli = [desifriraj_kos(sejni, i, s, aad_kosa(session_id, i, skupaj, i == skupaj - 1))
            for i, s in enumerate(sifropisi)]
    return b"".join(deli)


def sha256_hex(podatki: bytes) -> str:
    """Zgostitev celotne datoteke po zadnjem kosu (P2P-NACRT.md: 'sele nato se datoteka
    preimenuje v koncno ime')."""
    return hashlib.sha256(podatki).hexdigest()
