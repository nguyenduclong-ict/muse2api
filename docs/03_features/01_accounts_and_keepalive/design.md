[[ navbar | muse2apiv2 | Overview | Accounts* | API & Keys | Tasks & Media | Settings ]]

::: columns-2
::: column Sidebar {span-1}
- Overview
- **Accounts**
- API & Keys
- Tasks & Media
- Settings
:::

::: column Main Content {span-4}
# Accounts & Keep-Alive

::: row {right}
[Download Extension]{outline} [Refresh All]{outline} [Keep-Alive All]{outline} [Export]{outline} [+ Import Account]{primary}
:::

::: card Pool Summary
| Total Accounts | Healthy | Cooldown / Expired | Active WSS Tunnels |
|---|---|---|---|
| **4** | ((3)){success} | ((1)){warning} | **3** |
:::

::: card Accounts List
| Account | Status | Quota | Proxy | Keep-Alive | Enabled | Actions |
|---|---|---|---|---|---|---|
| **muse-01** | ((healthy)){success} | 30% bonus used (1.4B left) | No proxy | 2m ago | - [x] | [Edit] [Refresh] [Delete]{danger} |
| **muse-02** | ((cooldown)){warning} | 85% weekly used | 1.2.3.4 | 18m ago | - [x] | [Edit] [Refresh] [Delete]{danger} |
| **muse-03** | ((expired)){danger} | Unknown | No proxy | 1h ago | - [ ] | [Edit] [Refresh] [Delete]{danger} |
:::

::: modal Import Account
### Import Account from Cookie
[Account Label___]{placeholder:"e.g. muse-01"}
[Cookie String or JSON___]{rows:4 placeholder:"Paste Cookie header string or JSON array..."}
[Assign Proxy: No proxy v]
::: row {right}
[Cancel]{ghost} [Save & Test WSS]{primary}
:::
:::

::: modal Edit Account
### Edit Account
[Account Label___]{value:"muse-01"}
[New Cookie String or JSON (Optional)___]{rows:3 placeholder:"Leave blank to keep existing cookies..."}
[Assign Proxy: No proxy v]
- [x] Enabled
::: row {right}
[Cancel]{ghost} [Save Changes]{primary}
:::
:::
:::
:::
