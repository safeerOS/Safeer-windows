from unittest import mock

from safeer_windows import policy


def test_najvecja_ikona_iz_glave_strani():
    p = policy._IkonePovezave()
    p.feed('<head><link rel="icon" href="/f16.png" sizes="16x16">'
           '<link rel="apple-touch-icon" href="/touch.png"><link rel="icon" type="image/svg+xml" href="/l.svg"></head>')
    najboljsa = sorted(p.ikone, key=lambda x: -x[0])[0][1]
    assert najboljsa == "/l.svg"


def test_ikona_je_data_url_s_iste_strani():
    klici = []

    def prenesi(url, meja, cas=6.0):
        klici.append(url)
        if url == "https://primer.si":
            return b'<link rel="apple-touch-icon" href="/t.png">', "text/html"
        return b"\x89PNG\r\n\x1a\nxx", "image/png"

    with mock.patch.object(policy, "_prenesi", prenesi):
        ikona = policy.ikona_strani("https://primer.si")
    assert ikona.startswith("data:image/png;base64,")
    assert all(u.startswith("https://primer.si") for u in klici)   # nobene tuje storitve za ikone


def test_brez_ikone_ne_pade():
    with mock.patch.object(policy, "_prenesi", side_effect=OSError("ni omrezja")):
        assert policy.ikona_strani("https://primer.si") == ""
    assert policy.ikona_strani("javascript:alert(1)") == ""
