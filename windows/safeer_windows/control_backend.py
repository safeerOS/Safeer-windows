"""Safeer Control Backend za Windows — upravljanje povezave, seznanitev in naprav Safeer Linka."""

from __future__ import annotations

import base64
import http.client
import json
import os
import secrets
import socket
import sys
import threading
import time
import urllib.parse
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
CORE_DIR = os.path.abspath(os.path.join(PACKAGE_DIR, "..", ".."))
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

from core import link_deljenje, link_hub, link_hub_streznik, link_tls
from safeer_windows import os_backend_win
from safeer_windows.navidezni_zaslon import NavidezniZaslon

CONFIG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~/.config"), "SafeerControl")
CONFIG_FILE = os.path.join(CONFIG_DIR, "link.json")
#: Magnet povezava z druge naprave v krogu: odpre jo Safeer OS (Medijski center), kot na Linuxu.
DEJANJA_MAGNET = ["magnet.open"]
#: Torrent prenasa in pretaka ta racunalnik, naprava (televizor, telefon) samo predvaja tok in nicesar ne
#: shranjuje - isto kot Safeer Control na Linuxu (core/link_datoteke.py: tok_torrenta).
DEJANJA_TOK_TORRENTA = ["magnet.stream", "magnet.list", "magnet.remove", "magnet.keep"]
#: Sprotno pretvarjanje za napravo, ki videa ne zna predvajati (core/link_sprotno.py, isti protokol kot Linux/Android).
DEJANJA_PRETOK = ["video.stream", "video.stream_stop", "video.stream_status"]
#: Zakon solidarnosti: naprava z dolocenimi pravicami (tudi samo zaslon) sme prositi za moc racunalnika - s tem ne
#: dobi njegovih datotek ali zaslona, le pretvorjen svoj video in podatek, koliko moci ima racunalnik.
DEJANJA_SOLIDARNOST = ["host.info"] + DEJANJA_PRETOK + DEJANJA_TOK_TORRENTA
#: Daljinec (Link) upravlja Medijski center v istem procesu (os_app nastavi ob_mediju). Tipke daljinca
#: play_pause/play/pause/stop/next/previous gredo najprej v predvajalnik; "media" je izrecni ukaz s parametri.
DEJANJA_MEDIJ = ["media"]
#: »Nadaljuj z druge naprave«: telefon vprasa, kaj Medijski center tu predvaja, in nadaljuje pri isti sekundi
#: (core/link_predvajanje.py, isti protokol kot Linux in Predaja.kt na Androidu). Samo naprava s pravico do
#: datotek (profil polno ali izbrano) - datoteka gre le iz deljenih map, play.stop je samo premor.
DEJANJA_PREDAJA = ["play.state", "play.stop", "play.offer"]
#: Seznami predvajanja so enaki na vseh uporabnikovih napravah v Linku (core/seznami_sink.py, SeznamiSink.kt na
#: Androidu): druga naprava v Linku prebere sezname Medijskega centra (samo branje, brez posebne pravice).
DEJANJA_SEZNAMI = ["lists.get"]
#: Sejni zeton s podpisom velja pri srediscu 12 ur; toliko casa ga uporabljamo, preden vzamemo novega.
SEJA_HTTP_HRANIMO_S = 1800.0
#: Premori (s) med ponovnimi poskusi zagona sredisca, kadar vrata se drzi kopija programa, ki se zapira.
POSKUSI_SREDISCA = (1.0, 1.0, 2.0, 2.0, 3.0)
TIPKE_MEDIJ = ("play_pause", "play", "pause", "stop", "next", "previous", "naslednja", "prejsnja")


class _WindowsDeljenjeZaslona(link_deljenje.DeljenjeZaslona):
    """Hubu posreduje Safeerjev izolirani zaslon, ne uporabnikovega fizičnega namizja."""

    def __init__(self, *args, navidezni_zaslon: NavidezniZaslon, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._navidezni_zaslon = navidezni_zaslon

    def zajem_na_voljo(self) -> Tuple[bool, str]:
        return True, ""

    def _okvir(self) -> Optional[bytes]:
        posnetek = self._navidezni_zaslon.zajemi_posnetek()
        slika = str((posnetek or {}).get("image") or "")
        if not slika:
            return None
        encoded = slika.split(",", 1)[1] if "," in slika else slika
        return base64.b64decode(encoded, validate=True)


#: Kako dolgo velja najdeni seznam hubov; prazen velja dlje (iskanje brez najdbe je najdaljse).
HUBI_VELJAJO_S = 10.0
HUBI_PRAZNI_VELJAJO_S = 30.0


def _se_razresi(gostitelj: str) -> bool:
    """Ali ima gostitelj naslov: stevilcni naslov vedno, ime samo, ce ga omrezje pozna."""
    try:
        socket.inet_aton(gostitelj)
        return True
    except (OSError, TypeError, ValueError):
        pass
    try:
        return bool(socket.getaddrinfo(gostitelj, None))
    except (OSError, UnicodeError):
        return False


class SafeerControlBackend:
    _instance: Optional["SafeerControlBackend"] = None
    _lock = threading.Lock()

    @classmethod
    def pridobi(cls) -> "SafeerControlBackend":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self, config_pot: str = CONFIG_FILE) -> None:
        self.config_pot = config_pot
        self.nastavitve: Dict[str, Any] = {}
        self.nalozi_nastavitve()

        self.device_id, self.device_ime = self._doloci_identiteto()
        self.lokalna_koda = str(100000 + secrets.randbelow(900000))
        self._lokalna_koda_cas = time.time()
        self.navidezni_zaslon = NavidezniZaslon()
        self.povezava: Optional[link_hub.Povezava] = None
        self.naprave: List[dict] = []
        #: "Poslji na napravo": ponudba druge naprave, ki tu caka na Sprejmi/Zavrni (core/link_predvajanje.ponudba_iz).
        self.ponudba_cakajoca: Optional[dict] = None
        self._prijava: Optional[dict] = None
        self._qr: Optional[dict] = None
        self._qr_rod = 0
        self._vabilo: Optional[dict] = None
        self._vabilo_rod = 0
        self._cakajoci: Dict[str, list] = {}
        #: Safeer Chat: potrditve sredisca in prejem sporocil (os_app nastavi ob_klepetu).
        self._klepet_cakajoci: Dict[str, list] = {}
        self.ob_klepetu: Optional[Callable[[dict], None]] = None
        #: Magnet povezava z druge naprave (magnet.open): os_app jo odpre v Medijskem centru istega procesa.
        self.ob_magnetu: Optional[Callable[[str], None]] = None
        #: Medijski center (os_app): ob_mediju(ukaz, params) -> izid dict ali None (ni obdelano -> navidezni zaslon).
        #: Klic pride iz omrezne niti; os_app ga sam prenese v nit vmesnika.
        self.ob_mediju: Optional[Callable[[str, dict], Optional[Dict[str, Any]]]] = None
        #: Seznami predvajanja Medijskega centra (os_app): ob_seznamih(parametri) -> podatki za `lists.get`.
        self.ob_seznamih: Optional[Callable[[dict], dict]] = None
        self._poslusavci: List[Callable[[str, Any], None]] = []
        self._povezovanje = False
        #: Sejni zeton za klice HTTP tujega sredisca: (zeton, velja do [monotonic], naslov sredisca).
        self._seja_http: Tuple[str, float, str] = ("", 0.0, "")
        #: Povezovanje tece naenkrat samo enkrat (zagon programa, stran in gumb ga lahko sprozijo hkrati).
        self._povezi_kljuc = threading.Lock()
        self._zadnji_hubi: List[dict] = []
        self._cas_hubi = 0.0
        #: Iskanje hubov tece v ozadju (hubi_brez_cakanja): ali je bilo ze kdaj koncano in ali ravno tece.
        self._hubi_iskani = False
        self._hubi_isce = False
        self._hubi_kljuc = threading.Lock()
        self._deljenje_zaslona: Optional[link_deljenje.DeljenjeZaslona] = None
        self._opozorjena_dovoljenja: set[str] = set()
        self._lokalni_hub: Optional[link_hub_streznik.HubStreznik] = None

    def nova_lokalna_koda(self) -> str:
        self.lokalna_koda = str(100000 + secrets.randbelow(900000))
        self._lokalna_koda_cas = time.time()
        self._oddaj_dogodek("lokalnaKoda", self.lokalna_koda)
        self._oddaj_dogodek("stanje", self.stanje_linka())
        return self.lokalna_koda

    # ------------------------------------------------------------------ Shramba
    def nalozi_nastavitve(self) -> dict:
        try:
            if os.path.exists(self.config_pot):
                with open(self.config_pot, "r", encoding="utf-8") as f:
                    self.nastavitve = json.load(f) or {}
            else:
                self.nastavitve = {}
        except Exception as e:
            print(f"[ControlBackend] Napaka pri branju {self.config_pot}: {e}")
            self.nastavitve = {}
        return self.nastavitve

    def shrani_nastavitve(self) -> bool:
        try:
            os.makedirs(os.path.dirname(self.config_pot), exist_ok=True)
            zacasna = self.config_pot + ".tmp"
            with open(zacasna, "w", encoding="utf-8") as f:
                json.dump(self.nastavitve, f, ensure_ascii=False, indent=2)
            if sys.platform != "win32":
                try:
                    os.chmod(zacasna, 0o600)
                except OSError:
                    pass
            os.replace(zacasna, self.config_pot)
            return True
        except Exception as e:
            print(f"[ControlBackend] Napaka pri shranjevanju {self.config_pot}: {e}")
            return False

    def _doloci_identiteto(self) -> Tuple[str, str]:
        hostname = socket.gethostname().split(".")[0] or "PC"
        id_nap = link_hub.id_naprave() + "-control"
        ime_nap = f"Safeer Control ({hostname})"
        return id_nap, ime_nap

    # ------------------------------------------------------------------ Poslusavci dogodkov
    def dodaj_poslusalca(self, fn: Callable[[str, Any], None]) -> None:
        if fn not in self._poslusavci:
            self._poslusavci.append(fn)

    def odstrani_poslusalca(self, fn: Callable[[str, Any], None]) -> None:
        if fn in self._poslusavci:
            self._poslusavci.remove(fn)

    def _oddaj_dogodek(self, vrsta: str, podatki: Any) -> None:
        for fn in list(self._poslusavci):
            try:
                fn(vrsta, podatki)
            except Exception as e:
                print(f"[ControlBackend] Napaka v poslusalcu dogodka {vrsta}: {e}")

    # ------------------------------------------------------------------ Stanje za Safeer OS & Safeer Link
    def je_povezan(self) -> bool:
        return self.povezava is not None and getattr(self.povezava, "tece", False)

    def hub_url(self) -> str:
        return str(self.nastavitve.get("hub_url") or "")

    def hub_fp(self) -> str:
        return str(self.nastavitve.get("hub_fp") or "")

    def zeton(self) -> str:
        return str(self.nastavitve.get("control_token") or "")

    def _gostimo_lokalno(self) -> bool:
        """Ali je sredisce, na katero je Control prijavljen, nase (v tem procesu)."""
        lokalni = getattr(self, "_lokalni_hub", None)
        return bool(lokalni is not None and lokalni.tece() and lokalni.hub is not None
                    and self.hub_url().startswith("wss://127.0.0.1:"))

    def _zeton_http(self) -> str:
        """Zeton za klice HTTP sredisca (vabilo, preimenovanje, oddaja datoteke, odhod).

        Zeton seznanitve velja 24 ur, program pa lahko tece vec dni:
        - lastno sredisce (isti proces): veljaven zeton obdrzimo, preteklega zamenjamo neposredno pri srediscu;
        - tuje sredisce: naprava v krogu zaupanja dobi sejni zeton s podpisom kljuca (velja 12 ur, hranimo ga pol
          ure); sicer ostane zeton seznanitve.
        """
        hub, zeton = self.hub_url(), self.zeton()
        if not hub:
            return ""
        if self._gostimo_lokalno():
            sredisce = self._lokalni_hub.hub
            if zeton and sredisce.naprava_zetona(zeton) is not None:
                return zeton
            nov = sredisce.zeton_lastne_naprave(self.device_id, self.device_ime)
            if not nov:
                return zeton
            self.nastavitve["control_token"] = nov
            self.shrani_nastavitve()
            return nov
        seja, velja_do, za = getattr(self, "_seja_http", ("", 0.0, ""))
        if seja and za == hub and time.monotonic() < velja_do:
            return seja
        try:
            from core import link_krog
            if bool(self.nastavitve.get("zaupana", True)) and link_krog.lahko_s_podpisom(self.device_id):
                seja = link_hub.seja_s_podpisom(hub, self.device_id, self.hub_fp(), self.device_ime) or ""
                if seja:
                    self._seja_http = (seja, time.monotonic() + SEJA_HTTP_HRANIMO_S, hub)
                    return seja
        except Exception as e:  # noqa: BLE001 - brez seje ostane zeton seznanitve
            print(f"[ControlBackend] Seja s podpisom ni uspela: {e}")
        return zeton

    def stanje_povezave(self) -> dict:
        """Stanje za Safeer OS: stanje ('povezan' | 'nov' | 'brez'), control=True, zaupana, hubi."""
        povezan = self.je_povezan()
        zaupana = bool(self.nastavitve.get("zaupana", True))
        if not povezan and self.zeton() and self.hub_url():
            if not self._povezovanje:
                threading.Thread(target=self.povezi_se, daemon=True).start()

        if povezan or (self.zeton() and self.hub_url()):
            stanje = "povezan"
        elif bool(self.nastavitve.get("brez_povezave")):
            stanje = "brez"
        else:
            stanje = "nov"

        # Iskanje hubov traja vec sekund; stanje ga ne caka (zacetna stran Safeer OS je cakala z njim).
        # None = prvo iskanje se tece; ko se konca, stran dobi dogodek in vprasa znova.
        hubi: Optional[List[dict]] = []
        if stanje != "povezan":
            hubi = self.hubi_brez_cakanja()

        return {
            "stanje": stanje,
            "control": True,
            "zaupana": zaupana,
            "predajanje": bool(self.nastavitve.get("predvajanje_za_naprave", True)),
            "hubi": hubi,
            "varno": True,
            "kakovost": "najvisja",
        }

    def stanje_linka(self) -> dict:
        """Stanje za window.__safeerLink.stanje v assets/link/link.js."""
        hub = self.hub_url()
        zeton = self.zeton()
        znan = bool(hub)
        seznanjen = bool(zeton and hub)
        povezan = self.je_povezan()

        ime_huba = self.nastavitve.get("hub_ime") or ""
        if not ime_huba and hub:
            try:
                ime_huba = hub.split("//", 1)[1].split(":", 1)[0]
            except Exception:
                ime_huba = hub

        return {
            "znan": znan,
            "seznanjen": seznanjen,
            "povezan": povezan,
            "hub": ime_huba or hub,
            "hub_url": hub,
            "naprava": self.device_ime,
            "imeNaprave": self.device_ime,
            "id": self.device_id,
            "idNaprave": self.device_id,
            "control": True,
            "varno": True,
            "kakovost": "najvisja",
            "sifriranje": "TLS 1.2+ (ECDHE/AEAD)",
            "navidezni_zaslon": True,
            "vKrogu": False,
            "clanKroga": False,
            "brezPovezaveIzbrano": bool(self.nastavitve.get("brez_povezave")),
            "zaupajOkno": bool(self.nastavitve.get("zaupana", True)),
            "brezPovezave": True,
            "lokalnaKoda": self.lokalna_koda,
            "deljeneMape": self.deljene_mape_za_vmesnik(),
            "standardneDeljene": self._standardne_mape_deljene(),
            "dovoljenja": dict(self.nastavitve.get("dovoljenja_naprav") or {}),
        }

    @staticmethod
    def _osnova_id(id_naprave: str) -> str:
        """Id brez pripone sorodnika (`n-<16 hex>-os` -> `n-<16 hex>`); drugi id-ji ostanejo."""
        i = str(id_naprave or "")
        return i[:-3] if i.endswith("-os") and len(i) == 21 and i.startswith("n-") else i

    def fizicna_naprava(self, id_naprave: str) -> str:
        """Fizicna naprava za id: polje `naprava` iz seznama huba (isti kljuc v krogu = ista naprava), sicer osnova id-ja.

        Telefon ali televizor je v Linku z dvema identitetama (zaslon/sredisce `n-…` in Safeer OS `n-…-os`);
        za uporabnika je to ENA naprava in pravice veljajo zanjo, ne za vsako identiteto posebej."""
        i = str(id_naprave or "")
        for n in self.naprave:
            if str(n.get("id") or "") == i and n.get("naprava"):
                return str(n["naprava"])
        return self._osnova_id(i)

    def sorodniki(self, id_naprave: str) -> List[str]:
        """Vsi znani id-ji iste fizicne naprave (vkljucno s tem)."""
        f = self.fizicna_naprava(id_naprave)
        ids = [str(n.get("id") or "") for n in self.naprave if str(n.get("id") or "") and self.fizicna_naprava(str(n.get("id"))) == f]
        for i in [str(id_naprave or "")] + [k for k in (self.nastavitve.get("dovoljenja_naprav") or {}) if self._osnova_id(k) == f]:
            if i and i not in ids:
                ids.append(i)
        return ids

    def dovoljenje_za(self, id_naprave: str) -> str:
        """Vrne profil dostopa naprave: polno, izbrano, zaslon ali vprasaj. Velja za fizicno napravo:
        izbira za eno identiteto telefona velja tudi za drugo (sicer bi isti telefon vprasal dvakrat)."""
        dovoljenja = self.nastavitve.get("dovoljenja_naprav") or {}
        profil = str(dovoljenja.get(str(id_naprave or "")) or "")
        if profil in ("polno", "izbrano", "zaslon"):
            return profil
        izbrani = [str(dovoljenja.get(s) or "") for s in self.sorodniki(id_naprave)]
        for kandidat in ("polno", "izbrano", "zaslon"):
            if kandidat in izbrani:
                return kandidat
        if profil == "vprasaj":
            return profil
        # Stare namestitve ohranijo delovanje do prvega seznama naprav. Vsaka dejansko
        # odkrita nova naprava pa spodaj dobi profil `vprasaj` in nima dostopa brez izbire.
        if any(str(n.get("id") or "") == str(id_naprave or "") for n in self.naprave):
            return "vprasaj"
        return "polno"

    def _sme_na_streznik(self, id_naprave: str, ves_disk: bool) -> bool:
        """Ali sme naprava na streznik datotek: cel disk samo s profilom `polno`, izbrane mape tudi z `izbrano`."""
        profil = self.dovoljenje_za(id_naprave)
        return profil == "polno" if ves_disk else profil in ("polno", "izbrano")

    def _preklici_zetone(self, id_naprave: str) -> None:
        """Takoj preklice zetone naprave na obeh streznikih datotek (znizanje pravic ali odstranitev)."""
        for d in list((getattr(self, "_datoteke", None) or {}).values()):
            try:
                d.streznik.preklici(id_naprave)
            except Exception:
                pass

    def nastavi_dovoljenje(self, id_naprave: str, profil: str) -> bool:
        id_naprave, profil = str(id_naprave or "").strip(), str(profil or "").strip().lower()
        if not id_naprave or profil not in ("polno", "izbrano", "zaslon"):
            return False
        dovoljenja = dict(self.nastavitve.get("dovoljenja_naprav") or {})
        prej = self.dovoljenje_za(id_naprave)
        # Pravica velja za fizicno napravo: vse njene identitete (zaslon in Safeer OS) dobijo isti profil.
        sorodniki = self.sorodniki(id_naprave)
        for s in sorodniki:
            dovoljenja[s] = profil
        self.nastavitve["dovoljenja_naprav"] = dovoljenja
        ok = self.shrani_nastavitve()
        if ok and profil != prej and profil != "polno":
            # Manj pravic kot prej: stari zetoni ne smejo veljati se do 12 h (pregled 29. 9. 2026, tocka 12).
            for s in sorodniki:
                self._preklici_zetone(s)
        if ok:
            for s in sorodniki:
                self._opozorjena_dovoljenja.discard(s)
            self._oddaj_dogodek("dovoljenja", dovoljenja)
            self._oddaj_dogodek("stanje", self.stanje_linka())
        return ok

    def _dejanje_dovoljeno(self, id_naprave: str, akcija: str) -> bool:
        if akcija == "status" or akcija in DEJANJA_SEZNAMI:
            # Seznami predvajanja so na vseh napravah v Linku enaki (Android jih da vsaki napravi v Linku); branje
            # seznamov ne odpre datotek, zaslona ali upravljanja, zato tihe uskladitve ne ustavlja vprasanje o pravicah.
            return True
        profil = self.dovoljenje_za(id_naprave)
        if profil == "polno":
            return True
        if profil in ("izbrano", "zaslon") and akcija in DEJANJA_SOLIDARNOST:
            return True
        if profil == "izbrano":
            return akcija.startswith("files.") or akcija in DEJANJA_PREDAJA
        if profil == "zaslon":
            return akcija in ("screenshot", "screen.capture", "screen.start", "screen.stop", "screen.status")
        return False

    def _lastni_naslovi(self) -> list:
        """Naslovi tega racunalnika za odgovor na `screen.start`. So dodatek: brez njih seja dela kot prej."""
        try:
            from core.link_zvok import lastni_naslovi
            return [str(n) for n in lastni_naslovi(self.hub_url())][:4]
        except Exception:  # noqa: BLE001
            return []

    # ------------------------------------------------------------------ Odkrivanje Hubov v omrezju
    def _lokalni_ip(self) -> str:
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"
        finally:
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass

    def _preisci_subnet_8990(self, prefix: str) -> List[str]:
        from concurrent.futures import ThreadPoolExecutor
        odprti: List[str] = []

        def testiraj(zadnji: int):
            ip = f"{prefix}.{zadnji}"
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.20)
                    if s.connect_ex((ip, 8990)) == 0:
                        odprti.append(ip)
            except Exception:
                pass

        try:
            with ThreadPoolExecutor(max_workers=35) as bazen:
                bazen.map(testiraj, range(1, 255))
        except Exception:
            pass

        return odprti

    def hubi_brez_cakanja(self) -> Optional[List[dict]]:
        """Zadnji znani seznam hubov TAKOJ; None, dokler prvo iskanje ni koncano.

        Zastarel seznam osvezi nit v ozadju (ena naenkrat). Ko se seznam spremeni ali je prvo iskanje koncano,
        poslusalci dobijo dogodek »povezava« - stran Safeer OS takrat stanje prebere znova."""
        velja = HUBI_VELJAJO_S if self._zadnji_hubi else HUBI_PRAZNI_VELJAJO_S
        svez = self._hubi_iskani and (time.time() - self._cas_hubi) < velja
        if not svez:
            with self._hubi_kljuc:
                zazeni = not self._hubi_isce
                self._hubi_isce = True
            if zazeni:
                threading.Thread(target=self._osvezi_hube, name="SafeerHubSearch", daemon=True).start()
        return list(self._zadnji_hubi) if self._hubi_iskani else None

    def _osvezi_hube(self) -> None:
        try:
            prvic = not self._hubi_iskani
            prej = [h.get("naslov") for h in self._zadnji_hubi]
            novi = self.hubi_v_omrezju(osvezi=True)
            if prvic or [h.get("naslov") for h in novi] != prej:
                self._oddaj_dogodek("povezava", None)
        except Exception as e:  # noqa: BLE001
            print(f"[ControlBackend] iskanje hubov: {e}")
        finally:
            self._hubi_isce = False

    def hubi_v_omrezju(self, osvezi: bool = False) -> List[dict]:
        """Poisce Safeer Hube v omrezju in POCAKA na izid (vec sekund) - za iskanje na zahtevo (poisci_hub).
        Za stanje vmesnika je hubi_brez_cakanja."""
        zdaj = time.time()
        if not osvezi and (zdaj - self._cas_hubi < HUBI_VELJAJO_S) and self._zadnji_hubi:
            return list(self._zadnji_hubi)

        najdeni = []
        try:
            mdns_seznam = link_hub.poisci_hube_mdns(cas=1.2)
            for h in mdns_seznam:
                najdeni.append({
                    "ime": h.get("ime") or h.get("naslov", ""),
                    "naslov": h["naslov"],
                    "tls": h.get("tls", True),
                    "fp": h.get("fp", ""),
                })
        except Exception as e:
            print(f"[ControlBackend] mDNS iskanje: {e}")

        kandidat_ipji: List[str] = []
        if self.hub_url():
            try:
                from urllib.parse import urlparse
                u = urlparse(self.hub_url())
                if u.hostname:
                    kandidat_ipji.append(u.hostname)
            except Exception:
                pass

        # Ta racunalnik in privzeto ime huba. (Tu so bili do 1.0.37 zapisani naslovi razvijalcevega doma: vsak
        # uporabnik jih je ob vsakem iskanju cakal po 0,8 s na shemo, najdeni hub na takem naslovu pa je dobil
        # ime razvijalceve naprave.)
        for h_ip in ["127.0.0.1", link_hub.PRIVZETI_GOSTITELJ]:
            if h_ip not in kandidat_ipji:
                kandidat_ipji.append(h_ip)

        # Ugotovi lokalni IP in dodaj subnet scan
        lokalni_ip = self._lokalni_ip()
        if lokalni_ip and "." in lokalni_ip and not lokalni_ip.startswith("127."):
            prefix = lokalni_ip.rsplit(".", 1)[0]
            najdeni_v_omrezju = self._preisci_subnet_8990(prefix)
            for ip in najdeni_v_omrezju:
                if ip not in kandidat_ipji:
                    kandidat_ipji.append(ip)

        znani = {n["naslov"] for n in najdeni}

        def preveri(ip: str) -> Optional[dict]:
            """En kandidat: najprej TLS (wss), nato brez (ws). Huba, ki ga je nasel ze mDNS, ne vprasamo znova
            (prej ga je zanka vprasala se brez TLS in cakala na zavrnitev)."""
            if not ip or f"wss://{ip}:8990/cast/ws" in znani or f"ws://{ip}:8990/cast/ws" in znani:
                return None
            if not _se_razresi(ip):
                return None                 # ime, ki ga v tem omrezju ni: ne cakamo nanj se pri vsaki shemi
            odtis = self.hub_fp() if (self.hub_url() and ip in self.hub_url()) else None
            for shema in ("wss", "ws"):
                naslov = f"{shema}://{ip}:8990/cast/ws"
                try:
                    if link_hub.je_hub(link_hub._osnova(naslov), timeout=0.8, odtis=odtis):
                        return {"ime": f"Safeer Hub ({ip})", "naslov": naslov, "tls": shema == "wss", "fp": odtis or ""}
                except Exception:
                    pass
            return None

        # Kandidate vprasamo hkrati: iskanje traja toliko kot najpocasnejsi, ne kot vsi skupaj.
        try:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=8) as bazen:
                najdeni.extend(h for h in bazen.map(preveri, list(dict.fromkeys(kandidat_ipji))) if h)
        except Exception as e:  # noqa: BLE001
            print(f"[ControlBackend] iskanje hubov po naslovih: {e}")

        # Varna vozlisca (TLS) imajo prednost; sicer ostane vrstni red najdbe (mDNS z imeni naprav prvi).
        najdeni.sort(key=lambda n: not n.get("tls", False))

        self._zadnji_hubi = najdeni
        self._cas_hubi = time.time()
        self._hubi_iskani = True
        return list(najdeni)

    def poisci_hub(self) -> Optional[dict]:
        hubi = self.hubi_v_omrezju(osvezi=True)
        # Prednost imajo varna TLS vozlisca
        tls_hubi = [h for h in hubi if h.get("tls")]
        izbrani = tls_hubi[0] if tls_hubi else (hubi[0] if hubi else None)
        if izbrani:
            self.nastavitve["hub_url"] = izbrani["naslov"]
            if izbrani.get("fp"):
                self.nastavitve["hub_fp"] = izbrani["fp"]
            self.shrani_nastavitve()
            self._oddaj_dogodek("hub", {"najden": True, "naslov": izbrani["naslov"], "ime": izbrani.get("ime", "")})
            return izbrani
        self._oddaj_dogodek("hub", {"najden": False, "naslov": "", "isce_naprej": False})
        return None

    def _sprotno(self):
        from core import link_sprotno
        return link_sprotno.sprotno()

    def _sprotni_streznik(self):
        """Streznik datotek samo za /live/ tokove (brez deljenih map): zeton naprave ni vezan na pravico do datotek."""
        from core import link_datoteke
        s = getattr(self, "_streznik_pretoka", None)
        if s is None:
            s = self._streznik_pretoka = link_datoteke.Datoteke(poti=[], tls_mapa=self.navidezni_zaslon.tls_mapa, ves_disk=False).streznik
        return s

    def _pretok(self, akcija: str, params: dict, posiljatelj: str) -> Dict[str, Any]:
        """video.stream / video.stream_stop / video.stream_status (core/link_sprotno.py)."""
        from core import link_sprotno
        sp = self._sprotno()
        if akcija == "video.stream_stop":
            return ({"ok": True, "message": "Ustavljeno"} if sp.ustavi_ukaz(str(params.get("id") or ""))
                    else {"ok": False, "message": "Ni takega toka", "code": "ni_opravila"})
        if akcija == "video.stream_status":
            st = sp.stanje(str(params.get("id") or ""))
            return {"ok": True, "message": "Stanje", "data": st} if st else {"ok": False, "message": "Ni takega toka", "code": "ni_opravila"}
        pomoc = (os_backend_win.zmogljivost().get("pomoc") or {})
        if pomoc.get("lahko") is False:
            return {"ok": False, "message": "Računalnik ta trenutek ne more pomagati", "code": str(pomoc.get("razlog") or "zaseden")}
        try:
            d = sp.zacni(params, posiljatelj, self._sprotni_streznik())
            print(f"[SafeerSprotno] video.stream za {posiljatelj}: {params.get('name')} -> {d.get('url')}", flush=True)
            return {"ok": True, "message": "Pretvarjam sproti", "data": d}
        except link_sprotno.NapakaPretoka as e:
            print(f"[SafeerSprotno] video.stream za {posiljatelj} zavrnjen: {e}", flush=True)
            return {"ok": False, "message": "Sprotno pretvarjanje ni mogoče", "code": str(e)}
        except Exception as e:  # noqa: BLE001
            print(f"[SafeerSprotno] video.stream napaka: {e}", flush=True)
            return {"ok": False, "message": str(e), "code": "napaka"}

    def _predaja(self, akcija: str, posiljatelj: str, params: Optional[dict] = None) -> Dict[str, Any]:
        """play.state / play.stop / play.offer: kaj Medijski center predvaja (os_app `state`), premor na zahtevo cilja
        in ponudba druge naprave (core/link_predvajanje.py)."""
        params = dict(params or {})
        from core import link_predvajanje
        from safeer_windows import predvajalnik_nadaljuj

        def stanje() -> Optional[dict]:
            m = self._medij("state", {})
            return (m.get("data") or None) if m and m.get("ok") else None

        def premor() -> bool:
            m = self._medij("pause", {})
            return bool(m and m.get("ok") and (m.get("data") or {}).get("status") == "playing")

        def zadnji() -> Optional[dict]:
            # Nazadnje gledani video s shranjenim mestom (nadaljuj.json), ce je se na disku.
            d = predvajalnik_nadaljuj.nalozi()
            for uri in sorted(d, key=lambda k: int((d[k] or {}).get("cas") or 0), reverse=True):
                pot = link_predvajanje.pot_iz_uri(uri)
                if pot and os.path.isfile(pot) and link_predvajanje.je_video(pot):
                    v = d[uri] or {}
                    return {"pot": pot, "ime": os.path.splitext(os.path.basename(pot))[0], "pozicija": v.get("polozaj") or 0,
                            "trajanje": v.get("trajanje") or 0, "zadnjic": v.get("cas") or 0}
            return None

        try:
            datoteke = self._datoteke_za(posiljatelj)
        except Exception:  # noqa: BLE001
            datoteke = None
        deli = lambda: bool(self.nastavitve.get("predvajanje_za_naprave", True))  # noqa: E731
        pr = link_predvajanje.Predvajanje(stanje, premor, datoteke, zadnji, deli)
        if akcija == "play.stop":
            return {"ok": True, "message": "Premor", "data": pr.ustavi()}
        if akcija == "play.offer":
            # "Poslji na napravo": ponudba caka na Sprejmi/Zavrni v tihi pasici (os_app); nic se ne zacne samo.
            if not deli():
                return {"ok": True, "message": "Ponudba", "data": {"queued": False, "reason": "izklopljeno"}}
            ime = next((str(n.get("ime") or "") for n in self.naprave if n.get("id") == posiljatelj), "") or str(params.get("from") or "")
            p = link_predvajanje.ponudba_iz(posiljatelj, ime, params)
            if p is None:
                return {"ok": True, "message": "Ponudba", "data": {"queued": False, "reason": "ni_vnosa"}}
            self.ponudba_cakajoca = p
            self._oddaj_dogodek("predajaPonudba", {"od": p["od"], "od_ime": p["od_ime"], "opis": link_predvajanje.opis_ponudbe(p)})
            return {"ok": True, "message": "Ponudba", "data": {"queued": True, "shown": "banner"}}
        return {"ok": True, "message": "Predvajanje", "data": pr.stanje(posiljatelj, self.hub_url())}

    def vzemi_ponudbo(self) -> Optional[dict]:
        from core import link_predvajanje
        p, self.ponudba_cakajoca = self.ponudba_cakajoca, None
        return p if p and time.time() - float(p.get("cas") or 0) < link_predvajanje.PONUDBA_VELJA_S else None

    def zavrni_ponudbo(self) -> None:
        self.ponudba_cakajoca = None

    # ------------------------------------------------------------------ ta racunalnik kot cilj vleka in izvor potiskanja
    def _naprave_z_daljincem(self) -> List[dict]:
        return [n for n in self.naprave if str(n.get("id") or "") and n.get("id") != self.device_id
                and "remote" in (n.get("zmoznosti") or n.get("capabilities") or [])]

    def uskladi_sezname(self, uskladi: Callable[[Callable[[dict], Optional[dict]]], bool]) -> bool:
        """Sezname predvajanja uskladi z vsemi napravami v Linku, ki imajo daljinec: uskladi(vprasaj) dobi funkcijo, ki
        eni napravi poslje `lists.get` (MediaCenter.seznami_uskladi). Vrne True, ce se je tukaj kaj spremenilo. Klic iz
        delovne niti; naprava, ki dejanja ne pozna ali ne odgovori, se preskoci."""
        if not self.je_povezan():
            return False
        spremenjeno = False
        for n in self._naprave_z_daljincem():
            # Samo naprave, ki same povedo, da znajo sezname ("lists"): starejsa razlicica dejanja ne pozna.
            if "lists" not in (n.get("zmoznosti") or n.get("capabilities") or []):
                continue
            id_naprave = str(n["id"])

            def vprasaj(parametri: dict, _id: str = id_naprave) -> Optional[dict]:
                r = self.ukaz_pocakaj(_id, "lists.get", parametri, cas=6.0)
                return r.get("data") if isinstance(r, dict) and r.get("ok") and isinstance(r.get("data"), dict) else None
            try:
                if uskladi(vprasaj):
                    spremenjeno = True
            except Exception as e:  # noqa: BLE001
                print(f"[SafeerSeznami] {id_naprave}: {e}", flush=True)
        return spremenjeno

    def predaja_ponudbe(self) -> Dict[str, Any]:
        """"Nadaljuj z druge naprave" na tem racunalniku: vse naprave z daljincem vprasa hkrati (play.state, 3 s) in vrne,
        kar igrajo ali so nazadnje gledale (najprej, kar igra) - isti zapis kot Linux Control (Predaja)."""
        from core import link_predvajanje
        naprave = self._naprave_z_daljincem()
        izidi: Dict[str, dict] = {}

        def vprasaj(n: dict) -> None:
            try:
                izidi[n["id"]] = self.ukaz_pocakaj(str(n["id"]), "play.state", {}, cas=3.0)
            except Exception as e:  # noqa: BLE001
                izidi[n["id"]] = {"ok": False, "message": str(e)}
        niti = [threading.Thread(target=vprasaj, args=(n,), daemon=True) for n in naprave]
        for t in niti:
            t.start()
        for t in niti:
            t.join(4.0)
        ponudbe = []
        for n in naprave:
            r = izidi.get(n["id"]) or {}
            d = r.get("data") if r.get("ok") and isinstance(r.get("data"), dict) else None
            if not d or not isinstance(d.get("item"), dict) or not (d.get("playing") or d.get("last")):
                continue
            if link_predvajanje.ponudba_iz(n["id"], "", d) is None:
                continue
            ponudbe.append({"naprava": {"id": n["id"], "ime": n.get("ime") or n["id"]},
                            "naslov": str(d["item"].get("naslov") or ""), "igra": bool(d.get("playing")) and bool(d.get("is_playing", True)),
                            "nazadnje": bool(d.get("last")), "position_ms": int(d.get("position_ms") or 0),
                            "duration_ms": int(d.get("duration_ms") or 0),
                            "opis": link_predvajanje.opis_ponudbe({"item": d["item"], "position_ms": d.get("position_ms") or 0}), "podatki": d})
        ponudbe.sort(key=lambda p: (not p["igra"], p["nazadnje"]))
        return {"ok": True, "ponudbe": ponudbe}

    def predaja_prevzemi(self, id_naprave: str, podatki: dict, ustavi_tam: bool) -> Dict[str, Any]:
        """Izbrana ponudba igra tu (kot sprejeto "Poslji na napravo"); izvor igra naprej, razen ce uporabnik izbere "ustavi tam"."""
        from core import link_predvajanje
        ime = next((str(n.get("ime") or "") for n in self.naprave if n.get("id") == id_naprave), id_naprave)
        p = link_predvajanje.ponudba_iz(id_naprave, ime, podatki if isinstance(podatki, dict) else {})
        if p is None:
            return {"ok": False, "koda": "ni_vnosa"}
        if ustavi_tam:
            try:
                self.ukaz_pocakaj(id_naprave, "play.stop", {}, cas=5.0)
            except Exception:  # noqa: BLE001
                pass
        self.ponudba_cakajoca = p
        self._oddaj_dogodek("predajaSprejmi", {})
        return {"ok": True}

    def predaja_ponudi(self, id_naprave: str) -> Dict[str, Any]:
        """"Poslji na napravo" s tega racunalnika: kar Medijski center igra, napravi (zeton streznika datotek zanjo)."""
        st = self._predaja("play.state", id_naprave).get("data") or {}
        if not st.get("playing"):
            return {"ok": False, "koda": str(st.get("reason") or "ni_predvajanja")}
        parametri = {k: st[k] for k in ("item", "position_ms", "duration_ms", "server", "server_device") if k in st}
        parametri["from"] = str(self.device_ime or "")
        from core import link_predvajanje
        return link_predvajanje.izid_ponudbe(self.ukaz_pocakaj(id_naprave, "play.offer", parametri, cas=8.0))

    def _datoteke_za(self, posiljatelj: str):
        """Deljene mape za napravo: en streznik za omejen dostop in en za cel disk (dovoljenje "polno").

        Prej je vsak `files.list` naredil nov streznik na novih vratih (ostajali so odprti), zeton
        prejsnjega pa je s tem nehal veljati sredi predvajanja. Zdaj oba ostaneta in ju streze tudi Hub
        (/cast/d/), da tok tece tudi prek Global Linka."""
        from core import link_datoteke
        polno = self.dovoljenje_za(posiljatelj) == "polno"
        shramba = getattr(self, "_datoteke", None)
        if shramba is None:
            shramba = self._datoteke = {}
        if not polno and True in shramba:
            # Naprava nima (vec) dostopa do celega diska: njen zeton za ta streznik takoj preklicemo.
            shramba[True].streznik.preklici(posiljatelj)
        d = shramba.get(polno)
        if d is None:
            d = link_datoteke.Datoteke(poti=self.deljene_mape(), tls_mapa=self.navidezni_zaslon.tls_mapa, ves_disk=polno)
            # Zeton velja le, dokler ima naprava se pravico do tega streznika in je v krogu - preveri se ob
            # vsaki zahtevi (tudi med predvajanjem), ne sele ob naslednjem seznamu ali po 12 urah.
            privzeto = d.streznik.umaknjena
            d.streznik.umaknjena = lambda n, _p=polno, _u=privzeto: _u(n) or not self._sme_na_streznik(n, _p)
            shramba[polno] = d
        else:
            d.mape.nastavi(self.deljene_mape())
        return d

    def zagotovi_lokalni_hub(self) -> Optional[dict]:
        """Če v hiši ni Huba, ga ta računalnik varno prevzame in se nanj vpiše.

        Tako Safeer Control na dveh računalnikih ni odvisen od prižganega TV-ja.
        Lastni Control dobi žeton neposredno od Huba v istem procesu (brez kode in brez omrežja).
        """
        if self._lokalni_hub is not None and self._lokalni_hub.tece():
            return {"naslov": self.hub_url(), "fp": self._lokalni_hub.odtis, "lokalni": True}
        streznik = link_hub_streznik.HubStreznik()
        # Deljene mape tudi prek Huba (/cast/d/): po Global Linku pride samo povezava do vrat Huba.
        streznik.datoteke = lambda: [x.streznik for x in list((getattr(self, "_datoteke", None) or {}).values())]
        if not self._zazeni_sredisce(streznik) or streznik.hub is None:
            return None
        self._lokalni_hub = streznik
        naslov = f"wss://127.0.0.1:{streznik.vrata}/cast/ws"
        try:
            # Hub tece v nasem procesu: zeton dobimo neposredno od njega. Prej se je Control ob vsakem zagonu z
            # lastnim Hubom seznanil s kodo po omrezju (SPAKE2 na obeh koncih istega procesa: 2,6-4,8 s, izmerjeno
            # 5. 10. 2026) in pri tem Hubu za stalno zamenjal obvestilo o kodi (ob_kodi) z zbiralnikom - nova
            # naprava, ki se je hotela povezati s kodo, je na tem racunalniku ni vec videla.
            zeton = streznik.hub.zeton_lastne_naprave(self.device_id, self.device_ime)
            if not zeton:
                raise RuntimeError("lokalna_prijava_ni_stekla")
            self.nastavitve.update({
                "control_token": zeton,
                "hub_fp": streznik.odtis,
                "hub_url": naslov,
                "hub_ime": "Ta računalnik · Safeer Link",
                "brez_povezave": False,
            })
            self.shrani_nastavitve()
            self._oddaj_dogodek("hub", {"najden": True, "naslov": naslov,
                                        "ime": "Ta računalnik · Safeer Link", "lokalni": True})
            return {"naslov": naslov, "fp": streznik.odtis, "lokalni": True}
        except Exception as exc:
            print(f"[ControlBackend] Lokalni Safeer Link se ni zagnal: {exc}")
            streznik.ustavi()
            self._lokalni_hub = None
            return None

    @staticmethod
    def _zazeni_sredisce(streznik) -> bool:
        """Zazene sredisce; ce ne gre, pocaka in poskusi znova - vrata lahko se drzi kopija programa, ki se zapira.

        Sredisce si na Windows vrat ne deli vec z drugim procesom (core/link_hub_streznik.nastavitve_vticnika). Prej
        je nova kopija ob posodobitvi ali hitrem ponovnem zagonu "uspesno" poslusala na istih vratih kot stara; zdaj
        pocaka, da jih stara sprosti. Klic tece v delovni niti (povezi_se, povezi_naprave), vmesnika ne ustavi."""
        if streznik.zazeni():
            return True
        for premor in POSKUSI_SREDISCA:
            time.sleep(premor)
            if streznik.zazeni():
                print("[ControlBackend] Sredisce se je zagnalo po cakanju na vrata.")
                return True
        return False

    def nadzor(self, cilj: str, dejanje: str, polozaj: Optional[float] = None, glasnost: Optional[float] = None) -> bool:
        """Ukazi za predvajanje in daljinec (seek, volume, pause, play, play_pause)."""
        if self._povezava:
            return self._povezava.nadzor(cilj, dejanje, polozaj, glasnost)
        return False

    # ------------------------------------------------------------------ Seznanjanje
    def zacni_seznanitev(self) -> dict:
        hub = self.hub_url()
        if not hub:
            h = self.poisci_hub()
            hub = h["naslov"] if h else ""
        if not hub:
            self._oddaj_dogodek("napaka", {"koda": "ni_huba", "sporocilo": "Ni najdenega Safeer Huba v omrezju."})
            return {"ok": False, "napaka": "ni_huba"}

        try:
            zacetek = link_hub.zacni_seznanitev(hub, self.device_id, self.device_ime)
            if not zacetek or (isinstance(zacetek, dict) and zacetek.get("napaka")):
                razlog = (zacetek or {}).get("napaka") or "seznanitev_ni_stekla"
                self._oddaj_dogodek("napaka", {"koda": razlog, "sporocilo": f"Seznanitev ni uspela ({razlog})."})
                return {"ok": False, "napaka": razlog}
            self._prijava = zacetek
            odziv = {"nacin": "koda_na_gostitelju", "koda": ""}
            self._oddaj_dogodek("nacin", odziv)
            return {"ok": True, "prijava": zacetek}
        except Exception as e:
            print(f"[ControlBackend] Napaka pri zacetku seznanitve: {e}")
            self._oddaj_dogodek("napaka", {"koda": "napaka", "sporocilo": str(e)})
            return {"ok": False, "napaka": str(e)}

    def potrdi_kodo(self, koda: str) -> bool:
        koda_cista = "".join(ch for ch in str(koda) if ch.isdigit())
        if len(koda_cista) < 4:
            self._oddaj_dogodek("kodaNiSprejeta", {"razlog": "prekratka_koda"})
            return False

        # Preveri lokalno kodo računalnika
        if koda_cista == self.lokalna_koda:
            self._oddaj_dogodek("seznanitev", True)
            self._oddaj_dogodek("stanje", self.stanje_linka())
            return True

        hub = self.hub_url()
        prijava = self._prijava
        if not hub or not prijava:
            h = self.poisci_hub()
            hub = h["naslov"] if h else ""
            if hub:
                self.zacni_seznanitev()
                prijava = self._prijava
            if not hub or not prijava:
                self._oddaj_dogodek("kodaNiSprejeta", {"razlog": "prijava_ne_obstaja"})
                return False

        try:
            zeton, razlog = link_hub.potrdi_kodo(hub, prijava, self.device_id, koda_cista)
            if not zeton:
                self._oddaj_dogodek("kodaNiSprejeta", {"razlog": razlog or "napacna_koda"})
                return False

            self._prijava = None
            self.nastavitve["control_token"] = zeton
            self.nastavitve["hub_fp"] = str(prijava.get("odtis", ""))
            self.nastavitve["hub_url"] = hub
            self.nastavitve["brez_povezave"] = False

            seznanitve = self.nastavitve.get("seznanitve", {})
            if isinstance(seznanitve, dict) and self.nastavitve["hub_fp"]:
                seznanitve[self.nastavitve["hub_fp"]] = {"token": zeton, "hub_url": hub}
                self.nastavitve["seznanitve"] = seznanitve

            self.shrani_nastavitve()
            self._oddaj_dogodek("seznanitev", True)
            self._oddaj_dogodek("stanje", self.stanje_linka())

            threading.Thread(target=self.povezi_se, daemon=True).start()
            return True
        except Exception as e:
            print(f"[ControlBackend] Napaka pri potrditvi kode: {e}")
            self._oddaj_dogodek("kodaNiSprejeta", {"razlog": str(e)})
            return False

    def prekini_seznanitev(self) -> None:
        self._prijava = None

    # ------------------------------------------------------------------ QR Seznanjanje
    def zacni_qr(self) -> None:
        self._qr_rod += 1
        rod = self._qr_rod

        # Takoj pošlji lokalno 6-mestno kodo tega računalnika
        self._oddaj_dogodek("lokalnaKoda", self.lokalna_koda)

        # Takoj generiraj in pošlji veljaven QR SVG za ta računalnik
        lokalni_ip = self._lokalni_ip()
        povezava_lokalna = f"https://safeer.si/p#i={self.device_id}&s={self.lokalna_koda}&ip={lokalni_ip}"
        svg_lokalni = link_hub.qr_svg(povezava_lokalna)
        if svg_lokalni:
            self._oddaj_dogodek("qr", {"svg": svg_lokalni, "velja": 300, "lokalno": True, "ip": lokalni_ip})

        def delo():
            hub = self.hub_url()
            if not hub:
                h = self.poisci_hub()
                hub = h["naslov"] if h else ""
            if not hub:
                self._oddaj_dogodek("qrInfo", {"sporocilo": "Povezava pripravljena. Iščem Safeer Hub v omrežju …"})
                return

            try:
                prijava = link_hub.zacni_qr(hub, self.device_id, self.device_ime)
                if not prijava or prijava.get("napaka"):
                    return

                if rod != self._qr_rod:
                    link_hub.preklici_qr(hub, prijava, self.device_id)
                    return

                svg = link_hub.qr_svg(prijava["povezava"])
                self._qr = prijava
                self._oddaj_dogodek("qr", {"svg": svg, "velja": prijava.get("velja", 120), "lokalno": False})

                konec = time.time() + max(30, int(prijava.get("velja", 120)) - 15)
                while rod == self._qr_rod:
                    time.sleep(1.5)
                    if rod != self._qr_rod:
                        return
                    if time.time() > konec:
                        self.zacni_qr()
                        return
                    zeton, razlog = link_hub.stanje_qr(hub, prijava, self.device_id)
                    if zeton:
                        self._qr = None
                        self._qr_rod += 1
                        self.nastavitve["control_token"] = zeton
                        self.nastavitve["hub_fp"] = prijava.get("odtis", "")
                        self.nastavitve["hub_url"] = hub
                        self.nastavitve["brez_povezave"] = False
                        self.shrani_nastavitve()
                        self._oddaj_dogodek("seznanitev", True)
                        self._oddaj_dogodek("stanje", self.stanje_linka())
                        threading.Thread(target=self.povezi_se, daemon=True).start()
                        return
                    if razlog == "qr_ne_obstaja":
                        self.zacni_qr()
                        return
            except Exception as e:
                print(f"[ControlBackend] QR napaka: {e}")

        threading.Thread(target=delo, daemon=True).start()

    def prekini_qr(self) -> None:
        self._qr_rod += 1
        prijava = self._qr
        hub = self.hub_url()
        self._qr = None
        if prijava and hub:
            threading.Thread(target=lambda: link_hub.preklici_qr(hub, prijava, self.device_id), daemon=True).start()

    # ------------------------------------------------------------------ Vabilo za novo napravo
    def zacni_vabilo(self) -> None:
        """Pripravi skupno QR in 6-mestno vabilo sredisca v delovni niti."""
        threading.Thread(target=self._zacni_vabilo, name="safeer-link-vabilo", daemon=True).start()

    def _zacni_vabilo(self) -> None:
        """Obnavlja isto vabilo, iz katerega stran dobi QR, pin in veljavnost."""
        self._vabilo_rod += 1
        rod = self._vabilo_rod
        naslov, zeton, odtis = self.hub_url(), self._zeton_http(), self.hub_fp()
        if not naslov or not zeton:
            self._oddaj_dogodek("vabilo", {"napaka": "ni_seznanjena"})
            return

        staro = self._vabilo
        vabilo = link_hub.povabi(naslov, zeton, odtis, str((staro or {}).get("qr_id") or ""))
        if rod != self._vabilo_rod:
            if vabilo.get("qr_id"):
                link_hub.preklici_vabilo(naslov, zeton, odtis, str(vabilo["qr_id"]))
            return
        if vabilo.get("napaka"):
            self._oddaj_dogodek("vabilo", vabilo)
            return

        self._vabilo = vabilo
        self._oddaj_dogodek("vabilo", {
            "svg": link_hub.qr_svg(str(vabilo["povezava"])),
            "velja": int(vabilo.get("velja") or 300),
            "pin": str(vabilo.get("pin") or ""),
        })
        konec = time.time() + max(30, int(vabilo.get("velja") or 300) - 20)
        while rod == self._vabilo_rod:
            time.sleep(2.0)
            if rod != self._vabilo_rod:
                return
            if time.time() > konec:
                self.zacni_vabilo()
                return
            stanje = link_hub.stanje_vabila(naslov, zeton, odtis, str(vabilo["qr_id"]))
            if stanje.get("pridruzen"):
                self._vabilo = None
                self._oddaj_dogodek("vabilo", {"pridruzen": str(stanje["pridruzen"])})
                # Okno ostane pripravljeno za naslednjo napravo z novim vabilom.
                self.zacni_vabilo()
                return
            if not stanje.get("caka") and not stanje.get("napaka"):
                self.zacni_vabilo()
                return

    def prekini_vabilo(self) -> None:
        """Zapre odprto vabilo in ga preklice tudi na srediscu."""
        self._vabilo_rod += 1
        staro, self._vabilo = self._vabilo, None
        naslov, odtis = self.hub_url(), self.hub_fp()
        if staro and naslov:
            def preklici() -> None:
                zeton = self._zeton_http()
                if zeton:
                    link_hub.preklici_vabilo(naslov, zeton, odtis, str(staro["qr_id"]))

            threading.Thread(target=preklici, name="safeer-link-vabilo-preklic", daemon=True).start()

    def povezi_naprave(self) -> None:
        self.nastavitve["brez_povezave"] = False
        self.shrani_nastavitve()
        def pripravi() -> None:
            if not self.hub_url():
                najden = self.poisci_hub()
                if not najden:
                    self.zagotovi_lokalni_hub()
            if self.zeton() and self.hub_url():
                self.povezi_se()
            self._oddaj_dogodek("stanje", self.stanje_linka())
            self.zacni_vabilo()

        threading.Thread(target=pripravi, name="safeer-link-priprava", daemon=True).start()
        self._oddaj_dogodek("brezPovezave", False)
        self._oddaj_dogodek("stanje", self.stanje_linka())

    def koncaj(self) -> None:
        self.prekini_vabilo()
        self.prekini_qr()
        self.koncaj_deljenje_zaslona()
        if self.povezava is not None:
            try:
                self.povezava.zapri()
            except Exception:
                pass
            self.povezava = None
        if getattr(self, "_mesh", None) is not None:
            self._mesh.ustavi()
            self._mesh = None
        if getattr(self, "_oglas", None) is not None:
            self._oglas.koncaj()
            self._oglas = None
        if self._lokalni_hub is not None:
            self._lokalni_hub.ustavi()
            self._lokalni_hub = None
        for d in list((getattr(self, "_datoteke", None) or {}).values()):
            try:
                d.ustavi()
            except Exception:
                pass
        self._datoteke = {}

    def pozabi_napravo(self) -> bool:
        hub = self.hub_url()
        zeton = self._zeton_http()
        odtis = self.hub_fp()
        if hub and zeton:
            try:
                link_hub.odidi(hub, zeton, odtis)
            except Exception:
                pass

        if self.povezava is not None:
            try:
                self.povezava.zapri()
            except Exception:
                pass
            self.povezava = None

        self.naprave = []
        for k in ("control_token", "hub_url", "hub_fp", "seznanitve", "zaupana", "seja_prijave"):
            self.nastavitve.pop(k, None)
        self.shrani_nastavitve()

        self._oddaj_dogodek("pozabljeno", True)
        self._oddaj_dogodek("naprave", [])
        self._oddaj_dogodek("stanje", self.stanje_linka())
        return True

    def nastavi_zaupanje(self, zaupaj: bool) -> bool:
        self.nastavitve["zaupana"] = bool(zaupaj)
        self.shrani_nastavitve()
        self._oddaj_dogodek("stanje", self.stanje_linka())
        return True

    def nastavi_predajanje(self, deli: bool) -> bool:
        """Stikalo "Predvajanje za druge naprave" (Safeer OS, poleg Zaupaj): ali druge naprave smejo vprasati, kaj tu igra,
        nadaljevati tukaj in poslati sem (play.state / play.stop / play.offer). Isti kljuc kot v pladnju Controla za Linux."""
        self.nastavitve["predvajanje_za_naprave"] = bool(deli)
        self.shrani_nastavitve()
        return bool(deli)

    def nadaljuj_brez_povezave(self) -> bool:
        self.nastavitve["brez_povezave"] = True
        self.shrani_nastavitve()
        self._oddaj_dogodek("brezPovezave", True)
        self._oddaj_dogodek("stanje", self.stanje_linka())
        return True

    # ------------------------------------------------------------------ Link Mesh (docs/LINK-MESH.md)
    def _zagotovi_mesh(self) -> None:
        """Link Mesh: ta racunalnik gosti SVOJ Hub, se oglasi (mDNS mesh=mesh1) in se sam poveze s Hubi
        drugih naprav iz kroga zaupanja. Control se poveze na lastni Hub; izpad televizorja ne podre nicesar.
        Samo zaupan racunalnik, ki je v krogu zaupanja (prijava s podpisom kljuca)."""
        if not link_hub_streznik.mesh_vklopljen() or not self.nastavitve.get("zaupana", True):
            return
        try:
            from core import link_krog
            if not link_krog.lahko_s_podpisom(self.device_id):
                return
        except Exception:
            return
        lokalni = self._lokalni_hub
        if lokalni is None or not lokalni.tece():
            if self.zagotovi_lokalni_hub() is None:
                return
            lokalni = self._lokalni_hub
        if getattr(self, "_mesh", None) is not None or lokalni is None or lokalni.hub is None:
            return
        from core import link_mesh
        nas_id = link_hub_streznik.id_za_oglas()
        if not nas_id:
            return
        lokalni.hub.nas_id = nas_id
        from core import link_krog
        self._mesh = link_mesh.MeshPovezovalec(
            lokalni.hub, nas_id, self.device_ime,
            pot_znanih=os.path.join(link_krog._mapa_nastavitev(), "mesh-sosedje.json"),
            vrata=lambda s=lokalni: s.vrata if s.tece() else 0)
        self._mesh.zazeni()
        print(f"[ControlBackend] Link Mesh: vozlisce {nas_id} na vratih {lokalni.vrata}")
        self._zacni_oglas(lokalni, nas_id)
        # Pomocnik sprotnega pretvarjanja potrebuje ffmpeg: ce ga ni, ga prenesemo v ozadju (pripeta LGPL gradnja).
        try:
            from safeer_windows import ffmpeg_win
            ffmpeg_win.zagotovi_v_ozadju()
        except Exception as e:  # noqa: BLE001
            print(f"[SafeerSprotno] ffmpeg: priprava ni uspela ({e})")

    def _zacni_oglas(self, lokalni, nas_id: str) -> None:
        """Oglas mDNS (da nas najdejo naprave, ki nas se ne poznajo) v svoji niti.

        Uvoz knjiznice in registracija trajata vec sekund (izmerjeno 5. 10. 2026: 2,3-8,1 s); klic znanih sosedov in
        prijava lastnega Controla sta prej cakala nanju, ceprav oglasa ne potrebujeta."""
        oglas = link_hub_streznik.Oglas()
        self._oglas = oglas
        vrata, odtis, ime = lokalni.vrata, lokalni.odtis, self.device_ime

        def zacni() -> None:
            try:
                oglas.zacni(vrata, odtis, nas_id, ime)
            except Exception as e:  # noqa: BLE001
                print(f"[ControlBackend] Oglas mDNS se ni zagnal: {e}")
            if self._oglas is not oglas:
                # Med registracijo smo se ustavili (koncaj): oglasa za ugasnjen Hub ne pustimo v omrezju.
                oglas.koncaj()

        threading.Thread(target=zacni, name="safeer-link-oglas", daemon=True).start()

    # ------------------------------------------------------------------ Trajna WebSocket povezava
    def povezi_ob_zagonu(self, vedno: bool = False) -> bool:
        """Ob zagonu programa: povezovanje s Safeer Linkom se zacne takoj, v svoji niti.

        Prej ga je sprozila sele nalozena zacetna stran (ko je vprasala za stanje), pri zagonu v ozadju pa je teklo
        v glavni niti in zadrzalo zanko dogodkov. Racunalnik, ki se ni povezan z nobenim Hubom, se ne povezuje sam
        (vedno=True: zagon v ozadju, kjer je povezovanje ze prej steklo brez tega pogoja)."""
        if self._povezovanje or self.je_povezan():
            return False
        if not vedno and not (self.zeton() and self.hub_url()):
            return False
        threading.Thread(target=self.povezi_se, name="safeer-link-zagon", daemon=True).start()
        return True

    def povezi_se(self) -> bool:
        # Samo eno povezovanje naenkrat: zastavica se postavi takoj. Prej sele po zagonu lastnega Huba (vec sekund),
        # zato sta dva hkratna klica (stran in gumb) lahko oba zaganjala Hub.
        with self._povezi_kljuc:
            if self._povezovanje or self.je_povezan():
                return True
            self._povezovanje = True
        try:
            return self._povezi_se()
        finally:
            self._povezovanje = False

    def _povezi_se(self) -> bool:
        try:
            self._zagotovi_mesh()
        except Exception as e:  # noqa: BLE001
            print(f"[ControlBackend] Link Mesh se ni zagnal: {e}")

        hub = self.hub_url()
        zeton = self.zeton()
        odtis = self.hub_fp()
        if not (hub and zeton):
            return False

        try:
            if self.povezava is not None:
                try:
                    self.povezava.zapri()
                except Exception:
                    pass
                self.povezava = None

            p = link_hub.Povezava(
                ws_naslov=hub,
                zeton=zeton,
                device_id=self.device_id,
                ime=self.device_ime,
                sinhronizira=False,
                odtis=odtis or None,
                dodatne_zmoznosti=["files", "remote", "desktop", "screen", "apps", "chat", "lists"]
                # Magnet povezave z drugih naprav odpre Safeer OS na tem racunalniku.
                + (["magnet"] if self.magnet_na_voljo() or self.tok_torrenta_na_voljo() else []),
                katalog=self.navidezni_zaslon.katalog_aplikacij,
                v_krog=bool(self.nastavitve.get("zaupana", True)),
            )
            p.ob_sporocilu = self._na_sporocilo
            p.ob_stanju = self._na_stanje_povezave
            p.povezi()
            self.povezava = p
            if self.tok_torrenta_na_voljo():
                # Prenosi za naprave, ki jih 48 ur nihce ni predvajal, se odstranijo sami (kot na Linuxu).
                try:
                    from core import link_datoteke
                    link_datoteke.zazeni_ciscenje()
                except Exception:  # noqa: BLE001
                    pass
            return True
        except Exception as e:
            print(f"[ControlBackend] Povezava s Hubom ni uspela: {e}")
            return False

    def _na_stanje_povezave(self, povezan: bool) -> None:
        self._oddaj_dogodek("povezava", povezan)
        self._oddaj_dogodek("stanje", self.stanje_linka())

    def _na_sporocilo(self, sporocilo: dict) -> None:
        if not isinstance(sporocilo, dict):
            return
        vrsta = sporocilo.get("type", "")

        if vrsta == "cast.devices":
            seznam = []
            nova_brez_dovoljenja = []
            dovoljenja = dict(self.nastavitve.get("dovoljenja_naprav") or {})
            for d in sporocilo.get("devices") or []:
                # Zanka od Huba, ki tece drugje, je naslov TISTEGA Huba (core/link_hub_streznik.naslov_za_povezavo).
                naslov = link_hub_streznik.naslov_za_povezavo(d.get("ip") or d.get("naslov"), self.hub_url())
                seznam.append({
                    "id": d.get("id", ""),
                    "ime": d.get("name", ""),
                    "vloga": d.get("role", "receiver"),
                    "zmoznosti": d.get("capabilities") or [],
                    "platforma": d.get("platform") or "",
                    "vrsta": d.get("kind") or "",
                    "naslov": naslov,
                    "ip": naslov,
                    "zasedenaOd": d.get("busy_by") or d.get("zasedenaOd") or "",
                    "zasedenaOdIme": d.get("busy_by_name") or d.get("zasedenaOdIme") or "",
                    "aplikacije": d.get("apps") if isinstance(d.get("apps"), dict) else {},
                    "ta": d.get("id") == self.device_id,
                    "naprava": d.get("device") or "",
                })
                id_n = str(d.get("id") or "")
                if id_n and id_n != self.device_id and id_n not in dovoljenja:
                    # Druga identiteta ze znane fizicne naprave (telefon: zaslon + Safeer OS) podeduje
                    # njeno izbiro - uporabnika za isti telefon ne vprasamo dvakrat.
                    fizicna = str(d.get("device") or "") or self._osnova_id(id_n)
                    podedovano = ""
                    for drug_id, drug_profil in dovoljenja.items():
                        if drug_id != id_n and drug_profil in ("polno", "izbrano", "zaslon") and (
                                self._osnova_id(drug_id) == fizicna or any(
                                    str(e.get("id") or "") == drug_id and str(e.get("device") or "") == fizicna
                                    for e in (sporocilo.get("devices") or []))):
                            podedovano = drug_profil
                            break
                    if podedovano:
                        dovoljenja[id_n] = podedovano
                        self.nastavitve["dovoljenja_naprav"] = dovoljenja
                        self.shrani_nastavitve()
                        continue
                    dovoljenja[id_n] = "vprasaj"
                    nova_brez_dovoljenja.append({"id": id_n, "ime": d.get("name") or id_n})
            if nova_brez_dovoljenja:
                self.nastavitve["dovoljenja_naprav"] = dovoljenja
                self.shrani_nastavitve()
            self.naprave = seznam
            self._oddaj_dogodek("naprave", self.naprave)
            self._oddaj_dogodek("stanje", self.stanje_linka())
            for naprava in nova_brez_dovoljenja:
                if naprava["id"] not in self._opozorjena_dovoljenja:
                    self._opozorjena_dovoljenja.add(naprava["id"])
                    self._oddaj_dogodek("dovoljenjeZahtevano", naprava)

        elif vrsta in ("control.result", "control.ack"):
            ref = str(sporocilo.get("ref_id", "") or sporocilo.get("id", "") or "")
            payload = sporocilo.get("payload")
            telo = dict(payload) if isinstance(payload, dict) else {}
            if ref in self._cakajoci:
                event, res_holder = self._cakajoci[ref]
                if vrsta == "control.result":
                    res_holder[0] = telo or sporocilo
                    event.set()
                elif str(sporocilo.get("status") or "") != "accepted":
                    # "accepted" confirms only that the hub forwarded the RPC;
                    # the device's data arrives later as control.result.
                    # Rejections, on the other hand, are terminal responses.
                    res_holder[0] = {
                        "ok": False,
                        "koda": str(sporocilo.get("error_code") or sporocilo.get("error") or sporocilo.get("status") or "zavrnjeno"),
                        "message": str(sporocilo.get("error") or sporocilo.get("message") or "Ukaz je bil zavrnjen."),
                    }
                    event.set()
            odziv_podatki = dict(telo)
            odziv_podatki["ref"] = ref
            odziv_podatki["ref_id"] = ref
            if "ok" not in odziv_podatki and vrsta == "control.ack":
                odziv_podatki["ok"] = True
            self._oddaj_dogodek("ukaz", odziv_podatki)

        elif vrsta == "control.command":
            self._obdelaj_nadzorni_ukaz(sporocilo)

        elif vrsta == "share.text":
            self._oddaj_dogodek("besedilo", sporocilo.get("payload"))

        elif vrsta == "chat.send":
            if self.ob_klepetu is not None:
                try:
                    self.ob_klepetu(sporocilo)
                except Exception as e:  # noqa: BLE001
                    print(f"[ControlBackend] Klepet: {e}")

        elif vrsta == "chat.ack":
            vnos = self._klepet_cakajoci.get(str(sporocilo.get("ref_id") or ""))
            if vnos is not None:
                stanje = str(sporocilo.get("status") or "")
                vnos[1] = stanje if stanje in ("accepted", "queued") else str(sporocilo.get("error_code") or stanje or "zavrnjeno")
                vnos[0].set()

        elif vrsta in ("share.screen", "share.file"):
            self._prejmi_deljenje(vrsta, sporocilo)

        elif vrsta == "cast.status":
            self._oddaj_dogodek("predvajanje", sporocilo.get("payload"))

        elif vrsta == "pair.code":
            # Nova naprava caka na kodo; sredisce jo poslje napravam v Linku. Kodo lastnega sredisca je ze pokazalo
            # sredisce samo (ob_kodi), zato jo tu pokazemo samo, kadar smo prijavljeni na tuje. Neveljavne nikoli.
            telo = sporocilo.get("payload") if isinstance(sporocilo.get("payload"), dict) else {}
            koda = str(telo.get("code") or "")
            if len(koda) == 6 and koda.isascii() and koda.isdigit() and not self._gostimo_lokalno():
                link_hub_streznik._obvestilo_kode(str(telo.get("name") or "")[:64], koda)

    def _prejmi_deljenje(self, vrsta: str, sporocilo: dict) -> None:
        """Zaslon ali datoteka z druge naprave (npr. \"Odpri tukaj\" s televizorja, datoteka s telefona)."""
        od = str(sporocilo.get("sender_name") or sporocilo.get("sender") or "naprava")
        telo = sporocilo.get("payload") if isinstance(sporocilo.get("payload"), dict) else {}
        if vrsta == "share.screen":
            dejanje = str(telo.get("action") or "")
            url = ""
            if dejanje == "start":
                pot = str(telo.get("path") or "")
                if pot.startswith("/") and self.hub_url():
                    url = link_deljenje._osnova(self.hub_url()) + pot
            self._oddaj_dogodek("zaslon", {"od": od, "dejanje": dejanje, "url": url, "odtis": self.hub_fp()})
            return
        ime = str(telo.get("name") or "datoteka")
        pot = str(telo.get("path") or "")
        odtis_vsebine = str(telo.get("sha256") or "")
        if not pot or not self.hub_url():
            return
        posiljatelj = str(sporocilo.get("sender") or "")

        def _prenesi() -> None:
            # Pot v sporocilu je relativna na sredisce, ki je datoteko sprejelo: nase (racunalnik jo odda nam) ali
            # posiljateljevo (oddal jo je svojemu, sporocilo je prislo cez sosede). Vprasamo po vrsti.
            sredisca = [(self.hub_url(), self.hub_fp())]
            sredisce, _koda = self._sredisce_naprave(posiljatelj)
            if sredisce is not None:
                sredisca.append(sredisce)
            cilj, razlog = link_deljenje.prevzemi_pri_srediscih(sredisca, pot, ime, odtis_vsebine)
            self._oddaj_dogodek("prejetaDatoteka", {
                "od": od, "ime": os.path.basename(cilj) if cilj else ime, "pot": cilj or "",
                "uspeh": bool(cilj), "napaka": "" if cilj else str(razlog or ""),
            })

        threading.Thread(target=_prenesi, name="SafeerFileReceive", daemon=True).start()

    def _obdelaj_nadzorni_ukaz(self, sporocilo: dict) -> None:
        """Obdela dohodni ukaz daljinca z druge naprave (TV, telefon) na ločenem navideznem zaslonu."""
        posiljatelj = str(sporocilo.get("sender") or sporocilo.get("source") or "")
        id_ukaza = str(sporocilo.get("id") or "")
        payload = sporocilo.get("payload") or {}
        akcija = str(payload.get("action") or "").strip().lower()
        params = payload.get("params") or {}
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except Exception:
                params = {}

        izid: Dict[str, Any] = {"ok": True, "message": "Ukaz izveden"}

        try:
            if not self._dejanje_dovoljeno(posiljatelj, akcija):
                izid = {
                    "ok": False,
                    "message": "Na tem računalniku najprej izberi pravice za to napravo.",
                    "code": "dovoljenje_potrebno",
                    "data": {"permission": self.dovoljenje_za(posiljatelj)},
                }
                ime_n = next((str(n.get("ime") or "") for n in self.naprave if n.get("id") == posiljatelj), "")
                self._oddaj_dogodek("dovoljenjeZahtevano", {"id": posiljatelj, "ime": ime_n or posiljatelj})

            elif akcija == "status":
                stanje_naprave = dict(self.navidezni_zaslon.stanje_naprave())
                if self.magnet_na_voljo():
                    stanje_naprave["actions"] = list(stanje_naprave.get("actions") or []) + DEJANJA_MAGNET
                if self.tok_torrenta_na_voljo():
                    stanje_naprave["actions"] = list(stanje_naprave.get("actions") or []) + DEJANJA_TOK_TORRENTA
                if self._sprotno().ffmpeg():
                    stanje_naprave["actions"] = list(stanje_naprave.get("actions") or []) + DEJANJA_PRETOK
                medij = self._medij("status", {})
                if medij is not None:
                    stanje_naprave["actions"] = list(stanje_naprave.get("actions") or []) + DEJANJA_MEDIJ + DEJANJA_PREDAJA
                    if getattr(self, "ob_seznamih", None) is not None:
                        stanje_naprave["actions"] = stanje_naprave["actions"] + DEJANJA_SEZNAMI
                    stanje_naprave["keys"] = list(dict.fromkeys(list(stanje_naprave.get("keys") or []) + ["next", "previous"]))
                    stanje_naprave["media"] = medij.get("data") or {}
                izid = {
                    "ok": True,
                    "message": "Stanje",
                    "data": stanje_naprave,
                }

            elif akcija in DEJANJA_MAGNET:
                izid = self.odpri_magnet(str(params.get("uri") or ""))

            elif akcija in DEJANJA_TOK_TORRENTA:
                # Branje metapodatkov torrenta traja tudi minuto: ne v niti povezave, sicer bi drugi ukazi cakali.
                def delo(p: dict = dict(params)) -> None:
                    try:
                        izid_toka = self._tok_torrenta(akcija, p, posiljatelj)
                    except Exception as e:  # noqa: BLE001
                        izid_toka = {"ok": False, "message": f"Napaka pri izvedbi ukaza: {e}", "code": "napaka_izvedbe"}
                    self._odgovori_na_ukaz(posiljatelj, id_ukaza, akcija, izid_toka)
                threading.Thread(target=delo, name="safeer-magnet-tok", daemon=True).start()
                return

            elif akcija in DEJANJA_MEDIJ:
                izid = self._medij(str(params.get("cmd") or params.get("key") or ""), dict(params)) or {
                    "ok": False, "message": "Medijski center ni na voljo", "code": "ni_medija"}

            elif akcija in ("key", "key_down", "key_up"):
                k = str(params.get("key") or "")
                medij = self._medij(k, {}) if (akcija == "key" and k.strip().lower() in TIPKE_MEDIJ) else None
                if medij is not None and medij.get("ok"):
                    izid = medij
                else:
                    self.navidezni_zaslon.obdelaj_tipko(k)
                    izid = {"ok": True, "message": f"Tipka {k}"}

            elif akcija == "scroll":
                smer = str(params.get("direction") or "down")
                self.navidezni_zaslon.obdelaj_pomik(smer)
                izid = {"ok": True, "message": f"Drsenje {smer}"}

            elif akcija == "volume":
                podatki = self.navidezni_zaslon.nastavi_glasnost(
                    smer=str(params.get("direction") or ""),
                    raven=params.get("level"),
                )
                izid = {"ok": True, "message": f"Glasnost {podatki['level']} %", "data": podatki}

            elif akcija in ("screenshot", "screen.capture"):
                posnetek = self.navidezni_zaslon.zajemi_posnetek()
                izid = {"ok": True, "message": "Posnetek navideznega zaslona", "data": posnetek}

            elif akcija == "open_url":
                url = str(params.get("url") or "").strip()
                if not (url.startswith("http://") or url.startswith("https://") or url.startswith("safeer://")):
                    izid = {"ok": False, "message": "Dovoljeni so samo naslovi http(s) ali safeer://"}
                else:
                    self.navidezni_zaslon.odpri_url(url)
                    izid = {"ok": True, "message": "Stran se odpira na ločenem navideznem zaslonu"}

            elif akcija in ("apps", "apps.list"):
                ikone = params.get("icons") is not False
                od = int(params.get("offset") or 0)
                meja = int(params.get("limit") or 50)
                podatki = dict(self.navidezni_zaslon.seznam_programov_za_daljinec(z_ikonami=ikone, od=od, meja=meja))
                # V Link gre seznam samo enkrat ("items"): "apps" je isti seznam z istimi ikonami in je
                # odgovor podvojil cez mejo sporocila v hubu (325 kB) - Linux ni dobil nobenega programa.
                podatki.pop("apps", None)
                izid = {"ok": True, "message": f"{len(podatki['items'])} programov", "data": podatki}

            elif akcija in ("apps.launch", "launch_app"):
                app_id = str(params.get("app") or params.get("package") or "").strip()
                stream = bool(params.get("stream"))
                if app_id:
                    self.navidezni_zaslon.zazeni_program(app_id)
                    # Program zares zazenemo na tem racunalniku; televizor ga vidi prek pravega zaslona
                    # (screen.start). Prej je bil to samo zapis v navideznem kontekstu - nic se ni odprlo.
                    program = next((p for p in self.navidezni_zaslon._vsi_programi()
                                    if p.get("id") == app_id or str(p.get("ime") or "").lower() == app_id.lower()), None)
                    pot = str((program or {}).get("pot") or "")
                    zagnan = bool(pot) and os_backend_win.zazeni_program(pot)
                    odgovor_data = {"stream": "pending"} if stream else None
                    if zagnan:
                        izid = {"ok": True, "message": f"{program.get('ime') or app_id} se odpira na računalniku",
                                "data": odgovor_data}
                    else:
                        izid = {"ok": False, "message": "Programa ni bilo mogoče zagnati na tem računalniku.",
                                "code": "ni_zagnan"}
                else:
                    izid = {"ok": False, "message": "Manjka oznaka programa"}

            elif akcija == "apps.running":
                tecejo = self.navidezni_zaslon.tecejo_programi()
                izid = {"ok": True, "message": "Odprti programi", "data": {"running": tecejo}}

            elif akcija == "apps.close":
                app_id = str(params.get("app") or params.get("package") or "").strip()
                zaprti = self.navidezni_zaslon.zapri_program(app_id)
                izid = {"ok": True, "message": "Program se zapira", "data": {"closed": zaprti}}

            elif akcija == "screen.start":
                kakovost = str(params.get("quality") or "najvisja")
                seja = dict(self.navidezni_zaslon.zacni_sejo(posiljatelj, kakovost=kakovost))
                # Nasi naslovi: gledalec jih poskusi poleg naslova iz seznama naprav (docs/LINK-MESH.md, pravilo 8).
                seja["hosts"] = self._lastni_naslovi()
                izid = {"ok": True, "message": "Navidezni zaslon se deli", "data": seja}

            elif akcija == "screen.stop":
                self.navidezni_zaslon.ustavi_sejo()
                izid = {"ok": True, "message": "Deljenje navideznega zaslona je končano"}

            elif akcija == "screen.status":
                stanje_zaslona = self.navidezni_zaslon.stanje_seje()
                izid = {"ok": True, "message": "Stanje navideznega zaslona", "data": stanje_zaslona}

            elif akcija in ("mouse.move", "mouse.click", "touch"):
                x = params.get("x")
                y = params.get("y")
                vrsta_m = "klik" if akcija in ("mouse.click", "touch") else "premik"
                self.navidezni_zaslon.obdelaj_misko(
                    vrsta_m,
                    int(x if x is not None else self.navidezni_zaslon.kazalec_x),
                    int(y if y is not None else self.navidezni_zaslon.kazalec_y),
                )
                izid = {"ok": True, "message": "Vnos izveden na navideznem zaslonu"}

            elif akcija == "host.info":
                podatki = os_backend_win.zmogljivost()
                try:
                    k = self._sprotno().kodirniki()
                    if k:
                        podatki["gpu"] = dict(podatki.get("gpu") or {}, **k)
                except Exception:  # noqa: BLE001
                    pass
                izid = {"ok": True, "message": "Podatki o računalniku", "data": podatki}

            elif akcija in DEJANJA_PRETOK:
                izid = self._pretok(akcija, dict(params), posiljatelj)

            elif akcija in DEJANJA_PREDAJA:
                izid = self._predaja(akcija, posiljatelj, dict(params))

            elif akcija in DEJANJA_SEZNAMI:
                seznami = getattr(self, "ob_seznamih", None)
                if seznami is None:
                    izid = {"ok": False, "message": "Medijski center ni odprt.", "code": "ni_na_voljo"}
                else:
                    izid = {"ok": True, "message": "Seznami", "data": seznami(dict(params))}

            elif akcija == "files.list":
                mapa = str(params.get("folder") or "")
                try:
                    d = self._datoteke_za(posiljatelj)
                    podatki = d.seznam(mapa, posiljatelj, self.hub_url())
                    izid = {"ok": True, "message": f"{len(podatki.get('items', []))} vnosov", "data": podatki}
                except Exception as e:
                    izid = {"ok": False, "message": f"Napaka pri branju map: {e}", "data": {"items": []}}

            elif akcija == "files.open":
                dat_id = str(params.get("id") or "")
                try:
                    d = self._datoteke_za(posiljatelj)
                    if d.odpri(dat_id):
                        izid = {"ok": True, "message": "Datoteka se odpira na ločenem navideznem zaslonu"}
                    else:
                        izid = {"ok": False, "message": "Datoteke ni bilo mogoče odpreti"}
                except Exception as e:
                    izid = {"ok": False, "message": str(e)}

            elif akcija == "files.search":
                poizvedba = str(params.get("q") or "")
                try:
                    d = self._datoteke_za(posiljatelj)
                    podatki = d.isci(poizvedba, posiljatelj, self.hub_url())
                    izid = {"ok": True, "message": f"{len(podatki.get('items', []))} zadetkov", "data": podatki}
                except Exception as e:
                    izid = {"ok": False, "message": str(e)}

            else:
                izid = {"ok": False, "message": f"Neznano dejanje: {akcija}", "code": "neznano_dejanje"}

        except Exception as e:
            izid = {"ok": False, "message": f"Napaka pri izvedbi ukaza: {e}", "code": "napaka_izvedbe"}

        self._odgovori_na_ukaz(posiljatelj, id_ukaza, akcija, izid)

    def _odgovori_na_ukaz(self, posiljatelj: str, id_ukaza: str, akcija: str, izid: Dict[str, Any]) -> None:
        """Odgovor na ukaz daljinca nazaj pošiljatelju (tudi iz niti, ki dela dlje)."""
        povezava = self.povezava
        if posiljatelj and id_ukaza and povezava:
            povezava.poslji({
                "id": str(uuid.uuid4()),
                "type": "control.result",
                "target": posiljatelj,
                "ref_id": id_ukaza,
                "payload": {
                    "ok": bool(izid.get("ok", True)),
                    "action": akcija,
                    "message": str(izid.get("message") or ""),
                    "code": str(izid.get("code") or ""),
                    "data": izid.get("data"),
                }
            })

        self._oddaj_dogodek("nadzor_prejet", {
            "posiljatelj": posiljatelj,
            "akcija": akcija,
            "izid": izid,
        })

    # ------------------------------------------------------------------ Medijski center (daljinec)
    def _medij(self, ukaz: str, params: dict) -> Optional[Dict[str, Any]]:
        """Preda ukaz daljinca Medijskemu centru v istem procesu; None, ce ga ni ali ukaza ne pozna."""
        if self.ob_mediju is None:
            return None
        try:
            izid = self.ob_mediju(str(ukaz or "").strip().lower(), params or {})
        except Exception as e:  # noqa: BLE001
            print(f"[SafeerControl] medij {ukaz}: {e}")
            return None
        return izid if isinstance(izid, dict) else None

    # ------------------------------------------------------------------ Magnet povezave
    def tok_torrenta_na_voljo(self) -> bool:
        """Ali ta racunalnik zna torrent prenasati in pretakati napravam (rqbit obstaja za to platformo)."""
        try:
            from core import os_torrent
            return bool(os_torrent.platforma())
        except Exception:  # noqa: BLE001
            return False

    def _datoteke_torrenta(self):
        """Streznik za tokove torrenta (/m/): brez deljenih map, zeton naprave ni vezan na pravico do datotek."""
        from core import link_datoteke
        d = getattr(self, "_datoteke_tokov", None)
        if d is None:
            d = self._datoteke_tokov = link_datoteke.Datoteke(poti=[], tls_mapa=self.navidezni_zaslon.tls_mapa, ves_disk=False)
            # Knjiznica kroga: film, ki ga je Safeer OS na tem racunalniku zaradi gledanja prenesel sam, vidijo in
            # predvajajo tudi naprave (magnet.list); zasebnih naslovov med njimi ni. Motor je v istem procesu.
            from core import knjiznica_kroga
            d.gledanje = knjiznica_kroga.lokalni
            d.odstrani_gledanje = knjiznica_kroga.odstrani_lokalnega
            d.obdrzi_gledanje = knjiznica_kroga.nastavi_obdrzi
        return d

    def _tok_torrenta(self, akcija: str, params: dict, posiljatelj: str) -> Dict[str, Any]:
        """magnet.stream / magnet.list / magnet.remove: racunalnik prenasa torrent, naprava dobi samo tok.

        Isto vedenje kot Linux Control (core/link_daljinec.py): film, ki je na disku ze v celoti, gre takoj z
        diska; prenosi, ki jih 48 ur nihce ni predvajal, se odstranijo sami; ob pomanjkanju prostora, pomnilnika
        ali baterije racunalnik pove razlog in naprava vprasa naslednjega v Linku."""
        from core import os_torrent
        d = self._datoteke_torrenta()
        if akcija == "magnet.list":
            try:
                podatki = d.prenosi_za_naprave(id_naprave=posiljatelj)
                return {"ok": True, "message": f"{len(podatki['items'])} prenosov", "data": podatki}
            except Exception:  # noqa: BLE001
                return {"ok": True, "message": "Ni prenosov", "data": {"items": []}}
        if akcija == "magnet.remove":
            tid = params.get("id")
            if not isinstance(tid, int) or isinstance(tid, bool):
                return {"ok": False, "message": "Manjka prenos", "code": "ni_prenosa"}
            try:
                ok = d.odstrani_prenos(tid)
            except Exception:  # noqa: BLE001
                ok = False
            return ({"ok": True, "message": "Odstranjeno z računalnika"} if ok
                    else {"ok": False, "message": "Tega prenosa ni mogoče odstraniti", "code": "ni_prenosa"})
        if akcija == "magnet.keep":
            # »Obdrži«: prenos ne potece po 48 urah (odstrani ga samo uporabnik).
            tid, drzi = params.get("id"), params.get("keep")
            if not isinstance(tid, int) or isinstance(tid, bool) or not isinstance(drzi, bool):
                return {"ok": False, "message": "Manjka prenos", "code": "ni_prenosa"}
            try:
                ok = d.obdrzi_prenos(tid, drzi, id_naprave=posiljatelj)
            except Exception:  # noqa: BLE001
                ok = False
            return ({"ok": True, "message": "Prenos ostane na računalniku" if drzi else "Prenos ni več obdržan", "data": {"keep": drzi}}
                    if ok else {"ok": False, "message": "Tega prenosa ni mogoče obdržati", "code": "ni_prenosa"})
        uri = str(params.get("uri") or "")
        f = params.get("file")
        f = int(f) if isinstance(f, (int, float)) and not isinstance(f, bool) else None
        if os_torrent.razcleni_magnet(uri) is None:
            return {"ok": False, "message": "Torrenta ni mogoče pretakati", "code": "ni_magnet"}
        # Pretakanje torrenta je delo omrezja in diska: obremenjen procesor ni razlog za zavrnitev (kot na Linuxu).
        pomoc = (os_backend_win.zmogljivost().get("pomoc") or {})
        if pomoc.get("lahko") is False and str(pomoc.get("razlog") or "") != "preobremenjen":
            print(f"[SafeerTorrent] magnet.stream za {posiljatelj}: zavrnjeno ({pomoc.get('razlog')})", flush=True)
            return {"ok": False, "message": "Računalnik ta trenutek ne more pomagati", "code": str(pomoc.get("razlog") or "zaseden")}
        try:
            from core import link_datoteke
            podatki = d.tok_torrenta(uri, posiljatelj, self.hub_url(), f, opis_naprave=link_datoteke.opis_iz_parametrov(params))
            print(f"[SafeerTorrent] magnet.stream za {posiljatelj}: pretakam {podatki.get('name')}", flush=True)
            return {"ok": True, "message": "Računalnik pretaka: " + str(podatki.get("name") or ""), "data": podatki}
        except Exception as e:  # noqa: BLE001 - napravi povemo kratko kodo
            koda = str(e) if type(e).__name__ == "NapakaTorrenta" else "napaka"
            print(f"[SafeerTorrent] magnet.stream za {posiljatelj}: napaka {koda} ({e})", flush=True)
            return {"ok": False, "message": "Torrenta ni mogoče pretakati", "code": koda}

    def magnet_na_voljo(self) -> bool:
        """Ali ta racunalnik zna odpreti magnet povezavo z druge naprave (Safeer OS tece ali je namescen)."""
        if self.ob_magnetu is not None:
            return True
        try:
            from safeer_windows import magnet_win
            return bool(magnet_win.zaganjalnik())
        except Exception:  # noqa: BLE001
            return False

    def odpri_magnet(self, uri: str) -> Dict[str, Any]:
        """magnet.open z naprave v Linku: odpre jo Safeer OS; ukazov ali poti od naprave ne izvajamo."""
        from core import os_torrent
        m = os_torrent.razcleni_magnet(uri)
        if m is None:
            return {"ok": False, "message": "To ni veljavna magnet povezava", "code": "ni_magnet"}
        ime = m["ime"] or m["hash"][:12]
        if self.ob_magnetu is not None:
            self.ob_magnetu(m["uri"])
            return {"ok": True, "message": "Odpiram v Safeer OS: " + ime}
        from safeer_windows import magnet_win
        program = magnet_win.zaganjalnik()
        if not program:
            return {"ok": False, "message": "Safeer OS na tem računalniku ni nameščen", "code": "ni_safeer_os"}
        import subprocess
        dodatno: Dict[str, Any] = {}
        if sys.platform == "win32":
            dodatno["creationflags"] = 0x00000008  # DETACHED_PROCESS: brez okna ukazne vrstice
        else:
            dodatno["start_new_session"] = True
        subprocess.Popen(program + ["--magnet-naprava", m["uri"]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, **dodatno)
        return {"ok": True, "message": "Odpiram v Safeer OS: " + ime}

    def poslji_magnet(self, id_naprave: str, uri: str) -> Dict[str, Any]:
        """Magnet povezava na drugo napravo v Linku: tam se odpre v predvajalniku (magnet.open)."""
        from core import os_torrent
        m = os_torrent.razcleni_magnet(uri)
        if m is None:
            return {"ok": False, "koda": "ni_magnet"}
        return self.ukaz_pocakaj(str(id_naprave or ""), "magnet.open", {"uri": m["uri"]}, cas=15.0)

    def naprave_za_magnet(self) -> List[dict]:
        """Druge naprave v Linku, ki znajo odpreti magnet (zmoznost "magnet"): tja lahko posljemo povezavo."""
        izhod, videno = [], set()
        for n in self.naprave:
            id_n = str(n.get("id") or "")
            if not id_n or n.get("ta") or id_n == self.device_id or id_n in videno:
                continue
            if "magnet" not in (n.get("zmoznosti") or n.get("capabilities") or []):
                continue
            videno.add(id_n)
            izhod.append({"id": id_n, "ime": n.get("ime", ""), "platforma": n.get("platforma", "")})
        return izhod

    # ------------------------------------------------------------------ RPC ukazi napravam
    # ------------------------------------------------------------------ Safeer Chat
    def naprave_za_klepet(self) -> List[dict]:
        """Druge naprave v Linku, ki znajo klepet (ena vrstica na napravo)."""
        moja = next((n.get("naprava") for n in self.naprave if n.get("ta")), "") or ""
        izhod, videno = [], set()
        for n in self.naprave:
            naslov = n.get("naprava") or n.get("id", "")
            if n.get("ta") or (moja and naslov == moja) or "chat" not in (n.get("zmoznosti") or []) or naslov in videno:
                continue
            videno.add(naslov)
            izhod.append({"id": naslov, "ime": n.get("ime", ""), "platforma": n.get("platforma", "")})
        return izhod

    def poslji_klepet(self, id_naprave: str, besedilo: str, cas: str, cakaj: float = 10.0) -> str:
        """chat.send napravi v Linku; vrne "accepted", "queued" ali kodo napake."""
        if not self.je_povezan():
            return "ni_povezave"
        ref = "klepet-" + secrets.token_urlsafe(9)
        vnos = [threading.Event(), "potek"]
        self._klepet_cakajoci[ref] = vnos
        try:
            if not self.povezava.poslji({"id": ref, "type": "chat.send", "target": str(id_naprave),
                                         "payload": {"text": str(besedilo), "created_at": str(cas)}}):
                return "ni_povezave"
            vnos[0].wait(cakaj)
            return vnos[1]
        finally:
            self._klepet_cakajoci.pop(ref, None)

    def ukaz_pocakaj(self, id_naprave: str, dejanje: str, parametri: Optional[dict] = None, cas: float = 12.0) -> dict:
        if not self.je_povezan():
            return {"ok": False, "message": "Ni povezave s Safeer Linkom.", "koda": "ni_povezave"}

        ref = "cakaj-" + secrets.token_urlsafe(9)
        ev = threading.Event()
        odgovor = [None]
        self._cakajoci[ref] = (ev, odgovor)

        poslano = self.povezava.poslji({
            "id": ref,
            "type": "control.command",
            "target": id_naprave,
            "payload": {"action": dejanje, "params": parametri or {}},
        })
        if not poslano:
            self._cakajoci.pop(ref, None)
            return {"ok": False, "message": "Ukaza ni bilo mogoce poslati.", "koda": "ni_poslano"}

        ev.wait(cas)
        self._cakajoci.pop(ref, None)
        res = odgovor[0]
        if res is None:
            return {"ok": False, "message": "Naprava ni odgovorila.", "koda": "cas"}
        return res if isinstance(res, dict) else {"ok": True, "data": res}

    def vse_naprave(self) -> List[dict]:
        """Seznam naprav za Safeer OS stran Naprave."""
        rez = []
        for n in self.naprave:
            ime = n.get("ime") or n.get("name") or n.get("id", "")
            rez.append({
                "id": n.get("id", ""),
                "ime": ime,
                "platforma": n.get("platforma") or n.get("platform", ""),
                "vrsta": n.get("vrsta") or n.get("kind", ""),
                "naslov": n.get("naslov") or n.get("address") or n.get("host", ""),
                "ta": bool(n.get("ta") or n.get("id") == self.device_id),
                "zmoznosti": n.get("zmoznosti") or n.get("capabilities") or [],
            })
        return rez

    @staticmethod
    def _zmoznosti_naprave(naprava: dict) -> set[str]:
        """Poenoti oznake zmoznosti starejsih in novih odjemalcev.

        Nekateri odjemalci oglasujejo splosno zmoznost (``apps``/``files``),
        drugi pa posamezna dejanja (``apps.list``/``files.list``). Android
        zaslon poleg tega objavi katalog aplikacij, zato je tudi ta varen in
        nedvoumen dokaz, da zna odgovoriti na ``apps.list``.
        """
        surove = naprava.get("zmoznosti") or naprava.get("capabilities") or []
        if isinstance(surove, str):
            surove = [surove]
        z = {str(v).strip().lower() for v in surove if str(v).strip()}
        if any(v.startswith("apps.") for v in z):
            z.add("apps")
        if any(v.startswith("files.") for v in z) or "file" in z:
            z.add("files")
        if any(v.startswith("screen.") for v in z):
            z.add("screen")
        katalog = naprava.get("aplikacije") or naprava.get("apps")
        if isinstance(katalog, dict) and katalog:
            z.add("apps")
        return z

    @staticmethod
    def _seznam_iz_odgovora(podatki: dict, *imena: str) -> list:
        for ime in imena:
            vrednost = podatki.get(ime)
            if isinstance(vrednost, list):
                return vrednost
        return []

    def naprave_s_programi(self) -> List[dict]:
        """Naprave, ki znajo zagnati programe ali sprejemati daljinec (brez tega racunalnika)."""
        rez = []
        for n in self.naprave:
            if n.get("ta") or n.get("id") == self.device_id:
                continue
            z = self._zmoznosti_naprave(n)
            if "apps" in z or "remote" in z:
                ime = n.get("ime") or n.get("name") or n.get("id", "")
                rez.append({
                    "id": n.get("id", ""),
                    "ime": ime,
                    "platforma": n.get("platforma") or n.get("platform", ""),
                    "vrsta": n.get("vrsta") or n.get("kind", ""),
                })
        return rez

    def programi_naprave(self, id_naprave: str) -> dict:
        """Pridobi seznam namescenih programov oddaljene naprave (npr. TV ali telefon)."""
        if not id_naprave:
            return {"ok": False, "programi": []}

        naprava = next((n for n in self.naprave if str(n.get("id") or "") == str(id_naprave)), {})
        vsi = []
        od = 0
        for _ in range(10):
            r = self.ukaz_pocakaj(id_naprave, "apps.list", {"icons": True, "offset": od, "limit": 50}, cas=8.0)
            if not r.get("ok"):
                # Protocol v1 ze ob registraciji nosi majhen katalog brez ikon.
                # Ta rezervna pot prepreči prazen zaslon, kadar je Android ravno
                # v ozadju ali ko starejsi odjemalec se ne odgovarja na strani.
                katalog = naprava.get("aplikacije") or naprava.get("apps") or {}
                if isinstance(katalog, dict) and katalog:
                    vsi = [dict(v if isinstance(v, dict) else {}, id=k)
                           for k, v in katalog.items() if str(k)]
                    break
                return {"ok": False, "koda": r.get("koda") or r.get("code") or "napaka", "programi": []}
            podatki = r.get("data") if isinstance(r.get("data"), dict) else r
            kos = self._seznam_iz_odgovora(podatki, "items", "apps", "programi")
            vsi.extend(kos)
            skupaj = int(podatki.get("total") or len(vsi))
            od = int(podatki.get("offset") or 0) + len(kos)
            if not kos or od >= skupaj:
                break

        programi = []
        for item in vsi:
            if not isinstance(item, dict):
                continue
            app_id = item.get("id") or item.get("package") or item.get("paket")
            if not app_id:
                continue
            ikona = str(item.get("icon") or "")
            if not ikona and item.get("icon_png"):
                ikona = "data:image/png;base64," + str(item["icon_png"])
            programi.append({
                "id": str(app_id),
                "ime": str(item.get("name") or item.get("label") or item.get("ime") or app_id),
                "opis": str(item.get("comment") or item.get("description") or item.get("opis") or ""),
                "skupina": str(item.get("group") or item.get("kind") or item.get("skupina") or "drugo"),
                "ikona": ikona,
                "naprava": str(id_naprave),
            })

        return {"ok": True, "programi": programi,
                "deli": bool((podatki if 'podatki' in locals() else {}).get("enabled", True))}

    def naprave_s_datotekami(self) -> List[dict]:
        """Naprave, ki delijo datoteke ali podpirajo brskanje po datotekah (brez tega racunalnika)."""
        rez = []
        for n in self.naprave:
            if n.get("ta") or n.get("id") == self.device_id:
                continue
            z = self._zmoznosti_naprave(n)
            if "files" in z or not z:
                ime = n.get("ime") or n.get("name") or n.get("id", "")
                rez.append({
                    "id": n.get("id", ""),
                    "ime": ime,
                    "platforma": n.get("platforma") or n.get("platform", ""),
                    "vrsta": n.get("vrsta") or n.get("kind", ""),
                })
        return rez

    def datoteke_naprave(self, id_naprave: str, mapa: str = "") -> dict:
        """Pridobi seznam datotek ali map z oddaljene naprave prek files.list."""
        if not id_naprave:
            return {"ok": False, "items": [], "shared": False, "koda": "manjka_naprava"}
        r = self.ukaz_pocakaj(id_naprave, "files.list", {"folder": mapa}, cas=12.0)
        if not r.get("ok"):
            return {
                "ok": False,
                "koda": r.get("koda") or r.get("code") or "napaka",
                "sporocilo": r.get("message") or "Naprava ni odgovorila.",
                "items": [],
                "shared": False,
            }
        podatki = r.get("data") if isinstance(r.get("data"), dict) else r
        items = self._seznam_iz_odgovora(podatki, "items", "files", "datoteke", "elementi")
        return {
            "ok": True,
            "items": items,
            "folder": podatki.get("folder") or podatki.get("mapa") or podatki.get("path") or "",
            "shared": bool(podatki.get("shared", podatki.get("deli", True))),
            "edit": bool(podatki.get("edit", False)),
            "server": podatki.get("server"),
            "reason": podatki.get("reason") or podatki.get("razlog") or "",
        }

    def odpri_datoteko_naprave(self, id_naprave: str, id_datoteke: str) -> dict:
        """Zaprosi oddaljeno napravo, naj odpre datoteko s svojim programom."""
        if not id_naprave or not id_datoteke:
            return {"ok": False, "koda": "manjkajo_parametri"}
        r = self.ukaz_pocakaj(id_naprave, "files.open", {"id": id_datoteke}, cas=8.0)
        return {
            "ok": bool(r.get("ok")),
            "message": r.get("message") or "",
            "koda": r.get("koda") or r.get("code") or "",
        }

    def prenesi_datoteko_naprave(self, id_naprave: str, id_datoteke: str, ime_datoteke: str, streznik: Optional[dict] = None) -> dict:
        """Prenese datoteko z oddaljene naprave v mapo Prenosi in jo odpre."""
        if not id_datoteke:
            return {"ok": False, "koda": "manjka_datoteka"}
        if not streznik or not isinstance(streznik, dict) or not streznik.get("base_url"):
            return self.odpri_datoteko_naprave(id_naprave, id_datoteke)

        base_url = str(streznik.get("base_url") or "").rstrip("/")
        fp = streznik.get("fp")
        token = str(streznik.get("token") or "")
        u = urllib.parse.urlparse(base_url)
        gostitelj = u.hostname or "127.0.0.1"
        vrata = u.port or (443 if u.scheme == "https" else 80)

        mapa = os.path.join(os.path.expanduser("~"), "Downloads")
        os.makedirs(mapa, exist_ok=True)
        ime = link_deljenje.varno_ime(ime_datoteke or os.path.basename(id_datoteke) or "datoteka")
        cilj = link_deljenje.enolicna_pot(mapa, ime)

        pot_zahteve = f"/d/{urllib.parse.quote(id_datoteke)}"
        glave = {}
        if token:
            glave["X-Safeer-Token"] = token

        povezava = None
        try:
            if u.scheme == "https":
                povezava = link_tls._PripetaHttps(gostitelj, vrata, fp, timeout=30.0)
            else:
                povezava = http.client.HTTPConnection(gostitelj, vrata, timeout=30.0)
            povezava.request("GET", pot_zahteve, headers=glave)
            odgovor = povezava.getresponse()
            if odgovor.status != 200:
                return {"ok": False, "koda": f"http_{odgovor.status}", "sporocilo": f"Naprava je vrnila kodo {odgovor.status}"}

            with open(cilj, "wb") as f:
                while True:
                    kos = odgovor.read(65536)
                    if not kos:
                        break
                    f.write(kos)

            os_backend_win.odpri_datoteko(cilj)
            return {"ok": True, "pot": cilj}
        except Exception as e:
            if os.path.isfile(cilj):
                try:
                    os.remove(cilj)
                except OSError:
                    pass
            return {"ok": False, "koda": "napaka_prenosa", "sporocilo": str(e)}
        finally:
            if povezava:
                try:
                    povezava.close()
                except Exception:
                    pass

    def zazeni_na_napravi(self, id_naprave: str, app: str) -> dict:
        """Zagon programa na drugi napravi. Vrne ok + kodo in sporocilo naprave, da uporabnik
        izve, zakaj ni uspelo (npr. Android potrebuje dovoljenje za zagon iz ozadja)."""
        r = self.ukaz_pocakaj(id_naprave, "apps.launch", {"app": app}, cas=6.0)
        return {"ok": bool(r.get("ok")), "koda": str(r.get("koda") or r.get("code") or ""),
                "message": str(r.get("message") or "")}

    def odpri_tukaj(self, id_naprave: str, app: str) -> dict:
        r = self.ukaz_pocakaj(id_naprave, "apps.launch", {"app": app, "stream": True}, cas=8.0)
        podatki = r.get("data") if isinstance(r.get("data"), dict) else {}
        return {
            "ok": bool(r.get("ok")),
            "tu": podatki.get("stream") == "pending",
            "koda": str(r.get("koda") or ""),
            "message": str(r.get("message") or ""),
        }

    def preimenuj_napravo(self, id_naprave: str, novo_ime: str) -> dict:
        hub = self.hub_url()
        zeton = self._zeton_http()
        odtis = self.hub_fp()
        if not (hub and zeton):
            return {"ok": False, "koda": "ni_povezave"}
        ok, ime_shranjeno, n = link_deljenje.preimenuj_napravo(hub, zeton, odtis or "", id_naprave, novo_ime)
        if ok:
            for d in self.naprave:
                if d.get("id") == id_naprave:
                    d["ime"] = ime_shranjeno
            self._oddaj_dogodek("naprave", self.naprave)
        return {"ok": bool(ok), "ime": ime_shranjeno, "message": n.get("sporocilo", "")}

    def ukaz(self, cilj: str, akcija: str, podatki: Any = None, ref: str = "") -> bool:
        """Poslje nadzorni ukaz (daljinec, tipke, zvok) napravi."""
        if not self.je_povezan():
            return False
        if isinstance(podatki, str):
            try:
                podatki = json.loads(podatki)
            except Exception:
                pass
        return self.povezava.poslji({
            "id": ref or f"ukaz-{int(time.time() * 1000)}",
            "type": "control.command",
            "target": cilj,
            "payload": {"action": akcija, "params": podatki if isinstance(podatki, dict) else {}},
        })

    def poslji_besedilo(self, cilj: str, vsebina: str) -> bool:
        if not self.je_povezan():
            return False
        return self.povezava.poslji({
            "id": f"text-{int(time.time() * 1000)}",
            "type": "share.text",
            "target": cilj,
            "payload": {"text": vsebina},
        })

    def poslji_url(self, cilj: str, url: str, naslov: str = "") -> bool:
        """Pošlje spletni naslov po istem protokolu kot Android Safeer Link."""
        url = str(url or "").strip()
        if not self.je_povezan() or not cilj or not url.startswith(("http://", "https://")):
            return False
        return bool(self.povezava.poslji_url(cilj, url, naslov or ""))

    def _sredisce_naprave(self, id_naprave: str) -> tuple:
        """Sredisce druge naprave, kadar to ni nase: ((naslov, odtis), "") | (None, "") | (None, koda)."""
        lokalni = getattr(self, "_lokalni_hub", None)
        hub = lokalni.hub if (lokalni is not None and lokalni.tece()) else None
        try:
            from core import link_mesh
            return link_mesh.sredisce_naprave(hub, getattr(self, "_mesh", None), id_naprave)
        except Exception as e:  # noqa: BLE001 - brez tega podatka ravnamo kot doslej (lastno sredisce)
            print(f"[ControlBackend] Sredisce naprave: {e}")
            return None, ""

    def poslji_datoteko_napravi(self, cilj: str, pot: str,
                                napredek: Optional[Callable[[int], None]] = None) -> Tuple[bool, Dict[str, str]]:
        """Datoteko odda srediscu za napravo (PUT /cast/file); sredisce pove cilju, ta jo prevzame in preveri.

        Link Mesh: naprava ima svoje sredisce in datoteko prevzame pri NJEM, zato jo oddamo tja (prijava s podpisom,
        kot sosednja povezava). Pri nasem srediscu ostane samo naprava, ki je prijavljena neposredno nanj. Enako kot
        Safeer Control na Linuxu. Vrne (uspeh, napaka); klic caka do konca oddaje - vedno iz delovne niti."""
        sredisce, koda = self._sredisce_naprave(cilj)
        if koda:
            return False, {"sporocilo": link_deljenje.SPOROCILA_SREDISCA.get(koda, koda), "koda": koda, "zasedenaOd": ""}
        if sredisce is not None:
            naslov, odtis = sredisce
            lokalni = getattr(self, "_lokalni_hub", None)
            nas_id = str(getattr(getattr(lokalni, "hub", None), "nas_id", "") or "") or self.device_id
            seja = link_hub.seja_s_podpisom(naslov, nas_id, odtis, self.device_ime)
            if not seja:
                koda = "sredisce_naprave_ni_dosegljivo"
                return False, {"sporocilo": link_deljenje.SPOROCILA_SREDISCA[koda], "koda": koda, "zasedenaOd": ""}
            return link_deljenje.poslji_datoteko(naslov, seja, odtis, nas_id, cilj, pot, napredek)
        zeton = self._zeton_http()
        if not zeton:
            return False, {"sporocilo": "Datoteke ni mogoče poslati brez varne povezave s Safeer Linkom.",
                           "koda": "hub_ni_znan", "zasedenaOd": ""}
        return link_deljenje.poslji_datoteko(self.hub_url(), zeton, self.hub_fp(), self.device_id, cilj, pot, napredek)

    def poslji_datoteko(self, cilj: str, pot: str) -> bool:
        """Datoteko pošlje asinhrono in vmesniku sproti javlja napredek."""
        if not cilj or not os.path.isfile(pot) or not (self.hub_url() and self.zeton() and self.hub_fp()):
            self._oddaj_dogodek("deljenje", {
                "tece": False, "cilj": cilj, "ime": os.path.basename(pot),
                "napaka": "Datoteke ni mogoče poslati brez varne povezave s Safeer Linkom.",
            })
            return False

        ime = os.path.basename(pot)

        def _delo() -> None:
            def _napredek(odstotek: int) -> None:
                self._oddaj_dogodek("deljenje", {
                    "tece": True, "cilj": cilj, "ime": ime, "odstotek": odstotek, "napaka": "",
                })

            _napredek(0)
            ok, napaka = self.poslji_datoteko_napravi(cilj, pot, _napredek)
            self._oddaj_dogodek("deljenje", {
                "tece": False, "cilj": cilj, "ime": ime, "odstotek": 100 if ok else 0,
                "uspeh": ok, "napaka": "" if ok else str(napaka.get("sporocilo") or "Pošiljanje ni uspelo."),
            })

        threading.Thread(target=_delo, name="SafeerFileShare", daemon=True).start()
        return True

    def zacni_deljenje_zaslona(self, cilj: str, ime: str = "") -> bool:
        if not cilj or not (self.hub_url() and self.zeton() and self.hub_fp()):
            self._oddaj_dogodek("deljenje", {
                "tece": False, "cilj": cilj, "ime": ime,
                "napaka": "Zaslon lahko deliš po varni povezavi s Safeer Linkom.",
            })
            return False
        self.koncaj_deljenje_zaslona()
        deljenje = _WindowsDeljenjeZaslona(
            self.hub_url(), self.zeton(), self.hub_fp(), self.device_id, cilj, ime or cilj,
            ob_spremembi=lambda stanje: self._oddaj_dogodek("deljenje", stanje),
            navidezni_zaslon=self.navidezni_zaslon,
        )
        self._deljenje_zaslona = deljenje
        deljenje.zacni()
        return True

    def koncaj_deljenje_zaslona(self) -> bool:
        if self._deljenje_zaslona is None:
            return False
        self._deljenje_zaslona.ustavi()
        self._deljenje_zaslona = None
        return True

    def stanje_deljenja(self) -> dict:
        if self._deljenje_zaslona is None:
            return {"tece": False, "cilj": "", "ime": "", "napaka": ""}
        return self._deljenje_zaslona.stanje()

    # ------------------------------------------------------------------ Deljene mape
    def deljene_mape(self) -> List[str]:
        return list(self.nastavitve.get("deljene_mape", []))

    def deljene_mape_za_vmesnik(self) -> List[dict]:
        return [{"pot": pot, "ime": os.path.basename(os.path.normpath(pot)) or pot}
                for pot in self.deljene_mape()]

    def dodaj_deljeno_mapo(self, pot: str) -> bool:
        mape = self.deljene_mape()
        cista = os.path.abspath(pot)
        if os.path.isdir(cista) and cista not in mape:
            mape.append(cista)
            self.nastavitve["deljene_mape"] = mape
            self.shrani_nastavitve()
            self._oddaj_dogodek("stanje", self.stanje_linka())
            return True
        return False

    def deli_standardne_mape(self) -> int:
        """Enkrat doda obstoječe uporabnikove mape; podvojene poti se preskočijo."""
        dodanih = 0
        for mapa in os_backend_win.medijske_mape():
            pot = str(mapa.get("pot") or "")
            if pot and self.dodaj_deljeno_mapo(pot):
                dodanih += 1
        self._oddaj_dogodek("deljeneMape", {
            "mape": self.deljene_mape_za_vmesnik(),
            "standardne": self._standardne_mape_deljene(),
            "dodanih": dodanih,
        })
        return dodanih

    def _standardne_mape_deljene(self) -> bool:
        standardne = {os.path.normcase(os.path.abspath(str(m.get("pot") or "")))
                      for m in os_backend_win.medijske_mape() if m.get("pot")}
        deljene = {os.path.normcase(os.path.abspath(p)) for p in self.deljene_mape()}
        return bool(standardne) and standardne.issubset(deljene)

    def shrani_vzdevek(self, id_naprave: str, ime: str) -> bool:
        id_naprave, ime = str(id_naprave or "").strip(), str(ime or "").strip()[:80]
        if not id_naprave:
            return False
        vzdevki = dict(self.nastavitve.get("link_vzdevki") or {})
        if ime:
            vzdevki[id_naprave] = ime
        else:
            vzdevki.pop(id_naprave, None)
        self.nastavitve["link_vzdevki"] = vzdevki
        ok = self.shrani_nastavitve()
        if ok:
            self._oddaj_dogodek("vzdevki", vzdevki)
        return ok

    def odstrani_deljeno_mapo(self, indeks: int) -> bool:
        mape = self.deljene_mape()
        if 0 <= indeks < len(mape):
            del mape[indeks]
            self.nastavitve["deljene_mape"] = mape
            self.shrani_nastavitve()
            self._oddaj_dogodek("stanje", self.stanje_linka())
            return True
        return False


def get_backend() -> SafeerControlBackend:
    return SafeerControlBackend.pridobi()
