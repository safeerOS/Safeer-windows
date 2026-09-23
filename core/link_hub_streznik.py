"""Safeer Hub na racunalniku: da televizor ni vec pogoj, da se naprave vidijo.

Doslej je bil racunalnik v Safeer Linku samo odjemalec - `cast.register` je znal poslati, nikoli
obravnavati. Zato je ugasnjen televizor pomenil, da telefon in tablica izgubita racunalnik, ceprav
je ta ves cas prizgan. Tu je druga stran: isti protokol, kot ga govori HubUsmerjevalnik na
televizorju, da odjemalcev ni treba spreminjati.

Kaj ta Hub zna in cesa namenoma ne:

  * **zna** prijavo naprav iz kroga zaupanja (podpis kljuca, brez kode), seznam naprav,
    posredovanje sporocil (cast., share., control., sync.) in stanje;
  * **zna** seznanitev nove naprave s 6-mestno kodo (SPAKE2, isti postopek in iste napake kot
    HubUsmerjevalnik). Kodo pokazejo televizor in druge naprave z zaslonom v Linku (sporocilo
    `pair.code`) ter obvestilo na racunalniku. Koda po omrezju do nove naprave ne potuje nikoli;
    po NAJVEC_POSKUSOV napakah prijava pade. Nova naprava z zetonom vpise svoj kljuc v krog
    (`/cast/trust/enroll`), od tedaj se prijavlja s podpisom kot vse druge.

Zaupanje: Hub ima isto potrdilo TLS kot Controlov streznik datotek, torej **isti kljuc**, ki je
v krogu zaupanja. Naprava zato ta Hub prepozna po kljucu v potrdilu in se prijavi s podpisom,
brez nove kode - tocno tako, kot bi se na drugem televizorju.

Meje so v zasnovi, ne v zaupanju v naprave: najvec naprav, najvecje sporocilo, izhodna vrsta na
povezavo in izmet naprave, ki ne bere (glej core/link_ws.py).
"""

from __future__ import annotations

import http.server
import json
import ssl
import threading
import time
from typing import Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from core import link_krog, link_ws

#: Vrata Huba. Najprej privzeta (naprave jih poznajo tudi brez mDNS), sicer katerakoli prosta.
PRIVZETA_VRATA = 8990
POT_WS = "/cast/ws"

NAJVEC_NAPRAV = 32
NAJVEC_IMENA = 64
#: Izziv za podpis velja kratko in samo enkrat.
IZZIV_VELJA_S = 60.0
NAJVEC_IZZIVOV = 64
#: Vstopnica je enkratna in kratkoziva: iz nje nastane ena povezava WebSocket.
VSTOPNICA_VELJA_S = 60.0
NAJVEC_VSTOPNIC = 64
#: Protokol, ki ga govorimo (isto kot HubUsmerjevalnik).
RAZLICICA_PROTOKOLA = "1"
IDENTITETA_HUBA = "safeer-link-hub"
#: Seznanitev s kodo (kot HubUsmerjevalnik): koda velja 5 minut, najvec 5 napak, najvec 8 cakajocih.
PIN_VELJA_S = 300.0
NAJVEC_POSKUSOV = 5
NAJVEC_CAKAJOCIH = 8
#: Zeton iz seznanitve je samo za prvo prijavo in vpis kljuca v krog; potem naprava pride s podpisom.
ZETON_VELJA_S = 86400.0
NAJVEC_ZETONOV = 32
NACIN_SPAKE2 = "spake2"


def _zdaj() -> float:
    return time.time()


def _json(telo: dict) -> bytes:
    return json.dumps(telo, ensure_ascii=False).encode("utf-8")


class Naprava:
    """Ena povezana naprava, kakor jo vidi Hub."""

    def __init__(self, id_naprave: str, ime: str, vloga: str, zmoznosti: List[str], naslov: str) -> None:
        self.id = id_naprave
        self.ime = ime
        self.vloga = vloga
        self.zmoznosti = zmoznosti
        self.naslov = naslov
        self.zadnjic = _zdaj()
        self.povezava: Optional[link_ws.Povezava] = None
        # Protocol v1
        self.protokol = ""
        self.platforma = ""
        self.vrsta = ""
        self.razlicica = ""
        self.prioriteta = 0
        self.aplikacije: dict = {}

    def json(self) -> dict:
        zapis = {
            "id": self.id,
            "name": self.ime,
            "role": self.vloga,
            "capabilities": list(self.zmoznosti),
            "ip": self.naslov,
            "port": None,
            "last_seen": self.zadnjic,
        }
        if self.protokol:
            zapis["protocol"] = self.protokol
        if self.platforma:
            zapis["platform"] = self.platforma
        if self.vrsta:
            zapis["kind"] = self.vrsta
        if self.razlicica:
            zapis["version"] = self.razlicica
        if self.prioriteta:
            zapis["priority"] = self.prioriteta
        if self.aplikacije:
            zapis["apps"] = self.aplikacije
        return zapis


class Hub:
    """Register naprav in usmerjanje sporocil. Brez omrezja - to je HubStreznik.

    Loceno zato, ker je prav tu vsa logika, ki mora biti pravilna: kdo sme noter, kam gre
    sporocilo in kaj dobi posiljatelj nazaj. Tako je preizkusljiva brez vticnikov in TLS.
    """

    def __init__(self, odtis: str = "", nas_id: str = "", ura: Callable[[], float] = _zdaj,
                 pot_zetonov: str = "") -> None:
        self.odtis = (odtis or "").lower()
        self.nas_id = nas_id
        self.ura = ura
        self._zaklep = threading.RLock()
        self._naprave: Dict[str, Naprava] = {}
        self._izzivi: Dict[str, tuple] = {}        # nonce -> (device_id, cas)
        self._vstopnice: Dict[str, tuple] = {}     # vstopnica -> (device_id, cas)
        self._prijave: Dict[str, dict] = {}        # pair_id -> seznanitev s kodo
        self._pridruzitve: Dict[str, dict] = {}    # qr_id -> pridruzitev s QR kodo
        #: "ip:vrata", kot ga naprava potrebuje v QR kodi (nastavi HubStreznik).
        self.naslov_za_qr = ""
        self._zetoni: Dict[str, tuple] = {}        # zeton -> (device_id, ime, cas)
        #: Zetoni seznanitve prezivijo ponovni zagon (naprava, ki kljuca se ni vpisala, ne ostane zunaj).
        self._pot_zetonov = pot_zetonov
        self._nalozi_zetone()
        self.ob_spremembi: Optional[Callable[[], None]] = None
        #: Nova naprava caka na kodo: (ime naprave, koda) - racunalnik pokaze obvestilo.
        self.ob_kodi: Optional[Callable[[str, str], None]] = None

    # ------------------------------------------------------------------ prijava s podpisom

    def izziv(self, device_id: str) -> Optional[dict]:
        """Enkratni izziv za napravo, ki se hoce prijaviti s podpisom kljuca."""
        device_id = (device_id or "").strip()[:NAJVEC_IMENA]
        if not device_id:
            return None
        nonce = link_ws.nakljucni(18)
        with self._zaklep:
            self._pocisti_izzive()
            if len(self._izzivi) >= NAJVEC_IZZIVOV:
                return None
            self._izzivi[nonce] = (device_id, self.ura())
        return {"nonce": nonce, "fp": self.odtis, "hub_id": IDENTITETA_HUBA}

    def _pocisti_izzive(self) -> None:
        meja = self.ura() - IZZIV_VELJA_S
        for n in [n for n, (_, ko) in self._izzivi.items() if ko < meja]:
            self._izzivi.pop(n, None)

    def vstopnica_s_podpisom(self, device_id: str, nonce: str, podpis: str,
                             ime: str = "", platforma: str = "") -> Optional[dict]:
        """Preveri podpis proti kljucu iz kroga zaupanja in izda enkratno vstopnico.

        Izziv je enkraten: porabimo ga, ne glede na izid. Sicer bi lahko kdo na istem izzivu
        poskusal podpise, dokler eden ne bi ustrezal.
        """
        device_id = (device_id or "").strip()[:NAJVEC_IMENA]
        with self._zaklep:
            self._pocisti_izzive()
            vnos = self._izzivi.pop((nonce or "").strip(), None)
        if not vnos or not device_id or vnos[0] != device_id:
            return None
        clan = None
        try:
            clan = link_krog.krog().clan_za_id(device_id)
        except Exception:
            clan = None
        if not clan or not clan.get("kljuc"):
            return None
        podatki = link_krog.podatki_za_podpis(self.odtis, nonce, device_id)
        if not link_krog.preveri_podpis(str(clan["kljuc"]), podatki, podpis or ""):
            return None
        odgovor = {"ticket": self._nova_vstopnica(device_id), "hub_id": IDENTITETA_HUBA, "fp": self.odtis}
        try:
            odgovor["ring"] = link_krog.krog().json()
        except Exception:
            pass
        return odgovor

    def _pocisti_vstopnice(self) -> None:
        meja = self.ura() - VSTOPNICA_VELJA_S
        for v in [v for v, (_, ko) in self._vstopnice.items() if ko < meja]:
            self._vstopnice.pop(v, None)

    def porabi_vstopnico(self, vstopnica: str) -> Optional[str]:
        """Id naprave, ki ji vstopnica pripada. Velja natanko enkrat."""
        with self._zaklep:
            self._pocisti_vstopnice()
            vnos = self._vstopnice.pop((vstopnica or "").strip(), None)
        return vnos[0] if vnos else None

    def _nova_vstopnica(self, device_id: str) -> str:
        vstopnica = link_ws.nakljucni(24)
        with self._zaklep:
            self._pocisti_vstopnice()
            if len(self._vstopnice) >= NAJVEC_VSTOPNIC:
                najstarejsa = min(self._vstopnice, key=lambda k: self._vstopnice[k][1])
                self._vstopnice.pop(najstarejsa, None)
            self._vstopnice[vstopnica] = (device_id, self.ura())
        return vstopnica

    # ------------------------------------------------------------------ seznanitev s kodo

    def _nalozi_zetone(self) -> None:
        if not self._pot_zetonov:
            return
        try:
            with open(self._pot_zetonov, encoding="utf-8") as d:
                for z, v in (json.load(d) or {}).items():
                    if isinstance(v, list) and len(v) == 3:
                        self._zetoni[str(z)] = (str(v[0]), str(v[1]), float(v[2]))
        except Exception:
            pass

    def _shrani_zetone(self) -> None:
        """Klice se pod kljucavnico. Datoteka je samo za uporabnika (0600)."""
        if not self._pot_zetonov:
            return
        import os
        try:
            os.makedirs(os.path.dirname(self._pot_zetonov), exist_ok=True)
            zacasna = self._pot_zetonov + ".tmp"
            with open(os.open(zacasna, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as d:
                json.dump({z: list(v) for z, v in self._zetoni.items()}, d)
            os.replace(zacasna, self._pot_zetonov)
        except Exception:
            pass

    def _pocisti_prijave(self) -> None:
        meja = self.ura() - PIN_VELJA_S
        for k in [k for k, p in self._prijave.items() if p["nastala"] < meja]:
            self._prijave.pop(k, None)
        meja = self.ura() - ZETON_VELJA_S
        for z in [z for z, (_, _i, ko) in self._zetoni.items() if ko < meja]:
            self._zetoni.pop(z, None)

    def _objavi_kodo(self, tip: str, tovor: dict) -> None:
        """Kodo pokazejo naprave v Linku (televizor, tablica, racunalnik), ne nova naprava."""
        besedilo = json.dumps({"id": str(int(self.ura() * 1000)), "type": tip, "payload": tovor}, ensure_ascii=False)
        for n in self.povezane():
            if n.povezava is not None:
                try:
                    n.povezava.poslji(besedilo)
                except Exception:
                    pass

    def zacni_seznanitev(self, device_id: str, ime: str, naslov: str = "") -> Optional[dict]:
        """Nova naprava se zeli pridruziti. Kode ne vrnemo njej - pokazejo jo naprave v Linku."""
        device_id = (device_id or "").strip()[:NAJVEC_IMENA]
        ime = (ime or "").strip()[:NAJVEC_IMENA] or device_id
        if not device_id:
            return None
        import secrets
        with self._zaklep:
            self._pocisti_prijave()
            for k in [k for k, p in self._prijave.items() if p["device_id"] == device_id]:
                self._prijave.pop(k, None)
            if len(self._prijave) >= NAJVEC_CAKAJOCIH:
                return None
            pair_id = link_ws.nakljucni(8)
            koda = str(100000 + secrets.randbelow(900000))
            self._prijave[pair_id] = {"device_id": device_id, "ime": ime, "pin": koda, "naslov": naslov,
                                      "nastala": self.ura(), "krogov": 0, "poskusov": 0, "spake": None}
        self._objavi_kodo("pair.code", {"pair_id": pair_id, "name": ime, "code": koda,
                                        "expires_in_seconds": int(PIN_VELJA_S)})
        if self.ob_kodi is not None:
            try:
                self.ob_kodi(ime, koda)
            except Exception:
                pass
        return {"pair_id": pair_id, "nacin": NACIN_SPAKE2, "hub_id": IDENTITETA_HUBA, "fp": self.odtis,
                "expires_in_seconds": int(PIN_VELJA_S)}

    def _koncaj_prijavo(self, pair_id: str) -> None:
        """Klice se pod kljucavnico; kodo skrijejo vse naprave."""
        if self._prijave.pop(pair_id, None) is not None:
            threading.Thread(target=self._objavi_kodo, args=("pair.done", {"pair_id": pair_id}), daemon=True).start()

    def preklici_seznanitev(self, pair_id: str, device_id: str) -> bool:
        with self._zaklep:
            p = self._prijave.get(pair_id)
            if not p or p["device_id"] != device_id:
                return False
            self._koncaj_prijavo(pair_id)
        return True

    def zavrni_seznanitev(self, pair_id: str) -> bool:
        """Uporabnik je na napravi v Linku pritisnil Zavrni."""
        with self._zaklep:
            if pair_id not in self._prijave:
                return False
            self._koncaj_prijavo(pair_id)
        return True

    def spake_korak1(self, pair_id: str, device_id: str, pb: bytes) -> tuple:
        """(pa, ca, napaka). Kot HubUsmerjevalnik.spakeKorak1: sol je pair_id, AAD odtis potrdila."""
        from core.spake2 import Spake2
        with self._zaklep:
            self._pocisti_prijave()
            p = self._prijave.get(pair_id)
            if not p or p["device_id"] != device_id:
                return None, None, "prijava_ne_obstaja"
            p["krogov"] += 1
            if p["krogov"] > NAJVEC_POSKUSOV:
                self._koncaj_prijavo(pair_id)
                return None, None, "prevec_poskusov"
            try:
                s = Spake2.streznik(p["pin"], IDENTITETA_HUBA, device_id, self.odtis.encode("utf-8"),
                                    pair_id.encode("utf-8"))
                _, ca = s.zakljuci(pb)
            except Exception:
                p["spake"] = None
                return None, None, "neveljavna_tocka"
            p["spake"] = s
            return s.sporocilo(), ca, None

    def spake_korak2(self, pair_id: str, device_id: str, cb: bytes) -> tuple:
        """(zeton, napaka). Ujemanje potrditve pomeni isto kodo in isto potrdilo TLS."""
        with self._zaklep:
            self._pocisti_prijave()
            p = self._prijave.get(pair_id)
            if not p or p["device_id"] != device_id:
                return None, "prijava_ne_obstaja"
            s, p["spake"] = p["spake"], None
            if s is None:
                return None, "manjka_korak"
            if not s.preveri(cb):
                p["poskusov"] += 1
                if p["poskusov"] >= NAJVEC_POSKUSOV:
                    self._koncaj_prijavo(pair_id)
                    return None, "prevec_poskusov"
                return None, "napacna_koda"
            if len(self._zetoni) >= NAJVEC_ZETONOV:
                najstarejsi = min(self._zetoni, key=lambda k: self._zetoni[k][2])
                self._zetoni.pop(najstarejsi, None)
            zeton = "saf_pc_" + link_ws.nakljucni(24)
            self._zetoni[zeton] = (device_id, p["ime"], self.ura())
            self._shrani_zetone()
            self._koncaj_prijavo(pair_id)
            return zeton, None

    # ------------------------------------------------------------------ pridruzitev s QR kodo

    def ustvari_pridruzitev(self) -> tuple:
        """(qr_id, skrivnost). Hub hrani samo SHA-256 skrivnosti - iz njega je ne more izdati."""
        import hashlib
        with self._zaklep:
            self._pocisti_pridruzitve()
            while len(self._pridruzitve) >= NAJVEC_CAKAJOCIH:
                self._pridruzitve.pop(next(iter(self._pridruzitve)), None)
            qr_id = link_ws.nakljucni(12)
            skrivnost = link_ws.nakljucni(16)
            self._pridruzitve[qr_id] = {"odtis": hashlib.sha256(skrivnost.encode()).hexdigest(),
                                        "nastala": self.ura(), "poskusov": 0}
        return qr_id, skrivnost

    def _pocisti_pridruzitve(self) -> None:
        meja = self.ura() - PIN_VELJA_S
        for k in [k for k, p in self._pridruzitve.items() if p["nastala"] < meja]:
            self._pridruzitve.pop(k, None)

    def preklici_pridruzitev(self, qr_id: str) -> bool:
        with self._zaklep:
            return self._pridruzitve.pop((qr_id or "").strip(), None) is not None

    def pridruzi(self, qr_id: str, skrivnost: str, device_id: str, ime: str) -> tuple:
        """Naprava s skrivnostjo iz QR: (zeton, napaka). Skrivnost velja enkrat, ugibanje je omejeno."""
        import hashlib
        import hmac
        device_id = (device_id or "").strip()[:NAJVEC_IMENA]
        if not device_id:
            return None, "manjka_device_id"
        with self._zaklep:
            self._pocisti_pridruzitve()
            p = self._pridruzitve.get((qr_id or "").strip())
            if not p:
                return None, "qr_ne_obstaja"
            if not hmac.compare_digest(hashlib.sha256((skrivnost or "").encode()).hexdigest(), p["odtis"]):
                p["poskusov"] += 1
                if p["poskusov"] >= NAJVEC_POSKUSOV:
                    self._pridruzitve.pop(qr_id, None)
                    return None, "prevec_poskusov"
                return None, "qr_ne_obstaja"
            self._pridruzitve.pop(qr_id, None)
            zeton = "saf_pc_" + link_ws.nakljucni(24)
            self._zetoni[zeton] = (device_id, (ime or device_id).strip()[:NAJVEC_IMENA], self.ura())
            self._shrani_zetone()
        return zeton, None

    def naprava_zetona(self, zeton: str) -> Optional[tuple]:
        """(device_id, ime) za zeton iz seznanitve, ali None."""
        import hmac
        zeton = (zeton or "").strip()
        if not zeton:
            return None
        with self._zaklep:
            self._pocisti_prijave()
            for z, (device_id, ime, _) in self._zetoni.items():
                if hmac.compare_digest(z, zeton):
                    return device_id, ime
        return None

    def vstopnica_z_zetonom(self, zeton: str) -> Optional[dict]:
        n = self.naprava_zetona(zeton)
        if n is None:
            return None
        return {"ticket": self._nova_vstopnica(n[0]), "hub_id": IDENTITETA_HUBA, "fp": self.odtis}

    def vpisi_v_krog(self, zeton: str, kljuc: str, ime: str, platforma: str) -> tuple:
        """(odgovor, napaka). Naprava z zetonom vpise svoj javni kljuc; krog dobijo vse naprave."""
        n = self.naprava_zetona(zeton)
        if n is None:
            return None, "naprava_ni_seznanjena"
        device_id, ime_prijave = n
        ime = ((ime or "").strip() or ime_prijave)[:NAJVEC_IMENA]
        k = link_krog.krog()
        if not k.dodaj(device_id, (kljuc or "").strip(), ime, (platforma or "")[:16], self.nas_id or IDENTITETA_HUBA) \
                and not (k.clan(device_id) or {}).get("kljuc") == (kljuc or "").strip():
            return None, "neveljaven_kljuc"
        krog = k.json()
        besedilo = json.dumps({"type": "trust.update", "payload": krog}, ensure_ascii=False)
        for c in self.povezane():
            if c.povezava is not None:
                try:
                    c.povezava.poslji(besedilo)
                except Exception:
                    pass
        return {"device_id": device_id, "ring": krog}, None

    # ------------------------------------------------------------------ register

    def povezane(self) -> List[Naprava]:
        with self._zaklep:
            return [n for n in self._naprave.values() if n.povezava is not None]

    def stevilo(self) -> int:
        return len(self.povezane())

    def najdi(self, device_id: str) -> Optional[Naprava]:
        with self._zaklep:
            return self._naprave.get(device_id)

    def id_povezave(self, povezava) -> Optional[str]:
        with self._zaklep:
            for i, n in self._naprave.items():
                if n.povezava is povezava:
                    return i
        return None

    @staticmethod
    def naprava_iz_kljuca(device_id: str) -> Optional[str]:
        """Fizicna naprava za id: id iz kljuca (n-<16 hex>) njenega clana v krogu (HubUsmerjevalnik.napravaIzKljuca).

        Brskalnik in Safeer Control na istem racunalniku imata isti kljuc, torej isto napravo; vmesnik ju
        zdruzi. Naprava brez kljuca v krogu je nima.
        """
        try:
            clan = link_krog.krog().clan_za_id(device_id)
            return link_krog.id_iz_kljuca(str(clan["kljuc"])) if clan and clan.get("kljuc") else None
        except Exception:
            return None

    @staticmethod
    def ime_v_krogu(device_id: str) -> Optional[str]:
        """Ime naprave iz kroga zaupanja (skupno vsem hubom), ali None."""
        try:
            k = link_krog.krog()
            clan = k.clan(device_id) or k.clan_za_id(device_id)
            ime = str((clan or {}).get("ime") or "")
            return ime if ime and ime != device_id else None
        except Exception:
            return None

    def seznam_json(self) -> str:
        naprave = []
        for n in self.povezane():
            zapis = n.json()
            naprava = self.naprava_iz_kljuca(n.id)
            if naprava:
                zapis["device"] = naprava
                # Ime naprave s kljucem zivi v krogu (dal ga je uporabnik na katerem koli hubu).
                ime = self.ime_v_krogu(n.id)
                if ime:
                    zapis["own_name"] = n.ime
                    zapis["name"] = ime
            naprave.append(zapis)
        return json.dumps({"type": "cast.devices", "devices": naprave}, ensure_ascii=False)

    def objavi_naprave(self) -> None:
        sporocilo = self.seznam_json()
        for n in self.povezane():
            p = n.povezava
            if p is not None:
                p.poslji(sporocilo)
        if self.ob_spremembi is not None:
            try:
                self.ob_spremembi()
            except Exception:
                pass

    def registriraj(self, povezava, tovor: dict, dovoljeni_id: str) -> tuple:
        """(status, koda_napake). Vstopnica je vezana na en id: druge naprave z njo ni mogoce vpisati."""
        device_id = str(tovor.get("device_id") or "").strip()[:NAJVEC_IMENA]
        if not device_id:
            return "rejected", "manjka_device_id"
        if dovoljeni_id and device_id != dovoljeni_id:
            return "rejected", "vstopnica_ni_za_to_napravo"
        ime = str(tovor.get("name") or device_id).strip()[:NAJVEC_IMENA]
        vloga = str(tovor.get("role") or "receiver")[:16]
        zmoznosti = [str(z)[:24] for z in (tovor.get("capabilities") or [])][:24]
        stara = None
        with self._zaklep:
            obstojeca = self._naprave.get(device_id)
            if obstojeca is not None and obstojeca.povezava is not None and obstojeca.povezava is not povezava:
                # Nova povezava iste naprave zamenja staro; sicer naprava ostane "povezana", a nevidna.
                stara = obstojeca.povezava
                obstojeca.povezava = None
            if obstojeca is None:
                if len([n for n in self._naprave.values() if n.povezava is not None]) >= NAJVEC_NAPRAV:
                    return "rejected", "prevec_naprav"
                obstojeca = Naprava(device_id, ime, vloga, zmoznosti, getattr(povezava, "naslov", ""))
                self._naprave[device_id] = obstojeca
            obstojeca.ime = ime
            obstojeca.vloga = vloga
            obstojeca.zmoznosti = zmoznosti
            obstojeca.naslov = getattr(povezava, "naslov", "")
            obstojeca.zadnjic = self.ura()
            obstojeca.povezava = povezava
            obstojeca.protokol = str(tovor.get("protocol") or "")[:8]
            obstojeca.platforma = str(tovor.get("platform") or "")[:16]
            obstojeca.vrsta = str(tovor.get("kind") or "")[:16]
            obstojeca.razlicica = str(tovor.get("version") or "")[:32]
            try:
                obstojeca.prioriteta = max(0, min(1000, int(tovor.get("priority") or 0)))
            except Exception:
                obstojeca.prioriteta = 0
            if isinstance(tovor.get("apps"), dict):
                obstojeca.aplikacije = tovor["apps"]
        if stara is not None:
            # Zunaj kljucavnice: zapiranje je omrezje in ne sme zadrzati registra.
            try:
                stara.zapri(1000, "nova povezava iste naprave")
            except Exception:
                pass
        return "accepted", ""

    def odklopi(self, povezava) -> None:
        spremenjeno = False
        with self._zaklep:
            for n in self._naprave.values():
                if n.povezava is povezava:
                    n.povezava = None
                    spremenjeno = True
        if spremenjeno:
            self.objavi_naprave()

    # ------------------------------------------------------------------ sporocila

    @staticmethod
    def prostor(tip: str) -> str:
        if not tip or "." not in tip:
            return "cast"
        return tip.split(".", 1)[0]

    def _potrditev(self, id_sporocila: str, prostor: str, status: str, napaka: str = "", koda: str = "") -> str:
        zapis = {"id": str(int(self.ura() * 1000)), "type": prostor + ".ack",
                 "ref_id": id_sporocila, "status": status}
        if napaka:
            zapis["error"] = napaka
        if koda:
            zapis["error_code"] = koda
        return json.dumps(zapis, ensure_ascii=False)

    def obdelaj(self, povezava, surovo: str) -> Optional[str]:
        """Eno sporocilo naprave. Vrne odgovor (potrditev) ali None."""
        try:
            sporocilo = json.loads(surovo)
        except Exception:
            return self._potrditev("", "cast", "rejected", "Sporočila ni mogoče prebrati.", "pokvarjeno")
        if not isinstance(sporocilo, dict):
            return self._potrditev("", "cast", "rejected", "Sporočila ni mogoče prebrati.", "pokvarjeno")
        tip = str(sporocilo.get("type") or "")
        id_sporocila = str(sporocilo.get("id") or "")
        prostor = self.prostor(tip)

        if tip == "cast.register":
            tovor = sporocilo.get("payload")
            tovor = tovor if isinstance(tovor, dict) else {}
            status, koda = self.registriraj(povezava, tovor, getattr(povezava, "podatki", {}).get("id", ""))
            if status == "accepted":
                self.objavi_naprave()
                p = povezava
                try:
                    p.poslji(json.dumps({"type": "trust.update", "payload": link_krog.krog().json()},
                                        ensure_ascii=False))
                except Exception:
                    pass
            return self._potrditev(id_sporocila, "cast", status, "" if status == "accepted" else "Prijava zavrnjena.", koda)

        if tip == "cast.ping":
            return json.dumps({"id": id_sporocila, "type": "cast.pong"}, ensure_ascii=False)

        moj_id = self.id_povezave(povezava)
        if moj_id is None:
            # Vticnica brez prijave (npr. po zamenjavi povezave): odjemalec to prepozna in se vrne.
            return self._potrditev(id_sporocila, prostor, "rejected", "Naprava ni povezana.", "naprava_ni_povezana")

        cilj = str(sporocilo.get("target") or "")
        if cilj and cilj != "all":
            if cilj == moj_id:
                return self._potrditev(id_sporocila, prostor, "rejected", "Ista naprava.", "isti_naprava")
            naprava = self.najdi(cilj)
            if naprava is None or naprava.povezava is None:
                return self._potrditev(id_sporocila, prostor, "rejected", "Naprave ni na Safeer Linku.", "ni_naprave")
            sporocilo["sender"] = moj_id
            naprava.povezava.poslji(json.dumps(sporocilo, ensure_ascii=False))
            self._osvezi(moj_id)
            if tip.endswith(".result") or tip.endswith(".ack"):
                return None          # odgovorov in potrditev Hub ne potrjuje
            return self._potrditev(id_sporocila, prostor, "accepted")

        if tip == "trust.names":
            # Naprava ponudi imena iz svojega kroga; hub vzame samo imena znanih clanov z istim kljucem.
            tovor = sporocilo.get("payload")
            try:
                spremenjeno = link_krog.krog().zdruzi_imena(tovor if isinstance(tovor, dict) else {})
            except Exception:
                spremenjeno = False
            if spremenjeno:
                krog = json.dumps({"type": "trust.update", "payload": link_krog.krog().json()}, ensure_ascii=False)
                for n in self.povezane():
                    if n.povezava is not None:
                        try:
                            n.povezava.poslji(krog)
                        except Exception:
                            pass
                self.objavi_naprave()
            return self._potrditev(id_sporocila, "trust", "accepted")

        if tip == "pair.invite":
            # Naprava v Linku (televizor, tablica) pokaze QR kodo za novo napravo: sredisce ustvari
            # skrivnost, naprava jo samo narise. Tako se lahko nova naprava pridruzi na katerikoli napravi.
            tovor = sporocilo.get("payload") if isinstance(sporocilo.get("payload"), dict) else {}
            self.preklici_pridruzitev(str(tovor.get("preklici") or ""))
            qr_id, skrivnost = self.ustvari_pridruzitev()
            povezava = self.najdi(moj_id)
            if povezava is not None and povezava.povezava is not None:
                povezava.povezava.poslji(json.dumps({"id": str(int(self.ura() * 1000)), "type": "pair.invite.ok",
                                                     "payload": {"qr_id": qr_id, "secret": skrivnost, "fp": self.odtis,
                                                                 "address": self.naslov_za_qr,
                                                                 "expires_in_seconds": int(PIN_VELJA_S)}},
                                                    ensure_ascii=False))
            return self._potrditev(id_sporocila, "pair", "accepted")

        if tip == "pair.invite.cancel":
            tovor = sporocilo.get("payload") if isinstance(sporocilo.get("payload"), dict) else {}
            self.preklici_pridruzitev(str(tovor.get("qr_id") or ""))
            return self._potrditev(id_sporocila, "pair", "accepted")

        if tip == "pair.reject":
            tovor = sporocilo.get("payload")
            self.zavrni_seznanitev(str((tovor if isinstance(tovor, dict) else {}).get("pair_id") or ""))
            return self._potrditev(id_sporocila, "pair", "accepted")

        if tip == "apps.announce":
            tovor = sporocilo.get("payload")
            if isinstance(tovor, dict) and isinstance(tovor.get("apps"), dict):
                with self._zaklep:
                    naprava = self._naprave.get(moj_id)
                    if naprava is not None:
                        naprava.aplikacije = tovor["apps"]
                self.objavi_naprave()
            return self._potrditev(id_sporocila, "apps", "accepted")

        # Brez cilja (ali target=all): vsem drugim.
        sporocilo["sender"] = moj_id
        besedilo = json.dumps(sporocilo, ensure_ascii=False)
        for n in self.povezane():
            if n.id != moj_id and n.povezava is not None:
                n.povezava.poslji(besedilo)
        self._osvezi(moj_id)
        if tip.endswith(".result") or tip.endswith(".ack"):
            return None
        return self._potrditev(id_sporocila, prostor, "accepted")

    def _osvezi(self, device_id: str) -> None:
        with self._zaklep:
            naprava = self._naprave.get(device_id)
            if naprava is not None:
                naprava.zadnjic = self.ura()

    # ------------------------------------------------------------------ stanje

    def zdravje(self) -> dict:
        povezane = self.povezane()
        return {"status": "ok", "protocol": RAZLICICA_PROTOKOLA,
                "receivers": len([n for n in povezane if n.vloga == "receiver"]),
                "senders": len([n for n in povezane if n.vloga != "receiver"]),
                "sync_peers": len([n for n in povezane if "sync" in n.zmoznosti]),
                "sync_categories": []}


# ---------------------------------------------------------------------- omrezje

class _Obravnava(http.server.BaseHTTPRequestHandler):
    """Koncne tocke Huba. Namenoma jih je malo - vse drugo tece po WebSocketu."""

    protocol_version = "HTTP/1.1"
    server_version = "SafeerHub"
    sys_version = ""

    # Dnevnik vticnika bi ob vsaki zahtevi pisal v terminal; Safeer pise sam, kadar je kaj vredno.
    def log_message(self, *_a) -> None:
        pass

    # ------------------------------------------------------------------ pomozno
    @property
    def _hub(self) -> "Hub":
        return self.server.hub          # type: ignore[attr-defined]

    def _je_krajevni(self) -> bool:
        naslov = self.client_address[0] if self.client_address else ""
        return _je_krajevni_naslov(naslov)

    def _odgovori(self, koda: int, telo: dict) -> None:
        podatki = _json(telo)
        self.send_response(koda)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(podatki)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(podatki)
        except Exception:
            pass

    def _napaka(self, koda: int, sporocilo: str, oznaka: str) -> None:
        self._odgovori(koda, {"error": sporocilo, "error_code": oznaka, "detail": sporocilo, "code": oznaka})

    def _telo(self) -> dict:
        try:
            dolzina = int(self.headers.get("Content-Length") or 0)
        except Exception:
            return {}
        if dolzina <= 0 or dolzina > 64 * 1024:
            return {}
        try:
            return json.loads(self.rfile.read(dolzina).decode("utf-8")) or {}
        except Exception:
            return {}

    # ------------------------------------------------------------------ GET
    def do_GET(self) -> None:
        pot = urlparse(self.path).path
        if not self._je_krajevni():
            self._napaka(403, "Safeer Link deluje samo v krajevnem omrežju.", "samo_krajevno")
            return
        if pot == POT_WS:
            self._nadgradi()
            return
        if pot == "/cast/health":
            # Samo stevila, nikoli imena naprav: to je preverba, da tu res tece Safeer Hub.
            self._odgovori(200, self._hub.zdravje())
            return
        if pot in ("/cast/devices", "/cast/trust/ring"):
            # Seznam naprav in krog zaupanja (kljuci, imena, kdo je koga dodal) dobijo samo prijavljene
            # naprave, po WebSocketu (cast.devices, trust.update). Po HTTP ju ta Hub ne daje nikomur:
            # zetonov za HTTP (se) ne izdaja, brez zetona pa ju ne da niti Hub na televizorju.
            self._napaka(401, "Naprava ni seznanjena.", "naprava_ni_seznanjena")
            return
        if pot in ("/cast/ticket", "/cast/pair/start", "/cast/pair/spake", "/cast/pair/finish",
                   "/cast/pair/cancel", "/cast/trust/enroll", "/cast/pair/qr/join"):
            # Pot obstaja, a ne kot GET. Po tem naprava loci Safeer Hub od poljubnega streznika.
            self._napaka(405, "Ta način za to pot ni dovoljen.", "metoda_ni_dovoljena")
            return
        self._napaka(404, "Ni te poti.", "ni_poti")

    # ------------------------------------------------------------------ POST
    def do_POST(self) -> None:
        pot = urlparse(self.path).path
        if not self._je_krajevni():
            self._napaka(403, "Safeer Link deluje samo v krajevnem omrežju.", "samo_krajevno")
            return
        if pot == "/cast/auth/challenge":
            telo = self._telo()
            try:
                clan = link_krog.krog().clan_za_id(str(telo.get("device_id") or "").strip())
            except Exception:
                clan = None
            if not clan:
                # Kot HubUsmerjevalnik: 401 pove napravi, da jo vodimo pod drugim id-jem (alias) ali z zetonom.
                self._napaka(401, "Naprava ni v krogu zaupanja.", "naprava_ni_v_krogu")
                return
            izziv = self._hub.izziv(str(telo.get("device_id") or ""))
            if izziv is None:
                self._napaka(429, "Preveč prijav; poskusite čez nekaj minut.", "prevec_prijav")
                return
            self._odgovori(200, izziv)
            return
        if pot == "/cast/auth/ticket":
            telo = self._telo()
            odgovor = self._hub.vstopnica_s_podpisom(
                str(telo.get("device_id") or ""), str(telo.get("nonce") or ""),
                str(telo.get("signature") or ""), str(telo.get("name") or ""),
                str(telo.get("platform") or ""))
            if odgovor is None:
                # 401 pomeni: te naprave (s tem kljucem) v krogu nimamo. Odjemalec to razume.
                self._napaka(401, "Naprave ni v krogu zaupanja.", "ni_v_krogu")
                return
            self._odgovori(200, odgovor)
            return
        if pot == "/cast/ticket":
            # Samo zeton iz seznanitve na tem hubu (prva prijava nove naprave); sicer podpis.
            odgovor = self._hub.vstopnica_z_zetonom(self.headers.get("X-Safeer-Token") or "")
            if odgovor is None:
                self._napaka(401, "Naprava ni seznanjena.", "naprava_ni_seznanjena")
                return
            self._odgovori(200, odgovor)
            return
        if pot == "/cast/trust/enroll":
            telo = self._telo()
            odgovor, napaka = self._hub.vpisi_v_krog(self.headers.get("X-Safeer-Token") or "", str(telo.get("pubkey") or ""),
                                                   str(telo.get("name") or ""), str(telo.get("platform") or ""))
            if odgovor is None:
                if napaka == "naprava_ni_seznanjena":
                    self._napaka(401, "Naprava ni seznanjena.", napaka)
                else:
                    self._napaka(400, "Manjka ali neveljaven javni ključ.", napaka)
                return
            self._odgovori(200, odgovor)
            return
        if pot == "/cast/pair/qr/join":
            telo = self._telo()
            zeton, napaka = self._hub.pridruzi(str(telo.get("qr_id") or ""), str(telo.get("secret") or ""),
                                               str(telo.get("device_id") or ""), str(telo.get("name") or ""))
            if zeton is None:
                koda = 429 if napaka == "prevec_poskusov" else 400 if napaka == "manjka_device_id" else 404
                self._napaka(koda, "Koda ni veljavna." if koda != 400 else "Manjka device_id.", napaka or "qr_ne_obstaja")
                return
            self._odgovori(200, {"approved": True, "token": zeton, "hub_id": IDENTITETA_HUBA, "fp": self._hub.odtis})
            return
        if pot in ("/cast/pair/start", "/cast/pair/spake", "/cast/pair/finish", "/cast/pair/cancel"):
            self._seznanitev(pot, self._telo())
            return
        self._napaka(404, "Ni te poti.", "ni_poti")

    def _seznanitev(self, pot: str, telo: dict) -> None:
        """Seznanitev s kodo: iste poti, polja in napake kot HubHttp.odgovoriSeznanitev na Androidu."""
        pair_id = str(telo.get("pair_id") or "").strip()
        device_id = str(telo.get("device_id") or "").strip()[:NAJVEC_IMENA]
        if pot == "/cast/pair/start":
            if not device_id:
                self._napaka(400, "Manjka device_id.", "manjka_device_id")
                return
            naslov = self.client_address[0] if self.client_address else ""
            odgovor = self._hub.zacni_seznanitev(device_id, str(telo.get("name") or ""), naslov)
            if odgovor is None:
                self._napaka(429, "Preveč čakajočih prijav; poskusite čez nekaj minut.", "prevec_prijav")
                return
            self._odgovori(200, odgovor)
            return
        if not pair_id or not device_id:
            self._napaka(400, "Manjka pair_id ali device_id.", "manjka_pair_id")
            return
        if pot == "/cast/pair/cancel":
            self._odgovori(200, {"cancelled": self._hub.preklici_seznanitev(pair_id, device_id)})
            return
        polje = "pb" if pot == "/cast/pair/spake" else "cb"
        try:
            podatki = bytes.fromhex(str(telo.get(polje) or "").strip())
        except ValueError:
            podatki = b""
        if not podatki:
            self._napaka(400, "Manjka pair_id, device_id ali %s." % polje, "manjka_" + polje)
            return
        sporocila = {"prevec_poskusov": (429, "Preveč poskusov. Začnite znova."),
                     "prijava_ne_obstaja": (404, "Prijava je potekla. Začnite znova."),
                     "neveljavna_tocka": (400, "Neveljavno sporočilo."),
                     "napacna_koda": (401, "Koda ni pravilna."),
                     "manjka_korak": (409, "Najprej pošljite pb.")}
        if pot == "/cast/pair/spake":
            pa, ca, napaka = self._hub.spake_korak1(pair_id, device_id, podatki)
            if pa is None:
                koda, besedilo = sporocila.get(napaka or "", (409, "Seznanitev ni mogoča."))
                self._napaka(koda, besedilo, napaka or "seznanitev_ni_mogoca")
                return
            self._odgovori(200, {"pa": pa.hex(), "ca": ca.hex()})
            return
        zeton, napaka = self._hub.spake_korak2(pair_id, device_id, podatki)
        if zeton is None:
            koda, besedilo = sporocila.get(napaka or "", (409, "Seznanitev ni mogoča."))
            self._napaka(koda, besedilo, napaka or "seznanitev_ni_mogoca")
            return
        self._odgovori(200, {"approved": True, "token": zeton})

    # ------------------------------------------------------------------ WebSocket
    def _nadgradi(self) -> None:
        glave = {k: v for k, v in self.headers.items()}
        if not link_ws.je_nadgradnja(glave):
            self._napaka(400, "Manjka nadgradnja na WebSocket.", "ni_nadgradnje")
            return
        vstopnica = (parse_qs(urlparse(self.path).query).get("ticket") or [""])[0]
        device_id = self._hub.porabi_vstopnico(vstopnica)
        if not device_id:
            self._napaka(401, "Neveljavna ali potekla vstopnica.", "ni_vstopnice")
            return
        try:
            self.wfile.write(link_ws.odgovor_rokovanja(link_ws.kljuc_iz_glav(glave)))
            self.wfile.flush()
        except Exception:
            return
        self.close_connection = True
        vticnik = self.connection
        try:
            vticnik.settimeout(link_ws.PING_VSAKIH_S)
        except Exception:
            pass
        hub = self._hub
        povezava = link_ws.Povezava(
            vticnik, self.client_address[0] if self.client_address else "",
            ob_sporocilu=lambda p, s: _na_sporocilo(hub, p, s),
            ob_koncu=hub.odklopi)
        # Vstopnica je vezana na en id: prijava z drugim id-jem se zavrne (glej registriraj).
        povezava.podatki["id"] = device_id
        povezava.zanka_branja()


def _na_sporocilo(hub: "Hub", povezava, surovo: str) -> None:
    odgovor = hub.obdelaj(povezava, surovo)
    if odgovor:
        povezava.poslji(odgovor)


def _je_krajevni_naslov(naslov: str) -> bool:
    """Ali je naslov iz domacega omrezja? Hub se ne pogovarja z internetom."""
    if not naslov:
        return False
    if naslov.startswith("::ffff:"):
        naslov = naslov[7:]
    if naslov in ("127.0.0.1", "::1", "localhost"):
        return True
    deli = naslov.split(".")
    if len(deli) == 4 and all(d.isdigit() for d in deli):
        a, b = int(deli[0]), int(deli[1])
        if a == 10:
            return True
        if a == 192 and b == 168:
            return True
        if a == 172 and 16 <= b <= 31:
            return True
        if a == 169 and b == 254:
            return True
        return False
    # IPv6 krajevno omrezje: fe80::/10 (link-local) in fc00::/7 (unique local).
    nizko = naslov.lower()
    return nizko.startswith("fe8") or nizko.startswith("fe9") or nizko.startswith("fea") \
        or nizko.startswith("feb") or nizko.startswith("fc") or nizko.startswith("fd")


def _obvestilo_kode(ime: str, koda: str) -> None:
    """Koda za novo napravo tudi na racunalniku (Link je lahko brez televizorja). Brez notify-send nic."""
    import shutil
    import subprocess
    if not shutil.which("notify-send"):
        return
    try:
        subprocess.Popen(["notify-send", "-a", "Safeer Control", "-i", "safeer-control", "-t", str(int(PIN_VELJA_S * 1000)),
                          "Safeer Link: nova naprava",
                          "%s se želi povezati. Vpiši kodo %s %s" % (ime, koda[:3], koda[3:])],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


class _Streznik(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address) -> None:
        """Naprava, ki prekine povezavo, ni napaka Huba in ne sodi v uporabnikov terminal.

        Privzeto bi socketserver ob vsakem prekinjenem rokovanju TLS izpisal celo sled - ob
        ugasnjeni tablici ali zaprtem pokrovu bi bil dnevnik poln sledi, ki ne pomenijo nicesar.
        """
        return


class HubStreznik:
    """Hub racunalnika na omrezju: TLS, HTTP koncne tocke in WebSocket.

    Potrdilo je isto kot pri Controlovem strezniku datotek, torej isti kljuc, ki je v krogu
    zaupanja - naprava ta Hub prepozna po kljucu v potrdilu in se prijavi s podpisom, brez kode.
    """

    def __init__(self, tls_mapa: Optional[str] = None) -> None:
        self.tls_mapa = tls_mapa
        self.odtis = ""
        self.vrata = 0
        self.hub: Optional[Hub] = None
        self._streznik: Optional[_Streznik] = None
        self._nit: Optional[threading.Thread] = None
        self._zaklep = threading.Lock()

    def tece(self) -> bool:
        return self._streznik is not None

    def zazeni(self) -> bool:
        with self._zaklep:
            if self._streznik is not None:
                return True
            from core import link_datoteke
            if self.tls_mapa:
                kljuc, potrdilo, self.odtis = link_datoteke.zagotovi_potrdilo(self.tls_mapa)
            else:
                kljuc, potrdilo, self.odtis = link_datoteke.zagotovi_potrdilo()
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(potrdilo, kljuc)
            nas_id = ""
            try:
                nas_id = link_krog.id_iz_kljuca(link_krog.javni_kljuc_b64())
            except Exception:
                pass
            import os
            self.hub = Hub(odtis=self.odtis, nas_id=nas_id,
                           pot_zetonov=os.path.join(link_krog._mapa_nastavitev(), "hub-zetoni.json"))
            self.hub.ob_kodi = _obvestilo_kode
            streznik = None
            # Privzeta vrata naprave poznajo tudi brez mDNS; ce so zasedena, vzamemo katerakoli.
            for vrata in (PRIVZETA_VRATA, 0):
                try:
                    streznik = _Streznik(("0.0.0.0", vrata), _Obravnava)
                    break
                except OSError:
                    streznik = None
            if streznik is None:
                return False
            streznik.socket = ctx.wrap_socket(streznik.socket, server_side=True)
            streznik.hub = self.hub          # type: ignore[attr-defined]
            self.vrata = streznik.server_address[1]
            try:
                self.hub.naslov_za_qr = "%s:%d" % (_krajevni_ip(), self.vrata)
            except Exception:
                self.hub.naslov_za_qr = ""

            self._streznik = streznik
            self._nit = threading.Thread(target=streznik.serve_forever, name="safeer-hub", daemon=True)
            self._nit.start()
            return True

    def ustavi(self) -> None:
        with self._zaklep:
            streznik = self._streznik
            self._streznik = None
        if streznik is not None:
            for n in (self.hub.povezane() if self.hub else []):
                if n.povezava is not None:
                    try:
                        n.povezava.zapri(1001, "hub se ustavlja")
                    except Exception:
                        pass
            try:
                streznik.shutdown()
                streznik.server_close()
            except Exception:
                pass
        self.vrata = 0
        self.hub = None


# ---------------------------------------------------------------------- oglas in prevzem

#: Ime storitve mDNS, po kateri naprave iscejo Safeer Hub (isto kot na Androidu).
STORITEV_MDNS = "_safeercast._tcp.local."
#: Prioriteta racunalnika pri izvolitvi huba (IzvolitevHuba.PRIORITETA_LINUX).
PRIORITETA_LINUX = 80


class Oglas:
    """Oglas Huba prek mDNS. Brez zeroconfa mirno ne naredi nicesar - paket ostane brez nove
    obvezne odvisnosti, naprave pa Hub najdejo tudi po privzetem imenu in vratih."""

    def __init__(self) -> None:
        self._zc = None
        self._info = None

    def zacni(self, vrata: int, odtis: str, id_naprave: str, ime: str) -> bool:
        if self._info is not None:
            return True
        try:
            import socket as _s
            from zeroconf import ServiceInfo, Zeroconf   # type: ignore
        except Exception:
            return False
        try:
            lastnosti = {
                b"ws": POT_WS.encode(),
                b"tls": b"1",
                b"fp": (odtis or "").encode(),
                b"name": (ime or "").encode("utf-8")[:63],
                b"id": (id_naprave or "").encode(),
                b"prio": str(PRIORITETA_LINUX).encode(),
            }
            naslov = _s.inet_aton(_krajevni_ip())
            ime_storitve = ("safeer-%s.%s" % ((id_naprave or "pc")[-8:], STORITEV_MDNS))
            info = ServiceInfo(STORITEV_MDNS, ime_storitve, addresses=[naslov], port=vrata,
                               properties=lastnosti, server=_s.gethostname().rstrip(".") + ".local.")
            zc = Zeroconf()
            zc.register_service(info)
            self._zc, self._info = zc, info
            return True
        except Exception:
            self._zc, self._info = None, None
            return False

    def koncaj(self) -> None:
        zc, info = self._zc, self._info
        self._zc, self._info = None, None
        if zc is None:
            return
        try:
            if info is not None:
                zc.unregister_service(info)
        except Exception:
            pass
        try:
            zc.close()
        except Exception:
            pass


def _krajevni_ip() -> str:
    """Nas naslov v domacem omrezju (brez posiljanja cesarkoli)."""
    import socket as _s
    v = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
    try:
        v.connect(("192.168.0.1", 9))     # samo izbira poti, paket ne gre nikamor
        return v.getsockname()[0]
    except Exception:
        try:
            return _s.gethostbyname(_s.gethostname())
        except Exception:
            return "127.0.0.1"
    finally:
        try:
            v.close()
        except Exception:
            pass


def je_pred(a_prio: int, a_id: str, b_prio: int, b_id: str) -> bool:
    """Izvolitev huba, isto pravilo kot IzvolitevHuba.jePred na Androidu: visja prioriteta, pri enaki
    manjsi id. Vsaka naprava tako izracuna istega zmagovalca brez pogovora."""
    if a_id == b_id:
        return False
    if a_prio != b_prio:
        return a_prio > b_prio
    return a_id < b_id


def boljsi_hub(hubi: List[dict], nas_id: str, nas_odtis: str = "", prioriteta: int = PRIORITETA_LINUX,
               clan: Optional[Callable[[str], bool]] = None) -> Optional[dict]:
    """Oglasen hub clana kroga zaupanja, ki je pri izvolitvi pred nami (ali None: gostimo mi).

    Nas lastni oglas (isti id ali odtis) in oglasi zunaj kroga ne stejejo - tuj oglas nima glasu.
    """
    naj = None
    for h in hubi:
        hid = str(h.get("id") or "")
        if not hid or hid == nas_id or (nas_odtis and str(h.get("fp") or "").lower() == nas_odtis.lower()):
            continue
        if clan is not None and not clan(hid):
            continue
        if naj is None or je_pred(int(h.get("prio") or 0), hid, int(naj.get("prio") or 0), str(naj["id"])):
            naj = h
    if naj is not None and je_pred(int(naj.get("prio") or 0), str(naj["id"]), prioriteta, nas_id):
        return naj
    return None


def naj_gostimo(najden_hub: Optional[dict], nas_id: str = "", nas_odtis: str = "") -> bool:
    """Ali naj racunalnik zdaj sam gosti Hub?

    Pravilo je namenoma zadrzano: gostimo **samo, kadar drugega Huba ni**. Televizor, ki tece,
    ostane sredisce kot doslej - nocemo, da bi posodobitev cez noc premaknila sredisce hise.
    Ko televizor ugasne, racunalnik prevzame in telefon ter tablica ga najdeta; ko se televizor
    vrne, se naprave vrnejo k njemu, nas Hub pa se umakne (glej HubGostitelj.preveri).

    Nas lastni Hub seveda ni razlog za umik. Prepoznamo ga po dvojem, ker oglas ne pove vedno
    obojega: po id-ju iz oglasa in po odtisu potrdila. Brez tega bi se racunalnik ugasnil takoj,
    ko bi nasel samega sebe.
    """
    if najden_hub is None:
        return True
    if nas_id and str(najden_hub.get("id") or "") == nas_id:
        return True
    if nas_odtis and str(najden_hub.get("fp") or "").lower() == nas_odtis.lower():
        return True
    return False



def id_za_oglas() -> str:
    """Id, s katerim se Hub racunalnika oglasi prek mDNS.

    Mora biti id, pod katerim je nas kljuc **res v krogu zaupanja**: naprava oglasu ne verjame,
    ampak poisce tega clana v krogu in primerja njegov kljuc s kljucem v nasem potrdilu TLS. Ce bi
    oglasili id, ki ga v krogu ni (npr. svez id iz kljuca, ko je naprava vpisana pod imenom
    `...-control`), nam nihce ne bi zaupal in racunalnik bi gostil Hub, ki bi ostal prazen.
    """
    try:
        znan = link_krog.znan_id_za_nas_kljuc()
        if znan:
            return znan
    except Exception:
        pass
    try:
        return link_krog.id_iz_kljuca(link_krog.javni_kljuc_b64())
    except Exception:
        return ""

class HubGostitelj:
    """Zdruzi Hub, oglas in pravilo »gosti samo, kadar drugega ni«.

    `poisci()` naj vrne isto kot link_hub.poisci_hub_z_odtisom (ali None). Loceno zato, da je
    pravilo preizkusljivo brez omrezja.
    """

    def __init__(self, poisci: Callable[[], Optional[dict]], ime: str = "Safeer Control",
                 streznik: Optional["HubStreznik"] = None, oglas: Optional["Oglas"] = None,
                 hubi: Optional[Callable[[], List[dict]]] = None,
                 clan: Optional[Callable[[str], bool]] = None,
                 nas_id: Optional[Callable[[], str]] = None) -> None:
        self.poisci = poisci
        # Gateway (izvolitev): vsi oglaseni hubi s prioriteto, clanstvo v krogu in nas id za oglas.
        # Brez njih (ali ko mDNS ne vidi nobenega huba) velja staro pravilo »samo, kadar drugega ni«.
        self.hubi = hubi
        self.clan = clan
        self.nas_id_fn = nas_id
        self.ime = ime
        self.streznik = streznik or HubStreznik()
        self.oglas = oglas or Oglas()
        self.nas_id = ""
        self._zaklep = threading.Lock()

    def gostimo(self) -> bool:
        return self.streznik.tece()

    def preveri(self) -> bool:
        """En pregled: ce Huba ni, ga zazenemo; ce se je vrnil boljsi, se umaknemo."""
        try:
            najden = self.poisci()
        except Exception:
            najden = None
        try:
            oglaseni = self.hubi() if self.hubi is not None else []
        except Exception:
            oglaseni = []
        with self._zaklep:
            nas_odtis = self.streznik.odtis if self.streznik.tece() else ""
            if oglaseni:
                # Gateway: racunalnik (80) je boljsi koordinator od televizorja (60), tablice (40) in
                # telefona (20); umaknemo se samo boljsemu clanu kroga (npr. domacemu strezniku, 100).
                nas_id = self.nas_id or (self.nas_id_fn() if self.nas_id_fn is not None else "")
                gostimo = boljsi_hub(oglaseni, nas_id, nas_odtis, clan=self.clan) is None
            else:
                gostimo = naj_gostimo(najden, self.nas_id, nas_odtis)
            if gostimo:
                if self.streznik.tece():
                    return True
                if not self.streznik.zazeni():
                    return False
                self.nas_id = id_za_oglas()
                self.oglas.zacni(self.streznik.vrata, self.streznik.odtis, self.nas_id, self.ime)
                print("[SafeerLink] računalnik gosti Safeer Link (vrata %d)" % self.streznik.vrata)
                return True
            if self.streznik.tece():
                # Drug Hub je spet tu: umaknemo se, da hisa nima dveh sredisc.
                print("[SafeerLink] drug Safeer Link je spet na voljo; računalnik neha gostiti")
                self.oglas.koncaj()
                self.streznik.ustavi()
            return False

    def koncaj(self) -> None:
        with self._zaklep:
            self.oglas.koncaj()
            self.streznik.ustavi()
