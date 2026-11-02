"""secrets.sync na namizju: povezava storitve (core/uskladitev_kljucev.py) z Medijskim centrom in Safeer Linkom.

VirMedijev - vrednosti te naprave iz Medijskega centra (core/os_media.MediaCenter):
  - debrid kljuci (TorBox, Real-Debrid, AllDebrid): z vrednostjo samo kljuc, ki ga je storitev potrdila;
  - indeksator Usenet ({"url", "key"}): enako;
  - dodatki Stremio s poverilnico (`dodatek:<odtis>`, pravi naslov iz zbirke skrivnosti).
  Ponudnik Usenet (NNTP z geslom), viri IPTV z racunom in zaupanje zaslona se na namizju (se) ne usklajujejo: zapisi s
  temi kljuci se prezrejo, nicesar ne posljemo in ne izbrisemo.
  Prejeti debrid kljuc in indeksator se pred uporabo preverita pri storitvi s TE naprave (zavrnjen ne prepise
  veljavnega); dodatek se doda kot ob rocnem vnosu (preverba manifesta).

LinkSafeer - jaz, jedro naprave, ozji krog, naprave z zmoznostmi in ukaz (core/safeer_link.SafeerLink).
"""
from __future__ import annotations

import json
import logging
import urllib.parse
from typing import Callable, Dict, Optional, Set, Tuple

from core import debrid, debrid_pravila as DP, skrivni_dodatki, usenet_pravila as UP
from core import uskladitev_kljucev_pravila as P

_log = logging.getLogger("safeer.kljuci_sinh")


class VirMedijev:
    def __init__(self, dobi_mc: Callable[[], object]):
        self._mc = dobi_mc

    # -- pomocniki
    def _dbr(self):
        return self._mc().debrid

    def _nastavitve_debrid(self) -> dict:
        try:
            d = self._dbr()._nastavitve()
            return d if isinstance(d, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def _dodatki(self) -> list:
        mc = self._mc()
        try:
            with mc._lock:
                viri = mc._load().get("osebni_strezniki", [])
        except Exception:  # noqa: BLE001
            return []
        return [s for s in viri if isinstance(s, dict) and s.get("ponudnik") == "stremio" and s.get("url_enc")]

    @staticmethod
    def _odtis_vira(s: dict) -> Optional[str]:
        osnova = skrivni_dodatki.nadomestna_osnova(str(s.get("url") or ""))
        if not osnova:
            return None
        odtis = osnova.rsplit(skrivni_dodatki.OZNAKA, 1)[-1]
        return odtis if len(odtis) == 16 else None

    # -- Vir
    def ponudniki(self) -> Set[str]:
        return set(DP.VSI)

    def trenutne(self) -> Tuple[Dict[str, str], Set[str]]:
        vrednosti: Dict[str, str] = {}
        neznani: Set[str] = set()
        dbr = self._dbr()
        nast = self._nastavitve_debrid()
        for p in DP.VSI:
            k = P.kljuc_debrid(p)
            try:
                kljuc = dbr.kljuc(p)
                velja = dbr.kljuc_velja(p)
            except Exception:  # noqa: BLE001 - zbirka zaklenjena: neznan
                kljuc, velja = None, False
            shranjen = bool((nast.get("kljuci") or {}).get(p))
            o = P.oddaja(kljuc is not None, shranjen, velja)
            if o == P.VREDNOST and kljuc:
                vrednosti[k] = kljuc
            elif o == P.NEZNAN:
                neznani.add(k)
        try:
            ix = dbr.indeksator()
            ix_velja = DP.za_uskladitev(dbr.stanje_kljuca(DP.INDEKSATOR))
        except Exception:  # noqa: BLE001
            ix, ix_velja = None, False
        o = P.oddaja(ix is not None, isinstance(nast.get("usenet"), dict) and bool(nast.get("usenet")), ix_velja)
        if o == P.VREDNOST and ix:
            vrednosti[P.KLJUC_USENET] = json.dumps({"url": ix[0], "key": ix[1]}, separators=(",", ":"))
        elif o == P.NEZNAN:
            neznani.add(P.KLJUC_USENET)
        mc = self._mc()
        for s in self._dodatki():
            odtis = self._odtis_vira(s)
            if odtis is None:
                continue
            k = P.kljuc_dodatka(odtis)
            try:
                pravi = mc._odkleni_dodatek(skrivni_dodatki.nadomestna_osnova(str(s.get("url") or "")))
            except Exception:  # noqa: BLE001
                pravi = None
            if pravi and skrivni_dodatki.veljaven_skrivni_dodatek(pravi):
                vrednosti[k] = pravi
            else:
                neznani.add(k)
        return vrednosti, neznani

    def veljavna_vrednost(self, k: str, v: str) -> bool:
        if k.startswith(P.PREDPONA_DEBRID):
            p = k[len(P.PREDPONA_DEBRID):]
            return p in DP.VSI and DP.kljuc_iz_vnosa(v, p) is not None
        if k == P.KLJUC_USENET:
            try:
                d = json.loads(v)
            except ValueError:
                return False
            return (isinstance(d, dict) and UP.osnova(d.get("url")) is not None
                    and DP.kljuc_iz_vnosa(d.get("key"), DP.INDEKSATOR) is not None)
        if k.startswith(P.PREDPONA_DODATKA):
            predpona = skrivni_dodatki.skrivna_predpona_dodatka(v)
            return (skrivni_dodatki.veljaven_skrivni_dodatek(v) and predpona is not None
                    and skrivni_dodatki.odtis(predpona) == k[len(P.PREDPONA_DODATKA):])
        return False                    # usenet_ponudnik, iptv, zaupanje: namizje jih se ne usklajuje

    def pripravi(self, z) -> Optional[Callable[[], bool]]:
        """Brez zaklepa storitve (omrezje): preverba prejetega kljuca s te naprave; vrne shranjevanje ali None."""
        dbr = self._dbr()
        if z.kljuc.startswith(P.PREDPONA_DEBRID):
            p = z.kljuc[len(P.PREDPONA_DEBRID):]
            if z.izbrisan:
                return lambda: (dbr.pozabi_kljuc(p), True)[1]
            kljuc = DP.kljuc_iz_vnosa(z.vrednost, p)
            izid, paket = debrid.preveri_kljuc(p, kljuc)
            if not DP.sprejmi_prejetega(izid):
                _log.info("prejet kljuc %s: storitev ga s te naprave ne potrdi (%s)", p, izid)
                return None
            return lambda: bool(dbr.nastavi_kljuc(p, kljuc, paket, DP.STANJE_VELJA))
        if z.kljuc == P.KLJUC_USENET:
            if z.izbrisan:
                return lambda: (dbr.pozabi_indeksator(), True)[1]
            d = json.loads(z.vrednost)
            osn, kljuc = UP.osnova(d.get("url")), DP.kljuc_iz_vnosa(d.get("key"), DP.INDEKSATOR)
            if not DP.sprejmi_prejetega(debrid.indeksator_preveri(osn, kljuc)):
                return None
            return lambda: bool(dbr.nastavi_indeksator(osn, kljuc, DP.STANJE_VELJA))
        if z.kljuc.startswith(P.PREDPONA_DODATKA):
            odtis = z.kljuc[len(P.PREDPONA_DODATKA):]
            if z.izbrisan:
                return lambda: self._odstrani_dodatek(odtis)
            return lambda: self._dodaj_dodatek(z.vrednost)
        return None

    def _odstrani_dodatek(self, odtis: str) -> bool:
        mc = self._mc()
        for s in self._dodatki():
            if self._odtis_vira(s) == odtis:
                return bool(mc.remove_source(str(s.get("id") or "")))
        return True                     # ga ni - izbris je ze izveden

    def _dodaj_dodatek(self, pravi: str) -> bool:
        izid = self._mc().add_server("stremio", "", pravi, "", "")
        return bool(izid.get("ok") or izid.get("podvojen"))

    def obnovi(self, k: str, v: Optional[str]) -> bool:
        """Razveljavitev: prejsnja vrednost nazaj BREZ omrezja kot nepreverjena (uskladitev jo preveri)."""
        dbr = self._dbr()
        if k.startswith(P.PREDPONA_DEBRID):
            p = k[len(P.PREDPONA_DEBRID):]
            if v is None:
                dbr.pozabi_kljuc(p)
                return True
            return bool(dbr.nastavi_kljuc(p, v))
        if k == P.KLJUC_USENET:
            if v is None:
                dbr.pozabi_indeksator()
                return True
            d = json.loads(v)
            return bool(dbr.nastavi_indeksator(str(d.get("url") or ""), str(d.get("key") or "")))
        if k.startswith(P.PREDPONA_DODATKA):
            return self._odstrani_dodatek(k[len(P.PREDPONA_DODATKA):]) if v is None else self._dodaj_dodatek(v)
        return False

    def preveri_nepreverjene(self) -> None:
        try:
            self._dbr().preveri_nepreverjene()
        except Exception as e:  # noqa: BLE001
            _log.info("preverba nepreverjenih: %s", type(e).__name__)

    @staticmethod
    def gostitelj(v: str) -> str:
        try:
            return (urllib.parse.urlsplit(v).hostname or "").lower()
        except ValueError:
            return ""

    def ime_kljuca(self, k: str, v: Optional[str], g: str) -> str:
        if k.startswith(P.PREDPONA_DEBRID):
            return DP.ime(k[len(P.PREDPONA_DEBRID):])
        if k == P.KLJUC_USENET:
            return "Usenet"
        if k.startswith(P.PREDPONA_DODATKA):
            return "Dodatek " + P.prikaz_gostitelja(v or "", g, self.gostitelj(v or ""))
        return ""


class LinkSafeer:
    """Prilagoditev za core/safeer_link.SafeerLink (Safeer Control)."""

    def __init__(self, link):
        self._link = link

    def jaz(self) -> str:
        return str(self._link._id() or "")

    def jedro(self, ident: str) -> str:
        from core import link_dostop
        return link_dostop.jedro(ident)

    def v_krogu(self, ident: str) -> bool:
        from core import link_dostop
        return link_dostop.v_ozjem_krogu(ident)

    def ujema_zascito(self, ident: str, zascita: str) -> bool:
        from core import link_dostop
        return link_dostop.ujema_zascito(ident, zascita)

    def naprave(self) -> list:
        return [n for n in (getattr(self._link, "naprave", None) or []) if isinstance(n, dict)]

    def zna_zascito(self, ident: str) -> bool:
        p = getattr(self._link, "povezava", None)
        try:
            return p is not None and p._upravitelj_zascite() is not None and bool(p._naprava_zna_zascito(ident))
        except Exception:  # noqa: BLE001
            return False

    def povezan(self) -> bool:
        p = getattr(self._link, "povezava", None)
        return p is not None and bool(getattr(p, "tece", False))

    def ukaz(self, ident: str, dejanje: str, parametri: dict, cas: float) -> dict:
        return self._link.ukaz_pocakaj(ident, dejanje, parametri, cas=cas)
