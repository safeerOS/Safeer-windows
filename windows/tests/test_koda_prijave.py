"""Koda nove naprave gre v odprto okno programa (poslusalci) in v obvestilo namizja."""
from unittest import mock

from core import link_hub_streznik as s


def test_koda_gre_poslusalcem_v_oknu():
    prejeto = []
    s.POSLUSALCI_KODE.append(lambda ime, koda: prejeto.append((ime, koda)))
    try:
        # Obvestila namizja med preizkusom ne posiljamo (na razvijalcevem racunalniku bi se res pokazalo).
        with mock.patch.object(s, "_obvestilo") as obvestilo:
            s._obvestilo_kode("Telefon", "474046")
    finally:
        s.POSLUSALCI_KODE.pop()
    assert prejeto == [("Telefon", "474046")]
    assert obvestilo.call_count == 1
    assert "474 046" in obvestilo.call_args[0][1]


def test_pokvarjen_poslusalec_ne_ustavi_obvestila():
    def pokvarjen(_ime, _koda):
        raise RuntimeError("okno je zaprto")

    s.POSLUSALCI_KODE.append(pokvarjen)
    try:
        with mock.patch.object(s, "_obvestilo") as obvestilo:
            s._obvestilo_kode("Tablica", "123456")
    finally:
        s.POSLUSALCI_KODE.pop()
    assert obvestilo.call_count == 1


def test_jezik_obvestila_doloci_program():
    with mock.patch.object(s, "JEZIK_OBVESTIL", "sl"):
        assert s._slovensko() is True
        assert s.besedilo_kode("Telefon", "474046", s._slovensko())[1] == "Telefon se želi povezati. Vpiši kodo 474 046"
    with mock.patch.object(s, "JEZIK_OBVESTIL", "en"), mock.patch.dict("os.environ", {"LANG": "sl_SI.UTF-8"}):
        assert s._slovensko() is False              # izbira v programu ima prednost pred jezikom seje


def test_obvestilo_na_windows_ne_gre_po_dbusu():
    poslano = []
    with mock.patch.object(s.sys, "platform", "win32"), \
            mock.patch.object(s, "_obvestilo_windows", lambda naslov, besedilo: poslano.append((naslov, besedilo)) or True), \
            mock.patch.object(s, "_obvestilo_dbus", side_effect=AssertionError("D-Bus na Windows")), \
            mock.patch.object(s.threading, "Thread") as nit:
        s._obvestilo("Safeer Link: nova naprava", "Telefon se želi povezati.")
        nit.call_args.kwargs["target"]()             # telo niti izvedemo tu, da preizkus ne caka nanjo
    assert poslano == [("Safeer Link: nova naprava", "Telefon se želi povezati.")]
