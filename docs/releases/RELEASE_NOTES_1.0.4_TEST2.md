# Safeer OS za Windows 1.0.4-test2

Ta preizkusna izdaja dokonča ključne povezave med Safeer OS, Safeer Link, Safeer Control in Safeer Media.

## Kaj je novega

- Safeer Control je vgrajen pogled istega okna in istega procesa Safeer OS.
- Spletne povezave iz Controla se odprejo v vgrajenem Safeer Browserju, ne v zunanjem brskalniku.
- Delujejo pošiljanje URL-ja, besedila in datoteke, vzdevki naprav ter deljenje izoliranega Safeerjevega navideznega zaslona.
- Standardne uporabniške mape se dodajo samo enkrat; podvojene poti se preskočijo.
- Ob prvi povezavi nove naprave Safeer vpraša za profil: **Poln dostop** (vsi diski, datoteke, aplikacije in upravljanje), **Izbrane datoteke** ali **Samo zaslon**.
- Dovoljenja so shranjena za vsako napravo posebej in jih je mogoče kadarkoli spremeniti.
- Prenovljena domača stran jasno združi splet, aplikacije, datoteke, naprave in Media.
- Safeer Media ima nov kinematografski katalog, enotno iskanje, združevanje po IMDb/TMDb identiteti in izbor najboljšega vira.
- Dodan je `PREIZKUSI-SAFEER.ps1` za preverjanje nameščene aplikacije na Windows računalniku.

## Preverjanje

- 107 avtomatiziranih testov: uspešno.
- JavaScript sintaksa: uspešno.
- PowerShell parser: uspešno.
- Vizualni pregled domače strani in Safeer Media: uspešno.

Za namestitev razširite celoten ZIP v eno mapo in dvokliknite `install.bat`.
