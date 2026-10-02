/* Safeer OS · Splet – začetna stran vdelanega Safeer Browserja.
 * Ena stran za vse različice Safeer OS (Windows, Linux, Android TV, tablica, telefon).
 * Gostitelj pošlje stanje z window.safeerSpletInit(stanje) (Windows: tudi safeerWindowsInit):
 *   { language, engine, portals: [{title, url, favicon}], tv: bool }
 * Navigacija gre prek mostu webkit.messageHandlers.safeer ({action:'navigate', url}),
 * sicer prek SafeerAndroid.sporocilo(json) ali navadnega location.href.
 */
(function () {
  "use strict";

  var B = {
    sl: { nov: "Nov zavihek", pod: "Varno, hitro in zasebno brskanje znotraj Safeer OS.", isci: "Išči po spletu ali vnesi spletni naslov",
      pojdi: "Išči", bliz: "Bližnjice", dodaj: "Dodaj bližnjico", odstrani: "Odstrani bližnjico", uredi: "Uredi bližnjice", koncano: "Končano", obnovi: "Obnovi privzete",
      predlogi: "Predlogi za vas", vse: "Vse", novice: "Novice", zabava: "Zabava", tehnologija: "Tehnologija", znanost: "Znanost",
      k_potovanja: ["Potovanja", "Odkrij nove kraje", "ideje za potovanja"],
      k_glasba: ["Glasba", "Najboljše vsebine", "nova glasba neodvisnih izvajalcev"],
      k_novice: ["Novice", "Aktualno iz sveta", "novice danes"],
      k_teh: ["Tehnologija", "Odprta koda in orodja", "odprtokodni programi novosti"],
      k_zna: ["Znanost", "Vesolje in narava", "vesolje odkritja"],
      k_film: ["Filmi", "Javni arhivi in klasike", "javno dostopni klasični filmi"] },
    en: { nov: "New tab", pod: "Safe, fast and private browsing inside Safeer OS.", isci: "Search the web or enter an address",
      pojdi: "Search", bliz: "Shortcuts", dodaj: "Add shortcut", odstrani: "Remove shortcut", uredi: "Edit shortcuts", koncano: "Done", obnovi: "Restore defaults",
      predlogi: "Suggestions for you", vse: "All", novice: "News", zabava: "Fun", tehnologija: "Technology", znanost: "Science",
      k_potovanja: ["Travel", "Discover new places", "travel ideas"],
      k_glasba: ["Music", "The best picks", "new music from independent artists"],
      k_novice: ["News", "What's happening", "news today"],
      k_teh: ["Technology", "Open source and tools", "open source software news"],
      k_zna: ["Science", "Space and nature", "space discoveries"],
      k_film: ["Films", "Public archives and classics", "public domain classic films"] },
    de: { nov: "Neuer Tab", pod: "Sicheres, schnelles und privates Surfen in Safeer OS.", isci: "Im Web suchen oder Adresse eingeben",
      pojdi: "Suchen", bliz: "Verknüpfungen", dodaj: "Verknüpfung hinzufügen", odstrani: "Verknüpfung entfernen", uredi: "Verknüpfungen bearbeiten", koncano: "Fertig", obnovi: "Standard wiederherstellen",
      predlogi: "Vorschläge für dich", vse: "Alle", novice: "Nachrichten", zabava: "Unterhaltung", tehnologija: "Technik", znanost: "Wissenschaft",
      k_potovanja: ["Reisen", "Neue Orte entdecken", "Reiseideen"],
      k_glasba: ["Musik", "Die besten Inhalte", "neue Musik unabhängiger Künstler"],
      k_novice: ["Nachrichten", "Aktuelles aus der Welt", "Nachrichten heute"],
      k_teh: ["Technik", "Open Source und Werkzeuge", "Open-Source-Software Neuigkeiten"],
      k_zna: ["Wissenschaft", "Weltall und Natur", "Weltall Entdeckungen"],
      k_film: ["Filme", "Öffentliche Archive und Klassiker", "gemeinfreie klassische Filme"] },
    es: { nov: "Nueva pestaña", pod: "Navegación segura, rápida y privada dentro de Safeer OS.", isci: "Busca en la web o introduce una dirección",
      pojdi: "Buscar", bliz: "Accesos directos", dodaj: "Añadir acceso", odstrani: "Quitar acceso", uredi: "Editar accesos", koncano: "Listo", obnovi: "Restaurar predeterminados",
      predlogi: "Sugerencias para ti", vse: "Todo", novice: "Noticias", zabava: "Ocio", tehnologija: "Tecnología", znanost: "Ciencia",
      k_potovanja: ["Viajes", "Descubre nuevos lugares", "ideas de viaje"],
      k_glasba: ["Música", "Lo mejor", "música nueva de artistas independientes"],
      k_novice: ["Noticias", "Actualidad del mundo", "noticias de hoy"],
      k_teh: ["Tecnología", "Código abierto y herramientas", "novedades software de código abierto"],
      k_zna: ["Ciencia", "Espacio y naturaleza", "descubrimientos del espacio"],
      k_film: ["Películas", "Archivos públicos y clásicos", "películas clásicas de dominio público"] },
    fr: { nov: "Nouvel onglet", pod: "Navigation sûre, rapide et privée dans Safeer OS.", isci: "Rechercher sur le Web ou saisir une adresse",
      pojdi: "Rechercher", bliz: "Raccourcis", dodaj: "Ajouter un raccourci", odstrani: "Retirer le raccourci", uredi: "Modifier les raccourcis", koncano: "Terminé", obnovi: "Rétablir par défaut",
      predlogi: "Suggestions pour vous", vse: "Tout", novice: "Actualités", zabava: "Loisirs", tehnologija: "Technologie", znanost: "Science",
      k_potovanja: ["Voyages", "Découvrez de nouveaux lieux", "idées de voyage"],
      k_glasba: ["Musique", "Le meilleur", "nouvelle musique d’artistes indépendants"],
      k_novice: ["Actualités", "Ce qui se passe", "actualités du jour"],
      k_teh: ["Technologie", "Open source et outils", "nouveautés logiciels libres"],
      k_zna: ["Science", "Espace et nature", "découvertes spatiales"],
      k_film: ["Films", "Archives publiques et classiques", "films classiques du domaine public"] },
    it: { nov: "Nuova scheda", pod: "Navigazione sicura, veloce e privata in Safeer OS.", isci: "Cerca sul Web o inserisci un indirizzo",
      pojdi: "Cerca", bliz: "Scorciatoie", dodaj: "Aggiungi scorciatoia", odstrani: "Rimuovi scorciatoia", uredi: "Modifica scorciatoie", koncano: "Fine", obnovi: "Ripristina predefinite",
      predlogi: "Suggerimenti per te", vse: "Tutto", novice: "Notizie", zabava: "Svago", tehnologija: "Tecnologia", znanost: "Scienza",
      k_potovanja: ["Viaggi", "Scopri nuovi luoghi", "idee di viaggio"],
      k_glasba: ["Musica", "Il meglio", "nuova musica di artisti indipendenti"],
      k_novice: ["Notizie", "Attualità dal mondo", "notizie di oggi"],
      k_teh: ["Tecnologia", "Open source e strumenti", "novità software open source"],
      k_zna: ["Scienza", "Spazio e natura", "scoperte spaziali"],
      k_film: ["Film", "Archivi pubblici e classici", "film classici di pubblico dominio"] }
  };

  var ISKALNIKI = {
    duckduckgo: "https://duckduckgo.com/?q=", google: "https://www.google.com/search?q=",
    brave: "https://search.brave.com/search?q=", bing: "https://www.bing.com/search?q=",
    ecosia: "https://www.ecosia.org/search?q=", startpage: "https://www.startpage.com/do/search?q=",
    qwant: "https://www.qwant.com/?q=", youtube: "https://www.youtube.com/results?search_query="
  };

  // Privzete bližnjice (uporabnik jih zamenja s svojimi). Ikone samo, če jih gostitelj pošlje lokalno.
  var PRIVZETE = [
    { title: "YouTube", url: "https://www.youtube.com" },
    { title: "Google", url: "https://www.google.com" },
    { title: "Gmail", url: "https://mail.google.com" },
    { title: "RTV 365", url: "https://365.rtvslo.si" },
    { title: "Reddit", url: "https://www.reddit.com" },
    { title: "Wikipedia", url: "https://www.wikipedia.org" }
  ];

  // Lastne ilustracije kartic (brez fotografij in logotipov tujih znamk).
  var SLIKE = {
    potovanja: '<defs><linearGradient id="n1" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f7a35c"/><stop offset=".55" stop-color="#b7577a"/><stop offset="1" stop-color="#3b2a52"/></linearGradient></defs>' +
      '<rect width="400" height="200" fill="url(#n1)"/><circle cx="300" cy="78" r="26" fill="#ffd9a0" opacity=".9"/>' +
      '<path d="M0 150 L70 90 L120 125 L190 60 L260 118 L320 80 L400 132 V200 H0Z" fill="#5a3b5f"/>' +
      '<path d="M0 172 L90 128 L160 160 L240 116 L330 158 L400 140 V200 H0Z" fill="#2f2440"/>',
    glasba: '<defs><radialGradient id="n2" cx=".5" cy="0" r="1"><stop offset="0" stop-color="#8fb8ff"/><stop offset=".4" stop-color="#3a3fb0"/><stop offset="1" stop-color="#120c2e"/></radialGradient></defs>' +
      '<rect width="400" height="200" fill="url(#n2)"/>' +
      '<g opacity=".35" fill="#cfe0ff"><path d="M200 0 L120 200 H140Z"/><path d="M200 0 L260 200 H280Z"/><path d="M200 0 L40 200 H70Z"/><path d="M200 0 L350 200 H380Z"/></g>' +
      '<path d="M0 200 V168 q20-26 34 0 q10-40 26-6 q14-30 30 2 q16-44 32-4 q12-22 26 4 q14-38 30-2 q18-30 32 6 q12-26 28 0 q16-40 32-4 q14-24 28 4 q12-34 30-2 q16-28 30 4 q12-30 32 0 V200Z" fill="#0a0716"/>',
    novice: '<rect width="400" height="200" fill="#04102a"/><circle cx="260" cy="250" r="185" fill="#0f3f86"/>' +
      '<circle cx="260" cy="250" r="185" fill="none" stroke="#7cc8ff" stroke-width="4" opacity=".7"/>' +
      '<path d="M120 170 q60-40 120-10 q50 25 150 -20" fill="none" stroke="#4fa3e8" stroke-width="3" opacity=".6"/>' +
      '<path d="M140 120 q70 30 140 0" fill="none" stroke="#4fa3e8" stroke-width="3" opacity=".45"/>' +
      '<g fill="#fff" opacity=".75"><circle cx="40" cy="30" r="1.4"/><circle cx="90" cy="70" r="1"/><circle cx="150" cy="24" r="1.2"/><circle cx="60" cy="120" r="1"/><circle cx="360" cy="40" r="1.3"/></g>',
    teh: '<rect width="400" height="200" fill="#07231f"/>' +
      '<g fill="none" stroke="#57d6ad" stroke-width="2" opacity=".55"><path d="M0 60 H120 L150 90 H260 L290 60 H400"/><path d="M0 140 H90 L120 110 H220 L250 140 H400"/><path d="M200 0 V60 M200 140 V200"/></g>' +
      '<g fill="#57d6ad"><circle cx="150" cy="90" r="5"/><circle cx="260" cy="90" r="5"/><circle cx="120" cy="110" r="5"/><circle cx="250" cy="140" r="5"/></g>' +
      '<rect x="165" y="75" width="70" height="50" rx="8" fill="#0d3a33" stroke="#57d6ad" stroke-width="2"/>',
    zna: '<rect width="400" height="200" fill="#0b0a1f"/>' +
      '<g fill="#fff"><circle cx="30" cy="40" r="1.2"/><circle cx="120" cy="20" r="1"/><circle cx="210" cy="60" r="1.4"/><circle cx="340" cy="30" r="1.1"/><circle cx="380" cy="150" r="1"/><circle cx="60" cy="170" r="1.2"/><circle cx="160" cy="150" r=".9"/></g>' +
      '<circle cx="250" cy="110" r="52" fill="#d9965b"/><ellipse cx="250" cy="110" rx="95" ry="20" fill="none" stroke="#f3d3a5" stroke-width="5" transform="rotate(-18 250 110)"/>',
    film: '<rect width="400" height="200" fill="#1a1410"/>' +
      '<g fill="#2e241c"><rect x="0" y="0" width="400" height="26"/><rect x="0" y="174" width="400" height="26"/></g>' +
      '<g fill="#d9c7a8" opacity=".8"><rect x="16" y="7" width="18" height="12" rx="2"/><rect x="66" y="7" width="18" height="12" rx="2"/><rect x="116" y="7" width="18" height="12" rx="2"/><rect x="166" y="7" width="18" height="12" rx="2"/><rect x="216" y="7" width="18" height="12" rx="2"/><rect x="266" y="7" width="18" height="12" rx="2"/><rect x="316" y="7" width="18" height="12" rx="2"/><rect x="366" y="7" width="18" height="12" rx="2"/>' +
      '<rect x="16" y="181" width="18" height="12" rx="2"/><rect x="66" y="181" width="18" height="12" rx="2"/><rect x="116" y="181" width="18" height="12" rx="2"/><rect x="166" y="181" width="18" height="12" rx="2"/><rect x="216" y="181" width="18" height="12" rx="2"/><rect x="266" y="181" width="18" height="12" rx="2"/><rect x="316" y="181" width="18" height="12" rx="2"/><rect x="366" y="181" width="18" height="12" rx="2"/></g>' +
      '<polygon points="180,70 240,100 180,130" fill="#f4be63"/>'
  };
  var KARTICE = [
    { k: "k_potovanja", slika: "potovanja", zvrst: "zabava" },
    { k: "k_glasba", slika: "glasba", zvrst: "zabava" },
    { k: "k_novice", slika: "novice", zvrst: "novice" },
    { k: "k_teh", slika: "teh", zvrst: "tehnologija" },
    { k: "k_zna", slika: "zna", zvrst: "znanost" },
    { k: "k_film", slika: "film", zvrst: "zabava" }
  ];
  var ZVRSTI = ["vse", "novice", "zabava", "tehnologija", "znanost"];

  var S = { jezik: "sl", iskalnik: "duckduckgo", bliznjice: null, zvrst: "vse", skrite: [], ureja: false };

  // Odstranjene bliznjice (tudi vgrajene): nic ni vsiljeno. Kljuc je naslov brez sheme, www. in koncne posevnice.
  function kljucBliznjice(url) { return String(url || "").replace(/^https?:\/\/(www\.)?/i, "").replace(/\/+$/, "").toLowerCase(); }
  function jeSkrita(url) { return S.skrite.indexOf(kljucBliznjice(url)) >= 0; }
  function shraniSkrite() { try { localStorage.setItem("safeer_splet_skrite", JSON.stringify(S.skrite)); } catch (e) {} }
  function odstraniBliznjico(url) {
    var k = kljucBliznjice(url);
    if (S.skrite.indexOf(k) < 0) S.skrite.push(k);
    shraniSkrite();
    most({ action: "remove_portal", url: url });   // gostitelj si odstranitev zapomni (in ob zagonu poslje "hidden")
    narisiBliznjice();
  }
  function obnoviBliznjice() {
    S.skrite = []; shraniSkrite();
    most({ action: "reset_portals" });
    narisiBliznjice();
  }

  function t(k) { var b = B[S.jezik] || B.en; return b[k] != null ? b[k] : (B.en[k] != null ? B.en[k] : k); }
  function $(id) { return document.getElementById(id); }

  function most(sporocilo) {
    try {
      if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.safeer) {
        window.webkit.messageHandlers.safeer.postMessage(sporocilo); return true;
      }
      if (window.SafeerAndroid && window.SafeerAndroid.sporocilo) { window.SafeerAndroid.sporocilo(JSON.stringify(sporocilo)); return true; }
      if (window.__safeerKonzolniMost) { console.log("__safeer_bridge__:" + JSON.stringify(sporocilo)); return true; }
    } catch (e) {}
    return false;
  }
  function odpri(url) { if (!most({ action: "navigate", url: url })) window.location.href = url; }

  function vNaslov(vnos) {
    var q = (vnos || "").trim();
    if (!q) return "";
    if (/^(https?:|file:)/i.test(q)) return q;
    if (/^(localhost|127\.0\.0\.1)(:\d+)?(\/|$)/i.test(q)) return "http://" + q;
    if (q.indexOf(" ") < 0 && /^[^\s.]+(\.[^\s.]+)+(:\d+)?(\/.*)?$/.test(q)) return "https://" + q;
    return (ISKALNIKI[S.iskalnik] || ISKALNIKI.duckduckgo) + encodeURIComponent(q);
  }

  function crka(ime) {
    var c = (ime || "?").trim().charAt(0).toUpperCase();
    var h = 0; for (var i = 0; i < (ime || "").length; i++) h = (h * 31 + ime.charCodeAt(i)) % 360;
    return { c: c, barva: "hsl(" + h + " 45% 32%)" };
  }

  function narisiBliznjice() {
    var cilj = $("bliznjice"); cilj.innerHTML = ""; cilj.setAttribute("aria-label", t("bliz"));
    document.body.classList.toggle("ureja", S.ureja);
    // Gostitelj, ki seznam vodi sam (no_defaults), lahko poslje tudi prazen seznam: takrat vgrajenih ne vsiljujemo.
    var osnova = S.bliznjice && S.bliznjice.length ? S.bliznjice : (S.brezPrivzetih ? [] : PRIVZETE);
    var seznam = osnova.filter(function (p) { return !jeSkrita(p.url); }).slice(0, 11);
    seznam.forEach(function (p) {
      var url = p.url || ""; if (!/^https?:/i.test(url)) return;
      var ime = (p.title || p.name || "").trim() || url.replace(/^https?:\/\/(www\.)?/i, "").split("/")[0];
      var a = document.createElement("a"); a.className = "bliznjica"; a.href = url; a.title = S.ureja ? t("odstrani") : url;
      var znak = document.createElement("span"); znak.className = "znak";
      var ikona = typeof p.favicon === "string" ? p.favicon.trim() : "";
      if (/^(data:|safeer:|file:|blob:)/i.test(ikona)) {
        var img = document.createElement("img"); img.src = ikona; img.alt = ""; znak.appendChild(img);
        znak.style.background = "rgba(255,255,255,.06)";
      } else { var cr = crka(ime); znak.textContent = cr.c; znak.style.background = cr.barva; }
      var napis = document.createElement("span"); napis.className = "ime"; napis.textContent = ime;
      // Krizec: z misko se pokaze nad bliznjico, na dotik in z daljincem v nacinu urejanja (takrat odstrani ze dotik bliznjice).
      var x = document.createElement("span"); x.className = "odstrani"; x.textContent = "\u00d7"; x.title = t("odstrani");
      x.setAttribute("role", "button"); x.setAttribute("aria-label", t("odstrani") + ": " + ime);
      x.addEventListener("click", function (e) { e.preventDefault(); e.stopPropagation(); odstraniBliznjico(url); });
      a.appendChild(znak); a.appendChild(napis); a.appendChild(x);
      a.addEventListener("click", function (e) { e.preventDefault(); if (S.ureja) odstraniBliznjico(url); else odpri(url); });
      // Dolg pritisk ali desni klik: nacin urejanja (brez sistemskega menija povezave).
      a.addEventListener("contextmenu", function (e) { e.preventDefault(); if (!S.ureja) { S.ureja = true; narisiBliznjice(); } });
      cilj.appendChild(a);
    });
    var d = document.createElement("button"); d.type = "button"; d.className = "bliznjica dodaj";
    d.innerHTML = '<span class="znak">+</span><span class="ime"></span>';
    d.querySelector(".ime").textContent = t("dodaj");
    d.addEventListener("click", function () { if (!most({ action: "open_sidebar", service: "add_portal" })) {
      var u = window.prompt(t("dodaj"), "https://"); if (u && /^https?:\/\/\S+\.\S+/.test(u)) {
        S.bliznjice = (S.bliznjice && S.bliznjice.length ? S.bliznjice : PRIVZETE.slice()).concat([{ title: "", url: u }]);
        S.skrite = S.skrite.filter(function (k) { return k !== kljucBliznjice(u); }); shraniSkrite();
        try { localStorage.setItem("safeer_splet_bliznjice", JSON.stringify(S.bliznjice)); } catch (e) {}
        narisiBliznjice(); } } });
    cilj.appendChild(d);
    // V isti mrezi (dosegljivo z dotikom, misko in daljincem): Uredi bliznjice / Koncano in, ce je kaj odstranjenega, Obnovi privzete.
    function orodje(znak, napis, dejaven, klik) {
      var b = document.createElement("button"); b.type = "button"; b.className = "bliznjica orodje" + (dejaven ? " dejaven" : "");
      b.innerHTML = '<span class="znak"></span><span class="ime"></span>';
      b.querySelector(".znak").textContent = znak; b.querySelector(".ime").textContent = napis;
      b.addEventListener("click", klik);
      cilj.appendChild(b);
      return b;
    }
    if (seznam.length || S.ureja) {
      orodje(S.ureja ? "\u2713" : "\u270e", t(S.ureja ? "koncano" : "uredi"), S.ureja, function () {
        S.ureja = !S.ureja; narisiBliznjice();
        try { $("bliznjice").querySelector(".orodje").focus({ preventScroll: true }); } catch (e) {}
      });
    }
    if (S.skrite.length && (S.ureja || !seznam.length)) {
      orodje("\u21ba", t("obnovi"), false, function () { S.ureja = false; obnoviBliznjice(); });
    }
  }

  function narisiCipe() {
    var cilj = $("cipi"); cilj.innerHTML = "";
    ZVRSTI.forEach(function (z) {
      var b = document.createElement("button"); b.type = "button"; b.className = "cip"; b.setAttribute("role", "tab");
      b.textContent = t(z); b.setAttribute("aria-selected", z === S.zvrst ? "true" : "false");
      b.addEventListener("click", function () { S.zvrst = z; narisiCipe(); narisiKartice(); });
      cilj.appendChild(b);
    });
  }

  function narisiKartice() {
    var cilj = $("kartice"); cilj.innerHTML = "";
    var izbor = KARTICE.filter(function (k) { return S.zvrst === "vse" || k.zvrst === S.zvrst; });
    if (izbor.length < 3) izbor = izbor.concat(KARTICE.filter(function (k) { return izbor.indexOf(k) < 0; })).slice(0, 3);
    izbor.slice(0, 3).forEach(function (k) {
      var v = t(k.k);
      var b = document.createElement("button"); b.type = "button"; b.className = "kartica";
      b.innerHTML = '<svg class="slika" viewBox="0 0 400 200" preserveAspectRatio="xMidYMid slice" aria-hidden="true">' + SLIKE[k.slika] + '</svg>' +
        '<span class="napis"><span><b></b><small></small></span><svg class="puscica" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg></span>';
      b.querySelector("b").textContent = v[0]; b.querySelector("small").textContent = v[1];
      b.addEventListener("click", function () { odpri(vNaslov(v[2])); });
      cilj.appendChild(b);
    });
  }

  function prevedi() {
    document.documentElement.lang = S.jezik;
    document.title = t("nov");
    $("podnaslov").textContent = t("pod");
    $("vnos").placeholder = t("isci"); $("vnos").setAttribute("aria-label", t("isci"));
    $("pojdi").setAttribute("aria-label", t("pojdi"));
    $("predlogiBesedilo").textContent = t("predlogi");
    narisiBliznjice(); narisiCipe(); narisiKartice();
  }

  function init(stanje) {
    stanje = stanje || {};
    var j = String(stanje.language || stanje.jezik || S.jezik || "sl").slice(0, 2).toLowerCase();
    S.jezik = B[j] ? j : "en";
    if (stanje.engine && ISKALNIKI[stanje.engine]) S.iskalnik = stanje.engine;
    if (Array.isArray(stanje.portals)) S.bliznjice = stanje.portals;
    if (Array.isArray(stanje.hidden)) { S.skrite = stanje.hidden.map(kljucBliznjice); shraniSkrite(); }
    if (typeof stanje.no_defaults === "boolean") S.brezPrivzetih = stanje.no_defaults;
    if (stanje.tv) document.body.classList.add("tv");
    prevedi();
    document.documentElement.setAttribute("data-safeer-ready", "1");
  }
  window.safeerSpletInit = init;
  window.safeerWindowsInit = init;
  window.setCustomPortals = function (p) { if (Array.isArray(p)) { S.bliznjice = p; narisiBliznjice(); } };
  window.setSearchEngine = function (e) { if (ISKALNIKI[e]) S.iskalnik = e; };

  $("iskanje").addEventListener("submit", function (e) {
    e.preventDefault(); var u = vNaslov($("vnos").value); if (u) odpri(u);
  });
  $("predlogiNaslov").addEventListener("click", function () { S.zvrst = "vse"; narisiCipe(); narisiKartice(); });

  // Začetno stanje brez gostitelja: jezik brskalnika, shranjene bližnjice.
  try { var sh = JSON.parse(localStorage.getItem("safeer_splet_bliznjice") || "null"); if (Array.isArray(sh)) S.bliznjice = sh; } catch (e) {}
  try { var sk = JSON.parse(localStorage.getItem("safeer_splet_skrite") || "null"); if (Array.isArray(sk)) S.skrite = sk.map(kljucBliznjice); } catch (e) {}
  // Fokus v iskalno polje brez pomika strani (autofocus je stran pomaknil navzdol).
  setTimeout(function () { try { $("vnos").focus({ preventScroll: true }); } catch (e) {} }, 60);
  var q = new URLSearchParams(location.search);
  init({ language: q.get("lang") || (navigator.language || "sl"), engine: q.get("engine") || undefined, tv: q.get("tv") === "1" });
})();
