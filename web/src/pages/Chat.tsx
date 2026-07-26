import { useState } from "react";
import { api } from "../api/client";

interface StreamEvent {
  task?: { status?: string; result?: { summary?: string } };
  error?: string;
}

export default function Chat() {
  const [message, setMessage] = useState("");
  const [log, setLog] = useState<string[]>([]);
  const [sending, setSending] = useState(false);

  async function send() {
    if (!message.trim()) return;
    setSending(true);
    setLog((l) => [...l, `you: ${message}`]);
    try {
      const { task_id } = await api.chat("ORCH-0", message);
      setMessage("");
      watchTask(task_id);
    } catch (e) {
      setLog((l) => [...l, `error: ${e instanceof Error ? e.message : "failed"}`]);
    } finally {
      setSending(false);
    }
  }

  function watchTask(taskId: string) {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/stream?task_id=${taskId}`);
    ws.onmessage = (ev) => {
      const data: StreamEvent = JSON.parse(ev.data);
      if (data.error) {
        setLog((l) => [...l, `error: ${data.error}`]);
        return;
      }
      const status = data.task?.status;
      const summary = data.task?.result?.summary;
      setLog((l) => [...l, `orch0 [${status ?? "unknown"}]: ${summary ?? "…"}`]);
    };
    ws.onerror = () => setLog((l) => [...l, "error: stream connection failed"]);
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-2 overflow-y-auto rounded border border-slate-200 bg-white p-4">
        {log.length === 0 && <p className="text-sm text-slate-400">Say hello to ORCH-0.</p>}
        {log.map((line, i) => (
          <p key={i} className="text-sm text-slate-800">
            {line}
          </p>
        ))}
      </div>
      <div className="mt-3 flex gap-2">
        <input
          className="flex-1 rounded border border-slate-300 p-2 text-sm"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Type a message…"
        />
        <button
          className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          onClick={send}
          disabled={sending}
        >
          Send
        </button>
      </div>
    </div>
  );
}
