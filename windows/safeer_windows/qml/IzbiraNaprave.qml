// Izbira naprave za panel (Programi ali Datoteke): privzeto ta racunalnik, sicer katerakoli naprava v Safeer Linku,
// ki to zna (zmoznost: "programi" ali "datoteke"). Ob izbiri se sprozi izbrana(id, ime).
import QtQuick
import QtQuick.Controls.Basic

ComboBox {
    id: izbira
    property string zmoznost: "programi"
    property var naprave: []
    signal izbrana(string id, string ime)
    readonly property var moznosti: [{ id: "", ime: koren.t("taRacunalnik") }].concat(
        naprave.filter(function (n) { return !!n[zmoznost] }).map(function (n) { return { id: n[zmoznost], ime: n.ime } }))
    model: moznosti
    textRole: "ime"
    implicitWidth: 190; implicitHeight: 32
    font.pixelSize: 12
    onActivated: function (i) { izbira.izbrana(moznosti[i].id, moznosti[i].ime) }
    background: Rectangle {
        radius: 16; color: izbira.hovered ? Qt.rgba(1, 1, 1, 0.14) : Qt.rgba(1, 1, 1, 0.08)
        border.color: izbira.currentIndex > 0 ? koren.paleta.poudarek : Qt.rgba(1, 1, 1, 0.14)
        Behavior on color { ColorAnimation { duration: 120 } }
    }
    contentItem: Row {
        leftPadding: 12; spacing: 8
        Rectangle { width: 7; height: 7; radius: 4; anchors.verticalCenter: parent.verticalCenter
                    color: izbira.currentIndex > 0 ? koren.paleta.poudarek : koren.paleta.medlo }
        Text { text: izbira.displayText; color: koren.paleta.besedilo; font: izbira.font; elide: Text.ElideRight
               width: izbira.width - 50; anchors.verticalCenter: parent.verticalCenter }
    }
    indicator: Text { text: "▾"; color: koren.paleta.medlo; x: izbira.width - 22; anchors.verticalCenter: parent.verticalCenter }
    delegate: ItemDelegate {
        width: izbira.width
        contentItem: Text { text: modelData.ime; color: koren.paleta.besedilo; font.pixelSize: 12; elide: Text.ElideRight }
        background: Rectangle { radius: 8; color: parent.highlighted ? koren.poudarekA(0.22) : "transparent" }
        highlighted: izbira.highlightedIndex === index
    }
    popup.background: Rectangle { radius: 12; color: koren.paleta.vnos; border.color: Qt.rgba(1, 1, 1, 0.14) }
}
