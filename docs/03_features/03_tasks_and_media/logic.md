# Logic Design: Tasks & Media Management

## 1. Sequence Diagram — Vòng đời Task bất đồng bộ (Video / Async Image)

```mermaid
sequenceDiagram
    participant Client as Third-Party App
    participant API as FastAPI (/v1/videos)
    participant DB as SQLite (tasks)
    participant Worker as Async Task Runner

    Client->>API: POST /v1/videos
    API->>DB: INSERT task (status="queued")
    API->>Worker: Schedule background job
    API-->>Client: 200 {id: "tsk_...", status: "queued"}

    Worker->>DB: UPDATE task SET status="running"
    Worker->>Worker: Execute WSS chat.stream + subscribe + download /media/raw/...
    alt Success
        Worker->>DB: UPDATE task SET status="completed", media_filename="...", latency_ms=...
    else Error
        Worker->>DB: UPDATE task SET status="failed", error_message="..."
    end

    Client->>API: GET /v1/videos/tsk_...
    API->>DB: SELECT * FROM tasks WHERE id=?
    API-->>Client: 200 {status, url: "/v1/media/..."}
```

## 2. UI Event Handlers

| Phần tử UI | Sự kiện | API Endpoint | Tham số |
|---|---|---|---|
| Filter Type / Status | `onChange` | `GET /admin/tasks` | `?type=...&status=...&limit=50&offset=0` |
| `Delete` (Task) | `onClick` | `DELETE /admin/tasks/{id}` | `task_id` |
| `Clear Completed` | `onClick` | `POST /admin/tasks/clear` | `{}` |
| `Media Library` tab | `onSelect` | `GET /admin/media` | `{}` |
| `Delete` (Media) | `onClick` | `DELETE /admin/media/{name}` | `filename` |
