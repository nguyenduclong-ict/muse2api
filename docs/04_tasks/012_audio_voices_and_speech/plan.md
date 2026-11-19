# Task 012: Audio Voices & Speech (TTS) Endpoints + Console Support

- **Nguồn thay đổi:** [02_openai_api_and_keys/request-changes.md](../../03_features/02_openai_api_and_keys/request-changes.md#2026-11-19--bổ-sung-endpoints-v1audiovoices-và-v1audiospeech-tts), [03_tasks_and_media/request-changes.md](../../03_features/03_tasks_and_media/request-changes.md#2026-11-19--hỗ-trợ-bộ-lọc-task-audio-và-trình-phát-audio-preview)
- **Liên kết Spec:** [02_openai_api_and_keys/spec.md](../../03_features/02_openai_api_and_keys/spec.md), [02_openai_api_and_keys/logic.md](../../03_features/02_openai_api_and_keys/logic.md), [03_tasks_and_media/spec.md](../../03_features/03_tasks_and_media/spec.md)
- **Mục tiêu:** Triển khai `GET /v1/audio/voices` (danh mục giọng Muse TTS có lọc) và `POST /v1/audio/speech` (sinh giọng nói `.mp3` qua Muse WSS hỗ trợ emotion cues & `instructions`), cập nhật model aliases và đồng bộ giao diện Console (`ApiKeysPage`, `TasksMediaPage`).

## Danh sách tệp tạo mới / chỉnh sửa

- **Tạo mới:**
  - `packages/backend/data/voices.json`: Danh sách giọng Muse TTS tĩnh (1218 giọng, đã loại bỏ `avocado_v2:p1a1_short` và các trường nội bộ `aesthetics_mean*`, `adherence_mean`).
  - `packages/backend/services/voices.py`: Loader, bộ lọc `list_voices(...)` và hàm phân giải `resolve_voice(voice_input)` kèm bảng `OPENAI_VOICE_ALIASES`.
  - `packages/backend/tests/test_audio_voices_and_speech.py`: Bộ kiểm thử tự động 11 bài test (Voices Catalog, Prompt Builder, Auth, Validations, Mocked Execution Binary MP3 & JSON URL).
- **Chỉnh sửa:**
  - `packages/backend/services/wss_pool.py`: Thêm cờ `skip_system_prompt: bool = False` vào `_build_chat_items` / `generate_media`; cập nhật `_fetch_media_from_history` hỗ trợ `expect_kind="audio"` (nhận diện `audio/*`, `.mp3`/`.wav`/`.ogg`/`.m4a`, `payload.data.audios|audio|files`, mặc định `.mp3` / `audio/mpeg`).
  - `packages/backend/routers/v1_openai.py`: Bổ sung alias `muse-tts`, `tts-1`, `tts-1-hd`, `gpt-4o-mini-tts` vào `_MODELS`; thêm `GET /v1/audio/voices` và `POST /v1/audio/speech` với hàm `_build_speech_prompt`.
  - `packages/frontend/src/pages/ApiKeysPage.tsx`: Thêm tài liệu collapsible Input/Output cho `GET /v1/audio/voices` và `POST /v1/audio/speech`.
  - `packages/frontend/src/pages/TasksMediaPage.tsx`: Thêm option `audio` vào bộ lọc Type của Tasks; hỗ trợ icon/badge audio và trình phát `<audio controls>` trong modal Preview của Media Library.
  - `.gitignore`: Cập nhật cho phép theo dõi `packages/backend/data/voices.json`.

## Checklist triển khai (đối chiếu AC)

- [x] **Bước 1 — Dữ liệu giọng & Voice Service (`AC-107`, `BR-106`, `BR-109`):**
  - Tạo `packages/backend/data/voices.json` từ danh sách giọng được cung cấp, loại bỏ `avocado_v2:p1a1_short` và chỉ giữ các trường sạch (`id`, `name`, `gender`, `accent`, `tone`, `language`, `description`, `long_description`).
  - Tạo `packages/backend/services/voices.py` hỗ trợ `list_voices(gender, accent, language, tone, q)` và `resolve_voice(voice)` (exact `id`, case-insensitive `name`, OpenAI preset aliases `alloy`/`echo`/`fable`/`onyx`/`nova`/`shimmer`, mặc định `avocado_v2:MAI_01`).
- [x] **Bước 2 — WSS Audio Pipeline (`AC-108`, `BR-107`):**
  - Cập nhật `WSSPool._build_chat_items` và `WSSPool.generate_media` nhận `skip_system_prompt: bool = False` (TTS không tiêm Global System Prompt).
  - Cập nhật `WSSPool._fetch_media_from_history` ưu tiên trích xuất resource `audio` / `.mp3` khi `expect_kind == "audio"`, đặt tên file `aud_<hex>.mp3` và trả `mime_type="audio/mpeg"`.
- [x] **Bước 3 — API `/v1/audio/voices`, `/v1/audio/speech` & `/v1/models` (`AC-107`..`AC-110`, `BR-106`..`BR-108`):**
  - Bổ sung `muse-tts`, `tts-1`, `tts-1-hd`, `gpt-4o-mini-tts` vào `_MODELS`.
  - Triển khai `GET /v1/audio/voices` (có `require_v1_api_key`).
  - Triển khai `POST /v1/audio/speech` (có `require_v1_api_key`): validate `input` (1..4096 ký tự), `response_format` (`mp3` | `url` | `json`), `voice`; dựng prompt TTS giữ inline emotion cues + `instructions` + `speed`; ghi task `type="audio"` vào SQLite; trả binary `audio/mpeg` (kèm header `X-Muse-Media-Url`) hoặc JSON khi `response_format` là `url`/`json`.
- [x] **Bước 4 — Frontend Console (`AC-110`, `AC-206`):**
  - Cập nhật `ENDPOINTS` trong `ApiKeysPage.tsx` cho `GET /v1/audio/voices` và `POST /v1/audio/speech`.
  - Cập nhật `TasksMediaPage.tsx`: thêm filter `audio` cho Tasks, hiển thị thumbnail audio và trình phát `<audio controls>` trong modal Preview.
- [x] **Bước 5 — Tự động hóa kiểm thử & xác minh (`AC-107`..`AC-110`, `AC-206`):**
  - Chạy bộ kiểm thử backend 11/11 tests qua `packages/backend/tests/test_audio_voices_and_speech.py` đạt 100% OK.
  - Chạy `npm --prefix packages/frontend run build` đạt 0 lỗi TypeScript & Vite build.
