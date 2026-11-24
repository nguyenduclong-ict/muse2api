"""Pure-Python muse.ai WSS + Noise_XX_25519_AESGCM_SHA256 + Protobuf RPC client."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import queue
import re
import struct
import threading
import time
import urllib.parse
import uuid
from typing import Any, Iterator

import requests
import websocket
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
MAX_NOISE_CHUNK = 65489


class MuseAuthError(RuntimeError):
    """Raised when session cookies or auth tokens are invalid/expired."""


class MuseWSSError(RuntimeError):
    """Raised on WebSocket, Noise, or RPC transport failure."""


# --- Minimal Protobuf Helpers ---
def pb_varint(n: int) -> bytes:
    if n < 0:
        n &= (1 << 64) - 1
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def pb_bytes(field_no: int, data: bytes) -> bytes:
    return pb_varint((field_no << 3) | 2) + pb_varint(len(data)) + data


def pb_str(field_no: int, s: str) -> bytes:
    return pb_bytes(field_no, s.encode("utf-8"))


def pb_int(field_no: int, val: int) -> bytes:
    return pb_varint((field_no << 3) | 0) + pb_varint(val)


def pb_decode_fields(buf: bytes) -> dict[int, list[Any]]:
    pos = 0
    fields: dict[int, list[Any]] = {}
    while pos < len(buf):
        tag = 0
        shift = 0
        while True:
            b = buf[pos]
            pos += 1
            tag |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        fno = tag >> 3
        wtype = tag & 7
        if wtype == 0:
            val = 0
            shift = 0
            while True:
                b = buf[pos]
                pos += 1
                val |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
            fields.setdefault(fno, []).append(val)
        elif wtype == 2:
            ln = 0
            shift = 0
            while True:
                b = buf[pos]
                pos += 1
                ln |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
            val = buf[pos : pos + ln]
            pos += ln
            fields.setdefault(fno, []).append(val)
        elif wtype == 5:
            fields.setdefault(fno, []).append(buf[pos : pos + 4])
            pos += 4
        elif wtype == 1:
            fields.setdefault(fno, []).append(buf[pos : pos + 8])
            pos += 8
        else:
            raise MuseWSSError(f"Unsupported protobuf wire type: {wtype}")
    return fields


# --- Noise_XX_25519_AESGCM_SHA256 ---
def _hmac_sha256(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def _hkdf2(chaining_key: bytes, ikm: bytes) -> tuple[bytes, bytes]:
    temp_key = _hmac_sha256(chaining_key, ikm)
    out1 = _hmac_sha256(temp_key, b"\x01")
    out2 = _hmac_sha256(temp_key, out1 + b"\x02")
    return out1, out2


class CipherState:
    def __init__(self, key: bytes | None = None):
        self.aes = AESGCM(key) if key is not None else None
        self.nonce = 0
        self._lock = threading.Lock()

    def encrypt_with_ad(self, ad: bytes, pt: bytes) -> bytes:
        if self.aes is None:
            return pt
        with self._lock:
            iv = b"\x00\x00\x00\x00" + struct.pack(">Q", self.nonce)
            self.nonce += 1
            return self.aes.encrypt(iv, pt, ad)

    def decrypt_with_ad(self, ad: bytes, ct: bytes) -> bytes:
        if self.aes is None:
            return ct
        with self._lock:
            iv = b"\x00\x00\x00\x00" + struct.pack(">Q", self.nonce)
            self.nonce += 1
            return self.aes.decrypt(iv, ct, ad)


class NoiseXX:
    def __init__(self):
        proto = b"Noise_XX_25519_AESGCM_SHA256"
        self.h = proto.ljust(32, b"\x00")
        self.ck = self.h
        self.cs = CipherState(None)
        self.h = hashlib.sha256(self.h).digest()
        self.e_priv: X25519PrivateKey | None = None
        self.s_priv: X25519PrivateKey | None = None
        self.re_pub: bytes | None = None
        self.rs_pub: bytes | None = None

    def mix_hash(self, data: bytes) -> None:
        self.h = hashlib.sha256(self.h + data).digest()

    def mix_key(self, ikm: bytes) -> None:
        self.ck, k = _hkdf2(self.ck, ikm)
        self.cs = CipherState(k)

    def encrypt_and_hash(self, pt: bytes) -> bytes:
        ct = self.cs.encrypt_with_ad(self.h, pt)
        self.mix_hash(ct)
        return ct

    def decrypt_and_hash(self, ct: bytes) -> bytes:
        pt = self.cs.decrypt_with_ad(self.h, ct)
        self.mix_hash(ct)
        return pt

    def write_message_1(self, payload: bytes = b"") -> bytes:
        self.e_priv = X25519PrivateKey.generate()
        e_pub = self.e_priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.mix_hash(e_pub)
        return e_pub + self.encrypt_and_hash(payload)

    def read_message_2(self, msg: bytes) -> bytes:
        if len(msg) < 96:
            raise MuseWSSError(f"Noise message 2 too short ({len(msg)} < 96)")
        self.re_pub = msg[:32]
        self.mix_hash(self.re_pub)
        dh1 = self.e_priv.exchange(X25519PublicKey.from_public_bytes(self.re_pub))
        self.mix_key(dh1)
        self.rs_pub = self.decrypt_and_hash(msg[32:80])
        dh2 = self.e_priv.exchange(X25519PublicKey.from_public_bytes(self.rs_pub))
        self.mix_key(dh2)
        return self.decrypt_and_hash(msg[80:])

    def write_message_3(self, payload: bytes = b"") -> bytes:
        self.s_priv = X25519PrivateKey.generate()
        s_pub = self.s_priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        enc_s = self.encrypt_and_hash(s_pub)
        dh3 = self.s_priv.exchange(X25519PublicKey.from_public_bytes(self.re_pub))
        self.mix_key(dh3)
        return enc_s + self.encrypt_and_hash(payload)

    def split(self) -> tuple[CipherState, CipherState]:
        k1, k2 = _hkdf2(self.ck, b"")
        return CipherState(k1), CipherState(k2)


# --- Proxy & Cookie Helpers ---
def cookies_to_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def requests_proxies(proxy_url: str) -> dict[str, str] | None:
    p = (proxy_url or "").strip()
    if not p:
        return None
    return {"http": p, "https": p}


def websocket_proxy_kwargs(proxy_url: str) -> dict[str, Any]:
    p = (proxy_url or "").strip()
    if not p:
        return {}
    parsed = urllib.parse.urlparse(p)
    scheme = (parsed.scheme or "http").lower()
    if scheme in ("socks5", "socks5h"):
        ptype = "socks5"
    elif scheme in ("socks4", "socks4a"):
        ptype = "socks4"
    else:
        ptype = "http"
    kw: dict[str, Any] = {
        "proxy_type": ptype,
        "http_proxy_host": parsed.hostname,
        "http_proxy_port": parsed.port or (1080 if "socks" in ptype else 8080),
    }
    if parsed.username:
        kw["http_proxy_auth"] = (
            urllib.parse.unquote(parsed.username),
            urllib.parse.unquote(parsed.password or ""),
        )
    return kw


def wake_vm_http(
    cookies: dict[str, str],
    vm_id: str,
    proxy_url: str = "",
    retry_count: int = 0,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Wake sleeping muse.ai VM with required same-origin headers."""
    headers = {
        "Cookie": cookies_to_header(cookies),
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Content-Type": "application/json",
        "Origin": "https://muse.ai",
        "Referer": "https://muse.ai/thread/new",
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
    }
    proxies = requests_proxies(proxy_url)
    r = requests.post(
        "https://muse.ai/api/hatch/vm/wake",
        headers=headers,
        json={"vm_id": vm_id, "retry_count": retry_count},
        proxies=proxies,
        timeout=timeout,
    )
    if r.status_code == 401:
        raise MuseAuthError("Session expired (/api/hatch/vm/wake HTTP 401)")
    if not r.ok:
        raise MuseWSSError(f"/api/hatch/vm/wake HTTP {r.status_code}: {r.text[:150]}")
    try:
        return r.json()
    except Exception:
        return {"status": r.text}


_EPHEMERAL_AUTH_COOKIES: frozenset[str] = frozenset(
    {
        "hatch_native_auth_csrf",
        "hatch_native_auth_state",
        "hatch_native_auth_temp",
        "hatch_native_auth_save_login",
        "hatch_native_auth_provider_sso",
        "hatch_native_auth_provider_completion",
        "hatch_native_auth_provider_disclosure",
        "oauth_csrf_token",
        "oauth_pkce_verifier",
        "hatch_post_login_intent",
        "hatch_post_login_oauth_url",
        "hatch_checkpoint_oidc_return",
    }
)


def extract_set_cookie_headers(resp: requests.Response) -> list[str]:
    """Extract all Set-Cookie header lines in order from a requests.Response."""
    raw_headers = getattr(getattr(resp, "raw", None), "headers", None)
    if raw_headers is not None and hasattr(raw_headers, "getlist"):
        return list(raw_headers.getlist("Set-Cookie"))
    hdrs = getattr(resp, "headers", None) or {}
    val = hdrs.get("Set-Cookie")
    if isinstance(val, list):
        return [str(x) for x in val if x]
    if isinstance(val, str) and val:
        return [val]
    return []


def apply_set_cookies(
    cookies: dict[str, str],
    resp: requests.Response,
    *,
    skip_ephemeral: bool = True,
) -> tuple[dict[str, str], bool]:
    """Apply ordered Set-Cookie headers onto a flat cookie dict.

    Returns (updated_cookies, changed). Processes headers sequentially so a
    delete (Max-Age=0) followed by a fresh Set-Cookie for the same name keeps
    the new value.
    """
    updated = dict(cookies)
    for sc in extract_set_cookie_headers(resp):
        parts = [p.strip() for p in sc.split(";")]
        nv = parts[0] if parts else ""
        if "=" not in nv:
            continue
        name, value = nv.split("=", 1)
        name = name.strip()
        if not name:
            continue

        is_delete = value == ""
        for attr in parts[1:]:
            low = attr.lower()
            if low.startswith("max-age="):
                try:
                    if int(low.split("=", 1)[1].strip()) <= 0:
                        is_delete = True
                except ValueError:
                    pass

        if skip_ephemeral and name in _EPHEMERAL_AUTH_COOKIES:
            updated.pop(name, None)
            continue
        if is_delete:
            updated.pop(name, None)
        else:
            updated[name] = value

    return updated, updated != cookies


def _masked_contact_matches(masked: str, label: str) -> bool:
    """Check if a masked contact (e.g. 'd***7@h***.online') matches account label."""
    m = (masked or "").strip().lower()
    lbl = (label or "").strip().lower()
    if not m or not lbl:
        return False
    segments = [re.escape(seg) for seg in re.split(r"\*+", m)]
    pattern = "^" + ".*".join(segments) + "$"
    return re.match(pattern, lbl) is not None


def _pick_one_tap_account(saved_accounts: list[dict[str, Any]], account_label: str = "") -> dict[str, Any]:
    """Select an eligible One-Tap saved account, preferring a masked_contact match with label."""
    eligible = [
        item
        for item in saved_accounts
        if isinstance(item, dict) and item.get("saved_account_id") and item.get("one_tap_available") is not False
    ]
    if not eligible:
        raise MuseAuthError("One-Tap re-login unavailable (no eligible saved accounts)")
    if len(eligible) > 1 and (account_label or "").strip():
        for item in eligible:
            if _masked_contact_matches(item.get("masked_contact") or "", account_label) or _masked_contact_matches(
                item.get("display_label") or "", account_label
            ):
                return item
    return eligible[0]


def _read_json_safe(resp: requests.Response) -> dict[str, Any]:
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def one_tap_relogin_http(
    cookies: dict[str, str],
    *,
    account_label: str = "",
    proxy_url: str = "",
    timeout: float = 25.0,
) -> dict[str, str]:
    """Re-authenticate an expired muse.ai session via One-Tap using __Host-hatch_one_tap."""
    if not (cookies.get("__Host-hatch_one_tap") or "").strip():
        raise MuseAuthError("One-Tap re-login unavailable (missing __Host-hatch_one_tap)")

    session = requests.Session()
    proxies = requests_proxies(proxy_url)
    if proxies:
        session.proxies = proxies
    for k, v in cookies.items():
        session.cookies.set(k, v, domain="muse.ai", path="/")

    merged = dict(cookies)
    base_headers = {
        "User-Agent": USER_AGENT,
        "Origin": "https://muse.ai",
        "Referer": "https://muse.ai/",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
    }

    # Step 1: restart native auth flow
    r1 = session.post(
        "https://muse.ai/api/auth/native/restart",
        headers=base_headers,
        data="{}",
        timeout=timeout,
        allow_redirects=False,
    )
    if not r1.ok:
        raise MuseAuthError(f"One-Tap restart failed (HTTP {r1.status_code})")
    merged, _ = apply_set_cookies(merged, r1, skip_ephemeral=True)
    j1 = _read_json_safe(r1)
    csrf_token = j1.get("csrf_token")
    if not isinstance(csrf_token, str) or not csrf_token:
        raise MuseAuthError("One-Tap restart did not return csrf_token")

    csrf_headers = {**base_headers, "X-Hatch-CSRF-Token": csrf_token}

    # Step 2: start flow when flow_state == "new"
    if j1.get("flow_state") == "new":
        r2 = session.post(
            "https://muse.ai/api/auth/native/start",
            headers=csrf_headers,
            data="{}",
            timeout=timeout,
            allow_redirects=False,
        )
        if not r2.ok:
            raise MuseAuthError(f"One-Tap start failed (HTTP {r2.status_code})")
        merged, _ = apply_set_cookies(merged, r2, skip_ephemeral=True)
        j2 = _read_json_safe(r2)
    else:
        j2 = {}

    # Step 3: get saved accounts
    saved_accounts = j1.get("saved_accounts")
    if not isinstance(saved_accounts, list) or not saved_accounts:
        saved_accounts = j2.get("saved_accounts")
    if not isinstance(saved_accounts, list) or not saved_accounts:
        r3 = session.post(
            "https://muse.ai/api/auth/native/saved-accounts",
            headers=csrf_headers,
            data="{}",
            timeout=timeout,
            allow_redirects=False,
        )
        if not r3.ok:
            raise MuseAuthError(f"One-Tap saved-accounts failed (HTTP {r3.status_code})")
        merged, _ = apply_set_cookies(merged, r3, skip_ephemeral=True)
        j3 = _read_json_safe(r3)
        saved_accounts = j3.get("saved_accounts") or []

    target = _pick_one_tap_account(saved_accounts if isinstance(saved_accounts, list) else [], account_label=account_label)

    # Step 4: perform one-tap-login
    r4 = session.post(
        "https://muse.ai/api/auth/native/one-tap-login",
        headers=csrf_headers,
        json={
            "saved_account_id": target["saved_account_id"],
            "return_to": "/",
            "security_key_related_origins": False,
        },
        timeout=timeout,
        allow_redirects=False,
    )
    j4 = _read_json_safe(r4)
    if r4.status_code == 403:
        if j4.get("type") == "checkpointRequired":
            raise MuseAuthError("One-Tap login requires checkpoint verification")
        detail = j4.get("detail") or j4.get("type") or "forbidden"
        raise MuseAuthError(f"One-Tap login HTTP 403 ({detail})")
    if r4.status_code not in (200, 301, 302, 303, 307, 308):
        detail = j4.get("detail") or j4.get("type") or r4.text[:150]
        raise MuseAuthError(f"One-Tap login HTTP {r4.status_code}: {detail}")

    if r4.status_code == 200 and j4:
        if j4.get("one_tap") == "unavailable":
            raise MuseAuthError(f"One-Tap unavailable ({j4.get('reason') or 'unknown'})")
        if j4.get("reactivation_required") is True:
            raise MuseAuthError("One-Tap login requires account reactivation")
        if j4.get("registration_state") == "two_factor_required":
            raise MuseAuthError("One-Tap login requires two-factor authentication")

    merged, _ = apply_set_cookies(merged, r4, skip_ephemeral=True)

    if r4.status_code in (301, 302, 303, 307, 308):
        loc = (r4.headers.get("Location") or "").strip()
        if loc.startswith("/") or loc.startswith("https://muse.ai/"):
            next_url = loc if loc.startswith("http") else f"https://muse.ai{loc}"
            r_red = session.get(
                next_url,
                headers={"User-Agent": USER_AGENT},
                timeout=timeout,
                allow_redirects=False,
            )
            merged, _ = apply_set_cookies(merged, r_red, skip_ephemeral=True)

    if not (merged.get("hatch_sess") or "").strip():
        raise MuseAuthError("One-Tap login did not issue hatch_sess")

    for k in _EPHEMERAL_AUTH_COOKIES:
        merged.pop(k, None)
    return merged


def check_auth_session_http(
    cookies: dict[str, str],
    proxy_url: str = "",
    timeout: float = 20.0,
) -> tuple[dict[str, Any], dict[str, str], bool]:
    """Proactively validate & slide-renew hatch_sess/hatch_gw via POST /api/auth/check."""
    headers = {
        "Cookie": cookies_to_header(cookies),
        "User-Agent": USER_AGENT,
        "Origin": "https://muse.ai",
        "Referer": "https://muse.ai/",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
    }
    r = requests.post(
        "https://muse.ai/api/auth/check",
        headers=headers,
        data="{}",
        proxies=requests_proxies(proxy_url),
        timeout=timeout,
        allow_redirects=False,
    )
    if r.status_code == 401:
        raise MuseAuthError("Session expired (/api/auth/check HTTP 401)")
    if r.status_code == 403:
        j = _read_json_safe(r)
        if j.get("type") == "checkpointRequired":
            raise MuseAuthError("Checkpoint required (/api/auth/check HTTP 403)")
        raise MuseAuthError("/api/auth/check HTTP 403")
    if r.status_code != 200:
        raise MuseWSSError(f"/api/auth/check HTTP {r.status_code}")

    data = _read_json_safe(r)
    if data.get("ok") is not True:
        raise MuseAuthError(f"/api/auth/check failed (outcome={data.get('outcome')!r})")

    merged, changed = apply_set_cookies(cookies, r, skip_ephemeral=True)
    return data, merged, changed


def renew_session_http(
    cookies: dict[str, str],
    proxy_url: str = "",
    timeout: float = 20.0,
    *,
    out_cookies: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Call muse.ai/api/session and wake VM if sleeping."""
    headers = {
        "Cookie": cookies_to_header(cookies),
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    proxies = requests_proxies(proxy_url)
    r = requests.get("https://muse.ai/api/session", headers=headers, proxies=proxies, timeout=timeout)
    if r.status_code == 401:
        raise MuseAuthError("Session expired (/api/session HTTP 401)")
    if r.status_code != 200:
        raise MuseWSSError(f"/api/session HTTP {r.status_code}")
    data = r.json()
    if data.get("status") != "assigned":
        raise MuseAuthError(f"/api/session status={data.get('status')!r}")

    merged, changed = apply_set_cookies(cookies, r, skip_ephemeral=True)
    if out_cookies is not None and changed:
        out_cookies.clear()
        out_cookies.update(merged)

    vm_state = data.get("vm_state", "")
    vm_id = data.get("vm_id") or ""
    if vm_id and vm_state and vm_state.upper() != "RUNNING":
        try:
            wake_vm_http(merged, vm_id, proxy_url=proxy_url, retry_count=0, timeout=timeout)
        except Exception:
            pass
    return data


_QUOTA_NEXT_ACTION_ID = "40e0249eeae158685b6a8d0c3b203f53dd4f2c7d63"
_UPDATE_USER_PREFERENCES_NEXT_ACTION_ID = "40076d65709b71539d10a9f0f52656ee03877e4d17"


def fetch_live_session_http(cookies: dict[str, str], proxy_url: str = "", timeout: float = 20.0) -> dict[str, Any]:
    """Fetch live muse.ai session inventory via GET /api/session?vm_state=live."""
    headers = {
        "Cookie": cookies_to_header(cookies),
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    r = requests.get(
        "https://muse.ai/api/session?vm_state=live",
        headers=headers,
        proxies=requests_proxies(proxy_url),
        timeout=timeout,
    )
    if r.status_code == 401:
        raise MuseAuthError("Session expired (/api/session?vm_state=live HTTP 401)")
    if r.status_code != 200:
        raise MuseWSSError(f"/api/session?vm_state=live HTTP {r.status_code}")
    data = r.json()
    if data.get("status") != "assigned":
        raise MuseAuthError(f"/api/session?vm_state=live status={data.get('status')!r}")
    return data


def replace_vm_http(
    cookies: dict[str, str],
    source_env_id: str,
    destination_type: str = "standard",
    intent: str = "reset",
    proxy_url: str = "",
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Trigger muse.ai VM replacement (Reset Muse) via POST /api/hatch/replace-vm."""
    headers = {
        "Cookie": cookies_to_header(cookies),
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Content-Type": "application/json",
        "Origin": "https://muse.ai",
        "Referer": "https://muse.ai/settings",
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
    }
    r = requests.post(
        "https://muse.ai/api/hatch/replace-vm",
        headers=headers,
        json={
            "sourceEnvId": source_env_id,
            "destinationType": destination_type,
            "intent": intent,
        },
        proxies=requests_proxies(proxy_url),
        timeout=timeout,
    )
    if r.status_code == 401:
        raise MuseAuthError("Reset Muse HTTP 401 (session expired)")
    try:
        data = r.json()
    except Exception:
        data = None
    if not r.ok:
        code = data.get("code") if isinstance(data, dict) else None
        if code == "authentication_required":
            raise MuseAuthError("Reset Muse authentication_required")
        detail = code or r.text[:150]
        raise MuseWSSError(f"/api/hatch/replace-vm HTTP {r.status_code}: {detail}")
    if not isinstance(data, dict) or data.get("ok") is not True or not data.get("vmId"):
        code = data.get("code") if isinstance(data, dict) else "invalid_response"
        if code == "authentication_required":
            raise MuseAuthError("Reset Muse authentication_required")
        raise MuseWSSError(f"/api/hatch/replace-vm failed: {code}")
    return data


def sync_vm_selection_best_effort(
    cookies: dict[str, str],
    new_vm_id: str,
    new_gateway_url: str,
    expected_revision: int | None,
    proxy_url: str = "",
    timeout: float = 20.0,
) -> bool:
    """Best-effort sync of vm_selection.override via updateUserPreferencesAction."""
    if expected_revision is None:
        return False
    proxies = requests_proxies(proxy_url)
    cookie_hdr = cookies_to_header(cookies)
    try:
        r_set = requests.get(
            "https://muse.ai/settings",
            headers={"Cookie": cookie_hdr, "User-Agent": USER_AGENT},
            proxies=proxies,
            timeout=timeout,
        )
        if r_set.status_code != 200:
            return False
        m_owner = re.search(r'ownerId["\\]*:\s*["\\]*([A-Za-z0-9_-]+)', r_set.text)
        if not m_owner:
            return False
        owner_id = m_owner.group(1)
        payload = [{
            "pawOverrides": json.dumps({"gatewayUrl": new_gateway_url, "vmName": new_vm_id}, separators=(",", ":")),
            "vmOverrideGatewayUrl": new_gateway_url,
            "vmOverrideVmName": new_vm_id,
            "expectedVmSelectionRevision": int(expected_revision),
            "expectedVmSelectionOwnerId": owner_id,
        }]
        r_pref = requests.post(
            "https://muse.ai/settings",
            headers={
                "Cookie": cookie_hdr,
                "User-Agent": USER_AGENT,
                "Origin": "https://muse.ai",
                "Referer": "https://muse.ai/settings",
                "next-action": _UPDATE_USER_PREFERENCES_NEXT_ACTION_ID,
                "Accept": "text/x-component",
                "Content-Type": "text/plain;charset=UTF-8",
                "sec-fetch-site": "same-origin",
                "sec-fetch-mode": "cors",
                "sec-fetch-dest": "empty",
            },
            data=json.dumps(payload),
            proxies=proxies,
            timeout=timeout,
        )
        return r_pref.status_code == 200
    except Exception:
        return False


def fetch_quota_http(cookies: dict[str, str], proxy_url: str = "", timeout: float = 15.0) -> dict[str, Any]:
    """Fetch real subscription & usage quota via muse.ai Next-Action Server Action."""
    headers = {
        "Cookie": cookies_to_header(cookies),
        "User-Agent": USER_AGENT,
        "Origin": "https://muse.ai",
        "Referer": "https://muse.ai/thread/new",
        "next-action": _QUOTA_NEXT_ACTION_ID,
        "Accept": "text/x-component",
        "Content-Type": "text/plain;charset=UTF-8",
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
    }
    r = requests.post(
        "https://muse.ai/thread/new",
        headers=headers,
        data=json.dumps([{"includeAgreement": True}]),
        proxies=requests_proxies(proxy_url),
        timeout=timeout,
    )
    if r.status_code == 401:
        raise MuseAuthError("Quota check HTTP 401 (session expired)")
    if r.status_code != 200:
        raise MuseWSSError(f"Quota check HTTP {r.status_code}")

    sub: dict[str, Any] | None = None
    for line in r.text.splitlines():
        if ":" not in line:
            continue
        _, payload_str = line.split(":", 1)
        try:
            obj = json.loads(payload_str)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "subscription" in obj:
            sub = obj.get("subscription") or {}
            break
    if not sub:
        raise MuseWSSError("Quota payload not found in Next-Action response")

    usage = sub.get("usage") or {}
    tier = sub.get("tier") or {}
    topup_total = sub.get("topupTotal") or 0
    topup_bal = sub.get("topupBalance") or 0
    extra_pct = round((1 - (topup_bal / topup_total)) * 100) if topup_total > 0 else None

    out: dict[str, Any] = {
        "plan": tier.get("name") or sub.get("usageRowLabel") or "Unknown",
        "weekly_pct": usage.get("percentUsed"),
        "weekly_reset": sub.get("statusSubtitle") or "",
        "checked_at": time.time(),
    }
    if extra_pct is not None:
        out["extra_pct"] = extra_pct
    if sub.get("topupRowValueLabel"):
        out["extra_remaining"] = sub["topupRowValueLabel"]
    return out


# --- Persistent Multiplexed WSS Client ---
class MuseWSSClient:
    """Maintains a single encrypted Noise_XX WebSocket tunnel with stream_id multiplexing."""

    def __init__(self, cookies: dict[str, str], proxy_url: str = ""):
        self.cookies = cookies
        self.proxy_url = proxy_url
        self.ws: websocket.WebSocket | None = None
        self.send_cs: CipherState | None = None
        self.recv_cs: CipherState | None = None
        self.vm_name: str = ""
        self._connected = False
        self._write_lock = threading.Lock()
        self._stream_lock = threading.Lock()
        self._next_stream_id = 1
        self._next_chunk_id = 1
        self._streams: dict[int, queue.Queue[dict[str, Any] | None]] = {}
        self._reader_thread: threading.Thread | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected and self.ws is not None

    def _bootstrap(self, timeout: float = 20.0) -> dict[str, Any]:
        cookie_hdr = cookies_to_header(self.cookies)
        r = requests.get(
            "https://muse.ai/thread/new",
            headers={"Cookie": cookie_hdr, "User-Agent": USER_AGENT},
            proxies=requests_proxies(self.proxy_url),
            timeout=timeout,
            allow_redirects=False,
        )
        if r.status_code in (401, 403) or (r.status_code in (301, 302, 307, 308) and "/thread/" not in r.headers.get("Location", "")):
            raise MuseAuthError(f"Cookie expired or unauthorized (/thread/new HTTP {r.status_code})")
        if r.status_code != 200:
            raise MuseWSSError(f"Bootstrap /thread/new HTTP {r.status_code}")

        all_m = re.findall(r"__HATCH_GATEWAY_INIT__\s*=\s*(\{.*?\});", r.text)
        last_obj: dict[str, Any] | None = None
        for raw in all_m:
            cur = raw
            for _ in range(4):
                try:
                    parsed = json.loads(cur)
                    if isinstance(parsed, dict):
                        last_obj = parsed
                        if parsed.get("vmName") and parsed.get("authToken") and parsed.get("noiseNotaryToken"):
                            return parsed
                        break
                except json.JSONDecodeError:
                    pass
                if cur.startswith("{\\"):
                    cur = cur.replace("\\\\", "\\").replace('\\"', '"')
                else:
                    break

        # Fallback: extract tokens directly from Next.js RSC payload when __HATCH_GATEWAY_INIT__ has null tokens
        vm_m = re.search(r'vmName["\\]*:\s*["\\]*([0-9a-f-]{36})', r.text)
        tok_m = re.search(r"(muse-secret-edge-[A-Za-z0-9_.-]+)", r.text)
        notary_m = re.search(r"(endorsement\.v1\.[A-Za-z0-9_.+/=-]+)", r.text)
        if vm_m and tok_m and notary_m:
            return {
                **(last_obj or {}),
                "vmName": vm_m.group(1),
                "authToken": tok_m.group(1),
                "noiseNotaryToken": notary_m.group(1),
            }

        if not all_m:
            raise MuseAuthError("Missing __HATCH_GATEWAY_INIT__ in /thread/new (not logged in)")
        return last_obj or {}

    def connect(self, timeout: float = 25.0) -> None:
        for attempt in range(3):
            try:
                self._connect_once(timeout=timeout)
                return
            except MuseWSSError as exc:
                if attempt < 2 and "fail_ip_registry_not_found" in str(exc) and self.vm_name:
                    try:
                        wake_vm_http(
                            self.cookies,
                            self.vm_name,
                            proxy_url=self.proxy_url,
                            retry_count=attempt,
                            timeout=10.0,
                        )
                    except Exception:
                        pass
                    time.sleep(3.5)
                    continue
                raise

    def _connect_once(self, timeout: float = 25.0) -> None:
        self.close()
        init = self._bootstrap(timeout=timeout)
        self.vm_name = init.get("vmName") or ""
        auth_token = init.get("authToken")
        notary_token = init.get("noiseNotaryToken")
        if not self.vm_name or not auth_token or not notary_token:
            raise MuseWSSError("VM not ready (missing authToken/noiseNotaryToken)")
        qs = urllib.parse.urlencode(
            {
                "vm_id": self.vm_name,
                "auth_token": auth_token,
                "notary_token": notary_token,
                "app_id": "hatch-web",
                "app_version": "1",
                "request_id": str(uuid.uuid4()),
            }
        )
        ws_url = f"wss://hatch.metaaivm.com/v1/noise?{qs}"
        try:
            ws = websocket.create_connection(
                ws_url,
                origin="https://muse.ai",
                header=[f"User-Agent: {USER_AGENT}", f"Cookie: {cookies_to_header(self.cookies)}"],
                timeout=timeout,
                **websocket_proxy_kwargs(self.proxy_url),
            )
        except websocket.WebSocketBadStatusException as exc:
            headers = getattr(exc, "resp_headers", None) or {}
            res_status = headers.get("x-hatch-resolution-status") or headers.get("X-Hatch-Resolution-Status") or ""
            status_code = getattr(exc, "status_code", 0)
            if status_code == 401:
                raise MuseAuthError("WSS handshake HTTP 401 (unauthorized)") from exc
            detail = f" ({res_status})" if res_status else ""
            raise MuseWSSError(f"WSS handshake HTTP {status_code}{detail}") from exc
        noise = NoiseXX()
        ws.send(noise.write_message_1(pb_bytes(1, os.urandom(32))), opcode=websocket.ABNF.OPCODE_BINARY)
        noise.read_message_2(ws.recv())
        ws.send(noise.write_message_3(b""), opcode=websocket.ABNF.OPCODE_BINARY)
        self.send_cs, self.recv_cs = noise.split()
        self.ws = ws
        self._connected = True
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

    def close(self) -> None:
        self._connected = False
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None
        with self._stream_lock:
            for q in self._streams.values():
                q.put(None)
            self._streams.clear()

    def _read_loop(self) -> None:
        chunks_buf: dict[int, dict[int, bytes]] = {}
        try:
            while self._connected and self.ws is not None:
                try:
                    raw = self.ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if not raw:
                    break
                pt = self.recv_cs.decrypt_with_ad(b"", raw)
                nt = pb_decode_fields(pt)
                cid = nt.get(1, [0])[0]
                cidx = nt.get(2, [0])[0]
                ctot = nt.get(3, [1])[0]
                payload = nt.get(4, [b""])[0]
                if ctot > 1:
                    chunks_buf.setdefault(cid, {})[cidx] = payload
                    if len(chunks_buf[cid]) < ctot:
                        continue
                    payload = b"".join(chunks_buf[cid][i] for i in range(ctot))
                    del chunks_buf[cid]

                svc_resp = pb_decode_fields(payload)
                sf = pb_decode_fields(svc_resp.get(1, [b""])[0])
                sid = sf.get(1, [0])[0]

                event: dict[str, Any] | None = None
                if 3 in sf:
                    ar = pb_decode_fields(sf[3][0])
                    event = {
                        "kind": "response",
                        "status": ar.get(1, [200])[0],
                        "headers": ar.get(2, []),
                        "body": ar.get(3, [b""])[0],
                        "end_body": bool(ar.get(4, [0])[0]),
                    }
                elif 4 in sf:
                    bc = pb_decode_fields(sf[4][0])
                    event = {
                        "kind": "chunk",
                        "data": bc.get(1, [b""])[0],
                        "end_body": bool(bc.get(2, [0])[0]),
                    }
                elif 5 in sf:
                    rs = pb_decode_fields(sf[5][0])
                    event = {
                        "kind": "reset",
                        "code": rs.get(1, [0])[0],
                        "reason": rs.get(2, [b""])[0].decode("utf-8", errors="replace"),
                    }

                if event is not None:
                    with self._stream_lock:
                        q = self._streams.get(sid)
                    if q is not None:
                        q.put(event)
        except Exception:
            pass
        finally:
            self._connected = False
            with self._stream_lock:
                for q in self._streams.values():
                    q.put(None)

    def _open_stream(self, verb: str, path: str, body_bytes: bytes = b"",
                     content_type: str | None = None, service: int = 0) -> tuple[int, queue.Queue]:
        if not self.is_connected:
            raise MuseWSSError("WSS client is not connected")
        with self._stream_lock:
            sid = self._next_stream_id
            self._next_stream_id += 1
            cid = self._next_chunk_id
            self._next_chunk_id += 1
            q: queue.Queue = queue.Queue()
            self._streams[sid] = q

        hdrs = [
            pb_str(1, "x-request-id") + pb_str(2, str(uuid.uuid4())),
            pb_str(1, "x-app-id") + pb_str(2, "hatch-web"),
            pb_str(1, "Accept-Language") + pb_str(2, "en-US"),
        ]
        if content_type:
            hdrs.insert(0, pb_str(1, "Content-Type") + pb_str(2, content_type))

        app_req = pb_str(1, verb) + pb_str(2, path)
        for h in hdrs:
            app_req += pb_bytes(3, h)
        app_req += pb_bytes(4, body_bytes) + pb_int(5, 1)

        svc_frame = pb_int(1, sid) + pb_bytes(2, app_req)
        svc_req = pb_int(1, service) + pb_bytes(2, svc_frame)

        total_chunks = max(1, (len(svc_req) + MAX_NOISE_CHUNK - 1) // MAX_NOISE_CHUNK)
        with self._write_lock:
            for idx in range(total_chunks):
                part = svc_req[idx * MAX_NOISE_CHUNK : (idx + 1) * MAX_NOISE_CHUNK]
                nt_frame = pb_int(1, cid) + pb_int(2, idx) + pb_int(3, total_chunks) + pb_bytes(4, part)
                enc = self.send_cs.encrypt_with_ad(b"", nt_frame)
                self.ws.send(enc, opcode=websocket.ABNF.OPCODE_BINARY)
        return sid, q

    def _close_stream(self, sid: int) -> None:
        with self._stream_lock:
            self._streams.pop(sid, None)

    def request(self, verb: str, path: str, body_dict: dict[str, Any] | None = None,
                service: int = 0, timeout: float = 30.0) -> tuple[int, bytes]:
        body_bytes = json.dumps(body_dict).encode("utf-8") if body_dict is not None else b""
        ct = "application/json" if body_dict is not None else None
        sid, q = self._open_stream(verb, path, body_bytes, ct, service)
        buf = bytearray()
        status = 200
        deadline = time.time() + timeout
        try:
            while True:
                rem = deadline - time.time()
                if rem <= 0:
                    raise TimeoutError(f"RPC {verb} {path} timed out")
                ev = q.get(timeout=rem)
                if ev is None:
                    raise MuseWSSError(f"WSS disconnected during {verb} {path}")
                if ev["kind"] == "response":
                    status = ev["status"]
                    buf.extend(ev["body"])
                    if ev["end_body"]:
                        break
                elif ev["kind"] == "chunk":
                    buf.extend(ev["data"])
                    if ev["end_body"]:
                        break
                elif ev["kind"] == "reset":
                    raise MuseWSSError(f"Stream reset ({ev['code']}): {ev['reason']}")
            return status, bytes(buf)
        finally:
            self._close_stream(sid)

    def stream_rpc(self, verb: str, path: str, body_dict: dict[str, Any] | None = None,
                   service: int = 0, timeout: float = 180.0,
                   idle_timeout: float | None = None) -> Iterator[tuple[int | None, bytes]]:
        body_bytes = json.dumps(body_dict).encode("utf-8") if body_dict is not None else b""
        ct = "application/json" if body_dict is not None else None
        sid, q = self._open_stream(verb, path, body_bytes, ct, service)
        deadline = time.time() + timeout
        try:
            while True:
                rem = deadline - time.time()
                if rem <= 0:
                    raise TimeoutError(f"Stream {verb} {path} timed out after {int(timeout)}s")
                wait = min(rem, idle_timeout) if (idle_timeout and idle_timeout > 0) else rem
                try:
                    ev = q.get(timeout=wait)
                except queue.Empty:
                    if time.time() >= deadline:
                        raise TimeoutError(f"Stream {verb} {path} timed out after {int(timeout)}s")
                    raise TimeoutError(f"Stream {verb} {path} idle for {int(idle_timeout)}s with no events")
                if ev is None:
                    break
                if ev["kind"] == "response":
                    yield ev["status"], ev["body"]
                    if ev["end_body"]:
                        break
                elif ev["kind"] == "chunk":
                    yield None, ev["data"]
                    if ev["end_body"]:
                        break
                elif ev["kind"] == "reset":
                    raise MuseWSSError(f"Stream reset ({ev['code']}): {ev['reason']}")
        finally:
            self._close_stream(sid)
