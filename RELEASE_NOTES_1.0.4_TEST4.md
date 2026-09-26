# Safeer OS Windows 1.0.4-test4

Ta testna izdaja dokonča uporabniški tok Safeer Media v enotni aplikaciji Safeer OS.

- Uporabnik v **Nastavitve → Tvoji viri** enkrat vnese `https://vidlink.pro`; vir ni samodejno dodan.
- Podvojeni spletni naslov je zavrnjen.
- TMDb zagotovi enoten katalog, posterje, ocene, iskanje, žanre, sezone in epizode.
- VidLink prejme pravilen TMDb ID: `/movie/{tmdbId}` oziroma `/tv/{tmdbId}/{season}/{episode}`.
- Film ali epizoda se odpre v celozaslonskem predvajalnem sloju Safeer Media znotraj Safeer OS, brez zunanjega brskalnika.
- Neposredne datoteke in tokove še naprej predvaja vgrajeni LibVLC.
- Safeer Control, Safeer Link in 6-mestna povezovalna koda ostanejo del istega okna Safeer OS.
- Namestitveni program na 64-bitnem Windows preveri dejansko nalaganje `libvlc.dll` in po potrebi namesti 64-bitni VLC.
- Na Namizju je samo ena bližnjica **Safeer OS**; Media, Link, Control in splet so pogledi istega programa.

Preverjeno: **114 testov in 10 podtestov uspešnih**. TMDb katalog, dokumentirani VidLink naslov, šestmestna koda in 64-bitni LibVLC so bili preverjeni tudi na testnem Windows računalniku.

## Namestitev

1. Razširi celoten ZIP.
2. Dvoklikni `install.bat` (ne zaganjaj ga iz druge mape).
3. Za diagnostiko lahko zaženeš `PREIZKUSI-SAFEER.ps1 -Launch`.

## Odstranitev

V celotnem ZIP-u sta priložena `uninstall.bat` in `uninstall.ps1`. Enaki datoteki sta tudi v ločenem paketu `SafeerOS-Odstranitev.zip`.
