# Safeer Add-on SDK

Build add-ons for the Safeer Media Center on Safeer OS for Android (TV, tablet, phone), Safeer for Linux and Safeer for
Windows. Slovenska različica: [README.sl.md](README.sl.md).

An add-on is a **web service that returns JSON**: a [Stremio add-on](https://github.com/Stremio/stremio-addon-sdk/blob/master/docs/protocol.md)
plus, optionally, the `safeer` extension (buttons, folders, settings). Any language and any host works. **No add-on code
runs on the user's device** — Safeer draws everything itself from the data you return.

Safeer ships no add-ons and recommends none: it only lets users add the add-ons they choose. What an add-on offers is
the responsibility of its developer (see [Responsibility](#responsibility)).

- Protocol: [`docs/DODATKI-PROTOKOL.md`](../docs/DODATKI-PROTOKOL.md) (v1) and its JSON Schema
  [`docs/dodatki-protokol-v1.schema.json`](../docs/dodatki-protokol-v1.schema.json)
- SDK version: see [CHANGELOG.md](CHANGELOG.md). Licence: Apache-2.0 (the repository's `LICENSE`).

## Contents

| Path | What |
|---|---|
| `templates/node/` | Template add-on for Node.js 18+ (no dependencies): catalog, meta, stream, an action, enrich, a folder, settings, 429 with `Retry-After`. |
| `templates/python/` | The same template for Python 3.8+ (standard library only). |
| `python/check_addon.py` | Checker: tells you what Safeer will do with your add-on — on any computer with Python 3.8+. |
| `python/safeer_addon.py` | The protocol rules as a small Python module (used by the checker; you can import it in your own tests). |
| `skupni-primeri/protokol-v1.json` | Shared test vectors: the Safeer apps and this SDK must judge every case the same way. |
| `primer/`, `orodja/`, `*.sh` | Android repository only: Kotlin sample add-on and a Kotlin checker compiled from the Android app's own code (Java 17 + `kotlinc`). |

## Quick start (5 steps)

1. **Copy a template.** `sdk/templates/node/addon.mjs` or `sdk/templates/python/addon.py`. Change `id` (your own
   reverse domain, never change it later), `name`, `CATALOG` and the stream lookup.
2. **Run it.** `node addon.mjs 7000` or `python3 addon.py 7000` → `http://<your computer's IP>:7000/manifest.json`.
3. **Check it.**
   ```bash
   python3 sdk/python/check_addon.py http://127.0.0.1:7000/manifest.json --dev --actions
   ```
   Lines are `OK`, `INFO`, `WARN` or `ERROR`; exit code 1 means an error. `--content movie:tt0111161` tries a given
   item (otherwise the first catalog item), `--config key=value` sends settings like Safeer does, `--lang sl` prints in
   Slovenian, a local file (`check_addon.py manifest.json`) checks the manifest offline (e.g. in your CI).
4. **Try it on a device** (see [Installing in Safeer](#installing-in-safeer)). On Android, turn on add-on developer
   mode to use `http://` on your local network.
5. **Publish.** Host it on **https** (any hosting or reverse proxy with TLS), check the public URL again, and share the
   manifest URL or a `stremio://` link. For every change: bump `version` (semver) and add a `changelog` entry — users
   see it once after the update.

## Stremio compatibility

- Every Stremio add-on works in Safeer as is: `manifest`, `catalog` (with `search`, `skip`, `genre`), `meta`
  (with `videos` for series, id `<id>:<season>:<episode>`), `stream` (`url`, `infoHash` + `fileIdx`, `ytId`,
  `behaviorHints.proxyHeaders`), `subtitles`.
- An add-on with the `safeer` key still works in other Stremio clients; they ignore the key.
- With the official Stremio SDK (`stremio-addon-sdk`, checked with 1.6.10) the `safeer` key stays in the manifest. Serve
  the `/safeer/...` endpoints next to its router:

  ```js
  const { addonBuilder, getRouter } = require('stremio-addon-sdk');
  const express = require('express');               // already a dependency of stremio-addon-sdk
  const builder = new addonBuilder(manifest);       // manifest with "safeer": { "protocol": 1, ... }
  // builder.defineCatalogHandler(...), defineStreamHandler(...) as usual
  const app = express();
  app.get('/safeer/action/:action/:type/:id.json', (req, res) => {
    const settings = JSON.parse(Buffer.from(req.get('X-Safeer-Config') || 'e30', 'base64url').toString('utf8'));
    res.json({ ok: true, message: { en: 'Added', sl: 'Dodano' }, refresh: false });
  });
  app.use(getRouter(builder.getInterface()));
  app.listen(7000);
  ```

## Installing in Safeer

Users add add-ons themselves; Safeer checks that the manifest answers before it saves it.

| Device | How |
|---|---|
| Safeer OS for Android (TV, tablet, phone) | Media Center → My sources → Add-ons → enter the URL (manifest, the add-on's root, its `/configure` page or a `stremio://` link). In Safeer's built-in browser the add-on page's "Install" button (`stremio://…`, `web.stremio.com/#/addons?addon=…`, `…/manifest.json`) offers to add it, with a confirmation. **Developer mode:** long-press Add-ons → "Turn on add-on developer mode"; the "Add-on development" card in My sources has "Reload add-ons" and "Add-on log" (no paths, stream links or setting values). |
| Safeer for Linux | Media Center → Add-ons and sources → Paste → Connect. `stremio://` links open Safeer OS and wait for Connect. `http://` works on the home network. |
| Safeer for Windows | Media Center → "Viri medijskega centra" (sources) → type "Stremio dodatek (naslov manifest.json)" → the URL → "Poveži medijski strežnik" (same checks as Linux; these labels are shown in Slovenian). Safeer Player: ⚙ Dodatki. `stremio://` links are not registered on Windows yet — copy the URL. |

What each platform supports today: [protocol §10](../docs/DODATKI-PROTOKOL.md#10-support-per-platform). In short,
the Stremio part works everywhere; the `safeer` extensions work on Android (Linux and Windows ignore them for now and
still use the Stremio part); Linux and Windows accept only add-ons that offer `stream`.

## Rules for add-ons

1. **HTTPS everywhere** — manifest, endpoints, images, streams. `http://` is for local development only; Safeer for
   Linux and Windows refuses it outside the home network and never follows a redirect from https to http.
2. **Keep secrets out of URLs.** Ask for keys with a `safeer.settings` field of `type: "secret"`: Safeer stores the
   value encrypted on the device, sends it only over HTTPS in the `X-Safeer-Config` header and never shows or logs it.
   Never put a key in the query string — Safeer removes (Android) or refuses (Linux, Windows) URLs with `?…`, `#…` or
   `user:password@`. If your add-on must carry a per-user token, put it in the path and tell users to treat that URL
   like a password (encrypted storage of such URLs: Android — being added; Linux, Windows — planned).
3. **Never echo or log secrets** — not in messages, stream names, error pages or your server logs. Log as little as
   you can; paths can contain ids and tokens.
4. **Let Safeer handle debrid and torrents.** Return `infoHash` (+ `fileIdx`, `sources`) instead of asking users for
   their debrid key. Safeer plays torrents through the user's own debrid service (its key stays encrypted on the
   device) or through a Safeer device in the user's home that downloads torrents — never directly from a phone or TV.
5. **Be polite under load.** Answer `429` with `Retry-After` (seconds) when you need a pause — Safeer for Android
   pauses your add-on for as long as you ask (otherwise 15 minutes, doubling up to 2 hours). Use `404` for "nothing here"; `403` is treated like `429` (pause). `5xx` means "not
   responding". Cache headers are welcome.
6. **Stay within the limits** that work everywhere: ≤ 5 MiB per answer (≤ 1 MiB for `/safeer/…`), answer within 6 s.
7. **Mark adult content** with `behaviorHints.adult: true`. Safeer keeps such add-ons private (not on shelves, in
   search, history or on other devices).
8. **No DRM circumvention.** Do not build add-ons that bypass DRM or other technical protection measures; Safeer does
   not support them.
9. **Links are not streams.** Safeer does not show `externalUrl` links (donations, shops, chats) except YouTube
   trailers; an item that only has such links is hidden.
10. **No tracking.** Safeer sends only `Accept-Language`, a `User-Agent` and `X-Safeer-Config`. Do not try to identify
    users or devices beyond the settings they choose to give you.
11. **Stable identity.** Never change `id`; bump `version` (semver) for every change.

## Responsibility

Safeer is a platform, not a content provider. Safeer ships no add-ons, and does not host, review, curate, recommend or
advertise any add-on or provider; it has no control over what add-ons return. Developers are solely responsible for
their add-ons — for the content they list or link to, for having the rights to it, and for complying with the law in
every country where the add-on is offered. Users decide which add-ons they install and use them on their own
responsibility. Being compatible with Safeer, or passing this SDK's checker, does not mean that Safeer endorses an
add-on.

## Versions

- **Protocol** — `safeer.protocol` (integer, now `1`). New versions only add fields; an add-on for an older version
  keeps working.
- **SDK** — [CHANGELOG.md](CHANGELOG.md) (semver). Changes when the guide, templates or checker change.

## Android repository only: Kotlin sample and checker

`sdk/zazeni_primer.sh 7000` runs the Kotlin sample add-on; `sdk/preveri_dodatek.sh <manifest URL> [--vsebina type:id]
[--dejanja]` checks an add-on with the Android app's own code (output in Slovenian). Requires Java 17 and `kotlinc`
(`KOTLINC=/path/to/kotlinc` if it is not on `PATH`).

## For Safeer maintainers

The protocol document, the schema and everything in `sdk/` except the Android-only Kotlin files are **identical in
Android-tv, Safeer-linux and Safeer-windows**. `sdk/SKUPNO.sha256` lists them; change them in all three repositories
in the same round and update the list (`sha256sum -c sdk/SKUPNO.sha256` from the repository root shows what differs).

Tests (from the repository root):

```bash
python3 -m unittest discover -s sdk/python -p "*_test.py"   # every repository: vectors, checker, templates, copies
tests/run_dodatki_sdk_tests.sh                               # Android-tv: also the app's own code against the vectors
```
