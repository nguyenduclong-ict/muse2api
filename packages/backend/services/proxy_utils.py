"""Proxy parsing, normalization, and ipinfo.io health checking."""
from __future__ import annotations

import time
import urllib.parse
from typing import Any

import requests

from muse_wss import requests_proxies


def parse_proxy_line(raw: str) -> tuple[str, str]:
    """Parse URL, host:port, host:port:user:pass, or user:pass@host:port into (proxy_url, scheme)."""
    s = (raw or "").strip()
    if not s or s.startswith("#"):
        raise ValueError("Empty or comment line")

    if "://" in s:
        p = urllib.parse.urlparse(s)
        scheme = (p.scheme or "").lower()
        if scheme not in ("http", "https", "socks5", "socks5h", "socks4") or not p.hostname or not p.port:
            raise ValueError(f"Invalid proxy URL: {s}")
        return s, scheme

    if "@" in s:
        url = f"http://{s}"
        p = urllib.parse.urlparse(url)
        if not p.hostname or not p.port:
            raise ValueError(f"Invalid proxy format: {s}")
        return url, "http"

    parts = s.split(":")
    if len(parts) == 2:
        host, port_str = parts
        port = int(port_str)
        return f"http://{host.strip()}:{port}", "http"
    if len(parts) == 4:
        host, port_str, user, pwd = parts
        port = int(port_str)
        u = urllib.parse.quote(user.strip(), safe="")
        pw = urllib.parse.quote(pwd.strip(), safe="")
        return f"http://{u}:{pw}@{host.strip()}:{port}", "http"

    raise ValueError(f"Unsupported proxy format: {s}")


def check_proxy_ipinfo(proxy_url: str, timeout: float = 15.0) -> dict[str, Any]:
    t0 = time.time()
    try:
        r = requests.get(
            "https://ipinfo.io/json",
            proxies=requests_proxies(proxy_url),
            timeout=timeout,
        )
        latency_ms = int((time.time() - t0) * 1000)
        if r.status_code != 200:
            return {"ok": False, "status": "dead", "latency_ms": latency_ms, "error": f"ipinfo HTTP {r.status_code}"}
        data = r.json()
        return {
            "ok": True,
            "status": "alive",
            "ip": data.get("ip", ""),
            "country": data.get("country", ""),
            "city": data.get("city", ""),
            "org": data.get("org", ""),
            "latency_ms": latency_ms,
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "dead",
            "latency_ms": int((time.time() - t0) * 1000),
            "error": str(exc)[:300],
        }
