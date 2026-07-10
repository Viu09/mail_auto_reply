"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api, clearToken, getToken } from "@/lib/api";
import { AccountSummary, Email } from "@/lib/types";
import EmailDetail from "@/components/EmailDetail";
import {
  Avatar,
  NewBadge,
  PriorityBadge,
  SkeletonRow,
  dateGroup,
  emailDate,
  isNew,
  senderName,
  timeAgo,
} from "@/components/ui";
import { IconInbox, IconLogout, IconMail, IconRefresh, IconSend, IconX } from "@/components/icons";

const STATUSES = [
  { key: "pending", label: "En attente", Icon: IconInbox },
  { key: "sent", label: "Envoyés", Icon: IconSend },
  { key: "rejected", label: "Refusés", Icon: IconX },
] as const;

export default function InboxPage() {
  const router = useRouter();
  const [accounts, setAccounts] = useState<AccountSummary[]>([]);
  const [emails, setEmails] = useState<Email[]>([]);
  const [account, setAccount] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("pending");
  const [selected, setSelected] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  const refreshAccounts = useCallback(async () => {
    try {
      setAccounts(await api.accounts());
    } catch {
      /* redirect handled in api client */
    }
  }, []);

  const refreshEmails = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = { status, limit: "300" };
      if (account) params.account = account;
      setEmails(await api.listEmails(params));
    } finally {
      setLoading(false);
    }
  }, [account, status]);

  useEffect(() => {
    refreshAccounts();
  }, [refreshAccounts]);

  useEffect(() => {
    refreshEmails();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account, status]);

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
  }, [refreshAccounts, refreshEmails]);

  function logout() {
    clearToken();
    router.replace("/login");
  }

  const totalPending = accounts.reduce((s, a) => s + a.pending, 0);
  const accountLabel = (id: string) => accounts.find((a) => a.account_id === id)?.label || id;

  const groups = useMemo(() => {
    const out: { label: string; items: Email[] }[] = [];
    for (const e of emails) {
      const g = dateGroup(emailDate(e));
      const last = out[out.length - 1];
      if (last && last.label === g) last.items.push(e);
      else out.push({ label: g, items: [e] });
    }
    return out;
  }, [emails]);

  const showSkeleton = loading && emails.length === 0;

  return (
    <div className="flex h-[100dvh] flex-col overflow-hidden lg:flex-row">
      {/* Barre mobile */}
      <header className="flex items-center gap-2 border-b border-line bg-surface px-3 py-2.5 lg:hidden">
        <LogoMark />
        <span className="text-sm font-semibold text-white">Assistant Mail IA</span>
        <select
          value={account ?? ""}
          onChange={(e) => setAccount(e.target.value || null)}
          className="ml-auto rounded-lg border border-line bg-canvas px-2 py-1 text-xs text-slate-200"
        >
          <option value="">Tous les comptes</option>
          {accounts.map((a) => (
            <option key={a.account_id} value={a.account_id}>
              {a.label} ({a.pending})
            </option>
          ))}
        </select>
        <button onClick={logout} className="rounded-md p-1.5 text-slate-500 hover:bg-raised" aria-label="Quitter">
          <IconLogout className="h-4 w-4" />
        </button>
      </header>
      <div className="flex items-center gap-1.5 overflow-x-auto border-b border-line bg-surface px-3 py-2 lg:hidden">
        {STATUSES.map((s) => (
          <button
            key={s.key}
            onClick={() => setStatus(s.key)}
            className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-xs transition ${
              status === s.key ? "bg-brand text-white" : "bg-raised text-slate-400"
            }`}
          >
            <s.Icon className="h-3.5 w-3.5" />
            {s.label}
          </button>
        ))}
      </div>

      {/* Sidebar desktop */}
      <aside className="hidden w-64 shrink-0 flex-col border-r border-line bg-surface lg:flex">
        <div className="flex items-center gap-2.5 px-5 py-4">
          <LogoMark />
          <span className="text-[15px] font-semibold text-white">Assistant Mail IA</span>
          <button onClick={logout} title="Déconnexion" className="ml-auto rounded-md p-1.5 text-slate-500 hover:bg-raised hover:text-slate-300">
            <IconLogout className="h-4 w-4" />
          </button>
        </div>

        <div className="px-3">
          <p className="px-2 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-600">Comptes</p>
          <AccountItem label="Tous les comptes" count={totalPending} active={account === null} onClick={() => setAccount(null)} />
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

        <div className="mt-6 px-3">
          <p className="px-2 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-600">Statut</p>
          {STATUSES.map((s) => (
            <button
              key={s.key}
              onClick={() => setStatus(s.key)}
              className={`mb-0.5 flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm transition ${
                status === s.key ? "bg-raised text-white" : "text-slate-400 hover:bg-raised/60"
              }`}
            >
              <s.Icon className="h-4 w-4" />
              {s.label}
            </button>
          ))}
        </div>

        <div className="mt-auto px-5 py-4 text-[11px] text-slate-600">Mise à jour automatique toutes les 20 s</div>
      </aside>

      {/* Liste */}
      <section
        className={`min-h-0 w-full flex-col border-r border-line bg-canvas lg:flex lg:w-[380px] lg:shrink-0 ${
          selected != null ? "hidden lg:flex" : "flex"
        }`}
      >
        <div className="flex items-center justify-between px-4 py-2.5 text-xs text-slate-500">
          <span>{emails.length} email(s)</span>
          {loading && (
            <span className="inline-flex items-center gap-1.5 text-slate-600">
              <IconRefresh className="h-3.5 w-3.5 animate-spin" /> maj…
            </span>
          )}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto pb-6">
          {showSkeleton &&
            Array.from({ length: 7 }).map((_, i) => <SkeletonRow key={i} />)}

          {!showSkeleton &&
            groups.map((group) => (
              <div key={group.label}>
                <div className="sticky top-0 z-10 bg-canvas/90 px-4 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500 backdrop-blur">
                  {group.label}
                </div>
                {group.items.map((e) => (
                  <EmailRow
                    key={e.id}
                    email={e}
                    active={selected === e.id}
                    accountLabel={accountLabel(e.account_id)}
                    onClick={() => setSelected(e.id)}
                  />
                ))}
              </div>
            ))}

          {!showSkeleton && !emails.length && (
            <div className="flex flex-col items-center gap-3 px-4 py-20 text-center text-slate-600">
              <IconInbox className="h-10 w-10 opacity-40" />
              <p className="text-sm">Rien à afficher ici.</p>
            </div>
          )}
        </div>
      </section>

      {/* Détail (plein écran sur mobile) */}
      <main className={`min-h-0 min-w-0 flex-1 bg-canvas ${selected != null ? "flex" : "hidden lg:flex"}`}>
        <EmailDetail emailId={selected} onChanged={onChanged} onBack={() => setSelected(null)} />
      </main>
    </div>
  );
}

function LogoMark() {
  return (
    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand text-sm font-bold text-white shadow-sm">
      M
    </div>
  );
}

function EmailRow({
  email,
  active,
  accountLabel,
  onClick,
}: {
  email: Email;
  active: boolean;
  accountLabel: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex w-full animate-fade-in items-start gap-3 border-b border-line/50 border-l-2 px-4 py-3 text-left transition ${
        active ? "border-l-brand bg-raised" : "border-l-transparent hover:bg-raised/50"
      }`}
    >
      <Avatar sender={email.sender} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className={`truncate text-sm ${active ? "font-semibold text-white" : "font-medium text-slate-100"}`}>
            {senderName(email.sender)}
          </span>
          {isNew(email) && <NewBadge />}
          <span className="ml-auto shrink-0 text-[11px] text-slate-500">{timeAgo(emailDate(email))}</span>
        </div>
        <div className="mt-0.5 truncate text-sm text-slate-300">{email.subject || "(sans objet)"}</div>
        <div className="mt-1.5 flex items-center gap-2 text-[11px] text-slate-500">
          <span className="rounded bg-raised px-1.5 py-0.5 text-slate-400">{accountLabel}</span>
          <span className="truncate">{email.category}</span>
          <span className="ml-auto shrink-0">
            <PriorityBadge priority={email.priority} />
          </span>
        </div>
      </div>
    </button>
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
      className={`mb-0.5 flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition ${
        active ? "bg-brand-faint text-brand-soft" : "text-slate-300 hover:bg-raised/60"
      }`}
    >
      <IconMail className="h-4 w-4 shrink-0 opacity-70" />
      <span className="truncate">{label}</span>
      {count > 0 && (
        <span className="ml-auto rounded-full bg-brand/20 px-2 py-0.5 text-[11px] text-brand-soft">{count}</span>
      )}
    </button>
  );
}
