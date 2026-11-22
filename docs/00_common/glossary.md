# Glossary — Từ điển thuật ngữ

| Thuật ngữ                | Định nghĩa                                                                                                                                                                                                |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Muse Cloud VM**        | Máy ảo đám mây (`<vm_id>.metaaivm.com`) cấp riêng cho mỗi tài khoản `muse.ai`, xử lý chat, sinh ảnh/video và TTS. Tên miền này không phân giải qua DNS công cộng mà chỉ truy cập qua đường hầm Noise WSS. |
| **HTTP Bootstrap**       | Bước gọi `GET https://muse.ai/thread/new` kèm cookie để trích xuất `__HATCH_GATEWAY_INIT__` (`vmName`, `authToken`, `noiseNotaryToken`, `attestationTier`).                                               |
| **Noise Tunnel**         | Kết nối WebSocket nhị phân tới `wss://hatch.metaaivm.com/v1/noise` sử dụng giao thức `Noise_XX_25519_AESGCM_SHA256` để mã hóa đầu-cuối toàn bộ RPC và media.                                              |
| **Stream ID**            | Định danh `int64` tăng dần trong `ServiceFrame`, cho phép gửi/nhận nhiều request HTTP-over-Noise song song trên cùng một kết nối WSS.                                                                     |
| **Account Pool**         | Tập hợp các tài khoản `muse.ai` đang bật (`enabled=true`) và khỏe mạnh (`healthy`), được điều phối theo thuật toán LRU round-robin.                                                                       |
| **Keep-Alive**           | Tác vụ chạy nền định kỳ gọi `/api/session` (gia hạn cookie) và `/api/hatch/vm/wake` (đánh thức VM) để duy trì phiên hoạt động liên tục.                                                                   |
| **Client API Key**       | Khóa Bearer duy nhất (`m2a_...`) lưu dạng raw trong SQLite để xác thực các ứng dụng bên thứ 3 gọi vào `/v1/*`.                                                                                            |
| **Global System Prompt** | Đoạn chỉ dẫn hệ thống tùy chọn được gắn tự động vào đầu prompt của mọi request qua `/v1/*` khi tính năng được bật.                                                                                        |
