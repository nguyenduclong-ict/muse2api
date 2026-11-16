# API Overview — Tổng hợp hệ thống API

## 1. Quy chuẩn xác thực
- **`/v1/*`:** Bắt buộc header `Authorization: Bearer <api_key>` khớp với `api_key` đang lưu trong bảng `api_keys` (trả `401` nếu thiếu hoặc sai).
- **`/admin/*`:** Không yêu cầu xác thực.
- **`/healthz`, `/readyz`:** Mở công khai cho healthcheck.

## 2. Danh sách Endpoints `/v1/*` (OpenAI-Compatible)
| Method | Path | Chức năng |
|---|---|---|
| `GET` | `/v1/models` | Liệt kê các model alias được hỗ trợ |
| `POST` | `/v1/chat/completions` | Chat completions (SSE `stream=true` & non-stream) |
| `POST` | `/v1/responses` | OpenAI Responses API |
| `POST` | `/v1/images/generations` | Sinh ảnh (sync hoặc `async=true`) |
| `POST` | `/v1/images/edits` | Chỉnh sửa ảnh với ảnh tham chiếu |
| `POST` | `/v1/images/tasks` | Tạo task sinh ảnh bất đồng bộ |
| `GET` | `/v1/images/tasks/{task_id}` | Tra cứu tiến trình & kết quả task ảnh |
| `POST` | `/v1/videos` | Tạo task sinh video (text-to-video & image-to-video) |
| `POST` | `/v1/videos/generations` | Alias tạo task sinh video |
| `GET` | `/v1/videos/{task_id}` | Tra cứu tiến trình (`progress`) & kết quả video |
| `GET` | `/v1/media/{filename}` | Phục vụ file ảnh/video đã tải về `data/media/` |

## 3. Danh sách Endpoints `/admin/*` (Console)
| Nhóm | Endpoints chính |
|---|---|
| **Dashboard** | `GET /admin/dashboard` (health, pool summary, 7-day trend, recent tasks) |
| **Accounts** | `GET /admin/accounts`, `POST /admin/accounts`, `PATCH /admin/accounts/{id}`, `DELETE /admin/accounts/{id}`, `POST /admin/accounts/{id}/refresh`, `POST /admin/accounts/refresh`, `POST /admin/accounts/{id}/test`, `POST /admin/accounts/{id}/quota`, `POST /admin/accounts/quota`, `GET /admin/accounts/export`, `POST /admin/accounts/{id}/keepalive`, `POST /admin/accounts/keepalive`, `GET /admin/extension/download` |
| **Proxies** | `GET /admin/proxies`, `POST /admin/proxies/import`, `POST /admin/proxies/{id}/check`, `POST /admin/proxies/check-all`, `DELETE /admin/proxies/{id}` |
| **API Key** | `GET /admin/apikey`, `POST /admin/apikey/rotate` |
| **Tasks & Media** | `GET /admin/tasks`, `DELETE /admin/tasks/{id}`, `POST /admin/tasks/clear`, `GET /admin/media`, `POST /admin/media/delete`, `DELETE /admin/media/{name}` |
| **Settings** | `GET /admin/settings`, `POST /admin/settings`, `POST /admin/cleanup/run` |
