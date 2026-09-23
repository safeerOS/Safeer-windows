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
import socket
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


def napaka_huba(koda: int, odgovor: dict) -> Dict[str, str]:
    """Stabilna koda napake in - pri zasedeni napravi - kdo z njo deli (kot na telefonu)."""
    return {
        "sporocilo": odgovor.get("napaka") or odgovor.get("error") or f"Hub je odgovoril {koda}",
        "koda": odgovor.get("koda") or odgovor.get("error_code") or "",
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
        with open(pot, "rb") as f:
            while True:
                kos = f.read(KOS)
                if not kos:
                    break
                povezava.send(kos)
                poslano += len(kos)
                odst = int(poslano * 100 / velikost) if velikost else 100
                if napredek and odst != zadnji:
                    zadnji = odst
                    napredek(odst)
        odgovor = povezava.getresponse()
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
    u = urlparse(ws_naslov)
    gostitelj, vrata = u.hostname or "127.0.0.1", u.port or 443
    cilj = enolicna_pot(mapa or mapa_prenosov(), varno_ime(ime))
    povezava = link_tls._PripetaHttps(gostitelj, vrata, odtis, 30.0)
    try:
        povezava.request("GET", pot_huba)
        odgovor = povezava.getresponse()
        if odgovor.status != 200:
            return None, f"Hub je odgovoril {odgovor.status}"
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
            return None, "prstni odtis se ne ujema"
        return cilj, ""
    except Exception as e:  # noqa: BLE001
        try:
            os.remove(cilj)
        except OSError:
            pass
        return None, str(e)
    finally:
        try:
            povezava.close()
        except Exception:
            pass


# ----------------------------------------------------------------------
# Zaslon
# ----------------------------------------------------------------------

class DeljenjeZaslona:
    """Deli zaslon tega računalnika z eno napravo, dokler ga uporabnik ne prekine."""

    def __init__(self, ws_naslov: str, zeton: str, odtis: str, moj_id: str, cilj: str, ime_cilja: str,
                 ob_spremembi: Optional[Callable[[dict], None]] = None) -> None:
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
            koda, odgovor, _ = link_tls.zahteva(_osnova(self.ws_naslov) + "/cast/share/screen/start",
                                                {"device_id": self.moj_id, "target": self.cilj},
                                                zeton=self.zeton, timeout=8.0, pripeti=self.odtis)
            if koda != 200:
                n = napaka_huba(koda, odgovor)
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
                ostane = RAZMIK_S - (time.time() - zacetek)
                if ostane > 0:
                    self._ustavi.wait(ostane)
        except link_tls.NeujemanjeOdtisa:
            self.napaka, self.koda = "Hub ima drugo potrdilo, kot je bilo ob seznanitvi.", "odtis_se_ne_ujema"
        except Exception as e:  # noqa: BLE001
            if not self._ustavi.is_set():
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
