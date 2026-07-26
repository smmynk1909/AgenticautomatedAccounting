// Thin fetch wrapper for the gateway API (doc 11 §5). Dev-mode auth per
// DEVIATIONS.md #2: token comes from POST /api/dev/login, stored in
// localStorage, sent as a bearer token on every request.

const TOKEN_KEY = "awp_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> | undefined),
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(path, { ...options, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const err = (body as { error?: { code?: string; message?: string } })?.error ?? {};
    throw new ApiError(res.status, err.code ?? "UNKNOWN", err.message ?? res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export interface Ticket {
  ticket_id: string;
  category: string;
  subcategory: string | null;
  priority: string;
  status: string;
  summary_current: string;
  assignee_id: string | null;
}

export interface DashboardItem {
  id: string;
  panel: string;
  severity: string;
  title: string;
  body: string;
  action_link: string | null;
}

export interface PayrollLine {
  emp_id: string;
  earnings: Record<string, string>;
  deductions: Record<string, string>;
  gross: string;
  net: string;
}

export interface PayrollRun {
  register_id?: string;
  month: string;
  status: string;
  register: { lines: PayrollLine[]; totals: Record<string, string> } | null;
}

export interface Approval {
  id: string;
  gate: string;
  status: string;
  requested_by: string;
  approver_roles: string[];
  n_required: number;
  approvals_received: { user_id: string; ts: string; comment: string }[];
  payload: Record<string, unknown>;
}

export const api = {
  devLogin: (userId: string) =>
    request<{ token: string }>("/api/dev/login", {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    }),

  chat: (agentId: string, message: string) =>
    request<{ task_id: string }>(`/api/chat/${agentId}`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),

  getTask: (taskId: string) => request<Record<string, unknown>>(`/api/tasks/${taskId}`),

  listTickets: (params: Record<string, string> = {}) => {
    const qs = new URLSearchParams(params).toString();
    return request<{ tickets: Ticket[] }>(`/api/tickets${qs ? `?${qs}` : ""}`);
  },

  createTicket: (payload: Record<string, unknown>) =>
    request<Ticket>("/api/tickets", { method: "POST", body: JSON.stringify(payload) }),

  getDashboard: (role: string) =>
    request<{ items: DashboardItem[] }>(`/api/dashboard/${role}`),

  getPayrollRun: (month: string) => request<PayrollRun>(`/api/payroll/runs/${month}`),

  approvalsInbox: () => request<{ approvals: Approval[] }>("/api/approvals/inbox"),

  approve: (id: string, comment: string) =>
    request<Record<string, unknown>>(`/api/approvals/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ comment }),
    }),

  reject: (id: string, reason: string) =>
    request<Record<string, unknown>>(`/api/approvals/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
};
