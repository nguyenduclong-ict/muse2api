# State: Task 013 — Voice Languages Filter (Settings & TTS Voices/Speech)

- **Trạng thái:** `Completed`
- **Tiến độ:** 100%
- **Ngày hoàn thành:** `2026-11-19`

## Nhật ký thực hiện

1. **Bước 1 — Voices Service (Phân nhóm 18 Ngôn ngữ & Bộ lọc):**
   - Đã ánh xạ toàn bộ 36 `accent` và mã `fra` thành 18 nhóm ngôn ngữ chuẩn (`English` 1,000, `French` 35, `Indian` 26, `Finnish` 20, `Indonesian` 18, `Spanish` 14, `German` 13, `Arabic` 11, `Portuguese` 11, `Filipino` 10, `Malaysian` 10, `Chinese` 9, `Russian` 9, `Italian` 8, `Thai` 7, `Vietnamese` 7, `Japanese` 6, `Korean` 4), tổng đúng 1,218 giọng.
   - Thêm `list_available_voice_languages`, `normalize_voice_languages`, `is_voice_allowed`.
   - Cập nhật `list_voices(...)` nhận `allowed_languages` và mở rộng query `?language=` khớp cả mã gốc lẫn tên nhóm ngôn ngữ.
2. **Bước 2 — Database & Admin Settings API:**
   - Cập nhật [db.py](../../packages/backend/db.py): default `voice_languages = {"enabled": False, "languages": []}`.
   - Cập nhật [admin_core.py](../../packages/backend/routers/admin_core.py): `GET /admin/settings` trả `available_voice_languages` và `voice_languages`; `POST /admin/settings` nhận `voice_languages`, chuẩn hóa và lưu SQLite.
3. **Bước 3 — Áp dụng lọc trên `/v1/audio/voices` & `/v1/audio/speech`:**
   - Cập nhật [v1_openai.py](../../packages/backend/routers/v1_openai.py):
     - `GET /v1/audio/voices`: tự động nạp `allowed_languages` từ DB và lọc giao AND với client query.
     - `POST /v1/audio/speech`: chặn `400 Bad Request` nếu giọng không thuộc ngôn ngữ được bật trong Settings (**không fallback**, kể cả khi client bỏ trống `voice`).
4. **Bước 4 — Giao diện Settings Console:**
   - Cập nhật [SettingsPage.tsx](../../packages/frontend/src/pages/SettingsPage.tsx): thêm card **Voice Languages** có Switch, lưới 18 ngôn ngữ kèm bộ đếm giọng, thống kê số ngôn ngữ & giọng cho phép, nút Select All, Clear, Save.
5. **Bước 5 — Kiểm thử tự động & Build:**
   - Cập nhật [test_audio_voices_and_speech.py](../../packages/backend/tests/test_audio_voices_and_speech.py): toàn bộ 17/17 test cases đều PASS 100%.
   - Chạy `npm --prefix packages/frontend run build` hoàn thành không lỗi.
