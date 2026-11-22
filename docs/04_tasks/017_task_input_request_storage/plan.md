# Task 017: Lưu Input Request của các Task & Modal xem chi tiết

- **Liên kết Change Request:** [2026-11-19 — Lưu Input Request của các Task & Modal xem chi tiết](../../03_features/03_tasks_and_media/request-changes.md#2026-11-19--lưu-input-request-của-các-task--modal-xem-chi-tiết)
- **Liên kết Spec:** [03_tasks_and_media/spec.md](../../03_features/03_tasks_and_media/spec.md), [03_tasks_and_media/design.md](../../03_features/03_tasks_and_media/design.md), [03_tasks_and_media/logic.md](../../03_features/03_tasks_and_media/logic.md)
- **Mục tiêu:** Lưu trữ đầy đủ tham số đầu vào (`input_request_json`) của mọi task tạo từ 5 nguồn (`chat`, `image`, `video`, `audio`, `voice_preview`) với cơ chế rút gọn dữ liệu base64/binary và giới hạn `32 KB`, đồng thời cung cấp API `GET /admin/tasks/{id}` và Modal xem/copy chi tiết trên giao diện **Tasks History**.

## Danh sách tệp cần tạo / chỉnh sửa

- **Backend:**
  - `packages/backend/db.py`:
    - Thêm cột `input_request_json TEXT DEFAULT ''` vào bảng `tasks` và migration `ALTER TABLE tasks` cho DB cũ.
    - Bổ sung helper chuẩn hóa JSON (`sanitize` base64/data URI + giới hạn tối đa `32768` bytes UTF-8).
    - Cập nhật `create_task(..., input_request: Any = None)` để lưu `input_request_json`.
    - Cập nhật `list_tasks` loại trừ `input_request_json` để giữ payload nhẹ; cập nhật `get_task` trả về thêm `input_request` (parsed JSON) cùng `account_label`.
  - `packages/backend/routers/v1_openai.py`:
    - Truyền payload request đã trích xuất/chuẩn hóa vào `db.create_task` ở cả 4 nhóm endpoint: Chat (`/v1/chat/completions`, `/v1/responses`), Image (`/v1/images/generations`, `/v1/images/edits` với metadata file upload, `/v1/images`), Video (`/v1/videos*`), Audio TTS (`/v1/audio/speech`).
  - `packages/backend/services/voice_preview.py`:
    - Truyền `{ "source": "voice_preview", "voice_id", "voice_name", "language", "sample_text" }` vào `db.create_task`.
  - `packages/backend/routers/admin_core.py`:
    - Thêm endpoint `GET /admin/tasks/{task_id}` trả về chi tiết task kèm `input_request` (404 nếu không tìm thấy).
  - `packages/backend/tests/test_task_input_request.py` _(mới)_:
    - Unit & integration tests kiểm tra migration DB, sanitize base64, cắt `32 KB` giữ JSON hợp lệ, lưu đủ 5 nguồn, `GET /admin/tasks` không trả `input_request_json` và `GET /admin/tasks/{id}` trả đúng `input_request`.
- **Frontend:**
  - `packages/frontend/src/pages/TasksMediaPage.tsx`:
    - Thêm nút `View` (icon mắt) ở cột `Actions` trên từng dòng trong bảng **Tasks History**.
    - Thêm Modal **Task Detail** gọi `GET /admin/tasks/{id}`, hiển thị metadata task (`ID`, `Type`, `Model`, `Account`, `Status`, `Latency`, `Error`) và khối JSON `Input Request` có nút **Copy JSON**.

## Checklist triển khai (đối chiếu AC)

- [x] **Bước 1 — Database Schema, Sanitizer & `db.py` (`FR-201`, `BR-204`, `AC-207`):**
  - Thêm cột `input_request_json` vào `CREATE TABLE tasks` và migration `PRAGMA table_info(tasks)`.
  - Cài đặt helper sanitize base64/data URI/binary và giới hạn `32768` bytes UTF-8 giữ JSON hợp lệ.
  - Cập nhật `create_task`, `list_tasks` (loại trừ `input_request_json`) và `get_task` (trả kèm `input_request` parsed).
- [x] **Bước 2 — Cập nhật 5 nguồn tạo Task & Admin Detail API (`FR-201`, `FR-203`, `FR-206`, `AC-207`, `AC-208`):**
  - Truyền `input_request` vào `db.create_task` tại `v1_openai.py` (chat, responses, image generations/edits/tasks, video, speech) và `voice_preview.py`.
  - Thêm `GET /admin/tasks/{task_id}` vào `admin_core.py`.
- [x] **Bước 3 — Frontend Modal Task Detail (`FR-206`, `AC-208`):**
  - Bổ sung nút `View` ở bảng Tasks History và Modal **Task Detail** hiển thị `Input Request` JSON + nút **Copy**.
- [x] **Bước 4 — Kiểm thử tự động & xác minh trình duyệt (`AC-207`, `AC-208`):**
  - Chạy `packages/backend/tests/test_task_input_request.py` và toàn bộ backend test suite.
  - Chạy `npm --prefix packages/frontend run build` đảm bảo 0 lỗi TypeScript/Vite.
  - Xác minh trực tiếp trên trình duyệt tại trang Tasks & Media: mở Modal **Task Detail**, xem JSON và bấm **Copy**.

## Kế hoạch kiểm thử

1. **Unit & Integration Tests (`unittest`):**
   - Kiểm tra DB cũ không có cột `input_request_json` được migrate an toàn khi khởi tạo `Database`.
   - Kiểm tra payload chứa `data:image/png;base64,...` hoặc chuỗi base64 dài được thay thế thành placeholder tóm tắt (`[base64 ... ~XKB]`).
   - Kiểm tra payload text > `32 KB` được cắt gọn kèm `... [truncated]` và vẫn parse JSON thành công.
   - Kiểm tra `GET /admin/tasks` không trả `input_request_json` và `GET /admin/tasks/{id}` trả `input_request` đầy đủ (404 khi ID không tồn tại).
2. **Frontend Build & Browser Verification:**
   - `npm --prefix packages/frontend run build` thành công 0 lỗi.
   - Mở trang `/tasks`, bấm `View` trên một task để kiểm tra Modal **Task Detail** hiển thị đúng `Input Request` và copy được.
