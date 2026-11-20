# State: Task 018 — Tối ưu TTS Fast CLI Prompt & Chuẩn hóa âm lượng cục bộ (`ffmpeg loudnorm`)

- **Trạng thái:** `Completed`
- **Tiến độ:** 100%
- **Ngày tạo:** `2026-11-20`
- **Ngày hoàn thành:** `2026-11-20`
- **Blockers:** Không có.

## Nhật ký thực hiện
- 2026-11-20: Khởi tạo kế hoạch triển khai từ đặc tả [02_openai_api_and_keys/spec.md](../../03_features/02_openai_api_and_keys/spec.md), [06_api_playground/spec.md](../../03_features/06_api_playground/spec.md) và các entry `2026-11-20` trong `request-changes.md`.
- 2026-11-20: Hoàn thành cập nhật cấu hình (`packages/backend/config.py`, `.env.example`), pipeline `process_speech_audio` (`packages/backend/services/audio_format.py`), tiền xử lý tag + Fast CLI Prompt + Voice Preview (`packages/backend/services/voice_preview.py`), direct download fallback (`packages/backend/services/wss_pool.py`), và endpoint `POST /v1/audio/speech` (`packages/backend/routers/v1_openai.py`).
- 2026-11-20: Cập nhật và chạy unit/integration tests trên cả Windows host lẫn trong Docker container `muse2apiv2`: `test_voice_preview_cache.py`, `test_task_input_request.py`, `test_account_supported_models.py`, `test_db_resilience.py` (31/31 passed); `test_audio_voices_and_speech.py` (30/31 passed, 1 pre-existing failure `test_is_voice_allowed_and_filter`: 23 != 13 ngoài phạm vi task).
- 2026-11-20: Rebuild & restart `docker compose up -d --build` (`http://127.0.0.1:9123/healthz` trả `ok`) và kiểm chứng `process_speech_audio` với FFmpeg 7.1.5 thật trong container `muse2apiv2` (WAV 24000 Hz từ `-34.15 LUFS` được chuẩn hóa về `-16.05 LUFS`, giữ nguyên `24000 Hz` PCM16; chuyển đổi + chuẩn hóa sang MP3 đạt `-16.05 LUFS`).
