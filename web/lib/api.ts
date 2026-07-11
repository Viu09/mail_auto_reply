import {
  AccountSummary,
  Analytics,
  CategoryCount,
  Document,
  Email,
  IngestStatus,
  Rule,
  SenderFilter,
  Template,
} from "./types";
import { toastErr } from "./toast";

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

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...options, headers });
  } catch {
    toastErr("Connexion au serveur impossible. Réessaie dans un instant.");
    throw new ApiError(0, "Connexion impossible");
  }

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
    // Filet de sécurité : les erreurs serveur sont toujours signalées.
    if (res.status >= 500) toastErr(detail || "Erreur serveur.");
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

  oauthStatus(): Promise<{ configured: boolean; redirect_uri: string }> {
    return request("/accounts/oauth/status");
  },

  oauthStart(): Promise<{ auth_url: string }> {
    return request("/accounts/oauth/start");
  },

  deleteAccount(id: string): Promise<{ ok: boolean }> {
    return request(`/accounts/${encodeURIComponent(id)}`, { method: "DELETE" });
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

  deleteEmail(id: number): Promise<{ ok: boolean }> {
    return request(`/emails/${id}`, { method: "DELETE" });
  },

  bulkDeleteEmails(ids: number[]): Promise<{ deleted: number; requested: number }> {
    return request("/emails/bulk_delete", { method: "POST", body: JSON.stringify({ ids }) });
  },

  bulkSendEmails(ids: number[]): Promise<{ sent: number; requested: number }> {
    return request("/emails/bulk_send", { method: "POST", body: JSON.stringify({ ids }) });
  },

  bulkRejectEmails(ids: number[]): Promise<{ rejected: number; requested: number }> {
    return request("/emails/bulk_reject", { method: "POST", body: JSON.stringify({ ids }) });
  },

  uploadAttachment(id: number, file: File): Promise<unknown> {
    const form = new FormData();
    form.append("file", file);
    return request(`/emails/${id}/attachments`, { method: "POST", body: form });
  },

  // ------- catégories emails
  categories(params: Record<string, string> = {}): Promise<CategoryCount[]> {
    const query = new URLSearchParams(params).toString();
    return request(`/categories${query ? `?${query}` : ""}`);
  },

  renameCategory(from_name: string, to_name: string): Promise<{ updated: number }> {
    return request("/categories/rename", { method: "POST", body: JSON.stringify({ from_name, to_name }) });
  },

  recategorizeStatus(): Promise<{ remaining: number }> {
    return request("/categories/recategorize");
  },

  recategorize(): Promise<{ updated: number; remaining: number }> {
    return request("/categories/recategorize", { method: "POST" });
  },

  // ------- documents
  listDocuments(params: Record<string, string> = {}): Promise<Document[]> {
    const query = new URLSearchParams(params).toString();
    return request(`/documents${query ? `?${query}` : ""}`);
  },

  documentCategories(params: Record<string, string> = {}): Promise<CategoryCount[]> {
    const query = new URLSearchParams(params).toString();
    return request(`/documents/categories${query ? `?${query}` : ""}`);
  },

  renameDocumentCategory(from_name: string, to_name: string): Promise<{ updated: number }> {
    return request("/documents/categories/rename", {
      method: "POST",
      body: JSON.stringify({ from_name, to_name }),
    });
  },

  summarizeDocument(id: number): Promise<Document> {
    return request(`/documents/${id}/summary`, { method: "POST" });
  },

  deleteDocument(id: number): Promise<{ ok: boolean }> {
    return request(`/documents/${id}`, { method: "DELETE" });
  },

  // URL de téléchargement natif (token en query pour les liens <a href>)
  documentDownloadUrl(id: number): string {
    const token = getToken() || "";
    return `${API_URL}/documents/${id}/download?token=${encodeURIComponent(token)}`;
  },

  incomingAttachmentUrl(emailId: number, name: string): string {
    const token = getToken() || "";
    return `${API_URL}/emails/${emailId}/incoming/${encodeURIComponent(name)}?token=${encodeURIComponent(token)}`;
  },

  // ------- comptes
  updateAccount(id: string, fields: Partial<AccountSummary>): Promise<AccountSummary> {
    return request(`/accounts/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(fields),
    });
  },

  // ------- statut & analytics
  ingestStatus(): Promise<IngestStatus> {
    return request("/status");
  },

  analytics(account?: string): Promise<Analytics> {
    return request(`/analytics${account ? `?account=${encodeURIComponent(account)}` : ""}`);
  },

  // ------- règles d'automatisation
  rules(): Promise<Rule[]> {
    return request("/rules");
  },

  createRule(payload: Partial<Rule>): Promise<Rule> {
    return request("/rules", { method: "POST", body: JSON.stringify(payload) });
  },

  updateRule(id: number, payload: Partial<Rule>): Promise<Rule> {
    return request(`/rules/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
  },

  deleteRule(id: number): Promise<{ ok: boolean }> {
    return request(`/rules/${id}`, { method: "DELETE" });
  },

  // ------- filtres expéditeur
  senderFilters(): Promise<SenderFilter[]> {
    return request("/sender_filters");
  },

  createSenderFilter(payload: Partial<SenderFilter>): Promise<SenderFilter> {
    return request("/sender_filters", { method: "POST", body: JSON.stringify(payload) });
  },

  deleteSenderFilter(id: number): Promise<{ ok: boolean }> {
    return request(`/sender_filters/${id}`, { method: "DELETE" });
  },

  // ------- modèles de réponse
  templates(): Promise<Template[]> {
    return request("/templates");
  },

  createTemplate(payload: Partial<Template>): Promise<Template> {
    return request("/templates", { method: "POST", body: JSON.stringify(payload) });
  },

  updateTemplate(id: number, payload: Partial<Template>): Promise<Template> {
    return request(`/templates/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
  },

  deleteTemplate(id: number): Promise<{ ok: boolean }> {
    return request(`/templates/${id}`, { method: "DELETE" });
  },
};
