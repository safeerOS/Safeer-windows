// Prosojen panel: zamegljeno ozadje namizja pod panelom (ena zameglitev za vse panele), temna prosojna plast in rob.
import QtQuick
import QtQuick.Effects

Item {
    id: steklo
    property Item zamegljeno            // MultiEffect z zameglitvijo celotnega ozadja
    property real polmer: 18
    property color barva: Qt.rgba(0.05, 0.08, 0.13, 0.55)
    default property alias vsebina: notranje.data

    Item {
        id: vzorec
        anchors.fill: parent
        visible: false
        layer.enabled: true
        ShaderEffectSource {
            anchors.fill: parent
            sourceItem: steklo.zamegljeno
            hideSource: true
            live: true
            sourceRect: {
                if (!steklo.zamegljeno) return Qt.rect(0, 0, 0, 0)
                var p = steklo.mapToItem(steklo.zamegljeno, 0, 0)
                return Qt.rect(p.x, p.y, steklo.width, steklo.height)
            }
        }
    }
    Rectangle {
        id: maska
        anchors.fill: parent
        radius: steklo.polmer
        visible: false
        layer.enabled: true
    }
    MultiEffect {
        anchors.fill: parent
        source: vzorec
        maskEnabled: true
        maskSource: maska
        visible: steklo.zamegljeno !== null
    }
    Rectangle {
        anchors.fill: parent
        radius: steklo.polmer
        color: steklo.barva
        border.color: Qt.rgba(1, 1, 1, 0.10)
        border.width: 1
    }
    Item {
        id: notranje
        anchors.fill: parent
    }
}
