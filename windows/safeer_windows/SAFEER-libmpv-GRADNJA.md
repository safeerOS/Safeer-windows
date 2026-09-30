# Safeer namenska libmpv gradnja — načrt (osnova: milutv-libmpv, Meson + GitHub Actions)

Cilj: ena LGPL libmpv gradnja, katere obseg določajo potrebe izdelka in POTRJENI testi.
Pravilo: gradnja NI uspešna, ker ustvari DLL. Izdajo USTAVIJO neuspešni funkcionalni testi
(AV1, DASH, MPEG-4 P2, zajem slike, vsebniki). Šele nato ločeno: vgradnja, HDR, delovanje
na računalniku brez razvojnih orodij.

## Obvezni BOM (Matejeva specifikacija 2026-09-30)
| Področje | Zahteva |
|---|---|
| Video | H.264, HEVC, VP9, AV1 (prek dav1d), MPEG-4 Part 2 |
| Vsebniki | MP4/MOV, Matroska/WebM, MPEG-TS, AVI |
| Splet | HLS, DASH (z vsemi odvisnostmi), HTTPS, HTTP-glave + piškotki |
| Zvok/podnapisi | ohraniti obstoječi nabor + preveriti dejansko delovanje |
| Zajem slike | PNG ali JPEG encoder za izbrano pot zajema |
| Izris | delujoča Windows pot BREZ obveznega vulkan-1.dll (ANGLE/D3D11) |
| Distribucija | pripete različice, licence, BOM, preverjene DLL odvisnosti |

## Popravek osnove (milutv @ a36a682) — natančno
1. `versions.json` → dodaj v `wrapdb`: `dav1d`, `libxml2` (pripeti različici); ali git-wrap.
2. `subprojects/dav1d.wrap`, `subprojects/libxml2.wrap` (iz meson wrapdb).
3. `ffmpeg-components.json`:
   - decoder: dodaj `libdav1d`; preveri/dodaj `h263` (MPEG-4 P2 deli kodo z njim); obdrži ostale.
   - demuxer: eksplicitno dodaj `matroska`, `webm`, `dash` (+ obstoječi mov/mpegts/avi/hls).
   - NOVA skupina `encoder`: `["png","mjpeg"]` (za zajem slike).
   - `disabledGroups`: odstrani `encoders` (ker zdaj dovolimo png/mjpeg prek allow-liste).
4. `scripts/build-mpv.ps1`:
   - v `$groups` dodaj `encoder = 'encoders'` (da se uveljavi encoder allow-lista).
   - dodaj ffmpeg opciji: `-Dffmpeg:libdav1d=enabled`, `-Dffmpeg:libxml2=enabled`.
5. Nespremenjeno (namerno): `vulkan=disabled`, ANGLE/D3D11 pot, `gpl/version3/nonfree=disabled`.
   dav1d = BSD-2-Clause, libxml2 = MIT → licenca ostane LGPL-združljiva.

## Poligon
GitHub Actions (Windows runner) — `.github/workflows/build.yml`, `workflow_dispatch`.
Zasebne kode Safeer NE potrebuje (gradi le knjižnico). Fork + zagon zahtevata Matejevo "da" (potisk).

## Prag funkcionalnih testov (izdajo ustavi, če kateri pade)
Za vsako preveri DEJANSKO dekodiranje/izris (dwidth>0), ne le prepoznavo:
- AV1 (mp4 in webm/mkv), `vd=lavc:libdav1d`, 720p in 1080p + meritev izpuščenih sličic.
- DASH (lokalni .mpd) → predvaja segmente.
- MPEG-4 Part 2 (ne le .mp4 vsebnik).
- Vsebniki: MP4/MOV, MKV/WebM, MPEG-TS, AVI.
- HLS, HTTPS, HTTP-glave, piškotki, previjanje.
- Zajem slike: PNG/JPEG dejansko nastane.
- Podnapisi (vgrajeni + zunanji), zvočne steze.
Ločeno (seja 1 / prava naprava): vgradnja (wid/OSD/celozaslon), HDR→SDR, HDR-izhod na HDR-zaslonu,
delovanje na računalniku BREZ razvojnih orodij.

## "V zapisek" (zajem) — določiti pred testom (3 različne funkcije)
- (a) samo video sličica (screenshot-to-file "video"),
- (b) sličica + podnapisi,
- (c) celo okno z OSD (screenshot "window").
Vsaka rabi svoj test; privzeto predlagam (a) za "V zapisek", (c) ločeno za deljenje zaslona.

## Že preverjeno nocoj (r2 prototip, testni računalnik, Python 3.14, brez VLC)
DELUJE: H.264/HEVC/VP9, HDR zaznava (bt2020/pq), HLS, glave+piškotki, previjanje, zunanji podnapisi,
6/6 stabilno zapiranje, gpu-next+d3d11va izris (seja 1). VRZELI r2: AV1, DASH, MPEG-4 P2, zajem slike.

## Izvedba — mejnik 1 (2026-09-30)
- Fork: https://github.com/safeerOS/milutv-libmpv  (osnova jmonsellier/milutv-libmpv @ a36a682)
- Veja: safeer-build-r1, commit 0dee8cb (Matejev patch r1 + driver popravek + x64-only/brez objave/dnevniki)
- Lokalni klon: /home/janez/.tmp/milutv-src
- Tek 1: https://github.com/safeerOS/milutv-libmpv/actions/runs/36663066076  (workflow_dispatch, x64)
- Prag: check-safeer-capabilities.py (CONFIG_*), nato funkcionalni testi na Windows:
  scripts/smoke-safeer-player.py --av1 (mp4, webm), DASH, PNG "video"/"subtitles", h264 osnova, MPEG-4 P2.
- Opomba: prenos patcha prek orodja je spremenil 1 bajt (\s+ -> \s*) v check-safeer-capabilities.py;
  odkrito s primerjavo sha256 proti recipe/ in popravljeno. Vedno preverjaj rezultat, ne prenosa.
- Tek 2 (36663175680, 796c180): PADEL v Build libmpv. Vzrok: dav1d podprojekt OK, a ne klice
  meson.override_dependency('dav1d') -> "did not override 'dav1d' dependency and no variable name specified".
  Popravek e5bf407: wrap [provide] `dav1d = dav1d_dep` (src/meson.build:397 pri 54706fc). Tek 1 (36663066076)
  je padel v self-testu licence zaradi mojih pomoznih nizov -> umaknjeni (796c180).
- Tek 3: https://github.com/safeerOS/milutv-libmpv/actions/runs/36666352247 (e5bf407)
- Tek 3 (36666352247, e5bf407): dav1d in libxml2 razresena (YES), 2000/2000 prevedeno, mpv-2.dll povezan;
  PRAG check-safeer-capabilities je ustavil pakiranje: required_missing=[MPEG4_DECODER]. Vzrok (depgraph.py porta):
  'mpeg4_decoder': select ['h263_decoder','qpeldsp']; h263 ni bil na allow-listi -> resolver tiho izklopi mpeg4.
  Popravek de43c83: decoder += h263; prag += H263_DECODER. (Pojasni tudi r2 DLL brez MPEG-4 P2.)
- 06:10 DNS na janez: Safeer Shield (127.0.0.1:53, root) obtical (Recv-Q 212 kB, timeout), resolved brez DNS;
  zacasno `resolvectl dns enp1s0 192.168.0.1` (po pravilu: rezerva le, ko je filter sam nedosegljiv). Nepersistentno.
- Tek 4: https://github.com/safeerOS/milutv-libmpv/actions/runs/36668170637 (de43c83)
- Vzporedno: Codex (Linux, racun mojamama077 free) pise scripts/check-dll-deps.py (pravilo 6) v worktree milutv-codex, veja codex/dll-deps.
- Antigravity: `agy` CLI obstaja (-p, --dangerously-skip-permissions), a zahteva lastno prijavo (`agy` v terminalu) - ni uporabljen.
- check-dll-deps.py (60c2049, Codex + popravek): milutv r2 uvozi potrjeni z objdump; ANGLE = runtime LoadLibrary;
  UGOTOVITEV pravilo 6: paket zahteva MSVC runtime (MSVCP140, VCRUNTIME140, VCRUNTIME140_1) -> na cistem
  Windows brez VC++ 2015-2022 x64 Redistributable se libmpv NE nalozi. Odlocitev za izdajo: priloziti
  vcruntime DLL-je ali zahtevati Redistributable v namestitvenem paketu (test na cistem racunalniku obvezen).
- Tek 4 (36668170637, de43c83): PRAG ZMOZNOSTI PRESTAL (required_missing=[], forbidden=[]; MPEG4+H263 vkljucena).
  Padlo preverjanje "ena DLL" (korak 5): testdso.dll = libxml2 brezpogojen testni shared_module (ni odvisnost).
  Popravek 22ab357: izvzetje SAMO za testdso.dll v subprojects/libxml2; ostalo strogo.
- Tek 5: https://github.com/safeerOS/milutv-libmpv/actions/runs/36669847285 (22ab357)
- 06:27 DNS Linux: pravi vzrok obtical pihole-FTL (Pi-hole drzi :53; unbound je le upstream :5335). Restart z Matejevim
  sudo. Namescen nadzornik /usr/local/sbin/safeer-dns-nadzor.sh + systemd timer (30 s; 2 neuspeha -> restart +
  zacasna rezerva 192.168.0.1 samo dokler filter ne deluje; ob obnovi umik). Preverjen s simulacijo izpada: OK.
- Tek 5 (36669847285): padel isti korak 5 - regex zahteval `libxml2/`, mapa je `libxml2-2.15.4` -> e5cf7d3.
- Tek 6: https://github.com/safeerOS/milutv-libmpv/actions/runs/36671556517 (e5cf7d3) USPEL.
  Paket milutv-libmpv-safeer-av1-dash-snapshot-r1-x64.zip (51 MB) + sources.tar.gz (135 MB) v /home/janez/.tmp/r6.
  safeer-capabilities.json: configuration-pass, required_missing=[], forbidden=[]; manifest: dav1d 54706fc, libxml2 2.15.4-1;
  licenses/dav1d + licenses/libxml2-2.15.4 prisotni; ffmpeg-license.txt: CONFIG_GPL 0, VERSION3 0.
  check-dll-deps.py: PASS; zahteva MSVC runtime (MSVCP140/VCRUNTIME140/VCRUNTIME140_1). Vulkan ni uvozen.
  SHA256 libmpv-2.dll 19fed94b57e2947f4a8913d130c9cd81d35b2b1fd0706f27f6b000f416c47107 (23.9 MB); mpv v0.41.0-dev-gf9850ee72.
  Namesceno na Windows: C:\Users\User\Desktop\vendor\safeer-r1\.
- 07:34 gate-preizkus (run-safeer-gates.py, gpu-next+ANGLE, seja 1 prek schtasks): PRVI podproces (h264_pred, r1 DLL)
  je OBTICAL - 180 s timeout; proces python 7200 je ostal kot neubijljiv zombi (0 niti, "Access denied"), vsi
  NADALJNJI python procesi v seji 1 (tudi r2 kontrola in goli `python -c print`) so cakali v stanju PageIn.
  Vzrok NI dolocen (r1 DLL ali stanje racunalnika po 4,5 dneh; r2 harness je prej deloval). Ponovni zagon
  Windows (shutdown /r; sshd auto, AutoAdminLogon=1 brez shranjenega gesla) -> po zagonu OBTICI NA LogonUI
  (ni prijave v sejo 1) -> GUI/render preizkusi so blokirani, dokler se Matej ne prijavi.
- 07:50 preizkusi na ravni DEKODIRANJA (seja 0, vo=null, hwdec=no, scripts smoke0.py, brez okna) z r1 DLL:
  h264_24s.mp4 PASS (h264) | av1_24s.mp4 PASS (Selected decoder: libdav1d) + PNG 640x360 (85 kB, slika preverjena:
  testsrc okvir 00:00:05.042) | av1_24s.webm PASS (demuxer mkv, libdav1d) | mpeg4p2_24s.avi PASS (mpeg4) |
  DASH prek lokalnega http (index.mpd, 24 s, 12x HTTP 200) PASS + PNG. Rezultati C:\Users\User\Desktop\gates0\*.json.
  Opomba: stari media\dash je dolg le 2 s -> gates skripta z --seconds 8 bi ga oznacila kot padec; nov media\dash24 (24 s).
  MEJNIK 1 STANJE: dekodiranje AV1+DASH+PNG dokazano; izris (gpu-next/ANGLE) z r1 DLL SE NI potrjen (blokiran GUI)
  in odprt je incident obticanega procesa -> mejnik 1 se NI zakljucen.
- dependency-auditor (alirezarezvani/claude-skills): pregledan; skripte razclenjujejo package.json/requirements/go.mod,
  ne Meson/FFmpeg; matrika licenc je poenostavljena in mestoma napacna (npr. LGPL-2.1 vs Apache-2.0 oznacena kot
  nezdruzljiva). Za naso C gradnjo ni uporaben; nas prag je check-safeer-capabilities.py + ffmpeg-license.txt. Ni prevzet.
- 07:59 VZROK OBTICANJA NAJDEN (dnevnik dogodkov + WER): python.exe se je ob 07:34:53 SESUL v
  C:\WINDOWS\SYSTEM32\MSVCP140.dll 14.32.31326 (0xc0000005, offset 0x13278) z nalozenimi libmpv-2.dll + libEGL + libGLESv2
  + d3d11/igd10iumd64. Ponovljivo v seji 0 (smokeg.py, gpu-next/angle): r1 IN r2 (milutv) se sesujeta enako ->
  ni napaka r1 gradnje. S predhodno nalozenim msvcp140 14.44 (PySide6 paket) ni sesutja (ANGLE potem odpove le
  zaradi seje brez namizja, 0x887A0022 - pricakovano). Razlaga: ANGLE/libplacebo prevedena z MSVC STL 14.51
  (linker 14.51) zahteva msvcp140 >= 14.40 (znana nezdruzljivost std::mutex z starejsim msvcp140); prejsnji r2
  render_harness je deloval, ker je uvoz PySide6 prej nalozil msvcp140 14.44. Smoke skripta brez Qt -> sistemski 14.32 -> crash.
  POSLEDICA (pravilo 6): koncni paket MORA prilagati lastne msvcp140/vcruntime140/vcruntime140_1 (>= 14.44, iz VC redist)
  ali ob zagonu preveriti razlicico in pogon zavrniti z jasnim zapisom (ne sesuti). check-dll-deps.py "requires
  Redistributable" ni dovolj - potrebna je MINIMALNA razlicica.
  Popravek skript: smoke-safeer-player.py --runtime-dir (predhodno nalozi manjkajoce runtime DLL-je iz mape, v porocilo
  zapise msvcp140_loaded_from / vcruntime140_loaded_from); run-safeer-gates.py --runtime-dir. Na Windows:
  vendor\safeer-r1\runtime\ (14.44 iz PySide6, SAMO za preizkus). Seja 0: preload OK, brez sesutja.
  Gate-preizkusi izrisa cakajo na prijavo v sejo 1 (LogonUI).
- 09:16 Matej: geslo Windows — NE uporabljeno (vnos gesel za prijavo je zame prepovedano dejanje); GUI cakajo na prijavo.
- 09:20 Pravilo 6 v gradnji: scripts/package.ps1 korak 4b prilozi runtime\ (msvcp140, vcruntime140, vcruntime140_1) iz
  orodjarne (VCToolsRedistDir / VS\VC\Redist\MSVC, Microsoft.VC*.CRT za x64), zapise razlicice v manifest.runtime +
  licenses\msvc-runtime\README.txt (+ redist.txt, ce najden); check-dll-deps.py preveri, da je runtime\ prilozen
  (FAIL, ce manifest to obljublja, a datotek ni). Commit 9fc941f potisnjen na safeer-build-r1; Tek 7:
  https://github.com/safeerOS/milutv-libmpv/actions/runs/36682873363 (podvojeni 36682898397 preklican).
- safeer_mpv_pogon.py: predpripravi_runtime() (klic PRED uvozom PySide6), nalozi runtime\ iz paketa (le manjkajoce DLL-je),
  prebere zahtevano razlicico iz manifest.runtime, ob prestarem msvcp140 vrne libmpv_na_voljo()=False z razlogom
  (STANJE["napaka"]) -> nadzorovan preklop na Qt pogon; v dnevnik zapise mapo, msvcp140 pot+razlicico, runtime stanje.
  Preverjeno na Windows (seja 0): r1 + runtime 14.44 -> na_voljo=True, msvcp140 iz runtime\; simulacija zahteve 14.51
  -> False z jasnim sporocilom; po vrnitvi manifesta spet True. Desktop\vendor\mpv (zhongfly, Vulkan) preimenovan v
  mpv-zhongfly-NEUPORABNO-vulkan, da ga iskanje ne izbere.
- 09:25 Nove 24 s testne datoteke (stare hevc/vp9/hdr_pq/av1/h264.mp4 so le 2 s): media\hevc_24s.mp4, vp9_24s.webm,
  hdr_pq_24s.mp4 (HEVC 10-bit, bt2020/PQ). Strojno dekodiranje r1 (seja 0, vo=null, hwdec=d3d11va-copy, Intel HD 4600):
  h264 -> d3d11va-copy PASS (nv12) | hevc 8-bit -> d3d11va-copy PASS | hevc 10-bit PQ -> programsko (HD 4600 nima Main10),
  PASS z zaznanim HDR (primaries bt.2020, gamma pq, sig-peak 49.26) | vp9 -> programsko PASS. Locitev dekodiranja od
  izrisa (pravilo 3) potrjena: dekodiranje deluje brez okna. HDR->SDR IZRIS se ni preverjen (GUI).
- Tek 7 (36682873363, 9fc941f) USPEL. Paket zdaj vsebuje runtime\ (msvcp140/vcruntime140/vcruntime140_1 14.51.36247.0
  iz VS 18 Enterprise, VC\Redist\MSVC\14.51.36231\x64\Microsoft.VC145.CRT), manifest.runtime z razlicicami + toolchain
  14.51.36231, licenses\msvc-runtime\README.txt + redist.txt. check-dll-deps: PASS, "bundled". configuration-pass.
  libmpv-2.dll SHA256 04a46f35... (RAZLICEN od teka 6: 19fed94b...) -> gradnja je pripeta (isti viri), ni pa bitno
  ponovljiva (casovni zigi/PDB GUID); za pravilo 5 velja pripetost vhodov + manifest, ne enakost hashev.
  Namesceno na Windows (vendor\safeer-r1 zamenjan, runtime 14.51 namesto PySide6 14.44). Preverjeno (seja 0):
  pogtest: na_voljo=True, msvcp140 iz runtime\ 14.51 = zahtevana 14.51; AV1 dekodiranje + PNG PASS; gpu smoke z
  --runtime-dir: brez sesutja (odpove le zaradi seje brez namizja). Za GUI gate-preizkuse ostane prijava v sejo 1.
- __main__.py: na Windows pred uvozom PySide6 poklice safeer_mpv_pogon.predpripravi_runtime() (no-op brez paketa).
  README forka: dokumentiran priloz. runtime (fb50b42, potisnjeno na safeer-build-r1).
  STANJE 09:45: brez GUI ni vec kaj preverjati. Odprto (potrebuje prijavo v sejo 1): gate-preizkusi izrisa r1
  (gpu-next/ANGLE, hwdec auto, PNG iz okna), HDR->SDR, celozaslon/OSD, Qt vgradnja (wid); nato paket na cistem Windows.
- 10:25-10:40 Qt VGRADNJA (wid) razvita in preverjena na Linux Mint (X11, libmpv 0.37 sistemski, python-mpv 1.0.8 --user,
  PySide6 6.11.2) kot preizkusna klop za skupno kodo; Linux izdelek NI spremenjen. Nov modul safeer_mpv_okno.py:
  SafeerMpvVideo (nativna povrsina, wid) + SafeerMpvPredvajalnik (video + vrstica pod videom, celozaslon, tipke,
  Qt-signalni most iz mpv niti). Preizkusi (test_okno.py, test_ena.py, test_ponovi.py v ~/.tmp/mpvokno, posnetki v
  outputs/preizkus-telefon/libmpv-r1): vgradnja v Qt okno OK (gpu-next v wid), celozaslon + vrnitev OK, skok OK,
  posnetek OK, 8 datotek zapored v ENI instanci (h264/av1/hevc/vp9/HDR PQ/mpeg4/av1 webm) 8/8 OK (hwdec=no),
  6x ustvari/unici widget+pogon 6/6 OK (hwdec=no).
  NAJDENE IN POPRAVLJENE NAPAKE POGONA (safeer_mpv_pogon.py): (1) segfault: __init__ je takoj ustvaril vo=null instanco,
  povezi_video jo je unicil sredi opazovalnega klica -> zdaj lazno ustvarjanje (_zagotovi), _unici z zastavico
  _zapiranje + RLock; (2) branje lastnosti iz mpv niti (property_observer -> podatki()) umaknjeno: mpv nit le
  sporoci, GUI nit bere; end-file -> _konec_cakajoc, GUI klice obdelaj_konec(); (3) HWDEC nastavljiv (SAFEER_MPV_HWDEC).
  NAJDENA NAPAKA OKNA: prestarsenje nativnega widgeta v celozaslon na X11 ustvari NOVO nativno okno (mpv rise v staro)
  -> celozaslon zdaj brez prestarsenja: vrhnje okno showFullScreen + skrij sorodnike, wid ostane; geometrija obnovljena.
  ODPRTO (samo Linux klop): z hwdec=auto (vaapi, mpv 0.37) se proces sesuje v mpv_get_property ob menjavi datoteke
  (tudi vaapi-copy, tudi z branjem iz GUI niti) -> napaka libmpv/libva na tej klopi, ne nase kode; na Windows (r1, d3d11va)
  je treba menjavo datotek s hwdec preveriti posebej (GUI).
- 10:45-10:55 Samostojni predvajalnik safeer_predvajalnik.py (isti widget/pogon; `python -m safeer_windows --predvajalnik
  [datoteke|URL]`): meniji Datoteka/Predvajanje/Zvok/Podnapisi (sledi iz podatki()["steze"], osvezitev le ob spremembi),
  povleci-in-spusti, samo http/https URL, podnapisi (sub-add; preverjeno sid=1 zunanji). safeer_pogon_izbira.py:
  izbira mpv->qt z razlogom v dnevniku (SAFEER_POGON za preizkuse); na Windows preverjeno: "pogon: mpv (r1, msvcp140 14.51)".
  OSD (show-text prek libass) deluje v LGPL gradnji (posnetek 6_osd). Spletne glave: Referer/User-Agent/X-glave mpv poslje
  sam (streznik jih videl), brez glav 403 -> ustavljeno, z glavami predvaja. Opomba: python http.server brez Range ->
  mp4 z moov na koncu ne igra (webm/DASH v redu) - lastnost testnega streznika, ne pogona.
  Za Windows GUI (ko bo prijava): sw_test\gui_r1.cmd = test_okno_win.py (Qt vgradnja, hwdec auto, posnetki) + gates.
- 10:55-11:10 MEDIJSKI CENTER NA libmpv: nov mpv_player.py (MpvPlayerWidget) z ISTIM vmesnikom kot VlcPlayerWidget
  (available, player.is_playing(), play_item z razlicicami/glavami/podnapisi ob videu, izberi_podnapise z:k/v:id,
  naslednji_podnapisi (V), set_fullscreen_ui, nazaj/ozadje, isti videz). Podnapisi: mpv sub-add (sinhron; sid),
  vgrajeni iz track-list, samodejna izbira prek podnapisi_izbira kot doslej. Preizkus na Linux klopi (test_media.py):
  play_item OK, zunanji SRT samodejno izbran (sl), V -> izklop, menjava razlicice (AV1) OK, celozaslon UI OK, stop OK.
  os_app.py: _ustvari_medijski_center() -> mpv_player, ce safeer_pogon_izbira izbere mpv, sicer VlcPlayerWidget
  (nespremenjen); closeEvent zapre mpv pogon. launcher_os.py + __main__.py: predpripravi_runtime() pred PySide6.
  build_windows.py: mpv_vendor_args() - windows/vendor/mpv (izbirno) -> _internal/safeer_windows/vendor/mpv;
  ce mapa obstaja in je nepopolna (DLL, runtime, manifest, licence) ali python-mpv manjka -> gradnja PADE (pravilo 6).
  requirements.txt += python-mpv==1.0.8. OPOZORILO: test_media je zapisal ~/.config/safeer-os/podnapisi.json na
  Matejevem Linuxu (prej ga ni bilo) -> izbrisan, stanje obnovljeno; nadaljnji testi z XDG_CONFIG_HOME v ~/.tmp.
  SE NI: gradnja SafeerOS.exe z vendor/mpv (potrebuje Windows GUI za preizkus), CI korak za prenos pripetega paketa.
- 11:10-11:20 PAKET ZA WINDOWS Z libmpv: windows/safeer_windows/vendor/mpv (iz teka 7: 3 DLL, runtime\, licenses\,
  manifest, capabilities, ffmpeg-license; 30 MB; v .gitignore - CI ga bo moral prenesti iz pripete izdaje forka).
  safeer_os_windows.py: predpripravi_runtime() pred PySide6. launcher_go/main.go: pip seznam += python-mpv==1.0.8,
  preverjanje prek importlib.util.find_spec('mpv') (NE `import mpv`, ker ta nalozi DLL). Nov zip (283 datotek, 80 MB,
  sha 4373e64b) + SafeerOS.exe (Go, 82.7 MB, sha 9741d052...) zgrajen na janez; stari shranjeni kot *.pred-mpv.bak.
  Na Windows: Desktop\SafeerOS-mpv.exe (NI zamenjal SafeerOS-newest.exe) + sw_test\app (razpakiran zip): izbira pogona
  iz paketa = mpv, vendor\mpv v paketu, runtime 14.51 (seja 0). gui_r1.cmd korak 3: zagon Safeer OS v oknu + posnetek.
- 11:08 Matej "Da" -> PREDIZDAJA na forku: https://github.com/safeerOS/milutv-libmpv/releases/tag/safeer-av1-dash-snapshot-r1
  (x64 zip sha256 2e9f73c1c7e293d4305018affcb7727b1976fb001c7c317c724a3b7a7c67ba14, sources.tar.gz 135 MB (LGPL vir),
  SHA256SUMS, angle-x64.json, ffmpeg-license-x64.txt; opombe: kaj je preverjeno in kaj NE). Prenos preverjen (sha enak).
- 11:10-11:15 SESUTJE VAAPI RAZISKANO (Matej: "odkrij napako in odpravi"): gdb backtrace -> SIGSEGV v
  libavcodec.so.60 (FFmpeg 6.1.1-3ubuntu5) v avcodec_send_packet iz mpv dekodirne niti; samo AV1 + VAAPI
  (h264/hevc/vp9 z vaapi OK). Ponovljivo tudi s SAMOSTOJNIM mpv 0.37 (`mpv --hwdec=vaapi-copy av1_24s.webm` -> core dump)
  -> napaka sistemskega FFmpeg/iHD, ne nase kode. ODPRAVA v pogonu: hwdec_kodeki_za(ffmpeg_version, platforma):
  Linux + FFmpeg < 7 -> hwdec-codecs brez av1 (AV1 programsko z dav1d, ostali strojno), razlog v dnevnik in STANJE.
  Windows nespremenjen. Po popravku z hwdec=auto: test_ena 8/8 (h264/hevc/vp9/HDR vaapi, AV1 dav1d), test_ponovi 6/6,
  test_okno OK. +3 enotni testi (7/7).
- 11:15-11:18 CI: windows/fetch_libmpv.py (pripeti URL izdaje + SHA-256 2e9f73c1..., razpakira le potrebno v
  vendor/mpv, .izdaja znak; neujemanje vsote/nepopoln paket = izhod != 0), preverjen (identicno rocni kopiji);
  .github/workflows/windows-package.yml: korak "Fetch pinned libmpv" pred PyInstallerjem; build_windows.py fetch-libmpv.
  Nov zip (286 datotek, sha 3d1ebea3) + SafeerOS.exe (sha 0a74fb44...) -> Windows Desktop\SafeerOS-mpv.exe in sw_test\app.
  Preizkus nadzorovane rezerve na Windows: ce se PySide6 uvozi PRED predpripravi_runtime(), je v procesu msvcp140 14.44
  (shiboken6) -> pogon libmpv ZAVRNJEN z razlogom, izbran qt (REZERVA) - brez sesutja. Z vstopno tocko
  safeer_os_windows.py (predpripravi najprej) -> mpv, 14.51. Ravno to je razlog za klic pred PySide6.
- 11:43-11:55 Matej: (1) samostojni predvajalnik tudi za Linux; (2) v nastavitvah VSEH razlicic jasno oznacen vnos
  naslova za Stremio in Kodi dodatke. Narejeno:
  * predvajalnik_nastavitve.py (skupno Windows/Linux/Medijski center): stremio_dodatki/kodi_dodatki, preverjanje
    (stremio:// -> https, mora se koncati z /manifest.json; Kodi http(s)), JSON v %APPDATA%\Safeer oz. ~/.config/safeer;
    BEZ prilozenih katalogov. +5 enotnih testov. predvajalnik_dodatki_okno.py (Qt): dve jasno oznaceni polji + seznam.
    Samostojni predvajalnik: meni Nastavitve -> Dodatki (Stremio, Kodi) (Ctrl+D); Medijski center: gumb "Dodatki".
    Preverjeno na Linuxu (posnetek 10_dodatki, shranjevanje v JSON).
  * Linux: predvajalnik/safeer-predvajalnik (zaganjalnik, sistemski libmpv2 + PySide6 + python-mpv), .desktop, README;
    preizkus na Mintu OK (posnetek 11_linux_predvajalnik). Paketi .deb/AppImage/Flatpak sledijo z izdajo.
  * Android (veja dodatki-stremio-kodi, commit c0a322d, ni potisnjena): Safeer Media -> Moji viri -> kartica
    "Dodatki (Stremio, Kodi)" z dvema oznacenima poljema, MedijskiViri STREMIO/KODI, besedila v 6 jezikih; preverjeno
    na testnem telefonu (okno, vnos, shranjeno, prikaz med viri).
  * Android veja predvajalnik-tovarna (d7a5fbe) je loceno: skupna tovarna ExoPlayerja, meritve, zmogljivost dekoderja.
- 12:00-12:15 Matej: "objavi kar je preverjeno" + predvajalnik naj ima predstavitev na strani Medijskega centra.
  GitHub: Safeer-windows veja predvajalnik-libmpv (ba22ba9), Android-tv veji predvajalnik-tovarna (d7a5fbe) in
  dodatki-stremio-kodi (c0a322d) potisnjene (brez izdaj: Windows GUI in TV nista preverjena; main nespremenjen).
  safeer.si: v razdelku Medijski center nov pododdelek "Safeer predvajalnik" (SL/EN, preverjena dejstva, brez prenosov
  in brez obljubljene razlicice; posnetek okna Dodatki; povezava na gradnjo libmpv na GitHubu); V=20260930-p4;
  preverbe zelene (povezave 13 strani, brez drsnika, zasebnost); objavljeno prek izdaja --stran (Cloudflare).
  INCIDENT: prva dva poskusa objave padla - wrangler v Dockerju brez DNS. Vzrok: moj jutranji `resolvectl revert enp1s0`
  je odstranil DNS (192.168.0.1), ki ga NetworkManager potisne ob aktivaciji; gostitelj je delal le zato, ker glibc brez
  nameserverja vzame 127.0.0.1 (Pi-hole), Docker pa ne. Popravek: `resolvectl dns enp1s0 192.168.0.1` (kot DHCP).
  ODPRTO: safeer-dns-nadzor.sh ob "obnovi" naredi `resolvectl revert` -> isti izpad se bo ponovil; treba popraviti
  (namesto revert: nastavi 192.168.0.1) - potrebuje sudo, cakam Mateja.
- 12:26-12:36 Matej: samostojni "Safeer media player" za Android - za/proti, zmagovalec se naredi. ZA zmagal (skupna koda
  iznici podvajanje; strosek = nov okus). Android-tv veja predvajalnik-android (e84c746, potisnjena, iz dodatki-stremio-kodi):
  okus predvajalnik = si.safeer.player 0.1.0, manifest okusi/predvajalnik (LAUNCHER -> GlasbaActivity, VIEW video/audio/
  HLS/DASH prek content/file/http/https, brez leanback/boot/HOME), GlasbaActivity.predvajajIzNamena (ACTION_VIEW ->
  GlasbaStoritev + PredvajanjeActivity), build_tv_apk.sh podpise Safeer-Predvajalnik.apk. Preverjeno na testnem telefonu:
  namestitev ob Safeer OS, "Odpri z" http naslova videa igra (posnetek), brez FATAL. Lastna ikona in izdaja sledita.
- 12:47-13:12 Matej "Da" -> IZDAJA Safeer Predvajalnik 0.1.0 (Android). Lokalni main je bil 78 commitov za origin (2.1.130);
  reset na origin/main, veje dodatki + predvajalnik rebasane (spori: strings x7, MedijskiViri, GlasbaActivity iskanje,
  build_tv_apk.sh - upstream ima nov okus telefon), lastna ikona, stranska vrstica v okusu predvajalnik le Mediji/Naprave/
  Datoteke/Nastavitve. build_tv_apk.sh (vsi okusi) OK, podpis z izdajnim kljucem (sha e7808780...), 8.3 MB, 0.1.0.
  Preverjeno na telefonu: zagon, "Odpri z" (av1 webm prek http) PLAYING, brez FATAL. Oznaka predvajalnik-v0.1.0, izdaja
  https://github.com/safeerOS/Android-tv/releases/tag/predvajalnik-v0.1.0 (APK + .sha256 6ca61b68...). Veja
  predvajalnik-android potisnjena s --force-with-lease (rebase; razvojna veja). safeer.si: prenos v razdelku Safeer
  predvajalnik (7.94 MiB, izracunano), PREVERBE/PRENOSI posodobljeni, objavljeno in preverjeno (200, sha enak).
  Veja predvajalnik-tovarna se NI rebasana na 2.1.130 (sledi). NI v izdaji: TV/OS (nespremenjeno 2.1.130/0.5.6).

## 2026-09-30 13:38 — sklop (1): napredne funkcije namiznega predvajalnika (Linux klop, preverjeno)

Kaj je novo (skupna koda: samostojni predvajalnik in Medijski center):
- **Nadaljuj tam, kjer si končal** — `predvajalnik_nadaljuj.py` (`nadaljuj.json` poleg nastavitev; pravila
  kot v Safeer OS na Androidu: > 10 s od začetka, > 30 s do konca, največ 500 vnosov; ob koncu datoteke se
  vnos pozabi). `Sledilec` beleži vsakih ~5 s, takoj ob premoru in zaprtju; pogonu da `nadaljevanje(uri)` in
  `ob_koncu_datoteke(uri)`. Pogon: `predvajaj(i, zacetek)` (`start=`), `zacel_pri`; OSD "⏵ Nadaljujem od …".
  Izklop: `SAFEER_NADALJUJ=0`.
- **Zamik podnapisov/zvoka** (`sub-delay`/`audio-delay`): tipke Z/X in K/L (0,1 s; Shift 1 s), meniji
  Podnapisi ▸ Zamik / Zvok ▸ Zamik (vnos, ponastavi), v `podatki()` `zamikPodnapisov`, `zamikZvoka`.
- **Poglavja**: meni Poglavja (dinamičen iz `chapter-list`, označeno trenutno), PgUp/PgDn, `poglavje`/`nPoglavij`.
- **Skok na čas** Ctrl+T (`razclleni_cas`: 1:23:45, 23:45, 90, 1h5m, 12,5), Home = od začetka.
- **Hitrost** [ ] ±0,1, Backspace 1×, meni 0,5–2×; **sličica** naprej/nazaj (`.`/`,`, frame-step); **posnetek** S
  (PNG v Slike/Safeer, `screenshot-to-file`).
- Popravek stanja: `core-idle` je True tudi med premorom → po premoru je stanje prej kazalo "ustavljeno"
  (in Sledilec ni beležil). Zdaj `idle_active` ali `eof_reached` = "ustavljeno"; po koncu datoteke gumb ⏵
  predvaja znova.

Preverjeno (`~/.tmp/mpvokno/test_sklop1.py A/B`, `test_media.py`, h264 120 s + mkv s 3 poglavji):
- A: zamik podnapisov +0,5 −0,2 → 0,3 s; zvok −0,3 → 0; hitrost 1,5 → 1; skok na 15 s → položaj 16,5; premor →
  `nadaljuj.json` {polozaj 16.5, trajanje 120.1}; posnetek PNG 294 kB.
- B: odpre isto datoteko → začne pri 16,5 (`zacel_pri`=16.5, po 2 s 18,5); po koncu datoteke vnos izbrisan
  (`{}`), stanje "ustavljeno"; poglavja [Uvod 0, Sredina 8, Konec 16]; PgDn → poglavje 1 (8,8 s); poglavje(2) → 16,9 s.
- Samostojno okno: meniji Predvajanje/Poglavja/Zvok ▸ Zamik/Podnapisi ▸ Zamik zgrajeni, posnetek `12_sklop1.png`.
- Medijski center (`test_media.py`): nespremenjeno zeleno; pytest windows/tests: 289 passed (+ test_sledilec).
Windows GUI: še ni preverjeno (čaka prijavo; gui_r1.cmd).

## 2026-09-30 13:50 — sklop (2a): MPRIS2 (Linux) + medijske tipke; SMTC (Windows) odprto

- `predvajalnik_mpris.py`: MPRIS2 prek PySide6.QtDBus (brez novih odvisnosti). Storitev
  `org.mpris.MediaPlayer2.safeer` (samostojni) / `.safeeros` (Medijski center), ob zasedenem imenu `.instance<pid>`.
  Vmesnika `org.mpris.MediaPlayer2` (Raise, Quit, Identity, DesktopEntry=safeer-predvajalnik, sheme, MIME) in
  `.Player` (PlayPause/Play/Pause/Stop/Next/Previous/Seek/SetPosition/OpenUri; PlaybackStatus, Metadata
  (trackid, title, url, length), Position, Volume (r/w), Rate (r/w, 0,25–4), Can*), signali PropertiesChanged in Seeked.
  Vsi klici v GUI niti (QtDBus dostavlja v Qt zanko). Izklop: `SAFEER_MPRIS=0`. Ce ni D-Bus seje/QtDBus → neaktiven, brez napake.
- Medijske tipke v oknu (Qt Key_MediaPlay/Pause/TogglePlayPause/Stop/Next/Previous) v obeh gostiteljih (Linux + Windows).
- Pogon: `premor()` zdaj takoj sporoci stanje (med premorom ni tikov time-pos → MPRIS je kazal staro stanje).
- Sledilec: ob ustavitvi (Stop) zapise zadnji znani polozaj iste datoteke (test_sledilec_ustavitev).
- Omejitev: `mpris:length` je `i` (int32) pod 2^31 µs in `x` nad tem — PySide6 QDBusArgument ne zna vsiliti
  qlonglong v QVariantMap. playerctl/Cinnamon/GNOME/KDE to prenasajo (preverjeno le z busctl).

Preverjeno (Linux klop, busctl): Identity, PlaybackStatus Playing→Paused→Playing (<0,3 s), Metadata z naslovom/url/
length, Position `x`, Volume set 0.5 → 0.5, Next/Previous menjata datoteko in CanGoNext/CanGoPrevious, SetPosition 60 s
→ Position 60,5 s, Rate 1.5, Stop → Stopped, Play → predvaja znova (z nadaljevanjem), Raise; Medijski center
(`test_media.py`) objavi `safeeros`, PlayPause prek D-Bus deluje, test ostaja zelen; pytest 290 passed.
Odprto: Windows SMTC (System Media Transport Controls) — potrebuje WinRT (paket `winrt`/`winsdk` + interop za HWND);
brez prijave na Windows PC ni preverljivo, zato ga ne dodajam na slepo. Na Windows zaenkrat delujejo medijske tipke,
ko ima okno fokus. Link daljinec: ukazi gredo prek Safeer Control → navidezni zaslon (tipke); posebna vez s
predvajalnikom bo v sklopu 2b, ko preverim protokol Control-a.

## 2026-09-30 14:00 — sklop (2b): daljinec Link → Medijski center (v istem procesu)

- `control_backend.py`: `ob_mediju(ukaz, params)` (os_app nastavi). Tipke daljinca `play_pause/play/pause/stop/
  next/previous` gredo najprej v Medijski center; če ta ne predvaja (`ni_predvajanja`) ali ga ni, ostane dosedanje
  vedenje (navidezni zaslon). Nov ukaz `media` (`cmd`: play_pause, play, pause, stop, next, previous, seek
  {seconds}, volume {level}); `status` dobi `media` {active, status, title, position, duration, volume, index,
  count, engine}, `actions` += media, `keys` += next, previous. Dovoljenje kot za `key` (profil polno).
- `os_app.py`: `_link_medij` (omrežna nit → `dispatcher` → nit vmesnika; odgovor takoj z zadnjim znanim
  stanjem), `_media_zabelezi_stanje` (cache pod ključavnico iz signala `MpvPlayerWidget.stanje_spremenjeno`).
  Z VLC pogonom: play_pause/play/pause/stop; z mpv še next/previous/seek/volume.
- Preverjeno: `tests/test_link_medij.py` (3 testi: tipke → predvajalnik, neznana tipka → navidezni zaslon, brez
  predvajanja → navidezni zaslon, `media` brez centra → `ni_medija`, status z `media`); Linux klop
  `test_link_medij_gui.py` z MpvPlayerWidget iz tuje niti: status (stopped→playing "Film" 120 s), play_pause →
  paused, play → playing, seek +40 → 46 s, volume 33, neznan ukaz → None, stop → stopped. pytest 293 passed.
Odprto: odjemalec daljinca (Android Link) še nima gumbov naslednja/prejšnja; `keys` jih že oglašuje.
Safeer Control na Linuxu (drug repo) bi lahko isto dosegel prek MPRIS (`org.mpris.MediaPlayer2.safeer*`).

## 2026-09-30 14:10 — sklop (3): izbira kakovosti HLS/DASH

- Ugotovitev (preverjeno z mpv 0.37 / FFmpeg 6.1 na lokalnem HLS master.m3u8 in DASH .mpd z 2 razlicicama):
  FFmpeg demuxer izpostavi vsako razlicico kot svojo video sled (`demux-w/h`, `hls-bitrate`); mpv izbere ob
  zacetku po `--hls-bitrate` (privzeto max) in NE preklaplja samodejno. Izbira kakovosti = preklop `vid`;
  predvajanje se nadaljuje z istega mesta (640→320 v ~1 s).
- Pogon: `steze()` vrne `video` [{indeks, ime "640×360 · 0,9 Mb/s", sirina, visina, bitnost}] urejeno od
  najboljse (prazno pri eni sledi) in `trenutniVideo`; `nastavi_kakovost(id)`.
- Samostojni predvajalnik: meni **Kakovost** (viden le pri ≥2 razlicicah, oznacena trenutna).
- Medijski center: spustni seznam ▤ Kakovost poleg obstojecega izbora virov (viden le pri ≥2 razlicicah).
- Preverjeno na klopi: HLS v samostojnem oknu (meni 640×360/320×180, preklop → width 320, polozaj tece naprej,
  pri lokalni datoteki meni skrit), DASH v Medijskem centru (seznam, preklop → 320). Testi test_mpv_kakovost (3);
  pytest 296 passed.
Ni "samodejno" (ABR): mpv tega ne zna; ce bo potreba, je to lastna logika nad `nastavi_kakovost` (odprto).

## 2026-09-30 14:25 — sklop (4): Android predvajalnik (veja predvajalnik-android, 7895bc2, NI izdano)

Namesto skritih kretenj (Matej 29. 9.: »vidni gumbi in kartice«) vidni gumbi na telefonu/tablici:
- **Zvočna sled** (`ZvocneSledi.kt`, gumb 🔈 le pri >1 sledi, dialog kot pri podnapisih).
- **−10 s / +10 s** gumba, **drsnik po posnetku** (SeekBar; premik ob spustu, med vlečenjem se ne prepisuje).
- **Slika v sliki**: gumb + `supportsPictureInPicture`; razmerje iz videa (omejeno na 1:2,39–2,39:1); gumb
  predvajaj/premor v PiP oknu (RemoteAction → PendingIntent → sprejemnik, prijavljen samo v PiP); samodejni
  vstop ob Domov na Androidu 12+ (`setAutoEnterEnabled` med predvajanjem videa), na 8–11 `onUserLeaveHint`;
  v PiP je prekritje skrito.
- Popravka mimogrede: naslov pri `content://` je bil številka (zdaj DISPLAY_NAME); v samostojnem predvajalniku
  je Nazaj iz Medijev vodil v Domov Safeer OS (»Poveži naprave« itd.) – zdaj Nazaj iz razdelka → Mediji, iz
  Medijev → izhod.
Preverjeno na WP28_S (Android 14) z datoteko z 2 zvočnima sledema (slv/eng): gumbi vidni, dialog »Zvočna sled«
(Slovenščina · mono / Angleščina · mono), preklop na angleško obvelja; PiP se odpre (316×178, 16:9), video teče v
oknu, prekritje skrito, zapiranje PiP zapre predvajanje; naslov »dvazvoka_120s.mp4«; Nazaj: Datoteke → Mediji → izhod.
**Nepreverjeno:** gumb predvajaj/premor v PiP oknu – z adb dotiki nisem zadel gumba (dotik je okno razširil);
`am broadcast` iz lupine ga ne more sprožiti (sprejemnik ni izvožen – pravilno). Preveri ročno.
Opomba: `file://` iz `am start` da EACCES (omejen dostop Androida) – to ni napaka aplikacije; upravitelji datotek
pošljejo `content://`.
