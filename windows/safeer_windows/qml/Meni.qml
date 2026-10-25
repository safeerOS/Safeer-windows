// Meni namizja: zaobljen, barve iz palete (tema sistema), kot meni desnega klika na ozadje.
import QtQuick
import QtQuick.Controls.Basic

Menu {
    padding: 6
    background: Rectangle { implicitWidth: 230; radius: 12; color: koren.paleta.vnos; border.color: Qt.rgba(1, 1, 1, 0.14) }
}
