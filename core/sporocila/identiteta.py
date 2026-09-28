"""Lokalni identitetni graf za povezovanje naslovov z osebami."""

from __future__ import annotations

import re
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Iterable, Optional, Tuple

from .model import Oseba

PRIVZETA_POT = Path.home() / ".local/share/safeer/sporocila/sporocila.sqlite3"


def normaliziraj(vrsta: str, naslov: str) -> str:
    v, n = vrsta.strip().lower(), naslov.strip()
    if v in ("email", "e-posta", "e-pošta"):
        return n.casefold()
    if v in ("telefon", "phone", "sms", "whatsapp"):
        plus = n.lstrip().startswith("+")
        stevilke = re.sub(r"\D", "", n)
        if n.startswith("00"):
            stevilke, plus = stevilke[2:], True
        return ("+" if plus else "") + stevilke
    return n.casefold()


class IdentitetniGraf:
    def __init__(self, pot: Optional[Path] = None):
        self.pot = Path(pot or PRIVZETA_POT)
        self.pot.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.pot), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._zaklep = threading.RLock()
        with self._db:
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS osebe (
                    id TEXT PRIMARY KEY, ime TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS identitete (
                    vrsta TEXT NOT NULL, naslov TEXT NOT NULL, normaliziran TEXT NOT NULL,
                    oseba_id TEXT NOT NULL REFERENCES osebe(id) ON DELETE CASCADE,
                    PRIMARY KEY(vrsta, normaliziran)
                );
                CREATE TABLE IF NOT EXISTS zdruzitve (
                    iz_id TEXT PRIMARY KEY, v_id TEXT NOT NULL
                );
            """)

    def zapri(self) -> None:
        self._db.close()

    def dodaj(self, ime: str, identitete: Iterable[Tuple[str, str]] = (),
              oseba_id: str = "") -> Oseba:
        pari = [(str(v).lower(), str(n)) for v, n in identitete if str(n).strip()]
        obstojeci = []
        for vrsta, naslov in pari:
            oseba = self.najdi(vrsta, naslov)
            if oseba and oseba.id not in obstojeci:
                obstojeci.append(oseba.id)
        cilj = obstojeci[0] if obstojeci else (oseba_id or str(uuid.uuid4()))
        with self._zaklep, self._db:
            self._db.execute("INSERT OR IGNORE INTO osebe(id,ime) VALUES(?,?)", (cilj, ime or naslov_iz(pari)))
            if ime:
                self._db.execute("UPDATE osebe SET ime=? WHERE id=?", (ime, cilj))
            for drugi in obstojeci[1:]:
                self._zdruzi(drugi, cilj)
            for vrsta, naslov in pari:
                self._db.execute("""INSERT INTO identitete(vrsta,naslov,normaliziran,oseba_id)
                    VALUES(?,?,?,?) ON CONFLICT(vrsta,normaliziran) DO UPDATE SET oseba_id=excluded.oseba_id""",
                    (vrsta, naslov, normaliziraj(vrsta, naslov), cilj))
        return self.oseba(cilj)  # type: ignore[return-value]

    dodaj_osebo = dodaj

    def oseba(self, oseba_id: str) -> Optional[Oseba]:
        with self._zaklep:
            vrstica = self._db.execute("SELECT id,ime FROM osebe WHERE id=?", (oseba_id,)).fetchone()
            if not vrstica:
                return None
            identitete = [(r["vrsta"], r["naslov"]) for r in self._db.execute(
                "SELECT vrsta,naslov FROM identitete WHERE oseba_id=? ORDER BY vrsta,naslov", (oseba_id,))]
            return Oseba(vrstica["id"], vrstica["ime"], identitete)

    def najdi(self, vrsta: str, naslov: str) -> Optional[Oseba]:
        with self._zaklep:
            vrstica = self._db.execute("SELECT oseba_id FROM identitete WHERE vrsta=? AND normaliziran=?",
                                      (vrsta.lower(), normaliziraj(vrsta, naslov))).fetchone()
        return self.oseba(vrstica[0]) if vrstica else None

    def vse(self):
        with self._zaklep:
            ids = [r[0] for r in self._db.execute("SELECT id FROM osebe ORDER BY ime COLLATE NOCASE")]
        return [o for o in (self.oseba(i) for i in ids) if o]

    def _zdruzi(self, iz_id: str, v_id: str) -> None:
        if iz_id == v_id:
            return
        self._db.execute("UPDATE identitete SET oseba_id=? WHERE oseba_id=?", (v_id, iz_id))
        self._db.execute("INSERT OR REPLACE INTO zdruzitve(iz_id,v_id) VALUES(?,?)", (iz_id, v_id))
        self._db.execute("DELETE FROM osebe WHERE id=?", (iz_id,))

    def zdruzi(self, prvi_id: str, drugi_id: str) -> Oseba:
        """Drugo osebo zdruzi v prvo; operacija je rocno razdruzljiva."""
        with self._zaklep, self._db:
            if not self.oseba(prvi_id) or not self.oseba(drugi_id):
                raise KeyError("Oseba ne obstaja")
            self._zdruzi(drugi_id, prvi_id)
        return self.oseba(prvi_id)  # type: ignore[return-value]

    def razdruzi(self, oseba_id: str, identitete: Optional[Iterable[Tuple[str, str]]] = None,
                 novo_ime: str = "") -> Oseba:
        """Iz izbrane osebe izlocI navedene identitete (privzeto zadnjo)."""
        oseba = self.oseba(oseba_id)
        if not oseba:
            raise KeyError("Oseba ne obstaja")
        izbrane = list(identitete or oseba.identitete[-1:])
        if not izbrane:
            raise ValueError("Ni identitete za razdružitev")
        novi_id = str(uuid.uuid4())
        with self._zaklep, self._db:
            self._db.execute("INSERT INTO osebe(id,ime) VALUES(?,?)", (novi_id, novo_ime or naslov_iz(izbrane)))
            for vrsta, naslov in izbrane:
                self._db.execute("UPDATE identitete SET oseba_id=? WHERE vrsta=? AND normaliziran=? AND oseba_id=?",
                                 (novi_id, vrsta.lower(), normaliziraj(vrsta, naslov), oseba_id))
        return self.oseba(novi_id)  # type: ignore[return-value]


def naslov_iz(identitete: Iterable[Tuple[str, str]]) -> str:
    return next((n for _v, n in identitete), "Neznana oseba")
