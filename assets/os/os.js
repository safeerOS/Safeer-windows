/* Safeer OS za racunalnik: domaci zaslon, programi, datoteke, naprave, nastavitve.
 * Vse sistemsko gre skozi most window.SafeerOS.klic(metoda, argumenti) -> Promise (safeer_os.py).
 * Brez mosta (predogled v brskalniku) stran pokaze prazno, a delujoco lupino. */
(function () {
  "use strict";

  // ------------------------------------------------------------------ ikone (24 x 24, crte)
  var IK = {
    domov: "M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z",
    programi: "M4 4h6v6H4z M14 4h6v6h-6z M4 14h6v6H4z M14 14h6v6h-6z",
    mapa: "M3 6a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z",
    povezava: "M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1 M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1",
    drsniki: "M4 7h10 M18 7h2 M4 17h4 M12 17h8 M16 5v4 M10 15v4",
    napajanje: "M12 3v8 M6.3 6.3a8 8 0 1 0 11.4 0",
    isci: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z M20 20l-4-4",
    splet: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M3 12h18 M12 3c2.5 2.5 3.8 5.5 3.8 9s-1.3 6.5-3.8 9 M12 3C9.5 5.5 8.2 8.5 8.2 12s1.3 6.5 3.8 9",
    desno: "M9 6l6 6-6 6",
    nazaj: "M15 6l-6 6 6 6",
    naprave: "M2 5h14v10H2z M6 19h6 M9 15v4 M17 9h4a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-4a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1z",
    qr: "M4 4h6v6H4z M14 4h6v6h-6z M4 14h6v6H4z M14 14h2v2h-2z M18 14h2 M14 18h2 M18 18h2v2",
    poslji: "M4 12l16-8-6 16-2-7z",
    zaslon: "M3 4h18v12H3z M8 20h8 M12 16v4 M10 8l4 2-4 2z",
    daljinec: "M8 2h8a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z M12 6v.1 M10 11h4 M12 9v4 M10 17h4",
    celozaslonsko: "M4 9V4h5 M15 4h5v5 M20 15v5h-5 M9 20H4v-5",
    namizje: "M3 4h18v13H3z M3 14h18 M9 21h6",
    zvok: "M4 9v6h4l5 4V5L8 9z M16 9a4 4 0 0 1 0 6 M18.5 6.5a8 8 0 0 1 0 11",
    utisan: "M4 9v6h4l5 4V5L8 9z M17 9l5 6 M22 9l-5 6",
    wifi: "M2 9a15 15 0 0 1 20 0 M5 12.5a10 10 0 0 1 14 0 M8.5 16a5 5 0 0 1 7 0 M12 19.5v.1",
    ethernet: "M4 10h16v8H4z M8 18v2 M12 18v2 M16 18v2 M9 10V6h6v4",
    brezOmrezja: "M2 9a15 15 0 0 1 20 0 M8.5 16a5 5 0 0 1 7 0 M3 3l18 18",
    baterija: "M3 8h15v8H3z M20 11v2",
    polni: "M3 8h15v8H3z M20 11v2 M11 9l-2 3h3l-2 3",
    svetlost: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z M12 2v2 M12 20v2 M4.9 4.9l1.4 1.4 M17.7 17.7l1.4 1.4 M2 12h2 M20 12h2 M4.9 19.1l1.4-1.4 M17.7 6.3l1.4-1.4",
    luna: "M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z",
    zakleni: "M6 11h12v9H6z M8 11V8a4 4 0 0 1 8 0v3",
    odjava: "M14 4h5v16h-5 M10 16l-4-4 4-4 M6 12h10",
    ponovno: "M20 12a8 8 0 1 1-2.3-5.7 M20 4v5h-5",
    zvezda: "M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z",
    x: "M6 6l12 12 M18 6L6 18",
    plus: "M12 5v14 M5 12h14",
    film: "M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z M2 9h20 M2 15h20 M7 4v5 M12 4v5 M17 4v5 M7 15v5 M12 15v5 M17 15v5",
    serija: "M4 6h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z M8 2l4 4 4-4 M8 20v2 M16 20v2",
    tv: "M2 5h20v13H2z M8 21h8 M12 18v3",
    radio: "M3 7h18a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z M6 7l12-4 M6.5 14.5a2.5 2.5 0 1 0 5 0 2.5 2.5 0 0 0-5 0z M15 12h3 M15 15h3",
    "tv-v-zivo": "M2 6h15v12H2z M6 21h7 M9.5 18v3 M19 9a3 3 0 0 1 0 6 M21 7a6 6 0 0 1 0 10",
    telefon: "M6 2h12a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z M12 18h.01",
    tablica: "M4 2h16a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z M12 18h.01",
    iskra: "M12 2l2.4 5.6L20 10l-5.6 2.4L12 18l-2.4-5.6L4 10l5.6-2.4z M19 16l1.2 2.8L23 20l-2.8 1.2L19 24l-1.2-2.8L15 20l2.8-1.2z",
    sporocilo: "M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z",
    slika: "M4 4h16v16H4z M4 16l5-5 4 4 3-3 4 4 M15 8.5v.1",
    video: "M3 6h13v12H3z M16 10l5-3v10l-5-3",
    glasba: "M9 18V5l11-2v13 M9 18a3 3 0 1 1-3-3 3 3 0 0 1 3 3z M20 16a3 3 0 1 1-3-3 3 3 0 0 1 3 3z",
    dokument: "M6 3h8l4 4v14H6z M14 3v4h4 M9 12h6 M9 16h6",
    arhiv: "M4 4h16v4H4z M5 8v12h14V8 M10 12h4",
    program: "M4 5h16v14H4z M4 9h16 M8 13l2 2-2 2 M12 17h4",
    datoteka: "M6 3h8l4 4v14H6z M14 3v4h4",
    paleta: "M12 3a9 9 0 1 0 0 18c1 0 1.5-.8 1.5-1.5 0-.9-.7-1.2-.7-2 0-.8.7-1.5 1.5-1.5H16a5 5 0 0 0 5-5c0-4.4-4-8-9-8z M7.5 11v.1 M10 7.5v.1 M14 7.5v.1",
    scit: "M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z",
    tipkovnica: "M3 6h18v12H3z M7 10h.1 M11 10h.1 M15 10h.1 M7 14h10",
    miska: "M12 3a6 6 0 0 1 6 6v6a6 6 0 0 1-12 0V9a6 6 0 0 1 6-6z M12 7v3",
    bluetooth: "M7 7l10 10-5 4V3l5 4L7 17",
    tiskalnik: "M6 9V3h12v6 M6 18H4v-7h16v7h-2 M6 14h12v7H6z",
    uporabnik: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M4 21a8 8 0 0 1 16 0",
    zvonec: "M6 16v-5a6 6 0 0 1 12 0v5l2 2H4z M10 20a2 2 0 0 0 4 0",
    ura: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 7v5l3 2",
    disk: "M4 6h16v12H4z M4 13h16 M16 16v.1",
    slusalke: "M4 15v-3a8 8 0 0 1 16 0v3 M4 15h3v5H5a1 1 0 0 1-1-1z M20 15h-3v5h2a1 1 0 0 0 1-1z",
    mikrofon: "M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3z M5 11a7 7 0 0 0 14 0 M12 18v3"
  };
  function svg(ime) {
    return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="' + (IK[ime] || IK.datoteka) + '"/></svg>';
  }

  // ------------------------------------------------------------------ most
  var most = window.SafeerOS || null;
  function klic(metoda, argumenti) {
    if (!most) return Promise.reject("brez mosta");
    return most.klic(metoda, argumenti || []);
  }

  // ------------------------------------------------------------------ besedila
  var jezik = "sl";
  function t(kljuc, zamenjave) {
    var b = (BESEDILA_OS[jezik] && BESEDILA_OS[jezik][kljuc]);
    if (b == null) b = BESEDILA_OS.en[kljuc];
    if (b == null) b = kljuc;
    if (zamenjave) Object.keys(zamenjave).forEach(function (k) { b = b.split("{" + k + "}").join(zamenjave[k]); });
    return b;
  }
  var LOKALE = { sl: "sl-SI", en: "en-GB", de: "de-DE", es: "es-ES", fr: "fr-FR", it: "it-IT" };
  var BESEDILA_WINDOWS = {
    sl: {
      naprednoPod: "IP, DNS, VPN in druge nastavitve sistema Windows.",
      zvokNaprednoPod: "Izhodne naprave, mikrofon in druge nastavitve zvoka sistema Windows.",
      samozagonPod: "Upravljaš ga lahko tudi v zagonskih aplikacijah sistema Windows.",
      nazajVMint: "Nazaj v Windows", nazajVMintPod: "Zapri Safeer OS in pokaži namizje Windows.",
      nazajOpis: "Safeer OS se zapre in prikaže običajno namizje Windows. Znova ga lahko odpreš iz menija Start.",
      nastavitveOpis: "Najpomembnejše nastavitve sistema Windows na enem preglednem mestu.",
      pokaziNamizje: "Pokaži namizje Windows", pokaziNamizjePod: "Safeer OS se umakne v opravilno vrstico.",
      razlicica: "Safeer OS {v} · za Windows",
      scitNiMozno: "Ščit ni na voljo na tej napravi.",
      scitNapaka_ni_resolved: "Napaka pri vzpostavitvi povezave za Ščit."
    },
    en: {
      naprednoPod: "IP, DNS, VPN and other Windows settings.",
      zvokNaprednoPod: "Output devices, microphone and other Windows sound settings.",
      samozagonPod: "You can also manage this in Windows Startup apps.",
      nazajVMint: "Back to Windows", nazajVMintPod: "Close Safeer OS and show the Windows desktop.",
      nazajOpis: "Safeer OS closes and shows the regular Windows desktop. Open it again from the Start menu.",
      nastavitveOpis: "The most important Windows settings in one clear place.",
      pokaziNamizje: "Show the Windows desktop", pokaziNamizjePod: "Safeer OS moves to the taskbar.",
      razlicica: "Safeer OS {v} · for Windows",
      scitNiMozno: "Shield is not available on this device.",
      scitNapaka_ni_resolved: "Error establishing connection for Shield."
    },
    de: {
      naprednoPod: "IP, DNS, VPN und weitere Windows-Einstellungen.",
      zvokNaprednoPod: "Ausgabegeräte, Mikrofon und weitere Windows-Soundeinstellungen.",
      samozagonPod: "Auch unter Windows-Autostart-Apps verwaltbar.",
      nazajVMint: "Zurück zu Windows", nazajVMintPod: "Safeer OS schließen und den Windows-Desktop anzeigen.",
      nazajOpis: "Safeer OS wird geschlossen und der normale Windows-Desktop angezeigt. Über das Startmenü kannst du es erneut öffnen.",
      nastavitveOpis: "Die wichtigsten Windows-Einstellungen übersichtlich an einem Ort.",
      pokaziNamizje: "Windows-Desktop anzeigen", pokaziNamizjePod: "Safeer OS wird in die Taskleiste minimiert.",
      razlicica: "Safeer OS {v} · für Windows",
      scitNiMozno: "Der systemweite Schutz ist in dieser Windows-Version noch nicht verfügbar. Safeer Browser schützt weiterhin das Web.",
      scitNapaka_ni_resolved: "Der systemweite Schutz ist in dieser Windows-Version noch nicht verfügbar."
    },
    es: {
      naprednoPod: "IP, DNS, VPN y otros ajustes de Windows.",
      zvokNaprednoPod: "Dispositivos de salida, micrófono y otros ajustes de sonido de Windows.",
      samozagonPod: "También puedes gestionarlo en Aplicaciones de inicio de Windows.",
      nazajVMint: "Volver a Windows", nazajVMintPod: "Cerrar Safeer OS y mostrar el escritorio de Windows.",
      nazajOpis: "Safeer OS se cierra y muestra el escritorio habitual de Windows. Ábrelo de nuevo desde Inicio.",
      nastavitveOpis: "Los ajustes más importantes de Windows en un solo lugar.",
      pokaziNamizje: "Mostrar el escritorio de Windows", pokaziNamizjePod: "Safeer OS se minimiza en la barra de tareas.",
      razlicica: "Safeer OS {v} · para Windows",
      scitNiMozno: "El Escudo de todo el sistema aún no está disponible en esta versión para Windows. Safeer Browser sigue protegiendo la web.",
      scitNapaka_ni_resolved: "El Escudo de todo el sistema aún no está disponible en esta versión para Windows."
    },
    fr: {
      naprednoPod: "IP, DNS, VPN et autres paramètres Windows.",
      zvokNaprednoPod: "Périphériques de sortie, microphone et autres paramètres audio Windows.",
      samozagonPod: "Également gérable dans les applications de démarrage Windows.",
      nazajVMint: "Retour à Windows", nazajVMintPod: "Fermer Safeer OS et afficher le bureau Windows.",
      nazajOpis: "Safeer OS se ferme et affiche le bureau Windows habituel. Rouvrez-le depuis le menu Démarrer.",
      nastavitveOpis: "Les principaux paramètres Windows réunis clairement au même endroit.",
      pokaziNamizje: "Afficher le bureau Windows", pokaziNamizjePod: "Safeer OS se réduit dans la barre des tâches.",
      razlicica: "Safeer OS {v} · pour Windows",
      scitNiMozno: "Le Bouclier système n'est pas encore disponible dans cette version Windows. Safeer Browser continue de protéger le Web.",
      scitNapaka_ni_resolved: "Le Bouclier système n'est pas encore disponible dans cette version Windows."
    },
    it: {
      naprednoPod: "IP, DNS, VPN e altre impostazioni di Windows.",
      zvokNaprednoPod: "Dispositivi di uscita, microfono e altre impostazioni audio di Windows.",
      samozagonPod: "Puoi gestirlo anche nelle app di avvio di Windows.",
      nazajVMint: "Torna a Windows", nazajVMintPod: "Chiudi Safeer OS e mostra il desktop di Windows.",
      nazajOpis: "Safeer OS si chiude e mostra il normale desktop di Windows. Riaprilo dal menu Start.",
      nastavitveOpis: "Le impostazioni principali di Windows in un unico posto chiaro.",
      pokaziNamizje: "Mostra il desktop di Windows", pokaziNamizjePod: "Safeer OS si riduce nella barra delle applicazioni.",
      razlicica: "Safeer OS {v} · per Windows",
      scitNiMozno: "Lo Scudo di sistema non è ancora disponibile in questa versione Windows. Safeer Browser continua a proteggere il Web.",
      scitNapaka_ni_resolved: "Lo Scudo di sistema non è ancora disponibile in questa versione Windows."
    }
  };
  var BESEDILA_MEDIA = {
    sl: { mediaOpis:"Filmi, serije in glasba iz vseh tvojih virov v enem katalogu.",mediaOsvezi:"Osveži vire",mediaNastavitve:"Nastavitve",mediaNastavitveNaslov:"Nastavitve Safeer Media",mediaNastavitveOpis:"Uvoz in izvoz JSON knjižnic, neposreden vnos kode ter upravljanje virov.",mediaUvozDatoteke:"Naloži izvoženo JSON datoteko",mediaUvozDatotekeOpis:"Izberite .json datoteko kataloga ali virov, ki ste jo izvozili prej ali prejeli iz druge naprave.",mediaIzberiDatoteko:"Izberi .json datoteko",mediaNobenaDatoteka:"Nobena datoteka ni izbrana",mediaUvoziDatoteko:"Uvozi datoteko",mediaVnosJson:"Vnesi svojo JSON kodo",mediaVnosJsonOpis:"Prilepite JSON seznam medijev, prilagojeno konfiguracijo ali vir s tokovi.",mediaJsonImePh:"Ime zbirke ali vira (neobvezno)",mediaUvoziKodo:"Uvozi JSON kodo",mediaVstaviPrimer:"Primer kode (Code Example)",mediaPocisti:"Počisti",mediaPrimerVstavljen:"Primer JSON kode je bil uspešno vstavljen.",mediaIzvozJson:"Izvozi vsebine v JSON",mediaIzvozJsonOpis:"Prenesite celotno zbirko vaših virov in nastavitev v datoteko za varnostno kopijo ali prenos.",mediaPrenesiIzvoz:"Prenesi izvoženi JSON",mediaUvozUspesen:"Uspešno uvoženo: {n} vsebin v vir '{vir}'.",mediaUvozVirovUspesen:"Uspešno posodobljenih/dodanih virov: {n}.",mediaUvozNapaka:"Napaka pri uvozu JSON.",mediaVnesiteJson:"Prosimo, vnesite ali izberite veljavno JSON kodo.",mediaPredvaja:"PREDVAJA SE V SAFEER OS",mediaNapaka:"Tega toka ni mogoče predvajati. Poskusi drugo različico.",mediaIsci:"Išči filme, serije, videe, glasbo in radio",mediaVse:"Vse",mediaFilmi:"Filmi",mediaSerije:"Serije",mediaGlasba:"Glasba",mediaPrazno:"Ni zadetkov. Dodaj vir ali spremeni iskanje.",mediaViri:"Tvoji viri",mediaViriOpis:"Spletno stran, javni API, RSS ali M3U dodaš samo enkrat.",mediaVirIme:"Ime vira (neobvezno)",mediaVirUrl:"https://tilvids.com",mediaDodaj:"Dodaj vir",mediaZadetkov:"{n} enotnih vsebin",mediaRazlicic:"{n} različic",mediaVirDodan:"Vir je dodan in katalog združen.",mediaVirPodvojen:"Ta vir je že dodan.",mediaVirNapaka:"Vira ni bilo mogoče prebrati.",mediaOsvezeno:"Viri so osveženi.",mediaBrezVirov:"Dodaj prvi spletni vir; lokalne mape so vključene samodejno.",mediaVirElementov:"{n} vsebin"},
    en: { mediaOpis:"Movies, series and music from all your sources in one catalogue.",mediaOsvezi:"Refresh sources",mediaNastavitve:"Settings",mediaNastavitveNaslov:"Safeer Media Settings",mediaNastavitveOpis:"Import and export JSON libraries, enter custom code, and manage sources.",mediaUvozDatoteke:"Upload exported JSON file",mediaUvozDatotekeOpis:"Select a .json file of catalogue or sources previously exported or shared.",mediaIzberiDatoteko:"Choose .json file",mediaNobenaDatoteka:"No file selected",mediaUvoziDatoteko:"Import file",mediaVnosJson:"Add your own JSON code",mediaVnosJsonOpis:"Paste a JSON list of media, custom configuration, or streams.",mediaJsonImePh:"Collection or source name (optional)",mediaUvoziKodo:"Import JSON code",mediaVstaviPrimer:"Code Example",mediaPocisti:"Clear",mediaPrimerVstavljen:"JSON code example successfully inserted.",mediaIzvozJson:"Export catalogue to JSON",mediaIzvozJsonOpis:"Download the full collection of your sources and settings for backup or sharing.",mediaPrenesiIzvoz:"Download exported JSON",mediaUvozUspesen:"Successfully imported: {n} items into '{vir}'.",mediaUvozVirovUspesen:"Successfully updated/added sources: {n}.",mediaUvozNapaka:"Error importing JSON.",mediaVnesiteJson:"Please enter or select valid JSON code.",mediaPredvaja:"PLAYING IN SAFEER OS",mediaNapaka:"This stream cannot be played. Try another version.",mediaIsci:"Search movies, series and music",mediaVse:"All",mediaFilmi:"Movies",mediaSerije:"Series",mediaGlasba:"Music",mediaPrazno:"No results. Add a source or change the search.",mediaViri:"Your sources",mediaViriOpis:"Add a website, public API, RSS or M3U only once.",mediaVirIme:"Source name (optional)",mediaVirUrl:"https://example.com/catalogue.json",mediaDodaj:"Add source",mediaZadetkov:"{n} unique titles",mediaRazlicic:"{n} versions",mediaVirDodan:"Source added and catalogue merged.",mediaVirPodvojen:"This source has already been added.",mediaVirNapaka:"The source could not be read.",mediaOsvezeno:"Sources refreshed.",mediaBrezVirov:"Add your first web source; local folders are included automatically.",mediaVirElementov:"{n} titles"},
    de: { mediaOpis:"Filme, Serien und Musik aus allen Quellen in einem Katalog.",mediaOsvezi:"Quellen aktualisieren",mediaNastavitve:"Einstellungen",mediaNastavitveNaslov:"Safeer Media Einstellungen",mediaNastavitveOpis:"JSON-Bibliotheken importieren und exportieren sowie Quellen verwalten.",mediaUvozDatoteke:"Exportierte JSON-Datei hochladen",mediaUvozDatotekeOpis:"Wählen Sie eine .json-Datei aus, die Sie zuvor exportiert oder geteilt haben.",mediaIzberiDatoteko:".json-Datei auswählen",mediaNobenaDatoteka:"Keine Datei ausgewählt",mediaUvoziDatoteko:"Datei importieren",mediaVnosJson:"Eigenen JSON-Code eingeben",mediaVnosJsonOpis:"Fügen Sie eine JSON-Medienliste oder eigene Konfiguration ein.",mediaJsonImePh:"Name der Quelle (optional)",mediaUvoziKodo:"JSON-Code importieren",mediaVstaviPrimer:"Code-Beispiel",mediaPocisti:"Löschen",mediaPrimerVstavljen:"JSON-Codebeispiel erfolgreich eingefügt.",mediaIzvozJson:"Katalog in JSON exportieren",mediaIzvozJsonOpis:"Laden Sie die gesamte Quellensammlung für Backups oder Teilen herunter.",mediaPrenesiIzvoz:"Exportierte JSON herunterladen",mediaUvozUspesen:"Erfolgreich importiert: {n} Inhalte in '{vir}'.",mediaUvozVirovUspesen:"Erfolgreich aktualisiert/hinzugefügt: {n} Quellen.",mediaUvozNapaka:"Fehler beim Importieren von JSON.",mediaVnesiteJson:"Bitte geben Sie gültigen JSON-Code ein.",mediaPredvaja:"WIEDERGABE IN SAFEER OS",mediaNapaka:"Dieser Stream kann nicht abgespielt werden. Probiere eine andere Version.",mediaIsci:"Filme, Serien und Musik suchen",mediaVse:"Alle",mediaFilmi:"Filme",mediaSerije:"Serien",mediaGlasba:"Musik",mediaPrazno:"Keine Ergebnisse. Quelle hinzufügen oder Suche ändern.",mediaViri:"Deine Quellen",mediaViriOpis:"Website, öffentliche API, RSS oder M3U nur einmal hinzufügen.",mediaVirIme:"Name der Quelle (optional)",mediaVirUrl:"https://beispiel.de/katalog.json",mediaDodaj:"Quelle hinzufügen",mediaZadetkov:"{n} eindeutige Inhalte",mediaRazlicic:"{n} Versionen",mediaVirDodan:"Quelle hinzugefügt und Katalog zusammengeführt.",mediaVirPodvojen:"Diese Quelle wurde bereits hinzugefügt.",mediaVirNapaka:"Die Quelle konnte nicht gelesen werden.",mediaOsvezeno:"Quellen aktualisiert.",mediaBrezVirov:"Füge deine erste Webquelle hinzu; lokale Ordner sind automatisch enthalten.",mediaVirElementov:"{n} Inhalte"},
    es: { mediaOpis:"Películas, series y música de todas tus fuentes en un catálogo.",mediaOsvezi:"Actualizar fuentes",mediaNastavitve:"Ajustes",mediaNastavitveNaslov:"Ajustes de Safeer Media",mediaNastavitveOpis:"Importar y exportar bibliotecas JSON y gestionar fuentes.",mediaUvozDatoteke:"Subir archivo JSON exportado",mediaUvozDatotekeOpis:"Seleccione un archivo .json de catálogo o fuentes exportado previamente.",mediaIzberiDatoteko:"Seleccionar archivo .json",mediaNobenaDatoteka:"Ningún archivo seleccionado",mediaUvoziDatoteko:"Importar archivo",mediaVnosJson:"Añade tu propio código JSON",mediaVnosJsonOpis:"Pega una lista JSON de medios, configuración personalizada o flujos.",mediaJsonImePh:"Nombre de la fuente (opcional)",mediaUvoziKodo:"Importar código JSON",mediaVstaviPrimer:"Ejemplo de código",mediaPocisti:"Limpiar",mediaPrimerVstavljen:"Ejemplo de código JSON insertado con éxito.",mediaIzvozJson:"Exportar catálogo a JSON",mediaIzvozJsonOpis:"Descarga la colección completa de tus fuentes y ajustes.",mediaPrenesiIzvoz:"Descargar JSON exportado",mediaUvozUspesen:"Importado con éxito: {n} contenidos en '{vir}'.",mediaUvozVirovUspesen:"Fuentes actualizadas/añadidas con éxito: {n}.",mediaUvozNapaka:"Error al importar JSON.",mediaVnesiteJson:"Por favor introduce un código JSON válido.",mediaPredvaja:"REPRODUCIENDO EN SAFEER OS",mediaNapaka:"No se puede reproducir este flujo. Prueba otra versión.",mediaIsci:"Buscar películas, series y música",mediaVse:"Todo",mediaFilmi:"Películas",mediaSerije:"Series",mediaGlasba:"Música",mediaPrazno:"No hay resultados. Añade una fuente o cambia la búsqueda.",mediaViri:"Tus fuentes",mediaViriOpis:"Añade una web, API pública, RSS o M3U una sola vez.",mediaVirIme:"Nombre de la fuente (opcional)",mediaVirUrl:"https://ejemplo.es/catalogo.json",mediaDodaj:"Añadir fuente",mediaZadetkov:"{n} contenidos únicos",mediaRazlicic:"{n} versiones",mediaVirDodan:"Fuente añadida y catálogo combinado.",mediaVirPodvojen:"Esta fuente ya está añadida.",mediaVirNapaka:"No se pudo leer la fuente.",mediaOsvezeno:"Fuentes actualizadas.",mediaBrezVirov:"Añade tu primera fuente web; las carpetas locales ya están incluidas.",mediaVirElementov:"{n} contenidos"},
    fr: { mediaOpis:"Films, séries et musique de toutes vos sources dans un catalogue.",mediaOsvezi:"Actualiser les sources",mediaNastavitve:"Paramètres",mediaNastavitveNaslov:"Paramètres Safeer Media",mediaNastavitveOpis:"Importer et exporter des bibliothèques JSON et gérer les sources.",mediaUvozDatoteke:"Téléverser le fichier JSON exporté",mediaUvozDatotekeOpis:"Sélectionnez un fichier .json de catalogue ou de sources précédemment exporté.",mediaIzberiDatoteko:"Choisir un fichier .json",mediaNobenaDatoteka:"Aucun fichier sélectionné",mediaUvoziDatoteko:"Importer le fichier",mediaVnosJson:"Ajoutez votre propre code JSON",mediaVnosJsonOpis:"Collez une liste JSON de médias, une configuration personnalisée ou des flux.",mediaJsonImePh:"Nom de la source (facultatif)",mediaUvoziKodo:"Importer le code JSON",mediaVstaviPrimer:"Exemple de code",mediaPocisti:"Effacer",mediaPrimerVstavljen:"Exemple de code JSON inséré avec succès.",mediaIzvozJson:"Exporter le catalogue en JSON",mediaIzvozJsonOpis:"Téléchargez la collection complète de vos sources et paramètres.",mediaPrenesiIzvoz:"Télécharger le JSON exporté",mediaUvozUspesen:"Importation réussie : {n} éléments dans '{vir}'.",mediaUvozVirovUspesen:"Sources mises à jour/ajoutées : {n}.",mediaUvozNapaka:"Erreur lors de l'importation du JSON.",mediaVnesiteJson:"Veuillez entrer ou sélectionner un code JSON valide.",mediaPredvaja:"LECTURE DANS SAFEER OS",mediaNapaka:"Ce flux ne peut pas être lu. Essayez une autre version.",mediaIsci:"Rechercher films, séries et musique",mediaVse:"Tout",mediaFilmi:"Films",mediaSerije:"Séries",mediaGlasba:"Musique",mediaPrazno:"Aucun résultat. Ajoutez une source ou modifiez la recherche.",mediaViri:"Vos sources",mediaViriOpis:"Ajoutez un site, une API publique, un RSS ou M3U une seule fois.",mediaVirIme:"Nom de la source (facultatif)",mediaVirUrl:"https://exemple.fr/catalogue.json",mediaDodaj:"Ajouter la source",mediaZadetkov:"{n} contenus uniques",mediaRazlicic:"{n} versions",mediaVirDodan:"Source ajoutée et catalogue fusionné.",mediaVirPodvojen:"Cette source est déjà ajoutée.",mediaVirNapaka:"La source n’a pas pu être lue.",mediaOsvezeno:"Sources actualisées.",mediaBrezVirov:"Ajoutez votre première source web ; les dossiers locaux sont inclus.",mediaVirElementov:"{n} contenus"},
    it: { mediaOpis:"Film, serie e musica da tutte le fonti in un solo catalogo.",mediaOsvezi:"Aggiorna fonti",mediaNastavitve:"Impostazioni",mediaNastavitveNaslov:"Impostazioni Safeer Media",mediaNastavitveOpis:"Importa ed esporta librerie JSON e gestisci le fonti.",mediaUvozDatoteke:"Carica file JSON esportato",mediaUvozDatotekeOpis:"Seleziona un file .json di catalogo o fonti precedentemente esportato.",mediaIzberiDatoteko:"Scegli file .json",mediaNobenaDatoteka:"Nessun file selezionato",mediaUvoziDatoteko:"Importa file",mediaVnosJson:"Aggiungi il tuo codice JSON",mediaVnosJsonOpis:"Incolla un elenco JSON di contenuti multimediali, configurazioni o flussi.",mediaJsonImePh:"Nome fonte (facoltativo)",mediaUvoziKodo:"Importa codice JSON",mediaVstaviPrimer:"Esempio di codice",mediaPocisti:"Cancella",mediaPrimerVstavljen:"Esempio di codice JSON inserito con successo.",mediaIzvozJson:"Esporta catalogo in JSON",mediaIzvozJsonOpis:"Scarica l'intera raccolta delle tue fonti e impostazioni.",mediaPrenesiIzvoz:"Scarica JSON esportato",mediaUvozUspesen:"Importato con successo: {n} contenuti in '{vir}'.",mediaUvozVirovUspesen:"Fonti aggiornate/aggiunte con successo: {n}.",mediaUvozNapaka:"Errore durante l'importazione di JSON.",mediaVnesiteJson:"Inserisci o seleziona un codice JSON valido.",mediaPredvaja:"RIPRODUZIONE IN SAFEER OS",mediaNapaka:"Impossibile riprodurre questo flusso. Prova un’altra versione.",mediaIsci:"Cerca film, serie e musica",mediaVse:"Tutto",mediaFilmi:"Film",mediaSerije:"Serie",mediaGlasba:"Musica",mediaPrazno:"Nessun risultato. Aggiungi una fonte o cambia la ricerca.",mediaViri:"Le tue fonti",mediaViriOpis:"Aggiungi sito, API pubblica, RSS o M3U una sola volta.",mediaVirIme:"Nome fonte (facoltativo)",mediaVirUrl:"https://esempio.it/catalogo.json",mediaDodaj:"Aggiungi fonte",mediaZadetkov:"{n} contenuti unici",mediaRazlicic:"{n} versioni",mediaVirDodan:"Fonte aggiunta e catalogo unificato.",mediaVirPodvojen:"Questa fonte è già stata aggiunta.",mediaVirNapaka:"Impossibile leggere la fonte.",mediaOsvezeno:"Fonti aggiornate.",mediaBrezVirov:"Aggiungi la prima fonte web; le cartelle locali sono già incluse.",mediaVirElementov:"{n} contenuti"}
  };
  Object.keys(BESEDILA_MEDIA).forEach(function (koda) {
    if (BESEDILA_OS[koda]) Object.assign(BESEDILA_OS[koda], BESEDILA_MEDIA[koda]);
  });
  function prilagodiPlatformo(platforma) {
    if (platforma !== "windows") return;
    Object.keys(BESEDILA_WINDOWS).forEach(function (koda) {
      if (BESEDILA_OS[koda]) Object.assign(BESEDILA_OS[koda], BESEDILA_WINDOWS[koda]);
    });
  }
  function prevedi() {
    document.documentElement.lang = jezik;
    document.querySelectorAll("[data-t]").forEach(function (el) { el.textContent = t(el.getAttribute("data-t")); });
    document.querySelectorAll("[data-ph]").forEach(function (el) { el.placeholder = t(el.getAttribute("data-ph")); });
    document.querySelectorAll("[data-naslov]").forEach(function (el) { el.title = t(el.getAttribute("data-naslov")); });
    document.querySelectorAll("svg[data-ikona]").forEach(function (el) {
      el.setAttribute("viewBox", "0 0 24 24");
      el.innerHTML = '<path d="' + (IK[el.getAttribute("data-ikona")] || "") + '"/>';
    });
  }

  function $(id) { return document.getElementById(id); }
  function on(id, dogodek, poslusaj) {
    var e = typeof id === "string" ? $(id) : id;
    if (e && e.addEventListener) e.addEventListener(dogodek, poslusaj);
  }
  function el(oznaka, razred, html) {
    var e = document.createElement(oznaka);
    if (razred) e.className = razred;
    if (html != null) e.innerHTML = html;
    return e;
  }
  function ubezi(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (z) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[z];
    });
  }
  var obvestiloCas = 0;
  function obvesti(besedilo) {
    var o = $("obvestilo");
    o.textContent = besedilo;
    o.classList.add("viden");
    clearTimeout(obvestiloCas);
    obvestiloCas = setTimeout(function () { o.classList.remove("viden"); }, 2600);
  }
  // Barvna ploscica s prvo crko (program brez ikone, spletna aplikacija).
  function barva(ime) {
    var h = 0;
    for (var i = 0; i < ime.length; i++) h = (h * 31 + ime.charCodeAt(i)) >>> 0;
    var barve = ["#1f7a5c", "#2d5f9a", "#8a3d7a", "#a4492f", "#5a4aa0", "#2f7f8a", "#8a6d1f", "#3b6e2f"];
    return barve[h % barve.length];
  }
  function crka(ime) {
    var c = el("div", "crka", ubezi((ime || "?").trim().charAt(0).toUpperCase()));
    c.style.background = barva(ime || "?");
    return c;
  }
  function slikaAliCrka(pot, ime) {
    if (!pot || pot === "znak.svg") return crka(ime);
    var img = document.createElement("img");
    img.alt = "";
    img.src = pot;
    img.onerror = function () { img.replaceWith(crka(ime)); };
    return img;
  }

  // ------------------------------------------------------------------ stanje
  var S = {
    zacetek: null, programi: [], skupina: "vse", razdelek: "domov", pot: "", stanje: null,
    // Multi-host: programi drugih naprav v Safeer Linku (id naprave -> seznam), izbrana naprava ("" = ta racunalnik).
    naprave: [], programiNaprav: {}, nalagam: {}, naprava: "",
    // Multi-host: datoteke drugih naprav v Safeer Linku
    napraveDatoteke: [], izbranaNapravaDatoteke: "", daljinskaPot: [],
    daljinskiKoreni: {}, daljinskiServer: {},
    povezava: { stanje: "nov", control: true }, spletne: null, nedavne: [], nedavneApp: [], brskalnikNastavitve: null
  };
  var PRIVZETE_SPLETNE = [
    { ime: "YouTube", url: "https://www.youtube.com" },
    { ime: "RTV 365", url: "https://365.rtvslo.si" },
    { ime: "Gmail", url: "https://mail.google.com" },
    { ime: "Wikipedia", url: "https://www.wikipedia.org" }
  ];

  // ------------------------------------------------------------------ navigacija
  function pojdi(razdelek) {
    S.razdelek = razdelek;
    document.querySelectorAll("#meni button").forEach(function (b) {
      b.classList.toggle("izbran", b.getAttribute("data-razdelek") === razdelek);
    });
    document.querySelectorAll(".razdelek").forEach(function (r) { r.classList.toggle("viden", r.id === "r-" + razdelek); });
    $("vsebina").scrollTop = 0;
    if (razdelek === "datoteke") {
      nalozNapraveSDatoteki();
      if (!S.izbranaNapravaDatoteke && !S.pot) odpriNedavne();
    }
    if (razdelek === "naprave") { osveziPovezavo(); napraveZanka(); }
    if (razdelek === "nastavitve") {
      narisiNastavitve(); nalozScit(); scitZanka(); naloziMedia();
      naloziMediaWatchSettings();
      var mediaPlosca = $("mediaNastavitvePlosca"), mediaMesto = $("mediaNastavitveMesto");
      if (mediaPlosca && mediaMesto && mediaPlosca.parentNode !== mediaMesto) mediaMesto.appendChild(mediaPlosca);
      if (mediaPlosca) mediaPlosca.hidden = false;
    }
    if (razdelek === "programi") nalozNaprave();
    if (razdelek === "omrezje") nalozOmrezje(false);
    if (razdelek === "zvok") { nalozZvok(); zvokZanka(); if (!jblStanje) nalozJbl(); }
    if (razdelek === "media") naloziMedia();
    if (razdelek === "splet") narisiSpletnoZacetno();
  }
  function odpriSpletnoIskanje(niz) {
    pojdi("splet");
    klic("iskanjeSplet", [String(niz || "").trim()]);
  }
  function otvoriSpletnoStran(url, ime) {
    zabeleziNedavno({ vrsta: "stran", url: url, ime: ime });
    klic("splet", [url]).then(function (r) {
      // Storitve z DRM (Netflix ...) odpre Edge, ker vgrajeni pogon nima Widevine.
      if (r && r.zunanje) { obvesti((ime || imeIzNaslova(url)) + " se odpira v " + r.brskalnik + " (zaščitena vsebina, DRM)."); return; }
      pojdi("splet");
    });
  }

  // ------------------------------------------------------------------ nedavne aplikacije
  // Programi (tudi na drugih napravah), spletne aplikacije in spletne strani, ki jih je
  // uporabnik nazadnje odprl. Najnovejsi prvi, brez podvojitev, shranjeno v os.json.
  function imeIzNaslova(url) {
    try { return new URL(url).hostname.replace(/^www\./, ""); } catch (e) { return String(url || ""); }
  }
  function zabeleziNedavno(v) {
    if (!v) return;
    var vnos = { vrsta: v.vrsta, cas: Math.floor(Date.now() / 1000) };
    if (v.vrsta === "program") {
      vnos.id = v.id; vnos.ime = v.ime; vnos.ikona = v.ikona || "";
      if (v.naprava) { vnos.naprava = v.naprava; vnos.ime_naprave = v.ime_naprave || ""; }
      vnos.kljuc = "p:" + (v.naprava || "") + ":" + v.id;
    } else {
      var url = String(v.url || "");
      if (!/^https?:\/\//i.test(url)) return;
      var aplikacija = spletne().find(function (a) { return imeIzNaslova(a.url) === imeIzNaslova(url); });
      vnos.vrsta = aplikacija ? "spletna" : "stran";
      vnos.url = url;
      vnos.ime = v.ime || (aplikacija && aplikacija.ime) || imeIzNaslova(url);
      vnos.kljuc = "s:" + (aplikacija ? imeIzNaslova(url) : url.replace(/[#?].*$/, ""));
    }
    if (!vnos.ime) return;
    var seznam = (S.nedavneApp || []).filter(function (x) { return x.kljuc !== vnos.kljuc; });
    seznam.unshift(vnos);
    S.nedavneApp = seznam.slice(0, 20);
    klic("shraniNedavneApp", [S.nedavneApp]).catch(function () {});
    narisiDomaceNedavne();
  }
  function kdajPrej(cas) {
    var s_ = Math.max(0, Math.floor(Date.now() / 1000 - (cas || 0)));
    if (s_ < 60) return "pravkar";
    if (s_ < 3600) return "pred " + Math.floor(s_ / 60) + " min";
    if (s_ < 86400) return "pred " + Math.floor(s_ / 3600) + " h";
    return "pred " + Math.floor(s_ / 86400) + " d";
  }
  function narisiDomaceNedavne() {
    var cilj = $("domaceNedavne");
    if (!cilj) return;
    cilj.innerHTML = "";
    var seznam = S.nedavneApp || [];
    if (!seznam.length) {
      cilj.appendChild(el("p", "drobno", ubezi("Tu se prikažejo programi, spletne aplikacije in strani, ki jih odpreš.")));
      return;
    }
    var prostora = Math.max(3, Math.floor(((cilj.clientHeight || 240) + 8) / 52));
    seznam.slice(0, prostora).forEach(function (v) {
      var b = el("button", "nedavna-vrstica");
      b.appendChild(v.vrsta === "program" ? slikaAliCrka(v.ikona, v.ime) : crka(v.ime));
      var opis = v.vrsta === "program" ? (v.ime_naprave ? "Program · " + v.ime_naprave : "Program")
               : v.vrsta === "spletna" ? "Spletna aplikacija" : imeIzNaslova(v.url);
      b.appendChild(el("span", "besedilo", "<b>" + ubezi(v.ime) + "</b><small>" + ubezi(opis + " · " + kdajPrej(v.cas)) + "</small>"));
      var x = el("span", "odstrani", svg("x"));
      x.title = t("odstrani");
      x.addEventListener("click", function (e) {
        e.stopPropagation();
        S.nedavneApp = (S.nedavneApp || []).filter(function (y) { return y.kljuc !== v.kljuc; });
        klic("shraniNedavneApp", [S.nedavneApp]).catch(function () {});
        narisiDomaceNedavne();
      });
      b.appendChild(x);
      b.addEventListener("click", function () {
        if (v.vrsta === "program") {
          var p = (S.programi || []).find(function (q) { return q.id === v.id && (q.naprava || "") === (v.naprava || ""); });
          zazeni(p || { id: v.id, ime: v.ime, ikona: v.ikona, naprava: v.naprava });
        } else {
          otvoriSpletnoStran(v.url, v.ime);
        }
      });
      cilj.appendChild(b);
    });
  }
  window.safeerOsPojdi = function (kam) {
    kam = String(kam || "");
    if (kam.indexOf("iskanje:") === 0) {
      pojdi("domov");
      $("iskanje").value = kam.slice(8);
      $("iskanje").focus();
      isci();
      return;
    }
    if (kam.indexOf("zazeni:") === 0) {
      var p = S.programi.find(function (x) { return x.id === kam.slice(7); });
      if (p) zazeni(p);
      return;
    }
    if (kam === "hitro") { odpriHitro(); return; }
    if (kam === "napajanje") { odpriNapajanje(); return; }
    if (kam === "mint") { odpriMint(); return; }
    pojdi(kam);
  };

  // ------------------------------------------------------------------ ura in pozdrav
  function osveziUro() {
    var zdaj = new Date();
    var lok = LOKALE[jezik] || "en-GB";
    if ($("ura")) $("ura").textContent = zdaj.toLocaleTimeString(lok, { hour: "2-digit", minute: "2-digit" });
    if ($("datum")) $("datum").textContent = zdaj.toLocaleDateString(lok, { weekday: "short", day: "numeric", month: "short" });
    var h = zdaj.getHours();
    var ime = S.zacetek ? String(S.zacetek.ime || "").split(" ")[0] : "";
    var kljuc = h < 11 ? "jutro" : (h < 18 ? "dan" : "vecer");
    var pozdrav = t(kljuc, { ime: ime });
    if (!ime) pozdrav = pozdrav.replace(/,\s*!/, "!");
    if ($("pozdrav")) $("pozdrav").textContent = pozdrav;
  }

  // ------------------------------------------------------------------ programi
  function nalozPrograme() {
    return klic("programi").then(function (seznam) {
      S.programi = seznam || [];
      narisiPrograme();
      narisiDomov();
    }, function () {});
  }
  function zazeni(p) {
    if (p.naprava) {
      var n = S.naprave.find(function (x) { return x.id === p.naprava; }) || { ime: "" };
      obvesti(t("zaganjamNa", { ime: p.ime, naprava: n.ime }));
      klic("zazeniNaNapravi", [p.naprava, p.id]).then(function (r) {
        var ok = r === true || !!(r && r.ok);
        if (!ok) {
          // Sporocilo naprave (npr. "dovoli Prikaz cez druge aplikacije") je koristnejse od splosnega.
          obvesti(r && r.message ? r.message : t("niUspelo"));
          return;
        }
        zabeleziNedavno({ vrsta: "program", id: p.id, ime: p.ime, ikona: p.ikona, naprava: p.naprava, ime_naprave: n.ime });
      },
                                                        function () { obvesti(t("niUspelo")); });
      return;
    }
    obvesti(t("odpiram", { ime: p.ime }));
    klic("zazeni", [p.id]).then(function (ok) {
      if (!ok) { obvesti(t("niUspelo")); return; }
      zabeleziNedavno({ vrsta: "program", id: p.id, ime: p.ime, ikona: p.ikona });
      p.uporaba = (p.uporaba || 0) + 1;
      p.zadnjic = Date.now() / 1000;
      setTimeout(narisiDomov, 400);
    }, function () { obvesti(t("niUspelo")); });
  }
  // Program naprave v oknu na tem racunalniku: naprava vprasa za deljenje zaslona, nato ga upravljas z misko.
  function odpriTukaj(p) {
    var n = S.naprave.find(function (x) { return x.id === p.naprava; }) || { ime: "" };
    obvesti(t("potrdiNaNapravi", { ime: p.ime, naprava: n.ime }));
    klic("odpriTukaj", [p.naprava, p.id]).then(function (r) {
      if (!r || !r.ok) obvesti(t("niUspelo"));
      else if (!r.tu) obvesti(t("napravaNePretaka", { ime: p.ime, naprava: n.ime }));
    }, function () { obvesti(t("niUspelo")); });
  }
  function ploscicaPrograma(p, zPripenjanjem, naDomacem) {
    var b = el("button", "ploscica");
    b.title = p.opis || p.ime;
    b.appendChild(slikaAliCrka(p.ikona, p.ime));
    b.appendChild(el("span", "ime", ubezi(p.ime)));
    b.addEventListener("click", function () { zazeni(p); });
    if (p.naprava) {
      var tu = el("span", "pripni", svg("namizje"));
      tu.title = t("odpriTukaj");
      tu.addEventListener("click", function (e) { e.stopPropagation(); odpriTukaj(p); });
      b.appendChild(tu);
    }
    if (zPripenjanjem) {
      var pr = el("span", "pripni" + (p.pripet ? " pripet" : "") + (naDomacem ? " levo" : ""), svg("zvezda"));
      pr.title = p.pripet ? t("odpni") : t("pripni");
      pr.addEventListener("click", function (e) {
        e.stopPropagation();
        p.pripet = !p.pripet;
        if (p.pripet) p.skrit = false;
        klic("pripni", [p.id, p.pripet]).then(function () { narisiPrograme(); narisiDomov(); });
      });
      b.appendChild(pr);
    }
    if (naDomacem) {
      // Vsaka ploscica na domacem zaslonu gre stran: pripeta se odpne, pogosta ali privzeta se skrije.
      var x = el("span", "pripni odstrani", svg("x"));
      x.title = t("odstraniZDomacega");
      x.addEventListener("click", function (e) {
        e.stopPropagation();
        p.pripet = false; p.skrit = true;
        klic("pripni", [p.id, false]).then(function () { return klic("skrijDomov", [p.id, true]); })
          .then(function () { narisiPrograme(); narisiDomov(); });
      });
      b.appendChild(x);
    }
    return b;
  }
  var SKUPINE = ["splet", "pisarna", "predstavnost", "igre", "ucenje", "programiranje", "orodja", "sistem", "drugo"];
  // ---- multi-host: naprave v Linku in njihovi programi
  function programiIzbrane() {
    return S.naprava ? (S.programiNaprav[S.naprava] || []) : S.programi;
  }
  function vsiProgramiNaprav() {
    var vsi = [];
    Object.keys(S.programiNaprav).forEach(function (id) { vsi = vsi.concat(S.programiNaprav[id]); });
    return vsi;
  }
  function nalozNaprave() {
    if (S.povezava.stanje !== "povezan") { S.naprave = []; narisiPrograme(); return; }
    klic("napraveSProgrami").then(function (n) {
      S.naprave = n || [];
      if (S.naprava && !S.naprave.some(function (x) { return x.id === S.naprava; })) S.naprava = "";
      narisiPrograme();
      S.naprave.forEach(function (x) { if (!S.programiNaprav[x.id]) nalozProgrameNaprave(x.id); });
    }, function () {});
  }
  function nalozProgrameNaprave(id) {
    if (S.nalagam[id]) return;
    S.nalagam[id] = true;
    klic("programiNaprave", [id]).then(function (r) {
      S.nalagam[id] = false;
      S.programiNaprav[id] = (r && r.programi) || [];
      if (r && !r.ok) S.programiNaprav[id].napaka = r.koda || "napaka";
      else if (r && r.deli === false) S.programiNaprav[id].napaka = "ne_deli";
      narisiPrograme();
    }, function () { S.nalagam[id] = false; narisiPrograme(); });
  }
  function ikonaNaprave(n) {
    return n.platforma === "tv" ? "zaslon" : (n.platforma === "linux" || n.platforma === "windows" ? "namizje" : "naprave");
  }
  function narisiPrograme() {
    var fn = $("filtriNaprav");
    fn.innerHTML = "";
    fn.hidden = !S.naprave.length;
    if (S.naprave.length) {
      var ta = el("button", S.naprava === "" ? "izbran" : "", svg("namizje") + ubezi(t("taRacunalnik")) + "<span>" + S.programi.length + "</span>");
      ta.addEventListener("click", function () { S.naprava = ""; S.skupina = "vse"; narisiPrograme(); });
      fn.appendChild(ta);
      S.naprave.forEach(function (n) {
        var seznam = S.programiNaprav[n.id];
        var st = seznam ? seznam.length : (S.nalagam[n.id] ? "…" : "");
        var b = el("button", S.naprava === n.id ? "izbran" : "", svg(ikonaNaprave(n)) + ubezi(n.ime) + (st !== "" ? "<span>" + st + "</span>" : ""));
        b.addEventListener("click", function () {
          S.naprava = n.id; S.skupina = "vse"; narisiPrograme();
          if (!S.programiNaprav[n.id]) nalozProgrameNaprave(n.id);
        });
        fn.appendChild(b);
      });
    }
    var programi = programiIzbrane();
    var stevci = {};
    programi.forEach(function (p) { stevci[p.skupina] = (stevci[p.skupina] || 0) + 1; });
    var izbranaNaprava = S.naprave.find(function (x) { return x.id === S.naprava; });
    if ($("programiPod")) {
      $("programiPod").textContent = S.naprava
        ? t("programiNaprave", { n: programi.length, naprava: izbranaNaprava ? izbranaNaprava.ime : "" })
        : (S.naprave.length ? t("programiPodNaprave", { n: S.programi.length, k: S.naprave.length }) : t("programiPod", { n: S.programi.length }));
    }
    var filtri = $("filtri");
    if (filtri) {
      filtri.innerHTML = "";
      ["vse"].concat(SKUPINE).forEach(function (s) {
        if (s !== "vse" && !stevci[s]) return;
        var b = el("button", s === S.skupina ? "izbran" : "",
                   ubezi(t("sk_" + s)) + "<span>" + (s === "vse" ? programi.length : stevci[s]) + "</span>");
        b.addEventListener("click", function () { S.skupina = s; narisiPrograme(); });
        filtri.appendChild(b);
      });
    }
    var mreza = $("vsiProgrami");
    if (!mreza) return;
    mreza.innerHTML = "";
    if (S.naprava) {
      var seznamN = S.programiNaprav[S.naprava];
      if (!seznamN) { mreza.appendChild(el("div", "programi-obvestilo", ubezi(t("nalagamPrograme")))); return; }
      if (seznamN.napaka) {
        mreza.appendChild(el("div", "programi-obvestilo", ubezi(t(seznamN.napaka === "ne_deli" ? "napravaNeDeli" : "napravaNiOdgovorila"))));
        if (seznamN.napaka !== "ne_deli") return;
      }
    }
    programi.filter(function (p) { return S.skupina === "vse" || p.skupina === S.skupina; })
      .forEach(function (p) { mreza.appendChild(ploscicaPrograma(p, !p.naprava)); });
  }
  // Programi, ki jih ima vsak Mint, kot zacetni izbor, dokler uporabnik se nicesar ne odpira.
  var PRIVZETI = ["safeer-browser.desktop", "firefox.desktop", "nemo.desktop", "org.gnome.Terminal.desktop",
    "libreoffice-writer.desktop", "xed.desktop", "mintinstall.desktop", "org.gnome.Calculator.desktop",
    "celluloid.desktop", "io.github.celluloid_player.Celluloid.desktop", "rhythmbox.desktop",
    "org.gnome.Rhythmbox3.desktop", "thunderbird.desktop", "xviewer.desktop", "mintupdate.desktop"];
  function domaciProgrami() {
    var izbrani = S.programi.filter(function (p) { return p.pripet; });
    var uporabljeni = S.programi.filter(function (p) { return !p.pripet && !p.skrit && p.uporaba > 0; })
      .sort(function (a, b) { return (b.uporaba - a.uporaba) || (b.zadnjic - a.zadnjic); });
    izbrani = izbrani.concat(uporabljeni);
    PRIVZETI.forEach(function (id) {
      var p = S.programi.find(function (x) { return x.id === id; });
      if (p && !p.skrit && izbrani.indexOf(p) < 0) izbrani.push(p);
    });
    if (izbrani.length < 8 && S.programi.length > 0) {
      S.programi.forEach(function (p) {
        if (!p.skrit && izbrani.indexOf(p) < 0 && izbrani.length < 11) {
          izbrani.push(p);
        }
      });
    }
    return izbrani.slice(0, 11);
  }
  // Ena vrsta ploscic kot na televizorju: programi (pripeti, pogosti), nato spletne aplikacije, na koncu »Dodaj«.
  // Koliko jih gre v vrsto, je odvisno od sirine zaslona.
  function ploscicaSpletne(a, i) {
    var b = el("button", "ploscica");
    b.title = a.url;
    b.appendChild(crka(a.ime));
    b.appendChild(el("span", "ime", ubezi(a.ime)));
    var x = el("span", "pripni odstrani", svg("x"));
    x.title = t("odstrani");
    x.addEventListener("click", function (e) {
      e.stopPropagation();
      var nove = spletne().slice();
      nove.splice(i, 1);
      shraniSpletne(nove);
    });
    b.appendChild(x);
    b.addEventListener("click", function () { obvesti(t("odpiram", { ime: a.ime })); otvoriSpletnoStran(a.url, a.ime); });
    return b;
  }
  // Kartica "Spletne aplikacije" na domaci strani. Brez drsnika: pokaze toliko
  // ploscic, kolikor jih gre v 2 vrsti (3 na visokem zaslonu); ce jih je vec,
  // je zadnja ploscica "Vec aplikacij (+N)", ki odpre pregled vseh. Vrstni red
  // si uporabnik nastavi sam (vlecenje ali puscici) - prve so vidne tukaj.
  function premakniSpletno(od, na) {
    var seznam = spletne().slice();
    if (od === na || od < 0 || na < 0 || od >= seznam.length || na >= seznam.length) return;
    var a = seznam.splice(od, 1)[0];
    seznam.splice(na, 0, a);
    shraniSpletne(seznam);
    if ($("slojVecApp") && $("slojVecApp").classList.contains("viden")) narisiVseSpletne();
  }
  function urejljivaPloscica(a, i, vPregledu) {
    var b = ploscicaSpletne(a, i);
    b.draggable = true;
    b.dataset.indeks = i;
    b.addEventListener("dragstart", function (e) {
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", String(i));
      b.classList.add("vlecem");
    });
    b.addEventListener("dragend", function () { b.classList.remove("vlecem"); });
    b.addEventListener("dragover", function (e) { e.preventDefault(); b.classList.add("cilj-spusta"); });
    b.addEventListener("dragleave", function () { b.classList.remove("cilj-spusta"); });
    b.addEventListener("drop", function (e) {
      e.preventDefault(); b.classList.remove("cilj-spusta");
      var od = parseInt(e.dataTransfer.getData("text/plain"), 10);
      if (!isNaN(od)) premakniSpletno(od, i);
    });
    // Puscici za premik (miska, tipkovnica, daljinec).
    var pus = el("span", "premik");
    [["nazaj", -1, "Premakni levo"], ["desno", 1, "Premakni desno"]].forEach(function (d) {
      var g = el("span", "premik-gumb", svg(d[0]));
      g.title = d[2]; g.setAttribute("role", "button"); g.tabIndex = 0;
      var akcija = function (e) { e.stopPropagation(); e.preventDefault(); premakniSpletno(i, i + d[1]); };
      g.addEventListener("click", akcija);
      g.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") akcija(e); });
      pus.appendChild(g);
    });
    b.appendChild(pus);
    b.addEventListener("keydown", function (e) {
      if (!e.altKey) return;
      if (e.key === "ArrowLeft") { e.preventDefault(); premakniSpletno(i, i - 1); }
      if (e.key === "ArrowRight") { e.preventDefault(); premakniSpletno(i, i + 1); }
    });
    if (vPregledu) b.addEventListener("click", function () { zapriSloje(); });
    return b;
  }
  function narisiDomaceSpletne() {
    var cilj = $("domaceSpletneApp");
    if (!cilj) return;
    cilj.innerHTML = "";
    var seznam = spletne();
    if (!seznam.length) {
      cilj.appendChild(el("p", "drobno", ubezi("Še ni spletnih aplikacij. Klikni »+ Dodaj« in vpiši naslov strani.")));
      return;
    }
    var sirina = cilj.clientWidth || 600, razmik = 12, najmanj = 112;
    var stolpcev = Math.max(2, Math.floor((sirina + razmik) / (najmanj + razmik)));
    var vrstic = window.innerHeight >= 1000 ? 3 : 2;
    var mest = stolpcev * vrstic;
    cilj.style.gridTemplateColumns = "repeat(" + stolpcev + ", minmax(0, 1fr))";
    var prikazi = seznam.length > mest ? mest - 1 : seznam.length;
    seznam.slice(0, prikazi).forEach(function (a, i) { cilj.appendChild(urejljivaPloscica(a, i, false)); });
    if (seznam.length > prikazi) {
      var vec = el("button", "ploscica vec-aplikacij", svg("programi") + '<span class="ime">Več aplikacij</span><span class="vec-stevilo">+' + (seznam.length - prikazi) + "</span>");
      vec.addEventListener("click", odpriVecSpletnih);
      cilj.appendChild(vec);
    }
  }
  function narisiVseSpletne() {
    var cilj = $("vseSpletneApp");
    if (!cilj) return;
    cilj.innerHTML = "";
    spletne().forEach(function (a, i) { cilj.appendChild(urejljivaPloscica(a, i, true)); });
  }
  function odpriVecSpletnih() {
    narisiVseSpletne();
    $("slojVecApp").classList.add("viden");
  }
  function narisiDomov() {
    narisiDomaceSpletne();
    narisiDomaceNedavne();
    var vrsta = $("domaciProgrami");
    if (!vrsta) return;
    var sirina = vrsta.clientWidth || 1000;
    var mest = Math.max(4, Math.floor((sirina + 12) / (116 + 12)));
    var programi = domaciProgrami(), splet = spletne();
    var nSpletnih = Math.min(splet.length, Math.max(1, Math.floor((mest - 1) / 3)));
    var nProgramov = Math.min(programi.length, mest - 1 - nSpletnih);
    nSpletnih = Math.min(splet.length, mest - 1 - nProgramov);
    vrsta.innerHTML = "";
    programi.slice(0, nProgramov).forEach(function (p) { vrsta.appendChild(ploscicaPrograma(p, true, true)); });
    splet.slice(0, nSpletnih).forEach(function (a, i) { vrsta.appendChild(ploscicaSpletne(a, i)); });
    var dodaj = el("button", "ploscica dodaj", svg("plus") + '<span class="ime">' + ubezi(t("dodaj")) + "</span>");
    dodaj.addEventListener("click", odpriDodaj);
    vrsta.appendChild(dodaj);
    narisiHitriDostop();
  }
  function narisiHitriDostop() {
    var cilj = $("hitriDostop");
    if (!cilj) return;
    cilj.innerHTML = "";
    var r = (S.zacetek && S.zacetek.razpolozljivo) || { orodja: [] };
    var elementi = [
      ["splet", t("splet"), function () { $("kBrskalnik").click(); }],
      ["mapa", t("datoteke"), function () { pojdi("datoteke"); }],
      ["drsniki", t("nastavitve"), function () { pojdi("nastavitve"); }]
    ];
    if (r.orodja.indexOf("posodobitve") >= 0) {
      elementi.push(["ponovno", t("o_posodobitve"), function () { odpriNastavitev({ modul: "posodobitve", ime: t("o_posodobitve") }); }]);
    }
    elementi.forEach(function (e) {
      var b = el("button", "hiter", svg(e[0]) + "<span>" + ubezi(e[1]) + "</span>");
      b.addEventListener("click", e[2]);
      cilj.appendChild(b);
    });
  }
  var zamikVelikosti = 0;
  window.addEventListener("resize", function () { clearTimeout(zamikVelikosti); zamikVelikosti = setTimeout(narisiDomov, 150); });

  // ------------------------------------------------------------------ spletne aplikacije
  function spletne() { return Array.isArray(S.spletne) ? S.spletne : PRIVZETE_SPLETNE; }
  function narisiSpletnoZacetno() {
    var cilj = $("spletneAplikacije");
    if (!cilj) return;
    cilj.innerHTML = "";
    spletne().forEach(function (app) {
      if (!app || !app.url) return;
      var gumb = el("button", "spletna-bliznjica");
      gumb.type = "button";
      gumb.title = app.url;
      var ime = String(app.ime || app.url).trim();
      gumb.appendChild(el("span", "spletna-bliznjica-znak", ubezi(ime.charAt(0).toUpperCase() || "S")));
      var podatki = el("span", "spletna-bliznjica-podatki");
      podatki.appendChild(el("b", "", ubezi(app.ime || app.url)));
      try { podatki.appendChild(el("small", "", ubezi(new URL(app.url).hostname.replace(/^www\./, "")))); }
      catch (e) { podatki.appendChild(el("small", "", ubezi(app.url))); }
      gumb.appendChild(podatki);
      gumb.appendChild(el("span", "spletna-bliznjica-puscica", "›"));
      gumb.addEventListener("click", function () { otvoriSpletnoStran(app.url); });
      cilj.appendChild(gumb);
    });
  }
  function shraniSpletne(seznam) {
    S.spletne = seznam;
    narisiDomov();
    narisiSpletnoZacetno();
    klic("shraniSpletne", [seznam]).catch(function () {});
  }
  function normalizirajNaslov(s) {
    s = String(s || "").trim();
    if (!s) return "";
    if (!/^https?:\/\//i.test(s)) s = "https://" + s;
    try { var u = new URL(s); return /\./.test(u.hostname) ? u.href : ""; } catch (e) { return ""; }
  }
  function odpriDodaj() {
    $("dodajIme").value = "";
    $("dodajNaslov").value = "";
    $("slojDodaj").classList.add("viden");
    setTimeout(function () { $("dodajIme").focus(); }, 30);
  }

  // ------------------------------------------------------------------ odprta okna
  function osveziOkna() {
    klic("odprtaOkna").then(narisiOkna, function () {});
  }
  function narisiOkna(okna) {
    var blok = $("blokOkna");
    if (!blok) return;
    okna = okna || [];
    blok.hidden = okna.length === 0;
    var vrsta = $("okna");
    if (!vrsta) return;
    vrsta.innerHTML = "";
    okna.slice(0, 12).forEach(function (o) {
      var b = el("button", "okno");
      b.appendChild(slikaAliCrka(o.ikona, o.program || o.ime));
      b.appendChild(el("div", "", "<b>" + ubezi(o.program || o.ime) + "</b><span>" + ubezi(o.ime) + "</span>"));
      var z = el("span", "zapri", svg("x"));
      z.addEventListener("click", function (e) {
        e.stopPropagation();
        klic("zapriOkno", [o.id]).then(function () { setTimeout(osveziOkna, 500); });
      });
      b.appendChild(z);
      b.addEventListener("click", function () { klic("aktivirajOkno", [o.id]); });
      vrsta.appendChild(b);
    });
  }

  // ------------------------------------------------------------------ datoteke
  function velikost(b) {
    if (b < 1024) return b + " B";
    var e = ["kB", "MB", "GB", "TB"], i = -1;
    do { b /= 1024; i++; } while (b >= 1024 && i < e.length - 1);
    return (b < 10 ? b.toFixed(1) : Math.round(b)) + " " + e[i];
  }
  function datum(s) {
    if (!s) return "";
    return new Date(s * 1000).toLocaleDateString(LOKALE[jezik] || "en-GB", { day: "numeric", month: "short", year: "numeric" });
  }
  var IKONA_VRSTE = { mapa: "mapa", slika: "slika", video: "video", zvok: "glasba", dokument: "dokument",
                      arhiv: "arhiv", program: "program", drugo: "datoteka" };
  function vrsticaDatoteke(d, zPotjo, nedavna) {
    var b = el("button", "vrstica");
    b.innerHTML = svg(IKONA_VRSTE[d.vrsta] || "datoteka") + '<span class="ime">' + ubezi(d.ime) + "</span>" +
      (zPotjo ? '<span class="pod pot">' + ubezi(skrajsajPot(d.pot.replace(/\/[^\/]*$/, "") || "/")) + "</span>" : "") +
      '<span class="pod">' + (d.mapa ? "" : ubezi(velikost(d.velikost || 0)) + " · ") + ubezi(datum(d.spremenjeno || d.cas)) + "</span>";
    b.addEventListener("click", function () {
      if (d.mapa) { pojdi("datoteke"); odpriMapo(d.pot); }
      else { obvesti(t("odpiram", { ime: d.ime })); klic("odpriDatoteko", [d.pot]); }
    });
    if (!d.mapa && d.pot && S.povezava && S.povezava.stanje === "povezan") {
      // Poslji na drugo napravo v Safeer Linku (telefon, televizor, tablica).
      var p = el("span", "pozabi poslji-na", svg("poslji"));
      p.title = "Pošlji na napravo";
      p.addEventListener("click", function (e) { e.stopPropagation(); izberiNapravoZaPosiljanje(d); });
      b.appendChild(p);
    }
    if (nedavna) {
      // Iz seznama nedavnih (datoteka ostane): X na vsaki vrstici.
      var x = el("span", "pozabi", svg("x"));
      x.title = t("pozabiNedavno");
      x.addEventListener("click", function (e) {
        e.stopPropagation();
        klic("nedavnePozabi", [d.pot]).then(function () { b.remove(); osveziNedavne(); });
      });
      b.appendChild(x);
    }
    return b;
  }
  function posljiNaNapravo(d, n) {
    obvesti("Pošiljam " + d.ime + " na " + n.ime + " …");
    klic("posljiDatoteko", [n.id, d.pot]).then(function (ok) {
      if (!ok) obvesti("Datoteke ni bilo mogoče poslati na " + n.ime + ".");
    });
  }
  function izberiNapravoZaPosiljanje(d) {
    var naprave = S.napraveDatoteke || [];
    if (!naprave.length) {
      klic("napraveSDatoteki").then(function (n) {
        S.napraveDatoteke = n || [];
        if (S.napraveDatoteke.length) izberiNapravoZaPosiljanje(d);
        else obvesti("V Safeer Linku ni naprave, ki sprejema datoteke.");
      });
      return;
    }
    if (naprave.length === 1) { posljiNaNapravo(d, naprave[0]); return; }
    var staro = document.getElementById("slojPoslji");
    if (staro) staro.remove();
    var sloj = el("div", "sloj-koda-prijave");
    sloj.id = "slojPoslji";
    var okno = el("div", "koda-prijave-okno");
    var h = el("h2"); h.textContent = "Pošlji " + d.ime;
    okno.appendChild(h);
    naprave.forEach(function (n) {
      var g = el("button", "vrstica"); g.textContent = n.ime;
      g.addEventListener("click", function () { sloj.remove(); posljiNaNapravo(d, n); });
      okno.appendChild(g);
    });
    var z = el("button", "koda-prijave-gumb"); z.textContent = "Prekliči";
    z.addEventListener("click", function () { sloj.remove(); });
    okno.appendChild(z);
    sloj.addEventListener("click", function (e) { if (e.target === sloj) sloj.remove(); });
    sloj.appendChild(okno);
    document.body.appendChild(sloj);
  }
  function osveziNedavne() {
    narisiNedavneDomov();
    if (S.razdelek === "datoteke" && !S.pot) odpriNedavne();
  }
  function pocistiNedavne() {
    klic("nedavnePocisti").then(function () { obvesti(t("seznamPocisten")); osveziNedavne(); });
  }
  function dom() { return (S.zacetek && S.zacetek.mape && S.zacetek.mape[0] && S.zacetek.mape[0].pot) || ""; }
  function skrajsajPot(p) { var d = dom(); return d && p.indexOf(d) === 0 ? "~" + p.slice(d.length) : p; }
  function narisiMape() {
    narisiFiltreNapravDatoteke();
    var seznam = $("mapeSeznam");
    seznam.innerHTML = "";
    var ned = el("button", S.pot === "" ? "izbran" : "", svg("ura") + "<span>" + ubezi(t("nedavno")) + "</span>");
    ned.addEventListener("click", odpriNedavne);
    seznam.appendChild(ned);
    var IK_MAPE = { HOME: "domov", DESKTOP: "namizje", DOCUMENTS: "dokument", DOWNLOAD: "arhiv", PICTURES: "slika",
                    MUSIC: "glasba", VIDEOS: "video" };
    ((S.zacetek && S.zacetek.mape) || []).forEach(function (m) {
      var b = el("button", S.pot === m.pot ? "izbran" : "", svg(IK_MAPE[m.vrsta] || "mapa") + "<span>" + ubezi(m.ime) + "</span>");
      b.addEventListener("click", function () { odpriMapo(m.pot); });
      seznam.appendChild(b);
    });
  }
  function odpriNedavne() {
    S.pot = "";
    narisiMape();
    var dr = $("drobtine");
    dr.innerHTML = "";
    dr.appendChild(el("button", "", ubezi(t("nedavno"))));
    var desnoN = el("div", "desno");
    var poc = el("button", "gumb", svg("x") + "<span>" + ubezi(t("pocistiSeznam")) + "</span>");
    poc.addEventListener("click", pocistiNedavne);
    desnoN.appendChild(poc);
    dr.appendChild(desnoN);
    klic("nedavne").then(function (seznam) {
      S.nedavne = seznam || [];
      var v = $("vsebinaMape");
      v.innerHTML = "";
      if (!S.nedavne.length) { v.appendChild(el("div", "prazno", ubezi(t("prazno")))); return; }
      S.nedavne.forEach(function (d) { v.appendChild(vrsticaDatoteke(d, true, true)); });
    }, function () {});
  }
  function odpriMapo(pot) {
    klic("mapa", [pot]).then(function (r) {
      S.pot = r.pot;
      narisiMape();
      var dr = $("drobtine");
      dr.innerHTML = "";
      var d = dom();
      var zacetek = d && r.pot.indexOf(d) === 0 ? d : "/";
      var deli = r.pot.slice(zacetek.length).split("/").filter(Boolean);
      var koren = el("button", "", ubezi(zacetek === "/" ? "/" : (S.zacetek.mape[0].ime || "~")));
      koren.addEventListener("click", function () { odpriMapo(zacetek); });
      dr.appendChild(koren);
      var sproti = zacetek.replace(/\/$/, "");
      deli.forEach(function (del) {
        sproti += "/" + del;
        var cilj = sproti;
        dr.appendChild(el("span", "loc", "›"));
        var b = el("button", "", ubezi(del));
        b.addEventListener("click", function () { odpriMapo(cilj); });
        dr.appendChild(b);
      });
      var desno = el("div", "desno");
      var vDat = el("button", "gumb", svg("mapa") + "<span>" + ubezi(t("odpriVDatotekah")) + "</span>");
      vDat.addEventListener("click", function () { klic("pokaziVMapi", [r.pot]); });
      desno.appendChild(vDat);
      dr.appendChild(desno);
      var v = $("vsebinaMape");
      v.innerHTML = "";
      if (r.napaka) { v.appendChild(el("div", "prazno", ubezi(t(r.napaka === "ni_dovoljenja" ? "niDovoljenja" : "prazno")))); return; }
      if (!r.elementi.length) { v.appendChild(el("div", "prazno", ubezi(t("prazno")))); return; }
      r.elementi.forEach(function (e) { v.appendChild(vrsticaDatoteke(e, false)); });
    }, function () {});
  }

  function normalizirajVrsto(vrsta, jeMapa) {
    if (jeMapa || vrsta === "folder" || vrsta === "mapa") return "mapa";
    if (vrsta === "image" || vrsta === "slika") return "slika";
    if (vrsta === "video") return "video";
    if (vrsta === "audio" || vrsta === "zvok" || vrsta === "music") return "zvok";
    if (vrsta === "document" || vrsta === "dokument") return "dokument";
    if (vrsta === "archive" || vrsta === "arhiv") return "arhiv";
    if (vrsta === "app" || vrsta === "program") return "program";
    return "drugo";
  }

  function vrsticaDaljinskeDatoteke(d, idNaprave, server) {
    var jeMapa = (d.type === "folder" || d.vrsta === "folder" || d.vrsta === "mapa");
    var vrsta = normalizirajVrsto(d.type || d.vrsta, jeMapa);
    var imeDat = d.name || d.ime || "";
    var idDat = d.id || "";
    var b = el("button", "vrstica");
    b.innerHTML = svg(IKONA_VRSTE[vrsta] || "datoteka") + '<span class="ime">' + ubezi(imeDat) + '</span>' +
      '<span class="pod">' + (jeMapa ? "" : ubezi(velikost(d.size || d.velikost || 0)) + " · ") + ubezi(datum(d.mtime || d.spremenjeno || 0)) + '</span>';

    if (jeMapa) {
      b.addEventListener("click", function () {
        S.daljinskaPot.push({ id: idDat, ime: imeDat });
        naloziMapoNaprave(idNaprave, idDat, imeDat);
      });
    } else {
      b.addEventListener("click", function () {
        if (server && server.base_url) {
          obvesti(t("prenasamDatoteko", { ime: imeDat }));
          klic("prenesiDatotekoNaprave", [idNaprave, idDat, imeDat, server]).then(function (r) {
            if (r && r.ok) obvesti(t("datotekaPrenesena", { ime: imeDat }));
            else obvesti(t("napakaPrenosa"));
          }, function () { obvesti(t("napakaPrenosa")); });
        } else {
          var n = S.napraveDatoteke.find(function (x) { return x.id === idNaprave; }) || { ime: "" };
          obvesti(t("odpiramNaNapravi", { ime: imeDat, naprava: n.ime }));
          klic("odpriDatotekoNaprave", [idNaprave, idDat]);
        }
      });

      var gOdpri = el("span", "dejanje", svg("zaslon"));
      gOdpri.title = t("odpriNaNapravi");
      gOdpri.addEventListener("click", function (e) {
        e.stopPropagation();
        var n = S.napraveDatoteke.find(function (x) { return x.id === idNaprave; }) || { ime: "" };
        obvesti(t("odpiramNaNapravi", { ime: imeDat, naprava: n.ime }));
        klic("odpriDatotekoNaprave", [idNaprave, idDat]);
      });
      b.appendChild(gOdpri);
    }
    return b;
  }

  function nalozNapraveSDatoteki() {
    if (S.povezava.stanje !== "povezan") {
      S.napraveDatoteke = [];
      if (S.izbranaNapravaDatoteke) {
        S.izbranaNapravaDatoteke = "";
        odpriNedavne();
      }
      narisiFiltreNapravDatoteke();
      return;
    }
    klic("napraveSDatoteki").then(function (n) {
      S.napraveDatoteke = n || [];
      if (S.izbranaNapravaDatoteke && !S.napraveDatoteke.some(function (x) { return x.id === S.izbranaNapravaDatoteke; })) {
        S.izbranaNapravaDatoteke = "";
        odpriNedavne();
      }
      narisiFiltreNapravDatoteke();
    }, function () {});
  }

  function narisiFiltreNapravDatoteke() {
    var fn = $("filtriNapravDatoteke");
    if (!fn) return;
    fn.innerHTML = "";
    fn.hidden = !S.napraveDatoteke.length;
    var opis = $("datotekeOpis");
    if (S.napraveDatoteke.length) {
      var ta = el("button", S.izbranaNapravaDatoteke === "" ? "izbran" : "", svg("namizje") + ubezi(t("taRacunalnik")));
      ta.addEventListener("click", function () {
        if (S.izbranaNapravaDatoteke === "") return;
        S.izbranaNapravaDatoteke = "";
        narisiFiltreNapravDatoteke();
        odpriNedavne();
      });
      fn.appendChild(ta);
      S.napraveDatoteke.forEach(function (n) {
        var b = el("button", S.izbranaNapravaDatoteke === n.id ? "izbran" : "", svg(ikonaNaprave(n)) + ubezi(n.ime));
        b.addEventListener("click", function () {
          S.izbranaNapravaDatoteke = n.id;
          narisiFiltreNapravDatoteke();
          odpriKorenNaprave(n);
        });
        fn.appendChild(b);
      });
    }
    if (opis) {
      if (S.izbranaNapravaDatoteke) {
        var izbrana = S.napraveDatoteke.find(function (x) { return x.id === S.izbranaNapravaDatoteke; });
        opis.textContent = t("datotekeNaprave", { n: "", naprava: izbrana ? izbrana.ime : "" });
      } else {
        opis.textContent = S.napraveDatoteke.length
          ? t("datotekePodNaprave", { n: ((S.zacetek && S.zacetek.mape) || []).length, k: S.napraveDatoteke.length })
          : t("datotekeOpis");
      }
    }
  }

  function odpriKorenNaprave(n) {
    S.daljinskaPot = [{ id: "", ime: n.ime }];
    naloziMapoNaprave(n.id, "", n.ime);
  }

  function naloziMapoNaprave(idNaprave, mapaId, mapaIme) {
    var izbrana = S.napraveDatoteke.find(function (x) { return x.id === idNaprave; });
    var imeNaprave = izbrana ? izbrana.ime : "";
    var dr = $("drobtine");
    if (dr) {
      dr.innerHTML = "";
      S.daljinskaPot.forEach(function (korak, idx) {
        if (idx > 0) dr.appendChild(el("span", "loc", "›"));
        var g = el("button", "", ubezi(korak.ime));
        g.addEventListener("click", function () {
          S.daljinskaPot = S.daljinskaPot.slice(0, idx + 1);
          naloziMapoNaprave(idNaprave, korak.id, korak.ime);
        });
        dr.appendChild(g);
      });
      var desno = el("div", "desno");
      var osvez = el("button", "gumb", svg("ponovno") + "<span>" + ubezi(t("osvezi")) + "</span>");
      osvez.addEventListener("click", function () {
        naloziMapoNaprave(idNaprave, mapaId, mapaIme);
      });
      desno.appendChild(osvez);
      dr.appendChild(desno);
    }

    narisiMapeNaprave(idNaprave, mapaId);

    var v = $("vsebinaMape");
    if (v) {
      v.innerHTML = '<div class="prazno">' + ubezi(t("nalagamDatoteke")) + '</div>';
    }

    klic("datotekeNaprave", [idNaprave, mapaId]).then(function (r) {
      if (S.izbranaNapravaDatoteke !== idNaprave) return;
      if (!v) return;
      v.innerHTML = "";
      if (!r || !r.ok) {
        v.appendChild(el("div", "prazno", ubezi(t("napravaNiOdgovorilaDatoteke"))));
        return;
      }
      if (r.server) {
        S.daljinskiServer[idNaprave] = r.server;
      }
      if (mapaId === "") {
        S.daljinskiKoreni[idNaprave] = (r.items || []).filter(function (x) { return x.type === "folder" || x.vrsta === "folder" || x.vrsta === "mapa"; });
        narisiMapeNaprave(idNaprave, mapaId);
      }
      var opis = $("datotekeOpis");
      if (opis) {
        opis.textContent = t("datotekeNaprave", { n: r.items ? r.items.length : 0, naprava: imeNaprave });
      }
      if (!r.shared) {
        v.appendChild(el("div", "prazno", ubezi(t("napravaNeDeliDatotek"))));
        return;
      }
      var elementi = r.items || [];
      if (!elementi.length) {
        v.appendChild(el("div", "prazno", ubezi(t("prazno"))));
        return;
      }
      var razvrsceni = elementi.slice().sort(function (a, b) {
        var am = (a.type === "folder" || a.vrsta === "folder" || a.vrsta === "mapa");
        var bm = (b.type === "folder" || b.vrsta === "folder" || b.vrsta === "mapa");
        if (am !== bm) return am ? -1 : 1;
        var na = (a.name || a.ime || "").toLowerCase();
        var nb = (b.name || b.ime || "").toLowerCase();
        return na.localeCompare(nb);
      });
      razvrsceni.forEach(function (e) {
        v.appendChild(vrsticaDaljinskeDatoteke(e, idNaprave, r.server || S.daljinskiServer[idNaprave]));
      });
    }, function () {
      if (S.izbranaNapravaDatoteke !== idNaprave) return;
      if (v) {
        v.innerHTML = "";
        v.appendChild(el("div", "prazno", ubezi(t("napravaNiOdgovorilaDatoteke"))));
      }
    });
  }

  function narisiMapeNaprave(idNaprave, aktivnaMapaId) {
    var seznam = $("mapeSeznam");
    if (!seznam) return;
    seznam.innerHTML = "";
    var izbrana = S.napraveDatoteke.find(function (x) { return x.id === idNaprave; });
    var imeNaprave = izbrana ? izbrana.ime : "";
    var koren = el("button", aktivnaMapaId === "" ? "izbran" : "", svg("mapa") + "<span>" + ubezi(t("korenMape")) + "</span>");
    koren.addEventListener("click", function () {
      S.daljinskaPot = [{ id: "", ime: imeNaprave }];
      naloziMapoNaprave(idNaprave, "", imeNaprave);
    });
    seznam.appendChild(koren);

    var koreni = S.daljinskiKoreni[idNaprave] || [];
    koreni.forEach(function (m) {
      var mId = m.id || "";
      var mIme = m.name || m.ime || "";
      var b = el("button", aktivnaMapaId === mId ? "izbran" : "", svg("mapa") + "<span>" + ubezi(mIme) + "</span>");
      b.addEventListener("click", function () {
        S.daljinskaPot = [{ id: "", ime: imeNaprave }, { id: mId, ime: mIme }];
        naloziMapoNaprave(idNaprave, mId, mIme);
      });
      seznam.appendChild(b);
    });
  }
  function narisiNedavneDomov() {
    klic("nedavne").then(function (seznam) {
      seznam = (seznam || []).slice(0, 5);
      if ($("blokNedavne")) $("blokNedavne").hidden = !seznam.length;
      var v = $("nedavneDomov") || $("domovNadaljuj");
      if (!v) return;
      v.innerHTML = "";
      seznam.forEach(function (d) { v.appendChild(vrsticaDatoteke(d, true, true)); });
    }, function () {});
  }

  // ------------------------------------------------------------------ naprave
  var odjavaPotrjujem = false, odjavaCas = 0;
  function osveziPovezavo() {
    return klic("povezava").then(function (p) { S.povezava = p || S.povezava; narisiPovezavo(); }, function () { narisiPovezavo(); });
  }
  // V Napravah nepovezan racunalnik isce Safeer Link naprej: ko ga uporabnik vklopi na televizorju
  // ali telefonu, se kartica posodobi sama - brez klikanja »poišči znova«.
  var napraveCas = null;
  function napraveZanka() {
    clearInterval(napraveCas);
    napraveCas = setInterval(function () {
      if (S.razdelek !== "naprave") { clearInterval(napraveCas); return; }
      if (S.povezava.stanje !== "povezan") osveziPovezavo();
    }, 12000);
  }
  function narisiPovezavo() {
    var p = S.povezava;
    if (S.stanje) setTimeout(function () { narisiStanje(S.stanje); }, 0);
    var povezan = p.stanje === "povezan";
    if ($("napravePika")) $("napravePika").className = "pika" + (povezan ? "" : " siva");
    if ($("napraveNaslov")) $("napraveNaslov").textContent = t(povezan ? "povezanNaslov" : (p.stanje === "brez" ? "brezNaslov" : "novNaslov"));
    var hubi = p.hubi || [];
    if ($("napraveBesedilo")) $("napraveBesedilo").textContent = !p.control ? t("niControla") : povezan ? t("povezanOpis") :
      (hubi.length ? t("novOpisHub", { ime: hubi[0].ime }) : (p.hubi ? t("novOpisBrezHuba") : t("novOpis")));
    var namig = $("napraveNamig");
    if (namig) {
      namig.hidden = povezan || !p.control || hubi.length > 0 || !p.hubi;
      namig.textContent = t("napraveNamig");
    }
    narisiSeznamNaprav(povezan && !!p.control);
    if ($("gumbControl")) {
      $("gumbControl").hidden = !p.control;
      if ($("gumbControlBesedilo")) $("gumbControlBesedilo").textContent = t(povezan ? "odpriControl" : "poveziNaprave");
      var cSvg = $("gumbControl").querySelector("svg");
      if (cSvg) cSvg.innerHTML = '<path d="' + IK[povezan ? "naprave" : "qr"] + '"/>';
    }
    if ($("kNapravePod")) $("kNapravePod").textContent = t(povezan ? "napravePodPovezan" : "napravePodNov");
    if ($("blokZaupanje")) $("blokZaupanje").hidden = !povezan;
    if ($("gumbOdjava")) {
      $("gumbOdjava").hidden = !povezan || !p.control;
      $("gumbOdjava").classList.toggle("opozorilo", odjavaPotrjujem);
    }
    if ($("gumbOdjavaBesedilo")) $("gumbOdjavaBesedilo").textContent = t(odjavaPotrjujem ? "odjavaPotrdi" : "odjaviRacunalnik");
    if ($("stikaloZaupaj")) $("stikaloZaupaj").setAttribute("aria-checked", p.zaupana ? "true" : "false");
    if ($("zaupajPod")) $("zaupajPod").textContent = t(p.zaupana ? "zaupajDa" : "zaupajNe");
    if ($("domNapravaStanje")) $("domNapravaStanje").innerHTML = '<i class="pika' + (povezan ? "" : " siva") + '"></i><span>' +
      ubezi(t(povezan ? "povezanKratko" : "niPovezano")) + "</span>";
    if ($("domControl")) {
      $("domControl").hidden = !p.control;
      if ($("domControlBesedilo")) $("domControlBesedilo").textContent = t(povezan ? "odpriControl" : "poveziNaprave");
      var dSvg = $("domControl").querySelector("svg");
      if (dSvg) dSvg.innerHTML = '<path d="' + IK[povezan ? "naprave" : "qr"] + '"/>';
    }
    var sp = $("stanjePovezava");
    if (sp) sp.innerHTML = '<i class="pika' + (povezan ? "" : " siva") + '"></i><span>' + ubezi(povezan ? t("povezano") : t("brezNaprav")) + "</span>";
  }

  // Naprave v Linku s preimenovanjem: ime hrani sredisce, zato ga vidijo vse naprave (telefon, TV, tablica).
  var preimenujem = null;
  function narisiSeznamNaprav(pokaziSeznam) {
    var blok = $("blokSeznamNaprav");
    blok.hidden = !pokaziSeznam;
    if (!pokaziSeznam) { preimenujem = null; return; }
    klic("vseNaprave").then(function (naprave) {
      var ul = $("seznamNaprav"); ul.innerHTML = "";
      (naprave || []).forEach(function (n) {
        var li = el("li");
        var opis = n.ta ? t("taRacunalnik") : (n.platforma ? t("plat_" + n.platforma) : (n.vrsta || ""));
        if (preimenujem === n.id) {
          li.innerHTML = svg(ikonaNaprave(n)) + '<input class="vnosImena" maxlength="64"><button class="gumb glavni majhen"></button><button class="gumb majhen"></button>';
          var vnos = li.querySelector("input"); vnos.value = n.ime; vnos.placeholder = t("vnesiIme");
          var gumbi = li.querySelectorAll("button");
          gumbi[0].textContent = t("shraniIme"); gumbi[1].textContent = t("preklici");
          gumbi[0].addEventListener("click", function () { shraniIme(n.id, vnos.value); });
          gumbi[1].addEventListener("click", function () { preimenujem = null; narisiSeznamNaprav(true); });
          vnos.addEventListener("keydown", function (e) {
            if (e.key === "Enter") shraniIme(n.id, vnos.value);
            if (e.key === "Escape") { preimenujem = null; narisiSeznamNaprav(true); }
          });
          setTimeout(function () { vnos.focus(); vnos.select(); }, 0);
        } else {
          var jeDaljinec = !n.ta && (
            (n.zmoznosti && n.zmoznosti.indexOf("remote") >= 0) ||
            n.platforma === "tv" || n.vrsta === "screen" || n.vloga === "receiver"
          );
          var htmlGumbi = '<div style="display:flex;gap:6px;align-items:center;">' +
            '<button class="gumb majhen gumb-preimenuj">✎ ' + ubezi(t("preimenuj")) + '</button>';
          if (jeDaljinec) {
            htmlGumbi += '<button class="gumb majhen glavni gumb-daljinec" style="display:inline-flex;gap:4px;align-items:center;">' +
              svg("daljinec") + '<span>' + ubezi(t("daljinec") || "Daljinec") + '</span></button>';
          }
          htmlGumbi += '</div>';

          li.innerHTML = svg(ikonaNaprave(n)) + "<div><b></b><small></small></div>" + htmlGumbi;
          li.querySelector("b").textContent = n.ime || n.id;
          li.querySelector("small").textContent = opis;
          var gPreimenuj = li.querySelector(".gumb-preimenuj");
          if (gPreimenuj) {
            gPreimenuj.title = t("preimenuj");
            gPreimenuj.addEventListener("click", function () { preimenujem = n.id; narisiSeznamNaprav(true); });
          }
          var gDaljinec = li.querySelector(".gumb-daljinec");
          if (gDaljinec) {
            gDaljinec.title = t("daljinec") || "Daljinec";
            gDaljinec.addEventListener("click", function () {
              obvesti(t("odpiram", { ime: n.ime || "Daljinec" }));
              klic("daljinec", [n.id]);
            });
          }
        }
        ul.appendChild(li);
      });
      $("seznamNapravNamig").textContent = t("preimenujNamig");
    }, function () {});
  }
  function shraniIme(id, ime) {
    klic("preimenujNapravo", [id, ime]).then(function (r) {
      preimenujem = null;
      obvesti(t(r && r.ok ? "preimenovano" : "napPreimenovanje"));
      narisiSeznamNaprav(true);
      nalozNaprave();
    }, function () { obvesti(t("napPreimenovanje")); });
  }

  // ------------------------------------------------------------------ stanje sistema (vrstica zgoraj)
  function narisiStanje(s) {
    if (!s) return;
    S.stanje = s;
    var o = s.omrezje || {};
    var ikona = o.vrsta === "wifi" ? "wifi" : (o.vrsta === "ethernet" ? "ethernet" : "brezOmrezja");
    var ime = o.vrsta === "ethernet" ? (o.ime || t("zicna")) : (o.ime || t("brezOmrezja"));
    if ($("stanjeOmrezje")) {
      $("stanjeOmrezje").innerHTML = svg(ikona) + "<span>" + ubezi(ime) + "</span>";
      $("stanjeOmrezje").title = o.ime || "";
    }
    var z = s.zvok;
    if ($("stanjeZvok")) {
      $("stanjeZvok").innerHTML = z ? svg(z.utisan ? "utisan" : "zvok") + "<span>" + (z.utisan ? "" : z.glasnost + " %") + "</span>" : "";
    }
    var b = s.baterija;
    if ($("stanjeBaterija")) {
      $("stanjeBaterija").innerHTML = b ? svg(b.polni ? "polni" : "baterija") + "<span>" + b.odstotek + " %</span>" : "";
    }
    if ($("sistemPodatki")) {
      var podatki = [[t("omrezje"), ime, !!o.povezan]];
      if (b) podatki.push([t("baterija"), b.odstotek + " %" + (b.polni && !b.polna ? " · " + t("polni") : ""), true]);
      podatki.push(["Safeer Link", t(S.povezava.stanje === "povezan" ? "povezanKratko" : "niPovezano"), S.povezava.stanje === "povezan"]);
      $("sistemPodatki").innerHTML = podatki.map(function (v) {
        return "<dt>" + ubezi(v[0]) + '</dt><dd><i class="pika' + (v[2] ? "" : " siva") + '"></i>' + ubezi(v[1]) + "</dd>";
      }).join("");
    }
    if ($("slojHitro") && $("slojHitro").classList.contains("viden")) narisiHitro();
  }
  function osveziStanje() { klic("stanje").then(narisiStanje, function () {}); }

  // Drsniki in stikala (hitra plosca in nastavitve)
  var zamik = {};
  function drsnik(kljuc, ikona, vrednost, ob) {
    var d = el("div", "drsnik");
    d.innerHTML = svg(ikona) + "<label>" + ubezi(t(kljuc)) + '</label><input type="range" min="0" max="100" step="1"><output></output>';
    var vhod = d.querySelector("input"), izhod = d.querySelector("output");
    vhod.value = vrednost;
    izhod.textContent = vrednost + " %";
    vhod.setAttribute("aria-label", t(kljuc));
    vhod.addEventListener("input", function () {
      izhod.textContent = vhod.value + " %";
      clearTimeout(zamik[kljuc]);
      zamik[kljuc] = setTimeout(function () { ob(parseInt(vhod.value, 10)); }, 120);
    });
    return d;
  }
  function stikalo(kljuc, ikona, vklop, ob, pod) {
    var b = el("button", "stikalo");
    b.setAttribute("role", "switch");
    b.setAttribute("aria-checked", vklop ? "true" : "false");
    b.innerHTML = svg(ikona) + "<div><span>" + ubezi(t(kljuc)) + "</span>" + (pod ? "<small>" + ubezi(pod) + "</small>" : "") + "</div><i></i>";
    b.addEventListener("click", function () {
      var nov = b.getAttribute("aria-checked") !== "true";
      b.setAttribute("aria-checked", nov ? "true" : "false");
      ob(nov);
    });
    return b;
  }
  function kontrole(cilj, kompaktno) {
    var s = S.stanje || {};
    cilj.innerHTML = "";
    if (s.zvok) {
      cilj.appendChild(drsnik("glasnost", s.zvok.utisan ? "utisan" : "zvok", Math.min(100, s.zvok.glasnost), function (v) {
        klic("glasnost", [v]).then(function () { s.zvok.glasnost = v; s.zvok.utisan = false; narisiStanje(s); });
      }));
    }
    if (s.svetlost != null) {
      cilj.appendChild(drsnik("svetlost", "svetlost", s.svetlost, function (v) { klic("svetlost", [v]); s.svetlost = v; }));
    }
    var mreza = kompaktno ? el("div", "hitro-mreza") : cilj;
    var o = s.omrezje || {};
    if (o.wifi_obstaja) {
      mreza.appendChild(stikalo("wifi", "wifi", !!o.wifi_vklopljen, function (v) {
        klic("wifi", [v]).then(function () { setTimeout(osveziStanje, 1500); });
      }, kompaktno ? "" : (o.vrsta === "wifi" ? o.ime : (o.wifi_vklopljen ? "" : t("wifiIzklopljen")))));
    }
    if (s.nocna != null) mreza.appendChild(stikalo("nocna", "luna", !!s.nocna, function (v) { klic("nocna", [v]); s.nocna = v; }));
    if (s.zvok) {
      mreza.appendChild(stikalo("utisaj", "utisan", !!s.zvok.utisan, function () {
        klic("utisaj").then(function () { setTimeout(osveziStanje, 200); });
      }));
    }
    if (kompaktno) {
      cilj.appendChild(mreza);
      var vec = el("button", "gumb", svg("drsniki") + "<span>" + ubezi(t("nastavitve")) + "</span>");
      vec.addEventListener("click", function () { zapriSloje(); pojdi("nastavitve"); });
      cilj.appendChild(vec);
    }
  }
  function narisiHitro() { kontrole($("hitro"), true); }
  function odpriHitro() { zapriSloje(); narisiHitro(); $("slojHitro").classList.add("viden"); osveziStanje(); }

  // ------------------------------------------------------------------ omrezje
  var omrezjeGeslo = "", omrezjePozabi = "", omrezjeZaposleno = false;
  function signalIkona(n) { return n >= 67 ? 3 : (n >= 34 ? 2 : 1); }
  function nalozOmrezje(osvezi) {
    if (osvezi) $("omrezjeStanje").textContent = t("iscemOmrezja");
    klic("omrezje", [!!osvezi]).then(narisiOmrezje, function () {});
  }
  function narisiOmrezje(o) {
    o = o || { naprave: [], omrezja: [], shranjene: [] };
    var wifi = o.naprave.filter(function (n) { return n.vrsta === "wifi"; });
    var trenutne = $("omrezjeTrenutno");
    trenutne.innerHTML = "";
    o.naprave.forEach(function (n) {
      var povezana = n.stanje === "connected";
      var ime = n.vrsta === "ethernet" ? t("zicna") : "Wi-Fi";
      var v = el("div", "vrstica", svg(n.vrsta === "ethernet" ? "ethernet" : "wifi") + '<span class="ime">' + ubezi(ime) +
        (povezana && n.povezava ? " · " + ubezi(n.povezava) : "") + '</span><span class="pod"><i class="pika' + (povezana ? "" : " siva") +
        '"></i> ' + ubezi(t(povezana ? "povezanKratko" : "niPovezano")) + "</span>");
      trenutne.appendChild(v);
    });
    if (!o.naprave.length) trenutne.appendChild(el("div", "prazno", ubezi(t("brezOmrezja"))));
    var st = $("stikaloWifiOmrezje");
    st.hidden = !wifi.length;
    st.setAttribute("aria-checked", o.wifi_vklopljen ? "true" : "false");
    $("blokWifi").hidden = !wifi.length || !o.wifi_vklopljen;
    $("omrezjeStanje").textContent = !wifi.length ? t("niWifi") : (o.wifi_vklopljen ? "" : t("wifiIzklopljen"));
    var seznam = $("omrezjaSeznam");
    seznam.innerHTML = "";
    if (o.wifi_vklopljen && !o.omrezja.length) seznam.appendChild(el("div", "prazno", ubezi(t("niOmrezij"))));
    o.omrezja.forEach(function (w) {
      var v = el("div", "vrstica omrezje" + (w.povezano ? " povezano" : ""));
      v.innerHTML = '<span class="signal s' + signalIkona(w.signal) + '">' + svg("wifi") + "</span>" +
        '<span class="ime">' + ubezi(w.ime) + (w.zasciteno ? " " + '<svg class="kljucavnica" viewBox="0 0 24 24"><path d="' + IK.zakleni + '"/></svg>' : "") + "</span>";
      var desno = el("span", "dejanja");
      if (w.povezano) {
        desno.appendChild(el("span", "znacka", ubezi(t("povezanKratko"))));
        var odk = el("button", "gumb", ubezi(t("odklopi")));
        odk.addEventListener("click", function () {
          klic("omrezjeOdklopi", [w.ime]).then(function () { setTimeout(function () { nalozOmrezje(false); }, 800); });
        });
        desno.appendChild(odk);
      } else if (omrezjeGeslo === w.ime) {
        var vnos = el("input", "vnosGesla");
        vnos.type = "password"; vnos.placeholder = t("vnesiGeslo"); vnos.autocomplete = "off";
        var pov = el("button", "gumb glavni", ubezi(t("povezi")));
        var posl = function () {
          if (omrezjeZaposleno) return;
          omrezjeZaposleno = true;
          pov.textContent = t("povezujemSe");
          klic("omrezjePovezi", [w.ime, vnos.value]).then(function (r) {
            omrezjeZaposleno = false;
            if (r && r.ok) { omrezjeGeslo = ""; obvesti(t("povezanKratko") + ": " + w.ime); }
            else obvesti(t(r && r.napaka === "geslo" ? "napacnoGeslo" : "niUspelo"));
            nalozOmrezje(false);
          });
        };
        pov.addEventListener("click", posl);
        vnos.addEventListener("keydown", function (e) { if (e.key === "Enter") posl(); if (e.key === "Escape") { omrezjeGeslo = ""; nalozOmrezje(false); } });
        desno.appendChild(vnos); desno.appendChild(pov);
        setTimeout(function () { vnos.focus(); }, 30);
      } else {
        var p = el("button", "gumb", ubezi(t("povezi")));
        p.addEventListener("click", function () {
          if (w.zasciteno && !w.shranjeno) { omrezjeGeslo = w.ime; narisiOmrezje(o); return; }
          p.textContent = t("povezujemSe");
          klic("omrezjePovezi", [w.ime, ""]).then(function (r) {
            if (r && r.ok) obvesti(t("povezanKratko") + ": " + w.ime);
            else if (r && r.napaka === "geslo") { omrezjeGeslo = w.ime; }
            else obvesti(t("niUspelo"));
            nalozOmrezje(false);
          });
        });
        desno.appendChild(p);
      }
      v.appendChild(desno);
      seznam.appendChild(v);
    });
    var sh = $("omrezjaShranjena");
    sh.innerHTML = "";
    o.shranjene.forEach(function (c) {
      var v = el("div", "vrstica", svg(c.vrsta === "wifi" ? "wifi" : "ethernet") + '<span class="ime">' + ubezi(c.ime) + "</span>");
      var desno = el("span", "dejanja");
      if (c.aktivna) desno.appendChild(el("span", "znacka", ubezi(t("povezanKratko"))));
      else {
        var akt = el("button", "gumb", ubezi(t("povezi")));
        akt.addEventListener("click", function () {
          akt.textContent = t("povezujemSe");
          klic("omrezjeAktiviraj", [c.ime]).then(function (ok) { if (!ok) obvesti(t("niUspelo")); nalozOmrezje(false); });
        });
        desno.appendChild(akt);
      }
      var poz = el("button", "gumb" + (omrezjePozabi === c.ime ? " opozorilo" : ""), ubezi(t(omrezjePozabi === c.ime ? "potrdiPozabi" : "pozabiOmrezje")));
      poz.addEventListener("click", function () {
        if (omrezjePozabi !== c.ime) { omrezjePozabi = c.ime; narisiOmrezje(o); return; }
        omrezjePozabi = "";
        klic("omrezjePozabi", [c.ime]).then(function () { nalozOmrezje(false); });
      });
      desno.appendChild(poz);
      v.appendChild(desno);
      sh.appendChild(v);
    });
    $("blokShranjene").hidden = !o.shranjene.length;
    $("gumbOmrezjeNapredno").hidden = !o.napredno;
  }

  // ------------------------------------------------------------------ zvok
  var zvokStanje = null, zvokCas = 0, zvokDotik = 0, zvokCaka = "";
  var IKONA_ZVOKA = { zvocniki: "zvok", slusalke: "slusalke", hdmi: "zaslon", bluetooth: "bluetooth", usb: "zvok", mikrofon: "mikrofon" };
  var jblStanje = null, jblZaposleno = false;
  function nalozJbl() {
    klic("jbl").then(function (j) { jblStanje = j; narisiJbl(); }, function () {});
  }
  function narisiJbl() {
    var c = $("zvokJbl");
    c.innerHTML = "";
    var j = jblStanje;
    if (!j || !(j.vklop || j.najdena)) return;
    var pod = jblZaposleno ? t("jblPrenasam") : t("jblOpis");
    var st = stikalo("jblStikalo", "zvok", !!j.vklop, function (v) {
      if (jblZaposleno) return;
      jblZaposleno = true;
      narisiJbl();
      klic("jblVklop", [v]).then(function (r) {
        jblZaposleno = false;
        jblStanje = r;
        if (r && r.napaka) obvesti(t("jblNapaka_" + r.napaka));
        else if (v) obvesti(t("jblVklopljeno", { ime: r.ime || "JBL" }));
        narisiJbl();
      }, function () { jblZaposleno = false; narisiJbl(); });
    }, pod);
    st.querySelector("span").textContent = t("jblStikalo", { ime: j.ime || "JBL" });
    c.appendChild(st);
  }

  // ---- Scit: filtriranje DNS za ves racunalnik (stikalo in stanje v Nastavitvah) ----
  var scitStanje = null, scitZaposleno = false, scitCas = null;
  function nalozScit() {
    klic("scit").then(function (s) { scitStanje = s; narisiScit(); }, function () {});
  }
  function scitZanka() {
    clearInterval(scitCas);
    scitCas = setInterval(function () {
      if (S.razdelek !== "nastavitve") { clearInterval(scitCas); return; }
      if (!scitZaposleno) nalozScit();
    }, 5000);
  }
  function narisiScit() {
    var c = $("blokScit");
    c.innerHTML = "";
    var s = scitStanje;
    if (!s) return;
    var pod;
    if (scitZaposleno) pod = t("scitPripravljam");
    else if (!s.mozno) pod = t("scitNiMozno");
    else if (s.napaka) pod = t("scitNapaka_" + s.napaka);
    else if (s.vklop && s.tece) pod = s.domen ? t("scitTece", { n: s.blokiranih, p: s.poizvedb, d: s.domen }) : t("scitSeznami");
    else pod = t("scitOpis");
    var st = stikalo("scitStikalo", "scit", !!(s.vklop && s.tece) || (scitZaposleno && !s.vklop), function (v) {
      if (scitZaposleno || !s.mozno) { narisiScit(); return; }
      scitZaposleno = true;
      narisiScit();
      klic("scitVklop", [v]).then(function (r) {
        scitZaposleno = false;
        scitStanje = r;
        if (r && r.napaka) obvesti(t("scitNapaka_" + r.napaka));
        else obvesti(t(v ? "scitVklopljen" : "scitIzklopljen"));
        narisiScit();
      }, function () { scitZaposleno = false; nalozScit(); });
    }, pod);
    if (!s.mozno) st.classList.add("onemogoceno");
    c.appendChild(st);
    if (s.vklop && s.tece && s.zadnje && s.zadnje.length) {
      var z = el("div", "scit-zadnje", "<b>" + ubezi(t("scitZadnje")) + "</b>");
      s.zadnje.slice(0, 6).forEach(function (x) {
        z.appendChild(el("span", "", ubezi(x.ime) + " <i>" + ubezi(t("scitKat_" + x.kategorija)) + "</i>"));
      });
      c.appendChild(z);
    }
  }
  function nalozZvok() {
    klic("zvok").then(function (z) {
      zvokStanje = z;
      // Med vlecenjem drsnika ali izbiro v meniju ne risemo znova - sicer bi uporabniku ukradli miško.
      var a = document.activeElement;
      if (a && (a.type === "range" || a.tagName === "SELECT") && $("r-zvok").contains(a)) return;
      if (Date.now() - zvokDotik < 1200) return;
      narisiZvok(z);
    }, function () {});
  }
  function zvokZanka() {
    clearInterval(zvokCas);
    zvokCas = setInterval(function () {
      if (S.razdelek !== "zvok") { clearInterval(zvokCas); return; }
      nalozZvok();
    }, 2000);
  }
  function zvokDrsnik(kljuc, ikona, vrednost, utisan, naGlasnost, naUtisaj) {
    var ovoj = el("div", "zvok-glasnost");
    var d = drsnik(kljuc, utisan ? "utisan" : ikona, Math.min(100, vrednost), function (v) { zvokDotik = Date.now(); naGlasnost(v); });
    d.querySelector("input").addEventListener("input", function () { zvokDotik = Date.now(); });
    var u = el("button", "gumb-utisaj" + (utisan ? " utisan" : ""), svg(utisan ? "utisan" : "zvok"));
    u.title = t("utisaj");
    u.addEventListener("click", function () { zvokDotik = 0; naUtisaj(!utisan); });
    ovoj.appendChild(d);
    ovoj.appendChild(u);
    return ovoj;
  }
  function zvokVrstica(ikona, ime, pod, izbran, desno) {
    var v = el("div", "vrstica" + (izbran ? " izbran" : ""));
    v.tabIndex = 0;
    v.innerHTML = svg(ikona) + '<span class="besedilo"><b>' + ubezi(ime) + "</b>" + (pod ? "<small>" + ubezi(pod) + "</small>" : "") + "</span>";
    var d = el("span", "dejanja");
    if (desno) d.appendChild(desno);
    v.appendChild(d);
    return v;
  }
  function narisiZvok(z) {
    z = z || { izhodi: [], vhodi: [], programi: [], link: { naprave: [], zvok: {} } };
    var link = z.link || { naprave: [], zvok: {} }, naLinku = (link.zvok || {}).naprava || "";
    // Izhodi racunalnika
    var c = $("zvokIzhodi");
    c.innerHTML = "";
    z.izhodi.forEach(function (i) {
      var izbran = i.privzeti && !naLinku;
      var pod = [t("tip_" + i.vrsta), i.podnapis].filter(function (x, k, a) {
        return x && a.indexOf(x) === k && x.toLowerCase() !== String(i.ime).toLowerCase();
      }).join(" · ");
      var v = zvokVrstica(IKONA_ZVOKA[i.vrsta] || "zvok", i.ime, pod, izbran, izbran ? el("span", "znacka", ubezi(t("vUporabi"))) : null);
      var izberi = function () {
        if (izbran) return;
        zvokDotik = 0;
        klic("zvokIzhod", [i.id]).then(function (ok) {
          if (!ok) obvesti(t("niUspelo")); else if (naLinku) obvesti(t("zvokNazaj"));
          nalozZvok(); osveziStanje();
        });
      };
      v.addEventListener("click", izberi);
      v.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); izberi(); } });
      c.appendChild(v);
    });
    if (!z.izhodi.length) c.appendChild(el("div", "prazno", ubezi(t("niUspelo"))));
    var g = $("zvokGlasnostIzhoda");
    g.innerHTML = "";
    var privzeti = z.izhodi.filter(function (i) { return i.privzeti; })[0];
    if (privzeti && !naLinku) {
      g.appendChild(zvokDrsnik("glasnost", "zvok", privzeti.glasnost, privzeti.utisan,
        function (v) { klic("zvokGlasnostIzhoda", [privzeti.id, v]).then(osveziStanje); },
        function (u) { klic("zvokUtisajIzhod", [privzeti.id, u]).then(function () { nalozZvok(); osveziStanje(); }); }));
    }
    // Naprave v Safeer Linku
    var l = $("zvokLink");
    l.innerHTML = "";
    link.naprave.forEach(function (n) {
      var tece = naLinku === n.id, caka = zvokCaka === n.id && !tece;
      var ikona = (n.platforma === "tablet" || n.platforma === "phone") ? "naprave" : "zaslon";
      var gumb;
      if (tece) {
        gumb = el("span", "dejanja");
        var st = (link.zvok.stanje === "tece") ? "zvokPredvaja" : "zvokPovezujem";
        gumb.appendChild(el("span", "znacka" + (link.zvok.stanje === "tece" ? " tece" : ""), ubezi(t(st))));
        var ust = el("button", "gumb", ubezi(t("ustavi")));
        ust.addEventListener("click", function (e) {
          e.stopPropagation();
          klic("zvokUstavi").then(function () { zvokCaka = ""; obvesti(t("zvokNazaj")); setTimeout(nalozZvok, 600); });
        });
        gumb.appendChild(ust);
      } else {
        gumb = el("button", "gumb" + (caka ? "" : " glavni"), ubezi(t(caka ? "zvokPovezujem" : "predvajajTukaj")));
        gumb.addEventListener("click", function (e) {
          e.stopPropagation();
          zvokCaka = n.id;
          narisiZvok(z);
          klic("zvokNaNapravo", [n.id]).then(function (ok) {
            if (!ok) { zvokCaka = ""; obvesti(t("niUspelo")); } else obvesti(t("zvokNaNapravoZacet", { ime: n.ime }));
            setTimeout(nalozZvok, 800); setTimeout(function () { zvokCaka = ""; nalozZvok(); }, 6000);
          });
        });
      }
      l.appendChild(zvokVrstica(ikona, n.ime, "Safeer Link", tece, gumb));
    });
    if (!link.naprave.length) l.appendChild(el("div", "prazno", ubezi(t(link.povezan ? "zvokBrezNaprav" : "zvokBrezLinka"))));
    // Programi
    var p = $("zvokProgrami");
    p.innerHTML = "";
    var izbire = z.izhodi.map(function (i) { return [i.id, i.ime]; });
    if (naLinku) izbire.push(["safeer_link_zvok", link.zvok.ime || "Safeer Link"]);
    z.programi.forEach(function (pr) {
      var v = el("div", "vrstica program" + (pr.predvaja ? "" : " tiho"));
      v.appendChild(el("span", "crka", ubezi(String(pr.ime || "?").charAt(0).toUpperCase())));
      v.appendChild(el("span", "besedilo", "<b>" + ubezi(pr.ime) + "</b><small>" + ubezi(pr.predvaja ? (pr.naslov || "") : t("zvokUstavljeno")) + "</small>"));
      var r = el("input");
      r.type = "range"; r.min = 0; r.max = 100; r.value = Math.min(100, pr.glasnost);
      r.setAttribute("aria-label", t("glasnost") + " · " + pr.ime);
      var o = el("output", "", Math.min(100, pr.glasnost) + " %");
      var zam = 0;
      r.addEventListener("input", function () {
        zvokDotik = Date.now();
        o.textContent = r.value + " %";
        clearTimeout(zam);
        zam = setTimeout(function () { klic("zvokGlasnostPrograma", [pr.id, parseInt(r.value, 10)]); }, 120);
      });
      var u = el("button", "gumb-utisaj" + (pr.utisan ? " utisan" : ""), svg(pr.utisan ? "utisan" : "zvok"));
      u.title = t("utisaj");
      u.addEventListener("click", function () { klic("zvokUtisajProgram", [pr.id, !pr.utisan]).then(nalozZvok); });
      var s = el("select");
      s.title = t("zvokIzhodPrograma");
      izbire.forEach(function (i) {
        var op = el("option", "", ubezi(i[1]));
        op.value = i[0];
        if (i[0] === pr.izhod) op.selected = true;
        s.appendChild(op);
      });
      s.addEventListener("change", function () {
        klic("zvokPremakniProgram", [pr.id, s.value]).then(function (ok) { if (!ok) obvesti(t("niUspelo")); s.blur(); nalozZvok(); });
      });
      v.appendChild(r); v.appendChild(o); v.appendChild(u);
      if (izbire.length > 1) v.appendChild(s);
      p.appendChild(v);
    });
    $("blokZvokProgrami").hidden = !z.programi.length;
    // Vhod
    var vh = $("zvokVhodi");
    vh.innerHTML = "";
    z.vhodi.forEach(function (i) {
      var v = zvokVrstica(IKONA_ZVOKA[i.vrsta] || "mikrofon", i.ime, i.podnapis, i.privzeti, i.privzeti ? el("span", "znacka", ubezi(t("vUporabi"))) : null);
      v.addEventListener("click", function () {
        if (i.privzeti) return;
        klic("zvokVhod", [i.id]).then(function (ok) { if (!ok) obvesti(t("niUspelo")); nalozZvok(); });
      });
      vh.appendChild(v);
    });
    var gv = $("zvokGlasnostVhoda");
    gv.innerHTML = "";
    var vhod = z.vhodi.filter(function (i) { return i.privzeti; })[0];
    if (vhod) {
      gv.appendChild(zvokDrsnik("mikrofon", "mikrofon", vhod.glasnost, vhod.utisan,
        function (v) { klic("zvokGlasnostVhoda", [vhod.id, v]); },
        function (u) { klic("zvokUtisajVhod", [vhod.id, u]).then(nalozZvok); }));
    }
    $("blokZvokVhod").hidden = !z.vhodi.length;
    $("gumbZvokNapredno").hidden = !z.napredno;
  }

  // ------------------------------------------------------------------ nastavitve
  var SKUPINE_NASTAVITEV = [
    ["g_videz", "paleta", ["backgrounds", "themes", "fonts", "effects", "desktop", "panel", "applets", "desklets", "extensions"]],
    ["g_zaslon", "zaslon", ["display", "nightlight", "screensaver", "sound", "power", "o:posnetek-zaslona"]],
    ["g_naprave", "naprave", ["o:omrezje", "o:bluetooth", "mouse", "keyboard", "gestures", "o:tiskalniki", "thunderbolt"]],
    ["g_sistem", "drsniki", ["user", "privacy", "default", "startup", "calendar", "notifications", "accessibility", "windows",
                            "workspaces", "hotcorner", "general", "actions", "o:jezik"]],
    ["g_vzdrzevanje", "scit", ["o:posodobitve", "o:programska-oprema", "o:gonilniki", "o:varnostne-kopije", "o:kopije-datotek",
                               "o:opravila", "o:diski", "o:sistemsko-porocilo", "o:viri-programov", "o:terminal", "o:datoteke"]]
  ];
  var IKONA_NASTAVITVE = {
    backgrounds: "slika", themes: "paleta", fonts: "dokument", display: "zaslon", nightlight: "luna", screensaver: "zakleni",
    sound: "zvok", power: "napajanje", mouse: "miska", keyboard: "tipkovnica", user: "uporabnik", privacy: "scit",
    notifications: "zvonec", calendar: "ura", startup: "ponovno", "posodobitve": "ponovno", "programska-oprema": "programi",
    "gonilniki": "program", "varnostne-kopije": "ura", "kopije-datotek": "arhiv", "opravila": "drsniki", "diski": "disk",
    "omrezje": "ethernet", "bluetooth": "bluetooth", "tiskalniki": "tiskalnik", "terminal": "program", "datoteke": "mapa",
    "posnetek-zaslona": "slika", "jezik": "splet", "viri-programov": "arhiv", "sistemsko-porocilo": "dokument",
    windows: "namizje", workspaces: "programi", desktop: "namizje", panel: "namizje", accessibility: "uporabnik"
  };
  function seznamNastavitev() {
    var r = (S.zacetek && S.zacetek.razpolozljivo) || { moduli: [], orodja: [] };
    var izhod = [];
    SKUPINE_NASTAVITEV.forEach(function (g) {
      var elementi = [];
      g[2].forEach(function (k) {
        var orodje = k.indexOf("o:") === 0, kljuc = orodje ? k.slice(2) : k;
        if ((orodje ? r.orodja : r.moduli).indexOf(kljuc) < 0) return;
        elementi.push({ modul: kljuc, ime: t((orodje ? "o_" : "m_") + kljuc), ikona: IKONA_NASTAVITVE[kljuc] || g[1] });
      });
      if (elementi.length) izhod.push({ naslov: t(g[0]), elementi: elementi });
    });
    return izhod;
  }
  function odpriNastavitev(n) {
    // Windows ze ima varna, dostopna in celovita sistemska pogleda za omrezje in zvok.
    // Ne prikazuj praznega Linux pogleda, kadar namesto njega lahko odpremo pravi Windows pogled.
    if (S.zacetek && S.zacetek.namizje === "windows" && (n.modul === "omrezje" || n.modul === "sound")) {
      obvesti(t("odpiram", { ime: n.ime }));
      klic("nastavitve", [n.modul]);
      return;
    }
    // Omrezje ima Safeer OS svojo stran; Mintovo okno ostane pod »Napredno«.
    if (n.modul === "omrezje") { pojdi("omrezje"); return; }
    // Zvok ima Safeer OS svojo stran (izhodi, programi, naprave v Linku); Mintovo okno je pod »Napredno«.
    if (n.modul === "sound") { pojdi("zvok"); return; }
    obvesti(t("odpiram", { ime: n.ime }));
    klic("nastavitve", [n.modul]).then(function (ok) { if (!ok) obvesti(t("niUspelo")); });
  }
  function naloziNastavitveBrskalnika() {
    return klic("browserSettingsGet").then(function (podatki) {
      S.brskalnikNastavitve = podatki;
      narisiNastavitveBrskalnika();
    }).catch(function () {
      var cilj = $("browserSettings");
      if (cilj) cilj.innerHTML = '<p class="browser-settings-message">' + ubezi(t("br_napaka")) + '</p>';
    });
  }
  function narisiNastavitveBrskalnika() {
    var cilj = $("browserSettings"), data = S.brskalnikNastavitve;
    if (!cilj || !data) return;
    function selectCard(key, label, options, note) {
      var html = '<div class="browser-settings-card"><label for="br-' + key + '">' + ubezi(t(label)) + '</label><select id="br-' + key + '" data-browser-setting="' + key + '">';
      options.forEach(function (o) { html += '<option value="' + ubezi(o.value) + '"' + (data[key] === o.value ? ' selected' : '') + '>' + ubezi(o.label) + '</option>'; });
      return html + '</select>' + (note ? '<small>' + ubezi(t(note)) + '</small>' : '') + '</div>';
    }
    function toggleCard(key, label, note) {
      return '<div class="browser-settings-card"><button type="button" class="stikalo" role="switch" aria-checked="' + (data[key] ? 'true' : 'false') + '" data-browser-setting="' + key + '"><span>' + ubezi(t(label)) + '</span><i></i></button>' + (note ? '<small>' + ubezi(t(note)) + '</small>' : '') + '</div>';
    }
    var engines = (data.engines || []).map(function (e) { return { value: e.id, label: e.name }; });
    var html = selectCard("search_engine", "br_isci", engines) +
      selectCard("startup", "br_zagon", [{ value: "home", label: t("br_domov") }, { value: "restore", label: t("br_obnovi") }]) +
      '<div class="browser-settings-card"><span class="browser-setting-title">' + ubezi(t("br_zascita")) + '</span>' +
      [["adblock_enabled", "br_oglasi"], ["adguard_protection_enabled", "br_adguard"], ["tracking_protection_enabled", "br_sledenje"], ["gpc_dnt_enabled", "br_gpc"], ["block_third_party_cookies", "br_piskotki"]].map(function (x) { return '<button type="button" class="stikalo" role="switch" aria-checked="' + (data[x[0]] ? 'true' : 'false') + '" data-browser-setting="' + x[0] + '"><span>' + ubezi(t(x[1])) + '</span><i></i></button>'; }).join("") + '</div>' +
      selectCard("doh_provider", "br_dns", [{ value: "cloudflare", label: "Cloudflare" }, { value: "quad9", label: "Quad9" }, { value: "google", label: "Google" }, { value: "custom", label: t("br_customDns") }], "br_dnsPo") +
      (data.doh_provider === "custom" ? '<div class="browser-settings-card"><label for="br-custom-doh-url">' + ubezi(t("br_customDns")) + '</label><input id="br-custom-doh-url" type="url" inputmode="url" autocomplete="url" placeholder="https://dns.example/dns-query" value="' + ubezi(data.custom_doh_url || "") + '" data-browser-setting="custom_doh_url"><small>' + ubezi(t("br_https")) + '</small></div>' : '') +
      toggleCard("force_dark_mode", "br_temno") +
      toggleCard("hardware_acceleration", "br_pospesevanje", "br_restart") +
      toggleCard("ask_download_location", "br_prenos") +
      '<div class="browser-settings-card"><span class="browser-setting-title">' + ubezi(t("br_stats")) + '</span><div class="browser-settings-stats"><span><b>' + Number(data.total_ads_blocked || 0).toLocaleString() + '</b>' + ubezi(t("br_oglasiBlokirani")) + '</span><span><b>' + Number(data.total_threats_blocked || 0).toLocaleString() + '</b>' + ubezi(t("br_groznjeBlokirane")) + '</span></div><button type="button" class="gumb" id="browserClearData" style="margin-top:14px">' + ubezi(t("br_pocisti")) + '</button></div>' +
      '<p class="browser-settings-message" id="browserSettingsMessage" aria-live="polite"></p>';
    cilj.innerHTML = html;
    cilj.querySelectorAll("[data-browser-setting]").forEach(function (control) {
      var save = function () {
        var value = control.type === "checkbox" ? control.checked : control.tagName === "BUTTON" ? control.getAttribute("aria-checked") !== "true" : control.value;
        if (control.tagName === "BUTTON") control.setAttribute("aria-checked", value ? "true" : "false");
        if (control.dataset.browserSetting === "custom_doh_url" && value && !/^https:\/\//i.test(value)) {
          var msg = $("browserSettingsMessage"); if (msg) msg.textContent = t("br_https"); return;
        }
        klic("browserSettingsSet", [control.dataset.browserSetting, value]).then(function (result) {
          S.brskalnikNastavitve = result;
          narisiNastavitveBrskalnika();
          var msg = $("browserSettingsMessage"); if (msg) msg.textContent = t("br_shranjeno");
        }).catch(function () { var msg = $("browserSettingsMessage"); if (msg) msg.textContent = t("br_napaka"); });
      };
      control.addEventListener(control.tagName === "BUTTON" ? "click" : "change", save);
    });
    var clear = $("browserClearData");
    if (clear) clear.addEventListener("click", function () {
      if (!window.confirm(t("br_pocistiPotrdi"))) return;
      klic("browserClearData").then(function () { var msg = $("browserSettingsMessage"); if (msg) msg.textContent = t("br_pocisceno"); }, function () { var msg = $("browserSettingsMessage"); if (msg) msg.textContent = t("br_napaka"); });
    });
  }
  function narisiNastavitve() {
    kontrole($("hitreNastavitve"), false);
    naloziNastavitveBrskalnika();
    $("stikaloCelozaslonsko").setAttribute("aria-checked", S.zacetek && S.zacetek.celozaslonsko ? "true" : "false");
    $("stikaloSamozagon").setAttribute("aria-checked", S.zacetek && S.zacetek.samozagon ? "true" : "false");
    var cilj = $("skupineNastavitev");
    cilj.innerHTML = "";
    seznamNastavitev().forEach(function (g) {
      cilj.appendChild(el("h2", "", ubezi(g.naslov)));
      var m = el("div", "nastavitve-mreza");
      g.elementi.forEach(function (n) {
        var b = el("button", "nastavitev", svg(n.ikona) + "<span>" + ubezi(n.ime) + "</span>");
        b.addEventListener("click", function () { odpriNastavitev(n); });
        m.appendChild(b);
      });
      cilj.appendChild(m);
    });
    $("oSistemu").textContent = t("razlicica", { v: (S.zacetek && S.zacetek.razlicica) || "" }) +
      (S.zacetek ? " · " + S.zacetek.racunalnik : "");
    if (!S.stanje) klic("stanje").then(function (s) { narisiStanje(s); kontrole($("hitreNastavitve"), false); }, function () {});
  }

  // ------------------------------------------------------------------ napajanje
  var potrjuje = null, potrjujeCas = 0;
  function odpriNapajanje() {
    zapriSloje();
    potrjuje = null;
    narisiNapajanje();
    $("slojNapajanje").classList.add("viden");
  }
  function narisiNapajanje() {
    var p = $("napajanje");
    p.innerHTML = "";
    var mint = el("button", "", svg("namizje") + "<span>" + ubezi(t("nazajVMint")) + "</span>");
    mint.addEventListener("click", odpriMint);
    p.appendChild(mint);
    [["zakleni", "zakleni", false], ["spanje", "luna", false], ["odjava", "odjava", true],
     ["ponovni-zagon", "ponovno", true], ["izklop", "napajanje", true]].forEach(function (d) {
      var kljuc = d[0] === "ponovni-zagon" ? "ponovniZagon" : d[0];
      var b = el("button", potrjuje === d[0] ? "potrdi" : "", svg(d[1]) + "<span>" +
        ubezi(potrjuje === d[0] ? t("potrdi") : t(kljuc)) + "</span>");
      b.addEventListener("click", function () {
        if (d[2] && potrjuje !== d[0]) {
          potrjuje = d[0];
          clearTimeout(potrjujeCas);
          potrjujeCas = setTimeout(function () { potrjuje = null; narisiNapajanje(); }, 4000);
          narisiNapajanje();
          return;
        }
        zapriSloje();
        klic("napajanje", [d[0]]);
      });
      p.appendChild(b);
    });
  }

  // ------------------------------------------------------------------ nazaj v Linux Mint
  function odpriMint() {
    zapriSloje();
    $("mintZaStalno").hidden = !(S.zacetek && S.zacetek.samozagon);
    $("slojMint").classList.add("viden");
    setTimeout(function () { $("mintSamoTokrat").focus(); }, 30);
  }

  // ------------------------------------------------------------------ iskanje
  var iskanjeZamik = 0, iskanjeStevec = 0;
  function jeNaslov(s) { return /^(https?:\/\/)?[\w-]+(\.[\w-]+)+(:\d+)?(\/\S*)?$/i.test(s) && !/\s/.test(s); }
  function ujemanje(besedilo, niz) {
    besedilo = String(besedilo || "").toLowerCase();
    if (!besedilo) return 0;
    if (besedilo.indexOf(niz) === 0) return 3;
    if (besedilo.indexOf(" " + niz) >= 0) return 2;
    return besedilo.indexOf(niz) >= 0 ? 1 : 0;
  }
  function zadetek(ikonaEl, naslov, pod, ob) {
    var b = el("button", "zadetek");
    if (typeof ikonaEl === "string") b.innerHTML = svg(ikonaEl); else b.appendChild(ikonaEl);
    b.appendChild(el("div", "", "<b>" + ubezi(naslov) + "</b>" + (pod ? "<span>" + ubezi(pod) + "</span>" : "")));
    b.addEventListener("click", function () { zapriSloje(); ob(); });
    return b;
  }
  function isci() {
    var niz = $("iskanje").value.trim();
    var sloj = $("slojIskanje");
    if (!niz) { sloj.classList.remove("viden"); return; }
    $("slojHitro").classList.remove("viden");
    $("slojNapajanje").classList.remove("viden");
    sloj.classList.add("viden");
    var n = niz.toLowerCase();
    var z = $("zadetki");
    z.innerHTML = "";
    // Programi
    var programi = S.programi.concat(vsiProgramiNaprav()).map(function (p) {
      var ocena = ujemanje(p.ime, n) * 10 + ujemanje(p.splosno, n) * 3 + ujemanje((p.kljucne || []).join(" "), n) * 2 +
        ujemanje(p.opis, n);
      if (ocena && p.naprava) ocena -= 1;          // program tega racunalnika ima prednost pred istim na napravi
      return { p: p, ocena: ocena + (ocena ? Math.min(5, p.uporaba || 0) : 0) };
    }).filter(function (x) { return x.ocena > 0; }).sort(function (a, b) { return b.ocena - a.ocena; }).slice(0, 6);
    if (programi.length) {
      z.appendChild(el("h4", "", ubezi(t("zProgrami"))));
      programi.forEach(function (x) {
        var n2 = x.p.naprava ? S.naprave.find(function (y) { return y.id === x.p.naprava; }) : null;
        z.appendChild(zadetek(slikaAliCrka(x.p.ikona, x.p.ime), x.p.ime, n2 ? n2.ime : x.p.opis, function () { zazeni(x.p); }));
      });
    }
    // Nastavitve
    var nastavitve = [];
    seznamNastavitev().forEach(function (g) {
      g.elementi.forEach(function (e) { if (ujemanje(e.ime, n)) nastavitve.push({ e: e, g: g.naslov }); });
    });
    if (nastavitve.length) {
      z.appendChild(el("h4", "", ubezi(t("zNastavitve"))));
      nastavitve.slice(0, 5).forEach(function (x) {
        z.appendChild(zadetek(x.e.ikona, x.e.ime, x.g, function () { odpriNastavitev(x.e); }));
      });
    }
    // Splet
    z.appendChild(el("h4", "", ubezi(t("isciSplet"))));
    if (jeNaslov(niz)) {
      var naslov = normalizirajNaslov(niz);
      z.appendChild(zadetek("splet", t("odpriNaslov"), naslov, function () { otvoriSpletnoStran(naslov); }));
    }
    z.appendChild(zadetek("isci", "“" + niz + "”", t("isciSplet"), function () { odpriSpletnoIskanje(niz); }));
    // Datoteke (pocasneje, z zamikom)
    var mestoDatotek = el("div");
    z.appendChild(mestoDatotek);
    oznaciPrvega();
    clearTimeout(iskanjeZamik);
    var moj = ++iskanjeStevec;
    if (n.length >= 2) {
      mestoDatotek.appendChild(el("h4", "", ubezi(t("zDatoteke")) + ' <span style="opacity:.6;letter-spacing:0;text-transform:none">' + ubezi(t("iscem")) + "</span>"));
      iskanjeZamik = setTimeout(function () {
        klic("isciDatoteke", [niz]).then(function (seznam) {
          if (moj !== iskanjeStevec) return;
          mestoDatotek.innerHTML = "";
          seznam = (seznam || []).slice(0, 8);
          if (!seznam.length) return;
          mestoDatotek.appendChild(el("h4", "", ubezi(t("zDatoteke"))));
          seznam.forEach(function (d) {
            mestoDatotek.appendChild(zadetek(IKONA_VRSTE[d.vrsta] || "datoteka", d.ime, skrajsajPot(d.pot), function () {
              if (d.mapa) { pojdi("datoteke"); odpriMapo(d.pot); } else klic("odpriDatoteko", [d.pot]);
            }));
          });
        }, function () { mestoDatotek.innerHTML = ""; });
      }, 260);
    }
  }
  function zadetki() { return Array.prototype.slice.call(document.querySelectorAll("#zadetki .zadetek")); }
  function oznaciPrvega() {
    var vsi = zadetki();
    vsi.forEach(function (b, i) { b.classList.toggle("aktiven", i === 0); });
  }
  function premakniIzbiro(smer) {
    var vsi = zadetki();
    if (!vsi.length) return;
    var i = vsi.findIndex(function (b) { return b.classList.contains("aktiven"); });
    i = Math.max(0, Math.min(vsi.length - 1, i + smer));
    vsi.forEach(function (b, j) { b.classList.toggle("aktiven", j === i); });
    vsi[i].scrollIntoView({ block: "nearest" });
  }

  function zapriSloje() {
    document.querySelectorAll(".sloj").forEach(function (s) { s.classList.remove("viden"); });
    if ($("iskanje").value && document.activeElement !== $("iskanje")) $("iskanje").value = "";
  }

  // Nova naprava se pridruzuje Safeer Linku: kodo, ki jo vpise nanjo, pokazemo tudi tu (velika,
  // da jo uporabnik prebere z razdalje). Okno se zapre samo po 5 minutah ali ob kliku.
  function pokaziKodoPrijave(p) {
    var koda = String(p.koda || "");
    if (!/^[0-9]{6}$/.test(koda)) return;
    var staro = document.getElementById("slojKodaPrijave");
    if (staro) staro.remove();
    var sloj = el("div", "sloj-koda-prijave");
    sloj.id = "slojKodaPrijave";
    var okno = el("div", "koda-prijave-okno");
    var h = el("h2"); h.textContent = "Nova naprava";
    var o = el("p"); o.textContent = (p.ime || "Naprava") + " se želi pridružiti tvojemu Safeer Linku. Na njej vpiši to kodo:";
    var k = el("div", "koda-prijave"); k.textContent = koda.slice(0, 3) + " " + koda.slice(3);
    var g = el("button", "koda-prijave-gumb"); g.textContent = "V redu";
    g.addEventListener("click", function () { sloj.remove(); });
    okno.appendChild(h); okno.appendChild(o); okno.appendChild(k); okno.appendChild(g);
    sloj.appendChild(okno);
    document.body.appendChild(sloj);
    setTimeout(function () { if (sloj.parentNode) sloj.remove(); }, 300000);
  }

  // Nova naprava v Safeer Linku: kaj sme na tem racunalniku. Brez izbire nima dostopa (varno privzeto),
  // zato vprasamo takoj, ko se pojavi - ne sele v Safeer Control, kamor uporabnik morda nikoli ne gre.
  var cakajocaDovoljenja = [];
  function vprasajZaDovoljenje(n) {
    if (cakajocaDovoljenja.some(function (x) { return x.id === n.id; })) return;
    cakajocaDovoljenja.push(n);
    if (cakajocaDovoljenja.length === 1) pokaziDovoljenje();
  }
  function pokaziDovoljenje() {
    var n = cakajocaDovoljenja[0];
    if (!n) return;
    var sloj = el("div", "sloj-koda-prijave");
    var okno = el("div", "koda-prijave-okno");
    var h = el("h2"); h.textContent = "Nova naprava v Safeer Linku";
    var o = el("p"); o.textContent = "Kaj sme " + (n.ime || n.id) + " na tem računalniku?";
    okno.appendChild(h); okno.appendChild(o);
    function naprej() {
      sloj.remove();
      cakajocaDovoljenja.shift();
      pokaziDovoljenje();
    }
    [["polno", "Vse: programi, datoteke in zaslon"], ["izbrano", "Samo datoteke"], ["zaslon", "Samo ogled zaslona"]].forEach(function (m) {
      var g = el("button", "vrstica"); g.textContent = m[1];
      g.addEventListener("click", function () {
        klic("nastaviDovoljenje", [n.id, m[0]]).then(function (ok) {
          obvesti(ok ? ((n.ime || "Naprava") + ": dovoljenje shranjeno.") : t("niUspelo"));
        });
        naprej();
      });
      okno.appendChild(g);
    });
    var z = el("button", "koda-prijave-gumb"); z.textContent = "Ne zdaj";
    z.addEventListener("click", naprej);
    okno.appendChild(z);
    sloj.appendChild(okno);
    document.body.appendChild(sloj);
  }

  // ------------------------------------------------------------------ dogodki iz safeer_os.py
  window.safeerOsDogodek = function (vrsta, podatki) {
    if (vrsta === "stanje") narisiStanje(podatki);
    if (vrsta === "okna") narisiOkna(podatki);
    if (vrsta === "pojdi") window.safeerOsPojdi(podatki);
    if (vrsta === "mediaFallback" && podatki) predvajajHtml(podatki, 0);
    if (vrsta === "mediaOsvezen" && S.razdelek === "media") naloziMedia();
    if (vrsta === "kodaPrijave" && podatki) pokaziKodoPrijave(podatki);
    if (vrsta === "zaslonZNaprave" && podatki) {
      obvesti(podatki.dejanje === "stop" ? ("Naprava " + (podatki.od || "") + " je končala deljenje zaslona.")
                                         : ("Zaslon naprave " + (podatki.od || "") + " se odpira tukaj."));
    }
    if (vrsta === "dovoljenjeZahtevano" && podatki && podatki.id) vprasajZaDovoljenje(podatki);
    if (vrsta === "prejetaDatoteka" && podatki) {
      obvesti(podatki.uspeh ? ("Prejeto z naprave " + podatki.od + ": " + podatki.ime + " (mapa Prenosi)")
                            : ("Datoteke " + podatki.ime + " ni bilo mogoče prevzeti: " + (podatki.napaka || "")));
    }
    if (vrsta === "posiljanjeKoncano" && podatki) {
      obvesti(podatki.uspeh ? (podatki.ime + " je poslana.") : (podatki.napaka || "Pošiljanje ni uspelo."));
    }
    if (vrsta === "naprave") {
      if (S.razdelek === "programi") nalozNaprave();
      if (S.razdelek === "datoteke") nalozNapraveSDatoteki();
    }
    if (vrsta === "fokus") {
      osveziOkna();
      osveziStanje();
      osveziPovezavo();
      narisiNedavneDomov();
      if (S.razdelek === "datoteke") nalozNapraveSDatoteki();
    }
  };

  // ------------------------------------------------------------------ zacetek
  function poveziDogodke() {
    document.querySelectorAll("#meni button").forEach(function (b) {
      b.addEventListener("click", function () { pojdi(b.getAttribute("data-razdelek")); });
    });
    document.querySelectorAll("[data-pojdi]").forEach(function (b) {
      b.addEventListener("click", function () { pojdi(b.getAttribute("data-pojdi")); });
    });
    on("kBrskalnik", "click", function () {
      var b = S.programi.find(function (p) { return p.id === "safeer-browser.desktop"; }) ||
              S.programi.find(function (p) { return /safeer/i.test(p.id) && p.skupina === "splet"; });
      if (b) zazeni(b); else klic("iskanjeSplet", [""]);
    });
    on("gumbControl", "click", function () {
      obvesti(t("odpiram", { ime: "Safeer Control" }));
      // Povezan racunalnik: Control z napravami; sicer prijavno okno (QR / koda / brez povezave).
      klic(S.povezava.stanje === "povezan" ? "control" : "prijava");
    });
    on("gumbOdjava", "click", function () {
      if (!odjavaPotrjujem) {
        odjavaPotrjujem = true;
        clearTimeout(odjavaCas);
        odjavaCas = setTimeout(function () { odjavaPotrjujem = false; narisiPovezavo(); }, 5000);
        narisiPovezavo();
        return;
      }
      odjavaPotrjujem = false;
      klic("odjava").then(function (ok) {
        obvesti(t(ok ? "odjavljen" : "niUspelo"));
        setTimeout(osveziPovezavo, 2500);
        setTimeout(osveziPovezavo, 6000);
      });
    });
    on("domControl", "click", function () { var gc = $("gumbControl"); if (gc) gc.click(); });
    on("gumbStanje", "click", function () {
      if ($("slojHitro") && $("slojHitro").classList.contains("viden")) zapriSloje(); else odpriHitro();
    });
    on("gumbNapajanje", "click", function () {
      if ($("slojNapajanje") && $("slojNapajanje").classList.contains("viden")) zapriSloje(); else odpriNapajanje();
    });
    on("stikaloCelozaslonsko", "click", function () {
      var b = $("stikaloCelozaslonsko");
      if (!b) return;
      var nov = b.getAttribute("aria-checked") !== "true";
      b.setAttribute("aria-checked", nov ? "true" : "false");
      if (S.zacetek) S.zacetek.celozaslonsko = nov;
      klic("celozaslonsko", [nov]);
    });
    on("gumbNamizje", "click", function () { klic("namizje"); });
    on("stikaloSamozagon", "click", function () {
      var b = $("stikaloSamozagon");
      if (!b) return;
      var nov = b.getAttribute("aria-checked") !== "true";
      b.setAttribute("aria-checked", nov ? "true" : "false");
      klic("samozagon", [nov]).then(function (zdaj) {
        if (S.zacetek) S.zacetek.samozagon = !!zdaj;
        b.setAttribute("aria-checked", zdaj ? "true" : "false");
      });
    });
    on("stikaloZaupaj", "click", function () {
      var b = $("stikaloZaupaj");
      if (!b) return;
      var nov = b.getAttribute("aria-checked") !== "true";
      S.povezava.zaupana = nov;
      narisiPovezavo();
      klic("zaupanje", [nov]).then(function () { setTimeout(osveziPovezavo, 600); });
    });
    on("gumbNazajVMint", "click", odpriMint);
    on("stikaloWifiOmrezje", "click", function () {
      var b = $("stikaloWifiOmrezje");
      if (!b) return;
      var nov = b.getAttribute("aria-checked") !== "true";
      b.setAttribute("aria-checked", nov ? "true" : "false");
      klic("wifi", [nov]).then(function () { setTimeout(function () { nalozOmrezje(true); }, 1500); });
    });
    on("gumbOmrezjeOsvezi", "click", function () { nalozOmrezje(true); });
    on("gumbOmrezjeNazaj", "click", function () { pojdi("nastavitve"); });
    on("gumbOmrezjeNapredno", "click", function () {
      obvesti(t("odpiram", { ime: t("napredno") }));
      klic("nastavitve", ["omrezje"]);
    });
    on("stanjeOmrezje", "click", function (e) { e.stopPropagation(); zapriSloje(); pojdi("omrezje"); });
    on("stanjeZvok", "click", function (e) { e.stopPropagation(); zapriSloje(); pojdi("zvok"); });
    on("stanjeZvok", "contextmenu", function (e) { e.preventDefault(); e.stopPropagation(); zapriSloje(); pojdi("zvok"); });
    on("gumbZvokNazaj", "click", function () { pojdi("nastavitve"); });
    on("gumbNedavnePocistiDomov", "click", pocistiNedavne);
    on("gumbZvokNapredno", "click", function () {
      obvesti(t("odpiram", { ime: t("napredno") }));
      klic("nastavitve", ["sound"]);
    });
    on("mintPreklici", "click", zapriSloje);
    on("mintSamoTokrat", "click", function () { klic("nazajVMint", [false]); });
    on("mintZaStalno", "click", function () { klic("nazajVMint", [true]); });
    document.querySelectorAll(".sloj .tancica").forEach(function (t_) { t_.addEventListener("click", function () {
      if ($("iskanje")) $("iskanje").value = "";
      zapriSloje();
    }); });
    on("dodajPreklici", "click", zapriSloje);
    // Gumb "+ Dodaj" na kartici Spletne aplikacije (nova domaca stran).
    on("gumbOdpriDodajApp", "click", odpriDodaj);
    on("gumbPocistiNedavne", "click", function () {
      S.nedavneApp = [];
      klic("shraniNedavneApp", [[]]).catch(function () {});
      narisiDomaceNedavne();
    });
    on("vecAppZapri", "click", zapriSloje);
    on("vecAppDodaj", "click", function () { zapriSloje(); odpriDodaj(); });
    on("obrazecDodaj", "submit", function (e) {
      e.preventDefault();
      var naslov = normalizirajNaslov($("dodajNaslov").value);
      if (!naslov) { $("dodajNaslov").focus(); return; }
      var ime = $("dodajIme").value.trim() || new URL(naslov).hostname.replace(/^www\./, "");
      shraniSpletne(spletne().concat([{ ime: ime.slice(0, 40), url: naslov }]).slice(0, 24));
      zapriSloje();
    });
    on("spletIskalnik", "submit", function (e) {
      e.preventDefault();
      var vnos = $("spletVnos");
      if (vnos && vnos.value.trim()) odpriSpletnoIskanje(vnos.value);
    });
    var iskanje = $("iskanje");
    if (iskanje) {
      iskanje.addEventListener("input", isci);
      iskanje.addEventListener("keydown", function (e) {
        if (e.key === "ArrowDown") { e.preventDefault(); premakniIzbiro(1); }
        else if (e.key === "ArrowUp") { e.preventDefault(); premakniIzbiro(-1); }
        else if (e.key === "Enter") {
          var a = document.querySelector("#zadetki .zadetek.aktiven");
          if (a) { e.preventDefault(); a.click(); iskanje.value = ""; iskanje.blur(); }
        }
      });
      iskanje.addEventListener("focus", function () { if (iskanje.value) isci(); });
    }
    // Kot meni Start: kar zacnes tipkati, gre v iskanje.
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        var odprt = document.querySelector(".sloj.viden");
        if (odprt || iskanje.value) { iskanje.value = ""; zapriSloje(); iskanje.blur(); }
        else pojdi("domov");
        return;
      }
      var v = document.activeElement;
      if (v && (v.tagName === "INPUT" || v.tagName === "TEXTAREA")) return;
      if (e.ctrlKey || e.altKey || e.metaKey) return;
      if (e.key && e.key.length === 1 && e.key !== " ") {
        e.preventDefault();
        iskanje.focus();
        iskanje.value += e.key;
        isci();
      }
    });
  }

  function zacni() {
    if (/[?&]namizje=1/.test(location.search)) document.body.classList.add("namizje");
    prevedi();
    poveziDogodke();
    osveziUro();
    setInterval(osveziUro, 1000);
    narisiDomov();
    narisiPovezavo();
    if (!most) return;
    klic("zacetek").then(function (z) {
      S.zacetek = z;
      prilagodiPlatformo(z.namizje);
      if (BESEDILA_OS[z.jezik]) jezik = z.jezik;
      prevedi();
      if (Array.isArray(z.spletne)) S.spletne = z.spletne;
      if (Array.isArray(z.nedavne_app)) S.nedavneApp = z.nedavne_app;
      if (z.ozadje) $("ozadje").style.backgroundImage = 'url("' + z.ozadje.replace(/"/g, "%22") + '")';
      var ime = String(z.ime || "");
      if ($("imeUporabnika")) $("imeUporabnika").textContent = ime;
      if ($("imeRacunalnika")) $("imeRacunalnika").textContent = z.racunalnik || "";
      if (z.sistem && $("sistemIme")) $("sistemIme").textContent = z.sistem;
      if ($("sistemRacunalnik")) $("sistemRacunalnik").textContent = z.racunalnik || "";
      if ($("zacetnica")) $("zacetnica").textContent = (ime.trim().charAt(0) || "S").toUpperCase();
      S.povezava = z.povezava || S.povezava;
      narisiPovezavo();
      osveziUro();
      narisiMape();
      narisiDomov();
      narisiSpletnoZacetno();
      nalozPrograme();
      osveziStanje();
      osveziOkna();
      narisiNedavneDomov();
    }, function () {});
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", zacni); else zacni();
  // ------------------------------------------------------------------ Safeer Media
  // En katalog ne glede na vir. Zaledje zdruzi dvojnike in izbere najboljsi tok;
  var media = { katalog: [], viri: [], filter: "vse", genre: "", query: "", page: 1, skupaj_strani: 1, aktivni: null, zahteva: 0, timer: 0 };
  function mediaIkona(vrsta) {
    if (vrsta === "glasba") return "glasba";
    if (vrsta === "radio") return "radio";
    if (vrsta === "serija") return "serija";
    if (vrsta === "tv-v-zivo") return "tv-v-zivo";
    return "film";
  }
  function mediaOznaka(vrsta) {
    if (vrsta === "glasba") return t("mediaGlasba");
    if (vrsta === "video") return "Video";
    if (vrsta === "slika") return "Slika";
    if (vrsta === "podcast") return "Podcast";
    if (vrsta === "radio") return "Radio";
    if (vrsta === "tv-v-zivo") return "TV v živo";
    return t(vrsta === "serija" ? "mediaSerije" : "mediaFilmi");
  }

  function narisiStranjevanje() {
    var c = $("mediaStranjevanje"); if (!c) return; c.innerHTML = "";
    if (media.skupaj_strani <= 1) return;
    var prev = el("button", "gumb", "◀ Prejšnja stran");
    prev.disabled = media.page <= 1;
    prev.onclick = function () {
      if (media.page > 1) { media.page--; naloziMedia(); $("mediaMreza").scrollIntoView({behavior:"smooth", block:"start"}); }
    };
    var info = el("span", "stran-info", "Stran " + media.page + " od " + media.skupaj_strani);
    var next = el("button", "gumb", "Naslednja stran ▶");
    next.disabled = media.page >= media.skupaj_strani;
    next.onclick = function () {
      if (media.page < media.skupaj_strani) { media.page++; naloziMedia(); $("mediaMreza").scrollIntoView({behavior:"smooth", block:"start"}); }
    };
    c.appendChild(prev); c.appendChild(info); c.appendChild(next);
  }

  function narisiMedia() {
    var mreza = $("mediaMreza"); if (!mreza) return; mreza.innerHTML = "";
    var zanriEl = $("mediaZanri");
    if (zanriEl) {
      var prikaziZanre = (media.filter === "vse" || media.filter === "film" || media.filter === "serija");
      zanriEl.style.display = prikaziZanre ? "flex" : "none";
    }
    var iskano = media.query.trim().toLocaleLowerCase();
    var list = media.katalog.filter(function (x) {
      if (media.filter !== "vse" && x.vrsta !== media.filter) return false;
      if (!iskano) return true;
      return [x.naslov, x.izvajalec, x.opis].join(" ").toLocaleLowerCase().indexOf(iskano) >= 0;
    });
    $("mediaPrazno").hidden = !!list.length;
    $("mediaPovzetek").textContent = t("mediaZadetkov", { n: list.length }) + (media.skupaj_strani > 1 ? " · Stran " + media.page + " od " + media.skupaj_strani : "");
    if (media.filter === "radio" || media.filter === "video" || media.filter === "glasba") list.sort(function (a, b) {
      return (a.skupina || a.izvajalec || "").localeCompare(b.skupina || b.izvajalec || "");
    });
    var mediaZadnjaSkupina = "";
    list.forEach(function (x) {
      var skupina = x.skupina || (media.filter === "glasba" ? x.izvajalec : "");
      if ((media.filter === "radio" || media.filter === "video" || media.filter === "glasba") && skupina && skupina !== mediaZadnjaSkupina) {
        mediaZadnjaSkupina = skupina;
        mreza.appendChild(el("h3", "media-skupina", ubezi(mediaZadnjaSkupina)));
      }
      var card = el("button", "media-kartica");
      card.setAttribute("aria-label", (x.naslov || "Safeer Media") + " — " + mediaOznaka(x.vrsta));
    if (x.slika) {
        var image = document.createElement("img"); image.alt = ""; image.loading = "lazy"; image.src = x.slika;
        image.onerror = function () { image.replaceWith(el("span", "media-brez-slike", svg(mediaIkona(x.vrsta)))); };
        card.appendChild(image);
      } else card.appendChild(el("span", "media-brez-slike", svg(mediaIkona(x.vrsta))));
      var data = el("span", "media-podatki");
      data.appendChild(el("b", "", ubezi(x.naslov || "")));
      var meta = el("span", "media-meta");
      var metaOznaka = mediaOznaka(x.vrsta);
      if (x.v_zivo) metaOznaka += " · V ŽIVO";
      if (x.codec || x.bitrate) metaOznaka += " · " + [x.codec, x.bitrate ? x.bitrate + " kb/s" : ""].filter(Boolean).join(" ");
      if (x.vrsta === "serija" && (x.sezona || x.epizoda)) {
        metaOznaka += " · S" + String(x.sezona || 1).padStart(2, "0") + "E" + String(x.epizoda || 1).padStart(2, "0");
      }
      if (x.leto) metaOznaka += " · " + x.leto;
      meta.appendChild(el("span", "", ubezi(metaOznaka)));
      if (x.stevilo_razlicic > 1) meta.appendChild(el("span", "", ubezi(t("mediaRazlicic", { n: x.stevilo_razlicic }))));
      data.appendChild(meta); card.appendChild(data);
      card.appendChild(el("span", "media-kakovost", ubezi(x.kakovost || "1080p")));
      if (Number(x.ocena || 0) > 0) card.appendChild(el("span", "media-ocena", "★ " + Number(x.ocena).toFixed(1)));
      card.onclick = function () {
        if (x.tmdb_id || x.vrsta === "serija" || (x.vrsta === "film" && !x.peertube_uuid)) {
          odpriMediaPodrobnosti(x.id);
        } else {
          odpriMedia(x.id);
        }
      };
      mreza.appendChild(card);
    });
    narisiStranjevanje();
    narisiMediaVire();
  }
  function narisiMediaVire() {
    var cilj = $("mediaViri"); if (!cilj) return; cilj.innerHTML = "";
    if (!media.viri.length) { cilj.appendChild(el("div", "prazno", ubezi(t("mediaBrezVirov")))); return; }
    media.viri.forEach(function (source) {
      var row = el("div", "media-vir"); row.innerHTML = svg("splet");
      var info = el("div"); info.appendChild(el("b", "", ubezi(source.ime || source.url)));
      var status = source.napaka ? source.napaka : (source.vrsta === "streznik"
        ? "Osebni strežnik · " + (source.ponudnik || "")
        : (source.tip === "predvajalni_vir"
        ? "Predvajalni vir · " + t("mediaVirElementov", { n: source.stevilo || 0 })
        : t("mediaVirElementov", { n: source.stevilo || 0 })));
      info.appendChild(el("small", source.napaka ? "media-vir-napaka" : "", ubezi(status + " · " + source.url)));
      row.appendChild(info);
      var refresh = el("button", "gumb-ikona", svg("ponovno")); refresh.title = t("mediaOsvezi");
      refresh.onclick = function () { osveziMediaVir(source.id); }; row.appendChild(refresh);
      var remove = el("button", "gumb-ikona", svg("x")); remove.title = t("odstrani");
      remove.onclick = function () { klic("mediaOdstraniVir", [source.id]).then(naloziMedia); }; row.appendChild(remove);
      cilj.appendChild(row);
    });
  }
  function predvajajHtml(item, index) {
    var variants = item.razlicice && item.razlicice.length ? item.razlicice : [{ url:item.url, vir:item.vir, kakovost:item.kakovost, vrsta:item.vrsta }];
    var variant = variants[index || 0] || variants[0], audio = item.vrsta === "glasba" || item.vrsta === "radio" || item.vrsta === "podcast";
    var url = variant.url || "";
    var isDirectMedia = /\.(mp4|mkv|webm|avi|mov|m4v|mp3|flac|ogg|opus|m4a|aac|wav|m3u8)($|\?)/i.test(url) || url.startsWith("file:") || /mpegurl/i.test(variant.mime || item.mime || "");
    var video = $("mediaVideo"), playerAudio = $("mediaAudio"), iframe = $("mediaIframe"), playerImage = $("mediaSlika");

    if (media.timer) { window.clearTimeout(media.timer); media.timer = 0; }

    if (video) { video.pause(); video.removeAttribute("src"); video.hidden = true; video.style.display = "none"; }
    if (playerAudio) { playerAudio.pause(); playerAudio.removeAttribute("src"); playerAudio.hidden = true; playerAudio.style.display = "none"; }
    if (iframe) { iframe.src = "about:blank"; iframe.hidden = true; }
    if (playerImage) { playerImage.removeAttribute("src"); playerImage.hidden = true; }

    var pl = $("mediaPredvajalnik");
    if (pl) { pl.hidden = false; pl.classList.remove("kino"); }
    var napakaEl = $("mediaNapaka");
    napakaEl.hidden = true;
    napakaEl.classList.remove("media-opozorilo");
    napakaEl.textContent = t("mediaNapaka");
    $("mediaPredvajalnikNaslov").textContent = item.naslov || "Safeer Media";

    var metaSeznam = [item.izvajalec];
    if (item.vrsta === "serija" && (item.sezona || item.epizoda)) {
      metaSeznam.push("S" + String(item.sezona || 1).padStart(2, "0") + "E" + String(item.epizoda || 1).padStart(2, "0"));
    }
    metaSeznam.push(item.leto, variant.vir, variant.kakovost);
    $("mediaPredvajalnikMeta").textContent = metaSeznam.filter(Boolean).join(" · ");

    function poskusiNaslednjo() {
      var naslednja = (index || 0) + 1;
      if (naslednja < variants.length) {
        predvajajHtml(item, naslednja);
        return true;
      }
      return false;
    }

    if (item.vrsta === "slika" && playerImage) {
      playerImage.hidden = false;
      playerImage.src = url;
    } else if (isDirectMedia) {
      var player = audio ? playerAudio : video;
      if (player) {
        player.hidden = false;
        player.style.display = "block";
        player.src = url;
        player.load();
        try {
          var shranjenCas = Number(localStorage.getItem("safeer_media_progress_" + (item.id || url)) || 0);
          if (shranjenCas > 3) player.currentTime = shranjenCas;
          player.ontimeupdate = function () {
            if (player.currentTime > 3) localStorage.setItem("safeer_media_progress_" + (item.id || url), String(Math.floor(player.currentTime)));
          };
        } catch (e) {}
        player.onerror = function () {
          if (media.timer) window.clearTimeout(media.timer);
          media.timer = 0;
          if (!poskusiNaslednjo()) $("mediaNapaka").hidden = false;
        };
        player.play().catch(function () {});
        if (navigator.mediaSession) {
          try { navigator.mediaSession.metadata = new MediaMetadata({title: item.naslov || "Safeer Media", artist: item.izvajalec || item.vir || "Safeer OS", artwork: item.slika ? [{src: item.slika}] : []}); } catch (e) {}
        }
        media.timer = window.setTimeout(function () {
          media.timer = 0;
          if (player.readyState < 2 && !poskusiNaslednjo()) $("mediaNapaka").hidden = false;
        }, 20000);
      }
    } else {
      if (iframe && /^https?:\/\//i.test(url)) {
        iframe.hidden = false;
        napakaEl.hidden = true;
        iframe.src = url;
        // Cross-origin iframe ne razkrije stanja svojega predvajalnika.
        // Potek časa zato ni dokaz, da je ponudnik tok zavrnil: ne skrij
        // iframe-a in ne pošiljaj dodatnih zahtev na naslednje ponudnike.
        media.timer = window.setTimeout(function () {
          media.timer = 0;
          napakaEl.textContent = mediaZunanjiStatus();
          napakaEl.classList.add("media-opozorilo");
          napakaEl.hidden = false;
        }, 45000);
      } else napakaEl.hidden = false;
    }
    var choices = $("mediaRazlicice"); choices.innerHTML = "";
    variants.forEach(function (entry, i) {
      var button = el("button", i === (index || 0) ? "izbran" : "", ubezi([entry.kakovost, entry.vir].filter(Boolean).join(" · ")));
      button.onclick = function () { predvajajHtml(item, i); }; choices.appendChild(button);
    });
    $("vsebina").scrollTop = 0;
  }
  function mediaZunanjiStatus() {
    var jezik = (document.documentElement.lang || "sl").toLowerCase().split("-")[0];
    var sporocila = {
      sl: "Safeer ne more preveriti stanja zunanjega predvajalnika. Če je zaslon še vedno črn, izberi drugo različico.",
      en: "Safeer cannot inspect this external player. If the screen is still blank, try another version.",
      de: "Safeer kann diesen externen Player nicht überprüfen. Wenn der Bildschirm noch schwarz ist, probiere eine andere Version.",
      es: "Safeer no puede comprobar este reproductor externo. Si la pantalla sigue en negro, prueba otra versión.",
      fr: "Safeer ne peut pas vérifier ce lecteur externe. Si l’écran est toujours noir, essayez une autre version.",
      it: "Safeer non può verificare questo lettore esterno. Se lo schermo è ancora nero, prova un’altra versione."
    };
    return sporocila[jezik] || sporocila.sl;
  }
  function odpriMedia(id) {
    // Prenos, ki ga izdajatelj ponuja samo na svoji strani (npr. RTV SLO): odpremo ga v Spletu.
    var znan = (media.katalog || []).find(function (x) { return x.id === id; });
    if (znan && znan.stran) { otvoriSpletnoStran(znan.stran, znan.naslov); return; }
    klic("mediaPredvajaj", [id]).then(function (item) {
      if (!item) { obvesti(t("mediaVirNapaka")); return; }
      media.aktivni = item;
      if (!item.native) predvajajHtml(item, 0);
    }, function () { obvesti(t("mediaVirNapaka")); });
  }
  function zapriMediaHtml() {
    if (media.timer) { window.clearTimeout(media.timer); media.timer = 0; }
    [$("mediaVideo"), $("mediaAudio")].forEach(function (player) {
      if (player) { player.pause(); player.removeAttribute("src"); player.load(); player.hidden = true; player.style.display = "none"; }
    });
    var iframe = $("mediaIframe"); if (iframe) { iframe.src = "about:blank"; iframe.hidden = true; }
    var playerImage = $("mediaSlika"); if (playerImage) { playerImage.removeAttribute("src"); playerImage.hidden = true; }
    var pl = $("mediaPredvajalnik");
    if (pl) { pl.hidden = true; pl.classList.remove("kino"); }
    media.aktivni = null;
    klic("celozaslonsko", [false]);
  }
  // Zanri pod iskanjem: pri filmih in serijah filmski (TMDB), pri glasbi in radiu glasbene zvrsti,
  // drugje jih ni. Ob menjavi skupine izbrani zanr ponastavimo (filmska oznaka ni glasbena).
  var FILMSKI_ZANRI = null;
  function skupinaZanrov(filter) {
    if (filter === "film" || filter === "serija" || filter === "vse") return "film";
    if (filter === "glasba" || filter === "radio") return filter;
    return "";
  }
  function izberiZanr(b) {
    media.genre = b.getAttribute("data-media-genre") || "";
    media.page = 1;
    document.querySelectorAll("[data-media-genre]").forEach(function (q) { q.classList.toggle("izbran", q === b); });
    naloziMedia();
  }
  function narisiZanre() {
    var vrstica = $("mediaZanri");
    if (!vrstica) return;
    if (FILMSKI_ZANRI === null) FILMSKI_ZANRI = vrstica.innerHTML;
    var skupina = skupinaZanrov(media.filter);
    if (media._skupinaZanrov === skupina) return;
    media._skupinaZanrov = skupina;
    media.genre = "";
    vrstica.hidden = !skupina;
    if (skupina === "film") {
      vrstica.innerHTML = FILMSKI_ZANRI;
      vrstica.querySelectorAll("[data-media-genre]").forEach(function (b) {
        b.classList.toggle("izbran", !b.getAttribute("data-media-genre"));
        b.onclick = function () { izberiZanr(b); };
      });
      return;
    }
    if (!skupina) return;
    vrstica.innerHTML = "";
    var vse = el("button", "izbran"); vse.setAttribute("data-media-genre", "");
    vse.textContent = skupina === "radio" ? "Vse postaje" : "Vsa glasba";
    vse.onclick = function () { izberiZanr(vse); };
    vrstica.appendChild(vse);
    klic("mediaZvrsti", [skupina]).then(function (zvrsti) {
      if (media._skupinaZanrov !== skupina) return;
      (zvrsti || []).forEach(function (z) {
        var b = el("button"); b.setAttribute("data-media-genre", z.id); b.textContent = z.ime;
        b.onclick = function () { izberiZanr(b); };
        vrstica.appendChild(b);
      });
    });
  }

  function naloziMedia() {
    narisiZanre();
    var zahteva = ++media.zahteva;
    $("mediaPovzetek").textContent = "Nalagam katalog …";
    klic("mediaKatalog", [media.query, media.filter, media.genre, media.page || 1]).then(function (response) {
      if (zahteva !== media.zahteva) return;
      media.katalog = (response && response.vnosi) || [];
      media.viri = (response && response.viri) || [];
      media.skupaj_strani = (response && response.skupaj_strani) || 1;
      narisiMedia();
    }, function () { if (zahteva === media.zahteva) { media.katalog = []; media.viri = []; narisiMedia(); } });
  }

  function zapriMediaPodrobnosti() {
    var panel = $("mediaPodrobnosti"); if (panel) panel.hidden = true;
  }
  function mediaWatchCountryName(code, fallback) {
    try { return new Intl.DisplayNames([LOKALE[jezik] || "en-GB"], {type:"region"}).of(code) || fallback || code; }
    catch (_) { return fallback || code; }
  }
  function naloziMediaWatchSettings() {
    var select = $("mediaWatchCountry"); if (!select) return;
    klic("mediaWatchSettings", [jezik]).then(function (settings) {
      if (!settings) return;
      var automatic = document.createElement("option"); automatic.value = "auto";
      automatic.textContent = t("mediaWatchAuto", {country:mediaWatchCountryName(settings.zaznana, settings.ime_zaznane)});
      select.replaceChildren(automatic);
      (settings.regions || []).slice().sort(function (a,b) {
        return String(a.native_name || a.english_name).localeCompare(String(b.native_name || b.english_name), LOKALE[jezik] || "en");
      }).forEach(function (region) {
        var option = document.createElement("option"); option.value = region.code;
        option.textContent = mediaWatchCountryName(region.code, region.native_name || region.english_name);
        select.appendChild(option);
      });
      select.value = settings.izbrana || "auto";
      if (!select.value) select.value = "auto";
    }).catch(function () {});
  }
  on("mediaWatchCountry", "change", function () {
    klic("mediaWatchCountry", [this.value]).then(function () { obvesti(t("mediaOsvezeno")); })
      .catch(function () { obvesti(t("mediaVirNapaka")); });
  });
  function narisiMediaWatchProviders(item) {
    var target = $("mediaWatchProviders"); if (!target) return;
    target.innerHTML = "";
    var data = item.kje_gledati || {};
    var countryName = mediaWatchCountryName(data.drzava, data.ime_drzave);
    target.appendChild(el("h3", "", t("mediaWatchTitle", {country:countryName})));
    var groups = data.skupine || [];
    if (!groups.length) target.appendChild(el("p", "", t("mediaWatchNone", {country:countryName})));
    var groupLabels = {"naročnina":"mediaWatchSubscription", "brezplačno":"mediaWatchFree", "izposoja":"mediaWatchRent", "nakup":"mediaWatchBuy"};
    groups.forEach(function (group) {
      var section = el("div", "media-kje-gledati-skupina");
      section.appendChild(el("h4", "", t(groupLabels[group.id] || group.id)));
      var providers = el("div", "media-ponudniki");
      (group.ponudniki || []).forEach(function (provider) {
        var button = el("button", "media-ponudnik", ""); button.type = "button";
        if (provider.logo) { var logo = document.createElement("img"); logo.src = provider.logo; logo.alt = ""; logo.loading = "lazy"; button.appendChild(logo); }
        button.appendChild(el("span", "", ubezi(provider.ime || "")));
        button.onclick = function () { if (provider.povezava) otvoriSpletnoStran(provider.povezava, provider.ime); };
        providers.appendChild(button);
      });
      section.appendChild(providers); target.appendChild(section);
    });
    target.appendChild(el("p", "media-kje-gledati-vira", t("mediaWatchSource")));
  }
  function naloziMediaSezono(item, season, button) {
    document.querySelectorAll("#mediaSezone button").forEach(function (b) { b.classList.toggle("izbran", b === button); });
    $("mediaEpizode").innerHTML = '<div class="prazno">Nalagam epizode …</div>';
    klic("mediaSezona", [item.tmdb_id, season]).then(function (response) {
      var cilj = $("mediaEpizode"); cilj.innerHTML = "";
      var episodes = (response && response.epizode) || [];
      $("mediaEpizodeNaslov").textContent = "Epizode · " + (button ? button.textContent : "Sezona " + season);
      episodes.forEach(function (ep) {
        var row = el("article", "media-epizoda");
        if (ep.slika) { var img = document.createElement("img"); img.src = ep.slika; img.alt = ""; img.loading = "lazy"; row.appendChild(img); }
        var info = el("div", "media-epizoda-info");
        info.appendChild(el("b", "", "E" + String(ep.stevilka).padStart(2, "0") + "  " + ubezi(ep.naslov || "Epizoda")));
        info.appendChild(el("small", "", ubezi([ep.datum, ep.trajanje ? ep.trajanje + " min" : "", ep.ocena ? "★ " + ep.ocena : ""].filter(Boolean).join(" · "))));
        if (ep.opis) info.appendChild(el("p", "", ubezi(ep.opis))); row.appendChild(info);
        var play = el("button", "gumb glavni", "▶ Predvajaj (1080p)");
        play.onclick = function () {
          klic("mediaEpizoda", [item.tmdb_id, season, ep.stevilka, item.naslov + " · " + ep.naslov]).then(function (entry) {
            if (entry && entry.id) { zapriMediaPodrobnosti(); odpriMedia(entry.id); }
          });
        }; row.appendChild(play); cilj.appendChild(row);
      });
      if (!episodes.length) cilj.appendChild(el("div", "prazno", "Za to sezono ni podatkov."));
    });
  }
  function odpriMediaPodrobnosti(id) {
    klic("mediaPodrobnosti", [id, jezik]).then(function (item) {
      if (!item) return;
      var panel = $("mediaPodrobnosti"); panel.hidden = false;
      var hero = $("mediaPodrobnostiJunak"); hero.innerHTML = "";
      if (item.slika) { var poster = document.createElement("img"); poster.src = item.slika; poster.alt = ""; hero.appendChild(poster); }
      var info = el("div"); info.appendChild(el("h2", "", ubezi(item.naslov || "")));
      info.appendChild(el("p", "media-detail-meta", ubezi([item.leto, item.ocena ? "★ " + item.ocena : "", item.vrsta === "serija" ? "Serija" : "Film"].filter(Boolean).join(" · "))));
      if (item.opis) info.appendChild(el("p", "", ubezi(item.opis))); hero.appendChild(info);
      narisiMediaWatchProviders(item);
      var seasons = $("mediaSezone"); seasons.innerHTML = "";
      var episodes = $("mediaEpizode"); episodes.innerHTML = "";

      if (item.vrsta !== "serija") {
        if ($("mediaSezoneNaslov")) $("mediaSezoneNaslov").hidden = true;
        if ($("mediaSezone")) $("mediaSezone").hidden = true;
        $("mediaEpizodeNaslov").textContent = "Možnosti predvajanja";
        var playBtn = el("button", "gumb glavni", "▶ Predvajaj film (1080p HD)");
        playBtn.style.padding = "14px 28px";
        playBtn.style.fontSize = "18px";
        playBtn.style.marginTop = "12px";
        playBtn.onclick = function () {
          if (item.tmdb_id) {
            klic("mediaFilm", [item.tmdb_id, item.naslov]).then(function (entry) {
              if (entry && entry.id) { zapriMediaPodrobnosti(); odpriMedia(entry.id); }
              else { zapriMediaPodrobnosti(); odpriMedia(item.id); }
            });
          } else {
            zapriMediaPodrobnosti();
            odpriMedia(item.id);
          }
        };
        episodes.appendChild(playBtn);
      } else {
        if ($("mediaSezoneNaslov")) $("mediaSezoneNaslov").hidden = false;
        if ($("mediaSezone")) $("mediaSezone").hidden = false;
        $("mediaEpizodeNaslov").textContent = "Epizode";
        (item.sezone || []).forEach(function (season, index) {
          var b = el("button", index === 0 ? "izbran" : "", ubezi(season.ime || "Sezona " + season.stevilka));
          b.onclick = function () { naloziMediaSezono(item, season.stevilka, b); }; seasons.appendChild(b);
          if (index === 0) setTimeout(function () { naloziMediaSezono(item, season.stevilka, b); }, 0);
        });
        if (!(item.sezone || []).length) episodes.innerHTML = '<div class="prazno">Sezone niso na voljo.</div>';
      }
      panel.scrollIntoView({behavior:"smooth", block:"start"});
    }, function () { obvesti(t("mediaVirNapaka")); });
  }
  function osveziMediaVir(id) {
    $("mediaVirSporocilo").textContent = t("mediaOsvezi") + " …";
    klic("mediaOsveziVir", id ? [id] : []).then(function () {
      $("mediaVirSporocilo").textContent = t("mediaOsvezeno"); naloziMedia();
    }, function () { $("mediaVirSporocilo").textContent = t("mediaVirNapaka"); });
  }
  document.querySelectorAll("[data-media-filter]").forEach(function (b) {
    b.onclick = function () {
      media.filter = b.getAttribute("data-media-filter");
      media.page = 1;
      document.querySelectorAll("[data-media-filter]").forEach(function (q) {
        q.classList.toggle("izbran", q === b);
        q.classList.toggle("izbrana", q === b);
      });
      naloziMedia();
    };
  });
  document.querySelectorAll("[data-media-genre]").forEach(function (b) {
    b.onclick = function () { izberiZanr(b); };
  });
  on("mediaIskanje", "input", function () {
    media.query = this.value; media.page = 1; clearTimeout(media.timer); media.timer = setTimeout(naloziMedia, 350);
  });
  on("mediaPodrobnostiNazaj", "click", zapriMediaPodrobnosti);
  on("mediaPodrobnostiZapri", "click", zapriMediaPodrobnosti);
  on("mediaZapri", "click", zapriMediaHtml);
  on("mediaPredvajalnikNazaj", "click", zapriMediaHtml);
  window.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      var pl = $("mediaPredvajalnik");
      if (pl && !pl.hidden) {
        zapriMediaHtml();
        e.preventDefault();
      }
    }
  });
  on("mediaKino", "click", function () {
    var pl = $("mediaPredvajalnik");
    if (!pl) return;
    var jeKino = pl.classList.toggle("kino");
    klic("celozaslonsko", [jeKino]);
  });
  on("mediaOsvezi", "click", function () { osveziMediaVir(""); });
  on("mediaDodajVir", "submit", function (event) {
    event.preventDefault(); var url = $("mediaVirUrl").value.trim(), name = $("mediaVirIme").value.trim();
    if (!url) return;
    $("mediaVirSporocilo").textContent = t("mediaDodaj") + " …";
    klic("mediaDodajVir", [url, name]).then(function (result) {
      if (result && result.ok) { $("mediaVirUrl").value = ""; $("mediaVirIme").value = ""; $("mediaVirSporocilo").textContent = t("mediaVirDodan"); }
      else $("mediaVirSporocilo").textContent = (result && result.napaka === "podvojen") ? t("mediaVirPodvojen") : ((result && result.napaka) ? result.napaka : t("mediaVirNapaka"));
      naloziMedia();
    }, function () { $("mediaVirSporocilo").textContent = t("mediaVirNapaka"); });
  });
  on("mediaDodajMapo", "submit", function (event) {
    event.preventDefault();
    var pot = $("mediaMapaPot").value.trim();
    if (!pot) return;
    klic("mediaDodajMapo", [pot]).then(function (result) {
      $("mediaVirSporocilo").textContent = result && result.ok ? "Mapa je dodana." : ((result && result.napaka) || t("mediaVirNapaka"));
      if (result && result.ok) $("mediaMapaPot").value = "";
      naloziMedia();
    }, function () { $("mediaVirSporocilo").textContent = t("mediaVirNapaka"); });
  });
  on("mediaDodajStreznik", "submit", function (event) {
    event.preventDefault();
    var provider = $("mediaStreznikVrsta").value;
    var name = $("mediaStreznikIme").value.trim();
    var url = $("mediaStreznikUrl").value.trim();
    var username = $("mediaStreznikUporabnik").value.trim();
    var secret = $("mediaStreznikSkrivnost").value;
    if (!url || !secret) return;
    $("mediaVirSporocilo").textContent = "Povezujem strežnik …";
    klic("mediaDodajStreznik", [provider, name, url, username, secret]).then(function (result) {
      $("mediaStreznikSkrivnost").value = "";
      if (result && result.ok) {
        $("mediaStreznikUrl").value = ""; $("mediaStreznikIme").value = "";
        $("mediaVirSporocilo").textContent = "Strežnik je varno povezan.";
      } else $("mediaVirSporocilo").textContent = (result && result.napaka) || t("mediaVirNapaka");
      naloziMedia();
    }, function () {
      $("mediaStreznikSkrivnost").value = "";
      $("mediaVirSporocilo").textContent = t("mediaVirNapaka");
    });
  });

  // --- Safeer Media: Nastavitve, Uvoz & Izvoz JSON ---
  var mediaIzbranaDatoteka = null;

  function sporociloNastavitev(tekst, jeUspeh) {
    var el = $("mediaNastavitveSporocilo");
    if (!el) return;
    el.textContent = tekst;
    el.className = "namig " + (jeUspeh ? "uspeh" : "napaka");
  }

  if ($("mediaNastavitveGumb")) {
    $("mediaNastavitveGumb").addEventListener("click", function () {
      pojdi("nastavitve");
      var plosca = $("mediaNastavitvePlosca");
      if (plosca) setTimeout(function () { plosca.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, 0);
    });
  }

  if ($("mediaZapriNastavitve")) {
    $("mediaZapriNastavitve").addEventListener("click", function () {
      if ($("mediaNastavitvePlosca")) $("mediaNastavitvePlosca").hidden = true;
    });
  }

  // 1. Izbira in nalaganje izvožene JSON datoteke
  if ($("mediaIzberiDatoteko")) {
    $("mediaIzberiDatoteko").addEventListener("click", function () {
      $("mediaJsonDatoteka").click();
    });
  }

  if ($("mediaJsonDatoteka")) {
    $("mediaJsonDatoteka").addEventListener("change", function () {
      var dat = this.files && this.files[0];
      if (!dat) {
        mediaIzbranaDatoteka = null;
        $("mediaDatotekaIme").textContent = t("mediaNobenaDatoteka");
        $("mediaUvoziDatotekoGumb").disabled = true;
        return;
      }
      mediaIzbranaDatoteka = dat;
      var kb = Math.round(dat.size / 1024);
      $("mediaDatotekaIme").textContent = dat.name + " (" + kb + " KB)";
      $("mediaUvoziDatotekoGumb").disabled = false;
      sporociloNastavitev("", true);
    });
  }

  if ($("mediaUvoziDatotekoGumb")) {
    $("mediaUvoziDatotekoGumb").addEventListener("click", function () {
      if (!mediaIzbranaDatoteka) {
        sporociloNastavitev(t("mediaVnesiteJson"), false);
        return;
      }
      var ime = mediaIzbranaDatoteka.name.replace(/\.json$/i, "");
      var reader = new FileReader();
      reader.onload = function (e) {
        var vsebina = e.target.result;
        sporociloNastavitev(t("mediaUvoziDatoteko") + " …", true);
        klic("mediaUvoziJson", [vsebina, ime]).then(function (res) {
          if (res && res.ok) {
            var msg = res.vrsta === "viri"
              ? t("mediaUvozVirovUspesen", { n: (res.st_dodanih || 0) + (res.st_posodobljenih || 0) })
              : t("mediaUvozUspesen", { n: res.st_vnosov || 0, vir: res.vir || ime });
            sporociloNastavitev(msg, true);
            $("mediaJsonDatoteka").value = "";
            mediaIzbranaDatoteka = null;
            $("mediaDatotekaIme").textContent = t("mediaNobenaDatoteka");
            $("mediaUvoziDatotekoGumb").disabled = true;
            naloziMedia();
          } else {
            sporociloNastavitev(res && res.napaka ? res.napaka : t("mediaUvozNapaka"), false);
          }
        }, function () {
          sporociloNastavitev(t("mediaUvozNapaka"), false);
        });
      };
      reader.onerror = function () {
        sporociloNastavitev(t("mediaUvozNapaka"), false);
      };
      reader.readAsText(mediaIzbranaDatoteka, "utf-8");
    });
  }

  // 2. Vnos lastne JSON kode
  if ($("mediaUvoziKodoGumb")) {
    $("mediaUvoziKodoGumb").addEventListener("click", function () {
      var koda = $("mediaJsonKoda").value.trim();
      var ime = $("mediaJsonIme").value.trim();
      if (!koda) {
        sporociloNastavitev(t("mediaVnesiteJson"), false);
        return;
      }
      sporociloNastavitev(t("mediaUvoziKodo") + " …", true);
      klic("mediaUvoziJson", [koda, ime]).then(function (res) {
        if (res && res.ok) {
          var msg = res.vrsta === "viri"
            ? t("mediaUvozVirovUspesen", { n: (res.st_dodanih || 0) + (res.st_posodobljenih || 0) })
            : t("mediaUvozUspesen", { n: res.st_vnosov || 0, vir: res.vir || (ime || "JSON") });
          sporociloNastavitev(msg, true);
          $("mediaJsonKoda").value = "";
          $("mediaJsonIme").value = "";
          naloziMedia();
        } else {
          sporociloNastavitev(res && res.napaka ? res.napaka : t("mediaUvozNapaka"), false);
        }
      }, function () {
        sporociloNastavitev(t("mediaUvozNapaka"), false);
      });
    });
  }

  if ($("mediaPrimerKodeGumb")) {
    $("mediaPrimerKodeGumb").addEventListener("click", function () {
      var primer = [
        {
          "title": "Inception (Primer vdelanega filma)",
          "url": "https://vidsrc.cc/v2/embed/movie/tt1375666",
          "kind": "film",
          "year": 2010,
          "quality": "1080p",
          "poster": "https://m.media-amazon.com/images/M/MV5BMjAxMzY3NjcxNF5BMl5BanBnXkFtZTcwNTI5OTM0Mw@@._V1_SX300.jpg",
          "description": "Tat, ki krade skrivnosti skozi tehnologijo deljenja sanj, dobi obratno nalogo: vsaditev ideje."
        },
        {
          "title": "Igra prestolov S01E05 (Primer vdelane serije)",
          "url": "https://vidsrc.cc/v2/embed/tv/tt0944947/1/5",
          "kind": "serija",
          "season": 1,
          "episode": 5,
          "year": 2011,
          "quality": "1080p",
          "poster": "https://m.media-amazon.com/images/M/MV5BN2EyZjM3NzUtNWUzMi00MTgxLWI0NTctMzY4M2VlOTdjZWRiXkEyXkFqcGdeQXVyNDUzOTQ5MjY@._V1_SX300.jpg"
        },
        {
          "title": "Big Buck Bunny (Primer neposrednega MP4 videa)",
          "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
          "kind": "film",
          "year": 2008,
          "quality": "1080p",
          "poster": "https://upload.wikimedia.org/wikipedia/commons/c/c5/Big_buck_bunny_poster_big.jpg"
        }
      ];
      $("mediaJsonKoda").value = JSON.stringify(primer, null, 2);
      if (!$("mediaJsonIme").value) {
        $("mediaJsonIme").value = "Primer zbirke (Code Example)";
      }
      sporociloNastavitev(t("mediaPrimerVstavljen"), true);
      $("mediaJsonKoda").focus();
    });
  }

  if ($("mediaPocistiKodoGumb")) {
    $("mediaPocistiKodoGumb").addEventListener("click", function () {
      $("mediaJsonKoda").value = "";
      $("mediaJsonIme").value = "";
      sporociloNastavitev("", true);
    });
  }

  // 3. Izvoz v JSON datoteko
  if ($("mediaIzvoziGumb")) {
    $("mediaIzvoziGumb").addEventListener("click", function () {
      klic("mediaIzvoziJson", []).then(function (podatki) {
        if (!podatki) {
          sporociloNastavitev(t("niUspelo"), false);
          return;
        }
        var jsonStr = JSON.stringify(podatki, null, 2);
        var blob = new Blob([jsonStr], { type: "application/json;charset=utf-8" });
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = "safeer-media-izvoz.json";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        sporociloNastavitev(t("mediaPrenesiIzvoz") + " OK", true);
      }, function () {
        sporociloNastavitev(t("niUspelo"), false);
      });
    });
  }

})();
