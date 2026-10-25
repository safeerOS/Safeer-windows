/* Safeer OS: skupni most vmesnika za Linux in Windows (window.SafeerMost).
 *
 * Lastnik, 25. 10. 2026: »Kar velja za eno okolje, mora veljati za drugo.« Prenos sporocil (window.SafeerOS.klic) vstavi
 * gostitelj platforme pred nalaganjem strani - Linux WebKit (safeer_os.MOST_JS, zeton v zaprtju), Windows Qt WebEngine
 * (os_app.most_js). Ta datoteka je ENAKA na obeh platformah in doda, kar je bilo v vsakem os.js po svoje:
 *   klic(metoda, argumenti) -> Promise    (most lahko pride z zamikom - na Windows ga Qt vcasih vstavi po nalaganju)
 *   koMost(delo)                           delo, ko je most na voljo (najvec 5 s)
 *   ima(metoda) -> bool                    ali zaledje TE platforme metodo zna (odgovor »zmoznosti«, core/os_most_metode.py)
 *   koZnano(delo)                          delo, ko so zmoznosti znane (gumbe za neznane metode vmesnik skrije)
 *   platforma() -> "linux" | "windows" | "" in <html data-platforma="..."> za resnicne razlike (imena tipk v namigih)
 * Zaledje brez metode »zmoznosti« (starejse) vrne napako: takrat ima() vrne true za vse (vmesnik je tedaj se lasten
 * vmesnik platforme in klice samo metode svojega zaledja) - v konzoli je opozorilo.
 */
(function () {
  "use strict";
  if (window.SafeerMost) return;

  var most = window.SafeerOS || null;
  var cakajoMost = [];
  var zmoznosti = null;          // {metoda: true}; null = se ne vemo
  var vse = false;               // zaledje brez »zmoznosti«: ima() je vedno true
  var platforma = "";
  var cakajoZnano = [];

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
    return Promise.resolve(most.klic(metoda, argumenti || []));
  }

  function znano() {
    return vse || zmoznosti !== null;
  }

  function sprozi() {
    var vrsta = cakajoZnano; cakajoZnano = [];
    vrsta.forEach(function (d) { try { d(); } catch (e) { console.error(e); } });
  }

  function nastavi(odgovor) {
    var metode = (odgovor && Array.isArray(odgovor.metode)) ? odgovor.metode : null;
    if (!metode) { vse = true; console.warn("[SafeerMost] zaledje brez zmoznosti - vmesnik pokaze vse"); }
    else {
      zmoznosti = {};
      metode.forEach(function (m) { if (typeof m === "string") zmoznosti[m] = true; });
    }
    platforma = (odgovor && (odgovor.platforma === "linux" || odgovor.platforma === "windows")) ? odgovor.platforma : "";
    if (platforma && document.documentElement) document.documentElement.setAttribute("data-platforma", platforma);
    sprozi();
  }

  function ima(metoda) {
    if (vse) return true;
    return !!(zmoznosti && Object.prototype.hasOwnProperty.call(zmoznosti, metoda));
  }

  function koZnano(delo) {
    if (znano()) { delo(); return; }
    cakajoZnano.push(delo);
  }

  koMost(function () {
    klic("zmoznosti").then(nastavi, function () { nastavi(null); });
  });

  window.SafeerMost = {
    klic: klic,
    koMost: koMost,
    imaMost: imaMost,
    ima: ima,
    koZnano: koZnano,
    znano: znano,
    platforma: function () { return platforma; }
  };
})();
