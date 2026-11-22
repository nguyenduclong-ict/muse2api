# Task 009: Account Edit Modal, Unified Refresh, Proxy Display & Background WSS Tunnel

- **Mục tiêu:** Thêm nút Edit Account (mở modal chỉnh sửa), hiển thị cột Proxy gọn (`No proxy` hoặc `proxy_ip` / `proxy_masked`), gộp nút Refresh (check status + WSS + quota), và chạy nền WSS Tunnel tự động cập nhật trạng thái cho frontend.
- **Liên kết Spec:** [01_accounts_and_keepalive](../../03_features/01_accounts_and_keepalive/spec.md), [design.md](../../03_features/01_accounts_and_keepalive/design.md)

## Kế hoạch thực hiện

1. **Backend — Unified Refresh & Background WSS Tunnel:**
   - Thêm `POST /admin/accounts/{id}/refresh` và `POST /admin/accounts/refresh` trong `backend/routers/accounts.py`: thực hiện tuần tự/đồng bộ Keep-Alive (session check) + kết nối WSS (`wss_pool.test_account` / giữ tunnel mở) + lấy quota (`fetch_quota_http`), trả về thông tin account đã cập nhật.
   - Bổ sung vòng lặp nền `WSSMonitor` / background loop trong `backend/services/wss_pool.py` (hoặc `backend/main.py` lifespan) định kỳ kiểm tra/duy trì kết nối WSS Tunnel cho các account `enabled=true` (không `expired`, chưa hết quota) và cập nhật `status` / `wss_connected`.
   - Đảm bảo `PATCH /admin/accounts/{id}` hỗ trợ sửa `label`, `cookies_raw` (tùy chọn), `proxy_id` (kể cả gán `null` để về `No proxy`), `enabled` — và đóng kết nối WSS cũ nếu đổi proxy hoặc cookie hoặc tắt `enabled`.
2. **Frontend — AccountsPage UI:**
   - Cột **Proxy**: bỏ `<select>`, hiển thị `No proxy` khi `!acc.has_proxy`, hoặc `acc.proxy_ip || acc.proxy_masked` khi có proxy.
   - Bảng Actions: bỏ nút `Quota` và `Test WSS`; giữ/đổi thành nút **Edit** (mở Modal Edit), nút **Refresh** (gọi `POST /admin/accounts/{id}/refresh`), và nút **Delete**.
   - Nút **Refresh All** ở header gọi `POST /admin/accounts/refresh` để kiểm tra đồng bộ status + WSS + quota cho toàn bộ account đang bật.
   - Tạo **Modal Edit Account**: sửa `label`, `cookies_raw` (optional), `proxy_id` (dropdown từ danh sách Proxies), `enabled` switch.
3. **Kiểm thử:**
   - `npm run build` (`tsc -b && vite build`) pass.
   - `TestClient` kiểm tra `PATCH /admin/accounts/{id}` (đổi `label`, đổi `proxy_id` về `null`), `POST /admin/accounts/{id}/refresh`, `POST /admin/accounts/refresh`, và background WSS loop.
