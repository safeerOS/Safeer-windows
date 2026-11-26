"""Ukazi, ki tecejo kot root (pkexec): vedno z absolutnimi potmi.

pkexec program poisce po PATH KLICATELJA, se preden okolje pocisti (polkit 124, pkexec.c: g_find_program_in_path pred
clearenv). Ubuntu 24.04 / Mint 22 da ~/.local/bin na zacetek PATH, ce mapa obstaja - program, ki tece kot uporabnik, bi
tja odlozil svoj »install« ali »pkexec« in ob vpisu gesla dobil root (neodvisni pregled, 19. 10. 2026; isti model
napadalca kot pri namestitvi posodobitev iz ~/.cache). Zato: pkexec in program vedno z absolutno potjo.

V Flatpaku pkexec tece na gostitelju prek ovoja /app/host-bin/pkexec (packaging/flatpak_host_wrappers.sh), ki poklice
/usr/bin/pkexec; PATH peskovnika doloca paket, ne uporabnik. Program je pot na gostitelju.
"""
from __future__ import annotations

import os
import shutil
from typing import List, Optional, Sequence

PKEXEC = "/usr/bin/pkexec"

#: Programi, ki jih Safeer zazene kot root (poti na Linux Mint 22 / Ubuntu 24.04, preverjeno na testnem PC 19. 10. 2026).
SH = "/bin/sh"
INSTALL = "/usr/bin/install"
APT_GET = "/usr/bin/apt-get"
ADD_APT_REPOSITORY = "/usr/bin/add-apt-repository"
MINTSOURCES = "/usr/bin/mintsources"
LIGHTDM_SETTINGS = "/usr/bin/lightdm-settings"
#: Synaptic: ovoj synaptic-pkexec bi pkexec poklical po PATH, zato pkexec in ta program neposredno (kot ovoj).
SYNAPTIC = "/usr/sbin/synaptic"

#: Mape, v katere pise samo root. Program, ki ga zazenemo po imenu in lahko sam vprasa za skrbnisko geslo (ovoj s
#: pkexec, upravitelj posodobitev ali programov, Nastavitve, systemctl, safeer-cinnamon --od-vklopa ...), iscemo samo
#: tu: podtaknjen program v ~/.local/bin (pred /usr/bin v PATH) bi pokazal okno za geslo, ki ga uporabnik ob kliku
#: pricakuje, in dobil root (koncni neodvisni pregled, 19. 10. 2026).
SISTEMSKE_MAPE = ("/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin", "/snap/bin")
#: V Flatpaku: ovoji gostitelja (packaging/flatpak_host_wrappers.sh), ki program na gostitelju iscejo samo v
#: SISTEMSKE_MAPE; drugo je slika peskovnika, ki je uporabnik ne more spremeniti.
OVOJI_FLATPAK = "/app/host-bin"


def v_flatpaku() -> bool:
    return bool(os.environ.get("FLATPAK_ID")) or os.path.exists("/.flatpak-info")


def pkexec() -> str:
    """Ovoj gostitelja v Flatpaku, sicer /usr/bin/pkexec - nikoli iskanje po uporabnikovem PATH."""
    if v_flatpaku():
        return "/app/host-bin/pkexec"
    return PKEXEC


def na_voljo() -> bool:
    return os.access(pkexec(), os.X_OK)


def sistemski_program(ime: str, mape: Optional[Sequence[str]] = None) -> Optional[str]:
    """Absolutna pot programa iz SISTEMSKE_MAPE (v Flatpaku najprej ovoj gostitelja) ali None - nikoli po PATH."""
    if not ime or os.sep in ime:
        return None
    if mape is None:
        mape = ((OVOJI_FLATPAK,) + SISTEMSKE_MAPE) if v_flatpaku() else SISTEMSKE_MAPE
    return shutil.which(ime, path=os.pathsep.join(mape))


def sistemski_ukaz(ukaz: Sequence[str]) -> Optional[List[str]]:
    """Ukaz s programom z absolutno potjo (sistemski_program); absolutna pot ostane. None, ce programa ni."""
    if not ukaz:
        return None
    if os.path.isabs(ukaz[0]):
        return list(ukaz) if os.access(ukaz[0], os.X_OK) else None
    program = sistemski_program(ukaz[0])
    return [program, *ukaz[1:]] if program else None


def ukaz(program: str, *argumenti: str) -> List[str]:
    """[pkexec, program, argumenti...]; program mora biti absolutna pot (sicer ValueError)."""
    if not os.path.isabs(program):
        raise ValueError("program za root mora biti absolutna pot: %r" % program)
    return [pkexec(), program, *argumenti]
