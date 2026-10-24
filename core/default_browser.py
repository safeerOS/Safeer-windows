"""Native per-user browser registration for GTK desktops."""
import os
import tempfile
from pathlib import Path
from gi.repository import Gio, GLib

DESKTOP_ID = 'safeer-browser.desktop'
WEB_TYPES = ('x-scheme-handler/http', 'x-scheme-handler/https',
             'text/html', 'application/xhtml+xml')


_EXEC_RESERVED = set(' \t"\'\\><~|&;$*?#()`%')


def _exec_argument(value):
    """Quote an Exec argument only when the Desktop Entry spec requires it.

    xdg-utils (xdg-open, xdg-mime, xdg-settings) take the first word of Exec literally, quotes
    included, to find the program - a quoted "/usr/bin/safeer" is "not found" there and the
    entry is skipped in favour of the next browser. Plain paths therefore stay unquoted."""
    value = str(value)
    if not any(char in _EXEC_RESERVED for char in value):
        return value
    value = value.replace('%', '%%')
    for char in ('\\', '"', '`', '$'):
        value = value.replace(char, '\\' + char)
    return '"' + value + '"'


#: Vstop brskalnika v izvorni kodi (GTK4, WebKitGTK 6.0; GTK3 je umaknjen 18. 10. 2026).
VSTOP = 'safeer_brskalnik.py'


def _entry_script(app_dir):
    """Vstop, ki ga zazene vnos .desktop izvorne kode."""
    return Path(app_dir) / VSTOP


def launcher_command(app_dir):
    """The command that starts *this* install: the packaged launcher next to the payload
    (/usr/lib/safeer-browser -> /usr/bin/safeer) when it exists, else python3 with the entry script."""
    app_dir = Path(app_dir).resolve()
    launcher = app_dir.parent.parent / 'bin' / 'safeer'
    if launcher.is_file() and os.access(launcher, os.X_OK):
        return _exec_argument(launcher)
    return '/usr/bin/python3 -s ' + _exec_argument(_entry_script(app_dir))


def _exec_program(exec_line):
    """Resolved path of the program an Exec line starts, or None when it cannot run.

    GLib refuses to load a desktop entry whose program does not exist (GDesktopAppInfo returns
    NULL), which is exactly what a leftover entry from an uninstalled checkout looks like."""
    try:
        _ok, argv = GLib.shell_parse_argv(exec_line or '')
    except GLib.Error:
        return None
    if not argv:
        return None
    program = argv[0]
    if os.path.isabs(program):
        return program if os.access(program, os.X_OK) else None
    return GLib.find_program_in_path(program)


def _starts_this_install(exec_line, app_dir):
    """True when the Exec line runs this install's launcher or one of its entry scripts."""
    program = _exec_program(exec_line)
    if program is None:
        return False
    try:
        _ok, argv = GLib.shell_parse_argv(exec_line)
    except GLib.Error:
        return False
    app_dir = Path(app_dir).resolve()
    launcher = app_dir.parent.parent / 'bin' / 'safeer'
    try:
        if Path(program).resolve() == launcher.resolve():
            return True
    except OSError:
        pass
    words = [w for w in argv[1:] if not w.startswith('%')]
    vstop = app_dir / VSTOP
    return any(Path(w).resolve() == vstop for w in words if os.path.isabs(w))


def desktop_entry_text(existing, app_dir):
    """Repair the main group without changing existing launch actions or labels.

    Exec is rewritten whenever it would not start this install - a program that no longer
    exists, or another checkout of Safeer - since a broken Exec makes the whole entry
    unloadable and a foreign one would make the wrong Safeer the default."""
    key = GLib.KeyFile()
    if existing:
        key.load_from_data(existing, len(existing.encode('utf-8')),
                           GLib.KeyFileFlags.KEEP_COMMENTS | GLib.KeyFileFlags.KEEP_TRANSLATIONS)
    command = launcher_command(app_dir)
    defaults = {
        'Type': 'Application', 'Name': 'Safeer Browser',
        'Exec': command + ' %U',
        'Icon': 'safeer-browser', 'Terminal': 'false',
        # Razred okna = ID aplikacije (safeer_brskalnik.py, GLib.set_prgname).
        'StartupWMClass': 'io.github.memelandfaner.SafeerBrowser',
        'Categories': 'Network;WebBrowser;',
    }
    for name, value in defaults.items():
        try:
            present = key.get_string('Desktop Entry', name)
        except GLib.Error:
            present = None
        # Exec is ours to own: anything but the canonical command (a removed or foreign launcher,
        # or a needlessly quoted path that xdg-utils cannot resolve) is replaced.
        if not present or (name == 'Exec' and present != value):
            key.set_string('Desktop Entry', name, value)
    try:
        types = list(key.get_string_list('Desktop Entry', 'MimeType'))
    except GLib.Error:
        types = []
    key.set_string_list('Desktop Entry', 'MimeType', list(dict.fromkeys(types + list(WEB_TYPES))))
    # xdg-settings' fix_local_desktop_file can append MimeType to the last action.
    for group in key.get_groups()[0]:
        if not group.startswith('Desktop Action '):
            continue
        if 'MimeType' in key.get_keys(group)[0]:
            key.remove_key(group, 'MimeType')
        try:
            action_exec = key.get_string(group, 'Exec')
        except GLib.Error:
            action_exec = None
        if action_exec and (_exec_program(action_exec) is None or action_exec.startswith('"')):
            key.set_string(group, 'Exec', command)  # uninstalled launcher, or quoting xdg-utils cannot read
    return key.to_data()[0]


def _packaged_entry_for(app_dir):
    """Path of a system-wide safeer-browser.desktop that starts this install, or None."""
    user_dir = Path(GLib.get_user_data_dir()) / 'applications'
    for data_dir in GLib.get_system_data_dirs():
        candidate = Path(data_dir) / 'applications' / DESKTOP_ID
        if not candidate.is_file() or candidate.parent == user_dir:
            continue
        try:
            key = GLib.KeyFile()
            key.load_from_file(str(candidate), GLib.KeyFileFlags.NONE)
            if _starts_this_install(key.get_string('Desktop Entry', 'Exec'), app_dir):
                return candidate
        except GLib.Error:
            continue
    return None


def _back_up(path):
    backup = path.with_suffix('.desktop.safeer-backup')
    if not backup.exists():
        backup.write_bytes(path.read_bytes())


def ensure_desktop_entry(app_dir):
    """Return the desktop entry that registers this install, repairing or retiring a per-user one.

    A packaged install has its entry in /usr/share/applications; a stale per-user copy (left by
    an earlier checkout) would shadow it in menus and cannot even be loaded once its launcher
    is gone, so it is backed up and removed. Without a packaged entry (a development checkout)
    the per-user entry is written, or repaired so that it starts this install."""
    directory = Path(GLib.get_user_data_dir()) / 'applications'
    path = directory / DESKTOP_ID
    packaged = _packaged_entry_for(app_dir)
    if packaged is not None:
        if path.exists():
            _back_up(path)
            path.unlink()
        return packaged
    existing_app = Gio.DesktopAppInfo.new(DESKTOP_ID)
    source = path if path.exists() else (
        Path(existing_app.get_filename()) if existing_app is not None else None)
    existing = source.read_text() if source is not None else ''
    updated = desktop_entry_text(existing, app_dir)
    directory.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text() != updated:
        if path.exists():
            _back_up(path)
        fd, temporary = tempfile.mkstemp(prefix='.safeer-', suffix='.desktop', dir=directory)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(updated)
            os.chmod(temporary, 0o644)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return path


#: Nastavitev privzetega brskalnika iz Flatpaka: portala zanjo ni, dostopa do gostitelja (xdg-settings) Safeer Browser
#: od 1.0.127 nima (lastnik, 15. 10. 2026). Zato pove, kje v nastavitvah sistema se nastavi - po namizju.
NAVODILA = {
    "sl": {"cinnamon": "Odpri Meni → Nastavitve sistema → Prednostni programi in pri »Splet« izberi Safeer Browser.",
           "gnome": "Odpri Nastavitve → Programi → Privzeti programi in pri »Splet« izberi Safeer Browser.",
           "kde": "Odpri Sistemske nastavitve → Privzeti programi in pri »Spletni brskalnik« izberi Safeer Browser.",
           "xfce": "Odpri Nastavitve → Privzeti programi in pri »Spletni brskalnik« izberi Safeer Browser.",
           "mate": "Odpri Sistem → Nastavitve → Prednostni programi in pri »Spletni brskalnik« izberi Safeer Browser.",
           "drugo": "V nastavitvah sistema odpri privzete (prednostne) programe in za splet izberi Safeer Browser."},
    "en": {"cinnamon": "Open Menu → System Settings → Preferred Applications and choose Safeer Browser for “Web”.",
           "gnome": "Open Settings → Apps → Default Apps and choose Safeer Browser for “Web”.",
           "kde": "Open System Settings → Default Applications and choose Safeer Browser as “Web browser”.",
           "xfce": "Open Settings → Default Applications and choose Safeer Browser as “Web Browser”.",
           "mate": "Open System → Preferences → Preferred Applications and choose Safeer Browser as “Web Browser”.",
           "drugo": "Open the default (preferred) applications in your system settings and choose Safeer Browser for the web."},
    "de": {"cinnamon": "Öffne Menü → Systemeinstellungen → Bevorzugte Anwendungen und wähle bei „Web“ Safeer Browser.",
           "gnome": "Öffne Einstellungen → Apps → Standard-Apps und wähle bei „Web“ Safeer Browser.",
           "kde": "Öffne Systemeinstellungen → Standard-Anwendungen und wähle Safeer Browser als „Webbrowser“.",
           "xfce": "Öffne Einstellungen → Bevorzugte Anwendungen und wähle Safeer Browser als „Webbrowser“.",
           "mate": "Öffne System → Einstellungen → Bevorzugte Anwendungen und wähle Safeer Browser als „Webbrowser“.",
           "drugo": "Öffne in den Systemeinstellungen die Standard-Anwendungen und wähle Safeer Browser für das Web."},
    "es": {"cinnamon": "Abre Menú → Configuración del sistema → Aplicaciones preferidas y elige Safeer Browser en «Web».",
           "gnome": "Abre Configuración → Aplicaciones → Aplicaciones predeterminadas y elige Safeer Browser en «Web».",
           "kde": "Abre Preferencias del sistema → Aplicaciones predeterminadas y elige Safeer Browser como «Navegador web».",
           "xfce": "Abre Configuración → Aplicaciones predeterminadas y elige Safeer Browser como «Navegador web».",
           "mate": "Abre Sistema → Preferencias → Aplicaciones preferidas y elige Safeer Browser como «Navegador web».",
           "drugo": "Abre las aplicaciones predeterminadas en la configuración del sistema y elige Safeer Browser para la web."},
    "fr": {"cinnamon": "Ouvrez Menu → Paramètres système → Applications préférées et choisissez Safeer Browser pour « Web ».",
           "gnome": "Ouvrez Paramètres → Applications → Applications par défaut et choisissez Safeer Browser pour « Web ».",
           "kde": "Ouvrez Configuration du système → Applications par défaut et choisissez Safeer Browser comme « Navigateur web ».",
           "xfce": "Ouvrez Paramètres → Applications favorites et choisissez Safeer Browser comme « Navigateur web ».",
           "mate": "Ouvrez Système → Préférences → Applications préférées et choisissez Safeer Browser comme « Navigateur web ».",
           "drugo": "Ouvrez les applications par défaut dans les paramètres du système et choisissez Safeer Browser pour le web."},
    "it": {"cinnamon": "Apri Menu → Impostazioni di sistema → Applicazioni preferite e scegli Safeer Browser per «Web».",
           "gnome": "Apri Impostazioni → App → App predefinite e scegli Safeer Browser per «Web».",
           "kde": "Apri Impostazioni di sistema → Applicazioni predefinite e scegli Safeer Browser come «Browser web».",
           "xfce": "Apri Impostazioni → Applicazioni preferite e scegli Safeer Browser come «Browser web».",
           "mate": "Apri Sistema → Preferenze → Applicazioni preferite e scegli Safeer Browser come «Browser web».",
           "drugo": "Apri le applicazioni predefinite nelle impostazioni di sistema e scegli Safeer Browser per il web."},
}


def namizje(okolje=None):
    """cinnamon, gnome, kde, xfce, mate ali drugo - po XDG_CURRENT_DESKTOP (Flatpak ga prenese v peskovnik)."""
    vrednost = str((okolje if okolje is not None else os.environ).get('XDG_CURRENT_DESKTOP', '')).lower()
    for ime, znaki in (('cinnamon', ('cinnamon',)), ('kde', ('kde', 'plasma')), ('xfce', ('xfce',)),
                       ('mate', ('mate',)), ('gnome', ('gnome', 'unity', 'budgie', 'pantheon'))):
        if any(z in del_ for del_ in vrednost.split(':') for z in znaki):     # X-Cinnamon, ubuntu:GNOME ...
            return ime
    return 'drugo'


def navodila(jezik='en', okolje=None):
    besedila = NAVODILA.get(str(jezik or 'en')[:2], NAVODILA['en'])
    return besedila[namizje(okolje)]


def _mimeapps_privzeti(pot):
    """{vrsta: prvi program} iz razdelka [Default Applications] datoteke mimeapps.list."""
    key = GLib.KeyFile()
    try:
        key.load_from_file(str(pot), GLib.KeyFileFlags.NONE)
    except GLib.Error:
        return {}
    izid = {}
    for vrsta in WEB_TYPES:
        try:
            vrednost = key.get_string('Default Applications', vrsta)
        except GLib.Error:
            continue
        prvi = [v for v in vrednost.split(';') if v.strip()]
        if prvi:
            izid[vrsta] = prvi[0].strip()
    return izid


def privzeti_v_flatpaku(desktop_id, mapa=None, okolje=None):
    """Ali je <ID>.desktop privzeti brskalnik racunalnika - iz ~/.config racunalnika, ki ga Flatpak pokaze samo za branje
    (--filesystem=xdg-config/mimeapps.list:ro). Namizje lahko zapise svojo datoteko (<namizje>-mimeapps.list), ta ima
    prednost (specifikacija mime-apps); vidimo jo, ce obstaja. Brez datoteke: ne vemo -> False (vrstica ponudi navodila)."""
    mapa = Path(mapa) if mapa is not None else Path(os.path.expanduser('~')) / '.config'
    okolje = okolje if okolje is not None else os.environ
    datoteke = [mapa / (d.lower() + '-mimeapps.list') for d in
                str(okolje.get('XDG_CURRENT_DESKTOP', '')).split(':') if d] + [mapa / 'mimeapps.list']
    for vrsta in ('x-scheme-handler/http', 'x-scheme-handler/https'):
        program = next((p[vrsta] for p in map(_mimeapps_privzeti, datoteke) if vrsta in p), '')
        if program != desktop_id:
            return False
    return True


def is_default_browser():
    flatpak = os.environ.get("FLATPAK_ID")
    if flatpak:
        return privzeti_v_flatpaku(flatpak + ".desktop")
    for content_type in WEB_TYPES:
        app = Gio.AppInfo.get_default_for_type(content_type, False)
        if app is None or app.get_id() != DESKTOP_ID:
            return False
    return True


def set_default_browser(app_dir, jezik='en'):
    flatpak = os.environ.get("FLATPAK_ID")
    if flatpak:
        # Flatpak: brez dostopa do gostitelja ne moremo zapisati privzetega programa racunalnika (in ga ne smemo
        # prevzeti za hrbtom) - uporabnik dobi navodila za nastavitve svojega namizja.
        if is_default_browser():
            return True, []
        return False, [navodila(jezik)]
    if os.environ.get("APPIMAGE") or os.environ.get("SAFEER_PORTABLE"):
        return False, ["Izberite Safeer v sistemskih nastavitvah privzetih aplikacij. / Select Safeer in your desktop default-app settings."]
    errors = []
    try:
        path = ensure_desktop_entry(app_dir)
        try:
            app = Gio.DesktopAppInfo.new_from_filename(str(path))
        except TypeError:  # PyGObject raises this when GLib returns NULL (entry it will not load)
            app = None
        if app is None:
            raise RuntimeError(f'Zaganjalnika Safeer ni mogoče naložiti: {path}')
        for content_type in WEB_TYPES:
            try:
                if not app.set_as_default_for_type(content_type):
                    errors.append(content_type)
            except GLib.Error as error:
                errors.append(f'{content_type}: {error.message}')
        success = is_default_browser()
        if not success and not errors:
            errors.append('Sistem ni potrdil vseh povezav HTTP/HTTPS in spletnih datotek.')
        return success, errors
    except (OSError, GLib.Error, RuntimeError, TypeError, ValueError) as error:
        return False, [str(error)]
