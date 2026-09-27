import json
import os
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("web_search_tool")
GOOGLE_NEWS_API_BASE = os.environ.get(
    "GOOGLE_NEWS_API_BASE", "https://news.google.com/rss/search"
)


class _DescriptionParser(HTMLParser):
    """Extract readable text and links from a Google News RSS description."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_data(self, data: str) -> None:
        cleaned = " ".join(data.split())
        if cleaned:
            self.text_parts.append(cleaned)


def _clean_text(value: str) -> str:
    parser = _DescriptionParser()
    parser.feed(value)
    return " ".join(parser.text_parts)


def _canonical_link(description: str, feed_link: str) -> str:
    parser = _DescriptionParser()
    parser.feed(description)
    for link in parser.links:
        host = (urlparse(link).hostname or "").lower()
        if host and host != "news.google.com" and not host.endswith(".news.google.com"):
            return link
    return feed_link


@mcp.tool()
def search_web(query: str, recency: str = "past month", result_count: int = 5) -> str:
    """Search Google News for recent web articles matching a topic.

    Args:
        query: Topic or keywords to search for; must not be empty.
        recency: Time range, such as "past day", "past week", "past month",
            "past year", or "any time". Unrecognized values raise an error.
        result_count: Maximum number of articles to return, from 1 through 20.

    Returns:
        JSON containing article titles, canonical URLs when available, publication
        dates, sources, and snippets.
    """
    if not query.strip():
        raise ValueError("query must not be empty")
    if not 1 <= result_count <= 20:
        raise ValueError("result_count must be between 1 and 20")

    normalized_recency = re.sub(r"\s+", " ", recency.strip().lower())
    now = datetime.now(timezone.utc)
    recency_durations = {
        "past day": timedelta(days=1),
        "day": timedelta(days=1),
        "past week": timedelta(days=7),
        "week": timedelta(days=7),
        "past month": timedelta(days=30),
        "month": timedelta(days=30),
        "past year": timedelta(days=365),
        "year": timedelta(days=365),
    }
    if normalized_recency in ("any", "any time", "all"):
        search_query = query.strip()
    elif normalized_recency in recency_durations:
        since = (now - recency_durations[normalized_recency]).date().isoformat()
        search_query = f'{query.strip()} after:{since}'
    else:
        raise ValueError("recency must be past day, past week, past month, past year, or any time")

    params = {"q": search_query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        response = client.get(GOOGLE_NEWS_API_BASE, params=params)
        response.raise_for_status()

    root = ET.fromstring(response.content)
    items = root.findall("./channel/item")
    results = []
    for item in items[:result_count]:
        title = item.findtext("title", default="").strip()
        feed_link = item.findtext("link", default="").strip()
        description = item.findtext("description", default="")
        source = item.findtext("source", default="").strip()
        pub_date = item.findtext("pubDate", default="").strip()
        results.append(
            {
                "title": title,
                "canonical_url": _canonical_link(description, feed_link),
                "publication_date": pub_date or None,
                "source": source or None,
                "snippet": _clean_text(description),
            }
        )

    return json.dumps({"query": query, "recency": recency, "results": results}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
