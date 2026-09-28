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
