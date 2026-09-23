"""Krog zaupanja Safeer Linka na racunalniku (Safeer Control / brskalnik za Linux).

Isti zapis in ista pravila kot na Androidu (tv-browser-2, cast/KrogZaupanja.kt): vsaka naprava ima svoj
kljuc, krog je seznam javnih kljucev vseh seznanjenih naprav in ga hrani vsaka naprava. Kdorkoli iz
kroga je lahko hub; hub preveri podpis naprave, ne zetona.

Kljuc naprave je kljuc EC P-256, ki ga Control ze dela za svoje TLS potrdilo (core/link_datoteke.py,
`zagotovi_potrdilo`, openssl). Podpisujemo z openssl, zato ni nove odvisnosti.

Zapis kroga (samo objekti, brez seznamov - tako ga bere tudi JsonLahki na Androidu):
  {"v": 1,
   "clani": {"<id>": {"kljuc": "<base64 SPKI DER>", "ime": "...", "platforma": "linux",
                      "dodano": 1758300000.0, "dodal": "<id>"}},
   "umiki": {"<id>": {"umaknjeno": 1758300000.0, "umaknil": "<id>"}}}

Zdruzevanje je deterministicno: unija clanov po id (novejsi zapis zmaga), umik ima prednost pred
vnosom, ki je starejsi od njega; vnos, novejsi od umika, napravo vrne.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import threading
import time
from typing import Dict, Optional


def _mapa_nastavitev() -> str:
    from core import link_hub  # pozno: link_hub uvaza ta modul
    return link_hub.NASTAVITVE_MAPA


def _pot_kroga() -> str:
    return os.path.join(_mapa_nastavitev(), "krog.json")


# ------------------------------------------------------------------ kljuc naprave

def _pot_kljuca() -> str:
    from core import link_datoteke
    kljuc, _potrdilo, _odtis = link_datoteke.zagotovi_potrdilo()
    return kljuc


_javni: Optional[str] = None
_zaklep = threading.Lock()


def javni_kljuc_b64() -> str:
    """Javni kljuc te naprave, base64 zapisa SubjectPublicKeyInfo (DER)."""
    global _javni
    with _zaklep:
        if _javni:
            return _javni
        der = subprocess.run(["openssl", "pkey", "-in", _pot_kljuca(), "-pubout", "-outform", "DER"],
                             check=True, capture_output=True).stdout
        _javni = base64.b64encode(der).decode("ascii")
        return _javni


def podpisi(podatki: bytes) -> str:
    """Podpis SHA256withECDSA (DER), base64 - isto kot HubTls.podpisi na Androidu."""
    podpis = subprocess.run(["openssl", "dgst", "-sha256", "-sign", _pot_kljuca()],
                            input=podatki, check=True, capture_output=True).stdout
    return base64.b64encode(podpis).decode("ascii")


def preveri_podpis(kljuc_b64: str, podatki: bytes, podpis_b64: str) -> bool:
    """Ali je `podpis_b64` res podpis `podatki` s tem javnim kljucem (SHA256withECDSA)?

    Rabi ga hub, ko preverja prijavo naprave iz kroga - doslej je racunalnik znal samo podpisati,
    ker ni bil nikoli hub. Isto orodje kot pri podpisovanju (openssl), zato brez nove odvisnosti.
    Vsaka napaka pomeni False: neveljaven kljuc ali pokvarjen podpis nista izjema, ampak zavrnitev.
    """
    if not kljuc_b64 or not podpis_b64:
        return False
    try:
        der = base64.b64decode(kljuc_b64, validate=True)
        podpis = base64.b64decode(podpis_b64, validate=True)
    except Exception:
        return False
    if not podpis or not _veljaven_kljuc(kljuc_b64):
        return False
    import tempfile
    mapa = tempfile.mkdtemp(prefix="safeer-podpis-")
    try:
        pot_kljuca = os.path.join(mapa, "kljuc.der")
        pot_podpisa = os.path.join(mapa, "podpis.bin")
        with open(pot_kljuca, "wb") as d:
            d.write(der)
        with open(pot_podpisa, "wb") as d:
            d.write(podpis)
        r = subprocess.run(["openssl", "dgst", "-sha256", "-verify", pot_kljuca,
                            "-keyform", "DER", "-signature", pot_podpisa],
                           input=podatki, capture_output=True)
        return r.returncode == 0
    except Exception:
        return False
    finally:
        try:
            import shutil
            shutil.rmtree(mapa, ignore_errors=True)
        except Exception:
            pass


def podatki_clana(device_id: str, kljuc: str, platforma: str, dodano: float, dodal: str) -> bytes:
    """Kar podpise naprava, ki v krog doda drugo napravo (KrogZaupanja.podatkiClana).

    Podpis je vezan na id, kljuc, platformo, cas in podpisnika, zato vnosa ni mogoce ne spremeniti
    ne prestaviti k drugemu clanu. Brez njega bi lahko vsak, ki krog posreduje (npr. rele), vanj
    podtaknil svoj kljuc - zato je podpis pogoj, kadar krog pride od naprave in ne od nasega huba.
    """
    return ("safeer-krog-clan-v1\n%s\n%s\n%s\n%.3f\n%s" % (device_id, kljuc, platforma or "", dodano, dodal or "")).encode("utf-8")


def podatki_umika(device_id: str, umaknjeno: float, umaknil: str) -> bytes:
    """Kar podpise naprava, ki clana umakne (KrogZaupanja.podatkiUmika)."""
    return ("safeer-krog-umik-v1\n%s\n%.3f\n%s" % (device_id, umaknjeno, umaknil or "")).encode("utf-8")


def podatki_za_podpis(odtis_huba: str, nonce: str, device_id: str) -> bytes:
    """Kar naprava podpise ob prijavi: vezano na odtis huba in enkratni izziv (HubUsmerjevalnik.podatkiZaPodpis)."""
    return f"safeer-link-auth\n{(odtis_huba or '').lower()}\n{nonce}\n{device_id}".encode("utf-8")


def id_iz_kljuca(kljuc_b64: str) -> str:
    """Id nove naprave iz javnega kljuca (KrogZaupanja.idIzKljuca): n- + 16 hex SHA-256."""
    return "n-" + hashlib.sha256(base64.b64decode(kljuc_b64)).hexdigest()[:16]


DOLZINA_ID_IZ_KLJUCA = 18


def je_id_iz_kljuca(device_id: str) -> bool:
    """Ali je id izpeljan iz kljuca (`n-<16 hex>`, po zelji s pripono `-control` ...)."""
    if len(device_id) < DOLZINA_ID_IZ_KLJUCA or not device_id.startswith("n-"):
        return False
    jedro = device_id[2:DOLZINA_ID_IZ_KLJUCA]
    if any(z not in "0123456789abcdef" for z in jedro):
        return False
    return len(device_id) == DOLZINA_ID_IZ_KLJUCA or device_id[DOLZINA_ID_IZ_KLJUCA] == "-"


# ------------------------------------------------------------------ krog

def _veljaven_kljuc(b64: str) -> bool:
    try:
        der = base64.b64decode(b64, validate=True)
    except Exception:
        return False
    # SPKI za P-256 (nestisnjena tocka) ima 91 bajtov; dovolimo razumen razpon, ne nesmisla.
    return 60 <= len(der) <= 200 and der[:1] == b"\x30"


class Krog:
    """Krog zaupanja te naprave; ob vsaki spremembi se zapise na disk (0600)."""

    def __init__(self, pot: Optional[str] = None) -> None:
        self.pot = pot
        self.clani: Dict[str, dict] = {}
        self.umiki: Dict[str, dict] = {}
        self._zaklep = threading.RLock()
        if pot:
            try:
                with open(pot, "r", encoding="utf-8") as d:
                    self.zdruzi(json.load(d), shrani=False)
            except Exception:
                pass

    # -- branje

    def _veljaven(self, c: dict) -> bool:
        u = self.umiki.get(c["id"])
        return not (u and u["umaknjeno"] > c["dodano"])

    def clan(self, device_id: str) -> Optional[dict]:
        with self._zaklep:
            c = self.clani.get(device_id)
            return dict(c) if c and self._veljaven(c) else None

    def je_clan(self, device_id: str) -> bool:
        return self.clan(device_id) is not None

    def clan_za_id(self, device_id: str) -> Optional[dict]:
        """Clan za id, tudi ce je id iz kljuca (n-...) in je ta kljuc v krogu pod drugim (starim) id-jem.

        Isto kot KrogZaupanja.clanZaId: id iz kljuca dokazuje isti kljuc, torej isto napravo.
        """
        c = self.clan(device_id)
        if c or not je_id_iz_kljuca(device_id):
            return c
        jedro = device_id[:DOLZINA_ID_IZ_KLJUCA]
        with self._zaklep:
            for i, c in self.clani.items():
                if self._veljaven(c) and id_iz_kljuca(c["kljuc"]) == jedro:
                    return dict(c)
        return None

    def stevilo(self) -> int:
        with self._zaklep:
            return sum(1 for c in self.clani.values() if self._veljaven(c))

    def json(self) -> dict:
        """Zapis kroga; clani in umiki po id, da je isti krog na vsaki napravi tudi isti zapis."""
        with self._zaklep:
            return {
                "v": 1,
                "clani": {i: dict({"kljuc": c["kljuc"], "ime": c["ime"], "platforma": c["platforma"],
                                   "dodano": c["dodano"], "dodal": c["dodal"]},
                                  **({"imenovano": c["imenovano"]} if c.get("imenovano") else {}),
                                  **({"podpis": c["podpis"]} if c.get("podpis") else {}))
                            for i, c in sorted(self.clani.items())},
                "umiki": {i: dict({"umaknjeno": u["umaknjeno"], "umaknil": u["umaknil"]},
                                  **({"podpis": u["podpis"]} if u.get("podpis") else {}))
                          for i, u in sorted(self.umiki.items())},
            }

    # -- pisanje

    def dodaj(self, device_id: str, kljuc: str, ime: str, platforma: str, dodal: str,
              dodano: Optional[float] = None, podpis: str = "") -> bool:
        if not device_id or not _veljaven_kljuc(kljuc):
            return False
        dodano = dodano if dodano is not None else time.time()
        if not podpis and self._smo_mi(dodal):
            # Vnos podpisemo s kljucem te naprave: tako ga druge naprave lahko preverijo tudi takrat,
            # ko krog ne pride od huba, ampak od naprave ali prek releja.
            try:
                podpis = podpisi(podatki_clana(device_id, kljuc, platforma, dodano, dodal))
            except Exception:
                podpis = ""
        vnos = {"kljuc": kljuc, "ime": ime, "platforma": platforma, "dodano": dodano, "dodal": dodal}
        if podpis:
            vnos["podpis"] = podpis
        return self.zdruzi({"clani": {device_id: vnos}})

    def _smo_mi(self, device_id: str) -> bool:
        """Ali je ta id nasa naprava (isti kljuc)? Samo zase lahko podpisujemo."""
        if not device_id:
            return False
        try:
            nas = javni_kljuc_b64()
        except Exception:
            return False
        c = self.clani.get(device_id)
        if c and c.get("kljuc") == nas:
            return True
        return id_iz_kljuca(nas) == device_id[:DOLZINA_ID_IZ_KLJUCA]

    def umakni(self, device_id: str, kdo: str, ob: Optional[float] = None) -> bool:
        """Umakne clana (nadgrobnik ostane, da umik preide na vse naprave). Naprava, ki je ni v
        krogu, ne spremeni nicesar - sicer bi vsak tuj id pustil nadgrobnik."""
        if not self.je_clan(device_id):
            return False
        ob = ob if ob is not None else time.time()
        umik = {"umaknjeno": ob, "umaknil": kdo}
        if self._smo_mi(kdo):
            try:
                umik["podpis"] = podpisi(podatki_umika(device_id, ob, kdo))
            except Exception:
                pass
        return self.zdruzi({"umiki": {device_id: umik}})

    def preimenuj(self, device_id: str, ime: str, ob: Optional[float] = None) -> bool:
        """Uporabnik je napravo poimenoval: samo ime in cas imena, dodano ostane (preimenovanje ne obudi umaknjene)."""
        cisto = (ime or "").strip()[:64]
        ob = time.time() if ob is None else ob
        with self._zaklep:
            c = self.clani.get(device_id)
            if (not cisto or not c or not self._veljaven(c) or ob <= c.get("imenovano", 0.0)
                    or (c["ime"] == cisto and c.get("imenovano"))):
                return False
            c["ime"], c["imenovano"] = cisto, ob
            self._shrani()
        return True

    def zdruzi_imena(self, tuj) -> bool:
        """Imena, ki jih ponudi naprava (trust.names): samo ime znanih, neumaknjenih clanov z ISTIM kljucem in
        samo novejse. Nov clan, drug kljuc ali umik po tej poti ne pride (KrogZaupanja.zdruziImena)."""
        if isinstance(tuj, str):
            try:
                tuj = json.loads(tuj)
            except Exception:
                return False
        clani = (tuj or {}).get("clani") if isinstance(tuj, dict) else None
        if not isinstance(clani, dict):
            return False
        meja = time.time() + 86400
        spremenjeno = False
        with self._zaklep:
            for i, z in clani.items():
                c = self.clani.get(i)
                if not isinstance(z, dict) or not c or not self._veljaven(c):
                    continue
                try:
                    ob = float(z.get("imenovano") or 0.0)
                except (TypeError, ValueError):
                    continue
                ime = str(z.get("ime") or "").strip()[:64]
                if str(z.get("kljuc") or "") != c["kljuc"] or not ime or ob <= c.get("imenovano", 0.0) or ob > meja:
                    continue
                c["ime"], c["imenovano"] = ime, ob
                spremenjeno = True
            if spremenjeno:
                self._shrani()
        return spremenjeno

    def _kljuc_clana(self, device_id: str) -> str:
        """Javni kljuc clana (tudi prek id-ja iz kljuca), ali prazno."""
        c = self.clani.get(device_id)
        if not c and je_id_iz_kljuca(device_id):
            jedro = device_id[:DOLZINA_ID_IZ_KLJUCA]
            for _i, d in self.clani.items():
                if id_iz_kljuca(d["kljuc"]) == jedro:
                    c = d
                    break
        return str((c or {}).get("kljuc") or "")

    def zdruzi(self, tuj, shrani: bool = True, preveri_podpise: bool = False) -> bool:
        """Zdruzi tuj krog (dict ali JSON niz). Vrne True, ce se je nas krog spremenil.

        `preveri_podpise` velja za kroge, ki NE pridejo od nasega huba (naprava, rele, internet):
        nov ali spremenjen clan in umik morata biti podpisana s kljucem tistega, ki ju je dodal, in
        ta mora biti ze v nasem krogu. Tako tuja naprava ne more podtakniti svojega kljuca.
        """
        if isinstance(tuj, str):
            try:
                tuj = json.loads(tuj)
            except Exception:
                return False
        if not isinstance(tuj, dict):
            return False
        spremenjeno = False
        with self._zaklep:
            for i, u in (tuj.get("umiki") or {}).items():
                if not isinstance(u, dict):
                    continue
                try:
                    ob = float(u.get("umaknjeno"))
                except (TypeError, ValueError):
                    continue
                umaknil = str(u.get("umaknil") or "")
                podpis = str(u.get("podpis") or "")
                if preveri_podpise and not preveri_podpis(self._kljuc_clana(umaknil), podatki_umika(i, ob, umaknil), podpis):
                    continue
                obstojeci = self.umiki.get(i)
                if obstojeci is None or obstojeci["umaknjeno"] < ob:
                    self.umiki[i] = dict({"umaknjeno": ob, "umaknil": umaknil}, **({"podpis": podpis} if podpis else {}))
                    spremenjeno = True
            for i, c in (tuj.get("clani") or {}).items():
                if not isinstance(c, dict) or not _veljaven_kljuc(str(c.get("kljuc") or "")):
                    continue
                try:
                    dodano = float(c.get("dodano") or 0.0)
                except (TypeError, ValueError):
                    dodano = 0.0
                try:
                    imenovano = float(c.get("imenovano") or 0.0)
                except (TypeError, ValueError):
                    imenovano = 0.0
                nov = {"id": i, "kljuc": str(c["kljuc"]), "ime": str(c.get("ime") or i),
                       "platforma": str(c.get("platforma") or ""), "dodano": dodano,
                       "dodal": str(c.get("dodal") or ""), "imenovano": imenovano}
                if c.get("podpis"):
                    nov["podpis"] = str(c["podpis"])
                obstojeci = self.clani.get(i)
                if preveri_podpise and (obstojeci is None or obstojeci["kljuc"] != nov["kljuc"]):
                    # Nov clan ali drug kljuc: samo s podpisom clana, ki ga je dodal in ga ze poznamo.
                    if not preveri_podpis(self._kljuc_clana(nov["dodal"]),
                                          podatki_clana(i, nov["kljuc"], nov["platforma"], dodano, nov["dodal"]),
                                          str(nov.get("podpis") or "")):
                        continue
                if (obstojeci is None or obstojeci["dodano"] < dodano
                        or (obstojeci["dodano"] == dodano and obstojeci["kljuc"] != nov["kljuc"]
                            and obstojeci["kljuc"] < nov["kljuc"])):
                    # Novejsi vnos iste naprave ne izgubi imena, ki ga je dal uporabnik (KrogZaupanja.zdruzi).
                    if obstojeci is not None and obstojeci["kljuc"] == nov["kljuc"] \
                            and obstojeci.get("imenovano", 0.0) > imenovano:
                        nov["ime"], nov["imenovano"] = obstojeci["ime"], obstojeci["imenovano"]
                    self.clani[i] = nov
                    spremenjeno = True
                elif obstojeci["kljuc"] == nov["kljuc"] and imenovano > obstojeci.get("imenovano", 0.0) and nov["ime"]:
                    obstojeci["ime"], obstojeci["imenovano"] = nov["ime"], imenovano
                    spremenjeno = True
                elif (obstojeci["kljuc"] == nov["kljuc"] and obstojeci["dodano"] == dodano and obstojeci["ime"] != nov["ime"]
                      and not obstojeci.get("imenovano") and not imenovano):
                    # Naprava je sama spremenila svoje ime (uporabnik je ni poimenoval): kot doslej.
                    obstojeci["ime"] = nov["ime"]
                    spremenjeno = True
            for i in list(self.umiki):
                c = self.clani.get(i)
                if c and c["dodano"] > self.umiki[i]["umaknjeno"]:
                    del self.umiki[i]
                    spremenjeno = True
            if spremenjeno and shrani:
                self._shrani()
        return spremenjeno

    def _shrani(self) -> None:
        if not self.pot:
            return
        try:
            os.makedirs(os.path.dirname(self.pot), exist_ok=True)
            zacasna = self.pot + ".tmp"
            with open(zacasna, "w", encoding="utf-8") as d:
                json.dump(self.json(), d, ensure_ascii=False, indent=1)
            os.chmod(zacasna, 0o600)
            os.replace(zacasna, self.pot)
        except Exception:
            pass


_krog: Optional[Krog] = None


def krog() -> Krog:
    global _krog
    with _zaklep:
        if _krog is None:
            _krog = Krog(_pot_kroga())
        return _krog


def sprejmi(tuj) -> bool:
    """Krog, ki ga je poslal hub (trust.update ali odgovor na prijavo)."""
    return krog().zdruzi(tuj)


def je_vpisan(device_id: str) -> bool:
    """Ali je ta naprava v krogu s SVOJIM trenutnim kljucem."""
    c = krog().clan(device_id)
    if not c:
        return False
    try:
        return c["kljuc"] == javni_kljuc_b64()
    except Exception:
        return False


def znan_id_za_nas_kljuc(razen: str = "") -> Optional[str]:
    """Kateri koli id (razen `razen`), pod katerim je nas kljuc ze v krogu (stari id, sorodnik), ali None."""
    try:
        kljuc = javni_kljuc_b64()
    except Exception:
        return None
    k = krog()
    with k._zaklep:
        for i, c in k.clani.items():
            if i != razen and k._veljaven(c) and c["kljuc"] == kljuc:
                return i
    return None


def lahko_s_podpisom(device_id: str) -> bool:
    """Ali se naprava lahko prijavi s podpisom: id je v krogu z nasim kljucem ali pa je nas kljuc v krogu
    pod drugim id-jem (stari id pred prehodom na id iz kljuca) - hub tak podpis sprejme in nov id vpise
    kot alias, seznanitev prezivi."""
    return je_vpisan(device_id) or znan_id_za_nas_kljuc(razen=device_id) is not None
