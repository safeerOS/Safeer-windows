"""TLS do Safeer Huba: šifrirano in vezano na Hubov ključ, ne na overitelja.

Hub v domačem omrežju nima potrdila od overitelja; ima svoj par ključev in sam sebi
podpisano potrdilo. Naprava ga zato prepozna po prstnem odtisu potrdila (SHA-256):
 - pred seznanitvijo odtisa ne pozna: povezavo sprejme, si odtis zapomni in ga vplete
   v seznanitev (SPAKE2). Če je vmes napadalec s svojim potrdilom, se odtisa razlikujeta
   in seznanitev pade, ne da bi napadalec izvedel kodo;
 - po seznanitvi sprejme samo še potrdilo s tem odtisom. Vse drugo je napaka, ne opozorilo.

Brez zunanjih knjižnic: http.client + ssl iz standardne knjižnice.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import socket
import ssl
from typing import Optional, Tuple
from urllib.parse import urlparse


class NeujemanjeOdtisa(Exception):
    """Hub ima drugo potrdilo, kot je bilo ob seznanitvi."""


def odtis_potrdila(der: bytes) -> str:
    return hashlib.sha256(der).hexdigest()


def _kontekst() -> ssl.SSLContext:
    # Verige do overitelja ni; identiteto potrjuje odtis, ne ime gostitelja.
    k = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    k.check_hostname = False
    k.verify_mode = ssl.CERT_NONE
    k.minimum_version = ssl.TLSVersion.TLSv1_2
    return k


def ovij(vticnik: socket.socket, gostitelj: str, pripeti: Optional[str]) -> Tuple[ssl.SSLSocket, str]:
    """Navaden vtičnik ovije v TLS in preveri odtis. Vrne (vtičnik, videni odtis).

    `pripeti` = None pomeni "še ne poznam" (samo med seznanitvijo): sprejme katerokoli
    potrdilo. Sicer mora biti odtis natanko tak; ob neujemanju vtičnik zapre in dvigne
    NeujemanjeOdtisa.
    """
    s = _kontekst().wrap_socket(vticnik, server_hostname=gostitelj)
    der = s.getpeercert(binary_form=True) or b""
    videni = odtis_potrdila(der) if der else ""
    if not videni or (pripeti is not None and not _isti(videni, pripeti)):
        try:
            s.close()
        except Exception:
            pass
        raise NeujemanjeOdtisa("Safeer Link: Hub ima drugo potrdilo, kot je bilo ob seznanitvi.")
    return s, videni


def potrdilo_pem(ws_naslov: str, pripeti: str) -> str:
    """PEM Hubovega potrdila (samo, ce se ujema s pripetim odtisom) - za WebKit, ki naj ga
    sprejme za stran gledalca zaslona. Prazno, ce se ne ujema ali Huba ni."""
    u = urlparse(ws_naslov)
    gostitelj, vrata = u.hostname or "127.0.0.1", u.port or 443
    try:
        surov = socket.create_connection((gostitelj, vrata), 5.0)
    except OSError:
        return ""
    try:
        s, _ = ovij(surov, gostitelj, pripeti)
    except Exception:
        try:
            surov.close()
        except Exception:
            pass
        return ""
    try:
        der = s.getpeercert(binary_form=True) or b""
        return ssl.DER_cert_to_PEM_cert(der) if der else ""
    finally:
        try:
            s.close()
        except Exception:
            pass


def javni_kljuc_potrdila(der: bytes) -> str:
    """Javni kljuc potrdila (base64 SubjectPublicKeyInfo DER) - za primerjavo s krogom zaupanja.
    Uporabi `cryptography`, ce je, sicer openssl; prazno, ce ne gre."""
    import base64
    try:
        from cryptography import x509  # type: ignore
        from cryptography.hazmat.primitives import serialization  # type: ignore
        k = x509.load_der_x509_certificate(der).public_key()
        return base64.b64encode(k.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode("ascii")
    except Exception:
        pass
    try:
        import subprocess
        pem = subprocess.run(["openssl", "x509", "-inform", "DER", "-pubkey", "-noout"], input=der, check=True, capture_output=True).stdout
        spki = subprocess.run(["openssl", "pkey", "-pubin", "-outform", "DER"], input=pem, check=True, capture_output=True).stdout
        return base64.b64encode(spki).decode("ascii")
    except Exception:
        return ""


def potrdilo_huba(ws_naslov: str, timeout: float = 4.0) -> Tuple[str, str]:
    """(odtis, javni kljuc b64) potrdila, ki ga hub kaze na tem naslovu - brez pripetega odtisa.
    Samo za preverjanje pred zaupanjem: zaupanje da sele ujemanje kljuca s krogom zaupanja."""
    u = urlparse(ws_naslov)
    gostitelj, vrata = u.hostname or "127.0.0.1", u.port or 443
    try:
        surov = socket.create_connection((gostitelj, vrata), timeout)
    except OSError:
        return "", ""
    try:
        s, videni = ovij(surov, gostitelj, None)
    except Exception:
        try:
            surov.close()
        except Exception:
            pass
        return "", ""
    try:
        der = s.getpeercert(binary_form=True) or b""
        return videni, (javni_kljuc_potrdila(der) if der else "")
    finally:
        try:
            s.close()
        except Exception:
            pass


def _isti(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a.lower().encode(), b.lower().encode())


class _PripetaHttps(http.client.HTTPSConnection):
    """HTTPS povezava, ki po rokovanju preveri odtis Hubovega potrdila."""

    def __init__(self, gostitelj: str, vrata: int, pripeti: Optional[str], timeout: float) -> None:
        super().__init__(gostitelj, vrata, timeout=timeout, context=_kontekst())
        self.pripeti = pripeti
        self.videni = ""

    def connect(self) -> None:  # noqa: D401 - http.client API
        surov = socket.create_connection((self.host, self.port), self.timeout)
        try:
            self.sock, self.videni = ovij(surov, self.host, self.pripeti)
        except Exception:
            try:
                surov.close()
            except Exception:
                pass
            raise


def zahteva(url: str, telo: Optional[dict] = None, zeton: Optional[str] = None,
            timeout: float = 5.0, pripeti: Optional[str] = None,
            metoda: Optional[str] = None) -> Tuple[int, dict, str]:
    """HTTP(S) zahteva do Huba. Vrne (koda, json, videni odtis); koda 0 = ni odgovora.

    Za https:// preveri odtis (glej `ovij`). Za http:// odtis ostane prazen; taka
    povezava je dovoljena samo za odkrivanje (je to sploh Hub?), nikoli z žetonom -
    klicatelj z žetonom naj zahteva https.
    """
    u = urlparse(url)
    gostitelj = u.hostname or "127.0.0.1"
    varno = u.scheme == "https"
    vrata = u.port or (443 if varno else 80)
    pot = u.path or "/"
    if u.query:
        pot += "?" + u.query
    if zeton and not varno:
        return 0, {}, ""
    podatki = None if telo is None else json.dumps(telo).encode("utf-8")
    glave = {"Content-Type": "application/json", "Content-Length": str(len(podatki or b""))}
    if zeton:
        glave["X-Safeer-Token"] = zeton
    m = metoda or ("POST" if telo is not None else "GET")
    povezava: http.client.HTTPConnection
    if varno:
        povezava = _PripetaHttps(gostitelj, vrata, pripeti, timeout)
    else:
        povezava = http.client.HTTPConnection(gostitelj, vrata, timeout=timeout)
    try:
        povezava.request(m, pot, body=podatki, headers=glave)
        odgovor = povezava.getresponse()
        vsebina = odgovor.read().decode("utf-8", "replace")
        try:
            j = json.loads(vsebina) if vsebina else {}
        except json.JSONDecodeError:
            j = {}
        if not isinstance(j, dict):
            j = {}
        return odgovor.status, j, getattr(povezava, "videni", "")
    except NeujemanjeOdtisa:
        return 0, {"napaka": "odtis_se_ne_ujema"}, ""
    except Exception:
        return 0, {}, ""
    finally:
        try:
            povezava.close()
        except Exception:
            pass
