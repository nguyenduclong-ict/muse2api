# Request changes: Tasks & Media Management

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
