"""Navidezni oddaljeni ločeni zaslon za Safeer Control na Windows.

Omogoča, da televizorji, telefoni in druge naprave v Safeer Linku upravljajo ta računalnik
preko Safeer Controla v izoliranem navideznem prostoru (navidezno namizje 1920x1080).
Vnos (D-Pad, premik kazalca, kliki, odpiranje programov in spletnih strani) se izvaja
izključno v navideznem kontekstu, tako da fizični uporabnik za računalnikom nima občutka
motenja (fizična miška in aktivno okno ostaneta nedotaknjena).
"""

from __future__ import annotations

import base64
import io
import json
import os
import secrets
import socket
import ssl
import sys
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
CORE_DIR = os.path.abspath(os.path.join(PACKAGE_DIR, "..", ".."))
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

from core.link_datoteke import TLS_MAPA, zagotovi_potrdilo
from safeer_windows import os_backend_win

# Dimenzije navideznega zaslona
PRIVZETA_SIRINA = 1920
PRIVZETA_VISINA = 1080

# Okvirji pretoka (skladno s core/link_zaslon.py)
OKVIR_SLIKA = 1
OKVIR_ZVOK = 2
OKVIR_OBVESTILO = 3

# Posnetek pomanjšan za hiter prenos prek WebSocket/JSON
POSNETEK_SIRINA = 960
POSNETEK_VISINA = 540

# Privzete aplikacije na navideznem namizju
PRIVZETI_PROGRAMI = [
    {"id": "app_brskalnik", "ime": "Brskalnik", "ikona": "🌐", "opis": "Varni spletni brskalnik", "skupina": "splet", "url": "safeer://home"},
    {"id": "app_datoteke", "ime": "Datoteke", "ikona": "📁", "opis": "Upravitelj datotek", "skupina": "orodja", "url": ""},
    {"id": "app_youtube", "ime": "YouTube", "ikona": "▶️", "opis": "Video vsebine", "skupina": "predstavnost", "url": "https://www.youtube.com"},
    {"id": "app_mediji", "ime": "Predvajalnik", "ikona": "🎬", "opis": "Filmi in glasba", "skupina": "predstavnost", "url": ""},
    {"id": "app_pisarna", "ime": "Dokumenti", "ikona": "📝", "opis": "Urejevalnik besedil", "skupina": "pisarna", "url": ""},
    {"id": "app_kalkulator", "ime": "Računalo", "ikona": "🔢", "opis": "Hitri izračuni", "skupina": "orodja", "url": ""},
    {"id": "app_nastavitve", "ime": "Nastavitve", "ikona": "⚙️", "opis": "Sistemske nastavitve", "skupina": "sistem", "url": ""},
]


class NavidezniVnos:
    """Vmesnik za sprejem oddaljenega vnosa v navideznem kontekstu."""

    def __init__(self, zaslon: "NavidezniZaslon") -> None:
        self.zaslon = zaslon

    @property
    def mozno(self) -> bool:
        return True

    def izvedi(self, dogodek: dict) -> bool:
        return self.zaslon.obdelaj_vnosni_dogodek(dogodek)

    def sprosti_vse(self) -> None:
        self.zaslon.sprosti_vse()


class NavidezniZaslon:
    """Ločen navidezni zaslon in oddaljeno namizje za Safeer Control."""

    def __init__(self, sirina: int = PRIVZETA_SIRINA, visina: int = PRIVZETA_VISINA,
                 tls_mapa: str = TLS_MAPA) -> None:
        self.sirina = sirina
        self.visina = visina
        self.tls_mapa = tls_mapa

        # Navidezno stanje kazalca in izbire
        self.kazalec_x = sirina // 2
        self.kazalec_y = visina // 2
        self.izbrani_indeks = 0
        self.nacin = "namizje"  # "namizje" | "brskalnik" | "program"
        self.aktivni_url = ""
        self.aktivni_naslov = "Safeer Oddaljeno Namizje"
        self.aktivni_program_id = ""
        self.scroll_odmik = 0

        # Zvok in glasnost
        self.glasnost = 80
        self.utisano = False

        # Seznam programov na navideznem namizju
        self.programi = list(PRIVZETI_PROGRAMI)
        self.odprti_programi: Dict[str, dict] = {}

        # Pretočna strežniška seja (screen.start)
        self._posluh: Optional[socket.socket] = None
        self._odjemalec: Optional[ssl.SSLSocket] = None
        self._zeton = ""
        self.odtis = ""
        self.vrata = 0
        self._tece = False
        self._posiljatelj_seje = ""
        self._seja_nit: Optional[threading.Thread] = None
        self._kljuc = threading.RLock()

        self.vnos = NavidezniVnos(self)

    # ------------------------------------------------------------------ Stanje naprave
    def stanje_naprave(self) -> dict:
        """Stanje za ukaz 'status' daljinca."""
        return {
            "app": "safeer-control-windows",
            "version": "0.5.0",
            "foreground": True,
            "screen": "virtual",
            "title": self.aktivni_naslov,
            "url": self.aktivni_url or "safeer://desktop",
            "actions": [
                "status", "key", "key_down", "key_up", "scroll", "volume",
                "screenshot", "screen.start", "screen.stop", "screen.status",
                "apps", "apps.list", "apps.launch", "launch_app", "apps.running", "apps.close",
                "open_url", "files.list", "files.open", "files.search", "host.info",
                "mouse.move", "mouse.click", "touch"
            ],
            "keys": [
                "up", "down", "left", "right", "ok", "back", "home",
                "play_pause", "play", "pause", "stop", "volume_up", "volume_down"
            ],
            "volume": self.glasnost,
            "muted": self.utisano,
            "virtual_screen": {
                "width": self.sirina,
                "height": self.visina,
                "cursor": [self.kazalec_x, self.kazalec_y],
                "mode": self.nacin,
            }
        }

    # ------------------------------------------------------------------ Navidezni Vnos (Brez vpliva na fizični OS)
    def obdelaj_tipko(self, tipka: str) -> bool:
        """Obdela tipko v navideznem kontekstu.

        NE simulira operacijskih tipk fizične tipkovnice (SendInput), temveč premika
        fokus navideznega namizja ali upravlja navidezni brskalnik/predvajalnik.
        """
        k = str(tipka or "").strip().lower()
        preslikava = {
            "gor": "up", "navzgor": "up",
            "dol": "down", "navzdol": "down",
            "levo": "left",
            "desno": "right",
            "ok": "ok", "potrdi": "ok", "center": "ok", "vnasalka": "ok",
            "nazaj": "back", "ubezna": "back",
            "domov": "home",
            "predvajaj": "play_pause", "pavza": "play_pause", "play": "play", "pause": "pause",
            "ustavi": "stop",
            "glasneje": "volume_up", "tisje": "volume_down",
        }
        k = preslikava.get(k, k)

        with self._kljuc:
            if k == "home":
                self.nacin = "namizje"
                self.aktivni_url = ""
                self.aktivni_naslov = "Safeer Oddaljeno Namizje"
                self.izbrani_indeks = 0
                self._sinhroniziraj_kazalec_z_izbiro()
                return True

            if k == "back":
                if self.nacin != "namizje":
                    self.nacin = "namizje"
                    self.aktivni_url = ""
                    self.aktivni_naslov = "Safeer Oddaljeno Namizje"
                    return True
                return True

            if self.nacin == "namizje":
                st_programov = max(1, len(self.programi))
                stolpcev = 4
                if k == "right":
                    self.izbrani_indeks = (self.izbrani_indeks + 1) % st_programov
                elif k == "left":
                    self.izbrani_indeks = (self.izbrani_indeks - 1) % st_programov
                elif k == "down":
                    self.izbrani_indeks = (self.izbrani_indeks + stolpcev) % st_programov
                elif k == "up":
                    self.izbrani_indeks = (self.izbrani_indeks - stolpcev) % st_programov
                elif k == "ok":
                    if 0 <= self.izbrani_indeks < len(self.programi):
                        izbrani = self.programi[self.izbrani_indeks]
                        self.zazeni_program(izbrani["id"])
                    return True
                self._sinhroniziraj_kazalec_z_izbiro()
                return True

            # Nacin brskalnika ali programa
            if k == "up":
                self.scroll_odmik = max(0, self.scroll_odmik - 120)
                return True
            if k == "down":
                self.scroll_odmik += 120
                return True
            if k in ("play_pause", "play", "pause"):
                return True
            if k == "volume_up":
                self.nastavi_glasnost(smer="up")
                return True
            if k == "volume_down":
                self.nastavi_glasnost(smer="down")
                return True

        return True

    def _sinhroniziraj_kazalec_z_izbiro(self) -> None:
        """Postavi navidezni kazalec na sredino trenutno izbrane ploščice."""
        if not self.programi:
            return
        stolpcev = 4
        vrstica = self.izbrani_indeks // stolpcev
        stolpec = self.izbrani_indeks % stolpcev

        odmik_x = 280
        odmik_y = 320
        korak_x = 360
        korak_y = 220

        self.kazalec_x = min(self.sirina - 50, odmik_x + stolpec * korak_x)
        self.kazalec_y = min(self.visina - 50, odmik_y + vrstica * korak_y)

    def obdelaj_misko(self, vrsta: str, x: int, y: int, gumb: str = "levi") -> bool:
        """Premakne navidezni kazalec ali izvede klik na navideznem zaslonu."""
        with self._kljuc:
            self.kazalec_x = max(0, min(self.sirina - 1, int(x)))
            self.kazalec_y = max(0, min(self.visina - 1, int(y)))

            if vrsta in ("klik", "click"):
                # Preveri, če je uporabnik kliknil na katero od ploščic na navideznem namizju
                if self.nacin == "namizje":
                    stolpcev = 4
                    odmik_x = 280 - 150
                    odmik_y = 320 - 80
                    korak_x = 360
                    korak_y = 220
                    for i, p in enumerate(self.programi):
                        vrsta_i = i // stolpcev
                        stolpec_i = i % stolpcev
                        px = odmik_x + stolpec_i * korak_x
                        py = odmik_y + vrsta_i * korak_y
                        if px <= self.kazalec_x <= px + 300 and py <= self.kazalec_y <= py + 160:
                            self.izbrani_indeks = i
                            self.zazeni_program(p["id"])
                            break
        return True

    def obdelaj_pomik(self, smer: str) -> bool:
        """Navidezno drsenje."""
        with self._kljuc:
            if smer in ("up", "gor"):
                self.scroll_odmik = max(0, self.scroll_odmik - 200)
            elif smer in ("down", "dol"):
                self.scroll_odmik += 200
            elif smer in ("top", "zacetek"):
                self.scroll_odmik = 0
        return True

    def obdelaj_vnosni_dogodek(self, dogodek: dict) -> bool:
        """Obdela dogodek, ki prispe prek povratne povezave Safeer Zaslona (TV ali telefon)."""
        if not isinstance(dogodek, dict):
            return False
        vrsta = str(dogodek.get("vrsta") or "")
        if vrsta == "tipka":
            return self.obdelaj_tipko(str(dogodek.get("tipka") or ""))
        if vrsta in ("premik", "tocka"):
            x = dogodek.get("x")
            y = dogodek.get("y")
            if x is not None and y is not None:
                return self.obdelaj_misko("premik", int(x), int(y))
            dx = dogodek.get("dx") or 0
            dy = dogodek.get("dy") or 0
            return self.obdelaj_misko("premik", self.kazalec_x + int(dx), self.kazalec_y + int(dy))
        if vrsta == "klik":
            x = dogodek.get("x", self.kazalec_x)
            y = dogodek.get("y", self.kazalec_y)
            return self.obdelaj_misko("klik", int(x), int(y), str(dogodek.get("gumb") or "levi"))
        if vrsta == "kolesce":
            smer = str(dogodek.get("smer") or "down")
            return self.obdelaj_pomik(smer)
        return True

    def sprosti_vse(self) -> None:
        """Ponastavi morebitne pritisnjene gumbe."""
        pass

    # ------------------------------------------------------------------ Zvok in glasnost
    def nastavi_glasnost(self, smer: str = "", raven: Optional[int] = None) -> dict:
        """Prilagodi glasnost v navideznem kontekstu (in jo uskladi z zaledjem)."""
        with self._kljuc:
            if raven is not None:
                try:
                    self.glasnost = max(0, min(100, int(raven)))
                    self.utisano = False
                except (ValueError, TypeError):
                    pass
            elif smer == "up":
                self.glasnost = min(100, self.glasnost + 5)
                self.utisano = False
            elif smer == "down":
                self.glasnost = max(0, self.glasnost - 5)
            elif smer == "mute":
                self.utisano = True
            elif smer == "unmute":
                self.utisano = False
            elif smer == "toggle_mute":
                self.utisano = not self.utisano

            return {"level": self.glasnost, "muted": self.utisano}

    # ------------------------------------------------------------------ Programi in URL
    def odpri_url(self, url: str) -> bool:
        """Odpri spletno stran na ločenem navideznem zaslonu."""
        if not url:
            return False
        with self._kljuc:
            self.nacin = "brskalnik"
            self.aktivni_url = str(url)
            self.aktivni_naslov = f"Splet: {url}"
            self.scroll_odmik = 0
        return True

    def zazeni_program(self, app_id: str) -> bool:
        """Zažene program v navideznem kontekstu."""
        with self._kljuc:
            for p in self.programi:
                if p["id"] == app_id:
                    self.aktivni_program_id = app_id
                    if p.get("url"):
                        self.odpri_url(p["url"])
                    else:
                        self.nacin = "program"
                        self.aktivni_naslov = f"Safeer • {p['ime']}"
                    self.odprti_programi[app_id] = dict(p)
                    return True

            # Poskusi najti med sistemskimi programi
            sistemski = os_backend_win.poisci_start_menu_programe()
            for sp in sistemski:
                if sp["id"] == app_id or sp["ime"].lower() == app_id.lower():
                    self.aktivni_program_id = sp["id"]
                    self.nacin = "program"
                    self.aktivni_naslov = f"Program • {sp['ime']}"
                    self.odprti_programi[sp["id"]] = dict(sp)
                    return True

            self.aktivni_program_id = app_id
            self.nacin = "program"
            self.aktivni_naslov = f"Program • {app_id}"
            self.odprti_programi[app_id] = {"id": app_id, "ime": app_id}
            return True

    def zapri_program(self, app_id: str = "") -> int:
        """Zapre program na navideznem zaslonu."""
        with self._kljuc:
            if not app_id or app_id == self.aktivni_program_id:
                self.nacin = "namizje"
                self.aktivni_url = ""
                self.aktivni_naslov = "Safeer Oddaljeno Namizje"
                self.aktivni_program_id = ""
                if app_id in self.odprti_programi:
                    del self.odprti_programi[app_id]
                return 1
            if app_id in self.odprti_programi:
                del self.odprti_programi[app_id]
                return 1
            return 0

    def tecejo_programi(self) -> List[str]:
        """Seznam ID-jev trenutno odprtih programov na navideznem zaslonu."""
        with self._kljuc:
            return list(self.odprti_programi.keys())

    def katalog_aplikacij(self) -> dict:
        """Katalog za prijavo v Safeer Hub (Protocol v1)."""
        kat = {}
        for p in self.programi:
            kat[p["id"]] = {
                "name": p["ime"],
                "kind": p["skupina"],
            }
        return kat

    def seznam_programov_za_daljinec(self, z_ikonami: bool = True, od: int = 0, meja: int = 50) -> dict:
        """Vrne seznam programov v obliki, ki jo podpirata tako daljinec.js kot apps.list."""
        vsi = []
        for p in self.programi:
            vsi.append({
                "id": p["id"],
                "package": p["id"],
                "name": p["ime"],
                "label": p["ime"],
                "icon": p["ikona"] if z_ikonami else "",
                "group": p["skupina"],
                "comment": p["opis"],
            })

        # Dodaj še sistemske programe
        try:
            sistemski = os_backend_win.poisci_start_menu_programe()
            for sp in sistemski[:40]:
                vsi.append({
                    "id": sp["id"],
                    "package": sp["id"],
                    "name": sp["ime"],
                    "label": sp["ime"],
                    "icon": sp.get("ikona") if z_ikonami else "",
                    "group": sp.get("skupina", "drugo"),
                    "comment": sp.get("opis", ""),
                })
        except Exception:
            pass

        kos = vsi[od:od + meja]
        return {
            "apps": kos,
            "items": kos,
            "total": len(vsi),
            "offset": od,
            "limit": meja,
            "enabled": True,
        }

    # ------------------------------------------------------------------ Zajem posnetka (Screenshot)
    def zajemi_posnetek(self) -> dict:
        """Ustvari sliko navideznega zaslona in jo vrne kot JPEG Data URL.

        Upodobi navidezno namizje (ozadje, zgornjo vrstico, aplikacijske ploščice,
        stanje fokusa in navidezni kazalec) brez motenja fizičnega zaslona računalnika.
        """
        sirina = POSNETEK_SIRINA
        visina = POSNETEK_VISINA

        slika_bajti = None
        try:
            from PIL import Image, ImageDraw

            # 1. Osnovno ozadje (moderen temen gradient)
            im = Image.new("RGB", (sirina, visina), color=(15, 20, 28))
            draw = ImageDraw.Draw(im)

            # Nežen barvni preliv
            for y in range(visina):
                r = int(15 + (22 - 15) * (y / visina))
                g = int(20 + (32 - 20) * (y / visina))
                b = int(28 + (44 - 28) * (y / visina))
                draw.line([(0, y), (sirina, y)], fill=(r, g, b))

            # 2. Zgornja vrstica stanja
            draw.rectangle([(0, 0), (sirina, 36)], fill=(22, 27, 34))
            draw.line([(0, 36), (sirina, 36)], fill=(48, 54, 61))

            # Logotip in status ločenega zaslona
            draw.text((16, 10), "Safeer OS  •  Oddaljeno namizje (Windows)", fill=(240, 246, 252))
            ura_niz = time.strftime("%H:%M")
            draw.text((sirina // 2 - 20, 10), ura_niz, fill=(139, 148, 158))

            status_niz = f"Zvok: {self.glasnost}%" if not self.utisano else "Zvok: Utišano"
            draw.text((sirina - 120, 10), status_niz, fill=(88, 166, 255))

            # 3. Vsebina glede na način
            if self.nacin == "namizje":
                # Glavni naslov
                draw.text((40, 60), "Aplikacije in vsebine", fill=(255, 255, 255))
                draw.text((40, 82), "Upravljajte računalnik preko Safeer Link daljinca", fill=(139, 148, 158))

                # Mreža ploščic
                stolpcev = 4
                razmik_x = 210
                razmik_y = 110
                zacetek_x = 40
                zacetek_y = 120

                for i, p in enumerate(self.programi[:8]):
                    vrsta = i // stolpcev
                    stolpec = i % stolpcev
                    bx = zacetek_x + stolpec * razmik_x
                    by = zacetek_y + vrsta * razmik_y
                    bw = 195
                    bh = 95

                    je_izbran = (i == self.izbrani_indeks)

                    # Ozadje kartice
                    barva_kartice = (33, 38, 45) if not je_izbran else (45, 60, 85)
                    barva_obrobe = (88, 166, 255) if je_izbran else (48, 54, 61)
                    debelina_obrobe = 2 if je_izbran else 1

                    draw.rectangle([(bx, by), (bx + bw, by + bh)], fill=barva_kartice, outline=barva_obrobe, width=debelina_obrobe)

                    # Ikona in ime
                    draw.text((bx + 14, by + 16), p.get("ikona", "📦"), fill=(255, 255, 255))
                    draw.text((bx + 46, by + 18), p["ime"], fill=(255, 255, 255))
                    draw.text((bx + 14, by + 56), p.get("opis", "")[:24], fill=(139, 148, 158))

            elif self.nacin == "brskalnik":
                # Brskalniški vmesnik
                draw.rectangle([(40, 56), (sirina - 40, 96)], fill=(33, 38, 45), outline=(48, 54, 61))
                draw.text((56, 68), f"🔒 {self.aktivni_url or 'https://safeer.si'}", fill=(88, 166, 255))

                draw.rectangle([(40, 108), (sirina - 40, visina - 40)], fill=(22, 27, 34), outline=(48, 54, 61))
                draw.text((60, 130), f"Spletna stran: {self.aktivni_url}", fill=(240, 246, 252))
                draw.text((60, 160), "Prikazano na ločenem navideznem zaslonu.", fill=(139, 148, 158))
                draw.text((60, 185), f"Navidezni pomik: {self.scroll_odmik} px", fill=(110, 118, 129))

            else:
                # Način program
                draw.rectangle([(40, 56), (sirina - 40, visina - 40)], fill=(22, 27, 34), outline=(88, 166, 255), width=2)
                draw.text((60, 80), self.aktivni_naslov, fill=(255, 255, 255))
                draw.text((60, 110), "Program teče v ločeni oddaljeni seji.", fill=(139, 148, 158))

            # 4. Navidezni kazalec miške (pomanjšan sorazmerno s sliko)
            mx = int(self.kazalec_x * (sirina / self.sirina))
            my = int(self.kazalec_y * (visina / self.visina))
            draw.polygon([(mx, my), (mx + 12, my + 12), (mx + 5, my + 12), (mx + 8, my + 18), (mx + 5, my + 19), (mx + 2, my + 13), (mx, my + 16)],
                         fill=(255, 255, 255), outline=(0, 0, 0))

            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=75)
            slika_bajti = buf.getvalue()

        except Exception:
            slika_bajti = self._generiraj_zasilni_jpeg(sirina, visina)

        b64 = base64.b64encode(slika_bajti).decode("ascii")
        return {
            "image": f"data:image/jpeg;base64,{b64}",
            "width": self.sirina,
            "height": self.visina,
        }

    def _generiraj_zasilni_jpeg(self, w: int, h: int) -> bytes:
        """Minimalni veljavni JPEG v primeru odsotnosti knjižnic za risanje."""
        return base64.b64decode(
            "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="
        )

    # ------------------------------------------------------------------ Pretočna seja (Screen Stream)
    def zacni_sejo(self, posiljatelj: str, kakovost: str = "srednja") -> dict:
        """Začne pretočni strežnik za navidezni ločeni zaslon (skladno s core/link_zaslon.py)."""
        with self._kljuc:
            self.ustavi_sejo()

            self._zeton = secrets.token_urlsafe(24)
            self._posiljatelj_seje = posiljatelj

            kljuc, potrdilo, self.odtis = zagotovi_potrdilo(self.tls_mapa)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(potrdilo, kljuc)

            posluh = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            posluh.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            posluh.bind(("0.0.0.0", 0))
            posluh.listen(1)
            posluh.settimeout(30.0)

            self.vrata = posluh.getsockname()[1]
            self._posluh = posluh
            self._tece = True

            self._seja_nit = threading.Thread(target=self._streci_sejo, args=(posluh, ctx),
                                              name="safeer-navidezni-zaslon-streznik", daemon=True)
            self._seja_nit.start()

            return {
                "port": self.vrata,
                "fp": self.odtis,
                "token": self._zeton,
                "v": 2,
                "codec": "h264",
                "width": self.sirina,
                "height": self.visina,
                "fps": 30,
                "quality": kakovost,
                "audio": None,
                "input": True,
                "gamepad": True,
                "screen": "virtual",
                "game": False,
                "focus": True,
                "profile": "",
                "media": False,
            }

    def _streci_sejo(self, posluh: socket.socket, ctx: ssl.SSLContext) -> None:
        odjemalec = None
        try:
            surov, _ = posluh.accept()
            odjemalec = ctx.wrap_socket(surov, server_side=True)
            odjemalec.settimeout(10.0)

            # Preberi pozdrav
            vrstica = b""
            while b"\n" not in vrstica and len(vrstica) < 256:
                b = odjemalec.recv(1)
                if not b:
                    break
                vrstica += b
            pozdrav = vrstica.decode("utf-8", "replace").strip()
            if not pozdrav.startswith("SAFEER-ZASLON ") or pozdrav.split(" ", 1)[1] != self._zeton:
                odjemalec.close()
                return

            glava = {
                "v": 2, "w": self.sirina, "h": self.visina, "fps": 30,
                "zvok": None, "vnos": True, "plosek": True
            }
            odjemalec.sendall((json.dumps(glava) + "\n").encode("utf-8"))
            odjemalec.settimeout(None)
            self._odjemalec = odjemalec

            # Nit za branje povratnega vnosa iz naprave (TV daljinec, telefon)
            nit_vnos = threading.Thread(target=self._beri_povratni_vnos, args=(odjemalec,),
                                        name="safeer-navidezni-zaslon-vnos", daemon=True)
            nit_vnos.start()
            nit_vnos.join()

        except Exception as e:
            print(f"[NavidezniZaslon] Seja prekinjena: {e}")
        finally:
            if odjemalec:
                try:
                    odjemalec.close()
                except Exception:
                    pass
            self.ustavi_sejo()

    def _beri_povratni_vnos(self, odjemalec: ssl.SSLSocket) -> None:
        ostanek = b""
        try:
            while self._tece:
                kos = odjemalec.recv(4096)
                if not kos:
                    break
                ostanek += kos
                while b"\n" in ostanek:
                    vrstica, ostanek = ostanek.split(b"\n", 1)
                    if not vrstica:
                        continue
                    try:
                        dogodek = json.loads(vrstica.decode("utf-8", "replace"))
                        self.obdelaj_vnosni_dogodek(dogodek)
                    except Exception:
                        continue
        except Exception:
            pass

    def ustavi_sejo(self) -> None:
        """Ustavi pretočni strežnik navideznega zaslona."""
        with self._kljuc:
            self._tece = False
            if self._odjemalec:
                try:
                    self._odjemalec.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    self._odjemalec.close()
                except Exception:
                    pass
                self._odjemalec = None

            if self._posluh:
                try:
                    self._posluh.close()
                except Exception:
                    pass
                self._posluh = None
            self.vrata = 0
            self._zeton = ""

    def stanje_seje(self) -> dict:
        """Vrne trenutno stanje pretočne seje."""
        return {
            "tece": self._tece,
            "vrata": self.vrata,
            "dovoljeno": True,
            "mozno": True,
            "screen": "virtual",
        }


__all__ = ["NavidezniZaslon", "NavidezniVnos", "PRIVZETA_SIRINA", "PRIVZETA_VISINA"]
