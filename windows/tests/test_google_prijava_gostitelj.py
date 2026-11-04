"""Prijava Google (UA Firefox) samo za prave gostitelje Google.

Revizija 4. 11. 2026: host.startswith("accounts.google.") je veljal tudi za accounts.google.zlo.com, netloc z userinfo
(accounts.google.com@zlo.com) pa je dal gostitelja iz uporabniskega imena.
"""
import unittest

from safeer_windows import policy


class GooglePrijavaGostitelj(unittest.TestCase):
    def test_pravi_gostitelji(self):
        for url in ("https://accounts.google.com/signin", "https://accounts.google.si/", "https://accounts.google.co.uk/",
                    "https://accounts.google.com.au/x", "https://ACCOUNTS.GOOGLE.COM:443/", "https://myaccount.google.com/",
                    "https://www.google.com/accounts/x"):
            with self.subTest(url=url):
                self.assertTrue(policy.is_google_auth_url(url))

    def test_lazni_gostitelji(self):
        for url in ("https://accounts.google.zlo.com/", "https://accounts.google.com@zlo.com/",
                    "https://accounts.google.com:geslo@zlo.com/signin", "https://accounts.google.si.zlo.com/",
                    "https://accounts.google.zlo/", "https://zlo.com/?accounts.google.com", "https://xaccounts.google.com.zlo.net/"):
            with self.subTest(url=url):
                self.assertFalse(policy.is_google_auth_url(url))


if __name__ == "__main__":
    unittest.main()
