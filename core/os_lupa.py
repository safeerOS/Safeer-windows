"""Iskalna lupa namizja se uci iz uporabnikovih izbir (samo na tem racunalniku, nic ne gre po omrezju).

Vsaka izbira je zapis [niz, kljuc zadetka, cas, prvi]: niz je normaliziran iskalni niz (male crke, brez sumnikov -
to naredi stran), kljuc pove, kaj je uporabnik odprl (npr. »program:firefox.desktop«), »prvi« pa, ali je bil to
zadetek, ki ga je lupa ponudila kot prvega (Enter brez izbire). Iz tega:
- lupa naslednjic isto stvar za isti ali podoben niz ponudi prvo (racun je v delovna.js, naucenaOcena);
- statistika pove, kako pogosto je bila lupa takoj prava (merilo, ali ucenje pomaga).
Hranimo najvec NAJVEC zapisov; »pozabi« izbrise vse."""
import json
import os
import threading
import time
from typing import List, Optional

MAPA = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "safeer-os")
NAJVEC = 500
NAJDALJSI_NIZ = 80
NAJDALJSI_KLJUC = 400
ZADNJIH = 100


class Ucenje:
    def __init__(self, pot: Optional[str] = None) -> None:
        self.pot = pot or os.path.join(MAPA, "lupa.json")
        self._zaklep = threading.Lock()
        self.izbire: List[list] = self._preberi()

    def _preberi(self) -> List[list]:
        try:
            with open(self.pot, encoding="utf-8") as f:
                podatki = json.load(f) or {}
        except Exception:
            podatki = {}
        izbire = podatki.get("izbire") if isinstance(podatki, dict) else None
        return [z for z in (izbire or []) if self._veljaven(z)][-NAJVEC:]

    @staticmethod
    def _veljaven(z) -> bool:
        return (isinstance(z, list) and len(z) == 4 and isinstance(z[0], str) and isinstance(z[1], str)
                and isinstance(z[2], (int, float)) and isinstance(z[3], bool))

    def _shrani(self) -> None:
        os.makedirs(os.path.dirname(self.pot), exist_ok=True)
        zacasna = self.pot + ".tmp"
        with open(zacasna, "w", encoding="utf-8") as f:
            json.dump({"izbire": self.izbire}, f, ensure_ascii=False)
        os.replace(zacasna, self.pot)

    def zapomni(self, niz, kljuc, prvi=False) -> bool:
        niz = " ".join(str(niz or "").split())[:NAJDALJSI_NIZ]
        kljuc = str(kljuc or "")[:NAJDALJSI_KLJUC]
        if not niz or not kljuc:
            return False
        with self._zaklep:
            # Datoteko lahko pise tudi drug proces Safeer OS: najprej preberemo, kar je ze tam.
            self.izbire = self._preberi()
            self.izbire.append([niz, kljuc, round(time.time()), bool(prvi)])
            self.izbire = self.izbire[-NAJVEC:]
            try:
                self._shrani()
            except OSError as e:
                print("[SafeerOS] lupa:", e)
                return False
        return True

    def podatki(self) -> dict:
        with self._zaklep:
            return {"izbire": [list(z) for z in self.izbire], "statistika": self.statistika()}

    def statistika(self) -> dict:
        """Delez izbir, pri katerih je bil odprti zadetek tisti, ki ga je lupa ponudila prvega (vse in zadnjih 100)."""
        vse = self.izbire
        zadnje = vse[-ZADNJIH:]
        def delez(s):
            return round(100.0 * sum(1 for z in s if z[3]) / len(s), 1) if s else None
        return {"izbir": len(vse), "prvi_odstotek": delez(vse), "zadnjih": len(zadnje), "prvi_odstotek_zadnjih": delez(zadnje)}

    def pozabi(self) -> bool:
        with self._zaklep:
            self.izbire = []
            try:
                self._shrani()
            except OSError:
                return False
        return True
