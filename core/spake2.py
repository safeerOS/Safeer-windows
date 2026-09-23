"""SPAKE2 (RFC 9382) nad krivuljo P-256 za seznanjanje v Safeer Linku.

Zakaj: 6-mestna koda, ki jo televizor pokaže in jo uporabnik vtipka, ne sme nikoli
potovati po omrežju - niti šifrirana. S SPAKE2 obe strani iz kode izpeljeta skupni
ključ; kdor kode ne pozna (napadalec v omrežju, tudi "človek v sredini"), iz
izmenjanih sporočil ne izve nič in kode ne more uganiti "brez povezave": vsak
poskus zahteva nov krog s Hubom, ki poskuse šteje.

Brez zunanjih knjižnic: aritmetika na P-256 z Pythonovimi celimi števili. Enak
zapis kot Spake2.kt v brskalnikih za Android; oba preverja isti testni vektor.

Uporaba (odjemalec = naprava, ki se priključuje; strežnik = Hub):
    o = Spake2.odjemalec(koda, identiteta_odjemalca, identiteta_huba, odtis_tls)
    pa = o.sporocilo()                     # pošlji Hubu
    kljuc, potrditev = o.zakljuci(pb)     # pb od Huba; potrditev pošlji Hubu
    o.preveri(potrditev_huba)              # True, če Hub pozna isto kodo
"""

from __future__ import annotations

import hashlib
import hmac
import os
import struct
from typing import Optional, Tuple

P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
A = P - 3
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5

# Točki M in N iz RFC 9382, razdelek 6 (P-256).
_M_HEX = "02886e2f97ace46e55ba9dd7242579f2993b64e16ef3dcab95afd497333d8fa12f"
_N_HEX = "03d8bbd6c639c62937b04d997f38c3770719c629d7014d49a24b4f98baa1292b49"

Tocka = Optional[Tuple[int, int]]  # None = točka v neskončnosti


def _inv(a: int) -> int:
    return pow(a % P, P - 2, P)


def _sestej(p1: Tocka, p2: Tocka) -> Tocka:
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2:
        if (y1 + y2) % P == 0:
            return None
        lam = (3 * x1 * x1 + A) * _inv(2 * y1) % P
    else:
        lam = (y2 - y1) * _inv(x2 - x1) % P
    x3 = (lam * lam - x1 - x2) % P
    y3 = (lam * (x1 - x3) - y1) % P
    return (x3, y3)


def _pomnozi(k: int, tocka: Tocka) -> Tocka:
    k %= N
    rezultat: Tocka = None
    osnova = tocka
    while k:
        if k & 1:
            rezultat = _sestej(rezultat, osnova)
        osnova = _sestej(osnova, osnova)
        k >>= 1
    return rezultat


def _negiraj(t: Tocka) -> Tocka:
    return None if t is None else (t[0], (-t[1]) % P)


def _na_krivulji(t: Tocka) -> bool:
    if t is None:
        return False
    x, y = t
    return 0 <= x < P and 0 <= y < P and (y * y - (x * x * x + A * x + B)) % P == 0


def kodiraj(t: Tocka) -> bytes:
    if t is None:
        raise ValueError("točke v neskončnosti ni mogoče kodirati")
    return b"\x04" + t[0].to_bytes(32, "big") + t[1].to_bytes(32, "big")


def dekodiraj(b: bytes) -> Tocka:
    if len(b) == 65 and b[0] == 4:
        t = (int.from_bytes(b[1:33], "big"), int.from_bytes(b[33:65], "big"))
    elif len(b) == 33 and b[0] in (2, 3):
        x = int.from_bytes(b[1:], "big")
        y2 = (x * x * x + A * x + B) % P
        y = pow(y2, (P + 1) // 4, P)
        if (y * y - y2) % P != 0:
            raise ValueError("točka ni na krivulji")
        if (y & 1) != (b[0] & 1):
            y = P - y
        t = (x, y)
    else:
        raise ValueError("neveljaven zapis točke")
    if not _na_krivulji(t):
        raise ValueError("točka ni na krivulji")
    # Grupa P-256 ima kofaktor 1, zato je vsaka točka na krivulji v pravi podgrupi.
    return t


G = (GX, GY)
M = dekodiraj(bytes.fromhex(_M_HEX))
NN = dekodiraj(bytes.fromhex(_N_HEX))


def _dolz(b: bytes) -> bytes:
    return struct.pack("<Q", len(b)) + b


def w_iz_kode(koda: str, sol: bytes) -> int:
    """w = MHF(koda) mod n. Koda je kratka, zato jo pred tem raztegnemo (PBKDF2) s soljo
    seje (pair_id), da isti prepis ne velja v dveh sejah; glavno zaščito pa daje SPAKE2 sam."""
    surovo = hashlib.pbkdf2_hmac("sha256", koda.strip().encode("utf-8"), sol if sol else b"\x00", 20000, dklen=48)
    return int.from_bytes(surovo, "big") % N


class Spake2:
    """Ena stran protokola. `jaz`/`oni` sta identiteti (npr. id naprave / id huba)."""

    def __init__(self, w: int, jaz: bytes, oni: bytes, aad: bytes, strezniska: bool, x: Optional[int] = None) -> None:
        self.w = w
        self.jaz = jaz
        self.oni = oni
        self.aad = aad
        self.strezniska = strezniska
        self.x = x if x is not None else (int.from_bytes(os.urandom(48), "big") % (N - 1)) + 1
        # Stran A (Hub, strežnik) uporablja M, stran B (naprava) N - kot v RFC 9382.
        maska = M if strezniska else NN
        self.moja: Tocka = _sestej(_pomnozi(self.x, G), _pomnozi(self.w, maska))
        self.ke: Optional[bytes] = None
        self.kca: Optional[bytes] = None
        self.kcb: Optional[bytes] = None
        self.tt: Optional[bytes] = None

    @classmethod
    def odjemalec(cls, koda: str, jaz: str, hub: str, aad: bytes = b"", sol: bytes = b"") -> "Spake2":
        return cls(w_iz_kode(koda, sol), jaz.encode(), hub.encode(), aad, strezniska=False)

    @classmethod
    def streznik(cls, koda: str, jaz: str, odjemalec: str, aad: bytes = b"", sol: bytes = b"") -> "Spake2":
        return cls(w_iz_kode(koda, sol), jaz.encode(), odjemalec.encode(), aad, strezniska=True)

    def sporocilo(self) -> bytes:
        return kodiraj(self.moja)

    def zakljuci(self, njihovo: bytes) -> Tuple[bytes, bytes]:
        """Vrne (skupni ključ Ke, moja potrditev). Ob neveljavni točki dvigne ValueError."""
        njihova = dekodiraj(njihovo)
        maska_njih = NN if self.strezniska else M
        k = _pomnozi(self.x, _sestej(njihova, _negiraj(_pomnozi(self.w, maska_njih))))
        if k is None:
            raise ValueError("neveljaven skupni element")
        # V transkriptu je A vedno strežnik (Hub) in B odjemalec, kot v RFC.
        if self.strezniska:
            a, b_, pa, pb = self.jaz, self.oni, self.moja, njihova
        else:
            a, b_, pa, pb = self.oni, self.jaz, njihova, self.moja
        w_b = (self.w % N).to_bytes(32, "big")
        self.tt = (_dolz(a) + _dolz(b_) + _dolz(kodiraj(pa)) + _dolz(kodiraj(pb))
                   + _dolz(kodiraj(k)) + _dolz(w_b))
        h = hashlib.sha256(self.tt).digest()
        self.ke, ka = h[:16], h[16:]
        kc = _hkdf(ka, b"", b"ConfirmationKeys" + self.aad, 32)
        self.kca, self.kcb = kc[:16], kc[16:]
        moj = self.kca if self.strezniska else self.kcb
        return self.ke, hmac.new(moj, self.tt, hashlib.sha256).digest()

    def preveri(self, njihova_potrditev: bytes) -> bool:
        if self.tt is None:
            return False
        njihov = self.kcb if self.strezniska else self.kca
        return hmac.compare_digest(hmac.new(njihov, self.tt, hashlib.sha256).digest(), njihova_potrditev)


def _hkdf(ikm: bytes, sol: bytes, info: bytes, dolzina: int) -> bytes:
    prk = hmac.new(sol if sol else b"\x00" * 32, ikm, hashlib.sha256).digest()
    izhod, blok, i = b"", b"", 1
    while len(izhod) < dolzina:
        blok = hmac.new(prk, blok + info + bytes([i]), hashlib.sha256).digest()
        izhod += blok
        i += 1
    return izhod[:dolzina]
