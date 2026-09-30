# Safeer Predvajalnik (samostojna aplikacija)

Ista koda poganja Medijski center v Safeer OS (Windows) in samostojni predvajalnik za Windows in Linux
(`windows/safeer_windows/safeer_predvajalnik.py`, pogon `safeer_mpv_pogon.py`, okno `safeer_mpv_okno.py`).

- **Windows:** `python -m safeer_windows --predvajalnik [datoteka|URL]`; libmpv je prilozen v `vendor/mpv`.
- **Linux:** `predvajalnik/safeer-predvajalnik [datoteka|URL]`; uporablja sistemski `libmpv2` (apt),
  `PySide6` in `python-mpv==1.0.8` (pip). Paketi (.deb/AppImage/Flatpak) sledijo v izdaji.

Nastavitve → **Dodatki (Stremio, Kodi)**: dve jasno oznaceni polji, kamor uporabnik vnese naslove SVOJIH
dodatkov (Stremio: `…/manifest.json` ali `stremio://…`; Kodi: naslov repozitorija ali `.zip`). Safeer ne prilaga
nobenega kataloga ali dodatka. Shranjeno v `%APPDATA%\Safeer\predvajalnik.json` oz. `~/.config/safeer/predvajalnik.json`.
