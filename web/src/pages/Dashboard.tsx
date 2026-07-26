import { useEffect, useState } from "react";
import { api, ApiError, type DashboardItem } from "../api/client";

const ROLES = ["ceo", "director", "manager", "admin_head", "hr_head", "finance_head", "support_lead"];

export default function Dashboard() {
  const [role, setRole] = useState("director");
  const [items, setItems] = useState<DashboardItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const { items } = await api.getDashboard(role);
      setItems(items);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "failed to load dashboard");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role]);

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-base font-semibold text-slate-900">Dashboard</h2>
        <select
          className="rounded border border-slate-300 p-1.5 text-sm"
          value={role}
          onChange={(e) => setRole(e.target.value)}
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </div>

      {loading && <p className="text-sm text-slate-500">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="space-y-2">
        {items.map((item) => (
          <div key={item.id} className="rounded border border-slate-200 bg-white p-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-slate-900">{item.title}</span>
              <span className="text-xs uppercase text-slate-400">{item.panel}</span>
            </div>
            <p className="mt-1 text-sm text-slate-600">{item.body}</p>
          </div>
        ))}
      </div>
      {!loading && items.length === 0 && (
        <p className="mt-3 text-sm text-slate-400">No dashboard items for this role right now.</p>
      )}
    </div>
  );
}
