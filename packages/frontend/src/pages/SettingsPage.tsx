import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, RotateCcw, Save } from "lucide-react";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Checkbox,
  Input,
  Switch,
  Textarea,
} from "../components/ui";
import { useToast } from "../components/Toast";
import { apiFetch, formatBytes } from "../lib/api";

interface SettingsData {
  system_prompt: { enabled: boolean; prompt: string };
  media_cleanup: {
    enabled: boolean;
    retention_days: number;
    max_gb: number;
    interval_minutes: number;
  };
  auto_reset?: { enabled: boolean; interval_minutes: number };
  default_system_prompt: string;
  voice_languages?: { enabled: boolean; languages: string[] };
  available_voice_languages?: { name: string; count: number }[];
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
  const [vlEnabled, setVlEnabled] = useState(false);
  const [vlSelected, setVlSelected] = useState<Set<string>>(new Set());
  const [arEnabled, setArEnabled] = useState(false);
  const [arIntervalMin, setArIntervalMin] = useState(1440);

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
      setVlEnabled(data.voice_languages?.enabled ?? false);
      setVlSelected(new Set(data.voice_languages?.languages ?? []));
      setArEnabled(data.auto_reset?.enabled ?? false);
      setArIntervalMin(data.auto_reset?.interval_minutes ?? 1440);
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

  const saveVoiceLanguagesMut = useMutation({
    mutationFn: () =>
      apiFetch("/admin/settings", {
        method: "POST",
        body: JSON.stringify({
          voice_languages: {
            enabled: vlEnabled,
            languages: Array.from(vlSelected),
          },
        }),
      }),
    onSuccess: () => {
      toast.success("Voice languages setting saved.");
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (err: Error) => toast.error(`Save failed: ${err.message}`),
  });

  const cleanupMut = useMutation({
    mutationFn: () =>
      apiFetch<{ deleted_files: number; freed_bytes: number }>("/admin/cleanup/run", {
        method: "POST",
      }),
    onSuccess: (res) => {
      toast.success(
        `Cleanup finished: deleted ${res.deleted_files} files (${formatBytes(res.freed_bytes)} freed).`,
      );
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["media"] });
    },
    onError: (err: Error) => toast.error(`Cleanup failed: ${err.message}`),
  });

  const saveAutoResetMut = useMutation({
    mutationFn: () =>
      apiFetch("/admin/settings", {
        method: "POST",
        body: JSON.stringify({
          auto_reset: {
            enabled: arEnabled,
            interval_minutes: Math.max(60, arIntervalMin),
          },
        }),
      }),
    onSuccess: () => {
      toast.success("Auto Reset Muse policy saved.");
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (err: Error) => toast.error(`Save failed: ${err.message}`),
  });

  const runDueResetsMut = useMutation({
    mutationFn: () =>
      apiFetch<{ ok: boolean; triggered_ids: string[] }>("/admin/accounts/reset-due", {
        method: "POST",
      }),
    onSuccess: (res) => {
      const count = res.triggered_ids?.length || 0;
      if (count > 0) {
        toast.info(`Started Auto Reset for ${count} due account(s).`);
        qc.invalidateQueries({ queryKey: ["accounts"] });
        qc.invalidateQueries({ queryKey: ["dashboard"] });
      } else {
        toast.info("No eligible due accounts to reset right now.");
      }
    },
    onError: (err: Error) => toast.error(`Run due resets failed: ${err.message}`),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-white">Settings</h1>
        <p className="text-sm text-zinc-400">
          Configure Global System Prompt and automatic Media Cleanup policy.
        </p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Global System Prompt</CardTitle>
              <CardDescription>
                Prepend a &lt;system&gt;...&lt;/system&gt; block to all /v1/* requests.
              </CardDescription>
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
              <CardTitle>Voice Languages</CardTitle>
              <CardDescription>
                Filter /v1/audio/voices and /v1/audio/speech by selected languages (leave off or
                empty to allow all voices).
              </CardDescription>
            </div>
            <Switch checked={vlEnabled} onCheckedChange={setVlEnabled} />
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2">
            {(data?.available_voice_languages || []).map((lang) => {
              const checked = vlSelected.has(lang.name);
              return (
                <label
                  key={lang.name}
                  title={`${lang.name} (${lang.count} voices)`}
                  className={`flex items-center gap-2 rounded-lg border p-2 text-xs cursor-pointer select-none transition-colors ${
                    checked
                      ? "border-blue-500/60 bg-blue-500/10 text-zinc-100"
                      : "border-zinc-800 bg-zinc-950/60 text-zinc-400 hover:border-zinc-700 hover:text-zinc-200"
                  }`}
                >
                  <Checkbox
                    checked={checked}
                    onCheckedChange={() => {
                      setVlSelected((prev) => {
                        const next = new Set(prev);
                        if (next.has(lang.name)) next.delete(lang.name);
                        else next.add(lang.name);
                        return next;
                      });
                    }}
                  />
                  <span className="truncate font-medium">{lang.name}</span>
                  <span className="ml-auto font-mono text-[10px] text-zinc-500">
                    ({lang.count})
                  </span>
                </label>
              );
            })}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-zinc-800/80 pt-3">
            <div className="text-xs text-zinc-400">
              Selected: <span className="font-mono text-zinc-200">{vlSelected.size}</span> languages
              (
              <span className="font-mono text-zinc-200">
                {vlEnabled && vlSelected.size > 0
                  ? (data?.available_voice_languages || [])
                      .filter((l) => vlSelected.has(l.name))
                      .reduce((sum, l) => sum + l.count, 0)
                  : (data?.available_voice_languages || []).reduce((sum, l) => sum + l.count, 0)}
              </span>{" "}
              voices allowed)
            </div>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() =>
                  setVlSelected(new Set((data?.available_voice_languages || []).map((l) => l.name)))
                }
              >
                Select All
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setVlSelected(new Set())}
              >
                Clear
              </Button>
              <Button
                type="button"
                size="sm"
                loading={saveVoiceLanguagesMut.isPending}
                onClick={() => saveVoiceLanguagesMut.mutate()}
              >
                <Save className="h-4 w-4" /> Save Voice Languages
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Media Cleanup Policy</CardTitle>
              <CardDescription>
                Automatic retention and capacity enforcement for data/media/.
              </CardDescription>
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
            <Button
              variant="outline"
              loading={cleanupMut.isPending}
              onClick={() => cleanupMut.mutate()}
            >
              <Play className="h-4 w-4" /> Run Cleanup Now
            </Button>
            <Button loading={saveCleanupMut.isPending} onClick={() => saveCleanupMut.mutate()}>
              <Save className="h-4 w-4" /> Save Cleanup Policy
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Auto Reset Muse</CardTitle>
              <CardDescription>
                Periodically reset eligible accounts with Auto Reset enabled and
                requests_since_reset &gt; 0.
              </CardDescription>
            </div>
            <Switch checked={arEnabled} onCheckedChange={setArEnabled} />
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="max-w-xs space-y-1.5">
            <label className="text-xs font-medium text-zinc-300">Interval (Minutes, min 60)</label>
            <Input
              type="number"
              min={60}
              value={arIntervalMin}
              onChange={(e) => setArIntervalMin(Number(e.target.value))}
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              loading={runDueResetsMut.isPending}
              onClick={() => runDueResetsMut.mutate()}
            >
              <Play className="h-4 w-4" /> Run Due Resets Now
            </Button>
            <Button loading={saveAutoResetMut.isPending} onClick={() => saveAutoResetMut.mutate()}>
              <Save className="h-4 w-4" /> Save Auto Reset
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
