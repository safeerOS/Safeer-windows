# Safeer OS za Windows 1.0.36

- **Safeer OS se namesti na stalno mesto.** Program se ob namestitvi sam prepiše v svojo mapo; ikona na namizju in vnos v meniju Start kažeta tja. Preneseno datoteko `SafeerOS-Windows-….exe` lahko po prvem zagonu pobrišeš ali premakneš. Prej je ikona kazala na preneseno datoteko in je ostala mrtva, ko si to pobrisal.
- **Safeer OS je v meniju Start.** Če ikono z namizja pobrišeš, se ob posodobitvi ne vrne.
- **Hitrejši zagon.** Safeer OS se odpre skoraj sekundo prej: od klika do zagona programa je prej minila približno sekunda, zdaj približno 0,15 sekunde. Preverbo potrebnih knjižnic, ki je tekla pred vsakim zagonom, program opravi sam med zagonom, 80 MB velikega paketa pa zaganjalnik ne preverja več ob vsakem zagonu.
- **Po posodobitvi se Safeer OS zanesljivo odpre.** Nova različica je ob prevzemu od stare lahko obvisela brez okna, stara pa se je medtem zaprla – Safeer OS po posodobitvi ni tekel, dokler ga nisi odprl znova.
- **Starejša prenesena datoteka ne povozi novejše različice.** Če odpreš starejši preneseni `SafeerOS-Windows-….exe`, zažene različico, ki je nameščena. Prej je brez opozorila vrnil staro. Velja za datoteke od te različice naprej.
- **Posodobitve ne puščajo več namestitvenih datotek.** Vsaka posodobitev je v mapi programa pustila 84 MB. Zdaj se pobrišejo same, tudi tiste od prej; prekinjen prenos posodobitve ne pusti delne datoteke.
- **Safeer Link: povezava z drugimi napravami pod obremenitvijo ne pada več.** Ob večjem prometu med napravami se je povezava prekinila in vzpostavljala znova, sporočila na poti pa so se izgubila.
- Napaka ob počasnem zagonu se pokaže z opisom. Prej je Safeer OS ostal brez okna in brez sporočila.
- Dnevnik `safeer_os.log` se ob vsakem zagonu ne prepiše več; ponoven klik na ikono je prej izbrisal sled programa, ki je že tekel.

English: **Safeer OS now installs itself to a fixed location.** The desktop icon and the new Start menu entry point there, so the downloaded file can be deleted after the first start. Start-up is almost a second faster: the check of required libraries that ran before every start is now done by the app itself, and the launcher no longer hashes the 80 MB package on every start. After an update Safeer OS now reliably opens: the new version could hang without a window while taking over from the old one. An older downloaded file no longer overwrites a newer installation. Updates no longer leave installers behind (84 MB each), and an interrupted download leaves no partial file. Safeer Link connections to other devices no longer drop under load.
