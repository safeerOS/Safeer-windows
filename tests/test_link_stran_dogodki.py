"""Stran Safeer Linka (assets/link/link.js) iz dogodkov zaledja naredi napise, ki jih uporabnik vidi.

Preizkus stran ZARES pozene (node, brez brskalnika: elementi strani so preproste nadomestne vrednosti) in ji poslje
dogodke v obliki, ki jo oddajata zaledji za Linux in Windows. Tako se opazi, ce se zaledje in stran razideta ali ce
stran ob dogodku pade:
- 5. 10. 2026 je plosca »Deli z« na Windows po poslani datoteki ostala prazna - zaledje je oddajalo polja, ki jih stran
  ne bere;
- isti dan je ta preizkus pokazal, da se kartice dovoljenj na Windows ne risejo od 26. 9. 2026: funkcija `ubezi` ni
  bila dolocena, napako pa je pogoltnil lovilec odzivov (»stran nikoli ne sme pasti zaradi odziva«).
"""
import json
import os
import shutil
import subprocess
import unittest

KOREN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRAN = os.path.join(KOREN, "assets", "link", "link.js")

OGRODJE = r"""
const vm = require('vm'), fs = require('fs');
const vir0 = fs.readFileSync(process.argv[1], 'utf8');
const koraki = JSON.parse(process.argv[2]);
const LOVILEC = '} catch (e) {\n      // Stran nikoli ne sme pasti zaradi odziva.\n    }';
if (vir0.split(LOVILEC).length !== 2) { console.log(JSON.stringify({ogrodje: 'lovilca odzivov ni ali ni en sam'})); process.exit(0); }
const vir = vir0.replace(LOVILEC, '} catch (e) { window.__napake.push(String((e && e.stack) || e)); }');

function karkoli() {
  const f = function () { return karkoli(); };
  return new Proxy(f, {
    get(t, k) {
      if (k === Symbol.toPrimitive) return function () { return ''; };
      if (k === 'toString' || k === 'valueOf') return function () { return ''; };
      if (k === 'length') return 0;
      if (typeof k === 'symbol') return undefined;
      return karkoli();
    },
    set() { return true; }
  });
}
function element(id) {
  const stor = { id: id, textContent: '', hidden: false, value: '', innerHTML: '', className: '', title: '', disabled: false,
                 checked: false, children: [], childNodes: [], options: [], style: {}, dataset: {}, parentNode: null,
                 classList: { add() {}, remove() {}, toggle() { return false; }, contains() { return false; } },
                 addEventListener() {}, removeEventListener() {}, setAttribute() {}, removeAttribute() {},
                 getAttribute() { return null; }, appendChild(o) { stor.children.push(o); return o; },
                 removeChild(o) { return o; }, insertBefore(o) { stor.children.push(o); return o; },
                 querySelector() { return null; }, querySelectorAll() { return []; },
                 focus() {}, blur() {}, click() {}, scrollIntoView() {}, contains() { return false; },
                 getBoundingClientRect() { return { left: 0, top: 0, width: 0, height: 0, right: 0, bottom: 0 }; } };
  return new Proxy(stor, {
    get(t, k) { if (k in t) return t[k]; if (typeof k === 'symbol') return undefined; return karkoli(); },
    set(t, k, v) { t[k] = v; if (k === 'innerHTML' && v === '') t.children = []; return true; }
  });
}
const elementi = {};
function el(id) { if (!elementi[id]) elementi[id] = element(id); return elementi[id]; }
const document = {
  documentElement: element('html'), body: element('body'), title: '', hidden: false, visibilityState: 'visible',
  getElementById: el, querySelector() { return null; }, querySelectorAll() { return []; },
  addEventListener() {}, removeEventListener() {},
  createElement() { return element(''); }, createTextNode(b) { return { textContent: b, children: [] }; },
  createDocumentFragment() { return element(''); }
};
const okno = {
  document: document, navigator: { language: 'sl' }, location: { hash: '', search: '', href: '' },
  localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
  setTimeout() { return 0; }, clearTimeout() {}, setInterval() { return 0; }, clearInterval() {},
  requestAnimationFrame() { return 0; }, addEventListener() {}, removeEventListener() {},
  matchMedia() { return { matches: false, addEventListener() {}, addListener() {} }; },
  console: { log() {}, warn() {}, error() {} }, __napake: []
};
okno.window = okno;
vm.createContext(okno);
vm.runInContext(vir, okno);
function zberi(e) {
  if (!e || typeof e !== 'object') return '';
  const svoje = String(e.innerHTML || e.textContent || '');
  const otroci = Array.isArray(e.children) ? e.children.map(zberi).join('|') : '';
  return svoje + (otroci ? '[' + otroci + ']' : '');
}
const BERI = ['opombaDeljenje', 'opombaNaprave', 'panelZaslonTece', 'zaslonTeceBesedilo', 'deljenjeBesedilo', 'preimenujBlok',
              'dovoljenjaNaprav', 'opombaDovoljenja', 'seznamMape'];
const slike = [];
for (const korak of koraki) {
  if (korak[0] === '__nastavi') el(korak[1])[korak[2]] = korak[3];
  else okno.safeerLinkOdziv(korak[0], korak[1]);
  const slika = {};
  for (const id of BERI) {
    slika[id] = { besedilo: String(el(id).textContent), skrit: !!el(id).hidden, vrednost: String(el(id).value),
                  otrok: el(id).children.length, vsebina: zberi(el(id)) };
  }
  slike.push(slika);
}
console.log(JSON.stringify({ napake: okno.__napake, slike: slike }));
"""

NAPRAVE = [{"id": "n-tel", "ime": "Telefon", "vloga": "controller", "povezana": True},
           {"id": "n-tv", "ime": "Televizor", "vloga": "receiver", "povezana": True}]


def _stran(koraki):
    izid = subprocess.run([shutil.which("node"), "-e", OGRODJE, STRAN, json.dumps(koraki)],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    if izid.returncode != 0:
        raise AssertionError("stran se ni izvedla: " + izid.stderr[-1500:])
    podatki = json.loads(izid.stdout)
    if podatki.get("ogrodje"):
        raise AssertionError("ogrodje preizkusa: " + podatki["ogrodje"])
    if podatki["napake"]:
        raise AssertionError("stran je ob dogodku padla: " + podatki["napake"][0][:1500])
    return podatki["slike"]


def _deljenje(vrsta, stanje, cilj="n-tel", ime="", sporocilo="", koda="", zasedena_od="", **dodatno):
    """Dogodek »deljenje« natanko v obliki, ki jo oddajata zaledji (Linux: safeer_link.py; Windows: control_backend.py)."""
    return ["deljenje", dict({"vrsta": vrsta, "stanje": stanje, "cilj": cilj, "ime": ime, "sporocilo": sporocilo,
                              "koda": koda, "zasedenaOd": zasedena_od}, **dodatno)]


def _vir_strani() -> str:
    with open(STRAN, encoding="utf-8") as f:
        return f.read()


@unittest.skipUnless(shutil.which("node"), "node ni namescen")
class DogodkiNaStrani(unittest.TestCase):
    def test_datoteka_napredek_in_izid(self):
        s = _stran([["naprave", NAPRAVE],
                    _deljenje("datoteka", "posiljam", ime="porocilo.pdf", odstotek=0),
                    _deljenje("datoteka", "posiljam", ime="porocilo.pdf", odstotek=40),
                    _deljenje("datoteka", "poslano", ime="porocilo.pdf", odstotek=100)])
        self.assertEqual(s[1]["opombaDeljenje"]["besedilo"], "Pošiljam porocilo.pdf … 0 %")
        self.assertEqual(s[2]["opombaDeljenje"]["besedilo"], "Pošiljam porocilo.pdf … 40 %")
        self.assertEqual(s[3]["opombaDeljenje"]["besedilo"], "Poslano na Telefon.")

    def test_datoteka_napaka_pove_razlog(self):
        s = _stran([["naprave", NAPRAVE],
                    _deljenje("datoteka", "napaka", ime="a.txt", koda="naprava_ni_povezana", sporocilo="Ciljna naprava ni povezana."),
                    _deljenje("datoteka", "napaka", ime="a.txt", koda="dovoljenje_zavrnjeno", sporocilo="Zavrnjeno."),
                    _deljenje("datoteka", "napaka", ime="a.txt", sporocilo="Na disku ni prostora.")])
        besedila = [k["opombaDeljenje"]["besedilo"] for k in s[1:]]
        self.assertTrue(all(besedila), besedila)
        self.assertEqual(len(set(besedila)), 3, "vsaka napaka ima svoj napis: %r" % besedila)
        self.assertIn("Na disku ni prostora.", besedila[2])
        self.assertFalse(any("Pošiljam" in b or "Poslano" in b for b in besedila), besedila)

    def test_besedilo_poslano_izprazni_vnos(self):
        s = _stran([["naprave", NAPRAVE],
                    ["__nastavi", "deljenjeBesedilo", "value", "Kupi mleko"],
                    _deljenje("besedilo", "posiljam"),
                    _deljenje("besedilo", "poslano")])
        self.assertEqual((s[2]["opombaDeljenje"]["besedilo"], s[2]["deljenjeBesedilo"]["vrednost"]), ("Pošiljam …", "Kupi mleko"))
        self.assertEqual((s[3]["opombaDeljenje"]["besedilo"], s[3]["deljenjeBesedilo"]["vrednost"]), ("Poslano na Telefon.", ""))

    def test_besedilo_napaka_pusti_vnos(self):
        s = _stran([["__nastavi", "deljenjeBesedilo", "value", "Kupi mleko"],
                    _deljenje("besedilo", "napaka", koda="naprava_ni_povezana", sporocilo="Ciljna naprava ni povezana.")])
        self.assertTrue(s[1]["opombaDeljenje"]["besedilo"])
        self.assertEqual(s[1]["deljenjeBesedilo"]["vrednost"], "Kupi mleko")

    def test_zaslon_tece_in_konec(self):
        s = _stran([["naprave", NAPRAVE],
                    _deljenje("zaslon", "tece", cilj="n-tv", ime="Televizor", tece=True, napaka=""),
                    _deljenje("zaslon", "koncano", cilj="n-tv", ime="Televizor", tece=False, napaka="")])
        self.assertFalse(s[1]["panelZaslonTece"]["skrit"])
        self.assertIn("Televizor", s[1]["opombaDeljenje"]["besedilo"])
        self.assertIn("Televizor", s[1]["zaslonTeceBesedilo"]["besedilo"])
        self.assertTrue(s[2]["panelZaslonTece"]["skrit"])
        self.assertTrue(s[2]["opombaDeljenje"]["besedilo"])
        self.assertNotEqual(s[2]["opombaDeljenje"]["besedilo"], s[1]["opombaDeljenje"]["besedilo"])

    def test_zaslon_zasedena_naprava(self):
        s = _stran([["naprave", NAPRAVE],
                    _deljenje("zaslon", "koncano", cilj="n-tv", ime="Televizor", sporocilo="Naprava je zasedena.",
                              koda="naprava_zasedena", zasedena_od="Tablica", tece=False, napaka="Naprava je zasedena.")])
        self.assertTrue(s[1]["panelZaslonTece"]["skrit"])
        self.assertIn("Tablica", s[1]["opombaDeljenje"]["besedilo"])

    def test_zaslon_napaka_brez_sredisca(self):
        s = _stran([_deljenje("zaslon", "napaka", cilj="n-tv", ime="Televizor", koda="hub_ni_znan",
                              sporocilo="Zaslon lahko deliš po varni povezavi s Safeer Linkom.", tece=False)])
        self.assertTrue(s[0]["opombaDeljenje"]["besedilo"])
        self.assertTrue(s[0]["panelZaslonTece"]["skrit"])

    def test_preimenovano(self):
        s = _stran([["__nastavi", "opombaDeljenje", "textContent", "Pošiljam …"],
                    ["__nastavi", "preimenujBlok", "hidden", False],
                    ["preimenovano", {"id": "n-moj-control", "ime": "Pisarna"}]])
        self.assertEqual(s[2]["opombaDeljenje"]["besedilo"], "Ime je shranjeno.")
        self.assertTrue(s[2]["preimenujBlok"]["skrit"])

    def test_neuspelo_preimenovanje_se_pokaze_na_plosci(self):
        """Uporabnik je ime shranjeval na plosci »Deli z« (tam pise »Pošiljam …«): razlog mora priti tja, ne le k seznamu."""
        s = _stran([["__nastavi", "opombaDeljenje", "textContent", "Pošiljam …"],
                    ["napaka", {"koda": "preimenovanje_ni_uspelo", "sporocilo": "Naprava ni v krogu zaupanja."}]])
        self.assertEqual(s[1]["opombaDeljenje"]["besedilo"], "Imena ni bilo mogoče shraniti.")
        self.assertEqual(s[1]["opombaNaprave"]["besedilo"], "Imena ni bilo mogoče shraniti.")

    def test_neuspelo_preimenovanje_ni_tezava_povezave(self):
        vir = _vir_strani()
        mehke = vir[vir.index("var MEHKE_NAPAKE = {"):]
        self.assertIn("preimenovanje_ni_uspelo: 1", mehke[:mehke.index("};")])

    def test_druga_napaka_plosce_ne_prepise(self):
        s = _stran([["__nastavi", "opombaDeljenje", "textContent", "Poslano na Telefon."],
                    ["napaka", {"koda": "ukaz_ni_uspel", "sporocilo": "Ukaz ni uspel."}]])
        self.assertEqual(s[1]["opombaDeljenje"]["besedilo"], "Poslano na Telefon.")

    def test_prejeto(self):
        s = _stran([["prejeto", {"vrsta": "besedilo", "od": "Telefon", "besedilo": "Kupi mleko"}],
                    ["prejeto", {"vrsta": "datoteka", "od": "Telefon", "ime": "slika.jpg", "mapa": "Prenosi"}]])
        self.assertIn("Telefon", s[0]["opombaNaprave"]["besedilo"])
        self.assertNotIn("Kupi mleko", s[0]["opombaNaprave"]["besedilo"], "vsebina besedila ne gre v vrstico stanja")
        self.assertIn("slika.jpg", s[1]["opombaNaprave"]["besedilo"])
        self.assertIn("Prenosi", s[1]["opombaNaprave"]["besedilo"])

    def test_stara_oblika_dogodka_ne_pove_nicesar(self):
        """Zakaj je ta preizkus tu: dogodek brez polj vrsta in stanje (kot ga je oddajal Windows) plosce ne spremeni."""
        s = _stran([["deljenje", {"tece": False, "cilj": "n-tel", "ime": "a.txt", "odstotek": 100, "uspeh": True, "napaka": ""}]])
        self.assertEqual(s[0]["opombaDeljenje"]["besedilo"], "")

    def test_seznam_naprav_se_narise_brez_napake(self):
        """Vsak dogodek, ki ga stran dobi ob zagonu, se mora izvesti do konca (napako bi lovilec odzivov sicer skril)."""
        _stran([["naprave", NAPRAVE], ["naprave", []], ["povezava", True], ["povezava", False],
                ["deljeneMape", {"mape": [{"ime": "Videi", "pot": "/home/ana/Videi"}], "standardne": True}],
                ["dovoljenja", {"n-tel": "polno"}], ["naprave", NAPRAVE]])


@unittest.skipUnless(shutil.which("node"), "node ni namescen")
@unittest.skipUnless("function narisiDovoljenja(" in _vir_strani(), "ta stran nima kartic dovoljenj (Safeer Control za Linux)")
class KarticeDovoljenj(unittest.TestCase):
    """Razdelek »Dostop do tega racunalnika«: ena kartica na fizicno napravo, trije profili."""

    DVOJNA = [{"id": "n-1111111111111111", "ime": "Tablica", "vloga": "receiver", "zmoznosti": ["zaslon", "predvajanje"]},
              {"id": "n-1111111111111111-os", "ime": "Safeer OS (Tablica)", "vloga": "controller", "zmoznosti": []},
              {"id": "n-tel", "ime": "Telefon", "vloga": "controller"}]

    def test_ena_kartica_na_fizicno_napravo(self):
        s = _stran([["naprave", self.DVOJNA]])
        d = s[0]["dovoljenjaNaprav"]
        self.assertEqual(d["otrok"], 2, d["vsebina"])
        self.assertIn("<b>Tablica</b>", d["vsebina"])
        self.assertIn("<b>Telefon</b>", d["vsebina"])
        self.assertNotIn("Safeer OS (Tablica)", d["vsebina"], "kartica nosi ime identitete z vec zmoznostmi")
        self.assertTrue(s[0]["opombaDovoljenja"]["skrit"])

    def test_vsaka_kartica_ima_tri_profile(self):
        s = _stran([["naprave", [self.DVOJNA[2]]]])
        vsebina = s[0]["dovoljenjaNaprav"]["vsebina"]
        self.assertEqual(vsebina.count("<small>"), 3, vsebina)

    def test_brez_naprav_ni_kartic_je_pa_navodilo(self):
        s = _stran([["naprave", []]])
        self.assertEqual(s[0]["dovoljenjaNaprav"]["otrok"], 0)
        self.assertFalse(s[0]["opombaDovoljenja"]["skrit"])

    def test_ime_naprave_ni_html(self):
        """Ime doloci druga naprava; v kartico gre kot besedilo."""
        s = _stran([["naprave", [{"id": "n-x", "ime": "<img src=x onerror=alert(1)>", "vloga": "controller"}]]])
        vsebina = s[0]["dovoljenjaNaprav"]["vsebina"]
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", vsebina)
        self.assertNotIn("<img", vsebina)

    def test_izbrani_profil_je_oznacen(self):
        s = _stran([["naprave", [self.DVOJNA[2]]], ["dovoljenja", {"n-tel": "polno"}]])
        self.assertIn("✓", s[1]["dovoljenjaNaprav"]["vsebina"])
        self.assertNotIn("✓", s[0]["dovoljenjaNaprav"]["vsebina"])

    def test_deljene_mape_se_narisejo_tudi_ko_so_naprave(self):
        s = _stran([["naprave", self.DVOJNA],
                    ["deljeneMape", {"mape": [{"ime": "Videi", "pot": "C:\\Users\\Ana\\Videos"},
                                              {"ime": "Slike", "pot": "C:\\Users\\Ana\\Pictures"}], "standardne": True}]])
        self.assertEqual(s[1]["seznamMape"]["otrok"], 2, s[1]["seznamMape"]["vsebina"])
        self.assertIn("Videi", s[1]["seznamMape"]["vsebina"])

    def test_zahteva_za_dovoljenje_se_pokaze(self):
        s = _stran([["naprave", self.DVOJNA], ["dovoljenjeZahtevano", {"id": "n-tel", "ime": "Telefon"}]])
        self.assertIn("Telefon", s[1]["opombaDovoljenja"]["besedilo"])
        self.assertFalse(s[1]["opombaDovoljenja"]["skrit"])
        self.assertEqual(s[1]["dovoljenjaNaprav"]["otrok"], 2)


if __name__ == "__main__":
    unittest.main()
