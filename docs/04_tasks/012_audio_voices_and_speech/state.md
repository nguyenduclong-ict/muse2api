# State: Task 012 — Audio Voices & Speech (TTS) Endpoints + Console Support

- **Trạng thái:** `Completed`
- **Tiến độ:** 100%
- **Ngày cập nhật:** `2026-11-19`

## Nhật ký thực hiện

1. **Bước 1 — Data & Service:**
   - Trích xuất 1218 giọng sạch từ danh mục vào [voices.json](../../packages/backend/data/voices.json), loại bỏ giọng nội bộ `avocado_v2:p1a1_short` và các trường chấm điểm nội bộ.
   - Xây dựng [voices.py](../../packages/backend/services/voices.py) với bộ lọc linh hoạt và bảng ánh xạ alias OpenAI (`alloy`, `echo`, `fable`, `onyx`, `nova`, `shimmer`).
2. **Bước 2 — Hạ tầng WSS:**
   - Cập nhật [wss_pool.py](../../packages/backend/services/wss_pool.py) nhận cờ `skip_system_prompt` để tách biệt prompt TTS khỏi chat prompt.
   - Mở rộng hàm `_fetch_media_from_history` hỗ trợ nhận diện và tải binary audio `.mp3` (`audio/mpeg`).
3. **Bước 3 — Backend API:**
   - Cập nhật [v1_openai.py](../../packages/backend/routers/v1_openai.py): bổ sung model aliases `muse-tts`, `tts-1`, `tts-1-hd`, `gpt-4o-mini-tts`.
   - Thêm `GET /v1/audio/voices` (và alias `/v1/voices`) có phân quyền Bearer key và lọc metadata.
   - Thêm `POST /v1/audio/speech`: xác thực đầu vào, định dạng prompt bảo toàn emotion cues (`[laughs]`, `[sighs]`, v.v.), hỗ trợ `response_format` binary `audio/mpeg` và JSON `url`, ghi nhận task `audio` vào DB.
4. **Bước 4 — Frontend Console:**
   - Cập nhật [ApiKeysPage.tsx](../../packages/frontend/src/pages/ApiKeysPage.tsx): bổ sung documentation collapsible cho cả 2 endpoints mới.
   - Cập nhật [TasksMediaPage.tsx](../../packages/frontend/src/pages/TasksMediaPage.tsx): thêm filter task type `audio`, hiển thị icon `Music` trong bảng Media và trình phát `<audio controls>` trong modal Preview.
   - Cập nhật [.gitignore](../../.gitignore) để theo dõi `packages/backend/data/voices.json`.
5. **Bước 5 — Kiểm thử & Nghiệm thu:**
   - Tạo bộ test tự động [test_audio_voices_and_speech.py](../../packages/backend/tests/test_audio_voices_and_speech.py) với 11 test cases kiểm tra catalog, prompt builder, authentication, validations (400), và mocked execution cho cả 2 response formats (`mp3` và `url`). Toàn bộ 11/11 tests chạy qua và đạt 100% OK.
   - Chạy build frontend `tsc -b && vite build` hoàn thành không lỗi.
