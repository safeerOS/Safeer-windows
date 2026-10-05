"""Odjemalec Safeer Linka na Windows: naslov naprave iz seznama Huba.

Hub programu na svojem racunalniku pripise 127.0.0.1. Kadar smo pripeti na Hub DRUGE naprave, je to naslov tiste
naprave, ne nas - z njim bi se okno oddaljenega zaslona povezalo samo nase (core/link_hub_streznik.naslov_za_povezavo;
isto pravilo kot na Linuxu, tests/test_oddaljeni_zaslon_naslov.py)."""
import os
import tempfile

from safeer_windows import control_backend

SEZNAM = {"type": "cast.devices", "devices": [
    {"id": "tablica", "name": "Tablica", "ip": "127.0.0.1", "capabilities": ["remote"]},
    {"id": "pc-2", "name": "Pisarna", "ip": "192.168.0.135", "capabilities": ["desktop"]},
    {"id": "dalec", "name": "Telefon", "ip": "", "capabilities": ["remote"]},
]}


def _naslovi(hub):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        b = control_backend.SafeerControlBackend(config_pot=os.path.join(td, "link.json"))
        b.nastavitve["hub_url"] = hub
        b._na_sporocilo(SEZNAM)
        return {n["id"]: (n["naslov"], n["ip"]) for n in b.naprave}


def test_zanka_od_huba_drugje_je_naslov_tistega_huba():
    naslovi = _naslovi("wss://192.168.0.87:8990/cast/ws")
    assert naslovi["tablica"] == ("192.168.0.87", "192.168.0.87")
    assert naslovi["pc-2"] == ("192.168.0.135", "192.168.0.135")
    assert naslovi["dalec"] == ("", "")


def test_zanka_od_svojega_huba_ostane():
    naslovi = _naslovi("wss://127.0.0.1:8990/cast/ws")
    assert naslovi["tablica"] == ("127.0.0.1", "127.0.0.1")
    assert naslovi["pc-2"] == ("192.168.0.135", "192.168.0.135")
