from unittest import mock

from core import link_hub_streznik as s


def test_koda_gre_poslusalcem_v_oknu():
    prejeto = []
    s.POSLUSALCI_KODE.append(lambda ime, koda: prejeto.append((ime, koda)))
    try:
        with mock.patch.object(s, "_obvestilo_kode_windows"), mock.patch("shutil.which", return_value=None):
            s._obvestilo_kode("Telefon", "474046")
    finally:
        s.POSLUSALCI_KODE.pop()
    assert prejeto == [("Telefon", "474046")]
