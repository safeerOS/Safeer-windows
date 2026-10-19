# Safeer OS za Windows 1.0.42

Utrditev po varnostni izdaji 1.0.41. Vsakdanje delo (Splet, medijski center, Safeer Link) se ne spremeni.

## Števec ščita ne more napihniti stran

Števec blokiranih oglasov in groženj v WebView2 je sprejemal sporočila iz same strani, zato bi jih stran lahko napihnila. Zdaj vsako sporočilo nosi enkratni žeton seje, ki ga stran ne pozna (`STEVEC_ZETON`), in sporočila z napačnim žetonom se zavržejo. Poleg tega števec omejuje hitrost: največ 50 dogodkov na sporočilo in 300 na minuto, kar je za še tako oglasno stran dovolj, ponarejevalcu pa ne dopušča napihovanja. Devet novih preizkusov (`windows/tests/test_stevec_zeton.py`).

## Brez receptov za posamezne strani

Odstranjen je vgrajeni recept za posamezno spletno mesto (Hookshot) v ščitu oglasov. Nasprotoval je našemu pravilu v CONTRIBUTING, da se vedenje ne prilagaja posameznim stranem; ščit zdaj temelji samo na seznamih filtrov. Preizkus (`tests/test_brez_receptov_za_strani.py`) pazi, da se to ne vrne.

## Preizkusi

Preizkusi, ki se zaženejo v CI, zdaj uporabljajo začasno mapo zunaj AppData, zato zaščita pri deljenju map ostane nespremenjena, preizkusi pa so zanesljivi.
