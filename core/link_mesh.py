"""Link Mesh (docs/LINK-MESH.md): nas Hub se sam poveze s Hubi drugih naprav iz kroga zaupanja.

Hub na tej napravi tece vedno. Ta modul poisce druge Hube (mDNS), preveri, da potrdilo nosi
kljuc clana kroga, se prijavi s podpisom nasega kljuca in odpre **sosednjo povezavo**. Od tam naprej
vse dela Hub.obdelaj_soseda: izmenjava lokalnih naprav, usmerjanje, krog.

Global Link: kadar soseda neposredno ni (naprava je zunaj doma), ga poklicemo prek link.safeer.si.
Rele prenasa samo sifrirane bajte; TLS s kljucem iz kroga in prijava s podpisom ostaneta enaka kot v LAN.
Nas Hub se na releju tudi sam objavi (AgentHuba), da ga clani kroga dosezejo od zunaj.

Da nastane za vsak par ena povezava, prvi klice manjsi id; vecji pocaka in klice sam sele, ce ga
manjsi dolgo ne doseze (npr. pozarni zid na eni strani). Ce vseeno nastaneta dve, Hub obdrzi tisto,
ki jo je odprl manjsi id (Hub.dodaj_soseda).
"""

from __future__ import annotations

import collections
import json
import os
import threading
import time
from typing import Callable, Dict, List, Optional

from core import link_hub, link_krog, link_tls

#: Kako pogosto iscemo sosede in kdaj vecji id klice sam.
ISCI_VSAKIH_S = 15.0
VECJI_CAKA_S = 40.0
#: Srcni utrip sosednje povezave (streznik na drugi strani pinga sam; to je nasa stran).
UTRIP_S = 10.0
#: Po izgubi soseda poskusimo znova hitro (on se je morda le znova zagnal).
PONOVNO_PO_S = 2.0
#: Vrata Huba, kadar naslov soseda poznamo samo iz dohodne povezave (IP brez oglasa mDNS).
PRIVZETA_VRATA = 8990
#: Najvec zapomnjenih naslovov sosedov.
NAJVEC_ZNANIH = 32
#: Najvec cakajocih sporocil na sosednjo povezavo, preden jo zapremo (sosed ne bere).
NAJVEC_V_VRSTI = 512
#: Po toliko zaporednih neuspelih neposrednih klicih soseda poskusimo prek releja (Global Link).
RELE_PO_NEUSPEHIH = 2
#: Premor po neuspelem klicu prek releja (raste do NAJDALJSI_PREMOR_RELEJA_S): varuje dnevno kvoto releja.
PREMOR_RELEJA_S = 60.0
NAJDALJSI_PREMOR_RELEJA_S = 600.0

#: En agent Global Linka na proces (vec MeshPovezovalcev bi se na releju izrinjalo); vrata trenutnega Huba.
_agent = None
_agent_vrata: list = [None]
_agent_zaklep = threading.Lock()


class OdhodnaSosednja:
    """Povezava, ki smo jo odprli mi. Pise v svoji niti, da pocasen sosed ne ustavi nasega Huba."""

    def __init__(self, ws: "link_hub.WsOdjemalec", naslov: str) -> None:
        self.ws = ws
        self.naslov = naslov
        self.podatki: dict = {}
        self._vrsta: collections.deque = collections.deque()
        self._ima = threading.Event()
        self._zaprta = False
        threading.Thread(target=self._pisi, name="safeer-mesh-pisec", daemon=True).start()

    def poslji(self, besedilo: str) -> bool:
        if self._zaprta:
            return False
        if len(self._vrsta) >= NAJVEC_V_VRSTI:
            print("[SafeerLink] mesh: sosed %s ne bere (%d sporocil v vrsti) - povezavo zapiram" % (self.naslov, len(self._vrsta)),
                  flush=True)
            self.zapri(1008, "sosed ne bere")
            return False
        self._vrsta.append(besedilo)
        self._ima.set()
        return True

    def _pisi(self) -> None:
        while not self._zaprta:
            self._ima.wait(UTRIP_S)
            self._ima.clear()
            if not self._vrsta:
                if not self._zaprta and not self.ws.ping():
                    self.zapri()
                continue
            while self._vrsta and not self._zaprta:
                besedilo = self._vrsta.popleft()
                try:
                    self.ws.poslji(besedilo)
                except Exception:
                    self.zapri()
                    return

    def zapri(self, *_a, **_k) -> None:
        if self._zaprta:
            return
        self._zaprta = True
        self._ima.set()
        try:
            self.ws.zapri()
        except Exception:
            pass

    @property
    def zaprta(self) -> bool:
        return self._zaprta


class MeshPovezovalec:
    """Poisce in vzdrzuje sosednje povezave nasega Huba."""

    def __init__(self, hub, nas_id: str, ime: str = "Safeer",
                 poisci: Optional[Callable[[], List[dict]]] = None, pot_znanih: str = "",
                 vrata: Optional[Callable[[], int]] = None) -> None:
        self.hub = hub
        self.nas_id = nas_id
        self.ime = ime
        self.poisci = poisci or (lambda: link_hub.poisci_hube_mdns(2.0))
        self._klicem: set = set()
        self._prvic_videni: Dict[str, float] = {}
        #: Sosed, ki nas je zavrnil: id -> (do kdaj ga ne klicemo, zadnji premor). Premor raste do 10 min.
        self._zavrnjeni: Dict[str, tuple] = {}
        self._ustavljen = threading.Event()
        self._zbudi = threading.Event()
        self._zaklep = threading.Lock()
        self._nit: Optional[threading.Thread] = None
        #: Zapomnjeni naslovi sosedov (id -> oglas): za naprave, ki jih mDNS ne vidi (pozarni zid,
        #: izolacija), in za hiter ponovni priklop po ponovnem zagonu.
        self._pot_znanih = pot_znanih
        self._znani: Dict[str, dict] = self._nalozi_znane()
        #: Sosedje iz prejsnjega teka: v prvem krogu po zagonu jih poklicemo sami, tudi ce imajo manjsi id. Sosed za
        #: nas ponovni zagon ne ve in nas najde sele v svojem naslednjem krogu iskanja (izmerjeno 5. 10. 2026:
        #: racunalnik je bil po zagonu programa v Safeer Linku cez 26 in cez 51 s, njegov Hub pa je tekel ze po 10 s).
        #: Ce medtem poklice tudi sosed, Hub obdrzi povezavo, ki jo je odprl manjsi id (dodaj_soseda).
        self._po_zagonu: set = set(self._znani)
        #: Global Link: vrata nasega Huba (za agenta), zaporedni neuspehi neposrednih klicev in releji.
        self._vrata = vrata
        self._neuspehi: Dict[str, int] = {}
        self._premor_releja: Dict[str, tuple] = {}
        self._releji: Dict[str, object] = {}
        hub.ob_sosedu = self._ob_sosedu

    def zazeni(self) -> None:
        if self._nit is not None:
            return
        self._nit = threading.Thread(target=self._zanka, name="safeer-mesh", daemon=True)
        self._nit.start()
        self._zazeni_agenta()

    def ustavi(self) -> None:
        self._ustavljen.set()
        self._zbudi.set()
        with _agent_zaklep:
            if _agent_vrata[0] is self._vrata:
                _agent_vrata[0] = None       # agent neha sprejemati kanale, dokler Hub ne tece znova
        for rele in list(self._releji.values()):
            try:
                rele.zapri()
            except Exception:
                pass
        self._releji.clear()

    # -- Global Link

    def _zazeni_agenta(self) -> None:
        """Nas Hub objavi na link.safeer.si, da ga clani kroga dosezejo tudi zunaj doma."""
        global _agent
        if self._vrata is None or not global_link_vklopljen():
            return
        from core import link_rele
        with _agent_zaklep:
            _agent_vrata[0] = self._vrata
            if _agent is not None:
                return

            def vrata() -> int:
                f = _agent_vrata[0]
                try:
                    return int(f()) if f is not None else 0
                except Exception:
                    return 0

            _agent = link_rele.AgentHuba(vrata=vrata, vklopljen=global_link_vklopljen,
                                         krog_json=lambda: link_krog.krog().json())
            _agent.zazeni()

    def _rele(self, hid: str):
        """Lokalna vrata do soseda prek releja (eno na soseda) ali None, ce ga rele ne more doseci."""
        from core import link_rele
        clan = link_krog.krog().clan_za_id(hid)
        try:
            # Rele pozna napravo po id-ju iz njenega kljuca (Hub se lahko oglasa z id-jem s pripono,
            # npr. `n-...-control`); zaupanje da kljuc v potrdilu, ne id.
            cilj = link_rele.id_iz_kljuca(clan["kljuc"]) if clan else ""
        except Exception:
            cilj = ""
        if not cilj or not hid.startswith(cilj):
            return None
        with self._zaklep:
            rele = self._releji.get(hid)
            if rele is None:
                rele = link_rele.LokalniRele(cilj)
                self._releji[hid] = rele
        return rele

    def _klici_prek_releja(self, h: dict) -> bool:
        hid = str(h["id"])
        zdaj = time.time()
        if self._premor_releja.get(hid, (0.0, 0.0))[0] > zdaj:
            return False
        rele = self._rele(hid)
        if rele is None:
            return False
        naslov = "wss://127.0.0.1:%d/cast/ws" % rele.vrata
        try:
            dosegljiv = self._odpri(dict(h, naslov=naslov))
        except Exception as e:  # noqa: BLE001
            print("[SafeerLink] mesh: %s prek releja ni dosegljiv (%s)" % (hid, e))
            dosegljiv = False
        if dosegljiv:
            self._premor_releja.pop(hid, None)
            return True
        prej = self._premor_releja.get(hid, (0.0, 0.0))[1]
        premor = min(NAJDALJSI_PREMOR_RELEJA_S, prej * 2 if prej else PREMOR_RELEJA_S)
        self._premor_releja[hid] = (time.time() + premor, premor)
        napaka = getattr(rele, "zadnja_napaka", "")
        print("[SafeerLink] mesh: %s prek releja ni dosegljiv%s; znova cez %d s"
              % (hid, " (%s)" % napaka if napaka else "", premor))
        return False

    # -- zapomnjeni naslovi

    def _nalozi_znane(self) -> Dict[str, dict]:
        if not self._pot_znanih:
            return {}
        try:
            with open(self._pot_znanih, encoding="utf-8") as d:
                zapis = json.load(d)
            return {str(k): v for k, v in zapis.items() if isinstance(v, dict) and str(v.get("naslov", "")).startswith("wss://")}
        except Exception:
            return {}

    def _shrani_znane(self) -> None:
        if not self._pot_znanih:
            return
        try:
            os.makedirs(os.path.dirname(self._pot_znanih), exist_ok=True)
            zacasna = self._pot_znanih + ".tmp"
            with open(zacasna, "w", encoding="utf-8") as d:
                json.dump(self._znani, d)
            os.replace(zacasna, self._pot_znanih)
        except Exception:
            pass

    def zapomni(self, hid: str, naslov: str) -> None:
        """Naslov soseda si zapomnimo (iz oglasa ali dohodne povezave; IP brez vrat = privzeta vrata)."""
        if not hid or hid == self.nas_id or not naslov or _je_zanka(naslov):
            return               # 127.0.0.1 je rele (Global Link), ne naslov soseda
        if not naslov.startswith("wss://"):
            naslov = "wss://%s:%d/cast/ws" % (naslov, PRIVZETA_VRATA)
        with self._zaklep:
            if self._znani.get(hid, {}).get("naslov") == naslov:
                return
            self._znani[hid] = {"id": hid, "naslov": naslov, "tls": True, "mesh": link_hub_streznik_mesh()}
            while len(self._znani) > NAJVEC_ZNANIH:
                self._znani.pop(next(iter(self._znani)))
        self._shrani_znane()

    def _ob_sosedu(self, hid: str, naslov: str) -> None:
        if naslov:
            # Naslov iz odhodne povezave je pravi (z vrati); iz dohodne je samo IP.
            znan = self._znani.get(hid, {}).get("naslov", "")
            if not (znan and naslov in znan):
                self.zapomni(hid, naslov)
            return
        # Sosed je odsel: hitro poskusimo znova (morda se je le znova zagnal ali zamenjal omrezje).
        threading.Timer(PONOVNO_PO_S, self._zbudi.set).start()

    def _zanka(self) -> None:
        if self._po_zagonu:
            # Znane sosede poklicemo takoj; na oglase mDNS (cakanje in iskanje vzameta 4 s) ne cakamo.
            try:
                self.en_krog(isci=False)
            except Exception as e:  # noqa: BLE001
                print("[SafeerLink] mesh:", e)
        self._ustavljen.wait(2.0)
        while not self._ustavljen.is_set():
            try:
                self.en_krog()
            except Exception as e:  # noqa: BLE001
                print("[SafeerLink] mesh:", e)
            self._zbudi.wait(ISCI_VSAKIH_S)
            self._zbudi.clear()

    def kandidati(self, oglasi: List[dict], zdaj: Optional[float] = None) -> List[dict]:
        """Oglasi Hubov, ki jih moramo zdaj poklicati (brez omrezja - preizkusljivo)."""
        zdaj = time.time() if zdaj is None else zdaj
        povezani = set(self.hub.sosedje())
        izbrani = []
        for h in oglasi:
            hid = str(h.get("id") or "")
            if not hid or hid == self.nas_id or not h.get("tls") or hid in povezani:
                continue
            if h.get("mesh") != link_hub_streznik_mesh():
                continue            # star Hub: sosednje povezave ne razume
            if hid in brez_neposredne():
                continue            # preizkus poti prek vmesnega vozlisca
            with self._zaklep:
                if hid in self._klicem:
                    continue
                prvic = self._prvic_videni.setdefault(hid, zdaj)
            try:
                if link_krog.krog().clan_za_id(hid) is None:
                    continue
            except Exception:
                continue
            if self._zavrnjeni.get(hid, (0.0, 0.0))[0] > zdaj:
                continue            # nas je zavrnil; pocakamo
            if hid < self.nas_id and zdaj - prvic < VECJI_CAKA_S and hid not in self._po_zagonu:
                continue            # manjsi id klice prvi; pocakamo nanj (razen takoj po nasem zagonu)
            izbrani.append(h)
        return izbrani

    def en_krog(self, isci: bool = True) -> None:
        """En krog iskanja in klicanja sosedov. isci=False: samo zapomnjeni sosedje, brez iskanja oglasov mDNS."""
        oglasi = list(self.poisci() or []) if isci else []
        for h in oglasi:
            if h.get("mesh") == link_hub_streznik_mesh() and h.get("tls"):
                self.zapomni(str(h.get("id") or ""), str(h.get("naslov") or ""))
        # Kogar mDNS ta hip ne vidi, poskusimo na zapomnjenem naslovu.
        videni = {str(h.get("id") or "") for h in oglasi}
        with self._zaklep:
            oglasi += [dict(z) for hid, z in self._znani.items() if hid not in videni]
        for h in self.kandidati(oglasi):
            with self._zaklep:
                self._klicem.add(h["id"])
            threading.Thread(target=self._klici, args=(h,), name="safeer-mesh-klic", daemon=True).start()
        # Prednost po zagonu velja en krog: kogar takrat nismo dosegli, ga caka obicajno pravilo.
        self._po_zagonu.clear()

    def _klici(self, h: dict) -> None:
        hid = str(h["id"])
        try:
            dosegljiv = False
            if hid not in samo_prek_releja():
                try:
                    dosegljiv = self._odpri(h)
                except Exception as e:  # noqa: BLE001
                    print("[SafeerLink] mesh: %s ni dosegljiv (%s)" % (hid, e))
                if dosegljiv:
                    self._neuspehi.pop(hid, None)
                    return
                self._neuspehi[hid] = self._neuspehi.get(hid, 0) + 1
            if self._ustavljen.is_set() or not global_link_vklopljen():
                return
            # Neposredno ga ni (zunaj doma ali za pozarnim zidom): prek link.safeer.si.
            if hid in samo_prek_releja() or self._neuspehi.get(hid, 0) >= RELE_PO_NEUSPEHIH:
                self._klici_prek_releja(h)
        finally:
            with self._zaklep:
                self._klicem.discard(hid)

    def _odpri(self, h: dict) -> bool:
        """Poveze se s sosedom in bere do konca povezave. Vrne True, ce je bil sosed na tem naslovu
        dosegljiv (pravi kljuc in vstopnica) - tudi ce nas je nato zavrnil, ker ze ima drugo povezavo."""
        hid, naslov = str(h["id"]), str(h["naslov"])
        clan = link_krog.krog().clan_za_id(hid)
        if clan is None:
            return False
        # Zaupanje: kljuc v potrdilu mora biti kljuc tega clana v krogu (oglas mDNS ne velja nic).
        odtis, kljuc = link_tls.potrdilo_huba(naslov)
        if not odtis or not kljuc or kljuc != clan.get("kljuc"):
            return False
        vstopnica, _ = link_hub.vzemi_vstopnico_s_podpisom(naslov, self.nas_id, odtis, self.ime)
        if not vstopnica:
            return False
        dosegljiv = True
        locilo = "&" if "?" in naslov else "?"
        ws = link_hub.WsOdjemalec(f"{naslov}{locilo}ticket={vstopnica}", odtis=odtis)
        ws.odpri()
        # Prijava gre prva (sinhrono), sele nato pisec: sosed mora vedeti, da smo Hub, preden
        # dobi karkoli drugega.
        ws.poslji(json.dumps({"id": str(int(time.time() * 1000)), "type": "cast.register",
                              "payload": {"device_id": self.nas_id, "name": self.ime, "role": "hub",
                                          "capabilities": [link_hub_streznik_mesh()], "protocol": "1"}}))
        povezava = OdhodnaSosednja(ws, naslov)
        if not self.hub.dodaj_soseda(hid, povezava, self.nas_id):
            povezava.zapri()
            return dosegljiv
        print("[SafeerLink] mesh: sosed %s (%s%s)" % (hid, naslov, ", Global Link" if _je_zanka(naslov) else ""))
        # Premor po zavrnitvi pobrisemo sele, ko nas sosed res sprejme (prvo sporocilo, ki ni zavrnitev);
        # zavrnitev pride sele po odprtju, zato bi ga brisanje tu vedno vrnilo na 30 s.
        self._beri(hid, povezava)
        return dosegljiv

    def _beri(self, hid: str, povezava: OdhodnaSosednja) -> bool:
        """Bere sosedova sporocila do konca povezave; vrne True, ce nas je sosed sprejel."""
        sprejet = False
        try:
            while not povezava.zaprta:
                try:
                    surovo = povezava.ws.prejmi()
                except TimeoutError:
                    continue
                except Exception as e:  # noqa: BLE001
                    if not povezava.zaprta:
                        print("[SafeerLink] mesh: branje s soseda %s se je koncalo: %s: %s" % (hid, type(e).__name__, str(e)[:120]),
                              flush=True)
                    break
                if surovo is None:
                    break
                try:
                    sporocilo = json.loads(surovo)
                except Exception:
                    continue
                if isinstance(sporocilo, dict) and sporocilo.get("type") == "cast.ack" \
                        and sporocilo.get("status") == "rejected":
                    print("[SafeerLink] mesh: %s nas ni sprejel (%s)" % (hid, sporocilo.get("error_code", "")))
                    prej = self._zavrnjeni.get(hid, (0.0, 0.0))[1]
                    premor = min(600.0, prej * 2 if prej else 30.0)
                    self._zavrnjeni[hid] = (time.time() + premor, premor)
                    # Sosed nas ne sprejme (npr. ze ima povezavo, ki jo je odprl on).
                    break
                if not sprejet:
                    sprejet = True
                    self._zavrnjeni.pop(hid, None)
                odgovor = self.hub.obdelaj(povezava, surovo)
                if odgovor:
                    povezava.poslji(odgovor)
        finally:
            povezava.zapri()
            self.hub.odklopi(povezava)
        return sprejet


def brez_neposredne() -> set:
    """Samo za preizkus dostave prek vmesnega vozlisca: SAFEER_MESH_BREZ=id1,id2 (brez neposredne povezave)."""
    return {i.strip() for i in os.environ.get("SAFEER_MESH_BREZ", "").split(",") if i.strip()}


def samo_prek_releja() -> set:
    """Samo za preizkus Global Linka doma: SAFEER_MESH_RELE=id1,id2 (te sosede klicemo samo prek releja)."""
    return {i.strip() for i in os.environ.get("SAFEER_MESH_RELE", "").split(",") if i.strip()}


def global_link_vklopljen() -> bool:
    """Global Link (rele link.safeer.si) je privzeto vklopljen; SAFEER_GLOBAL_LINK=0 ga izklopi."""
    return os.environ.get("SAFEER_GLOBAL_LINK", "1").strip() != "0"


def _je_zanka(naslov: str) -> bool:
    """Ali naslov kaze na to napravo (127.x, ::1, localhost) - tam je lokalni konec releja."""
    from urllib.parse import urlparse
    gostitelj = (urlparse(naslov).hostname if "://" in naslov else naslov.strip("[]")) or ""
    return gostitelj == "localhost" or gostitelj == "::1" or gostitelj.startswith("127.")


def link_hub_streznik_mesh() -> str:
    from core import link_hub_streznik
    return link_hub_streznik.MESH
