# Feature Spec: Settings (Global System Prompt & Media Cleanup)

- **Trạng thái:** `Ready for Implementation`
- **Liên quan:** [Schema Summary](../../02_basic_design/02_database/schema_summary.md), [Non-Functional](../../01_srs/non_functional.md)

## 1. Mục tiêu & Bối cảnh
Quản lý cấu hình runtime của hệ thống thông qua UI Settings (`SCR-05`) và lưu bền vững trong bảng `settings` của SQLite (ghi đè `.env` sau khi lưu): **Global System Prompt** và **Media Cleanup**.

## 2. Phạm vi
- **In Scope:** Bật/tắt & chỉnh sửa Global System Prompt (có Reset Default), cấu hình chính sách dọn dẹp `data/media/` (retention days, max GB, interval minutes) và chạy dọn thủ công.
- **Out of Scope:** Quản lý biến môi trường cấp OS hay restart server từ UI.

## 3. Yêu cầu chức năng (`FR`)
- **FR-301 (Global System Prompt):**
  - Lưu 2 trường `enabled` (mặc định `false`) và `prompt` (mặc định nội dung session-isolation).
  - Cho phép chỉnh sửa, bật/tắt, và **Reset to Default**.
- **FR-302 (Media Cleanup Policy):**
  - Lưu `enabled` (mặc định `true`), `retention_days` (mặc định `1`, `0` = tắt xóa theo tuổi), `max_gb` (mặc định `1.0`, `0` = tắt giới hạn dung lượng), `interval_minutes` (mặc định `60`, tối thiểu `5`).
- **FR-303 (Scheduled & Manual Cleanup):**
  - Background Scheduler quét `data/media/` theo chu kỳ `interval_minutes`: xóa file quá `retention_days`, sau đó nếu tổng dung lượng vẫn vượt `max_gb`, xóa tiếp các file cũ nhất đến khi đạt ngưỡng.
  - Nút **Run Cleanup Now** (`POST /admin/cleanup/run`) thực thi ngay và trả về số file + dung lượng đã giải phóng.

## 4. Quy tắc nghiệp vụ (`BR`)
- **BR-301:** `interval_minutes` luôn được kẹp tối thiểu `>= 5` phút ở backend để tránh quét ổ đĩa liên tục.
- **BR-302:** Khi `Global System Prompt` tắt (`enabled=false`), không chèn `<system>...</system>` vào request gửi qua WSS.

## 5. Tiêu chí nghiệm thu (`AC`)
- **AC-301:** Lưu `Global System Prompt` với `enabled=true` áp dụng ngay cho request `/v1/chat/completions` tiếp theo mà không cần restart backend.
- **AC-302:** Chạy **Run Cleanup Now** khi `data/media/` vượt `max_gb` hoặc có file quá `retention_days` xóa đúng các file cũ nhất và trả về thống kê chính xác.
