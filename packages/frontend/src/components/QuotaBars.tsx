import { Clock, Sparkles, Zap } from "lucide-react";

export interface QuotaInfo {
  plan?: string;
  weekly_pct?: number;
  extra_pct?: number;
  extra_remaining?: string;
  weekly_reset?: string;
  checked_at?: number;
}

function barColor(remPct: number): string {
  if (remPct >= 30) return "bg-emerald-400";
  if (remPct >= 10) return "bg-amber-400";
  return "bg-rose-500";
}

function textColor(remPct: number): string {
  if (remPct >= 30) return "text-emerald-400";
  if (remPct >= 10) return "text-amber-400";
  return "text-rose-400";
}

function shortReset(reset?: string): string {
  if (!reset) return "Weekly";
  const m = reset.match(/on\s+(.+)$/i);
  return m ? m[1] : reset;
}

function shortExtraLeft(extraRemaining?: string): string {
  if (!extraRemaining) return "Extra";
  const m = extraRemaining.match(/\(([^)]+)\)/);
  return m ? m[1].replace(/\s*tokens\s*/i, " ").trim() : extraRemaining;
}

export function QuotaBars({ quota }: { quota?: QuotaInfo }) {
  if (!quota || (!quota.plan && typeof quota.weekly_pct !== "number" && !quota.extra_remaining)) {
    return <span className="text-xs text-zinc-500">Not checked</span>;
  }

  const weeklyRem = typeof quota.weekly_pct === "number" ? Math.max(0, Math.min(100, 100 - quota.weekly_pct)) : null;
  const extraRem = typeof quota.extra_pct === "number" ? Math.max(0, Math.min(100, 100 - quota.extra_pct)) : null;

  return (
    <div className="flex flex-col gap-1.5 w-full max-w-[205px]">
      {weeklyRem !== null && (
        <div className="relative overflow-hidden rounded-md border border-zinc-800/90 bg-zinc-950/90 px-2.5 pt-1.5 pb-2">
          <div className="flex items-center justify-between gap-2 text-[11px] leading-none">
            <span className="inline-flex items-center gap-1 text-zinc-300 truncate">
              <Sparkles className="h-3 w-3 shrink-0 text-blue-400" />
              <Clock className="h-3 w-3 shrink-0 text-amber-400" />
              <span className="truncate">{shortReset(quota.weekly_reset)}</span>
            </span>
            <span className={`font-mono font-semibold ${textColor(weeklyRem)}`}>{weeklyRem}%</span>
          </div>
          <div className="absolute bottom-0 left-0 right-0 h-[3px] bg-zinc-800">
            <div
              className={`h-full transition-all ${barColor(weeklyRem)}`}
              style={{ width: `${weeklyRem}%` }}
            />
          </div>
        </div>
      )}

      {extraRem !== null && (
        <div className="relative overflow-hidden rounded-md border border-zinc-800/90 bg-zinc-950/90 px-2.5 pt-1.5 pb-2">
          <div className="flex items-center justify-between gap-2 text-[11px] leading-none">
            <span className="inline-flex items-center gap-1 text-zinc-300 truncate">
              <Zap className="h-3 w-3 shrink-0 text-emerald-400" />
              <span className="truncate">{shortExtraLeft(quota.extra_remaining)}</span>
            </span>
            <span className={`font-mono font-semibold ${textColor(extraRem)}`}>{extraRem}%</span>
          </div>
          <div className="absolute bottom-0 left-0 right-0 h-[3px] bg-zinc-800">
            <div
              className={`h-full transition-all ${barColor(extraRem)}`}
              style={{ width: `${extraRem}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
