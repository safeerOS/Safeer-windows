"""Nastavitve spletnih mest: dovoljenja po straneh (kamera, mikrofon, lokacija, obvestila ...) kot v Firefoxu.

Lastnik, 14. 10. 2026 (posnetek nastavitev Firefoxa: »Nastavitve spletnih mest«, »Obvestila«). Prej je imel Splet eno
nastavitev za vse strani (vprasaj / dovoli / zavrni) in si odgovora ni zapomnil. Zdaj: odgovor se zapomni za stran,
privzeto za vsako vrsto se nastavi posebej, vse se da pregledati in spremeniti. GTK-ja ta modul ne potrebuje.
"""
from __future__ import annotations

import urllib.parse

#: Vrste dovoljenj (kljuc -> privzeto). »vprasaj« = stran vprasa uporabnika.
VRSTE = ("lokacija", "kamera", "mikrofon", "zaslon", "obvestila", "odlozisce", "kazalec", "drm", "naprave", "piskotki")
PRIVZETO = {"lokacija": "vprasaj", "kamera": "vprasaj", "mikrofon": "vprasaj", "zaslon": "vprasaj",
            "obvestila": "vprasaj", "odlozisce": "vprasaj", "kazalec": "dovoli", "drm": "dovoli", "naprave": "vprasaj",
            "piskotki": "vprasaj"}
ODLOCITVE = ("vprasaj", "dovoli", "zavrni")
SAMODEJNO = ("dovoli", "brez_zvoka", "blokiraj")


def vrste_zahteve(zahteva, WebKit) -> list:
    """Vrste, ki jih zahteva WebKitGTK potrebuje (kamera in mikrofon sta lahko oba hkrati)."""
    W = WebKit
    if isinstance(zahteva, W.UserMediaPermissionRequest):
        izid = []
        try:
            if W.user_media_permission_is_for_display_device(zahteva):
                return ["zaslon"]
        except Exception:  # noqa: BLE001 - starejsi WebKit
            pass
        if zahteva.get_property("is-for-video-device"):
            izid.append("kamera")
        if zahteva.get_property("is-for-audio-device"):
            izid.append("mikrofon")
        return izid or ["kamera"]
    tabela = (("GeolocationPermissionRequest", "lokacija"), ("NotificationPermissionRequest", "obvestila"),
              ("ClipboardPermissionRequest", "odlozisce"), ("PointerLockPermissionRequest", "kazalec"),
              ("MediaKeySystemPermissionRequest", "drm"), ("DeviceInfoPermissionRequest", "naprave"),
              ("WebsiteDataAccessPermissionRequest", "piskotki"))
    for razred, vrsta in tabela:
        r = getattr(W, razred, None)
        if r is not None and isinstance(zahteva, r):
            return [vrsta]
    return []


def gostitelj(uri: str) -> str:
    try:
        return (urllib.parse.urlsplit(uri or "").hostname or "").rstrip(".").lower()
    except ValueError:
        return ""


def _strani(config) -> dict:
    v = config.get("dovoljenja_strani", {}) or {}
    return {str(h): {str(k): str(o) for k, o in d.items() if k in VRSTE and o in ODLOCITVE}
            for h, d in v.items() if isinstance(d, dict)} if isinstance(v, dict) else {}


def privzeto(config, vrsta: str) -> str:
    """Privzeto za vrsto; stara nastavitev permissions_policy (allow/deny) velja kot privzeto za vse."""
    lastna = (config.get("dovoljenja_privzeto", {}) or {}).get(vrsta)
    if lastna in ODLOCITVE:
        return lastna
    staro = {"allow": "dovoli", "deny": "zavrni"}.get(str(config.get("permissions_policy", "ask")))
    return staro or PRIVZETO.get(vrsta, "vprasaj")


def odlocitev(config, uri: str, vrste) -> str:
    """»dovoli«, »zavrni« ali »vprasaj« za zahtevo strani. Vec vrst hkrati: zavrni, ce je katera zavrnjena; dovoli,
    ce so vse dovoljene; sicer vprasaj."""
    stran = _strani(config).get(gostitelj(uri), {})
    vse = [stran.get(v) or privzeto(config, v) for v in vrste] or ["vprasaj"]
    if "zavrni" in vse:
        return "zavrni"
    if all(o == "dovoli" for o in vse):
        return "dovoli"
    return "vprasaj"


def zapomni(config, uri: str, vrste, odl: str) -> None:
    h = gostitelj(uri)
    if not h or odl not in ODLOCITVE:
        return
    strani = _strani(config)
    d = strani.setdefault(h, {})
    for v in vrste:
        if odl == "vprasaj":
            d.pop(v, None)
        else:
            d[v] = odl
    if not d:
        strani.pop(h, None)
    config.set("dovoljenja_strani", dict(list(strani.items())[-500:]))


def izvori_obvestil(config) -> tuple:
    """(dovoljeni, zavrnjeni) izvori https://gostitelj za obvestila - za WebKitov zacetni seznam dovoljenj
    (initialize-notification-permissions), da zapomnjena odlocitev velja ze ob nalaganju strani."""
    dovoljeni, zavrnjeni = [], []
    for h, d in _strani(config).items():
        o = d.get("obvestila")
        if o == "dovoli":
            dovoljeni.append("https://" + h)
        elif o == "zavrni":
            zavrnjeni.append("https://" + h)
    return dovoljeni, zavrnjeni


def pozabi_stran(config, gost: str) -> None:
    strani = _strani(config)
    strani.pop(gost, None)
    config.set("dovoljenja_strani", strani)


def nastavi_privzeto(config, vrsta: str, odl: str) -> None:
    if vrsta in VRSTE and odl in ODLOCITVE:
        d = dict(config.get("dovoljenja_privzeto", {}) or {})
        d[vrsta] = odl
        config.set("dovoljenja_privzeto", d)


def seznam(config) -> list:
    """[(gostitelj, {vrsta: odlocitev})] za pregled v nastavitvah, po abecedi."""
    return sorted(_strani(config).items())


def samodejno_predvajanje(config) -> str:
    v = str(config.get("samodejno_predvajanje", "brez_zvoka"))
    return v if v in SAMODEJNO else "brez_zvoka"


BESEDILA = {
    "sl": {"dv_naslov": "Nastavitve spletnih mest", "dv_lokacija": "Lokacija", "dv_kamera": "Kamera",
           "dv_mikrofon": "Mikrofon", "dv_zaslon": "Deljenje zaslona", "dv_obvestila": "Obvestila",
           "dv_odlozisce": "Odložišče", "dv_kazalec": "Zaklep kazalca (igre)", "dv_drm": "Zaščitena vsebina (DRM)",
           "dv_naprave": "Seznam kamer in mikrofonov", "dv_piskotki": "Piškotki v vdelanih straneh",
           "dv_vprasaj": "Vprašaj", "dv_dovoli": "Dovoli", "dv_zavrni": "Zavrni", "dv_privzeto": "Privzeto za vse strani",
           "dv_strani": "Strani z lastno nastavitvijo", "dv_ni_strani": "Nobena stran še nima lastne nastavitve.",
           "dv_pozabi": "Pozabi", "dv_zahteva": "{stran} želi: {kaj}", "dv_samodejno": "Samodejno predvajanje",
           "dv_sp_dovoli": "Dovoli zvok in sliko", "dv_sp_brez_zvoka": "Samo brez zvoka", "dv_sp_blokiraj": "Blokiraj",
           "dv_pojavna": "Strani, ki smejo odpirati pojavna okna", "dv_programi": "Strani, ki smejo odpirati programe",
           "dv_zascita": "Strani brez zaščite pred sledenjem", "dv_odstrani": "Odstrani",
           "dv_novi": "Velja za nove zavihke."},
    "en": {"dv_naslov": "Site settings", "dv_lokacija": "Location", "dv_kamera": "Camera", "dv_mikrofon": "Microphone",
           "dv_zaslon": "Screen sharing", "dv_obvestila": "Notifications", "dv_odlozisce": "Clipboard",
           "dv_kazalec": "Pointer lock (games)", "dv_drm": "Protected content (DRM)",
           "dv_naprave": "List of cameras and microphones", "dv_piskotki": "Cookies in embedded pages",
           "dv_vprasaj": "Ask", "dv_dovoli": "Allow", "dv_zavrni": "Block", "dv_privzeto": "Default for all sites",
           "dv_strani": "Sites with their own setting", "dv_ni_strani": "No site has its own setting yet.",
           "dv_pozabi": "Forget", "dv_zahteva": "{stran} wants: {kaj}", "dv_samodejno": "Autoplay",
           "dv_sp_dovoli": "Allow audio and video", "dv_sp_brez_zvoka": "Muted only", "dv_sp_blokiraj": "Block",
           "dv_pojavna": "Sites allowed to open pop-ups", "dv_programi": "Sites allowed to open programs",
           "dv_zascita": "Sites without tracking protection", "dv_odstrani": "Remove", "dv_novi": "Applies to new tabs."},
    "de": {"dv_naslov": "Website-Einstellungen", "dv_lokacija": "Standort", "dv_kamera": "Kamera", "dv_mikrofon": "Mikrofon",
           "dv_zaslon": "Bildschirmfreigabe", "dv_obvestila": "Benachrichtigungen", "dv_odlozisce": "Zwischenablage",
           "dv_kazalec": "Mauszeiger-Sperre (Spiele)", "dv_drm": "Geschützte Inhalte (DRM)",
           "dv_naprave": "Liste der Kameras und Mikrofone", "dv_piskotki": "Cookies in eingebetteten Seiten",
           "dv_vprasaj": "Fragen", "dv_dovoli": "Erlauben", "dv_zavrni": "Blockieren", "dv_privzeto": "Standard für alle Seiten",
           "dv_strani": "Seiten mit eigener Einstellung", "dv_ni_strani": "Noch keine Seite hat eine eigene Einstellung.",
           "dv_pozabi": "Vergessen", "dv_zahteva": "{stran} möchte: {kaj}", "dv_samodejno": "Automatische Wiedergabe",
           "dv_sp_dovoli": "Ton und Video erlauben", "dv_sp_brez_zvoka": "Nur stumm", "dv_sp_blokiraj": "Blockieren",
           "dv_pojavna": "Seiten, die Pop-ups öffnen dürfen", "dv_programi": "Seiten, die Programme öffnen dürfen",
           "dv_zascita": "Seiten ohne Tracking-Schutz", "dv_odstrani": "Entfernen", "dv_novi": "Gilt für neue Tabs."},
    "es": {"dv_naslov": "Ajustes de sitios", "dv_lokacija": "Ubicación", "dv_kamera": "Cámara", "dv_mikrofon": "Micrófono",
           "dv_zaslon": "Compartir pantalla", "dv_obvestila": "Notificaciones", "dv_odlozisce": "Portapapeles",
           "dv_kazalec": "Bloqueo del puntero (juegos)", "dv_drm": "Contenido protegido (DRM)",
           "dv_naprave": "Lista de cámaras y micrófonos", "dv_piskotki": "Cookies en páginas incrustadas",
           "dv_vprasaj": "Preguntar", "dv_dovoli": "Permitir", "dv_zavrni": "Bloquear",
           "dv_privzeto": "Predeterminado para todos los sitios", "dv_strani": "Sitios con ajuste propio",
           "dv_ni_strani": "Ningún sitio tiene todavía un ajuste propio.", "dv_pozabi": "Olvidar",
           "dv_zahteva": "{stran} quiere: {kaj}", "dv_samodejno": "Reproducción automática",
           "dv_sp_dovoli": "Permitir audio y vídeo", "dv_sp_brez_zvoka": "Solo sin sonido", "dv_sp_blokiraj": "Bloquear",
           "dv_pojavna": "Sitios que pueden abrir ventanas emergentes", "dv_programi": "Sitios que pueden abrir programas",
           "dv_zascita": "Sitios sin protección contra rastreo", "dv_odstrani": "Quitar",
           "dv_novi": "Se aplica a las pestañas nuevas."},
    "fr": {"dv_naslov": "Paramètres des sites", "dv_lokacija": "Position", "dv_kamera": "Caméra", "dv_mikrofon": "Microphone",
           "dv_zaslon": "Partage d’écran", "dv_obvestila": "Notifications", "dv_odlozisce": "Presse-papiers",
           "dv_kazalec": "Verrouillage du pointeur (jeux)", "dv_drm": "Contenu protégé (DRM)",
           "dv_naprave": "Liste des caméras et micros", "dv_piskotki": "Cookies dans les pages intégrées",
           "dv_vprasaj": "Demander", "dv_dovoli": "Autoriser", "dv_zavrni": "Bloquer", "dv_privzeto": "Par défaut pour tous les sites",
           "dv_strani": "Sites avec un réglage propre", "dv_ni_strani": "Aucun site n’a encore de réglage propre.",
           "dv_pozabi": "Oublier", "dv_zahteva": "{stran} souhaite : {kaj}", "dv_samodejno": "Lecture automatique",
           "dv_sp_dovoli": "Autoriser son et vidéo", "dv_sp_brez_zvoka": "Sans son uniquement", "dv_sp_blokiraj": "Bloquer",
           "dv_pojavna": "Sites autorisés à ouvrir des pop-ups", "dv_programi": "Sites autorisés à ouvrir des programmes",
           "dv_zascita": "Sites sans protection contre le pistage", "dv_odstrani": "Supprimer",
           "dv_novi": "S’applique aux nouveaux onglets."},
    "it": {"dv_naslov": "Impostazioni dei siti", "dv_lokacija": "Posizione", "dv_kamera": "Fotocamera", "dv_mikrofon": "Microfono",
           "dv_zaslon": "Condivisione schermo", "dv_obvestila": "Notifiche", "dv_odlozisce": "Appunti",
           "dv_kazalec": "Blocco del puntatore (giochi)", "dv_drm": "Contenuti protetti (DRM)",
           "dv_naprave": "Elenco di fotocamere e microfoni", "dv_piskotki": "Cookie nelle pagine incorporate",
           "dv_vprasaj": "Chiedi", "dv_dovoli": "Consenti", "dv_zavrni": "Blocca", "dv_privzeto": "Predefinito per tutti i siti",
           "dv_strani": "Siti con impostazione propria", "dv_ni_strani": "Nessun sito ha ancora un’impostazione propria.",
           "dv_pozabi": "Dimentica", "dv_zahteva": "{stran} vuole: {kaj}", "dv_samodejno": "Riproduzione automatica",
           "dv_sp_dovoli": "Consenti audio e video", "dv_sp_brez_zvoka": "Solo senza audio", "dv_sp_blokiraj": "Blocca",
           "dv_pojavna": "Siti che possono aprire pop-up", "dv_programi": "Siti che possono aprire programmi",
           "dv_zascita": "Siti senza protezione antitracciamento", "dv_odstrani": "Rimuovi",
           "dv_novi": "Vale per le nuove schede."},
}
