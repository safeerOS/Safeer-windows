"""Cisti, brezgraficni deli protokola oddaljenega zaslona."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

OKVIR_SLIKA = 1
OKVIR_ZVOK = 2
OKVIR_OBVESTILO = 3
NAJVECJI_OKVIR = 8 * 1024 * 1024
#: Najvec naslovov, ki jih gledalec poskusi za eno sejo, in cas za vsakega, kadar jih je vec. Naprava po
#: `screen.start` caka 30 s; stirje poskusi po 4 s se izidejo z rezervo.
NAJVEC_KANDIDATOV = 4
CAS_KANDIDATA_S = 4.0


class ZavrnjenaSeja(RuntimeError):
    pass


@dataclass(frozen=True)
class Seja:
    naslov: str
    vrata: int
    odtis: str
    zeton: str
    razlicica: int = 2
    #: Vsi naslovi, ki jih gledalec poskusi po vrsti (prvi je `naslov`); prazno = samo `naslov`.
    naslovi: tuple = ()


def _cisti_odtis(odtis: str) -> str:
    vrednost = str(odtis or "").strip().lower()
    if vrednost.startswith("sha256/") or vrednost.startswith("sha256:"):
        vrednost = vrednost[7:]
    return "".join(z for z in vrednost if z in "0123456789abcdef")


def ima_naslov(naprava: Optional[dict]) -> bool:
    """Ali ima naprava v seznamu Safeer Linka omrezni naslov, na katerega se gledalec lahko poveze.
    Naprava, ki je dosegljiva samo prek Global Linka, ga nima - slika zaslona gre samo neposredno."""
    naprava = naprava or {}
    return bool(str(naprava.get("naslov") or naprava.get("address") or naprava.get("host") or "").strip())


def _naslov_naprave(naslov: str) -> bool:
    """Ali je `naslov` iz odgovora naprave naslov IPv4, na katerem jo ima smisel iskati: stiri desetiska stevila
    brez vodilnih nicel; zanka (127.x), 0.x ter skupinski in rezervirani naslovi (224 in vec) odpadejo. Ime
    gostitelja ni naslov - gledalec zaradi odgovora naprave ne sprasuje DNS."""
    deli = naslov.split(".")
    if len(deli) != 4:
        return False
    for d in deli:
        if not (d.isascii() and d.isdigit()) or len(d) > 3 or (len(d) > 1 and d[0] == "0"):
            return False
    stevila = [int(d) for d in deli]
    return max(stevila) <= 255 and stevila[0] not in (0, 127) and stevila[0] < 224


def kandidati_naslovov(naslov: str, hosts=None) -> list:
    """Naslovi, na katerih gledalec isce napravo: najprej naslov iz seznama naprav Safeer Linka, nato tisti, ki
    jih je naprava sama nastela v odgovoru na `screen.start` (`hosts`). Vsak samo enkrat, najvec
    NAJVEC_KANDIDATOV (docs/LINK-MESH.md, pravilo 8)."""
    izid = []
    prvi = str(naslov or "").strip()
    if prvi:
        izid.append(prvi)
    for h in hosts if isinstance(hosts, (list, tuple)) else ():
        if len(izid) >= NAJVEC_KANDIDATOV:
            break
        h = h.strip() if isinstance(h, str) else ""
        if h and h not in izid and _naslov_naprave(h):
            izid.append(h)
    return izid[:NAJVEC_KANDIDATOV]


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
    naslovi = tuple(kandidati_naslovov(naslov, podatki.get("hosts")))
    if not naslovi:
        raise ValueError("Naprava ni poslala omreznega naslova.")
    if not (1 <= vrata <= 65535):
        raise ValueError("Naprava ni poslala veljavnih vrat zaslona.")
    if len(odtis) != 64:
        raise ValueError("Naprava ni poslala veljavnega odtisa potrdila.")
    if not zeton or "\n" in zeton or "\r" in zeton:
        raise ValueError("Naprava ni poslala veljavnega enkratnega zetona.")
    return Seja(naslovi[0], vrata, odtis, zeton, int(podatki.get("v") or 2), naslovi)


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


__all__ = ["CAS_KANDIDATA_S", "MODIFIKATORJI", "NAJVEC_KANDIDATOV", "je_igra", "kandidati_naslovov",
           "NAJVECJI_OKVIR", "OKVIR_OBVESTILO", "OKVIR_SLIKA",
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
