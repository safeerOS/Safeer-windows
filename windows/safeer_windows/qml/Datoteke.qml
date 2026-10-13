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
    readonly property var prikazani: elementi.filter(function (e) {
        return !filter || e.ime.toLowerCase().indexOf(filter.toLowerCase()) >= 0
    })

    function zacni(mape) {
        var v = [{ oznaka: koren.t("nedavno"), vir: { vrsta: "nedavno", pot: "" } },
                 { oznaka: koren.t("smeti"), vir: { vrsta: "smeti", pot: "smeti" } },
                 { naslov: koren.t("mape") }]
        mape.forEach(function (m) { v.push({ oznaka: koren.t(m.vrsta) !== m.vrsta ? koren.t(m.vrsta) : m.ime, vir: { vrsta: "lokalno", pot: m.pot } }) })
        v.push({ naslov: koren.t("naprave") })
        panel.viri = v
        koren.klic("nosilci", [], function (n) {
            var z = panel.viri.slice()
            ;(n || []).forEach(function (x) { z.push({ oznaka: x.ime + (x.ime === x.pot.replace("\\", "") ? "" : " (" + x.pot.replace("\\", "") + ")"), vir: { vrsta: "lokalno", pot: x.pot }, pogon: x }) })
            panel.viri = z
        })
        odpri({ vrsta: "nedavno", pot: "" })
    }
    function odpri(v) { vir = v; filter = ""; poljeFilter.text = ""; nalozi(false) }
    function nalozi(tiho) {
        var st = ++zahteva
        if (!tiho) elementi = []
        var konec = function (r) {
            if (st !== zahteva) return
            if (vir.vrsta === "lokalno") { elementi = (r && r.elementi) || []; stars = (r && r.stars) || "" }
            else if (vir.vrsta === "smeti") { elementi = (r && r.elementi) || []; stars = "" }
            else { elementi = r || []; stars = "" }
        }
        if (vir.vrsta === "lokalno") { koren.klic("mapa", [vir.pot], konec); koren.klic("spremljajMapo", [vir.pot]) }
        else if (vir.vrsta === "smeti") koren.klic("smeti", [], konec)
        else koren.klic("nedavne", [], konec)
    }
    function odpriElement(e) {
        if (vir.vrsta === "smeti") return
        if (e.mapa) odpri({ vrsta: "lokalno", pot: e.pot })
        else koren.klic("odpriDatoteko", [e.pot])
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
        return vir.vrsta === "smeti" ? koren.t("kosPrazen") : vir.vrsta === "nedavno" ? koren.t("niNedavnih") : koren.t("prazno")
    }

    RowLayout {
        anchors.fill: parent; anchors.margins: 14; spacing: 12
        // ---------------- viri
        ListView {
            id: viriSeznam
            Layout.preferredWidth: 170; Layout.fillHeight: true
            clip: true; model: panel.viri; boundsBehavior: Flickable.StopAtBounds
            header: Text { text: koren.t("datoteke"); color: "#eef4ff"; font.pixelSize: 16; font.bold: true; height: 34; leftPadding: 4 }
            delegate: Item {
                width: viriSeznam.width; height: modelData.naslov ? 30 : 32
                Text {
                    visible: !!modelData.naslov; text: (modelData.naslov || "").toUpperCase()
                    color: "#7f93ad"; font.pixelSize: 10; font.letterSpacing: 1; anchors.bottom: parent.bottom; anchors.bottomMargin: 6; x: 6
                }
                Rectangle {
                    visible: !modelData.naslov
                    anchors.fill: parent; anchors.margins: 1; radius: 9
                    readonly property bool izbran: !!modelData.vir && panel.vir.vrsta === modelData.vir.vrsta && panel.vir.pot === modelData.vir.pot
                    color: izbran ? Qt.rgba(0.3, 0.9, 0.73, 0.18) : (mv.containsMouse ? Qt.rgba(1, 1, 1, 0.08) : "transparent")
                    Behavior on color { ColorAnimation { duration: 120 } }
                    Text { text: modelData.oznaka || ""; color: parent.izbran ? "#bff7e6" : "#dbe6f5"; font.pixelSize: 13; elide: Text.ElideRight
                           width: parent.width - 16; x: 10; anchors.verticalCenter: parent.verticalCenter }
                    MouseArea { id: mv; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                onClicked: if (modelData.vir) panel.odpri(modelData.vir) }
                }
            }
        }
        Rectangle { Layout.fillHeight: true; width: 1; color: Qt.rgba(1, 1, 1, 0.08) }
        // ---------------- vsebina
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 8
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                Gumb { besedilo: "↑"; visible: panel.stars !== ""; onKlik: panel.odpri({ vrsta: "lokalno", pot: panel.stars }) }
                Text {
                    Layout.fillWidth: true; color: "#c9d6e8"; font.pixelSize: 12; elide: Text.ElideLeft
                    text: panel.vir.vrsta === "lokalno" ? panel.vir.pot : panel.vir.vrsta === "smeti" ? koren.t("smeti") : koren.t("nedavno")
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
                        placeholderText: koren.t("filter"); placeholderTextColor: "#8fa3bd"; color: "#eef4ff"; font.pixelSize: 12
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
                    Text { text: koren.t("ime"); color: "#7f93ad"; font.pixelSize: 11; width: seznam.width - 190 }
                    Text { text: koren.t("velikost"); color: "#7f93ad"; font.pixelSize: 11; width: 80 }
                    Text { text: koren.t("spremenjeno"); color: "#7f93ad"; font.pixelSize: 11; width: 110 }
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
                            Text { text: modelData.ime; color: "#e6eef9"; font.pixelSize: 13; elide: Text.ElideRight
                                   width: parent.width - 32; anchors.verticalCenter: parent.verticalCenter }
                        }
                        Text { text: modelData.mapa ? "" : koren.velikost(modelData.velikost); color: "#9fb0c6"; font.pixelSize: 12; width: 80 }
                        Text { text: koren.cas(modelData.spremenjeno || modelData.izbrisano); color: "#9fb0c6"; font.pixelSize: 12; width: 110 }
                    }
                    MouseArea {
                        id: md; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton
                        onDoubleClicked: panel.odpriElement(modelData)
                        onClicked: function (m) { if (m.button === Qt.RightButton) { meni.e = modelData; meni.popup() } }
                    }
                }
                Text {
                    anchors.centerIn: parent; visible: seznam.count === 0
                    text: panel.prazno(); color: "#8fa3bd"; font.pixelSize: 13
                }
            }
        }
    }

    Menu {
        id: meni
        property var e: null
        MenuItem { text: koren.t("odpri"); visible: panel.vir.vrsta !== "smeti"; height: visible ? implicitHeight : 0; onTriggered: panel.odpriElement(meni.e) }
        MenuItem { text: koren.t("pokazi"); visible: panel.vir.vrsta !== "smeti"; height: visible ? implicitHeight : 0; onTriggered: koren.klic("pokaziVMapi", [meni.e.pot]) }
        MenuItem { text: koren.t("preimenuj"); visible: panel.vir.vrsta === "lokalno"; height: visible ? implicitHeight : 0; onTriggered: preimenovanje.zacni(meni.e) }
        MenuItem { text: koren.t("vKos"); visible: panel.vir.vrsta !== "smeti"; height: visible ? implicitHeight : 0; onTriggered: panel.vKos(meni.e) }
        MenuItem { text: koren.t("obnovi"); visible: panel.vir.vrsta === "smeti"; height: visible ? implicitHeight : 0
                   onTriggered: koren.klic("obnoviIzSmeti", [meni.e.id], function (r) { if (r && r.ok) panel.nalozi(true); else koren.obvesti(koren.t("niUspelo")) }) }
    }

    Popup {
        id: preimenovanje
        property var e: null
        anchors.centerIn: parent; modal: true; padding: 18; width: 380
        background: Rectangle { radius: 16; color: "#121b2a"; border.color: Qt.rgba(1, 1, 1, 0.14) }
        function zacni(e) { preimenovanje.e = e; novoIme.text = e.ime; open(); novoIme.forceActiveFocus(); novoIme.selectAll() }
        function shrani() {
            koren.klic("preimenujDatoteko", [preimenovanje.e.pot, novoIme.text], function (r) {
                if (r && r.ok) panel.nalozi(true); else koren.obvesti(koren.t("niUspelo"))
            })
            close()
        }
        ColumnLayout {
            anchors.fill: parent; spacing: 12
            Text { text: koren.t("preimenuj"); color: "#eef4ff"; font.pixelSize: 15; font.bold: true }
            TextField { id: novoIme; Layout.fillWidth: true; color: "#eef4ff"; font.pixelSize: 14
                        background: Rectangle { radius: 8; color: Qt.rgba(1, 1, 1, 0.08); border.color: "#4de6ba" }
                        Keys.onReturnPressed: preimenovanje.shrani() }
            RowLayout { Layout.alignment: Qt.AlignRight; spacing: 8
                Gumb { besedilo: koren.t("preklici"); onKlik: preimenovanje.close() }
                Gumb { besedilo: koren.t("shrani"); poudarjen: true; onKlik: preimenovanje.shrani() } }
        }
    }

    Popup {
        id: potrdi
        anchors.centerIn: parent; modal: true; padding: 18; width: 400
        background: Rectangle { radius: 16; color: "#121b2a"; border.color: Qt.rgba(1, 1, 1, 0.14) }
        ColumnLayout {
            anchors.fill: parent; spacing: 14
            Text { text: koren.t("izprazniVpr"); color: "#eef4ff"; font.pixelSize: 14; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            RowLayout { Layout.alignment: Qt.AlignRight; spacing: 8
                Gumb { besedilo: koren.t("preklici"); onKlik: potrdi.close() }
                Gumb { besedilo: koren.t("izprazni"); poudarjen: true
                       onKlik: { koren.klic("izprazniSmeti", [], function () { panel.nalozi(true) }); potrdi.close() } } }
        }
    }
}
