# Task 003: OpenAI `/v1/*` API & Client API Key

## 1. Mục tiêu triển khai

Xây dựng toàn bộ đầu API `/v1/*` tương thích OpenAI qua WSS Noise tunnel và API quản lý 1 Client API Key duy nhất lưu raw trong SQLite theo [OpenAI API Spec](../../03_features/02_openai_api_and_keys/spec.md).

## 2. Danh sách tệp tin cần tạo

- `backend/auth.py`
- `backend/routers/apikey.py`
- `backend/routers/v1_chat.py`
- `backend/routers/v1_media.py`
- `backend/routers/v1_audio.py`

## 3. Checklist triển khai

- [ ] `auth.py` & `routers/apikey.py`: xác thực `Bearer <raw_key>` cho `/v1/*` (`AC-101`), `GET /admin/apikey` trả raw key, `POST /admin/apikey/rotate` xoay key ngay (`AC-102`).
- [ ] `v1_chat.py`: `/v1/models`, `/v1/chat/completions` (SSE `stream=true` & non-stream), `/v1/responses`, tự động chèn Global System Prompt khi bật.
- [ ] `v1_media.py`: `/v1/images/generations`, `/v1/images/edits`, `/v1/images/tasks` (+ `/{task_id}`), `/v1/videos` & `/v1/videos/generations` (+ `/{task_id}`), tải binary qua `GET /media/raw/<path>` và phục vụ tại `/v1/media/{filename}` (`AC-103`).
- [ ] `v1_audio.py`: `/v1/audio/speech` (gọi `POST /api/voice/speak` qua WSS + transcode `ffmpeg` nếu cần).

## 4. Kế hoạch kiểm thử

- **Unit test:** Bearer auth check, SSE chunk formatting, system prompt injection.
- **Integration test:** Gọi thử OpenAI Python SDK / `curl` tới `/v1/chat/completions`, `/v1/images/generations`, `/v1/videos`, `/v1/audio/speech`.
