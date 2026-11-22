# Task 002: Accounts Pool, Proxy & Keep-Alive

## 1. Mục tiêu triển khai

Triển khai quản lý tài khoản (import cookie, bật/tắt, mask cookie, test WSS, test proxy, quota), WSS connection pool (LRU + failover) và Background Keep-Alive Scheduler theo [Accounts Spec](../../03_features/01_accounts_and_keepalive/spec.md).

## 2. Danh sách tệp tin cần tạo

- `backend/services/cookie_parser.py`
- `backend/services/wss_pool.py`
- `backend/services/keepalive.py`
- `backend/routers/accounts.py`

## 3. Checklist triển khai

- [ ] `cookie_parser.py`: hỗ trợ parse `Cookie:` header string và JSON array/dict, kiểm tra cookie phiên (`AC-001`).
- [ ] `wss_pool.py`: giữ ấm 1 WSS tunnel per account `healthy`, chọn tài khoản theo LRU `last_used_at`, đóng socket khi `enabled=false` (`AC-003`), tự động failover khi lỗi.
- [ ] `keepalive.py`: scheduler chạy nền mỗi `20 phút` gọi `/api/session` + `/api/hatch/vm/wake`, đánh dấu `expired` nếu `401`, ghi `keepalive_logs` (`AC-004`).
- [ ] `routers/accounts.py`: các route `/admin/accounts*` (CRUD, `/test`, `/quota`, `/proxy/test`, `/keepalive`), luôn mask cookie & proxy password (`AC-001`, `AC-002`).

## 4. Kế hoạch kiểm thử

- **Unit test:** Cookie parser (header & JSON), mask secret, LRU selection & failover.
- **Integration test:** Import cookie qua `POST /admin/accounts`, gọi `POST /admin/accounts/{id}/test` và `POST /admin/accounts/keepalive`.
