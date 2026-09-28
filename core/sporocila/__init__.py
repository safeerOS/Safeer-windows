"""Zdruzeni komunikacijski kanali Safeer OS.

Modul namerno uporablja le Pythonovo standardno knjiznico. Izjemi sta neobvezna
odjemalca Secret Service (``secretstorage`` oziroma ``keyring``), ki se nalozita
sele, ko uporabnik shrani skrivnost.
"""

from .model import Kanal, Oseba, Pogovor, Sporocilo

__all__ = ["Kanal", "Oseba", "Pogovor", "Sporocilo"]
