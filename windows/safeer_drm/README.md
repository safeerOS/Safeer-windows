# Safeer DRM

Predvajalnik zaščitenih vsebin (Widevine) za Safeer OS na Windows. Temelji na castLabs ECS (Electron for Content Security), ki ima Widevine licenco; Widevine modul (CDM) prenese ob prvem zagonu Googlov Component Updater.

Safeer OS ga vdela v svoje okno (`safeer_windows/webview2_media.py`), zato uporabnik vidi en sam predvajalnik. Dogovor ukazne vrstice in dnevnika je isti kot pri `SafeerMediaWebView.exe`, ki ostane rezerva.

## Dogovor
- Zagon: `safeer-drm.exe --parent=<okno> --url=<https> --profile=<mapa> --state=<events.jsonl> --command=<command.txt> [--storitev=1]`
- Dnevnik (JSON vrstice `{time, type, detail}`): `WINDOW_HANDLE`, `DRM_READY`/`DRM_FAILED`, `SESSION_READY`, `NAVIGATION_OK`/`NAVIGATION_FAILED`/`NAVIGATION_BLOCKED`, `MEDIA_RESPONSE`, `PLAYBACK_STARTED`, `HTTP_ERROR`, `FULLSCREEN_ON`/`FULLSCREEN_OFF`, `POPUP_BLOCKED`, `DOWNLOAD_BLOCKED`, `PERMISSION_BLOCKED`, `PROCESS_FAILED`.
- Ukazi (`command.txt`): `back`, `reload`, `exitfullscreen`.
- `--storitev=1` (Netflix in druge storitve iz `DRM_DOMENE`): stalen profil `SafeerDRMProfil`, brez samodejnega klika, prosto premikanje po https.

## Gradnja (Windows x64)
1. ECS `electron-v44.5.1+wvcus-win32-x64.zip` iz github.com/castlabs/electron-releases (preveri sha256 z digestom izdaje).
2. Razpakiraj v `SafeerDRM/`, kopiraj `main.js` in `package.json` v `SafeerDRM/resources/app/`, `electron.exe` preimenuj v `safeer-drm.exe`, izbriši `electron.exe.sig`.
3. VMP podpis (castLabs EVS, račun Safeer): `python -m castlabs_evs.vmp sign-pkg -H safeer-drm SafeerDRM`, nato `verify-pkg`. Sprememba `main.js` podpisa ne razveljavi (podpisan je izvršljivi del), sprememba izvršljivih datotek ga.
4. Mapa `SafeerDRM/` gre v `windows/` ob `SafeerMediaWebView.exe`.

## Meritve (13. 10. 2026, testni PC)
- Widevine 4.10.3112.0, Vimeo (DRM) v vdelanem oknu: 8,0 s posnetka v 8 s, 1280×720, 192 slik, 0 izpuščenih.
- Celozaslonski video → Safeer OS celozaslonsko; Esc → nazaj v okno; zapiranje ne pusti procesov ali sej.
