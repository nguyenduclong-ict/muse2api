# Task 016: API Playground & Voice Preview Cache

- **Liên kết Spec:** [06_api_playground/spec.md](../../03_features/06_api_playground/spec.md), [06_api_playground/design.md](../../03_features/06_api_playground/design.md), [06_api_playground/logic.md](../../03_features/06_api_playground/logic.md)
- **Mục tiêu:** Xây dựng API nghe thử mẫu giọng đọc TTS có cache đĩa bền vững (`GET /v1/audio/voices/{voice_id}/preview` + quản trị cache) và màn hình **Playground** (`/playground`, `SCR-07`) trong Admin Console cho phép kiểm thử trực tiếp 4 nhóm API `/v1/*` (Chat, Images, Video, Audio & Voices) kèm xem/copy `cURL` & `Raw Response`.

## Danh sách tệp cần tạo / chỉnh sửa

- **Backend:**
  - `packages/backend/config.py`: Thêm property `voice_preview_dir` (`data/voice_previews`).
  - `packages/backend/services/voice_preview.py` *(mới)*: Cài đặt `VoicePreviewService` (chuẩn hóa tên file an toàn, bảng câu mẫu cố định theo nhóm ngôn ngữ, in-flight lock theo `voice_id`, ghi file nguyên tử `.tmp` → `.mp3`, ghi log `tasks` khi cache miss, thống kê & xóa cache).
  - `packages/backend/main.py`: Tạo thư mục `cfg.voice_preview_dir` khi khởi động và gắn `app.state.voice_preview` vào state.
  - `packages/backend/routers/v1_openai.py`:
    - Cập nhật `GET /v1/audio/voices` (và `/v1/voices`) trả thêm `language_group`, `cached`, `preview_url`.
    - Thêm `GET /v1/audio/voices/{voice_id:path}/preview` (hỗ trợ `response_format=mp3|url|json`, `refresh=true|false`, header `X-Voice-Preview-Cache: HIT|MISS`).
    - Thêm `GET /v1/voice-previews/{filename}` phục vụ file `.mp3` đã cache.
  - `packages/backend/routers/admin_core.py`: Thêm `GET /admin/voices/preview/stats`, `DELETE /admin/voices/preview`, `DELETE /admin/voices/preview/{voice_id:path}`.
  - `packages/backend/tests/test_voice_preview_cache.py` *(mới)*: Unit & integration tests cho Voice Preview API, cache hit/miss, `refresh=true`, in-flight lock, `CleanupService` isolation và các endpoint `/admin/voices/preview*`.
- **Frontend:**
  - `packages/frontend/src/components/Layout.tsx`: Thêm mục điều hướng **Playground** (`/playground`) ngay dưới **API & Keys**.
  - `packages/frontend/src/App.tsx`: Khai báo route `/playground` trỏ tới `PlaygroundPage`.
  - `packages/frontend/src/pages/PlaygroundPage.tsx` *(mới)*: Màn hình Playground với 4 tab (Chat, Images, Video, Audio & Voices), giữ state trong phiên khi chuyển tab, tự động dùng API Key từ `GET /admin/apikey`, kèm ngăn xem/copy `cURL` & `Raw Response`.
  - `packages/frontend/src/pages/ApiKeysPage.tsx`: Bổ sung tài liệu endpoint `GET /v1/audio/voices/{voice_id}/preview` vào danh sách schema endpoints.

## Checklist triển khai (đối chiếu AC)

- [x] **Bước 1 — Backend Config & `VoicePreviewService` (`FR-501`, `BR-501`–`BR-505`):**
  - Thêm `voice_preview_dir` vào `config.py` và khởi tạo trong `main.py`.
  - Tạo `services/voice_preview.py` với `safe_preview_filename`, bảng câu mẫu theo 31 nhóm ngôn ngữ, in-flight lock, atomic replace, và ghi log `tasks` khi cache miss.
- [x] **Bước 2 — API `/v1/audio/voices/{voice_id}/preview` & `/admin/voices/preview*` (`FR-501`–`FR-503`, `AC-501`–`AC-506`):**
  - Mở rộng `GET /v1/audio/voices` trả thêm `language_group`, `cached`, `preview_url`.
  - Thêm `GET /v1/audio/voices/{voice_id:path}/preview` và `GET /v1/voice-previews/{filename}`.
  - Thêm các route quản trị cache trong `admin_core.py`.
- [x] **Bước 3 — Frontend Sidebar, Routing & `PlaygroundPage` (`FR-504`–`FR-509`, `BR-506`, `AC-507`, `AC-508`):**
  - Thêm link Sidebar `/playground` và route trong `App.tsx`.
  - Xây dựng tab **Chat** (`/v1/chat/completions` & `/v1/responses`, SSE streaming, Stop, đính kèm ảnh).
  - Xây dựng tab **Images** (`generations` & `edits`, upload/URL ảnh tham chiếu, sync/async polling).
  - Xây dựng tab **Video** (`POST /v1/videos` + auto-poll `GET /v1/videos/{id}` + video player).
  - Xây dựng tab **Audio & Voices** (Voice Catalog lọc/tìm kiếm/phân trang, nút duy nhất `Preview` và `Use`, form `POST /v1/audio/speech` + emotion cues + audio player).
  - Thêm ngăn `cURL & Raw Response` trên từng tab và cập nhật `ApiKeysPage.tsx`.
- [x] **Bước 4 — Kiểm thử tự động & xác minh trình duyệt (`AC-501`–`AC-508`):**
  - Viết và chạy `packages/backend/tests/test_voice_preview_cache.py` cùng toàn bộ test suite backend (32/32 tests pass).
  - Chạy `npm --prefix packages/frontend run build` đảm bảo 0 lỗi TypeScript/Vite.
  - Xác minh trực tiếp trên trình duyệt tại `/playground` với cả 4 tab và luồng Voice Preview.

## Kế hoạch kiểm thử

1. **Unit & Integration Tests (`unittest` + ASGI):**
   - Cache MISS lần đầu tạo `data/voice_previews/<safe>.mp3`, trả `audio/mpeg`, `X-Voice-Preview-Cache: MISS`, ghi 1 task vào SQLite (`AC-501`).
   - Cache HIT lần hai không gọi Muse WSS, không tạo task mới, trả `X-Voice-Preview-Cache: HIT` (`AC-502`).
   - `response_format=url` trả JSON đúng cấu trúc và tải được file qua `/v1/voice-previews/{filename}` (`AC-503`).
   - `refresh=true` gọi lại Muse, ghi đè file và trả `X-Voice-Preview-Cache: MISS` (`AC-504`).
   - `CleanupService.run_now()` không xóa file trong `data/voice_previews/` (`AC-505`).
   - `GET /v1/audio/voices` cập nhật đúng cờ `cached` và `preview_url` (`AC-506`).
   - `DELETE /admin/voices/preview` và `DELETE /admin/voices/preview/{voice_id}` hoạt động chính xác (`AC-508`).
2. **Frontend Build & Browser Verification:**
   - `npm --prefix packages/frontend run build` thành công 0 lỗi.
   - Kiểm tra trực tiếp trên trình duyệt tại `/playground`: chuyển đổi 4 tab giữ nguyên state, hiển thị cURL, lọc/nghe thử giọng đọc và xóa cache preview (`AC-507`, `AC-508`).
