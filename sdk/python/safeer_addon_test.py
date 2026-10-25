"""Tests of the Safeer add-on SDK (Python part): the shared test vectors, the checker, both templates and the shared
copies. Run from the repository root:

    python3 -m unittest discover -s sdk/python -p "*_test.py"

Preizkusi SDK: skupni primeri (isti kot na Androidu), orodje za preverjanje, obe predlogi in skupne kopije datotek.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SDK = os.path.dirname(HERE)
ROOT = os.path.dirname(SDK)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(SDK, "templates", "python"))

import addon as template  # noqa: E402
import check_addon as ca  # noqa: E402
import safeer_addon as sa  # noqa: E402

template.Handler.log_message = lambda *a, **k: None   # quiet tests

with open(os.path.join(SDK, "skupni-primeri", "protokol-v1.json"), encoding="utf-8") as _f:
    VECTORS = json.load(_f)


# Summaries - the same format as tests/DodatkiProtokolPrimeriTest.kt in the Android-tv repository.
def ext_summary(e):
    if e is None:
        return "none"
    a = "|".join("%s[%s]%s/%d/%s" % (x.id, ",".join(sorted(x.on)), x.icon, 1 if x.confirm else 0,
                                     x.label.for_lang("sl")) for x in e.actions)
    f = "|".join("%s/%s/%s" % (x.id, x.icon, x.name.for_lang("de")) for x in e.folders)
    s = "|".join("%s/%s/%d/%s/%s" % (x.key, x.type, 1 if x.required else 0, x.default, ",".join(x.options))
                 for x in e.settings)
    return "p=%d;new=%d;a=%s;e=%s;f=%s;s=%s;c=%s;w=%d" % (
        e.protocol, 1 if e.newer else 0, a, ",".join(sorted(e.enrich)), f, s, ",".join(sorted(e.changelog)),
        len(e.warnings))


def folder_summary(r):
    if r is None:
        return "none"
    items, nxt = r
    return "|".join("%s/%s/%s/%s/%s/%s" % (i.kind, i.path, i.type, i.id, i.name, i.poster) for i in items) + \
        ";next=" + nxt


def action_summary(r):
    if r is None:
        return "none"
    return "ok=%d;msg=%s;refresh=%d" % (1 if r.ok else 0, r.message.for_lang("sl") if r.message else "",
                                       1 if r.refresh else 0)


class SharedVectors(unittest.TestCase):
    def test_protocol_version(self):
        self.assertEqual(sa.VERSION, VECTORS["verzija_protokola"])
        with open(os.path.join(ROOT, "docs", "DODATKI-PROTOKOL.md"), encoding="utf-8") as f:
            self.assertIn("<!-- PROTOKOL-VERZIJA: %d -->" % sa.VERSION, f.read())

    def test_extension(self):
        for c in VECTORS["razsiritev"]:
            with self.subTest(c["ime"]):
                self.assertEqual(c["povzetek"], ext_summary(sa.parse_extension(c["manifest"])))
                # Text in, same result (the host reads the text).
                self.assertEqual(c["povzetek"], ext_summary(sa.parse_extension(json.dumps(c["manifest"]))))

    def test_header(self):
        for c in VECTORS["glava"]:
            with self.subTest(c["ime"]):
                e = sa.parse_extension(c["manifest"])
                h = sa.config_header(sa.settings_for_request(e.settings, c["url"]), c["vrednosti"])
                self.assertNotIn("=", h)
                raw = sa.base64.urlsafe_b64decode(h + "=" * (-len(h) % 4)).decode("utf-8")
                self.assertEqual(c["json"], raw)
                self.assertEqual(json.loads(c["json"]), sa.decode_config_header(h))

    def test_may_send_and_local(self):
        for c in VECTORS["sme_poslati"]:
            with self.subTest(c["url"]):
                self.assertEqual(c["pricakovano"], sa.may_send(c["url"], c["razvojni"]))
        for c in VECTORS["krajevni"]:
            with self.subTest(c["gostitelj"]):
                self.assertEqual(c["pricakovano"], sa.is_local(c["gostitelj"]))

    def test_urls(self):
        for c in VECTORS["naslovi"]:
            with self.subTest(c["pricakovano"]):
                if c["vrsta"] == "dejanje":
                    got = sa.action_url(c["osnova"], c["dejanje"], c["tip"], c["id"])
                elif c["vrsta"] == "dopolni":
                    got = sa.enrich_url(c["osnova"], c["tip"], c["id"])
                else:
                    got = sa.folder_url(c["osnova"], c["mapa"], c["pot"])
                self.assertEqual(c["pricakovano"], got)

    def test_responses(self):
        for c in VECTORS["mapa"]:
            with self.subTest(c["povzetek"]):
                self.assertEqual(c["povzetek"], folder_summary(sa.parse_folder(json.dumps(c["odgovor"]))))
        for c in VECTORS["dejanje"]:
            with self.subTest(c["povzetek"]):
                self.assertEqual(c["povzetek"], action_summary(sa.parse_action(json.dumps(c["odgovor"]))))

    def test_changelog(self):
        e = sa.parse_extension(VECTORS["spremembe"]["manifest"])
        for c in VECTORS["spremembe"]["primeri"]:
            with self.subTest(c):
                t = sa.changelog_to_show(e, c["prejsnja"], c["zdaj"])
                self.assertEqual(c["pricakovano"], t.for_lang("en") if t else None)


class FakeFetch:
    """Answers from a dict {url suffix: (status, body, headers)} - no network."""

    def __init__(self, answers, ms=10):
        self.answers, self.ms, self.calls = answers, ms, []

    def __call__(self, url, headers, limit):
        self.calls.append((url, dict(headers)))
        for suffix, (status, body, hdrs) in self.answers.items():
            if url.endswith(suffix):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                return ca.Response(status, data[:limit + 1], self.ms, hdrs, url, too_big=len(data) > limit)
        return None


def manifest(**over):
    m = {"id": "org.example.x", "version": "1.0.0", "name": "X", "resources": ["stream"], "types": ["movie"],
         "catalogs": []}
    m.update(over)
    return m


class Checker(unittest.TestCase):
    def run_check(self, answers, url="https://a.example/manifest.json", **kw):
        c = ca.Checker(fetch=FakeFetch(answers), **{k: v for k, v in kw.items() if k in ("developer_mode", "config", "lang")})
        c.check(url, kw.get("content"), kw.get("actions", False))
        return c

    def has(self, c, level, text):
        return any(line.startswith(c.t[level]) and text in line for line in c.lines)

    def test_install_url_rules(self):
        probs = dict((m.split(" - ")[0], lvl) for lvl, m in sa.install_url_problems("https://u:p@a.example/x/manifest.json?k=1#f"))
        self.assertEqual({"user:password in the URL": "error", "query string (?...)": "error", "fragment (#...)": "error"},
                         probs)
        self.assertEqual([], sa.install_url_problems("stremio://a.example/x/manifest.json"))
        self.assertEqual("error", sa.install_url_problems("http://a.example/manifest.json")[0][0])
        self.assertEqual("warn", sa.install_url_problems("http://192.168.1.2:7000/manifest.json")[0][0])

    def test_plain_stremio_addon(self):
        c = self.run_check({"/manifest.json": (200, manifest(), {"Content-Type": "application/json"}),
                            "/stream/movie/tt1.json": (200, {"streams": [{"url": "https://cdn.example/v.mp4"}]}, {})},
                           content=("movie", "tt1"))
        self.assertEqual(0, c.errors, c.lines)
        self.assertTrue(self.has(c, "OK", "plain Stremio add-on"))
        self.assertTrue(self.has(c, "OK", "direct 1, torrent 0"))

    def test_limits_429_and_redirect(self):
        big = b'{"x":"' + b"a" * (8 * 1024 * 1024) + b'"}'
        c = self.run_check({"/manifest.json": (200, big, {})})
        self.assertTrue(self.has(c, "ERROR", "larger than 8 MiB"))
        mid = json.dumps(dict(manifest(), pad="a" * (6 * 1024 * 1024))).encode()
        c = self.run_check({"/manifest.json": (200, mid, {})})
        self.assertTrue(self.has(c, "WARN", "over 5 MiB"))
        c = self.run_check({"/manifest.json": (429, b"{}", {})})
        self.assertTrue(self.has(c, "ERROR", "429 without Retry-After"))
        c = self.run_check({"/manifest.json": (429, b"{}", {"Retry-After": "30"})})
        self.assertEqual(0, c.errors)
        self.assertTrue(self.has(c, "WARN", "asks to wait 30"))

        def redirected(url, headers, limit):
            return ca.Response(200, json.dumps(manifest()).encode(), 5, {}, "http://a.example/manifest.json")
        c = ca.Checker(fetch=redirected)
        c.check("https://a.example/manifest.json")
        self.assertTrue(self.has(c, "ERROR", "redirected from https to http"))

    def test_manifest_rules(self):
        c = ca.Checker(fetch=FakeFetch({}))
        c.check_manifest({"name": "Adult films 18+", "resources": ["catalog"], "types": ["movie"], "version": "1",
                          "behaviorHints": {"configurationRequired": True}})
        for level, text in (("ERROR", "'id' missing"), ("WARN", "not semver"), ("WARN", "no 'stream' resource"),
                            ("WARN", "behaviorHints.adult is not true"), ("WARN", "configurationRequired")):
            self.assertTrue(self.has(c, level, text), (level, text, c.lines))
        c = ca.Checker(fetch=FakeFetch({}))
        c.check_manifest(manifest(behaviorHints={"adult": True}))
        self.assertTrue(self.has(c, "INFO", "private add-on"))

    def test_streams(self):
        streams = [{"url": "http://cdn.example/a.mp4", "name": "A"}, {"infoHash": "a" * 40, "fileIdx": 0},
                   {"infoHash": "xyz"}, {"ytId": "abc"}, {"externalUrl": "https://shop.example"}]
        c = self.run_check({"/manifest.json": (200, manifest(), {}),
                            "/stream/movie/tt1.json": (200, {"streams": streams}, {})}, content=("movie", "tt1"))
        self.assertTrue(self.has(c, "OK", "direct 1, torrent 1, trailers 1"))
        self.assertTrue(self.has(c, "WARN", "stream over http"))
        self.assertTrue(self.has(c, "WARN", "infoHash is not 40 hex"))
        c = self.run_check({"/manifest.json": (200, manifest(), {}),
                            "/stream/movie/tt1.json": (200, {"streams": [{"externalUrl": "https://x.example"}]}, {})},
                           content=("movie", "tt1"))
        self.assertTrue(self.has(c, "WARN", "only links to web pages"))

    def test_secret_never_over_http(self):
        m = manifest(safeer={"protocol": 1, "settings": [
            {"key": "api_key", "type": "secret", "label": "Key"}, {"key": "lang", "type": "text", "label": "L"}],
            "folders": [{"id": "f", "name": "F"}]})
        f = FakeFetch({"/manifest.json": (200, m, {}), "/safeer/folder/f.json": (200, {"items": []}, {})})
        c = ca.Checker(fetch=f, developer_mode=True, config={"api_key": "s3cret", "lang": "sl"})
        c.check("http://127.0.0.1:7000/manifest.json")
        sent = [sa.decode_config_header(h.get("X-Safeer-Config", "")) for _, h in f.calls]
        self.assertIn({"lang": "sl"}, sent)
        self.assertFalse(any("api_key" in s for s in sent))
        self.assertTrue(self.has(c, "WARN", "never sent over http"))
        # Without developer mode Safeer does not call extension endpoints over http at all.
        f2 = FakeFetch({"/manifest.json": (200, m, {}), "/safeer/folder/f.json": (200, {"items": []}, {})})
        c2 = ca.Checker(fetch=f2)
        c2.check("http://127.0.0.1:7000/manifest.json")
        self.assertFalse(any("/safeer/" in u for u, _ in f2.calls))

    def test_slovenian_output(self):
        c = self.run_check({"/manifest.json": (404, b"{}", {})}, lang="sl")
        self.assertTrue(c.lines[0].startswith("NAPAKA"))
        self.assertTrue(c.summary().startswith("Napak: 1"))


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Templates(unittest.TestCase):
    def check_running(self, base):
        c = ca.Checker(developer_mode=True, config={"api_key": "k", "quality": "720p"})
        c.check(base + "/manifest.json", None, True)
        self.assertEqual(0, c.errors, "\n".join(c.lines))
        for text in ("safeer extension v1: actions 1, folders 1, settings 2", "catalog movie/example: 1 items",
                     "stream movie/example:bbb: direct 1", "enrich movie/example:bbb", "action add-to-list: ok=true"):
            self.assertTrue(any(text in line for line in c.lines), (text, c.lines))
        # After the action the item is in the folder.
        with urllib.request.urlopen(sa.folder_url(base, "my-list", "all"), timeout=10) as r:
            self.assertEqual(["example:bbb"], [i.id for i in sa.parse_folder(r.read().decode())[0]])
        self.assertEqual([], sa.parse_extension(template.MANIFEST).warnings)

    def test_python_template(self):
        srv = template.serve(0, "127.0.0.1")
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            self.check_running("http://127.0.0.1:%d" % srv.server_address[1])
            old = template.RATE
            template.RATE = 0
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/manifest.json" % srv.server_address[1], timeout=10)
                self.fail("expected 429")
            except urllib.error.HTTPError as e:
                self.assertEqual(429, e.code)
                self.assertTrue(e.headers.get("Retry-After", "").isdigit())
            finally:
                template.RATE = old
        finally:
            srv.shutdown()
            srv.server_close()

    def test_node_template(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        port = _free_port()
        p = subprocess.Popen([node, os.path.join(SDK, "templates", "node", "addon.mjs"), str(port)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                try:
                    socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                    break
                except OSError:
                    time.sleep(0.05)
            self.check_running("http://127.0.0.1:%d" % port)
        finally:
            p.terminate()
            p.wait(timeout=10)


class SharedCopies(unittest.TestCase):
    def test_shared_files_match_list(self):
        """sdk/SKUPNO.sha256: the files that are identical in Android-tv, Safeer-linux and Safeer-windows. A change
        to one of them must be made in all three repositories (and the list updated) in the same round."""
        with open(os.path.join(SDK, "SKUPNO.sha256"), encoding="utf-8") as f:
            rows = [line.split(None, 1) for line in f if line.strip() and not line.startswith("#")]
        self.assertTrue(rows)
        for digest, path in rows:
            path = path.strip().lstrip("*")
            with self.subTest(path):
                with open(os.path.join(ROOT, path), "rb") as g:
                    self.assertEqual(digest, hashlib.sha256(g.read()).hexdigest(), "changed: " + path)


if __name__ == "__main__":
    unittest.main()
