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
import os
import logging
import re
import socket
import ssl
import sys
import threading
import time
from typing import Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from core import link_hub_deljenje, link_krog, link_obramba, link_tls, link_varovalka, link_ws

#: Vrata Huba. Najprej privzeta (naprave jih poznajo tudi brez mDNS), sicer katerakoli prosta.
PRIVZETA_VRATA = 8990
POT_WS = "/cast/ws"
#: Deljene datoteke prek Huba (tok in prenos tudi prek Global Linka).
POT_DATOTEKE = "/cast/d/"
#: Deljenje med napravami (core/link_hub_deljenje.py): besedilo, oddaja datoteke in njen prevzem.
POT_BESEDILO = "/cast/share/text"
#: Ime, ki ga napravi da uporabnik (zivi v krogu zaupanja, vidijo ga vse naprave).
POT_PREIMENUJ = "/cast/devices/rename"
POT_ODDAJA = "/cast/file"
POT_PREVZEM = "/cast/file/"
#: Toliko neprebranega telesa se preberemo in zavrzemo, da odjemalec dobi odgovor z napako; pri vecjem zapremo.
NAJVEC_ZAVRZENEGA = 64 * 1024 * 1024

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
#: Odgovor napravi, ki zeli zaceti prijavo s kodo, ko jo je varovalka zaprla.
BESEDILO_KODA_ZAPRTA = ("Povezovanje s kodo je začasno zaprto, ker je nekdo ugibal kodo. Na napravi v Safeer Linku "
                        "odpri »Poveži naprave« ali uporabi kodo QR.")
NAJVEC_POSKUSOV = 5
NAJVEC_CAKAJOCIH = 8
#: Zeton iz seznanitve je samo za prvo prijavo in vpis kljuca v krog; potem naprava pride s podpisom.
ZETON_VELJA_S = 86400.0
NAJVEC_ZETONOV = 32
NACIN_SPAKE2 = "spake2"
#: Naprava iz kroga dobi po prijavi s podpisom kratkoziv HTTP zeton (enako kot TV Hub).
SEJA_VELJA_S = 12 * 60 * 60.0
NAJVEC_SEJ = 64


#: Link Mesh (docs/LINK-MESH.md): vsaka naprava gosti svoj Hub, Hubi so sosedje vsak z vsakim.
MESH = "mesh1"
#: Najvec sosednjih Hubov in najvecje sporocilo, ki ga sosed sme poslati za eno napravo.
NAJVEC_SOSEDOV = 16
NAJVEC_MESH_SPOROCILO = 1024 * 1024

#: Safeer Chat: najvec cakajocih sporocil na napravo in koliko casa pocakajo.
KLEPET_NA_NAPRAVO = 100
KLEPET_ZIVLJENJE_S = 7 * 24 * 3600.0


def _zdaj() -> float:
    return time.time()


def _json(telo: dict) -> bytes:
    return json.dumps(telo, ensure_ascii=False).encode("utf-8")


def _gostitelj_naslova(naslov) -> str:
    """Gostitelj iz naslova povezave: goli IP (dohodna povezava) ali wss://gostitelj:vrata/pot (odhodna).
    IPv4 v zapisu IPv6 (::ffff:a.b.c.d) vrne kot IPv4, obmocje vmesnika (%eth0) odreze."""
    naslov = str(naslov or "").strip()
    if "://" in naslov:
        try:
            naslov = urlparse(naslov).hostname or ""
        except Exception:
            return ""
    naslov = naslov.strip("[]").split("%", 1)[0]
    if naslov.lower().startswith("::ffff:") and "." in naslov:
        naslov = naslov[7:]
    return naslov


def _samo_tukaj(naslov) -> bool:
    """Naslov, ki velja samo na racunalniku, kjer je nastal: zanka (127.x, ::1, localhost), IPv6 naslov povezave
    (fe80::/10 - brez vmesnika ga drug racunalnik ne more uporabiti) ali nic."""
    g = _gostitelj_naslova(naslov).lower()
    return not g or g in ("localhost", "::1") or g.startswith("127.") or g[:3] in ("fe8", "fe9", "fea", "feb")


def _naslov_za_druge(naslov, gostitelj: str) -> str:
    """Naslov naprave, kot velja ZUNAJ racunalnika, na katerem tece njen Hub.

    Hub programu, ki se nanj poveze z istega racunalnika (svoj Safeer Control, svoj Safeer OS), pripise 127.0.0.1.
    Ta naslov velja samo tam: kdor ga dobi na drugi napravi, se z njim poveze sam nase (telefon je tako namesto
    zaslona racunalnika klical svoja vrata). Cez mejo Huba zato namesto zanke potuje naslov racunalnika, na katerem
    naprava je (`gostitelj`). Ce ga ne poznamo (sosed prek Global Linka), naslova ni: "" pove resnico,
    127.0.0.1 pa bi kazal na napacno napravo.
    """
    if not _samo_tukaj(naslov):
        return str(naslov)
    return "" if _samo_tukaj(gostitelj) else _gostitelj_naslova(gostitelj)


def _konec_povezave(povezava, kateri: str) -> str:
    """IP enega konca sosednje povezave iz njene vticnice: "getsockname" = nas, "getpeername" = sosedov.
    Dohodna povezava (link_ws.Povezava) ima vticnico sama, odhodna (link_mesh.OdhodnaSosednja) v `ws`."""
    for nosilec in (povezava, getattr(povezava, "ws", None)):
        vticnica = getattr(nosilec, "vticnik", None)
        if vticnica is None:
            continue
        try:
            ime = getattr(vticnica, kateri)()[0]
        except Exception:
            continue
        if isinstance(ime, str):
            return _gostitelj_naslova(ime)
    return ""


def _nas_naslov_proti(povezava) -> str:
    """Nas naslov na poti do soseda (krajevni konec sosednje povezave). "" prek releja - tam je nas konec
    127.0.0.1 - in kadar ga ni mogoce prebrati."""
    nas = _konec_povezave(povezava, "getsockname")
    return "" if _samo_tukaj(nas) else nas


def _gostitelj_soseda(povezava) -> str:
    """Naslov racunalnika, na katerem tece sosednji Hub, kot ga vidimo mi: drugi konec povezave, sicer naslov, ki si
    ga je povezava zapomnila (IP dohodne ali wss://... odhodne). "" prek releja (drugi konec je 127.0.0.1)."""
    sosed = _konec_povezave(povezava, "getpeername") or _gostitelj_naslova(getattr(povezava, "naslov", ""))
    return "" if _samo_tukaj(sosed) else sosed


def _nas_naslov_za_odjemalca(povezava) -> Optional[str]:
    """Za seznam naprav, ki gre enemu odjemalcu: None, ce je odjemalec na TEM racunalniku (ali ga ne poznamo) -
    takemu naslovov ne spreminjamo. Sicer nas naslov na poti do njega; "" pomeni, da ga ni bilo mogoce prebrati."""
    if povezava is None or _samo_tukaj(getattr(povezava, "naslov", "")):
        return None
    return _nas_naslov_proti(povezava)


def naslov_za_povezavo(ip, hub_url) -> str:
    """Odjemalceva stran istega pravila: naslov naprave iz seznama Huba, kot velja pri odjemalcu.

    Hub programu na svojem racunalniku pripise 127.0.0.1. Ce nas Hub tece drugje (`hub_url` ne kaze na ta
    racunalnik), je naprava z zanko na NJEGOVEM racunalniku - starejsi Hubi zanko posljejo tudi odjemalcem od
    drugod. Kadar je Hub tukaj, je zanka res ta racunalnik in ostane."""
    ip = str(ip or "").strip()
    if not ip or not _samo_tukaj(ip):
        return ip
    gostitelj = _gostitelj_naslova(hub_url)
    return ip if _samo_tukaj(gostitelj) else gostitelj


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
        #: Id sosednjega Huba, pri katerem je naprava prijavljena (prazno = pri nas).
        self.sosed = ""
        #: Naprava je pri sosedu nasega soseda: pot gre prek enega vmesnega Huba (relay).
        self.posredno = False

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


class _Namestnik:
    """Povezava do naprave, ki je prijavljena pri sosednjem Hubu.

    Kar Hub poslje tej napravi, se ovije v `mesh.route` in gre sosedu; ta ga nespremenjenega preda
    svoji lokalni napravi. Tako vse obstojece usmerjanje (cilj, oddaja, klepet) dela brez sprememb.
    """

    def __init__(self, sosed_id: str, povezava, cilj: str, naslov: str = "", posredno: bool = False) -> None:
        self.sosed_id = sosed_id
        self.povezava = povezava
        self.cilj = cilj
        self.naslov = naslov
        self.posredno = posredno
        self.podatki: dict = {"sosed": sosed_id}

    def poslji(self, besedilo: str) -> bool:
        tovor = {"to": self.cilj, "msg": besedilo}
        if self.posredno:
            tovor["relay"] = True       # sosed naj preda svojemu sosedu (en sam vmesni skok)
        ovoj = {"id": link_ws.nakljucni(8), "type": "mesh.route", "payload": tovor}
        return bool(self.povezava.poslji(json.dumps(ovoj, ensure_ascii=False)))

    def zapri(self, *_a, **_k) -> None:
        # Zapreti se da samo sosednjo povezavo, ne posamezne oddaljene naprave.
        return None


class Hub:
    """Register naprav in usmerjanje sporocil. Brez omrezja - to je HubStreznik.

    Loceno zato, ker je prav tu vsa logika, ki mora biti pravilna: kdo sme noter, kam gre
    sporocilo in kaj dobi posiljatelj nazaj. Tako je preizkusljiva brez vticnikov in TLS.
    """

    def __init__(self, odtis: str = "", nas_id: str = "", ura: Callable[[], float] = _zdaj,
                 pot_zetonov: str = "", pot_varovalke: str = "") -> None:
        self.odtis = (odtis or "").lower()
        self.nas_id = nas_id
        self.ura = ura
        self._zaklep = threading.RLock()
        self._naprave: Dict[str, Naprava] = {}
        #: Safeer Chat za nepovezane naprave: cilj -> [(cas, surovo sporocilo)]
        self._klepet_cakajoci: Dict[str, list] = {}
        self._klepet_zaklep = threading.Lock()
        self._izzivi: Dict[str, tuple] = {}        # nonce -> (device_id, cas)
        self._vstopnice: Dict[str, tuple] = {}     # vstopnica -> (device_id, cas)
        self._prijave: Dict[str, dict] = {}        # pair_id -> seznanitev s kodo
        self._pridruzitve: Dict[str, dict] = {}    # qr_id -> pridruzitev s QR kodo
        self._pridruzeni: Dict[str, str] = {}      # porabljeni qr_id -> ime nove naprave
        self._qr_prijave: Dict[str, dict] = {}     # qr_id -> prijava s QR kodo na napravi
        #: "ip:vrata", kot ga naprava potrebuje v QR kodi (nastavi HubStreznik).
        self.naslov_za_qr = ""
        self._zetoni: Dict[str, tuple] = {}        # zeton -> (device_id, ime, cas)
        self._seje: Dict[str, tuple] = {}           # sejni zeton -> (device_id, potece)
        #: Zetoni seznanitve prezivijo ponovni zagon (naprava, ki kljuca se ni vpisala, ne ostane zunaj).
        self._pot_zetonov = pot_zetonov
        self._nalozi_zetone()
        #: Varovalka kode: skupna (ne po viru) omejitev ugibanja 6-mestne kode; stanje prezivi ponovni zagon.
        self._pot_varovalke = pot_varovalke
        self.varovalka = link_varovalka.VarovalkaKode(ura=ura, stanje=self._nalozi_varovalko(),
                                                      shrani=self._shrani_varovalko, ob_zapori=self._zapora_kode)
        #: Povezovanje s kodo se je zaprlo (dogodek varovalke): racunalnik pokaze obvestilo.
        self.ob_zapori_kode: Optional[Callable[[dict], None]] = None
        self.ob_spremembi: Optional[Callable[[], None]] = None
        #: Nova naprava caka na kodo: (ime naprave, koda) - racunalnik pokaze obvestilo.
        self.ob_kodi: Optional[Callable[[str, str], None]] = None
        #: Link Mesh: sosednji Hubi (id -> povezava), naprave vsakega soseda in zadnji poslani seznam.
        self._sosedje: Dict[str, object] = {}
        self._sosed_naprave: Dict[str, set] = {}
        #: Zadnji relay zemljevid vsakega soseda (naprave njegovih sosedov): id -> zapis.
        self._zadnji_relay: Dict[str, dict] = {}
        self._zadnji_mesh = ""
        #: Klice se, ko sosed pride ali odide (id, naslov ali ""): MeshPovezovalec si zapomni naslov
        #: in ob izgubi takoj poskusi znova.
        self.ob_sosedu: Optional[Callable[[str, str], None]] = None
        #: Datoteke na poti od posiljatelja do cilja (PUT /cast/file -> share.file -> GET /cast/file/<id>).
        self.deljenje = link_hub_deljenje.Deljenje(ura=ura)

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
        odgovor = {"ticket": self._nova_vstopnica(device_id, podpis=True), "session_token": self._nova_seja(device_id),
                   "hub_id": IDENTITETA_HUBA, "fp": self.odtis,
                   "expires_in_seconds": int(VSTOPNICA_VELJA_S)}
        try:
            odgovor["ring"] = link_krog.krog().json()
        except Exception:
            pass
        return odgovor

    def _pocisti_vstopnice(self) -> None:
        meja = self.ura() - VSTOPNICA_VELJA_S
        for v in [v for v, vnos in self._vstopnice.items() if vnos[1] < meja]:
            self._vstopnice.pop(v, None)

    def porabi_vstopnico(self, vstopnica: str) -> Optional[str]:
        """Id naprave, ki ji vstopnica pripada. Velja natanko enkrat."""
        return self.porabi_vstopnico_s_podpisom(vstopnica)[0]

    def porabi_vstopnico_s_podpisom(self, vstopnica: str) -> tuple:
        """(id naprave ali None, ali je bila vstopnica izdana s podpisom kljuca iz kroga)."""
        with self._zaklep:
            self._pocisti_vstopnice()
            vnos = self._vstopnice.pop((vstopnica or "").strip(), None)
        if not vnos:
            return None, False
        return vnos[0], bool(vnos[2]) if len(vnos) > 2 else False

    def _nova_vstopnica(self, device_id: str, podpis: bool = False) -> str:
        vstopnica = link_ws.nakljucni(24)
        with self._zaklep:
            self._pocisti_vstopnice()
            if len(self._vstopnice) >= NAJVEC_VSTOPNIC:
                najstarejsa = min(self._vstopnice, key=lambda k: self._vstopnice[k][1])
                self._vstopnice.pop(najstarejsa, None)
            self._vstopnice[vstopnica] = (device_id, self.ura(), podpis)
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

    def _nalozi_varovalko(self) -> Optional[dict]:
        if not self._pot_varovalke:
            return None
        try:
            with open(self._pot_varovalke, encoding="utf-8") as d:
                stanje = json.load(d)
            return stanje if isinstance(stanje, dict) else None
        except Exception:
            return None

    def _shrani_varovalko(self, stanje: dict) -> None:
        """Datoteka je samo za uporabnika (0600), kot zetoni."""
        if not self._pot_varovalke:
            return
        import os
        os.makedirs(os.path.dirname(self._pot_varovalke), exist_ok=True)
        zacasna = self._pot_varovalke + ".tmp"
        with open(os.open(zacasna, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as d:
            json.dump(stanje, d)
        os.replace(zacasna, self._pot_varovalke)

    def _odprte_kode(self) -> set:
        """Klice se pod kljucavnico: kode vabil, ki jih je odprla naprava v Linku (»Poveži naprave«)."""
        self._pocisti_pridruzitve()
        return {v.get("pin") for v in self._pridruzitve.values() if v.get("pin")}

    def _zapora_kode(self, dogodek: dict) -> None:
        """Varovalka je zaprla povezovanje s kodo: cakajoce prijave brez vabila padejo, kode na zaslonih ugasnejo."""
        with self._zaklep:
            odprte = self._odprte_kode()
            for pair_id in [k for k, p in self._prijave.items() if p.get("pin") not in odprte]:
                self._koncaj_prijavo(pair_id)
        if self.ob_zapori_kode is not None:
            try:
                self.ob_zapori_kode(dogodek)
            except Exception:
                pass

    def _pocisti_prijave(self) -> None:
        meja = self.ura() - PIN_VELJA_S
        for k in [k for k, p in self._prijave.items() if p["nastala"] < meja]:
            self._prijave.pop(k, None)
        meja = self.ura() - ZETON_VELJA_S
        potekli = [z for z, (_, _i, ko) in self._zetoni.items() if ko < meja]
        for z in potekli:
            self._zetoni.pop(z, None)
        if potekli:
            self._shrani_zetone()

    def _nov_zeton(self, device_id: str, ime: str) -> str:
        """Doda trajni zeton seznanitve z enotno omejitvijo in varnim zapisom."""
        self._pocisti_prijave()
        while len(self._zetoni) >= NAJVEC_ZETONOV:
            najstarejsi = min(self._zetoni, key=lambda k: self._zetoni[k][2])
            self._zetoni.pop(najstarejsi, None)
        zeton = "saf_pc_" + link_ws.nakljucni(24)
        self._zetoni[zeton] = (device_id, ime, self.ura())
        self._shrani_zetone()
        return zeton

    def _nova_seja(self, device_id: str) -> str:
        with self._zaklep:
            zdaj = self.ura()
            for z in [z for z, (_i, potece) in self._seje.items() if potece < zdaj]:
                self._seje.pop(z, None)
            while len(self._seje) >= NAJVEC_SEJ:
                najstarejsa = min(self._seje, key=lambda k: self._seje[k][1])
                self._seje.pop(najstarejsa, None)
            zeton = "saf_seja_" + link_ws.nakljucni(24)
            self._seje[zeton] = (device_id, zdaj + SEJA_VELJA_S)
            return zeton

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
        """Nova naprava se zeli pridruziti. Kode ne vrnemo njej - pokazejo jo naprave v Linku.

        None = prevec cakajocih prijav; {"napaka": "seznanitev_zaprta"} = varovalka je povezovanje s kodo zaprla."""
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
            # Ce je katera naprava v Linku ravno odprla »Poveži naprave«, ze kaze 6-mestno kodo: nova
            # naprava se seznani prav z njo (enako kot sredisce na televizorju), uporabnik jo samo prepise.
            self._pocisti_pridruzitve()
            odprta = [v.get("pin") for v in self._pridruzitve.values() if v.get("pin")]
            if not self.varovalka.zacetek(naslov, bool(odprta)):
                return {"napaka": "seznanitev_zaprta"}
            koda = odprta[-1] if odprta else str(100000 + secrets.randbelow(900000))
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
            # En krog naprave pove, ali je njena koda prava: to JE poskus kode in steje v skupno mejo.
            if not self.varovalka.poskus(str(p.get("naslov") or ""), p["pin"] in self._odprte_kode()):
                self._koncaj_prijavo(pair_id)
                return None, None, "seznanitev_zaprta"
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
            zeton = self._nov_zeton(device_id, p["ime"])
            self.varovalka.uspeh(str(p.get("naslov") or ""))
            # Koda z vabila je enkratna: po uspesni seznanitvi ne velja vec.
            for k in [k for k, v in self._pridruzitve.items() if v.get("pin") == p["pin"]]:
                self._pridruzitve.pop(k, None)
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
            import secrets
            self._pridruzitve[qr_id] = {"odtis": hashlib.sha256(skrivnost.encode()).hexdigest(),
                                        "nastala": self.ura(), "poskusov": 0,
                                        "pin": str(100000 + secrets.randbelow(900000))}
        return qr_id, skrivnost

    def ima_odprto_kodo(self) -> bool:
        with self._zaklep:
            self._pocisti_pridruzitve()
            return any(v.get("pin") for v in self._pridruzitve.values())

    def pin_pridruzitve(self, qr_id: str) -> str:
        """6-mestna koda vabila (pokaze jo naprava, ki vabi; nova naprava jo vtipka)."""
        with self._zaklep:
            p = self._pridruzitve.get((qr_id or "").strip())
            return str(p.get("pin") or "") if p else ""

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
            pravo_ime = (ime or device_id).strip()[:NAJVEC_IMENA]
            zeton = self._nov_zeton(device_id, pravo_ime)
            while len(self._pridruzeni) >= NAJVEC_CAKAJOCIH:
                self._pridruzeni.pop(next(iter(self._pridruzeni)), None)
            self._pridruzeni[qr_id] = pravo_ime
        return zeton, None

    # ------------------------------------------------------------------ prijava s QR kodo (naprava pokaže QR)
    def zacni_qr(self, device_id: str, ime: str, platform: str, secret_sha256: str, poll_secret: str) -> tuple:
        import re
        if not re.match(r"^[0-9a-f]{64}$", (secret_sha256 or "").lower()) or len(poll_secret or "") < 16:
            return None, "neveljavno"
        with self._zaklep:
            self._pocisti_qr()
            for k in [k for k, p in self._qr_prijave.items() if p["device_id"] == device_id]:
                self._qr_prijave.pop(k, None)
            if len(self._qr_prijave) >= NAJVEC_CAKAJOCIH:
                return None, "prevec_prijav"
            qr_id = link_ws.nakljucni(12)
            self._qr_prijave[qr_id] = {
                "device_id": device_id,
                "name": (ime or device_id).strip()[:NAJVEC_IMENA],
                "platform": (platform or "windows").strip()[:16],
                "secret_sha256": secret_sha256.lower(),
                "poll_secret": poll_secret,
                "nastala": self.ura(),
                "token": None,
                "approved": False,
                "poskusov": 0
            }
        return qr_id, None

    def qr_podatki(self, qr_id: str, skrivnost: str) -> tuple:
        import hashlib
        import hmac
        with self._zaklep:
            self._pocisti_qr()
            p = self._qr_prijave.get((qr_id or "").strip())
            if not p:
                return None, "qr_ne_obstaja"
            if not hmac.compare_digest(hashlib.sha256((skrivnost or "").encode("utf-8")).hexdigest(), p["secret_sha256"]):
                p["poskusov"] += 1
                if p["poskusov"] >= NAJVEC_POSKUSOV:
                    self._qr_prijave.pop(qr_id, None)
                    return None, "prevec_poskusov"
                return None, "qr_ne_obstaja"
            return {"device_id": p["device_id"], "name": p["name"], "platform": p["platform"]}, None

    def odobri_qr(self, qr_id: str, skrivnost: str, odobril_device_id: str) -> tuple:
        import hashlib
        import hmac
        with self._zaklep:
            self._pocisti_qr()
            p = self._qr_prijave.get((qr_id or "").strip())
            if not p:
                return None, "qr_ne_obstaja"
            if not hmac.compare_digest(hashlib.sha256((skrivnost or "").encode("utf-8")).hexdigest(), p["secret_sha256"]):
                p["poskusov"] += 1
                if p["poskusov"] >= NAJVEC_POSKUSOV:
                    self._qr_prijave.pop(qr_id, None)
                    return None, "prevec_poskusov"
                return None, "qr_ne_obstaja"
            if p["device_id"] == odobril_device_id:
                return None, "ista_naprava"
            if not p["token"]:
                zeton = self._nov_zeton(p["device_id"], p["name"])
                p["token"] = zeton
                p["approved"] = True
                p["odobril"] = odobril_device_id
            return {"device_id": p["device_id"], "name": p["name"], "platform": p["platform"]}, None

    def prevzemi_qr(self, qr_id: str, device_id: str, poll_secret: str) -> tuple:
        import hmac
        with self._zaklep:
            self._pocisti_qr()
            p = self._qr_prijave.get((qr_id or "").strip())
            if not p or p["device_id"] != device_id or not hmac.compare_digest(p["poll_secret"], poll_secret):
                return "qr_ne_obstaja", None
            if not p["token"]:
                return "caka", None
            zeton = p["token"]
            self._qr_prijave.pop(qr_id, None)
            return "odobreno", zeton

    def preklici_qr(self, qr_id: str, device_id: str, poll_secret: str) -> bool:
        import hmac
        with self._zaklep:
            p = self._qr_prijave.get((qr_id or "").strip())
            if not p or p["device_id"] != device_id or not hmac.compare_digest(p["poll_secret"], poll_secret):
                return False
            self._qr_prijave.pop(qr_id, None)
            return True

    def _pocisti_qr(self) -> None:
        meja = self.ura() - PIN_VELJA_S
        for k in [k for k, p in self._qr_prijave.items() if p["nastala"] < meja]:
            self._qr_prijave.pop(k, None)

    def zeton_lastne_naprave(self, device_id: str, ime: str = "") -> Optional[str]:
        """Zeton za napravo, ki to sredisce gosti v ISTEM procesu (Safeer OS za Windows in njegovo sredisce).

        Ni pot HTTP: kdor lahko poklice to metodo, ze tece v nasem procesu. Seznanitev s kodo (SPAKE2) med dvema
        koncema istega procesa zato ne varuje nicesar, traja pa (izmerjeno 5. 10. 2026 na testnem Windows)
        2,6-4,8 s ob vsakem zagonu. Prejsnje zetone iste naprave zamenja: zagon za zagonom bi sicer iz shrambe
        (NAJVEC_ZETONOV) izrinil zetone drugih naprav.
        """
        device_id = (device_id or "").strip()[:NAJVEC_IMENA]
        if not device_id:
            return None
        with self._zaklep:
            for z in [z for z, vnos in self._zetoni.items() if vnos[0] == device_id]:
                self._zetoni.pop(z, None)
            return self._nov_zeton(device_id, (ime or device_id).strip()[:NAJVEC_IMENA])

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
            zdaj = self.ura()
            for z in [z for z, (_i, potece) in self._seje.items() if potece < zdaj]:
                self._seje.pop(z, None)
            for z, (device_id, _potece) in self._seje.items():
                if hmac.compare_digest(z, zeton):
                    try:
                        clan = link_krog.krog().clan_za_id(device_id)
                    except Exception:
                        clan = None
                    if clan:
                        return device_id, str(clan.get("ime") or device_id)
        return None

    def sorodni_zeton(self, zeton: str, device_id: str, ime: str) -> tuple:
        """Zeton za drugi Safeerjev program iste fizicne naprave (npr. Browser -> Control)."""
        lastnik = self.naprava_zetona(zeton)
        device_id = (device_id or "").strip()[:NAJVEC_IMENA]
        if lastnik is None:
            return None, "naprava_ni_seznanjena"
        if not device_id:
            return None, "manjka_device_id"
        if device_id == lastnik[0] or not device_id.startswith(lastnik[0] + "-"):
            return None, "ni_sorodnik"
        with self._zaklep:
            return self._nov_zeton(device_id, (ime or device_id).strip()[:NAJVEC_IMENA]), None

    def stanje_pridruzitve(self, qr_id: str) -> dict:
        with self._zaklep:
            self._pocisti_pridruzitve()
            ime = self._pridruzeni.get((qr_id or "").strip(), "")
            return {"pending": (qr_id or "").strip() in self._pridruzitve,
                    "joined": bool(ime), "name": ime}

    def odidi(self, zeton: str) -> Optional[List[str]]:
        """Naprava sama zapusti Link; odstranijo se tudi njeni aliasi z istim javnim kljucem."""
        lastnik = self.naprava_zetona(zeton)
        if lastnik is None:
            return None
        device_id = lastnik[0]
        krog = link_krog.krog()
        clan = krog.clan_za_id(device_id)
        kljuc = str((clan or {}).get("kljuc") or "")
        idji = {device_id}
        if kljuc:
            for i, c in (krog.json().get("clani") or {}).items():
                if c.get("kljuc") == kljuc and i != self.nas_id:
                    idji.add(i)
        povezave = []
        with self._zaklep:
            for z in [z for z, (i, _ime, _ko) in self._zetoni.items() if i in idji]:
                self._zetoni.pop(z, None)
            for z in [z for z, (i, _potece) in self._seje.items() if i in idji]:
                self._seje.pop(z, None)
            self._shrani_zetone()
            for i in idji:
                n = self._naprave.get(i)
                if n is not None and n.povezava is not None:
                    povezave.append(n.povezava)
                    n.povezava = None
        for i in idji:
            if i == self.nas_id:
                continue
            trenutni = krog.clan(i)
            dodano = float((trenutni or {}).get("dodano") or 0.0)
            krog.umakni(i, device_id, max(self.ura(), dodano + 0.001))
        for p in povezave:
            try:
                p.zapri(1000, "naprava je zapustila Safeer Link")
            except Exception:
                pass
        krog_json = krog.json()
        obvestilo = json.dumps({"type": "trust.update", "payload": krog_json}, ensure_ascii=False)
        for n in self.povezane():
            if n.povezava is not None:
                try:
                    n.povezava.poslji(obvestilo)
                except Exception:
                    pass
        self.objavi_naprave()
        return sorted(idji)

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

    def ima_povezavo_z(self, naslov: str) -> bool:
        """Ali ima naprava ali sosednje sredisce s tega naslova pri nas odprto povezavo (prijava z vstopnico je uspela).
        Tak vir je za obrambo zaupan, dokler je povezan."""
        if not naslov:
            return False
        with self._zaklep:
            if any(n.povezava is not None and not n.sosed and n.naslov == naslov for n in self._naprave.values()):
                return True
            return bool(self._sosed_na_naslovu(naslov))

    def _sosed_na_naslovu(self, naslov: str) -> str:
        """Klice se pod kljucavnico: id sosednjega sredisca (Link Mesh), ki je povezano s tega naslova, ali ''."""
        for sosed_id, p in self._sosedje.items():
            n = str(getattr(p, "naslov", "") or "")
            if n == naslov:
                return sosed_id
            if "://" in n:        # odhodna sosednja povezava nosi naslov sredisca (wss://ip:vrata/cast/ws)
                try:
                    if urlparse(n).hostname == naslov:
                        return sosed_id
                except Exception:
                    pass
        return ""

    def ime_po_naslovu(self, naslov: str) -> str:
        """Ime naprave ali sosednjega sredisca, ki ga sredisce pozna s tega naslova, ali ''. Za obvestilo obrambe."""
        if not naslov:
            return ""
        with self._zaklep:
            znane = [n for n in self._naprave.values() if n.naslov == naslov and not n.sosed]
            sosed = "" if znane else self._sosed_na_naslovu(naslov)
        if znane:
            n = max(znane, key=lambda x: x.zadnjic)
            return self.ime_v_krogu(n.id) or n.ime or ""
        # Sosednje sredisce ni v registru naprav: ime ima krog zaupanja.
        return (self.ime_v_krogu(sosed) or "") if sosed else ""

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

    def seznam_json(self, za: Optional[object] = None) -> str:
        """Seznam naprav za enega odjemalca (`za` = njegova povezava; brez nje surov seznam).

        Program, ki je s Hubom povezan z ISTEGA racunalnika, ima pri nas 127.0.0.1 in dobi polje `here`. Odjemalcu z
        istega racunalnika naslov ostane (po njem prepozna programe svoje naprave). Odjemalec od DRUGOD bi se z njim
        povezal sam nase, zato dobi nas naslov na poti do njega - krajevni konec njegove povezave."""
        nas = _nas_naslov_za_odjemalca(za)
        naprave = []
        for n in self.povezane():
            zapis = n.json()
            if not n.sosed and n.naslov and _samo_tukaj(n.naslov):
                zapis["here"] = True
                if nas is not None:
                    zapis["ip"] = nas
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
        # Odjemalci z istega racunalnika dobijo isti (surov) seznam; odjemalci od drugod svojega - gl. seznam_json.
        seznami: Dict[Optional[str], str] = {}
        for n in self.povezane():
            p = n.povezava
            if p is not None and not n.sosed:
                kljuc = _nas_naslov_za_odjemalca(p)
                if kljuc not in seznami:
                    seznami[kljuc] = self.seznam_json(p)
                p.poslji(seznami[kljuc])
        self._objavi_sosedom()
        if self.ob_spremembi is not None:
            try:
                self.ob_spremembi()
            except Exception:
                pass

    def _ime_naprave(self, device_id: str) -> str:
        n = self.najdi(device_id)
        return n.ime if n is not None and n.ime else device_id

    # ------------------------------------------------------------------ deljenje (besedilo, datoteka)

    def cilj_deljenja(self, cilj: str, posiljatelj: str, datoteka: bool = False) -> Optional[tuple]:
        """None, ce cilj lahko dobi deljenje; sicer (koda HTTP, sporocilo, oznaka)."""
        if not cilj:
            return 400, "Manjka target.", "manjka_target"
        if cilj == posiljatelj:
            return 400, "Naprava ne more deliti sama s sabo.", "isti_naprava"
        naprava = self.najdi(cilj)
        if naprava is None or naprava.povezava is None:
            return 404, "Ciljna naprava ni povezana.", "naprava_ni_povezana"
        if datoteka and naprava.sosed:
            # Cilj datoteko prevzame pri SVOJEM sredisci (pot v share.file je relativna), ta pa je pri nas.
            return 409, "Ciljna naprava je povezana prek drugega središča; datoteke ji od tu ni mogoče poslati.", \
                "naprava_pri_drugem_srediscu"
        return None

    def posreduj_deljenje(self, tip: str, posiljatelj: str, cilj: str, tovor: dict, ime_posiljatelja: str = "") -> bool:
        """Sporocilo deljenja ciljni napravi - enako, kot ga poslje Hub na Androidu (posredujDeljenje)."""
        naprava = self.najdi(cilj)
        if naprava is None or naprava.povezava is None:
            return False
        ime = self._ime_naprave(posiljatelj)
        sporocilo = {"id": "hub-" + link_ws.nakljucni(8), "type": tip, "target": cilj, "sender": posiljatelj,
                     "sender_name": ime if ime != posiljatelj or not ime_posiljatelja else ime_posiljatelja,
                     "timestamp": self.ura(), "payload": tovor}
        try:
            return naprava.povezava.poslji(json.dumps(sporocilo, ensure_ascii=False)) is not False
        except Exception:
            return False

    def preimenuj_napravo(self, zeton: str, device_id: str, ime: str) -> tuple:
        """POST /cast/devices/rename: ime, ki ga je napravi dal uporabnik. Zivi v krogu zaupanja in ga vidijo vse
        naprave (kot HubUsmerjevalnik.preimenuj na Androidu); prazno ime vrne tisto, ki ga naprava pove o sebi.
        Preimenujemo vse clane z istim kljucem (brskalnik in Safeer Control na isti napravi). Vrne (koda, odgovor)."""
        if not self.naprava_zetona(zeton):
            return 401, link_hub_deljenje.napaka("Naprava ni seznanjena.", "naprava_ni_seznanjena")
        device_id = str(device_id or "").strip()[:NAJVEC_IMENA]
        if not device_id:
            return 400, link_hub_deljenje.napaka("Manjka device_id.", "manjka_device_id")
        fizicna = self.naprava_iz_kljuca(device_id)
        if not fizicna:
            return 404, link_hub_deljenje.napaka("Naprava ni v krogu zaupanja.", "naprava_ni_v_krogu")
        cisto = re.sub(r"[\x00-\x1f<>]", "", str(ime or "")).strip()[:NAJVEC_IMENA]
        krog = link_krog.krog()
        spremenjeno = False
        for cid, c in krog.json().get("clani", {}).items():
            try:
                if link_krog.id_iz_kljuca(str(c.get("kljuc") or "")) != fizicna:
                    continue
            except Exception:
                continue
            naprava = self.najdi(cid)
            novo = cisto or (naprava.ime if naprava is not None and naprava.ime else "") or str(c.get("ime") or "")
            if novo and novo != c.get("ime"):
                # Novejse ime zmaga pri zdruzevanju krogov na vseh napravah (tudi ob zamaknjeni uri).
                spremenjeno = krog.preimenuj(cid, novo, max(time.time(), float(c.get("imenovano") or 0.0) + 0.001)) or spremenjeno
        if spremenjeno:
            self._po_spremembi_kroga()
        return 200, {"id": device_id, "name": self.ime_v_krogu(device_id) or self._ime_naprave(device_id)}

    def deli_besedilo(self, zeton: str, cilj: str, besedilo: str) -> tuple:
        """POST /cast/share/text. Vrne (koda HTTP, odgovor)."""
        lastnik = self.naprava_zetona(zeton)
        if not lastnik:
            return 401, link_hub_deljenje.napaka("Naprava ni seznanjena.", "naprava_ni_seznanjena")
        posiljatelj, ime = lastnik
        cilj = str(cilj or "").strip()[:NAJVEC_IMENA]
        besedilo = str(besedilo or "")[:link_hub_deljenje.NAJVEC_BESEDILA]
        if cilj and not besedilo.strip():
            return 400, link_hub_deljenje.napaka("Besedilo je prazno.", "prazno_besedilo")
        zavrnjeno = self.cilj_deljenja(cilj, posiljatelj)
        if zavrnjeno is not None:
            return zavrnjeno[0], link_hub_deljenje.napaka(zavrnjeno[1], zavrnjeno[2])
        if not self.posreduj_deljenje("share.text", posiljatelj, cilj, {"text": besedilo}, ime):
            return 404, link_hub_deljenje.napaka("Ciljna naprava ni povezana.", "naprava_ni_povezana")
        return 200, {"sent": True}

    def steviloCakajocihKlepetov(self, cilj: str) -> int:  # noqa: N802 (enako ime kot na Androidu)
        with self._klepet_zaklep:
            return len(self._klepet_cakajoci.get(cilj, []))

    def _usmeri_klepet(self, sporocilo: dict, id_sporocila: str, cilj: str, moj_id: str) -> str:
        """Safeer Chat. Cilj je fizicna naprava (kljuc iz kroga) ali posamezen id; nepovezani pocaka."""
        tovor = sporocilo.get("payload") if isinstance(sporocilo.get("payload"), dict) else {}
        besedilo_kl = str(tovor.get("text") or "")
        if not besedilo_kl or len(besedilo_kl.encode("utf-8")) > 16 * 1024:
            return self._potrditev(id_sporocila, "chat", "rejected", "Sporočilo je prazno ali preveliko.", "meja")
        with self._zaklep:
            vse = list(self._naprave.values())
        kandidati = [n for n in vse if "chat" in (n.zmoznosti or []) and self.naprava_iz_kljuca(n.id) == cilj]
        naprava = self.najdi(cilj)
        if naprava is None and not kandidati:
            return self._potrditev(id_sporocila, "chat", "rejected", "Naprave ni na Safeer Linku.", "ni_naprave")
        moj_kljuc = self.naprava_iz_kljuca(moj_id)
        if moj_kljuc and moj_kljuc == cilj:
            return self._potrditev(id_sporocila, "chat", "rejected", "Ista naprava.", "isti_naprava")
        sporocilo["sender"] = moj_id
        sporocilo["sender_name"] = self._ime_naprave(moj_id)
        if moj_kljuc:
            sporocilo["sender_device"] = moj_kljuc
        besedilo = json.dumps(sporocilo, ensure_ascii=False)
        prejemnik = naprava.povezava if naprava is not None and naprava.povezava is not None else next(
            (n.povezava for n in kandidati if n.povezava is not None), None)
        if prejemnik is not None:
            try:
                prejemnik.poslji(besedilo)
                self._osvezi(moj_id)
                return self._potrditev(id_sporocila, "chat", "accepted")
            except Exception:
                pass
        with self._klepet_zaklep:
            vrsta = self._klepet_cakajoci.setdefault(cilj, [])
            vrsta.append((self.ura(), besedilo))
            del vrsta[:-KLEPET_NA_NAPRAVO]
        return self._potrditev(id_sporocila, "chat", "queued")

    def _dostavi_klepet(self, cilj: str, povezava) -> None:
        with self._klepet_zaklep:
            cakajoci = self._klepet_cakajoci.pop(cilj, [])
        zdaj, ostanek = self.ura(), []
        for cas, sporocilo in cakajoci:
            if zdaj - cas > KLEPET_ZIVLJENJE_S:
                continue
            try:
                povezava.poslji(sporocilo)
            except Exception:
                ostanek.append((cas, sporocilo))
        if ostanek:
            with self._klepet_zaklep:
                self._klepet_cakajoci[cilj] = ostanek + self._klepet_cakajoci.get(cilj, [])

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
            if obstojeca is not None and obstojeca.sosed:
                # Naprava je bila vidna prek soseda, zdaj se prijavlja pri nas: velja lokalna povezava.
                self._sosed_naprave.get(obstojeca.sosed, set()).discard(device_id)
                obstojeca.sosed = ""
                obstojeca.posredno = False
                obstojeca.povezava = None
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
        self._stik(device_id)
        return "accepted", ""

    def _stik(self, idji) -> None:
        """Clan se je oglasil (prijava, sosed, seznam soseda): zabelezi za pospravljanje kroga (link_krog.pospravi)."""
        try:
            link_krog.krog().zabelezi_stik(idji, self.ura())
        except Exception:
            pass

    def pospravi_krog(self) -> list:
        """Umakne clane brez stika vec kot DNI_BREZ_STIKA (stare identitete po ponovni namestitvi); umik gre vsem."""
        try:
            umaknjeni = link_krog.krog().pospravi(self.nas_id or IDENTITETA_HUBA, self.ura())
        except Exception:
            return []
        if umaknjeni:
            logging.getLogger("safeer.link").info("Krog: umaknjeni clani brez stika %d dni: %s", link_krog.DNI_BREZ_STIKA, ", ".join(umaknjeni))
            self._po_spremembi_kroga()
        return umaknjeni

    def odklopi(self, povezava) -> None:
        sosed = self._sosed_povezave(povezava)
        if sosed:
            self._odstrani_soseda(sosed, povezava)
            return
        spremenjeno = False
        with self._zaklep:
            for n in self._naprave.values():
                if n.povezava is povezava:
                    n.povezava = None
                    spremenjeno = True
        if spremenjeno:
            self.objavi_naprave()

    # ------------------------------------------------------------------ Link Mesh (docs/LINK-MESH.md)

    def sosedje(self) -> List[str]:
        with self._zaklep:
            return sorted(self._sosedje)

    def _sosed_povezave(self, povezava) -> str:
        with self._zaklep:
            for sid, p in self._sosedje.items():
                if p is povezava:
                    return sid
        return ""

    def _je_clan(self, device_id: str) -> bool:
        try:
            return link_krog.krog().clan_za_id(device_id) is not None
        except Exception:
            return False

    def _lokalne_json(self, nas_naslov: Optional[str] = None) -> Dict[str, dict]:
        """Nase lokalne naprave za sosede (id -> zapis): samo clani kroga, brez oddaljenih in brez casa
        zadnjega stika. Oblika je ista kot na Androidu (HubUsmerjevalnik.lokalneZaSosede).

        `nas_naslov` je nas naslov na poti do soseda, ki mu seznam posiljamo: program s TEGA racunalnika (pri nas
        127.0.0.1) gre cez mejo s tem naslovom - gl. `_naslov_za_druge`. Brez njega (None) ostane zapis surov; tak
        je samo kljuc, po katerem vemo, ali se je seznam spremenil."""
        naprave = {}
        for n in self.povezane():
            if n.sosed or not self._je_clan(n.id):
                continue
            zapis = n.json()
            for polje in ("id", "last_seen", "port"):
                zapis.pop(polje, None)
            if nas_naslov is not None:
                zapis["ip"] = _naslov_za_druge(n.naslov, nas_naslov)
            naprave[n.id] = zapis
        return naprave

    def _posredne_json(self) -> Dict[str, dict]:
        """Naprave nasih NEPOSREDNIH sosedov (ne tistih, ki jih ze sami vidimo posredno): sosed, ki
        do njih nima svoje poti, jih doseze prek nas. Tako je pot najvec en vmesni Hub - brez zank."""
        naprave = {}
        for n in self.povezane():
            if not n.sosed or n.posredno or not self._je_clan(n.id):
                continue
            zapis = n.json()
            for polje in ("id", "last_seen", "port"):
                zapis.pop(polje, None)
            zapis["hub"] = n.sosed
            naprave[n.id] = zapis
        return naprave

    def _mesh_naprave(self, za: Optional[object] = None) -> str:
        """Seznam za enega soseda (`za` = povezava do njega): vsak sosed dobi nas naslov, kot velja na poti do njega."""
        return json.dumps({"type": "mesh.devices", "id": link_ws.nakljucni(8),
                           "payload": {"hub": self.nas_id, "devices": self._lokalne_json(_nas_naslov_proti(za)),
                                       "relay": self._posredne_json()}},
                          ensure_ascii=False, sort_keys=True)

    def _objavi_sosedom(self, samo: Optional[object] = None) -> None:
        seznam = {"d": self._lokalne_json(), "r": self._posredne_json()}
        kljuc = json.dumps(seznam, sort_keys=True)
        with self._zaklep:
            if samo is None and kljuc == self._zadnji_mesh:
                return
            if samo is None:
                self._zadnji_mesh = kljuc
            prejemniki = [samo] if samo is not None else list(self._sosedje.values())
        for p in prejemniki:
            try:
                p.poslji(self._mesh_naprave(p))
            except Exception:
                pass

    def dodaj_soseda(self, sosed_id: str, povezava, zacel: str) -> bool:
        """Sosednja povezava je vzpostavljena (`zacel` = id Huba, ki jo je odprl).

        Ce za istega soseda ze obstaja povezava (oba sta klicala hkrati), ostane tista, ki jo je
        odprl manjsi id - obe strani tako izbereta isto in ena povezava se zapre.
        """
        if not sosed_id or sosed_id == self.nas_id:
            return False
        stara = None
        with self._zaklep:
            obstojeca = self._sosedje.get(sosed_id)
            if obstojeca is not None and obstojeca is not povezava:
                zacetnik_stare = getattr(obstojeca, "podatki", {}).get("zacel", "")
                if zacetnik_stare == min(sosed_id, self.nas_id) and zacel != zacetnik_stare:
                    return False
                stara = obstojeca
            if obstojeca is None and len(self._sosedje) >= NAJVEC_SOSEDOV:
                return False
            try:
                povezava.podatki["zacel"] = zacel
            except Exception:
                pass
            self._sosedje[sosed_id] = povezava
        if stara is not None:
            self._pocisti_soseda(sosed_id)
            try:
                stara.zapri(1000, "podvojena sosednja povezava")
            except Exception:
                pass
        if self.ob_sosedu is not None:
            try:
                self.ob_sosedu(sosed_id, str(getattr(povezava, "naslov", "") or ""))
            except Exception:
                pass
        self._stik(sosed_id)
        # Novemu sosedu takoj nase naprave in nas krog.
        self._objavi_sosedom(samo=povezava)
        try:
            povezava.poslji(json.dumps({"type": "mesh.trust", "id": link_ws.nakljucni(8),
                                        "payload": link_krog.krog().json()}, ensure_ascii=False))
        except Exception:
            pass
        return True

    def _sprejmi_soseda(self, povezava, tovor: dict, id_sporocila: str) -> str:
        """Drug Hub se je prijavil kot sosed. Samo clan kroga s podpisom kljuca, pod svojim id.
        Zavrnjena povezava se po odgovoru zapre - sicer bi vsak ponovni poskus pustil odprto vticnico."""
        odgovor = self._sprejmi_soseda_odlocitev(povezava, tovor, id_sporocila)
        if '"rejected"' in odgovor:
            try:
                povezava.podatki["zapri_po_odgovoru"] = True
            except Exception:
                pass
        return odgovor

    def _sprejmi_soseda_odlocitev(self, povezava, tovor: dict, id_sporocila: str) -> str:
        sosed_id = str(tovor.get("device_id") or "").strip()[:NAJVEC_IMENA]
        podatki = getattr(povezava, "podatki", {}) or {}
        if not sosed_id or podatki.get("id") != sosed_id or not podatki.get("podpis") or not self._je_clan(sosed_id):
            return self._potrditev(id_sporocila, "cast", "rejected", "Sosed mora biti clan kroga s podpisom.", "ni_sosed")
        from core import link_mesh
        if sosed_id in link_mesh.brez_neposredne():
            return self._potrditev(id_sporocila, "cast", "rejected", "Preizkus: brez neposredne povezave.", "preizkus")
        if not self.dodaj_soseda(sosed_id, povezava, sosed_id):
            return self._potrditev(id_sporocila, "cast", "rejected", "Sosednja povezava ze obstaja.", "podvojen_sosed")
        return self._potrditev(id_sporocila, "cast", "accepted")

    def _pocisti_soseda(self, sosed_id: str) -> List[str]:
        """Odstrani oddaljene naprave soseda iz registra. Vrne njihove id-je.

        Neposredne naprave izgubljenega soseda so morda se dosegljive prek drugega soseda (relay):
        zato posredne poti takoj preracunamo."""
        with self._zaklep:
            ids = list(self._sosed_naprave.pop(sosed_id, set()))
            self._zadnji_relay.pop(sosed_id, None)
            for i in ids:
                n = self._naprave.get(i)
                if n is not None and n.sosed == sosed_id and not n.posredno:
                    # Ostane znana, a nepovezana (kot lokalna po odklopu): klepet zanjo pocaka.
                    n.sosed = ""
                    n.povezava = None
            ids += self._pocisti_posredne_prek(sosed_id)
        self._uporabi_posredne()
        return ids

    def _odstrani_soseda(self, sosed_id: str, povezava=None) -> None:
        with self._zaklep:
            if povezava is not None and self._sosedje.get(sosed_id) is not povezava:
                return          # zaprla se je stara (podvojena) povezava; velja nova
            self._sosedje.pop(sosed_id, None)
        if self._pocisti_soseda(sosed_id):
            self.objavi_naprave()
        if self.ob_sosedu is not None:
            try:
                self.ob_sosedu(sosed_id, "")
            except Exception:
                pass

    def _pocisti_posredne_prek(self, sosed_id: str) -> List[str]:
        """Pod kljucavnico: posredne naprave prek tega soseda postanejo nepovezane."""
        ids = []
        for i, n in self._naprave.items():
            if n.posredno and n.sosed == sosed_id:
                n.sosed, n.posredno, n.povezava = "", False, None
                ids.append(i)
        return ids

    def _napolni(self, n: "Naprava", z: dict) -> None:
        n.ime = str(z.get("name") or n.id)[:NAJVEC_IMENA]
        n.vloga = str(z.get("role") or "receiver")[:16]
        n.zmoznosti = [str(x)[:24] for x in (z.get("capabilities") or [])][:24]
        n.naslov = str(z.get("ip") or "")[:64]
        n.protokol = str(z.get("protocol") or "")[:8]
        n.platforma = str(z.get("platform") or "")[:16]
        n.vrsta = str(z.get("kind") or "")[:16]
        n.razlicica = str(z.get("version") or "")[:32]
        try:
            n.prioriteta = max(0, min(1000, int(z.get("priority") or 0)))
        except Exception:
            n.prioriteta = 0
        n.aplikacije = z["apps"] if isinstance(z.get("apps"), dict) else {}
        n.zadnjic = self.ura()

    def _uporabi_posredne(self) -> None:
        """Iz zadnjih relay zemljevidov sosedov sestavi posredne poti. Lokalna in neposredna pot imata
        vedno prednost; ce napravo ponuja vec sosedov, velja prvi po id (vsi Hubi izberejo enako)."""
        novi: List[str] = []
        with self._zaklep:
            zeljene: Dict[str, tuple] = {}
            for sosed in sorted(self._zadnji_relay):
                if sosed not in self._sosedje:
                    continue
                for did, z in list(self._zadnji_relay[sosed].items())[:NAJVEC_NAPRAV]:
                    if did in zeljene or did == self.nas_id or str(z.get("hub") or "") == self.nas_id:
                        continue
                    n = self._naprave.get(did)
                    if n is not None and n.povezava is not None and not n.posredno:
                        continue                  # lokalna ali neposredna pot
                    zeljene[did] = (sosed, z)
            for did, n in list(self._naprave.items()):
                if n.posredno and (did not in zeljene or zeljene[did][0] != n.sosed):
                    n.sosed, n.posredno, n.povezava = "", False, None
            for did, (sosed, z) in zeljene.items():
                n = self._naprave.get(did)
                if n is None:
                    n = Naprava(did, "", "receiver", [], "")
                    self._naprave[did] = n
                if n.povezava is None:
                    novi.append(did)
                self._napolni(n, z)
                n.naslov = _naslov_za_druge(n.naslov, "")[:64]
                n.sosed, n.posredno = sosed, True
                if not (isinstance(n.povezava, _Namestnik) and n.povezava.sosed_id == sosed and n.povezava.posredno):
                    n.povezava = _Namestnik(sosed, self._sosedje[sosed], did, n.naslov, posredno=True)
        self._dostavi_cakajoce(novi)

    def _dostavi_cakajoce(self, ids: List[str]) -> None:
        """Klepet, ki je cakal na napravo, gre zdaj prek soseda."""
        for did in ids:
            n = self.najdi(did)
            if n is not None and n.povezava is not None:
                self._dostavi_klepet(did, n.povezava)
                kljuc = self.naprava_iz_kljuca(did)
                if kljuc and "chat" in (n.zmoznosti or []):
                    self._dostavi_klepet(kljuc, n.povezava)

    def _sosedove_naprave(self, sosed_id: str, povezava, naprave: dict, relay: Optional[dict] = None) -> None:
        novi: Dict[str, dict] = {}
        for did, z in list((naprave if isinstance(naprave, dict) else {}).items())[:NAJVEC_NAPRAV]:
            if not isinstance(z, dict):
                continue
            did = str(did or "").strip()
            if len(did) > NAJVEC_IMENA:
                continue
            # Cez mejo Huba gredo samo clani kroga (sosed ne more pripeljati tujca) in nikoli mi sami.
            if did and did != self.nas_id and self._je_clan(did):
                novi[did] = z
        self._stik(list(novi))
        dodani = []
        gostitelj = _gostitelj_soseda(povezava)
        with self._zaklep:
            if self._sosedje.get(sosed_id) is not povezava:
                return
            stari = self._sosed_naprave.get(sosed_id, set())
            obdrzani = set()
            for did, z in novi.items():
                n = self._naprave.get(did)
                if n is not None and not n.sosed and n.povezava is not None:
                    continue                      # lokalna prijava ima prednost
                if n is not None and n.sosed and n.sosed != sosed_id and not n.posredno and n.povezava is not None:
                    continue                      # ze vidna neposredno prek drugega soseda
                if n is None:
                    n = Naprava(did, "", "receiver", [], "")
                    self._naprave[did] = n
                if n.povezava is None:
                    dodani.append(did)
                self._napolni(n, z)
                n.naslov = _naslov_za_druge(n.naslov, gostitelj)[:64]
                n.sosed, n.posredno = sosed_id, False
                n.povezava = _Namestnik(sosed_id, povezava, did, n.naslov)
                obdrzani.add(did)
            for did in stari - obdrzani:
                n = self._naprave.get(did)
                if n is not None and n.sosed == sosed_id and not n.posredno:
                    n.sosed = ""
                    n.povezava = None
            self._sosed_naprave[sosed_id] = obdrzani
            if relay is not None:
                cisti = {}
                for did, zz in list((relay if isinstance(relay, dict) else {}).items())[:NAJVEC_NAPRAV]:
                    did = str(did or "").strip()
                    if isinstance(zz, dict) and did and len(did) <= NAJVEC_IMENA and self._je_clan(did):
                        cisti[did] = zz
                self._zadnji_relay[sosed_id] = cisti
        self._dostavi_cakajoce(dodani)
        self._uporabi_posredne()
        self.objavi_naprave()

    def _po_spremembi_kroga(self, razen: Optional[object] = None) -> None:
        """Krog se je spremenil: lokalnim napravam trust.update, sosedom mesh.trust; umaknjeni
        clani izgubijo sosednjo povezavo in oddaljene zapise."""
        try:
            krog = link_krog.krog().json()
        except Exception:
            return
        posodobitev = json.dumps({"type": "trust.update", "payload": krog}, ensure_ascii=False)
        for n in self.povezane():
            if n.povezava is not None and not n.sosed:
                try:
                    n.povezava.poslji(posodobitev)
                except Exception:
                    pass
        mesh = json.dumps({"type": "mesh.trust", "id": link_ws.nakljucni(8), "payload": krog}, ensure_ascii=False)
        with self._zaklep:
            sosedje = list(self._sosedje.items())
        for sid, p in sosedje:
            if not self._je_clan(sid):
                self._odstrani_soseda(sid, p)
                try:
                    p.zapri(1008, "umaknjen iz kroga")
                except Exception:
                    pass
                continue
            if p is not razen:
                try:
                    p.poslji(mesh)
                except Exception:
                    pass
        with self._zaklep:
            tujci = [i for i, n in self._naprave.items() if n.sosed and not self._je_clan(i)]
            for i in tujci:
                sosed = self._naprave[i].sosed
                self._sosed_naprave.get(sosed, set()).discard(i)
                del self._naprave[i]
        self.objavi_naprave()

    def obdelaj_soseda(self, sosed_id: str, povezava, sporocilo: dict) -> Optional[str]:
        """Sporocilo sosednjega Huba. Sosed nikoli ne posreduje naprej - samo nasim lokalnim napravam."""
        tip = str(sporocilo.get("type") or "")
        tovor = sporocilo.get("payload") if isinstance(sporocilo.get("payload"), dict) else {}
        if tip == "mesh.devices":
            self._sosedove_naprave(sosed_id, povezava, tovor.get("devices"), tovor.get("relay") or {})
            return None
        if tip == "mesh.route":
            cilj = str(tovor.get("to") or "")
            msg = tovor.get("msg")
            if not isinstance(msg, str) or len(msg.encode("utf-8")) > NAJVEC_MESH_SPOROCILO:
                return None
            n = self.najdi(cilj)
            try:
                vsebina = json.loads(msg)
            except Exception:
                return None
            if not isinstance(vsebina, dict):
                return None
            posiljatelj = str(vsebina.get("sender") or "")
            if tovor.get("relay"):
                # En vmesni skok: samo napravi, ki je NEPOSREDNO pri nasem drugem sosedu, in samo v imenu
                # naprave, ki je lokalno pri sosedu, ki prosi za posredovanje. Nikoli se enkrat naprej.
                with self._zaklep:
                    njegove = set(self._sosed_naprave.get(sosed_id, set()))
                if n is None or not n.sosed or n.posredno or n.sosed == sosed_id or n.povezava is None:
                    return None
                if not posiljatelj or posiljatelj not in njegove:
                    return None
                try:
                    n.povezava.poslji(msg)
                except Exception:
                    pass
                return None
            if n is None or n.sosed or n.povezava is None:
                return None                       # samo lokalne naprave; nikoli naprej
            with self._zaklep:
                # Sosed govori v imenu svojih naprav in naprav, ki jih posreduje (relay, en skok).
                njegove = set(self._sosed_naprave.get(sosed_id, set())) | set(self._zadnji_relay.get(sosed_id, {}))
            # Sosed sme govoriti samo v imenu naprav, ki so prijavljene pri njem (ali v svojem).
            # Brez posiljatelja smejo samo obvestila Huba o seznanitvi (koda za novo napravo).
            if not posiljatelj:
                if not str(vsebina.get("type") or "").startswith("pair."):
                    return None
            elif posiljatelj not in njegove and posiljatelj != sosed_id:
                return None
            try:
                n.povezava.poslji(msg)
            except Exception:
                pass
            return None
        if tip == "mesh.trust":
            try:
                # Nov clan, drug kljuc in umik samo s podpisom clana, ki ga ze poznamo.
                spremenjeno = link_krog.krog().zdruzi(tovor, preveri_podpise=True)
            except Exception:
                spremenjeno = False
            if spremenjeno:
                self._po_spremembi_kroga(razen=povezava)
            return None
        if tip == "cast.ping":
            return json.dumps({"id": str(sporocilo.get("id") or ""), "type": "cast.pong"}, ensure_ascii=False)
        return None

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

        sosed = self._sosed_povezave(povezava)
        if sosed:
            return self.obdelaj_soseda(sosed, povezava, sporocilo)
        if tip.startswith("mesh."):
            return self._potrditev(id_sporocila, "mesh", "rejected", "Samo sosednji Hub.", "ni_sosed")

        if tip == "cast.register":
            tovor = sporocilo.get("payload")
            tovor = tovor if isinstance(tovor, dict) else {}
            if str(tovor.get("role") or "") == "hub" and MESH in (tovor.get("capabilities") or []):
                return self._sprejmi_soseda(povezava, tovor, id_sporocila)
            status, koda = self.registriraj(povezava, tovor, getattr(povezava, "podatki", {}).get("id", ""))
            if status == "accepted":
                self.objavi_naprave()
                p = povezava
                try:
                    p.poslji(json.dumps({"type": "trust.update", "payload": link_krog.krog().json()},
                                        ensure_ascii=False))
                except Exception:
                    pass
                prijavljen = str(tovor.get("device_id") or "")
                self._dostavi_klepet(prijavljen, povezava)
                kljuc = self.naprava_iz_kljuca(prijavljen)
                if kljuc and "chat" in (tovor.get("capabilities") or []):
                    self._dostavi_klepet(kljuc, povezava)
            return self._potrditev(id_sporocila, "cast", status, "" if status == "accepted" else "Prijava zavrnjena.", koda)

        if tip == "cast.ping":
            return json.dumps({"id": id_sporocila, "type": "cast.pong"}, ensure_ascii=False)

        moj_id = self.id_povezave(povezava)
        if moj_id is None:
            # Vticnica brez prijave (npr. po zamenjavi povezave): odjemalec to prepozna in se vrne.
            return self._potrditev(id_sporocila, prostor, "rejected", "Naprava ni povezana.", "naprava_ni_povezana")

        # Safeer Chat uporablja isto ze avtenticirano/podpisano sejo Linka. Meja je
        # bistveno nizja od splosne WebSocket meje, da klepet ne more izriniti nadzora.
        if tip == "chat.send":
            tovor = sporocilo.get("payload") if isinstance(sporocilo.get("payload"), dict) else {}
            besedilo = str(tovor.get("text") or tovor.get("besedilo") or "")
            if not besedilo or len(besedilo.encode("utf-8")) > 16 * 1024:
                return self._potrditev(id_sporocila, "chat", "rejected", "Sporočilo je prazno ali preveliko.", "meja")
        elif tip == "chat.list":
            tovor = sporocilo.get("payload") if isinstance(sporocilo.get("payload"), dict) else {}
            try:
                meja = int(tovor.get("limit") or 50)
            except (TypeError, ValueError):
                meja = 0
            if meja < 1 or meja > 200:
                return self._potrditev(id_sporocila, "chat", "rejected", "Neveljavna omejitev seznama.", "meja")

        cilj = str(sporocilo.get("target") or "")
        if cilj and cilj != "all":
            if cilj == moj_id:
                return self._potrditev(id_sporocila, prostor, "rejected", "Ista naprava.", "isti_naprava")
            naprava = self.najdi(cilj)
            if tip == "chat.send":
                return self._usmeri_klepet(sporocilo, id_sporocila, cilj, moj_id)
            if naprava is None or naprava.povezava is None:
                return self._potrditev(id_sporocila, prostor, "rejected", "Naprave ni na Safeer Linku.", "ni_naprave")
            sporocilo["sender"] = moj_id
            naprava.povezava.poslji(json.dumps(sporocilo, ensure_ascii=False))
            self._osvezi(moj_id)
            if tip.endswith(".result") or tip.endswith(".ack"):
                return None          # odgovorov in potrditev Hub ne potrjuje
            if prostor == "internet":
                # Tokovi Safeer Internet Gatewaya: potrditev za vsak kos bi podvojila promet in polnila vrsto
                # posiljatelja. Potrjujeta si napravi sami (internet.window); Hub javi samo zavrnitev.
                return None
            return self._potrditev(id_sporocila, prostor, "accepted")

        if tip == "trust.names":
            # Naprava ponudi imena iz svojega kroga; hub vzame samo imena znanih clanov z istim kljucem.
            tovor = sporocilo.get("payload")
            try:
                spremenjeno = link_krog.krog().zdruzi_imena(tovor if isinstance(tovor, dict) else {})
            except Exception:
                spremenjeno = False
            if spremenjeno:
                self._po_spremembi_kroga()
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
        if koda >= 400:
            self._sovrazno(link_obramba.vrsta_napake(koda, str(telo.get("error_code") or telo.get("code") or "")))

    # ------------------------------------------------------------------ obramba
    def _vir(self) -> str:
        return self.client_address[0] if self.client_address else ""

    def _sovrazno(self, vrsta: str) -> None:
        """Sovrazen dogodek tega vira (core/link_obramba): zavrnjen podpis, tipanje poti, ugibanje kode ..."""
        obramba = getattr(self.server, "obramba", None)
        if obramba is not None and vrsta:
            obramba.dogodek(self._vir(), vrsta)

    def _zaupaj(self) -> None:
        """Vir se je izkazal kot clan kroga (veljaven podpis, vstopnica ali zeton)."""
        obramba = getattr(self.server, "obramba", None)
        if obramba is not None:
            obramba.zaupaj(self._vir())

    def _lastnik_zetona(self):
        """Naprava, ki ji pripada zeton v glavi (id, ime), ali None. Veljaven zeton pomeni zaupan vir."""
        lastnik = self._hub.naprava_zetona(self.headers.get("X-Safeer-Token") or "")
        if lastnik:
            self._zaupaj()
        return lastnik

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
        if pot.startswith(POT_DATOTEKE):
            self._datoteka(pot, samo_glava=False)
            return
        if pot.startswith(POT_PREVZEM):
            self._prevzem_datoteke(pot)
            return
        if pot in ("/cast/devices", "/cast/trust/ring"):
            # Seznam naprav in krog zaupanja (kljuci, imena, kdo je koga dodal) dobijo samo prijavljene
            # naprave, po WebSocketu (cast.devices, trust.update). Po HTTP ju ta Hub ne daje nikomur:
            # zetonov za HTTP (se) ne izdaja, brez zetona pa ju ne da niti Hub na televizorju.
            self._napaka(401, "Naprava ni seznanjena.", "naprava_ni_seznanjena")
            return
        if pot in ("/cast/ticket", "/cast/pair/start", "/cast/pair/spake", "/cast/pair/finish",
                   "/cast/pair/cancel", "/cast/pair/sibling", "/cast/trust/enroll", "/cast/devices/leave",
                   "/cast/pair/qr/join", "/cast/pair/qr/invite", "/cast/pair/qr/invite/status",
                   "/cast/pair/qr/invite/cancel", "/cast/pair/qr/odprto",
                   "/cast/pair/qr/start", "/cast/pair/qr/info", "/cast/pair/qr/approve",
                   "/cast/pair/qr/status", "/cast/pair/qr/cancel", POT_BESEDILO, POT_ODDAJA, POT_PREIMENUJ):
            # Pot obstaja, a ne kot GET. Po tem naprava loci Safeer Hub od poljubnega streznika.
            self._napaka(405, "Ta način za to pot ni dovoljen.", "metoda_ni_dovoljena")
            return
        self._napaka(404, "Ni te poti.", "ni_poti")

    def do_HEAD(self) -> None:
        pot = urlparse(self.path).path
        if self._je_krajevni() and pot.startswith(POT_DATOTEKE):
            self._datoteka(pot, samo_glava=True)
            return
        # HEAD nima telesa (HTTP/1.1).
        self.send_response(403 if not self._je_krajevni() else 404)
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    def _datoteka(self, pot: str, samo_glava: bool) -> None:
        """Deljena datoteka prek Huba (Global Link: rele pripelje samo do vrat Huba). Isti zeton in
        ista pravila kot streznik datotek (core/link_datoteke.postrezi_datoteko)."""
        dobi = getattr(self.server, "datoteke", None)
        streznik = dobi() if callable(dobi) else None
        if isinstance(streznik, (list, tuple)):
            # Vec streznikov (npr. Windows: loceno za omejen dostop in za cel disk): tisti, ki pozna zeton.
            z = (self.headers.get("X-Safeer-Token") or "").strip()
            streznik = next((s for s in streznik if s is not None and s.zeton_velja(z)), None) or \
                next((s for s in streznik if s is not None), None)
        if streznik is None:
            self._napaka(404, "Ta naprava ne deli datotek.", "ni_datotek")
            return
        # Zeton preveri postrezi_datoteko; obramba mora izvedeti izid (odgovor ne gre skozi _odgovori).
        z = (self.headers.get("X-Safeer-Token") or "").strip()
        if z and streznik.zeton_velja(z):
            self._zaupaj()
        else:
            self._sovrazno("brez_zaupanja")
        from urllib.parse import unquote
        from core import link_datoteke
        link_datoteke.postrezi_datoteko(self, streznik, unquote(pot[len(POT_DATOTEKE):]), samo_glava)

    # ------------------------------------------------------------------ deljenje: datoteka
    def _prevzem_datoteke(self, pot: str) -> None:
        """GET /cast/file/<id>?k=<kljuc>: ciljna naprava prevzame datoteko, ki ji jo je napovedal share.file."""
        zaloga = self._hub.deljenje
        kljuc = (parse_qs(urlparse(self.path).query).get("k") or [""])[0]
        d = zaloga.najdi(pot[len(POT_PREVZEM):].split("/")[0], kljuc)
        if d is None:
            self._odgovori(404, link_hub_deljenje.napaka("Te datoteke ni.", "ni_datoteke"))
            return
        if not zaloga.zacni_prevzem():
            self._odgovori(503, link_hub_deljenje.napaka("Preveč hkratnih prenosov.", "prevec_prenosov"))
            return
        cela = False
        try:
            with open(d.pot, "rb") as vhod:
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(d.velikost))
                self.send_header("x-safeer-sha256", d.sha256)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                poslano = 0
                while True:
                    kos = vhod.read(link_hub_deljenje.KOS)
                    if not kos:
                        break
                    self.wfile.write(kos)
                    poslano += len(kos)
                self.wfile.flush()
                cela = poslano == d.velikost
        except Exception:  # noqa: BLE001 - cilj je prekinil prevzem; datoteka pocaka na nov poskus
            self.close_connection = True
        finally:
            zaloga.koncaj_prevzem(d, cela)

    def _zavrzi_telo(self) -> None:
        """Pred odgovorom z napako: majhno telo preberemo (odjemalec ga se posilja), pri velikem zapremo povezavo."""
        try:
            dolzina = int(self.headers.get("Content-Length") or 0)
        except Exception:
            dolzina = -1
        if dolzina < 0 or dolzina > NAJVEC_ZAVRZENEGA:
            self.close_connection = True
            return
        try:
            ostalo = dolzina
            while ostalo > 0:
                kos = self.rfile.read(min(link_hub_deljenje.KOS, ostalo))
                if not kos:
                    break
                ostalo -= len(kos)
        except Exception:
            self.close_connection = True

    def do_PUT(self) -> None:
        """PUT /cast/file?name=&target=: naprava odda datoteko za drugo napravo; cilju pove Hub (share.file)."""
        u = urlparse(self.path)
        if not self._je_krajevni():
            self._zavrzi_telo()
            self._napaka(403, "Safeer Link deluje samo v krajevnem omrežju.", "samo_krajevno")
            return
        if u.path != POT_ODDAJA:
            self._zavrzi_telo()
            self._napaka(404, "Ni te poti.", "ni_poti")
            return
        hub = self._hub
        lastnik = self._lastnik_zetona()
        if not lastnik:
            self._zavrzi_telo()
            self._odgovori(401, link_hub_deljenje.napaka("Naprava ni seznanjena.", "naprava_ni_seznanjena"))
            return
        posiljatelj, ime_posiljatelja = lastnik
        q = parse_qs(u.query)
        ime = link_hub_deljenje.varno_ime((q.get("name") or [""])[0])
        cilj = (q.get("target") or [""])[0].strip()[:NAJVEC_IMENA]
        try:
            dolzina = int(self.headers.get("Content-Length") or -1)
        except Exception:
            dolzina = -1
        zavrnjeno = hub.cilj_deljenja(cilj, posiljatelj, datoteka=True) if cilj else None
        if zavrnjeno is not None:
            self._zavrzi_telo()
            self._odgovori(zavrnjeno[0], link_hub_deljenje.napaka(zavrnjeno[1], zavrnjeno[2]))
            return
        vnaprej = hub.deljenje.preveri(ime, cilj, dolzina)
        if vnaprej is not None:
            self._zavrzi_telo()
            self._odgovori(vnaprej[0], vnaprej[1])
            return
        koda, odgovor, d = hub.deljenje.sprejmi(self.rfile, dolzina, ime, cilj, posiljatelj,
                                               self.headers.get("x-safeer-sha256") or "")
        if d is None:
            self.close_connection = True      # telo morda ni prebrano do konca
        else:
            # Ce je cilj medtem odsel, datoteka pocaka na Hubu (eno uro); posiljatelj je svoje opravil.
            hub.posreduj_deljenje("share.file", posiljatelj, cilj, d.tovor(), ime_posiljatelja)
        self._odgovori(koda, odgovor)

    # ------------------------------------------------------------------ POST
    def do_POST(self) -> None:
        pot = urlparse(self.path).path
        if not self._je_krajevni():
            self._napaka(403, "Safeer Link deluje samo v krajevnem omrežju.", "samo_krajevno")
            return
        if pot == POT_PREIMENUJ:
            telo = self._telo()
            koda, odgovor = self._hub.preimenuj_napravo(self.headers.get("X-Safeer-Token") or "",
                                                        str(telo.get("device_id") or ""), str(telo.get("name") or ""))
            self._odgovori(koda, odgovor)
            return
        if pot == POT_BESEDILO:
            telo = self._telo()
            koda, odgovor = self._hub.deli_besedilo(self.headers.get("X-Safeer-Token") or "",
                                                    str(telo.get("target") or ""), str(telo.get("text") or ""))
            self._odgovori(koda, odgovor)
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
            self._zaupaj()
            self._odgovori(200, odgovor)
            return
        if pot == "/cast/ticket":
            # Samo zeton iz seznanitve na tem hubu (prva prijava nove naprave); sicer podpis.
            odgovor = self._hub.vstopnica_z_zetonom(self.headers.get("X-Safeer-Token") or "")
            if odgovor is None:
                self._napaka(401, "Naprava ni seznanjena.", "naprava_ni_seznanjena")
                return
            self._zaupaj()
            self._odgovori(200, odgovor)
            return
        if pot == "/cast/pair/sibling":
            telo = self._telo()
            zeton, napaka = self._hub.sorodni_zeton(
                self.headers.get("X-Safeer-Token") or "", str(telo.get("device_id") or ""),
                str(telo.get("name") or ""))
            if zeton is None:
                kodi = {"naprava_ni_seznanjena": 401, "manjka_device_id": 400, "ni_sorodnik": 403}
                self._napaka(kodi.get(napaka or "", 400), "Sorodne naprave ni mogoče povezati.", napaka or "napaka")
                return
            self._odgovori(200, {"token": zeton, "hub_id": IDENTITETA_HUBA, "fp": self._hub.odtis})
            return
        if pot == "/cast/devices/leave":
            idji = self._hub.odidi(self.headers.get("X-Safeer-Token") or "")
            if idji is None:
                self._napaka(401, "Naprava ni seznanjena.", "naprava_ni_seznanjena")
                return
            self._odgovori(200, {"left": True, "count": len(idji)})
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
        if pot == "/cast/pair/qr/odprto":
            # Ali ta naprava ravno kaze 6-mestno kodo: naprava, kamor jo uporabnik vtipka, po tem izbere
            # pravo sredisce (z Link Mesh ima Hub vsaka naprava). Koda sama ne gre po omrezju.
            self._odgovori(200, {"open": self._hub.ima_odprto_kodo()})
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
        if pot in ("/cast/pair/qr/invite", "/cast/pair/qr/invite/status", "/cast/pair/qr/invite/cancel"):
            if not self._lastnik_zetona():
                self._napaka(401, "Naprava ni seznanjena.", "naprava_ni_seznanjena")
                return
            telo = self._telo()
            qr_id = str(telo.get("qr_id") or "").strip()
            if pot == "/cast/pair/qr/invite":
                if qr_id:
                    self._hub.preklici_pridruzitev(qr_id)
                nov_id, skrivnost = self._hub.ustvari_pridruzitev()
                pin = self._hub.pin_pridruzitve(nov_id)
                # address: naslov sredisca v domacem omrezju. Naprava, ki vabi, se nanj lahko poveze
                # prek 127.0.0.1 (svoj Hub) - tega naslova nova naprava ne sme dobiti v QR kodi.
                self._odgovori(200, {"qr_id": nov_id, "secret": skrivnost, "fp": self._hub.odtis,
                                     "pin": pin, "code": pin, "address": self._hub.naslov_za_qr,
                                     "expires_in_seconds": int(PIN_VELJA_S), "web_port": 0})
                return
            if pot.endswith("/status"):
                self._odgovori(200, self._hub.stanje_pridruzitve(qr_id))
                return
            self._hub.preklici_pridruzitev(qr_id)
            self._odgovori(200, {"cancelled": True})
            return
        if pot == "/cast/pair/qr/start":
            telo = self._telo()
            device_id = str(telo.get("device_id") or "").strip()[:NAJVEC_IMENA]
            if not device_id:
                self._napaka(400, "Manjka device_id.", "manjka_device_id")
                return
            qr_id, napaka = self._hub.zacni_qr(device_id, str(telo.get("name") or ""),
                                              str(telo.get("platform") or ""),
                                              str(telo.get("secret_sha256") or ""),
                                              str(telo.get("poll_secret") or ""))
            if not qr_id:
                koda = 429 if napaka == "prevec_prijav" else 400
                self._napaka(koda, "Prijava ni mogoča.", napaka or "napaka")
                return
            self._sovrazno("seznanitev")
            self._odgovori(200, {
                "qr_id": qr_id,
                "hub_id": IDENTITETA_HUBA,
                "fp": self._hub.odtis,
                "expires_in_seconds": int(PIN_VELJA_S)
            })
            return
        if pot in ("/cast/pair/qr/info", "/cast/pair/qr/approve"):
            odobril = self._lastnik_zetona()
            if not odobril:
                self._napaka(401, "Naprava ni seznanjena.", "naprava_ni_seznanjena")
                return
            telo = self._telo()
            qr_id = str(telo.get("qr_id") or "").strip()
            skrivnost = str(telo.get("secret") or "").strip()
            if not qr_id or not skrivnost:
                self._napaka(400, "Koda ne obstaja.", "qr_ne_obstaja")
                return
            if pot.endswith("/info"):
                podatki, napaka = self._hub.qr_podatki(qr_id, skrivnost)
            else:
                podatki, napaka = self._hub.odobri_qr(qr_id, skrivnost, odobril[0])
            if not podatki:
                koda = 429 if napaka == "prevec_poskusov" else 404
                self._napaka(koda, "Koda ne velja več.", napaka or "qr_ne_obstaja")
                return
            if pot.endswith("/approve"):
                podatki["approved"] = True
            self._odgovori(200, podatki)
            return
        if pot == "/cast/pair/qr/status":
            telo = self._telo()
            stanje, zeton = self._hub.prevzemi_qr(str(telo.get("qr_id") or ""),
                                                  str(telo.get("device_id") or ""),
                                                  str(telo.get("poll_secret") or ""))
            if stanje == "qr_ne_obstaja":
                self._napaka(404, "Koda ne obstaja več.", "qr_ne_obstaja")
                return
            izid = {"approved": bool(zeton)}
            if zeton:
                izid["token"] = zeton
                izid["hub_id"] = IDENTITETA_HUBA
                izid["fp"] = self._hub.odtis
            self._odgovori(200, izid)
            return
        if pot == "/cast/pair/qr/cancel":
            telo = self._telo()
            ok = self._hub.preklici_qr(str(telo.get("qr_id") or ""),
                                       str(telo.get("device_id") or ""),
                                       str(telo.get("poll_secret") or ""))
            self._odgovori(200, {"cancelled": ok})
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
            if odgovor.get("napaka") == "seznanitev_zaprta":
                self._napaka(429, BESEDILO_KODA_ZAPRTA, "seznanitev_zaprta")
                return
            # Vsak zacetek uporabniku pokaze obvestilo s kodo: cetrti v minuti vir zapre.
            self._sovrazno("zacetek_seznanitve")
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
                     "seznanitev_zaprta": (429, BESEDILO_KODA_ZAPRTA),
                     "manjka_korak": (409, "Najprej pošljite pb.")}
        if pot == "/cast/pair/spake":
            pa, ca, napaka = self._hub.spake_korak1(pair_id, device_id, podatki)
            if pa is None:
                koda, besedilo = sporocila.get(napaka or "", (409, "Seznanitev ni mogoča."))
                self._napaka(koda, besedilo, napaka or "seznanitev_ni_mogoca")
                return
            # Odgovor napravi pove, ali je njena koda prava (potrditev sredisca): vsak krog je poskus kode.
            self._sovrazno("poskus_kode")
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
        device_id, s_podpisom = self._hub.porabi_vstopnico_s_podpisom(vstopnica)
        if not device_id:
            self._napaka(401, "Neveljavna ali potekla vstopnica.", "ni_vstopnice")
            return
        self._zaupaj()
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
        povezava.podatki["podpis"] = s_podpisom
        povezava.zanka_branja()


def _na_sporocilo(hub: "Hub", povezava, surovo: str) -> None:
    odgovor = hub.obdelaj(povezava, surovo)
    if odgovor:
        povezava.poslji(odgovor)
    if getattr(povezava, "podatki", {}).get("zapri_po_odgovoru"):
        povezava.zapri(1008, "zavrnjeno")


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


def besedilo_kode(ime: str, koda: str, slovensko: bool) -> tuple:
    """(naslov, besedilo) obvestila s kodo za novo napravo - loceno, da je preizkusljivo."""
    ime = " ".join(str(ime or "").split())[:40]
    if slovensko:
        return ("Safeer Link: nova naprava", "%s se želi povezati. Vpiši kodo %s %s" % (ime, koda[:3], koda[3:]))
    return ("Safeer Link: new device", "%s wants to connect. Enter the code %s %s" % (ime, koda[:3], koda[3:]))


#: Program z oknom (Safeer OS za Windows) se tu prijavi, da kodo nove naprave pokaze sam: fn(ime, koda).
POSLUSALCI_KODE: List[Callable[[str, str], None]] = []
#: Jezik obvestil, kadar ga doloca program (Safeer OS za Windows ima svoj jezik vmesnika): "sl", "en" ...;
#: None = jezik seje oziroma sistema.
JEZIK_OBVESTIL: Optional[str] = None


def _obvestilo_kode(ime: str, koda: str) -> None:
    """Koda za novo napravo tudi na racunalniku (Link je lahko brez televizorja): najprej v odprtih oknih programa
    (poslusalci), nato obvestilo namizja."""
    for poslusalec in list(POSLUSALCI_KODE):
        try:
            poslusalec(ime, koda)
        except Exception:
            pass
    _obvestilo(*besedilo_kode(ime, koda, _slovensko()), cas_ms=int(PIN_VELJA_S * 1000))


def _slovensko() -> bool:
    """Jezik obvestil: ki ga je nastavil program (JEZIK_OBVESTIL), sicer jezik seje po istem vrstnem redu kot Control
    (LANGUAGE, LC_ALL, LC_MESSAGES, LANG), na Windows jezik prikaza."""
    if JEZIK_OBVESTIL:
        return str(JEZIK_OBVESTIL).strip().lower().startswith("sl")
    for kljuc in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        vrednost = (os.environ.get(kljuc) or "").strip().lower()
        if vrednost and vrednost not in ("c", "posix"):
            return vrednost.startswith("sl")
    if sys.platform == "win32":
        try:
            import ctypes
            # Primarni jezik prikaza Windows: spodnjih 10 bitov oznake jezika; 0x24 = slovenscina.
            return (int(ctypes.windll.kernel32.GetUserDefaultUILanguage()) & 0x3FF) == 0x24
        except Exception:
            return False
    return False


#: Gumbi na obvestilih: stevilka obvestila -> {kljuc dejanja: klic}. Pritisk sporoci obvestilni streznik s signalom
#: ActionInvoked; poslusamo ga enkrat na proces (v glavni zanki GLib - program brez nje gumbov nima).
_dejanja: Dict[int, Dict[str, Callable[[], None]]] = {}
_dejanja_zaklep = threading.Lock()
_dejanja_narocena = False
#: Povezava z vodilom seje, na kateri poslusamo pritiske gumbov. Drzimo jo, dokler proces zivi: Gio.bus_get_sync vrne
#: skupno povezavo, ki se zapre, ko jo spusti zadnji lastnik - z njo bi tiho izginilo tudi narocilo na signal.
_vodilo_dejanj = None
NAJVEC_OBVESTIL_Z_GUMBI = 32


def _zapomni_dejanja(stevilka: int, klici: Dict[str, Callable[[], None]]) -> None:
    with _dejanja_zaklep:
        while len(_dejanja) >= NAJVEC_OBVESTIL_Z_GUMBI:
            _dejanja.pop(next(iter(_dejanja)), None)
        _dejanja[int(stevilka)] = dict(klici)


def _ob_signalu_obvestila(_vodilo, _posiljatelj, _pot, _vmesnik, signal, parametri, *_ostalo) -> None:
    """ActionInvoked(stevilka, kljuc): izvede dejanje gumba.

    Signala NotificationClosed ne poslusamo: namizje ga poslje ze, ko oblacek obvestila izgine, obvestilo pa z
    gumbom ostane v pladnju - gumb bi bil takrat mrtev (videno v Cinnamonu). Gumbi se pozabijo ob pritisku ali ko jih
    izrine novejse obvestilo; pritisk na gumb stare zapore ne naredi nicesar (vir ni vec zaprt).
    """
    if signal != "ActionInvoked":
        return
    try:
        stevilka, kljuc = parametri.unpack()
    except Exception:
        return
    with _dejanja_zaklep:
        klici = _dejanja.pop(int(stevilka), None)
    klic = (klici or {}).get(str(kljuc))
    if klic is None:
        return
    try:
        klic()
    except Exception as e:  # noqa: BLE001 - gumb obvestila ne sme podreti glavne zanke
        print("[SafeerLink] dejanje obvestila ni uspelo:", e, flush=True)


def _naroci_dejanja(vodilo) -> None:
    global _dejanja_narocena, _vodilo_dejanj
    if _dejanja_narocena:
        return
    from gi.repository import Gio
    vodilo.signal_subscribe("org.freedesktop.Notifications", "org.freedesktop.Notifications", "ActionInvoked",
                            "/org/freedesktop/Notifications", None, Gio.DBusSignalFlags.NONE, _ob_signalu_obvestila)
    _vodilo_dejanj = vodilo
    _dejanja_narocena = True


def _obvestilo_dbus(naslov: str, besedilo: str, cas_ms: int, dejanja: Optional[list] = None) -> bool:
    """Obvestilo po D-Busu (org.freedesktop.Notifications): brez orodja notify-send, ki ga paket ne zahteva.

    `dejanja`: [(kljuc, napis, klic)] - gumbi na obvestilu."""
    try:
        from gi.repository import Gio, GLib
        vodilo = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        gumbi: List[str] = []
        for kljuc, napis, _klic in dejanja or []:
            gumbi += [str(kljuc), str(napis)]
        if gumbi:
            _naroci_dejanja(vodilo)
        odgovor = vodilo.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                                   "org.freedesktop.Notifications", "Notify",
                                   GLib.Variant("(susssasa{sv}i)", ("Safeer Control", 0, "safeer-control", naslov, besedilo, gumbi, {}, int(cas_ms))),
                                   GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, 3000, None)
        if gumbi:
            _zapomni_dejanja(int(odgovor.unpack()[0]), {str(kljuc): klic for kljuc, _napis, klic in dejanja or []})
        return True
    except Exception:
        return False


def _obvestilo_windows(naslov: str, besedilo: str) -> bool:
    """Obvestilo v kotu zaslona na Windows (PowerShell, brez dodatnih modulov). Besedilo gre v okolje, ne v ukaz."""
    import subprocess
    from xml.sax.saxutils import escape
    xml = ("<toast duration='long'><visual><binding template='ToastGeneric'><text>%s</text><text>%s</text>"
           "</binding></visual></toast>") % (escape(naslov), escape(besedilo))
    skripta = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] | Out-Null;"
        "$x = New-Object Windows.Data.Xml.Dom.XmlDocument; $x.LoadXml($env:SAFEER_TOAST);"
        "$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe';"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show("
        "[Windows.UI.Notifications.ToastNotification]::new($x))"
    )
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", skripta],
                         env=dict(os.environ, SAFEER_TOAST=xml), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except Exception:
        return False


def _obvestilo(naslov: str, besedilo: str, cas_ms: int = 15000, dejanja: Optional[list] = None) -> None:
    """Obvestilo namizja; sredisce tece v ozadju, uporabnik drugace ne izve. V svoji niti: sredisce ne caka nanj.

    `dejanja`: [(kljuc, napis, klic)] - gumbi (samo po D-Busu; notify-send in obvestilo Windows jih nimata)."""
    def poslji() -> None:
        if sys.platform == "win32":
            _obvestilo_windows(naslov, besedilo)
            return
        if _obvestilo_dbus(naslov, besedilo, cas_ms, dejanja):
            return
        import shutil
        import subprocess
        if not shutil.which("notify-send"):
            return
        try:
            subprocess.Popen(["notify-send", "-a", "Safeer Control", "-i", "safeer-control", "-t", str(int(cas_ms)), naslov, besedilo],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    threading.Thread(target=poslji, name="safeer-obvestilo", daemon=True).start()


def besedilo_zapore(vir: str, trajanje_s: float, razlog: str, slovensko: bool, ime: str = "") -> tuple:
    """(naslov, besedilo) obvestila ob zapori vira - loceno, da je preizkusljivo. `ime`: naprava, ki jo sredisce pozna
    s tega naslova - potem je to najbrz uporabnikova naprava s pokvarjeno prijavo, ne tujec."""
    minut = max(1, int(round(trajanje_s / 60.0)))
    ime = " ".join(str(ime or "").split())[:40]
    if ime:
        if slovensko:
            return ("Safeer Link: naprava ustavljena",
                    "»%s« (%s) se prijavlja narobe. Za %d min je ne poslušam. Če je tvoja, jo potem v Safeer Linku poveži znova."
                    % (ime, vir, minut))
        return ("Safeer Link: device stopped",
                "\u201c%s\u201d (%s) keeps signing in incorrectly. I will not listen to it for %d min. If it is yours, connect it again in Safeer Link afterwards."
                % (ime, vir, minut))
    if slovensko:
        kaj = {"seznanitev": "je ugibala kodo za povezavo", "zacetek_seznanitve": "se je vsiljevala v Safeer Link",
               "poskus_kode": "je ugibala kodo za povezavo",
               "brez_zaupanja": "se je prijavljala brez dovoljenja",
               "povezava": "je odpirala preveč povezav", "rokovanje": "je tipala vrata Safeer Linka",
               "tipanje": "je tipala po Safeer Linku", "okvir": "je pošiljala pokvarjena sporočila"}.get(razlog, "se je vedla sumljivo")
        return ("Safeer Link: naprava ustavljena",
                "Naprava z naslova %s %s. Za %d min je ne poslušam več. Tvoje naprave delajo naprej." % (vir, kaj, minut))
    kaj = {"seznanitev": "was guessing the pairing code", "zacetek_seznanitve": "kept asking to join Safeer Link",
           "poskus_kode": "was guessing the pairing code",
           "brez_zaupanja": "kept signing in without permission",
           "povezava": "was opening too many connections", "rokovanje": "was probing the Safeer Link port",
           "tipanje": "was probing Safeer Link", "okvir": "was sending broken messages"}.get(razlog, "behaved suspiciously")
    return ("Safeer Link: device stopped",
            "The device at %s %s. I will not listen to it for %d min. Your devices keep working." % (vir, kaj, minut))


def _trajanje(sekund: float, slovensko: bool) -> str:
    """»1 uro«, »1 dan«, »7 dni« (tozilnik) oziroma »1 hour«, »1 day«, »7 days«."""
    ur = max(1, int(round(sekund / 3600.0)))
    if ur < 24:
        if slovensko:
            return "%d %s" % (ur, "uro" if ur == 1 else "uri" if ur == 2 else "ure" if ur in (3, 4) else "ur")
        return "%d %s" % (ur, "hour" if ur == 1 else "hours")
    dni = max(1, int(round(ur / 24.0)))
    if slovensko:
        return "%d %s" % (dni, "dan" if dni == 1 else "dneva" if dni == 2 else "dni")
    return "%d %s" % (dni, "day" if dni == 1 else "days")


def besedilo_zapore_kode(dogodek: dict, slovensko: bool, imena: Optional[dict] = None) -> tuple:
    """(naslov, besedilo) obvestila, ko varovalka zapre povezovanje s kodo. `imena`: naslov -> ime naprave, ki jo
    sredisce pozna s tega naslova."""
    trajanje = _trajanje(float(dogodek.get("trajanje_s") or 0.0), slovensko)
    viri = []
    for vir, _stevilo in (dogodek.get("viri") or [])[:3]:
        ime = " ".join(str((imena or {}).get(vir) or "").split())[:40]
        viri.append("%s (%s)" % (ime, vir) if ime else str(vir))
    if slovensko:
        kaj = "Nekdo je ugibal kodo za povezavo" if dogodek.get("razlog") == "kode" \
            else "Nekdo je znova in znova začenjal povezovanje"
        od_kod = (" (%s)" % ", ".join(viri)) if viri else ""
        return ("Safeer Link: povezovanje s kodo je zaprto",
                "%s%s. Povezovanje s kodo je zaprto za %s. Novo napravo povežeš tako, da na eni od svojih naprav "
                "odpreš »Poveži naprave«, ali s kodo QR. Tvoje naprave delajo naprej." % (kaj, od_kod, trajanje))
    kaj = "Someone was guessing the pairing code" if dogodek.get("razlog") == "kode" \
        else "Someone kept starting to pair over and over"
    od_kod = (" (%s)" % ", ".join(viri)) if viri else ""
    return ("Safeer Link: pairing by code is closed",
            "%s%s. Pairing by code is closed for %s. To add a device, open \u201cConnect devices\u201d on one of "
            "your devices, or use the QR code. Your devices keep working." % (kaj, od_kod, trajanje))


def besedilo_sprostitve(kdo: str, slovensko: bool) -> tuple:
    """(naslov, besedilo) potrditve, ko uporabnik ustavljeno napravo sprosti z gumbom na obvestilu."""
    kdo = " ".join(str(kdo or "").split())[:60]
    if slovensko:
        return ("Safeer Link: naprava sproščena", "%s je sproščena. Spet se lahko poveže." % kdo)
    return ("Safeer Link: device released", "%s is released. It can connect again." % kdo)


def besedilo_odprtja_kode(slovensko: bool) -> tuple:
    if slovensko:
        return ("Safeer Link: povezovanje s kodo je odprto", "Povezovanje s kodo je spet odprto. Naslednja zapora bo daljša.")
    return ("Safeer Link: pairing by code is open", "Pairing by code is open again. The next closure will last longer.")


def besedilo_napada(viri: list, slovensko: bool) -> tuple:
    if slovensko:
        return ("Safeer Link: napad v domačem omrežju",
                "Ustavljene naprave: %s. Preveri, kdo je v tvojem omrežju (gostje, neznane naprave)." % ", ".join(viri[:6]))
    return ("Safeer Link: attack in the home network",
            "Stopped devices: %s. Check who is in your network (guests, unknown devices)." % ", ".join(viri[:6]))


def nastavitve_vticnika(sistem: str = os.name) -> tuple:
    """(deli naslov [SO_REUSEADDR], izkljucna raba [SO_EXCLUSIVEADDRUSE]) za vticnik sredisca na danem sistemu.

    Linux: SO_REUSEADDR pomeni samo, da vrata dobimo tudi takoj po ponovnem zagonu (stare povezave v TIME_WAIT jih ne
    drzijo); na vrata, kjer kdo poslusa, se ne da vezati. Windows: ista nastavitev pomeni, da si vrata DELIMO z drugim
    procesom - vezava na 8990 je uspela, ceprav jih je drzal drug program (izmerjeno 5. 10. 2026), povezave pa je
    dobival tisti. Tam zato brez deljenja in z izkljucno rabo, ki tudi drugim prepreci, da bi se vezali na nasa vrata.
    """
    windows = sistem == "nt"
    return (not windows), windows


class _Streznik(link_tls.RokovanjeVNiti, http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = nastavitve_vticnika()[0]

    def server_bind(self) -> None:
        izkljucno = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if nastavitve_vticnika()[1] and izkljucno is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, izkljucno, 1)
        super().server_bind()

    #: Obrambni mehanizem (core/link_obramba.Obramba) ali None.
    obramba = None

    def verify_request(self, request, client_address) -> bool:
        """Zaprt vir ne pride niti do rokovanja TLS: povezava se zapre brez potrdila in brez odgovora."""
        obramba = self.obramba
        if obramba is None:
            return True
        return obramba.dovoli(client_address[0] if client_address else "")

    def ob_neuspelem_rokovanju(self, client_address) -> None:
        if self.obramba is not None:
            self.obramba.dogodek(client_address[0] if client_address else "", "rokovanje")

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
        #: Streznik datotek (core/link_datoteke.StreznikDatotek ali funkcija, ki ga vrne) za tok prek
        #: Huba (/cast/d/<id>); None = ta naprava datotek ne deli.
        self.datoteke = None
        self._streznik: Optional[_Streznik] = None
        self._nit: Optional[threading.Thread] = None
        self._zaklep = threading.Lock()
        #: Obrambni mehanizem: zivi dlje kot streznik (zapora velja tudi po ponovnem zagonu sredisca v istem procesu).
        self.obramba = link_obramba.Obramba(ob_zapori=self._ob_zapori, ob_napadu=self._ob_napadu,
                                            ob_opozorilu=self._ob_opozorilu)
        #: Povratna klica za vmesnik: (vir, trajanje_s, razlog) in (seznam virov).
        self.ob_zapori: Optional[Callable[[str, float, str], None]] = None
        self.ob_napadu: Optional[Callable[[List[str]], None]] = None
        #: Varovalka je zaprla povezovanje s kodo (dogodek link_varovalka).
        self.ob_zapori_kode: Optional[Callable[[dict], None]] = None

    def tece(self) -> bool:
        return self._streznik is not None

    @staticmethod
    def _sestava(teze: dict) -> str:
        return ", ".join("%s %d" % (k, v) for k, v in sorted(teze.items(), key=lambda kv: -kv[1]))

    def _ob_opozorilu(self, vir: str, vsota: int, teze: dict) -> None:
        """Vir je na polovici praga: samo v dnevnik (ce je to uporabnikova naprava, se tu vidi, kaj pocne)."""
        print("[SafeerLink] obramba: %s na %d od %d (%s)" % (vir, vsota, link_obramba.PRAG, self._sestava(teze)), flush=True)

    def _ob_zapori(self, vir: str, trajanje_s: float, razlog: str) -> None:
        sestava = ""
        try:
            sestava = self._sestava(next((z["sestava"] for z in self.obramba.stanje()["zaprti"] if z["vir"] == vir), {}))
        except Exception:
            pass
        logging.getLogger("safeer.link").warning("obramba: vir %s zaprt za %d s (%s)", vir, int(trajanje_s), sestava or razlog)
        print("[SafeerLink] obramba: %s zaprt za %d min (%s)" % (vir, int(trajanje_s // 60), sestava or razlog), flush=True)
        ime = ""
        try:
            ime = self.hub.ime_po_naslovu(vir) if self.hub is not None else ""
        except Exception:
            pass
        slovensko = _slovensko()
        _obvestilo(*besedilo_zapore(vir, trajanje_s, razlog, slovensko, ime),
                   dejanja=[("sprosti", "Sprosti" if slovensko else "Release", lambda: self.sprosti_vir(vir, ime))])
        if self.ob_zapori is not None:
            try:
                self.ob_zapori(vir, trajanje_s, razlog)
            except Exception:
                pass

    def sprosti_vir(self, vir: str, ime: str = "") -> bool:
        """Uporabnik je ustavljeno napravo sprostil sam (gumb na obvestilu)."""
        sproscen = self.obramba.sprosti(vir)
        print("[SafeerLink] obramba: %s %s" % (vir, "sproščen (uporabnik)" if sproscen else "ni bil zaprt"), flush=True)
        if sproscen:
            _obvestilo(*besedilo_sprostitve("»%s« (%s)" % (ime, vir) if ime else vir, _slovensko()))
        return sproscen

    def odpri_povezovanje_s_kodo(self) -> bool:
        """Uporabnik je povezovanje s kodo odprl sam (gumb na obvestilu). Stetje ponovitev ostane."""
        hub = self.hub
        if hub is None or not hub.varovalka.zaprto():
            return False
        hub.varovalka.odpri()
        print("[SafeerLink] varovalka: povezovanje s kodo odprto (uporabnik)", flush=True)
        _obvestilo(*besedilo_odprtja_kode(_slovensko()))
        return True

    def _ob_zapori_kode(self, dogodek: dict) -> None:
        """Varovalka je zaprla povezovanje s kodo (skupna meja, ne po viru)."""
        viri = [str(v) for v, _n in (dogodek.get("viri") or [])]
        logging.getLogger("safeer.link").warning("varovalka: povezovanje s kodo zaprto za %d s (%s; viri: %s)",
                                                 int(dogodek.get("trajanje_s") or 0), dogodek.get("razlog"), ", ".join(viri))
        print("[SafeerLink] varovalka: povezovanje s kodo zaprto za %d min (%s; viri: %s)"
              % (int((dogodek.get("trajanje_s") or 0) // 60), dogodek.get("razlog"), ", ".join(viri) or "-"), flush=True)
        imena = {}
        for vir in viri:
            try:
                imena[vir] = self.hub.ime_po_naslovu(vir) if self.hub is not None else ""
            except Exception:
                pass
        slovensko = _slovensko()
        _obvestilo(*besedilo_zapore_kode(dogodek, slovensko, imena), cas_ms=60000,
                   dejanja=[("odpri", "Odpri povezovanje s kodo" if slovensko else "Open pairing by code", self.odpri_povezovanje_s_kodo)])
        if self.ob_zapori_kode is not None:
            try:
                self.ob_zapori_kode(dogodek)
            except Exception:
                pass

    def _ob_napadu(self, viri: List[str]) -> None:
        logging.getLogger("safeer.link").warning("obramba: napad, zaprti viri: %s", ", ".join(viri))
        print("[SafeerLink] obramba: NAPAD - zaprti viri: %s" % ", ".join(viri), flush=True)
        _obvestilo(*besedilo_napada(viri, _slovensko()), cas_ms=60000)
        if self.ob_napadu is not None:
            try:
                self.ob_napadu(viri)
            except Exception:
                pass

    @staticmethod
    def _ze_gosti_lokalno() -> bool:
        """Ali na tem racunalniku ze posluša drug Hub (Safeer OS ali Safeer Control) na privzetih
        vratih? Varnostna mreza poleg mDNS izvolitve: oba procesa privzeto delita isto TLS identiteto
        (core/link_datoteke.TLS_MAPA), zato se v izvolitvi napacno prepoznata kot "jaz sam" namesto
        kot dva razlicna kandidata - brez tega preverjanja bi oba hkrati gostila Hub."""
        import socket as _s
        v = _s.socket(_s.AF_INET, _s.SOCK_STREAM)
        v.settimeout(0.3)
        try:
            v.connect(("127.0.0.1", PRIVZETA_VRATA))
        except OSError:
            return False
        finally:
            try:
                v.close()
            except Exception:
                pass
        # Nekdo poslusa. Ce to dokazano NI Safeer Hub (drug program na istih vratih), gostimo na drugih vratih;
        # prej je tak program gostovanje preprecil in racunalnik je ostal brez sredisca.
        return not ni_safeer_hub(PRIVZETA_VRATA)

    def zazeni(self) -> bool:
        with self._zaklep:
            if self._streznik is not None:
                return True
            if self._ze_gosti_lokalno():
                return False
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
                           pot_zetonov=os.path.join(link_krog._mapa_nastavitev(), "hub-zetoni.json"),
                           pot_varovalke=os.path.join(link_krog._mapa_nastavitev(), "hub-varovalka.json"))
            self.hub.ob_kodi = _obvestilo_kode
            self.hub.ob_zapori_kode = self._ob_zapori_kode
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
            if streznik.server_address[1] != PRIVZETA_VRATA and os.environ.get("SAFEER_HUB_DRUGI") != "1" and _na_privzetih_vratih_ze_tece_hub():
                # Na tem racunalniku ze tece Safeer Hub (npr. Safeer Control v ozadju). Drugi Hub z lastno
                # identiteto bi se v omrezju oglasal z istim imenom racunalnika in druge naprave bi se povezovale
                # nanj - ta bi jih zavrnil (30. 9. 2026: Windows -> "Safeer Control (racunalnik-...)" zavrnjen).
                logging.getLogger("safeer.link").warning("Hub na vratih %d ze tece - drugega Huba v tem procesu ne zazenem (SAFEER_HUB_DRUGI=1 za razvoj)", PRIVZETA_VRATA)
                try:
                    streznik.server_close()
                except Exception:
                    pass
                return False
            streznik.socket = ctx.wrap_socket(streznik.socket, server_side=True, do_handshake_on_connect=False)
            streznik.hub = self.hub          # type: ignore[attr-defined]
            streznik.obramba = self.obramba
            self.obramba.zaupan = self.hub.ima_povezavo_z
            streznik.datoteke = lambda: self.datoteke() if callable(self.datoteke) else self.datoteke  # type: ignore[attr-defined]
            self.vrata = streznik.server_address[1]
            try:
                self.hub.naslov_za_qr = "%s:%d" % (_krajevni_ip(), self.vrata)
            except Exception:
                self.hub.naslov_za_qr = ""

            self._streznik = streznik
            self._nit = threading.Thread(target=streznik.serve_forever, name="safeer-hub", daemon=True)
            self._nit.start()
            threading.Thread(target=self._pospravljanje, name="safeer-hub-pospravljanje", daemon=True).start()
            return True

    def _pospravljanje(self) -> None:
        """Enkrat na dan (prvic uro po zagonu) pospravi krog (Hub.pospravi_krog); tece, dokler tece streznik."""
        do_kroga = 3600.0
        while True:
            # Vsakih deset minut: neprevzete deljene datoteke (veljajo eno uro) ne ostajajo na disku.
            time.sleep(600.0)
            do_kroga -= 600.0
            with self._zaklep:
                if self._streznik is None:
                    return
                hub = self.hub
            try:
                if hub is not None:
                    hub.deljenje.pocisti()
            except Exception:
                pass
            if do_kroga > 0:
                continue
            try:
                self.hub.pospravi_krog()
            except Exception:
                pass
            do_kroga = 86400.0

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
            try:
                if self.hub is not None:
                    self.hub.deljenje.izprazni()
            except Exception:
                pass
        self.vrata = 0
        self.hub = None


# ---------------------------------------------------------------------- oglas in prevzem

#: Ime storitve mDNS, po kateri naprave iscejo Safeer Hub (isto kot na Androidu).
STORITEV_MDNS = "_safeercast._tcp.local."
#: Prioriteta racunalnika pri izvolitvi huba (IzvolitevHuba.PRIORITETA_LINUX).
PRIORITETA_LINUX = 80


def ime_oglasa(id_naprave: str) -> str:
    """Ime primerka storitve mDNS za Hub racunalnika: za vsako napravo drugacno.

    Prej »safeer-« + zadnjih 8 znakov id-ja. Id Controla se konca na »-control«, zato sta se dva racunalnika v istem
    omrezju oglasala z istim imenom (»safeer--control«); drugemu registracija ni uspela in v omrezju ga ni bilo
    videti (ugotovljeno 5. 10. 2026: testni Windows ob racunalniku z Linuxom). Ime zdaj nastane iz dela id-ja, ki
    je pri vsaki napravi drugacen (brez pripone vloge); naprave Hub prepoznajo po polju `id`, ne po tem imenu.
    """
    jedro = (id_naprave or "").strip()
    for pripona in ("-control", "-os"):
        if jedro.endswith(pripona):
            jedro = jedro[:-len(pripona)]
            break
    znaki = "".join(z for z in jedro if z.isascii() and z.isalnum())[-12:]
    return "safeer-%s" % (znaki or "pc")


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
                # Link Mesh: ta Hub zna sosednje povezave (star Hub tega ne oglasi in ga ne klicemo).
                b"mesh": MESH.encode(),
            }
            naslov = _s.inet_aton(_krajevni_ip())
            ime_storitve = "%s.%s" % (ime_oglasa(id_naprave), STORITEV_MDNS)
            info = ServiceInfo(STORITEV_MDNS, ime_storitve, addresses=[naslov], port=vrata,
                               properties=lastnosti, server=_s.gethostname().rstrip(".") + ".local.")
            zc = Zeroconf()
            try:
                # Ce je ime vseeno zasedeno (ostanek prejsnjega zagona v omrezju), dobi pripono - oglas z
                # drugacnim imenom je boljsi kot nobenega.
                zc.register_service(info, allow_name_change=True)
            except Exception:
                zc.close()
                raise
            self._zc, self._info = zc, info
            return True
        except Exception as e:  # noqa: BLE001
            # Prej tiho: Hub brez oglasa je tekel, ne da bi bilo iz dnevnika razvidno, da ga v omrezju ni videti.
            print("[SafeerLink] oglas mDNS ni uspel: %s: %s" % (type(e).__name__, e), flush=True)
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


def ni_safeer_hub(vrata: int = PRIVZETA_VRATA, timeout: float = 1.5, gostitelj: str = "127.0.0.1") -> bool:
    """True samo, kadar na vratih DOKAZANO poslusa nekaj, kar ni Safeer Hub: ne govori TLS ali na pot zdravja ne
    odgovori kot sredisce. Ob dvomu (nihce ne poslusa, ne odgovori pravocasno, prekine) False - lahko je nase
    sredisce, ki se ravno zaganja ali je zasedeno."""
    import socket as _s
    try:
        surov = _s.create_connection((gostitelj, vrata), timeout=timeout)
    except OSError:
        return False
    tls = None
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            tls = ctx.wrap_socket(surov)
        except (ssl.SSLEOFError, ssl.SSLZeroReturnError):
            return False                 # zaprl med rokovanjem: ne vemo
        except ssl.SSLError:
            return True                  # ne govori TLS: drug program
        except OSError:
            return False                 # cas ali prekinitev: ne vemo
        glava = b""
        try:
            tls.settimeout(timeout)
            tls.sendall(b"GET /cast/health HTTP/1.1\r\nHost: 127.0.0.1\r\nAccept: application/json\r\n"
                        b"Connection: close\r\n\r\n")
            while b"\r\n" not in glava and len(glava) < 4096:
                kos = tls.recv(1024)
                if not kos:
                    break
                glava += kos
        except OSError:
            return False
        prva = glava.split(b"\r\n", 1)[0].split()
        if not glava:
            return False                 # brez odgovora: ne vemo
        if len(prva) < 2 or not prva[0].startswith(b"HTTP/"):
            return True                  # odgovoril je, a ne s HTTP
        # Sredisce na pot zdravja odgovori 200; 401/403 sta se vedno sredisce (zahteva zeton, zapora vira).
        return prva[1] not in (b"200", b"401", b"403")
    finally:
        for v in (tls, surov):
            try:
                if v is not None:
                    v.close()
            except Exception:
                pass


def _na_privzetih_vratih_ze_tece_hub(timeout: float = 1.5) -> bool:
    """Ali na tem racunalniku na privzetih vratih ze odgovarja Safeer Hub (pot zdravja, TLS brez preverjanja)."""
    import ssl as _ssl
    import urllib.request as _u
    try:
        ctx = _ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = _ssl.CERT_NONE
        with _u.urlopen(_u.Request("https://127.0.0.1:%d/cast/health" % PRIVZETA_VRATA, headers={"Accept": "application/json"}), timeout=timeout, context=ctx) as o:
            return o.status == 200
    except Exception as e:  # noqa: BLE001
        return getattr(e, "code", 0) == 401


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

def mesh_vklopljen() -> bool:
    """Link Mesh (docs/LINK-MESH.md): vsaka naprava gosti svoj Hub in se poveze s sosedi.
    Izklop za primerjavo/odpravljanje napak: SAFEER_LINK_MESH=0."""
    import os
    return os.environ.get("SAFEER_LINK_MESH", "1") != "0"


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
        self.mesh = None

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
            if mesh_vklopljen():
                # Link Mesh: vsaka naprava je vozlisce; nihce se ne umika.
                gostimo = True
            elif oglaseni:
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
                if mesh_vklopljen() and self.nas_id and getattr(self.streznik, "hub", None) is not None:
                    from core import link_mesh
                    self.streznik.hub.nas_id = self.nas_id
                    import os
                    self.mesh = link_mesh.MeshPovezovalec(
                        self.streznik.hub, self.nas_id, self.ime,
                        pot_znanih=os.path.join(link_krog._mapa_nastavitev(), "mesh-sosedje.json"),
                        vrata=lambda s=self.streznik: s.vrata if s.tece() else 0)
                    self.mesh.zazeni()
                return True
            if self.streznik.tece():
                # Drug Hub je spet tu: umaknemo se, da hisa nima dveh sredisc.
                print("[SafeerLink] drug Safeer Link je spet na voljo; računalnik neha gostiti")
                self.oglas.koncaj()
                self.streznik.ustavi()
            return False

    def koncaj(self) -> None:
        with self._zaklep:
            if self.mesh is not None:
                self.mesh.ustavi()
                self.mesh = None
            self.oglas.koncaj()
            self.streznik.ustavi()
