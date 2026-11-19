# Feature Spec: Accounts & Keep-Alive

- **Trạng thái:** `Ready for Implementation`
- **Liên quan:** [System Architecture](../../02_basic_design/00_system_architecture.md), [ERD](../../02_basic_design/02_database/erd.md)

## 1. Mục tiêu & Bối cảnh
Quản lý vòng đời tài khoản `muse.ai` không cần trình duyệt: import từ cookie, theo dõi trạng thái/quota, bật/tắt tham gia pool, gắn proxy riêng và duy trì phiên sống tự động qua Keep-Alive.

## 2. Phạm vi
- **In Scope:** Import cookie (header string hoặc JSON), chỉnh sửa label/proxy/enabled/model hỗ trợ (`chat`, `image`, `video`, `speech`), test kết nối WSS (`Noise_XX` + `GET /health`), kiểm tra quota, chạy Keep-Alive nền (20 phút/lần) và thủ công.
- **Out of Scope:** Đăng nhập bằng email/password hoặc giải OTP/CAPTCHA tự động.

## 3. Yêu cầu chức năng (`FR`)
- **FR-001 (Import Cookie):** Cho phép nhập `label`, chuỗi `Cookie:` header hoặc JSON array/dict, `proxy_id` (tùy chọn) và `supported_models` (tùy chọn, mặc định đủ 4 loại `["chat", "image", "video", "speech"]`). Hệ thống parse cookie, xác nhận có ít nhất cookie phiên (`hatch_sess` hoặc `hatch_vml`), lưu vào bảng `accounts`.
- **FR-002 (Bật/Tắt & Xóa tài khoản):** Admin có thể toggle `enabled` hoặc xóa tài khoản khỏi pool; tài khoản `enabled=false` bị loại khỏi điều phối `/v1/*` và đóng kết nối WSS đang giữ.
- **FR-003 (Test WSS Connection):** Nút **Test WSS** thực hiện HTTP Bootstrap (`GET /thread/new`) + `Noise_XX` handshake + `GET /health`, cập nhật `status = healthy` nếu `200 OK` hoặc `expired`/`error` kèm thông báo lỗi.
- **FR-004 (Quota Check):** Gọi Next.js Server Action (`POST https://muse.ai/thread/new` với `next-action` và `[{"includeAgreement":true}]`) để lấy thông số quota thực tế (`plan`, `weekly_pct`, `weekly_reset`, `extra_pct`, `extra_remaining`) lưu vào `quota_json` và hiển thị bằng 2 thanh progress pill (% còn lại).
- **FR-005 (Gắn Proxy từ danh sách Proxies & hiển thị cột Proxy):** Cho phép chọn `proxy_id` từ danh sách proxy đã lưu ở [Proxy Management](../05_proxy_management/spec.md) (hoặc để trống `No proxy`) khi import hoặc edit tài khoản; **không cho nhập raw proxy URL hoặc chọn `<select>` trực tiếp trên bảng Account**. Cột `Proxy` trên bảng hiển thị `No proxy` khi chưa gắn, hoặc hiển thị `proxy_ip` (nếu đã check IP) / `proxy_masked` khi đã gắn.
- **FR-006 (Keep-Alive chạy ngầm & cập nhật Status):** Scheduler chạy nền định kỳ mỗi `20 phút` cho các tài khoản `enabled=true`, gọi `GET /api/session` và `POST /api/hatch/vm/wake` (nếu VM ngủ), tự động cập nhật `status` (`healthy`, `expired`, hoặc `cooldown` khi lỗi mạng/proxy), `last_keepalive_at`, `last_error`, và ghi kết quả vào `keepalive_logs`. Hỗ trợ kích hoạt thủ công cho 1 tài khoản hoặc toàn bộ pool.
- **FR-007 (Auto-Polling Quota & Refresh All):** Frontend tự động polling `POST /admin/accounts/quota` mỗi `5 phút` và cung cấp nút **Refresh All** ở cả Overview và Accounts (mọi nút gọi API đều hiển thị spinner loading mà không làm thay đổi kích thước nút, thông báo qua custom Toast).
- **FR-008 (Export Accounts):** Cho phép xuất danh sách tài khoản (`cookies`, `cookie_header`, `proxy_id`, `proxy_url`, `enabled`, `supported_models`, `status`, `quota`) thành tệp `muse2apiv2-accounts.json` qua `GET /admin/accounts/export`.
- **FR-009 (Chrome Extension Copy & Import Cookie):** Dự án cung cấp thư mục `extension/` (Manifest V3) với 2 chức năng:
  1. **Copy Cookie:** Đọc toàn bộ cookie của `muse.ai` (kể cả `HttpOnly`) và copy thành chuỗi `Cookie:` header.
  2. **Import Cookie:** Cho phép dán chuỗi `Cookie:` header hoặc JSON (`{name: value}` / array) để ghi đè/nạp cookie vào trình duyệt cho `https://muse.ai` (xử lý chuẩn cả cookie `__Host-` và cookie thường), tùy chọn tải lại tab `muse.ai` đang mở.
  Trên giao diện Accounts có nút **Download Extension** tải về gói `.zip` qua `GET /admin/extension/download`.
- **FR-012 (Copy Cookie từ Account):** Mỗi dòng tài khoản trên Console có nút **Copy Cookie** gọi `GET /admin/accounts/{id}/cookies` để lấy chuỗi `cookie_header` của tài khoản đó và copy vào clipboard (hiển thị Toast xác nhận), phục vụ dán nhanh vào Extension.
- **FR-010 (Edit Account & Modal Edit):** Mỗi dòng tài khoản có nút **Edit** mở modal chỉnh sửa (`label`, `cookies_raw` tùy chọn — để trống giữ nguyên cookie cũ, `proxy_id` chọn từ danh sách Proxies hoặc `No proxy`, danh sách `supported_models`, và trạng thái `enabled`), lưu qua `PATCH /admin/accounts/{id}`.
- **FR-011 (Unified Refresh & Background WSS Tunnel Daemon):**
  - Bỏ nút **Quota** và nút **Test WSS** riêng lẻ trên từng dòng Account; thay bằng nút **Refresh** (`POST /admin/accounts/{id}/refresh`) thực hiện đồng bộ cả 3 bước: (1) kiểm tra trạng thái/session Keep-Alive, (2) kiểm tra & kết nối WSS Tunnel, (3) kiểm tra Quota; cập nhật `status`, `wss_connected`, `quota`, `last_keepalive_at`.
  - **WSS Tunnel chạy ngầm:** Backend duy trì vòng lặp nền tự động kết nối/giữ sống WSS Tunnel cho các tài khoản `enabled=true` (không `expired`, chưa hết quota), tự cập nhật `wss_connected` và `status` vào DB/pool để frontend hiển thị theo thời gian thực.
- **FR-013 (Cấu hình Model hỗ trợ trên từng tài khoản):**
  - Mỗi tài khoản lưu danh sách loại model hỗ trợ (`supported_models`) gồm tập con không rỗng của 4 loại: `"chat"`, `"image"`, `"video"`, `"speech"`.
  - Hỗ trợ truyền `supported_models` khi tạo mới (`POST /admin/accounts`, mặc định bật đủ cả 4 loại nếu không truyền) và cập nhật (`PATCH /admin/accounts/{id}`), trả về trong payload của `GET /admin/accounts`, `GET /admin/dashboard` và `GET /admin/accounts/export`.
  - Trên Console, modal **Import Account** và modal **Edit Account** cung cấp 4 toggle pill (`Chat`, `Image`, `Video`, `Speech`); bảng **Accounts** hiển thị các badge model đang bật ở dạng chỉ xem (chỉnh sửa thông qua modal **Edit**). Bảng tài khoản trên trang **Overview** giữ nguyên, không thêm cột mới.

## 4. Quy tắc nghiệp vụ (`BR`)
- **BR-001:** Cookie và mật khẩu proxy không bao giờ được trả nguyên văn qua `GET /admin/accounts` hay ghi vào log; luôn mask khi hiển thị.
- **BR-002:** Tài khoản có `status` là `expired` hoặc `disabled` không được chọn trong LRU pool; tài khoản `cooldown` được bỏ qua cho đến khi hết thời gian cooldown.
- **BR-003:** Kết nối Keep-Alive thất bại với HTTP `401` phải chuyển `status` tài khoản sang `expired` ngay lập tức.
- **BR-004 (Auto-Skip Exhausted Quota):** Khi chọn tài khoản trong pool (`_candidate_accounts`), hệ thống phải tự động bỏ qua các tài khoản đã hết quota:
  - Tài khoản bị coi là hết quota khi `weekly_pct >= 100` **và** (`extra_pct` không có hoặc `extra_pct >= 100`).
  - Nếu `weekly_pct >= 100` nhưng `extra_pct < 100` (còn token bổ sung) hoặc tài khoản chưa có dữ liệu `quota_json` thì vẫn được chọn.
  - Nếu trong quá trình gọi WSS gặp lỗi hết quota từ upstream, hệ thống cập nhật `quota_json` (`weekly_pct: 100`) và failover sang tài khoản kế tiếp. Nếu toàn bộ tài khoản đều hết quota, trả lỗi rõ ràng (`503`).
- **BR-005 (Ràng buộc giá trị & điều phối theo `supported_models`):**
  - Giá trị hợp lệ duy nhất thuộc tập `{"chat", "image", "video", "speech"}` (chuẩn hóa chữ thường, loại bỏ phần tử trùng lặp và sắp xếp theo thứ tự cố định `["chat", "image", "video", "speech"]`).
  - Mỗi tài khoản **bắt buộc bật ít nhất 1 loại model**; nếu `supported_models` rỗng (`[]`) hoặc chứa giá trị ngoài tập hợp lệ, API trả `400 Bad Request` và giao diện chặn lưu kèm thông báo nhắc chọn tối thiểu 1 loại.
  - Các tài khoản đã tồn tại trước khi nâng cấp DB (hoặc khi cột `supported_models_json` rỗng/NULL) mặc định được coi là hỗ trợ đủ cả 4 loại `["chat", "image", "video", "speech"]`.
  - Việc chỉ cập nhật `supported_models` trên `PATCH /admin/accounts/{id}` không đóng kết nối WSS đang mở và không ảnh hưởng tới lịch Keep-Alive; tài khoản chỉ bị loại khỏi danh sách ứng viên (`_candidate_accounts(capability)`) của những loại request không có trong `supported_models` (chi tiết định tuyến xem [OpenAI API Spec](../02_openai_api_and_keys/spec.md), `BR-111`).

## 5. Tiêu chí nghiệm thu (`AC`)
- **AC-001:** Import cookie hợp lệ (như chuỗi từ `tmp/account1.txt`) lưu thành công vào SQLite và hiển thị cookie đã mask trên bảng Accounts.
- **AC-002:** Bấm **Test WSS** trên tài khoản hợp lệ hoàn tất handshake `Noise_XX` và trả về `healthy` trong `< 10s`.
- **AC-003:** Tắt `enabled` trên tài khoản đang mở WSS sẽ đóng socket của tài khoản đó và không nhận thêm request từ `/v1/*`.
- **AC-004:** Chạy **Keep-Alive All** cập nhật `last_keepalive_at` và ghi bản ghi mới vào `keepalive_logs`.
- **AC-005:** Bấm **Refresh All** cập nhật quota thực tế cho toàn bộ tài khoản đang bật, hiển thị thanh progress pill và thông báo Toast thành công.
- **AC-006:** Bấm **Export** tải về tệp `muse2apiv2-accounts.json` hợp lệ chứa đầy đủ cookies, `supported_models` và cấu hình proxy.
- **AC-007:** Bấm **Download Extension** tải về tệp `.zip` chứa `manifest.json` và mã nguồn extension copy cookie `muse.ai`.
- **AC-008:** Khi Keep-Alive nền gặp lỗi `401` hoặc lỗi mạng, `status` của tài khoản trong bảng `accounts` tự động chuyển sang `expired` hoặc `cooldown`.
- **AC-009:** Tài khoản có `weekly_pct = 100` (và không còn `extra_pct < 100`) tự động bị bỏ qua khi điều phối request `/v1/*`; nếu còn token bổ sung (`extra_pct < 100`) vẫn được chọn bình thường.
- **AC-010:** Bấm **Edit** trên 1 tài khoản mở modal cho phép đổi `label`, `proxy_id`, `supported_models` hoặc cập nhật cookie mới; cột `Proxy` hiển thị `No proxy` hoặc `proxy_ip` / `proxy_masked` dạng text tĩnh (không có `<select>`).
- **AC-011:** Bấm **Refresh** trên 1 tài khoản kiểm tra đồng thời trạng thái session, kết nối WSS và quota; đồng thời WSS Tunnel nền tự động kết nối cho tài khoản đang bật và cập nhật trạng thái `Connected` lên giao diện.
- **AC-012:** Bấm **Copy Cookie** trên 1 tài khoản sao chép đúng chuỗi `cookie_header` vào clipboard; dán chuỗi đó vào ô **Import Cookies** trong Chrome Extension và bấm Import sẽ nạp đầy đủ cookie cho `https://muse.ai`.
- **AC-013:** Tài khoản cũ sau khi migrate DB và tài khoản mới tạo không truyền `supported_models` đều có `supported_models = ["chat", "image", "video", "speech"]`. Gửi `POST /admin/accounts` hoặc `PATCH /admin/accounts/{id}` với `supported_models: []` hoặc giá trị lạ (vd `["audio"]`) trả `400 Bad Request`; gửi `["chat", "image", "speech"]` lưu đúng vào SQLite và trả đúng qua `GET /admin/accounts` & `GET /admin/accounts/export`.
- **AC-014:** Trên giao diện **Accounts**, modal **Import Account** mặc định chọn đủ 4 pill (`Chat`, `Image`, `Video`, `Speech`), modal **Edit Account** cho phép bật/tắt từng loại và không cho lưu khi bỏ chọn cả 4; bảng Accounts hiển thị đúng các badge model đang bật của từng tài khoản ở dạng chỉ xem.
