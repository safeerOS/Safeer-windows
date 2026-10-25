/* Safeer Cinnamon - delovna povrsina (iskanje, predvajalnik, datoteke, programi naprav).
 *
 * Vse podatke da Safeer OS prek mosta window.SafeerOS.klic(metoda, argumenti) - iste metode kot glavna
 * stran (mapa, nedavne, isciDatoteke, napraveZDatotekami, datotekeNaprave, napraveSProgrami,
 * programiNaprave, zazeniNaNapravi, odpriTukaj, knjiznicaMedijev, predvajalnikStanje ...).
 * Stran si ne izmislja naprav, datotek ali programov: kar most ne vrne, se ne prikaze.
 */
(function () {
  "use strict";

  // ------------------------------------------------------------------ most
  var most = window.SafeerOS || null;
  function klic(metoda, argumenti) {
    if (!most) return Promise.reject("brez mosta");
    return Promise.resolve(most.klic(metoda, argumenti || []));
  }
  function $(id) { return document.getElementById(id); }
  function el(oznaka, razred, besedilo) {
    var e = document.createElement(oznaka);
    if (razred) e.className = razred;
    if (besedilo != null) e.textContent = besedilo;
    return e;
  }

  // ------------------------------------------------------------------ besedila (SL, EN)
  var BESEDILA = {
    sl: {
      mikrofonNaslov: "Išči z glasom", govorPoslusam: "Poslušam … povej, kaj iščeš", govorPrepoznavam: "Prepoznavam …", govorTisina: "Nisem slišal ničesar. Pritisni mikrofon in povej znova.", govorNiPodprto: "Iskanje z glasom na tem računalniku ni na voljo.", govorMikrofon: "Mikrofona ni mogoče odpreti.", govorNapaka: "Prepoznava govora ni uspela.", govorNamestiNaslov: "Iskanje z glasom", govorNamestiOpis: "Govor se prepozna na tem računalniku – nič ne gre na splet. Za to je treba enkrat prenesti prepoznavo govora ({mb} MB).", govorPrenesi: "Prenesi", govorNeZdaj: "Ne zdaj", govorPrenasam: "Prenašam prepoznavo govora … {o} %", govorPrekini: "Prekini", govorPrenosNapaka: "Prenos ni uspel. Poskusi znova.", govorPreklici: "Prekliči", govorKoncaj: "Končaj",
      iskanjePh: "Išči po spletu, programih, datotekah in medijih …", iskanjePhKratko: "Išči programe, datoteke, splet …", iskanjePhKrajse: "Išči programe in splet …", iskanjePhNajkrajse: "Išči …", iskanjeNamig: "Enter odpre označeno · Shift+Enter splet",
      plosceNaslov: "Plošče", medijiNaslov: "Medijski center", datotekeNaslov: "Datoteke", programiNaslov: "Programi",
      zamenjajStrani: "Zamenjaj levo in desno", ponastavi: "Privzeta postavitev", vecjiTekst: "Večje besedilo", velikostBesedila: "Velikost besedila", tekst200: "200 % – za ogled od daleč",
      manjProsojnosti: "Manj prosojnosti", spletVBrskalniku: "Iskanje po spletu v privzetem brskalniku", spletVBrskalnikuIme: "Iskanje po spletu v brskalniku {ime}", sistemNaslov: "Namizje in sistem", modulTeme: "Tema, ikone in kazalec …", modulOzadja: "Sistemska ozadja …", modulPisave: "Pisave …", modulZaslon: "Zaslon …", modulOkna: "Okna …", modulPult: "Pult …", modulNocna: "Nočna svetloba …", modulVse: "Vse nastavitve sistema …", skrijPlosco: "Skrij ploščo", pokaziPlosco: "Pokaži ploščo {ime}", spremeniVelikost: "Povleci za spremembo velikosti (puščice s tipkovnico)",
      odpriMedijskiCenter: "Odpri Medijski center", niPredvajanja: "Ni predvajanja",
      medijNavodilo: "Izberi glasbo ali video v Datotekah ali v Medijskem centru.",
      medijIskanjePh: "Išči glasbo, radio, filme in serije …", medijIskanjeVse: "Vsi zadetki za »{q}« v Medijskem centru",
      medijIskanjeIscem: "Iščem …", medijTokovi: "Programi postaje:", medijIskanjeSe: "Iščem še po virih …", medijIskanjeNic: "Ni zadetkov.", medijTaRacunalnik: "Ta računalnik",
      prejsnja: "Prejšnja", premor: "Predvajaj / premor", naslednja: "Naslednja",
      predvaja: "Predvaja", vPremoru: "Premor", ustavljeno: "Ustavljeno", napakaPredvajanja: "Predvajanje ni uspelo",
      filterPh: "Filtriraj …", filterPrgPh: "Išči programe …", vseVrste: "Vse vrste", vrstaDokument: "Dokumenti",
      vrstaSlika: "Slike", vrstaVideo: "Video", vrstaZvok: "Glasba", vrstaMapa: "Mape",
      en_mapa: "Mapa", en_dokument: "Dokument", en_slika: "Slika", en_video: "Video", en_zvok: "Zvok", en_arhiv: "Arhiv",
      en_program: "Program", en_splet: "Splet", en_drugo: "Drugo",
      stIme: "Ime", stVrsta: "Vrsta", stLokacija: "Lokacija", stVelikost: "Velikost", stSpremenjeno: "Spremenjeno",
      pregled: "Pregled", nedavno: "Nedavno", priljubljeno: "Priljubljeno", mape: "Mape", naprave: "Naprave",
      taRacunalnik: "Ta računalnik", domov: "Domača mapa",
      DOCUMENTS: "Dokumenti", PICTURES: "Fotografije", VIDEOS: "Videi", MUSIC: "Glasba", DOWNLOAD: "Prenosi", DESKTOP: "Namizje",
      nalagam: "Nalagam …", praznaMapa: "Mapa je prazna.", niZadetkov: "Ni ustreznih datotek.",
      niNedavnih: "Še ni nedavnih datotek.", niPriljubljenih: "Še nimaš priljubljenih. Desni klik na datoteko ali mapo → Dodaj med priljubljene.",
      niMape: "Mape ni več.", niDovoljenja: "Do te mape nimaš dovoljenja.",
      napravaNeOdgovori: "Naprava trenutno ni dosegljiva. Podatki niso prikazani, da ne bi bili zastareli.",
      napravaNeDeli: "Naprava ne deli datotek. Na njej v Safeer Linku vklopi deljenje datotek.",
      napravaOsvezeno: "osveženo ob {cas}", oddaljeno: "na napravi {naprava}",
      odpri: "Odpri", pokaziVMapi: "Pokaži v mapi", dodajPriljubljeno: "Dodaj med priljubljene",
      odpriZ: "Odpri z …", privzetProgram: "privzeto", drugProgram: "Drug program …",
      vednoSTem: "Vedno odpri to vrsto datotek s tem programom", niProgramaZaVrsto: "Za to vrsto datotek ni nastavljenega programa.",
      odslejZ: "Od zdaj se ta vrsta datotek odpira s programom {ime}.",
      odstraniPriljubljeno: "Odstrani iz priljubljenih", predogled: "Predogled", zapri: "Zapri",
      odpiramNaNapravi: "Z naprave predvajam le glasbo in video. Druge datoteke odpri na sami napravi.",
      niUspelo: "Ni uspelo.", strani: "{a}–{b} od {n}", nazaj: "‹", naprej: "›",
      kVse: "Vse", kPisarna: "Pisarna", kUstvarjanje: "Ustvarjanje", kMediji: "Mediji", kSplet: "Splet", kIgre: "Igre",
      kDrugo: "Drugo", kPriljubljeni: "★ Priljubljeni",
      oblak: "Oblak", oblakOpis: "Igre tečejo na strežnikih ponudnika {ponudnik}; potrebuješ njihov račun.",
      oblakNamesti: "Namesti (uradni paket {ponudnik})", oblakVec: "Več o storitvi",
      ppGumb: "Namesti programe …", ppNaslov: "Od kod želiš nameščati programe?",
      ppUvod: "Izberi ponudnika programov. Safeer nobenega ne priporoča – po abecedi so, nič ni privzeto.",
      ppOdpri: "Odpri", ppNamesti: "Namesti", ppNamescam: "Nameščam …", ppVec: "Več", ppNamesceno: "nameščeno",
      ppGeslo: "vpraša za geslo", ppKoncano: "{ime} je nameščen.", ppNapaka: "{ime} se ni namestil.",
      ppPreklicano: "Namestitev je preklicana.", ppPrazno: "Seznama ponudnikov ni bilo mogoče prebrati.",
      ppIme_gnome_software: "GNOME Programi", ppIme_mintinstall: "Upravitelj programov",
      ppOpis_bazaar: "Programi iz Flathuba.", ppOpis_discover: "KDE-jev center programov (paketi sistema in Flatpak).",
      ppOpis_gearlever: "Programi AppImage: namesti, posodablja in pospravi.",
      ppOpis_gnome_software: "GNOME-ov center programov (paketi sistema in Flatpak).",
      ppOpis_snap_store: "Programi Snap. Linux Mint ima Snap izklopljen; z »Omogoči« ga vklopiš (vidiš vsak korak).",
      ppOpis_mintinstall: "Center programov Linux Mint (paketi sistema in Flathub).",
      ppZavihekPonudniki: "Ponudniki", ppZavihekViri: "Viri", ppZavihekGithub: "GitHub", ppOmogoci: "Omogoči",
      ppKorak_nosnap: "Odstrani Mintovo zaporo Snapa (/etc/apt/preferences.d/nosnap.pref)", ppKorak_snapd: "Namesti paket snapd",
      ppKorak_snap_store: "Namesti Snap Store",
      ppVirSnap: "Vir: Snapcraft (Canonical) · za ves računalnik · sistem vpraša za geslo",
      ppPosSnap: "Posodobitve: Snap programe posodablja sam (lastnost Snapa). Zadržiš jih z ukazom »snap refresh --hold«.",
      ppViriUvod: "Viri, iz katerih se na tem računalniku nameščajo programi. Dodaš lahko svojega: PPA ali repozitorij Flatpak.",
      ppViriPh: "ppa:ime/ppa ali https://…/vir.flatpakrepo", ppViriDodaj: "Dodaj vir", ppViriPrazno: "Ni virov.",
      ppViriNeveljaven: "To ni PPA (ppa:ime/ppa) ali naslov https://…/ime.flatpakrepo.",
      ppViriPpa: "Dodan bo PPA {vir} za ves računalnik · sistem vpraša za geslo.",
      ppViriFlatpak: "Dodan bo repozitorij Flatpak »{ime}« ({vir}) · samo za tvojega uporabnika · brez gesla.",
      ppViriOpozorilo: "Safeer programov iz tega vira ne preverja. Dodaj samo vir, ki mu zaupaš.",
      ppViriDodan: "Vir je dodan.", ppViriNapaka: "Vira ni bilo mogoče dodati.",
      ppZaUporabnika: "za tvojega uporabnika", ppZaSistem: "za ves računalnik",
      ppGhUvod: "Javni repozitoriji na GitHubu in datoteke njihovih izdaj. Shraniš jih v mapo, ki jo izbereš; Safeer jih ne preverja in ne namesti sam.",
      ppGhMapa: "Shrani v: {pot}", ppGhSpremeni: "Spremeni …", ppGhIzberiMapo: "Kam shranim programe in datoteke?",
      ppGhIsciPh: "Išči repozitorij (npr. localsend)", ppGhIsci: "Išči", ppGhIscem: "Iščem …", ppGhNic: "Ni zadetkov.",
      ppGhIzdaje: "Izdaje", ppGhNazaj: "Rezultati", ppGhBrezIzdaj: "Ta repozitorij nima izdaj.", ppGhBrezDatotek: "Brez datotek.",
      ppGhPredizdaja: "predizdaja", ppGhArhiviran: "arhiviran", ppGhPrenosov: "{n}× preneseno", ppGhShrani: "Shrani",
      ppGhShranjujem: "Shranjujem …", ppGhShranjeno: "Shranjeno: {ime}", ppGhNiMape: "V izbrano mapo ni mogoče pisati.",
      ppGhVse: "Vse", ppGhZaTaKratko: "Ta računalnik", ppGhDrugo: "Drugo", ppGhDrugaLicenca: "druga licenca", ppGhNiZaNas: "V teh izdajah ni datoteke za ta računalnik (Linux).",
      ppZvrst_mediji: "Mediji", ppZvrst_ustvarjanje: "Ustvarjanje", ppZvrst_pisarna: "Pisarna", ppZvrst_splet: "Splet",
      ppZvrst_komunikacija: "Komunikacija", ppZvrst_igre: "Igre", ppZvrst_razvoj: "Razvoj", ppZvrst_sistem: "Sistem in orodja",
      ppZvrst_varnost: "Varnost in zasebnost", ppZvrst_drugo: "Drugo",
      ppGhZaTa: "za ta računalnik", ppAptVir: "skladišče paketov · za ves računalnik",
      ppGhShranjenoPreverjeno: "Shranjeno in preverjeno (SHA-256 z GitHuba): {ime}",
      ppGhKontrolna: "Prenesena datoteka se ne ujema s SHA-256 z GitHuba, zato je nisem shranil.",
      ppGhNapaka: "GitHub zdaj ne odgovarja. Poskusi pozneje.", ppGhOmejitev: "GitHub omejuje število iskanj brez prijave. Poskusi čez minuto.",
      ppPreverjam: "Preverjam, kaj se bo namestilo …", ppKajSe: "Namestilo se bo:", ppOkolje: "okolje, ki ga program potrebuje",
      ppVirFlatpak: "Vir: Flathub · samo za tvojega uporabnika · brez gesla · prenos {mb} MB",
      ppVirApt: "Vir: skladišča {vir} · za ves računalnik · sistem vpraša za geslo · prenos {mb} MB",
      ppPosSamo: "Posodobitve: v Upravitelju posodobitev imaš vklopljene samodejne posodobitve, zato se bo posodabljal sam. To spremeniš v nastavitvah Upravitelja posodobitev.",
      ppPosRocno: "Posodobitve: ponudi jih Upravitelj posodobitev; namestijo se šele, ko jih potrdiš.",
      ppPotrdi: "Namesti", ppPreklici: "Prekliči", ppNiPodatkov: "Podatkov o namestitvi ni bilo mogoče prebrati, zato ne namestim.",
      oblakNamescam: "Nameščam {ime} iz uradnega vira {ponudnik}. To lahko traja nekaj minut …",
      oblakNamesceno: "{ime} je nameščen. Najdeš ga med Igrami.", oblakZeNamescam: "Namestitev že teče.",
      oblakNapaka_vir: "Uradnega vira ni bilo mogoče dodati. Preveri povezavo z internetom.",
      oblakNapaka_namestitev: "Namestitev ni uspela. Poskusi znova.", oblakNapaka_prostor: "Na disku ni dovolj prostora za namestitev.",
      oblakNapaka_ni_zdruzljivo: "Ta računalnik ne izpolnjuje zahtev.",
      oblakZdruzljivo: "Ta računalnik izpolnjuje zahteve.", oblakPoskusi: "Lahko poskusiš: {razlog}", oblakNe: "Ne bo delovalo: {razlog}",
      oblakRazlog_osnova: "{sistem} ni na uradnem seznamu, a ima isto osnovo kot podprti {osnova}",
      oblakRazlog_sistem: "{sistem} ni na uradnem seznamu ponudnika", oblakRazlog_ram: "premalo pomnilnika (potrebno {potrebno} GB)",
      oblakRazlog_jedra: "premalo procesorskih jeder (potrebni {potrebno})", oblakRazlog_arhitektura: "potreben je 64-bitni procesor x86",
      oblakRazlog_flatpak: "Flatpak ni nameščen",
      kopiraj: "Kopiraj", izrezi: "Izreži", prilepi: "Prilepi", prilepiV: "Prilepi v to mapo", lastnosti: "Lastnosti",
      kopirajN: "Kopiraj ({n})", izreziN: "Izreži ({n})", vSmetiN: "Premakni v Smeti ({n})", obnoviN: "Obnovi ({n})",
      izbranoN: "Izbrano: {n}", pocistiIzbiro: "Prekliči izbiro", izberiVse: "Izberi vse",
      delnoUspelo: "Narejeno: {ok}, ni uspelo: {ne}.", premaknjenoV: "Premaknjeno v »{mapa}«: {ime}", kopiranoV: "Kopirano v »{mapa}«: {ime}",
      vSmetiVecOk: "V Smeteh: {ime} (obnoviš jih v Datotekah → Smeti).", obnovljenoN: "Obnovljeno: {ime}",
      kopirano: "Kopirano: {ime}. Prilepiš z desnim klikom ali Ctrl+V.", izrezano: "Izrezano: {ime}. Prilepiš z desnim klikom ali Ctrl+V.",
      kopiram: "Kopiram …", premikam: "Premikam …", prilepljeno: "Kopirano sem: {ime}", premaknjeno: "Premaknjeno sem: {ime}",
      prilepiNapaka_vase: "Mape ni mogoče kopirati vase.", prilepiNapaka_ni_prostora: "Na disku ni dovolj prostora.",
      prilepiNapaka_ni_dovoljenja: "V to mapo ni mogoče pisati.", prilepiNapaka_ni_datoteke: "Izvirne datoteke ni več.",
      prilepiNapaka_ni_dovoljeno: "Tega ni mogoče kopirati ali premakniti.", prilepiNapaka_ni_mape: "Ciljne mape ni več.",
      smeti: "Smeti", praznoSmeti: "Smeti so prazne.", obnovi: "Obnovi", obnovljeno: "Obnovljeno: {ime}",
      izprazniSmeti: "Izprazni Smeti …", smetiIzpraznjene: "Smeti so izpraznjene.",
      izvrzi: "Varno odstrani", izvrzeno: "{ime} lahko odklopiš.", izvrziZaseden: "{ime} je še v uporabi. Zapri datoteke z njega in poskusi znova.",
      prostoNa: "{prosto} prosto od {skupaj}",
      lVrsta: "Vrsta", lVelikost: "Velikost", lKje: "Mesto", lSpremenjeno: "Spremenjeno", lPravice: "Pravice", lVsebuje: "Vsebuje",
      lElementov: "{n} elementov", lPovezava: "Kaže na",
      niPriljubljenihPrg: "Še nimaš priljubljenih programov. Klikni ☆ na programu in tukaj ga boš vedno hitro našel.",
      vseNaprave: "Vse naprave", razvrstiIme: "Po imenu", razvrstiNaprava: "Po napravi",
      pogledSeznam: "Seznam / mreža", spletnaAplikacija: "V brskalniku",
      odpriTukaj: "Odpri tukaj (zaslon naprave na tem računalniku)", zazeniNaNapravi: "Zaženi na napravi",
      kategorija: "Kategorija: {k}", popraviKategorijo: "Premakni v kategorijo",
      niNaprav: "Programi drugih naprav se pokažejo, ko napravo dodaš v Safeer Linku (Safeer Control).",
      niProgramov: "V tej kategoriji ni programov.", napravaNedosegljiva: "{naprava}: ni dosegljiva", napraveNedosegljive1: "{n} naprava ni dosegljiva", napraveNedosegljive2: "{n} napravi nista dosegljivi", napraveNedosegljive3: "{n} naprave niso dosegljive", napraveNedosegljive5: "{n} naprav ni dosegljivih",
      brezControla: "Safeer Link (Safeer Control) ne teče, zato programi naprav niso na voljo.",
      zagonPoslan: "Ukaz poslan napravi {naprava}.",
      skSplet: "Splet", skProgrami: "Programi", skNastavitve: "Nastavitve", skProgramiNaprav: "Programi naprav", skDatoteke: "Datoteke", skMediji: "Mediji", skPrikaziNa: "Prikaži na", prikaziNaVrsta: "Prikaži »{kaj}« na: {ime}", prikazanoNa: "Odpira se na {ime}: {kaj}", izberiNapravo: "Izberi, na kateri napravi naj se prikaže.", niNapraveCilja: "V Safeer Linku ni take naprave.", napravaNeZna: "{ime} tega še ne zna – posodobi Safeer na njej.",
      skZapiski: "Zapiski", skSafeer: "Safeer OS", ciljMedia: "Medijski center", ciljNaprave: "Naprave (Safeer Link)", ciljScit: "Ščit – zaščita za ves računalnik",
      ciljNastavitve: "Nastavitve Safeer OS", ciljZapiski: "Zapiski", ciljSporocila: "Sporočila", ciljSplet: "Splet v Safeer OS",
      odpreSafeerOs: "odpre Safeer OS", odprePredvajalnik: "odpre Safeer Player",
      skNaprave: "Naprave", napravaDatoteke: "datoteke na napravi", napravaProgrami: "programi naprave",
      isciVMedijih: "Poišči »{q}« v Medijskem centru", odpreMedijski: "filmi, serije, glasba, radio",
      posljiNaNapravo: "Pošlji na napravo …", posNiNaprav: "V Safeer Linku ni naprave, ki bi sprejela datoteko.",
      posPosiljam: "Pošiljam napravi {naprava}: {ime} … {odst} %",
      posPosiljamN: "Pošiljam napravi {naprava} ({k} od {n}): {ime} … {odst} %",
      posPoslano: "Poslano napravi {naprava}: {ime}", posPoslanoN: "Poslano napravi {naprava}: {n}", 
      posNapaka: "Pošiljanje napravi {naprava} ni uspelo: {razlog}.",
      posN_naprava_ni_povezana: "naprava ni povezana",
      posN_sredisce_ne_zna: "središče tega še ne zna – posodobi Safeer na napravi, ki je središče",
      posN_naprava_pri_drugem_srediscu: "naprava je povezana prek drugega središča",
      posN_stari_control: "Safeer Control je treba zagnati znova (teče starejša različica)",
      posN_ni_controla: "Safeer Control ne teče", posN_hub_ni_znan: "ta računalnik ni povezan v Safeer Link",
      posN_prazna_mapa: "mapa je prazna", posN_prevec_datotek: "preveč datotek naenkrat (največ {najvec})",
      posN_prevelika: "datoteka je večja od 4 GB", posN_ni_prostora: "ni dovolj prostora za datoteko",
      posN_naprava_zasedena: "z napravo trenutno deli druga naprava", posN_ni_datoteke: "datoteke ni več",
      posN_naprava_ni_seznanjena: "ta računalnik pri središču ni prijavljen",
      posN_sredisce_naprave_ni_dosegljivo: "naprava v tem omrežju ni dosegljiva", posN_posiljanje_ni_uspelo: "povezava je bila prekinjena",
      isciVSpletu: "Išči »{q}« v spletu", odpreVBrskalniku: "rezultati tukaj na namizju", isciem: "Iščem …",
      prostor: "{n} el.",
      spremeniOzadje: "Spremeni ozadje …", prilagodiDock: "Uredi dock …",
      dockDodaj: "Dodaj v dock", dockOdstrani: "Odstrani iz docka", dockNaslov: "Dock", dockDodajProgram: "Dodaj program …",
      dockGor: "Premakni gor", dockDol: "Premakni dol", dockPrazen: "V docku ni programov.", dockVecNastavitev: "Več nastavitev docka …",
      dockIsci: "Poišči program …", dockBrezPlanka: "Dock (Plank) ni nameščen.", dockOpis: "Vrstni red spremeniš s puščicama; ikone lahko tudi povlečeš kar na docku.",
      dockDodano: "{ime} je v docku.", dockOdstranjeno: "{ime} ni več v docku.", nazaj: "Nazaj",
      dockNamig: "Program dodaš v dock z desnim klikom na program › Dodaj v dock ali v Uredi dock.",
      linkPovezan: "Safeer Link · {n}", linkPovezanBrez: "Safeer Link · povezano",
      linkPovezi: "Poveži se v Safeer Link", linkNaslov: "Safeer Link: tvoje naprave (odpre Safeer Control)",
      naprav1: "1 naprava", naprav2: "2 napravi", naprav34: "{n} naprave", napravN: "{n} naprav",
      novoNaslov: "Nova mapa ali datoteka", novaMapa: "Nova mapa …", novaDatoteka: "Nova datoteka",
      vPrazna: "Prazna datoteka …", vBesedilo: "Besedilna datoteka …", vDokument: "Dokument …",
      vPreglednica: "Preglednica …", vPredstavitev: "Predstavitev …", vPredloga: "Predloga: {ime} …",
      oknoMapa: "Nova mapa", oknoDatoteka: "Nova datoteka", oknoPreimenuj: "Preimenuj",
      privzetoMapa: "Nova mapa", privzetoDatoteka: "Nova datoteka", privzetoDokument: "Nov dokument",
      privzetoPreglednica: "Nova preglednica", privzetoPredstavitev: "Nova predstavitev",
      novoIme: "Ime", novoVrsta: "Vrsta", novoKje: "Kje", novoSpremeni: "Spremeni …", preklici: "Prekliči",
      ustvari: "Ustvari", preimenuj: "Preimenuj", preimenujMeni: "Preimenuj …", vSmeti: "Premakni v Smeti",
      shraniNaNapravo: "Shrani na drugo napravo …", shrPripravljam: "Pripravljam »{ime}« (preverjam vsebino) …",
      shrPrenasam: "Naprava {naprava} shranjuje »{ime}« … {odst} %", shrKopijaNaslov: "Kopija je shranjena in preverjena",
      shrKopija: "»{ime}« je zdaj tudi na napravi {naprava}, v mapi {kje}. Kopija je preverjena – vsebina je enaka izvirniku.",
      shrVprasaj: "Izbrišem izvirnik na tem računalniku? Sprosti se {velikost}.", shrIzbrisi: "Izbriši izvirnik",
      shrObdrzi: "Obdrži oboje", shrIzbrisano: "Izvirnik je izbrisan. »{ime}« najdeš na napravi {naprava} ({kje}).",
      shrObdrzano: "Obdržano oboje: izvirnik je tu, kopija na napravi {naprava}.",
      shrNiNaprave: "Nobena naprava v Safeer Linku ta trenutek nima dovolj prostora ali ne more pomagati (baterija, zasedenost).",
      shrSpremenjena: "Datoteka se je medtem spremenila – izvirnika ne brišem. Shrani jo znova.",
      shrNapaka: "Shranjevanje na drugo napravo ni uspelo ({koda}).", shrZapri: "Zapri", shrPrenosi: "Prenosi",
      najvecje: "Največje datoteke", niVelikih: "Ni datotek, večjih od 100 MB.",
      pretvoriV: "Pretvori v …", ptdNaslov: "Pretvori »{ime}«", ptdIzberi: "V katero obliko? Izvirnik ostane.",
      ptdPretvarjam: "Pretvarjam »{ime}« v {cilj} …", ptdKoncano: "Shranjeno ob izvirniku kot »{izhod}« ({velikost}).",
      ptdNapaka: "Pretvorba ni uspela ({koda}).", ptdNiOrodja: "Za to vrsto datotek manjka program: {orodje}.",
      ptdNiMogoce: "Te datoteke ni mogoče pretvoriti.",
      ptdNiUspelo: "Te datoteke ni bilo mogoče pretvoriti – morda je poškodovana. Izvirnik je nespremenjen.",
      ptdPrepocasi: "Pretvorba je trajala predolgo in je bila ustavljena. Izvirnik je nespremenjen.",
      ptdNiDatoteke: "Datoteke ni več na tem mestu.",
      pretvori: "Pretvori za televizor (1080p) …", prvIscem: "Iščem napravo z najboljšim strojnim kodirnikom za »{ime}« …",
      prvPrenasam: "Naprava {naprava} prenaša »{ime}« … {odst} %", prvPretvarjam: "Naprava {naprava} pretvarja »{ime}« … {odst} %", prvPretvarjamTu: "Nobena naprava ne more pomagati, zato »{ime}« pretvarja ta računalnik … {odst} %",
      prvShranjujem: "Naprava {naprava} shranjuje pretvorjeni video …", prvKoncanoNaslov: "Video je pretvorjen",
      prvKoncano: "»{izhod}« ({velikost}) je na napravi {naprava}, v mapi {kje}. Predvaja ga vsak televizor. Izvirnik na tem računalniku ostane nespremenjen.",
      prvVprasaj: "Ga prenesem tudi na ta računalnik, zraven izvirnika?", prvPrenesi: "Prenesi na ta računalnik", prvPusti: "Pusti tam",
      prvNazaj: "Prenašam »{izhod}« na ta računalnik … {odst} %", prvNaRacunalniku: "»{izhod}« je zdaj tudi na tem računalniku, zraven izvirnika.",
      prvPusceno: "»{izhod}« ostane na napravi {naprava} ({kje}). Najdeš ga v Datotekah te naprave.",
      prvNeDeli: "Naprava {naprava} ne deli datotek, zato videa ne morem prenesti sem. Ostaja na napravi ({kje}).",
      prvNiNaprave: "Nobena naprava v Safeer Linku ta trenutek nima strojnega kodirnika za 1080p, dovolj prostora ali moči (baterija, zasedenost).",
      prvNapaka: "Pretvorba ni uspela ({koda}).",
      prvNeZna: "Nobena naprava v Safeer Linku ne zna prebrati tega videa (oblika ali ločljivost, npr. 4K HEVC). Izvirnik ostane nespremenjen.",
      pretvoriMapo: "Pretvori videe v mapi za televizor …", prvSkNaslov: "Pretvarjanje videov – vse naprave pomagajo",
      prvSkPoteka: "Pretvorjenih {opr} od {vseh}. Vsaka naprava pretvarja en video naenkrat in vzame naslednjega, ko konča – močnejša opravi več.",
      prvSkKoncano: "Pretvorjenih {opr} od {vseh} videov.", prvSkNapake: "{n} videov ni bilo mogoče pretvoriti ({koda}).",
      prvSkVprasaj: "Jih prenesem na ta računalnik, vsakega zraven izvirnika?", prvSkPrenesi: "Prenesi vse sem", prvSkPusti: "Pusti na napravah",
      prvSkNazaj: "Prenašam pretvorjene videe na ta računalnik …", prvSkNaRacunalniku: "Pretvorjeni videi so zdaj zraven izvirnikov ({n}).",
      prvSkPusceno: "Pretvorjeni videi ostanejo na napravah (Prenosi › Safeer Shramba).", prvSkDela: "pretvarja", prvSkNiVidea: "V tej mapi ni videov.",
      maloProstora: "Na računalniku je prostora le še {prosto}. Večje datoteke lahko shraniš na napravo v Safeer Linku – izvirnik izbrišeš šele, ko vidiš, kje je kopija.",
      pokaziNajvecje: "Pokaži največje datoteke",
      vSmetiOk: "»{ime}« je v Smeteh (obnoviš ga v Datotekah → Smeti).", ustvarjeno: "Ustvarjeno: {ime}",
      izberiMapoNaslov: "Kam naj ustvarim?", izberi: "Izberi", osvezi: "Osveži",
      razveljavi: "Razveljavi", razveljavljeno: "Razveljavljeno.", nicZaRazveljaviti: "Ni česa razveljaviti.",
      razveljavitevNiUspela: "Tega ni več mogoče razveljaviti (datoteka je bila medtem premaknjena ali je na njenem mestu druga).",
      preimenovano: "Preimenovano: {ime}",
      nObstaja: "Datoteka s tem imenom tu že obstaja.", nIme: "Ime ne sme biti prazno, začeti s piko ali vsebovati »/«.",
      nDovoljenje: "V to mapo nimaš dovoljenja za pisanje. Izberi drugo.", nMapa: "Te mape ni več.",
      nSmeti: "V Smeti ni šlo (morda nimaš dovoljenja).", nSplosno: "Ni uspelo."
    },
    en: {
      mikrofonNaslov: "Search by voice", govorPoslusam: "Listening … say what you are looking for", govorPrepoznavam: "Recognising …", govorTisina: "I did not hear anything. Press the microphone and speak again.", govorNiPodprto: "Voice search is not available on this computer.", govorMikrofon: "The microphone cannot be opened.", govorNapaka: "Speech recognition failed.", govorNamestiNaslov: "Search by voice", govorNamestiOpis: "Speech is recognised on this computer – nothing goes to the internet. Speech recognition has to be downloaded once ({mb} MB).", govorPrenesi: "Download", govorNeZdaj: "Not now", govorPrenasam: "Downloading speech recognition … {o} %", govorPrekini: "Cancel", govorPrenosNapaka: "The download failed. Try again.", govorPreklici: "Cancel", govorKoncaj: "Done",
      iskanjePh: "Search the web, apps, files and media …", iskanjePhKratko: "Search apps, files, web …", iskanjePhKrajse: "Search apps and web …", iskanjePhNajkrajse: "Search …", iskanjeNamig: "Enter opens the selection · Shift+Enter web",
      plosceNaslov: "Panels", medijiNaslov: "Media center", datotekeNaslov: "Files", programiNaslov: "Apps",
      zamenjajStrani: "Swap left and right", ponastavi: "Default layout", vecjiTekst: "Larger text", velikostBesedila: "Text size", tekst200: "200 % – for viewing from afar",
      manjProsojnosti: "Less transparency", spletVBrskalniku: "Search the web in the default browser", spletVBrskalnikuIme: "Search the web in {ime}", sistemNaslov: "Desktop and system", modulTeme: "Theme, icons and pointer …", modulOzadja: "System backgrounds …", modulPisave: "Fonts …", modulZaslon: "Display …", modulOkna: "Windows …", modulPult: "Panel …", modulNocna: "Night light …", modulVse: "All system settings …", skrijPlosco: "Hide panel", pokaziPlosco: "Show the {ime} panel", spremeniVelikost: "Drag to resize (arrow keys work too)",
      odpriMedijskiCenter: "Open Media center", niPredvajanja: "Nothing playing",
      medijNavodilo: "Pick music or a video in Files or in the Media center.",
      medijIskanjePh: "Search music, radio, films and series …", medijIskanjeVse: "All results for “{q}” in the Media center",
      medijIskanjeIscem: "Searching …", medijTokovi: "Station channels:", medijIskanjeSe: "Still searching sources …", medijIskanjeNic: "Nothing found.", medijTaRacunalnik: "This computer",
      prejsnja: "Previous", premor: "Play / pause", naslednja: "Next",
      predvaja: "Playing", vPremoru: "Paused", ustavljeno: "Stopped", napakaPredvajanja: "Playback failed",
      filterPh: "Filter …", filterPrgPh: "Search apps …", vseVrste: "All types", vrstaDokument: "Documents",
      vrstaSlika: "Pictures", vrstaVideo: "Video", vrstaZvok: "Music", vrstaMapa: "Folders",
      en_mapa: "Folder", en_dokument: "Document", en_slika: "Picture", en_video: "Video", en_zvok: "Audio", en_arhiv: "Archive",
      en_program: "Program", en_splet: "Web", en_drugo: "Other",
      stIme: "Name", stVrsta: "Type", stLokacija: "Location", stVelikost: "Size", stSpremenjeno: "Modified",
      pregled: "Overview", nedavno: "Recent", priljubljeno: "Favourites", mape: "Folders", naprave: "Devices",
      taRacunalnik: "This computer", domov: "Home folder",
      DOCUMENTS: "Documents", PICTURES: "Pictures", VIDEOS: "Videos", MUSIC: "Music", DOWNLOAD: "Downloads", DESKTOP: "Desktop",
      nalagam: "Loading …", praznaMapa: "This folder is empty.", niZadetkov: "No matching files.",
      niNedavnih: "No recent files yet.", niPriljubljenih: "No favourites yet. Right-click a file or folder → Add to favourites.",
      niMape: "The folder no longer exists.", niDovoljenja: "You don't have access to this folder.",
      napravaNeOdgovori: "The device can't be reached right now. Nothing is shown so you never see stale data.",
      napravaNeDeli: "The device doesn't share files. Turn on file sharing for it in Safeer Link.",
      napravaOsvezeno: "refreshed at {cas}", oddaljeno: "on {naprava}",
      odpri: "Open", pokaziVMapi: "Show in folder", dodajPriljubljeno: "Add to favourites",
      odpriZ: "Open with …", privzetProgram: "default", drugProgram: "Another program …",
      vednoSTem: "Always open this type of file with this program", niProgramaZaVrsto: "No program is set up for this type of file.",
      odslejZ: "From now on this type of file opens with {ime}.",
      odstraniPriljubljeno: "Remove from favourites", predogled: "Preview", zapri: "Close",
      odpiramNaNapravi: "From a device I can only play music and video. Open other files on the device itself.",
      niUspelo: "That didn't work.", strani: "{a}–{b} of {n}", nazaj: "‹", naprej: "›",
      kVse: "All", kPisarna: "Office", kUstvarjanje: "Creative", kMediji: "Media", kSplet: "Web", kIgre: "Games",
      kDrugo: "Other", kPriljubljeni: "★ Favourites",
      oblak: "Cloud", oblakOpis: "Games run on {ponudnik} servers; you need an account with them.",
      oblakNamesti: "Install (official {ponudnik} package)", oblakVec: "About the service",
      ppGumb: "Install apps …", ppNaslov: "Where do you want to install apps from?",
      ppUvod: "Choose an app provider. Safeer recommends none – they are in alphabetical order, nothing is the default.",
      ppOdpri: "Open", ppNamesti: "Install", ppNamescam: "Installing …", ppVec: "More", ppNamesceno: "installed",
      ppGeslo: "asks for a password", ppKoncano: "{ime} is installed.", ppNapaka: "{ime} was not installed.",
      ppPreklicano: "Installation cancelled.", ppPrazno: "The list of providers could not be read.",
      ppIme_gnome_software: "GNOME Software", ppIme_mintinstall: "Software Manager",
      ppOpis_bazaar: "Apps from Flathub.", ppOpis_discover: "KDE's software center (system packages and Flatpak).",
      ppOpis_gearlever: "AppImage apps: install, update and tidy up.",
      ppOpis_gnome_software: "GNOME's software center (system packages and Flatpak).",
      ppOpis_snap_store: "Snap apps. Linux Mint turns Snap off; “Enable” turns it on (you see every step).",
      ppOpis_mintinstall: "The Linux Mint software center (system packages and Flathub).",
      ppZavihekPonudniki: "Providers", ppZavihekViri: "Sources", ppZavihekGithub: "GitHub", ppOmogoci: "Enable",
      ppKorak_nosnap: "Remove Mint's Snap block (/etc/apt/preferences.d/nosnap.pref)", ppKorak_snapd: "Install the snapd package",
      ppKorak_snap_store: "Install Snap Store",
      ppVirSnap: "Source: Snapcraft (Canonical) · for the whole computer · the system asks for a password",
      ppPosSnap: "Updates: Snap updates its apps by itself (a property of Snap). You can hold them with “snap refresh --hold”.",
      ppViriUvod: "Sources this computer installs programs from. You can add your own: a PPA or a Flatpak repository.",
      ppViriPh: "ppa:name/ppa or https://…/source.flatpakrepo", ppViriDodaj: "Add source", ppViriPrazno: "No sources.",
      ppViriNeveljaven: "That is not a PPA (ppa:name/ppa) or an https://…/name.flatpakrepo address.",
      ppViriPpa: "The PPA {vir} will be added for the whole computer · the system asks for a password.",
      ppViriFlatpak: "The Flatpak repository “{ime}” ({vir}) will be added · for your user only · no password.",
      ppViriOpozorilo: "Safeer does not check programs from this source. Add only a source you trust.",
      ppViriDodan: "The source is added.", ppViriNapaka: "The source could not be added.",
      ppZaUporabnika: "for your user", ppZaSistem: "for the whole computer",
      ppGhUvod: "Public GitHub repositories and the files of their releases. Save them to a folder you choose; Safeer does not check or install them by itself.",
      ppGhMapa: "Save to: {pot}", ppGhSpremeni: "Change …", ppGhIzberiMapo: "Where should programs and files be saved?",
      ppGhIsciPh: "Search repositories (e.g. localsend)", ppGhIsci: "Search", ppGhIscem: "Searching …", ppGhNic: "No results.",
      ppGhIzdaje: "Releases", ppGhNazaj: "Results", ppGhBrezIzdaj: "This repository has no releases.", ppGhBrezDatotek: "No files.",
      ppGhPredizdaja: "pre-release", ppGhArhiviran: "archived", ppGhPrenosov: "{n} downloads", ppGhShrani: "Save",
      ppGhShranjujem: "Saving …", ppGhShranjeno: "Saved: {ime}", ppGhNiMape: "The chosen folder cannot be written to.",
      ppGhVse: "All", ppGhZaTaKratko: "This computer", ppGhDrugo: "Other", ppGhDrugaLicenca: "other licence", ppGhNiZaNas: "These releases have no file for this computer (Linux).",
      ppZvrst_mediji: "Media", ppZvrst_ustvarjanje: "Creative", ppZvrst_pisarna: "Office", ppZvrst_splet: "Web",
      ppZvrst_komunikacija: "Communication", ppZvrst_igre: "Games", ppZvrst_razvoj: "Development", ppZvrst_sistem: "System and tools",
      ppZvrst_varnost: "Security and privacy", ppZvrst_drugo: "Other",
      ppGhZaTa: "for this computer", ppAptVir: "package repository · for the whole computer",
      ppGhShranjenoPreverjeno: "Saved and verified (SHA-256 from GitHub): {ime}",
      ppGhKontrolna: "The downloaded file does not match GitHub's SHA-256, so it was not kept.",
      ppGhNapaka: "GitHub is not answering right now. Try again later.", ppGhOmejitev: "GitHub limits searches without signing in. Try again in a minute.",
      ppPreverjam: "Checking what will be installed …", ppKajSe: "This will be installed:", ppOkolje: "runtime the program needs",
      ppVirFlatpak: "Source: Flathub · for your user only · no password · download {mb} MB",
      ppVirApt: "Source: {vir} repositories · for the whole computer · the system asks for a password · download {mb} MB",
      ppPosSamo: "Updates: automatic updates are on in the Update Manager, so it will update by itself. You can change this in the Update Manager settings.",
      ppPosRocno: "Updates: the Update Manager offers them; they are installed only when you confirm.",
      ppPotrdi: "Install", ppPreklici: "Cancel", ppNiPodatkov: "Could not read what would be installed, so nothing is installed.",
      oblakNamescam: "Installing {ime} from the official {ponudnik} source. This can take a few minutes…",
      oblakNamesceno: "{ime} is installed. You will find it under Games.", oblakZeNamescam: "The installation is already running.",
      oblakNapaka_vir: "The official source could not be added. Check your internet connection.",
      oblakNapaka_namestitev: "The installation failed. Try again.", oblakNapaka_prostor: "Not enough disk space to install.",
      oblakNapaka_ni_zdruzljivo: "This computer does not meet the requirements.",
      oblakZdruzljivo: "This computer meets the requirements.", oblakPoskusi: "Worth a try: {razlog}", oblakNe: "Will not work: {razlog}",
      oblakRazlog_osnova: "{sistem} is not on the official list, but shares its base with the supported {osnova}",
      oblakRazlog_sistem: "{sistem} is not on the provider's official list", oblakRazlog_ram: "not enough memory ({potrebno} GB needed)",
      oblakRazlog_jedra: "not enough processor cores ({potrebno} needed)", oblakRazlog_arhitektura: "a 64-bit x86 processor is needed",
      oblakRazlog_flatpak: "Flatpak is not installed",
      kopiraj: "Copy", izrezi: "Cut", prilepi: "Paste", prilepiV: "Paste into this folder", lastnosti: "Properties",
      kopirajN: "Copy ({n})", izreziN: "Cut ({n})", vSmetiN: "Move to Trash ({n})", obnoviN: "Restore ({n})",
      izbranoN: "Selected: {n}", pocistiIzbiro: "Clear selection", izberiVse: "Select all",
      delnoUspelo: "Done: {ok}, failed: {ne}.", premaknjenoV: "Moved to “{mapa}”: {ime}", kopiranoV: "Copied to “{mapa}”: {ime}",
      vSmetiVecOk: "In the Trash: {ime} (restore them from Files → Trash).", obnovljenoN: "Restored: {ime}",
      kopirano: "Copied: {ime}. Paste with right-click or Ctrl+V.", izrezano: "Cut: {ime}. Paste with right-click or Ctrl+V.",
      kopiram: "Copying…", premikam: "Moving…", prilepljeno: "Copied here: {ime}", premaknjeno: "Moved here: {ime}",
      prilepiNapaka_vase: "A folder cannot be copied into itself.", prilepiNapaka_ni_prostora: "Not enough space on the disk.",
      prilepiNapaka_ni_dovoljenja: "This folder cannot be written to.", prilepiNapaka_ni_datoteke: "The original file is gone.",
      prilepiNapaka_ni_dovoljeno: "This cannot be copied or moved.", prilepiNapaka_ni_mape: "The destination folder is gone.",
      smeti: "Trash", praznoSmeti: "The Trash is empty.", obnovi: "Restore", obnovljeno: "Restored: {ime}",
      izprazniSmeti: "Empty Trash…", smetiIzpraznjene: "The Trash has been emptied.",
      izvrzi: "Eject", izvrzeno: "{ime} can be unplugged.", izvrziZaseden: "{ime} is still in use. Close its files and try again.",
      prostoNa: "{prosto} free of {skupaj}",
      lVrsta: "Type", lVelikost: "Size", lKje: "Location", lSpremenjeno: "Modified", lPravice: "Permissions", lVsebuje: "Contains",
      lElementov: "{n} items", lPovezava: "Points to",
      niPriljubljenihPrg: "No favourite apps yet. Click ☆ on an app and you will always find it here quickly.",
      vseNaprave: "All devices", razvrstiIme: "By name", razvrstiNaprava: "By device",
      pogledSeznam: "List / grid", spletnaAplikacija: "In the browser",
      odpriTukaj: "Open here (device screen on this computer)", zazeniNaNapravi: "Start on the device",
      kategorija: "Category: {k}", popraviKategorijo: "Move to category",
      niNaprav: "Apps from your other devices appear once you add a device in Safeer Link (Safeer Control).",
      niProgramov: "No apps in this category.", napravaNedosegljiva: "{naprava}: not reachable", napraveNedosegljive1: "{n} device not reachable", napraveNedosegljive2: "{n} devices not reachable", napraveNedosegljive3: "{n} devices not reachable", napraveNedosegljive5: "{n} devices not reachable",
      brezControla: "Safeer Link (Safeer Control) isn't running, so apps on your devices aren't available.",
      zagonPoslan: "Sent to {naprava}.",
      skSplet: "Web", skProgrami: "Apps", skNastavitve: "Settings", skProgramiNaprav: "Apps on devices", skDatoteke: "Files", skMediji: "Media", skPrikaziNa: "Show on", prikaziNaVrsta: "Show “{kaj}” on: {ime}", prikazanoNa: "Opening on {ime}: {kaj}", izberiNapravo: "Choose the device to show it on.", niNapraveCilja: "There is no such device in Safeer Link.", napravaNeZna: "{ime} cannot do this yet – update Safeer on it.",
      skZapiski: "Notes", skSafeer: "Safeer OS", ciljMedia: "Media Centre", ciljNaprave: "Devices (Safeer Link)", ciljScit: "Shield – protection for the whole computer",
      ciljNastavitve: "Safeer OS settings", ciljZapiski: "Notes", ciljSporocila: "Messages", ciljSplet: "Web in Safeer OS",
      odpreSafeerOs: "opens Safeer OS", odprePredvajalnik: "opens Safeer Player",
      skNaprave: "Devices", napravaDatoteke: "files on the device", napravaProgrami: "apps on the device",
      isciVMedijih: "Find “{q}” in the Media Centre", odpreMedijski: "films, series, music, radio",
      posljiNaNapravo: "Send to a device …", posNiNaprav: "No device in Safeer Link can receive a file.",
      posPosiljam: "Sending “{ime}” to {naprava} … {odst} %",
      posPosiljamN: "Sending to {naprava}: {k} of {n} · “{ime}” … {odst} %",
      posPoslano: "Sent to {naprava}: {ime}", posPoslanoN: "Sent to {naprava}: {n}", 
      posNapaka: "Sending to {naprava} failed: {razlog}.",
      posN_naprava_ni_povezana: "the device is not connected",
      posN_sredisce_ne_zna: "the hub cannot do this yet – update Safeer on the device that is the hub",
      posN_naprava_pri_drugem_srediscu: "the device is connected through another hub",
      posN_stari_control: "Safeer Control has to be restarted (an older version is running)",
      posN_ni_controla: "Safeer Control is not running", posN_hub_ni_znan: "this computer is not connected to Safeer Link",
      posN_prazna_mapa: "the folder is empty", posN_prevec_datotek: "too many files at once (at most {najvec})",
      posN_prevelika: "the file is larger than 4 GB", posN_ni_prostora: "not enough space for the file",
      posN_naprava_zasedena: "another device is sharing with that device right now", posN_ni_datoteke: "the file is gone",
      posN_naprava_ni_seznanjena: "this computer is not signed in at the hub",
      posN_sredisce_naprave_ni_dosegljivo: "the device cannot be reached on this network", posN_posiljanje_ni_uspelo: "the connection was interrupted",
      isciVSpletu: "Search the web for “{q}”", odpreVBrskalniku: "results right here on the desktop", isciem: "Searching …",
      prostor: "{n} items",
      spremeniOzadje: "Change wallpaper …", prilagodiDock: "Edit dock …",
      dockDodaj: "Add to dock", dockOdstrani: "Remove from dock", dockNaslov: "Dock", dockDodajProgram: "Add an app …",
      dockGor: "Move up", dockDol: "Move down", dockPrazen: "No apps in the dock.", dockVecNastavitev: "More dock settings …",
      dockIsci: "Find an app …", dockBrezPlanka: "The dock (Plank) is not installed.", dockOpis: "Change the order with the arrows; you can also drag icons on the dock itself.",
      dockDodano: "{ime} is in the dock.", dockOdstranjeno: "{ime} is no longer in the dock.", nazaj: "Back",
      dockNamig: "Add an app to the dock by right-clicking it › Add to dock, or in Edit dock.",
      linkPovezan: "Safeer Link · {n}", linkPovezanBrez: "Safeer Link · connected",
      linkPovezi: "Connect to Safeer Link", linkNaslov: "Safeer Link: your devices (opens Safeer Control)",
      naprav1: "1 device", naprav2: "2 devices", naprav34: "{n} devices", napravN: "{n} devices",
      novoNaslov: "New folder or file", novaMapa: "New folder …", novaDatoteka: "New file",
      vPrazna: "Empty file …", vBesedilo: "Text file …", vDokument: "Document …",
      vPreglednica: "Spreadsheet …", vPredstavitev: "Presentation …", vPredloga: "Template: {ime} …",
      oknoMapa: "New folder", oknoDatoteka: "New file", oknoPreimenuj: "Rename",
      privzetoMapa: "New folder", privzetoDatoteka: "New file", privzetoDokument: "New document",
      privzetoPreglednica: "New spreadsheet", privzetoPredstavitev: "New presentation",
      novoIme: "Name", novoVrsta: "Type", novoKje: "Where", novoSpremeni: "Change …", preklici: "Cancel",
      ustvari: "Create", preimenuj: "Rename", preimenujMeni: "Rename …", vSmeti: "Move to Trash",
      shraniNaNapravo: "Store on another device …", shrPripravljam: "Preparing “{ime}” (checking its content) …",
      shrPrenasam: "{naprava} is storing “{ime}” … {odst} %", shrKopijaNaslov: "The copy is stored and verified",
      shrKopija: "“{ime}” is now also on {naprava}, in the folder {kje}. The copy is verified – identical to the original.",
      shrVprasaj: "Delete the original on this computer? This frees {velikost}.", shrIzbrisi: "Delete original",
      shrObdrzi: "Keep both", shrIzbrisano: "The original is deleted. You will find “{ime}” on {naprava} ({kje}).",
      shrObdrzano: "Kept both: the original is here, the copy is on {naprava}.",
      shrNiNaprave: "No device in Safeer Link has enough space right now or can help (battery, busy).",
      shrSpremenjena: "The file changed in the meantime – the original is not deleted. Store it again.",
      shrNapaka: "Storing on another device failed ({koda}).", shrZapri: "Close", shrPrenosi: "Downloads",
      najvecje: "Largest files", niVelikih: "No files larger than 100 MB.",
      pretvoriV: "Convert to …", ptdNaslov: "Convert “{ime}”", ptdIzberi: "Which format? The original stays.",
      ptdPretvarjam: "Converting “{ime}” to {cilj} …", ptdKoncano: "Saved next to the original as “{izhod}” ({velikost}).",
      ptdNapaka: "Conversion failed ({koda}).", ptdNiOrodja: "A program for this kind of file is missing: {orodje}.",
      ptdNiMogoce: "This file cannot be converted.",
      ptdNiUspelo: "This file could not be converted – it may be damaged. The original is unchanged.",
      ptdPrepocasi: "The conversion took too long and was stopped. The original is unchanged.",
      ptdNiDatoteke: "The file is no longer there.",
      pretvori: "Convert for TV (1080p) …", prvIscem: "Looking for the device with the best hardware encoder for “{ime}” …",
      prvPrenasam: "{naprava} is fetching “{ime}” … {odst} %", prvPretvarjam: "{naprava} is converting “{ime}” … {odst} %", prvPretvarjamTu: "No device can help, so this computer is converting “{ime}” … {odst} %",
      prvShranjujem: "{naprava} is saving the converted video …", prvKoncanoNaslov: "The video is converted",
      prvKoncano: "“{izhod}” ({velikost}) is on {naprava}, in the folder {kje}. Every TV can play it. The original on this computer is unchanged.",
      prvVprasaj: "Copy it to this computer too, next to the original?", prvPrenesi: "Copy to this computer", prvPusti: "Leave it there",
      prvNazaj: "Copying “{izhod}” to this computer … {odst} %", prvNaRacunalniku: "“{izhod}” is now also on this computer, next to the original.",
      prvPusceno: "“{izhod}” stays on {naprava} ({kje}). You will find it in that device's Files.",
      prvNeDeli: "{naprava} does not share files, so the video can't be copied here. It stays on the device ({kje}).",
      prvNiNaprave: "No device in Safeer Link has a 1080p hardware encoder, enough space or power right now (battery, busy).",
      prvNapaka: "Conversion failed ({koda}).",
      prvNeZna: "No device in Safeer Link can read this video (format or resolution, e.g. 4K HEVC). The original stays unchanged.",
      pretvoriMapo: "Convert videos in folder for TV …", prvSkNaslov: "Converting videos – all devices help",
      prvSkPoteka: "{opr} of {vseh} converted. Every device converts one video at a time and takes the next when done – the stronger one does more.",
      prvSkKoncano: "{opr} of {vseh} videos converted.", prvSkNapake: "{n} videos could not be converted ({koda}).",
      prvSkVprasaj: "Copy them to this computer, each next to its original?", prvSkPrenesi: "Copy all here", prvSkPusti: "Leave on devices",
      prvSkNazaj: "Copying converted videos to this computer …", prvSkNaRacunalniku: "The converted videos are now next to the originals ({n}).",
      prvSkPusceno: "The converted videos stay on the devices (Downloads › Safeer Shramba).", prvSkDela: "converting", prvSkNiVidea: "There are no videos in this folder.",
      maloProstora: "Only {prosto} left on this computer. You can store larger files on a device in Safeer Link – you delete the original only after you see where the copy is.",
      pokaziNajvecje: "Show largest files",
      vSmetiOk: "“{ime}” is in the Trash (restore it from Files → Trash).", ustvarjeno: "Created: {ime}",
      izberiMapoNaslov: "Where should I create it?", izberi: "Select", osvezi: "Refresh",
      razveljavi: "Undo", razveljavljeno: "Undone.", nicZaRazveljaviti: "Nothing to undo.",
      razveljavitevNiUspela: "This can no longer be undone (the file was moved since, or another one is in its place).",
      preimenovano: "Renamed: {ime}",
      nObstaja: "A file with this name already exists here.", nIme: "The name can't be empty, start with a dot or contain “/”.",
      nDovoljenje: "You can't write to this folder. Pick another one.", nMapa: "This folder no longer exists.",
      nSmeti: "Couldn't move it to the Trash (maybe no permission).", nSplosno: "That didn't work."
    }
  };
  var jezik = "sl";
  function t(k, z) {
    var b = (BESEDILA[jezik] && BESEDILA[jezik][k]);
    if (b == null) b = BESEDILA.en[k];
    if (b == null) b = k;
    if (z) Object.keys(z).forEach(function (x) { b = b.split("{" + x + "}").join(z[x]); });
    return b;
  }
  // Namig v polju se nikoli ne odreze: ce dolgo besedilo ne gre v polje (velika pisava, ozko okno),
  // vzamemo krajso razlicico (<kljuc>Kratko, <kljuc>Krajse, <kljuc>Najkrajse), ki je cela vidna.
  var phMerilo = null;
  function phSirina(e, besedilo) {
    phMerilo = phMerilo || document.createElement("canvas").getContext("2d");
    var cs = getComputedStyle(e);
    phMerilo.font = cs.fontStyle + " " + cs.fontWeight + " " + cs.fontSize + " " + cs.fontFamily;
    return phMerilo.measureText(besedilo).width;
  }
  function phPrilagodi(e) {
    var k = e.getAttribute("data-ph"), moznosti = [t(k)];
    [k + "Kratko", k + "Krajse", k + "Najkrajse"].forEach(function (x) { var b = t(x); if (b !== x) moznosti.push(b); });
    var cs = getComputedStyle(e), fs = parseFloat(cs.fontSize) || 14;
    var prostor = e.clientWidth - (parseFloat(cs.paddingLeft) || 0) - (parseFloat(cs.paddingRight) || 0) - (e.type === "search" ? 1.2 * fs : 0);
    var izbrano = moznosti[moznosti.length - 1];
    if (prostor > 0) {
      for (var i = 0; i < moznosti.length; i++) { if (phSirina(e, moznosti[i]) <= prostor) { izbrano = moznosti[i]; break; } }
    } else izbrano = moznosti[0];
    e.placeholder = izbrano;
  }
  function opazujPh(e) {
    if (e._phOpazovan || typeof ResizeObserver === "undefined") return;
    e._phOpazovan = true;
    new ResizeObserver(function () { if (!e.getAttribute("data-ph-zaklenjen")) phPrilagodi(e); }).observe(e);
  }
  function prevedi() {
    document.documentElement.lang = jezik;
    document.querySelectorAll("[data-t]").forEach(function (e) { e.textContent = t(e.getAttribute("data-t")); });
    document.querySelectorAll("[data-ph]").forEach(function (e) { phPrilagodi(e); opazujPh(e); });
    document.querySelectorAll("[data-naslov]").forEach(function (e) {
      e.title = t(e.getAttribute("data-naslov")); e.setAttribute("aria-label", e.title);
    });
  }

  // ------------------------------------------------------------------ nastavitve postavitve
  // Samo udobje enega uporabnika na tem racunalniku (sirina stolpcev, skrite plosce): localStorage.
  var PRIVZETO = { levo: 50, medij: 118, skrite: [], zamenjano: false, vecjiTekst: false, manjProsojnosti: false, spletVBrskalniku: false,
                   pogled: "mreza", priljubljeniPrg: [], kategorije: {}, priljubljeneDat: [] };
  var N = nalozi();
  function nalozi() {
    var n = JSON.parse(JSON.stringify(PRIVZETO));
    try {
      var s = JSON.parse(localStorage.getItem("safeer_delovna") || "{}");
      Object.keys(n).forEach(function (k) { if (s[k] != null && typeof s[k] === typeof n[k]) n[k] = s[k]; });
    } catch (e) { /* zasebni nacin ali pokvarjen zapis: privzeto */ }
    return n;
  }
  function shrani() { try { localStorage.setItem("safeer_delovna", JSON.stringify(N)); } catch (e) { /* ni shrambe */ } }
  // Vecje besedilo in manj prosojnosti: ko je vklopljen Safeer Cinnamon, sta to nastavitvi SISTEMA (tema lupine in
  // programov, velikost besedila) - stikali ju upravljata in jima sledita. Brez njega veljata samo za to stran.
  var V = { naVoljo: false, kontrast: false, vecjiTekst: false };
  function vecjiTekst() { return V.naVoljo ? !!V.vecjiTekst : !!N.vecjiTekst; }
  function manjProsojnosti() { return V.naVoljo ? !!V.kontrast : !!N.manjProsojnosti; }
  function nastaviVidez(v) { if (v && typeof v === "object") { V = v; uveljaviPostavitev(); } }

  function uveljaviPostavitev() {
    var root = document.documentElement.style;
    root.setProperty("--levo", String(Math.max(25, Math.min(75, N.levo))));
    root.setProperty("--medij", Math.max(92, N.medij) + "px");
    // Sistemska povecava besedila poveca tudi to stran (WebKit ji sledi): lastno povecanje bi se ji pristelo.
    document.body.classList.toggle("vecji-tekst", !V.naVoljo && !!N.vecjiTekst);
    document.body.classList.toggle("manj-prosojnosti", manjProsojnosti());
    ["mediji", "datoteke", "programi"].forEach(function (p) {
      var sk = N.skrite.indexOf(p) >= 0;
      document.querySelector('section[data-plosca="' + p + '"]').hidden = sk;
      var cb = document.querySelector('#meniPlosce input[data-plosca="' + p + '"]');
      if (cb) cb.checked = !sk;
    });
    $("deliMediji").hidden = N.skrite.indexOf("mediji") >= 0 || N.skrite.indexOf("datoteke") >= 0;
    narisiSkritePlosce();
    var aPrazen = N.skrite.indexOf("mediji") >= 0 && N.skrite.indexOf("datoteke") >= 0;
    var bPrazen = N.skrite.indexOf("programi") >= 0;
    var p = $("postavitev");
    p.classList.toggle("samo-a", bPrazen && !aPrazen);
    p.classList.toggle("samo-b", aPrazen && !bPrazen);
    p.classList.toggle("zamenjano", !!N.zamenjano);
    p.classList.toggle("vse-skrito", aPrazen && bPrazen);
    if (N.skrite.indexOf("datoteke") >= 0) $("ploscaMediji").style.flex = "1";
    else $("ploscaMediji").style.flex = "";
    $("stikaloTekst").checked = vecjiTekst();
    // S Safeer Cinnamon izbira velikosti (ves sistem); brez njega stikalo velja samo za to stran.
    $("vrsticaVelikost").hidden = !V.naVoljo; $("vrsticaTekst").hidden = !!V.naVoljo;
    if (V.naVoljo) {
      var o = Number(V.tekstOdstotek) || 100, izb = $("izbiraTeksta"), najblizja = "100";
      Array.prototype.forEach.call(izb.options, function (x) { if (Math.abs(Number(x.value) - o) < Math.abs(Number(najblizja) - o)) najblizja = x.value; });
      izb.value = najblizja;
    }
    $("stikaloProsojnost").checked = manjProsojnosti();
    $("stikaloBrskalnik").checked = !!N.spletVBrskalniku;
    requestAnimationFrame(function () { izrisiDatoteke(); izrisiPrograme(); });
  }

  // Delilnika: miska in tipkovnica (puscice). Brez navpicnega pomikanja: velikost se samo razporedi.
  function delilnik(elDeli, navpicno) {
    function premik(dx, dy) {
      if (navpicno) {
        var w = $("postavitev").getBoundingClientRect().width;
        N.levo = Math.max(25, Math.min(75, N.levo + dx / w * 100));
      } else {
        var h = $("stolpecA").getBoundingClientRect().height;
        N.medij = Math.max(92, Math.min(h * 0.6, N.medij + dy));
      }
      uveljaviPostavitev();
    }
    elDeli.addEventListener("pointerdown", function (e) {
      e.preventDefault(); elDeli.setPointerCapture(e.pointerId); elDeli.classList.add("vlecem");
      var x = e.clientX, y = e.clientY;
      function mv(ev) { premik(ev.clientX - x, ev.clientY - y); x = ev.clientX; y = ev.clientY; }
      function up() { elDeli.classList.remove("vlecem"); elDeli.removeEventListener("pointermove", mv); elDeli.removeEventListener("pointerup", up); shrani(); }
      elDeli.addEventListener("pointermove", mv); elDeli.addEventListener("pointerup", up);
    });
    elDeli.addEventListener("keydown", function (e) {
      var k = { ArrowLeft: [-24, 0], ArrowRight: [24, 0], ArrowUp: [0, -16], ArrowDown: [0, 16] }[e.key];
      if (!k) return;
      e.preventDefault(); premik(k[0], k[1]); shrani();
    });
  }

  // Premik plosce: povleci glavo programov na drugo stran (zamenja stolpca).
  // Stolpec je cilj samo, dokler vlecemo plosco (vlecemPlosco = njen id): vlecenje datotek ga ne sme oznaciti.
  var vlecemPlosco = "";
  function vleciGlavo() {
    document.querySelectorAll(".plosca .glava h2").forEach(function (h) {
      h.setAttribute("draggable", "true");
      h.addEventListener("dragstart", function (e) {
        var pl = h.closest(".plosca"); pl.classList.add("vlecem"); vlecemPlosco = pl.id;
        e.dataTransfer.setData("text/plain", pl.id); e.dataTransfer.effectAllowed = "move";
      });
      h.addEventListener("dragend", function () {
        document.querySelectorAll(".vlecem, .cilj").forEach(function (x) { x.classList.remove("vlecem"); x.classList.remove("cilj"); });
        setTimeout(function () { vlecemPlosco = ""; }, 300);
      });
    });
    ["stolpecA", "stolpecB"].forEach(function (id) {
      var s = $(id);
      s.addEventListener("dragover", function (e) { if (!vlecemPlosco) return; e.preventDefault(); s.classList.add("cilj"); });
      s.addEventListener("dragleave", function () { s.classList.remove("cilj"); });
      s.addEventListener("drop", function (e) {
        if (!vlecemPlosco) return;
        e.preventDefault(); s.classList.remove("cilj");
        var iz = document.getElementById(vlecemPlosco);
        vlecemPlosco = "";
        if (iz && !s.contains(iz)) { N.zamenjano = !N.zamenjano; shrani(); uveljaviPostavitev(); }
      });
    });
    // Kar je spusceno mimo cilja (datoteka iz drugega programa), nima ucinka - kazalec to pove ze med vlecenjem.
    document.addEventListener("dragover", function (e) {
      if (e.defaultPrevented || vlecemPlosco || (e.target && e.target.closest && e.target.closest("input, textarea"))) return;
      e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = "none";
    });
    document.addEventListener("drop", function (e) {
      if (e.defaultPrevented || (e.target && e.target.closest && e.target.closest("input, textarea"))) return;
      e.preventDefault();
    });
  }

  // ------------------------------------------------------------------ pomozno
  var LOKALE = { sl: "sl-SI", en: "en-GB" };
  function velikost(b) {
    if (!b) return "";
    if (b >= 1073741824) return (b / 1073741824).toFixed(1).replace(".", jezik === "sl" ? "," : ".") + " GB";
    if (b >= 1048576) return (b / 1048576).toFixed(1).replace(".", jezik === "sl" ? "," : ".") + " MB";
    return Math.max(1, Math.round(b / 1024)) + " kB";
  }
  function cas(s) {
    if (!s) return "";
    var d = new Date(s * 1000), zdaj = new Date();
    var o = d.toDateString() === zdaj.toDateString() ? { hour: "2-digit", minute: "2-digit" }
      : d.getFullYear() === zdaj.getFullYear() ? { day: "numeric", month: "numeric" } : { day: "numeric", month: "numeric", year: "2-digit" };
    try { return d.toLocaleString(LOKALE[jezik] || "sl-SI", o); } catch (e) { return d.toISOString().slice(0, 10); }
  }
  var IKONE_VRST = {
    mapa: "M3 7h6l2 2h10v10H3z", slika: "M4 5h16v14H4z M8 14l3-3 5 5 M15 10h.01", video: "M4 6h12v12H4z M16 10l4-2v8l-4-2",
    zvok: "M9 18V6l10-2v12 M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0z", dokument: "M6 3h8l4 4v14H6z M14 3v4h4 M9 12h6 M9 16h6",
    arhiv: "M5 4h14v16H5z M12 4v8", splet: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M3 12h18 M12 3c3 3 3 15 0 18 M12 3c-3 3-3 15 0 18", program: "M4 5h16v14H4z M8 10l3 2-3 2 M13 15h3",
    naprava: "M8 3h8a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z M11 18h2", drugo: "M6 3h8l4 4v14H6z"
  };
  function ikonaVrste(vrsta) {
    var v = IKONE_VRST[vrsta] ? vrsta : "drugo";
    var s = el("span", "ikona-vrste v-" + v);
    s.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="' + IKONE_VRST[v] + '"/></svg>';
    return s;
  }
  function vrstaOddaljenega(type) {
    return type === "folder" ? "mapa" : type === "audio" ? "zvok" : type === "video" ? "video" : type === "image" ? "slika" : "drugo";
  }
  // Barvna ploscica s prvo crko za program brez ikone - enako kot na glavni strani Safeer OS (os.js).
  function barva(ime) {
    var h = 0;
    for (var i = 0; i < ime.length; i++) h = (h * 31 + ime.charCodeAt(i)) >>> 0;
    var barve = ["#1f7a5c", "#2d5f9a", "#8a3d7a", "#a4492f", "#5a4aa0", "#2f7f8a", "#8a6d1f", "#3b6e2f"];
    return barve[h % barve.length];
  }
  function crka(ime, razred) {
    var c = el("span", (razred || "") + " crka", (String(ime || "?").trim().charAt(0) || "?").toUpperCase());
    c.style.background = barva(String(ime || "?"));
    c.setAttribute("aria-hidden", "true");
    return c;
  }
  function slikaAliCrka(src, ime, razred) {
    if (!src) return crka(ime, razred);
    var img = el("img", razred || ""); img.alt = ""; img.src = src; img.loading = "lazy";
    img.onerror = function () { img.replaceWith(crka(ime, razred)); };
    return img;
  }
  var casObvestila = 0;
  // dejanje: { ime, naredi } doda obvestilu gumb (Razveljavi); tako obvestilo ostane dlje, da ga je mogoce doseci.
  function obvesti(b, dejanje) {
    var o = $("obvestilo"); o.textContent = b; o.hidden = false;
    if (dejanje) {
      var g = el("button", "", dejanje.ime); g.type = "button";
      g.addEventListener("click", function () { o.hidden = true; dejanje.naredi(); });
      o.appendChild(g);
    }
    clearTimeout(casObvestila); casObvestila = setTimeout(function () { o.hidden = true; }, dejanje ? 9000 : 4200);
  }
  function stranskoBesedilo(p) { return p.replace(/^\/home\/[^/]+/, "~"); }

  // ------------------------------------------------------------------ zacetek
  var Z = { mape: [], dom: "", spletne: [] };
  function robovi(r) {
    ["vrh", "dno", "levo", "desno"].forEach(function (k) {
      var v = Math.max(0, Math.min(400, parseInt(r[k], 10) || 0));
      document.documentElement.style.setProperty("--r-" + k, v + "px");
    });
  }
  function zacni() {
    // Gumb + ima samo aria-label: brskalnikov namig (title) bi prekril meni, ki se odpre pod njim.
    var gn = $("gumbNovo"); if (gn) { gn.removeAttribute("data-naslov"); gn.setAttribute("aria-label", t("novoNaslov")); }
    var q = {};
    location.search.replace(/^\?/, "").split("&").forEach(function (d) { var x = d.split("="); if (x[0]) q[x[0]] = x[1]; });
    robovi(q);
    prevedi();
    klic("lupaUcenje").then(function (p) { U.izbire = (p && p.izbire) || []; }).catch(function () {});
    uveljaviPostavitev();
    delilnik($("deliStolpca"), true);
    delilnik($("deliMediji"), false);
    vleciGlavo();
    vezi();
    poveziMedijIskanje();
    if (!most) { document.body.classList.add("brez-mosta"); return; }
    klic("zacetek").then(function (z) {
      z = z || {};
      jezik = BESEDILA[z.jezik] ? z.jezik : "en"; prevedi();
      if (z.ozadje && !document.body.classList.contains("v-oknu")) {
        document.documentElement.style.setProperty("--ozadje-slika", 'url("' + z.ozadje + '")');
      }
      nastaviVidez(z.videz);
      VL.sistemsko = !!z.vlecenjeDatotek;
      Z.mape = z.mape || []; Z.dom = (Z.mape[0] && Z.mape[0].pot) || "";
      Z.zaznamki = Array.isArray(z.zaznamki) ? z.zaznamki : [];
      Z.spletne = Array.isArray(z.spletne) ? z.spletne : [];
      zgradiStranDatotek();
      odpriVir({ vrsta: "nedavno" });
      preveriProstor();
      klic("predlogeDatotek").then(function (p) { predlogeDatotek = Array.isArray(p) ? p.slice(0, 12) : []; }).catch(function () {});
      naloziProgrameNaprav();
      medijZanka();
      osveziLink();
    }).catch(function () { zgradiStranDatotek(); });
  }

  // ------------------------------------------------------------------ DATOTEKE
  // D.naprave: naprave, ki delijo svoje datoteke (odpres jih); D.sprejmejo: naprave, ki sprejmejo datoteko (cilj
  // spusta in »Poslji na napravo«).
  var D = { vir: null, vse: [], stran: 0, razvrsti: "ime", smer: 1, izbran: -1, naprave: [], sprejmejo: [], nosilci: [],
            zahteva: 0, izbrani: {}, sidro: "" };

  // Izbira vec datotek: klik izbere eno, Ctrl+klik doda ali odvzame, Shift+klik (ali Shift+puscica) izbere obseg od
  // zadnje izbrane - tudi cez strani -, Ctrl+A vse. D.izbrani: kljuc vnosa -> vnos; D.izbran ostane vrstica s fokusom.
  function kljucVnosa(e) { return e.smeti ? "s:" + e.smeti : e.oddaljeno ? "o:" + e.id : "p:" + e.pot; }
  function izbraniVnosi() { return Object.keys(D.izbrani).map(function (k) { return D.izbrani[k]; }); }
  function jeIzbran(e) { return !!D.izbrani[kljucVnosa(e)]; }
  function pocistiIzbiro() { D.izbrani = {}; D.sidro = ""; }
  function izberiSamo(e) { D.izbrani = {}; D.sidro = kljucVnosa(e); D.izbrani[D.sidro] = e; }
  function preklopiIzbiro(e) {
    var k = kljucVnosa(e);
    if (D.izbrani[k]) delete D.izbrani[k]; else D.izbrani[k] = e;
    D.sidro = k;
  }
  function izberiObseg(e) {
    var s = filtrirani(), a = -1, b = -1, k = kljucVnosa(e);
    for (var i = 0; i < s.length; i++) { var ki = kljucVnosa(s[i]); if (ki === D.sidro) a = i; if (ki === k) b = i; }
    if (a < 0 || b < 0) { izberiSamo(e); return; }
    D.izbrani = {};
    for (var j = Math.min(a, b); j <= Math.max(a, b); j++) D.izbrani[kljucVnosa(s[j])] = s[j];
  }
  function izberiVse() {
    var s = filtrirani();
    D.izbrani = {};
    s.forEach(function (e) { D.izbrani[kljucVnosa(e)] = e; });
    D.sidro = s.length ? kljucVnosa(s[0]) : "";
  }
  // Izbrani, s katerimi se da delati na tem racunalniku (ne v Smeteh in ne na drugi napravi).
  function izbraniLokalni() { return izbraniVnosi().filter(function (e) { return e.pot && !e.oddaljeno && !e.smeti; }); }
  function steviloElementov(n) {
    if (jezik === "sl") {
      var m = n % 100;
      return n + " " + (m === 1 ? "element" : m === 2 ? "elementa" : (m === 3 || m === 4) ? "elementi" : "elementov");
    }
    return n + (n === 1 ? " item" : " items");
  }
  function prikaziIzbiro() {
    var ovoj = $("datStrani"), stari = ovoj.querySelector(".izbira"), v = izbraniVnosi();
    if (stari) stari.remove();
    if (v.length < 2) return;
    var skupaj = 0;
    v.forEach(function (e) { if (!e.mapa) skupaj += e.velikost || 0; });
    ovoj.insertBefore(el("span", "izbira", t("izbranoN", { n: steviloElementov(v.length) }) + (skupaj ? " · " + velikost(skupaj) : "")), ovoj.firstChild);
  }

  function zgradiStranDatotek() {
    var s = $("datStran"); s.innerHTML = "";
    function oznaka(b) { s.appendChild(el("p", "oznaka", b)); }
    function gumb(ime, vir, pikaOk) {
      var g = el("button"); g.type = "button";
      if (pikaOk != null) g.appendChild(el("i", "pika" + (pikaOk ? " ok" : "")));
      else g.appendChild(ikonaVrste(vir.vrsta === "naprava" ? "program" : "mapa"));
      g.appendChild(el("span", "napis", ime));
      g._vir = vir;
      g.addEventListener("click", function () { odpriVir(vir); });
      if (vir.vrsta === "lokalno") ciljSpusta(g, function () { return vir.pot; });
      s.appendChild(g);
      return g;
    }
    oznaka(t("pregled"));
    gumb(t("nedavno"), { vrsta: "nedavno" });
    gumb(t("priljubljeno"), { vrsta: "priljubljeno" });
    gumb(t("najvecje"), { vrsta: "najvecje" });
    gumb(t("smeti"), { vrsta: "smeti" });
    oznaka(t("mape"));
    // Kot pri obicajni temi (Nemo): domaca mapa, Namizje, uporabnikove mape in zaznamki (lastnik, 11. 10. 2026).
    Z.mape.forEach(function (m) {
      if (m.vrsta === "HOME") gumb(t("domov"), { vrsta: "lokalno", pot: m.pot });
      else if (["DESKTOP", "DOCUMENTS", "PICTURES", "VIDEOS", "MUSIC", "DOWNLOAD"].indexOf(m.vrsta) >= 0)
        gumb(BESEDILA[jezik][m.vrsta] ? t(m.vrsta) : m.ime, { vrsta: "lokalno", pot: m.pot });
    });
    (Z.zaznamki || []).forEach(function (m) { gumb(m.ime, { vrsta: "lokalno", pot: m.pot }).title = m.pot; });
    oznaka(t("naprave"));
    // Ta racunalnik = cel datotecni sistem (kot »Racunalnik« v Nemu); domaca mapa je zgoraj med Mapami.
    gumb(t("taRacunalnik"), { vrsta: "lokalno", pot: "/" }, true);
    // Nosilci (USB kljuci, zunanji in drugi diski, omrezna mesta): odpres jih kot mapo, desni klik = varno odstrani.
    D.nosilci.forEach(function (n) {
      var g = gumb(n.ime, { vrsta: "lokalno", pot: n.pot }, true);
      g.title = n.velikost ? t("prostoNa", { prosto: velikost(n.prosto) || "0", skupaj: velikost(n.velikost) }) : n.pot;
      if (n.naprava) g.addEventListener("contextmenu", function (ev) {
        ev.preventDefault();
        pokaziMeni([[t("odpri"), function () { odpriVir({ vrsta: "lokalno", pot: n.pot }); }], [t("izvrzi"), function () { izvrziNosilec(n); }]], ev.clientX, ev.clientY);
      });
    });
    // Naprave v Linku: klik pokaze njihove datoteke; na napravo, ki sprejme datoteko, lahko datoteke spustis (= poslji).
    var nastete = {};
    function gumbNaprave(n) {
      if (nastete[n.id]) return;
      nastete[n.id] = 1;
      var g = gumb(n.ime, { vrsta: "naprava", id: n.id, ime: n.ime, pot: [] }, true);
      if (D.sprejmejo.some(function (x) { return x.id === n.id; })) ciljPosiljanja(g, n);
    }
    D.naprave.forEach(gumbNaprave);
    D.sprejmejo.forEach(gumbNaprave);
    oznaciVir();
    if (!most) return;
    klic("napraveZDatotekami").then(function (naprave) {
      var prej = JSON.stringify(D.naprave);
      D.naprave = Array.isArray(naprave) ? naprave.filter(function (n) { return n && n.id; }) : [];
      if (JSON.stringify(D.naprave) !== prej) zgradiStranDatotek();
    }).catch(function () {});
    klic("napraveZaPosiljanje").then(function (naprave) {
      var prej = JSON.stringify(D.sprejmejo);
      D.sprejmejo = Array.isArray(naprave) ? naprave.filter(function (n) { return n && n.id; }) : [];
      if (JSON.stringify(D.sprejmejo) !== prej) zgradiStranDatotek();
    }).catch(function () {});
    osveziNosilce();
  }
  function osveziNosilce() {
    if (!most) return;
    klic("nosilci").then(function (nosilci) {
      var prej = JSON.stringify(D.nosilci.map(function (n) { return n.pot; }));
      var novi = Array.isArray(nosilci) ? nosilci.filter(function (n) { return n && n.pot; }) : [];
      var spremenjeno = JSON.stringify(novi.map(function (n) { return n.pot; })) !== prej;
      D.nosilci = novi;
      if (spremenjeno) zgradiStranDatotek();
    }).catch(function () {});
  }
  function izvrziNosilec(n) {
    klic("izvrziNosilec", [n.pot]).then(function (r) {
      if (r && r.ok) {
        obvesti(t("izvrzeno", { ime: n.ime }));
        if (D.vir && D.vir.vrsta === "lokalno" && String(D.vir.pot).indexOf(n.pot) === 0) odpriVir({ vrsta: "nedavno" });
      } else obvesti(r && r.napaka === "zaseden" ? t("izvrziZaseden", { ime: n.ime }) : t("niUspelo"));
      osveziNosilce();
    }).catch(function () { obvesti(t("niUspelo")); });
  }
  function enakVir(a, b) {
    if (!a || !b || a.vrsta !== b.vrsta) return false;
    if (a.vrsta === "lokalno") return a.pot === b.pot;
    if (a.vrsta === "naprava") return a.id === b.id;
    return true;
  }
  function oznaciVir() {
    document.querySelectorAll("#datStran button").forEach(function (g) {
      var v = g._vir, cur = D.vir;
      var da = cur && (enakVir(v, cur) || (v.vrsta === "lokalno" && cur.vrsta === "lokalno" && cur.koren === v.pot));
      g.setAttribute("aria-current", da ? "true" : "false");
    });
  }

  // Safeer OS spremlja pogled, ki ga plosca kaze: ko se v mapi (med nedavnimi, v Smeteh) kaj spremeni - tudi zaradi
  // drugega programa (prenos, Nemo, datoteka z druge naprave) -, pride dogodek »datoteke« in seznam preberemo znova.
  function pogledVira(vir) {
    return !vir ? "" : vir.vrsta === "lokalno" ? vir.pot : vir.vrsta === "nedavno" ? "@nedavno" : vir.vrsta === "smeti" ? "@smeti" : "";
  }
  function spremljajVir(vir) { if (most) klic("spremljajMapo", [pogledVira(vir)]).catch(function () {}); }
  function vnosiSmeti(r) {
    return ((r && r.elementi) || []).map(function (v) {
      return { ime: v.ime, pot: v.izvirna || v.pot, mapa: !!v.mapa, vrsta: v.vrsta, velikost: v.velikost || 0,
               spremenjeno: v.izbrisano || 0, smeti: v.id };
    });
  }
  function odtisVnosov(vnosi) {
    return (vnosi || []).map(function (e) {
      return kljucVnosa(e) + "|" + (e.ime || "") + "|" + (e.velikost || 0) + "|" + Math.round(e.spremenjeno || 0);
    }).join("\n");
  }
  // Tiha osvezitev: brez »Nalagam«, stran, izbira in fokus ostanejo. Ce se ni nic spremenilo, nicesar ne prerisemo.
  var tihoCaka = 0;
  function osveziVirTiho() {
    var vir = D.vir;
    if (!vir || !most || !pogledVira(vir)) return;
    // Med vlecenjem datotek seznama ne prerisemo (vrstica, ki jo uporabnik drzi, bi izginila): poskusimo malo pozneje.
    if (VL.poti.length) { clearTimeout(tihoCaka); tihoCaka = setTimeout(osveziVirTiho, 1200); return; }
    var st = D.zahteva;
    var branje = vir.vrsta === "lokalno" ? klic("mapa", [vir.pot]) : vir.vrsta === "nedavno" ? klic("nedavne") : klic("smeti");
    branje.then(function (r) {
      if (st !== D.zahteva || D.vir !== vir) return;                 // uporabnik je medtem odprl kaj drugega
      var vnosi;
      if (vir.vrsta === "lokalno") {
        if (!r || r.napaka) { odpriVir(vir); return; }                 // mape ni vec: obicajno odprtje pokaze stanje
        vnosi = r.elementi || [];
      } else if (vir.vrsta === "nedavno") vnosi = r || [];
      else vnosi = vnosiSmeti(r);
      if (!D.napaka && odtisVnosov(vnosi) === odtisVnosov(D.vse)) return;
      var vFokusu = document.activeElement && document.activeElement.closest ? document.activeElement.closest("#datVrstice tr") : null;
      var mesto = vFokusu ? vFokusu.sectionRowIndex : -1;
      var kljucFokusa = mesto >= 0 && D.vidni && D.vidni[mesto] ? kljucVnosa(D.vidni[mesto]) : "";
      var izbrani = {};
      vnosi.forEach(function (e) { var k = kljucVnosa(e); if (D.izbrani[k]) izbrani[k] = e; });
      D.izbrani = izbrani;
      if (D.sidro && !izbrani[D.sidro]) D.sidro = "";
      D.vse = vnosi; D.napaka = false;
      izrisiDatoteke();
      if (mesto >= 0) {
        var vrstice = $("datVrstice").rows, novo = -1;
        for (var i = 0; i < (D.vidni || []).length; i++) if (kljucVnosa(D.vidni[i]) === kljucFokusa) { novo = i; break; }
        if (novo < 0) novo = Math.min(mesto, vrstice.length - 1);
        if (novo >= 0 && vrstice[novo]) { D.izbran = novo; try { vrstice[novo].focus(); } catch (x) {} }
      }
    }).catch(function () {});
  }

  function odpriVir(vir) {
    D.vir = vir; D.stran = 0; D.izbran = -1; D.vse = []; pocistiIzbiro();
    if (vir.vrsta === "lokalno" && !vir.koren) vir.koren = vir.pot;
    oznaciVir();
    spremljajVir(vir);
    datSporocilo(t("nalagam"));
    $("datStanje").textContent = "";
    var st = ++D.zahteva;
    function prispelo(fn) { return function (r) { if (st === D.zahteva) fn(r); }; }
    if (vir.vrsta === "nedavno") {
      klic("nedavne").then(prispelo(function (r) { nastaviVnose(r || [], t("niNedavnih")); drobtine([t("nedavno")]); }))
        .catch(prispelo(function () { nastaviVnose([], t("niUspelo"), true); }));
    } else if (vir.vrsta === "najvecje") {
      // Za skupni prostor: najvecje datoteke v domaci mapi (pregled traja najvec 1,5 s, v ozadju).
      klic("najvecjeDatoteke").then(prispelo(function (r) { nastaviVnose(r || [], t("niVelikih")); drobtine([t("najvecje")]); }))
        .catch(prispelo(function () { nastaviVnose([], t("niUspelo"), true); }));
    } else if (vir.vrsta === "priljubljeno") {
      nastaviVnose(N.priljubljeneDat.slice(), t("niPriljubljenih")); drobtine([t("priljubljeno")]);
    } else if (vir.vrsta === "smeti") {
      // Smeti: stolpec Lokacija pove, kje je datoteka bila, cas pa, kdaj je bila izbrisana.
      klic("smeti").then(prispelo(function (r) {
        nastaviVnose(vnosiSmeti(r), t("praznoSmeti")); drobtine([t("smeti")]);
      })).catch(prispelo(function () { nastaviVnose([], t("niUspelo"), true); }));
    } else if (vir.vrsta === "lokalno") {
      klic("mapa", [vir.pot]).then(prispelo(function (r) {
        r = r || {};
        if (r.napaka) { nastaviVnose([], r.napaka === "ni_dovoljenja" ? t("niDovoljenja") : t("niMape"), true); }
        else {
          // Safeer OS vrne pravo pot mape (npr. brez koncne posevnice): spremljamo to.
          if (r.pot && r.pot !== vir.pot) { vir.pot = r.pot; spremljajVir(vir); }
          nastaviVnose(r.elementi || [], t("praznaMapa"));
        }
        drobtineLokalno(vir);
      })).catch(prispelo(function () { nastaviVnose([], t("niUspelo"), true); }));
    } else if (vir.vrsta === "naprava") {
      var mapa = vir.pot.length ? vir.pot[vir.pot.length - 1].id : "";
      drobtineNaprava(vir);
      klic("datotekeNaprave", [vir.id, mapa]).then(prispelo(function (r) {
        // Nedosegljiva ali nedeljena naprava: pokazemo stanje, nikoli starih podatkov.
        if (!r || !r.ok) { nastaviVnose([], t("napravaNeOdgovori"), true); $("datStanje").textContent = t("napravaNedosegljiva", { naprava: vir.ime }); return; }
        if (r.shared === false) { nastaviVnose([], t("napravaNeDeli"), true); return; }
        vir.streznik = r.server || ""; vir.kljuc = r.kljuc || "";
        var vnosi = (r.items || []).map(function (v) {
          return { ime: v.name || v.id, id: v.id, oddaljeno: true, naprava: vir.ime, mapa: v.type === "folder",
                   vrsta: vrstaOddaljenega(v.type), velikost: v.size || 0, spremenjeno: v.modified || v.mtime || 0, izvirnik: v };
        });
        nastaviVnose(vnosi, t("praznaMapa"));
        $("datStanje").textContent = t("napravaOsvezeno", { cas: cas(Date.now() / 1000) });
      })).catch(prispelo(function () { nastaviVnose([], t("napravaNeOdgovori"), true); }));
    }
  }
  function drobtine(deli) {
    var ol = $("drobtine"); ol.innerHTML = "";
    deli.forEach(function (d) {
      var li = el("li");
      if (typeof d === "string") li.textContent = d;
      else { var b = el("button", "", d.ime); b.type = "button"; b.addEventListener("click", d.klik); li.appendChild(b); }
      ol.appendChild(li);
    });
  }
  function drobtineLokalno(vir) {
    var koren = vir.koren || vir.pot, deli = [];
    var imeKorena = (Z.mape.filter(function (m) { return m.pot === koren; })[0] || {});
    var imeK = koren === "/" ? t("taRacunalnik") : imeKorena.vrsta === "HOME" ? t("domov")
      : (BESEDILA[jezik][imeKorena.vrsta] ? t(imeKorena.vrsta) : (koren.split("/").pop() || "/"));
    deli.push({ ime: imeK, klik: function () { odpriVir({ vrsta: "lokalno", pot: koren, koren: koren }); } });
    if (vir.pot.indexOf(koren) === 0 && vir.pot !== koren) {
      var pot = koren;
      vir.pot.slice(koren.length).split("/").filter(Boolean).forEach(function (del) {
        pot = pot.replace(/\/$/, "") + "/" + del;
        var p = pot;
        deli.push({ ime: del, klik: function () { odpriVir({ vrsta: "lokalno", pot: p, koren: koren }); } });
      });
    }
    var zadnji = deli.pop(); deli.push(zadnji.ime);
    drobtine(deli);
  }
  function drobtineNaprava(vir) {
    var deli = [{ ime: vir.ime, klik: function () { vir.pot = []; odpriVir(vir); } }];
    vir.pot.forEach(function (p, i) {
      deli.push({ ime: p.ime, klik: function () { vir.pot = vir.pot.slice(0, i + 1); odpriVir(vir); } });
    });
    var zadnji = deli.pop(); deli.push(zadnji.ime);
    drobtine(deli);
  }
  function datSporocilo(b, napaka) {
    var s = $("datSporocilo"); s.textContent = b || ""; s.hidden = !b; s.classList.toggle("napaka", !!napaka);
  }
  var prazenOpis = "";
  function nastaviVnose(vnosi, praznoBesedilo, napaka) {
    D.vse = vnosi; prazenOpis = praznoBesedilo; D.napaka = !!napaka;
    if (napaka) datSporocilo(praznoBesedilo, true); else datSporocilo("");
    izrisiDatoteke();
  }
  function filtrirani() {
    var besede = kljucIskanja($("datFilter").value).split(/\s+/).filter(Boolean), v = $("datVrsta").value;
    var r = D.vse.filter(function (e) {
      if (besede.length && !ujemaVse(e.ime, besede)) return false;
      if (v && (v === "mapa" ? !e.mapa : e.vrsta !== v)) return false;
      return true;
    });
    if (D.vir && D.vir.vrsta === "nedavno" && D.razvrsti === "ime" && D.smer === 1 && !D.rocno) return r; // nedavne: po casu
    if (D.vir && D.vir.vrsta === "najvecje" && !D.rocno) return r; // najvecje: ze urejene po velikosti
    if (D.vir && D.vir.vrsta === "smeti" && !D.rocno) return r; // smeti: nazadnje izbrisano najprej
    var k = D.razvrsti, s = D.smer;
    return r.sort(function (a, b) {
      if (a.mapa !== b.mapa) return a.mapa ? -1 : 1;
      var x = a[k], y = b[k];
      if (typeof x === "string") return x.localeCompare(y, jezik, { sensitivity: "base", numeric: true }) * s;
      return ((x || 0) - (y || 0)) * s;
    });
  }
  // Koliko vrstic gre v ploščo brez pomikanja.
  function vrsticNaStran() {
    var tb = $("datSeznam"), gl = document.querySelector(".dat-glavno");
    if (!gl || !gl.offsetParent) return 10;
    var vis = gl.getBoundingClientRect().height - document.querySelector(".dat-orodja").getBoundingClientRect().height
      - tb.tHead.getBoundingClientRect().height - $("datStrani").getBoundingClientRect().height - 8;
    var vzorec = tb.tBodies[0].rows[0];
    var h = vzorec ? vzorec.getBoundingClientRect().height : parseFloat(getComputedStyle(document.body).fontSize) * 2.05;
    return Math.max(1, Math.floor(vis / Math.max(h, 18)));
  }
  function izrisiDatoteke() {
    var tb = $("datVrstice");
    if (!tb) return;
    var seznam = filtrirani();
    tb.innerHTML = "";
    // en vzorcni red za meritev visine
    if (seznam.length) tb.appendChild(vrsticaDatoteke(seznam[0], 0));
    var naStran = vrsticNaStran();
    tb.innerHTML = "";
    var strani = Math.max(1, Math.ceil(seznam.length / naStran));
    var oznaci = -1;
    if (D.oznaci) {
      // Pravkar ustvarjen ali preimenovan vnos: pokazemo stran, kjer je, in ga oznacimo.
      for (var oi = 0; oi < seznam.length; oi++) if (seznam[oi].ime === D.oznaci) { oznaci = oi; break; }
      if (oznaci >= 0) {
        D.stran = Math.floor(oznaci / naStran); D.izbran = oznaci % naStran;
        // Pravkar prilepljeno ali ustvarjeno je izbrano (vec prilepljenih: vsi).
        var nova = D.oznaciVse && D.oznaciVse.length ? D.oznaciVse : [D.oznaci];
        pocistiIzbiro();
        seznam.forEach(function (x) { if (nova.indexOf(x.ime) >= 0) D.izbrani[kljucVnosa(x)] = x; });
        D.sidro = kljucVnosa(seznam[oznaci]);
      }
      D.oznaci = ""; D.oznaciVse = null;
    }
    D.stran = Math.min(D.stran, strani - 1);
    var od = D.stran * naStran, do_ = Math.min(seznam.length, od + naStran);
    D.vidni = seznam.slice(od, do_);
    D.vidni.forEach(function (e, i) {
      var vr = vrsticaDatoteke(e, i);
      if (oznaci >= 0 && i === D.izbran) { vr.classList.add("novo"); setTimeout(function () { try { vr.focus(); } catch (x) {} }, 0); }
      tb.appendChild(vr);
    });
    naloziSlicice();
    if (!seznam.length && !D.napaka && D.vse !== null) datSporocilo(D.vse.length ? t("niZadetkov") : prazenOpis);
    else if (!D.napaka) datSporocilo("");
    ostraniStrani($("datStrani"), od, do_, seznam.length, strani, D.stran, function (s) { D.stran = s; D.izbran = -1; izrisiDatoteke(); });
    prikaziIzbiro();
    document.querySelectorAll("#datSeznam th button").forEach(function (b) {
      if (b.getAttribute("data-razvrsti") === D.razvrsti && D.rocno) b.setAttribute("data-smer", D.smer > 0 ? "▲" : "▼");
      else b.removeAttribute("data-smer");
    });
  }
  function vrsticaDatoteke(e, i) {
    var tr = el("tr"); tr.tabIndex = 0; tr.setAttribute("aria-selected", jeIzbran(e) ? "true" : "false");
    var td = el("td"), c = el("div", "celica-ime");
    var ik = ikonaVrste(e.mapa ? "mapa" : e.vrsta);
    if (e.pot && !e.oddaljeno && !e.smeti && (e.vrsta === "slika" || e.vrsta === "video")) ik.setAttribute("data-slicica", e.pot);
    c.appendChild(ik); c.appendChild(el("span", "", e.ime));
    // Polno ime kot namig samo, ko je odrezano: sicer bi namig (WebKitGTK ga pokaze z zamikom, brez premika miske)
    // prekril meni desnega klika, ki se odpre pod kazalcem - tudi postavko »Pretvori v …«.
    td.appendChild(c); tr.appendChild(td);
    td.addEventListener("mouseenter", function () { var s = c.lastChild; td.title = s && s.scrollWidth > s.clientWidth + 1 ? e.ime : ""; });
    tr.appendChild(el("td", "st-vrsta", t("en_" + (e.mapa ? "mapa" : (IKONE_VRST[e.vrsta] ? e.vrsta : "drugo")))));
    var lok = el("td", "st-lok");
    if (e.oddaljeno) { var o = el("span", "oznaka-vira oddaljeno", e.naprava); lok.appendChild(o); }
    else lok.textContent = e.pot ? stranskoBesedilo(e.pot.replace(/\/[^/]*$/, "")) : "";
    tr.appendChild(lok);
    tr.appendChild(el("td", "st-vel", e.mapa ? "" : velikost(e.velikost)));
    tr.appendChild(el("td", "st-cas", cas(e.spremenjeno)));
    tr.addEventListener("click", function (ev) {
      D.izbran = i;
      if (ev.shiftKey) izberiObseg(e); else if (ev.ctrlKey || ev.metaKey) preklopiIzbiro(e); else izberiSamo(e);
      oznaciIzbrano();
    });
    tr.addEventListener("dblclick", function (ev) { if (!ev.ctrlKey && !ev.shiftKey && !ev.metaKey) odpriVnos(e); });
    // Povleci: izbrane datoteke (ali to vrstico) premaknes v mapo - vrstico mape ali mapo v stranskem seznamu.
    if (e.pot && !e.oddaljeno && !e.smeti) {
      tr.draggable = true;
      tr.addEventListener("dragstart", function (ev) {
        if (!jeIzbran(e)) { izberiSamo(e); D.izbran = i; oznaciIzbrano(); }
        VL.poti = izbraniLokalni().map(function (x) { return x.pot; });
        if (VL.sistemsko) {
          // Pravo vlecenje namizja (zacne ga Safeer OS): datoteke sprejmejo tudi drugi programi - Nemo, brskalnik,
          // posta. V Datotekah je spust se vedno premik (VL.poti); konec sporoci dogodek vlecenjeKoncano.
          ev.preventDefault();
          klic("zacniVlecenje", [VL.poti]).then(function (ok) { if (!ok) VL.poti = []; }, function () { VL.poti = []; });
          return;
        }
        // Brez njega ostane vlecenje znotraj Datotek. Drugim programom ne ponudimo nicesar: WebKitGTK bi ob seznamu
        // naslovov ponudil se spletno povezavo, iz katere Nemo naredi bliznjico namesto kopije.
        ev.dataTransfer.effectAllowed = "move";
        try { ev.dataTransfer.setData(VRSTA_VLECENJA, JSON.stringify(VL.poti)); } catch (x) { /* vlecenje deluje vseeno */ }
      });
      tr.addEventListener("dragend", function (ev) {
        koncajVlecenje(!!(ev.dataTransfer && ev.dataTransfer.dropEffect && ev.dataTransfer.dropEffect !== "none"));
      });
      if (e.mapa) ciljSpusta(tr, function () { return e.pot; });
    }
    tr.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") { ev.preventDefault(); odpriVnos(e); }
      else if (ev.key === " " && !(tipkano && Date.now() - tipkanoCas <= 900)) { ev.preventDefault(); predogled(e); }
      else if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
        ev.preventDefault();
        var n = i + (ev.key === "ArrowDown" ? 1 : -1), vr = $("datVrstice").rows;
        if (n >= 0 && n < vr.length) {
          D.izbran = n;
          // Shift razsiri izbiro do te vrstice, Ctrl premakne samo fokus, sicer je izbrana ta vrstica.
          if (ev.shiftKey) izberiObseg(D.vidni[n]); else if (!ev.ctrlKey) izberiSamo(D.vidni[n]);
          vr[n].focus(); oznaciIzbrano();
        }
      } else if (ev.key === "ContextMenu" || (ev.shiftKey && ev.key === "F10")) {
        ev.preventDefault(); var r = tr.getBoundingClientRect(); meniZaVrstico(e, i, r.left + 40, r.bottom);
      } else if (ev.key === "Backspace") { ev.preventDefault(); gorVMapo(); }
      else if (ev.key === "Escape" && Object.keys(D.izbrani).length) { pocistiIzbiro(); oznaciIzbrano(); }
      else if (ev.key === "F2" && !e.oddaljeno && !e.smeti) { ev.preventDefault(); odpriOknoNovo({ nacin: "preimenuj", pot: e.pot, ime: e.ime, mapa: e.mapa }); }
      else if (ev.key === "Delete" && !e.oddaljeno && !e.smeti) { ev.preventDefault(); vSmetiVec(zaDejanje(e)); }
      else if (ev.ctrlKey && !ev.shiftKey && !ev.altKey && !e.oddaljeno && !e.smeti && (ev.key === "c" || ev.key === "C")) { ev.preventDefault(); vOdlozisceVec(zaDejanje(e), false); }
      else if (ev.ctrlKey && !ev.shiftKey && !ev.altKey && !e.oddaljeno && !e.smeti && (ev.key === "x" || ev.key === "X")) { ev.preventDefault(); vOdlozisceVec(zaDejanje(e), true); }
      else if (ev.key.length === 1 && !ev.ctrlKey && !ev.altKey && !ev.metaKey && (ev.key !== " " || tipkano && Date.now() - tipkanoCas <= 900)) {
        ev.preventDefault(); skociNaIme(ev.key);
      }
    });
    tr.addEventListener("contextmenu", function (ev) { ev.preventDefault(); meniZaVrstico(e, i, ev.clientX, ev.clientY); });
    return tr;
  }
  // Tipkanje v seznamu skoci na prvo datoteko, ki se zacne z vtipkanim (tudi na drugi strani); premor zacne znova.
  var tipkano = "", tipkanoCas = 0;
  function skociNaIme(znak) {
    var zdaj = Date.now();
    tipkano = (zdaj - tipkanoCas > 900 ? "" : tipkano) + kljucIskanja(znak); tipkanoCas = zdaj;
    var s = filtrirani();
    for (var i = 0; i < s.length; i++) {
      if (kljucIskanja(s[i].ime).indexOf(tipkano) === 0) { D.oznaciVse = null; D.oznaci = s[i].ime; izrisiDatoteke(); return true; }
    }
    return false;
  }
  // Dejanje s tipkovnico velja za vse izbrane, ce je vrstica med njimi; sicer samo zanjo.
  function zaDejanje(e) {
    var lok = izbraniLokalni();
    return jeIzbran(e) && lok.length > 1 ? lok : [e];
  }
  // Desni klik na izbrano vrstico ohrani izbiro (meni za vse izbrane), na neizbrano izbere samo njo.
  function meniZaVrstico(e, i, x, y) {
    D.izbran = i;
    if (!jeIzbran(e)) izberiSamo(e);
    oznaciIzbrano();
    if (Object.keys(D.izbrani).length > 1) meniVec(x, y); else meniDatoteke(e, x, y);
  }
  function oznaciIzbrano() {
    Array.prototype.forEach.call($("datVrstice").rows, function (r, j) {
      r.setAttribute("aria-selected", D.vidni && D.vidni[j] && jeIzbran(D.vidni[j]) ? "true" : "false");
    });
    prikaziIzbiro();
  }
  function meniVec(x, y) {
    var vsi = izbraniVnosi(), lok = izbraniLokalni(), m = [];
    if (vsi.length && vsi.every(function (e) { return e.smeti; })) {
      m.push([t("obnoviN", { n: steviloElementov(vsi.length) }), function () { obnoviIzSmetiVec(vsi); }]);
      m.push(["—"]);
      m.push([t("izprazniSmeti"), izprazniSmeti]);
    } else if (lok.length) {
      var koliko = steviloElementov(lok.length);
      if (lok.every(function (e) { return !e.mapa; })) {
        m.push([t("odpriZ"), function () { odpriZ(lok[0], lok.map(function (e) { return e.pot; })); }]);
        m.push(["—"]);
      }
      m.push([t("kopirajN", { n: koliko }), function () { vOdlozisceVec(lok, false); }]);
      m.push([t("izreziN", { n: koliko }), function () { vOdlozisceVec(lok, true); }]);
      if (O.poti.length && D.vir && D.vir.vrsta === "lokalno") m.push([t("prilepi"), function () { prilepi(null); }]);
      m.push([t("vSmetiN", { n: koliko }), function () { vSmetiVec(lok); }]);
      var samoDatoteke = lok.filter(function (e) { return !e.mapa; });
      if (samoDatoteke.length) m.push([t("posljiNaNapravo"), function () { izberiNapravoInPoslji(samoDatoteke.map(function (e) { return e.pot; })); }]);
      m.push(["—"]);
    }
    m.push([t("pocistiIzbiro"), function () { pocistiIzbiro(); oznaciIzbrano(); }]);
    pokaziMeni(m, x, y);
  }

  // ------------------------------------------------------------------ RAZVELJAVI
  // Zadnja dejanja z datotekami (premik, kopija, v Smeti, preimenovanje, nova mapa ali datoteka) se dajo razveljaviti:
  // z gumbom v obvestilu ali s Ctrl+Z. Zapis dejanja sestavimo iz odgovora Safeer OS; razveljavitev nikoli nicesar ne
  // prepise in ne izbrise trajno (kopije in ustvarjeno gredo v Smeti).
  var RZ = [];
  function zapomniDejanje(zapis) {
    if (!zapis || !((zapis.pari && zapis.pari.length) || (zapis.idji && zapis.idji.length))) return null;
    RZ.push(zapis); if (RZ.length > 20) RZ.shift();
    return { ime: t("razveljavi"), naredi: function () { razveljavi(zapis); } };
  }
  function razveljavi(zapis) {
    zapis = zapis || RZ[RZ.length - 1];
    if (!zapis) { obvesti(t("nicZaRazveljaviti")); return; }
    RZ = RZ.filter(function (x) { return x !== zapis; });
    klic("razveljaviDatoteke", [zapis]).then(function (r) {
      r = r || {};
      var n = r.narejeno || 0, ne = (r.napake || []).length;
      obvesti(n && !ne ? t("razveljavljeno") : n ? t("delnoUspelo", { ok: n, ne: ne }) : t("razveljavitevNiUspela"));
      // Po razveljavljenem premiku ali preimenovanju so datoteke spet na starem mestu: tam jih oznacimo.
      if (n && (zapis.vrsta === "premik" || zapis.vrsta === "preimenovanje") && D.vir && D.vir.vrsta === "lokalno") {
        var tu = zapis.pari.filter(function (p) { return p[0].replace(/\/[^/]*$/, "") === D.vir.pot; })
          .map(function (p) { return p[0].split("/").pop(); });
        if (tu.length) { D.oznaciVse = tu; D.oznaci = tu[0]; }
      }
      if (D.vir) odpriVir(D.vir);
    }).catch(function () { obvesti(t("razveljavitevNiUspela")); });
  }

  // ------------------------------------------------------------------ POVLECI IN SPUSTI
  // Izbrane datoteke v mapo: vlecenje znotraj Datotek jih PREMAKNE, z drzano tipko Ctrl KOPIRA (ev.ctrlKey je med
  // vlecenjem v WebKitGTK vedno true, zato beremo, kaj dovoli vir: s Ctrl samo kopiranje - samoKopija). VL.poti: kaj
  // vlecemo iz tega seznama (med vlecenjem podatkov ni mogoce brati). Datoteke iz drugega programa (Nemo, namizje) se
  // v mapo KOPIRAJO: WebKitGTK strani njihovih poti ne pove (seznam naslovov je prazen), zato si jih zapomni Safeer OS -
  // dogodek vleceneDatoteke pove, koliko jih je (VL.zunanje), ob spustu pa jih stran prevzame z metodo spusceneDatoteke.
  // VL.sistemsko: vlecenje iz Datotek zacne Safeer OS kot pravo vlecenje namizja (X11).
  var VL = { poti: [], zunanje: 0, sistemsko: false };
  var VRSTA_VLECENJA = "application/x-safeer-datoteke";
  function vrsteSpusta(ev) { return ev.dataTransfer && ev.dataTransfer.types ? Array.prototype.slice.call(ev.dataTransfer.types) : []; }
  // Vlecenje iz tega seznama (ne iz drugega programa): pove ga nasa vrsta podatkov, med vlecenjem tudi VL.poti.
  function jeNaseVlecenje(ev) { return VL.poti.length > 0 || vrsteSpusta(ev).indexOf(VRSTA_VLECENJA) >= 0; }
  function samoKopija(ev) { return !!ev.dataTransfer && ev.dataTransfer.effectAllowed === "copy"; }
  // Konec vlecenja iz Datotek. Nekateri pogoni ga sporocijo pred spustom, zato stanje pobrisemo z zamikom. Ce spusta
  // nismo prevzeli mi (datoteke so sle v drug program, ki jih je morda premaknil), seznam osvezimo.
  function koncajVlecenje(sprejeto) {
    setTimeout(function () {
      var zunaj = VL.poti.length > 0 && sprejeto;
      VL.poti = []; pocistiCilje();
      if (zunaj && D.vir && D.vir.vrsta === "lokalno") odpriVir(D.vir);
    }, 700);
  }
  function pocistiCilje() {
    Array.prototype.forEach.call(document.querySelectorAll(".spusti"), function (x) { x.classList.remove("spusti"); });
  }
  function jeZunanjeVlecenje(ev) {
    if (VL.poti.length || !VL.zunanje) return false;
    var vrste = vrsteSpusta(ev);
    return vrste.indexOf("Files") >= 0 || vrste.indexOf("text/uri-list") >= 0;
  }
  function jeSpustDatotek(ev) { return jeNaseVlecenje(ev) || jeZunanjeVlecenje(ev); }
  function potiIzSpusta(ev) {
    if (VL.poti.length) return VL.poti.slice();
    try {
      var nase = JSON.parse(ev.dataTransfer.getData(VRSTA_VLECENJA) || "[]");
      if (Array.isArray(nase) && nase.length) return nase.map(String);
    } catch (x) { /* ni nase vlecenje */ }
    return [];
  }
  // Ali je spust teh poti v mapo smiseln: ne v mapo, kjer ze so, ne mape vase.
  function smiselnSpust(poti, cilj) {
    return poti.some(function (p) { return p !== cilj && p.replace(/\/[^/]*$/, "") !== cilj && cilj.indexOf(p + "/") !== 0; });
  }
  function ciljSpusta(element, potCilja) {
    element.addEventListener("dragover", function (ev) {
      var cilj = potCilja();
      if (!cilj || !jeSpustDatotek(ev)) return;
      if (VL.poti.length && !smiselnSpust(VL.poti, cilj)) return;
      ev.preventDefault(); ev.stopPropagation();
      ev.dataTransfer.dropEffect = jeNaseVlecenje(ev) && !samoKopija(ev) ? "move" : "copy";
      element.classList.add("spusti");
    });
    element.addEventListener("dragleave", function () { element.classList.remove("spusti"); });
    element.addEventListener("drop", function (ev) {
      var cilj = potCilja();
      element.classList.remove("spusti");
      if (!cilj || !jeSpustDatotek(ev)) return;
      ev.preventDefault(); ev.stopPropagation();
      function smiselne(poti) {
        return poti.filter(function (p) { return p !== cilj && p.replace(/\/[^/]*$/, "") !== cilj && cilj.indexOf(p + "/") !== 0; });
      }
      if (jeNaseVlecenje(ev)) {
        var poti = smiselne(potiIzSpusta(ev));
        VL.poti = [];
        if (poti.length) premakniAliKopiraj(poti, cilj, !samoKopija(ev));
        return;
      }
      VL.zunanje = 0;
      klic("spusceneDatoteke").then(function (zunanje) {
        var z = smiselne((Array.isArray(zunanje) ? zunanje : []).map(String));
        if (z.length) premakniAliKopiraj(z, cilj, false);
      }, function () {});
    });
  }
  // Spust na napravo v stranskem seznamu = poslji. Datoteke ostanejo, kjer so (nic se ne premakne).
  function ciljPosiljanja(element, naprava) {
    element.title = t("posljiNaNapravo").replace(/\s\u2026$/, "") + ": " + naprava.ime;
    element.addEventListener("dragover", function (ev) {
      if (!jeSpustDatotek(ev)) return;
      ev.preventDefault(); ev.stopPropagation();
      // Vlecenje iz Datotek dovoli samo premik (effectAllowed); spust mora izbrati dovoljen ucinek, sicer ga ni.
      ev.dataTransfer.dropEffect = ev.dataTransfer.effectAllowed === "move" ? "move" : "copy";
      element.classList.add("spusti");
    });
    element.addEventListener("dragleave", function () { element.classList.remove("spusti"); });
    element.addEventListener("drop", function (ev) {
      element.classList.remove("spusti");
      if (!jeSpustDatotek(ev)) return;
      ev.preventDefault(); ev.stopPropagation();
      if (jeNaseVlecenje(ev)) {
        var poti = potiIzSpusta(ev);
        VL.poti = [];
        posljiNaNapravo(naprava, poti);
        return;
      }
      VL.zunanje = 0;
      klic("spusceneDatoteke").then(function (zunanje) {
        posljiNaNapravo(naprava, (Array.isArray(zunanje) ? zunanje : []).map(String));
      }, function () {});
    });
  }
  // Razlog neuspeha v jeziku strani; neznana koda pokaze sporocilo Controla.
  function razlogPosiljanja(r) {
    var k = "posN_" + ((r && r.koda) || "");
    if ((BESEDILA[jezik] && BESEDILA[jezik][k]) || BESEDILA.en[k]) return t(k, { najvec: (r && r.najvec) || "" });
    return (r && (r.sporocilo || r.message || r.koda)) || t("niUspelo");
  }
  function besediloPosiljanja(r, naprava) {
    var ime = r.naprava || naprava.ime;
    if (r.stanje === "posiljam") {
      return r.datotek > 1 ? t("posPosiljamN", { naprava: ime, k: Math.min(r.datotek, (r.poslanih || 0) + 1), n: r.datotek, ime: r.ime, odst: r.odstotek || 0 })
                           : t("posPosiljam", { naprava: ime, ime: r.ime, odst: r.odstotek || 0 });
    }
    if (r.stanje === "poslano") {
      return (r.datotek > 1 ? t("posPoslanoN", { naprava: ime, n: steviloElementov(r.datotek) }) : t("posPoslano", { naprava: ime, ime: r.ime })) +
        "";
    }
    return t("posNapaka", { naprava: ime, razlog: razlogPosiljanja(r) });
  }
  // Datoteke odda Safeer Control (isto kot »Poslji datoteko« v njem); tu spremljamo napredek do konca.
  function posljiNaNapravo(naprava, poti) {
    poti = (poti || []).filter(Boolean);
    if (!poti.length) return;
    obvesti(t("posPosiljam", { naprava: naprava.ime, ime: poti[0].split("/").pop(), odst: 0 }));
    klic("posljiNapravi", [naprava.id, poti]).then(function (r) {
      if (!r || !r.ok) { obvesti(t("posNapaka", { naprava: naprava.ime, razlog: razlogPosiljanja(r) })); return; }
      obvesti(besediloPosiljanja(r, naprava));
      if (r.stanje === "posiljam") spremljajPosiljanje(r.id, naprava);
    }).catch(function () { obvesti(t("posNapaka", { naprava: naprava.ime, razlog: t("niUspelo") })); });
  }
  function spremljajPosiljanje(id, naprava) {
    var brezOdgovora = 0;
    function korak() {
      klic("posljiStanje", [id]).then(function (r) {
        if (!r || !r.ok) {
          if (++brezOdgovora > 5) { obvesti(t("posNapaka", { naprava: naprava.ime, razlog: razlogPosiljanja(r) })); return; }
          setTimeout(korak, 1000); return;
        }
        brezOdgovora = 0;
        obvesti(besediloPosiljanja(r, naprava));
        if (r.stanje === "posiljam") setTimeout(korak, 600);
      }).catch(function () {
        if (++brezOdgovora > 5) { obvesti(t("posNapaka", { naprava: naprava.ime, razlog: t("niUspelo") })); return; }
        setTimeout(korak, 1000);
      });
    }
    setTimeout(korak, 400);
  }
  // »Poslji na napravo …« iz menija: izbira naprave, ki sprejme datoteko.
  function izberiNapravoInPoslji(poti) {
    poti = (poti || []).filter(Boolean);
    if (!poti.length) return;
    klic("napraveZaPosiljanje").then(function (naprave) {
      naprave = (Array.isArray(naprave) ? naprave : []).filter(function (n) { return n && n.id; });
      if (!naprave.length) { obvesti(t("posNiNaprav")); return; }
      var naslov = t("posljiNaNapravo").replace(/\s\u2026$/, "");
      var ovoj = el("div", "meni lastnosti odpri-z"); ovoj.setAttribute("role", "dialog"); ovoj.setAttribute("aria-label", naslov);
      ovoj.appendChild(el("p", "meni-naslov", naslov));
      ovoj.appendChild(el("p", "lastnosti-ime", poti.length > 1 ? t("izbranoN", { n: steviloElementov(poti.length) }) : poti[0].split("/").pop()));
      var seznam = el("div", "odpri-z-seznam");
      function zapri() { ovoj.remove(); document.removeEventListener("keydown", esc, true); }
      function esc(ev) { if (ev.key === "Escape") { ev.preventDefault(); zapri(); } }
      naprave.forEach(function (n) {
        var b = el("button"); b.type = "button";
        b.appendChild(ikonaVrste("naprava"));
        b.appendChild(el("span", "ime", n.ime));
        b.addEventListener("click", function () { zapri(); posljiNaNapravo(n, poti); });
        seznam.appendChild(b);
      });
      ovoj.appendChild(seznam);
      var g = el("button", "zapri", t("zapri")); g.type = "button"; g.addEventListener("click", zapri);
      ovoj.appendChild(g);
      document.addEventListener("keydown", esc, true);
      document.body.appendChild(ovoj);
      seznam.querySelector("button").focus();
    }).catch(function () { obvesti(t("niUspelo")); });
  }
  function premakniAliKopiraj(poti, cilj, premakni) {
    obvesti(t(premakni ? "premikam" : "kopiram"));
    klic("prilepiDatoteke", [poti, cilj, !!premakni]).then(function (r) {
      r = r || {};
      var narejeno = r.narejeno || [], napake = r.napake || [];
      var nazaj = zapomniDejanje({ vrsta: premakni ? "premik" : "kopija", pari: r.pari || [] });
      if (narejeno.length && !napake.length) {
        obvesti(t(premakni ? "premaknjenoV" : "kopiranoV", { mapa: cilj.replace(/\/$/, "").split("/").pop() || "/",
          ime: narejeno.length === 1 ? String(narejeno[0]).split("/").pop() : steviloElementov(narejeno.length) }), nazaj);
      } else if (narejeno.length) obvesti(t("delnoUspelo", { ok: narejeno.length, ne: napake.length }), nazaj);
      else {
        var koda = r.napaka || (napake[0] || {}).napaka || "";
        obvesti(BESEDILA[jezik]["prilepiNapaka_" + koda] ? t("prilepiNapaka_" + koda) : t("niUspelo"));
      }
      // Kar je prislo v odprto mapo, je po osvezitvi izbrano.
      if (narejeno.length && D.vir && D.vir.vrsta === "lokalno" && D.vir.pot === cilj) {
        D.oznaciVse = narejeno.map(function (p) { return String(p).split("/").pop(); }); D.oznaci = D.oznaciVse[0];
      }
      if (D.vir) odpriVir(D.vir);
    }).catch(function () { obvesti(t("niUspelo")); });
  }
  function gorVMapo() {
    var v = D.vir; if (!v) return;
    if (v.vrsta === "lokalno" && v.pot !== v.koren) odpriVir({ vrsta: "lokalno", pot: v.pot.replace(/\/[^/]+\/?$/, "") || "/", koren: v.koren });
    else if (v.vrsta === "naprava" && v.pot.length) { v.pot.pop(); odpriVir(v); }
  }
  // Slicice za slike in videe v vidnih vrsticah (iz predpomnilnika namizja ali pomanjsane sproti, v ozadju).
  var slicicePredpomnilnik = {}, sliciceZahteva = 0;
  function vstaviSlicico(ikona, naslov) {
    var img = el("img", "slicica"); img.alt = ""; img.loading = "lazy";
    img.onerror = function () { img.remove(); };
    img.onload = function () { ikona.classList.add("s-slicico"); };
    img.src = naslov; ikona.appendChild(img);
  }
  function naloziSlicice() {
    if (!most) return;
    var ikone = Array.prototype.slice.call(document.querySelectorAll("#datVrstice [data-slicica]")), manjka = [];
    ikone.forEach(function (ik) {
      var pot = ik.getAttribute("data-slicica");
      if (slicicePredpomnilnik[pot]) vstaviSlicico(ik, slicicePredpomnilnik[pot]);
      else if (slicicePredpomnilnik[pot] !== "") manjka.push(pot);
    });
    if (!manjka.length) return;
    var st = ++sliciceZahteva;
    klic("sliciceDatotek", [manjka]).then(function (r) {
      r = r || {};
      manjka.forEach(function (pot) { slicicePredpomnilnik[pot] = r[pot] || ""; });
      if (st !== sliciceZahteva) return;
      Array.prototype.forEach.call(document.querySelectorAll("#datVrstice [data-slicica]"), function (ik) {
        var naslov = slicicePredpomnilnik[ik.getAttribute("data-slicica")];
        if (naslov && !ik.querySelector("img")) vstaviSlicico(ik, naslov);
      });
    }).catch(function () {});
  }

  // ------------------------------------------------------------------ ODLOZISCE, SMETI, LASTNOSTI
  var O = { poti: [], rezi: false, ime: "" };
  function vOdlozisce(e, rezi) { vOdlozisceVec([e], rezi); }
  function vOdlozisceVec(vnosi, rezi) {
    vnosi = vnosi.filter(function (e) { return e && e.pot && !e.oddaljeno && !e.smeti; });
    if (!vnosi.length) return;
    O.poti = vnosi.map(function (e) { return e.pot; }); O.rezi = !!rezi;
    O.ime = vnosi.length === 1 ? vnosi[0].ime : steviloElementov(vnosi.length);
    obvesti(t(rezi ? "izrezano" : "kopirano", { ime: O.ime }));
  }
  function prilepi(vMapo) {
    if (!O.poti.length) return;
    var cilj = vMapo || kamNovo(), rezi = O.rezi, ime = O.ime;
    obvesti(t(rezi ? "premikam" : "kopiram"));
    klic("prilepiDatoteke", [O.poti, cilj, rezi]).then(function (r) {
      r = r || {};
      var narejeno = r.narejeno || [], spodletele = r.napake || [];
      if (narejeno.length) {
        var nazaj = zapomniDejanje({ vrsta: rezi ? "premik" : "kopija", pari: r.pari || [] });
        if (spodletele.length) obvesti(t("delnoUspelo", { ok: narejeno.length, ne: spodletele.length }), nazaj);
        else obvesti(t(rezi ? "premaknjeno" : "prilepljeno", { ime: narejeno.length === 1 ? String(narejeno[0]).split("/").pop() : ime }), nazaj);
        if (rezi) { O.poti = []; O.ime = ""; }
        D.oznaciVse = narejeno.map(function (p) { return String(p).split("/").pop(); });
        D.oznaci = D.oznaciVse[0];
      } else {
        var koda = r.napaka || ((r.napake || [])[0] || {}).napaka || "";
        // Premik v mapo, kjer datoteka ze je, ni napaka: nic ni bilo treba narediti.
        if (r.ok && !koda) obvesti(t("premaknjeno", { ime: ime }));
        else obvesti(BESEDILA[jezik]["prilepiNapaka_" + koda] ? t("prilepiNapaka_" + koda) : t("niUspelo"));
      }
      if (D.vir) odpriVir(D.vir);
    }).catch(function () { obvesti(t("niUspelo")); });
  }
  function obnoviIzSmeti(e) {
    klic("obnoviIzSmeti", [e.smeti]).then(function (r) {
      obvesti(r && r.ok ? t("obnovljeno", { ime: e.ime }) : t("niUspelo"));
      if (D.vir) odpriVir(D.vir);
    }).catch(function () { obvesti(t("niUspelo")); });
  }
  // Vec datotek zapored (ne hkrati): dve datoteki z istim imenom iz razlicnih map bi se v Smeteh sicer lahko stepli za ime.
  function zapored(vnosi, dejanje) {
    var izidi = [];
    return vnosi.reduce(function (veriga, e) {
      return veriga.then(function () { return dejanje(e); }).then(function (r) { izidi.push(!!(r && r.ok)); })
        .catch(function () { izidi.push(false); });
    }, Promise.resolve()).then(function () { return izidi; });
  }
  function obnoviIzSmetiVec(vnosi) {
    zapored(vnosi, function (e) { return klic("obnoviIzSmeti", [e.smeti]); }).then(function (izidi) {
      var ok = izidi.filter(Boolean).length;
      obvesti(ok === vnosi.length ? t("obnovljenoN", { ime: steviloElementov(ok) }) : t("delnoUspelo", { ok: ok, ne: vnosi.length - ok }));
      if (D.vir) odpriVir(D.vir);
    });
  }
  function vSmetiVec(vnosi) {
    vnosi = vnosi.filter(function (e) { return e && e.pot && !e.oddaljeno && !e.smeti; });
    if (!vnosi.length) return;
    if (vnosi.length === 1) { vSmeti(vnosi[0]); return; }
    var idji = [];
    zapored(vnosi, function (e) {
      return klic("vSmeti", [e.pot]).then(function (r) { if (r && r.ok && r.id) idji.push(r.id); return r; });
    }).then(function (izidi) {
      var ok = izidi.filter(Boolean).length, vSmeteh = {};
      vnosi.forEach(function (e, i) { if (izidi[i]) vSmeteh[e.pot] = true; });
      N.priljubljeneDat = N.priljubljeneDat.filter(function (p) { return !vSmeteh[p.pot]; }); shrani();
      obvesti(ok === vnosi.length ? t("vSmetiVecOk", { ime: steviloElementov(ok) }) : ok ? t("delnoUspelo", { ok: ok, ne: vnosi.length - ok }) : t("nSmeti"),
              zapomniDejanje({ vrsta: "smeti", idji: idji }));
      if (D.vir) odpriVir(D.vir);
    });
  }
  function izprazniSmeti() {
    // Trajni izbris potrdi sistemsko okno Safeer OS (ne stran); odgovor pride, ko je konec.
    klic("izprazniSmeti").then(function (r) {
      if (r && r.potrjeno) obvesti(t("smetiIzpraznjene"));
      if (D.vir && D.vir.vrsta === "smeti") odpriVir(D.vir);
    }).catch(function () { obvesti(t("niUspelo")); });
  }
  function lastnosti(e) {
    klic("lastnostiDatoteke", [e.pot]).then(function (l) {
      if (!l || !l.ok) { obvesti(t("niUspelo")); return; }
      var ovoj = el("div", "meni lastnosti"); ovoj.setAttribute("role", "dialog"); ovoj.setAttribute("aria-label", t("lastnosti"));
      ovoj.appendChild(el("p", "meni-naslov", t("lastnosti")));
      ovoj.appendChild(el("p", "lastnosti-ime", l.ime));
      var dl = el("dl");
      function vr(k, v) { if (v === "" || v == null) return; dl.appendChild(el("dt", "", k)); dl.appendChild(el("dd", "", String(v))); }
      vr(t("lVrsta"), t("en_" + (l.mapa ? "mapa" : (IKONE_VRST[l.vrsta] ? l.vrsta : "drugo"))) + (l.mime && !l.mapa ? " · " + l.mime : ""));
      vr(t("lVelikost"), velikost(l.velikost) || "0 kB");
      if (l.mapa) vr(t("lVsebuje"), t("lElementov", { n: l.vsebuje || 0 }));
      vr(t("lKje"), stranskoBesedilo(l.pot.replace(/\/[^/]*$/, "") || "/"));
      vr(t("lSpremenjeno"), new Date(l.spremenjeno * 1000).toLocaleString(LOKALE[jezik] || "sl-SI"));
      vr(t("lPravice"), l.pravice + " · " + l.lastnik);
      if (l.povezava != null) vr(t("lPovezava"), l.povezava);
      ovoj.appendChild(dl);
      var g = el("button", "", t("zapri")); g.type = "button"; g.addEventListener("click", zapri);
      ovoj.appendChild(g);
      function zapri() { ovoj.remove(); document.removeEventListener("keydown", esc, true); }
      function esc(ev) { if (ev.key === "Escape" || ev.key === "Enter") { ev.preventDefault(); zapri(); } }
      document.addEventListener("keydown", esc, true);
      document.body.appendChild(ovoj); g.focus();
    }).catch(function () { obvesti(t("niUspelo")); });
  }

  // »Odpri z ...«: programi, ki so se v namizju prijavili za to vrsto datoteke (privzeti prvi), »Drug program ...«
  // pokaze vse iz menija. Kljukica nastavi izbrani program za privzetega - v vsem namizju, ne samo v Safeer OS.
  function odpriZ(e, poti) {
    poti = poti && poti.length ? poti : [e.pot];
    klic("programiZaDatoteko", [poti[0]]).then(function (r) {
      if (!r || !r.ok) { obvesti(t("niUspelo")); return; }
      var ovoj = el("div", "meni lastnosti odpri-z"); ovoj.setAttribute("role", "dialog"); ovoj.setAttribute("aria-label", t("odpriZ"));
      ovoj.appendChild(el("p", "meni-naslov", t("odpriZ")));
      ovoj.appendChild(el("p", "lastnosti-ime", poti.length > 1 ? t("izbranoN", { n: steviloElementov(poti.length) }) : e.ime));
      var seznam = el("div", "odpri-z-seznam"), vedno = null;
      function zapri() { ovoj.remove(); document.removeEventListener("keydown", esc, true); }
      function esc(ev) { if (ev.key === "Escape") { ev.preventDefault(); zapri(); } }
      function izberi(p) {
        var trajno = !!(vedno && vedno.checked);
        zapri();
        klic("odpriZ", [poti, p.id, trajno]).then(function (o) {
          if (!o || !o.ok) obvesti(t("niUspelo"));
          else if (o.privzet) obvesti(t("odslejZ", { ime: p.ime }));
        }).catch(function () { obvesti(t("niUspelo")); });
      }
      function napolni(programi) {
        seznam.textContent = "";
        if (!programi.length) seznam.appendChild(el("p", "prazno", t("niProgramaZaVrsto")));
        programi.forEach(function (p) {
          var b = el("button"); b.type = "button";
          var znan = P.lokalni.filter(function (x) { return x.id === p.id; })[0];
          b.appendChild(slikaAliCrka(znan ? znan.ikona : "", p.ime));
          b.appendChild(el("span", "ime", p.ime));
          if (p.privzet) b.appendChild(el("span", "privzet", t("privzetProgram")));
          b.addEventListener("click", function () { izberi(p); });
          seznam.appendChild(b);
        });
      }
      napolni(r.programi || []);
      ovoj.appendChild(seznam);
      var drug = el("button", "drug", t("drugProgram")); drug.type = "button";
      drug.addEventListener("click", function () {
        var privzeti = (r.programi || []).filter(function (p) { return p.privzet; })[0];
        drug.disabled = true;
        // Samo programi, ki znajo sprejeti datoteko (brez nastavitev namizja ipd.).
        klic("programiZaOdpiranje").then(function (vsi) {
          napolni((Array.isArray(vsi) ? vsi : []).map(function (p) {
            return { id: String(p.id), ime: String(p.ime || p.id), privzet: !!privzeti && privzeti.id === p.id };
          }));
          drug.remove();
          var prvi = seznam.querySelector("button"); if (prvi) prvi.focus();
        }).catch(function () { drug.disabled = false; obvesti(t("niUspelo")); });
      });
      ovoj.appendChild(drug);
      if (r.vrsta) {
        var l = el("label", "odpri-z-vedno"); vedno = el("input"); vedno.type = "checkbox";
        l.appendChild(vedno); l.appendChild(el("span", "", t("vednoSTem")));
        ovoj.appendChild(l);
      }
      var g = el("button", "zapri", t("zapri")); g.type = "button"; g.addEventListener("click", zapri);
      ovoj.appendChild(g);
      document.addEventListener("keydown", esc, true);
      document.body.appendChild(ovoj);
      (seznam.querySelector("button") || g).focus();
    }).catch(function () { obvesti(t("niUspelo")); });
  }

  function odpriVnos(e) {
    if (e.smeti) { var vrs = $("datVrstice").rows[D.izbran], rr = vrs ? vrs.getBoundingClientRect() : { left: 80, bottom: 200 }; meniDatoteke(e, rr.left + 40, rr.bottom); return; }
    if (e.oddaljeno) {
      var v = D.vir;
      if (e.mapa) { v.pot.push({ id: e.id, ime: e.ime }); odpriVir(v); return; }
      if (e.vrsta !== "zvok" && e.vrsta !== "video") { obvesti(t("odpiramNaNapravi")); return; }
      if (!v.streznik) { obvesti(t("napravaNeOdgovori")); return; }
      var predvajljivi = D.vse.filter(function (x) { return !x.mapa && (x.vrsta === "zvok" || x.vrsta === "video"); });
      var seznam = predvajljivi.map(function (x) { return x.izvirnik; });
      klic("predvajajZNaprave", [v.streznik, v.kljuc, seznam, predvajljivi.indexOf(e), v.ime, v.id]).then(function (ok) {
        if (!ok) obvesti(t("niUspelo")); else medijOsvezi();
      }).catch(function () { obvesti(t("niUspelo")); });
      return;
    }
    if (e.mapa) { odpriVir({ vrsta: "lokalno", pot: e.pot, koren: D.vir && D.vir.vrsta === "lokalno" ? D.vir.koren : e.pot }); return; }
    var poskus = (e.vrsta === "zvok" || e.vrsta === "video") ? klic("odpriLokalniMedij", [e.pot]) : Promise.resolve(false);
    poskus.then(function (ok) {
      if (ok) { medijOsvezi(); return; }
      return klic("odpriDatoteko", [e.pot]).then(function (ok2) { if (!ok2) obvesti(t("niUspelo")); });
    }).catch(function () { obvesti(t("niUspelo")); });
  }
  function jePriljubljena(e) { return N.priljubljeneDat.some(function (p) { return p.pot === e.pot; }); }
  function meniDatoteke(e, x, y) {
    var m = [];
    if (e.smeti) {
      m.push([t("obnovi"), function () { obnoviIzSmeti(e); }]);
      m.push(["—"]);
      m.push([t("izprazniSmeti"), izprazniSmeti]);
      pokaziMeni(m, x, y);
      return;
    }
    m.push([t("odpri"), function () { odpriVnos(e); }]);
    if (!e.oddaljeno) {
      m.push([t("odpriZ"), function () { odpriZ(e); }]);
      m.push([t("predogled"), function () { predogled(e); }, e.mapa]);
      m.push([t("pokaziVMapi"), function () { klic("pokaziVMapi", [e.pot]); }]);
      m.push(jePriljubljena(e)
        ? [t("odstraniPriljubljeno"), function () {
            N.priljubljeneDat = N.priljubljeneDat.filter(function (p) { return p.pot !== e.pot; }); shrani();
            if (D.vir && D.vir.vrsta === "priljubljeno") odpriVir(D.vir);
          }]
        : [t("dodajPriljubljeno"), function () {
            N.priljubljeneDat.push({ ime: e.ime, pot: e.pot, mapa: !!e.mapa, vrsta: e.mapa ? "mapa" : e.vrsta,
                                     velikost: e.velikost || 0, spremenjeno: e.spremenjeno || 0 });
            N.priljubljeneDat = N.priljubljeneDat.slice(-60); shrani();
          }]);
      m.push(["—"]);
      m.push([t("kopiraj"), function () { vOdlozisce(e, false); }]);
      m.push([t("izrezi"), function () { vOdlozisce(e, true); }]);
      if (O.poti.length) m.push([t(e.mapa ? "prilepiV" : "prilepi"), function () { prilepi(e.mapa ? e.pot : null); }]);
      m.push([t("preimenujMeni"), function () { odpriOknoNovo({ nacin: "preimenuj", pot: e.pot, ime: e.ime, mapa: e.mapa }); }]);
      m.push([t("vSmeti"), function () { vSmeti(e); }]);
      m.push([t("lastnosti"), function () { lastnosti(e); }]);
      if (!e.mapa) m.push([t("posljiNaNapravo"), function () { izberiNapravoInPoslji([e.pot]); }]);
      if (!e.mapa) m.push([t("shraniNaNapravo"), function () { shraniNaNapravo(e); }]);
      if (!e.mapa && e.vrsta === "video") m.push([t("pretvori"), function () { pretvoriVideo(e); }]);
      if (!e.mapa && pretvorljiva(e.ime))
        m.push([t("pretvoriV"), function () { pretvoriDatoteko(e); }]);
      if (e.mapa) m.push([t("pretvoriMapo"), function () { pretvoriMapo(e); }]);
      m.push(["—"]);
      postavkeNovo(m, e.mapa ? e.pot : null);
    }
    pokaziMeni(m, x, y);
  }

  // ------------------------------------------------------------------ NOVA MAPA / DATOTEKA
  var VRSTE_NOVIH = [["prazna", "vPrazna", "privzetoDatoteka"], ["besedilo", "vBesedilo", "privzetoDatoteka"],
                     ["dokument", "vDokument", "privzetoDokument"], ["preglednica", "vPreglednica", "privzetoPreglednica"],
                     ["predstavitev", "vPredstavitev", "privzetoPredstavitev"]];
  var predlogeDatotek = [];
  /** Privzeto mesto za novo: odprta krajevna mapa, sicer domaca mapa (Nedavno, Priljubljeno, naprava). */
  function kamNovo() {
    var v = D.vir;
    if (v && v.vrsta === "lokalno" && v.pot) return v.pot;
    return Z.dom || "~";
  }
  function postavkeNovo(m, vMapo) {
    var kam = vMapo || kamNovo();
    m.push([t("novaMapa"), function () { odpriOknoNovo({ nacin: "mapa", kam: kam }); }]);
    m.push(["—"]);
    VRSTE_NOVIH.forEach(function (v) {
      m.push([t(v[1]), function () { odpriOknoNovo({ nacin: "datoteka", vrsta: v[0], kam: kam }); }]);
    });
    predlogeDatotek.forEach(function (p) {
      m.push([t("vPredloga", { ime: p.ime }), function () { odpriOknoNovo({ nacin: "datoteka", vrsta: "predloga", predloga: p.pot, ime: p.ime, kam: kam }); }]);
    });
  }
  function meniNovo(x, y) {
    var m = [];
    if (D.vir && D.vir.vrsta === "smeti") { pokaziMeni([[t("izprazniSmeti"), izprazniSmeti], [t("osvezi"), function () { odpriVir(D.vir); }]], x, y); return; }
    if (O.poti.length && D.vir && D.vir.vrsta === "lokalno") { m.push([t("prilepi"), function () { prilepi(null); }]); m.push(["—"]); }
    if (RZ.length) { m.push([t("razveljavi"), function () { razveljavi(); }]); m.push(["—"]); }
    postavkeNovo(m, null);
    m.push(["—"]);
    m.push([t("osvezi"), function () { if (D.vir) odpriVir(D.vir); }]);
    pokaziMeni(m, x, y);
  }
  var NO = { nastavitve: null };
  function napakaNovo(koda) {
    return t({ obstaja: "nObstaja", napacno_ime: "nIme", ni_dovoljenja: "nDovoljenje", ni_dovoljeno: "nDovoljenje",
               ni_mape: "nMapa" }[koda] || "nSplosno");
  }
  function odpriOknoNovo(o) {
    NO.nastavitve = o;
    zapriMeni();
    var preimenuj = o.nacin === "preimenuj";
    $("novoNaslovOkna").textContent = t(preimenuj ? "oknoPreimenuj" : o.nacin === "mapa" ? "oknoMapa" : "oknoDatoteka");
    $("novoPotrdi").textContent = t(preimenuj ? "preimenuj" : "ustvari");
    $("novoKjeVrsta").hidden = preimenuj;
    $("novoVrstaVrsta").hidden = o.nacin !== "datoteka";
    var s = $("novoVrsta"); s.innerHTML = "";
    if (o.nacin === "datoteka") {
      VRSTE_NOVIH.forEach(function (v) { var op = el("option", "", t(v[1]).replace(/ \u2026$/, "")); op.value = v[0]; s.appendChild(op); });
      predlogeDatotek.forEach(function (p) { var op = el("option", "", t("vPredloga", { ime: p.ime }).replace(/ \u2026$/, "")); op.value = "predloga:" + p.pot; s.appendChild(op); });
      s.value = o.vrsta === "predloga" ? "predloga:" + o.predloga : (o.vrsta || "prazna");
    }
    var ime = preimenuj ? o.ime : o.nacin === "mapa" ? t("privzetoMapa")
      : o.vrsta === "predloga" ? o.ime : t((VRSTE_NOVIH.filter(function (v) { return v[0] === o.vrsta; })[0] || VRSTE_NOVIH[0])[2]);
    var polje = $("novoIme"); polje.value = ime;
    nastaviKje(o.kam);
    $("novoNapaka").hidden = true;
    $("oknoNovo").hidden = false;
    setTimeout(function () {
      polje.focus();
      // Kot v Nemu: oznaceno je ime brez koncnice, da ga uporabnik takoj prepise.
      var konec = preimenuj && !o.mapa && ime.lastIndexOf(".") > 0 ? ime.lastIndexOf(".") : ime.length;
      polje.setSelectionRange(0, konec);
    }, 0);
  }
  function nastaviKje(pot) {
    NO.kam = pot;
    var dom = (Z.dom || "").replace(/\/$/, "");
    $("novoKje").textContent = !pot || pot === "~" || pot.replace(/\/$/, "") === dom ? t("domov")
      : dom && pot.indexOf(dom + "/") === 0 ? t("domov") + " \u203a " + pot.slice(dom.length + 1).split("/").join(" \u203a ")
      : pot;
    $("novoKje").title = pot || "";
  }
  function zapriOknoNovo() { $("oknoNovo").hidden = true; NO.nastavitve = null; }
  function potrdiNovo() {
    var o = NO.nastavitve; if (!o) return;
    var ime = $("novoIme").value.trim();
    var obljuba;
    if (o.nacin === "preimenuj") obljuba = klic("preimenujDatoteko", [o.pot, ime]);
    else if (o.nacin === "mapa") obljuba = klic("novaMapa", [NO.kam, ime]);
    else {
      var v = $("novoVrsta").value;
      obljuba = v.indexOf("predloga:") === 0 ? klic("novaDatoteka", [NO.kam, ime, "prazna", v.slice(9)])
        : klic("novaDatoteka", [NO.kam, ime, v, ""]);
    }
    $("novoPotrdi").disabled = true;
    obljuba.then(function (r) {
      $("novoPotrdi").disabled = false;
      if (!r || !r.ok) { var n = $("novoNapaka"); n.textContent = napakaNovo(r && r.napaka); n.hidden = false; $("novoIme").focus(); return; }
      zapriOknoNovo();
      var nova = r.pot || "", mapa = nova.replace(/\/[^/]*$/, "") || "/", imeNovega = nova.split("/").pop();
      if (o.nacin !== "preimenuj") obvesti(t("ustvarjeno", { ime: imeNovega }), zapomniDejanje({ vrsta: "novo", pari: [["", nova]] }));
      else if (nova && nova !== o.pot) obvesti(t("preimenovano", { ime: imeNovega }), zapomniDejanje({ vrsta: "preimenovanje", pari: [[o.pot, nova]] }));
      // Pokazemo mapo, kjer je nastalo, in vnos oznacimo (koren ohranimo, ce je mapa v njem).
      var koren = D.vir && D.vir.vrsta === "lokalno" && D.vir.koren && (mapa + "/").indexOf(D.vir.koren.replace(/\/$/, "") + "/") === 0
        ? D.vir.koren : mapa;
      D.oznaci = imeNovega;
      odpriVir({ vrsta: "lokalno", pot: mapa, koren: koren });
    }).catch(function () { $("novoPotrdi").disabled = false; var n = $("novoNapaka"); n.textContent = t("nSplosno"); n.hidden = false; });
  }
  // ------------------------------------------------------------------ SKUPNI PROSTOR (zakon solidarnosti)
  /** Ko racunalniku zmanjkuje prostora, Datoteke same ponudijo shranjevanje na napravo v Linku. */
  var opozoriloProstora = null;
  function preveriProstor() {
    klic("prostorDiska").then(function (p) {
      if (opozoriloProstora) { opozoriloProstora.remove(); opozoriloProstora = null; }
      if (!p || !p.malo) return;
      var o = el("div", "dat-opozorilo"); o.setAttribute("role", "status"); opozoriloProstora = o;
      o.style.cssText = "display:flex;gap:.8em;align-items:center;padding:.55em .8em;margin-bottom:.45em;border-radius:10px;background:rgba(255,190,90,.14);border:1px solid rgba(255,190,90,.45)";
      var b = el("span", "", t("maloProstora", { prosto: velikost(p.prosto) })); b.style.flex = "1";
      var g = el("button", "", t("pokaziNajvecje")); g.type = "button";
      g.addEventListener("click", function () { odpriVir({ vrsta: "najvecje" }); });
      o.appendChild(b); o.appendChild(g);
      var glavno = document.querySelector(".dat-glavno"); if (glavno) glavno.insertBefore(o, glavno.firstChild);
    }).catch(function () {});
  }

  // Datoteko shrani naprava v Safeer Linku z najvec prostora. Izvirnik izbrise sele uporabnik,
  // ko vidi, na kateri napravi in v kateri mapi je preverjena kopija.
  function shraniNaNapravo(e) {
    var ovoj = el("div", "meni"); ovoj.setAttribute("role", "dialog");
    ovoj.style.cssText = "position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);max-width:34em;padding:1em 1.2em";
    var naslov = el("p", "meni-naslov", t("shraniNaNapravo").replace(/\s\u2026$/, ""));
    var besedilo = el("p", "", t("shrPripravljam", { ime: e.ime })); besedilo.style.cssText = "margin:.6em 0";
    var vprasanje = el("p", ""); vprasanje.style.cssText = "margin:.6em 0;font-weight:600"; vprasanje.hidden = true;
    var gumbi = el("div", ""); gumbi.style.cssText = "display:flex;gap:.6em;justify-content:flex-end;margin-top:.8em";
    var gZapri = el("button", "", t("shrZapri")); gZapri.type = "button";
    gZapri.addEventListener("click", zapri); gumbi.appendChild(gZapri);
    [naslov, besedilo, vprasanje, gumbi].forEach(function (x) { ovoj.appendChild(x); });
    document.body.appendChild(ovoj);
    var id = null, casovnik = 0;
    function zapri() { clearTimeout(casovnik); ovoj.remove(); }
    function zamenjajGumbe(seznam) { gumbi.innerHTML = ""; seznam.forEach(function (g) { gumbi.appendChild(g); }); }
    function koncaj(sporocilo) { besedilo.textContent = sporocilo; vprasanje.hidden = true; zamenjajGumbe([gZapri]); }
    function napaka(r) {
      var k = (r && (r.napaka || r.koda)) || "napaka";
      koncaj(k === "ni_naprave" ? t("shrNiNaprave") : k === "spremenjena" ? t("shrSpremenjena") : t("shrNapaka", { koda: k }));
    }
    function pokazi(r) {
      // Android pove pot kot "Download/Safeer Shramba/ime": uporabnik pozna mapo Prenosi.
      var kje = (r.kje || "").replace(/^Download\//, t("shrPrenosi") + " › ").replace(/\//g, " › ");
      var z = { ime: r.ime, naprava: r.naprava || "", kje: kje, velikost: velikost(r.velikost),
                odst: r.velikost ? Math.floor(100 * (r.preneseno || 0) / r.velikost) : 0 };
      if (r.stanje === "pripravljam") { besedilo.textContent = t("shrPripravljam", z); }
      else if (r.stanje === "prenasam") { besedilo.textContent = t("shrPrenasam", z); }
      else if (r.stanje === "kopija") {
        naslov.textContent = t("shrKopijaNaslov");
        besedilo.textContent = t("shrKopija", z);
        vprasanje.textContent = t("shrVprasaj", z); vprasanje.hidden = false;
        var gIzbrisi = el("button", "", t("shrIzbrisi")); gIzbrisi.type = "button";
        var gObdrzi = el("button", "", t("shrObdrzi")); gObdrzi.type = "button";
        gIzbrisi.addEventListener("click", function () {
          gIzbrisi.disabled = true;
          klic("shrambaIzbrisi", [id]).then(function (x) {
            if (!x || !x.ok) { napaka(x); return; }
            koncaj(t("shrIzbrisano", z));
            if (D.vir) odpriVir(D.vir);
            preveriProstor();
          }).catch(function () { napaka(null); });
        });
        gObdrzi.addEventListener("click", function () {
          klic("shrambaObdrzi", [id]).then(function () { koncaj(t("shrObdrzano", z)); }).catch(function () { napaka(null); });
        });
        zamenjajGumbe([gObdrzi, gIzbrisi]);
        try { gObdrzi.focus(); } catch (x) {}
        return;
      }
      else if (r.stanje === "napaka") { napaka(r); return; }
      casovnik = setTimeout(osvezi, 1500);
    }
    function osvezi() {
      klic("shrambaStanje", [id]).then(function (r) { if (r && r.ok) pokazi(r); else napaka(r); }).catch(function () { napaka(null); });
    }
    klic("shraniNaNapravo", [e.pot]).then(function (r) {
      if (!r || !r.ok) { napaka(r); return; }
      id = r.id; pokazi(r);
    }).catch(function () { napaka(null); });
  }

  // Pretvorba slike, zvoka ali dokumenta na tem racunalniku (core/os_pretvorba_datotek.py): izbira oblike,
  // napredek, rezultat ob izvirniku. Nic ne gre na splet.
  // Koncnice, ki jih zna core/os_pretvorba_datotek.py (test_pretvorba_datotek preveri, da se seznama ujemata):
  // »Pretvori v …« se pokaze samo, ko pretvorba res obstaja - brez okna, ki potem rece »ni mogoce«.
  var PRETVORLJIVE = "aac aif aiff avif bmp csv doc docx flac gif heic heif htm html ico jfif jpeg jpg m4a mka mp3 odp ods odt oga ogg opus png ppt pptx rtf tif tiff txt wav webp wma xls xlsx".split(" ");
  function pretvorljiva(ime) {
    var i = String(ime || "").lastIndexOf(".");
    return i > 0 && PRETVORLJIVE.indexOf(ime.slice(i + 1).toLowerCase()) >= 0;
  }

  function pretvoriDatoteko(e) {
    var ovoj = el("div", "meni"); ovoj.setAttribute("role", "dialog");
    ovoj.style.cssText = "position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);max-width:34em;padding:1em 1.2em";
    // Naslov je v velikih crkah (meni-naslov): ime datoteke gre v svojo vrstico, da ostane zapisano tako, kot je.
    var naslov = el("p", "meni-naslov", t("pretvoriV").replace(/\s\u2026$/, ""));
    var imeDat = el("p", "", e.ime); imeDat.style.cssText = "margin:.1em 0 0;font-weight:600;overflow-wrap:anywhere";
    var besedilo = el("p", "", t("ptdIzberi")); besedilo.style.cssText = "margin:.6em 0";
    ovoj.setAttribute("aria-label", t("ptdNaslov", { ime: e.ime }));
    var oblike = el("div", ""); oblike.style.cssText = "display:grid;grid-template-columns:repeat(3,minmax(5.5em,1fr));gap:.3em;margin:.4em 0";
    var gumbi = el("div", "");
    gumbi.style.cssText = "display:flex;gap:.6em;justify-content:flex-end;margin-top:.6em;padding-top:.5em;border-top:1px solid rgba(127,127,127,.25)";
    var gZapri = el("button", "", t("shrZapri")); gZapri.type = "button";
    gZapri.addEventListener("click", zapri); gumbi.appendChild(gZapri);
    [naslov, imeDat, besedilo, oblike, gumbi].forEach(function (x) { ovoj.appendChild(x); });
    document.body.appendChild(ovoj);
    var casovnik = 0;
    function zapri() { clearTimeout(casovnik); ovoj.remove(); document.removeEventListener("keydown", esc, true); }
    function esc(ev) { if (ev.key === "Escape") { ev.preventDefault(); zapri(); } }
    document.addEventListener("keydown", esc, true);
    var ORODJA = { slika: "ImageMagick", zvok: "ffmpeg", besedilo: "LibreOffice", preglednica: "LibreOffice", predstavitev: "LibreOffice" };
    var skupinaDat = "";
    // Uporabnik vidi razlog z besedami; notranja koda ostane samo za neznane primere.
    var BESEDILA_NAPAK = { ni_mogoce: "ptdNiMogoce", ni_uspelo: "ptdNiUspelo", prepocasi: "ptdPrepocasi", ni_datoteke: "ptdNiDatoteke" };
    function napaka(r) {
      var k = (r && r.koda) || "napaka";
      oblike.innerHTML = "";
      besedilo.textContent = k === "ni_orodja" ? t("ptdNiOrodja", { orodje: ORODJA[(r && r.skupina) || skupinaDat] || "?" })
        : BESEDILA_NAPAK[k] ? t(BESEDILA_NAPAK[k]) : t("ptdNapaka", { koda: k });
    }
    function spremljaj(id, cilj) {
      klic("pretvorbaDatotekeStanje", [id]).then(function (r) {
        if (!r || !r.ok) { napaka(r); return; }
        if (r.stanje === "koncano") {
          besedilo.textContent = t("ptdKoncano", { izhod: String(r.izhod || "").split("/").pop(), velikost: velikost(r.velikost || 0) });
          // r.izhod je samo ime; Nemo potrebuje celo pot (r.pot_izhoda).
          if (D.vir) odpriVir(D.vir);
          if (r.pot_izhoda) {
            var gMapa = el("button", "", t("pokaziVMapi")); gMapa.type = "button";
            gMapa.addEventListener("click", function () { klic("pokaziVMapi", [r.pot_izhoda]); zapri(); });
            gumbi.insertBefore(gMapa, gZapri);
          }
          try { gZapri.focus(); } catch (x) {}
          return;
        }
        if (r.stanje === "napaka") { napaka(r); return; }
        casovnik = setTimeout(function () { spremljaj(id, cilj); }, 700);
      }).catch(function () { napaka(null); });
    }
    klic("pretvorbaMoznosti", [e.pot]).then(function (m) {
      if (!m || !m.cilji || !m.cilji.length) { napaka({ koda: "ni_mogoce" }); return; }
      skupinaDat = m.skupina || "";
      if (!m.orodje) { napaka({ koda: "ni_orodja", skupina: m.skupina }); return; }
      m.cilji.forEach(function (c, i) {
        var g = el("button", "", c.toUpperCase()); g.type = "button";
        g.addEventListener("click", function () {
          oblike.innerHTML = ""; besedilo.textContent = t("ptdPretvarjam", { ime: e.ime, cilj: c.toUpperCase() });
          klic("pretvoriDatoteko", [e.pot, c]).then(function (r) {
            if (!r || !r.ok) { napaka(r); return; }
            spremljaj(r.id, c);
          }).catch(function () { napaka(null); });
        });
        oblike.appendChild(g);
        if (i === 0) { try { g.focus(); } catch (x) {} }
      });
    }).catch(function () { napaka(null); });
  }

  // Grafika v krogu solidarnosti: video pretvori naprava z najboljsim strojnim kodirnikom (H.264, 1080p).
  // Izvirnik ostane; uporabnik izbere, ali pretvorjeni video prenese sem ali ga pusti na napravi.
  function pretvoriVideo(e) {
    var ovoj = el("div", "meni"); ovoj.setAttribute("role", "dialog");
    ovoj.style.cssText = "position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);max-width:34em;padding:1em 1.2em";
    var naslov = el("p", "meni-naslov", t("pretvori").replace(/\s\u2026$/, ""));
    var besedilo = el("p", "", t("prvIscem", { ime: e.ime })); besedilo.style.cssText = "margin:.6em 0";
    var vprasanje = el("p", ""); vprasanje.style.cssText = "margin:.6em 0;font-weight:600"; vprasanje.hidden = true;
    var gumbi = el("div", ""); gumbi.style.cssText = "display:flex;gap:.6em;justify-content:flex-end;margin-top:.8em";
    var gZapri = el("button", "", t("shrZapri")); gZapri.type = "button";
    gZapri.addEventListener("click", zapri); gumbi.appendChild(gZapri);
    [naslov, besedilo, vprasanje, gumbi].forEach(function (x) { ovoj.appendChild(x); });
    document.body.appendChild(ovoj);
    var id = null, casovnik = 0;
    function zapri() { clearTimeout(casovnik); ovoj.remove(); }
    function zamenjajGumbe(seznam) { gumbi.innerHTML = ""; seznam.forEach(function (g) { gumbi.appendChild(g); }); }
    function koncaj(sporocilo) { besedilo.textContent = sporocilo; vprasanje.hidden = true; zamenjajGumbe([gZapri]); }
    function napaka(r) {
      var k = (r && (r.napaka || r.koda)) || "napaka";
      koncaj(k === "ni_naprave" ? t("prvNiNaprave") : k === "ne_zna_dekodirati" ? t("prvNeZna") : t("prvNapaka", { koda: k }));
    }
    function pokazi(r) {
      // Samo mapa (ime datoteke je ze v besedilu): "Download/Safeer Shramba/x.mp4" -> "Prenosi › Safeer Shramba".
      var kje = (r.kje || "").replace(/\/[^\/]*$/, "").replace(/^Download(\/|$)/, t("shrPrenosi") + "$1").replace(/\//g, " \u203a ");
      var z = { ime: r.ime, naprava: r.naprava || "", kje: kje, izhod: r.izhod || "", velikost: velikost(r.izhod_velikost || 0),
                odst: r.odstotek || 0 };
      var st = r.stanje;
      if (st === "isceno") besedilo.textContent = t("prvIscem", z);
      else if (st === "prenasam") besedilo.textContent = t("prvPrenasam", z);
      else if (st === "pretvarjam") besedilo.textContent = t("prvPretvarjam", z);
      else if (st === "pretvarjam_tu") besedilo.textContent = t("prvPretvarjamTu", z);
      else if (st === "shranjujem") besedilo.textContent = t("prvShranjujem", z);
      else if (st === "prenasam_nazaj") { besedilo.textContent = t("prvNazaj", z); zamenjajGumbe([gZapri]); }
      else if (st === "na_racunalniku") { koncaj(t("prvNaRacunalniku", z)); if (D.vir) odpriVir(D.vir); return; }
      else if (st === "pusceno") { koncaj(t("prvPusceno", z)); return; }
      else if (st === "koncano") {
        naslov.textContent = t("prvKoncanoNaslov");
        if (r.napaka) { koncaj(r.napaka === "naprava_ne_deli" ? t("prvNeDeli", z) : t("prvKoncano", z) + " " + t("prvNapaka", { koda: r.napaka })); return; }
        besedilo.textContent = t("prvKoncano", z);
        vprasanje.textContent = t("prvVprasaj"); vprasanje.hidden = false;
        var gPrenesi = el("button", "", t("prvPrenesi")); gPrenesi.type = "button";
        var gPusti = el("button", "", t("prvPusti")); gPusti.type = "button";
        gPrenesi.addEventListener("click", function () {
          gPrenesi.disabled = true; gPusti.disabled = true; vprasanje.hidden = true;
          klic("pretvorbaPrenesi", [id]).then(function (x) { if (!x || !x.ok) { napaka(x); return; } pokazi(x); })
            .catch(function () { napaka(null); });
        });
        gPusti.addEventListener("click", function () {
          klic("pretvorbaPusti", [id]).then(function (x) { pokazi(x && x.ok ? x : r); }).catch(function () { napaka(null); });
        });
        zamenjajGumbe([gPusti, gPrenesi]);
        try { gPrenesi.focus(); } catch (x) {}
        return;
      }
      else if (st === "napaka") { napaka(r); return; }
      casovnik = setTimeout(osvezi, 1500);
    }
    function osvezi() {
      klic("pretvorbaStanje", [id]).then(function (r) { if (r && r.ok) pokazi(r); else napaka(r); }).catch(function () { napaka(null); });
    }
    klic("pretvoriVideo", [e.pot]).then(function (r) {
      if (!r || !r.ok) { napaka(r); return; }
      id = r.id; pokazi(r);
    }).catch(function () { napaka(null); });
  }

  // Zakon solidarnosti, korak 4 (sorazmerni delez): vse videe v mapi si razdelijo naprave, ki lahko pomagajo.
  function pretvoriMapo(e) {
    var ovoj = el("div", "meni"); ovoj.setAttribute("role", "dialog");
    ovoj.style.cssText = "position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);max-width:36em;padding:1em 1.2em";
    var naslov = el("p", "meni-naslov", t("prvSkNaslov"));
    var besedilo = el("p", ""); besedilo.style.cssText = "margin:.6em 0";
    var naprave = el("p", ""); naprave.style.cssText = "margin:.4em 0;opacity:.85;white-space:pre-line";
    var vprasanje = el("p", ""); vprasanje.style.cssText = "margin:.6em 0;font-weight:600"; vprasanje.hidden = true;
    var gumbi = el("div", ""); gumbi.style.cssText = "display:flex;gap:.6em;justify-content:flex-end;margin-top:.8em";
    var gZapri = el("button", "", t("shrZapri")); gZapri.type = "button";
    gZapri.addEventListener("click", zapri); gumbi.appendChild(gZapri);
    [naslov, besedilo, naprave, vprasanje, gumbi].forEach(function (x) { ovoj.appendChild(x); });
    document.body.appendChild(ovoj);
    var id = null, casovnik = 0;
    function zapri() { clearTimeout(casovnik); ovoj.remove(); }
    function zamenjajGumbe(seznam) { gumbi.innerHTML = ""; seznam.forEach(function (g) { gumbi.appendChild(g); }); }
    function koncaj(sporocilo) { besedilo.textContent = sporocilo; vprasanje.hidden = true; zamenjajGumbe([gZapri]); }
    function napaka(r) {
      var k = (r && (r.napaka || r.koda)) || "napaka";
      koncaj(k === "ni_videov" ? t("prvSkNiVidea") : k === "ni_naprave" ? t("prvNiNaprave") : t("prvNapaka", { koda: k }));
    }
    function pokazi(r) {
      var z = { opr: r.uspesno || 0, vseh: r.skupaj || 0 };
      // Kdo koliko opravi (sorazmerni delez) in kaj kdo ta trenutek dela.
      var vrstice = [], dela = {};
      (r.opravila || []).forEach(function (o) {
        if (o.naprava && ["prenasam", "pretvarjam", "shranjujem"].indexOf(o.stanje) >= 0) dela[o.naprava] = o.ime + " " + (o.odstotek || 0) + " %";
      });
      var imena = {};
      Object.keys(r.po_napravah || {}).forEach(function (k) { imena[k] = 1; });
      Object.keys(dela).forEach(function (k) { imena[k] = 1; });
      Object.keys(imena).forEach(function (k) {
        vrstice.push(k + ": " + ((r.po_napravah || {})[k] || 0) + (dela[k] ? " · " + t("prvSkDela") + " " + dela[k] : ""));
      });
      naprave.textContent = vrstice.join("\n");
      if (r.nazaj === "prenasam") { besedilo.textContent = t("prvSkNazaj"); zamenjajGumbe([gZapri]); }
      else if (r.nazaj === "koncano") {
        var n = (r.opravila || []).filter(function (o) { return o.stanje === "na_racunalniku"; }).length;
        koncaj(t("prvSkNaRacunalniku", { n: n })); if (D.vir) odpriVir(D.vir); return;
      }
      else if (r.koncano) {
        var tekst = t("prvSkKoncano", z);
        if (r.napake) {
          var prva = (r.opravila || []).filter(function (o) { return o.stanje === "napaka"; })[0] || {};
          tekst += " " + t("prvSkNapake", { n: r.napake, koda: prva.napaka || "" });
        }
        if (!r.uspesno) { koncaj(tekst); return; }
        if ((r.opravila || []).some(function (o) { return o.stanje === "pusceno"; })) { koncaj(tekst + " " + t("prvSkPusceno")); return; }
        besedilo.textContent = tekst;
        vprasanje.textContent = t("prvSkVprasaj"); vprasanje.hidden = false;
        var gPrenesi = el("button", "", t("prvSkPrenesi")); gPrenesi.type = "button";
        var gPusti = el("button", "", t("prvSkPusti")); gPusti.type = "button";
        gPrenesi.addEventListener("click", function () {
          gPrenesi.disabled = true; gPusti.disabled = true; vprasanje.hidden = true;
          klic("pretvorbaPrenesiSkupino", [id]).then(function (x) { if (!x || !x.ok) { napaka(x); return; } pokazi(x); osveziKasneje(); })
            .catch(function () { napaka(null); });
        });
        gPusti.addEventListener("click", function () {
          klic("pretvorbaPustiSkupino", [id]).then(function (x) { pokazi(x && x.ok ? x : r); }).catch(function () { napaka(null); });
        });
        zamenjajGumbe([gPusti, gPrenesi]);
        try { gPrenesi.focus(); } catch (x) {}
        return;
      }
      else besedilo.textContent = t("prvSkPoteka", z);
      osveziKasneje();
    }
    function osveziKasneje() { clearTimeout(casovnik); casovnik = setTimeout(osvezi, 1500); }
    function osvezi() {
      klic("pretvorbaSkupina", [id]).then(function (r) { if (r && r.ok) pokazi(r); else napaka(r); }).catch(function () { napaka(null); });
    }
    besedilo.textContent = t("prvIscem", { ime: e.ime });
    klic("pretvoriVec", [[e.pot]]).then(function (r) {
      if (!r || !r.ok) { napaka(r); return; }
      id = r.id; pokazi(r);
    }).catch(function () { napaka(null); });
  }

  function vSmeti(e) {
    klic("vSmeti", [e.pot]).then(function (r) {
      if (!r || !r.ok) { obvesti(t("nSmeti")); return; }
      N.priljubljeneDat = N.priljubljeneDat.filter(function (p) { return p.pot !== e.pot; }); shrani();
      obvesti(t("vSmetiOk", { ime: e.ime }), zapomniDejanje({ vrsta: "smeti", idji: r.id ? [r.id] : [] }));
      if (D.vir) odpriVir(D.vir);
    }).catch(function () { obvesti(t("nSmeti")); });
  }
  function predogled(e) {
    if (!e || e.oddaljeno || e.mapa) return;
    var ovoj = el("div", "meni"); ovoj.setAttribute("role", "dialog");
    ovoj.style.cssText = "position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);max-width:70vw;max-height:80vh;overflow:hidden;padding:1em";
    ovoj.appendChild(el("p", "meni-naslov", e.ime));
    if (e.vrsta === "slika") {
      var img = el("img"); img.alt = e.ime; img.src = "file://" + encodeURI(e.pot);
      img.style.cssText = "max-width:66vw;max-height:60vh;display:block;border-radius:10px;margin:.3em auto";
      ovoj.appendChild(img);
    }
    var p = el("p", "", [stranskoBesedilo(e.pot), velikost(e.velikost), cas(e.spremenjeno)].filter(Boolean).join(" · "));
    p.style.cssText = "color:var(--tiho);margin:.5em .5em"; ovoj.appendChild(p);
    var g1 = el("button", "", t("odpri")); g1.type = "button"; g1.addEventListener("click", function () { zapri(); odpriVnos(e); });
    var g2 = el("button", "", t("zapri")); g2.type = "button"; g2.addEventListener("click", zapri);
    ovoj.appendChild(g1); ovoj.appendChild(g2);
    function zapri() { ovoj.remove(); document.removeEventListener("keydown", esc, true); }
    function esc(ev) { if (ev.key === "Escape" || ev.key === " ") { ev.preventDefault(); zapri(); } }
    document.addEventListener("keydown", esc, true);
    document.body.appendChild(ovoj); g1.focus();
  }

  function ostraniStrani(ovoj, od, do_, n, strani, trenutna, pojdi) {
    ovoj.innerHTML = "";
    if (n <= 0) return;
    ovoj.appendChild(el("span", "", t("strani", { a: od + 1, b: do_, n: n })));
    if (strani <= 1) return;
    var n1 = el("button", "", t("nazaj")); n1.type = "button"; n1.disabled = trenutna <= 0; n1.setAttribute("aria-label", "Prejšnja stran");
    var n2 = el("button", "", t("naprej")); n2.type = "button"; n2.disabled = trenutna >= strani - 1; n2.setAttribute("aria-label", "Naslednja stran");
    n1.addEventListener("click", function () { pojdi(trenutna - 1); });
    n2.addEventListener("click", function () { pojdi(trenutna + 1); });
    ovoj.appendChild(n1); ovoj.appendChild(n2);
  }

  // ------------------------------------------------------------------ PROGRAMI NAPRAV
  // lokalni: programi tega racunalnika (most "programi"); oddaljeni: programi naprav v Linku. rocno: uporabnik je
  // zavihek izbral sam, zato ga ne preklapljamo vec na Priljubljene.
  // oblak: ponudniki iger v oblaku (most "igreOblak"); nenamesceni so med Igrami kot ploscica z gumbom Namesti.
  var P = { naprave: [], programi: [], lokalni: [], oddaljeni: [], oblak: [], nedosegljive: [], kategorija: "vse", stran: 0,
            brezControla: false, nalozeno: false, rocno: false, namescam: false };
  var KATEGORIJE = ["priljubljeni", "vse", "pisarna", "ustvarjanje", "mediji", "splet", "igre", "drugo"];
  var IMENA_KATEGORIJ = { vse: "kVse", priljubljeni: "kPriljubljeni", pisarna: "kPisarna", ustvarjanje: "kUstvarjanje",
                          mediji: "kMediji", splet: "kSplet", igre: "kIgre", drugo: "kDrugo" };
  // Skupine iz metapodatkov (core/os_programi, Android paketi) -> kategorije kataloga; uporabnik lahko popravi.
  var IZ_SKUPINE = { pisarna: "pisarna", ucenje: "pisarna", programiranje: "ustvarjanje", predstavnost: "mediji",
                     splet: "splet", igre: "igre", orodja: "drugo", sistem: "drugo", drugo: "drugo" };
  function kljucPrograma(p) { return p.naprava + ":" + p.id; }
  function kategorijaPrograma(p) { return N.kategorije[kljucPrograma(p)] || IZ_SKUPINE[p.skupina] || "drugo"; }

  function jePriljubljen(p) { return N.priljubljeniPrg.indexOf(kljucPrograma(p)) >= 0; }
  // Kje program tece: Ta racunalnik, ime naprave ali Oblak · ponudnik.
  function oznakaOblaka(ponudnik) { return "☁ " + t("oblak") + " · " + ponudnik; }
  // Programi tega racunalnika so v istem seznamu kot programi naprav: uporabnik isce na enem mestu in si
  // priljubljene izbere ne glede na to, kje program tece.
  function sestaviPrograme() {
    var vsi = P.lokalni.concat(P.oddaljeni);
    // Spletne aplikacije, ki jih je uporabnik sam shranil v Safeer OS (potrjene bliznjice).
    Z.spletne.forEach(function (s, i) {
      if (!s || !s.url) return;
      vsi.push({ id: "splet:" + i, ime: s.ime || s.url, naprava: "splet", imeNaprave: t("spletnaAplikacija"), skupina: "splet",
                 ikona: s.ikona && /^(data:image\/|https:)/.test(s.ikona) ? s.ikona : "", url: s.url });
    });
    // Igre v oblaku, ki se niso namescene: ploscica pove, kje bi igra tekla, in ponudi namestitev iz uradnega vira.
    P.oblak.forEach(function (o) {
      if (!o || !o.id || o.namescen) return;
      vsi.push({ id: "oblak:" + o.id, ime: o.ime, naprava: "oblak", imeNaprave: oznakaOblaka(o.ponudnik), skupina: "igre",
                 ikona: "", ponudnikOblaka: o });
    });
    P.programi = vsi;
    // Kdor ima priljubljene, jih vidi najprej (dokler zavihka ne izbere sam).
    if (!P.rocno && P.kategorija === "vse" && vsi.some(jePriljubljen)) P.kategorija = "priljubljeni";
    zgradiIzbiroNaprav();
    izrisiPrograme();
  }
  // Programi tega racunalnika (hitro, brez naprav). Seznam se spreminja: program, namescen ob odprti delovni
  // povrsini, se je prej pokazal sele po ponovnem zagonu (4. 10. 2026). Zdaj ga preberemo znova ob dogodku
  // »programi« (Safeer OS spremlja mape z zaganjalniki) in, za vsak primer, ko uporabnik isce v plosci.
  var lokalniOb = 0;
  function naloziLokalnePrograme() {
    lokalniOb = Date.now();
    dockNalozi();
    return klic("programi").then(function (s) {
      P.lokalni = (Array.isArray(s) ? s : []).filter(function (p) { return p && p.id; }).map(function (p) {
        return { id: String(p.id), ime: String(p.ime || p.id), opis: String(p.opis || p.splosno || ""), skupina: p.skupina || "drugo",
                 ikona: p.ikona || "", naprava: "ta", imeNaprave: p.oblak ? oznakaOblaka(String(p.oblak)) : t("taRacunalnik"),
                 platforma: "linux", lokalni: true };
      });
      sestaviPrograme();
    }).catch(function () { /* brez seznama: ostanejo programi naprav */ });
  }
  function naloziProgrameNaprav() {
    // Ta racunalnik ne caka na naprave: njegovi programi so na voljo takoj, tudi ce Safeer Link ne tece.
    naloziLokalnePrograme();
    klic("igreOblak").then(function (s) { P.oblak = Array.isArray(s) ? s : []; sestaviPrograme(); }).catch(function () {});
    klic("napraveSProgrami").then(function (naprave) {
      P.naprave = Array.isArray(naprave) ? naprave.filter(function (n) { return n && n.id; }) : [];
      P.brezControla = false;
      zgradiIzbiroNaprav();
      var obljube = P.naprave.map(function (n) {
        return klic("programiNaprave", [n.id]).then(function (r) { return { n: n, r: r }; })
          .catch(function () { return { n: n, r: null }; });
      });
      return Promise.all(obljube);
    }).then(function (izidi) {
      var vsi = [], ned = [];
      (izidi || []).forEach(function (x) {
        if (x.r && x.r.ok) x.r.programi.forEach(function (p) { p.imeNaprave = x.n.ime; p.platforma = x.n.platforma; vsi.push(p); });
        else { ned.push(x.n.ime); if (x.r && x.r.koda === "ni_controla") P.brezControla = true; }
      });
      P.oddaljeni = vsi; P.nedosegljive = ned; P.nalozeno = true;
      sestaviPrograme();
      izrisiLink();
      ponoviCeTreba();
    }).catch(function () {
      P.brezControla = true; P.nalozeno = true; P.oddaljeni = []; sestaviPrograme();
      ponoviCeTreba();
    });
  }
  // Ob prijavi se Safeer Control (Link) lahko zazene sele za delovno povrsino: dokler ni naprav ali
  // Controla, poskusimo znova (8 s, najvec 8-krat); ko se odzove, osvezimo tudi naprave v Datotekah.
  var poskusiNaprav = 0, casPoskusa = 0;
  function ponoviCeTreba() {
    clearTimeout(casPoskusa);
    if (!(P.brezControla || !P.naprave.length) || poskusiNaprav >= 8) return;
    poskusiNaprav++;
    casPoskusa = setTimeout(function () { zgradiStranDatotek(); naloziProgrameNaprav(); }, 8000);
  }
  function prgNapravaShranjena() {
    try { var v = localStorage.getItem("safeer_prg_naprava"); return v == null ? "ta" : v; } catch (e) { return "ta"; }
  }
  function zgradiIzbiroNaprav() {
    var s = $("prgNaprava"), prej = s.value || prgNapravaShranjena(); s.innerHTML = "";
    // Privzeto programi tega racunalnika (lastnik, 11. 10. 2026): programe drugih naprav uporabnik vklopi sam.
    if (P.lokalni.length) { var ta = el("option", "", t("taRacunalnik")); ta.value = "ta"; s.appendChild(ta); }
    var o = el("option", "", t("vseNaprave")); o.value = ""; s.appendChild(o);
    P.naprave.forEach(function (n) { var x = el("option", "", n.ime); x.value = n.id; s.appendChild(x); });
    // Spletne bliznjice niso naprava: najdes jih pod Vse naprave in v kategoriji Splet.
    s.value = prej;
    if (s.value !== prej) s.value = P.lokalni.length ? "ta" : "";
  }
  function zgradiKategorije() {
    var z = $("prgKategorije"); z.innerHTML = "";
    KATEGORIJE.forEach(function (k) {
      var b = el("button", "", t(IMENA_KATEGORIJ[k])); b.type = "button"; b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", P.kategorija === k ? "true" : "false");
      b.addEventListener("click", function () { P.kategorija = k; P.rocno = true; P.stran = 0; izrisiPrograme(); });
      z.appendChild(b);
    });
  }
  function programiFiltrirani() {
    var besede = kljucIskanja($("prgFilter").value).split(/\s+/).filter(Boolean), nap = $("prgNaprava").value, k = P.kategorija;
    var r = P.programi.filter(function (p) {
      if (nap && p.naprava !== nap) return false;
      if (k === "priljubljeni" && !jePriljubljen(p)) return false;
      if (k !== "vse" && k !== "priljubljeni" && kategorijaPrograma(p) !== k) return false;
      if (besede.length && !ujemaVse(p.ime + " " + (p.opis || ""), besede)) return false;
      return true;
    });
    var po = $("prgRazvrsti").value;
    r.sort(function (a, b) {
      var fa = jePriljubljen(a), fb = jePriljubljen(b);
      if (fa !== fb) return fa ? -1 : 1;
      if (po === "naprava" && a.imeNaprave !== b.imeNaprave) return a.imeNaprave.localeCompare(b.imeNaprave, jezik);
      return a.ime.localeCompare(b.ime, jezik, { sensitivity: "base" });
    });
    return r;
  }
  function izrisiPrograme() {
    var mreza = $("prgMreza");
    if (!mreza) return;
    zgradiKategorije();
    var seznamPogled = N.pogled === "seznam";
    mreza.classList.toggle("seznam-pogled", seznamPogled);
    $("ikonaPogled").setAttribute("d", seznamPogled ? "M4 4h7v7H4z M13 4h7v7h-7z M4 13h7v7H4z M13 13h7v7h-7z" : "M4 6h16 M4 12h16 M4 18h16");
    var sp = $("prgSporocilo");
    var sporocila = [];
    if (!P.nalozeno) sporocila.push(t("nalagam"));
    else if (P.brezControla) sporocila.push(t("brezControla"));
    else if (!P.naprave.length && $("prgNaprava").value !== "ta") sporocila.push(t("niNaprav"));
    // Nedosegljive naprave so pomembne le, ko uporabnik gleda tudi programe drugih naprav.
    // Ena kratka vrstica namesto dolgega nastevanja; imena so v namigu ob prehodu z misko.
    var nedosegljive = $("prgNaprava").value !== "ta" ? P.nedosegljive : [];
    if (nedosegljive.length) {
      var nn = nedosegljive.length, d100 = nn % 100;
      var kljuc = d100 === 1 ? "1" : d100 === 2 ? "2" : (d100 === 3 || d100 === 4) ? "3" : "5";
      sporocila.push(t("napraveNedosegljive" + kljuc, { n: nn }));
    }
    // Zmogljivost mreze brez pomikanja
    var r = mreza.getBoundingClientRect(), fs = parseFloat(getComputedStyle(mreza).fontSize) || 14;
    var stolpci = seznamPogled ? 1 : Math.max(2, Math.min(6, Math.floor((r.width + 0.6 * fs) / (8.6 * fs))));
    var visVrst = seznamPogled ? 2.6 * fs : 7.4 * fs, gap = (seznamPogled ? 0.25 : 0.6) * fs;
    var visina = Math.max(visVrst, r.height);
    var vrstic = Math.max(1, Math.floor((visina + gap) / (visVrst + gap)));
    mreza.style.setProperty("--stolpci", stolpci);
    var naStran = stolpci * vrstic;
    var seznam = programiFiltrirani();
    var strani = Math.max(1, Math.ceil(seznam.length / naStran));
    P.stran = Math.min(P.stran, strani - 1);
    var od = P.stran * naStran, do_ = Math.min(seznam.length, od + naStran);
    mreza.innerHTML = "";
    seznam.slice(od, do_).forEach(function (p) { mreza.appendChild(ploscicaPrograma(p)); });
    if (P.programi.length && !seznam.length) {
      var brezPriljubljenih = P.kategorija === "priljubljeni" && !P.programi.some(jePriljubljen);
      mreza.appendChild(el("p", "prazno", t(brezPriljubljenih ? "niPriljubljenihPrg" : "niProgramov")));
    }
    sp.textContent = sporocila.join(" · "); sp.hidden = !sporocila.length;
    sp.title = nedosegljive.join(", ");
    sp.classList.toggle("napaka", P.nedosegljive.length > 0 || P.brezControla);
    ostraniStrani($("prgStrani"), od, do_, seznam.length, strani, P.stran, function (s) { P.stran = s; izrisiPrograme(); });
  }
  function ploscicaPrograma(p) {
    var b = el("button", "program" + (p.ponudnikOblaka ? " ponudba" : "")); b.type = "button"; b.setAttribute("role", "listitem");
    // Brez ikone z naprave: crka v barvi kot v Safeer OS (ne izmisljamo logotipa programa).
    b.appendChild(slikaAliCrka(p.ikona, p.ime));
    b.appendChild(el("span", "ime", p.ime));
    b.appendChild(el("small", "", p.imeNaprave));
    var fav = jePriljubljen(p), z = el("span", "zvezda" + (fav ? " je" : ""), fav ? "★" : "☆");
    z.setAttribute("role", "button"); z.title = t(fav ? "odstraniPriljubljeno" : "dodajPriljubljeno");
    z.setAttribute("aria-label", z.title);
    z.addEventListener("click", function (e) { e.preventDefault(); e.stopPropagation(); preklopiPriljubljen(p); });
    b.appendChild(z);
    b.title = p.ime + " · " + p.imeNaprave + (p.opis ? "\n" + p.opis : "");
    b.addEventListener("click", function (e) {
      if (p.lokalni) { zazeniLokalni(p); return; }
      if (p.naprava === "splet") { klic("splet", [p.url]); return; }
      var r = b.getBoundingClientRect();
      if (p.ponudnikOblaka) { meniOblaka(p, r.left + 12, r.bottom - 6); return; }
      meniPrograma(p, r.left + 12, r.bottom - 6, e);
    });
    b.addEventListener("contextmenu", function (e) { e.preventDefault(); if (p.ponudnikOblaka) meniOblaka(p, e.clientX, e.clientY); else meniPrograma(p, e.clientX, e.clientY, e); });
    return b;
  }
  // Igra v oblaku, ki se ni namescena: kaj je, ali bo delovala, in namestitev iz ponudnikovega uradnega vira (samo na klik).
  function razlogOblaka(z) {
    var r = (z && z.razlogi && z.razlogi[0]) || null;
    return r && BESEDILA[jezik]["oblakRazlog_" + r.koda] ? t("oblakRazlog_" + r.koda, r) : "";
  }
  function meniOblaka(p, x, y) {
    var o = p.ponudnikOblaka, z = o.zdruzljivost || {}, m = [];
    m.push([t("oblakOpis", { ponudnik: o.ponudnik }), null, true]);
    m.push([z.stanje === "zdruzljivo" ? t("oblakZdruzljivo") : t(z.stanje === "ne" ? "oblakNe" : "oblakPoskusi", { razlog: razlogOblaka(z) }), null, true]);
    m.push(["—"]);
    m.push([t("oblakNamesti", { ponudnik: o.ponudnik }), function () { namestiOblak(o); }, z.stanje === "ne"]);
    m.push([t("oblakVec"), function () { klic("splet", [o.stran]); }]);
    pokaziMeni(m, x, y);
  }
  // Ponudniki programov (core/os_ponudniki_programov.py, core/os_github_programi.py): uporabnik izbere, od kod namesca
  // programe. Trije zavihki: Ponudniki (po abecedi, brez priporocila), Viri (Flatpak repozitoriji, PPA - doda svoje) in
  // GitHub (javni repozitoriji in datoteke izdaj, shrani v mapo, ki jo izbere sam). Nic se ne namesti brez potrditve, v
  // kateri uporabnik vidi, kaj natanko, od kod, koliko in kako se bo posodabljalo (lastnik, 11. 10. 2026).
  function ponudnikiProgramov() {
    var ovoj = el("div", "meni"); ovoj.setAttribute("role", "dialog"); ovoj.setAttribute("aria-label", t("ppNaslov"));
    // Pritrjen zgoraj (ne na sredini): ko se vsebina spremeni, okno ne poskoci pod kazalcem.
    ovoj.style.cssText = "position:fixed;left:50%;top:6vh;transform:translateX(-50%);width:min(40em,94vw);max-height:88vh;overflow:auto;padding:1em 1.2em";
    ovoj.appendChild(el("p", "meni-naslov", t("ppNaslov")));
    var zavihki = el("div", ""); zavihki.style.cssText = "display:flex;gap:.4em;margin:.3em 0 .6em";
    var vsebina = el("div", "");
    var gumbi = el("div", "");
    gumbi.style.cssText = "display:flex;justify-content:flex-end;margin-top:.6em;padding-top:.5em;border-top:1px solid rgba(127,127,127,.25)";
    var gZapri = el("button", "", t("shrZapri")); gZapri.type = "button"; gZapri.style.width = "auto";
    gZapri.addEventListener("click", zapri); gumbi.appendChild(gZapri);
    [zavihki, vsebina, gumbi].forEach(function (x) { ovoj.appendChild(x); });
    document.body.appendChild(ovoj);
    var casovnik = 0;
    function zapri() { clearTimeout(casovnik); ovoj.remove(); document.removeEventListener("keydown", esc, true); }
    function esc(ev) { if (ev.key === "Escape") { ev.preventDefault(); zapri(); } }
    document.addEventListener("keydown", esc, true);
    function stevilo(v) { return String(v || 0).replace(".", jezik === "sl" ? "," : "."); }
    function gumb(besedilo, glavni) {
      var g = el("button", "", besedilo); g.type = "button";
      g.style.cssText = "width:auto;flex:none" + (glavni ? ";border:1px solid var(--obroba-mocna)" : "");
      return g;
    }
    function vrsticaZ(naslovBesedilo, opisBesedilo) {
      var vrsta = el("div", ""); vrsta.style.cssText = "display:flex;align-items:center;flex-wrap:wrap;gap:.8em;padding:.45em 0;border-bottom:1px solid rgba(127,127,127,.12)";
      var b = el("div", ""); b.style.cssText = "flex:1;min-width:0";
      var n = el("div", "", naslovBesedilo); n.style.cssText = "font-weight:600;overflow-wrap:anywhere";
      b.appendChild(n);
      if (opisBesedilo) { var o = el("div", "", opisBesedilo); o.style.cssText = "font-size:.9em;opacity:.75;overflow-wrap:anywhere"; b.appendChild(o); }
      vrsta.appendChild(b);
      return vrsta;
    }
    // Okvir za potrditev: vrstice besedila, seznam, gumba Preklici / potrdi.
    function potrditev(vrsta, vrstice, seznam, potrdiBesedilo, naPotrdi, naPreklic) {
      var okvir = el("div", ""); okvir.style.cssText = "flex-basis:100%;margin:.2em 0;padding:.6em .7em;border:1px solid var(--obroba-mocna);border-radius:8px;font-size:.9em";
      if (seznam && seznam.length) {
        okvir.appendChild(el("div", "", t("ppKajSe")));
        var ul = el("ul", ""); ul.style.cssText = "margin:.3em 0 .4em 1.2em;padding:0";
        seznam.forEach(function (x) { ul.appendChild(el("li", "", x)); });
        okvir.appendChild(ul);
      }
      vrstice.forEach(function (x) { var d = el("div", "", x); d.style.marginTop = ".25em"; okvir.appendChild(d); });
      var vg = el("div", ""); vg.style.cssText = "display:flex;gap:.6em;justify-content:flex-end;margin-top:.5em";
      var gP = gumb(t("ppPreklici")), gO = gumb(potrdiBesedilo, true);
      vg.appendChild(gP); vg.appendChild(gO); okvir.appendChild(vg); vrsta.appendChild(okvir);
      gP.addEventListener("click", function () { okvir.remove(); if (naPreklic) naPreklic(); });
      gO.addEventListener("click", function () { gO.disabled = true; gP.disabled = true; naPotrdi(); });
      try { gO.focus(); } catch (x) {}
      return okvir;
    }
    // Vrsta cipov za filter: [[kljuc, besedilo, stevilo]]; izbrani je obrobljen.
    function cipi(moznosti, izbrani, naIzbiro) {
      var v = el("div", ""); v.style.cssText = "display:flex;flex-wrap:wrap;gap:.35em;margin:.5em 0";
      moznosti.forEach(function (m) {
        var g = gumb(m[1] + (m[2] !== undefined ? " · " + m[2] : ""), m[0] === izbrani);
        g.style.fontWeight = m[0] === izbrani ? "600" : "400";
        g.setAttribute("aria-pressed", m[0] === izbrani ? "true" : "false");
        g.addEventListener("click", function () { naIzbiro(m[0]); });
        v.appendChild(g);
      });
      return v;
    }
    var ZAVIHKI = [["ponudniki", "ppZavihekPonudniki"], ["viri", "ppZavihekViri"], ["github", "ppZavihekGithub"]];
    var trenutni = "ponudniki";
    ZAVIHKI.forEach(function (z) {
      var g = gumb(t(z[1])); g.setAttribute("role", "tab"); g.setAttribute("data-zavihek", z[0]);
      g.addEventListener("click", function () { odpriZavihek(z[0]); });
      zavihki.appendChild(g);
    });
    function odpriZavihek(k) {
      trenutni = k; clearTimeout(casovnik);
      zavihki.querySelectorAll("button").forEach(function (b) {
        var izbran = b.getAttribute("data-zavihek") === k;
        b.setAttribute("aria-selected", izbran ? "true" : "false");
        b.style.border = izbran ? "1px solid var(--obroba-mocna)" : "1px solid transparent";
        b.style.fontWeight = izbran ? "600" : "400";
      });
      vsebina.innerHTML = "";
      if (k === "ponudniki") zavihekPonudniki(); else if (k === "viri") zavihekViri(); else zavihekGithub();
    }

    // ---------------------------------------------------------------- Ponudniki
    function kljuc(id) { return String(id).replace(/-/g, "_"); }
    function ime(p) { return BESEDILA[jezik]["ppIme_" + kljuc(p.id)] ? t("ppIme_" + kljuc(p.id)) : p.ime; }
    function zavihekPonudniki() {
      var uvod = el("p", "", t("ppUvod")); uvod.style.cssText = "margin:.2em 0 .6em;opacity:.8"; vsebina.appendChild(uvod);
      var seznam = el("div", ""); vsebina.appendChild(seznam);
      function izrisi(vsi) {
        seznam.innerHTML = "";
        if (!vsi.length) { seznam.appendChild(el("p", "", t("ppPrazno"))); return; }
        vsi.slice().sort(function (a, b) { return ime(a).localeCompare(ime(b)); }).forEach(function (p) {
          var vrsta = vrsticaZ(ime(p) + (p.namescen ? " · " + t("ppNamesceno") : ""),
            t("ppOpis_" + kljuc(p.id)) + (p.namestljiv && p.vrsta === "apt" ? " (" + t("ppGeslo") + ")" : ""));
          var g = gumb(p.namescen ? t("ppOdpri") : p.vrsta === "snap" ? t("ppOmogoci") : t("ppNamesti"), true);
          if (!p.namescen && !p.namestljiv) g.disabled = true;
          g.addEventListener("click", function () {
            if (p.namescen) { klic("ponudnikOdpri", [p.id]); zapri(); return; }
            g.disabled = true; g.textContent = t("ppPreverjam");
            klic("ponudnikPodrobnosti", [p.id]).then(function (d) {
              if (!d || !d.ok) { obvesti(t("ppNiPodatkov")); osvezi(); return; }
              var seznamPaketov, vrstice;
              if (d.vrsta === "snap") {
                seznamPaketov = (d.koraki || []).map(function (k) { return t("ppKorak_" + kljuc(k)); });
                vrstice = [t("ppVirSnap"), t("ppPosSnap")];
              } else {
                seznamPaketov = (d.paketi || []).map(function (x) {
                  return x.ime + (x.razlicica ? " " + x.razlicica : "") + (x.okolje ? " – " + t("ppOkolje") : "") + (x.prenos_mb ? " (" + stevilo(x.prenos_mb) + " MB)" : "");
                });
                vrstice = [d.vrsta === "flatpak" ? t("ppVirFlatpak", { mb: stevilo(d.prenos_mb) }) : t("ppVirApt", { vir: d.vir, mb: stevilo(d.prenos_mb) }),
                           t(d.samodejno ? "ppPosSamo" : "ppPosRocno")];
              }
              g.hidden = true;
              potrditev(vrsta, vrstice, seznamPaketov, d.vrsta === "snap" ? t("ppOmogoci") : t("ppPotrdi"), function () {
                g.hidden = false; g.textContent = t("ppNamescam");
                klic("ponudnikNamesti", [p.id]).then(function (r) {
                  if (r && r.ok) { obvesti(t("ppKoncano", { ime: ime(p) })); osvezi(); naloziProgrameNaprav(); }
                  else { obvesti(r && r.napaka === "preklicano" ? t("ppPreklicano") : t("ppNapaka", { ime: ime(p) })); osvezi(); }
                }).catch(function () { obvesti(t("ppNapaka", { ime: ime(p) })); osvezi(); });
              }, osvezi);
            }).catch(function () { obvesti(t("ppNiPodatkov")); osvezi(); });
          });
          vrsta.appendChild(g); seznam.appendChild(vrsta);
        });
      }
      function osvezi() { klic("ponudnikiProgramov").then(function (s) { izrisi(Array.isArray(s) ? s : []); }).catch(function () { izrisi([]); }); }
      osvezi();
    }

    // ---------------------------------------------------------------- Viri
    function zavihekViri() {
      var uvod = el("p", "", t("ppViriUvod")); uvod.style.cssText = "margin:.2em 0 .6em;opacity:.8"; vsebina.appendChild(uvod);
      var seznam = el("div", ""); vsebina.appendChild(seznam);
      var vnos = el("div", ""); vnos.style.cssText = "display:flex;gap:.6em;align-items:center;flex-wrap:wrap;margin-top:.7em";
      var polje = el("input", "filter"); polje.type = "text"; polje.placeholder = t("ppViriPh"); polje.style.cssText = "flex:1;min-width:14em";
      var gDodaj = gumb(t("ppViriDodaj"), true);
      vnos.appendChild(polje); vnos.appendChild(gDodaj); vsebina.appendChild(vnos);
      function izrisi(v) {
        seznam.innerHTML = "";
        (v.flatpak || []).forEach(function (x) { seznam.appendChild(vrsticaZ(x.ime + " · Flatpak", x.url + " · " + t(x.za === "uporabnik" ? "ppZaUporabnika" : "ppZaSistem"))); });
        (v.ppa || []).forEach(function (x) { seznam.appendChild(vrsticaZ(x + " · PPA", t("ppZaSistem"))); });
        (v.apt || []).forEach(function (x) { seznam.appendChild(vrsticaZ(x.url.replace(/^https?:\/\//, "") + " · " + x.izdaja, t("ppAptVir"))); });
        if (!seznam.children.length) seznam.appendChild(el("p", "", t("ppViriPrazno")));
      }
      function osvezi() { klic("viriProgramov").then(function (v) { izrisi(v || {}); }).catch(function () { izrisi({}); }); }
      gDodaj.addEventListener("click", function () {
        var niz = (polje.value || "").trim();
        klic("virPodrobnosti", [niz]).then(function (d) {
          if (!d || !d.ok) { obvesti(t("ppViriNeveljaven")); return; }
          gDodaj.disabled = true;
          var vrstice = [d.vrsta === "ppa" ? t("ppViriPpa", { vir: d.vir }) : t("ppViriFlatpak", { vir: d.vir, ime: d.ime }), t("ppViriOpozorilo")];
          potrditev(vnos, vrstice, null, t("ppViriDodaj"), function () {
            klic("dodajVir", [niz]).then(function (r) {
              gDodaj.disabled = false;
              if (r && r.ok) { obvesti(t("ppViriDodan")); polje.value = ""; osvezi(); }
              else obvesti(r && r.napaka === "preklicano" ? t("ppPreklicano") : t("ppViriNapaka"));
              vnos.querySelectorAll("div").forEach(function (o) { if (o.parentNode === vnos) o.remove(); });
            }).catch(function () { gDodaj.disabled = false; obvesti(t("ppViriNapaka")); });
          }, function () { gDodaj.disabled = false; });
        });
      });
      osvezi();
    }

    // ---------------------------------------------------------------- GitHub
    function privzetaMapa() {
      var m = (Z.mape || []).filter(function (x) { return x.vrsta === "DOWNLOAD"; })[0];
      return N.mapaProgramov || (m && m.pot) || Z.dom || "~";
    }
    function zavihekGithub() {
      var uvod = el("p", "", t("ppGhUvod")); uvod.style.cssText = "margin:.2em 0 .6em;opacity:.8"; vsebina.appendChild(uvod);
      var mapaVrsta = el("div", ""); mapaVrsta.style.cssText = "display:flex;gap:.6em;align-items:center;margin-bottom:.6em";
      var mapaBesedilo = el("div", ""); mapaBesedilo.style.cssText = "flex:1;min-width:0;overflow-wrap:anywhere";
      var gMapa = gumb(t("ppGhSpremeni"));
      mapaVrsta.appendChild(mapaBesedilo); mapaVrsta.appendChild(gMapa); vsebina.appendChild(mapaVrsta);
      function narisiMapo() { mapaBesedilo.textContent = t("ppGhMapa", { pot: stranskoBesedilo(privzetaMapa()) }); }
      narisiMapo();
      gMapa.addEventListener("click", function () {
        klic("izberiMapo", [privzetaMapa(), t("ppGhIzberiMapo"), t("preklici"), t("izberi")]).then(function (p) {
          if (p) { N.mapaProgramov = p; shrani(); narisiMapo(); }
        });
      });
      var iskanje = el("div", ""); iskanje.style.cssText = "display:flex;gap:.6em;align-items:center";
      var polje = el("input", "filter"); polje.type = "search"; polje.placeholder = t("ppGhIsciPh"); polje.style.cssText = "flex:1;min-width:12em";
      var gIsci = gumb(t("ppGhIsci"), true);
      iskanje.appendChild(polje); iskanje.appendChild(gIsci); vsebina.appendChild(iskanje);
      var rezultati = el("div", ""); rezultati.style.marginTop = ".5em"; vsebina.appendChild(rezultati);
      function napaka(r) { rezultati.innerHTML = ""; rezultati.appendChild(el("p", "", t(r && r.napaka === "omejitev" ? "ppGhOmejitev" : "ppGhNapaka"))); }
      function isci() {
        var niz = (polje.value || "").trim(); if (!niz) return;
        rezultati.innerHTML = ""; rezultati.appendChild(el("p", "", t("ppGhIscem")));
        klic("githubIsci", [niz]).then(function (r) {
          if (!r || !r.ok) { napaka(r); return; }
          rezultati.innerHTML = "";
          if (!r.repozitoriji.length) { rezultati.appendChild(el("p", "", t("ppGhNic"))); return; }
          zadnjeIskanje = r.repozitoriji; narisiRepozitorije();
        }).catch(function () { napaka(null); });
      }
      var zadnjeIskanje = [], izbranaZvrst = "vse";
      function narisiRepozitorije() {
        rezultati.innerHTML = "";
        var stetje = {};
        zadnjeIskanje.forEach(function (x) { stetje[x.zvrst] = (stetje[x.zvrst] || 0) + 1; });
        var moznosti = [["vse", t("ppGhVse"), zadnjeIskanje.length]];
        Object.keys(stetje).sort(function (a, b) { return stetje[b] - stetje[a]; }).forEach(function (k) { moznosti.push([k, t("ppZvrst_" + k), stetje[k]]); });
        if (!stetje[izbranaZvrst]) izbranaZvrst = "vse";
        rezultati.appendChild(cipi(moznosti, izbranaZvrst, function (k) { izbranaZvrst = k; narisiRepozitorije(); }));
        zadnjeIskanje.filter(function (x) { return izbranaZvrst === "vse" || x.zvrst === izbranaZvrst; }).forEach(function (x) {
            var opis = [x.opis, t("ppZvrst_" + x.zvrst), "★ " + x.zvezdice, x.licenca === "NOASSERTION" ? t("ppGhDrugaLicenca") : x.licenca, x.posodobljeno, x.arhiviran ? t("ppGhArhiviran") : ""].filter(Boolean).join(" · ");
            var vrsta = vrsticaZ(x.repo, opis);
            var g = gumb(t("ppGhIzdaje"), true);
            g.addEventListener("click", function () { izdaje(x.repo); });
            vrsta.appendChild(g); rezultati.appendChild(vrsta);
        });
      }
      var izbraniSistem = "";
      function izdaje(repo) {
        rezultati.innerHTML = ""; rezultati.appendChild(el("p", "", t("ppGhIscem")));
        klic("githubIzdaje", [repo]).then(function (r) {
          if (!r || !r.ok) { napaka(r); return; }
          rezultati.innerHTML = "";
          var nazaj = gumb("← " + t("ppGhNazaj")); nazaj.addEventListener("click", narisiRepozitorije); rezultati.appendChild(nazaj);
          var naslov = el("p", "", repo); naslov.style.cssText = "font-weight:600;margin:.5em 0 .2em"; rezultati.appendChild(naslov);
          if (!r.izdaje.length) { rezultati.appendChild(el("p", "", t("ppGhBrezIzdaj"))); return; }
          // Filter po sistemu: »Ta racunalnik« (Linux in ta arhitektura), Linux, Windows, macOS, Android ... z stevilom datotek.
          var vse = []; r.izdaje.forEach(function (iz) { vse = vse.concat(iz.datoteke); });
          function ustreza(d, k) { return k === "vse" || (k === "nas" ? d.nas : d.sistem === k); }
          var moznosti = [["nas", t("ppGhZaTaKratko")], ["linux", "Linux"], ["windows", "Windows"], ["macos", "macOS"],
                          ["android", "Android"], ["ios", "iOS"], ["drugo", t("ppGhDrugo")], ["vse", t("ppGhVse")]]
            .map(function (m) { return [m[0], m[1], vse.filter(function (d) { return ustreza(d, m[0]); }).length]; })
            .filter(function (m) { return m[2] > 0 || m[0] === "vse"; });
          var zaNas = vse.some(function (d) { return d.nas; });
          if (!izbraniSistem || !moznosti.some(function (m) { return m[0] === izbraniSistem; })) izbraniSistem = zaNas ? "nas" : "vse";
          rezultati.appendChild(cipi(moznosti, izbraniSistem, function (k) { izbraniSistem = k; izdaje(repo); }));
          if (!zaNas) { var op = el("p", "", t("ppGhNiZaNas")); op.style.cssText = "margin:.2em 0;opacity:.8"; rezultati.appendChild(op); }
          r.izdaje.forEach(function (iz) {
            iz = { ime: iz.ime, datum: iz.datum, predizdaja: iz.predizdaja, datoteke: iz.datoteke.filter(function (d) { return ustreza(d, izbraniSistem); }) };
            var h = el("div", "", iz.ime + " · " + iz.datum + (iz.predizdaja ? " · " + t("ppGhPredizdaja") : ""));
            h.style.cssText = "margin:.7em 0 .2em;opacity:.85"; rezultati.appendChild(h);
            if (!iz.datoteke.length) { rezultati.appendChild(el("p", "", t("ppGhBrezDatotek"))); return; }
            iz.datoteke.forEach(function (d) {
              var vrsta = vrsticaZ(d.ime, stevilo(d.mb) + " MB · " + t("ppGhPrenosov", { n: d.prenosi })
                + (d.nas ? " · " + t("ppGhZaTa") : d.linux ? " · Linux" : "") + (d.sha256 ? " · SHA-256" : ""));
              var g = gumb(t("ppGhShrani"), true), shranjenaPot = "";
              g.addEventListener("click", function () {
                if (shranjenaPot) { klic("pokaziVMapi", [shranjenaPot]); return; }
                g.disabled = true; g.textContent = t("ppGhShranjujem");
                klic("githubShrani", [d.url, d.ime, privzetaMapa(), d.sha256 || ""]).then(function (z) {
                  if (!z || !z.ok) { g.disabled = false; g.textContent = t("ppGhShrani"); obvesti(t(z && z.koda === "mapa" ? "ppGhNiMape" : "ppGhNapaka")); return; }
                  (function spremljaj() {
                    klic("githubStanje", [z.id]).then(function (s) {
                      if (!s || !s.ok || s.stanje === "napaka") {
                        g.disabled = false; g.textContent = t("ppGhShrani");
                        obvesti(t(s && s.koda === "kontrolna" ? "ppGhKontrolna" : "ppGhNapaka")); return;
                      }
                      if (s.stanje === "koncano") {
                        g.disabled = false; g.textContent = t("pokaziVMapi"); shranjenaPot = s.pot;
                        obvesti(t(s.preverjeno ? "ppGhShranjenoPreverjeno" : "ppGhShranjeno", { ime: s.ime })); return;
                      }
                      g.textContent = s.skupaj ? Math.round(100 * s.prebrano / s.skupaj) + " %" : stevilo(Math.round(s.prebrano / 104857.6) / 10) + " MB";
                      casovnik = setTimeout(spremljaj, 500);
                    }).catch(function () { g.disabled = false; g.textContent = t("ppGhShrani"); });
                  })();
                }).catch(function () { g.disabled = false; g.textContent = t("ppGhShrani"); });
              });
              vrsta.appendChild(g); rezultati.appendChild(vrsta);
            });
          });
        }).catch(function () { napaka(null); });
      }
      gIsci.addEventListener("click", function () { izbranaZvrst = "vse"; izbraniSistem = ""; isci(); });
      polje.addEventListener("keydown", function (ev) { if (ev.key === "Enter") { ev.preventDefault(); izbranaZvrst = "vse"; izbraniSistem = ""; isci(); } });
      try { polje.focus(); } catch (x) {}
    }
    odpriZavihek("ponudniki");
  }

  function namestiOblak(o) {
    if (P.namescam) { obvesti(t("oblakZeNamescam")); return; }
    P.namescam = true;
    obvesti(t("oblakNamescam", { ime: o.ime, ponudnik: o.ponudnik }));
    klic("igreOblakNamesti", [o.id]).then(function (r) {
      P.namescam = false;
      if (r && r.ok) { obvesti(t("oblakNamesceno", { ime: o.ime })); P.kategorija = "igre"; P.rocno = true; naloziProgrameNaprav(); }
      else obvesti(BESEDILA[jezik]["oblakNapaka_" + (r && r.napaka)] ? t("oblakNapaka_" + r.napaka) : t("niUspelo"));
    }).catch(function () { P.namescam = false; obvesti(t("niUspelo")); });
  }
  function meniPrograma(p, x, y) {
    var m = [];
    if (p.naprava === "splet") {
      m.push([t("odpri"), function () { klic("splet", [p.url]); }]);
    } else if (p.lokalni) {
      m.push([t("odpri"), function () { zazeniLokalni(p); }]);
    } else {
      m.push([t("odpriTukaj"), function () { zazeni("odpriTukaj", p); }]);
      m.push([t("zazeniNaNapravi"), function () { zazeni("zazeniNaNapravi", p); }]);
    }
    m.push([jePriljubljen(p) ? t("odstraniPriljubljeno") : t("dodajPriljubljeno"), function () { preklopiPriljubljen(p); }]);
    if (p.lokalni && DK.plank) {
      var vDocku = DK.ids.indexOf(p.id) >= 0;
      m.push([t(vDocku ? "dockOdstrani" : "dockDodaj"), function () { dockPreklopi(p.id, p.ime, !vDocku); }]);
    }
    m.push(["—"]);
    m.push([t("kategorija", { k: t(IMENA_KATEGORIJ[kategorijaPrograma(p)]) }), null, true]);
    ["pisarna", "ustvarjanje", "mediji", "splet", "igre", "drugo"].forEach(function (k) {
      if (k === kategorijaPrograma(p)) return;
      m.push(["  → " + t(IMENA_KATEGORIJ[k]), function () { N.kategorije[kljucPrograma(p)] = k; shrani(); izrisiPrograme(); }]);
    });
    pokaziMeni(m, x, y);
  }
  // ------------------------------------------------------------------ DOCK (core/os_dock.py)
  // Lastnik, 11. 10. 2026: dodajanje, odstranjevanje in razvrscanje programov v docku mora biti enostavno - tudi z
  // daljincem (puscici namesto vlecenja). Spremembo Plank pokaze po kratkem ponovnem zagonu.
  var DK = { plank: false, ids: [], programi: [] };
  function dockNalozi() {
    return klic("dock").then(function (r) {
      DK.plank = !!(r && r.plank); DK.programi = (r && r.programi) || [];
      DK.ids = DK.programi.map(function (x) { return x.id; });
      return DK;
    }).catch(function () { return DK; });
  }
  function dockPreklopi(id, ime, dodaj) {
    return klic(dodaj ? "dockDodaj" : "dockOdstrani", [id]).then(function (r) {
      if (!r || r.ok === false) { obvesti(t("niUspelo")); return; }
      obvesti(t(dodaj ? "dockDodano" : "dockOdstranjeno", { ime: ime }));
      return dockNalozi();
    }).catch(function () { obvesti(t("niUspelo")); });
  }
  function urediDock() {
    var ovoj = el("div", "meni dock-urejanje"); ovoj.setAttribute("role", "dialog"); ovoj.setAttribute("aria-label", t("dockNaslov"));
    ovoj.style.cssText = "position:fixed;left:50%;top:6vh;transform:translateX(-50%);width:min(30em,94vw);max-height:88vh;overflow:auto;padding:1em 1.2em";
    var izbiram = false;
    function zapri() { ovoj.remove(); document.removeEventListener("keydown", esc, true); }
    function esc(ev) { if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); if (izbiram) { izbiram = false; narisi(); } else zapri(); } }
    function g(besedilo, naslov, fn) {
      var b = el("button", "", besedilo); b.type = "button"; if (naslov) { b.title = naslov; b.setAttribute("aria-label", naslov); }
      b.addEventListener("click", fn); return b;
    }
    function premakni(i, smer) {
      var vrsta = DK.programi.map(function (x) { return x.dockitem; });
      var j = i + smer; if (j < 0 || j >= vrsta.length) return;
      var x = vrsta[i]; vrsta[i] = vrsta[j]; vrsta[j] = x;
      var px = DK.programi[i]; DK.programi[i] = DK.programi[j]; DK.programi[j] = px;
      narisi(j, smer < 0 ? "gor" : "dol");
      klic("dockRazvrsti", [vrsta]).then(function (r) { if (!r || r.ok === false) obvesti(t("niUspelo")); dockNalozi(); });
    }
    function narisi(fokusVrstica, fokusGumb) {
      ovoj.innerHTML = "";
      ovoj.appendChild(el("p", "meni-naslov", izbiram ? t("dockDodajProgram") : t("dockNaslov")));
      if (!DK.plank) { ovoj.appendChild(el("p", "", t("dockBrezPlanka"))); ovoj.appendChild(g(t("zapri"), "", zapri)); return; }
      if (izbiram) { narisiIzbiro(); return; }
      ovoj.appendChild(el("p", "meni-namig", t("dockOpis")));
      var seznam = el("div", "dock-seznam");
      if (!DK.programi.length) seznam.appendChild(el("p", "prazno", t("dockPrazen")));
      DK.programi.forEach(function (x, i) {
        var v = el("div", "dock-vrstica");
        v.appendChild(slikaAliCrka(x.ikona, x.ime));
        v.appendChild(el("span", "ime", x.ime));
        var gor = g("↑", t("dockGor"), function () { premakni(i, -1); }); gor.disabled = i === 0; gor.dataset.v = "gor";
        var dol = g("↓", t("dockDol"), function () { premakni(i, 1); }); dol.disabled = i === DK.programi.length - 1; dol.dataset.v = "dol";
        var od = g("✕", t("dockOdstrani"), function () { dockPreklopi(x.id, x.ime, false).then(function () { narisi(); }); });
        v.appendChild(gor); v.appendChild(dol); v.appendChild(od);
        seznam.appendChild(v);
        if (fokusVrstica === i) setTimeout(function () { var f = v.querySelector('[data-v="' + fokusGumb + '"]:not(:disabled)') || v.querySelector("button:not(:disabled)"); if (f) f.focus(); }, 0);
      });
      ovoj.appendChild(seznam);
      var spodaj = el("div", "dock-gumbi");
      spodaj.appendChild(g(t("dockDodajProgram"), "", function () { izbiram = true; narisi(); }));
      spodaj.appendChild(g(t("dockVecNastavitev"), "", function () { zapri(); klic("nastavitveDocka"); }));
      spodaj.appendChild(g(t("zapri"), "", zapri));
      ovoj.appendChild(spodaj);
    }
    function narisiIzbiro() {
      var polje = el("input", "filter"); polje.type = "search"; polje.placeholder = t("dockIsci"); polje.style.cssText = "width:100%;box-sizing:border-box;margin:.2em 0 .5em";
      var seznam = el("div", "dock-seznam");
      function izpisi() {
        var q = polje.value.trim().toLocaleLowerCase(jezik);
        seznam.innerHTML = "";
        P.lokalni.filter(function (p) {
          return DK.ids.indexOf(p.id) < 0 && (!q || p.ime.toLocaleLowerCase(jezik).indexOf(q) >= 0);
        }).sort(function (a, b) { return a.ime.localeCompare(b.ime, jezik, { sensitivity: "base" }); }).forEach(function (p) {
          var b = el("button", "dock-vrstica dock-izbira"); b.type = "button";
          b.appendChild(slikaAliCrka(p.ikona, p.ime)); b.appendChild(el("span", "ime", p.ime)); b.appendChild(el("span", "plus", "+"));
          b.addEventListener("click", function () { dockPreklopi(p.id, p.ime, true).then(function () { izbiram = false; narisi(); }); });
          seznam.appendChild(b);
        });
      }
      polje.addEventListener("input", izpisi);
      ovoj.appendChild(polje); ovoj.appendChild(seznam); izpisi();
      var spodaj = el("div", "dock-gumbi");
      spodaj.appendChild(g(t("nazaj"), "", function () { izbiram = false; narisi(); }));
      ovoj.appendChild(spodaj);
      setTimeout(function () { polje.focus(); }, 0);
    }
    document.addEventListener("keydown", esc, true);
    document.body.appendChild(ovoj);
    dockNalozi().then(function () { narisi(); var f = ovoj.querySelector("button:not(:disabled)"); if (f) f.focus(); });
  }
  function preklopiPriljubljen(p) {
    var k = kljucPrograma(p);
    if (jePriljubljen(p)) N.priljubljeniPrg = N.priljubljeniPrg.filter(function (x) { return x !== k; });
    else N.priljubljeniPrg.push(k);
    shrani(); izrisiPrograme();
  }
  function zazeniLokalni(p) {
    klic("zazeni", [p.id]).then(function (ok) { if (!ok) obvesti(t("niUspelo")); }).catch(function () { obvesti(t("niUspelo")); });
  }
  function zazeni(metoda, p) {
    klic(metoda, [p.naprava, p.id]).then(function (r) {
      if (r && r.ok === false) obvesti((r.message || r.sporocilo) ? String(r.message || r.sporocilo) : t("niUspelo"));
      else obvesti((r && r.message) ? String(r.message) : t("zagonPoslan", { naprava: p.imeNaprave }));
    }).catch(function () { obvesti(t("niUspelo")); });
  }

  // ------------------------------------------------------------------ meni (skupen)
  var meniOdprt = null;
  function pokaziMeni(postavke, x, y) {
    var m = $("meniPrograma"); m.innerHTML = "";
    postavke.forEach(function (p) {
      if (p[0] === "—") { m.appendChild(el("hr")); return; }
      var b = el("button", "", p[0]); b.type = "button"; b.setAttribute("role", "menuitem");
      if (p[2] || !p[1]) b.disabled = true;
      else b.addEventListener("click", function () { zapriMeni(); p[1](); });
      m.appendChild(b);
    });
    m.hidden = false; m.style.position = "fixed";
    var w = m.offsetWidth, h = m.offsetHeight;
    m.style.left = Math.max(8, Math.min(x, innerWidth - w - 8)) + "px";
    m.style.top = Math.max(8, Math.min(y, innerHeight - h - 8)) + "px";
    meniOdprt = m;
    var prvi = m.querySelector("button:not(:disabled)"); if (prvi) prvi.focus();
  }
  function zapriMeni() { if (meniOdprt) { meniOdprt.hidden = true; meniOdprt = null; } }

  // ------------------------------------------------------------------ MEDIJI
  var M = { casovnik: 0, zadnje: null };
  function medijZanka() {
    clearTimeout(M.casovnik);
    if (document.hidden || N.skrite.indexOf("mediji") >= 0) { M.casovnik = setTimeout(medijZanka, 4000); return; }
    medijOsvezi().then(function () { M.casovnik = setTimeout(medijZanka, M.zadnje && M.zadnje.stanje === "predvaja" ? 1000 : 3000); });
  }
  // ------------------------------------------------------------------ iskanje v predvajalniku
  // Vsi viri Medijskega centra (dodatki, Jamendo, radio, TV, ta racunalnik) brez odpiranja okna: glasba in radio
  // zaigrata v predvajalniku na namizju, film in serija se odpreta v Safeer Playerju (odpriIzKataloga).
  var MI = { cas: null, zahteva: 0, zadetki: [] };
  // Zadetki pridejo po delih: najprej ta racunalnik in predpomnilnik kataloga (takoj, brez omrezja), nato sveze iskanje
  // po virih. Ne cakamo na najpocasnejsi vir: kar je, je takoj vidno; po 20 s iskanja po virih ne cakamo vec.
  // Vrstni red: naslov, ki se z iskanim zacne (beseda), pred zadetkom sredi besede (»rock« ne najde najprej »Brockovich«).
  function medijOcena(z, q) {
    var naslov = z.lokalno ? (z.d.naslov || z.d.ime || "") : (z.k.naslov || ""), izv = z.lokalno ? "" : (z.k.izvajalec || "");
    var b = q.toLocaleLowerCase(jezik), zacetek = new RegExp("(^|[^\\p{L}\\p{N}])" + b.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "u");
    if (zacetek.test(naslov.toLocaleLowerCase(jezik))) return 0;
    if (zacetek.test(izv.toLocaleLowerCase(jezik))) return 1;
    return 2;
  }
  function medijIsci(q) {
    var polje = $("medijZadetki");
    q = String(q || "").trim();
    clearTimeout(MI.cas);
    if (q.length < 2) { ++MI.zahteva; polje.hidden = true; polje.textContent = ""; MI.zadetki = []; return; }
    MI.cas = setTimeout(function () {
      var zahteva = ++MI.zahteva, deli = { lokalno: [], hitro: [], sveze: null, radio: [] }, konec = false;
      // »rock radio«: uporabnik isce radijsko postajo - te pridejo prve, iscemo pa »rock« med postajami.
      var radioBesede = /(^|\s)(radio|radia|radijo|radijske?|postaj[ae]?|station|sender)(\s|$)/i;
      var zeliRadio = radioBesede.test(q), qRadio = q.replace(radioBesede, " ").replace(/\s+/g, " ").trim() || q;
      polje.hidden = false; polje.textContent = "";
      polje.appendChild(el("p", "medij-zadetki-stanje", t("medijIskanjeIscem")));
      function zdruzi() {
        if (zahteva !== MI.zahteva) return;
        var videni = {}, katalog = [];
        var radio = deli.radio.slice(0, zeliRadio ? 8 : 3);
        (zeliRadio ? radio.concat(deli.sveze || [], deli.hitro) : (deli.sveze || []).concat(radio, deli.hitro)).forEach(function (k) {
          var kljuc = String(k.id || "") || ((k.naslov || "") + "|" + (k.vrsta || ""));
          var kljuc2 = (k.naslov || "").toLocaleLowerCase(jezik) + "|" + (k.izvajalec || "").toLocaleLowerCase(jezik);
          if (videni[kljuc] || videni[kljuc2]) return;
          videni[kljuc] = videni[kljuc2] = true; katalog.push({ k: k });
        });
        var vsi = deli.lokalno.map(function (d) { return { lokalno: true, d: d }; }).concat(katalog);
        vsi.forEach(function (z, i) {
          var jeRadio = !z.lokalno && (z.k.vrsta === "radio" || radio.indexOf(z.k) >= 0);
          // Postaje v vrstnem redu, ki ga da streznik (domace postaje prve, kot pri spletnem iskalniku).
          z.o = (zeliRadio && jeRadio ? -1 : medijOcena(z, jeRadio ? qRadio : q)) * 1000 + i;
        });
        var dobri = vsi.filter(function (z) { return z.o < 2000; });
        // Zadetek sredi besede pokazemo le, ce boljsih ni dovolj.
        if (dobri.length < 4) dobri = vsi;
        MI.zadetki = dobri.sort(function (a, b) { return a.o - b.o; }).slice(0, 3);   // lastnik: le 3 najverjetnejsi, Datoteke ostanejo vidne
        narisiMedijZadetke(q, !konec);
      }
      klic("knjiznicaMedijev", ["", q, 0]).then(function (s) { deli.lokalno = (s || []).slice(0, 4); zdruzi(); }).catch(function () {});
      klic("mediaIsciPredpomnilnik", [q]).then(function (s) { deli.hitro = s || []; zdruzi(); }).catch(function () {});
      var rok = setTimeout(function () { if (zahteva === MI.zahteva && !konec) { konec = true; zdruzi(); } }, 20000);
      var radioKonec = klic("mediaKatalog", [q, "radio", "", 1, "", [], false, [], ""]).then(function (r) {
        deli.radio = ((r && r.vnosi) || []).slice(0, 10); zdruzi();
      }).catch(function () {});
      klic("mediaKatalog", [q, "vse", "", 1, "", [], false, [], ""]).then(function (r) {
        deli.sveze = ((r && r.vnosi) || []).slice(0, 20); zdruzi();
      }).catch(function () {}).then(function () { return radioKonec; }).then(function () { clearTimeout(rok); konec = true; zdruzi(); });
    }, 350);
  }
  function narisiMedijZadetke(q, seIscem) {
    var polje = $("medijZadetki"), fokus = document.activeElement && polje.contains(document.activeElement) ? Array.prototype.indexOf.call(polje.children, document.activeElement) : -1;
    polje.textContent = "";
    if (!MI.zadetki.length) polje.appendChild(el("p", "medij-zadetki-stanje", t(seIscem ? "medijIskanjeIscem" : "medijIskanjeNic")));
    MI.zadetki.forEach(function (z, i) {
      var b = el("button", "medij-zadetek"); b.type = "button"; b.setAttribute("role", "option");
      var slika = z.k && z.k.slika;
      var znak = el("span", "medij-zadetek-znak");
      if (slika) { var img = document.createElement("img"); img.alt = ""; img.loading = "lazy"; img.src = slika; img.onerror = function () { img.remove(); }; znak.appendChild(img); }
      b.appendChild(znak);
      var besedilo = el("span", "medij-zadetek-besedilo");
      besedilo.appendChild(el("b", "", z.lokalno ? (z.d.naslov || z.d.ime || "") : (z.k.naslov || "")));
      var pod = z.lokalno ? t("medijTaRacunalnik") : [z.k.izvajalec, z.k.vir].filter(Boolean).join(" · ");
      besedilo.appendChild(el("small", "", pod));
      b.appendChild(besedilo);
      b.addEventListener("click", function () { medijIzberi(i); });
      polje.appendChild(b);
    });
    var vse = el("button", "medij-zadetek vse", t("medijIskanjeVse", { q: q })); vse.type = "button";
    vse.addEventListener("click", function () { klic("odpriRazdelek", ["mediji:" + q]); medijIskanjePocisti(); });
    polje.appendChild(vse);
    if (seIscem && MI.zadetki.length) polje.appendChild(el("p", "medij-zadetki-stanje", t("medijIskanjeSe")));
    polje.hidden = false;
    if (fokus >= 0 && polje.children[fokus]) polje.children[fokus].focus();
  }
  function medijIzberi(i) {
    var z = MI.zadetki[i];
    if (!z) return;
    if (z.lokalno) {
      M.tokovi = null; narisiTokove();
      klic("odpriLokalniMedij", [z.d.pot]).then(function (ok) { if (ok) medijOsvezi(); else obvesti(t("niUspelo")); });
    } else {
      odpriIzKataloga(z.k);
      naloziTokove(z.k);
    }
    medijIskanjePocisti();
  }
  // Postaja z vec programi: cipi pod predvajalnikom, izbrani je oznacen (core/zakoniti_viri.tokovi_postaje).
  function naloziTokove(k) {
    M.tokovi = null; narisiTokove();
    if (!k || k.vrsta !== "radio" || !k.id) return;
    var id = k.id;
    klic("mediaTokovi", [id]).then(function (s) {
      if (!Array.isArray(s) || s.length < 2) return;
      M.tokovi = { postaja: id, seznam: s, izbran: "", cas: Date.now() };
      narisiTokove();
    }).catch(function () {});
  }
  function narisiTokove() {
    var v = $("medijTokovi"); if (!v) return;
    v.textContent = "";
    if (!M.tokovi) { v.hidden = true; return; }
    v.setAttribute("aria-label", t("medijTokovi"));
    v.appendChild(el("span", "medij-tokovi-naslov", t("medijTokovi")));
    M.tokovi.seznam.forEach(function (tok) {
      var b = el("button", "cip" + (M.tokovi.izbran === tok.id ? " izbran" : ""), tok.naslov); b.type = "button";
      if (tok.bitrate) b.title = tok.bitrate + " kbit/s";
      b.addEventListener("click", function () {
        M.tokovi.izbran = tok.id; M.tokovi.cas = Date.now(); narisiTokove();
        klic("mediaPredvajaj", [tok.id]).then(function (izid) {
          if (!izid || izid.napaka_koda || izid.napaka) obvesti(t("niUspelo")); else medijOsvezi();
        }).catch(function () { obvesti(t("niUspelo")); });
      });
      v.appendChild(b);
    });
    v.hidden = false;
  }
  function medijIskanjePocisti() {
    $("medijIskanjePolje").value = ""; $("medijZadetki").hidden = true; $("medijZadetki").textContent = ""; MI.zadetki = [];
  }
  function poveziMedijIskanje() {
    var polje = $("medijIskanjePolje"), obrazec = $("medijIskanje");
    if (!polje || !obrazec) return;
    polje.addEventListener("input", function () { medijIsci(polje.value); });
    obrazec.addEventListener("submit", function (e) { e.preventDefault(); if (MI.zadetki.length) medijIzberi(0); });
    polje.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); medijIskanjePocisti(); polje.blur(); }
      else if (e.key === "ArrowDown") { var prvi = document.querySelector("#medijZadetki .medij-zadetek"); if (prvi) { e.preventDefault(); prvi.focus(); } }
    });
    $("medijZadetki").addEventListener("keydown", function (e) {
      var vsi = Array.prototype.slice.call(this.querySelectorAll(".medij-zadetek")), i = vsi.indexOf(document.activeElement);
      if (e.key === "ArrowDown" && i < vsi.length - 1) { e.preventDefault(); vsi[i + 1].focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); if (i > 0) vsi[i - 1].focus(); else polje.focus(); }
      else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); medijIskanjePocisti(); }
    });
  }

  function medijOsvezi() {
    return klic("predvajalnikStanje").then(function (p) { M.zadnje = p || {}; izrisiMedij(); }).catch(function () {});
  }
  function izrisiMedij() {
    var p = M.zadnje || {}, ima = !!p.naslov && p.stanje !== "ustavljeno";
    // Programi postaje izginejo, ko predvajanje konca (ne takoj po izbiri - tok se sele zacenja).
    if (!ima && M.tokovi && Date.now() - M.tokovi.cas > 15000) { M.tokovi = null; narisiTokove(); }
    $("ploscaMediji").classList.toggle("prazno", !ima);
    $("medijNaslov").textContent = ima ? p.naslov : t("niPredvajanja");
    var pod = !ima ? t("medijNavodilo")
      : p.stanje === "napaka" ? t("napakaPredvajanja")
      : (p.stanje === "premor" ? t("vPremoru") : t("predvaja")) + (p.izvor ? " · " + p.izvor : "");
    $("medijPodnaslov").textContent = pod;
    $("medijNapredek").style.width = (ima && p.trajanje > 0 ? Math.min(100, p.pozicija / p.trajanje * 100) : 0) + "%";
    $("ikonaPremor").setAttribute("d", p.stanje === "predvaja" ? "M8 5v14 M16 5v14" : "M8 5v14l11-7z");
    document.querySelectorAll("#kontrole button").forEach(function (b) { b.disabled = !ima; });
  }

  // ------------------------------------------------------------------ ISKANJE
  var I = { st: 0, casovnik: 0, zadetki: [], izbran: -1 };
  // Kako dobro se program ujema z iskanim: zacetek imena > zacetek besede > kjerkoli v imenu > opis ali kljucne besede.
  function ocenaPrograma(p, ql) {
    var ime = kljucIskanja(p.ime);
    if (ime.indexOf(ql) === 0) return 3;
    if (ime.indexOf(" " + ql) >= 0 || ime.indexOf("-" + ql) >= 0) return 2;
    return ime.indexOf(ql) >= 0 ? 1 : 0;
  }
  // Iskanje ne gleda na sumnike in velike crke (kot iskanje datotek, core/os_iskalnik.py); vec besed je lahko v
  // poljubnem vrstnem redu, ujemati se morajo vse.
  function kljucIskanja(s) {
    return String(s || "").toLowerCase().replace(/[\u0111\u0142\u00f8\u00df\u00e6\u0153\u0131]/g, function (z) { return POSEBNE_CRKE[z]; })
      .normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  }
  // Crke, ki jih razstavitev NFD ne loci na osnovo in naglas (ista tabela kot core/os_datoteke.py in iskanje.js).
  var POSEBNE_CRKE = { "\u0111": "d", "\u0142": "l", "\u00f8": "o", "\u00df": "ss", "\u00e6": "ae", "\u0153": "oe", "\u0131": "i" };
  function ujemaVse(besedilo, besede) {
    var k = kljucIskanja(besedilo);
    return besede.every(function (b) { return k.indexOf(b) >= 0; });
  }
  // Za zadetke iskanja (programi, Safeer OS, naprave): besede brez locil; kratka beseda (1-2 crki) se mora ujemati z
  // zacetkom besede - »tv« ne najde »nastaviTVe« -, daljsa kjerkoli (»office« najde LibreOffice).
  function besedeIskanja(q) {
    return kljucIskanja(q).replace(/[^\p{L}\p{N}]+/gu, " ").trim().split(" ").filter(Boolean);
  }
  function ujemaZadetek(besedilo, besede) {
    var k = " " + kljucIskanja(besedilo).replace(/[^\p{L}\p{N}]+/gu, " ");
    return besede.length > 0 && besede.every(function (b) {
      if (k.indexOf(b.length < 3 ? " " + b : b) >= 0) return true;
      // Sklon (povedano z glasom): »zaslona« najde »Zaslon«, »datoteko« »Datoteka« - zacetek besede brez zadnjih
      // dveh crk (vsaj stiri).
      return b.length >= 5 && k.indexOf(" " + b.slice(0, Math.max(4, b.length - 2))) >= 0;
    });
  }
  // Safeer OS sam: razdelki glavnega okna in Scit (media v oknu Safeer Player). [cilj za odpriRazdelek, kljuc imena,
  // kljucne besede brez sumnikov].
  var SAFEER_CILJI = [
    ["media", "ciljMedia", "medijski center filmi serije glasba radio tv televizija video katalog media centre movies series music"],
    ["naprave", "ciljNaprave", "safeer link naprave telefon televizor tablica povezi qr koda devices phone tablet pair"],
    ["nastavitve#blokScit", "ciljScit", "scit zascita dns oglasi sledilci blokiranje premor dovoli shield ads trackers protection block"],
    ["nastavitve", "ciljNastavitve", "nastavitve safeer os posodobitve samozagon celozaslonsko settings updates"],
    ["zapiski", "ciljZapiski", "zapiski belezke opombe notes"],
    ["sporocila", "ciljSporocila", "sporocila posta klepet messages mail chat"],
    ["splet", "ciljSplet", "splet brskalnik zaznamki web browser"]
  ];
  function safeerCilji(besede) {
    return SAFEER_CILJI.filter(function (c) { return ujemaZadetek(t(c[1]) + " " + c[2], besede); })
      .map(function (c) { return { vrsta: "safeer", cilj: c[0], ime: t(c[1]) }; }).slice(0, 4);
  }
  // Naprave iz Safeer Linka, po imenu ali po vrsti (»telefon«, »tv«). Zadetek pokaze datoteke naprave tu, v plosci
  // Datoteke; naprava, ki datotek ne deli, pokaze svoje programe v plosci Programi.
  var BESEDE_NAPRAV = { tv: "tv televizor televizija television", phone: "telefon mobitel phone", tablet: "tablica tablet",
                        windows: "windows racunalnik computer pc", linux: "linux racunalnik computer pc", mac: "mac racunalnik computer" };
  function napraveZaIskanje(besede) {
    var videne = {}, vse = [];
    function dodaj(n, datoteke) {
      if (!n || !n.id || videne[n.id]) return;
      videne[n.id] = 1; vse.push({ vrsta: "naprava", n: n, datoteke: datoteke, poImenu: ujemaZadetek(n.ime, besede) });
    }
    D.naprave.forEach(function (n) { dodaj(n, true); });
    P.naprave.forEach(function (n) { dodaj(n, false); });
    return vse.filter(function (v) {
      return v.poImenu || ujemaZadetek(v.n.ime + " " + (BESEDE_NAPRAV[v.n.platforma] || v.n.platforma || ""), besede);
    }).slice(0, 4);
  }
  // Kateri zadetek odpre Enter, ce uporabnik ni izbral sam: prvi program (kot meni Start), sicer Safeer OS, sicer
  // naprava, najdena po imenu. Naprava, najdena samo po vrsti (»telefon«), Enterja ne prevzame - ostane splet.
  var RANG_ZADETKA = { naCilj: 4, program: 3, safeer: 2, naprava: 1 };
  /* Kaj uporabnik isce (Enter brez izbire): spletni naslov -> splet; program -> program; datoteka, slika, medij ali
     zapisek, katerega ime se z nizom zacne ali je enako (ali niz izgleda kot pot ali datoteka s koncnico) -> ta vnos;
     razdelek Safeer OS ali naprava po imenu; sicer splet (prva vrstica). Ocene so iz skupnega iskanje.js
     (SafeerIskanje.oceni: enako 100, zacetek 70, beseda 50, del 30) - ista pravila kot iskanje v Safeer OS. */
  var PRAG_IMENA = 70;
  /* Ucenje lupe (core/os_lupa.py, samo na tem racunalniku): izbire [niz, kljuc zadetka, cas, prvi]. Za iskani niz dobi
     zadetek oceno iz prejsnjih izbir z enakim ali podobnim nizom (eden je zacetek drugega; enak niz steje dvojno),
     novejse stejejo vec (polovica po 30 dneh). Zadetek z oceno vsaj PRAG_UCENJA lupa ponudi prvega. */
  var U = { izbire: [] };
  var POL_ZIVLJENJA = 30 * 86400, PRAG_UCENJA = 0.5, NAJVEC_IZBIR = 500;
  function kljucZadetka(v) {
    switch (v && v.vrsta) {
      case "splet": return "splet";
      case "program": return "program:" + v.p.id;
      case "prgNaprave": return "prgNaprave:" + (v.p.imeNaprave || "") + ":" + v.p.id;
      case "safeer": return "safeer:" + v.cilj;
      case "naprava": return "naprava:" + v.n.id;
      case "datoteka": case "medij": return v.vrsta + ":" + (v.d.pot || v.d.id || v.d.ime || "");
      case "zapisek": return "zapisek:" + v.z.id;
      case "katalog": return "katalog:" + v.k.id;
      case "mediji": return "mediji";
    }
    return "";
  }
  function nizUcenja(q) { return kljucIskanja(q).replace(/\s+/g, " ").trim(); }
  function naucenaOcena(ql, zdaj) {
    var ocene = {};
    zdaj = zdaj || Date.now() / 1000;
    if (!ql) return ocene;
    U.izbire.forEach(function (z) {
      var niz = z[0], enak = niz === ql;
      if (!enak && !(niz.length >= 2 && (niz.indexOf(ql) === 0 || ql.indexOf(niz) === 0))) return;
      var utez = Math.pow(0.5, Math.max(0, zdaj - z[2]) / POL_ZIVLJENJA) * (enak ? 2 : 1);
      ocene[z[1]] = (ocene[z[1]] || 0) + utez;
    });
    return ocene;
  }
  // Seznam po naucenem (stabilno: pri enaki oceni ostane dosedanji vrstni red).
  function poUcenju(seznam, N, kljuc) {
    return seznam.map(function (x, i) { return [N[kljuc(x)] || 0, i, x]; })
      .sort(function (a, b) { return (b[0] - a[0]) || (a[1] - b[1]); }).map(function (y) { return y[2]; });
  }
  function najboljNauceni(vnosi, N) {
    var naj = -1, najO = 0;
    vnosi.forEach(function (v, i) { var o = N[kljucZadetka(v)] || 0; if (o > najO) { najO = o; naj = i; } });
    return najO >= PRAG_UCENJA ? naj : -1;
  }
  function imeVnosa(v) {
    if (v.vrsta === "datoteka" || v.vrsta === "medij") return v.d.naslov || v.d.ime || "";
    if (v.vrsta === "zapisek") return v.z.naslov || "";
    return "";
  }
  function privzetiZadetek(vnosi, q, N) {
    // Kar je uporabnik za tak niz ze izbral, je prvo (tudi splet - ce je takrat izbral splet).
    var nauceni = N ? najboljNauceni(vnosi, N) : -1;
    if (nauceni >= 0) return nauceni;
    var I_ = typeof SafeerIskanje !== "undefined" ? SafeerIskanje : null;
    if (I_ && q && I_.jeNaslov(q)) return 0;
    var prvi = 0, rang = 0;
    vnosi.forEach(function (v, i) {
      var r = v.vrsta === "naprava" && !v.poImenu ? 0 : (RANG_ZADETKA[v.vrsta] || 0);
      if (I_ && q && (v.vrsta === "datoteka" || v.vrsta === "medij" || v.vrsta === "zapisek")) {
        var ime = imeVnosa(v), brezKoncnice = ime.replace(/\.[^.\s]{1,8}$/, "");
        var ocena = Math.max(I_.oceni(ime, q), I_.oceni(brezKoncnice, q));
        if (ocena >= PRAG_IMENA || (v.vrsta === "datoteka" && I_.jePotAliKoncnica(q) && ocena > 0)) r = 2.5;
      }
      if (r > rang) { rang = r; prvi = i; }
    });
    return prvi;
  }
  /* "Prikazi na ..." (glas ali tipkanje; sl, en, de, es, pt): cilj na koncu niza. Vrne {q: niz brez cilja in brez
     glagola na zacetku, vrste: platforme naprav} ali null. Iskanje je potem samo za q, izbrani zadetek se odpre na
     izbrani napravi (core/link_daljinec.py media.open). */
  var PC = ["windows", "linux", "mac"];
  var CILJI_MEDIJA = [
    [/ (na|v) (tv|televiziji|televizorju|televizor|televizijo)$/, ["tv"]], [/ na (racunalniku|racunalnik|pc|prenosniku)$/, PC],
    [/ na (tablici|tablico|tablica)$/, ["tablet"]], [/ na (telefonu|telefon|mobitelu|mobitel)$/, ["phone"]],
    [/ on (the |my )?(tv|television|telly)$/, ["tv"]], [/ on (the |my |this )?(computer|pc|laptop)$/, PC],
    [/ on (the |my )?tablet$/, ["tablet"]], [/ on (the |my )?(phone|mobile)$/, ["phone"]],
    [/ (auf|im) (dem |meinem )?(fernseher|tv|fernsehen)$/, ["tv"]], [/ auf (dem |meinem )?(computer|pc|rechner|laptop)$/, PC],
    [/ auf (dem |meinem )?tablet$/, ["tablet"]], [/ auf (dem |meinem )?(handy|telefon|smartphone)$/, ["phone"]],
    [/ en (la |mi )?(tele|television|tv)$/, ["tv"]], [/ en (el |mi )?(ordenador|computador|computadora|pc|portatil)$/, PC],
    [/ en (la |mi )?tableta$/, ["tablet"]], [/ en (el |mi )?(movil|telefono|celular)$/, ["phone"]],
    [/ n(a|o) (tv|televisao|televisor)$/, ["tv"]], [/ no (computador|pc|portatil)$/, PC],
    [/ no tablet$/, ["tablet"]], [/ no (telemovel|celular|telefone)$/, ["phone"]],
    [/ sur (la |ma )?(tele|television|tv)$/, ["tv"]], [/ sur (lordinateur|mon ordinateur|le pc|mon pc)$/, PC],
    [/ sur (la |ma )?tablette$/, ["tablet"]], [/ sur (le |mon )?(telephone|portable|mobile)$/, ["phone"]],
    [/ (sulla|in) (tv|televisione)$/, ["tv"]], [/ sul (computer|pc)$/, PC],
    [/ sul tablet$/, ["tablet"]], [/ sul (telefono|cellulare)$/, ["phone"]]
  ];
  var GLAGOLI_PRIKAZA = ["prikazi", "pokazi", "predvajaj", "odpri", "zavrti", "show", "play", "open", "put", "zeige", "spiele",
                         "offne", "muestra", "reproduce", "pon", "abre", "mostra", "reproduz", "toca", "passa",
                         "montre", "joue", "ouvre", "lance", "riproduci", "apri", "metti"];
  function ciljMedija(q) {
    var besede = String(q || "").trim().split(/\s+/).filter(Boolean);
    var k = " " + besede.map(function (b) { return kljucIskanja(b).replace(/[^\p{L}\p{N}]+/gu, ""); }).join(" ");
    for (var i = 0; i < CILJI_MEDIJA.length; i++) {
      var m = k.match(CILJI_MEDIJA[i][0]);
      if (!m) continue;
      var ostanek = besede.slice(0, besede.length - m[0].trim().split(" ").length);
      if (ostanek.length && GLAGOLI_PRIKAZA.indexOf(kljucIskanja(ostanek[0]).replace(/[^\p{L}]+/gu, "")) >= 0) ostanek = ostanek.slice(1);
      return { q: ostanek.join(" "), vrste: CILJI_MEDIJA[i][1] };
    }
    return null;
  }
  // Naprave za cilj: vse ustrezne iz Linka; »na racunalniku« na racunalniku ponudi tudi tega (id "").
  function napraveCilja(cilj, naprave, taJeRacunalnik) {
    var izbor = (naprave || []).filter(function (n) { return cilj.vrste.indexOf(n.platforma) >= 0; });
    if (taJeRacunalnik && cilj.vrste === PC) izbor.unshift({ id: "", ime: t("taRacunalnik"), platforma: "linux" });
    return izbor;
  }
  function isci(q) {
    var st = ++I.st;
    q = q.trim();
    I.zadnji = q; I.rocno = false;
    if (!q) { I.poEnter = false; I.caka = false; skrijZadetke(); return; }
    var cilj = ciljMedija(q);
    I.cilj = cilj && cilj.q ? cilj : null;
    if (I.cilj) q = I.cilj.q;
    var ql = kljucIskanja(q), besede = besedeIskanja(q);
    var nauceno = naucenaOcena(nizUcenja(q));
    I.nauceno = nauceno;
    I.caka = true;
    var skupine = [];
    // Programi naprav (ze nalozeni, potrjeni seznami)
    var prg = P.programi.filter(function (p) { return !p.lokalni && ujemaZadetek(p.ime + " " + (p.opis || ""), besede); }).slice(0, 6);
    var safeer = q.length >= 2 ? safeerCilji(besede) : [];
    var naprave = q.length >= 2 ? napraveZaIskanje(besede) : [];
    var cakaj = [
      klic("programi").then(function (s) {
        // Programi in orodja za nastavitve sistema (Cinnamon, Mint) - vsaka skupina do 5 zadetkov.
        var vsi = (s || []).filter(function (p) { return !p.skrit && ujemaZadetek(p.ime + " " + (p.splosno || "") + " " + (p.kljucne || []).join(" "), besede); })
          .sort(function (a, b) {
            return ((nauceno["program:" + b.id] || 0) - (nauceno["program:" + a.id] || 0)) ||
              (ocenaPrograma(b, ql) - ocenaPrograma(a, ql)) || ((b.uporaba || 0) - (a.uporaba || 0));
          });
        var programi = vsi.filter(function (p) { return !p.nastavitev; }).slice(0, 5);
        programi.nastavitve = vsi.filter(function (p) { return p.nastavitev; }).slice(0, 5);
        return programi;
      }).catch(function () { return []; }),
      q.length >= 2 ? klic("isciDatoteke", [q]).then(function (s) { return (s || []).slice(0, 6); }).catch(function () { return []; }) : Promise.resolve([]),
      q.length >= 2 ? klic("knjiznicaMedijev", ["", q, 0]).then(function (s) { return (s || []).slice(0, 5); }).catch(function () { return []; }) : Promise.resolve([]),
      q.length >= 2 ? klic("zapiskiSeznam", [q]).then(function (s) { return (s || []).slice(0, 4); }).catch(function () { return []; }) : Promise.resolve([]),
      // Katalog Medijskega centra (filmi, serije, glasba, radio, TV): samo iz predpomnilnika na disku - med
      // tipkanjem se ne sprasuje virov po omrezju. Najprej naslovi, ki se z iskanim ujemajo.
      q.length >= 3 ? klic("mediaIsciPredpomnilnik", [q]).then(function (s) {
        s = s || [];
        var poNaslovu = s.filter(function (x) { return ujemaZadetek((x.naslov || "") + " " + (x.izvajalec || ""), besede); });
        return (poNaslovu.length ? poNaslovu : s).slice(0, 5);
      }).catch(function () { return []; }) : Promise.resolve([]),
      I.cilj ? klic("napraveZaMedij").catch(function () { return []; }) : Promise.resolve([])
    ];
    // Enter, pritisnjen pred prihodom zadetkov (I.poEnter): odlocimo, ko pridejo VSI zadetki - enako kot po prikazu
    // (privzetiZadetek: datoteka, slika ali zapisek z ujemajocim imenom pred spletom). Ce iskanje po disku traja
    // dlje kot 1,5 s po Enterju, odlocimo s tem, kar je ze tu: program, nastavitev, Safeer OS, naprava, sicer splet.
    I.hitriEnter = function () {
      // »Prikazi na …« odloci izris vseh zadetkov (naprave za cilj), ne programi.
      if (st !== I.st || !I.poEnter || I.cilj) return;
      I.poEnter = false;
      cakaj[0].then(function (programi) {
        if (st !== I.st) return;
        var napravaPoImenu = naprave.filter(function (v) { return v.poImenu; })[0];
        var nast = programi.nastavitve || [];
        // Enter brez izbire: program, sicer nastavitev, katere ime se z nizom zacne, sicer Safeer OS ali naprava.
        var nastPoImenu = nast.filter(function (p) { return ocenaPrograma(p, ql) >= 2; })[0];
        var kandidati = programi.concat(nast).map(function (p) { return { vrsta: "program", p: p }; }).concat(safeer, naprave);
        var nauceni = najboljNauceni(kandidati, nauceno);
        if (nauceni >= 0) { I.privzetiV = kandidati[nauceni]; izberiZadetek(kandidati[nauceni]); return; }
        I.privzetiV = programi.length ? { vrsta: "program", p: programi[0] } : nastPoImenu ? { vrsta: "program", p: nastPoImenu } : null;
        izberiZadetek(programi.length ? { vrsta: "program", p: programi[0] } : nastPoImenu ? { vrsta: "program", p: nastPoImenu } :
          safeer.length ? safeer[0] : napravaPoImenu || { vrsta: "splet", q: q });
      });
    };
    izrisiZadetke([{ naslov: t("skSplet"), vnosi: [{ vrsta: "splet", q: q }] }, { naslov: t("isciem"), vnosi: [] }]);
    Promise.all(cakaj).then(function (r) {
      if (st !== I.st) return;
      I.caka = false;
      if (I.cilj) {
        I.napraveCilja = napraveCilja(I.cilj, r[5], true);
        var naCilj = I.napraveCilja.map(function (n) {
          return { vrsta: "naCilj", n: n, naslov: q, izberi: I.napraveCilja.length > 1 };
        });
        skupine.push({ naslov: t("skPrikaziNa"), vnosi: naCilj.length ? naCilj : [{ vrsta: "naCilj", n: null, naslov: q }] });
      }
      skupine.push({ naslov: t("skSplet"), vnosi: [{ vrsta: "splet", q: q }] });
      if (r[0].length) skupine.push({ naslov: t("skProgrami"), vnosi: r[0].map(function (p) { return { vrsta: "program", p: p }; }) });
      if ((r[0].nastavitve || []).length) skupine.push({ naslov: t("skNastavitve"), vnosi: r[0].nastavitve.map(function (p) { return { vrsta: "program", p: p }; }) });
      if (safeer.length) skupine.push({ naslov: t("skSafeer"), vnosi: safeer });
      if (naprave.length) skupine.push({ naslov: t("skNaprave"), vnosi: naprave });
      if (prg.length) skupine.push({ naslov: t("skProgramiNaprav"), vnosi: prg.map(function (p) { return { vrsta: "prgNaprave", p: p }; }) });
      if (r[1].length) skupine.push({ naslov: t("skDatoteke"), vnosi: poUcenju(r[1].map(function (d) { return { vrsta: "datoteka", d: d }; }), nauceno, kljucZadetka) });
      if (r[3].length) skupine.push({ naslov: t("skZapiski"), vnosi: poUcenju(r[3].map(function (z) { return { vrsta: "zapisek", z: z }; }), nauceno, kljucZadetka) });
      // Mediji: zadetki iz krajevne knjiznice, na koncu pa pot v Medijski center. Katalog isce sele tam - med
      // tipkanjem na namizju virov ne sprasujemo in naslovov iz kataloga ne kazemo.
      var mediji = poUcenju(r[2].map(function (d) { return { vrsta: "medij", d: d }; })
        .concat(r[4].map(function (k) { return { vrsta: "katalog", k: k }; })), nauceno, kljucZadetka);
      if (q.length >= 2) mediji.push({ vrsta: "mediji", q: q });
      if (mediji.length) skupine.push({ naslov: t("skMediji"), vnosi: mediji });
      izrisiZadetke(skupine);
      if (I.poEnter) {
        I.poEnter = false; clearTimeout(I.enterCasovnik);
        var b = I.zadetki[I.izbran];
        if (b && b._v.vrsta === "naCilj" && b._v.izberi) { obvesti(t("izberiNapravo")); return; }
        izberiZadetek(b ? b._v : { vrsta: "splet", q: q });
      }
    });
  }
  function izrisiZadetke(skupine) {
    var z = $("zadetki"); z.innerHTML = ""; I.zadetki = []; I.izbran = 0;
    skupine.forEach(function (s) {
      z.appendChild(el("p", "skupina-naslov", s.naslov));
      s.vnosi.forEach(function (v) {
        var b = el("button", "zadetek"); b.type = "button"; b.setAttribute("role", "option"); b.tabIndex = -1;
        var ime, pod = "", vir = "";
        if (v.vrsta === "splet") {
          b.appendChild(ikonaVrste("splet")); ime = t("isciVSpletu", { q: v.q }); pod = t("odpreVBrskalniku");
        } else if (v.vrsta === "program") {
          appendIkona(b, v.p.ikona, v.p.ime); ime = v.p.ime; pod = v.p.opis || ""; vir = t("taRacunalnik");
        } else if (v.vrsta === "prgNaprave") {
          appendIkona(b, v.p.ikona, v.p.ime); ime = v.p.ime; vir = v.p.imeNaprave;
        } else if (v.vrsta === "safeer") {
          // Medijski center se odpre v svojem oknu Safeer Player (safeer_os.py _odpri_razdelek), ostalo v Safeer OS.
          b.appendChild(ikonaVrste("program")); ime = v.ime; pod = t(v.cilj === "media" ? "odprePredvajalnik" : "odpreSafeerOs");
        } else if (v.vrsta === "naCilj") {
          b.appendChild(ikonaVrste("naprava"));
          ime = v.n ? t("prikaziNaVrsta", { kaj: v.k ? v.k.naslov : v.naslov, ime: v.n.ime }) : t("niNapraveCilja");
        } else if (v.vrsta === "zapisek") {
          b.appendChild(ikonaVrste("dokument")); ime = v.z.naslov; pod = v.z.odlomek || "";
        } else if (v.vrsta === "naprava") {
          b.appendChild(ikonaVrste("naprava")); ime = v.n.ime; pod = t(v.datoteke ? "napravaDatoteke" : "napravaProgrami"); vir = "Safeer Link";
        } else if (v.vrsta === "katalog") {
          // Vsebina iz kataloga Medijskega centra (vir, ki ga je dodal uporabnik, ali vgrajeni zakoniti viri).
          if (v.k.slika && /^https:\/\//.test(v.k.slika)) appendIkona(b, v.k.slika, v.k.naslov);
          else b.appendChild(ikonaVrste(v.k.vrsta === "glasba" || v.k.vrsta === "podcast" || v.k.vrsta === "radio" ? "zvok" : "video"));
          ime = v.k.naslov || ""; pod = v.k.izvajalec || "";
          vir = t("skMediji");
        } else if (v.vrsta === "mediji") {
          b.appendChild(ikonaVrste("video")); ime = t("isciVMedijih", { q: v.q }); pod = t("odpreMedijski");
        } else if (v.vrsta === "datoteka") {
          b.appendChild(ikonaVrste(v.d.mapa ? "mapa" : v.d.vrsta)); ime = v.d.ime; pod = stranskoBesedilo(v.d.pot); vir = t("taRacunalnik");
        } else {
          b.appendChild(ikonaVrste(v.d.vrsta === "glasba" ? "zvok" : v.d.vrsta === "slike" ? "slika" : "video"));
          ime = v.d.naslov || v.d.ime || v.d.pot; pod = stranskoBesedilo(v.d.pot || ""); vir = t("taRacunalnik");
        }
        b.appendChild(el("span", "ime", ime));
        if (pod) b.appendChild(el("small", "", pod));
        if (vir) b.appendChild(el("span", "oznaka-vira" + (v.vrsta === "prgNaprave" || v.vrsta === "naprava" ? " oddaljeno" : ""), vir));
        b.addEventListener("click", function () { izberiZadetek(v); });
        b.addEventListener("mouseenter", function () { I.izbran = I.zadetki.indexOf(b); oznaciZadetek(); });
        b._v = v; I.zadetki.push(b); z.appendChild(b);
      });
    });
    // Na namizju Enter odpre program, ce se kateri ujema (kot meni Start); splet ostane prva vrstica in Shift+Enter.
    if (!I.rocno) I.izbran = privzetiZadetek(I.zadetki.map(function (b) { return b._v; }), I.zadnji, I.nauceno);
    I.privzetiV = I.zadetki[I.izbran] ? I.zadetki[I.izbran]._v : null;
    z.hidden = false; $("iskalnoPolje").setAttribute("aria-expanded", "true");
    oznaciZadetek();
  }
  function appendIkona(b, src, ime) { b.appendChild(slikaAliCrka(src, ime || "?", "ikona-zadetka")); }
  function oznaciZadetek() {
    I.zadetki.forEach(function (b, i) { b.setAttribute("aria-selected", i === I.izbran ? "true" : "false"); });
    var b = I.zadetki[I.izbran]; if (b) b.scrollIntoView({ block: "nearest" });
  }
  function skrijZadetke() { $("zadetki").hidden = true; $("iskalnoPolje").setAttribute("aria-expanded", "false"); I.zadetki = []; }
  /* Iskanje z glasom (core/os_govor.py, na tem racunalniku). Prvi pritisk: ce prepoznave se ni, jo ponudimo prenesti
     (velikost pove Safeer OS); sicer poslusamo. Med poslusanjem drugi pritisk konca govor, Esc ga preklice.
     Prepoznano besedilo gre v polje in se isce kot natipkano - nic se ne odpre samo od sebe. */
  var G = { stanje: "" };
  function mikrofonKlik() {
    if (G.stanje === "poslusam") { klic("govorUstavi"); return; }
    if (G.stanje === "prepoznavam" || G.stanje === "namescam") return;
    klic("govorStanje").then(function (s) {
      if (!s || !s.podprto) obvesti(t("govorNiPodprto"));
      else if (s.namescam) prikaziPrenosGovora(0);
      else if (!s.namesceno) ponudiPrenosGovora(s.prenos || 0);
      else zacniPoslusati();
    }).catch(function () { obvesti(t("govorNiPodprto")); });
  }
  function zacniPoslusati() {
    klic("govorPoslusaj").then(function (ok) { if (!ok) obvesti(t("govorNapaka")); }).catch(function () { obvesti(t("govorNapaka")); });
  }
  function plosaGovora(naslov, opis) {
    var z = $("zadetki"); z.innerHTML = ""; I.zadetki = [];
    var p = el("div", "govor-plosca");
    p.appendChild(el("p", "govor-naslov", naslov));
    if (opis) p.appendChild(el("p", "govor-opis", opis));
    z.appendChild(p); z.hidden = false; $("iskalnoPolje").setAttribute("aria-expanded", "true");
    return p;
  }
  function gumbGovora(gumbi, besedilo, glavni, fn) {
    var g = el("button", "cip" + (glavni ? " glavni-gumb" : ""), besedilo); g.type = "button";
    g.addEventListener("click", fn); gumbi.appendChild(g); return g;
  }
  function ponudiPrenosGovora(bajtov) {
    var p = plosaGovora(t("govorNamestiNaslov"), t("govorNamestiOpis", { mb: Math.max(1, Math.round(bajtov / 1e6)) }));
    var gumbi = el("div", "gumbi"); p.appendChild(gumbi);
    gumbGovora(gumbi, t("govorNeZdaj"), false, skrijZadetke);
    gumbGovora(gumbi, t("govorPrenesi"), true, function () {
      klic("govorNamesti").then(function (ok) { if (ok) prikaziPrenosGovora(0); else { skrijZadetke(); obvesti(t("govorNiPodprto")); } });
    }).focus();
  }
  function prikaziPrenosGovora(odstotek) {
    G.stanje = "namescam";
    var p = plosaGovora(t("govorPrenasam", { o: odstotek }));
    var vrstica = document.createElement("progress"); vrstica.max = 100; vrstica.value = odstotek; p.appendChild(vrstica);
    var gumbi = el("div", "gumbi"); p.appendChild(gumbi);
    gumbGovora(gumbi, t("govorPrekini"), false, function () { klic("govorPrekliciNamestitev"); });
  }
  // Valovi glasnosti: zadnjih VALOV ravni (0..1) od desne proti levi; tisina so pike, govor stolpci.
  var VALOV = 34, ravni = [];
  function narisiValove() {
    var c = $("govorValovi"); if (!c) return;
    while (c.children.length < VALOV) c.appendChild(document.createElement("i"));
    for (var i = 0; i < VALOV; i++) {
      var r = ravni[ravni.length - VALOV + i] || 0;
      c.children[i].style.height = (r < 0.28 ? 3 : Math.round(3 + (r - 0.28) / 0.72 * 22)) + "px";
    }
  }
  function vrsticaGovora(vklop, prepoznava) {
    var f = $("iskanje");
    f.classList.toggle("govori", vklop); f.classList.toggle("prepoznava", !!prepoznava);
    $("govorVrstica").hidden = !vklop;
    if (!vklop) { ravni = []; $("govorDelno").textContent = ""; narisiValove(); }
  }
  function govorDogodek(d) {
    var g = $("gumbMikrofon"), polje = $("iskalnoPolje"), v = d.vrsta;
    if (v === "raven") { ravni.push(d.r || 0); if (ravni.length > 200) ravni.splice(0, 100); narisiValove(); return; }
    if (v === "delno") { if (G.stanje === "poslusam" || G.stanje === "prepoznavam") $("govorDelno").textContent = d.besedilo || ""; return; }
    if (v === "poslusam") { ravni = []; $("govorDelno").textContent = ""; vrsticaGovora(true, false); }
    else if (v === "prepoznavam") { vrsticaGovora(true, true); if (!$("govorDelno").textContent) $("govorDelno").textContent = t("govorPrepoznavam"); }
    else if (v !== "namescam") vrsticaGovora(false);
    G.stanje = (v === "poslusam" || v === "prepoznavam" || v === "namescam") ? v : "";
    g.classList.toggle("poslusam", v === "poslusam");
    g.classList.toggle("prepoznavam", v === "prepoznavam");
    if (v === "poslusam") { polje.value = ""; skrijZadetke(); polje.focus(); }
    if (v === "poslusam" || v === "prepoznavam") { polje.setAttribute("data-ph-zaklenjen", "1"); polje.placeholder = t(v === "poslusam" ? "govorPoslusam" : "govorPrepoznavam"); }
    else { polje.removeAttribute("data-ph-zaklenjen"); phPrilagodi(polje); }
    if (v === "namescam") prikaziPrenosGovora(d.odstotek || 0);
    else if (v === "namesceno") { skrijZadetke(); zacniPoslusati(); }
    else if (v === "besedilo") {
      if (d.besedilo) { polje.value = d.besedilo; polje.focus(); clearTimeout(I.casovnik); isci(d.besedilo); }
      else obvesti(t("govorTisina"));
    }
    else if (v === "tisina") obvesti(t("govorTisina"));
    else if (v === "napaka") {
      skrijZadetke();
      if (d.razlog !== "preklicano") obvesti(t(d.razlog === "mikrofon" ? "govorMikrofon" : d.razlog === "prenos" ? "govorPrenosNapaka" : "govorNapaka"));
    }
  }
  // Izbira gre v ucenje lupe; »prvi« pove, ali je bil to zadetek, ki ga je lupa ponudila prvega (merilo uspeha).
  function zapomniIzbiro(v) {
    var ql = nizUcenja(I.zadnji || ""), k = kljucZadetka(v);
    if (!ql || !k) return;
    var prvi = !!I.privzetiV && kljucZadetka(I.privzetiV) === k;
    U.izbire.push([ql, k, Math.round(Date.now() / 1000), prvi]);
    if (U.izbire.length > NAJVEC_IZBIR) U.izbire.shift();
    klic("lupaZapomni", [ql, k, prvi]).catch(function () {});
  }
  function izberiZadetek(v) {
    zapomniIzbiro(v);
    skrijZadetke();
    if (v.vrsta === "splet") odpriSplet(v.q);
    else if (v.vrsta === "program") klic("zazeni", [v.p.id]);
    else if (v.vrsta === "prgNaprave") { var r = $("iskalnoPolje").getBoundingClientRect(); meniPrograma(v.p, r.left, r.bottom + 6); }
    else if (v.vrsta === "safeer") klic("odpriRazdelek", [v.cilj]);
    else if (v.vrsta === "zapisek") klic("odpriRazdelek", ["zapisek:" + v.z.id]);
    else if (v.vrsta === "naprava") odpriNapravo(v);
    else if (v.vrsta === "mediji") klic("odpriRazdelek", ["mediji:" + v.q]);
    else if (v.vrsta === "katalog" && I.cilj) prikaziKatalogNa(v.k);
    else if (v.vrsta === "katalog") odpriIzKataloga(v.k);
    else if (v.vrsta === "naCilj") prikaziNa(v);
    else if (v.vrsta === "datoteka") odpriVnos(v.d);
    else if (v.vrsta === "medij") klic("odpriLokalniMedij", [v.d.pot]).then(function (ok) { if (ok) medijOsvezi(); else obvesti(t("niUspelo")); });
    $("iskalnoPolje").value = "";
  }
  /* Vsebina iz kataloga: glasba, radio in TV se predvajajo takoj (mali predvajalnik na namizju); film ali serija se
     odpre v Safeer Playerju (podrobnosti, sezone, kje gledati). */
  function odpriIzKataloga(k) {
    if (k.vrsta === "film" || k.vrsta === "serija" || k.vrsta === "video") {
      klic("odpriRazdelek", ["mediji:" + (k.naslov || "")]);
      return;
    }
    klic("mediaPredvajaj", [k.id]).then(function (izid) {
      if (!izid || izid.napaka_koda || izid.napaka) obvesti(t("niUspelo")); else medijOsvezi();
    }).catch(function () { obvesti(t("niUspelo")); });
  }
  /* "Prikazi na ...": naslov (ali izbrani vnos kataloga) odpre Medijski center izbrane naprave; ta racunalnik (id "")
     ga odpre tukaj. Vec naprav iste vrste: uporabnik izbere (vrstice "Prikazi na"). */
  function prikaziNa(v) {
    if (!v.n) { obvesti(t("niNapraveCilja")); return; }
    var kaj = v.k ? v.k.naslov : v.naslov;
    if (!v.n.id) { if (v.k) odpriIzKataloga(v.k); else klic("odpriRazdelek", ["mediji:" + kaj]); return; }
    var m = { title: kaj, kind: v.k ? (v.k.vrsta || "") : "", year: v.k && v.k.leto ? Number(v.k.leto) || null : null };
    klic("odpriMedijNa", [v.n.id, JSON.stringify(m)]).then(function (izid) {
      var koda = izid && (izid.koda || izid.code);
      if (izid && izid.ok) obvesti(t("prikazanoNa", { ime: v.n.ime, kaj: kaj }));
      else if (koda === "neznano_dejanje" || koda === "stari_control") obvesti(t("napravaNeZna", { ime: v.n.ime }));
      else obvesti(t("niUspelo"));
    }).catch(function () { obvesti(t("niUspelo")); });
  }
  function prikaziKatalogNa(k) {
    var n = I.napraveCilja || [];
    if (n.length === 1) { prikaziNa({ n: n[0], k: k }); return; }
    if (!n.length) { obvesti(t("niNapraveCilja")); return; }
    izrisiZadetke([{ naslov: t("izberiNapravo"), vnosi: n.map(function (x) { return { vrsta: "naCilj", n: x, k: k, naslov: k.naslov }; }) }]);
    $("iskalnoPolje").focus();
  }
  function odpriNapravo(v) {
    if (v.datoteke) {
      if (N.skrite.indexOf("datoteke") >= 0) nastaviSkrito("datoteke", false);
      odpriVir({ vrsta: "naprava", id: v.n.id, ime: v.n.ime, pot: [] });
    } else {
      if (N.skrite.indexOf("programi") >= 0) nastaviSkrito("programi", false);
      $("prgNaprava").value = v.n.id; P.kategorija = "vse"; P.rocno = true; P.stran = 0; izrisiPrograme();
    }
  }
  function odpriSplet(q) {
    // Spletni zadetek: rezultati v plosci na namizju, tik pod iskalnim poljem (isti vgrajeni brskalnik kot Splet v
    // Safeer OS, z vsemi moznostmi). Brez tega (starejsi Safeer OS, brez peskovnika) privzeti brskalnik.
    if (N.spletVBrskalniku) {
      klic("odpriVBrskalniku", [q]).then(function (ok) { if (ok === false) klic("iskanjeSplet", [q]); })
        .catch(function () { klic("iskanjeSplet", [q]); });
      return;
    }
    var r = $("iskalnoPolje").getBoundingClientRect();
    klic("spletNaNamizju", [q, Math.round(r.bottom)]).then(function (ok) { if (ok === false) return klic("odpriVBrskalniku", [q]); })
      .catch(function () { klic("odpriVBrskalniku", [q]).catch(function () { klic("iskanjeSplet", [q]); }); });
  }

  // ------------------------------------------------------------------ SAFEER LINK (gumb pod iskalnikom)
  // Samo prikaz stanja; prijavno okno (Safeer Control) se odpre izkljucno na klik uporabnika.
  var L = { stanje: null, casovnik: 0 };
  function steviloNaprav(n) {
    var m100 = n % 100;
    if (jezik !== "sl") return t(n === 1 ? "naprav1" : "napravN", { n: n });
    if (m100 === 1) return t("naprav1");
    if (m100 === 2) return t("naprav2");
    if (m100 === 3 || m100 === 4) return t("naprav34", { n: n });
    return t("napravN", { n: n });
  }
  function izrisiLink() {
    var g = $("gumbLink"), p = L.stanje;
    if (!p || !p.control) { g.hidden = true; return; }
    var povezan = p.stanje === "povezan";
    var ids = {};
    P.naprave.concat(D.naprave).forEach(function (n) { if (n && n.id) ids[n.id] = 1; });
    var n = Object.keys(ids).length;
    g.hidden = false;
    g.classList.toggle("povezan", povezan);
    g.classList.toggle("nepovezan", !povezan);
    $("linkBesedilo").textContent = povezan ? (n ? t("linkPovezan", { n: steviloNaprav(n) }) : t("linkPovezanBrez")) : t("linkPovezi");
    g.title = t("linkNaslov");
  }
  function osveziLink() {
    clearTimeout(L.casovnik);
    if (!most) return;
    klic("povezava").then(function (p) { L.stanje = p || null; izrisiLink(); }).catch(function () {});
    L.casovnik = setTimeout(osveziLink, 60000);
  }

  // ------------------------------------------------------------------ vezave
  var zadnjeOsvezevanje = Date.now();
  function vezi() {
    var polje = $("iskalnoPolje");
    var mik = $("gumbMikrofon");
    mik.setAttribute("aria-label", t("mikrofonNaslov")); mik.title = t("mikrofonNaslov");
    mik.addEventListener("click", mikrofonKlik);
    $("govorPreklici").setAttribute("aria-label", t("govorPreklici")); $("govorPreklici").title = t("govorPreklici");
    $("govorKoncaj").setAttribute("aria-label", t("govorKoncaj")); $("govorKoncaj").title = t("govorKoncaj");
    $("govorPreklici").addEventListener("click", function () { klic("govorPreklici"); });
    $("govorKoncaj").addEventListener("click", function () { klic("govorUstavi"); });
    narisiValove();
    polje.addEventListener("input", function () { clearTimeout(I.casovnik); var q = polje.value; I.casovnik = setTimeout(function () { isci(q); }, 220); });
    polje.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        if (!I.zadetki.length) return;
        e.preventDefault(); I.rocno = true; I.izbran = (I.izbran + (e.key === "ArrowDown" ? 1 : -1) + I.zadetki.length) % I.zadetki.length; oznaciZadetek();
      } else if (e.key === "Escape") {
        if (G.stanje === "poslusam" || G.stanje === "prepoznavam") klic("govorPreklici");
        skrijZadetke(); polje.value = ""; I.poEnter = false;
      }
      else if (e.key === "Enter" && e.shiftKey) {
        // Shift+Enter: vedno splet, tudi ce se ujema program.
        e.preventDefault();
        var niz = polje.value.trim(); if (!niz) return;
        clearTimeout(I.casovnik); I.st++; I.poEnter = false;
        izberiZadetek({ vrsta: "splet", q: niz });
      }
    });
    $("iskanje").addEventListener("submit", function (e) {
      e.preventDefault();
      var q = polje.value.trim(); if (!q) return;
      if (!I.rocno && (q !== I.zadnji || I.caka)) {
        // Zadetki za ta niz se niso tu (hitro tipkanje + Enter): odloci, ko pridejo vsi (najvec 1,5 s).
        I.poEnter = true;
        if (q !== I.zadnji) { clearTimeout(I.casovnik); isci(q); I.poEnter = true; }
        clearTimeout(I.enterCasovnik);
        I.enterCasovnik = setTimeout(function () { if (I.hitriEnter) I.hitriEnter(); }, 1500);
        return;
      }
      var b = I.zadetki[I.izbran];
      if (b && b._v.vrsta === "naCilj" && b._v.izberi && !I.rocno) { obvesti(t("izberiNapravo")); return; }
      izberiZadetek(b ? b._v : { vrsta: "splet", q: q });
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        zapriMeni(); $("meniPlosce").hidden = true;
        if (G.stanje === "poslusam" || G.stanje === "prepoznavam") klic("govorPreklici");   // polje je med govorom skrito
      }
      var vPolju = /^(INPUT|SELECT|TEXTAREA)$/.test((document.activeElement || {}).tagName || "");
      if ((e.ctrlKey && (e.key === "k" || e.key === "K")) || (!vPolju && e.key === "/")) { e.preventDefault(); polje.focus(); polje.select(); }
    });
    document.addEventListener("click", function (e) {
      if (meniOdprt && !meniOdprt.contains(e.target) && !e.target.closest(".program")) zapriMeni();
      if (!e.target.closest(".vrh")) skrijZadetke();
      if (!e.target.closest(".vrh-orodja")) { $("meniPlosce").hidden = true; $("gumbPlosce").setAttribute("aria-expanded", "false"); }
    });

    // Plosce, postavitev, dostopnost
    $("gumbPlosce").addEventListener("click", function () {
      var m = $("meniPlosce"); m.hidden = !m.hidden; this.setAttribute("aria-expanded", m.hidden ? "false" : "true");
    });
    document.querySelectorAll("#meniPlosce input[data-plosca]").forEach(function (cb) {
      cb.addEventListener("change", function () { nastaviSkrito(cb.getAttribute("data-plosca"), !cb.checked); });
    });
    document.querySelectorAll("[data-skrij]").forEach(function (b) {
      b.addEventListener("click", function () { nastaviSkrito(b.getAttribute("data-skrij"), true); });
    });
    $("gumbZamenjaj").addEventListener("click", function () { N.zamenjano = !N.zamenjano; shrani(); uveljaviPostavitev(); });
    $("gumbPonastavi").addEventListener("click", function () {
      var ohrani = { priljubljeniPrg: N.priljubljeniPrg, kategorije: N.kategorije, priljubljeneDat: N.priljubljeneDat };
      N = JSON.parse(JSON.stringify(PRIVZETO)); Object.keys(ohrani).forEach(function (k) { N[k] = ohrani[k]; });
      shrani(); uveljaviPostavitev();
    });
    $("stikaloTekst").addEventListener("change", function () {
      if (V.naVoljo) { klic("videzCinnamonNastavi", ["tekst", this.checked]).then(nastaviVidez).catch(uveljaviPostavitev); return; }
      N.vecjiTekst = this.checked; shrani(); uveljaviPostavitev();
    });
    $("izbiraTeksta").addEventListener("change", function () {
      klic("videzCinnamonNastavi", ["tekst", Number(this.value)]).then(nastaviVidez).catch(uveljaviPostavitev);
    });
    // Sistemske nastavitve namizja (Cinnamon): odpre jih sistem, uporabnik ima vse moznosti.
    Array.prototype.forEach.call(document.querySelectorAll("[data-modul]"), function (b) {
      b.addEventListener("click", function () { klic("sistemskeNastavitve", [b.getAttribute("data-modul")]).catch(function () {}); });
    });
    // Uporabnik, ki mu je ljubsi drug brskalnik: iskanje po spletu iz zgornjega polja odpre privzeti brskalnik sistema.
    $("stikaloBrskalnik").addEventListener("change", function () { N.spletVBrskalniku = this.checked; shrani(); });
    klic("privzetiBrskalnik", []).then(function (ime) {
      if (ime) $("napisBrskalnik").textContent = t("spletVBrskalnikuIme", { ime: ime });
    }).catch(function () {});
    $("stikaloProsojnost").addEventListener("change", function () {
      if (V.naVoljo) { klic("videzCinnamonNastavi", ["kontrast", this.checked]).then(nastaviVidez).catch(uveljaviPostavitev); return; }
      N.manjProsojnosti = this.checked; shrani(); uveljaviPostavitev();
    });

    // Nova mapa / datoteka: gumb +, desni klik na prazno, Ctrl+Shift+N, okno
    $("gumbNovo").addEventListener("click", function (ev) {
      // Sicer bi splosni »klik drugam zapre meni« (document) meni takoj zaprl.
      ev.stopPropagation();
      var r = this.getBoundingClientRect(); meniNovo(r.left, r.bottom + 4);
    });
    document.querySelector(".dat-glavno").addEventListener("contextmenu", function (ev) {
      if (ev.target.closest("tbody tr") || ev.target.closest("input, select, button")) return;
      ev.preventDefault(); meniNovo(ev.clientX, ev.clientY);
    });
    // Spust v prazen del seznama = v odprto mapo.
    ciljSpusta(document.querySelector(".dat-glavno"), function () { return D.vir && D.vir.vrsta === "lokalno" ? D.vir.pot : ""; });
    $("ploscaDatoteke").addEventListener("keydown", function (ev) {
      if (ev.ctrlKey && ev.shiftKey && (ev.key === "N" || ev.key === "n")) { ev.preventDefault(); odpriOknoNovo({ nacin: "mapa", kam: kamNovo() }); }
      // Ctrl+A izbere vse v seznamu (tudi na drugih straneh); v polju za vnos ostane izbira besedila.
      else if (ev.ctrlKey && !ev.shiftKey && !ev.altKey && (ev.key === "a" || ev.key === "A") && !ev.target.closest("input, textarea, select")) {
        ev.preventDefault(); izberiVse(); oznaciIzbrano();
      }
      // Ctrl+Z razveljavi zadnje dejanje z datotekami (v polju za vnos ostane razveljavitev tipkanja).
      else if (ev.ctrlKey && !ev.shiftKey && !ev.altKey && (ev.key === "z" || ev.key === "Z") && !ev.target.closest("input, textarea, select")) {
        ev.preventDefault(); razveljavi();
      }
      // Ctrl+V prilepi v odprto mapo (v polju za vnos ostane navadno lepljenje besedila).
      else if (ev.ctrlKey && !ev.shiftKey && !ev.altKey && (ev.key === "v" || ev.key === "V") && O.poti.length &&
               D.vir && D.vir.vrsta === "lokalno" && !ev.target.closest("input, textarea, select")) { ev.preventDefault(); prilepi(null); }
    });
    $("obrazecNovo").addEventListener("submit", function (ev) { ev.preventDefault(); potrdiNovo(); });
    $("novoPreklici").addEventListener("click", zapriOknoNovo);
    $("oknoNovo").addEventListener("keydown", function (ev) { if (ev.key === "Escape") { ev.stopPropagation(); zapriOknoNovo(); } });
    $("oknoNovo").addEventListener("mousedown", function (ev) { if (ev.target === this) zapriOknoNovo(); });
    $("novoVrsta").addEventListener("change", function () {
      // Ime sledi vrsti, dokler ga uporabnik ni spremenil sam.
      var polje = $("novoIme"), prej = VRSTE_NOVIH.map(function (v) { return t(v[2]); });
      if (prej.indexOf(polje.value) < 0 && predlogeDatotek.map(function (p) { return p.ime; }).indexOf(polje.value) < 0) return;
      var v = this.value;
      polje.value = v.indexOf("predloga:") === 0 ? (predlogeDatotek.filter(function (p) { return "predloga:" + p.pot === v; })[0] || {}).ime || polje.value
        : t((VRSTE_NOVIH.filter(function (x) { return x[0] === v; })[0] || VRSTE_NOVIH[0])[2]);
    });
    $("novoSpremeni").addEventListener("click", function () {
      klic("izberiMapo", [NO.kam || "~", t("izberiMapoNaslov"), t("preklici"), t("izberi")]).then(function (p) {
        if (p) nastaviKje(p);
        $("novoIme").focus();
      }).catch(function () {});
    });

    // Datoteke
    $("datFilter").addEventListener("input", function () { D.stran = 0; izrisiDatoteke(); });
    $("datVrsta").addEventListener("change", function () { D.stran = 0; izrisiDatoteke(); });
    document.querySelectorAll("#datSeznam th button").forEach(function (b) {
      b.addEventListener("click", function () {
        var k = b.getAttribute("data-razvrsti");
        if (D.razvrsti === k && D.rocno) D.smer = -D.smer; else { D.razvrsti = k; D.smer = k === "spremenjeno" ? -1 : 1; }
        D.rocno = true; izrisiDatoteke();
      });
    });
    $("ploscaDatoteke").addEventListener("keydown", function (e) {
      if (e.key === "PageDown" || e.key === "PageUp") {
        e.preventDefault(); var b = $("datStrani").querySelectorAll("button")[e.key === "PageDown" ? 1 : 0];
        if (b && !b.disabled) b.click();
      }
    });

    // Programi
    $("prgFilter").addEventListener("input", function () {
      P.stran = 0; izrisiPrograme();
      // Kdor isce program, ki ga je pravkar namestil, ga mora najti: seznam preberemo znova (najvec na 5 s).
      if (Date.now() - lokalniOb > 5000) naloziLokalnePrograme();
    });
    $("prgNaprava").addEventListener("change", function () {
      try { localStorage.setItem("safeer_prg_naprava", this.value); } catch (e) { /* ni shrambe */ }
      P.stran = 0; izrisiPrograme();
    });
    $("prgRazvrsti").addEventListener("change", function () { izrisiPrograme(); });
    $("prgNamesti").addEventListener("click", ponudnikiProgramov);
    $("prgPogled").addEventListener("click", function () { N.pogled = N.pogled === "seznam" ? "mreza" : "seznam"; shrani(); P.stran = 0; izrisiPrograme(); });
    $("ploscaProgrami").addEventListener("keydown", function (e) {
      if (e.key === "PageDown" || e.key === "PageUp") {
        e.preventDefault(); var b = $("prgStrani").querySelectorAll("button")[e.key === "PageDown" ? 1 : 0];
        if (b && !b.disabled) b.click();
      }
    });

    // Safeer Link, ozadje, dock
    $("gumbLink").addEventListener("click", function () {
      // Povezan racunalnik: okno »Poveži naprave« (QR ALI 6-mestna koda). Nepovezan: prijavno okno
      // (QR / vpis kode / brez povezave). Oboje v Safeer Controlu; prijavno okno se pokaze tudi samo ob prijavi
      // v namizje, ce racunalnik ni povezan (safeer_os._prijavno_okno_ob_prijavi).
      var povezan = L.stanje && L.stanje.stanje === "povezan";
      klic(povezan ? "novaNaprava" : "prijava").then(function (ok) { if (ok === false) obvesti(t("brezControla")); })
        .catch(function () {});
      setTimeout(osveziLink, 8000);
    });
    $("gumbOzadje").addEventListener("click", function () { $("meniPlosce").hidden = true; klic("nastavitveOzadja"); });
    $("gumbDock").addEventListener("click", function () { $("meniPlosce").hidden = true; urediDock(); });

    // Mediji
    document.querySelectorAll("#kontrole [data-ukaz]").forEach(function (b) {
      b.addEventListener("click", function () { klic("predvajalnikUkaz", [b.getAttribute("data-ukaz")]).then(medijOsvezi); });
    });
    // »media« odpre Medijski center v svojem oknu Safeer Player, ne cele lupine Safeer OS (safeer_os.py _odpri_razdelek).
    $("gumbMedijskiCenter").addEventListener("click", function () { klic("odpriRazdelek", ["media"]).catch(function () {}); });

    // Velikost okna: prerazporedi strani (brez pomikanja)
    var rt = 0;
    window.addEventListener("resize", function () { clearTimeout(rt); rt = setTimeout(function () { izrisiDatoteke(); izrisiPrograme(); }, 120); });
    document.addEventListener("visibilitychange", function () { if (!document.hidden) medijZanka(); });
    // Dogodki iz Safeer OS (enako ime kot na glavni strani): osvezi, kar se je spremenilo.
    window.safeerOsDogodek = function (vrsta) {
      if (vrsta === "medijskaKnjiznica") medijOsvezi();
      else if (vrsta === "govor") govorDogodek(arguments[1] || {});
      else if (vrsta === "iskanjeOdDrugod") {
        // Glas s telefona (Safeer Link): niz v lupo, kot bi ga uporabnik natipkal ali povedal tu.
        var q = String((arguments[1] || {}).q || "").trim(), polje = $("iskalnoPolje");
        if (q) { polje.value = q; polje.focus(); clearTimeout(I.casovnik); isci(q); }
      }
      else if (vrsta === "ozadje") {
        var u = arguments[1] || "";
        document.documentElement.style.setProperty("--ozadje-slika", u ? 'url("' + u + '")' : "none");
      }
      else if (vrsta === "robovi") { robovi(arguments[1] || {}); izrisiDatoteke(); izrisiPrograme(); }
      else if (vrsta === "videz") nastaviVidez(arguments[1]);
      else if (vrsta === "vleceneDatoteke") { VL.zunanje = (arguments[1] && arguments[1].stevilo) || 0; if (!VL.zunanje) pocistiCilje(); }
      else if (vrsta === "vlecenjeKoncano") koncajVlecenje(!!(arguments[1] && arguments[1].sprejeto));
      else if (vrsta === "programi") naloziLokalnePrograme();     // program namescen ali odstranjen
      // Prikazana mapa (nedavne, Smeti) se je spremenila zunaj Safeer OS; nosilec priklopljen ali odklopljen.
      else if (vrsta === "datoteke") { if (arguments[1] && arguments[1].pot === pogledVira(D.vir)) osveziVirTiho(); }
      else if (vrsta === "nosilci") osveziNosilce();
      else if (vrsta === "fokus" && Date.now() - zadnjeOsvezevanje > 30000) {
        // Naprave v Linku se spreminjajo: ob vrnitvi v Safeer OS osvezimo najvec vsakih 30 s.
        zadnjeOsvezevanje = Date.now(); zgradiStranDatotek(); naloziProgrameNaprav(); osveziLink();
      }
    };
  }
  // Skrij vedno deluje, tudi pri zadnji plosci (prej je bil gumb tam brez ucinka - lastnik, 11. 10. 2026): skrite
  // plosce so v polju pod iskanjem in se vrnejo z enim klikom; ozadje namizja ostane cisto.
  function nastaviSkrito(p, skrij) {
    N.skrite = N.skrite.filter(function (x) { return x !== p; });
    if (skrij) N.skrite.push(p);
    shrani(); uveljaviPostavitev();
  }
  var PLOSCE = [["mediji", "medijiNaslov", "M9 18V5l12-2v13 M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0z M21 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0z"],
                ["datoteke", "datotekeNaslov", "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"],
                ["programi", "programiNaslov", "M4 4h6v6H4z M14 4h6v6h-6z M4 14h6v6H4z M14 14h6v6h-6z"]];
  function narisiSkritePlosce() {
    var polje = $("skritePlosce");
    if (!polje) return;
    polje.textContent = "";
    PLOSCE.forEach(function (pl) {
      if (N.skrite.indexOf(pl[0]) < 0) return;
      var ime = t(pl[1]);
      var b = el("button", "skrita-plosca");
      b.type = "button";
      b.setAttribute("aria-label", t("pokaziPlosco", { ime: ime }));
      b.title = t("pokaziPlosco", { ime: ime });
      var ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg"), pot = document.createElementNS(ns, "path");
      svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true"); pot.setAttribute("d", pl[2]);
      svg.appendChild(pot); b.appendChild(svg);
      b.appendChild(document.createTextNode(ime));
      b.addEventListener("click", function () { nastaviSkrito(pl[0], false); });
      polje.appendChild(b);
    });
    polje.hidden = !polje.childNodes.length;
  }

  window.SafeerDelovna = { osvezi: function () { zgradiStranDatotek(); naloziProgrameNaprav(); medijOsvezi(); } };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", zacni); else zacni();
})();
