# Safeer Browser for Windows

A fast, private web browser for Windows 10 and Windows 11, built on Qt WebEngine with the
same protection as the Linux edition: ad and threat filtering, encrypted DNS (DoH), tracking
parameter removal and a clean home page. No account, no telemetry.

**Download:** [safeer.si/browser/windows/](https://safeer.si/browser/windows/) —
installer and portable package. The Windows edition is a **beta**: it is tested automatically
on a Windows server, not yet on a wide range of real computers.

The Windows application lives in [`windows/`](windows/); `core/`, `ui/` and `assets/` are
shared with the Linux edition. Building and testing are described in
[`windows/README.md`](windows/README.md) and run on GitHub Actions
(`.github/workflows/windows-package.yml`).

Slovensko: Safeer za Windows je hiter in zaseben brskalnik za Windows 10 in 11 z enako zascito
kot razlicica za Linux: filtri oglasov in groznj, sifriran DNS (DoH), odstranjevanje sledilnih
parametrov in pregledna domaca stran. Brez racuna in brez telemetrije. Prenos je na
[safeer.si/browser/windows/](https://safeer.si/browser/windows/); razlicica za Windows je beta,
preizkusena samodejno na streznikih, ne pa se na razlicnih pravih racunalnikih.

- Issues and questions: [Issues](../../issues)
- Licence: Apache 2.0 (see [LICENSE](LICENSE)); bundled dependencies (including Qt) keep their own licences.
- Safeer is an independent project, not affiliated with Google, Microsoft or online content providers.
