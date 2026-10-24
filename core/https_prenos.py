"""Prenos datoteke, ki jo potem zazenemo ali ji zaupamo (program, model, potrdilo): vsak skok preusmeritve samo https.

SHA-256 vsake take datoteke je pripet v kodi in preverjen pred uporabo, zato podtaknjena vsebina ne gre skozi. Brez
tega pa bi preusmeritev lahko zahtevo poslala na http, kjer jo vidi in spremeni vsak na poti (obramba v globino,
neodvisni pregled 19. 10. 2026; enako kot core/os_github_programi in core/os_posodobitve za njune prenose). Naslova
cilja (notranji ali javni) ne preverjamo: pripeta SHA-256 zadosca, posiljamo pa samo GET brez poverilnic.
"""
from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request


class SamoHttps(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme.lower() != "https":
            raise urllib.error.HTTPError(req.full_url, code, "preusmeritev brez https ni dovoljena", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def odpri(zahteva, timeout: float = 30):
    """urlopen samo za https: zacetni naslov in vsak skok preusmeritve."""
    url = zahteva.full_url if isinstance(zahteva, urllib.request.Request) else str(zahteva)
    if urllib.parse.urlsplit(url).scheme.lower() != "https":
        raise ValueError("prenos samo prek https")
    return urllib.request.build_opener(SamoHttps()).open(zahteva, timeout=timeout)  # nosec B310 - samo https
