"""Safeer Add-on Protocol v1 - pure rules (no network, no I/O), Python 3.8+ standard library only.

The same rules as the Android host (Android-tv: src/main/kotlin/si/safeer/tv/os/DodatkiProtokol.kt). Both are checked
against the shared test vectors in sdk/skupni-primeri/protokol-v1.json, so this module and the app cannot judge an
add-on differently. Specification: docs/DODATKI-PROTOKOL.md.

Ista pravila kot gostitelj na Androidu (DodatkiProtokol.kt); oba preverjata skupni primeri
sdk/skupni-primeri/protokol-v1.json.

Licence: Apache-2.0.
"""
from __future__ import annotations

import base64
import json
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

#: Protocol version this module implements (`PROTOKOL-VERZIJA` in docs/DODATKI-PROTOKOL.md).
VERSION = 1

MAX_ACTIONS = 8
MAX_FOLDERS = 4
MAX_SETTINGS = 20
MAX_OPTIONS = 20
MAX_LABEL = 80
MAX_MESSAGE = 500
MAX_ITEMS = 200
#: Safeer extension endpoints (/safeer/...): at most 1 MiB (all platforms).
MAX_EXTENSION_BYTES = 1024 * 1024
#: Stremio resources (manifest, catalog, meta, stream, subtitles) per platform. An add-on that must work everywhere
#: stays within the smallest one.
MAX_STREMIO_BYTES = {"android": 8 * 1024 * 1024, "linux": 5 * 1024 * 1024, "windows": 5 * 1024 * 1024}
MAX_STREMIO_BYTES_ALL = min(MAX_STREMIO_BYTES.values())
#: The Android host reads JSON nested at most this deep (deeper manifests lose the `safeer` extension there).
MAX_JSON_DEPTH = 12

TYPES = frozenset({"movie", "series", "episode", "tv", "channel", "radio", "music"})
ICONS = frozenset({"plus", "check", "heart", "star", "list", "folder", "download", "subtitles", "info", "share",
                   "refresh", "lock"})
SETTING_TYPES = frozenset({"text", "secret", "toggle", "choice"})
_ID = re.compile(r"[a-z0-9-]{1,40}")
_KEY = re.compile(r"[a-z0-9_]{1,40}")
# Java's \s (the host is JVM): ASCII whitespace only, unlike Python's Unicode \s.
_SPACES = re.compile(r"[ \t\n\x0b\f\r]+")


@dataclass(frozen=True)
class Text:
    """User-visible text per language; `for_lang` picks the user's language, then English, then the first one."""
    by_lang: Dict[str, str]

    def for_lang(self, lang: str) -> str:
        key = (lang or "").lower().split("-")[0]
        if key in self.by_lang:
            return self.by_lang[key]
        if "en" in self.by_lang:
            return self.by_lang["en"]
        return next(iter(self.by_lang.values()), "")


@dataclass(frozen=True)
class Action:
    id: str
    on: frozenset
    icon: str
    label: Text
    confirm: bool


@dataclass(frozen=True)
class Folder:
    id: str
    icon: str
    name: Text


@dataclass(frozen=True)
class Setting:
    key: str
    type: str
    required: bool
    options: Tuple[str, ...]
    default: str
    label: Text

    @property
    def secret(self) -> bool:
        return self.type == "secret"


@dataclass
class Extension:
    """The parsed `safeer` key. `newer`: the add-on needs a newer protocol - Safeer ignores all extensions (the Stremio
    part keeps working). `warnings`: what was dropped and why (for the developer)."""
    protocol: int
    newer: bool = False
    actions: List[Action] = field(default_factory=list)
    enrich: frozenset = frozenset()
    folders: List[Folder] = field(default_factory=list)
    settings: List[Setting] = field(default_factory=list)
    changelog: Dict[str, Text] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    @property
    def has_secrets(self) -> bool:
        return any(s.secret for s in self.settings)


# ---------------------------------------------------------------------------------------------------------- helpers

def _is_str(v) -> bool:
    return isinstance(v, str)


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _strings(v) -> List[str]:
    """A JSON list of strings; anything that is not a string is skipped (as on the host)."""
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


def _objects(v) -> List[dict]:
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def clean(s: str, limit: int) -> str:
    """Plain text: no control characters, no repeated spaces, at most `limit` characters.
    (The host counts UTF-16 units; for characters outside the BMP, e.g. emoji, the limits differ by one per character.)"""
    s = "".join(c for c in s if c == " " or unicodedata.category(c) != "Cc")
    return _SPACES.sub(" ", s).strip()[:limit]


def text(obj: dict, key: str, limit: int = MAX_LABEL) -> Optional[Text]:
    """A string, or an object {language: string}; empty or invalid -> None."""
    v = obj.get(key)
    if _is_str(v):
        c = clean(v, limit)
        return Text({"en": c}) if c else None
    if isinstance(v, dict):
        by = {}
        for lang, val in v.items():
            if _is_str(val):
                c = clean(val, limit)
                if c:
                    by[lang.lower()] = c
        return Text(by) if by else None
    return None


def icon(name) -> str:
    n = name.strip().lower() if _is_str(name) else ""
    return n if n in ICONS else "info"


def json_depth(v, depth: int = 1) -> int:
    if isinstance(v, dict):
        return max([json_depth(x, depth + 1) for x in v.values()] or [depth])
    if isinstance(v, list):
        return max([json_depth(x, depth + 1) for x in v] or [depth])
    return depth - 1


def _distinct(items: Iterable, key) -> list:
    seen, out = set(), []
    for it in items:
        k = key(it)
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out


# ------------------------------------------------------------------------------------------------- the extension

def parse_extension(manifest) -> Optional[Extension]:
    """The `safeer` extension of a manifest (dict or JSON text); None when there is none (a plain Stremio add-on).
    Invalid entries are dropped one by one; a broken extension never disables the Stremio part."""
    if _is_str(manifest):
        try:
            manifest = json.loads(manifest)
        except ValueError:
            return None
    if not isinstance(manifest, dict) or not isinstance(manifest.get("safeer"), dict):
        return None
    s = manifest["safeer"]
    warnings: List[str] = []
    p = s.get("protocol")
    protocol = int(p) if _is_number(p) else 0
    if protocol < 1:
        return Extension(0, warnings=["protocol: missing or not an integer >= 1 - extensions ignored"])
    if protocol > VERSION:
        return Extension(protocol, newer=True, warnings=["protocol %d > %d: update Safeer" % (protocol, VERSION)])

    actions = []
    for a in _objects(s.get("actions")):
        aid = a.get("id").strip() if _is_str(a.get("id")) else ""
        on = frozenset(t.strip().lower() for t in _strings(a.get("on"))) & TYPES
        label = text(a, "label")
        if not _ID.fullmatch(aid):
            warnings.append('actions: invalid id "%s"' % aid[:40])
        elif not on:
            warnings.append("actions/%s: 'on' has no known type" % aid)
        elif label is None:
            warnings.append("actions/%s: label missing" % aid)
        else:
            if "icon" in a and (a.get("icon").strip().lower() if _is_str(a.get("icon")) else "") not in ICONS:
                warnings.append("actions/%s: unknown icon -> info" % aid)
            actions.append(Action(aid, on, icon(a.get("icon")), label, a.get("confirm") is True))
    actions = _distinct(actions, lambda x: x.id)
    if len(actions) > MAX_ACTIONS:
        warnings.append("actions: more than %d - the rest is dropped" % MAX_ACTIONS)

    enrich = frozenset(t.strip().lower() for t in _strings(s.get("enrich"))) & TYPES

    folders = []
    for f in _objects(s.get("folders")):
        fid = f.get("id").strip() if _is_str(f.get("id")) else ""
        name = text(f, "name")
        if not _ID.fullmatch(fid):
            warnings.append('folders: invalid id "%s"' % fid[:40])
        elif name is None:
            warnings.append("folders/%s: name missing" % fid)
        else:
            folders.append(Folder(fid, icon(f.get("icon") if _is_str(f.get("icon")) else "folder"), name))
    folders = _distinct(folders, lambda x: x.id)
    if len(folders) > MAX_FOLDERS:
        warnings.append("folders: more than %d - the rest is dropped" % MAX_FOLDERS)

    settings = []
    for n in _objects(s.get("settings")):
        key = n.get("key").strip() if _is_str(n.get("key")) else ""
        typ = n.get("type").strip().lower() if _is_str(n.get("type")) else ""
        label = text(n, "label")
        options = tuple(_distinct([o for o in (clean(x, MAX_LABEL) for x in _strings(n.get("options"))) if o],
                                  lambda x: x)[:MAX_OPTIONS])
        d = n.get("default")
        if _is_str(d):
            default = clean(d, MAX_MESSAGE)
        elif isinstance(d, bool):
            default = "true" if d else "false"
        elif _is_number(d):
            default = json.dumps(d)
        else:
            default = ""
        if not _KEY.fullmatch(key):
            warnings.append('settings: invalid key "%s"' % key[:40])
        elif typ not in SETTING_TYPES:
            warnings.append('settings/%s: unknown type "%s"' % (key, typ[:20]))
        elif label is None:
            warnings.append("settings/%s: label missing" % key)
        elif typ == "choice" and not options:
            warnings.append("settings/%s: choice without options" % key)
        elif typ == "secret" and default:
            # A default secret would be in the manifest for everyone - not accepted.
            warnings.append("settings/%s: a secret must not have a default" % key)
        else:
            if typ == "choice" and default not in options:
                default = options[0]
            settings.append(Setting(key, typ, n.get("required") is True, options, default, label))
    settings = _distinct(settings, lambda x: x.key)
    if len(settings) > MAX_SETTINGS:
        warnings.append("settings: more than %d - the rest is dropped" % MAX_SETTINGS)

    changelog = {}
    c = s.get("changelog")
    if isinstance(c, dict):
        for ver in c:
            t = text(c, ver, MAX_MESSAGE)
            if t is not None:
                changelog[ver.strip()[:20]] = t

    return Extension(protocol, False, actions[:MAX_ACTIONS], enrich, folders[:MAX_FOLDERS], settings[:MAX_SETTINGS],
                     changelog, warnings)


def actions_for(ext: Extension, typ: str) -> List[Action]:
    return [a for a in ext.actions if typ.lower() in a.on]


# ------------------------------------------------------------------------------------- endpoint URLs (Java encoding)

def _enc(s: str) -> str:
    """java.net.URLEncoder (UTF-8) with %20 for a space - exactly what the host sends."""
    out = []
    for b in s.encode("utf-8"):
        c = chr(b)
        out.append(c if (c.isascii() and c.isalnum()) or c in ".-*_" else "%%%02X" % b)
    return "".join(out)


def base_url(manifest_url: str) -> str:
    """Add-on base URL as Safeer derives it: stremio:// -> https://, without /manifest.json and the trailing /."""
    n = manifest_url.strip()
    if n.startswith("stremio://"):
        n = "https://" + n[len("stremio://"):]
    if n.endswith("/manifest.json"):
        n = n[:-len("/manifest.json")]
    return n.rstrip("/")


def action_url(base: str, action: str, typ: str, cid: str) -> str:
    return "%s/safeer/action/%s/%s/%s.json" % (base.rstrip("/"), _enc(action), _enc(typ), _enc(cid))


def enrich_url(base: str, typ: str, cid: str) -> str:
    return "%s/safeer/enrich/%s/%s.json" % (base.rstrip("/"), _enc(typ), _enc(cid))


def folder_url(base: str, folder: str, path: str = "") -> str:
    parts = [p for p in path.split("/") if p.strip() and p not in (".", "..")]
    tail = ("/" + "/".join(_enc(p) for p in parts)) if parts else ""
    return "%s/safeer/folder/%s%s.json" % (base.rstrip("/"), _enc(folder), tail)


def stremio_url(base: str, resource: str, typ: str, cid: str, extra: str = "") -> str:
    """/catalog|meta|stream|subtitles/{type}/{id}[/{extra}].json (extra e.g. "search=dune", already in key=value form)."""
    tail = "/" + extra if extra else ""
    return "%s/%s/%s/%s%s.json" % (base.rstrip("/"), resource, _enc(typ), _enc(cid), tail)


# ------------------------------------------------------------------------------------------ settings sent to add-on

def _escape(v: str) -> str:
    """JSON string escaping exactly as the host writes it (JsonLahki.ubezi): \\" \\\\ \\n \\r \\t, other control
    characters as \\u00xx, everything else unchanged."""
    out = []
    for c in v:
        if c == '"':
            out.append('\\"')
        elif c == "\\":
            out.append("\\\\")
        elif c == "\n":
            out.append("\\n")
        elif c == "\r":
            out.append("\\r")
        elif c == "\t":
            out.append("\\t")
        elif ord(c) < 0x20:
            out.append("\\u%04x" % ord(c))
        else:
            out.append(c)
    return "".join(out)


def config_header(settings: List[Setting], values: Dict[str, str]) -> str:
    """Value of `X-Safeer-Config`: base64url (no padding) of a JSON object with the setting values - never in the URL.
    Keys the manifest does not describe are dropped (the add-on gets only what it asked for)."""
    parts = []
    for s in settings:
        v = values.get(s.key, s.default)
        if s.type == "toggle":
            parts.append('"%s":%s' % (_escape(s.key), "true" if v == "true" else "false"))
        elif v:
            parts.append('"%s":"%s"' % (_escape(s.key), _escape(v)))
    raw = ("{" + ",".join(parts) + "}").encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_config_header(value: str) -> dict:
    """For add-on developers: X-Safeer-Config -> dict ({} when missing or invalid)."""
    if not value:
        return {}
    try:
        d = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return d if isinstance(d, dict) else {}


def settings_for_request(settings: List[Setting], url: str) -> List[Setting]:
    """Over https all settings; otherwise only the non-secret ones (a secret never travels unencrypted, not even in
    developer mode)."""
    return list(settings) if url.strip().lower().startswith("https://") else [s for s in settings if not s.secret]


def is_local(host: str) -> bool:
    """Local address (developer mode): localhost, ::1, *.local, 127.x, 10.x, 192.168.x, 172.16-31.x."""
    g = host.strip().lower()
    if g.startswith("[") and g.endswith("]"):
        g = g[1:-1]
    if g in ("localhost", "::1") or g.endswith(".local"):
        return True
    parts = g.split(".")
    if len(parts) != 4 or not all(re.fullmatch(r"[0-9]{1,10}", p) for p in parts):
        return False
    d = [int(p) for p in parts]
    if any(x > 2147483647 for x in d):  # the host parses each part as a 32-bit Int
        return False
    return d[0] == 127 or d[0] == 10 or (d[0] == 192 and d[1] == 168) or (d[0] == 172 and 16 <= d[1] <= 31)


def may_send(url: str, developer_mode: bool) -> bool:
    """https always; http only in developer mode to a local address."""
    try:
        u = urllib.parse.urlsplit(url.strip())
        host = u.hostname
    except ValueError:
        return False
    scheme = (u.scheme or "").lower()
    if not scheme or not host:
        return False
    return scheme == "https" or (scheme == "http" and developer_mode and is_local(host))


# --------------------------------------------------------------------------------------------- extension responses

@dataclass(frozen=True)
class ActionResult:
    ok: bool
    message: Optional[Text]
    refresh: bool


def parse_action(body) -> Optional[ActionResult]:
    if _is_str(body):
        if len(body) > MAX_EXTENSION_BYTES:
            return None
        try:
            body = json.loads(body)
        except ValueError:
            return None
    if not isinstance(body, dict):
        return None
    return ActionResult(body.get("ok") is not False, text(body, "message", MAX_MESSAGE), body.get("refresh") is True)


@dataclass(frozen=True)
class Item:
    kind: str
    path: str
    type: str
    id: str
    name: str
    poster: str


def parse_folder(body) -> Optional[Tuple[List[Item], str]]:
    """Folder response -> (items, next). Posters only over https; at most MAX_ITEMS items."""
    if _is_str(body):
        if len(body) > MAX_EXTENSION_BYTES:
            return None
        try:
            body = json.loads(body)
        except ValueError:
            return None
    if not isinstance(body, dict):
        return None
    items = []
    for e in _objects(body.get("items")):
        name = clean(e.get("name"), MAX_LABEL) if _is_str(e.get("name")) else ""
        poster = e.get("poster").strip() if _is_str(e.get("poster")) else ""
        poster = poster if poster.startswith("https://") else ""
        kind = e.get("kind").strip().lower() if _is_str(e.get("kind")) else ""
        if kind == "folder":
            path = e.get("path").strip() if _is_str(e.get("path")) else ""
            if path and name:
                items.append(Item("folder", path[:512], "", "", name, poster))
        elif kind == "meta":
            typ = e.get("type").strip().lower() if _is_str(e.get("type")) else ""
            cid = e.get("id").strip() if _is_str(e.get("id")) else ""
            if typ and cid and name:
                items.append(Item("meta", "", typ, cid[:256], name, poster))
    nxt = body.get("next").strip()[:512] if _is_str(body.get("next")) else ""
    return items[:MAX_ITEMS], nxt


def changelog_to_show(ext: Extension, previous: Optional[str], now: str) -> Optional[Text]:
    """Shown once after an update (manifest version changed); not on the first install."""
    if not previous or not previous.strip() or previous == now:
        return None
    return ext.changelog.get(now)


# ------------------------------------------------------------------------------------- add-on URL (installation)

def install_url_problems(url: str) -> List[Tuple[str, str]]:
    """Problems of a manifest URL that users will paste or open (stremio:// install links included), as
    [(severity, message)] with severity "error" (Safeer refuses or changes it) or "warn". Rules of the hosts:
    Android removes the query and fragment; Linux and Windows refuse a URL with a query, fragment or user:password,
    and accept http only on the home network."""
    out: List[Tuple[str, str]] = []
    u = url.strip()
    if u.startswith("stremio://"):
        u = "https://" + u[len("stremio://"):]
    try:
        d = urllib.parse.urlsplit(u)
        host = d.hostname or ""
    except ValueError:
        return [("error", "not a valid URL")]
    if d.scheme not in ("http", "https") or not host:
        return [("error", "only http(s):// or stremio:// URLs with a host")]
    if d.username or d.password:
        out.append(("error", "user:password in the URL - Safeer for Linux and Windows refuses it"))
    if d.query:
        out.append(("error", "query string (?...) - Safeer removes it (Android) or refuses the URL (Linux, Windows); "
                              "put configuration in the path or use safeer.settings"))
    if d.fragment:
        out.append(("error", "fragment (#...) - Safeer removes it (Android) or refuses the URL (Linux, Windows)"))
    if d.scheme == "http":
        if is_local(host):
            out.append(("warn", "http on a local address - fine for development only (developer mode / home network)"))
        else:
            out.append(("error", "http over the internet - Safeer for Linux and Windows accepts only https; "
                                  "extensions never work over it"))
    if not d.path.endswith("/manifest.json"):
        out.append(("warn", "the URL does not end with /manifest.json - Safeer adds it (and drops /configure)"))
    return out
