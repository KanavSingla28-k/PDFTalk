"use client";
import { useEffect, useState, useCallback } from "react";
import { getApiBaseUrl } from "@/lib/api";

const API = getApiBaseUrl();

// ── Types ───────────────────────────────────────────────────────────────────

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

// ── Status colour map ────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, string> = {
  ready:      "#10b981",
  processing: "#f59e0b",
  failed:     "#ef4444",
  pending:    "#6366f1",
};

// ── Login form ───────────────────────────────────────────────────────────────

function LoginForm({ onSuccess }: { onSuccess: () => void }) {
  const [token, setToken]     = useState("");
  const [error, setError]     = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit() {
    if (!token.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/internal/admin/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
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
    <main style={styles.loginBg}>
      <div style={styles.loginCard}>
        {/* Logo */}
        <div style={styles.logoRow}>
          <div style={styles.logoIcon}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#818cf8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14,2 14,8 20,8"/>
              <line x1="16" y1="13" x2="8" y2="13"/>
              <line x1="16" y1="17" x2="8" y2="17"/>
              <polyline points="10,9 9,9 8,9"/>
            </svg>
          </div>
          <span style={styles.logoText}>PDFTalk</span>
          <span style={styles.logoBadge}>Admin</span>
        </div>

        <h1 style={styles.loginTitle}>Command Centre</h1>
        <p style={styles.loginSub}>Authenticate with your admin token to continue.</p>

        <div style={styles.inputWrap}>
          <svg style={styles.inputIcon} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#6b7280" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
            <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
          </svg>
          <input
            id="admin-token-input"
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
            placeholder="Enter admin token"
            style={styles.input}
            autoFocus
          />
        </div>

        {error && (
          <div style={styles.errorBox}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#f87171" strokeWidth="2">
              <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
            {error}
          </div>
        )}

        <button
          id="admin-login-btn"
          onClick={handleSubmit}
          disabled={loading || !token.trim()}
          style={{ ...styles.loginBtn, opacity: (loading || !token.trim()) ? 0.5 : 1 }}
        >
          {loading ? (
            <span style={styles.spinner} />
          ) : (
            <>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10,17 15,12 10,7"/><line x1="15" y1="12" x2="3" y2="12"/>
              </svg>
              Sign in
            </>
          )}
        </button>
      </div>
    </main>
  );
}

// ── Stat card ────────────────────────────────────────────────────────────────

function StatCard({
  label, value, icon, color = "#6366f1", alert = false, sub,
}: {
  label: string; value: number | string; icon: React.ReactNode;
  color?: string; alert?: boolean; sub?: string;
}) {
  return (
    <div style={{ ...styles.statCard, borderColor: alert ? "#ef4444" : "rgba(255,255,255,0.07)" }}>
      <div style={{ ...styles.statIcon, background: `${color}22`, color }}>
        {icon}
      </div>
      <div>
        <p style={styles.statLabel}>{label}</p>
        <p style={{ ...styles.statValue, color: alert ? "#f87171" : "#f1f5f9" }}>
          {typeof value === "number" ? value.toLocaleString() : value}
        </p>
        {sub && <p style={styles.statSub}>{sub}</p>}
      </div>
      {alert && (
        <div style={styles.alertDot} />
      )}
    </div>
  );
}

// ── Mini bar chart ───────────────────────────────────────────────────────────

function SparkBars({ data }: { data: { day: string; count: number }[] }) {
  const max = Math.max(...data.map((d) => d.count), 1);
  const last7 = data.slice(-14);
  return (
    <div style={styles.sparkWrap}>
      {last7.map((d, i) => (
        <div key={i} style={styles.sparkBarCol}>
          <div style={{ ...styles.sparkBar, height: `${Math.max((d.count / max) * 100, 4)}%` }} />
          {i % 3 === 0 && (
            <span style={styles.sparkLabel}>{d.day.slice(5)}</span>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Dashboard ────────────────────────────────────────────────────────────────

function Dashboard({ onLogout }: { onLogout: () => void }) {
  const [stats, setStats]     = useState<Stats | null>(null);
  const [error, setError]     = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  const fetchStats = useCallback(() => {
    setLoading(true);
    fetch(`${API}/internal/admin/stats`, { credentials: "include" })
      .then((r) => {
        if (r.status === 401 || r.status === 403) { onLogout(); return null; }
        if (!r.ok) throw new Error(`${r.status}`);
        return r.json();
      })
      .then((data) => {
        if (data) { setStats(data); setLastRefresh(new Date()); }
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [onLogout]);

  useEffect(() => { fetchStats(); }, [fetchStats]);

  async function handleLogout() {
    await fetch(`${API}/internal/admin/logout`, { method: "POST", credentials: "include" });
    onLogout();
  }

  if (error) return (
    <main style={styles.dashBg}>
      <div style={{ padding: "2rem", color: "#f87171", fontFamily: "monospace" }}>
        ❌ {error}
      </div>
    </main>
  );

  const { users, documents, tokens, queue } = stats ?? {
    users: { total: 0, verified: 0, unverified: 0, signups_by_day: [] },
    documents: { total: 0, by_status: {} },
    tokens: { top_users_today: [] },
    queue: { dead_letter_count: 0, failed_jobs_7d: 0 },
  };

  const maxQuota = 100000;
  const docStatuses = Object.entries(documents.by_status);

  return (
    <main style={styles.dashBg}>
      {/* Top bar */}
      <header style={styles.topBar}>
        <div style={styles.logoRow}>
          <div style={styles.logoIcon}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#818cf8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14,2 14,8 20,8"/>
            </svg>
          </div>
          <span style={styles.logoText}>PDFTalk</span>
          <span style={styles.logoBadge}>Admin</span>
        </div>

        <div style={styles.topBarRight}>
          <span style={styles.refreshTime}>
            Updated {lastRefresh.toLocaleTimeString()}
          </span>
          <button
            id="admin-refresh-btn"
            onClick={fetchStats}
            disabled={loading}
            style={styles.refreshBtn}
            title="Refresh"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
              style={{ animation: loading ? "spin 1s linear infinite" : "none" }}>
              <polyline points="23,4 23,10 17,10"/>
              <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
            </svg>
          </button>
          <button
            id="admin-grafana-btn"
            onClick={() => window.open("/grafana", "_blank")}
            style={styles.grafanaBtn}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/>
              <line x1="6" y1="20" x2="6" y2="14"/>
            </svg>
            Grafana
          </button>
          <button id="admin-logout-btn" onClick={handleLogout} style={styles.logoutBtn}>
            Sign out
          </button>
        </div>
      </header>

      <div style={styles.dashContent}>

        {/* KPI row */}
        <section style={styles.kpiGrid}>
          <StatCard
            label="Total Users"
            value={users.total}
            color="#6366f1"
            icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>}
            sub={`${users.verified} verified · ${users.unverified} unverified`}
          />
          <StatCard
            label="Total Documents"
            value={documents.total}
            color="#10b981"
            icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/></svg>}
          />
          <StatCard
            label="Dead-letter Jobs"
            value={queue.dead_letter_count}
            color={queue.dead_letter_count > 0 ? "#ef4444" : "#10b981"}
            alert={queue.dead_letter_count > 0}
            icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="7.86,2 16.14,2 22,7.86 22,16.14 16.14,22 7.86,22 2,16.14 2,7.86"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>}
            sub={`${queue.failed_jobs_7d} failed in last 7 days`}
          />
          <StatCard
            label="Pending Verifications"
            value={stats?.emails.verification_tokens_active ?? 0}
            color="#f59e0b"
            icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>}
          />
        </section>

        {/* Charts row */}
        <div style={styles.chartsRow}>

          {/* Signup trend */}
          <section style={styles.panel}>
            <div style={styles.panelHeader}>
              <span style={styles.panelTitle}>Sign-up Trend (Last 14 Days)</span>
            </div>
            {users.signups_by_day.length > 0
              ? <SparkBars data={users.signups_by_day} />
              : <p style={styles.emptyMsg}>No sign-up data yet.</p>
            }
          </section>

          {/* Document status */}
          <section style={styles.panel}>
            <div style={styles.panelHeader}>
              <span style={styles.panelTitle}>Documents by Status</span>
            </div>
            {docStatuses.length > 0 ? (
              <div style={styles.statusList}>
                {docStatuses.map(([status, count]) => {
                  const total = documents.total || 1;
                  const pct   = ((count / total) * 100).toFixed(0);
                  const color = STATUS_COLORS[status] ?? "#6366f1";
                  return (
                    <div key={status} style={styles.statusRow}>
                      <div style={styles.statusLabelRow}>
                        <span style={{ ...styles.statusDot, background: color }} />
                        <span style={styles.statusName}>{status}</span>
                        <span style={styles.statusCount}>{count}</span>
                      </div>
                      <div style={styles.barBg}>
                        <div style={{ ...styles.barFill, width: `${pct}%`, background: color }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p style={styles.emptyMsg}>No documents yet.</p>
            )}
          </section>
        </div>

        {/* Token utilization table */}
        <section style={styles.panel}>
          <div style={styles.panelHeader}>
            <span style={styles.panelTitle}>Token Utilization Today (Top 20 Users)</span>
            <span style={styles.panelSub}>Daily quota: {maxQuota.toLocaleString()} tokens</span>
          </div>
          {tokens.top_users_today.length === 0 ? (
            <p style={styles.emptyMsg}>No query activity today.</p>
          ) : (
            <div style={styles.tableWrap}>
              <table style={styles.table}>
                <thead>
                  <tr>
                    <th style={styles.th}>#</th>
                    <th style={styles.th}>User ID</th>
                    <th style={styles.th}>Tokens Used</th>
                    <th style={styles.th}>Quota Usage</th>
                  </tr>
                </thead>
                <tbody>
                  {tokens.top_users_today.map((u, i) => {
                    const pct    = (u.tokens_today / maxQuota) * 100;
                    const over80 = pct > 80;
                    const color  = over80 ? "#ef4444" : pct > 50 ? "#f59e0b" : "#10b981";
                    return (
                      <tr key={u.user_id} style={styles.tr}>
                        <td style={{ ...styles.td, color: "#6b7280", width: "2rem" }}>{i + 1}</td>
                        <td style={{ ...styles.td, fontFamily: "monospace", fontSize: "0.75rem", color: "#94a3b8" }}>
                          {u.user_id}
                        </td>
                        <td style={{ ...styles.td, color: "#f1f5f9" }}>
                          {u.tokens_today.toLocaleString()}
                        </td>
                        <td style={{ ...styles.td, minWidth: "200px" }}>
                          <div style={styles.quotaRow}>
                            <div style={styles.barBg}>
                              <div style={{ ...styles.barFill, width: `${Math.min(pct, 100)}%`, background: color }} />
                            </div>
                            <span style={{ ...styles.quotaPct, color }}>{pct.toFixed(1)}%</span>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>

      </div>

      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
      `}</style>
    </main>
  );
}

// ── Root ─────────────────────────────────────────────────────────────────────

export default function AdminPage() {
  const [view, setView] = useState<View>("login");

  useEffect(() => {
    fetch(`${API}/internal/admin/stats`, { credentials: "include" })
      .then((r) => { if (r.ok) setView("dashboard"); })
      .catch(() => {});
  }, []);

  if (view === "dashboard")
    return <Dashboard onLogout={() => setView("login")} />;

  return <LoginForm onSuccess={() => setView("dashboard")} />;
}

// ── Styles ────────────────────────────────────────────────────────────────────

const styles: Record<string, React.CSSProperties> = {
  /* Login */
  loginBg: {
    minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center",
    background: "linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #0f0f1a 100%)",
    fontFamily: "'Inter', system-ui, sans-serif",
  },
  loginCard: {
    background: "rgba(255,255,255,0.04)", backdropFilter: "blur(24px)",
    border: "1px solid rgba(255,255,255,0.09)", borderRadius: "20px",
    padding: "2.5rem", width: "100%", maxWidth: "400px",
    boxShadow: "0 25px 60px rgba(0,0,0,0.5)",
  },
  loginTitle: { color: "#f1f5f9", fontSize: "1.5rem", fontWeight: 700, margin: "1rem 0 0.25rem" },
  loginSub:   { color: "#6b7280", fontSize: "0.875rem", marginBottom: "1.75rem" },
  inputWrap:  { position: "relative", marginBottom: "1rem" },
  inputIcon:  { position: "absolute", left: "0.875rem", top: "50%", transform: "translateY(-50%)" },
  input: {
    width: "100%", boxSizing: "border-box",
    background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)",
    borderRadius: "10px", padding: "0.75rem 0.875rem 0.75rem 2.5rem",
    color: "#f1f5f9", fontSize: "0.875rem", outline: "none",
  },
  loginBtn: {
    width: "100%", display: "flex", alignItems: "center", justifyContent: "center", gap: "0.5rem",
    background: "linear-gradient(135deg, #6366f1, #4f46e5)", color: "#fff",
    border: "none", borderRadius: "10px", padding: "0.75rem", fontSize: "0.9rem",
    fontWeight: 600, cursor: "pointer", transition: "opacity 0.2s",
  },
  errorBox: {
    display: "flex", alignItems: "center", gap: "0.5rem",
    background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)",
    borderRadius: "8px", padding: "0.625rem 0.875rem",
    color: "#f87171", fontSize: "0.8rem", marginBottom: "1rem",
  },
  spinner: {
    width: "16px", height: "16px", borderRadius: "50%",
    border: "2px solid rgba(255,255,255,0.3)", borderTopColor: "#fff",
    display: "inline-block", animation: "spin 0.8s linear infinite",
  },

  /* Shared logo */
  logoRow:  { display: "flex", alignItems: "center", gap: "0.5rem" },
  logoIcon: {
    width: "32px", height: "32px", borderRadius: "8px",
    background: "rgba(99,102,241,0.15)", display: "flex", alignItems: "center", justifyContent: "center",
  },
  logoText:  { color: "#f1f5f9", fontWeight: 700, fontSize: "1rem" },
  logoBadge: {
    fontSize: "0.65rem", fontWeight: 600, letterSpacing: "0.05em",
    background: "rgba(99,102,241,0.2)", color: "#818cf8",
    padding: "0.2rem 0.5rem", borderRadius: "999px", border: "1px solid rgba(99,102,241,0.3)",
  },

  /* Dashboard */
  dashBg: {
    minHeight: "100vh", background: "#0b0b14",
    fontFamily: "'Inter', system-ui, sans-serif", color: "#f1f5f9",
  },
  topBar: {
    display: "flex", alignItems: "center", justifyContent: "space-between",
    padding: "0.875rem 1.75rem",
    borderBottom: "1px solid rgba(255,255,255,0.07)",
    background: "rgba(255,255,255,0.02)", backdropFilter: "blur(12px)",
    position: "sticky", top: 0, zIndex: 10,
  },
  topBarRight:  { display: "flex", alignItems: "center", gap: "0.75rem" },
  refreshTime:  { color: "#4b5563", fontSize: "0.75rem" },
  refreshBtn: {
    background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.08)",
    borderRadius: "8px", padding: "0.4rem 0.6rem", color: "#9ca3af", cursor: "pointer",
    display: "flex", alignItems: "center",
  },
  grafanaBtn: {
    display: "flex", alignItems: "center", gap: "0.4rem",
    background: "rgba(249,115,22,0.12)", border: "1px solid rgba(249,115,22,0.25)",
    borderRadius: "8px", padding: "0.4rem 0.875rem", color: "#fb923c",
    fontSize: "0.8rem", fontWeight: 600, cursor: "pointer",
  },
  logoutBtn: {
    background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.08)",
    borderRadius: "8px", padding: "0.4rem 0.875rem", color: "#9ca3af",
    fontSize: "0.8rem", cursor: "pointer",
  },

  dashContent: { padding: "1.75rem", maxWidth: "1300px", margin: "0 auto" },

  /* KPI grid */
  kpiGrid: { display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "1rem", marginBottom: "1.25rem" },
  statCard: {
    background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)",
    borderRadius: "16px", padding: "1.25rem", display: "flex", alignItems: "flex-start",
    gap: "1rem", position: "relative", overflow: "hidden",
    transition: "border-color 0.2s",
  },
  statIcon:  { width: "40px", height: "40px", borderRadius: "10px", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 },
  statLabel: { color: "#6b7280", fontSize: "0.75rem", fontWeight: 500, marginBottom: "0.25rem", textTransform: "uppercase", letterSpacing: "0.05em" },
  statValue: { fontSize: "1.75rem", fontWeight: 700, lineHeight: 1 },
  statSub:   { color: "#4b5563", fontSize: "0.7rem", marginTop: "0.3rem" },
  alertDot:  { position: "absolute", top: "0.875rem", right: "0.875rem", width: "8px", height: "8px", borderRadius: "50%", background: "#ef4444", boxShadow: "0 0 6px #ef4444" },

  /* Charts row */
  chartsRow: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginBottom: "1.25rem" },
  panel: {
    background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)",
    borderRadius: "16px", padding: "1.25rem",
  },
  panelHeader: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "1rem" },
  panelTitle:  { color: "#e2e8f0", fontSize: "0.875rem", fontWeight: 600 },
  panelSub:    { color: "#4b5563", fontSize: "0.75rem" },
  emptyMsg:    { color: "#4b5563", fontSize: "0.8rem", textAlign: "center", padding: "2rem 0" },

  /* Spark bars */
  sparkWrap: { display: "flex", alignItems: "flex-end", gap: "4px", height: "80px", paddingBottom: "1.5rem", position: "relative" },
  sparkBarCol: { display: "flex", flexDirection: "column", alignItems: "center", flex: 1, height: "100%" },
  sparkBar:    { width: "100%", background: "linear-gradient(180deg, #6366f1, #4338ca)", borderRadius: "3px 3px 0 0", marginTop: "auto", minHeight: "3px" },
  sparkLabel:  { color: "#4b5563", fontSize: "0.6rem", marginTop: "4px", whiteSpace: "nowrap" },

  /* Status bars */
  statusList: { display: "flex", flexDirection: "column", gap: "0.875rem" },
  statusRow:  { display: "flex", flexDirection: "column", gap: "0.375rem" },
  statusLabelRow: { display: "flex", alignItems: "center", gap: "0.5rem" },
  statusDot:  { width: "8px", height: "8px", borderRadius: "50%", flexShrink: 0 },
  statusName: { color: "#94a3b8", fontSize: "0.8rem", flex: 1, textTransform: "capitalize" },
  statusCount:{ color: "#f1f5f9", fontSize: "0.8rem", fontWeight: 600 },
  barBg:      { width: "100%", height: "6px", background: "rgba(255,255,255,0.06)", borderRadius: "999px", overflow: "hidden" },
  barFill:    { height: "100%", borderRadius: "999px", transition: "width 0.6s ease" },

  /* Table */
  tableWrap: { overflowX: "auto" },
  table:     { width: "100%", borderCollapse: "collapse" },
  th: {
    padding: "0.625rem 0.875rem", textAlign: "left",
    color: "#4b5563", fontSize: "0.7rem", fontWeight: 600,
    textTransform: "uppercase", letterSpacing: "0.06em",
    borderBottom: "1px solid rgba(255,255,255,0.06)",
  },
  tr:        { borderBottom: "1px solid rgba(255,255,255,0.04)" },
  td:        { padding: "0.75rem 0.875rem", fontSize: "0.825rem" },
  quotaRow:  { display: "flex", alignItems: "center", gap: "0.625rem" },
  quotaPct:  { fontSize: "0.75rem", fontWeight: 600, minWidth: "40px" },
};
