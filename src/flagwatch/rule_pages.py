from __future__ import annotations

import re
from xml.etree import ElementTree
from urllib.parse import urldefrag, urljoin, urlsplit

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


def extract_readable_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for element in soup.select("script, style, form, nav, footer, svg, noscript, template"):
        element.decompose()
    container = soup.find("main") or soup.find("article") or soup.body or soup
    lines = [re.sub(r"\s+", " ", line).strip() for line in container.get_text("\n").splitlines()]
    readable = "\n".join(line for line in lines if line)
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
        element = soup.select_one(selector)
        if element and element.get("content"):
            value = re.sub(r"\s+", " ", str(element["content"])).strip()
            if value and value not in metadata:
                metadata.append(value)
    return "\n".join(metadata)


def discover_rule_links(base_url: str, html: str, limit: int = 6) -> list[str]:
    base = urlsplit(base_url)
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        absolute, _fragment = urldefrag(urljoin(base_url, href))
        parsed = urlsplit(absolute)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != base.netloc:
            continue
        searchable = f"{anchor.get_text(' ', strip=True)} {parsed.path}".lower()
        if not any(keyword in searchable for keyword in RULE_KEYWORDS):
            continue
        if absolute not in links:
            links.append(absolute)
        if len(links) == limit:
            break
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
