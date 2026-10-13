// Panel Datoteke: Nedavno, Koš, mape, pogoni; seznam z odpiranjem, »Pokaži v mapi«, preimenovanjem in Košem
// (z Razveljavi). Seznam se osvezi sam, ko se mapa spremeni zunaj Safeer OS.
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

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
    readonly property var prikazani: elementi.filter(function (e) {
        return !filter || e.ime.toLowerCase().indexOf(filter.toLowerCase()) >= 0
    })

    function zacni(mape) {
        var v = [{ oznaka: koren.t("nedavno"), vir: { vrsta: "nedavno", pot: "" } },
                 { oznaka: koren.t("smeti"), vir: { vrsta: "smeti", pot: "smeti" } },
                 { naslov: koren.t("mape") }]
        mape.forEach(function (m) { v.push({ oznaka: koren.t(m.vrsta) !== m.vrsta ? koren.t(m.vrsta) : m.ime, vir: { vrsta: "lokalno", pot: m.pot } }) })
        v.push({ naslov: koren.t("naprave") })
        panel.viri = v; panel.lokalniViri = v
        koren.klic("nosilci", [], function (n) {
            var z = panel.lokalniViri.slice()
            ;(n || []).forEach(function (x) { z.push({ oznaka: x.ime + (x.ime === x.pot.replace("\\", "") ? "" : " (" + x.pot.replace("\\", "") + ")"), vir: { vrsta: "lokalno", pot: x.pot }, pogon: x }) })
            panel.lokalniViri = z
            if (!panel.naprava) panel.viri = z
        })
        odpri({ vrsta: "nedavno", pot: "" })
    }
    function odpri(v) { vir = v; filter = ""; poljeFilter.text = ""; nalozi(false) }
    function izberiNapravo(id, ime) {
        naprava = id; imeNaprave = ime; pot = []; streznik = null
        if (!id) { viri = lokalniViri; odpri({ vrsta: "nedavno", pot: "" }); return }
        viri = [{ naslov: koren.t("mapeNaprave") }]
        odpri({ vrsta: "naprava", pot: "" })
    }
    function vnosNaprave(d) {
        var mapa = d.type === "folder" || d.vrsta === "folder" || d.vrsta === "mapa"
        var ime = d.name || d.ime || ""
        return { ime: ime, id: d.id || "", mapa: mapa, velikost: d.size || d.velikost || 0,
                 spremenjeno: d.mtime || d.spremenjeno || 0, vrsta: mapa ? "mapa" : (d.vrsta || ""), pot: d.id || "" }
    }
    function nalozi(tiho) {
        var st = ++zahteva
        if (!tiho) elementi = []
        var konec = function (r) {
            if (st !== zahteva) return
            if (vir.vrsta === "lokalno") { elementi = (r && r.elementi) || []; stars = (r && r.stars) || "" }
            else if (vir.vrsta === "smeti") { elementi = (r && r.elementi) || []; stars = "" }
            else { elementi = r || []; stars = "" }
        }
        stanje = ""
        if (vir.vrsta === "naprava") {
            koren.klic("datotekeNaprave", [naprava, vir.pot], function (r) {
                if (st !== zahteva) return
                if (!r || !r.ok) { stanje = "napaka"; elementi = []; return }
                if (!r.shared) { stanje = "neDeli"; elementi = []; return }
                if (r.server) streznik = r.server
                var vnosi = (r.items || []).map(panel.vnosNaprave)
                vnosi.sort(function (a, b) { return a.mapa !== b.mapa ? (a.mapa ? -1 : 1) : a.ime.toLowerCase().localeCompare(b.ime.toLowerCase()) })
                elementi = vnosi
                if (vir.pot === "") {   // koren naprave: mape tudi v stranski vrstici
                    viri = [{ naslov: koren.t("mapeNaprave") }].concat(vnosi.filter(function (e) { return e.mapa })
                        .map(function (e) { return { oznaka: e.ime, vir: { vrsta: "naprava", pot: e.id }, ime: e.ime } }))
                }
            }, function () { if (st === zahteva) { stanje = "napaka"; elementi = [] } })
            return
        }
        if (vir.vrsta === "lokalno") { koren.klic("mapa", [vir.pot], konec); koren.klic("spremljajMapo", [vir.pot]) }
        else if (vir.vrsta === "smeti") koren.klic("smeti", [], konec)
        else koren.klic("nedavne", [], konec)
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
        return vir.vrsta === "smeti" ? koren.t("kosPrazen") : vir.vrsta === "nedavno" ? koren.t("niNedavnih") : koren.t("prazno")
    }

    RowLayout {
        anchors.fill: parent; anchors.margins: 14; spacing: 12
        // ---------------- viri
        ListView {
            id: viriSeznam
            Layout.preferredWidth: 170; Layout.fillHeight: true
            clip: true; model: panel.viri; boundsBehavior: Flickable.StopAtBounds
            header: Column {
                spacing: 8; bottomPadding: 6
                Text { text: koren.t("datoteke"); color: koren.paleta.besedilo; font.pixelSize: 16; font.bold: true; leftPadding: 4 }
                IzbiraNaprave {
                    width: viriSeznam.width; zmoznost: "datoteke"; naprave: koren.naprave
                    onIzbrana: function (id, ime) { panel.izberiNapravo(id, ime) }
                }
            }
            delegate: Item {
                width: viriSeznam.width; height: modelData.naslov ? 30 : 32
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
                    Text { text: modelData.oznaka || ""; color: parent.izbran ? Qt.lighter(koren.paleta.poudarek, 1.35) : koren.paleta.besedilo; font.pixelSize: 13; elide: Text.ElideRight
                           width: parent.width - 16; x: 10; anchors.verticalCenter: parent.verticalCenter }
                    MouseArea { id: mv; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
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
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 8
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                Gumb { besedilo: "↑"; visible: panel.stars !== "" || (panel.vir.vrsta === "naprava" && panel.pot.length > 0)
                       onKlik: {
                           if (panel.vir.vrsta === "naprava") {
                               var p = panel.pot.slice(0, -1); panel.pot = p
                               panel.odpri({ vrsta: "naprava", pot: p.length ? p[p.length - 1].id : "" })
                           } else panel.odpri({ vrsta: "lokalno", pot: panel.stars })
                       } }
                Text {
                    Layout.fillWidth: true; color: koren.paleta.besedilo; font.pixelSize: 12; elide: Text.ElideLeft
                    text: panel.vir.vrsta === "naprava" ? [panel.imeNaprave].concat(panel.pot.map(function (x) { return x.ime })).join("  ›  ")
                        : panel.vir.vrsta === "lokalno" ? panel.vir.pot : panel.vir.vrsta === "smeti" ? koren.t("smeti") : koren.t("nedavno")
                }
                Gumb { besedilo: koren.t("izprazni"); visible: panel.vir.vrsta === "smeti" && panel.elementi.length > 0; onKlik: potrdi.open() }
                Gumb { besedilo: "+ " + koren.t("novaMapa"); visible: panel.vir.vrsta === "lokalno"
                       onKlik: koren.klic("novaMapa", [panel.vir.pot, koren.t("novaMapa")], function (r) {
                           if (r && r.ok) { panel.nalozi(true); preimenovanje.zacni({ ime: r.ime, pot: r.pot }) } else koren.obvesti(koren.t("niUspelo")) }) }
                Rectangle {
                    width: 170; height: 30; radius: 15; color: Qt.rgba(1, 1, 1, 0.07); border.color: Qt.rgba(1, 1, 1, 0.12)
                    TextField {
                        id: poljeFilter
                        anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 10
                        placeholderText: koren.t("filter"); placeholderTextColor: koren.paleta.medlo; color: koren.paleta.besedilo; font.pixelSize: 12
                        background: Item {}
                        onTextChanged: panel.filter = text
                    }
                }
            }
            ListView {
                id: seznam
                Layout.fillWidth: true; Layout.fillHeight: true
                clip: true; model: panel.prikazani; boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                header: Row {
                    height: 26; spacing: 0
                    Text { text: koren.t("ime"); color: Qt.darker(koren.paleta.medlo, 1.15); font.pixelSize: 11; width: seznam.width - 190 }
                    Text { text: koren.t("velikost"); color: Qt.darker(koren.paleta.medlo, 1.15); font.pixelSize: 11; width: 80 }
                    Text { text: koren.t("spremenjeno"); color: Qt.darker(koren.paleta.medlo, 1.15); font.pixelSize: 11; width: 110 }
                }
                delegate: Rectangle {
                    width: seznam.width; height: 34; radius: 8
                    color: md.containsMouse ? Qt.rgba(1, 1, 1, 0.08) : "transparent"
                    Behavior on color { ColorAnimation { duration: 100 } }
                    Row {
                        anchors.verticalCenter: parent.verticalCenter; x: 6; spacing: 0
                        Row {
                            width: seznam.width - 196; spacing: 8
                            Rectangle {
                                width: 22; height: 22; radius: 6; anchors.verticalCenter: parent.verticalCenter
                                color: modelData.mapa ? "#3b82f6" : modelData.vrsta === "slika" ? "#e879f9" : modelData.vrsta === "video" ? "#f97316"
                                     : modelData.vrsta === "zvok" ? "#22c55e" : modelData.vrsta === "dokument" ? "#60a5fa" : "#64748b"
                                Text { anchors.centerIn: parent; color: "white"; font.pixelSize: 10; font.bold: true
                                       text: modelData.mapa ? "▣" : (modelData.ime.split(".").pop() || "?").slice(0, 3).toUpperCase() }
                            }
                            Text { text: modelData.ime; color: koren.paleta.besedilo; font.pixelSize: 13; elide: Text.ElideRight
                                   width: parent.width - 32; anchors.verticalCenter: parent.verticalCenter }
                        }
                        Text { text: modelData.mapa ? "" : koren.velikost(modelData.velikost); color: koren.paleta.medlo; font.pixelSize: 12; width: 80 }
                        Text { text: koren.cas(modelData.spremenjeno || modelData.izbrisano); color: koren.paleta.medlo; font.pixelSize: 12; width: 110 }
                    }
                    MouseArea {
                        id: md; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton
                        onDoubleClicked: panel.odpriElement(modelData)
                        onClicked: function (m) { if (m.button === Qt.RightButton) { meni.e = modelData; meni.popup() } }
                    }
                }
                Text {
                    anchors.centerIn: parent; visible: seznam.count === 0
                    text: panel.prazno(); color: koren.paleta.medlo; font.pixelSize: 13
                }
            }
        }
    }

    Menu {
        id: meni
        property var e: null
        MenuItem { text: koren.t("odpri"); visible: panel.vir.vrsta !== "smeti"; height: visible ? implicitHeight : 0; onTriggered: panel.odpriElement(meni.e) }
        MenuItem { text: koren.t("odpriSProgramom", { naprava: panel.imeNaprave })
                   visible: panel.vir.vrsta === "naprava" && !!meni.e && !meni.e.mapa; height: visible ? implicitHeight : 0
                   onTriggered: panel.odpriSProgramomNaprave(meni.e) }
        MenuItem { text: koren.t("pokazi"); visible: panel.vir.vrsta === "lokalno" || panel.vir.vrsta === "nedavno"; height: visible ? implicitHeight : 0; onTriggered: koren.klic("pokaziVMapi", [meni.e.pot]) }
        MenuItem { text: koren.t("preimenuj"); visible: panel.vir.vrsta === "lokalno"; height: visible ? implicitHeight : 0; onTriggered: preimenovanje.zacni(meni.e) }
        MenuItem { text: koren.t("vKos"); visible: panel.vir.vrsta === "lokalno" || panel.vir.vrsta === "nedavno"; height: visible ? implicitHeight : 0; onTriggered: panel.vKos(meni.e) }
        MenuItem { text: koren.t("obnovi"); visible: panel.vir.vrsta === "smeti"; height: visible ? implicitHeight : 0
                   onTriggered: koren.klic("obnoviIzSmeti", [meni.e.id], function (r) { if (r && r.ok) panel.nalozi(true); else koren.obvesti(koren.t("niUspelo")) }) }
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
