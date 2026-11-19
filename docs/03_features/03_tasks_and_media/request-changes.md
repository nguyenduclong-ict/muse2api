# Request changes: Tasks & Media Management

## 2026-11-19 — Lưu Input Request của các Task & Modal xem chi tiết

- **Yêu cầu:** Lưu thêm toàn bộ input request của các task vào database và cho phép xem chi tiết trên giao diện Tasks History.
- **Phân loại:** Feature mở rộng
- **Đặc tả thay đổi:**
  - `spec.md`: cập nhật `FR-201`, `FR-203`, bổ sung `FR-206`, `BR-204`, `AC-207`, `AC-208`.
  - `design.md`: thêm nút `[View]` trên bảng Tasks History và Modal `Task Detail`.
  - `logic.md`: thêm handler `GET /admin/tasks/{id}` và quy trình sanitize base64 + giới hạn `32 KB` cho `input_request_json`.
  - `02_basic_design/02_database/erd.md`: bổ sung cột `input_request_json` vào bảng `TASKS`.
  - `02_basic_design/01_api_overview.md`: bổ sung `GET /admin/tasks/{id}`.
- **Quyết định:** Lưu JSON đầy đủ tham số cho cả 5 nguồn tạo task (`chat`, `image`, `video`, `audio`, `voice_preview`), thay thế dữ liệu base64/binary lớn bằng metadata tóm tắt, giới hạn `32 KB`, và tách payload chi tiết qua `GET /admin/tasks/{id}` để không làm chậm `GET /admin/tasks`.
- **Task:** `chưa tạo`

## 2026-11-19 — Hỗ trợ bộ lọc Task `audio` và trình phát Audio Preview

- **Yêu cầu:** Cập nhật trang Tasks & Media để lọc được các tác vụ TTS (`type=audio`) và nghe thử file `.mp3` trực tiếp trong modal Preview.
- **Phân loại:** Feature mở rộng
- **Đặc tả thay đổi:**
  - `spec.md`: cập nhật `FR-203`, `FR-205`, bổ sung `AC-206`.
- **Quyết định:** Tận dụng phân loại `kind="audio"` đã có ở `GET /admin/media`, bổ sung option `audio` ở dropdown Type của Tasks và thẻ `<audio controls>` trong modal Preview.
- **Task:** [T-012](../../04_tasks/012_audio_voices_and_speech/plan.md)

## 2026-11-17 — Phân trang Server cho Tasks & Media (mặc định 10)

- **Yêu cầu:** Thêm phân trang server (mặc định `page_size=10`) cho danh sách Tasks và danh sách Media.
- **Phân loại:** Feature mở rộng / Pagination
- **Đặc tả thay đổi:**
  - `spec.md`: cập nhật `FR-203`, `FR-205`, bổ sung `AC-205`.
- **Quyết định:** Chuẩn hóa query params `page` (1-based) & `page_size` (default `10`, max `100`), trả về `{ total, page, page_size, total_pages }` ở cả `/admin/tasks` và `/admin/media`.
- **Task:** [T-010](../../04_tasks/010_tasks_media_pagination/plan.md)

## 2026-11-17 — Xóa Task tự động xóa Media liên quan

- **Yêu cầu:** Khi xóa 1 task hoặc Clear Completed, xóa luôn file media liên quan trong `data/media/`.
- **Phân loại:** Feature mở rộng
- **Đặc tả thay đổi:**
  - `spec.md`: cập nhật `FR-204`, bổ sung `AC-204`.
- **Quyết định:** Kiểm tra chỉ xóa file nếu không còn bản ghi task nào khác tham chiếu tới cùng `media_filename`.
- **Task:** [T-007](../../04_tasks/007_proxies_extension_task_cleanup/plan.md)

## 2026-11-17 — Overview Accounts+Quota, Media Thumbnail, Multi-Select & Zero-Shift UI

- **Yêu cầu:** Bỏ Recent Tasks ở Overview để hiển thị Accounts + Quota; thêm thumbnail, custom Checkbox chọn nhiều và xóa hàng loạt ở Media Library; sửa lỗi nhảy layout khi hiện nút Delete Selected và dùng `react-router-dom`.
- **Phân loại:** Feature mở rộng
- **Đặc tả thay đổi:**
  - `spec.md`: cập nhật `FR-202`, `FR-205`, `AC-203`, bổ sung `BR-203`.
  - `00_common/tech_stack.md`: bổ sung `react-router-dom`.
  - `02_basic_design/01_api_overview.md`: bổ sung `POST /admin/media/delete`.
- **Quyết định:** Dùng custom `Checkbox` component (hỗ trợ `indeterminate`), giữ cố định chiều cao `CardHeader` và dùng `overflow-y-scroll` ở `<main>` để loại bỏ nhảy layout.
- **Task:** đã triển khai trực tiếp
