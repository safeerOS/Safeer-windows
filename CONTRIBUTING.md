# Contributing to Safeer

Thank you for taking the time. This project is Apache-2.0 and patches are welcome.

## The one rule that is not negotiable

**No per-site recipes.** Safeer must not contain code written for one named website: no
`if (hostname === "example.com")`, no `site_example.js`, no selector list copied from one
page's markup. Everything works by what a page *is* — its markup, its stream format, its
request pattern — not by who publishes it.

This is not style. It is the promise the product makes: your sites work, not just ours. A
build guard enforces it and will fail your build. If a site is broken, the right patch is a
generic rule that fixes that whole class of sites, and a test that proves it.

Bookmarks, start-page tiles and voice shortcuts are not adaptations — those are just entries
in a list, and they are fine.

## Before you open a pull request

- Run the tests. Every repository has a test command in its README; a red suite is not ready.
- Keep the change focused. One problem per pull request reviews far faster than five.
- Explain the *why* in the commit message. What was broken, how you know it is fixed, and on
  which device or distribution you saw it work.
- New behaviour needs a test. A bug fix without a failing-then-passing test tends to come back.

## Reporting a bug

Open an issue with: what you did, what you expected, what happened, the version (Settings, or
`safeer --version` on Linux), and the device or distribution. For a rendering problem, the URL
matters — if the page is private, a screenshot and the page's framework are usually enough.

**Security issues do not go in the issue tracker.** See [SECURITY.md](SECURITY.md).

## Claims must be true

If your change alters what the browser does, update the README in the same pull request. We do
not ship documentation that promises something the code does not do, and we do not name a
version number in prose where a link to the release will stay correct on its own.

## Code of conduct

Participation is covered by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
