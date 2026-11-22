# Task 008: Git Init, Docker/Compose & Auto-Skip Exhausted Quota

- **Mục tiêu:** Khởi tạo Git repository sạch, đóng gói ứng dụng bằng Docker + Docker Compose, và tự động bỏ qua các tài khoản đã hết quota khi điều phối request `/v1/*`.
- **Liên kết Spec:** [00_system_architecture](../../02_basic_design/00_system_architecture.md), [01_accounts_and_keepalive](../../03_features/01_accounts_and_keepalive/spec.md)

## Kế hoạch thực hiện

1. **Git Initialization:**
   - Tạo `.gitignore` loại trừ `.env`, `data/`, `*.db`, `node_modules/`, `frontend/dist/`, `__pycache__/`, `.venv/`, `*.log`.
   - Chạy `git init` tại root `muse2apiv2`.
2. **Docker & Docker Compose:**
   - Tạo `.dockerignore`.
   - Tạo `Dockerfile` (multi-stage: `node:20-alpine` build `frontend/dist`, `python:3.12-slim` chạy FastAPI + Uvicorn).
   - Tạo `docker-compose.yml` (volume `./data:/app/data`, port `8000:8000`, `MUSE2API_DATA_DIR=/app/data`, healthcheck `/health`, `restart: unless-stopped`).
3. **Auto-Skip Exhausted Quota:**
   - Thêm helper `is_quota_exhausted(quota_json)` trong `backend/services/wss_pool.py` (hết quota khi `weekly_pct >= 100` và không còn `extra_pct < 100`).
   - Lọc bỏ các tài khoản hết quota trong `WSSPool._candidate_accounts()`; cập nhật thông báo lỗi khi toàn bộ tài khoản đều hết quota.
   - Kiểm tra lỗi quota từ upstream khi chạy WSS để tự động đánh dấu hết quota và failover sang tài khoản kế tiếp.
4. **Kiểm thử:**
   - Viết unit/integration tests kiểm chứng `_candidate_accounts()` skip đúng account hết quota (`weekly_pct=100` & không có extra), vẫn chọn account `weekly_pct=100` nhưng `extra_pct=30`, và vẫn chọn account chưa check quota.
   - Kiểm tra `git status` không theo dõi file nhạy cảm (`.env`, `data/`).
   - Kiểm tra `docker compose config` (nếu Docker CLI có sẵn trên máy).
