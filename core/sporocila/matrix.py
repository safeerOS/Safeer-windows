"""Matrix (odprt protokol, Client-Server API v3) - »Lastni API«: uporabnik vpise naslov svojega streznika
(homeserver) in zeton dostopa (access token), ki ga dobi v svojem odjemalcu (Element: Nastavitve › Pomoc in
o programu › Dostopni zeton) ali z lastno prijavo. Safeer ne ustvari racuna in ne shrani gesla.

Sinhronizacija: /sync s casovno oznako `since` (v stanju kanala) in filtrom (zadnjih 30 dogodkov na sobo).
Sobe = pogovori; pri zasebnih sobah (m.direct ali 2 clana) je oseba drugi clan, sicer soba sama.
Posiljanje: PUT /rooms/{id}/send/m.room.message/{txn}. Prebrano: POST /rooms/{id}/receipt/m.read/{event}.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional, Sequence
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .adapter import Adapter
from .model import Pogovor, Sporocilo
from . import skrivnosti

NAJVEC_NA_SOBO = 200


class NapakaPrijave(RuntimeError):
    pass


class MatrixAdapter(Adapter):
    vrsta = "matrix"
    zmore = {"poslji"}

    def __init__(self, kanal_id: str, streznik: str, zeton: str = "", vnos_zetona: Optional[Callable[[], str]] = None,
                 timeout: float = 20):
        self.kanal_id = kanal_id
        self.streznik = streznik.rstrip("/")
        self._zeton, self._vnos_zetona = zeton, vnos_zetona
        self.timeout = timeout
        self.uporabnik = ""
        self._since = ""
        self._sobe: dict = {}      # room_id -> {"ime", "oseba", "clani": {uid: ime}, "sporocila": [Sporocilo], "neprebrano", "zadnji_event"}
        self._imena: dict = {}     # uid -> prikazno ime

    @property
    def kljuc_skrivnosti(self): return "matrix:" + self.kanal_id

    def shrani_zeton(self, zeton: str) -> bool:
        self._zeton = zeton
        return skrivnosti.shrani(self.kljuc_skrivnosti, zeton)

    def pozabi_zeton(self) -> None:
        skrivnosti.pozabi(self.kljuc_skrivnosti)

    def _skrivnost(self):
        return skrivnosti.zahtevaj(self.kljuc_skrivnosti, self._zeton, self._vnos_zetona)

    def _api(self, pot: str, metoda: str = "GET", podatki=None, parametri: Optional[dict] = None, timeout: Optional[float] = None):
        url = self.streznik + "/_matrix/client/v3" + pot + ("?" + urlencode(parametri) if parametri else "")
        telo = None if podatki is None else json.dumps(podatki, ensure_ascii=False).encode("utf-8")
        zahteva = Request(url, data=telo, method=metoda, headers={"Authorization": "Bearer " + self._skrivnost(),
                                                                   "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urlopen(zahteva, timeout=timeout or self.timeout) as odgovor:  # nosec: streznik izrecno nastavi uporabnik
                surovo = odgovor.read()
        except Exception as e:  # noqa: BLE001
            koda = getattr(e, "code", 0)
            if koda in (401, 403):
                raise NapakaPrijave("Žeton ni sprejet") from e
            raise
        return json.loads(surovo.decode("utf-8")) if surovo else {}

    # ---- stanje (trajno prek storitve) ----
    def stanje(self) -> dict:
        return {"since": self._since, "uporabnik": self.uporabnik,
                "sobe": {rid: {"ime": s["ime"], "oseba": s["oseba"], "clani": s["clani"], "neprebrano": s["neprebrano"], "zadnji_event": s["zadnji_event"],
                               "sporocila": [m.slovar() for m in s["sporocila"][-NAJVEC_NA_SOBO:]]} for rid, s in self._sobe.items()},
                "imena": self._imena}

    def obnovi(self, stanje: dict) -> None:
        self._since = str(stanje.get("since") or ""); self.uporabnik = str(stanje.get("uporabnik") or "")
        self._imena = dict(stanje.get("imena") or {})
        for rid, s in (stanje.get("sobe") or {}).items():
            self._sobe[rid] = {"ime": s.get("ime", ""), "oseba": s.get("oseba", rid), "clani": dict(s.get("clani") or {}),
                               "neprebrano": int(s.get("neprebrano") or 0), "zadnji_event": s.get("zadnji_event", ""),
                               "sporocila": [Sporocilo.iz_slovarja(m) for m in (s.get("sporocila") or [])]}

    # ---- povezava ----
    def povezi(self) -> None:
        if not self.streznik.startswith("https://") and not self.streznik.startswith("http://localhost") and not self.streznik.startswith("http://127."):
            raise ValueError("Naslov strežnika se mora začeti s https://")
        kdo = self._api("/account/whoami")
        self.uporabnik = str(kdo.get("user_id") or "")
        if not self.uporabnik:
            raise NapakaPrijave("Žeton ni sprejet")

    def ime_osebe(self, oseba_id: str) -> str:
        return self._imena.get(oseba_id) or (self._sobe.get(oseba_id, {}).get("ime") if oseba_id in self._sobe else "") or ""

    # ---- sinhronizacija ----
    def _sync(self) -> None:
        filt = json.dumps({"room": {"timeline": {"limit": 30}, "ephemeral": {"types": []}, "state": {"types": ["m.room.name", "m.room.member", "m.room.canonical_alias"], "lazy_load_members": True}},
                           "presence": {"types": []}, "account_data": {"types": ["m.direct"]}}, separators=(",", ":"))
        parametri = {"filter": filt, "timeout": "0"}
        if self._since:
            parametri["since"] = self._since
        odg = self._api("/sync", parametri=parametri, timeout=max(self.timeout, 30))
        self._since = str(odg.get("next_batch") or self._since)
        direktne = {}
        for dogodek in ((odg.get("account_data") or {}).get("events") or []):
            if dogodek.get("type") == "m.direct" and isinstance(dogodek.get("content"), dict):
                for uid, sobe in dogodek["content"].items():
                    for rid in sobe or []:
                        direktne[rid] = uid
        for rid, soba in ((odg.get("rooms") or {}).get("join") or {}).items():
            s = self._sobe.setdefault(rid, {"ime": "", "oseba": rid, "clani": {}, "neprebrano": 0, "zadnji_event": "", "sporocila": []})
            dogodki = list((soba.get("state") or {}).get("events") or []) + list((soba.get("timeline") or {}).get("events") or [])
            for d in dogodki:
                tip, vsebina = d.get("type"), d.get("content") if isinstance(d.get("content"), dict) else {}
                if tip == "m.room.name" and vsebina.get("name"):
                    s["ime"] = str(vsebina["name"])
                elif tip == "m.room.member":
                    uid = str(d.get("state_key") or "")
                    if uid:
                        if vsebina.get("membership") in ("join", "invite"):
                            s["clani"][uid] = str(vsebina.get("displayname") or uid)
                            self._imena[uid] = s["clani"][uid]
                        else:
                            s["clani"].pop(uid, None)
            znani = {m.id for m in s["sporocila"]}
            for d in (soba.get("timeline") or {}).get("events") or []:
                if d.get("type") != "m.room.message" or d.get("event_id") in znani:
                    continue
                vsebina = d.get("content") if isinstance(d.get("content"), dict) else {}
                besedilo = str(vsebina.get("body") or "")
                if vsebina.get("msgtype") in ("m.image", "m.file", "m.video", "m.audio"):
                    priponke = [{"ime": besedilo or "priponka", "url": str(vsebina.get("url") or "")}]
                    besedilo = "📎 " + besedilo
                else:
                    priponke = []
                cas = datetime.fromtimestamp(int(d.get("origin_server_ts") or 0) / 1000, timezone.utc).isoformat()
                od = str(d.get("sender") or "")
                s["sporocila"].append(Sporocilo(str(d.get("event_id")), rid, "ven" if od == self.uporabnik else "noter", besedilo, cas, priponke,
                                                 "poslano" if od == self.uporabnik else "prejeto"))
                if od != self.uporabnik:
                    s["neprebrano"] += 1
                s["zadnji_event"] = str(d.get("event_id"))
            s["sporocila"] = s["sporocila"][-NAJVEC_NA_SOBO:]
            drugi = [u for u in s["clani"] if u != self.uporabnik]
            if rid in direktne or len(drugi) == 1:
                s["oseba"] = direktne.get(rid) or drugi[0]
                if not s["ime"]:
                    s["ime"] = self._imena.get(s["oseba"], s["oseba"])
            else:
                s["oseba"] = rid
                if not s["ime"]:
                    s["ime"] = ", ".join(s["clani"][u] for u in drugi[:3]) or rid
                self._imena[rid] = s["ime"]
        for rid in ((odg.get("rooms") or {}).get("leave") or {}):
            self._sobe.pop(rid, None)

    def pogovori(self, od: Optional[str] = None) -> Iterable[Pogovor]:
        zacetni = not self._since
        self._sync()
        if zacetni and self._since:
            # Synapse zacetni /sync nekaj minut streze iz predpomnilnika (lahko je zastarel); inkrementalni
            # sync od next_batch takoj prinese, kar je v vmesnem casu prislo (preverjeno na lokalnem Synapse).
            self._sync()
        izid = []
        for rid, s in self._sobe.items():
            zadnje = s["sporocila"][-1] if s["sporocila"] else None
            izid.append(Pogovor(rid, self.kanal_id, s["oseba"], "" if s["oseba"] != rid else s["ime"],
                                zadnje.besedilo if zadnje else "", s["neprebrano"], zadnje.cas if zadnje else ""))
            s["neprebrano"] = 0   # storitev sesteva inkrementalno (obnovi -> prej + novo)
        return izid

    def sporocila(self, pogovor_id: str, pred: Optional[str] = None, najvec: int = 50) -> Iterable[Sporocilo]:
        return list(self._sobe.get(pogovor_id, {}).get("sporocila", []))[-max(1, min(int(najvec), NAJVEC_NA_SOBO)):]

    def poslji(self, pogovor_id: str, besedilo: str, priponke: Sequence[dict] = ()) -> Sporocilo:
        txn = "safeer-" + uuid.uuid4().hex
        odg = self._api("/rooms/" + quote(pogovor_id, safe="") + "/send/m.room.message/" + txn, "PUT", {"msgtype": "m.text", "body": besedilo})
        s = Sporocilo(str(odg.get("event_id") or txn), pogovor_id, "ven", besedilo, datetime.now(timezone.utc).isoformat(), [], "poslano")
        soba = self._sobe.setdefault(pogovor_id, {"ime": "", "oseba": pogovor_id, "clani": {}, "neprebrano": 0, "zadnji_event": "", "sporocila": []})
        soba["sporocila"].append(s)
        return s

    def oznaci_prebrano(self, pogovor_id: str) -> None:
        zadnji = self._sobe.get(pogovor_id, {}).get("zadnji_event")
        if zadnji:
            try:
                self._api("/rooms/" + quote(pogovor_id, safe="") + "/receipt/m.read/" + quote(zadnji, safe=""), "POST", {})
            except Exception:
                pass
