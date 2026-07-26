import { useEffect, useState } from "react";
import { api, type Approval } from "../api/client";

export default function Approvals() {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const { approvals } = await api.approvalsInbox();
      setApprovals(approvals);
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load approvals");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function approve(id: string) {
    setBusyId(id);
    try {
      await api.approve(id, "");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "approve failed");
    } finally {
      setBusyId(null);
    }
  }

  async function reject(id: string) {
    const reason = window.prompt("Reason for rejecting?");
    if (!reason) return;
    setBusyId(id);
    try {
      await api.reject(id, reason);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "reject failed");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <h2 className="mb-3 text-base font-semibold text-slate-900">Approvals inbox</h2>
      {loading && <p className="text-sm text-slate-500">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}
      {!loading && approvals.length === 0 && (
        <p className="text-sm text-slate-400">Nothing pending for your role.</p>
      )}
      <div className="space-y-3">
        {approvals.map((a) => (
          <div key={a.id} className="rounded border border-slate-200 bg-white p-4">
            <div className="mb-1 flex items-center justify-between">
              <span className="font-medium text-slate-900">{a.gate}</span>
              <span className="text-xs text-slate-400">
                {a.approvals_received.length}/{a.n_required} votes
              </span>
            </div>
            <p className="mb-2 text-xs text-slate-500">requested by {a.requested_by}</p>
            <pre className="mb-3 overflow-x-auto rounded bg-slate-50 p-2 text-xs">
              {JSON.stringify(a.payload, null, 2)}
            </pre>
            <div className="flex gap-2">
              <button
                className="rounded bg-green-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
                onClick={() => approve(a.id)}
                disabled={busyId === a.id}
              >
                Approve
              </button>
              <button
                className="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
                onClick={() => reject(a.id)}
                disabled={busyId === a.id}
              >
                Reject
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
