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
      <div className="hidden h-full w-full items-center justify-center text-slate-600 lg:flex">
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

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      {/* En-tête */}
      <div className="flex items-start gap-3 border-b border-line px-4 py-3 sm:px-6">
        {onBack && (
          <button onClick={onBack} className="mt-0.5 rounded-md p-1 text-slate-400 hover:bg-raised lg:hidden" aria-label="Retour">
            ←
          </button>
        )}
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-base font-semibold text-white sm:text-lg">{email.subject || "(sans objet)"}</h2>
          <div className="mt-0.5 truncate text-sm text-slate-400">{email.sender}</div>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
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

      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-4 py-5 sm:px-6">
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
          <div className="rounded-lg border border-line bg-raised/50 px-3 py-2 text-sm text-slate-400">
            Cet email ne semble pas nécessiter de réponse (newsletter, notification…). Tu peux le refuser ou le marquer comme lu.
          </div>
        )}

        {/* Réponse proposée — mise en avant */}
        <Section title="Réponse proposée par l'IA">
          <textarea
            value={reply}
            onChange={(e) => setReply(e.target.value)}
            disabled={sent}
            rows={12}
            placeholder="(Aucune réponse suggérée pour cet email)"
            className="field font-normal leading-relaxed"
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
                if (f) run("upload", () => api.uploadAttachment(email.id, f), `Pièce jointe « ${f.name} » ajoutée à la réponse.`);
                if (fileRef.current) fileRef.current.value = "";
              }}
            />
            <button onClick={() => fileRef.current?.click()} disabled={!!busy || sent} className="btn btn-ghost">
              + Pièce jointe à envoyer
            </button>
          </div>
        </Section>

        {/* Retravailler avec l'IA */}
        {!sent && (
          <Section title="Retravailler avec l'IA">
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
                placeholder="ex. rends le ton plus formel et propose un rendez-vous"
                className="field"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && instructions.trim()) {
                    run("refine", async () => {
                      const r = await api.refine(email.id, instructions);
                      setInstructions("");
                      return r;
                    }, "Réponse retravaillée.");
                  }
                }}
              />
              <button
                onClick={() =>
                  run("refine", async () => {
                    const r = await api.refine(email.id, instructions);
                    setInstructions("");
                    return r;
                  }, "Réponse retravaillée.")
                }
                disabled={!!busy || !instructions.trim()}
                className="btn btn-ghost shrink-0"
              >
                {busy === "refine" ? "…" : "Retravailler"}
              </button>
            </div>
          </Section>
        )}

        <Section title="Résumé">
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-300">{email.summary || "—"}</p>
        </Section>

        {email.attachment_names.length > 0 && (
          <Section title="Pièces jointes fournies">
            <div className="flex flex-wrap gap-2">
              {email.attachment_names.map((name) => (
                <a
                  key={name}
                  href={`${api.apiUrl}/emails/${email.id}/incoming/${encodeURIComponent(name)}`}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-raised px-2.5 py-1.5 text-xs text-brand-soft hover:bg-overlay"
                >
                  <span>📎</span>
                  <span className="max-w-[220px] truncate">{name}</span>
                </a>
              ))}
            </div>
          </Section>
        )}

        {(email.required_documents.length > 0 || email.provided_documents.length > 0) && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Section title="Documents demandés">
              <DocList items={email.required_documents} empty="Aucun" />
            </Section>
            <Section title="Documents mentionnés comme fournis">
              <DocList items={email.provided_documents} empty="Aucun" />
            </Section>
          </div>
        )}

        {email.detailed_summary && email.detailed_summary !== email.summary && (
          <Details title="Synthèse détaillée">
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-400">{email.detailed_summary}</p>
          </Details>
        )}

        {email.attachment_analysis && (
          <Details title="Analyse des pièces jointes">
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-400">{email.attachment_analysis}</p>
          </Details>
        )}

        {/* Mail original en entier */}
        <Section title="Mail original complet">
          <div className="max-h-96 overflow-y-auto rounded-lg border border-line bg-canvas p-3">
            <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-300">
              {email.body_text || email.snippet || "(contenu indisponible)"}
            </p>
          </div>
        </Section>
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

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      {children}
    </div>
  );
}

function Details({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <details className="rounded-lg border border-line bg-raised/40 px-3 py-2">
      <summary className="cursor-pointer select-none text-[11px] font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </summary>
      <div className="mt-2">{children}</div>
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
