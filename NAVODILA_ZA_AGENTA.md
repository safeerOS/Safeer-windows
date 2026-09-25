# Navodila za Agenta: Pregled, Varnostni Ključi in Postopek Posodabljanja Safeer OS & Control

Ta dokument je namenjen AI agentom in razvijalcem, ki pregledujejo, preverjajo, popravljajo ali nadgrajujejo izvorno kodo v tem repozitoriju.

---

## 1. Osnovni podatki o repozitoriju in veja

- **Lokacija repozitorija**: `/home/janez/Namizje/Neimenovana mapa/novi-repo/safeerOS/Safeer-windows`
- **Aktivna delovna veja**: `resava-poenotenje-wip`
- **KRITIČNO PRAVILO**: **NIKOLI ne preklapljaj na vejo `main` in NIKOLI ne potiskaj (push) neposredno na `main`.** Vse spremembe morajo ostati na `resava-poenotenje-wip`.
- **Git podpisi**: Pri ukazih `git commit` vedno uporabi zastavico `--no-gpg-sign`.

---

## 2. Arhitektura sistema in opravljeno delo

Safeer OS za Windows je hibridni sistem (Go zaganjalnik + Python 3 + PySide6 / Qt WebEngine + HTML5/CSS/JS vmesnik).

### 2.1 Enotni program (Safeer OS z vgrajenim Safeer Controlom)
Safeer OS in Safeer Control **nista dva ločena programa**, temveč enotna aplikacija:
- **[`windows/safeer_windows/os_app.py`](windows/safeer_windows/os_app.py)**:
  - Glavno okno `SafeerOsWindow`. Vsebuje `QStackedWidget` z dvema pogledoma:
    1. Domači zaslon Safeer OS (`assets/os/index.html`).
    2. Vgrajen nadzor naprav Safeer Control (`assets/link/index.html`).
  - Prehod med namizjem in nadzorom naprav je hipen in tekoč v istem oknu in istem procesu.
  - V levem meniju Safeer Controla je gumb **"Safeer OS Domov"**, prav tako klik na ✕ vrne uporabnika na namizje.
  - Zastavice ob zagonu:
    - `python windows/safeer_os_windows.py` (privzeto celozaslonsko domače namizje)
    - `python windows/safeer_os_windows.py --okno` (v oknu)
    - `python windows/safeer_os_windows.py --control` (odpre enotni program neposredno v razdelku Control)
- **[`windows/safeer_control_windows.py`](windows/safeer_control_windows.py)**:
  - Zgolj vstopna točka, ki posreduje argumente `--control --okno` neposredno v osrednji `os_app.py:main()`.

### 2.2 Ločeni navidezni oddaljeni zaslon (`NavidezniZaslon`)
- **[`windows/safeer_windows/navidezni_zaslon.py`](windows/safeer_windows/navidezni_zaslon.py)**:
  - Zagotavlja popolno izolacijo oddaljenega uporabnika (TV daljinec, telefon): fizična miška, tipkovnica in fokus oken na računalniku ostanejo 100 % nedotaknjeni.
  - Vnosi oddaljenega uporabnika **nikoli** ne kličejo `SendInput` ali `mouse_event`.
  - Ločeni koordinati kazalca `(kazalec_x, kazalec_y)`, D-pad navigacija, navidezna glasnost.
  - **Visoka kakovost**: 60 FPS, ločljivost 1920 × 1080 (raven `"najvisja"`), zajem zaslona 1280 × 720 / 1080p pri kakovosti JPEG 85.
  - **Varnost**: Šifriranje toka s TLS 1.2+ z AEAD ciphersuiti (`ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM`), stisk roke zaščiten pred časovnimi napadi s konstantno-časovno primerjavo `hmac.compare_digest`.

### 2.3 Povezava s Safeer Linkom in obdelava ukazov
- **[`windows/safeer_windows/control_backend.py`](windows/safeer_windows/control_backend.py)**:
  - Razred `SafeerControlBackend`: povezava preko WebSocket/TLS z lokalnim Safeer Link Hubom (vrata 8990).
  - Obravnava dohodnih ukazov `control.command` z oddaljenih naprav (status, tipke, drsenje, glasnost, screenshot, odpiranje url-jev, zagon programov, deljenje zaslona).
  - Vrača standardne odzive `control.result` z ujemajočim se `ref_id`.
  - Prikazuje stanje povezave z oznakami `"varno": True`, `"kakovost": "najvisja"`.

### 2.4 Go zaganjalnik (`SafeerOS.exe`)
- **[`windows/launcher_go/main.go`](windows/launcher_go/main.go)**:
  - Samostojna binarna koda, prevedena z Go za Windows (`GOOS=windows GOARCH=amd64`).
  - Vsebuje vdelan arhiv `safeer-os-windows.zip` (`//go:embed safeer-os-windows.zip`).
  - Ob zagonu preveri SHA-256 vsoto in po potrebi razširi datoteke v `%LOCALAPPDATA%\SafeerOS\app`.
  - Samodejno poišče nameščen Python 3 (3.10+) in po potrebi namesti `PySide6`.
  - Vedno zažene `windows/safeer_os_windows.py`. Če se kliče kot `SafeerControl.exe` ali s parametrom `--control`, doda `--control --okno`.

### 2.5 PowerShell namestitveni paket
- **[`install.ps1`](install.ps1)** in **[`install.bat`](install.bat)**:
  - Samodejna namestitev na testnem Windows računalniku (preveri Windows x64, avtomatsko namesti Python 3.12, namesti `PySide6`, `Pillow`, `cryptography`, `qrcode`, skopira datoteke v `%LOCALAPPDATA%\SafeerOS`, doda pravila za vrata 8990 v Windows požarni zid in ustvari bližnjice na Namizju in v meniju Start).
- **[`uninstall.ps1`](uninstall.ps1)** in **[`uninstall.bat`](uninstall.bat)**:
  - Čista odstranitev programa, bližnjic in pravil požarnega zidu.

---

## 3. Kje se nahajajo varnostni ključi, potrdila in žetoni

V sistemu Safeer OS / Link varnost temelji na lokalnem šifriranju z eliptičnimi krivuljami (ECDSA / ECDHE) in Certificate Pinningu:

| Element | Datoteka | Privzeta lokacija na Windows | Opis in namen |
|---|---|---|---|
| **Zasebni ključ naprave** | `kljuc.pem` | `%USERPROFILE%\.config\safeer-control\tls\kljuc.pem` | EC ključ (`prime256v1`), ustvarjen z OpenSSL ob prvi rabi (pravice 0600). Uporablja se za podpisovanje sej v krog in vzpostavitev TLS strežnika za navidezni zaslon. |
| **Javno TLS potrdilo** | `potrdilo.pem` | `%USERPROFILE%\.config\safeer-control\tls\potrdilo.pem` | Samopodpisano X.509 potrdilo (veljavnost 10 let, `/CN=Safeer Control <hostname>`). |
| **Prstni odtis potrdila** | Izračunan SHA-256 | V pomnilniku / izmenjan ob seznanitvi | SHA-256 heksadecimalni odtis DER potrdila. Služi za Certificate Pinning med napravami v domačem omrežju (preprečuje MITM). |
| **Žetoni in nastavitve seznanitve** | `link.json` | `%APPDATA%\SafeerControl\link.json` | Vsebuje `control_token` (skrivni žeton za avtentikacijo na Hubu), `hub_url`, `hub_fp` (prstni odtis huba) in shranjene seznanitve. |
| **Krog zaupanih naprav** | `krog.json` | `%APPDATA%\Safeer\krog.json` | Vsebuje seznam javnih ključev naprav (`devices`), ki so del varnega domačega kroga zaupanja. |

*Opomba za kodo:* Generator ključa in potrdila se nahaja v funkciji `zagotovi_potrdilo(mapa)` v [`core/link_datoteke.py`](core/link_datoteke.py:L292).

---

## 4. Postopek preverjanja kode (Audit)

Pred kakršnim koli spreminjanjem zaženi teste:

```bash
# 1. Preveri delovno vejo
git status
git branch  # mora biti: resava-poenotenje-wip

# 2. Zaženi celotno zbirko testov
PYTHONPATH=windows pytest windows/tests/

# Pričakovani rezultat: Vseh 74 testov mora biti zelenih (74 passed)
```

Preveri tudi skladnost PowerShell skript (če je na voljo `pwsh`):
```bash
pwsh -Command "$tokens = $null; $errors = $null; [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path ./install.ps1).Path, [ref]$tokens, [ref]$errors); if ($errors.Count -eq 0) { Write-Host 'OK' } else { $errors; exit 1 }"
```

---

## 5. Navodila za posodobitve (Popravki hroščev ali izboljšave)

Če najdeš hrošča ali dodaš izboljšavo, **moraš nujno slediti spodnjim 6 korakom v točno tem vrstnem redu**.

### KORAK 1: Uredi izvorno kodo
- Spremembe v Python modulih (`windows/safeer_windows/`, `core/`).
- Spremembe v spletnem vmesniku (`assets/os/`, `assets/link/`, `ui/`).

### KORAK 2: Zaženi in posodobi teste
- Zaženi teste:
  ```bash
  PYTHONPATH=windows pytest windows/tests/
  ```
- Če dodajaš novo funkcionalnost, dodaj nov unit test v `windows/tests/test_os_windows.py`. Vsi testi morajo uspešno prestati!

### KORAK 3: OBVEZNO osveži vdelani ZIP paket
Ker Go zaganjalnik (`SafeerOS.exe`) vsebuje vdelan arhiv `safeer-os-windows.zip`, **nobena sprememba v Pythonu ali assets ne bo prišla v izvršljivo datoteko**, če ne osvežiš arhiva!

Zaženi obnovitveno skripto:
```bash
python3 tests/_zip_obnovi.py
```
Preveri, da skripta izpiše novih vnosov (cca. 132 vnosov) in velikost zipa.

### KORAK 4: Znova prevedi Go zaganjalnik (`SafeerOS.exe`)
Z orodjem Go navzkrižno prevedi binarno kodo za Windows x64:

```bash
cd windows/launcher_go
GOOS=windows GOARCH=amd64 go build -ldflags "-H=windowsgui" -o SafeerOS.exe .
cp SafeerOS.exe ../SafeerOS.exe
cp SafeerOS.exe ../SafeerControl.exe
cd ../..
```

### KORAK 5: Sinhroniziraj namestitvene skripte
Če si spremenil `install.ps1`, `install.bat`, `uninstall.ps1` ali `uninstall.bat`, jih prekopiraj tudi v mapo `windows/`:
```bash
cp install.ps1 windows/install.ps1
cp install.bat windows/install.bat
cp uninstall.ps1 windows/uninstall.ps1
cp uninstall.bat windows/uninstall.bat
```

### KORAK 6: Potrdi spremembe v Git (samo veja `resava-poenotenje-wip`)
```bash
git add .
git commit --no-gpg-sign -m "opis tvojega popravka ali izboljsave"
```

Nikoli ne uporabljaj `git push origin main` ali `git checkout main`.
