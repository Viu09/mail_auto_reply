"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { Email } from "@/lib/types";
import { PriorityBadge, StatusBadge, Tag } from "./ui";

export default function EmailDetail({
  emailId,
  onChanged,
}: {
  emailId: number | null;
  onChanged: () => void;
}) {
  const [email, setEmail] = useState<Email | null>(null);
  const [reply, setReply] = useState("");
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
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
      <div className="flex h-full items-center justify-center text-slate-600">
        Sélectionne un email pour l'afficher.
      </div>
    );
  }

  const sent = email.approval_status === "sent";
  const rejected = email.approval_status === "rejected";

  async function run(label: string, fn: () => Promise<Email | unknown>) {
    setBusy(label);
    setNotice(null);
    try {
      const updated = (await fn()) as Email;
      if (updated && typeof updated === "object" && "id" in updated) {
        setEmail(updated as Email);
        setReply((updated as Email).suggested_reply);
      }
      onChanged();
    } catch (err) {
      setNotice((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* En-tete */}
      <div className="border-b border-ink-800 px-6 py-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="truncate text-lg font-semibold text-white">{email.subject || "(sans objet)"}</h2>
          <div className="flex shrink-0 items-center gap-2">
            <PriorityBadge priority={email.priority} />
            <StatusBadge status={email.approval_status} />
          </div>
        </div>
        <div className="mt-1 text-sm text-slate-400">{email.sender}</div>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <Tag>{email.category}</Tag>
          {email.tags.map((t) => (
            <Tag key={t}>{t}</Tag>
          ))}
        </div>
      </div>

      <div className="flex-1 space-y-6 overflow-y-auto px-6 py-5">
        {notice && (
          <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {notice}
          </div>
        )}

        <Section title="Résumé">
          <p className="whitespace-pre-wrap text-sm text-slate-300">{email.summary}</p>
        </Section>

        {email.detailed_summary && (
          <Details title="Synthèse détaillée">
            <p className="whitespace-pre-wrap text-sm text-slate-400">{email.detailed_summary}</p>
          </Details>
        )}

        <div className="grid grid-cols-2 gap-4">
          <Section title="Documents demandés">
            <DocList items={email.required_documents} empty="Aucun" />
          </Section>
          <Section title="Documents fournis">
            <DocList items={email.provided_documents} empty="Aucun" />
          </Section>
        </div>

        {email.attachment_names.length > 0 && (
          <Section title="Pièces jointes reçues">
            <div className="flex flex-wrap gap-2">
              {email.attachment_names.map((name) => (
                <a
                  key={name}
                  href={`${api.apiUrl}/emails/${email.id}/incoming/${encodeURIComponent(name)}`}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-md border border-ink-700 bg-ink-800 px-2 py-1 text-xs text-indigo-300 hover:bg-ink-700"
                >
                  {name}
                </a>
              ))}
            </div>
            {email.attachment_analysis && (
              <Details title="Analyse des pièces jointes">
                <p className="whitespace-pre-wrap text-sm text-slate-400">{email.attachment_analysis}</p>
              </Details>
            )}
          </Section>
        )}

        <Details title="Contenu original du mail">
          <p className="whitespace-pre-wrap text-sm text-slate-400">{email.body_text || email.snippet}</p>
        </Details>

        {/* Reponse editable */}
        <Section title="Réponse proposée">
          <textarea
            value={reply}
            onChange={(e) => setReply(e.target.value)}
            disabled={sent}
            rows={12}
            className="w-full rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 text-sm leading-relaxed outline-none focus:border-indigo-500 disabled:opacity-60"
          />
          <div className="mt-2 flex items-center gap-2">
            <button
              onClick={() => run("save", () => api.updateReply(email.id, reply))}
              disabled={!!busy || sent}
              className="rounded-md border border-ink-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-ink-800 disabled:opacity-50"
            >
              Enregistrer le texte
            </button>
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) run("upload", () => api.uploadAttachment(email.id, f));
                if (fileRef.current) fileRef.current.value = "";
              }}
            />
            <button
              onClick={() => fileRef.current?.click()}
              disabled={!!busy || sent}
              className="rounded-md border border-ink-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-ink-800 disabled:opacity-50"
            >
              + Pièce jointe
            </button>
          </div>
        </Section>

        {/* Retravail IA */}
        {!sent && (
          <Section title="Retravailler avec l'IA">
            <div className="flex gap-2">
              <input
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
                placeholder="ex. rends le ton plus formel et propose un rendez-vous"
                className="flex-1 rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 text-sm outline-none focus:border-indigo-500"
              />
              <button
                onClick={() =>
                  run("refine", async () => {
                    const r = await api.refine(email.id, instructions);
                    setInstructions("");
                    return r;
                  })
                }
                disabled={!!busy || !instructions.trim()}
                className="rounded-lg bg-ink-700 px-3 py-2 text-sm text-white hover:bg-ink-600 disabled:opacity-50"
              >
                {busy === "refine" ? "…" : "Retravailler"}
              </button>
            </div>
          </Section>
        )}
      </div>

      {/* Barre d'actions */}
      <div className="flex items-center gap-3 border-t border-ink-800 px-6 py-4">
        {!sent && !rejected && (
          <>
            <button
              onClick={() => run("send", () => api.send(email.id))}
              disabled={!!busy}
              className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
            >
              {busy === "send" ? "Envoi…" : "Envoyer la réponse"}
            </button>
            <button
              onClick={() => run("reject", () => api.reject(email.id))}
              disabled={!!busy}
              className="rounded-lg border border-ink-700 px-4 py-2 text-sm text-slate-300 hover:bg-ink-800 disabled:opacity-50"
            >
              Refuser
            </button>
          </>
        )}
        <button
          onClick={() => run("read", () => api.markRead(email.id))}
          disabled={!!busy || email.marked_read}
          className="ml-auto rounded-lg border border-ink-700 px-4 py-2 text-sm text-slate-300 hover:bg-ink-800 disabled:opacity-50"
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
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      {children}
    </div>
  );
}

function Details({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <details className="rounded-lg border border-ink-800 bg-ink-900/50 px-3 py-2">
      <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-slate-500">
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
