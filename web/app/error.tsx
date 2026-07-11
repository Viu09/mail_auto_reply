"use client";

import { useEffect } from "react";

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    // Trace côté client pour le debug.
    console.error(error);
  }, [error]);

  return (
    <div className="flex h-[100dvh] flex-col items-center justify-center gap-4 bg-canvas px-6 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-rose-500/15 text-rose-300">
        <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
          <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
          <path d="M12 9v4M12 17h.01" />
        </svg>
      </div>
      <div>
        <h1 className="text-lg font-semibold text-white">Une erreur est survenue</h1>
        <p className="mt-1 max-w-sm text-sm text-slate-500">
          Quelque chose s&apos;est mal passé. Tu peux réessayer ; si le problème persiste, recharge la page.
        </p>
      </div>
      <div className="flex gap-2">
        <button onClick={reset} className="btn btn-primary">
          Réessayer
        </button>
        <a href="/inbox" className="btn btn-ghost">
          Retour à la boîte
        </a>
      </div>
    </div>
  );
}
