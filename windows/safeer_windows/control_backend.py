"""Safeer Control Backend za Windows — upravljanje povezave, seznanitev in naprav Safeer Linka."""

from __future__ import annotations

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

from core import link_deljenje, link_hub, link_tls
from safeer_windows import os_backend_win
from safeer_windows.navidezni_zaslon import NavidezniZaslon

CONFIG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~/.config"), "SafeerControl")
CONFIG_FILE = os.path.join(CONFIG_DIR, "link.json")


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
        self._prijava: Optional[dict] = None
        self._qr: Optional[dict] = None
        self._qr_rod = 0
        self._cakajoci: Dict[str, list] = {}
        self._poslusavci: List[Callable[[str, Any], None]] = []
        self._povezovanje = False
        self._zadnji_hubi: List[dict] = []
        self._cas_hubi = 0.0

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

        hubi = []
        if stanje != "povezan":
            hubi = self.hubi_v_omrezju()

        return {
            "stanje": stanje,
            "control": True,
            "zaupana": zaupana,
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
            "deljeneMape": self.deljene_mape(),
            "standardneDeljene": False,
        }

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

    def hubi_v_omrezju(self, osvezi: bool = False) -> List[dict]:
        zdaj = time.time()
        if not osvezi and (zdaj - self._cas_hubi < 10) and self._zadnji_hubi:
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

        # Znani hišni naslovi (Philips TV, Linux PC, telefoni)
        for h_ip in ["192.168.0.77", "192.168.0.135", "192.168.0.143", "192.168.0.216", "192.168.0.10", "127.0.0.1", "safeer.local"]:
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

        # Najprej preizkusi TLS (wss), nato ne-TLS (ws)
        for ip in kandidat_ipji:
            if not ip:
                continue
            for shema in ("wss", "ws"):
                naslov = f"{shema}://{ip}:8990/cast/ws"
                if any(n["naslov"] == naslov for n in najdeni):
                    continue
                try:
                    osnova = link_hub._osnova(naslov)
                    odtis = self.hub_fp() if (self.hub_url() and ip in self.hub_url()) else None
                    if link_hub.je_hub(osnova, timeout=0.8, odtis=odtis):
                        ime_h = f"Safeer Hub ({ip})"
                        if ip == "192.168.0.77":
                            ime_h = "Philips Android TV"
                        elif ip == "192.168.0.135":
                            ime_h = "Linux Centralni Hub"
                        najdeni.append({
                            "ime": ime_h,
                            "naslov": naslov,
                            "tls": shema == "wss",
                            "fp": odtis or "",
                        })
                        break
                except Exception:
                    pass

        # Sortiraj: TLS hubi in znana hišna vozlišča imajo prednost
        najdeni.sort(key=lambda n: (
            not n.get("tls", False),
            0 if ("192.168.0.135" in n["naslov"] or "192.168.0.77" in n["naslov"]) else 1
        ))

        self._zadnji_hubi = najdeni
        self._cas_hubi = zdaj
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

    def povezi_naprave(self) -> None:
        self.nastavitve["brez_povezave"] = False
        self.shrani_nastavitve()
        self.zacni_qr()
        self._oddaj_dogodek("brezPovezave", False)
        self._oddaj_dogodek("stanje", self.stanje_linka())

    def pozabi_napravo(self) -> bool:
        hub = self.hub_url()
        zeton = self.zeton()
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

    def nadaljuj_brez_povezave(self) -> bool:
        self.nastavitve["brez_povezave"] = True
        self.shrani_nastavitve()
        self._oddaj_dogodek("brezPovezave", True)
        self._oddaj_dogodek("stanje", self.stanje_linka())
        return True

    # ------------------------------------------------------------------ Trajna WebSocket povezava
    def povezi_se(self) -> bool:
        if self._povezovanje or self.je_povezan():
            return True

        hub = self.hub_url()
        zeton = self.zeton()
        odtis = self.hub_fp()
        if not (hub and zeton):
            return False

        self._povezovanje = True
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
                dodatne_zmoznosti=["files", "remote", "desktop", "screen", "apps"],
                katalog=self.navidezni_zaslon.katalog_aplikacij,
                v_krog=bool(self.nastavitve.get("zaupana", True)),
            )
            p.ob_sporocilu = self._na_sporocilo
            p.ob_stanju = self._na_stanje_povezave
            p.povezi()
            self.povezava = p
            return True
        except Exception as e:
            print(f"[ControlBackend] Povezava s Hubom ni uspela: {e}")
            return False
        finally:
            self._povezovanje = False

    def _na_stanje_povezave(self, povezan: bool) -> None:
        self._oddaj_dogodek("povezava", povezan)
        self._oddaj_dogodek("stanje", self.stanje_linka())

    def _na_sporocilo(self, sporocilo: dict) -> None:
        if not isinstance(sporocilo, dict):
            return
        vrsta = sporocilo.get("type", "")

        if vrsta == "cast.devices":
            seznam = []
            for d in sporocilo.get("devices") or []:
                seznam.append({
                    "id": d.get("id", ""),
                    "ime": d.get("name", ""),
                    "vloga": d.get("role", "receiver"),
                    "zmoznosti": d.get("capabilities") or [],
                    "platforma": d.get("platform") or "",
                    "vrsta": d.get("kind") or "",
                    "naslov": d.get("ip") or d.get("naslov") or "",
                    "ip": d.get("ip") or d.get("naslov") or "",
                    "zasedenaOd": d.get("busy_by") or d.get("zasedenaOd") or "",
                    "zasedenaOdIme": d.get("busy_by_name") or d.get("zasedenaOdIme") or "",
                    "aplikacije": d.get("apps") if isinstance(d.get("apps"), dict) else {},
                    "ta": d.get("id") == self.device_id,
                })
            self.naprave = seznam
            self._oddaj_dogodek("naprave", self.naprave)
            self._oddaj_dogodek("stanje", self.stanje_linka())

        elif vrsta in ("control.result", "control.ack"):
            ref = str(sporocilo.get("ref_id", "") or sporocilo.get("id", "") or "")
            payload = sporocilo.get("payload")
            telo = dict(payload) if isinstance(payload, dict) else {}
            if ref in self._cakajoci:
                event, res_holder = self._cakajoci[ref]
                res_holder[0] = telo or sporocilo
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

        elif vrsta == "cast.status":
            self._oddaj_dogodek("predvajanje", sporocilo.get("payload"))

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
            if akcija == "status":
                izid = {
                    "ok": True,
                    "message": "Stanje",
                    "data": self.navidezni_zaslon.stanje_naprave(),
                }

            elif akcija in ("key", "key_down", "key_up"):
                k = str(params.get("key") or "")
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
                podatki = self.navidezni_zaslon.seznam_programov_za_daljinec(z_ikonami=ikone, od=od, meja=meja)
                izid = {"ok": True, "message": f"{len(podatki['items'])} programov", "data": podatki}

            elif akcija in ("apps.launch", "launch_app"):
                app_id = str(params.get("app") or params.get("package") or "").strip()
                stream = bool(params.get("stream"))
                if app_id:
                    self.navidezni_zaslon.zazeni_program(app_id)
                    odgovor_data = {"stream": "pending"} if stream else None
                    izid = {"ok": True, "message": "Program se odpira na ločenem navideznem zaslonu", "data": odgovor_data}
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
                seja = self.navidezni_zaslon.zacni_sejo(posiljatelj, kakovost=kakovost)
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
                izid = {"ok": True, "message": "Podatki o računalniku", "data": os_backend_win.stanje_sistema()}

            elif akcija == "files.list":
                mapa = str(params.get("folder") or "")
                try:
                    from core import link_datoteke
                    d = link_datoteke.Datoteke(poti=self.deljene_mape(), tls_mapa=self.navidezni_zaslon.tls_mapa)
                    podatki = d.seznam(mapa, posiljatelj, self.hub_url())
                    izid = {"ok": True, "message": f"{len(podatki.get('items', []))} vnosov", "data": podatki}
                except Exception as e:
                    izid = {"ok": False, "message": f"Napaka pri branju map: {e}", "data": {"items": []}}

            elif akcija == "files.open":
                dat_id = str(params.get("id") or "")
                try:
                    from core import link_datoteke
                    d = link_datoteke.Datoteke(poti=self.deljene_mape(), tls_mapa=self.navidezni_zaslon.tls_mapa)
                    if d.odpri(dat_id):
                        izid = {"ok": True, "message": "Datoteka se odpira na ločenem navideznem zaslonu"}
                    else:
                        izid = {"ok": False, "message": "Datoteke ni bilo mogoče odpreti"}
                except Exception as e:
                    izid = {"ok": False, "message": str(e)}

            elif akcija == "files.search":
                poizvedba = str(params.get("q") or "")
                try:
                    from core import link_datoteke
                    d = link_datoteke.Datoteke(poti=self.deljene_mape(), tls_mapa=self.navidezni_zaslon.tls_mapa)
                    podatki = d.isci(poizvedba, posiljatelj, self.hub_url())
                    izid = {"ok": True, "message": f"{len(podatki.get('items', []))} zadetkov", "data": podatki}
                except Exception as e:
                    izid = {"ok": False, "message": str(e)}

            else:
                izid = {"ok": False, "message": f"Neznano dejanje: {akcija}", "code": "neznano_dejanje"}

        except Exception as e:
            izid = {"ok": False, "message": f"Napaka pri izvedbi ukaza: {e}", "code": "napaka_izvedbe"}

        # Pošlji odgovor nazaj pošiljatelju
        if posiljatelj and id_ukaza and self.povezava:
            self.povezava.poslji({
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

    # ------------------------------------------------------------------ RPC ukazi napravam
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
                "ta": bool(n.get("ta") or n.get("id") == self.device_id),
                "zmoznosti": n.get("zmoznosti") or n.get("capabilities") or [],
            })
        return rez

    def naprave_s_programi(self) -> List[dict]:
        """Naprave, ki znajo zagnati programe ali sprejemati daljinec (brez tega racunalnika)."""
        rez = []
        for n in self.naprave:
            if n.get("ta") or n.get("id") == self.device_id:
                continue
            z = n.get("zmoznosti") or n.get("capabilities") or []
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

        vsi = []
        od = 0
        for _ in range(10):
            r = self.ukaz_pocakaj(id_naprave, "apps.list", {"icons": True, "offset": od, "limit": 50}, cas=8.0)
            if not r.get("ok"):
                return {"ok": False, "koda": r.get("koda", "napaka"), "programi": []}
            podatki = r.get("data") if isinstance(r.get("data"), dict) else r
            kos = podatki.get("items") or []
            vsi.extend(kos)
            skupaj = int(podatki.get("total") or len(vsi))
            od = int(podatki.get("offset") or 0) + len(kos)
            if not kos or od >= skupaj:
                break

        programi = []
        for item in vsi:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            ikona = str(item.get("icon") or "")
            if not ikona and item.get("icon_png"):
                ikona = "data:image/png;base64," + str(item["icon_png"])
            programi.append({
                "id": str(item["id"]),
                "ime": str(item.get("name") or item["id"]),
                "opis": str(item.get("comment") or ""),
                "skupina": str(item.get("group") or "drugo"),
                "ikona": ikona,
                "naprava": str(id_naprave),
            })

        return {"ok": True, "programi": programi, "deli": True}

    def naprave_s_datotekami(self) -> List[dict]:
        """Naprave, ki delijo datoteke ali podpirajo brskanje po datotekah (brez tega racunalnika)."""
        rez = []
        for n in self.naprave:
            if n.get("ta") or n.get("id") == self.device_id:
                continue
            z = n.get("zmoznosti") or n.get("capabilities") or []
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
        return {
            "ok": True,
            "items": podatki.get("items") or [],
            "folder": podatki.get("folder") or "",
            "shared": bool(podatki.get("shared", True)),
            "edit": bool(podatki.get("edit", False)),
            "server": podatki.get("server"),
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

    def zazeni_na_napravi(self, id_naprave: str, app: str) -> bool:
        r = self.ukaz_pocakaj(id_naprave, "apps.launch", {"app": app}, cas=6.0)
        return bool(r.get("ok"))

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
        zeton = self.zeton()
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

    # ------------------------------------------------------------------ Deljene mape
    def deljene_mape(self) -> List[str]:
        return list(self.nastavitve.get("deljene_mape", []))

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
