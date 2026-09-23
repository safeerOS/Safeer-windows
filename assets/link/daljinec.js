/**
 * Safeer Control — daljinec v Safeer Linku.
 *
 * Ko sta napravi povezani prek Safeer Linka, telefon (ali racunalnik) upravlja televizor:
 * z glasom, s tipkami, z dotikom aplikacije. Vse gre po Linku kot `control.command`;
 * odgovor pride kot `control.result`. Stran ne vidi ne zetona ne omrezja - za vse prosi
 * most (window.SafeerLink.ukaz / poslusaj), odgovori pridejo v safeerLinkOdziv in od tam
 * v SafeerDaljinec.odziv / SafeerDaljinec.govor.
 *
 * Glas se razume tukaj, brez oblaka: kratka slovnica v jeziku uporabnika (glasnost, tipke,
 * aplikacije po imenu, strani, iskanje). Kar ne razumemo, gre kot iskanje na napravo -
 * uporabnik vedno vidi, kaj smo slisali in kaj smo naredili.
 *
 * Ista datoteka je v brskalniku za telefon, televizor in Linux.
 */
(function () {
  "use strict";

  var most = window.SafeerLink || null;
  var el = function (id) { return document.getElementById(id); };
  var api = function () { return window.SafeerLinkStran || {}; };

  // ----------------------------------------------------------------
  // Besedila (6 jezikov, kot Safeer Link)
  // ----------------------------------------------------------------

  var BESEDILA = {
    sl: {
      upravljam: "Upravljam", nazajNaLink: "Nazaj na Safeer Link", pokaziZaslon: "Pokaži zaslon naprave",
      samodejno: "Samodejno", govori: "Govori", poslji: "Pošlji",
      govoriNamig: "Pritisni mikrofon in povej, npr. »odpri YouTube« ali »glasneje«",
      pisiNamig: "Vpiši ukaz, npr. »odpri YouTube«, »glasneje« ali »program 25«",
      vnosNamig: "Ukaz, stran ali iskanje …",
      domov: "Domov", nazaj: "Nazaj", predvajaj: "Predvajaj", meni: "Meni",
      stranGor: "Stran gor", stranDol: "Stran dol", prejsnji: "Prejšnji", naslednji: "Naslednji",
      aplikacije: "Aplikacije na napravi", aplikacijeNa: "Aplikacije na napravi »{ime}«", sredisce: "Središče Safeer Linka: {ime}", osvezi: "Osveži", vec: "Več",
      znovaZazeni: "Znova zaženi Safeer", pocistiPredpomnilnik: "Počisti predpomnilnik", stanjeNaprave: "Stanje naprave",
      poslusam: "Poslušam …", obdelujem: "Razumem …", nicSlisano: "Nič nisem slišal. Poskusi znova.",
      dovoljenje: "Dovoli mikrofon, nato pritisni znova.", niGovora: "Glasovno upravljanje na tej napravi ni na voljo.",
      napakaGovora: "Prepoznava ni uspela. Poskusi znova.",
      brezOdgovora: "Naprava se ni odzvala. Je Safeer na njej odprt?",
      niPovezave: "Ni povezave s Safeer Linkom.",
      pretociNaRacunalnik: "Odpri na tem računalniku", pretakam: "Na napravi potrdi »Deli zaslon«, nato se {ime} odpre tukaj.",
      poslano: "Poslano", tipka: "Tipka {ime}", odpiram: "Odpiram {ime}", iscem: "Iščem »{kaj}«",
      iscemYoutube: "YouTube: »{kaj}«", odpiramStran: "Odpiram stran", glasnostNa: "Glasnost {n} %",
      glasneje: "Glasneje", tisje: "Tišje", utisano: "Utišano", zvokNazaj: "Zvok je nazaj",
      nisemRazumel: "Nisem razumel: »{kaj}« — iščem to na napravi.",
      aplikacijaNiNamescena: "Aplikacije »{ime}« ni na napravi.",
      nalagamAplikacije: "Nalagam aplikacije …", brezAplikacij: "Naprava ni vrnila seznama aplikacij.",
      posnetekOsvezen: "Zaslon ob {cas}", posnetekNiUspel: "Posnetka ni bilo mogoče narediti.",
      odprtaStran: "Odprto: {naslov}", naprava: "naprava", niVOspredju: "Safeer na napravi ni odprt — odpri stran ali pritisni Domov.",
      niNaRacunalniku: "Te tipke na računalniku ni — uporabi miško ali tipkovnico.",
      neMoreVOspredje: "Safeer se na napravi ne more odpreti sam: na njej odpri Safeer Link in pritisni »Dovoli«.",
      kanal: "Program {n}", predvajanje: "Predvajanje", pavza: "Pavza"
    },
    en: {
      upravljam: "Controlling", nazajNaLink: "Back to Safeer Link", pokaziZaslon: "Show device screen",
      samodejno: "Auto", govori: "Speak", poslji: "Send",
      govoriNamig: "Tap the microphone and say e.g. “open YouTube” or “louder”",
      pisiNamig: "Type a command, e.g. “open YouTube”, “louder” or “channel 25”",
      vnosNamig: "Command, page or search …",
      domov: "Home", nazaj: "Back", predvajaj: "Play", meni: "Menu",
      stranGor: "Page up", stranDol: "Page down", prejsnji: "Previous", naslednji: "Next",
      aplikacije: "Apps on the device", aplikacijeNa: "Apps on “{ime}”", sredisce: "Safeer Link hub: {ime}", osvezi: "Refresh", vec: "More",
      znovaZazeni: "Restart Safeer", pocistiPredpomnilnik: "Clear cache", stanjeNaprave: "Device status",
      poslusam: "Listening …", obdelujem: "Got it …", nicSlisano: "I didn't hear anything. Try again.",
      dovoljenje: "Allow the microphone, then tap again.", niGovora: "Voice control is not available on this device.",
      napakaGovora: "Recognition failed. Try again.",
      brezOdgovora: "The device did not respond. Is Safeer open on it?",
      niPovezave: "Not connected to Safeer Link.",
      pretociNaRacunalnik: "Open on this computer", pretakam: "Confirm “Share screen” on the device, then {ime} opens here.",
      poslano: "Sent", tipka: "Key {ime}", odpiram: "Opening {ime}", iscem: "Searching “{kaj}”",
      iscemYoutube: "YouTube: “{kaj}”", odpiramStran: "Opening page", glasnostNa: "Volume {n} %",
      glasneje: "Louder", tisje: "Quieter", utisano: "Muted", zvokNazaj: "Sound is back",
      nisemRazumel: "Didn't understand “{kaj}” — searching for it on the device.",
      aplikacijaNiNamescena: "The app “{ime}” is not on the device.",
      nalagamAplikacije: "Loading apps …", brezAplikacij: "The device returned no app list.",
      posnetekOsvezen: "Screen at {cas}", posnetekNiUspel: "Could not take a screenshot.",
      odprtaStran: "Open: {naslov}", naprava: "device", niVOspredju: "Safeer is not open on the device — open a page or press Home.",
      niNaRacunalniku: "That key does not exist on a computer — use the mouse or keyboard.",
      neMoreVOspredje: "Safeer cannot open by itself on the device: open Safeer Link there and press “Allow”.",
      kanal: "Channel {n}", predvajanje: "Playing", pavza: "Pause"
    },
    de: {
      upravljam: "Steuere", nazajNaLink: "Zurück zu Safeer Link", pokaziZaslon: "Gerätebildschirm zeigen",
      samodejno: "Automatisch", govori: "Sprechen", poslji: "Senden",
      govoriNamig: "Tippe auf das Mikrofon und sage z. B. „öffne YouTube“ oder „lauter“",
      pisiNamig: "Gib einen Befehl ein, z. B. „öffne YouTube“, „lauter“ oder „Programm 25“",
      vnosNamig: "Befehl, Seite oder Suche …",
      domov: "Start", nazaj: "Zurück", predvajaj: "Wiedergabe", meni: "Menü",
      stranGor: "Seite hoch", stranDol: "Seite runter", prejsnji: "Zurück", naslednji: "Weiter",
      aplikacije: "Apps auf dem Gerät", aplikacijeNa: "Apps auf „{ime}“", sredisce: "Safeer-Link-Zentrale: {ime}", osvezi: "Aktualisieren", vec: "Mehr",
      znovaZazeni: "Safeer neu starten", pocistiPredpomnilnik: "Cache leeren", stanjeNaprave: "Gerätestatus",
      poslusam: "Ich höre …", obdelujem: "Verstanden …", nicSlisano: "Ich habe nichts gehört. Versuch es noch einmal.",
      dovoljenje: "Mikrofon erlauben, dann erneut tippen.", niGovora: "Sprachsteuerung ist auf diesem Gerät nicht verfügbar.",
      napakaGovora: "Erkennung fehlgeschlagen. Versuch es noch einmal.",
      brezOdgovora: "Das Gerät hat nicht geantwortet. Ist Safeer dort geöffnet?",
      niPovezave: "Nicht mit Safeer Link verbunden.",
      pretociNaRacunalnik: "Auf diesem Computer öffnen", pretakam: "Bestätige „Bildschirm teilen“ auf dem Gerät, dann öffnet sich {ime} hier.",
      poslano: "Gesendet", tipka: "Taste {ime}", odpiram: "Öffne {ime}", iscem: "Suche „{kaj}“",
      iscemYoutube: "YouTube: „{kaj}“", odpiramStran: "Öffne Seite", glasnostNa: "Lautstärke {n} %",
      glasneje: "Lauter", tisje: "Leiser", utisano: "Stumm", zvokNazaj: "Ton ist wieder da",
      nisemRazumel: "„{kaj}“ nicht verstanden — suche danach auf dem Gerät.",
      aplikacijaNiNamescena: "Die App „{ime}“ ist nicht auf dem Gerät.",
      nalagamAplikacije: "Lade Apps …", brezAplikacij: "Das Gerät hat keine App-Liste geliefert.",
      posnetekOsvezen: "Bildschirm um {cas}", posnetekNiUspel: "Screenshot nicht möglich.",
      odprtaStran: "Offen: {naslov}", naprava: "Gerät", niVOspredju: "Safeer ist auf dem Gerät nicht geöffnet — Seite öffnen oder Start drücken.",
      niNaRacunalniku: "Diese Taste gibt es am Computer nicht — Maus oder Tastatur benutzen.",
      neMoreVOspredje: "Safeer kann sich auf dem Gerät nicht selbst öffnen: dort Safeer Link öffnen und „Erlauben“ drücken.",
      kanal: "Programm {n}", predvajanje: "Wiedergabe", pavza: "Pause"
    },
    es: {
      upravljam: "Controlando", nazajNaLink: "Volver a Safeer Link", pokaziZaslon: "Mostrar pantalla del dispositivo",
      samodejno: "Automático", govori: "Hablar", poslji: "Enviar",
      govoriNamig: "Toca el micrófono y di, p. ej., «abre YouTube» o «más alto»",
      pisiNamig: "Escribe una orden, p. ej. «abre YouTube», «más alto» o «canal 25»",
      vnosNamig: "Comando, página o búsqueda …",
      domov: "Inicio", nazaj: "Atrás", predvajaj: "Reproducir", meni: "Menú",
      stranGor: "Página arriba", stranDol: "Página abajo", prejsnji: "Anterior", naslednji: "Siguiente",
      aplikacije: "Apps en el dispositivo", aplikacijeNa: "Apps en «{ime}»", sredisce: "Centro de Safeer Link: {ime}", osvezi: "Actualizar", vec: "Más",
      znovaZazeni: "Reiniciar Safeer", pocistiPredpomnilnik: "Borrar caché", stanjeNaprave: "Estado del dispositivo",
      poslusam: "Escuchando …", obdelujem: "Entendido …", nicSlisano: "No he oído nada. Inténtalo de nuevo.",
      dovoljenje: "Permite el micrófono y vuelve a tocar.", niGovora: "El control por voz no está disponible en este dispositivo.",
      napakaGovora: "El reconocimiento falló. Inténtalo de nuevo.",
      brezOdgovora: "El dispositivo no respondió. ¿Está Safeer abierto en él?",
      niPovezave: "Sin conexión con Safeer Link.",
      pretociNaRacunalnik: "Abrir en este ordenador", pretakam: "Confirma «Compartir pantalla» en el dispositivo y {ime} se abrirá aquí.",
      poslano: "Enviado", tipka: "Tecla {ime}", odpiram: "Abriendo {ime}", iscem: "Buscando «{kaj}»",
      iscemYoutube: "YouTube: «{kaj}»", odpiramStran: "Abriendo página", glasnostNa: "Volumen {n} %",
      glasneje: "Más alto", tisje: "Más bajo", utisano: "Silenciado", zvokNazaj: "Sonido activado",
      nisemRazumel: "No entendí «{kaj}»: lo busco en el dispositivo.",
      aplikacijaNiNamescena: "La app «{ime}» no está en el dispositivo.",
      nalagamAplikacije: "Cargando apps …", brezAplikacij: "El dispositivo no devolvió la lista de apps.",
      posnetekOsvezen: "Pantalla a las {cas}", posnetekNiUspel: "No se pudo capturar la pantalla.",
      odprtaStran: "Abierto: {naslov}", naprava: "dispositivo", niVOspredju: "Safeer no está abierto en el dispositivo: abre una página o pulsa Inicio.",
      niNaRacunalniku: "Esa tecla no existe en un ordenador: usa el ratón o el teclado.",
      neMoreVOspredje: "Safeer no puede abrirse solo en el dispositivo: abre allí Safeer Link y pulsa «Permitir».",
      kanal: "Canal {n}", predvajanje: "Reproduciendo", pavza: "Pausa"
    },
    fr: {
      upravljam: "Je contrôle", nazajNaLink: "Retour à Safeer Link", pokaziZaslon: "Afficher l'écran de l'appareil",
      samodejno: "Auto", govori: "Parler", poslji: "Envoyer",
      govoriNamig: "Touchez le micro et dites p. ex. « ouvre YouTube » ou « plus fort »",
      pisiNamig: "Tapez une commande, p. ex. « ouvre YouTube », « plus fort » ou « chaîne 25 »",
      vnosNamig: "Commande, page ou recherche …",
      domov: "Accueil", nazaj: "Retour", predvajaj: "Lecture", meni: "Menu",
      stranGor: "Page haut", stranDol: "Page bas", prejsnji: "Précédent", naslednji: "Suivant",
      aplikacije: "Applis sur l'appareil", aplikacijeNa: "Applis sur « {ime} »", sredisce: "Centre Safeer Link : {ime}", osvezi: "Actualiser", vec: "Plus",
      znovaZazeni: "Redémarrer Safeer", pocistiPredpomnilnik: "Vider le cache", stanjeNaprave: "État de l'appareil",
      poslusam: "J'écoute …", obdelujem: "Compris …", nicSlisano: "Je n'ai rien entendu. Réessayez.",
      dovoljenje: "Autorisez le micro, puis touchez à nouveau.", niGovora: "La commande vocale n'est pas disponible sur cet appareil.",
      napakaGovora: "La reconnaissance a échoué. Réessayez.",
      brezOdgovora: "L'appareil n'a pas répondu. Safeer y est-il ouvert ?",
      niPovezave: "Pas de connexion à Safeer Link.",
      pretociNaRacunalnik: "Ouvrir sur cet ordinateur", pretakam: "Confirmez « Partager l'écran » sur l'appareil, puis {ime} s'ouvrira ici.",
      poslano: "Envoyé", tipka: "Touche {ime}", odpiram: "J'ouvre {ime}", iscem: "Recherche « {kaj} »",
      iscemYoutube: "YouTube : « {kaj} »", odpiramStran: "J'ouvre la page", glasnostNa: "Volume {n} %",
      glasneje: "Plus fort", tisje: "Moins fort", utisano: "Muet", zvokNazaj: "Le son est revenu",
      nisemRazumel: "Je n'ai pas compris « {kaj} » — je le cherche sur l'appareil.",
      aplikacijaNiNamescena: "L'appli « {ime} » n'est pas sur l'appareil.",
      nalagamAplikacije: "Chargement des applis …", brezAplikacij: "L'appareil n'a pas renvoyé de liste d'applis.",
      posnetekOsvezen: "Écran à {cas}", posnetekNiUspel: "Capture d'écran impossible.",
      odprtaStran: "Ouvert : {naslov}", naprava: "appareil", niVOspredju: "Safeer n'est pas ouvert sur l'appareil — ouvrez une page ou appuyez sur Accueil.",
      niNaRacunalniku: "Cette touche n'existe pas sur un ordinateur — utilisez la souris ou le clavier.",
      neMoreVOspredje: "Safeer ne peut pas s'ouvrir tout seul sur l'appareil : ouvrez-y Safeer Link et appuyez sur « Autoriser ».",
      kanal: "Chaîne {n}", predvajanje: "Lecture", pavza: "Pause"
    },
    it: {
      upravljam: "Controllo", nazajNaLink: "Torna a Safeer Link", pokaziZaslon: "Mostra lo schermo del dispositivo",
      samodejno: "Automatico", govori: "Parla", poslji: "Invia",
      govoriNamig: "Tocca il microfono e di' ad es. «apri YouTube» o «più forte»",
      pisiNamig: "Scrivi un comando, ad es. «apri YouTube», «più forte» o «canale 25»",
      vnosNamig: "Comando, pagina o ricerca …",
      domov: "Home", nazaj: "Indietro", predvajaj: "Riproduci", meni: "Menu",
      stranGor: "Pagina su", stranDol: "Pagina giù", prejsnji: "Precedente", naslednji: "Successivo",
      aplikacije: "App sul dispositivo", aplikacijeNa: "App su «{ime}»", sredisce: "Centro Safeer Link: {ime}", osvezi: "Aggiorna", vec: "Altro",
      znovaZazeni: "Riavvia Safeer", pocistiPredpomnilnik: "Svuota la cache", stanjeNaprave: "Stato del dispositivo",
      poslusam: "In ascolto …", obdelujem: "Capito …", nicSlisano: "Non ho sentito nulla. Riprova.",
      dovoljenje: "Consenti il microfono, poi tocca di nuovo.", niGovora: "Il controllo vocale non è disponibile su questo dispositivo.",
      napakaGovora: "Riconoscimento non riuscito. Riprova.",
      brezOdgovora: "Il dispositivo non ha risposto. Safeer è aperto lì?",
      niPovezave: "Nessuna connessione a Safeer Link.",
      pretociNaRacunalnik: "Apri su questo computer", pretakam: "Conferma «Condividi schermo» sul dispositivo, poi {ime} si aprirà qui.",
      poslano: "Inviato", tipka: "Tasto {ime}", odpiram: "Apro {ime}", iscem: "Cerco «{kaj}»",
      iscemYoutube: "YouTube: «{kaj}»", odpiramStran: "Apro la pagina", glasnostNa: "Volume {n} %",
      glasneje: "Più forte", tisje: "Più piano", utisano: "Silenziato", zvokNazaj: "Audio riattivato",
      nisemRazumel: "Non ho capito «{kaj}»: lo cerco sul dispositivo.",
      aplikacijaNiNamescena: "L'app «{ime}» non è sul dispositivo.",
      nalagamAplikacije: "Carico le app …", brezAplikacij: "Il dispositivo non ha restituito l'elenco delle app.",
      posnetekOsvezen: "Schermo alle {cas}", posnetekNiUspel: "Impossibile catturare lo schermo.",
      odprtaStran: "Aperto: {naslov}", naprava: "dispositivo", niVOspredju: "Safeer non è aperto sul dispositivo: apri una pagina o premi Home.",
      niNaRacunalniku: "Quel tasto non esiste su un computer: usa il mouse o la tastiera.",
      neMoreVOspredje: "Safeer non può aprirsi da solo sul dispositivo: apri lì Safeer Link e premi «Consenti».",
      kanal: "Canale {n}", predvajanje: "In riproduzione", pavza: "Pausa"
    }
  };

  var jezik = (function () {
    var oznaka = "";
    try { if (api().jezik) oznaka = String(api().jezik || ""); } catch (e) {}
    try { if (!oznaka && most && most.jezik) oznaka = String(most.jezik() || ""); } catch (e) {}
    if (!oznaka) oznaka = (navigator.language || "en");
    oznaka = oznaka.toLowerCase().slice(0, 2);
    return BESEDILA[oznaka] ? oznaka : "en";
  })();

  function t(kljuc, nadomestki) {
    var niz = BESEDILA[jezik][kljuc];
    if (niz === undefined) niz = BESEDILA.en[kljuc];
    if (niz === undefined) niz = BESEDILA.sl[kljuc] || "";
    if (nadomestki) {
      for (var k in nadomestki) {
        if (Object.prototype.hasOwnProperty.call(nadomestki, k)) niz = niz.split("{" + k + "}").join(String(nadomestki[k]));
      }
    }
    return niz;
  }

  function prevedi() {
    var vsi = document.querySelectorAll("#zaslonDaljinec [data-d]");
    for (var i = 0; i < vsi.length; i++) {
      var niz = t(vsi[i].getAttribute("data-d"));
      if (niz) vsi[i].textContent = niz;
    }
    var naslovi = document.querySelectorAll("#zaslonDaljinec [data-d-naslov]");
    for (var j = 0; j < naslovi.length; j++) {
      var n = t(naslovi[j].getAttribute("data-d-naslov"));
      if (n) { naslovi[j].setAttribute("aria-label", n); naslovi[j].setAttribute("title", n); }
    }
    var polja = document.querySelectorAll("#zaslonDaljinec [data-d-placeholder]");
    for (var p = 0; p < polja.length; p++) {
      var ph = t(polja[p].getAttribute("data-d-placeholder"));
      if (ph) polja[p].setAttribute("placeholder", ph);
    }
  }

  // ----------------------------------------------------------------
  // Stanje
  // ----------------------------------------------------------------

  var stanje = {
    naprava: null,          // {id, ime, zmoznosti}
    odprt: false,
    cakajoci: {},           // ref -> {cb, dejanje, timer}
    aplikacije: [],         // [{package, label, icon}]
    aplikacijeZa: "",       // id naprave, za katero velja seznam
    glasnost: null,
    utisano: false,
    samodejno: false,
    posnetekTimer: null,
    poslusam: false,
    zadnjeSliseno: ""
  };
  var stevec = 0;

  function pokazi(id, vidno) { var e = el(id); if (e) e.hidden = !vidno; }
  function besedilo(id, niz) { var e = el(id); if (e) e.textContent = niz == null ? "" : String(niz); }

  function znaGovor() {
    try { return !!(most && most.znaGovor && most.znaGovor()); } catch (e) { return false; }
  }

  // ----------------------------------------------------------------
  // Posiljanje ukazov
  // ----------------------------------------------------------------

  function ukaz(dejanje, parametri, cb, casDoOdgovora) {
    var n = stanje.naprava;
    if (!n || !most || !most.ukaz) {
      if (cb) cb({ ok: false, message: t("niPovezave") });
      return null;
    }
    var ref = "d" + Date.now().toString(36) + "-" + (++stevec);
    var vnos = { cb: cb || null, dejanje: dejanje, timer: null };
    vnos.timer = setTimeout(function () {
      if (stanje.cakajoci[ref]) {
        delete stanje.cakajoci[ref];
        if (cb) cb({ ok: false, message: t("brezOdgovora"), casovna: true });
      }
    }, casDoOdgovora || 8000);
    stanje.cakajoci[ref] = vnos;
    try {
      most.ukaz(n.id, dejanje, JSON.stringify(parametri || {}), ref);
    } catch (e) {
      clearTimeout(vnos.timer);
      delete stanje.cakajoci[ref];
      if (cb) cb({ ok: false, message: t("niPovezave") });
    }
    return ref;
  }

  /** Odgovor naprave (control.result) ali zavrnitev sredisca (control.ack). */
  function odziv(podatki) {
    if (!podatki) return;
    var ref = String(podatki.ref || "");
    var vnos = stanje.cakajoci[ref];
    if (!vnos) return;
    clearTimeout(vnos.timer);
    delete stanje.cakajoci[ref];
    if (vnos.cb) vnos.cb(podatki);
  }

  /** Stabilne oznake napak z naprave v jezik uporabnika; besedilo naprave je le rezerva. */
  function prevodKode(koda, rezerva) {
    var prevodi = {
      ni_v_ospredju: t("niVOspredju"), neznano_dejanje: t("brezOdgovora"),
      ni_namescena: t("aplikacijaNiNamescena", { ime: rezerva.replace(/^Aplikacija\s+/, "").replace(/\s+ni namescena$/, "") }),
      ni_na_racunalniku: t("niNaRacunalniku"), naprava_ni_povezana: t("niPovezave")
    };
    return prevodi[koda] || rezerva;
  }

  // Kratek utrip na tipki, da uporabnik vidi, da je dotik prijel, tudi ce naprava odgovori pozneje.
  function utrip(gumb) {
    if (!gumb) return;
    gumb.classList.add("utrip");
    setTimeout(function () { gumb.classList.remove("utrip"); }, 180);
  }

  function pokaziOdgovor(izid, uspehBesedilo) {
    var o = el("daljinecOdgovor");
    if (!o) return;
    var ok = !!(izid && izid.ok);
    var niz = ok ? (uspehBesedilo || (izid && izid.message) || t("poslano")) : ((izid && izid.message) || t("brezOdgovora"));
    if (!ok && izid && izid.koda) niz = prevodKode(izid.koda, niz);
    o.textContent = niz;
    o.classList.toggle("napaka", !ok);
    var s = el("daljinecStanje");
    if (s && !ok) { s.textContent = niz; s.classList.add("napaka"); }
    else if (s && ok && s.classList.contains("napaka")) { s.classList.remove("napaka"); osveziStanje(); }
    if (ok && stanje.samodejno) nacrtujPosnetek(900);
  }

  // ----------------------------------------------------------------
  // Tipke, glasnost, drsenje
  // ----------------------------------------------------------------

  function tipka(ime, gumb) {
    utrip(gumb);
    ukaz("key", { key: ime }, function (izid) { pokaziOdgovor(izid, t("tipka", { ime: imeTipke(ime) })); });
  }

  function imeTipke(ime) {
    var imena = { home: t("domov"), back: t("nazaj"), play_pause: t("predvajaj"), menu: t("meni"),
      previous: t("prejsnji"), next: t("naslednji"), up: "↑", down: "↓", left: "←", right: "→", ok: "OK" };
    return imena[ime] || ime;
  }

  function drsenje(smer, gumb) {
    utrip(gumb);
    ukaz("scroll", { direction: smer }, function (izid) { pokaziOdgovor(izid, smer === "up" ? t("stranGor") : t("stranDol")); });
  }

  function glasnost(parametri, gumb) {
    utrip(gumb);
    ukaz("volume", parametri, function (izid) {
      if (izid && izid.ok && izid.data) narisiGlasnost(izid.data);
      var opis = parametri.direction === "up" ? t("glasneje") : parametri.direction === "down" ? t("tisje")
        : parametri.level != null ? t("glasnostNa", { n: parametri.level })
        : (izid && izid.data && izid.data.muted ? t("utisano") : t("zvokNazaj"));
      pokaziOdgovor(izid, opis);
    });
  }

  function narisiGlasnost(podatki) {
    if (!podatki) return;
    if (typeof podatki.level === "number") stanje.glasnost = podatki.level;
    stanje.utisano = !!podatki.muted;
    var raven = el("daljinecGlasnostRaven");
    if (raven) raven.style.height = (stanje.glasnost == null ? 0 : Math.max(0, Math.min(100, stanje.glasnost))) + "%";
    besedilo("daljinecGlasnostVrednost", stanje.glasnost == null ? "–" : (stanje.utisano ? "🔇" : stanje.glasnost + "%"));
    var u = document.querySelector("#daljinecGlasnost .utisaj");
    if (u) u.classList.toggle("utisano", stanje.utisano);
  }

  // ----------------------------------------------------------------
  // Aplikacije
  // ----------------------------------------------------------------

  function naloziAplikacije(prisilno) {
    var n = stanje.naprava;
    if (!n) return;
    if (!prisilno && stanje.aplikacijeZa === n.id && stanje.aplikacije.length) { narisiAplikacije(); return; }
    besedilo("daljinecAplikacijeOpomba", t("nalagamAplikacije"));
    ukaz("apps", { icons: true }, function (izid) {
      if (izid && izid.ok && izid.data && izid.data.apps) {
        stanje.aplikacije = izid.data.apps;
        stanje.aplikacijeZa = n.id;
        besedilo("daljinecAplikacijeOpomba", "");
        narisiAplikacije();
        try { window.localStorage.setItem("safeer_daljinec_apps_" + n.id, JSON.stringify(stanje.aplikacije.map(function (a) { return { package: a.package, label: a.label }; }))); } catch (e) {}
      } else {
        // Brez seznama (npr. racunalnik): plosco aplikacij skrijemo, ne kazemo napake.
        var podprto = !(izid && /ni na voljo|not available|unsupported|Neznano dejanje/i.test(izid.message || ""));
        stanje.aplikacije = [];
        narisiAplikacije();
        besedilo("daljinecAplikacijeOpomba", podprto ? ((izid && izid.message) || t("brezAplikacij")) : "");
        pokazi("daljinecAplikacijePanel", podprto);
      }
    }, 15000);
  }

  function narisiAplikacije() {
    var mreza = el("daljinecAplikacije");
    if (!mreza) return;
    mreza.innerHTML = "";
    pokazi("daljinecAplikacijePanel", true);
    stanje.aplikacije.forEach(function (a) {
      var gumb = document.createElement("button");
      gumb.className = "aplikacija";
      gumb.setAttribute("data-paket", a.package);
      gumb.setAttribute("title", a.label || a.package);
      if (a.icon) {
        var slika = document.createElement("img");
        slika.alt = "";
        slika.src = a.icon;
        gumb.appendChild(slika);
      } else {
        var znak = document.createElement("span");
        znak.className = "aplikacijaZnak";
        znak.textContent = (a.label || a.package || "?").trim().charAt(0).toUpperCase();
        gumb.appendChild(znak);
      }
      var ime = document.createElement("span");
      ime.textContent = a.label || a.package;
      gumb.appendChild(ime);
      gumb.addEventListener("click", function () { zazeniAplikacijo(a, gumb); });
      mreza.appendChild(gumb);
    });
  }

  function zazeniAplikacijo(a, gumb) {
    utrip(gumb);
    var ime = a.label || a.package;
    // Safeer Control: aplikacijo s tablice/telefona odpre tu - naprava deli zaslon sem (Protocol v1 apps.launch
    // s stream), miska in tipkovnica v oknu gledalca pa jo upravljata prek Safeer Vnosa.
    var pretoci = el("daljinecPretoci");
    if (pretoci && pretoci.checked && !el("daljinecPretociIzbira").hidden) {
      ukaz("apps.launch", { app: a.package, stream: true }, function (izid) { pokaziOdgovor(izid, t("pretakam", { ime: ime })); });
      return;
    }
    ukaz("launch_app", { package: a.package }, function (izid) { pokaziOdgovor(izid, t("odpiram", { ime: ime })); });
  }

  /** Aplikacija po (delu) imena: "youtube" najde YouTube, "brskalnik" Safeer. */
  function najdiAplikacijo(ime) {
    var iskano = normaliziraj(ime);
    if (!iskano) return null;
    var kandidati = stanje.aplikacije.slice();
    // Sopomenke, ki jih ljudje uporabljajo namesto pravega imena aplikacije (prva ima prednost).
    var sopomenke = {
      "youtube": ["youtube"],
      "jutub": ["youtube"], "yutub": ["youtube"], "yt": ["youtube"],
      "brskalnik": ["safeer", "browser", "chrome"], "browser": ["safeer", "browser"],
      "navegador": ["safeer", "browser"], "navigateur": ["safeer", "browser"],
      "filmi": ["netflix"], "filme": ["netflix"],
      "serije": ["netflix"], "movies": ["netflix"],
      "televizija": ["xplore", "live tv", "tv"], "televizijo": ["xplore", "live tv", "tv"], "tv v zivo": ["xplore", "live tv"],
      "fernsehen": ["xplore", "live tv", "tv"], "television": ["xplore", "live tv", "tv"], "televisione": ["xplore", "live tv", "tv"],
      "glasba": ["spotify", "youtube music"], "music": ["spotify", "youtube music"],
      "nastavitve": ["settings", "nastavitve"], "settings": ["settings"], "einstellungen": ["settings"]
    };
    // Sopomenke imajo prednost pred dobesednim imenom ("jutub" -> YouTube).
    // Kar nima sopomenk, se isce dobesedno.
    var iskanja = (sopomenke[iskano] || [iskano]).slice();
    if (iskanja.indexOf(iskano) < 0) iskanja.push(iskano);
    // Tocke: tocno ime > ime se zacne z iskanim > iskano je beseda v imenu > del imena (>= 4 znaki)
    // > del paketa (>= 5 znakov, po segmentih, da "yt" ne najde "playtv"). Zgodnejsa sopomenka
    // ima prednost pred poznejso pri enakih tockah.
    var najboljsa = null, najTocke = 0;
    for (var i = 0; i < iskanja.length; i++) {
      var q = normaliziraj(iskanja[i]);
      if (!q) continue;
      var qBrez = q.replace(/\s+/g, "");
      for (var j = 0; j < kandidati.length; j++) {
        var oznaka = normaliziraj(kandidati[j].label || "");
        var oznakaBrez = oznaka.replace(/\s+/g, "");
        var segmenti = String(kandidati[j].package || "").toLowerCase().split(".");
        var tocke = 0;
        if (oznaka === q || oznakaBrez === qBrez) tocke = 100;
        else if (oznaka.indexOf(q + " ") === 0 || oznakaBrez.indexOf(qBrez) === 0 && qBrez.length >= 3) tocke = 80;
        else if ((" " + oznaka + " ").indexOf(" " + q + " ") >= 0) tocke = 70;
        else if (q.length >= 4 && oznakaBrez.indexOf(qBrez) >= 0) tocke = 50;
        else if (qBrez.length >= 5 && segmenti.some(function (seg) { return seg === qBrez || seg.indexOf(qBrez) >= 0; })) tocke = 30;
        if (tocke > najTocke) { najTocke = tocke; najboljsa = kandidati[j]; }
      }
      if (najboljsa && najTocke >= 70) break;
    }
    return najboljsa;
  }

  function normaliziraj(niz) {
    return String(niz || "").toLowerCase()
      .replace(/[čć]/g, "c").replace(/š/g, "s").replace(/ž/g, "z").replace(/đ/g, "d")
      .replace(/[àáâä]/g, "a").replace(/[èéêë]/g, "e").replace(/[ìíîï]/g, "i").replace(/[òóôö]/g, "o").replace(/[ùúûü]/g, "u").replace(/ß/g, "ss").replace(/ñ/g, "n")
      .replace(/[^a-z0-9 .\-\/:_]+/g, " ").replace(/\s+/g, " ").trim();
  }

  // ----------------------------------------------------------------
  // Glas: slovnica ukazov (brez oblaka)
  // ----------------------------------------------------------------

  /** Besede po jezikih. Vsak vnos je seznam korenov; ujemanje je po zacetku besede. */
  var SLOVNICA = {
    sl: {
      glasneje: ["glasneje", "glasnejse", "povecaj glasnost", "zvisaj glasnost", "bolj naglas", "naglas", "glasnost gor"],
      tisje: ["tisje", "tise", "zmanjsaj glasnost", "znizaj glasnost", "stisaj", "manj naglas", "glasnost dol"],
      utisaj: ["utisaj", "brez zvoka", "tiho", "izklopi zvok", "ugasni zvok"],
      zvok: ["vklopi zvok", "odkleni zvok", "zvok nazaj", "prizgi zvok"],
      glasnostNa: ["glasnost na", "glasnost", "zvok na"],
      domov: ["domov", "domaca stran", "zacetna stran", "na zacetek"],
      nazaj: ["nazaj", "zapri"],
      meni: ["meni"],
      gor: ["gor", "navzgor"], dol: ["dol", "navzdol"], levo: ["levo"], desno: ["desno"], ok: ["potrdi", "ok", "v redu", "izberi", "klikni"],
      predvajaj: ["predvajaj", "nadaljuj", "play"], pavza: ["pavza", "ustavi", "stop", "pocakaj", "premor"],
      naslednji: ["naslednji", "naprej"], prejsnji: ["prejsnji", "prejsnja"],
      stranGor: ["stran gor", "drsi gor", "pomakni gor"], stranDol: ["stran dol", "drsi dol", "pomakni dol", "listaj"],
      odpri: ["odpri", "zazeni", "zagni", "pokazi", "vklopi", "prizgi"],
      program: ["program", "kanal", "preklopi na"],
      youtube: ["youtube", "jutub", "yutub"],
      predvajajGlasbo: ["predvajaj", "zavrti", "poslusaj", "poslusal bi", "pesem", "komad", "glasbo", "glasba"],
      poisci: ["poisci", "isci", "najdi", "google", "kdo je", "kaj je", "kje je", "vreme"],
      posnetek: ["posnetek", "kaj je na zaslonu", "pokazi zaslon", "zaslon"],
      znovaZazeni: ["znova zazeni", "ponovno zazeni", "restart"], pocisti: ["pocisti predpomnilnik", "pocisti", "sprosti pomnilnik"],
      stran: ["stran", "povezavo", "naslov"],
      mesalo: ["prosim", "na televizorju", "na tv", "na televiziji", "na napravi", "lahko", "mi", "daj"]
    },
    en: {
      glasneje: ["louder", "volume up", "turn it up", "increase volume", "raise volume"],
      tisje: ["quieter", "volume down", "turn it down", "decrease volume", "lower volume", "softer"],
      utisaj: ["mute", "silence", "no sound", "sound off"],
      zvok: ["unmute", "sound on", "sound back"],
      glasnostNa: ["volume to", "volume", "set volume"],
      domov: ["home", "home screen", "start page"],
      nazaj: ["back", "go back", "close"],
      meni: ["menu"],
      gor: ["up"], dol: ["down"], levo: ["left"], desno: ["right"], ok: ["ok", "select", "confirm", "enter", "click"],
      predvajaj: ["play", "resume", "continue"], pavza: ["pause", "stop", "hold"],
      naslednji: ["next", "skip"], prejsnji: ["previous", "back one"],
      stranGor: ["page up", "scroll up"], stranDol: ["page down", "scroll down", "scroll"],
      odpri: ["open", "launch", "start", "show", "run", "go to"],
      program: ["channel", "program", "switch to"],
      youtube: ["youtube"],
      predvajajGlasbo: ["play", "listen to", "put on", "song", "music"],
      poisci: ["search for", "search", "find", "google", "look up", "who is", "what is", "where is", "weather"],
      posnetek: ["screenshot", "show screen", "what is on the screen", "screen"],
      znovaZazeni: ["restart", "reboot safeer"], pocisti: ["clear cache", "clean cache", "free memory"],
      stran: ["page", "link", "website", "url"],
      mesalo: ["please", "on the tv", "on tv", "on the television", "on the device", "can you", "could you", "for me"]
    },
    de: {
      glasneje: ["lauter", "lautstarke hoch", "lautstarke erhohen"], tisje: ["leiser", "lautstarke runter", "lautstarke verringern"],
      utisaj: ["stumm", "ton aus", "kein ton"], zvok: ["ton an", "ton wieder", "laut schalten"],
      glasnostNa: ["lautstarke auf", "lautstarke"],
      domov: ["start", "startseite", "home", "zuhause"], nazaj: ["zuruck", "schliessen"], meni: ["menu"],
      gor: ["hoch", "nach oben", "oben"], dol: ["runter", "nach unten", "unten"], levo: ["links"], desno: ["rechts"], ok: ["ok", "auswahlen", "bestatigen", "klicken"],
      predvajaj: ["abspielen", "weiter", "wiedergabe", "play"], pavza: ["pause", "stopp", "stop", "anhalten"],
      naslednji: ["nachster", "nachste", "weiter"], prejsnji: ["vorheriger", "vorherige", "zuruck"],
      stranGor: ["seite hoch", "nach oben scrollen"], stranDol: ["seite runter", "nach unten scrollen", "scrollen"],
      odpri: ["offne", "offnen", "starte", "starten", "zeige", "zeig", "mach", "geh zu"],
      program: ["programm", "kanal", "sender", "schalte auf", "umschalten auf"],
      youtube: ["youtube"], predvajajGlasbo: ["spiel", "spiele", "abspielen", "lied", "musik", "hore"],
      poisci: ["suche nach", "suche", "such", "finde", "google", "wer ist", "was ist", "wo ist", "wetter"],
      posnetek: ["screenshot", "bildschirm zeigen", "bildschirm"],
      znovaZazeni: ["neu starten", "neustart"], pocisti: ["cache leeren", "speicher freigeben"],
      stran: ["seite", "link", "webseite"], mesalo: ["bitte", "auf dem fernseher", "im fernseher", "am fernseher", "kannst du", "mir"]
    },
    es: {
      glasneje: ["mas alto", "sube el volumen", "subir volumen", "mas volumen"], tisje: ["mas bajo", "baja el volumen", "bajar volumen", "menos volumen"],
      utisaj: ["silencio", "silenciar", "sin sonido", "mute"], zvok: ["activar sonido", "sonido", "quitar silencio"],
      glasnostNa: ["volumen a", "volumen al", "volumen"],
      domov: ["inicio", "pantalla de inicio", "casa"], nazaj: ["atras", "volver", "cerrar"], meni: ["menu"],
      gor: ["arriba"], dol: ["abajo"], levo: ["izquierda"], desno: ["derecha"], ok: ["ok", "seleccionar", "confirmar", "aceptar", "clic"],
      predvajaj: ["reproducir", "reproduce", "continuar", "play"], pavza: ["pausa", "pausar", "parar", "detener", "stop"],
      naslednji: ["siguiente"], prejsnji: ["anterior"],
      stranGor: ["pagina arriba", "subir"], stranDol: ["pagina abajo", "bajar", "desplazar"],
      odpri: ["abre", "abrir", "inicia", "iniciar", "lanza", "muestra", "ve a"],
      program: ["canal", "programa", "cambia a", "pon el"],
      youtube: ["youtube"], predvajajGlasbo: ["pon", "reproduce", "escuchar", "cancion", "musica"],
      poisci: ["busca", "buscar", "encuentra", "google", "quien es", "que es", "donde esta", "tiempo"],
      posnetek: ["captura", "muestra la pantalla", "pantalla"],
      znovaZazeni: ["reiniciar", "reinicia"], pocisti: ["borrar cache", "limpiar cache", "liberar memoria"],
      stran: ["pagina", "enlace", "web"], mesalo: ["por favor", "en la tele", "en la television", "en el televisor", "puedes", "me"]
    },
    fr: {
      glasneje: ["plus fort", "monte le son", "augmente le volume", "monter le volume"], tisje: ["moins fort", "baisse le son", "baisser le volume", "diminue le volume"],
      utisaj: ["muet", "coupe le son", "sans son", "silence"], zvok: ["remets le son", "son", "active le son"],
      glasnostNa: ["volume a", "volume"],
      domov: ["accueil", "page d accueil", "maison"], nazaj: ["retour", "reviens", "ferme"], meni: ["menu"],
      gor: ["haut", "en haut"], dol: ["bas", "en bas"], levo: ["gauche"], desno: ["droite"], ok: ["ok", "valide", "confirme", "selectionne", "clique"],
      predvajaj: ["lecture", "lire", "joue", "continue", "play"], pavza: ["pause", "arrete", "stop"],
      naslednji: ["suivant", "suivante"], prejsnji: ["precedent", "precedente"],
      stranGor: ["page haut", "defiler vers le haut", "monte"], stranDol: ["page bas", "defiler vers le bas", "descends", "defile"],
      odpri: ["ouvre", "ouvrir", "lance", "lancer", "demarre", "montre", "va sur", "va a"],
      program: ["chaine", "programme", "passe sur", "mets la"],
      youtube: ["youtube"], predvajajGlasbo: ["joue", "mets", "ecouter", "ecoute", "chanson", "musique"],
      poisci: ["cherche", "recherche", "trouve", "google", "qui est", "qu est ce que", "ou est", "meteo"],
      posnetek: ["capture", "montre l ecran", "ecran"],
      znovaZazeni: ["redemarre", "redemarrer"], pocisti: ["vide le cache", "vider le cache", "libere la memoire"],
      stran: ["page", "lien", "site"], mesalo: ["s il te plait", "s il vous plait", "sur la tele", "sur la television", "peux tu", "moi"]
    },
    it: {
      glasneje: ["piu forte", "alza il volume", "aumenta il volume", "piu alto"], tisje: ["piu piano", "abbassa il volume", "diminuisci il volume", "piu basso"],
      utisaj: ["muto", "silenzio", "togli l audio", "senza audio"], zvok: ["riattiva l audio", "audio", "rimetti l audio"],
      glasnostNa: ["volume a", "volume al", "volume"],
      domov: ["home", "pagina iniziale", "inizio", "casa"], nazaj: ["indietro", "torna", "chiudi"], meni: ["menu"],
      gor: ["su", "sopra"], dol: ["giu", "sotto"], levo: ["sinistra"], desno: ["destra"], ok: ["ok", "conferma", "seleziona", "clicca", "invio"],
      predvajaj: ["riproduci", "continua", "play"], pavza: ["pausa", "ferma", "stop"],
      naslednji: ["successivo", "prossimo", "avanti"], prejsnji: ["precedente"],
      stranGor: ["pagina su", "scorri su"], stranDol: ["pagina giu", "scorri giu", "scorri"],
      odpri: ["apri", "aprire", "avvia", "lancia", "mostra", "vai su", "vai a"],
      program: ["canale", "programma", "metti il", "passa a"],
      youtube: ["youtube"], predvajajGlasbo: ["metti", "riproduci", "ascolta", "ascoltare", "canzone", "musica"],
      poisci: ["cerca", "trova", "google", "chi e", "cos e", "dov e", "meteo"],
      posnetek: ["screenshot", "mostra lo schermo", "schermo"],
      znovaZazeni: ["riavvia", "riavviare"], pocisti: ["svuota la cache", "pulisci la cache", "libera la memoria"],
      stran: ["pagina", "link", "sito"], mesalo: ["per favore", "sulla tv", "sul televisore", "in tv", "puoi", "mi"]
    }
  };

  function slovnica() { return SLOVNICA[jezik] || SLOVNICA.en; }

  function odrezi(niz, predpone) {
    // Vrne ostanek za prvo predpono, ki se ujema na zacetku (najdaljsa najprej), ali null.
    var urejene = predpone.slice().sort(function (a, b) { return b.length - a.length; });
    for (var i = 0; i < urejene.length; i++) {
      var p = urejene[i];
      if (niz === p) return "";
      if (niz.indexOf(p + " ") === 0) return niz.slice(p.length + 1).trim();
    }
    return null;
  }

  function vsebuje(niz, besede) {
    for (var i = 0; i < besede.length; i++) {
      var b = besede[i];
      if (niz === b || niz.indexOf(b + " ") === 0 || niz.indexOf(" " + b + " ") >= 0 || niz.slice(-(b.length + 1)) === " " + b) return true;
    }
    return false;
  }

  function ocisti(niz) {
    // Locila na koncu besed (nekateri prepoznavalniki jih dodajo) stran; pika v naslovu ostane.
    var s = normaliziraj(String(niz || "").replace(/[.,!?;:]+(\s|$)/g, "$1"));
    var g = slovnica();
    (g.mesalo || []).forEach(function (m) {
      s = (" " + s + " ").split(" " + m + " ").join(" ").trim();
    });
    return s.replace(/\s+/g, " ").trim();
  }

  /**
   * Besedilo v ukaz: {dejanje, parametri, opis} ali null.
   * Vrstni red je pomemben: najprej glasnost in tipke (kratke, nedvoumne), potem programi,
   * aplikacije po imenu, YouTube, strani, iskanje. Kar ostane, je iskanje.
   */
  function razumi(besedilo) {
    var surovo = String(besedilo || "").trim();
    var s = ocisti(surovo);
    if (!s) return null;
    var g = slovnica();
    var st = s.match(/\b(\d{1,3})\b/);
    var stevilka = st ? parseInt(st[1], 10) : null;

    // Glasnost
    if (vsebuje(s, g.utisaj)) return { dejanje: "volume", parametri: { direction: "mute" }, opis: t("utisano") };
    if (vsebuje(s, g.zvok)) return { dejanje: "volume", parametri: { direction: "unmute" }, opis: t("zvokNazaj") };
    if (vsebuje(s, g.glasneje)) return { dejanje: "volume", parametri: { direction: "up" }, opis: t("glasneje") };
    if (vsebuje(s, g.tisje)) return { dejanje: "volume", parametri: { direction: "down" }, opis: t("tisje") };
    if (vsebuje(s, g.glasnostNa) && stevilka != null && stevilka <= 100) {
      return { dejanje: "volume", parametri: { level: stevilka }, opis: t("glasnostNa", { n: stevilka }) };
    }

    // Posnetek, vzdrzevanje
    if (vsebuje(s, g.posnetek)) return { dejanje: "screenshot", parametri: {}, opis: t("pokaziZaslon") };
    if (vsebuje(s, g.znovaZazeni)) return { dejanje: "restart", parametri: {}, opis: t("znovaZazeni") };
    if (vsebuje(s, g.pocisti)) return { dejanje: "clear_cache", parametri: {}, opis: t("pocistiPredpomnilnik") };

    // Tipke (samo kratki ukazi: "nazaj", "domov", "gor" ...)
    var tipke = [["domov", "home"], ["nazaj", "back"], ["meni", "menu"], ["gor", "up"], ["dol", "down"], ["levo", "left"], ["desno", "right"],
      ["ok", "ok"], ["pavza", "pause"], ["naslednji", "next"], ["prejsnji", "previous"]];
    for (var i = 0; i < tipke.length; i++) {
      var besede = g[tipke[i][0]] || [];
      if (besede.indexOf(s) >= 0) return { dejanje: "key", parametri: { key: tipke[i][1] }, opis: t("tipka", { ime: imeTipke(tipke[i][1]) }) };
    }
    if ((g.predvajaj || []).indexOf(s) >= 0) return { dejanje: "key", parametri: { key: "play_pause" }, opis: t("predvajanje") };
    if ((g.stranGor || []).indexOf(s) >= 0) return { dejanje: "scroll", parametri: { direction: "up" }, opis: t("stranGor") };
    if ((g.stranDol || []).indexOf(s) >= 0) return { dejanje: "scroll", parametri: { direction: "down" }, opis: t("stranDol") };

    // Program / kanal po stevilki: "program 25", "preklopi na kanal 3" -> stevke kot tipke.
    if (vsebuje(s, g.program) && stevilka != null && stevilka <= 999) {
      return { dejanje: "digits", parametri: { digits: String(stevilka) }, opis: t("kanal", { n: stevilka }) };
    }

    // "odpri X" / "zazeni X": aplikacija po imenu, sicer stran, sicer iskanje.
    var ostanek = odrezi(s, g.odpri);
    if (ostanek !== null) {
      if (!ostanek) return { dejanje: "key", parametri: { key: "home" }, opis: t("domov") };
      if (vsebuje(ostanek, g.youtube) || ostanek === "youtube") {
        var pojem = odrezi(ostanek, g.youtube);
        if (pojem) return youtube(pojem);
        var yt = najdiAplikacijo("youtube");
        if (yt) return { dejanje: "launch_app", parametri: { package: yt.package }, opis: t("odpiram", { ime: yt.label }) };
        return { dejanje: "open_url", parametri: { url: "https://www.youtube.com/" }, opis: t("odpiram", { ime: "YouTube" }) };
      }
      var app = najdiAplikacijo(ostanek);
      if (app) return { dejanje: "launch_app", parametri: { package: app.package }, opis: t("odpiram", { ime: app.label }) };
      var stranOst = odrezi(ostanek, g.stran);
      if (stranOst) return stran(stranOst);
      if (jeNaslov(ostanek)) return stran(ostanek);
      if (ostanek.length <= 24 && stanje.aplikacije.length) {
        // Kratko ime, ki ga med aplikacijami ni: povemo, ne iscemo na slepo.
        return { dejanje: "napaka", parametri: {}, opis: t("aplikacijaNiNamescena", { ime: ostanek }) };
      }
      return iskanje(ostanek);
    }

    // YouTube: "youtube X", "predvajaj X", "zavrti X"
    var ytOst = odrezi(s, g.youtube);
    if (ytOst !== null) {
      if (ytOst) return youtube(ytOst);
      var yt2 = najdiAplikacijo("youtube");
      if (yt2) return { dejanje: "launch_app", parametri: { package: yt2.package }, opis: t("odpiram", { ime: yt2.label }) };
      return { dejanje: "open_url", parametri: { url: "https://www.youtube.com/" }, opis: t("odpiram", { ime: "YouTube" }) };
    }
    var glasbaOst = odrezi(s, g.predvajajGlasbo);
    if (glasbaOst !== null && glasbaOst) {
      var brezYt = odrezi(glasbaOst, (g.youtube || []).map(function (y) { return "na " + y; }).concat(g.youtube || [], ["on youtube", "auf youtube", "en youtube", "sur youtube", "su youtube"]));
      return youtube(brezYt !== null ? (brezYt || glasbaOst) : glasbaOst);
    }

    // Aplikacija samo po imenu ("netflix")
    var app2 = najdiAplikacijo(s);
    if (app2 && s.length <= 24) return { dejanje: "launch_app", parametri: { package: app2.package }, opis: t("odpiram", { ime: app2.label }) };

    // Naslov strani
    if (jeNaslov(s)) return stran(s);

    // Iskanje
    var iskOst = odrezi(s, g.poisci);
    if (iskOst !== null) return iskanje(iskOst || surovo);
    return { dejanje: "iskanje", parametri: { q: surovo }, opis: t("nisemRazumel", { kaj: surovo }), neznano: true };
  }

  function jeNaslov(s) {
    return /^(https?:\/\/)?([a-z0-9-]+\.)+[a-z]{2,}(\/\S*)?$/i.test(s.replace(/\s+/g, ""));
  }
  function stran(s) {
    var url = s.replace(/\s+/g, "");
    if (!/^https?:\/\//i.test(url)) url = "https://" + url;
    return { dejanje: "open_url", parametri: { url: url }, opis: t("odpiramStran") };
  }
  function iskanje(q) {
    return { dejanje: "open_url", parametri: { url: "https://www.google.com/search?q=" + encodeURIComponent(q) }, opis: t("iscem", { kaj: q }) };
  }
  function youtube(q) {
    var url = "https://www.youtube.com/results?search_query=" + encodeURIComponent(q);
    var yt = najdiAplikacijo("youtube");
    if (yt) return { dejanje: "open_in_app", parametri: { package: yt.package, url: url }, opis: t("iscemYoutube", { kaj: q }) };
    return { dejanje: "open_url", parametri: { url: url }, opis: t("iscemYoutube", { kaj: q }) };
  }

  /** Izvede razumljen ukaz (tudi vec tipk zapored, npr. stevke programa). */
  function izvediRazumljeno(u) {
    if (!u) return;
    besedilo("daljinecOdgovor", u.opis);
    var o = el("daljinecOdgovor");
    if (o) o.classList.toggle("napaka", u.dejanje === "napaka");
    if (u.dejanje === "napaka") return;
    if (u.dejanje === "iskanje") {
      ukaz("open_url", { url: "https://www.google.com/search?q=" + encodeURIComponent(u.parametri.q) }, function (izid) { pokaziOdgovor(izid, u.opis); });
      return;
    }
    if (u.dejanje === "digits") {
      var stevke = String(u.parametri.digits).split("");
      var i = 0;
      var naslednja = function () {
        if (i >= stevke.length) { pokaziOdgovor({ ok: true }, u.opis); return; }
        ukaz("key", { key: stevke[i++] }, function (izid) {
          if (!izid || !izid.ok) { pokaziOdgovor(izid); return; }
          setTimeout(naslednja, 250);
        });
      };
      naslednja();
      return;
    }
    if (u.dejanje === "open_in_app") {
      ukaz("open_in_app", u.parametri, function (izid) {
        if (izid && izid.ok) { pokaziOdgovor(izid, u.opis); return; }
        // Aplikacija povezave ne zna: odpremo jo v Safeerju.
        ukaz("open_url", { url: u.parametri.url }, function (izid2) { pokaziOdgovor(izid2, u.opis); });
      });
      return;
    }
    ukaz(u.dejanje, u.parametri, function (izid) {
      if (u.dejanje === "volume" && izid && izid.ok && izid.data) narisiGlasnost(izid.data);
      if (u.dejanje === "screenshot" && izid && izid.ok) { pokaziPosnetek(izid.data); return; }
      pokaziOdgovor(izid, u.opis);
    });
  }

  function izvediBesedilo(besedilo) {
    var cisto = String(besedilo || "").trim();
    if (!cisto) return;
    stanje.zadnjeSliseno = cisto;
    var e = el("daljinecSliseno");
    if (e) { e.textContent = "»" + cisto + "«"; e.classList.remove("namig"); }
    izvediRazumljeno(razumi(cisto));
  }

  // ----------------------------------------------------------------
  // Glas: most -> stran
  // ----------------------------------------------------------------

  function mikrofon() {
    var gumb = el("daljinecMikrofon");
    if (!znaGovor()) { pokaziOdgovorNiz(t("niGovora"), true); return; }
    if (stanje.poslusam) {
      try { most.nehajPoslusati(); } catch (e) {}
      nastaviMikrofon("");
      return;
    }
    nastaviMikrofon("poslusam");
    var e = el("daljinecSliseno");
    if (e) { e.textContent = t("poslusam"); e.classList.add("namig"); }
    besedilo("daljinecOdgovor", "");
    try { most.poslusaj(jezik); } catch (err) { nastaviMikrofon(""); pokaziOdgovorNiz(t("napakaGovora"), true); }
  }

  function nastaviMikrofon(nacin) {
    var gumb = el("daljinecMikrofon");
    stanje.poslusam = nacin === "poslusam";
    if (!gumb) return;
    gumb.classList.toggle("poslusam", nacin === "poslusam");
    gumb.classList.toggle("obdelujem", nacin === "obdelujem");
  }

  function pokaziOdgovorNiz(niz, napaka) {
    var o = el("daljinecOdgovor");
    if (!o) return;
    o.textContent = niz;
    o.classList.toggle("napaka", !!napaka);
  }

  /** Odziv prepoznavalnika: {stanje: poslusam|delno|koncno|obdelujem|napaka, besedilo, koda}. */
  function govor(podatki) {
    if (!podatki) return;
    var s = podatki.stanje;
    var e = el("daljinecSliseno");
    if (s === "poslusam") {
      nastaviMikrofon("poslusam");
      if (e) { e.textContent = t("poslusam"); e.classList.add("namig"); }
    } else if (s === "delno") {
      if (e && podatki.besedilo) { e.textContent = "»" + podatki.besedilo + " …«"; e.classList.remove("namig"); }
    } else if (s === "obdelujem") {
      nastaviMikrofon("obdelujem");
      pokaziOdgovorNiz(t("obdelujem"), false);
    } else if (s === "koncno") {
      nastaviMikrofon("");
      if (podatki.besedilo) izvediBesedilo(podatki.besedilo);
      else { if (e) { e.textContent = t("nicSlisano"); e.classList.add("namig"); } }
    } else if (s === "napaka") {
      nastaviMikrofon("");
      pokaziOdgovorNiz("", false);
      var koda = podatki.koda || "";
      var niz = koda === "nic_slisano" ? t("nicSlisano") : koda === "dovoljenje" ? t("dovoljenje")
        : koda === "ni_prepoznavalnika" ? t("niGovora") : t("napakaGovora");
      if (e) { e.textContent = niz; e.classList.add("namig"); }
    }
  }

  // ----------------------------------------------------------------
  // Posnetek zaslona
  // ----------------------------------------------------------------

  function posnetek() {
    var g = el("daljinecPosnetekGumb");
    pokazi("daljinecPosnetek", true);
    if (g) g.classList.add("vklopljen");
    ukaz("screenshot", {}, function (izid) {
      if (izid && izid.ok) pokaziPosnetek(izid.data);
      else {
        besedilo("daljinecPosnetekOpomba", (izid && izid.message) || t("posnetekNiUspel"));
        if (izid && !izid.ok && stanje.samodejno) nacrtujPosnetek(6000);
      }
    }, 12000);
  }

  function pokaziPosnetek(podatki) {
    pokazi("daljinecPosnetek", true);
    var g = el("daljinecPosnetekGumb");
    if (g) g.classList.add("vklopljen");
    var slika = el("daljinecSlika");
    if (slika && podatki && podatki.image) slika.src = podatki.image;
    var zdaj = new Date();
    var cas = ("0" + zdaj.getHours()).slice(-2) + ":" + ("0" + zdaj.getMinutes()).slice(-2) + ":" + ("0" + zdaj.getSeconds()).slice(-2);
    besedilo("daljinecPosnetekOpomba", t("posnetekOsvezen", { cas: cas }));
    if (stanje.samodejno) nacrtujPosnetek(4000);
  }

  function nacrtujPosnetek(zamik) {
    if (stanje.posnetekTimer) clearTimeout(stanje.posnetekTimer);
    if (!stanje.odprt || !stanje.samodejno) return;
    stanje.posnetekTimer = setTimeout(function () {
      stanje.posnetekTimer = null;
      if (stanje.odprt && stanje.samodejno && document.visibilityState !== "hidden") posnetek();
      else if (stanje.samodejno) nacrtujPosnetek(4000);
    }, zamik);
  }

  function preklopiPosnetek() {
    var vidno = !el("daljinecPosnetek").hidden;
    if (vidno) {
      pokazi("daljinecPosnetek", false);
      var g = el("daljinecPosnetekGumb");
      if (g) g.classList.remove("vklopljen");
      stanje.samodejno = false;
      var st = el("daljinecSamodejno");
      if (st) st.checked = false;
      if (stanje.posnetekTimer) clearTimeout(stanje.posnetekTimer);
      stanje.posnetekTimer = null;
    } else {
      posnetek();
    }
  }

  // ----------------------------------------------------------------
  // Stanje naprave
  // ----------------------------------------------------------------

  function osveziStanje() {
    ukaz("status", {}, function (izid) {
      var s = el("daljinecStanje");
      if (!s) return;
      if (izid && izid.ok && izid.data) {
        var d = izid.data;
        if (d.volume != null) narisiGlasnost({ level: d.volume, muted: !!d.muted });
        var naslov = d.title || d.url || "";
        if (naslov && naslov.indexOf("android_asset") >= 0) naslov = t("domov");
        var neMore = d.foreground === false && d.can_wake === false;
        s.textContent = neMore ? t("neMoreVOspredje") : d.foreground === false ? t("niVOspredju") : (naslov ? t("odprtaStran", { naslov: naslov }) : (d.version ? "Safeer " + d.version : ""));
        s.classList.toggle("napaka", d.foreground === false);
        // Kar naprava ne zna, skrijemo: drsenje je le v brskalniku, aplikacije le na Androidu.
        var dejanja = d.actions || [];
        pokazi("daljinecAplikacijePanel", dejanja.indexOf("launch_app") >= 0);
        // Pretakanje na ta racunalnik: samo v Safeer Control in pri napravi, ki zna apps.launch (Android).
        pokazi("daljinecPretociIzbira", document.body.classList.contains("namizje") && dejanja.indexOf("apps.launch") >= 0);
        pokazi("daljinecDrsenje", dejanja.indexOf("scroll") >= 0);
        var tipkeNaprave = d.keys || [];
        var dpad = el("daljinecDpad");
        if (dpad) dpad.style.visibility = tipkeNaprave.indexOf("ok") >= 0 ? "" : "hidden";
        if (dejanja.indexOf("launch_app") >= 0) naloziAplikacije(false);
      } else {
        s.textContent = (izid && izid.message) || t("brezOdgovora");
        s.classList.add("napaka");
      }
    }, 6000);
  }

  /** Katera naprava je sredisce Safeer Linka (na njej tece Link, prek nje gredo ukazi). */
  function osveziSredisce() {
    var e = el("daljinecSredisce");
    if (!e) return;
    var ime = "";
    try { ime = api().sredisce ? api().sredisce() : ""; } catch (err) { ime = ""; }
    e.textContent = ime ? t("sredisce", { ime: ime }) : "";
    e.style.display = ime ? "" : "none";
  }

  // ----------------------------------------------------------------
  // Odpiranje in zapiranje
  // ----------------------------------------------------------------

  var prevedeno = false;
  var pripeto = false;

  function odpri(naprava) {
    if (!naprava) return;
    stanje.naprava = naprava;
    stanje.odprt = true;
    if (!prevedeno) { prevedi(); prevedeno = true; }
    if (!pripeto) { pripni(); pripeto = true; }
    var ime = (api().prijaznoIme ? api().prijaznoIme(naprava) : (naprava.ime || t("naprava")));
    besedilo("daljinecIme", ime);
    besedilo("daljinecStanje", "");
    besedilo("daljinecAplikacijeNaslov", t("aplikacijeNa", { ime: ime }));
    osveziSredisce();
    besedilo("daljinecOdgovor", "");
    var e = el("daljinecSliseno");
    var govor = znaGovor();
    if (e) { e.textContent = t(govor ? "govoriNamig" : "pisiNamig"); e.classList.add("namig"); }
    var mik = el("daljinecMikrofon");
    // Brez prepoznave govora (racunalnik) mikrofona ne kazemo: ukaz se vpise v polje spodaj.
    if (mik) { mik.disabled = !govor; mik.style.display = govor ? "" : "none"; }
    pokazi("daljinecGlas", true);
    // Shranjen seznam aplikacij (brez ikon) pokazemo takoj; sveze pridejo iz naprave.
    if (stanje.aplikacijeZa !== naprava.id) {
      stanje.aplikacije = [];
      try {
        var shranjene = JSON.parse(window.localStorage.getItem("safeer_daljinec_apps_" + naprava.id) || "[]");
        if (shranjene && shranjene.length) { stanje.aplikacije = shranjene; stanje.aplikacijeZa = ""; }
      } catch (err) {}
    }
    narisiAplikacije();
    if (api().pokaziDaljinec) api().pokaziDaljinec(true);
    pokazi("zaslonDaljinec", true);
    try { window.scrollTo(0, 0); } catch (err) {}
    osveziStanje();
    if (api().televizor && api().televizor()) {
      setTimeout(function () { try { el("daljinecMikrofon").focus(); } catch (err) {} }, 60);
    }
  }

  function zapri() {
    stanje.odprt = false;
    stanje.naprava = null;
    stanje.samodejno = false;
    if (stanje.posnetekTimer) clearTimeout(stanje.posnetekTimer);
    stanje.posnetekTimer = null;
    if (stanje.poslusam) { try { most.nehajPoslusati(); } catch (e) {} nastaviMikrofon(""); }
    pokazi("daljinecPosnetek", false);
    var g = el("daljinecPosnetekGumb");
    if (g) g.classList.remove("vklopljen");
    pokazi("zaslonDaljinec", false);
    if (api().pokaziDaljinec) api().pokaziDaljinec(false);
  }

  /** Seznam naprav se je spremenil: ce nase ni vec, daljinec zapremo. */
  function naprave(seznam) {
    if (!stanje.odprt || !stanje.naprava) return;
    var se = (seznam || []).some(function (n) { return n.id === stanje.naprava.id; });
    if (!se) { zapri(); return; }
    osveziSredisce();
  }

  function pripni() {
    var nazaj = el("daljinecNazaj");
    if (nazaj) nazaj.addEventListener("click", zapri);
    var pg = el("daljinecPosnetekGumb");
    if (pg) pg.addEventListener("click", preklopiPosnetek);
    var sam = el("daljinecSamodejno");
    if (sam) sam.addEventListener("change", function () { stanje.samodejno = !!sam.checked; if (stanje.samodejno) posnetek(); });
    var mik = el("daljinecMikrofon");
    if (mik) mik.addEventListener("click", mikrofon);
    var obrazec = el("daljinecVnosObrazec");
    if (obrazec) obrazec.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var v = el("daljinecVnos");
      if (!v) return;
      izvediBesedilo(v.value);
      v.value = "";
      try { v.blur(); } catch (e) {}
    });
    var koren = el("zaslonDaljinec");
    if (koren) koren.addEventListener("click", function (ev) {
      var cilj = ev.target;
      while (cilj && cilj !== koren && !(cilj.getAttribute && (cilj.getAttribute("data-tipka") || cilj.getAttribute("data-glasnost") || cilj.getAttribute("data-drsenje") || cilj.getAttribute("data-ukaz")))) cilj = cilj.parentNode;
      if (!cilj || cilj === koren) return;
      var k = cilj.getAttribute("data-tipka");
      if (k) { tipka(k, cilj); return; }
      var gl = cilj.getAttribute("data-glasnost");
      if (gl) { glasnost({ direction: gl }, cilj); return; }
      var dr = cilj.getAttribute("data-drsenje");
      if (dr) { drsenje(dr, cilj); return; }
      var uk = cilj.getAttribute("data-ukaz");
      if (uk) {
        utrip(cilj);
        ukaz(uk, {}, function (izid) {
          var o = el("daljinecVecOpomba");
          var niz = izid ? (izid.message || "") : t("brezOdgovora");
          if (uk === "status" && izid && izid.ok && izid.data) {
            var d = izid.data;
            niz = (d.model ? d.model + " · " : "") + (d.app || "") + " " + (d.version || "") + (d.android ? " · Android " + d.android : "") + (d.url ? " · " + d.url : "");
          }
          if (o) o.textContent = niz;
          if (uk !== "status") pokaziOdgovor(izid, izid && izid.message);
        }, 15000);
      }
    });
    var osv = el("daljinecAplikacijeOsvezi");
    if (osv) osv.addEventListener("click", function () { naloziAplikacije(true); });
    // Daljinec televizorja: Nazaj na strani zapre daljinec, ne cele strani Linka.
    document.addEventListener("keydown", function (ev) {
      if (!stanje.odprt) return;
      if (ev.key === "Escape" || ev.key === "Backspace" && !(ev.target && /input|textarea/i.test(ev.target.tagName))) {
        ev.preventDefault();
        zapri();
      }
    });
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "hidden" && stanje.poslusam) { try { most.nehajPoslusati(); } catch (e) {} nastaviMikrofon(""); }
    });
  }

  window.SafeerDaljinec = {
    odpri: odpri,
    zapri: zapri,
    odziv: odziv,
    govor: govor,
    naprave: naprave,
    jeOdprt: function () { return stanje.odprt; },
    razumi: razumi
  };
})();
