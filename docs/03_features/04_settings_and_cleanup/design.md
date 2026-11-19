[[ navbar | muse2apiv2 | Overview | Accounts | API & Keys | Tasks & Media | Settings* ]]

::: columns-2
::: column Sidebar {span-1}
- Overview
- Accounts
- API & Keys
- Tasks & Media
- **Settings**
:::

::: column Main Content {span-4}
# Settings

::: card Global System Prompt
- [ ] Enable Global System Prompt (prepend `<system>...</system>` to all `/v1/*` requests)

[System Prompt Content___]{rows:5 placeholder:"Enter global system prompt..."}
::: row {right}
[Reset Default]{outline} [Save Prompt]{primary}
:::
:::

::: card Voice Languages
- [x] Filter `/v1/audio/voices` and `/v1/audio/speech` by selected languages (leave off or empty to allow all voices)

::: columns-3
::: column Group 1
- [x] English (US) (541)
- [ ] English (UK) (200)
- [ ] English (Australia) (73)
- [ ] English (Ireland) (39)
- [ ] French (35)
- [ ] Indian (26)
- [ ] English (South Africa) (20)
- [ ] English (Kenya) (20)
- [ ] English (Nigeria) (20)
- [ ] English (Trinidad) (20)
- [ ] Finnish (20)
:::
::: column Group 2
- [ ] English (Zimbabwe) (19)
- [ ] Indonesian (18)
- [ ] English (New Zealand) (15)
- [ ] Spanish (14)
- [ ] German (13)
- [ ] English (Singapore) (12)
- [ ] Arabic (11)
- [ ] English (Jamaica) (11)
- [ ] Portuguese (11)
- [ ] Filipino (10)
- [ ] Malaysian (10)
:::
::: column Group 3
- [ ] Chinese (9)
- [ ] English (Canada) (9)
- [ ] Russian (9)
- [ ] Italian (8)
- [ ] Thai (7)
- [x] Vietnamese (7)
- [x] Japanese (6)
- [ ] Korean (4)
- [ ] Other (1)
:::
:::

::: row {between}
**Selected:** 3 languages (554 voices allowed)
::: row {right}
[Select All]{outline} [Clear]{outline} [Save Voice Languages]{primary}
:::
:::
:::

::: card Media Cleanup Policy
- [x] Enable Scheduled Media Cleanup

::: columns-3
::: column Retention
[Retention (Days)___]{value:"1"}
:::
::: column Capacity Cap
[Max Storage (GB)___]{value:"1"}
:::
::: column Schedule
[Interval (Minutes, min 5)___]{value:"60"}
:::
:::

::: row {between}
**Last Run:** 15m ago (freed 0 MB) — **Current Usage:** 248 MB
::: row {right}
[Run Cleanup Now]{outline} [Save Cleanup Policy]{primary}
:::
:::
:::
:::
:::
