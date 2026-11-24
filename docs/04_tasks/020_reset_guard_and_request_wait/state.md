# State: Task 020 — Khóa nguyên tử chống race Reset, Bảo vệ Pool theo `supported_models` & Giữ/Chờ Request `/v1/*`

- **Trạng thái:** `Completed`
- **Tiến độ:** 100%
- **Ngày tạo:** `2026-11-25`
- **Ngày hoàn thành:** `2026-11-25`
- **Blockers:** Không có.

## Nhật ký thực hiện

- 2026-11-25: Khởi tạo Task 020 từ 2 Change Request (`01_accounts_and_keepalive` và `02_openai_api_and_keys`).
- 2026-11-25: Triển khai cấu hình `MUSE2API_RESET_WAIT_TIMEOUT_SECONDS=150`, `MUSE2API_RESET_MAX_WAITERS=50` (`config.py`, `.env.example`), khóa nguyên tử `_resetting_accounts` + `_reset_cond` + `wait_for_candidate` + `can_auto_reset_account` (`services/wss_pool.py`, `services/reset_service.py`), và luồng chờ Sync/SSE/Async/Preview (`routers/v1_openai.py`, `services/voice_preview.py`).
- 2026-11-25: Kiểm thử toàn bộ backend test suite (`unittest discover -s packages\backend\tests -v`): 97/97 passed (100%), bao gồm `test_muse_reset_and_auto_reset.py` (`AC-020`, `AC-021`) và `test_reset_guard_and_request_wait.py` (`AC-118`..`AC-120`).
