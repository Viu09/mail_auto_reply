"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, clearToken, getToken } from "@/lib/api";
import { AccountSummary, Email } from "@/lib/types";
import EmailDetail from "@/components/EmailDetail";
import { PriorityBadge, StatusBadge, timeAgo } from "@/components/ui";

const STATUSES = [
  { key: "pending", label: "En attente" },
  { key: "sent", label: "Envoyés" },
  { key: "rejected", label: "Refusés" },
] as const;

export default function InboxPage() {
  const router = useRouter();
  const [accounts, setAccounts] = useState<AccountSummary[]>([]);
  const [emails, setEmails] = useState<Email[]>([]);
  const [account, setAccount] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("pending");
  const [selected, setSelected] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  const refreshAccounts = useCallback(async () => {
    try {
      setAccounts(await api.accounts());
    } catch {
      /* auth redirect handled in api */
    }
  }, []);

  const refreshEmails = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = { status };
      if (account) params.account = account;
      const list = await api.listEmails(params);
      setEmails(list);
      if (list.length && !list.some((e) => e.id === selected)) {
        setSelected(list[0].id);
      }
      if (!list.length) setSelected(null);
    } finally {
      setLoading(false);
    }
  }, [account, status, selected]);

  useEffect(() => {
    refreshAccounts();
  }, [refreshAccounts]);

  useEffect(() => {
    refreshEmails();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account, status]);

  // Rafraichissement periodique de la liste + compteurs
  useEffect(() => {
    const id = setInterval(() => {
      refreshAccounts();
      refreshEmails();
    }, 20000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account, status]);

  const onChanged = useCallback(() => {
    refreshAccounts();
    refreshEmails();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshAccounts, refreshEmails]);

  function logout() {
    clearToken();
    router.replace("/login");
  }

  return (
    <div className="flex h-screen">
      {/* Colonne comptes */}
      <aside className="flex w-60 shrink-0 flex-col border-r border-ink-800 bg-ink-900">
        <div className="flex items-center justify-between px-4 py-4">
          <span className="text-sm font-semibold text-white">Assistant Mail IA</span>
          <button onClick={logout} title="Déconnexion" className="text-xs text-slate-500 hover:text-slate-300">
            Quitter
          </button>
        </div>

        <div className="px-3">
          <AccountItem
            label="Tous les comptes"
            count={accounts.reduce((s, a) => s + a.pending, 0)}
            active={account === null}
            onClick={() => setAccount(null)}
          />
          {accounts.map((a) => (
            <AccountItem
              key={a.account_id}
              label={a.label}
              count={a.pending}
              active={account === a.account_id}
              onClick={() => setAccount(a.account_id)}
            />
          ))}
        </div>

        <div className="mt-4 border-t border-ink-800 px-3 pt-3">
          {STATUSES.map((s) => (
            <button
              key={s.key}
              onClick={() => setStatus(s.key)}
              className={`mb-1 block w-full rounded-lg px-3 py-2 text-left text-sm transition ${
                status === s.key ? "bg-ink-700 text-white" : "text-slate-400 hover:bg-ink-800"
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>
      </aside>

      {/* Colonne liste */}
      <section className="flex w-96 shrink-0 flex-col border-r border-ink-800 bg-ink-950">
        <div className="flex items-center justify-between px-4 py-3 text-xs text-slate-500">
          <span>{emails.length} email(s)</span>
          {loading && <span>maj…</span>}
        </div>
        <div className="flex-1 overflow-y-auto">
          {emails.map((e) => {
            const label = accounts.find((a) => a.account_id === e.account_id)?.label || e.account_id;
            return (
              <button
                key={e.id}
                onClick={() => setSelected(e.id)}
                className={`block w-full border-b border-ink-800 px-4 py-3 text-left transition ${
                  selected === e.id ? "bg-ink-800" : "hover:bg-ink-900"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium text-slate-100">{e.sender}</span>
                  <PriorityBadge priority={e.priority} />
                </div>
                <div className="mt-0.5 truncate text-sm text-slate-400">{e.subject || "(sans objet)"}</div>
                <div className="mt-1 flex items-center gap-2 text-[11px] text-slate-500">
                  <span className="rounded bg-ink-800 px-1.5 py-0.5 text-slate-400">{label}</span>
                  <span>{e.category}</span>
                  <span className="ml-auto">{timeAgo(e.created_at)}</span>
                </div>
              </button>
            );
          })}
          {!emails.length && !loading && (
            <div className="px-4 py-10 text-center text-sm text-slate-600">Rien à afficher ici.</div>
          )}
        </div>
      </section>

      {/* Colonne detail */}
      <main className="flex-1 bg-ink-900">
        <EmailDetail emailId={selected} onChanged={onChanged} />
      </main>
    </div>
  );
}

function AccountItem({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`mb-1 flex w-full items-center justify-between rounded-lg px-3 py-2 text-sm transition ${
        active ? "bg-indigo-600/20 text-indigo-200" : "text-slate-300 hover:bg-ink-800"
      }`}
    >
      <span className="truncate">{label}</span>
      {count > 0 && (
        <span className="ml-2 rounded-full bg-indigo-500/20 px-2 py-0.5 text-[11px] text-indigo-200">{count}</span>
      )}
    </button>
  );
}
