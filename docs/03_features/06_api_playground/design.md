[[ navbar | muse2apiv2 | Overview | Accounts | Proxies | API & Keys | Playground* | Tasks & Media | Settings ]]

::: columns-2
::: column Sidebar {span-1}
- Overview
- Accounts
- Proxies
- API & Keys
- **Playground**
- Tasks & Media
- Settings
:::

::: column Main Content {span-4}
# API Playground
Test `/v1/*` OpenAI-compatible endpoints live and preview cached TTS voices.

::: tabs
::: tab Chat
::: columns-2
::: column Controls {span-1}
::: card Request Settings
Endpoint
- (*) Chat Completions (`/v1/chat/completions`)
- ( ) Responses (`/v1/responses`)

Model
[muse-spark v]

- [x] Stream (SSE)

System / Instructions
[Optional system prompt...___]{rows:3}

Reference Image (optional)
[https://... or upload___] [Upload]{outline}

[Clear Chat]{outline}
:::
:::

::: column Conversation {span-3}
::: card Chat Output
**User:** Explain WebSocket keep-alive in 2 sentences.

**Assistant:** WebSocket keep-alive periodically sends lightweight ping frames so idle connections are not dropped by NATs or proxies. It also detects broken peers early so the client can reconnect cleanly.

---
[Type your message...___]{rows:2}
::: row {right}
[Stop]{danger} [Send]{primary}
:::
:::

::: card cURL & Raw Response
`curl -X POST http://localhost:18610/v1/chat/completions -H "Authorization: Bearer ***" ...`
::: row {right}
[Show Key]{ghost} [Copy cURL]{outline}
:::
:::
:::
:::
:::

::: tab Images
::: columns-2
::: column Controls {span-1}
::: card Image Parameters
Mode
- (*) Generations (`/v1/images/generations`)
- ( ) Edits (`/v1/images/edits`)

Prompt
[A neon cyberpunk cat in rain...___]{rows:4}

Aspect Ratio / Size
[16:9 v]

Response Format
[url v]

- [ ] Async task mode

Reference Image (required for Edits)
[Drop or choose image file___] [Upload]{outline}

[Generate Image]{primary}
:::
:::

::: column Result {span-3}
::: card Generated Image
((Completed · 4.2s · 16:9)){success}

[ Image Preview Canvas ]

::: row {right}
[Open URL]{outline} [Download]{outline}
:::
:::

::: card cURL & Raw Response
`{ "created": 1795058000, "data": [{ "url": "http://.../v1/media/ima_xxx.webp" }] }`
::: row {right}
[Copy cURL]{outline}
:::
:::
:::
:::
:::

::: tab Video
::: columns-2
::: column Controls {span-1}
::: card Video Parameters
Prompt
[Golden maple leaves drifting in the wind...___]{rows:4}

Duration
[5 seconds v]

Aspect Ratio / Size
[16:9 v]

First-Frame Image (optional)
[https://... or upload___] [Upload]{outline}

[Generate Video]{primary}
:::
:::

::: column Result {span-3}
::: card Video Task & Player
Task `vid_a1b2c3` ((completed · 100%)){success}

[ Video Player Controls ]

::: row {right}
[Download MP4]{outline}
:::
:::

::: card cURL & Raw Response
`{ "id": "vid_a1b2c3", "status": "completed", "progress": 100, "url": "http://.../v1/media/vid_a1b2c3.mp4" }`
::: row {right}
[Copy cURL]{outline}
:::
:::
:::
:::
:::

::: tab Audio & Voices
::: columns-2
::: column Voice Explorer {span-2}
::: card Voice Catalog
::: row
[Search voice name, ID, tone...___] [All Languages v] [Gender v]
:::

| Voice | Group / Accent | Actions |
|---|---|---|
| **Aria** (`avocado_v2:MAI_01`) | English (US) · F, American, Warm | [Preview]{primary} [Use]{outline} |
| **Linh** (`avocado_v2:vn_01`) | Vietnamese · F, Vietnamese, Natural | [Preview]{outline} [Use]{outline} |
| **Magnus** (`avocado_v2:magnus`) | English (UK) · M, British, Deep | [Preview]{primary} [Use]{outline} |

::: row {right}
[Prev]{outline} Page 1 / 122 [Next]{outline}
:::
:::
:::

::: column Speech Tester {span-2}
::: card Test POST /v1/audio/speech
Selected Voice
[avocado_v2:MAI_01 (Aria)___]

Model
[muse-tts v]

Speed
[1.0___]

Response Format
[mp3 (binary) v]

Style Instructions (optional)
[Speak warmly and naturally___]

Input Text
[Hello world! [laughs] That is fantastic.___]{rows:4}

Quick Emotion Cues
[[laughs]]{ghost} [[sighs]]{ghost} [[whispers]]{ghost} [[excited]]{ghost}

::: row {right}
[Generate Speech]{primary}
:::

---
Now Playing: **Aria** ((245 KB · 3.1s)){success}
[ Audio Player Controls ]
::: row {right}
[Download MP3]{outline}
:::
:::

::: card cURL & Raw Response
`curl -X POST http://localhost:18610/v1/audio/speech -H "Authorization: Bearer ***" ...`
::: row {right}
[Copy cURL]{outline}
:::
:::
:::
:::
:::
:::
:::
:::
