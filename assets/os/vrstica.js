/* Safeerjeva vrstica: Domov, odprti programi (kot opravilna vrstica), stanje in ura.
 * Most je isti kot na domacem zaslonu (window.SafeerOS.klic); dogodke »okna« in »stanje« poslje safeer_os.py. */
(function () {
  "use strict";
  var IK = {
    zvok: "M4 9v6h4l5 4V5L8 9z M16 9a4 4 0 0 1 0 6 M18.5 6.5a8 8 0 0 1 0 11",
    utisan: "M4 9v6h4l5 4V5L8 9z M17 9l5 6 M22 9l-5 6",
    wifi: "M2 9a15 15 0 0 1 20 0 M5 12.5a10 10 0 0 1 14 0 M8.5 16a5 5 0 0 1 7 0 M12 19.5v.1",
    ethernet: "M4 10h16v8H4z M8 18v2 M12 18v2 M16 18v2 M9 10V6h6v4",
    brez: "M2 9a15 15 0 0 1 20 0 M8.5 16a5 5 0 0 1 7 0 M3 3l18 18",
    baterija: "M3 8h15v8H3z M20 11v2",
    polni: "M3 8h15v8H3z M20 11v2 M11 9l-2 3h3l-2 3"
  };
  function svg(ime) { return '<svg viewBox="0 0 24 24"><path d="' + IK[ime] + '"/></svg>'; }
  function $(id) { return document.getElementById(id); }
  function ubezi(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (z) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[z];
    });
  }
  var most = window.SafeerOS || null;
  function klic(m, a) { return most ? most.klic(m, a || []) : Promise.reject(); }
  var jezik = "sl";
  function t(k) { var b = (BESEDILA_OS[jezik] || {})[k]; return b == null ? (BESEDILA_OS.en[k] || k) : b; }
  var LOKALE = { sl: "sl-SI", en: "en-GB", de: "de-DE", es: "es-ES", fr: "fr-FR", it: "it-IT" };
  var povezan = false;

  function ura() {
    var z = new Date(), lok = LOKALE[jezik] || "en-GB";
    $("ura").textContent = z.toLocaleTimeString(lok, { hour: "2-digit", minute: "2-digit" });
    $("datum").textContent = z.toLocaleDateString(lok, { weekday: "short", day: "numeric", month: "short" });
  }
  function okna(seznam) {
    var c = $("okna");
    c.innerHTML = "";
    (seznam || []).slice().reverse().forEach(function (o) {
      var b = document.createElement("button");
      b.className = "okno" + (o.aktivno ? " aktivno" : "") + (o.pomanjsano ? " pomanjsano" : "");
      b.title = o.ime || o.program;
      if (o.ikona) {
        var img = document.createElement("img");
        img.src = o.ikona; img.alt = "";
        img.onerror = function () { img.replaceWith(crka(o)); };
        b.appendChild(img);
      } else b.appendChild(crka(o));
      var s = document.createElement("span");
      s.textContent = o.program || o.ime;
      b.appendChild(s);
      b.addEventListener("click", function () { klic("preklopiOkno", [o.id]); });
      c.appendChild(b);
    });
  }
  function crka(o) {
    var d = document.createElement("div");
    d.className = "crka";
    d.textContent = String(o.program || o.ime || "?").charAt(0).toUpperCase();
    return d;
  }
  function stanje(s) {
    if (!s) return;
    var o = s.omrezje || {};
    $("sOmrezje").innerHTML = svg(o.vrsta === "wifi" ? "wifi" : (o.vrsta === "ethernet" ? "ethernet" : "brez"));
    $("sOmrezje").title = o.vrsta === "ethernet" ? t("zicna") : (o.ime || t("brezOmrezja"));
    var z = s.zvok;
    $("sZvok").innerHTML = z ? svg(z.utisan ? "utisan" : "zvok") + (z.utisan ? "" : ubezi(Math.min(100, z.glasnost)) + " %") : "";
    var b = s.baterija;
    $("sBaterija").innerHTML = b ? svg(b.polni ? "polni" : "baterija") + ubezi(b.odstotek) + " %" : "";
  }
  function link(p) {
    povezan = !!(p && p.stanje === "povezan");
    $("sLink").innerHTML = '<i class="pika' + (povezan ? "" : " siva") + '"></i>';
    $("sLink").title = povezan ? "Safeer Link" : t("brezNaprav");
  }
  window.safeerOsDogodek = function (vrsta, podatki) {
    if (vrsta === "okna") okna(podatki);
    if (vrsta === "stanje") stanje(podatki);
    if (vrsta === "fokus") klic("povezava").then(link, function () {});
  };
  function zacni() {
    $("gumbDomov").addEventListener("click", function () { klic("domov", [""]); });
    $("gumbProgrami").addEventListener("click", function () { klic("domov", ["programi"]); });
    $("gumbIsci").addEventListener("click", function () { klic("domov", ["iskanje:"]); });
    $("gumbStanje").addEventListener("click", function () { klic("domov", ["hitro"]); });
    // Desni klik na zvocnik odpre stran Zvok (izhodi, programi, predvajanje na napravi v Linku),
    // na omrezje pa stran Omrezje - kot v vrstici Minta, le v nasi preobleki.
    $("sZvok").addEventListener("contextmenu", function (e) { e.preventDefault(); e.stopPropagation(); klic("domov", ["zvok"]); });
    $("sOmrezje").addEventListener("contextmenu", function (e) { e.preventDefault(); e.stopPropagation(); klic("domov", ["omrezje"]); });
    document.addEventListener("contextmenu", function (e) { e.preventDefault(); });
    ura();
    setInterval(ura, 1000);
    if (!most) return;
    klic("zacetek").then(function (z) {
      if (BESEDILA_OS[z.jezik]) jezik = z.jezik;
      document.querySelectorAll("[data-naslov]").forEach(function (e) { e.title = t(e.getAttribute("data-naslov")); });
      link(z.povezava);
      ura();
    }, function () {});
    klic("odprtaOkna").then(okna, function () {});
    klic("stanje").then(stanje, function () {});
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", zacni); else zacni();
})();
