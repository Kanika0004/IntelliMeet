import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes, Link } from "react-router-dom";
import { QueryCache, QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { Toaster } from "sonner";
import "./index.css";
import { Layout } from "./components/Layout";
import { Dashboard } from "./pages/Dashboard";
import { Meetings } from "./pages/Meetings";
import { NewMeeting } from "./pages/NewMeeting";
import { MeetingDetail } from "./pages/MeetingDetail";
import { Settings } from "./pages/Settings";
import { useTheme } from "./lib/theme";
import { Login } from "./pages/Login";
import { api, ApiError } from "./lib/api";

const queryClient: QueryClient = new QueryClient({
  // A 401 from any request means the session ended: re-check who is signed in (shows the login page).
  queryCache: new QueryCache({
    onError: (err, query) => {
      if (err instanceof ApiError && err.status === 401 && query.queryKey[0] !== "me") queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  }),
  defaultOptions: { queries: { staleTime: 5_000, retry: 1, refetchOnWindowFocus: true } },
});

function NotFound() {
  return (
    <div className="py-24 text-center">
      <p className="text-sm font-semibold text-accent-text">404</p>
      <h1 className="mt-2 text-2xl font-semibold">Page not found</h1>
      <Link to="/" className="mt-4 inline-block text-sm text-muted underline">Go to dashboard</Link>
    </div>
  );
}

function AuthGate({ children }: { children: React.ReactNode }) {
  const { data, isLoading } = useQuery({ queryKey: ["me"], queryFn: api.me, staleTime: 60_000 });
  if (isLoading) return null;
  if (data?.auth && !data.user) return <Login signup={data.signup} />;
  return <>{children}</>;
}

function ThemedToaster() {
  const { theme } = useTheme();
  return <Toaster theme={theme} position="bottom-right" richColors closeButton />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthGate>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="meetings" element={<Meetings />} />
            <Route path="meetings/:id" element={<MeetingDetail />} />
            <Route path="new" element={<NewMeeting />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
        </AuthGate>
      </BrowserRouter>
      <ThemedToaster />
    </QueryClientProvider>
  </StrictMode>,
);
