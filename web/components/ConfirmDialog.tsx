"use client";

import { useEffect } from "react";
import { IconSend, IconTrash, IconX } from "./icons";

export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Supprimer",
  busyLabel = "Suppression…",
  busy = false,
  tone = "danger",
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  busyLabel?: string;
  busy?: boolean;
  tone?: "danger" | "brand";
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const danger = tone === "danger";
  const Icon = danger ? IconTrash : IconSend;
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onCancel();
      if (e.key === "Enter" && !busy) onConfirm();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, busy, onCancel, onConfirm]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      <div
        className="absolute inset-0 animate-fade-in bg-black/60 backdrop-blur-sm"
        onClick={busy ? undefined : onCancel}
      />
      <div className="relative w-full max-w-sm animate-fade-in rounded-2xl border border-line bg-surface p-5 shadow-panel">
        <div className="flex items-start gap-3.5">
          <div
            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${
              danger ? "bg-rose-500/15 text-rose-300" : "bg-brand-faint text-brand-soft"
            }`}
          >
            <Icon className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-base font-semibold text-white">{title}</h3>
            <p className="mt-1 text-sm leading-relaxed text-slate-400">{message}</p>
          </div>
          <button
            onClick={busy ? undefined : onCancel}
            disabled={busy}
            className="rounded-md p-1 text-slate-500 transition hover:bg-raised hover:text-slate-300 disabled:opacity-40"
            aria-label="Fermer"
          >
            <IconX className="h-4 w-4" />
          </button>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onCancel} disabled={busy} className="btn btn-ghost">
            Annuler
          </button>
          <button
            onClick={onConfirm}
            disabled={busy}
            className="btn bg-rose-600 text-white hover:bg-rose-500 disabled:opacity-60"
          >
            {busy ? busyLabel : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
