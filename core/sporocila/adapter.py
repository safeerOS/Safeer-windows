"""Pogodba, ki jo izpolni vsak komunikacijski kanal."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Optional, Sequence, Set

from .model import Pogovor, Sporocilo


class Adapter(ABC):
    vrsta: str = ""
    zmore: Set[str] = set()

    @abstractmethod
    def povezi(self) -> None:
        """Vzpostavi povezavo oziroma preveri nastavitve."""

    @abstractmethod
    def pogovori(self, od: Optional[str] = None) -> Iterable[Pogovor]:
        pass

    @abstractmethod
    def sporocila(self, pogovor_id: str, pred: Optional[str] = None,
                  najvec: int = 50) -> Iterable[Sporocilo]:
        pass

    @abstractmethod
    def poslji(self, pogovor_id: str, besedilo: str,
               priponke: Sequence[dict] = ()) -> Sporocilo:
        pass

    @abstractmethod
    def oznaci_prebrano(self, pogovor_id: str) -> None:
        pass
