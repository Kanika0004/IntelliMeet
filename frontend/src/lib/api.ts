export type MeetingStatus =
  | "queued"
  | "joining"
  | "recording"
  | "transcribing"
  | "analyzing"
  | "completed"
  | "failed"
  | "cancelled";

export const ACTIVE_STATUSES: MeetingStatus[] = ["queued", "joining", "recording", "transcribing", "analyzing"];

export interface ActionItem {
  task: string;
  owner: string | null;
  due: string | null;
  done: boolean;
}

export interface Sentiment {
  label: "positive" | "neutral" | "negative" | "mixed" | string;
  score: number;
  explanation: string;
}

export interface Analysis {
  title: string;
  summary: string;
  key_points: string[];
  decisions: string[];
  action_items: ActionItem[];
  topics: string[];
  sentiment: Sentiment;
  provider: string;
  warning?: string;
}

export interface Segment {
  start: number;
  end: number;
  text: string;
  speaker?: string;
}

export interface Transcript {
  text: string;
  language: string | null;
  segments: Segment[];
}

export interface MeetingBase {
  id: string;
  title: string;
  source: "bot" | "upload" | "sample";
  meet_link: string | null;
  status: MeetingStatus;
  stage_message: string | null;
  progress: number;
  duration_requested: number | null;
  duration_seconds: number | null;
  analyze: boolean;
  original_filename: string | null;
  has_audio: boolean;
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface MeetingSummary extends MeetingBase {
  summary: string | null;
  topics: string[];
  sentiment: Sentiment | null;
  action_items_total: number;
  action_items_open: number;
}

export interface MeetingEvent {
  stage: string;
  message: string;
  at: string;
}

export interface MeetingDetail extends MeetingBase {
  can_reprocess: boolean;
  analysis: Analysis | null;
  transcript: Transcript | null;
  events: MeetingEvent[];
}

export interface Stats {
  total_meetings: number;
  completed_meetings: number;
  meetings_this_week: number;
  total_seconds: number;
  open_action_items: number;
  average_sentiment: number | null;
  active_jobs: number;
}

export interface OpenActionItem extends ActionItem {
  index: number;
  meeting_id: string;
  meeting_title: string;
  meeting_date: string;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface AppConfig {
  version: string;
  demo?: boolean;
  transcriber: { provider: string; configured: boolean; model: string };
  analyzer: { provider: string; model: string; configured: boolean };
  bot: {
    display_name: string;
    chrome_profile: boolean;
    account: string | null;
    google_credentials: boolean;
    headless: boolean;
    audio_device: string | null;
    default_duration: number;
  };
  ffmpeg: boolean;
  audio: { source: string; device: string | null };
}

export type Secret = { set: boolean; masked: string };
export interface SettingsValues {
  transcriber: string;
  openai_api_key: Secret;
  whisper_model: string;
  local_whisper_model: string;
  analyzer: string;
  gpt_model: string;
  gemini_api_key: Secret;
  gemini_model: string;
  bot_display_name: string;
  duration: number;
  admit_timeout: number;
  headless: boolean;
  audio_source: string;
  audio_device: string | number;
}
export interface AudioDevices {
  loopback_supported: boolean;
  speakers: string[];
  default_speaker: string | null;
  inputs: string[];
  default_input: string | null;
  errors: string[];
}
export interface AudioTestResult {
  seconds: number;
  peak: number;
  rms: number;
  source: string;
  silent: boolean;
  url: string;
}

export interface BotStatus {
  signed_in: boolean;
  account: string | null;
  login_in_progress: boolean;
  message: string | null;
  profile_dir: string;
  password_fallback: boolean;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init);
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : body.detail?.[0]?.msg ?? msg;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, msg || `Request failed (${res.status})`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  config: () => request<AppConfig>("/config"),
  stats: () => request<Stats>("/stats"),
  meetings: (params: { q?: string; status?: string } = {}) => {
    const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]);
    return request<MeetingSummary[]>(`/meetings${qs.toString() ? `?${qs}` : ""}`);
  },
  meeting: (id: string) => request<MeetingDetail>(`/meetings/${id}`),
  sendBot: (body: { meet_link: string; title?: string; duration_minutes: number; analyze: boolean }) =>
    request<MeetingDetail>("/meetings", json("POST", body)),
  upload: (file: File, title: string, analyze: boolean, onProgress?: (pct: number) => void) =>
    new Promise<MeetingDetail>((resolve, reject) => {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("title", title);
      fd.append("analyze", String(analyze));
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/meetings/upload");
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(Math.round((e.loaded / e.total) * 100));
      xhr.onload = () => {
        let body: any = null;
        try {
          body = JSON.parse(xhr.responseText);
        } catch {
          /* ignore */
        }
        if (xhr.status >= 200 && xhr.status < 300) resolve(body);
        else reject(new ApiError(xhr.status, body?.detail ?? "Upload failed"));
      };
      xhr.onerror = () => reject(new ApiError(0, "Network error during upload"));
      xhr.send(fd);
    }),
  rename: (id: string, title: string) => request<MeetingDetail>(`/meetings/${id}`, json("PATCH", { title })),
  remove: (id: string) => request<void>(`/meetings/${id}`, { method: "DELETE" }),
  stop: (id: string) => request<MeetingDetail>(`/meetings/${id}/stop`, { method: "POST" }),
  retry: (id: string, mode: "auto" | "rejoin" | "reprocess" | "reanalyze" = "auto") =>
    request<MeetingDetail>(`/meetings/${id}/retry?mode=${mode}`, { method: "POST" }),
  settings: () => request<{ values: SettingsValues; env_path: string; default_audio_source: string }>("/settings"),
  saveSettings: (changes: Partial<Record<keyof SettingsValues, unknown>>) =>
    request<{ saved: string[]; values: SettingsValues }>("/settings", json("PUT", changes)),
  testAI: () => request<{ ok: boolean; provider: string; message: string }>("/settings/test-ai", { method: "POST" }),
  audioDevices: () => request<AudioDevices>("/audio/devices"),
  audioTest: (body: { seconds?: number; audio_source?: string; audio_device?: string }) =>
    request<AudioTestResult>("/audio/test", json("POST", body)),
  toggleAction: (id: string, index: number, done: boolean) =>
    request<ActionItem>(`/meetings/${id}/action-items/${index}`, json("PATCH", { done })),
  openActionItems: () => request<OpenActionItem[]>("/action-items?status=open"),
  chat: (id: string) => request<ChatMessage[]>(`/meetings/${id}/chat`),
  ask: (id: string, message: string) => request<ChatMessage>(`/meetings/${id}/chat`, json("POST", { message })),
  clearChat: (id: string) => request<void>(`/meetings/${id}/chat`, { method: "DELETE" }),
  botStatus: () => request<BotStatus>("/bot/status"),
  botLogin: () => request<BotStatus>("/bot/login", { method: "POST" }),
  botLoginCancel: () => request<BotStatus>("/bot/login/cancel", { method: "POST" }),
  botLogout: () => request<BotStatus>("/bot/logout", { method: "POST" }),
  loadSample: () => request<{ ids: string[] }>("/sample", { method: "POST" }),
  audioUrl: (id: string) => `/api/meetings/${id}/audio`,
  exportUrl: (id: string, format: "md" | "json") => `/api/meetings/${id}/export?format=${format}`,
};
