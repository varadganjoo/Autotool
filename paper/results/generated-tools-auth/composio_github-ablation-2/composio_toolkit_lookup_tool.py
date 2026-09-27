import html
import json
import os
import re
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("composio_toolkit_lookup_tool")
COMPOSIO_API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://composio.dev").rstrip("/")


def _find_counts(value: Any, path: str = "page data") -> list[tuple[int, str]]:
    """Find explicit toolkit/action counts and action lists in embedded page data."""
    found: list[tuple[int, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            normalized = key_text.lower().replace("_", "").replace("-", "")
            child_path = f"{path}.{key_text}"
            if (
                isinstance(child, (int, float))
                and not isinstance(child, bool)
                and re.search(r"(?:tool|action).*(?:count|total)|(?:count|total).*(?:tool|action)", normalized)
            ):
                found.append((int(child), f"{child_path} = {int(child)}"))
            elif (
                isinstance(child, list)
                and re.fullmatch(r"(?:available)?(?:tools|actions)", normalized)
            ):
                named_items = [
                    item for item in child
                    if isinstance(item, str)
                    or (isinstance(item, dict) and any(k in item for k in ("name", "slug", "key", "tool_name")))
                ]
                if len(named_items) == len(child):
                    found.append((len(child), f"{child_path} contains {len(child)} listed items"))
            found.extend(_find_counts(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_find_counts(child, f"{path}[{index}]"))
    return found


@mcp.tool()
def lookup_composio_toolkit(toolkit_name: str) -> str:
    """Look up a toolkit's official Composio page and any publicly stated action count.

    Args:
        toolkit_name: Toolkit name or slug, for example "GitHub" or "google-sheets".
    """
    name = toolkit_name.strip()
    if not name:
        raise ValueError("toolkit_name must not be empty")
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    page_url = f"{COMPOSIO_API_BASE}/toolkits/{slug}"

    with httpx.Client(timeout=10.0, follow_redirects=True, headers={"User-Agent": "ComposioToolkitLookup/1.0"}) as client:
        response = client.get(page_url)
        response.raise_for_status()

    source_html = response.text
    visible_text = html.unescape(re.sub(r"(?is)<(script|style|noscript)\b[^>]*>.*?</\1>", " ", source_html))
    visible_text = re.sub(r"(?s)<[^>]+>", " ", visible_text)
    visible_text = re.sub(r"\s+", " ", visible_text).strip()

    evidence: list[dict[str, str]] = []
    counts: list[tuple[int, str]] = []

    # Prefer explicit, human-readable count statements present on the official page.
    count_patterns = (
        re.compile(r"\b([\d,]+)\s+(?:available\s+)?(?:tools|actions)\b", re.I),
        re.compile(r"\b(?:tools|actions)\s*[:(]\s*([\d,]+)\b", re.I),
    )
    for pattern in count_patterns:
        for match in pattern.finditer(visible_text):
            count = int(match.group(1).replace(",", ""))
            snippet = visible_text[max(0, match.start() - 100):min(len(visible_text), match.end() + 100)]
            counts.append((count, snippet))

    # Also inspect embedded JSON used by the official site to render toolkit metadata.
    for index, match in enumerate(re.finditer(r"(?is)<script\b[^>]*>(.*?)</script>", source_html)):
        script = match.group(1).strip()
        if not script:
            continue
        try:
            data = json.loads(script)
        except (json.JSONDecodeError, TypeError):
            continue
        for count, detail in _find_counts(data):
            counts.append((count, detail))

    # Remove duplicate evidence while preserving order. Do not infer a count from unrelated text.
    unique_counts: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for item in counts:
        if item not in seen:
            unique_counts.append(item)
            seen.add(item)

    if unique_counts:
        # A toolkit page may expose the same count in metadata and visible copy; use the first
        # explicit count and retain all corroborating snippets/locations in the response.
        available_tool_count: Optional[int] = unique_counts[0][0]
        for count, detail in unique_counts:
            evidence.append({"source_url": page_url, "snippet": detail})
    else:
        available_tool_count = None
        evidence.append({
            "source_url": page_url,
            "snippet": "The official toolkit page loaded, but it did not expose a verifiable numeric tools/actions count in its page text or embedded JSON. No count was guessed.",
        })

    result = {
        "toolkit": name,
        "official_page_url": page_url,
        "available_tool_count": available_tool_count,
        "sources": evidence,
    }
    return json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
