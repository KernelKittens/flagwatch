from __future__ import annotations

import httpx
import pytest

from flagwatch.fetching import GuardedFetcher, ResponseTooLargeError, UnsafeUrlError


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.1.2.3", "169.254.169.254", "::1", "fc00::1"],
)
def test_rejects_non_public_destinations(address):
    fetcher = GuardedFetcher(resolver=lambda _host: [address])

    with pytest.raises(UnsafeUrlError):
        fetcher.get_text("https://rules.example/")


def test_revalidates_redirect_before_requesting_target():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})

    fetcher = GuardedFetcher(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        resolver=lambda host: ["93.184.216.34"] if host == "rules.example" else ["127.0.0.1"],
    )

    with pytest.raises(UnsafeUrlError):
        fetcher.get_text("https://rules.example/")

    assert len(requests) == 1


def test_rejects_oversized_response():
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"x" * 33,
        )
    )
    fetcher = GuardedFetcher(
        client=httpx.Client(transport=transport),
        resolver=lambda _host: ["93.184.216.34"],
        max_bytes=32,
    )

    with pytest.raises(ResponseTooLargeError):
        fetcher.get_text("https://rules.example/")


def test_accepts_xml_sitemaps_as_plain_text():
    xml = b'<?xml version="1.0"?><urlset><url><loc>https://rules.example/rules</loc></url></urlset>'
    fetcher = GuardedFetcher(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    headers={"content-type": "application/xml"},
                    content=xml,
                )
            )
        ),
        resolver=lambda _host: ["93.184.216.34"],
    )

    page = fetcher.get_page("https://rules.example/sitemap.xml")

    assert page.text.startswith('<?xml version="1.0"?>')
    assert page.html is None


@pytest.mark.parametrize("media_type", ["application/javascript", "text/javascript"])
def test_accepts_javascript_as_inert_text(media_type):
    source = b'const policy = "We use a strict no-AI policy.";'
    fetcher = GuardedFetcher(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    headers={"content-type": media_type},
                    content=source,
                )
            )
        ),
        resolver=lambda _host: ["93.184.216.34"],
    )

    page = fetcher.get_page("https://ctf.example/assets/app.js")

    assert page.text == source.decode()
