---
name: build
description: Triển khai tính năng (/build <tên tính năng>) dựa trên tài liệu đặc tả. Đọc docs/03_features/<feature>/request-changes.md khi có để nắm phần đặc tả vừa thay đổi, tự động kiểm tra trạng thái trong docs/04_tasks/, tự động tạo mới task nếu chưa tồn tại, thực thi code, kiểm thử tự động, xác minh trình duyệt và đồng bộ trạng thái thực tế.
---

# Skill: /build (Implementation & Execution)

## 1. Mục Tiêu (Objective)

Triển khai, sửa đổi hoặc mở rộng mã nguồn hệ thống theo đúng tài liệu đặc tả đã được phê duyệt. Duy trì sự ổn định, tuân thủ quy chuẩn kỹ thuật và kiểm thử nghiêm ngặt.

**Cú pháp kích hoạt:**
```bash
/build <tên_tính_năng>
```
*Ví dụ:* `/build channel_management`, `/build 02_automation_workflows`, `/build custom_goal_presets`

---

## 2. Quy Trình 5 Bước Chuẩn (Standard Lifecycle)

```text
/build <tên_tính_năng>
           │
           ▼
[Bước 1: Kiểm Tra Task Trong docs/04_tasks/]
           │
           ├──► Tìm thấy task ──► Đọc plan.md, state.md và request-changes.md (nếu có)
           │
           └──► Chưa có task  ──► Kiểm tra spec trong docs/03_features/
                                  ├── Có spec ──► Tự động tạo docs/04_tasks/<xxx_feature>/
                                  │               (Sinh plan.md & state.md, cập nhật backlog.md)
                                  └── Chưa có ──► DỪNG LẠI, kích hoạt /spec trước
           │
           ▼
[Bước 2: Cập Nhật Trạng Thái & Lập Trình (Coding)]
           │  - Đặt state.md thành `In Progress`
           │  - Thực thi theo checklist trong plan.md
           │  - Thỏa mãn FR-xxx, BR-xxx và AC-xxx
           ▼
[Bước 3: Kiểm Thử Tự Động & Kiểm Chứng Trình Duyệt]
           │  - Chạy npm test (Unit/Integration)
           │  - Chạy build / type-check (npm run build)
           │  - Nếu có UI: Xác minh luồng trên trình duyệt (Browser Verification)
           ▼
[Bước 4: Đồng Bộ Hóa Trạng Thái & Báo Cáo Trung Thực]
           │  - Cập nhật checklist trong plan.md
           │  - Cập nhật state.md theo chuẩn Agents.md (Real 100% vs Mock 50%)
           │  - Đồng bộ trạng thái trong docs/03_features/<feature>/spec.md
           ▼
[Bước 5: Báo Cáo Kết Quả Theo Format Chuẩn]
```

---

## 3. Bước 1: Kiểm Tra & Khởi Tạo Task Trong `docs/04_tasks/`

Khi nhận lệnh `/build <tên_tính_năng>`:

### 3.1. Tìm kiếm trong `docs/04_tasks/`:
- Quét danh sách các thư mục con trong `docs/04_tasks/` (ví dụ `001_...`, `002_...`).
- Nếu tìm thấy thư mục khớp với tên tính năng:
  - Nạp nội dung `plan.md` (checklist, kế hoạch) và `state.md` (trạng thái, blockers).
  - Đọc `docs/03_features/<xx_feature>/request-changes.md` nếu có; entry mới nhất cho biết phần đặc tả nào vừa đổi và là nguồn phạm vi bổ sung cho task.
  - Xác nhận các công việc đã làm và các công việc còn lại.
  - Chuyển trạng thái trong `state.md` sang `In Progress`.

### 3.2. Nếu KHÔNG tìm thấy trong `docs/04_tasks/`:
1. Kiểm tra tài liệu đặc tả trong `docs/03_features/`:
   - Tìm thư mục tính năng tương ứng trong `docs/03_features/<xx_feature_name>/spec.md`.
   - Đọc `request-changes.md` cùng thư mục nếu có; xác định entry mới nhất liên quan đến đặc tả sắp triển khai.
   - **Quality Gate:** Nếu chưa có tài liệu đặc tả hoặc tài liệu đang ở trạng thái `Draft` chưa hoàn thiện:
     - **DỪNG VIỆC CODE NGAY LẬP TỨC.**
     - Kích hoạt kỹ thuật `/spec` để làm rõ yêu cầu và phản biện qua `/grill-me`.
2. Khi đặc tả đã sẵn sàng (`Ready for Implementation`):
   - Đếm số lượng task hiện có trong `docs/04_tasks/` để lấy số thứ tự 3 chữ số tiếp theo (ví dụ: `005_<ten_tinh_nang>`).
   - Tạo thư mục: `docs/04_tasks/<xxx_ten_tinh_nang>/`.
   - **Tạo tệp `plan.md`:**
     - Mô tả mục tiêu kỹ thuật.
     - Danh sách files cần tạo mới hoặc chỉnh sửa.
     - Checklist công việc chi tiết chia theo từng tiêu chí nghiệm thu (`AC-xxx`).
     - Kế hoạch kiểm thử tự động và kiểm chứng giao diện.
     - Nếu có `request-changes.md`, ghi liên kết tới entry mới nhất ở đầu plan.
   - **Tạo tệp `state.md`:**
     - Trạng thái: `In Progress`.
     - Tiến độ: `0%`.
     - Nhật ký thực hiện (Execution Log).
   - **Cập nhật `docs/04_tasks/backlog.md`:** Thêm task mới vào bảng quản lý tiến độ.

---

## 4. Bước 2: Triển Khai Mã Nguồn (Implementation)

- **Nguyên tắc đọc tài liệu thiết kế:**
  - **Nhật ký thay đổi (`request-changes.md`):** Đọc entry mới nhất của tính năng để biết yêu cầu nào vừa làm thay đổi `spec.md`, `design.md`, `logic.md` và mã `FR/BR/AC` liên quan. Chỉ đọc file này; `/spec` là nơi ghi entry mới.
  - **Giao diện trực quan (`design.md`):** Đọc bản vẽ wiremd để dựng đúng cấu trúc HTML/CSS, bố cục component, thẻ, trường nhập liệu, nút bấm và trạng thái hiển thị. Tệp này là bản vẽ mockup thuần túy, không chứa code logic.
  - **Luồng xử lý & Sự kiện (`logic.md`):** Đọc bảng `UI Event Handlers` để biết chính xác sự kiện click/submit của từng nút gọi API endpoint nào, kèm theo Sequence Diagram, các hàm xử lý dữ liệu và thuật toán nghiệp vụ.
- **Tuân thủ quy ước:**
  - Quy chuẩn đặt tên, định dạng response và xử lý lỗi theo `docs/00_common/conventions.md`.
  - Công nghệ theo danh mục phê duyệt tại `docs/00_common/tech_stack.md`.
- **Kiểm soát phạm vi (Anti-Scope-Creep):**
  - Chỉ chỉnh sửa các file thuộc phạm vi task.
  - Tuyệt đối không tự ý refactor code không liên quan hoặc thay đổi cấu hình dự án mà chưa có yêu cầu.
- **Tuân thủ quy tắc nghiệp vụ:**
  - Đảm bảo các `BR-xxx` được tôn trọng (ví dụ: SQLite WAL mode, cô lập thư mục workspace, human delay 1.5-3.5s chống bot).

---

## 5. Bước 3: Kiểm Thử Tự Động & Xác Minh Trình Duyệt

### 5.1. Kiểm thử tự động bắt buộc:
1. **Unit & API Tests:** Chạy `npm test` hoặc script test cụ thể, đảm bảo toàn bộ tests passed.
2. **Type Check & Build:** Chạy `npm run build` (hoặc `tsc`) để đảm bảo không có lỗi TypeScript, lỗi import hoặc lỗi bundle.
3. **Linter / Formatting:** Đảm bảo code sạch sẽ, không để lại `console.log` debug rác hoặc token nhạy cảm.

### 5.2. Xác minh trên trình duyệt (Browser Verification Flow - Bắt buộc nếu có UI):
- Khi thay đổi giao diện (UI, layout, CSS, routing, form):
  - Mở ứng dụng trên trình duyệt qua công cụ browser có sẵn.
  - Thao tác tương tác end-to-end: click, nhập liệu, submit, kiểm tra phản hồi.
  - Kiểm tra trạng thái rỗng (empty state), trạng thái đang tải (loading) và xử lý lỗi (error state).
  - Kiểm tra tính tương thích trên cả Desktop và Mobile viewport.

---

## 6. Bước 4: Đồng Bộ Trạng Thái & Báo Cáo Trung Thực (Theo Agents.md)

### 6.1. Nguyên tắc minh bạch mức độ triển khai:
- **`Implemented (Production)` - 100% tiến độ:**
  - Kết nối dịch vụ thật, có bằng chứng thực tế (DB ghi thành công, browser thật mở, API trả về HTTP 200).
- **`Implemented (Mock Data)` - 50% tiến độ:**
  - Đã có luồng chạy hoàn chỉnh (Database, API, UI) nhưng tích hợp bên ngoài dùng mock/stub/simulator.
  - Phải ghi rõ trong báo cáo: *"Đã hoàn thành với dữ liệu mock (Mock Data / Prototype / Simulation)"*.

### 6.2. Cập nhật hồ sơ:
- Đánh dấu hoàn thành checklist trong `docs/04_tasks/<xxx_task>/plan.md`.
- Cập nhật tiến độ và ghi chú trong `docs/04_tasks/<xxx_task>/state.md`.
- Cập nhật trạng thái trong `docs/03_features/<feature>/spec.md` và `docs/04_tasks/backlog.md`.
- Giữ nguyên các entry trong `docs/03_features/<feature>/request-changes.md`; file này do `/spec` ghi khi đặc tả thay đổi.

---

## 7. Bước 5: Báo Cáo Hoàn Thành

Khi hoàn thành công việc, báo cáo theo đúng định dạng quy định:

```markdown
**Đã xong**:
- **Tính năng triển khai:** <Tên tính năng / Task ID>
- **Các tệp thay đổi:**
  - `path/to/file1`
  - `path/to/file2`
- **Mức độ hoàn thiện:** Implemented (Production - 100%) | Implemented (Mock Data - 50%)
- **Bằng chứng kiểm thử:**
  - Lệnh test: `npm test` (X passed, 0 failed)
  - Lệnh build: `npm run build` (Success)
  - Kiểm chứng giao diện: (Kết quả thao tác browser)
- **Hồ sơ tiến độ đã cập nhật:**
  - `docs/04_tasks/<xxx_task>/plan.md`
  - `docs/04_tasks/<xxx_task>/state.md`
  - `docs/03_features/<feature>/spec.md`
```
