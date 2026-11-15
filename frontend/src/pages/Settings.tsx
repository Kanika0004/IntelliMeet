import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AudioLines,
  Bot,
  BrainCircuit,
  CheckCircle2,
  CircleAlert,
  Eye,
  EyeOff,
  Headphones,
  Mic,
  Monitor,
  Moon,
  Palette,
  Play,
  RefreshCw,
  Speaker,
  Sun,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";
import { api, type AudioTestResult, type Secret, type SettingsValues } from "../lib/api";
import { cn } from "../lib/format";
import { Button, Card, Input, Skeleton, Switch } from "../components/ui";
import { BotAccount } from "../components/BotAccount";
import { setTheme, storedTheme } from "../lib/theme";

type Values = SettingsValues;
type Draft = Partial<Record<keyof Values, unknown>>;

/* ----------------------------------------------------------- primitives */
function Field({ label, hint, children, className }: { label: string; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={cn("grid gap-1.5 sm:grid-cols-[200px_1fr] sm:gap-6", className)}>
      <div className="pt-2">
        <p className="text-[13px] font-medium">{label}</p>
      </div>
      <div className="min-w-0">
        {children}
        {hint && <p className="mt-1.5 text-xs text-muted">{hint}</p>}
      </div>
    </div>
  );
}

function Select({ value, onChange, options, className }: { value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; className?: string }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={cn(
        "h-10 w-full rounded-lg border border-line bg-surface px-3 text-sm focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20",
        className,
      )}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

function SecretField({ current, value, onChange, placeholder }: { current: Secret; value: unknown; onChange: (v: string | undefined) => void; placeholder: string }) {
  const [show, setShow] = useState(false);
  const editing = value !== undefined;
  if (current.set && !editing)
    return (
      <div className="flex h-10 items-center gap-2 rounded-lg border border-line bg-surface-2/50 px-3">
        <CheckCircle2 className="h-4 w-4 text-emerald-500" />
        <span className="flex-1 font-mono text-[13px] text-muted">{current.masked}</span>
        <Button variant="ghost" size="sm" className="h-7" onClick={() => onChange("")}>
          Replace
        </Button>
      </div>
    );
  return (
    <div className="relative">
      <Input
        type={show ? "text" : "password"}
        autoComplete="off"
        spellCheck={false}
        value={(value as string) ?? ""}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="pr-20 font-mono text-[13px]"
      />
      <div className="absolute right-1.5 top-1/2 flex -translate-y-1/2 gap-0.5">
        <button type="button" onClick={() => setShow((s) => !s)} className="grid h-7 w-7 place-items-center rounded text-subtle hover:text-fg" aria-label="Show key">
          {show ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
        </button>
        {current.set && (
          <button type="button" onClick={() => onChange(undefined)} className="rounded px-1.5 text-xs text-subtle hover:text-fg">
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}

function Section({
  id,
  icon,
  title,
  description,
  children,
  dirty,
  saving,
  onSave,
  onReset,
}: {
  id: string;
  icon: ReactNode;
  title: string;
  description: string;
  children: ReactNode;
  dirty?: boolean;
  saving?: boolean;
  onSave?: () => void;
  onReset?: () => void;
}) {
  return (
    <Card id={id} className="scroll-mt-20 overflow-hidden">
      <div className="flex items-start gap-3 border-b border-line px-5 py-4">
        <span className="mt-0.5 text-muted">{icon}</span>
        <div>
          <h2 className="text-sm font-semibold">{title}</h2>
          <p className="mt-0.5 text-[13px] text-muted">{description}</p>
        </div>
      </div>
      <div className="space-y-5 px-5 py-5">{children}</div>
      {onSave && (
        <div className={cn("flex items-center justify-end gap-2 border-t border-line px-5 py-3 transition-colors", dirty ? "bg-accent-soft/40" : "bg-surface-2/30")}>
          {dirty && <span className="mr-auto text-xs text-muted">Unsaved changes</span>}
          {dirty && (
            <Button variant="ghost" size="sm" onClick={onReset}>
              Discard
            </Button>
          )}
          <Button size="sm" disabled={!dirty} loading={saving} onClick={onSave}>
            Save changes
          </Button>
        </div>
      )}
    </Card>
  );
}

/* ---------------------------------------------------------- section state */
function useSection(values: Values | undefined, keys: (keyof Values)[]) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<Draft>({});
  useEffect(() => setDraft({}), [values]);
  const get = <K extends keyof Values>(k: K): any => (k in draft ? draft[k] : values?.[k]);
  const set = (k: keyof Values, v: unknown) =>
    setDraft((d) => {
      const next = { ...d };
      const original = values?.[k];
      if (v === undefined || (typeof original !== "object" && v === original)) delete next[k];
      else next[k] = v;
      return next;
    });
  const dirty = keys.some((k) => k in draft);
  const save = useMutation({
    mutationFn: () => api.saveSettings(draft),
    onSuccess: (r) => {
      qc.setQueryData(["settings"], (old: any) => ({ ...old, values: r.values }));
      qc.invalidateQueries({ queryKey: ["config"] });
      toast.success("Settings saved");
    },
    onError: (e: Error) => toast.error(e.message),
  });
  return { get, set, dirty, save: () => save.mutate(), saving: save.isPending, reset: () => setDraft({}), draft };
}

/* ------------------------------------------------------------- AI section */
function AISection({ values }: { values: Values }) {
  const sec = useSection(values, ["transcriber", "openai_api_key", "whisper_model", "local_whisper_model", "analyzer", "gpt_model", "gemini_api_key", "gemini_model"]);
  const test = useMutation({ mutationFn: api.testAI });
  const transcriber = sec.get("transcriber");
  const analyzer = sec.get("analyzer");
  const needsOpenAI = transcriber === "openai" || analyzer === "openai" || analyzer === "auto";
  const needsGemini = analyzer === "gemini" || analyzer === "auto";

  return (
    <Section
      id="ai"
      icon={<BrainCircuit className="h-4 w-4" />}
      title="AI providers"
      description="Speech-to-text and the model that writes summaries and answers questions."
      dirty={sec.dirty}
      saving={sec.saving}
      onSave={sec.save}
      onReset={sec.reset}
    >
      <Field label="Transcription" hint={transcriber === "local" ? "Runs on this computer, so it's free and private but slower. Needs: pip install faster-whisper" : "Fast and accurate. Uses your OpenAI key."}>
        <Select
          value={transcriber}
          onChange={(v) => sec.set("transcriber", v)}
          options={[
            { value: "openai", label: "OpenAI Whisper (cloud)" },
            { value: "local", label: "faster-whisper (on this computer)" },
          ]}
        />
      </Field>
      {transcriber === "local" ? (
        <Field label="Local model" hint="Larger = more accurate but slower. 'small' is a good balance on a laptop.">
          <Select
            value={sec.get("local_whisper_model")}
            onChange={(v) => sec.set("local_whisper_model", v)}
            options={["tiny", "base", "small", "medium", "large-v3"].map((m) => ({ value: m, label: m }))}
          />
        </Field>
      ) : null}
      <Field label="Analysis model" hint="Auto uses OpenAI if a key is set, otherwise Gemini, otherwise the offline analyzer.">
        <Select
          value={analyzer}
          onChange={(v) => sec.set("analyzer", v)}
          options={[
            { value: "auto", label: "Auto" },
            { value: "openai", label: "OpenAI GPT" },
            { value: "gemini", label: "Google Gemini" },
            { value: "basic", label: "Offline (no API key, basic quality)" },
          ]}
        />
      </Field>
      {needsOpenAI && (
        <Field label="OpenAI API key" hint={<>Get one at platform.openai.com → API keys.</>}>
          <SecretField current={values.openai_api_key} value={sec.draft.openai_api_key} onChange={(v) => sec.set("openai_api_key", v)} placeholder="sk-proj-…" />
        </Field>
      )}
      {needsOpenAI && (
        <Field label="GPT model">
          <Input value={sec.get("gpt_model")} onChange={(e) => sec.set("gpt_model", e.target.value)} className="font-mono text-[13px]" />
        </Field>
      )}
      {needsGemini && (
        <Field label="Gemini API key" hint="Free tier available at aistudio.google.com → Get API key.">
          <SecretField current={values.gemini_api_key} value={sec.draft.gemini_api_key} onChange={(v) => sec.set("gemini_api_key", v)} placeholder="AIza…" />
        </Field>
      )}
      {needsGemini && (
        <Field label="Gemini model" hint="Free tier: Flash-Lite allows ~500 requests a day; 3.8 Flash only ~20 a day. If the chosen model is busy or out of quota, IntelliMeet tries the others automatically.">
          <Select
            value={String(sec.get("gemini_model"))}
            onChange={(v) => sec.set("gemini_model", v)}
            options={[
              { value: "gemini-3.5-flash-lite", label: "gemini-3.5-flash-lite (recommended for free tier)" },
              { value: "gemini-3.1-flash-lite", label: "gemini-3.1-flash-lite" },
              { value: "gemini-3.8-flash", label: "gemini-3.8-flash (best quality, ~20 free requests/day)" },
              { value: "gemini-3.6-flash", label: "gemini-3.6-flash" },
              ...(["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.8-flash", "gemini-3.6-flash"].includes(String(sec.get("gemini_model")))
                ? []
                : [{ value: String(sec.get("gemini_model")), label: String(sec.get("gemini_model")) }]),
            ]}
          />
        </Field>
      )}
      <Field label="Connection" hint={sec.dirty ? "Save your changes first, then test." : undefined}>
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="outline" size="sm" onClick={() => test.mutate()} loading={test.isPending} disabled={sec.dirty}>
            Test AI connection
          </Button>
          {test.data && (
            <span className={cn("flex items-center gap-1.5 text-[13px]", test.data.ok ? "text-emerald-600 dark:text-emerald-400" : "text-red-600")}>
              {test.data.ok ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />}
              <span className="break-all">{test.data.message}</span>
            </span>
          )}
        </div>
      </Field>
    </Section>
  );
}

/* ------------------------------------------------------------ Bot section */
function BotSection({ values }: { values: Values }) {
  const sec = useSection(values, ["bot_display_name", "duration", "admit_timeout", "headless"]);
  return (
    <Section
      id="bot"
      icon={<Bot className="h-4 w-4" />}
      title="Meeting bot"
      description="How the bot appears in meetings and how long it stays."
      dirty={sec.dirty}
      saving={sec.saving}
      onSave={sec.save}
      onReset={sec.reset}
    >
      <BotAccount compact />
      <Field label="Name in meeting" hint="Shown to participants when the bot joins as a guest.">
        <Input value={sec.get("bot_display_name")} onChange={(e) => sec.set("bot_display_name", e.target.value)} maxLength={60} />
      </Field>
      <Field label="Default length" hint="Pre-selected on the New meeting page.">
        <div className="flex items-center gap-2">
          <Input
            type="number"
            min={1}
            max={240}
            value={Math.round(Number(sec.get("duration")) / 60)}
            onChange={(e) => sec.set("duration", Math.max(1, Number(e.target.value) || 1) * 60)}
            className="w-28"
          />
          <span className="text-sm text-muted">minutes</span>
        </div>
      </Field>
      <Field label="Wait to be admitted" hint="How long the bot waits in the lobby before giving up.">
        <div className="flex items-center gap-2">
          <Input
            type="number"
            min={1}
            max={60}
            value={Math.round(Number(sec.get("admit_timeout")) / 60)}
            onChange={(e) => sec.set("admit_timeout", Math.max(1, Number(e.target.value) || 1) * 60)}
            className="w-28"
          />
          <span className="text-sm text-muted">minutes</span>
        </div>
      </Field>
      <Field
        label="Hide Chrome window"
        hint={
          sec.get("headless") ? (
            <span className="text-amber-600 dark:text-amber-400">A hidden (headless) Chrome plays no sound, so system-audio recording will be silent. Keep this off.</span>
          ) : (
            "Keep off. The window must play the meeting sound so it can be recorded. You can minimise it."
          )
        }
      >
        <div className="pt-2">
          <Switch checked={!!sec.get("headless")} onChange={(v) => sec.set("headless", v)} />
        </div>
      </Field>
    </Section>
  );
}

/* ---------------------------------------------------------- Audio section */
function LevelMeter({ r }: { r: AudioTestResult }) {
  const pct = Math.min(100, Math.round(Math.sqrt(r.peak) * 100));
  const quiet = !r.silent && r.peak < 0.05;
  return (
    <div className="rounded-xl border border-line p-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        {r.silent ? <XCircle className="h-4 w-4 text-red-500" /> : quiet ? <CircleAlert className="h-4 w-4 text-amber-500" /> : <CheckCircle2 className="h-4 w-4 text-emerald-500" />}
        {r.silent ? "Silent: nothing was captured" : quiet ? "Very quiet: turn the volume up" : "Audio captured"}
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-surface-2">
        <div className={cn("h-full rounded-full transition-all", r.silent ? "bg-red-500" : quiet ? "bg-amber-500" : "bg-emerald-500")} style={{ width: `${Math.max(2, pct)}%` }} />
      </div>
      <p className="mt-2 text-xs text-muted">
        {r.seconds.toFixed(1)} s from {r.source} · peak {(r.peak * 100).toFixed(1)}%
      </p>
      {r.silent && (
        <p className="mt-2 text-xs text-muted">
          Make sure something was playing during the test. With “System audio”, choose the speaker you actually hear sound from (e.g. headphones). With an input device, make sure it's enabled in Windows Sound settings.
        </p>
      )}
      <audio controls src={`${r.url}?t=${Date.now()}`} className="mt-3 h-9 w-full" />
    </div>
  );
}

function AudioSection({ values }: { values: Values; defaultSource: string }) {
  const sec = useSection(values, ["audio_source", "audio_device"]);
  const { data: devices, refetch, isFetching } = useQuery({ queryKey: ["audio-devices"], queryFn: api.audioDevices });
  const source: string = sec.get("audio_source") || (devices?.loopback_supported ? "loopback" : "device");
  const device = String(sec.get("audio_device") ?? "");
  const test = useMutation({
    mutationFn: () => api.audioTest({ seconds: 5, audio_source: source, audio_device: device }),
    onError: (e: Error) => toast.error(e.message),
  });

  const list = source === "loopback" ? devices?.speakers ?? [] : devices?.inputs ?? [];
  const def = source === "loopback" ? devices?.default_speaker : devices?.default_input;
  const options = useMemo(
    () => [
      { value: "", label: `System default${def ? ` (${def})` : ""}` },
      ...list.map((n) => ({ value: n, label: n })),
      ...(device && !list.includes(device) ? [{ value: device, label: `${device} (not found)` }] : []),
    ],
    [list, def, device],
  );

  const SourceCard = ({ value, icon, title, desc, disabled }: { value: string; icon: ReactNode; title: string; desc: string; disabled?: boolean }) => (
    <button
      type="button"
      disabled={disabled}
      onClick={() => {
        sec.set("audio_source", value);
        sec.set("audio_device", "");
        test.reset();
      }}
      className={cn(
        "flex flex-1 items-start gap-3 rounded-xl border p-4 text-left transition disabled:cursor-not-allowed disabled:opacity-50",
        source === value ? "border-accent bg-accent-soft/50 ring-1 ring-accent" : "border-line hover:bg-surface-2",
      )}
    >
      <span className={cn("grid h-8 w-8 shrink-0 place-items-center rounded-lg", source === value ? "bg-accent text-white" : "bg-surface-2 text-muted")}>{icon}</span>
      <span>
        <span className="block text-sm font-semibold">{title}</span>
        <span className="mt-0.5 block text-xs text-muted">{desc}</span>
      </span>
    </button>
  );

  return (
    <Section
      id="audio"
      icon={<AudioLines className="h-4 w-4" />}
      title="Audio capture"
      description="Where the bot records the meeting sound from."
      dirty={sec.dirty}
      saving={sec.saving}
      onSave={sec.save}
      onReset={sec.reset}
    >
      <div className="flex flex-col gap-3 sm:flex-row">
        <SourceCard
          value="loopback"
          icon={<Speaker className="h-4 w-4" />}
          title="System audio (recommended)"
          desc="Records what your computer plays, including the meeting from the bot's Chrome window. No extra software."
          disabled={devices ? !devices.loopback_supported : false}
        />
        <SourceCard value="device" icon={<Mic className="h-4 w-4" />} title="Input device" desc="Stereo Mix, VB-Audio Cable, BlackHole, or a microphone." />
      </div>

      <Field label={source === "loopback" ? "Speaker to record" : "Input device"} hint={source === "loopback" ? "Pick the output you actually hear sound from (headphones or speakers)." : undefined}>
        <div className="flex gap-2">
          <Select value={device} onChange={(v) => { sec.set("audio_device", v); test.reset(); }} options={options} />
          <Button variant="outline" size="icon" className="h-10 w-10 shrink-0" onClick={() => refetch()} aria-label="Refresh devices" title="Refresh devices">
            <RefreshCw className={cn("h-4 w-4", isFetching && "animate-spin")} />
          </Button>
        </div>
      </Field>

      {devices?.errors.map((e) => (
        <p key={e} className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-800 dark:text-amber-300">
          {e}
        </p>
      ))}

      <Field label="Test" hint="Play any video or music, click Test, and check the level. You can also listen back to the clip.">
        <div className="space-y-3">
          <Button variant="outline" size="sm" onClick={() => test.mutate()} loading={test.isPending}>
            {test.isPending ? "Recording 5 seconds…" : (
              <>
                <Play className="h-3.5 w-3.5" /> Test audio (5 s)
              </>
            )}
          </Button>
          {test.data && <LevelMeter r={test.data} />}
        </div>
      </Field>

      {source === "loopback" && (
        <div className="flex gap-3 rounded-lg border border-line bg-surface-2/40 p-3 text-xs text-muted">
          <Headphones className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            Everything your computer plays gets recorded, so mute other tabs during a meeting. If you are in the same meeting on this laptop, mute your own Meet tab (right-click the tab → Mute site) so the audio isn't recorded twice.
          </span>
        </div>
      )}
    </Section>
  );
}

/* -------------------------------------------------------------- Appearance */
function AppearanceSection() {
  const [theme, setT] = useState(storedTheme());
  return (
    <Section id="appearance" icon={<Palette className="h-4 w-4" />} title="Appearance" description="Stored in this browser.">
      <div className="grid grid-cols-3 gap-3">
        {(
          [
            ["light", "Light", Sun],
            ["dark", "Dark", Moon],
            ["system", "System", Monitor],
          ] as const
        ).map(([v, label, Icon]) => (
          <button
            key={v}
            onClick={() => {
              setTheme(v);
              setT(v);
            }}
            className={cn(
              "flex flex-col items-center gap-2 rounded-xl border p-4 text-sm font-medium transition",
              theme === v ? "border-accent bg-accent-soft/60 text-accent-text ring-1 ring-accent" : "border-line hover:bg-surface-2",
            )}
          >
            <Icon className="h-5 w-5" /> {label}
          </button>
        ))}
      </div>
    </Section>
  );
}

/* -------------------------------------------------------------------- page */
const NAV = [
  { id: "bot", label: "Meeting bot", icon: Bot },
  { id: "audio", label: "Audio capture", icon: AudioLines },
  { id: "ai", label: "AI providers", icon: BrainCircuit },
  { id: "appearance", label: "Appearance", icon: Palette },
];

export function Settings() {
  const { data, isLoading } = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const { data: cfg } = useQuery({ queryKey: ["config"], queryFn: api.config });

  return (
    <div className="animate-fade-in">
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
      <p className="mt-1 text-sm text-muted">Changes are saved to your .env file and take effect immediately. No restart needed.</p>

      <div className="mt-6 grid gap-8 lg:grid-cols-[180px_1fr]">
        <nav className="hidden lg:block">
          <ul className="sticky top-20 space-y-0.5">
            {NAV.map(({ id, label, icon: Icon }) => (
              <li key={id}>
                <a href={`#${id}`} className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm text-muted hover:bg-surface-2 hover:text-fg">
                  <Icon className="h-4 w-4" /> {label}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <div className="min-w-0 space-y-6">
          {isLoading || !data ? (
            <>
              <Skeleton className="h-72 rounded-xl" />
              <Skeleton className="h-72 rounded-xl" />
            </>
          ) : (
            <>
              <BotSection values={data.values} />
              <AudioSection values={data.values} defaultSource={data.default_audio_source} />
              <AISection values={data.values} />
              <AppearanceSection />
              <p className="text-center text-xs text-subtle">
                IntelliMeet v{cfg?.version} · settings file: <span className="font-mono">{data.env_path}</span> · ffmpeg {cfg?.ffmpeg ? "found" : "not found"}
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
