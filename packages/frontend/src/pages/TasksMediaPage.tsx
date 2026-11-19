import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronLeft, ChevronRight, Copy, Download, ExternalLink, Eye, Music, Trash2, X } from "lucide-react";
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

interface TaskDetail extends TaskItem {
  input_request?: unknown;
  input_request_json?: string;
}

interface MediaItem {
  filename: string;
  kind: string;
  size_bytes: number;
  created_at: number;
  url: string;
}

function PaginationBar({
  page,
  pageSize,
  total,
  totalPages,
  onPageChange,
  onPageSizeChange,
}: {
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
  onPageChange: (nextPage: number) => void;
  onPageSizeChange: (nextSize: number) => void;
}) {
  if (total === 0) return null;
  const start = (page - 1) * pageSize + 1;
  const end = Math.min(total, page * pageSize);

  return (
    <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-zinc-800/80 pt-3 text-xs text-zinc-400">
      <div className="flex items-center gap-3">
        <span>
          Showing <span className="font-mono text-zinc-200">{start}–{end}</span> of{" "}
          <span className="font-mono text-zinc-200">{total}</span>
        </span>
        <select
          aria-label="Rows per page"
          value={pageSize}
          onChange={(e) => onPageSizeChange(Number(e.target.value))}
          className="h-7 rounded-md border border-zinc-800 bg-zinc-950 px-2 text-xs text-zinc-200"
        >
          <option value={10}>10 / page</option>
          <option value={20}>20 / page</option>
          <option value={50}>50 / page</option>
        </select>
      </div>
      <div className="flex items-center gap-1.5">
        <Button
          size="sm"
          variant="outline"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          <ChevronLeft className="h-3.5 w-3.5" /> Prev
        </Button>
        <span className="px-2 font-mono text-zinc-300">
          {page} / {totalPages}
        </span>
        <Button
          size="sm"
          variant="outline"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
        >
          Next <ChevronRight className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  );
}

export function TasksMediaPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [subTab, setSubTab] = useState<"tasks" | "media">("tasks");
  const [typeFilter, setTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [tasksPage, setTasksPage] = useState(1);
  const [tasksPageSize, setTasksPageSize] = useState(10);
  const [mediaPage, setMediaPage] = useState(1);
  const [mediaPageSize, setMediaPageSize] = useState(10);
  const [selectedMedia, setSelectedMedia] = useState<Set<string>>(new Set());
  const [deletingTaskId, setDeletingTaskId] = useState<string | null>(null);
  const [deletingMediaName, setDeletingMediaName] = useState<string | null>(null);
  const [previewMedia, setPreviewMedia] = useState<MediaItem | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [copiedInputJson, setCopiedInputJson] = useState(false);

  useEffect(() => {
    if (!previewMedia && !selectedTaskId) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setPreviewMedia(null);
        setSelectedTaskId(null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [previewMedia, selectedTaskId]);

  const { data: taskDetail, isLoading: isLoadingTaskDetail } = useQuery({
    queryKey: ["task-detail", selectedTaskId],
    queryFn: () => apiFetch<TaskDetail>(`/admin/tasks/${encodeURIComponent(selectedTaskId!)}`),
    enabled: Boolean(selectedTaskId),
  });

  const { data: tasksData } = useQuery({
    queryKey: ["tasks", typeFilter, statusFilter, tasksPage, tasksPageSize],
    queryFn: () =>
      apiFetch<{ tasks: TaskItem[]; total: number; page: number; page_size: number; total_pages: number }>(
        `/admin/tasks?type=${encodeURIComponent(typeFilter)}&status=${encodeURIComponent(statusFilter)}&page=${tasksPage}&page_size=${tasksPageSize}`
      ),
    refetchInterval: 4000,
  });

  const { data: mediaData } = useQuery({
    queryKey: ["media", mediaPage, mediaPageSize],
    queryFn: () =>
      apiFetch<{ files: MediaItem[]; total: number; page: number; page_size: number; total_pages: number; usage_bytes: number }>(
        `/admin/media?page=${mediaPage}&page_size=${mediaPageSize}`
      ),
    refetchInterval: 8000,
  });

  useEffect(() => {
    if (tasksData && tasksPage > tasksData.total_pages) {
      setTasksPage(tasksData.total_pages);
    }
  }, [tasksData, tasksPage]);

  useEffect(() => {
    if (mediaData && mediaPage > mediaData.total_pages) {
      setMediaPage(mediaData.total_pages);
    }
  }, [mediaData, mediaPage]);

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
                onChange={(e) => {
                  setTypeFilter(e.target.value);
                  setTasksPage(1);
                }}
                className="h-8 rounded-lg border border-zinc-800 bg-zinc-950 px-2.5 text-xs text-zinc-200"
              >
                <option value="">All Types</option>
                <option value="chat">Chat</option>
                <option value="image">Image</option>
                <option value="video">Video</option>
                <option value="audio">Audio</option>
              </select>
              <select
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value);
                  setTasksPage(1);
                }}
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
                          <div className="inline-flex items-center gap-1.5">
                            <Button
                              size="sm"
                              variant="outline"
                              title="View Task Detail"
                              onClick={() => {
                                setCopiedInputJson(false);
                                setSelectedTaskId(t.id);
                              }}
                            >
                              <Eye className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              size="sm"
                              variant="danger"
                              loading={deletingTaskId === t.id}
                              disabled={t.status === "running"}
                              onClick={() => deleteTaskMut.mutate(t.id)}
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
            <PaginationBar
              page={tasksData?.page || tasksPage}
              pageSize={tasksData?.page_size || tasksPageSize}
              total={tasksData?.total || 0}
              totalPages={tasksData?.total_pages || 1}
              onPageChange={setTasksPage}
              onPageSizeChange={(size) => {
                setTasksPageSize(size);
                setTasksPage(1);
              }}
            />
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader className="min-h-[60px] flex flex-row items-center justify-between gap-3 space-y-0">
            <CardTitle>Stored Media Files ({mediaData?.total ?? mediaFiles.length})</CardTitle>
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
                          <button
                            type="button"
                            onClick={() => setPreviewMedia(f)}
                            className="block w-14 h-10 overflow-hidden rounded border border-zinc-800 bg-zinc-950 hover:border-blue-500/70 transition-colors cursor-pointer"
                            title="Preview media"
                          >
                            {f.kind === "video" ? (
                              <video src={f.url} muted playsInline preload="metadata" className="h-full w-full object-cover" />
                            ) : f.kind === "audio" ? (
                              <div className="flex h-full w-full items-center justify-center bg-zinc-900 text-zinc-400">
                                <Music className="h-4 w-4 text-indigo-400" />
                              </div>
                            ) : (
                              <img src={f.url} alt={f.filename} loading="lazy" className="h-full w-full object-cover" />
                            )}
                          </button>
                        </td>
                        <td className="py-2.5 pr-4 font-mono text-xs text-blue-400">
                          <button
                            type="button"
                            onClick={() => setPreviewMedia(f)}
                            className="hover:underline text-left cursor-pointer"
                          >
                            {f.filename}
                          </button>
                        </td>
                        <td className="py-2.5 pr-4 capitalize text-zinc-300">{f.kind}</td>
                        <td className="py-2.5 pr-4 font-mono text-xs text-zinc-400">{formatBytes(f.size_bytes)}</td>
                        <td className="py-2.5 pr-4 text-xs text-zinc-500">{formatTimeAgo(f.created_at)}</td>
                        <td className="py-2.5 text-right">
                          <div className="inline-flex items-center gap-1.5">
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => setPreviewMedia(f)}
                              title="Preview media"
                            >
                              <Eye className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              size="sm"
                              variant="danger"
                              loading={deletingMediaName === f.filename}
                              onClick={() => deleteMediaMut.mutate(f.filename)}
                              title="Delete media"
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
            <PaginationBar
              page={mediaData?.page || mediaPage}
              pageSize={mediaData?.page_size || mediaPageSize}
              total={mediaData?.total || 0}
              totalPages={mediaData?.total_pages || 1}
              onPageChange={(p) => {
                setSelectedMedia(new Set());
                setMediaPage(p);
              }}
              onPageSizeChange={(size) => {
                setSelectedMedia(new Set());
                setMediaPageSize(size);
                setMediaPage(1);
              }}
            />
          </CardContent>
        </Card>
      )}

      {previewMedia && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-xs"
          onClick={() => setPreviewMedia(null)}
        >
          <Card
            className="w-full max-w-4xl border-zinc-700 bg-zinc-900 overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <CardHeader className="flex flex-row items-center justify-between gap-3 border-b border-zinc-800 py-3">
              <div className="min-w-0">
                <CardTitle className="truncate font-mono text-sm text-zinc-100">
                  {previewMedia.filename}
                </CardTitle>
                <p className="text-xs text-zinc-400 capitalize">
                  {previewMedia.kind} · {formatBytes(previewMedia.size_bytes)} · {formatTimeAgo(previewMedia.created_at)}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <a
                  href={previewMedia.url}
                  download={previewMedia.filename}
                  className="inline-flex h-8 items-center gap-1.5 rounded-md border border-zinc-700 bg-zinc-800/70 px-2.5 text-xs font-medium text-zinc-200 hover:bg-zinc-800"
                >
                  <Download className="h-3.5 w-3.5" /> Download
                </a>
                <a
                  href={previewMedia.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex h-8 items-center gap-1.5 rounded-md border border-zinc-700 bg-zinc-800/70 px-2.5 text-xs font-medium text-zinc-200 hover:bg-zinc-800"
                >
                  <ExternalLink className="h-3.5 w-3.5" /> Open
                </a>
                <Button size="sm" variant="ghost" onClick={() => setPreviewMedia(null)} title="Close">
                  <X className="h-4 w-4" />
                </Button>
              </div>
            </CardHeader>
            <CardContent className="flex items-center justify-center bg-zinc-950 p-4">
              {previewMedia.kind === "video" ? (
                <video
                  src={previewMedia.url}
                  controls
                  autoPlay
                  playsInline
                  className="max-h-[75vh] w-full rounded bg-black"
                />
              ) : previewMedia.kind === "audio" ? (
                <div className="flex w-full flex-col items-center justify-center gap-4 py-8">
                  <div className="flex h-20 w-20 items-center justify-center rounded-full border border-zinc-800 bg-zinc-900 text-indigo-400">
                    <Music className="h-10 w-10" />
                  </div>
                  <audio
                    src={previewMedia.url}
                    controls
                    autoPlay
                    className="w-full max-w-lg"
                  />
                </div>
              ) : (
                <img
                  src={previewMedia.url}
                  alt={previewMedia.filename}
                  className="max-h-[75vh] max-w-full rounded object-contain"
                />
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {selectedTaskId && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm"
          onClick={() => setSelectedTaskId(null)}
        >
          <Card
            className="w-full max-w-3xl overflow-hidden border-zinc-700 bg-zinc-900 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <CardHeader className="flex flex-row items-center justify-between gap-3 border-b border-zinc-800 py-3">
              <div className="min-w-0">
                <CardTitle className="truncate font-mono text-sm text-zinc-100">
                  Task Detail · {selectedTaskId}
                </CardTitle>
                {taskDetail && (
                  <p className="mt-0.5 text-xs text-zinc-400">
                    <span className="capitalize">{taskDetail.type}</span> · {taskDetail.model || "-"} ·{" "}
                    {taskDetail.account_label || taskDetail.account_id || "-"} ·{" "}
                    {taskDetail.latency_ms ? `${(taskDetail.latency_ms / 1000).toFixed(1)}s` : "-"}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {taskDetail?.input_request !== null && taskDetail?.input_request !== undefined && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={async () => {
                      const text = JSON.stringify(taskDetail.input_request, null, 2);
                      await navigator.clipboard.writeText(text);
                      setCopiedInputJson(true);
                      toast.success("Copied input request JSON.");
                      setTimeout(() => setCopiedInputJson(false), 1800);
                    }}
                  >
                    {copiedInputJson ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                    {copiedInputJson ? "Copied" : "Copy JSON"}
                  </Button>
                )}
                <Button size="sm" variant="ghost" onClick={() => setSelectedTaskId(null)} title="Close">
                  <X className="h-4 w-4" />
                </Button>
              </div>
            </CardHeader>
            <CardContent className="max-h-[75vh] space-y-4 overflow-y-auto bg-zinc-950 p-4">
              {isLoadingTaskDetail ? (
                <div className="py-8 text-center text-sm text-zinc-400">Loading task details...</div>
              ) : !taskDetail ? (
                <div className="py-8 text-center text-sm text-rose-400">Failed to load task details.</div>
              ) : (
                <>
                  {taskDetail.error_message && (
                    <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-300">
                      <span className="font-semibold">Error:</span> {taskDetail.error_message}
                    </div>
                  )}
                  <div>
                    <div className="mb-1.5 flex items-center justify-between text-xs font-medium text-zinc-400">
                      <span>Input Request</span>
                      <Badge
                        variant={
                          taskDetail.status === "completed"
                            ? "success"
                            : taskDetail.status === "failed"
                            ? "danger"
                            : "warning"
                        }
                      >
                        {taskDetail.status}
                      </Badge>
                    </div>
                    {taskDetail.input_request !== null && taskDetail.input_request !== undefined ? (
                      <pre className="max-h-[52vh] overflow-auto rounded-lg border border-zinc-800 bg-zinc-900/90 p-3 font-mono text-xs text-zinc-200">
                        {JSON.stringify(taskDetail.input_request, null, 2)}
                      </pre>
                    ) : (
                      <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4 text-xs text-zinc-500">
                        No input request recorded for this task.
                        {taskDetail.prompt_preview ? ` Preview: ${taskDetail.prompt_preview}` : ""}
                      </div>
                    )}
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
