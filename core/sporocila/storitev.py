"""Orkestracija adapterjev, lokalni predpomnilnik in lahka sinhronizacija."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, Optional

from .adapter import Adapter
from .identiteta import IdentitetniGraf, PRIVZETA_POT
from .model import Kanal, Pogovor, Sporocilo


class StoritevSporocil:
    def __init__(self, pot: Optional[Path] = None, interval: float = 60):
        self.pot = Path(pot or PRIVZETA_POT)
        self.pot.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.pot), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.graf = IdentitetniGraf(self.pot)
        self.adapterji: Dict[str, Adapter] = {}
        self.interval = max(1, float(interval))
        self._ustavi = threading.Event()
        self._nit = None
        self._zaklep = threading.RLock()
        with self.db:
            self.db.executescript("""
              CREATE TABLE IF NOT EXISTS kanali(id TEXT PRIMARY KEY,vrsta TEXT,ime TEXT,stanje TEXT,nastavitve TEXT);
              CREATE TABLE IF NOT EXISTS pogovori(id TEXT,kanal_id TEXT,oseba_id TEXT,zadeva TEXT,
                zadnje_sporocilo TEXT,neprebrano INTEGER,cas TEXT,PRIMARY KEY(id,kanal_id));
              CREATE TABLE IF NOT EXISTS sporocila(id TEXT,pogovor_id TEXT,kanal_id TEXT,smer TEXT,
                besedilo TEXT,cas TEXT,priponke TEXT,stanje TEXT,PRIMARY KEY(id,kanal_id));
              CREATE TABLE IF NOT EXISTS kanal_stanje(id TEXT PRIMARY KEY, podatki TEXT);
            """)
        self._sinhronizacija = threading.Lock()
        self._obnovljeni = set()

    def registriraj(self, kanal: Kanal, adapter: Adapter, nastavitve: Optional[dict] = None) -> None:
        nastavitve = dict(nastavitve or {})
        prepovedano = {"geslo", "password", "zeton", "token", "api_access_token", "secret"}
        if any(str(k).lower() in prepovedano for k in nastavitve):
            raise ValueError("Skrivnosti ne sodijo v nastavitveno datoteko")
        self.adapterji[kanal.id] = adapter
        with self._zaklep, self.db:
            self.db.execute("INSERT OR REPLACE INTO kanali VALUES(?,?,?,?,?)",
                            (kanal.id, kanal.vrsta, kanal.ime, kanal.stanje,
                             json.dumps(nastavitve, ensure_ascii=False)))

    dodaj_adapter = registriraj

    def kanali(self):
        with self._zaklep:
            return [Kanal(r["id"], r["vrsta"], r["ime"], r["stanje"])
                    for r in self.db.execute("SELECT * FROM kanali ORDER BY ime COLLATE NOCASE")]

    def sinhroniziraj(self, kanal_id: Optional[str] = None) -> int:
        """Prenese novo. Hkrati tece najvec ena sinhronizacija (zanka v ozadju in gumb v vmesniku)."""
        with self._sinhronizacija:
            return self._sinhroniziraj(kanal_id)

    @staticmethod
    def _razlog(napaka: Exception) -> str:
        ime = type(napaka).__name__
        if ime == "ManjkaSkrivnost":
            return "napaka:geslo"
        if ime in ("NapakaPrijave", "SMTPAuthenticationError") or "AUTH" in str(napaka).upper():
            return "napaka:prijava"
        if isinstance(napaka, (OSError, TimeoutError)):
            return "napaka:omrezje"
        return "napaka"

    def _sinhroniziraj(self, kanal_id: Optional[str] = None) -> int:
        skupaj = 0
        ids = [kanal_id] if kanal_id else list(self.adapterji)
        for kid in ids:
            adapter = self.adapterji.get(kid)
            if not adapter:
                continue
            try:
                if kid not in self._obnovljeni and hasattr(adapter, "obnovi"):
                    vrstica = self.db.execute("SELECT podatki FROM kanal_stanje WHERE id=?", (kid,)).fetchone()
                    if vrstica:
                        adapter.obnovi(json.loads(vrstica["podatki"] or "{}"))
                    self._obnovljeni.add(kid)
                adapter.povezi()
                pogovori = list(adapter.pogovori())
                pripravljeni = []
                for p in pogovori:
                    ime = adapter.ime_osebe(p.oseba_id) if hasattr(adapter, "ime_osebe") else ""
                    oseba_id = self._oseba(adapter.vrsta, p.oseba_id, ime)
                    pripravljeni.append((p, oseba_id, list(adapter.sporocila(p.id, najvec=50))))
                with self._zaklep, self.db:
                    self.db.execute("UPDATE kanali SET stanje='povezan' WHERE id=?", (kid,))
                    for p, oseba_id, sporocila in pripravljeni:
                        prej = self.db.execute("SELECT neprebrano FROM pogovori WHERE id=? AND kanal_id=?",
                                               (p.id, kid)).fetchone()
                        # Inkrementalno: nova neprebrana se pristejejo k ze znanim.
                        neprebrano = p.neprebrano + (int(prej["neprebrano"] or 0) if prej and hasattr(adapter, "obnovi") else 0)
                        self.db.execute("INSERT OR REPLACE INTO pogovori VALUES(?,?,?,?,?,?,?)",
                            (p.id, kid, oseba_id, p.zadeva, p.zadnje_sporocilo, neprebrano, p.cas))
                        for s in sporocila:
                            self._shrani_sporocilo(kid, s)
                        skupaj += 1
                    if hasattr(adapter, "stanje"):
                        self.db.execute("INSERT OR REPLACE INTO kanal_stanje VALUES(?,?)",
                                        (kid, json.dumps(adapter.stanje(), ensure_ascii=False)))
            except Exception as napaka:
                # Brez skrivnosti/omrezja kanal ostane uporaben po predpomnilniku. Izjeme namenoma
                # ne zapisujemo: lahko bi vsebovala uporabnisko ime ali odgovor streznika.
                with self._zaklep, self.db:
                    self.db.execute("UPDATE kanali SET stanje=? WHERE id=?", (self._razlog(napaka), kid))
        return skupaj

    def oznaci_prebrano(self, kanal_id: str, pogovor_id: str) -> None:
        with self._zaklep, self.db:
            self.db.execute("UPDATE pogovori SET neprebrano=0 WHERE id=? AND kanal_id=?", (pogovor_id, kanal_id))
        adapter = self.adapterji.get(kanal_id)
        if adapter:
            try:
                adapter.oznaci_prebrano(pogovor_id)
            except Exception:
                pass

    def odstrani_kanal(self, kanal_id: str) -> None:
        adapter = self.adapterji.pop(kanal_id, None)
        for metoda in ("pozabi_geslo", "pozabi_zeton", "zapri"):
            if adapter is not None and hasattr(adapter, metoda):
                try:
                    getattr(adapter, metoda)()
                except Exception:
                    pass
        with self._zaklep, self.db:
            for tabela in ("kanali", "kanal_stanje"):
                self.db.execute("DELETE FROM %s WHERE id=?" % tabela, (kanal_id,))
            self.db.execute("DELETE FROM pogovori WHERE kanal_id=?", (kanal_id,))
            self.db.execute("DELETE FROM sporocila WHERE kanal_id=?", (kanal_id,))
        # Osebe, ki so ostale brez vsakega pogovora, izginejo skupaj s kanalom.
        with self.graf._zaklep, self.graf._db:
            self.graf._db.execute("DELETE FROM identitete WHERE oseba_id NOT IN (SELECT DISTINCT oseba_id FROM pogovori)")
            self.graf._db.execute("DELETE FROM osebe WHERE id NOT IN (SELECT DISTINCT oseba_id FROM pogovori)")

    def _oseba(self, vrsta: str, vrednost: str, ime: str = "") -> str:
        tip = "email" if vrsta == "email" and "@" in vrednost else ("telefon" if vrednost.startswith("+") else vrsta)
        return self.graf.dodaj(ime.strip(), [(tip, vrednost)]).id

    def _shrani_sporocilo(self, kanal_id: str, s: Sporocilo):
        self.db.execute("INSERT OR REPLACE INTO sporocila VALUES(?,?,?,?,?,?,?,?)",
            (s.id, s.pogovor_id, kanal_id, s.smer, s.besedilo, s.cas,
             json.dumps(s.priponke, ensure_ascii=False), s.stanje))

    def pogovori(self, kanal: str = ""):
        sql = "SELECT * FROM pogovori"
        args = ()
        if kanal: sql += " WHERE kanal_id=?"; args = (kanal,)
        sql += " ORDER BY CASE WHEN cas='' THEN 1 ELSE 0 END,cas DESC"
        with self._zaklep:
            return [Pogovor(r["id"], r["kanal_id"], r["oseba_id"], r["zadeva"],
                             r["zadnje_sporocilo"], r["neprebrano"], r["cas"])
                    for r in self.db.execute(sql, args)]

    def zdruzeni_pogovori(self, kanal: str = ""):
        skupine = []
        po_osebi = {}
        for p in self.pogovori(kanal):
            if p.oseba_id not in po_osebi:
                oseba = self.graf.oseba(p.oseba_id)
                vnos = {"oseba": oseba.slovar() if oseba else {"id": p.oseba_id, "ime": p.oseba_id, "identitete": []},
                        "pogovori": [], "cas": p.cas, "neprebrano": 0}
                po_osebi[p.oseba_id] = vnos; skupine.append(vnos)
            po_osebi[p.oseba_id]["pogovori"].append(p.slovar())
            po_osebi[p.oseba_id]["neprebrano"] += p.neprebrano
        return skupine

    def sporocila(self, kanal_id: str, pogovor_id: str, najvec: int = 50):
        with self._zaklep:
            # Enak cas (e-posta ima natancnost sekunde): vrstni red prihoda (rowid) odloci.
            vrstice = self.db.execute("""SELECT * FROM sporocila WHERE kanal_id=? AND pogovor_id=?
                ORDER BY cas DESC, rowid DESC LIMIT ?""", (kanal_id, pogovor_id, max(1, min(int(najvec), 200)))).fetchall()
        return [Sporocilo(r["id"], r["pogovor_id"], r["smer"], r["besedilo"], r["cas"],
                          json.loads(r["priponke"] or "[]"), r["stanje"]) for r in reversed(vrstice)]

    def poslji(self, kanal_id: str, pogovor_id: str, besedilo: str, priponke=()):
        adapter = self.adapterji[kanal_id]
        s = adapter.poslji(pogovor_id, besedilo, priponke)
        with self._zaklep, self.db:
            self._shrani_sporocilo(kanal_id, s)
            self.db.execute("UPDATE pogovori SET zadnje_sporocilo=?,cas=? WHERE id=? AND kanal_id=?",
                            (besedilo[:240], s.cas, pogovor_id, kanal_id))
        return s

    def zazeni(self):
        if self._nit and self._nit.is_alive(): return
        self._ustavi.clear()
        def zanka():
            while not self._ustavi.is_set():
                self.sinhroniziraj()
                self._ustavi.wait(self.interval)
        self._nit = threading.Thread(target=zanka, name="safeer-sporocila", daemon=True)
        self._nit.start()

    def ustavi(self):
        self._ustavi.set()
        if self._nit and self._nit is not threading.current_thread(): self._nit.join(timeout=2)

    def zapri(self):
        self.ustavi(); self.graf.zapri(); self.db.close()


Storitev = StoritevSporocil
