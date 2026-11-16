[[ navbar | muse2apiv2 | Overview | Accounts | Proxies* | API & Keys | Tasks & Media | Settings ]]

::: columns-2
::: column Sidebar {span-1}
- Overview
- Accounts
- **Proxies**
- API & Keys
- Tasks & Media
- Settings
:::

::: column Main Content {span-4}
# Proxies

::: row {right}
[Check All]{outline} [+ Import Proxies]{primary}
:::

::: card Proxy List
| Proxy | Scheme | Status | IP / Location | Org | Latency | Accounts | Actions |
|---|---|---|---|---|---|---|---|
| `103.1.2.3:8080` | `http` | ((alive)){success} | `103.1.2.3` (VN, Hanoi) | VNPT | 142ms | 2 | [Check] [Delete]{danger} |
| `45.6.7.8:1080` | `socks5` | ((dead)){danger} | - | - | - | 0 | [Check] [Delete]{danger} |
:::

::: modal Import Proxies
### Import Proxies (One per line)
[Proxies___]{rows:6 placeholder:"http://user:pass@host:port\nsocks5://user:pass@host:port\nhost:port:user:pass\nhost:port"}
::: row {right}
[Cancel]{ghost} [Import]{primary}
:::
:::
:::
:::
