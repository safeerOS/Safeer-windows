"""Adapter za uradni Chatwoot Application API in njegove webhooke."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Callable, Iterable, Optional, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .adapter import Adapter
from .model import Pogovor, Sporocilo
from . import skrivnosti


class ChatwootAdapter(Adapter):
    vrsta = "chatwoot"
    zmore = {"poslji", "priponke", "realni_cas"}

    def __init__(self, kanal_id: str, url: str, account_id: int, zeton: str = "",
                 vnos_zetona: Optional[Callable[[], str]] = None, timeout: float = 15):
        self.kanal_id = kanal_id
        self.url = url.rstrip("/")
        self.account_id = int(account_id)
        self._zeton, self._vnos_zetona = zeton, vnos_zetona
        self.timeout = timeout
        self.webhooki = []

    @property
    def kljuc_skrivnosti(self): return "chatwoot:" + self.kanal_id

    def shrani_zeton(self, zeton: str) -> bool:
        self._zeton = zeton
        return skrivnosti.shrani(self.kljuc_skrivnosti, zeton)

    def _skrivnost(self):
        return skrivnosti.zahtevaj(self.kljuc_skrivnosti, self._zeton, self._vnos_zetona)

    def _api(self, pot: str, metoda: str = "GET", podatki=None):
        telo = None if podatki is None else json.dumps(podatki, ensure_ascii=False).encode("utf-8")
        zahteva = Request(self.url + "/api/v1/accounts/" + str(self.account_id) + pot,
                          data=telo, method=metoda,
                          headers={"api_access_token": self._skrivnost(), "Content-Type": "application/json",
                                   "Accept": "application/json"})
        with urlopen(zahteva, timeout=self.timeout) as odgovor:  # nosec: URL izrecno nastavi uporabnik
            surovo = odgovor.read()
        return json.loads(surovo.decode("utf-8")) if surovo else {}

    def povezi(self) -> None:
        self._api("/conversations?status=all&page=1")

    @staticmethod
    def _seznam(odgovor):
        if isinstance(odgovor, list): return odgovor
        if not isinstance(odgovor, dict): return []
        korist = odgovor.get("data", {}).get("payload") if isinstance(odgovor.get("data"), dict) else odgovor.get("payload")
        return korist if isinstance(korist, list) else []

    def pogovori(self, od: Optional[str] = None) -> Iterable[Pogovor]:
        poizvedba = {"status": "all", "page": 1}
        if od: poizvedba["since"] = od
        odgovor = self._api("/conversations?" + urlencode(poizvedba))
        rezultat = []
        for p in self._seznam(odgovor):
            meta = p.get("meta") if isinstance(p.get("meta"), dict) else {}
            stik = meta.get("sender") if isinstance(meta.get("sender"), dict) else {}
            oseba = str(stik.get("id") or stik.get("email") or stik.get("phone_number") or "neznan")
            zadnje = p.get("last_non_activity_message") or {}
            cas = zadnje.get("created_at") or p.get("timestamp") or p.get("created_at") or ""
            if isinstance(cas, (int, float)):
                cas = datetime.fromtimestamp(cas, timezone.utc).isoformat()
            rezultat.append(Pogovor(str(p.get("id", "")), self.kanal_id, oseba,
                                     str(p.get("custom_attributes", {}).get("subject", "") if isinstance(p.get("custom_attributes"), dict) else ""),
                                     str(zadnje.get("content") or ""), int(p.get("unread_count") or 0), str(cas)))
        return rezultat

    def sporocila(self, pogovor_id: str, pred: Optional[str] = None,
                  najvec: int = 50) -> Iterable[Sporocilo]:
        pot = "/conversations/" + str(pogovor_id) + "/messages"
        if pred: pot += "?before=" + str(pred)
        odgovor = self._api(pot)
        rezultat = []
        for s in self._seznam(odgovor)[-max(1, min(int(najvec), 200)):]:
            cas = s.get("created_at", "")
            if isinstance(cas, (int, float)): cas = datetime.fromtimestamp(cas, timezone.utc).isoformat()
            rezultat.append(Sporocilo(str(s.get("id", "")), str(pogovor_id),
                "ven" if int(s.get("message_type", 0) or 0) == 1 else "noter", str(s.get("content") or ""), str(cas),
                [{"ime": a.get("file_name", "priponka"), "tip": a.get("file_type", ""), "url": a.get("data_url", "")}
                 for a in (s.get("attachments") or []) if isinstance(a, dict)], str(s.get("status") or "prejeto")))
        return rezultat

    def poslji(self, pogovor_id: str, besedilo: str,
               priponke: Sequence[dict] = ()) -> Sporocilo:
        # Application API sprejme vsebino; priponke z datotekami zahtevajo multipart in niso
        # tiho pretvorjene v neuradne URL-je. URL-priponke lahko posreduje klicatelj.
        podatki = {"content": besedilo, "message_type": "outgoing", "private": False}
        if priponke: podatki["attachments"] = list(priponke)
        s = self._api("/conversations/" + str(pogovor_id) + "/messages", "POST", podatki)
        cas = s.get("created_at", datetime.now(timezone.utc).isoformat())
        if isinstance(cas, (int, float)): cas = datetime.fromtimestamp(cas, timezone.utc).isoformat()
        return Sporocilo(str(s.get("id", "")), str(pogovor_id), "ven", str(s.get("content") or besedilo),
                         str(cas), list(s.get("attachments") or []), str(s.get("status") or "poslano"))

    def oznaci_prebrano(self, pogovor_id: str) -> None:
        self._api("/conversations/" + str(pogovor_id) + "/update_last_seen", "POST", {})

    def sprejmi_webhook(self, telo) -> bool:
        """Sprejme ze preverjeno JSON telo HTTP ovojnice; omrezni streznik ostane zamenljiv."""
        if isinstance(telo, (bytes, str)):
            telo = json.loads(telo.decode() if isinstance(telo, bytes) else telo)
        if not isinstance(telo, dict) or not str(telo.get("event", "")).startswith(("message_", "conversation_")):
            return False
        self.webhooki.append(telo)
        return True
