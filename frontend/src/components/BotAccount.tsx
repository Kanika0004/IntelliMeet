import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ExternalLink, Loader2, LogIn, LogOut, UserX } from "lucide-react";
import { toast } from "sonner";
import { api } from "../lib/api";
import { cn } from "../lib/format";
import { Button, Card, ConfirmDialog } from "./ui";

/** Google account used by the bot. `compact` renders a one-line banner for other pages. */
export function BotAccount({ compact = false }: { compact?: boolean }) {
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState(false);
  const { data } = useQuery({
    queryKey: ["bot-status"],
    queryFn: api.botStatus,
    refetchInterval: (q) => (q.state.data?.login_in_progress ? 1500 : false),
  });

  // Toast once when a sign-in attempt finishes.
  const wasActive = useRef(false);
  useEffect(() => {
    if (!data) return;
    if (wasActive.current && !data.login_in_progress) {
      if (data.signed_in) toast.success(data.message ?? "Bot signed in");
      else if (data.message) toast.error(data.message);
      qc.invalidateQueries({ queryKey: ["config"] });
    }
    wasActive.current = data.login_in_progress;
  }, [data, qc]);

  const refresh = (s: unknown) => qc.setQueryData(["bot-status"], s);
  const login = useMutation({ mutationFn: api.botLogin, onSuccess: refresh, onError: (e: Error) => toast.error(e.message) });
  const cancel = useMutation({ mutationFn: api.botLoginCancel, onSuccess: refresh });
  const logout = useMutation({
    mutationFn: api.botLogout,
    onSuccess: (s) => {
      refresh(s);
      setConfirm(false);
      qc.invalidateQueries({ queryKey: ["config"] });
      toast.success("Bot signed out");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (!data) return null;
  const busy = data.login_in_progress;

  const action = busy ? (
    <Button variant="outline" size="sm" onClick={() => cancel.mutate()}>
      Cancel
    </Button>
  ) : data.signed_in ? (
    <Button variant="ghost" size="sm" onClick={() => setConfirm(true)}>
      <LogOut className="h-3.5 w-3.5" /> Sign out
    </Button>
  ) : (
    <Button size="sm" onClick={() => login.mutate()} loading={login.isPending}>
      <LogIn className="h-3.5 w-3.5" /> Sign in bot
    </Button>
  );

  const icon = busy ? (
    <Loader2 className="h-4 w-4 animate-spin text-accent" />
  ) : data.signed_in ? (
    <CheckCircle2 className="h-4 w-4 text-emerald-500" />
  ) : (
    <UserX className="h-4 w-4 text-amber-500" />
  );

  const title = busy ? (data.message === "Checking sign-in…" ? "Checking sign-in…" : "Sign in, then close the Chrome window") : data.signed_in ? `Bot signed in as ${data.account}` : "Bot is not signed in to Google";
  const desc = busy
    ? data.message ?? "A Chrome window has opened. Sign in to Google there, then close that window."
    : data.signed_in
      ? "The bot joins meetings with this account."
      : "It will join as a guest. Many meetings (e.g. college/work Google Workspace) block guests.";

  const body = (
    <div className={cn("flex items-start gap-3", compact ? "p-3.5" : "p-5")}>
      <span className="mt-0.5">{icon}</span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium break-words">{title}</p>
        <p className="mt-0.5 text-[13px] text-muted">{desc}</p>
        {!compact && !busy && !data.signed_in && (
          <ul className="mt-3 space-y-1 text-[13px] text-muted">
            <li>• Use an account that is allowed in your meetings. For college meetings, that is usually your college account.</li>
            <li>• A separate account for the bot works best. If it's the same account you are using in the call, the bot joins as a second device ("Join here too").</li>
          </ul>
        )}
      </div>
      <div className="shrink-0">{action}</div>
    </div>
  );

  return (
    <>
      {compact ? (
        <div className={cn("rounded-xl border", data.signed_in ? "border-line bg-surface" : "border-amber-500/30 bg-amber-500/5")}>{body}</div>
      ) : (
        <Card>
          <div className="flex items-center justify-between px-5 pt-4">
            <h3 className="text-sm font-semibold">Bot's Google account</h3>
            <a href="https://support.google.com/meet/answer/9303164" target="_blank" rel="noreferrer" className="flex items-center gap-1 text-xs text-subtle hover:text-fg">
              Meet join rules <ExternalLink className="h-3 w-3" />
            </a>
          </div>
          {body}
        </Card>
      )}
      <ConfirmDialog
        open={confirm}
        onClose={() => setConfirm(false)}
        onConfirm={() => logout.mutate()}
        loading={logout.isPending}
        title="Sign the bot out?"
        description="This clears the bot's Chrome profile. You'll need to sign in again before it can join meetings that block guests."
        confirmLabel="Sign out"
      />
    </>
  );
}
