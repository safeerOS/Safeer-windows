// Ikona povecevalnega stekla (risana, neodvisna od pisave).
import QtQuick

Item {
    property color barva: "#c1d0e2"
    width: 20; height: 20
    Rectangle { x: 1; y: 1; width: 13; height: 13; radius: 7; color: "transparent"; border.color: parent.barva; border.width: 2 }
    Rectangle { x: 12; y: 13; width: 8; height: 2.4; radius: 1.2; color: parent.barva; rotation: 45; transformOrigin: Item.Left }
}
