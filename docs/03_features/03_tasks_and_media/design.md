[[ navbar | muse2apiv2 | Overview | Accounts | API & Keys | Tasks & Media* | Settings ]]

::: columns-2
::: column Sidebar {span-1}
- Overview
- Accounts
- API & Keys
- **Tasks & Media**
- Settings
:::

::: column Main Content {span-4}
# Tasks & Media

::: tabs
::: tab Tasks History
::: row {between}
[Type: All v] [Status: All v]
[Clear Completed]{outline}
:::

| Task ID | Type | Model | Account | Status | Latency | Output | Actions |
|---|---|---|---|---|---|---|---|
| `tsk_9a12` | video | muse-video | muse-01 | ((completed)){success} | 42.1s | [View MP4]{link} | [View]{outline} [Delete]{danger} |
| `tsk_9a11` | image | muse-image | muse-02 | ((running)){warning} | - | - | [View]{outline} |
| `tsk_9a10` | chat | gpt-4o | muse-01 | ((failed)){danger} | 3.2s | Timeout | [View]{outline} [Delete]{danger} |

::: modal Task Detail (`tsk_9a12`)
- **Type:** `video` | **Model:** `muse-video` | **Status:** ((completed)){success}
- **Input Request:**
  - `prompt`: `"A cinematic drone shot over mountains"`
  - `aspect_ratio`: `"16:9"`
  - `duration`: `5`
[Copy JSON]{outline} [Close]*
:::
:::

::: tab Media Library
::: row {between}
**Storage Used:** 248 MB / 1.00 GB
[Refresh]{outline}
:::

| Filename | Type | Size | Created | Actions |
|---|---|---|---|---|
| `vid_9a12.mp4` | video/mp4 | 4.76 MB | 2m ago | [Preview]{outline} [Delete]{danger} |
| `img_9a08.png` | image/png | 1.12 MB | 1h ago | [Preview]{outline} [Delete]{danger} |
:::
:::
:::
:::
