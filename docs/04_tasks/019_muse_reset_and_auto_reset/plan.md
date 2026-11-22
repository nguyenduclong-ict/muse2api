# Task 019: Reset Muse thủ công & Auto-Reset định kỳ theo tài khoản

- **Liên kết Change Request:**
  - [2026-11-22 — Reset Muse thủ công & Auto-Reset định kỳ theo tài khoản](../../03_features/01_accounts_and_keepalive/request-changes.md)
  - [2026-11-22 — Bổ sung cấu hình toàn cục Auto Reset Muse (`auto_reset`)](../../03_features/04_settings_and_cleanup/request-changes.md)
- **Liên kết Spec:**
  - [01_accounts_and_keepalive/spec.md](../../03_features/01_accounts_and_keepalive/spec.md), [design.md](../../03_features/01_accounts_and_keepalive/design.md), [logic.md](../../03_features/01_accounts_and_keepalive/logic.md)
  - [04_settings_and_cleanup/spec.md](../../03_features/04_settings_and_cleanup/spec.md), [design.md](../../03_features/04_settings_and_cleanup/design.md), [logic.md](../../03_features/04_settings_and_cleanup/logic.md)
- **Mục tiêu:** Triển khai tính năng **Reset Muse** thủ công cho từng tài khoản (`POST /api/hatch/replace-vm` chạy nền `202 Accepted` với trạng thái `resetting`, drain `in_flight` tối đa `30s`, đồng bộ WSS `/health`), bộ đếm `requests_since_reset`, lịch sử `reset_logs`, và **Auto-Reset** định kỳ theo `interval_minutes` kết hợp cờ `auto_reset` riêng cho từng tài khoản.

## Danh sách tệp cần tạo / chỉnh sửa

- **Backend:**
  - `packages/backend/db.py`: thêm 5 cột reset trên `accounts` + migration, bảng `reset_logs` (giữ 30 bản ghi/account), mặc định `settings.auto_reset`, `increment_requests_since_reset`, `recover_resetting_accounts`, `add_reset_log`, `list_reset_logs`.
  - `packages/backend/muse_wss.py`: thêm `fetch_live_session_http`, `replace_vm_http`, `sync_vm_selection_best_effort`.
  - `packages/backend/services/wss_pool.py`: thêm `in_flight` tracking, `healthy_available_count`, `increment_requests_since_reset`, bỏ qua `resetting` trong `get_client` và `maintain_tunnels`.
  - `packages/backend/services/keepalive.py`: bỏ qua tài khoản đang `resetting` trong `run_due` và `run_one`.
  - `packages/backend/services/reset_service.py` (tạo mới): `ResetService` xử lý reset thủ công bất đồng bộ, drain, backoff 15 phút, và vòng lặp nền auto-reset tuần tự mỗi 60s.
  - `packages/backend/main.py`: gọi `recover_resetting_accounts()` khi startup, khởi tạo và start/stop `ResetService` trong `lifespan`.
  - `packages/backend/routers/accounts.py`: mở rộng payload/serializer/export với `auto_reset` & metadata reset, bỏ qua `resetting` khi refresh, thêm `POST /admin/accounts/{id}/reset`, `POST /admin/accounts/reset-due`, `GET /admin/accounts/reset-logs`.
  - `packages/backend/routers/admin_core.py`: thêm `auto_reset` vào `SettingsPatchReq` (`interval_minutes >= 60`).
- **Frontend:**
  - `packages/frontend/src/pages/AccountsPage.tsx`: nút `Reset Muse` + modal xác nhận, badge `resetting` + tag `Auto`, switch `Auto Reset` trong modal Import & Edit, hiển thị `Last Reset` & `Requests since reset` trong Edit.
  - `packages/frontend/src/pages/OverviewPage.tsx`: badge `resetting` với spinner.
  - `packages/frontend/src/pages/SettingsPage.tsx`: card `Auto Reset Muse` (`enabled`, `interval_minutes >= 60`, `Run Due Resets Now`, `Save Auto Reset`).
- **Tests:**
  - `packages/backend/tests/test_muse_reset_and_auto_reset.py` (tạo mới).

## Checklist triển khai (đối chiếu AC)

- [x] **Bước 1 — DB Schema, Migration & Crash Recovery (`AC-015`, `BR-007`, `BR-008`):**
  - Thêm `auto_reset`, `last_reset_at`, `last_reset_status`, `last_reset_error`, `requests_since_reset` vào `accounts` kèm migration `ALTER TABLE` cho DB cũ.
  - Tạo bảng `reset_logs` giữ 30 dòng/account; thêm `recover_resetting_accounts()` và mặc định `settings.auto_reset`.
- [x] **Bước 2 — Giao thức Reset Muse & Concurrency Guards (`AC-016`, `BR-006`, `BR-007`):**
  - Thêm `fetch_live_session_http`, `replace_vm_http`, `sync_vm_selection_best_effort` trong `muse_wss.py`.
  - Thêm `in_flight` tracking + `increment_requests_since_reset` + skip `resetting` trong `WSSPool` và `KeepAliveService`.
- [x] **Bước 3 — `ResetService` & API Endpoints (`AC-016`..`AC-018`, `AC-305`):**
  - Tạo `services/reset_service.py` và gắn vào `main.py` (`lifespan`).
  - Cập nhật `routers/accounts.py` (`202` manual reset, `409` khi đang resetting, `reset-due`, `reset-logs`, `export`, `auto_reset` first-enable timestamp) và `routers/admin_core.py` (`auto_reset` clamp `>= 60`).
- [x] **Bước 4 — Giao diện Console (`AC-019`, `AC-305`):**
  - Cập nhật `AccountsPage.tsx`, `OverviewPage.tsx`, `SettingsPage.tsx`.
- [x] **Bước 5 — Kiểm thử tự động & Build (`AC-015`..`AC-019`, `AC-305`):**
  - Viết và chạy `test_muse_reset_and_auto_reset.py` cùng toàn bộ backend test suite.
  - Chạy `npm run build` (`tsc -b && vite build`) trong `packages/frontend`.

## Kế hoạch kiểm thử

1. **Backend Unit & Integration Tests (`unittest`):**
   - Kiểm tra migration DB cũ, tạo bảng `reset_logs` (pruning 30 dòng), và `recover_resetting_accounts()` khi startup.
   - Kiểm tra `GET/POST /admin/settings` với `auto_reset` (`interval_minutes < 60` bị kẹp thành `60`).
   - Kiểm tra `POST /admin/accounts/{id}/reset` trả `202`, `409` khi đang resetting, chờ drain `in_flight`, gọi `replace-vm` + WSS `/health`, đặt `requests_since_reset = 0`, từ chối `hatch_cvm`, và concurrency skip trên `maintain_tunnels`/`keepalive`/`refresh`.
   - Kiểm tra `requests_since_reset` tăng khi chạy request `/v1/*`; `ResetService.run_due()` hoãn khi `requests_since_reset == 0`, `in_flight > 0`, quota hết, `expired`, hoặc `healthy_available_count <= 1`; kiểm tra `401`/error backoff 15 phút.
2. **Frontend Build:** `npm run build` (`tsc -b && vite build`) pass không lỗi.
