# Feature Spec: Proxy Management

- **Trạng thái:** `Ready for Implementation`
- **Liên quan:** [ERD](../../02_basic_design/02_database/erd.md), [Screens Overview](../../02_basic_design/03_screens_overview.md), [Accounts Spec](../01_accounts_and_keepalive/spec.md)

## 1. Mục tiêu & Bối cảnh
Quản lý tập trung danh sách proxy (HTTP/HTTPS/SOCKS5), kiểm tra trạng thái sống và IP đầu ra qua `ipinfo.io`, cho phép gắn proxy cho từng Account từ danh sách có sẵn thay vì nhập tay rời rạc.

## 2. Phạm vi
- **In Scope:**
  - Import nhiều proxy cùng lúc từ textarea plain text (mỗi proxy 1 dòng).
  - Check trạng thái từng proxy hoặc toàn bộ proxy qua `https://ipinfo.io/json`.
  - Hiển thị danh sách proxy (masked credentials, scheme, IP, country/city, org, latency, số account đang gắn).
  - Xóa proxy (tự động gỡ khỏi các account đang gắn).
- **Out of Scope:** Proxy Pool / round-robin (đã hoãn sang phiên bản sau).

## 3. Yêu cầu chức năng (`FR`)
- **FR-401 (Import nhiều Proxy dạng Textarea):** `POST /admin/proxies/import` nhận chuỗi plain text, tách theo dòng, bỏ qua dòng trống và các dòng trùng lặp đã tồn tại; hỗ trợ các định dạng:
  - URL chuẩn: `http://host:port`, `http://user:pass@host:port`, `https://...`, `socks5://...`, `socks5h://...`
  - Dạng rút gọn: `host:port` và `host:port:user:pass` (tự động chuẩn hóa thành `http://...`).
- **FR-402 (Check Proxy qua `ipinfo`):** `POST /admin/proxies/{id}/check` và `POST /admin/proxies/check-all` gọi `GET https://ipinfo.io/json` thông qua proxy đó (timeout 15s), lưu `ip`, `country`, `city`, `org`, `latency_ms`, `last_checked_at`, cập nhật `status = alive` hoặc `dead` + `last_error`.
- **FR-403 (Xóa Proxy & Tự động gỡ khỏi Account):** `DELETE /admin/proxies/{id}` xóa bản ghi khỏi bảng `proxies`; nhờ `ON DELETE SET NULL` (và đóng WSS socket của các account bị ảnh hưởng nếu cần), mọi account đang gắn proxy này tự động chuyển `proxy_id = NULL` (Direct).

## 4. Quy tắc nghiệp vụ (`BR`)
- **BR-401:** Mật khẩu proxy luôn được mask (`scheme://***:***@host:port`) khi trả về API `GET /admin/proxies` và hiển thị trên UI.
- **BR-402:** Khi gán hoặc thay đổi `proxy_id` của một account, kết nối WSS hiện tại của account đó phải được đóng để lần kết nối tiếp theo dùng đúng proxy mới.

## 5. Tiêu chí nghiệm thu (`AC`)
- **AC-401:** Paste danh sách gồm `host:port`, `host:port:user:pass`, `socks5://user:pass@host:port` vào modal/textarea Import và bấm Import lưu đúng các proxy chuẩn hóa vào SQLite.
- **AC-402:** Bấm Check trên một proxy sống cập nhật `status=alive`, hiển thị IP egress, quốc gia/thành phố và latency (`ms`).
- **AC-403:** Xóa một proxy đang được gắn cho Account A sẽ tự động đặt `proxy_id=null` trên Account A mà không gây lỗi khóa ngoại.
