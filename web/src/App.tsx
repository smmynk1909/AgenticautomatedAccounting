import { useState } from "react";
import { clearToken, getToken } from "./api/client";
import Approvals from "./pages/Approvals";
import Chat from "./pages/Chat";
import Dashboard from "./pages/Dashboard";
import DevLogin from "./pages/DevLogin";
import Tickets from "./pages/Tickets";

type Tab = "chat" | "tickets" | "approvals" | "dashboard";

const TABS: { id: Tab; label: string }[] = [
  { id: "chat", label: "Chat" },
  { id: "tickets", label: "Tickets" },
  { id: "approvals", label: "Approvals" },
  { id: "dashboard", label: "Dashboard" },
];

export default function App() {
  const [loggedIn, setLoggedIn] = useState(() => getToken() !== null);
  const [tab, setTab] = useState<Tab>("chat");

  if (!loggedIn) {
    return <DevLogin onLoggedIn={() => setLoggedIn(true)} />;
  }

  return (
    <div className="flex h-screen flex-col bg-slate-50">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
        <h1 className="text-sm font-semibold text-slate-900">AWP</h1>
        <nav className="flex gap-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`rounded px-3 py-1.5 text-sm font-medium ${
                tab === t.id ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"
              }`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <button
          className="text-sm text-slate-500 hover:text-slate-900"
          onClick={() => {
            clearToken();
            setLoggedIn(false);
          }}
        >
          Log out
        </button>
      </header>
      <main className="flex-1 overflow-y-auto p-4">
        {tab === "chat" && <Chat />}
        {tab === "tickets" && <Tickets />}
        {tab === "approvals" && <Approvals />}
        {tab === "dashboard" && <Dashboard />}
      </main>
    </div>
  );
}
