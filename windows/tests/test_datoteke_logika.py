"""Ciste funkcije panela Datoteke na namizju QML (qml/datoteke_logika.js): vnosi naprav (Android »modified« v ms),
datum nastanka (date_taken), filter »Datum nastanka« (Danes, Ta teden, Ta mesec, Izberi obdobje), razvrscanje,
diski in bliznjica Fotografije. Preizkus tece v Node.js (isti JavaScript kot v QML)."""
import json
import os
import shutil
import subprocess
import unittest

KOREN = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
JS = os.path.join(KOREN, "windows", "safeer_windows", "qml", "datoteke_logika.js")

PREIZKUS = r"""
const fs = require("fs"), vm = require("vm"), assert = require("assert");
const koda = fs.readFileSync(process.argv[1], "utf8").replace(/^\.pragma library\s*/, "");
const m = { exports: {} }; vm.runInNewContext(koda, { module: m });
const L = m.exports;
// Android: modified v ms; racunalnik: mtime v s; date_taken ima prednost.
let v = L.vnosNaprave({ id: "media:image:5", name: "IMG.jpg", type: "image", size: 10, modified: 1761385200000 });
assert.strictEqual(v.spremenjeno, 1761385200); assert.strictEqual(v.nastanek, 1761385200); assert.strictEqual(v.vrsta, "slika");
v = L.vnosNaprave({ id: "x", name: "a.jpg", mime: "image/jpeg", mtime: 1700000000, date_taken: 1600000000000 });
assert.strictEqual(v.nastanek, 1600000000); assert.strictEqual(v.spremenjeno, 1700000000);
assert.strictEqual(L.vnosNaprave({ id: "media:image", name: "Fotografije", type: "folder" }).mapa, true);
// Obdobja (krajevni cas): sreda 22. 10. 2026 ob 15:00
const zdaj = new Date(2026, 9, 22, 15, 0).getTime();
const d = L.obmocje("danes", zdaj); assert.strictEqual(d[0], new Date(2026, 9, 22).getTime() / 1000); assert.strictEqual(d[1] - d[0], 86400);
const t = L.obmocje("teden", zdaj); assert.strictEqual(t[0], new Date(2026, 9, 19).getTime() / 1000);   // ponedeljek
const me = L.obmocje("mesec", zdaj); assert.strictEqual(me[0], new Date(2026, 9, 1).getTime() / 1000); assert.strictEqual(me[1], new Date(2026, 10, 1).getTime() / 1000);
assert.strictEqual(L.obmocje("", zdaj), null);
const o = L.obmocje("obdobje", zdaj, "1. 10. 2026", "2026-10-05");
assert.strictEqual(o[0], new Date(2026, 9, 1).getTime() / 1000); assert.strictEqual(o[1], new Date(2026, 9, 6).getTime() / 1000);
assert.strictEqual(L.datum("31. 2. 2026"), null); assert.strictEqual(L.datum("nekaj"), null);
// Filter: mape izpadejo samo, ko je obdobje izbrano; ime brez razlike v velikih crkah.
const el = [{ ime: "Mapa", mapa: true }, { ime: "Danes.jpg", nastanek: d[0] + 100 }, { ime: "Lani.jpg", nastanek: d[0] - 400 * 86400 }];
assert.deepStrictEqual(L.filtriraj(el, "", d).map(e => e.ime), ["Danes.jpg"]);
assert.deepStrictEqual(L.filtriraj(el, "lani", null).map(e => e.ime), ["Lani.jpg"]);
assert.strictEqual(L.filtriraj(el, "", null).length, 3);
// Razvrscanje: mape vedno prve; nastanek najnovejsi prvi; velikost najvecja prva.
assert.deepStrictEqual(L.razvrsti(el, "nastanek").map(e => e.ime), ["Mapa", "Danes.jpg", "Lani.jpg"]);
assert.deepStrictEqual(L.razvrsti([{ ime: "b", velikost: 1 }, { ime: "a", velikost: 9 }], "velikost").map(e => e.ime), ["a", "b"]);
assert.deepStrictEqual(L.razvrsti([{ ime: "b" }, { ime: "A" }], "ime").map(e => e.ime), ["A", "b"]);
// Diski
assert.strictEqual(L.imeDiska({ naprava: "C:", sistem: true }, "Sistemski disk"), "Sistemski disk (C:)");
assert.strictEqual(L.imeDiska({ naprava: "D:", oznaka: "Podatki" }, "x"), "Podatki (D:)");
assert.strictEqual(L.zasedeno({ velikost: 100, prosto: 25 }), 0.75); assert.strictEqual(L.zasedeno({ velikost: 0 }), 0);
// Slicice in bliznjica Fotografije (Android: media:image)
assert.ok(L.imaSlicico({ vrsta: "video" })); assert.ok(!L.imaSlicico({ vrsta: "slika", mapa: true }));
assert.strictEqual(L.mapaFotografij([{ id: "media:video", mapa: true }, { id: "media:image", mapa: true }]).id, "media:image");
assert.strictEqual(L.mapaFotografij([{ id: "share:0:", mapa: true }]), null);
console.log("ok");
"""


@unittest.skipIf(shutil.which("node") is None, "brez Node.js")
class DatotekeLogika(unittest.TestCase):
    def test_logika(self):
        r = subprocess.run(["node", "-e", PREIZKUS, JS], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ok", r.stdout)

    def test_qml_uporablja_knjiznico(self):
        with open(os.path.join(os.path.dirname(JS), "Datoteke.qml"), encoding="utf-8") as f:
            qml = f.read()
        self.assertIn('import "datoteke_logika.js" as L', qml)
        # Slicice slik in videov ter Fotografije naprave so v panelu.
        for niz in ('koren.klic("sliciceNamizja"', "GridView", "L.mapaFotografij(vnosi)", '"diskiNamizja"', "naloziVec()"):
            self.assertIn(niz, qml)


if __name__ == "__main__":
    unittest.main()
