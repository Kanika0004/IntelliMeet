import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Bot, CalendarDays, CheckSquare, Clock, FlaskConical, Smile, Upload, Video } from "lucide-react";
import { toast } from "sonner";
import { api, ACTIVE_STATUSES, type MeetingSummary } from "../lib/api";
import { formatDuration, formatHours, greeting, relativeTime } from "../lib/format";
import { Button, Card, CardHeader, EmptyState, Progress, Skeleton } from "../components/ui";
import { PipelineStepper, SourceIcon, StatusBadge } from "../components/meeting";
import { ActionItemRow } from "./MeetingDetail";

function StatCard({ label, value, sub, icon }: { label: string; value: React.ReactNode; sub?: string; icon: React.ReactNode }) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between text-muted">
        <span className="text-[13px] font-medium">{label}</span>
        {icon}
      </div>
      <div className="mt-2 text-2xl font-semibold tracking-tight">{value}</div>
      {sub && <p className="mt-0.5 text-xs text-subtle">{sub}</p>}
    </Card>
  );
}

function LiveCard({ m }: { m: MeetingSummary }) {
  return (
    <Link to={`/meetings/${m.id}`} className="block">
      <Card className="p-4 transition hover:border-accent/40 hover:shadow-sm">
        <div className="flex flex-wrap items-center gap-3">
          <SourceIcon source={m.source} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold">{m.title}</p>
            <p className="truncate text-xs text-muted">{m.stage_message}</p>
          </div>
          <StatusBadge status={m.status} />
        </div>
        <div className="mt-4 hidden sm:block">
          <PipelineStepper meeting={m} />
        </div>
        <Progress value={m.progress} className="mt-4" />
      </Card>
    </Link>
  );
}

export function Dashboard() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data: stats } = useQuery({ queryKey: ["stats"], queryFn: api.stats, refetchInterval: 5000 });
  const { data: meetings, isLoading } = useQuery({
    queryKey: ["meetings", { q: "", status: "" }],
    queryFn: () => api.meetings(),
    refetchInterval: (q) => (q.state.data?.some((m) => ACTIVE_STATUSES.includes(m.status)) ? 2000 : 15000),
  });
  const { data: actions } = useQuery({ queryKey: ["action-items"], queryFn: api.openActionItems });

  const sample = useMutation({
    mutationFn: api.loadSample,
    onSuccess: () => {
      qc.invalidateQueries();
      toast.success("Sample meetings added");
    },
  });

  const live = meetings?.filter((m) => ACTIVE_STATUSES.includes(m.status)) ?? [];
  const recent = meetings?.filter((m) => !ACTIVE_STATUSES.includes(m.status)).slice(0, 6) ?? [];
  const empty = !isLoading && meetings?.length === 0;
  const avg = stats?.average_sentiment;

  return (
    <div className="space-y-8 animate-fade-in">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{greeting()}</h1>
          <p className="mt-1 text-sm text-muted">Here's what's happening across your meetings.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => navigate("/new?mode=upload")}>
            <Upload className="h-4 w-4" /> Upload<span className="hidden sm:inline"> recording</span>
          </Button>
          <Button onClick={() => navigate("/new")}>
            <Bot className="h-4 w-4" /> Send bot<span className="hidden sm:inline"> to a meeting</span>
          </Button>
        </div>
      </div>

      {empty ? (
        <Card className="overflow-hidden">
          <div className="grid gap-0 md:grid-cols-[1.2fr_1fr]">
            <div className="p-8">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-accent-soft px-2.5 py-1 text-xs font-medium text-accent-text">
                <Video className="h-3.5 w-3.5" /> Welcome to IntelliMeet
              </span>
              <h2 className="mt-4 text-xl font-semibold tracking-tight">Never take meeting notes again</h2>
              <p className="mt-2 max-w-md text-sm text-muted">
                Send the IntelliMeet bot into any Google Meet. It records the call, transcribes it, and gives you a summary, decisions and
                action items you can search and chat with.
              </p>
              <div className="mt-6 flex flex-wrap gap-2">
                <Button onClick={() => navigate("/new")}>
                  <Bot className="h-4 w-4" /> Send bot to a meeting
                </Button>
                <Button variant="outline" onClick={() => sample.mutate()} loading={sample.isPending}>
                  <FlaskConical className="h-4 w-4" /> Explore sample meetings
                </Button>
              </div>
            </div>
            <ol className="space-y-4 border-t border-line bg-surface-2/50 p-8 md:border-l md:border-t-0">
              {[
                ["Paste a Meet link", "Choose how long the bot should stay."],
                ["The bot joins and records", "Mic and camera stay off; it only listens."],
                ["Get the intelligence", "Summary, key points, action items, sentiment and Q&A."],
              ].map(([t, d], i) => (
                <li key={t} className="flex gap-3">
                  <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-surface text-xs font-semibold ring-1 ring-line">{i + 1}</span>
                  <div>
                    <p className="text-sm font-medium">{t}</p>
                    <p className="text-[13px] text-muted">{d}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </Card>
      ) : (
        <>
          {live.length > 0 && (
            <section>
              <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
                <span className="rec-dot h-2 w-2 rounded-full bg-red-500" /> In progress
              </h2>
              <div className="grid gap-3 md:grid-cols-2">
                {live.map((m) => (
                  <LiveCard key={m.id} m={m} />
                ))}
              </div>
            </section>
          )}

          <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {stats ? (
              <>
                <StatCard label="Meetings" value={stats.total_meetings} sub={`${stats.meetings_this_week} this week`} icon={<CalendarDays className="h-4 w-4" />} />
                <StatCard label="Time captured" value={formatHours(stats.total_seconds)} sub={`${stats.completed_meetings} processed`} icon={<Clock className="h-4 w-4" />} />
                <StatCard label="Open action items" value={stats.open_action_items} sub="across all meetings" icon={<CheckSquare className="h-4 w-4" />} />
                <StatCard
                  label="Avg. sentiment"
                  value={avg == null ? "—" : avg > 0.2 ? "Positive" : avg < -0.2 ? "Negative" : "Neutral"}
                  sub={avg == null ? "no data yet" : `score ${avg > 0 ? "+" : ""}${avg.toFixed(2)}`}
                  icon={<Smile className="h-4 w-4" />}
                />
              </>
            ) : (
              Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[106px] rounded-xl" />)
            )}
          </section>

          <section className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
            <Card>
              <CardHeader
                title="Recent meetings"
                action={
                  <Link to="/meetings" className="flex items-center gap-1 text-[13px] font-medium text-accent-text hover:underline">
                    View all <ArrowRight className="h-3.5 w-3.5" />
                  </Link>
                }
              />
              <div className="divide-y divide-line">
                {isLoading &&
                  Array.from({ length: 3 }).map((_, i) => (
                    <div key={i} className="flex gap-3 px-5 py-3">
                      <Skeleton className="h-9 w-9" />
                      <div className="flex-1 space-y-2">
                        <Skeleton className="h-3.5 w-1/2" />
                        <Skeleton className="h-3 w-3/4" />
                      </div>
                    </div>
                  ))}
                {recent.map((m) => (
                  <Link key={m.id} to={`/meetings/${m.id}`} className="flex items-start gap-3 px-5 py-3 transition hover:bg-surface-2/60">
                    <SourceIcon source={m.source} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <p className="truncate text-sm font-medium">{m.title}</p>
                        {m.status !== "completed" && <StatusBadge status={m.status} />}
                      </div>
                      <p className="mt-0.5 line-clamp-1 text-[13px] text-muted">{m.summary ?? m.error ?? m.stage_message}</p>
                    </div>
                    <div className="hidden shrink-0 flex-col items-end gap-1 sm:flex">
                      <span className="text-xs text-subtle">{relativeTime(m.created_at)}</span>
                      <span className="text-xs text-muted">{formatDuration(m.duration_seconds)}</span>
                    </div>
                  </Link>
                ))}
                {!isLoading && recent.length === 0 && <p className="px-5 py-8 text-center text-sm text-muted">Processed meetings will appear here.</p>}
              </div>
            </Card>

            <Card>
              <CardHeader title="Open action items" description="Tick them off as they get done" />
              <div className="max-h-[420px] overflow-y-auto px-2 pb-2">
                {actions?.length === 0 && (
                  <EmptyState icon={<CheckSquare className="h-5 w-5" />} title="All caught up" description="New action items from meetings will show up here." />
                )}
                {actions?.slice(0, 12).map((a) => (
                  <ActionItemRow
                    key={`${a.meeting_id}-${a.index}`}
                    meetingId={a.meeting_id}
                    index={a.index}
                    item={a}
                    footer={
                      <Link to={`/meetings/${a.meeting_id}`} className="truncate hover:text-fg hover:underline">
                        {a.meeting_title}
                      </Link>
                    }
                  />
                ))}
              </div>
            </Card>
          </section>

        </>
      )}
    </div>
  );
}
