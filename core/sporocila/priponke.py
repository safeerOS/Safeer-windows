"""Priponke e-poste: zgradba pisma (IMAP BODYSTRUCTURE), imena datotek, dekodiranje dela in posiljanje.

Prej (do 15. 10. 2026) smo priponke iskali samo v prvih 64 KB pisma: priponka za tem mejo (vecina pravih priponk) ali
v odrezanem drevesu MIME se ni pokazala, prenesti pa je ni bilo mogoce. Zdaj zgradbo pove streznik (BODYSTRUCTURE,
RFC 3501 7.4.2) ne glede na velikost pisma, prenesemo pa samo izbrani del (BODY.PEEK[<del>]) - kot Gmail in Outlook.

Standardna knjiznica nima razclenjevalnika odgovorov IMAP; imaplib vrne surove kose. Tu je majhen, strpen
razclenjevalnik (oklepaji, nizi v narekovajih, dobesedni nizi {n}, NIL, atomi z [..]) in razlaga zgradbe za
Gmail, Outlook/Exchange, Dovecot: gnezdeni multipart/mixed+related+alternative, slike v vrstici s Content-ID,
priponke brez Content-Disposition (samo name=), imena po RFC 2231 in RFC 2047, posredovana pisma (message/rfc822).
"""
from __future__ import annotations

import binascii
import mimetypes
import quopri
import re
from email.header import decode_header, make_header
from email.utils import collapse_rfc2231_value, decode_params
from typing import Any, Dict, List, Optional, Tuple

#: Najvec skupaj prilozenih datotek v enem pismu (Gmail, Outlook.com: 25 MB; vecje streznik zavrne).
NAJVEC_PRILOG = 25 * 1024 * 1024
#: Kos pri prenosu dela (BODY.PEEK[del]<odmik.dolzina>): napredek za velike priponke in zmeren pomnilnik.
KOS_PRENOSA = 512 * 1024
#: Varovalo: vec od tega en del ne more biti (streznik ali napaka v zanki).
NAJVEC_DEL = 512 * 1024 * 1024

#: Podpisi in sifrirni ovoji: niso priponke za uporabnika (Gmail in Outlook jih ne kazeta kot datoteke).
_PODPISI = {"application/pgp-signature", "application/pkcs7-signature", "application/x-pkcs7-signature",
            "application/pgp-encrypted"}


# ---------------------------------------------------------------------------------------------- razclenjevalnik
class NapakaRazclenjevanja(ValueError):
    pass


def zdruzi_odgovor(podatki) -> bytes:
    """Kose iz imaplib (bajti in pari (vrstica do {n}, dobesedni niz)) zlozi nazaj v obliko z zice.

    imaplib vrstico, ki se konca z {n}, in n bajtov za njo vrne kot par; nadaljevanje vrstice za dobesednim nizom je
    naslednji kos. Med kose damo presledek: dobesedni niz je cel zeton, presledek za njim ne spremeni pomena."""
    deli = []
    for kos in podatki or []:
        if kos is None:
            continue
        if isinstance(kos, tuple):
            glava = kos[0] if isinstance(kos[0], bytes) else str(kos[0]).encode("latin-1", "replace")
            vsebina = kos[1] if len(kos) > 1 and isinstance(kos[1], bytes) else b""
            # imaplib je prebral tocno toliko bajtov, kolikor jih je napovedal {n}: dolzino vzamemo iz vsebine, da
            # razclenjevanje ne zavisi od glave (in deluje tudi z rocno sestavljenimi odgovori v preizkusih).
            glava = re.sub(rb"~?\{\d+\+?\}\s*$", b"{%d}" % len(vsebina), glava)
            deli.append(glava + b"\r\n" + vsebina)
        elif isinstance(kos, bytes):
            deli.append(kos)
        else:
            deli.append(str(kos).encode("latin-1", "replace"))
    return b" ".join(deli)


class _Bralnik:
    def __init__(self, b: bytes):
        self.b, self.i = b, 0

    def presledki(self) -> None:
        while self.i < len(self.b) and self.b[self.i] in b" \t\r\n":
            self.i += 1

    def konec(self) -> bool:
        self.presledki()
        return self.i >= len(self.b)

    def vrednost(self, globina: int = 0):
        if globina > 64:
            raise NapakaRazclenjevanja("pregloboko")
        self.presledki()
        if self.i >= len(self.b):
            raise NapakaRazclenjevanja("konec")
        z = self.b[self.i:self.i + 1]
        if z == b"(":
            self.i += 1
            seznam = []
            while True:
                self.presledki()
                if self.i >= len(self.b):
                    raise NapakaRazclenjevanja("manjka )")
                if self.b[self.i:self.i + 1] == b")":
                    self.i += 1
                    return seznam
                seznam.append(self.vrednost(globina + 1))
        if z == b")":
            raise NapakaRazclenjevanja("odvecen )")
        if z == b'"':
            return self._niz()
        if z == b"{" or (z == b"~" and self.b[self.i + 1:self.i + 2] == b"{"):
            return self._dobesedno()
        return self._atom()

    def _niz(self) -> bytes:
        self.i += 1
        izid = bytearray()
        while self.i < len(self.b):
            z = self.b[self.i]
            if z == 0x5C and self.i + 1 < len(self.b):     # \" in \\
                izid.append(self.b[self.i + 1])
                self.i += 2
                continue
            if z == 0x22:
                self.i += 1
                return bytes(izid)
            izid.append(z)
            self.i += 1
        raise NapakaRazclenjevanja("niz brez konca")

    def _dobesedno(self) -> bytes:
        if self.b[self.i:self.i + 1] == b"~":
            self.i += 1
        m = re.compile(rb"\{(\d+)\+?\}\r?\n").match(self.b, self.i)
        if not m:
            raise NapakaRazclenjevanja("dobesedni niz")
        n = int(m.group(1))
        zacetek = m.end()
        if zacetek + n > len(self.b):
            raise NapakaRazclenjevanja("kratek dobesedni niz")
        self.i = zacetek + n
        return self.b[zacetek:zacetek + n]

    def _atom(self):
        zacetek = self.i
        while self.i < len(self.b):
            z = self.b[self.i:self.i + 1]
            if z == b"[":                       # BODY[HEADER.FIELDS (DATE)] - oklepaji v [] so del atoma
                konec = self.b.find(b"]", self.i)
                self.i = len(self.b) if konec < 0 else konec + 1
                continue
            if z in (b" ", b"(", b")", b"\r", b"\n", b'"'):
                break
            self.i += 1
        atom = self.b[zacetek:self.i].decode("latin-1")
        if not atom:
            raise NapakaRazclenjevanja("prazen atom")
        return None if atom.upper() == "NIL" else atom


def razcleni(b: bytes):
    """Ena vrednost IMAP (za preizkuse in BODYSTRUCTURE, ki ga dobimo samega)."""
    return _Bralnik(b).vrednost()


def razcleni_fetch(podatki) -> List[Dict[str, Any]]:
    """Odgovor na (UID) FETCH -> [{"UID": "5", "FLAGS": [...], "BODYSTRUCTURE": [...], "BODY[]<0>": b"..."}].

    Kljuci so imena podatkov z velikimi crkami. Nerazumljiv ostanek odgovora se izpusti (ne podre sinhronizacije)."""
    bralnik = _Bralnik(zdruzi_odgovor(podatki))
    izid = []
    while not bralnik.konec():
        try:
            st = bralnik.vrednost()
            if isinstance(st, str) and st.upper() == "FETCH":     # odgovor z »FETCH« (imaplib ga sicer odreze)
                st = bralnik.vrednost()
            vrednosti = bralnik.vrednost()
        except NapakaRazclenjevanja:
            break
        if not isinstance(vrednosti, list):
            continue
        sporocilo: Dict[str, Any] = {}
        for i in range(0, len(vrednosti) - 1, 2):
            ime = vrednosti[i]
            if isinstance(ime, bytes):
                ime = ime.decode("latin-1")
            if isinstance(ime, str):
                sporocilo[ime.upper()] = vrednosti[i + 1]
        izid.append(sporocilo)
    return izid


def vsebina_dela(sporocilo: Dict[str, Any]) -> Optional[bytes]:
    """Vsebina BODY[...] iz enega odgovora (ne glede na odmik <n>); None, ce je ni."""
    for kljuc, vrednost in sporocilo.items():
        if kljuc.startswith("BODY[") and isinstance(vrednost, (bytes, type(None))):
            return vrednost if vrednost is not None else b""
    return None


# ---------------------------------------------------------------------------------------------- imena in besedila
def niz(v) -> str:
    """Niz iz zgradbe: UTF-8 (RFC 6855, Gmail posilja 8-bitno), sicer Latin-1 (nic se ne izgubi)."""
    if v is None:
        return ""
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8")
        except UnicodeDecodeError:
            return v.decode("latin-1")
    return str(v)


def _besede(ime: str) -> str:
    """RFC 2047 (=?UTF-8?B?...?=) tudi v parametrih, kjer ga standard ne dovoli - Outlook in Gmail ga posiljata."""
    if "=?" not in ime:
        return ime
    try:
        return str(make_header(decode_header(ime)))
    except Exception:  # noqa: BLE001 - pokvarjeno kodiranje: ostane, kot je
        return ime


def parametri(seznam) -> Dict[str, str]:
    """(k1 v1 k2 v2 ...) -> {k: v} z razvozlanimi nadaljevanji RFC 2231 (filename*0*, filename*1 ...)."""
    if not isinstance(seznam, list):
        return {}
    pari = []
    for i in range(0, len(seznam) - 1, 2):
        k, v = niz(seznam[i]).strip(), niz(seznam[i + 1])
        if k:
            pari.append((k.lower(), v))
    if not pari:
        return {}
    try:
        # decode_params pricakuje vrednost glave kot prvi par; vrne vrednosti v narekovajih, RFC 2231 kot
        # (charset, jezik, besedilo) - na koncu seznama, zato razsirjeno ime (filename*) prepise navadno (filename).
        razvozlano = decode_params([("x", "")] + [(k, '"%s"' % v.replace("\\", "\\\\").replace('"', '\\"'))
                                                   for k, v in pari])[1:]
    except Exception:  # noqa: BLE001
        razvozlano = [(k, '"%s"' % v) for k, v in pari]
    izid = {}
    for k, v in razvozlano:
        try:
            v = collapse_rfc2231_value(v, errors="replace", fallback_charset="utf-8")
        except Exception:  # noqa: BLE001
            v = v[2] if isinstance(v, tuple) else str(v)
        v = str(v)
        if len(v) >= 2 and v[0] == v[-1] == '"':      # Python 3.12: vrednost RFC 2231 ostane v narekovajih
            v = v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        izid[k.rstrip("*")] = _besede(v)
    return izid


def _koncnica(tip: str) -> str:
    k = mimetypes.guess_extension(tip, strict=False) or ""
    return {".jpe": ".jpg", ".jfif": ".jpg", ".ksh": ".txt", ".bat": ".txt"}.get(k, k)


def ocena_velikosti(velikost: int, kodiranje: str) -> int:
    """Velikost datoteke iz velikosti kodiranega dela: base64 v vrsticah po 76 znakov = 57 bajtov na 78 bajtov."""
    if velikost <= 0:
        return 0
    if kodiranje == "base64":
        return velikost * 57 // 78
    return velikost


# ---------------------------------------------------------------------------------------------- zgradba pisma
def _dispozicija(polja: list, od: int) -> Tuple[str, Dict[str, str]]:
    """Razsiritveni del enodelnega telesa: prvi seznam oblike ("attachment"|"inline" (parametri)). Nekateri streizniki
    (stari Exchange) ga postavijo na napacno mesto, zato ga iscemo, ne beremo s fiksnega indeksa."""
    for v in polja[od:]:
        if isinstance(v, list) and v and isinstance(v[0], (bytes, str)) and (len(v) == 1 or isinstance(v[1], (list, type(None)))):
            ime = niz(v[0]).lower()
            if ime in ("attachment", "inline") or (ime and len(v) == 2 and isinstance(v[1], list)):
                return ime, parametri(v[1] if len(v) > 1 else None)
    return "", {}


def zgradba(bs) -> Dict[str, Any]:
    """Razlaga BODYSTRUCTURE: {"priponke": [...], "besedilo": {"del", "kodiranje", "charset"} | None, "html": ...}.

    Priponka: {"ime", "tip", "velikost", "kodirano", "del", "kodiranje", "inline", "cid"}; "del" je stevilka dela za
    BODY[<del>], "velikost" ocena velikosti datoteke, "kodirano" velikost na strezniku (za napredek prenosa)."""
    izid: Dict[str, Any] = {"priponke": [], "besedilo": None, "html": None}
    if isinstance(bs, list):
        _obdelaj(bs, "", izid, "mixed", 0)
    return izid


def _obdelaj(d: list, stevilka: str, izid: dict, starsevski: str, globina: int) -> None:
    if globina > 40 or not d:
        return
    if isinstance(d[0], list):                                   # multipart: (del)(del)... "podvrsta" [razsiritve]
        otroci = []
        for v in d:
            if isinstance(v, list):
                otroci.append(v)
            else:
                break
        podvrsta = niz(d[len(otroci)]).lower() if len(d) > len(otroci) else "mixed"
        for i, otrok in enumerate(otroci, 1):
            _obdelaj(otrok, (stevilka + "." if stevilka else "") + str(i), izid, podvrsta, globina + 1)
        return
    if len(d) < 7:
        return
    stevilka = stevilka or "1"
    tip = (niz(d[0]) + "/" + niz(d[1])).lower()
    par = parametri(d[2])
    cid = niz(d[3]).strip().strip("<>")
    kodiranje = niz(d[5]).lower()
    try:
        velikost = int(niz(d[6]) or 0)
    except ValueError:
        velikost = 0
    # Razsiritve so za stevilom vrstic (text/*) oz. ovojnico in telesom (message/rfc822); iscemo od 7. polja naprej,
    # ker stevilo vrstic in ovojnica nista seznama oblike (ime (parametri)).
    disp, dpar = _dispozicija(d, 7)
    ime = dpar.get("filename") or par.get("name") or ""
    if tip in _PODPISI:
        return
    priponka = False
    inline = False
    if tip == "message/rfc822":
        priponka = True
        if not ime:
            ovojnica = d[7] if len(d) > 7 and isinstance(d[7], list) else []
            zadeva = _besede(niz(ovojnica[1])) if len(ovojnica) > 1 else ""
            ime = (zadeva.strip() or "sporocilo")[:120] + ".eml"
    elif disp == "attachment":
        priponka = True
    elif tip.startswith("text/") and not ime:
        # Telo pisma (prvo besedilo in prvi HTML zunaj priponk).
        if tip == "text/plain" and izid["besedilo"] is None and disp != "attachment":
            izid["besedilo"] = {"del": stevilka, "kodiranje": kodiranje, "charset": par.get("charset", ""), "velikost": velikost}
        elif tip == "text/html" and izid["html"] is None and disp != "attachment":
            izid["html"] = {"del": stevilka, "kodiranje": kodiranje, "charset": par.get("charset", ""), "velikost": velikost}
        return
    elif tip.startswith("image/") and cid and disp != "attachment" and (starsevski == "related" or disp == "inline" or not ime):
        priponka, inline = True, True
    elif ime:
        priponka = True                                          # brez Content-Disposition, samo name= (Outlook)
    elif tip.startswith(("multipart/", "text/")):
        return
    elif disp == "inline" or tip.startswith(("image/", "application/", "audio/", "video/")):
        priponka = True                                          # brez imena: ime dobi po vrsti
    if not priponka:
        return
    if not ime:
        ime = ("slika" if tip.startswith("image/") else "priponka") + _koncnica(tip)
    izid["priponke"].append({"ime": ime, "tip": tip, "velikost": ocena_velikosti(velikost, kodiranje),
                             "kodirano": velikost, "del": stevilka, "kodiranje": kodiranje, "inline": inline, "cid": cid})


# ---------------------------------------------------------------------------------------------- dekodiranje
class Dekodirnik:
    """Sprotno dekodiranje prenosnega kodiranja (Content-Transfer-Encoding) po kosih poljubne dolzine."""

    def __init__(self, kodiranje: str):
        self.kodiranje = (kodiranje or "").lower().strip()
        self._ostanek = b""

    def vnesi(self, kos: bytes) -> bytes:
        if self.kodiranje == "base64":
            podatki = self._ostanek + re.sub(rb"[^A-Za-z0-9+/=]", b"", kos)
            cel = len(podatki) - len(podatki) % 4
            self._ostanek = podatki[cel:]
            return _b64(podatki[:cel])
        if self.kodiranje == "quoted-printable":
            podatki = self._ostanek + kos
            konec = podatki.rfind(b"\n")
            if konec < 0:
                self._ostanek = podatki
                return b""
            self._ostanek = podatki[konec + 1:]
            return quopri.decodestring(podatki[:konec + 1])
        return kos

    def koncaj(self) -> bytes:
        ostanek, self._ostanek = self._ostanek, b""
        if not ostanek:
            return b""
        if self.kodiranje == "base64":
            return _b64(ostanek + b"=" * (-len(ostanek) % 4))
        if self.kodiranje == "quoted-printable":
            return quopri.decodestring(ostanek)
        return ostanek


def _b64(podatki: bytes) -> bytes:
    """base64 po skupinah: polnilo »=« sredi toka (zlepljeni kosi pri nekaterih odjemalcih) ne ustavi dekodiranja."""
    if not podatki:
        return b""
    if b"=" not in podatki[:-2]:
        try:
            return binascii.a2b_base64(podatki)
        except binascii.Error:
            pass
    izid = bytearray()
    for i in range(0, len(podatki), 4):
        skupina = podatki[i:i + 4]
        try:
            izid += binascii.a2b_base64(skupina + b"=" * (-len(skupina) % 4))
        except binascii.Error:
            continue
    return bytes(izid)


def dekodiraj(podatki: bytes, kodiranje: str) -> bytes:
    d = Dekodirnik(kodiranje)
    return d.vnesi(podatki) + d.koncaj()


# ---------------------------------------------------------------------------------------------- posiljanje
def mime_za(ime: str) -> Tuple[str, str]:
    tip = mimetypes.guess_type(ime, strict=False)[0] or "application/octet-stream"
    glavni, _, pod = tip.partition("/")
    return (glavni or "application"), (pod or "octet-stream")


def dodaj_priloge(msg, priloge) -> List[dict]:
    """Datoteke iz [{"pot"}] priloži pismu (EmailMessage). Vrne opis prilog za Sporocilo; izjema ValueError s kodo
    »prilog_ni« (datoteke ni) ali »priloge_prevelike« (skupaj vec kot NAJVEC_PRILOG)."""
    import os
    opis, skupaj, datoteke = [], 0, []
    for p in priloge or ():
        pot = str((p or {}).get("pot") or "") if isinstance(p, dict) else str(p or "")
        pot = os.path.realpath(os.path.expanduser(pot))
        if not pot or not os.path.isfile(pot):
            raise ValueError("prilog_ni")
        velikost = os.path.getsize(pot)
        skupaj += velikost
        if skupaj > NAJVEC_PRILOG:
            raise ValueError("priloge_prevelike")
        datoteke.append((pot, velikost))
    for pot, velikost in datoteke:
        ime = os.path.basename(pot)
        glavni, pod = mime_za(ime)
        with open(pot, "rb") as f:
            vsebina = f.read(NAJVEC_PRILOG + 1)
        msg.add_attachment(vsebina, maintype=glavni, subtype=pod, filename=ime)
        opis.append({"ime": ime, "tip": glavni + "/" + pod, "velikost": velikost, "lokalno": pot})
    return opis


def datoteke_prilog(priloge, najvec_ena: int, najvec_skupaj: int = 0) -> List[dict]:
    """Priloge s strani -> [{"pot", "ime", "velikost", "tip"}] za kanale, ki datoteko nalozijo sami (Telegram,
    Matrix). ValueError »prilog_ni« ali »priloga_prevelika_kanal« (vec, kot kanal sprejme), preden gre kaj na splet."""
    import os
    izid, skupaj = [], 0
    for p in priloge or ():
        pot = str((p or {}).get("pot") or "") if isinstance(p, dict) else str(p or "")
        pot = os.path.realpath(os.path.expanduser(pot))
        if not pot or not os.path.isfile(pot):
            raise ValueError("prilog_ni")
        velikost = os.path.getsize(pot)
        skupaj += velikost
        if velikost > najvec_ena or (najvec_skupaj and skupaj > najvec_skupaj):
            raise ValueError("priloga_prevelika_kanal")
        glavni, pod = mime_za(os.path.basename(pot))
        izid.append({"pot": pot, "ime": os.path.basename(pot), "velikost": velikost, "tip": glavni + "/" + pod})
    return izid


def vecdelni_obrazec(polja: dict, ime_polja: str, ime: str, tip: str, vsebina: bytes) -> Tuple[bytes, str]:
    """multipart/form-data (RFC 7578) brez dodatnih knjiznic: (telo, Content-Type)."""
    import uuid
    meja = "safeer" + uuid.uuid4().hex
    deli = []
    for k, v in polja.items():
        deli.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (meja, k, v)).encode("utf-8"))
    varno = ime.replace("\\", "_").replace('"', "_").replace("\r", " ").replace("\n", " ")
    deli.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\nContent-Type: %s\r\n\r\n"
                 % (meja, ime_polja, varno, tip)).encode("utf-8") + vsebina + b"\r\n")
    deli.append(("--%s--\r\n" % meja).encode("ascii"))
    return b"".join(deli), "multipart/form-data; boundary=" + meja
