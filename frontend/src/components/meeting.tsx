import { Bot, Check, CircleSlash, FileAudio, FlaskConical, Loader2, Sparkles, Mic, LogIn, FileText, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import { Badge, type Tone } from "./ui";
import type { MeetingBase, MeetingStatus, Sentiment } from "../lib/api";
import { avatarColor, cn, initials } from "../lib/format";

const STATUS: Record<MeetingStatus, { label: string; tone: Tone }> = {
  queued: { label: "Queued", tone: "neutral" },
  joining: { label: "Joining", tone: "blue" },
  recording: { label: "Recording", tone: "red" },
  transcribing: { label: "Transcribing", tone: "accent" },
  analyzing: { label: "Analyzing", tone: "accent" },
  completed: { label: "Completed", tone: "green" },
  failed: { label: "Failed", tone: "red" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

export function StatusBadge({ status }: { status: MeetingStatus }) {
  const s = STATUS[status] ?? STATUS.queued;
  const live = ["joining", "transcribing", "analyzing"].includes(status);
  return (
    <Badge tone={s.tone}>
      {status === "recording" && <span className="rec-dot h-1.5 w-1.5 rounded-full bg-red-500" />}
      {live && <Loader2 className="h-3 w-3 animate-spin" />}
      {status === "completed" && <Check className="h-3 w-3" />}
      {s.label}
    </Badge>
  );
}

const SENTIMENT: Record<string, { tone: Tone; emoji: string }> = {
  positive: { tone: "green", emoji: "●" },
  neutral: { tone: "neutral", emoji: "●" },
  negative: { tone: "red", emoji: "●" },
  mixed: { tone: "amber", emoji: "●" },
};

export function SentimentBadge({ sentiment }: { sentiment: Sentiment | null | undefined }) {
  if (!sentiment) return null;
  const s = SENTIMENT[sentiment.label] ?? SENTIMENT.neutral;
  return (
    <Badge tone={s.tone} className="capitalize">
      <span className="text-[8px]">{s.emoji}</span>
      {sentiment.label}
    </Badge>
  );
}

export function SourceIcon({ source, className }: { source: MeetingBase["source"]; className?: string }) {
  const Icon = source === "bot" ? Bot : source === "sample" ? FlaskConical : FileAudio;
  return (
    <div className={cn("grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-line bg-surface-2 text-muted", className)}>
      <Icon className="h-4 w-4" />
    </div>
  );
}

export const sourceLabel = (s: MeetingBase["source"]) => (s === "bot" ? "Google Meet bot" : s === "sample" ? "Sample" : "Upload");

export function Avatar({ name, size = "md" }: { name: string; size?: "sm" | "md" }) {
  return (
    <span
      title={name}
      className={cn(
        "inline-grid shrink-0 place-items-center rounded-full font-semibold",
        size === "sm" ? "h-6 w-6 text-[10px]" : "h-8 w-8 text-xs",
        avatarColor(name),
      )}
    >
      {initials(name)}
    </span>
  );
}

/* ---------------------------------------------------------- Pipeline stepper */
interface Step {
  key: MeetingStatus;
  label: string;
  icon: ReactNode;
}

export function PipelineStepper({ meeting }: { meeting: MeetingBase }) {
  const steps: Step[] = [
    ...(meeting.source === "bot"
      ? [
          { key: "joining" as const, label: "Join meeting", icon: <LogIn className="h-3.5 w-3.5" /> },
          { key: "recording" as const, label: "Record audio", icon: <Mic className="h-3.5 w-3.5" /> },
        ]
      : []),
    { key: "transcribing", label: "Transcribe", icon: <FileText className="h-3.5 w-3.5" /> },
    ...(meeting.analyze ? [{ key: "analyzing" as const, label: "AI analysis", icon: <Sparkles className="h-3.5 w-3.5" /> }] : []),
  ];
  const order: MeetingStatus[] = ["queued", ...steps.map((s) => s.key), "completed"];
  const failed = meeting.status === "failed" || meeting.status === "cancelled";
  const current = failed ? -1 : order.indexOf(meeting.status);

  return (
    <ol className="flex items-center gap-2">
      {steps.map((s, i) => {
        const idx = i + 1;
        const done = !failed && current > idx;
        const active = !failed && current === idx;
        return (
          <li key={s.key} className="flex flex-1 items-center gap-2 min-w-0">
            <div
              className={cn(
                "flex items-center gap-2 rounded-full border py-1 pl-1 pr-3 text-xs font-medium transition-colors min-w-0",
                done && "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
                active && "border-accent/40 bg-accent-soft text-accent-text",
                !done && !active && "border-line text-subtle",
              )}
            >
              <span
                className={cn(
                  "grid h-5 w-5 shrink-0 place-items-center rounded-full",
                  done ? "bg-emerald-500 text-white" : active ? "bg-accent text-white" : "bg-surface-2",
                )}
              >
                {done ? <Check className="h-3 w-3" /> : active ? <Loader2 className="h-3 w-3 animate-spin" /> : s.icon}
              </span>
              <span className="truncate">{s.label}</span>
            </div>
            {i < steps.length - 1 && <div className={cn("h-px flex-1 min-w-3", done ? "bg-emerald-500/40" : "bg-line")} />}
          </li>
        );
      })}
      {failed && (
        <li className="flex items-center gap-1.5 text-xs font-medium text-red-600">
          {meeting.status === "failed" ? <XCircle className="h-4 w-4" /> : <CircleSlash className="h-4 w-4" />}
          {meeting.status === "failed" ? "Failed" : "Cancelled"}
        </li>
      )}
    </ol>
  );
}

/* --------------------------------------------------- Minimal markdown render */
function inline(text: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|_[^_]+_)/g);
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**")) return <strong key={i}>{p.slice(2, -2)}</strong>;
    if (p.startsWith("`") && p.endsWith("`")) return <code key={i}>{p.slice(1, -1)}</code>;
    if (p.startsWith("_") && p.endsWith("_") && p.length > 2) return <em key={i} className="text-muted">{p.slice(1, -1)}</em>;
    return p;
  });
}

export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) {
      blocks.push(
        <ul key={blocks.length}>
          {list.map((l, i) => (
            <li key={i}>{inline(l)}</li>
          ))}
        </ul>,
      );
      list = [];
    }
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const m = line.match(/^([-*•]|\d+\.)\s+(.*)$/);
    if (m) {
      list.push(m[2]);
      continue;
    }
    flush();
    if (line) blocks.push(<p key={blocks.length}>{inline(line.replace(/^#+\s*/, ""))}</p>);
  }
  flush();
  return <div className="prose-chat text-sm leading-relaxed">{blocks}</div>;
}
