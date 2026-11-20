# Request changes: API Playground & Voice Preview Cache

## 2026-11-20 — Đồng bộ Fast CLI Prompt & chuẩn hóa âm lượng cục bộ cho Voice Preview

- **Yêu cầu:** Đồng bộ tối ưu tốc độ tạo voice (Fast Prompt chạy trực tiếp `/opt/hatch/bin/tts speak ... --text-stdin`) và chuyển bước chuẩn hóa âm lượng (`-16 LUFS`, true peak `-1.5 dB`) về xử lý cục bộ bằng `ffmpeg` cho luồng nghe thử Voice Preview khi cache miss hoặc `refresh=true`.
- **Phân loại:** Feature mở rộng
- **Đặc tả thay đổi:**
  - `spec.md`: chuyển trạng thái về `Ready for Implementation`; cập nhật `FR-501`; bổ sung `BR-507` và `AC-509`.
  - `logic.md`: cập nhật Sequence Diagram và Mục 4.3 (`build_speech_prompt` kèm `output_filename=tts-<task_id>.mp3`, `expected_output_filename` direct fallback, và `process_speech_audio(..., target_format="mp3")`).
- **Quyết định:** Áp dụng đồng nhất pipeline Fast Prompt và 2-pass `loudnorm` (`process_speech_audio` với cấu hình `MUSE2API_AUDIO_NORMALIZE`, graceful fallback khi thiếu `ffmpeg`) cho Voice Preview để tránh lệch âm lượng và giữ tốc độ sinh cache nhất quán với `POST /v1/audio/speech`.
- **Task:** [T-018](../../04_tasks/018_tts_fast_prompt_and_local_loudnorm/plan.md)
