# Task 015: Split English Voice Languages by Country (31 Canonical Groups)

- **Nguồn thay đổi:** [04_settings_and_cleanup/request-changes.md](../../03_features/04_settings_and_cleanup/request-changes.md#2026-11-19--tách-nhóm-english-1000-theo-từng-quốc-gia-31-nhóm-chuẩn), [02_openai_api_and_keys/request-changes.md](../../03_features/02_openai_api_and_keys/request-changes.md#2026-11-19--tách-lọc-english-theo-quốc-gia--giữ-tương-thích-ngược-query-languageenglish)
- **Liên kết Spec:** [04_settings_and_cleanup/spec.md](../../03_features/04_settings_and_cleanup/spec.md), [04_settings_and_cleanup/design.md](../../03_features/04_settings_and_cleanup/design.md), [04_settings_and_cleanup/logic.md](../../03_features/04_settings_and_cleanup/logic.md), [02_openai_api_and_keys/spec.md](../../03_features/02_openai_api_and_keys/spec.md), [02_openai_api_and_keys/logic.md](../../03_features/02_openai_api_and_keys/logic.md)
- **Mục tiêu:** Tách nhóm `English (1,000)` thành 13 nhóm quốc gia Tiếng Anh (`English (US)`, `English (UK)`, `English (Australia)`, ...) cộng 17 ngôn ngữ khác (giữ gộp `French (35)`) và `Other` (`Transylvanian`, 1) thành **31 nhóm chuẩn** phủ đủ 1,218 giọng, đồng thời duy trì tương thích ngược cho cấu hình DB cũ `"English"` và query `GET /v1/audio/voices?language=English`.

## Danh sách tệp chỉnh sửa

- **Backend:**
  - `packages/backend/services/voices.py`:
    - Cập nhật `ACCENT_TO_LANGUAGE_GROUP`, thêm hằng `ENGLISH_LANGUAGE_GROUPS` (13 nhóm `English (*)`) và cập nhật `CANONICAL_LANGUAGE_GROUPS` thành 31 nhóm chuẩn (mặc định fallback `"Other"` khi gặp accent chưa biết).
    - Cập nhật `normalize_voice_languages(...)`: tự động mở rộng `"English"` (case-insensitive) thành toàn bộ 13 nhóm trong `ENGLISH_LANGUAGE_GROUPS`, loại trùng và lọc giá trị không hợp lệ.
    - Cập nhật `list_voices(...)`: khi client truyền query `language="English"` (case-insensitive), khớp toàn bộ các giọng thuộc 13 nhóm `English (*)`; vẫn khớp exact case-insensitive với tên nhóm chuẩn (`English (US)`, `Vietnamese`, `Other`, ...) và mã gốc `eng`/`fra`.
  - `packages/backend/routers/admin_core.py`:
    - Trong `GET /admin/settings`: chuẩn hóa `settings["voice_languages"]["languages"]` qua `normalize_voice_languages(...)` để cấu hình DB cũ có `"English"` hiển thị đúng 13 nhóm `English (*)` trên UI.
  - `packages/backend/tests/test_audio_voices_and_speech.py`:
    - Cập nhật unit tests & integration tests theo 31 nhóm chuẩn (`English (US)` = 541, `English (UK)` = 200, `Other` = 1, tổng = 1,218), kiểm tra expand `"English"` từ DB cũ, query `?language=English` / `?language=English (US)`, và chặn `Aria` (`English (US)`) khi chỉ bật `English (UK)`.
- **Frontend:**
  - `packages/frontend/src/pages/SettingsPage.tsx`:
    - Rà soát lưới hiển thị 31 nhóm (đảm bảo tên dài như `English (South Africa)`, `English (New Zealand)` hiển thị rõ ràng, không bị cắt mất ý nghĩa trên desktop/mobile; điều chỉnh grid columns `grid-cols-2 sm:grid-cols-3 lg:grid-cols-4` nếu cần).

## Checklist triển khai (đối chiếu AC)

- [x] **Bước 1 — Cập nhật 31 nhóm chuẩn & tương thích ngược trong `voices.py` (`BR-303`, `BR-304`, `FR-111`):**
  - Cập nhật `ACCENT_TO_LANGUAGE_GROUP`, `ENGLISH_LANGUAGE_GROUPS`, `CANONICAL_LANGUAGE_GROUPS` (đủ 31 nhóm, tổng đúng 1,218 giọng).
  - Cập nhật `normalize_voice_languages` tự động mở rộng `"English"` thành 13 nhóm `English (*)`.
  - Cập nhật `list_voices` hỗ trợ query `language="English"` khớp toàn bộ 13 nhóm `English (*)`.
- [x] **Bước 2 — Đồng bộ `GET /admin/settings` (`BR-304`, `AC-303`, `AC-304`):**
  - Chuẩn hóa `voice_languages.languages` khi trả về ở `GET /admin/settings` để DB cũ lưu `"English"` tự động bung thành 13 nhóm `English (*)`.
- [x] **Bước 3 — Tối ưu bố cục lưới 31 mục trên `SettingsPage.tsx` (`FR-304`, `AC-303`):**
  - Điều chỉnh grid responsive để tên nhóm như `English (South Africa)` / `English (Australia)` dễ đọc trên các kích thước màn hình.
- [x] **Bước 4 — Cập nhật kiểm thử tự động & xác minh build (`AC-111`, `AC-112`, `AC-303`, `AC-304`):**
  - Cập nhật và chạy `packages/backend/tests/test_audio_voices_and_speech.py`.
  - Chạy `npm --prefix packages/frontend run build` đảm bảo 0 lỗi.

## Kế hoạch kiểm thử

1. **Unit & Integration Tests (`unittest` + ASGI):**
   - `list_available_voice_languages()` trả đúng `31` nhóm, tổng `1218` giọng (`English (US)` = 541, `English (UK)` = 200, `English (Australia)` = 73, `French` = 35, `Vietnamese` = 7, `Japanese` = 6, `Other` = 1).
   - `normalize_voice_languages(["English", "Vietnamese"])` mở rộng thành 13 nhóm `English (*)` + `"Vietnamese"` (= 14 nhóm).
   - `GET /admin/settings` khi DB cũ lưu `["English"]` trả về đúng 13 nhóm `English (*)`.
   - Bật `["English (US)", "Vietnamese", "Japanese"]`: `GET /v1/audio/voices` trả `554` giọng; `?language=English` trả `541` giọng; `?language=English (UK)` hoặc `?accent=British` trả `0` giọng; `?language=Vietnamese` trả `7` giọng.
   - Bật `["English (UK)", "Vietnamese", "Japanese"]`: `POST /v1/audio/speech` với `voice="Aria"`, `voice="alloy"`, hoặc bỏ trống `voice` đều trả `400` (không fallback).
2. **Frontend Build:**
   - `npm --prefix packages/frontend run build` thành công 0 lỗi.
