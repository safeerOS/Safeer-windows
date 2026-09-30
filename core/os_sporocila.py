"""Most med razdelkom Sporocila v Safeer OS in jedrom zdruzenih sporocil (core/sporocila)."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Callable, List, Optional

from .sporocila import ponudniki as _ponudniki
from .sporocila.chatwoot import ChatwootAdapter
from .sporocila.email import EmailAdapter
from .sporocila.model import Kanal
from .sporocila.storitev import StoritevSporocil

# Znani ponudniki: IMAP/SMTP streznik in namig za prijavo (vecina zahteva "geslo za aplikacije").
PONUDNIKI = {
    "gmail.com": ("imap.gmail.com", "smtp.gmail.com", "aplikacije"),
    "googlemail.com": ("imap.gmail.com", "smtp.gmail.com", "aplikacije"),
    "yahoo.com": ("imap.mail.yahoo.com", "smtp.mail.yahoo.com", "aplikacije"),
    "icloud.com": ("imap.mail.me.com", "smtp.mail.me.com", "aplikacije"),
    "me.com": ("imap.mail.me.com", "smtp.mail.me.com", "aplikacije"),
    "gmx.net": ("imap.gmx.net", "mail.gmx.net", ""),
    "gmx.com": ("imap.gmx.com", "mail.gmx.com", ""),
    "siol.net": ("imap.siol.net", "mail.siol.net", ""),
    "t-2.net": ("imap.t-2.net", "smtp.t-2.net", ""),
    "outlook.com": ("outlook.office365.com", "smtp.office365.com", "oauth"),
    "hotmail.com": ("outlook.office365.com", "smtp.office365.com", "oauth"),
    "live.com": ("outlook.office365.com", "smtp.office365.com", "oauth"),
}
INTERVAL_S = 120
#: Safeer Chat: sporocila med napravami v Safeer Linku (en pogovor na napravo).
KANAL_LINKA = "safeer-link"
VRSTA_LINKA = "safeer"
NAJVEC_KLEPET = 16 * 1024
NAPAKE_KLEPETA = {
    "ni_povezave": "Safeer Link ni povezan.",
    "ni_controla": "Safeer Control ne teče.",
    "ni_naprave": "Te naprave ni več v Safeer Linku.",
    "meja": "Sporočilo je predolgo.",
    "potek": "Središče Safeer Linka ni odgovorilo.",
}


def _cas_zdaj() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _cas_klepeta(vrednost: str) -> str:
    """Cas posiljatelja v nasi obliki (UTC do sekunde); nerazumljiv cas -> cas prejema."""
    try:
        d = datetime.fromisoformat(str(vrednost).replace("Z", "+00:00"))
        if d.tzinfo is None:
            raise ValueError
        return d.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    except (TypeError, ValueError):
        return _cas_zdaj()


class SporocilaOS:
    def __init__(self, pot=None, zazeni: bool = True):
        self.storitev = StoritevSporocil(pot, interval=INTERVAL_S)
        #: Posiljanje po Linku (nastavi gostitelj): (naprava, besedilo, cas) -> "accepted"/"queued"/koda napake
        self.poslji_klepet: Optional[Callable[[str, str, str], str]] = None
        #: Naprave v Linku, ki znajo klepet (nastavi gostitelj): [{"id", "ime"}]
        self.naprave_klepeta: Optional[Callable[[], List[dict]]] = None
        self._nalozi()
        if zazeni and self.storitev.adapterji:
            self.storitev.zazeni()

    # ------------------------------------------------------------------ kanali
    def _adapter(self, kid: str, vrsta: str, n: dict, skrivnost: str = ""):
        if vrsta == "email":
            return EmailAdapter(kid, n.get("naslov", ""), n.get("imap", ""), n.get("smtp", ""),
                                int(n.get("imap_vrata") or 993), int(n.get("smtp_vrata") or 465),
                                n.get("uporabnik", ""), skrivnost)
        if vrsta == "chatwoot":
            return ChatwootAdapter(kid, n.get("url", ""), int(n.get("account_id") or 0), skrivnost)
        return None

    def _nalozi(self):
        for r in self.storitev.db.execute("SELECT * FROM kanali").fetchall():
            try:
                a = self._adapter(r["id"], r["vrsta"], json.loads(r["nastavitve"] or "{}"))
            except Exception:
                a = None
            if a is not None:
                self.storitev.adapterji[r["id"]] = a

    @staticmethod
    def privzeta_streznika(naslov: str) -> dict:
        p = _ponudniki.iz_naslova(naslov)
        if p:
            return {"imap": p["imap"], "smtp": p["smtp"], "imap_vrata": p["imap_vrata"], "smtp_vrata": p["smtp_vrata"],
                    "namig": "" if p["geslo"] == "navadno" else p["geslo"], "ponudnik": p["id"]}
        domena = naslov.rsplit("@", 1)[-1].lower().strip()
        imap, smtp, namig = PONUDNIKI.get(domena, ("imap." + domena, "smtp." + domena, ""))
        return {"imap": imap, "smtp": smtp, "imap_vrata": 993, "smtp_vrata": 465, "namig": namig, "ponudnik": "drug"}

    @staticmethod
    def ponudniki() -> dict:
        """Seznam ponudnikov in aplikacij za carovnik »Dodaj kanal«."""
        return _ponudniki.za_vmesnik()

    def dodaj_kanal(self, podatki: dict) -> dict:
        """Doda kanal SAMO, ce se prijava posreci - uporabnik takoj ve, ali je vse prav."""
        vrsta = str(podatki.get("vrsta", ""))
        kid = str(uuid.uuid4())
        if vrsta == "email":
            naslov = str(podatki.get("naslov", "")).strip()
            if "@" not in naslov or "." not in naslov.rsplit("@", 1)[-1]:
                raise ValueError("Vnesi veljaven e-poštni naslov.")
            p = self.privzeta_streznika(naslov)
            izbrani = _ponudniki.po_id(str(podatki.get("ponudnik") or ""))
            if izbrani and izbrani["id"] != "drug":
                p = {"imap": izbrani["imap"], "smtp": izbrani["smtp"], "imap_vrata": izbrani["imap_vrata"], "smtp_vrata": izbrani["smtp_vrata"],
                     "namig": "" if izbrani["geslo"] == "navadno" else izbrani["geslo"], "ponudnik": izbrani["id"]}
            if p["namig"] == "oauth":
                raise ValueError("Outlook in Hotmail ne dovolita več prijave z geslom (samo Microsoftova prijava). Ta vrsta prijave pride v naslednji različici.")
            geslo = str(podatki.get("geslo") or "")
            if not geslo:
                raise ValueError("Vnesi geslo.")
            nastavitve = {"naslov": naslov, "uporabnik": str(podatki.get("uporabnik") or naslov),
                          "imap": str(podatki.get("imap") or p["imap"]), "smtp": str(podatki.get("smtp") or p["smtp"]),
                          "imap_vrata": int(podatki.get("imap_vrata") or p.get("imap_vrata") or 993),
                          "smtp_vrata": int(podatki.get("smtp_vrata") or p.get("smtp_vrata") or 465)}
            for kljuc in ("imap", "smtp"):   # "gostitelj:vrata" iz rocnega vnosa
                g, _, vr = nastavitve[kljuc].rpartition(":")
                if g and vr.isdigit():
                    nastavitve[kljuc], nastavitve[kljuc + "_vrata"] = g, int(vr)
            if p.get("ponudnik"):
                nastavitve["ponudnik"] = p["ponudnik"]
            a = self._adapter(kid, "email", nastavitve, geslo)
            try:
                a.povezi()
            except Exception as e:
                ime = type(e).__name__
                # Nekateri ponudniki hocejo uporabnisko ime brez domene: poskusimo se tako, preden obupamo.
                brez = naslov.rsplit("@", 1)[0]
                if ime == "NapakaPrijave" and nastavitve["uporabnik"] == naslov and brez:
                    nastavitve["uporabnik"] = brez
                    a = self._adapter(kid, "email", nastavitve, geslo)
                    try:
                        a.povezi(); ime = ""
                    except Exception as e2:
                        ime = type(e2).__name__; nastavitve["uporabnik"] = naslov
                if ime == "NapakaPrijave":
                    namig = " Pri tem ponudniku potrebuješ »geslo za aplikacije« (nastaviš ga v varnostnih nastavitvah računa)." if p["namig"] == "aplikacije" else ""
                    raise ValueError("Prijava ni uspela - preveri naslov in geslo." + namig)
                if ime:
                    raise ValueError("Strežnika %s ni mogoče doseči." % nastavitve["imap"])
            a.shrani_geslo(geslo)
            ime = naslov
        elif vrsta == "chatwoot":
            nastavitve = {"url": str(podatki.get("url", "")).strip().rstrip("/"), "account_id": int(podatki.get("account_id") or 0)}
            zeton = str(podatki.get("zeton") or "")
            if not nastavitve["url"].startswith("https://") or not nastavitve["account_id"] or not zeton:
                raise ValueError("Vnesi naslov https://, številko računa in žeton Chatwoot.")
            a = self._adapter(kid, "chatwoot", nastavitve, zeton)
            try:
                a.povezi()
            except Exception:
                raise ValueError("Chatwoot ni sprejel povezave - preveri naslov, račun in žeton.")
            a.shrani_zeton(zeton)
            ime = str(podatki.get("ime") or "Chatwoot")
        else:
            raise ValueError("Nepodprta vrsta kanala")
        self.storitev.registriraj(Kanal(kid, vrsta, ime, "povezan"), a, nastavitve)
        threading.Thread(target=self._prvic, args=(kid,), daemon=True).start()
        return {"id": kid, "vrsta": vrsta, "ime": ime, "stanje": "povezan"}

    def _prvic(self, kid: str) -> None:
        self.storitev.sinhroniziraj(kid)
        self.storitev.zazeni()

    def nastavi_skrivnost(self, kanal_id: str, skrivnost: str) -> dict:
        """Ponovni vnos gesla/zetona (npr. brez zbirke skrivnosti po ponovnem zagonu)."""
        a = self.storitev.adapterji.get(kanal_id)
        if a is None or not skrivnost:
            raise ValueError("Ni kanala")
        (a.shrani_geslo if hasattr(a, "shrani_geslo") else a.shrani_zeton)(str(skrivnost))
        self.storitev.sinhroniziraj(kanal_id)
        return self.seznam()

    def odstrani_kanal(self, kanal_id: str) -> dict:
        self.storitev.odstrani_kanal(str(kanal_id))
        return self.seznam()

    # ------------------------------------------------------------------ branje/pisanje
    def seznam(self, kanal: str = "") -> dict:
        skupine = self.storitev.zdruzeni_pogovori(kanal)
        kanali = {k.id: k.slovar() for k in self.storitev.kanali()}
        try:
            smeri = self.storitev.zadnje_smeri()
        except Exception:
            smeri = {}
        for s in skupine:
            for p in s["pogovori"]:
                p["kanal"] = kanali.get(p["kanal_id"], {})
                p["zadnji_ven"] = smeri.get((p["kanal_id"], p["id"])) == "ven"
        return {"kanali": list(kanali.values()), "skupine": skupine, "oznake": self.storitev.vse_oznake()}

    # ---- osebe in oznake (uporabnikovo urejanje) ----
    def preimenuj_osebo(self, oseba_id: str, ime: str) -> dict:
        if not self.storitev.graf.preimenuj(str(oseba_id), str(ime)):
            raise ValueError("Oseba ne obstaja.")
        return self.seznam()

    def zdruzi_osebi(self, cilj_id: str, drugi_id: str) -> dict:
        if cilj_id == drugi_id:
            raise ValueError("Izberi drugo osebo.")
        self.storitev.zdruzi_osebi(str(cilj_id), str(drugi_id))
        return self.seznam()

    def razdruzi_osebo(self, oseba_id: str, identiteta) -> dict:
        if not isinstance(identiteta, (list, tuple)) or len(identiteta) != 2:
            raise ValueError("Neveljavna identiteta.")
        self.storitev.razdruzi_osebo(str(oseba_id), (str(identiteta[0]), str(identiteta[1])))
        return self.seznam()

    def nastavi_oznake(self, kanal_id: str, pogovor_id: str, oznake) -> dict:
        self.storitev.nastavi_oznake(str(kanal_id), str(pogovor_id), list(oznake or []))
        return self.seznam()

    def osebe(self) -> list:
        return [o.slovar() for o in self.storitev.graf.vse()]

    def pogovor(self, kanal_id: str, pogovor_id: str) -> list:
        self.storitev.oznaci_prebrano(kanal_id, pogovor_id)
        return [s.slovar() for s in self.storitev.sporocila(kanal_id, pogovor_id)]

    def poslji(self, kanal_id: str, pogovor_id: str, besedilo: str) -> dict:
        besedilo = str(besedilo).strip()
        if not besedilo:
            raise ValueError("Prazno sporočilo")
        if kanal_id == KANAL_LINKA:
            return self._poslji_po_linku(str(pogovor_id), besedilo)
        return self.storitev.poslji(kanal_id, pogovor_id, besedilo).slovar()

    # ------------------------------------------------------------------ Safeer Chat (Link)
    def _zagotovi_kanal_linka(self) -> None:
        st = self.storitev
        with st._zaklep, st.db:
            st.db.execute("INSERT OR IGNORE INTO kanali VALUES(?,?,?,?,?)",
                          (KANAL_LINKA, VRSTA_LINKA, "Safeer Link", "povezan", "{}"))

    def _pogovor_linka(self, naprava_id: str, ime: str, zadnje: str, cas: str, novih: int) -> None:
        st = self.storitev
        oseba = st.graf.dodaj(ime.strip() or naprava_id, [(VRSTA_LINKA, naprava_id)]).id
        with st._zaklep, st.db:
            prej = st.db.execute("SELECT neprebrano, zadnje_sporocilo, cas FROM pogovori WHERE id=? AND kanal_id=?",
                                 (naprava_id, KANAL_LINKA)).fetchone()
            neprebrano = (int(prej["neprebrano"] or 0) if prej else 0) + novih
            if prej and not zadnje:
                zadnje, cas = prej["zadnje_sporocilo"] or "", prej["cas"] or cas
            st.db.execute("INSERT OR REPLACE INTO pogovori(id,kanal_id,oseba_id,zadeva,zadnje_sporocilo,neprebrano,cas,identiteta) VALUES(?,?,?,?,?,?,?,?)",
                          (naprava_id, KANAL_LINKA, oseba, "", zadnje[:240], neprebrano, cas, naprava_id))

    def prejmi_klepet(self, od: str, ime: str, besedilo: str, cas: str = "", sid: str = "") -> bool:
        """chat.send z druge naprave; vrne True, ce je sporocilo novo (ne ponovljena dostava)."""
        od, besedilo = str(od or "").strip(), str(besedilo or "")[:NAJVEC_KLEPET]
        if not od or not besedilo.strip():
            return False
        self._zagotovi_kanal_linka()
        sid = "chat:" + (str(sid) or uuid.uuid4().hex)
        st = self.storitev
        with st._zaklep:
            if st.db.execute("SELECT 1 FROM sporocila WHERE id=? AND kanal_id=?", (sid, KANAL_LINKA)).fetchone():
                return False
        cas = _cas_klepeta(cas)
        with st._zaklep, st.db:
            st.db.execute("INSERT OR REPLACE INTO sporocila VALUES(?,?,?,?,?,?,?,?)",
                          (sid, od, KANAL_LINKA, "noter", besedilo, cas, "[]", "prejeto"))
        self._pogovor_linka(od, ime, besedilo.replace("\n", " "), cas, 1)
        return True

    def zacni_klepet(self, naprava_id: str, ime: str) -> dict:
        """Uporabnik pise napravi prvi: pogovor obstaja, preden je kaj poslano."""
        naprava_id = str(naprava_id or "").strip()
        if not naprava_id:
            raise ValueError("Ni naprave")
        self._zagotovi_kanal_linka()
        self._pogovor_linka(naprava_id, str(ime or ""), "", _cas_zdaj(), 0)
        return self.seznam()

    def naprave_za_klepet(self) -> list:
        try:
            return list(self.naprave_klepeta() if self.naprave_klepeta else [])
        except Exception:
            return []

    def _poslji_po_linku(self, naprava_id: str, besedilo: str) -> dict:
        if len(besedilo.encode("utf-8")) > NAJVEC_KLEPET:
            raise ValueError(NAPAKE_KLEPETA["meja"])
        if self.poslji_klepet is None:
            raise ValueError(NAPAKE_KLEPETA["ni_controla"])
        cas = _cas_zdaj()
        izid = str(self.poslji_klepet(naprava_id, besedilo, cas) or "")
        if izid not in ("accepted", "queued"):
            raise ValueError(NAPAKE_KLEPETA.get(izid, "Sporočila ni bilo mogoče poslati."))
        sid = "chat:ven:" + uuid.uuid4().hex
        st = self.storitev
        with st._zaklep, st.db:
            st.db.execute("INSERT OR REPLACE INTO sporocila VALUES(?,?,?,?,?,?,?,?)",
                          (sid, naprava_id, KANAL_LINKA, "ven", besedilo, cas, "[]",
                           "caka" if izid == "queued" else "poslano"))
            st.db.execute("UPDATE pogovori SET zadnje_sporocilo=?,cas=? WHERE id=? AND kanal_id=?",
                          (besedilo[:240], cas, naprava_id, KANAL_LINKA))
        return {"id": sid, "pogovor_id": naprava_id, "smer": "ven", "besedilo": besedilo, "cas": cas,
                "stanje": "caka" if izid == "queued" else "poslano", "caka": izid == "queued"}

    def isci(self, niz: str) -> list:
        n = str(niz).casefold().strip()
        if not n:
            return []
        return [s for s in self.storitev.zdruzeni_pogovori()
                if n in (s["oseba"]["ime"] + " " + s["oseba"].get("privzeto_ime", "") + " " +
                         " ".join(p["zadnje_sporocilo"] + " " + p["zadeva"] + " " + p["id"] + " " + " ".join(p.get("oznake", []))
                                  for p in s["pogovori"])).casefold()][:20]

    def sinhroniziraj(self) -> dict:
        self.storitev.sinhroniziraj()
        return self.seznam()

    def zapri(self) -> None:
        self.storitev.zapri()
