/* Cista odlocitev za pametno iskanje Safeer OS. Brez DOM-a, zato jo lahko
 * uporablja vmesnik in neposredno preverjajo Node testi. */
(function (koren, tovarna) {
  var api = tovarna();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (koren) koren.SafeerPametnoIskanje = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function besedilo(v) {
    return String(v || "").trim().toLocaleLowerCase();
  }

  function domena(url) {
    try { return new URL(/^https?:\/\//i.test(url) ? url : "https://" + url).hostname.replace(/^www\./, ""); }
    catch (_) { return ""; }
  }

  function kratica(ime) {
    ime = String(ime || "");
    var velike = (ime.match(/[A-ZČŠŽ]/g) || []).join("").toLocaleLowerCase();
    if (velike.length > 1) return velike;
    return ime.split(/[^\p{L}\p{N}]+/u).filter(Boolean).map(function (del) { return del.charAt(0); }).join("").toLocaleLowerCase();
  }

  function oceni(niz, vrednosti) {
    niz = besedilo(niz);
    if (!niz) return 0;
    var najboljsa = 0;
    (vrednosti || []).forEach(function (vrednost) {
      var v = besedilo(vrednost);
      if (!v) return;
      if (v === niz) najboljsa = Math.max(najboljsa, 100);
      else if (v.indexOf(niz) === 0) najboljsa = Math.max(najboljsa, 80);
      else if (v.indexOf(" " + niz) >= 0 || v.indexOf("." + niz) >= 0) najboljsa = Math.max(najboljsa, 65);
      else if (v.indexOf(niz) >= 0) najboljsa = Math.max(najboljsa, 45);
    });
    return najboljsa;
  }

  function najboljsi(niz, seznam, vrednosti) {
    var najboljsiVnos = null, najboljsaOcena = 0;
    (seznam || []).forEach(function (vnos) {
      var ocena = oceni(niz, vrednosti(vnos));
      if (ocena > najboljsaOcena) { najboljsaOcena = ocena; najboljsiVnos = vnos; }
    });
    return { vnos: najboljsiVnos, ocena: najboljsaOcena };
  }

  function jeNaslov(niz) {
    niz = String(niz || "").trim();
    if (!/^https?:\/\//i.test(niz) && /\.(pdf|docx?|xlsx?|pptx?|od[tpfs]|txt|rtf|csv|json|zip|7z|rar|jpe?g|png|gif|webp|svg|mp[34]|mkv|avi|mov|wav|flac)$/i.test(niz)) return false;
    return /^https?:\/\//i.test(niz) || (!/\s/.test(niz) && niz.indexOf(".") >= 0);
  }

  function jePotAliDatoteka(niz) {
    niz = String(niz || "").trim();
    return /^(~\/|[a-z]:[\\/]|\\\\|\/)/i.test(niz) ||
      /\.(pdf|docx?|xlsx?|pptx?|od[tpfs]|txt|rtf|csv|json|zip|7z|rar|jpe?g|png|gif|webp|svg|mp[34]|mkv|avi|mov|wav|flac)$/i.test(niz);
  }

  function nameraIskanja(niz, podatki) {
    niz = String(niz || "").trim();
    podatki = podatki || {};
    var spletna = najboljsi(niz, podatki.spletne, function (a) {
      var host = domena(a.url);
      return [a.ime, host, host.split(".")[0], kratica(a.ime)];
    });
    if (/^https?:\/\//i.test(niz)) return { vrsta: "splet", naslov: true, niz: niz };
    if (jePotAliDatoteka(niz)) return { vrsta: "datoteke", niz: niz };
    if (jeNaslov(niz)) return { vrsta: "splet", naslov: true, niz: niz };
    if (spletna.ocena >= 65) return { vrsta: "splet", spletna: spletna.vnos, ocena: spletna.ocena, niz: niz };

    var program = najboljsi(niz, podatki.programi, function (p) {
      return [p.ime, p.splosno, (p.kljucne || []).join(" ")];
    });
    if (program.ocena >= 80) return { vrsta: "programi", zadetek: program.vnos, ocena: program.ocena, niz: niz };

    var datoteka = najboljsi(niz, podatki.datoteke, function (d) { return [d.ime, d.pot]; });
    if (datoteka.ocena >= 65) {
      return { vrsta: "datoteke", zadetek: datoteka.vnos, ocena: datoteka.ocena, niz: niz };
    }

    var media = najboljsi(niz, podatki.mediji, function (m) { return [m.naslov, m.izvajalec, m.opis, m.vrsta]; });
    var mediaBesede = /(^|\s)(film|filme|pel[ií]cula|movie|serija|serie|s[eé]rie|series|glasba|musik|m[uú]sica|musique|musica|music|pesem|lied|canci[oó]n|chanson|canzone|song|radio|tv|fernsehen|video)(\s|$)/i;
    if (mediaBesede.test(niz) || media.ocena >= 65) {
      return { vrsta: "media", zadetek: media.vnos, ocena: media.ocena, niz: niz };
    }

    var naprava = najboljsi(niz, podatki.naprave, function (n) { return [n.ime, n.id, n.platforma, n.vrsta]; });
    if (/^(safeer\s*)?link$/i.test(niz) || naprava.ocena >= 65) {
      return { vrsta: "naprave", zadetek: naprava.vnos, ocena: naprava.ocena, niz: niz };
    }
    return { vrsta: "splet", iskanje: true, niz: niz };
  }

  return { nameraIskanja: nameraIskanja, oceni: oceni, jeNaslov: jeNaslov, jePotAliDatoteka: jePotAliDatoteka };
});
