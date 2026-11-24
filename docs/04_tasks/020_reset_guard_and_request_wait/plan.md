# Task 020: Khóa nguyên tử chống race Reset, Bảo vệ Pool theo `supported_models` & Giữ/Chờ Request `/v1/*`

- **Liên kết Change Request:**
  - [2026-11-25 — Khóa nguyên tử chống race condition khi Reset & Bảo vệ Auto-Reset theo `supported_models`](../../03_features/01_accounts_and_keepalive/request-changes.md)
  - [2026-11-25 — Giữ & Chờ Request `/v1/*` khi Tài khoản hỗ trợ Capability đang Reset](../../03_features/02_openai_api_and_keys/request-changes.md)
- **Liên kết Spec:**
  - [01_accounts_and_keepalive/spec.md](../../03_features/01_accounts_and_keepalive/spec.md), [logic.md](../../03_features/01_accounts_and_keepalive/logic.md)
  - [02_openai_api_and_keys/spec.md](../../03_features/02_openai_api_and_keys/spec.md), [logic.md](../../03_features/02_openai_api_and_keys/logic.md)
- **Mục tiêu:** Loại bỏ hoàn toàn race condition giữa đặt chỗ Reset và điều phối request `/v1/*` qua khóa nguyên tử `_resetting_accounts` + `in_flight` dưới cùng `WSSPool._lock`, siết kiểm tra bảo vệ pool của Auto-Reset theo từng `supported_models` (`healthy_available_count(capability) >= 2`), và bổ sung cơ chế giữ & chờ request `/v1/*` khi tài khoản hỗ trợ capability đang `resetting` (Sync/SSE/Voice Preview chờ trên `Condition` có early-exit `503`, Async Tasks trả ngay `200 queued` và chờ trong worker nền).

## Danh sách tệp cần tạo / chỉnh sửa

- **Config & Env:**
  - `packages/backend/config.py`: thêm `reset_wait_timeout_seconds` (`MUSE2API_RESET_WAIT_TIMEOUT_SECONDS`, mặc định `150.0`, `>= 0.0`) và `reset_max_waiters` (`MUSE2API_RESET_MAX_WAITERS`, mặc định `50`, `>= 1`).
  - `.env.example`: bổ sung cấu hình mẫu `MUSE2API_RESET_WAIT_TIMEOUT_SECONDS=150` và `MUSE2API_RESET_MAX_WAITERS=50`.
- **Backend Services:**
  - `packages/backend/services/wss_pool.py`: thêm `AccountResettingError`, `_resetting_accounts`, `_reset_cond`, `_waiters_count`; triển khai `begin_reset`, `end_reset`, `is_resetting`, `wait_for_in_flight_drain`, `healthy_available_count(capability)`, `can_auto_reset_account(acc)`, `has_resetting_account(capability)`, `ensure_candidate_or_resetting(capability)`, `wait_for_candidate(capability, timeout)`; cập nhật `_track_in_flight`, `_candidate_accounts`, `maintain_tunnels`, `execute_chat`, `stream_chat_events`, `generate_media` (xử lý `AccountResettingError` & chờ lại khi race).
  - `packages/backend/services/reset_service.py`: cập nhật đặt chỗ nguyên tử (`begin_reset(require_idle=False)` cho manual reset, `begin_reset(require_idle=True)` cho auto-reset), drain qua `wait_for_in_flight_drain`, kiểm tra pool qua `can_auto_reset_account`, và đảm bảo bất biến ghi DB `status` cuối trước khi gọi `end_reset()` trong `finally`.
  - `packages/backend/services/voice_preview.py`: cập nhật `get_or_generate_preview` sử dụng `wait_for_candidate("speech", timeout=timeout)` thay cho `ensure_candidate("speech")` (giữ fallback nếu mock).
- **Backend Routers:**
  - `packages/backend/routers/v1_openai.py`: tách luồng Sync/SSE (`_wait_capability_or_503`, dùng `run_in_threadpool` trên route `async def` như `/v1/images/edits` non-async và `/v1/audio/speech`) vs Async Tasks (`_ensure_async_capability_or_503` cho `/v1/videos*`, `/v1/images/tasks`, `async=true` trên `/v1/images/*`); cập nhật `_run_async_media` giữ nguyên `"queued"` trong khi chờ và chỉ chuyển `"running"` trong callback `on_account_selected`.
- **Tests:**
  - `packages/backend/tests/test_muse_reset_and_auto_reset.py`: bổ sung test cho `AC-020` (bảo vệ pool theo `supported_models`) và `AC-021` (atomic reservation & thứ tự ghi DB trước `end_reset`).
  - `packages/backend/tests/test_reset_guard_and_request_wait.py` (tạo mới): kiểm thử đầy đủ `AC-118`, `AC-119`, `AC-120` và race `AccountResettingError`.

## Checklist triển khai (đối chiếu AC)

- [x] **Bước 1 — Cấu hình biến môi trường (`BR-112`):**
  - Thêm `reset_wait_timeout_seconds` và `reset_max_waiters` vào `packages/backend/config.py` và `.env.example`.
- [x] **Bước 2 — Khóa nguyên tử, Drain & Bảo vệ Pool theo Capability (`AC-020`, `AC-021`, `BR-007`, `BR-008`):**
  - Bổ sung `AccountResettingError`, `_resetting_accounts`, `_reset_cond`, `begin_reset`, `end_reset`, `is_resetting`, `wait_for_in_flight_drain`, `healthy_available_count(capability)` và `can_auto_reset_account` vào `WSSPool`.
  - Cập nhật `_track_in_flight` kiểm tra `_resetting_accounts` dưới cùng `_lock` và `notify_all()` khi `in_flight` về `0`.
  - Cập nhật `ResetService`: manual reset đặt `begin_reset(require_idle=False)` + drain qua `_reset_cond`; auto-reset đặt `begin_reset(require_idle=True)` và kiểm tra `can_auto_reset_account`; luôn ghi DB `status` xong rồi mới `end_reset` trong `finally`.
- [x] **Bước 3 — Giữ & Chờ Request trên `WSSPool`, Router `/v1/*` & `VoicePreviewService` (`AC-118`, `AC-119`, `AC-120`, `FR-105`, `BR-111`, `BR-112`):**
  - Bổ sung `has_resetting_account`, `ensure_candidate_or_resetting`, `wait_for_candidate` (với `_waiters_count`, early-exit `503` khi hết tài khoản resetting, timeout `effective_wait`), và xử lý `AccountResettingError` + chờ lại khi race trong `execute_chat`, `stream_chat_events`, `generate_media`.
  - Cập nhật `routers/v1_openai.py` (`_wait_capability_or_503`, `_ensure_async_capability_or_503`, `run_in_threadpool` trên route `async def`, `_run_async_media` giữ `queued` đến khi có ứng viên) và `services/voice_preview.py`.
- [x] **Bước 4 — Kiểm thử tự động (`AC-020`, `AC-021`, `AC-118`..`AC-120`):**
  - Cập nhật `test_muse_reset_and_auto_reset.py` và tạo mới `test_reset_guard_and_request_wait.py`.
  - Chạy `unittest` cho cả các suite mới và toàn bộ backend test suite.

## Kế hoạch kiểm thử

1. **Khóa nguyên tử & Bảo vệ Pool (`test_muse_reset_and_auto_reset.py` — `AC-020`, `AC-021`):**
   - Kiểm tra pool có 2 tài khoản `healthy`: A hỗ trợ `["chat", "speech"]`, B hỗ trợ `["chat"]` → Auto-Reset hoãn A (`insufficient_healthy_pool`) và vẫn cho phép auto-reset B.
   - Kiểm tra `begin_reset(aid, require_idle=True)` trả `False` khi `in_flight > 0`; khi reset đặt chỗ trước, `_track_in_flight(aid)` ném `AccountResettingError`; khi `end_reset(aid)` chạy, DB đã cập nhật `status` trước khi đánh thức waiter.
2. **Giữ & Chờ Request `/v1/*` (`test_reset_guard_and_request_wait.py` — `AC-118`..`AC-120`):**
   - Sync `/v1/chat/completions` (`stream=false` & `stream=true`) và `/v1/audio/speech` chờ khi tài khoản duy nhất đang `resetting` và trả `200 OK` ngay khi `end_reset` kích hoạt; vẫn fail-fast `503` khi `expired` hoặc hết quota.
   - Async `/v1/videos`, `/v1/images/tasks`, `/v1/images/generations` (`async=true`) trả ngay `200 {status: "queued"}`, worker giữ `"queued"` rồi chuyển `"running"` → `"completed"` sau reset, hoặc `"failed"` nếu reset thất bại.
   - Early exit `503` ngay lập tức (không đợi hết timeout) khi reset thất bại làm không còn tài khoản `resetting`.
   - Timeout `MUSE2API_RESET_WAIT_TIMEOUT_SECONDS=0` trả `503` ngay; vượt `MUSE2API_RESET_MAX_WAITERS` trả `503` (`"Too many requests waiting for account reset"`).
   - Race `AccountResettingError` trong `execute_chat` / `generate_media` không làm mất trạng thái `resetting` thành `cooldown` và tự failover sang account khác hoặc chờ reset xong.
3. **Full Backend Test Suite:**
   - Chạy `packages\backend\.venv\Scripts\python.exe -m unittest discover -s packages\backend\tests -v` xác nhận pass toàn bộ các bài test liên quan.
