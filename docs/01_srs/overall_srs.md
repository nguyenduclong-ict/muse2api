# Overall SRS — Đặc tả yêu cầu tổng quan

## 1. Bối cảnh & Mục tiêu
`muse2api` phiên bản 1 điều khiển `muse.ai` thông qua Chromium headless + CDP + DOM manipulation, dẫn đến tiêu tốn nhiều RAM/CPU và dễ bị ảnh hưởng khi giao diện web thay đổi.

`muse2apiv2` là phiên bản độc lập viết lại hoàn toàn phần lõi giao tiếp bằng **Python WSS + Noise Protocol (`Noise_XX_25519_AESGCM_SHA256`)**, không sử dụng trình duyệt headless, kết hợp giao diện quản trị **ReactJS + shadcn/ui**.

## 2. Phạm vi hệ thống (Scope)

### Trong phạm vi (In Scope)
- **Quản lý tài khoản:** Import từ cookie, xem/cập nhật trạng thái, kiểm tra quota, bật/tắt, cấu hình proxy riêng, chạy keep-alive tự động và thủ công.
- **API Endpoint `/v1/*`:** Cung cấp đầu API tương thích OpenAI cho ứng dụng bên thứ 3 (Chat, Responses, Image Generation/Edit/Tasks, Video Generation/Polling, Text-to-Speech, Models, Media).
- **Quản lý API Key:** 1 API Key duy nhất cho `/v1/*`, lưu raw trong DB để xem lại, copy và xoay key.
- **Quản lý Tasks:** Theo dõi lịch sử, trạng thái, kết quả media và xóa/dọn task.
- **Cài đặt:** Global System Prompt và Media Cleanup tự động/thủ công.

### Ngoài phạm vi (Out of Scope)
- Tự động đăng nhập bằng tài khoản/mật khẩu hoặc giải CAPTCHA.
- Xác thực đăng nhập cho trang quản trị (Console UI & `/admin/*` mở trực tiếp theo yêu cầu).
- Hỗ trợ đa người dùng / phân quyền nhiều Admin.
