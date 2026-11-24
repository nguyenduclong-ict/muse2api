# Logic Design: OpenAI-Compatible API & API Key

## 1. Sequence Diagram — Request qua WSS Noise Tunnel

```mermaid
sequenceDiagram
    participant App as Third-Party App
    participant API as FastAPI (/v1/*)
    participant Guard as Ref Media & SSRF Guard
    participant Pool as WSS Pool (LRU)
    participant VM as Muse Cloud VM (/v1/noise)
    participant AudioFmt as Local Audio Pipeline (ffmpeg)

    App->>API: POST /v1/* (Bearer m2a_...)
    API->>API: Verify raw_key in SQLite api_keys
    opt Có URL / Base64 / Multipart tham chiếu
        API->>Guard: Validate & fetch media (no private IP, <=10 items, <=40MiB/100MiB)
        Guard-->>API: list[(bytes, mime_type)]
    end
    opt Audio TTS (/v1/audio/speech)
        API->>API: preprocess_speech_text() + build Fast CLI prompt (tts-<task_id>.<ext>)
    end
    API->>Pool: wait_for_candidate(capability) / ensure_candidate_or_resetting(capability)
    alt Có account hỗ trợ đang resetting (Sync/SSE/Preview)
        Pool->>Pool: Wait on _reset_cond (max 150s, instant wakeup on end_reset)
    else Không có tài khoản hỗ trợ / hết quota / hết hạn chờ
        Pool-->>API: NoCandidateAccountError (503)
        API-->>App: 503 Service Unavailable (JSON error)
    end
    Pool->>VM: Stream N: POST /chat/stream (items, session_id)
    VM-->>Pool: 200 OK (session_id created)
    Pool->>VM: Stream N+1: POST /chat/subscribe (session_id)
    loop Streaming BodyChunks
        VM-->>Pool: event delta / task.status / delta.presentation
        Pool-->>API: Yield text delta or completion signal
        API-->>App: SSE chunk (chat.completion.chunk hoặc response.*)
    end
    opt Media Output (Image / Video / Audio)
        Pool->>VM: GET /chat/history?session_id=...
        alt Có resource trong history
            VM-->>Pool: resources[].path (/workspace/imagine_media/... hoặc your_files/tts-*.mp3)
            Pool->>VM: GET /media/raw/<path>
        else Audio chưa có resources[] trong history
            Pool->>VM: Direct fallback GET /media/raw/workspace/your_files/<expected_output_filename>
            Pool->>VM: Fallback GET /media/raw/your_files/<expected_output_filename>
        end
        VM-->>Pool: Binary BodyChunks
        Pool->>Pool: Save to data/media/<filename>
    end
    opt Audio TTS (/v1/audio/speech — mp3 / wav / url / json)
        API->>AudioFmt: process_speech_audio(path, target_fmt, normalize=cfg.audio_normalize)
        AudioFmt-->>API: (final_path, converted, normalized) + update tasks.media_filename
    end
    API-->>App: Final JSON (url/json) hoặc Binary audio (X-Audio-Converted, X-Audio-Normalized)
```

## 2. UI Event Handlers

| Phần tử UI             | Sự kiện   | API Endpoint                | Tham số                      |
| ---------------------- | --------- | --------------------------- | ---------------------------- |
| `Show / Hide`          | `onClick` | - (client state)            | Toggle mask/unmask `raw_key` |
| `Copy Key`             | `onClick` | - (clipboard)               | Copy `raw_key`               |
| `Rotate Key` (confirm) | `onClick` | `POST /admin/apikey/rotate` | `{}`                         |

## 3. Thuật toán xử lý bổ sung

1. **SSRF Guard cho Reference URL (`BR-104`):**
   - Kiểm tra scheme chỉ cho phép `http`/`https` (hoặc local file nếu `MUSE2API_REF_IMAGE_LOCAL_FILES=1`).
   - Phân giải DNS (`socket.getaddrinfo`) và kiểm tra mọi IP không thuộc `is_private`, `is_loopback`, `is_link_local`, `is_reserved`, `is_multicast` (trừ khi `MUSE2API_REF_IMAGE_PRIVATE_FETCH=1`).
   - Tắt redirect tự động (`allow_redirects=False`) hoặc kiểm tra lại IP ở mỗi hop; giới hạn tối đa 40 MiB/item và 100 MiB tổng.
2. **LRU, Lọc theo `supported_models`, Fail-Fast `503` & Giữ/Chờ khi Reset (`FR-105`, `BR-111`, `BR-112`):**
   - Ánh xạ `capability` từ loại lời gọi trong `WSSPool`:
     - `execute_chat` / `stream_chat_events` → `capability = "chat"`
     - `generate_media(..., expect_kind="image")` → `capability = "image"`
     - `generate_media(..., expect_kind="video")` → `capability = "video"`
     - `generate_media(..., expect_kind="audio")` → `capability = "speech"`
   - `_candidate_accounts(capability)`: lọc `enabled = 1`, `status in ('healthy', 'unknown', 'cooldown')`, `id not in _resetting_accounts`, `not is_quota_exhausted(quota_json)` và `capability in parse_supported_models(supported_models_json)`. Sắp xếp ưu tiên `status == 'healthy'` trước, sau đó tăng dần theo `last_used_at`.
   - `has_resetting_account(capability) -> bool`: kiểm tra xem có tài khoản nào thỏa `enabled = 1`, `not is_quota_exhausted(quota_json)`, `capability in parse_supported_models(supported_models_json)` và (`status == 'resetting'` hoặc `id in _resetting_accounts`) hay không.
   - `_no_candidate_error(capability)`:
     1. Lấy danh sách `enabled` có chứa `capability` trong `supported_models` (`matching_enabled`).
     2. Nếu `matching_enabled` rỗng → `"No enabled accounts support '<capability>'"`.
     3. Nếu toàn bộ `matching_enabled` đều hết quota (`is_quota_exhausted`) → `"All enabled accounts supporting '<capability>' have exhausted their quota"`.
     4. Ngược lại → `"No healthy enabled accounts available for '<capability>'"`.
   - **Cơ chế giữ & chờ trên `WSSPool` (`wait_for_candidate` & `ensure_candidate_or_resetting`):**
     - `ensure_candidate_or_resetting(capability) -> None`: dùng cho nhóm **Async Tasks** (`POST /v1/videos*`, `POST /v1/images/tasks`, `async=true` trên `/v1/images/*`). Nếu `_candidate_accounts(capability)` không rỗng thì cho qua ngay; nếu rỗng nhưng `has_resetting_account(capability)` là `True` và `cfg.reset_wait_timeout_seconds > 0` thì vẫn cho phép tạo task `status="queued"` và trả `200`; ngược lại ném `NoCandidateAccountError` → `503`.
     - `wait_for_candidate(capability, timeout: float | None = None) -> list[dict[str, Any]]`:
       1. Nếu `_candidate_accounts(capability)` không rỗng, trả về ngay.
       2. Tính `effective_wait = min(cfg.reset_wait_timeout_seconds, timeout)` nếu `timeout` dương, ngược lại dùng `cfg.reset_wait_timeout_seconds`. Nếu `effective_wait <= 0` hoặc `not has_resetting_account(capability)`, ném `NoCandidateAccountError` ngay.
       3. Dưới `self._lock`: kiểm tra `self._waiters_count >= cfg.reset_max_waiters`; nếu vượt ngưỡng, ném `NoCandidateAccountError("Too many requests waiting for account reset")` (`503`). Tăng `self._waiters_count += 1` trong `try/finally`.
       4. Trong vòng `while`: chờ trên `self._reset_cond.wait(timeout=min(1.0, remaining))` (được đánh thức tức thì khi `end_reset()` gọi `notify_all()`). Mỗi lần tỉnh dậy kiểm tra lại `_candidate_accounts(capability)` — có ứng viên thì trả về ngay; nếu `not self.has_resetting_account(capability)` hoặc hết `deadline` hoặc `self._stop.is_set()`, thoát sớm và ném `NoCandidateAccountError`.
     - **Router & Async Worker:**
       - Nhóm **Sync / SSE / Voice Preview** (`/v1/chat/completions`, `/v1/responses`, `/v1/images/generations` & `/v1/images/edits` với `async=false`, `/v1/audio/speech`, `/v1/audio/voices/{id}/preview`): gọi `pool.wait_for_candidate(capability, timeout=...)` trước khi mở `StreamingResponse` hoặc tạo task `running`. Trên các route `async def` (`images_edits`, `create_speech`, `preview_voice`), bắt buộc bọc qua `await run_in_threadpool(...)` để không khóa event loop.
       - Nhóm **Async Tasks**: `_run_async_media` giữ task ở trạng thái `"queued"`, gọi `pool.generate_media(...)` (bên trong tự chờ qua `wait_for_candidate`), cập nhật `status="running"` trong callback `on_account_selected` khi đã lấy được tài khoản, hoặc đánh dấu `"failed"` nếu ném `NoCandidateAccountError` / lỗi thực thi.
   - **Xử lý `AccountResettingError` & Chờ lại khi race giữa chừng:**
     - Định nghĩa `AccountResettingError(MuseWSSError)`. Trong `execute_chat`, `stream_chat_events` và `generate_media`, nếu `_track_in_flight(aid)` hoặc `get_client(aid)` ném `AccountResettingError`: bỏ qua `aid` sang ứng viên kế tiếp (không gọi `close_account(aid)`, không đặt `status="cooldown"`).
     - Nếu duyệt hết `candidates` trong lượt hiện tại mà vẫn chưa gửi chunk nào ra client và vẫn `has_resetting_account(capability)` (còn ngân sách thời gian chờ), gọi lại `wait_for_candidate(capability, timeout=remaining)` để lấy danh sách ứng viên mới sau reset.
     - Nếu `POST /chat/stream` lỗi `401`/timeout trước khi trả chunk đầu tiên, đánh dấu tài khoản và retry sang tài khoản hợp lệ kế tiếp trong cùng tập `candidates`.
   - **Cấu hình biến môi trường (`packages/backend/config.py` & `.env.example`):**
     - `MUSE2API_RESET_WAIT_TIMEOUT_SECONDS`: mặc định `"150"` (`float >= 0`, `0` = tắt chờ).
     - `MUSE2API_RESET_MAX_WAITERS`: mặc định `"50"` (`int >= 1`, giới hạn waiter đồng thời).
3. **SSE Format cho `/v1/responses`:**
   - Bắn lần lượt `event: response.created`, các `event: response.output_text.delta` theo `delta` từ `chat.subscribe`, và `event: response.completed` kèm full output.
4. **Danh mục Giọng, Lọc Ngôn ngữ Settings & Phân giải `voice` (`BR-106`, `BR-109`, `BR-110`):**
   - Nạp danh sách giọng một lần vào bộ nhớ từ `packages/backend/data/voices.json`, lọc bỏ `avocado_v2:p1a1_short` và chuẩn hóa các trường công khai (`id`, `name`, `gender`, `accent`, `tone`, `language`, `description`, `long_description`).
   - Xây dựng 2 chỉ mục tra cứu O(1): `by_id` (khớp chính xác) và `by_name_lower` (khớp không phân biệt hoa thường), cộng bảng `OPENAI_VOICE_ALIASES`:
     - `alloy` → `avocado_v2:MAI_01`
     - `echo` → `avocado_v2:MAI_03`
     - `fable` → `avocado_v2:isabella`
     - `onyx` → `avocado_v2:magnus`
     - `nova` → `avocado_v2:paloma`
     - `shimmer` → `avocado_v2:lumi`
   - Đọc cài đặt `voice_languages` từ SQLite (`db.get_settings().get("voice_languages")`): nếu `enabled == True` và danh sách `languages` sau chuẩn hóa (`normalize_voice_languages`, có tự động mở rộng `"English"` thành 13 nhóm `English (*)`) không rỗng, xác định tập cho phép `allowed_languages: set[str]` (lowercase) theo 31 nhóm chuẩn (`get_voice_language_group(v)` trong `services/voices.py`).
   - `GET /v1/audio/voices` (và `/v1/voices`):
     - Nếu `allowed_languages` khác rỗng: chỉ giữ các giọng có `get_voice_language_group(v).lower() in allowed_languages`.
     - Tiếp tục lọc giao (**AND**) theo query params của client: `gender`, `accent`, `tone` (case-insensitive exact match), `language` (khớp không phân biệt hoa thường với `v["language"]`, `get_voice_language_group(v)`, hoặc khớp toàn bộ 13 nhóm `English (*)` khi client truyền `language="English"`), và `q` (case-insensitive substring trên `id`, `name`, `accent`, `tone`, `description`, `long_description`).
   - `POST /v1/audio/speech`:
     - Phân giải `voice_info = resolve_voice(body.voice)` (trả `400` nếu không tồn tại trong catalog).
     - Nếu `allowed_languages` khác rỗng và `get_voice_language_group(voice_info).lower() not in allowed_languages`: trả ngay `400 Bad Request` (`invalid_request_error`) nêu rõ giọng `{voice_info['name']}` thuộc ngôn ngữ `{lang_group}` hiện không nằm trong danh sách ngôn ngữ được bật trong Settings (không fallback ngay cả khi client bỏ trống `voice`).
5. **Xây dựng Fast Prompt TTS, Tiền xử lý Tag, Tải Audio Fallback & Chuẩn hóa Âm lượng Cục bộ (`BR-107`, `BR-108`):**
   - **Kiểm tra đầu vào cơ bản:** `input` sau trim có độ dài `1..4096` ký tự và `response_format.lower() in {"mp3", "wav", "url", "json"}`; sai trả `400`.
   - **Tiền xử lý bracket tags cục bộ (`services/voice_preview.py::preprocess_speech_text(text: str, language: str) -> str`):**
     - Khớp mọi biểu thức dạng `[...]` không phân biệt hoa/thường (bỏ khoảng trắng thừa bên trong ngoặc trước khi đối chiếu bảng mapping):
       - Ngôn ngữ `"vi"`: `[laughs]` → `, hơ hơ,`; `[chuckles]`, `[giggles]` → `, hơ hơ,`; `[clears throat]` → `, ừm,`; `[sneezes]` → `Hắt xì!`.
       - Ngôn ngữ khác `"vi"`: `[laughs]` → `, haha,`; `[chuckles]`, `[giggles]` → `, heh,`; `[clears throat]` → `, hmm,`; `[sneezes]` → `Achoo!`.
       - Dùng chung mọi ngôn ngữ: `[sighs]` → `Haiz...`; `[gasps]` → `Huh!`; `[coughs]` → `Hm hm!`; `[pause]`, `[long pause]` → `...`.
       - Mọi `[tag]` khác (`[whispers]`, `[shouts]`, `[angry]`, `[sad]`, `[happy]`, `[excited]`, tag lạ): xóa bỏ hoàn toàn (`""`).
     - Sau khi thay/xóa, dọn khoảng trắng ngang liên tiếp, tránh khoảng trắng trước dấu phẩy (`,`) hoặc dấu phẩy lặp (`,,` / dấu phẩy mở đầu câu sau khi xóa tag đầu dòng), nhưng giữ nguyên ngắt dòng giữa các đoạn văn.
     - Nếu `preprocess_speech_text(...)` trả chuỗi rỗng sau trim (ví dụ `input="[whispers]"`), trả ngay `400 Bad Request` (`invalid_request_error`).
   - **Template Fast Prompt (`services/voice_preview.py::build_speech_prompt(..., output_filename: str | None = None)`):**
     - Tạo `task_id = f"aud_{secrets.token_hex(6)}"` trước khi dựng prompt; xác định `target_fmt = "wav" if fmt == "wav" else "mp3"` và tên file duy nhất `output_filename = f"tts-{task_id}.{target_fmt}"` (sanitize qua `os.path.basename` / chỉ cho phép `[a-zA-Z0-9._-]`, fallback sinh `tts-<hex>.<fmt>` nếu trống).
     - `language_code = get_voice_language_code(voice_info)` (mặc định `en`); `speed_pct` quy đổi hệ số `speed` sang phần trăm (mặc định `100`, vd `1.25` → `125`).
     - Tham số `instructions` được nhận ở schema API nhưng **bỏ qua** ở Fast Path (không chèn vào prompt và không fallback sang prompt đọc skill).
     - Ghép prompt nguyên văn theo mẫu sau (gửi với `skip_system_prompt=True`):
       ```text
       Generate an audio speech file using this exact command, do not read any skill files first:

       /opt/hatch/bin/tts speak --voice "{voice_id}" --language {lang} --speed {speed_pct} --format {fmt} --output ~/workspace/your_files/{safe_output_filename} --text-stdin

       Voice: {voice_name} ({voice_id})
       Language: {lang}
       Speed: {speed_pct}
       Format: {fmt}

       Text to speak (already converted, read exactly as written, no bracket tags left):
       {processed_text}
       ```
   - **Trích xuất Audio từ Muse & Direct Download Fallback (`WSSPool.generate_media` / `_fetch_media_from_history`):**
     - `generate_media(..., expected_output_filename: str | None = None)` truyền tên file kỳ vọng xuống `_fetch_media_from_history`.
     - Tại mỗi lượt kiểm tra `/chat/history`:
       1. Tìm trong `chat_events` (`resources[]` và `payload.data.audios/audio/files/...`) resource có `kind` chứa `"audio"` hoặc `mime_type` `audio/*` hoặc đuôi `.mp3`/`.wav`/`.ogg`/`.m4a`; nếu có nhiều mục, ưu tiên mục có path kết thúc bằng `expected_output_filename`.
       2. Nếu tìm thấy, tải qua `GET /media/raw/<media_path>`.
       3. Nếu lượt kiểm tra `/chat/history` chưa thấy resource audio nào và `expected_output_filename` khác rỗng, thử tải trực tiếp lần lượt:
          - `GET /media/raw/workspace/your_files/{expected_output_filename}`
          - `GET /media/raw/your_files/{expected_output_filename}`
            Nếu một trong hai trả `200 OK` với dữ liệu binary khác rỗng, lưu ngay vào `data/media/aud_<hex>.<ext>` mà không phải đợi retry hay báo lỗi `No audio resource produced`.
       4. Chỉ khi cả `/chat/history` lẫn direct fallback đều chưa có file mới `time.sleep(0.8)` rồi thử lại (tối đa 3 lượt).
   - **Pipeline hậu xử lý âm thanh cục bộ (`services/audio_format.py::process_speech_audio`):**
     - Signature: `process_speech_audio(file_path: str, target_format: str, *, normalize: bool = True, target_lufs: float = -16.0, true_peak: float = -1.5, lra: float = 11.0) -> tuple[str, bool, bool]` trả về `(final_path, was_converted, was_normalized)`.
     - Bước 1 — Kiểm tra định dạng: xác định `needs_convert = not matches_target_format(data, target_fmt)` (`RIFF...WAVE` PCM 16-bit cho `wav`; `ID3` hoặc MPEG sync frame cho `mp3`).
     - Bước 2 — Nếu `not normalize`:
       - Nếu `not needs_convert`: đổi tên nguyên tử sang `.<target_fmt>` nếu lệch phần mở rộng và trả `(dst_path, False, False)`.
       - Nếu `needs_convert`: gọi `convert_audio_file` (`pcm_s16le` hoặc `libmp3lame -qscale:a 2`), xóa nguồn cũ nếu khác tên và trả `(dst_path, True, False)`.
     - Bước 3 — Nếu `normalize == True`:
       - Tìm `ffmpeg` (`find_ffmpeg()`). Nếu không có `ffmpeg`:
         - Nếu `needs_convert`: ném `AudioConversionError` (router trả `502`).
         - Nếu `not needs_convert`: ghi log `WARNING`, đổi tên nguyên tử sang `.<target_fmt>` nếu cần và trả `(dst_path, False, False)` (Graceful fallback).
       - Chạy Pass 1 đo thông số loudness:
         `ffmpeg -y -hide_banner -i <src_path> -af loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}:print_format=json -f null -`
       - Xác định sample rate gốc `orig_sr`: ưu tiên đọc `wf.getframerate()` qua `wave.open` nếu đầu vào là WAV hợp lệ; ngược lại parse regex `(\d+)\s+Hz` từ `stderr` của Pass 1 (tránh chạy thêm tiến trình `ffprobe`).
       - Phân tích khối JSON từ `stderr` của Pass 1:
         - Nếu `input_i == "-inf"` (clip im lặng hoàn toàn): bỏ qua `loudnorm` (`normalized=False`); chỉ convert nếu `needs_convert`, ngược lại giữ file gốc (`(dst_path, False, False)`).
         - Nếu parse đủ `input_i`, `input_tp`, `input_lra`, `input_thresh`, `target_offset`: dựng bộ lọc Pass 2 2-pass linear:
           `loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}:measured_I={...}:measured_TP={...}:measured_LRA={...}:measured_thresh={...}:offset={...}:linear=true:print_format=summary`
         - Nếu không parse được JSON Pass 1 (nhưng không im lặng): fallback sang bộ lọc 1-pass `loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}`.
       - Chạy Pass 2 (gộp convert + normalize trong **1 lần encode duy nhất** qua file `.tmp` rồi `os.replace()`):
         - Luôn truyền `-ar {orig_sr}` (nếu xác định được `orig_sr > 0`) để ngăn `loudnorm` upsample nội bộ lên `192000 Hz`.
         - Codec đích: `pcm_s16le -f wav` (với `wav`) hoặc `libmp3lame -qscale:a 2 -f mp3` (với `mp3`).
       - Nếu Pass 1 hoặc Pass 2 lỗi thực thi `ffmpeg`: nếu `needs_convert` thì ném `AudioConversionError`; nếu `not needs_convert` thì ghi `WARNING` và fallback giữ file gốc (`(dst_path, False, False)`).
       - Khi ghi đích thành công, xóa file nguồn cũ nếu đường dẫn khác `dst_path`, trả `(dst_path, needs_convert, True)`.
   - **Cấu hình biến môi trường (`packages/backend/config.py` & `.env.example`):**
     - `MUSE2API_AUDIO_NORMALIZE`: mặc định `"1"` (`bool`, bật chuẩn hóa cục bộ).
     - `MUSE2API_AUDIO_TARGET_LUFS`: mặc định `"-16.0"` (`float`).
     - `MUSE2API_AUDIO_TRUE_PEAK`: mặc định `"-1.5"` (`float`).
     - `MUSE2API_AUDIO_LRA`: mặc định `"11.0"` (`float`).
   - **Hoàn tất phản hồi tại `POST /v1/audio/speech`:**
     - Áp dụng `process_speech_audio` với `target_fmt = "wav" if fmt == "wav" else "mp3"` cho **cả 4 chế độ** `response_format` (`mp3`, `wav`, `url`, `json`).
     - Cập nhật `tasks.media_filename` trong SQLite và `final_size` theo tệp sau xử lý.
     - Với `mp3`/`wav`, trả `FileResponse` (`audio/mpeg` hoặc `audio/wav`) kèm header `X-Muse-Media-Url: /v1/media/<filename>`, `X-Audio-Converted: 0|1`, và `X-Audio-Normalized: 0|1`. Với `url`/`json`, trả JSON metadata trỏ tới `/v1/media/<filename>` đã chuẩn hóa.
