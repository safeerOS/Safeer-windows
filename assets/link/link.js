/**
 * Safeer Link — vgrajen zaslon brskalnika.
 *
 * Oblika je namenoma brez zavihkov: en sam zaslon, ki ga uporabnik prelista.
 * Zgoraj je dejanje (poslji to stran), pod njim stanje (naprave), na dnu nastavitev
 * (sinhronizacija). Kdor odpre Link, najveckrat nekaj posilja -- to naj bo prvo.
 *
 * Stran sama nikoli ne govori z omrezjem in nikoli ne vidi zetona: za vse prosi most
 * (window.SafeerLink), ki ga aplikacija pripne samo temu pogledu. Odgovori pridejo
 * nazaj v window.safeerLinkOdziv, ker most ne sme cakati na omrezje.
 *
 * Nacela vmesnika:
 *  - uporabnik ne vidi ne IP-jev ne vrat ne nastavitev,
 *  - stanje je barva: zelena povezano, siva ni Safeer Linka, rumena tezava,
 *  - imena naprav so cloveska, nikoli tehnicni ID,
 *  - sporocila so v jeziku uporabnika in v navadnih besedah, vedno z naslednjim korakom.
 */
(function () {
  "use strict";

  var most = window.SafeerLink || null;
  // Odprt daljinec (daljinec.js) prekrije vse drugo; glej pokaziDaljinec.
  var daljinecOdprt = false;

  // Krajevna imena naprav: vsak uporabnik na svoji napravi poimenuje ostale po svoje.
  // Shranjena so na tej napravi (most.vzdevki / most.shraniVzdevek), ne na Safeer Linku,
  // zato prezivijo tudi zamenjavo naprave, ki gosti. Brez mostu ostane localStorage.
  var vzdevki = {};
  function naloziVzdevke() {
    try {
      if (most && most.vzdevki) { vzdevki = JSON.parse(most.vzdevki() || "{}") || {}; return; }
      vzdevki = JSON.parse(window.localStorage.getItem("safeer_link_vzdevki") || "{}") || {};
    } catch (e) { vzdevki = {}; }
  }
  function shraniVzdevek(id, ime) {
    if (!id) return false;
    if (ime) vzdevki[id] = ime; else delete vzdevki[id];
    try {
      if (most && most.shraniVzdevek) { most.shraniVzdevek(id, ime || ""); return true; }
      window.localStorage.setItem("safeer_link_vzdevki", JSON.stringify(vzdevki));
      return true;
    } catch (e) { return false; }
  }
  naloziVzdevke();

  var el = function (id) { return document.getElementById(id); };

  // ----------------------------------------------------------------
  // Jezik uporabnika
  // ----------------------------------------------------------------

  var BESEDILA = {
    sl: {
      poisciDrugega: "Poišči drug Safeer Link",
      vnesiKodoOpis: "Na napravi, kjer teče Safeer Link, se je izpisala 6-mestna številka. Prepiši jo sem.",
      povezi: "Poveži",
      preverjamKodo: "Preverjam kodo …",
      napNapacnaKoda: "Koda ni pravilna. Poskusi znova.",
      napPrevecPoskusov: "Preveč poskusov. Začni znova — dobiš novo kodo.",
      napPrijavaPotekla: "Koda je potekla. Začni znova.",
      napNapravaNiZnana: "Safeer Link te naprave ne pozna več (gostitelj je bil ponastavljen ali te je odstranil). Poveži jo znova s kodo.",
      prijavaCakaKodo: "Na tej napravi vtipkaj številko, ki jo vidiš tukaj",
      javniWifiNaslov: "V javnih omrežjih priporočamo, da je Safeer Link izklopljen",
      javniWifiOpis: "V kavarni, hotelu ali na letališču je v istem omrežju lahko kdorkoli. Če Safeer Link tam kljub temu uporabljaš, ostaneš zaščiten: tuja naprava se ne more povezati sama. Naprava, ki gosti Safeer Link, izpiše na svojem zaslonu 6-mestno številko, in dokler te številke ne vtipkaš na drugi napravi, se ne poveže nič in se ne prenese nič.",
      napHubNiZnan: "Huba še ne poznam. Najprej ga poišči.",
      napIskanje: "Iskanja ni bilo mogoče zagnati.",
      napSeznanitev: "Seznanitve ni bilo mogoče začeti.",
      napPovezava: "Povezava ni uspela. Preveri, ali je Safeer Link na drugi napravi vklopljen.",
      napStranNiPrimerna: "Te strani ni mogoče poslati.",
      napSamoHttp: "Poslati je mogoče samo naslove http in https.",
      napPosiljanje: "Pošiljanje ni uspelo. Poskusi znova.",
      napUkaz: "Ukaz ni uspel.",
      napZaznamki: "Zaznamkov ni bilo mogoče poslati.",
      napSyncStart: "Sinhronizacije ni bilo mogoče začeti.",
      napSyncNastavi: "Sinhronizacije ni bilo mogoče nastaviti.",
      napZdruzevanje: "Združevanja zaznamkov ni bilo mogoče končati.",
      napHubNeTece: "Safeer Link tu ni vklopljen.",
      napHubNiZagnan: "Huba ni bilo mogoče zagnati.",
      napHubNiUstavljen: "Huba ni bilo mogoče ustaviti.",
      napPrijavaPotekla: "Prijave ni več ali pa je potekla.",
      napTvJeZaslon: "Televizor je zaslon in ne pošilja.",
      napTvNeUpravlja: "Televizor ne upravlja drugih zaslonov.",
      napSyncTvNiNaVoljo: "Sinhronizacija zaznamkov na televizorju še ni na voljo.",
      preverjam: "Preverjam …",
      zapri: "Zapri",
      povezano: "Povezano z domačim Safeer Linkom",
      cakaNaPotrditev: "Čaka na tvojo potrditev",
      niVklopljen: "Ni povezano",
      brezHubaNaslov: "Safeer Link še ni vklopljen",
      brezHubaOpis: "Safeer Link poveže tvoje naprave doma — telefon, računalnik in televizor. Z ene na drugo pošlješ stran, besedilo, datoteko ali zaslon, brez oblaka in brez računa. Povezovanje začneš na katerikoli napravi (lahko tudi na tej), ostale se le pridružijo.",
      brezHubaPomirilo: "Safeer OS deluje tudi brez povezanih naprav. Naprave lahko povežeš kadar koli.",
      poisci: "Poišči v mojem omrežju",
      kakoDobim: "Kako to vklopim",
      iscem: "Iščem …",
      niNajden: "V tem omrežju ga nisem našel. Preveri, ali Safeer Link teče na kateri od tvojih naprav, in poskusi znova.",
      povežiNaslov: "Poveži to napravo",
      hubNajdenNa: "V tvojem omrežju je Safeer Link vklopljen na napravi",
      zakajPotrditi: "Povezavo potrdi enkrat — nato si lahko izmenjujeta strani, besedila, datoteke in zaslon.",
      potrdiKodo: "Kodo potrdi na napravi, kjer teče Safeer Link:",
      kodaVelja: "Koda velja 5 minut.",
      poveziSSafeerLink: "Poveži s Safeer Link",
      cakamNaPotrditev: "Čakam na potrditev …",
      niPotrjeno: "Koda ni bila potrjena. Poskusi znova.",
      posljiStran: "Pošlji to stran",
      odprtoVBrskalniku: "Odprto v brskalniku",
      domacaStran: "Domača stran — pošiljanje ni mogoče",
      predvajaSeNa: "Predvaja se na",
      nazaj10: "10 s",
      pavza: "Pavza",
      predvajaj: "Predvajaj",
      naprej10: "10 s",
      povezaneNaprave: "Povezane naprave",
      osvezi: "Osveži",
      povezujem: "Povezujem se …",
      taNaprava: "Ta naprava",
      povezanaZLinkom: "Povezana s Safeer Linkom",
      domace: "Domača povezava",
      zaslon: "Zaslon",
      televizor: "Televizor",
      posljiNaZaslon: "Pošlji na ta zaslon",
      posljiNaNapravo: "Pošlji na to napravo",
      poslji: "Pošlji",
      povezan: "Povezan",
      brezZaslonov: "Nobena druga naprava še ni povezana. Na njej odpri Safeer Link in vtipkaj kodo, ki jo pokaže ta naprava.",
      poslanoNa: "Poslano na {ime}.",
      niDosegljiv: "{ime} trenutno ni dosegljiv. Preveri, ali je prižgan, in poskusi znova.",
      neMorePoslati: "Te strani ni mogoče poslati. Odpri spletno stran in poskusi znova.",
      povezaveNi: "Povezave s Safeer Linkom ni. Poskusi znova.",
      pozabiNapravo: "Pozabi to napravo",
      pozabiPotrdi: "Res? Dotakni se še enkrat — ta naprava se bo odklopila.",
      pozabljeno: "Naprava je odklopljena. Znova jo lahko povežeš kadar koli.",
      sinhronizacija: "Sinhronizacija",
      syncOpis: "Zaznamki potujejo med tvojimi napravami prek domačega Safeer Linka. Nič ne gre v oblak.",
      mapeNaslov: "Datoteke za televizor",
      mapeOpis: "Izbrane mape vidi Safeer OS na televizorju — filmi, glasba in slike se predvajajo naravnost s tega računalnika, samo v domačem omrežju.",
      mapeDodaj: "Dodaj mapo",
      mapePrazno: "Ni izbrane nobene mape. Televizor ne vidi nič.",
      mapeOdstrani: "Odstrani",
      mapeStandardne: "Deli Videi, Glasba in Slike",
      syncPrivzeto: "Sinhronizacija se vklopi, ko jo potrdiš — do takrat se ne pošlje nič.",
      zaznamki: "Zaznamki",
      syncVklopljena: "Vklopljeno",
      syncIzklopljena: "Izklopljeno",
      syncPotrdi: "Potrdi",
      syncVklopljenaOpis: "Vklopljena — {n} zaznamkov na tej napravi",
      syncNiNaVoljo: "Na tej napravi še ni na voljo",
      syncVprasanje: "Tvojih {n} zaznamkov bo poslanih vsem tvojim napravam. Dotakni se še enkrat, da potrdiš.",
      syncPovabilo: "Dotakni se, da vklopiš. Do takrat se ne pošlje nič.",
      syncVklapljam: "Vklapljam …",
      syncIzklapljam: "Izklapljam …",
      syncTece: "Sinhronizacija teče v ozadju.",
      syncPrejeto: "Prejeto: {n} novih zaznamkov.",
      syncUgasnjena: "Sinhronizacija je izklopljena. Nič se ne pošilja.",
      nastavitve: "Nastavitve",
      nastavitveOpis: "Videz, iskalnik, zaščite",
      filtri: "Seznami filtrov",
      filtriOpis: "Iste zaščite na vseh napravah",
      kmalu: "Kmalu",
      tezava: "Nekaj ni v redu. Poskusi znova.",
      preseljenNaslov: "Safeer Link je na novem naslovu",
      preseljenOpis: "Doma se javlja z drugega naslova kot doslej — običajno zato, ker mu je usmerjevalnik podelil novega. Potrdi, da je to tvoj Safeer Link.",
      daPovezi: "Da, poveži",
      preverjamNaslov: "Povezujem se na nov naslov …"
    },
    en: {
      poisciDrugega: "Look for another Safeer Link",
      vnesiKodoOpis: "A 6-digit number appeared on the device running Safeer Link. Type it here.",
      povezi: "Connect",
      preverjamKodo: "Checking the code …",
      napNapacnaKoda: "That code is not right. Try again.",
      napPrevecPoskusov: "Too many attempts. Start again — you will get a new code.",
      napPrijavaPotekla: "The code has expired. Start again.",
      napNapravaNiZnana: "Safeer Link no longer knows this device (the host was reset or removed it). Connect it again with a code.",
      prijavaCakaKodo: "Type the number you see here on that device",
      javniWifiNaslov: "On public networks we recommend turning Safeer Link off",
      javniWifiOpis: "In a cafe, hotel or airport anyone can be on the same network. If you still use Safeer Link there, you stay protected: a stranger's device cannot connect on its own. The device hosting Safeer Link shows a 6-digit number on its screen, and until you type that number on the other device, nothing connects and nothing is transferred.",
      napHubNiZnan: "No connection is known yet. Search your network first.",
      napIskanje: "The search could not be started.",
      napSeznanitev: "Pairing could not be started.",
      napPovezava: "The connection failed. Check that Safeer Link is switched on on the other device.",
      napStranNiPrimerna: "This page cannot be sent.",
      napSamoHttp: "Only http and https addresses can be sent.",
      napPosiljanje: "Sending failed. Try again.",
      napUkaz: "The command failed.",
      napZaznamki: "The bookmarks could not be sent.",
      napSyncStart: "Sync could not be started.",
      napSyncNastavi: "Sync could not be set up.",
      napZdruzevanje: "Merging the bookmarks could not be finished.",
      napHubNeTece: "Safeer Link is not switched on here.",
      napHubNiZagnan: "Safeer Link could not be switched on.",
      napHubNiUstavljen: "Safeer Link could not be switched off.",
      napPrijavaPotekla: "The request is gone or has expired.",
      napTvJeZaslon: "The television is a screen; it does not send.",
      napTvNeUpravlja: "The television does not control other screens.",
      napSyncTvNiNaVoljo: "Bookmark sync is not available on the television yet.",
      preverjam: "Checking …",
      zapri: "Close",
      povezano: "Connected to your home Safeer Link",
      cakaNaPotrditev: "Waiting for your approval",
      niVklopljen: "Not connected",
      brezHubaNaslov: "Safeer Link is not set up yet",
      brezHubaOpis: "Safeer Link connects the devices in your home — phone, computer and television. Send a page, text, a file or your screen from one to another, with no cloud and no account. Start on any device (this one will do); the others simply join.",
      brezHubaPomirilo: "Safeer OS also works without connected devices. You can connect them at any time.",
      poisci: "Look on my network",
      kakoDobim: "How do I turn this on",
      iscem: "Looking …",
      niNajden: "I could not find it on this network. Check that Safeer Link is running on one of your devices and try again.",
      povežiNaslov: "Connect this device",
      hubNajdenNa: "On your network, Safeer Link is switched on at",
      zakajPotrditi: "Approve the connection once — then you can exchange pages, text, files and screens.",
      potrdiKodo: "Approve this code on the device running Safeer Link:",
      kodaVelja: "The code is valid for 5 minutes.",
      poveziSSafeerLink: "Connect to Safeer Link",
      cakamNaPotrditev: "Waiting for approval …",
      niPotrjeno: "The code was not approved. Please try again.",
      posljiStran: "Send this page",
      odprtoVBrskalniku: "Open in the browser",
      domacaStran: "Home page — cannot be sent",
      predvajaSeNa: "Playing on",
      nazaj10: "10 s",
      pavza: "Pause",
      predvajaj: "Play",
      naprej10: "10 s",
      povezaneNaprave: "Connected devices",
      osvezi: "Refresh",
      povezujem: "Connecting …",
      taNaprava: "This device",
      povezanaZLinkom: "Connected to Safeer Link",
      domace: "Home link",
      zaslon: "Screen",
      televizor: "Television",
      posljiNaZaslon: "Send to this screen",
      posljiNaNapravo: "Send to this device",
      poslji: "Send",
      povezan: "Connected",
      brezZaslonov: "No other device is connected yet. Open Safeer Link on it and type the code shown by this device.",
      poslanoNa: "Sent to {ime}.",
      niDosegljiv: "{ime} cannot be reached right now. Check that it is on and try again.",
      neMorePoslati: "This page cannot be sent. Open a website and try again.",
      povezaveNi: "There is no connection to Safeer Link. Please try again.",
      pozabiNapravo: "Forget this device",
      pozabiPotrdi: "Sure? Tap once more — this device will be disconnected.",
      pozabljeno: "The device is disconnected. You can connect it again any time.",
      sinhronizacija: "Sync",
      syncOpis: "Your bookmarks travel between your devices through your home Safeer Link. Nothing goes to the cloud.",
      mapeNaslov: "Files for the TV",
      mapeOpis: "Safeer OS on the TV sees the folders you pick here — films, music and photos play straight from this computer, on your home network only.",
      mapeDodaj: "Add folder",
      mapePrazno: "No folder selected. The TV sees nothing.",
      mapeOdstrani: "Remove",
      mapeStandardne: "Share Videos, Music and Pictures",
      syncPrivzeto: "Sync starts once you confirm it — until then nothing is sent.",
      zaznamki: "Bookmarks",
      syncVklopljena: "On",
      syncIzklopljena: "Off",
      syncPotrdi: "Confirm",
      syncVklopljenaOpis: "On — {n} bookmarks on this device",
      syncNiNaVoljo: "Not available on this device yet",
      syncVprasanje: "Your {n} bookmarks will be sent to all your devices. Tap once more to confirm.",
      syncPovabilo: "Tap to turn on. Until then nothing is sent.",
      syncVklapljam: "Turning on …",
      syncIzklapljam: "Turning off …",
      syncTece: "Sync runs in the background.",
      syncPrejeto: "Received: {n} new bookmarks.",
      syncUgasnjena: "Sync is off. Nothing is being sent.",
      nastavitve: "Settings",
      nastavitveOpis: "Look, search engine, protections",
      filtri: "Filter lists",
      filtriOpis: "The same protections on every device",
      kmalu: "Soon",
      tezava: "Something went wrong. Please try again.",
      preseljenNaslov: "Safeer Link has a new address",
      preseljenOpis: "It is announcing itself from a different address than before — usually because the router gave it a new one. Confirm that this is your Safeer Link.",
      daPovezi: "Yes, connect",
      preverjamNaslov: "Connecting to the new address …"
    },
    de: {
      poisciDrugega: "Anderen Safeer Link suchen",
      vnesiKodoOpis: "Auf dem Gerät mit Safeer Link ist eine 6-stellige Zahl erschienen. Geben Sie sie hier ein.",
      povezi: "Verbinden",
      preverjamKodo: "Code wird geprüft …",
      napNapacnaKoda: "Der Code stimmt nicht. Versuchen Sie es erneut.",
      napPrevecPoskusov: "Zu viele Versuche. Beginnen Sie neu — Sie erhalten einen neuen Code.",
      napPrijavaPotekla: "Der Code ist abgelaufen. Beginnen Sie neu.",
      napNapravaNiZnana: "Safeer Link kennt dieses Gerät nicht mehr (der Host wurde zurückgesetzt oder hat es entfernt). Verbinde es erneut mit einem Code.",
      prijavaCakaKodo: "Geben Sie die hier angezeigte Zahl auf jenem Gerät ein",
      javniWifiNaslov: "In öffentlichen Netzen empfehlen wir, Safeer Link auszuschalten",
      javniWifiOpis: "Im Cafe, Hotel oder Flughafen kann jeder im selben Netz sein. Wenn Sie Safeer Link dort trotzdem nutzen, bleiben Sie geschützt: ein fremdes Gerät kann sich nicht von selbst verbinden. Das Gerät, auf dem Safeer Link läuft, zeigt eine 6-stellige Zahl an, und solange Sie diese Zahl nicht auf dem anderen Gerät eingeben, verbindet sich nichts und wird nichts übertragen.",
      napHubNiZnan: "Noch keine Verbindung bekannt. Durchsuche zuerst dein Netzwerk.",
      napIskanje: "Die Suche konnte nicht gestartet werden.",
      napSeznanitev: "Die Kopplung konnte nicht gestartet werden.",
      napPovezava: "Die Verbindung ist fehlgeschlagen. Prüfe, ob Safeer Link auf dem anderen Gerät eingeschaltet ist.",
      napStranNiPrimerna: "Diese Seite kann nicht gesendet werden.",
      napSamoHttp: "Es können nur http- und https-Adressen gesendet werden.",
      napPosiljanje: "Senden fehlgeschlagen. Versuche es noch einmal.",
      napUkaz: "Der Befehl ist fehlgeschlagen.",
      napZaznamki: "Die Lesezeichen konnten nicht gesendet werden.",
      napSyncStart: "Die Synchronisierung konnte nicht gestartet werden.",
      napSyncNastavi: "Die Synchronisierung konnte nicht eingerichtet werden.",
      napZdruzevanje: "Das Zusammenführen der Lesezeichen konnte nicht beendet werden.",
      napHubNeTece: "Safeer Link ist hier nicht eingeschaltet.",
      napHubNiZagnan: "Safeer Link konnte nicht eingeschaltet werden.",
      napHubNiUstavljen: "Safeer Link konnte nicht ausgeschaltet werden.",
      napPrijavaPotekla: "Die Anfrage gibt es nicht mehr oder sie ist abgelaufen.",
      napTvJeZaslon: "Der Fernseher ist ein Bildschirm; er sendet nicht.",
      napTvNeUpravlja: "Der Fernseher steuert keine anderen Bildschirme.",
      napSyncTvNiNaVoljo: "Die Lesezeichen-Synchronisierung ist auf dem Fernseher noch nicht verfügbar.",
      preverjam: "Prüfe …",
      zapri: "Schließen",
      povezano: "Mit deinem Safeer Link zu Hause verbunden",
      cakaNaPotrditev: "Warte auf deine Bestätigung",
      niVklopljen: "Nicht verbunden",
      brezHubaNaslov: "Safeer Link ist noch nicht eingerichtet",
      brezHubaOpis: "Safeer Link verbindet die Geräte bei dir zu Hause — Telefon, Computer und Fernseher. Sende eine Seite, Text, eine Datei oder deinen Bildschirm von einem zum anderen, ohne Cloud und ohne Konto. Beginne auf einem beliebigen Gerät (auch auf diesem); die anderen kommen einfach dazu.",
      brezHubaPomirilo: "Safeer OS funktioniert auch ohne verbundene Geräte. Du kannst sie jederzeit verbinden.",
      poisci: "In meinem Netzwerk suchen",
      kakoDobim: "Wie schalte ich das ein",
      iscem: "Suche …",
      niNajden: "Ich konnte ihn in diesem Netzwerk nicht finden. Prüfe, ob Safeer Link auf einem deiner Geräte läuft, und versuche es erneut.",
      povežiNaslov: "Dieses Gerät verbinden",
      hubNajdenNa: "In deinem Netzwerk ist Safeer Link eingeschaltet auf",
      zakajPotrditi: "Bestätige die Verbindung einmal — danach könnt ihr Seiten, Texte, Dateien und Bildschirme austauschen.",
      potrdiKodo: "Bestätige diesen Code auf dem Gerät, auf dem Safeer Link läuft:",
      kodaVelja: "Der Code gilt 5 Minuten.",
      poveziSSafeerLink: "Mit Safeer Link verbinden",
      cakamNaPotrditev: "Warte auf Bestätigung …",
      niPotrjeno: "Der Code wurde nicht bestätigt. Bitte versuche es erneut.",
      posljiStran: "Diese Seite senden",
      odprtoVBrskalniku: "Im Browser öffnen",
      domacaStran: "Startseite — kann nicht gesendet werden",
      predvajaSeNa: "Läuft auf",
      nazaj10: "10 s",
      pavza: "Pause",
      predvajaj: "Wiedergabe",
      naprej10: "10 s",
      povezaneNaprave: "Verbundene Geräte",
      osvezi: "Aktualisieren",
      povezujem: "Verbinde …",
      taNaprava: "Dieses Gerät",
      povezanaZLinkom: "Mit Safeer Link verbunden",
      domace: "Heimverbindung",
      zaslon: "Bildschirm",
      televizor: "Fernseher",
      posljiNaZaslon: "An diesen Bildschirm senden",
      posljiNaNapravo: "An dieses Gerät senden",
      poslji: "Senden",
      povezan: "Verbunden",
      brezZaslonov: "Noch kein anderes Gerät ist verbunden. Öffne dort Safeer Link und gib den Code ein, den dieses Gerät anzeigt.",
      poslanoNa: "An {ime} gesendet.",
      niDosegljiv: "{ime} ist gerade nicht erreichbar. Prüfe, ob das Gerät an ist, und versuche es erneut.",
      neMorePoslati: "Diese Seite kann nicht gesendet werden. Öffne eine Website und versuche es erneut.",
      povezaveNi: "Es besteht keine Verbindung zu Safeer Link. Bitte versuche es erneut.",
      pozabiNapravo: "Dieses Gerät vergessen",
      pozabiPotrdi: "Sicher? Tippe noch einmal — dieses Gerät wird getrennt.",
      pozabljeno: "Das Gerät ist getrennt. Du kannst es jederzeit wieder verbinden.",
      sinhronizacija: "Synchronisierung",
      syncOpis: "Deine Lesezeichen wandern über deinen Safeer Link zu Hause zwischen deinen Geräten. Nichts geht in die Cloud.",
      mapeNaslov: "Dateien für den Fernseher",
      mapeOpis: "Safeer OS auf dem Fernseher sieht die hier gewählten Ordner — Filme, Musik und Fotos laufen direkt von diesem Computer, nur im Heimnetz.",
      mapeDodaj: "Ordner hinzufügen",
      mapePrazno: "Kein Ordner gewählt. Der Fernseher sieht nichts.",
      mapeOdstrani: "Entfernen",
      mapeStandardne: "Videos, Musik und Bilder freigeben",
      syncPrivzeto: "Die Synchronisierung startet, sobald du sie bestätigst — bis dahin wird nichts gesendet.",
      zaznamki: "Lesezeichen",
      syncVklopljena: "Ein",
      syncIzklopljena: "Aus",
      syncPotrdi: "Bestätigen",
      syncVklopljenaOpis: "Ein — {n} Lesezeichen auf diesem Gerät",
      syncNiNaVoljo: "Auf diesem Gerät noch nicht verfügbar",
      syncVprasanje: "Deine {n} Lesezeichen werden an alle deine Geräte gesendet. Tippe noch einmal zum Bestätigen.",
      syncPovabilo: "Zum Einschalten tippen. Bis dahin wird nichts gesendet.",
      syncVklapljam: "Schalte ein …",
      syncIzklapljam: "Schalte aus …",
      syncTece: "Die Synchronisierung läuft im Hintergrund.",
      syncPrejeto: "Empfangen: {n} neue Lesezeichen.",
      syncUgasnjena: "Die Synchronisierung ist aus. Es wird nichts gesendet.",
      nastavitve: "Einstellungen",
      nastavitveOpis: "Aussehen, Suchmaschine, Schutzfunktionen",
      filtri: "Filterlisten",
      filtriOpis: "Der gleiche Schutz auf jedem Gerät",
      kmalu: "Bald",
      tezava: "Etwas ist schiefgelaufen. Bitte versuche es erneut.",
      preseljenNaslov: "Safeer Link hat eine neue Adresse",
      preseljenOpis: "Er meldet sich von einer anderen Adresse als zuvor — meist weil der Router ihm eine neue gegeben hat. Bestätige, dass das dein Safeer Link ist.",
      daPovezi: "Ja, verbinden",
      preverjamNaslov: "Verbinde mit der neuen Adresse …"
    },
    es: {
      poisciDrugega: "Buscar otro Safeer Link",
      vnesiKodoOpis: "En el dispositivo con Safeer Link ha aparecido un número de 6 dígitos. Escríbalo aquí.",
      povezi: "Conectar",
      preverjamKodo: "Comprobando el código …",
      napNapacnaKoda: "El código no es correcto. Inténtelo de nuevo.",
      napPrevecPoskusov: "Demasiados intentos. Empiece de nuevo: obtendrá un código nuevo.",
      napPrijavaPotekla: "El código ha caducado. Empiece de nuevo.",
      napNapravaNiZnana: "Safeer Link ya no conoce este dispositivo (el anfitrión se reinició o lo eliminó). Conéctalo de nuevo con un código.",
      prijavaCakaKodo: "Escriba en ese dispositivo el número que ve aquí",
      javniWifiNaslov: "En redes públicas recomendamos apagar Safeer Link",
      javniWifiOpis: "En una cafetería, un hotel o un aeropuerto cualquiera puede estar en la misma red. Si aun así usa Safeer Link allí, sigue protegido: un dispositivo ajeno no puede conectarse por su cuenta. El dispositivo que aloja Safeer Link muestra un número de 6 dígitos en su pantalla, y mientras no escriba ese número en el otro dispositivo, no se conecta nada ni se transfiere nada.",
      napHubNiZnan: "Todavía no se conoce ninguna conexión. Busca primero en tu red.",
      napIskanje: "No se pudo iniciar la búsqueda.",
      napSeznanitev: "No se pudo iniciar el emparejamiento.",
      napPovezava: "La conexión ha fallado. Comprueba que Safeer Link esté activado en el otro dispositivo.",
      napStranNiPrimerna: "Esta página no se puede enviar.",
      napSamoHttp: "Solo se pueden enviar direcciones http y https.",
      napPosiljanje: "El envío ha fallado. Inténtalo de nuevo.",
      napUkaz: "El comando ha fallado.",
      napZaznamki: "No se pudieron enviar los marcadores.",
      napSyncStart: "No se pudo iniciar la sincronización.",
      napSyncNastavi: "No se pudo configurar la sincronización.",
      napZdruzevanje: "No se pudo terminar de combinar los marcadores.",
      napHubNeTece: "Safeer Link no está activado aquí.",
      napHubNiZagnan: "No se pudo activar Safeer Link.",
      napHubNiUstavljen: "No se pudo desactivar Safeer Link.",
      napPrijavaPotekla: "La solicitud ya no existe o ha caducado.",
      napTvJeZaslon: "El televisor es una pantalla; no envía.",
      napTvNeUpravlja: "El televisor no controla otras pantallas.",
      napSyncTvNiNaVoljo: "La sincronización de marcadores todavía no está disponible en el televisor.",
      preverjam: "Comprobando …",
      zapri: "Cerrar",
      povezano: "Conectado a tu Safeer Link de casa",
      cakaNaPotrditev: "Esperando tu aprobación",
      niVklopljen: "Sin conexión",
      brezHubaNaslov: "Safeer Link todavía no está configurado",
      brezHubaOpis: "Safeer Link conecta los dispositivos de tu casa: teléfono, ordenador y televisor. Envía una página, texto, un archivo o tu pantalla de uno a otro, sin nube y sin cuenta. Empieza en cualquier dispositivo (este mismo sirve); los demás simplemente se unen.",
      brezHubaPomirilo: "Safeer OS también funciona sin dispositivos conectados. Puedes conectarlos en cualquier momento.",
      poisci: "Buscar en mi red",
      kakoDobim: "Cómo activo esto",
      iscem: "Buscando …",
      niNajden: "No lo he encontrado en esta red. Comprueba que Safeer Link esté funcionando en alguno de tus dispositivos e inténtalo de nuevo.",
      povežiNaslov: "Conectar este dispositivo",
      hubNajdenNa: "En tu red, Safeer Link está activado en",
      zakajPotrditi: "Aprueba la conexión una vez; después podréis intercambiar páginas, textos, archivos y pantallas.",
      potrdiKodo: "Aprueba este código en el dispositivo donde funciona Safeer Link:",
      kodaVelja: "El código es válido durante 5 minutos.",
      poveziSSafeerLink: "Conectar con Safeer Link",
      cakamNaPotrditev: "Esperando la aprobación …",
      niPotrjeno: "El código no se aprobó. Inténtalo de nuevo.",
      posljiStran: "Enviar esta página",
      odprtoVBrskalniku: "Abrir en el navegador",
      domacaStran: "Página de inicio: no se puede enviar",
      predvajaSeNa: "Reproduciéndose en",
      nazaj10: "10 s",
      pavza: "Pausa",
      predvajaj: "Reproducir",
      naprej10: "10 s",
      povezaneNaprave: "Dispositivos conectados",
      osvezi: "Actualizar",
      povezujem: "Conectando …",
      taNaprava: "Este dispositivo",
      povezanaZLinkom: "Conectado a Safeer Link",
      domace: "Conexión de casa",
      zaslon: "Pantalla",
      televizor: "Televisor",
      posljiNaZaslon: "Enviar a esta pantalla",
      posljiNaNapravo: "Enviar a este dispositivo",
      poslji: "Enviar",
      povezan: "Conectado",
      brezZaslonov: "Todavía no hay ningún otro dispositivo conectado. Abre Safeer Link en él y escribe el código que muestra este dispositivo.",
      poslanoNa: "Enviado a {ime}.",
      niDosegljiv: "Ahora mismo no se puede llegar a {ime}. Comprueba que esté encendido e inténtalo de nuevo.",
      neMorePoslati: "Esta página no se puede enviar. Abre un sitio web e inténtalo de nuevo.",
      povezaveNi: "No hay conexión con Safeer Link. Inténtalo de nuevo.",
      pozabiNapravo: "Olvidar este dispositivo",
      pozabiPotrdi: "¿Seguro? Toca una vez más: este dispositivo se desconectará.",
      pozabljeno: "El dispositivo está desconectado. Puedes volver a conectarlo cuando quieras.",
      sinhronizacija: "Sincronización",
      syncOpis: "Tus marcadores viajan entre tus dispositivos a través de tu Safeer Link de casa. Nada va a la nube.",
      mapeNaslov: "Archivos para el televisor",
      mapeOpis: "Safeer OS en el televisor ve las carpetas que elijas aquí: películas, música y fotos se reproducen directamente desde este ordenador, solo en tu red doméstica.",
      mapeDodaj: "Añadir carpeta",
      mapePrazno: "Ninguna carpeta seleccionada. El televisor no ve nada.",
      mapeOdstrani: "Quitar",
      mapeStandardne: "Compartir Vídeos, Música e Imágenes",
      syncPrivzeto: "La sincronización empieza cuando la confirmes; hasta entonces no se envía nada.",
      zaznamki: "Marcadores",
      syncVklopljena: "Activada",
      syncIzklopljena: "Desactivada",
      syncPotrdi: "Confirmar",
      syncVklopljenaOpis: "Activada: {n} marcadores en este dispositivo",
      syncNiNaVoljo: "Todavía no disponible en este dispositivo",
      syncVprasanje: "Tus {n} marcadores se enviarán a todos tus dispositivos. Toca una vez más para confirmar.",
      syncPovabilo: "Toca para activar. Hasta entonces no se envía nada.",
      syncVklapljam: "Activando …",
      syncIzklapljam: "Desactivando …",
      syncTece: "La sincronización funciona en segundo plano.",
      syncPrejeto: "Recibidos: {n} marcadores nuevos.",
      syncUgasnjena: "La sincronización está desactivada. No se envía nada.",
      nastavitve: "Ajustes",
      nastavitveOpis: "Aspecto, buscador, protecciones",
      filtri: "Listas de filtros",
      filtriOpis: "Las mismas protecciones en todos los dispositivos",
      kmalu: "Pronto",
      tezava: "Algo ha salido mal. Inténtalo de nuevo.",
      preseljenNaslov: "Safeer Link tiene una dirección nueva",
      preseljenOpis: "Se anuncia desde una dirección distinta a la anterior, normalmente porque el router le ha dado una nueva. Confirma que este es tu Safeer Link.",
      daPovezi: "Sí, conectar",
      preverjamNaslov: "Conectando con la nueva dirección …"
    },
    fr: {
      poisciDrugega: "Chercher un autre Safeer Link",
      vnesiKodoOpis: "Un nombre à 6 chiffres est apparu sur l'appareil où tourne Safeer Link. Saisissez-le ici.",
      povezi: "Connecter",
      preverjamKodo: "Vérification du code …",
      napNapacnaKoda: "Ce code n'est pas correct. Réessayez.",
      napPrevecPoskusov: "Trop de tentatives. Recommencez : vous obtiendrez un nouveau code.",
      napPrijavaPotekla: "Le code a expiré. Recommencez.",
      napNapravaNiZnana: "Safeer Link ne connaît plus cet appareil (l’hôte a été réinitialisé ou l’a retiré). Reconnecte-le avec un code.",
      prijavaCakaKodo: "Saisissez sur cet appareil le nombre affiché ici",
      javniWifiNaslov: "Sur les réseaux publics, nous conseillons de désactiver Safeer Link",
      javniWifiOpis: "Dans un café, un hôtel ou un aéroport, n'importe qui peut être sur le même réseau. Si vous utilisez quand même Safeer Link, vous restez protégé : un appareil inconnu ne peut pas se connecter tout seul. L'appareil qui héberge Safeer Link affiche un nombre à 6 chiffres à l'écran, et tant que vous ne saisissez pas ce nombre sur l'autre appareil, rien ne se connecte et rien n'est transféré.",
      napHubNiZnan: "Aucune connexion n’est encore connue. Cherche d’abord sur ton réseau.",
      napIskanje: "La recherche n\'a pas pu démarrer.",
      napSeznanitev: "L\'association n\'a pas pu démarrer.",
      napPovezava: "La connexion a échoué. Vérifie que Safeer Link est activé sur l’autre appareil.",
      napStranNiPrimerna: "Cette page ne peut pas être envoyée.",
      napSamoHttp: "Seules les adresses http et https peuvent être envoyées.",
      napPosiljanje: "L\'envoi a échoué. Réessaie.",
      napUkaz: "La commande a échoué.",
      napZaznamki: "Les favoris n\'ont pas pu être envoyés.",
      napSyncStart: "La synchronisation n\'a pas pu démarrer.",
      napSyncNastavi: "La synchronisation n\'a pas pu être configurée.",
      napZdruzevanje: "La fusion des favoris n\'a pas pu être terminée.",
      napHubNeTece: "Safeer Link n’est pas activé ici.",
      napHubNiZagnan: "Safeer Link n’a pas pu être activé.",
      napHubNiUstavljen: "Safeer Link n’a pas pu être désactivé.",
      napPrijavaPotekla: "La demande n\'existe plus ou a expiré.",
      napTvJeZaslon: "Le téléviseur est un écran ; il n\'envoie pas.",
      napTvNeUpravlja: "Le téléviseur ne contrôle pas les autres écrans.",
      napSyncTvNiNaVoljo: "La synchronisation des favoris n\'est pas encore disponible sur le téléviseur.",
      preverjam: "Vérification …",
      zapri: "Fermer",
      povezano: "Connecté à ton Safeer Link à la maison",
      cakaNaPotrditev: "En attente de ton approbation",
      niVklopljen: "Non connecté",
      brezHubaNaslov: "Safeer Link n\'est pas encore configuré",
      brezHubaOpis: "Safeer Link relie les appareils de ta maison — téléphone, ordinateur et téléviseur. Envoie une page, un texte, un fichier ou ton écran de l’un à l’autre, sans cloud et sans compte. Commence sur n’importe quel appareil (celui-ci convient) ; les autres se joignent simplement.",
      brezHubaPomirilo: "Safeer OS fonctionne aussi sans appareils connectés. Tu peux les connecter à tout moment.",
      poisci: "Chercher sur mon réseau",
      kakoDobim: "Comment activer cela",
      iscem: "Recherche …",
      niNajden: "Je ne l\'ai pas trouvé sur ce réseau. Vérifie que Safeer Link fonctionne sur un de tes appareils et réessaie.",
      povežiNaslov: "Connecter cet appareil",
      hubNajdenNa: "Sur ton réseau, Safeer Link est activé sur",
      zakajPotrditi: "Approuve la connexion une fois — ensuite vous pourrez échanger pages, textes, fichiers et écrans.",
      potrdiKodo: "Approuve ce code sur l\'appareil où fonctionne Safeer Link :",
      kodaVelja: "Le code est valable 5 minutes.",
      poveziSSafeerLink: "Se connecter à Safeer Link",
      cakamNaPotrditev: "En attente de l\'approbation …",
      niPotrjeno: "Le code n\'a pas été approuvé. Réessaie.",
      posljiStran: "Envoyer cette page",
      odprtoVBrskalniku: "Ouvrir dans le navigateur",
      domacaStran: "Page d\'accueil — ne peut pas être envoyée",
      predvajaSeNa: "Lecture sur",
      nazaj10: "10 s",
      pavza: "Pause",
      predvajaj: "Lecture",
      naprej10: "10 s",
      povezaneNaprave: "Appareils connectés",
      osvezi: "Actualiser",
      povezujem: "Connexion …",
      taNaprava: "Cet appareil",
      povezanaZLinkom: "Connecté à Safeer Link",
      domace: "Connexion maison",
      zaslon: "Écran",
      televizor: "Téléviseur",
      posljiNaZaslon: "Envoyer vers cet écran",
      posljiNaNapravo: "Envoyer vers cet appareil",
      poslji: "Envoyer",
      povezan: "Connecté",
      brezZaslonov: "Aucun autre appareil n’est encore connecté. Ouvre Safeer Link dessus et saisis le code affiché par cet appareil.",
      poslanoNa: "Envoyé vers {ime}.",
      niDosegljiv: "{ime} est injoignable pour le moment. Vérifie qu\'il est allumé et réessaie.",
      neMorePoslati: "Cette page ne peut pas être envoyée. Ouvre un site web et réessaie.",
      povezaveNi: "Il n\'y a pas de connexion à Safeer Link. Réessaie.",
      pozabiNapravo: "Oublier cet appareil",
      pozabiPotrdi: "Sûr ? Appuie encore une fois — cet appareil sera déconnecté.",
      pozabljeno: "L\'appareil est déconnecté. Tu peux le reconnecter quand tu veux.",
      sinhronizacija: "Synchronisation",
      syncOpis: "Tes favoris circulent entre tes appareils via ton Safeer Link à la maison. Rien ne part vers le cloud.",
      mapeNaslov: "Fichiers pour le téléviseur",
      mapeOpis: "Safeer OS sur le téléviseur voit les dossiers choisis ici : films, musique et photos se lisent directement depuis cet ordinateur, uniquement sur le réseau domestique.",
      mapeDodaj: "Ajouter un dossier",
      mapePrazno: "Aucun dossier choisi. Le téléviseur ne voit rien.",
      mapeOdstrani: "Retirer",
      mapeStandardne: "Partager Vidéos, Musique et Images",
      syncPrivzeto: "La synchronisation démarre dès que tu la confirmes — jusque-là rien n\'est envoyé.",
      zaznamki: "Favoris",
      syncVklopljena: "Activée",
      syncIzklopljena: "Désactivée",
      syncPotrdi: "Confirmer",
      syncVklopljenaOpis: "Activée — {n} favoris sur cet appareil",
      syncNiNaVoljo: "Pas encore disponible sur cet appareil",
      syncVprasanje: "Tes {n} favoris seront envoyés à tous tes appareils. Appuie encore une fois pour confirmer.",
      syncPovabilo: "Appuie pour activer. Jusque-là rien n\'est envoyé.",
      syncVklapljam: "Activation …",
      syncIzklapljam: "Désactivation …",
      syncTece: "La synchronisation fonctionne en arrière-plan.",
      syncPrejeto: "Reçus : {n} nouveaux favoris.",
      syncUgasnjena: "La synchronisation est désactivée. Rien n\'est envoyé.",
      nastavitve: "Paramètres",
      nastavitveOpis: "Apparence, moteur de recherche, protections",
      filtri: "Listes de filtres",
      filtriOpis: "Les mêmes protections sur chaque appareil",
      kmalu: "Bientôt",
      tezava: "Quelque chose a mal tourné. Réessaie.",
      preseljenNaslov: "Safeer Link a une nouvelle adresse",
      preseljenOpis: "Il s\'annonce depuis une adresse différente — le plus souvent parce que le routeur lui en a donné une nouvelle. Confirme que c\'est bien ton Safeer Link.",
      daPovezi: "Oui, connecter",
      preverjamNaslov: "Connexion à la nouvelle adresse …"
    },
    it: {
      poisciDrugega: "Cerca un altro Safeer Link",
      vnesiKodoOpis: "Sul dispositivo con Safeer Link è comparso un numero di 6 cifre. Digitalo qui.",
      povezi: "Collega",
      preverjamKodo: "Verifico il codice …",
      napNapacnaKoda: "Il codice non è corretto. Riprova.",
      napPrevecPoskusov: "Troppi tentativi. Ricomincia: otterrai un nuovo codice.",
      napPrijavaPotekla: "Il codice è scaduto. Ricomincia.",
      napNapravaNiZnana: "Safeer Link non conosce più questo dispositivo (l’host è stato ripristinato o l’ha rimosso). Collegalo di nuovo con un codice.",
      prijavaCakaKodo: "Digita su quel dispositivo il numero che vedi qui",
      javniWifiNaslov: "Sulle reti pubbliche consigliamo di spegnere Safeer Link",
      javniWifiOpis: "Al bar, in hotel o in aeroporto chiunque può essere sulla stessa rete. Se usi comunque Safeer Link, resti protetto: un dispositivo estraneo non può collegarsi da solo. Il dispositivo che ospita Safeer Link mostra sullo schermo un numero di 6 cifre e, finché non digiti quel numero sull'altro dispositivo, non si collega nulla e non viene trasferito nulla.",
      napHubNiZnan: "Nessuna connessione è ancora nota. Cerca prima nella tua rete.",
      napIskanje: "Non è stato possibile avviare la ricerca.",
      napSeznanitev: "Non è stato possibile avviare l\'associazione.",
      napPovezava: "La connessione non è riuscita. Controlla che Safeer Link sia acceso sull’altro dispositivo.",
      napStranNiPrimerna: "Questa pagina non può essere inviata.",
      napSamoHttp: "Si possono inviare solo indirizzi http e https.",
      napPosiljanje: "Invio non riuscito. Riprova.",
      napUkaz: "Il comando non è riuscito.",
      napZaznamki: "Non è stato possibile inviare i preferiti.",
      napSyncStart: "Non è stato possibile avviare la sincronizzazione.",
      napSyncNastavi: "Non è stato possibile impostare la sincronizzazione.",
      napZdruzevanje: "Non è stato possibile completare l\'unione dei preferiti.",
      napHubNeTece: "Safeer Link qui non è acceso.",
      napHubNiZagnan: "Non è stato possibile accendere Safeer Link.",
      napHubNiUstavljen: "Non è stato possibile spegnere Safeer Link.",
      napPrijavaPotekla: "La richiesta non esiste più o è scaduta.",
      napTvJeZaslon: "Il televisore è uno schermo; non invia.",
      napTvNeUpravlja: "Il televisore non controlla altri schermi.",
      napSyncTvNiNaVoljo: "La sincronizzazione dei preferiti non è ancora disponibile sul televisore.",
      preverjam: "Controllo …",
      zapri: "Chiudi",
      povezano: "Connesso al tuo Safeer Link di casa",
      cakaNaPotrditev: "In attesa della tua approvazione",
      niVklopljen: "Non connesso",
      brezHubaNaslov: "Safeer Link non è ancora configurato",
      brezHubaOpis: "Safeer Link collega i dispositivi di casa tua: telefono, computer e televisore. Invia una pagina, un testo, un file o il tuo schermo da uno all’altro, senza cloud e senza account. Inizia su un dispositivo qualsiasi (va bene anche questo); gli altri si uniscono e basta.",
      brezHubaPomirilo: "Safeer OS funziona anche senza dispositivi collegati. Puoi collegarli in qualsiasi momento.",
      poisci: "Cerca nella mia rete",
      kakoDobim: "Come lo attivo",
      iscem: "Ricerca …",
      niNajden: "Non l\'ho trovato in questa rete. Controlla che Safeer Link sia in esecuzione su uno dei tuoi dispositivi e riprova.",
      povežiNaslov: "Collega questo dispositivo",
      hubNajdenNa: "Nella tua rete Safeer Link è acceso su",
      zakajPotrditi: "Approva la connessione una volta: poi potrete scambiarvi pagine, testi, file e schermi.",
      potrdiKodo: "Approva questo codice sul dispositivo su cui è in esecuzione Safeer Link:",
      kodaVelja: "Il codice è valido per 5 minuti.",
      poveziSSafeerLink: "Collegati a Safeer Link",
      cakamNaPotrditev: "In attesa dell\'approvazione …",
      niPotrjeno: "Il codice non è stato approvato. Riprova.",
      posljiStran: "Invia questa pagina",
      odprtoVBrskalniku: "Apri nel browser",
      domacaStran: "Pagina iniziale: non può essere inviata",
      predvajaSeNa: "In riproduzione su",
      nazaj10: "10 s",
      pavza: "Pausa",
      predvajaj: "Riproduci",
      naprej10: "10 s",
      povezaneNaprave: "Dispositivi collegati",
      osvezi: "Aggiorna",
      povezujem: "Connessione …",
      taNaprava: "Questo dispositivo",
      povezanaZLinkom: "Connesso a Safeer Link",
      domace: "Connessione di casa",
      zaslon: "Schermo",
      televizor: "Televisore",
      posljiNaZaslon: "Invia a questo schermo",
      posljiNaNapravo: "Invia a questo dispositivo",
      poslji: "Invia",
      povezan: "Connesso",
      brezZaslonov: "Nessun altro dispositivo è ancora collegato. Apri Safeer Link su di esso e digita il codice mostrato da questo dispositivo.",
      poslanoNa: "Inviato a {ime}.",
      niDosegljiv: "{ime} non è raggiungibile in questo momento. Controlla che sia acceso e riprova.",
      neMorePoslati: "Questa pagina non può essere inviata. Apri un sito web e riprova.",
      povezaveNi: "Non c\'è connessione a Safeer Link. Riprova.",
      pozabiNapravo: "Dimentica questo dispositivo",
      pozabiPotrdi: "Sicuro? Tocca ancora una volta: questo dispositivo verrà scollegato.",
      pozabljeno: "Il dispositivo è scollegato. Puoi ricollegarlo quando vuoi.",
      sinhronizacija: "Sincronizzazione",
      syncOpis: "I tuoi preferiti viaggiano tra i tuoi dispositivi attraverso il Safeer Link di casa. Niente finisce nel cloud.",
      mapeNaslov: "File per il televisore",
      mapeOpis: "Safeer OS sul televisore vede le cartelle scelte qui: film, musica e foto si riproducono direttamente da questo computer, solo nella rete di casa.",
      mapeDodaj: "Aggiungi cartella",
      mapePrazno: "Nessuna cartella scelta. Il televisore non vede nulla.",
      mapeOdstrani: "Rimuovi",
      mapeStandardne: "Condividi Video, Musica e Immagini",
      syncPrivzeto: "La sincronizzazione parte quando la confermi: fino ad allora non viene inviato nulla.",
      zaznamki: "Preferiti",
      syncVklopljena: "Attiva",
      syncIzklopljena: "Disattivata",
      syncPotrdi: "Conferma",
      syncVklopljenaOpis: "Attiva — {n} preferiti su questo dispositivo",
      syncNiNaVoljo: "Non ancora disponibile su questo dispositivo",
      syncVprasanje: "I tuoi {n} preferiti verranno inviati a tutti i tuoi dispositivi. Tocca ancora una volta per confermare.",
      syncPovabilo: "Tocca per attivare. Fino ad allora non viene inviato nulla.",
      syncVklapljam: "Attivazione …",
      syncIzklapljam: "Disattivazione …",
      syncTece: "La sincronizzazione funziona in background.",
      syncPrejeto: "Ricevuti: {n} nuovi preferiti.",
      syncUgasnjena: "La sincronizzazione è disattivata. Non viene inviato nulla.",
      nastavitve: "Impostazioni",
      nastavitveOpis: "Aspetto, motore di ricerca, protezioni",
      filtri: "Liste di filtri",
      filtriOpis: "Le stesse protezioni su ogni dispositivo",
      kmalu: "Presto",
      tezava: "Qualcosa è andato storto. Riprova.",
      preseljenNaslov: "Safeer Link ha un nuovo indirizzo",
      preseljenOpis: "Si annuncia da un indirizzo diverso da prima, di solito perché il router gliene ha assegnato uno nuovo. Conferma che questo è il tuo Safeer Link.",
      daPovezi: "Sì, collega",
      preverjamNaslov: "Connessione al nuovo indirizzo …"
    }
  };

  /**
   * Stabilne kode napak iz mostu. Most poslje kodo in besedilo; stran pokaze prevod
   * kode, besedilo pa uporabi le, ce kode ne pozna (starejsi most, nova koda).
   */
  var NAPAKE = {
    hub_ni_znan: "napHubNiZnan",
    iskanje_ni_steklo: "napIskanje",
    seznanitev_ni_stekla: "napSeznanitev",
    povezava_ni_uspela: "napPovezava",
    stran_ni_primerna: "napStranNiPrimerna",
    samo_http: "napSamoHttp",
    posiljanje_ni_uspelo: "napPosiljanje",
    ukaz_ni_uspel: "napUkaz",
    zaznamki_niso_poslani: "napZaznamki",
    sync_ni_stekla: "napSyncStart",
    sync_ni_nastavljena: "napSyncNastavi",
    zdruzevanje_ni_koncano: "napZdruzevanje",
    hub_ne_tece: "napHubNeTece",
    hub_ni_zagnan: "napHubNiZagnan",
    hub_ni_ustavljen: "napHubNiUstavljen",
    prijava_potekla: "napPrijavaPotekla",
    naprava_ni_znana: "napNapravaNiZnana",
    tv_je_zaslon: "napTvJeZaslon",
    tv_ne_upravlja: "napTvNeUpravlja",
    sync_tv_ni_na_voljo: "napSyncTvNiNaVoljo",
    preimenovanje_ni_uspelo: "napPreimenovanje"
  };

  var BESEDILA_DELJENJE = {
    sl: {
      napDovoljenje: "Deljenje zaslona ni bilo dovoljeno.",
      zasedenoKratko: "Zasedeno",
      zasedenoDeli: "Zasedeno — deli {ime}",
      napZasedena: "Z napravo trenutno deli {ime}. Počakaj, da konča.",
      preimenuj: "Preimenuj",
      shraniIme: "Shrani ime",
      vnesiIme: "Novo ime naprave …",
      preimenovano: "Ime je shranjeno.",
      napPreimenovanje: "Imena ni bilo mogoče shraniti.",
      napOdtis: "Datoteka ni prišla nepoškodovana. Poskusi znova.",
      zasedenaCakaj: "Ta naprava je zasedena; deljenje bo mogoče, ko {ime} konča.",
      deliZ: "Deli z: {ime}",
      izberiVsebino: "Kaj želiš deliti s to napravo?",
      deliZaslon: "Zaslon",
      odpriSafeerOs: "Safeer OS na televizorju",
      odpriBrskalnik: "Safeer brskalnik",
      odpiramNaZaslonu: "Odpiram {ime} na napravi {naprava} …",
      deliDatoteka: "Datoteka",
      deliBesedilo: "Besedilo",
      posljiNaNapravo: "Pošlji na napravo",
      vnesiBesedilo: "Vpiši besedilo …",
      zaslonOpis: "Na izbrani napravi se bo prikazoval zaslon te naprave, dokler deljenja ne prekineš. Sistem te bo najprej vprašal za dovoljenje.",
      datotekaOpis: "Odprlo se bo okno, v katerem poiščeš datoteko na tej napravi. Prispela bo v mapo prenosov izbrane naprave.",
      besediloOpis: "Besedilo se pokaže na izbrani napravi; povezava se da odpreti z enim dotikom.",
      prekiniZaslon: "Prekini deljenje zaslona",
      zaslonTeceNa: "Zaslon se prikazuje na {ime}",
      zaslonZaganjam: "Začenjam deljenje zaslona …",
      zaslonKoncano: "Deljenje zaslona je končano.",
      posiljam: "Pošiljam …",
      posiljamOdstotek: "Pošiljam {ime} … {n} %",
      poslanoNapravi: "Poslano na {ime}.",
      napDeljenje: "Ni uspelo: {napaka}",
      prejetoBesedilo: "Prejeto sporočilo z naprave {ime}",
      prejetaStran: "Stran z naprave {ime} se odpira",
      prejetaDatoteka: "Prejeta datoteka {ime} ({mapa})",
      prejetZaslon: "{ime} deli zaslon s to napravo",
      naprava: "Naprava",
      deliDotik: "Dotakni se za deljenje",
      deliKlik: "Klikni za deljenje in daljinec",
      dodajNaslov: "Dodaj telefon ali tablico",
      dodajKorak1: "Na telefonu odpri Safeer in v meniju izberi Safeer Link.",
      dodajKorak2: "Pritisni »Poveži s Safeer Link«.",
      dodajKorak3: "Na napravi {sredisce} se izpiše 6-mestna koda – prepiši jo v telefon.",
      dodajOpomba: "Koda se pokaže samo na središču: kdor ga ne vidi, se ne more povezati – tudi ne v javnem omrežju.",
      istaNaprava: "{ime} teče na tej napravi",
      daljinec: "Daljinec",
      ospredjeOpis: "Da se Safeer odpre sam, ko mu s telefona pošlješ stran ali ukaz, mu enkrat dovoli prekrivanje drugih aplikacij.",
      ospredjeDovoli: "Dovoli",
      zapriDeljenje: "Zapri"
    },
    en: {
      napDovoljenje: "Screen sharing was not allowed.",
      zasedenoKratko: "Busy",
      zasedenoDeli: "Busy — {ime} is sharing",
      napZasedena: "{ime} is currently sharing with this device. Wait until it finishes.",
      preimenuj: "Rename",
      shraniIme: "Save name",
      vnesiIme: "New device name …",
      preimenovano: "Name saved.",
      napPreimenovanje: "The name could not be saved.",
      napOdtis: "The file did not arrive intact. Try again.",
      zasedenaCakaj: "This device is busy; sharing will be possible once {ime} finishes.",
      deliZ: "Share with: {ime}",
      izberiVsebino: "What do you want to share with this device?",
      deliZaslon: "Screen",
      odpriSafeerOs: "Safeer OS on the TV",
      odpriBrskalnik: "Safeer browser",
      odpiramNaZaslonu: "Opening {ime} on {naprava} …",
      deliDatoteka: "File",
      deliBesedilo: "Text",
      posljiNaNapravo: "Send to device",
      vnesiBesedilo: "Type your text …",
      zaslonOpis: "The selected device will show this device's screen until you stop sharing. The system will ask for permission first.",
      datotekaOpis: "A window will open to pick a file on this device. It will arrive in the downloads folder of the selected device.",
      besediloOpis: "The text is shown on the selected device; a link can be opened with one tap.",
      prekiniZaslon: "Stop screen sharing",
      zaslonTeceNa: "Screen is shown on {ime}",
      zaslonZaganjam: "Starting screen sharing …",
      zaslonKoncano: "Screen sharing has ended.",
      posiljam: "Sending …",
      posiljamOdstotek: "Sending {ime} … {n} %",
      poslanoNapravi: "Sent to {ime}.",
      napDeljenje: "Failed: {napaka}",
      prejetoBesedilo: "Message received from {ime}",
      prejetaStran: "Opening a page from {ime}",
      prejetaDatoteka: "File received: {ime} ({mapa})",
      prejetZaslon: "{ime} is sharing its screen with this device",
      naprava: "Device",
      deliDotik: "Tap to share",
      deliKlik: "Click to share or use the remote",
      dodajNaslov: "Add a phone or tablet",
      dodajKorak1: "On the phone, open Safeer and choose Safeer Link in the menu.",
      dodajKorak2: "Tap “Connect to Safeer Link”.",
      dodajKorak3: "A 6-digit code appears on {sredisce} – type it into the phone.",
      dodajOpomba: "The code is shown only on the hub: whoever cannot see it cannot connect – not even on public Wi-Fi.",
      istaNaprava: "{ime} runs on this device",
      daljinec: "Remote control",
      ospredjeOpis: "So that Safeer opens by itself when your phone sends it a page or a command, allow it once to appear over other apps.",
      ospredjeDovoli: "Allow",
      zapriDeljenje: "Close"
    },
    de: {
      napDovoljenje: "Die Bildschirmfreigabe wurde nicht erlaubt.",
      zasedenoKratko: "Belegt",
      zasedenoDeli: "Belegt — {ime} teilt",
      napZasedena: "{ime} teilt gerade mit diesem Gerät. Warte, bis es fertig ist.",
      preimenuj: "Umbenennen",
      shraniIme: "Namen speichern",
      vnesiIme: "Neuer Gerätename …",
      preimenovano: "Name gespeichert.",
      napPreimenovanje: "Der Name konnte nicht gespeichert werden.",
      napOdtis: "Die Datei kam nicht unversehrt an. Versuche es erneut.",
      zasedenaCakaj: "Dieses Gerät ist belegt; Teilen ist möglich, sobald {ime} fertig ist.",
      deliZ: "Teilen mit: {ime}",
      izberiVsebino: "Was möchtest du mit diesem Gerät teilen?",
      deliZaslon: "Bildschirm",
      odpriSafeerOs: "Safeer OS auf dem Fernseher",
      odpriBrskalnik: "Safeer-Browser",
      odpiramNaZaslonu: "Öffne {ime} auf {naprava} …",
      deliDatoteka: "Datei",
      deliBesedilo: "Text",
      posljiNaNapravo: "An Gerät senden",
      vnesiBesedilo: "Text eingeben …",
      zaslonOpis: "Das gewählte Gerät zeigt den Bildschirm dieses Geräts, bis du die Freigabe beendest. Das System fragt zuerst um Erlaubnis.",
      datotekaOpis: "Es öffnet sich ein Fenster, in dem du eine Datei auf diesem Gerät auswählst. Sie landet im Download-Ordner des gewählten Geräts.",
      besediloOpis: "Der Text wird auf dem gewählten Gerät angezeigt; ein Link lässt sich mit einem Tipp öffnen.",
      prekiniZaslon: "Bildschirmfreigabe beenden",
      zaslonTeceNa: "Bildschirm wird auf {ime} angezeigt",
      zaslonZaganjam: "Bildschirmfreigabe wird gestartet …",
      zaslonKoncano: "Bildschirmfreigabe beendet.",
      posiljam: "Sende …",
      posiljamOdstotek: "Sende {ime} … {n} %",
      poslanoNapravi: "An {ime} gesendet.",
      napDeljenje: "Fehlgeschlagen: {napaka}",
      prejetoBesedilo: "Nachricht von {ime} erhalten",
      prejetaStran: "Seite von {ime} wird geöffnet",
      prejetaDatoteka: "Datei erhalten: {ime} ({mapa})",
      prejetZaslon: "{ime} teilt den Bildschirm mit diesem Gerät",
      naprava: "Gerät",
      deliDotik: "Zum Teilen antippen",
      deliKlik: "Klicken zum Teilen oder für die Fernbedienung",
      istaNaprava: "{ime} läuft auf diesem Gerät",
      daljinec: "Fernbedienung",
      ospredjeOpis: "Damit sich Safeer von selbst öffnet, wenn das Telefon eine Seite oder einen Befehl schickt, erlaube ihm einmal, über anderen Apps zu erscheinen.",
      ospredjeDovoli: "Erlauben",
      zapriDeljenje: "Schließen"
    },
    es: {
      napDovoljenje: "No se permitió compartir la pantalla.",
      zasedenoKratko: "Ocupado",
      zasedenoDeli: "Ocupado — {ime} está compartiendo",
      napZasedena: "{ime} está compartiendo con este dispositivo. Espera a que termine.",
      preimenuj: "Renombrar",
      shraniIme: "Guardar nombre",
      vnesiIme: "Nuevo nombre del dispositivo …",
      preimenovano: "Nombre guardado.",
      napPreimenovanje: "No se pudo guardar el nombre.",
      napOdtis: "El archivo no llegó intacto. Inténtalo de nuevo.",
      zasedenaCakaj: "Este dispositivo está ocupado; podrás compartir cuando {ime} termine.",
      deliZ: "Compartir con: {ime}",
      izberiVsebino: "¿Qué quieres compartir con este dispositivo?",
      deliZaslon: "Pantalla",
      odpriSafeerOs: "Safeer OS en el televisor",
      odpriBrskalnik: "Navegador Safeer",
      odpiramNaZaslonu: "Abriendo {ime} en {naprava} …",
      deliDatoteka: "Archivo",
      deliBesedilo: "Texto",
      posljiNaNapravo: "Enviar al dispositivo",
      vnesiBesedilo: "Escribe el texto …",
      zaslonOpis: "El dispositivo elegido mostrará la pantalla de este dispositivo hasta que detengas la compartición. El sistema pedirá permiso primero.",
      datotekaOpis: "Se abrirá una ventana para elegir un archivo de este dispositivo. Llegará a la carpeta de descargas del dispositivo elegido.",
      besediloOpis: "El texto se muestra en el dispositivo elegido; un enlace se abre con un toque.",
      prekiniZaslon: "Dejar de compartir pantalla",
      zaslonTeceNa: "La pantalla se muestra en {ime}",
      zaslonZaganjam: "Iniciando la compartición de pantalla …",
      zaslonKoncano: "La pantalla compartida ha terminado.",
      posiljam: "Enviando …",
      posiljamOdstotek: "Enviando {ime} … {n} %",
      poslanoNapravi: "Enviado a {ime}.",
      napDeljenje: "No se pudo: {napaka}",
      prejetoBesedilo: "Mensaje recibido de {ime}",
      prejetaStran: "Abriendo una página de {ime}",
      prejetaDatoteka: "Archivo recibido: {ime} ({mapa})",
      prejetZaslon: "{ime} comparte su pantalla con este dispositivo",
      naprava: "Dispositivo",
      deliDotik: "Toca para compartir",
      deliKlik: "Haz clic para compartir o usar el mando",
      istaNaprava: "{ime} funciona en este dispositivo",
      daljinec: "Mando a distancia",
      ospredjeOpis: "Para que Safeer se abra solo cuando el teléfono le envíe una página o un comando, permítele una vez aparecer sobre otras apps.",
      ospredjeDovoli: "Permitir",
      zapriDeljenje: "Cerrar"
    },
    fr: {
      napDovoljenje: "Le partage d’écran n’a pas été autorisé.",
      zasedenoKratko: "Occupé",
      zasedenoDeli: "Occupé — {ime} partage",
      napZasedena: "{ime} partage actuellement avec cet appareil. Attends qu’il ait fini.",
      preimenuj: "Renommer",
      shraniIme: "Enregistrer le nom",
      vnesiIme: "Nouveau nom de l’appareil …",
      preimenovano: "Nom enregistré.",
      napPreimenovanje: "Le nom n’a pas pu être enregistré.",
      napOdtis: "Le fichier n’est pas arrivé intact. Réessaie.",
      zasedenaCakaj: "Cet appareil est occupé ; le partage sera possible quand {ime} aura fini.",
      deliZ: "Partager avec : {ime}",
      izberiVsebino: "Que veux-tu partager avec cet appareil ?",
      deliZaslon: "Écran",
      odpriSafeerOs: "Safeer OS sur le téléviseur",
      odpriBrskalnik: "Navigateur Safeer",
      odpiramNaZaslonu: "Ouverture de {ime} sur {naprava} …",
      deliDatoteka: "Fichier",
      deliBesedilo: "Texte",
      posljiNaNapravo: "Envoyer à l’appareil",
      vnesiBesedilo: "Saisis le texte …",
      zaslonOpis: "L’appareil choisi affichera l’écran de cet appareil jusqu’à ce que tu arrêtes le partage. Le système demandera d’abord l’autorisation.",
      datotekaOpis: "Une fenêtre s’ouvrira pour choisir un fichier sur cet appareil. Il arrivera dans le dossier de téléchargements de l’appareil choisi.",
      besediloOpis: "Le texte s’affiche sur l’appareil choisi ; un lien s’ouvre d’une pression.",
      prekiniZaslon: "Arrêter le partage d’écran",
      zaslonTeceNa: "L’écran est affiché sur {ime}",
      zaslonZaganjam: "Démarrage du partage d’écran …",
      zaslonKoncano: "Le partage d’écran est terminé.",
      posiljam: "Envoi …",
      posiljamOdstotek: "Envoi de {ime} … {n} %",
      poslanoNapravi: "Envoyé à {ime}.",
      napDeljenje: "Échec : {napaka}",
      prejetoBesedilo: "Message reçu de {ime}",
      prejetaStran: "Ouverture d’une page de {ime}",
      prejetaDatoteka: "Fichier reçu : {ime} ({mapa})",
      prejetZaslon: "{ime} partage son écran avec cet appareil",
      naprava: "Appareil",
      deliDotik: "Toucher pour partager",
      deliKlik: "Cliquer pour partager ou utiliser la télécommande",
      istaNaprava: "{ime} fonctionne sur cet appareil",
      daljinec: "Télécommande",
      ospredjeOpis: "Pour que Safeer s'ouvre tout seul quand le téléphone lui envoie une page ou une commande, autorisez-le une fois à s'afficher par-dessus les autres applis.",
      ospredjeDovoli: "Autoriser",
      zapriDeljenje: "Fermer"
    },
    it: {
      napDovoljenje: "La condivisione dello schermo non è stata consentita.",
      zasedenoKratko: "Occupato",
      zasedenoDeli: "Occupato — {ime} sta condividendo",
      napZasedena: "{ime} sta condividendo con questo dispositivo. Aspetta che finisca.",
      preimenuj: "Rinomina",
      shraniIme: "Salva nome",
      vnesiIme: "Nuovo nome del dispositivo …",
      preimenovano: "Nome salvato.",
      napPreimenovanje: "Impossibile salvare il nome.",
      napOdtis: "Il file non è arrivato integro. Riprova.",
      zasedenaCakaj: "Questo dispositivo è occupato; potrai condividere quando {ime} avrà finito.",
      deliZ: "Condividi con: {ime}",
      izberiVsebino: "Cosa vuoi condividere con questo dispositivo?",
      deliZaslon: "Schermo",
      deliDatoteka: "File",
      deliBesedilo: "Testo",
      posljiNaNapravo: "Invia al dispositivo",
      vnesiBesedilo: "Scrivi il testo …",
      zaslonOpis: "Il dispositivo scelto mostrerà lo schermo di questo dispositivo finché non interrompi la condivisione. Il sistema chiederà prima il permesso.",
      datotekaOpis: "Si aprirà una finestra per scegliere un file su questo dispositivo. Arriverà nella cartella dei download del dispositivo scelto.",
      besediloOpis: "Il testo viene mostrato sul dispositivo scelto; un link si apre con un tocco.",
      prekiniZaslon: "Interrompi condivisione schermo",
      zaslonTeceNa: "Lo schermo è mostrato su {ime}",
      zaslonZaganjam: "Avvio della condivisione dello schermo …",
      zaslonKoncano: "La condivisione dello schermo è terminata.",
      posiljam: "Invio …",
      posiljamOdstotek: "Invio di {ime} … {n} %",
      poslanoNapravi: "Inviato a {ime}.",
      napDeljenje: "Non riuscito: {napaka}",
      prejetoBesedilo: "Messaggio ricevuto da {ime}",
      prejetaStran: "Apertura di una pagina da {ime}",
      prejetaDatoteka: "File ricevuto: {ime} ({mapa})",
      prejetZaslon: "{ime} condivide lo schermo con questo dispositivo",
      naprava: "Dispositivo",
      deliDotik: "Tocca per condividere",
      deliKlik: "Fai clic per condividere o usare il telecomando",
      istaNaprava: "{ime} è in esecuzione su questo dispositivo",
      odpriSafeerOs: "Safeer OS sul televisore",
      odpriBrskalnik: "Browser Safeer",
      odpiramNaZaslonu: "Apro {ime} su {naprava} …",
      daljinec: "Telecomando",
      ospredjeOpis: "Perché Safeer si apra da solo quando il telefono gli invia una pagina o un comando, consentigli una volta di apparire sopra le altre app.",
      ospredjeDovoli: "Consenti",
      zapriDeljenje: "Chiudi"
    }
  };
  for (var _jd in BESEDILA_DELJENJE) {
    if (!BESEDILA[_jd]) BESEDILA[_jd] = {};
    for (var _kd in BESEDILA_DELJENJE[_jd]) BESEDILA[_jd][_kd] = BESEDILA_DELJENJE[_jd][_kd];
  }

  // Prijavno okno (Safeer Control / Safeer OS na racunalniku).
  var BESEDILA_PRIJAVA = {
    sl: {
      prijavaNaslov: "Prijava",
      prijavaPodnaslov: "Poveži ta računalnik s svojimi napravami.",
      prijavaQrNaslov: "Skeniraj s telefonom",
      prijavaQrOpis: "Usmeri kamero telefona ali tablice, ki je že v Safeer Linku, v kodo in potrdi na telefonu.",
      prijavaQrPripravljam: "Pripravljam kodo …",
      prijavaQrOsvezi: "Koda se sama obnavlja.",
      prijavaNiHuba: "V domačem omrežju ni Safeer Linka. Vklopi ga na televizorju ali tablici.",
      prijavaPoisci: "Poišči znova",
      prijavaHubStar: "Safeer na televizorju je za kodo QR prestar. Uporabi 6-mestno kodo ali ga posodobi.",
      prijavaPrevec: "Preveč hkratnih prijav. Poskusi čez minuto.",
      prijavaBrezQr: "Kode QR tu ni mogoče narisati. Uporabi 6-mestno kodo.",
      prijavaAli: "ali",
      prijavaLokalnaKodaNaslov: "Koda tega računalnika",
      prijavaLokalnaKodaOpis: "To 6-mestno kodo vpiši na televizorju ali v Safeer aplikaciji na telefonu.",
      prijavaNovaKoda: "Nova koda",
      prijavaNazajOs: "Safeer OS Domov",
      prijavaKodaNaslov: "Vpiši 6-mestno kodo",
      prijavaKodaOpis: "Klikni v polje – koda se pokaže na televizorju ali tablici, kjer teče Safeer Link.",
      prijavaKodaNaSredisce: "Koda je zdaj na zaslonu naprave s Safeer Linkom. Prepiši jo sem.",
      prijavaKodaSestMest: "Koda ima 6 številk.",
      prijavaGumb: "Prijava",
      prijavaPreverjam: "Preverjam …",
      prijavaBrez: "Nadaljuj brez povezave naprav",
      prijavaOsSeNastaja: "Safeer OS za računalnik še nastaja. Ko bo nameščen, se odpre od tu.",
      prijavaZaupaj: "Zaupaj temu računalniku",
      prijavaZaupajOpis: "Povezava bo potrebna samo enkrat. Izberi le na svojem računalniku – sicer se ob naslednji prijavi v računalnik znova povežeš.",
      prijavaUspela: "Prijavljeno. Povezujem …",
      prijavaZnovaZazeni: "Safeer OS je treba znova zagnati, da naloži posodobitev: zapri ga v pladnju ali se odjavi in prijavi.",
      brezPovezaveNaslov: "Naprave niso povezane",
      brezPovezaveOpis: "Safeer OS deluje na tem računalniku. Telefon, tablico ali televizor povežeš, kadar želiš.",
      poveziNaprave: "Poveži naprave",
      odpriSafeerOs: "Odpri Safeer OS"
    },
    en: {
      prijavaNaslov: "Sign in",
      prijavaPodnaslov: "Connect this computer to your devices.",
      prijavaQrNaslov: "Scan with your phone",
      prijavaQrOpis: "Point the camera of a phone or tablet that is already in Safeer Link at the code and confirm on the phone.",
      prijavaQrPripravljam: "Preparing the code …",
      prijavaQrOsvezi: "The code refreshes by itself.",
      prijavaNiHuba: "There is no Safeer Link on your home network. Turn it on on the TV or tablet.",
      prijavaPoisci: "Search again",
      prijavaHubStar: "Safeer on the TV is too old for the QR code. Use the 6-digit code or update it.",
      prijavaPrevec: "Too many sign-ins at once. Try again in a minute.",
      prijavaBrezQr: "The QR code can't be drawn here. Use the 6-digit code.",
      prijavaAli: "or",
      prijavaLokalnaKodaNaslov: "This computer's code",
      prijavaLokalnaKodaOpis: "Enter this 6-digit code on your TV or phone in the Safeer app.",
      prijavaNovaKoda: "New code",
      prijavaNazajOs: "Safeer OS Home",
      prijavaKodaNaslov: "Enter the 6-digit code",
      prijavaKodaOpis: "Click the field – the code appears on the TV or tablet running Safeer Link.",
      prijavaKodaNaSredisce: "The code is now on the screen of the Safeer Link device. Type it here.",
      prijavaKodaSestMest: "The code has 6 digits.",
      prijavaGumb: "Sign in",
      prijavaPreverjam: "Checking …",
      prijavaBrez: "Continue without connecting devices",
      prijavaOsSeNastaja: "Safeer OS for computers is still being built. Once installed, it opens from here.",
      prijavaZaupaj: "Trust this computer",
      prijavaZaupajOpis: "You'll only need to connect once. Choose this only on your own computer – otherwise you'll connect again next time you sign in to the computer.",
      prijavaUspela: "Signed in. Connecting …",
      prijavaZnovaZazeni: "Restart Safeer OS to load the update: quit it from the tray, or log out and back in.",
      brezPovezaveNaslov: "No devices connected",
      brezPovezaveOpis: "Safeer OS works on this computer. Connect your phone, tablet or TV whenever you like.",
      poveziNaprave: "Connect devices",
      odpriSafeerOs: "Open Safeer OS"
    },
    de: {
      prijavaNaslov: "Anmelden",
      prijavaPodnaslov: "Verbinde diesen Computer mit deinen Geräten.",
      prijavaQrNaslov: "Mit dem Handy scannen",
      prijavaQrOpis: "Richte die Kamera eines Handys oder Tablets, das schon in Safeer Link ist, auf den Code und bestätige am Handy.",
      prijavaQrPripravljam: "Code wird vorbereitet …",
      prijavaQrOsvezi: "Der Code erneuert sich von selbst.",
      prijavaNiHuba: "Kein Safeer Link im Heimnetz. Schalte ihn am Fernseher oder Tablet ein.",
      prijavaPoisci: "Erneut suchen",
      prijavaHubStar: "Safeer auf dem Fernseher ist für den QR-Code zu alt. Nutze den 6-stelligen Code oder aktualisiere ihn.",
      prijavaPrevec: "Zu viele gleichzeitige Anmeldungen. Versuche es in einer Minute erneut.",
      prijavaBrezQr: "Der QR-Code kann hier nicht angezeigt werden. Nutze den 6-stelligen Code.",
      prijavaAli: "oder",
      prijavaLokalnaKodaNaslov: "Code dieses Computers",
      prijavaLokalnaKodaOpis: "Gib diesen 6-stelligen Code am Fernseher oder in der Safeer-App auf dem Handy ein.",
      prijavaNovaKoda: "Neuer Code",
      prijavaNazajOs: "Safeer OS Startseite",
      prijavaKodaNaslov: "6-stelligen Code eingeben",
      prijavaKodaOpis: "Klicke ins Feld – der Code erscheint auf dem Fernseher oder Tablet mit Safeer Link.",
      prijavaKodaNaSredisce: "Der Code steht jetzt auf dem Bildschirm des Safeer-Link-Geräts. Gib ihn hier ein.",
      prijavaKodaSestMest: "Der Code hat 6 Ziffern.",
      prijavaGumb: "Anmelden",
      prijavaPreverjam: "Wird geprüft …",
      prijavaBrez: "Ohne Geräteverbindung fortfahren",
      prijavaOsSeNastaja: "Safeer OS für Computer entsteht noch. Sobald es installiert ist, öffnet es sich von hier.",
      prijavaZaupaj: "Diesem Computer vertrauen",
      prijavaZaupajOpis: "Die Verbindung ist nur einmal nötig. Wähle das nur auf deinem eigenen Computer – sonst verbindest du dich bei der nächsten Anmeldung am Computer erneut.",
      prijavaUspela: "Angemeldet. Verbinde …",
      prijavaZnovaZazeni: "Starte Safeer OS neu, um das Update zu laden: im Infobereich beenden oder ab- und wieder anmelden.",
      brezPovezaveNaslov: "Keine Geräte verbunden",
      brezPovezaveOpis: "Safeer OS läuft auf diesem Computer. Verbinde Handy, Tablet oder Fernseher, wann immer du willst.",
      poveziNaprave: "Geräte verbinden",
      odpriSafeerOs: "Safeer OS öffnen"
    },
    es: {
      prijavaNaslov: "Iniciar sesión",
      prijavaPodnaslov: "Conecta este ordenador con tus dispositivos.",
      prijavaQrNaslov: "Escanea con el móvil",
      prijavaQrOpis: "Apunta al código con la cámara de un móvil o tableta que ya esté en Safeer Link y confirma en el móvil.",
      prijavaQrPripravljam: "Preparando el código …",
      prijavaQrOsvezi: "El código se renueva solo.",
      prijavaNiHuba: "No hay Safeer Link en tu red doméstica. Actívalo en el televisor o la tableta.",
      prijavaPoisci: "Buscar de nuevo",
      prijavaHubStar: "Safeer en el televisor es demasiado antiguo para el código QR. Usa el código de 6 cifras o actualízalo.",
      prijavaPrevec: "Demasiados inicios de sesión a la vez. Inténtalo en un minuto.",
      prijavaBrezQr: "Aquí no se puede mostrar el código QR. Usa el código de 6 cifras.",
      prijavaAli: "o",
      prijavaLokalnaKodaNaslov: "Código de este ordenador",
      prijavaLokalnaKodaOpis: "Introduce este código de 6 cifras en la televisión o móvil con la app Safeer.",
      prijavaNovaKoda: "Nuevo código",
      prijavaNazajOs: "Safeer OS Inicio",
      prijavaKodaNaslov: "Introduce el código de 6 cifras",
      prijavaKodaOpis: "Haz clic en el campo: el código aparece en el televisor o la tableta con Safeer Link.",
      prijavaKodaNaSredisce: "El código está ahora en la pantalla del dispositivo con Safeer Link. Escríbelo aquí.",
      prijavaKodaSestMest: "El código tiene 6 cifras.",
      prijavaGumb: "Entrar",
      prijavaPreverjam: "Comprobando …",
      prijavaBrez: "Continuar sin conectar dispositivos",
      prijavaOsSeNastaja: "Safeer OS para ordenador aún está en desarrollo. Cuando esté instalado, se abrirá desde aquí.",
      prijavaZaupaj: "Confiar en este ordenador",
      prijavaZaupajOpis: "Solo tendrás que conectarte una vez. Elígelo solo en tu propio ordenador; si no, volverás a conectarte la próxima vez que inicies sesión en el ordenador.",
      prijavaUspela: "Sesión iniciada. Conectando …",
      prijavaZnovaZazeni: "Reinicia Safeer OS para cargar la actualización: ciérralo desde la bandeja o cierra y abre sesión.",
      brezPovezaveNaslov: "No hay dispositivos conectados",
      brezPovezaveOpis: "Safeer OS funciona en este ordenador. Conecta el móvil, la tableta o el televisor cuando quieras.",
      poveziNaprave: "Conectar dispositivos",
      odpriSafeerOs: "Abrir Safeer OS"
    },
    fr: {
      prijavaNaslov: "Connexion",
      prijavaPodnaslov: "Connecte cet ordinateur à tes appareils.",
      prijavaQrNaslov: "Scanne avec ton téléphone",
      prijavaQrOpis: "Vise le code avec l'appareil photo d'un téléphone ou d'une tablette déjà dans Safeer Link, puis confirme sur le téléphone.",
      prijavaQrPripravljam: "Préparation du code …",
      prijavaQrOsvezi: "Le code se renouvelle tout seul.",
      prijavaNiHuba: "Aucun Safeer Link sur ton réseau domestique. Active-le sur le téléviseur ou la tablette.",
      prijavaPoisci: "Chercher à nouveau",
      prijavaHubStar: "Safeer sur le téléviseur est trop ancien pour le code QR. Utilise le code à 6 chiffres ou mets-le à jour.",
      prijavaPrevec: "Trop de connexions simultanées. Réessaie dans une minute.",
      prijavaBrezQr: "Le code QR ne peut pas être affiché ici. Utilise le code à 6 chiffres.",
      prijavaAli: "ou",
      prijavaLokalnaKodaNaslov: "Code de cet ordinateur",
      prijavaLokalnaKodaOpis: "Saisis ce code à 6 chiffres sur ton téléviseur ou dans l'app Safeer de ton téléphone.",
      prijavaNovaKoda: "Nouveau code",
      prijavaNazajOs: "Safeer OS Accueil",
      prijavaKodaNaslov: "Saisis le code à 6 chiffres",
      prijavaKodaOpis: "Clique dans le champ : le code s'affiche sur le téléviseur ou la tablette avec Safeer Link.",
      prijavaKodaNaSredisce: "Le code est maintenant à l'écran de l'appareil Safeer Link. Saisis-le ici.",
      prijavaKodaSestMest: "Le code a 6 chiffres.",
      prijavaGumb: "Se connecter",
      prijavaPreverjam: "Vérification …",
      prijavaBrez: "Continuer sans connecter d'appareils",
      prijavaOsSeNastaja: "Safeer OS pour ordinateur est encore en préparation. Une fois installé, il s'ouvrira d'ici.",
      prijavaZaupaj: "Faire confiance à cet ordinateur",
      prijavaZaupajOpis: "La connexion ne sera nécessaire qu'une fois. Choisis-le seulement sur ton propre ordinateur – sinon tu te reconnecteras à la prochaine ouverture de session.",
      prijavaUspela: "Connecté. Connexion en cours …",
      prijavaZnovaZazeni: "Redémarre Safeer OS pour charger la mise à jour : quitte-le depuis la zone de notification ou reconnecte-toi.",
      brezPovezaveNaslov: "Aucun appareil connecté",
      brezPovezaveOpis: "Safeer OS fonctionne sur cet ordinateur. Connecte ton téléphone, ta tablette ou ton téléviseur quand tu veux.",
      poveziNaprave: "Connecter des appareils",
      odpriSafeerOs: "Ouvrir Safeer OS"
    },
    it: {
      prijavaNaslov: "Accedi",
      prijavaPodnaslov: "Collega questo computer ai tuoi dispositivi.",
      prijavaQrNaslov: "Scansiona con il telefono",
      prijavaQrOpis: "Inquadra il codice con la fotocamera di un telefono o tablet già in Safeer Link e conferma sul telefono.",
      prijavaQrPripravljam: "Preparo il codice …",
      prijavaQrOsvezi: "Il codice si rinnova da solo.",
      prijavaNiHuba: "Nessun Safeer Link nella rete di casa. Attivalo sul televisore o sul tablet.",
      prijavaPoisci: "Cerca di nuovo",
      prijavaHubStar: "Safeer sul televisore è troppo vecchio per il codice QR. Usa il codice di 6 cifre o aggiornalo.",
      prijavaPrevec: "Troppi accessi contemporanei. Riprova tra un minuto.",
      prijavaBrezQr: "Qui il codice QR non può essere mostrato. Usa il codice di 6 cifre.",
      prijavaAli: "oppure",
      prijavaLokalnaKodaNaslov: "Codice di questo computer",
      prijavaLokalnaKodaOpis: "Inserisci questo codice a 6 cifre sulla TV o nell'app Safeer sullo smartphone.",
      prijavaNovaKoda: "Nuovo codice",
      prijavaNazajOs: "Safeer OS Home",
      prijavaKodaNaslov: "Inserisci il codice di 6 cifre",
      prijavaKodaOpis: "Fai clic nel campo: il codice appare sul televisore o sul tablet con Safeer Link.",
      prijavaKodaNaSredisce: "Il codice è ora sullo schermo del dispositivo con Safeer Link. Scrivilo qui.",
      prijavaKodaSestMest: "Il codice ha 6 cifre.",
      prijavaGumb: "Accedi",
      prijavaPreverjam: "Verifica …",
      prijavaBrez: "Continua senza collegare dispositivi",
      prijavaOsSeNastaja: "Safeer OS per computer è ancora in preparazione. Una volta installato, si aprirà da qui.",
      prijavaZaupaj: "Considera attendibile questo computer",
      prijavaZaupajOpis: "Dovrai collegarti una sola volta. Sceglilo solo sul tuo computer, altrimenti ti ricollegherai al prossimo accesso al computer.",
      prijavaUspela: "Accesso eseguito. Connessione …",
      prijavaZnovaZazeni: "Riavvia Safeer OS per caricare l'aggiornamento: chiudilo dall'area di notifica o esci e rientra.",
      brezPovezaveNaslov: "Nessun dispositivo collegato",
      brezPovezaveOpis: "Safeer OS funziona su questo computer. Collega telefono, tablet o televisore quando vuoi.",
      poveziNaprave: "Collega dispositivi",
      odpriSafeerOs: "Apri Safeer OS"
    }
  };
  for (var _jp in BESEDILA_PRIJAVA) {
    if (!BESEDILA[_jp]) BESEDILA[_jp] = {};
    for (var _kp in BESEDILA_PRIJAVA[_jp]) BESEDILA[_jp][_kp] = BESEDILA_PRIJAVA[_jp][_kp];
  }
  var BESEDILA_VABILO = {
    "sl": {
      "vabiloGumb": "Pokaži QR kodo za novo napravo",
      "vabiloOpis": "S kamero telefona ali tablice skeniraj kodo – Safeer se odpre in naprava se poveže s Safeer Linkom.",
      "vabiloPridruzen": "✓ {ime} je povezan.",
      "vabiloHubStar": "Središče je treba posodobiti, da lahko pokaže kodo tukaj. Kodo najdeš tudi na središču (Naprave → Poveži novo napravo).",
      "vabiloNapaka": "Kode ni bilo mogoče pripraviti. Poskusi znova.",
      "vabiloZapri": "Skrij kodo"
    },
    "en": {
      "vabiloGumb": "Show QR code for a new device",
      "vabiloOpis": "Scan the code with your phone or tablet camera – Safeer opens and the device joins Safeer Link.",
      "vabiloPridruzen": "✓ {ime} is connected.",
      "vabiloHubStar": "The hub needs an update to show the code here. You'll also find the code on the hub (Devices → Connect a new device).",
      "vabiloNapaka": "The code could not be prepared. Try again.",
      "vabiloZapri": "Hide code"
    },
    "de": {
      "vabiloGumb": "QR-Code für ein neues Gerät zeigen",
      "vabiloOpis": "Scanne den Code mit der Kamera von Handy oder Tablet – Safeer öffnet sich und das Gerät tritt Safeer Link bei.",
      "vabiloPridruzen": "✓ {ime} ist verbunden.",
      "vabiloHubStar": "Die Zentrale muss aktualisiert werden, um den Code hier zu zeigen. Den Code findest du auch auf der Zentrale (Geräte → Neues Gerät verbinden).",
      "vabiloNapaka": "Der Code konnte nicht erstellt werden. Versuche es erneut.",
      "vabiloZapri": "Code ausblenden"
    },
    "es": {
      "vabiloGumb": "Mostrar código QR para un dispositivo nuevo",
      "vabiloOpis": "Escanea el código con la cámara del móvil o la tableta: Safeer se abre y el dispositivo se une a Safeer Link.",
      "vabiloPridruzen": "✓ {ime} está conectado.",
      "vabiloHubStar": "Hay que actualizar el centro para mostrar el código aquí. También encontrarás el código en el centro (Dispositivos → Conectar un dispositivo nuevo).",
      "vabiloNapaka": "No se ha podido preparar el código. Inténtalo de nuevo.",
      "vabiloZapri": "Ocultar código"
    },
    "fr": {
      "vabiloGumb": "Afficher le code QR pour un nouvel appareil",
      "vabiloOpis": "Scanne le code avec l'appareil photo du téléphone ou de la tablette – Safeer s'ouvre et l'appareil rejoint Safeer Link.",
      "vabiloPridruzen": "✓ {ime} est connecté.",
      "vabiloHubStar": "Le centre doit être mis à jour pour afficher le code ici. Tu trouveras aussi le code sur le centre (Appareils → Connecter un nouvel appareil).",
      "vabiloNapaka": "Impossible de préparer le code. Réessaie.",
      "vabiloZapri": "Masquer le code"
    },
    "it": {
      "vabiloGumb": "Mostra il codice QR per un nuovo dispositivo",
      "vabiloOpis": "Scansiona il codice con la fotocamera del telefono o del tablet: Safeer si apre e il dispositivo entra in Safeer Link.",
      "vabiloPridruzen": "✓ {ime} è collegato.",
      "vabiloHubStar": "L'hub va aggiornato per mostrare il codice qui. Trovi il codice anche sull'hub (Dispositivi → Collega un nuovo dispositivo).",
      "vabiloNapaka": "Impossibile preparare il codice. Riprova.",
      "vabiloZapri": "Nascondi codice"
    }
  };
  for (var _jv in BESEDILA_VABILO) {
    if (!BESEDILA[_jv]) BESEDILA[_jv] = {};
    for (var _kv in BESEDILA_VABILO[_jv]) BESEDILA[_jv][_kv] = BESEDILA_VABILO[_jv][_kv];
  }

  var jezik = (function () {
    var oznaka = "";
    try {
      if (most && most.jezik) oznaka = String(most.jezik() || "");
    } catch (e) {}
    if (!oznaka) oznaka = (navigator.language || navigator.userLanguage || "en");
    oznaka = oznaka.toLowerCase().slice(0, 2);
    return BESEDILA[oznaka] ? oznaka : "en";
  })();

  function t(kljuc, nadomestki) {
    var niz = (BESEDILA[jezik] && BESEDILA[jezik][kljuc]);
    if (niz === undefined) niz = (BESEDILA.en && BESEDILA.en[kljuc]);
    if (niz === undefined) niz = BESEDILA.sl[kljuc];
    if (niz === undefined) return "";
    if (nadomestki) {
      for (var k in nadomestki) {
        if (Object.prototype.hasOwnProperty.call(nadomestki, k)) {
          niz = niz.split("{" + k + "}").join(String(nadomestki[k]));
        }
      }
    }
    return niz;
  }

  function prevediStran() {
    document.documentElement.lang = jezik;
    var vsi = document.querySelectorAll("[data-t]");
    for (var i = 0; i < vsi.length; i++) {
      var kljuc = vsi[i].getAttribute("data-t");
      var niz = t(kljuc);
      if (niz) vsi[i].textContent = niz;
    }
    var naslovi = document.querySelectorAll("[data-t-naslov]");
    for (var j = 0; j < naslovi.length; j++) {
      var n = t(naslovi[j].getAttribute("data-t-naslov"));
      if (n) naslovi[j].setAttribute("aria-label", n);
    }
  }

  // Besedila za sredisce na televizorju. Dodana so tu na kupu, da se v obeh jezikih
  // vidijo skupaj -- kar je treba prevesti, je na enem mestu.
  var BESEDILA_HUB = {
    sl: {
      tuOpis: "Začni povezovanje tukaj: vklopi Safeer Link, nato na drugi napravi vtipkaj kodo, ki jo pokaže ta naprava.",
      tuOpisTv: "Če telefona ali računalnika nimaš pri roki, začni kar na tem televizorju.",
      vklopiLink: "Vklopi Safeer Link",
      izklopiLink: "Izklopi Safeer Link",
      tuNaslov: "Safeer Link teče na tej napravi",
      tuNaslovTv: "Safeer Link teče na tem televizorju",
      tuPojasnilo: "Naprave v domačem omrežju se povezujejo na to napravo. Ko se povežejo, si lahko med seboj pošiljajo strani, besedila, datoteke in zaslon.",
      tuSredisce: "Vklopljen na tej napravi",
      povezana: "Povezana",
      sePotrdi: "Še enkrat pritisni, da ji odvzameš dostop",
      cakaPrijava: "Naprava se želi povezati",
      primerjajKodo: "Na tej napravi vtipkaj številko, ki jo vidiš tukaj",
      potrdi: "Potrdi",
      zavrni: "Zavrni",
      odstrani: "Odstrani",
      povezanNaTv: "Sme pošiljati na to napravo",
      nobeneNaprave: "Povežite naprave za lažje delo",
      prizigam: "Prižigam …"
    },
    en: {
      tuOpis: "Start connecting here: switch on Safeer Link, then on the other device type the code this device shows.",
      tuOpisTv: "If no phone or computer is at hand, start right here on this television.",
      vklopiLink: "Turn on Safeer Link",
      izklopiLink: "Turn off Safeer Link",
      tuNaslov: "Safeer Link is running on this device",
      tuNaslovTv: "Safeer Link is running on this television",
      tuPojasnilo: "Devices on your home network connect to this device. Once connected, they can send each other pages, text, files and their screen.",
      tuSredisce: "Switched on on this device",
      povezana: "Connected",
      sePotrdi: "Press again to revoke access",
      cakaPrijava: "A device wants to connect",
      primerjajKodo: "On that device, type the number you see here",
      potrdi: "Approve",
      zavrni: "Decline",
      odstrani: "Remove",
      povezanNaTv: "May send to this device",
      nobeneNaprave: "Connect your devices to make work easier",
      prizigam: "Turning on …"
    },
    de: {
      tuOpis: "Beginne hier: Schalte Safeer Link ein und gib dann auf dem anderen Gerät den Code ein, den dieses Gerät anzeigt.",
      tuOpisTv: "Wenn kein Telefon oder Computer zur Hand ist, beginne einfach auf diesem Fernseher.",
      vklopiLink: "Safeer Link einschalten",
      izklopiLink: "Safeer Link ausschalten",
      tuNaslov: "Safeer Link läuft auf diesem Gerät",
      tuNaslovTv: "Safeer Link läuft auf diesem Fernseher",
      tuPojasnilo: "Geräte im Heimnetz verbinden sich mit diesem Gerät. Danach können sie sich gegenseitig Seiten, Text, Dateien und den Bildschirm senden.",
      tuSredisce: "Auf diesem Gerät eingeschaltet",
      povezana: "Verbunden",
      sePotrdi: "Erneut drücken, um den Zugriff zu entziehen",
      cakaPrijava: "Ein Gerät möchte sich verbinden",
      primerjajKodo: "Gib auf diesem Gerät die Zahl ein, die du hier siehst",
      potrdi: "Bestätigen",
      zavrni: "Ablehnen",
      odstrani: "Entfernen",
      povezanNaTv: "Darf an dieses Gerät senden",
      nobeneNaprave: "Verbinde deine Geräte, um dir die Arbeit zu erleichtern",
      prizigam: "Wird eingeschaltet …"
    },
    es: {
      tuOpis: "Empieza a conectar aquí: activa Safeer Link y, en el otro dispositivo, escribe el código que muestra este.",
      tuOpisTv: "Si no tienes el teléfono ni el ordenador a mano, empieza aquí mismo, en este televisor.",
      vklopiLink: "Activar Safeer Link",
      izklopiLink: "Desactivar Safeer Link",
      tuNaslov: "Safeer Link está activo en este dispositivo",
      tuNaslovTv: "Safeer Link está activo en este televisor",
      tuPojasnilo: "Los dispositivos de tu red doméstica se conectan a este dispositivo. Una vez conectados, pueden enviarse páginas, texto, archivos y la pantalla.",
      tuSredisce: "Activado en este dispositivo",
      povezana: "Conectado",
      sePotrdi: "Pulsa de nuevo para retirarle el acceso",
      cakaPrijava: "Un dispositivo quiere conectarse",
      primerjajKodo: "En ese dispositivo, escribe el número que ves aquí",
      potrdi: "Aprobar",
      zavrni: "Rechazar",
      odstrani: "Quitar",
      povezanNaTv: "Puede enviar a este dispositivo",
      nobeneNaprave: "Conecta tus dispositivos para trabajar más cómodo",
      prizigam: "Activando …"
    },
    fr: {
      tuOpis: "Commence ici : active Safeer Link, puis saisis sur l’autre appareil le code affiché par celui-ci.",
      tuOpisTv: "S’il n’y a ni téléphone ni ordinateur sous la main, commence directement sur ce téléviseur.",
      vklopiLink: "Activer Safeer Link",
      izklopiLink: "Désactiver Safeer Link",
      tuNaslov: "Safeer Link est actif sur cet appareil",
      tuNaslovTv: "Safeer Link est actif sur ce téléviseur",
      tuPojasnilo: "Les appareils de ton réseau domestique se connectent à cet appareil. Une fois connectés, ils peuvent s\'envoyer des pages, du texte, des fichiers et leur écran.",
      tuSredisce: "Activé sur cet appareil",
      povezana: "Connecté",
      sePotrdi: "Appuie encore une fois pour lui retirer l\'accès",
      cakaPrijava: "Un appareil veut se connecter",
      primerjajKodo: "Sur cet appareil, saisis le nombre que tu vois ici",
      potrdi: "Approuver",
      zavrni: "Refuser",
      odstrani: "Retirer",
      povezanNaTv: "Peut envoyer vers cet appareil",
      nobeneNaprave: "Connecte tes appareils pour te faciliter la vie",
      prizigam: "Activation …"
    },
    it: {
      tuOpis: "Inizia a collegare da qui: accendi Safeer Link, poi sull’altro dispositivo digita il codice mostrato da questo.",
      tuOpisTv: "Se non hai a portata di mano telefono o computer, inizia direttamente da questo televisore.",
      vklopiLink: "Attiva Safeer Link",
      izklopiLink: "Disattiva Safeer Link",
      tuNaslov: "Safeer Link è attivo su questo dispositivo",
      tuNaslovTv: "Safeer Link è attivo su questo televisore",
      tuPojasnilo: "I dispositivi della tua rete domestica si collegano a questo dispositivo. Una volta collegati, possono inviarsi pagine, testi, file e lo schermo.",
      tuSredisce: "Acceso su questo dispositivo",
      povezana: "Collegato",
      sePotrdi: "Premi di nuovo per revocarle l\'accesso",
      cakaPrijava: "Un dispositivo vuole collegarsi",
      primerjajKodo: "Su quel dispositivo digita il numero che vedi qui",
      potrdi: "Approva",
      zavrni: "Rifiuta",
      odstrani: "Rimuovi",
      povezanNaTv: "Può inviare a questo dispositivo",
      nobeneNaprave: "Collega i tuoi dispositivi per lavorare più comodamente",
      prizigam: "Attivazione …"
    }
  };
  for (var _jezik in BESEDILA_HUB) {
    if (!BESEDILA[_jezik]) BESEDILA[_jezik] = {};
    for (var _kljuc in BESEDILA_HUB[_jezik]) BESEDILA[_jezik][_kljuc] = BESEDILA_HUB[_jezik][_kljuc];
  }

  // ----------------------------------------------------------------
  // Stanje
  // ----------------------------------------------------------------

  var stanje = {
    znan: false,
    seznanjen: false,
    povezan: false,
    televizor: false,
    hub: "",
    imeNaprave: "",
    idNaprave: "",
    naprave: [],
    prejemnik: null,
    predvajanje: null,
    tezava: false,
    preseljen: false,
    hubTece: false,
    control: false,
    hubPovezanih: 0,
    prijave: [],
    hubNaprave: [],
    lokalnaKoda: ""
  };

  function besedilo(id, vsebina) {
    var e = el(id);
    if (e) e.textContent = vsebina;
  }

  function pokazi(id, ali) {
    var e = el(id);
    if (e) e.hidden = !ali;
  }

  // Ena preimenovana oznaka v HTML ne sme podreti celotne inicializacije zaslona.
  function naKlik(id, funkcija) {
    var e = el(id);
    if (e) e.addEventListener("click", funkcija);
  }

  function cas(sekunde) {
    if (!isFinite(sekunde) || sekunde < 0) return "0:00";
    var s = Math.floor(sekunde % 60);
    var m = Math.floor(sekunde / 60);
    return m + ":" + (s < 10 ? "0" : "") + s;
  }

  /** Naslov Huba brez vrat in brez sheme; uporabnik ne rabi videti ne enega ne drugega. */
  function prijaznaHisa(naslov) {
    if (!naslov) return "";
    var golo = String(naslov).replace(/^wss?:\/\//, "").replace(/\/.*$/, "");
    return golo.replace(/:\d+$/, "");
  }

  /** Ime naprave, kot ga razume clovek. Tehnicnega ID nikoli ne pokazemo. */
  function prijaznoIme(naprava) {
    if (!naprava) return t("zaslon");
    if (naprava.id && vzdevki[naprava.id]) return vzdevki[naprava.id];
    var ime = (naprava.ime || "").trim();
    if (ime && !/^[a-z0-9]+-[a-z0-9-]{4,}$/i.test(ime)) return ime;
    return naprava.vloga === "receiver" ? t("televizor") : t("zaslon");
  }

  // Crtne ikone (iste kot na safeer.si) namesto emojijev: na vsaki napravi so videti enako.
  var IKONE = {
    tv: "<svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M2 4h20v13H2z M8 21h8 M12 17v4\"/></svg>",
    racunalnik: "<svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M1 3h22v14H1z M8 21h8 M12 17v4\"/></svg>",
    telefon: "<svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M6.5 1.5h11a2.5 2.5 0 0 1 2.5 2.5v16a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 20V4a2.5 2.5 0 0 1 2.5-2.5z M10.5 18.5h3\"/></svg>",
    hisa: "<svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M3 11 12 3l9 8 M5 10v11h5v-6h4v6h5V10\"/></svg>",
    zvezda: "<svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M12 3l2.8 5.6 6.2.9-4.5 4.4 1.1 6.1L12 17.1 6.4 20l1.1-6.1L3 9.5l6.2-.9z\"/></svg>",
    nastavitve: "<svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M12 15.5a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7z M12 2.5V5 M12 19v2.5 M2.5 12H5 M19 12h2.5 M5.3 5.3 7 7 M17 17l1.7 1.7 M5.3 18.7 7 17 M17 7l1.7-1.7\"/></svg>",
    scit: "<svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M12 3 4 6v6c0 4.5 3.4 8.2 8 9 4.6-.8 8-4.5 8-9V6z M8.5 12l2.5 2.5 4.5-5\"/></svg>",
    povezava: "<svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1 M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1\"/></svg>",
    kljucavnica: "<svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M5 11h14v10H5z M8 11V7a4 4 0 0 1 8 0v4\"/></svg>",
    zaslon: "<svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M6.5 1.5h11a2.5 2.5 0 0 1 2.5 2.5v16a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 20V4a2.5 2.5 0 0 1 2.5-2.5z M8 6h8v9H8z\"/></svg>",
    mapa: "<svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M3 6h6l2 2h10v11H3z\"/></svg>",
    sporocilo: "<svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M4 4h16v12H9l-5 4z\"/></svg>",
    wifi: "<svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M2 9a15 15 0 0 1 20 0 M5.5 12.5a10 10 0 0 1 13 0 M9 16a5 5 0 0 1 6 0 M12 19.5v.1\"/></svg>",
    nazaj: "<svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M11 19 2 12l9-7z M21 19l-9-7 9-7z\"/></svg>",
    pavza: "<svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M7 5h3v14H7z M14 5h3v14h-3z\"/></svg>",
    predvajaj: "<svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M6 4l14 8-14 8z\"/></svg>",
    naprej: "<svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M13 5l9 7-9 7z M3 5l9 7-9 7z\"/></svg>"
  };
  function ikonaZnak(kljuc) {
    var e = document.createElement("span");
    e.className = "ikona";
    if (IKONE[kljuc]) e.innerHTML = IKONE[kljuc]; else e.textContent = kljuc;
    return e;
  }

  function vrstica(ikonaKljuc, ime, pod, znackaBesedilo, barva, obKliku) {
    var li = document.createElement("li");
    if (obKliku) {
      li.className = "klikljiv";
      li.tabIndex = 0;
    }

    var ikona = ikonaZnak(ikonaKljuc);

    var telo = document.createElement("div");
    telo.className = "telo";
    var i = document.createElement("div");
    i.className = "ime";
    i.textContent = ime;
    var p = document.createElement("div");
    p.className = "pod";
    p.textContent = pod;
    telo.appendChild(i);
    telo.appendChild(p);

    var z = document.createElement("span");
    z.className = "znacka" + (barva ? " " + barva : "");
    z.textContent = znackaBesedilo;

    li.appendChild(ikona);
    li.appendChild(telo);
    li.appendChild(z);

    if (obKliku) {
      li.addEventListener("click", obKliku);
      li.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); obKliku(); }
      });
    }
    return li;
  }

  // ----------------------------------------------------------------
  // Izris
  // ----------------------------------------------------------------

  /** Izris lokalne 6-mestne kode tega racunalnika za vpis v TV ali telefon */
  function narisiLokalnoKodo() {
    var okvir = el("lokalnaKodaStevilke");
    if (okvir) {
      okvir.textContent = stanje.lokalnaKoda || "------";
    }
  }

  /** Stanje je barva, ne stavek: zelena povezano, siva ni ga, rumena tezava. */
  function narisiStanje() {
    var pika = el("pika");
    var barva = "siva";
    var napis = t("niVklopljen");
    if (stanje.hubTece) {
      barva = "zelena";
      napis = t("tuSredisce");
    } else if (stanje.tezava) {
      barva = "rumena";
      napis = t("tezava");
    } else if (stanje.znan && stanje.seznanjen) {
      barva = stanje.povezan ? "zelena" : "rumena";
      napis = stanje.povezan ? t("povezano") : t("povezujem");
    } else if (stanje.preseljen) {
      barva = "rumena";
      napis = t("preseljenNaslov");
    } else if (stanje.znan) {
      barva = "rumena";
      napis = t("cakaNaPotrditev");
    }
    if (pika) pika.className = "pika " + barva;
    besedilo("podnaslov", napis);
  }

  function narisiZaslon() {
    // Dokler je odprt daljinec, so drugi zasloni skriti; narisemo jih, ko se zapre.
    if (daljinecOdprt) return;
    // Safeer Control brez povezave: samo prijavno okno (QR, koda, nadaljuj brez). Nic drugega.
    var prijavno = jePrijavnoOkno();
    var brezPovezave = jeBrezPovezave();
    document.body.classList.toggle("prijava", prijavno || brezPovezave);
    pokazi("zaslonPrijava", prijavno);
    pokazi("zaslonBrezPovezave", brezPovezave);
    if (prijavno || brezPovezave) {
      ["zaslonHubTu", "zaslonBrezHuba", "zaslonPreseljen", "zaslonSeznanitev", "zaslonPovezan", "hubStikalo"]
        .forEach(function (id) { pokazi(id, false); });
      if (prijavno) {
        zacniPrijavo();
        narisiLokalnoKodo();
      } else {
        koncajPrijavo();
      }
      narisiStanje();
      return;
    }
    koncajPrijavo();
    // Sredisce tece tu. Naprava, ki gosti (telefon, racunalnik ali televizor), je hkrati
    // navadna naprava: vidi ostale in jim posilja, zato ostane tudi obicajni pogled.
    var tuSredisce = stanje.hubTece;
    var samoSredisce = false;
    var brezHuba = !tuSredisce && !stanje.znan && !stanje.preseljen;
    var caka = !tuSredisce && stanje.znan && !stanje.seznanjen && !stanje.preseljen;
    pokazi("zaslonHubTu", tuSredisce);
    pokazi("zaslonBrezHuba", brezHuba);
    pokazi("zaslonPreseljen", !tuSredisce && stanje.preseljen);
    pokazi("zaslonSeznanitev", caka);
    pokazi("zaslonPovezan", !samoSredisce && !brezHuba && !caka && !stanje.preseljen);
    pokazi("gumbPozabi", !tuSredisce && !brezHuba && !caka && !!(most && most.pozabiNapravo));
    pokazi("hubStikalo", podpiraHub);
    var vklopi = el("gumbHubVklopi");
    var izklopi = el("gumbHubIzklopi");
    if (vklopi) vklopi.disabled = tuSredisce;
    if (izklopi) izklopi.disabled = !tuSredisce;
    besedilo("opombaHubVklop", tuSredisce ? "" : t(stanje.televizor ? "tuOpisTv" : "tuOpis"));
    besedilo("naslovHubTu", t(stanje.televizor ? "tuNaslovTv" : "tuNaslov"));
    narisiStanje();
    osveziOpozoriloOspredje();
  }

  function zasloni() {
    // Stran gre na vsako drugo napravo, ki jo zna odpreti: zaslon (televizor) vedno,
    // telefon ali racunalnik pa, ce to javi med zmoznostmi.
    return stanje.naprave.filter(function (n) {
      if (n.id === stanje.idNaprave) return false;
      if (n.vloga === "receiver") return true;
      var z = n.zmoznosti || [];
      return z.indexOf("url") >= 0;
    });
  }

  function narisiNaprave() {
    var seznam = el("seznamNaprav");
    if (!seznam) return;
    seznam.innerHTML = "";

    // Hub javlja samo zaslone, zato to napravo in Safeer Link narisemo sama --
    // uporabnik mora vedno videti, kje je, tudi kadar televizorja se ni.
    var jaz = null;
    for (var k = 0; k < stanje.naprave.length; k++) if (stanje.naprave[k].id === stanje.idNaprave) jaz = stanje.naprave[k];
    seznam.appendChild(vrstica(
      stanje.televizor ? "tv" : "racunalnik",
      (jaz && jaz.ime) || stanje.imeNaprave || t("taNaprava"),
      stanje.hubTece ? t("tuSredisce") : (stanje.povezan ? t("povezanaZLinkom") : t("povezujem")),
      t("taNaprava"),
      stanje.povezan ? "zivo" : "",
      (znaDeliti && jaz) ? function () { odpriDeljenje(jaz, true); } : null
    ));
    // Vrstica "Safeer Link na naslovu ..." ima smisel le na napravi, ki se povezuje drugam;
    // ce Safeer Link tece tu, bi kazala 127.0.0.1 in podvajala glavo strani.
    if (stanje.hub && !stanje.hubTece) {
      var sredisce = imeSredisca();
      var naslovHuba = prijaznaHisa(stanje.hub);
      seznam.appendChild(vrstica(
        "hisa", "Safeer Link", (sredisce && sredisce !== naslovHuba) ? sredisce + " · " + naslovHuba : naslovHuba,
        t("domace"), "zivo", null));
    }

    // Vse naprave, ki jih Hub pozna, razen te: vsaka je lahko cilj deljenja.
    var druge = stanje.naprave.filter(function (n) { return n.id !== stanje.idNaprave; });
    // Ena fizicna naprava, ena vrstica: Safeer OS (vrsta "os") na istem naslovu kot zaslon je
    // aplikacija tega zaslona, ne druga naprava. Protocol v1; naprave 0.2 ostanejo, kot so.
    var sorodniki = {};
    druge = druge.filter(function (n) {
      if (n.vrsta !== "os" || !n.naslov) return true;
      var zaslon = druge.some(function (z) { return z !== n && z.vloga === "receiver" && z.naslov === n.naslov; });
      if (zaslon) sorodniki[n.naslov] = n;
      return !zaslon;
    });
    druge.forEach(function (n) {
      var jeZaslon = n.vloga === "receiver";
      var deljivo = znaDeliti;
      var zasedena = !!n.zasedenaOd && n.zasedenaOd !== stanje.idNaprave;
      var pod = zasedena ? t("zasedenoDeli", { ime: n.zasedenaOdIme || n.zasedenaOd })
        : (deljivo ? t(jeNamizje() ? "deliKlik" : "deliDotik") : (jeZaslon ? t("zaslon") : t("naprava")));
      if (!zasedena && n.naslov && sorodniki[n.naslov]) pod = t("istaNaprava", { ime: "Safeer OS" }) + " · " + pod;
      seznam.appendChild(vrstica(
        (jeZaslon && !n.platforma) ? "tv" : ikonaNapraveVSeznamu(n),
        prijaznoIme(n),
        pod,
        zasedena ? t("zasedenoKratko") : t("povezan"), zasedena ? "rumenaZnacka" : "zivo",
        deljivo ? function () { odpriDeljenje(n); } : null));
    });

    besedilo("opombaNaprave",
             (druge.length || stanje.televizor) ? "" : t("brezZaslonov"));
  }

  function ikonaNapraveVSeznamu(naprava) {
    // Protocol v1: naprava pove platformo in vrsto sama; ugibanje po imenu ostane za naprave 0.2.
    var pl = (naprava && naprava.platforma) || "";
    var vr = (naprava && naprava.vrsta) || "";
    if (pl === "tv" || vr === "screen" && pl !== "tablet") return "tv";
    if (pl === "linux" || pl === "windows" || pl === "macos" || vr === "computer" || vr === "control") return "racunalnik";
    if (pl === "phone" || pl === "tablet" || vr === "handheld") return "telefon";
    var opis = ((naprava && (naprava.ime || "")) + " " + (naprava && (naprava.id || ""))).toLowerCase();
    if (/(televizor|tv|philips|android tv)/.test(opis)) return "tv";
    if (/(racunaln|računaln|computer|namizn|desktop|laptop|prenosn|linux|windows|mac|pc\b)/.test(opis)) return "racunalnik";
    return "telefon";
  }


  /** Ali je trenutno odprta stran sploh mogoce poslati (domaca stran, datoteke z naprave niso). */
  function stranPosljiva() {
    if (!most || !most.trenutnaStranJson) return true;
    try {
      var p = JSON.parse(most.trenutnaStranJson());
      return !p || p.posljiva !== false;
    } catch (e) {
      return true;
    }
  }

  function narisiPrejemnike() {
    var seznam = el("seznamPrejemnikov");
    if (!seznam) return;
    seznam.innerHTML = "";

    var prejemniki = zasloni();
    // Smernica: gumb za posiljanje naj obstaja samo, ko je kam poslati (in Control nima strani).
    pokazi("panelCast", prejemniki.length > 0 && !stanje.control);
    if (!prejemniki.length || stanje.control) return;
    // Domace strani ni mogoce poslati: vrstica s stranjo to ze pove, vrstic »Poslji« zato ne ponujamo,
    // da dotik ne konca z napako.
    if (!stranPosljiva()) { besedilo("opombaCast", ""); return; }

    besedilo("opombaCast", "");
    prejemniki.forEach(function (n) {
      var ime = prijaznoIme(n);
      seznam.appendChild(vrstica(n.vloga === "receiver" ? "tv" : ikonaNapraveVSeznamu(n), ime,
        t(n.vloga === "receiver" ? "posljiNaZaslon" : "posljiNaNapravo"), t("poslji"), "zivo",
        function () {
          stanje.prejemnik = n;
          besedilo("imePrejemnika", ime);
          if (most) most.posljiTrenutno(n.id);
        }));
    });
  }

  function narisiPredvajanje() {
    var p = stanje.predvajanje;
    pokazi("predvajalnik", !!p && !stanje.televizor);
    if (!p) return;
    besedilo("naslovPredvajanja", p.naslov || p.url || "—");
    besedilo("casPolozaj", cas(p.polozaj));
    besedilo("casTrajanje", cas(p.trajanje));
    var crta = el("crtaNapolnjena");
    if (crta) {
      var delez = p.trajanje > 0 ? Math.min(100, (p.polozaj / p.trajanje) * 100) : 0;
      crta.style.width = delez + "%";
    }
  }

  function narisiTrenutnoStran() {
    if (!most) return;
    var podatki;
    try {
      podatki = JSON.parse(most.trenutnaStranJson());
    } catch (e) {
      return;
    }
    besedilo("naslovStrani", podatki.naslov || podatki.url || "—");
    besedilo("urlStrani", podatki.posljiva ? podatki.url : t("domacaStran"));
  }

  // Vklop odda vse zaznamke vsem napravam. To je premalo za en sam dotik,
  // zato prvi dotik samo vprasa, drugi pa res vklopi.
  var syncPotrjujem = false;

  function narisiSync() {
    var seznam = el("seznamSync");
    if (!seznam) return;
    seznam.innerHTML = "";

    var zaznamki = { vklopljena: false, stevilo: 0, nadvoljo: true };
    if (most && most.sinhronizacijaStanje) {
      try {
        var s = JSON.parse(most.sinhronizacijaStanje());
        if (s && s.zaznamki) {
          zaznamki.vklopljena = !!s.zaznamki.vklopljena;
          zaznamki.stevilo = s.zaznamki.stevilo || 0;
          if (s.zaznamki.nadvoljo === false) zaznamki.nadvoljo = false;
        }
      } catch (e) {}
    }

    var pod;
    if (zaznamki.vklopljena) {
      pod = t("syncVklopljenaOpis", { n: zaznamki.stevilo });
    } else if (!zaznamki.nadvoljo) {
      pod = t("syncNiNaVoljo");
    } else if (syncPotrjujem) {
      pod = t("syncVprasanje", { n: zaznamki.stevilo });
    } else {
      pod = t("syncPovabilo");
    }

    var znacka = zaznamki.vklopljena ? t("syncVklopljena")
               : (syncPotrjujem ? t("syncPotrdi") : t("syncIzklopljena"));

    seznam.appendChild(vrstica(
      "zvezda", t("zaznamki"), pod, znacka,
      zaznamki.vklopljena ? "zivo" : (syncPotrjujem ? "opozorilo" : ""),
      zaznamki.nadvoljo ? function () {
        if (!most) return;
        if (zaznamki.vklopljena) {
          syncPotrjujem = false;
          besedilo("opombaSync", t("syncIzklapljam"));
          most.nastaviSinhronizacijo(false);
          return;
        }
        if (!syncPotrjujem) {
          syncPotrjujem = true;
          besedilo("opombaSync", "");
          narisiSync();
          return;
        }
        syncPotrjujem = false;
        besedilo("opombaSync", t("syncVklapljam"));
        most.nastaviSinhronizacijo(true);
      } : null
    ));

    [
      { ikona: "nastavitve", ime: t("nastavitve"), pod: t("nastavitveOpis") },
      { ikona: "scit", ime: t("filtri"), pod: t("filtriOpis") }
    ].forEach(function (v) {
      seznam.appendChild(vrstica(v.ikona, v.ime, v.pod, t("kmalu"), "", null));
    });
  }

  function narisiVse() {
    narisiZaslon();
    narisiNaprave();
    narisiPrejemnike();
    narisiTrenutnoStran();
    if (!stanje.televizor) narisiPredvajanje();
    if (stanje.control) narisiControl();
  }

  /** Vgrajeni razdelek Naprave v Safeer OS: Link povezuje, Control pa upravlja naprave. */
  function narisiControl() {
    document.title = "Safeer OS · Naprave";
    besedilo("naslovAplikacije", "Safeer OS");
    pokazi("podrocjeAplikacije", true);
    pokazi("lociloPodrocja", true);
    pokazi("gumbZapri", false);
    pokazi("panelCast", false);
    pokazi("panelSync", false);
    pokazi("predvajalnik", false);
    pokazi("panelMape", stanje.znan && stanje.seznanjen);
    pokazi("panelDodaj", stanje.znan && (stanje.seznanjen || stanje.vKrogu));
    pokazi("vabiloBlok", !!(most && most.zacniVabilo));
    var sredisce = imeSredisca() || t("televizor");
    besedilo("dodajKorak3", t("dodajKorak3", { sredisce: sredisce }));
    narisiMape();
    narisiMeni();
  }

  // ---------- vgrajeni razdelek Naprave: levi meni znotraj Safeer OS ----------

  var razdelek = "";

  function jeNamizje() { return !!stanje.control; }

  function narisiMeni() {
    if (!jeNamizje()) return;
    if (jePrijavnoOkno() || jeBrezPovezave()) return;
    besedilo("dodajKorak3", t("dodajKorak3", { sredisce: imeSredisca() || t("televizor") }));
    document.body.classList.add("namizje");
    pokazi("stranskiMeni", true);
    // Razdelek je na voljo le, ce je njegov panel sploh na voljo (Control nima strani za posiljanje ne sinhronizacije).
    var gumbi = document.querySelectorAll("#stranskiMeni button[data-razdelek]");
    for (var i = 0; i < gumbi.length; i++) {
      var ime = gumbi[i].getAttribute("data-razdelek");
      var naVoljo = true;
      if (ime === "domov") naVoljo = true;
      else if (ime === "poslji") naVoljo = !el("panelCast").hidden;
      else if (ime === "sync") naVoljo = !el("panelSync").hidden;
      else if (ime === "mape") naVoljo = !el("panelMape").hidden;
      else if (ime === "daljinec") naVoljo = napravaZaDaljinec() !== null;
      gumbi[i].hidden = !naVoljo;
    }
    if (!razdelek) izberiRazdelek("naprave");
    else if (razdelek !== "daljinec" && razdelek !== "domov" && el("stranskiMeni").querySelector('button[data-razdelek="' + razdelek + '"]').hidden) izberiRazdelek("naprave");
  }

  function najdiNapravo(id) {
    if (!id || !stanje.naprave) return null;
    for (var i = 0; i < stanje.naprave.length; i++) {
      if (stanje.naprave[i].id === id) return stanje.naprave[i];
    }
    return null;
  }

  /** Zaslon (televizor), ki sprejema ukaze daljinca; prvi tak, ali null. */
  function napravaZaDaljinec() {
    var z = stanje.naprave.filter(function (n) {
      if (n.id === stanje.idNaprave) return false;
      var zm = n.zmoznosti || [];
      return zm.indexOf("remote") >= 0 || n.platforma === "tv" || n.vrsta === "screen" || n.vloga === "receiver";
    });
    return z.length ? z[0] : null;
  }

  function oznaciRazdelek(ime) {
    razdelek = ime;
    document.body.setAttribute("data-razdelek", ime);
    var gumbi = document.querySelectorAll("#stranskiMeni button[data-razdelek]");
    for (var i = 0; i < gumbi.length; i++) {
      gumbi[i].classList.toggle("izbran", gumbi[i].getAttribute("data-razdelek") === ime);
    }
  }

  function izberiRazdelek(ime) {
    if (ime === "domov") {
      if (most && most.zapri) most.zapri();
      return;
    }
    if (ime === "daljinec") {
      var n = napravaZaDaljinec();
      if (!n || !window.SafeerDaljinec) { izberiRazdelek("naprave"); return; }
      oznaciRazdelek("daljinec");
      window.SafeerDaljinec.odpri(n);
      return;
    }
    if (window.SafeerDaljinec && window.SafeerDaljinec.jeOdprt()) {
      oznaciRazdelek(ime);
      window.SafeerDaljinec.zapri();
      return;
    }
    oznaciRazdelek(ime);
    zapriDeljenje();
    var glavni = el("main") || document.querySelector("main");
    if (glavni) glavni.scrollTop = 0;
  }

  /** Deljene mape (Safeer Control): seznam, odstranitev s klikom na vrstico, gumb za dodajanje. */
  function narisiMape() {
    var seznam = el("seznamMape");
    if (!seznam) return;
    seznam.innerHTML = "";
    var mape = stanje.deljeneMape || [];
    pokazi("opombaMape", mape.length === 0);
    pokazi("gumbStandardneMape", !(stanje.standardneDeljene));
    mape.forEach(function (m, i) {
      var li = vrstica("mapa", m.ime || m.pot, m.pot || "", t("mapeOdstrani"), "", function () {
        if (most && most.odstraniDeljenoMapo) most.odstraniDeljenoMapo(i);
      });
      var pod = li.querySelector(".pod");
      if (pod) pod.style.wordBreak = "break-all";  // dolga pot brez presledkov ne sme prekriti znacke
      seznam.appendChild(li);
    });
  }

  // ----------------------------------------------------------------
  // Sredisce na tem televizorju
  // ----------------------------------------------------------------

  var podpiraHub = !!(most && most.hubStanje);
  var hubUra = null;
  var hubPodpis = "";
  var hubPrejPrijav = 0;
  var odvzemam = "";

  /** Prebere stanje sredisca pri mostu. Na napravah brez te podpore ne naredi nicesar. */
  function hubOsvezi() {
    if (!podpiraHub) return;
    try {
      var s = JSON.parse(most.hubStanje() || "{}");
      stanje.hubTece = !!s.tece;
      stanje.hubPovezanih = s.naprav || 0;
    } catch (e) {}
    try {
      stanje.prijave = JSON.parse(most.hubPrijave() || "[]");
    } catch (e) {
      stanje.prijave = [];
    }
    try {
      stanje.hubNaprave = JSON.parse(most.hubSeznanjene() || "[]");
    } catch (e) {
      stanje.hubNaprave = [];
    }
    narisiHub();
    narisiZaslon();
    hubUraNastavi();
  }

  /** Medtem ko sredisce tece, stanje osvezujemo sami -- nova prijava se mora pokazati sama. */
  function hubUraNastavi() {
    if (stanje.hubTece && !hubUra) hubUra = setInterval(hubOsvezi, 4000);
    if (!stanje.hubTece && hubUra) {
      clearInterval(hubUra);
      hubUra = null;
    }
  }

  function narisiHub() {
    // Seznama ne prerisujemo, ce se ni nic spremenilo: na daljincu bi vsako risanje
    // odneslo fokus z gumba, ki ga ima uporabnik ravno pod prstom.
    var podpis = JSON.stringify([stanje.prijave, stanje.hubNaprave, odvzemam]);
    if (podpis === hubPodpis) return;
    hubPodpis = podpis;

    // Kje je bil fokus? Po izrisu ga vrnemo na isto mesto: brez tega drugi pritisk
    // na daljincu pade v prazno, ker je element, ki ga je uporabnik gledal, nov.
    var prejsnjiFokus = null;
    try {
      prejsnjiFokus = document.activeElement &&
        document.activeElement.getAttribute && document.activeElement.getAttribute("data-fokus");
    } catch (e) {}

    var prijave = el("seznamPrijav");
    if (prijave) {
      prijave.innerHTML = "";
      stanje.prijave.forEach(function (p) { prijave.appendChild(vrsticaPrijave(p)); });
    }
    pokazi("panelPrijave", stanje.prijave.length > 0);

    var naprave = el("seznamHubNaprav");
    if (naprave) {
      naprave.innerHTML = "";
      stanje.hubNaprave.forEach(function (n) {
        // Naprava, ki gosti, ima svoj zeton (posiljanje nase), a v seznamu "kdo sme posiljati
        // na to napravo" nima kaj iskati - uporabnik bi videl sam sebe.
        if (n.id === stanje.idNaprave) return;
        // Klik odpre plosco z imenom naprave: Preimenuj (krajevno ime) in Odstrani (dostop se
        // odvzame v dveh korakih: en sam pritisk na daljincu je prehitro storjen).
        var vrsticaNaprave = vrstica(
          ikonaNaprave(n),
          prijaznoIme(n),
          t("povezanNaTv"),
          t("povezana"),
          "zivo",
          function () { odpriDeljenje(n, true, true); });
        vrsticaNaprave.setAttribute("data-fokus", "naprava:" + n.id);
        naprave.appendChild(vrsticaNaprave);
      });
    }
    var drugihVHubu = stanje.hubNaprave.filter(function (n) { return n.id !== stanje.idNaprave; }).length;
    besedilo("opombaHub", drugihVHubu ? "" : t("nobeneNaprave"));

    // Fokus nazaj na isto mesto; ce ga ni vec, na cakajoco prijavo.
    var nicNiFokusirano = !document.activeElement || document.activeElement === document.body;
    var vrnjen = false;
    if (prejsnjiFokus) {
      var isti = document.querySelector('[data-fokus="' + prejsnjiFokus + '"]');
      if (isti) {
        try { isti.focus(); vrnjen = true; } catch (e) {}
      }
    }
    // Nova prijava: fokus gre na Potrdi, da je dovolj en pritisk na V redu.
    // Prav tako takrat, kadar fokus ni nikjer -- daljinec mora vedno imeti kam.
    if (!vrnjen && stanje.prijave.length &&
        (stanje.prijave.length > hubPrejPrijav || nicNiFokusirano)) {
      setTimeout(fokusirajPotrditev, 80);
    }
    hubPrejPrijav = stanje.prijave.length;
  }

  /**
   * Ikona pove, kaj se povezuje. Vrsto naprave uganemo iz imena, ki ga naprava pove o sebi --
   * racunalnik naj bo racunalnik in ne telefon, sicer uporabnik ne ve, katera naprava je katera.
   */
  function ikonaNaprave(naprava) {
    var opis = ((naprava && (naprava.ime || "")) + " " + (naprava && (naprava.id || ""))).toLowerCase();
    if (/(televizor|tv|philips|android tv)/.test(opis)) return "tv";
    if (/(racunaln|računaln|computer|namizn|desktop|laptop|prenosn|linux|windows|mac|pc\b)/.test(opis)) return "racunalnik";
    if (/(tablic|tablet|ipad)/.test(opis)) return "telefon";
    return "telefon";
  }

  function vrsticaPrijave(p) {
    var li = document.createElement("li");
    li.className = "prijava";

    var telo = document.createElement("div");
    telo.className = "telo";
    var ime = document.createElement("div");
    ime.className = "ime";
    ime.textContent = (ikonaNaprave(p) + " " + (p.ime || t("zaslon"))).trim();
    var pod = document.createElement("div");
    pod.className = "pod";
    // Navadno je koda navodilo: uporabnik jo prebere tu in vtipka na drugi napravi.
    // Starejsa naprava kodo kaze pri sebi in caka na potrditev tukaj.
    pod.textContent = p.potrebujePotrditev ? t("primerjajKodo") : t("prijavaCakaKodo");
    telo.appendChild(ime);
    telo.appendChild(pod);

    var koda = document.createElement("div");
    koda.className = "stevilke";
    koda.textContent = p.koda || "------";

    var tipke = document.createElement("div");
    tipke.className = "tipke";
    if (p.potrebujePotrditev) {
      var potrdi = document.createElement("button");
      potrdi.className = "glavni";
      potrdi.setAttribute("data-potrdi", "1");
      potrdi.setAttribute("data-fokus", "prijava:" + p.id + ":potrdi");
      potrdi.textContent = t("potrdi");
      potrdi.addEventListener("click", function () {
        if (most && most.hubPotrdi) most.hubPotrdi(p.id);
      });
      tipke.appendChild(potrdi);
    }
    var zavrni = document.createElement("button");
    zavrni.className = "drugotni tanek";
    zavrni.setAttribute("data-fokus", "prijava:" + p.id + ":zavrni");
    zavrni.textContent = t("zavrni");
    zavrni.addEventListener("click", function () {
      if (most && most.hubZavrni) most.hubZavrni(p.id);
    });
    tipke.appendChild(zavrni);

    li.appendChild(telo);
    li.appendChild(koda);
    li.appendChild(tipke);
    return li;
  }

  function fokusirajPotrditev() {
    var gumb = document.querySelector("#seznamPrijav button[data-potrdi]");
    if (gumb) {
      try { gumb.focus(); } catch (e) {}
    }
  }

  // ----------------------------------------------------------------
  // Odzivi mostu
  // ----------------------------------------------------------------

  // ----------------------------------------------------------------
  // Prijavno okno (Safeer Control / Safeer OS na racunalniku)
  // ----------------------------------------------------------------

  var prijava = { qr: false, koda: false, krogNeuspel: false, cakalnik: null, ponovno: null };

  /**
   * Control, ki ni povezan (ne z zetonom ne s krogom zaupanja) in sredisce ne tece tu. Clan kroga
   * zaupanja se poveze sam s podpisom; prijavno okno dobi sele, ce to ne uspe.
   */
  function jeNepovezan() {
    if (!stanje.control || stanje.hubTece || (stanje.znan && stanje.seznanjen) || stanje.vKrogu) return false;
    return !(stanje.clanKroga && !prijava.krogNeuspel);
  }

  function jePrijavnoOkno() { return jeNepovezan() && !stanje.brezPovezaveIzbrano; }

  /** Uporabnik je izbral »Nadaljuj brez povezave«: namesto prijave kartica »Poveži naprave«. */
  function jeBrezPovezave() { return jeNepovezan() && !!stanje.brezPovezaveIzbrano; }

  // »Poveži novo napravo« (Safeer Control): QR koda sredisca za nov telefon ali tablico.
  var vabiloOdprto = false;
  function narisiVabilo(p) {
    var qr = el("vabiloQr");
    if (p.svg) {
      qr.innerHTML = p.svg;
      qr.hidden = false;
      besedilo("opombaVabilo", t("prijavaQrOsvezi"));
    } else if (p.pridruzen) {
      qr.hidden = true;
      vabiloOdprto = false;
      besedilo("gumbVabilo", t("vabiloGumb"));
      besedilo("opombaVabilo", t("vabiloPridruzen", { ime: p.pridruzen }));
    } else if (p.napaka) {
      qr.hidden = true;
      vabiloOdprto = false;
      besedilo("gumbVabilo", t("vabiloGumb"));
      besedilo("opombaVabilo", t(p.napaka === "hub_star" ? "vabiloHubStar" : "vabiloNapaka"));
    }
  }
  function preklopiVabilo(odpri) {
    if (!most || !most.zacniVabilo) return;
    vabiloOdprto = odpri === undefined ? !vabiloOdprto : !!odpri;
    besedilo("gumbVabilo", t(vabiloOdprto ? "vabiloZapri" : "vabiloGumb"));
    if (vabiloOdprto) {
      besedilo("opombaVabilo", t("prijavaQrPripravljam"));
      most.zacniVabilo();
    } else {
      el("vabiloQr").hidden = true;
      besedilo("opombaVabilo", "");
      most.prekiniVabilo();
    }
  }
  window.safeerLinkOdpri = function (kaj, napravaId) {
    if (kaj === "prijava") {
      stanje.brezPovezaveIzbrano = false;
      document.body.classList.add("prijava");
      pokazi("zaslonPrijava", true);
      ["zaslonHubTu", "zaslonBrezHuba", "zaslonPreseljen", "zaslonSeznanitev", "zaslonPovezan", "zaslonBrezPovezave", "hubStikalo"].forEach(function (id) { pokazi(id, false); });
      zacniPrijavo();
      narisiLokalnoKodo();
      return;
    } else if (kaj === "novaNaprava") {
      if (typeof izberiRazdelek === "function") izberiRazdelek("naprave");
      preklopiVabilo(true);
      var p = el("panelDodaj");
      if (p && p.scrollIntoView) p.scrollIntoView({ block: "start" });
    } else if (kaj === "daljinec") {
      var cilj = (napravaId && typeof najdiNapravo === "function") ? najdiNapravo(napravaId) : null;
      if (!cilj && typeof napravaZaDaljinec === "function") cilj = napravaZaDaljinec();
      if (cilj && window.SafeerDaljinec) {
        if (typeof oznaciRazdelek === "function") oznaciRazdelek("daljinec");
        window.SafeerDaljinec.odpri(cilj);
      } else if (typeof izberiRazdelek === "function") {
        izberiRazdelek("daljinec");
      }
    } else if (kaj === "naprave" || kaj === "mape" || kaj === "poslji" || kaj === "sync") {
      if (typeof izberiRazdelek === "function") izberiRazdelek(kaj);
    }
  };

  function zacniPrijavo(tiho) {
    pokazi("gumbBrezPovezave", !!stanje.brezPovezave);
    // »Zaupaj temu racunalniku« zna samo Safeer Control / Linux (most.nastaviZaupanje).
    pokazi("prijavaZaupanje", !!(most && most.nastaviZaupanje));
    var kljukica = el("prijavaZaupaj");
    if (kljukica) kljukica.checked = !!stanje.zaupajOkno;
    if (most && !most.zacniQr) {
      // Stran je novejsa od programa, ki tece (posodobitev med tekom): povemo, kaj pomaga.
      besedilo("opombaQr", t("prijavaZnovaZazeni"));
      return;
    }
    if (prijava.qr || !most) return;
    prijava.qr = true;
    // Odgovor pride v nekaj sekundah; ce ga ni, uporabnik ne sme gledati »Pripravljam kodo« v nedogled.
    if (prijava.cakalnik) clearTimeout(prijava.cakalnik);
    prijava.cakalnik = setTimeout(function () {
      prijava.cakalnik = null;
      if (prijava.qr && !(el("qrSlika") && el("qrSlika").querySelector("svg"))) narisiQr({ napaka: "ni_huba" });
    }, 15000);
    var okvir = el("qrSlika");
    if (!tiho && okvir && !okvir.querySelector("svg")) {
      okvir.classList.remove("prazno");
      okvir.innerHTML = "";
      var cakam = document.createElement("span");
      cakam.className = "qrCakam";
      cakam.textContent = t("prijavaQrPripravljam");
      okvir.appendChild(cakam);
      pokazi("gumbQrZnova", false);
      besedilo("opombaQr", "");
    }
    most.zacniQr();
  }

  function koncajPrijavo() {
    if (prijava.ponovno) { clearTimeout(prijava.ponovno); prijava.ponovno = null; }
    if (prijava.qr && most && most.prekiniQr) most.prekiniQr();
    prijava.qr = false;
    prijava.koda = false;
  }

  function narisiQr(podatki) {
    if (prijava.cakalnik) { clearTimeout(prijava.cakalnik); prijava.cakalnik = null; }
    var okvir = el("qrSlika");
    if (!okvir) return;
    if (podatki && podatki.svg) {
      // SVG narise program sam (python3-qrcode) iz nase povezave; z omrezja ne pride nic.
      okvir.classList.remove("prazno");
      okvir.innerHTML = String(podatki.svg).replace(/^<\?xml[^>]*>\s*/, "");
      besedilo("opombaQr", t("prijavaQrOsvezi"));
      pokazi("gumbQrZnova", false);
      return;
    }
    var n = (podatki && podatki.napaka) || "";
    prijava.qr = false;
    if (!okvir.querySelector("svg")) {
      okvir.innerHTML = "";
      okvir.classList.add("prazno");
    }
    if (!n) {
      besedilo("opombaQr", t("prijavaBrezQr"));
      return;
    }
    besedilo("opombaQr", t(n === "hub_star" ? "prijavaHubStar" : n === "prevec_prijav" ? "prijavaPrevec" : "prijavaNiHuba"));
    pokazi("gumbQrZnova", true);
    // Safeer Linka (se) ni: iscemo naprej sami v ozadju, vsakih 8 s
    if (n === "ni_huba" && jePrijavnoOkno()) {
      if (prijava.ponovno) clearTimeout(prijava.ponovno);
      prijava.ponovno = setTimeout(function () { prijava.ponovno = null; if (jePrijavnoOkno()) zacniPrijavo(true); }, 8000);
    }
  }

  /** Klik v polje za kodo: sredisce pokaze kodo (seznanitev s kodo, SPAKE2). */
  function zacniKodo() {
    if (prijava.koda || !most) return;
    prijava.koda = true;
    besedilo("opombaPrijavaKoda", t("iscem"));
    if (stanje.znan) most.seznani();
    else { povezujemPoIskanju = true; most.poisciHub(); }
  }

  function posljiKodo() {
    var vnos = el("prijavaVnosKode");
    var koda = vnos ? String(vnos.value || "").replace(/\D/g, "") : "";
    if (koda.length !== 6) {
      besedilo("opombaPrijavaKoda", t("prijavaKodaSestMest"));
      if (vnos) try { vnos.focus(); } catch (e) {}
      if (!prijava.koda) zacniKodo();
      return;
    }
    besedilo("opombaPrijavaKoda", t("prijavaPreverjam"));
    if (most) most.potrdiKodo(koda);
  }

  /** Ali je iskanje sprozil gumb za povezavo; takrat gremo naprej brez novega klika. */
  var povezujemPoIskanju = false;

  window.safeerLinkOdziv = function (vrsta, podatki) {
    try {
      if (vrsta === "hub") {
        if (podatki && podatki.najden) {
          stanje.znan = true;
          stanje.tezava = false;
          stanje.preseljen = false;
          besedilo("naslovHuba", prijaznaHisa(podatki.naslov));
          osveziStanje();
          if (povezujemPoIskanju) {
            povezujemPoIskanju = false;
            if (most) most.seznani();
          }
        } else {
          povezujemPoIskanju = false;
          if (stanje.clanKroga && !prijava.krogNeuspel) { prijava.krogNeuspel = true; narisiZaslon(); }
          besedilo("opombaIskanje", t("niNajden"));
          besedilo("opombaSeznanitev", t("niNajden"));
          narisiStanje();
        }
      } else if (vrsta === "hub-tu") {
        stanje.hubTece = !!(podatki && podatki.tece);
        stanje.hubPovezanih = (podatki && podatki.naprav) || 0;
        hubPodpis = "";
        hubOsvezi();
      } else if (vrsta === "hub-prijave") {
        stanje.prijave = podatki || [];
        narisiHub();
        narisiZaslon();
      } else if (vrsta === "hub-seznanjene") {
        stanje.hubNaprave = podatki || [];
        narisiHub();
      } else if (vrsta === "preseljen") {
        stanje.preseljen = true;
        besedilo("noviNaslov", prijaznaHisa(podatki && podatki.naslov));
        narisiZaslon();
      } else if (vrsta === "koda") {
        pokazi("kodaBlok", true);
        besedilo("kodaStevilke", String(podatki));
        besedilo("opombaSeznanitev", t("cakamNaPotrditev"));
        var g = el("gumbSeznani");
        if (g) g.disabled = true;
      } else if (vrsta === "qr") {
        narisiQr(podatki);
      } else if (vrsta === "lokalnaKoda") {
        stanje.lokalnaKoda = String(podatki || "");
        narisiLokalnoKodo();
      } else if (vrsta === "brezPovezave") {
        var sporociloOs = podatki && podatki.os === false ? t("prijavaOsSeNastaja") : "";
        besedilo("opombaBrezPovezave", sporociloOs);
        besedilo("opombaBrezPovezaveOs", sporociloOs);
      } else if (vrsta === "nacin" && jePrijavnoOkno()) {
        besedilo("opombaPrijavaKoda", t("prijavaKodaNaSredisce"));
        var vp = el("prijavaVnosKode");
        if (vp) try { vp.focus(); } catch (e) {}
      } else if (vrsta === "kodaNiSprejeta" && jePrijavnoOkno()) {
        var rp = (podatki && podatki.razlog) || "napacna_koda";
        besedilo("opombaPrijavaKoda", t(rp === "prevec_poskusov" ? "napPrevecPoskusov"
          : (rp === "prijava_ne_obstaja" ? "napPrijavaPotekla" : "napNapacnaKoda")));
        if (rp === "prevec_poskusov" || rp === "prijava_ne_obstaja") prijava.koda = false;
        var vk = el("prijavaVnosKode");
        if (vk) { vk.value = ""; try { vk.focus(); } catch (e) {} }
      } else if (vrsta === "nacin") {
        // Nov Hub: kodo pokaze gostitelj, uporabnik jo prepise sem.
        // Starejsi Hub: kodo pokazemo mi, potrdi se na gostitelju.
        var gs = el("gumbSeznani");
        if (gs) gs.disabled = true;
        if (podatki && podatki.nacin === "koda_na_gostitelju") {
          // Gumb umaknemo: zdaj je na vrsti vnos kode, ne se en klik na isto stvar.
          pokazi("gumbSeznani", false);
          pokazi("kodaBlok", false);
          pokazi("vnosKodeBlok", true);
          besedilo("opombaSeznanitev", "");
          var vnos = el("vnosKode");
          if (vnos) { vnos.value = ""; try { vnos.focus(); } catch (e) {} }
        } else {
          pokazi("vnosKodeBlok", false);
          pokazi("kodaBlok", true);
          besedilo("kodaStevilke", String((podatki && podatki.koda) || "------"));
          besedilo("opombaSeznanitev", t("cakamNaPotrditev"));
        }
      } else if (vrsta === "kodaNiSprejeta") {
        var razlog = (podatki && podatki.razlog) || "napacna_koda";
        var kljucNapake = razlog === "prevec_poskusov" ? "napPrevecPoskusov"
          : (razlog === "prijava_ne_obstaja" ? "napPrijavaPotekla" : "napNapacnaKoda");
        besedilo("opombaSeznanitev", t(kljucNapake));
        if (razlog === "prevec_poskusov" || razlog === "prijava_ne_obstaja") {
          pokazi("vnosKodeBlok", false);
          pokazi("gumbSeznani", true);
          var gz = el("gumbSeznani");
          if (gz) gz.disabled = false;
        } else {
          var v2 = el("vnosKode");
          if (v2) { v2.value = ""; try { v2.focus(); } catch (e) {} }
        }
      } else if (vrsta === "seznanitev") {
        if (podatki && jePrijavnoOkno()) besedilo("opombaPrijavaKoda", t("prijavaUspela"));
        var gumb = el("gumbSeznani");
        if (gumb) gumb.disabled = false;
        if (podatki) {
          stanje.seznanjen = true;
          narisiZaslon();
          poveziSe();
        } else {
          pokazi("kodaBlok", false);
          pokazi("vnosKodeBlok", false);
          pokazi("gumbSeznani", true);
          besedilo("opombaSeznanitev", t("niPotrjeno"));
        }
      } else if (vrsta === "ukaz") {
        if (window.SafeerDaljinec) window.SafeerDaljinec.odziv(podatki);
      } else if (vrsta === "govor") {
        if (window.SafeerDaljinec) window.SafeerDaljinec.govor(podatki);
      } else if (vrsta === "naprave") {
        stanje.naprave = podatki || [];
        if (window.SafeerDaljinec) window.SafeerDaljinec.naprave(stanje.naprave);
        if (deljenje.naprava && !stanje.naprave.some(function (n) { return n.id === deljenje.naprava.id; })) zapriDeljenje();
        narisiNaprave();
        narisiPrejemnike();
        narisiMeni();
      } else if (vrsta === "predvajanje") {
        stanje.predvajanje = podatki;
        narisiPredvajanje();
      } else if (vrsta === "poslano") {
        var kam = stanje.prejemnik ? prijaznoIme(stanje.prejemnik) : t("televizor");
        besedilo("opombaCast", t("poslanoNa", { ime: kam }));
      } else if (vrsta === "vabilo") {
        narisiVabilo(podatki || {});
      } else if (vrsta === "pozabljeno") {
        besedilo("opombaPozabi", t("pozabljeno"));
        stanje.seznanjen = false;
        stanje.povezan = false;
        narisiVse();
      } else if (vrsta === "sinhronizacija") {
        narisiSync();
        if (podatki && podatki.vklopljena) {
          besedilo("opombaSync", podatki.dodanih
            ? t("syncPrejeto", { n: podatki.dodanih })
            : t("syncTece"));
        } else {
          besedilo("opombaSync", t("syncUgasnjena"));
        }
      } else if (vrsta === "deljeneMape") {
        stanje.deljeneMape = (podatki && podatki.mape) || [];
        stanje.standardneDeljene = !!(podatki && podatki.standardne);
        narisiMape();
      } else if (vrsta === "stanje") {
        // Most je zamenjal Hub (npr. vklop/izklop sredisca tu): znova preberemo stanje.
        stanje.naprave = [];
        stanje.povezan = false;
        osveziStanje();
      } else if (vrsta === "povezava") {
        stanje.povezan = !!podatki;
        stanje.tezava = false;
        narisiNaprave();
        narisiStanje();
      } else if (vrsta === "deljenje") {
        naDeljenje(podatki);
      } else if (vrsta === "prejeto") {
        naPrejeto(podatki);
      } else if (vrsta === "preimenovano") {
        naPreimenovano(podatki);
      } else if (vrsta === "napaka") {
        // Tehnicnega besedila uporabniku ne kazemo: povemo, kaj to pomeni zanj.
        // Zavrnitev enega dejanja (stran ni primerna, ukaz ni uspel ...) ni tezava povezave:
        // glava ostane zelena, sporocilo se pokaze ob dejanju.
        if (!jeMehkaNapaka(podatki)) stanje.tezava = true;
        var sporocilo = izNapake(podatki);
        besedilo("opombaNaprave", sporocilo);
        besedilo("opombaIskanje", sporocilo);
        besedilo("opombaCast", sporocilo);
        besedilo("opombaSeznanitev", sporocilo);
        if (jePrijavnoOkno()) besedilo("opombaPrijavaKoda", sporocilo);
        // Clan kroga, ki ga sredisce ne sprejme vec: zdaj potrebuje prijavo (QR ali koda).
        var kodaNapake = podatki && typeof podatki === "object" ? podatki.koda : "";
        if (stanje.clanKroga && !prijava.krogNeuspel && kodaNapake === "naprava_ni_znana") {
          prijava.krogNeuspel = true;
          narisiZaslon();
        }
        narisiStanje();
      }
    } catch (e) {
      // Stran nikoli ne sme pasti zaradi odziva.
    }
  };

  /** Iz tehnicne napake naredi poved, ki uporabniku pove, kaj naj naredi. */
  /** Napaka pride kot besedilo ali kot {koda, sporocilo}; koda ima prednost. */
  var MEHKE_NAPAKE = { stran_ni_primerna: 1, samo_http: 1, ukaz_ni_uspel: 1, zaznamki_niso_poslani: 1,
                       sync_ni_nastavljena: 1, zdruzevanje_ni_koncano: 1, naprava_ni_znana: 1 };

  function jeMehkaNapaka(podatki) {
    return !!(podatki && typeof podatki === "object" && MEHKE_NAPAKE[String(podatki.koda || "")]);
  }

  function izNapake(podatki) {
    if (podatki && typeof podatki === "object") {
      var kljuc = NAPAKE[String(podatki.koda || "")];
      if (kljuc) {
        var niz = t(kljuc);
        if (niz) return niz;
      }
      return clovesko(String(podatki.sporocilo || ""));
    }
    return clovesko(String(podatki));
  }

  function clovesko(sporocilo) {
    var m = (sporocilo || "").toLowerCase();
    if (m.indexOf("unauthorized") >= 0 || m.indexOf("401") >= 0 ||
        m.indexOf("ni povezan") >= 0) {
      return t("povezaveNi");
    }
    if (m.indexOf("websocket") >= 0 || m.indexOf("connection") >= 0 ||
        m.indexOf("povezava") >= 0 || m.indexOf("timeout") >= 0) {
      return t("povezaveNi");
    }
    if (m.indexOf("http") >= 0 && m.indexOf("naslov") >= 0) {
      return t("neMorePoslati");
    }
    // Ce sporocila ne prepoznamo, je ze napisano po slovensko iz mostu --
    // a le kadar ni videti tehnicno.
    if (/[<>{}]|error|exception|traceback|failed/i.test(sporocilo)) {
      return t("tezava");
    }
    return sporocilo || t("tezava");
  }

  // ----------------------------------------------------------------
  // Deljenje z izbrano napravo: zaslon, datoteka, besedilo
  //
  // Uporabnik se dotakne naprave, izbere, kaj deli, in dobi en gumb "Poslji na napravo".
  // Besedilo vpise tu; datoteko poisce v sistemskem oknu; zaslon dovoli v sistemskem
  // vprasanju in ga lahko kadar koli prekine.
  // ----------------------------------------------------------------

  var znaDeliti = !!(most && most.posljiBesedilo);
  // Katere vrste deljenja zna ta naprava: televizor poslje besedilo, ne pa datoteke ali zaslona.
  var znaVrsto = {
    besedilo: znaDeliti,
    datoteka: !!(most && most.izberiDatoteko),
    zaslon: !!(most && most.zacniDeljenjeZaslona)
  };
  var deljenje = { naprava: null, vrsta: "" };
  var zaslonDeljenje = { tece: false, ime: "", cilj: "" };

  function odpriDeljenje(naprava, samoIme, hubVnos) {
    if (!znaDeliti && !hubVnos) return;
    deljenje.naprava = naprava;
    deljenje.vrsta = "";
    deljenje.samoIme = !!samoIme;
    deljenje.hubVnos = !!hubVnos;
    odvzemam = "";
    besedilo("gumbOdstrani", t("odstrani"));
    pokazi("gumbOdstrani", !!hubVnos);
    besedilo("deljenjeNaslov", samoIme ? prijaznoIme(naprava) : t("deliZ", { ime: prijaznoIme(naprava) }));
    besedilo("opombaDeljenje", "");
    besedilo("deljenjeOpis", "");
    pokazi("deljenjeBesedilo", false);
    pokazi("gumbPosljiNaNapravo", false);
    pokazi("preimenujBlok", false);
    // Daljinec: napravo, ki javi zmoznost "remote" ali je TV/zaslon, je mogoce upravljati (Safeer Control).
    var znaDaljinec = !samoIme && !!(most && most.ukaz) && (((naprava.zmoznosti || []).indexOf("remote") >= 0) || naprava.platforma === "tv" || naprava.vrsta === "screen" || naprava.vloga === "receiver") && !!window.SafeerDaljinec;
    pokazi("gumbDaljinec", znaDaljinec);
    pokazi("bliznjiceZaslona", znaDaljinec);
    pokazi("izbireDeljenja", !samoIme);
    pokazi("opisIzbire", !samoIme);
    var izbire = document.querySelectorAll("#izbireDeljenja .izbira");
    var zasedena = !samoIme && !!naprava.zasedenaOd && naprava.zasedenaOd !== stanje.idNaprave;
    for (var i = 0; i < izbire.length; i++) {
      izbire[i].classList.remove("izbrana");
      izbire[i].disabled = zasedena;
      izbire[i].hidden = !znaVrsto[izbire[i].getAttribute("data-vrsta")];
    }
    if (zasedena) besedilo("opombaDeljenje", t("zasedenaCakaj", { ime: naprava.zasedenaOdIme || naprava.zasedenaOd }));
    pokazi("panelDeljenje", true);
    // Glava strani je pripeta na vrh; plosco potisnemo tik pod njo, da je naslov "Deli z" viden.
    var p = el("panelDeljenje");
    var glava = document.querySelector("header.glava");
    if (p) {
      try {
        var vrh = p.getBoundingClientRect().top + (window.pageYOffset || 0) - ((glava ? glava.offsetHeight : 0) + 8);
        window.scrollTo({ top: Math.max(0, vrh), behavior: "smooth" });
      } catch (e) {}
    }
    // Daljinec: fokus takoj na prvi gumb plosce (levo/desno: Preimenuj, Odstrani, Zapri; dol: izbire),
    // sicer bi ga smerne tipke odnesle na X v glavi. Ob zapiranju se vrne na vrstico naprave.
    deljenje.fokusNazaj = document.activeElement;
    if (stanje.televizor) {
      setTimeout(function () {
        var prvi = samoIme ? el("gumbPreimenuj") : (document.querySelector("#panelDeljenje .izbira:not([hidden])") || el("gumbPreimenuj"));
        try { if (prvi) prvi.focus(); } catch (e) {}
      }, 60);
    }
  }

  function zapriDeljenje() {
    deljenje.naprava = null;
    deljenje.vrsta = "";
    pokazi("panelDeljenje", false);
    var nazaj = deljenje.fokusNazaj;
    deljenje.fokusNazaj = null;
    if (stanje.televizor && nazaj && nazaj.focus && document.body.contains(nazaj)) {
      try { nazaj.focus(); } catch (e) {}
    }
  }

  function odpriPreimenovanje() {
    var n = deljenje.naprava;
    if (!n) return;
    pokazi("preimenujBlok", true);
    var v = el("vnosImena");
    if (v) {
      v.value = prijaznoIme(n);
      v.setAttribute("placeholder", t("vnesiIme"));
      try { v.focus(); v.select(); } catch (e) {}
    }
  }

  function shraniIme() {
    var n = deljenje.naprava;
    if (!n) return;
    var v = el("vnosImena");
    var ime = v ? String(v.value || "").trim() : "";
    // Svoje ime naprava sporoci Safeer Linku (vidijo ga vsi); imena drugih naprav so krajevna.
    if (n.id !== stanje.idNaprave) {
      if (ime === (n.ime || "").trim()) ime = "";
      if (shraniVzdevek(n.id, ime)) {
        pokazi("preimenujBlok", false);
        besedilo("opombaDeljenje", t("preimenovano"));
        besedilo("deljenjeNaslov", deljenje.samoIme ? prijaznoIme(n) : t("deliZ", { ime: prijaznoIme(n) }));
        narisiVse();
        return;
      }
    }
    if (!most || !most.preimenujNapravo) return;
    besedilo("opombaDeljenje", t("posiljam"));
    most.preimenujNapravo(n.id, ime);
  }

  /** Odvzem dostopa napravi s plosce: prvi pritisk vprasa, drugi odvzame. */
  function odstraniNapravo() {
    var n = deljenje.naprava;
    if (!n || !deljenje.hubVnos) return;
    if (odvzemam !== n.id) {
      odvzemam = n.id;
      besedilo("gumbOdstrani", t("sePotrdi"));
      return;
    }
    odvzemam = "";
    if (most && most.hubPreklici) most.hubPreklici(n.id);
    zapriDeljenje();
  }

  /** Odziv mostu "preimenovano": {id, ime}. Ime pride nazaj tudi v novem seznamu naprav. */
  function naPreimenovano(p) {
    pokazi("preimenujBlok", false);
    besedilo("opombaDeljenje", t("preimenovano"));
    if (p && deljenje.naprava && deljenje.naprava.id === p.id) {
      deljenje.naprava.ime = p.ime || deljenje.naprava.ime;
      besedilo("deljenjeNaslov", deljenje.samoIme ? prijaznoIme(deljenje.naprava) : t("deliZ", { ime: prijaznoIme(deljenje.naprava) }));
    }
  }

  function izberiVrsto(vrsta) {
    deljenje.vrsta = vrsta;
    var izbire = document.querySelectorAll("#izbireDeljenja .izbira");
    for (var i = 0; i < izbire.length; i++) {
      izbire[i].classList.toggle("izbrana", izbire[i].getAttribute("data-vrsta") === vrsta);
    }
    besedilo("deljenjeOpis", vrsta === "zaslon" ? t("zaslonOpis") : (vrsta === "datoteka" ? t("datotekaOpis") : t("besediloOpis")));
    pokazi("deljenjeBesedilo", vrsta === "besedilo");
    pokazi("gumbPosljiNaNapravo", true);
    besedilo("opombaDeljenje", "");
    if (vrsta === "besedilo") {
      var v = el("deljenjeBesedilo");
      if (v) { try { v.focus(); } catch (e) {} }
    }
  }

  function posljiNaNapravo() {
    var n = deljenje.naprava;
    if (!most || !n || !deljenje.vrsta) return;
    var ime = prijaznoIme(n);
    if (deljenje.vrsta === "besedilo") {
      var v = el("deljenjeBesedilo");
      var vsebina = v ? String(v.value || "").trim() : "";
      if (!vsebina) { try { v.focus(); } catch (e) {} return; }
      besedilo("opombaDeljenje", t("posiljam"));
      most.posljiBesedilo(n.id, vsebina);
    } else if (deljenje.vrsta === "datoteka") {
      besedilo("opombaDeljenje", "");
      most.izberiDatoteko(n.id);
    } else if (deljenje.vrsta === "zaslon") {
      besedilo("opombaDeljenje", t("zaslonZaganjam"));
      most.zacniDeljenjeZaslona(n.id, ime);
    }
  }

  function narisiZaslonDeljenje() {
    pokazi("panelZaslonTece", zaslonDeljenje.tece);
    if (zaslonDeljenje.tece) {
      besedilo("zaslonTeceBesedilo", t("zaslonTeceNa", { ime: zaslonDeljenje.ime || zaslonDeljenje.cilj || t("naprava") }));
    }
  }

  function osveziZaslonDeljenje() {
    if (!most || !most.deljenjeZaslonaStanje) return;
    try {
      var s = JSON.parse(most.deljenjeZaslonaStanje() || "{}");
      zaslonDeljenje.tece = !!s.tece;
      zaslonDeljenje.ime = s.ime || "";
      zaslonDeljenje.cilj = s.cilj || "";
    } catch (e) {}
    narisiZaslonDeljenje();
  }

  /** Odziv mostu "deljenje": {vrsta, stanje, cilj, ime, sporocilo, odstotek}. */
  function naDeljenje(p) {
    if (!p) return;
    var imeCilja = "";
    var n = deljenje.naprava;
    if (n && n.id === p.cilj) imeCilja = prijaznoIme(n);
    if (!imeCilja) {
      for (var i = 0; i < stanje.naprave.length; i++) {
        if (stanje.naprave[i].id === p.cilj) { imeCilja = prijaznoIme(stanje.naprave[i]); break; }
      }
    }
    if (!imeCilja) imeCilja = p.ime || p.cilj || t("naprava");

    if (p.vrsta === "zaslon") {
      if (p.stanje === "tece") {
        zaslonDeljenje.tece = true;
        zaslonDeljenje.ime = p.ime || imeCilja;
        zaslonDeljenje.cilj = p.cilj;
        besedilo("opombaDeljenje", t("zaslonTeceNa", { ime: zaslonDeljenje.ime }));
      } else if (p.stanje === "zaganjam") {
        besedilo("opombaDeljenje", t("zaslonZaganjam"));
      } else {
        zaslonDeljenje.tece = false;
        besedilo("opombaDeljenje", (p.sporocilo || p.koda) ? napakaDeljenja(p) : t("zaslonKoncano"));
      }
      narisiZaslonDeljenje();
      return;
    }
    if (p.stanje === "posiljam") {
      besedilo("opombaDeljenje", (p.vrsta === "datoteka" && typeof p.odstotek === "number")
        ? t("posiljamOdstotek", { ime: p.ime || "", n: p.odstotek })
        : t("posiljam"));
    } else if (p.stanje === "poslano") {
      besedilo("opombaDeljenje", t("poslanoNapravi", { ime: imeCilja }));
      if (p.vrsta === "besedilo") {
        var v = el("deljenjeBesedilo");
        if (v) v.value = "";
      }
    } else if (p.stanje === "napaka") {
      besedilo("opombaDeljenje", napakaDeljenja(p));
    }
  }

  /** Napaka deljenja v jeziku uporabnika: koda ima prednost pred besedilom Huba. */
  function napakaDeljenja(p) {
    if (p.koda === "naprava_zasedena") return t("napZasedena", { ime: p.zasedenaOd || t("naprava") });
    if (p.koda === "napacen_odtis") return t("napOdtis");
    if (p.koda === "dovoljenje_zavrnjeno") return t("napDovoljenje");
    if (p.koda === "naprava_ni_povezana") return t("niDosegljiv", { ime: t("naprava") });
    return t("napDeljenje", { napaka: clovesko(p.sporocilo || "") });
  }

  /** Odziv mostu "prejeto": kaj nam je poslala druga naprava. */
  function naPrejeto(p) {
    if (!p) return;
    var od = p.od || t("naprava");
    if (p.vrsta === "besedilo") besedilo("opombaNaprave", t("prejetoBesedilo", { ime: od }));
    else if (p.vrsta === "datoteka") besedilo("opombaNaprave", t("prejetaDatoteka", { ime: p.ime || "", mapa: p.mapa || "" }));
    else if (p.vrsta === "zaslon" && p.dejanje === "start") besedilo("opombaNaprave", t("prejetZaslon", { ime: od }));
    else if (p.vrsta === "stran") besedilo("opombaNaprave", t("prejetaStran", { ime: od }));
  }

  function pripraviDeljenje() {
    naKlik("gumbDeljenjeZapri", zapriDeljenje);
    naKlik("gumbPosljiNaNapravo", posljiNaNapravo);
    naKlik("gumbPreimenuj", odpriPreimenovanje);
    naKlik("gumbOdstrani", odstraniNapravo);
    naKlik("gumbShraniIme", shraniIme);
    var vnosImena = el("vnosImena");
    if (vnosImena) vnosImena.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); shraniIme(); } });
    naKlik("gumbPrekiniZaslon", function () {
      if (most && most.koncajDeljenjeZaslona) most.koncajDeljenjeZaslona();
    });
    var izbire = document.querySelectorAll("#izbireDeljenja .izbira");
    for (var i = 0; i < izbire.length; i++) {
      (function (gumb) {
        gumb.addEventListener("click", function () { izberiVrsto(gumb.getAttribute("data-vrsta")); });
      })(izbire[i]);
    }
    var v = el("deljenjeBesedilo");
    if (v) v.setAttribute("placeholder", t("vnesiBesedilo"));
    osveziZaslonDeljenje();
  }

  // ----------------------------------------------------------------
  // Dejanja
  // ----------------------------------------------------------------

  function osveziStanje() {
    if (!most) {
      stanje.tezava = true;
      narisiStanje();
      return;
    }
    var s;
    try {
      s = JSON.parse(most.stanje());
    } catch (e) {
      s = { znan: false, seznanjen: false };
    }
    stanje.znan = !!s.znan;
    stanje.seznanjen = !!s.seznanjen;
    stanje.hub = s.hub || "";
    stanje.imeNaprave = s.naprava || "";
    stanje.idNaprave = s.id || "";
    stanje.control = !!s.control;
    stanje.vKrogu = !!s.vKrogu;
    stanje.clanKroga = !!s.clanKroga;
    stanje.brezPovezaveIzbrano = !!s.brezPovezaveIzbrano;
    stanje.zaupajOkno = !!s.zaupajOkno;
    stanje.brezPovezave = !!s.brezPovezave;
    stanje.deljeneMape = s.deljeneMape || [];
    stanje.standardneDeljene = !!s.standardneDeljene;
    stanje.lokalnaKoda = s.lokalnaKoda || "";
    narisiLokalnoKodo();
    besedilo("naslovHuba", prijaznaHisa(s.hub));
    narisiVse();
    if (stanje.znan && stanje.seznanjen) poveziSe();
  }

  function poveziSe() {
    if (!most) return;
    try {
      var zadnje = JSON.parse(most.naprave() || "[]");
      if (zadnje.length) stanje.naprave = zadnje;
      most.poveziSe();
    } catch (e) {}
    narisiVse();
  }

  // ----------------------------------------------------------------
  // Zacetek
  // ----------------------------------------------------------------

  document.addEventListener("DOMContentLoaded", function () {
    prevediStran();

    try {
      if (most && most.jeTelevizor && most.jeTelevizor()) stanje.televizor = true;
    } catch (e) {}

    naKlik("gumbDodajMapo", function () {
      if (most && most.dodajDeljenoMapo) most.dodajDeljenoMapo();
    });
    naKlik("gumbStandardneMape", function () {
      if (most && most.deliStandardneMape) most.deliStandardneMape();
    });
    naKlik("gumbZapri", function () {
      if (most) most.zapri();
    });

    naKlik("gumbPoisci", function () {
      besedilo("opombaIskanje", t("iscem"));
      if (most) most.poisciHub();
    });

    naKlik("gumbQrZnova", function () {
      prijava.qr = false;
      zacniPrijavo();
    });
    naKlik("gumbPrijavaNazaj", function () {
      if (most && most.zapri) most.zapri();
    });
    naKlik("gumbBrezPovezaveNazaj", function () {
      if (most && most.zapri) most.zapri();
    });
    naKlik("gumbNovaLokalnaKoda", function () {
      if (most && most.novaLokalnaKoda) {
        var nova = most.novaLokalnaKoda();
        if (nova) {
          stanje.lokalnaKoda = String(nova);
          narisiLokalnoKodo();
        }
      }
    });
    naKlik("gumbPrijavaKoda", posljiKodo);
    naKlik("gumbPoveziNaprave", function () {
      if (most && most.poveziNaprave) most.poveziNaprave();
    });
    naKlik("gumbOdpriOsLokalno", function () {
      besedilo("opombaBrezPovezaveOs", "");
      if (most && most.nadaljujBrezPovezave) most.nadaljujBrezPovezave();
    });
    naKlik("gumbBrezPovezave", function () {
      besedilo("opombaBrezPovezave", "");
      if (most && most.nadaljujBrezPovezave) most.nadaljujBrezPovezave();
    });
    naKlik("gumbVabilo", function () { preklopiVabilo(); });
    var zaupaj = el("prijavaZaupaj");
    if (zaupaj) {
      zaupaj.addEventListener("change", function () {
        if (most && most.nastaviZaupanje) most.nastaviZaupanje(!!zaupaj.checked);
      });
    }
    var vnosPrijava = el("prijavaVnosKode");
    if (vnosPrijava) {
      vnosPrijava.addEventListener("focus", zacniKodo);
      vnosPrijava.addEventListener("input", function () {
        var cisto = String(vnosPrijava.value || "").replace(/\D/g, "").slice(0, 6);
        if (cisto !== vnosPrijava.value) vnosPrijava.value = cisto;
        if (cisto.length === 6) posljiKodo();
      });
      vnosPrijava.addEventListener("keydown", function (e) { if (e.key === "Enter") posljiKodo(); });
    }

    naKlik("gumbNavodila", function () {
      if (most && most.odpri) most.odpri("https://safeer.si/");
    });

    naKlik("gumbSeznani", function () {
      // Ena poteza, en gumb: najprej preverimo, da je Safeer Link res tam
      // (racunalnik je lahko ugasnjen, naslov drugacen), in takoj nadaljujemo
      // do kode. Uporabniku ni treba vedeti, da sta to dva koraka.
      besedilo("opombaSeznanitev", t("iscem"));
      povezujemPoIskanju = true;
      if (most) most.poisciHub();
    });

    naKlik("gumbVnesiKodo", function () {
      var vnos = el("vnosKode");
      var koda = vnos ? String(vnos.value || "").replace(/\D/g, "") : "";
      if (koda.length < 6) {
        besedilo("opombaSeznanitev", t("napNapacnaKoda"));
        return;
      }
      besedilo("opombaSeznanitev", t("preverjamKodo"));
      if (most && most.potrdiKodo) most.potrdiKodo(koda);
    });

    var vnosKode = el("vnosKode");
    if (vnosKode) {
      vnosKode.addEventListener("keydown", function (e) {
        if (e.key === "Enter") {
          e.preventDefault();
          var g = el("gumbVnesiKodo");
          if (g) g.click();
        }
      });
    }

    naKlik("gumbOsvezi", poveziSe);

    naKlik("gumbHubVklopi", function () {
      besedilo("opombaHubVklop", t("prizigam"));
      if (most && most.hubVklopi) most.hubVklopi();
    });

    naKlik("gumbHubIzklopi", function () {
      if (most && most.hubIzklopi) most.hubIzklopi();
    });

    naKlik("gumbHubOsvezi", function () {
      hubPodpis = "";
      hubOsvezi();
    });

    naKlik("gumbPotrdiNaslov", function () {
      if (!most || !most.potrdiNovNaslov) return;
      besedilo("opombaPreselitev", t("preverjamNaslov"));
      most.potrdiNovNaslov();
    });

    var pozabiPotrjujem = false;
    naKlik("gumbPozabi", function () {
      if (!most || !most.pozabiNapravo) return;
      if (!pozabiPotrjujem) {
        pozabiPotrjujem = true;
        besedilo("opombaPozabi", t("pozabiPotrdi"));
        return;
      }
      pozabiPotrjujem = false;
      most.pozabiNapravo();
    });

    var tipke = document.querySelectorAll(".tipke button");
    for (var j = 0; j < tipke.length; j++) {
      (function (tipka) {
        tipka.addEventListener("click", function () {
          if (!most || !stanje.prejemnik) return;
          var ukaz = tipka.getAttribute("data-ukaz");
          var p = stanje.predvajanje;
          if (ukaz === "nazaj" || ukaz === "naprej") {
            var osnova = p ? p.polozaj : 0;
            var cilj = Math.max(0, osnova + (ukaz === "naprej" ? 10 : -10));
            most.nadzor(stanje.prejemnik.id, "seek", cilj);
          } else {
            most.nadzor(stanje.prejemnik.id, ukaz, 0);
          }
        });
      })(tipke[j]);
    }

    narisiSync();
    pripraviDeljenje();
    pazljivNaSmerneTipke();
    osveziStanje();
    hubOsvezi();
    // Na daljincu prvi fokus odloca, kaj uporabnik potrdi: naj bo glavno dejanje,
    // ne krizec za zapiranje.
    setTimeout(fokusirajGlavno, 150);
  });

  /**
   * Zasilni izhod za daljinec. Ce fokus ni na nobenem gumbu (to se na televizorju zgodi,
   * kadar se stran na novo izrise), prvi pritisk na smerno tipko ne premakne nicesar --
   * zato ga porabimo za to, da fokus postavimo na glavno dejanje.
   */
  function pazljivNaSmerneTipke() {
    document.addEventListener("keydown", function (e) {
      var smerna = e.key === "ArrowUp" || e.key === "ArrowDown" ||
                   e.key === "ArrowLeft" || e.key === "ArrowRight";
      if (!smerna) return;
      var kje = document.activeElement;
      if (!kje || kje === document.body || kje === document.documentElement) {
        e.preventDefault();
        fokusirajGlavno();
      }
    }, true);
  }

  function fokusirajGlavno() {
    // Ce kdo caka na potrditev, je to najpomembnejse na zaslonu.
    var potrdi = document.querySelector("#seznamPrijav button[data-potrdi]");
    if (potrdi) {
      try { potrdi.focus(); } catch (err) {}
      return;
    }
    var kandidati = ["gumbSeznani", "gumbPoisci", "gumbHubVklopi", "gumbHubIzklopi",
                     "gumbOsvezi", "gumbHubOsvezi"];
    // Onemogocen gumb ni cilj za daljinec.
    for (var i = 0; i < kandidati.length; i++) {
      var e = el(kandidati[i]);
      if (e && e.offsetParent !== null && !e.disabled) {
        try { e.focus(); } catch (err) {}
        return;
      }
    }
  }

  // ----------------------------------------------------------------
  // Daljinec (daljinec.js): kar potrebuje od te strani, in kako se odpre.
  // ----------------------------------------------------------------

  var pokritoZaDaljinec = [];
  function pokaziDaljinec(odprt) {
    if (odprt) {
      if (daljinecOdprt) return;
      daljinecOdprt = true;
      pokritoZaDaljinec = [];
      // V aplikaciji glava in levi meni ostaneta: daljinec je le se en razdelek.
      var izbor = jeNamizje()
        ? "main > .zaslon:not(#zaslonDaljinec), #hubStikalo"
        : "header.glava, main > .zaslon:not(#zaslonDaljinec), #hubStikalo, footer.opozoriloWifi";
      var kandidati = document.querySelectorAll(izbor);
      for (var i = 0; i < kandidati.length; i++) {
        if (!kandidati[i].hidden) { kandidati[i].hidden = true; pokritoZaDaljinec.push(kandidati[i]); }
      }
      if (jeNamizje()) oznaciRazdelek("daljinec");
    } else {
      if (!daljinecOdprt) return;
      daljinecOdprt = false;
      for (var j = 0; j < pokritoZaDaljinec.length; j++) pokritoZaDaljinec[j].hidden = false;
      pokritoZaDaljinec = [];
      if (jeNamizje() && razdelek === "daljinec") oznaciRazdelek("naprave");
      narisiZaslon();
      var nazaj = el("gumbOsvezi");
      if (stanje.televizor && nazaj) { try { nazaj.focus(); } catch (e) {} }
    }
  }

  /** Ime naprave, na kateri tece Safeer Link (sredisce): ta naprava, naprava z lokalnim naslovom pri Hubu ali naslov Huba. */
  function imeSredisca() {
    if (stanje.hubTece) return stanje.imeNaprave || t("taNaprava");
    var lokalni = { "127.0.0.1": 1, "::1": 1, "localhost": 1, "::ffff:127.0.0.1": 1 };
    for (var i = 0; i < stanje.naprave.length; i++) {
      var n = stanje.naprave[i];
      if (n && n.naslov && lokalni[String(n.naslov)]) return prijaznoIme(n);
    }
    return prijaznaHisa(stanje.hub);
  }

  window.SafeerLinkStran = {
    jezik: jezik,
    prijaznoIme: prijaznoIme,
    televizor: function () { return !!stanje.televizor; },
    sredisce: imeSredisca,
    pokaziDaljinec: pokaziDaljinec
  };

  // Televizor: brez dovoljenja za prekrivanje se Safeer ob ukazu s telefona ne odpre sam.
  function osveziOpozoriloOspredje() {
    var blok = el("opozoriloOspredje");
    if (!blok) return;
    var pokaziGa = false;
    try { pokaziGa = !!(stanje.televizor && most && most.lahkoVOspredje && !most.lahkoVOspredje()); } catch (e) {}
    blok.hidden = !pokaziGa;
  }
  var gumbDovoliOspredje = el("gumbDovoliOspredje");
  if (gumbDovoliOspredje) gumbDovoliOspredje.addEventListener("click", function () {
    try { if (most && most.dovoliOspredje) most.dovoliOspredje(); } catch (e) {}
  });
  osveziOpozoriloOspredje();
  document.addEventListener("visibilitychange", function () { if (document.visibilityState === "visible") osveziOpozoriloOspredje(); });
  window.addEventListener("focus", osveziOpozoriloOspredje);

  var meniGumbi = document.querySelectorAll("#stranskiMeni button[data-razdelek]");
  for (var mi = 0; mi < meniGumbi.length; mi++) {
    meniGumbi[mi].addEventListener("click", function () { izberiRazdelek(this.getAttribute("data-razdelek")); });
  }

  /** Paket Safeer OS na tej napravi: iz kataloga aplikacij (Protocol v1), sicer po platformi. */
  function paketSafeerOs(n) {
    var k = n.aplikacije || {};
    if (k["si.safeer.os"]) return "si.safeer.os";
    if (k["si.safeer.tablet"]) return "si.safeer.tablet";
    return n.platforma === "tablet" ? "si.safeer.tablet" : "si.safeer.os";
  }

  function odpriNaZaslonu(paket, ime) {
    var n = deljenje.naprava;
    if (!n || !most || !most.ukaz) return;
    besedilo("opombaDeljenje", t("odpiramNaZaslonu", { ime: ime, naprava: prijaznoIme(n) }));
    most.ukaz(n.id, "launch_app", JSON.stringify({ package: paket }), "");
  }

  var gumbOdpriSafeerOs = el("gumbOdpriSafeerOs");
  if (gumbOdpriSafeerOs) gumbOdpriSafeerOs.addEventListener("click", function () {
    var n = deljenje.naprava;
    if (n) odpriNaZaslonu(paketSafeerOs(n), "Safeer OS");
  });
  var gumbOdpriBrskalnik = el("gumbOdpriBrskalnik");
  if (gumbOdpriBrskalnik) gumbOdpriBrskalnik.addEventListener("click", function () {
    var n = deljenje.naprava;
    if (n) odpriNaZaslonu(n.platforma === "tablet" ? "si.safeer.tablet" : "si.safeer.tv", "Safeer");
  });

  var gumbDaljinec = el("gumbDaljinec");
  if (gumbDaljinec) gumbDaljinec.addEventListener("click", function () {
    var n = deljenje.naprava;
    if (!n || !window.SafeerDaljinec) return;
    zapriDeljenje();
    window.SafeerDaljinec.odpri(n);
  });
})();
