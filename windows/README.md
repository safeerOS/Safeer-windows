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

## Omejitve

- Brez podpisa kode Windows SmartScreen ob prvem zagonu opozori na neznanega izdajatelja.
- Qt WebEngine ne vsebuje plačljivih kodekov (H.264/AAC) in Widevine DRM. YouTube deluje (VP9/AV1/Opus), Netflix in podobne storitve pa ne.
- Filtri zmanjšajo oglase in blokirajo znane grožnje, ne zagotavljajo pa popolne zaščite.
