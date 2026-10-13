/* Plosca sporocil delovne povrsine: pogovori iz Sporocil Safeer OS (klepet: Safeer Link, Matrix, Telegram ...;
   e-posta posebej), neprebrani z modro piko, iskanje, »Novo sporocilo« in »Odpri v celoti« (okno Sporocila).
   Odpre jo kuverta v pultu zgoraj desno (safeer_os.py _preklopi_plosco_sporocil). */
(function () {
  "use strict";
  var most = window.SafeerOS || null;
  var BESEDILA = {
    sl: { naslov: "Sporočila in e-pošta", klepet: "Sporočila", email: "E-pošta", isci: "Išči sporočila …",
          novo: "Novo sporočilo", vse: "Odpri v celoti", prazno: "Ni sporočil.", praznoIsk: "Ni zadetkov.",
          brezKanalov: "Ni še povezanih kanalov. Dodaš jih v Sporočilih (Odpri v celoti).", zapri: "Zapri" },
    en: { naslov: "Messages and email", klepet: "Messages", email: "Email", isci: "Search messages …",
          novo: "New message", vse: "Open all", prazno: "No messages.", praznoIsk: "No matches.",
          brezKanalov: "No channels connected yet. Add them in Messages (Open all).", zapri: "Close" },
    de: { naslov: "Nachrichten und E-Mail", klepet: "Nachrichten", email: "E-Mail", isci: "Nachrichten suchen …",
          novo: "Neue Nachricht", vse: "Alles öffnen", prazno: "Keine Nachrichten.", praznoIsk: "Keine Treffer.",
          brezKanalov: "Noch keine Kanäle verbunden. Füge sie in Nachrichten hinzu (Alles öffnen).", zapri: "Schließen" },
    es: { naslov: "Mensajes y correo", klepet: "Mensajes", email: "Correo", isci: "Buscar mensajes …",
          novo: "Nuevo mensaje", vse: "Abrir todo", prazno: "No hay mensajes.", praznoIsk: "Sin resultados.",
          brezKanalov: "Aún no hay canales conectados. Añádelos en Mensajes (Abrir todo).", zapri: "Cerrar" },
    fr: { naslov: "Messages et e-mails", klepet: "Messages", email: "E-mail", isci: "Rechercher des messages …",
          novo: "Nouveau message", vse: "Tout ouvrir", prazno: "Aucun message.", praznoIsk: "Aucun résultat.",
          brezKanalov: "Aucun canal connecté. Ajoute-les dans Messages (Tout ouvrir).", zapri: "Fermer" },
    it: { naslov: "Messaggi ed e-mail", klepet: "Messaggi", email: "E-mail", isci: "Cerca messaggi …",
          novo: "Nuovo messaggio", vse: "Apri tutto", prazno: "Nessun messaggio.", praznoIsk: "Nessun risultato.",
          brezKanalov: "Nessun canale collegato. Aggiungili in Messaggi (Apri tutto).", zapri: "Chiudi" }
  };
  var jezik = (location.search.match(/[?&]jezik=([a-z]{2})(?:&|$)/) || [])[1] || "sl";
  if (!BESEDILA[jezik]) jezik = "en";
  var LOKALE = { sl: "sl-SI", en: "en-GB", de: "de-DE", es: "es-ES", fr: "fr-FR", it: "it-IT" };
  var S = { vrsta: "klepet", podatki: { skupine: [], kanali: [] }, nalozeno: false };

  function t(k) { return BESEDILA[jezik][k] || BESEDILA.en[k] || k; }
  function $(id) { return document.getElementById(id); }
  function klic(m, a) { return most ? Promise.resolve(most.klic(m, a || [])) : Promise.reject("brez mosta"); }

  // Vrstice: en pogovor = ena vrstica (oseba, zadnje sporocilo ali zadeva, cas, neprebrano).
  function vrstice() {
    var izid = [];
    (S.podatki.skupine || []).forEach(function (skupina) {
      (skupina.pogovori || []).forEach(function (p) {
        var vrsta = ((p.kanal || {}).vrsta || "") === "email" ? "email" : "klepet";
        izid.push({ vrsta: vrsta, ime: (skupina.oseba || {}).ime || p.oseba_id || "", p: p });
      });
    });
    izid.sort(function (a, b) { return String(b.p.cas || "").localeCompare(String(a.p.cas || "")); });
    return izid;
  }
  function kratekCas(cas) {
    var d = new Date(cas || ""); if (isNaN(d.getTime())) return "";
    var lok = LOKALE[jezik] || "en-GB", danes = new Date();
    if (d.toDateString() === danes.toDateString()) return d.toLocaleTimeString(lok, { hour: "2-digit", minute: "2-digit" });
    return d.toLocaleDateString(lok, { day: "numeric", month: "short" });
  }
  function zacetnice(ime) {
    var deli = String(ime || "?").trim().split(/\s+/).filter(Boolean);
    return ((deli[0] || "?").charAt(0) + (deli.length > 1 ? deli[deli.length - 1].charAt(0) : "")).toUpperCase();
  }
  function barva(ime) {
    var h = 0, s = String(ime || "");
    for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
    return "hsl(" + h + ", 45%, 42%)";
  }
  function narisi() {
    var vse = vrstice(), q = $("iskanje").value.trim().toLowerCase();
    var stevilo = { klepet: 0, email: 0 };
    vse.forEach(function (v) { stevilo[v.vrsta] += Number(v.p.neprebrano || 0); });
    [["zavSporocila", "klepet"], ["zavEposta", "email"]].forEach(function (z) {
      var b = $(z[0]);
      b.textContent = t(z[1]);
      if (stevilo[z[1]]) { var s = document.createElement("span"); s.className = "stevec"; s.textContent = stevilo[z[1]]; b.appendChild(s); }
      b.classList.toggle("izbran", S.vrsta === z[1]);
      b.setAttribute("aria-selected", S.vrsta === z[1] ? "true" : "false");
    });
    var seznam = $("seznam");
    seznam.textContent = "";
    var izbrane = vse.filter(function (v) {
      if (v.vrsta !== S.vrsta) return false;
      if (!q) return true;
      return (v.ime + " " + (v.p.zadeva || "") + " " + (v.p.zadnje_sporocilo || "")).toLowerCase().indexOf(q) >= 0;
    });
    izbrane.slice(0, 60).forEach(function (v) {
      var li = document.createElement("li");
      var b = document.createElement("button");
      b.type = "button";
      b.className = "vrstica" + (v.p.neprebrano ? " neprebrano" : "");
      var pika = document.createElement("span"); pika.className = "pika" + (v.p.neprebrano ? "" : " prebrano");
      var av = document.createElement("span"); av.className = "avatar"; av.textContent = zacetnice(v.ime);
      av.style.background = barva(v.ime);
      var bes = document.createElement("span"); bes.className = "besedilo";
      var ime = document.createElement("b"); ime.textContent = v.ime;
      var vrst = document.createElement("small");
      vrst.textContent = v.vrsta === "email" && v.p.zadeva ? v.p.zadeva : (v.p.zadnje_sporocilo || v.p.zadeva || "");
      bes.appendChild(ime); bes.appendChild(vrst);
      var desno = document.createElement("span"); desno.className = "desno";
      var cas = document.createElement("time"); cas.textContent = kratekCas(v.p.cas); desno.appendChild(cas);
      if (v.p.neprebrano) { var n = document.createElement("i"); n.textContent = v.p.neprebrano; desno.appendChild(n); }
      b.appendChild(pika); b.appendChild(av); b.appendChild(bes); b.appendChild(desno);
      b.addEventListener("click", function () { odpri("pogovor:" + v.p.kanal_id + ":" + v.p.id); });
      li.appendChild(b); seznam.appendChild(li);
    });
    if (!izbrane.length) {
      var p = document.createElement("p"); p.className = "prazno";
      p.textContent = !S.nalozeno ? "" : q ? t("praznoIsk") : (S.podatki.kanali || []).length ? t("prazno") : t("brezKanalov");
      seznam.appendChild(p);
    }
  }
  function odpri(cilj) {
    klic("odpriRazdelek", [cilj]).catch(function () {});
    klic("skrijPloscoSporocil").catch(function () {});
  }
  function osvezi() {
    return klic("sporocilaSeznam").then(function (p) {
      S.podatki = p || { skupine: [], kanali: [] }; S.nalozeno = true; narisi();
    }, function () { S.nalozeno = true; narisi(); });
  }
  // Safeer OS poklice ob vsakem odprtju plosce (podatki so sveži, iskanje prazno, fokus v iskanju).
  window.safeerPloscaOsvezi = function () {
    $("iskanje").value = "";
    osvezi().then(function () { $("iskanje").focus(); });
  };

  document.documentElement.lang = jezik;
  $("naslov").textContent = t("naslov");
  $("iskanje").placeholder = t("isci");
  $("novo").textContent = t("novo");
  $("vse").textContent = t("vse");
  $("zapri").setAttribute("aria-label", t("zapri"));
  $("zapri").addEventListener("click", function () { klic("skrijPloscoSporocil").catch(function () {}); });
  $("novo").addEventListener("click", function () { odpri("sporocila:novo"); });
  $("vse").addEventListener("click", function () { odpri("sporocila"); });
  $("iskanje").addEventListener("input", narisi);
  [["zavSporocila", "klepet"], ["zavEposta", "email"]].forEach(function (z) {
    $(z[0]).addEventListener("click", function () { S.vrsta = z[1]; narisi(); });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") klic("skrijPloscoSporocil").catch(function () {});
  });
  narisi();
  osvezi().then(function () {
    // Prvi pogled: zavihek z neprebranimi (e-posta, ce je novo samo tam).
    var n = { klepet: 0, email: 0 };
    vrstice().forEach(function (v) { n[v.vrsta] += Number(v.p.neprebrano || 0); });
    if (!n.klepet && n.email) { S.vrsta = "email"; narisi(); }
  });
})();
