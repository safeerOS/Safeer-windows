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
    """Zamenja le privzeti kontekst za odhodni HTTPS (urllib/http.client).

    Globalno vbrizganje (truststore.inject_into_ssl) ne pride v postev: zamenja tudi strezniske kontekste
    in tiste s pripetim lastnim certifikatom (Safeer Link, oddaljeni zaslon) - zaslon se potem ne odzove.
    """
    global _ze
    if _ze or sys.platform != "win32":
        return ""
    _ze = True
    try:
        import truststore  # type: ignore

        def s_sistemom():
            return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

        s_sistemom()  # preveri, da deluje, preden ga nastavimo
        ssl._create_default_https_context = s_sistemom
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

    def s_koreni():
        kontekst = ssl.create_default_context()
        try:
            kontekst.load_verify_locations(cafile=pot)
        except Exception:
            pass
        return kontekst

    ssl._create_default_https_context = s_koreni
    return "certifi"
