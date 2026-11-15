import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { FlaskConical, ListVideo, Plus, Search, X } from "lucide-react";
import { api, ACTIVE_STATUSES } from "../lib/api";
import { formatDate, formatDuration } from "../lib/format";
import { Button, Card, EmptyState, Input, Segmented, Skeleton } from "../components/ui";
import { SentimentBadge, SourceIcon, StatusBadge, sourceLabel } from "../components/meeting";

type Filter = "" | "active" | "completed" | "failed";

function useDebounced<T>(value: T, ms = 250) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function Meetings() {
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const status = (params.get("status") ?? "") as Filter;
  const dq = useDebounced(q);
  const navigate = useNavigate();

  useEffect(() => {
    const next = new URLSearchParams(params);
    if (dq) next.set("q", dq);
    else next.delete("q");
    setParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dq]);

  const { data, isLoading } = useQuery({
    queryKey: ["meetings", { q: dq, status }],
    queryFn: () => api.meetings({ q: dq, status }),
    refetchInterval: (query) => (query.state.data?.some((m) => ACTIVE_STATUSES.includes(m.status)) ? 2000 : false),
    placeholderData: (prev) => prev,
  });

  const setStatus = (s: Filter) => {
    const next = new URLSearchParams(params);
    if (s) next.set("status", s);
    else next.delete("status");
    setParams(next, { replace: true });
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Meetings</h1>
          <p className="mt-1 text-sm text-muted">Every recorded and uploaded meeting, searchable by title, transcript and summary.</p>
        </div>
        <Button onClick={() => navigate("/new")}>
          <Plus className="h-4 w-4" /> New meeting
        </Button>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full sm:max-w-xs">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search meetings…" className="pl-9 pr-8" />
          {q && (
            <button onClick={() => setQ("")} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-subtle hover:text-fg" aria-label="Clear search">
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
        <Segmented<Filter>
          value={status}
          onChange={setStatus}
          items={[
            { value: "", label: "All" },
            { value: "active", label: "In progress" },
            { value: "completed", label: "Completed" },
            { value: "failed", label: "Failed" },
          ]}
        />
      </div>

      <Card className="overflow-hidden">
        {isLoading ? (
          <div className="divide-y divide-line">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="flex items-center gap-3 px-5 py-4">
                <Skeleton className="h-9 w-9" />
                <Skeleton className="h-4 flex-1" />
                <Skeleton className="h-4 w-20" />
              </div>
            ))}
          </div>
        ) : data && data.length > 0 ? (
          <table className="w-full text-sm">
            <thead className="hidden border-b border-line bg-surface-2/50 text-left text-xs font-medium text-muted md:table-header-group">
              <tr>
                <th className="px-5 py-2.5 font-medium">Meeting</th>
                <th className="px-3 py-2.5 font-medium">Date</th>
                <th className="px-3 py-2.5 font-medium">Duration</th>
                <th className="px-3 py-2.5 font-medium">Action items</th>
                <th className="px-3 py-2.5 font-medium">Sentiment</th>
                <th className="px-5 py-2.5 text-right font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {data.map((m) => (
                <tr key={m.id} onClick={() => navigate(`/meetings/${m.id}`)} className="cursor-pointer transition hover:bg-surface-2/60">
                  <td className="px-5 py-3.5">
                    <div className="flex items-center gap-3">
                      <SourceIcon source={m.source} />
                      <div className="min-w-0">
                        <Link to={`/meetings/${m.id}`} className="block truncate font-medium" onClick={(e) => e.stopPropagation()}>
                          {m.title}
                        </Link>
                        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
                          <span>{sourceLabel(m.source)}</span>
                          {m.topics.slice(0, 3).map((t) => (
                            <span key={t} className="hidden rounded bg-surface-2 px-1.5 py-px lg:inline">
                              {t}
                            </span>
                          ))}
                          <span className="md:hidden">· {formatDate(m.created_at)}</span>
                        </div>
                      </div>
                      <div className="ml-auto md:hidden">
                        <StatusBadge status={m.status} />
                      </div>
                    </div>
                  </td>
                  <td className="hidden whitespace-nowrap px-3 py-3.5 text-muted md:table-cell">{formatDate(m.created_at)}</td>
                  <td className="hidden whitespace-nowrap px-3 py-3.5 text-muted md:table-cell">{formatDuration(m.duration_seconds)}</td>
                  <td className="hidden px-3 py-3.5 md:table-cell">
                    {m.action_items_total ? (
                      <span className="text-muted">
                        <span className="font-medium text-fg">{m.action_items_open}</span> open / {m.action_items_total}
                      </span>
                    ) : (
                      <span className="text-subtle">—</span>
                    )}
                  </td>
                  <td className="hidden px-3 py-3.5 md:table-cell">{m.sentiment ? <SentimentBadge sentiment={m.sentiment} /> : <span className="text-subtle">—</span>}</td>
                  <td className="hidden px-5 py-3.5 text-right md:table-cell">
                    <StatusBadge status={m.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : dq || status ? (
          <EmptyState
            icon={<Search className="h-5 w-5" />}
            title="No matching meetings"
            description="Try a different search term or filter."
            action={
              <Button
                variant="outline"
                onClick={() => {
                  setQ("");
                  setStatus("");
                }}
              >
                Clear filters
              </Button>
            }
          />
        ) : (
          <EmptyState
            icon={<ListVideo className="h-5 w-5" />}
            title="No meetings yet"
            description="Send the bot into a Google Meet or upload a recording to get started."
            action={
              <>
                <Button onClick={() => navigate("/new")}>
                  <Plus className="h-4 w-4" /> New meeting
                </Button>
                <Button variant="outline" onClick={() => api.loadSample().then(() => window.location.reload())}>
                  <FlaskConical className="h-4 w-4" /> Load samples
                </Button>
              </>
            }
          />
        )}
      </Card>
      {data && data.length > 0 && <p className="text-xs text-subtle">{data.length} meeting{data.length === 1 ? "" : "s"}</p>}
    </div>
  );
}
