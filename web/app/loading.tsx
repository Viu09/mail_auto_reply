export default function Loading() {
  return (
    <div className="flex h-[100dvh] items-center justify-center bg-canvas">
      <div className="flex items-center gap-2.5 text-slate-500">
        <svg className="h-5 w-5 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
          <path d="M21 12a9 9 0 1 1-6.219-8.56" />
        </svg>
        <span className="text-sm">Chargement…</span>
      </div>
    </div>
  );
}
