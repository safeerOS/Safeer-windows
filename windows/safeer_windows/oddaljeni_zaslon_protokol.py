"""Cisti, brezgraficni deli protokola oddaljenega zaslona."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

OKVIR_SLIKA = 1
OKVIR_ZVOK = 2
OKVIR_OBVESTILO = 3
NAJVECJI_OKVIR = 8 * 1024 * 1024


class ZavrnjenaSeja(RuntimeError):
    pass


@dataclass(frozen=True)
class Seja:
    naslov: str
    vrata: int
    odtis: str
    zeton: str
    razlicica: int = 2


def _cisti_odtis(odtis: str) -> str:
    vrednost = str(odtis or "").strip().lower()
    if vrednost.startswith("sha256/") or vrednost.startswith("sha256:"):
        vrednost = vrednost[7:]
    return "".join(z for z in vrednost if z in "0123456789abcdef")


def razcleni_odgovor(odgovor: dict, naprava: Optional[dict] = None) -> Seja:
    if not isinstance(odgovor, dict):
        raise ValueError("Naprava je vrnila neveljaven odgovor.")
    if not odgovor.get("ok"):
        raise ZavrnjenaSeja(str(odgovor.get("message") or odgovor.get("sporocilo") or
                                "Naprava je zavrnila oddaljeni zaslon."))
    podatki = odgovor.get("data")
    if not isinstance(podatki, dict):
        podatki = odgovor
    naprava = naprava or {}
    naslov = str(podatki.get("host") or podatki.get("address") or podatki.get("naslov") or
                  naprava.get("naslov") or naprava.get("address") or naprava.get("host") or "").strip()
    try:
        vrata = int(podatki.get("port") or podatki.get("vrata") or 0)
    except (TypeError, ValueError):
        vrata = 0
    odtis = _cisti_odtis(str(podatki.get("fp") or podatki.get("fingerprint") or podatki.get("odtis") or ""))
    zeton = str(podatki.get("token") or podatki.get("zeton") or "")
    if not naslov:
        raise ValueError("Naprava ni poslala omreznega naslova.")
    if not (1 <= vrata <= 65535):
        raise ValueError("Naprava ni poslala veljavnih vrat zaslona.")
    if len(odtis) != 64:
        raise ValueError("Naprava ni poslala veljavnega odtisa potrdila.")
    if not zeton or "\n" in zeton or "\r" in zeton:
        raise ValueError("Naprava ni poslala veljavnega enkratnega zetona.")
    return Seja(naslov, vrata, odtis, zeton, int(podatki.get("v") or 2))


class RazclenjevalnikOkvirjev:
    def __init__(self) -> None:
        self._podatki = bytearray()

    def dodaj(self, podatki: bytes) -> list[tuple[int, bytes]]:
        self._podatki.extend(podatki)
        rezultat = []
        while len(self._podatki) >= 5:
            vrsta = self._podatki[0]
            dolzina = int.from_bytes(self._podatki[1:5], "big")
            if dolzina <= 0 or dolzina > NAJVECJI_OKVIR:
                raise ValueError("Pokvarjen okvir oddaljenega zaslona.")
            if len(self._podatki) < 5 + dolzina:
                break
            rezultat.append((vrsta, bytes(self._podatki[5:5 + dolzina])))
            del self._podatki[:5 + dolzina]
        return rezultat


POSEBNE_TIPKE = {
    "up": "gor", "down": "dol", "left": "levo", "right": "desno",
    "return": "vnasalka", "enter": "vnasalka", "escape": "ubezna",
    "backspace": "vracalka", "delete": "brisalka", "tab": "tabulator",
    "space": "presledek", "pageup": "stran_gor", "pagedown": "stran_dol",
    "home": "zacetek", "end": "konec",
    **{f"f{i}": f"f{i}" for i in range(1, 13)},
}
MODIFIKATORJI = {"control": "krmilka", "alt": "alt", "shift": "dvigalka", "meta": "sistemska"}


def preslikaj_tipko_ime(ime: str, besedilo: str = "", dol: bool = True,
                        ctrl_alt: bool = False) -> Optional[dict]:
    ime = str(ime or "").lower()
    if ime in MODIFIKATORJI:
        return {"vrsta": "tipka_dol" if dol else "tipka_gor", "tipka": MODIFIKATORJI[ime]}
    if ime in POSEBNE_TIPKE:
        return {"vrsta": "tipka_dol" if dol else "tipka_gor", "tipka": POSEBNE_TIPKE[ime]}
    if ctrl_alt and len(ime) == 1 and ime in "abcdefghijklmnopqrstuvwxyz0123456789":
        return {"vrsta": "tipka_dol" if dol else "tipka_gor", "tipka": ime}
    if dol and besedilo and all(ord(z) >= 32 for z in besedilo):
        return {"vrsta": "besedilo", "besedilo": besedilo[:200]}
    return None


__all__ = ["MODIFIKATORJI", "je_igra", "NAJVECJI_OKVIR", "OKVIR_OBVESTILO", "OKVIR_SLIKA",
           "OKVIR_ZVOK", "POSEBNE_TIPKE", "RazclenjevalnikOkvirjev", "Seja",
           "ZavrnjenaSeja", "preslikaj_tipko_ime", "razcleni_odgovor"]


def je_igra(odgovor) -> bool:
    """Ali gostitelj pravi, da je spredaj igra (screen.start vrne "game": true)."""
    if not isinstance(odgovor, dict):
        return False
    for kljuc in ("game",):
        if odgovor.get(kljuc) is True:
            return True
    for gnezdo in ("result", "data", "odgovor"):
        if isinstance(odgovor.get(gnezdo), dict) and odgovor[gnezdo].get("game") is True:
            return True
    return False
