import json
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch

from core.sporocila.chatwoot import ChatwootAdapter
from core.sporocila.email import EmailAdapter
from core.sporocila.identiteta import IdentitetniGraf, normaliziraj
from core.sporocila.model import Kanal, Oseba, Pogovor, Sporocilo
from core.sporocila.storitev import StoritevSporocil


def test_model_json_roundtrip():
    modeli = [
        Kanal("k", "email", "Pošta", "povezan"),
        Oseba("o", "Ana", [("email", "ana@example.test")]),
        Pogovor("p", "k", "o", "Zadeva", "Živjo", 2, "2026-09-28T10:00:00+00:00"),
        Sporocilo("s", "p", "noter", "Živjo", "2026-09-28T10:00:00+00:00", [{"ime": "a.txt"}], "prejeto"),
    ]
    for model in modeli:
        assert type(model).from_json(model.to_json()) == model


def test_identitetni_graf_zdruzi_email_in_telefon():
    with tempfile.TemporaryDirectory() as d:
        g = IdentitetniGraf(Path(d) / "sporocila.db")
        a = g.dodaj("Ana", [("email", "ANA@EXAMPLE.TEST"), ("telefon", "+386 40 123 456")])
        assert g.dodaj("A.", [("email", "ana@example.test")]).id == a.id
        assert g.dodaj("Ana T.", [("telefon", "+38640123456")]).id == a.id
        nova = g.razdruzi(a.id, [("telefon", "+386 40 123 456")], "Drug telefon")
        assert nova.id != a.id
        assert normaliziraj("telefon", "+386 40 123 456") == "+38640123456"
        g.zapri()


def _email_surov(od=b"Ana <ana@example.test>", komu=b"jaz@example.test", zadeva=b"Pozdrav", mid=b"m1", telo=b"Zivjo"):
    return (b"From: " + od + b"\r\nTo: " + komu + b"\r\nSubject: " + zadeva +
            b"\r\nDate: Mon, 28 Sep 2026 10:00:00 +0000\r\nMessage-ID: <" + mid + b"@example.test>\r\n\r\n" + telo +
            b"\r\n\r\nOn Mon, Ana wrote:\r\n> staro besedilo\r\n")


def test_email_nit_po_osebi_brez_oznacevanja_prebranega_in_odgovor():
    imap = MagicMock()
    imap.noop.return_value = ("OK", [b""])
    klici = []

    def uid(ukaz, *argumenti):
        klici.append((ukaz,) + argumenti)
        if ukaz == "search":
            return ("OK", [b"7 8"]) if argumenti[-1] == "ALL" else ("OK", [b""])
        if ukaz == "fetch":
            return ("OK", [(b"7 (UID 7 FLAGS (\\Seen) BODY[]<0> {1}", _email_surov()), b")",
                           (b"8 (UID 8 FLAGS () BODY[]<0> {1}", _email_surov(zadeva=b"Re: Pozdrav", mid=b"m2", telo=b"Kje si?")), b")"])
        return ("OK", [b""])
    imap.uid.side_effect = uid
    smtp = MagicMock()
    with patch("core.sporocila.email.imaplib.IMAP4_SSL", return_value=imap), \
         patch("core.sporocila.email.smtplib.SMTP_SSL", return_value=smtp):
        a = EmailAdapter("k", "jaz@example.test", "imap.example.test", "smtp.example.test", geslo="skrivno")
        pogovori = list(a.pogovori())
        assert len(pogovori) == 1 and pogovori[0].id == "ana@example.test"      # ena nit na osebo
        assert pogovori[0].neprebrano == 1 and pogovori[0].zadnje_sporocilo == "Kje si?"
        sp = a.sporocila("ana@example.test")
        assert [x.besedilo for x in sp] == ["Zivjo", "Kje si?"]                  # brez citata
        fetch = [k for k in klici if k[0] == "fetch"][0]
        assert "BODY.PEEK[]" in fetch[2]                                        # ne oznaci prebranega
        list(a.pogovori())
        assert [k for k in klici if k[0] == "search"][-1][-1] == "9:*"          # samo nova pisma
        poslano = a.poslji("ana@example.test", "Doma sem")
        assert poslano.smer == "ven"
        smtp.login.assert_called_once_with("jaz@example.test", "skrivno")
        msg = smtp.send_message.call_args.args[0]
        assert msg["Subject"] == "Re: Pozdrav" and msg["In-Reply-To"] == "<m2@example.test>"
        stanje = a.stanje()
        assert stanje["zadnji_uid"] == 8 and "skrivno" not in json.dumps(stanje)


class _HTTP:
    def __init__(self, podatki): self.podatki = podatki
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def read(self): return json.dumps(self.podatki).encode()


def test_chatwoot_adapter_mock_urllib():
    odgovor = {"data": {"payload": [{"id": 4, "unread_count": 1,
        "meta": {"sender": {"id": 8}}, "last_non_activity_message": {"content": "Pozdrav", "created_at": 10}}]}}
    with patch("core.sporocila.chatwoot.urlopen", return_value=_HTTP(odgovor)) as odpri:
        a = ChatwootAdapter("cw", "https://chatwoot.example.test", 2, "skrivni-zeton")
        pogovor = list(a.pogovori())[0]
        assert pogovor.id == "4" and pogovor.neprebrano == 1
        assert odpri.call_args.args[0].get_header("Api_access_token") == "skrivni-zeton"


class _Adapter:
    vrsta, zmore = "email", {"poslji"}
    def povezi(self): pass
    def pogovori(self, od=None): return [Pogovor("p", "k", "ana@example.test", "", "Pozdrav", 1, "2026-09-28T10:00:00Z")]
    def sporocila(self, pogovor_id, pred=None, najvec=50): return [Sporocilo("s", "p", "noter", "Pozdrav", "2026-09-28T10:00:00Z")]
    def poslji(self, pogovor_id, besedilo, priponke=()): return Sporocilo("s2", pogovor_id, "ven", besedilo, "2026-09-28T11:00:00Z")
    def oznaci_prebrano(self, pogovor_id): pass


def test_storitev_sinhronizira_in_ne_zapise_skrivnosti():
    with tempfile.TemporaryDirectory() as d:
        pot = Path(d) / "sporocila.db"
        s = StoritevSporocil(pot)
        s.registriraj(Kanal("k", "email", "Test"), _Adapter(), {"naslov": "jaz@example.test"})
        assert s.sinhroniziraj() == 1
        assert s.pogovori()[0].zadnje_sporocilo == "Pozdrav"
        assert "skriv" not in pot.read_bytes().decode("utf-8", "ignore").lower()
        try:
            s.registriraj(Kanal("x", "email", "X"), _Adapter(), {"geslo": "ne-sme-na-disk"})
            assert False
        except ValueError:
            pass
        s.zapri()


def test_email_datum_brez_pasu_je_utc():
    from email import message_from_bytes
    from core.sporocila.email import _cas
    msg = message_from_bytes(b"Date: Mon, 28 Sep 2026 06:24:36 -0000\r\n\r\nx")
    assert _cas(msg) == "2026-09-28T06:24:36+00:00"


def test_odstranitev_kanala_pocisti_osebe_brez_pogovorov():
    with tempfile.TemporaryDirectory() as d:
        s = StoritevSporocil(Path(d) / "sporocila.db")
        s.registriraj(Kanal("k", "email", "Test"), _Adapter(), {"naslov": "jaz@example.test"})
        s.sinhroniziraj()
        assert s.zdruzeni_pogovori()
        s.odstrani_kanal("k")
        assert s.zdruzeni_pogovori() == [] and s.kanali() == []
        assert s.graf.vse() == []
        s.zapri()
