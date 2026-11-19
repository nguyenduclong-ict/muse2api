# Task 013: Voice Languages Filter (Settings & TTS Voices/Speech)

- **Nguồn thay đổi:** [04_settings_and_cleanup/request-changes.md](../../03_features/04_settings_and_cleanup/request-changes.md#2026-11-19--bổ-sung-cài-đặt-lọc-ngôn-ngữ-giọng-đọc-tts-voice_languages), [02_openai_api_and_keys/request-changes.md](../../03_features/02_openai_api_and_keys/request-changes.md#2026-11-19--áp-dụng-cài-đặt-lọc-ngôn-ngữ-giọng-đọc-voice_languages-cho-v1audiovoices-và-v1audiospeech)
- **Liên kết Spec:** [04_settings_and_cleanup/spec.md](../../03_features/04_settings_and_cleanup/spec.md), [04_settings_and_cleanup/design.md](../../03_features/04_settings_and_cleanup/design.md), [04_settings_and_cleanup/logic.md](../../03_features/04_settings_and_cleanup/logic.md), [02_openai_api_and_keys/spec.md](../../03_features/02_openai_api_and_keys/spec.md), [02_openai_api_and_keys/logic.md](../../03_features/02_openai_api_and_keys/logic.md)
- **Mục tiêu:** Cho phép admin cấu hình danh sách ngôn ngữ giọng đọc TTS muốn hỗ trợ trên màn hình **Settings** (`SCR-05`), lưu bền vững vào SQLite (`settings.voice_languages`), và áp dụng lọc nghiêm ngặt ngay lập tức cho cả `GET /v1/audio/voices` (`/v1/voices`) và `POST /v1/audio/speech` (trả `400`, không fallback).

## Danh sách tệp chỉnh sửa

- **Backend:**
  - `packages/backend/services/voices.py`:
    - Bổ sung bảng ánh xạ `ACCENT_TO_LANGUAGE_GROUP` (36 accent + `fra` → 18 nhóm ngôn ngữ chuẩn, tổng 1,218 giọng).
    - Bổ sung các hàm: `get_voice_language_group(voice)`, `list_available_voice_languages()`, `normalize_voice_languages(languages)`, `is_voice_allowed(voice, allowed_languages)`.
    - Cập nhật `list_voices(...)` nhận thêm tham số `allowed_languages: list[str] | set[str] | None = None` và mở rộng bộ lọc `language=` khớp cả mã gốc (`eng`/`fra`) lẫn tên nhóm ngôn ngữ (`English`, `Vietnamese`, `Japanese`, ...).
  - `packages/backend/db.py`:
    - Bổ sung giá trị mặc định `voice_languages: {"enabled": False, "languages": []}` trong `init_schema()` (và đảm bảo `get_settings()` luôn có fallback mặc định nếu DB cũ chưa có key).
  - `packages/backend/routers/admin_core.py`:
    - Thêm Pydantic model `VoiceLanguagesUpdate(enabled: bool, languages: list[str])` vào `SettingsPatchReq`.
    - Cập nhật `GET /admin/settings`: trả kèm `voice_languages` và `available_voice_languages`.
    - Cập nhật `POST /admin/settings`: chuẩn hóa `languages` qua `normalize_voice_languages(...)` và lưu vào `settings` (`key="voice_languages"`).
  - `packages/backend/routers/v1_openai.py`:
    - Viết helper `_get_allowed_voice_languages(db) -> list[str]` (trả về danh sách rỗng khi `enabled=False` hoặc `languages=[]`).
    - Cập nhật `GET /v1/audio/voices` (`/v1/voices`): truyền `allowed_languages` vào `list_voices(...)` để lọc giao **AND** với các query params của client.
    - Cập nhật `POST /v1/audio/speech`: sau khi `resolve_voice(body.voice)` thành công, kiểm tra `is_voice_allowed(voice_info, allowed_languages)`; nếu không hợp lệ (kể cả khi client bỏ trống `voice` và mặc định `Aria` nằm ngoài tập ngôn ngữ đang bật) thì trả `400 Bad Request` (`invalid_request_error`), **không fallback**.
  - `packages/backend/tests/test_audio_voices_and_speech.py`:
    - Bổ sung unit tests & integration tests cho 18 nhóm ngôn ngữ, `/admin/settings`, lọc `GET /v1/audio/voices` (lọc giao AND & query `?language=Vietnamese`), và chặn `POST /v1/audio/speech` (trả `400` không fallback khi `English` tắt).
- **Frontend:**
  - `packages/frontend/src/pages/SettingsPage.tsx`:
    - Cập nhật `SettingsData` interface nhận `voice_languages` và `available_voice_languages`.
    - Thêm card **Voice Languages** theo wireframe `design.md`: công tắc `Switch` bật/tắt, lưới 18 ngôn ngữ kèm số lượng giọng (`English (1000)`, `Vietnamese (7)`, ...), tổng số ngôn ngữ & giọng đang chọn, nút `Select All`, `Clear`, và `Save Voice Languages`.

## Checklist triển khai (đối chiếu AC)

- [x] **Bước 1 — Phân nhóm 18 Ngôn ngữ trong Voices Service (`BR-303`, `BR-304`):**
  - Định nghĩa ánh xạ đủ 36 accent + `fra` → 18 nhóm ngôn ngữ (đảm bảo tổng count = 1,218 giọng, không bỏ sót).
  - Cài đặt `get_voice_language_group`, `list_available_voice_languages`, `normalize_voice_languages`, `is_voice_allowed`.
  - Cập nhật `list_voices(...)` hỗ trợ `allowed_languages` và mở rộng query `language` nhận cả tên nhóm lẫn `eng`/`fra`.
- [x] **Bước 2 — Lưu trữ & Admin Settings API (`FR-304`, `BR-304`, `AC-303`, `AC-304`):**
  - Thêm default `voice_languages` vào `db.py`.
  - Mở rộng `GET /admin/settings` và `POST /admin/settings` trong `admin_core.py` có chuẩn hóa danh sách ngôn ngữ.
- [x] **Bước 3 — Áp dụng lọc trên `/v1/audio/voices` & `/v1/audio/speech` (`FR-111`, `FR-112`, `BR-110`, `AC-111`, `AC-112`):**
  - Cập nhật `get_audio_voices` đọc `voice_languages` từ DB và lọc giao AND.
  - Cập nhật `create_speech` kiểm tra ngôn ngữ của giọng sau phân giải; trả `400 Bad Request` nếu nằm ngoài danh sách bật (không fallback khi bỏ trống `voice`).
- [x] **Bước 4 — Giao diện Settings Console (`FR-304`, `AC-303`, `AC-304`):**
  - Thêm card **Voice Languages** trong `SettingsPage.tsx` (Switch, grid chọn ngôn ngữ có số lượng giọng, Select All / Clear / Save, toast phản hồi).
- [x] **Bước 5 — Kiểm thử tự động & Xác minh (`AC-111`, `AC-112`, `AC-303`, `AC-304`):**
  - Chạy toàn bộ test suite `packages/backend/tests/test_audio_voices_and_speech.py` (17/17 tests passed).
  - Chạy `npm --prefix packages/frontend run build` (`tsc -b && vite build`) hoàn thành 0 lỗi.
