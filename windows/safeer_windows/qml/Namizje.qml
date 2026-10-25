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
            if (vrsta === "slicica" && p) datoteke.slicicaPrisla(p)
            if (vrsta === "prostori") prostori.odpri(p && p.smer < 0 ? -1 : 1)
            if (vrsta === "videz" && p) koren.uporabiVidez(p)
            if (vrsta === "iskanjeOdDrugod" && p && p.q) { polje.text = p.q; polje.forceActiveFocus() }
        }
    }
    property string jezik: "sl"
    property string razlicica: ""
    // Tema sistema (Nastavitve Safeer OS) in videz namizja (Prilagodi namizje) - en videz z vmesnikom, Spletom in Controlom.
    // Privzeto = barve namizja Safeer OS na Linuxu (tokens.css); prava paleta pride iz tema.py (os.css).
    property var paleta: ({ poudarek: "#8ac7ff", poudarekTemna: "#0b1424", besedilo: "#eaf2ff", medlo: "#afbed4",
                            vnos: "#121d2d", fokus: "#9dceff", ok: "#7fe0b6",
                            karticaRgb: [0.0627, 0.102, 0.1686], poudarekRgb: [0.5412, 0.7804, 1.0] })
    property real zameglitev: 1.0
    property real prosojnost: 0.55
    property var videz: ({})
    function plosca(a) { var c = paleta.karticaRgb || [0.0627, 0.102, 0.1686]; return Qt.rgba(c[0], c[1], c[2], a) }
    function poudarekA(a) { var c = paleta.poudarekRgb || [0.5412, 0.7804, 1.0]; return Qt.rgba(c[0], c[1], c[2], a) }
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
              temaOpis: "Barve so iz teme sistema (Nastavitve Safeer OS › Videz) – enake v Spletu in Safeer Controlu.",
              // Diski, O tem racunalniku, slicice in datum nastanka (lastnik, 25. 10. 2026)
              diski: "Diski", diskSistem: "Sistemski disk", diskProsto: "{prosto} prostih od {skupaj}", diskMalo: "Na disku {ime} zmanjkuje prostora: prostih je še {prosto}.", poImenu: "Po imenu", poDatumu: "Po datumu nastanka", poVelikosti: "Po velikosti", datumNastanka: "Datum nastanka", vseObdobje: "Vse", danes: "Danes", taTeden: "Ta teden", taMesec: "Ta mesec", letos: "Letos", izberiObdobje: "Izberi obdobje …", od: "Od", do: "Do", uporabi: "Uporabi", obdobjeNapaka: "Vpiši datum, npr. 25. 10. 2026.", pogledSeznam: "Seznam", pogledMreza: "Mreža s sličicami", fotografijeNaprave: "Fotografije", naloziVec: "Naloži več", nastanek: "Nastanek", niVObdobju: "V tem obdobju ni datotek.", oRacunalniku: "O tem računalniku", oRacunalnikuMeni: "O tem računalniku …", racRacunalnik: "Računalnik", racSistem: "Sistem", racJedro: "Jedro", racProcesor: "Procesor", racJeder: "{n} niti", racPomnilnik: "Pomnilnik", racPomnilnikVr: "{skupaj} (na voljo {prosto})", racGraficna: "Grafična kartica", racCas: "Čas delovanja", racMin: "{m} min", racUr: "{h} h", racDni: "{d} d {h} h", racSafeer: "Safeer OS", vseNastavitve: "Vse nastavitve …", nastavitveSistema: "Nastavitve sistema …", razvrsti: "Razvrsti", obicajnoNamizje: "Običajno namizje Windows", bliznjicaVrata: "Ctrl+Alt+Shift+W" },
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
              temaOpis: "Colours come from the system theme (Safeer OS Settings › Appearance) – the same in Web and Safeer Control.",
              diski: "Drives", diskSistem: "System drive", diskProsto: "{prosto} free of {skupaj}", diskMalo: "{ime} is running out of space: {prosto} left.", poImenu: "By name", poDatumu: "By date taken", poVelikosti: "By size", datumNastanka: "Date taken", vseObdobje: "Any time", danes: "Today", taTeden: "This week", taMesec: "This month", letos: "This year", izberiObdobje: "Choose dates …", od: "From", do: "To", uporabi: "Apply", obdobjeNapaka: "Enter a date, e.g. 25. 10. 2026.", pogledSeznam: "List", pogledMreza: "Grid with thumbnails", fotografijeNaprave: "Photos", naloziVec: "Load more", nastanek: "Taken", niVObdobju: "No files in this period.", oRacunalniku: "About this computer", oRacunalnikuMeni: "About this computer …", racRacunalnik: "Computer", racSistem: "System", racJedro: "Kernel", racProcesor: "Processor", racJeder: "{n} threads", racPomnilnik: "Memory", racPomnilnikVr: "{skupaj} ({prosto} available)", racGraficna: "Graphics", racCas: "Uptime", racMin: "{m} min", racUr: "{h} h", racDni: "{d} d {h} h", racSafeer: "Safeer OS", vseNastavitve: "All settings …", nastavitveSistema: "System settings …", razvrsti: "Sort", obicajnoNamizje: "Standard Windows desktop", bliznjicaVrata: "Ctrl+Alt+Shift+W" },
        // Ostali jeziki Safeer OS: vsa besedila prevedena (preizkus test_namizje_qml_prevodi); t() za manjkajoce vzame en.
        de: { isci: "Apps, Dateien und das Web durchsuchen …", splet: "Im Web suchen", programi: "Apps", isciProg: "App suchen …", vse: "Alle", datoteke: "Dateien", nedavno: "Zuletzt verwendet", smeti: "Papierkorb", mape: "Ordner", naprave: "Geräte", filter: "Filtern …", ime: "Name", velikost: "Größe", spremenjeno: "Geändert", prazno: "Dieser Ordner ist leer.", niNedavnih: "Noch keine zuletzt verwendeten Dateien.", kosPrazen: "Der Papierkorb ist leer.", odpri: "Öffnen", pokazi: "Im Ordner anzeigen", preimenuj: "Umbenennen", vKos: "In den Papierkorb", obnovi: "Wiederherstellen", izprazni: "Papierkorb leeren", izprazniVpr: "Papierkorb leeren? Die Dateien können nicht wiederhergestellt werden.", preklici: "Abbrechen", razveljavi: "Rückgängig", vKosPoslano: "„{ime}“ ist im Papierkorb.", novaMapa: "Neuer Ordner", niUspelo: "Das hat nicht geklappt.", medijski: "Mediencenter", niPredvajanja: "Keine Wiedergabe", medijOpis: "Musik, Radio, Filme und Serien aus deinen Quellen.", odpriMedijski: "Mediencenter öffnen", link: "Safeer Link", napravN: "{n} Geräte", nastavitve: "Einstellungen", taRacunalnik: "Dieser PC", HOME: "Persönlicher Ordner", DESKTOP: "Desktop", DOCUMENTS: "Dokumente", DOWNLOAD: "Downloads", PICTURES: "Bilder", MUSIC: "Musik", VIDEOS: "Videos", gor: "Nach oben", shrani: "Speichern", nalagam: "Wird geladen …", niOdgovorila: "Das Gerät hat nicht geantwortet.", neDeli: "Das Gerät gibt keine Dateien frei.", odpiramZ: "{ime} wird von {naprava} geöffnet …", zazeniNa: "Auf dem Gerät starten", odpriNaNapravi: "Auf dem Gerät öffnen", prenasam: "{ime} wird heruntergeladen …", mapeNaprave: "Ordner des Geräts", brezProgramov: "Keine Apps auf diesem Gerät.", niLocenega: "Das Gerät hat keinen separaten Bildschirm – es kann das nicht öffnen, ohne seinen Benutzer zu stören.", oddaljeno: "Remote-Desktop", odpriSProgramom: "Mit einer App auf {naprava} öffnen", prilagodi: "Desktop anpassen …", temaSistema: "Systemdesign und Einstellungen …", ozadje: "Hintergrund", ozadjeWindows: "Windows-Hintergrund", lastnaSlika: "Eigenes Bild …", zameglitevNapis: "Unschärfe der Flächen", prosojnostNapis: "Deckkraft der Flächen", privzeto: "Standard", zapri: "Schließen", temaOpis: "Die Farben stammen aus dem Systemdesign (Safeer-OS-Einstellungen › Darstellung) – gleich in Web und Safeer Control.",
              diski: "Laufwerke", diskSistem: "Systemlaufwerk", diskProsto: "{prosto} frei von {skupaj}", diskMalo: "Auf {ime} wird der Platz knapp: noch {prosto} frei.", poImenu: "Nach Name", poDatumu: "Nach Aufnahmedatum", poVelikosti: "Nach Größe", datumNastanka: "Aufnahmedatum", vseObdobje: "Jederzeit", danes: "Heute", taTeden: "Diese Woche", taMesec: "Dieser Monat", letos: "Dieses Jahr", izberiObdobje: "Zeitraum wählen …", od: "Von", do: "Bis", uporabi: "Anwenden", obdobjeNapaka: "Gib ein Datum ein, z. B. 25. 10. 2026.", pogledSeznam: "Liste", pogledMreza: "Raster mit Vorschaubildern", fotografijeNaprave: "Fotos", naloziVec: "Mehr laden", nastanek: "Aufgenommen", niVObdobju: "Keine Dateien in diesem Zeitraum.", oRacunalniku: "Über diesen Computer", oRacunalnikuMeni: "Über diesen Computer …", racRacunalnik: "Computer", racSistem: "System", racJedro: "Kernel", racProcesor: "Prozessor", racJeder: "{n} Threads", racPomnilnik: "Arbeitsspeicher", racPomnilnikVr: "{skupaj} ({prosto} verfügbar)", racGraficna: "Grafik", racCas: "Laufzeit", racMin: "{m} min", racUr: "{h} h", racDni: "{d} T {h} h", racSafeer: "Safeer OS", vseNastavitve: "Alle Einstellungen …", nastavitveSistema: "Systemeinstellungen …", razvrsti: "Sortieren", obicajnoNamizje: "Normaler Windows-Desktop", bliznjicaVrata: "Strg+Alt+Umschalt+W" },
        es: { isci: "Busca aplicaciones, archivos y en la web …", splet: "Buscar en la web", programi: "Aplicaciones", isciProg: "Buscar una aplicación …", vse: "Todo", datoteke: "Archivos", nedavno: "Recientes", smeti: "Papelera de reciclaje", mape: "Carpetas", naprave: "Dispositivos", filter: "Filtrar …", ime: "Nombre", velikost: "Tamaño", spremenjeno: "Modificado", prazno: "Esta carpeta está vacía.", niNedavnih: "Aún no hay archivos recientes.", kosPrazen: "La papelera de reciclaje está vacía.", odpri: "Abrir", pokazi: "Mostrar en la carpeta", preimenuj: "Cambiar nombre", vKos: "Mover a la papelera", obnovi: "Restaurar", izprazni: "Vaciar la papelera", izprazniVpr: "¿Vaciar la papelera? Los archivos no se podrán restaurar.", preklici: "Cancelar", razveljavi: "Deshacer", vKosPoslano: "«{ime}» está en la papelera.", novaMapa: "Nueva carpeta", niUspelo: "No ha funcionado.", medijski: "Centro multimedia", niPredvajanja: "Nada en reproducción", medijOpis: "Música, radio, películas y series de tus fuentes.", odpriMedijski: "Abrir el centro multimedia", link: "Safeer Link", napravN: "{n} dispositivos", nastavitve: "Ajustes", taRacunalnik: "Este equipo", HOME: "Carpeta personal", DESKTOP: "Escritorio", DOCUMENTS: "Documentos", DOWNLOAD: "Descargas", PICTURES: "Imágenes", MUSIC: "Música", VIDEOS: "Vídeos", gor: "Subir", shrani: "Guardar", nalagam: "Cargando …", niOdgovorila: "El dispositivo no respondió.", neDeli: "El dispositivo no comparte archivos.", odpiramZ: "Abriendo {ime} desde {naprava} …", zazeniNa: "Iniciar en el dispositivo", odpriNaNapravi: "Abrir en el dispositivo", prenasam: "Descargando {ime} …", mapeNaprave: "Carpetas del dispositivo", brezProgramov: "No hay aplicaciones en este dispositivo.", niLocenega: "El dispositivo no tiene una pantalla aparte: no puede abrir esto sin molestar a su usuario.", oddaljeno: "Escritorio remoto", odpriSProgramom: "Abrir con una aplicación de {naprava}", prilagodi: "Personalizar el escritorio …", temaSistema: "Tema y ajustes del sistema …", ozadje: "Fondo de pantalla", ozadjeWindows: "Fondo de Windows", lastnaSlika: "Tu propia imagen …", zameglitevNapis: "Desenfoque de paneles", prosojnostNapis: "Opacidad de paneles", privzeto: "Predeterminado", zapri: "Cerrar", temaOpis: "Los colores vienen del tema del sistema (Ajustes de Safeer OS › Apariencia), los mismos en Web y Safeer Control.",
              diski: "Unidades", diskSistem: "Unidad del sistema", diskProsto: "{prosto} libres de {skupaj}", diskMalo: "{ime} se está quedando sin espacio: quedan {prosto}.", poImenu: "Por nombre", poDatumu: "Por fecha de captura", poVelikosti: "Por tamaño", datumNastanka: "Fecha de captura", vseObdobje: "Cualquier fecha", danes: "Hoy", taTeden: "Esta semana", taMesec: "Este mes", letos: "Este año", izberiObdobje: "Elegir fechas …", od: "Desde", do: "Hasta", uporabi: "Aplicar", obdobjeNapaka: "Escribe una fecha, p. ej. 25. 10. 2026.", pogledSeznam: "Lista", pogledMreza: "Cuadrícula con miniaturas", fotografijeNaprave: "Fotos", naloziVec: "Cargar más", nastanek: "Captura", niVObdobju: "No hay archivos en este periodo.", oRacunalniku: "Acerca de este equipo", oRacunalnikuMeni: "Acerca de este equipo …", racRacunalnik: "Equipo", racSistem: "Sistema", racJedro: "Núcleo", racProcesor: "Procesador", racJeder: "{n} hilos", racPomnilnik: "Memoria", racPomnilnikVr: "{skupaj} ({prosto} disponibles)", racGraficna: "Gráficos", racCas: "Tiempo encendido", racMin: "{m} min", racUr: "{h} h", racDni: "{d} d {h} h", racSafeer: "Safeer OS", vseNastavitve: "Todos los ajustes …", nastavitveSistema: "Ajustes del sistema …", razvrsti: "Ordenar", obicajnoNamizje: "Escritorio normal de Windows", bliznjicaVrata: "Ctrl+Alt+Mayús+W" },
        fr: { isci: "Rechercher des applications, des fichiers et sur le web …", splet: "Rechercher sur le web", programi: "Applications", isciProg: "Trouver une application …", vse: "Tout", datoteke: "Fichiers", nedavno: "Récents", smeti: "Corbeille", mape: "Dossiers", naprave: "Appareils", filter: "Filtrer …", ime: "Nom", velikost: "Taille", spremenjeno: "Modifié", prazno: "Ce dossier est vide.", niNedavnih: "Pas encore de fichiers récents.", kosPrazen: "La corbeille est vide.", odpri: "Ouvrir", pokazi: "Afficher dans le dossier", preimenuj: "Renommer", vKos: "Mettre à la corbeille", obnovi: "Restaurer", izprazni: "Vider la corbeille", izprazniVpr: "Vider la corbeille ? Les fichiers ne pourront pas être restaurés.", preklici: "Annuler", razveljavi: "Annuler", vKosPoslano: "« {ime} » est dans la corbeille.", novaMapa: "Nouveau dossier", niUspelo: "Cela n’a pas fonctionné.", medijski: "Centre multimédia", niPredvajanja: "Aucune lecture", medijOpis: "Musique, radio, films et séries de tes sources.", odpriMedijski: "Ouvrir le centre multimédia", link: "Safeer Link", napravN: "{n} appareils", nastavitve: "Réglages", taRacunalnik: "Ce PC", HOME: "Dossier personnel", DESKTOP: "Bureau", DOCUMENTS: "Documents", DOWNLOAD: "Téléchargements", PICTURES: "Images", MUSIC: "Musique", VIDEOS: "Vidéos", gor: "Dossier parent", shrani: "Enregistrer", nalagam: "Chargement …", niOdgovorila: "L’appareil n’a pas répondu.", neDeli: "L’appareil ne partage pas de fichiers.", odpiramZ: "Ouverture de {ime} depuis {naprava} …", zazeniNa: "Lancer sur l’appareil", odpriNaNapravi: "Ouvrir sur l’appareil", prenasam: "Téléchargement de {ime} …", mapeNaprave: "Dossiers de l’appareil", brezProgramov: "Aucune application sur cet appareil.", niLocenega: "L’appareil n’a pas d’écran séparé – il ne peut pas ouvrir ceci sans déranger son utilisateur.", oddaljeno: "Bureau à distance", odpriSProgramom: "Ouvrir avec une application de {naprava}", prilagodi: "Personnaliser le bureau …", temaSistema: "Thème et réglages du système …", ozadje: "Fond d’écran", ozadjeWindows: "Fond d’écran Windows", lastnaSlika: "Ta propre image …", zameglitevNapis: "Flou des panneaux", prosojnostNapis: "Opacité des panneaux", privzeto: "Par défaut", zapri: "Fermer", temaOpis: "Les couleurs viennent du thème du système (Réglages Safeer OS › Apparence) – les mêmes dans Web et Safeer Control.",
              diski: "Disques", diskSistem: "Disque système", diskProsto: "{prosto} libres sur {skupaj}", diskMalo: "{ime} manque d’espace : il reste {prosto}.", poImenu: "Par nom", poDatumu: "Par date de prise de vue", poVelikosti: "Par taille", datumNastanka: "Date de prise de vue", vseObdobje: "Toutes les dates", danes: "Aujourd’hui", taTeden: "Cette semaine", taMesec: "Ce mois-ci", letos: "Cette année", izberiObdobje: "Choisir les dates …", od: "Du", do: "Au", uporabi: "Appliquer", obdobjeNapaka: "Saisis une date, p. ex. 25. 10. 2026.", pogledSeznam: "Liste", pogledMreza: "Grille avec miniatures", fotografijeNaprave: "Photos", naloziVec: "Charger plus", nastanek: "Prise de vue", niVObdobju: "Aucun fichier sur cette période.", oRacunalniku: "À propos de cet ordinateur", oRacunalnikuMeni: "À propos de cet ordinateur …", racRacunalnik: "Ordinateur", racSistem: "Système", racJedro: "Noyau", racProcesor: "Processeur", racJeder: "{n} threads", racPomnilnik: "Mémoire", racPomnilnikVr: "{skupaj} ({prosto} disponibles)", racGraficna: "Graphisme", racCas: "Durée de fonctionnement", racMin: "{m} min", racUr: "{h} h", racDni: "{d} j {h} h", racSafeer: "Safeer OS", vseNastavitve: "Tous les réglages …", nastavitveSistema: "Réglages du système …", razvrsti: "Trier", obicajnoNamizje: "Bureau Windows habituel", bliznjicaVrata: "Ctrl+Alt+Maj+W" },
        it: { isci: "Cerca app, file e sul web …", splet: "Cerca sul web", programi: "App", isciProg: "Trova un’app …", vse: "Tutto", datoteke: "File", nedavno: "Recenti", smeti: "Cestino", mape: "Cartelle", naprave: "Dispositivi", filter: "Filtra …", ime: "Nome", velikost: "Dimensione", spremenjeno: "Modificato", prazno: "Questa cartella è vuota.", niNedavnih: "Ancora nessun file recente.", kosPrazen: "Il Cestino è vuoto.", odpri: "Apri", pokazi: "Mostra nella cartella", preimenuj: "Rinomina", vKos: "Sposta nel Cestino", obnovi: "Ripristina", izprazni: "Svuota il Cestino", izprazniVpr: "Svuotare il Cestino? I file non potranno essere ripristinati.", preklici: "Annulla", razveljavi: "Annulla", vKosPoslano: "«{ime}» è nel Cestino.", novaMapa: "Nuova cartella", niUspelo: "Non è riuscito.", medijski: "Centro multimediale", niPredvajanja: "Nessuna riproduzione", medijOpis: "Musica, radio, film e serie dalle tue fonti.", odpriMedijski: "Apri il Centro multimediale", link: "Safeer Link", napravN: "{n} dispositivi", nastavitve: "Impostazioni", taRacunalnik: "Questo PC", HOME: "Cartella personale", DESKTOP: "Desktop", DOCUMENTS: "Documenti", DOWNLOAD: "Download", PICTURES: "Immagini", MUSIC: "Musica", VIDEOS: "Video", gor: "Su", shrani: "Salva", nalagam: "Caricamento …", niOdgovorila: "Il dispositivo non ha risposto.", neDeli: "Il dispositivo non condivide file.", odpiramZ: "Apertura di {ime} da {naprava} …", zazeniNa: "Avvia sul dispositivo", odpriNaNapravi: "Apri sul dispositivo", prenasam: "Download di {ime} …", mapeNaprave: "Cartelle del dispositivo", brezProgramov: "Nessuna app su questo dispositivo.", niLocenega: "Il dispositivo non ha uno schermo separato: non può aprirlo senza disturbare il suo utente.", oddaljeno: "Desktop remoto", odpriSProgramom: "Apri con un’app di {naprava}", prilagodi: "Personalizza il desktop …", temaSistema: "Tema e impostazioni di sistema …", ozadje: "Sfondo", ozadjeWindows: "Sfondo di Windows", lastnaSlika: "Un’immagine tua …", zameglitevNapis: "Sfocatura dei pannelli", prosojnostNapis: "Opacità dei pannelli", privzeto: "Predefinito", zapri: "Chiudi", temaOpis: "I colori vengono dal tema di sistema (Impostazioni di Safeer OS › Aspetto), uguali in Web e Safeer Control.",
              diski: "Unità", diskSistem: "Unità di sistema", diskProsto: "{prosto} liberi su {skupaj}", diskMalo: "Su {ime} lo spazio sta finendo: restano {prosto}.", poImenu: "Per nome", poDatumu: "Per data di scatto", poVelikosti: "Per dimensione", datumNastanka: "Data di scatto", vseObdobje: "Qualsiasi data", danes: "Oggi", taTeden: "Questa settimana", taMesec: "Questo mese", letos: "Quest’anno", izberiObdobje: "Scegli le date …", od: "Dal", do: "Al", uporabi: "Applica", obdobjeNapaka: "Inserisci una data, ad es. 25. 10. 2026.", pogledSeznam: "Elenco", pogledMreza: "Griglia con miniature", fotografijeNaprave: "Foto", naloziVec: "Carica altro", nastanek: "Scatto", niVObdobju: "Nessun file in questo periodo.", oRacunalniku: "Informazioni su questo computer", oRacunalnikuMeni: "Informazioni su questo computer …", racRacunalnik: "Computer", racSistem: "Sistema", racJedro: "Kernel", racProcesor: "Processore", racJeder: "{n} thread", racPomnilnik: "Memoria", racPomnilnikVr: "{skupaj} ({prosto} disponibili)", racGraficna: "Grafica", racCas: "Tempo di attività", racMin: "{m} min", racUr: "{h} h", racDni: "{d} g {h} h", racSafeer: "Safeer OS", vseNastavitve: "Tutte le impostazioni …", nastavitveSistema: "Impostazioni di sistema …", razvrsti: "Ordina", obicajnoNamizje: "Desktop normale di Windows", bliznjicaVrata: "Ctrl+Alt+Maiusc+W" }
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

    // Safeer Link in Prostori pod iskanjem
    property int napravVLinku: 0
    Row {
        anchors.horizontalCenter: parent.horizontalCenter
        y: iskanje.y + iskanje.height + 10
        visible: !zadetki.visible
        spacing: 8
    Rectangle {
        id: linkGumb
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
    // Prostori (Safeer Link Spaces): zasloni povezanih naprav in navidezna namizja Windows (tudi Ctrl+Win+Tab).
    Rectangle {
        id: prostoriGumb
        objectName: "prostoriGumb"
        height: 26; width: prostoriNapis.width + 40; radius: 13
        color: mpg.containsMouse ? Qt.rgba(1, 1, 1, 0.16) : koren.plosca(koren.prosojnost)
        border.color: Qt.rgba(1, 1, 1, 0.12)
        Behavior on color { ColorAnimation { duration: 150 } }
        Text { x: 10; anchors.verticalCenter: parent.verticalCenter; text: "⧉"; color: koren.paleta.poudarek; font.pixelSize: 13 }
        Text { id: prostoriNapis; x: 28; anchors.verticalCenter: parent.verticalCenter; color: koren.paleta.besedilo; font.pixelSize: 12
               text: koren.prostoriBesedila.prostori || "Prostori" }
        MouseArea { id: mpg; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: prostori.odpri(0)
                    ToolTip.visible: containsMouse; ToolTip.delay: 500
                    ToolTip.text: koren.bliznjice.prostori === false
                                  ? String(koren.prostoriBesedila.prostoriNamig || "").replace(/\s*\([^()]*\)\s*$/, "")
                                  : (koren.prostoriBesedila.prostoriNamig || "") }
        Accessible.role: Accessible.Button
        Accessible.name: koren.prostoriBesedila.prostori || "Prostori"
    }
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
            koren.jezik = koren.besedila[z.jezik] ? z.jezik : "en"
            koren.razlicica = String(z.razlicica || "")
            koren.ozadjeUrl = z.ozadje || ""
            if (z.videz) koren.uporabiVidez(z.videz)
            datoteke.zacni(z.mape || [])
        })
        programi.nalozi()
        osveziLink()
        koren.klic("besedilaProstorov", [], function (b) { if (b) koren.prostoriBesedila = b })
        koren.klic("bliznjice", [], function (b) { if (b) koren.bliznjice = b })
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
        // Bliznjica, ki je ni bilo mogoce prijaviti (zasedel jo je drug program), se v meniju ne oglasuje (N9).
        onAboutToShow: koren.klic("bliznjice", [], function (b) { if (b) koren.bliznjice = b })
        objectName: "meniNamizja"
        background: Rectangle { implicitWidth: 330; radius: 12; color: koren.paleta.vnos; border.color: Qt.rgba(1, 1, 1, 0.14) }
        MenuItem {
            text: koren.t("prilagodi")
            contentItem: Text { text: parent.text; color: koren.paleta.besedilo; font.pixelSize: 13; leftPadding: 6 }
            background: Rectangle { radius: 8; color: parent.highlighted ? koren.poudarekA(0.22) : "transparent" }
            onTriggered: prilagodi.odpri()
        }
        MenuItem {
            // Nastavitve sistema: okno Nastavitve Safeer OS (samo ta razdelek, brez stare lupine in brez Safeer Linka)
            text: koren.t("nastavitveSistema")
            contentItem: Text { text: parent.text; color: koren.paleta.besedilo; font.pixelSize: 13; leftPadding: 6 }
            background: Rectangle { radius: 8; color: parent.highlighted ? koren.poudarekA(0.22) : "transparent" }
            onTriggered: koren.klic("odpriRazdelek", ["nastavitve"])
        }
        MenuItem {
            text: koren.t("oRacunalnikuMeni")
            contentItem: Text { text: parent.text; color: koren.paleta.besedilo; font.pixelSize: 13; leftPadding: 6 }
            background: Rectangle { radius: 8; color: parent.highlighted ? koren.poudarekA(0.22) : "transparent" }
            onTriggered: oRacunalniku.odpri()
        }
        MenuSeparator { contentItem: Rectangle { implicitHeight: 1; color: Qt.rgba(1, 1, 1, 0.12) } }
        MenuItem {
            // Varnostna vrata (pravilo lastnika): en klik nazaj na obicajno namizje Windows; vklop spet v Nastavitvah
            // (»Safeer OS kot namizje«). Isto naredi sistemska bliznjica Ctrl+Alt+Shift+W, tudi ce namizje ne odgovarja.
            text: koren.t("obicajnoNamizje") + (koren.bliznjice.varnostna === false ? "" : "    " + koren.t("bliznjicaVrata"))
            contentItem: Text { text: parent.text; color: koren.paleta.besedilo; font.pixelSize: 13; leftPadding: 6 }
            background: Rectangle { radius: 8; color: parent.highlighted ? koren.poudarekA(0.22) : "transparent" }
            onTriggered: koren.klic("namizjeSafeer", [false])
        }
    }
    Prilagodi { id: prilagodi; z: 30; anchors.fill: parent }
    ORacunalniku { id: oRacunalniku; z: 30; anchors.fill: parent }
    Prostori { id: prostori; objectName: "prostori"; z: 31; anchors.fill: parent; besedila: koren.prostoriBesedila }
    property var prostoriBesedila: ({})
    property var bliznjice: ({})
    // Disk iz »O tem racunalniku«: odpre ga v panelu Datoteke (ta racunalnik).
    function pokaziMapo(pot) {
        if (datoteke.naprava) { datoteke.naprava = ""; datoteke.viri = datoteke.lokalniViri }
        datoteke.odpri({ vrsta: "lokalno", pot: pot })
    }

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
