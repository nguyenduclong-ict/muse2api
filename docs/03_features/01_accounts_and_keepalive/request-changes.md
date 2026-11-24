# Request changes: Accounts & Keep-Alive

## 2026-11-24 — Nâng cấp Chrome Extension sang Import/Export Cookie cho mọi site (v2.0.0)

- **Yêu cầu:** Nâng cấp Chrome Extension (`extension/`) từ chỉ hỗ trợ `muse.ai` sang hỗ trợ Import, Export Cookie và Clear Site Data cho mọi website.
- **Phân loại:** Feature mở rộng
- **Đặc tả thay đổi:**
  - `extension/manifest.json`: nâng phiên bản lên `2.0.0`, bổ sung quyền `tabs` và `host_permissions` cho `http://*/*`, `https://*/*`.
  - `extension/cookie-utils.js`: tách module thuần xử lý domain/URL, formatters (`Header`, `JSON`, `Netscape`), auto-detect parser và `buildCookieSetDetails` (hỗ trợ `__Host-`, `__Secure-`, `sameSite`, `partitionKey`, `localhost`/IP, multi-domain).
  - `extension/popup.html`, `extension/popup.js`: thêm Target Site selector (tự nhận diện active tab hoặc nhập tay), checkbox `Include subdomains`, segmented export format (`Header` / `JSON` / `Netscape`), nút `Download`, nút `Load File` + nhận diện định dạng trực tiếp khi import, và `Clear Site Data` theo site đang chọn.
  - `spec.md` (`FR-009`), `README.md`: cập nhật tài liệu hướng dẫn và đặc tả v2.0.
- **Quyết định:** Giữ mặc định định dạng Export là `Header` và tương thích 1-click với `muse.ai` để không làm thay đổi quy trình nạp tài khoản trên Console; giữ nguyên toàn bộ tệp cần đóng gói trong `extension/` (không đặt file test vào `extension/` để `GET /admin/extension/download` luôn sạch).

## 2026-11-22 — Reset Muse thủ công & Auto-Reset định kỳ theo tài khoản

- **Yêu cầu:** Bổ sung tính năng Reset Muse thủ công cho từng tài khoản (tương đương luồng _Cài đặt → Kiểm soát dữ liệu → Đặt lại Muse_ trên `muse.ai`) và tính năng Auto-Reset định kỳ theo khoảng thời gian lặp lại kèm cờ `auto_reset` riêng cho từng tài khoản và cơ chế đếm request phát sinh.
- **Phân loại:** Feature mở rộng
- **Đặc tả thay đổi:**
  - `spec.md`: cập nhật `Phạm vi`, `FR-001`, `FR-008`, `FR-010`; bổ sung `FR-014`, `FR-015`, `BR-006`, `BR-007`, `BR-008`, `AC-015`..`AC-019`.
  - `design.md`: bổ sung nút `[Reset]`, tag `((Auto))`, badge `((resetting)){info}` trên bảng Accounts, công tắc `Auto Reset` trong modal Import/Edit (kèm thông tin `Last Reset` & `Requests since reset` trong Edit) và modal xác nhận `Reset Muse`.
  - `logic.md`: bổ sung Sequence Diagram cho Manual Reset & Auto-Reset, cập nhật bảng `UI Event Handlers`, thêm mục thuật toán Reset Muse (`POST /api/hatch/replace-vm`), drain `in_flight`, đếm `requests_since_reset`, scheduler tuần tự `ResetService`, backoff 15 phút, `reset_logs` (30 dòng/tài khoản) và crash recovery.
  - `../../02_basic_design/01_api_overview.md`: bổ sung `POST /admin/accounts/{id}/reset`, `POST /admin/accounts/reset-due`, `GET /admin/accounts/reset-logs`.
  - `../../02_basic_design/02_database/erd.md`, `../../02_basic_design/02_database/schema_summary.md`: bổ sung 5 cột reset trên `accounts` và bảng mới `reset_logs`.
- **Quyết định:** Sử dụng giao thức `POST /api/hatch/replace-vm` (đã kiểm chứng thực nghiệm trên tài khoản `hatch_vm`, bỏ qua bước nhập tên tác nhân phía client vì không gửi lên server); không hỗ trợ `hatch_cvm` (yêu cầu PIN/recovery key); API thủ công trả `202 Accepted` chạy nền với `status = "resetting"`; auto-reset chạy tuần tự từng tài khoản theo `interval_minutes`, hoãn khi tài khoản bận (`in_flight > 0`), khi chưa phát sinh request (`requests_since_reset == 0`), hoặc khi pool chỉ còn `<= 1` tài khoản `healthy`; tách bảng `reset_logs` riêng để không bị `keepalive_logs` (giới hạn 20 dòng) đẩy trôi.
- **Task:** [T-019](../../04_tasks/019_muse_reset_and_auto_reset/plan.md)

## 2026-11-19 — Cấu hình loại model hỗ trợ (`chat`, `image`, `video`, `speech`) trên từng tài khoản

- **Yêu cầu:** Thêm cài đặt chọn các loại model hỗ trợ (`chat`, `image`, `video`, `speech`) trên từng tài khoản; tài khoản tắt loại model nào thì không được chọn cho các request thuộc loại đó.
- **Phân loại:** Feature mở rộng
- **Đặc tả thay đổi:**
  - `spec.md`: cập nhật `FR-001`, `FR-008`, `FR-010`; bổ sung `FR-013`, `BR-005`, `AC-013`, `AC-014`.
  - `design.md`: bổ sung cột `Models` (badge chỉ xem) trên bảng Accounts và nhóm toggle `Supported Models` (`Chat`, `Image`, `Video`, `Speech`) trong modal Import Account & Edit Account.
  - `logic.md`: cập nhật bảng `UI Event Handlers`, bổ sung thuật toán migrate cột `supported_models_json` và validate `supported_models`.
  - `../../02_basic_design/02_database/erd.md`, `../../02_basic_design/02_database/schema_summary.md`: bổ sung cột `supported_models_json` cho bảng `accounts`.
- **Quyết định:** Mặc định bật đủ cả 4 loại (`["chat", "image", "video", "speech"]`) cho cả tài khoản cũ khi migrate và tài khoản mới import; bắt buộc chọn tối thiểu 1 loại khi lưu (loại bỏ phương án cho phép danh sách rỗng vì đã có nút `Enabled` để tạm dừng toàn bộ tài khoản); trên bảng Accounts chỉ hiển thị badge dạng xem, chỉnh sửa qua modal Edit/Import; đưa `supported_models` vào Export JSON và giữ nguyên bảng Overview.
- **Task:** [T-014](../../04_tasks/014_account_supported_models/plan.md)

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
