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
