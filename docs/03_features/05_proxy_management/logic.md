# Logic Design: Proxy Management

## 1. Sequence Diagram — Import & Check Proxy qua `ipinfo.io`

```mermaid
sequenceDiagram
    actor Admin
    participant UI as React Console (/proxies)
    participant API as FastAPI (/admin/proxies)
    participant DB as SQLite (proxies, accounts)
    participant IPInfo as ipinfo.io

    Admin->>UI: Paste multi-line proxies & click Import
    UI->>API: POST /admin/proxies/import {proxies_text}
    API->>API: Parse & normalize each line (URL, host:port, host:port:user:pass)
    API->>DB: INSERT OR IGNORE INTO proxies
    API-->>UI: 201 {imported, skipped, proxies}

    Admin->>UI: Click Check / Check All
    UI->>API: POST /admin/proxies/{id}/check
    API->>IPInfo: GET https://ipinfo.io/json (via proxy, timeout 15s)
    alt 200 OK
        IPInfo-->>API: {ip, country, city, org}
        API->>DB: UPDATE proxies SET status="alive", ip=..., latency_ms=...
    else Error / Timeout
        API->>DB: UPDATE proxies SET status="dead", last_error=...
    end
    API-->>UI: 200 {ok, proxy}
```

## 2. UI Event Handlers

| Phần tử UI | Sự kiện | API Endpoint | Tham số |
|---|---|---|---|
| `+ Import Proxies` → `Import` | `onSubmit` | `POST /admin/proxies/import` | `{proxies_text}` |
| `Check` (row) | `onClick` | `POST /admin/proxies/{id}/check` | `proxy_id` |
| `Check All` | `onClick` | `POST /admin/proxies/check-all` | `{}` |
| `Delete` (row) | `onClick` | `DELETE /admin/proxies/{id}` | `proxy_id` |

## 3. Thuật toán Parse & Chuẩn hóa Proxy
1. Với mỗi dòng sau khi `.strip()`: bỏ qua nếu rỗng hoặc bắt đầu bằng `#`.
2. Nếu chứa `://`: parse bằng `urllib.parse.urlparse`, kiểm tra scheme thuộc `("http", "https", "socks5", "socks5h", "socks4")` và có `hostname` + `port`.
3. Nếu không chứa `://`:
   - `parts = line.split(":")`
   - Nếu `len(parts) == 2` (`host:port`) → `http://{host}:{port}`
   - Nếu `len(parts) == 4` (`host:port:user:pass`) → `http://{quote(user)}:{quote(pass)}@{host}:{port}`
   - Nếu chứa `@` (`user:pass@host:port`) → `http://{line}`
4. Khi xóa proxy (`DELETE /admin/proxies/{id}`): tìm các `accounts` có `proxy_id = id`, đóng WSS connection của các account đó, rồi xóa bản ghi `proxies` (`ON DELETE SET NULL` tự động đặt `accounts.proxy_id = NULL`).
