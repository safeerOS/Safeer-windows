// Panel Datoteke: Nedavno, Koš, mape, diski (prosti prostor), naprave v Safeer Linku; seznam ali mreža s pomanjšanimi
// sličicami slik in videov, razvrščanje in filter »Datum nastanka«; odpiranje, »Pokaži v mapi«, preimenovanje in Koš
// (z Razveljavi). Seznam se osveži sam, ko se mapa spremeni zunaj Safeer OS.
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "datoteke_logika.js" as L

Steklo {
    id: panel
    property var vir: ({ vrsta: "nedavno", pot: "" })
    property var elementi: []
    property var viri: []
    property string filter: ""
    property string stars: ""
    property int zahteva: 0
    // Naprava v Safeer Linku ("" = ta racunalnik): njene mape in datoteke (files.list prek Safeer Controla).
    property string naprava: ""
    property string imeNaprave: ""
    property var streznik: null
    property var pot: []                 // [{id, ime}] mape naprave od korena navzdol
    property var lokalniViri: []
    property string stanje: ""           // "", "napaka", "neDeli"
    // Diski s prostim prostorom (core/sistem_podatki.diski), opozorilo o malo prostora enkrat na sejo za disk.
    property var diski: []
    property var opozorjeni: ({})
    // Slicice: pot (ta racunalnik) ali oznaka (naprava) -> file:/// naslov slicice v predpomnilniku.
    property var slicice: ({})
    property string pogled: "seznam"     // "seznam" ali "mreza"
    property string razvrstitev: "ime"   // "ime", "nastanek", "velikost"
    property string obdobje: ""          // "", "danes", "teden", "mesec", "leto", "obdobje"
    property string obdobjeOd: ""
    property string obdobjeDo: ""
    property int naslednjiOdmik: 0       // naprava ima se vnosov (nalaganje po delih)
    readonly property bool naNapravi: vir.vrsta === "naprava"
    readonly property var prikazani: L.razvrsti(L.filtriraj(elementi, filter, L.obmocje(obdobje, Date.now(), obdobjeOd, obdobjeDo)), razvrstitev)

    function zacni(mape) {
        var v = [{ oznaka: koren.t("nedavno"), vir: { vrsta: "nedavno", pot: "" } },
                 { oznaka: koren.t("smeti"), vir: { vrsta: "smeti", pot: "smeti" } },
                 { naslov: koren.t("mape") }]
        mape.forEach(function (m) { v.push({ oznaka: koren.t(m.vrsta) !== m.vrsta ? koren.t(m.vrsta) : m.ime, vir: { vrsta: "lokalno", pot: m.pot } }) })
        panel.viri = v; panel.lokalniViri = v
        naloziDiske()
        odpri({ vrsta: "nedavno", pot: "" })
    }
    function naloziDiske() {
        koren.klic("diskiNamizja", [], function (d) {
            panel.diski = (d || []).filter(function (x) { return x && x.pot })
            var z = panel.lokalniViri.filter(function (x) { return !x.disk && x.naslov !== koren.t("diski") })
            if (panel.diski.length) z.push({ naslov: koren.t("diski") })
            panel.diski.forEach(function (x) { z.push({ disk: x, oznaka: L.imeDiska(x, koren.t("diskSistem")), vir: { vrsta: "lokalno", pot: x.pot } }) })
            panel.lokalniViri = z
            if (!panel.naprava) panel.viri = z
            opozori()
        })
    }
    function opozori() {
        var o = {}
        for (var k in opozorjeni) o[k] = opozorjeni[k]
        diski.forEach(function (d) {
            if (!d.malo_prostora || o[d.naprava]) return
            o[d.naprava] = true
            koren.obvesti(koren.t("diskMalo", { ime: L.imeDiska(d, koren.t("diskSistem")), prosto: koren.velikost(d.prosto || 0) }))
        })
        opozorjeni = o
    }
    Timer { interval: 60000; running: panel.visible && !panel.naprava; repeat: true; onTriggered: panel.naloziDiske() }

    function odpri(v) {
        vir = v; filter = ""; poljeFilter.text = ""; naslednjiOdmik = 0
        if (v.foto) { pogled = "mreza"; razvrstitev = "nastanek" }
        nalozi(false)
    }
    function izberiNapravo(id, ime) {
        naprava = id; imeNaprave = ime; pot = []; streznik = null
        if (!id) { viri = lokalniViri; odpri({ vrsta: "nedavno", pot: "" }); return }
        viri = [{ naslov: koren.t("mapeNaprave") }]
        odpri({ vrsta: "naprava", pot: "" })
    }
    function nalozi(tiho) {
        var st = ++zahteva
        if (!tiho) elementi = []
        var konec = function (r) {
            if (st !== zahteva) return
            if (vir.vrsta === "lokalno") { elementi = (r && r.elementi) || []; stars = (r && r.stars) || "" }
            else if (vir.vrsta === "smeti") { elementi = (r && r.elementi) || []; stars = "" }
            else { elementi = r || []; stars = "" }
            naloziSlicice()
        }
        stanje = ""
        if (vir.vrsta === "naprava") {
            koren.klic("datotekeNaprave", [naprava, vir.pot, 0], function (r) {
                if (st !== zahteva) return
                if (!r || !r.ok) { stanje = "napaka"; elementi = []; return }
                if (!r.shared) { stanje = "neDeli"; elementi = []; return }
                if (r.server) streznik = r.server
                naslednjiOdmik = Number(r.next_offset || 0)
                var vnosi = (r.items || []).map(L.vnosNaprave)
                elementi = vnosi
                if (vir.pot === "") {   // koren naprave: bliznjica Fotografije in mape tudi v stranski vrstici
                    var f = L.mapaFotografij(vnosi), v = []
                    if (f) v.push({ oznaka: koren.t("fotografijeNaprave"), vir: { vrsta: "naprava", pot: f.id, foto: true }, ime: f.ime })
                    v.push({ naslov: koren.t("mapeNaprave") })
                    viri = v.concat(vnosi.filter(function (e) { return e.mapa })
                        .map(function (e) { return { oznaka: e.ime, vir: { vrsta: "naprava", pot: e.id }, ime: e.ime } }))
                }
                naloziSlicice()
            }, function () { if (st === zahteva) { stanje = "napaka"; elementi = [] } })
            return
        }
        if (vir.vrsta === "lokalno") { koren.klic("mapa", [vir.pot], konec); koren.klic("spremljajMapo", [vir.pot]) }
        else if (vir.vrsta === "smeti") koren.klic("smeti", [], konec)
        else koren.klic("nedavne", [], konec)
    }
    // Naprava z veliko datotekami (galerija telefona) jih da po delih: »Naloži več« prinese naslednji del.
    function naloziVec() {
        var st = zahteva, odmik = naslednjiOdmik
        naslednjiOdmik = 0
        koren.klic("datotekeNaprave", [naprava, vir.pot, odmik], function (r) {
            if (st !== zahteva || !r || !r.ok) return
            if (r.server) streznik = r.server
            naslednjiOdmik = Number(r.next_offset || 0)
            elementi = elementi.concat((r.items || []).map(L.vnosNaprave))
            naloziSlicice()
        })
    }

    // ---------------------------------------------------------------- slicice (v ozadju, sproti)
    function izvorSlicic() { return vir.vrsta === "naprava" ? naprava : "ta" }
    function naloziSlicice() {
        if (vir.vrsta === "smeti") return
        var izvor = izvorSlicic()
        var manjka = elementi.filter(function (e) { return L.imaSlicico(e) && !(e.pot in panel.slicice) })
        if (!manjka.length) return
        var seznam = manjka.map(function (e) {
            return izvor === "ta" ? { pot: e.pot, vrsta: e.vrsta }
                                  : { id: e.id, vrsta: e.vrsta, mime: e.mime, ime: e.ime, spremenjeno: e.spremenjeno, velikost: e.velikost }
        })
        koren.klic("sliciceNamizja", [izvor, seznam, izvor === "ta" ? null : streznik], function (r) {
            if (r && r.slicice) dodajSlicice(r.slicice)
        })
    }
    function dodajSlicice(nove) {
        var s = {}, n = 0
        for (var k in slicice) { s[k] = slicice[k]; n++ }
        if (n > 3000) s = {}                 // drzimo samo zadnje (pomnilnik), predpomnilnik na disku ostane
        for (var j in nove) s[j] = nove[j]
        slicice = s
    }
    function slicicaPrisla(p) {               // dogodek »slicica« iz Pythona (narejena v ozadju)
        if (!p || p.izvor !== izvorSlicic()) return
        var o = {}; o[p.id] = p.url
        dodajSlicice(o)
    }

    function odpriElement(e) {
        if (vir.vrsta === "smeti") return
        if (vir.vrsta === "naprava") {
            if (e.mapa) { pot = pot.concat([{ id: e.id, ime: e.ime }]); odpri({ vrsta: "naprava", pot: e.id }); return }
            // Najbolj gladko: datoteka pride sem in jo odpre program tega racunalnika (fotografije, video, urejanje).
            // Ce prenos ni mogoc, jo odpre program naprave prek oddaljenega namizja (lastnik, 13. 10. 2026).
            if (streznik && streznik.base_url) odpriTukaj(e)
            else odpriSProgramomNaprave(e)
            return
        }
        if (e.mapa) odpri({ vrsta: "lokalno", pot: e.pot })
        else koren.klic("odpriDatoteko", [e.pot])
    }
    function odpriTukaj(e) {
        koren.obvesti(koren.t("prenasam", { ime: e.ime }))
        koren.klic("prenesiDatotekoNaprave", [naprava, e.id, e.ime, streznik], function (r) {
            if (!r || !r.ok) koren.obvesti(koren.t("niUspelo"))
        })
    }
    function odpriSProgramomNaprave(e) {
        // Prek oddaljenega namizja: naprava datoteko odpre na svojem LOCENEM zaslonu - njen uporabnik tega ne opazi.
        koren.obvesti(koren.t("odpiramZ", { ime: e.ime, naprava: imeNaprave }))
        koren.klic("odpriDatotekoTukaj", [naprava, e.id], function (r) {
            if (!(r && r.ok)) koren.obvesti(r && r.koda === "ni_locenega_zaslona" ? koren.t("niLocenega") : ((r && r.message) || koren.t("niUspelo")))
        })
    }
    function vKos(e) {
        koren.klic("vSmeti", [e.pot], function (r) {
            if (!r || !r.ok) { koren.obvesti(koren.t("niUspelo")); return }
            panel.nalozi(true)
            koren.obvesti(koren.t("vKosPoslano", { ime: e.ime }), r.id ? koren.t("razveljavi") : "",
                          function () { koren.klic("obnoviIzSmeti", [r.id], function () { panel.nalozi(true) }) })
        })
    }
    function prazno() {
        if (stanje === "napaka") return koren.t("niOdgovorila")
        if (stanje === "neDeli") return koren.t("neDeli")
        if (obdobje && elementi.length) return koren.t("niVObdobju")
        return vir.vrsta === "smeti" ? koren.t("kosPrazen") : vir.vrsta === "nedavno" ? koren.t("niNedavnih") : koren.t("prazno")
    }
    function barvaVrste(e) {
        return e.mapa ? "#3b82f6" : e.vrsta === "slika" ? "#e879f9" : e.vrsta === "video" ? "#f97316"
             : e.vrsta === "zvok" ? "#22c55e" : e.vrsta === "dokument" ? "#60a5fa" : "#64748b"
    }
    function oznakaVrste(e) { return e.mapa ? "▣" : (e.ime.split(".").pop() || "?").slice(0, 3).toUpperCase() }
    function napisRazvrstitve() {        // kratko na gumbu (panel je ozek), celotno v meniju
        return "⇅ " + koren.t({ ime: "ime", nastanek: "nastanek", velikost: "velikost" }[razvrstitev] || "ime")
    }
    function napisObdobja() {
        if (!obdobje) return koren.t("datumNastanka")
        if (obdobje === "obdobje") return (obdobjeOd || "…") + " – " + (obdobjeDo || "…")
        return koren.t({ danes: "danes", teden: "taTeden", mesec: "taMesec", leto: "letos" }[obdobje])
    }

    RowLayout {
        anchors.fill: parent; anchors.margins: 14; spacing: 12
        // ---------------- viri
        ListView {
            id: viriSeznam
            Layout.preferredWidth: 178; Layout.fillHeight: true
            clip: true; model: panel.viri; boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            header: Column {
                spacing: 8; bottomPadding: 6
                Text { text: koren.t("datoteke"); color: koren.paleta.besedilo; font.pixelSize: 16; font.bold: true; leftPadding: 4 }
                IzbiraNaprave {
                    width: viriSeznam.width; zmoznost: "datoteke"; naprave: koren.naprave
                    onIzbrana: function (id, ime) { panel.izberiNapravo(id, ime) }
                }
            }
            delegate: Item {
                width: viriSeznam.width; height: modelData.naslov ? 30 : modelData.disk ? 48 : 32
                Text {
                    visible: !!modelData.naslov; text: (modelData.naslov || "").toUpperCase()
                    color: Qt.darker(koren.paleta.medlo, 1.15); font.pixelSize: 10; font.letterSpacing: 1; anchors.bottom: parent.bottom; anchors.bottomMargin: 6; x: 6
                }
                Rectangle {
                    visible: !modelData.naslov
                    anchors.fill: parent; anchors.margins: 1; radius: 9
                    readonly property bool izbran: !!modelData.vir && panel.vir.vrsta === modelData.vir.vrsta && panel.vir.pot === modelData.vir.pot
                    color: izbran ? koren.poudarekA(0.18) : (mv.containsMouse ? Qt.rgba(1, 1, 1, 0.08) : "transparent")
                    Behavior on color { ColorAnimation { duration: 120 } }
                    Column {
                        x: 10; width: parent.width - 18; anchors.verticalCenter: parent.verticalCenter; spacing: 3
                        Text { text: modelData.oznaka || ""; width: parent.width; elide: Text.ElideRight; font.pixelSize: 13
                               color: parent.parent.izbran ? Qt.lighter(koren.paleta.poudarek, 1.35) : koren.paleta.besedilo }
                        // Disk: zasedenost (rdece, ko zmanjkuje prostora) in »… prostih od …«
                        Rectangle {
                            visible: !!modelData.disk; width: parent.width; height: 4; radius: 2; color: Qt.rgba(1, 1, 1, 0.12)
                            Rectangle {
                                height: parent.height; radius: 2
                                width: modelData.disk ? parent.width * L.zasedeno(modelData.disk) : 0
                                color: modelData.disk && modelData.disk.malo_prostora ? "#f87171" : koren.paleta.poudarek
                            }
                        }
                        Text {
                            visible: !!modelData.disk; width: parent.width; elide: Text.ElideRight; font.pixelSize: 10
                            color: modelData.disk && modelData.disk.malo_prostora ? "#fca5a5" : koren.paleta.medlo
                            text: modelData.disk ? koren.t("diskProsto", { prosto: koren.velikost(modelData.disk.prosto || 0), skupaj: koren.velikost(modelData.disk.velikost) }) : ""
                        }
                    }
                    MouseArea { id: mv; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                ToolTip.visible: !!modelData.disk && containsMouse; ToolTip.delay: 600
                                ToolTip.text: modelData.disk ? (modelData.oznaka + (modelData.disk.datotecni_sistem ? " · " + modelData.disk.datotecni_sistem : "")) : ""
                                onClicked: if (modelData.vir) {
                                    if (modelData.vir.vrsta === "naprava") panel.pot = [{ id: modelData.vir.pot, ime: modelData.ime }]
                                    panel.odpri(modelData.vir)
                                } }
                }
            }
        }
        Rectangle { Layout.fillHeight: true; width: 1; color: Qt.rgba(1, 1, 1, 0.08) }
        // ---------------- vsebina
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; Layout.preferredWidth: 100; spacing: 8
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                Gumb { besedilo: "↑"; visible: panel.stars !== "" || (panel.vir.vrsta === "naprava" && panel.pot.length > 0)
                       Accessible.name: koren.t("gor")
                       onKlik: {
                           if (panel.vir.vrsta === "naprava") {
                               var p = panel.pot.slice(0, -1); panel.pot = p
                               panel.odpri({ vrsta: "naprava", pot: p.length ? p[p.length - 1].id : "" })
                           } else panel.odpri({ vrsta: "lokalno", pot: panel.stars })
                       } }
                Text {
                    Layout.fillWidth: true; Layout.preferredWidth: 40; color: koren.paleta.besedilo; font.pixelSize: 12; elide: Text.ElideLeft
                    text: panel.vir.vrsta === "naprava" ? [panel.imeNaprave].concat(panel.pot.map(function (x) { return x.ime })).join("  ›  ")
                        : panel.vir.vrsta === "lokalno" ? panel.vir.pot : panel.vir.vrsta === "smeti" ? koren.t("smeti") : koren.t("nedavno")
                }
                Gumb { besedilo: koren.t("izprazni"); visible: panel.vir.vrsta === "smeti" && panel.elementi.length > 0; onKlik: potrdi.open() }
                Gumb { besedilo: "+ " + koren.t("novaMapa"); visible: panel.vir.vrsta === "lokalno"
                       onKlik: koren.klic("novaMapa", [panel.vir.pot, koren.t("novaMapa")], function (r) {
                           if (r && r.ok) { panel.nalozi(true); preimenovanje.zacni({ ime: r.ime, pot: r.pot }) } else koren.obvesti(koren.t("niUspelo")) }) }
                Rectangle {
                    Layout.preferredWidth: 130; height: 30; radius: 15; color: Qt.rgba(1, 1, 1, 0.07); border.color: Qt.rgba(1, 1, 1, 0.12)
                    TextField {
                        id: poljeFilter
                        anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 10
                        placeholderText: koren.t("filter"); placeholderTextColor: koren.paleta.medlo; color: koren.paleta.besedilo; font.pixelSize: 12
                        background: Item {}
                        onTextChanged: panel.filter = text
                    }
                }
            }
            // Razvrscanje, datum nastanka in pogled (seznam / mreza s slicicami)
            RowLayout {
                Layout.fillWidth: true; spacing: 6
                visible: panel.vir.vrsta !== "smeti"
                Gumb { id: gumbRazvrsti; besedilo: panel.napisRazvrstitve() + " ▾"; Accessible.name: koren.t("razvrsti")
                       onKlik: meniRazvrsti.popup(gumbRazvrsti, 0, height + 4) }
                Gumb { id: gumbObdobje; besedilo: panel.napisObdobja() + " ▾"; poudarjen: panel.obdobje !== ""
                       onKlik: meniObdobje.popup(gumbObdobje, 0, height + 4) }
                Item { Layout.fillWidth: true }
                Text { text: panel.prikazani.length ? String(panel.prikazani.length) : ""; color: koren.paleta.medlo; font.pixelSize: 11 }
                Gumb { besedilo: "☰"; poudarjen: panel.pogled === "seznam"; Accessible.name: koren.t("pogledSeznam"); onKlik: panel.pogled = "seznam"
                       ToolTip.visible: hov1.hovered; ToolTip.text: koren.t("pogledSeznam"); HoverHandler { id: hov1 } }
                Gumb { besedilo: "▦"; poudarjen: panel.pogled === "mreza"; Accessible.name: koren.t("pogledMreza"); onKlik: panel.pogled = "mreza"
                       ToolTip.visible: hov2.hovered; ToolTip.text: koren.t("pogledMreza"); HoverHandler { id: hov2 } }
            }
            Item {
                Layout.fillWidth: true; Layout.fillHeight: true
                ListView {
                    id: seznam
                    anchors.fill: parent
                    visible: panel.pogled === "seznam"
                    clip: true; model: visible ? panel.prikazani : []; boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    header: Row {
                        height: 26; spacing: 0
                        Text { text: koren.t("ime"); color: Qt.darker(koren.paleta.medlo, 1.15); font.pixelSize: 11; width: seznam.width - 190 }
                        Text { text: koren.t("velikost"); color: Qt.darker(koren.paleta.medlo, 1.15); font.pixelSize: 11; width: 80 }
                        Text { text: koren.t(panel.naNapravi ? "nastanek" : "spremenjeno"); color: Qt.darker(koren.paleta.medlo, 1.15); font.pixelSize: 11; width: 110 }
                    }
                    footer: Item {
                        width: seznam.width; height: panel.naslednjiOdmik > 0 ? 44 : 0
                        Gumb { anchors.centerIn: parent; visible: panel.naslednjiOdmik > 0; besedilo: koren.t("naloziVec"); onKlik: panel.naloziVec() }
                    }
                    delegate: Rectangle {
                        width: seznam.width; height: 36; radius: 8
                        color: md.containsMouse ? Qt.rgba(1, 1, 1, 0.08) : "transparent"
                        Behavior on color { ColorAnimation { duration: 100 } }
                        Row {
                            anchors.verticalCenter: parent.verticalCenter; x: 6; spacing: 0
                            Row {
                                width: seznam.width - 196; spacing: 8
                                Rectangle {
                                    width: 26; height: 26; radius: 6; anchors.verticalCenter: parent.verticalCenter; clip: true
                                    color: slicicaS.status === Image.Ready ? "transparent" : panel.barvaVrste(modelData)
                                    Text { anchors.centerIn: parent; color: "white"; font.pixelSize: 10; font.bold: true
                                           visible: slicicaS.status !== Image.Ready; text: panel.oznakaVrste(modelData) }
                                    Image { id: slicicaS; anchors.fill: parent; fillMode: Image.PreserveAspectCrop; asynchronous: true
                                            sourceSize: Qt.size(52, 52); source: L.imaSlicico(modelData) ? (panel.slicice[modelData.pot] || "") : "" }
                                }
                                Text { text: modelData.ime; color: koren.paleta.besedilo; font.pixelSize: 13; elide: Text.ElideRight
                                       width: parent.width - 36; anchors.verticalCenter: parent.verticalCenter }
                            }
                            Text { text: modelData.mapa ? "" : koren.velikost(modelData.velikost); color: koren.paleta.medlo; font.pixelSize: 12; width: 80
                                   anchors.verticalCenter: parent.verticalCenter }
                            Text { text: koren.cas(L.casNastanka(modelData)); color: koren.paleta.medlo; font.pixelSize: 12; width: 110
                                   anchors.verticalCenter: parent.verticalCenter }
                        }
                        MouseArea {
                            id: md; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton
                            onDoubleClicked: panel.odpriElement(modelData)
                            onClicked: function (m) { if (m.button === Qt.RightButton) { meni.e = modelData; meni.popup() } }
                        }
                    }
                }
                GridView {
                    id: mreza
                    anchors.fill: parent
                    visible: panel.pogled === "mreza"
                    clip: true; model: visible ? panel.prikazani : []; boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    readonly property int stolpcev: Math.max(1, Math.floor(width / 118))
                    cellWidth: Math.floor(width / stolpcev); cellHeight: cellWidth + 26
                    footer: Item {
                        width: mreza.width; height: panel.naslednjiOdmik > 0 ? 44 : 0
                        Gumb { anchors.centerIn: parent; visible: panel.naslednjiOdmik > 0; besedilo: koren.t("naloziVec"); onKlik: panel.naloziVec() }
                    }
                    delegate: Item {
                        width: mreza.cellWidth; height: mreza.cellHeight
                        Rectangle {
                            anchors.fill: parent; anchors.margins: 3; radius: 10
                            color: mm.containsMouse ? Qt.rgba(1, 1, 1, 0.08) : "transparent"
                            Rectangle {
                                id: okvir
                                x: 5; y: 5; width: parent.width - 10; height: width; radius: 8; clip: true
                                color: slicicaM.status === Image.Ready ? Qt.rgba(0, 0, 0, 0.25) : Qt.rgba(1, 1, 1, 0.05)
                                Rectangle {
                                    anchors.centerIn: parent; width: 40; height: 40; radius: 10; visible: slicicaM.status !== Image.Ready
                                    color: panel.barvaVrste(modelData)
                                    Text { anchors.centerIn: parent; color: "white"; font.pixelSize: 12; font.bold: true; text: panel.oznakaVrste(modelData) }
                                }
                                Image { id: slicicaM; anchors.fill: parent; fillMode: Image.PreserveAspectCrop; asynchronous: true
                                        sourceSize: Qt.size(256, 256); source: L.imaSlicico(modelData) ? (panel.slicice[modelData.pot] || "") : ""
                                        opacity: status === Image.Ready ? 1 : 0; Behavior on opacity { NumberAnimation { duration: 180 } } }
                                Text { visible: modelData.vrsta === "video" && slicicaM.status === Image.Ready; text: "▶"; color: "white"
                                       font.pixelSize: 14; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 6; style: Text.Outline; styleColor: "#80000000" }
                            }
                            Text { anchors.top: okvir.bottom; anchors.topMargin: 4; x: 5; width: parent.width - 10; horizontalAlignment: Text.AlignHCenter
                                   text: modelData.ime; color: koren.paleta.besedilo; font.pixelSize: 11; elide: Text.ElideMiddle }
                            MouseArea {
                                id: mm; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton
                                ToolTip.visible: containsMouse; ToolTip.delay: 700
                                ToolTip.text: modelData.ime + (modelData.mapa ? "" : "\n" + koren.velikost(modelData.velikost) + " · " + koren.cas(L.casNastanka(modelData)))
                                onDoubleClicked: panel.odpriElement(modelData)
                                onClicked: function (m) { if (m.button === Qt.RightButton) { meni.e = modelData; meni.popup() } }
                            }
                        }
                    }
                }
                Text {
                    anchors.centerIn: parent; visible: panel.prikazani.length === 0
                    text: panel.prazno(); color: koren.paleta.medlo; font.pixelSize: 13
                }
            }
        }
    }

    Meni {
        id: meniRazvrsti
        MeniVnos { text: koren.t("poImenu"); izbran: panel.razvrstitev === "ime"; onTriggered: panel.razvrstitev = "ime" }
        MeniVnos { text: koren.t("poDatumu"); izbran: panel.razvrstitev === "nastanek"; onTriggered: panel.razvrstitev = "nastanek" }
        MeniVnos { text: koren.t("poVelikosti"); izbran: panel.razvrstitev === "velikost"; onTriggered: panel.razvrstitev = "velikost" }
    }
    Meni {
        id: meniObdobje
        MeniVnos { text: koren.t("vseObdobje"); izbran: panel.obdobje === ""; onTriggered: panel.obdobje = "" }
        MeniVnos { text: koren.t("danes"); izbran: panel.obdobje === "danes"; onTriggered: panel.obdobje = "danes" }
        MeniVnos { text: koren.t("taTeden"); izbran: panel.obdobje === "teden"; onTriggered: panel.obdobje = "teden" }
        MeniVnos { text: koren.t("taMesec"); izbran: panel.obdobje === "mesec"; onTriggered: panel.obdobje = "mesec" }
        MeniVnos { text: koren.t("letos"); izbran: panel.obdobje === "leto"; onTriggered: panel.obdobje = "leto" }
        MeniVnos { text: koren.t("izberiObdobje"); izbran: panel.obdobje === "obdobje"; onTriggered: izbiraObdobja.zacni() }
    }

    Meni {
        id: meni
        property var e: null
        MeniVnos { text: koren.t("odpri"); visible: panel.vir.vrsta !== "smeti"; onTriggered: panel.odpriElement(meni.e) }
        MeniVnos { text: koren.t("odpriSProgramom", { naprava: panel.imeNaprave })
                   visible: panel.vir.vrsta === "naprava" && !!meni.e && !meni.e.mapa
                   onTriggered: panel.odpriSProgramomNaprave(meni.e) }
        MeniVnos { text: koren.t("pokazi"); visible: panel.vir.vrsta === "lokalno" || panel.vir.vrsta === "nedavno"; onTriggered: koren.klic("pokaziVMapi", [meni.e.pot]) }
        MeniVnos { text: koren.t("preimenuj"); visible: panel.vir.vrsta === "lokalno"; onTriggered: preimenovanje.zacni(meni.e) }
        MeniVnos { text: koren.t("vKos"); visible: panel.vir.vrsta === "lokalno" || panel.vir.vrsta === "nedavno"; onTriggered: panel.vKos(meni.e) }
        MeniVnos { text: koren.t("obnovi"); visible: panel.vir.vrsta === "smeti"
                   onTriggered: koren.klic("obnoviIzSmeti", [meni.e.id], function (r) { if (r && r.ok) panel.nalozi(true); else koren.obvesti(koren.t("niUspelo")) }) }
    }

    Popup {
        id: izbiraObdobja
        anchors.centerIn: parent; modal: true; padding: 18; width: 380
        background: Rectangle { radius: 16; color: koren.paleta.vnos; border.color: Qt.rgba(1, 1, 1, 0.14) }
        function zacni() { poljeOd.text = panel.obdobjeOd; poljeDo.text = panel.obdobjeDo; napaka.text = ""; open(); poljeOd.forceActiveFocus() }
        function uporabi() {
            var od = poljeOd.text.trim(), dd = poljeDo.text.trim()
            if ((od && L.datum(od) === null) || (dd && L.datum(dd) === null) || (!od && !dd)) { napaka.text = koren.t("obdobjeNapaka"); return }
            panel.obdobjeOd = od; panel.obdobjeDo = dd; panel.obdobje = "obdobje"
            close()
        }
        ColumnLayout {
            anchors.fill: parent; spacing: 10
            Text { text: koren.t("izberiObdobje"); color: koren.paleta.besedilo; font.pixelSize: 15; font.bold: true }
            RowLayout {
                spacing: 8
                Text { text: koren.t("od"); color: koren.paleta.medlo; font.pixelSize: 12; Layout.preferredWidth: 28 }
                TextField { id: poljeOd; Layout.fillWidth: true; color: koren.paleta.besedilo; font.pixelSize: 14; placeholderText: "1. 10. 2026"
                            placeholderTextColor: koren.paleta.medlo
                            background: Rectangle { radius: 8; color: Qt.rgba(1, 1, 1, 0.08); border.color: koren.paleta.poudarek }
                            Keys.onReturnPressed: izbiraObdobja.uporabi() }
            }
            RowLayout {
                spacing: 8
                Text { text: koren.t("do"); color: koren.paleta.medlo; font.pixelSize: 12; Layout.preferredWidth: 28 }
                TextField { id: poljeDo; Layout.fillWidth: true; color: koren.paleta.besedilo; font.pixelSize: 14; placeholderText: "25. 10. 2026"
                            placeholderTextColor: koren.paleta.medlo
                            background: Rectangle { radius: 8; color: Qt.rgba(1, 1, 1, 0.08); border.color: koren.paleta.poudarek }
                            Keys.onReturnPressed: izbiraObdobja.uporabi() }
            }
            Text { id: napaka; visible: text !== ""; color: "#fca5a5"; font.pixelSize: 12; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            RowLayout { Layout.alignment: Qt.AlignRight; spacing: 8
                Gumb { besedilo: koren.t("preklici"); onKlik: izbiraObdobja.close() }
                Gumb { besedilo: koren.t("uporabi"); poudarjen: true; onKlik: izbiraObdobja.uporabi() } }
        }
    }

    Popup {
        id: preimenovanje
        property var e: null
        anchors.centerIn: parent; modal: true; padding: 18; width: 380
        background: Rectangle { radius: 16; color: koren.paleta.vnos; border.color: Qt.rgba(1, 1, 1, 0.14) }
        function zacni(e) { preimenovanje.e = e; novoIme.text = e.ime; open(); novoIme.forceActiveFocus(); novoIme.selectAll() }
        function shrani() {
            koren.klic("preimenujDatoteko", [preimenovanje.e.pot, novoIme.text], function (r) {
                if (r && r.ok) panel.nalozi(true); else koren.obvesti(koren.t("niUspelo"))
            })
            close()
        }
        ColumnLayout {
            anchors.fill: parent; spacing: 12
            Text { text: koren.t("preimenuj"); color: koren.paleta.besedilo; font.pixelSize: 15; font.bold: true }
            TextField { id: novoIme; Layout.fillWidth: true; color: koren.paleta.besedilo; font.pixelSize: 14
                        background: Rectangle { radius: 8; color: Qt.rgba(1, 1, 1, 0.08); border.color: koren.paleta.poudarek }
                        Keys.onReturnPressed: preimenovanje.shrani() }
            RowLayout { Layout.alignment: Qt.AlignRight; spacing: 8
                Gumb { besedilo: koren.t("preklici"); onKlik: preimenovanje.close() }
                Gumb { besedilo: koren.t("shrani"); poudarjen: true; onKlik: preimenovanje.shrani() } }
        }
    }

    Popup {
        id: potrdi
        anchors.centerIn: parent; modal: true; padding: 18; width: 400
        background: Rectangle { radius: 16; color: koren.paleta.vnos; border.color: Qt.rgba(1, 1, 1, 0.14) }
        ColumnLayout {
            anchors.fill: parent; spacing: 14
            Text { text: koren.t("izprazniVpr"); color: koren.paleta.besedilo; font.pixelSize: 14; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            RowLayout { Layout.alignment: Qt.AlignRight; spacing: 8
                Gumb { besedilo: koren.t("preklici"); onKlik: potrdi.close() }
                Gumb { besedilo: koren.t("izprazni"); poudarjen: true
                       onKlik: { koren.klic("izprazniSmeti", [], function () { panel.nalozi(true) }); potrdi.close() } } }
        }
    }
}
