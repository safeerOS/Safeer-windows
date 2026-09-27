from unittest import mock

from core import link_hub
from safeer_windows import control_backend


def _odgovor_vabila(**dodatno):
    odgovor = {
        "qr_id": "qr-1",
        "secret": "skrivnost",
        "fp": "aabb",
        "web_port": 8991,
        "expires_in_seconds": 287,
    }
    odgovor.update(dodatno)
    return odgovor


def test_povabi_vrne_pin_iz_istega_odgovora_kot_qr():
    with mock.patch.object(link_hub, "_zahteva", return_value=(200, _odgovor_vabila(pin="907 870"))):
        vabilo = link_hub.povabi("wss://192.168.1.8:8990/cast/ws", "zeton", "aabb")

    assert vabilo["pin"] == "907870"
    assert vabilo["velja"] == 287
    assert vabilo["qr_id"] == "qr-1"
    assert "#j=qr-1&s=skrivnost" in vabilo["povezava"]


def test_povabi_sprejme_code_in_staro_sredisce_brez_pina():
    with mock.patch.object(link_hub, "_zahteva", return_value=(200, _odgovor_vabila(code="123456"))):
        assert link_hub.povabi("wss://hub.test:8990/cast/ws", "z", "fp")["pin"] == "123456"

    with mock.patch.object(link_hub, "_zahteva", return_value=(200, _odgovor_vabila())):
        assert link_hub.povabi("wss://hub.test:8990/cast/ws", "z", "fp")["pin"] == ""


def test_windows_vabilo_poslje_svg_veljavnost_in_pin_skupaj():
    backend = control_backend.SafeerControlBackend.__new__(control_backend.SafeerControlBackend)
    backend._vabilo = None
    backend._vabilo_rod = 0
    dogodki = []

    with mock.patch.object(backend, "hub_url", return_value="wss://hub.test:8990/cast/ws"), \
         mock.patch.object(backend, "zeton", return_value="zeton"), \
         mock.patch.object(backend, "hub_fp", return_value="aabb"), \
         mock.patch.object(backend, "_oddaj_dogodek", side_effect=lambda vrsta, podatki: dogodki.append((vrsta, podatki))), \
         mock.patch.object(backend, "zacni_vabilo"), \
         mock.patch.object(link_hub, "povabi", return_value={
             "qr_id": "qr-1", "povezava": "https://safeer.si/p#j=qr-1", "velja": 300, "pin": "907870"
         }), \
         mock.patch.object(link_hub, "qr_svg", return_value="<svg>qr</svg>"), \
         mock.patch.object(link_hub, "stanje_vabila", return_value={"caka": False, "pridruzen": ""}), \
         mock.patch.object(control_backend.time, "sleep", return_value=None):
        backend._zacni_vabilo()

    assert dogodki[0] == ("vabilo", {"svg": "<svg>qr</svg>", "velja": 300, "pin": "907870"})


def test_windows_po_pridruzitvi_pokaze_ime_in_pripravi_novo_vabilo():
    backend = control_backend.SafeerControlBackend.__new__(control_backend.SafeerControlBackend)
    backend._vabilo = None
    backend._vabilo_rod = 0
    dogodki = []

    with mock.patch.object(backend, "hub_url", return_value="wss://hub.test:8990/cast/ws"), \
         mock.patch.object(backend, "zeton", return_value="zeton"), \
         mock.patch.object(backend, "hub_fp", return_value="aabb"), \
         mock.patch.object(backend, "_oddaj_dogodek", side_effect=lambda vrsta, podatki: dogodki.append((vrsta, podatki))), \
         mock.patch.object(backend, "zacni_vabilo") as nova, \
         mock.patch.object(link_hub, "povabi", return_value={
             "qr_id": "qr-1", "povezava": "https://safeer.si/p#j=qr-1", "velja": 300, "pin": "907870"
         }), \
         mock.patch.object(link_hub, "qr_svg", return_value="<svg>qr</svg>"), \
         mock.patch.object(link_hub, "stanje_vabila", return_value={"caka": False, "pridruzen": "Telefon"}), \
         mock.patch.object(control_backend.time, "sleep", return_value=None):
        backend._zacni_vabilo()

    assert dogodki[-1] == ("vabilo", {"pridruzen": "Telefon"})
    nova.assert_called_once_with()
