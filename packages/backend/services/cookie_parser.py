"""Cookie parsing and masking utilities."""
from __future__ import annotations

import json
import urllib.parse


def parse_cookies(raw: str) -> dict[str, str]:
    """Parse raw Cookie header string or JSON list/dict into {name: value}."""
    s = (raw or "").strip()
    if not s:
        raise ValueError("Cookie input is empty")

    cookies: dict[str, str] = {}
    if s.startswith("{") or s.startswith("["):
        data = json.loads(s)
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, dict) and "value" in v:
                    cookies[str(k)] = str(v["value"])
                else:
                    cookies[str(k)] = str(v)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("name"):
                    cookies[str(item["name"])] = str(item.get("value", ""))
        else:
            raise ValueError("Unsupported JSON cookie format")
    else:
        if s.lower().startswith("cookie:"):
            s = s.split(":", 1)[1].strip()
        for part in s.split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            k, v = part.split("=", 1)
            k = k.strip()
            v = v.strip()
            if k:
                cookies[k] = v

    if not cookies:
        raise ValueError("No valid cookies found")
    if not any(k in cookies for k in ("hatch_sess", "hatch_vml", "__Host-hatch_one_tap")):
        raise ValueError("Missing required muse.ai session cookie (hatch_sess / hatch_vml)")
    return cookies


def mask_cookies(cookies: dict[str, str]) -> dict[str, str]:
    masked: dict[str, str] = {}
    for k, v in cookies.items():
        if len(v) <= 10:
            masked[k] = "***"
        else:
            masked[k] = f"{v[:5]}...{v[-4:]}"
    return masked


def mask_proxy(proxy_url: str) -> str:
    p = (proxy_url or "").strip()
    if not p:
        return ""
    parsed = urllib.parse.urlparse(p)
    if not parsed.username and not parsed.password:
        return p
    host_part = f"{parsed.hostname}:{parsed.port}" if parsed.port else (parsed.hostname or "")
    return f"{parsed.scheme}://***:***@{host_part}"
