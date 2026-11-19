# State: Task 015 — Split English Voice Languages by Country (31 Canonical Groups)

- **Trạng thái:** `Completed`
- **Tiến độ:** 100%
- **Ngày tạo:** `2026-11-19`
- **Ngày hoàn thành:** `2026-11-19`
- **Blockers:** Không có.

## Nhật ký thực hiện
- 2026-11-19: Cập nhật `packages/backend/services/voices.py` định nghĩa 31 nhóm ngôn ngữ chuẩn (`ACCENT_TO_LANGUAGE_GROUP`, `ENGLISH_LANGUAGE_GROUPS`, `CANONICAL_LANGUAGE_GROUPS`), tự động expand `English` thành 13 nhóm quốc gia trong `normalize_voice_languages`, và hỗ trợ query `?language=English` khớp cả 13 nhóm.
- 2026-11-19: Cập nhật `packages/backend/routers/admin_core.py` trong `get_settings()` tự động chuẩn hóa qua `normalize_voice_languages` giúp DB cũ có `"English"` bung đủ 13 nhóm trên UI.
- 2026-11-19: Cập nhật `packages/frontend/src/pages/SettingsPage.tsx` nâng cấp responsive grid `grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2` và tooltip title giúp hiển thị rõ ràng 31 mục ngôn ngữ.
- 2026-11-19: Cập nhật test suite `packages/backend/tests/test_audio_voices_and_speech.py` kiểm tra toàn bộ 31 nhóm chuẩn, phân bố 1,218 giọng, expand DB cũ, query param `language`, và chặn speech với giọng US khi chỉ bật UK (không fallback). Toàn bộ 24/24 backend tests PASS.
- 2026-11-19: Build frontend `npm --prefix packages/frontend run build` thành công 100% không lỗi.
