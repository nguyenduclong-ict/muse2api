# Conventions — Quy chuẩn dự án

## 1. Quy chuẩn mã định danh tài liệu
- `FR-xxx`: Yêu cầu chức năng (Functional Requirement).
- `BR-xxx`: Quy tắc nghiệp vụ (Business Rule).
- `AC-xxx`: Tiêu chí nghiệm thu (Acceptance Criteria).
- `SCR-xx`: Mã màn hình giao diện (Screen ID).

## 2. Format Response & Error
- **Nhóm `/v1/*` (OpenAI-compatible):**
  - Trả JSON theo chuẩn OpenAI (`{"error": {"message": "...", "type": "...", "code": "..."}}`) kèm HTTP status `401`, `400`, `429`, `502`, `504`.
- **Nhóm `/admin/*` (Console API):**
  - Thành công: `200 OK` / `201 Created` trả JSON trực tiếp.
  - Lỗi: `{"detail": "..."}` với HTTP status `400`, `404`, `500`.

## 3. Bảo mật dữ liệu hiển thị & Logging
- Cookie (`hatch_sess`, `hatch_vml`, `hatch_gw`, `__Host-hatch_one_tap`) và mật khẩu proxy **không bao giờ** được ghi vào log hoặc trả nguyên văn ra API `/admin/accounts`. Khi hiển thị trên UI/API phải mask dạng `prefix...suffix`.
- Riêng **Client API Key** (`/v1/*`) được phép xem raw trên UI Admin theo yêu cầu vận hành.

## 4. Quy chuẩn thời gian & đường dẫn
- Toàn bộ timestamp lưu trong SQLite ở định dạng **Unix epoch seconds (float/int)** hoặc **ISO-8601 UTC**.
- Đường dẫn file media đầu ra lưu tương đối dưới `data/media/<filename>` và phục vụ qua `GET /v1/media/<filename>`.
