# Task 018: Tối ưu TTS Fast CLI Prompt & Chuẩn hóa âm lượng cục bộ (`ffmpeg loudnorm`)

- **Liên kết Change Request:**
  - [2026-11-20 — Tối ưu tốc độ tạo voice (Fast CLI Prompt, chuyển đổi tag cục bộ) & Chuẩn hóa âm lượng tại local](../../03_features/02_openai_api_and_keys/request-changes.md)
  - [2026-11-20 — Đồng bộ Fast CLI Prompt & chuẩn hóa âm lượng cục bộ cho Voice Preview](../../03_features/06_api_playground/request-changes.md)
- **Liên kết Spec:**
  - [02_openai_api_and_keys/spec.md](../../03_features/02_openai_api_and_keys/spec.md), [02_openai_api_and_keys/logic.md](../../03_features/02_openai_api_and_keys/logic.md)
  - [06_api_playground/spec.md](../../03_features/06_api_playground/spec.md), [06_api_playground/logic.md](../../03_features/06_api_playground/logic.md)
- **Mục tiêu:** Cắt giảm ~15–20s độ trễ đọc skill trên Muse agent khi tạo voice TTS bằng Fast CLI Prompt (`/opt/hatch/bin/tts speak ... --text-stdin`), chuyển đổi/loại bỏ bracket tags ở backend, sinh `--output` duy nhất `tts-<task_id>.<ext>` kèm direct download fallback `/media/raw/workspace/your_files/<filename>`, và chuyển toàn bộ bước chuẩn hóa âm lượng (`-16 LUFS`, true peak `-1.5 dB`, giữ sample rate gốc) về xử lý cục bộ bằng `ffmpeg` 2-pass `loudnorm` cho cả `POST /v1/audio/speech` (mọi format `mp3`, `wav`, `url`, `json`) lẫn `GET /v1/audio/voices/{voice_id}/preview`.

## Danh sách tệp cần tạo / chỉnh sửa

- **Cấu hình:**
  - `packages/backend/config.py`: thêm `audio_normalize`, `audio_target_lufs`, `audio_true_peak`, `audio_lra`.
  - `.env.example`: ghi tài liệu 4 biến môi trường `MUSE2API_AUDIO_*`.
- **Backend Services & Router:**
  - `packages/backend/services/audio_format.py`: bổ sung `process_speech_audio` (xác thực định dạng + 2-pass `loudnorm` linear giữ sample rate gốc, fallback 1-pass, bỏ qua clip im lặng, graceful fallback khi thiếu `ffmpeg`).
  - `packages/backend/services/voice_preview.py`: bổ sung `preprocess_speech_text`, `sanitize_output_filename`, cập nhật `build_speech_prompt` sang Fast CLI Prompt, và cập nhật `VoicePreviewService.get_or_generate_preview` dùng Fast Prompt + `process_speech_audio(..., "mp3")`.
  - `packages/backend/services/wss_pool.py`: bổ sung `expected_output_filename` cho `generate_media` & `_fetch_media_from_history` kèm direct download fallback `/media/raw/workspace/your_files/<filename>` và `/media/raw/your_files/<filename>`.
  - `packages/backend/routers/v1_openai.py`: tiền xử lý text sớm (400 nếu rỗng sau bỏ tag), sinh `tts-<task_id>.<ext>`, chạy `process_speech_audio` cho cả 4 `response_format` (`mp3`, `wav`, `url`, `json`) và trả header `X-Audio-Normalized: 0|1`.
- **Tests:**
  - `packages/backend/tests/test_audio_voices_and_speech.py`
  - `packages/backend/tests/test_voice_preview_cache.py`
  - `packages/backend/tests/test_task_input_request.py`

## Checklist triển khai (đối chiếu AC)

- [x] **Bước 1 — Cấu hình biến môi trường (`FR-112`, `BR-107`):**
  - Thêm `audio_normalize`, `audio_target_lufs`, `audio_true_peak`, `audio_lra` vào `packages/backend/config.py`.
  - Cập nhật `.env.example` với `MUSE2API_AUDIO_NORMALIZE=1` và các tham số tùy chọn.
- [x] **Bước 2 — Pipeline chuẩn hóa âm lượng cục bộ (`AC-116`, `BR-107`):**
  - Cài đặt `process_speech_audio` và các helper (`_get_wav_sample_rate`, `_parse_sample_rate_from_ffmpeg_stderr`, `_parse_loudnorm_stats`, `_measure_loudnorm`, `_encode_audio_file`) trong `packages/backend/services/audio_format.py`.
  - Đảm bảo gộp convert + 2-pass `loudnorm` trong 1 lần encode nguyên tử, giữ `-ar <orig_sr>`, fallback 1-pass, bỏ qua clip im lặng, và graceful fallback khi thiếu `ffmpeg` nếu đúng định dạng.
- [x] **Bước 3 — Tiền xử lý Tag, Fast CLI Prompt & Voice Preview (`AC-115`, `AC-509`, `BR-107`, `BR-108`, `BR-507`):**
  - Cài đặt `preprocess_speech_text` (chuyển tag phát âm theo `vi` / non-`vi`, xóa sạch mọi tag khác, dọn khoảng trắng) và `sanitize_output_filename` trong `packages/backend/services/voice_preview.py`.
  - Cập nhật `build_speech_prompt` sang Fast CLI Prompt (`do not read any skill files first`, bỏ `instructions`, bỏ `normalize to -16 LUFS`).
  - Cập nhật `VoicePreviewService.get_or_generate_preview` truyền `tts-<task_id>.mp3`, `expected_output_filename`, và xử lý qua `process_speech_audio(..., "mp3")`.
- [x] **Bước 4 — Direct Download Fallback & Router `/v1/audio/speech` (`AC-115`, `AC-116`, `AC-117`, `FR-112`):**
  - Cập nhật `WSSPool.generate_media` & `_fetch_media_from_history` hỗ trợ `expected_output_filename` và tải trực tiếp `/media/raw/workspace/your_files/<filename>` / `/media/raw/your_files/<filename>`.
  - Cập nhật `create_speech` trong `packages/backend/routers/v1_openai.py` kiểm tra rỗng sau bỏ tag (`400`), chạy `process_speech_audio` cho cả 4 `response_format`, và trả `X-Audio-Normalized: 0|1`.
- [x] **Bước 5 — Kiểm thử tự động & FFmpeg 7.1.5 thật trong Docker (`AC-115`, `AC-116`, `AC-117`, `AC-509`):**
  - Cập nhật và chạy unit/integration tests trên backend.
  - Rebuild/restart `docker compose up -d --build` và kiểm chứng `process_speech_audio` với FFmpeg 7.1.5 thật bên trong container `muse2apiv2` (WAV PCM16 giữ nguyên 24000 Hz, `-16 LUFS`, `TP <= -1.5 dB`, và MP3 hợp lệ).

## Kế hoạch kiểm thử

1. **Unit & Integration Tests (`unittest`):**
   - Kiểm tra `preprocess_speech_text` với tag `vi` / non-`vi`, tag lạ bị xóa, trường hợp chỉ có tag trả chuỗi rỗng → `400`.
   - Kiểm tra `build_speech_prompt` dùng Fast CLI, unique `tts-<task_id>.<ext>`, bỏ qua `instructions`, không chứa `normalize to -16 LUFS`.
   - Kiểm tra `process_speech_audio`: 2-pass `loudnorm` giữ `-ar <orig_sr>`, fallback 1-pass, im lặng `input_i == "-inf"`, `normalize=False`, graceful fallback thiếu `ffmpeg`, lỗi `502` khi cần convert mà thiếu `ffmpeg`.
   - Kiểm tra `WSSPool._fetch_media_from_history` ưu tiên khớp `expected_output_filename` và fallback tải trực tiếp `/media/raw/workspace/your_files/<expected>` / `/media/raw/<expected>`.
   - Kiểm tra `POST /v1/audio/speech` chạy `process_speech_audio` cho cả `mp3`, `wav`, `url`, `json` và trả `X-Audio-Normalized`; kiểm tra `VoicePreviewService` (`AC-509`).
2. **Real FFmpeg Verification (Docker `muse2apiv2`):**
   - Sinh WAV 24000 Hz 16-bit PCM sine wave nhỏ (-30 dBFS) trong container và chạy `process_speech_audio` sang `wav` và `mp3`; đo lại loudness và sample rate đầu ra.
