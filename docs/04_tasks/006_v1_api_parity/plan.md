# Task 006: OpenAI `/v1/*` Full Parity (Excluding TTS)

- **Nguồn thay đổi:** [request-changes.md](../../03_features/02_openai_api_and_keys/request-changes.md)

## 1. Mục tiêu triển khai
Bổ sung đầy đủ các tính năng `/v1/*` còn thiếu so với `../muse2api` theo [spec.md](../../03_features/02_openai_api_and_keys/spec.md) và [logic.md](../../03_features/02_openai_api_and_keys/logic.md) (loại trừ `/v1/audio/speech`).

## 2. Danh sách tệp tin cần tạo / chỉnh sửa
- `backend/config.py`
- `backend/services/ref_media.py` (tạo mới: SSRF Guard & tải media tham chiếu)
- `backend/services/wss_pool.py`
- `backend/routers/v1_openai.py`
- `frontend/src/pages/ApiKeysPage.tsx` (đồng bộ danh sách endpoint)

## 3. Checklist triển khai
- [ ] `config.py`: thêm `ref_image_local_files`, `ref_image_private_fetch`, `tool_protocol`.
- [ ] `ref_media.py`: kiểm tra SSRF (`BR-104`), giới hạn 10 items / 40 MiB / 100 MiB (`AC-105`).
- [ ] `v1_openai.py`:
  - [ ] `GET /v1/models`: đầy đủ danh sách alias (`FR-107`).
  - [ ] `POST /v1/responses`: hỗ trợ `stream=true` SSE (`response.created`, `response.output_text.delta`, `response.completed`) và `instructions` (`FR-106`, `AC-104`).
  - [ ] `POST /v1/chat/completions`: multimodal `image_url`, top-level `prompt`, `MUSE2API_TOOL_PROTOCOL` (`FR-103`, `BR-105`).
  - [ ] `POST /v1/images/*` & `/v1/videos*`: reference media URL/base64/multipart, `async=true`, `Idempotency-Key`, `aspect_ratio`, `resolution`, `extra`, `timeout`, full metadata (`FR-108`, `FR-109`, `AC-103`, `AC-106`).
  - [ ] Bỏ endpoint `/v1/audio/speech` khỏi scope.
- [ ] Cập nhật `ApiKeysPage.tsx` và rebuild `frontend/dist/`.

## 4. Kế hoạch kiểm thử
- **Unit & Security Test:** SSRF guard (chặn `127.0.0.1`, `169.254.169.254`), `Idempotency-Key`, `async=true`, `/v1/responses` SSE format, `GET /v1/models`.
- **Integration Test:** Chạy test với tài khoản thật cho `/v1/responses` (`stream=true`), `/v1/images/generations` (`async=true` + poll), `/v1/videos` (kèm ảnh tham chiếu).
