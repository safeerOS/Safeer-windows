# Safeer OS Windows 1.0.4-test4

Ta testna izdaja dokonča uporabniški tok Safeer Media v enotni aplikaciji Safeer OS.

- Uporabnik v **Nastavitve → Tvoji viri** enkrat vnese `https://vidlink.pro`; vir ni samodejno dodan.
- Podvojeni spletni naslov je zavrnjen.
- TMDb zagotovi enoten katalog, posterje, ocene, iskanje, žanre, sezone in epizode.
- VidLink prejme pravilen TMDb ID: `/movie/{tmdbId}` oziroma `/tv/{tmdbId}/{season}/{episode}`.
- Film ali epizoda se odpre v celozaslonskem predvajalnem sloju Safeer Media znotraj Safeer OS, brez zunanjega brskalnika.
- Neposredne datoteke in tokove še naprej predvaja vgrajeni LibVLC.
- Safeer Control, Safeer Link in 6-mestna povezovalna koda ostanejo del istega okna Safeer OS.

Preverjeno: **112 testov in 10 podtestov uspešnih**. TMDb katalog in dokumentirani VidLink naslov sta bila preverjena tudi z resničnim omrežnim odzivom.

## Namestitev

1. Razširi celoten ZIP.
2. Dvoklikni `install.bat` (ne zaganjaj ga iz druge mape).
3. Za diagnostiko lahko zaženeš `PREIZKUSI-SAFEER.ps1 -Launch`.

## Odstranitev

V celotnem ZIP-u sta priložena `uninstall.bat` in `uninstall.ps1`. Enaki datoteki sta tudi v ločenem paketu `SafeerOS-Odstranitev.zip`.
