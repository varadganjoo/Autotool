import json
import os
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("composio_toolkit_info_tool")
COMPOSIO_API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://composio.dev").rstrip("/")


class _PageParser(HTMLParser):
    """Collect page text, heading text, and JSON-like script contents."""

    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []
        self.script_parts: list[str] = []
        self._in_script = False
        self._in_h1 = False
        self.h1_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "script":
            self._in_script = True
        elif tag.lower() == "h1":
            self._in_h1 = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script":
            self._in_script = False
        elif tag.lower() == "h1":
            self._in_h1 = False

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self.script_parts.append(data)
        else:
            self.text_parts.append(data)
            if self._in_h1:
                self.h1_parts.append(data)


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _verified_data(documents: list[Any], page_text: str, slug: str) -> tuple[str | None, int | None]:
    matching_objects: list[dict[str, Any]] = []
    all_objects: list[dict[str, Any]] = []
    for document in documents:
        for obj in _walk(document):
            all_objects.append(obj)
            identity_values = [obj.get(key) for key in ("slug", "toolkit_slug", "app", "id")]
            if any(isinstance(value, str) and value.lower() == slug.lower() for value in identity_values):
                matching_objects.append(obj)

    name: str | None = None
    for obj in matching_objects:
        for key in ("display_name", "name", "title"):
            value = obj.get(key)
            if isinstance(value, str) and value.strip() and value.lower() != slug.lower():
                name = value.strip()
                break
        if name:
            break

    # Prefer an explicit exact count or a tool/action array belonging to the
    # requested toolkit, rather than inferring a count from unrelated page data.
    exact_count: int | None = None
    count_keys = {"toolcount", "actioncount", "totaltools", "totalactions", "numberoftools", "numberofactions"}
    list_keys = {"tools", "actions"}
    for obj in matching_objects:
        for key, value in obj.items():
            normalized_key = _norm(key)
            if normalized_key in count_keys and isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                exact_count = value
                break
            if normalized_key in list_keys and isinstance(value, list):
                exact_count = len(value)
                break
        if exact_count is not None:
            break

    # Some public toolkit pages serialize their toolkit data without repeating
    # its slug inside the serialized object. Accept a single unambiguous action
    # or tool list only when its entries have recognizable names.
    if exact_count is None:
        candidates: list[int] = []
        for obj in all_objects:
            for key, value in obj.items():
                if _norm(key) not in list_keys or not isinstance(value, list) or not value:
                    continue
                if all(isinstance(item, dict) and any(
                    isinstance(item.get(field), str) and item.get(field).strip()
                    for field in ("name", "slug", "title", "action")
                ) for item in value):
                    candidates.append(len(value))
        if candidates and len(set(candidates)) == 1:
            exact_count = candidates[0]

    if exact_count is None:
        # A displayed exact count is also verifiable. Deliberately reject
        # abbreviated or approximate labels such as "100+ tools".
        displayed = re.findall(r"(?<![\w+])([0-9][0-9,]*)\s+(?:tools|actions)\b", page_text, flags=re.IGNORECASE)
        values = {int(value.replace(",", "")) for value in displayed}
        if len(values) == 1:
            exact_count = values.pop()

    return name, exact_count


@mcp.tool()
def get_composio_toolkit_info(toolkit_slug: str) -> str:
    """Look up a Composio toolkit's publicly listed name and exact tool count.

    Fetches the public Composio toolkit page and reports a count only when an
    exact count or complete listed tool/action array can be verified.

    Args:
        toolkit_slug: Composio toolkit slug, such as ``github``.
    """
    slug = toolkit_slug.strip()
    if not slug:
        raise ValueError("toolkit_slug must not be empty")

    source_url = f"{COMPOSIO_API_BASE}/toolkits/{quote(slug, safe='') }"
    with httpx.Client(timeout=10.0, follow_redirects=True, headers={"User-Agent": "composio-toolkit-info-mcp/1.0"}) as client:
        response = client.get(source_url)
        response.raise_for_status()

    parser = _PageParser()
    parser.feed(response.text)
    page_text = " ".join(parser.text_parts)
    documents: list[Any] = []
    try:
        documents.append(response.json())
    except (ValueError, json.JSONDecodeError):
        pass
    for content in parser.script_parts:
        candidate = content.strip()
        if not candidate:
            continue
        try:
            documents.append(json.loads(candidate))
        except (ValueError, json.JSONDecodeError):
            # Next.js flight data may contain JSON fragments surrounded by JS.
            # Extract only complete object/array-shaped fragments and parse them
            # as JSON; never evaluate script content.
            for match in re.finditer(r"(?:^|\s)(\{.*\}|\[.*\])(?:\s|$)", candidate, flags=re.DOTALL):
                try:
                    documents.append(json.loads(match.group(1)))
                except (ValueError, json.JSONDecodeError):
                    continue

    name, count = _verified_data(documents, page_text, slug)
    if name is None and parser.h1_parts:
        heading = " ".join(" ".join(parser.h1_parts).split()).strip()
        if heading:
            name = heading

    if count is None:
        raise ValueError(f"Could not verify an exact tool/action count for Composio toolkit '{slug}' from {source_url}")
    if name is None:
        raise ValueError(f"Verified a tool/action count for '{slug}', but could not verify the toolkit name from {source_url}")

    result = {
        "toolkit_name": name,
        "tool_count": count,
        "source_url": str(response.url),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }
    return json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
