import pytest


@pytest.fixture(autouse=True)
def keep_public_media_apis_fake(monkeypatch):
    """Existing MediaCenter unit tests stay deterministic; API tests inject their own fake."""
    from core.zakoniti_viri import ZakonitiViri
    monkeypatch.setattr(ZakonitiViri, "get", lambda self, query="", configured_hosts=None: [])
