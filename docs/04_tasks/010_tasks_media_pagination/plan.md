# Task 010: Server-Side Pagination for Tasks & Media

- **Mục tiêu:** Bổ sung phân trang phía server (mặc định `10` bản ghi/trang) cho cả danh sách Tasks (`GET /admin/tasks`) và Media (`GET /admin/media`).
- **Liên kết Spec:** [03_tasks_and_media](../../03_features/03_tasks_and_media/spec.md)

## Kế hoạch thực hiện

1. **Database (`packages/backend/db.py`):**
   - Thêm `count_tasks(task_type="", status="") -> int` đếm tổng số task theo điều kiện lọc.
2. **Backend API (`packages/backend/routers/admin_core.py`):**
   - Cập nhật `GET /admin/tasks`: nhận `page: int = 1`, `page_size: int = 10` (clamp `1..100`), tính `offset = (page - 1) * page_size`, trả về `{"tasks": items, "total": total, "page": page, "page_size": page_size, "total_pages": total_pages}`.
   - Cập nhật `GET /admin/media`: nhận `page: int = 1`, `page_size: int = 10` (clamp `1..100`), cắt lát `files` sau khi sort theo `created_at DESC`, trả về `{"files": paged, "total": total, "page": page, "page_size": page_size, "total_pages": total_pages, "usage_bytes": ...}`.
3. **Frontend (`packages/frontend/src/pages/TasksMediaPage.tsx`):**
   - Quản lý `tasksPage` / `tasksPageSize` (mặc định `10`) và `mediaPage` / `mediaPageSize` (mặc định `10`).
   - Tự reset `tasksPage` về `1` khi đổi `typeFilter`/`statusFilter`; tự reset `selectedMedia` khi đổi trang Media và tự lùi trang nếu trang hiện tại vượt `total_pages` sau khi xóa.
   - Thêm thanh Pagination (`Showing X–Y of Z`, chọn `10 / 20 / 50`, nút `Prev` / số trang / `Next`) ở cuối mỗi bảng.
4. **Kiểm thử:**
   - `npm run build` pass.
   - `TestClient` kiểm tra `GET /admin/tasks?page=1&page_size=10`, `page=2`, filter `type`/`status`, và `GET /admin/media?page=1&page_size=10`, `page=2`.
