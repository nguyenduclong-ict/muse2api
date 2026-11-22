# Task 007: Proxy Management, Extension Download & Task Media Cleanup

- **Nguồn thay đổi:** [Accounts RC](../../03_features/01_accounts_and_keepalive/request-changes.md), [Tasks RC](../../03_features/03_tasks_and_media/request-changes.md), [Proxy Spec](../../03_features/05_proxy_management/spec.md)

## 1. Mục tiêu triển khai

1. Xóa task (`DELETE /admin/tasks/{id}`, `POST /admin/tasks/clear`) tự động xóa file media tương ứng trong `data/media/`.
2. Keep-Alive chạy ngầm cập nhật chuẩn `status` (`healthy`/`expired`/`cooldown`) cho account.
3. Tạo thư mục `extension/` (Manifest V3 copy cookie `muse.ai`) và endpoint `GET /admin/extension/download` + nút tải trên UI.
4. Xây dựng trang quản lý Proxy (`/proxies`): import nhiều dòng, check qua `ipinfo.io`, gắn proxy từ danh sách vào Account (bỏ nhập raw), tự gỡ khỏi Account khi xóa proxy.

## 2. Danh sách tệp tin cần tạo / chỉnh sửa

- `extension/manifest.json`, `extension/popup.html`, `extension/popup.js` (tạo mới)
- `backend/db.py`, `backend/services/keepalive.py`, `backend/services/wss_pool.py`
- `backend/services/proxy_utils.py`, `backend/routers/proxies.py` (tạo mới)
- `backend/routers/accounts.py`, `backend/routers/admin_core.py`, `backend/main.py`
- `frontend/src/pages/ProxiesPage.tsx` (tạo mới), `frontend/src/pages/AccountsPage.tsx`, `frontend/src/components/Layout.tsx`, `frontend/src/App.tsx`

## 3. Checklist triển khai

- [ ] `extension/`: tạo Manifest V3 extension đọc & copy cookie `muse.ai`.
- [ ] `db.py`: thêm bảng `proxies`, cột `accounts.proxy_id` (`ON DELETE SET NULL`), trả danh sách `media_filename` cần xóa khi xóa task.
- [ ] `proxy_utils.py` & `routers/proxies.py`: parse multi-line proxy, check `ipinfo.io`, xóa proxy tự gỡ khỏi accounts.
- [ ] `accounts.py`, `admin_core.py`, `keepalive.py`, `wss_pool.py`: `proxy_id`, download extension `.zip`, xóa media khi xóa task, Keep-Alive cập nhật `status`.
- [ ] `frontend/`: trang `ProxiesPage`, route `/proxies`, dropdown chọn Proxy & nút `Download Extension` ở `AccountsPage`.

## 4. Kế hoạch kiểm thử

- **Backend (`TestClient`):** Test import nhiều proxy, xóa proxy tự gỡ `proxy_id` khỏi account, xóa task xóa luôn file media trong `data/media/`, tải `.zip` extension (`200 OK`), Keep-Alive cập nhật `status`.
- **Frontend:** `npm run build` (`tsc -b && vite build`) pass 0 lỗi.
