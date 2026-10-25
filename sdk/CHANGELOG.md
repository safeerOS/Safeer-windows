# Safeer Add-on SDK — changes

Semver. The protocol version (`safeer.protocol`) is separate: see `docs/DODATKI-PROTOKOL.md` §8.

## 1.0.0 — 2026-10-25

- Guide in English and Slovenian (`README.md`, `README.sl.md`): quick start, Stremio compatibility, installing on
  Android, Linux and Windows, rules for add-ons, responsibility, versions.
- Templates without dependencies: Node.js 18+ (`templates/node/`) and Python 3.8+ (`templates/python/`).
- Checker for every computer (`python/check_addon.py`, Python 3.8+) with the protocol rules as a module
  (`python/safeer_addon.py`).
- Shared test vectors (`skupni-primeri/protokol-v1.json`), passed by the Android app's own code and by the Python rules.
- Protocol v1 document: limits per platform, what Safeer sends, rate limiting (429/403), installing, support per platform.
- Android repository: the Kotlin checker uses the app's limits per request (8 MiB Stremio resources, 1 MiB extensions)
  and reads at most the limit.
