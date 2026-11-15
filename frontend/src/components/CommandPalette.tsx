import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CornerDownLeft, LayoutDashboard, ListVideo, Plus, Search, Settings } from "lucide-react";
import { api } from "../lib/api";
import { cn, relativeTime } from "../lib/format";
import { Dialog, Kbd } from "./ui";
import { SourceIcon, StatusBadge } from "./meeting";

interface Item {
  id: string;
  label: string;
  hint?: string;
  icon: React.ReactNode;
  run: () => void;
  extra?: React.ReactNode;
}

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const { data: meetings = [] } = useQuery({
    queryKey: ["meetings", { q, status: "" }],
    queryFn: () => api.meetings({ q }),
    enabled: open,
  });

  useEffect(() => {
    if (open) {
      setQ("");
      setActive(0);
      setTimeout(() => inputRef.current?.focus(), 10);
    }
  }, [open]);

  const go = (to: string) => () => {
    navigate(to);
    onClose();
  };

  const items: Item[] = useMemo(() => {
    const pages: Item[] = [
      { id: "new", label: "New meeting", hint: "Send bot or upload", icon: <Plus className="h-4 w-4" />, run: go("/new") },
      { id: "dash", label: "Dashboard", icon: <LayoutDashboard className="h-4 w-4" />, run: go("/") },
      { id: "list", label: "All meetings", icon: <ListVideo className="h-4 w-4" />, run: go("/meetings") },
      { id: "set", label: "Settings", icon: <Settings className="h-4 w-4" />, run: go("/settings") },
    ].filter((p) => !q || p.label.toLowerCase().includes(q.toLowerCase()));
    const ms: Item[] = meetings.slice(0, 8).map((m) => ({
      id: m.id,
      label: m.title,
      hint: relativeTime(m.created_at),
      icon: <SourceIcon source={m.source} className="h-7 w-7 rounded-md" />,
      run: go(`/meetings/${m.id}`),
      extra: m.status !== "completed" ? <StatusBadge status={m.status} /> : undefined,
    }));
    return [...ms, ...pages];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meetings, q]);

  useEffect(() => {
    setActive(0);
  }, [q]);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, items.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      items[active]?.run();
    }
  };

  const meetingCount = Math.min(meetings.length, 8);

  return (
    <Dialog open={open} onClose={onClose} className="max-w-xl overflow-hidden">
      <div className="flex items-center gap-2 border-b border-line px-4">
        <Search className="h-4 w-4 text-subtle" />
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={onKey}
          placeholder="Search titles, transcripts, summaries…"
          className="h-12 flex-1 bg-transparent text-sm outline-none placeholder:text-subtle"
        />
        <Kbd>Esc</Kbd>
      </div>
      <div className="max-h-[50vh] overflow-y-auto p-2">
        {items.length === 0 && <p className="px-3 py-8 text-center text-sm text-muted">No results for “{q}”</p>}
        {items.map((it, i) => (
          <div key={it.id}>
            {i === 0 && meetingCount > 0 && <p className="px-2 pb-1 pt-1 text-[11px] font-medium uppercase tracking-wide text-subtle">Meetings</p>}
            {i === meetingCount && <p className="px-2 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-subtle">Go to</p>}
            <button
              onMouseEnter={() => setActive(i)}
              onClick={it.run}
              className={cn("flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left text-sm", i === active && "bg-surface-2")}
            >
              <span className="text-muted">{it.icon}</span>
              <span className="flex-1 truncate">{it.label}</span>
              {it.extra}
              {it.hint && <span className="text-xs text-subtle">{it.hint}</span>}
              {i === active && <CornerDownLeft className="h-3.5 w-3.5 text-subtle" />}
            </button>
          </div>
        ))}
      </div>
    </Dialog>
  );
}
