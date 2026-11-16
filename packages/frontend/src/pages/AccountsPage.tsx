import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, HeartPulse, Pencil, Plus, Puzzle, RefreshCw, Trash2, Wifi } from "lucide-react";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Switch,
  Textarea,
} from "../components/ui";
import { QuotaBars, type QuotaInfo } from "../components/QuotaBars";
import { useToast } from "../components/Toast";
import { apiFetch, formatTimeAgo } from "../lib/api";
import type { ProxyItem } from "./ProxiesPage";

export interface AccountItem {
  id: string;
  label: string;
  cookie_count: number;
  proxy_id?: string | null;
  proxy_masked: string;
  proxy_ip?: string;
  proxy_status?: string;
  has_proxy: boolean;
  enabled: boolean;
  status: string;
  wss_connected: boolean;
  quota: QuotaInfo;
  last_used_at: number;
  last_keepalive_at: number;
  last_error: string;
}

export function AccountsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [modalOpen, setModalOpen] = useState(false);
  const [label, setLabel] = useState("");
  const [cookiesRaw, setCookiesRaw] = useState("");
  const [proxyId, setProxyId] = useState("");
  const [exporting, setExporting] = useState(false);
  const [downloadingExt, setDownloadingExt] = useState(false);

  const [editingAcc, setEditingAcc] = useState<AccountItem | null>(null);
  const [editLabel, setEditLabel] = useState("");
  const [editCookies, setEditCookies] = useState("");
  const [editProxyId, setEditProxyId] = useState("");
  const [editEnabled, setEditEnabled] = useState(true);

  const [refreshId, setRefreshId] = useState<string | null>(null);
  const [delId, setDelId] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["accounts"],
    queryFn: () => apiFetch<{ accounts: AccountItem[] }>("/admin/accounts"),
    refetchInterval: 5000,
  });

  const { data: proxiesData } = useQuery({
    queryKey: ["proxies"],
    queryFn: () => apiFetch<{ proxies: ProxyItem[] }>("/admin/proxies"),
  });

  const createMut = useMutation({
    mutationFn: () =>
      apiFetch("/admin/accounts", {
        method: "POST",
        body: JSON.stringify({
          label,
          cookies_raw: cookiesRaw,
          proxy_id: proxyId || null,
          enabled: true,
        }),
      }),
    onSuccess: () => {
      setModalOpen(false);
      setLabel("");
      setCookiesRaw("");
      setProxyId("");
      toast.success("Account imported and WSS tested.");
      qc.invalidateQueries({ queryKey: ["accounts"] });
      qc.invalidateQueries({ queryKey: ["proxies"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (err: Error) => toast.error(`Import failed: ${err.message}`),
  });

  const toggleMut = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      apiFetch(`/admin/accounts/${id}`, { method: "PATCH", body: JSON.stringify({ enabled }) }),
    onSuccess: (_, vars) => {
      toast.info(vars.enabled ? "Account enabled." : "Account disabled.");
      qc.invalidateQueries({ queryKey: ["accounts"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });

  const openEditModal = (acc: AccountItem) => {
    setEditingAcc(acc);
    setEditLabel(acc.label);
    setEditCookies("");
    setEditProxyId(acc.proxy_id || "");
    setEditEnabled(acc.enabled);
  };

  const editMut = useMutation({
    mutationFn: () => {
      if (!editingAcc) throw new Error("No account selected");
      const payload: Record<string, unknown> = {
        label: editLabel,
        proxy_id: editProxyId || null,
        enabled: editEnabled,
      };
      if (editCookies.trim()) {
        payload.cookies_raw = editCookies.trim();
      }
      return apiFetch(`/admin/accounts/${editingAcc.id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
    },
    onSuccess: () => {
      setEditingAcc(null);
      setEditCookies("");
      toast.success("Account updated.");
      qc.invalidateQueries({ queryKey: ["accounts"] });
      qc.invalidateQueries({ queryKey: ["proxies"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (err: Error) => toast.error(`Update failed: ${err.message}`),
  });

  const refreshOneMut = useMutation({
    mutationFn: (id: string) => {
      setRefreshId(id);
      return apiFetch<{ ok: boolean; error?: string; account?: AccountItem }>(`/admin/accounts/${id}/refresh`, {
        method: "POST",
      });
    },
    onSuccess: (res) => {
      if (res.ok) toast.success("Refreshed status, WSS tunnel & quota.");
      else toast.error(`Refresh completed with issue: ${res.error || "Unknown"}`);
      qc.invalidateQueries({ queryKey: ["accounts"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (err: Error) => toast.error(`Refresh failed: ${err.message}`),
    onSettled: () => setRefreshId(null),
  });

  const refreshAllMut = useMutation({
    mutationFn: () => apiFetch<{ results: { ok: boolean }[] }>("/admin/accounts/refresh", { method: "POST" }),
    onSuccess: (res) => {
      const okCount = (res.results || []).filter((r) => r.ok).length;
      toast.success(`Refreshed ${okCount}/${res.results?.length || 0} enabled accounts (status, WSS & quota).`);
      qc.invalidateQueries({ queryKey: ["accounts"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (err: Error) => toast.error(`Refresh all failed: ${err.message}`),
  });

  const keepaliveAllMut = useMutation({
    mutationFn: () => apiFetch("/admin/accounts/keepalive", { method: "POST" }),
    onSuccess: () => {
      toast.success("Keep-Alive All completed.");
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
    onError: (err: Error) => toast.error(`Keep-Alive All failed: ${err.message}`),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => {
      setDelId(id);
      return apiFetch(`/admin/accounts/${id}`, { method: "DELETE" });
    },
    onSuccess: () => {
      toast.info("Account deleted.");
      qc.invalidateQueries({ queryKey: ["accounts"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onSettled: () => setDelId(null),
  });

  const handleDownloadExtension = async () => {
    setDownloadingExt(true);
    try {
      const res = await fetch("/admin/extension/download");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "muse2apiv2-extension.zip";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success("Downloaded muse2apiv2-extension.zip.");
    } catch (err) {
      toast.error(`Download failed: ${(err as Error).message}`);
    } finally {
      setDownloadingExt(false);
    }
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      const res = await fetch("/admin/accounts/export");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "muse2apiv2-accounts.json";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success("Exported accounts to muse2apiv2-accounts.json.");
    } catch (err) {
      toast.error(`Export failed: ${(err as Error).message}`);
    } finally {
      setExporting(false);
    }
  };

  const accounts = data?.accounts || [];
  const proxies = proxiesData?.proxies || [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-white">Accounts</h1>
          <p className="text-sm text-zinc-400">Import muse.ai cookies, manage WSS tunnels, quota, proxies, and keep-alive.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" loading={refreshAllMut.isPending} onClick={() => refreshAllMut.mutate()}>
            <RefreshCw className="h-4 w-4 text-blue-400" />
            Refresh All
          </Button>
          <Button variant="outline" loading={keepaliveAllMut.isPending} onClick={() => keepaliveAllMut.mutate()}>
            <HeartPulse className="h-4 w-4 text-emerald-400" />
            Keep-Alive All
          </Button>
          <Button variant="outline" loading={downloadingExt} onClick={handleDownloadExtension}>
            <Puzzle className="h-4 w-4 text-amber-400" />
            Download Extension
          </Button>
          <Button variant="outline" loading={exporting} onClick={handleExport} disabled={accounts.length === 0}>
            <Download className="h-4 w-4" />
            Export
          </Button>
          <Button onClick={() => setModalOpen(true)}>
            <Plus className="h-4 w-4" />
            Import Account
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader className="min-h-[60px] flex flex-row items-center justify-between space-y-0">
          <CardTitle>Account Pool ({accounts.length})</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="py-6 text-sm text-zinc-400">Loading accounts...</div>
          ) : accounts.length === 0 ? (
            <div className="py-10 text-center text-sm text-zinc-500">
              No accounts imported yet. Click <span className="text-zinc-300 font-medium">Import Account</span> to add one.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-zinc-800 text-xs text-zinc-400">
                    <th className="py-2 pr-4 font-medium">Label</th>
                    <th className="py-2 pr-4 font-medium">Status</th>
                    <th className="py-2 pr-4 font-medium">Quota Remaining</th>
                    <th className="py-2 pr-4 font-medium">WSS Tunnel</th>
                    <th className="py-2 pr-4 font-medium">Proxy</th>
                    <th className="py-2 pr-4 font-medium">Keep-Alive</th>
                    <th className="py-2 pr-4 font-medium">Enabled</th>
                    <th className="py-2 font-medium text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/60">
                  {accounts.map((acc) => (
                    <tr key={acc.id} className="hover:bg-zinc-800/30">
                      <td className="py-3 pr-4">
                        <div className="font-medium text-zinc-100">{acc.label}</div>
                        <div className="font-mono text-[11px] text-zinc-500">{acc.id} · {acc.cookie_count} cookies</div>
                      </td>
                      <td className="py-3 pr-4">
                        <Badge
                          variant={
                            acc.status === "healthy"
                              ? "success"
                              : acc.status === "expired"
                              ? "danger"
                              : "warning"
                          }
                        >
                          {acc.status}
                        </Badge>
                        {acc.last_error && (
                          <div className="mt-1 max-w-[180px] truncate text-[11px] text-rose-400" title={acc.last_error}>
                            {acc.last_error}
                          </div>
                        )}
                      </td>
                      <td className="py-3 pr-4">
                        <QuotaBars quota={acc.quota} />
                      </td>
                      <td className="py-3 pr-4">
                        {acc.wss_connected ? (
                          <Badge variant="info">
                            <Wifi className="h-3 w-3" /> Connected
                          </Badge>
                        ) : (
                          <span className="text-xs text-zinc-500">Idle</span>
                        )}
                      </td>
                      <td className="py-3 pr-4 font-mono text-xs text-zinc-300">
                        {!acc.has_proxy ? (
                          <span className="text-zinc-500">No proxy</span>
                        ) : acc.proxy_ip ? (
                          <span title={acc.proxy_masked}>{acc.proxy_ip}</span>
                        ) : (
                          <span>{acc.proxy_masked}</span>
                        )}
                      </td>
                      <td className="py-3 pr-4 text-xs text-zinc-400">{formatTimeAgo(acc.last_keepalive_at)}</td>
                      <td className="py-3 pr-4">
                        <Switch
                          checked={acc.enabled}
                          onCheckedChange={(v) => toggleMut.mutate({ id: acc.id, enabled: v })}
                        />
                      </td>
                      <td className="py-3 text-right">
                        <div className="inline-flex items-center gap-1.5">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => openEditModal(acc)}
                            title="Edit account"
                          >
                            <Pencil className="h-3.5 w-3.5" /> Edit
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            loading={refreshId === acc.id}
                            onClick={() => refreshOneMut.mutate(acc.id)}
                            title="Check status, WSS tunnel & quota"
                          >
                            <RefreshCw className="h-3.5 w-3.5" /> Refresh
                          </Button>
                          <Button
                            size="sm"
                            variant="danger"
                            loading={delId === acc.id}
                            onClick={() => deleteMut.mutate(acc.id)}
                            title="Delete account"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-xs">
          <Card className="w-full max-w-lg border-zinc-700 bg-zinc-900">
            <CardHeader>
              <CardTitle>Import Account from Cookie</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-zinc-300">Account Label</label>
                <Input placeholder="e.g. muse-01" value={label} onChange={(e) => setLabel(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-zinc-300">Cookie Header String or JSON</label>
                <Textarea
                  rows={5}
                  className="font-mono text-xs"
                  placeholder="Paste Cookie header string (hatch_sess=...; hatch_vml=...) or JSON array..."
                  value={cookiesRaw}
                  onChange={(e) => setCookiesRaw(e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-zinc-300">Proxy (Optional)</label>
                <select
                  value={proxyId}
                  onChange={(e) => setProxyId(e.target.value)}
                  className="h-9 w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 font-mono text-xs text-zinc-200 focus:border-blue-500 focus:outline-none"
                >
                  <option value="">No proxy</option>
                  {proxies.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.proxy_masked}{p.ip ? ` — ${p.ip}` : ""} ({p.status})
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <Button variant="ghost" onClick={() => setModalOpen(false)}>Cancel</Button>
                <Button
                  loading={createMut.isPending}
                  onClick={() => createMut.mutate()}
                  disabled={!cookiesRaw.trim()}
                >
                  Save & Test WSS
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {editingAcc && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-xs">
          <Card className="w-full max-w-lg border-zinc-700 bg-zinc-900">
            <CardHeader>
              <CardTitle>Edit Account — {editingAcc.label}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-zinc-300">Account Label</label>
                <Input
                  placeholder="e.g. muse-01"
                  value={editLabel}
                  onChange={(e) => setEditLabel(e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-zinc-300">New Cookie String or JSON (Optional)</label>
                <Textarea
                  rows={4}
                  className="font-mono text-xs"
                  placeholder="Leave blank to keep existing cookies..."
                  value={editCookies}
                  onChange={(e) => setEditCookies(e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-zinc-300">Proxy</label>
                <select
                  value={editProxyId}
                  onChange={(e) => setEditProxyId(e.target.value)}
                  className="h-9 w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 font-mono text-xs text-zinc-200 focus:border-blue-500 focus:outline-none"
                >
                  <option value="">No proxy</option>
                  {proxies.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.proxy_masked}{p.ip ? ` — ${p.ip}` : ""} ({p.status})
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex items-center justify-between rounded-md border border-zinc-800 bg-zinc-950/60 px-3 py-2">
                <span className="text-xs font-medium text-zinc-300">Enabled in Pool</span>
                <Switch checked={editEnabled} onCheckedChange={setEditEnabled} />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <Button variant="ghost" onClick={() => setEditingAcc(null)}>Cancel</Button>
                <Button
                  loading={editMut.isPending}
                  onClick={() => editMut.mutate()}
                  disabled={!editLabel.trim()}
                >
                  Save Changes
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
