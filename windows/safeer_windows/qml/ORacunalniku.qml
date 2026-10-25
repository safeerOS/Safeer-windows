// O tem računalniku (lastnik, 25. 10. 2026: »podatkov o prostoru na disku nisi vgradil, niti podatkov o strojni in
// programski opremi«): strojna in programska oprema ter diski s prostim prostorom, na namizju - brez iskanja po
// Nastavitvah. Podatki so iz core/sistem_podatki.py (isti modul kot na Linuxu); nič ne zapusti računalnika.
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "datoteke_logika.js" as L

Item {
    id: okno
    visible: opacity > 0
    opacity: 0
    Behavior on opacity { NumberAnimation { duration: 180 } }
    property var p: null
    property bool nalagam: false
    function odpri() {
        opacity = 1; forceActiveFocus()
        nalagam = p === null
        koren.klic("sistemPodatki", [], function (r) { okno.p = r || {}; okno.nalagam = false },
                   function () { okno.nalagam = false })
    }
    function zapri() { opacity = 0 }
    Keys.onEscapePressed: zapri()

    function cas(s) {
        var ure = Math.floor((s || 0) / 3600)
        return ure >= 24 ? koren.t("racDni", { d: Math.floor(ure / 24), h: ure % 24 })
             : ure >= 1 ? koren.t("racUr", { h: ure }) : koren.t("racMin", { m: Math.floor((s || 0) / 60) })
    }
    readonly property var vrstice: {
        if (!p) return []
        var v = [], ram = p.pomnilnik || {}
        function dodaj(k, x) { if (x) v.push({ k: koren.t(k), v: String(x) }) }
        dodaj("racRacunalnik", p.racunalnik)
        dodaj("racSistem", (p.sistem || "") + (p.arhitektura ? " (" + p.arhitektura + ")" : ""))
        dodaj("racJedro", p.jedro)
        dodaj("racProcesor", p.procesor ? p.procesor + (p.jeder ? " · " + koren.t("racJeder", { n: p.jeder }) : "") : "")
        dodaj("racPomnilnik", ram.skupaj ? koren.t("racPomnilnikVr", { skupaj: koren.velikost(ram.skupaj), prosto: koren.velikost(ram.na_voljo || 0) }) : "")
        dodaj("racGraficna", (p.graficne || []).join(", "))
        dodaj("racCas", p.cas_delovanja_s ? cas(p.cas_delovanja_s) : "")
        dodaj("racSafeer", koren.razlicica)
        return v
    }

    Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0, 0, 0.35)
        MouseArea { anchors.fill: parent; onClicked: okno.zapri() } }

    Rectangle {
        id: okvir
        width: Math.min(640, parent.width - 80); height: Math.min(parent.height - 80, vsebina.implicitHeight + 48)
        anchors.centerIn: parent
        radius: 22
        color: koren.plosca(0.96); border.color: Qt.rgba(1, 1, 1, 0.14)
        MouseArea { anchors.fill: parent }        // klik v oknu ga ne zapre
        Flickable {
            anchors.fill: parent; anchors.margins: 24
            contentHeight: vsebina.implicitHeight; clip: true; boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            Column {
                id: vsebina
                width: parent.width; spacing: 14
                Row {
                    spacing: 14
                    Rectangle {
                        width: 46; height: 46; radius: 12
                        gradient: Gradient { GradientStop { position: 0; color: "#2f6bff" } GradientStop { position: 1; color: "#7a4dff" } }
                        Text { anchors.centerIn: parent; text: "🖥"; font.pixelSize: 22; color: "white" }
                    }
                    Column {
                        anchors.verticalCenter: parent.verticalCenter; spacing: 2
                        Text { text: koren.t("oRacunalniku"); color: koren.paleta.besedilo; font.pixelSize: 20; font.bold: true }
                        Text { text: okno.p ? (okno.p.sistem || "") : koren.t("nalagam"); color: koren.paleta.medlo; font.pixelSize: 12 }
                    }
                }
                // Strojna in programska oprema
                Rectangle {
                    width: parent.width; height: mrezaPodatkov.implicitHeight + 24; radius: 14; color: Qt.rgba(1, 1, 1, 0.05)
                    visible: okno.vrstice.length > 0
                    GridLayout {
                        id: mrezaPodatkov
                        x: 14; y: 12; width: parent.width - 28; columns: 2; columnSpacing: 18; rowSpacing: 8
                        Repeater {
                            model: okno.vrstice
                            delegate: Text { text: modelData.k; color: koren.paleta.medlo; font.pixelSize: 12
                                             Layout.row: index; Layout.column: 0; Layout.alignment: Qt.AlignTop }
                        }
                        Repeater {
                            model: okno.vrstice
                            delegate: Text { text: modelData.v; color: koren.paleta.besedilo; font.pixelSize: 13; wrapMode: Text.WordWrap
                                             Layout.row: index; Layout.column: 1; Layout.fillWidth: true }
                        }
                    }
                }
                // Diski s prostim prostorom
                Text { text: koren.t("diski"); color: koren.paleta.besedilo; font.pixelSize: 15; font.bold: true
                       visible: !!okno.p && (okno.p.diski || []).length > 0 }
                Repeater {
                    model: okno.p ? (okno.p.diski || []) : []
                    delegate: Rectangle {
                        width: vsebina.width; height: 62; radius: 14; color: md.containsMouse ? Qt.rgba(1, 1, 1, 0.09) : Qt.rgba(1, 1, 1, 0.05)
                        Column {
                            x: 14; width: parent.width - 28; anchors.verticalCenter: parent.verticalCenter; spacing: 6
                            RowLayout {
                                width: parent.width
                                Text { text: L.imeDiska(modelData, koren.t("diskSistem")); color: koren.paleta.besedilo; font.pixelSize: 13; font.bold: true
                                       Layout.fillWidth: true; elide: Text.ElideRight }
                                Text { text: koren.t("diskProsto", { prosto: koren.velikost(modelData.prosto || 0), skupaj: koren.velikost(modelData.velikost) })
                                       color: modelData.malo_prostora ? "#fca5a5" : koren.paleta.medlo; font.pixelSize: 12 }
                            }
                            Rectangle {
                                width: parent.width; height: 8; radius: 4; color: Qt.rgba(1, 1, 1, 0.12)
                                Rectangle { height: parent.height; radius: 4; width: parent.width * L.zasedeno(modelData)
                                            color: modelData.malo_prostora ? "#f87171" : koren.paleta.poudarek }
                            }
                        }
                        MouseArea { id: md; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                    onClicked: { okno.zapri(); koren.pokaziMapo(modelData.pot) } }
                    }
                }
                Row {
                    spacing: 10; anchors.right: parent.right
                    Gumb { besedilo: koren.t("vseNastavitve"); onKlik: { okno.zapri(); koren.klic("odpriRazdelek", ["nastavitve"]) } }
                    Gumb { besedilo: koren.t("zapri"); poudarjen: true; onKlik: okno.zapri() }
                }
            }
        }
    }
}
