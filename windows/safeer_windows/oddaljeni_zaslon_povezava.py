"""Povezava gledalca oddaljenega zaslona z napravo, ki zaslon deli - brez grafike, da jo je mogoce preizkusiti.

Okvirje bere dekodirna nit, vnos (miska, tipke) posilja glavna nit okna. Vticnica TLS s casovno omejitvijo dveh
niti sama ne prenese (core/link_vticnik.py): na Windows pisanje pade z WinError 10035, na Linuxu bralna nit lazno
javi konec povezave - seja se prekine, medtem ko uporabnik premika misko. Zato gre vse skozi VarnaTls.

Pozdrav in okvirji so isti kot v core/link_zaslon.py:
    SAFEER-ZASLON <zeton>\\n        -> naprava
    {"w":1920,"h":1080,...}\\n      <- naprava, nato okvirji: 1 bajt vrste, 4 bajti dolzine, vsebina
    {"vrsta":"tocka",...}\\n        -> naprava (vnos, ena vrstica JSON na dogodek)
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import ssl
import sys
import threading
from typing import Iterator, Optional, Tuple

_KOREN = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if _KOREN not in sys.path:
    sys.path.insert(0, _KOREN)

from core import link_vticnik  # noqa: E402

from .oddaljeni_zaslon_protokol import NAJVECJI_OKVIR, Seja  # noqa: E402

#: Slika tece ves cas (tudi mirno namizje); tisina, daljsa od tega, pomeni, da naprave ni vec.
TISINA_S = 10.0
#: Najdaljsa glava seje (ena vrstica JSON).
NAJVEC_GLAVA = 4096
#: Najdlje sme posiljanje enega dogodka vnosa cakati. Vnos posilja glavna nit okna: ce naprava ne bere vec, okno
#: ne sme obstati do omejitve branja. Dogodek ima nekaj deset bajtov; kdor ga v tem casu ne vzame, ga ni vec.
ROK_VNOSA_S = 3.0


class PrekinjenaPovezava(ConnectionError):
    """Povezava je padla: konec sredi okvirja, tisina ali napaka omrezja.

    Namenoma brez besedila - okno pokaze svoje sporocilo v jeziku uporabnika, ne sistemske napake."""


def _zapri(vticnica) -> None:
    if vticnica is None:
        return
    try:
        vticnica.shutdown(socket.SHUT_RDWR)
    except (OSError, ValueError):
        pass
    try:
        vticnica.close()
    except (OSError, ValueError):
        pass


class PovezavaGledalca:
    """Ena seja TLS: `povezi()` in `okvirji()` klice dekodirna nit, `poslji()` in `zapri()` katerakoli."""

    def __init__(self, seja: Seja, cas_povezave: float = 8.0, tisina_s: float = TISINA_S) -> None:
        self.seja = seja
        self.cas_povezave = cas_povezave
        self.tisina_s = tisina_s
        self._kljuc = threading.Lock()
        self._zaprta = False
        self._surova: Optional[socket.socket] = None      # med povezovanjem: da jo zapri() lahko prekine
        self._vticnica = None                             # ovita (VarnaTls); sele ko je seja vzpostavljena

    # ------------------------------------------------------------------ vzpostavitev
    def _zapomni(self, vticnica) -> None:
        with self._kljuc:
            if self._zaprta:
                _zapri(vticnica)
                raise PrekinjenaPovezava()
            self._surova = vticnica

    @staticmethod
    def _vrstica(vhod) -> bytes:
        zbrano = bytearray()
        while len(zbrano) <= NAJVEC_GLAVA:
            znak = vhod.recv(1)
            if not znak:
                break
            if znak == b"\n":
                return bytes(zbrano)
            zbrano.extend(znak)
        raise ValueError("Neveljavna glava oddaljenega zaslona.")

    def povezi(self) -> dict:
        """Poveze se, preveri pripeti odtis potrdila, poslje zeton in vrne glavo seje."""
        goli = socket.create_connection((self.seja.naslov, self.seja.vrata), timeout=self.cas_povezave)
        self._zapomni(goli)
        goli.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        kontekst = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        kontekst.minimum_version = ssl.TLSVersion.TLSv1_2
        kontekst.check_hostname = False
        kontekst.verify_mode = ssl.CERT_NONE
        tls = kontekst.wrap_socket(goli, server_hostname=self.seja.naslov)
        self._zapomni(tls)
        dejanski = hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest()
        if dejanski != self.seja.odtis:
            _zapri(tls)
            raise ssl.SSLError("Odtis potrdila se ne ujema.")
        tls.settimeout(self.tisina_s)
        tls.sendall(("SAFEER-ZASLON " + self.seja.zeton + "\n").encode("utf-8"))
        glava = json.loads(self._vrstica(tls).decode("utf-8"))
        if not isinstance(glava, dict):
            raise ValueError("Neveljavna glava oddaljenega zaslona.")
        # Od tu naprej bere ena nit, pise druga.
        vticnica = link_vticnik.zavaruj(tls)
        if isinstance(vticnica, link_vticnik.VarnaTls):
            vticnica.nastavi_rok_pisanja(ROK_VNOSA_S)
        with self._kljuc:
            if self._zaprta:
                _zapri(vticnica)
                raise PrekinjenaPovezava()
            self._vticnica = vticnica
        return glava

    # ------------------------------------------------------------------ okvirji in vnos
    @staticmethod
    def _beri(vticnica, koliko: int, na_meji: bool = False) -> Optional[bytes]:
        deli = bytearray()
        while len(deli) < koliko:
            try:
                kos = vticnica.recv(koliko - len(deli))
            except OSError:                       # tudi casovna omejitev in zaprtje iz druge niti
                raise PrekinjenaPovezava() from None
            if not kos:
                if na_meji and not deli:
                    return None
                raise PrekinjenaPovezava()
            deli.extend(kos)
        return bytes(deli)

    def okvirji(self) -> Iterator[Tuple[int, bytes]]:
        """Okvirji (vrsta, telo), dokler naprava povezave ne zapre.

        Konec na meji okvirja je navaden konec (naprava je sejo koncala); konec sredi okvirja, tisina ali
        napaka omrezja je `PrekinjenaPovezava`."""
        vticnica = self._vticnica
        if vticnica is None:
            raise PrekinjenaPovezava()
        while True:
            glava = self._beri(vticnica, 5, na_meji=True)
            if glava is None:
                return
            dolzina = int.from_bytes(glava[1:], "big")
            if dolzina <= 0 or dolzina > NAJVECJI_OKVIR:
                raise ValueError("Pokvarjen okvir oddaljenega zaslona.")
            yield glava[0], self._beri(vticnica, dolzina)

    def poslji(self, dogodek: dict) -> None:
        """Dogodek vnosa napravi. Pred vzpostavitvijo seje ne naredi nicesar; napaka omrezja je OSError."""
        vticnica = self._vticnica
        if vticnica is None:
            return
        vticnica.sendall((json.dumps(dogodek, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))

    def zapri(self) -> None:
        """Konca sejo; nit, ki bere ali se povezuje, se zbudi s `PrekinjenaPovezava`."""
        with self._kljuc:
            self._zaprta = True
            vticnica, surova = self._vticnica, self._surova
            self._vticnica = self._surova = None
        _zapri(vticnica)
        _zapri(surova)


__all__ = ["PovezavaGledalca", "PrekinjenaPovezava", "TISINA_S"]
