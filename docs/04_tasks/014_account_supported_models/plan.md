# Task 014: Account Supported Models (`chat`, `image`, `video`, `speech`) & Capability Routing

- **Nguồn thay đổi:** [01_accounts_and_keepalive/request-changes.md](../../03_features/01_accounts_and_keepalive/request-changes.md), [02_openai_api_and_keys/request-changes.md](../../03_features/02_openai_api_and_keys/request-changes.md)
- **Liên kết Spec:** [01_accounts_and_keepalive/spec.md](../../03_features/01_accounts_and_keepalive/spec.md), [01_accounts_and_keepalive/design.md](../../03_features/01_accounts_and_keepalive/design.md), [01_accounts_and_keepalive/logic.md](../../03_features/01_accounts_and_keepalive/logic.md), [02_openai_api_and_keys/spec.md](../../03_features/02_openai_api_and_keys/spec.md), [02_openai_api_and_keys/logic.md](../../03_features/02_openai_api_and_keys/logic.md)
- **Mục tiêu:** Cho phép cấu hình danh sách loại model hỗ trợ (`chat`, `image`, `video`, `speech`) cho từng tài khoản trong SQLite & Admin Console; điều phối pool `/v1/*` lọc chính xác theo `supported_models` của tài khoản và fail-fast HTTP `503 Service Unavailable` khi không có tài khoản hợp lệ.

## Danh sách tệp cần tạo / chỉnh sửa

- **Backend:**
  - `packages/backend/db.py`:
    - Khai báo hằng số `SUPPORTED_MODEL_TYPES = ("chat", "image", "video", "speech")` cùng các helper `normalize_supported_models(models)` (validate bắt buộc >= 1 giá trị hợp lệ, khử trùng lặp, giữ thứ tự chuẩn) và `parse_supported_models(raw_json)` (fallback mặc định đủ 4 loại khi rỗng/lỗi).
    - Thêm cột `supported_models_json TEXT NOT NULL DEFAULT '["chat","image","video","speech"]'` vào bảng `accounts` và migration `ALTER TABLE accounts ADD COLUMN supported_models_json ...` trong `init_schema()`.
    - Cập nhật `create_account(...)` nhận `supported_models` và bổ sung `"supported_models_json"` vào `allowed` trong `update_account(...)`.
  - `packages/backend/routers/accounts.py`:
    - Bổ sung `supported_models: list[str] | None = None` vào `AccountCreateReq` và `AccountPatchReq`.
    - Validate qua `normalize_supported_models(...)` (trả `400 Bad Request` nếu rỗng hoặc chứa giá trị không thuộc 4 loại hợp lệ).
    - Trên `PATCH /admin/accounts/{id}`: chỉ lưu `supported_models_json`, không đóng WSS tunnel khi chỉ đổi `supported_models`.
    - Cập nhật `_serialize_account` và `GET /admin/accounts/export` trả kèm trường `"supported_models"`.
  - `packages/backend/services/wss_pool.py`:
    - Định nghĩa ngoại lệ `NoCandidateAccountError(MuseWSSError)`.
    - Cập nhật `_candidate_accounts(capability: str | None = None)` lọc theo `capability in parse_supported_models(a.get("supported_models_json"))`.
    - Cập nhật `_no_candidate_error(capability: str | None = None)` phân biệt rõ: không có tài khoản enabled nào bật `capability`, tất cả tài khoản hỗ trợ `capability` đã hết quota, hoặc không có tài khoản khỏe mạnh khả dụng.
    - Bổ sung `ensure_candidate(capability: str)` (raise `NoCandidateAccountError` nếu không có ứng viên).
    - Truyền đúng `capability` trong `execute_chat` (`"chat"`), `stream_chat_events` (`"chat"`), `generate_media` (`"image"` / `"video"` / `"speech"` tương ứng `expect_kind` `"image"` / `"video"` / `"audio"`).
  - `packages/backend/routers/v1_openai.py`:
    - Gọi `pool.ensure_candidate(capability)` sớm trước khi tạo `StreamingResponse` (ở `/v1/chat/completions`, `/v1/responses`), trước khi tạo task `queued` + background thread (ở `/v1/videos`, `/v1/videos/generations`, `/v1/images/tasks`, `async=true` trên `/v1/images/generations` & `/v1/images/edits`), và bắt `NoCandidateAccountError` ở các nhánh sync (`/v1/chat/completions`, `/v1/responses`, `/v1/images/*`, `/v1/audio/speech`) để trả HTTP `503 Service Unavailable` chuẩn OpenAI (`type: "service_unavailable_error"`) mà không tạo task rác.
  - `packages/backend/tests/test_account_supported_models.py` *(tạo mới)*:
    - Unit & integration tests cho migration DB, CRUD/Export `/admin/accounts`, lọc `_candidate_accounts(capability)`, định tuyến các endpoint `/v1/*` và fail-fast `503`.
- **Frontend:**
  - `packages/frontend/src/pages/AccountsPage.tsx`:
    - Bổ sung `supported_models: string[]` vào `AccountItem`.
    - Hiển thị cột `Models` (badge chỉ xem gọn cho các loại model đang bật) trên bảng Accounts.
    - Thêm bộ 4 toggle pill (`Chat`, `Image`, `Video`, `Speech`) vào modal **Import Account** (mặc định bật đủ 4) và modal **Edit Account** (nạp từ `acc.supported_models`); chặn nút lưu và hiển thị cảnh báo ngắn nếu bỏ chọn cả 4.

## Checklist triển khai (đối chiếu AC)

- [x] **Bước 1 — Schema, Migration & Validation `supported_models` trong DB (`FR-013`, `BR-005`, `AC-013`):**
  - Thêm cột `supported_models_json` + migration cho DB cũ trong `db.py` (mặc định `["chat","image","video","speech"]`).
  - Cài đặt `normalize_supported_models` & `parse_supported_models`; cập nhật `create_account` và `update_account`.
- [x] **Bước 2 — Admin Accounts API & Export (`FR-001`, `FR-008`, `FR-010`, `FR-013`, `BR-005`, `AC-006`, `AC-010`, `AC-013`):**
  - Mở rộng `POST /admin/accounts`, `PATCH /admin/accounts/{id}`, `GET /admin/accounts`, `GET /admin/accounts/export`.
  - Xác nhận trả `400` khi `supported_models` rỗng hoặc có giá trị không hợp lệ; đổi `supported_models` không đóng WSS socket.
- [x] **Bước 3 — Capability Routing & Fail-Fast `503` trong WSSPool & `/v1/*` (`FR-105`, `BR-111`, `AC-113`, `AC-114`):**
  - Cập nhật `WSSPool._candidate_accounts(capability)`, `_no_candidate_error(capability)`, `ensure_candidate(capability)`, `NoCandidateAccountError`.
  - Cập nhật toàn bộ endpoints trong `v1_openai.py` (`chat`, `responses`, `images/generations`, `images/edits`, `images/tasks`, `videos`, `videos/generations`, `audio/speech`) kiểm tra candidate sớm và trả `503` khi không có tài khoản hỗ trợ (không tạo task rác cho async).
- [x] **Bước 4 — Giao diện Accounts Console (`FR-013`, `AC-010`, `AC-014`):**
  - Cập nhật `AccountsPage.tsx`: hiển thị cột `Models` dạng badge chỉ xem; thêm 4 toggle pill (`Chat`, `Image`, `Video`, `Speech`) vào modal Import Account và Edit Account kèm validation tối thiểu 1 loại.
  - Giữ nguyên `OverviewPage.tsx`.
- [x] **Bước 5 — Kiểm thử tự động & Xác minh trình duyệt (`AC-013`, `AC-014`, `AC-113`, `AC-114`):**
  - Viết và chạy pytest cho `packages/backend/tests/test_account_supported_models.py` cùng toàn bộ test suite hiện có (24/24 tests passed).
  - Chạy `npm --prefix packages/frontend run build` đảm bảo 0 lỗi TypeScript/Vite.
  - Xác minh trên trình duyệt trang **Accounts** (bảng cột Models, modal Import mặc định đủ 4, modal Edit bật/tắt & chặn lưu khi bỏ chọn hết, lưu bền vững sau F5 và responsive mobile 390x844).

## Kế hoạch kiểm thử

1. **Unit & API Tests (`pytest`):**
   - Migration DB cũ thiếu cột `supported_models_json` tự động bổ sung và đọc ra đủ 4 loại.
   - `POST /admin/accounts` không truyền `supported_models` → mặc định đủ 4; truyền `[]` hoặc `["invalid"]` → `400`; truyền `["speech", "chat", "chat"]` → chuẩn hóa `["chat", "speech"]`.
   - `PATCH /admin/accounts/{id}` đổi `supported_models` cập nhật đúng và không gọi `close_account`.
   - `GET /admin/accounts/export` chứa đúng `supported_models`.
   - Pool routing: Account A (`["chat", "image", "speech"]`) và Account B (`["video"]`): `/v1/videos` chỉ chọn B; `/v1/chat/completions` (gồm cả `image_url`), `/v1/responses`, `/v1/images/*`, `/v1/audio/speech` chỉ chọn A.
   - Fail-fast `503`: khi không có account hỗ trợ `"video"` hoặc toàn bộ account bật `"video"` hết quota → `POST /v1/videos`, `POST /v1/images/tasks`, `POST /v1/chat/completions` (`stream=true`/`false`), `POST /v1/responses`, `POST /v1/audio/speech` trả ngay `503` với thông điệp rõ nguyên nhân và không tạo bản ghi `tasks` thừa cho async.
2. **Frontend Build & Browser Verification:**
   - Build frontend sạch (`tsc -b && vite build`).
   - Kiểm tra trực quan bảng Accounts (cột `Models` không vỡ layout), modal Import và modal Edit (bỏ chọn hết cả 4 sẽ khóa nút Save và hiển thị thông báo nhắc).
