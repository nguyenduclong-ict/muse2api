# Request changes: OpenAI-Compatible API (`/v1/*`) & API Key

## 2026-11-17 — Collapsible Input/Output Endpoints & UI Stability

- **Yêu cầu:** Bổ sung hướng dẫn Input/Output dạng collapse cho từng endpoint `/v1/*` và cố định kích thước nút Show/Copy.
- **Phân loại:** Feature mở rộng
- **Đặc tả thay đổi:**
  - `spec.md`: bổ sung `FR-110`.
- **Quyết định:** Dùng accordion đóng/mở theo từng endpoint và cố định chiều rộng nút `Show/Hide`, `Copy/Copied`.
- **Task:** đã triển khai trực tiếp

## 2026-11-17 — Bổ sung parity đầy đủ với `muse2api` v1 (loại trừ `/v1/audio/speech`)

- **Yêu cầu:** Bổ sung đầy đủ các tính năng `/v1/*` còn thiếu so với `../muse2api` (streaming `/v1/responses`, reference media kèm chống SSRF, `async` flag, `Idempotency-Key`, metadata task, đầy đủ model alias, hỗ trợ `image_url` trong chat và `MUSE2API_TOOL_PROTOCOL`), bỏ qua endpoint `/v1/audio/speech`.
- **Phân loại:** Feature mở rộng
- **Đặc tả thay đổi:**
  - `spec.md`: cập nhật Phạm vi (loại bỏ `/v1/audio/speech`), bổ sung `FR-106`..`FR-109`, `BR-104`..`BR-105`, `AC-104`..`AC-106`.
  - `logic.md`: bổ sung luồng SSRF Guard cho reference URLs và SSE events cho `/v1/responses`.
  - `01_api_overview.md`: đồng bộ danh sách endpoints `/v1/*` (bỏ `/v1/audio/speech`).
- **Quyết định:** Giữ cơ chế chống SSRF mặc định tắt fetch mạng nội bộ/file cục bộ như v1; không triển khai `/v1/audio/speech` theo xác nhận của người dùng.
- **Task:** [T-006](../../04_tasks/006_v1_api_parity/plan.md)
