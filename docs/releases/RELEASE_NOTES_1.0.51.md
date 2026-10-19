# Safeer OS za Windows 1.0.51

**Zaslon računalnika z zvokom.** Ko računalnik gledaš in upravljaš s televizorja, tablice ali telefona (Povezani zasloni), zdaj slišiš tudi zvok, ki ga računalnik predvaja – film, YouTube, sistemske zvoke. Zvok gre kot surov PCM (48 kHz, stereo, koščki po 10 ms), enako kot iz Safeerja na Linuxu, zato ga naprava predvaja brez dekodiranja. Dolga tišina ne porablja omrežja.

- Zajem prek Windows WASAPI loopback (knjižnica soundcard, BSD-3, zaganjalnik jo namesti sam). Brez nje zaslon deluje kot prej, brez zvoka.
- Nova knjižnica, ki pride s posodobitvijo, se namesti takoj; prej je neuspel poskus z drugo knjižnico zadržal vse za 24 ur.
