from __future__ import annotations

import re
from collections.abc import Iterator
from urllib.parse import urldefrag, urljoin, urlsplit
from xml.etree import ElementTree

from bs4 import BeautifulSoup

RULE_KEYWORDS = (
    "rules",
    "faq",
    "terms",
    "eligibility",
    "prize",
    "register",
    "conduct",
    "policy",
)

AI_POLICY_TERMS = re.compile(
    r"\b(?:AI|LLMs?|ChatGPT|Claude|Copilot|Gemini)\b|"
    r"\b(?:artificial intelligence|large language models?|generative AI)\b",
)
ABSOLUTE_URL = re.compile(r"https?://[^\s\"'`<>]+", re.IGNORECASE)


def _extract_body_text(soup: BeautifulSoup) -> str:
    container = soup.find("main") or soup.find("article") or soup.body or soup
    lines = [re.sub(r"\s+", " ", line).strip() for line in container.get_text("\n").splitlines()]
    return "\n".join(line for line in lines if line)


def extract_readable_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for element in soup.select("script, style, form, nav, footer, svg, noscript, template"):
        element.decompose()
    readable = _extract_body_text(soup)
    if readable:
        return readable

    metadata: list[str] = []
    if soup.title and soup.title.string:
        metadata.append(re.sub(r"\s+", " ", soup.title.string).strip())
    for selector in (
        'meta[name="description"]',
        'meta[property="og:description"]',
        'meta[name="twitter:description"]',
    ):
        metadata_tag = soup.select_one(selector)
        if metadata_tag and metadata_tag.get("content"):
            value = re.sub(r"\s+", " ", str(metadata_tag["content"])).strip()
            if value and value not in metadata:
                metadata.append(value)
    return "\n".join(metadata)


def has_readable_body(html: str, minimum_characters: int = 40) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    for element in soup.select("script, style, form, nav, footer, svg, noscript, template"):
        element.decompose()
    return len(_extract_body_text(soup)) >= minimum_characters


def discover_rule_links(
    base_url: str,
    html: str,
    limit: int = 6,
    *,
    allow_cross_origin: bool = False,
) -> list[str]:
    base = urlsplit(base_url)
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        absolute, _fragment = urldefrag(urljoin(base_url, href))
        parsed = urlsplit(absolute)
        same_origin = parsed.netloc == base.netloc
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username
            or parsed.password
            or (not same_origin and not (allow_cross_origin and parsed.scheme == "https"))
        ):
            continue
        searchable = f"{anchor.get_text(' ', strip=True)} {parsed.path}".lower()
        if not any(keyword in searchable for keyword in RULE_KEYWORDS):
            continue
        if absolute not in links:
            links.append(absolute)
        if len(links) == limit:
            break
    return links


def discover_script_links(base_url: str, html: str, limit: int = 3) -> list[str]:
    base = urlsplit(base_url)
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for script in soup.find_all("script", src=True):
        absolute, _fragment = urldefrag(urljoin(base_url, str(script["src"]).strip()))
        parsed = urlsplit(absolute)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != base.netloc:
            continue
        if not parsed.path.casefold().endswith((".js", ".mjs")):
            continue
        if absolute not in links:
            links.append(absolute)
        if len(links) == limit:
            break
    return links


def _decode_javascript_string(value: str) -> str:
    def replace_unicode(match: re.Match[str]) -> str:
        try:
            return chr(int(match.group(1), 16))
        except (ValueError, OverflowError):
            return match.group(0)

    decoded = re.sub(r"\\u\{([0-9a-fA-F]{1,6})\}", replace_unicode, value)
    decoded = re.sub(r"\\u([0-9a-fA-F]{4})", replace_unicode, decoded)
    escapes = {
        "\\": "\\",
        '"': '"',
        "'": "'",
        "`": "`",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "b": "\b",
        "f": "\f",
        "/": "/",
    }
    return re.sub(r"\\([\\\"'`nrtbf/])", lambda match: escapes[match.group(1)], decoded)


def _javascript_string_literals(
    source: str,
    max_literal_characters: int = 2048,
) -> Iterator[str]:
    matches: list[tuple[int, str]] = []
    for quote in ('"', "'", "`"):
        escaped_quote = re.escape(quote)
        pattern = re.compile(
            rf"(?={escaped_quote}((?:\\.|[^{escaped_quote}\\])"
            rf"{{0,{max_literal_characters}}}){escaped_quote})",
            re.DOTALL,
        )
        matches.extend(
            (match.start(), _decode_javascript_string(match.group(1)))
            for match in pattern.finditer(source)
        )
    for _position, value in sorted(matches):
        yield value


def extract_javascript_evidence(source: str, limit: int = 24) -> str:
    evidence: list[str] = []
    for literal in _javascript_string_literals(source):
        normalized = re.sub(r"\s+", " ", literal).strip()
        if len(normalized) < 12 or not AI_POLICY_TERMS.search(normalized):
            continue
        if normalized not in evidence:
            evidence.append(normalized)
        if len(evidence) == limit:
            break
    return "\n".join(evidence)


def discover_embedded_rule_links(base_url: str, source: str, limit: int = 6) -> list[str]:
    base = urlsplit(base_url)
    links: list[str] = []
    for literal in _javascript_string_literals(source):
        stripped = literal.strip()
        candidates = ABSOLUTE_URL.findall(stripped)
        if stripped.startswith(("/", "./", "../")):
            candidates.append(stripped)
        for candidate in candidates:
            absolute, _fragment = urldefrag(urljoin(base_url, candidate.rstrip("),.;")))
            parsed = urlsplit(absolute)
            same_origin = parsed.netloc == base.netloc
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.username
                or parsed.password
                or (not same_origin and parsed.scheme != "https")
            ):
                continue
            searchable = f"{parsed.path} {parsed.query}".casefold()
            if not any(keyword in searchable for keyword in RULE_KEYWORDS):
                continue
            if absolute not in links:
                links.append(absolute)
            if len(links) == limit:
                return links
    return links


def discover_sitemap_rule_links(base_url: str, xml: str, limit: int = 6) -> list[str]:
    base = urlsplit(base_url)
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return []

    links: list[str] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1].casefold() != "loc" or not element.text:
            continue
        absolute, _fragment = urldefrag(urljoin(base_url, element.text.strip()))
        parsed = urlsplit(absolute)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != base.netloc:
            continue
        if not any(keyword in parsed.path.casefold() for keyword in RULE_KEYWORDS):
            continue
        if absolute not in links:
            links.append(absolute)
        if len(links) == limit:
            break
    return links
