# Tech Stack — Công nghệ sử dụng

## 1. Backend (Python 3.12+)
- **Web Framework:** FastAPI + Uvicorn (ASGI, hỗ trợ SSE streaming).
- **HTTP Client:** `requests` (HTTP bootstrap, `/api/session`, `/api/hatch/vm/wake`, hỗ trợ HTTP/SOCKS5 proxy qua `PySocks`).
- **WebSocket & Noise Crypto:**
  - `websocket-client` (kết nối WSS nhị phân `opcode=2` kèm proxy & custom `Origin`).
  - `cryptography` (`X25519PrivateKey`, `X25519PublicKey`, `AESGCM`).
  - Protobuf encoder/decoder tối giản (hoặc `protobuf`) cho `NoiseTransportFrame`, `ServiceRequest`, `ServiceResponse`, `ServiceFrame`.
- **Database:** SQLite (`sqlite3` chuẩn thư viện Python, giữ persistent connection với `RLock`; khi chạy Docker Compose lưu `muse2apiv2.db` trên Docker named volume native Linux `muse2apiv2_db:/app/db` qua `MUSE2API_DB_PATH` ở chế độ `WAL` và tự động migrate một lần từ `data/muse2apiv2.db` nếu tồn tại, còn `media/` và `voice_previews/` giữ tại `./data:/app/data`; tự fallback sang `TRUNCATE` nếu đặt DB trực tiếp trên `9p`/network mount, hỗ trợ ép qua `MUSE2API_SQLITE_JOURNAL_MODE`).
- **Media Processing (tùy chọn):** `ffmpeg` để chuyển đổi định dạng audio cho `/v1/audio/speech` khi cần.

## 2. Frontend (ReactJS)
- **Core:** React 18+ + TypeScript + Vite + `react-router-dom`.
- **UI & Styling:** Tailwind CSS + **shadcn/ui** + `lucide-react`.
- **Data Fetching:** TanStack Query (polling trạng thái pool, tasks, quota).
- **Giao diện & Color Scheme:**
  - Layout: **Sidebar → Content** cố định bên trái (tiếng Anh).
  - Theme: **Slate/Zinc Dark-First** (`#09090B` background, `#111114` card, `#27272A` border), accent **Emerald (`#10B981`)** cho trạng thái healthy/connected và **Blue/Indigo (`#3B82F6`)** cho action chính.
  - Font: `Inter` (UI) và `JetBrains Mono` (API key, IDs, logs).

## 3. Triển khai (Deployment)
- **Single-port:** FastAPI phục vụ cả `/v1/*`, `/admin/*` và file tĩnh `frontend/dist/` trên cùng một cổng (mặc định `18610`).
- **Development:** Vite dev server chạy riêng và proxy `/v1` + `/admin` sang FastAPI.
