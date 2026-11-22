# Actors & Permissions — Tác nhân & Phân quyền

## 1. Danh sách tác nhân

| Tác nhân                 | Mô tả                                                                            | Cơ chế xác thực                                                   |
| ------------------------ | -------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| **Admin Operator**       | Người vận hành hệ thống qua giao diện web ReactJS hoặc gọi trực tiếp `/admin/*`. | Không yêu cầu xác thực (truy cập mở).                             |
| **Third-Party Client**   | Ứng dụng bên thứ 3 (Cursor, OpenWebUI, script, bot...) gọi vào `/v1/*`.          | Bắt buộc header `Authorization: Bearer <API_KEY>`.                |
| **Background Scheduler** | Tiến trình nền nội bộ chạy định kỳ Keep-Alive và Media Cleanup.                  | Nội bộ hệ thống.                                                  |
| **Muse Cloud VM**        | Hạ tầng đích (`muse.ai` + `hatch.metaaivm.com/v1/noise`).                        | Cookie tài khoản + `authToken` + `noiseNotaryToken` + `Noise_XX`. |

## 2. Ma trận quyền truy cập

| Nhóm tài nguyên                                    | Admin Operator             | Third-Party Client                |
| -------------------------------------------------- | -------------------------- | --------------------------------- |
| `GET /` (React Console UI)                         | Cho phép                   | Không áp dụng                     |
| `/admin/*` (Accounts, Tasks, Settings, API Key)    | Toàn quyền                 | Không sử dụng                     |
| `/v1/*` (Chat, Image, Video, Audio, Models, Media) | Có thể gọi nếu kèm API Key | Được phép khi đúng Bearer API Key |
| `/healthz`, `/readyz`                              | Cho phép                   | Cho phép                          |
