[[ navbar | muse2apiv2 | Overview | Accounts | API & Keys* | Tasks & Media | Settings ]]

::: columns-2
::: column Sidebar {span-1}
- Overview
- Accounts
- **API & Keys**
- Tasks & Media
- Settings
:::

::: column Main Content {span-4}
# API Endpoint & Client Key

::: card Third-Party API Key (OpenAI Compatible)
**Base URL:** `http://localhost:18610/v1`

[API Key___]{value:"m2a_7f9a2c4e8b1d..." readonly}
::: row {left}
[Show / Hide]{outline} [Copy Key]{outline} [Rotate Key]{danger}
:::
> Single key stored in SQLite for third-party integrations. Rotating invalidates the previous key immediately.
:::

::: card Supported Endpoints
| Endpoint | Protocol | Streaming | Status |
|---|---|---|---|
| `POST /v1/chat/completions` | Chat Completions | SSE | ((Ready)){success} |
| `POST /v1/responses` | Responses API | SSE | ((Ready)){success} |
| `POST /v1/images/generations` | Images (Sync/Async) | - | ((Ready)){success} |
| `POST /v1/videos` | Video Tasks | Polling | ((Ready)){success} |
| `POST /v1/audio/speech` | Text-to-Speech | Binary | ((Ready)){success} |
:::

::: card Quick Integration Example
[cURL Snippet___]{rows:5 readonly value:"curl -X POST http://localhost:18610/v1/chat/completions -H 'Authorization: Bearer m2a_...' ..."}
:::
:::
:::
