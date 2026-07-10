import { AccountSummary, Email, Rule } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const TOKEN_KEY = "mail_dashboard_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  window.localStorage.removeItem(TOKEN_KEY);
}

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(`${API_URL}${path}`, { ...options, headers });

  if (res.status === 401) {
    clearToken();
    if (typeof window !== "undefined" && !path.startsWith("/auth/login")) {
      window.location.href = "/login";
    }
    throw new ApiError(401, "Session expiree");
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  apiUrl: API_URL,

  async login(email: string, password: string): Promise<{ token: string; email: string }> {
    return request("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  },

  accounts(): Promise<AccountSummary[]> {
    return request("/accounts");
  },

  listEmails(params: Record<string, string>): Promise<Email[]> {
    const query = new URLSearchParams(params).toString();
    return request(`/emails${query ? `?${query}` : ""}`);
  },

  getEmail(id: number): Promise<Email> {
    return request(`/emails/${id}`);
  },

  updateReply(id: number, reply: string): Promise<Email> {
    return request(`/emails/${id}/reply`, { method: "PATCH", body: JSON.stringify({ reply }) });
  },

  refine(id: number, instructions: string): Promise<Email> {
    return request(`/emails/${id}/refine`, { method: "POST", body: JSON.stringify({ instructions }) });
  },

  send(id: number): Promise<Email> {
    return request(`/emails/${id}/send`, { method: "POST" });
  },

  reject(id: number): Promise<Email> {
    return request(`/emails/${id}/reject`, { method: "POST" });
  },

  markRead(id: number): Promise<Email> {
    return request(`/emails/${id}/mark_read`, { method: "POST" });
  },

  uploadAttachment(id: number, file: File): Promise<unknown> {
    const form = new FormData();
    form.append("file", file);
    return request(`/emails/${id}/attachments`, { method: "POST", body: form });
  },

  rules(): Promise<Rule[]> {
    return request("/rules");
  },
};
