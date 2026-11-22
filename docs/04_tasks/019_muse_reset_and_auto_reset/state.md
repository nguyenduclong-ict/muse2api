# State: Task 019 — Reset Muse thủ công & Auto-Reset định kỳ theo tài khoản

- **Trạng thái:** `Completed`
- **Tiến độ:** 100%
- **Ngày tạo:** `2026-11-22`
- **Ngày hoàn thành:** `2026-11-22`
- **Blockers:** Không có.

## Nhật ký thực hiện

- 2026-11-22: Khởi tạo Task 019 từ đặc tả `01_accounts_and_keepalive` và `04_settings_and_cleanup`.
- 2026-11-22: Triển khai đầy đủ schema/migration DB (`db.py`), giao thức `replace-vm` (`muse_wss.py`), `in_flight` tracking & `requests_since_reset` (`services/wss_pool.py`), `ResetService` (`services/reset_service.py`), routes (`routers/accounts.py`, `routers/admin_core.py`), lifespan (`main.py`), và UI (`AccountsPage.tsx`, `OverviewPage.tsx`, `SettingsPage.tsx`).
- 2026-11-22: Kiểm thử `test_muse_reset_and_auto_reset.py` (6/6 passed); full backend suite 67/68 passed (1 pre-existing failure `test_is_voice_allowed_and_filter`: `23 != 13` trong `test_audio_voices_and_speech.py` ngoài phạm vi task); `npm --prefix packages/frontend run build` (`tsc -b && vite build`) thành công.
