"""Deljenje v Safeer Linku na Linuxu: besedilo, datoteka in zaslon - pošiljanje in sprejem.

Protokol je isti kot na telefonu (vsebina po HTTPS, nadzor pri Hubu):
 - besedilo:  POST /cast/share/text {device_id, target, text}
 - datoteka:  PUT  /cast/file?name&target&from  (telo = datoteka, glava x-safeer-sha256);
              Hub vrne svoj odtis in cilju pošlje share.file {name, path, sha256}
 - zaslon:    POST /cast/share/screen/start {device_id, target} -> {id, push_path};
              okvirje (4 bajti dolžine, big-endian + JPEG) potiskamo po eni TLS vtičnici;
              POST /cast/share/screen/stop {id}
 - sprejem datoteke: GET <hub>/<path>, preverjen SHA-256, v mapo prenosov.

Vse gre samo po TLS s pripetim odtisom Huba (link_tls). Zajem zaslona: GdkPixbuf iz
korenskega okna (X11); na Waylandu zajem ni na voljo in to povemo naravnost.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import select
import socket
import ssl
import threading
import time
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import quote, urlparse

from core import link_tls

KAKOVOST_JPEG = 60
NAJVEC_PX = 1280
RAZMIK_S = 0.25          # ~4 okvirji/s: dovolj za pogled, prijazno do procesorja
UTRIP_S = 4.0            # zadnji okvir ponovimo, da Hub ve, da še živimo
KOS = 64 * 1024


def _osnova(ws_naslov: str) -> str:
    u = urlparse(ws_naslov)
    return f"https://{u.netloc}"


#: Razlogi, zakaj datoteke ni mogoce oddati sredisci druge naprave (core/link_mesh.sredisce_naprave).
SPOROCILA_SREDISCA = {
    "naprava_pri_drugem_srediscu": "Naprava je povezana prek drugega središča; datoteke ji od tu ni mogoče poslati.",
    "sredisce_naprave_ni_dosegljivo": "Naprava v tem omrežju ni dosegljiva.",
}
#: Isto za deljenje zaslona (sredisce_za_zaslon); stran prevede po kodi, to besedilo je za dnevnik in ukazno vrstico.
SPOROCILA_ZASLONA = {
    "naprava_pri_drugem_srediscu": "Naprava je povezana prek drugega središča; zaslona ji od tu ni mogoče pokazati.",
    "sredisce_naprave_ni_dosegljivo": "Naprava v tem omrežju ni dosegljiva.",
    "zaslon_ni_na_voljo": "Ta naprava zaslona še ne zna prikazati. Posodobi Safeer na njej.",
    "hub_ni_znan": "Zaslon lahko deliš po varni povezavi s Safeer Linkom.",
    "konec_pri_napravi": "Naprava zaslona ne prikazuje več, zato se je deljenje končalo.",
}


def napaka_huba(koda: int, odgovor: dict) -> Dict[str, str]:
    """Stabilna koda napake in - pri zasedeni napravi - kdo z njo deli (kot na telefonu)."""
    oznaka = odgovor.get("koda") or odgovor.get("error_code") or ""
    if koda in (405, 501) or (koda == 404 and oznaka in ("", "ni_poti")):
        # Sredisce te poti nima: racunalnik s Safeerjem pred 2.1.45 (deljenje je znal samo Hub na Androidu).
        return {"sporocilo": "Središče tega še ne zna; posodobi Safeer na napravi, ki je središče.",
                "koda": "sredisce_ne_zna", "zasedenaOd": ""}
    return {
        "sporocilo": odgovor.get("napaka") or odgovor.get("error") or f"Hub je odgovoril {koda}",
        "koda": oznaka,
        "zasedenaOd": odgovor.get("busy_by_name") or odgovor.get("busy_by") or "",
    }


# ----------------------------------------------------------------------
# Besedilo
# ----------------------------------------------------------------------

def poslji_besedilo(ws_naslov: str, zeton: str, odtis: str, moj_id: str, cilj: str, besedilo: str) -> Tuple[bool, Dict[str, str]]:
    koda, odgovor, _ = link_tls.zahteva(_osnova(ws_naslov) + "/cast/share/text",
                                        {"device_id": moj_id, "target": cilj, "text": besedilo},
                                        zeton=zeton, timeout=8.0, pripeti=odtis)
    if koda == 200:
        return True, {}
    return False, napaka_huba(koda, odgovor)


def preimenuj_napravo(ws_naslov: str, zeton: str, odtis: str, id_naprave: str, ime: str) -> Tuple[bool, str, Dict[str, str]]:
    koda, odgovor, _ = link_tls.zahteva(_osnova(ws_naslov) + "/cast/devices/rename",
                                        {"device_id": id_naprave, "name": ime.strip()},
                                        zeton=zeton, timeout=8.0, pripeti=odtis)
    if koda == 200:
        return True, str(odgovor.get("name", "") or ""), {}
    return False, "", napaka_huba(koda, odgovor)


# ----------------------------------------------------------------------
# Datoteka - pošiljanje
# ----------------------------------------------------------------------

def _sha256_datoteke(pot: str) -> str:
    h = hashlib.sha256()
    with open(pot, "rb") as f:
        while True:
            kos = f.read(KOS)
            if not kos:
                break
            h.update(kos)
    return h.hexdigest()


def poslji_datoteko(ws_naslov: str, zeton: str, odtis: str, moj_id: str, cilj: str, pot: str,
                    napredek: Optional[Callable[[int], None]] = None) -> Tuple[bool, Dict[str, str]]:
    """Pošlje datoteko Hubu za cilj. Vrne (uspeh, napaka). Napredek dobi odstotek."""
    ime = os.path.basename(pot)
    velikost = os.path.getsize(pot)
    odtis_dat = _sha256_datoteke(pot)
    u = urlparse(ws_naslov)
    gostitelj, vrata = u.hostname or "127.0.0.1", u.port or 443
    cilj_pot = ("/cast/file?name=" + quote(ime, safe="") + "&target=" + quote(cilj, safe="")
                + "&from=" + quote(moj_id, safe=""))
    povezava = link_tls._PripetaHttps(gostitelj, vrata, odtis, 30.0)
    try:
        povezava.putrequest("PUT", cilj_pot)
        povezava.putheader("X-Safeer-Token", zeton)
        povezava.putheader("Content-Type", "application/octet-stream")
        povezava.putheader("Content-Length", str(velikost))
        povezava.putheader("x-safeer-sha256", odtis_dat)
        povezava.endheaders()
        poslano = 0
        zadnji = -1
        prekinjeno: Optional[Exception] = None
        with open(pot, "rb") as f:
            while True:
                kos = f.read(KOS)
                if not kos:
                    break
                try:
                    povezava.send(kos)
                except OSError as e:
                    # Sredisce je oddajo zavrnilo in zaprlo povezavo, se preden smo poslali vse (cilj ni povezan, ni
                    # prostora ...): razlog je morda ze v odgovoru - spodaj ga poskusimo prebrati.
                    prekinjeno = e
                    break
                poslano += len(kos)
                odst = int(poslano * 100 / velikost) if velikost else 100
                if napredek and odst != zadnji:
                    zadnji = odst
                    napredek(odst)
        try:
            odgovor = povezava.getresponse()
        except Exception:
            if prekinjeno is not None:
                raise prekinjeno
            raise
        telo = odgovor.read().decode("utf-8", "replace")
        try:
            j = json.loads(telo) if telo else {}
        except json.JSONDecodeError:
            j = {}
        if odgovor.status != 200:
            return False, napaka_huba(odgovor.status, j if isinstance(j, dict) else {})
        hubov = str(j.get("sha256", "") or "") if isinstance(j, dict) else ""
        if hubov and hubov != odtis_dat:
            return False, {"sporocilo": "Datoteka je po poti spremenjena (odtis se ne ujema).", "koda": "odtis_se_ne_ujema", "zasedenaOd": ""}
        return True, {}
    except link_tls.NeujemanjeOdtisa:
        return False, {"sporocilo": "Hub ima drugo potrdilo, kot je bilo ob seznanitvi.", "koda": "odtis_se_ne_ujema", "zasedenaOd": ""}
    except Exception as e:  # noqa: BLE001 - uporabnik dobi razlog, brskalnik teče naprej
        return False, {"sporocilo": f"Pošiljanje ni uspelo: {e}", "koda": "posiljanje_ni_uspelo", "zasedenaOd": ""}
    finally:
        try:
            povezava.close()
        except Exception:
            pass


# ----------------------------------------------------------------------
# Datoteka - sprejem
# ----------------------------------------------------------------------

def mapa_prenosov() -> str:
    for kandidat in ("~/Prenosi", "~/Downloads"):
        p = os.path.expanduser(kandidat)
        if os.path.isdir(p):
            return p
    p = os.path.expanduser("~/Prenosi")
    os.makedirs(p, exist_ok=True)
    return p


def varno_ime(ime: str) -> str:
    ime = os.path.basename(ime.replace("\\", "/")).strip() or "datoteka"
    return "".join(z if (z.isalnum() or z in " ._-()[]") else "_" for z in ime)[:180]


def enolicna_pot(mapa: str, ime: str) -> str:
    osnova, konc = os.path.splitext(ime)
    pot = os.path.join(mapa, ime)
    n = 1
    while os.path.exists(pot):
        pot = os.path.join(mapa, f"{osnova} ({n}){konc}")
        n += 1
    return pot


def prevzemi_datoteko(ws_naslov: str, odtis: str, pot_huba: str, ime: str, pricakovan_odtis: str,
                      mapa: Optional[str] = None) -> Tuple[Optional[str], str]:
    """Prenese datoteko s Huba v mapo prenosov. Vrne (pot, "") ali (None, razlog)."""
    cilj, razlog, _koda = _prevzemi(ws_naslov, odtis, pot_huba, ime, pricakovan_odtis, mapa)
    return cilj, razlog


def prevzemi_pri_srediscih(sredisca, pot_huba: str, ime: str, pricakovan_odtis: str,
                           mapa: Optional[str] = None) -> Tuple[Optional[str], str]:
    """Datoteko prevzame pri prvem sredisci s seznama [(naslov, odtis), ...], ki jo ima. Vrne kot prevzemi_datoteko.

    Pot v `share.file` je relativna na sredisce, ki je datoteko sprejelo - to pa je lahko nase (posiljatelj jo je
    oddal nam; tako delajo racunalniki) ali posiljateljevo (oddal jo je svojemu, sporocilo je prislo cez sosede).
    Iz sporocila se tega ne vidi, zato vprasamo po vrsti. Naslednje sredisce pride na vrsto samo, ce prejsnje
    odgovori, da te datoteke nima (404); vsaka druga napaka je koncna (ni prostora, napacen odtis, ni povezave)."""
    razlog = "Središče ni znano."
    for naslov, odtis in sredisca:
        if not naslov or not odtis:
            continue
        cilj, razlog, koda = _prevzemi(naslov, odtis, pot_huba, ime, pricakovan_odtis, mapa)
        if cilj or koda != 404:
            return cilj, razlog
    return None, razlog


def _prevzemi(ws_naslov: str, odtis: str, pot_huba: str, ime: str, pricakovan_odtis: str,
              mapa: Optional[str] = None) -> Tuple[Optional[str], str, int]:
    """(pot, "", 200) ali (None, razlog, koda HTTP sredisca); koda 0 = do odgovora ni prislo ali prenos ni uspel."""
    u = urlparse(ws_naslov)
    gostitelj, vrata = u.hostname or "127.0.0.1", u.port or 443
    cilj = enolicna_pot(mapa or mapa_prenosov(), varno_ime(ime))
    povezava = link_tls._PripetaHttps(gostitelj, vrata, odtis, 30.0)
    try:
        povezava.request("GET", pot_huba)
        odgovor = povezava.getresponse()
        if odgovor.status != 200:
            return None, f"Hub je odgovoril {odgovor.status}", int(odgovor.status)
        h = hashlib.sha256()
        with open(cilj, "wb") as f:
            while True:
                kos = odgovor.read(KOS)
                if not kos:
                    break
                f.write(kos)
                h.update(kos)
        pricakovan = pricakovan_odtis or (odgovor.getheader("x-safeer-sha256") or "")
        if pricakovan and h.hexdigest() != pricakovan:
            try:
                os.remove(cilj)
            except OSError:
                pass
            return None, "prstni odtis se ne ujema", 0
        return cilj, "", 200
    except Exception as e:  # noqa: BLE001
        try:
            os.remove(cilj)
        except OSError:
            pass
        return None, str(e), 0
    finally:
        try:
            povezava.close()
        except Exception:
            pass


# ----------------------------------------------------------------------
# Zaslon
# ----------------------------------------------------------------------

def gledalec_pri_srediscih(sredisca, pot: str, timeout: float = 4.0) -> Tuple[str, str]:
    """Kje je stran gledalca iz `share.screen`: (naslov strani, odtis sredisca) ali ("", ""), ce je nima nobeno.

    Pot v sporocilu je relativna na sredisce, ki je deljenje sprejelo - nase (posiljatelj ga je zacel pri nas; tako
    delajo racunalniki, docs/LINK-MESH.md pravilo 9) ali posiljateljevo (telefon ga zacne pri svojem, sporocilo je
    prislo cez sosede). Iz sporocila se tega ne vidi, zato vprasamo po vrsti `sredisca` = [(naslov, odtis), ...];
    zmaga prvo, ki stran ima (200). Izmerjeno 5. 10. 2026: racunalnik je iskal samo pri svojem in telefonov zaslon
    se je odprl kot {"error": "Ni te poti."}."""
    for naslov, odtis in sredisca:
        if not naslov or not odtis:
            continue
        u = urlparse(naslov)
        povezava = link_tls._PripetaHttps(u.hostname or "127.0.0.1", u.port or 443, odtis, timeout)
        odgovor = None
        try:
            povezava.request("GET", pot)
            odgovor = povezava.getresponse()
            koda = odgovor.status
        except Exception:  # noqa: BLE001 - nedosegljivo sredisce ali tuje potrdilo: vprasamo naslednje
            koda = 0
        finally:
            for odprto in (odgovor, povezava):
                try:
                    if odprto is not None:
                        odprto.close()
                except Exception:
                    pass
        if koda == 200:
            return _osnova(naslov) + pot, odtis
    return "", ""


def sredisce_za_zaslon(sredisce_naprave: Callable[[str], tuple], seja: Callable[[str, str], tuple],
                       lastno: Callable[[], tuple], cilj: str) -> tuple:
    """Pri katerem sredisci posiljatelj zacne deljenje zaslona za napravo `cilj`.

    Link Mesh: vsaka naprava ima svoje sredisce in zaslon ji pokaze ONO (gledalec bere okvirje pri njem), zato
    deljenje zacnemo tam - s sejo s podpisom, kot oddamo datoteko. Napravi brez svojega sredisca (prijavljena je
    pri tistem, na katerega smo prijavljeni mi) zaslon pokaze to sredisce.

    sredisce_naprave(cilj) -> ((naslov, odtis), "") | (None, "") | (None, koda)      (link_mesh.sredisce_naprave)
    seja(naslov, odtis)    -> (sejni zeton ali None, nas id pri tem sredisci)
    lastno()               -> ((naslov, zeton, odtis, nas id), "") za sredisce, na katero smo prijavljeni (nase ali
                              tuje); (None, "hub_ni_znan"), ce zanj nimamo zetona.
    Vrne ((naslov, zeton, odtis, nas id), opis) ali (None, {"sporocilo", "koda", "zasedenaOd"}). V opisu je
    `pri_napravi`: True, kadar je izbrano sredisce ciljne naprave same. Caka na omrezje."""
    def napaka(koda: str) -> tuple:
        return None, {"sporocilo": SPOROCILA_ZASLONA.get(koda, koda), "koda": koda, "zasedenaOd": ""}

    izbrano, koda = sredisce_naprave(cilj)
    if koda:
        return napaka(koda)
    if izbrano is not None:
        naslov, odtis = izbrano
        zeton, nas_id = seja(naslov, odtis)
        if not zeton:
            return napaka("sredisce_naprave_ni_dosegljivo")
        return (naslov, zeton, odtis, nas_id), {"pri_napravi": True}
    nase, koda = lastno()
    if nase is None:
        return napaka(koda or "zaslon_ni_na_voljo")
    return nase, {}


class DeljenjeZaslona:
    """Deli zaslon tega računalnika z eno napravo, dokler ga uporabnik ne prekine."""

    def __init__(self, ws_naslov: str, zeton: str, odtis: str, moj_id: str, cilj: str, ime_cilja: str,
                 ob_spremembi: Optional[Callable[[dict], None]] = None,
                 sredisce: Optional[Callable[[], tuple]] = None) -> None:
        #: Link Mesh: kje deljenje zacnemo, izvemo sele v delovni niti (prijava s podpisom caka na omrezje).
        #: Klic vrne ((naslov, zeton, odtis, moj id), {}) ali (None, napaka) - glej sredisce_za_zaslon.
        self._sredisce = sredisce
        self._pri_napravi = False
        self.ws_naslov = ws_naslov
        self.zeton = zeton
        self.odtis = odtis
        self.moj_id = moj_id
        self.cilj = cilj
        self.ime_cilja = ime_cilja
        self.ob_spremembi = ob_spremembi
        self.tece = False
        self.napaka = ""
        self.koda = ""
        self.zasedena_od = ""
        self._id = ""
        self._ustavi = threading.Event()
        self._nit: Optional[threading.Thread] = None

    def stanje(self) -> dict:
        return {"tece": self.tece, "cilj": self.cilj, "ime": self.ime_cilja, "napaka": self.napaka,
                "koda": self.koda, "zasedenaOd": self.zasedena_od}

    def _javi(self) -> None:
        if self.ob_spremembi:
            self.ob_spremembi(self.stanje())

    def zacni(self) -> None:
        self._ustavi.clear()
        self._nit = threading.Thread(target=self._tok, daemon=True)
        self._nit.start()

    def ustavi(self) -> None:
        self._ustavi.set()

    # --- odgovor sredisca ------------------------------------------------
    @staticmethod
    def _odgovor_sredisca(vticnik, cakaj_s: float = 0.0) -> Optional[dict]:
        """Odgovor sredisca na nas tok okvirjev, ce je ze prisel; None = sredisce se sprejema.

        Sredisce med deljenjem ne poslje nicesar. Ko deljenje konca samo (nihce vec ne gleda, ustavlja se),
        odgovori z razlogom in zapre povezavo - po tem locimo konec deljenja od padle povezave. Vrne telo odgovora;
        {} = povezava je zaprta brez berljivega razloga."""
        try:
            pripravljen = bool(vticnik.pending()) or bool(select.select([vticnik], [], [], cakaj_s)[0])
        except Exception:  # noqa: BLE001 - vticnik brez opisnika (preizkusi) ali ze zaprt
            return None
        if not pripravljen:
            return None
        surovo = b""
        try:
            # Prvo branje kratko: zapis TLS brez podatkov (vstopnica seje takoj po rokovanju) ne sme ustaviti okvirjev.
            vticnik.settimeout(0.05)
            for _ in range(8):
                kos = vticnik.recv(8192)
                if not kos:
                    break
                surovo += kos
                vticnik.settimeout(1.0)
                glava, locilo, telo = surovo.partition(b"\r\n\r\n")
                dolzina = re.search(rb"(?i)content-length:\s*(\d+)", glava) if locilo else None
                if locilo and (dolzina is None or len(telo) >= int(dolzina.group(1))):
                    break
        except (socket.timeout, ssl.SSLWantReadError):
            if not surovo:
                return None
        except OSError:
            pass
        finally:
            try:
                vticnik.settimeout(None)
            except Exception:
                pass
        try:
            j = json.loads(surovo.partition(b"\r\n\r\n")[2].decode("utf-8"))
        except Exception:
            j = {}
        return j if isinstance(j, dict) else {}

    def _konec_pri_srediscu(self, odgovor: dict) -> None:
        """Deljenje je koncalo sredisce. Ce zato, ker ga nihce vec ne gleda, to povemo; sicer je navaden konec."""
        if str(odgovor.get("razlog") or "") == "ni_gledalcev":
            self.koda = "konec_pri_napravi"
            self.napaka = SPOROCILA_ZASLONA["konec_pri_napravi"]

    # --- zajem -----------------------------------------------------------
    @staticmethod
    def zajem_na_voljo() -> Tuple[bool, str]:
        if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
            return False, "Zajem zaslona na Waylandu še ni na voljo."
        try:
            import gi
            gi.require_version("Gdk", "3.0")
            from gi.repository import Gdk
            okno = Gdk.get_default_root_window()
            if okno is None:
                return False, "Zaslona ni mogoče zajeti."
            return True, ""
        except Exception as e:  # noqa: BLE001
            return False, f"Zajem zaslona ni na voljo: {e}"

    @staticmethod
    def _okvir() -> Optional[bytes]:
        from gi.repository import Gdk, GdkPixbuf
        okno = Gdk.get_default_root_window()
        s, v = okno.get_width(), okno.get_height()
        pb = Gdk.pixbuf_get_from_window(okno, 0, 0, s, v)
        if pb is None:
            return None
        if max(s, v) > NAJVEC_PX:
            if s >= v:
                ns, nv = NAJVEC_PX, max(1, int(v * NAJVEC_PX / s))
            else:
                ns, nv = max(1, int(s * NAJVEC_PX / v)), NAJVEC_PX
            pb = pb.scale_simple(ns, nv, GdkPixbuf.InterpType.BILINEAR)
        ok, podatki = pb.save_to_bufferv("jpeg", ["quality"], [str(KAKOVOST_JPEG)])
        return bytes(podatki) if ok else None

    def _tok(self) -> None:
        vticnik = None
        try:
            if self._sredisce is not None:
                izbrano, n = self._sredisce()
                if izbrano is None:
                    self.napaka, self.koda = str(n.get("sporocilo") or ""), str(n.get("koda") or "")
                    self.zasedena_od = str(n.get("zasedenaOd") or "")
                    return          # stanje javi `finally`
                self.ws_naslov, self.zeton, self.odtis, self.moj_id = izbrano
                self._pri_napravi = bool(n.get("pri_napravi"))
            koda, odgovor, _ = link_tls.zahteva(_osnova(self.ws_naslov) + "/cast/share/screen/start",
                                                {"device_id": self.moj_id, "target": self.cilj},
                                                zeton=self.zeton, timeout=8.0, pripeti=self.odtis)
            if koda != 200:
                n = napaka_huba(koda, odgovor)
                if self._pri_napravi and n["koda"] == "sredisce_ne_zna":
                    # To sredisce JE ciljna naprava (Link Mesh). Ce poti nima, tujega zaslona ne zna prikazati -
                    # danes sredisce racunalnika. »Posodobi Safeer na napravi, ki je središče« bi zavedlo.
                    n = {"sporocilo": SPOROCILA_ZASLONA["zaslon_ni_na_voljo"], "koda": "zaslon_ni_na_voljo", "zasedenaOd": ""}
                self.napaka, self.koda, self.zasedena_od = n["sporocilo"], n["koda"], n["zasedenaOd"]
                self._javi()
                return
            self._id = str(odgovor.get("id", "") or "")
            pot = str(odgovor.get("push_path", "") or "")
            if not self._id or not pot:
                self.napaka = "Hub ni vrnil poti za deljenje."
                self._javi()
                return
            u = urlparse(self.ws_naslov)
            gostitelj, vrata = u.hostname or "127.0.0.1", u.port or 443
            surov = socket.create_connection((gostitelj, vrata), timeout=10.0)
            surov.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            vticnik, _ = link_tls.ovij(surov, gostitelj, self.odtis)
            vticnik.settimeout(None)
            vticnik.sendall((f"POST {pot} HTTP/1.1\r\nHost: {gostitelj}\r\n"
                             f"x-safeer-token: {self.zeton}\r\nContent-Type: application/octet-stream\r\n"
                             "Connection: close\r\n\r\n").encode("ascii"))
            self.tece = True
            self.napaka = self.koda = self.zasedena_od = ""
            self._javi()
            zadnji = b""
            zadnji_cas = 0.0
            while not self._ustavi.is_set():
                zacetek = time.time()
                okvir = None
                try:
                    okvir = self._okvir()
                except Exception:  # noqa: BLE001 - en neuspel zajem ne konca deljenja
                    okvir = None
                if okvir is not None and okvir != zadnji:
                    vticnik.sendall(len(okvir).to_bytes(4, "big") + okvir)
                    zadnji, zadnji_cas = okvir, time.time()
                elif zadnji and time.time() - zadnji_cas > UTRIP_S:
                    vticnik.sendall(len(zadnji).to_bytes(4, "big") + zadnji)
                    zadnji_cas = time.time()
                konec = self._odgovor_sredisca(vticnik)
                if konec is not None:
                    self._konec_pri_srediscu(konec)
                    break
                ostane = RAZMIK_S - (time.time() - zacetek)
                if ostane > 0:
                    self._ustavi.wait(ostane)
        except link_tls.NeujemanjeOdtisa:
            self.napaka, self.koda = "Hub ima drugo potrdilo, kot je bilo ob seznanitvi.", "odtis_se_ne_ujema"
        except Exception as e:  # noqa: BLE001
            if not self._ustavi.is_set():
                # Pisanje je padlo. Ce je sredisce pred tem odgovorilo, je deljenje koncalo ono - to ni napaka.
                konec = self._odgovor_sredisca(vticnik, 1.0) if vticnik is not None else None
                if konec:
                    self._konec_pri_srediscu(konec)
                else:
                    self.napaka = f"Deljenje zaslona je padlo: {e}"
        finally:
            self.tece = False
            if vticnik is not None:
                try:
                    vticnik.close()
                except Exception:
                    pass
            if self._id:
                # Hub ob zaprti vtičnici konča sam; izrecen stop pove cilju takoj.
                try:
                    link_tls.zahteva(_osnova(self.ws_naslov) + "/cast/share/screen/stop", {"id": self._id},
                                     zeton=self.zeton, timeout=5.0, pripeti=self.odtis)
                except Exception:
                    pass
                self._id = ""
            self._javi()
