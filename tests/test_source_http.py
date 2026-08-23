from __future__ import annotations

import httpx
import pytest

from flagwatch.fetching import ResponseTooLargeError, UnsafeUrlError
from flagwatch.sources.http import (
    ApiAuthenticationError,
    ApiRateLimitError,
    ApiResponseError,
    GuardedJsonClient,
)


def public_resolver(_host: str) -> list[str]:
    return ["93.184.216.34"]


def test_reads_json_with_bounded_authorization() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"success": True, "data": []},
        )

    client = GuardedJsonClient(
        base_url="https://ctf.example/api/v1/",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        resolver=public_resolver,
        token="super-secret",
        auth_scheme="Token",
    )

    payload = client.get_json("challenges", params={"page": 2})

    assert payload == {"success": True, "data": []}
    assert requests[0].url == "https://ctf.example/api/v1/challenges?page=2"
    assert requests[0].headers["authorization"] == "Token super-secret"


def test_rejects_absolute_paths_and_private_origins() -> None:
    client = GuardedJsonClient(
        base_url="https://ctf.example/api/v1/",
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(200))),
        resolver=lambda _host: ["127.0.0.1"],
    )

    with pytest.raises(UnsafeUrlError):
        client.get_json("https://evil.example/data")

    with pytest.raises(UnsafeUrlError):
        client.get_json("challenges")


def test_rejects_redirects_instead_of_leaking_authorization() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"location": "https://evil.example/steal"})

    client = GuardedJsonClient(
        base_url="https://ctf.example/api/v1/",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        resolver=public_resolver,
        token="super-secret",
    )

    with pytest.raises(ApiResponseError, match="redirect") as captured:
        client.get_json("challenges")

    assert "super-secret" not in str(captured.value)
    assert len(requests) == 1


def test_rejects_oversized_or_non_json_responses() -> None:
    oversized = GuardedJsonClient(
        base_url="https://ctf.example/api/v1/",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    headers={"content-type": "application/json"},
                    content=b"{" + b"x" * 64 + b"}",
                )
            )
        ),
        resolver=public_resolver,
        max_bytes=32,
    )
    non_json = GuardedJsonClient(
        base_url="https://ctf.example/api/v1/",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    headers={"content-type": "text/html"},
                    text="<h1>secret error body</h1>",
                )
            )
        ),
        resolver=public_resolver,
    )

    with pytest.raises(ResponseTooLargeError):
        oversized.get_json("challenges")
    with pytest.raises(ApiResponseError, match="JSON content type") as captured:
        non_json.get_json("challenges")
    assert "secret error body" not in str(captured.value)


@pytest.mark.parametrize(
    ("status", "error_type"),
    [(401, ApiAuthenticationError), (403, ApiAuthenticationError), (429, ApiRateLimitError)],
)
def test_categorizes_remote_failures_without_response_bodies(status, error_type) -> None:
    client = GuardedJsonClient(
        base_url="https://ctf.example/api/v1/",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(status, text="private remote detail")
            )
        ),
        resolver=public_resolver,
    )

    with pytest.raises(error_type) as captured:
        client.get_json("challenges")

    assert "private remote detail" not in str(captured.value)


def test_rejects_invalid_json_without_echoing_it() -> None:
    client = GuardedJsonClient(
        base_url="https://ctf.example/api/v1/",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    headers={"content-type": "application/problem+json"},
                    content=b'{"token":"secret"',
                )
            )
        ),
        resolver=public_resolver,
    )

    with pytest.raises(ApiResponseError, match="valid JSON") as captured:
        client.get_json("challenges")

    assert "secret" not in str(captured.value)
