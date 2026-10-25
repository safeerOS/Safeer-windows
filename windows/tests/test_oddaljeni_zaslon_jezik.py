import pytest

pytest.importorskip("PySide6")
from safeer_windows import oddaljeni_zaslon as oz  # noqa: E402


def test_besedila_v_vseh_jezikih_imajo_iste_kljuce():
    kljuci = set(oz._BESEDILA["en"])
    for jezik, besedila in oz._BESEDILA.items():
        assert set(besedila) == kljuci, jezik


def test_nastavi_jezik_in_nadomestni_anglescina():
    oz.nastavi_jezik("en-GB")
    assert oz._b("znova") == "Reconnect"
    assert oz._b("naslov", ime="Linux PC") == "Remote screen – Linux PC"
    oz.nastavi_jezik("ja")
    assert oz._b("okno") == "Window"
    oz.nastavi_jezik("sl")
    assert oz._b("koncala") == "Naprava je končala povezavo."


def test_sporocilo_brez_naslova_imenuje_napravo_v_vseh_jezikih():
    for jezik in oz._BESEDILA:
        oz.nastavi_jezik(jezik)
        besedilo = oz._b("ni_doma", ime="Linux PC")
        assert besedilo.startswith("Linux PC ") and "Global Link" in besedilo, jezik
    oz.nastavi_jezik("sl")


def test_sporocilo_nedosegljive_naprave_imenuje_napravo_v_vseh_jezikih():
    for jezik in oz._BESEDILA:
        oz.nastavi_jezik(jezik)
        besedilo = oz._b("ni_dosegljiv", ime="Linux PC")
        assert "Linux PC" in besedilo and "{" not in besedilo, jezik
    oz.nastavi_jezik("sl")


def test_obvestila_naprave_so_stavki_v_vseh_jezikih():
    for jezik in oz._BESEDILA:
        oz.nastavi_jezik(jezik)
        for razlog in ("ni_okna", "zaprto", "na_namizju"):
            besedilo = oz.besedilo_obvestila("konec", razlog)
            assert besedilo and "_" not in besedilo and "{" not in besedilo, (jezik, razlog)
        assert "Claude" in oz.besedilo_obvestila("konec", "na_namizju", "Claude"), jezik
        assert "Claude" in oz.besedilo_obvestila("program", "caka", "Claude"), jezik
        assert "{" not in oz.besedilo_obvestila("program", "caka"), jezik
        assert oz.besedilo_obvestila("konec", "neznano") == oz._b("koncala"), jezik
    oz.nastavi_jezik("sl")
    assert oz.besedilo_obvestila("konec", "na_namizju", "Claude") == \
        "Claude je že odprt na namizju računalnika – prikazujem namizje ..."
