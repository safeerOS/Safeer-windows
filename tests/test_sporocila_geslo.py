"""Geslo za e-posto: prilepljeni nedeljivi presledki in znaki izven ASCII ne smejo dati »streznika ni mogoce doseci«."""
import base64
import imaplib
import unittest
from unittest import mock

from core.sporocila import email as em


class OcistiGeslo(unittest.TestCase):
    def test_geslo_za_aplikacije_brez_presledkov(self):
        self.assertEqual(em.ocisti_geslo(" abcd efgh ijkl​mnop ", brez_presledkov=True), "abcdefghijklmnop")

    def test_navadno_geslo_ohrani_presledek(self):
        self.assertEqual(em.ocisti_geslo(" moje geslo﻿ "), "moje geslo")


class PrijavaUtf8(unittest.TestCase):
    def _adapter(self, geslo):
        return em.EmailAdapter("k", "a@b.si", "imap.b.si", "smtp.b.si", 993, 465, "a@b.si", geslo)

    def test_ascii_uporabi_login(self):
        imap = mock.MagicMock()
        with mock.patch.object(em.imaplib, "IMAP4_SSL", return_value=imap):
            self._adapter("abc").povezi()
        imap.login.assert_called_once_with("a@b.si", "abc")
        imap.authenticate.assert_not_called()

    def test_utf8_uporabi_authenticate_plain(self):
        imap = mock.MagicMock()
        with mock.patch.object(em.imaplib, "IMAP4_SSL", return_value=imap):
            self._adapter("geslošč").povezi()
        imap.login.assert_not_called()
        meh, odgovor = imap.authenticate.call_args[0]
        self.assertEqual(meh, "PLAIN")
        self.assertEqual(odgovor(b""), b"\0a@b.si\0" + "geslošč".encode("utf-8"))

    def test_zavrnjena_prijava_je_napaka_prijave(self):
        imap = mock.MagicMock()
        imap.authenticate.side_effect = imaplib.IMAP4.error("AUTHENTICATIONFAILED")
        with mock.patch.object(em.imaplib, "IMAP4_SSL", return_value=imap):
            with self.assertRaises(em.NapakaPrijave):
                self._adapter("geslošč").povezi()


class PosiljanjeUtf8(unittest.TestCase):
    """SMTP: smtplib.login zna samo ASCII - geslo s sumniki gre kot AUTH PLAIN v UTF-8 (Windows, 25. 10. 2026;
    isti preizkus naj dobi tudi Safeer-linux)."""

    def _adapter(self, geslo):
        return em.EmailAdapter("k", "a@b.si", "imap.b.si", "smtp.b.si", 993, 465, "a@b.si", geslo)

    def test_ascii_uporabi_login(self):
        smtp = mock.MagicMock()
        with mock.patch.object(em.smtplib, "SMTP_SSL", return_value=smtp):
            self._adapter("abc").poslji("c@d.si", "zivjo")
        smtp.login.assert_called_once_with("a@b.si", "abc")
        smtp.docmd.assert_not_called()
        smtp.send_message.assert_called_once()

    def test_utf8_poslje_auth_plain(self):
        smtp = mock.MagicMock()
        smtp.docmd.return_value = (235, b"2.7.0 Accepted")
        with mock.patch.object(em.smtplib, "SMTP_SSL", return_value=smtp):
            self._adapter("geslo\u00a0š").poslji("c@d.si", "zivjo")
        smtp.login.assert_not_called()
        ukaz, argument = smtp.docmd.call_args[0]
        self.assertEqual(ukaz, "AUTH")
        meh, kodirano = argument.split(" ", 1)
        self.assertEqual(meh, "PLAIN")
        self.assertEqual(base64.b64decode(kodirano), b"\0a@b.si\0" + "geslo\u00a0š".encode("utf-8"))
        smtp.send_message.assert_called_once()

    def test_zavrnjena_utf8_prijava_je_napaka_prijave(self):
        smtp = mock.MagicMock()
        smtp.docmd.return_value = (535, b"5.7.8 Username and Password not accepted")
        with mock.patch.object(em.smtplib, "SMTP_SSL", return_value=smtp):
            with self.assertRaises(em.NapakaPrijave):
                self._adapter("geslošč").poslji("c@d.si", "zivjo")
        smtp.send_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
