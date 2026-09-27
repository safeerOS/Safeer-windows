import json

import pytest
from safeer_windows.oddaljeni_zaslon_protokol import (
    RazclenjevalnikOkvirjev,
    ZavrnjenaSeja,
    preslikaj_tipko_ime,
    razcleni_odgovor,
)


ODTIS = "12" * 32


def test_razcleni_screen_start_iz_gnezdenega_odgovora_in_naprave():
    seja = razcleni_odgovor(
        {"ok": True, "data": {"port": 4567, "fp": ":".join(["12"] * 32),
                                "token": "enkraten", "v": 2}},
        {"naslov": "192.168.1.24"},
    )
    assert seja.naslov == "192.168.1.24"
    assert seja.vrata == 4567
    assert seja.odtis == ODTIS
    assert seja.zeton == "enkraten"


def test_razcleni_screen_start_pokaze_sporocilo_zavrnitve():
    with pytest.raises(ZavrnjenaSeja, match="Dovoljenje ni potrjeno"):
        razcleni_odgovor({"ok": False, "code": "ni_dovoljeno",
                          "message": "Dovoljenje ni potrjeno."})


def test_okvirji_se_razclenijo_tudi_ce_pridejo_po_delih():
    prvi = b"\x00\x00\x00\x01\x67"
    obvestilo = json.dumps({"konec": "koncano"}).encode()
    tok = bytes([1]) + len(prvi).to_bytes(4, "big") + prvi
    tok += bytes([3]) + len(obvestilo).to_bytes(4, "big") + obvestilo
    r = RazclenjevalnikOkvirjev()
    assert r.dodaj(tok[:3]) == []
    assert r.dodaj(tok[3:8]) == []
    assert r.dodaj(tok[8:]) == [(1, prvi), (3, obvestilo)]


def test_okvir_z_nemogoco_dolzino_je_zavrnjen():
    r = RazclenjevalnikOkvirjev()
    with pytest.raises(ValueError, match="Pokvarjen okvir"):
        r.dodaj(b"\x01\x00\x80\x00\x01")


def test_tipke_vkljucujejo_posebne_modifikatorje_in_sumnike():
    assert preslikaj_tipko_ime("control", "", True) == {
        "vrsta": "tipka_dol", "tipka": "krmilka"}
    assert preslikaj_tipko_ime("control", "", False) == {
        "vrsta": "tipka_gor", "tipka": "krmilka"}
    assert preslikaj_tipko_ime("left", "", True) == {
        "vrsta": "tipka_dol", "tipka": "levo"}
    assert preslikaj_tipko_ime("s", "s", True, ctrl_alt=True) == {
        "vrsta": "tipka_dol", "tipka": "s"}
    assert preslikaj_tipko_ime("", "š", True) == {
        "vrsta": "besedilo", "besedilo": "š"}
