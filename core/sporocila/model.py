"""Enotni, od ponudnika neodvisni podatkovni model sporocil."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any, Dict, List, Tuple, Type, TypeVar

T = TypeVar("T", bound="JSONModel")


class JSONModel:
    """Majhen JSON vmesnik, uporaben tudi za promet cez JS-most."""

    def slovar(self) -> Dict[str, Any]:
        return asdict(self)  # type: ignore[arg-type]

    def json(self) -> str:
        return json.dumps(self.slovar(), ensure_ascii=False, separators=(",", ":"))

    to_dict = slovar
    to_json = json

    @classmethod
    def iz_slovarja(cls: Type[T], podatki: Dict[str, Any]) -> T:
        return cls(**podatki)  # type: ignore[arg-type]

    @classmethod
    def iz_jsona(cls: Type[T], besedilo: str) -> T:
        podatki = json.loads(besedilo)
        if not isinstance(podatki, dict):
            raise ValueError("JSON modela mora biti predmet")
        return cls.iz_slovarja(podatki)

    from_dict = iz_slovarja
    from_json = iz_jsona


@dataclass
class Kanal(JSONModel):
    id: str
    vrsta: str
    ime: str
    stanje: str = "nepovezan"


@dataclass
class Oseba(JSONModel):
    id: str
    ime: str                      # prikazno ime: uporabnikovo lastno ime, sicer ime iz kanala
    identitete: List[Tuple[str, str]] = field(default_factory=list)
    privzeto_ime: str = ""        # ime, kot ga da kanal (profil, glava From) - ostane vidno tudi po preimenovanju
    lastno_ime: str = ""          # ime, ki ga je dal uporabnik (ima prednost, sinhronizacija ga ne prepise)

    @classmethod
    def iz_slovarja(cls, podatki: Dict[str, Any]) -> "Oseba":
        return cls(id=str(podatki.get("id", "")), ime=str(podatki.get("ime", "")),
                   identitete=[(str(v), str(n)) for v, n in podatki.get("identitete", [])],
                   privzeto_ime=str(podatki.get("privzeto_ime", "")), lastno_ime=str(podatki.get("lastno_ime", "")))


@dataclass
class Pogovor(JSONModel):
    id: str
    kanal_id: str
    oseba_id: str
    zadeva: str = ""
    zadnje_sporocilo: str = ""
    neprebrano: int = 0
    cas: str = ""


@dataclass
class Sporocilo(JSONModel):
    id: str
    pogovor_id: str
    smer: str
    besedilo: str
    cas: str
    priponke: List[Dict[str, Any]] = field(default_factory=list)
    stanje: str = "prejeto"
