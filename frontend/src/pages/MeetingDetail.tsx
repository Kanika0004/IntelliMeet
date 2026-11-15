import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowUp,
  Calendar,
  Check,
  ChevronDown,
  Clock,
  Copy,
  Download,
  ExternalLink,
  FileText,
  Gavel,
  Lightbulb,
  ListChecks,
  MessageSquare,
  Pencil,
  RotateCcw,
  Search,
  Sparkles,
  Square,
  Trash2,
  User,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { api, ACTIVE_STATUSES, type ActionItem, type MeetingDetail as Meeting, type Sentiment } from "../lib/api";
import { cn, formatDate, formatDuration, timestamp } from "../lib/format";
import { Badge, Button, Card, CardHeader, ConfirmDialog, EmptyState, Input, Progress, Skeleton, Tabs } from "../components/ui";
import { Avatar, Markdown, PipelineStepper, SentimentBadge, StatusBadge, sourceLabel } from "../components/meeting";
import { BotAccount } from "../components/BotAccount";

/* ======================================================== Action item row */
export function ActionItemRow({ meetingId, index, item, footer }: { meetingId: string; index: number; item: ActionItem; footer?: ReactNode }) {
  const qc = useQueryClient();
  const [done, setDone] = useState(item.done);
  useEffect(() => {
    setDone(item.done);
  }, [item.done]);
  const toggle = useMutation({
    mutationFn: (v: boolean) => api.toggleAction(meetingId, index, v),
    onMutate: (v) => setDone(v),
    onError: (e: Error) => {
      setDone(item.done);
      toast.error(e.message);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["meeting", meetingId] });
      qc.invalidateQueries({ queryKey: ["action-items"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
      qc.invalidateQueries({ queryKey: ["meetings"] });
    },
  });
  return (
    <label className="group flex cursor-pointer gap-3 rounded-lg px-3 py-2.5 transition hover:bg-surface-2/60">
      <button
        type="button"
        role="checkbox"
        aria-checked={done}
        onClick={() => toggle.mutate(!done)}
        className={cn(
          "mt-0.5 grid h-[18px] w-[18px] shrink-0 place-items-center rounded-[5px] border transition",
          done ? "border-accent bg-accent text-white" : "border-subtle/60 group-hover:border-accent",
        )}
      >
        {done && <Check className="h-3 w-3" strokeWidth={3} />}
      </button>
      <div className="min-w-0 flex-1" onClick={() => toggle.mutate(!done)}>
        <p className={cn("text-sm leading-snug transition", done && "text-subtle line-through")}>{item.task}</p>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
          {item.owner && (
            <span className="flex items-center gap-1">
              <User className="h-3 w-3" /> {item.owner}
            </span>
          )}
          {item.due && (
            <span className="flex items-center gap-1">
              <Calendar className="h-3 w-3" /> {item.due}
            </span>
          )}
          {footer && <span className="min-w-0 truncate" onClick={(e) => e.stopPropagation()}>{footer}</span>}
        </div>
      </div>
    </label>
  );
}

/* ============================================================== Sentiment */
function SentimentCard({ s }: { s: Sentiment }) {
  const pct = ((s.score + 1) / 2) * 100;
  return (
    <Card>
      <CardHeader title="Sentiment" action={<SentimentBadge sentiment={s} />} />
      <div className="px-5 pb-5">
        <div className="relative h-2 rounded-full bg-gradient-to-r from-red-400 via-zinc-300 to-emerald-400 dark:via-zinc-600">
          <div className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-fg shadow dark:border-zinc-900" style={{ left: `${pct}%` }} />
        </div>
        <div className="mt-1.5 flex justify-between text-[11px] text-subtle">
          <span>Negative</span>
          <span>Neutral</span>
          <span>Positive</span>
        </div>
        {s.explanation && <p className="mt-3 text-[13px] leading-relaxed text-muted">{s.explanation}</p>}
      </div>
    </Card>
  );
}

/* =============================================================== Overview */
function Overview({ m, onRegenerate, regenerating }: { m: Meeting; onRegenerate?: () => void; regenerating?: boolean }) {
  const a = m.analysis;
  if (!a)
    return (
      <EmptyState
        icon={<Sparkles className="h-5 w-5" />}
        title="AI analysis was turned off"
        description="This meeting was processed without analysis. The transcript and Ask AI are still available."
      />
    );
  const done = a.action_items.filter((i) => i.done).length;
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
      <div className="space-y-4">
        {(a.warning || a.provider?.startsWith("offline") || a.provider === "basic") && (
          <div className="flex flex-wrap items-start gap-3 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
            <div className="min-w-0 flex-1 text-sm">
              <p className="font-medium">This summary was made by the basic offline analyzer</p>
              <p className="mt-0.5 break-words text-[13px] text-muted">
                {a.warning ?? "No AI provider is configured."} Results are much better with the AI model. Fix the AI settings if needed, then click Regenerate summary.
              </p>
            </div>
            {onRegenerate && (
              <Button size="sm" onClick={onRegenerate} loading={regenerating}>
                <Sparkles className="h-3.5 w-3.5" /> Regenerate summary
              </Button>
            )}
          </div>
        )}
        <Card>
          <CardHeader title="Summary" icon={<FileText className="h-4 w-4" />} action={<CopyButton text={a.summary} />} />
          <p className="px-5 pb-5 text-[15px] leading-relaxed">{a.summary}</p>
        </Card>

        <Card>
          <CardHeader
            title="Action items"
            icon={<ListChecks className="h-4 w-4" />}
            description={a.action_items.length ? `${done} of ${a.action_items.length} done` : undefined}
          />
          {a.action_items.length ? (
            <>
              <div className="px-5">
                <Progress value={done / a.action_items.length} />
              </div>
              <div className="px-2 py-2">
                {a.action_items.map((it, i) => (
                  <ActionItemRow key={i} meetingId={m.id} index={i} item={it} />
                ))}
              </div>
            </>
          ) : (
            <p className="px-5 pb-5 text-sm text-muted">No action items were identified.</p>
          )}
        </Card>

        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader title="Key points" icon={<Lightbulb className="h-4 w-4" />} />
            <ul className="space-y-2.5 px-5 pb-5">
              {a.key_points.map((p, i) => (
                <li key={i} className="flex gap-2.5 text-sm leading-snug">
                  <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                  {p}
                </li>
              ))}
              {!a.key_points.length && <li className="text-sm text-muted">None identified.</li>}
            </ul>
          </Card>
          <Card>
            <CardHeader title="Decisions" icon={<Gavel className="h-4 w-4" />} />
            <ul className="space-y-2.5 px-5 pb-5">
              {a.decisions.map((p, i) => (
                <li key={i} className="flex gap-2.5 text-sm leading-snug">
                  <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
                  {p}
                </li>
              ))}
              {!a.decisions.length && <li className="text-sm text-muted">No explicit decisions were recorded.</li>}
            </ul>
          </Card>
        </div>
      </div>

      <div className="space-y-4">
        <SentimentCard s={a.sentiment} />
        {a.topics.length > 0 && (
          <Card>
            <CardHeader title="Topics" />
            <div className="flex flex-wrap gap-1.5 px-5 pb-5">
              {a.topics.map((t) => (
                <Link key={t} to={`/meetings?q=${encodeURIComponent(t)}`}>
                  <Badge tone="accent" className="hover:brightness-95">
                    {t}
                  </Badge>
                </Link>
              ))}
            </div>
          </Card>
        )}
        <DetailsCard m={m} />
      </div>
    </div>
  );
}

function DetailsCard({ m }: { m: Meeting }) {
  const rows: [string, ReactNode][] = [
    ["Source", sourceLabel(m.source)],
    ["Started", formatDate(m.started_at ?? m.created_at, { year: "numeric" })],
    ["Duration", formatDuration(m.duration_seconds)],
    ["Language", m.transcript?.language?.toUpperCase() ?? "—"],
    ["Analyzed by", m.analysis?.provider ?? "—"],
  ];
  if (m.original_filename) rows.splice(1, 0, ["File", m.original_filename]);
  return (
    <Card>
      <CardHeader title="Details" />
      <dl className="space-y-2.5 px-5 pb-5 text-[13px]">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-4">
            <dt className="text-muted">{k}</dt>
            <dd className="truncate text-right font-medium">{v}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

/* ============================================================= Transcript */
function highlight(text: string, q: string): ReactNode {
  if (!q) return text;
  const parts = text.split(new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi"));
  return parts.map((p, i) => (p.toLowerCase() === q.toLowerCase() ? <mark key={i}>{p}</mark> : p));
}

function TranscriptView({ m }: { m: Meeting }) {
  const [q, setQ] = useState("");
  const [time, setTime] = useState(0);
  const audioRef = useRef<HTMLAudioElement>(null);
  const segs = m.transcript?.segments ?? [];
  const matches = useMemo(() => (q ? segs.filter((s) => s.text.toLowerCase().includes(q.toLowerCase())).length : 0), [q, segs]);
  const shown = q ? segs.filter((s) => s.text.toLowerCase().includes(q.toLowerCase()) || s.speaker?.toLowerCase().includes(q.toLowerCase())) : segs;
  const fullText = segs.map((s) => `[${timestamp(s.start)}] ${s.speaker ? `${s.speaker}: ` : ""}${s.text}`).join("\n") || m.transcript?.text || "";

  const seek = (t: number) => {
    if (audioRef.current) {
      audioRef.current.currentTime = t;
      audioRef.current.play();
    }
  };

  if (!m.transcript) return <EmptyState icon={<FileText className="h-5 w-5" />} title="No transcript" />;

  return (
    <Card className="overflow-hidden">
      <div className="space-y-3 border-b border-line p-4">
        {m.has_audio && <audio ref={audioRef} controls src={api.audioUrl(m.id)} onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)} className="h-10 w-full" />}
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search transcript…" className="h-9 pl-9" />
          </div>
          {q && <span className="whitespace-nowrap text-xs text-muted">{matches} match{matches === 1 ? "" : "es"}</span>}
          <CopyButton text={fullText} label="Copy" />
        </div>
      </div>
      <div className="max-h-[calc(100vh-17rem)] min-h-[320px] divide-y divide-line/60 overflow-y-auto">
        {shown.map((s, i) => {
          const active = m.has_audio && time >= s.start && time < s.end;
          return (
            <div key={i} className={cn("flex gap-3 px-4 py-3 transition-colors sm:px-5", active && "bg-accent-soft/60")}>
              {s.speaker ? <Avatar name={s.speaker} size="sm" /> : <span className="h-6 w-6 shrink-0" />}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  {s.speaker && <span className="text-[13px] font-semibold">{highlight(s.speaker, q)}</span>}
                  <button
                    onClick={() => seek(s.start)}
                    disabled={!m.has_audio}
                    className={cn("font-mono text-[11px] text-subtle", m.has_audio && "hover:text-accent-text hover:underline")}
                    title={m.has_audio ? "Play from here" : undefined}
                  >
                    {timestamp(s.start)}
                  </button>
                </div>
                <p className="mt-0.5 text-sm leading-relaxed">{highlight(s.text, q)}</p>
              </div>
            </div>
          );
        })}
        {!segs.length && <p className="whitespace-pre-wrap p-5 text-sm leading-relaxed">{highlight(m.transcript.text, q)}</p>}
        {q && shown.length === 0 && <p className="p-8 text-center text-sm text-muted">No lines match “{q}”.</p>}
      </div>
    </Card>
  );
}

/* ================================================================= Ask AI */
const SUGGESTIONS = ["What were the main decisions?", "Who is responsible for what?", "What risks or concerns came up?", "Write a follow-up email to the team"];

function AskAI({ m }: { m: Meeting }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const { data: messages = [], isLoading } = useQuery({ queryKey: ["chat", m.id], queryFn: () => api.chat(m.id) });

  const ask = useMutation({
    mutationFn: (q: string) => api.ask(m.id, q),
    onMutate: (q) => setPending(q),
    onSettled: () => {
      setPending(null);
      qc.invalidateQueries({ queryKey: ["chat", m.id] });
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const clear = useMutation({ mutationFn: () => api.clearChat(m.id), onSuccess: () => qc.invalidateQueries({ queryKey: ["chat", m.id] }) });

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, pending]);

  const send = (q: string) => {
    q = q.trim();
    if (!q || ask.isPending) return;
    setText("");
    ask.mutate(q);
    taRef.current?.focus();
  };

  const empty = !isLoading && messages.length === 0 && !pending;

  return (
    <Card className="flex h-[calc(100vh-15rem)] min-h-[480px] flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-line px-5 py-3">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Sparkles className="h-4 w-4 text-accent" /> Ask about this meeting
        </div>
        {messages.length > 0 && (
          <Button variant="ghost" size="sm" onClick={() => clear.mutate()}>
            <RotateCcw className="h-3.5 w-3.5" /> Clear
          </Button>
        )}
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-6">
        {empty ? (
          <div className="mx-auto flex h-full max-w-md flex-col items-center justify-center text-center">
            <div className="grid h-12 w-12 place-items-center rounded-2xl bg-accent-soft text-accent-text">
              <MessageSquare className="h-5 w-5" />
            </div>
            <h3 className="mt-4 text-sm font-semibold">Chat with your meeting</h3>
            <p className="mt-1 text-[13px] text-muted">Answers are grounded in this meeting's transcript.</p>
            <div className="mt-5 grid w-full gap-2 sm:grid-cols-2">
              {SUGGESTIONS.map((s) => (
                <button key={s} onClick={() => send(s)} className="rounded-lg border border-line px-3 py-2.5 text-left text-[13px] text-muted transition hover:border-accent/50 hover:text-fg">
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto max-w-3xl space-y-5">
            {messages.map((msg) => (
              <Bubble key={msg.id} role={msg.role} content={msg.content} />
            ))}
            {pending && (
              <>
                <Bubble role="user" content={pending} />
                <div className="flex gap-3">
                  <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-accent text-white">
                    <Sparkles className="h-3.5 w-3.5" />
                  </span>
                  <div className="flex items-center gap-1 pt-2">
                    {[0, 1, 2].map((i) => (
                      <span key={i} className="h-1.5 w-1.5 animate-bounce rounded-full bg-subtle" style={{ animationDelay: `${i * 120}ms` }} />
                    ))}
                  </div>
                </div>
              </>
            )}
            <div ref={endRef} />
          </div>
        )}
      </div>
      <div className="border-t border-line p-3 sm:p-4">
        <form
          className="mx-auto flex max-w-3xl items-end gap-2 rounded-xl border border-line bg-surface px-3 py-2 focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/20"
          onSubmit={(e) => {
            e.preventDefault();
            send(text);
          }}
        >
          <textarea
            ref={taRef}
            rows={1}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              e.target.style.height = "auto";
              e.target.style.height = Math.min(e.target.scrollHeight, 160) + "px";
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(text);
              }
            }}
            placeholder="Ask anything about this meeting…"
            className="max-h-40 flex-1 resize-none bg-transparent py-1.5 text-sm outline-none placeholder:text-subtle"
          />
          <Button type="submit" size="icon" className="h-8 w-8 shrink-0" disabled={!text.trim()} loading={ask.isPending} aria-label="Send">
            {!ask.isPending && <ArrowUp className="h-4 w-4" />}
          </Button>
        </form>
        <p className="mt-2 text-center text-[11px] text-subtle">Enter to send · Shift + Enter for a new line</p>
      </div>
    </Card>
  );
}

function Bubble({ role, content }: { role: "user" | "assistant"; content: string }) {
  if (role === "user")
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-accent px-4 py-2.5 text-sm text-accent-fg">{content}</div>
      </div>
    );
  return (
    <div className="group flex gap-3">
      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-accent text-white">
        <Sparkles className="h-3.5 w-3.5" />
      </span>
      <div className="min-w-0 flex-1 pt-0.5">
        <Markdown text={content} />
        <div className="mt-1 opacity-0 transition group-hover:opacity-100">
          <CopyButton text={content} />
        </div>
      </div>
    </div>
  );
}

/* ============================================================ Processing */
function useElapsed(since: string | null) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  return since ? Math.max(0, (now - new Date(since).getTime()) / 1000) : 0;
}

function Processing({ m, onStop, stopping }: { m: Meeting; onStop: () => void; stopping: boolean }) {
  const elapsed = useElapsed(m.started_at ?? m.created_at);
  const canStop = ["queued", "joining", "recording"].includes(m.status);
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
      <Card className="p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-subtle">Current step</p>
            <p className="mt-1 text-lg font-semibold">{m.stage_message ?? "Starting…"}</p>
            <p className="mt-0.5 text-sm text-muted">
              Elapsed {timestamp(elapsed)}
              {m.status === "recording" && m.duration_requested ? ` · up to ${formatDuration(m.duration_requested)} of audio` : ""}
            </p>
          </div>
          {canStop && (
            <Button variant="outline" onClick={onStop} loading={stopping}>
              <Square className="h-3.5 w-3.5 fill-current" /> {m.status === "recording" ? "Stop & process" : "Cancel"}
            </Button>
          )}
        </div>
        <div className="mt-6 overflow-x-auto pb-1">
          <PipelineStepper meeting={m} />
        </div>
        <Progress value={m.progress} className="mt-5" />
        {m.status === "joining" && (
          <div className="mt-5 flex gap-3 rounded-lg border border-sky-500/20 bg-sky-500/5 p-3 text-[13px] text-sky-800 dark:text-sky-300">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            If the meeting has a waiting room, admit “IntelliMeet Bot” from Google Meet's participant panel.
          </div>
        )}
        {m.status === "recording" && (
          <div className="mt-5 flex items-center gap-3 rounded-lg border border-red-500/20 bg-red-500/5 p-3 text-[13px] text-red-700 dark:text-red-300">
            <span className="rec-dot h-2 w-2 rounded-full bg-red-500" /> Recording in progress. The bot leaves automatically when time is up.
          </div>
        )}
      </Card>
      <ActivityLog m={m} />
    </div>
  );
}

function ActivityLog({ m }: { m: Meeting }) {
  return (
    <Card>
      <CardHeader title="Activity" />
      <ol className="relative mx-5 mb-5 space-y-4 border-l border-line pl-5">
        {[...m.events].reverse().slice(0, 12).map((e, i) => (
          <li key={i} className="relative">
            <span className={cn("absolute -left-[25px] top-1 h-2.5 w-2.5 rounded-full ring-4 ring-surface", i === 0 ? (e.stage === "failed" ? "bg-red-500" : "bg-accent") : "bg-line")} />
            <p className="line-clamp-3 text-[13px] leading-snug break-words">{e.message}</p>
            <p className="text-[11px] text-subtle">{new Date(e.at).toLocaleTimeString()}</p>
          </li>
        ))}
      </ol>
    </Card>
  );
}

/* ================================================================ Helpers */
function CopyButton({ text, label }: { text: string; label?: string }) {
  const [ok, setOk] = useState(false);
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setOk(true);
          setTimeout(() => setOk(false), 1500);
        } catch {
          toast.error("Couldn't copy to clipboard");
        }
      }}
      className="h-7 px-2"
      aria-label="Copy"
    >
      {ok ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : <Copy className="h-3.5 w-3.5" />}
      {label && <span>{ok ? "Copied" : label}</span>}
    </Button>
  );
}

function ExportMenu({ id }: { id: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  return (
    <div ref={ref} className="relative">
      <Button variant="outline" size="sm" onClick={() => setOpen((o) => !o)}>
        <Download className="h-3.5 w-3.5" /> Export <ChevronDown className="h-3.5 w-3.5" />
      </Button>
      {open && (
        <div className="absolute right-0 z-20 mt-1 w-48 rounded-lg border border-line bg-surface p-1 shadow-lg animate-fade-in">
          {(
            [
              ["md", "Markdown notes", ".md"],
              ["json", "Raw data", ".json"],
            ] as const
          ).map(([f, label, ext]) => (
            <a key={f} href={api.exportUrl(id, f)} onClick={() => setOpen(false)} className="flex items-center justify-between rounded-md px-2.5 py-2 text-sm hover:bg-surface-2">
              {label} <span className="font-mono text-xs text-subtle">{ext}</span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

function EditableTitle({ m }: { m: Meeting }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(m.title);
  useEffect(() => {
    setValue(m.title);
  }, [m.title]);
  const save = useMutation({
    mutationFn: () => api.rename(m.id, value),
    onSuccess: () => {
      qc.invalidateQueries();
      setEditing(false);
    },
    onError: (e: Error) => toast.error(e.message),
  });
  if (editing)
    return (
      <form
        className="flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (value.trim() && value !== m.title) save.mutate();
          else setEditing(false);
        }}
      >
        <Input autoFocus value={value} onChange={(e) => setValue(e.target.value)} className="h-10 text-lg font-semibold" onKeyDown={(e) => e.key === "Escape" && setEditing(false)} />
        <Button size="icon" type="submit" loading={save.isPending} aria-label="Save">
          {!save.isPending && <Check className="h-4 w-4" />}
        </Button>
        <Button size="icon" variant="ghost" type="button" onClick={() => setEditing(false)} aria-label="Cancel">
          <X className="h-4 w-4" />
        </Button>
      </form>
    );
  return (
    <button onClick={() => setEditing(true)} className="group flex items-center gap-2 text-left">
      <h1 className="text-2xl font-semibold tracking-tight">{m.title}</h1>
      <Pencil className="h-4 w-4 text-subtle opacity-0 transition group-hover:opacity-100" />
    </button>
  );
}

/* =================================================================== Page */
type Tab = "overview" | "transcript" | "chat";

export function MeetingDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("overview");
  const [confirmDelete, setConfirmDelete] = useState(false);

  const { data: m, isLoading, error } = useQuery({
    queryKey: ["meeting", id],
    queryFn: () => api.meeting(id),
    refetchInterval: (q) => (q.state.data && ACTIVE_STATUSES.includes(q.state.data.status) ? 1500 : false),
  });

  const prevStatus = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (prevStatus.current && prevStatus.current !== "completed" && m?.status === "completed") {
      toast.success("Meeting processed", { description: "Summary and action items are ready." });
      qc.invalidateQueries({ queryKey: ["stats"] });
      qc.invalidateQueries({ queryKey: ["meetings"] });
      qc.invalidateQueries({ queryKey: ["action-items"] });
    }
    prevStatus.current = m?.status;
  }, [m?.status, qc]);

  const stop = useMutation({ mutationFn: () => api.stop(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["meeting", id] }), onError: (e: Error) => toast.error(e.message) });
  const retry = useMutation({
    mutationFn: (mode: "auto" | "rejoin" | "reprocess" | "reanalyze" = "auto") => api.retry(id, mode),
    onSuccess: (_d, mode) => {
      qc.invalidateQueries();
      toast.success(mode === "reanalyze" ? "Regenerating the summary…" : mode === "reprocess" ? "Re-processing the recording" : "Bot is on its way again");
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const remove = useMutation({
    mutationFn: () => api.remove(id),
    onSuccess: () => {
      qc.invalidateQueries();
      toast.success("Meeting deleted");
      navigate("/meetings");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (isLoading)
    return (
      <div className="space-y-4">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="mt-6 h-64 w-full rounded-xl" />
      </div>
    );
  if (error || !m)
    return (
      <EmptyState
        icon={<AlertTriangle className="h-5 w-5" />}
        title="Meeting not found"
        description="It may have been deleted."
        action={
          <Button variant="outline" onClick={() => navigate("/meetings")}>
            Back to meetings
          </Button>
        }
      />
    );

  const active = ACTIVE_STATUSES.includes(m.status);
  const failed = m.status === "failed" || m.status === "cancelled";

  return (
    <div className="animate-fade-in">
      <Link to="/meetings" className="inline-flex items-center gap-1.5 text-[13px] font-medium text-muted hover:text-fg">
        <ArrowLeft className="h-3.5 w-3.5" /> Meetings
      </Link>

      <div className="mt-3 flex flex-col-reverse items-start justify-between gap-3 sm:flex-row sm:gap-4">
        <div className="min-w-0 w-full flex-1">
          <EditableTitle m={m} />
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2 text-[13px] text-muted">
            <StatusBadge status={m.status} />
            <span className="flex items-center gap-1.5">
              <Calendar className="h-3.5 w-3.5" /> {formatDate(m.created_at, { weekday: "short", year: "numeric" })}
            </span>
            {m.duration_seconds ? (
              <span className="flex items-center gap-1.5">
                <Clock className="h-3.5 w-3.5" /> {formatDuration(m.duration_seconds)}
              </span>
            ) : null}
            {m.meet_link && (
              <a href={m.meet_link} target="_blank" rel="noreferrer" className="flex min-w-0 items-center gap-1.5 truncate hover:text-fg">
                <ExternalLink className="h-3.5 w-3.5" /> {m.meet_link.replace(/^https?:\/\//, "")}
              </a>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 self-end sm:self-auto">
          {m.status === "completed" && m.transcript && (
            <Button variant="outline" size="sm" onClick={() => retry.mutate("reanalyze")} loading={retry.isPending && retry.variables === "reanalyze"} title="Run the AI summary again on the saved transcript">
              <Sparkles className="h-3.5 w-3.5" /> Regenerate summary
            </Button>
          )}
          {m.status === "completed" && <ExportMenu id={m.id} />}
          {failed && (
            <Button variant="outline" size="sm" onClick={() => retry.mutate("auto")} loading={retry.isPending}>
              <RotateCcw className="h-3.5 w-3.5" /> Retry
            </Button>
          )}
          {(!active || m.status === "queued") && (
            <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(true)} className="text-muted hover:text-red-600">
              <Trash2 className="h-3.5 w-3.5" /> Delete
            </Button>
          )}
        </div>
      </div>

      <div className="mt-6">
        {active && <Processing m={m} onStop={() => stop.mutate()} stopping={stop.isPending} />}

        {failed && (
          <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
            <Card className="border-red-500/30 p-6">
              <div className="flex gap-3">
                <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-red-500/10 text-red-600">
                  <AlertTriangle className="h-4 w-4" />
                </div>
                <div>
                  <h2 className="font-semibold">{m.status === "failed" ? "Processing failed" : "Cancelled"}</h2>
                  <p className="mt-1 text-sm text-muted break-words">{m.error ?? "This meeting was cancelled before it finished."}</p>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {m.source === "bot" && (
                      <Button size="sm" onClick={() => retry.mutate("rejoin")} loading={retry.isPending && retry.variables === "rejoin"}>
                        <RotateCcw className="h-3.5 w-3.5" /> Send bot again
                      </Button>
                    )}
                    {m.can_reprocess && (
                      <Button size="sm" variant={m.source === "bot" ? "outline" : "primary"} onClick={() => retry.mutate("reprocess")} loading={retry.isPending && retry.variables === "reprocess"}>
                        <RotateCcw className="h-3.5 w-3.5" /> Re-process recording
                      </Button>
                    )}
                    <Button size="sm" variant="outline" onClick={() => navigate("/settings")}>
                      Check settings
                    </Button>
                  </div>
                </div>
              </div>
              {m.source === "bot" && (
                <div className="mt-5">
                  <BotAccount compact />
                </div>
              )}
            </Card>
            <ActivityLog m={m} />
          </div>
        )}

        {m.status === "completed" && (
          <>
            <Tabs<Tab>
              value={tab}
              onChange={setTab}
              className="mb-5"
              items={[
                { value: "overview", label: "Overview", icon: <Sparkles className="h-4 w-4" /> },
                { value: "transcript", label: "Transcript", icon: <FileText className="h-4 w-4" />, count: m.transcript?.segments.length || undefined },
                { value: "chat", label: "Ask AI", icon: <MessageSquare className="h-4 w-4" /> },
              ]}
            />
            {tab === "overview" && <Overview m={m} onRegenerate={() => retry.mutate("reanalyze")} regenerating={retry.isPending && retry.variables === "reanalyze"} />}
            {tab === "transcript" && <TranscriptView m={m} />}
            {tab === "chat" && <AskAI m={m} />}
          </>
        )}
      </div>

      <ConfirmDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onConfirm={() => remove.mutate()}
        loading={remove.isPending}
        title="Delete this meeting?"
        description="The recording, transcript, analysis and chat history will be permanently removed."
        confirmLabel="Delete meeting"
      />
    </div>
  );
}
