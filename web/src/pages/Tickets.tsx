import { useEffect, useState } from "react";
import { api, ApiError, type Ticket } from "../api/client";

export default function Tickets() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const { tickets } = await api.listTickets();
      setTickets(tickets);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "failed to load tickets");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-base font-semibold text-slate-900">Tickets</h2>
        <button
          className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white"
          onClick={() => setShowNew((v) => !v)}
        >
          {showNew ? "Cancel" : "New ticket"}
        </button>
      </div>

      {showNew && (
        <NewTicketForm
          onCreated={() => {
            setShowNew(false);
            load();
          }}
        />
      )}

      {loading && <p className="text-sm text-slate-500">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-slate-500">
            <th className="py-2">ID</th>
            <th>Category</th>
            <th>Priority</th>
            <th>Status</th>
            <th>Summary</th>
          </tr>
        </thead>
        <tbody>
          {tickets.map((t) => (
            <tr key={t.ticket_id} className="border-b border-slate-100">
              <td className="py-2 font-mono text-xs">{t.ticket_id}</td>
              <td>{t.category}</td>
              <td>{t.priority}</td>
              <td>{t.status}</td>
              <td className="max-w-xs truncate">{t.summary_current}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!loading && tickets.length === 0 && (
        <p className="mt-3 text-sm text-slate-400">No tickets visible to your role.</p>
      )}
    </div>
  );
}

function NewTicketForm({ onCreated }: { onCreated: () => void }) {
  const [category, setCategory] = useState("it_support");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      await api.createTicket({ channel: "dashboard", category, subject, body });
      setSubject("");
      setBody("");
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to create ticket");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mb-4 space-y-2 rounded border border-slate-200 bg-white p-4">
      <select
        className="w-full rounded border border-slate-300 p-2 text-sm"
        value={category}
        onChange={(e) => setCategory(e.target.value)}
      >
        {["device", "access", "facilities", "records", "hr", "it_support", "procurement"].map(
          (c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ),
        )}
      </select>
      <input
        className="w-full rounded border border-slate-300 p-2 text-sm"
        placeholder="Subject"
        value={subject}
        onChange={(e) => setSubject(e.target.value)}
      />
      <textarea
        className="w-full rounded border border-slate-300 p-2 text-sm"
        placeholder="Description"
        value={body}
        onChange={(e) => setBody(e.target.value)}
      />
      <button
        className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        onClick={submit}
        disabled={submitting || !subject || !body}
      >
        Create
      </button>
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}
