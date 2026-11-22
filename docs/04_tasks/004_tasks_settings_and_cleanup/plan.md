# Task 004: Tasks, Media Library & Settings Cleanup

## 1. Mục tiêu triển khai

Triển khai API Dashboard, quản lý Tasks, Media Library, Settings (Global System Prompt & Media Cleanup) và Background Cleanup Worker theo [Tasks Spec](../../03_features/03_tasks_and_media/spec.md) và [Settings Spec](../../03_features/04_settings_and_cleanup/spec.md).

## 2. Danh sách tệp tin cần tạo

- `backend/services/cleanup.py`
- `backend/routers/tasks.py`
- `backend/routers/settings.py`
- `backend/main.py`

## 3. Checklist triển khai

- [ ] `routers/tasks.py`: `/admin/dashboard` (pool health, 7-day trend, recent tasks), `/admin/tasks` (filter `type`, `status`), `DELETE /admin/tasks/{id}`, `POST /admin/tasks/clear` (`AC-201`, `AC-202`), `/admin/media` & `DELETE /admin/media/{name}` (`AC-203`).
- [ ] `routers/settings.py`: `GET/POST /admin/settings` cho `system_prompt` và `media_cleanup`, validate `interval_minutes >= 5` (`AC-301`).
- [ ] `services/cleanup.py`: scheduler chạy nền + `POST /admin/cleanup/run` xóa theo tuổi và ngưỡng `max_gb` (`AC-302`).
- [ ] `main.py`: ghép toàn bộ router `/v1/*`, `/admin/*`, `/healthz`, `/readyz` và cấu hình serve static `frontend/dist/`.

## 4. Kế hoạch kiểm thử

- **Unit test:** Thuật toán cleanup theo `retention_days` và `max_gb`, clear tasks giữ lại `running`.
- **Integration test:** Test lưu settings, chạy `POST /admin/cleanup/run`, lọc/xóa tasks và media.
