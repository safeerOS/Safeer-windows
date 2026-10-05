"""Obrambni mehanizem sredisca Safeer Linka: steje sovrazne dogodke po viru in vir za nekaj casa zapre.

Sredisce poslusa v domacem omrezju. Kdor ni clan kroga zaupanja, tam nima kaj iskati - a doslej je lahko poskusal
brez konca: tipal poti, ugibal kodo seznanitve (vsak zacetek seznanitve uporabniku pokaze obvestilo), posiljal
zavrnjene podpise in vstopnice, odpiral povezave. Stevilo poskusov je bilo omejeno samo znotraj ene prijave.

Pravila (docs/LINK-DEFENCE.md):

- vsak sovrazen dogodek ima tezo; ko vsota tez enega vira v zadnji minuti doseze PRAG, je vir zaprt. Zapora je tiha:
  povezava se zapre takoj po sprejemu - brez rokovanja TLS, brez potrdila, brez odgovora;
- zapora traja ZAPORA_S, ob vsaki ponovitvi dvakrat dlje (do NAJDALJSA_ZAPORA_S);
- vir, ki se je pravkar izkazal kot clan kroga (veljaven podpis, vstopnica ali zeton) ali ima pri sredisci odprto
  povezavo, je zaupan: gole povezave se mu ne stejejo (telefon, ki lista mapo s slikami, jih odpre na stotine),
  sovrazni dogodki pa stejejo polovico;
- ta naprava sama (127.0.0.1, ::1) ni nikoli zaprta: od tam prihajajo lastni programi in kanali Global Linka;
- vec zaprtih virov v kratkem casu ali vir, ki se po zapori vraca, je napad: sredisce ga sporoci (ob_napadu).

Modul je cista logika (ura je parameter): brez omrezja, niti in datotek. Isti za Linux in Windows.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from typing import Callable, Deque, Dict, List, Optional, Tuple

#: Teza dogodka (cela stevila, da je vsota natancna). Legitimna naprava jih naredi nekaj na minuto (prijava pod drugim
#: id-jem vrne 401, iskanje sredisca poskusi tudi goli HTTP); napadalec jih naredi na desetine.
TEZE: Dict[str, int] = {
    "povezava": 1,          # sprejeta povezava vira, ki ni zaupan (poplava: 400 na minuto)
    "rokovanje": 10,        # rokovanje TLS ni uspelo (ni TLS, pregledovalnik vrat, tiha povezava)
    "tipanje": 10,          # pot, ki je sredisce nima, ali okvarjena zahteva
    "brez_zaupanja": 20,    # zavrnjen podpis, vstopnica ali zeton; koda QR, ki je ni (20 na minuto)
    "okvir": 20,            # pokvarjen okvir WebSocket
    "poskus_kode": 20,      # en krog SPAKE2 = en poskus kode (prijava ima pet krogov)
    "seznanitev": 40,       # napacna koda, prevec poskusov, zacetek prijave s kodo QR (10 na minuto)
    "zacetek_seznanitve": 100,  # zacetek seznanitve s kodo: uporabniku pokaze obvestilo (cetrti v minuti zapre vir)
}
#: Okno stetja in prag vsote tez v njem.
OKNO_S = 60.0
PRAG = 400
#: Trajanje zapore; ob ponovitvi se podvoji.
ZAPORA_S = 600.0
NAJDALJSA_ZAPORA_S = 3600.0
#: Po toliko casu brez nove zapore se stetje ponovitev vira zacne znova.
POZABI_PONOVITVE_S = 24 * 3600.0
#: Kako dolgo po uspesni prijavi velja vir za zaupanega.
ZAUPANJE_S = 600.0
#: Najvec virov v spominu (najstarejsi nezaprti izpadejo) in dogodkov na vir.
NAJVEC_VIROV = 1024
NAJVEC_DOGODKOV = 1024
#: Opozorilo v dnevnik, ko vir doseze polovico praga (najvec enkrat na OPOZORILO_VSAKIH_S): tako se lazni preplah
#: prave naprave vidi, se preden je zaprta.
OPOZORILO_PRAG = PRAG // 2
OPOZORILO_VSAKIH_S = 600.0
#: Napad: toliko razlicnih virov zaprtih v NAPAD_OKNO_S ali isti vir zaprt tolikokrat.
NAPAD_VIROV = 3
NAPAD_PONOVITEV = 3
NAPAD_OKNO_S = 1800.0


def je_ta_naprava(vir: str) -> bool:
    """Ali povezava prihaja s te naprave same (zanka)."""
    v = (vir or "").strip().lower()
    if v.startswith("::ffff:"):
        v = v[7:]
    return v == "::1" or v == "localhost" or v.startswith("127.")


class _Vir:
    __slots__ = ("dogodki", "zaprt_do", "ponovitev", "zadnja_zapora", "zaupan_do", "razlog", "sestava", "opozorjen")

    def __init__(self) -> None:
        self.dogodki: Deque[Tuple[float, int, str]] = deque(maxlen=NAJVEC_DOGODKOV)
        self.zaprt_do = 0.0
        self.ponovitev = 0
        self.zadnja_zapora = 0.0
        self.zaupan_do = 0.0
        self.razlog = ""
        self.sestava: Dict[str, int] = {}
        self.opozorjen = -1e18


class Obramba:
    """Stetje sovraznih dogodkov po viru (naslov IP). Varno za vec niti; povratni klici tecejo zunaj zaklepa."""

    def __init__(self, ura: Callable[[], float] = time.monotonic,
                 ob_zapori: Optional[Callable[[str, float, str], None]] = None,
                 ob_napadu: Optional[Callable[[List[str]], None]] = None,
                 izvzet: Callable[[str], bool] = je_ta_naprava,
                 zaupan: Optional[Callable[[str], bool]] = None,
                 ob_opozorilu: Optional[Callable[[str, int, Dict[str, int]], None]] = None) -> None:
        self.ura = ura
        self.ob_zapori = ob_zapori
        self.ob_napadu = ob_napadu
        #: (vir, vsota tez, sestava po vrstah) - vir je na polovici praga; samo za dnevnik.
        self.ob_opozorilu = ob_opozorilu
        self.izvzet = izvzet
        #: Zaupanje od zunaj: ali ima vir pri sredisci odprto povezavo (prijavljena naprava, sosednje sredisce).
        #: Klice se zunaj zaklepa (sme vzeti zaklep sredisca).
        self.zaupan = zaupan
        self._viri: "OrderedDict[str, _Vir]" = OrderedDict()
        self._zaklep = threading.Lock()
        self._zavrnjenih = 0
        self._zapore: Deque[Tuple[float, str]] = deque(maxlen=64)     # (kdaj, vir) - za prepoznavo napada
        self._napad_javljen = -1e18

    # ------------------------------------------------------------------ vhod

    def dovoli(self, vir: str) -> bool:
        """Ob sprejemu povezave: False = vir je zaprt, povezavo zapri brez odgovora. Povezavo tudi presteje."""
        if not vir or self.izvzet(vir):
            return True
        obvestila = []
        povezan = self._povezan(vir)
        with self._zaklep:
            zdaj = self.ura()
            v = self._vir(vir, zdaj)
            if v.zaprt_do > zdaj:
                self._zavrnjenih += 1
                return False
            if v.zaupan_do <= zdaj and not povezan:
                v.dogodki.append((zdaj, TEZE["povezava"], "povezava"))
                obvestila = self._oceni(vir, v, zdaj)
            dovoljen = v.zaprt_do <= zdaj
        self._obvesti(obvestila)
        return dovoljen

    def dogodek(self, vir: str, vrsta: str) -> None:
        """Sovrazen dogodek vira (kljuc iz TEZE; neznana vrsta steje kot tipanje)."""
        if not vir or self.izvzet(vir):
            return
        povezan = self._povezan(vir)
        with self._zaklep:
            zdaj = self.ura()
            v = self._vir(vir, zdaj)
            if v.zaprt_do > zdaj:
                return
            teza = TEZE.get(vrsta, 10)
            if v.zaupan_do > zdaj or povezan:
                teza //= 2
            v.dogodki.append((zdaj, teza, vrsta))
            obvestila = self._oceni(vir, v, zdaj)
        self._obvesti(obvestila)

    def zaupaj(self, vir: str) -> None:
        """Vir se je izkazal kot clan kroga (veljaven podpis, vstopnica ali zeton)."""
        if not vir or self.izvzet(vir):
            return
        with self._zaklep:
            zdaj = self.ura()
            v = self._vir(vir, zdaj)
            v.zaupan_do = zdaj + ZAUPANJE_S
            # Povezave, ki jih je odprl pred prijavo, niso bile poplava.
            v.dogodki = deque((d for d in v.dogodki if d[2] != "povezava"), maxlen=NAJVEC_DOGODKOV)

    # ------------------------------------------------------------------ stanje

    def zaprt(self, vir: str) -> bool:
        with self._zaklep:
            v = self._viri.get(vir)
            return v is not None and v.zaprt_do > self.ura()

    def stanje(self) -> dict:
        """Za vmesnik in dnevnik: zaprti viri (naslov, se sekund, razlog, katera zapora po vrsti), stevilo zavrnjenih."""
        with self._zaklep:
            zdaj = self.ura()
            zaprti = [{"vir": ime, "se_s": int(v.zaprt_do - zdaj), "razlog": v.razlog, "zapora": v.ponovitev,
                       "sestava": dict(v.sestava)}
                      for ime, v in self._viri.items() if v.zaprt_do > zdaj]
            return {"zaprti": zaprti, "zavrnjenih": self._zavrnjenih,
                    "napad": zdaj - self._napad_javljen < NAPAD_OKNO_S}

    def sprosti(self, vir: str) -> bool:
        """Uporabnik vir sprosti sam (npr. svojo napravo, ki je zgresila kodo)."""
        with self._zaklep:
            v = self._viri.get(vir)
            if v is None or v.zaprt_do <= self.ura():
                return False
            v.zaprt_do = 0.0
            v.ponovitev = 0
            v.dogodki.clear()
            return True

    # ------------------------------------------------------------------ notranje

    def _povezan(self, vir: str) -> bool:
        if self.zaupan is None:
            return False
        try:
            return bool(self.zaupan(vir))
        except Exception:
            return False

    def _vir(self, vir: str, zdaj: float) -> _Vir:
        v = self._viri.get(vir)
        if v is None:
            v = _Vir()
            self._viri[vir] = v
            if len(self._viri) > NAJVEC_VIROV:
                # Najstarejsi vir, ki ni zaprt, izpade; ce so zaprti vsi (poplava z mnogo naslovov), najstarejsi.
                for ime, star in self._viri.items():
                    if star.zaprt_do <= zdaj and star is not v:
                        del self._viri[ime]
                        break
                else:
                    self._viri.popitem(last=False)
        else:
            self._viri.move_to_end(vir)
        return v

    def _oceni(self, vir: str, v: _Vir, zdaj: float) -> list:
        while v.dogodki and v.dogodki[0][0] <= zdaj - OKNO_S:
            v.dogodki.popleft()
        vsota = sum(d[1] for d in v.dogodki)
        if vsota < OPOZORILO_PRAG:
            return []
        teze: Dict[str, int] = {}
        for _, teza, vrsta in v.dogodki:
            teze[vrsta] = teze.get(vrsta, 0) + teza
        if vsota < PRAG:
            if zdaj - v.opozorjen < OPOZORILO_VSAKIH_S:
                return []
            v.opozorjen = zdaj
            return [("opozorilo", vir, vsota, teze)]
        # Razlog = vrsta z najvecjo skupno tezo (kaj je vir v resnici pocel).
        v.razlog = max(teze, key=lambda k: teze[k])
        v.sestava = teze
        if zdaj - v.zadnja_zapora > POZABI_PONOVITVE_S:
            v.ponovitev = 0
        trajanje = min(NAJDALJSA_ZAPORA_S, ZAPORA_S * (2 ** v.ponovitev))
        v.ponovitev += 1
        v.zadnja_zapora = zdaj
        v.zaprt_do = zdaj + trajanje
        v.dogodki.clear()
        self._zapore.append((zdaj, vir))
        obvestila = [("zapora", vir, trajanje, v.razlog)]
        nedavni = sorted({ime for kdaj, ime in self._zapore if kdaj > zdaj - NAPAD_OKNO_S})
        if (len(nedavni) >= NAPAD_VIROV or v.ponovitev >= NAPAD_PONOVITEV) and zdaj - self._napad_javljen >= NAPAD_OKNO_S:
            self._napad_javljen = zdaj
            obvestila.append(("napad", nedavni))
        return obvestila

    def _obvesti(self, obvestila: list) -> None:
        for o in obvestila:
            try:
                if o[0] == "zapora" and self.ob_zapori is not None:
                    self.ob_zapori(o[1], o[2], o[3])
                elif o[0] == "napad" and self.ob_napadu is not None:
                    self.ob_napadu(o[1])
                elif o[0] == "opozorilo" and self.ob_opozorilu is not None:
                    self.ob_opozorilu(o[1], o[2], o[3])
            except Exception:
                pass


#: Koda napake v odgovoru sredisca -> vrsta sovraznega dogodka. Cesar tu ni, ni sovrazno: 405 je del prepoznave sredisca
#: (link_hub.je_hub), 409/503 sta stanje, ne napad.
VRSTA_PO_NAPAKI: Dict[str, str] = {
    "ni_poti": "tipanje", "samo_krajevno": "tipanje", "ni_nadgradnje": "tipanje",
    "manjka_device_id": "tipanje", "manjka_pair_id": "tipanje", "manjka_pb": "tipanje", "manjka_cb": "tipanje",
    "naprava_ni_seznanjena": "brez_zaupanja", "ni_v_krogu": "brez_zaupanja", "naprava_ni_v_krogu": "brez_zaupanja",
    "ni_vstopnice": "brez_zaupanja", "ni_sorodnik": "brez_zaupanja",
    "qr_ne_obstaja": "brez_zaupanja", "prijava_ne_obstaja": "brez_zaupanja",
    "napacna_koda": "seznanitev", "prevec_poskusov": "seznanitev", "prevec_prijav": "seznanitev",
    "neveljavna_tocka": "seznanitev",
    # Varovalka je povezovanje s kodo zaprla: kdor vseeno sprasuje, tipa (uporabnikova nova naprava vprasa enkrat).
    "seznanitev_zaprta": "tipanje",
}


def vrsta_napake(koda_http: int, oznaka: str) -> str:
    """Vrsta sovraznega dogodka za odgovor z napako ('' = ni sovrazno)."""
    if koda_http < 400:
        return ""
    return VRSTA_PO_NAPAKI.get(oznaka or "", "")
