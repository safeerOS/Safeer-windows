// Prilagodi namizje: ozadje (Safeer, Windows ali lastna slika), zameglitev in prekrivnost plosc. Barve so iz teme sistema.
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs

Item {
    id: prilagodi
    visible: opacity > 0
    opacity: 0
    Behavior on opacity { NumberAnimation { duration: 180 } }
    function odpri() { opacity = 1; koren.klic("videzNamizja", [], function (v) { koren.uporabiVidez(v) }) }
    function zapri() { opacity = 0 }
    function nastavi(sprememba) { koren.klic("nastaviVidezNamizja", [sprememba], function (v) { koren.uporabiVidez(v) }) }

    Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0, 0, 0.35)
        MouseArea { anchors.fill: parent; onClicked: prilagodi.zapri() } }

    Rectangle {
        id: okvir
        width: Math.min(720, parent.width - 80); height: vsebina.implicitHeight + 48
        anchors.centerIn: parent
        radius: 22
        color: koren.plosca(0.96); border.color: Qt.rgba(1, 1, 1, 0.14)
        MouseArea { anchors.fill: parent }        // klik v oknu ga ne zapre
        Column {
            id: vsebina
            x: 24; y: 24; width: okvir.width - 48; spacing: 16
            Text { text: koren.t("prilagodi").replace(" …", ""); color: koren.paleta.besedilo; font.pixelSize: 20; font.bold: true }
            Text { text: koren.t("ozadje"); color: koren.paleta.medlo; font.pixelSize: 13 }
            Flow {
                width: parent.width; spacing: 12
                Repeater {
                    model: (koren.videz.ozadja || []).concat(koren.videz.windows ? [{ kljuc: "windows", ime: koren.t("ozadjeWindows"), url: koren.videz.windows }] : [])
                                                     .concat(koren.videz.lastna ? [{ kljuc: koren.videz.lastna, ime: koren.t("lastnaSlika").replace(" …", ""), url: "file:///" + koren.videz.lastna.replace(/\\/g, "/") }] : [])
                    delegate: Item {
                        width: 152; height: 112
                        property bool izbrano: koren.videz.izbira === modelData.kljuc
                        Rectangle {
                            id: slicica; width: 152; height: 86; radius: 12; clip: true
                            color: koren.paleta.vnos
                            border.width: parent.izbrano ? 3 : 1
                            border.color: parent.izbrano ? koren.paleta.poudarek : (mo.containsMouse ? Qt.rgba(1, 1, 1, 0.4) : Qt.rgba(1, 1, 1, 0.14))
                            Image { anchors.fill: parent; anchors.margins: parent.border.width; source: modelData.url
                                    fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize.width: 320 }
                            MouseArea { id: mo; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                        onClicked: prilagodi.nastavi({ ozadje: modelData.kljuc }) }
                        }
                        Text { anchors.top: slicica.bottom; anchors.topMargin: 6; width: 152; elide: Text.ElideRight
                               horizontalAlignment: Text.AlignHCenter; text: modelData.ime; font.pixelSize: 12
                               color: parent.izbrano ? koren.paleta.poudarek : koren.paleta.besedilo }
                    }
                }
                Item {
                    width: 152; height: 112
                    Rectangle {
                        width: 152; height: 86; radius: 12; color: "transparent"
                        border.color: ml.containsMouse ? koren.paleta.poudarek : Qt.rgba(1, 1, 1, 0.22); border.width: 1
                        Text { anchors.centerIn: parent; text: "+"; color: koren.paleta.besedilo; font.pixelSize: 30 }
                        MouseArea { id: ml; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                    onClicked: izbiraSlike.open() }
                    }
                    Text { y: 92; width: 152; horizontalAlignment: Text.AlignHCenter; text: koren.t("lastnaSlika")
                           color: koren.paleta.besedilo; font.pixelSize: 12 }
                }
            }
            Row {
                spacing: 14; width: parent.width
                Text { text: koren.t("zameglitevNapis"); color: koren.paleta.besedilo; font.pixelSize: 13; width: 170; anchors.verticalCenter: parent.verticalCenter }
                Slider { id: dZam; width: parent.width - 190; from: 0; to: 1; value: koren.zameglitev
                         onMoved: koren.zameglitev = value; onPressedChanged: if (!pressed) prilagodi.nastavi({ zameglitev: value }) }
            }
            Row {
                spacing: 14; width: parent.width
                Text { text: koren.t("prosojnostNapis"); color: koren.paleta.besedilo; font.pixelSize: 13; width: 170; anchors.verticalCenter: parent.verticalCenter }
                Slider { id: dPro; width: parent.width - 190; from: 0.2; to: 0.9; value: koren.prosojnost
                         onMoved: koren.prosojnost = value; onPressedChanged: if (!pressed) prilagodi.nastavi({ prosojnost: value }) }
            }
            Text { width: parent.width; wrapMode: Text.WordWrap; text: koren.t("temaOpis"); color: koren.paleta.medlo; font.pixelSize: 12 }
            Row {
                spacing: 10; anchors.right: parent.right
                Gumb { besedilo: koren.t("temaSistema"); onKlik: { prilagodi.zapri(); koren.klic("odpriRazdelek", ["nastavitve"]) } }
                Gumb { besedilo: koren.t("privzeto"); onKlik: prilagodi.nastavi({ privzeto: true }) }
                Gumb { besedilo: koren.t("zapri"); poudarjen: true; onKlik: prilagodi.zapri() }
            }
        }
    }
    FileDialog {
        id: izbiraSlike
        nameFilters: ["Slike (*.jpg *.jpeg *.png *.webp *.bmp)"]
        onAccepted: {
            var pot = decodeURIComponent(String(selectedFile).replace(/^file:\/\/\//, ""))
            prilagodi.nastavi({ ozadje: pot.replace(/\//g, "\\") })
        }
    }
}
