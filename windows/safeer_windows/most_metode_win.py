"""Metode mostu, ki jih zaledje Safeer OS na Windows izvede samo - za zmoznosti() skupnega dispecerja
(core/os_most_metode.py): vmesnik (assets/os/most.js, ima()) skrije gumb za metodo, ki je tu ni.

Zamrznjen SafeerOS.exe nima izvorne kode, zato seznama ni mogoce sestaviti ob zagonu (ast). Ustvarjen 25. 10. 2026 s
scripts/most_pregled.py; windows/tests/test_most_metode_win.py pade, ce se ne ujema z os_app.py / namizje_win.py /
namizje_qml.py - nova metoda v zaledju gre tudi sem.
"""

#: Okno Safeer OS (os.js): os_app._izvedi_metodo, _sporocila, _magnet_metoda.
HTML = frozenset({
    "browserClearData", "browserSettingsGet", "browserSettingsSet", "cakajociMagnet", "celozaslonsko", "control",
    "daljinec", "datotekeNaprave", "diski", "dvdPogoni", "dvdPredvajaj", "isciDatoteke", "iskanjeSplet", "jbl",
    "kopiraj", "magnetDeliNaprej", "magnetDodaj", "magnetIzDatoteke", "magnetMapa", "magnetNaNapravo",
    "magnetNadaljuj", "magnetNaprave", "magnetOdstrani", "magnetPovezava", "magnetPreberi", "magnetPredvajaj",
    "magnetPremor", "magnetPrenesiProgram", "magnetPrivzeto", "magnetProgram", "magnetSeznam", "mapa",
    "mediaDebrid", "mediaDodajMapo", "mediaDodajNaSeznam", "mediaDodajStreznik", "mediaDodajVir", "mediaEpizoda",
    "mediaFilm", "mediaImaKodi", "mediaIsciPredpomnilnik", "mediaIzvoziJson", "mediaKatalog", "mediaKnjiznica",
    "mediaKnjiznicaObdrzi", "mediaKnjiznicaOdstrani", "mediaKnjiznicaPredvajaj", "mediaNaKodi", "mediaNaZvocnik",
    "mediaNaprave", "mediaOdkrijDlna", "mediaOdstraniSSeznama", "mediaOdstraniSeznam", "mediaOdstraniVir",
    "mediaOsveziVir", "mediaPodrobnosti", "mediaPredvajaj", "mediaSeznam", "mediaSeznamZamenjava", "mediaSeznami",
    "mediaSezona", "mediaStanje", "mediaUvoziJson", "mediaUvoziSeznam", "mediaWatchCountry", "mediaWatchSettings",
    "mediaZvocnikDejanje", "mediaZvocniki", "mediaZvrsti", "namizje", "namizjeSafeer", "namizjeWindows",
    "napajanje", "napraveSDatoteki", "napraveSProgrami", "nastaviDovoljenje", "nastaviTemo", "nastavitve",
    "nazajVMint", "nazajVWindows", "nedavne", "novaNaprava", "oddaljeniZaslon", "odjava", "odlozisceBeri",
    "odpriDatoteko", "odpriDatotekoNaprave", "odpriDatotekoTukaj", "odpriTukaj", "odpri_url", "odprtaOkna",
    "omrezje", "podnapisVtt", "pokaziVMapi", "posljiDatoteko", "posodobi", "posodobitveStanje", "povezava",
    "predajaPoizvedi", "predajaPrevzemi", "predajanje", "predvajajDatotekoNaprave", "preimenujNapravo",
    "prenesiDatotekoNaprave", "prijava", "priklopiDisk", "pripni", "programi", "programiNaprave", "prostorOdpri",
    "prostori", "samozagon", "scit", "scitVklop", "shraniNedavneApp", "shraniSpletne", "sistemPodatki",
    "skrijDomov", "skrijStransko", "splet", "spletNotranji", "sporocilaDodaj", "sporocilaIsci", "sporocilaIsciPri",
    "sporocilaIzbrisi", "sporocilaIzbrisiPogovor", "sporocilaNaprave", "sporocilaOdstrani", "sporocilaOsebe",
    "sporocilaOznake", "sporocilaPogovor", "sporocilaPonudniki", "sporocilaPoslji", "sporocilaPreimenuj",
    "sporocilaRazdruzi", "sporocilaSeznam", "sporocilaSinhroniziraj", "sporocilaSkrivnost", "sporocilaStreznik",
    "sporocilaZacni", "sporocilaZdruzi", "stanje", "vrniSplet", "vseNaprave", "zacetek", "zapisekDobi",
    "zapisekIzbrisi", "zapisekShrani", "zapiskiSeznam", "zapriSplet", "zaupanje", "zazeni", "zazeniNaNapravi",
    "zvok"})

#: Delovna povrsina (delovna.html, namizje_win.py): HTML + namizje_win.metode.
DELOVNA = HTML | frozenset({
    "dock", "dockRazvrsti", "govorStanje", "igreOblak", "izprazniSmeti", "izvrziNosilec", "kavcCelZaslon",
    "lastnostiDatoteke", "lupaUcenje", "lupaZapomni", "najvecjeDatoteke", "napraveZDatotekami",
    "napraveZaPosiljanje", "nastavitveDocka", "nastavitveOzadja", "nosilci", "novaDatoteka", "novaMapa",
    "obnoviIzSmeti", "odpriRazdelek", "odpriVBrskalniku", "odpriZ", "ok", "plank", "podprto", "ponudnikiProgramov",
    "posljiNapravi", "predlogeDatotek", "preimenujDatoteko", "prilepiDatoteke", "privzeti", "privzetiBrskalnik",
    "programiZaDatoteko", "programiZaOdpiranje", "prostorDiska", "razveljaviDatoteke", "sistemskeNastavitve",
    "sliciceDatotek", "smeti", "spletNaNamizju", "spremljajMapo", "spusceneDatoteke", "vSmeti",
    "videzCinnamonNastavi", "viriProgramov", "zacniVlecenje"})

#: Namizje QML (namizje_qml.izvedi): DELOVNA + metode namizja QML.
QML = DELOVNA | frozenset({
    "besedilaProstorov", "bliznjice", "diskiNamizja", "napraveNamizja", "nastaviVidezNamizja", "programiNamizja",
    "programiNapraveNamizja", "sliciceNamizja", "videzNamizja"})
