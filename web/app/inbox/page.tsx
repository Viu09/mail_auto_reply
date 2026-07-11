"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, clearToken, getToken } from "@/lib/api";
import { AccountSummary, CategoryCount, Email } from "@/lib/types";
import EmailDetail from "@/components/EmailDetail";
import ConfirmDialog from "@/components/ConfirmDialog";
import ThemeToggle from "@/components/ThemeToggle";
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
import {
  IconChart,
  IconCheck,
  IconFolder,
  IconInbox,
  IconLogout,
  IconMail,
  IconPencil,
  IconPlus,
  IconRefresh,
  IconSend,
  IconSettings,
  IconSparkles,
  IconTrash,
  IconX,
} from "@/components/icons";

const STATUSES = [
  { key: "pending", label: "En attente", Icon: IconInbox },
  { key: "sent", label: "Envoyés", Icon: IconSend },
  { key: "rejected", label: "Refusés", Icon: IconX },
] as const;

export default function InboxPage() {
  const router = useRouter();
  const [accounts, setAccounts] = useState<AccountSummary[]>([]);
  const [emails, setEmails] = useState<Email[]>([]);
  const [categories, setCategories] = useState<CategoryCount[]>([]);
  const [account, setAccount] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("pending");
  const [category, setCategory] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [loading, setLoading] = useState(true);
  const [recatBusy, setRecatBusy] = useState(false);
  const [recatRemaining, setRecatRemaining] = useState(0);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [confirmBulk, setConfirmBulk] = useState<null | "delete" | "send">(null);
  const [deleting, setDeleting] = useState(false);
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(100);

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

  const refreshCategories = useCallback(async () => {
    try {
      const params: Record<string, string> = { status };
      if (account) params.account = account;
      setCategories(await api.categories(params));
    } catch {
      /* ignore */
    }
  }, [account, status]);

  const refreshEmails = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = { status, limit: String(limit) };
      if (account) params.account = account;
      if (category) params.category = category;
      if (search.trim()) params.search = search.trim();
      setEmails(await api.listEmails(params));
    } finally {
      setLoading(false);
    }
  }, [account, status, category, limit, search]);

  useEffect(() => {
    refreshAccounts();
  }, [refreshAccounts]);

  // La catégorie sélectionnée peut disparaître (auto add/remove) : on la réinitialise.
  useEffect(() => {
    if (category && !categories.some((c) => c.name === category)) setCategory(null);
  }, [categories, category]);

  useEffect(() => {
    // Débounce (surtout pour la recherche) : refetch après une courte pause.
    const t = setTimeout(() => {
      refreshEmails();
      refreshCategories();
      setSelectedIds([]);
    }, search ? 300 : 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account, status, category, limit, search]);

  useEffect(() => {
    const id = setInterval(() => {
      refreshAccounts();
      refreshEmails();
      refreshCategories();
    }, 20000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account, status, category, limit, search]);

  const onChanged = useCallback(() => {
    refreshAccounts();
    refreshEmails();
    refreshCategories();
  }, [refreshAccounts, refreshEmails, refreshCategories]);

  async function renameCategory(name: string) {
    const next = window.prompt(
      `Renommer la catégorie « ${name} ».\nSaisis un nom existant pour fusionner les deux.`,
      name,
    );
    if (!next || next.trim() === name) return;
    await api.renameCategory(name, next.trim());
    if (category === name) setCategory(next.trim());
    onChanged();
  }

  useEffect(() => {
    api.recategorizeStatus().then((r) => setRecatRemaining(r.remaining)).catch(() => {});
  }, []);

  // Résultat du retour OAuth (?connected / ?reconnected / ?account_error).
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    const connected = p.get("connected");
    const reconnected = p.get("reconnected");
    const err = p.get("account_error");
    if (connected) setBanner({ kind: "ok", text: `Compte ${connected} connecté.` });
    else if (reconnected) setBanner({ kind: "ok", text: `Compte ${reconnected} reconnecté.` });
    else if (err) setBanner({ kind: "err", text: `Échec de la connexion du compte (${err}).` });
    if (connected || reconnected || err) {
      window.history.replaceState({}, "", "/inbox");
      refreshAccounts();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!banner) return;
    const t = setTimeout(() => setBanner(null), 6000);
    return () => clearTimeout(t);
  }, [banner]);

  // Raccourcis clavier : j/k naviguer, x sélectionner, Échap fermer.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable)) return;
      if (!emails.length) return;
      const idx = selected != null ? emails.findIndex((x) => x.id === selected) : -1;
      if (e.key === "j" || e.key === "ArrowDown") {
        e.preventDefault();
        const n = emails[Math.min(emails.length - 1, idx + 1)];
        if (n) setSelected(n.id);
      } else if (e.key === "k" || e.key === "ArrowUp") {
        e.preventDefault();
        const p = emails[Math.max(0, idx < 0 ? 0 : idx - 1)];
        if (p) setSelected(p.id);
      } else if (e.key === "Escape") {
        setSelected(null);
      } else if (e.key === "x" && selected != null) {
        e.preventDefault();
        toggleSelect(selected);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [emails, selected]);

  async function addAccount() {
    try {
      const status = await api.oauthStatus();
      if (!status.configured) {
        window.alert(
          "La connexion Google n'est pas encore configurée côté serveur.\n\n" +
            "1) Dans Google Cloud, crée un identifiant OAuth de type « Application Web ».\n" +
            "2) Ajoute cette URL de redirection autorisée :\n\n" +
            status.redirect_uri +
            "\n\n3) Renseigne GOOGLE_OAUTH_CLIENT_JSON (ou _BASE64) avec ce client.",
        );
        return;
      }
      const { auth_url } = await api.oauthStart();
      window.location.href = auth_url;
    } catch (e) {
      setBanner({ kind: "err", text: (e as Error).message });
    }
  }

  async function removeAccount(id: string, label: string) {
    if (
      !window.confirm(
        `Supprimer le compte « ${label} » ?\nTous ses emails et documents importés seront effacés de l'app et il ne sera plus synchronisé (Gmail n'est pas touché). Tu pourras le reconnecter via « + Ajouter ».`,
      )
    )
      return;
    await api.deleteAccount(id);
    if (account === id) setAccount(null);
    setBanner({ kind: "ok", text: `Compte « ${label} » supprimé.` });
    onChanged();
  }

  async function runRecategorize() {
    setRecatBusy(true);
    try {
      let remaining = Infinity;
      let guard = 0;
      do {
        const r = await api.recategorize();
        remaining = r.remaining;
        setRecatRemaining(remaining);
        refreshCategories();
        refreshEmails();
        guard += 1;
      } while (remaining > 0 && guard < 30);
    } finally {
      setRecatBusy(false);
    }
  }

  function logout() {
    clearToken();
    router.replace("/login");
  }

  function toggleSelect(id: number) {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  const allVisibleSelected = emails.length > 0 && emails.every((e) => selectedIds.includes(e.id));

  function toggleSelectAll() {
    setSelectedIds(allVisibleSelected ? [] : emails.map((e) => e.id));
  }

  async function runBulk() {
    const action = confirmBulk;
    const ids = selectedIds;
    if (!action || !ids.length) return;
    setDeleting(true);
    // Retrait optimiste : les emails disparaissent immédiatement de la liste.
    setEmails((prev) => prev.filter((e) => !ids.includes(e.id)));
    if (selected != null && ids.includes(selected)) setSelected(null);
    try {
      if (action === "delete") await api.bulkDeleteEmails(ids);
      else await api.bulkSendEmails(ids);
      setSelectedIds([]);
      setConfirmBulk(null);
      setBanner({
        kind: "ok",
        text: action === "delete" ? `${ids.length} email(s) supprimé(s).` : `${ids.length} réponse(s) envoyée(s).`,
      });
      refreshAccounts();
      refreshCategories();
    } catch (e) {
      setBanner({ kind: "err", text: (e as Error).message || "Échec de l'opération." });
      refreshEmails();
    } finally {
      setDeleting(false);
    }
  }

  async function bulkReject() {
    const ids = selectedIds;
    if (!ids.length) return;
    setEmails((prev) => prev.filter((e) => !ids.includes(e.id)));
    setSelectedIds([]);
    try {
      await api.bulkRejectEmails(ids);
      setBanner({ kind: "ok", text: `${ids.length} email(s) refusé(s).` });
      refreshAccounts();
    } catch (e) {
      setBanner({ kind: "err", text: (e as Error).message });
      refreshEmails();
    }
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
      <ConfirmDialog
        open={confirmBulk !== null}
        busy={deleting}
        tone={confirmBulk === "send" ? "brand" : "danger"}
        title={
          confirmBulk === "send"
            ? `Envoyer ${selectedIds.length} réponse${selectedIds.length > 1 ? "s" : ""} ?`
            : `Supprimer ${selectedIds.length} email${selectedIds.length > 1 ? "s" : ""} ?`
        }
        message={
          confirmBulk === "send"
            ? "Les réponses proposées par l'IA seront envoyées par email. Action irréversible."
            : "Ils seront déplacés vers la corbeille Gmail (récupérables ~30 jours) et retirés de l'app."
        }
        confirmLabel={
          confirmBulk === "send" ? `Envoyer (${selectedIds.length})` : `Supprimer (${selectedIds.length})`
        }
        busyLabel={confirmBulk === "send" ? "Envoi…" : "Suppression…"}
        onConfirm={runBulk}
        onCancel={() => setConfirmBulk(null)}
      />
      {banner && (
        <div
          className={`fixed left-1/2 top-3 z-50 flex -translate-x-1/2 items-center gap-2 rounded-lg border px-3.5 py-2 text-sm shadow-panel ${
            banner.kind === "ok"
              ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-200"
              : "border-rose-500/30 bg-rose-500/15 text-rose-200"
          }`}
        >
          {banner.kind === "ok" ? <IconCheck className="h-4 w-4" /> : <IconX className="h-4 w-4" />}
          {banner.text}
        </div>
      )}
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
        <button onClick={addAccount} className="rounded-md p-1.5 text-slate-400 hover:bg-raised" aria-label="Ajouter un compte">
          <IconPlus className="h-4 w-4" />
        </button>
        <Link href="/documents" className="rounded-md p-1.5 text-slate-400 hover:bg-raised" aria-label="Documents">
          <IconFolder className="h-4 w-4" />
        </Link>
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
          <div className="flex items-center justify-between px-2 pb-1.5">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-600">Comptes</p>
            <button
              onClick={addAccount}
              title="Connecter un compte Gmail"
              className="inline-flex items-center gap-1 rounded-md bg-brand-faint px-1.5 py-0.5 text-[10px] font-medium text-brand-soft transition hover:bg-brand/20"
            >
              <IconPlus className="h-3 w-3" /> Ajouter
            </button>
          </div>
          <AccountItem label="Tous les comptes" count={totalPending} active={account === null} onClick={() => setAccount(null)} />
          {accounts.map((a) => (
            <AccountItem
              key={a.account_id}
              label={a.label}
              count={a.pending}
              active={account === a.account_id}
              warn={a.connected === false}
              onClick={() => setAccount(a.account_id)}
              onDelete={a.removable ? () => removeAccount(a.account_id, a.label) : undefined}
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

        <div className="mt-6 min-h-0 flex flex-col px-3">
          <div className="flex items-center justify-between px-2 pb-1.5">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-600">Catégories</p>
            {recatRemaining > 0 && (
              <button
                onClick={runRecategorize}
                disabled={recatBusy}
                title="Reclasser les emails restés en « Autre » avec l'IA"
                className="inline-flex items-center gap-1 rounded-md bg-brand-faint px-1.5 py-0.5 text-[10px] font-medium text-brand-soft transition hover:bg-brand/20 disabled:opacity-60"
              >
                <IconSparkles className={`h-3 w-3 ${recatBusy ? "animate-pulse" : ""}`} />
                {recatBusy ? `${recatRemaining}…` : `Affiner ${recatRemaining}`}
              </button>
            )}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto pr-0.5">
            <CategoryItem label="Tous" active={category === null} onClick={() => setCategory(null)} />
            {categories.map((c) => (
              <CategoryItem
                key={c.name}
                label={c.name}
                count={c.count}
                active={category === c.name}
                onClick={() => setCategory(c.name)}
                onEdit={() => renameCategory(c.name)}
              />
            ))}
          </div>
        </div>

        <div className="mt-4 px-3">
          <p className="px-2 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-600">Navigation</p>
          <Link
            href="/documents"
            className="mb-0.5 flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm text-slate-400 transition hover:bg-raised/60"
          >
            <IconFolder className="h-4 w-4" />
            Documents
          </Link>
          <Link
            href="/analytics"
            className="mb-0.5 flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm text-slate-400 transition hover:bg-raised/60"
          >
            <IconChart className="h-4 w-4" />
            Statistiques
          </Link>
          <Link
            href="/settings"
            className="mb-0.5 flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm text-slate-400 transition hover:bg-raised/60"
          >
            <IconSettings className="h-4 w-4" />
            Paramètres
          </Link>
          <ThemeToggle className="w-full" />
        </div>

        <div className="px-5 py-4 text-[11px] text-slate-600">Mise à jour automatique toutes les 20 s</div>
      </aside>

      {/* Liste */}
      <section
        className={`min-h-0 w-full flex-col border-r border-line bg-canvas lg:flex lg:w-[380px] lg:shrink-0 ${
          selected != null ? "hidden lg:flex" : "flex"
        }`}
      >
        <div className="flex items-center gap-2.5 px-4 py-2.5 text-xs text-slate-500">
          <input
            type="checkbox"
            checked={allVisibleSelected}
            onChange={toggleSelectAll}
            title="Tout sélectionner"
            className="h-4 w-4 shrink-0 cursor-pointer rounded border-line bg-canvas accent-brand"
          />
          {selectedIds.length > 0 ? (
            <>
              <span className="font-medium text-slate-200">{selectedIds.length} sélectionné(s)</span>
              <div className="ml-auto flex items-center gap-1.5">
                {status === "pending" && (
                  <>
                    <button
                      onClick={() => setConfirmBulk("send")}
                      className="inline-flex items-center gap-1 rounded-md bg-emerald-500/15 px-2.5 py-1 font-medium text-emerald-300 transition hover:bg-emerald-500/25"
                    >
                      <IconSend className="h-3.5 w-3.5" /> Envoyer
                    </button>
                    <button
                      onClick={bulkReject}
                      className="inline-flex items-center gap-1 rounded-md bg-raised px-2.5 py-1 font-medium text-slate-300 transition hover:bg-overlay"
                    >
                      <IconX className="h-3.5 w-3.5" /> Refuser
                    </button>
                  </>
                )}
                <button
                  onClick={() => setConfirmBulk("delete")}
                  className="inline-flex items-center gap-1 rounded-md bg-rose-500/15 px-2.5 py-1 font-medium text-rose-300 transition hover:bg-rose-500/25"
                >
                  <IconTrash className="h-3.5 w-3.5" /> Supprimer
                </button>
                <button
                  onClick={() => setSelectedIds([])}
                  className="rounded-md px-2 py-1 text-slate-400 transition hover:bg-raised"
                >
                  Annuler
                </button>
              </div>
            </>
          ) : (
            <>
              <span>{emails.length} email(s)</span>
              {loading && (
                <span className="ml-auto inline-flex items-center gap-1.5 text-slate-600">
                  <IconRefresh className="h-3.5 w-3.5 animate-spin" /> maj…
                </span>
              )}
            </>
          )}
        </div>

        {/* Recherche plein texte */}
        <div className="border-b border-line px-3 pb-2">
          <div className="relative">
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Rechercher (expéditeur, objet, contenu…)"
              className="w-full rounded-lg border border-line bg-canvas px-3 py-1.5 pr-7 text-xs text-slate-200 placeholder:text-slate-600 focus:border-brand focus:outline-none"
            />
            {search && (
              <button
                onClick={() => setSearch("")}
                className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-slate-500 hover:text-slate-300"
                aria-label="Effacer"
              >
                <IconX className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>

        {/* Onglets catégories — mobile uniquement (sur desktop ils sont dans la sidebar) */}
        {categories.length > 0 && (
          <div className="flex items-center gap-2 overflow-x-auto border-b border-line px-3 pb-2.5 lg:hidden">
            <CategoryTab label="Tous" active={category === null} onClick={() => setCategory(null)} />
            {categories.map((c) => (
              <CategoryTab
                key={c.name}
                label={c.name}
                count={c.count}
                active={category === c.name}
                onClick={() => setCategory(c.name)}
                onEdit={() => renameCategory(c.name)}
              />
            ))}
          </div>
        )}

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
                    checked={selectedIds.includes(e.id)}
                    accountLabel={accountLabel(e.account_id)}
                    onClick={() => setSelected(e.id)}
                    onToggle={() => toggleSelect(e.id)}
                  />
                ))}
              </div>
            ))}

          {!showSkeleton && !emails.length && (
            <div className="flex flex-col items-center gap-3 px-4 py-20 text-center text-slate-600">
              <IconInbox className="h-10 w-10 opacity-40" />
              <p className="text-sm">{search ? "Aucun résultat." : "Rien à afficher ici."}</p>
            </div>
          )}

          {!showSkeleton && emails.length >= limit && (
            <div className="p-4 text-center">
              <button
                onClick={() => setLimit((l) => l + 100)}
                className="rounded-lg border border-line px-4 py-2 text-sm text-slate-300 transition hover:bg-raised"
              >
                Charger plus
              </button>
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
  checked,
  accountLabel,
  onClick,
  onToggle,
}: {
  email: Email;
  active: boolean;
  checked: boolean;
  accountLabel: string;
  onClick: () => void;
  onToggle: () => void;
}) {
  return (
    <div
      className={`flex w-full animate-fade-in items-start border-b border-line/50 border-l-2 transition ${
        active
          ? "border-l-brand bg-raised"
          : checked
            ? "border-l-brand/40 bg-brand-faint"
            : "border-l-transparent hover:bg-raised/50"
      }`}
    >
      <label className="flex cursor-pointer items-center py-3 pl-4 pr-1" onClick={(e) => e.stopPropagation()}>
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          className="h-4 w-4 cursor-pointer rounded border-line bg-canvas accent-brand"
        />
      </label>
      <button onClick={onClick} className="flex min-w-0 flex-1 items-start gap-3 py-3 pl-1 pr-4 text-left">
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
    </div>
  );
}

function CategoryTab({
  label,
  count,
  active,
  onClick,
  onEdit,
}: {
  label: string;
  count?: number;
  active: boolean;
  onClick: () => void;
  onEdit?: () => void;
}) {
  return (
    <span
      className={`group inline-flex shrink-0 items-center gap-1.5 rounded-full px-3.5 py-1.5 text-sm transition ${
        active ? "bg-brand text-white shadow-sm" : "bg-raised text-slate-300 hover:text-white"
      }`}
    >
      <button onClick={onClick} className="inline-flex items-center gap-1.5">
        {label}
        {typeof count === "number" && (
          <span className={active ? "text-white/70" : "text-slate-500"}>{count}</span>
        )}
      </button>
      {onEdit && active && (
        <button
          onClick={onEdit}
          title="Renommer / fusionner"
          className="text-white/70 hover:text-white"
        >
          <IconPencil className="h-3.5 w-3.5" />
        </button>
      )}
    </span>
  );
}

function CategoryItem({
  label,
  count,
  active,
  onClick,
  onEdit,
}: {
  label: string;
  count?: number;
  active: boolean;
  onClick: () => void;
  onEdit?: () => void;
}) {
  return (
    <div
      className={`group mb-0.5 flex items-center rounded-lg text-sm transition ${
        active ? "bg-brand-faint text-brand-soft" : "text-slate-300 hover:bg-raised/60"
      }`}
    >
      <button onClick={onClick} className="flex min-w-0 flex-1 items-center gap-2.5 px-3 py-2 text-left">
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${active ? "bg-brand-soft" : "bg-line2"}`} />
        <span className="truncate">{label}</span>
        {typeof count === "number" && (
          <span
            className={`ml-auto rounded-full px-2 py-0.5 text-[11px] ${
              active ? "bg-brand/20 text-brand-soft" : "bg-raised text-slate-500"
            }`}
          >
            {count}
          </span>
        )}
      </button>
      {onEdit && (
        <button
          onClick={onEdit}
          title="Renommer / fusionner"
          className="mr-1.5 rounded-md p-1 text-slate-600 opacity-0 transition hover:bg-raised hover:text-slate-300 group-hover:opacity-100"
        >
          <IconPencil className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}

function AccountItem({
  label,
  count,
  active,
  warn,
  onClick,
  onDelete,
}: {
  label: string;
  count: number;
  active: boolean;
  warn?: boolean;
  onClick: () => void;
  onDelete?: () => void;
}) {
  return (
    <div
      className={`group mb-0.5 flex items-center rounded-lg text-sm transition ${
        active ? "bg-brand-faint text-brand-soft" : "text-slate-300 hover:bg-raised/60"
      }`}
    >
      <button onClick={onClick} className="flex min-w-0 flex-1 items-center gap-2.5 px-3 py-2 text-left">
        <IconMail className="h-4 w-4 shrink-0 opacity-70" />
        <span className="truncate">{label}</span>
        {warn && (
          <span
            className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400"
            title="Compte à reconnecter"
          />
        )}
        {count > 0 && (
          <span className="ml-auto rounded-full bg-brand/20 px-2 py-0.5 text-[11px] text-brand-soft">{count}</span>
        )}
      </button>
      {onDelete && (
        <button
          onClick={onDelete}
          title="Supprimer ce compte"
          className="mr-1.5 rounded-md p-1 text-slate-600 opacity-0 transition hover:bg-rose-500/10 hover:text-rose-300 group-hover:opacity-100"
        >
          <IconTrash className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}
