import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, RotateCcw, Save } from "lucide-react";
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, Switch, Textarea } from "../components/ui";
import { useToast } from "../components/Toast";
import { apiFetch, formatBytes } from "../lib/api";

interface SettingsData {
  system_prompt: { enabled: boolean; prompt: string };
  media_cleanup: { enabled: boolean; retention_days: number; max_gb: number; interval_minutes: number };
  default_system_prompt: string;
}

export function SettingsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [spEnabled, setSpEnabled] = useState(false);
  const [spPrompt, setSpPrompt] = useState("");
  const [mcEnabled, setMcEnabled] = useState(true);
  const [retentionDays, setRetentionDays] = useState(1);
  const [maxGb, setMaxGb] = useState(1);
  const [intervalMin, setIntervalMin] = useState(60);

  const { data } = useQuery({
    queryKey: ["settings"],
    queryFn: () => apiFetch<SettingsData>("/admin/settings"),
  });

  useEffect(() => {
    if (data) {
      setSpEnabled(data.system_prompt?.enabled ?? false);
      setSpPrompt(data.system_prompt?.prompt ?? "");
      setMcEnabled(data.media_cleanup?.enabled ?? true);
      setRetentionDays(data.media_cleanup?.retention_days ?? 1);
      setMaxGb(data.media_cleanup?.max_gb ?? 1);
      setIntervalMin(data.media_cleanup?.interval_minutes ?? 60);
    }
  }, [data]);

  const savePromptMut = useMutation({
    mutationFn: () =>
      apiFetch("/admin/settings", {
        method: "POST",
        body: JSON.stringify({ system_prompt: { enabled: spEnabled, prompt: spPrompt } }),
      }),
    onSuccess: () => {
      toast.success("Global system prompt saved.");
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (err: Error) => toast.error(`Save failed: ${err.message}`),
  });

  const saveCleanupMut = useMutation({
    mutationFn: () =>
      apiFetch("/admin/settings", {
        method: "POST",
        body: JSON.stringify({
          media_cleanup: {
            enabled: mcEnabled,
            retention_days: retentionDays,
            max_gb: maxGb,
            interval_minutes: Math.max(5, intervalMin),
          },
        }),
      }),
    onSuccess: () => {
      toast.success("Media cleanup policy saved.");
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (err: Error) => toast.error(`Save failed: ${err.message}`),
  });

  const cleanupMut = useMutation({
    mutationFn: () => apiFetch<{ deleted_files: number; freed_bytes: number }>("/admin/cleanup/run", { method: "POST" }),
    onSuccess: (res) => {
      toast.success(`Cleanup finished: deleted ${res.deleted_files} files (${formatBytes(res.freed_bytes)} freed).`);
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["media"] });
    },
    onError: (err: Error) => toast.error(`Cleanup failed: ${err.message}`),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-white">Settings</h1>
        <p className="text-sm text-zinc-400">Configure Global System Prompt and automatic Media Cleanup policy.</p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Global System Prompt</CardTitle>
              <CardDescription>Prepend a &lt;system&gt;...&lt;/system&gt; block to all /v1/* requests.</CardDescription>
            </div>
            <Switch checked={spEnabled} onCheckedChange={setSpEnabled} />
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <Textarea rows={5} value={spPrompt} onChange={(e) => setSpPrompt(e.target.value)} />
          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              onClick={() => {
                if (data?.default_system_prompt) {
                  setSpPrompt(data.default_system_prompt);
                  toast.info("Reset prompt to default (click Save to apply).");
                }
              }}
            >
              <RotateCcw className="h-4 w-4" /> Reset Default
            </Button>
            <Button loading={savePromptMut.isPending} onClick={() => savePromptMut.mutate()}>
              <Save className="h-4 w-4" /> Save Prompt
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Media Cleanup Policy</CardTitle>
              <CardDescription>Automatic retention and capacity enforcement for data/media/.</CardDescription>
            </div>
            <Switch checked={mcEnabled} onCheckedChange={setMcEnabled} />
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-zinc-300">Retention (Days, 0 = off)</label>
              <Input
                type="number"
                min={0}
                value={retentionDays}
                onChange={(e) => setRetentionDays(Number(e.target.value))}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-zinc-300">Max Storage (GB, 0 = off)</label>
              <Input
                type="number"
                step="0.1"
                min={0}
                value={maxGb}
                onChange={(e) => setMaxGb(Number(e.target.value))}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-zinc-300">Interval (Minutes, min 5)</label>
              <Input
                type="number"
                min={5}
                value={intervalMin}
                onChange={(e) => setIntervalMin(Number(e.target.value))}
              />
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" loading={cleanupMut.isPending} onClick={() => cleanupMut.mutate()}>
              <Play className="h-4 w-4" /> Run Cleanup Now
            </Button>
            <Button loading={saveCleanupMut.isPending} onClick={() => saveCleanupMut.mutate()}>
              <Save className="h-4 w-4" /> Save Cleanup Policy
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
