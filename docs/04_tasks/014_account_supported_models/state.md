# State: Task 014 — Account Supported Models (`chat`, `image`, `video`, `speech`) & Capability Routing

- **Trạng thái:** `Completed`
- **Tiến độ:** 100%
- **Ngày hoàn thành:** `2026-11-19`

## Nhật ký thực hiện

1. **Bước 1 — SQLite Schema, Migration & Helpers:**
   - Trong [db.py](../../../packages/backend/db.py): bổ sung hằng số `SUPPORTED_MODEL_TYPES = ("chat", "image", "video", "speech")`, hàm `normalize_supported_models` (chặn rỗng/phần tử lạ, khử trùng lặp và giữ thứ tự chuẩn) và `parse_supported_models` (fallback an toàn về đủ 4 loại).
   - Bổ sung cột `supported_models_json` và logic migration `ALTER TABLE accounts ADD COLUMN supported_models_json ...` cho database cũ.
   - Cập nhật `create_account` và `update_account`.
2. **Bước 2 — Admin Accounts API & Export:**
   - Trong [accounts.py](../../../packages/backend/routers/accounts.py): mở rộng Pydantic models `AccountCreateReq`, `AccountPatchReq`, serialize `supported_models`, và đưa `supported_models` vào `GET /admin/accounts/export`.
   - Xác nhận `PATCH` chỉ đổi `supported_models` không đóng WSS socket của tài khoản.
3. **Bước 3 — Capability Routing & Fail-Fast 503:**
   - Trong [wss_pool.py](../../../packages/backend/services/wss_pool.py): cập nhật `_candidate_accounts(capability)` chỉ chọn các tài khoản có bật loại model tương ứng (`chat`, `image`, `video`, `speech`), `_no_candidate_error(capability)`, và hàm `ensure_candidate(capability)` ném `NoCandidateAccountError`.
   - Trong [v1_openai.py](../../../packages/backend/routers/v1_openai.py): kiểm tra sớm `_ensure_capability_or_503` trước khi tạo task async (`videos`, `videos/generations`, `images/tasks`, `async=true` media) và trước khi mở SSE stream (`chat/completions`, `responses`), trả ngay HTTP `503 Service Unavailable` chuẩn OpenAI mà không tạo task rác trong DB.
4. **Bước 4 — Giao diện Accounts Console:**
   - Trong [AccountsPage.tsx](../../../packages/frontend/src/pages/AccountsPage.tsx): thêm component `SupportedModelsPicker` với 4 toggle pill (`Chat`, `Image`, `Video`, `Speech`), bộ đếm `X/4 enabled`, cảnh báo khi bỏ chọn hết cả 4, và khóa nút submit.
   - Bổ sung cột `Models` hiển thị danh sách badge chỉ xem trên bảng Accounts.
5. **Bước 5 — Kiểm thử tự động & Xác minh trình duyệt:**
   - Viết test suite toàn diện tại [test_account_supported_models.py](../../../packages/backend/tests/test_account_supported_models.py). Toàn bộ 24/24 tests backend (gồm cả test suite voices/speech) đều **PASS 100%**.
   - Build frontend thành công sạch sẽ với `npm run build` (`tsc -b && vite build`, 0 errors).
   - Browser Subagent đã thực thi kiểm chứng E2E trên `http://127.0.0.1:18619/accounts`: kiểm tra bảng Accounts, modal Import (4/4 mặc định, bỏ chọn hết báo lỗi & khóa nút Save), modal Edit (bật/tắt, lưu thành công cập nhật bảng, reload trang vẫn giữ đúng trạng thái), và kiểm tra responsive mobile (390x844). 0 lỗi console, 0 request mạng lỗi.

- **Blockers:** Không có

## Ghi chú chuẩn bị

- Đặc tả đã hoàn tất và đồng bộ tại:
  - [01_accounts_and_keepalive/spec.md](../../03_features/01_accounts_and_keepalive/spec.md) (`FR-013`, `BR-005`, `AC-013`, `AC-014`)
  - [02_openai_api_and_keys/spec.md](../../03_features/02_openai_api_and_keys/spec.md) (`FR-105`, `BR-111`, `AC-113`, `AC-114`)
  - [erd.md](../../02_basic_design/02_database/erd.md) & [schema_summary.md](../../02_basic_design/02_database/schema_summary.md)
- Sẵn sàng triển khai theo [plan.md](./plan.md).
