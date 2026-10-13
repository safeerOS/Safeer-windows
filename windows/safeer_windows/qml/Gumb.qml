import QtQuick

Rectangle {
    id: gumb
    property string besedilo: ""
    property bool poudarjen: false
    signal klik()
    height: 30; width: napis.implicitWidth + 26; radius: 15
    color: poudarjen ? (m.containsMouse ? Qt.lighter(koren.paleta.poudarek, 1.12) : koren.paleta.poudarek)
                     : (m.pressed ? Qt.rgba(1, 1, 1, 0.22) : m.containsMouse ? Qt.rgba(1, 1, 1, 0.16) : Qt.rgba(1, 1, 1, 0.08))
    border.color: poudarjen ? "transparent" : Qt.rgba(1, 1, 1, 0.14)
    scale: m.pressed ? 0.96 : 1
    Behavior on color { ColorAnimation { duration: 140 } }
    Behavior on scale { NumberAnimation { duration: 90 } }
    Text {
        id: napis; anchors.centerIn: parent; text: gumb.besedilo
        color: gumb.poudarjen ? koren.paleta.poudarekTemna : koren.paleta.besedilo; font.pixelSize: 12; font.bold: gumb.poudarjen
    }
    MouseArea { id: m; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: gumb.klik() }
}
