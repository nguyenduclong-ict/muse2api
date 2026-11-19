import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { Layout } from "./components/Layout";
import { ToastProvider } from "./components/Toast";
import { OverviewPage } from "./pages/OverviewPage";
import { AccountsPage } from "./pages/AccountsPage";
import { ProxiesPage } from "./pages/ProxiesPage";
import { ApiKeysPage } from "./pages/ApiKeysPage";
import { PlaygroundPage } from "./pages/PlaygroundPage";
import { TasksMediaPage } from "./pages/TasksMediaPage";
import { SettingsPage } from "./pages/SettingsPage";
import { apiFetch } from "./lib/api";

const queryClient = new QueryClient();

function ConsoleShell() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () =>
      apiFetch<{ pool: { active_wss_tunnels: number; healthy_accounts: number } }>("/admin/dashboard"),
    refetchInterval: 5000,
  });

  // Auto-poll all account quotas every 5 minutes
  useEffect(() => {
    const timer = setInterval(async () => {
      try {
        await apiFetch("/admin/accounts/quota", { method: "POST" });
        qc.invalidateQueries({ queryKey: ["accounts"] });
        qc.invalidateQueries({ queryKey: ["dashboard"] });
      } catch {
        // silent background poll
      }
    }, 5 * 60 * 1000);
    return () => clearInterval(timer);
  }, [qc]);

  return (
    <Layout
      activeTunnels={data?.pool.active_wss_tunnels ?? 0}
      healthyAccounts={data?.pool.healthy_accounts ?? 0}
    >
      <Routes>
        <Route path="/" element={<OverviewPage />} />
        <Route path="/accounts" element={<AccountsPage />} />
        <Route path="/proxies" element={<ProxiesPage />} />
        <Route path="/api-keys" element={<ApiKeysPage />} />
        <Route path="/playground" element={<PlaygroundPage />} />
        <Route path="/tasks" element={<TasksMediaPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <ConsoleShell />
        </ToastProvider>
      </QueryClientProvider>
    </BrowserRouter>
  );
}
