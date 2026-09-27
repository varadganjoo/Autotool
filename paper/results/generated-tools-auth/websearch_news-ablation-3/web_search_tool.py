import email.utils
import html
import json
import os
import re
import xml.etree.ElementTree as ET

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("web_search_tool")
GOOGLE_NEWS_API_BASE = os.environ.get(
    "GOOGLE_NEWS_API_BASE", "https://news.google.com/rss/search"
)
FRESHNESS_PERIODS = {
    "day": "1d",
    "week": "7d",
    "month": "1m",
    "year": "1y",
}


def _clean_html(value: str) -> str:
    """Turn an RSS HTML fragment into readable plain text."""
    text = re.sub(r"<[^>]*>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _publication_timestamp(value: str) -> float:
    """Return a sortable timestamp, placing unparseable dates last."""
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        return parsed.timestamp() if parsed is not None else float("-inf")
    except (TypeError, ValueError, OverflowError):
        return float("-inf")


@mcp.tool()
def search_jwst_articles(
    query: str = "James Webb Space Telescope",
    freshness: str = "month",
    result_limit: int = 10,
) -> str:
    """Search Google News for recent articles about the James Webb Space Telescope.

    Args:
        query: Search terms to combine with the James Webb Space Telescope topic.
        freshness: Recency window: "day", "week", "month", "year", or "any".
        result_limit: Maximum number of articles to return, from 1 to 30.

    Returns:
        A JSON array of article titles, URLs, publication dates, snippets, and sources.
    """
    cleaned_query = query.strip()
    if not cleaned_query:
        raise ValueError("query must not be empty")
    if freshness not in (*FRESHNESS_PERIODS.keys(), "any"):
        raise ValueError('freshness must be "day", "week", "month", "year", or "any"')
    if not 1 <= result_limit <= 30:
        raise ValueError("result_limit must be between 1 and 30")

    # Keep searches focused on JWST while allowing additional user-supplied terms.
    if re.search(r"\b(jwst|james\s+webb)\b", cleaned_query, flags=re.IGNORECASE):
        search_query = cleaned_query
    else:
        search_query = f'"James Webb Space Telescope" {cleaned_query}'
    period = FRESHNESS_PERIODS.get(freshness)
    if period:
        search_query = f"{search_query} when:{period}"

    params = {
        "q": search_query,
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
        "sort": "date",
    }
    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        response = client.get(GOOGLE_NEWS_API_BASE, params=params)
        response.raise_for_status()

    root = ET.fromstring(response.content)
    results = []
    for item in root.findall(".//item"):
        title = _clean_html(item.findtext("title", default=""))
        url = (item.findtext("link", default="") or "").strip()
        publication_date = (item.findtext("pubDate", default="") or "").strip()
        description = item.findtext("description", default="") or ""
        source_element = item.find("source")
        source = _clean_html(source_element.text or "") if source_element is not None else ""
        snippet = _clean_html(description)
        if title and url:
            results.append(
                {
                    "title": title,
                    "url": url,
                    "publication_date": publication_date or None,
                    "snippet": snippet,
                    "source": source or None,
                    "_sort_timestamp": _publication_timestamp(publication_date),
                }
            )

    results.sort(key=lambda item: item["_sort_timestamp"], reverse=True)
    for result in results:
        result.pop("_sort_timestamp", None)
    return json.dumps(results[:result_limit], ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
