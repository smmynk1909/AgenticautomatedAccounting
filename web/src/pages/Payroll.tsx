import { useEffect, useState } from "react";
import { api, ApiError, type PayrollRun } from "../api/client";

function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

export default function Payroll() {
  const [month, setMonth] = useState(currentMonth());
  const [run, setRun] = useState<PayrollRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setRun(await api.getPayrollRun(month));
    } catch (e) {
      setRun(null);
      setError(e instanceof ApiError ? e.message : "failed to load payroll run");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [month]);

  const lines = run?.register?.lines ?? [];
  const totals = run?.register?.totals;

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-base font-semibold text-slate-900">Payroll</h2>
        <input
          type="month"
          className="rounded border border-slate-300 p-1.5 text-sm"
          value={month}
          onChange={(e) => setMonth(e.target.value)}
        />
      </div>

      {loading && <p className="text-sm text-slate-500">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {run && (
        <p className="mb-3 text-sm text-slate-500">
          Status: <span className="font-medium text-slate-800">{run.status}</span>
        </p>
      )}

      {lines.length > 0 && (
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-slate-500">
              <th className="py-2">Employee</th>
              <th>Gross</th>
              <th>TDS</th>
              <th>Net</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((line) => (
              <tr key={line.emp_id} className="border-b border-slate-100">
                <td className="py-2 font-mono text-xs">{line.emp_id}</td>
                <td>{line.gross}</td>
                <td>{line.deductions.tds ?? "0"}</td>
                <td className="font-medium">{line.net}</td>
              </tr>
            ))}
          </tbody>
          {totals && (
            <tfoot>
              <tr className="border-t border-slate-300 font-semibold">
                <td className="py-2">Total</td>
                <td>{totals.gross}</td>
                <td>{totals.tds}</td>
                <td>{totals.net}</td>
              </tr>
            </tfoot>
          )}
        </table>
      )}
      {!loading && !error && lines.length === 0 && (
        <p className="mt-3 text-sm text-slate-400">
          No computed payroll register for {month} yet.
        </p>
      )}
    </div>
  );
}
