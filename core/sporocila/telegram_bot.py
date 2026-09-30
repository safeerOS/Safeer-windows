"""Telegram Bot API (uradna, brezplacna pot) - »Lastni API«: uporabnik pri @BotFather ustvari bota in vpise
njegov zeton. Bot prejema sporocila, ki mu jih ljudje posljejo (zasebno ali v skupinah, kjer je clan), in nanje
odgovarja. To NI uporabnikov osebni Telegram racun (za tega bi bil potreben TDLib in api_id).

Bot API nima zgodovine: sporocila dobimo z getUpdates (odmik `offset` v stanju kanala) in jih hranimo lokalno.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional, Sequence
from urllib.request import Request, urlopen

from .adapter import Adapter
from .model import Pogovor, Sporocilo
from . import skrivnosti

NAJVEC_NA_KLEPET = 200


class NapakaPrijave(RuntimeError):
    pass


class TelegramBotAdapter(Adapter):
    vrsta = "telegram_bot"
    zmore = {"poslji"}

    def __init__(self, kanal_id: str, zeton: str = "", vnos_zetona: Optional[Callable[[], str]] = None, timeout: float = 20):
        self.kanal_id = kanal_id
        self._zeton, self._vnos_zetona = zeton, vnos_zetona
        self.timeout = timeout
        self.bot = {}
        self._offset = 0
        self._klepeti: dict = {}   # chat_id -> {"ime", "oseba", "sporocila": [], "neprebrano"}
        self._imena: dict = {}

    @property
    def kljuc_skrivnosti(self): return "telegram_bot:" + self.kanal_id

    def shrani_zeton(self, zeton: str) -> bool:
        self._zeton = zeton
        return skrivnosti.shrani(self.kljuc_skrivnosti, zeton)

    def pozabi_zeton(self) -> None:
        skrivnosti.pozabi(self.kljuc_skrivnosti)

    def _skrivnost(self):
        return skrivnosti.zahtevaj(self.kljuc_skrivnosti, self._zeton, self._vnos_zetona)

    def _api(self, metoda: str, podatki: Optional[dict] = None, timeout: Optional[float] = None) -> dict:
        telo = json.dumps(podatki or {}, ensure_ascii=False).encode("utf-8")
        zahteva = Request("https://api.telegram.org/bot" + self._skrivnost() + "/" + metoda, data=telo, method="POST",
                          headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urlopen(zahteva, timeout=timeout or self.timeout) as odgovor:
                surovo = odgovor.read()
        except Exception as e:  # noqa: BLE001
            if getattr(e, "code", 0) in (401, 404):
                raise NapakaPrijave("Žeton bota ni sprejet") from e
            raise
        odg = json.loads(surovo.decode("utf-8")) if surovo else {}
        if not odg.get("ok"):
            raise RuntimeError(str(odg.get("description") or "Telegram napaka"))
        return odg.get("result")

    def stanje(self) -> dict:
        return {"offset": self._offset, "bot": self.bot, "imena": self._imena,
                "klepeti": {cid: {"ime": k["ime"], "oseba": k["oseba"], "neprebrano": k["neprebrano"],
                                  "sporocila": [m.slovar() for m in k["sporocila"][-NAJVEC_NA_KLEPET:]]} for cid, k in self._klepeti.items()}}

    def obnovi(self, stanje: dict) -> None:
        self._offset = int(stanje.get("offset") or 0); self.bot = dict(stanje.get("bot") or {}); self._imena = dict(stanje.get("imena") or {})
        for cid, k in (stanje.get("klepeti") or {}).items():
            self._klepeti[cid] = {"ime": k.get("ime", ""), "oseba": k.get("oseba", cid), "neprebrano": int(k.get("neprebrano") or 0),
                                  "sporocila": [Sporocilo.iz_slovarja(m) for m in (k.get("sporocila") or [])]}

    def povezi(self) -> None:
        self.bot = self._api("getMe") or {}
        if not self.bot.get("id"):
            raise NapakaPrijave("Žeton bota ni sprejet")

    def ime_osebe(self, oseba_id: str) -> str:
        return self._imena.get(oseba_id, "")

    @staticmethod
    def _ime_uporabnika(u: dict) -> str:
        return " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or (("@" + u["username"]) if u.get("username") else str(u.get("id", "")))

    def _prenesi(self) -> None:
        posodobitve = self._api("getUpdates", {"offset": self._offset, "timeout": 0, "allowed_updates": ["message", "edited_message"]}, timeout=max(self.timeout, 30)) or []
        for u in posodobitve:
            self._offset = max(self._offset, int(u.get("update_id") or 0) + 1)
            m = u.get("message") or u.get("edited_message")
            if not isinstance(m, dict):
                continue
            klepet = m.get("chat") or {}
            cid = str(klepet.get("id") or "")
            if not cid:
                continue
            k = self._klepeti.setdefault(cid, {"ime": "", "oseba": cid, "neprebrano": 0, "sporocila": []})
            od = m.get("from") or {}
            if klepet.get("type") == "private":
                k["oseba"] = "tg:" + str(od.get("id") or cid); k["ime"] = self._ime_uporabnika(od); self._imena[k["oseba"]] = k["ime"]
            else:
                k["oseba"] = "tg-skupina:" + cid; k["ime"] = str(klepet.get("title") or cid); self._imena[k["oseba"]] = k["ime"]
            besedilo = str(m.get("text") or m.get("caption") or "")
            priponke = []
            for vrsta in ("document", "photo", "video", "audio", "voice"):
                if m.get(vrsta):
                    priponke.append({"ime": (m[vrsta].get("file_name") if isinstance(m[vrsta], dict) else vrsta) or vrsta}); besedilo = besedilo or "📎 " + vrsta
            if klepet.get("type") != "private" and od:
                besedilo = self._ime_uporabnika(od) + ": " + besedilo
            mid = str(m.get("message_id"))
            if any(s.id == mid for s in k["sporocila"]):
                continue
            cas = datetime.fromtimestamp(int(m.get("date") or 0), timezone.utc).isoformat()
            lasten = self.bot and od.get("id") == self.bot.get("id")
            k["sporocila"].append(Sporocilo(mid, cid, "ven" if lasten else "noter", besedilo, cas, priponke, "poslano" if lasten else "prejeto"))
            k["sporocila"] = k["sporocila"][-NAJVEC_NA_KLEPET:]
            if not lasten:
                k["neprebrano"] += 1

    def pogovori(self, od: Optional[str] = None) -> Iterable[Pogovor]:
        self._prenesi()
        izid = []
        for cid, k in self._klepeti.items():
            zadnje = k["sporocila"][-1] if k["sporocila"] else None
            izid.append(Pogovor(cid, self.kanal_id, k["oseba"], "" if k["oseba"].startswith("tg:") else k["ime"],
                                zadnje.besedilo if zadnje else "", k["neprebrano"], zadnje.cas if zadnje else ""))
            k["neprebrano"] = 0
        return izid

    def sporocila(self, pogovor_id: str, pred: Optional[str] = None, najvec: int = 50) -> Iterable[Sporocilo]:
        return list(self._klepeti.get(pogovor_id, {}).get("sporocila", []))[-max(1, min(int(najvec), NAJVEC_NA_KLEPET)):]

    def poslji(self, pogovor_id: str, besedilo: str, priponke: Sequence[dict] = ()) -> Sporocilo:
        odg = self._api("sendMessage", {"chat_id": int(pogovor_id) if pogovor_id.lstrip("-").isdigit() else pogovor_id, "text": besedilo}) or {}
        s = Sporocilo(str(odg.get("message_id") or ""), pogovor_id, "ven", besedilo,
                      datetime.fromtimestamp(int(odg.get("date") or 0), timezone.utc).isoformat() if odg.get("date") else datetime.now(timezone.utc).isoformat(), [], "poslano")
        self._klepeti.setdefault(pogovor_id, {"ime": "", "oseba": pogovor_id, "neprebrano": 0, "sporocila": []})["sporocila"].append(s)
        return s

    def oznaci_prebrano(self, pogovor_id: str) -> None:
        pass   # Bot API nima potrdil o branju
