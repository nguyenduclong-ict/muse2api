import React from "react";
import { NavLink } from "react-router-dom";
import { Activity, Globe, KeyRound, LayoutDashboard, ListTodo, PlayCircle, Settings, Users, Radio } from "lucide-react";
import { cn } from "./ui";

const NAV_ITEMS: { to: string; label: string; icon: React.ComponentType<{ className?: string }>; end?: boolean }[] = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/accounts", label: "Accounts", icon: Users },
  { to: "/proxies", label: "Proxies", icon: Globe },
  { to: "/api-keys", label: "API & Keys", icon: KeyRound },
  { to: "/playground", label: "Playground", icon: PlayCircle },
  { to: "/tasks", label: "Tasks & Media", icon: ListTodo },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function Layout({
  activeTunnels,
  healthyAccounts,
  children,
}: {
  activeTunnels: number;
  healthyAccounts: number;
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-screen overflow-hidden bg-zinc-950 text-zinc-100">
      {/* Sidebar */}
      <aside className="flex w-64 shrink-0 flex-col border-r border-zinc-800/80 bg-zinc-950/90">
        <div className="flex h-14 items-center gap-2.5 border-b border-zinc-800/80 px-5">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
            <Radio className="h-4 w-4" />
          </div>
          <div>
            <div className="text-sm font-semibold tracking-tight text-zinc-100">muse2apiv2</div>
            <div className="text-[10px] font-mono text-zinc-500">WSS Noise Gateway</div>
          </div>
        </div>

        <nav className="flex-1 space-y-1 p-3">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cn(
                    "flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-zinc-800/90 text-white shadow-sm"
                      : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200"
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <Icon className={cn("h-4 w-4", isActive ? "text-emerald-400" : "text-zinc-500")} />
                    {item.label}
                  </>
                )}
              </NavLink>
            );
          })}
        </nav>

        <div className="border-t border-zinc-800/80 p-4 space-y-2 text-xs">
          <div className="flex items-center justify-between text-zinc-400">
            <span className="flex items-center gap-1.5">
              <Activity className="h-3.5 w-3.5 text-emerald-400" />
              Healthy Pool
            </span>
            <span className="font-mono text-zinc-200">{healthyAccounts}</span>
          </div>
          <div className="flex items-center justify-between text-zinc-400">
            <span>WSS Tunnels</span>
            <span className="font-mono text-emerald-400">{activeTunnels} active</span>
          </div>
        </div>
      </aside>

      {/* Main Content (overflow-y-scroll prevents horizontal shift across routes) */}
      <main className="flex-1 overflow-y-scroll">
        <div className="mx-auto max-w-6xl p-6 md:p-8">{children}</div>
      </main>
    </div>
  );
}
