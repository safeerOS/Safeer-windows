import pytest

pytest.importorskip("PySide6")

from unittest import mock

from safeer_windows import os_app  # noqa: E402


def test_nastavitev_in_okolje_imata_prednost_pred_sistemom():
    with mock.patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("SAFEER_OS_JEZIK", None)
        assert os_app._jezik_vmesnika({"jezik": "en"}) == "en"
        assert os_app._jezik_vmesnika({"jezik": "sl"}) == "sl"
    with mock.patch.dict("os.environ", {"SAFEER_OS_JEZIK": "en"}):
        assert os_app._jezik_vmesnika({"jezik": "sl"}) == "en"


def test_brez_nastavitve_jezik_sistema():
    with mock.patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("SAFEER_OS_JEZIK", None)
        with mock.patch.object(os_app.policy, "ui_language", return_value="en"):
            assert os_app._jezik_vmesnika({}) == "en"
        with mock.patch.object(os_app.policy, "ui_language", return_value="sl"):
            assert os_app._jezik_vmesnika({"jezik": "xx"}) == "sl"
