"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { Email } from "@/lib/types";
import { PriorityBadge, StatusBadge, Tag, fullDate, emailDate } from "./ui";

export default function EmailDetail({
  emailId,
  onChanged,
  onBack,
}: {
  emailId: number | null;
  onChanged: () => void;
  onBack?: () => void;
}) {
  const [email, setEmail] = useState<Email | null>(null);
  const [reply, setReply] = useState("");
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (emailId == null) {
      setEmail(null);
      return;
    }
    setNotice(null);
    api.getEmail(emailId).then((e) => {
      setEmail(e);
      setReply(e.suggested_reply);
    });
  }, [emailId]);

  if (emailId == null || !email) {
    return (
      <div className="hidden h-full w-full items-center justify-center bg-canvas text-slate-600 lg:flex">
        Sélectionne un email pour l'afficher.
      </div>
    );
  }

  const sent = email.approval_status === "sent";
  const rejected = email.approval_status === "rejected";
  const hasReply = reply.replace(/\s/g, "").length > 0;

  async function run(label: string, fn: () => Promise<unknown>, okText?: string) {
    setBusy(label);
    setNotice(null);
    try {
      const updated = (await fn()) as Email;
      if (updated && typeof updated === "object" && "approval_status" in updated) {
        setEmail(updated);
        setReply(updated.suggested_reply);
      }
      if (okText) setNotice({ kind: "ok", text: okText });
      onChanged();
    } catch (err) {
      setNotice({ kind: "err", text: (err as Error).message });
    } finally {
      setBusy(null);
    }
  }

  function refineNow() {
    if (!instructions.trim()) return;
    run(
      "refine",
      async () => {
        const r = await api.refine(email!.id, instructions);
        setInstructions("");
        return r;
      },
      "Réponse retravaillée par l'IA.",
    );
  }

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-canvas">
      {/* En-tête */}
      <div className="flex items-start gap-3 border-b border-line bg-surface px-4 py-3 sm:px-6">
        {onBack && (
          <button onClick={onBack} className="mt-0.5 rounded-md px-1.5 py-0.5 text-lg text-slate-400 hover:bg-raised lg:hidden" aria-label="Retour">
            ←
          </button>
        )}
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-semibold leading-tight text-white sm:text-lg">{email.subject || "(sans objet)"}</h2>
          <div className="mt-1 truncate text-sm text-slate-400">{email.sender}</div>
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
            <PriorityBadge priority={email.priority} />
            <StatusBadge status={email.approval_status} />
            <Tag>{email.category}</Tag>
            {email.tags.map((t) => (
              <Tag key={t}>{t}</Tag>
            ))}
            <span className="ml-auto shrink-0 text-[11px] text-slate-500">{fullDate(emailDate(email))}</span>
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4 sm:px-6">
        {notice && (
          <div
            className={`rounded-lg border px-3 py-2 text-sm ${
              notice.kind === "ok"
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                : "border-rose-500/30 bg-rose-500/10 text-rose-300"
            }`}
          >
            {notice.text}
          </div>
        )}

        {!email.should_reply && !sent && (
          <div className="flex items-center gap-2 rounded-lg border border-line bg-raised px-3 py-2 text-sm text-slate-400">
            <span>ℹ️</span>
            <span>Cet email ne semble pas nécessiter de réponse (newsletter, notification…).</span>
          </div>
        )}

        {/* Résumé (contexte immédiat) */}
        <Card title="Résumé">
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-200">{email.summary || "—"}</p>
        </Card>

        {/* Réponse proposée */}
        <Card title="Réponse proposée par l'IA" accent>
          <textarea
            value={reply}
            onChange={(e) => setReply(e.target.value)}
            disabled={sent}
            rows={11}
            placeholder="(Aucune réponse suggérée pour cet email)"
            className="field min-h-[180px] leading-relaxed"
          />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <button
              onClick={() => run("save", () => api.updateReply(email.id, reply), "Texte enregistré.")}
              disabled={!!busy || sent}
              className="btn btn-ghost"
            >
              Enregistrer le texte
            </button>
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) run("upload", () => api.uploadAttachment(email.id, f), `Pièce jointe « ${f.name} » ajoutée.`);
                if (fileRef.current) fileRef.current.value = "";
              }}
            />
            <button onClick={() => fileRef.current?.click()} disabled={!!busy || sent} className="btn btn-ghost">
              + Pièce jointe
            </button>
          </div>

          {!sent && (
            <div className="mt-3 flex flex-col gap-2 border-t border-line pt-3 sm:flex-row">
              <input
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
                placeholder="Retravailler avec l'IA — ex. rends le ton plus formel"
                className="field"
                onKeyDown={(e) => e.key === "Enter" && refineNow()}
              />
              <button onClick={refineNow} disabled={!!busy || !instructions.trim()} className="btn btn-primary shrink-0">
                {busy === "refine" ? "…" : "Retravailler"}
              </button>
            </div>
          )}
        </Card>

        {email.attachment_names.length > 0 && (
          <Card title="Pièces jointes fournies">
            <div className="flex flex-wrap gap-2">
              {email.attachment_names.map((name) => (
                <a
                  key={name}
                  href={`${api.apiUrl}/emails/${email.id}/incoming/${encodeURIComponent(name)}`}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-canvas px-2.5 py-1.5 text-xs text-brand-soft hover:bg-raised"
                >
                  <span>📎</span>
                  <span className="max-w-[220px] truncate">{name}</span>
                </a>
              ))}
            </div>
          </Card>
        )}

        {(email.required_documents.length > 0 || email.provided_documents.length > 0) && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Card title="Documents demandés">
              <DocList items={email.required_documents} empty="Aucun" />
            </Card>
            <Card title="Documents fournis">
              <DocList items={email.provided_documents} empty="Aucun" />
            </Card>
          </div>
        )}

        {email.detailed_summary && email.detailed_summary !== email.summary && (
          <Details title="Synthèse détaillée">
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-300">{email.detailed_summary}</p>
          </Details>
        )}

        {email.attachment_analysis && (
          <Details title="Analyse des pièces jointes">
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-300">{email.attachment_analysis}</p>
          </Details>
        )}

        <Details title="Mail original complet">
          <div className="max-h-96 overflow-y-auto rounded-lg bg-canvas p-1">
            <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-300">
              {email.body_text || email.snippet || "(contenu indisponible)"}
            </p>
          </div>
        </Details>
      </div>

      {/* Barre d'actions */}
      <div className="flex flex-wrap items-center gap-2 border-t border-line bg-surface px-4 py-3 sm:px-6">
        {!sent && !rejected && (
          <>
            <button
              onClick={() => run("send", () => api.send(email.id), "Réponse envoyée par email.")}
              disabled={!!busy || !hasReply}
              className="btn btn-success"
            >
              {busy === "send" ? "Envoi…" : "Envoyer la réponse"}
            </button>
            <button onClick={() => run("reject", () => api.reject(email.id), "Email refusé.")} disabled={!!busy} className="btn btn-ghost">
              Refuser
            </button>
          </>
        )}
        <button
          onClick={() => run("read", () => api.markRead(email.id), "Marqué comme lu dans Gmail.")}
          disabled={!!busy || email.marked_read}
          className="btn btn-ghost sm:ml-auto"
        >
          {email.marked_read ? "Marqué lu ✓" : busy === "read" ? "…" : "Marquer comme lu"}
        </button>
      </div>
    </div>
  );
}

function Card({ title, children, accent }: { title: string; children: React.ReactNode; accent?: boolean }) {
  return (
    <section className={`rounded-xl border bg-surface p-4 ${accent ? "border-brand/30" : "border-line"}`}>
      <h3 className="mb-2.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      {children}
    </section>
  );
}

function Details({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <details className="rounded-xl border border-line bg-surface px-4 py-3">
      <summary className="cursor-pointer select-none text-[11px] font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </summary>
      <div className="mt-3">{children}</div>
    </details>
  );
}

function DocList({ items, empty }: { items: string[]; empty: string }) {
  if (!items.length) return <p className="text-sm text-slate-500">{empty}</p>;
  return (
    <ul className="space-y-1 text-sm text-slate-300">
      {items.map((it) => (
        <li key={it}>• {it}</li>
      ))}
    </ul>
  );
}
