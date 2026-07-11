"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, getToken } from "@/lib/api";
import { Analytics } from "@/lib/types";
import { IconArrowLeft, IconRefresh } from "@/components/icons";

const MIN_SAVED_PER_REPLY = 6; // minutes estimées gagnées par réponse envoyée

export default function AnalyticsPage() {
  const router = useRouter();
  const [data, setData] = useState<Analytics | null>(null);

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  useEffect(() => {
    api.analytics().then(setData).catch(() => {});
  }, []);

  const savedMin = (data?.sent || 0) * MIN_SAVED_PER_REPLY;
  const savedLabel =
    savedMin >= 60 ? `${Math.floor(savedMin / 60)} h ${savedMin % 60} min` : `${savedMin} min`;

  const maxCat = Math.max(1, ...(data?.by_category || []).map((c) => c.count));
  const maxDay = Math.max(1, ...(data?.by_day || []).map((d) => d.count));

  return (
    <div className="min-h-[100dvh] bg-canvas">
      <header className="sticky top-0 z-10 flex items-center gap-3 border-b border-line bg-surface px-4 py-3">
        <Link href="/inbox" className="rounded-md p-1.5 text-slate-400 hover:bg-raised" aria-label="Retour">
          <IconArrowLeft className="h-5 w-5" />
        </Link>
        <span className="text-[15px] font-semibold text-white">Statistiques</span>
        {!data && <IconRefresh className="h-4 w-4 animate-spin text-slate-600" />}
      </header>

      <div className="mx-auto max-w-4xl space-y-6 p-4 sm:p-6">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Kpi label="Emails traités" value={data?.total ?? 0} />
          <Kpi label="Réponses envoyées" value={data?.sent ?? 0} tone="ok" />
          <Kpi label="En attente" value={data?.pending ?? 0} tone="warn" />
          <Kpi label="Temps gagné (est.)" value={savedLabel} tone="brand" />
        </div>

        <Card title="Répartition par catégorie">
          {!data || data.by_category.length === 0 ? (
            <Empty />
          ) : (
            <div className="space-y-2.5">
              {data.by_category.slice(0, 12).map((c) => (
                <div key={c.name} className="flex items-center gap-3">
                  <span className="w-28 shrink-0 truncate text-xs text-slate-400">{c.name}</span>
                  <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-raised">
                    <div
                      className="h-full rounded-full bg-brand"
                      style={{ width: `${(c.count / maxCat) * 100}%` }}
                    />
                  </div>
                  <span className="w-8 shrink-0 text-right text-xs tabular-nums text-slate-500">{c.count}</span>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card title="Volume par jour (30 derniers)">
          {!data || data.by_day.length === 0 ? (
            <Empty />
          ) : (
            <div className="flex h-40 items-end gap-1 overflow-x-auto">
              {data.by_day.map((d) => (
                <div key={d.day} className="flex min-w-[10px] flex-1 flex-col items-center gap-1" title={`${d.day} : ${d.count}`}>
                  <div
                    className="w-full rounded-t bg-brand/70 transition-all hover:bg-brand"
                    style={{ height: `${Math.max(4, (d.count / maxDay) * 130)}px` }}
                  />
                  <span className="text-[9px] text-slate-600">{d.day.slice(8, 10)}</span>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card title="Statut des réponses">
          <div className="flex flex-wrap gap-4 text-sm">
            <Legend color="bg-emerald-500" label="Envoyées" value={data?.sent ?? 0} />
            <Legend color="bg-brand" label="En attente" value={data?.pending ?? 0} />
            <Legend color="bg-slate-500" label="Refusées" value={data?.rejected ?? 0} />
            <Legend color="bg-amber-500" label="Documents" value={data?.documents ?? 0} />
          </div>
        </Card>
      </div>
    </div>
  );
}

function Kpi({ label, value, tone }: { label: string; value: string | number; tone?: "ok" | "warn" | "brand" }) {
  const color =
    tone === "ok" ? "text-emerald-300" : tone === "warn" ? "text-amber-300" : tone === "brand" ? "text-brand-soft" : "text-white";
  return (
    <div className="rounded-2xl border border-line bg-surface p-4 shadow-panel">
      <div className="text-[11px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${color}`}>{value}</div>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-line bg-surface p-5 shadow-panel">
      <h2 className="mb-4 text-sm font-semibold text-white">{title}</h2>
      {children}
    </section>
  );
}

function Legend({ color, label, value }: { color: string; label: string; value: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className={`h-3 w-3 rounded-sm ${color}`} />
      <span className="text-slate-400">{label}</span>
      <span className="font-semibold text-slate-100">{value}</span>
    </div>
  );
}

function Empty() {
  return <p className="text-sm text-slate-500">Pas encore de données.</p>;
}
