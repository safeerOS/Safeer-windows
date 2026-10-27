"""Znani ponudniki e-poste za Sporocila (Safeer OS na racunalniku; ista tabela kot PonudnikiEposte.kt na Androidu).

Uporabnik izbere ponudnika, vpise le naslov in geslo; streznike in vrata poznamo mi. Naslovi so javni podatki
ponudnikov, preverjeni 30. 9. 2026 z zivo povezavo (IMAP 993 TLS; SMTP 465 TLS ali 587 STARTTLS).
geslo: navadno | aplikacije (2FA + geslo za aplikacije) | oauth (geslo ni vec dovoljeno; OAuth se nimamo).
Aplikacije: ponudniki brez IMAP/SMTP in klepeti - na racunalniku kot spletna aplikacija (uradni naslov) ali
uradna stran za prenos; Safeer nicesar ne prenasa sam.
"""
from __future__ import annotations

NAVADNO, APLIKACIJE, OAUTH, DRUG = "navadno", "aplikacije", "oauth", "drug"

PONUDNIKI: list[dict] = [
    {"id": "gmail", "ime": "Gmail", "domene": ["gmail.com", "googlemail.com"], "imap": "imap.gmail.com", "imap_vrata": 993, "smtp": "smtp.gmail.com", "smtp_vrata": 465, "geslo": APLIKACIJE, "navodila": "gmail", "geslo_stran": "https://myaccount.google.com/apppasswords"},
    {"id": "siol", "ime": "Siol (Telekom Slovenije)", "domene": ["siol.net", "siol.com"], "imap": "imap.siol.net", "imap_vrata": 993, "smtp": "mail.siol.net", "smtp_vrata": 465, "geslo": NAVADNO, "navodila": "navadno"},
    {"id": "t2", "ime": "T-2", "domene": ["t-2.net", "t-2.si"], "imap": "imap.t-2.net", "imap_vrata": 993, "smtp": "smtp.t-2.net", "smtp_vrata": 465, "geslo": NAVADNO, "navodila": "navadno"},
    {"id": "telemach", "ime": "Telemach", "domene": ["telemach.net", "telemach.si"], "imap": "imap.telemach.net", "imap_vrata": 993, "smtp": "smtp.telemach.net", "smtp_vrata": 587, "geslo": NAVADNO, "navodila": "navadno"},
    {"id": "amis", "ime": "Amis", "domene": ["amis.net"], "imap": "imap.amis.net", "imap_vrata": 993, "smtp": "smtp.amis.net", "smtp_vrata": 465, "geslo": NAVADNO, "navodila": "navadno"},
    {"id": "arnes", "ime": "Arnes", "domene": ["arnes.si", "guest.arnes.si"], "imap": "imap.arnes.si", "imap_vrata": 993, "smtp": "mail.arnes.si", "smtp_vrata": 465, "geslo": NAVADNO, "navodila": "arnes"},
    {"id": "yahoo", "ime": "Yahoo Mail", "domene": ["yahoo.com", "yahoo.co.uk", "yahoo.de", "ymail.com", "rocketmail.com"], "imap": "imap.mail.yahoo.com", "imap_vrata": 993, "smtp": "smtp.mail.yahoo.com", "smtp_vrata": 465, "geslo": APLIKACIJE, "navodila": "yahoo", "geslo_stran": "https://login.yahoo.com/account/security"},
    {"id": "icloud", "ime": "iCloud Mail", "domene": ["icloud.com", "me.com", "mac.com"], "imap": "imap.mail.me.com", "imap_vrata": 993, "smtp": "smtp.mail.me.com", "smtp_vrata": 587, "geslo": APLIKACIJE, "navodila": "icloud", "geslo_stran": "https://account.apple.com"},
    {"id": "gmx", "ime": "GMX", "domene": ["gmx.net", "gmx.de", "gmx.at", "gmx.ch", "gmx.com"], "imap": "imap.gmx.net", "imap_vrata": 993, "smtp": "mail.gmx.net", "smtp_vrata": 465, "geslo": NAVADNO, "navodila": "gmx"},
    {"id": "mailcom", "ime": "mail.com", "domene": ["mail.com", "email.com", "usa.com"], "imap": "imap.mail.com", "imap_vrata": 993, "smtp": "smtp.mail.com", "smtp_vrata": 465, "geslo": NAVADNO, "navodila": "gmx"},
    {"id": "zoho", "ime": "Zoho Mail", "domene": ["zohomail.eu", "zohomail.com", "zoho.com", "zoho.eu"], "imap": "imap.zoho.eu", "imap_vrata": 993, "smtp": "smtp.zoho.eu", "smtp_vrata": 465, "geslo": APLIKACIJE, "navodila": "zoho"},
    {"id": "fastmail", "ime": "Fastmail", "domene": ["fastmail.com", "fastmail.fm"], "imap": "imap.fastmail.com", "imap_vrata": 993, "smtp": "smtp.fastmail.com", "smtp_vrata": 465, "geslo": APLIKACIJE, "navodila": "fastmail"},
    {"id": "posteo", "ime": "Posteo", "domene": ["posteo.de", "posteo.net", "posteo.eu"], "imap": "posteo.de", "imap_vrata": 993, "smtp": "posteo.de", "smtp_vrata": 465, "geslo": NAVADNO, "navodila": "navadno"},
    {"id": "seznam", "ime": "Seznam.cz", "domene": ["seznam.cz", "email.cz", "post.cz"], "imap": "imap.seznam.cz", "imap_vrata": 993, "smtp": "smtp.seznam.cz", "smtp_vrata": 465, "geslo": NAVADNO, "navodila": "navadno"},
    {"id": "outlook", "ime": "Outlook / Hotmail", "domene": ["outlook.com", "hotmail.com", "live.com", "msn.com", "outlook.de", "hotmail.de"], "imap": "outlook.office365.com", "imap_vrata": 993, "smtp": "smtp.office365.com", "smtp_vrata": 587, "geslo": OAUTH, "navodila": "oauth"},
    {"id": DRUG, "ime": "", "domene": [], "imap": "", "imap_vrata": 993, "smtp": "", "smtp_vrata": 465, "geslo": NAVADNO, "navodila": "drug"},
]

#: Ponudniki brez IMAP/SMTP in spletni klepeti so v core/spletni_klepeti.py (en katalog za Sporocila in stranske plosce
#: vseh brskalnikov Safeer; vdelajo se v Sporocila). Tu ostanejo programi, ki v enem oknu zdruzijo vec storitev - samo
#: uradna stran za prenos; Safeer nicesar ne prenasa sam.
APLIKACIJE_SPOROCIL: list[dict] = [
    # Vec kanalov v eni aplikaciji (lastnik, 12. 10. 2026): programi, ki v enem oknu zdruzijo vec storitev ali protokolov.
    # Najprej odprtokodni. Uradne strani preverjene 12. 10. 2026.
    {"ime": "Thunderbird", "vrsta": "vec", "opis": "e-pošta, koledar in klepet Matrix", "splet": "", "prenos": "https://www.thunderbird.net/"},
    {"ime": "Ferdium", "vrsta": "vec", "opis": "WhatsApp, Telegram, Discord, Slack … v enem oknu (odprta koda)", "splet": "", "prenos": "https://ferdium.org/download"},
    {"ime": "Pidgin", "vrsta": "vec", "opis": "XMPP, IRC in drugi protokoli (odprta koda)", "splet": "", "prenos": "https://pidgin.im/"},
    {"ime": "Delta Chat", "vrsta": "vec", "opis": "klepet prek tvoje e-pošte (odprta koda)", "splet": "", "prenos": "https://get.delta.chat"},
    {"ime": "Beeper", "vrsta": "vec", "opis": "WhatsApp, Signal, Telegram, Messenger, Instagram, Discord, Slack …", "splet": "", "prenos": "https://www.beeper.com/download"},
    {"ime": "Rambox", "vrsta": "vec", "opis": "delovni prostor za več storitev (del funkcij plačljiv)", "splet": "", "prenos": "https://rambox.app/"},
]


def po_id(pid: str) -> dict | None:
    return next((p for p in PONUDNIKI if p["id"] == pid), None)


def iz_naslova(naslov: str) -> dict | None:
    d = naslov.rsplit("@", 1)[-1].lower().strip()
    return next((p for p in PONUDNIKI if d in p["domene"]), None)


def za_vmesnik(jezik: str = "sl") -> dict:
    """Vse, kar potrebuje spletni vmesnik (brez navodil - ta so prevedena v besedila.js). »klepeti«: katalog vdeljivih
    spletnih klepetov in poste (core/spletni_klepeti.py) z imeni v jeziku vmesnika."""
    from core import spletni_klepeti
    return {"ponudniki": [{k: v for k, v in p.items()} for p in PONUDNIKI], "aplikacije": list(APLIKACIJE_SPOROCIL),
            "klepeti": spletni_klepeti.za_vmesnik(jezik)}
