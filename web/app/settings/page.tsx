"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, clearToken, getToken } from "@/lib/api";
import { AccountSummary, IngestStatus, Rule, SenderFilter, Template } from "@/lib/types";
import { IconArrowLeft, IconCheck, IconPlus, IconRefresh, IconTrash } from "@/components/icons";
import { toastOk } from "@/lib/toast";

export default function SettingsPage() {
  const router = useRouter();
  const [status, setStatus] = useState<IngestStatus | null>(null);
  const [accounts, setAccounts] = useState<AccountSummary[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [filters, setFilters] = useState<SenderFilter[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [s, a, r, f, t] = await Promise.all([
        api.ingestStatus().catch(() => null),
        api.accounts().catch(() => []),
        api.rules().catch(() => []),
        api.senderFilters().catch(() => []),
        api.templates().catch(() => []),
      ]);
      setStatus(s);
      setAccounts(a);
      setRules(r);
      setFilters(f);
      setTemplates(t);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <div className="min-h-[100dvh] bg-canvas">
      <header className="sticky top-0 z-10 flex items-center gap-3 border-b border-line bg-surface px-4 py-3">
        <Link href="/inbox" className="rounded-md p-1.5 text-slate-400 hover:bg-raised" aria-label="Retour">
          <IconArrowLeft className="h-5 w-5" />
        </Link>
        <span className="text-[15px] font-semibold text-white">Paramètres</span>
        {loading && <IconRefresh className="h-4 w-4 animate-spin text-slate-600" />}
        <button
          onClick={() => {
            clearToken();
            router.replace("/login");
          }}
          className="ml-auto text-xs text-slate-500 hover:text-slate-300"
        >
          Déconnexion
        </button>
      </header>

      <div className="mx-auto max-w-3xl space-y-6 p-4 sm:p-6">
        <SystemStatus status={status} />
        <AccountsSection accounts={accounts} onChanged={refresh} />
        <RulesSection rules={rules} onChanged={refresh} />
        <FiltersSection filters={filters} onChanged={refresh} />
        <TemplatesSection templates={templates} onChanged={refresh} />
      </div>
    </div>
  );
}

function Section({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-line bg-surface p-5 shadow-panel">
      <h2 className="text-sm font-semibold text-white">{title}</h2>
      {description && <p className="mt-0.5 text-xs text-slate-500">{description}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function SystemStatus({ status }: { status: IngestStatus | null }) {
  const done = status?.backfill_all_done;
  return (
    <Section title="État du système" description="Ingestion des emails et rattrapage de l'historique.">
      {!status ? (
        <p className="text-sm text-slate-500">Chargement…</p>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Stat label="Emails traités" value={String(status.total_emails)} />
          <Stat
            label="Dernier email"
            value={status.last_email_at ? new Date(status.last_email_at).toLocaleString("fr-FR") : "—"}
          />
          <Stat
            label="Historique"
            value={done ? "À jour" : "Rattrapage en cours…"}
            tone={done ? "ok" : "warn"}
          />
        </div>
      )}
    </Section>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "ok" | "warn" }) {
  return (
    <div className="rounded-xl border border-line bg-canvas px-3 py-2.5">
      <div className="text-[11px] uppercase tracking-wider text-slate-500">{label}</div>
      <div
        className={`mt-0.5 truncate text-sm font-medium ${
          tone === "warn" ? "text-amber-300" : tone === "ok" ? "text-emerald-300" : "text-slate-100"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function AccountsSection({ accounts, onChanged }: { accounts: AccountSummary[]; onChanged: () => void }) {
  async function reconnect() {
    const status = await api.oauthStatus();
    if (!status.configured) {
      window.alert(`Connexion Google non configurée. URL de redirection à déclarer :\n\n${status.redirect_uri}`);
      return;
    }
    const { auth_url } = await api.oauthStart();
    window.location.href = auth_url;
  }

  return (
    <Section title="Comptes" description="Signature, langue et requête Gmail par compte connecté.">
      <div className="space-y-3">
        {accounts.map((a) => (
          <AccountRow key={a.account_id} account={a} onChanged={onChanged} onReconnect={reconnect} />
        ))}
      </div>
    </Section>
  );
}

function AccountRow({
  account,
  onChanged,
  onReconnect,
}: {
  account: AccountSummary;
  onChanged: () => void;
  onReconnect: () => void;
}) {
  const [signature, setSignature] = useState(account.signature || "");
  const [lang, setLang] = useState(account.reply_language || "fr");
  const [query, setQuery] = useState(account.gmail_query || "");
  const [saved, setSaved] = useState(false);

  async function save() {
    await api.updateAccount(account.account_id, {
      signature,
      reply_language: lang,
      gmail_query: query,
    });
    setSaved(true);
    toastOk("Réglages du compte enregistrés.");
    setTimeout(() => setSaved(false), 2000);
    onChanged();
  }

  return (
    <div className="rounded-xl border border-line bg-canvas p-3.5">
      <div className="flex items-center gap-2">
        <span className="truncate text-sm font-medium text-slate-100">{account.label}</span>
        {account.connected === false && (
          <button
            onClick={onReconnect}
            className="rounded-md bg-amber-500/15 px-2 py-0.5 text-[11px] font-medium text-amber-300 hover:bg-amber-500/25"
          >
            À reconnecter
          </button>
        )}
      </div>
      {account.editable ? (
        <div className="mt-3 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
          <label className="text-xs text-slate-500">
            Langue de réponse
            <input value={lang} onChange={(e) => setLang(e.target.value)} className="field mt-1" placeholder="fr" />
          </label>
          <label className="text-xs text-slate-500">
            Requête Gmail
            <input value={query} onChange={(e) => setQuery(e.target.value)} className="field mt-1" placeholder="category:primary" />
          </label>
          <label className="text-xs text-slate-500 sm:col-span-2">
            Signature
            <textarea
              value={signature}
              onChange={(e) => setSignature(e.target.value)}
              rows={2}
              className="field mt-1"
            />
          </label>
          <div className="sm:col-span-2">
            <button onClick={save} className="btn btn-primary">
              <IconCheck className="h-4 w-4" /> {saved ? "Enregistré" : "Enregistrer"}
            </button>
          </div>
        </div>
      ) : (
        <p className="mt-1 text-xs text-slate-500">Compte configuré côté serveur (non modifiable ici).</p>
      )}
    </div>
  );
}

const ACTIONS: Record<string, string> = {
  auto_send: "Envoyer automatiquement",
  auto_reject: "Refuser automatiquement",
  flag: "Signaler",
};

function RulesSection({ rules, onChanged }: { rules: Rule[]; onChanged: () => void }) {
  const [category, setCategory] = useState("");
  const [maxPriority, setMaxPriority] = useState("");
  const [action, setAction] = useState("flag");

  async function add() {
    await api.createRule({
      name: category || "Règle",
      category: category || null,
      max_priority: maxPriority || null,
      action: action as Rule["action"],
      enabled: true,
    });
    setCategory("");
    toastOk("Règle ajoutée.");
    onChanged();
  }

  return (
    <Section
      title="Règles d'automatisation"
      description="Traite automatiquement certains emails selon leur catégorie et priorité."
    >
      <div className="space-y-2">
        {rules.length === 0 && <p className="text-sm text-slate-500">Aucune règle.</p>}
        {rules.map((r) => (
          <div key={r.id} className="flex items-center gap-2 rounded-lg border border-line bg-canvas px-3 py-2 text-sm">
            <button
              onClick={() => api.updateRule(r.id, { enabled: !r.enabled }).then(onChanged)}
              className={`h-4 w-4 shrink-0 rounded-full border ${r.enabled ? "border-emerald-500 bg-emerald-500/40" : "border-line"}`}
              title={r.enabled ? "Activée" : "Désactivée"}
            />
            <span className="text-slate-300">
              {r.category || "Toutes catégories"}
              {r.max_priority ? ` · ≤ ${r.max_priority}` : ""} → <b className="text-slate-100">{ACTIONS[r.action] || r.action}</b>
            </span>
            <button onClick={() => api.deleteRule(r.id).then(onChanged)} className="ml-auto text-rose-300 hover:text-rose-200">
              <IconTrash className="h-4 w-4" />
            </button>
          </div>
        ))}
      </div>
      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-4">
        <input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="Catégorie (vide = toutes)" className="field" />
        <select value={maxPriority} onChange={(e) => setMaxPriority(e.target.value)} className="field">
          <option value="">Toute priorité</option>
          <option value="low">≤ basse</option>
          <option value="medium">≤ moyenne</option>
          <option value="high">≤ haute</option>
        </select>
        <select value={action} onChange={(e) => setAction(e.target.value)} className="field">
          <option value="flag">Signaler</option>
          <option value="auto_send">Envoyer auto</option>
          <option value="auto_reject">Refuser auto</option>
        </select>
        <button onClick={add} className="btn btn-primary">
          <IconPlus className="h-4 w-4" /> Ajouter
        </button>
      </div>
    </Section>
  );
}

function FiltersSection({ filters, onChanged }: { filters: SenderFilter[]; onChanged: () => void }) {
  const [pattern, setPattern] = useState("");
  const [action, setAction] = useState("ignore");
  const [category, setCategory] = useState("");

  async function add() {
    if (!pattern.trim()) return;
    await api.createSenderFilter({
      pattern: pattern.trim(),
      action: action as SenderFilter["action"],
      category: action === "category" ? category || "Autre" : null,
      enabled: true,
    });
    setPattern("");
    setCategory("");
    toastOk("Filtre ajouté.");
    onChanged();
  }

  return (
    <Section
      title="Filtres expéditeur"
      description="Appliqués AVANT l'IA (économie de coût). « Ignorer » n'analyse pas l'email ; « Catégorie » force une catégorie."
    >
      <div className="space-y-2">
        {filters.length === 0 && <p className="text-sm text-slate-500">Aucun filtre.</p>}
        {filters.map((f) => (
          <div key={f.id} className="flex items-center gap-2 rounded-lg border border-line bg-canvas px-3 py-2 text-sm">
            <code className="rounded bg-raised px-1.5 py-0.5 text-xs text-slate-300">{f.pattern}</code>
            <span className="text-slate-400">
              → {f.action === "ignore" ? "Ignorer (pas d'IA)" : `Catégorie : ${f.category}`}
            </span>
            <button onClick={() => api.deleteSenderFilter(f.id).then(onChanged)} className="ml-auto text-rose-300 hover:text-rose-200">
              <IconTrash className="h-4 w-4" />
            </button>
          </div>
        ))}
      </div>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
        <input
          value={pattern}
          onChange={(e) => setPattern(e.target.value)}
          placeholder="ex : @newsletter.com"
          className="field sm:min-w-[200px] sm:flex-1"
        />
        <select value={action} onChange={(e) => setAction(e.target.value)} className="field sm:w-44">
          <option value="ignore">Ignorer</option>
          <option value="category">Forcer catégorie</option>
        </select>
        {action === "category" && (
          <input
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            placeholder="Catégorie"
            className="field sm:w-40"
          />
        )}
        <button onClick={add} className="btn btn-primary shrink-0">
          <IconPlus className="h-4 w-4" /> Ajouter
        </button>
      </div>
    </Section>
  );
}

function TemplatesSection({ templates, onChanged }: { templates: Template[]; onChanged: () => void }) {
  const [name, setName] = useState("");
  const [body, setBody] = useState("");

  async function add() {
    if (!name.trim() || !body.trim()) return;
    await api.createTemplate({ name: name.trim(), body });
    setName("");
    setBody("");
    toastOk("Modèle ajouté.");
    onChanged();
  }

  return (
    <Section title="Modèles de réponse" description="Réutilisables en un clic depuis la fiche email.">
      <div className="space-y-2">
        {templates.length === 0 && <p className="text-sm text-slate-500">Aucun modèle.</p>}
        {templates.map((t) => (
          <div key={t.id} className="rounded-lg border border-line bg-canvas px-3 py-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-slate-100">{t.name}</span>
              <button onClick={() => api.deleteTemplate(t.id).then(onChanged)} className="ml-auto text-rose-300 hover:text-rose-200">
                <IconTrash className="h-4 w-4" />
              </button>
            </div>
            <p className="mt-1 line-clamp-2 whitespace-pre-wrap text-xs text-slate-500">{t.body}</p>
          </div>
        ))}
      </div>
      <div className="mt-3 space-y-2">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Nom du modèle" className="field" />
        <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={3} placeholder="Corps du modèle…" className="field" />
        <button onClick={add} className="btn btn-primary">
          <IconPlus className="h-4 w-4" /> Ajouter le modèle
        </button>
      </div>
    </Section>
  );
}
