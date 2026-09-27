"""Zapiski v Safeer OS (po zgledu Deta Surf, Apache 2.0): zapiski z @-omembami datotek, strani,
programov in drugih zapiskov ter izrezki s spleta z virom.

Vse ostane na tem racunalniku (en JSON v mapi nastavitev Safeer OS), brez oblaka in brez racuna.
Omemba je v besedilu navadna povezava Markdown ``[@ime](cilj)``:

* ``https://...`` - spletna stran (odpre se v Spletu),
* ``safeer:datoteka:<pot>`` - datoteka na tem racunalniku,
* ``safeer:zapisek:<id>`` - drug zapisek,
* ``safeer:program:<id>`` - program.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from typing import Optional

NAJVEC_ZAPISKOV = 2000
NAJVEC_BESEDILA = 200_000
NAJVEC_NASLOVA = 160
_OMEMBA = re.compile(r"\[@([^\]]{1,160})\]\(([^)\s]{1,2048})\)")


def _cas() -> int:
    return int(time.time())


def omembe(besedilo: str) -> list[dict]:
    """Vse omembe v zapisku (za prikaz virov in povratne povezave)."""
    izid, videne = [], set()
    for ime, cilj in _OMEMBA.findall(besedilo or ""):
        if cilj in videne:
            continue
        videne.add(cilj)
        vrsta = ("stran" if cilj.startswith(("https://", "http://")) else
                 cilj.split(":")[1] if cilj.startswith("safeer:") and cilj.count(":") >= 2 else "")
        if vrsta:
            izid.append({"ime": ime, "cilj": cilj, "vrsta": vrsta})
    return izid


class Zapiski:
    def __init__(self, pot: str):
        self.pot = pot
        self._kljuc = threading.Lock()

    # ---------------------------------------------------------------- shramba
    def _nalozi(self) -> dict:
        try:
            with open(self.pot, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("zapiski"), list):
                return data
        except (OSError, ValueError):
            pass
        return {"zapiski": [], "zadnji": ""}

    def _shrani(self, data: dict) -> None:
        os.makedirs(os.path.dirname(self.pot) or ".", exist_ok=True)
        zacasna = self.pot + ".tmp"
        with open(zacasna, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(zacasna, self.pot)

    @staticmethod
    def _povzetek(z: dict) -> dict:
        besedilo = _OMEMBA.sub(lambda m: "@" + m.group(1), z.get("besedilo", ""))
        return {"id": z["id"], "naslov": z.get("naslov") or "Brez naslova",
                "odlomek": " ".join(besedilo.split())[:160], "spremenjeno": z.get("spremenjeno", 0),
                "pripet": bool(z.get("pripet"))}

    # ---------------------------------------------------------------- javno
    def seznam(self, iskano: str = "") -> list[dict]:
        with self._kljuc:
            data = self._nalozi()
        zapiski = data["zapiski"]
        if iskano:
            igla = iskano.casefold()
            zapiski = [z for z in zapiski if igla in (z.get("naslov", "") + "\n" + z.get("besedilo", "")).casefold()]
        zapiski = sorted(zapiski, key=lambda z: (not z.get("pripet"), -int(z.get("spremenjeno") or 0)))
        return [self._povzetek(z) for z in zapiski]

    def zadnji(self) -> str:
        with self._kljuc:
            data = self._nalozi()
        ident = str(data.get("zadnji") or "")
        return ident if any(z.get("id") == ident for z in data["zapiski"]) else ""

    def dobi(self, ident: str) -> Optional[dict]:
        with self._kljuc:
            data = self._nalozi()
        z = next((z for z in data["zapiski"] if z.get("id") == ident), None)
        if not z:
            return None
        povratne = [self._povzetek(o) for o in data["zapiski"]
                    if o.get("id") != ident and ("safeer:zapisek:" + ident) in o.get("besedilo", "")]
        return dict(z, omembe=omembe(z.get("besedilo", "")), povratne=povratne)

    def shrani(self, ident: str, naslov: str, besedilo: str, pripet: Optional[bool] = None) -> dict:
        naslov = str(naslov or "").strip()[:NAJVEC_NASLOVA]
        besedilo = str(besedilo or "")[:NAJVEC_BESEDILA]
        with self._kljuc:
            data = self._nalozi()
            z = next((z for z in data["zapiski"] if z.get("id") == ident), None) if ident else None
            if z is None:
                if len(data["zapiski"]) >= NAJVEC_ZAPISKOV:
                    raise ValueError("Doseženo je največje število zapiskov.")
                z = {"id": "z" + secrets.token_hex(6), "ustvarjeno": _cas()}
                data["zapiski"].append(z)
            z.update(naslov=naslov, besedilo=besedilo, spremenjeno=_cas())
            if pripet is not None:
                z["pripet"] = bool(pripet)
            data["zadnji"] = z["id"]
            self._shrani(data)
        return self._povzetek(z)

    def izbrisi(self, ident: str) -> bool:
        with self._kljuc:
            data = self._nalozi()
            pred = len(data["zapiski"])
            data["zapiski"] = [z for z in data["zapiski"] if z.get("id") != ident]
            if data.get("zadnji") == ident:
                data["zadnji"] = ""
            if len(data["zapiski"]) == pred:
                return False
            self._shrani(data)
        return True

    def dodaj_izrezek(self, url: str, naslov_strani: str, izbor: str) -> dict:
        """Izrezek s spleta (izbrano besedilo ali cela stran) v zadnji zapisek, z virom.

        Ce zapiska se ni, ustvarimo zapisek "Iz spleta". Vsak navedek ima povezavo na stran.
        """
        url = str(url or "")
        if not url.startswith(("https://", "http://")):
            raise ValueError("Samo spletne strani lahko dodaš v zapisek.")
        naslov_strani = " ".join(str(naslov_strani or url).split())[:120].replace("[", "(").replace("]", ")")
        izbor = str(izbor or "").strip()[:5000]
        blok = ""
        if izbor:
            blok += "\n".join("> " + vrstica for vrstica in izbor.splitlines()) + "\n"
        blok += "— [@%s](%s)\n" % (naslov_strani, url.replace(" ", "%20").replace(")", "%29"))
        with self._kljuc:
            data = self._nalozi()
            z = next((z for z in data["zapiski"] if z.get("id") == data.get("zadnji")), None)
            if z is None:
                z = {"id": "z" + secrets.token_hex(6), "ustvarjeno": _cas(), "naslov": "Iz spleta", "besedilo": ""}
                data["zapiski"].append(z)
            besedilo = z.get("besedilo", "")
            z["besedilo"] = (besedilo.rstrip("\n") + "\n\n" if besedilo.strip() else "") + blok
            z["spremenjeno"] = _cas()
            data["zadnji"] = z["id"]
            self._shrani(data)
        return self._povzetek(z)
