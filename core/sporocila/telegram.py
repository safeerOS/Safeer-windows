"""Telegram adapter (faza 2).

Uradni uporabniski odjemalec zahteva TDLib, zato v lahki prvi fazi ni povezave.
"""

from .adapter import Adapter


class TelegramAdapter(Adapter):
    vrsta = "telegram"
    zmore = set()

    def povezi(self): raise NotImplementedError("Telegram pride v fazi 2 (TDLib).")
    def pogovori(self, od=None): return []
    def sporocila(self, pogovor_id, pred=None, najvec=50): return []
    def poslji(self, pogovor_id, besedilo, priponke=()): raise NotImplementedError
    def oznaci_prebrano(self, pogovor_id): raise NotImplementedError
