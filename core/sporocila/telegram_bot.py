"""Telegram Bot API (uradna, brezplacna pot) - »Lastni API«: uporabnik pri @BotFather ustvari bota in vpise
njegov zeton. Bot prejema sporocila, ki mu jih ljudje posljejo (zasebno ali v skupinah, kjer je clan), in nanje
odgovarja. To NI uporabnikov osebni Telegram racun (za tega bi bil potreben TDLib in api_id).

Bot API nima zgodovine: sporocila dobimo z getUpdates (odmik `offset` v stanju kanala) in jih hranimo lokalno.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional, Sequence
from urllib.request import Request, urlopen

from .adapter import Adapter, prenesi_url
from . import priponke as _priponke

#: Bot API: datoteka do 50 MB (sendDocument), fotografija do 10 MB (sendPhoto) - omejitvi Telegrama.
NAJVEC_DATOTEKA = 50 * 1024 * 1024
NAJVEC_FOTO = 10 * 1024 * 1024
from .model import Pogovor, Sporocilo
from . import skrivnosti

NAJVEC_NA_KLEPET = 200


class NapakaPrijave(RuntimeError):
    pass


class TelegramBotAdapter(Adapter):
    vrsta = "telegram_bot"
    zmore = {"poslji", "priloge"}
    #: Naslov Bot API (preizkusi ga preusmerijo na lokalni nadomestni streznik).
    API = "https://api.telegram.org"

    def __init__(self, kanal_id: str, zeton: str = "", vnos_zetona: Optional[Callable[[], str]] = None, timeout: float = 20):
        self.kanal_id = kanal_id
        self._zeton, self._vnos_zetona = zeton, vnos_zetona
        self.timeout = timeout
        self.bot = {}
        self._offset = 0
        self._klepeti: dict = {}   # chat_id -> {"ime", "oseba", "sporocila": [], "neprebrano"}
        self._imena: dict = {}
        #: Dolgi getUpdates (s): nastavi nit kanala (sprotno.py); 0 = takoj.
        self.dolgo_cakanje_s = 0.0

    @property
    def kljuc_skrivnosti(self): return "telegram_bot:" + self.kanal_id

    def shrani_zeton(self, zeton: str) -> bool:
        self._zeton = zeton
        return skrivnosti.shrani(self.kljuc_skrivnosti, zeton)

    def pozabi_zeton(self) -> None:
        skrivnosti.pozabi(self.kljuc_skrivnosti)

    def _skrivnost(self):
        return skrivnosti.zahtevaj(self.kljuc_skrivnosti, self._zeton, self._vnos_zetona)

    def _api(self, metoda: str, podatki: Optional[dict] = None, timeout: Optional[float] = None, dolga: bool = False) -> dict:
        telo = json.dumps(podatki or {}, ensure_ascii=False).encode("utf-8")
        url = self.API + "/bot" + self._skrivnost() + "/" + metoda
        glave = {"Content-Type": "application/json", "Accept": "application/json"}
        try:
            if dolga:
                # Dolgi getUpdates: povezavo drzimo sami, da jo izklop kanala prekine takoj (sprotno.prekini_zahtevo).
                from .sprotno import dolga_zahteva
                surovo = dolga_zahteva(self, url, "POST", telo, glave, timeout or self.timeout)
            else:
                with urlopen(Request(url, data=telo, method="POST", headers=glave), timeout=timeout or self.timeout) as odgovor:
                    surovo = odgovor.read()
        except Exception as e:  # noqa: BLE001
            if getattr(e, "code", 0) in (401, 404):
                raise NapakaPrijave("Žeton bota ni sprejet") from e
            raise
        odg = json.loads(surovo.decode("utf-8")) if surovo else {}
        if not odg.get("ok"):
            raise RuntimeError(str(odg.get("description") or "Telegram napaka"))
        return odg.get("result")

    def stanje(self) -> dict:
        return {"offset": self._offset, "bot": self.bot, "imena": self._imena,
                "klepeti": {cid: {"ime": k["ime"], "oseba": k["oseba"], "neprebrano": k["neprebrano"],
                                  "sporocila": [m.slovar() for m in k["sporocila"][-NAJVEC_NA_KLEPET:]]} for cid, k in self._klepeti.items()}}

    def obnovi(self, stanje: dict) -> None:
        self._offset = int(stanje.get("offset") or 0); self.bot = dict(stanje.get("bot") or {}); self._imena = dict(stanje.get("imena") or {})
        for cid, k in (stanje.get("klepeti") or {}).items():
            self._klepeti[cid] = {"ime": k.get("ime", ""), "oseba": k.get("oseba", cid), "neprebrano": int(k.get("neprebrano") or 0),
                                  "sporocila": [Sporocilo.iz_slovarja(m) for m in (k.get("sporocila") or [])]}

    def povezi(self) -> None:
        if getattr(self, "_preverjen", False):
            return      # dolga poizvedba: getMe samo enkrat na zagon (preklican zeton javi getUpdates z 401)
        self.bot = self._api("getMe") or {}
        if not self.bot.get("id"):
            raise NapakaPrijave("Žeton bota ni sprejet")
        self._preverjen = True

    def ime_osebe(self, oseba_id: str) -> str:
        return self._imena.get(oseba_id, "")

    @staticmethod
    def _ime_uporabnika(u: dict) -> str:
        return " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or (("@" + u["username"]) if u.get("username") else str(u.get("id", "")))

    def _prenesi(self) -> None:
        cakaj = int(max(0, self.dolgo_cakanje_s))
        posodobitve = self._api("getUpdates", {"offset": self._offset, "timeout": cakaj, "allowed_updates": ["message", "edited_message"]},
                                timeout=max(self.timeout, 30, cakaj + 15), dolga=cakaj > 0) or []
        for u in posodobitve:
            self._offset = max(self._offset, int(u.get("update_id") or 0) + 1)
            m = u.get("message") or u.get("edited_message")
            if not isinstance(m, dict):
                continue
            klepet = m.get("chat") or {}
            cid = str(klepet.get("id") or "")
            if not cid:
                continue
            k = self._klepeti.setdefault(cid, {"ime": "", "oseba": cid, "neprebrano": 0, "sporocila": []})
            od = m.get("from") or {}
            if klepet.get("type") == "private":
                k["oseba"] = "tg:" + str(od.get("id") or cid); k["ime"] = self._ime_uporabnika(od); self._imena[k["oseba"]] = k["ime"]
            else:
                k["oseba"] = "tg-skupina:" + cid; k["ime"] = str(klepet.get("title") or cid); self._imena[k["oseba"]] = k["ime"]
            besedilo = str(m.get("text") or m.get("caption") or "")
            priponke = []
            for vrsta in ("document", "photo", "video", "audio", "voice"):
                if m.get(vrsta):
                    priponke.append(self._priponka(vrsta, m[vrsta], str(m.get("message_id"))))
                    besedilo = besedilo or "📎 " + priponke[-1]["ime"]
            if klepet.get("type") != "private" and od:
                besedilo = self._ime_uporabnika(od) + ": " + besedilo
            mid = str(m.get("message_id"))
            if any(s.id == mid for s in k["sporocila"]):
                continue
            cas = datetime.fromtimestamp(int(m.get("date") or 0), timezone.utc).isoformat()
            lasten = self.bot and od.get("id") == self.bot.get("id")
            k["sporocila"].append(Sporocilo(mid, cid, "ven" if lasten else "noter", besedilo, cas, priponke, "poslano" if lasten else "prejeto"))
            k["sporocila"] = k["sporocila"][-NAJVEC_NA_KLEPET:]
            if not lasten:
                k["neprebrano"] += 1

    @staticmethod
    def _priponka(vrsta: str, podatki, mid: str) -> dict:
        """Opis priponke z file_id (za prenos z getFile). Fotografija pride v vec velikostih: vzamemo najvecjo."""
        if isinstance(podatki, list):
            podatki = podatki[-1] if podatki and isinstance(podatki[-1], dict) else {}
        if not isinstance(podatki, dict):
            podatki = {}
        privzeto = {"photo": ("foto_%s.jpg", "image/jpeg"), "voice": ("glas_%s.ogg", "audio/ogg"),
                    "video": ("video_%s.mp4", "video/mp4"), "audio": ("zvok_%s.mp3", "audio/mpeg")}.get(vrsta, ("datoteka_%s", ""))
        return {"ime": str(podatki.get("file_name") or privzeto[0] % mid), "tip": str(podatki.get("mime_type") or privzeto[1]),
                "velikost": int(podatki.get("file_size") or 0), "file_id": str(podatki.get("file_id") or "")}

    def prenesi_priponko(self, sporocilo_id: str, priponka: dict, pisi, napredek=None) -> int:
        """Bot API: getFile -> https://api.telegram.org/file/bot<zeton>/<pot> (najvec 20 MB, omejitev Telegrama)."""
        file_id = str(priponka.get("file_id") or "")
        if not file_id:
            raise ValueError("ni_podprto")
        datoteka = self._api("getFile", {"file_id": file_id}) or {}
        pot = str(datoteka.get("file_path") or "")
        if not pot or ".." in pot.split("/"):
            raise ValueError("ni_podprto")
        return prenesi_url("https://api.telegram.org/file/bot" + self._skrivnost() + "/" + pot, pisi, napredek,
                           timeout=max(self.timeout, 60))

    def pogovori(self, od: Optional[str] = None) -> Iterable[Pogovor]:
        self._prenesi()
        izid = []
        for cid, k in self._klepeti.items():
            zadnje = k["sporocila"][-1] if k["sporocila"] else None
            izid.append(Pogovor(cid, self.kanal_id, k["oseba"], "" if k["oseba"].startswith("tg:") else k["ime"],
                                zadnje.besedilo if zadnje else "", k["neprebrano"], zadnje.cas if zadnje else ""))
            k["neprebrano"] = 0
        return izid

    def sporocila(self, pogovor_id: str, pred: Optional[str] = None, najvec: int = 50) -> Iterable[Sporocilo]:
        return list(self._klepeti.get(pogovor_id, {}).get("sporocila", []))[-max(1, min(int(najvec), NAJVEC_NA_KLEPET)):]

    def _api_datoteka(self, metoda: str, polja: dict, ime_polja: str, d: dict) -> dict:
        """Klic Bot API z datoteko (multipart/form-data)."""
        with open(d["pot"], "rb") as f:
            vsebina = f.read(NAJVEC_DATOTEKA + 1)
        telo, vrsta = _priponke.vecdelni_obrazec(polja, ime_polja, d["ime"], d["tip"], vsebina)
        zahteva = Request("https://api.telegram.org/bot" + self._skrivnost() + "/" + metoda, data=telo, method="POST",
                          headers={"Content-Type": vrsta, "Accept": "application/json"})
        try:
            with urlopen(zahteva, timeout=max(self.timeout, 120)) as odgovor:
                surovo = odgovor.read()
        except Exception as e:  # noqa: BLE001
            if getattr(e, "code", 0) in (401, 404):
                raise NapakaPrijave("Žeton bota ni sprejet") from e
            if getattr(e, "code", 0) == 413:
                raise ValueError("priloga_prevelika_kanal") from e
            raise
        odg = json.loads(surovo.decode("utf-8")) if surovo else {}
        if not odg.get("ok"):
            raise RuntimeError(str(odg.get("description") or "Telegram napaka"))
        return odg.get("result") or {}

    def poslji(self, pogovor_id: str, besedilo: str, priponke: Sequence[dict] = ()) -> Sporocilo:
        """Besedilo in priloge: fotografija (JPEG/PNG/WebP do 10 MB) kot sendPhoto, vse drugo sendDocument; besedilo
        do 1024 znakov gre kot napis k prvi prilogi, daljse kot svoje sporocilo pred njimi."""
        datoteke = _priponke.datoteke_prilog(priponke, NAJVEC_DATOTEKA)
        chat_id = int(pogovor_id) if pogovor_id.lstrip("-").isdigit() else pogovor_id
        odg: dict = {}
        napis = besedilo if datoteke and len(besedilo) <= 1024 else ""
        if besedilo and not napis:
            odg = self._api("sendMessage", {"chat_id": chat_id, "text": besedilo}) or {}
        opis = []
        for i, d in enumerate(datoteke):
            foto = d["tip"] in ("image/jpeg", "image/png", "image/webp") and d["velikost"] <= NAJVEC_FOTO
            polja = {"chat_id": chat_id}
            if i == 0 and napis:
                polja["caption"] = napis
            odg = self._api_datoteka("sendPhoto" if foto else "sendDocument", polja, "photo" if foto else "document", d)
            vrnjeno = odg.get("photo") or odg.get("document") or {}
            if isinstance(vrnjeno, list):
                vrnjeno = vrnjeno[-1] if vrnjeno else {}
            opis.append({"ime": d["ime"], "tip": d["tip"], "velikost": d["velikost"], "lokalno": d["pot"],
                         "file_id": str((vrnjeno or {}).get("file_id") or "")})
        s = Sporocilo(str(odg.get("message_id") or ""), pogovor_id, "ven", besedilo,
                      datetime.fromtimestamp(int(odg.get("date") or 0), timezone.utc).isoformat() if odg.get("date") else datetime.now(timezone.utc).isoformat(), opis, "poslano")
        self._klepeti.setdefault(pogovor_id, {"ime": "", "oseba": pogovor_id, "neprebrano": 0, "sporocila": []})["sporocila"].append(s)
        return s

    def oznaci_prebrano(self, pogovor_id: str) -> None:
        pass   # Bot API nima potrdil o branju
