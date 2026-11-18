# Request changes: Accounts & Keep-Alive

## 2026-11-18 — Import Cookie vào Extension & Copy Cookie từ Account

- **Yêu cầu:** Thêm chức năng import cookie vào Chrome Extension (`extension/`) và thêm nút Copy Cookie trên từng tài khoản ở màn Accounts để dán vào extension.
- **Phân loại:** Feature mở rộng
- **Đặc tả thay đổi:**
  - `spec.md`: cập nhật `FR-009`, bổ sung `FR-012`, `AC-012`.
  - `design.md`: thêm nút `Copy Cookie` vào bảng Accounts.
  - `01_api_overview.md`: bổ sung `GET /admin/accounts/{id}/cookies`.
- **Task:** [T-011](../../04_tasks/011_extension_import_and_copy_cookie/plan.md)

## 2026-11-17 — Edit Account Modal, Unified Refresh, Proxy Display & WSS Tunnel Daemon

- **Yêu cầu:** Thêm nút Edit Account (mở modal chỉnh sửa), cột Proxy bỏ `<select>` và hiển thị `No proxy` hoặc `proxy_ip`, bỏ nút `Quota` và `Test WSS` riêng lẻ, nút `Refresh` kiểm tra đồng bộ trạng thái + WSS + quota, và WSS Tunnel tự chạy ngầm ở backend để cập nhật trạng thái lên frontend.
- **Phân loại:** Feature mở rộng / UI + Background Service
- **Đặc tả thay đổi:**
  - `spec.md`: cập nhật `FR-005`, bổ sung `FR-010`, `FR-011`, `AC-010`, `AC-011`.
  - `design.md`: cập nhật cột Proxy và Action buttons trên bảng Accounts, thêm wireframe Modal Edit Account.
  - `01_api_overview.md`: bổ sung `POST /admin/accounts/{id}/refresh`, `POST /admin/accounts/refresh`.
- **Task:** [T-009](../../04_tasks/009_account_edit_refresh_wss_daemon/plan.md)

## 2026-11-17 — Tự động skip account khi hết quota

- **Yêu cầu:** Khi request đến (`/v1/*`), không chọn account đã hết quota.
- **Phân loại:** Feature mở rộng / Pool Routing
- **Đặc tả thay đổi:**
  - `spec.md`: bổ sung `BR-004` và `AC-009`.
- **Quyết định:** Chỉ coi là hết quota khi `weekly_pct >= 100` và không còn token bổ sung (`extra_pct is None` hoặc `extra_pct >= 100`). Nếu chưa kiểm tra quota (`quota_json` rỗng) vẫn cho phép chọn.
- **Task:** [T-008](../../04_tasks/008_git_docker_quota_skip/plan.md)

## 2026-11-17 — Gắn Proxy theo danh sách, đồng bộ status Keep-Alive & tải Extension

- **Yêu cầu:** Bỏ nhập raw proxy trên Account (chọn từ danh sách Proxies), đảm bảo Keep-Alive nền cập nhật `status` tài khoản (`healthy`/`expired`/`cooldown`), thêm thư mục `extension/` copy cookie `muse.ai` và nút tải `.zip` trên UI.
- **Phân loại:** Feature mở rộng
- **Đặc tả thay đổi:**
  - `spec.md`: cập nhật `FR-005`, `FR-006`, bổ sung `FR-009`, `AC-007`..`AC-008`.
  - `design.md`: đổi ô nhập raw proxy thành dropdown chọn Proxy, thêm nút `Download Extension`.
- **Quyết định:** Bỏ qua migrate `proxy_url` cũ do chưa có tài khoản nào gắn proxy; extension dùng Manifest V3 tập trung đọc & copy cookie `muse.ai`.
- **Task:** [T-007](../../04_tasks/007_proxies_extension_task_cleanup/plan.md)

## 2026-11-17 — Quota thực tế, Auto-polling 5 phút, Progress Bars & Export Accounts

- **Yêu cầu:** Hiển thị quota thực tế dạng thanh progress pill, tự động polling quota mỗi 5 phút + nút Refresh All, custom Toast, nút loading không vỡ UI và Export Accounts.
- **Phân loại:** Feature mở rộng
- **Đặc tả thay đổi:**
  - `spec.md`: cập nhật `FR-004`, bổ sung `FR-007`..`FR-008`, `AC-005`..`AC-006`.
  - `01_api_overview.md`: bổ sung `POST /admin/accounts/quota`, `GET /admin/accounts/export`.
- **Quyết định:** Lấy quota qua HTTP `Next-Action` Server Action (`POST https://muse.ai/thread/new`) thay cho mở Chromium; xuất raw cookies/proxy trong file JSON để phục vụ backup/re-import.
- **Task:** đã triển khai trực tiếp
