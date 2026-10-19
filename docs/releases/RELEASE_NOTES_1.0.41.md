# Safeer OS za Windows 1.0.41

Varnostna izdaja. Po več krogih je neodvisni pregled kode (8. 10. 2026) našel spodnje težave; vse so popravljene, vsaka ima preizkus, glavna najdba pregleda samih popravkov (F1 – svežina posodobitev) pa je bila popravljena in ponovno preverjena pred objavo. Vsakdanje delo (Splet, medijski center, Safeer Link) se ne spremeni, razen kot je zapisano spodaj.

## Posodobitve: podpisan seznam, obvezna vsota in zaščita pred vračanjem nazaj

Preverjanje posodobitev v programu zaupa seznamu različic na safeer.si šele, ko je pristen **in svež**.

- **Podpisan seznam različic.** `razlicice.json` je podpisan s ključem Ed25519 (`razlicice.json.sig` z istega gostitelja); seznam brez veljavnega podpisa se zavrne.
- **Vsota je obvezna.** Paket se prenese samo z veljavnim 64-mestnim SHA-256 iz podpisanega seznama; manjkajoča ali napačna vsota preverjanja ne izklopi več. Samo HTTPS.
- **Brez vrnitve na starejšo različico.** Podpisan seznam nosi podpisan čas izdaje in veljavnosti (`izdano`, `potece`). Program zavrne potekel seznam in vsak seznam, starejši od najnovejšega, ki ga je že videl. S tem je zaprt napad, pri katerem bi nekdo, ki upravlja gostitelja (ne pa našega podpisnega ključa), ponudil pristen **starejši** seznam in računalnik zadržal pri znani ranljivi različici.

## Deljene mape in »ves disk« ne izdajo več map programov

- Deljena mapa in »ves disk« ne pokažeta in ne izročita map **AppData** (ključi in žetoni programov), sistemskih map in registrskih panjev – tudi če je tja usmerjena sama deljena mapa.
- Poti **UNC** (`\\strežnik\…`) ter `\\?\` in `\\.\` se zavrnejo v celoti: pri UNC sistemska mapa ni prva komponenta za črko diska, razrešitev poti pa bi segla v omrežje.

## Seznanitev s kodo QR: celoten prstni odtis potrdila

Koda QR zdaj nosi celoten 64-mestni prstni odtis potrdila, naprava, ki jo prebere, ga primerja v celoti (prej le prvih 16 znakov).

## Preizkusi

Preizkusi na pravem Windowsu (deljenje map, UNC, pretok datotek, predaja predvajanja) so zeleni; zaščita AppData je preverjena tudi na pravi poti pod `%LOCALAPPDATA%`.
