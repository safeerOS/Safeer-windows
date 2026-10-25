# Safeer SDK za dodatke

Razvijaj dodatke za Medijski center Safeer v Safeer OS za Android (TV, tablica, telefon), Safeer za Linux in Safeer za
Windows. English version: [README.md](README.md).

Dodatek je **spletna storitev, ki vrača JSON**: [dodatek Stremio](https://github.com/Stremio/stremio-addon-sdk/blob/master/docs/protocol.md)
in po želji še razširitev `safeer` (gumbi, mape, nastavitve). Deluje v katerem koli jeziku in na katerem koli
strežniku. **Koda dodatka nikoli ne teče na uporabnikovi napravi** — Safeer vse nariše sam iz podatkov, ki jih vrneš.

Safeer ne priloži nobenega dodatka in nobenega ne priporoča: uporabniku le omogoči, da doda dodatke, ki jih izbere sam.
Za to, kar dodatek ponuja, je odgovoren njegov razvijalec (glej [Odgovornost](#odgovornost)).

- Protokol: [`docs/DODATKI-PROTOKOL.md`](../docs/DODATKI-PROTOKOL.md) (v1, angleško) in shema JSON
  [`docs/dodatki-protokol-v1.schema.json`](../docs/dodatki-protokol-v1.schema.json)
- Različica SDK: [CHANGELOG.md](CHANGELOG.md). Licenca: Apache-2.0 (datoteka `LICENSE` repozitorija).

## Vsebina

| Pot | Kaj |
|---|---|
| `templates/node/` | Predloga dodatka za Node.js 18+ (brez odvisnosti): katalog, meta, tok, dejanje, dopolnitev (enrich), mapa, nastavitve, 429 z `Retry-After`. |
| `templates/python/` | Ista predloga za Python 3.8+ (samo standardna knjižnica). |
| `python/check_addon.py` | Orodje za preverjanje: pove, kaj bo Safeer naredil s tvojim dodatkom — na vsakem računalniku s Pythonom 3.8+. |
| `python/safeer_addon.py` | Pravila protokola kot majhen modul Python (uporablja ga orodje; lahko ga uvoziš v svoje preizkuse). |
| `skupni-primeri/protokol-v1.json` | Skupni preizkusni primeri: aplikacije Safeer in ta SDK morajo vsak primer presoditi enako. |
| `primer/`, `orodja/`, `*.sh` | Samo v repozitoriju za Android: primer dodatka in orodje za preverjanje v Kotlinu, prevedena iz kode same aplikacije (Java 17 + `kotlinc`). |

## Hiter začetek (5 korakov)

1. **Kopiraj predlogo.** `sdk/templates/node/addon.mjs` ali `sdk/templates/python/addon.py`. Spremeni `id` (tvoja
   obrnjena domena; pozneje ga ne spreminjaj), `name`, `CATALOG` in iskanje tokov.
2. **Zaženi jo.** `node addon.mjs 7000` ali `python3 addon.py 7000` → `http://<IP tvojega računalnika>:7000/manifest.json`.
3. **Preveri jo.**
   ```bash
   python3 sdk/python/check_addon.py http://127.0.0.1:7000/manifest.json --dev --actions --lang sl
   ```
   Vrstice so `OK`, `INFO`, `OPOZORILO` ali `NAPAKA`; izhod 1 pomeni napako. `--content movie:tt0111161` preizkusi
   izbrano vsebino (sicer prvo iz kataloga), `--config kljuc=vrednost` pošlje nastavitve kot Safeer, krajevna datoteka
   (`check_addon.py manifest.json`) preveri manifest brez omrežja (npr. v tvojem CI).
4. **Preizkusi na napravi** (glej [Namestitev v Safeer](#namestitev-v-safeer)). Na Androidu vklopi razvojni način
   dodatkov, da lahko uporabiš `http://` v domačem omrežju.
5. **Objavi.** Gostuj na **https** (katero koli gostovanje ali obratni posrednik s TLS), znova preveri javni naslov in
   deli naslov manifesta ali povezavo `stremio://`. Ob vsaki spremembi povečaj `version` (semver) in dodaj vnos v
   `changelog` — uporabnik ga po posodobitvi vidi enkrat.

## Združljivost s Stremiom

- Vsak dodatek Stremio deluje v Safeerju nespremenjen: `manifest`, `catalog` (s `search`, `skip`, `genre`), `meta`
  (z `videos` za serije, id `<id>:<sezona>:<epizoda>`), `stream` (`url`, `infoHash` + `fileIdx`, `ytId`,
  `behaviorHints.proxyHeaders`), `subtitles`.
- Dodatek s ključem `safeer` deluje tudi v drugih odjemalcih Stremio; ključ prezrejo.
- Z uradnim Stremio SDK (`stremio-addon-sdk`, preverjeno z 1.6.10) ključ `safeer` ostane v manifestu. Končne točke
  `/safeer/...` postrezi poleg njegovega usmerjevalnika — primer kode je v [README.md](README.md#stremio-compatibility).

## Namestitev v Safeer

Uporabnik dodatke doda sam; Safeer pred shranitvijo preveri, ali manifest odgovori.

| Naprava | Kako |
|---|---|
| Safeer OS za Android (TV, tablica, telefon) | Medijski center → Moji viri → Dodatki → vnesi naslov (manifest, koren dodatka, njegovo stran `/configure` ali povezavo `stremio://`). V vgrajenem brskalniku Safeer gumb »Install« na strani dodatka (`stremio://…`, `web.stremio.com/#/addons?addon=…`, `…/manifest.json`) ponudi dodajanje, vedno s potrditvijo. **Razvojni način:** dolg pritisk na Dodatki → »Vklopi razvojni način dodatkov«; kartica »Razvoj dodatkov« v Mojih virih ima »Znova naloži dodatke« in »Dnevnik dodatkov« (brez poti, povezav tokov in vrednosti nastavitev). |
| Safeer za Linux | Medijski center → Dodatki in viri → Prilepi → Poveži. Povezave `stremio://` odprejo Safeer OS, ki počaka na Poveži. `http://` deluje v domačem omrežju. |
| Safeer za Windows | Medijski center → »Viri medijskega centra« → vrsta »Stremio dodatek (naslov manifest.json)« → naslov → »Poveži medijski strežnik« (enaka preverjanja kot na Linuxu). Safeer Player: ⚙ Dodatki. Povezave `stremio://` na Windows še niso registrirane — naslov kopiraj. |

Kaj posamezna platforma danes podpira: [protokol §10](../docs/DODATKI-PROTOKOL.md#10-support-per-platform). Na
kratko: del Stremio deluje povsod; razširitve `safeer` delujejo na Androidu (Linux in Windows jih zaenkrat prezreta in
uporabita del Stremio); Linux in Windows sprejmeta samo dodatke, ki ponujajo `stream`.

## Pravila za dodatke

1. **Povsod HTTPS** — manifest, končne točke, slike, tokovi. `http://` je samo za razvoj doma; Safeer za Linux in
   Windows ga zunaj domačega omrežja zavrne in nikoli ne sledi preusmeritvi s https na http.
2. **Skrivnosti ne v naslov.** Ključe zahtevaj s poljem `safeer.settings` vrste `type: "secret"`: Safeer vrednost
   shrani šifrirano na napravi, jo pošlje samo po HTTPS v glavi `X-Safeer-Config` in je nikoli ne pokaže ali zapiše v
   dnevnik. Ključa nikoli ne daj v poizvedbo — Safeer naslove z `?…`, `#…` ali `uporabnik:geslo@` odreže (Android) ali
   zavrne (Linux, Windows). Če mora dodatek nositi osebni žeton, ga daj v pot in uporabniku povej, naj ta naslov varuje
   kot geslo (šifrirana shramba takih naslovov: Android — v pripravi; Linux, Windows — načrtovano).
3. **Skrivnosti nikoli ne vračaj in ne beleži** — ne v sporočilih, imenih tokov, straneh z napakami ali dnevnikih
   strežnika. Beleži čim manj; poti lahko vsebujejo id-je in žetone.
4. **Debrid in torrente prepusti Safeerju.** Vrni `infoHash` (+ `fileIdx`, `sources`), namesto da uporabnika prosiš za
   ključ debrid. Safeer torrente predvaja prek uporabnikove lastne storitve debrid (njen ključ ostane šifriran na
   napravi) ali prek naprave Safeer v uporabnikovem domu, ki prenaša torrente — nikoli neposredno s telefona ali TV.
5. **Bodi vljuden pod obremenitvijo.** Ko potrebuješ premor, odgovori `429` z `Retry-After` (sekunde) — Safeer za
   Android dodatek počaka toliko, kolikor prosiš (sicer 15 minut, ob ponovitvi dvakrat dlje, do 2 ur). Za »tega nimam«
   uporabi `404`; `403` Safeer razume kot `429` (premor). `5xx` pomeni »ne odgovarja«. Glave predpomnjenja so dobrodošle.
6. **Ostani v mejah**, ki delujejo povsod: ≤ 5 MiB na odgovor (≤ 1 MiB za `/safeer/…`), odgovor v 6 s.
7. **Vsebino za odrasle označi** z `behaviorHints.adult: true`. Safeer take dodatke ohrani zasebne (ne na policah, v
   iskanju, zgodovini ali na drugih napravah).
8. **Brez obvodov DRM.** Ne izdeluj dodatkov, ki obidejo DRM ali druge tehnične zaščitne ukrepe; Safeer jih ne podpira.
9. **Povezava ni tok.** Safeer ne kaže povezav `externalUrl` (donacije, trgovine, klepeti), razen napovednikov na
   YouTubu; vsebina, ki ima samo take povezave, se skrije.
10. **Brez sledenja.** Safeer pošlje samo `Accept-Language`, `User-Agent` in `X-Safeer-Config`. Ne poskušaj
    prepoznati uporabnikov ali naprav prek tega, kar ti sami dajo v nastavitvah.
11. **Stalna istovetnost.** `id` nikoli ne spreminjaj; ob vsaki spremembi povečaj `version` (semver).

## Odgovornost

Safeer je platforma, ne ponudnik vsebin. Safeer ne priloži nobenega dodatka ter ne gosti, ne pregleduje, ne izbira, ne
priporoča in ne oglašuje nobenega dodatka ali ponudnika; nad tem, kaj dodatki vračajo, nima nadzora. Za dodatek je
odgovoren izključno njegov razvijalec — za vsebino, ki jo navaja ali na katero povezuje, za pravice do nje in za
skladnost z zakoni v vseh državah, kjer je dodatek na voljo. Uporabnik sam izbere, katere dodatke namesti, in jih
uporablja na lastno odgovornost. Združljivost s Safeerjem ali uspešno preverjanje z orodjem tega SDK ne pomeni, da
Safeer dodatek podpira ali priporoča.

## Različice

- **Protokol** — `safeer.protocol` (celo število, zdaj `1`). Nove različice samo dodajajo polja; dodatek za starejšo
  različico deluje naprej.
- **SDK** — [CHANGELOG.md](CHANGELOG.md) (semver). Spremeni se, ko se spremenijo navodila, predloge ali orodje.

## Samo v repozitoriju za Android: primer in orodje v Kotlinu

`sdk/zazeni_primer.sh 7000` zažene primer dodatka v Kotlinu; `sdk/preveri_dodatek.sh <naslov manifesta> [--vsebina tip:id]
[--dejanja]` preveri dodatek s kodo same aplikacije za Android (izpis v slovenščini). Potrebna sta Java 17 in `kotlinc`
(`KOTLINC=/pot/do/kotlinc`, če ga ni v `PATH`).

## Za vzdrževalce Safeerja

Dokument protokola, shema in vse v `sdk/` razen datotek Kotlin za Android so **enaki v Android-tv, Safeer-linux in
Safeer-windows**. Seznam je `sdk/SKUPNO.sha256`; spremeni jih v vseh treh repozitorijih v istem krogu in posodobi
seznam (`sha256sum -c sdk/SKUPNO.sha256` iz korena repozitorija pokaže, kaj se razlikuje).

Preizkusi (iz korena repozitorija):

```bash
python3 -m unittest discover -s sdk/python -p "*_test.py"   # vsak repozitorij: primeri, orodje, predloge, kopije
tests/run_dodatki_sdk_tests.sh                               # Android-tv: tudi koda aplikacije proti primerom
```
