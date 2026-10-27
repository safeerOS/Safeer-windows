"""Bounded recovery for interrupted search connections, with TLS validation intact."""
import html
import re
import urllib.parse
from gi.repository import Gio, GLib, GObject
import gi

# Splet in Safeer Browser: GTK4 in WebKit 6.0 (GTK3 umaknjen 18. 10. 2026). WebKit2 4.1 samo, ce je proces ze izbral
# GTK 3. Prej je bil WebKit2 4.1 privzet, ce Gtk se ni bil izbran: samostojni uvoz (tests/test_network_errors.py v svojem
# procesu) je padel z »Namespace WebKit2 not available«, ker CI namesti samo gir1.2-webkit-6.0 (19. 10. 2026).
if gi.get_required_version("Gtk") == "3.0":
    gi.require_version('WebKit2', '4.1')
    from gi.repository import WebKit2
else:
    gi.require_version('WebKit', '6.0')
    from gi.repository import WebKit as WebKit2

BESEDILA = {
    "sl": ("Varne povezave ni mogoče potrditi", "Strani trenutno ni mogoče odpreti",
           "Spletno mesto je poslalo neveljavno potrdilo. Povezava je ostala blokirana.",
           "Povezava s spletnim mestom se je prekinila. Preverite povezavo in poskusite znova.",
           "Poskusi znova", "Za vrnitev uporabite gumb Nazaj ali Domov v brskalniku."),
    "en": ("The secure connection could not be verified", "This page can't be opened right now",
           "The website sent an invalid certificate. The connection stayed blocked.",
           "The connection to the website was interrupted. Check your connection and try again.",
           "Try again", "Use the Back or Home button in the browser to go back."),
    "de": ("Die sichere Verbindung konnte nicht bestätigt werden", "Die Seite kann gerade nicht geöffnet werden",
           "Die Website hat ein ungültiges Zertifikat gesendet. Die Verbindung bleibt blockiert.",
           "Die Verbindung zur Website wurde unterbrochen. Prüfe die Verbindung und versuche es erneut.",
           "Erneut versuchen", "Mit Zurück oder Startseite im Browser kommst du zurück."),
    "es": ("No se pudo verificar la conexión segura", "Ahora no se puede abrir la página",
           "El sitio envió un certificado no válido. La conexión sigue bloqueada.",
           "Se interrumpió la conexión con el sitio. Comprueba la conexión e inténtalo de nuevo.",
           "Reintentar", "Usa Atrás o Inicio en el navegador para volver."),
    "fr": ("La connexion sécurisée n’a pas pu être vérifiée", "Impossible d’ouvrir la page pour le moment",
           "Le site a envoyé un certificat non valide. La connexion reste bloquée.",
           "La connexion au site a été interrompue. Vérifiez la connexion et réessayez.",
           "Réessayer", "Utilisez Retour ou Accueil dans le navigateur pour revenir."),
    "it": ("Impossibile verificare la connessione sicura", "Al momento la pagina non si può aprire",
           "Il sito ha inviato un certificato non valido. La connessione resta bloccata.",
           "La connessione al sito si è interrotta. Controlla la connessione e riprova.",
           "Riprova", "Usa Indietro o Home nel browser per tornare."),
}

#: Lastnik 27. 10. 2026: seja Spleta je sla na lasten posrednik, ki ne sprejme povezave (nastavitev), stran pa je kazala
#: le »Povezava se je prekinila« - nihce ni vedel, da gre za nastavitev Spleta (Chrome in Firefox sta delala).
BESEDILA_POSREDNIK = {
    "sl": "Splet uporablja lasten posrednik %s, ki ne sprejme povezave. Izklopite ali popravite ga v nastavitvah Spleta (Lasten posrednik).",
    "en": "The browser uses a custom proxy %s that refuses the connection. Turn it off or fix it in the browser settings (Custom proxy).",
    "de": "Der Browser nutzt einen eigenen Proxy %s, der die Verbindung ablehnt. Schalte ihn in den Browser-Einstellungen aus oder korrigiere ihn (Eigener Proxy).",
    "es": "El navegador usa un proxy propio %s que rechaza la conexión. Desactívalo o corrígelo en los ajustes del navegador (Proxy propio).",
    "fr": "Le navigateur utilise un proxy personnalisé %s qui refuse la connexion. Désactivez-le ou corrigez-le dans les réglages du navigateur (Proxy personnalisé).",
    "it": "Il browser usa un proxy personalizzato %s che rifiuta la connessione. Disattivalo o correggilo nelle impostazioni del browser (Proxy personalizzato).",
}

#: Napake, pri katerih seja posrednika sploh ne doseze (zavrnjena povezava ali napaka posrednika).
def napaka_posrednika(error) -> bool:
    try:
        return any(error.matches(Gio.io_error_quark(), k) for k in (
            Gio.IOErrorEnum.CONNECTION_REFUSED, Gio.IOErrorEnum.PROXY_FAILED, Gio.IOErrorEnum.PROXY_NOT_ALLOWED,
            Gio.IOErrorEnum.PROXY_NEED_AUTH, Gio.IOErrorEnum.PROXY_AUTH_FAILED))
    except (TypeError, AttributeError):
        return False


#: Prehodne napake povezave (lastnik, 20. 10. 2026: Google iskanje v Spletu je enkrat pokazalo »Strani trenutno ni
#: mogoce odpreti«, ponovni poskus je delal - prej se je samodejno ponovilo samo iskanje DuckDuckGo). Brez napak
#: potrdil: te nikoli ne ponavljamo.
#: Zahteva streznika ZAGOTOVO ni dosegla (povezave ni bilo, posrednik jo je zavrnil, rokovanje TLS ni koncano):
#: ponovitev GET je varna na vsaki strani.
NI_POSLANO_TLS = ("HANDSHAKE",)
NI_POSLANO_IO = ("CONNECTION_REFUSED", "HOST_UNREACHABLE", "NETWORK_UNREACHABLE", "PROXY_FAILED", "NOT_CONNECTED")
#: Zahteva je morda ze prisla do streznika (povezava prekinjena med odgovorom, rok): Kimi pregled 20. 10. 2026 -
#: povezava z enkratnim zetonom (potrditev prijave) bi se ponovila. Samodejno samo za strani rezultatov iskalnikov.
DVOUMNO_TLS = ("EOF", "NOT_TLS")
DVOUMNO_IO = ("CONNECTION_CLOSED", "BROKEN_PIPE", "PARTIAL_INPUT", "TIMED_OUT")
#: Strani rezultatov iskalnikov (core/config.SEARCH_ENGINES, safeer_os.ISKALNIKI): (del gostitelja, poti).
ISKANJA = ((r"(www\.)?google\.[a-z]{2,3}(\.[a-z]{2})?", ("/search",)),
           (r"(www\.|html\.|lite\.)?duckduckgo\.com", ("", "/", "/html/", "/lite/")), (r"(www\.)?bing\.com", ("/search",)),
           (r"search\.brave\.com", ("/search",)), (r"(www\.)?ecosia\.org", ("/search",)),
           (r"(www\.)?startpage\.com", ("/do/search", "/sp/search")))
#: Toliko zadnjih navigacij (naslov -> metoda) si zapomni decide_policy (glavni okvir in podokvirji).
NAJVEC_ZAHTEV = 32
#: Notranja napaka WebKita (WebCore::internalError): domena in koda, kot ju WebKitGTK 2.54 da v load-failed.
DOMENA_NOTRANJE, KODA_NOTRANJE = "WebKitErrorDomain", 300
#: Zamiki samodejnih ponovitev (s): DoH posrednik ali Scit po kratkem izpadu (omrezje, prebujenje) potrebuje do ~1 s.
ZAMIKI_PONOVITVE = (0.4, 1.5)


def _ujema(error, tls, io) -> bool:
    for imena, domena, enum in ((tls, Gio.tls_error_quark(), Gio.TlsError), (io, Gio.io_error_quark(), Gio.IOErrorEnum)):
        for ime in imena:
            koda = getattr(enum, ime, None)
            if koda is not None and error.matches(domena, koda):
                return True
    return False


def ni_poslano(error) -> bool:
    """Napaka, pri kateri zahteva streznika ni dosegla (ponovitev GET varna povsod)."""
    if _ujema(error, NI_POSLANO_TLS, NI_POSLANO_IO):
        return True
    if error.matches(Gio.resolver_error_quark(), Gio.ResolverError.TEMPORARY_FAILURE):
        return True
    # »WebKit encountered an internal error« (WebLoaderStrategy::internallyFailedLoadTimerFired): spletni proces
    # zahteve ni mogel predati omreznemu procesu, ker se je ta ravno koncal - zahteva ni sla nikamor, ponovitev gre
    # novemu omreznemu procesu (izmerjeno 20. 10. 2026 na prenosniku lastnika: Google iz lupe -> ta napaka, takoj
    # zatem stran dela).
    return error.matches(GLib.quark_from_string(DOMENA_NOTRANJE), KODA_NOTRANJE)


def je_prehodna(error) -> bool:
    """Napaka povezave, ki jo ponovni poskus lahko odpravi (prekinjena povezava, posrednik, rok)."""
    return (ni_poslano(error) or _ujema(error, DVOUMNO_TLS, DVOUMNO_IO)
            or error.matches(WebKit2.network_error_quark(), WebKit2.NetworkError.TRANSPORT))


def je_iskanje(uri) -> bool:
    """Stran rezultatov iskalnika (GET z nizom q): ponovitev je vedno varna (nicesar ne spremeni na strezniku)."""
    deli = urllib.parse.urlsplit(uri)
    gost = (deli.hostname or "").lower()
    if deli.scheme != "https" or not urllib.parse.parse_qs(deli.query).get("q"):
        return False
    return any(re.fullmatch(g, gost) and deli.path in poti for g, poti in ISKANJA)


def can_retry_search(uri, method, error, attempted):
    """Samodejna ponovitev glavne navigacije: samo GET (nikoli obrazci), http(s) in najvec len(ZAMIKI_PONOVITVE)-krat
    za isti naslov. Napaka, pri kateri zahteva ni dosegla streznika - na vsaki strani; napaka, pri kateri je morda ze
    prisla (prekinjen odgovor) - samo stran rezultatov iskalnika (sicer bi se lahko dvakrat porabila povezava z
    enkratnim zetonom)."""
    if isinstance(attempted, bool):
        attempted = 1 if attempted else 0
    parsed = urllib.parse.urlsplit(uri)
    if not (attempted < len(ZAMIKI_PONOVITVE) and method == 'GET' and parsed.scheme in ('https', 'http')
            and parsed.hostname):
        return False
    return ni_poslano(error) or (je_prehodna(error) and je_iskanje(uri))


def opis_napake(error) -> str:
    """Kratka tehnicna oznaka napake za stran in dnevnik (brez naslova strani)."""
    try:
        return "%s %d" % (GLib.quark_to_string(error.domain) if isinstance(error.domain, int) else error.domain,
                          error.code)
    except Exception:  # noqa: BLE001
        return ""


def error_html(uri, method, certificate=False, jezik="sl", koda="", posrednik=""):
    jezik = (jezik or "sl")[:2] if (jezik or "sl")[:2] in BESEDILA else "en"
    t_cert, t_ni, m_cert, m_ni, t_znova, t_nazaj = BESEDILA[jezik]
    host = html.escape(urllib.parse.urlsplit(uri).hostname or '')
    target = html.escape(uri, quote=True)
    title = t_cert if certificate else t_ni
    message = m_cert if certificate else m_ni
    if posrednik and not certificate:
        message = html.escape(BESEDILA_POSREDNIK[jezik] % _posrednik_za_prikaz(posrednik))
    retry = f'<a href="{target}">{t_znova}</a>' if method == 'GET' and not certificate else ''
    oznaka = f'<p class="k">{html.escape(koda)}</p>' if koda else ''
    return f'''<!doctype html><html lang="{jezik}"><meta name="viewport" content="width=device-width,initial-scale=1">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
    <title>{title} — Safeer</title><style>html{{color-scheme:dark}}body{{background:#0c1420;color:#eef4fa;font:18px system-ui;max-width:620px;margin:12vh auto;padding:28px;line-height:1.6}}h1{{font-size:28px}}p{{color:#bdcadd}}a{{display:inline-block;padding:12px 22px;background:#85cd3e;color:#102006;border-radius:10px;text-decoration:none;font-weight:600}}.k{{font-size:13px;color:#7f8ea3}}</style>
    <h1>{title}</h1><p>{host}</p><p>{message}</p>{retry}<p>{t_nazaj}</p>{oznaka}</html>'''


def _posrednik_za_prikaz(url: str) -> str:
    """Samo shema, gostitelj in vrata - brez uporabniskega imena in gesla, ki sta lahko v naslovu posrednika."""
    try:
        d = urllib.parse.urlsplit(str(url).strip())
        if d.hostname:
            gost = "[%s]" % d.hostname if ":" in d.hostname else d.hostname
            return "%s://%s%s" % (d.scheme or "http", gost, ":%d" % d.port if d.port else "")
    except ValueError:
        pass
    return ""


def _ima_vire(view):
    """WebKit2 4.1 javi glavno zahtevo (in njeno metodo); WebKitGTK 6.0 ne. Lazni pogled v preizkusih: kot 4.1."""
    if not isinstance(view, GObject.Object):
        return True
    try:
        return bool(GObject.signal_lookup('resource-load-started', type(view)))
    except (TypeError, AttributeError):
        # Starejsi PyGObject (Ubuntu 22.04) za tip brez GType vrze AttributeError, novejsi TypeError (CI 14. 10. 2026).
        return True


class NetworkErrorHandler:
    def __init__(self, view, jezik=None, posrednik=None):
        self.view = view
        self.jezik = jezik          # klicljivo ali niz; Splet: jezik vmesnika
        self.posrednik = posrednik  # klicljivo: naslov lastnega posrednika seje ali "" (stran napake ga omeni)
        self.requests = {}
        self.retried = {}           # naslov -> stevilo samodejnih ponovitev
        self.error_document = False
        self.pending = None
        self.generation = 0
        view._safeer_load_failed = False
        # WebKitGTK 6.0 nima resource-load-started: glavna zahteva je tam vedno GET (gumb »Poskusi znova« = nov GET).
        if _ima_vire(view):
            view.connect('resource-load-started', self.resource_started)
        else:
            # 6.0: metodo glavne navigacije izvemo iz odlocitve (POST obrazca se ne sme ponoviti kot GET).
            view.connect('decide-policy', self.decide_policy)
        view.connect('load-changed', self.load_changed)
        view.connect('load-failed', self.load_failed)
        view.connect('load-failed-with-tls-errors', self.certificate_failed)
        view.connect('destroy', self.destroyed)

    def resource_started(self, view, resource, request):
        if resource == view.get_main_resource():
            self.requests = {request.get_uri(): request.get_http_method()}

    def decide_policy(self, view, decision, kind):
        # Odlocitve pridejo tudi za podokvirje (iframe), WebKitGTK 6.0 pa zanesljivo ne pove, za kateri okvir gre:
        # metode zato ZBIRAMO (zadnjih NAJVEC_ZAHTEV), ne zamenjamo - sicer bi GET iframa med oddajo obrazca prepisal
        # POST glavne navigacije in neuspel POST bi se ponovil kot GET (pomocnik, pregled popravkov 2812b8b).
        try:
            if kind == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
                zahteva = decision.get_navigation_action().get_request()
                uri, metoda = zahteva.get_uri(), zahteva.get_http_method() or 'GET'
                self.requests.pop(uri, None)
                self.requests[uri] = metoda
                while len(self.requests) > NAJVEC_ZAHTEV:
                    self.requests.pop(next(iter(self.requests)))
        except Exception:  # noqa: BLE001
            pass
        return False

    def load_changed(self, view, event):
        if event == WebKit2.LoadEvent.STARTED:
            self.generation += 1
        if event == WebKit2.LoadEvent.COMMITTED:
            if self.error_document:
                self.error_document = False
            else:
                view._safeer_load_failed = False
                self.retried.clear()

    def destroyed(self, *args):
        self.cancel_pending()

    def cancel_pending(self):
        self.generation += 1
        if self.pending:
            GLib.source_remove(self.pending)
            self.pending = None

    def _metoda(self, uri):
        """Metoda glavne zahteve (resource-load-started ali, kjer ga ni, decide-policy). Naslov napake je lahko ze
        preusmerjen (Google iskanje 302): preusmerjen GET ostane GET, POST ne velja za GET. Brez podatka None: nov
        zavihek iz obrazca POST target=_blank ima prazen zapis (odlocitev je dobil odpiralec) - prej je to veljalo
        za GET in neuspel POST bi se ponovil kot GET (OpenAI pregled 1.0.129, 20. 10. 2026). Metodo novemu zavihku
        poda os_splet._novo_okno."""
        if uri in self.requests:
            return self.requests[uri]
        if self.requests:
            return 'GET' if all(m == 'GET' for m in self.requests.values()) else None
        return None

    def show_error(self, uri, certificate=False, koda="", posrednik=""):
        self.view._safeer_load_failed = True
        self.error_document = True
        jezik = self.jezik() if callable(self.jezik) else (self.jezik or "sl")
        self.view.load_alternate_html(error_html(uri, self._metoda(uri), certificate, jezik, koda, posrednik), uri, None)

    def _lasten_posrednik(self) -> str:
        try:
            return str(self.posrednik() or "") if callable(self.posrednik) else ""
        except Exception:  # noqa: BLE001 - stran napake se pokaze tudi, ce nastavitev ni mogoce prebrati
            return ""

    def _brez_virov(self):
        return not _ima_vire(self.view)

    def certificate_failed(self, view, uri, certificate, flags):
        self.show_error(uri, True)
        return True

    def load_failed(self, view, event, uri, error):
        if getattr(view, "_safeer_crashed", False):
            return True
        if error.matches(WebKit2.network_error_quark(), WebKit2.NetworkError.CANCELLED):
            return False
        if error.matches(WebKit2.policy_error_quark(), WebKit2.PolicyError.FRAME_LOAD_INTERRUPTED_BY_POLICY_CHANGE):
            return False
        metoda = self._metoda(uri)
        poskusov = self.retried.get(uri, 0)
        koda = opis_napake(error)
        # Dnevnik (sled.log): samo ime gostitelja, brez poti in poizvedbe (zasebnost).
        print("[Splet] napaka nalaganja %s: %s, ponovitev %d" % (urllib.parse.urlsplit(uri).hostname or "?", koda,
              poskusov), flush=True)
        if can_retry_search(uri, metoda, error, poskusov):
            self.retried[uri] = poskusov + 1
            generation = self.generation
            def retry():
                self.pending = None
                # A failed provisional navigation may restore the previous URI.
                # Guard against a newer navigation, rather than comparing that URI.
                if self.generation == generation:
                    view.load_uri(uri)
                return False
            self.pending = GLib.timeout_add(int(ZAMIKI_PONOVITVE[poskusov] * 1000), retry)
            return True
        certificate = error.matches(Gio.tls_error_quark(), Gio.TlsError.BAD_CERTIFICATE)
        posrednik = self._lasten_posrednik() if napaka_posrednika(error) else ""
        self.show_error(uri, certificate, koda, posrednik)
        return True
