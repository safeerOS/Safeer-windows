// Vnos v meniju namizja (isti videz kot meni desnega klika): barve iz palete, kljukica pri izbrani moznosti.
import QtQuick
import QtQuick.Controls.Basic

MenuItem {
    id: vnos
    property bool izbran: false
    height: visible ? implicitHeight : 0
    contentItem: Text {
        text: (vnos.izbran ? "✓  " : "") + vnos.text
        color: vnos.enabled ? koren.paleta.besedilo : koren.paleta.medlo
        font.pixelSize: 13; leftPadding: vnos.izbran ? 6 : 22; elide: Text.ElideRight
    }
    background: Rectangle { implicitWidth: 220; radius: 8; color: vnos.highlighted ? koren.poudarekA(0.22) : "transparent" }
}
