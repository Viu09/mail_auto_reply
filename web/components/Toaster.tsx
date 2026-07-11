"use client";

import { useEffect, useState } from "react";
import { ToastItem, dismissToast, subscribeToasts } from "@/lib/toast";
import { IconCheck, IconInfo, IconX } from "./icons";

export default function Toaster() {
  const [items, setItems] = useState<ToastItem[]>([]);

  useEffect(() => subscribeToasts(setItems), []);

  if (items.length === 0) return null;

  return (
    <div className="pointer-events-none fixed inset-x-0 top-3 z-[100] flex flex-col items-center gap-2 px-4">
      {items.map((t) => (
        <div
          key={t.id}
          role="status"
          className={`pointer-events-auto flex w-full max-w-sm animate-fade-in items-start gap-2.5 rounded-xl border px-3.5 py-2.5 text-sm shadow-panel ${
            t.kind === "ok"
              ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-200"
              : t.kind === "err"
                ? "border-rose-500/30 bg-rose-500/15 text-rose-200"
                : "border-brand/30 bg-brand-faint text-brand-soft"
          }`}
        >
          <span className="mt-0.5 shrink-0">
            {t.kind === "ok" ? (
              <IconCheck className="h-4 w-4" />
            ) : t.kind === "err" ? (
              <IconX className="h-4 w-4" />
            ) : (
              <IconInfo className="h-4 w-4" />
            )}
          </span>
          <span className="min-w-0 flex-1 break-words">{t.text}</span>
          <button
            onClick={() => dismissToast(t.id)}
            className="shrink-0 rounded p-0.5 opacity-60 transition hover:opacity-100"
            aria-label="Fermer"
          >
            <IconX className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}
