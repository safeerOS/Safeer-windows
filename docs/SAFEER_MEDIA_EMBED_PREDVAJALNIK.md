# Tehnična dokumentacija: Prikaz zunanjih Embed vsebin znotraj lastnega Safeer Media predvajalnika

## 1. Izvršni povzetek in arhitekturni koncept

Sodobne pretočne platforme (kot je vidbox.vc) same ne gostujejo terabajtov video datotek niti ne izvajajo neposrednega pretakanja (streaming) z lastnih strežnikov. Namesto tega uporabljajo tehniko **vdelave (embedding)** zunanjih predvajalnikov specializiranih ponudnikov (npr. **VidSrc**, **VidLink**, **SuperEmbed**, **EmbedSU**) prek standardnega HTML elementa `<iframe>`.

Ključni cilj Safeer Media arhitekture je zagotoviti **nativno, varno in enotno uporabniško izkušnjo**:
1. Uporabnik **nikoli ne zapusti Safeer OS** aplikacije.
2. Zunanji predvajalnik je popolnoma integriran v Safeer Media vmesnik.
3. Nad in okoli predvajalnika je nameščen **lasten Safeer OS UI** (izbira epizod, sezon, kakovosti, preklop strežnikov, gumb za zaprtje, status predvajanja).
4. Safeer Ščit (adblock in varnostni filter) samodejno preprečuje nezaželene popunderje, preusmeritve in sledilnike.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Safeer OS Glava: Naslov vsebine, leto, izbrana kakovost, [✕ Zapri]         │  ← Safeer UI
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ [Loading Overlay: "Nalaganje varnega predvajalnika..." (z-index 5)] │   │  ← Safeer UI
│   ├─────────────────────────────────────────────────────────────────────┤   │
│   │                                                                     │   │
│   │                         <iframe>                                    │   │  ← Zunanji vir
│   │                   (VidSrc / VidLink / ...)                          │   │    (vdelano)
│   │                                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  Safeer OS Spodnja vrstica / Stranska plošča:                               │  ← Safeer UI
│  [⏮ Prejšnja] [⏸ Premor] [⏭ Naslednja] │ Strežnik: [VidLink ▾] [VidSrc]    │
│  Sezona: [1 ▾] Epizoda: [1] [2] [3] [4] [5]...                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Osnovni gradnik: HTML `<iframe>` in konfiguracija

Zunanja spletna stran ponudnika se vgradi v natančno dimenzioniran vsebnik. Tipičen primer kode, prilagojen za Safeer OS:

```html
<div class="safeer-embed-vsebnik" id="safeerEmbedVsebnik">
  <!-- Indikator nalaganja (Skeleton / Spinner) -->
  <div class="safeer-embed-nalagalnik" id="safeerEmbedNalagalnik">
    <div class="safeer-spinner"></div>
    <p>Nalaganje varnega predvajalnika …</p>
  </div>

  <!-- Vdelani zunanji predvajalnik -->
  <iframe
    id="safeerEmbedIframe"
    src="https://vidsrc.cc/v2/embed/tv/tt0944947/1/5"
    width="100%"
    height="100%"
    frameborder="0"
    allowfullscreen="true"
    webkitallowfullscreen="true"
    mozallowfullscreen="true"
    allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
    referrerpolicy="no-referrer"
    sandbox="allow-scripts allow-same-origin allow-forms allow-presentation"
    style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: none; background: #000000;">
  </iframe>
</div>
```

### Razlaga ključnih atributov:

| Atribut | Namen in varnostni pomen |
| :--- | :--- |
| `src` | URL zunanjega ponudnika z ustreznimi identifikatorji (npr. IMDb ID `tt0944947` ali TMDB ID, sezona, epizoda). |
| `width="100%"`, `height="100%"` | Zapolni celoten dodeljeni prostor predvajalnika. |
| `allowfullscreen` | Omogoča celozaslonski način znotraj samega predvajalnika brez zapuščanja strani. |
| `allow="autoplay; encrypted-media; picture-in-picture; fullscreen"` | Dovoljenja za samodejno predvajanje, dešifriranje DRM tokov in sliko v sliki (PiP). |
| `referrerpolicy="no-referrer"` | Preprečuje, da bi zunanji ponudnik prejel podatke o lokalnem naslovu ali referenčni strani aplikacije. |
| `sandbox` | Omejuje zmožnosti zunanjega skripta na varne operacije (glej razdelek 5). |
| `style="position: absolute; ..."` | Odpravi morebitne robove in omogoča popolno odzivno prilagajanje (16:9 razmerje). |

---

## 3. Kako dosežemo, da uporabnik "ne zapusti" aplikacije

Glavna težava zunanjih video ponudnikov so neželene preusmeritve (redirects) in odpiranje novih oken/zavihkov ob kliku na video element. Safeer Media uporablja večplastno zaščito:

### 1. Izolacija z absolutnim pozicioniranjem in `overflow: hidden`
- Zunanji predvajalnik je umeščen v vsebnik z razmerjem stranic 16:9 ali v celozaslonski način.
- Vsebnik ima `position: relative; overflow: hidden; border-radius: 12px;`.
- Zunanji elementi (glave, logotipi, pasice zunanje strani) se porežejo ali skrijejo, s čimer predvajalnik deluje kot integralni del Safeer OS.

### 2. Preprečevanje zunanjih povezav in popup oken
- **Odsotnost `allow-popups` in `allow-popups-to-escape-sandbox`**:
  Če iframe nima atributa `allow-popups`, brskalnik samodejno zavrne poskuse klica `window.open()` ali klikov na elemente s `target="_blank"`.
- **Prestrezanje na nivoju Safeer WebView / WebEngine**:
  V namizni aplikaciji Safeer OS (PySide6 / WebEngine ali WebView) se v kodi okna preusmeri vsaka zahteva za novo okno:
  ```python
  # Primer v Safeer OS oknu: onemogočanje neavtoriziranih zunanjih oken
  def createWindow(self, windowType):
      # Zavrni odpiranje oglasnih popup oken
      return None
  ```
- **Zadržanje URL-ja**:
  Naslovna vrstica in kontekst aplikacije ves čas ostaneta v domeni Safeer OS (`assets/os/index.html`).

---

## 4. Lastni uporabniški vmesnik (Safeer OS Custom UI Layer)

Okoli in nad iframe predvajalnikom Safeer Media prikazuje lasten UI, s katerim uporabnik upravlja vsebino:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ [← Nazaj]   Igra prestolov (S01E05: Volk in lev)          [Server: VidLink] │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│                                                                             │
│                              <IFRAME>                                       │
│                                                                             │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  Sezone in epizode:                                                         │
│  [Sezona 1]  [1] [2] [3] [4] [★ 5] [6] [7] [8] [9] [10]                      │
│  Izbira strežnika:                                                          │
│  (•) VidLink (Hitro, 1080p)  ( ) VidSrc (Rezerva)  ( ) SuperEmbed (Multi)   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Z-Index stratifikacija plasti:

1. **Plast 1 (`z-index: 1`) - Iframe Video Player**:
   Sam zunanji predvajalnik.
2. **Plast 2 (`z-index: 5`) - Loading Overlay**:
   Prikazuje se med inicializacijo in zbledi, ko je video pripravljen.
3. **Plast 3 (`z-index: 10`) - Safeer OS Kontrole**:
   - Glava predvajalnika (naslov, leto, žanr, gumb za zaprtje `✕`).
   - Nastavitve vira (izbirnik različic / strežnikov).
   - Vmesnik za serije (sezona/epizoda).
   - **Pomembno**: Za dele plasti, kjer uporabnik komunicira neposredno z video kontrolami (Play/Pause, časovnica znotraj iframe-a), se uporabi `pointer-events: none` na prozornem ozadju in `pointer-events: auto` na konkretnih Safeer gumbih.

---

## 5. Dvosmerna JavaScript komunikacija (`window.postMessage`)

Nekateri vodilni ponudniki (zlasti **VidLink**) podpirajo varno dvosmerno komunikacijo prek standardnega protokola `window.postMessage`.

### 1. Poslušanje dogodkov iz iframe predvajalnika
Safeer Media posluša sporočila iz predvajalnika za samodejno beleženje napredka in skrivanje nalagalnika:

```javascript
window.addEventListener("message", function (event) {
  // Preveri izvor ali tip dogodka
  var data = event.data;
  if (!data) return;

  // Če ponudnik pošilja JSON niz, ga razčleni
  if (typeof data === "string") {
    try { data = JSON.parse(data); } catch (e) { return; }
  }

  // Prepoznava napredka predvajanja (VidLink / standardni postMessage)
  if (data.type === "MEDIA_DATA" || data.event === "timeupdate" || data.action === "playback") {
    var currentTime = data.currentTime || (data.data && data.data.currentTime) || 0;
    var duration = data.duration || (data.data && data.data.duration) || 0;

    // Skrij indikator nalaganja, saj se video že predvaja
    var loader = document.getElementById("safeerEmbedNalagalnik");
    if (loader) loader.classList.add("skrit");

    // Shranjevanje pozicije za "Nadaljuj z ogledom" (če je več kot 5 sekund)
    if (currentTime > 5 && duration > 0) {
      shraniNapredekOgleda(trenutniMediaId, currentTime, duration);
    }
  }

  // Detekcija konca predvajanja (avtomatski preklop na naslednjo epizodo)
  if (data.event === "ended" || data.type === "PLAYER_ENDED") {
    predvajajNaslednjoEpizodo();
  }
});
```

### 2. Pošiljanje ukazov v iframe (Play, Pause, Seek)
Iz lastnih Safeer OS gumbov lahko pošiljamo ukaze zunanjemu predvajalniku:

```javascript
function posljiUkazVEmbed(ukaz, parametri) {
  var iframe = document.getElementById("safeerEmbedIframe");
  if (!iframe || !iframe.contentWindow) return;

  iframe.contentWindow.postMessage({
    source: "safeer_os",
    action: ukaz, // npr. "pause", "play", "seek"
    params: parametri || {}
  }, "*");
}
```

---

## 6. Napredne tehnike zanesljivosti in varnosti

### A. Odzivno oblikovanje (Responsive 16:9 Aspect Ratio)
Za zagotovitev brezhibnega prikaza na vseh napravah (računalnik, prenosnik, TV zaslon ali telefon):

```css
.safeer-embed-vsebnik {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9; /* Sodobni CSS standard za video razmerje */
  max-height: 80vh;
  background-color: #000000;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.45);
}

.safeer-embed-vsebnik iframe {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  border: none;
}
```

### B. Loading Overlay brez belega prebliska ("Zero White Flash")
Privzeti `<iframe>` elementi imajo pogosto belo ozadje med nalaganjem DOM-a. Rešitev:
1. Iframe element ima vgrajen inline stil `background: #000000;`.
2. Nad iframe se postavi Safeer OS Loading Overlay z enakim temnim ozadjem (`#0d1117`) in Safeer logotipom/spinnerjem.
3. Ob dogodku `iframe.onload` ali prvem `postMessage` sporočilu se overlay zmehčano umakne (`opacity: 0; pointer-events: none; transition: opacity 0.3s ease;`).

### C. Varnostni Sandbox profil
Sandbox atribut natančno določa, kaj skripta znotraj iframe-a sme početi:

```html
sandbox="allow-scripts allow-same-origin allow-forms allow-presentation"
```
- `allow-scripts`: Nujno potrebno za zagon video predvajalnika (HLS/DASH/video.js).
- `allow-same-origin`: Omogoča predvajalniku branje lastnih nastavitev piškotkov ali lokalne hrambe strežnika.
- `allow-presentation`: Omogoča preklop v celozaslonski način in AirPlay/Cast.
- **Onemogočeno (`allow-popups`, `allow-top-navigation`)**: Preprečuje zunanjemu predvajalniku, da bi klical neavtorizirana okna ali preusmeril glavno Safeer OS aplikacijo!

### D. Kaskadni samodejni preklop virov (Cascading Fallback Watchdog)
Če izbrani zunanji strežnik ne deluje (npr. odstranjen posnetek, 404, blokada domene ali predolgo nalaganje), Safeer Media ne prikaže praznega zaslona, ampak samodejno preklopi na naslednji razpoložljivi vir:

```javascript
var mediaWatchdogTimer = null;
var trenutniIndeksVira = 0;

function zazenEmbedPredvajalnik(viri, indeks) {
  trenutniIndeksVira = indeks || 0;
  var aktivniVir = viri[trenutniIndeksVira];
  if (!aktivniVir) {
    prikaziNapakoVira("Nobeden od razpoložljivih virov ni dosegljiv.");
    return;
  }

  var iframe = document.getElementById("safeerEmbedIframe");
  iframe.src = aktivniVir.url;

  // Počisti prejšnji nadzorni časovnik
  if (mediaWatchdogTimer) clearTimeout(mediaWatchdogTimer);

  // Watchdog: če v 9 sekundah ni potrditve predvajanja, poskusi rezervni vir
  mediaWatchdogTimer = setTimeout(function () {
    if (trenutniIndeksVira + 1 < viri.length) {
      console.warn("Vir ni odgovoril v roku, preklapljam na rezervni vir...");
      obvesti("Strežnik " + aktivniVir.ime + " se ne odziva. Preklapljam na naslednji vir...");
      zazenEmbedPredvajalnik(viri, trenutniIndeksVira + 1);
    }
  }, 9000);
}
```

### E. Integracija s Safeer Ščitom (Adblock & Threat Shield)
Zunanji iframe predvajalniki pogosto poskušajo nalagati zunanje oglasne mreže ali analitiko. Safeer Ščit (`core/adblock.py`, `core/threat_intel.py`, `core/os_scit.py`) že na nivoju operacijskega sistema ali lokalnega DNS proxyja prestreže in zablokira:
- Domene oglasnih posrednikov (popads, adsterra, monetag itd.).
- Zlonamerne skripte in botnet klicatelje.
Uporabnik tako dobi popolnoma čist predvajalnik brez reklamnih prekinitev.

---

## 7. Primer strukturiranega JSON kataloga za Safeer Media

V Safeer Media nastavitvah lahko uporabnik ali vir zagotovi JSON seznam, ki vsebuje tako neposredne tokove kot tudi zunanje embed vire z več rezervnimi strežniki:

```json
{
  "name": "Moj Safeer Media Katalog",
  "items": [
    {
      "title": "Igra prestolov",
      "type": "serija",
      "year": 2011,
      "season": 1,
      "episode": 5,
      "description": "Ned išče razloge za smrt Jon Arryna, medtem ko Robert načrtuje napad na Daenerys.",
      "poster": "https://image.tmdb.org/t/p/w500/u3bZgnGQ9T01sWNhyveQz0wH0Hl.jpg",
      "sources": [
        {
          "name": "VidSrc (Hitro)",
          "url": "https://vidsrc.cc/v2/embed/tv/tt0944947/1/5",
          "kind": "embed",
          "quality": "1080p"
        },
        {
          "name": "VidLink (Backup 1)",
          "url": "https://vidlink.pro/tv/1399/1/5",
          "kind": "embed",
          "quality": "1080p"
        },
        {
          "name": "SuperEmbed (Backup 2)",
          "url": "https://multiembed.mov/?video_id=tt0944947&s=1&e=5",
          "kind": "embed",
          "quality": "Auto"
        }
      ]
    },
    {
      "title": "Klub golih pesti (Fight Club)",
      "type": "film",
      "year": 1999,
      "poster": "https://image.tmdb.org/t/p/w500/pB8BM7pdSp6B6Ih7QZ4DrQ3PmJK.jpg",
      "sources": [
        {
          "name": "VidSrc VIP",
          "url": "https://vidsrc.cc/v2/embed/movie/tt0137523",
          "kind": "embed",
          "quality": "1080p"
        },
        {
          "name": "VidLink HD",
          "url": "https://vidlink.pro/movie/550",
          "kind": "embed",
          "quality": "1080p"
        }
      ]
    }
  ]
}
```

---

## 8. Zaključek

S to arhitekturo Safeer Media doseže:
1. **Brezhibno uporabniško izkušnjo**: Video se predvaja kot domača komponenta Safeer OS brez odpiranja brskalnika ali ločenih oken.
2. **Popolno varnost**: Strogi sandbox in Safeer Ščit preprečujeta pojav oglasov, popup oken ali nevarnih preusmeritev.
3. **Visoko zanesljivost**: Samodejni kaskadni nadzornik (watchdog) takoj preklopi na rezervni strežnik, če primarni odpove.
4. **Enostavno vzdrževanje**: Širitev na nove ponudnike zahteva le dodajanje URL predloge v katalog brez potrebe po spreminjanju video predvajalnika.
