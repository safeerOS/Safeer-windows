"""Deljenje prek Huba na racunalniku: besedilo in datoteka med napravami.

Isti protokol kot Hub na Androidu (HubHttp.kt, HubTokovi.kt), da odjemalcev ni treba spreminjati:

  * ``POST /cast/share/text`` {target, text}, zeton v glavi  -> cilju ``share.text {text}``;
  * ``PUT  /cast/file?name=&target=&from=``, telo = datoteka, zeton v glavi, neobvezno ``x-safeer-sha256``
    -> datoteka pocaka na Hubu, cilju ``share.file {id, name, size, path, sha256}``;
  * ``GET  /cast/file/<id>?k=<kljuc>`` -> cilj datoteko prevzame (kljuc je iz ``share.file``).

Do te razlicice je racunalnik kot sredisce znal samo posredovati sporocila; teh treh poti ni imel, zato »Poslji
besedilo« in »Poslji datoteko« med napravami nista delala, kadar je bilo sredisce racunalnik (PUT -> 501, POST -> 404).

Pravila (kot HubTokovi): datoteka se pise na disk v koscih in nikoli ne sestavlja v pomnilniku; hkrati tece omejeno
stevilo prenosov; prostor na disku se preveri pred sprejemom; neprevzeta datoteka se po eni uri izbrise. Posiljatelj
je lastnik zetona - ``from`` iz poizvedbe ne velja nic. Deljenja zaslona tu (se) ni.

Modul ne pozna omrezja: dobi bralni tok in vrne kodo HTTP z odgovorom, zato je preizkusljiv brez vticnikov.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import threading
import time
from typing import Callable, Dict, Optional, Tuple

NAJVEC_PRENOSOV = 3
NAJVECJA_DATOTEKA = 4 * 1024 * 1024 * 1024
REZERVA_PROSTORA = 200 * 1024 * 1024
DATOTEKA_VELJA_S = 3600.0
NAJVEC_CAKAJOCIH = 64
NAJVEC_BESEDILA = 20_000
NAJVEC_IMENA_DATOTEKE = 180
KOS = 64 * 1024


def privzeta_mapa(windows: Optional[bool] = None) -> str:
    """Zacasna mapa za datoteke, ki cakajo na prevzem: predpomnilnik uporabnika, ne /tmp (tam bi jih videli drugi).
    Na Windows mapa programa v profilu uporabnika (kot predpomnilnik pretoka, link_sprotno.mapa_predpomnilnika)."""
    if (os.name == "nt") if windows is None else windows:
        return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "SafeerOS", "deljenje")
    osnova = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(osnova, "safeer-link", "deljenje")


def varno_ime(ime: str) -> str:
    """Samo ime datoteke: brez poti, nadzornih znakov in pik na zacetku (kot varnoIme na Androidu)."""
    ime = str(ime or "").replace("\\", "/").split("/")[-1]
    ime = "".join(z for z in ime if z >= " " and z not in '<>:"|?*\x7f').strip().lstrip(".")
    return ime[:NAJVEC_IMENA_DATOTEKE]


def napaka(sporocilo: str, koda: str = "") -> dict:
    """Odgovor z napako v obeh oblikah, ki ju odjemalci berejo (napaka/koda in error/error_code)."""
    return {"napaka": sporocilo, "koda": koda, "error": sporocilo, "error_code": koda}


class Datoteka:
    def __init__(self, ime: str, velikost: int, pot: str, cilj: str, posiljatelj: str, sha256: str, nastala: float) -> None:
        self.id = secrets.token_hex(8)
        self.kljuc = secrets.token_hex(16)
        self.ime = ime
        self.velikost = velikost
        self.pot = pot
        self.cilj = cilj
        self.posiljatelj = posiljatelj
        self.sha256 = sha256
        self.nastala = nastala

    def pot_prevzema(self) -> str:
        return "/cast/file/%s?k=%s" % (self.id, self.kljuc)

    def tovor(self) -> dict:
        """Tovor sporocila share.file, kot ga poslje Hub na Androidu."""
        return {"id": self.id, "name": self.ime, "size": self.velikost, "path": self.pot_prevzema(),
                "sha256": self.sha256, "for_host": False}


class Deljenje:
    """Datoteke na poti od posiljatelja do cilja."""

    def __init__(self, mapa: Callable[[], str] = privzeta_mapa, ura: Callable[[], float] = time.time,
                 prosto: Optional[Callable[[str], int]] = None) -> None:
        self._mapa = mapa
        self.ura = ura
        self._prosto = prosto or (lambda m: shutil.disk_usage(m).free)
        self._zaklep = threading.Lock()
        self._datoteke: Dict[str, Datoteka] = {}
        self._prenosov = 0
        self._pospravljeno = False

    # ------------------------------------------------------------------ pomozno
    def _pripravi_mapo(self) -> str:
        mapa = self._mapa()
        os.makedirs(mapa, mode=0o700, exist_ok=True)
        if not self._pospravljeno:
            # Ostanki prejsnjega zagona: kljuci zanje so sli s procesom, prevzeti jih ne more nihce vec.
            self._pospravljeno = True
            for ime in os.listdir(mapa):
                try:
                    os.remove(os.path.join(mapa, ime))
                except OSError:
                    pass
        return mapa

    def _zasedi(self) -> bool:
        with self._zaklep:
            if self._prenosov >= NAJVEC_PRENOSOV:
                return False
            self._prenosov += 1
            return True

    def _sprosti(self) -> None:
        with self._zaklep:
            self._prenosov = max(0, self._prenosov - 1)

    def stevilo(self) -> int:
        with self._zaklep:
            return len(self._datoteke)

    # ------------------------------------------------------------------ sprejem (PUT /cast/file)
    def preveri(self, ime: str, cilj: str, dolzina: int) -> Optional[Tuple[int, dict]]:
        """Napaka, ki jo lahko povemo, se preden beremo telo; None = sprejem se lahko zacne."""
        if not ime or not cilj or dolzina < 0:
            return 400, napaka("Manjka ime, cilj ali dolžina.", "manjka_podatek")
        if dolzina > NAJVECJA_DATOTEKA:
            return 413, napaka("Datoteka je prevelika.", "prevelika")
        self.pocisti()
        if self.stevilo() >= NAJVEC_CAKAJOCIH:
            return 503, napaka("Preveč datotek čaka na prevzem.", "prevec_cakajocih")
        try:
            mapa = self._pripravi_mapo()
            prosto = int(self._prosto(mapa))
        except OSError:
            return 507, napaka("Datoteke ni mogoče shraniti.", "ni_prostora")
        if prosto < dolzina + REZERVA_PROSTORA:
            return 507, napaka("Ni dovolj prostora.", "ni_prostora")
        return None

    def sprejmi(self, vhod, dolzina: int, ime: str, cilj: str, posiljatelj: str,
                napovedan_sha: str = "") -> Tuple[int, dict, Optional[Datoteka]]:
        """Prebere natanko `dolzina` bajtov iz `vhod` v zacasno datoteko. Vrne (koda HTTP, odgovor, datoteka ali None)."""
        ime = varno_ime(ime)
        zavrnjeno = self.preveri(ime, cilj, dolzina)
        if zavrnjeno is not None:
            return zavrnjeno[0], zavrnjeno[1], None
        if not self._zasedi():
            return 503, napaka("Preveč hkratnih prenosov.", "prevec_prenosov"), None
        pot = os.path.join(self._pripravi_mapo(), secrets.token_hex(6) + "-" + ime)
        prejeto, odtis = 0, hashlib.sha256()
        try:
            with open(os.open(pot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as izhod:
                while prejeto < dolzina:
                    kos = vhod.read(min(KOS, dolzina - prejeto))
                    if not kos:
                        break
                    izhod.write(kos)
                    odtis.update(kos)
                    prejeto += len(kos)
        except Exception:  # noqa: BLE001 - prekinjena povezava ali poln disk: datoteke ne obdrzimo
            self._odstrani_pot(pot)
            self._sprosti()
            return 500, napaka("Prenos je bil prekinjen.", "prenos_prekinjen"), None
        self._sprosti()
        if prejeto != dolzina:
            self._odstrani_pot(pot)
            return 400, napaka("Datoteka ni prišla cela.", "ni_cela"), None
        sha256 = odtis.hexdigest()
        napovedan = (napovedan_sha or "").strip().lower()
        if napovedan and napovedan != sha256:
            self._odstrani_pot(pot)
            return 400, napaka("Prstni odtis se ne ujema.", "napacen_odtis"), None
        d = Datoteka(ime, prejeto, pot, cilj, posiljatelj, sha256, self.ura())
        with self._zaklep:
            self._datoteke[d.id] = d
        return 200, {"id": d.id, "name": d.ime, "size": prejeto, "key": d.kljuc, "for_host": False, "sha256": sha256}, d

    # ------------------------------------------------------------------ prevzem (GET /cast/file/<id>?k=)
    def najdi(self, id_: str, kljuc: str) -> Optional[Datoteka]:
        with self._zaklep:
            d = self._datoteke.get(str(id_ or ""))
        if d is None or not kljuc or not secrets.compare_digest(d.kljuc, str(kljuc)) or not os.path.isfile(d.pot):
            return None
        return d

    def zacni_prevzem(self) -> bool:
        return self._zasedi()

    def koncaj_prevzem(self, d: Datoteka, cela: bool) -> None:
        """Po prevzemu je zacasna datoteka opravila svoje; prekinjen prevzem jo pusti (cilj poskusi znova)."""
        self._sprosti()
        if cela:
            self.odstrani(d.id)

    def odstrani(self, id_: str) -> None:
        with self._zaklep:
            d = self._datoteke.pop(id_, None)
        if d is not None:
            self._odstrani_pot(d.pot)

    @staticmethod
    def _odstrani_pot(pot: str) -> None:
        try:
            os.remove(pot)
        except OSError:
            pass

    def pocisti(self) -> None:
        """Datoteke, ki jih v eni uri ni nihce prevzel, izbrisemo."""
        meja = self.ura() - DATOTEKA_VELJA_S
        with self._zaklep:
            stare = [i for i, d in self._datoteke.items() if d.nastala < meja]
        for i in stare:
            self.odstrani(i)

    def izprazni(self) -> None:
        """Ob ustavitvi Huba: nic ne ostane na disku."""
        with self._zaklep:
            vse = list(self._datoteke)
        for i in vse:
            self.odstrani(i)
