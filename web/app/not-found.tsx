import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex h-[100dvh] flex-col items-center justify-center gap-4 bg-canvas px-6 text-center">
      <div className="text-5xl font-bold text-slate-700">404</div>
      <div>
        <h1 className="text-lg font-semibold text-white">Page introuvable</h1>
        <p className="mt-1 text-sm text-slate-500">Cette page n&apos;existe pas ou a été déplacée.</p>
      </div>
      <Link href="/inbox" className="btn btn-primary">
        Retour à la boîte
      </Link>
    </div>
  );
}
