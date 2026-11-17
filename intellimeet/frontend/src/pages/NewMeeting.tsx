import { useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Bot, CheckCircle2, ClipboardPaste, FileAudio, FileText, Info, Sparkles, Upload, X } from "lucide-react";
import { toast } from "sonner";
import { api, type AppConfig } from "../lib/api";
import { cn, MEET_LINK_RE } from "../lib/format";
import { Button, Card, Input, Label, Progress, Switch } from "../components/ui";
import { BotAccount } from "../components/BotAccount";

type Mode = "bot" | "upload";
const PRESETS = [15, 30, 45, 60, 90];
const ACCEPT = ".wav,.mp3,.m4a,.mp4,.webm,.ogg,.flac,.mpeg,.mpga,.txt,.vtt,.srt";

function ModeCard({ active, onClick, icon, title, desc }: { active: boolean; onClick: () => void; icon: React.ReactNode; title: string; desc: string }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex flex-1 items-start gap-3 rounded-xl border p-4 text-left transition",
        active ? "border-accent bg-accent-soft/60 ring-1 ring-accent" : "border-line bg-surface hover:border-subtle/60",
      )}
    >
      <span className={cn("grid h-9 w-9 shrink-0 place-items-center rounded-lg", active ? "bg-accent text-white" : "bg-surface-2 text-muted")}>{icon}</span>
      <span>
        <span className="block text-sm font-semibold">{title}</span>
        <span className="mt-0.5 block text-[13px] text-muted">{desc}</span>
      </span>
    </button>
  );
}

function Check({ ok, warn, children }: { ok: boolean; warn?: boolean; children: React.ReactNode }) {
  return (
    <li className="flex gap-2.5 text-[13px]">
      {ok ? (
        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
      ) : (
        <AlertCircle className={cn("mt-0.5 h-4 w-4 shrink-0", warn ? "text-amber-500" : "text-red-500")} />
      )}
      <span className="text-muted">{children}</span>
    </li>
  );
}

function Readiness({ cfg, mode }: { cfg?: AppConfig; mode: Mode }) {
  if (!cfg) return null;
  return (
    <Card className="p-5">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        <Info className="h-4 w-4 text-muted" /> Setup check
      </h3>
      <ul className="mt-4 space-y-3">
        {mode === "bot" && (
          <>
            <Check ok={cfg.bot.chrome_profile} warn>
              {cfg.bot.account ? `Bot signed in as ${cfg.bot.account}` : "Bot not signed in to Google: it will join as a guest"}
            </Check>
            <Check ok={cfg.audio.source === "loopback" || !!cfg.audio.device} warn>
              {cfg.audio.source === "loopback"
                ? `Recording system audio${cfg.audio.device ? ` from “${cfg.audio.device}”` : ""}. Test it in Settings → Audio.`
                : cfg.audio.device
                  ? `Recording from input “${cfg.audio.device}”`
                  : "Recording from the default microphone, which won't capture other participants. Switch to System audio in Settings."}
            </Check>
          </>
        )}
        <Check ok={cfg.transcriber.configured}>
          {cfg.transcriber.configured
            ? `Transcription: ${cfg.transcriber.provider === "local" ? "faster-whisper (local)" : "OpenAI Whisper"}`
            : mode === "upload"
              ? "No transcription provider — audio needs OPENAI_API_KEY or TRANSCRIBER=local. Transcript files (.txt/.vtt/.srt) still work."
              : "No transcription provider configured (OPENAI_API_KEY or TRANSCRIBER=local)"}
        </Check>
        <Check ok={cfg.analyzer.configured} warn>
          {cfg.analyzer.configured ? `AI analysis: ${cfg.analyzer.provider} · ${cfg.analyzer.model}` : "No LLM key — using the offline basic analyzer"}
        </Check>
      </ul>
      <Link to="/settings" className="mt-4 inline-block text-[13px] font-medium text-accent-text hover:underline">
        View configuration →
      </Link>
    </Card>
  );
}

function BotForm() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [link, setLink] = useState("");
  const [title, setTitle] = useState("");
  const [minutes, setMinutes] = useState(30);
  const [custom, setCustom] = useState(false);
  const [analyze, setAnalyze] = useState(true);
  const [touched, setTouched] = useState(false);
  const valid = MEET_LINK_RE.test(link.trim());

  const send = useMutation({
    mutationFn: () => api.sendBot({ meet_link: link.trim(), title: title.trim() || undefined, duration_minutes: minutes, analyze }),
    onSuccess: (m) => {
      qc.invalidateQueries();
      toast.success("Bot is on its way", { description: "It will ask to join — admit “IntelliMeet Bot” in Meet." });
      navigate(`/meetings/${m.id}`);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const paste = async () => {
    try {
      setLink((await navigator.clipboard.readText()).trim());
      setTouched(true);
    } catch {
      toast.error("Clipboard access was blocked — paste with Ctrl+V instead.");
    }
  };

  return (
    <form
      className="space-y-6"
      onSubmit={(e) => {
        e.preventDefault();
        setTouched(true);
        if (valid) send.mutate();
      }}
    >
      <div>
        <Label htmlFor="link">Google Meet link</Label>
        <div className="relative">
          <Input
            id="link"
            autoFocus
            value={link}
            onChange={(e) => setLink(e.target.value)}
            onBlur={() => setTouched(true)}
            placeholder="https://meet.google.com/abc-defg-hij"
            invalid={touched && !!link && !valid}
            className="pr-24 font-mono text-[13px]"
          />
          <div className="absolute right-1.5 top-1/2 flex -translate-y-1/2 items-center gap-1">
            {valid && <CheckCircle2 className="h-4 w-4 text-emerald-500" />}
            <Button type="button" variant="ghost" size="sm" onClick={paste} className="h-7 px-2">
              <ClipboardPaste className="h-3.5 w-3.5" /> Paste
            </Button>
          </div>
        </div>
        {touched && link && !valid && <p className="mt-1.5 text-xs text-red-600">Enter a link like meet.google.com/abc-defg-hij</p>}
      </div>

      <div>
        <Label htmlFor="title" hint="Optional — AI will name it">
          Meeting title
        </Label>
        <Input id="title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Weekly project sync" />
      </div>

      <div>
        <Label hint="The bot leaves after this, or when you stop it">Recording length</Label>
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((p) => (
            <button
              type="button"
              key={p}
              onClick={() => {
                setMinutes(p);
                setCustom(false);
              }}
              className={cn(
                "h-9 rounded-lg border px-3.5 text-sm font-medium transition",
                !custom && minutes === p ? "border-accent bg-accent-soft text-accent-text" : "border-line hover:bg-surface-2",
              )}
            >
              {p < 60 ? `${p} min` : `${p / 60 === 1 ? "1 hr" : `${p / 60} hr`}`}
            </button>
          ))}
          <div className={cn("flex h-9 items-center gap-1.5 rounded-lg border px-2.5 text-sm", custom ? "border-accent" : "border-line")}>
            <input
              type="number"
              min={1}
              max={240}
              value={custom ? minutes : ""}
              placeholder="Custom"
              onFocus={() => setCustom(true)}
              onChange={(e) => {
                setCustom(true);
                setMinutes(Math.max(1, Math.min(240, Number(e.target.value) || 1)));
              }}
              className="w-16 bg-transparent outline-none placeholder:text-subtle"
            />
            <span className="text-muted">min</span>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between rounded-xl border border-line bg-surface-2/40 p-4">
        <div className="flex gap-3">
          <Sparkles className="mt-0.5 h-4 w-4 text-accent" />
          <div>
            <p className="text-sm font-medium">AI analysis</p>
            <p className="text-[13px] text-muted">Summary, key points, decisions, action items and sentiment.</p>
          </div>
        </div>
        <Switch checked={analyze} onChange={setAnalyze} />
      </div>

      <div className="flex items-center justify-end gap-2 border-t border-line pt-5">
        <Button type="button" variant="ghost" onClick={() => navigate(-1)}>
          Cancel
        </Button>
        <Button type="submit" size="lg" loading={send.isPending} disabled={!valid && touched}>
          <Bot className="h-4 w-4" /> Send bot to meeting
        </Button>
      </div>
    </form>
  );
}

function fmtSize(b: number) {
  return b > 1024 * 1024 ? `${(b / 1024 / 1024).toFixed(1)} MB` : `${Math.ceil(b / 1024)} KB`;
}

function UploadForm() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [analyze, setAnalyze] = useState(true);
  const [drag, setDrag] = useState(false);
  const [pct, setPct] = useState(0);

  const upload = useMutation({
    mutationFn: () => api.upload(file!, title.trim(), analyze, setPct),
    onSuccess: (m) => {
      qc.invalidateQueries();
      toast.success("Upload complete — processing started");
      navigate(`/meetings/${m.id}`);
    },
    onError: (e: Error) => {
      setPct(0);
      toast.error(e.message);
    },
  });

  const pick = (f: File | undefined) => {
    if (!f) return;
    const ext = "." + f.name.split(".").pop()?.toLowerCase();
    if (!ACCEPT.split(",").includes(ext)) {
      toast.error(`Unsupported file type ${ext}`);
      return;
    }
    setFile(f);
  };

  const isText = file && /\.(txt|vtt|srt)$/i.test(file.name);

  return (
    <form
      className="space-y-6"
      onSubmit={(e) => {
        e.preventDefault();
        if (file) upload.mutate();
      }}
    >
      {!file ? (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            pick(e.dataTransfer.files[0]);
          }}
          onClick={() => inputRef.current?.click()}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-12 text-center transition",
            drag ? "border-accent bg-accent-soft/50" : "border-line hover:border-subtle hover:bg-surface-2/40",
          )}
        >
          <div className="grid h-12 w-12 place-items-center rounded-xl bg-surface-2 text-muted">
            <Upload className="h-5 w-5" />
          </div>
          <p className="mt-4 text-sm font-medium">
            Drop a recording here, or <span className="text-accent-text">browse</span>
          </p>
          <p className="mt-1 text-xs text-muted">MP3, WAV, M4A, MP4, WEBM, OGG, FLAC — or a transcript (.txt, .vtt, .srt)</p>
          <input ref={inputRef} type="file" accept={ACCEPT} hidden onChange={(e) => pick(e.target.files?.[0])} />
        </div>
      ) : (
        <div className="flex items-center gap-3 rounded-xl border border-line bg-surface-2/40 p-4">
          <div className="grid h-10 w-10 place-items-center rounded-lg bg-accent-soft text-accent-text">
            {isText ? <FileText className="h-5 w-5" /> : <FileAudio className="h-5 w-5" />}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{file.name}</p>
            <p className="text-xs text-muted">
              {fmtSize(file.size)} · {isText ? "transcript" : "audio"}
            </p>
            {upload.isPending && <Progress value={pct / 100} className="mt-2" />}
          </div>
          {!upload.isPending && (
            <Button type="button" variant="ghost" size="icon" onClick={() => setFile(null)} aria-label="Remove file">
              <X className="h-4 w-4" />
            </Button>
          )}
        </div>
      )}

      <div>
        <Label htmlFor="utitle" hint="Optional — AI will name it">
          Meeting title
        </Label>
        <Input id="utitle" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Client kickoff call" />
      </div>

      <div className="flex items-center justify-between rounded-xl border border-line bg-surface-2/40 p-4">
        <div className="flex gap-3">
          <Sparkles className="mt-0.5 h-4 w-4 text-accent" />
          <div>
            <p className="text-sm font-medium">AI analysis</p>
            <p className="text-[13px] text-muted">Summary, key points, decisions, action items and sentiment.</p>
          </div>
        </div>
        <Switch checked={analyze} onChange={setAnalyze} />
      </div>

      <div className="flex items-center justify-end gap-2 border-t border-line pt-5">
        <Button type="button" variant="ghost" onClick={() => navigate(-1)}>
          Cancel
        </Button>
        <Button type="submit" size="lg" disabled={!file} loading={upload.isPending}>
          <Upload className="h-4 w-4" /> {upload.isPending ? `Uploading ${pct}%` : "Upload and process"}
        </Button>
      </div>
    </form>
  );
}

export function NewMeeting() {
  const [params, setParams] = useSearchParams();
  const mode: Mode = params.get("mode") === "upload" ? "upload" : "bot";
  const { data: cfg } = useQuery({ queryKey: ["config"], queryFn: api.config });
  const setMode = (m: Mode) => setParams(m === "upload" ? { mode: "upload" } : {}, { replace: true });

  return (
    <div className="mx-auto max-w-5xl animate-fade-in">
      <h1 className="text-2xl font-semibold tracking-tight">New meeting</h1>
      <p className="mt-1 text-sm text-muted">Capture a live Google Meet, or analyse a recording you already have.</p>

      <div className="mt-6 flex flex-col gap-3 sm:flex-row">
        <ModeCard active={mode === "bot"} onClick={() => setMode("bot")} icon={<Bot className="h-4 w-4" />} title="Join a Google Meet" desc="The bot joins, records and leaves automatically." />
        <ModeCard active={mode === "upload"} onClick={() => setMode("upload")} icon={<Upload className="h-4 w-4" />} title="Upload a recording" desc="Audio, video or an existing transcript." />
      </div>

      {mode === "bot" && (
        <div className="mt-6">
          <BotAccount compact />
        </div>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_300px]">
        <Card className="p-6">{mode === "bot" ? <BotForm /> : <UploadForm />}</Card>
        <div className="space-y-4">
          <Readiness cfg={cfg} mode={mode} />
          {mode === "bot" && (
            <Card className="p-5">
              <h3 className="text-sm font-semibold">How it works</h3>
              <ol className="mt-3 space-y-2.5 text-[13px] text-muted">
                <li>1. A Chrome window opens and joins with mic & camera off.</li>
                <li>2. Admit <span className="font-medium text-fg">IntelliMeet Bot</span> from the meeting.</li>
                <li>3. It records for the chosen time — or stop it any time.</li>
                <li>4. The transcript and analysis appear on the meeting page.</li>
              </ol>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
