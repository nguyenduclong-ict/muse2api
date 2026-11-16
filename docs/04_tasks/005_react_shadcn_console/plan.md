# Task 005: ReactJS + shadcn/ui Admin Console

## 1. Mục tiêu triển khai
Xây dựng giao diện quản trị ReactJS + TypeScript + Tailwind + shadcn/ui (Tiếng Anh, layout Sidebar → Content, Dark-First Slate/Zinc + Emerald/Blue) cho 5 màn hình theo [Screens Overview](../../02_basic_design/03_screens_overview.md).

## 2. Danh sách tệp tin cần tạo
- `frontend/package.json`
- `frontend/vite.config.ts` (proxy `/v1`, `/admin` sang FastAPI khi dev)
- `frontend/src/App.tsx` & `frontend/src/components/Layout.tsx` (Sidebar → Content)
- `frontend/src/pages/OverviewPage.tsx` (`SCR-01`)
- `frontend/src/pages/AccountsPage.tsx` (`SCR-02`)
- `frontend/src/pages/ApiKeysPage.tsx` (`SCR-03`)
- `frontend/src/pages/TasksMediaPage.tsx` (`SCR-04`)
- `frontend/src/pages/SettingsPage.tsx` (`SCR-05`)

## 3. Checklist triển khai
- [ ] Khởi tạo Vite React-TS + Tailwind + shadcn/ui + `lucide-react` + TanStack Query.
- [ ] Thiết lập theme Dark-First (`zinc-950` / `zinc-900`, accent `Emerald` & `Blue`, font `Inter` + `JetBrains Mono`) và Sidebar điều hướng 5 màn hình.
- [ ] Xây dựng `OverviewPage` (KPI cards, biểu đồ 7 ngày, recent tasks).
- [ ] Xây dựng `AccountsPage` (bảng tài khoản, modal Import Cookie + Test Proxy, nút Test WSS / Quota / Keep-Alive / Delete).
- [ ] Xây dựng `ApiKeysPage` (hiển thị raw key, Show/Hide, Copy, Rotate Key, cURL examples).
- [ ] Xây dựng `TasksMediaPage` (tabs Tasks History & Media Library, filters, Clear Completed, preview/delete media).
- [ ] Xây dựng `SettingsPage` (Global System Prompt + Reset Default, Media Cleanup + Run Cleanup Now).
- [ ] Build `frontend/dist/` và kiểm tra FastAPI serve single-port hoạt động mượt.

## 4. Kế hoạch kiểm thử
- **Build check:** `npm run build` không lỗi TypeScript/Vite.
- **Browser verification:** Mở console qua FastAPI single-port, kiểm tra điều hướng 5 màn hình và thao tác end-to-end với backend.
