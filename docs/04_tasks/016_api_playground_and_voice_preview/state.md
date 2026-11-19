# State: Task 016 — API Playground & Voice Preview Cache

- **Trạng thái:** `Completed`
- **Tiến độ:** 100%
- **Ngày tạo:** `2026-11-19`
- **Ngày hoàn thành:** `2026-11-19`
- **Blockers:** Không có.

## Nhật ký thực hiện
- 2026-11-19: Khởi tạo kế hoạch triển khai từ đặc tả [06_api_playground/spec.md](../../03_features/06_api_playground/spec.md).
- 2026-11-19: Hoàn thành Backend `config.py` (`voice_preview_dir`), `services/voice_preview.py` (chuẩn hóa tên file, bảng câu mẫu theo 31 nhóm ngôn ngữ, in-flight lock, atomic write, task logging), mở rộng `routers/v1_openai.py` (`GET /v1/audio/voices/{id}/preview`, `GET /v1/voice-previews/{filename}`), và `routers/admin_core.py`.
- 2026-11-19: Hoàn thành Frontend `Layout.tsx` (thêm link Sidebar Playground), `App.tsx` (route `/playground`), `ApiKeysPage.tsx` (cập nhật schema docs), và `PlaygroundPage.tsx` (4 tab Chat, Images, Video, Audio & Voices, cURL inspector, single Preview/Use button).
- 2026-11-19: Kiểm thử tự động `test_voice_preview_cache.py` cùng toàn bộ test suite backend (32/32 tests PASS). Build frontend `npm run build` thành công 100% không lỗi. Xác minh trình duyệt thực tế thành công qua browser subagent.
- 2026-11-19: Tối ưu UX giao diện theo phản hồi: Mở rộng cột điều khiển bên trái từ 25% (`lg:col-span-1`) lên ~42% (`lg:col-span-5 xl:col-span-5 2xl:col-span-4`) trên cả 3 tab Video, Images và Chat; nâng Voice Catalog lên 58% (`lg:col-span-7`) ở tab Audio & Voices; đồng thời mở rộng Sidebar chính từ 240px (`w-60`) lên 256px (`w-64`) để toàn bộ console đạt độ cân bằng và tiện dụng cao nhất. Đã build và verify thành công qua browser subagent.
- 2026-11-19: Bảo toàn danh mục 280 giọng tiêu biểu của dự án trong `packages/backend/data/voices.json`. Trả tường minh trường `long_description` trong endpoint `GET /v1/audio/voices` (`/v1/voices`) phục vụ agent; cập nhật tài liệu mẫu trên `ApiKeysPage.tsx`; bổ sung hiển thị `long_description` trực quan trên bảng Voice Catalog và thẻ mô tả Selected Voice trong `PlaygroundPage.tsx`; cập nhật toàn bộ test suite `test_audio_voices_and_speech.py`, `test_voice_preview_cache.py`, `test_account_supported_models.py` (32/32 tests PASS). Build frontend đạt 100% không lỗi. Backend daemon khởi động lại thành công trên cổng 18610.
