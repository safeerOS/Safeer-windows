import unittest
from gi.repository import Gio, GLib
from core.network_errors import can_retry_search, error_html

class NetworkErrorTests(unittest.TestCase):
    def test_only_first_safe_search_get_retries(self):
        error = GLib.Error.new_literal(Gio.tls_error_quark(), 'Peer closed connection', Gio.TlsError.EOF)
        url='https://duckduckgo.com/?q=test'
        self.assertTrue(can_retry_search(url,'GET',error,False))
        reported=GLib.Error.new_literal(Gio.tls_error_quark(),'The TLS connection was non-properly terminated',Gio.TlsError.NOT_TLS)
        self.assertTrue(can_retry_search(url,'GET',reported,False))
        self.assertFalse(can_retry_search(url,'POST',error,False))
        # Dve samodejni ponovitvi (core/network_errors.ZAMIKI_PONOVITVE), potem stran napake; od 20. 10. 2026 za vse
        # GET navigacije s prehodno napako, ne samo za iskanje DuckDuckGo.
        self.assertTrue(can_retry_search(url,'GET',error,1))
        self.assertFalse(can_retry_search(url,'GET',error,2))
        badcert=GLib.Error.new_literal(Gio.tls_error_quark(),'Bad certificate',Gio.TlsError.BAD_CERTIFICATE)
        self.assertFalse(can_retry_search(url,'GET',badcert,False))
    def test_error_page_does_not_replay_forms_or_allow_certificates(self):
        self.assertNotIn('href=',error_html('https://example.org/','POST'))
        self.assertNotIn('href=',error_html('https://example.org/','GET',True))
        self.assertIn('&quot;',error_html('https://example.org/?q="test"','GET'))
        self.assertNotIn('<script>',error_html('https://example.org/','GET'))

    def test_recovery_keeps_previous_uri_and_does_not_override_new_navigation(self):
        from unittest.mock import patch
        from core.network_errors import NetworkErrorHandler, WebKit2
        class View:
            def __init__(self): self.loaded=[]
            def connect(self,*args): pass
            def load_uri(self,uri): self.loaded.append(uri)
            def get_uri(self): return 'about:blank'
        url='https://duckduckgo.com/?q=test'
        error=GLib.Error.new_literal(Gio.tls_error_quark(),'EOF',Gio.TlsError.NOT_TLS)
        v=View();h=NetworkErrorHandler(v);h.requests[url]='GET';callbacks=[]
        with patch('core.network_errors.GLib.timeout_add',side_effect=lambda delay,cb: callbacks.append(cb) or 1):
            self.assertTrue(h.load_failed(v,WebKit2.LoadEvent.STARTED,url,error))
        callbacks.pop()();self.assertEqual(v.loaded,[url])
        h.retried.clear()
        with patch('core.network_errors.GLib.timeout_add',side_effect=lambda delay,cb: callbacks.append(cb) or 1):
            h.load_failed(v,WebKit2.LoadEvent.STARTED,url,error)
        h.load_changed(v,WebKit2.LoadEvent.STARTED)
        callbacks.pop()();self.assertEqual(v.loaded,[url])


def test_jeziki_napake():
    from core.network_errors import BESEDILA
    assert set(BESEDILA) == {"sl", "en", "de", "es", "fr", "it"}
    assert "Try again" in error_html("https://example.org/", "GET", jezik="en")
    assert 'lang="sl"' in error_html("https://example.org/", "GET")


def test_prehodne_napake_vseh_strani_se_ponovijo():
    """Lastnik 20. 10. 2026: Google iskanje - povezava prekinjena; prej samo DuckDuckGo."""
    from core.network_errors import je_prehodna, opis_napake
    zaprta = GLib.Error.new_literal(Gio.io_error_quark(), "Connection terminated unexpectedly", Gio.IOErrorEnum.PARTIAL_INPUT)
    ponastavljena = GLib.Error.new_literal(Gio.io_error_quark(), "Connection reset by peer", Gio.IOErrorEnum.CONNECTION_CLOSED)
    posrednik = GLib.Error.new_literal(Gio.io_error_quark(), "SOCKSv5", Gio.IOErrorEnum.PROXY_FAILED)
    url = "https://www.google.com/search?q=say%20maybe"
    for napaka in (zaprta, ponastavljena, posrednik):
        assert je_prehodna(napaka)
        assert can_retry_search(url, "GET", napaka, 0)
        assert can_retry_search(url, "GET", napaka, 1)
        assert not can_retry_search(url, "GET", napaka, 2)
        assert not can_retry_search(url, "POST", napaka, 0)
        assert not can_retry_search(url, None, napaka, 0)
    assert not can_retry_search("file:///etc/passwd", "GET", zaprta, 0)
    badcert = GLib.Error.new_literal(Gio.tls_error_quark(), "Bad certificate", Gio.TlsError.BAD_CERTIFICATE)
    assert not je_prehodna(badcert)
    ni_datoteke = GLib.Error.new_literal(Gio.io_error_quark(), "Not found", Gio.IOErrorEnum.NOT_FOUND)
    assert not je_prehodna(ni_datoteke)
    assert opis_napake(zaprta) == "g-io-error-quark 34"
    assert "g-io-error-quark 34" in error_html(url, "GET", koda=opis_napake(zaprta))
    assert "<b>" not in error_html(url, "GET", koda="<b>")


def test_metoda_iz_odlocitve_in_preusmeritve():
    """6.0 nima resource-load-started: metoda glavne navigacije iz decide-policy; preusmerjen GET ostane GET, POST
    obrazca (tudi preusmerjen) se ne ponovi."""
    from core.network_errors import NetworkErrorHandler
    class Pogled:
        def connect(self, *a): pass
        def load_uri(self, uri): pass
    h = NetworkErrorHandler(Pogled())
    for brez_virov in (True, False):
        h._brez_virov = lambda: brez_virov
        h.requests = {"https://www.google.com/search?q=a": "GET"}
        assert h._metoda("https://www.google.com/search?q=a&sei=x") == "GET"
        h.requests = {"https://example.org/poslji": "POST"}
        assert h._metoda("https://example.org/hvala") is None
    h.requests = {"https://www.google.com/search?q=a": "GET"}
    assert h._metoda("https://www.google.com/search?q=a&sei=x") == "GET"
    h.requests = {"https://example.org/poslji": "POST"}
    assert h._metoda("https://example.org/hvala") is None
    assert h._metoda("https://example.org/poslji") == "POST"


def test_splet_vidi_odlocitve_pred_politiko():
    """_politika v os_splet odlocitve obravnava in vrne True (ustavi signal) - NetworkErrorHandler mora biti prikljucen
    PRED njo, sicer ne vidi metode navigacije."""
    import os
    s = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core", "os_splet.py"),
             encoding="utf-8").read()
    assert s.index("NetworkErrorHandler(pogled") < s.index('pogled.connect("decide-policy", self._politika)')


def test_iframe_ne_prepise_post_glavne_navigacije():
    """Pomocnik (pregled popravkov 2812b8b): odlocitev GET podokvirja med oddajo obrazca je prepisala POST glavne
    navigacije - neuspel POST bi se ponovil kot GET. Metode se zbirajo; POST ostane POST, neznan naslov ob POST ni GET."""
    from core.network_errors import NetworkErrorHandler, WebKit2

    class Zahteva:
        def __init__(self, u, m): self.u, self.m = u, m
        def get_uri(self): return self.u
        def get_http_method(self): return self.m

    class Odlocitev:
        def __init__(self, u, m): self.z = Zahteva(u, m)
        def get_navigation_action(self):
            z = self.z
            class A:
                def get_request(self): return z
            return A()

    class Pogled:
        def connect(self, *a): pass
        def load_uri(self, uri): self.nalozen = uri
        def load_alternate_html(self, html, uri, _b): self.napaka = uri
    v = Pogled()
    h = NetworkErrorHandler(v)
    h._brez_virov = lambda: True
    nav = WebKit2.PolicyDecisionType.NAVIGATION_ACTION
    assert h.decide_policy(v, Odlocitev("https://trgovina.si/placaj", "POST"), nav) is False
    h.decide_policy(v, Odlocitev("https://oglasi.example/okvir", "GET"), nav)
    assert h._metoda("https://trgovina.si/placaj") == "POST"
    assert h._metoda("https://trgovina.si/hvala") is None          # neznan naslov po POST: brez ponovitve
    napaka = GLib.Error.new_literal(Gio.io_error_quark(), "Connection terminated unexpectedly", Gio.IOErrorEnum.PARTIAL_INPUT)
    from unittest.mock import patch
    with patch("core.network_errors.GLib.timeout_add", side_effect=AssertionError("POST se ne sme ponoviti")):
        h.load_failed(v, WebKit2.LoadEvent.STARTED, "https://trgovina.si/placaj", napaka)
    assert not hasattr(v, "nalozen") and v.napaka == "https://trgovina.si/placaj"
    from core import network_errors as ne
    for i in range(ne.NAJVEC_ZAHTEV + 5):
        h.decide_policy(v, Odlocitev("https://a.si/%d" % i, "GET"), nav)
    assert len(h.requests) == ne.NAJVEC_ZAHTEV
    assert h._metoda("https://a.si/preusmerjen") == "GET"            # same GET: preusmerjen GET ostane GET


def test_dvoumna_napaka_samo_na_iskanju():
    """Kimi pregled 20. 10. 2026: prekinjen odgovor (zahteva je morda ze prisla do streznika) se na navadni strani ne
    ponovi sam - povezava z enkratnim zetonom bi se porabila dvakrat. Napaka brez poslane zahteve se ponovi povsod."""
    from core.network_errors import ni_poslano
    zaprta = GLib.Error.new_literal(Gio.io_error_quark(), "Connection terminated unexpectedly", Gio.IOErrorEnum.PARTIAL_INPUT)
    zavrnjena = GLib.Error.new_literal(Gio.io_error_quark(), "Connection refused", Gio.IOErrorEnum.CONNECTION_REFUSED)
    notranja = GLib.Error.new_literal(GLib.quark_from_string("WebKitErrorDomain"), "internal error", 300)
    potrditev = "https://trgovina.si/potrdi?zeton=abc"
    assert not can_retry_search(potrditev, "GET", zaprta, 0)
    assert can_retry_search(potrditev, "GET", zavrnjena, 0)
    assert can_retry_search(potrditev, "GET", notranja, 0)
    assert ni_poslano(notranja) and not ni_poslano(zaprta)
    for iskanje in ("https://www.google.com/search?q=a", "https://www.google.si/search?q=a", "https://duckduckgo.com/?q=a",
                    "https://www.bing.com/search?q=a", "https://search.brave.com/search?q=a",
                    "https://www.ecosia.org/search?q=a", "https://www.startpage.com/do/search?q=a"):
        assert can_retry_search(iskanje, "GET", zaprta, 0), iskanje
    for ni in ("https://www.google.com/maps?q=a", "https://accounts.google.com/search?q=a&x=1&continue=", "http://www.google.com/search?q=a",
               "https://www.google.com/search"):
        assert not can_retry_search(ni, "GET", zaprta, 0), ni


def test_brez_zapisa_metode_ni_ponovitve():
    """OpenAI pregled 1.0.129 (20. 10. 2026): nov zavihek iz obrazca POST target=_blank nima zapisa metode (odlocitev
    je dobil odpiralec). Prazen zapis je prej veljal za GET in neuspel POST bi se ponovil kot GET - zdaj None."""
    from core.network_errors import NetworkErrorHandler
    class Pogled:
        def connect(self, *a): pass
        def load_uri(self, uri): pass
    h = NetworkErrorHandler(Pogled())
    for brez_virov in (True, False):
        h._brez_virov = lambda: brez_virov
        h.requests = {}
        assert h._metoda("https://trgovina.si/placaj") is None
    h.requests = {"https://trgovina.si/placaj": "POST"}       # kar poda os_splet._novo_okno
    assert h._metoda("https://trgovina.si/placaj") == "POST"


def test_novo_okno_in_okno_aplikacije_dobita_metodo_odpiralca():
    """OpenAI pregled 1.0.129: zavihek in pojavno okno vdelane aplikacije (target=_blank, window.open) dobita metodo
    zahteve odpiralca - GET ohrani samodejno ponovitev, POST je nima."""
    import types
    import core.os_splet as os_splet
    for metoda in ("GET", "POST"):
        nov = types.SimpleNamespace(_safeer_napake=types.SimpleNamespace(requests={}))
        zahteva = types.SimpleNamespace(get_uri=lambda: "https://a.si/x", get_http_method=lambda m=metoda: m)
        os_splet._metoda_odpiralca(nov, types.SimpleNamespace(get_request=lambda z=zahteva: z))
        assert nov._safeer_napake.requests == {"https://a.si/x": metoda}
    os_splet._metoda_odpiralca(nov, None)                     # brez dejanja: nic, brez napake
    import inspect
    assert "_metoda_odpiralca(nov, dejanje)" in inspect.getsource(os_splet.VdelaniSplet._okno_aplikacije)
    assert "_metoda_odpiralca(nov, dejanje)" in inspect.getsource(os_splet.VdelaniSplet._novo_okno)
