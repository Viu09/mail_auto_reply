"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { Email } from "@/lib/types";
import ConfirmDialog from "./ConfirmDialog";
import { PriorityBadge, StatusBadge, Tag, fullDate, emailDate } from "./ui";
import {
  IconArrowLeft,
  IconCheck,
  IconFile,
  IconInfo,
  IconMail,
  IconPaperclip,
  IconSend,
  IconSparkles,
  IconTrash,
  IconX,
} from "./icons";

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
  const [confirmDelete, setConfirmDelete] = useState(false);
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
      <div className="hidden h-full w-full flex-col items-center justify-center gap-3 bg-canvas text-slate-600 lg:flex">
        <IconMail className="h-10 w-10 opacity-30" />
        <span className="text-sm">Sélectionne un email pour l'afficher.</span>
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

  async function deleteNow() {
    if (!email) return;
    setBusy("delete");
    setNotice(null);
    try {
      await api.deleteEmail(email.id);
      setConfirmDelete(false);
      onBack?.();
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
    <div className="flex h-full w-full min-w-0 animate-fade-in flex-col overflow-hidden bg-canvas">
      <ConfirmDialog
        open={confirmDelete}
        busy={busy === "delete"}
        title="Supprimer cet email ?"
        message="Il sera déplacé vers la corbeille Gmail (récupérable ~30 jours) et retiré de l'app."
        onConfirm={deleteNow}
        onCancel={() => setConfirmDelete(false)}
      />
      {/* En-tête */}
      <div className="border-b border-line bg-surface px-4 py-3.5 sm:px-6">
        <div className="mx-auto flex w-full max-w-3xl items-start gap-3">
          {onBack && (
            <button onClick={onBack} className="mt-0.5 rounded-md p-1 text-slate-400 hover:bg-raised lg:hidden" aria-label="Retour">
              <IconArrowLeft className="h-5 w-5" />
            </button>
          )}
          <div className="min-w-0 flex-1">
            <h2 className="break-words text-base font-semibold leading-tight text-white sm:text-lg">
              {email.subject || "(sans objet)"}
            </h2>
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
      </div>

      {/* Corps défilant, colonne de lecture centrée */}
      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-4 py-4 sm:px-6">
        <div className="mx-auto w-full max-w-3xl space-y-5">
          {notice && (
            <div
              className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
                notice.kind === "ok"
                  ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                  : "border-rose-500/30 bg-rose-500/10 text-rose-300"
              }`}
            >
              {notice.kind === "ok" ? <IconCheck className="h-4 w-4 shrink-0" /> : <IconX className="h-4 w-4 shrink-0" />}
              {notice.text}
            </div>
          )}

          {!email.should_reply && !sent && (
            <div className="flex items-center gap-2.5 rounded-lg border border-line bg-raised px-3 py-2.5 text-sm text-slate-400">
              <IconInfo className="h-4 w-4 shrink-0 text-slate-500" />
              <span>Cet email ne semble pas nécessiter de réponse (newsletter, notification…).</span>
            </div>
          )}

          <Card title="Résumé" icon={<IconInfo className="h-3.5 w-3.5 text-slate-500" />}>
            {email.summary ? (
              <SummaryText text={email.summary} />
            ) : (
              <p className="text-sm text-slate-500">—</p>
            )}
          </Card>

          <Card
            title="Réponse proposée par l'IA"
            icon={<IconSparkles className="h-3.5 w-3.5 text-brand-soft" />}
            accent
            chip={email.target_language}
          >
            <textarea
              value={reply}
              onChange={(e) => setReply(e.target.value)}
              disabled={sent}
              rows={11}
              placeholder="(Aucune réponse suggérée pour cet email)"
              className="w-full resize-y rounded-xl border border-line bg-canvas/70 px-4 py-3 text-sm leading-relaxed text-slate-100 outline-none transition focus:border-brand focus:shadow-[0_0_0_3px_rgba(99,102,241,0.15)] disabled:opacity-70"
            />
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button
                onClick={() => run("save", () => api.updateReply(email.id, reply), "Texte enregistré.")}
                disabled={!!busy || sent}
                className="btn btn-ghost"
              >
                <IconCheck className="h-4 w-4" /> Enregistrer
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
                <IconPaperclip className="h-4 w-4" /> Pièce jointe
              </button>
            </div>

            {!sent && (
              <div className="mt-4 flex flex-col gap-2 border-t border-line/60 pt-4 sm:flex-row">
                <input
                  value={instructions}
                  onChange={(e) => setInstructions(e.target.value)}
                  placeholder="Retravailler avec l'IA — ex. rends le ton plus formel"
                  className="field rounded-xl"
                  onKeyDown={(e) => e.key === "Enter" && refineNow()}
                />
                <button onClick={refineNow} disabled={!!busy || !instructions.trim()} className="btn btn-primary shrink-0">
                  <IconSparkles className="h-4 w-4" /> {busy === "refine" ? "…" : "Retravailler"}
                </button>
              </div>
            )}
          </Card>

          {email.attachment_names.length > 0 && (
            <Card title="Pièces jointes fournies" icon={<IconPaperclip className="h-3.5 w-3.5 text-slate-500" />}>
              <div className="flex flex-wrap gap-2">
                {email.attachment_names.map((name) => (
                  <a
                    key={name}
                    href={api.incomingAttachmentUrl(email.id, name)}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-canvas px-2.5 py-1.5 text-xs text-brand-soft hover:bg-raised"
                  >
                    <IconFile className="h-3.5 w-3.5" />
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
            <Details title="Synthèse détaillée" icon={<IconInfo className="h-3.5 w-3.5 text-slate-500" />}>
              <Prose text={email.detailed_summary} />
            </Details>
          )}

          {email.attachment_analysis && (
            <Details title="Analyse des pièces jointes" icon={<IconPaperclip className="h-3.5 w-3.5 text-slate-500" />}>
              <Prose text={email.attachment_analysis} />
            </Details>
          )}

          <Details title="Mail original complet">
            <div className="max-h-96 overflow-auto rounded-lg bg-canvas p-3">
              <p className="whitespace-pre-wrap [overflow-wrap:anywhere] text-sm leading-relaxed text-slate-300">
                {email.body_text || email.snippet || "(contenu indisponible)"}
              </p>
            </div>
          </Details>
        </div>
      </div>

      {/* Barre d'actions */}
      <div className="border-t border-line bg-surface px-4 py-3 sm:px-6">
        <div className="mx-auto flex w-full max-w-3xl flex-wrap items-center gap-2">
          {!sent && !rejected && (
            <>
              <button
                onClick={() => run("send", () => api.send(email.id), "Réponse envoyée par email.")}
                disabled={!!busy || !hasReply}
                className="btn btn-success"
              >
                <IconSend className="h-4 w-4" /> {busy === "send" ? "Envoi…" : "Envoyer la réponse"}
              </button>
              <button onClick={() => run("reject", () => api.reject(email.id), "Email refusé.")} disabled={!!busy} className="btn btn-ghost">
                <IconX className="h-4 w-4" /> Refuser
              </button>
            </>
          )}
          <button
            onClick={() => run("read", () => api.markRead(email.id), "Marqué comme lu dans Gmail.")}
            disabled={!!busy || email.marked_read}
            className="btn btn-ghost sm:ml-auto"
          >
            <IconCheck className="h-4 w-4" />
            {email.marked_read ? "Marqué lu" : busy === "read" ? "…" : "Marquer comme lu"}
          </button>
          <button
            onClick={() => setConfirmDelete(true)}
            disabled={!!busy}
            className="btn btn-ghost text-rose-300 hover:bg-rose-500/10"
          >
            <IconTrash className="h-4 w-4" />
            Supprimer
          </button>
        </div>
      </div>
    </div>
  );
}

function Card({
  title,
  children,
  icon,
  accent,
  chip,
}: {
  title: string;
  children: React.ReactNode;
  icon?: React.ReactNode;
  accent?: boolean;
  chip?: string;
}) {
  return (
    <section
      className={`min-w-0 overflow-hidden rounded-2xl border shadow-panel ${
        accent
          ? "border-brand/25 bg-gradient-to-b from-brand-faint to-surface"
          : "border-line bg-surface"
      }`}
    >
      <div className="flex items-center gap-2 border-b border-line/60 px-5 py-3">
        {icon}
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">{title}</h3>
        {chip && (
          <span className="ml-auto rounded-full bg-raised px-2.5 py-0.5 text-[10px] font-medium text-slate-300 ring-1 ring-line">
            {chip}
          </span>
        )}
      </div>
      <div className="px-5 py-4">{children}</div>
    </section>
  );
}

function Details({
  title,
  children,
  icon,
  defaultOpen,
}: {
  title: string;
  children: React.ReactNode;
  icon?: React.ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <details open={defaultOpen} className="group min-w-0 rounded-2xl border border-line bg-surface open:shadow-panel">
      <summary className="flex cursor-pointer select-none items-center gap-2 px-5 py-3.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400 transition hover:text-slate-200">
        <svg
          className="h-3.5 w-3.5 text-slate-500 transition-transform group-open:rotate-90"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="m9 18 6-6-6-6" />
        </svg>
        {icon}
        {title}
      </summary>
      <div className="px-5 pb-5">{children}</div>
    </details>
  );
}

// Rend un texte de synthèse en paragraphes lisibles ; les énumérations séparées
// par « ; » deviennent une liste à puces pour la scannabilité.
function Prose({ text }: { text: string }) {
  const blocks = text
    .split(/\n{2,}/)
    .map((b) => b.trim())
    .filter(Boolean);
  const source = blocks.length ? blocks : [text.trim()];

  return (
    <div className="rounded-xl border border-line/60 border-l-2 border-l-brand/50 bg-canvas/40 px-4 py-4">
      <div className="space-y-3 text-[13.5px] leading-7 text-slate-300">
        {source.map((block, i) => {
          const parts = block.split(/\s*;\s+/);
          if (parts.length >= 3) {
            const [head, ...rest] = parts;
            const colon = head.lastIndexOf(" : ");
            const intro = colon > -1 ? head.slice(0, colon + 3) : "";
            const firstItem = colon > -1 ? head.slice(colon + 3) : head;
            const items = [firstItem, ...rest];
            return (
              <div key={i} className="space-y-2">
                {intro && <p className="text-slate-200">{intro.replace(/\s*:\s*$/, "")} :</p>}
                <ul className="space-y-1.5">
                  {items.map((it, j) => (
                    <li key={j} className="flex gap-2.5">
                      <span className="mt-2.5 h-1 w-1 shrink-0 rounded-full bg-brand-soft" />
                      <span>{it.replace(/\.$/, "")}</span>
                    </li>
                  ))}
                </ul>
              </div>
            );
          }
          return <p key={i}>{block}</p>;
        })}
      </div>
    </div>
  );
}

function SummaryText({ text }: { text: string }) {
  const lines = text.split("\n").filter((l) => l.trim());
  return (
    <div className="space-y-1.5">
      {lines.map((line, i) => {
        const m = line.match(/^\s*([A-Za-zÀ-ÿ' ]{3,20})\s*:\s*(.*)$/);
        if (m) {
          return (
            <p key={i} className="text-sm leading-relaxed text-slate-200">
              <span className="font-semibold text-slate-100">{m[1].trim()}</span>
              <span className="text-slate-500"> · </span>
              {m[2]}
            </p>
          );
        }
        return (
          <p key={i} className="text-sm leading-relaxed text-slate-200">
            {line}
          </p>
        );
      })}
    </div>
  );
}

function DocList({ items, empty }: { items: string[]; empty: string }) {
  if (!items.length) return <p className="text-sm text-slate-500">{empty}</p>;
  return (
    <ul className="space-y-1 text-sm text-slate-300">
      {items.map((it) => (
        <li key={it} className="break-words">
          • {it}
        </li>
      ))}
    </ul>
  );
}
