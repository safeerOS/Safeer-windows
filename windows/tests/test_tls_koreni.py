"""Koreni za Windows smejo spremeniti le privzeti odhodni HTTPS, nikoli ssl.SSLContext ali create_default_context
(globalni truststore je pokvaril streznik oddaljenega zaslona s pripetim certifikatom)."""
import importlib
import ssl
from unittest import mock


def test_namesti_ne_poseze_v_druge_kontekste():
    from safeer_windows import tls_koreni
    tls_koreni = importlib.reload(tls_koreni)
    prej = (ssl.SSLContext, ssl.create_default_context, ssl._create_default_https_context)
    try:
        with mock.patch.object(tls_koreni.sys, "platform", "win32"):
            nacin = tls_koreni.namesti()
        assert ssl.SSLContext is prej[0]
        assert ssl.create_default_context is prej[1]
        if nacin:
            kontekst = ssl._create_default_https_context()
            assert kontekst.verify_mode == ssl.CERT_REQUIRED and kontekst.check_hostname
    finally:
        ssl._create_default_https_context = prej[2]
