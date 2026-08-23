from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from flagwatch.fetching import (
    Resolver,
    ResponseTooLargeError,
    UnsafeUrlError,
    resolve_public_addresses,
    validate_public_url,
)


class ApiError(RuntimeError):
    pass


class ApiAuthenticationError(ApiError):
    pass


class ApiRateLimitError(ApiError):
    pass


class ApiResponseError(ApiError):
    pass


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url)
    return parsed.scheme.casefold(), (parsed.hostname or "").casefold(), parsed.port


class GuardedJsonClient:
    def __init__(
        self,
        *,
        base_url: str,
        client: httpx.Client | None = None,
        resolver: Resolver = resolve_public_addresses,
        token: str | None = None,
        auth_scheme: str = "Bearer",
        max_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise UnsafeUrlError("API base URL must use HTTP or HTTPS")
        if parsed.username or parsed.password:
            raise UnsafeUrlError("API base URL cannot contain credentials")
        self.base_url = base_url.rstrip("/") + "/"
        self.client = client or httpx.Client(timeout=10.0)
        self.resolver = resolver
        self.token = token
        self.auth_scheme = auth_scheme.strip()
        self.max_bytes = max_bytes

    def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
    ) -> Any:
        parsed_path = urlsplit(path)
        if parsed_path.scheme or parsed_path.netloc or path.startswith("//"):
            raise UnsafeUrlError("API paths must be relative to the configured origin")
        url = urljoin(self.base_url, path.lstrip("/"))
        if _origin(url) != _origin(self.base_url):
            raise UnsafeUrlError("API path escaped the configured origin")
        validate_public_url(url, self.resolver)

        headers = {
            "Accept": "application/json",
            "User-Agent": "Flagwatch/0.2 read-only CTF intelligence",
        }
        if self.token:
            headers["Authorization"] = f"{self.auth_scheme} {self.token}"
        response = self.client.get(url, params=params, headers=headers, follow_redirects=False)

        if 300 <= response.status_code < 400:
            raise ApiResponseError("API redirects are not allowed")
        if response.status_code in {401, 403}:
            raise ApiAuthenticationError(
                f"API authorization failed with HTTP {response.status_code}"
            )
        if response.status_code == 429:
            raise ApiRateLimitError("API rate limit was reached")
        if response.status_code >= 400:
            raise ApiResponseError(f"API request failed with HTTP {response.status_code}")

        declared_length = response.headers.get("content-length")
        if declared_length and declared_length.isdigit() and int(declared_length) > self.max_bytes:
            raise ResponseTooLargeError("API response exceeds the size limit")
        if len(response.content) > self.max_bytes:
            raise ResponseTooLargeError("API response exceeds the size limit")

        media_type = response.headers.get("content-type", "").split(";", 1)[0].casefold()
        if media_type != "application/json" and not media_type.endswith("+json"):
            raise ApiResponseError("API response did not use a JSON content type")
        try:
            return json.loads(response.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ApiResponseError("API response was not valid JSON") from error
