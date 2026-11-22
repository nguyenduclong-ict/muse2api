# Nghiên cứu kỹ thuật: Tính năng Reset Muse thủ công & Auto-Reset định kỳ theo tài khoản

- **Ngày thực hiện:** 2026-11-22
- **Phạm vi:**
  1. Truy vết giao thức **Reset Muse** thực tế từ sản phẩm `muse.ai` (tương đương luồng UI: _Cài đặt → Kiểm soát dữ liệu → Đặt lại Muse → Nhập tên tác nhân → Đặt lại → Chờ hoàn tất_).
  2. Khảo sát kiến trúc codebase `muse2apiv2` để thiết kế tích hợp **Reset Muse thủ công** và **Auto-Reset định kỳ** (có cờ `auto_reset` riêng cho từng tài khoản).
- **Trạng thái:** Chỉ nghiên cứu & tổng hợp nguồn sơ cấp; chưa chỉnh sửa mã nguồn ứng dụng.

---

## 1. Tóm tắt điều hành (Executive Summary)

1. **Bước "Nhập tên tác nhân" trên UI `muse.ai` chỉ là kiểm tra cục bộ ở client:**
   - Trong component `HatchResetProjectDialog` (module `923993`, chunk `/_next/static/immutable/chunks/0nd-8c2w_rpz_.js`), chuỗi người dùng nhập (`q.trim()`) chỉ được so sánh trực tiếp trên trình duyệt với tên tác nhân (`eg`) hoặc chữ `"Reset"`. Giá trị này **không được gửi** trong bất kỳ HTTP request nào lên `muse.ai`. Do đó backend `muse2apiv2` không cần thu thập hay truyền tên tác nhân.
2. **Luồng mạng thật sự của `Cài đặt → Kiểm soát dữ liệu → Đặt lại Muse` là `POST /api/hatch/replace-vm` (Luồng A):**
   - Khảo sát hàm `dT()` trong chunk `/_next/static/immutable/chunks/2d9hjbgne_w55.js` (`surface: "settings"`, `subsurface: "data_privacy"`) và máy trạng thái `HatchVmReplacementFlow` (`tS`) trong chunk `/_next/static/immutable/chunks/09_mnao0dznvr.js`: khi xác nhận reset, `muse.ai` **không** gọi `/api/hatch/reset-vm` mà khởi chạy flow `replace_vm` với `intent: "reset"` qua **`POST /api/hatch/replace-vm`**, đọc lại inventory qua `GET /api/session?vm_state=live`, và lưu lựa chọn VM mới qua Next.js Server Action `updateUserPreferencesAction`.
   - Bên cạnh đó vẫn tồn tại **Luồng B** (`POST /api/hatch/reset-vm` + `POST /api/hatch/lease-vm`) dùng cho các ngữ cảnh khôi phục VM lỗi / PIN recovery.
3. **Tích hợp vào `muse2apiv2` đòi hỏi kiểm soát đồng thời chặt chẽ với `WSSPool` và `KeepAliveService`:**
   - Hiện tại `WSSPool._get_acc_lock(aid)` (`packages/backend/services/wss_pool.py:90-94`) chỉ được giữ khi tạo kết nối `get_client()` và `/health`, **không** giữ trong suốt thời gian chạy RPC (`execute_chat`, `stream_chat_events`, `generate_media`). Gọi `close_account(aid)` khi còn request đang chạy sẽ đẩy `None` vào mọi stream queue (`muse_wss.py:522-524`), làm hỏng các request đang xử lý.
   - `WSSPool.maintain_tunnels()` (`wss_pool.py:235-241`) và `KeepAliveService.run_due()` (`keepalive.py:55-63`) hiện chỉ kiểm tra `enabled` / `expired` / quota, chưa có cơ chế bỏ qua tài khoản đang trong quá trình reset (`status = "resetting"`).
   - `keepalive_logs` (`db.py:805-824`) tự cắt còn 20 bản ghi gần nhất mỗi tài khoản; không nên dùng chung cho lịch sử reset vì keepalive chạy 20 phút/lần sẽ đẩy trôi toàn bộ log reset trong vòng dưới 7 giờ.

---

## 2. Phần 1 — Giao thức Reset Muse từ nguồn sơ cấp (`muse.ai`)

### 2.1. Danh sách nguồn sơ cấp đã kiểm chứng

| Nguồn sơ cấp                                                                                               | Nội dung kiểm chứng                                                                                                                                                                                              |
| ---------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET https://muse.ai/api/session` & `GET https://muse.ai/api/session?vm_state=live`                        | Gọi trực tiếp bằng cookie tài khoản `hatch_vm` đang `healthy` trong `data/muse2apiv2.db`; xác nhận cấu trúc `status`, `vm_id`, `vm_name`, `vm_type`, `endpoint_url`, `vm_selection`, `cvm_eligibility`, `vms[]`. |
| `GET https://muse.ai/settings`                                                                             | Xác nhận RSC payload chứa `ownerId` và `sessionBindingId`.                                                                                                                                                       |
| `/_next/static/immutable/chunks/2d9hjbgne_w55.js`                                                          | Hàm `dT()` cài đặt nút **Reset {agentName}** trong _Settings → Data controls_ (`surface: "settings"`, `subsurface: "data_privacy"`).                                                                             |
| `/_next/static/immutable/chunks/0nd-8c2w_rpz_.js` (module `923993`)                                        | `HatchResetProjectDialog`: logic xác nhận tên tác nhân phía client và nhánh gọi `onConfirmedReplacement()` vs `POST /api/hatch/reset-vm`.                                                                        |
| `/_next/static/immutable/chunks/09_mnao0dznvr.js`                                                          | `HatchVmReplacementFlow`: class `tS`, `tk("/api/hatch/replace-vm")`, `th("/api/session?vm_state=live")`, chuỗi lỗi `tI`, và quy trình cập nhật `vm_selection`.                                                   |
| `/_next/static/immutable/chunks/3y56fmbu-gpcx.js` (module `470006`) & `0ctn6hbmesxn2.js` (module `758532`) | Server Action `updateUserPreferencesAction` với Next-Action ID `40076d65709b71539d10a9f0f52656ee03877e4d17`.                                                                                                     |
| `/_next/static/immutable/chunks/09eq254gikpwu.js` (module `76924`)                                         | Helper chuẩn hóa `fqdn` / `hostname` từ `gatewayUrl`.                                                                                                                                                            |
| `/_next/static/immutable/chunks/2b63f1fpudzqm.js` (module `506171`)                                        | Helper `POST /api/hatch/lease-vm` với payload `{"vmType": e}`.                                                                                                                                                   |
| `packages/backend/muse_wss.py:398-466`                                                                     | Luồng `_bootstrap()` từ `GET /thread/new` lấy `__HATCH_GATEWAY_INIT__` (`vmName`, `authToken`, `noiseNotaryToken`) và `Noise_XX` WSS handshake.                                                                  |

### 2.2. Vai trò của bước "Nhập tên tác nhân"

Trong module `923993` (`0nd-8c2w_rpz_.js`), `HatchResetProjectDialog` kiểm tra điều kiện kích hoạt nút xác nhận (`eb`) như sau:

- Khi dùng trong màn _Settings → Data controls_ (`es === false`, `ea === false`):
  - Nếu có tên tác nhân (`U.length > 0`), `eg = U`; ngược lại `eg = "Reset"`.
  - Điều kiện hợp lệ là `q.trim() === eg`.
- Khi bấm nút xác nhận (`eb && !$`), dialog đóng lại và gọi `eR()`.
- Trong `eR()`, **nếu prop `onConfirmedReplacement` (`V`) được truyền vào** (chính là trường hợp của `dT()` trong Settings):
  - `eR()` gọi `V()`, nếu trả về `true` thì đóng dialog và kết thúc — **không hề gọi `/api/hatch/reset-vm`**.
  - `V()` gọi `(0, dS.j)(e.flow)` với `flow.kind = "replace_vm"`, `flow.intent = "reset"`, rồi đóng kết nối hiện tại (`l?.close()`).

**Kết luận:** Tên tác nhân chỉ là lớp xác nhận giao diện trên trình duyệt, không có tham số nào liên quan đến tên tác nhân trong giao thức mạng.

### 2.3. Luồng A — Luồng chính của `Cài đặt → Kiểm soát dữ liệu → Đặt lại Muse`

#### Bước 1: Đọc thông tin VM hiện tại (`GET /api/session?vm_state=live`)

- **Headers:** `Cookie`, `User-Agent`, `Accept: application/json`.
- **Dữ liệu trả về thực tế (đã kiểm chứng trên tài khoản `hatch_vm`):**
  ```json
  {
    "status": "assigned",
    "cvm_eligibility": {
      "observedAtMs": 1795331281054,
      "state": "NOT_ELIGIBLE",
      "defaultVm": {
        "vmId": "34d93898-68dc-49bb-8e4d-6a51585fc454",
        "vmName": "34d93898-68dc-49bb-8e4d-6a51585fc454",
        "vmType": "hatch_vm"
      }
    },
    "vm_selection": {
      "revision": 6,
      "override": {
        "gatewayUrl": "wss://34d93898-68dc-49bb-8e4d-6a51585fc454.metaaivm.com/",
        "vmName": "34d93898-68dc-49bb-8e4d-6a51585fc454"
      },
      "selectedMigrationSource": null
    },
    "vm_id": "34d93898-68dc-49bb-8e4d-6a51585fc454",
    "endpoint_url": "wss://34d93898-68dc-49bb-8e4d-6a51585fc454.metaaivm.com/",
    "vm_name": "34d93898-68dc-49bb-8e4d-6a51585fc454",
    "vm_state": "UNKNOWN",
    "vm_type": "hatch_vm",
    "vms": [
      {
        "id": "34d93898-68dc-49bb-8e4d-6a51585fc454",
        "vm_id": "34d93898-68dc-49bb-8e4d-6a51585fc454",
        "name": "34d93898-68dc-49bb-8e4d-6a51585fc454",
        "endpoint_url": "wss://34d93898-68dc-49bb-8e4d-6a51585fc454.metaaivm.com/",
        "is_preferred": true,
        "vm_type": "hatch_vm",
        "vm_state": "UNKNOWN",
        "vm_state_source": "live"
      }
    ]
  }
  ```
- Từ payload này lấy: `sourceEnvId = vm_id` (UUID 36 ký tự), `vm_type` (`"hatch_vm"` hoặc `"hatch_cvm"`), và `selectionRevision = vm_selection.revision`.
- **Ràng buộc an toàn:** Nếu `vm_type == "hatch_cvm"` (Confidential VM), luồng frontend yêu cầu PIN và WebCrypto recovery key (`initializeReplacementCvm`). Backend `muse2apiv2` hiện không quản lý CVM PIN nên cần kiểm tra `vm_type == "hatch_vm"` và từ chối rõ ràng nếu gặp `hatch_cvm`.

#### Bước 2: Gọi `POST https://muse.ai/api/hatch/replace-vm`

- **Headers:**
  - `Cookie: <cookie_header>`
  - `User-Agent: <USER_AGENT>`
  - `Content-Type: application/json`
  - `Origin: https://muse.ai`
  - `Referer: https://muse.ai/settings`
  - `sec-fetch-site: same-origin`
  - `sec-fetch-mode: cors`
  - `sec-fetch-dest: empty`
- **Request Body (`09_mnao0dznvr.js`, hàm `tk` & `tS.execute`):**
  ```json
  {
    "sourceEnvId": "<source_vm_uuid>",
    "destinationType": "standard",
    "intent": "reset"
  }
  ```
  _(Với tài khoản `hatch_vm`, `destinationType` là `"standard"`.)_
- **Response Schema (hàm `tb` trong `09_mnao0dznvr.js`):**
  - **Thành công (HTTP 200):**
    ```json
    {
      "ok": true,
      "vmId": "<new_vm_uuid>",
      "releasedOld": true
    }
    ```
  - **Thất bại (`ok: false`):**
    ```json
    {
      "ok": false,
      "code": "<error_code>",
      "replacementOutcome": "not_started | unknown",
      "upstreamStatus": 500,
      "backendErrorCode": "...",
      "retryAfterMs": 5000
    }
    ```
    Danh sách mã lỗi `tI` được client định nghĩa: `authentication_required`, `invalid_request`, `employee_required`, `cvm_disabled`, `cvm_gate_unavailable`, `subscription_required`, `subscription_unavailable`, `source_deletion_disabled`, `inventory_unavailable`, `source_missing`, `source_ambiguous`, `source_type_mismatch`, `inventory_type_unknown`, `destination_exists`, `request_aborted`, `upstream_rejected`, `invalid_upstream_response`, `transport_error`, `unavailable`.

#### Bước 3: Chờ VM mới xuất hiện trong inventory (`GET /api/session?vm_state=live`)

- Frontend đọc lại `GET /api/session?vm_state=live`, tìm bản ghi trong `vms[]` có `vm.id == new_vm_id` và `vm_type == "hatch_vm"` để lấy `gatewayUrl` mới (`endpoint_url`, dạng `wss://<new_vm_id>.metaaivm.com/`).

#### Bước 4: Cập nhật `vm_selection` (nếu cần) qua Server Action `updateUserPreferencesAction`

- Chunk `09_mnao0dznvr.js` gọi `updatePreferences(...)` (module `758532` → `470006`):
  - `POST https://muse.ai/settings` (hoặc `/thread/new`)
  - Header `next-action: 40076d65709b71539d10a9f0f52656ee03877e4d17`, `Accept: text/x-component`, `Content-Type: text/plain;charset=UTF-8`
  - Payload JSON array 1 phần tử:
    ```json
    [
      {
        "pawOverrides": "{\"gatewayUrl\":\"wss://<new_vm_id>.metaaivm.com/\",\"vmName\":\"<new_vm_id>\"}",
        "vmOverrideGatewayUrl": "wss://<new_vm_id>.metaaivm.com/",
        "vmOverrideVmName": "<new_vm_id>",
        "expectedVmSelectionRevision": 6,
        "expectedVmSelectionOwnerId": "<ownerId>"
      }
    ]
    ```
  - Lưu ý: `ownerId` có thể parse từ HTML của `GET /settings` (key `"ownerId":"..."` trong RSC payload, đã xác nhận xuất hiện ở `GET /settings`).
  - **Cần kiểm chứng thực nghiệm:** Hiện chưa rõ backend của `muse.ai` có tự chuyển `vm_selection` sang `new_vm_id` sau `replace-vm` hay bắt buộc phải gọi `updateUserPreferencesAction` (giống cách `fetch_quota_http` dùng `_QUOTA_NEXT_ACTION_ID` trong `muse_wss.py:312`). Nếu bắt buộc gọi, cần lưu ý hash `next-action` có thể thay đổi khi `muse.ai` deploy bản mới.

#### Bước 5: Đánh thức & xác nhận VM mới sẵn sàng

- Gọi `wake_vm_http(cookies, new_vm_id, ...)` (`POST /api/hatch/vm/wake`, `muse_wss.py:248-282`) nếu `vm_state` chưa `RUNNING`.
- Thực hiện bootstrap `GET /thread/new` + `Noise_XX` WSS handshake + `GET /health` == `200` (có retry backoff vì VM mới vừa tạo có thể trả `fail_ip_registry_not_found` trong vài chục giây đầu, `muse_wss.py:452-465`).

### 2.4. Luồng B — Luồng khôi phục / Legacy (`reset-vm` + `lease-vm`)

Trong các ngữ cảnh không truyền `onConfirmedReplacement` (như VM recovery / PIN recovery ở `0nd-8c2w_rpz_.js` và `2vpwjq4ppbnca.js`), frontend gọi:

1. `POST https://muse.ai/api/hatch/reset-vm` với body:
   ```json
   { "fqdn": "<vm_id>.metaaivm.com" }
   ```
   (hoặc thêm `"switchTo": "standard"` khi chuyển loại VM).
2. Sau đó xin cấp VM mới qua `POST https://muse.ai/api/hatch/lease-vm` (`2b63f1fpudzqm.js` module `506171`) với body:
   ```json
   { "vmType": "standard" }
   ```
   Response thành công: `{ "status": "assigned", "gatewayUrl": "...", "vmName": "...", "vmId": "..." }`.

### 2.5. So sánh Luồng A vs Luồng B

| Tiêu chí               | Luồng A (`POST /api/hatch/replace-vm`)                                                                 | Luồng B (`reset-vm` + `lease-vm`)                                                                          |
| ---------------------- | ------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| Khớp luồng UI Settings | **Khớp 100%** với `dT()` (_Settings → Data controls → Reset Muse_)                                     | Dùng cho recovery / PIN reset / reconnect                                                                  |
| Tính nguyên tử         | 1 call tạo VM mới + giải phóng VM cũ (`releasedOld`), trả lỗi cấu trúc chi tiết (`replacementOutcome`) | Tách 2 bước (`reset-vm` rồi `lease-vm`); dễ kẹt trạng thái không có VM nếu bước 2 lỗi                      |
| Rủi ro kỹ thuật        | Có bước lưu `updateUserPreferencesAction` dùng Next-Action hash có thể đổi theo bản build              | Nếu `lease-vm` lỗi hoặc không gọi `updateUserPreferencesAction`, tài khoản có thể rơi vào `status: "none"` |
| Hỗ trợ CVM             | Có kiểm tra `destinationType: "standard"` vs `"confidential"`                                          | Có tham số `switchTo` nhưng không rõ còn được duy trì cho UI Settings hay không                            |

**Khuyến nghị:** Ưu tiên **Luồng A** (`POST /api/hatch/replace-vm`), và **test thử nghiệm 1 lần trên 1 tài khoản phụ** trước khi implement chính thức để xác nhận:

1. Sau `replace-vm`, `GET /thread/new` có tự trả `vmName = new_vm_id` ngay không hay bắt buộc gọi `updateUserPreferencesAction`.
2. Thời gian thực tế từ lúc gọi `replace-vm` đến khi `GET /health` qua WSS trả về `200 OK`.

---

## 3. Phần 2 — Nghiên cứu tích hợp vào `muse2apiv2`

### 3.1. Database Schema & Migration (`packages/backend/db.py`)

- **Pattern hiện có:** `Database.init_schema()` (`db.py:476-597`) tạo bảng bằng `CREATE TABLE IF NOT EXISTS`, sau đó kiểm tra cột qua `PRAGMA table_info(accounts)` (`db.py:552-562`) và dùng `ALTER TABLE accounts ADD COLUMN ...` để migrate không mất dữ liệu (đã áp dụng cho `proxy_id` và `supported_models_json`).
- **Đề xuất mở rộng bảng `accounts` (`db.py:495-510`):**
  - `auto_reset INTEGER NOT NULL DEFAULT 0` (cờ bật/tắt auto-reset riêng cho từng tài khoản; mặc định `0` = tắt cho cả tài khoản cũ và tài khoản mới import để an toàn).
  - `last_reset_at REAL DEFAULT 0` (mốc timestamp lần reset gần nhất, dùng tính đến hạn cho Auto-Reset và hiển thị UI).
  - `last_reset_status TEXT DEFAULT ''` (`""` | `"ok"` | `"error"`).
  - `last_reset_error TEXT DEFAULT ''`.
- **Các điểm đồng bộ bắt buộc trong code khi thêm cột trên `accounts`:**
  - `create_account()` (`db.py:749-776`): thêm tham số `auto_reset: bool = False`.
  - `update_account()` (`db.py:778-795`): bổ sung `"auto_reset"`, `"last_reset_at"`, `"last_reset_status"`, `"last_reset_error"` vào tập `allowed`.
  - `_serialize_account()` (`routers/accounts.py:39-63`): trả về `auto_reset`, `last_reset_at`, `last_reset_status`, `last_reset_error`.
  - `GET /admin/accounts/export` (`routers/accounts.py:87-108`): xuất thêm `auto_reset`.
- **Lưu trữ lịch sử Reset — không dùng chung `keepalive_logs`:**
  - `add_keepalive_log()` (`db.py:805-824`) tự động xóa chỉ giữ **20 dòng mới nhất mỗi tài khoản**. Với tần suất keep-alive 20 phút/lần (72 dòng/ngày), log reset định kỳ mỗi ngày sẽ bị xóa sạch sau dưới 7 giờ.
  - Nên tạo bảng riêng `reset_logs` (cấu trúc tương tự `keepalive_logs`: `id`, `account_id`, `trigger_type` [`manual`/`auto`], `status` [`ok`/`error`], `old_vm_id`, `new_vm_id`, `message`, `duration_ms`, `created_at`) hoặc tối thiểu lưu metadata `last_reset_*` trên `accounts` kèm `reset_logs` giữ 20–50 bản ghi mỗi tài khoản.
- **Crash Recovery khi khởi động (`packages/backend/main.py`):**
  - Tương tự `db.fail_orphaned_tasks()` (`main.py:47`), nếu dùng `status = "resetting"` trong SQLite và server bị tắt/restart giữa chừng, tài khoản sẽ kẹt mãi ở `"resetting"` (và bị loại khỏi pool). Cần thêm `db.recover_resetting_accounts()` chạy trong `lifespan()` để chuyển các tài khoản `"resetting"` bị treo về `"unknown"` (hoặc `"cooldown"`).

### 3.2. Settings Persistence & API (`config.py`, `db.py`, `routers/admin_core.py`)

- **Pattern hiện có:**
  - `db.init_schema()` (`db.py:572-595`) seed mặc định các key JSON trong bảng `settings` (`"system_prompt"`, `"media_cleanup"`, `"voice_languages"`).
  - API sử dụng **`GET /admin/settings`** (`admin_core.py:204-212`) và **`POST /admin/settings`** (`admin_core.py:215-232`) — không dùng `PUT`. `SettingsPatchReq` (`admin_core.py:34-37`) cập nhật từng phần (chỉ update các trường khác `None`).
- **Đề xuất key mới `"auto_reset"` trong `settings`:**
  ```json
  {
    "enabled": false,
    "interval_minutes": 1440
  }
  ```
  - Lưu ý giới hạn dưới ở backend (tương tự `BR-301` của cleanup kẹp `>= 5` phút ở `admin_core.py:222`), ví dụ kẹp `interval_minutes >= 60` (hoặc `>= 30`) để tránh reset VM liên tục gây rate-limit từ `muse.ai`.

### 3.3. Background Scheduler & Xử lý xung đột đồng thời (`WSSPool`, `KeepAliveService`)

Đây là phần có rủi ro cao nhất khi triển khai:

1. **Ngắt kết nối khi đang có request chạy (`in-flight requests`):**
   - `WSSPool.execute_chat` (`wss_pool.py:286-335`), `stream_chat_events` (`wss_pool.py:337-397`), và `generate_media` (`wss_pool.py:399-483`) gọi `get_client(aid)` rồi nhả `_get_acc_lock(aid)` trước khi thực thi RPC (có thể kéo dài 180–300 giây cho video/TTS).
   - Nếu reset gọi `close_account(aid)` ngang chừng, `MuseWSSClient.close()` (`muse_wss.py:513-524`) sẽ gửi `None` vào tất cả stream queue đang chạy, làm lỗi request và kích hoạt `except` khiến pool đánh dấu nhầm tài khoản là `cooldown`.
   - **Giải pháp:**
     - Đặt `status = "resetting"` ngay đầu quy trình reset → `_candidate_accounts()` (`wss_pool.py:167-178`, chỉ chọn `healthy`, `unknown`, `cooldown`) sẽ **tự động loại tài khoản này khỏi các request mới**.
     - Bổ sung bộ đếm `_in_flight[aid]` (hoặc đọc `client._streams`) trên `WSSPool` để **chờ các request đang chạy hoàn tất** (drain với timeout, ví dụ tối đa 60–120s cho auto-reset; hoặc hoãn lượt auto-reset nếu tài khoản đang bận) trước khi gọi `close_account(aid)` và `replace-vm`.

2. **Xung đột với `WSSPool.maintain_tunnels()`, `KeepAliveService` và `Refresh`:**
   - `WSSPool.maintain_tunnels()` (`wss_pool.py:235-241`) hiện chỉ bỏ qua `not enabled`, `status == "expired"`, và `is_quota_exhausted`. Nếu không sửa, nó sẽ thấy tunnel bị đóng trong lúc reset và gọi `test_account(aid)` mỗi 60s, gây lỗi hoặc ghi đè `status`.
   - `KeepAliveService.run_due()` (`keepalive.py:55-63`) chỉ bỏ qua `not enabled`, sẽ gọi `/api/session` + `/api/hatch/vm/wake` và ghi đè `status = "healthy"` giữa lúc đang reset.
   - `POST /admin/accounts/{id}/refresh` (`routers/accounts.py:271-323`) cũng có thể chạy trùng lúc reset.
   - **Giải pháp:** Đồng bộ kiểm tra `status == "resetting"` (và/hoặc per-account reset lock trong `WSSPool` / `ResetService`) tại cả 3 nơi: `maintain_tunnels()`, `KeepAliveService.run_due()`, và `_refresh_account_full()`.

3. **An toàn cho toàn bộ Pool khi Auto-Reset:**
   - Không chạy song song nhiều account cùng lúc: nên dùng 1 `ResetService` chạy nền kiểm tra mỗi `60s` (theo đúng pattern `KeepAliveService._loop()` ở `keepalive.py:39-48`, tốt hơn `CleanupService` sleep cả chu kỳ vì nhận thay đổi settings trong <= 60s), và **reset tuần tự từng tài khoản một** (`max_workers = 1`).
   - Nếu toàn bộ pool chỉ còn 1 tài khoản `healthy` duy nhất phục vụ `/v1/*`, việc auto-reset sẽ gây `503 No healthy enabled accounts available` trong thời gian reset (có thể mất 30–120s). Cần chốt chính sách rõ cho trường hợp này.
   - Tài khoản `enabled = false` hoặc `status == "expired"` phải bị bỏ qua khi auto-reset.

4. **Đồng bộ vs Bất đồng bộ cho API thủ công (`POST /admin/accounts/{id}/reset`):**
   - Reset VM + chờ VM mới khởi động + handshake WSS có thể mất **30–120 giây**, dễ vượt ngưỡng timeout HTTP của browser/reverse-proxy nếu chạy đồng bộ.
   - Thiết kế khuyến nghị: `POST /admin/accounts/{id}/reset` kiểm tra hợp lệ, chuyển `status = "resetting"`, đẩy job vào worker thread riêng và trả về `202 Accepted` (hoặc `{ ok: true, status: "resetting", account }`). Frontend hiện đã poll `GET /admin/accounts` và `GET /admin/dashboard` mỗi **5 giây** (`AccountsPage.tsx:132`, `OverviewPage.tsx:32`) nên UI tự cập nhật tiến trình và kết quả khi xong.

### 3.4. Giao diện Frontend (`AccountsPage.tsx`, `SettingsPage.tsx`, `OverviewPage.tsx`)

- **`AccountsPage.tsx`:**
  - **Import Modal (`AccountsPage.tsx:495-545`) & Edit Modal (`AccountsPage.tsx:547-616`):** Thêm toggle `Auto Reset` theo đúng pattern `Switch` của `Enabled in Pool` (`AccountsPage.tsx:599-602`), kèm hiển thị `last_reset_at` / `last_reset_error` trong Edit Modal (hoặc tooltip trên bảng).
  - **Bảng Accounts (`AccountsPage.tsx:374-489`):**
    - Cột `Actions` hiện có độ rộng `w-[124px]` chứa 3 nút icon (`Edit`, `Refresh`, `Delete`). Thêm nút **Reset Muse** (ví dụ icon `RotateCcw`) cần nới `w-[124px]` lên khoảng `w-[156px]` để giữ sticky column không bị cắt.
    - Nên mở hộp thoại xác nhận (confirm modal) trước khi Reset thủ công vì thao tác này xóa toàn bộ lịch sử chat, file và tác vụ đang chạy trên VM của tài khoản `muse.ai`.
    - Cập nhật hàm render `Badge` cho `status === "resetting"` (`variant="info"` + spinner) ở cả `AccountsPage.tsx:401-411` và `OverviewPage.tsx:149-159`.
- **`SettingsPage.tsx`:**
  - Thêm card **Auto Reset Muse** theo đúng bố cục của card **Media Cleanup** (`Switch` bật/tắt ở `CardHeader`, ô nhập chu kỳ + nút Save và có thể thêm `Run Due Resets Now` ở `CardContent`).

---

## 4. Quyết định sản phẩm đã chốt

1. **Giao thức Reset Muse:** Dùng Luồng A (`POST https://muse.ai/api/hatch/replace-vm`), đã được kiểm chứng thực nghiệm thành công trên `acc_8ab7bcee5a91` (xem mục 5).
2. **Mô hình lịch Auto-Reset:** Cấu hình theo **khoảng thời gian lặp lại** (`interval_minutes`, tương tự Keep-Alive & Media Cleanup), kết hợp cờ `auto_reset` riêng trên từng tài khoản.
3. **Chính sách hoãn khi bận / ít tài khoản:** Hoãn lượt auto-reset nếu tài khoản đang có request `/v1/*` chạy (`in-flight > 0`) **hoặc** pool chỉ còn đúng 1 tài khoản `healthy` khả dụng.
4. **Điều kiện Quota & Đếm Request phát sinh:**
   - **Không** auto-reset các tài khoản đã hết quota (`is_quota_exhausted(quota_json)`).
   - **Đếm số request đến từng tài khoản** (kể từ lần reset gần nhất, ví dụ cột `requests_since_reset` trên `accounts` được tăng khi tài khoản xử lý request `/v1/*` và đặt về `0` sau mỗi lần reset thành công). Nếu đến hạn auto-reset nhưng tài khoản **chưa phát sinh request nào** (`requests_since_reset == 0`) thì **tiếp tục hoãn** (không reset vô ích).
5. **Chế độ API nút Reset thủ công:** Trả `202` chạy nền với trạng thái `status = "resetting"`, giao diện `AccountsPage` / `OverviewPage` tự cập nhật qua polling 5s sẵn có.

---

## 5. Kết quả kiểm chứng thực nghiệm (`acc_8ab7bcee5a91`)

Thực hiện trực tiếp trên tài khoản `andersenzaire000@gmail.com` (`acc_8ab7bcee5a91`) ngày 2026-11-22:

| Bước                                                                              | Kết quả thực tế              | Thời gian / Chi tiết                                                                                                                                                                            |
| --------------------------------------------------------------------------------- | ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Pre-check** `GET /api/session?vm_state=live`                                    | `HTTP 200`                   | `old_vm_id = 965a9fd2-4168-442f-a87b-3adefcf112d7`, `vm_type = hatch_vm`, `vm_selection.revision = 1`, `override = null`                                                                        |
| **Pre-check** `GET /settings`                                                     | `HTTP 200`                   | Trích xuất thành công `ownerId`                                                                                                                                                                 |
| **Trigger** `POST /api/hatch/replace-vm`                                          | `HTTP 200` (`5.77s`)         | Body gửi: `{"sourceEnvId": "965a9fd2-...", "destinationType": "standard", "intent": "reset"}`<br>Phản hồi: `{"ok": true, "vmId": "4ac4162e-3028-4a99-a037-dbe83b7a2a26", "releasedOld": true}`  |
| **Post-1** `GET /api/session?vm_state=live` (trước `updateUserPreferencesAction`) | `HTTP 200`                   | `status = "assigned"`, `vm_id = 4ac4162e-...` (đã tự chuyển sang VM mới), `vms = [("4ac4162e-...", "hatch_vm", "UNKNOWN", is_preferred=True)]`, `vm_selection.override = null` (`revision = 1`) |
| **Post-1** `GET /thread/new` (trước `updateUserPreferencesAction`)                | `HTTP 200`                   | `vmName` trong trang đã **tự trỏ sang `4ac4162e-3028-4a99-a037-dbe83b7a2a26`** (`matches_new = True`)                                                                                           |
| **Sync** `POST /settings` (`updateUserPreferencesAction`)                         | `HTTP 200` (`1.37s`)         | Cập nhật `vm_selection.revision: 1 -> 2`, `override.vmName = 4ac4162e-...`                                                                                                                      |
| **WSS Verify** `Noise_XX` + `GET /health`                                         | `HTTP 200` ngay lần thử `#1` | Kết nối WSS thành công tại `12.3s`, tổng thời gian đến `WSS /health = 200` là **`15.94s`**                                                                                                      |

**Kết luận kỹ thuật rút ra từ thực nghiệm:**

- `POST /api/hatch/replace-vm` tự động giải phóng VM cũ (`releasedOld: true`), gán VM mới làm VM mặc định trong `/api/session` và `/thread/new` ngay lập tức mà **không bắt buộc** phải phụ thuộc vào Next-Action hash `updateUserPreferencesAction` để kết nối WSS.
- Tuy vậy, gọi best-effort `updateUserPreferencesAction` (nếu có `ownerId`) giúp đồng bộ cả `vm_selection.override` cho trình duyệt; nếu Next-Action hash thay đổi trong tương lai, lỗi ở bước này không làm hỏng kết nối WSS của backend.
- Toàn bộ quy trình diễn ra trong ~`16s` (nhanh hơn nhiều so với ước tính ban đầu 30–120s).
