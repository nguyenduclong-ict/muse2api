import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, HardDrive, Loader2, Radio, RefreshCw, Users, Wifi } from "lucide-react";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../components/ui";
import { QuotaBars } from "../components/QuotaBars";
import { useToast } from "../components/Toast";
import { apiFetch, formatBytes, formatTimeAgo } from "../lib/api";
import type { AccountItem } from "./AccountsPage";

interface DashboardData {
  pool: {
    total_accounts: number;
    enabled_accounts: number;
    healthy_accounts: number;
    active_wss_tunnels: number;
  };
  storage: {
    usage_bytes: number;
    last_cleanup_at: number;
    last_freed_bytes: number;
  };
  trend_7d: { day: string; total: number; completed: number; failed: number }[];
  accounts: AccountItem[];
}

export function OverviewPage() {
  const qc = useQueryClient();
  const toast = useToast();

  const { data, isLoading } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => apiFetch<DashboardData>("/admin/dashboard"),
    refetchInterval: 5000,
  });

  const refreshAllMut = useMutation({
    mutationFn: () =>
      apiFetch<{ results: { ok: boolean }[] }>("/admin/accounts/quota", { method: "POST" }),
    onSuccess: (res) => {
      const okCount = (res.results || []).filter((r) => r.ok).length;
      toast.success(`Refreshed quota for ${okCount}/${res.results?.length || 0} enabled accounts.`);
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
    onError: (err: Error) => toast.error(`Refresh quota failed: ${err.message}`),
  });

  if (isLoading || !data) {
    return <div className="text-sm text-zinc-400">Loading dashboard...</div>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-white">Overview</h1>
        <p className="text-sm text-zinc-400">
          System health, WSS tunnel pool, and account quota overview.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-medium text-zinc-400">Healthy Accounts</CardTitle>
            <Users className="h-4 w-4 text-emerald-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono">
              {data.pool.healthy_accounts}{" "}
              <span className="text-sm font-normal text-zinc-500">
                / {data.pool.total_accounts}
              </span>
            </div>
            <p className="mt-1 text-xs text-zinc-500">
              {data.pool.enabled_accounts} enabled in pool
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-medium text-zinc-400">Active WSS Tunnels</CardTitle>
            <Radio className="h-4 w-4 text-blue-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono text-emerald-400">
              {data.pool.active_wss_tunnels}
            </div>
            <p className="mt-1 text-xs text-zinc-500">Noise_XX encrypted sockets</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-medium text-zinc-400">Media Storage</CardTitle>
            <HardDrive className="h-4 w-4 text-zinc-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono">
              {formatBytes(data.storage.usage_bytes)}
            </div>
            <p className="mt-1 text-xs text-zinc-500">
              Last cleanup: {formatTimeAgo(data.storage.last_cleanup_at)}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-medium text-zinc-400">7-Day Tasks</CardTitle>
            <Activity className="h-4 w-4 text-zinc-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono">
              {data.trend_7d.reduce((acc, d) => acc + d.total, 0)}
            </div>
            <p className="mt-1 text-xs text-zinc-500">
              {data.trend_7d.reduce((acc, d) => acc + d.completed, 0)} completed
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle>Accounts & Quota</CardTitle>
            <CardDescription>
              Auto-refreshes every 5 minutes · Live WSS & remaining quota
            </CardDescription>
          </div>
          <Button
            size="sm"
            variant="outline"
            loading={refreshAllMut.isPending}
            onClick={() => refreshAllMut.mutate()}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh All
          </Button>
        </CardHeader>
        <CardContent>
          {data.accounts.length === 0 ? (
            <div className="py-8 text-center text-sm text-zinc-500">No accounts imported yet.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full table-fixed text-left text-sm">
                <thead>
                  <tr className="border-b border-zinc-800 text-xs text-zinc-400">
                    <th className="w-[22%] py-2 pr-3 font-medium">Account</th>
                    <th className="w-[13%] py-2 pr-3 font-medium">Status</th>
                    <th className="w-[27%] py-2 pr-3 font-medium">Quota Remaining</th>
                    <th className="w-[14%] py-2 pr-3 font-medium">WSS Tunnel</th>
                    <th className="w-[12%] py-2 pr-3 font-medium">Keep-Alive</th>
                    <th className="w-[12%] py-2 font-medium">Enabled</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/60">
                  {data.accounts.map((acc) => (
                    <tr key={acc.id} className="hover:bg-zinc-800/30">
                      <td className="py-2.5 pr-3 min-w-0">
                        <div className="truncate font-medium text-zinc-100" title={acc.label}>
                          {acc.label}
                        </div>
                        <div
                          className="truncate font-mono text-[11px] text-zinc-500"
                          title={acc.id}
                        >
                          {acc.id}
                        </div>
                      </td>
                      <td className="py-2.5 pr-3">
                        <Badge
                          variant={
                            acc.status === "healthy"
                              ? "success"
                              : acc.status === "expired"
                                ? "danger"
                                : acc.status === "resetting"
                                  ? "info"
                                  : "warning"
                          }
                        >
                          {acc.status === "resetting" && (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          )}
                          {acc.status}
                        </Badge>
                      </td>
                      <td className="py-2.5 pr-3">
                        <QuotaBars quota={acc.quota} />
                      </td>
                      <td className="py-2.5 pr-3">
                        {acc.wss_connected ? (
                          <Badge variant="info">
                            <Wifi className="h-3 w-3" /> Connected
                          </Badge>
                        ) : (
                          <span className="text-xs text-zinc-500">Idle</span>
                        )}
                      </td>
                      <td className="py-2.5 pr-3 whitespace-nowrap text-xs text-zinc-400">
                        {formatTimeAgo(acc.last_keepalive_at)}
                      </td>
                      <td className="py-2.5">
                        <Badge variant={acc.enabled ? "success" : "default"}>
                          {acc.enabled ? "Enabled" : "Disabled"}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
