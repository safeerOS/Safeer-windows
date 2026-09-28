"""Safeer Chat prek obstojece avtenticirane povezave Safeer Link.

Ne ustvarja kljucev in ne uvaja nove kriptografske sheme: sporocila ``chat.send`` ter
``chat.list`` potujejo po isti podpisano vzpostavljeni seji kot ostali ukazi Linka.
"""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
import uuid
from typing import Iterable, Optional, Sequence

from .adapter import Adapter
from .model import Pogovor, Sporocilo

NAJVEC_BESEDILA = 16 * 1024
NAJVEC_SEZNAMA = 200


def preveri_tovor(tovor: dict) -> dict:
    if not isinstance(tovor, dict): raise ValueError("Neveljavno sporočilo")
    besedilo = str(tovor.get("text") or tovor.get("besedilo") or "")
    if not besedilo or len(besedilo.encode("utf-8")) > NAJVEC_BESEDILA:
        raise ValueError("Sporočilo je prazno ali preveliko")
    return {"conversation": str(tovor.get("conversation") or tovor.get("pogovor_id") or "")[:128],
            "text": besedilo, "created_at": str(tovor.get("created_at") or datetime.now(timezone.utc).isoformat())[:64]}


class SafeerChatAdapter(Adapter):
    vrsta = "safeer"
    zmore = {"poslji", "realni_cas"}

    def __init__(self, kanal_id: str, povezava=None, db=None):
        self.kanal_id, self.povezava = kanal_id, povezava
        self._db = db or sqlite3.connect(":memory:", check_same_thread=False)
        with self._db:
            self._db.execute("""CREATE TABLE IF NOT EXISTS safeer_chat (
                id TEXT PRIMARY KEY, pogovor_id TEXT, smer TEXT, besedilo TEXT, cas TEXT, oseba_id TEXT)""")

    def povezi(self) -> None:
        if self.povezava is None: raise RuntimeError("Safeer Link ni povezan")

    def sprejmi(self, sporocilo: dict) -> Sporocilo:
        telo = preveri_tovor(sporocilo.get("payload") or {})
        sid = str(sporocilo.get("id") or uuid.uuid4())
        oseba = str(sporocilo.get("sender") or "neznan")
        pogovor = telo["conversation"] or oseba
        s = Sporocilo(sid, pogovor, "noter", telo["text"], telo["created_at"], [], "prejeto")
        self._zapisi(s, oseba)
        return s

    def _zapisi(self, s: Sporocilo, oseba=""):
        with self._db:
            self._db.execute("INSERT OR REPLACE INTO safeer_chat VALUES(?,?,?,?,?,?)",
                             (s.id, s.pogovor_id, s.smer, s.besedilo, s.cas, oseba))

    def pogovori(self, od: Optional[str] = None) -> Iterable[Pogovor]:
        vrstice = self._db.execute("""SELECT pogovor_id,MAX(cas) cas,
            (SELECT besedilo FROM safeer_chat s2 WHERE s2.pogovor_id=s.pogovor_id ORDER BY cas DESC LIMIT 1) zadnje,
            MAX(oseba_id) oseba FROM safeer_chat s GROUP BY pogovor_id ORDER BY cas DESC""")
        return [Pogovor(r[0], self.kanal_id, r[3] or r[0], "", r[2], 0, r[1]) for r in vrstice if not od or r[1] >= od]

    def sporocila(self, pogovor_id: str, pred: Optional[str] = None, najvec: int = 50):
        sql = "SELECT id,pogovor_id,smer,besedilo,cas FROM safeer_chat WHERE pogovor_id=?"
        args = [pogovor_id]
        if pred: sql += " AND cas<?"; args.append(pred)
        sql += " ORDER BY cas DESC LIMIT ?"; args.append(max(1, min(int(najvec), NAJVEC_SEZNAMA)))
        return [Sporocilo(r[0], r[1], r[2], r[3], r[4], [], "prejeto") for r in self._db.execute(sql, args)][::-1]

    def poslji(self, pogovor_id: str, besedilo: str, priponke: Sequence[dict] = ()) -> Sporocilo:
        if priponke: raise ValueError("Safeer Chat v fazi 1 še ne pošilja priponk")
        telo = preveri_tovor({"conversation": pogovor_id, "text": besedilo})
        sid = str(uuid.uuid4())
        zapis = {"id": sid, "type": "chat.send", "target": pogovor_id, "payload": telo}
        self.povezi()
        if not self.povezava.poslji(zapis): raise RuntimeError("Sporočila ni bilo mogoče poslati")
        s = Sporocilo(sid, pogovor_id, "ven", besedilo, telo["created_at"], [], "poslano")
        self._zapisi(s)
        return s

    def oznaci_prebrano(self, pogovor_id: str) -> None: return None

    def zahteva_seznam(self, cilj: str, najvec: int = 50) -> bool:
        self.povezi()
        return bool(self.povezava.poslji({"id": str(uuid.uuid4()), "type": "chat.list", "target": cilj,
            "payload": {"limit": max(1, min(int(najvec), NAJVEC_SEZNAMA))}}))
