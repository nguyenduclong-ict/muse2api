---
name: spec
description: Phân loại yêu cầu (feature/bug) và đánh giá phạm vi ảnh hưởng tài liệu, kích hoạt phản biện sâu, khảo sát codebase và thiết lập tài liệu đặc tả chuẩn hóa theo kiến trúc 5 tầng của docs/. Khi cập nhật tính năng đã có, ghi nhật ký vào docs/03_features/<feature>/request-changes.md. Sau khi tạo tài liệu, chủ động hỏi người dùng để khởi tạo task trong 04_tasks/.
---

# Skill: /spec (Specification & Documentation)

## 1. Mục Tiêu (Objective)

Đặc tả rõ ràng, chặt chẽ và có khả năng kiểm chứng cho mọi tính năng, kiến trúc hoặc thay đổi trong hệ thống. Đảm bảo tài liệu là nguồn chân lý duy nhất (Single Source of Truth) trước khi triển khai code.

**Nguyên tắc vàng:** Luôn bám sát thực tế nghiệp vụ, kiểm chứng thông tin qua codebase và tài liệu hiện có. Phản biện kỹ lưỡng trước khi chốt đặc tả.

---

## 2. Quy Trình 5 Pha Chuẩn (Standard Lifecycle)

```text
Yêu Cầu Từ Người Dùng / Khách Hàng
       │
       ▼
[Pha 1: Phân Loại Yêu Cầu & Đánh Giá Tài Liệu]
       │  - Phân loại: Feature vs Bug (chạy đầu tiên)
       │  - Đánh giá mức độ ảnh hưởng đến tài liệu nghiệp vụ
       │  ├── Feature ──► Tạo doc mới (tính năng mới) hoặc Cập nhật doc (tính năng đã có)
       │  └── Bug     ──► Đánh giá thay đổi nghiệp vụ:
       │                   ├── Có đổi nghiệp vụ ──► Cập nhật spec.md / logic.md
       │                   └── Lỗi kỹ thuật thuần túy ──► Giữ nguyên spec (bổ sung AC/edge case nếu cần)
       ▼
[Pha 2: Khảo Sát & Phản Biện Sâu]
       │  - Kích hoạt kỹ năng có tên "grilling"
       │  - Tự động khảo sát sự thật qua codebase & docs
       │  - Phỏng vấn người dùng theo từng vòng (Rounds)
       │
       └────► BẮT BUỘC DỪNG LẠI & CHỜ NGƯỜI DÙNG PHẢN HỒI (Interactive Gate):
              ├── Chưa đạt đồng thuận ──► Tiếp tục phỏng vấn vòng tiếp theo
              └── Đã đạt đồng thuận (Shared Understanding) ──► Chuyển sang Pha 3
       ▼
[Pha 3: Thiết Kế & Đặc Tả Chuẩn Hóa]
       │  - Viết/cập nhật tài liệu theo cấu trúc 5 tầng của docs/
       │  - Feature cũ: ghi entry mới vào request-changes.md
       │  - Gán mã định danh ổn định (FR-xxx, BR-xxx, AC-xxx)
       │  - Sử dụng cú pháp Markdown Relative Links trực tiếp
       │  - Tập trung nội dung kỹ thuật, không chèn văn bản khẩu hiệu/boilerplate
       ▼
[Pha 4: Hoàn Thiện & Kiểm Tra Toàn Vẹn Liên Kết]
       │  - Đặt trạng thái: Draft | Ready for Implementation
       │  - Kiểm tra toàn vẹn Markdown Relative Links
       │  - docs/README.md chỉ giới thiệu cấu trúc thư mục gốc,
       │    không liệt kê chi tiết các tính năng đã triển khai
       ▼
[Pha 5: Cầu Nối Triển Khai (04_tasks Trigger)]
       │
       └────► BẮT BUỘC HỎI NGƯỜI DÙNG:
              "Bạn có muốn tạo task trong docs/04_tasks/ để chuẩn bị triển khai không?"
              ├── Có ──► Tự động tạo docs/04_tasks/<xxx_ten_task>/ (plan.md & state.md)
              └── Không ──► Kết thúc quy trình /spec
```

---

## 3. Pha 1: Phân Loại Yêu Cầu & Đánh Giá Tài Liệu (Bắt Buộc Chạy Đầu Tiên)

Ngay khi tiếp nhận yêu cầu, Agent thực hiện phân loại và xác định mức độ tác động lên hệ thống tài liệu:

### 3.1. Phân Loại Yêu Cầu:

1. **`Feature` (Triển khai tính năng):**
   - **Tính năng mới hoàn toàn:** Tạo thư mục và bộ tài liệu mới trong `docs/03_features/<xx_ten_tinh_nang>/` (gồm `spec.md`, `design.md` nếu có giao diện UI, `logic.md`). Cập nhật tài liệu cấp cao tại `docs/01_srs/` và `docs/02_basic_design/` khi tính năng tác động đến kiến trúc tổng thể, cơ sở dữ liệu hoặc hệ thống API.
   - **Tính năng đã có (Mở rộng / Nâng cấp):** Đọc `request-changes.md` hiện có (nếu có) để nắm các thay đổi trước. Cập nhật tài liệu hiện có trong thư mục tính năng tương ứng, bổ sung các mã định danh mới (`FR-xxx`, `BR-xxx`, `AC-xxx`), cập nhật sơ đồ sequence trong `logic.md` hoặc mockup trong `design.md`. Sau khi sửa, ghi một entry mới vào `request-changes.md` theo mục 5.2.

2. **`Bug` (Khách hàng / Người dùng báo lỗi):**
   - **Trường hợp làm thay đổi nghiệp vụ:** Lỗi phát sinh do quy tắc nghiệp vụ cũ chưa bao quát hết, xung đột logic, hoặc việc sửa lỗi dẫn đến thay đổi hành vi mong muốn của hệ thống, ràng buộc dữ liệu, thông báo phản hồi hay luồng thao tác trên giao diện.
     - _Hành động:_ Cập nhật tài liệu đặc tả (`spec.md`, `logic.md`, quy chuẩn `conventions.md`) trước khi thực hiện mã nguồn. Mọi thay đổi nghiệp vụ được ghi nhận vào tài liệu để bảo toàn vai trò nguồn chân lý duy nhất, kèm một entry trong `request-changes.md`.
   - **Trường hợp lỗi kỹ thuật thuần túy (Code defect):** Tài liệu nghiệp vụ đã mô tả chính xác hành vi mong muốn, lỗi xuất phát từ mã nguồn (lỗi cú pháp, thiếu kiểm tra null/undefined, unhandled exception, cấu hình sai biến môi trường, race condition).
     - _Hành động:_ Giữ nguyên các quy tắc nghiệp vụ cốt lõi trong `spec.md`. Bổ sung tiêu chí nghiệm thu kiểm thử (`AC-xxx`) hoặc kịch bản biên (Edge Case) vào tài liệu để phòng ngừa lỗi tái diễn, sau đó chuyển sang bước lập kế hoạch triển khai. Nếu tài liệu tính năng thay đổi, ghi entry tương ứng vào `request-changes.md`.

### 3.2. Ma Trận Quyết Định Tài Liệu (Documentation Decision Matrix):

| Loại Yêu Cầu | Tình Trạng Hiện Tại       | Đánh Giá Nghiệp Vụ                   | Hành Động Tài Liệu                                                 | Thư Mục Mục Tiêu                 |
| :----------- | :------------------------ | :----------------------------------- | :----------------------------------------------------------------- | :------------------------------- |
| **Feature**  | Tính năng mới hoàn toàn   | Định nghĩa nghiệp vụ mới             | Tạo bộ tài liệu mới (`spec.md`, `design.md`, `logic.md`)           | `docs/03_features/<xx_feature>/` |
| **Feature**  | Tính năng đã có sẵn       | Mở rộng hoặc thay đổi nghiệp vụ      | Cập nhật tài liệu hiện có, bổ sung `FR-xxx`, `BR-xxx`, `AC-xxx`    | `docs/03_features/<xx_feature>/` |
| **Bug**      | Báo cáo lỗi từ người dùng | Có thay đổi quy tắc nghiệp vụ        | Cập nhật quy tắc `BR-xxx`, hành vi `FR-xxx`, tiêu chí `AC-xxx`     | `docs/03_features/<xx_feature>/` |
| **Bug**      | Báo cáo lỗi từ người dùng | Lỗi kỹ thuật thuần túy (Code defect) | Giữ nguyên spec, bổ sung tiêu chí kiểm thử `AC-xxx` hoặc edge case | `docs/03_features/<xx_feature>/` |

Mọi hành động cập nhật tài liệu của một tính năng đã có đều kèm một entry mới trong `docs/03_features/<xx_feature>/request-changes.md` (mục 5.2).

### 3.3. Xác Nhận Phân Loại Ban Đầu Với Người Dùng:

Trước khi bước vào phản biện sâu, Agent thông báo ngắn gọn kết quả phân loại:

- **Phân loại:** `[Feature | Bug]`
- **Đánh giá tài liệu:** `[Tạo document mới | Cập nhật document hiện có | Giữ nguyên spec, bổ sung AC/edge case]`
- **Tài liệu mục tiêu:** `docs/03_features/<tên_thư_mục>/...`
- **Nhật ký thay đổi:** `docs/03_features/<tên_thư_mục>/request-changes.md` (chỉ khi cập nhật tính năng đã có)

---

## 4. Pha 2: Khảo Sát & Phản Biện Sâu Qua Kỹ Năng (nếu cần)

### 4.1. Tìm Kiếm & Khởi Chạy Skill:

Call the Skill tool with "grilling", if not found, stop and ask the user to install it.

### 4.2. Trách Nhiệm Tìm Kiếm Sự Thật (Facts Finding):

- Việc khảo sát sự thật (codebase, cấu hình hiện có, tệp tài liệu cũ) là trách nhiệm của Agent thông qua các công cụ có sẵn. Tuyệt đối không hỏi người dùng những thông tin mà Agent có thể tự tra cứu được trong hệ thống.
- Quyền đưa ra quyết định (Decisions) thuộc về người dùng: Agent trình bày bối cảnh, các điểm mù và khuyến nghị; người dùng lựa chọn phương án.

### 4.3. Điều Kiện Chuyển Sang Pha 3:

- Phiên `grilling` chỉ kết thúc khi toàn bộ các nhánh của cây thiết kế (frontier) đã được giải quyết rõ ràng, không còn giả định ngầm và người dùng xác nhận đã đạt được sự đồng thuận (Shared Understanding).
- Khi đó, Agent mới bắt đầu chuyển sang Pha 3 để thiết kế và viết tài liệu đặc tả chuẩn hóa.

---

## 5. Pha 3: Cấu Trúc Tài Liệu 5 Tầng Chuẩn Hóa

Toàn bộ tài liệu kỹ thuật được tổ chức theo chuẩn mực thống nhất trong thư mục `docs/`:

```text
docs/
├── 00_common/                          # Quy ước & Từ điển dùng chung toàn dự án
│   ├── glossary.md                     # Từ điển thuật ngữ nghiệp vụ (Domain terms)
│   ├── conventions.md                  # Quy chuẩn đặt tên, mã lỗi, format response chung
│   └── tech_stack.md                   # Danh sách công nghệ, thư viện, phiên bản sử dụng
│
├── 01_srs/                             # CẤP 1: ĐẶC TẢ YÊU CẦU TỔNG QUAN (What & Why)
│   ├── overall_srs.md                  # Bối cảnh, mục tiêu, phạm vi dự án, luồng nghiệp vụ chính
│   ├── actors_and_permissions.md       # Danh sách tác nhân & Ma trận phân quyền (RBAC)
│   └── non_functional.md               # Yêu cầu phi chức năng (Bảo mật, hiệu năng, tải trọng)
│
├── 02_basic_design/                    # CẤP 2: THIẾT KẾ CƠ BẢN TOÀN HỆ THỐNG (High-Level How)
│   ├── 00_system_architecture.md       # Sơ đồ kiến trúc tổng thể, luồng dữ liệu (dùng Mermaid)
│   ├── 01_api_overview.md              # Danh sách tổng hợp các đầu API, chuẩn Auth, Rate limit
│   ├── 02_database/                    # Thiết kế Cơ sở dữ liệu tổng thể
│   │   ├── erd.md                      # Sơ đồ ERD (vẽ bằng Mermaid erDiagram hoặc DBML)
│   │   └── schema_summary.md           # Tổng hợp danh sách bảng & mô tả chức năng từng bảng
│   ├── 03_screens_overview.md          # Danh sách màn hình (Screen ID, Tên, Route) & Sơ đồ chuyển trang
│   └── decisions/                      # Các quyết định kiến trúc quan trọng (ADRs)
│
├── 03_features/                        # CẤP 3: CHI TIẾT TÍNH NĂNG / DETAILED DESIGN (Implementation)
│   └── <xx_ten_tinh_nang>/             # Đánh số thứ tự (01, 02...) theo nhóm module
│       ├── spec.md                     # Yêu cầu chi tiết, User stories, Business rules (FR, BR, AC)
│       ├── design.md                   # [Nếu có UI] Mô tả giao diện wiremd, layout, event xử lý
│       ├── logic.md                    # [DD] Sequence diagram, thuật toán, validation, DB query
│       └── request-changes.md          # Nhật ký thay đổi đặc tả (chỉ tạo khi cập nhật feature cũ)
│
└── 04_tasks/                           # QUẢN LÝ TIẾN ĐỘ & TRIỂN KHAI (Execution & Tracking)
    ├── backlog.md                      # Danh sách toàn bộ các task/milestone đang chờ
    └── <xxx_ten_task>/                 # Đánh số 3 chữ số (001, 002...) theo thứ tự thực tế
        ├── plan.md                     # Kế hoạch triển khai, các bước thực hiện, checklist đầu việc
        └── state.md                    # Trạng thái hiện tại, tiến độ, blockers
```

### 5.1. Quy Định Chi Tiết Trong `docs/03_features/<feature_name>/`

Mỗi tính năng có 3 tệp chính với ranh giới trách nhiệm phân minh. Khi cập nhật một tính năng đã có, thêm tệp thứ tư là `request-changes.md`.

1. **`spec.md` (Đặc tả yêu cầu & nghiệp vụ cốt lõi):**
   - **Mục tiêu & Bối cảnh:** Tại sao cần tính năng này?
   - **Trạng thái:** `Draft` | `Ready for Implementation` | `Implemented (Mock Data)` | `Implemented (Production)`.
   - **Phạm vi:** In Scope & Out of Scope rõ ràng.
   - **Yêu Cầu Chức Năng (`FR-xxx`):** Mô tả, điều kiện tiên quyết, hành vi mong muốn.
   - **Quy Tắc Nghiệp Vụ (`BR-xxx`):** Ràng buộc logic, tính toán, kiểm soát dữ liệu.
   - **Tiêu Chí Nghiệm Thu (`AC-xxx`):** Từng tiêu chí phải kiểm chứng được tự động hoặc qua thao tác cụ thể.

2. **`design.md` (Bản vẽ giao diện Mockup thuần túy theo skill /wireframe):**
   - **Đặc tả trực quan 100% bằng cú pháp wiremd:** Sử dụng các container `::: card`, `::: modal`, `::: tabs`, `::: tab`, `::: columns-N`, thanh điều hướng `[[ navbar ]]`, các nút `[Button]*`, các trường nhập `[Input___]`, lựa chọn `- (*)`, checkbox `- [x]`, huy hiệu `((Badge)){success}`.
   - **Quy chuẩn nội dung:**
     - Tệp `design.md` là bản vẽ mockup thuần túy, biên dịch trực tiếp ra HTML mockup qua công cụ `wiremd.js`.
     - Toàn bộ phần giải thích kỹ thuật (biến môi trường, đường dẫn tệp thực thi, giao thức stdio, cổng cấp phát, mã màu HEX, lý thuyết kiến trúc) đặt tại `logic.md` hoặc `spec.md`.
     - Bảng sự kiện giao diện (`UI Event Handlers`) đặt tại `logic.md`.

3. **`logic.md` (Thiết kế chi tiết luồng xử lý, thuật toán & Sự kiện tương tác):**
   - **Sequence Diagram:** Vẽ bằng Mermaid biểu diễn luồng tương tác giữa Client -> Server -> DB / Fury MCP / LLM.
   - **Xử Lý Sự Kiện Tương Tác Giao Diện (UI Event Handlers):** Bảng tổng hợp toàn bộ các sự kiện tương tác của người dùng (Click nút nào, submit form nào, gọi API endpoint nào, tham số truyền vào là gì).
   - **Thuật toán & Quy tắc xử lý:** Các bước validate dữ liệu đầu vào, thuật toán tính toán (ví dụ: `nextRunAt`, `humanDelay`).
   - **Thông số kỹ thuật backend:** Danh sách hàm xử lý, API routes liên quan, câu lệnh truy vấn CSDL và thông số tiến trình (daemon, environment variables).

4. **`request-changes.md` (Nhật ký thay đổi đặc tả của tính năng đã có):**
   - Chỉ tạo khi `/spec` sửa `spec.md`, `design.md` hoặc `logic.md` của một tính năng đã tồn tại.
   - Ghi lại yêu cầu đầu vào, phạm vi đặc tả đã đổi, quyết định và task triển khai; không chép lại toàn bộ nội dung đặc tả.
   - Mới nhất ở trên cùng; không sửa hoặc xoá entry cũ, chỉ bổ sung entry mới.

### 5.2. Quy Tắc Ghi `request-changes.md`

**Khi nào ghi:**

- Feature mở rộng hoặc nâng cấp một tính năng đã có.
- Bug làm thay đổi quy tắc nghiệp vụ, hành vi `FR-xxx`, `BR-xxx` hoặc tiêu chí `AC-xxx` của tính năng.
- Bug kỹ thuật thuần túy mà `/spec` vẫn bổ sung `AC-xxx` hoặc edge case vào tài liệu tính năng.
- Một thay đổi tác động nhiều tính năng: ghi một entry trong `request-changes.md` của từng tính năng bị ảnh hưởng.

Tính năng mới hoàn toàn chưa cần tệp này; tạo ở lần cập nhật đặc tả đầu tiên sau khi tính năng đã tồn tại.

**Cấu trúc entry:**

```markdown
# Request changes: <Tên tính năng>

## 2026-11-04 — <Tiêu đề ngắn của thay đổi>

- **Yêu cầu:** <Tóm tắt yêu cầu từ người dùng, 1–3 câu.>
- **Phân loại:** Feature mở rộng | Bug thay đổi nghiệp vụ | Bug bổ sung tiêu chí
- **Đặc tả thay đổi:**
  - `spec.md`: thêm `FR-xxx`, sửa `BR-xxx`, thêm `AC-xxx`
  - `logic.md`: <luồng hoặc thuật toán đã đổi>
  - `design.md`: <màn hình hoặc trạng thái đã đổi>
- **Quyết định:** <Lý do chọn hành vi mới; nêu phương án bị loại nếu quan trọng.>
- **Task:** [T-046](../../04_tasks/046_cartoon_ui_storage_naming/plan.md) hoặc `chưa tạo`
```

**Quy ước:**

- Heading dùng ngày thực hiện thay đổi theo `YYYY-MM-DD` và một tiêu đề ngắn, không dùng số thứ tự tự phát.
- Chỉ liệt kê mã yêu cầu và tên tệp đã đổi; nội dung chi tiết nằm trong `spec.md`, `design.md`, `logic.md`.
- Ghi quyết định nghiệp vụ, không ghi nhật ký sửa code.
- Sau khi tạo task ở Pha 5, cập nhật dòng `Task:` của entry vừa ghi bằng liên kết tương đối.
- Kiểm tra liên kết tương đối và tính duy nhất của heading trước khi kết thúc Pha 4.

---

## 6. Pha 4: Hoàn Thiện Tài Liệu & Kiểm Tra Toàn Vẹn Liên Kết

Sau khi hoàn tất việc tạo hoặc cập nhật tài liệu đặc tả ở Pha 3:

1. **Đặt trạng thái tài liệu đặc tả:**
   - Cập nhật trạng thái rõ ràng tại `docs/03_features/<xx_feature>/spec.md`: `Draft` hoặc `Ready for Implementation`.

2. **Kiểm tra nhật ký thay đổi (nếu cập nhật tính năng đã có):**
   - `docs/03_features/<xx_feature>/request-changes.md` có entry mới ở trên cùng, đúng ngày và tiêu đề.
   - Entry liệt kê các tệp trong `spec.md`/`design.md`/`logic.md` đã đổi và các mã `FR-xxx`, `BR-xxx`, `AC-xxx` liên quan.
   - Dòng `Task:` ghi `chưa tạo` hoặc liên kết tương đối tới `plan.md`.

3. **Kiểm tra tính toàn vẹn liên kết (Relative Links):**
   - Đảm bảo tất cả liên kết chéo giữa các tài liệu đều sử dụng đường dẫn tương đối và trỏ chính xác đến tệp tồn tại.
   - Khi tính năng tác động đến kiến trúc tổng thể, cơ sở dữ liệu hoặc API dùng chung, đồng bộ các tài liệu cấp cao tương ứng (`docs/01_srs/`, `docs/02_basic_design/`).

4. **Nguyên tắc bảo toàn `docs/README.md`:**
   - Tệp `docs/README.md` chỉ giới thiệu cấu trúc thư mục gốc của `docs/` (kiến trúc 5 tầng chuẩn hóa).
   - Danh mục các tính năng được lưu trữ độc lập tại từng thư mục con trong `docs/03_features/`.
   - Danh mục tác vụ và tiến độ dự án được quản lý tập trung tại `docs/04_tasks/backlog.md`.
   - Không liệt kê chi tiết các tính năng cụ thể hoặc danh sách task đã triển khai vào `docs/README.md`.

---

## 7. Quy Chuẩn Kỹ Thuật & Chống Văn Bản Khẩu Hiệu (Anti-Boilerplate Rule)

### 7.1. Cú pháp Markdown Relative Links:
- Sử dụng Markdown Relative Links khi tạo liên kết giữa các tài liệu trong dự án (ví dụ: `[System Architecture](../../02_basic_design/00_system_architecture.md)` hoặc `[Tech Stack](../00_common/tech_stack.md)`).
- Đây là thao tác kỹ thuật bắt buộc khi viết cú pháp liên kết.

### 7.2. Nghiêm cấm chèn văn bản khẩu hiệu và giải thích quy tắc AI (No Metatext / No Boilerplate):
- Mọi tài liệu kỹ thuật tập trung trực tiếp vào kiến trúc, nghiệp vụ và mã nguồn dự án.
- Tuyệt đối không đưa vào tài liệu bất kỳ đoạn văn bản boilerplate, khẩu hiệu hoặc câu tự thuật giải thích quy tắc nội bộ của AI (ví dụ: *"Toàn bộ liên kết trong thư mục `docs/` tuân thủ quy tắc đường dẫn tương đối...", "Tài liệu này tuân thủ cấu trúc 5 tầng...", "Đảm bảo tính toàn vẹn khi di chuyển hoặc sao chép mã nguồn mà không bao giờ bị gãy link..."*).
- Quy chuẩn kỹ thuật được tuân thủ bằng hành động cụ thể (viết đúng cú pháp đường dẫn, đúng cấu trúc thư mục), không tạo các mục văn bản tuyên bố quy tắc thừa thãi trong tài liệu dự án.

---

## 8. Pha 5: Hỏi Khởi Tạo Task Trong `04_tasks/`

Sau khi hoàn tất việc tạo hoặc cập nhật tài liệu trong `docs/`, Agent **BẮT BUỘC đưa ra câu hỏi xác nhận**:

> _"Tài liệu đặc tả cho tính năng `[Tên Tính Năng]` đã được cập nhật hoàn tất tại `docs/03_features/[tên_thư_mục]/`. Bạn có muốn tôi khởi tạo task tương ứng trong `docs/04_tasks/` để sẵn sàng theo dõi và triển khai không?"_

### Khi người dùng đồng ý:

1. Đọc `docs/04_tasks/` để lấy số thứ tự tiếp theo (ví dụ: `005_<ten_task>`).
2. Tạo thư mục `docs/04_tasks/<xxx_ten_task>/`.
3. Tạo `plan.md`:
   - Mục tiêu triển khai.
   - Danh sách các tệp tin cần tạo/chỉnh sửa.
   - Checklist từng bước chi tiết (Tasks breakdown) đối chiếu theo các `AC-xxx` trong spec.
   - Kế hoạch kiểm thử (Unit test, Integration test, Browser verification).
   - Nếu task sinh từ một thay đổi của tính năng cũ, ghi liên kết tới entry tương ứng trong `request-changes.md` ở đầu plan.
4. Tạo `state.md`:
   - Trạng thái hiện tại: `Pending` (Tiến độ: 0%).
   - Danh sách blockers hoặc các mục cần chuẩn bị trước.
5. Cập nhật `docs/04_tasks/backlog.md`.
6. Nếu vừa cập nhật một tính năng đã có, thay `Task: chưa tạo` trong entry mới nhất của `request-changes.md` bằng liên kết tương đối tới `docs/04_tasks/<xxx_ten_task>/plan.md`.
