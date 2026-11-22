# Request changes: Settings & Media Cleanup

## 2026-11-22 — Bổ sung cấu hình toàn cục Auto Reset Muse (`auto_reset`)

- **Yêu cầu:** Thêm cấu hình định kỳ đặt lại Muse toàn cục (`enabled`, `interval_minutes`) trên trang Settings và nút kích hoạt chạy ngay cho các tài khoản đến hạn.
- **Phân loại:** Feature mở rộng
- **Đặc tả thay đổi:**
  - `spec.md`: cập nhật `Mục tiêu & Bối cảnh`, `Phạm vi`; bổ sung `FR-305`, `BR-305`, `AC-305`.
  - `design.md`: bổ sung card **Auto Reset Muse** trên màn hình `SCR-05`.
  - `logic.md`: cập nhật Sequence Diagram, bảng `UI Event Handlers` và thêm mục validate/khởi tạo `settings.auto_reset`.
  - `../../02_basic_design/02_database/schema_summary.md`: bổ sung key `auto_reset` vào mô tả bảng `settings`.
- **Quyết định:** Lưu theo khoảng thời gian lặp lại (`interval_minutes`, mặc định `1440` phút = 24 giờ, kẹp tối thiểu `60` phút ở backend) đồng nhất với `media_cleanup`; giữ `enabled = false` mặc định để Admin chủ động kích hoạt.
- **Task:** [T-019](../../04_tasks/019_muse_reset_and_auto_reset/plan.md)

## 2026-11-19 — Tách nhóm `English (1,000)` theo từng quốc gia (31 nhóm chuẩn)

- **Yêu cầu:** Tách nhóm `English` (1,000 giọng) ra theo từng quốc gia nói tiếng Anh để admin kiểm soát chi tiết hơn trên Settings thay vì gom chung 1,000 giọng.
- **Phân loại:** Feature mở rộng
- **Đặc tả thay đổi:**
  - `spec.md`: cập nhật `FR-304`, `BR-303` (18 nhóm → 31 nhóm gồm 13 quốc gia Tiếng Anh + 17 ngôn ngữ/quốc gia khác + `Other`), `BR-304` (tương thích ngược expand `"English"`), `AC-303`, `AC-304`.
  - `design.md`: cập nhật wireframe card **Voice Languages** hiển thị 31 mục.
  - `logic.md`: cập nhật Mục 4 cho bảng 31 nhóm và cơ chế mở rộng tương thích ngược `"English"`.
- **Quyết định:** Tách `English` thành 13 quốc gia (gom các giọng vùng miền trong cùng một nước như `American` + `Southern American` + `New York` + `Mid-Atlantic` → `English (US)` 541; `British` + `Scottish` → `English (UK)` 200), giữ gộp `French` (35), đưa `Transylvanian` (1) vào `Other`, và tự động expand `"English"` từ DB cũ thành đủ 13 nhóm `English (*)`. Loại bỏ phương án tách phẳng 36 accent lẻ để giao diện gọn hơn.
- **Task:** [T-015](../../04_tasks/015_voice_languages_by_country/plan.md)

## 2026-11-19 — Bổ sung cài đặt lọc ngôn ngữ giọng đọc TTS (`voice_languages`)

- **Yêu cầu:** Cho phép admin cấu hình danh sách ngôn ngữ giọng đọc muốn hỗ trợ trên màn hình Settings (ví dụ chọn Tiếng Anh, Tiếng Việt, Tiếng Nhật) để các endpoint TTS chỉ cung cấp giọng thuộc các ngôn ngữ đó.
- **Phân loại:** Feature mở rộng
- **Đặc tả thay đổi:**
  - `spec.md`: mở rộng phạm vi; thêm `FR-304`, `BR-303`, `BR-304`, `AC-303`, `AC-304`.
  - `design.md`: bổ sung card **Voice Languages** trên màn hình Settings (`SCR-05`) kèm danh sách 18 ngôn ngữ, bộ đếm giọng và các nút thao tác.
  - `logic.md`: cập nhật Sequence Diagram, bảng UI Event Handlers và thuật toán phân nhóm/chuẩn hóa 18 nhóm ngôn ngữ.
  - `../../02_basic_design/02_database/schema_summary.md`: bổ sung key `voice_languages` vào bảng `settings`.
- **Quyết định:** Gom 36 giá trị `accent` (cùng `language="fra"`) trong `voices.json` thành 18 nhóm ngôn ngữ chuẩn bao phủ đủ 1,218 giọng; giữ công tắc bật/tắt `enabled` mặc định `false` và quy ước tắt hoặc chọn rỗng `[]` nghĩa là cho phép toàn bộ giọng. Loại bỏ phương án chọn lẻ 36 accent gốc để tránh thao tác phức tạp khi bật Tiếng Anh.
- **Task:** [T-013](../../04_tasks/013_voice_languages_filter/plan.md)
