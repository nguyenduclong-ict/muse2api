"""SSRF-safe reference media loader for /v1/* endpoints."""
from __future__ import annotations

import base64
import ipaddress
import mimetypes
import os
import socket
import urllib.parse
from typing import Any

import requests

from config import Config

MAX_REF_ITEMS = 10
MAX_ITEM_BYTES = 40 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024


class RefMediaError(ValueError):
    """Raised when a reference media input is invalid or blocked by SSRF policy."""


def _is_forbidden_ip(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _validate_public_url(url: str, allow_private: bool) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise RefMediaError(f"Unsupported reference URL scheme: {parsed.scheme!r}")
    if allow_private:
        return
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise RefMediaError(f"DNS resolution failed for reference host: {exc}") from exc
    if not infos:
        raise RefMediaError("No addresses resolved for reference host")
    for info in infos:
        addr = info[4][0]
        if _is_forbidden_ip(addr):
            raise RefMediaError(f"Reference URL resolves to forbidden private/internal IP: {addr}")


def _fetch_public_url(url: str, cfg: Config) -> tuple[bytes, str]:
    _validate_public_url(url, allow_private=cfg.ref_image_private_fetch)
    r = requests.get(url, timeout=30.0, allow_redirects=False, stream=True)
    if r.status_code in (301, 302, 303, 307, 308):
        raise RefMediaError("Redirects are disabled when fetching reference URLs")
    if r.status_code != 200:
        raise RefMediaError(f"Reference URL returned HTTP {r.status_code}")

    chunks = bytearray()
    for chunk in r.iter_content(chunk_size=65536):
        if not chunk:
            continue
        chunks.extend(chunk)
        if len(chunks) > MAX_ITEM_BYTES:
            raise RefMediaError("Reference media exceeds 40 MiB per-item limit")
    mime = (r.headers.get("Content-Type") or "").split(";", 1)[0].strip()
    if not mime:
        mime = mimetypes.guess_type(urllib.parse.urlparse(url).path)[0] or "image/png"
    return bytes(chunks), mime


def decode_reference_item(raw: Any, cfg: Config) -> tuple[bytes, str]:
    """Decode a single reference (data URL, http(s) URL, raw base64, or optional local path)."""
    if isinstance(raw, dict):
        raw = raw.get("url") or raw.get("image_url") or raw.get("b64_json") or ""
        if isinstance(raw, dict):
            raw = raw.get("url") or ""
    if not isinstance(raw, str) or not raw.strip():
        raise RefMediaError("Empty reference media item")

    s = raw.strip()
    if s.startswith("data:"):
        hdr, _, b64 = s.partition(",")
        mime = "image/png"
        if ";" in hdr:
            mime = hdr[5:].split(";", 1)[0] or mime
        try:
            data = base64.b64decode(b64)
        except Exception as exc:
            raise RefMediaError("Invalid base64 data URL") from exc
        if len(data) > MAX_ITEM_BYTES:
            raise RefMediaError("Reference media exceeds 40 MiB per-item limit")
        return data, mime

    if s.startswith(("http://", "https://")):
        return _fetch_public_url(s, cfg)

    # Check if local file path
    if os.path.sep in s or "/" in s or (len(s) > 2 and s[1] == ":"):
        if os.path.isfile(s):
            if not cfg.ref_image_local_files:
                raise RefMediaError("Local file paths are disabled for reference media")
            if os.path.getsize(s) > MAX_ITEM_BYTES:
                raise RefMediaError("Reference file exceeds 40 MiB per-item limit")
            with open(s, "rb") as f:
                data = f.read()
            mime = mimetypes.guess_type(s)[0] or "application/octet-stream"
            return data, mime

    # Fallback: raw base64 string
    try:
        data = base64.b64decode(s, validate=True)
    except Exception as exc:
        raise RefMediaError("Invalid reference media value (expected URL, data URL, or base64)") from exc
    if len(data) > MAX_ITEM_BYTES:
        raise RefMediaError("Reference media exceeds 40 MiB per-item limit")
    return data, "image/png"


def load_reference_list(raw_items: list[Any], cfg: Config) -> list[tuple[bytes, str]]:
    if len(raw_items) > MAX_REF_ITEMS:
        raise RefMediaError(f"Too many reference items ({len(raw_items)} > {MAX_REF_ITEMS})")
    out: list[tuple[bytes, str]] = []
    total = 0
    for item in raw_items:
        data, mime = decode_reference_item(item, cfg)
        if not data:
            continue
        if len(data) > MAX_ITEM_BYTES:
            raise RefMediaError("Reference media exceeds 40 MiB per-item limit")
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise RefMediaError("Total reference media exceeds 100 MiB limit")
        out.append((data, mime))
    return out
