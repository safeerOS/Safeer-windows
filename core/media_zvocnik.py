"""Medijski center -> zvocnik v omrezju (DLNA, npr. JBL BAR 300): »Predvajaj na zvocniku«.

Zvocnik skladbo ali radio potegne sam (javni http(s) naslov). Datoteko s tega racunalnika mu ponudi
majhen streznik (core/dlna_zvocniki.StreznikDatotek) samo pod nakljucnim zetonom, dokler igra.
Ce zvocnik ta trenutek igra drug vir (npr. TV), brez potrditve ne preklopimo.
"""

from __future__ import annotations

import ipaddress
import os
import threading
import time
import urllib.parse
from typing import Callable, Dict, List, Optional

from core import dlna_zvocniki as dlna

OSVEZI_S = 60.0


def _domaci_https(url: str) -> bool:
    """https na domacem naslovu (samopodpisano potrdilo) zvocnik ne more preveriti."""
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https":
        return False
    try:
        return ipaddress.ip_address(p.hostname or "").is_private
    except ValueError:
        return (p.hostname or "").endswith(".local") or p.hostname == "localhost"


def _lokalni_http(url: str) -> bool:
    return urllib.parse.urlsplit(url).hostname in ("127.0.0.1", "localhost", "::1")


class MediaZvocniki:
    def __init__(self, najdi: Callable[..., list] = dlna.najdi, streznik=dlna.StreznikDatotek,
                 lan_naslov: Callable[[str], str] = dlna.lan_naslov_za) -> None:
        self._najdi = najdi
        self._streznik_razred = streznik
        self._lan_naslov = lan_naslov
        self._zvocniki: Dict[str, object] = {}
        self._iskano = 0.0
        self._isce = False
        self._kljuc = threading.RLock()
        self._streznik = None
        self.aktivni = None

    # ------------------------------------------------------------------ seznam
    def osvezi(self, pocakaj: bool = False) -> None:
        with self._kljuc:
            if self._isce:
                return
            self._isce = True

        def _isci() -> None:
            try:
                najdeni = {z.udn: z for z in self._najdi(3.0)}
                with self._kljuc:
                    if self.aktivni is not None:
                        najdeni.setdefault(self.aktivni.udn, self.aktivni)
                    self._zvocniki = najdeni
            except Exception:
                pass
            finally:
                with self._kljuc:
                    self._iskano, self._isce = time.monotonic(), False

        if pocakaj:
            _isci()
        else:
            threading.Thread(target=_isci, name="safeer-media-zvocniki", daemon=True).start()

    def seznam(self, pocakaj: bool = False) -> List[dict]:
        if pocakaj and not self._zvocniki:
            self.osvezi(pocakaj=True)
        elif time.monotonic() - self._iskano > OSVEZI_S:
            self.osvezi()
        with self._kljuc:
            return [{"id": z.udn, "ime": z.ime or z.model, "model": z.model,
                     "aktiven": self.aktivni is not None and self.aktivni.udn == z.udn}
                    for z in sorted(self._zvocniki.values(), key=lambda z: z.ime)]

    # ------------------------------------------------------------------ predvajanje
    def predvajaj(self, item: dict, udn: str, potrdi: bool = False) -> dict:
        with self._kljuc:
            z = self._zvocniki.get(udn)
        if z is None:
            return {"ok": False, "napaka": "ni_zvocnika"}
        url = str(item.get("url") or "")
        pot = str(item.get("pot") or "")
        mime = str(item.get("mime") or "")
        if not potrdi:
            try:
                if z.stanje() == "PLAYING":
                    uri = str(z.polozaj().get("TrackURI") or "")
                    if uri and not uri.lower().startswith(("http://", "https://")):
                        return {"ok": False, "vir": uri}
            except Exception:
                pass
        streznik = None
        if pot and os.path.isfile(pot) and (not url or _lokalni_http(url) or url.startswith("file:")):
            streznik = self._streznik_razred(pot, self._lan_naslov(z.naslov)).__enter__()
            url = streznik.url
        elif not url.lower().startswith(("http://", "https://")) or _domaci_https(url) or _lokalni_http(url):
            return {"ok": False, "napaka": "vir_ni_za_zvocnik"}
        if not mime.startswith("audio/"):
            mime = "audio/mpeg"
        try:
            z.predvajaj(url, str(item.get("naslov") or ""), str(item.get("izvajalec") or ""), mime)
        except Exception as e:
            if streznik is not None:
                streznik.__exit__(None, None, None)
            return {"ok": False, "napaka": str(e)[:200]}
        with self._kljuc:
            self._ustavi_streznik()
            self._streznik, self.aktivni = streznik, z
        return {"ok": True, "ime": z.ime}

    def _ustavi_streznik(self) -> None:
        if self._streznik is not None:
            try:
                self._streznik.__exit__(None, None, None)
            except Exception:
                pass
            self._streznik = None

    def dejanje(self, kaj: str) -> dict:
        z = self.aktivni
        if z is None:
            return {"ok": False}
        try:
            if kaj == "premor":
                (z.premor if z.stanje() == "PLAYING" else z.nadaljuj)()
            elif kaj in ("glasneje", "tisje"):
                z.nastavi_glasnost(z.glasnost() + (5 if kaj == "glasneje" else -5))
            elif kaj == "ustavi":
                z.ustavi()
                with self._kljuc:
                    self._ustavi_streznik()
                    self.aktivni = None
            return {"ok": True, "glasnost": z.glasnost() if kaj != "ustavi" else None}
        except Exception as e:
            return {"ok": False, "napaka": str(e)[:200]}
