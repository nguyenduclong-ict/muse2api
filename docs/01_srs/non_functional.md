# Non-Functional Requirements — Yêu cầu phi chức năng

## 1. Hiệu năng & Tải trọng

- **Không phụ thuộc trình duyệt:** Loại bỏ hoàn toàn Chromium, giảm mức tiêu thụ RAM tĩnh xuống mức tiến trình Python thuần (< 150 MB khi idle).
- **WSS Connection Pooling:** Giữ ấm 1 kết nối WSS cho mỗi tài khoản `healthy`, tái sử dụng đa luồng qua `stream_id` multiplexing; tự động đóng/mở lại khi đứt kết nối hoặc token hết hạn.
- **Độ trễ khởi tạo:** HTTP bootstrap + `Noise_XX` handshake hoàn tất trong khoảng `1–4 giây` (tùy trạng thái VM đang chạy hay ngủ).

## 2. Độ tin cậy & Khả năng phục hồi

- **LRU Round-Robin & Failover:** Phân phối request đều giữa các tài khoản `healthy`; khi một tài khoản lỗi `401`/hết quota, đánh dấu trạng thái tương ứng (`expired`/`cooldown`) và chuyển ngay sang tài khoản kế tiếp.
- **An toàn dữ liệu:** SQLite bật chế độ `WAL` (`Write-Ahead Logging`) để đọc/ghi đồng thời từ FastAPI worker và Background Scheduler không bị khóa (`database is locked`).

## 3. Bảo mật & Quyền riêng tư

- Cookie tài khoản và thông tin xác thực proxy không được in ra stdout/file log và luôn được mask khi trả về qua `/admin/accounts`.
- Toàn bộ dữ liệu (DB, media tải về) lưu cục bộ trong thư mục `data/`, không gửi ra bên thứ 3 ngoài `muse.ai` / `hatch.metaaivm.com`.
