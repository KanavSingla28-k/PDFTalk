"use client";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "";

// ── Types ──────────────────────────────────────────────────────────────────

type Stats = {
  users: {
    total: number;
    verified: number;
    unverified: number;
    signups_by_day: { day: string; count: number }[];
  };
  documents: { total: number; by_status: Record<string, number> };
  emails: { verification_tokens_active: number };
  tokens: { top_users_today: { user_id: string; tokens_today: number }[] };
  queue: { dead_letter_count: number; failed_jobs_7d: number };
};

type View = "login" | "dashboard";

// ── Login form ─────────────────────────────────────────────────────────────

function LoginForm({ onSuccess }: { onSuccess: () => void }) {
  const [token, setToken]   = useState("");
  const [error, setError]   = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit() {
    if (!token.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/internal/admin/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",   // receive the httpOnly cookie
        body: JSON.stringify({ token }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail ?? `${res.status}`);
      }
      onSuccess();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="bg-white border rounded-xl p-8 w-full max-w-sm space-y-4 shadow-sm">
        <h1 className="text-xl font-bold">PDFTalk Admin</h1>
        <p className="text-sm text-gray-500">Enter your admin token to continue.</p>

        <input
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
          placeholder="Admin token"
          className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-300"
          autoFocus
        />

        {error && (
          <p className="text-sm text-red-600 font-mono">{error}</p>
        )}

        <button
          onClick={handleSubmit}
          disabled={loading || !token.trim()}
          className="w-full bg-gray-900 text-white rounded-lg py-2 text-sm font-medium
                     hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {loading ? "Signing in…" : "Sign in"}
        </button>
      </div>
    </main>
  );
}

// ── Dashboard ──────────────────────────────────────────────────────────────

function Dashboard({ onLogout }: { onLogout: () => void }) {
  const [stats, setStats]   = useState<Stats | null>(null);
  const [error, setError]   = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API}/internal/admin/stats`, {
      credentials: "include",   // send the httpOnly cookie — no token in JS
    })
      .then((r) => {
        if (r.status === 401 || r.status === 403) {
          // Cookie expired or missing — go back to login
          onLogout();
          return null;
        }
        if (!r.ok) throw new Error(`${r.status}`);
        return r.json();
      })
      .then((data) => data && setStats(data))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [onLogout]);

  async function handleLogout() {
    await fetch(`${API}/internal/admin/logout`, {
      method: "POST",
      credentials: "include",
    });
    onLogout();
  }

  if (loading) return <p className="p-8 text-gray-500">Loading…</p>;
  if (error)   return <p className="p-8 text-red-600 font-mono">{error}</p>;
  if (!stats)  return null;

  const { users, documents, tokens, queue } = stats;
  const maxQuota = Number(process.env.NEXT_PUBLIC_MAX_DAILY_TOKENS ?? 100000);

  return (
    <main className="p-8 max-w-5xl mx-auto space-y-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">PDFTalk Admin</h1>
        <button
          onClick={handleLogout}
          className="text-sm text-gray-500 hover:text-gray-800 underline"
        >
          Sign out
        </button>
      </div>

      {/* Users */}
      <section>
        <h2 className="text-lg font-semibold mb-3">Users</h2>
        <div className="grid grid-cols-3 gap-4">
          <Stat label="Total"      value={users.total} />
          <Stat label="Verified"   value={users.verified} />
          <Stat label="Unverified" value={users.unverified} />
        </div>
        <p className="mt-4 text-sm text-gray-500">
          Sign-ups last 30 days:{" "}
          {users.signups_by_day.map((d) => `${d.day}: ${d.count}`).join(" · ")}
        </p>
      </section>

      {/* Documents */}
      <section>
        <h2 className="text-lg font-semibold mb-3">Documents</h2>
        <div className="grid grid-cols-4 gap-4">
          {Object.entries(documents.by_status).map(([s, count]) => (
            <Stat key={s} label={s} value={count as number} />
          ))}
        </div>
      </section>

      {/* Queue health */}
      <section>
        <h2 className="text-lg font-semibold mb-3">Queue Health</h2>
        <div className="grid grid-cols-2 gap-4">
          <Stat
            label="Dead-letter jobs"
            value={queue.dead_letter_count}
            alert={queue.dead_letter_count > 0}
          />
          <Stat
            label="Failed jobs (7d)"
            value={queue.failed_jobs_7d}
            alert={queue.failed_jobs_7d > 10}
          />
        </div>
      </section>

      {/* Token utilization */}
      <section>
        <h2 className="text-lg font-semibold mb-3">
          Token Utilization Today (Top 20 Users)
        </h2>
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b text-left text-gray-500">
              <th className="py-2 pr-4">User ID</th>
              <th className="py-2 pr-4">Tokens Used</th>
              <th className="py-2">% of Daily Quota</th>
            </tr>
          </thead>
          <tbody>
            {tokens.top_users_today.map((u) => {
              const pct = ((u.tokens_today / maxQuota) * 100).toFixed(1);
              const over80 = Number(pct) > 80;
              return (
                <tr key={u.user_id} className="border-b hover:bg-gray-50">
                  <td className="py-1 pr-4 font-mono text-xs">{u.user_id}</td>
                  <td className="py-1 pr-4">{u.tokens_today.toLocaleString()}</td>
                  <td className="py-1">
                    <div className="flex items-center gap-2">
                      <div className="w-32 bg-gray-200 rounded-full h-1.5">
                        <div
                          className={`h-1.5 rounded-full ${over80 ? "bg-red-500" : "bg-blue-500"}`}
                          style={{ width: `${Math.min(Number(pct), 100)}%` }}
                        />
                      </div>
                      <span className={over80 ? "text-red-600 font-medium" : ""}>
                        {pct}%
                      </span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      {/* Grafana link */}
      <section className="border-t pt-4">
        <a
          href="/grafana"
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-600 underline text-sm"
        >
          → Open Grafana dashboards
        </a>
      </section>
    </main>
  );
}

// ── Root ───────────────────────────────────────────────────────────────────

export default function AdminPage() {
  const [view, setView] = useState<View>("login");

  // On mount, probe the stats endpoint — if the cookie is already valid
  // (e.g., page refresh within the 8-hour window) skip the login screen.
  useEffect(() => {
    fetch(`${API}/internal/admin/stats`, { credentials: "include" })
      .then((r) => { if (r.ok) setView("dashboard"); })
      .catch(() => {});
  }, []);

  if (view === "dashboard")
    return <Dashboard onLogout={() => setView("login")} />;

  return <LoginForm onSuccess={() => setView("dashboard")} />;
}

// ── Shared components ──────────────────────────────────────────────────────

function Stat({
  label,
  value,
  alert = false,
}: {
  label: string;
  value: number;
  alert?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border p-4 ${
        alert ? "border-red-400 bg-red-50" : "bg-white"
      }`}
    >
      <p className="text-xs text-gray-500 uppercase tracking-wide">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${alert ? "text-red-600" : ""}`}>
        {value.toLocaleString()}
      </p>
    </div>
  );
}
