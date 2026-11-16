# Task 001: Core WSS Noise Client & SQLite Store

## 1. Mục tiêu triển khai
Xây dựng module giao tiếp WSS thuần (`Noise_XX_25519_AESGCM_SHA256` + Protobuf 3 lớp + HTTP Bootstrap) và lớp khởi tạo cơ sở dữ liệu SQLite (`WAL` mode) cho `muse2apiv2`.

## 2. Danh sách tệp tin cần tạo
- `backend/config.py`
- `backend/db.py`
- `backend/muse_wss.py`
- `backend/requirements.txt`
- `.env.example`

## 3. Checklist triển khai
- [ ] Khởi tạo cấu trúc `backend/` và `requirements.txt` (`fastapi`, `uvicorn`, `requests`, `PySocks`, `websocket-client`, `cryptography`).
- [ ] Viết `backend/db.py` tạo 5 bảng (`accounts`, `keepalive_logs`, `tasks`, `api_keys`, `settings`) ở chế độ `WAL` và seed giá trị mặc định (1 API key `m2a_...`, `system_prompt`, `media_cleanup`).
- [ ] Viết `backend/muse_wss.py`:
  - [ ] HTTP Bootstrap (`GET https://muse.ai/thread/new`) trích xuất `__HATCH_GATEWAY_INIT__`.
  - [ ] `NoiseXX` handshake 3 bước + `CipherState` AES-256-GCM.
  - [ ] Protobuf `NoiseTransportFrame` (chunking ≤ `65489`B) + `ServiceRequest`/`ServiceResponse` + `ServiceFrame` (`stream_id` multiplexing).
  - [ ] Hỗ trợ HTTP/SOCKS5 proxy cho cả `requests` và `websocket-client`.
- [ ] Khảo sát và ghi nhận payload chi tiết cho 3 điểm mở: đọc quota, upload file tham chiếu, `POST /api/voice/speak`.

## 4. Kế hoạch kiểm thử
- **Unit test:** Kiểm tra `NoiseXX` key schedule, Protobuf encode/decode nhiều chunk, và khởi tạo schema SQLite.
- **Integration test:** Kết nối WSS thật qua `GET /health`, `POST /chat/stream` → `POST /chat/subscribe` → `GET /chat/history` → `GET /media/raw/...`.
