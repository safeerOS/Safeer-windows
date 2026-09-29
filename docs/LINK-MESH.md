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
