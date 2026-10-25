.pragma library
// Ciste funkcije panela Datoteke (namizje Safeer OS za Windows): vnosi naprav v Linku, datum nastanka, filter po
// obdobju, razvrscanje in diski. Brez Qt - preizkusi jih windows/tests/test_datoteke_logika.py z Node.js.

// Vnos z naprave v Linku (files.list) -> vnos panela. Android da »modified« v milisekundah (MediaStore DATE_MODIFIED
// x 1000), racunalnik (core/link_datoteke) »modified« v ms ali »mtime« v sekundah. Datum nastanka: »date_taken«
// (ms, EXIF/MediaStore DATE_TAKEN), sicer cas spremembe.
function sekunde(v) {
    var n = Number(v) || 0
    if (n <= 0) return 0
    return n > 1e11 ? n / 1000 : n          // vecje od 1e11 so milisekunde (1e11 s je leto 5138)
}

function vrstaNaprave(d) {
    var t = String(d.type || d.vrsta || "")
    if (t === "folder" || t === "mapa") return "mapa"
    if (t === "image" || t === "slika") return "slika"
    if (t === "video") return "video"
    if (t === "audio" || t === "zvok") return "zvok"
    var m = String(d.mime || "")
    if (m.indexOf("image/") === 0) return "slika"
    if (m.indexOf("video/") === 0) return "video"
    if (m.indexOf("audio/") === 0) return "zvok"
    return t || ""
}

function vnosNaprave(d) {
    var vrsta = vrstaNaprave(d)
    var mapa = vrsta === "mapa"
    var spremenjeno = sekunde(d.modified) || sekunde(d.mtime) || sekunde(d.spremenjeno)
    return { ime: String(d.name || d.ime || ""), id: String(d.id || ""), mapa: mapa,
             velikost: Number(d.size || d.velikost || 0), spremenjeno: spremenjeno,
             nastanek: sekunde(d.date_taken) || sekunde(d.nastanek) || spremenjeno,
             vrsta: vrsta, mime: String(d.mime || ""), pot: String(d.id || "") }
}

function casNastanka(e) {
    return (e && (e.nastanek || e.spremenjeno || e.izbrisano)) || 0
}

// Obdobje za filter »Datum nastanka«: [od, do) v sekundah ali null (vse). »teden« zacne v ponedeljek (kot v Sloveniji).
function obmocje(vrsta, zdajMs, odNiz, doNiz) {
    var z = new Date(zdajMs)
    var polnoc = new Date(z.getFullYear(), z.getMonth(), z.getDate()).getTime() / 1000
    if (vrsta === "danes") return [polnoc, polnoc + 86400]
    if (vrsta === "teden") {
        var dan = (z.getDay() + 6) % 7            // ponedeljek = 0
        var zacetek = new Date(z.getFullYear(), z.getMonth(), z.getDate() - dan).getTime() / 1000
        return [zacetek, zacetek + 7 * 86400 + 3600]   // +1 h: premik ure v tednu ne odreze nedelje
    }
    if (vrsta === "mesec") {
        return [new Date(z.getFullYear(), z.getMonth(), 1).getTime() / 1000,
                new Date(z.getFullYear(), z.getMonth() + 1, 1).getTime() / 1000]
    }
    if (vrsta === "leto") {
        return [new Date(z.getFullYear(), 0, 1).getTime() / 1000, new Date(z.getFullYear() + 1, 0, 1).getTime() / 1000]
    }
    if (vrsta === "obdobje") {
        var a = datum(odNiz), b = datum(doNiz)
        if (a === null && b === null) return null
        return [a === null ? 0 : a, b === null ? 1e12 : b + 86400]
    }
    return null
}

// »25. 10. 2026«, »25.10.2026« ali »2026-10-25« -> polnoc tega dne (krajevni cas) v sekundah; null, ce ni datum.
function datum(niz) {
    var s = String(niz || "").trim()
    if (!s) return null
    var m = s.match(/^(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})$/), l, me, d
    if (m) { d = +m[1]; me = +m[2]; l = +m[3] }
    else {
        m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/)
        if (!m) return null
        l = +m[1]; me = +m[2]; d = +m[3]
    }
    var t = new Date(l, me - 1, d)
    if (t.getFullYear() !== l || t.getMonth() !== me - 1 || t.getDate() !== d) return null
    return t.getTime() / 1000
}

// Filter po imenu in obdobju; mape ostanejo (v njih je lahko kaj iz obdobja), razen ko je obdobje izbrano.
function filtriraj(elementi, besedilo, obm) {
    var q = String(besedilo || "").toLowerCase()
    return (elementi || []).filter(function (e) {
        if (q && String(e.ime || "").toLowerCase().indexOf(q) < 0) return false
        if (!obm) return true
        if (e.mapa) return false
        var c = casNastanka(e)
        return c >= obm[0] && c < obm[1]
    })
}

// Razvrscanje: »ime« (A-Z), »nastanek« (najnovejse najprej), »velikost« (najvecje najprej). Mape vedno na vrhu.
function razvrsti(elementi, nacin) {
    var v = (elementi || []).slice()
    v.sort(function (a, b) {
        if (!!a.mapa !== !!b.mapa) return a.mapa ? -1 : 1
        if (nacin === "nastanek") { var r = casNastanka(b) - casNastanka(a); if (r) return r }
        else if (nacin === "velikost") { var s = (b.velikost || 0) - (a.velikost || 0); if (s) return s }
        return String(a.ime || "").toLowerCase().localeCompare(String(b.ime || "").toLowerCase())
    })
    return v
}

// Disk (core/sistem_podatki.diski): ime kot v Raziskovalcu in delez zasedenosti 0..1.
function imeDiska(d, sistemskiNapis) {
    var n = String(d.naprava || "")
    var crka = /^[A-Za-z]:\\?$/.test(n) ? n.slice(0, 2).toUpperCase() : ""
    if (d.sistem) return sistemskiNapis + (crka ? " (" + crka + ")" : "")
    if (crka) return d.oznaka ? d.oznaka + " (" + crka + ")" : crka
    return d.oznaka || n
}

function zasedeno(d) {
    if (!d || !(d.velikost > 0)) return 0
    return Math.max(0, Math.min(1, 1 - (d.prosto || 0) / d.velikost))
}

// Ali je vnos za slicico (slika ali video).
function imaSlicico(e) {
    return !!e && !e.mapa && (e.vrsta === "slika" || e.vrsta === "video")
}

// Bliznjica »Fotografije« naprave: mapa fotoaparata, kot jo da naprava v korenu (Android: media:image).
function mapaFotografij(vnosi) {
    for (var i = 0; i < (vnosi || []).length; i++) {
        var e = vnosi[i]
        if (e && e.mapa && (e.id === "media:image" || e.id === "media:camera" || e.id === "media:dcim")) return e
    }
    return null
}

if (typeof module !== "undefined") module.exports = { sekunde: sekunde, vnosNaprave: vnosNaprave, casNastanka: casNastanka,
    obmocje: obmocje, datum: datum, filtriraj: filtriraj, razvrsti: razvrsti, imeDiska: imeDiska, zasedeno: zasedeno,
    imaSlicico: imaSlicico, mapaFotografij: mapaFotografij, vrstaNaprave: vrstaNaprave }
