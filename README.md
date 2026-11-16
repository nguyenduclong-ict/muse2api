# muse2apiv2

OpenAI-compatible API Gateway (`/v1/*`) và Admin Console cho **muse.ai**, giao tiếp trực tiếp qua HTTPS + WSS (`Noise_XX_25519_AESGCM_SHA256` & Protobuf) không cần chạy trình duyệt ngầm.

## Cấu trúc thư mục

```text
muse2apiv2/
├── packages/
│   ├── backend/          # FastAPI gateway, WSS pool, Keep-Alive, SQLite WAL (quản lý bằng uv)
│   └── frontend/         # React + Vite + Tailwind + shadcn/ui Admin Console
├── extension/            # Chrome Extension (Manifest V3) copy cookie muse.ai
├── docs/                 # Tài liệu SRS, Basic Design, Feature Specs & Tasks
├── data/                 # Runtime SQLite DB & thư mục media/ (tự tạo, gitignored)
├── Dockerfile            # Multi-stage build (Node 20 + Python 3.12 + uv)
├── docker-compose.yml    # Triển khai nhanh với volume ./data
└── .env.example          # Mẫu biến môi trường
```

## Tính năng chính

- **OpenAI `/v1/*` API Parity:** Hỗ trợ `/v1/models`, `/v1/chat/completions` (streaming SSE & non-stream), `/v1/responses`, `/v1/images/generations`, `/v1/images/edits`, `/v1/images/tasks`, `/v1/videos`, `/v1/videos/generations`, `/v1/media/{filename}`.
- **Account Pool & Auto-Skip Quota:** Điều phối LRU + failover tự động, bỏ qua các tài khoản đã hết quota (chỉ skip khi `weekly_pct >= 100` và không còn token bổ sung `extra_pct < 100`).
- **WSS Tunnel & Keep-Alive chạy ngầm:** Tự động duy trì/kiểm tra kết nối WSS Tunnel định kỳ, làm mới phiên và cập nhật trạng thái (`healthy`, `expired`, `cooldown`) lên UI.
- **Proxy Management:** Import nhiều dòng (`http`/`https`/`socks4`/`socks5`), kiểm tra IP/vị trí/latency qua `ipinfo.io`, gán proxy cho tài khoản và tự gỡ khi xóa proxy.
- **Chrome Extension Copy Cookie:** Tải trực tiếp từ giao diện **Accounts → Download Extension** (`.zip`) để lấy chuỗi cookie `muse.ai` (kể cả `HttpOnly`).
- **Tasks & Media Cleanup:** Theo dõi lịch sử task kèm tài khoản thực thi; xóa task sẽ dọn luôn file media tương ứng khỏi `data/media/`.

---

## Chạy Local (Development)

### 1. Cấu hình môi trường
```bash
cp .env.example .env
```

### 2. Build Frontend
```bash
cd packages/frontend
npm install
npm run build
```

### 3. Chạy Backend bằng `uv`
```bash
cd packages/backend
uv sync
uv run uvicorn main:app --host 0.0.0.0 --port 18610
```
Hoặc chạy trực tiếp file `main.py`:
```bash
cd packages/backend
uv run python main.py
```

Sau khi khởi động, mở trình duyệt tại `http://127.0.0.1:18610` để truy cập Admin Console.

---

## Chạy bằng Docker Compose

```bash
cp .env.example .env
docker compose up -d --build
```

- Mặc định ánh xạ cổng `8000:8000` (hoặc theo `MUSE2API_PORT` trong `.env`).
- Dữ liệu SQLite (`muse2apiv2.db`) và file media được lưu bền vững tại `./data`.

---

## Hướng dẫn lấy Cookie bằng Extension

1. Vào trang **Accounts** trên Console, bấm **Download Extension** để tải `muse2apiv2-extension.zip` và giải nén.
2. Mở Chrome/Edge tại `chrome://extensions`, bật **Developer mode**, chọn **Load unpacked** và trỏ vào thư mục vừa giải nén.
3. Đăng nhập `https://muse.ai`, bấm icon extension → **Copy Cookies**, sau đó dán vào modal **Import Account**.
