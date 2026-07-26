import { useState } from "react";
import { api, setToken } from "../api/client";

// config/dev_users.yaml — DEVIATIONS.md #2, no password.
const DEV_USERS = [
  "dev-ceo",
  "dev-director",
  "dev-finance-head",
  "dev-hr-head",
  "dev-admin-head",
  "dev-support-lead",
  "dev-manager",
  "dev-recruiter",
  "dev-employee",
];

export default function DevLogin({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [userId, setUserId] = useState(DEV_USERS[0]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function login() {
    setLoading(true);
    setError(null);
    try {
      const { token } = await api.devLogin(userId);
      setToken(token);
      onLoggedIn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50">
      <div className="w-80 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="mb-1 text-lg font-semibold text-slate-900">AWP — Dev Login</h1>
        <p className="mb-4 text-sm text-slate-500">No password (DEVIATIONS.md #2).</p>
        <select
          className="mb-3 w-full rounded border border-slate-300 p-2 text-sm"
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
        >
          {DEV_USERS.map((u) => (
            <option key={u} value={u}>
              {u}
            </option>
          ))}
        </select>
        <button
          className="w-full rounded bg-slate-900 py-2 text-sm font-medium text-white disabled:opacity-50"
          onClick={login}
          disabled={loading}
        >
          {loading ? "Logging in…" : "Log in"}
        </button>
        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      </div>
    </div>
  );
}
