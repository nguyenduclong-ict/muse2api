import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Globe, Plus, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Textarea,
} from "../components/ui";
import { useToast } from "../components/Toast";
import { apiFetch, formatTimeAgo } from "../lib/api";

export interface ProxyItem {
  id: string;
  proxy_masked: string;
  scheme: string;
  status: "ok" | "dead" | "unchecked" | string;
  ip: string;
  country: string;
  city: string;
  org: string;
  latency_ms: number;
  last_checked_at: number;
  last_error: string;
  account_count: number;
  created_at: number;
}

export function ProxiesPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [modalOpen, setModalOpen] = useState(false);
  const [proxiesText, setProxiesText] = useState("");
  const [checkingId, setCheckingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["proxies"],
    queryFn: () => apiFetch<{ proxies: ProxyItem[] }>("/admin/proxies"),
    refetchInterval: 10000,
  });

  const importMut = useMutation({
    mutationFn: () =>
      apiFetch<{ imported: number; skipped: number; errors: string[] }>("/admin/proxies/import", {
        method: "POST",
        body: JSON.stringify({ proxies_text: proxiesText }),
      }),
    onSuccess: (res) => {
      setModalOpen(false);
      setProxiesText("");
      if (res.errors?.length) {
        toast.info(`Imported ${res.imported}, skipped ${res.skipped}. ${res.errors.length} line(s) invalid.`);
      } else {
        toast.success(`Imported ${res.imported} proxy(s)${res.skipped ? `, ${res.skipped} skipped` : ""}.`);
      }
      qc.invalidateQueries({ queryKey: ["proxies"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
    onError: (err: Error) => toast.error(`Import failed: ${err.message}`),
  });

  const checkAllMut = useMutation({
    mutationFn: () => apiFetch<{ results: { id: string; ok: boolean }[] }>("/admin/proxies/check-all", { method: "POST" }),
    onSuccess: (res) => {
      const okCount = res.results.filter((r) => r.ok).length;
      toast.success(`Checked ${res.results.length} proxy(s): ${okCount} alive.`);
      qc.invalidateQueries({ queryKey: ["proxies"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
    onError: (err: Error) => toast.error(`Check all failed: ${err.message}`),
  });

  const checkMut = useMutation({
    mutationFn: (id: string) => {
      setCheckingId(id);
      return apiFetch<{ ok: boolean; proxy: ProxyItem }>(`/admin/proxies/${id}/check`, { method: "POST" });
    },
    onSuccess: (res) => {
      if (res.ok) {
        toast.success(`Proxy OK (${res.proxy.ip || "connected"}, ${res.proxy.latency_ms}ms).`);
      } else {
        toast.error(`Proxy dead: ${res.proxy.last_error || "unreachable"}`);
      }
      qc.invalidateQueries({ queryKey: ["proxies"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
    onError: (err: Error) => toast.error(`Check failed: ${err.message}`),
    onSettled: () => setCheckingId(null),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => {
      setDeletingId(id);
      return apiFetch<{ ok: boolean; detached_accounts: number }>(`/admin/proxies/${id}`, { method: "DELETE" });
    },
    onSuccess: (res) => {
      const extra = res.detached_accounts > 0 ? ` (${res.detached_accounts} account(s) detached)` : "";
      toast.success(`Proxy deleted${extra}.`);
      qc.invalidateQueries({ queryKey: ["proxies"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
    },
    onError: (err: Error) => toast.error(`Delete failed: ${err.message}`),
    onSettled: () => setDeletingId(null),
  });

  const proxies = data?.proxies ?? [];

  const statusVariant = (status: string) => {
    if (status === "ok") return "success";
    if (status === "dead") return "danger";
    return "default";
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Proxies</h1>
          <p className="text-sm text-muted-foreground">
            Manage HTTP/SOCKS proxies, verify exit IPs via ipinfo.io, and assign them to accounts.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            onClick={() => checkAllMut.mutate()}
            loading={checkAllMut.isPending}
            disabled={proxies.length === 0}
          >
            <RefreshCw className="h-4 w-4" /> Check All
          </Button>
          <Button onClick={() => setModalOpen(true)}>
            <Plus className="h-4 w-4" /> Import Proxies
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Globe className="h-4 w-4 text-muted-foreground" />
            Saved Proxies ({proxies.length})
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="px-4 py-3 font-medium">Proxy</th>
                <th className="px-4 py-3 font-medium">Type</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Exit IP</th>
                <th className="px-4 py-3 font-medium">Location / Org</th>
                <th className="px-4 py-3 font-medium">Latency</th>
                <th className="px-4 py-3 font-medium">Accounts</th>
                <th className="px-4 py-3 font-medium">Checked</th>
                <th className="px-4 py-3 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {isLoading ? (
                <tr>
                  <td colSpan={9} className="px-4 py-8 text-center text-muted-foreground">
                    Loading proxies...
                  </td>
                </tr>
              ) : proxies.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-4 py-8 text-center text-muted-foreground">
                    No proxies configured yet. Click "Import Proxies" to add one or more.
                  </td>
                </tr>
              ) : (
                proxies.map((p) => {
                  const location = [p.city, p.country].filter(Boolean).join(", ");
                  return (
                    <tr key={p.id} className="hover:bg-muted/20">
                      <td className="px-4 py-3 font-mono text-xs">{p.proxy_masked}</td>
                      <td className="px-4 py-3">
                        <Badge variant="default" className="uppercase text-[10px]">
                          {p.scheme || "http"}
                        </Badge>
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant={statusVariant(p.status)}>{p.status}</Badge>
                        {p.status === "dead" && p.last_error && (
                          <div className="mt-1 max-w-[180px] truncate text-[11px] text-rose-400" title={p.last_error}>
                            {p.last_error}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs">{p.ip || "—"}</td>
                      <td className="px-4 py-3 text-xs">
                        <div>{location || "—"}</div>
                        {p.org && (
                          <div className="max-w-[200px] truncate text-[11px] text-muted-foreground" title={p.org}>
                            {p.org}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-xs text-muted-foreground">
                        {p.latency_ms > 0 ? `${p.latency_ms} ms` : "—"}
                      </td>
                      <td className="px-4 py-3 text-xs">
                        <Badge variant={p.account_count > 0 ? "info" : "default"}>
                          {p.account_count}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-xs text-muted-foreground">
                        {p.last_checked_at ? formatTimeAgo(p.last_checked_at) : "Never"}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-1.5">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => checkMut.mutate(p.id)}
                            loading={checkingId === p.id}
                            title="Check proxy via ipinfo.io"
                          >
                            <ShieldCheck className="h-3.5 w-3.5" /> Check
                          </Button>
                          <Button
                            size="sm"
                            variant="danger"
                            onClick={() => deleteMut.mutate(p.id)}
                            loading={deletingId === p.id}
                            title="Delete proxy"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <Card className="w-full max-w-xl">
            <CardHeader>
              <CardTitle>Import Proxies</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">
                  Proxy List (one per line)
                </label>
                <Textarea
                  rows={8}
                  placeholder={`http://user:pass@1.2.3.4:8080\nsocks5://1.2.3.4:1080\n1.2.3.4:8080:user:pass\n1.2.3.4:8080`}
                  value={proxiesText}
                  onChange={(e) => setProxiesText(e.target.value)}
                  className="font-mono text-xs"
                />
                <p className="text-[11px] text-muted-foreground">
                  Supported formats: <code>scheme://user:pass@host:port</code>, <code>host:port:user:pass</code>,{" "}
                  <code>user:pass@host:port</code>, or <code>host:port</code> (HTTP/HTTPS/SOCKS4/SOCKS5).
                </p>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <Button variant="ghost" onClick={() => setModalOpen(false)}>
                  Cancel
                </Button>
                <Button
                  onClick={() => importMut.mutate()}
                  disabled={!proxiesText.trim()}
                  loading={importMut.isPending}
                >
                  Import
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
