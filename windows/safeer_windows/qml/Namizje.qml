// Namizje Safeer OS za Windows (Qt Quick). Ista dela kot na Linuxu: iskanje, Medijski center, datoteke, programi,
// Safeer Link. Podatki pridejo iz Pythona prek »Most« (iste metode kot spletna stran na Linuxu).
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Effects
import QtQuick.Layouts

Item {
    id: koren
    width: 1440; height: 860

    // ------------------------------------------------------------------ most in besedila
    property var cakajo: ({})
    function klic(metoda, argumenti, ok, napaka) {
        var id = Most.klic(metoda, JSON.stringify(argumenti || []))
        cakajo[id] = { ok: ok, napaka: napaka }
    }
    Connections {
        target: Most
        function onOdgovor(id, uspeh, podatki) {
            var c = koren.cakajo[id]; if (!c) return
            delete koren.cakajo[id]
            var v = null
            try { v = JSON.parse(podatki) } catch (e) {}
            if (uspeh && c.ok) c.ok(v)
            else if (!uspeh && c.napaka) c.napaka(v)
        }
        function onDogodek(vrsta, podatki) {
            var p = null
            try { p = JSON.parse(podatki) } catch (e) {}
            if (vrsta === "datoteke" && p && p.pot === datoteke.vir.pot) datoteke.nalozi(true)
            if (vrsta === "videz" && p) koren.uporabiVidez(p)
            if (vrsta === "iskanjeOdDrugod" && p && p.q) { polje.text = p.q; polje.forceActiveFocus() }
        }
    }
    property string jezik: "sl"
    // Tema sistema (Nastavitve Safeer OS) in videz namizja (Prilagodi namizje) - en videz z vmesnikom, Spletom in Controlom.
    property var paleta: ({ poudarek: "#54d6a5", poudarekTemna: "#06231a", besedilo: "#f0f4f3", medlo: "#b0bdc4",
                            vnos: "#111b27", karticaRgb: [0.067, 0.098, 0.141], poudarekRgb: [0.329, 0.839, 0.647] })
    property real zameglitev: 1.0
    property real prosojnost: 0.55
    property var videz: ({})
    function plosca(a) { var c = paleta.karticaRgb || [0.067, 0.098, 0.141]; return Qt.rgba(c[0], c[1], c[2], a) }
    function poudarekA(a) { var c = paleta.poudarekRgb || [0.329, 0.839, 0.647]; return Qt.rgba(c[0], c[1], c[2], a) }
    function uporabiVidez(v) {
        if (!v) return
        koren.videz = v
        if (v.paleta) koren.paleta = v.paleta
        if (v.ozadje !== undefined) koren.ozadjeUrl = v.ozadje || ""
        if (v.zameglitev !== undefined) koren.zameglitev = v.zameglitev
        if (v.prosojnost !== undefined) koren.prosojnost = v.prosojnost
    }
    readonly property var besedila: ({
        sl: { isci: "Išči po programih, datotekah in spletu …", splet: "Išči na spletu", programi: "Programi",
              isciProg: "Išči programe …", vse: "Vse", datoteke: "Datoteke", nedavno: "Nedavno", smeti: "Koš",
              mape: "Mape", naprave: "Naprave", filter: "Filtriraj …", ime: "Ime", velikost: "Velikost",
              spremenjeno: "Spremenjeno", prazno: "Mapa je prazna.", niNedavnih: "Še ni nedavnih datotek.",
              kosPrazen: "Koš je prazen.", odpri: "Odpri", pokazi: "Pokaži v mapi", preimenuj: "Preimenuj",
              vKos: "V Koš", obnovi: "Obnovi", izprazni: "Izprazni Koš", izprazniVpr: "Izprazni Koš? Datotek ne bo mogoče obnoviti.",
              preklici: "Prekliči", razveljavi: "Razveljavi", vKosPoslano: "»{ime}« je v Košu.", novaMapa: "Nova mapa",
              niUspelo: "Ni uspelo.", medijski: "Medijski center", niPredvajanja: "Ni predvajanja",
              medijOpis: "Glasba, radio, filmi in serije iz tvojih virov.", odpriMedijski: "Odpri Medijski center",
              link: "Safeer Link", napravN: "{n} naprav", nastavitve: "Nastavitve", taRacunalnik: "Ta računalnik",
              HOME: "Domača mapa", DESKTOP: "Namizje", DOCUMENTS: "Dokumenti", DOWNLOAD: "Prenosi",
              PICTURES: "Fotografije", MUSIC: "Glasba", VIDEOS: "Videi", gor: "Navzgor", shrani: "Shrani",
              nalagam: "Nalagam …", niOdgovorila: "Naprava ni odgovorila.", neDeli: "Naprava ne deli datotek.",
              odpiramZ: "Odpiram {ime} z naprave {naprava} …", zazeniNa: "Zaženi na napravi", odpriNaNapravi: "Odpri na napravi",
              prenasam: "Prenašam {ime} …", mapeNaprave: "Mape naprave", brezProgramov: "Na napravi ni programov.",
              niLocenega: "Naprava nima ločenega zaslona – odpreš lahko samo, kar ne moti njenega uporabnika.",
              oddaljeno: "Oddaljeno namizje", odpriSProgramom: "Odpri s programom naprave {naprava}",
              prilagodi: "Prilagodi namizje …", temaSistema: "Tema in nastavitve sistema …", ozadje: "Ozadje",
              ozadjeWindows: "Ozadje Windows", lastnaSlika: "Lastna slika …", zameglitevNapis: "Zameglitev plošč",
              prosojnostNapis: "Prekrivnost plošč", privzeto: "Privzeto", zapri: "Zapri",
              temaOpis: "Barve so iz teme sistema (Nastavitve Safeer OS › Videz) – enake v Spletu in Safeer Controlu." },
        en: { isci: "Search apps, files and the web …", splet: "Search the web", programi: "Apps",
              isciProg: "Find an app …", vse: "All", datoteke: "Files", nedavno: "Recent", smeti: "Recycle Bin",
              mape: "Folders", naprave: "Devices", filter: "Filter …", ime: "Name", velikost: "Size",
              spremenjeno: "Modified", prazno: "This folder is empty.", niNedavnih: "No recent files yet.",
              kosPrazen: "The Recycle Bin is empty.", odpri: "Open", pokazi: "Show in folder", preimenuj: "Rename",
              vKos: "Move to Recycle Bin", obnovi: "Restore", izprazni: "Empty Recycle Bin", izprazniVpr: "Empty the Recycle Bin? Files can't be restored.",
              preklici: "Cancel", razveljavi: "Undo", vKosPoslano: "“{ime}” is in the Recycle Bin.", novaMapa: "New folder",
              niUspelo: "That didn't work.", medijski: "Media centre", niPredvajanja: "Nothing playing",
              medijOpis: "Music, radio, films and series from your sources.", odpriMedijski: "Open Media centre",
              link: "Safeer Link", napravN: "{n} devices", nastavitve: "Settings", taRacunalnik: "This PC",
              HOME: "Home", DESKTOP: "Desktop", DOCUMENTS: "Documents", DOWNLOAD: "Downloads",
              PICTURES: "Pictures", MUSIC: "Music", VIDEOS: "Videos", gor: "Up", shrani: "Save",
              nalagam: "Loading …", niOdgovorila: "The device didn't answer.", neDeli: "The device doesn't share files.",
              odpiramZ: "Opening {ime} from {naprava} …", zazeniNa: "Start on the device", odpriNaNapravi: "Open on the device",
              prenasam: "Downloading {ime} …", mapeNaprave: "Device folders", brezProgramov: "No apps on this device.",
              niLocenega: "The device has no separate screen – it can't open this without disturbing its user.",
              oddaljeno: "Remote desktop", odpriSProgramom: "Open with an app on {naprava}",
              prilagodi: "Customise desktop …", temaSistema: "System theme and settings …", ozadje: "Wallpaper",
              ozadjeWindows: "Windows wallpaper", lastnaSlika: "Your own picture …", zameglitevNapis: "Panel blur",
              prosojnostNapis: "Panel opacity", privzeto: "Default", zapri: "Close",
              temaOpis: "Colours come from the system theme (Safeer OS Settings › Appearance) – the same in Web and Safeer Control." }
    })
    function t(k, vr) {
        var s = (besedila[jezik] || besedila.en)[k] || besedila.en[k] || k
        if (vr) for (var x in vr) s = s.replace("{" + x + "}", vr[x])
        return s
    }
    function velikost(b) {
        if (!b) return ""
        var e = ["B", "KB", "MB", "GB", "TB"], i = 0
        while (b >= 1024 && i < 4) { b /= 1024; i++ }
        return (i ? b.toFixed(b < 10 ? 1 : 0) : b) + " " + e[i]
    }
    function cas(s) {
        if (!s) return ""
        var d = new Date(s * 1000), z = new Date()
        if (d.toDateString() === z.toDateString()) return Qt.formatTime(d, "hh:mm")
        return Qt.formatDate(d, "d. M. yyyy")
    }
    function obvesti(besedilo, dejanje, ob) { obvestilo.pokazi(besedilo, dejanje, ob) }

    // ------------------------------------------------------------------ ozadje
    property string ozadjeUrl: ""
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0; color: "#0b1426" }
            GradientStop { position: 1; color: "#152a3d" }
        }
    }
    Image {
        id: ozadje
        anchors.fill: parent
        source: koren.ozadjeUrl
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: false
        sourceSize.width: 1920
        opacity: status === Image.Ready ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 600 } }
    }
    MultiEffect {
        id: zamegljeno
        anchors.fill: ozadje
        source: ozadje
        blurEnabled: true
        blur: koren.zameglitev
        Behavior on blur { NumberAnimation { duration: 200 } }
        blurMax: 64
        saturation: 0.15
        brightness: -0.08
        // Vidna mora biti (sicer se ne izrise v teksturo); skrijejo jo panelni ShaderEffectSource (hideSource).
    }

    // ------------------------------------------------------------------ iskanje (zgoraj na sredini)
    Steklo {
        id: iskanje
        zamegljeno: zamegljeno
        width: Math.min(640, koren.width * 0.46); height: 54
        anchors.horizontalCenter: parent.horizontalCenter
        y: 18
        polmer: 27
        TextField {
            id: polje
            anchors.fill: parent; anchors.leftMargin: 52; anchors.rightMargin: 18
            placeholderText: koren.t("isci")
            placeholderTextColor: koren.paleta.medlo
            color: koren.paleta.besedilo; font.pixelSize: 16
            background: Item {}
            onTextChanged: casovnikIskanja.restart()
            Keys.onReturnPressed: zadetki.izberi(zadetki.trenutni)
            Keys.onDownPressed: zadetki.trenutni = Math.min(zadetki.trenutni + 1, zadetkiModel.count - 1)
            Keys.onUpPressed: zadetki.trenutni = Math.max(zadetki.trenutni - 1, 0)
            Keys.onEscapePressed: text = ""
        }
        Lupa { x: 20; anchors.verticalCenter: parent.verticalCenter }
    }
    Timer { id: casovnikIskanja; interval: 180; onTriggered: zadetki.isci(polje.text) }
    ListModel { id: zadetkiModel }
    Steklo {
        id: zadetki
        zamegljeno: zamegljeno
        z: 10
        property int trenutni: 0
        property int zahteva: 0
        visible: polje.text.length > 0 && zadetkiModel.count > 0
        width: iskanje.width; x: iskanje.x; y: iskanje.y + iskanje.height + 8
        height: Math.min(420, seznamZadetkov.contentHeight + 16)
        barva: koren.plosca(Math.min(0.95, koren.prosojnost + 0.27))
        function isci(q) {
            zadetkiModel.clear(); trenutni = 0
            q = (q || "").trim(); if (!q) return
            var st = ++zahteva, ql = q.toLowerCase()
            programi.vsi.filter(function (p) { return p.ime.toLowerCase().indexOf(ql) >= 0 }).slice(0, 5)
                .forEach(function (p) { zadetkiModel.append({ vrsta: "program", ime: p.ime, opis: koren.t("programi"), kljuc: p.id, ikona: p.ikona || "" }) })
            zadetkiModel.append({ vrsta: "splet", ime: koren.t("splet") + ": " + q, opis: "", kljuc: q, ikona: "" })
            koren.klic("isciDatoteke", [q, 8], function (r) {
                if (st !== zahteva) return
                ;(r || []).forEach(function (d) {
                    zadetkiModel.insert(Math.max(0, zadetkiModel.count - 1), { vrsta: "datoteka", ime: d.ime, opis: d.pot, kljuc: d.pot, ikona: "" })
                })
            })
        }
        function izberi(i) {
            if (i < 0 || i >= zadetkiModel.count) return
            var z = zadetkiModel.get(i)
            if (z.vrsta === "program") koren.klic("zazeni", [z.kljuc], function (ok) { if (!ok) koren.obvesti(koren.t("niUspelo")) })
            else if (z.vrsta === "datoteka") koren.klic("odpriDatoteko", [z.kljuc])
            else koren.klic("spletNaNamizju", [z.kljuc])
            polje.text = ""
        }
        ListView {
            id: seznamZadetkov
            anchors.fill: parent; anchors.margins: 8
            model: zadetkiModel; clip: true; interactive: contentHeight > height
            delegate: Rectangle {
                width: seznamZadetkov.width; height: 46; radius: 10
                color: index === zadetki.trenutni ? Qt.rgba(1, 1, 1, 0.12) : (mz.containsMouse ? Qt.rgba(1, 1, 1, 0.06) : "transparent")
                Row {
                    anchors.verticalCenter: parent.verticalCenter; x: 10; spacing: 12
                    Image { source: model.ikona; width: 26; height: 26; visible: model.ikona !== ""; sourceSize: Qt.size(52, 52) }
                    Text { text: model.vrsta === "splet" ? "🌐" : "📄"; visible: model.ikona === ""; font.pixelSize: 20; width: 26 }
                    Column {
                        Text { text: model.ime; color: koren.paleta.besedilo; font.pixelSize: 14; elide: Text.ElideRight; width: seznamZadetkov.width - 70 }
                        Text { text: model.opis; color: koren.paleta.medlo; font.pixelSize: 11; elide: Text.ElideMiddle; width: seznamZadetkov.width - 70; visible: text !== "" }
                    }
                }
                MouseArea { id: mz; anchors.fill: parent; hoverEnabled: true; onClicked: zadetki.izberi(index) }
            }
        }
    }

    // Safeer Link pod iskanjem
    property int napravVLinku: 0
    Rectangle {
        id: linkGumb
        anchors.horizontalCenter: parent.horizontalCenter
        y: iskanje.y + iskanje.height + 10
        visible: !zadetki.visible
        height: 26; width: linkVrstica.width + 22; radius: 13
        color: ml.containsMouse ? Qt.rgba(1, 1, 1, 0.16) : koren.plosca(koren.prosojnost)
        border.color: Qt.rgba(1, 1, 1, 0.12)
        Behavior on color { ColorAnimation { duration: 150 } }
        Row {
            id: linkVrstica; anchors.centerIn: parent; spacing: 7
            Rectangle { width: 7; height: 7; radius: 4; color: koren.napravVLinku > 0 ? koren.paleta.poudarek : koren.paleta.medlo; anchors.verticalCenter: parent.verticalCenter }
            Text { text: koren.t("link") + (koren.napravVLinku > 0 ? " · " + koren.t("napravN", { n: koren.napravVLinku }) : ""); color: koren.paleta.besedilo; font.pixelSize: 12 }
        }
        MouseArea { id: ml; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: koren.klic("odpriRazdelek", ["naprave"]) }
    }

    // ------------------------------------------------------------------ paneli
    readonly property real rob: 30
    readonly property real vrhPanelov: 104
    Steklo {
        id: medijski
        zamegljeno: zamegljeno
        x: koren.rob; y: koren.vrhPanelov
        width: (koren.width - 3 * koren.rob) * 0.44; height: 150
        Column {
            anchors.fill: parent; anchors.margins: 18; spacing: 10
            RowLayout {
                width: parent.width
                Text { text: koren.t("medijski"); color: koren.paleta.besedilo; font.pixelSize: 16; font.bold: true; Layout.fillWidth: true }
                Gumb { besedilo: koren.t("odpriMedijski"); onKlik: koren.klic("odpriRazdelek", ["media"]) }
            }
            Row {
                spacing: 14
                Rectangle {
                    width: 54; height: 54; radius: 12
                    gradient: Gradient { GradientStop { position: 0; color: "#2f6bff" } GradientStop { position: 1; color: "#7a4dff" } }
                    Text { anchors.centerIn: parent; text: "♫"; color: "white"; font.pixelSize: 24 }
                }
                Column {
                    anchors.verticalCenter: parent.verticalCenter; spacing: 4
                    Text { text: koren.t("niPredvajanja"); color: koren.paleta.besedilo; font.pixelSize: 15; font.bold: true }
                    Text { text: koren.t("medijOpis"); color: koren.paleta.medlo; font.pixelSize: 12 }
                }
            }
        }
    }

    Datoteke {
        id: datoteke
        zamegljeno: zamegljeno
        x: koren.rob; y: medijski.y + medijski.height + koren.rob * 0.6
        width: medijski.width; height: koren.height - y - koren.rob
    }

    Programi {
        id: programi
        zamegljeno: zamegljeno
        x: medijski.x + medijski.width + koren.rob; y: koren.vrhPanelov
        width: koren.width - x - koren.rob; height: koren.height - y - koren.rob
    }

    // vstop: paneli prihajajo drug za drugim
    Component.onCompleted: {
        var paneli = [medijski, datoteke, programi]
        for (var i = 0; i < paneli.length; i++) { paneli[i].opacity = 0; paneli[i].scale = 0.97 }
        vstop.start()
        koren.klic("zacetek", [], function (z) {
            z = z || {}
            koren.jezik = (z.jezik === "sl" || z.jezik === "en") ? z.jezik : "en"
            koren.ozadjeUrl = z.ozadje || ""
            if (z.videz) koren.uporabiVidez(z.videz)
            datoteke.zacni(z.mape || [])
        })
        programi.nalozi()
        osveziLink()
    }
    // Safeer Link se ob zagonu sele poveze: stevilo naprav osvezimo na 20 s.
    property var naprave: []
    function osveziLink() {
        koren.klic("napraveNamizja", [], function (n) { koren.naprave = n || []; koren.napravVLinku = koren.naprave.length })
    }
    Timer { interval: 20000; running: true; repeat: true; onTriggered: koren.osveziLink() }
    SequentialAnimation {
        id: vstop
        PauseAnimation { duration: 120 }
        ParallelAnimation {
            NumberAnimation { target: medijski; property: "opacity"; to: 1; duration: 380; easing.type: Easing.OutCubic }
            NumberAnimation { target: medijski; property: "scale"; to: 1; duration: 380; easing.type: Easing.OutCubic }
            SequentialAnimation {
                PauseAnimation { duration: 90 }
                ParallelAnimation {
                    NumberAnimation { target: datoteke; property: "opacity"; to: 1; duration: 380; easing.type: Easing.OutCubic }
                    NumberAnimation { target: datoteke; property: "scale"; to: 1; duration: 380; easing.type: Easing.OutCubic }
                }
            }
            SequentialAnimation {
                PauseAnimation { duration: 180 }
                ParallelAnimation {
                    NumberAnimation { target: programi; property: "opacity"; to: 1; duration: 380; easing.type: Easing.OutCubic }
                    NumberAnimation { target: programi; property: "scale"; to: 1; duration: 380; easing.type: Easing.OutCubic }
                }
            }
        }
    }

    // ------------------------------------------------------------------ prilagodi namizje (desni klik na ozadje)
    MouseArea {
        anchors.fill: parent
        z: -1
        acceptedButtons: Qt.RightButton
        onClicked: function (m) { meniNamizja.popup() }
    }
    Menu {
        id: meniNamizja
        background: Rectangle { implicitWidth: 230; radius: 12; color: koren.paleta.vnos; border.color: Qt.rgba(1, 1, 1, 0.14) }
        MenuItem {
            text: koren.t("prilagodi")
            contentItem: Text { text: parent.text; color: koren.paleta.besedilo; font.pixelSize: 13; leftPadding: 6 }
            background: Rectangle { radius: 8; color: parent.highlighted ? koren.poudarekA(0.22) : "transparent" }
            onTriggered: prilagodi.odpri()
        }
        MenuItem {
            text: koren.t("temaSistema")
            contentItem: Text { text: parent.text; color: koren.paleta.besedilo; font.pixelSize: 13; leftPadding: 6 }
            background: Rectangle { radius: 8; color: parent.highlighted ? koren.poudarekA(0.22) : "transparent" }
            onTriggered: koren.klic("odpriRazdelek", ["nastavitve"])
        }
    }
    Prilagodi { id: prilagodi; z: 30; anchors.fill: parent }

    // ------------------------------------------------------------------ obvestilo spodaj (z dejanjem, npr. Razveljavi)
    Rectangle {
        id: obvestilo
        z: 20
        property var ob: null
        anchors.horizontalCenter: parent.horizontalCenter
        y: koren.height - 70
        height: 40; radius: 20; width: vrsticaObv.width + 30
        color: koren.plosca(0.94); border.color: Qt.rgba(1, 1, 1, 0.14)
        opacity: 0; visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 200 } }
        function pokazi(b, dejanje, ob) {
            napisObv.text = b; gumbObv.besedilo = dejanje || ""; obvestilo.ob = ob || null
            opacity = 1; skrijObv.restart()
        }
        Row {
            id: vrsticaObv; anchors.centerIn: parent; spacing: 14
            Text { id: napisObv; color: koren.paleta.besedilo; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter }
            Gumb { id: gumbObv; visible: besedilo !== ""; onKlik: { if (obvestilo.ob) obvestilo.ob(); obvestilo.opacity = 0 } }
        }
        Timer { id: skrijObv; interval: 6000; onTriggered: obvestilo.opacity = 0 }
    }
}
