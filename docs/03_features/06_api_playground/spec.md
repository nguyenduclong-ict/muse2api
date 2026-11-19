# Feature Spec: API Playground & Voice Preview Cache

- **Trạng thái:** `Implemented (Production)`
- **Liên quan:** [API Overview](../../02_basic_design/01_api_overview.md), [Screens Overview](../../02_basic_design/03_screens_overview.md), [OpenAI API & Keys](../02_openai_api_and_keys/spec.md), [Settings & Cleanup](../04_settings_and_cleanup/spec.md)

## 1. Mục tiêu & Bối cảnh
Cung cấp một giao diện **Playground** (`/playground`) trực quan ngay trong Admin Console cho phép nhà phát triển và quản trị viên kiểm thử trực tiếp toàn bộ các endpoint `/v1/*` (Chat, Responses, Images, Video, Audio & Voices) bằng API Key hiện hành, kèm xem/sao chép mã lệnh `cURL` và phản hồi JSON thô.

Đồng thời, vì danh mục giọng đọc tĩnh (`packages/backend/data/voices.json`) không có sẵn URL âm thanh mẫu từ Muse, hệ thống bổ sung một API chuyên biệt cho phép nghe thử giọng đọc (Voice Preview) có cơ chế cache đĩa bền vững để phát tức thì từ lần thứ hai trở đi mà không tiêu tốn lại quota Muse.

## 2. Phạm vi
- **In Scope:**
  - Màn hình riêng `SCR-07: Playground` (`/playground`) trên Sidebar (ngôn ngữ giao diện Tiếng Anh đồng bộ toàn bộ Console).
  - 4 tab kiểm thử API trực quan: **Chat** (`chat/completions` & `responses`), **Images** (`images/generations` & `images/edits`), **Video** (`videos` + tự động poll `videos/{id}`), **Audio & Voices** (`audio/voices` + nghe thử có cache + `audio/speech`).
  - Khung xem nhanh và sao chép `cURL` + `Raw Response` trên từng tab.
  - API công khai `GET /v1/audio/voices/{voice_id}/preview` (có xác thực Bearer API Key, hỗ trợ trả binary `audio/mpeg` hoặc JSON `url`, hỗ trợ `refresh=true`).
  - Bổ sung trường `cached` và `preview_url` trong phản hồi `GET /v1/audio/voices`.
  - API quản trị cache preview (`GET /admin/voices/preview/stats`, `DELETE /admin/voices/preview`, `DELETE /admin/voices/preview/{voice_id}`).
  - Cơ chế cache đĩa riêng tại `data/voice_previews/`, câu mẫu cố định theo nhóm ngôn ngữ, in-flight lock chống sinh trùng.
- **Out of Scope:**
  - Lưu trữ lịch sử hội thoại Chat của Playground vào SQLite (chỉ giữ trong bộ nhớ React trong phiên làm việc, reset khi reload).
  - Tùy chỉnh câu mẫu nghe thử cho từng giọng qua API preview (mỗi giọng gắn cố định 1 câu mẫu chuẩn theo ngôn ngữ để tối ưu cache; người dùng muốn đọc văn bản tùy ý sẽ dùng `POST /v1/audio/speech`).
  - Tự động tải trước (pre-warm) toàn bộ 1.218 giọng khi khởi động server.

## 3. Yêu cầu chức năng (`FR`)

### 3.1. API Nghe thử Giọng đọc có Cache (Voice Preview API)
- **FR-501 (API Sample Voice `/v1/audio/voices/{voice_id}/preview`):**
  - Endpoint `GET /v1/audio/voices/{voice_id}/preview` yêu cầu header `Authorization: Bearer <api_key>`.
  - Tham số đường dẫn `voice_id` hỗ trợ ID đầy đủ (ví dụ `avocado_v2:MAI_01`), tên giọng không phân biệt hoa/thường (`Aria`), hoặc OpenAI alias (`alloy`, `echo`, ...).
  - Tham số truy vấn tùy chọn:
    - `response_format`: `"mp3"` (mặc định — trả trực tiếp binary `audio/mpeg` kèm header `X-Voice-Preview-Cache: HIT|MISS`) hoặc `"url"` / `"json"` (trả JSON gồm `voice_id`, `voice_name`, `language_group`, `sample_text`, `cached`, `url`, `bytes`).
    - `refresh`: `false` (mặc định) hoặc `true` (bỏ qua file cache cũ, gọi Muse sinh mẫu mới và ghi đè file cache).
  - Nếu `voice_id` không tồn tại hoặc không thuộc danh sách `voice_languages` đang bật trong Settings, trả `400 invalid_request_error` tương tự `POST /v1/audio/speech`.
- **FR-502 (Bổ sung metadata cache vào `GET /v1/audio/voices`):**
  - Mỗi phần tử trong `data` của `GET /v1/audio/voices` bổ sung thêm:
    - `language_group`: tên nhóm ngôn ngữ chuẩn hóa (ví dụ `"English (US)"`, `"Vietnamese"`).
    - `cached`: `true` nếu đã có file MP3 hợp lệ trong `data/voice_previews/`, ngược lại `false`.
    - `preview_url`: đường dẫn đầy đủ tới `GET /v1/audio/voices/{id}/preview`.
- **FR-503 (Phục vụ & Quản trị Cache Preview):**
  - `GET /v1/voice-previews/{filename}`: phục vụ trực tiếp file `.mp3` đã cache (dùng cho trường `url` khi `response_format=url|json`, tương tự `GET /v1/media/{filename}`).
  - `GET /admin/voices/preview/stats`: trả số lượng file cache hiện có và tổng dung lượng (`count`, `total_bytes`).
  - `DELETE /admin/voices/preview`: xóa toàn bộ file `.mp3` trong `data/voice_previews/`.
  - `DELETE /admin/voices/preview/{voice_id}`: xóa file cache của riêng một giọng.

### 3.2. Giao diện API Playground (`SCR-07`)
- **FR-504 (Điều hướng & Tự động xác thực):**
  - Thêm mục **Playground** (`/playground`) vào Sidebar ngay dưới **API & Keys**.
  - Khi mở trang, Playground tự động lấy API Key hiện hành qua `GET /admin/apikey` và gắn `Authorization: Bearer <raw_key>` cho mọi yêu cầu gọi `/v1/*`.
- **FR-505 (Tab Chat):**
  - Cho phép chọn mode `Chat Completions (/v1/chat/completions)` hoặc `Responses (/v1/responses)`.
  - Chọn model từ danh sách `GET /v1/models`, bật/tắt `Stream (SSE)`, nhập optional `System / Instructions`, đính kèm ảnh tham chiếu (upload file chuyển sang data URL hoặc dán URL), gửi hội thoại nhiều lượt và nút `Clear Chat`.
  - Khi `stream=true`, hiển thị văn bản sinh ra theo thời gian thực (streaming chunks) và hỗ trợ nút `Stop` để hủy request (`AbortController`).
- **FR-506 (Tab Images):**
  - Chuyển đổi giữa `Generations (/v1/images/generations)` và `Edits (/v1/images/edits)`.
  - Nhập `prompt`, chọn `size` / `aspect_ratio` (`1:1`, `16:9`, `9:16`, `4:3`, `3:4`), chọn `response_format` (`url` / `b64_json`), bật/tắt `async` (nếu `async=true`, tự động poll `GET /v1/images/tasks/{id}` đến khi hoàn tất).
  - Hỗ trợ tải ảnh tham chiếu từ máy hoặc dán URL (bắt buộc ở mode `Edits`, tùy chọn ở mode `Generations`).
  - Hiển thị ảnh kết quả trực tiếp kèm kích thước, thời gian phản hồi và nút tải xuống.
- **FR-507 (Tab Video):**
  - Form gửi `POST /v1/videos` gồm `prompt`, `duration` (5s / 8s / 10s), `size` (`16:9`, `9:16`, `1:1`), và tùy chọn ảnh khung hình đầu (`image` / `image_url`).
  - Sau khi nhận `task_id`, tự động poll `GET /v1/videos/{task_id}` mỗi 2 giây, hiển thị thanh tiến trình (`progress %`) và trạng thái; khi `completed`, hiển thị trình phát `<video controls>` và nút tải `.mp4`.
- **FR-508 (Tab Audio & Voices):**
  - **Khu vực Voice Catalog:** Tải danh sách giọng từ `GET /v1/audio/voices` (tự động tuân thủ `voice_languages` trong Settings), hỗ trợ lọc theo `Language`, `Gender`, tìm kiếm `q` và phân trang.
  - Mỗi dòng giọng hiển thị tên, ID, nhóm ngôn ngữ/accent/giới tính/tone, nút duy nhất **Preview** (gọi `GET /v1/audio/voices/{id}/preview`, server phát sample cố định và tự động lưu cache đĩa cho các lần sau mà không cần người dùng can thiệp), và nút **Use** để đưa giọng đó vào form Speech.
  - Toàn bộ cơ chế lưu cache đĩa diễn ra ngầm định ở server (trong suốt với người dùng, UI không hiển thị cột Cache hay nút Refresh thừa thãi).
  - **Khu vực Speech Tester (`POST /v1/audio/speech`):** Chọn giọng (từ Explorer hoặc nhập tay), chọn model (`muse-tts`, `tts-1`, `tts-1-hd`, `gpt-4o-mini-tts`), nhập văn bản cần đọc kèm các nút chèn nhanh emotion cues (`[laughs]`, `[sighs]`, `[whispers]`, `[excited]`), nhập optional `instructions`, chỉnh `speed` (`0.25` – `4.0`), chọn `response_format` (`mp3` / `url`), bấm **Generate Speech** và phát trực tiếp trên trình phát `<audio controls>` kèm nút tải `.mp3`.
- **FR-509 (cURL & Raw Response Inspector):**
  - Mỗi tab có ngăn thu gọn/mở rộng hiển thị lệnh `cURL` tương ứng với cấu hình hiện tại (có nút Copy, hỗ trợ ẩn/hiện API Key) và phần `Raw Response` (status code, latency `ms`, response headers/JSON).

## 4. Quy tắc nghiệp vụ (`BR`)
- **BR-501 (Tách biệt thư mục Cache Preview):** File nghe thử giọng đọc được lưu tại `data/voice_previews/` với tên tệp chuẩn hóa an toàn từ `voice_id` (thay thế mọi ký tự không phải `[a-zA-Z0-9_-]` thành `__`, ví dụ `avocado_v2:MAI_01` → `avocado_v2__MAI_01.mp3`). Thư mục này hoàn toàn độc lập với `data/media/` và **không** bị `CleanupService` tự động xóa.
- **BR-502 (Câu mẫu cố định theo nhóm ngôn ngữ):** Mỗi nhóm ngôn ngữ trong `CANONICAL_LANGUAGE_GROUPS` có một câu mẫu ngắn (2–4 giây) cố định trong backend (ví dụ: `Vietnamese`, `Japanese`, `Korean`, `French`, `Spanish`, `German`, `Chinese`, `Russian`, `Italian`, `Thai`, `Indonesian`, `Portuguese`, `Arabic`, `Indian`, `Finnish`, `Filipino`, `Malaysian`, và mặc định `English` cho toàn bộ 13 nhóm `English (*)` và `Other`).
- **BR-503 (Chống gọi trùng In-Flight):** Khi nhiều yêu cầu cùng gọi `GET /v1/audio/voices/{voice_id}/preview` cho cùng một `voice_id` chưa có cache tại cùng thời điểm, chỉ một luồng duy nhất gọi Muse TTS; các yêu cầu còn lại chờ khóa theo `voice_id` và nhận lại file cache vừa sinh.
- **BR-504 (Ghi file nguyên tử):** File cache mới phải được ghi ra tệp tạm (`*.tmp`) trong `data/voice_previews/` rồi `os.replace()` sang tệp đích `.mp3` để tránh đọc phải file dở dang khi có yêu cầu đồng thời.
- **BR-505 (Ghi log `tasks` khi Cache Miss):** Khi `GET /v1/audio/voices/{voice_id}/preview` bị cache miss (hoặc `refresh=true`) và phải gọi Muse TTS, hệ thống ghi một bản ghi vào bảng `tasks` với `kind="audio"`, `model="muse-tts"`, `prompt_preview="[Voice Preview] <voice_name>: <sample_text>"`. Khi cache hit, không tạo bản ghi `tasks` mới.
- **BR-506 (Bảo toàn trạng thái trong phiên):** Chuyển đổi giữa 4 tab trong Playground không làm mất dữ liệu đang nhập hoặc kết quả vừa sinh trong cùng phiên làm việc; toàn bộ state được reset khi tải lại trang.

## 5. Tiêu chí nghiệm thu (`AC`)
- **AC-501:** Gọi `GET /v1/audio/voices/avocado_v2:MAI_01/preview` lần đầu với API Key hợp lệ trả `200`, `Content-Type: audio/mpeg`, header `X-Voice-Preview-Cache: MISS`, tạo file `data/voice_previews/avocado_v2__MAI_01.mp3` và ghi 1 bản ghi vào bảng `tasks`.
- **AC-502:** Gọi lại `GET /v1/audio/voices/avocado_v2:MAI_01/preview` lần thứ hai trả `200`, header `X-Voice-Preview-Cache: HIT`, không gọi Muse WSS và không tạo thêm bản ghi trong bảng `tasks`.
- **AC-503:** Gọi `GET /v1/audio/voices/avocado_v2:MAI_01/preview?response_format=url` trả JSON chứa `cached: true`, `url` trỏ tới `/v1/voice-previews/avocado_v2__MAI_01.mp3` và tải được file `.mp3` từ URL đó.
- **AC-504:** Gọi `GET /v1/audio/voices/avocado_v2:MAI_01/preview?refresh=true` gọi Muse sinh lại mẫu mới, ghi đè file cache và trả `X-Voice-Preview-Cache: MISS`.
- **AC-505:** Chạy `CleanupService.run_now()` (dù `retention_days=0` hoặc vượt `max_gb`) không xóa bất kỳ file nào trong `data/voice_previews/`.
- **AC-506:** Gọi `GET /v1/audio/voices` trả về `cached: true` cho các giọng đã có file trong `data/voice_previews/` và `cached: false` cho các giọng chưa có, kèm `preview_url` hợp lệ.
- **AC-507:** Trên giao diện `/playground`, kiểm thử thành công cả 4 tab:
  - Chat nhận text streaming theo thời gian thực khi `Stream` bật.
  - Images hiển thị ảnh kết quả ở cả chế độ `Generations` và `Edits`.
  - Video hiển thị tiến trình poll và phát được video `.mp4` khi hoàn tất.
  - Audio & Voices lọc được giọng, bấm Play Preview phát âm thanh và cập nhật badge `Cached`, bấm Generate Speech phát được audio từ văn bản nhập vào.
- **AC-508:** Bấm **Clear Preview Cache** trên Playground xóa toàn bộ file trong `data/voice_previews/`, cập nhật bộ đếm về `0 cached voices` và tắt toàn bộ badge `Cached`.
