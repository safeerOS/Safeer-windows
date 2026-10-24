"""Safeer Link: seznam naprav se po prvem posnetku posilja samo s spremembami (lastnik, 18. 10. 2026).

Do 1.0.126 je sredisce ob vsaki spremembi (prijava, odhod, katalog programov ...) vsem povezanim poslalo CEL seznam, zato
je bil val prijav N naprav O(N^3) bajtov: meritev 18. 10. 2026 (`Hub.obdelaj`, prave prijave) 32 naprav 2,8 MB,
100 naprav 79 MB, 200 naprav 628 MB, 400 naprav 5,2 GB. Za podjetje z veliko napravami to ne gre. Zdaj:

* **Dogovor z zmoznostjo.** Odjemalec, ki zna, v prijavi (`cast.register`) navede ZMOZNOST; sosednje sredisce (Link
  Mesh) jo navede v prijavi in v polju `caps` svojega seznama (`mesh.devices`). Kdor je ne navede (starejsi Safeer na
  racunalniku, Androidu ali Windows), dobi cel seznam kot doslej - mesan krog dela.
* **Posnetek in spremembe.** Kdor zna, dobi najprej posnetek: cel seznam z `epoch` (nakljucna oznaka seznama pri tem
  srediscu) in `ver` (zaporedna stevilka). Potem samo spremembe od `base` do `ver`: dodane naprave (cel zapis),
  spremenjene (samo spremenjena polja: `set`, odstranjena polja `unset`) in odstranjene (`del`, samo id).
* **Vrzel ali dvom pomeni posnetek.** Prejemnik, ki dobi spremembo z `base`, ki ni njegova verzija (ali drug `epoch`),
  ali spremembo, ki se ne sklada z njegovim seznamom (sprememba ali odstranitev naprave, ki je nima; dodajanje naprave,
  ki jo ima), seznam zavrze in zahteva posnetek (`*.sync`). Po ponovni povezavi vedno najprej posnetek.
* **Zdruzevanje.** Spremembe v oknu OKNO_S se zdruzijo v eno sporocilo (prva po mirovanju gre takoj), zato val prijav
  ne poslje sporocila za vsako prijavo. Okno je izbrano z meritvijo (tools/link_val_prijav.py, docs/LINK-MESH.md).

Varnost je ista kot pri celem seznamu: spremembe so razlika istega seznama, ki bi ga prejemnik dobil cel (isti filtri:
samo clani kroga cez mejo sredisca, pomoc drugim napravam, naslov na poti do prejemnika), po isti povezavi TLS. Nic iz
sporocila sprememb ne podeli dostopa - zapisi so isti kot v celem seznamu in prejemnik jim verjame enako malo.

Brez odvisnosti od GTK; isti protokol govori Android (cast/SeznamSprememb.kt).
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from collections import OrderedDict
from typing import Callable, Dict, Iterable, List, Optional, Tuple

#: Zmoznost v prijavi (`capabilities`) in v `caps` seznama soseda: prejemnik zna posnetek + spremembe.
ZMOZNOST = "devdelta1"
#: Okno zdruzevanja sprememb (s). Meritev 18. 10. 2026 (tools/link_val_prijav.py, zanka, pravi TLS): glej docs/LINK-MESH.md.
OKNO_S = 0.25
#: Sporocila. Posnetek je obstojeci `cast.devices` (z `epoch` in `ver`) oz. `mesh.devices` (z `epoch`, `ver`, `caps`).
POSNETEK = "cast.devices"
SPREMEMBE = "cast.devices.delta"
ZAHTEVA = "cast.devices.sync"
MESH_POSNETEK = "mesh.devices"
MESH_SPREMEMBE = "mesh.devices.delta"
MESH_ZAHTEVA = "mesh.devices.sync"
#: Polja, ki se spreminjajo brez pomena za seznam (cas zadnjega stika): ne stejejo kot sprememba, gredo samo v posnetek
#: in z dodano napravo. Sicer bi vsaka objava nosila vse aktivne naprave (spet O(N) na spremembo).
NESTALNA_POLJA = frozenset({"last_seen"})
#: Zrcalo seznama pri prejemniku: najvec toliko bajtov JSON. Posnetek mora iti v en okvir (1 MiB, link_ws); spremembe so
#: majhne, a sredisce bi jih lahko kopicilo brez meje - prek meje prejemnik zrcalo zavrze in zahteva posnetek.
NAJVEC_ZRCALA = 4 * 1024 * 1024
#: Prejemnik posnetek zahteva najvec tako pogosto (ce prejsnja zahteva se ni dobila odgovora).
ZAHTEVA_NAJPREJ_S = 2.0

#: Kljuca v `podatki` povezave (link_ws.Povezava, link_mesh.OdhodnaSosednja): ali zna spremembe in kaj je dobila.
ZNA = "seznam_spremembe"
POSLANO = "seznam_poslano"
PREJETO = "seznam_prejeto"


def nova_epoha() -> str:
    """Oznaka enega zaporedja verzij. Ob ponovnem zagonu sredisca je druga, zato stara verzija nikoli ne velja znova."""
    return secrets.token_hex(8)


def razlika_zapisa(star: dict, nov: dict) -> Optional[Tuple[dict, List[str]]]:
    """(spremenjena polja, odstranjena polja) ali None, ce je zapis enak. Nestalna polja ne stejejo."""
    nastavi = {k: v for k, v in nov.items()
               if k != "id" and k not in NESTALNA_POLJA and (k not in star or star[k] != v)}
    odstrani = [k for k in star if k != "id" and k not in nov and k not in NESTALNA_POLJA]
    if not nastavi and not odstrani:
        return None
    return nastavi, odstrani


def razlika(staro: "OrderedDict[str, dict]", novo: Dict[str, dict], z_id: bool) -> Tuple["OrderedDict[str, dict]", Optional[dict]]:
    """Nov objavljeni seznam in sprememba enega dela (None, ce je enak).

    Objavljeni vrstni red: naprave, ki ostanejo, na svojem mestu, nove na koncu - tako, kot ga sestavi prejemnik iz
    sprememb. Zato je posnetek vedno enak seznamu, ki ga ima prejemnik po spremembah (tudi po vrstnem redu).
    `z_id`: zapisi nosijo "id" (cast.devices); sicer je id samo kljuc (mesh.devices) in ga sprememba doda sama."""
    objavljeno: "OrderedDict[str, dict]" = OrderedDict()
    spremenjene = []
    odstranjene = []
    for i, z in staro.items():
        if i not in novo:
            odstranjene.append(i)
            continue
        r = razlika_zapisa(z, novo[i])
        if r is not None:
            vnos = {"id": i, "set": r[0]}
            if r[1]:
                vnos["unset"] = r[1]
            spremenjene.append(vnos)
        objavljeno[i] = novo[i]
    dodane = []
    for i, z in novo.items():
        if i not in staro:
            objavljeno[i] = z
            dodane.append(z if z_id else dict({"id": i}, **z))
    if not (odstranjene or spremenjene or dodane):
        return objavljeno, None
    d: dict = {}
    if dodane:
        d["add"] = dodane
    if spremenjene:
        d["chg"] = spremenjene
    if odstranjene:
        d["del"] = odstranjene
    return objavljeno, d


def _velikost(zapis: dict) -> int:
    try:
        return len(json.dumps(zapis, ensure_ascii=False, separators=(",", ":")))
    except (TypeError, ValueError):
        return NAJVEC_ZRCALA + 1


class Zrcalo:
    """Prejemnikova kopija seznama (enega ali vec delov) s svojo verzijo. Spremembo sprejme samo, ce se natanko nadaljuje
    na njegovo verzijo in se sklada z njegovim seznamom; sicer pove, da potrebuje posnetek."""

    def __init__(self, deli: Dict[str, bool]) -> None:
        #: ime dela -> ali zapisi nosijo "id" (cast.devices) ali je id samo kljuc (mesh.devices)
        self.z_id = dict(deli)
        self.deli: Dict[str, "OrderedDict[str, dict]"] = {ime: OrderedDict() for ime in deli}
        self._velikosti: Dict[Tuple[str, str], int] = {}
        self.velikost = 0
        self.epoha: Optional[str] = None
        self.ver: Optional[int] = None
        self.velja = False

    def posnetek(self, vsebina: Dict[str, object], epoha=None, ver=None) -> None:
        """Cel seznam. Del je seznam zapisov z "id" (z_id) ali slovar id -> zapis. Verzija velja samo s pravilnimi tipi."""
        self._velikosti = {}
        self.velikost = 0
        for ime, z_id in self.z_id.items():
            del_ = OrderedDict()
            surovo = vsebina.get(ime)
            if z_id:
                for z in surovo if isinstance(surovo, list) else []:
                    if isinstance(z, dict) and isinstance(z.get("id"), str):
                        del_[z["id"]] = z
            else:
                for i, z in (surovo.items() if isinstance(surovo, dict) else []):
                    if isinstance(i, str) and isinstance(z, dict):
                        del_[i] = z
            self.deli[ime] = del_
            for i, z in del_.items():
                v = _velikost(z)
                self._velikosti[(ime, i)] = v
                self.velikost += v
        dobra = isinstance(epoha, str) and 0 < len(epoha) <= 64 and isinstance(ver, int) and not isinstance(ver, bool)
        self.epoha = epoha if dobra else None
        self.ver = ver if dobra else None
        self.velja = True

    def zavrzi(self) -> None:
        for ime in self.deli:
            self.deli[ime] = OrderedDict()
        self._velikosti = {}
        self.velikost = 0
        self.epoha = None
        self.ver = None
        self.velja = False

    def _zapisi(self, ime: str, i: str, zapis: Optional[dict]) -> None:
        stara = self._velikosti.pop((ime, i), 0)
        self.velikost -= stara
        if zapis is None:
            self.deli[ime].pop(i, None)
            return
        self.deli[ime][i] = zapis
        v = _velikost(zapis)
        self._velikosti[(ime, i)] = v
        self.velikost += v

    def _uporabi_del(self, ime: str, d) -> bool:
        if d is None:
            return True
        if not isinstance(d, dict):
            return False
        del_ = self.deli[ime]
        z_id = self.z_id[ime]
        odstrani = d.get("del", [])
        spremeni = d.get("chg", [])
        dodaj = d.get("add", [])
        if not isinstance(odstrani, list) or not isinstance(spremeni, list) or not isinstance(dodaj, list):
            return False
        for i in odstrani:
            if not isinstance(i, str) or i not in del_:
                return False
            self._zapisi(ime, i, None)
        for c in spremeni:
            if not isinstance(c, dict):
                return False
            i = c.get("id")
            nastavi = c.get("set", {})
            brisi = c.get("unset", [])
            if not isinstance(i, str) or i not in del_ or not isinstance(nastavi, dict) or not isinstance(brisi, list):
                return False
            if "id" in nastavi or any(not isinstance(k, str) or k == "id" for k in brisi):
                return False
            zapis = dict(del_[i])
            zapis.update(nastavi)
            for k in brisi:
                zapis.pop(k, None)
            self._zapisi(ime, i, zapis)
        for a in dodaj:
            if not isinstance(a, dict) or not isinstance(a.get("id"), str):
                return False
            i = a["id"]
            if i in del_:
                return False
            self._zapisi(ime, i, dict(a) if z_id else {k: v for k, v in a.items() if k != "id"})
        return True

    def uporabi(self, tovor: dict) -> str:
        """Sprememba (`epoch`, `base`, `ver` in deli). Vrne "ok", "vrzel" (ni nasa verzija) ali "dvom" (se ne sklada,
        prevelika). Pri "dvom" je zrcalo zavrzeno; pri obeh mora prejemnik zahtevati posnetek."""
        if not isinstance(tovor, dict):
            return "dvom"
        ver = tovor.get("ver")
        if (not self.velja or self.epoha is None or tovor.get("epoch") != self.epoha
                or tovor.get("base") != self.ver or not isinstance(ver, int) or isinstance(ver, bool) or ver <= self.ver):
            return "vrzel"
        for ime in self.z_id:
            if not self._uporabi_del(ime, tovor.get(ime)) or self.velikost > NAJVEC_ZRCALA:
                self.zavrzi()
                return "dvom"
        self.ver = ver
        return "ok"

    def seznam(self, ime: str = "devices") -> List[dict]:
        return list(self.deli[ime].values())

    def slovar(self, ime: str) -> Dict[str, dict]:
        return dict(self.deli[ime])


class Prejemnik:
    """Odjemalceva stran za `cast.devices`: iz posnetka in sprememb sestavi cel seznam, kot bi ga dobil od starega
    sredisca. Program naprej dobi vedno navaden `cast.devices` - nic drugega v odjemalcu se ne spremeni."""

    def __init__(self, ura: Callable[[], float] = time.monotonic) -> None:
        self.zrcalo = Zrcalo({"devices": True})
        self._ura = ura
        self._zahtevano: Optional[float] = None

    def sprejmi(self, sporocilo: dict) -> Tuple[Optional[dict], bool]:
        """(sporocilo `cast.devices` za program ali None, ali zahtevati posnetek)."""
        tip = sporocilo.get("type")
        if tip == POSNETEK:
            self.zrcalo.posnetek({"devices": sporocilo.get("devices")}, sporocilo.get("epoch"), sporocilo.get("ver"))
            self._zahtevano = None
            return sporocilo, False         # posnetek gre naprej nespremenjen (tudi od starega sredisca)
        if tip != SPREMEMBE:
            return sporocilo, False
        if self.zrcalo.uporabi(sporocilo) != "ok":
            return None, self._zahtevaj()
        return {"type": POSNETEK, "devices": self.zrcalo.seznam()}, False

    def _zahtevaj(self) -> bool:
        zdaj = self._ura()
        if self._zahtevano is not None and zdaj - self._zahtevano < ZAHTEVA_NAJPREJ_S:
            return False
        self._zahtevano = zdaj
        return True


class Pogled:
    """Kar je sredisce objavilo eni skupini prejemnikov (isti seznam - npr. vsi odjemalci z istega omrezja): posnetek
    v objavljenem vrstnem redu, verzija in zadnja sprememba (od ver-1 do ver)."""

    def __init__(self, deli: Dict[str, bool]) -> None:
        self.z_id = dict(deli)
        self.deli: Dict[str, "OrderedDict[str, dict]"] = {ime: OrderedDict() for ime in deli}
        self.epoha = nova_epoha()
        self.ver = 0
        self.zadnja: Optional[Dict[str, dict]] = None

    def posodobi(self, novo: Dict[str, Dict[str, dict]]) -> bool:
        """Nov seznam skupine; True, ce se je objava spremenila (nova verzija)."""
        spremembe: Dict[str, dict] = {}
        for ime, z_id in self.z_id.items():
            objavljeno, d = razlika(self.deli[ime], novo.get(ime) or {}, z_id)
            self.deli[ime] = objavljeno
            if d:
                spremembe[ime] = d
        if self.ver and not spremembe:
            return False
        self.ver += 1
        self.zadnja = spremembe if self.ver > 1 else None
        return True

    def posnetek(self, ime: str = "devices") -> List[dict]:
        return list(self.deli[ime].values())

    def slovar(self, ime: str) -> Dict[str, dict]:
        return dict(self.deli[ime])


def razposlji(pogled: Pogled, povezave: Iterable, posnetek: Callable[[], str], spremembe: Callable[[], str]) -> int:
    """Vsaki povezavi skupine to, kar potrebuje: nic (ze ima to verzijo), spremembe (zna in ima prejsnjo verzijo) ali
    posnetek. Sporocili se sestavita najvec enkrat za vso skupino. Vrne stevilo poslanih bajtov (za meritve)."""
    besedila: Dict[str, str] = {}
    poslano = 0
    zdaj = (pogled.epoha, pogled.ver)
    prej = (pogled.epoha, pogled.ver - 1)
    for p in povezave:
        podatki = getattr(p, "podatki", None)
        if not isinstance(podatki, dict):
            podatki = {}
        if podatki.get(POSLANO) == zdaj:
            continue
        if podatki.get(ZNA) and pogled.zadnja is not None and podatki.get(POSLANO) == prej:
            vrsta = "s"
            if vrsta not in besedila:
                besedila[vrsta] = spremembe()
        else:
            vrsta = "p"
            if vrsta not in besedila:
                besedila[vrsta] = posnetek()
        # Zapisano PRED posiljanjem: zahteva za posnetek, ki pride kot odgovor na to sporocilo (tudi v isti niti), ga
        # pobrise in ostane pobrisana. Ce posiljanje ne uspe, naslednjic posnetek - prejemnik bi sicer cakal na spremembo,
        # ki je ni dobil.
        podatki[POSLANO] = zdaj
        try:
            if vrsta == "p" and not podatki.get(ZNA) and getattr(p, "NADOMESTI", False):
                # Starejsi prejemnik dobi samo cele sezname: novejsi nadomesti tistega, ki se caka v vrsti (ob valu prijav
                # sicer vrsta prekipi in prejemnik izpade). Pri tistem, ki zna spremembe, ne - te gredo v vrstnem redu.
                try:
                    ok = p.poslji(besedila[vrsta], nadomesti=POSNETEK) is not False
                except TypeError:       # ovoj povezave brez tega argumenta: navadno posiljanje
                    ok = p.poslji(besedila[vrsta]) is not False
            else:
                ok = p.poslji(besedila[vrsta]) is not False
        except Exception:  # noqa: BLE001 - ena povezava ne sme ustaviti objave drugim
            ok = False
        if not ok:
            podatki[POSLANO] = None
        if ok:
            poslano += len(besedila[vrsta].encode("utf-8"))
    return poslano


def _casovnik_niti(zamik: float, klic: Callable[[], None]) -> None:
    t = threading.Timer(max(0.0, zamik), klic)
    t.daemon = True
    t.name = "safeer-link-seznam"
    t.start()


class Dusilec:
    """Zdruzi spremembe v oknu: prva po mirovanju se objavi takoj, vse naslednje v oknu skupaj ob njegovem koncu.

    Objava sama vedno prebere TRENUTNO stanje, zato se nobena sprememba ne izgubi - ce pride med objavo, sprozi naslednjo.
    `okno_s` 0: objava takoj v klicateljevi niti (preizkusi brez casovnikov). Sicer tece v svoji niti, da klicatelj
    (bralna nit naprave) nikoli ne caka na razposiljanje drugim."""

    def __init__(self, izvedi: Callable[[], None], okno_s: float = 0.0, ura: Callable[[], float] = time.monotonic,
                 casovnik: Optional[Callable[[float, Callable[[], None]], None]] = None) -> None:
        self._izvedi = izvedi
        self.okno_s = float(okno_s or 0.0)
        self._ura = ura
        self._casovnik = casovnik or _casovnik_niti
        self._zaklep = threading.Lock()
        self._zadnja: Optional[float] = None
        self._caka = False
        self._ustavljen = False
        self._v_teku = False
        self._ponovi = False

    def sprozi(self) -> None:
        if self.okno_s <= 0:
            self._takoj()
            return
        with self._zaklep:
            if self._ustavljen or self._caka:
                return
            zdaj = self._ura()
            zamik = 0.0 if self._zadnja is None else max(0.0, self._zadnja + self.okno_s - zdaj)
            self._caka = True
        self._casovnik(zamik, self._ob_izteku)

    def _takoj(self) -> None:
        """Objava v klicateljevi niti. Ce se med objavo sprozi nova (prejemnik je takoj odgovoril v isti niti ali druga
        nit), se ne gnezdi: tekoca objava se ponovi, ko konca - spremembe gredo tako vedno v vrstnem redu verzij."""
        with self._zaklep:
            if self._ustavljen:
                return
            if self._v_teku:
                self._ponovi = True
                return
            self._v_teku = True
        try:
            while True:
                with self._zaklep:
                    self._ponovi = False
                self._izvedi()
                with self._zaklep:
                    if not self._ponovi or self._ustavljen:
                        self._v_teku = False
                        return
        except BaseException:
            with self._zaklep:
                self._v_teku = False
            raise

    def _ob_izteku(self) -> None:
        with self._zaklep:
            self._caka = False
            if self._ustavljen:
                return
            self._zadnja = self._ura()
        try:
            self._izvedi()
        except Exception as e:  # noqa: BLE001 - casovnik ne sme pasti; naslednja sprememba sprozi novo objavo
            print("[SafeerLink] objava seznama naprav: %s: %s" % (type(e).__name__, str(e)[:160]), flush=True)

    def ustavi(self) -> None:
        with self._zaklep:
            self._ustavljen = True
