# Safeer Add-on Protocol — v1

<!-- PROTOKOL-VERZIJA: 1 -->

One protocol for Safeer add-ons on every device: Safeer OS for TV, tablet and phone (Android-tv), Safeer for Linux
(Safeer-linux) and Safeer for Windows (Safeer-windows). An add-on is written once and works on all of them. Each
repository carries an identical copy of this document and of the shared SDK in `sdk/` (guide, templates, checker,
shared test vectors — see `sdk/README.md`); the Android repository also has a Kotlin sample and checker built from the
app's own code.

Licence of this document and of the SDKs: Apache-2.0.

## 1. What an add-on is

An add-on is an **HTTP(S) service that returns JSON**. It is a [Stremio add-on](https://github.com/Stremio/stremio-addon-sdk/blob/master/docs/protocol.md)
(`manifest.json`, `catalog`, `meta`, `stream`, `subtitles`) with optional Safeer extensions under the `safeer` key of the
manifest. Every existing Stremio add-on therefore works in Safeer unchanged, and an add-on with Safeer extensions still
works in other Stremio clients (they ignore unknown keys).

**No add-on code ever runs on the user's device.** Safeer draws everything itself — buttons, folders, settings — from the
data the add-on returns. An add-on cannot inject scripts, HTML, styles or native code.

Safeer ships no add-on and recommends none. Users add the add-ons they choose (§9); add-on developers are responsible
for their add-ons (`sdk/README.md`, "Responsibility").

## 2. Manifest extension

```json
{
  "id": "org.example.lists",
  "version": "1.2.0",
  "name": "Example Lists",
  "resources": ["catalog", "meta", "stream"],
  "types": ["movie", "series"],
  "catalogs": [],
  "safeer": {
    "protocol": 1,
    "actions": [
      { "id": "add-to-list", "on": ["movie", "series"], "icon": "plus",
        "label": { "en": "Add to my list", "sl": "Dodaj na moj seznam" }, "confirm": false }
    ],
    "enrich": ["movie", "series"],
    "folders": [
      { "id": "my-account", "icon": "folder", "name": { "en": "My account", "sl": "Moj račun" } }
    ],
    "settings": [
      { "key": "api_key", "type": "secret", "required": true, "label": { "en": "API key", "sl": "Ključ API" } },
      { "key": "quality", "type": "choice", "options": ["auto", "1080p", "720p"], "default": "auto",
        "label": { "en": "Quality", "sl": "Kakovost" } },
      { "key": "only_cached", "type": "toggle", "default": false, "label": { "en": "Only instant", "sl": "Samo takoj" } }
    ],
    "changelog": { "1.2.0": { "en": "Folders", "sl": "Mape" } }
  }
}
```

| Field | Meaning |
|---|---|
| `protocol` | Integer, required. The lowest protocol version the add-on's extensions need. A host with an older protocol ignores **all** `safeer` extensions (the Stremio part keeps working) and tells the user to update Safeer. |
| `actions` | Up to 8 buttons on a content page. `id`: `[a-z0-9-]{1,40}`. `on`: content types (`movie`, `series`, `episode`, `tv`, `channel`, `radio`, `music`). `icon`: one of the fixed icon names (§6). `label`: text per language. `confirm`: ask the user before running. |
| `enrich` | Content types for which the page is shown at once and completed later by `enrich` (§3.2). |
| `folders` | Up to 4 folders the user can browse in Media Center (e.g. the user's own account at a service). |
| `settings` | Up to 20 fields Safeer draws in its own settings screen. `key`: `[a-z0-9_]{1,40}`. `type`: `text`, `secret`, `toggle`, `choice` (up to 20 `options`). `secret` values are stored encrypted on the device and are never shown again or logged; a `secret` must not have a `default`. |
| `changelog` | Shown to the user once after the add-on updates (`version` of the manifest changed). |

Unknown fields inside `safeer` are ignored (forward compatibility). Invalid entries are dropped one by one; a broken
extension never disables the Stremio part of the add-on. JSON Schema: `docs/dodatki-protokol-v1.schema.json`.

### Text

Every user-visible text is an object `{ "<language>": "<plain text>" }` (`en`, `sl`, `de`, `fr`, `it`, `es`, …) or a
plain string. Safeer picks the user's language, then `en`, then the first one. Text is plain (no HTML, no markup),
trimmed, at most 80 characters for labels and names, 500 for messages and change logs. Control characters (tab, new
line) are removed.

## 3. Endpoints

All endpoints are `GET` relative to the add-on base URL (the manifest URL without `/manifest.json`), as in Stremio.
`{type}` and `{id}` are URL-encoded.

### 3.1 Action — `/safeer/action/{actionId}/{type}/{id}.json`

```json
{ "ok": true, "message": { "en": "Added", "sl": "Dodano" }, "refresh": false }
```
`message` is shown as a short notice. `refresh: true` asks Safeer to reload the page (catalog, meta).

### 3.2 Enrich — `/safeer/enrich/{type}/{id}.json`

```json
{ "meta": { "imdbRating": "7.9", "language": "en", "cast": ["…"], "description": "…" } }
```
Same fields as a Stremio `meta` object. Safeer merges only fields it does not already have; it never replaces the
title, the id or the streams.

### 3.3 Folder — `/safeer/folder/{folderId}.json` and `/safeer/folder/{folderId}/{path}.json`

```json
{ "items": [
  { "kind": "folder", "path": "movies", "name": "Movies" },
  { "kind": "meta", "type": "movie", "id": "tt0111161", "name": "The Shawshank Redemption", "poster": "https://…" }
] }
```
`kind`: `folder` (opens `{path}`), `meta` (a normal content card; playback through `stream` as usual). At most 200 items
per response; `next` (a path) for more. Posters only over `https://`. Each part of `{path}` is encoded separately;
`.` and `..` parts are dropped.

## 4. What Safeer sends

Setting values are sent on every request in the header `X-Safeer-Config: <base64url(JSON object)>` (no padding), never
in the URL, so they do not end up in logs, history or the player. Only keys the manifest describes are sent. A request
with `secret` values is only sent over HTTPS — over http (developer mode, §7) the secrets are left out. Safeer also
sends `Accept-Language` and a `User-Agent` naming Safeer. Nothing else about the user or the device is sent.

## 5. Limits and failures

| | Safeer OS (Android) | Safeer for Linux and Windows |
|---|---|---|
| Stremio responses (manifest, catalog, meta, stream, subtitles) | at most 8 MiB | at most 5 MiB |
| Extension responses (`/safeer/…`) | at most 1 MiB | — (§10) |
| Time | connect 10 s, read 20 s | Linux: each catalog 6 s (catalogs of one add-on load in parallel) |
| Add-on URL | `http` or `https`; query and fragment are removed | `https` (http only on the home network); a URL with a query, fragment or user:password is refused |

An add-on that should work everywhere stays within the smaller limit: **≤ 5 MiB, answer within 6 s, https**.

- `https://` required for images and links too, except a local address in developer mode.
- HTTP status: `404` (and other 4xx except those below) means "I have nothing for this" — normal. `5xx`, timeouts and
  connection errors mean the add-on is not responding: it is marked as such (with time and HTTP code) and retried
  later. Content that cannot play (dead channel, pay-wall only) is hidden from the user, never shown as broken.
- Rate: Safeer limits its own requests per add-on. On **`429` or `403`** it pauses that add-on — for as long as
  `Retry-After` (seconds or HTTP date) or `RateLimit-Reset` says, otherwise 15 minutes, doubling up to 2 hours (Android;
  the pause is shared between the user's devices). Do not answer `403` for "not found"; use `404`. Playback started
  by the user is not delayed by a pause.

## 6. Icons

`plus`, `check`, `heart`, `star`, `list`, `folder`, `download`, `subtitles`, `info`, `share`, `refresh`, `lock`.
An unknown icon becomes `info`.

## 7. Developer mode (each SDK)

Install from a local address (`http://192.168.x.x:port/manifest.json`, `http://localhost:…`), a "Reload add-ons"
button that forgets cached manifests and locks, and a log of add-on responses without stream URLs or settings values.
On Linux and Windows a local `http` address on the home network is accepted without a separate mode.

## 8. Versions

- **v1** (this document): actions, enrich, folders, settings, changelog.

A new protocol version only adds fields; a host never breaks an add-on written for an older version. The SDK has its
own version (`sdk/CHANGELOG.md`, semver); it changes when the guide, templates or checker change, the protocol version
only when this document gains fields.

## 9. Installing an add-on

Users add an add-on themselves; Safeer always checks that the manifest answers with valid JSON before it saves it.

- **Safeer OS (Android: TV, tablet, phone):** Media Center → My sources → Add-ons → enter the manifest URL (also the
  add-on's root or `/configure` page, or a `stremio://` link). In Safeer's built-in browser, the "Install" button of an
  add-on page (`stremio://…`, `web.stremio.com/#/addons?addon=…` or a direct `…/manifest.json` link) offers to add it,
  always with a confirmation.
- **Safeer for Linux:** Media Center → Add-ons and sources → Paste → Connect. `stremio://` links open Safeer OS (system
  handler `x-scheme-handler/stremio`) and wait for Connect.
- **Safeer for Windows:** Media Center → "Viri medijskega centra" (sources) → type "Stremio dodatek (naslov
  manifest.json)" → the URL → "Poveži medijski strežnik" (the same checks as on Linux). Safeer Player: ⚙ Dodatki.
  `stremio://` links are not registered on Windows yet — copy the URL. (These Windows labels are shown in Slovenian.)

## 10. Support per platform

| | Android | Linux | Windows |
|---|---|---|---|
| Stremio part (catalog, meta, stream, subtitles) | yes | yes | yes |
| `safeer` extensions v1 | yes | not yet — ignored, the Stremio part works | not yet — ignored, the Stremio part works |
| Add-on without a `stream` resource (catalog only) | yes | refused | refused |
| Streams with `infoHash` (torrents) | through the user's debrid service or a Safeer device that downloads torrents | yes | Safeer OS: yes; Safeer Player: no |
| Private add-ons (`behaviorHints.adult: true`) | kept off shelves, search, history and other devices | the same, also recognised by name | the same as Linux |

The table describes the hosts as of this version of the document; each host repository updates its copy when its
support changes.
