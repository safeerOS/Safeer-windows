# Safeer OS Windows 1.0.4-test15

Ta izdaja zdruzuje popravke Safeer Media in medsebojnega upravljanja naprav v eni aplikaciji.

## Safeer Media

- Spletne predvajalne vire odpre 64-bitni Microsoft Edge WebView2 znotraj okna Safeer OS.
- Qt WebEngine brez kodekov H.264/AAC ni vec primarni predvajalnik za embed ponudnike.
- Pop-upi, prenosi, dovoljenja, zunanje navigacije in napake potrdil so blokirani.
- Neposredne HLS, DASH, video in zvocne tokove se naprej predvaja LibVLC.
- Podprti so uporabnisko dodani viri VidLink, VidSrc, Videasy in VidRock; noben vir ni dodan samodejno.
- Glavni katalog prikaze eno kartico na serijo; sezone in epizode se odprejo sele v podrobnostih.
- Stari podvojeni epizodni vnosi se ob nadgradnji samodejno zdruzijo, znani plakati pa se popravijo po IMDb/TMDb ID-ju.
- Epizoda vedno uporabi dejansko dodan uporabnikov vir; aplikacija ne vstavi VidLinka, ce ga uporabnik ni dodal.
- Predvajalnik izvede samo en pravi WebView2 klik, zato se film po zagonu ne ustavi zaradi podvojenega ukaza.
- Nedelujoč vir po 18 sekundah prepusti mesto naslednjemu uporabnikovemu viru.
- Gumb `Celozaslonsko` skrije Safeerjevo in Windows orodno vrstico; `Esc` vrne običajni pogled.
- WebView2 in spletni medij sta prisilno odutišana; slika in zvok sta bila potrjena na testnem Windows računalniku.

## Safeer Link in Control

- Windows pravilno prepozna programe in datoteke Android, Linux in starejsih odjemalcev tudi, ce oglasujejo posamezna dejanja `apps.list` ali `files.list`.
- Ce je mobilna naprava zacasno v ozadju, se uporabi njen ze objavljeni Protocol v1 katalog aplikacij.
- Odgovori `items`, `apps`, `programi`, `files`, `datoteke` in `elementi` se poenotijo v isti uporabniski prikaz.
- Windows v Safeer Link objavi dejanski Start meni z obstojnimi ID-ji in brez podvojenih imen.
- Dostop ostaja odvisen od uporabnikove izbire: polni dostop, izbrane mape ali samo zaslon.

## Namestitev in odstranitev

- Paket je samo za 64-bitni Windows 10/11.
- `SafeerMediaWebView.exe` je v celotnem paketu in v vdelanem ZIP-u zaganjalnika.
- Paket vedno vsebuje `uninstall.bat` in `uninstall.ps1`.

Preverjeno: 129 testov in 20 podtestov uspesnih ter dejansko predvajanje slike, zvoka in celozaslonskega videa na Windows 10 x64.
