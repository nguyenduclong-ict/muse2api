# Logic Design: OpenAI-Compatible API & API Key

## 1. Sequence Diagram — Request qua WSS Noise Tunnel

```mermaid
sequenceDiagram
    participant App as Third-Party App
    participant API as FastAPI (/v1/*)
    participant Guard as Ref Media & SSRF Guard
    participant Pool as WSS Pool (LRU)
    participant VM as Muse Cloud VM (/v1/noise)

    App->>API: POST /v1/* (Bearer m2a_...)
    API->>API: Verify raw_key in SQLite api_keys
    opt Có URL / Base64 / Multipart tham chiếu
        API->>Guard: Validate & fetch media (no private IP, <=10 items, <=40MiB/100MiB)
        Guard-->>API: list[(bytes, mime_type)]
    end
    API->>Pool: acquire_healthy_account()
    Pool->>VM: Stream N: POST /chat/stream (items, session_id)
    VM-->>Pool: 200 OK (session_id created)
    Pool->>VM: Stream N+1: POST /chat/subscribe (session_id)
    loop Streaming BodyChunks
        VM-->>Pool: event delta / task.status / delta.presentation
        Pool-->>API: Yield text delta or completion signal
        API-->>App: SSE chunk (chat.completion.chunk hoặc response.*)
    end
    opt Media Output (Image / Video)
        Pool->>VM: GET /chat/history?session_id=...
        VM-->>Pool: resources[].path (/workspace/imagine_media/...)
        Pool->>VM: GET /media/raw/<path>
        VM-->>Pool: Binary BodyChunks
        Pool->>Pool: Save to data/media/<filename>
    end
    API-->>App: Final JSON / Media URL (/v1/media/<filename>)
```

## 2. UI Event Handlers

| Phần tử UI | Sự kiện | API Endpoint | Tham số |
|---|---|---|---|
| `Show / Hide` | `onClick` | - (client state) | Toggle mask/unmask `raw_key` |
| `Copy Key` | `onClick` | - (clipboard) | Copy `raw_key` |
| `Rotate Key` (confirm) | `onClick` | `POST /admin/apikey/rotate` | `{}` |

## 3. Thuật toán xử lý bổ sung
1. **SSRF Guard cho Reference URL (`BR-104`):**
   - Kiểm tra scheme chỉ cho phép `http`/`https` (hoặc local file nếu `MUSE2API_REF_IMAGE_LOCAL_FILES=1`).
   - Phân giải DNS (`socket.getaddrinfo`) và kiểm tra mọi IP không thuộc `is_private`, `is_loopback`, `is_link_local`, `is_reserved`, `is_multicast` (trừ khi `MUSE2API_REF_IMAGE_PRIVATE_FETCH=1`).
   - Tắt redirect tự động (`allow_redirects=False`) hoặc kiểm tra lại IP ở mỗi hop; giới hạn tối đa 40 MiB/item và 100 MiB tổng.
2. **LRU & Failover:**
   - Lấy danh sách `enabled = 1 AND status = 'healthy'`, sắp xếp tăng dần theo `last_used_at`.
   - Nếu `POST /chat/stream` lỗi `401`/timeout trước khi trả chunk đầu tiên, đánh dấu tài khoản và retry sang tài khoản kế tiếp.
3. **SSE Format cho `/v1/responses`:**
   - Bắn lần lượt `event: response.created`, các `event: response.output_text.delta` theo `delta` từ `chat.subscribe`, và `event: response.completed` kèm full output.
