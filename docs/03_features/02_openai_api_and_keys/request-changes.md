# Request changes: OpenAI-Compatible API (`/v1/*`) & API Key

## 2026-11-19 — Hỗ trợ `response_format="wav"` + `"mp3"` cho `POST /v1/audio/speech` (tiêm prompt + fallback `ffmpeg`)

- **Yêu cầu:** Hỗ trợ sinh và trả về định dạng `.wav` (16-bit PCM) song song với `.mp3` trên `POST /v1/audio/speech` cho các client như `../cartoonkit`, theo cơ chế tiêm định dạng đích vào prompt gửi Muse, kiểm tra định dạng thực tế qua header/magic bytes và tự động chạy `ffmpeg` convert fallback nếu Muse trả không đúng định dạng yêu cầu; giữ nguyên từ chối `400` với các định dạng khác (`opus`, `aac`, `flac`, `pcm`).
- **Phân loại:** Feature mở rộng
- **Đặc tả thay đổi:**
  - `spec.md`: cập nhật Phạm vi (`Out of Scope` bỏ `wav`), `FR-112`, `BR-107`, `BR-108`, `AC-109`.
  - `logic.md`: cập nhật Mục 5 bổ sung `output_format` trong `build_speech_prompt`, kiểm tra magic bytes / PCM16 WAV và `ffmpeg` fallback (`services/audio_format.py`).
  - `../../02_basic_design/01_api_overview.md`: cập nhật mô tả `POST /v1/audio/speech` hỗ trợ `.mp3`/`.wav` binary và `url` JSON.
- **Quyết định:** Chỉ hỗ trợ 2 định dạng audio nhị phân (`mp3`, `wav`) cùng `url`/`json`; cài `ffmpeg` trong `Dockerfile`; xác thực RIFF/WAVE 16-bit PCM bằng thư viện `wave` và MP3 qua `ID3`/MPEG sync frame thay vì chỉ tin phần mở rộng file; cập nhật `tasks.media_filename` sau bước kiểm tra/convert để khớp tệp lưu thực tế.
- **Task:** triển khai trực tiếp

## 2026-11-19 — Trả trường `long_description` trên `GET /v1/audio/voices` & Đồng bộ catalog giọng tuyển chọn

- **Yêu cầu:** Endpoint `GET /v1/audio/voices` (và alias `/v1/voices`) bắt buộc trả trường `long_description` (mô tả chi tiết âm vực, phong cách, sắc thái và đối tượng giọng nói) cho các agent và client tiêu thụ; bảo toàn danh mục `voices.json` đã được tuyển chọn (280 giọng đại diện phân bố đều theo 31 nhóm ngôn ngữ).
- **Phân loại:** Feature mở rộng & Fix tương thích dữ liệu
- **Đặc tả thay đổi:**
  - `spec.md`: cập nhật `FR-111` khẳng định payload trả về bao gồm `long_description`.
  - `packages/backend/routers/v1_openai.py`: định nghĩa tường minh `long_description: v.get("long_description", "")` trong danh sách trả về của `get_audio_voices`.
  - `packages/frontend/src/pages/ApiKeysPage.tsx`: cập nhật output schema mẫu của `GET /v1/audio/voices` có trường `description` và `long_description`.
  - `packages/frontend/src/pages/PlaygroundPage.tsx`: bổ sung `long_description` vào interface `VoiceItem`, tìm kiếm theo `long_description`, hiển thị tooltip/dòng phụ trên bảng danh sách giọng và thẻ mô tả của giọng đang chọn.
- **Quyết định:** Giữ nguyên danh mục 280 giọng tiêu biểu do người dùng đã tuyển chọn; fallback `resolve_voice(None)` về giọng đầu tiên của catalog thay vì hardcode giọng không tồn tại; kiểm thử 100% trường `long_description` hiện diện trên toàn bộ các giọng.
- **Task:** [T-016](../../04_tasks/016_api_playground_and_voice_preview/plan.md)

## 2026-11-19 — Tách lọc `English` theo quốc gia & giữ tương thích ngược query `?language=English`

- **Yêu cầu:** Cập nhật bộ lọc `voice_languages` trên `/v1/audio/voices` và `/v1/audio/speech` theo 31 nhóm chuẩn sau khi tách `English` thành 13 quốc gia (vd `English (US)`, `English (UK)`...), đồng thời vẫn hỗ trợ query `?language=English` khớp tất cả các nhóm `English (*)`.
- **Phân loại:** Feature mở rộng
- **Đặc tả thay đổi:**
  - `spec.md`: cập nhật `FR-111`, `AC-111`, `AC-112`.
  - `logic.md`: cập nhật Mục 4 (mở rộng `"English"` từ cấu hình DB cũ và hỗ trợ query `?language=English` khớp 13 nhóm `English (*)`).
- **Quyết định:** Giữ tương thích ngược cho query `?language=English` và cấu hình DB cũ có `"English"`, đồng thời siết kiểm tra đúng theo quốc gia đã bật trên `POST /v1/audio/speech` (vd chỉ bật `English (UK)` sẽ từ chối `Aria` thuộc `English (US)` với `400`, không fallback).
- **Task:** [T-015](../../04_tasks/015_voice_languages_by_country/plan.md)

## 2026-11-19 — Điều phối pool theo model hỗ trợ của tài khoản (`chat`, `image`, `video`, `speech`) & Fail-Fast `503`

- **Yêu cầu:** Không chọn các tài khoản không bật loại model tương ứng khi điều phối request `/v1/*` (`chat`, `image`, `video`, `speech`), và phản hồi lỗi rõ ràng khi không có tài khoản hỗ trợ.
- **Phân loại:** Feature mở rộng
- **Đặc tả thay đổi:**
  - `spec.md`: cập nhật `FR-105`; bổ sung `BR-111`, `AC-113`, `AC-114`.
  - `logic.md`: cập nhật Sequence Diagram và Mục 2 (`_candidate_accounts(capability)`, `_no_candidate_error(capability)`, `NoCandidateAccountError` / `ensure_candidate` fail-fast `503`).
  - `../../00_common/conventions.md`: bổ sung mã trạng thái `503` vào chuẩn lỗi `/v1/*`.
- **Quyết định:** Phân loại cố định theo nhóm endpoint đầu ra (`chat`: `/v1/chat/completions` kể cả kèm `image_url`, `/v1/responses`; `image`: `/v1/images/*`; `video`: `/v1/videos*`; `speech`: `/v1/audio/speech`). Áp dụng fail-fast `503 Service Unavailable` ngay trước khi mở SSE stream hoặc tạo task async (`queued`) để tránh tạo bản ghi task chắc chắn thất bại.
- **Task:** [T-014](../../04_tasks/014_account_supported_models/plan.md)

## 2026-11-19 — Áp dụng cài đặt lọc ngôn ngữ giọng đọc (`voice_languages`) cho `/v1/audio/voices` và `/v1/audio/speech`

- **Yêu cầu:** Khi admin cấu hình danh sách ngôn ngữ hỗ trợ trong Settings (ví dụ Tiếng Anh, Tiếng Việt, Tiếng Nhật), endpoint `GET /v1/audio/voices` chỉ trả về giọng thuộc các ngôn ngữ đã chọn và `POST /v1/audio/speech` cũng từ chối giọng ngoài các ngôn ngữ đó.
- **Phân loại:** Feature mở rộng
- **Đặc tả thay đổi:**
  - `spec.md`: cập nhật `FR-111`, `FR-112`; thêm `BR-110`, `AC-111`, `AC-112`.
  - `logic.md`: cập nhật Mục 4 (lọc giao AND theo `settings.voice_languages`, mở rộng query `?language=` hỗ trợ cả tên nhóm ngôn ngữ và mã `eng`/`fra`, và kiểm tra chặn trên `POST /v1/audio/speech`).
- **Quyết định:** Áp dụng nghiêm ngặt cho cả `GET /v1/audio/voices` (lọc giao AND với query params) và `POST /v1/audio/speech` (trả `400 Bad Request`, **không fallback** kể cả khi client bỏ trống `voice` mà giọng mặc định `Aria` nằm ngoài ngôn ngữ đang bật). Loại bỏ phương án tự động fallback sang giọng đầu tiên trong danh sách đang bật để tránh sinh sai giọng ngoài ý muốn của client.
- **Task:** [T-013](../../04_tasks/013_voice_languages_filter/plan.md)

## 2026-11-19 — Bổ sung endpoints `/v1/audio/voices` và `/v1/audio/speech` (TTS)

- **Yêu cầu:** Thêm 2 endpoint `GET /v1/audio/voices` (danh sách giọng Muse TTS kèm bộ lọc) và `POST /v1/audio/speech` (sinh giọng nói `.mp3` qua Muse WSS, hỗ trợ inline emotion cues và `instructions`), đồng thời bổ sung tài liệu endpoint trên Console.
- **Phân loại:** Feature mở rộng
- **Đặc tả thay đổi:**
  - `spec.md`: chuyển TTS vào In Scope; cập nhật `FR-107`, `FR-110`, `BR-101`; bổ sung `FR-111`, `FR-112`, `BR-106`..`BR-109`, `AC-107`..`AC-110`.
  - `logic.md`: bổ sung luồng phân giải giọng, template prompt TTS (bỏ qua Global System Prompt) và trích xuất resource `audio`/`.mp3` từ `/chat/history`.
  - `../../02_basic_design/01_api_overview.md`: thêm `GET /v1/audio/voices`, `POST /v1/audio/speech` và cập nhật `/v1/media/{filename}`.
- **Quyết định:** Lưu tĩnh danh mục giọng vào `packages/backend/data/voices.json` (ẩn `avocado_v2:p1a1_short`); mặc định `POST /v1/audio/speech` trả binary `audio/mpeg` (chuẩn OpenAI) kèm tùy chọn `response_format="url"|"json"`; trả `400` nếu `voice` không tồn tại hoặc định dạng audio khác `mp3`/`url`/`json`.
- **Task:** [T-012](../../04_tasks/012_audio_voices_and_speech/plan.md)

## 2026-11-17 — Collapsible Input/Output Endpoints & UI Stability

- **Yêu cầu:** Bổ sung hướng dẫn Input/Output dạng collapse cho từng endpoint `/v1/*` và cố định kích thước nút Show/Copy.
- **Phân loại:** Feature mở rộng
- **Đặc tả thay đổi:**
  - `spec.md`: bổ sung `FR-110`.
- **Quyết định:** Dùng accordion đóng/mở theo từng endpoint và cố định chiều rộng nút `Show/Hide`, `Copy/Copied`.
- **Task:** đã triển khai trực tiếp

## 2026-11-17 — Bổ sung parity đầy đủ với `muse2api` v1 (loại trừ `/v1/audio/speech`)

- **Yêu cầu:** Bổ sung đầy đủ các tính năng `/v1/*` còn thiếu so với `../muse2api` (streaming `/v1/responses`, reference media kèm chống SSRF, `async` flag, `Idempotency-Key`, metadata task, đầy đủ model alias, hỗ trợ `image_url` trong chat và `MUSE2API_TOOL_PROTOCOL`), bỏ qua endpoint `/v1/audio/speech`.
- **Phân loại:** Feature mở rộng
- **Đặc tả thay đổi:**
  - `spec.md`: cập nhật Phạm vi (loại bỏ `/v1/audio/speech`), bổ sung `FR-106`..`FR-109`, `BR-104`..`BR-105`, `AC-104`..`AC-106`.
  - `logic.md`: bổ sung luồng SSRF Guard cho reference URLs và SSE events cho `/v1/responses`.
  - `01_api_overview.md`: đồng bộ danh sách endpoints `/v1/*` (bỏ `/v1/audio/speech`).
- **Quyết định:** Giữ cơ chế chống SSRF mặc định tắt fetch mạng nội bộ/file cục bộ như v1; không triển khai `/v1/audio/speech` theo xác nhận của người dùng.
- **Task:** [T-006](../../04_tasks/006_v1_api_parity/plan.md)
