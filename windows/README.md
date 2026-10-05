# Safeer Browser za Windows

Windows različica brskalnika Safeer. Temelji na **Qt WebEngine (Chromium)** in uporablja isto zaščito kot Linux različica:

- filtri oglasov in znanih groženj (`core/adblock.py`),
- skripta proti YouTube pavzi »Nadaljujem gledanje?«,
- odstranjevanje oglasnih vložkov na Push Square, Nintendo Life, Pure Xbox ...,
- odstranjevanje sledilnih parametrov (utm, fbclid ...),
- domača stran (`ui/home.*`).

## Funkcije

- Zavihki: srednji klik zapre zavihek, `Ctrl+Shift+T` odpre zaprt zavihek. Na voljo sta tudi zasebno okno (`Ctrl+Shift+N`) in iskanje po strani (`Ctrl+F`).
- Blokiranje oglasnih zahtev in zlonamernih domen z opozorilno stranjo. Pojavna okna brez klika so blokirana.
- Šifriran DNS (DoH, privzeto Cloudflare, brez tihega preklopa na navadni DNS). Na voljo sta Global Privacy Control in blokiranje piškotkov tretjih oseb.
- Priljubljene strani na domači strani (dodajanje z `Ctrl+D`) in uvoz zaznamkov iz Chroma, Edga, Brava, Vivaldija, Opere in Firefoxa.
- Prenosi v mapo Prenosi, bralni način, povečava strani in celozaslonski način.
- Namestitveni program registrira Safeer med brskalniki v sistemu Windows (Nastavitve → Aplikacije → Privzete aplikacije).

## Gradnja

Gradnjo izvaja GitHub Actions (`.github/workflows/windows-package.yml`) na Windows strežniku:

1. unit testi,
2. zagon pravega okna brskalnika iz izvorne kode s samodejnim testom (domača stran, blokiranje, sledilni parametri, grožnje, pojavna okna, prenosi, zasebno okno, DoH, YouTube skripte),
3. PyInstaller `SafeerBrowser.exe` in ponovni test,
4. prenosni ZIP, namestitveni program (Inno Setup) in `SHA256SUMS`,
5. tiha namestitev, preverjanje registracije, zagon in odstranitev.

Lokalno na Windows (Python 3.12 x64):

```powershell
python -m pip install -r windows/requirements.txt
python -m unittest discover -s windows/tests
python windows/build_windows.py smoke-source --online
python windows/build_windows.py pyinstaller
python windows/build_windows.py package   # potrebuje Inno Setup 6
```

Zagon iz izvorne kode: `set PYTHONPATH=windows` in `python -m safeer_windows`.

## Most med vmesnikom in aplikacijo

Vmesnik Safeer OS (`assets/os`) kliče aplikacijo z `window.SafeerOS.klic(metoda, argumenti)`; skripta mostu klic izpiše v konzolo, `SafeerOsPage.javaScriptConsoleMessage` ga izvede in odgovor vrne z `window.__safeerOsOdgovor`.

- **Skripta mostu je registrirana na strani (`page.scripts()`), ne na profilu.** Po koncu procesa strani (straža pomnilnika, sesutje) QtWebEngine skript profila v nov proces ne prenese – stran se naloži brez mostu in noben gumb ne dela (izmerjeno s PySide6 6.11.2 na Windows in Linuxu). Skripte strani se prenesejo. Enako velja za `control_window.py`.
- **Po vsakem nalaganju** `SafeerOsWindow._preveri_most` preveri, ali most obstaja, in ga sicer vstavi ročno; `os.js` nanj počaka (`koMost`).
- **Žeton.** Qt javi izpise konzole vseh okvirjev, tudi tuje strani v vgradnem predvajalniku. Vsak klic zato nosi žeton, ki živi v zaprtju skripte mostu v glavnem okvirju; klic brez njega se ne izvede.
- **Meni polja in odložišče.** Privzeti meni QtWebEngine je v lupini izklopljen; `os.js` pokaže svoj meni (Izreži, Kopiraj, Prilepi, Izberi vse). Odložišče gre skozi most (`kopiraj`, `odlozisceBeri`): Qt, na Windows ob neuspehu Win32; izid se zapiše v dnevnik brez vsebine.
- Preizkus: `windows/tests/test_most_lupine.py` (tudi živi preizkus v QtWebEngine, `windows/tests/_most_zivo.py`).

## Zaganjalnik Safeer OS (`windows/launcher_go`)

`SafeerOS-Windows-<različica>.exe` je majhen program v Go z vdelanim paketom `safeer-os-windows.zip`. Ob zagonu paket po potrebi razpakira v `%LOCALAPPDATA%\SafeerOS\app`, poišče Python in zažene `windows/safeer_os_windows.py`.

- **Stalno mesto.** Zaganjalnik se ob namestitvi sam prepiše v `%LOCALAPPDATA%\SafeerOS\SafeerOS.exe`. Nanj kažejo ikona na namizju, vnos v meniju Start, samodejna posodobitev (`app\.zaganjalnik`) in protokol `magnet:`. Preneseno datoteko sme uporabnik po prvem zagonu pobrisati ali premakniti. Zaganjalnik, ki mu ime določa drug način (`SafeerControl.exe`), se ne kopira.
- **Starejši zaganjalnik ne prepiše novejše namestitve.** Paket se razpakira, kadar je namestitev nepopolna, kadar je njegova različica (`windows/VERSION`) novejša od nameščene ali kadar je različica ista, vsebina pa druga. Starejši paket nameščeno različico pusti in jo samo zažene, stalne kopije zaganjalnika pa ne prepiše. Namerno vrnitev na starejšo različico naredi stikalo `--namesti`.
- **Seznam datotek (`app\.datoteke`).** Po razpakiranju zaganjalnik zapiše, kaj je namestil. Ob naslednji namestitvi odstrani datoteke s seznama, ki jih nov paket nima več, in mape, ki so ostale prazne. Datotek, ki jih ni namestil sam, se ne dotakne.
- **Bližnjici.** Ikona na namizju nastane samo ob prvi namestitvi (pobrisana se ne vrne), vnos v meniju Start vedno, kadar ga ni. Ko zaganjalnik bližnjici ureja (namestitev, posodobitev, zagon z drugega mesta), popravi tisto, katere cilj ne obstaja več. Živo bližnjico preusmeri samo na stalno kopijo, ko je ta pravkar nameščena ali posodobljena.
- **Mapa `posodobitve`.** Prenesene namestitvene datoteke (`SafeerOS*.exe`) zaganjalnik po zagonu odstrani, razen tiste, iz katere teče. Nedokončan prenos (`.del`) in `posodobi.cmd` odstrani, ko sta starejša od ene ure.
- **Datoteke v rabi.** Datoteko, ki je Windows ne pusti prepisati, ker teče (`SafeerMediaWebView.exe`, stalna kopija zaganjalnika), umakne s preimenovanjem (`.staro-…`) in jo pobriše ob naslednjem zagonu.
- **Knjižnice Pythona preveri program sam.** Zaganjalnik program zažene takoj, z okoljem `SAFEER_OS_PREVERI_KNJIZNICE=1`. Program (`safeer_windows/knjiznice.py`) pogleda, ali so knjižnice nameščene – brez uvoza, v nekaj milisekundah – in v dnevnik izpiše `[SafeerOS] knjiznice OK`. Če katera manjka, se konča s kodo 86; zaganjalnik jih namesti (`pip`) in program zažene znova. Prej je zaganjalnik pred vsakim zagonom pognal poseben Python, ki je knjižnice uvozil (okoli pol sekunde čakanja ob vsakem odpiranju programa). Seznam paketov je v `main.go` (`paketiPip`), seznam modulov v `knjiznice.py`; ujemanje preverja `windows/tests/test_knjiznice.py`.

Preizkusi: `go vet ./...` in `go test ./...` v `windows/launcher_go`. Pravila tečejo tudi na Linuxu; preizkusi s pravimi bližnjicami `.lnk` in z datoteko v rabi tečejo samo na Windows (v CI opravilo `zaganjalnik`, Windows Server 2022; ročno na Windows 10 Pro 22H2).

## Omejitve

- Brez podpisa kode Windows SmartScreen ob prvem zagonu opozori na neznanega izdajatelja.
- Qt WebEngine ne vsebuje plačljivih kodekov (H.264/AAC) in Widevine DRM. YouTube deluje (VP9/AV1/Opus), Netflix in podobne storitve pa ne.
- Filtri zmanjšajo oglase in blokirajo znane grožnje, ne zagotavljajo pa popolne zaščite.
