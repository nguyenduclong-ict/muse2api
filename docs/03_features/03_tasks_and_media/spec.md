# Feature Spec: Tasks & Media Management

- **Trạng thái:** `Ready for Implementation`
- **Liên quan:** [ERD](../../02_basic_design/02_database/erd.md), [Screens Overview](../../02_basic_design/03_screens_overview.md)

## 1. Mục tiêu & Bối cảnh
Cung cấp bảng điều khiển Overview (`SCR-01`) và trang Tasks & Media (`SCR-04`) để theo dõi toàn bộ lịch sử tác vụ sinh nội dung (`chat`, `image`, `video`, `speech`), xem tiến trình realtime, xóa task và quản lý thư viện file media trong `data/media/`.

## 2. Phạm vi
- **In Scope:** Lưu vết task trong SQLite, thống kê 7 ngày cho Overview, lọc task theo loại/trạng thái, xóa từng task hoặc Clear Completed, xem/xóa file media.
- **Out of Scope:** Chỉnh sửa nội dung media trực tiếp trên UI.

## 3. Yêu cầu chức năng (`FR`)
- **FR-201 (Ghi nhận Task):** Mọi request tới `/v1/chat/completions`, `/v1/responses`, `/v1/images/*`, `/v1/videos*`, `/v1/audio/speech` và luồng `Voice Preview` đều tạo bản ghi trong bảng `tasks` (`queued`/`running` → `completed`/`failed`), lưu `account_id`, `model`, `prompt_preview`, `input_request_json`, `latency_ms`, `media_filename`, `error_message`.
- **FR-202 (Overview Dashboard):** `GET /admin/dashboard` trả về: số tài khoản healthy/total, số WSS tunnel đang mở, thống kê task 7 ngày gần nhất, tổng dung lượng `data/media/`, và danh sách `accounts` kèm `quota` (bỏ bảng Recent Tasks khỏi Overview).
- **FR-203 (Danh sách, Lọc & Phân trang Server Tasks):** `GET /admin/tasks` hỗ trợ lọc theo `type` (`chat`, `image`, `video`, `audio`), `status` (`running`, `completed`, `failed`), và phân trang server qua `page` (mặc định `1`), `page_size` (mặc định `10`, tối đa `100`), trả về `{ tasks, total, page, page_size, total_pages }` (không kèm `input_request_json` để giữ payload nhẹ).
- **FR-204 (Xóa Tasks & Dọn Media liên quan):** `DELETE /admin/tasks/{id}` xóa 1 task và xóa luôn file `media_filename` tương ứng trong `data/media/` (nếu không còn task khác tham chiếu); `POST /admin/tasks/clear` xóa toàn bộ task không còn `running` và dọn sạch các file media tương ứng của các task đó.
- **FR-205 (Thư viện Media, Multi-Select & Phân trang Server):** `GET /admin/media` hỗ trợ phân trang server qua `page` (mặc định `1`), `page_size` (mặc định `10`, tối đa `100`), trả về `{ files, total, page, page_size, total_pages, usage_bytes }`; liệt kê file kèm thumbnail/icon preview (`<img>` / `<video>` / `<audio>`), modal xem/nghe media (gồm trình phát `<audio controls>` cho file audio), chọn nhiều file qua custom `Checkbox` (`indeterminate`) và xóa hàng loạt qua `POST /admin/media/delete` hoặc xóa lẻ qua `DELETE /admin/media/{name}`.
- **FR-206 (Xem chi tiết Task & Input Request):** `GET /admin/tasks/{id}` trả về thông tin đầy đủ của 1 task bao gồm `input_request` (đã parse JSON, hoặc object rỗng/null nếu bản ghi cũ chưa có). Trên tab **Tasks History**, mỗi dòng có nút mở Modal **Task Detail** hiển thị metadata và nội dung `Input Request` dạng JSON có nút **Copy**.

## 4. Quy tắc nghiệp vụ (`BR`)
- **BR-201:** `prompt_preview` chỉ lưu tối đa `200` ký tự đầu để giữ DB gọn nhẹ.
- **BR-202:** Không cho phép xóa task đang ở trạng thái `running` qua `POST /admin/tasks/clear`.
- **BR-203 (Zero Layout Shift):** `CardHeader` của bảng Media giữ chiều cao tối thiểu cố định và dành sẵn không gian cho nút `Delete Selected` (`invisible` khi chưa chọn) để thao tác check/uncheck không làm dịch chuyển bảng.
- **BR-204 (Chuẩn hóa & Giới hạn `input_request_json`):**
  - Tự động thay thế chuỗi base64/data URI ảnh hoặc nội dung file upload nhị phân (ví dụ `/v1/images/edits`, `reference_images`, `image_url`) bằng metadata tóm tắt dạng `"[base64 image ~120KB]"` hoặc `"[uploaded file: name, ~120KB]"`.
  - Giới hạn kích thước tối đa của chuỗi `input_request_json` là `32 KB` (`32768` bytes UTF-8). Nếu vượt ngưỡng, cắt gọn các trường chuỗi dài kèm hậu tố `... [truncated]` sao cho kết quả vẫn là JSON hợp lệ.

## 5. Tiêu chí nghiệm thu (`AC`)
- **AC-201:** Sau khi gọi `/v1/videos`, task xuất hiện với `status=running` và tự động cập nhật sang `completed` kèm `media_filename` khi video tải xong.
- **AC-202:** Bấm **Clear Completed** xóa toàn bộ task `completed`/`failed` nhưng giữ nguyên task `running`.
- **AC-203:** Xóa 1 hoặc nhiều file qua `POST /admin/media/delete` sẽ xóa các file vật lý khỏi `data/media/` mà không làm nhảy layout khi chọn checkbox.
- **AC-204:** Xóa 1 task có `media_filename` (qua `DELETE /admin/tasks/{id}` hoặc `POST /admin/tasks/clear`) sẽ xóa luôn file vật lý trong `data/media/`.
- **AC-205:** Cả 2 tab **Tasks** và **Media** mặc định hiển thị tối đa `10` bản ghi mỗi trang từ API server (`page=1&page_size=10`), có điều hướng chuyển trang và đổi `page_size` (`10 / 20 / 50`), tự reset về trang `1` khi đổi bộ lọc.
- **AC-206:** Bộ lọc `Type` trong tab **Tasks** có tùy chọn `audio` để lọc các tác vụ TTS; bấm xem một file `.mp3` trong tab **Media** mở modal hiển thị trình phát `<audio controls>` phát được file từ `/v1/media/{filename}`.
- **AC-207:** Mọi task tạo mới từ 5 nguồn (`chat`, `image`, `video`, `audio`, `voice_preview`) đều lưu `input_request_json` hợp lệ; dữ liệu base64/binary lớn được thay bằng placeholder tóm tắt và tổng dung lượng chuỗi JSON không vượt quá `32 KB`.
- **AC-208:** Gọi `GET /admin/tasks/{id}` trả về chi tiết task kèm `input_request` đã parse; trên UI tab **Tasks History**, bấm nút xem chi tiết mở Modal hiển thị `Input Request` và copy được nội dung JSON.
