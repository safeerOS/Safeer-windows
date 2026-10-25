#!/usr/bin/env python3
"""Template add-on for Safeer (and every Stremio client) - Python 3.8+ standard library only.

    python3 addon.py 7000        ->  http://<this computer's IP>:7000/manifest.json

What it shows: a Stremio add-on (manifest, catalog, meta, stream) plus the optional Safeer extensions (an action,
enrich, a folder and settings that arrive in the X-Safeer-Config header), and polite rate limiting (HTTP 429 with
Retry-After). Replace CATALOG and the stream lookup with your own content. Serve it over https in production
(behind any reverse proxy or hosting that terminates TLS).

Predloga dodatka: zamenjaj CATALOG in iskanje tokov s svojo vsebino. Licence: Apache-2.0.
"""
from __future__ import annotations

import base64
import json
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MANIFEST = {
    "id": "org.example.template",          # your own reverse-domain id, never change it after publishing
    "version": "1.0.0",                    # semver; bump it with every change users should see
    "name": "Template add-on",
    "description": "Example add-on for the Safeer Add-on Protocol v1",
    "resources": ["catalog", "meta", "stream"],
    "types": ["movie"],
    "idPrefixes": ["example:"],
    "catalogs": [{"type": "movie", "id": "example", "name": "Examples"}],
    # Optional Safeer extensions - other Stremio clients ignore this key.
    "safeer": {
        "protocol": 1,
        "actions": [{"id": "add-to-list", "on": ["movie"], "icon": "plus",
                     "label": {"en": "Add to my list", "sl": "Dodaj na moj seznam"}}],
        "enrich": ["movie"],
        "folders": [{"id": "my-list", "name": {"en": "My list", "sl": "Moj seznam"}}],
        "settings": [
            {"key": "api_key", "type": "secret", "label": {"en": "API key", "sl": "Ključ API"}},
            {"key": "quality", "type": "choice", "options": ["auto", "1080p", "720p"], "default": "auto",
             "label": {"en": "Quality", "sl": "Kakovost"}},
        ],
        "changelog": {"1.0.0": {"en": "First version", "sl": "Prva različica"}},
    },
}

# Your content. Big Buck Bunny (c) Blender Foundation, CC BY 3.0 - a freely licensed sample.
CATALOG = [
    {"id": "example:bbb", "type": "movie", "name": "Big Buck Bunny", "releaseInfo": "2008",
     "poster": "https://upload.wikimedia.org/wikipedia/commons/c/c5/Big_buck_bunny_poster_big.jpg",
     "stream": "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/360/Big_Buck_Bunny_360_10s_1MB.mp4"},
]

MY_LIST = []          # filled by the action; in memory only - use your own storage
_LOCK = threading.Lock()

# Rate limit per client address: RATE requests per WINDOW seconds, then 429 with Retry-After.
RATE, WINDOW = 120, 60
_hits = {}


def config(handler) -> dict:
    """Settings Safeer sends: X-Safeer-Config = base64url(JSON). Secrets arrive only over https."""
    raw = handler.headers.get("X-Safeer-Config") or ""
    try:
        data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")) if raw else {}
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def find(cid):
    return next((m for m in CATALOG if m["id"] == cid), None)


def card(m):
    return {k: m[k] for k in ("id", "type", "name", "poster", "releaseInfo") if k in m}


class Handler(BaseHTTPRequestHandler):
    server_version = "SafeerTemplate/1.0"

    def log_message(self, fmt, *args):   # never log full paths: they can carry ids or user tokens
        sys.stderr.write("%s %s\n" % (self.command, self.path.split("/")[1] if "/" in self.path else ""))

    def send_json(self, status, body, extra_headers=None):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")     # web Stremio clients need it
        self.send_header("Cache-Control", "max-age=300")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def limited(self) -> bool:
        now = time.monotonic()
        with _LOCK:
            if len(_hits) > 10000:   # forget old addresses - a public server sees many
                for k in [k for k, (s, _) in _hits.items() if now - s > WINDOW]:
                    del _hits[k]
            start, count = _hits.get(self.client_address[0], (now, 0))
            if now - start > WINDOW:
                start, count = now, 0
            _hits[self.client_address[0]] = (start, count + 1)
        if count + 1 > RATE:
            self.send_json(429, {"error": "rate limit"}, {"Retry-After": str(int(WINDOW - (now - start)) + 1)})
            return True
        return False

    def do_GET(self):  # noqa: N802 - http.server API
        if self.limited():
            return
        path = urllib.parse.urlsplit(self.path).path
        tail = path.strip("/")
        tail = tail[:-5] if tail.endswith(".json") else tail
        parts = [urllib.parse.unquote(x) for x in tail.split("/")]   # decode each part: ids may contain "/" or ":"
        try:
            self.route(path, parts)
        except Exception:  # noqa: BLE001 - never leak a stack trace to clients
            self.send_json(500, {"error": "server"})

    def route(self, path, p):
        if path == "/manifest.json":
            return self.send_json(200, MANIFEST)
        if len(p) >= 3 and p[0] == "catalog" and p[1] == "movie" and p[2] == "example":
            return self.send_json(200, {"metas": [card(m) for m in CATALOG]})
        if len(p) == 3 and p[0] == "meta":
            m = find(p[2])
            return self.send_json(200, {"meta": card(m)}) if m else self.send_json(404, {"error": "not found"})
        if len(p) == 3 and p[0] == "stream":
            m = find(p[2])
            quality = config(self).get("quality", "auto")       # a setting chosen by the user in Safeer
            streams = [{"name": "Template", "title": "360p sample (%s)" % quality, "url": m["stream"]}] if m else []
            return self.send_json(200, {"streams": streams})
        # ---- Safeer extensions (docs/DODATKI-PROTOKOL.md section 3)
        if len(p) == 5 and p[:3] == ["safeer", "action", "add-to-list"]:
            cid = p[4]
            with _LOCK:
                if cid not in MY_LIST:
                    MY_LIST.append(cid)
            has_key = "api_key" in config(self)   # use the secret; never send it back or log it
            return self.send_json(200, {"ok": True, "refresh": False, "message": {
                "en": "Added" + (" (with API key)" if has_key else ""),
                "sl": "Dodano" + (" (s ključem API)" if has_key else "")}})
        if len(p) == 4 and p[:2] == ["safeer", "enrich"]:
            return self.send_json(200, {"meta": {"description": "A giant rabbit and three bullies.",
                                                 "imdbRating": "7.2", "language": "en"}})
        if p == ["safeer", "folder", "my-list"]:
            return self.send_json(200, {"items": [{"kind": "folder", "path": "all", "name": "All"}]})
        if p == ["safeer", "folder", "my-list", "all"]:
            with _LOCK:
                ids = list(MY_LIST)
            items = [dict(card(find(i)), kind="meta") for i in ids if find(i)]
            return self.send_json(200, {"items": items})
        return self.send_json(404, {"error": "not found"})


def serve(port: int = 7000, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


if __name__ == "__main__":
    srv = serve(int(sys.argv[1]) if len(sys.argv) > 1 else 7000)
    print("Add-on: http://<this computer's IP>:%d/manifest.json  (Ctrl+C to stop)" % srv.server_address[1])
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.server_close()
