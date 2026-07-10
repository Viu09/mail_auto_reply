import { Email } from "@/lib/types";

export function PriorityBadge({ priority }: { priority: Email["priority"] }) {
  const map: Record<string, string> = {
    high: "bg-rose-500/15 text-rose-300 border-rose-500/30",
    medium: "bg-amber-500/15 text-amber-300 border-amber-500/30",
    low: "bg-slate-500/15 text-slate-300 border-slate-500/30",
  };
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${map[priority] || map.low}`}>
      {priority}
    </span>
  );
}

export function StatusBadge({ status }: { status: Email["approval_status"] }) {
  const map: Record<string, string> = {
    pending: "bg-indigo-500/15 text-indigo-300 border-indigo-500/30",
    sent: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
    rejected: "bg-slate-600/20 text-slate-400 border-slate-600/40",
  };
  const label: Record<string, string> = { pending: "En attente", sent: "Envoyé", rejected: "Refusé" };
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${map[status]}`}>
      {label[status]}
    </span>
  );
}

export function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-md border border-ink-700 bg-ink-800 px-2 py-0.5 text-[11px] text-slate-300">
      {children}
    </span>
  );
}

export function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "à l'instant";
  if (mins < 60) return `il y a ${mins} min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `il y a ${hours} h`;
  const days = Math.floor(hours / 24);
  return `il y a ${days} j`;
}
