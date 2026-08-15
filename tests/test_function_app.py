from __future__ import annotations

import importlib.util
from pathlib import Path

import azure.functions as func

ROOT = Path(__file__).parents[1]


def _function_module():
    path = ROOT / "azure-functions" / "function_app.py"
    spec = importlib.util.spec_from_file_location("flagwatch_function_app", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeBlobs:
    def __init__(self, value: bytes | None) -> None:
        self.value = value

    def download(self, _name: str) -> bytes | None:
        return self.value


def test_events_returns_last_good_snapshot_with_cache_headers(monkeypatch) -> None:
    module = _function_module()
    monkeypatch.setattr(module, "blob_store", lambda: FakeBlobs(b'{"events":[]}'))
    request = func.HttpRequest(method="GET", url="https://example.test/api/events", body=b"")

    response = module.events(request)

    assert response.status_code == 200
    assert response.mimetype == "application/json"
    assert response.headers["Cache-Control"] == "public, max-age=300, stale-if-error=86400"
    assert response.get_body() == b'{"events":[]}'


def test_events_returns_generic_503_when_snapshot_is_missing(monkeypatch) -> None:
    module = _function_module()
    monkeypatch.setattr(module, "blob_store", lambda: FakeBlobs(None))
    request = func.HttpRequest(method="GET", url="https://example.test/api/events", body=b"")

    response = module.events(request)

    assert response.status_code == 503
    assert b"storage" not in response.get_body().lower()
    assert b"credential" not in response.get_body().lower()
