"""Samodejno usklajevanje kljucev in dodatkov v ozjem krogu na namizju (secrets.sync) - shramba, posiljanje, prejem.

Lastnik, 25. 10. 2026: kljuce in dodatke vneses enkrat, veljajo na vseh napravah ozjega kroga; lastnik 28. 10. 2026:
na namizju (Linux, nato Windows) se dodatki, kljuci in gesla niso usklajevali. Protokol in pravila so Androidova
(UskladitevKljucev.kt): core/uskladitev_kljucev_pravila.py, outputs/nacrti/uskladitev-kljucev.md.

Sestavni deli (zamenljivi, za preizkuse):
  - Shramba: stanje brez vrednosti (zapisi, naprave, vklop, kljuc lokalnega odtisa) v datoteki 0600;
  - vir (`Vir`): trenutne vrednosti te naprave in uporaba prejetih (Medijski center: debrid kljuci, indeksator Usenet,
    dodatki s poverilnico - `VirMedijev`); vrednosti so v sistemski zbirki skrivnosti, nikoli v dnevniku;
  - link (`Link`): jaz, jedro naprave, ozji krog, seznam naprav z zmoznostmi, zascita od naprave do naprave, ukaz.

Zaklep: pod `_zaklep` ni omrezja (pregled Grok 33, F2) - preverba prejetih kljucev pri storitvi tece brez njega.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from core import uskladitev_kljucev_pravila as P
from core.uskladitev_kljucev_pravila import Meta, Zapis

_log = logging.getLogger("safeer.kljuci_sinh")

#: Kako pogosto (s) se uskladitev sprozi sama, tudi brez spremembe (nova naprava v krogu, povezava po spanju).
SAMODEJNO_S = 10 * 60
#: Vec sprememb v tem casu gre v eno sporocilo (kot Android).
ZDRUZI_S = 3.0
CAS_UKAZA_S = 12.0


def _zdaj_ms() -> int:
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------------------------- shramba
class Shramba:
    """Stanje brez vrednosti: {"meta": {k: {c, i, d, h}}, "naprave": {jedro: {id, ime, s, t}}, "vklopljeno",
    "uvozeno", "k_odtisa"}. Datoteka samo za lastnika (0600); zapis atomarno."""

    def __init__(self, pot: str):
        self.pot = pot

    def _beri(self) -> dict:
        try:
            with open(self.pot, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _pisi(self, d: dict) -> None:
        mapa = os.path.dirname(self.pot) or "."
        os.makedirs(mapa, exist_ok=True)
        zacasna = "%s.%d.tmp" % (self.pot, threading.get_ident())
        fd = os.open(zacasna, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(zacasna, self.pot)

    def _posodobi(self, fn: Callable[[dict], None]) -> None:
        d = self._beri()
        fn(d)
        self._pisi(d)

    # -- zapisi
    def meta(self) -> Dict[str, Meta]:
        izid: Dict[str, Meta] = {}
        for k, m in (self._beri().get("meta") or {}).items():
            if isinstance(m, dict):
                izid[str(k)] = Meta(P._int(m.get("c")), str(m.get("i") or ""), m.get("d") is True, str(m.get("h") or ""))
        return izid

    def pisi_meta(self, meta: Dict[str, Meta]) -> None:
        self._posodobi(lambda d: d.__setitem__("meta", {k: {"c": m.cas, "i": m.izvor, "d": m.izbrisan, "h": m.odtis}
                                                         for k, m in meta.items()}))

    # -- naprave
    def naprave(self) -> Dict[str, dict]:
        n = self._beri().get("naprave") or {}
        return {str(k): v for k, v in n.items() if isinstance(v, dict) and v.get("s") in P.STANJA}

    def pisi_naprave(self, naprave: Dict[str, dict]) -> None:
        self._posodobi(lambda d: d.__setitem__("naprave", naprave))

    # -- nastavitve
    def vklopljeno(self) -> bool:
        return self._beri().get("vklopljeno", True) is not False

    def nastavi_vklopljeno(self, da: bool) -> None:
        self._posodobi(lambda d: d.__setitem__("vklopljeno", bool(da)))

    def uvozeno(self) -> bool:
        return self._beri().get("uvozeno") is True

    def oznaci_uvozeno(self) -> None:
        self._posodobi(lambda d: d.__setitem__("uvozeno", True))

    def kljuc_odtisa(self) -> str:
        """Nakljucen kljuc lokalnega odtisa vrednosti (pregled U8): iz odtisa se kratkega kljuca ne da preveriti brez
        te datoteke. Odtis ne gre med naprave."""
        d = self._beri()
        k = str(d.get("k_odtisa") or "")
        if len(k) >= 32:
            return k
        k = secrets.token_hex(32)
        d["k_odtisa"] = k
        self._pisi(d)
        return k


# ---------------------------------------------------------------------------------------------- cakajoce in spremembe
@dataclass
class Cakajoca:
    """Zapisi z naprave, ki tu se ni potrjena (samo v pomnilniku, P.CAKA_VELJA_MS)."""
    kljuc: str
    id: str
    ime: str
    zapisi: List[Zapis]
    prejeto: int


@dataclass
class Sprememba:
    """Zamenjava ali izbris kljuca z druge naprave (pregled U1) - razveljavitev vrne `prejsnje`."""
    kljuc: str
    id: str
    ime: str
    kljuci: List[str]
    prejsnje: Dict[str, Optional[str]]
    ob: int


@dataclass
class _Pripravljen:
    z: Zapis
    shrani: Callable[[], bool]


class Uskladitev:
    """En objekt na proces (Safeer Control). `vir` in `link` glej docstring modula."""

    def __init__(self, shramba: Shramba, vir, link, ura: Callable[[], int] = _zdaj_ms):
        self.shramba = shramba
        self.vir = vir
        self.link = link
        self._ura = ura
        self._zaklep = threading.RLock()
        self._cakajoce: Dict[str, Cakajoca] = {}
        self._spremembe: Dict[str, Sprememba] = {}
        self._casovnik: Optional[threading.Timer] = None
        self._zaklep_casovnika = threading.Lock()
        #: Klic ob napravi, ki caka na potrditev (okno ali obvestilo) in ob zamenjavi z druge naprave.
        self.ob_vprasanju: Optional[Callable[[Cakajoca], None]] = None
        self.ob_spremembi: Optional[Callable[[Sprememba], None]] = None

    # -- nastavitve
    def vklopljeno(self) -> bool:
        return self.shramba.vklopljeno()

    def nastavi_vklopljeno(self, da: bool) -> None:
        self.shramba.nastavi_vklopljeno(da)
        if da:
            self.sprozi(0.5)

    # -- naprave
    def _jedro(self, ident: str) -> str:
        try:
            return str(self.link.jedro(ident) or "") or ident
        except Exception:  # noqa: BLE001
            return ident

    def _v_krogu(self, ident: str) -> bool:
        try:
            return bool(ident) and bool(self.link.v_krogu(ident))
        except Exception:  # noqa: BLE001 - »ne vem« ni »da«
            return False

    def _jaz(self) -> str:
        try:
            return str(self.link.jaz() or "")
        except Exception:  # noqa: BLE001
            return ""

    def _ime_naprave(self, ident: str) -> str:
        try:
            for n in self.link.naprave():
                if str(n.get("id") or "") == ident:
                    return str(n.get("ime") or "")[:80]
        except Exception as e:  # noqa: BLE001 - ime je samo za prikaz
            _log.info("ime naprave: %s", type(e).__name__)
        return ""

    def _zapomni(self, ident: str, ime: str, stanje: str, usklajeno: bool) -> None:
        with self._zaklep:
            k = self._jedro(ident)
            vse = self.shramba.naprave()
            prej = vse.get(k) or {}
            vse[k] = {"id": ident, "ime": (ime or str(prej.get("ime") or ""))[:80], "s": stanje,
                      "t": self._ura() if usklajeno else int(prej.get("t") or 0)}
            self.shramba.pisi_naprave(vse)

    def stanje_naprave(self, ident: str) -> Optional[str]:
        return (self.shramba.naprave().get(self._jedro(ident)) or {}).get("s")

    def naprave(self) -> List[dict]:
        """Naprave, s katerimi se ta naprava usklajuje (seznam v nastavitvah): {kljuc, id, ime, stanje, zadnjic}."""
        return sorted(({"kljuc": k, "id": v.get("id", ""), "ime": v.get("ime", ""), "stanje": v.get("s"),
                        "zadnjic": int(v.get("t") or 0)} for k, v in self.shramba.naprave().items()),
                      key=lambda n: str(n["ime"]).lower())

    def dovoli_znova(self, kljuc: str) -> None:
        with self._zaklep:
            vse = self.shramba.naprave()
            if vse.pop(kljuc, None) is None:
                return
            self.shramba.pisi_naprave(vse)
        self.sprozi(0.5)

    def _pocisti_zunaj_kroga(self) -> None:
        """Pregled U11: naprava zunaj ozjega kroga izgubi stanje (tudi potrditev); zavrnitev ostane."""
        with self._zaklep:
            vse = self.shramba.naprave()
            zunaj = []
            for k, n in vse.items():
                if n.get("s") == P.ZAVRNJENA:
                    continue
                try:
                    v = bool(self.link.v_krogu(str(n.get("id") or "")))
                except Exception:  # noqa: BLE001 - Grok 15, N16: napaka pri preverbi ni »zunaj«
                    v = True
                if not v:
                    zunaj.append(k)
            if not zunaj:
                return
            for k in zunaj:
                vse.pop(k, None)
                self._cakajoce.pop(k, None)
                self._spremembe.pop(k, None)
            self.shramba.pisi_naprave(vse)
            _log.info("naprav zunaj ozjega kroga pozabljenih: %d", len(zunaj))

    # -- vrednosti te naprave
    def _odtis(self, v: str) -> str:
        return hmac.new(self.shramba.kljuc_odtisa().encode(), ("safeer-sinh|" + v).encode("utf-8"),
                        hashlib.sha256).hexdigest()[:16]

    def _posodobi(self) -> Tuple[Dict[str, Meta], Dict[str, str]]:
        """Lastne spremembe v zapise (pod zaklepom, brez omrezja). Vrne zapise in vrednosti."""
        with self._zaklep:
            vrednosti, neznani = self.vir.trenutne()
            meta = self.shramba.meta()
            odtisi = {k: self._odtis(v) for k, v in vrednosti.items()}
            uvoz = not self.shramba.uvozeno()
            spr = P.lokalne_spremembe(meta, odtisi, set(neznani), self._jaz(), self._ura(), uvoz)
            if spr:
                meta.update(spr)
                self.shramba.pisi_meta(meta)
            if uvoz:
                self.shramba.oznaci_uvozeno()
            return meta, vrednosti

    def odstrani(self, kljuc: str, v_krog: bool, brisi: Callable[[], None]) -> None:
        """Gumb »Odstrani« (Grok 33, F1): kljuc, ki tu ni veljal, se pozabi brez groba (drugim napravam ne izbrise)."""
        with self._zaklep:
            if not v_krog:
                meta = self.shramba.meta()
                potem = P.po_odstranitvi(meta, kljuc, False)
                if len(potem) != len(meta):
                    self.shramba.pisi_meta(potem)
            brisi()
        self.sprozi()

    # -- sporocilo
    def _z_gostitelji(self, zapisi: Sequence[Zapis]) -> List[Zapis]:
        izid = []
        for z in zapisi:
            if not z.izbrisan and z.kljuc.startswith(P.PREDPONA_DODATKA):
                try:
                    g = self.vir.gostitelj(z.vrednost)
                except Exception:  # noqa: BLE001
                    g = ""
                izid.append(Zapis(z.kljuc, z.cas, z.izvor, z.izbrisan, z.vrednost, P.samo_ime_gostitelja(g)))
            else:
                izid.append(z)
        return izid

    # -- prejem zapisov s potrjene naprave
    def _prejmi_zapise(self, od: str, ime: str, zapisi: Sequence[Zapis]) -> int:
        od_naprava = self._jedro(od)
        jaz = self._jaz()
        ponudniki = set(self.vir.ponudniki())
        with self._zaklep:
            self._posodobi()
            kandidati = P.za_uporabo(self.shramba.meta(), zapisi, self._ura(), ponudniki, self.vir.veljavna_vrednost,
                                     lambda izvor: izvor != jaz and P.izvor_posiljatelja(self._jedro(izvor), od_naprava))
        if not kandidati:
            return 0
        # Brez zaklepa: preverba prejetih kljucev pri storitvi (omrezje).
        pripravljeni: Dict[Zapis, _Pripravljen] = {}
        for z in kandidati:
            try:
                shrani = self.vir.pripravi(z)
            except Exception as e:  # noqa: BLE001
                _log.info("pripravi: %s", type(e).__name__)
                shrani = None
            if shrani is not None:
                pripravljeni[z] = _Pripravljen(z, shrani)
        if not pripravljeni:
            return 0
        zamenjani: List[str] = []
        prejsnje: Dict[str, Optional[str]] = {}
        with self._zaklep:
            self._posodobi()
            meta = self.shramba.meta()
            vsi = P.se_vedno_novejsi(meta, list(pripravljeni))
            vr, neberljivi = self.vir.trenutne() if vsi else ({}, set())
            za_uporabo = P.brez_neberljivih(vsi, set(neberljivi))
            zam = P.zamenjave(meta, za_uporabo)
            if zam:
                prejsnje = {z.kljuc: vr.get(z.kljuc) for z in zam}
            shranjeni: List[Zapis] = []
            for z in za_uporabo:
                try:
                    ok = bool(pripravljeni[z].shrani())
                except Exception as e:  # noqa: BLE001
                    _log.info("shrani: %s", type(e).__name__)
                    ok = False
                if ok:
                    shranjeni.append(z)
            if shranjeni:
                po_shranitvi = self.vir.trenutne()[0] if any(not z.izbrisan for z in shranjeni) else {}
                for z in shranjeni:
                    meta[z.kljuc] = Meta(z.cas, z.izvor, z.izbrisan, "" if z.izbrisan else
                                         self._odtis(P.vrednost_za_odtis(z.vrednost, po_shranitvi.get(z.kljuc))))
                self.shramba.pisi_meta(meta)
            uspeli = {z.kljuc for z in shranjeni}
            zamenjani = [z.kljuc for z in zam if z.kljuc in uspeli]
            n = len(shranjeni)
        if n:
            _log.info("prejetih sprememb: %d", n)
            if zamenjani:
                zdaj = self._ura()
                with self._zaklep:
                    prej = self._spremembe.get(od_naprava)
                    stara = prej if prej is not None and P.caka_velja(prej.ob, zdaj) else None
                    kljuci, vrednosti = P.zdruzi_spremembi(stara.kljuci if stara else [], stara.prejsnje if stara else {},
                                                           zamenjani, {k: prejsnje.get(k) for k in zamenjani})
                    s = self._spremembe[od_naprava] = Sprememba(od_naprava, od, ime, kljuci, vrednosti, zdaj)
                if self.ob_spremembi is not None:
                    try:
                        self.ob_spremembi(s)
                    except Exception as e:  # noqa: BLE001 - obvestilo ne sme podreti prejema
                        _log.info("obvestilo o spremembi: %s", type(e).__name__)
        return n

    # -- posiljanje
    def sprozi(self, zamik: float = ZDRUZI_S) -> None:
        """Uskladitev z vsemi napravami v ozjem krogu v ozadju; vec sprememb v `zamik` gre v eno."""
        if not self.vklopljeno():
            return
        with self._zaklep_casovnika:
            if self._casovnik is not None:
                self._casovnik.cancel()
            t = threading.Timer(max(0.0, zamik), self._uskladi_varno)
            t.daemon = True
            t.name = "safeer-kljuci-sinh"
            self._casovnik = t
            t.start()

    def _uskladi_varno(self) -> None:
        try:
            self.uskladi_zdaj()
        except Exception as e:  # noqa: BLE001
            _log.info("uskladitev: %s", type(e).__name__)

    def uskladi_zdaj(self) -> int:
        """Vrne stevilo naprav, ki so dobile sporocilo."""
        if not self.vklopljeno():
            return 0
        try:
            if not self.link.povezan():
                return 0
        except Exception:  # noqa: BLE001
            return 0
        self._pocisti_zunaj_kroga()
        try:
            self.vir.preveri_nepreverjene()       # poslje se samo kljuc, ki ga je storitev potrdila
        except Exception as e:  # noqa: BLE001
            _log.info("preverba kljucev: %s", type(e).__name__)
        meta, vr = self._posodobi()
        lastni = self._z_gostitelji(P.za_poslati(meta, vr, self._jaz()))
        povabilo = P.za_povabilo(lastni)
        stanja = self.shramba.naprave()
        videne: Set[str] = set()
        poslanih = 0
        naprave = sorted(self.link.naprave(), key=lambda n: P.ZMOZNOST not in (n.get("zmoznosti") or []))
        for n in naprave:
            ident = str(n.get("id") or "")
            if not ident or ident == self._jaz():
                continue
            if not self._v_krogu(ident):            # ozji krog TE naprave - ob vsakem posiljanju
                continue
            k = self._jedro(ident)
            if k in videne:
                continue
            videne.add(k)
            ime = str(n.get("ime") or "")
            zmoznost = P.ZMOZNOST in (n.get("zmoznosti") or [])
            zapis = stanja.get(k) or {}
            prej = zapis.get("s") if zapis.get("s") != P.STARA else None
            if not zmoznost:
                if not zapis or zapis.get("s") == P.STARA:
                    self._zapomni(ident, ime, P.STARA, False)
                continue
            try:
                zascita = bool(self.link.zna_zascito(ident))
            except Exception:  # noqa: BLE001
                zascita = False
            if not P.sme_poslati(True, True, zascita, True, True, prej):
                continue
            if prej is None:
                self._zapomni(ident, ime, P.POVABLJENA, False)
            self._poslji_napravi(ident, ime, lastni if P.vrednosti_za(prej) else povabilo)
            poslanih += 1
        if poslanih:
            _log.info("uskladitev: zapisov %d, naprav %d", len(lastni), poslanih)
        return poslanih

    def _poslji_napravi(self, ident: str, ime: str, zapisi: Sequence[Zapis]) -> None:
        par = {"v": P.VERZIJA, "items": P.v_json(zapisi)}
        izid = self.link.ukaz(ident, P.DEJANJE, par, CAS_UKAZA_S) or {}
        if not self.vklopljeno() or not self._v_krogu(ident):
            return                                      # U11: medtem izklopljeno ali odstranjena iz kroga
        data = izid.get("data") if isinstance(izid.get("data"), dict) else {}
        koda = str(izid.get("koda") or izid.get("code") or "")
        if izid.get("ok") and data.get("accepted") is True:
            prejeti = P.iz_json(data.get("items"))
            if self.stanje_naprave(ident) == P.POTRJENA:
                self._zapomni(ident, ime, P.POTRJENA, True)
                self._prejmi_zapise(ident, ime, prejeti)
            else:
                self._vprasaj(ident, ime, prejeti)       # U1: tudi pobudnik potrdi enkrat
        elif data.get("pending") is True:
            pass                                         # caka na potrditev tam
        elif data.get("reason") == "zavrnjeno":
            self._zapomni(ident, ime, P.ZAVRNJENA, False)
        elif koda == "neznano_dejanje":
            self._zapomni(ident, ime, P.STARA, False)

    # -- prejem (dejanje secrets.sync)
    def _vprasaj(self, od: str, ime: str, zapisi: Sequence[Zapis]) -> None:
        k = self._jedro(od)
        c = Cakajoca(k, od, ime, list(zapisi), self._ura())
        with self._zaklep:
            self._cakajoce[k] = c
        self._zapomni(od, ime, P.CAKA, False)
        _log.info("naprava v ozjem krogu zeli uskladiti kljuce (caka na potrditev), zapisov %d", len(zapisi))
        if self.ob_vprasanju is not None:
            try:
                self.ob_vprasanju(c)
            except Exception as e:  # noqa: BLE001 - obvestilo ne sme podreti prejema
                _log.info("obvestilo za potrditev: %s", type(e).__name__)

    def prejmi(self, od: str, ime: str, parametri: dict, zascita: str = "") -> dict:
        """`secrets.sync` z druge naprave. Samo po preverjeni seji od naprave do naprave (`zascita` = jedro
        preverjenega kljuca, ki se mora ujemati s posiljateljem) in samo od naprave v ozjem krogu (preveri se tu)."""
        try:
            ujema = bool(zascita) and bool(self.link.ujema_zascito(od, zascita))
        except Exception:  # noqa: BLE001
            ujema = False
        if not ujema:
            return {"accepted": False, "reason": "zascita"}
        ime = ime or self._ime_naprave(od)
        v_krogu = self._v_krogu(od)
        if not v_krogu:
            self._pocisti_zunaj_kroga()
        zapisi = P.iz_json((parametri or {}).get("items"))
        odziv = P.sprejem(self.vklopljeno(), v_krogu, self.stanje_naprave(od))
        if odziv == P.ZAVRNI:
            razlog = "izklopljeno" if not self.vklopljeno() else ("ni_krog" if not v_krogu else "zavrnjeno")
            return {"accepted": False, "reason": razlog}
        if odziv == P.VPRASAJ:
            self._vprasaj(od, ime, zapisi)
            return {"accepted": False, "pending": True}
        self._zapomni(od, ime, P.POTRJENA, True)

        def delo() -> None:
            try:
                if self.vklopljeno() and self._v_krogu(od):
                    self._prejmi_zapise(od, ime, zapisi)
            except Exception as e:  # noqa: BLE001
                _log.info("prejem: %s", type(e).__name__)
        threading.Thread(target=delo, name="safeer-kljuci-prejem", daemon=True).start()
        meta, vr = self._posodobi()
        return {"accepted": True, "items": P.v_json(self._z_gostitelji(P.za_poslati(meta, vr, self._jaz())))}

    # -- potrditev in razveljavitev (okno ali obvestilo)
    def cakajoca(self) -> Optional[Cakajoca]:
        zdaj = self._ura()
        with self._zaklep:
            for k in [k for k, c in self._cakajoce.items() if not P.caka_velja(c.prejeto, zdaj)]:
                self._cakajoce.pop(k, None)
            return min(self._cakajoce.values(), key=lambda c: c.prejeto, default=None)

    def opis_zapisov(self, c: Cakajoca) -> List[str]:
        izid: List[str] = []
        for z in c.zapisi:
            if z.izbrisan:
                continue
            ime = self.vir.ime_kljuca(z.kljuc, z.vrednost, z.gostitelj)
            if ime and ime not in izid:
                izid.append(ime)
        return izid

    def potrdi(self, kljuc: str, da: bool) -> None:
        with self._zaklep:
            c = self._cakajoce.pop(kljuc, None)
        if c is None:
            return
        if not da:
            self._zapomni(c.id, c.ime, P.ZAVRNJENA, False)
            return
        if not self.vklopljeno() or not self._v_krogu(c.id):
            return
        self._zapomni(c.id, c.ime, P.POTRJENA, True)
        sveze = P.caka_velja(c.prejeto, self._ura())

        def delo() -> None:
            try:
                if sveze and self._v_krogu(c.id):
                    self._prejmi_zapise(c.id, c.ime, c.zapisi)
            finally:
                self.sprozi(0.2)
        threading.Thread(target=delo, name="safeer-kljuci-potrditev", daemon=True).start()

    def sprememba(self) -> Optional[Sprememba]:
        zdaj = self._ura()
        with self._zaklep:
            for k in [k for k, s in self._spremembe.items() if not P.caka_velja(s.ob, zdaj)]:
                self._spremembe.pop(k, None)
            return min(self._spremembe.values(), key=lambda s: s.ob, default=None)

    def opis_spremembe(self, s: Sprememba) -> List[str]:
        izid: List[str] = []
        for k in s.kljuci:
            ime = self.vir.ime_kljuca(k, s.prejsnje.get(k), "")
            if ime and ime not in izid:
                izid.append(ime)
        return izid

    def potrdi_spremembo(self, s: Sprememba, razveljavi: bool) -> None:
        with self._zaklep:
            self._spremembe.pop(s.kljuc, None)
        if not razveljavi:
            return

        def delo() -> None:
            with self._zaklep:
                for k in s.kljuci:
                    try:
                        self.vir.obnovi(k, s.prejsnje.get(k))
                    except Exception as e:  # noqa: BLE001
                        _log.info("obnovi: %s", type(e).__name__)
            _log.info("razveljavljenih sprememb z druge naprave: %d", len(s.kljuci))
            self.sprozi(0.2)
        threading.Thread(target=delo, name="safeer-kljuci-razveljavi", daemon=True).start()


# ---------------------------------------------------------------------------------------------- en objekt na proces
_STORITEV: Optional[Uskladitev] = None


def nastavi(storitev: Optional[Uskladitev]) -> None:
    global _STORITEV
    _STORITEV = storitev


def storitev() -> Optional[Uskladitev]:
    return _STORITEV
