# Feature Spec: Settings (Global System Prompt, Voice Languages & Media Cleanup)

- **Trạng thái:** `Ready for Implementation`
- **Liên quan:** [Schema Summary](../../02_basic_design/02_database/schema_summary.md), [Non-Functional](../../01_srs/non_functional.md), [OpenAI API & Keys](../02_openai_api_and_keys/spec.md)

## 1. Mục tiêu & Bối cảnh
Quản lý cấu hình runtime của hệ thống thông qua UI Settings (`SCR-05`) và lưu bền vững trong bảng `settings` của SQLite (ghi đè `.env` sau khi lưu): **Global System Prompt**, **Voice Languages** và **Media Cleanup**.

## 2. Phạm vi
- **In Scope:**
  - Bật/tắt & chỉnh sửa Global System Prompt (có Reset Default).
  - Bật/tắt & chọn danh sách ngôn ngữ giọng đọc TTS được hỗ trợ (**Voice Languages**), đồng bộ trực tiếp tới `GET /v1/audio/voices` và `POST /v1/audio/speech`.
  - Cấu hình chính sách dọn dẹp `data/media/` (`retention_days`, `max_gb`, `interval_minutes`) và chạy dọn thủ công.
- **Out of Scope:** Quản lý biến môi trường cấp OS, restart server từ UI, hoặc ẩn/hiện lẻ từng `voice_id` cụ thể.

## 3. Yêu cầu chức năng (`FR`)
- **FR-301 (Global System Prompt):**
  - Lưu 2 trường `enabled` (mặc định `false`) và `prompt` (mặc định nội dung session-isolation).
  - Cho phép chỉnh sửa, bật/tắt, và **Reset to Default**.
- **FR-302 (Media Cleanup Policy):**
  - Lưu `enabled` (mặc định `true`), `retention_days` (mặc định `1`, `0` = tắt xóa theo tuổi), `max_gb` (mặc định `1.0`, `0` = tắt giới hạn dung lượng), `interval_minutes` (mặc định `60`, tối thiểu `5`).
- **FR-303 (Scheduled & Manual Cleanup):**
  - Background Scheduler quét `data/media/` theo chu kỳ `interval_minutes`: xóa file quá `retention_days`, sau đó nếu tổng dung lượng vẫn vượt `max_gb`, xóa tiếp các file cũ nhất đến khi đạt ngưỡng.
  - Nút **Run Cleanup Now** (`POST /admin/cleanup/run`) thực thi ngay và trả về số file + dung lượng đã giải phóng.
- **FR-304 (Voice Languages Filter):**
  - Lưu bản ghi `voice_languages` trong bảng `settings` gồm `{ "enabled": bool, "languages": list[str] }` (mặc định `enabled = false`, `languages = []`).
  - `GET /admin/settings` trả thêm `voice_languages` và `available_voice_languages` (danh sách 31 nhóm ngôn ngữ / quốc gia chuẩn kèm số lượng giọng thực tế từng nhóm: `[{ "name": str, "count": int }, ...]`).
  - `POST /admin/settings` nhận thêm trường tùy chọn `voice_languages` để cập nhật cấu hình ngay lập tức không cần khởi động lại server.
  - Giao diện **Settings** (`SCR-05`) bổ sung card **Voice Languages** gồm công tắc bật/tắt (`Switch`), lưới chọn nhiều ngôn ngữ / quốc gia hiển thị tên và số giọng (`English (US) (541)`, `English (UK) (200)`, `Vietnamese (7)`, `Japanese (6)`...), nút **Select All**, **Clear** và **Save Voice Languages**.

## 4. Quy tắc nghiệp vụ (`BR`)
- **BR-301:** `interval_minutes` luôn được kẹp tối thiểu `>= 5` phút ở backend để tránh quét ổ đĩa liên tục.
- **BR-302:** Khi `Global System Prompt` tắt (`enabled=false`), không chèn `<system>...</system>` vào request gửi qua WSS.
- **BR-303 (Ánh xạ 31 Nhóm Ngôn ngữ / Quốc gia Chuẩn cho Danh mục Giọng):**
  - Do dữ liệu gốc trong `packages/backend/data/voices.json` lưu mã `language` chỉ gồm `eng`/`fra` còn phân loại vùng/ngôn ngữ nằm ở trường `accent` (36 giá trị), toàn bộ 1,218 giọng công khai được phân vào đúng **31 nhóm chuẩn** (mỗi giọng thuộc duy nhất 1 nhóm), trong đó Tiếng Anh được tách riêng theo 13 quốc gia:
    - **Tiếng Anh theo quốc gia (13 nhóm — 999 giọng):**
      - `English (US)` (541): `American` (458), `Southern American` (75), `New York` (7), `Mid-Atlantic` (1)
      - `English (UK)` (200): `British` (170), `Scottish` (30)
      - `English (Australia)` (73): `Australian`
      - `English (Ireland)` (39): `Irish`
      - `English (South Africa)` (20): `South African`
      - `English (Kenya)` (20): `Kenyan`
      - `English (Nigeria)` (20): `Nigerian`
      - `English (Trinidad)` (20): `Trinidadian`
      - `English (Zimbabwe)` (19): `Zimbabwean`
      - `English (New Zealand)` (15): `New Zealand`
      - `English (Singapore)` (12): `Singaporean`
      - `English (Jamaica)` (11): `Jamaican`
      - `English (Canada)` (9): `Canadian`
    - **Các ngôn ngữ / quốc gia khác (17 nhóm — 218 giọng):**
      - `French` (35): `French` (20), `French Canadian` (15, và mọi giọng có `language == "fra"`)
      - `Indian` (26): `Indian`
      - `Finnish` (20): `Finnish`
      - `Indonesian` (18): `Indonesian`
      - `Spanish` (14): `Spanish`
      - `German` (13): `German`
      - `Arabic` (11): `Middle Eastern`
      - `Portuguese` (11): `Brazilian`
      - `Filipino` (10): `Filipino`
      - `Malaysian` (10): `Malaysian`
      - `Chinese` (9): `Chinese`
      - `Russian` (9): `Russian`
      - `Italian` (8): `Italian`
      - `Thai` (7): `Thai`
      - `Vietnamese` (7): `Vietnamese`
      - `Japanese` (6): `Japanese`
      - `Korean` (4): `Korean`
    - **Khác (1 nhóm — 1 giọng):**
      - `Other` (1): `Transylvanian`
- **BR-304 (Hành vi mặc định, Chuẩn hóa & Tương thích ngược `"English"`):**
  - Khi `voice_languages.enabled == false` **hoặc** `voice_languages.languages` rỗng (`[]`), bộ lọc không hoạt động — hệ thống cho phép toàn bộ 1,218 giọng.
  - Khi lưu qua `POST /admin/settings` hoặc đọc từ DB cũ, backend đối chiếu không phân biệt hoa thường với danh mục 31 nhóm chuẩn, chuẩn hóa về tên chính tắc (canonical name), loại trùng và bỏ qua giá trị không hợp lệ.
  - **Tương thích ngược:** Nếu đầu vào hoặc cấu hình DB cũ chứa giá trị `"English"` (không phân biệt hoa thường), backend tự động mở rộng (expand) thành toàn bộ 13 nhóm `English (*)`.

## 5. Tiêu chí nghiệm thu (`AC`)
- **AC-301:** Lưu `Global System Prompt` với `enabled=true` áp dụng ngay cho request `/v1/chat/completions` tiếp theo mà không cần restart backend.
- **AC-302:** Chạy **Run Cleanup Now** khi `data/media/` vượt `max_gb` hoặc có file quá `retention_days` xóa đúng các file cũ nhất và trả về thống kê chính xác.
- **AC-303:** Trên màn hình **Settings** (`SCR-05`), `GET /admin/settings` trả đủ 31 nhóm trong `available_voice_languages` (tổng count = 1,218, trong đó `English (US)` = 541, `English (UK)` = 200); khi bật `Voice Languages`, chọn `English (US)`, `Vietnamese`, `Japanese` và bấm **Save Voice Languages**, trạng thái lưu bền vững trong SQLite và áp dụng ngay cho `GET /v1/audio/voices` lẫn `POST /v1/audio/speech` mà không cần restart backend.
- **AC-304:** Khi tắt công tắc `Voice Languages` (`enabled=false`) hoặc bỏ chọn tất cả (`languages=[]`) rồi lưu, `GET /v1/audio/voices` trả lại toàn bộ 1,218 giọng và `POST /v1/audio/speech` cho phép toàn bộ giọng hợp lệ; khi cấu hình DB cũ có `"English"`, hệ thống tự động mở rộng đủ 13 nhóm `English (*)`.
