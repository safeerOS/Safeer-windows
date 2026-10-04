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
    vrstica: "M4 5h16v14H4z M9 5v14 M15.5 9.5L13 12l2.5 2.5",
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
    sporocila: "M4 5h16v11H9l-5 4z M8 9h8 M8 12h6",
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
  // Most (window.SafeerOS) vstavi Safeer OS, se preden se stran zacne nalagati. Ce ga ob zagonu ni - po koncu
  // procesa strani ga QtWebEngine ni vedno vstavil -, ga Safeer OS doda takoj po nalaganju; zato ga iscemo sproti
  // (imaMost) in z nalaganjem podatkov nanj pocakamo (koMost).
  var most = window.SafeerOS || null;
  var cakajoMost = [];
  function imaMost() {
    if (!most) most = window.SafeerOS || null;
    return !!most;
  }
  function koMost(delo) {
    if (imaMost()) { delo(); return; }
    cakajoMost.push(delo);
    if (cakajoMost.length > 1) return;
    var poskusi = 0;
    var ura = setInterval(function () {
      if (!imaMost() && ++poskusi < 100) return;        // najvec 5 s
      clearInterval(ura);
      var vrsta = cakajoMost; cakajoMost = [];
      if (imaMost()) vrsta.forEach(function (d) { try { d(); } catch (e) { console.error(e); } });
    }, 50);
  }
  function klic(metoda, argumenti) {
    if (!imaMost()) return Promise.reject("brez mosta");
    return most.klic(metoda, argumenti || []);
  }
  // Ce mostu vseeno ni (ne bi se smelo zgoditi), naj uporabnik ne gleda gumbov, ki ne naredijo nic: povemo, kaj storiti.
  var brezMostuObvesceno = 0;
  window.addEventListener("unhandledrejection", function (e) {
    if (!e || e.reason !== "brez mosta" || imaMost()) return;
    if (window.performance && performance.now() < 8000) return;      // ob zagonu most se lahko prihaja (koMost)
    if (Date.now() - brezMostuObvesceno < 60000) return;
    brezMostuObvesceno = Date.now();
    obvesti(t("brezMostu"));
  });

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
  // Ime izdelka je enako v vseh jezikih; razdelek sam še vedno uporablja
  // lokalizirani naslov »Naprave / Devices / Geräte …«.
  Object.keys(BESEDILA_OS).forEach(function (koda) {
    BESEDILA_OS[koda].safeerLink = "Safeer Link";
  });
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
    sl: { mediaPredaja:"Nadaljuj z druge naprave",mediaPredajaOpis:"Kaj predvaja ali je nazadnje gledala druga naprava – nadaljuj tukaj pri isti sekundi.",mediaPredajaVprasam:"Sprašujem naprave …",mediaPredajaNic:"Nobena naprava v Safeer Linku zdaj ničesar ne predvaja.",mediaPredajaIgra:"igra",mediaPredajaNazadnje:"nazadnje",mediaPredajaTukaj:"Nadaljuj tukaj",mediaPredajaTukajUstavi:"Nadaljuj tukaj in ustavi tam",mediaPredajaNapaka:"Naprav ni bilo mogoče vprašati.",mediaOpis:"Filmi, serije in glasba iz vseh tvojih virov v enem katalogu.",mediaOsvezi:"Osveži vire",mediaNastavitve:"Nastavitve",mediaNastavitveNaslov:"Nastavitve Safeer Media",mediaNastavitveOpis:"Uvoz in izvoz JSON knjižnic, neposreden vnos kode ter upravljanje virov.",mediaUvozDatoteke:"Naloži izvoženo JSON datoteko",mediaUvozDatotekeOpis:"Izberite .json datoteko kataloga ali virov, ki ste jo izvozili prej ali prejeli iz druge naprave.",mediaIzberiDatoteko:"Izberi .json datoteko",mediaNobenaDatoteka:"Nobena datoteka ni izbrana",mediaUvoziDatoteko:"Uvozi datoteko",mediaVnosJson:"Vnesi svojo JSON kodo",mediaVnosJsonOpis:"Prilepite JSON seznam medijev, prilagojeno konfiguracijo ali vir s tokovi.",mediaJsonImePh:"Ime zbirke ali vira (neobvezno)",mediaUvoziKodo:"Uvozi JSON kodo",mediaVstaviPrimer:"Primer kode (Code Example)",mediaPocisti:"Počisti",mediaPrimerVstavljen:"Primer JSON kode je bil uspešno vstavljen.",mediaIzvozJson:"Izvozi vsebine v JSON",mediaIzvozJsonOpis:"Prenesite celotno zbirko vaših virov in nastavitev v datoteko za varnostno kopijo ali prenos.",mediaPrenesiIzvoz:"Prenesi izvoženi JSON",mediaUvozUspesen:"Uspešno uvoženo: {n} vsebin v vir '{vir}'.",mediaUvozVirovUspesen:"Uspešno posodobljenih/dodanih virov: {n}.",mediaUvozNapaka:"Napaka pri uvozu JSON.",mediaVnesiteJson:"Prosimo, vnesite ali izberite veljavno JSON kodo.",mediaPredvaja:"PREDVAJA SE V SAFEER OS",mediaNapaka:"Tega toka ni mogoče predvajati. Poskusi drugo različico.",mediaIsci:"Išči filme, serije, videe, glasbo in radio",mediaVse:"Vse",mediaFilmi:"Filmi",mediaSerije:"Serije",mediaGlasba:"Glasba",mediaPrazno:"Ni zadetkov. Dodaj vir ali spremeni iskanje.",mediaViri:"Tvoji viri",mediaViriOpis:"Spletno stran, javni API, RSS ali M3U dodaš samo enkrat.",mediaVirIme:"Ime vira (neobvezno)",mediaVirUrl:"https://tilvids.com",mediaDodaj:"Dodaj vir",mediaZadetkov:"{n} enotnih vsebin",mediaRazlicic:"{n} različic",mediaVirDodan:"Vir je dodan in katalog združen.",mediaVirPodvojen:"Ta vir je že dodan.",mediaVirNapaka:"Vira ni bilo mogoče prebrati.",mediaOsvezeno:"Viri so osveženi.",mediaBrezVirov:"Dodaj prvi spletni vir; lokalne mape so vključene samodejno.",mediaVirElementov:"{n} vsebin",zvocnikNa:"Na zvočnik",zvocnikIscem:"Iščem zvočnike v omrežju …",zvocnikNiNajdenih:"Ni najdenih zvočnikov. Zvočnik mora biti prižgan in v istem omrežju (DLNA).",zvocnikIgra:"Zdaj igra na: {ime}",zvocnikZaseden:"{ime} igra {vir} – pritisni še enkrat za preklop",zvocnikNaslov:"Na zvočniku: {ime}",zvocnikPremor:"Premor / nadaljuj",zvocnikNazaj:"Nazaj na računalnik",zvocnikNiVir:"Te vsebine zvočnik ne more predvajati."},
    en: { mediaPredaja:"Continue from another device",mediaPredajaOpis:"What another device is playing or last watched – continue here at the same second.",mediaPredajaVprasam:"Asking devices …",mediaPredajaNic:"No device in Safeer Link is playing anything right now.",mediaPredajaIgra:"playing",mediaPredajaNazadnje:"last",mediaPredajaTukaj:"Continue here",mediaPredajaTukajUstavi:"Continue here and stop there",mediaPredajaNapaka:"Could not ask the devices.",mediaOpis:"Movies, series and music from all your sources in one catalogue.",mediaOsvezi:"Refresh sources",mediaNastavitve:"Settings",mediaNastavitveNaslov:"Safeer Media Settings",mediaNastavitveOpis:"Import and export JSON libraries, enter custom code, and manage sources.",mediaUvozDatoteke:"Upload exported JSON file",mediaUvozDatotekeOpis:"Select a .json file of catalogue or sources previously exported or shared.",mediaIzberiDatoteko:"Choose .json file",mediaNobenaDatoteka:"No file selected",mediaUvoziDatoteko:"Import file",mediaVnosJson:"Add your own JSON code",mediaVnosJsonOpis:"Paste a JSON list of media, custom configuration, or streams.",mediaJsonImePh:"Collection or source name (optional)",mediaUvoziKodo:"Import JSON code",mediaVstaviPrimer:"Code Example",mediaPocisti:"Clear",mediaPrimerVstavljen:"JSON code example successfully inserted.",mediaIzvozJson:"Export catalogue to JSON",mediaIzvozJsonOpis:"Download the full collection of your sources and settings for backup or sharing.",mediaPrenesiIzvoz:"Download exported JSON",mediaUvozUspesen:"Successfully imported: {n} items into '{vir}'.",mediaUvozVirovUspesen:"Successfully updated/added sources: {n}.",mediaUvozNapaka:"Error importing JSON.",mediaVnesiteJson:"Please enter or select valid JSON code.",mediaPredvaja:"PLAYING IN SAFEER OS",mediaNapaka:"This stream cannot be played. Try another version.",mediaIsci:"Search movies, series and music",mediaVse:"All",mediaFilmi:"Movies",mediaSerije:"Series",mediaGlasba:"Music",mediaPrazno:"No results. Add a source or change the search.",mediaViri:"Your sources",mediaViriOpis:"Add a website, public API, RSS or M3U only once.",mediaVirIme:"Source name (optional)",mediaVirUrl:"https://example.com/catalogue.json",mediaDodaj:"Add source",mediaZadetkov:"{n} unique titles",mediaRazlicic:"{n} versions",mediaVirDodan:"Source added and catalogue merged.",mediaVirPodvojen:"This source has already been added.",mediaVirNapaka:"The source could not be read.",mediaOsvezeno:"Sources refreshed.",mediaBrezVirov:"Add your first web source; local folders are included automatically.",mediaVirElementov:"{n} titles",zvocnikNa:"To speaker",zvocnikIscem:"Searching for speakers in your network…",zvocnikNiNajdenih:"No speakers found. The speaker must be on and in the same network (DLNA).",zvocnikIgra:"Now playing on {ime}",zvocnikZaseden:"{ime} is playing {vir} – press again to switch",zvocnikNaslov:"On speaker: {ime}",zvocnikPremor:"Pause / resume",zvocnikNazaj:"Back to this computer",zvocnikNiVir:"The speaker cannot play this item."},
    de: { mediaPredaja:"Auf anderem Gerät weiterschauen",mediaPredajaOpis:"Was ein anderes Gerät gerade abspielt oder zuletzt gesehen hat – hier an derselben Sekunde weiter.",mediaPredajaVprasam:"Frage Geräte …",mediaPredajaNic:"Kein Gerät im Safeer Link spielt gerade etwas ab.",mediaPredajaIgra:"läuft",mediaPredajaNazadnje:"zuletzt",mediaPredajaTukaj:"Hier weiter",mediaPredajaTukajUstavi:"Hier weiter und dort stoppen",mediaPredajaNapaka:"Die Geräte konnten nicht gefragt werden.",mediaOpis:"Filme, Serien und Musik aus allen Quellen in einem Katalog.",mediaOsvezi:"Quellen aktualisieren",mediaNastavitve:"Einstellungen",mediaNastavitveNaslov:"Safeer Media Einstellungen",mediaNastavitveOpis:"JSON-Bibliotheken importieren und exportieren sowie Quellen verwalten.",mediaUvozDatoteke:"Exportierte JSON-Datei hochladen",mediaUvozDatotekeOpis:"Wählen Sie eine .json-Datei aus, die Sie zuvor exportiert oder geteilt haben.",mediaIzberiDatoteko:".json-Datei auswählen",mediaNobenaDatoteka:"Keine Datei ausgewählt",mediaUvoziDatoteko:"Datei importieren",mediaVnosJson:"Eigenen JSON-Code eingeben",mediaVnosJsonOpis:"Fügen Sie eine JSON-Medienliste oder eigene Konfiguration ein.",mediaJsonImePh:"Name der Quelle (optional)",mediaUvoziKodo:"JSON-Code importieren",mediaVstaviPrimer:"Code-Beispiel",mediaPocisti:"Löschen",mediaPrimerVstavljen:"JSON-Codebeispiel erfolgreich eingefügt.",mediaIzvozJson:"Katalog in JSON exportieren",mediaIzvozJsonOpis:"Laden Sie die gesamte Quellensammlung für Backups oder Teilen herunter.",mediaPrenesiIzvoz:"Exportierte JSON herunterladen",mediaUvozUspesen:"Erfolgreich importiert: {n} Inhalte in '{vir}'.",mediaUvozVirovUspesen:"Erfolgreich aktualisiert/hinzugefügt: {n} Quellen.",mediaUvozNapaka:"Fehler beim Importieren von JSON.",mediaVnesiteJson:"Bitte geben Sie gültigen JSON-Code ein.",mediaPredvaja:"WIEDERGABE IN SAFEER OS",mediaNapaka:"Dieser Stream kann nicht abgespielt werden. Probiere eine andere Version.",mediaIsci:"Filme, Serien und Musik suchen",mediaVse:"Alle",mediaFilmi:"Filme",mediaSerije:"Serien",mediaGlasba:"Musik",mediaPrazno:"Keine Ergebnisse. Quelle hinzufügen oder Suche ändern.",mediaViri:"Deine Quellen",mediaViriOpis:"Website, öffentliche API, RSS oder M3U nur einmal hinzufügen.",mediaVirIme:"Name der Quelle (optional)",mediaVirUrl:"https://beispiel.de/katalog.json",mediaDodaj:"Quelle hinzufügen",mediaZadetkov:"{n} eindeutige Inhalte",mediaRazlicic:"{n} Versionen",mediaVirDodan:"Quelle hinzugefügt und Katalog zusammengeführt.",mediaVirPodvojen:"Diese Quelle wurde bereits hinzugefügt.",mediaVirNapaka:"Die Quelle konnte nicht gelesen werden.",mediaOsvezeno:"Quellen aktualisiert.",mediaBrezVirov:"Füge deine erste Webquelle hinzu; lokale Ordner sind automatisch enthalten.",mediaVirElementov:"{n} Inhalte",zvocnikNa:"Auf Lautsprecher",zvocnikIscem:"Suche Lautsprecher im Netzwerk …",zvocnikNiNajdenih:"Keine Lautsprecher gefunden. Er muss eingeschaltet und im selben Netzwerk sein (DLNA).",zvocnikIgra:"Läuft jetzt auf {ime}",zvocnikZaseden:"{ime} spielt {vir} – nochmals drücken zum Umschalten",zvocnikNaslov:"Auf Lautsprecher: {ime}",zvocnikPremor:"Pause / fortsetzen",zvocnikNazaj:"Zurück auf diesen Computer",zvocnikNiVir:"Der Lautsprecher kann diesen Inhalt nicht abspielen."},
    es: { mediaPredaja:"Continuar desde otro dispositivo",mediaPredajaOpis:"Lo que otro dispositivo reproduce o vio por última vez – continúa aquí en el mismo segundo.",mediaPredajaVprasam:"Preguntando a los dispositivos …",mediaPredajaNic:"Ningún dispositivo de Safeer Link reproduce nada ahora.",mediaPredajaIgra:"reproduciendo",mediaPredajaNazadnje:"último",mediaPredajaTukaj:"Continuar aquí",mediaPredajaTukajUstavi:"Continuar aquí y parar allí",mediaPredajaNapaka:"No se pudo preguntar a los dispositivos.",mediaOpis:"Películas, series y música de todas tus fuentes en un catálogo.",mediaOsvezi:"Actualizar fuentes",mediaNastavitve:"Ajustes",mediaNastavitveNaslov:"Ajustes de Safeer Media",mediaNastavitveOpis:"Importar y exportar bibliotecas JSON y gestionar fuentes.",mediaUvozDatoteke:"Subir archivo JSON exportado",mediaUvozDatotekeOpis:"Seleccione un archivo .json de catálogo o fuentes exportado previamente.",mediaIzberiDatoteko:"Seleccionar archivo .json",mediaNobenaDatoteka:"Ningún archivo seleccionado",mediaUvoziDatoteko:"Importar archivo",mediaVnosJson:"Añade tu propio código JSON",mediaVnosJsonOpis:"Pega una lista JSON de medios, configuración personalizada o flujos.",mediaJsonImePh:"Nombre de la fuente (opcional)",mediaUvoziKodo:"Importar código JSON",mediaVstaviPrimer:"Ejemplo de código",mediaPocisti:"Limpiar",mediaPrimerVstavljen:"Ejemplo de código JSON insertado con éxito.",mediaIzvozJson:"Exportar catálogo a JSON",mediaIzvozJsonOpis:"Descarga la colección completa de tus fuentes y ajustes.",mediaPrenesiIzvoz:"Descargar JSON exportado",mediaUvozUspesen:"Importado con éxito: {n} contenidos en '{vir}'.",mediaUvozVirovUspesen:"Fuentes actualizadas/añadidas con éxito: {n}.",mediaUvozNapaka:"Error al importar JSON.",mediaVnesiteJson:"Por favor introduce un código JSON válido.",mediaPredvaja:"REPRODUCIENDO EN SAFEER OS",mediaNapaka:"No se puede reproducir este flujo. Prueba otra versión.",mediaIsci:"Buscar películas, series y música",mediaVse:"Todo",mediaFilmi:"Películas",mediaSerije:"Series",mediaGlasba:"Música",mediaPrazno:"No hay resultados. Añade una fuente o cambia la búsqueda.",mediaViri:"Tus fuentes",mediaViriOpis:"Añade una web, API pública, RSS o M3U una sola vez.",mediaVirIme:"Nombre de la fuente (opcional)",mediaVirUrl:"https://ejemplo.es/catalogo.json",mediaDodaj:"Añadir fuente",mediaZadetkov:"{n} contenidos únicos",mediaRazlicic:"{n} versiones",mediaVirDodan:"Fuente añadida y catálogo combinado.",mediaVirPodvojen:"Esta fuente ya está añadida.",mediaVirNapaka:"No se pudo leer la fuente.",mediaOsvezeno:"Fuentes actualizadas.",mediaBrezVirov:"Añade tu primera fuente web; las carpetas locales ya están incluidas.",mediaVirElementov:"{n} contenidos",zvocnikNa:"Al altavoz",zvocnikIscem:"Buscando altavoces en la red…",zvocnikNiNajdenih:"No se encontraron altavoces. Debe estar encendido y en la misma red (DLNA).",zvocnikIgra:"Suena en {ime}",zvocnikZaseden:"{ime} reproduce {vir} – pulsa otra vez para cambiar",zvocnikNaslov:"En altavoz: {ime}",zvocnikPremor:"Pausa / continuar",zvocnikNazaj:"Volver a este ordenador",zvocnikNiVir:"El altavoz no puede reproducir este contenido."},
    fr: { mediaPredaja:"Continuer depuis un autre appareil",mediaPredajaOpis:"Ce qu'un autre appareil lit ou a regardé en dernier – continuer ici à la même seconde.",mediaPredajaVprasam:"Interrogation des appareils …",mediaPredajaNic:"Aucun appareil du Safeer Link ne lit quoi que ce soit en ce moment.",mediaPredajaIgra:"en lecture",mediaPredajaNazadnje:"dernier",mediaPredajaTukaj:"Continuer ici",mediaPredajaTukajUstavi:"Continuer ici et arrêter là-bas",mediaPredajaNapaka:"Impossible d'interroger les appareils.",mediaOpis:"Films, séries et musique de toutes vos sources dans un catalogue.",mediaOsvezi:"Actualiser les sources",mediaNastavitve:"Paramètres",mediaNastavitveNaslov:"Paramètres Safeer Media",mediaNastavitveOpis:"Importer et exporter des bibliothèques JSON et gérer les sources.",mediaUvozDatoteke:"Téléverser le fichier JSON exporté",mediaUvozDatotekeOpis:"Sélectionnez un fichier .json de catalogue ou de sources précédemment exporté.",mediaIzberiDatoteko:"Choisir un fichier .json",mediaNobenaDatoteka:"Aucun fichier sélectionné",mediaUvoziDatoteko:"Importer le fichier",mediaVnosJson:"Ajoutez votre propre code JSON",mediaVnosJsonOpis:"Collez une liste JSON de médias, une configuration personnalisée ou des flux.",mediaJsonImePh:"Nom de la source (facultatif)",mediaUvoziKodo:"Importer le code JSON",mediaVstaviPrimer:"Exemple de code",mediaPocisti:"Effacer",mediaPrimerVstavljen:"Exemple de code JSON inséré avec succès.",mediaIzvozJson:"Exporter le catalogue en JSON",mediaIzvozJsonOpis:"Téléchargez la collection complète de vos sources et paramètres.",mediaPrenesiIzvoz:"Télécharger le JSON exporté",mediaUvozUspesen:"Importation réussie : {n} éléments dans '{vir}'.",mediaUvozVirovUspesen:"Sources mises à jour/ajoutées : {n}.",mediaUvozNapaka:"Erreur lors de l'importation du JSON.",mediaVnesiteJson:"Veuillez entrer ou sélectionner un code JSON valide.",mediaPredvaja:"LECTURE DANS SAFEER OS",mediaNapaka:"Ce flux ne peut pas être lu. Essayez une autre version.",mediaIsci:"Rechercher films, séries et musique",mediaVse:"Tout",mediaFilmi:"Films",mediaSerije:"Séries",mediaGlasba:"Musique",mediaPrazno:"Aucun résultat. Ajoutez une source ou modifiez la recherche.",mediaViri:"Vos sources",mediaViriOpis:"Ajoutez un site, une API publique, un RSS ou M3U une seule fois.",mediaVirIme:"Nom de la source (facultatif)",mediaVirUrl:"https://exemple.fr/catalogue.json",mediaDodaj:"Ajouter la source",mediaZadetkov:"{n} contenus uniques",mediaRazlicic:"{n} versions",mediaVirDodan:"Source ajoutée et catalogue fusionné.",mediaVirPodvojen:"Cette source est déjà ajoutée.",mediaVirNapaka:"La source n’a pas pu être lue.",mediaOsvezeno:"Sources actualisées.",mediaBrezVirov:"Ajoutez votre première source web ; les dossiers locaux sont inclus.",mediaVirElementov:"{n} contenus",zvocnikNa:"Vers l'enceinte",zvocnikIscem:"Recherche d'enceintes sur le réseau…",zvocnikNiNajdenih:"Aucune enceinte trouvée. Elle doit être allumée et sur le même réseau (DLNA).",zvocnikIgra:"Lecture sur {ime}",zvocnikZaseden:"{ime} lit {vir} – appuyez encore pour basculer",zvocnikNaslov:"Sur l'enceinte : {ime}",zvocnikPremor:"Pause / reprendre",zvocnikNazaj:"Revenir sur cet ordinateur",zvocnikNiVir:"L'enceinte ne peut pas lire ce contenu."},
    it: { mediaPredaja:"Continua da un altro dispositivo",mediaPredajaOpis:"Ciò che un altro dispositivo riproduce o ha visto per ultimo – continua qui allo stesso secondo.",mediaPredajaVprasam:"Chiedo ai dispositivi …",mediaPredajaNic:"Nessun dispositivo in Safeer Link sta riproducendo qualcosa ora.",mediaPredajaIgra:"in riproduzione",mediaPredajaNazadnje:"ultimo",mediaPredajaTukaj:"Continua qui",mediaPredajaTukajUstavi:"Continua qui e ferma lì",mediaPredajaNapaka:"Impossibile chiedere ai dispositivi.",mediaOpis:"Film, serie e musica da tutte le fonti in un solo catalogo.",mediaOsvezi:"Aggiorna fonti",mediaNastavitve:"Impostazioni",mediaNastavitveNaslov:"Impostazioni Safeer Media",mediaNastavitveOpis:"Importa ed esporta librerie JSON e gestisci le fonti.",mediaUvozDatoteke:"Carica file JSON esportato",mediaUvozDatotekeOpis:"Seleziona un file .json di catalogo o fonti precedentemente esportato.",mediaIzberiDatoteko:"Scegli file .json",mediaNobenaDatoteka:"Nessun file selezionato",mediaUvoziDatoteko:"Importa file",mediaVnosJson:"Aggiungi il tuo codice JSON",mediaVnosJsonOpis:"Incolla un elenco JSON di contenuti multimediali, configurazioni o flussi.",mediaJsonImePh:"Nome fonte (facoltativo)",mediaUvoziKodo:"Importa codice JSON",mediaVstaviPrimer:"Esempio di codice",mediaPocisti:"Cancella",mediaPrimerVstavljen:"Esempio di codice JSON inserito con successo.",mediaIzvozJson:"Esporta catalogo in JSON",mediaIzvozJsonOpis:"Scarica l'intera raccolta delle tue fonti e impostazioni.",mediaPrenesiIzvoz:"Scarica JSON esportato",mediaUvozUspesen:"Importato con successo: {n} contenuti in '{vir}'.",mediaUvozVirovUspesen:"Fonti aggiornate/aggiunte con successo: {n}.",mediaUvozNapaka:"Errore durante l'importazione di JSON.",mediaVnesiteJson:"Inserisci o seleziona un codice JSON valido.",mediaPredvaja:"RIPRODUZIONE IN SAFEER OS",mediaNapaka:"Impossibile riprodurre questo flusso. Prova un’altra versione.",mediaIsci:"Cerca film, serie e musica",mediaVse:"Tutto",mediaFilmi:"Film",mediaSerije:"Serie",mediaGlasba:"Musica",mediaPrazno:"Nessun risultato. Aggiungi una fonte o cambia la ricerca.",mediaViri:"Le tue fonti",mediaViriOpis:"Aggiungi sito, API pubblica, RSS o M3U una sola volta.",mediaVirIme:"Nome fonte (facoltativo)",mediaVirUrl:"https://esempio.it/catalogo.json",mediaDodaj:"Aggiungi fonte",mediaZadetkov:"{n} contenuti unici",mediaRazlicic:"{n} versioni",mediaVirDodan:"Fonte aggiunta e catalogo unificato.",mediaVirPodvojen:"Questa fonte è già stata aggiunta.",mediaVirNapaka:"Impossibile leggere la fonte.",mediaOsvezeno:"Fonti aggiornate.",mediaBrezVirov:"Aggiungi la prima fonte web; le cartelle locali sono già incluse.",mediaVirElementov:"{n} contenuti",zvocnikNa:"Sulla cassa",zvocnikIscem:"Ricerca casse nella rete…",zvocnikNiNajdenih:"Nessuna cassa trovata. Deve essere accesa e nella stessa rete (DLNA).",zvocnikIgra:"In riproduzione su {ime}",zvocnikZaseden:"{ime} riproduce {vir} – premi di nuovo per passare",zvocnikNaslov:"Sulla cassa: {ime}",zvocnikPremor:"Pausa / riprendi",zvocnikNazaj:"Torna a questo computer",zvocnikNiVir:"La cassa non può riprodurre questo contenuto."}
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
    if (typeof S !== "undefined" && S.povezava) narisiHeroLink();
    document.querySelectorAll("svg[data-ikona]").forEach(function (el) {
      el.setAttribute("viewBox", "0 0 24 24");
      el.innerHTML = '<path d="' + (IK[el.getAttribute("data-ikona")] || "") + '"/>';
    });
    vrsticaUredi();
  }

  /* Zlozljiva stranska vrstica: gumb v glavi ali Ctrl+B, kot v brskalnikih. */
  function vrsticaUredi() {
    var gumb = document.getElementById("gumbVrstica");
    if (!gumb) return;
    var skrcena = document.body.classList.contains("vrstica-skrcena");
    gumb.setAttribute("aria-expanded", skrcena ? "false" : "true");
    gumb.title = t(skrcena ? "vrsticaRazsiri" : "vrsticaSkrci");
    gumb.setAttribute("aria-label", gumb.title);
    if (gumb.dataset.vezan) return;
    gumb.dataset.vezan = "1";
    gumb.addEventListener("click", vrsticaPreklopi);
    document.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && (e.key === "b" || e.key === "B")) {
        e.preventDefault();
        // Skrita vrstica se s Ctrl+B najprej pokaze (kot v brskalnikih), sicer se skrci/razsiri.
        if (document.body.classList.contains("vrstica-skrita")) vrsticaSkrij(false); else vrsticaPreklopi();
      }
    });
    var skrij = document.getElementById("gumbSkrijVrstico"), rocaj = document.getElementById("rocajVrstice");
    if (skrij) skrij.addEventListener("click", function () { vrsticaSkrij(true); });
    if (rocaj) rocaj.addEventListener("click", function () { vrsticaSkrij(false); });
  }
  function vrsticaSkrij(da) {
    document.body.classList.toggle("vrstica-skrita", !!da);
    try { localStorage.setItem("safeer_vrstica_skrita", da ? "1" : "0"); } catch (e) {}
    var rocaj = document.getElementById("rocajVrstice");
    if (rocaj) { rocaj.title = t("vrsticaPokazi"); rocaj.setAttribute("aria-label", rocaj.title); }
    if (document.body.classList.contains("nacin-splet")) {
      try { var _p = klic("skrijStransko", [!!da]); if (_p && _p.catch) _p.catch(function () {}); } catch (e) {}
    }
    if (!da) { var izbran = document.querySelector("#meni button.izbran"); if (izbran) izbran.focus(); }
  }
  function vrsticaPreklopi() {
    var skrcena = document.body.classList.toggle("vrstica-skrcena");
    try { localStorage.setItem("safeer_vrstica_skrcena", skrcena ? "1" : "0"); } catch (e) {}
    vrsticaUredi();
  }
  try { if (localStorage.getItem("safeer_vrstica_skrcena") === "1") document.body.classList.add("vrstica-skrcena"); } catch (e) {}
  try { if (localStorage.getItem("safeer_vrstica_skrita") === "1") document.body.classList.add("vrstica-skrita"); } catch (e) {}

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
    sporocilaSkupine: [], sporocilaKanali: [], sporocilaFilter: "", sporocilaAktivni: null, urejaniKanal: null,
    zacetek: null, programi: [], skupina: "vse", programIskanje: "", razdelek: "domov", pot: "", stanje: null,
    // Multi-host: programi drugih naprav v Safeer Linku (id naprave -> seznam), izbrana naprava ("" = ta racunalnik).
    naprave: [], iskalneNaprave: [], programiNaprav: {}, nalagam: {}, naprava: "",
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
    if (document.body.classList.contains("nacin-splet") && razdelek !== "splet") {
      klic("zapriSplet", [razdelek]);
    }
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
      narisiNastavitve(); nalozScit(); scitZanka(); naloziMedia(); nalozPosodobitve(false);
      naloziMediaWatchSettings();
      var mediaPlosca = $("mediaNastavitvePlosca"), mediaMesto = $("mediaNastavitveMesto");
      if (mediaPlosca && mediaMesto && mediaPlosca.parentNode !== mediaMesto) mediaMesto.appendChild(mediaPlosca);
      if (mediaPlosca) mediaPlosca.hidden = false;
    }
    if (razdelek === "programi") nalozNaprave();
    if (razdelek === "sporocila") { naloziSporocila(); sporocilaZanka(); }
    if (razdelek === "zapiski") naloziZapiske(function (seznam) {
      if (!Z.aktivni && seznam.length) odpriZapisek(seznam[0].id);
    });
    if (razdelek === "omrezje") nalozOmrezje(false);
    if (razdelek === "zvok") { nalozZvok(); zvokZanka(); if (!jblStanje) nalozJbl(); }
    if (razdelek === "media") { naloziMedia(); osveziDvdPogon(); }
    if (razdelek === "splet") {
      narisiSpletnoZacetno();
      // Splet je vdelan Safeer Browser (zacetna stran Splet) - enako na vseh razlicicah Safeer OS.
      if (!document.body.classList.contains("nacin-splet")) klic("vrniSplet");
    }
  }
  function odpriSpletnoIskanje(niz) {
    if ($("spletVnos")) $("spletVnos").value = String(niz || "").trim();
    pojdi("splet");
    klic("iskanjeSplet", [String(niz || "").trim()]);
  }
  function otvoriSpletnoStran(url, ime, vednoNotri) {
    if ($("spletVnos")) $("spletVnos").value = url;
    zabeleziNedavno({ vrsta: "stran", url: url, ime: ime });
    if (vednoNotri) pojdi("splet");
    klic(vednoNotri ? "spletNotranji" : "splet", [url]).then(function (r) {
      // Storitve z DRM (Netflix ...) odpre Edge, ker vgrajeni pogon nima Widevine.
      if (r && r.zunanje) { obvesti((ime || imeIzNaslova(url)) + " se odpira v " + r.brskalnik + " (zaščitena vsebina, DRM)."); return; }
      if (!vednoNotri) pojdi("splet");
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
    if (s_ < 60) return t("pravkar");
    if (s_ < 3600) return t("predMin", { n: Math.floor(s_ / 60) });
    if (s_ < 86400) return t("predH", { n: Math.floor(s_ / 3600) });
    return t("predD", { n: Math.floor(s_ / 86400) });
  }
  function narisiDomaceNedavne() {
    var cilj = $("domaceNedavne");
    if (!cilj) return;
    cilj.innerHTML = "";
    var seznam = S.nedavneApp || [];
    if (!seznam.length) {
      cilj.appendChild(el("p", "drobno", ubezi(t("nedavnePrazno"))));
      return;
    }
    var prostora = Math.max(3, Math.floor(((cilj.clientHeight || 240) + 8) / 52));
    seznam.slice(0, prostora).forEach(function (v) {
      var b = el("button", "nedavna-vrstica");
      b.appendChild(v.vrsta === "program" ? slikaAliCrka(v.ikona, v.ime) : crka(v.ime));
      var opis = v.vrsta === "program" ? (v.ime_naprave ? t("vrstaProgram") + " · " + v.ime_naprave : t("vrstaProgram"))
               : v.vrsta === "spletna" ? t("vrstaSpletna") : imeIzNaslova(v.url);
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
  window.safeerOsRazdelek = function () { return S.razdelek || ""; };
  // Straza pomnilnika (Safeer OS) vmesnik obcasno nalozi znova. Sredi dela tega ne sme: prekinilo bi predvajanje,
  // izbrisalo napisano besedilo ali zaprlo vprasanje, na katero se nisi odgovoril. Vrne razlog ali prazen niz.
  window.safeerOsZaseden = function () {
    try {
      var p = $("mediaPredvajalnik");
      if (p && !p.hidden) return "predvajanje";
      if ([].some.call(document.querySelectorAll("video, audio"), function (m) { return !m.paused && !m.ended; })) return "predvajanje";
      if (document.querySelector(".sloj-koda-prijave")) return "vprasanje";
      var a = document.activeElement;
      if (a && a.value && (a.tagName === "TEXTAREA" || (a.tagName === "INPUT" && a.type !== "password"))) return "vnos";
    } catch (e) {}
    return "";
  };
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
    // Samo ob spremembi: vsako pisanje (tudi enakega besedila) sprozi izris strani (1x na sekundo).
    nastaviBesedilo($("ura"), zdaj.toLocaleTimeString(lok, { hour: "2-digit", minute: "2-digit" }));
    nastaviBesedilo($("datum"), zdaj.toLocaleDateString(lok, { weekday: "short", day: "numeric", month: "short" }));
    var h = zdaj.getHours();
    var ime = S.zacetek ? String(S.zacetek.ime || "").split(" ")[0] : "";
    var kljuc = h < 11 ? "jutro" : (h < 18 ? "dan" : "vecer");
    var pozdrav = t(kljuc, { ime: ime });
    if (!ime) pozdrav = pozdrav.replace(/,\s*!/, "!");
    nastaviBesedilo($("pozdrav"), pozdrav);
  }
  function nastaviBesedilo(e, besedilo) { if (e && e.textContent !== besedilo) e.textContent = besedilo; }

  // ------------------------------------------------------------------ programi
  function nalozPrograme() {
    return klic("programi").then(function (seznam) {
      S.programi = seznam || [];
      narisiPrograme();
      narisiDomov();
    }, function () {});
  }
  function zazeni(p) {
    // Program druge naprave se privzeto odpre TUKAJ (oddaljeno namizje: naprava ga zazene na
    // navideznem zaslonu in pretaka sliko). Zagon na sami napravi je izbira z ikono na ploscici.
    if (p.naprava) { odpriTukaj(p); return; }
    obvesti(t("odpiram", { ime: p.ime }));
    zazeniLokalno(p);
  }
  function zazeniNaSamiNapravi(p) {
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
  }
  function zazeniLokalno(p) {
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
      if (!r || !r.ok) { obvesti(r && r.message ? r.message : t("niUspelo")); return; }
      if (!r.tu) obvesti(t("napravaNePretaka", { ime: p.ime, naprava: n.ime }));
      zabeleziNedavno({ vrsta: "program", id: p.id, ime: p.ime, ikona: p.ikona, naprava: p.naprava, ime_naprave: n.ime });
    }, function () { obvesti(t("niUspelo")); });
  }
  function ploscicaPrograma(p, zPripenjanjem, naDomacem) {
    var b = el("button", "ploscica");
    b.title = p.opis || p.ime;
    b.appendChild(slikaAliCrka(p.ikona, p.ime));
    b.appendChild(el("span", "ime", ubezi(p.ime)));
    b.addEventListener("click", function () { zazeni(p); });
    if (p.naprava) {
      var tam = el("span", "pripni", svg("zaslon"));
      tam.title = t("zazeniNaNapravi");
      tam.addEventListener("click", function (e) { e.stopPropagation(); zazeniNaSamiNapravi(p); });
      b.appendChild(tam);
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
  function narisiHeroLink() {
    var st = $("heroLinkStanje"), pod = $("heroLinkPod");
    if (!st || !pod) return;
    var povezan = S.povezava && S.povezava.stanje === "povezan";
    st.textContent = povezan ? t("linkPovezano") : t("linkNiPovezan");
    pod.textContent = !povezan ? t("linkPovezi") : (S.heroStevilo == null ? "" : t("linkNapraveN", { n: S.heroStevilo }));
  }
  // Stevilo drugih naprav v Linku za kartico na Domov; Control je ob zagonu lahko se prazen, zato nekajkrat ponovi.
  function prestejHeroNaprave(poskus) {
    klic("vseNaprave").then(function (seznam) {
      var n = zdruziSorodnike(seznam || []).filter(function (x) { return !x.ta; }).length;
      if (!n && poskus < 8) { setTimeout(function () { prestejHeroNaprave(poskus + 1); }, 4000); return; }
      S.heroStevilo = n;
      narisiHeroLink();
    }, function () { if (poskus < 8) setTimeout(function () { prestejHeroNaprave(poskus + 1); }, 4000); });
  }
  function nalozNaprave() {
    if (S.povezava.stanje !== "povezan") { S.naprave = []; narisiPrograme(); return; }
    klic("napraveSProgrami").then(function (n) {
      S.naprave = n || [];
      if (S.naprava && !S.naprave.some(function (x) { return x.id === S.naprava; })) S.naprava = "";
      narisiPrograme();
      S.naprave.forEach(function (x) {
        var shranjeni = S.programiNaprav[x.id];
        if (!shranjeni || (shranjeni.length && shranjeni.every(function (p) { return !p.ikona; }))) nalozProgrameNaprave(x.id);
      });
    }, function () {});
  }
  function osveziIskalneNaprave() {
    klic("vseNaprave").then(function (seznam) { S.iskalneNaprave = zdruziSorodnike(seznam || []); }, function () {});
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
    var iskano = String(S.programIskanje || "").trim().toLocaleLowerCase();
    var prikazani = programi.filter(function (p) {
      if (S.skupina !== "vse" && p.skupina !== S.skupina) return false;
      return !iskano || [p.ime, p.splosno, p.opis, (p.kljucne || []).join(" ")].join(" ").toLocaleLowerCase().indexOf(iskano) >= 0;
    });
    prikazani.forEach(function (p, i) {
      var ploscica = ploscicaPrograma(p, !p.naprava);
      if (iskano && prikazani.length === 1 && i === 0) ploscica.classList.add("iskalni-zadetek");
      mreza.appendChild(ploscica);
    });
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
      cilj.appendChild(el("p", "drobno", ubezi(t("spletnePrazno"))));
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
      var vec = el("button", "ploscica vec-aplikacij", svg("programi") + '<span class="ime">' + ubezi(t("vecAplikacij")) + '</span><span class="vec-stevilo">+' + (seznam.length - prikazi) + "</span>");
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
    if (!jeMapa) b._linkDatoteka = d;
    b.innerHTML = svg(IKONA_VRSTE[vrsta] || "datoteka") + '<span class="ime">' + ubezi(imeDat) + '</span>' +
      '<span class="pod">' + (jeMapa ? "" : ubezi(velikost(d.size || d.velikost || 0)) + " · ") + ubezi(datum(d.mtime || d.spremenjeno || 0)) + '</span>';

    if (jeMapa) {
      b.addEventListener("click", function () {
        S.daljinskaPot.push({ id: idDat, ime: imeDat });
        naloziMapoNaprave(idNaprave, idDat, imeDat);
      });
    } else {
      b.addEventListener("click", function () {
        if (server && server.base_url && (vrsta === "zvok" || vrsta === "video")) {
          // Glasba in video: predvajanje takoj, sproti z naprave (brez prenosa); zvok z vrsto cele mape.
          predvajajZNaprave(idNaprave, d, server);
          return;
        }
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

  // Datoteke druge naprave, ki jih predvajamo sproti: id "link:<naprava>:<datoteka>" -> podatki za klic.
  S.linkMediji = S.linkMediji || {};
  function predvajajZNaprave(idNaprave, d, server, izVrste) {
    var idDat = d.id || "";
    var vrsta = normalizirajVrsto(d.type || d.vrsta, false) === "zvok" ? "audio" : "video";
    var kljuc = "link:" + idNaprave + ":" + idDat;
    S.linkMediji[kljuc] = { naprava: idNaprave, d: d, server: server };
    if (!izVrste && vrsta === "audio") {
      // Vrsta = vse skladbe te mape (album): po koncu samodejno naslednja, kot pri lokalni glasbi.
      var skladbe = Array.prototype.slice.call(document.querySelectorAll("#vsebinaMape .vrstica"))
        .map(function (el) { return el._linkDatoteka; }).filter(function (x) { return x && normalizirajVrsto(x.type || x.vrsta, false) === "zvok"; });
      skladbe.forEach(function (x) { S.linkMediji["link:" + idNaprave + ":" + x.id] = { naprava: idNaprave, d: x, server: server }; });
      media.vrsta = skladbe.map(function (x) { return "link:" + idNaprave + ":" + x.id; });
      media.vrstaMesto = Math.max(0, media.vrsta.indexOf(kljuc));
      media.vrstaZgodovina = [];
      narisiVrsto();
    }
    // 7. argument: podnapisi ob videu na napravi (polje subtitles seznama datotek).
    klic("predvajajDatotekoNaprave", [idNaprave, idDat, d.name || d.ime || "", server, vrsta, d.mime || "",
                                      Array.isArray(d.subtitles) ? d.subtitles : []]).then(function (item) {
      if (!item || !item.ok) { obvesti((item && item.napaka) || t("mediaVirNapaka")); return; }
      media.aktivni = item;
      if (!izVrste && window.safeerOsPojdi) window.safeerOsPojdi("media");
      if (!item.native) { predvajajHtml(item, 0); return; }
      // Predvaja VLC (npr. M4A/AAC, video): zvok v strani utihne, da ne igrata dva hkrati.
      var a = $("mediaAudio"); if (a) { a.pause(); a.removeAttribute("src"); }
      osveziMini();
    }, function () { obvesti(t("mediaVirNapaka")); });
  }

  // ------------------------------------------------------------------ Safeer Media: magnet povezave
  // Magnet (BitTorrent): prikaz vsebine, predvajanje že med prenosom, prenos, pošiljanje na napravo in
  // deljenje lastnih datotek. Motor je rqbit na 127.0.0.1 z geslom (core/os_torrent.py), enako kot na Linuxu.
  S.magnet = { opis: null, casovnik: 0 };
  function magnetVelikost(b) {
    b = Number(b) || 0;
    if (b >= 1073741824) return (b / 1073741824).toFixed(1) + " GB";
    if (b >= 1048576) return Math.round(b / 1048576) + " MB";
    return Math.max(1, Math.round(b / 1024)) + " kB";
  }
  function magnetNapaka(koda) {
    var k = "magnetNapaka_" + (koda || "napaka"), s = t(k);
    return s === k ? t("magnetNapaka_napaka") : s;
  }
  function magnetSporocilo(besedilo, razred) {
    var v = $("magnetVsebina"); v.innerHTML = "";
    if (besedilo) v.appendChild(el("p", razred || "drobno", ubezi(besedilo)));
  }
  function magnetGumb(besedilo, dejanje, razred) {
    var g = el("button", razred || "", ubezi(besedilo)); g.type = "button";
    g.addEventListener("click", function (e) { e.stopPropagation(); dejanje(g); });
    return g;
  }
  // "Nadaljuj z druge naprave" na tem racunalniku: Control vprasa naprave (play.state), izbira igra tu pri isti sekundi.
  function odpriPredajo() {
    $("slojPredaja").classList.add("viden");
    var seznam = $("predajaSeznam"); seznam.innerHTML = "";
    seznam.appendChild(el("p", "drobno", ubezi(t("mediaPredajaVprasam"))));
    klic("predajaPoizvedi").then(function (r) {
      var ponudbe = r && Array.isArray(r.ponudbe) ? r.ponudbe : [];
      seznam.innerHTML = "";
      if (!ponudbe.length) { seznam.appendChild(el("p", "drobno", ubezi(t("mediaPredajaNic")))); return; }
      ponudbe.forEach(function (p) {
        var v = el("div", "magnet-vrstica", svg("naprave") + "<div><b>" + ubezi((p.naprava && p.naprava.ime) || "") + "</b><small>" +
          ubezi(p.opis + " · " + t(p.igra ? "mediaPredajaIgra" : "mediaPredajaNazadnje")) + "</small></div>");
        var tukaj = el("button", "gumb glavni", ubezi(t("mediaPredajaTukaj"))); tukaj.type = "button";
        tukaj.addEventListener("click", function () { prevzemiPredajo(p, false); });
        v.appendChild(tukaj);
        if (p.igra) {
          // Izvor ne ustavi sam: uporabnik izbere, ali tam tece naprej (druga oseba gleda) ali se ustavi.
          var ustavi = el("button", "gumb", ubezi(t("mediaPredajaTukajUstavi"))); ustavi.type = "button";
          ustavi.addEventListener("click", function () { prevzemiPredajo(p, true); });
          v.appendChild(ustavi);
        }
        seznam.appendChild(v);
      });
    }).catch(function () { seznam.innerHTML = ""; seznam.appendChild(el("p", "drobno", ubezi(t("mediaPredajaNapaka")))); });
  }
  function prevzemiPredajo(p, ustaviTam) {
    klic("predajaPrevzemi", [p.naprava.id, p.podatki, !!ustaviTam]).then(function (ok) {
      if (!ok) { obvesti(t("mediaPredajaNapaka")); return; }
      $("slojPredaja").classList.remove("viden");
    }).catch(function () { obvesti(t("mediaPredajaNapaka")); });
  }
  function odpriMagnet(uri, samodejno) {
    if (window.safeerOsPojdi && S.razdelek !== "media") window.safeerOsPojdi("media");
    $("slojMagnet").classList.add("viden");
    magnetSporocilo("");
    if (uri) $("magnetPolje").value = uri;
    klic("magnetPrivzeto", [false]).then(function (je) { $("magnetPrivzeto").hidden = !!je; }).catch(function () {});
    magnetOsveziPrenose();
    if (!S.magnet.casovnik) S.magnet.casovnik = setInterval(function () {
      if (!$("slojMagnet").classList.contains("viden")) { clearInterval(S.magnet.casovnik); S.magnet.casovnik = 0; return; }
      magnetOsveziPrenose();
    }, 2000);
    // Samo povezava z naprave v krogu se prebere in predvaja sama; iz brskalnika čaka na uporabnika.
    if (uri && samodejno) preberiMagnet(uri, true);
    else if (uri) { magnetSporocilo(t("magnetPritisniOdpri")); $("magnetOdpri").focus(); }
    else $("magnetPolje").focus();
  }
  function zagotoviProgram() {
    return klic("magnetProgram").then(function (p) {
      if (!p || !p.podprto) { magnetSporocilo(t("magnetNiPodprto")); return false; }
      if (p.na_voljo) return true;
      // Enkratni prenos odprtokodnega motorja: uporabnik ve, kaj in od kod se prenaša.
      return new Promise(function (koncano) {
        var v = $("magnetVsebina"); v.innerHTML = "";
        v.appendChild(el("p", "drobno", ubezi(t("magnetProgramOpis", { mb: p.mb }))));
        v.appendChild(magnetGumb(t("magnetProgramPrenesi"), function (g) {
          g.disabled = true; g.textContent = t("magnetProgramPrenasam", { odstotek: 0 });
          S.magnet.gumbPrograma = g;
          klic("magnetPrenesiProgram").then(function (r) {
            S.magnet.gumbPrograma = null;
            if (r && r.ok) koncano(true); else { magnetSporocilo(magnetNapaka(r && r.koda)); koncano(false); }
          }).catch(function () { magnetSporocilo(magnetNapaka("prenos_programa")); koncano(false); });
        }, "gumb glavni"));
      });
    });
  }
  function preberiMagnet(uri, samodejno) {
    zagotoviProgram().then(function (ok) {
      if (!ok) return;
      magnetSporocilo(t("magnetBerem"));
      klic("magnetPreberi", [uri]).then(function (r) {
        if (!r || !r.ok) { magnetSporocilo(magnetNapaka(r && r.koda)); return; }
        S.magnet.opis = r;
        narisiMagnetOpis(r, samodejno);
      }).catch(function () { magnetSporocilo(magnetNapaka("napaka")); });
    });
  }
  function magnetIkona(vrsta) {
    return vrsta === "video" ? "video" : vrsta === "audio" ? "glasba" : vrsta === "slika" ? "slika" : vrsta === "nevarno" ? "scit" : "datoteka";
  }
  function narisiMagnetOpis(r, samodejno) {
    var v = $("magnetVsebina"); v.innerHTML = "";
    v.appendChild(el("p", "", "<b>" + ubezi(r.ime || r.hash) + "</b>"));
    if (r.sumljiv) v.appendChild(el("div", "magnet-opozorilo", ubezi(t("magnetSumljiv"))));
    var seznam = el("div", "magnet-seznam");
    var izbire = [];
    r.datoteke.forEach(function (f) {
      var vrstica = el("div", "magnet-vrstica");
      var izbira = el("input"); izbira.type = "checkbox"; izbira.checked = !!f.izbrana;
      izbira.setAttribute("aria-label", f.ime);
      var zapis = { f: f, el: izbira, potrjena: false };
      izbire.push(zapis);
      // Morda program: privzeto ne. Prepoznava se lahko zmoti, zato uporabnik po opozorilu vseeno izbere.
      if (f.vrsta === "nevarno") izbira.addEventListener("change", function () {
        var staro = vrstica.nextSibling && vrstica.nextSibling.classList && vrstica.nextSibling.classList.contains("magnet-opozorilo") ? vrstica.nextSibling : null;
        if (staro) staro.remove();
        if (!izbira.checked) { zapis.potrjena = false; return; }
        if (zapis.potrjena) return;
        izbira.checked = false;
        var o = el("div", "magnet-opozorilo", ubezi(t("magnetNevarnoOpis", { ime: f.ime.split("/").pop() })));
        var d = el("div", "magnet-dejanja");
        d.appendChild(magnetGumb(t("magnetVseeno"), function () { zapis.potrjena = true; izbira.checked = true; o.remove(); izbira.focus(); }));
        d.appendChild(magnetGumb(t("preklici"), function () { o.remove(); izbira.focus(); }));
        o.appendChild(d);
        vrstica.parentNode.insertBefore(o, vrstica.nextSibling);
      });
      vrstica.appendChild(izbira);
      vrstica.insertAdjacentHTML("beforeend", svg(magnetIkona(f.vrsta)) + '<div><b title="' + ubezi(f.ime) + '">' + ubezi(f.ime) +
        '</b><small>' + ubezi(magnetVelikost(f.velikost)) + '</small></div>');
      vrstica.appendChild(el("span", "magnet-oznaka" + (f.vrsta === "nevarno" ? " nevarno" : ""), ubezi(t("magnetVrsta_" + f.vrsta))));
      if (f.predvajljivo) vrstica.appendChild(magnetGumb("▶ " + t("magnetPredvajaj"), function () { predvajajMagnet(r.uri, f); }));
      seznam.appendChild(vrstica);
    });
    v.appendChild(seznam);
    var dejanja = el("div", "magnet-dejanja");
    dejanja.appendChild(magnetGumb(t("magnetPrenesiIzbrane"), function (g) {
      var izbrane = izbire.filter(function (x) { return x.el.checked && (x.f.vrsta !== "nevarno" || x.potrjena); }).map(function (x) { return x.f.i; });
      var potrjene = izbire.filter(function (x) { return x.potrjena && x.el.checked; }).map(function (x) { return x.f.i; });
      if (!izbrane.length) { obvesti(magnetNapaka("ni_izbranih")); return; }
      g.disabled = true;
      klic("magnetDodaj", [r.uri, izbrane, potrjene]).then(function (d) {
        g.disabled = false;
        obvesti(d && d.ok ? t("magnetPrenasam") : magnetNapaka(d && d.koda));
        magnetOsveziPrenose();
      }).catch(function () { g.disabled = false; obvesti(magnetNapaka("napaka")); });
    }));
    magnetPosiljanje(dejanja, function () { return r.uri; });
    v.appendChild(dejanja);
    if (samodejno) {
      // Z druge naprave ali iz brskalnika: en sam posnetek (ali ena skladba) se začne predvajati takoj.
      var predvajljive = r.datoteke.filter(function (f) { return f.predvajljivo; });
      var videi = predvajljive.filter(function (f) { return f.vrsta === "video"; });
      if (predvajljive.length === 1) predvajajMagnet(r.uri, predvajljive[0]);
      else if (videi.length === 1) predvajajMagnet(r.uri, videi[0]);
    }
  }
  function magnetPosiljanje(dejanja, uri) {
    // Pošlji na drugo napravo v Linku (tam se odpre v predvajalniku) ali kopiraj za deljenje z drugimi.
    var izbor = el("select"); izbor.setAttribute("aria-label", t("magnetPoslji"));
    izbor.appendChild(el("option", "", ubezi(t("magnetPosljiNa"))));
    klic("magnetNaprave").then(function (naprave) {
      (naprave || []).forEach(function (n) { var o = el("option", "", ubezi(n.ime || n.id)); o.value = n.id; izbor.appendChild(o); });
      if (!(naprave || []).length) izbor.disabled = true;
    }).catch(function () { izbor.disabled = true; });
    izbor.addEventListener("change", function () {
      var id = izbor.value, ime = izbor.options[izbor.selectedIndex].textContent;
      if (!id) return;
      klic("magnetNaNapravo", [id, uri()]).then(function (r) {
        obvesti(r && r.ok ? t("magnetPoslano", { naprava: ime }) : t("magnetNiPoslano"));
      }).catch(function () { obvesti(t("magnetNiPoslano")); });
      izbor.selectedIndex = 0;
    });
    dejanja.appendChild(izbor);
    dejanja.appendChild(magnetGumb(t("magnetKopiraj"), function () {
      klic("kopiraj", [uri()]).then(function () { obvesti(t("magnetKopirano")); });
    }));
  }
  function poMagnetPredvajanju(p, video) {
    // Windows: video predvaja VLC (LibVLC), brez njega predvajalnik strani; zvok kot pri napravah v Linku.
    if (!p || !p.ok) { obvesti(magnetNapaka(p && p.koda)); return; }
    if (!p.native) {
      if (video) zapriSloje();
      media.aktivni = p;
      predvajajHtml(p, 0);
    } else {
      if (video) zapriSloje();
      else { var a = $("mediaAudio"); if (a) { a.pause(); a.removeAttribute("src"); } media.aktivni = p; osveziMini(); }
    }
    magnetOsveziPrenose();
  }
  function predvajajMagnet(uri, f) {
    obvesti(t("magnetZaganjam"));
    klic("magnetDodaj", [uri, [f.i]]).then(function (d) {
      if (!d || !d.ok) { obvesti(magnetNapaka(d && d.koda)); return; }
      klic("magnetPredvajaj", [d.id, f.i, f.ime]).then(function (p) { poMagnetPredvajanju(p, f.vrsta === "video"); })
        .catch(function () { obvesti(magnetNapaka("napaka")); });
    }).catch(function () { obvesti(magnetNapaka("napaka")); });
  }
  function magnetOsveziPrenose() {
    klic("magnetSeznam").then(narisiMagnetPrenose).catch(function () {});
  }
  function narisiMagnetPrenose(seznam) {
    var v = $("magnetPrenosi");
    seznam = Array.isArray(seznam) ? seznam : [];
    var podpis = JSON.stringify(seznam.map(function (x) { return [x.id, x.stanje, x.deli_naprej, x.koncano]; }));
    if (!seznam.length) { v.innerHTML = ""; v.appendChild(el("p", "drobno", ubezi(t("magnetNiPrenosov")))); S.magnet.podpis = ""; return; }
    if (podpis !== S.magnet.podpis) {
      S.magnet.podpis = podpis; v.innerHTML = "";
      seznam.forEach(function (x) { v.appendChild(magnetVrsticaPrenosa(x)); });
    }
    seznam.forEach(function (x) {
      var vr = v.querySelector('[data-prenos="' + Number(x.id) + '"]'); if (!vr) return;
      var odst = x.skupaj ? Math.floor(100 * x.preneseno / x.skupaj) : 0;
      vr.querySelector("i").style.width = odst + "%";
      vr.querySelector("small").textContent = x.koncano ? t("magnetKoncano") + " · " + magnetVelikost(x.skupaj) :
        odst + " % · " + Number(x.hitrost_mibs || 0).toFixed(1) + " MiB/s · " + t("magnetPovezav", { n: x.povezave }) +
        (x.stanje === "paused" ? " · " + t("magnetPremor") : "");
    });
  }
  function magnetVrsticaPrenosa(x) {
    var vr = el("div", "magnet-vrstica"); vr.setAttribute("data-prenos", Number(x.id));
    vr.innerHTML = svg("povezava") + '<div><b title="' + ubezi(x.ime) + '">' + ubezi(x.ime) + '</b><small></small></div>';
    vr.appendChild(el("div", "magnet-merilo", "<i></i>"));
    var d = el("div", "magnet-dejanja");
    var prva = (x.datoteke || []).filter(function (f) { return f.predvajljivo && f.vkljucena; })[0];
    if (prva) d.appendChild(magnetGumb("▶ " + t("magnetPredvajaj"), function () {
      klic("magnetPredvajaj", [x.id, prva.i, prva.ime]).then(function (p) { poMagnetPredvajanju(p, prva.vrsta === "video"); });
    }));
    d.appendChild(magnetGumb(x.stanje === "paused" ? t("magnetNadaljuj") : t("magnetPremor"), function () {
      klic(x.stanje === "paused" ? "magnetNadaljuj" : "magnetPremor", [x.id]).then(magnetOsveziPrenose);
    }));
    d.appendChild(magnetGumb(t("magnetDeliNaprej"), function () {
      klic("magnetDeliNaprej", [x.hash, !x.deli_naprej]).then(function () {
        if (!x.deli_naprej) klic("magnetNadaljuj", [x.id]);
        magnetOsveziPrenose();
      });
    }, x.deli_naprej ? "vklopljen" : ""));
    magnetPosiljanje(d, function () { return "magnet:?xt=urn:btih:" + x.hash + "&dn=" + encodeURIComponent(x.ime); });
    d.appendChild(magnetGumb(t("magnetMapa"), function () { klic("magnetMapa", [x.mapa]); }));
    d.appendChild(magnetGumb(t("magnetOdstrani"), function () { klic("magnetOdstrani", [x.id, false]).then(magnetOsveziPrenose); }));
    if (!x.lastna) d.appendChild(magnetGumb(t("magnetIzbrisi"), function (g) {
      // Dva koraka: brisanje prenesenih datotek je nepovratno.
      if (!g.dataset.potrdi) { g.dataset.potrdi = "1"; g.textContent = t("magnetIzbrisiRes"); return; }
      klic("magnetOdstrani", [x.id, true]).then(magnetOsveziPrenose);
    }));
    vr.appendChild(d);
    return vr;
  }
  function magnetDeljen(podatki) {
    if (!podatki || !podatki.ok) { magnetSporocilo(magnetNapaka(podatki && podatki.koda)); return; }
    var v = $("magnetVsebina"); v.innerHTML = "";
    v.appendChild(el("p", "", ubezi(t("magnetDeljeno", { ime: podatki.ime }))));
    v.appendChild(el("p", "magnet-povezava", ubezi(podatki.uri)));
    var d = el("div", "magnet-dejanja"); magnetPosiljanje(d, function () { return podatki.uri; }); v.appendChild(d);
    magnetOsveziPrenose();
  }

  // ------------------------------------------------------------------ DVD brez zaščite
  // Gumb »Predvajaj disk« se pokaže samo, kadar je v pogonu DVD (core/os_dvd.py; predvaja LibVLC).
  function osveziDvdPogon() {
    if (!imaMost()) return;
    klic("dvdPogoni").then(function (pogoni) {
      var disk = (Array.isArray(pogoni) ? pogoni : []).filter(function (p) { return p.vstavljen; })[0];
      $("medijiDisk").hidden = !disk;
      S.dvdPogon = disk ? disk.naprava : "";
      if (disk) $("medijiDiskIme").textContent = t("predvajajDisk") + (disk.ime && disk.ime !== "DVD" ? " · " + disk.ime : "");
    }).catch(function () {});
  }

  // ------------------------------------------------------------------ podnapisi v predvajalniku strani
  // Brez LibVLC predvaja stran (HTML5): podnapise dobi kot WebVTT (podnapisVtt) in <track>. Samodejno kot
  // VLC: izbrani jezik, jezik vmesnika ali edini podnapis; »izklop« ostane izklopljen tudi za naslednje videe.
  var podnapisiZahteva = 0;
  function pocistiPodnapiseStrani(video) {
    podnapisiZahteva++;
    if (video) Array.prototype.slice.call(video.querySelectorAll("track")).forEach(function (tr) {
      try { URL.revokeObjectURL(tr.src); } catch (e) {}
      tr.remove();
    });
    var g = $("mediaPodnapisi"); if (g) { g.hidden = true; g.onclick = null; }
  }
  function podnapisiStrani(video, item) {
    var seznam = (item.podnapisi || []).filter(function (p) { return p && p.id; }).slice(0, 24);
    if (!video || !seznam.length) return;
    var zahteva = podnapisiZahteva, izbira = "";
    try { izbira = localStorage.getItem("safeer_podnapisi") || ""; } catch (e) {}
    var privzeti = -1;
    if (izbira !== "izklop") {
      [izbira, jezik].forEach(function (j) {
        if (privzeti < 0 && j) privzeti = seznam.findIndex(function (p) { return p.jezik === j; });
      });
      if (privzeti < 0 && (seznam.length === 1 || izbira === "vklop")) privzeti = 0;
    }
    var sledi = [];
    function izberi(i) {
      sledi.forEach(function (tr, j) { if (tr && tr.track) tr.track.mode = j === i ? "showing" : "disabled"; });
      var g = $("mediaPodnapisi"), p = seznam[i];
      if (g) g.textContent = "CC · " + (p ? (p.napis || p.ime) : t("podnapisiIzklop"));
      privzeti = i;
    }
    seznam.forEach(function (p, i) {
      klic("podnapisVtt", [p.id]).then(function (vtt) {
        if (zahteva !== podnapisiZahteva || !vtt) return;
        var tr = document.createElement("track");
        tr.kind = "subtitles"; tr.label = p.napis || p.ime || ("CC " + (i + 1));
        if (p.jezik) tr.srclang = p.jezik;
        tr.src = URL.createObjectURL(new Blob([vtt], { type: "text/vtt" }));
        video.appendChild(tr);
        sledi[i] = tr;
        izberi(privzeti);
      }).catch(function () {});
    });
    var g = $("mediaPodnapisi");
    if (!g) return;
    g.hidden = false; g.title = t("podnapisi");
    g.textContent = "CC · " + t("podnapisiIzklop");
    g.onclick = function () {
      // Kot tipka V v VLC: izklop -> prvi -> drugi ... -> izklop; izbira velja za naslednje videe.
      var nov = privzeti + 1 >= seznam.length ? -1 : privzeti + 1;
      izberi(nov);
      try { localStorage.setItem("safeer_podnapisi", nov < 0 ? "izklop" : (seznam[nov].jezik || "vklop")); } catch (e) {}
    };
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
    narisiHeroLink();
    if (povezan && !S.heroNaprave) { S.heroNaprave = true; prestejHeroNaprave(0); }
    if (!povezan) S.heroNaprave = false;
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
    if ($("stikaloPredaja") && typeof p.predajanje === "boolean") $("stikaloPredaja").setAttribute("aria-checked", p.predajanje ? "true" : "false");
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
  // Ena naprava ima lahko v Linku vec vnosov (TV: sprejemnik zaslona "n-x" in Safeer OS "n-x-os";
  // racunalnik: "pc-y" in "pc-y-control"). Uporabnik vidi eno napravo: zdruzimo jih po osnovnem id-ju,
  // obdrzimo osnovni vnos (ta zna daljinec in zaslon) in zdruzimo zmoznosti. Ta racunalnik je prvi.
  function zdruziSorodnike(naprave) {
    var poOsnovi = {}, vrstniRed = [];
    (naprave || []).forEach(function (n) {
      if (!n || !n.id) return;
      var osnova = String(n.id).replace(/-(os|control)$/, "");
      var obstojec = poOsnovi[osnova];
      if (!obstojec) { poOsnovi[osnova] = Object.assign({}, n); vrstniRed.push(osnova); return; }
      var jeOsnovni = n.id === osnova;
      var glavni = jeOsnovni ? Object.assign({}, n) : obstojec, drugi = jeOsnovni ? obstojec : n;
      var zm = (glavni.zmoznosti || []).slice();
      (drugi.zmoznosti || []).forEach(function (z) { if (zm.indexOf(z) < 0) zm.push(z); });
      glavni.zmoznosti = zm;
      glavni.ta = !!(glavni.ta || drugi.ta);
      poOsnovi[osnova] = glavni;
    });
    var izid = vrstniRed.map(function (k) { return poOsnovi[k]; });
    return izid.filter(function (n) { return n.ta; }).concat(izid.filter(function (n) { return !n.ta; }));
  }
  function narisiSeznamNaprav(pokaziSeznam) {
    var blok = $("blokSeznamNaprav");
    blok.hidden = !pokaziSeznam;
    if (!pokaziSeznam) { preimenujem = null; return; }
    klic("vseNaprave").then(function (naprave) {
      var ul = $("seznamNaprav"); ul.innerHTML = "";
      var iskano = $("napraveIskanje") ? $("napraveIskanje").value.trim().toLocaleLowerCase() : "";
      zdruziSorodnike(naprave).filter(function (n) {
        return !iskano || [n.ime, n.id, n.platforma, n.vrsta].join(" ").toLocaleLowerCase().indexOf(iskano) >= 0;
      }).forEach(function (n, indeks) {
        var li = el("li");
        if (iskano && indeks === 0) { li.classList.add("iskalni-zadetek"); li.tabIndex = -1; }
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
          var jeRacunalnik = !n.ta && (n.platforma === "linux" || n.platforma === "windows" ||
            n.platforma === "win32" || n.platforma === "macos" || n.vrsta === "computer" ||
            n.vrsta === "racunalnik" || n.vrsta === "control");
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
          if (jeRacunalnik) {
            htmlGumbi += '<button class="gumb majhen glavni gumb-oddaljeni-zaslon" style="display:inline-flex;gap:4px;align-items:center;">' +
              svg("zaslon") + '<span>' + ubezi(t("upravljajRacunalnik")) + '</span></button>';
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
          var gZaslon = li.querySelector(".gumb-oddaljeni-zaslon");
          if (gZaslon) {
            gZaslon.addEventListener("click", function () {
              obvesti(t("odpiram", { ime: n.ime || n.id }));
              klic("oddaljeniZaslon", [n.id, n.ime || n.id]);
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
    if (!kompaktno && cilj.id === "hitreNastavitve") {
      // Racunalnik brez zvoka, svetlosti in Wi-Fi (namizni PC): prazen razdelek skrijemo skupaj z naslovom.
      var prazno = !cilj.children.length, naslov = cilj.previousElementSibling;
      cilj.hidden = prazno;
      if (naslov && naslov.tagName === "H2") naslov.hidden = prazno;
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
  // ------------------------------------------------------------------ teme (videz)
  // Pet najbolj razsirjenih shem (Catppuccin, Tokyo Night, Gruvbox, Nord, Dracula - vse MIT) + privzeta Safeer.
  var TEME = [
    { id: "safeer", ime: "Safeer", opis: "temaSafeer", barve: ["#090d15", "#111924", "#54d6a5", "#f0f4f3"] },
    { id: "catppuccin", ime: "Catppuccin Mocha", opis: "catppuccin.com", barve: ["#1e1e2e", "#313244", "#94e2d5", "#cdd6f4"] },
    { id: "tokyonight", ime: "Tokyo Night", opis: "tokyonight (enkia)", barve: ["#1a1b26", "#24283b", "#73daca", "#c0caf5"] },
    { id: "gruvbox", ime: "Gruvbox Dark", opis: "gruvbox (morhetz)", barve: ["#282828", "#3c3836", "#8ec07c", "#ebdbb2"] },
    { id: "nord", ime: "Nord", opis: "nordtheme.com", barve: ["#2e3440", "#3b4252", "#88c0d0", "#eceff4"] },
    { id: "dracula", ime: "Dracula", opis: "draculatheme.com", barve: ["#282a36", "#44475a", "#8be9fd", "#f8f8f2"] }
  ];
  function trenutnaTema() { try { return localStorage.getItem("safeer_tema") || "safeer"; } catch (e) { return "safeer"; } }
  function nastaviTemo(id) {
    if (!TEME.some(function (x) { return x.id === id; })) id = "safeer";
    if (id === "safeer") document.documentElement.removeAttribute("data-tema"); else document.documentElement.setAttribute("data-tema", id);
    try { localStorage.setItem("safeer_tema", id); } catch (e) {}
    narisiTeme();
  }
  function narisiTeme() {
    var m = $("temeMreza"); if (!m) return;
    var izbrana = trenutnaTema(); m.innerHTML = "";
    TEME.forEach(function (tm) {
      var b = el("button", "tema-kartica" + (tm.id === izbrana ? " izbran" : "")); b.type = "button"; b.setAttribute("aria-pressed", tm.id === izbrana ? "true" : "false");
      var pred = el("div", "tema-predogled"); tm.barve.forEach(function (c) { var i = el("i"); i.style.background = c; pred.appendChild(i); });
      b.appendChild(pred); b.appendChild(el("b", "", ubezi(tm.ime)));
      b.appendChild(el("small", "", ubezi(tm.id === "safeer" ? t(tm.opis) : tm.opis) + (tm.id === izbrana ? " · " + ubezi(t("temaIzbrana")) : "")));
      b.addEventListener("click", function () { nastaviTemo(tm.id); });
      m.appendChild(b);
    });
  }
  // ------------------------------------------------------------------ posodobitve (safeer.si/os/razlicice.json)
  S.posodobitve = { stanje: null, zanka: 0 };
  function narisiPosodobitve(st) {
    S.posodobitve.stanje = st;
    var naslov = $("posodobitveNaslov"), pod = $("posodobitvePod"), gumb = $("gumbPosodobi");
    if (!naslov) return;
    var p = st && st.posodabljanje;
    if (p && p.tece) {
      naslov.textContent = p.faza === "namescanje" ? t("posodobitevNamescam") : t("posodobitevPrenasam", { ime: p.sporocilo || "", odstotek: p.odstotek || 0 });
      pod.textContent = "";
      gumb.disabled = true;
      return;
    }
    gumb.disabled = false;
    if (p && p.faza === "koncano") { naslov.textContent = t("posodobitevKoncano", { opis: p.sporocilo || "" }); pod.textContent = ""; return; }
    if (p && p.faza === "napaka" && p.sporocilo !== "prekinjeno") { naslov.textContent = t("posodobitevNapaka", { napaka: p.sporocilo || "" }); pod.textContent = t("posodobitevNajnovejsaPod"); return; }
    if (st && st.nove && st.nove.length) {
      naslov.textContent = t("posodobitevNaVoljo", { opis: st.opis });
      var novo = st.novo && (st.novo[jezik] || st.novo.en) ? (st.novo[jezik] || st.novo.en) + " " : "";
      pod.textContent = novo + ((st.nacin === "deb" || st.nacin === "windows") ? t("posodobitevNaVoljoPod") : (st.nacin === "flatpak" || st.nacin === "appimage") ? t("posodobitevNaVoljoFlatpak") : t("posodobitevRocnoPod"));
      return;
    }
    naslov.textContent = t("posodobitevNajnovejsa", { v: (st && st.nasa) || (S.zacetek && S.zacetek.razlicica) || "" });
    pod.textContent = st && st.napaka ? t("posodobitevNapaka", { napaka: st.napaka }) : t("posodobitevNajnovejsaPod");
  }
  function nalozPosodobitve(vsiljeno) {
    if (vsiljeno) { $("posodobitveNaslov").textContent = t("posodobitevPreverjam"); $("posodobitvePod").textContent = ""; }
    klic("posodobitveStanje", [!!vsiljeno]).then(narisiPosodobitve, function () { narisiPosodobitve(S.posodobitve.stanje); });
  }
  function posodobitveZanka() {
    if (S.posodobitve.zanka) return;
    S.posodobitve.zanka = setInterval(function () {
      klic("posodobitveStanje", [false]).then(function (st) {
        narisiPosodobitve(st);
        if (!(st.posodabljanje && st.posodabljanje.tece)) { clearInterval(S.posodobitve.zanka); S.posodobitve.zanka = 0; if (st.posodabljanje && st.posodabljanje.faza === "koncano") $("domPosodobitev").hidden = true; }
      }).catch(function () {});
    }, 1000);
  }
  function posodobi() {
    var st = S.posodobitve.stanje;
    if (!st || !st.nove || !st.nove.length) { nalozPosodobitve(true); return; }
    if (st.nacin !== "deb" && st.nacin !== "flatpak" && st.nacin !== "appimage" && st.nacin !== "windows") { klic("splet", [st.stran || "https://safeer.si/os/"]); return; }
    klic("posodobi").then(function (r) {
      if (r && r.ok) { narisiPosodobitve({ nasa: st.nasa, nove: st.nove, opis: st.opis, nacin: st.nacin, posodabljanje: { tece: true, faza: "prenos", odstotek: 0, sporocilo: "" } }); posodobitveZanka(); }
      else if (r && r.koda === "rocno") klic("splet", [r.stran || "https://safeer.si/os/"]);
      else nalozPosodobitve(true);
    }).catch(function () { obvesti(t("niUspelo")); });
  }
  // Z domacega zaslona na gumb Posodobitve v Nastavitvah. Nastavitve se narisejo v vec korakih (teme, hitre
  // nastavitve, brskalnik, viri), zato gumb v pogled premaknemo veckrat - sicer ga pozneje nalozena vsebina
  // odrine in uporabnik pristane sredi strani brez gumba.
  function naPosodobitve() {
    pojdi("nastavitve");
    [0, 250, 700, 1500].forEach(function (ms) {
      setTimeout(function () {
        var g = $("gumbPosodobi");
        if (!g || S.razdelek !== "nastavitve") return;
        if (ms === 0) { try { g.focus({ preventScroll: true }); } catch (e) { g.focus(); } }
        g.scrollIntoView({ block: "center" });
      }, ms);
    });
  }
  function pokaziPosodobitevDoma(st) {
    // Tiha opomba na domacem zaslonu, dokler uporabnik nove razlicice ne namesti (Nastavitve -> Posodobitve).
    S.posodobitve.stanje = st;
    var b = $("domPosodobitev");
    if (!b) return;
    b.hidden = !(st && st.nove && st.nove.length);
    if (!b.hidden) $("domPosodobitevNaslov").textContent = t("posodobitevNaVoljo", { opis: st.opis });
  }

  function narisiNastavitve() {
    narisiTeme();
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
  var pametniRezultati = { datoteke: [], mediji: [] };
  function jeNaslov(s) { return SafeerPametnoIskanje.jeNaslov(s); }
  function ujemanje(besedilo, niz) {
    besedilo = String(besedilo || "").toLowerCase();
    if (!besedilo) return 0;
    if (besedilo.indexOf(niz) === 0) return 3;
    if (besedilo.indexOf(" " + niz) >= 0) return 2;
    return besedilo.indexOf(niz) >= 0 ? 1 : 0;
  }
  function zadetek(ikonaEl, naslov, pod, ob, razred) {
    var b = el("button", "zadetek");
    if (razred) b.classList.add(razred);
    if (typeof ikonaEl === "string") b.innerHTML = svg(ikonaEl); else b.appendChild(ikonaEl);
    b.appendChild(el("div", "", "<b>" + ubezi(naslov) + "</b>" + (pod ? "<span>" + ubezi(pod) + "</span>" : "")));
    b.addEventListener("click", function () { zapriSloje(); ob(); });
    return b;
  }
  function naslovSkupine(cilj, kljuc) { cilj.appendChild(el("h4", "", ubezi(t(kljuc)))); }
  function podatkiPametnegaIskanja() {
    return {
      spletne: spletne(),
      programi: S.programi.concat(vsiProgramiNaprav()),
      datoteke: pametniRezultati.datoteke,
      mediji: pametniRezultati.mediji,
      naprave: [{ ime: "Safeer Link", id: "safeer-link" }].concat(S.iskalneNaprave || [], S.naprave || [], S.napraveDatoteke || []),
      sporocila: S.sporocilaSkupine || []
    };
  }
  function odpriProgramIskanje(niz, program) {
    zapriSloje();
    S.programIskanje = String(niz || "").trim();
    S.skupina = "vse";
    if (program) S.naprava = program.naprava || "";
    if ($("programiIskanje")) $("programiIskanje").value = S.programIskanje;
    pojdi("programi");
    narisiPrograme();
    setTimeout(function () {
      var prvi = $("vsiProgrami").querySelector(".ploscica");
      if (prvi) prvi.focus(); else if ($("programiIskanje")) $("programiIskanje").focus();
    }, 30);
  }
  function prikaziIskanjeDatotek(niz, seznam) {
    S.pot = "@iskanje";
    narisiMape();
    var dr = $("drobtine"); dr.innerHTML = "";
    dr.appendChild(el("b", "", ubezi(t("rezultatiIskanja", { niz: niz }))));
    var v = $("vsebinaMape"); v.innerHTML = "";
    (seznam || []).forEach(function (d, i) {
      var vrstica = vrsticaDatoteke(d, true, false);
      if (i === 0) vrstica.classList.add("iskalni-zadetek");
      v.appendChild(vrstica);
    });
    if (!(seznam || []).length) v.appendChild(el("div", "prazno", ubezi(t("niZadetkov"))));
    setTimeout(function () { var prvi = v.querySelector("button"); if (prvi) prvi.focus(); }, 30);
  }
  function odpriDatotekeIskanje(niz, seznam) {
    zapriSloje();
    S.pot = "@iskanje";
    if ($("datotekeIskanje")) $("datotekeIskanje").value = niz;
    pojdi("datoteke");
    if (seznam) prikaziIskanjeDatotek(niz, seznam);
    else klic("isciDatoteke", [niz]).then(function (r) { prikaziIskanjeDatotek(niz, r || []); });
  }
  function odpriMediaIskanje(niz) {
    zapriSloje();
    media.query = String(niz || "").trim(); media.filter = "vse"; media.page = 1;
    if ($("mediaIskanje")) $("mediaIskanje").value = media.query;
    document.querySelectorAll("[data-media-filter]").forEach(function (b) {
      var izbran = b.getAttribute("data-media-filter") === "vse";
      b.classList.toggle("izbran", izbran); b.classList.toggle("izbrana", izbran);
    });
    pojdi("media");
  }
  function odpriNapraveIskanje(niz) {
    zapriSloje();
    if ($("napraveIskanje")) $("napraveIskanje").value = niz;
    pojdi("naprave");
    setTimeout(function () {
      var prvi = document.querySelector("#seznamNaprav li.iskalni-zadetek") || $("gumbControl");
      if (prvi && prvi.focus) prvi.focus();
    }, 80);
  }
  function izvediNamero(niz) {
    var namera = SafeerPametnoIskanje.nameraIskanja(niz, podatkiPametnegaIskanja());
    if (namera.vrsta === "programi") return odpriProgramIskanje(niz, namera.zadetek);
    if (namera.vrsta === "datoteke") return odpriDatotekeIskanje(niz, pametniRezultati.datoteke);
    if (namera.vrsta === "media") return odpriMediaIskanje(niz);
    if (namera.vrsta === "naprave") return odpriNapraveIskanje(niz);
    if (namera.vrsta === "sporocila" && namera.zadetek) {
      zapriSloje(); pojdi("sporocila");
      return odpriPogovor(namera.zadetek.oseba || {}, (namera.zadetek.pogovori || [])[0]);
    }
    zapriSloje();
    if (namera.spletna) return otvoriSpletnoStran(namera.spletna.url, namera.spletna.ime, true);
    if (namera.naslov) return otvoriSpletnoStran(normalizirajNaslov(niz), niz, true);
    odpriSpletnoIskanje(niz);
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
    pametniRezultati.datoteke = [];
    pametniRezultati.mediji = [];
    // Spletne aplikacije: ime, domena in kratica (npr. yt -> YouTube).
    var spletneZ = spletne().map(function (a) {
      var ocena = SafeerPametnoIskanje.oceni(n, [a.ime, imeIzNaslova(a.url), (String(a.ime).match(/[A-ZČŠŽ]/g) || []).join("")]);
      return { a: a, ocena: ocena };
    }).filter(function (x) { return x.ocena > 0; }).sort(function (a, b) { return b.ocena - a.ocena; }).slice(0, 5);
    if (spletneZ.length) {
      naslovSkupine(z, "zSpletneAplikacije");
      spletneZ.forEach(function (x) {
        z.appendChild(zadetek(crka(x.a.ime), x.a.ime, imeIzNaslova(x.a.url), function () {
          otvoriSpletnoStran(x.a.url, x.a.ime, true);
        }, "spletni"));
      });
    }
    // Programi
    var programi = S.programi.concat(vsiProgramiNaprav()).map(function (p) {
      var ocena = ujemanje(p.ime, n) * 10 + ujemanje(p.splosno, n) * 3 + ujemanje((p.kljucne || []).join(" "), n) * 2 +
        ujemanje(p.opis, n);
      if (ocena && p.naprava) ocena -= 1;          // program tega racunalnika ima prednost pred istim na napravi
      return { p: p, ocena: ocena + (ocena ? Math.min(5, p.uporaba || 0) : 0) };
    }).filter(function (x) { return x.ocena > 0; }).sort(function (a, b) { return b.ocena - a.ocena; }).slice(0, 6);
    if (programi.length) {
      naslovSkupine(z, "zProgrami");
      programi.forEach(function (x) {
        var n2 = x.p.naprava ? S.naprave.find(function (y) { return y.id === x.p.naprava; }) : null;
        z.appendChild(zadetek(slikaAliCrka(x.p.ikona, x.p.ime), x.p.ime, n2 ? n2.ime : x.p.opis, function () { odpriProgramIskanje(x.p.ime, x.p); }));
      });
    }
    // Sporocila: osebe in pogovori (seznam nalozimo, ce razdelka se nisi odprl).
    var mestoSporocil = el("div");
    z.appendChild(mestoSporocil);
    function narisiZadetkeSporocil() {
      mestoSporocil.innerHTML = "";
      var zadetki = [];
      (S.sporocilaSkupine || []).forEach(function (sk) {
        var oseba = sk.oseba || {}, pogovori = sk.pogovori || [];
        var ocena = ujemanje(oseba.ime, n) * 10 + ujemanje((oseba.identitete || []).map(function (i) { return i[1]; }).join(" "), n) * 5;
        pogovori.forEach(function (p) { ocena += ujemanje(p.zadeva, n) * 2 + ujemanje(p.zadnje_sporocilo, n); });
        if (ocena > 0 && pogovori.length) zadetki.push({ oseba: oseba, pogovor: pogovori[0], ocena: ocena });
      });
      zadetki.sort(function (a, b) { return b.ocena - a.ocena; }).slice(0, 4).forEach(function (x, i) {
        if (i === 0) naslovSkupine(mestoSporocil, "zSporocila");
        mestoSporocil.appendChild(zadetek("sporocila", x.oseba.ime || "", x.pogovor.zadnje_sporocilo || x.pogovor.zadeva || "", function () {
          pojdi("sporocila"); odpriPogovor(x.oseba, x.pogovor);
        }));
      });
    }
    narisiZadetkeSporocil();
    if (!(S.sporocilaSkupine || []).length && imaMost()) {
      var mojSp = iskanjeStevec + 1;
      klic("sporocilaSeznam").then(function (p) {
        if (!p || mojSp !== iskanjeStevec) return;
        S.sporocilaSkupine = p.skupine || []; S.sporocilaKanali = p.kanali || [];
        narisiZadetkeSporocil();
      }).catch(function () {});
    }
    // Datoteke in mediji pridejo iz lokalnih predpomnilnikov po 250 ms.
    var mestoDatotek = el("div"), mestoMedijev = el("div");
    z.appendChild(mestoDatotek);
    z.appendChild(mestoMedijev);
    var naprave = [{ ime: "Safeer Link", platforma: "" }].concat(S.iskalneNaprave || [], S.naprave || [], S.napraveDatoteke || []).filter(function (x, i, a) {
      return a.findIndex(function (y) { return (y.id || y.ime) === (x.id || x.ime); }) === i;
    }).filter(function (x) { return ujemanje(x.ime, n) || ujemanje(x.platforma, n); }).slice(0, 5);
    if (naprave.length) {
      naslovSkupine(z, "zNaprave");
      naprave.forEach(function (x) { z.appendChild(zadetek(ikonaNaprave(x), x.ime, "Safeer Link", function () { odpriNapraveIskanje(x.ime); })); });
    }
    naslovSkupine(z, "isciSplet");
    if (jeNaslov(niz)) {
      var naslov = normalizirajNaslov(niz);
      z.appendChild(zadetek("splet", t("odpriNavedeniNaslov", { naslov: naslov }), naslov, function () { otvoriSpletnoStran(naslov, niz, true); }, "spletni"));
    }
    z.appendChild(zadetek("isci", t("isciNaSpletu", { niz: niz }), t("isciSplet"), function () { odpriSpletnoIskanje(niz); }, "spletni"));
    clearTimeout(iskanjeZamik);
    var moj = ++iskanjeStevec;
    if (n.length >= 2) {
      iskanjeZamik = setTimeout(function () {
        klic("isciDatoteke", [niz]).then(function (seznam) {
          if (moj !== iskanjeStevec) return;
          mestoDatotek.innerHTML = "";
          seznam = (seznam || []).slice(0, 8);
          pametniRezultati.datoteke = seznam;
          if (!seznam.length) return;
          naslovSkupine(mestoDatotek, "zDatoteke");
          seznam.forEach(function (d) {
            mestoDatotek.appendChild(zadetek(IKONA_VRSTE[d.vrsta] || "datoteka", d.ime, skrajsajPot(d.pot), function () { odpriDatotekeIskanje(niz, seznam); }));
          });
        }, function () { mestoDatotek.innerHTML = ""; });
        klic("mediaIsciPredpomnilnik", [niz]).then(function (seznam) {
          if (moj !== iskanjeStevec) return;
          mestoMedijev.innerHTML = ""; seznam = (seznam || []).slice(0, 8); pametniRezultati.mediji = seznam;
          if (!seznam.length) return;
          naslovSkupine(mestoMedijev, "zMediji");
          seznam.forEach(function (m) {
            mestoMedijev.appendChild(zadetek(mediaIkona(m.vrsta), m.naslov, mediaOznaka(m.vrsta), function () { odpriMediaIskanje(niz); }));
          });
        }, function () { mestoMedijev.innerHTML = ""; });
      }, 250);
    }
  }
  function zadetki() { return Array.prototype.slice.call(document.querySelectorAll("#zadetki .zadetek")); }
  function premakniIzbiro(smer) {
    var vsi = zadetki();
    if (!vsi.length) return;
    var i = vsi.findIndex(function (b) { return b.classList.contains("aktiven"); });
    if (i < 0) i = smer > 0 ? -1 : 0;
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
  // »Ne zdaj« velja 24 ur za to napravo: mreža naprave ob vsaki ponovni povezavi javi znova in
  // brez tega bi se vprašanje vračalo vsakih nekaj sekund (ni ga bilo mogoče zapreti).
  var ODLOG_DOVOLJENJA_MS = 24 * 3600 * 1000;
  function odlozenoDovoljenje(id) {
    try { return Date.now() - Number(localStorage.getItem("safeer.odlozeno." + id) || 0) < ODLOG_DOVOLJENJA_MS; }
    catch (e) { return !!(S.odlozenaDovoljenja && S.odlozenaDovoljenja[id]); }
  }
  function odloziDovoljenje(id) {
    try { localStorage.setItem("safeer.odlozeno." + id, String(Date.now())); }
    catch (e) { (S.odlozenaDovoljenja = S.odlozenaDovoljenja || {})[id] = true; }
  }
  function vprasajZaDovoljenje(n) {
    if (odlozenoDovoljenje(n.id)) return;
    if (cakajocaDovoljenja.some(function (x) { return x.id === n.id; })) return;
    cakajocaDovoljenja.push(n);
    if (cakajocaDovoljenja.length === 1) pokaziDovoljenje();
  }
  function pokaziDovoljenje() {
    var n = cakajocaDovoljenja[0];
    if (!n) return;
    var sloj = el("div", "sloj-koda-prijave");
    var okno = el("div", "koda-prijave-okno");
    var h = el("h2"); h.textContent = t("novaNapravaNaslov");
    var o = el("p"); o.textContent = t("novaNapravaVprasanje").replace("{ime}", n.ime || n.id);
    okno.appendChild(h); okno.appendChild(o);
    function naprej() {
      sloj.remove();
      cakajocaDovoljenja.shift();
      pokaziDovoljenje();
    }
    [["polno", t("dovoliVse")], ["izbrano", t("dovoliDatoteke")], ["zaslon", t("dovoliZaslon")]].forEach(function (m) {
      var g = el("button", "vrstica"); g.textContent = m[1];
      g.addEventListener("click", function () {
        klic("nastaviDovoljenje", [n.id, m[0]]).then(function (ok) {
          obvesti(ok ? t("dovoljenjeShranjeno").replace("{ime}", n.ime || t("napravaSplosno")) : t("niUspelo"));
        });
        naprej();
      });
      okno.appendChild(g);
    });
    var z = el("button", "koda-prijave-gumb"); z.textContent = t("neZdaj");
    z.addEventListener("click", function () { odloziDovoljenje(n.id); naprej(); });
    okno.appendChild(z);
    sloj.appendChild(okno);
    document.body.appendChild(sloj);
  }

  // ------------------------------------------------------------------ zapiski (po zgledu Deta Surf)
  // Omemba je v besedilu povezava [@ime](cilj); cilj je spletni naslov ali safeer:vrsta:vrednost.
  var Z = { aktivni: null, casovnik: 0, pogled: false, iskano: "", omembe: [], izbranaOmemba: 0, izbrisPotrdi: 0 };
  var OMEMBA_RE = /\[@([^\]]{1,160})\]\(([^)\s]{1,2048})\)/g;

  function naloziZapiske(potem) {
    klic("zapiskiSeznam", [Z.iskano]).then(function (seznam) {
      var mesto = $("zapiskiVrstice"); if (!mesto) return;
      mesto.innerHTML = "";
      (seznam || []).forEach(function (z) {
        var b = el("button", "zapisek-vrstica" + (Z.aktivni && Z.aktivni.id === z.id ? " izbran" : ""));
        b.innerHTML = "<b>" + (z.pripet ? "📌 " : "") + ubezi(z.naslov) + "</b><small>" + ubezi(z.odlomek || "Prazen zapisek") + "</small>";
        b.addEventListener("click", function () { odpriZapisek(z.id); });
        mesto.appendChild(b);
      });
      if (!(seznam || []).length) mesto.appendChild(el("div", "prazno", Z.iskano ? "Ni zadetkov." : "Še nimaš zapiskov."));
      if (potem) potem(seznam || []);
    });
  }
  function odpriZapisek(id) {
    klic("zapisekDobi", [id]).then(function (z) {
      if (!z) return;
      Z.aktivni = z;
      $("zapisekUrejevalnik").hidden = false;
      $("zapisekNaslov").value = z.naslov || "";
      $("zapisekBesedilo").value = z.besedilo || "";
      $("zapisekPripni").textContent = z.pripet ? "Odpni" : "Pripni";
      $("zapisekStanje").textContent = "";
      narisiViriZapiska(z);
      if (Z.pogled) narisiPogledZapiska();
      document.querySelectorAll(".zapisek-vrstica").forEach(function (b) { b.classList.remove("izbran"); });
      naloziZapiske();
    });
  }
  function cipOmembe(ime, cilj) {
    var c = el("button", "zapisek-cip"); c.type = "button";
    var ikona = /^https?:/.test(cilj) ? "🌐" : cilj.indexOf("safeer:datoteka:") === 0 ? "📄" :
      cilj.indexOf("safeer:zapisek:") === 0 ? "📝" : cilj.indexOf("safeer:program:") === 0 ? "▶" : "@";
    c.textContent = ikona + " " + ime; c.title = cilj;
    c.addEventListener("click", function () { odpriCiljZapiska(cilj); });
    return c;
  }
  function narisiViriZapiska(z) {
    var viri = $("zapisekViri"), povratne = $("zapisekPovratne");
    viri.innerHTML = ""; povratne.innerHTML = "";
    (z.omembe || []).forEach(function (o) { viri.appendChild(cipOmembe(o.ime, o.cilj)); });
    (z.povratne || []).forEach(function (p) { povratne.appendChild(cipOmembe(p.naslov, "safeer:zapisek:" + p.id)); });
    if (!viri.childNodes.length) viri.appendChild(el("span", "namig", "Z @ omeni vir."));
    if (!povratne.childNodes.length) povratne.appendChild(el("span", "namig", "Noben drug zapisek."));
  }
  function odpriCiljZapiska(cilj) {
    if (/^https?:\/\//.test(cilj)) { otvoriSpletnoStran(cilj); return; }
    var deli = cilj.split(":"), vrsta = deli[1], vrednost = deli.slice(2).join(":");
    if (vrsta === "datoteka") klic("odpriDatoteko", [vrednost]);
    else if (vrsta === "zapisek") odpriZapisek(vrednost);
    else if (vrsta === "program") {
      var p = (S.programi || []).find(function (x) { return x.id === vrednost; });
      if (p) zazeni(p); else obvesti("Programa ni več.");
    }
  }
  function shraniZapisekKmalu() {
    clearTimeout(Z.casovnik);
    $("zapisekStanje").textContent = "…";
    Z.casovnik = setTimeout(shraniZapisek, 600);
  }
  function shraniZapisek() {
    if (!Z.aktivni) return;
    var naslov = $("zapisekNaslov").value, besedilo = $("zapisekBesedilo").value;
    klic("zapisekShrani", [Z.aktivni.id, naslov, besedilo, null]).then(function () {
      Z.aktivni.naslov = naslov; Z.aktivni.besedilo = besedilo;
      $("zapisekStanje").textContent = "Shranjeno";
      klic("zapisekDobi", [Z.aktivni.id]).then(function (z) { if (z && Z.aktivni && z.id === Z.aktivni.id) narisiViriZapiska(z); });
      naloziZapiske();
    }, function () { $("zapisekStanje").textContent = "Ni shranjeno"; });
  }
  function narisiPogledZapiska() {
    var besedilo = $("zapisekBesedilo").value;
    var mesto = $("zapisekPrikaz"); mesto.innerHTML = "";
    var citat = null;
    besedilo.split("\n").forEach(function (vrstica) {
      var jeCitat = vrstica.indexOf("> ") === 0;
      var cilj = jeCitat ? (citat || (citat = mesto.appendChild(el("blockquote")))) : mesto;
      if (!jeCitat) citat = null;
      var odstavek = el("div");
      var besedilo = jeCitat ? vrstica.slice(2) : vrstica, zadnji = 0, m;
      OMEMBA_RE.lastIndex = 0;
      while ((m = OMEMBA_RE.exec(besedilo))) {
        odstavek.appendChild(document.createTextNode(besedilo.slice(zadnji, m.index)));
        odstavek.appendChild(cipOmembe(m[1], m[2]));
        zadnji = m.index + m[0].length;
      }
      odstavek.appendChild(document.createTextNode(besedilo.slice(zadnji)));
      if (!besedilo) odstavek.innerHTML = "&nbsp;";
      cilj.appendChild(odstavek);
    });
  }
  function preklopiPogledZapiska() {
    Z.pogled = !Z.pogled;
    $("zapisekBesedilo").hidden = Z.pogled;
    $("zapisekPrikaz").hidden = !Z.pogled;
    $("zapisekPogled").textContent = Z.pogled ? "Uredi" : "Pogled";
    if (Z.pogled) narisiPogledZapiska();
  }

  // --- @ omembe: med pisanjem ponudimo zapiske, nedavne strani in programe, programe in datoteke
  function iskanjeOmembe() {
    var ta = $("zapisekBesedilo"), pred = ta.value.slice(0, ta.selectionStart);
    var m = /(^|\s)@([^@\n\]\[()]{0,40})$/.exec(pred);
    return m ? { niz: m[2], zacetek: ta.selectionStart - m[2].length - 1 } : null;
  }
  function zapriOmembe() { $("zapisekOmembeOkno").hidden = true; Z.omembe = []; }
  function ponudiOmembe() {
    var q = iskanjeOmembe();
    if (!q) { zapriOmembe(); return; }
    var niz = q.niz.trim().toLocaleLowerCase(), predlogi = [];
    function ujema(ime) { return !niz || String(ime || "").toLocaleLowerCase().indexOf(niz) >= 0; }
    (S.nedavneApp || []).forEach(function (v) {
      if (v.url && ujema(v.ime)) predlogi.push({ ime: v.ime, cilj: v.url, vrsta: "Stran" });
      else if (v.vrsta === "program" && !v.naprava && ujema(v.ime)) predlogi.push({ ime: v.ime, cilj: "safeer:program:" + v.id, vrsta: "Program" });
    });
    (S.programi || []).filter(function (p) { return niz.length >= 2 && ujema(p.ime); }).slice(0, 5)
      .forEach(function (p) { predlogi.push({ ime: p.ime, cilj: "safeer:program:" + p.id, vrsta: "Program" }); });
    var moj = (Z.omembeZahteva = (Z.omembeZahteva || 0) + 1);
    klic("zapiskiSeznam", [niz]).then(function (zapiski) {
      (zapiski || []).filter(function (z) { return !Z.aktivni || z.id !== Z.aktivni.id; }).slice(0, 5)
        .forEach(function (z) { predlogi.push({ ime: z.naslov, cilj: "safeer:zapisek:" + z.id, vrsta: "Zapisek" }); });
      var datoteke = niz.length >= 2 ? klic("isciDatoteke", [niz]) : Promise.resolve([]);
      return datoteke.then(function (seznam) {
        (seznam || []).filter(function (d) { return !d.mapa; }).slice(0, 6)
          .forEach(function (d) { predlogi.push({ ime: d.ime, cilj: "safeer:datoteka:" + d.pot, vrsta: "Datoteka" }); });
      }, function () {});
    }).then(function () {
      if (moj !== Z.omembeZahteva) return;
      var videni = {};
      Z.omembe = predlogi.filter(function (p) { if (videni[p.cilj]) return false; videni[p.cilj] = 1; return true; }).slice(0, 12);
      Z.izbranaOmemba = 0;
      narisiOmembe();
    });
  }
  function narisiOmembe() {
    var okno = $("zapisekOmembeOkno"); okno.innerHTML = "";
    if (!Z.omembe.length) { okno.hidden = true; return; }
    Z.omembe.forEach(function (p, i) {
      var b = el("button", i === Z.izbranaOmemba ? "izbran" : ""); b.type = "button";
      b.appendChild(document.createTextNode(p.ime));
      b.appendChild(el("small", "", ubezi(p.vrsta)));
      b.addEventListener("mousedown", function (e) { e.preventDefault(); vstaviOmembo(p); });
      okno.appendChild(b);
    });
    okno.hidden = false;
  }
  function vstaviOmembo(p) {
    var q = iskanjeOmembe(), ta = $("zapisekBesedilo");
    if (!q) return;
    var ime = String(p.ime || "").replace(/[\[\]]/g, "").slice(0, 120);
    var vstavek = "[@" + ime + "](" + p.cilj.replace(/\s/g, "%20").replace(/\)/g, "%29") + ") ";
    ta.value = ta.value.slice(0, q.zacetek) + vstavek + ta.value.slice(ta.selectionStart);
    var poz = q.zacetek + vstavek.length;
    ta.setSelectionRange(poz, poz); ta.focus();
    zapriOmembe();
    shraniZapisekKmalu();
  }
  (function pripraviZapiske() {
    on("zapisekNov", "click", function () {
      Z.iskano = ""; $("zapiskiIskanje").value = "";
      klic("zapisekShrani", ["", "Nov zapisek", "", null]).then(function (z) {
        odpriZapisek(z.id);
        setTimeout(function () { var n = $("zapisekNaslov"); n.focus(); n.select(); }, 150);
      });
    });
    on("zapiskiIskanje", "input", function () { Z.iskano = this.value; naloziZapiske(); });
    on("zapisekNaslov", "input", shraniZapisekKmalu);
    on("zapisekNaslov", "keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); $("zapisekBesedilo").focus(); } });
    on("zapisekBesedilo", "input", function () { shraniZapisekKmalu(); ponudiOmembe(); });
    on("zapisekBesedilo", "blur", function () { setTimeout(zapriOmembe, 150); });
    on("zapisekBesedilo", "keydown", function (e) {
      if ($("zapisekOmembeOkno").hidden || !Z.omembe.length) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        Z.izbranaOmemba = (Z.izbranaOmemba + (e.key === "ArrowDown" ? 1 : Z.omembe.length - 1)) % Z.omembe.length;
        narisiOmembe();
      } else if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault(); vstaviOmembo(Z.omembe[Z.izbranaOmemba]);
      } else if (e.key === "Escape") { e.preventDefault(); zapriOmembe(); }
    });
    on("zapisekPogled", "click", preklopiPogledZapiska);
    on("zapisekPripni", "click", function () {
      if (!Z.aktivni) return;
      var novo = !Z.aktivni.pripet;
      klic("zapisekShrani", [Z.aktivni.id, $("zapisekNaslov").value, $("zapisekBesedilo").value, novo]).then(function () {
        Z.aktivni.pripet = novo; $("zapisekPripni").textContent = novo ? "Odpni" : "Pripni"; naloziZapiske();
      });
    });
    on("zapisekIzbrisi", "click", function () {
      if (!Z.aktivni) return;
      // Dvoklik varnost: prvi klik vpraša, drugi v 4 s izbriše (brez sistemskega okna).
      if (Date.now() - Z.izbrisPotrdi > 4000) {
        Z.izbrisPotrdi = Date.now(); $("zapisekIzbrisi").textContent = "Res izbrišem?";
        setTimeout(function () { $("zapisekIzbrisi").textContent = "Izbriši"; }, 4000);
        return;
      }
      klic("zapisekIzbrisi", [Z.aktivni.id]).then(function () {
        Z.aktivni = null; Z.izbrisPotrdi = 0; $("zapisekIzbrisi").textContent = "Izbriši";
        $("zapisekUrejevalnik").hidden = true; naloziZapiske();
      });
    });
  })();

  // ------------------------------------------------------------------ dogodki iz safeer_os.py
  window.safeerOsDogodek = function (vrsta, podatki) {
    if (vrsta === "stanje") narisiStanje(podatki);
    if (vrsta === "okna") narisiOkna(podatki);
    if (vrsta === "pojdi") window.safeerOsPojdi(podatki);
    if (vrsta === "posodobitev") pokaziPosodobitevDoma(podatki);
    if (vrsta === "mediaFallback" && podatki) predvajajHtml(podatki, 0);
    if (vrsta === "magnet") {
      // Vzamemo tudi čakajočo povezavo, da je stran ob naslednjem nalaganju ne odpre znova.
      var samo = !!(podatki && podatki.samodejno === true);
      klic("cakajociMagnet").then(function (c) {
        if (c && c.uri) odpriMagnet(c.uri, c.samodejno === true); else odpriMagnet((podatki && podatki.uri) || "", samo);
      }).catch(function () { odpriMagnet((podatki && podatki.uri) || "", samo); });
    }
    // Film iz torrenta (dodatek): med branjem torrenta in prenosom zacetka uporabnik vidi, da se nekaj dogaja.
    if (vrsta === "mediaTorrent") obvesti(t("mediaTorrentPripravljam", { ime: (podatki && podatki.naslov) || "" }));
    if (vrsta === "magnetProgram" && S.magnet.gumbPrograma && podatki)
      S.magnet.gumbPrograma.textContent = t("magnetProgramPrenasam", { odstotek: Math.floor(100 * podatki.n / (podatki.vse || 1)) });
    if (vrsta === "magnetDeljen") magnetDeljen(podatki);
    // "mediaViriUsklajeni": Moji viri so se uskladili z drugo napravo v Linku (dodan ali izbrisan dodatek, podkast ...).
    if ((vrsta === "mediaOsvezen" || vrsta === "mediaViriUsklajeni") && S.razdelek === "media") naloziMedia();
    // Seznami predvajanja so se uskladili z drugo napravo v Linku: seznam seznamov (in odprt seznam) tiho osvezimo.
    if (vrsta === "mediaSeznamiUsklajeni") {
      naloziSeznamePredvajanja();
      if (media.seznam && media.seznam.ime) {
        klic("mediaSeznam", [media.seznam.ime]).then(function (sz) {
          if (sz && sz.vnosi && sz.vnosi.length && media.seznam && media.seznam.ime === sz.ime) { media.seznam = sz; narisiMedia(); }
        }, function () {});
      }
      return;
    }
    if (vrsta === "mediaSeznamOsvezen" && podatki && podatki.ime) {
      // Uvozene skladbe so dobile posnetke (slike): odprt seznam tiho osvezimo, seznam seznamov tudi.
      naloziSeznamePredvajanja();
      if (media.seznam && media.seznam.ime === podatki.ime) {
        klic("mediaSeznam", [podatki.ime]).then(function (sz) {
          if (sz && sz.vnosi && sz.vnosi.length && media.seznam && media.seznam.ime === sz.ime) { media.seznam = sz; narisiMedia(); }
        }, function () {});
      }
      return;
    }
    if (vrsta === "mediaKatalogOsvezen" && podatki && S.razdelek === "media" && podatki.kljuc && podatki.kljuc === media.kljuc) {
      prevzemiMediaKatalog(podatki, true);
    }
    // Preverjanje v ozadju: naslovi, ki jih noben dodatek ne predvaja, izginejo iz mreze (brez obvestila).
    if (vrsta === "mediaNiNaVoljo" && podatki && podatki.idji && media.katalog) {
      var prejKartic = media.katalog.length;
      media.katalog = media.katalog.filter(function (x) { return podatki.idji.indexOf(x.id) < 0; });
      if (media.katalog.length !== prejKartic) {
        if (typeof media.skupaj === "number") media.skupaj = Math.max(media.katalog.length, media.skupaj - (prejKartic - media.katalog.length));
        if (S.razdelek === "media") narisiMedia();
      }
    }
    if (vrsta === "kodaPrijave" && podatki) pokaziKodoPrijave(podatki);
    if (vrsta === "sporocilaNova") {
      if (S.razdelek === "sporocila") naloziSporocila();
      else if (podatki && podatki.ime) obvesti(t("sporocila") + ": " + podatki.ime);
    }
    if (vrsta === "zapiskiSpremenjeni" && S.razdelek === "zapiski") {
      naloziZapiske(); if (Z.aktivni) odpriZapisek(Z.aktivni.id);
    }
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
      osveziIskalneNaprave();
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

  // ------------------------------------------------------------------ zdruzeni nabiralnik
  function naloziSporocila() {
    if (!imaMost()) { narisiSporocila(); return; }
    klic("sporocilaSeznam").then(function (p) {
      S.sporocilaSkupine = p.skupine || []; S.sporocilaKanali = p.kanali || []; S.sporocilaOznakeVse = p.oznake || [];
      narisiSporocila(); uskladiOdprtPogovor();
    }).catch(function () { narisiSporocila(); });
  }
  function kanalIkona(vrsta) { return vrsta === "email" ? "sporocila" : vrsta === "safeer" ? "povezava" : "sporocila"; }
  function kratekCas(cas) {
    if (!cas) return "";
    var d = new Date(cas); if (isNaN(d.getTime())) return "";
    var lok = LOKALE[jezik] || jezik, danes = new Date();
    if (d.toDateString() === danes.toDateString()) return d.toLocaleTimeString(lok, { hour: "2-digit", minute: "2-digit" });
    return d.toLocaleDateString(lok, d.getFullYear() === danes.getFullYear() ? { day: "numeric", month: "short" }
      : { day: "numeric", month: "short", year: "numeric" });
  }
  function stanjeKanala(k) {
    var st = String(k.stanje || "");
    if (st === "napaka:geslo") return t("kanalVnesiGeslo");
    if (st === "napaka:prijava") return t("kanalPrijavaNi");
    if (st === "napaka:omrezje") return t("kanalNiDosegljiv");
    if (st.indexOf("napaka") === 0) return t("niUspelo");
    return "";
  }
  function narisiKanale() {
    var cilj = $("sporocilaKanali"); if (!cilj) return; cilj.innerHTML = "";
    S.sporocilaKanali.forEach(function (k) {
      var opis = stanjeKanala(k);
      var b = el("button", "kanal-cip" + (opis ? " napaka" : ""));
      b.type = "button";
      b.innerHTML = "<i></i><span>" + ubezi(k.ime) + "</span>" + (opis ? "<small>" + ubezi(opis) + "</small>" : "");
      b.addEventListener("click", function () { if (k.vrsta === "safeer") odpriPisiNapravi(); else odpriUrejanjeKanala(k); });
      cilj.appendChild(b);
    });
  }
  /* Safeer Chat: napisi napravi v Linku (telefon, tablica, TV, drug racunalnik). */
  function odpriPisiNapravi() {
    zapriSloje();
    var cilj = $("pisiNaprave"); cilj.innerHTML = "";
    cilj.appendChild(el("p", "drobno", ubezi(t("povezujem"))));
    $("slojPisi").classList.add("viden");
    klic("sporocilaNaprave").then(function (naprave) {
      cilj.innerHTML = "";
      if (!(naprave || []).length) { cilj.appendChild(el("p", "drobno", ubezi(t("niNapravKlepet")))); $("pisiPreklici").focus(); return; }
      naprave.forEach(function (n, i) {
        var b = el("button", "pogovor-vrstica");
        b.type = "button";
        b.innerHTML = '<span class="kanal-ikona">' + svg("povezava") + '</span><span><b>' + ubezi(n.ime || n.id) + '</b></span>';
        b.addEventListener("click", function () {
          klic("sporocilaZacni", [n.id, n.ime || ""]).then(function (p) {
            zapriSloje();
            S.sporocilaSkupine = p.skupine || []; S.sporocilaKanali = p.kanali || [];
            var najden = null, oseba = null;
            S.sporocilaSkupine.forEach(function (sk) { (sk.pogovori || []).forEach(function (x) {
              if (x.kanal_id === "safeer-link" && x.id === n.id) { najden = x; oseba = sk.oseba; } }); });
            narisiSporocila();
            if (najden) { odpriPogovor(oseba, najden); setTimeout(function () { $("sporocilaBesedilo").focus(); }, 30); }
          }).catch(function (e) { obvesti(typeof e === "string" ? e : t("niUspelo")); });
        });
        cilj.appendChild(b);
        if (i === 0) setTimeout(function () { b.focus(); }, 30);
      });
    }).catch(function () { cilj.innerHTML = ""; cilj.appendChild(el("p", "drobno", ubezi(t("niNapravKlepet")))); });
  }
  function odpriUrejanjeKanala(k) {
    zapriSloje(); S.urejaniKanal = k;
    $("kanalUrediNaslov").textContent = k.ime;
    $("kanalUrediOpis").textContent = stanjeKanala(k) || t("kanalPovezan");
    $("kanalUrediGeslo").value = ""; $("kanalUrediGeslo").hidden = k.vrsta !== "email" && k.vrsta !== "chatwoot";
    $("slojKanalUredi").classList.add("viden"); $("kanalUrediGeslo").focus();
  }
  function jeKlepet(vrsta) { return vrsta === "chatwoot" || vrsta === "safeer" || vrsta === "matrix" || vrsta === "telegram_bot"; }
  function zacetnice(ime) {
    var deli = String(ime || "").split(/\s+/).map(function (x) { return x.replace(/[^\p{L}\p{N}]/gu, ""); }).filter(Boolean);
    return deli.slice(0, 2).map(function (x) { return x.charAt(0).toUpperCase(); }).join("") || "?";
  }
  function pogovorUstreza(skupina, p) {
    var vrsta = (p.kanal || {}).vrsta || "";
    var f = S.sporocilaFilter;
    if (f === "email" && vrsta !== "email") return false;
    if (f === "klepet" && !jeKlepet(vrsta)) return false;
    var mapa = S.sporocilaMapa || "vse";
    if (mapa === "neprebrano" && !p.neprebrano) return false;
    if (mapa === "poslano" && !p.zadnji_ven) return false;
    if (mapa.indexOf("oznaka:") === 0 && (p.oznake || []).indexOf(mapa.slice(7)) < 0) return false;
    var n = (S.sporocilaNiz || "").trim().toLowerCase();
    if (n) {
      var besedilo = (skupina.oseba.ime + " " + (skupina.oseba.privzeto_ime || "") + " " + (p.zadeva || "") + " " + (p.zadnje_sporocilo || "") + " " + ((p.kanal || {}).ime || "") + " " + (p.oznake || []).join(" ")).toLowerCase();
      if (besedilo.indexOf(n) < 0) return false;
    }
    return true;
  }
  function narisiSporocila() {
    narisiKanale();
    var cilj = $("sporocilaSeznam"); if (!cilj) return; cilj.innerHTML = "";
    var neprebrano = 0, vseh = 0, vrstice = [];
    S.sporocilaSkupine.forEach(function (skupina) {
      (skupina.pogovori || []).forEach(function (p) {
        vseh++; if (p.neprebrano) neprebrano += Number(p.neprebrano);
        if (pogovorUstreza(skupina, p)) vrstice.push({ skupina: skupina, p: p });
      });
    });
    vrstice.sort(function (a, b) { return String(b.p.cas || "").localeCompare(String(a.p.cas || "")); });
    vrstice.forEach(function (v) {
      var skupina = v.skupina, p = v.p, vrsta = (p.kanal || {}).vrsta || "";
      var b = el("button", "pogovor-vrstica" + (S.sporocilaAktivni && S.sporocilaAktivni.id === p.id && S.sporocilaAktivni.kanal_id === p.kanal_id ? " izbran" : ""));
      b.innerHTML = '<span class="kanal-ikona">' + ubezi(zacetnice(skupina.oseba.ime)) + '</span><span><b>' + ubezi(skupina.oseba.ime) +
        '<span class="oznaka-kanala">' + ubezi((p.kanal || {}).ime || vrsta) + '</span>' + (p.oznake || []).map(function (o) { return '<span class="oznaka-pogovora">' + ubezi(o) + '</span>'; }).join("") + '</b><small>' + ubezi(p.zadeva && vrsta === "email" ? p.zadeva + " – " + (p.zadnje_sporocilo || "") : (p.zadnje_sporocilo || p.zadeva || "")) + '</small></span><span><time>' +
        ubezi(kratekCas(p.cas)) + '</time>' + (p.neprebrano ? '<i>' + Number(p.neprebrano) + '</i>' : '') + '</span>';
      b.addEventListener("click", function () { odpriPogovor(skupina.oseba, p); }); cilj.appendChild(b);
    });
    if (!cilj.children.length) cilj.appendChild(el("p", "prazno", ubezi(t(vseh ? "niZadetkov" : "niPogovorov"))));
    var sn = $("stNeprebrano"), sp = $("stPrejeto");
    if (sn) { sn.textContent = neprebrano; sn.hidden = !neprebrano; }
    if (sp) { sp.textContent = neprebrano; sp.hidden = !neprebrano; }
    narisiOznakeMape();
  }
  function narisiOznakeMape() {
    var cilj = $("sporocilaOznake"); if (!cilj) return; cilj.innerHTML = "";
    var oznake = S.sporocilaOznakeVse || [];
    var dl = $("seznamOznak"); if (dl) { dl.innerHTML = ""; oznake.forEach(function (o) { var op = document.createElement("option"); op.value = o; dl.appendChild(op); }); }
    cilj.parentNode.querySelector('[data-t="oznakeNaslov"]').hidden = !oznake.length;
    oznake.forEach(function (o) {
      var b = el("button", (S.sporocilaMapa === "oznaka:" + o) ? "izbran" : ""); b.type = "button";
      b.innerHTML = "<span>" + ubezi(o) + "</span>";
      b.addEventListener("click", function () {
        S.sporocilaMapa = (S.sporocilaMapa === "oznaka:" + o) ? "vse" : "oznaka:" + o;
        $("sporocilaMape").querySelectorAll("button").forEach(function (x) { x.classList.toggle("izbran", S.sporocilaMapa === "vse" && x.getAttribute("data-mapa") === "vse"); });
        narisiSporocila();
      });
      cilj.appendChild(b);
    });
  }
  function shraniOznake(pogovor, oznake) {
    klic("sporocilaOznake", [pogovor.kanal_id, pogovor.id, oznake]).then(function (p) {
      posodobiSeznamIzOdgovora(p);
    }).catch(function (e) { obvesti(typeof e === "string" && e ? e : t("niUspelo")); });
  }
  function odpriOsebaSloj(nacin) {
    var o = S.sporocilaOseba; if (!o) return;
    zapriSloje(); S.osebaNacin = nacin;
    $("osebaIme").hidden = nacin !== "preimenuj"; $("osebaIzbira").hidden = nacin !== "zdruzi";
    if (nacin === "preimenuj") {
      $("osebaNaslov").textContent = t("osebaPreimenujNaslov"); $("osebaOpis").textContent = t("osebaPreimenujOpis", { privzeto: o.privzeto_ime || o.ime });
      $("osebaIme").value = o.lastno_ime || "";
    } else {
      $("osebaNaslov").textContent = t("osebaZdruziNaslov"); $("osebaOpis").textContent = t("osebaZdruziOpis", { ime: o.ime });
      var sel = $("osebaIzbira"); sel.innerHTML = "";
      S.sporocilaSkupine.forEach(function (sk) {
        if (sk.oseba.id === o.id) return;
        var op = document.createElement("option"); op.value = sk.oseba.id;
        op.textContent = sk.oseba.ime + " (" + (sk.oseba.identitete || []).map(function (i) { return Array.isArray(i) ? i[1] : i.naslov; }).join(", ") + ")";
        sel.appendChild(op);
      });
    }
    $("slojOseba").classList.add("viden"); (nacin === "preimenuj" ? $("osebaIme") : $("osebaIzbira")).focus();
  }
  function posodobiSeznamIzOdgovora(p) {
    S.sporocilaSkupine = p.skupine || []; S.sporocilaKanali = p.kanali || []; S.sporocilaOznakeVse = p.oznake || [];
    // Oseba je lahko dobila novo ime ali se zdruzila: pano in naslov kazeta novo stanje.
    var a = S.sporocilaAktivni, nova = null, svez = null;
    S.sporocilaSkupine.forEach(function (sk) { (sk.pogovori || []).forEach(function (x) { if (a && x.id === a.id && x.kanal_id === a.kanal_id) { nova = sk.oseba; svez = x; } }); });
    if (nova) { S.sporocilaOseba = nova; S.sporocilaAktivni = svez; $("sporocilaNaslov").textContent = nova.ime; narisiPano(nova, svez, S.sporocilaZadnjaVsebina || []); }
    narisiSporocila();
  }
  function odpriPogovor(oseba, pogovor) {
    S.sporocilaAktivni = pogovor; S.sporocilaOseba = oseba; narisiSporocila();
    $("sporocilaNaslov").textContent = oseba.ime;
    $("sporocilaPodnaslov").textContent = ((pogovor.kanal || {}).ime || "") + (pogovor.zadeva ? " · " + pogovor.zadeva : "");
    var vnos = $("sporocilaBesedilo"), gumb = $("sporocilaVnos").querySelector("button");
    vnos.disabled = false; gumb.disabled = false;
    var pano = $("sporocilaPano"); pano.hidden = false; pano.title = t("pokaziPano");
    narisiPano(oseba, pogovor, []);
    naloziVsebinoPogovora(pogovor);
  }
  /* Stranski pano: oseba, njeni naslovi/racuni po kanalih in datoteke iz pogovora. */
  function narisiPano(oseba, pogovor, sporocila) {
    S.sporocilaZadnjaVsebina = sporocila || [];
    if (S.sporocilaPanoOseba !== oseba.id) { S.sporocilaPanoOseba = oseba.id; $("panoIskanjeVnos").value = ""; $("panoZadetki").innerHTML = ""; }
    $("panoAvatar").textContent = zacetnice(oseba.ime); $("panoIme").textContent = oseba.ime;
    $("panoPrivzeto").textContent = (oseba.lastno_ime && oseba.privzeto_ime && oseba.privzeto_ime !== oseba.ime) ? t("privzetoIme", { ime: oseba.privzeto_ime }) : "";
    $("panoKanal").textContent = (pogovor.kanal || {}).ime || "";
    var oz = $("panoOznake"); oz.innerHTML = "";
    (pogovor.oznake || []).forEach(function (o) {
      var c = el("span", "", ubezi(o)); var x = el("button", "", "×"); x.type = "button"; x.title = t("odstrani");
      x.addEventListener("click", function () { shraniOznake(pogovor, (pogovor.oznake || []).filter(function (y) { return y !== o; })); });
      c.appendChild(x); oz.appendChild(c);
    });
    var idn = $("panoIdentitete"); idn.innerHTML = "";
    var identitete = oseba.identitete || [];
    if (!identitete.length && pogovor.id && (pogovor.kanal || {}).vrsta === "email") identitete = [["email", pogovor.id]];
    identitete.forEach(function (i) {
      var v = Array.isArray(i) ? i : [i.vrsta, i.naslov];
      var vr = el("span", "identiteta", ubezi((v[0] ? v[0] + ": " : "") + (v[1] || "")));
      if (identitete.length > 1) {
        var r = el("button", "", ubezi(t("osebaRazdruzi"))); r.type = "button"; r.className = "gumb"; r.style.cssText = "padding:2px 8px;font-size:11px";
        r.addEventListener("click", function () { klic("sporocilaRazdruzi", [oseba.id, [v[0], v[1]]]).then(posodobiSeznamIzOdgovora).catch(function (e) { obvesti(typeof e === "string" && e ? e : t("niUspelo")); }); });
        vr.appendChild(r);
      }
      idn.appendChild(vr);
    });
    if (!idn.children.length) idn.appendChild(el("span", "identiteta", ubezi(pogovor.id || "")));
    var pr = $("panoPriponke"); pr.innerHTML = "";
    var priponke = [];
    (sporocila || []).forEach(function (s) { (s.priponke || []).forEach(function (a) { priponke.push(a); }); });
    if (!priponke.length) pr.appendChild(el("p", "drobno", ubezi(t("panoNiPriponk"))));
    priponke.slice(-12).reverse().forEach(function (a) { pr.appendChild(el("span", "identiteta", ubezi(a.ime || a.name || String(a)))); });
  }
  function naloziVsebinoPogovora(pogovor) {
    klic("sporocilaPogovor", [pogovor.kanal_id, pogovor.id]).then(function (seznam) {
      if (S.sporocilaAktivni !== pogovor) return;   // uporabnik je medtem odprl drug pogovor
      var cilj = $("sporocilaVsebina"); cilj.innerHTML = "";
      var oznacen = null;
      (seznam || []).forEach(function (s) {
        var m = el("div", "mehurcek " + (s.smer === "ven" ? "ven" : "noter"));
        m.textContent = s.besedilo || ""; m.appendChild(el("time", "", ubezi(kratekCas(s.cas)))); cilj.appendChild(m);
        if (S.sporocilaOznaciId && s.id === S.sporocilaOznaciId) { m.classList.add("zadetek"); oznacen = m; }
      }); cilj.scrollTop = cilj.scrollHeight;
      if (oznacen) { oznacen.scrollIntoView({ block: "center" }); S.sporocilaOznaciId = null; }
      if (S.sporocilaOseba) narisiPano(S.sporocilaOseba, pogovor, seznam || []);
      if (pogovor.neprebrano) { pogovor.neprebrano = 0; naloziSporocila(); }
    });
  }
  /* Po osvezitvi seznama: odprt pogovor dobi nova sporocila, izginul (odstranjen kanal) se zapre.
     Prej je desna stran ostala na starem stanju, dokler pogovora nisi znova odprl. */
  function uskladiOdprtPogovor() {
    var a = S.sporocilaAktivni; if (!a) return;
    var nov = null;
    S.sporocilaSkupine.forEach(function (s) {
      (s.pogovori || []).forEach(function (p) { if (p.id === a.id && p.kanal_id === a.kanal_id) nov = p; });
    });
    if (!nov) {
      S.sporocilaAktivni = null;
      $("sporocilaNaslov").textContent = t("izberiPogovor"); $("sporocilaPodnaslov").textContent = "";
      $("sporocilaPano").hidden = true; $("sporocilaPanoVsebina").hidden = true;
      $("sporocilaVsebina").innerHTML = "";
      $("sporocilaBesedilo").disabled = true; $("sporocilaVnos").querySelector("button").disabled = true;
      narisiSporocila();
      return;
    }
    if (nov.cas !== a.cas || nov.zadnje_sporocilo !== a.zadnje_sporocilo) {
      S.sporocilaAktivni = nov; narisiSporocila(); naloziVsebinoPogovora(nov);
    }
  }
  var sporocilaCasovnik = 0;
  function sporocilaZanka() {
    if (sporocilaCasovnik) return;
    sporocilaCasovnik = setInterval(function () {
      if (S.razdelek !== "sporocila") { clearInterval(sporocilaCasovnik); sporocilaCasovnik = 0; return; }
      naloziSporocila();
    }, 30000);
  }
  var kanalPonudnikiPodatki = null;
  function odpriCarovnikKanala() {
    zapriSloje(); $("kanalNapaka").hidden = true; $("kanalPonudnik").value = "";
    $("kanalVrsta").value = "email";
    $("kanalVrstaIzbira").querySelectorAll("button").forEach(function (x) { x.classList.toggle("izbran", x.getAttribute("data-vrsta") === "email"); });
    preklopiKanalPolja(); $("slojKanal").classList.add("viden");
    if (kanalPonudnikiPodatki) { narisiPonudnike(); return; }
    klic("sporocilaPonudniki").then(function (p) { kanalPonudnikiPodatki = p || { ponudniki: [], aplikacije: [] }; narisiPonudnike(); })
      .catch(function () { kanalPonudnikiPodatki = { ponudniki: [{ id: "drug", ime: "", domene: [], geslo: "navadno", navodila: "drug" }], aplikacije: [] }; narisiPonudnike(); });
  }
  function navodilaZa(kljuc) {
    var k = { gmail: "navGmail", yahoo: "navYahoo", icloud: "navIcloud", gmx: "navGmx", zoho: "navZoho", fastmail: "navFastmail", arnes: "navArnes", oauth: "navOauth", drug: "navDrug" }[kljuc] || "navNavadno";
    return t(k);
  }
  function narisiPonudnike() {
    var m = $("kanalPonudnikiMreza"); m.textContent = "";
    (kanalPonudnikiPodatki.ponudniki || []).forEach(function (p) {
      var b = document.createElement("button"); b.type = "button"; b.setAttribute("data-id", p.id);
      var drug = p.id === "drug", oauth = p.geslo === "oauth";
      if (oauth) b.classList.add("ni-na-voljo");
      var ime = document.createElement("b"); ime.textContent = drug ? t("kanalDrugPonudnikIme") : p.ime + (oauth ? "  · " + t("kanalNiNaVoljo") : "");
      var opis = document.createElement("small");
      opis.textContent = drug ? t("kanalDrugPonudnikOpis") : p.geslo === "aplikacije" ? t("namigGesloAplikacije") : oauth ? "" : (p.domene || []).slice(0, 2).map(function (d) { return "@" + d; }).join(", ");
      b.appendChild(ime); b.appendChild(opis);
      b.addEventListener("click", function () { izberiPonudnika(p); });
      m.appendChild(b);
    });
    var a = $("kanalAplikacijeMreza"); a.textContent = "";
    [["posta", "kanalAppPosta"], ["klepet", "kanalAppKlepet"]].forEach(function (sk) {
      var seznam = (kanalPonudnikiPodatki.aplikacije || []).filter(function (x) { return x.vrsta === sk[0]; });
      if (!seznam.length) return;
      var h = document.createElement("b"); h.className = "aplikacije-skupina"; h.textContent = t(sk[1]); a.appendChild(h);
      seznam.forEach(function (x) {
        var v = document.createElement("div"); v.className = "aplikacije-vrsta";
        var ime = document.createElement("div"); ime.className = "ime"; ime.textContent = x.ime;
        var podnaslov = document.createElement("small"); podnaslov.textContent = (x.splet || x.prenos || "").replace(/^https?:\/\//, "").split("/")[0]; ime.appendChild(podnaslov);
        v.appendChild(ime);
        if (x.splet) { var g1 = document.createElement("button"); g1.type = "button"; g1.className = "gumb glavni"; g1.textContent = t("kanalAppSplet");
          g1.addEventListener("click", function () { zapriSloje(); otvoriSpletnoStran(x.splet, x.ime, true); }); v.appendChild(g1); }
        if (x.prenos) { var g2 = document.createElement("button"); g2.type = "button"; g2.className = "gumb"; g2.textContent = t("kanalAppPrenos");
          g2.addEventListener("click", function () { zapriSloje(); otvoriSpletnoStran(x.prenos, x.ime, true); }); v.appendChild(g2); }
        a.appendChild(v);
      });
    });
  }
  function izberiPonudnika(p) {
    $("kanalPonudnik").value = p.id; $("kanalNapaka").hidden = true;
    var drug = p.id === "drug";
    $("kanalPonudniki").hidden = true; $("kanalEmail").hidden = false;
    $("kanalNaslov").placeholder = drug ? t("epostniNaslov") : t("kanalNaslovPri", { ime: p.ime });
    $("kanalGeslo").placeholder = p.geslo === "aplikacije" ? t("kanalGesloAplikacije16") : t("kanalNavadnoGeslo");
    $("kanalNavodila").textContent = navodilaZa(p.navodila);
    $("kanalStrezniki").hidden = !drug; $("kanalNapredno").hidden = drug;
    $("kanalImap").value = drug ? "" : (p.imap + (p.imap_vrata && p.imap_vrata !== 993 ? ":" + p.imap_vrata : ""));
    $("kanalSmtp").value = drug ? "" : (p.smtp + (p.smtp_vrata && p.smtp_vrata !== 465 ? ":" + p.smtp_vrata : ""));
    $("kanalImap").removeAttribute("data-rocno"); $("kanalSmtp").removeAttribute("data-rocno");
    preklopiKanalPolja();
    $("kanalPovezi").disabled = p.geslo === "oauth";
    $("kanalNaslov").focus();
  }
  function preklopiKanalPolja() {
    var v = $("kanalVrsta").value, email = v === "email", ponudnik = $("kanalPonudnik").value;
    $("kanalPonudniki").hidden = !email || !!ponudnik; $("kanalEmail").hidden = !email || !ponudnik;
    $("kanalChatwoot").hidden = v !== "chatwoot"; $("kanalAplikacijeSeznam").hidden = v !== "aplikacije";
    $("kanalApi").hidden = v !== "api"; if (v === "api") preklopiApiProtokol();
    $("kanalPovezi").hidden = v === "aplikacije" || (email && !ponudnik);
    $("kanalSkrivnostOpis").hidden = v === "aplikacije";
    if (v !== "email" || ponudnik) $("kanalPovezi").disabled = false;
  }
  /* Lastni API: Matrix potrebuje streznik + zeton, Telegram Bot samo zeton. Navodila povedo, kje ju dobis. */
  function preklopiApiProtokol() {
    var pr = $("kanalProtokol").value;
    $("kanalApiStreznik").hidden = pr !== "matrix";
    $("kanalApiZeton").placeholder = pr === "matrix" ? t("apiZeton") : "123456:ABC…";
    $("kanalApiNavodila").textContent = t(pr === "matrix" ? "navMatrix" : "navTelegramBot");
  }
  /* Iskanje po vsebini sporocil ene osebe (vsi njeni kanali); klik na zadetek odpre tisti pogovor. */
  function isciPriOsebi(niz) {
    var oseba = S.sporocilaOseba, cilj = $("panoZadetki"); if (!oseba) return;
    niz = String(niz || "").trim(); cilj.innerHTML = "";
    if (niz.length < 2) return;
    klic("sporocilaIsciPri", [oseba.id, niz]).then(function (zadetki) {
      if (!S.sporocilaOseba || S.sporocilaOseba.id !== oseba.id || $("panoIskanjeVnos").value.trim() !== niz) return;
      cilj.innerHTML = "";
      if (!zadetki || !zadetki.length) { cilj.appendChild(el("p", "drobno", ubezi(t("panoNiZadetkov")))); return; }
      zadetki.forEach(function (z) {
        var b = el("button", "pano-zadetek"); b.type = "button";
        b.appendChild(el("small", "", ubezi(((z.kanal || {}).ime || "") + " · " + kratekCas(z.cas))));
        b.appendChild(el("span", "", ubezi(z.izsek || "")));
        b.addEventListener("click", function () {
          var pog = null;
          S.sporocilaSkupine.forEach(function (s) { (s.pogovori || []).forEach(function (p) { if (p.id === z.pogovor_id && p.kanal_id === z.kanal_id) pog = p; }); });
          if (pog) { S.sporocilaOznaciId = z.id; odpriPogovor(oseba, pog); }
        });
        cilj.appendChild(b);
      });
    }).catch(function () {});
  }
  // ------------------------------------------------------------------ zacetek
  function poveziDogodke() {
    $("kanalApiProtokol").querySelectorAll("button").forEach(function (b) {
      b.addEventListener("click", function () {
        $("kanalProtokol").value = b.getAttribute("data-protokol");
        $("kanalApiProtokol").querySelectorAll("button").forEach(function (x) { x.classList.toggle("izbran", x === b); });
        preklopiApiProtokol();
      });
    });
    $("panoIskanjeVnos").addEventListener("input", function () { isciPriOsebi(this.value); });
    $("sporocilaDodaj").addEventListener("click", odpriCarovnikKanala);
    $("sporocilaPisi").addEventListener("click", odpriPisiNapravi);
    $("pisiPreklici").addEventListener("click", zapriSloje);
    $("kanalPreklici").addEventListener("click", zapriSloje);
    $("kanalVrstaIzbira").querySelectorAll("button").forEach(function (b) {
      b.addEventListener("click", function () {
        $("kanalVrsta").value = b.getAttribute("data-vrsta");
        $("kanalVrstaIzbira").querySelectorAll("button").forEach(function (x) { x.classList.toggle("izbran", x === b); });
        preklopiKanalPolja();
      });
    });
    $("kanalZamenjaj").addEventListener("click", function () { $("kanalPonudnik").value = ""; preklopiKanalPolja(); });
    $("kanalNapredno").addEventListener("click", function () { $("kanalStrezniki").hidden = false; $("kanalNapredno").hidden = true; });
    ["kanalImap", "kanalSmtp"].forEach(function (id) { $(id).addEventListener("input", function () { this.setAttribute("data-rocno", "1"); }); });
    $("kanalNaslov").addEventListener("blur", function () {
      var naslov = this.value.trim(); if (naslov.indexOf("@") < 1 || $("kanalPonudnik").value !== "drug") return;
      // Drug ponudnik: ce je domena znanega ponudnika, ga izberemo; sicer predlagamo imap./smtp.domena.
      var znani = (kanalPonudnikiPodatki && kanalPonudnikiPodatki.ponudniki || []).filter(function (p) { return (p.domene || []).indexOf(naslov.split("@")[1].toLowerCase()) >= 0; })[0];
      if (znani) { izberiPonudnika(znani); return; }
      klic("sporocilaStreznik", [naslov]).then(function (p) {
        if (!$("kanalImap").getAttribute("data-rocno")) $("kanalImap").value = p.imap || "";
        if (!$("kanalSmtp").getAttribute("data-rocno")) $("kanalSmtp").value = p.smtp || "";
      });
    });
    $("kanalUrediPreklici").addEventListener("click", zapriSloje);
    $("kanalOdstrani").addEventListener("click", function () {
      var k = S.urejaniKanal; if (!k) return;
      if ($("kanalOdstrani").getAttribute("data-potrdi") !== k.id) {
        $("kanalOdstrani").setAttribute("data-potrdi", k.id); $("kanalOdstrani").textContent = t("odstraniKanalPotrdi"); return;
      }
      $("kanalOdstrani").removeAttribute("data-potrdi"); $("kanalOdstrani").textContent = t("odstraniKanal");
      klic("sporocilaOdstrani", [k.id]).then(function () { zapriSloje(); S.sporocilaAktivni = null; naloziSporocila(); });
    });
    $("obrazecKanalUredi").addEventListener("submit", function (e) {
      e.preventDefault(); var k = S.urejaniKanal, g = $("kanalUrediGeslo").value;
      if (!k || !g) return;
      klic("sporocilaSkrivnost", [k.id, g]).then(function (p) {
        $("kanalUrediGeslo").value = ""; zapriSloje();
        S.sporocilaSkupine = p.skupine || []; S.sporocilaKanali = p.kanali || []; narisiSporocila();
      }).catch(function (napaka) { obvesti(String(napaka || t("niUspelo"))); });
    });
    $("sporocilaBesedilo").addEventListener("keydown", function (e) {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); $("sporocilaVnos").requestSubmit(); }
    });
    $("sporocilaFiltri").querySelectorAll("button").forEach(function (b) {
      b.addEventListener("click", function () {
        S.sporocilaFilter = b.getAttribute("data-kanal-vrsta") || "";
        $("sporocilaFiltri").querySelectorAll("button").forEach(function (x) { x.classList.toggle("izbran", x === b); });
        narisiSporocila();
      });
    });
    $("sporocilaMape").querySelectorAll("button").forEach(function (b) {
      b.addEventListener("click", function () {
        S.sporocilaMapa = b.getAttribute("data-mapa") || "vse";
        $("sporocilaMape").querySelectorAll("button").forEach(function (x) { x.classList.toggle("izbran", x === b); });
        narisiSporocila();
      });
    });
    $("sporocilaIskanje").addEventListener("input", function () { S.sporocilaNiz = this.value; narisiSporocila(); });
    $("sporocilaPano").addEventListener("click", function () { var p = $("sporocilaPanoVsebina"); p.hidden = !p.hidden; });
    $("panoPreimenuj").addEventListener("click", function () { odpriOsebaSloj("preimenuj"); });
    $("panoZdruzi").addEventListener("click", function () { odpriOsebaSloj("zdruzi"); });
    $("osebaPreklici").addEventListener("click", zapriSloje);
    $("obrazecOseba").addEventListener("submit", function (e) {
      e.preventDefault(); var o = S.sporocilaOseba; if (!o) return;
      var klicMet = S.osebaNacin === "preimenuj" ? klic("sporocilaPreimenuj", [o.id, $("osebaIme").value.trim()]) : klic("sporocilaZdruzi", [o.id, $("osebaIzbira").value]);
      klicMet.then(function (p) { zapriSloje(); posodobiSeznamIzOdgovora(p); }).catch(function (err) { obvesti(typeof err === "string" && err ? err : t("niUspelo")); });
    });
    $("panoOznakaObrazec").addEventListener("submit", function (e) {
      e.preventDefault(); var a = S.sporocilaAktivni, v = $("panoOznakaVnos").value.trim(); if (!a || !v) return;
      $("panoOznakaVnos").value = ""; shraniOznake(a, (a.oznake || []).concat([v]));
    });
    $("obrazecKanal").addEventListener("submit", function (e) {
      e.preventDefault(); var email = $("kanalVrsta").value === "email";
      if ($("kanalVrsta").value === "aplikacije") return;
      if (email && $("kanalPonudnik").value === "outlook") { $("kanalNapaka").textContent = t("navOauth"); $("kanalNapaka").hidden = false; return; }
      function gostitelj(v, privzeto) { var t2 = String(v || "").trim(), i = t2.lastIndexOf(":"); var vr = i > 0 ? parseInt(t2.slice(i + 1), 10) : NaN; return isNaN(vr) ? [t2, privzeto] : [t2.slice(0, i), vr]; }
      var gi = gostitelj($("kanalImap").value, 993), gs = gostitelj($("kanalSmtp").value, 465);
      var p = email ? { vrsta:"email", naslov:$("kanalNaslov").value, imap:gi[0], imap_vrata:gi[1],
        smtp:gs[0], smtp_vrata:gs[1], geslo:$("kanalGeslo").value, ponudnik:$("kanalPonudnik").value } :
        $("kanalVrsta").value === "api" ? { vrsta:$("kanalProtokol").value, streznik:$("kanalApiStreznik").value, zeton:$("kanalApiZeton").value, ime:$("kanalApiIme").value } :
        { vrsta:"chatwoot", url:$("kanalUrl").value, account_id:Number($("kanalRacun").value), zeton:$("kanalZeton").value };
      var gumb = $("kanalPovezi"); gumb.disabled = true; gumb.textContent = t("povezujem");
      $("kanalNapaka").hidden = true;
      klic("sporocilaDodaj", [p]).then(function () {
        gumb.disabled = false; gumb.textContent = t("povezi");
        $("kanalGeslo").value = ""; $("kanalZeton").value = ""; $("kanalApiZeton").value = ""; zapriSloje(); naloziSporocila();
        setTimeout(naloziSporocila, 4000);
      }).catch(function (napaka) {
        gumb.disabled = false; gumb.textContent = t("povezi");
        $("kanalNapaka").textContent = String(napaka || t("niUspelo")); $("kanalNapaka").hidden = false;
      });
    });
    $("sporocilaVnos").addEventListener("submit", function (e) {
      e.preventDefault(); var p = S.sporocilaAktivni, besedilo = $("sporocilaBesedilo").value.trim();
      if (!p || !besedilo) return;
      klic("sporocilaPoslji", [p.kanal_id, p.id, besedilo]).then(function (r) {
        $("sporocilaBesedilo").value = ""; odpriPogovor({ ime: $("sporocilaNaslov").textContent.split(" · ")[0] }, p);
        naloziSporocila();          // seznam pokaze zadnje sporocilo takoj, ne sele ob naslednji osvezitvi
        if (r && r.caka) obvesti(t("klepetCaka"));
      }).catch(function (e) { obvesti(typeof e === "string" && e ? e : t("niUspelo")); });
    });
    document.querySelectorAll("#meni button").forEach(function (b) {
      b.addEventListener("click", function () {
        var razdelek = b.getAttribute("data-razdelek");
        if (razdelek === "splet" && !document.body.classList.contains("nacin-splet")) klic("vrniSplet");
        pojdi(razdelek);
      });
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
    on("gumbPosodobi", "click", posodobi);
    on("domPosodobitevGumb", "click", naPosodobitve);
    on("stikaloPredaja", "click", function () {
      // "Predvajanje za druge naprave": Nadaljuj z druge naprave / Pošlji na napravo proti temu računalniku.
      var b = $("stikaloPredaja");
      if (!b) return;
      var nov = b.getAttribute("aria-checked") !== "true";
      b.setAttribute("aria-checked", nov ? "true" : "false");
      if (S.povezava) S.povezava.predajanje = nov;
      klic("predajanje", [nov]).then(function (zdaj) { b.setAttribute("aria-checked", zdaj ? "true" : "false"); }).catch(function () {});
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
          e.preventDefault();
          if (a) a.click(); else izvediNamero(iskanje.value);
          iskanje.value = ""; iskanje.blur();
        }
      });
      iskanje.addEventListener("focus", function () { if (iskanje.value) isci(); });
    }
    on("programiIskanje", "input", function () { S.programIskanje = this.value; S.skupina = "vse"; narisiPrograme(); });
    on("programiIskanje", "keydown", function (e) {
      if (e.key !== "Enter") return;
      var prvi = $("vsiProgrami").querySelector(".ploscica");
      if (prvi) { e.preventDefault(); prvi.click(); }
    });
    on("datotekeIskanje", "input", function () {
      var niz = this.value.trim(); clearTimeout(iskanjeZamik);
      if (niz.length < 2) return;
      iskanjeZamik = setTimeout(function () { klic("isciDatoteke", [niz]).then(function (r) { prikaziIskanjeDatotek(niz, r || []); }); }, 250);
    });
    on("napraveIskanje", "input", function () { narisiSeznamNaprav(S.povezava.stanje === "povezan" && !!S.povezava.control); });
    // Kot meni Start: kar zacnes tipkati, gre v iskanje.
    document.addEventListener("keydown", function (e) {
      var predvajalnik = $("mediaPredvajalnik");
      var predvajalnikOdprt = !!(predvajalnik && !predvajalnik.hidden);
      var pogovor = document.querySelector(".sloj-koda-prijave");
      if (e.key === "Escape") {
        // Esc v vprašanju = »Ne zdaj« / »V redu«; predvajalnik zapre poslušalec na oknu. Ne skoči na Domov.
        if (pogovor) { var zapri = pogovor.querySelector(".koda-prijave-gumb"); if (zapri) zapri.click(); return; }
        if (predvajalnikOdprt) return;
        var odprt = document.querySelector(".sloj.viden");
        if (odprt || iskanje.value) { iskanje.value = ""; zapriSloje(); iskanje.blur(); }
        else pojdi("domov");
        return;
      }
      var v = document.activeElement;
      if (v && (v.tagName === "INPUT" || v.tagName === "TEXTAREA" || v.tagName === "SELECT" || v.isContentEditable)) return;
      // Odprt obrazec, vprašanje ali predvajalnik: tipke ne smejo teči v iskanje za njimi.
      var sloj = document.querySelector(".sloj.viden");
      if ((sloj && sloj.id !== "slojIskanje") || pogovor || predvajalnikOdprt) return;
      if (e.ctrlKey || e.altKey || e.metaKey) return;
      if (e.key && e.key.length === 1 && e.key !== " ") {
        e.preventDefault();
        iskanje.focus();
        iskanje.value += e.key;
        isci();
      }
    });
  }

  // ------------------------------------------------------------------ meni polja (desni klik)
  // Privzeti meni QtWebEngine je v lupini izklopljen (anglesko »Back / Reload / View page source« sem ne sodi).
  // Polja za vnos in izbrano besedilo dobijo svoj kratek meni v jeziku vmesnika. Odlozisce gre skozi most:
  // Safeer OS preveri, da je besedilo res zapisano, in o neuspehu pove, namesto da se ne zgodi nic.
  var meniPolja = null;
  function zapriMeniPolja() {
    if (!meniPolja) return;
    meniPolja.remove();
    meniPolja = null;
  }
  function poljeZaMeni(cilj) {
    var e = cilj && cilj.closest ? cilj.closest("input, textarea, [contenteditable=''], [contenteditable='true'], [contenteditable='plaintext-only']") : null;
    if (!e || e.disabled) return null;
    if (e.tagName === "INPUT" && !/^(text|search|url|email|tel|password|number)$/i.test(e.type || "text")) return null;
    return e;
  }
  function izborPolja(p) {
    // {od, konec, besedilo}; polja brez izbire po mestih (number, email) in urejevalno besedilo nimajo od/konec.
    var od = null, konec = null, besedilo = "";
    if (p && (p.tagName === "INPUT" || p.tagName === "TEXTAREA")) {
      try { od = p.selectionStart; konec = p.selectionEnd; } catch (e) { od = konec = null; }
    }
    if (od != null && konec != null) besedilo = p.value.substring(od, konec);
    else besedilo = String(window.getSelection ? window.getSelection() : "");
    return { od: od, konec: konec, besedilo: besedilo };
  }
  function vrniIzborPolja(p, izbor) {
    if (!p) return;
    p.focus();
    if (izbor.od != null && izbor.konec != null) { try { p.setSelectionRange(izbor.od, izbor.konec); } catch (e) {} }
  }
  function odpriMeniPolja(p, x, y) {
    zapriMeniPolja();
    var izbor = izborPolja(p);
    var geslo = !!p && p.tagName === "INPUT" && p.type === "password";
    var samoBranje = !p || !!p.readOnly;
    var imaVsebino = !!p && ((p.tagName === "INPUT" || p.tagName === "TEXTAREA") ? p.value.length > 0 : (p.textContent || "").length > 0);
    var m = el("div", "meni-polja");
    m.setAttribute("role", "menu");
    function vrstica(kljuc, omogoceno, dejanje) {
      var g = el("button");
      g.type = "button"; g.textContent = t(kljuc); g.disabled = !omogoceno;
      g.setAttribute("role", "menuitem");
      // Pritisk ne sme vzeti fokusa polju: izbira in kazalec ostaneta, kjer sta.
      g.addEventListener("mousedown", function (e) { e.preventDefault(); });
      g.addEventListener("click", function () { zapriMeniPolja(); dejanje(); });
      m.appendChild(g);
    }
    function niUspelo() { obvesti(t("meniOdlozisceNapaka")); }
    if (p) vrstica("meniIzrezi", !!izbor.besedilo && !geslo && !samoBranje, function () {
      klic("kopiraj", [izbor.besedilo]).then(function (ok) {
        if (!ok) { niUspelo(); return; }
        vrniIzborPolja(p, izbor);
        document.execCommand("delete");
      }, niUspelo);
    });
    vrstica("meniKopiraj", !!izbor.besedilo && !geslo, function () {
      klic("kopiraj", [izbor.besedilo]).then(function (ok) {
        vrniIzborPolja(p, izbor);
        if (!ok) niUspelo();
      }, niUspelo);
    });
    if (p) vrstica("meniPrilepi", !samoBranje, function () {
      klic("odlozisceBeri").then(function (r) {
        var besedilo = (r && r.besedilo) || "";
        vrniIzborPolja(p, izbor);
        if (!besedilo) { obvesti(t("meniOdloziscePrazno")); return; }
        // Enovrsticno polje: prelomi vrstic postanejo presledki (kot pri lepljenju s tipkovnico).
        if (p.tagName === "INPUT") besedilo = besedilo.replace(/\r\n|\r|\n/g, " ");
        document.execCommand("insertText", false, besedilo);
      }, niUspelo);
    });
    if (p) vrstica("meniIzberiVse", imaVsebino, function () {
      p.focus();
      if (p.select) p.select(); else document.execCommand("selectAll");
    });
    document.body.appendChild(m);
    var r = m.getBoundingClientRect();
    m.style.left = Math.max(4, Math.min(x, window.innerWidth - r.width - 4)) + "px";
    m.style.top = Math.max(4, Math.min(y, window.innerHeight - r.height - 4)) + "px";
    meniPolja = m;
  }
  function poveziMeniPolja() {
    document.addEventListener("contextmenu", function (e) {
      var p = poljeZaMeni(e.target);
      if (!p && e.target.closest && e.target.closest("#slojIskanje")) {
        // Odprti zadetki iskanja: polje je pod tancico sloja, klik vanj zato zadene tancico.
        var polje = $("iskanje"), okvir = polje ? polje.getBoundingClientRect() : null;
        if (okvir && e.clientX >= okvir.left && e.clientX <= okvir.right && e.clientY >= okvir.top && e.clientY <= okvir.bottom) p = polje;
      }
      var izbrano = p ? "" : String(window.getSelection ? window.getSelection() : "").trim();
      if (!p && !izbrano) { zapriMeniPolja(); return; }
      e.preventDefault();
      if (p && document.activeElement !== p) p.focus();
      odpriMeniPolja(p, e.clientX, e.clientY);
    });
    document.addEventListener("mousedown", function (e) { if (meniPolja && !meniPolja.contains(e.target)) zapriMeniPolja(); }, true);
    document.addEventListener("keydown", function (e) {
      if (meniPolja && e.key === "Escape") { e.preventDefault(); e.stopPropagation(); zapriMeniPolja(); }
    }, true);
    window.addEventListener("blur", zapriMeniPolja);
    window.addEventListener("resize", zapriMeniPolja);
    document.addEventListener("scroll", zapriMeniPolja, true);
  }

  function zacni() {
    if (/[?&]namizje=1/.test(location.search)) document.body.classList.add("namizje");
    prevedi();
    poveziDogodke();
    poveziMeniPolja();
    osveziUro();
    setInterval(osveziUro, 1000);
    narisiDomov();
    narisiPovezavo();
    // Podatke nalozimo, ko je most na voljo (obicajno takoj; glej koMost).
    koMost(function () {
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
      osveziIskalneNaprave();
      nalozPrograme();
      osveziStanje();
      osveziOkna();
      narisiNedavneDomov();
    }, function () {});
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", zacni); else zacni();
  // ------------------------------------------------------------------ Safeer Media
  // En katalog ne glede na vir. Zaledje zdruzi dvojnike in izbere najboljsi tok;
  var media = { katalog: [], viri: [], filter: "film", genre: "", query: "", page: 1, skupaj_strani: 1, aktivni: null, zahteva: 0, timer: 0,
                // Razvrstitev in zacasno izklopljeni viri veljajo do ponovnega zagona (namenoma ne shranjujemo).
                razvrsti: "", izklopljeni: {}, samoLokalno: false, znaniViri: {},
                izklopljeniJeziki: {}, znaniJeziki: {},
                // Seznami predvajanja (uvozeni z YouTuba ali Spotifyja): vsi seznami in trenutno odprt seznam.
                seznami: [], seznam: null,
                // Polica »Na tvojih napravah« (knjižnica kroga).
                knjiznica: [], zahtevaKnjiznice: 0 };
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
      var prikaziZanre = !!skupinaZanrov(media.filter);
      zanriEl.style.display = prikaziZanre ? "flex" : "none";
    }
    var iskano = media.query.trim().toLocaleLowerCase();
    // Odprt seznam predvajanja: mreza kaze njegove skladbe v vrstnem redu seznama (brez zdruzevanja po izvajalcu).
    var izSeznama = !!media.seznam;
    narisiSeznamePredvajanja();
    narisiKnjiznico();
    if (izSeznama && zanriEl) zanriEl.style.display = "none";
    var list = izSeznama ? media.seznam.vnosi.slice() : media.katalog.filter(function (x) {
      if (media.filter !== "vse" && x.vrsta !== media.filter) return false;
      if (!iskano) return true;
      return [x.naslov, x.izvajalec, x.opis].join(" ").toLocaleLowerCase().indexOf(iskano) >= 0;
    });
    $("mediaPrazno").hidden = !!list.length;
    $("mediaPovzetek").textContent = izSeznama ? "" : t("mediaZadetkov", { n: media.skupaj != null ? media.skupaj : list.length }) + (media.skupaj_strani > 1 ? " · Stran " + media.page + " od " + media.skupaj_strani : "");
    var zdruzi = !izSeznama && !media.razvrsti && (media.filter === "radio" || media.filter === "video" || media.filter === "glasba");
    if (zdruzi) {
      // Naslov skupine ima smisel, ko skupine res združujejo. Kjer ima skoraj vsak izvajalec eno samo skladbo, bi
      // bila v vsaki vrstici ena kartica in ob njej prazen prostor – takrat ostane navadna mreža.
      var skupine = {};
      list.forEach(function (x) { var s = x.skupina || (media.filter === "glasba" ? x.izvajalec : ""); if (s) skupine[s] = 1; });
      var stSkupin = Object.keys(skupine).length;
      if (!stSkupin || list.length / stSkupin < 2) zdruzi = false;
    }
    if (zdruzi) list.sort(function (a, b) {
      return (a.skupina || a.izvajalec || "").localeCompare(b.skupina || b.izvajalec || "");
    });
    var mediaZadnjaSkupina = "";
    list.forEach(function (x) {
      var skupina = izSeznama ? "" : (x.skupina || (media.filter === "glasba" ? x.izvajalec : ""));
      if (zdruzi && skupina && skupina !== mediaZadnjaSkupina) {
        mediaZadnjaSkupina = skupina;
        mreza.appendChild(el("h3", "media-skupina", ubezi(mediaZadnjaSkupina)));
      }
      var card = el("button", "media-kartica");
      if (iskano && mreza.querySelectorAll(".media-kartica").length === 0) card.classList.add("iskalni-zadetek");
      card.setAttribute("aria-label", (x.naslov || "Medijski center") + " — " + mediaOznaka(x.vrsta));
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
      // Skladba s seznama predvajanja: pod naslovom izvajalec (koga pricakovati), ne splosna oznaka "Glasba".
      if (izSeznama && x.izvajalec) metaOznaka = x.izvajalec;
      meta.appendChild(el("span", "", ubezi(metaOznaka)));
      if (x.stevilo_razlicic > 1) meta.appendChild(el("span", "", ubezi(t("mediaRazlicic", { n: x.stevilo_razlicic }))));
      data.appendChild(meta); card.appendChild(data);
      // Kakovost pokazemo le, ce jo poznamo - "HD" na filmu iz leta 1938 bi bil zavajajoc.
      var znacka = x.kakovost || (x.vrsta === "tv-v-zivo" ? "V živo" : x.vrsta === "radio" ? "Radio" : x.vrsta === "glasba" ? "Glasba" : "");
      if (znacka) card.appendChild(el("span", "media-kakovost", ubezi(znacka)));
      if (Number(x.ocena || 0) > 0) card.appendChild(el("span", "media-ocena", "★ " + Number(x.ocena).toFixed(1)));
      if (izSeznama) {
        var odstraniSkladbo = el("span", "media-odstrani", "✕"); odstraniSkladbo.title = t("seznamOdstraniSkladbo");
        odstraniSkladbo.onclick = function (e) {
          e.stopPropagation();
          var ime = media.seznam.ime;
          klic("mediaOdstraniSSeznama", [ime, x.id]).then(function () {
            naloziSeznamePredvajanja();
            klic("mediaSeznam", [ime]).then(function (sz) { media.seznam = sz && sz.vnosi && sz.vnosi.length ? sz : null; narisiMedia(); });
          });
        };
        card.appendChild(odstraniSkladbo);
      }
      card.onclick = function () {
        if (x.tmdb_id || x.vrsta === "serija" || (x.vrsta === "film" && !x.peertube_uuid)) {
          odpriMediaPodrobnosti(x.id);
        } else if (x.vrsta === "glasba" || x.vrsta === "podcast") {
          nastaviVrsto(x);
          odpriMedia(x.id);
        } else {
          media.vrsta = []; narisiVrsto();
          odpriMedia(x.id);
        }
      };
      mreza.appendChild(card);
    });
    if (izSeznama) { var str = $("mediaStranjevanje"); if (str) str.innerHTML = ""; } else narisiStranjevanje();
    narisiMediaVire();
  }
  // ------------------------------------------------------------------ seznami predvajanja
  // "1 skladba, 2 skladbi, 3 skladbe, 5 skladb" (slovenska dvojina in mnozina); drugi jeziki ednina in mnozina.
  function stSkladb(n) {
    n = Number(n) || 0;
    if (n === 1) return t("seznamSkladba");
    if (jezik === "sl") {
      var o = n % 100;
      if (o === 2) return t("seznamSkladbi").replace("2", String(n));
      if (o === 3 || o === 4) return t("seznamSkladbe", { n: n });
      if (o === 1) return t("seznamSkladba").replace("1", String(n));
    }
    return t("seznamSkladb", { n: n });
  }
  // ---- polica »Na tvojih napravah«: kar je prenesla katera koli naprava v Safeer Linku (knjižnica kroga)
  // Film predvaja naprava, ki ga hrani; zasebnih naslovov in prenosov brez naslova na polici ni (odloči jedro).
  function knjiznicaVidna() {
    return (media.filter === "vse" || media.filter === "video" || media.filter === "film" || media.filter === "serija") &&
      !media.query.trim() && !media.seznam;
  }
  function naloziKnjiznico() {
    if (!knjiznicaVidna()) { narisiKnjiznico(); return; }
    var zahteva = ++media.zahtevaKnjiznice;
    klic("mediaKnjiznica").then(function (s) {
      if (zahteva !== media.zahtevaKnjiznice) return;
      media.knjiznica = s || []; narisiKnjiznico();
    }, function () {});
  }
  function knjiznicaKje(x) { return x.naprava && x.naprava.tukaj ? t("knjiznicaTukaj") : ((x.naprava && x.naprava.ime) || ""); }
  function narisiKnjiznico() {
    var c = $("mediaKnjiznica"); if (!c) return; c.innerHTML = "";
    var vnosi = knjiznicaVidna() ? (media.knjiznica || []) : [];
    c.hidden = !vnosi.length;
    if (!vnosi.length) return;
    c.appendChild(el("h3", "", ubezi(t("knjiznicaNaslov"))));
    var vrsta = el("div", "media-knjiznica-vrsta");
    vnosi.forEach(function (x) {
      var card = el("button", "media-kartica"); card.type = "button";
      var kje = knjiznicaKje(x);
      card.setAttribute("aria-label", (x.naslov || "") + " — " + kje);
      card.title = (x.naslov || "") + " · " + kje;
      if (x.slika) {
        var image = document.createElement("img"); image.alt = ""; image.loading = "lazy"; image.src = x.slika;
        image.onerror = function () { image.replaceWith(el("span", "media-brez-slike", svg("video"))); };
        card.appendChild(image);
      } else card.appendChild(el("span", "media-brez-slike", svg("video")));
      var data = el("span", "media-podatki");
      data.appendChild(el("b", "", ubezi(x.naslov || "")));
      var meta = el("span", "media-meta");
      meta.appendChild(el("span", "", ubezi(kje)));
      var stanje = x.koncano ? (x.velikost ? velikost(x.velikost) : "") : t("knjiznicaSePrenasa");
      if (stanje) meta.appendChild(el("span", "", ubezi(stanje)));
      data.appendChild(meta); card.appendChild(data);
      // Odstranitev v dveh korakih (prvi klik vpraša), brez sistemskega okna – kot pri seznamih predvajanja.
      var odstrani = el("span", "media-odstrani", "✕"), potrjeno = false; odstrani.title = t("knjiznicaOdstrani");
      odstrani.onclick = function (e) {
        e.stopPropagation();
        if (!potrjeno) { potrjeno = true; odstrani.classList.add("potrdi"); odstrani.textContent = t("knjiznicaOdstraniRes"); return; }
        card.classList.add("media-caka");
        klic("mediaKnjiznicaOdstrani", [x.kljuc]).then(function (ok) {
          if (!ok) { card.classList.remove("media-caka"); obvesti(t("knjiznicaOdstraniNiUspelo")); return; }
          media.knjiznica = (media.knjiznica || []).filter(function (y) { return y.kljuc !== x.kljuc; });
          narisiKnjiznico(); obvesti(t("knjiznicaOdstranjeno"));
        }, function () { card.classList.remove("media-caka"); obvesti(t("knjiznicaOdstraniNiUspelo")); });
      };
      card.onmouseleave = function () { if (potrjeno) { potrjeno = false; odstrani.classList.remove("potrdi"); odstrani.textContent = "✕"; } };
      card.appendChild(odstrani);
      // »Obdrži«: prenos ne poteče po 48 urah. Samo pri napravi, ki to zna (jedro pove true/false; sicer null).
      if (x.obdrzi === true || x.obdrzi === false) {
        if (x.obdrzi) meta.appendChild(el("span", "media-obdrzano", ubezi(t("knjiznicaObdrzanoOznaka"))));
        var obdrzi = el("span", "media-obdrzi" + (x.obdrzi ? " je" : ""),
          '<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path d="M6 3h12v18l-6-4-6 4z" fill="' +
          (x.obdrzi ? "currentColor" : "none") + '" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>');
        obdrzi.title = t(x.obdrzi ? "knjiznicaNeObdrzi" : "knjiznicaObdrzi");
        obdrzi.onclick = function (e) {
          e.stopPropagation();
          var novo = !x.obdrzi; card.classList.add("media-caka");
          klic("mediaKnjiznicaObdrzi", [x.kljuc, novo]).then(function (ok) {
            card.classList.remove("media-caka");
            if (!ok) { obvesti(t("knjiznicaObdrziNiUspelo")); return; }
            x.obdrzi = novo; narisiKnjiznico(); obvesti(t(novo ? "knjiznicaObdrzano" : "knjiznicaNiVecObdrzano"));
          }, function () { card.classList.remove("media-caka"); obvesti(t("knjiznicaObdrziNiUspelo")); });
        };
        card.appendChild(obdrzi);
      }
      card.onclick = function () { predvajajIzKnjiznice(x); };
      vrsta.appendChild(card);
    });
    c.appendChild(vrsta);
  }
  function predvajajIzKnjiznice(x) {
    media.ozadje = false; media.izVrste = false;
    var zahteva = media.zahtevaKnjiznicePredvajanja = (media.zahtevaKnjiznicePredvajanja || 0) + 1;
    // Film, ki ni še v celoti na disku ali ga pretaka druga naprava, se ne začne v hipu: uporabnik vidi, da se pripravlja.
    if (x.naprava && x.naprava.id !== "tukaj") obvesti(t("knjiznicaPripravljam", { ime: x.naslov || "", naprava: knjiznicaKje(x) }));
    else if (!x.koncano) obvesti(t("mediaTorrentPripravljam", { ime: x.naslov || "" }));
    klic("mediaKnjiznicaPredvajaj", [x.kljuc]).then(function (item) {
      if (zahteva !== media.zahtevaKnjiznicePredvajanja) return;        // uporabnik je medtem izbral drug film s police
      if (!item || (item.napaka_koda && item.napaka_koda !== "ni_prostora" && item.napaka_koda !== "malo_pomnilnika") || item.napaka) {
        obvesti(t("knjiznicaNiUspelo"));
        if (item && item.napaka_koda === "ni_prenosa") naloziKnjiznico();   // prenosa ni več (odstranjen drugje)
        return;
      }
      poPredvajanju(item, item.id);
    }, function () { if (zahteva === media.zahtevaKnjiznicePredvajanja) obvesti(t("knjiznicaNiUspelo")); });
  }

  function seznamiVidni() { return (media.filter === "glasba" || media.filter === "vse") && !media.query.trim(); }
  function naloziSeznamePredvajanja() {
    return klic("mediaSeznami").then(function (s) { media.seznami = s || []; narisiSeznamePredvajanja(); }, function () {});
  }
  function odpriSeznamPredvajanja(ime) {
    klic("mediaSeznam", [ime]).then(function (sz) {
      if (!sz || !sz.vnosi || !sz.vnosi.length) { obvesti(t("seznamNiUspel")); return; }
      media.seznam = sz; narisiMedia();
      var vsebina = $("vsebina"), c = $("mediaSeznami"); if (vsebina && c) c.scrollIntoView({ block: "start" });
    }, function () { obvesti(t("seznamNiUspel")); });
  }
  function uvoziSeznamPredvajanja(povezava) {
    povezava = String(povezava || "").trim(); if (!povezava) return;
    obvesti(t("seznamUvazam"));
    klic("mediaUvoziSeznam", [povezava]).then(function (r) {
      if (!r || r.napaka) { obvesti(t(r && r.napaka === "ni_seznam" ? "seznamNiSeznam" : "seznamNiUspel")); return; }
      obvesti(t("seznamUvozen", { ime: r.ime, n: r.stevilo }));
      naloziSeznamePredvajanja().then(function () { odpriSeznamPredvajanja(r.ime); });
    }, function () { obvesti(t("seznamNiUspel")); });
  }
  function narisiSeznamePredvajanja() {
    var c = $("mediaSeznami"); if (!c) return; c.innerHTML = "";
    if (media.seznam) {
      c.hidden = false;
      var sz = media.seznam, glava = el("div", "media-seznam-glava");
      var nazaj = el("button", "gumb", ubezi(t("seznamNazaj")));
      nazaj.onclick = function () { media.seznam = null; narisiMedia(); };
      glava.appendChild(nazaj);
      glava.appendChild(el("h3", "", ubezi(sz.ime)));
      glava.appendChild(el("small", "", ubezi(stSkladb(sz.vnosi.length) + (sz.vir ? " · " + sz.vir : ""))));
      var vse = el("button", "gumb glavni", ubezi("▶ " + t("seznamPredvajajVse")));
      vse.onclick = function () { var prvi = sz.vnosi[0]; if (prvi) { nastaviVrsto(prvi); odpriMedia(prvi.id); } };
      glava.appendChild(vse);
      // Odstranitev v dveh korakih (prvi klik vprasa), brez sistemskega okna.
      var odstrani = el("button", "gumb", ubezi(t("seznamOdstrani"))), potrjeno = false;
      odstrani.onclick = function () {
        if (!potrjeno) { potrjeno = true; odstrani.textContent = t("seznamOdstraniRes"); return; }
        klic("mediaOdstraniSeznam", [sz.ime]).then(function () { media.seznam = null; naloziSeznamePredvajanja().then(narisiMedia); });
      };
      glava.appendChild(odstrani);
      c.appendChild(glava);
      return;
    }
    if (!seznamiVidni()) { c.hidden = true; return; }
    c.hidden = false;
    c.appendChild(el("h3", "", ubezi(t("seznamiNaslov"))));
    var vrsta = el("div", "media-seznami-vrsta");
    (media.seznami || []).forEach(function (sz) {
      var k = el("button", "media-seznam-kartica");
      if (sz.slika) {
        var slika = document.createElement("img"); slika.alt = ""; slika.loading = "lazy"; slika.src = sz.slika;
        slika.onerror = function () { slika.replaceWith(el("span", "media-brez-slike", svg("glasba"))); };
        k.appendChild(slika);
      } else k.appendChild(el("span", "media-brez-slike", svg("glasba")));
      var opis = el("span"); opis.appendChild(el("b", "", ubezi(sz.ime)));
      opis.appendChild(el("small", "", ubezi(stSkladb(sz.stevilo) + (sz.vir ? " · " + sz.vir : ""))));
      k.appendChild(opis);
      k.onclick = function () { odpriSeznamPredvajanja(sz.ime); };
      vrsta.appendChild(k);
    });
    var obrazec = el("form", "media-seznam-uvoz"), polje = document.createElement("input");
    polje.type = "text"; polje.placeholder = t("seznamUvoziNamig"); polje.autocomplete = "off";
    var gumb = el("button", "gumb", ubezi(t("seznamUvozi"))); gumb.type = "submit";
    obrazec.appendChild(polje); obrazec.appendChild(gumb);
    obrazec.onsubmit = function (e) { e.preventDefault(); var v = polje.value; polje.value = ""; uvoziSeznamPredvajanja(v); };
    vrsta.appendChild(obrazec);
    c.appendChild(vrsta);
  }
  // "Na seznam": trenutno skladbo dodas na obstojec seznam predvajanja ali na novega (svoj seznam nastaja med poslusanjem).
  function pokaziSeznamMeni() {
    var m = $("mediaSeznamMeni"), item = media.aktivni; if (!m || !item) return;
    if (!m.hidden) { m.hidden = true; return; }
    m.innerHTML = "";
    var dodaj = function (ime) {
      ime = String(ime || "").trim(); if (!ime) return;
      klic("mediaDodajNaSeznam", [ime, item.id]).then(function (r) {
        m.hidden = true;
        obvesti(r && r.ok ? t("seznamDodano", { ime: ime }) : (r && r.ze ? t("seznamZe", { ime: ime }) : t("seznamNiMogoce")));
        naloziSeznamePredvajanja();
      }, function () { obvesti(t("seznamNiMogoce")); });
    };
    (media.seznami || []).forEach(function (sz) {
      var g = el("button", "gumb", ubezi(sz.ime)); g.onclick = function () { dodaj(sz.ime); }; m.appendChild(g);
    });
    var obrazec = document.createElement("form"), polje = document.createElement("input");
    polje.type = "text"; polje.maxLength = 60; polje.placeholder = t("seznamNovIme");
    var nov = el("button", "gumb", ubezi(t("seznamNov"))); nov.type = "submit";
    obrazec.style.display = "flex"; obrazec.style.gap = "8px";
    obrazec.appendChild(polje); obrazec.appendChild(nov);
    obrazec.onsubmit = function (e) { e.preventDefault(); if (!polje.value.trim()) { polje.focus(); return; } dodaj(polje.value); };
    m.appendChild(obrazec);
    m.hidden = false;
  }
  // Vgradni predvajalnik YouTuba sporoca stanje (konec posnetka, napaka) s postMessage: ob koncu naslednja iz vrste.
  window.addEventListener("message", function (e) {
    if (e.origin !== "https://www.youtube.com" || !media.ytSkladba) return;
    var d; try { d = typeof e.data === "string" ? JSON.parse(e.data) : e.data; } catch (x) { return; }
    if (!d) return;
    var skladba = media.ytSkladba;
    var stanje = d.event === "onStateChange" ? d.info : (d.event === "infoDelivery" && d.info && typeof d.info.playerState === "number" ? d.info.playerState : null);
    if (stanje === 1 && !media.ytIgra) { media.ytIgra = true; osveziMini(); }
    if (stanje === 2 && media.ytIgra) { media.ytIgra = false; media.ytZeIgral = true; osveziMini(); }
    if (stanje === 0 && (media.ytIgra || media.ytZeIgral)) {
      media.ytIgra = false; media.ytSkladba = null;
      if (!predvajajIzVrste(1)) osveziMini();
      return;
    }
    if (d.event === "onError" || (d.event === "infoDelivery" && d.info && d.info.videoData && d.info.videoData.errorCode)) {
      // Lastnik posnetka vgradnje ne dovoli (ali posnetka ni vec): poiscemo drug posnetek iste skladbe, sicer naslednja.
      media.ytSkladba = null; media.ytIgra = false;
      klic("mediaSeznamZamenjava", [skladba.id]).then(function (nova) {
        if (nova && nova.youtube && nova.youtube !== skladba.youtube) { media.aktivni = nova; predvajajHtml(nova, 0); return; }
        obvesti(t("seznamBrezPosnetka", { ime: skladba.naslov || "" }));
        predvajajIzVrste(1);
      }, function () { predvajajIzVrste(1); });
    }
  });
  function predvajajYoutube(item, iframe) {
    media.ytSkladba = item; media.ytIgra = false; media.ytZeIgral = false;
    // Vgradni predvajalnik mora vedeti, kdo ga vgrajuje (Referer), sicer javi napako 153.
    iframe.setAttribute("referrerpolicy", "strict-origin-when-cross-origin");
    iframe.hidden = false;
    iframe.onload = function () {
      if (media.ytSkladba !== item) return;
      var poslji = function (o) { try { iframe.contentWindow.postMessage(JSON.stringify(o), "https://www.youtube.com"); } catch (e) {} };
      poslji({ event: "listening", id: "safeer", channel: "widget" });
      poslji({ event: "command", func: "addEventListener", args: ["onStateChange"], id: "safeer", channel: "widget" });
      poslji({ event: "command", func: "addEventListener", args: ["onError"], id: "safeer", channel: "widget" });
    };
    iframe.src = "https://www.youtube.com/embed/" + encodeURIComponent(item.youtube) + "?autoplay=1&enablejsapi=1&rel=0&playsinline=1&origin=" + encodeURIComponent(location.origin);
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
      // Vir, ki je enak na vseh napravah v Safeer Linku, se izbriše povsod: prvi klik vpraša (brez sistemskega okna).
      var povsod = (source.ponudnik === "stremio" && source.zaseben === false) ||
        (source.vrsta !== "streznik" && source.tip !== "predvajalni_vir" && (!!source.link_tip || (source.stevilo || 0) > 0)), potrjeno = false;
      remove.onclick = function () {
        if (povsod && !potrjeno) { potrjeno = true; remove.classList.add("potrdi"); remove.textContent = t("virOdstraniPovsod"); return; }
        klic("mediaOdstraniVir", [source.id]).then(naloziMedia);
      };
      row.onmouseleave = function () { if (potrjeno) { potrjeno = false; remove.classList.remove("potrdi"); remove.innerHTML = svg("x"); } };
      row.appendChild(remove);
      cilj.appendChild(row);
    });
  }
  function predvajajHtml(item, index) {
    var variants = item.razlicice && item.razlicice.length ? item.razlicice : [{ url:item.url, vir:item.vir, kakovost:item.kakovost, vrsta:item.vrsta }];
    var variant = variants[index || 0] || variants[0], audio = item.vrsta === "glasba" || item.vrsta === "radio" || item.vrsta === "podcast";
    var url = variant.url || "";
    var isDirectMedia = /\.(mp4|mkv|webm|avi|mov|m4v|mp3|flac|ogg|opus|m4a|aac|wav|m3u8)($|\?)/i.test(url) || url.startsWith("file:") || /mpegurl/i.test(variant.mime || item.mime || "") ||
      // Zvočni tok brez končnice (Jamendo, Icecast radio): strežnik je potrdil zvok (audio/*), ni spletna stran.
      (audio && item.neposredni_zvok === true && (index || 0) === 0) ||
      // Tok z druge naprave v Linku (lokalni varni tok 127.0.0.1): neposreden medij brez končnice.
      (item.neposredni === true && /^http:\/\/127\.0\.0\.1:\d+\/m\/[0-9a-f]{32}$/.test(url)) ||
      // Datoteka iz magnet povezave (lokalni tok rqbita z geslom na 127.0.0.1): predvaja se že med prenosom.
      (item.neposredni === true && /^http:\/\/127\.0\.0\.1:\d+\/t\/[0-9a-f]{32}\//.test(url));
    var video = $("mediaVideo"), playerAudio = $("mediaAudio"), iframe = $("mediaIframe"), playerImage = $("mediaSlika");

    if (media.timer) { window.clearTimeout(media.timer); media.timer = 0; }

    if (video) { video.pause(); video.removeAttribute("src"); video.hidden = true; video.style.display = "none"; }
    pocistiPodnapiseStrani(video);
    if (playerAudio) { playerAudio.pause(); playerAudio.removeAttribute("src"); playerAudio.hidden = true; playerAudio.style.display = "none"; }
    if (iframe) { iframe.onload = null; iframe.src = "about:blank"; iframe.hidden = true; }
    media.ytSkladba = null; media.ytIgra = false;
    if (playerImage) { playerImage.removeAttribute("src"); playerImage.hidden = true; }

    var pl = $("mediaPredvajalnik");
    // Glasba v ozadju: naslednja skladba iz vrste ne sme sredi brskanja odpreti plošče predvajalnika.
    if (!audio) media.ozadje = false;
    if (pl) { pl.hidden = !!media.ozadje; pl.classList.remove("kino"); }
    var napakaEl = $("mediaNapaka");
    napakaEl.hidden = true;
    napakaEl.classList.remove("media-opozorilo");
    napakaEl.textContent = t("mediaNapaka");
    $("mediaPredvajalnikNaslov").textContent = item.naslov || "Medijski center";

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
        if (!audio) podnapisiStrani(player, item);
        try {
          // Nadaljevanje samo za video (film, epizoda). Skladba se vedno začne od začetka – sicer bi se
          // ob ponovnem krogu albuma začela tik pred koncem in vrsta bi se vrtela v prazno.
          var kljucNapredka = "safeer_media_progress_" + (item.id || url);
          if (audio) { player.ontimeupdate = null; localStorage.removeItem(kljucNapredka); }
          else {
            var shranjenCas = Number(localStorage.getItem(kljucNapredka) || 0);
            if (shranjenCas > 3) player.currentTime = shranjenCas;
            player.ontimeupdate = function () {
              if (player.currentTime > 3) localStorage.setItem(kljucNapredka, String(Math.floor(player.currentTime)));
            };
          }
        } catch (e) {}
        player.onerror = function () {
          if (media.timer) window.clearTimeout(media.timer);
          media.timer = 0;
          if (!poskusiNaslednjo()) {
            $("mediaNapaka").hidden = false;
            // Glasba v ozadju: plošča je skrita, zato napako pokažemo v mali vrstici.
            if (media.ozadje && $("mediaMiniMeta")) { $("mediaMiniMeta").textContent = $("mediaNapaka").textContent; obvesti($("mediaNapaka").textContent); }
          }
        };
        player.onended = audio ? function () { if (!predvajajIzVrste(1)) osveziMini(); } :
          function () { try { localStorage.removeItem("safeer_media_progress_" + (item.id || url)); } catch (e) {} };
        if (audio) { player.onplay = osveziMini; player.onpause = osveziMini; }
        player.play().catch(function () {});
        osveziMini();
        if (navigator.mediaSession) {
          try { navigator.mediaSession.metadata = new MediaMetadata({title: item.naslov || "Medijski center", artist: item.izvajalec || item.vir || "Safeer OS", artwork: item.slika ? [{src: item.slika}] : []}); } catch (e) {}
        }
        media.timer = window.setTimeout(function () {
          media.timer = 0;
          if (player.readyState < 2 && !poskusiNaslednjo()) $("mediaNapaka").hidden = false;
        }, 20000);
      }
    } else if (item.youtube && iframe) {
      predvajajYoutube(item, iframe);
      osveziMini();
    } else {
      if (iframe && /^https?:\/\//i.test(url)) {
        iframe.setAttribute("referrerpolicy", "no-referrer");
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
  // ------------------------------------------------------------------ glasba: cakalna vrsta
  // Ideja po Tauonu (koda je nasa): po koncu skladbe samodejno naslednja, premesaj, ponovi.
  function vrstaNastavitev(kljuc, privzeto) {
    try { var v = localStorage.getItem("safeer_glasba_" + kljuc); return v == null ? privzeto : v; } catch (e) { return privzeto; }
  }
  function vrstaShrani(kljuc, vrednost) { try { localStorage.setItem("safeer_glasba_" + kljuc, String(vrednost)); } catch (e) {} }
  function nastaviVrsto(zacetni) {
    // Skladba z odprtega seznama predvajanja: vrsta je seznam (v njegovem vrstnem redu), ne katalog.
    var osnova = media.seznam && media.seznam.vnosi.some(function (x) { return x.id === zacetni.id; }) ? media.seznam.vnosi : (media.katalog || []);
    var seznam = osnova.filter(function (x) { return x.vrsta === zacetni.vrsta && !x.stran; });
    media.vrsta = seznam.map(function (x) { return x.id; });
    media.vrstaMesto = Math.max(0, media.vrsta.indexOf(zacetni.id));
    media.vrstaZgodovina = [];
    narisiVrsto();
  }
  function naslednjiVVrsti(smer) {
    var n = (media.vrsta || []).length;
    if (!n) return null;
    if (smer < 0) {
      if (media.vrstaZgodovina && media.vrstaZgodovina.length) return media.vrstaZgodovina.pop();
      return (media.vrstaMesto - 1 + n) % n;
    }
    if (vrstaNastavitev("ponovi", "0") === "1") return media.vrstaMesto;          // ponovi skladbo
    if (vrstaNastavitev("premesaj", "0") === "1" && n > 1) {
      var r; do { r = Math.floor(Math.random() * n); } while (r === media.vrstaMesto);
      return r;
    }
    var naslednji = media.vrstaMesto + 1;
    return naslednji < n ? naslednji : (vrstaNastavitev("ponoviVse", "1") === "1" ? 0 : null);
  }
  function predvajajIzVrste(smer) {
    var mesto = naslednjiVVrsti(smer);
    if (mesto == null) return false;
    if (smer > 0) (media.vrstaZgodovina = media.vrstaZgodovina || []).push(media.vrstaMesto);
    media.vrstaMesto = mesto;
    narisiVrsto();
    media.izVrste = true;       // naslednja/prejšnja iz vrste: ostani v ozadju, če je glasba v ozadju
    odpriMedia(media.vrsta[mesto]);
    return true;
  }
  function narisiVrsto() {
    var ima = (media.vrsta || []).length > 1;
    ["mediaPrejsnja", "mediaNaslednja", "mediaPremesaj", "mediaPonovi"].forEach(function (id) {
      var g = $(id); if (g) g.hidden = !ima;
    });
    var pm = $("mediaPremesaj"), po = $("mediaPonovi");
    if (pm) pm.classList.toggle("vklopljen", vrstaNastavitev("premesaj", "0") === "1");
    if (po) po.classList.toggle("vklopljen", vrstaNastavitev("ponovi", "0") === "1");
    if (navigator.mediaSession) {
      try {
        navigator.mediaSession.setActionHandler("nexttrack", ima ? function () { predvajajIzVrste(1); } : null);
        navigator.mediaSession.setActionHandler("previoustrack", ima ? function () { predvajajIzVrste(-1); } : null);
      } catch (e) {}
    }
  }

  function odpriMedia(id) {
    // Uporabnik je sam izbral vsebino: pokaži predvajalnik (tudi, če je prej glasba igrala v ozadju).
    if (!media.izVrste) media.ozadje = false;
    var izVrste = media.izVrste;
    media.izVrste = false;
    // Skladba z druge naprave (vrsta albuma iz Datotek): naslednja gre po istem varnem toku.
    var link = String(id || "").indexOf("link:") === 0 && S.linkMediji && S.linkMediji[id];
    if (link) { predvajajZNaprave(link.naprava, link.d, link.server, izVrste); return; }
    // Prenos, ki ga izdajatelj ponuja samo na svoji strani (npr. RTV SLO): odpremo ga v Spletu.
    var znan = (media.katalog || []).find(function (x) { return x.id === id; });
    if (znan && znan.stran) { otvoriSpletnoStran(znan.stran, znan.naslov); return; }
    klic("mediaPredvajaj", [id]).then(function (item) { poPredvajanju(item, id); }, function () { obvesti(t("mediaVirNapaka")); });
  }
  // Odgovor predvajalnika (katalog ali polica »Na tvojih napravah«): napaka kot kratko obvestilo, sicer predvajanje.
  function poPredvajanju(item, id) {
      if (!item) { obvesti(t("mediaVirNapaka")); return; }
      if (item.napaka_koda === "ni_toka") {
        // Noben vir tega ne predvaja: brez okna in brez strani - kratko obvestilo, film izgine iz mreze.
        obvesti(t("mediaNapaka_ni_toka", { ime: item.naslov || "" }));
        if (item.vrsta === "film") {
          var prej = (media.katalog || []).length;
          media.katalog = (media.katalog || []).filter(function (x) {
            return !(x.vrsta === "film" && (x.id === item.id || x.id === id || (item.tmdb_id && x.tmdb_id === item.tmdb_id)));
          });
          if (typeof media.skupaj === "number") media.skupaj = Math.max(media.katalog.length, media.skupaj - (prej - media.katalog.length));
          zapriMediaPodrobnosti(); narisiMedia();
        }
        return;
      }
      if (item.napaka_koda) { obvesti(t("mediaNapaka_" + item.napaka_koda)); return; }
      if (item.napaka) { obvesti(item.napaka); return; }
      if (item.sporocilo) { obvesti(item.sporocilo); return; }
      // »stran« ob toku, ki ga predvajalnik že igra, je le izvor (npr. stran filma v arhivu): v Splet gre samo,
      // kar nima toka - sicer bi se film predvajal, čez njega pa bi se odprla še spletna stran.
      if (item.stran && !item.native) { otvoriSpletnoStran(item.stran, item.naslov); return; }
      media.aktivni = item;
      klic("mediaImaKodi").then(function (ima) { var g = $("mediaNaKodi"); if (g) g.hidden = !ima; });
      var gs = $("mediaNaSeznam"); if (gs) gs.hidden = !(item.vrsta === "glasba" || item.vrsta === "podcast");
      var ms = $("mediaSeznamMeni"); if (ms) ms.hidden = true;
      var gz = $("mediaNaZvocnik"); if (gz) gz.hidden = !!(item.native || item.vrsta === "film" || item.vrsta === "serija" || item.vrsta === "video");
      var pz = $("mediaZvocnikPlosca"); if (pz) pz.hidden = true;
      if (!item.native) predvajajHtml(item, 0);
  }
  function vezaVrste() {
    var g = function (id, fn) { var e = $(id); if (e) e.addEventListener("click", fn); };
    g("mediaPrejsnja", function () { predvajajIzVrste(-1); });
    g("mediaNaslednja", function () { predvajajIzVrste(1); });
    g("mediaPremesaj", function () { vrstaShrani("premesaj", vrstaNastavitev("premesaj", "0") === "1" ? "0" : "1"); narisiVrsto(); });
    g("mediaPonovi", function () { vrstaShrani("ponovi", vrstaNastavitev("ponovi", "0") === "1" ? "0" : "1"); narisiVrsto(); });
    narisiVrsto();
  }
  document.addEventListener("DOMContentLoaded", vezaVrste);
  if (document.readyState !== "loading") setTimeout(vezaVrste, 0);

  // Mala vrstica za glasbo v ozadju: naslov, nazaj/pavza/naprej, odpri ploščo, ustavi.
  function zvokTece() {
    var a = $("mediaAudio");
    // Skladba s seznama predvajanja igra v vgradnem predvajalniku (okvir): tudi to je zvok, ki tece v ozadju.
    return !!(media.aktivni && ((a && a.getAttribute("src")) || media.ytSkladba));
  }
  function ytUkaz(func) {
    var iframe = $("mediaIframe");
    try { iframe.contentWindow.postMessage(JSON.stringify({ event: "command", func: func, args: [], id: "safeer", channel: "widget" }), "https://www.youtube.com"); } catch (e) {}
  }
  function osveziMini() {
    var m = $("mediaMini"); if (!m) return;
    var a = $("mediaAudio");
    var vidna = !!media.ozadje && zvokTece();
    m.hidden = !vidna;
    if (!vidna) return;
    $("mediaMiniNaslov").textContent = (media.aktivni && media.aktivni.naslov) || "";
    $("mediaMiniMeta").textContent = (media.aktivni && (media.aktivni.izvajalec || media.aktivni.vir)) || "";
    $("mediaMiniPremor").innerHTML = (media.ytSkladba ? media.ytIgra : (a && !a.paused)) ? "&#10074;&#10074;" : "&#9654;";
    var vec = (media.vrsta || []).length > 1;
    $("mediaMiniPrejsnja").disabled = !vec; $("mediaMiniNaslednja").disabled = !vec;
  }
  function nazajIzPredvajalnika() {
    // Zvok igra naprej v ozadju (kot v vsakem glasbenem predvajalniku); video in spletni viri se zaprejo.
    if (!zvokTece()) { zapriMediaHtml(); return; }
    var pl = $("mediaPredvajalnik");
    if (pl) { if (pl.classList.contains("kino")) { pl.classList.remove("kino"); klic("celozaslonsko", [false]); } pl.hidden = true; }
    media.ozadje = true;
    osveziMini();
  }
  function odpriIzMini() {
    media.ozadje = false;
    var pl = $("mediaPredvajalnik"); if (pl) pl.hidden = false;
    osveziMini();
    if (window.safeerOsPojdi) window.safeerOsPojdi("media");
  }
  function zapriMediaHtml() {
    media.ozadje = false;
    var mini = $("mediaMini"); if (mini) mini.hidden = true;
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
    if (filter === "glasba" || filter === "radio" || filter === "tv-v-zivo") return filter;
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
    vse.textContent = skupina === "radio" ? "Vse postaje" : skupina === "tv-v-zivo" ? "Vse države" : "Vsa glasba";
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

  // Katalog pride najprej iz predpomnilnika (takoj); ko v ozadju prispejo sveži podatki,
  // jih Python pošlje kot dogodek "mediaKatalogOsvezen" in pogled tiho posodobimo.
  // Viri, ki jih uporabnik lahko zacasno izklopi: iz trenutnih kartic in seznama virov.
  // Zapomnimo si jih, da izklopljen vir ne izgine iz seznama (sicer ga ne bi mogel spet vklopiti).
  function zapomniMediaVire(response) {
    ((response && response.vnosi) || []).forEach(function (x) {
      var razl = (x.razlicice && x.razlicice.length) ? x.razlicice : [x];
      razl.forEach(function (r) { if (r.vir_id && r.vir_id !== "lokalno") media.znaniViri[r.vir_id] = r.vir || r.vir_id; });
    });
    ((response && response.viri) || []).forEach(function (v) { if (v.id) media.znaniViri[v.id] = v.ime || v.id; });
    ((response && response.vnosi) || []).forEach(function (x) { if (x.jezik) media.znaniJeziki[x.jezik] = 1; });
  }
  function imeJezika(koda) {
    try { var ime = new Intl.DisplayNames([LOKALE[jezik] || "sl-SI"], { type: "language" }).of(koda);
          return ime ? ime.charAt(0).toLocaleUpperCase() + ime.slice(1) : koda; }
    catch (_) { return koda; }
  }
  function osveziGumbViri() {
    var gumb = $("mediaViriFilterGumb"); if (!gumb) return;
    var n = Object.keys(media.izklopljeni).length + Object.keys(media.izklopljeniJeziki).length;
    gumb.textContent = media.samoLokalno ? "Viri in jeziki: samo ta naprava" : (n ? "Viri in jeziki: " + n + " izklopljen" + (n === 1 ? "" : (n === 2 ? "a" : (n < 5 ? "i" : "ih"))) : "Viri in jeziki: vsi");
    gumb.classList.toggle("aktiven", media.samoLokalno || n > 0);
  }
  function narisiViriFilter() {
    var seznam = $("mediaViriFilterSeznam"); if (!seznam) return;
    seznam.innerHTML = "";
    var ids = Object.keys(media.znaniViri).sort(function (a, b) { return String(media.znaniViri[a]).localeCompare(String(media.znaniViri[b])); });
    if (!ids.length) seznam.appendChild(el("small", "", "Viri se pokažejo, ko se katalog naloži."));
    ids.forEach(function (id) {
      var vrstica = el("label"), cb = el("input");
      cb.type = "checkbox"; cb.checked = !media.izklopljeni[id];
      cb.onchange = function () {
        if (cb.checked) delete media.izklopljeni[id]; else media.izklopljeni[id] = 1;
        osveziGumbViri(); media.page = 1; naloziMedia();
      };
      var besedilo = el("span"); besedilo.appendChild(el("b", "", ubezi(media.znaniViri[id])));
      vrstica.appendChild(cb); vrstica.appendChild(besedilo); seznam.appendChild(vrstica);
    });
    seznam.classList.toggle("onemogoceno", media.samoLokalno);
    $("mediaSamoLokalno").checked = media.samoLokalno;
    var jeziki = $("mediaJezikiFilterSeznam");
    if (jeziki) {
      jeziki.innerHTML = "";
      var kode = Object.keys(media.znaniJeziki).sort(function (a, b) { return imeJezika(a).localeCompare(imeJezika(b)); });
      if (!kode.length) jeziki.appendChild(el("small", "", "Jeziki se pokažejo, ko se katalog naloži."));
      kode.forEach(function (koda) {
        var vrstica = el("label"), cb = el("input");
        cb.type = "checkbox"; cb.checked = !media.izklopljeniJeziki[koda];
        cb.onchange = function () {
          if (cb.checked) delete media.izklopljeniJeziki[koda]; else media.izklopljeniJeziki[koda] = 1;
          osveziGumbViri(); media.page = 1; naloziMedia();
        };
        var besedilo = el("span"); besedilo.appendChild(el("b", "", ubezi(imeJezika(koda))));
        vrstica.appendChild(cb); vrstica.appendChild(besedilo); jeziki.appendChild(vrstica);
      });
      jeziki.classList.toggle("onemogoceno", media.samoLokalno);
    }
  }

  function prevzemiMediaKatalog(response, tiho) {
    zapomniMediaVire(response);
    if (!$("mediaViriFilter").hidden) narisiViriFilter();
    media.kljuc = (response && response.kljuc) || "";
    media.katalog = (response && response.vnosi) || [];
    if (response && response.viri) media.viri = response.viri;
    media.skupaj_strani = (response && response.skupaj_strani) || 1;
    media.skupaj = (response && typeof response.skupaj === "number") ? response.skupaj : null;
    var drsnik = $("vsebina") || document.documentElement;
    var odmik = drsnik.scrollTop;
    narisiMedia();
    if (tiho) drsnik.scrollTop = odmik;
  }

  function naloziMedia() {
    narisiZanre();
    naloziSeznamePredvajanja();
    naloziKnjiznico();
    var zahteva = ++media.zahteva;
    $("mediaPovzetek").textContent = "Nalagam katalog …";
    return klic("mediaKatalog", [media.query, media.filter, media.genre, media.page || 1,
                          media.razvrsti, Object.keys(media.izklopljeni), media.samoLokalno,
                          Object.keys(media.izklopljeniJeziki)]).then(function (response) {
      if (zahteva !== media.zahteva) return;
      prevzemiMediaKatalog(response);
      if (media.query) setTimeout(function () { var prvi = $("mediaMreza").querySelector(".media-kartica"); if (prvi) prvi.focus(); }, 30);
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
    var groups = data.skupine || [];
    // Brez drzave in brez ponudnikov (npr. vsebina iz dodatka brez podatkov TMDB) okvirja ne kazemo.
    target.hidden = !groups.length && !String(countryName || "").replace(/[\s,()]/g, "");
    if (target.hidden) return;
    target.appendChild(el("h3", "", t("mediaWatchTitle", {country:countryName})));
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
        var play = el("button", "gumb glavni", "▶ Predvajaj");
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
        var playBtn = el("button", "gumb glavni", "▶ Predvajaj film");
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
      media.page = 1; media.seznam = null;
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
  on("mediaRazvrsti", "change", function () {
    media.razvrsti = $("mediaRazvrsti").value; media.page = 1; naloziMedia();
  });
  on("mediaViriFilterGumb", "click", function (event) {
    event.stopPropagation();
    var plosca = $("mediaViriFilter"), odpri = plosca.hidden;
    plosca.hidden = !odpri; $("mediaViriFilterGumb").setAttribute("aria-expanded", odpri ? "true" : "false");
    if (odpri) narisiViriFilter();
  });
  on("mediaSamoLokalno", "change", function () {
    media.samoLokalno = $("mediaSamoLokalno").checked;
    narisiViriFilter(); osveziGumbViri(); media.page = 1; naloziMedia();
  });
  on("mediaViriFilterPonastavi", "click", function () {
    media.izklopljeni = {}; media.izklopljeniJeziki = {}; media.samoLokalno = false;
    narisiViriFilter(); osveziGumbViri(); media.page = 1; naloziMedia();
  });
  document.addEventListener("click", function (event) {
    var plosca = $("mediaViriFilter");
    if (plosca && !plosca.hidden && !event.target.closest(".media-filter-viri")) {
      plosca.hidden = true; $("mediaViriFilterGumb").setAttribute("aria-expanded", "false");
    }
  });
  on("mediaIskanje", "input", function () {
    media.query = this.value; media.page = 1; media.seznam = null; clearTimeout(media.timer); media.timer = setTimeout(naloziMedia, 350);
  });
  on("mediaPodrobnostiNazaj", "click", zapriMediaPodrobnosti);
  on("mediaPodrobnostiZapri", "click", zapriMediaPodrobnosti);
  on("mediaZapri", "click", zapriMediaHtml);
  on("mediaNaKodi", "click", function () {
    var item = media.aktivni;
    if (!item) return;
    klic("mediaNaKodi", [item.id]).then(function (r) {
      if (r && r.ok) { obvesti(item.naslov + " se predvaja na " + r.kodi + "."); zapriMediaHtml(); }
      else obvesti((r && r.napaka) || t("niUspelo"));
    });
  });
  // ------------------------------------------------------------------ zvocnik v omrezju (DLNA)
  var zvocnikPotrdi = {};
  function plosciZvocnika() {
    var p = $("mediaZvocnikPlosca");
    if (!p) {
      p = el("div", "media-zvocnik"); p.id = "mediaZvocnikPlosca"; p.hidden = true;
      var pl = $("mediaPredvajalnik"); if (pl) pl.appendChild(p);
    }
    return p;
  }
  function narisiZvocnike(r) {
    var p = plosciZvocnika(); p.innerHTML = "";
    r = r || { zvocniki: [] };
    if (r.aktiven) {
      p.appendChild(el("b", "", ubezi(t("zvocnikNaslov", { ime: r.aktiven }))));
      var v = el("div", "vrsta");
      [["premor", t("zvocnikPremor")], ["tisje", "−"], ["glasneje", "+"], ["ustavi", t("zvocnikNazaj")]].forEach(function (d) {
        var g = el("button", "gumb", ubezi(d[1]));
        g.addEventListener("click", function () {
          klic("mediaZvocnikDejanje", [d[0]]).then(function () {
            if (d[0] === "ustavi") { p.hidden = true; var a = $("mediaAudio"); if (a && a.src) a.play(); }
          });
        });
        v.appendChild(g);
      });
      p.appendChild(v);
      return;
    }
    if (!r.zvocniki.length) { p.appendChild(el("div", "drobno", ubezi(t("zvocnikNiNajdenih")))); return; }
    r.zvocniki.forEach(function (z) {
      var vir = zvocnikPotrdi[z.id];
      var g = el("button", "gumb zvocnik" + (vir ? "" : " glavni"), ubezi(vir ? t("zvocnikZaseden", { ime: z.ime, vir: vir }) : z.ime));
      g.addEventListener("click", function () {
        var item = media.aktivni; if (!item) return;
        var soglasje = !!zvocnikPotrdi[z.id]; delete zvocnikPotrdi[z.id];
        klic("mediaNaZvocnik", [item.id, z.id, soglasje]).then(function (o) {
          if (o && o.vir) { zvocnikPotrdi[z.id] = o.vir; narisiZvocnike(r); return; }
          if (!o || !o.ok) { obvesti(o && o.napaka === "vir_ni_za_zvocnik" ? t("zvocnikNiVir") : t("niUspelo")); return; }
          [$("mediaAudio"), $("mediaVideo")].forEach(function (pl) { if (pl) pl.pause(); });
          obvesti(t("zvocnikIgra", { ime: o.ime }));
          klic("mediaZvocniki").then(narisiZvocnike);
        });
      });
      p.appendChild(g);
    });
  }
  function naloziZvocnike(poskus) {
    klic("mediaZvocniki").then(function (r) {
      if (r && !r.aktiven && !(r.zvocniki || []).length && poskus < 3) { setTimeout(function () { naloziZvocnike(poskus + 1); }, 1500); return; }
      narisiZvocnike(r);
    });
  }
  on("mediaNaZvocnik", "click", function () {
    var p = plosciZvocnika();
    if (!p.hidden) { p.hidden = true; return; }
    p.hidden = false; p.innerHTML = "";
    p.appendChild(el("div", "drobno", ubezi(t("zvocnikIscem"))));
    naloziZvocnike(0);
  });
  on("mediaPredvajalnikNazaj", "click", nazajIzPredvajalnika);
  on("mediaMiniOdpri", "click", odpriIzMini);
  on("mediaMiniZapri", "click", zapriMediaHtml);
  on("mediaNaSeznam", "click", pokaziSeznamMeni);
  on("mediaMiniPrejsnja", "click", function () { predvajajIzVrste(-1); });
  on("mediaMiniNaslednja", "click", function () { predvajajIzVrste(1); });
  on("mediaMiniPremor", "click", function () {
    if (media.ytSkladba) { ytUkaz(media.ytIgra ? "pauseVideo" : "playVideo"); return; }
    var a = $("mediaAudio"); if (!a) return; if (a.paused) a.play().catch(function () {}); else a.pause();
  });
  window.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      var pl = $("mediaPredvajalnik");
      if (pl && !pl.hidden) {
        nazajIzPredvajalnika();
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
  on("medijiPredaja", "click", odpriPredajo);
  on("predajaZapri", "click", function () { $("slojPredaja").classList.remove("viden"); });
  // Magnet povezave in DVD (Safeer Media).
  on("medijiMagnet", "click", function () { odpriMagnet(""); });
  on("medijiDisk", "click", function () {
    if (S.dvdPogon) klic("dvdPredvajaj", [S.dvdPogon]).then(function (r) {
      if (!r || !r.ok) obvesti(t("mediaNapaka_" + ((r && r.koda) || "dvd")));
    }).catch(function () { obvesti(t("mediaNapaka_dvd")); });
  });
  on("magnetZapri", "click", zapriSloje);
  on("magnetObrazec", "submit", function (e) {
    e.preventDefault();
    var uri = $("magnetPolje").value.trim();
    if (uri.indexOf("magnet:?") !== 0) { magnetSporocilo(magnetNapaka("ni_magnet")); return; }
    preberiMagnet(uri, false);
  });
  on("magnetDeliDatoteko", "click", function () { zagotoviProgram().then(function (ok) { if (ok) klic("magnetIzDatoteke", [false]); }); });
  on("magnetDeliMapo", "click", function () { zagotoviProgram().then(function (ok) { if (ok) klic("magnetIzDatoteke", [true]); }); });
  on("magnetPrivzeto", "click", function () {
    // Protokol magnet: registriramo samo na ta izrecni pritisk uporabnika (HKCU, brez skrbniških pravic).
    klic("magnetPrivzeto", [true]).then(function (je) {
      $("magnetPrivzeto").hidden = !!je;
      obvesti(je ? t("magnetPrivzetoOk") : t("magnetPrivzetoNastavitve"));
    });
  });
  koMost(function () {
    klic("cakajociMagnet").then(function (c) { if (c && c.uri) odpriMagnet(c.uri, c.samodejno === true); }).catch(function () {});
  });
  on("mediaDodajVir", "submit", function (event) {
    event.preventDefault(); var url = $("mediaVirUrl").value.trim(), name = $("mediaVirIme").value.trim();
    if (!url) return;
    $("mediaVirSporocilo").textContent = t("mediaDodaj") + " …";
    klic("mediaDodajVir", [url, name]).then(function (result) {
      if (result && result.ok) { $("mediaVirUrl").value = ""; $("mediaVirIme").value = ""; $("mediaVirSporocilo").textContent = t("mediaVirDodan"); }
      else $("mediaVirSporocilo").textContent = (result && result.napaka === "podvojen") ? t("mediaVirPodvojen")
        : (result && result.sporocilo) ? result.sporocilo : ((result && result.napaka) ? result.napaka : t("mediaVirNapaka"));
      if (result && !result.ok && result.sporocilo) obvesti(result.sporocilo);
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
    var potrebnaPrijava = { jellyfin: 1, emby: 1, navidrome: 1, plex: 1 };
    if (!url) return;
    if (potrebnaPrijava[provider] && !secret) {
      $("mediaVirSporocilo").textContent = "Ta strežnik potrebuje geslo ali žeton.";
      return;
    }
    $("mediaVirSporocilo").textContent = "Povezujem strežnik …";
    klic("mediaDodajStreznik", [provider, name, url, username, secret]).then(function (result) {
      $("mediaStreznikSkrivnost").value = "";
      if (result && result.ok) {
        $("mediaStreznikUrl").value = ""; $("mediaStreznikIme").value = "";
        $("mediaVirSporocilo").textContent = "Strežnik je varno povezan.";
      } else {
        $("mediaVirSporocilo").textContent = (result && result.napaka) || t("mediaVirNapaka");
        if (result && result.sporocilo) obvesti(result.sporocilo);
      }
      naloziMedia();
    }, function () {
      $("mediaStreznikSkrivnost").value = "";
      $("mediaVirSporocilo").textContent = t("mediaVirNapaka");
    });
  });

  // DLNA/UPnP (Gerbera, MiniDLNA, NAS, TV sprejemniki): poiscemo jih v domacem omrezju in jih
  // ponudimo za povezavo z enim klikom - uporabnik naslova opisa naprave ne pozna.
  on("mediaOdkrijDlna", "click", function () {
    var sporocilo = $("mediaVirSporocilo");
    sporocilo.textContent = "Iščem medijske strežnike v domačem omrežju …";
    klic("mediaOdkrijDlna").then(function (najdeni) {
      var seznam = najdeni || [];
      if (!seznam.length) { sporocilo.textContent = "V domačem omrežju ni najdenega strežnika DLNA/UPnP."; return; }
      sporocilo.textContent = "Najdeni strežniki – klikni za povezavo:";
      seznam.forEach(function (n) {
        var g = el("button", "gumb"); g.type = "button"; g.textContent = "Poveži " + n.ime;
        g.addEventListener("click", function () {
          sporocilo.textContent = "Povezujem " + n.ime + " …";
          klic("mediaDodajStreznik", ["dlna", n.ime, n.url, "", ""]).then(function (r) {
            sporocilo.textContent = r && r.ok ? (n.ime + " je povezan.") : ((r && r.napaka) || t("mediaVirNapaka"));
            naloziMedia();
          });
        });
        sporocilo.appendChild(document.createElement("br"));
        sporocilo.appendChild(g);
      });
    }, function () { sporocilo.textContent = t("mediaVirNapaka"); });
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
          "title": "Big Buck Bunny (Primer neposrednega MP4 videa)",
          "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
          "kind": "film",
          "year": 2008,
          "quality": "1080p",
          "poster": "https://upload.wikimedia.org/wikipedia/commons/c/c5/Big_buck_bunny_poster_big.jpg"
        },
        {
          "title": "Sintel (Blender Foundation, CC BY 3.0)",
          "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/Sintel.mp4",
          "kind": "film",
          "year": 2010,
          "quality": "1080p"
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
