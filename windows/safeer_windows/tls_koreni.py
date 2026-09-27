"""Zaupanja vredni korenski certifikati za Python na Windows.

Python na Windows bere le korene, ki so ze v sistemski shrambi. Windows manjkajoce korene (npr. GoDaddy G2
za archive.org) nalozi sele, ko jih zahteva CryptoAPI - Python tega ne sprozi, zato je bila povezava do
Internet Archive "self-signed certificate in certificate chain", v brskalniku pa je delovala.

1. truststore: preverjanje prepusti Windows (kot brskalnik), manjkajoce korene nalozi sam.
2. sicer: sistemski koreni + Mozillin seznam (certifi, ki ga ima vsak pip).
Preverjanje ostane vklopljeno - nikoli ga ne izklopimo.
"""
from __future__ import annotations

import ssl
import sys

_ze = False


def namesti() -> str:
    global _ze
    if _ze or sys.platform != "win32":
        return ""
    _ze = True
    try:
        import truststore  # type: ignore
        truststore.inject_into_ssl()
        return "truststore"
    except Exception:
        pass
    pot = ""
    for ime in ("certifi", "pip._vendor.certifi"):
        try:
            modul = __import__(ime, fromlist=["where"])
            pot = modul.where()
            break
        except Exception:
            continue
    if not pot:
        return ""
    izvirni = ssl.create_default_context

    def s_koreni(*a, **k):
        kontekst = izvirni(*a, **k)
        try:
            kontekst.load_verify_locations(cafile=pot)
        except Exception:
            pass
        return kontekst

    ssl.create_default_context = s_koreni
    ssl._create_default_https_context = s_koreni  # urllib brez izrecnega konteksta
    return "certifi"
