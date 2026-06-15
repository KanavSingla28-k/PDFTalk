"use client";
import { useEffect, useState } from "react";

// The operator sets this once in the browser console:
// localStorage.setItem("admin_token", "<ADMIN_TOKEN value>")
function getAdminToken(): string {
  return typeof window !== "undefined"
    ? localStorage.getItem("admin_token") ?? ""
    : "";
}

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

export default function AdminDashboard() {
  const [stats, setStats]     = useState<Stats | null>(null);
  const [error, setError]     = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_URL}/internal/admin/stats`, {
      headers: { Authorization: `Bearer ${getAdminToken()}` },
    })
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} — check ADMIN_TOKEN in localStorage`);
        return r.json();
      })
      .then(setStats)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="p-8 text-gray-500">Loading…</p>;
  if (error)   return <p className="p-8 text-red-600 font-mono">{error}</p>;
  if (!stats)  return null;

  const { users, documents, tokens, queue } = stats;
  const maxQuota = Number(process.env.NEXT_PUBLIC_MAX_DAILY_TOKENS ?? 100000);

  return (
    <main className="p-8 max-w-5xl mx-auto space-y-8">
      <h1 className="text-2xl font-bold">PDFTalk Admin</h1>

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
          → Open Grafana dashboards (ingestion pipeline, system health)
        </a>
      </section>
    </main>
  );
}

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
    <div className={`rounded-lg border p-4 ${alert ? "border-red-400 bg-red-50" : "bg-white"}`}>
      <p className="text-xs text-gray-500 uppercase tracking-wide">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${alert ? "text-red-600" : ""}`}>
        {value.toLocaleString()}
      </p>
    </div>
  );
}
