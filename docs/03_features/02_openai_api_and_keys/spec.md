# Feature Spec: OpenAI-Compatible API (`/v1/*`) & API Key

- **Trạng thái:** `Ready for Implementation`
- **Liên quan:** [API Overview](../../02_basic_design/01_api_overview.md), [System Architecture](../../02_basic_design/00_system_architecture.md)

## 1. Mục tiêu & Bối cảnh
Cung cấp đầu API chuẩn OpenAI (`/v1/*`) đầy đủ tính năng tương đương `../muse2api` cho các ứng dụng bên thứ 3 gọi trực tiếp qua WSS Noise tunnel, đồng thời cho phép xem/copy/xoay 1 API Key duy nhất lưu dạng raw trong SQLite.

## 2. Phạm vi
- **In Scope:**
  - Endpoints: `/v1/models` (đầy đủ alias), `/v1/chat/completions` (SSE + non-stream, multimodal `image_url`, top-level `prompt`, `MUSE2API_TOOL_PROTOCOL`), `/v1/responses` (SSE + non-stream, `instructions`), `/v1/images/generations`, `/v1/images/edits` (multipart & JSON), `/v1/images/tasks` (+ `/{id}` & `Idempotency-Key`), `/v1/videos` & `/v1/videos/generations` (+ `/{id}`), `/v1/media/{name}`.
  - Quản lý 1 Client API Key (`m2a_...`) lưu raw trong bảng `api_keys`.
- **Out of Scope:**
  - Endpoint `/v1/audio/speech` (TTS).
  - Quản lý nhiều API Key phân quyền theo từng user/app.

## 3. Yêu cầu chức năng (`FR`)
- **FR-101 (Xác thực `/v1/*`):** Mọi request tới `/v1/*` (trừ `/v1/media/{name}`) phải kiểm tra `Authorization: Bearer <key>` khớp `api_keys.raw_key`.
- **FR-102 (Quản lý 1 API Key Raw):** Khởi tạo tự động 1 key `m2a_<random>` nếu bảng `api_keys` trống (hoặc lấy từ `MUSE2API_KEY` trong `.env`). API `GET /admin/apikey` trả về `raw_key` nguyên văn để Admin xem/copy; `POST /admin/apikey/rotate` tạo key mới thay thế ngay lập tức.
- **FR-103 (Chat Completions qua WSS):** Gửi `POST /chat/stream` và subscribe `POST /chat/subscribe` để nhận delta text theo thời gian thực, chuyển đổi thành SSE `chat.completion.chunk` (hoặc JSON sync). Hỗ trợ `messages` kèm `image_url`, top-level `prompt` khi `messages` rỗng, và tùy chọn `MUSE2API_TOOL_PROTOCOL` (`0` mặc định) cho `tools`/`tool_calls`.
- **FR-104 (Image & Video Generation qua WSS):** Gửi prompt sinh ảnh/video qua `POST /chat/stream`, theo dõi `POST /chat/subscribe` đến khi `task.status == "completed"`, đọc `GET /chat/history` lấy path resource, tải binary qua `GET /media/raw/<path>` về `data/media/` và trả URL `/v1/media/<filename>` hoặc `b64_json`.
- **FR-105 (LRU Pool & Failover):** Chọn tài khoản `healthy` có `last_used_at` cũ nhất; nếu tài khoản lỗi `401` hoặc timeout khi bắt đầu stream, tự động retry sang tài khoản khác trong pool.
- **FR-106 (`/v1/responses` Streaming & `instructions`):** Hỗ trợ `stream=true` trả SSE events (`response.created`, `response.output_text.delta`, `response.completed`) và đọc trường `instructions` để ghép vào prompt gửi qua WSS.
- **FR-107 (`GET /v1/models` Alias đầy đủ):** Trả đầy đủ danh sách model alias tương đương v1 (`muse-spark`, `gpt-4o`, `gpt-4o-mini`, `gpt-5`, `claude-sonnet-4`, `claude-opus-4`, `deepseek-chat`, `gemini-2.5-pro`, `muse-image`, `muse-video`, v.v.).
- **FR-108 (Reference Media & SSRF Guard):** Hỗ trợ đầu vào media tham chiếu (`image`, `images`, `image_url`, `reference_image`, `videos`, `audios`, `files` từ URL công khai hoặc base64/data URL; multipart `image`, `image[]`, `video`, `audio`, `file`) trên `/v1/images/generations`, `/v1/images/edits`, `/v1/images/tasks`, `/v1/videos*` và `image_url` trong `/v1/chat/completions`.
- **FR-109 (Async Flag, Idempotency & Task Metadata):** Hỗ trợ `async=true` trên `/v1/images/generations` và `/v1/images/edits`, header `Idempotency-Key` trên `/v1/images/tasks`, các tham số `aspect_ratio`, `resolution`, `extra`, `timeout`, và trả đầy đủ metadata (`progress`, `size`, `kind`, `bytes`, `b64_json`) ở `GET /v1/images/tasks/{id}` và `GET /v1/videos/{id}`.
- **FR-110 (Collapsible Endpoint Docs & Stable Controls):** Danh sách Available `/v1/*` Endpoints trên UI hỗ trợ đóng/mở (collapse) xem schema Input & Output; các nút `Show/Hide` và `Copy/Copied` giữ cố định chiều rộng để không làm lệch layout.

## 4. Quy tắc nghiệp vụ (`BR`)
- **BR-101:** Khi Global System Prompt đang bật trong `settings`, backend tự động chèn `<system>...</system>` vào đầu nội dung prompt gửi lên `muse.ai`.
- **BR-102:** `POST /chat/subscribe` chỉ được gọi **sau khi** `POST /chat/stream` trả `200 OK` và xác nhận `session_id` tồn tại trên VM.
- **BR-103:** Khi xoay API key (`rotate`), key cũ mất hiệu lực ngay lập tức đối với các request mới tới `/v1/*`.
- **BR-104 (SSRF & Media Limits):** Mặc định từ chối URL mạng nội bộ (`MUSE2API_REF_IMAGE_PRIVATE_FETCH=0`) và đường dẫn file cục bộ (`MUSE2API_REF_IMAGE_LOCAL_FILES=0`). Giới hạn tối đa **10** media tham chiếu mỗi request, **40 MiB** mỗi item và **100 MiB** tổng dung lượng.
- **BR-105:** `MUSE2API_TOOL_PROTOCOL` mặc định tắt (`0`); khi tắt, không tiêm hướng dẫn JSON tool calling vào prompt.

## 5. Tiêu chí nghiệm thu (`AC`)
- **AC-101:** Request `/v1/chat/completions` thiếu hoặc sai `Authorization` trả về `401 Unauthorized` chuẩn OpenAI.
- **AC-102:** `GET /admin/apikey` trả về đúng `raw_key` trong SQLite; sau khi bấm Rotate, key cũ bị từ chối và key mới hoạt động ngay.
- **AC-103:** Gọi `POST /v1/videos` (kèm hoặc không kèm ảnh tham chiếu) và `GET /v1/videos/{task_id}` trả về `progress` và URL `.mp4` hợp lệ phục vụ tại `/v1/media/{filename}`.
- **AC-104:** Gọi `POST /v1/responses` với `stream=true` và `instructions` trả về đúng chuỗi SSE `response.created` → `response.output_text.delta` → `response.completed`.
- **AC-105:** Truyền URL nội bộ (`http://127.0.0.1/...` hoặc `http://169.254.169.254/...`) làm ảnh tham chiếu bị chặn với `400 Bad Request` khi `MUSE2API_REF_IMAGE_PRIVATE_FETCH=0`.
- **AC-106:** Gọi `POST /v1/images/generations` với `"async": true` trả ngay `{id, status: "queued"}` và tra cứu được kết quả qua `GET /v1/images/tasks/{id}`.
