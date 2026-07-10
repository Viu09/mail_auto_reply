import { Email } from "@/lib/types";

export function PriorityBadge({ priority }: { priority: Email["priority"] }) {
  const map: Record<string, string> = {
    high: "bg-rose-500/15 text-rose-300 ring-rose-500/25",
    medium: "bg-amber-500/15 text-amber-300 ring-amber-500/25",
    low: "bg-slate-500/10 text-slate-400 ring-slate-500/20",
  };
  const label: Record<string, string> = { high: "Haute", medium: "Moyenne", low: "Basse" };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ${map[priority] || map.low}`}>
      {label[priority] || priority}
    </span>
  );
}

export function StatusBadge({ status }: { status: Email["approval_status"] }) {
  const map: Record<string, string> = {
    pending: "bg-brand-faint text-brand-soft ring-brand/25",
    sent: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/25",
    rejected: "bg-slate-600/15 text-slate-400 ring-slate-600/30",
  };
  const label: Record<string, string> = { pending: "En attente", sent: "Envoyé", rejected: "Refusé" };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ${map[status]}`}>
      {label[status]}
    </span>
  );
}

export function NewBadge() {
  return (
    <span className="inline-flex items-center rounded-full bg-brand px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white">
      Nouveau
    </span>
  );
}

export function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-md border border-line bg-raised px-2 py-0.5 text-[11px] text-slate-300">
      {children}
    </span>
  );
}

export function Avatar({ sender }: { sender: string }) {
  const name = sender.replace(/<.*>/, "").replace(/"/g, "").trim() || sender;
  const initial = (name[0] || "?").toUpperCase();
  const hue = Array.from(name).reduce((a, c) => a + c.charCodeAt(0), 0) % 360;
  return (
    <div
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-semibold text-white"
      style={{ backgroundColor: `hsl(${hue} 45% 40%)` }}
    >
      {initial}
    </div>
  );
}

export function senderName(sender: string): string {
  return sender.replace(/<.*>/, "").replace(/"/g, "").trim() || sender;
}

// Date reelle de reception (fallback sur created_at).
export function emailDate(e: Email): Date {
  return new Date(e.received_at || e.created_at);
}

export function isNew(e: Email): boolean {
  return Date.now() - emailDate(e).getTime() < 24 * 3600 * 1000;
}

export function timeAgo(date: Date): string {
  const diff = Date.now() - date.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "à l'instant";
  if (mins < 60) return `${mins} min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} h`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} j`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months} mois`;
  return `${Math.floor(months / 12)} an${months >= 24 ? "s" : ""}`;
}

// Libellé de groupe pour la liste (Nouveaux / Aujourd'hui / etc.).
export function dateGroup(date: Date): string {
  const diff = Date.now() - date.getTime();
  const day = 24 * 3600 * 1000;
  if (diff < day) return "Nouveaux (24 h)";
  if (diff < 7 * day) return "7 derniers jours";
  if (diff < 30 * day) return "30 derniers jours";
  return "Plus ancien";
}

export function fullDate(date: Date): string {
  return date.toLocaleString("fr-FR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
