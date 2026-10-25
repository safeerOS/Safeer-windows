#!/usr/bin/env python3
"""Safeer add-on checker: shows, before you publish, what Safeer will do with your add-on.

    python3 check_addon.py https://my-addon.example/manifest.json [--content movie:tt0111161] [--actions]
                           [--config key=value ...] [--dev] [--lang sl]
    python3 check_addon.py path/to/manifest.json          (offline: manifest and the safeer extension only)

Lines are OK, INFO, WARN or ERROR; the exit code is 1 when there is an ERROR, 2 for wrong usage.
Python 3.8+ standard library only. Same rules as the Safeer apps (safeer_addon.py, checked against the shared test
vectors that the Android app's own code also passes). Licence: Apache-2.0.

Preveri dodatek, preden ga objavis (izpis v slovenscini: --lang sl).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Callable, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import safeer_addon as sa  # noqa: E402

USER_AGENT = "Safeer-AddonChecker/1.0 (+https://safeer.si)"
RESOURCES = {"catalog", "meta", "stream", "subtitles", "addon_catalog"}
_SEMVER = re.compile(r"\d+\.\d+\.\d+([-+][0-9A-Za-z.+-]*)?")
_INFOHASH = re.compile(r"[0-9a-fA-F]{40}")
# The same words Safeer for Linux and Windows uses to treat an add-on as private (core/media_servers.py).
_ADULT = re.compile(
    r"(?<![a-z0-9])(18\+|xxx|porn\w*|nsfw|hentai|jav|erotic\w*|erotik\w*|adults?[ -]only|"
    r"adult (?:films?|movies?|videos?|content|entertainment|stream\w*))(?![a-z0-9])", re.I)

SL = {
    "OK": "OK", "INFO": "INFO", "WARN": "OPOZORILO", "ERROR": "NAPAKA",
    "ready": "Dodatek je pripravljen za Safeer.", "errors": "Napak: %d", "warnings": "opozoril: %d",
}
EN = {"OK": "OK", "INFO": "INFO", "WARN": "WARN", "ERROR": "ERROR",
      "ready": "The add-on is ready for Safeer.", "errors": "Errors: %d", "warnings": "warnings: %d"}


class Response:
    def __init__(self, status: int, body: bytes, ms: int, headers: Dict[str, str], final_url: str = "",
                 too_big: bool = False):
        self.status, self.body, self.ms, self.headers, self.final_url, self.too_big = \
            status, body, ms, {k.lower(): v for k, v in headers.items()}, final_url, too_big


Fetch = Callable[[str, Dict[str, str], int], Optional[Response]]


def network_fetch(url: str, headers: Dict[str, str], limit: int, timeout: float = 20.0) -> Optional[Response]:
    """GET with the limits Safeer applies: reads at most `limit` + 1 bytes (never the whole body of a huge answer)."""
    start = time.monotonic()
    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        body = e.read(64 * 1024) if e.fp else b""
        return Response(e.code, body, int((time.monotonic() - start) * 1000), dict(e.headers or {}), url)
    except Exception:  # noqa: BLE001 - connection refused, DNS, TLS, timeout: "did not answer"
        return None
    with resp:
        length = resp.headers.get("Content-Length")
        if length and length.isdigit() and int(length) > limit:
            return Response(resp.status, b"", int((time.monotonic() - start) * 1000), dict(resp.headers),
                            resp.geturl(), too_big=True)
        body = resp.read(limit + 1)
        return Response(resp.status, body, int((time.monotonic() - start) * 1000), dict(resp.headers), resp.geturl(),
                        too_big=len(body) > limit)


class Checker:
    def __init__(self, fetch: Fetch = network_fetch, lang: str = "en", developer_mode: bool = False,
                 config: Optional[Dict[str, str]] = None):
        self.fetch = fetch
        self.lang = "sl" if lang.lower().startswith("sl") else "en"
        self.t = SL if self.lang == "sl" else EN
        self.dev = developer_mode
        self.config = dict(config or {})
        self.lines: List[str] = []
        self.errors = 0
        self.warnings = 0
        self.ext: Optional[sa.Extension] = None

    # ---- output
    def _line(self, level: str, msg: str):
        self.lines.append("%-10s %s" % (self.t[level], msg))

    def ok(self, msg): self._line("OK", msg)
    def info(self, msg): self._line("INFO", msg)

    def warn(self, msg):
        self.warnings += 1
        self._line("WARN", msg)

    def error(self, msg):
        self.errors += 1
        self._line("ERROR", msg)

    # ---- one request
    def get(self, url: str, what: str, extension: bool = False) -> Optional[dict]:
        limit = sa.MAX_EXTENSION_BYTES if extension else max(sa.MAX_STREMIO_BYTES.values())
        headers = {"Accept": "application/json", "Accept-Language": self.lang, "User-Agent": USER_AGENT}
        if self.ext is not None and self.ext.settings and not self.ext.newer:
            headers["X-Safeer-Config"] = sa.config_header(sa.settings_for_request(self.ext.settings, url), self.config)
        r = self.fetch(url, headers, limit)
        if r is None:
            self.error("%s: no answer (connection, DNS, TLS or timeout)" % what)
            return None
        if r.final_url and url.startswith("https://") and r.final_url.startswith("http://"):
            self.error("%s: redirected from https to http - Safeer for Linux and Windows does not follow it" % what)
        if r.status == 429:
            wait = r.headers.get("retry-after") or r.headers.get("ratelimit-reset")
            if wait:
                self.warn("%s: HTTP 429, asks to wait %s - Safeer pauses this add-on as asked" % (what, wait))
            else:
                self.error("%s: HTTP 429 without Retry-After - say how long to wait (Retry-After: seconds)" % what)
            return None
        if not 200 <= r.status < 300:
            self.error("%s: HTTP %d" % (what, r.status))
            return None
        if r.too_big:
            self.error("%s: larger than %s - Safeer drops it" % (what, _mib(limit)))
            return None
        if not extension and len(r.body) > sa.MAX_STREMIO_BYTES_ALL:
            self.warn("%s: %s - Safeer for Linux and Windows drops answers over %s" %
                      (what, _mib(len(r.body)), _mib(sa.MAX_STREMIO_BYTES_ALL)))
        if r.ms > 20000:
            self.error("%s: answered after %d ms - Safeer waits at most 20 s" % (what, r.ms))
        elif r.ms > 6000 and what.startswith("catalog"):
            self.warn("%s: %d ms - Safeer for Linux and Windows gives each catalog 6 s" % (what, r.ms))
        elif r.ms > 5000:
            self.warn("%s: slow answer (%d ms)" % (what, r.ms))
        try:
            data = json.loads(r.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self.error("%s: not valid JSON (UTF-8)" % what)
            return None
        if not isinstance(data, dict):
            self.error("%s: not a JSON object" % what)
            return None
        ctype = r.headers.get("content-type", "")
        if ctype and "json" not in ctype.lower():
            self.warn("%s: Content-Type is %s (use application/json)" % (what, ctype.split(";")[0]))
        if what == "manifest" and "access-control-allow-origin" not in r.headers:
            self.info("%s: no Access-Control-Allow-Origin header (Safeer does not need it; web Stremio clients do)"
                      % what)
        return data

    # ---- the manifest
    def check_manifest(self, m: dict, url: str = "") -> None:
        for f in ("id", "name", "version"):
            if not isinstance(m.get(f), str) or not m.get(f).strip():
                self.error("manifest: '%s' missing (string)" % f)
        if isinstance(m.get("version"), str) and not _SEMVER.fullmatch(m["version"].strip()):
            self.warn("manifest: version '%s' is not semver (x.y.z) - Stremio clients require it" % m["version"])
        res = m.get("resources")
        names = []
        if not isinstance(res, list) or not res:
            self.error("manifest: 'resources' missing or empty")
        else:
            for r in res:
                n = r if isinstance(r, str) else (r.get("name") if isinstance(r, dict) else None)
                if not isinstance(n, str) or n not in RESOURCES:
                    self.warn("manifest: unknown resource %r" % (n if n is not None else r,))
                else:
                    names.append(n)
        if not isinstance(m.get("types"), list) or not m.get("types"):
            self.warn("manifest: 'types' is empty")
        if "catalogs" in m and not isinstance(m.get("catalogs"), list):
            self.error("manifest: 'catalogs' must be a list")
        if names and "stream" not in names:
            self.warn("manifest: no 'stream' resource - Safeer for Android shows the catalog; Safeer for Linux and "
                      "Windows refuses an add-on that cannot play anything")
        for k in ("logo", "background", "icon"):
            v = m.get(k)
            if isinstance(v, str) and v.startswith("http://"):
                self.warn("manifest: %s over http - use https" % k)
        hints = m.get("behaviorHints") if isinstance(m.get("behaviorHints"), dict) else {}
        texts = [m.get("name"), m.get("description"), m.get("id")]
        texts += [c.get("name") for c in (m.get("catalogs") or []) if isinstance(c, dict)] \
            if isinstance(m.get("catalogs"), list) else []
        if hints.get("adult") is True:
            self.info("manifest: behaviorHints.adult - private add-on: Safeer keeps its content off shelves, search, "
                      "history and other devices")
        elif any(isinstance(t, str) and _ADULT.search(t) for t in texts):
            self.warn("manifest: looks like adult content but behaviorHints.adult is not true - set it; Safeer for "
                      "Linux and Windows already treats it as private")
        if hints.get("configurationRequired") is True:
            self.warn("manifest: configurationRequired - Safeer installs the URL it is given; users must install the "
                      "URL your configuration page produces")
        if sa.json_depth(m) > sa.MAX_JSON_DEPTH:
            self.warn("manifest: nested deeper than %d levels - Safeer for Android ignores the safeer extension"
                      % sa.MAX_JSON_DEPTH)
        self.ok("manifest: %s %s (%s)" % (m.get("name"), m.get("version"), ", ".join(names) or "-"))

        self.ext = sa.parse_extension(m)
        e = self.ext
        if e is None:
            self.ok("safeer extension: none (a plain Stremio add-on - works in Safeer as is)")
            return
        if e.newer:
            self.warn("safeer.protocol %d is newer than %d - this Safeer ignores the extensions" % (e.protocol, sa.VERSION))
        elif e.protocol == 0:
            self.error("safeer.protocol missing - the extensions are ignored")
        else:
            self.ok("safeer extension v%d: actions %d, folders %d, settings %d, enrich %s" % (
                e.protocol, len(e.actions), len(e.folders), len(e.settings), ",".join(sorted(e.enrich)) or "-"))
        for w in e.warnings:
            self.warn("safeer: %s" % w)
        if url and not e.newer and e.protocol:
            if not sa.may_send(url, self.dev):
                self.warn("safeer: extensions are not called over http (only in developer mode on a local address)")
            elif e.has_secrets and not url.lower().startswith("https://"):
                self.warn("safeer: settings of type secret are never sent over http - test them over https")

    # ---- everything
    def check(self, manifest_url: str, content: Optional[Tuple[str, str]] = None, call_actions: bool = False) -> int:
        for level, msg in sa.install_url_problems(manifest_url):
            (self.error if level == "error" else self.warn)("URL: " + msg)
        u = manifest_url.strip().split("#")[0].split("?")[0]
        base = sa.base_url(u)
        if base.endswith("/configure"):
            base = base[:-len("/configure")]
        url = base + "/manifest.json"
        m = self.get(url, "manifest")
        if m is None:
            return self.errors
        self.check_manifest(m, url)
        e = self.ext
        active = e is not None and not e.newer and e.protocol >= 1 and sa.may_send(url, self.dev)

        if active:
            for f in e.folders:
                body = self.get(sa.folder_url(base, f.id), "folder %s" % f.id, extension=True)
                if body is None:
                    continue
                parsed = sa.parse_folder(body)
                if parsed is None:
                    self.error("folder %s: not a folder answer" % f.id)
                else:
                    self.ok("folder %s: %d items%s" % (f.id, len(parsed[0]), ", has a next page" if parsed[1] else ""))

        names = _resource_names(m)
        sample = content
        catalogs = [c for c in (m.get("catalogs") or []) if isinstance(c, dict)] if isinstance(m.get("catalogs"), list) else []
        for c in catalogs[:4]:
            extra = _required_extra(c)
            if extra is None:
                self.info("catalog %s/%s: needs a value without options (e.g. search) - not called" %
                          (c.get("type"), c.get("id")))
                continue
            what = "catalog %s/%s" % (c.get("type"), c.get("id"))
            body = self.get(sa.stremio_url(base, "catalog", str(c.get("type", "")), str(c.get("id", "")), extra), what)
            if body is None:
                continue
            metas = body.get("metas")
            if not isinstance(metas, list):
                self.error("%s: 'metas' missing" % what)
                continue
            bad = [x for x in metas if not (isinstance(x, dict) and x.get("id") and x.get("type") and x.get("name"))]
            if bad:
                self.warn("%s: %d of %d items without id, type or name - Safeer skips them" % (what, len(bad), len(metas)))
            http = [x for x in metas if isinstance(x, dict) and str(x.get("poster", "")).startswith("http://")]
            if http:
                self.warn("%s: %d posters over http - use https" % (what, len(http)))
            self.ok("%s: %d items" % (what, len(metas)))
            if sample is None:
                first = next((x for x in metas if isinstance(x, dict) and x.get("id") and x.get("type")), None)
                if first:
                    sample = (str(first["type"]), str(first["id"]))

        if sample is None:
            if "stream" in names or "meta" in names:
                self.info("no content to try: add --content type:id (e.g. --content movie:tt0111161)")
            return self.errors
        typ, cid = sample
        self.info("content tried: %s %s" % (typ, cid))
        if "meta" in names and _serves(m, "meta", typ, cid):
            body = self.get(sa.stremio_url(base, "meta", typ, cid), "meta %s/%s" % (typ, cid))
            if body is not None:
                meta = body.get("meta")
                if not isinstance(meta, dict) or not meta.get("id") or not meta.get("name"):
                    self.error("meta %s/%s: 'meta' with id and name missing" % (typ, cid))
                else:
                    videos = meta.get("videos") if isinstance(meta.get("videos"), list) else []
                    self.ok("meta %s/%s: %s%s" % (typ, cid, meta.get("name"),
                                                 (", %d episodes/videos" % len(videos)) if videos else ""))
        if "stream" in names and _serves(m, "stream", typ, cid):
            self.check_streams(base, typ, cid)
        if "subtitles" in names and _serves(m, "subtitles", typ, cid):
            body = self.get(sa.stremio_url(base, "subtitles", typ, cid), "subtitles %s/%s" % (typ, cid))
            if body is not None:
                subs = body.get("subtitles")
                if not isinstance(subs, list):
                    self.error("subtitles: 'subtitles' missing")
                else:
                    good = [s for s in subs if isinstance(s, dict) and str(s.get("url", "")).startswith("https://")
                            and s.get("lang")]
                    if len(good) < len(subs):
                        self.warn("subtitles: %d of %d without https url or lang" % (len(subs) - len(good), len(subs)))
                    self.ok("subtitles %s/%s: %d" % (typ, cid, len(good)))
        if active and typ in e.enrich:
            body = self.get(sa.enrich_url(base, typ, cid), "enrich %s/%s" % (typ, cid), extension=True)
            if body is not None:
                (self.ok("enrich %s/%s" % (typ, cid)) if isinstance(body.get("meta"), dict)
                 else self.error("enrich: 'meta' missing"))
        if active:
            acts = sa.actions_for(e, typ)
            if acts and not call_actions:
                self.info("actions: not called (add --actions; they may change something at your service)")
            for a in (acts if call_actions else []):
                body = self.get(sa.action_url(base, a.id, typ, cid), "action %s" % a.id, extension=True)
                if body is None:
                    continue
                res = sa.parse_action(body)
                if res is None:
                    self.error("action %s: invalid answer" % a.id)
                else:
                    msg = res.message.for_lang(self.lang)[:60] if res.message else ""
                    self.ok("action %s: ok=%s, message=%s" % (a.id, str(res.ok).lower(), msg))
        return self.errors

    def check_streams(self, base: str, typ: str, cid: str) -> None:
        what = "stream %s/%s" % (typ, cid)
        body = self.get(sa.stremio_url(base, "stream", typ, cid), what)
        if body is None:
            return
        streams = body.get("streams")
        if not isinstance(streams, list):
            self.error("%s: 'streams' missing" % what)
            return
        direct = torrent = trailer = links = other = 0
        for s in streams:
            if not isinstance(s, dict):
                other += 1
                continue
            url = s.get("url") if isinstance(s.get("url"), str) else ""
            ih = s.get("infoHash") if isinstance(s.get("infoHash"), str) else ""
            ext_url = s.get("externalUrl") if isinstance(s.get("externalUrl"), str) else ""
            if url.startswith(("https://", "http://")):
                direct += 1
                if url.startswith("http://"):
                    self.warn("%s: stream over http (%s) - some devices refuse it; use https" %
                              (what, str(s.get("name", ""))[:30]))
            elif ih:
                if _INFOHASH.fullmatch(ih):
                    torrent += 1
                else:
                    self.warn("%s: infoHash is not 40 hex characters - Safeer skips it" % what)
            elif s.get("ytId") or "youtube.com/" in ext_url or "youtu.be/" in ext_url:
                trailer += 1
            elif ext_url:
                links += 1
            else:
                other += 1
        if direct or torrent:
            self.ok("%s: direct %d, torrent %d%s" % (what, direct, torrent, (", trailers %d" % trailer) if trailer else ""))
            if torrent:
                self.info("%s: torrents play through the user's own debrid service or a Safeer device that can "
                          "download torrents - never directly from the phone or TV" % what)
        elif links:
            self.warn("%s: only links to web pages (externalUrl) - Safeer does not show them; the content is hidden"
                      % what)
        else:
            self.warn("%s: no stream - Safeer marks the content as not available" % what)

    def summary(self) -> str:
        if self.errors:
            return self.t["errors"] % self.errors + (", " + self.t["warnings"] % self.warnings if self.warnings else "")
        return self.t["ready"] + ((" (" + self.t["warnings"] % self.warnings + ")") if self.warnings else "")


def _mib(n: int) -> str:
    return "%.1f MiB" % (n / 1048576.0) if n % 1048576 else "%d MiB" % (n // 1048576)


def _resource_names(m: dict) -> List[str]:
    out = []
    for r in (m.get("resources") if isinstance(m.get("resources"), list) else []):
        n = r if isinstance(r, str) else (r.get("name") if isinstance(r, dict) else None)
        if isinstance(n, str):
            out.append(n)
    return out


def _serves(m: dict, resource: str, typ: str, cid: str) -> bool:
    """Whether Safeer would ask this add-on: the type and the id prefix (top-level or per resource) match."""
    types, prefixes = m.get("types"), m.get("idPrefixes")
    for r in (m.get("resources") if isinstance(m.get("resources"), list) else []):
        if isinstance(r, dict) and r.get("name") == resource:
            types, prefixes = r.get("types", types), r.get("idPrefixes", prefixes)
    if isinstance(types, list) and types and typ not in types:
        return False
    if isinstance(prefixes, list) and prefixes and not any(isinstance(p, str) and cid.startswith(p) for p in prefixes):
        return False
    return True


def _required_extra(c: dict) -> Optional[str]:
    """The extra path a client must send for this catalog: "" when nothing is required, "name=first option" when a
    required extra has options (as Safeer does), None when a required extra has no options (search)."""
    for x in (c.get("extra") if isinstance(c.get("extra"), list) else []):
        if isinstance(x, dict) and x.get("isRequired") is True:
            opts = x.get("options")
            if isinstance(opts, list) and opts and isinstance(opts[0], str):
                return "%s=%s" % (x.get("name"), sa._enc(opts[0]))
            return None
    return ""


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Check a Safeer / Stremio add-on (Safeer Add-on Protocol v1).")
    p.add_argument("manifest", help="manifest URL (https://..., stremio://...) or a local manifest.json file")
    p.add_argument("--content", "--vsebina", help="content to try: type:id, e.g. movie:tt0111161")
    p.add_argument("--actions", "--dejanja", action="store_true", help="also call the safeer actions")
    p.add_argument("--config", action="append", default=[], metavar="KEY=VALUE",
                   help="setting values Safeer sends in X-Safeer-Config")
    p.add_argument("--dev", action="store_true", help="developer mode: http allowed on a local address")
    p.add_argument("--lang", default=os.environ.get("SAFEER_LANG", "en"), help="en (default) or sl")
    a = p.parse_args(argv)
    content = None
    if a.content:
        if ":" not in a.content:
            p.error("--content must be type:id")
        content = (a.content.split(":", 1)[0], a.content.split(":", 1)[1])
    config = {}
    for kv in a.config:
        if "=" not in kv:
            p.error("--config must be KEY=VALUE")
        k, v = kv.split("=", 1)
        config[k] = v
    c = Checker(lang=a.lang, developer_mode=a.dev, config=config)
    if os.path.isfile(a.manifest):
        try:
            with open(a.manifest, encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError, UnicodeDecodeError) as e:
            c.error("manifest: cannot read (%s)" % e.__class__.__name__)
            m = None
        if isinstance(m, dict):
            c.check_manifest(m)
        elif m is not None:
            c.error("manifest: not a JSON object")
    else:
        c.check(a.manifest, content, a.actions)
    for line in c.lines:
        print(line)
    print(c.summary())
    return 1 if c.errors else 0


if __name__ == "__main__":
    sys.exit(main())
