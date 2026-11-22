# Task 011: Extension Import Cookie & Account Copy Cookie

- **Mục tiêu:** Thêm tính năng Import Cookie vào Chrome Extension (`extension/`) và nút Copy Cookie cho từng tài khoản trên màn Accounts (`AccountsPage.tsx`) để copy nhanh cookie dán vào extension.
- **Liên kết Spec:** [01_accounts_and_keepalive](../../03_features/01_accounts_and_keepalive/spec.md), [design.md](../../03_features/01_accounts_and_keepalive/design.md)

## Kế hoạch thực hiện

1. **Backend (`packages/backend/routers/accounts.py`):**
   - Thêm endpoint `GET /admin/accounts/{account_id}/cookies`: trả về `{ id, label, cookie_header, cookies }` (dùng `cookies_to_header`).
2. **Frontend (`packages/frontend/src/pages/AccountsPage.tsx`):**
   - Thêm nút **Copy Cookie** (`Copy` icon) trên mỗi dòng Account: gọi `GET /admin/accounts/${acc.id}/cookies`, ghi `cookie_header` vào `navigator.clipboard`, hiển thị Toast thành công (`Copied cookies for ...`).
3. **Chrome Extension (`extension/`):**
   - Cập nhật `popup.html` & `popup.js`:
     - Giữ nút **Copy muse.ai Cookies** (Export).
     - Thêm phần **Import Cookies**: `<textarea>` nhận `Cookie:` header string (`k1=v1; k2=v2`) hoặc JSON object/array, nút **Import Cookies** (xóa cookie cũ của `https://muse.ai` nếu cần hoặc ghi đè bằng `chrome.cookies.set`, xử lý chuẩn cookie `__Host-`), hiển thị trạng thái và hỗ trợ reload tab `muse.ai` đang mở (nếu có quyền `tabs` hoặc chỉ reload khi người dùng mở).
   - Cập nhật `manifest.json` (tên `muse2apiv2 Cookie Manager`, version `1.1.0`).
4. **Kiểm thử:**
   - `npm run build` (`tsc -b && vite build`) pass.
   - `TestClient` kiểm tra `GET /admin/accounts/{id}/cookies` trả đúng `cookie_header` và `GET /admin/extension/download` trả zip mới nhất.
