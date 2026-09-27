import json
import os
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("parcelly_answer_tool")
REQUIRED_ENV = ["PARCELLY_USERNAME", "PARCELLY_PASSWORD"]
API_BASE = os.environ.get("PARCELLY_API_BASE", "http://127.0.0.1:61476/parcelly/api")


def _last_scan_location(data):
    if isinstance(data, dict):
        for key in ("last_scanned", "lastScan", "last_scan", "last_scanned_location", "lastScanLocation"):
            if key in data:
                value = data[key]
                if isinstance(value, dict):
                    for loc_key in ("location", "place", "facility", "city", "name"):
                        if loc_key in value:
                            return str(value[loc_key])
                return str(value)
        events = data.get("events") or data.get("history") or data.get("scans") or data.get("tracking_events")
        if isinstance(events, list) and events:
            event = events[0]
            if isinstance(event, dict):
                for key in ("location", "place", "facility", "city", "scan_location"):
                    if key in event:
                        return str(event[key])
    return json.dumps(data)


@mcp.tool()
def answer_last_scan(number: str) -> str:
    """Fetch tracking information and return the last scan location for a parcel.

    Args:
        number: Parcel tracking number.
    """
    username = os.environ["PARCELLY_USERNAME"]
    password = os.environ["PARCELLY_PASSWORD"]
    with httpx.Client(timeout=10) as client:
        response = client.get(f"{API_BASE}/track/{number}", auth=(username, password))
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError:
            return response.text
        return _last_scan_location(data)


if __name__ == "__main__":
    mcp.run()
