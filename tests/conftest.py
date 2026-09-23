from pathlib import Path

import pytest

from bodylog import Store, import_chat

FIXTURE = Path(__file__).parent / "fixtures" / "chat.txt"


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


@pytest.fixture
def imported(store):
    """The four fixture sessions; returns (store, session ids)."""
    r = import_chat(store, FIXTURE.read_text())
    return store, r.sessions


HTTP = Path(__file__).parent / "fixtures" / "http"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """No test reaches the internet: every source call fails unless a test installs recorded responses."""
    from bodylog import sources

    def refuse(url, params=None, body=None):
        raise sources.SourceError(f"network disabled in tests: {url}")

    monkeypatch.setattr(sources, "fetch", refuse)
    monkeypatch.delenv("BODYLOG_OFFLINE", raising=False)


@pytest.fixture
def recorded(monkeypatch):
    """Serve recorded API responses: recorded({"kimchi": "fdc_search_kimchi.json", ...}) keyed by the FDC/OFF query
    or barcode. Unlisted requests fail as they would offline. Returns the list of requests made."""
    import json

    from bodylog import sources

    calls = []

    def install(routes: dict):
        def fake(url, params=None, body=None):
            calls.append((url, params, body))
            q = (body or {}).get("query") or (params or {}).get("q") or url.rsplit("/", 1)[-1].removesuffix(".json")
            api = "fdc" if "nal.usda.gov" in url else "off"
            name = routes.get((api, q))
            if not name:
                raise sources.SourceError(f"no recording for {api} {q!r}")
            return json.loads((HTTP / name).read_text())

        monkeypatch.setattr(sources, "fetch", fake)
        return calls

    return install
