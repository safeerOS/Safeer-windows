"""Kljuc za primerjavo pri iskanju: male crke brez sumnikov in naglasov.

Brez odvisnosti. Isti kljuc uporabljajo iskanje datotek (os_datoteke, os_iskalnik), zapiski (os_zapiski) in medijska
knjiznica (os_knjiznica); v vmesniku mu ustrezata kljucIskanja (assets/os/delovna.js) in brezNaglasa
(assets/os/iskanje.js) z isto tabelo posebnih crk - enakost varuje tests/test_iskalni_kljuc.py.
"""

from __future__ import annotations

import unicodedata

#: Crke, ki jih razstavitev Unicode ne loci na osnovo in naglas.
POSEBNE_CRKE = {"đ": "d", "ł": "l", "ø": "o", "ß": "ss", "æ": "ae", "œ": "oe", "ı": "i"}
_PREVOD = str.maketrans(POSEBNE_CRKE)


def kljuc(besedilo: str) -> str:
    """Male crke brez sumnikov in naglasov (č -> c, é -> e, đ -> d)."""
    s = str(besedilo).lower()
    if s.isascii():
        return s
    s = unicodedata.normalize("NFKD", s.translate(_PREVOD))
    return "".join(z for z in s if not unicodedata.combining(z))
