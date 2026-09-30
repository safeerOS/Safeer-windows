# Prototipna libmpv gradnja — provenanca (NE za izdajo)

Namen: samo Windows prototip za primerjavo pogonov. Za izdajo velja lastna gradnja
(GitHub Actions, pripeti commiti, pregled odvisnosti, licence, kontrolne vsote).

- Vir: https://github.com/jmonsellier/milutv-libmpv (tretja oseba)
- Izdaja: mpv-f9850ee-ff9.0.1-r2  (mpv v0.41.0-dev-gf9850ee72, FFmpeg 9.0.1)
- Datoteka: milutv-libmpv-mpv-f9850ee-ff9.0.1-r2-x64.zip
- SHA256 (potrjen ob prenosu): c8f8763e8a5bd6c907669c8ed731b1b2ad05c8823347f750f892e9f9b2e595da
- Licenca (dokazi v paketu): mpv -Dgpl=false; FFmpeg CONFIG_GPL 0, CONFIG_VERSION3 0 (LGPL v2.1+);
  odvisnosti: libplacebo/FriBidi (LGPL), libass (ISC), FreeType, HarfBuzz (MIT), zlib, ANGLE (BSD-3).
- Izkljuceno v tej gradnji: Vulkan, D3D11 render API, runtime shader prevajalnik, skriptanje (ni "osc").
  Izris tece prek ANGLE (OpenGL ES -> D3D). Dejanski izbrani izrisovalnik je treba potrditi iz dnevnika.
- Opozorilo: SHA256 dokazuje ujemanje z objavljeno vsoto, NE gradnje iz navedene kode.
  Reproducibilnost dokaze sele lastna gradnja.

Preverjeno na testnem racunalniku (Windows, Python 3.14.7, brez uporabe VLC):
- python-mpv 1.0.8 uvoz OK; mpv init OK; predvajanje OK; property_observer (callbacki) OK; terminate OK.
- HTTP glave nastavljive: user-agent, referrer, http-header-fields.
- Adapter safeer_mpv_pogon.SafeerMpvPogon: predvajanje + glasnost/hitrost/utisaj/ponovi/skok/steze/callback/zapri OK.

Se NI potrjeno: gpu-next izris v okno (wid) v seji namizja, celozaslon, veckratno zapiranje,
slika/podnapisi vizualno, delovanje v uradnem paketu brez namescenega mpv/VLC.
