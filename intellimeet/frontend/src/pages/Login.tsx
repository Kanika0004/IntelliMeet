import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "../lib/api";
import { Button, Card, Input, Label } from "../components/ui";

/** Sign-in / sign-up screen shown when the server has user accounts turned on. */
export function Login({ signup }: { signup: boolean }) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      if (mode === "login") await api.login({ email, password });
      else await api.register({ name, email, password });
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
      await qc.refetchQueries({ queryKey: ["me"] });
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center">
          <img src="/favicon.svg" alt="" className="h-11 w-11" />
          <h1 className="mt-3 text-xl font-semibold tracking-tight">
            Intelli<span className="text-accent">Meet</span>
          </h1>
          <p className="mt-1 text-sm text-muted">AI meeting assistant: record, transcribe, summarise and ask questions.</p>
        </div>
        <Card className="p-6">
          <h2 className="text-base font-semibold">{mode === "login" ? "Sign in" : "Create your account"}</h2>
          <form onSubmit={submit} className="mt-4 space-y-4">
            {mode === "register" && (
              <div>
                <Label htmlFor="name">Name</Label>
                <Input id="name" value={name} onChange={(e) => setName(e.target.value)} required autoComplete="name" />
              </div>
            )}
            <div>
              <Label htmlFor="email">E-mail</Label>
              <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
            </div>
            <div>
              <Label htmlFor="password" hint={mode === "register" ? "At least 8 characters" : undefined}>
                Password
              </Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={mode === "register" ? 8 : undefined}
                autoComplete={mode === "login" ? "current-password" : "new-password"}
              />
            </div>
            <Button type="submit" className="w-full" loading={busy}>
              {mode === "login" ? "Sign in" : "Create account"}
            </Button>
          </form>
          {signup && (
            <p className="mt-4 text-center text-[13px] text-muted">
              {mode === "login" ? "New here? " : "Already have an account? "}
              <button type="button" className="font-medium text-accent-text hover:underline" onClick={() => setMode(mode === "login" ? "register" : "login")}>
                {mode === "login" ? "Create an account" : "Sign in"}
              </button>
            </p>
          )}
        </Card>
      </div>
    </div>
  );
}
