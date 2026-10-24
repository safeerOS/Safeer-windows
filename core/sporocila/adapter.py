"""Pogodba, ki jo izpolni vsak komunikacijski kanal."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Iterable, Optional, Sequence, Set

from .model import Pogovor, Sporocilo


def varen_streznik(url: str) -> bool:
    """Naslov, kamor smemo poslati zeton: https:// ali http:// samo na tem racunalniku (ime tocno »localhost« ali
    povratni IP, tudi ::1). Preverjanje z startswith je spustilo http://127.zlo.tld in http://localhost.zlo.tld -
    zeton bi sel v cistopisu na tuj streznik (pregled 14. 10. 2026)."""
    import ipaddress
    from urllib.parse import urlsplit
    try:
        deli = urlsplit(str(url or "").strip())
        gostitelj = deli.hostname or ""
        deli.port  # noqa: B018 - neveljavna vrata sprozijo ValueError
    except ValueError:
        return False
    if not gostitelj or deli.username or deli.password:
        return False
    if deli.scheme == "https":
        return True
    if deli.scheme != "http":
        return False
    if gostitelj == "localhost":
        return True
    try:
        return ipaddress.ip_address(gostitelj).is_loopback
    except ValueError:
        return False


def odpri_brez_preusmeritev(zahteva, timeout=None):
    """urlopen za zahteve z zetonom: urllib ob preusmeritvi glavo Authorization prenese na nov (tudi tuj) naslov,
    zato preusmeritve zavrnemo (3xx -> HTTPError)."""
    from urllib.request import HTTPRedirectHandler, build_opener

    class _BrezPreusmeritve(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
            return None
    return build_opener(_BrezPreusmeritve).open(zahteva, timeout=timeout)


#: Varovalo pri prenosu priponke po HTTP (Telegram Bot API dovoli 20 MB, Matrix streznik obicajno 50-100 MB).
NAJVEC_HTTP_PRIPONKA = 512 * 1024 * 1024


def prenesi_url(url: str, pisi: Callable[[bytes], None], napredek: Optional[Callable[[int], None]] = None,
                glave: Optional[dict] = None, timeout: float = 30) -> int:
    """Prenos priponke po kosih (samo https:// ali povratni naslov, brez preusmeritev - zahteva lahko nosi zeton)."""
    from urllib.request import Request
    if not varen_streznik(url):
        raise ValueError("ni_varno")
    zahteva = Request(url, headers=dict(glave or {}, Accept="*/*"))
    skupaj = 0
    with odpri_brez_preusmeritev(zahteva, timeout=timeout) as odgovor:
        while True:
            kos = odgovor.read(256 * 1024)
            if not kos:
                break
            skupaj += len(kos)
            if skupaj > NAJVEC_HTTP_PRIPONKA:
                raise ValueError("prevelik")
            pisi(kos)
            if napredek is not None:
                napredek(skupaj)
    return skupaj


class Adapter(ABC):
    vrsta: str = ""
    zmore: Set[str] = set()

    @abstractmethod
    def povezi(self) -> None:
        """Vzpostavi povezavo oziroma preveri nastavitve."""

    @abstractmethod
    def pogovori(self, od: Optional[str] = None) -> Iterable[Pogovor]:
        pass

    @abstractmethod
    def sporocila(self, pogovor_id: str, pred: Optional[str] = None,
                  najvec: int = 50) -> Iterable[Sporocilo]:
        pass

    @abstractmethod
    def poslji(self, pogovor_id: str, besedilo: str,
               priponke: Sequence[dict] = ()) -> Sporocilo:
        pass

    @abstractmethod
    def oznaci_prebrano(self, pogovor_id: str) -> None:
        pass

    def prenesi_priponko(self, sporocilo_id: str, priponka: dict, pisi: Callable[[bytes], None],
                         napredek: Optional[Callable[[int], None]] = None) -> int:
        """Vsebino priponke poda pisi() po kosih; vrne stevilo bajtov. Kanal, ki tega ne zna, sprozi NotImplementedError."""
        raise NotImplementedError("ni_podprto")
