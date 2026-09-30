"""Lastni API v Sporocilih: Matrix in Telegram Bot prek lazne mreze (urlopen), dodajanje kanala prek SporocilaOS,
iskanje po sporocilih ene osebe."""
import io, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.sporocila import matrix, telegram_bot, skrivnosti  # noqa: E402
from core.sporocila.storitev import StoritevSporocil  # noqa: E402
from core import os_sporocila  # noqa: E402


class Odgovor(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def lazna_mreza(odzivi):
    """odzivi: seznam (podniz_url, slovar ali HTTPError). Zabelezi klice v .klici."""
    klici = []
    def urlopen(zahteva, timeout=None):
        url = zahteva.full_url
        klici.append((zahteva.get_method(), url, zahteva.data, dict(zahteva.header_items())))
        for kos, odziv in odzivi:
            if kos in url:
                if isinstance(odziv, Exception):
                    raise odziv
                return Odgovor(json.dumps(odziv).encode("utf-8"))
        raise AssertionError("nepricakovan klic " + url)
    urlopen.klici = klici
    return urlopen


MATRIX_SYNC = {"next_batch": "s2", "account_data": {"events": [{"type": "m.direct", "content": {"@ana:matrix.org": ["!dm:matrix.org"]}}]},
               "rooms": {"join": {"!dm:matrix.org": {
                   "state": {"events": [{"type": "m.room.member", "state_key": "@ana:matrix.org", "content": {"membership": "join", "displayname": "Ana Kralj"}},
                                        {"type": "m.room.member", "state_key": "@jaz:matrix.org", "content": {"membership": "join", "displayname": "Jaz"}}]},
                   "timeline": {"events": [{"type": "m.room.message", "event_id": "$e1", "sender": "@ana:matrix.org", "origin_server_ts": 1790000000000,
                                            "content": {"msgtype": "m.text", "body": "Živjo, si za kavo?"}}]}}}}}


class Matrix(unittest.TestCase):
    def test_povezi_sync_poslji(self):
        mreza = lazna_mreza([("/account/whoami", {"user_id": "@jaz:matrix.org"}), ("/sync", MATRIX_SYNC),
                             ("/send/m.room.message/", {"event_id": "$poslano"}), ("/receipt/m.read/", {})])
        with mock.patch.object(matrix, "urlopen", mreza):
            a = matrix.MatrixAdapter("k1", "https://matrix.org", "ZETON")
            a.povezi()
            self.assertEqual(a.uporabnik, "@jaz:matrix.org")
            self.assertEqual(mreza.klici[0][3].get("Authorization"), "Bearer ZETON")
            pog = list(a.pogovori())
            self.assertEqual(len(pog), 1); self.assertEqual(pog[0].oseba_id, "@ana:matrix.org"); self.assertEqual(pog[0].neprebrano, 1)
            self.assertEqual(a.ime_osebe("@ana:matrix.org"), "Ana Kralj")
            sp = list(a.sporocila("!dm:matrix.org"))
            self.assertEqual(sp[0].besedilo, "Živjo, si za kavo?"); self.assertEqual(sp[0].smer, "noter")
            s = a.poslji("!dm:matrix.org", "Ja!")
            self.assertEqual(s.id, "$poslano"); self.assertEqual(s.smer, "ven")
            a.oznaci_prebrano("!dm:matrix.org")
            st = a.stanje(); b = matrix.MatrixAdapter("k1", "https://matrix.org", "ZETON"); b.obnovi(st)
            self.assertEqual(len(list(b.sporocila("!dm:matrix.org"))), 2)   # stanje prezivi ponovni zagon

    def test_slab_zeton(self):
        mreza = lazna_mreza([("/account/whoami", HTTPError("u", 401, "Unauthorized", {}, None))])
        with mock.patch.object(matrix, "urlopen", mreza):
            a = matrix.MatrixAdapter("k1", "https://matrix.org", "NAPACEN")
            with self.assertRaises(matrix.NapakaPrijave):
                a.povezi()


class Telegram(unittest.TestCase):
    def test_getme_updates_poslji(self):
        posod = [{"update_id": 7, "message": {"message_id": 1, "date": 1790000000, "chat": {"id": 555, "type": "private"},
                                              "from": {"id": 555, "first_name": "Bojan", "last_name": "Zupan"}, "text": "Pozdrav botu"}}]
        mreza = lazna_mreza([("/getMe", {"ok": True, "result": {"id": 99, "username": "safeer_bot"}}),
                             ("/getUpdates", {"ok": True, "result": posod}),
                             ("/sendMessage", {"ok": True, "result": {"message_id": 2, "date": 1790000100}})])
        with mock.patch.object(telegram_bot, "urlopen", mreza):
            a = telegram_bot.TelegramBotAdapter("k2", "123456:ABC")
            a.povezi(); self.assertEqual(a.bot["username"], "safeer_bot")
            self.assertIn("/bot123456:ABC/getMe", mreza.klici[0][1])
            pog = list(a.pogovori())
            self.assertEqual(pog[0].id, "555"); self.assertEqual(pog[0].oseba_id, "tg:555"); self.assertEqual(a.ime_osebe("tg:555"), "Bojan Zupan")
            s = a.poslji("555", "Hvala"); self.assertEqual(s.id, "2")
            self.assertEqual(json.loads(mreza.klici[-1][2])["chat_id"], 555)
            self.assertEqual(len(list(a.sporocila("555"))), 2)

    def test_slab_zeton(self):
        mreza = lazna_mreza([("/getMe", HTTPError("u", 404, "Not Found", {}, None))])
        with mock.patch.object(telegram_bot, "urlopen", mreza):
            with self.assertRaises(telegram_bot.NapakaPrijave):
                telegram_bot.TelegramBotAdapter("k2", "x:y").povezi()


class DodajKanalInIskanje(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.st = StoritevSporocil(Path(self.tmp) / "s.sqlite3")
        self.os = os_sporocila.SporocilaOS.__new__(os_sporocila.SporocilaOS); self.os.storitev = self.st
        self.p1 = mock.patch.object(skrivnosti, "shrani", lambda k, v: False); self.p1.start()
        self.p2 = mock.patch.object(os_sporocila.threading, "Thread", lambda **kw: mock.Mock()); self.p2.start()

    def tearDown(self):
        self.p1.stop(); self.p2.stop(); self.st.zapri()

    def test_preverjanje_vnosa(self):
        with self.assertRaises(ValueError): self.os.dodaj_kanal({"vrsta": "matrix", "streznik": "", "zeton": "x"})
        with self.assertRaises(ValueError): self.os.dodaj_kanal({"vrsta": "telegram_bot", "zeton": "brezdvopicja"})

    def test_matrix_kanal_in_iskanje_pri_osebi(self):
        mreza = lazna_mreza([("/account/whoami", {"user_id": "@jaz:matrix.org"}), ("/sync", MATRIX_SYNC), ("/receipt/", {})])
        with mock.patch.object(matrix, "urlopen", mreza):
            k = self.os.dodaj_kanal({"vrsta": "matrix", "streznik": "matrix.org", "zeton": "ZETON"})   # brez https:// -> doda sam
            self.assertEqual(k["vrsta"], "matrix"); self.assertEqual(k["ime"], "@jaz:matrix.org")
            self.st.sinhroniziraj()
        sez = self.os.seznam()
        self.assertEqual(sez["kanali"][0]["vrsta"], "matrix")
        skupina = sez["skupine"][0]; self.assertEqual(skupina["oseba"]["ime"], "Ana Kralj")
        zad = self.os.isci_pri_osebi(skupina["oseba"]["id"], "kavo")
        self.assertEqual(len(zad), 1); self.assertIn("kavo", zad[0]["izsek"]); self.assertEqual(zad[0]["kanal"]["vrsta"], "matrix")
        self.assertEqual(self.os.isci_pri_osebi(skupina["oseba"]["id"], "100%_nic"), [])
        self.assertEqual(self.os.isci_pri_osebi("neznana-oseba", "kavo"), [])

    def test_telegram_kanal(self):
        mreza = lazna_mreza([("/getMe", {"ok": True, "result": {"id": 99, "username": "safeer_bot"}}), ("/getUpdates", {"ok": True, "result": []})])
        with mock.patch.object(telegram_bot, "urlopen", mreza):
            k = self.os.dodaj_kanal({"vrsta": "telegram_bot", "zeton": "123456:ABCDEFGHIJKLMNOPQRS"})
        self.assertEqual(k["ime"], "Telegram @safeer_bot")
        self.assertEqual(json.loads(self.st.db.execute("SELECT nastavitve FROM kanali").fetchone()[0]).get("bot"), "safeer_bot")


if __name__ == "__main__":
    unittest.main()
