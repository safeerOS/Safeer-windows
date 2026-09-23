"""Zaupanje racunalniku in seja prijave (Safeer Control, Safeer OS za racunalnik).

Racunalnik lahko uporablja vec ljudi. Zato povezava z napravami (telefon, tablica, televizor)
privzeto velja samo do konca te prijave v racunalnik: ob naslednji prijavi (po odjavi ali
ponovnem zagonu) se prijavno okno (QR / koda / brez povezave) pokaze znova.

Ce uporabnik v prijavnem oknu izbere »Zaupaj temu racunalniku«, je povezava potrebna samo
enkrat - kot doslej. Racunalnik, ki mu ne zaupamo, se tudi ne vpise v krog zaupanja: prijava s
podpisom kljuca bi sicer prezivela brisanje zetona.

Seja je identiteta prijave: boot_id (nov ob vsakem zagonu) + stevilka prijave v logind
(prikazovalna seja uporabnika; enaka za vse njegove procese, tudi tiste brez okolja seje).

Kljuci v link.json:
  zaupana         True/False - odlocitev ob prijavi. Manjka pri starih seznanitvah: te ostanejo
                  zaupane (uporabnik jih je naredil, ko je bila povezava vedno trajna).
  seja_prijave    seja, v kateri je bila naprava povezana (za nezaupan racunalnik).
  brez_povezave   seja, v kateri je uporabnik izbral »Nadaljuj brez povezave naprav«.
"""

from __future__ import annotations

import os
from typing import Optional

NEZNANA_REVIZIJSKA = "4294967295"
#: Kar o povezavi racunalnik pozabi, ko se nezaupana seja konca.
KLJUCI_POVEZAVE = ("control_token", "hub_fp", "seznanitve", "seja_prijave")


def _beri(pot: str) -> str:
    try:
        with open(pot, encoding="ascii", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


_prijava_cache: Optional[str] = None


def _prijavna_seja(proc: str = "/proc") -> str:
    """Stevilka prijave v racunalnik (logind). Procesi iste prijave jo vidijo razlicno (program iz
    samozagona ima XDG_SESSION_ID, program, ki ga zazene D-Bus ali systemd --user, ne), zato jo
    vzamemo tam, kjer je za vse enaka: prikazovalna seja uporabnika (loginctl show-user -p Display)."""
    global _prijava_cache
    if _prijava_cache is not None and proc == "/proc":
        return _prijava_cache
    seja = ""
    try:
        import subprocess
        r = subprocess.run(["loginctl", "show-user", str(os.getuid()), "-p", "Display", "--value"],
                           capture_output=True, text=True, timeout=3)
        seja = r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        seja = ""
    if not seja:
        seja = os.environ.get("XDG_SESSION_ID") or ""
    if not seja:
        revizijska = _beri(os.path.join(proc, "self/sessionid"))
        seja = "" if revizijska == NEZNANA_REVIZIJSKA else revizijska
    if proc == "/proc":
        _prijava_cache = seja
    return seja


def trenutna_seja(proc: str = "/proc") -> str:
    """boot_id (nov ob vsakem zagonu) + prijava v racunalnik (nova ob vsaki prijavi)."""
    return _beri(os.path.join(proc, "sys/kernel/random/boot_id")) + ":" + _prijavna_seja(proc)


def zaupana(podatki: dict) -> bool:
    v = podatki.get("zaupana")
    return True if v is None else bool(v)


def seznanjena(podatki: dict) -> bool:
    return bool(podatki.get("control_token")) and bool(podatki.get("hub_fp"))


def povezava_velja(podatki: dict, seja: Optional[str] = None) -> bool:
    """Ali seznanitev v tej seji velja (zaupan racunalnik ali ista prijava)."""
    if not seznanjena(podatki):
        return False
    if zaupana(podatki):
        return True
    return podatki.get("seja_prijave") == (seja or trenutna_seja())


def brez_v_seji(podatki: dict, seja: Optional[str] = None) -> bool:
    """»Nadaljuj brez povezave naprav« velja do konca te prijave."""
    v = podatki.get("brez_povezave")
    return isinstance(v, str) and v == (seja or trenutna_seja())


def pocisti(podatki: dict, seja: Optional[str] = None) -> bool:
    """Ob novi prijavi pozabi, kar je veljalo samo za prejsnjo. Vrne True, ce se je kaj spremenilo."""
    seja = seja or trenutna_seja()
    spremenjeno = False
    if "brez_povezave" in podatki and not brez_v_seji(podatki, seja):
        podatki.pop("brez_povezave", None)
        spremenjeno = True
    if not zaupana(podatki) and podatki.get("seja_prijave") != seja:
        for kljuc in KLJUCI_POVEZAVE:
            if kljuc in podatki:
                podatki.pop(kljuc, None)
                spremenjeno = True
    return spremenjeno


def po_prijavi(podatki: dict, zaupaj: bool, seja: Optional[str] = None) -> None:
    """Uspesna prijava (QR ali koda): zapomni si odlocitev o zaupanju in sejo."""
    podatki["zaupana"] = bool(zaupaj)
    podatki["seja_prijave"] = seja or trenutna_seja()
    podatki.pop("brez_povezave", None)
