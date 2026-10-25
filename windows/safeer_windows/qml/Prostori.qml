// Prostori (Safeer Link Spaces, MVP - kot Linux): ta racunalnik, navidezna namizja Windows in zasloni povezanih naprav v
// enem preklopniku na namizju. Odpre ga gumb »Prostori« pod iskanjem ali sistemska bliznjica Ctrl+Win+Tab (os_app).
// Puscice izberejo, Enter odpre, Esc zapre. Podatki in odpiranje: os_app._prostori / _prostor_odpri (core/link_prostori.py),
// besedila iz assets/os/besedila.js (namizje_qml.besedila_prostorov) - ista kot v oknu Safeer OS.
import QtQuick
import QtQuick.Controls.Basic

Item {
    id: pr
    visible: opacity > 0
    opacity: 0
    Behavior on opacity { NumberAnimation { duration: 160 } }
    property var besedila: ({})
    property var seznam: []
    property var namizja: []
    property int izbran: 0
    property string stanje: ""
    property string odpira: ""
    property bool nalozeno: false
    readonly property var ploscice: {
        var z = namizja.length > 1
            ? namizja.map(function (n) { return { namizje: true, indeks: n.indeks, ime: n.ime, ta: !!n.trenutno, id: "namizje:" + n.indeks } })
            : [{ ta: true, id: "" }]
        return z.concat(seznam).concat([{ dodaj: true, id: "+" }])
    }
    function tp(k, vr) {
        var s = besedila[k] || k
        if (vr) for (var x in vr) s = s.replace("{" + x + "}", vr[x])
        return s
    }
    function ime(p) { return p.namizje ? p.ime : (p.ta ? koren.t("taRacunalnik") : (p.dodaj ? tp("prostorDodaj") : (p.ime || p.id))) }
    function pod(p) {
        if (p.namizje) return p.ta ? tp("prostorTaPod") : tp("prostorNamizjeWindows")
        if (p.ta) return tp("prostorTaPod")
        if (p.dodaj) return tp("prostorDodajPod")
        return p.povezana ? tp("prostorPovezana") : tp("prostorNiPovezana")
    }
    function znak(p) {
        if (p.dodaj) return "+"
        if (p.ta || p.namizje || p.vrsta === "racunalnik") return "🖥"
        return p.vrsta === "tv" ? "📺" : (p.vrsta === "tablica" ? "▭" : "📱")
    }
    function odpri(smer) {
        if (opacity > 0) { premakni(smer || 1); return }
        opacity = 1
        izbran = nalozeno && smer > 0 ? Math.min(1, ploscice.length - 1) : 0
        stanje = nalozeno ? "" : tp("prostoriIscem")
        trak.forceActiveFocus()
        nalozi()
        zanka.start()
    }
    function zapri() { opacity = 0; zanka.stop(); odpira = "" }
    function premakni(smer) { var n = ploscice.length; izbran = ((izbran + smer) % n + n) % n }
    function nalozi() {
        koren.klic("prostori", [], function (r) {
            var izbranId = (ploscice[izbran] || {}).id
            pr.nalozeno = true
            pr.seznam = (r && r.prostori) || []
            pr.namizja = (r && r.namizja) || []
            if (r && r.koda === "ni_povezave") pr.stanje = tp("prostorNiLinka")
            else if (pr.stanje === tp("prostoriIscem") || pr.stanje === tp("prostorNiLinka")) pr.stanje = pr.seznam.length ? "" : tp("prostoriPrazno")
            var i = ploscice.map(function (p) { return p.id }).indexOf(izbranId)
            if (i >= 0) pr.izbran = i
        }, function () { pr.stanje = koren.t("niUspelo") })
    }
    function izberi(p) {
        if (p.namizje) { zapri(); if (!p.ta) koren.klic("namizjeWindows", [p.indeks]); return }
        if (p.ta) { zapri(); return }
        if (p.dodaj) { zapri(); koren.klic("novaNaprava", []); return }
        if (!p.povezana) { stanje = tp("prostorBrezPovezave", { ime: ime(p) }); return }
        if (odpira) return
        odpira = p.id
        stanje = tp("prostorOdpiram", { ime: ime(p) })
        koren.klic("prostorOdpri", [p.id], function (r) {
            pr.odpira = ""
            if (!r || !r.ok) {
                pr.stanje = r && r.koda === "ni_prostora" ? tp("prostorNiVec", { ime: ime(p) })
                          : (r && r.koda === "ni_povezave" ? tp("prostorNiLinka") : ((r && r.message) || koren.t("niUspelo")))
                return
            }
            pr.zapri()
            koren.obvesti(r.nacin === "zaslon" ? tp("prostorPotrdi", { ime: ime(p) }) : tp("prostorOdpiram", { ime: ime(p) }))
        }, function () { pr.odpira = ""; pr.stanje = koren.t("niUspelo") })
    }
    Timer { id: zanka; interval: 5000; repeat: true; onTriggered: pr.nalozi() }

    Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0, 0, 0.35)
        MouseArea { anchors.fill: parent; onClicked: pr.zapri() } }

    Rectangle {
        id: okvir
        anchors.horizontalCenter: parent.horizontalCenter
        y: 24
        width: Math.min(1120, parent.width - 48); height: vsebina.implicitHeight + 36
        radius: 22
        color: koren.plosca(0.96); border.color: Qt.rgba(1, 1, 1, 0.14)
        MouseArea { anchors.fill: parent }
        Column {
            id: vsebina
            x: 20; y: 18; width: okvir.width - 40; spacing: 10
            Row {
                width: parent.width
                Text { text: pr.tp("prostori"); color: koren.paleta.besedilo; font.pixelSize: 20; font.bold: true; width: parent.width - 40 }
                Gumb { besedilo: "✕"; onKlik: pr.zapri(); Accessible.name: koren.t("zapri") }
            }
            Text { text: pr.tp("prostoriPod"); color: koren.paleta.medlo; font.pixelSize: 12; wrapMode: Text.WordWrap; width: parent.width }
            ListView {
                id: trak
                width: parent.width; height: 168
                orientation: ListView.Horizontal; spacing: 14; clip: true
                model: pr.ploscice; currentIndex: pr.izbran
                boundsBehavior: Flickable.StopAtBounds
                focus: true
                Keys.onLeftPressed: pr.premakni(-1)
                Keys.onRightPressed: pr.premakni(1)
                Keys.onUpPressed: pr.premakni(-1)
                Keys.onDownPressed: pr.premakni(1)
                Keys.onReturnPressed: pr.izberi(pr.ploscice[pr.izbran])
                Keys.onEnterPressed: pr.izberi(pr.ploscice[pr.izbran])
                Keys.onEscapePressed: pr.zapri()
                Keys.onTabPressed: pr.premakni(1)
                delegate: Rectangle {
                    width: 196; height: 160; radius: 16
                    readonly property bool izbran: index === pr.izbran
                    color: izbran || mp.containsMouse ? koren.poudarekA(0.16) : Qt.rgba(1, 1, 1, 0.05)
                    border.width: 2
                    border.color: izbran ? koren.paleta.poudarek : Qt.rgba(1, 1, 1, 0.10)
                    opacity: !modelData.ta && !modelData.dodaj && !modelData.namizje && !modelData.povezana ? 0.6 : 1
                    Rectangle {
                        id: slicica
                        x: 8; y: 8; width: parent.width - 16; height: 100; radius: 10; clip: true
                        color: Qt.rgba(1, 1, 1, 0.06)
                        border.color: modelData.dodaj ? Qt.rgba(1, 1, 1, 0.3) : "transparent"
                        Image { anchors.fill: parent; visible: !!(modelData.ta || modelData.namizje); source: visible ? koren.ozadjeUrl : ""
                                fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize.width: 360 }
                        Text { anchors.centerIn: parent; text: pr.znak(modelData); font.pixelSize: 34; color: koren.paleta.besedilo
                               style: Text.Outline; styleColor: "#60000000" }
                        Rectangle { anchors.fill: parent; radius: 10; color: "transparent"; border.width: pr.odpira === modelData.id ? 2 : 0
                                    border.color: koren.paleta.poudarek }
                    }
                    Column {
                        x: 12; anchors.top: slicica.bottom; anchors.topMargin: 6; width: parent.width - 24; spacing: 2
                        Text { text: pr.ime(modelData); color: koren.paleta.besedilo; font.pixelSize: 14; font.bold: true; elide: Text.ElideRight; width: parent.width }
                        Row {
                            spacing: 6
                            Rectangle { width: 8; height: 8; radius: 4; anchors.verticalCenter: parent.verticalCenter
                                        visible: !modelData.ta && !modelData.dodaj && !modelData.namizje
                                        color: modelData.povezana ? (koren.paleta.ok || "#7fe0b6") : "#6b7780" }
                            Text { text: pr.pod(modelData); color: koren.paleta.medlo; font.pixelSize: 12; elide: Text.ElideRight; width: 160 }
                        }
                    }
                    MouseArea { id: mp; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                onClicked: { pr.izbran = index; pr.izberi(modelData) } }
                    Accessible.role: Accessible.Button
                    Accessible.name: pr.ime(modelData) + ", " + pr.pod(modelData)
                }
            }
            Text { text: pr.stanje; visible: text !== ""; color: koren.paleta.medlo; font.pixelSize: 12; wrapMode: Text.WordWrap; width: parent.width }
        }
    }
}
