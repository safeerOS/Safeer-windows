"""E-posta (IMAP + SMTP) kot kanal Safeer Sporocil - samo standardna knjiznica.

Pogovor je oseba (njen e-naslov), ne posamezno pismo: vsa pisma z isto osebo so ena nit, kot v
klepetu. Pisma beremo z BODY.PEEK, zato jih sinhronizacija NE oznaci kot prebrana; prenesemo le
nova pisma (UID vecji od zadnjega) in iz vsakega najvec prvih 64 KB - lahko za pomnilnik in omrezje.
"""

from __future__ import annotations

from datetime import datetime, timezone
from email import message_from_bytes, policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr, parsedate_to_datetime
import imaplib
import re
import smtplib
import ssl
from typing import Callable, Dict, Iterable, List, Optional, Sequence

from .adapter import Adapter
from .model import Pogovor, Sporocilo
from . import skrivnosti

PRVIC_NAJVEC = 200        # ob prvi povezavi zadnjih 200 pisem
NAJVEC_BAJTOV = 65536     # iz vsakega pisma prvih 64 KB (besedilo, ne priponke)
CASOVNA_OMEJITEV = 20


class NapakaPrijave(RuntimeError):
    """Streznik je zavrnil uporabnisko ime ali geslo."""


def _glava(vrednost) -> str:
    try:
        return str(make_header(decode_header(str(vrednost or ""))))
    except Exception:
        return str(vrednost or "")


def _cas(msg) -> str:
    try:
        dt = parsedate_to_datetime(msg.get("Date"))
        if dt.tzinfo is None:          # "-0000" (RFC 5322: pas neznan) - vzamemo UTC, ne krajevni cas
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _brez_html(besedilo: str) -> str:
    besedilo = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", besedilo)
    besedilo = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", besedilo)
    besedilo = re.sub(r"<[^>]+>", " ", besedilo)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
        besedilo = besedilo.replace(a, b)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", besedilo)).strip()


def _brez_citata(besedilo: str) -> str:
    """Odgovor brez citiranega prejsnjega pisma (vrstice z > in vse po 'On ... wrote:')."""
    vrstice = []
    for v in besedilo.splitlines():
        if re.match(r"^\s*(On|Dne|Am|Le|El|Il)\b.{0,200}(wrote|napisal|schrieb|écrit|escribió|scritto)", v, re.I):
            break
        if v.lstrip().startswith(">"):
            continue
        vrstice.append(v)
    return "\n".join(vrstice).strip() or besedilo.strip()


def telo_pisma(msg) -> str:
    deli = msg.walk() if msg.is_multipart() else (msg,)
    html = ""
    for del_ in deli:
        if del_.get_content_disposition() == "attachment":
            continue
        tip = del_.get_content_type()
        if tip not in ("text/plain", "text/html"):
            continue
        try:
            vrednost = str(del_.get_content())
        except Exception:
            vrednost = (del_.get_payload(decode=True) or b"").decode(del_.get_content_charset() or "utf-8", "replace")
        if tip == "text/plain" and vrednost.strip():
            return _brez_citata(vrednost.strip())
        if tip == "text/html" and not html:
            html = _brez_citata(_brez_html(vrednost))
    return html


def _priponke(msg) -> List[dict]:
    out = []
    for d in msg.walk():
        if d.get_content_disposition() == "attachment":
            out.append({"ime": _glava(d.get_filename() or "priponka"), "tip": d.get_content_type()})
    return out


class EmailAdapter(Adapter):
    vrsta = "email"
    zmore = {"poslji"}

    def __init__(self, kanal_id: str, naslov: str, imap_streznik: str, smtp_streznik: str,
                 imap_vrata: int = 993, smtp_vrata: int = 465, uporabnik: str = "",
                 geslo: str = "", vnos_gesla: Optional[Callable[[], str]] = None):
        self.kanal_id, self.naslov = kanal_id, naslov.strip()
        self.imap_streznik, self.smtp_streznik = imap_streznik, smtp_streznik
        self.imap_vrata, self.smtp_vrata = int(imap_vrata), int(smtp_vrata)
        self.uporabnik = uporabnik or self.naslov
        self._geslo, self._vnos_gesla = geslo, vnos_gesla
        self._imap: Optional[imaplib.IMAP4_SSL] = None
        self.zadnji_uid = 0
        # Sporocila zadnje sinhronizacije po osebi (storitev jih shrani v bazo).
        self._nova: Dict[str, List[Sporocilo]] = {}
        self._zadnja_niti: Dict[str, dict] = {}   # oseba -> {"zadeva", "message_id", "uidi"}

    # --------------------------------------------------------------- skrivnost
    @property
    def kljuc_skrivnosti(self) -> str:
        return "email:" + self.kanal_id

    def shrani_geslo(self, geslo: str) -> bool:
        self._geslo = geslo
        return skrivnosti.shrani(self.kljuc_skrivnosti, geslo)

    def pozabi_geslo(self) -> None:
        self._geslo = ""
        skrivnosti.pozabi(self.kljuc_skrivnosti)

    def _skrivnost(self) -> str:
        return skrivnosti.zahtevaj(self.kljuc_skrivnosti, self._geslo, self._vnos_gesla)

    # --------------------------------------------------------------- povezava
    def povezi(self) -> None:
        if self._imap is not None:
            try:
                if self._imap.noop()[0] == "OK":
                    return
            except Exception:
                pass
            self._imap = None
        imap = imaplib.IMAP4_SSL(self.imap_streznik, self.imap_vrata,
                                 ssl_context=ssl.create_default_context(), timeout=CASOVNA_OMEJITEV)
        try:
            imap.login(self.uporabnik, self._skrivnost())
        except imaplib.IMAP4.error as e:
            try:
                imap.logout()
            except Exception:
                pass
            raise NapakaPrijave("Prijava ni uspela") from e
        imap.select("INBOX", readonly=False)
        self._imap = imap

    def zapri(self) -> None:
        if self._imap is not None:
            try:
                self._imap.logout()
            except Exception:
                pass
            self._imap = None

    # --------------------------------------------------------------- branje
    def _nova_pisma(self):
        self.povezi()
        if self.zadnji_uid:
            status, odg = self._imap.uid("search", None, "UID", "%d:*" % (self.zadnji_uid + 1))
        else:
            status, odg = self._imap.uid("search", None, "ALL")
        if status != "OK" or not odg or not odg[0]:
            return []
        uidi = sorted(int(u) for u in odg[0].split() if int(u) > self.zadnji_uid)
        if not self.zadnji_uid:
            uidi = uidi[-PRVIC_NAJVEC:]
        pisma = []
        for i in range(0, len(uidi), 25):
            skupina = ",".join(str(u) for u in uidi[i:i + 25])
            status, podatki = self._imap.uid("fetch", skupina, "(UID FLAGS BODY.PEEK[]<0.%d>)" % NAJVEC_BAJTOV)
            if status != "OK":
                continue
            for kos in podatki or []:
                if not isinstance(kos, tuple) or len(kos) < 2:
                    continue
                glava = kos[0].decode("utf-8", "replace") if isinstance(kos[0], bytes) else str(kos[0])
                m = re.search(r"UID (\d+)", glava)
                if not m:
                    continue
                pisma.append((int(m.group(1)), "\\Seen" in glava, message_from_bytes(kos[1], policy=policy.default)))
        return pisma

    def pogovori(self, od: Optional[str] = None) -> Iterable[Pogovor]:
        self._nova = {}
        pogovori: Dict[str, Pogovor] = {}
        lasten = self.naslov.casefold()
        for uid, prebrano, msg in sorted(self._nova_pisma(), key=lambda x: x[0]):
            self.zadnji_uid = max(self.zadnji_uid, uid)
            od_koga = parseaddr(str(msg.get("From", "")))
            komu = parseaddr(str(msg.get("To", "")))
            moje = od_koga[1].casefold() == lasten
            ime, naslov = (komu if moje else od_koga)
            oseba = (naslov or "neznan").casefold()
            zadeva = _glava(msg.get("Subject"))
            cas = _cas(msg)
            besedilo = telo_pisma(msg)
            mid = str(msg.get("Message-ID") or "").strip()
            s = Sporocilo("uid:%d" % uid, oseba, "ven" if moje else "noter", besedilo, cas, _priponke(msg),
                          "poslano" if moje else ("prebrano" if prebrano else "prejeto"))
            self._nova.setdefault(oseba, []).append(s)
            nit = self._zadnja_niti.setdefault(oseba, {"uidi": []})
            nit.update({"zadeva": zadeva, "message_id": mid, "ime": _glava(ime)})
            nit["uidi"].append(uid)
            p = pogovori.get(oseba) or Pogovor(oseba, self.kanal_id, oseba, zadeva, "", 0, cas)
            p.zadeva, p.zadnje_sporocilo, p.cas = zadeva, besedilo.replace("\n", " ")[:240], cas
            if not moje and not prebrano:
                p.neprebrano += 1
            pogovori[oseba] = p
        return list(pogovori.values())

    def ime_osebe(self, oseba: str) -> str:
        return (self._zadnja_niti.get(oseba) or {}).get("ime", "")

    def sporocila(self, pogovor_id: str, pred: Optional[str] = None,
                  najvec: int = 50) -> Iterable[Sporocilo]:
        return list(self._nova.get(pogovor_id, []))[-max(1, int(najvec)):]

    # --------------------------------------------------------------- pisanje
    def poslji(self, pogovor_id: str, besedilo: str,
               priponke: Sequence[dict] = ()) -> Sporocilo:
        prejemnik = pogovor_id if "@" in pogovor_id else ""
        if not prejemnik:
            raise ValueError("Ni naslova prejemnika")
        nit = self._zadnja_niti.get(pogovor_id) or {}
        zadeva = nit.get("zadeva") or ""
        msg = EmailMessage()
        msg["From"], msg["To"] = self.naslov, prejemnik
        msg["Subject"] = zadeva if zadeva.lower().startswith(("re:", "odg:", "aw:")) else ("Re: " + zadeva if zadeva else "Sporočilo")
        if nit.get("message_id"):
            msg["In-Reply-To"] = nit["message_id"]
            msg["References"] = nit["message_id"]
        msg["Message-ID"] = make_msgid(domain=self.naslov.rsplit("@", 1)[-1] or None)
        msg.set_content(besedilo)
        kontekst = ssl.create_default_context()
        # 587 in 25 = STARTTLS, vse drugo (465 in nestandardna vrata) = neposreden TLS.
        if self.smtp_vrata not in (587, 25):
            smtp = smtplib.SMTP_SSL(self.smtp_streznik, self.smtp_vrata, context=kontekst, timeout=CASOVNA_OMEJITEV)
        else:
            smtp = smtplib.SMTP(self.smtp_streznik, self.smtp_vrata, timeout=CASOVNA_OMEJITEV)
            smtp.starttls(context=kontekst)
        try:
            try:
                smtp.login(self.uporabnik, self._skrivnost())
            except smtplib.SMTPAuthenticationError as e:
                raise NapakaPrijave("Prijava ni uspela") from e
            smtp.send_message(msg)
        finally:
            try:
                smtp.quit()
            except Exception:
                pass
        cas = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        return Sporocilo("mid:" + str(msg["Message-ID"]).strip("<>"), pogovor_id, "ven", besedilo, cas, [], "poslano")

    def oznaci_prebrano(self, pogovor_id: str) -> None:
        uidi = (self._zadnja_niti.get(pogovor_id) or {}).get("uidi") or []
        if not uidi:
            return
        self.povezi()
        self._imap.uid("store", ",".join(str(u) for u in uidi[-200:]), "+FLAGS", "(\\Seen)")

    # --------------------------------------------------------------- stanje med zagoni
    def stanje(self) -> dict:
        """Kar mora ostati med zagoni (brez skrivnosti in brez vsebine pisem)."""
        return {"zadnji_uid": self.zadnji_uid,
                "niti": {o: {"zadeva": n.get("zadeva", ""), "message_id": n.get("message_id", ""),
                             "ime": n.get("ime", ""), "uidi": n.get("uidi", [])[-50:]}
                         for o, n in list(self._zadnja_niti.items())[-500:]}}

    def obnovi(self, stanje: dict) -> None:
        self.zadnji_uid = int(stanje.get("zadnji_uid") or 0)
        self._zadnja_niti = {str(o): dict(n) for o, n in (stanje.get("niti") or {}).items()}
