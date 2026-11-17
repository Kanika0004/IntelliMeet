import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { LayoutDashboard, ListVideo, LogOut, Menu, Moon, Plus, Search, Settings, Sun, X } from "lucide-react";
import { api } from "../lib/api";
import { cn } from "../lib/format";
import { Button, Kbd } from "./ui";
import { CommandPalette } from "./CommandPalette";
import { useTheme } from "../lib/theme";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/meetings", label: "Meetings", icon: ListVideo },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function Logo({ compact }: { compact?: boolean }) {
  return (
    <Link to="/" className="flex items-center gap-2.5">
      <img src="/favicon.svg" alt="" className="h-7 w-7" />
      {!compact && (
        <span className="text-[15px] font-semibold tracking-tight">
          Intelli<span className="text-accent">Meet</span>
        </span>
      )}
    </Link>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const qc = useQueryClient();
  const { data: stats } = useQuery({ queryKey: ["stats"], queryFn: api.stats, refetchInterval: 5000 });
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me, staleTime: 60_000 });
  const user = me?.user;
  const nav = NAV.filter((n) => n.to !== "/settings" || !me?.auth || user?.is_admin);
  const signOut = async () => {
    await api.logout().catch(() => undefined);
    await qc.refetchQueries({ queryKey: ["me"] });
    qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
  };
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-14 items-center px-4">
        <Logo />
      </div>
      <div className="px-3 pt-2">
        <Link
          to="/new"
          onClick={onNavigate}
          className="flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-accent text-sm font-medium text-accent-fg shadow-sm shadow-indigo-500/20 transition hover:brightness-110"
        >
          <Plus className="h-4 w-4" /> New meeting
        </Link>
      </div>
      <nav className="mt-4 flex-1 space-y-0.5 px-3">
        {nav.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm font-medium transition-colors",
                isActive ? "bg-surface-2 text-fg" : "text-muted hover:bg-surface-2/60 hover:text-fg",
              )
            }
          >
            <Icon className="h-4 w-4" />
            <span className="flex-1">{label}</span>
            {label === "Meetings" && !!stats?.active_jobs && (
              <span className="flex items-center gap-1 rounded-full bg-red-500/10 px-1.5 py-0.5 text-[11px] font-semibold text-red-600 dark:text-red-400">
                <span className="rec-dot h-1.5 w-1.5 rounded-full bg-red-500" />
                {stats.active_jobs}
              </span>
            )}
          </NavLink>
        ))}
      </nav>
      {user ? (
        <div className="m-3 flex items-center gap-2.5 rounded-xl border border-line bg-surface-2/50 p-3">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-sm font-semibold text-accent-text">
            {user.name.charAt(0).toUpperCase()}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-medium">
              {user.name}
              {user.is_admin && <span className="ml-1 text-[10px] font-normal text-muted">(admin)</span>}
            </p>
            <p className="truncate text-[11px] text-muted">{user.email}</p>
          </div>
          <button onClick={signOut} className="text-subtle hover:text-fg" title="Sign out" aria-label="Sign out">
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      ) : (
        <div className="m-3 rounded-xl border border-line bg-surface-2/50 p-3">
          <p className="text-xs font-medium">B.Tech CSE Major Project</p>
          <p className="mt-0.5 text-[11px] leading-snug text-muted">AI meeting assistant: record, transcribe, summarize and ask questions.</p>
        </div>
      )}
    </div>
  );
}

export function Layout() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const { theme, toggle } = useTheme();
  const location = useLocation();

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const { data: cfg } = useQuery({ queryKey: ["config"], queryFn: api.config, staleTime: Infinity });
  return (
    <div className="min-h-screen">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 border-r border-line bg-surface lg:block">
        <Sidebar />
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 border-r border-line bg-surface animate-fade-in">
            <button className="absolute right-3 top-4 text-muted" onClick={() => setMobileOpen(false)} aria-label="Close menu">
              <X className="h-5 w-5" />
            </button>
            <Sidebar onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      <div className="lg:pl-60">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-line bg-bg/80 px-4 backdrop-blur-md sm:px-6">
          <button className="text-muted lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open menu">
            <Menu className="h-5 w-5" />
          </button>
          <div className="lg:hidden">
            <Logo compact />
          </div>
          <button
            onClick={() => setPaletteOpen(true)}
            className="flex h-9 w-full max-w-sm items-center gap-2 rounded-lg border border-line bg-surface px-3 text-sm text-subtle transition hover:border-subtle/60"
          >
            <Search className="h-4 w-4" />
            <span className="flex-1 text-left">Search meetings…</span>
            <span className="hidden sm:flex gap-0.5">
              <Kbd>Ctrl</Kbd>
              <Kbd>K</Kbd>
            </span>
          </button>
          <div className="ml-auto flex items-center gap-1">
            <Button variant="ghost" size="icon" onClick={toggle} aria-label="Toggle theme" title="Toggle theme">
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
            <Link to="/new" className="sm:hidden">
              <Button size="icon" aria-label="New meeting">
                <Plus className="h-4 w-4" />
              </Button>
            </Link>
          </div>
        </header>
        {cfg?.demo && (
          <div className="border-b border-amber-300/60 bg-amber-50 px-4 py-2 text-center text-xs text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200 sm:px-6">
            Hosted demo: explore the sample meetings, upload a transcript (.txt, .vtt, .srt) and use Ask AI. The Google Meet
            bot and audio recording run only when IntelliMeet is installed on your own computer.
          </div>
        )}
        <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 sm:py-8">
          <Outlet />
        </main>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}
