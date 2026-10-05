# Safeer Link Mesh (mesh1) — res decentralizirano

Stanje 29. 9. 2026. Veja `link-mesh` v Android-tv, Safeer-linux, Safeer-windows (in pozneje Mobile-android).

## Zakaj

Danes je zaupanje že decentralizirano (vsaka naprava hrani cel podpisan krog), nadzorna pot pa ne:
naprave izvolijo **en** hub (`IzvolitevHuba`), vse druge se umaknejo in se povežejo nanj. Če hub
ugasne, se Link za ~7–90 s podre, naprave se prerazporedijo, telefon in tablica pa izgubita
računalnik, ki je ves čas prižgan. Hub je ena točka odpovedi in ena točka, skozi katero gre vse.

## Pravilo mesh1

1. **Vsaka naprava je vozlišče.** Vsaka naprava s Safeer Linkom gosti svoj hub, vedno (brez
   izvolitve in brez umika). Njene aplikacije (Safeer OS, sprejemnik, Control) se prijavijo na
   **svoj** hub (lokalno).
2. **Vozlišča se povežejo neposredno, vsako z vsakim.** Hub A se poveže na hub B iz kroga zaupanja
   (mDNS oglas + ključ v potrdilu = ključ člana v krogu) z obstoječo prijavo s podpisom
   (`/cast/auth/challenge` → `/cast/auth/ticket` → WebSocket). Na eni strani je to navaden odjemalec
   z `role: "hub"` in zmožnostjo `mesh1`; od tu naprej je povezava simetrična (**sosednja povezava**).
   Klice obe strani; če nastaneta dve povezavi za isti par, ostane tista, ki jo je odprl manjši id.
3. **Sosedje si izmenjajo samo svoje lokalne naprave** (`mesh.devices`). Hub vsako napravo soseda
   vpiše v svoj register kot **oddaljeno napravo** z namestnikom povezave (proxy): pošiljanje nanjo
   se ovije v `mesh.route` in gre sosedu, ta ga dostavi svoji lokalni napravi. Vse obstoječe
   usmerjanje (`cast.*`, `share.*`, `control.*`, `chat.*`, `data.*`, `internet.*`, `handoff.*`,
   oddaje brez cilja) zato deluje brez sprememb.
4. **Brez zank.** Sosed nikoli ne posreduje naprej (samo lokalnim napravam) in v `mesh.devices`
   nikoli ne navede oddaljenih naprav ali sosedov. Oddaja brez cilja doseže vsako napravo natanko
   enkrat: lokalne neposredno, oddaljene prek njihovega huba.
5. **Lokalna registracija ima prednost.** Če se naprava prijavi tudi neposredno (stari odjemalec),
   velja neposredna povezava; oddaljeni zapis istega id se prezre.
6. **Izpad vozlišča podre samo njegove naprave.** Ko sosednja povezava pade, hub odstrani vse
   njegove oddaljene naprave in objavi nov `cast.devices`. Drugi pari tečejo naprej.
7. **Naslov naprave zunaj njene naprave ni nikoli zanka** (5. 10. 2026). Aplikacija, ki se prijavi
   na hub svoje naprave, ima pri njem naslov `127.0.0.1`. Ta naslov velja samo na tisti napravi: kdor
   ga dobi drugje, se z njim poveže sam nase (telefon je namesto zaslona računalnika klical svoja
   vrata). Zato:
   - **sosedom** (`mesh.devices`, izvoz): hub namesto zanke zapiše svoj naslov na poti do tistega
     soseda (vsakemu sosedu svojega – krajevni konec sosednje povezave);
   - **od sosedov** (uvoz): zanko ali prazen `ip` sosedove naprave hub zamenja z naslovom, na
     katerem teče sosedov hub (drugi konec sosednje povezave);
   - **svojim odjemalcem** (`cast.devices`): odjemalec z iste naprave dobi zanko (po njej prepozna
     procese svoje naprave); odjemalec od drugod – vmesnik telefona je lahko pripet na hub druge
     naprave – dobi naslov huba na poti do njega. Polje `here: true` pove, da je naprava na napravi
     huba, ne glede na to, kateri naslov je odjemalec dobil (po njem odjemalec ve, kako je hubu ime);
   - **odjemalec** zanko od huba, ki teče drugje, bere kot naslov tistega huba – tako dela tudi s
     starejšim hubom.
   Dovolj je, da pravilo upošteva ena stran – starejše različice pošiljajo `127.0.0.1`. Prek releja
   (Global Link) naslova ni: `ip` je prazen in odjemalec neposredne povezave (slika zaslona) ne
   poskuša, temveč pove, da ta deluje samo v istem omrežju. Naprava, ki je pri hubu prijavljena iz
   omrežja, obdrži svoj naslov.
8. **Naprava, ki ponuja neposredno povezavo, svoje naslove našteje sama** (5. 10. 2026). Naslov v
   seznamu naprav pripiše hub; napravi, ki jo vidi samo posredno, ga lahko pripiše narobe (pravilo 7
   je nastalo po taki napaki). Računalnik zato v odgovoru na `screen.start` poleg `port`, `fp` in
   `token` vrne `hosts` – svoje naslove IPv4, najverjetnejši najprej, največ štiri, brez zanke
   (isti seznam kot v `audio.play`):
   - naslov na poti do huba, kadar hub teče drugje;
   - naslovi vmesnikov krajevnega omrežja, tisti na privzeti poti prvi (vmesniki vsebnikov in
     navideznih strojev ne štejejo);
   - naslov na privzeti poti in naslovi predorov (VPN) nazadnje – računalnik, ki ves promet pošilja
     skozi VPN, bi sicer napravi v istem omrežju povedal samo naslov predora.

   Gledalec poskusi **najprej naslov iz seznama naprav, nato naštete**: vsakega enkrat, skupaj
   največ štiri, vsakega največ 4 s, kadar jih je več (računalnik čaka 30 s). Iz `hosts` vzame samo
   naslove IPv4 (štiri desetiška števila brez vodilnih ničel), ki niso zanka (127.x), 0.x ali 224 in
   več; imena gostitelja ne razrešuje. Povezavo sprejme samo, če se potrdilo ujema z odtisom iz
   odgovora, in enkratni žeton pošlje šele po tem – naprava na napačnem naslovu ga ne vidi. Ko pravo
   napravo najde, so napake končne (drugih naslovov ne poskuša več).

   Star računalnik `hosts` ne pošlje in gledalec dela kot prej; star gledalec polje prezre. Naprave
   brez naslova v seznamu gledalec še vedno ne prosi (pravilo 7).

9. **Kar hub posreduje sam – datoteko in zaslon – pošiljatelj odda hubu ciljne naprave** (5. 10. 2026).
   Pot v `share.file` (`/cast/file/<id>?k=…`) in pot gledalca v `share.screen`
   (`/cast/screen/<id>/view?k=…`) sta relativni na hub, ki je vsebino sprejel, in se čez sosede ne
   preneseta. Zato:
   - **datoteka**: pošiljatelj jo odda (`PUT /cast/file`) hubu ciljne naprave, prijavljen s sejo s
     podpisom (`/cast/auth/challenge` → `/cast/auth/ticket`), kot sosednja povezava. Hub oddajo zavrne
     (409 `naprava_pri_drugem_srediscu`), če je cilj pri sosedu. Prejemnik datoteko poišče **najprej
     pri svojem hubu, nato pri pošiljateljevem** – iz sporočila se ne vidi, kateri jo ima; naslednji
     pride na vrsto samo, če prejšnji odgovori 404, vsaka druga napaka je končna
     (`link_deljenje.prevzemi_pri_srediscih`). Do 1.0.97 je Safeer Control na Linuxu vprašal samo
     pošiljateljev hub in datoteka z drugega računalnika je ostala v zalogi njegovega huba.
   - **zaslon**: pošiljatelj začne deljenje (`POST /cast/share/screen/start`) pri hubu ciljne naprave
     z isto sejo in tja potiska okvirje; ta hub svoji napravi pove, kje je gledalec
     (`link_deljenje.sredisce_za_zaslon`). Hub računalnika zaslona ne posreduje: naprava, ki je
     prijavljena neposredno nanj, dobi `zaslon_ni_na_voljo`. Do 1.0.97 (Linux) in 1.0.38 (Windows) je
     bil cilj deljenja hub računalnika in »Zaslon« na plošči »Deli z« ni deloval.

   Zaupanje je isto kot pri sosednji povezavi: ključ v potrdilu huba mora biti ključ člana kroga
   (`link_mesh.sredisce_naprave`).

## Sporočila (novo)

```
mesh.devices   {type, id, payload: {hub: <device_id huba>, devices: [<zapis kot v cast.devices>]}}
mesh.route     {type, id, payload: {to: <lokalni id pri sosedu>, msg: "<surovo sporočilo>"}}
mesh.trust     {type, id, payload: <krog json>}     (zdruzi s preverjanjem podpisov, brez odmeva)
```

- `mesh.route`: prejemnik preveri, da je `to` njegova **lokalna** naprava, in ji pošlje `msg`
  nespremenjen (pošiljatelja je vpisal hub, ki ga je sprejel od svoje naprave). Največ 1 MiB.
- Hub sprejme `mesh.*` samo od povezave, prijavljene z `role: "hub"` in podpisom člana kroga.
- `mesh.trust`: vsak hub krog po spremembi pošlje sosedom; sosed združi (`zdruzi(preveriPodpise)`)
  in ga razpošlje svojim napravam samo, če se je spremenil.

## Kaj se ne spremeni

- Seznanitev (SPAKE2, QR, 6-mestna koda) pri kateremkoli hubu; `pair.code` doseže vse zaslone prek
  oddaljenih zapisov.
- Neposredne seje (zaslon, programi, datoteke računalnika, Data Transport) — že tečejo mimo huba.
- Rele link.safeer.si za internet (samo šifrirano).

## Znane meje v1

- Dostava prek vmesnega vozlišča (narejeno 29. 9.): `mesh.devices` nosi še `relay` = naprave
  NEPOSREDNIH sosedov (z `hub`). Kdor do take naprave nima svoje poti, jo vpiše kot posredno in ji
  pošilja `mesh.route` z `relay: true`; vmesni Hub preda naprej samo napravi svojega neposrednega soseda
  in samo v imenu naprave, ki je lokalna pri prosilcu. Največ en vmesni skok, brez zank; neposredna pot
  ima vedno prednost, ob njenem izpadu promet takoj steče prek vmesnega (in obratno).
- `share.file` prek huba (stari telefonski rele): pot `path` velja na hubu pošiljatelja; oddaljeni
  prejemnik dobi še `hub_address` in `hub_fp`. Stari prejemniki tega ne poznajo — zato novi pošiljatelji
  uporabljajo neposredno pot (Protocol v1).
- Kategorije `sync.*` se hranijo na hubu, ki jih je sprejel.
- Klepet, ki čaka na nepovezano napravo, hrani hub pošiljatelja in ga dostavi, ko se cilj pojavi
  lokalno **ali prek soseda**.

## Global Link: soseda zunaj doma (narejeno 29. 9.)

- Vsak Hub se objavi na `link.safeer.si` (AgentHuba: `/v1/presence` s seznamom `allow` = člani kroga,
  `/v1/listen`, kanal `/v1/accept` → lokalni Hub). Rele prenaša samo šifrirane bajte; TLS s pripetim
  ključem iz kroga in prijava s podpisom sta enaka kot v LAN. Tujec ne izve niti, ali Hub obstaja.
- Kdor kliče soseda: najprej neposredno (mDNS ali zapomnjeni naslov). Po **2 zaporednih** neuspelih
  klicih (brez odgovora ali napačen ključ) pokliče prek releja (`LokalniRele` / `GlobalLink.naslov`):
  lokalna vrata `127.0.0.1:x` → kanal `/v1/connect?to=<id iz ključa>`. Zavrnitev (`cast.ack rejected`)
  ni neuspeh — sosed je dosegljiv.
- Cilj releja je id iz ključa člana (Hub se lahko oglaša s pripono, npr. `n-…-control`).
- Po neuspehu prek releja premor 60 s, podvaja se do 10 min (dnevna kvota Workerja).
- Naslov `127.*` / `::1` / `localhost` si nikoli ne zapomnimo kot naslov soseda (to je lokalni konec releja
  ali dohodni kanal releja).
- Izklop: `SAFEER_GLOBAL_LINK=0` (računalnik) / nastavitev »Dostop do mojih naprav od kjerkoli« (Android).
  Preizkus doma: `SAFEER_MESH_RELE=id1,id2` (računalnik) / »Preizkus: tudi doma prek interneta« (Android).
- Znana meja: povezava prek releja ostane, dokler deluje; ko se naprava vrne domov, preide na LAN šele ob
  naslednjem ponovnem priklopu.
- Popravek ob tem: kanal releja in sosednja povezava vtičnico ob koncu samo `shutdown`, zapre pa jo šele,
  ko je nobena nit ne uporablja več. Prej je druga nit (OpenSSL) brala že zaprto številko vtičnice, ki jo je
  sistem dal naslednjemu kanalu → `WRONG_VERSION_NUMBER` (4 od 10 prijav prek releja; po popravku 25/25).

## Združljivost

- Hub z mesh1 sprejema stare odjemalce kot doslej.
- Star hub (brez mesh1) sosednje povezave ne razume (`neznan_tip`); nov hub ga zato ne kliče kot
  soseda, ampak se tja (dokler ga ne posodobimo) poveže po starem kot odjemalec.
- Izvolitev ostane samo za stare naprave; nove se ne umikajo.

## Preizkusi

- Enotski (brez omrežja): trije hubi A–B–C s pravimi `obdelaj`: seznam na vsakem vsebuje vse,
  usmerjanje s ciljem, oddaja natanko enkrat, izpad B odstrani samo B-jeve naprave, lokalna prednost,
  `mesh.route` na nelokalno napravo zavrnjen, `mesh.*` od ne-huba zavrnjen, klepet čaka in se dostavi
  ob pojavu prek soseda, krog se razširi brez odmeva.
- V živo: Linux, TV, testni telefon, Windows — vsaka vidi vsako; ugasnemo TV → ostali se vidijo
  naprej brez prekinitve; ugasnemo računalnik → isto.
