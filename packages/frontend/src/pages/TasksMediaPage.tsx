import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Trash2 } from "lucide-react";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Checkbox } from "../components/ui";
import { useToast } from "../components/Toast";
import { apiFetch, formatBytes, formatTimeAgo } from "../lib/api";

interface TaskItem {
  id: string;
  type: string;
  status: string;
  model: string;
  account_id?: string;
  account_label: string;
  prompt_preview: string;
  media_filename: string;
  error_message: string;
  latency_ms: number;
  created_at: number;
}

interface MediaItem {
  filename: string;
  kind: string;
  size_bytes: number;
  created_at: number;
  url: string;
}

export function TasksMediaPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [subTab, setSubTab] = useState<"tasks" | "media">("tasks");
  const [typeFilter, setTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [selectedMedia, setSelectedMedia] = useState<Set<string>>(new Set());
  const [deletingTaskId, setDeletingTaskId] = useState<string | null>(null);
  const [deletingMediaName, setDeletingMediaName] = useState<string | null>(null);

  const { data: tasksData } = useQuery({
    queryKey: ["tasks", typeFilter, statusFilter],
    queryFn: () =>
      apiFetch<{ tasks: TaskItem[] }>(
        `/admin/tasks?type=${encodeURIComponent(typeFilter)}&status=${encodeURIComponent(statusFilter)}`
      ),
    refetchInterval: 4000,
  });

  const { data: mediaData } = useQuery({
    queryKey: ["media"],
    queryFn: () => apiFetch<{ files: MediaItem[]; usage_bytes: number }>("/admin/media"),
    refetchInterval: 8000,
  });

  const deleteTaskMut = useMutation({
    mutationFn: (id: string) => {
      setDeletingTaskId(id);
      return apiFetch(`/admin/tasks/${id}`, { method: "DELETE" });
    },
    onSuccess: () => {
      toast.info("Task deleted.");
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
    onSettled: () => setDeletingTaskId(null),
  });

  const clearTasksMut = useMutation({
    mutationFn: () => apiFetch<{ deleted: number }>("/admin/tasks/clear", { method: "POST" }),
    onSuccess: (res) => {
      toast.success(`Cleared ${res.deleted} completed tasks.`);
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });

  const deleteMediaMut = useMutation({
    mutationFn: (name: string) => {
      setDeletingMediaName(name);
      return apiFetch(`/admin/media/${encodeURIComponent(name)}`, { method: "DELETE" });
    },
    onSuccess: () => {
      toast.info("Media file deleted.");
      qc.invalidateQueries({ queryKey: ["media"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onSettled: () => setDeletingMediaName(null),
  });

  const deleteMediaBatchMut = useMutation({
    mutationFn: (filenames: string[]) =>
      apiFetch<{ ok: boolean; deleted: number }>("/admin/media/delete", {
        method: "POST",
        body: JSON.stringify({ filenames }),
      }),
    onSuccess: (res) => {
      setSelectedMedia(new Set());
      toast.success(`Deleted ${res.deleted} media files.`);
      qc.invalidateQueries({ queryKey: ["media"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });

  const mediaFiles = mediaData?.files || [];
  const allSelected = mediaFiles.length > 0 && mediaFiles.every((f) => selectedMedia.has(f.filename));
  const someSelected = selectedMedia.size > 0 && !allSelected;

  const toggleSelectAll = () => {
    if (allSelected) {
      setSelectedMedia(new Set());
    } else {
      setSelectedMedia(new Set(mediaFiles.map((f) => f.filename)));
    }
  };

  const toggleOne = (filename: string) => {
    setSelectedMedia((prev) => {
      const next = new Set(prev);
      if (next.has(filename)) next.delete(filename);
      else next.add(filename);
      return next;
    });
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-white">Tasks & Media</h1>
          <p className="text-sm text-zinc-400">Monitor generation history and manage local media files.</p>
        </div>
        <div className="inline-flex rounded-lg border border-zinc-800 bg-zinc-900 p-1">
          <button
            onClick={() => setSubTab("tasks")}
            className={`rounded-md px-3 py-1 text-xs font-medium cursor-pointer ${
              subTab === "tasks" ? "bg-zinc-800 text-white" : "text-zinc-400 hover:text-zinc-200"
            }`}
          >
            Tasks History
          </button>
          <button
            onClick={() => setSubTab("media")}
            className={`rounded-md px-3 py-1 text-xs font-medium cursor-pointer ${
              subTab === "media" ? "bg-zinc-800 text-white" : "text-zinc-400 hover:text-zinc-200"
            }`}
          >
            Media Library ({formatBytes(mediaData?.usage_bytes || 0)})
          </button>
        </div>
      </div>

      {subTab === "tasks" ? (
        <Card>
          <CardHeader className="min-h-[60px] flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
            <div className="flex items-center gap-2">
              <select
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                className="h-8 rounded-lg border border-zinc-800 bg-zinc-950 px-2.5 text-xs text-zinc-200"
              >
                <option value="">All Types</option>
                <option value="chat">Chat</option>
                <option value="image">Image</option>
                <option value="video">Video</option>
              </select>
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="h-8 rounded-lg border border-zinc-800 bg-zinc-950 px-2.5 text-xs text-zinc-200"
              >
                <option value="">All Statuses</option>
                <option value="running">Running</option>
                <option value="completed">Completed</option>
                <option value="failed">Failed</option>
              </select>
            </div>
            <Button size="sm" variant="outline" loading={clearTasksMut.isPending} onClick={() => clearTasksMut.mutate()}>
              Clear Completed
            </Button>
          </CardHeader>
          <CardContent>
            {(tasksData?.tasks || []).length === 0 ? (
              <div className="py-8 text-center text-sm text-zinc-500">No tasks found.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-zinc-800 text-xs text-zinc-400">
                      <th className="py-2 pr-4 font-medium">ID</th>
                      <th className="py-2 pr-4 font-medium">Type</th>
                      <th className="py-2 pr-4 font-medium">Account</th>
                      <th className="py-2 pr-4 font-medium">Status</th>
                      <th className="py-2 pr-4 font-medium">Latency</th>
                      <th className="py-2 pr-4 font-medium">Output</th>
                      <th className="py-2 font-medium text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-800/60">
                    {(tasksData?.tasks || []).map((t) => (
                      <tr key={t.id} className="hover:bg-zinc-800/30">
                        <td className="py-2.5 pr-4 font-mono text-xs text-zinc-300">{t.id}</td>
                        <td className="py-2.5 pr-4 capitalize text-zinc-300">{t.type}</td>
                        <td className="py-2.5 pr-4 text-zinc-300" title={t.account_id || undefined}>
                          {t.account_label ? (
                            <span>{t.account_label}</span>
                          ) : t.account_id ? (
                            <span className="font-mono text-xs text-zinc-400">{t.account_id}</span>
                          ) : (
                            <span className="text-zinc-500">-</span>
                          )}
                        </td>
                        <td className="py-2.5 pr-4">
                          <Badge
                            variant={
                              t.status === "completed" ? "success" : t.status === "failed" ? "danger" : "warning"
                            }
                          >
                            {t.status}
                          </Badge>
                        </td>
                        <td className="py-2.5 pr-4 font-mono text-xs text-zinc-400">
                          {t.latency_ms ? `${(t.latency_ms / 1000).toFixed(1)}s` : "-"}
                        </td>
                        <td className="py-2.5 pr-4 text-xs">
                          {t.media_filename ? (
                            <a
                              href={`/v1/media/${t.media_filename}`}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-1 text-blue-400 hover:underline"
                            >
                              {t.media_filename} <ExternalLink className="h-3 w-3" />
                            </a>
                          ) : t.error_message ? (
                            <span className="text-rose-400">{t.error_message.slice(0, 60)}</span>
                          ) : (
                            <span className="text-zinc-500">{formatTimeAgo(t.created_at)}</span>
                          )}
                        </td>
                        <td className="py-2.5 text-right">
                          <Button
                            size="sm"
                            variant="danger"
                            loading={deletingTaskId === t.id}
                            disabled={t.status === "running"}
                            onClick={() => deleteTaskMut.mutate(t.id)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader className="min-h-[60px] flex flex-row items-center justify-between gap-3 space-y-0">
            <CardTitle>Stored Media Files ({mediaFiles.length})</CardTitle>
            <div className="min-h-7 flex items-center">
              <Button
                size="sm"
                variant="danger"
                className={selectedMedia.size === 0 ? "invisible pointer-events-none" : ""}
                loading={deleteMediaBatchMut.isPending}
                onClick={() => deleteMediaBatchMut.mutate(Array.from(selectedMedia))}
              >
                <Trash2 className="h-3.5 w-3.5" />
                Delete Selected ({selectedMedia.size})
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {mediaFiles.length === 0 ? (
              <div className="py-8 text-center text-sm text-zinc-500">No media files stored.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-zinc-800 text-xs text-zinc-400">
                      <th className="py-2 pr-3 w-8">
                        <Checkbox
                          ariaLabel="Select all media"
                          checked={allSelected}
                          indeterminate={someSelected}
                          onCheckedChange={toggleSelectAll}
                        />
                      </th>
                      <th className="py-2 pr-4 font-medium">Preview</th>
                      <th className="py-2 pr-4 font-medium">Filename</th>
                      <th className="py-2 pr-4 font-medium">Kind</th>
                      <th className="py-2 pr-4 font-medium">Size</th>
                      <th className="py-2 pr-4 font-medium">Created</th>
                      <th className="py-2 font-medium text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-800/60">
                    {mediaFiles.map((f) => (
                      <tr key={f.filename} className="hover:bg-zinc-800/30">
                        <td className="py-2.5 pr-3">
                          <Checkbox
                            ariaLabel={`Select ${f.filename}`}
                            checked={selectedMedia.has(f.filename)}
                            onCheckedChange={() => toggleOne(f.filename)}
                          />
                        </td>
                        <td className="py-2.5 pr-4">
                          <a href={f.url} target="_blank" rel="noreferrer" className="block w-14 h-10 overflow-hidden rounded border border-zinc-800 bg-zinc-950">
                            {f.kind === "video" ? (
                              <video src={f.url} muted playsInline preload="metadata" className="h-full w-full object-cover" />
                            ) : (
                              <img src={f.url} alt={f.filename} loading="lazy" className="h-full w-full object-cover" />
                            )}
                          </a>
                        </td>
                        <td className="py-2.5 pr-4 font-mono text-xs text-blue-400">
                          <a href={f.url} target="_blank" rel="noreferrer" className="hover:underline">
                            {f.filename}
                          </a>
                        </td>
                        <td className="py-2.5 pr-4 capitalize text-zinc-300">{f.kind}</td>
                        <td className="py-2.5 pr-4 font-mono text-xs text-zinc-400">{formatBytes(f.size_bytes)}</td>
                        <td className="py-2.5 pr-4 text-xs text-zinc-500">{formatTimeAgo(f.created_at)}</td>
                        <td className="py-2.5 text-right">
                          <Button
                            size="sm"
                            variant="danger"
                            loading={deletingMediaName === f.filename}
                            onClick={() => deleteMediaMut.mutate(f.filename)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
