"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, clearToken, getToken } from "@/lib/api";
import { CategoryCount, Document } from "@/lib/types";
import RichText from "@/components/RichText";
import { toastOk } from "@/lib/toast";
import {
  IconArrowLeft,
  IconDownload,
  IconEye,
  IconFile,
  IconLogout,
  IconPencil,
  IconRefresh,
  IconSparkles,
  IconTrash,
  IconX,
} from "@/components/icons";

function humanSize(bytes: number): string {
  if (!bytes) return "";
  const units = ["o", "Ko", "Mo", "Go"];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value.toFixed(value >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

function docDate(d: Document): string {
  const raw = d.received_at || d.created_at;
  return new Date(raw).toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" });
}

export default function DocumentsPage() {
  const router = useRouter();
  const [docs, setDocs] = useState<Document[]>([]);
  const [categories, setCategories] = useState<CategoryCount[]>([]);
  const [category, setCategory] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [preview, setPreview] = useState<Document | null>(null);

  useEffect(() => {
    if (!getToken()) router.replace("/login");
  }, [router]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = {};
      if (category) params.category = category;
      if (search.trim()) params.search = search.trim();
      const [d, c] = await Promise.all([api.listDocuments(params), api.documentCategories()]);
      setDocs(d);
      setCategories(c);
    } finally {
      setLoading(false);
    }
  }, [category, search]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (category && !categories.some((c) => c.name === category)) setCategory(null);
  }, [categories, category]);

  useEffect(() => {
    if (!preview) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setPreview(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [preview]);

  async function summarize(id: number) {
    setBusy(id);
    try {
      const updated = await api.summarizeDocument(id);
      setDocs((prev) => prev.map((d) => (d.id === id ? updated : d)));
      toastOk("Résumé généré.");
    } finally {
      setBusy(null);
    }
  }

  async function remove(id: number) {
    if (!window.confirm("Supprimer ce fichier stocké ? (l'email d'origine n'est pas touché)")) return;
    setBusy(id);
    try {
      await api.deleteDocument(id);
      setDocs((prev) => prev.filter((d) => d.id !== id));
      api.documentCategories().then(setCategories);
    } finally {
      setBusy(null);
    }
  }

  async function renameCategory(name: string) {
    const next = window.prompt(
      `Renommer la catégorie « ${name} ».\nSaisis un nom existant pour fusionner.`,
      name,
    );
    if (!next || next.trim() === name) return;
    await api.renameDocumentCategory(name, next.trim());
    if (category === name) setCategory(next.trim());
    refresh();
  }

  function logout() {
    clearToken();
    router.replace("/login");
  }

  function previewable(d: Document): boolean {
    const m = (d.mime_type || "").toLowerCase();
    return m.startsWith("image/") || m === "application/pdf" || /\.(png|jpe?g|gif|webp|pdf)$/i.test(d.file_name);
  }

  function toggleSelect(id: number) {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  async function bulkDelete() {
    if (!selected.length) return;
    if (!window.confirm(`Supprimer ${selected.length} fichier(s) stocké(s) ? (les emails d'origine ne sont pas touchés)`))
      return;
    const ids = selected;
    setDocs((prev) => prev.filter((d) => !ids.includes(d.id)));
    setSelected([]);
    await Promise.all(ids.map((id) => api.deleteDocument(id).catch(() => {})));
    api.documentCategories().then(setCategories);
    toastOk(`${ids.length} fichier(s) supprimé(s).`);
  }

  return (
    <div className="flex h-[100dvh] flex-col overflow-hidden bg-canvas">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-surface px-3 py-3 sm:px-4">
        <Link href="/inbox" className="shrink-0 rounded-md p-1.5 text-slate-400 hover:bg-raised" aria-label="Retour">
          <IconArrowLeft className="h-5 w-5" />
        </Link>
        <IconFile className="h-5 w-5 shrink-0 text-brand-soft" />
        <span className="text-[15px] font-semibold text-white">Documents</span>
        <span className="text-xs text-slate-500">{docs.length} fichier(s)</span>
        {loading && <IconRefresh className="h-4 w-4 animate-spin text-slate-600" />}
        <button
          onClick={logout}
          title="Déconnexion"
          className="ml-auto shrink-0 rounded-md p-1.5 text-slate-500 hover:bg-raised sm:order-last"
        >
          <IconLogout className="h-4 w-4" />
        </button>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Rechercher…"
          className="order-last w-full min-w-0 rounded-lg border border-line bg-canvas px-3 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 sm:order-none sm:ml-auto sm:w-56"
        />
      </header>

      {categories.length > 0 && (
        <div className="flex items-center gap-1.5 overflow-x-auto border-b border-line bg-surface px-4 py-2">
          <Tab label="Tous" active={category === null} onClick={() => setCategory(null)} />
          {categories.map((c) => (
            <Tab
              key={c.name}
              label={c.name}
              count={c.count}
              active={category === c.name}
              onClick={() => setCategory(c.name)}
              onEdit={() => renameCategory(c.name)}
            />
          ))}
        </div>
      )}

      {selected.length > 0 && (
        <div className="flex items-center gap-3 border-b border-line bg-brand-faint px-4 py-2 text-sm">
          <span className="font-medium text-slate-200">{selected.length} sélectionné(s)</span>
          <button
            onClick={bulkDelete}
            className="ml-auto inline-flex items-center gap-1 rounded-md bg-rose-500/15 px-2.5 py-1 font-medium text-rose-300 hover:bg-rose-500/25"
          >
            <IconTrash className="h-3.5 w-3.5" /> Supprimer
          </button>
          <button onClick={() => setSelected([])} className="rounded-md px-2 py-1 text-slate-400 hover:bg-raised">
            Annuler
          </button>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <div className="mx-auto grid w-full max-w-4xl grid-cols-1 gap-3">
          {!loading && docs.length === 0 && (
            <div className="flex flex-col items-center gap-3 py-24 text-center text-slate-600">
              <IconFile className="h-10 w-10 opacity-40" />
              <p className="text-sm">Aucun fichier stocké pour le moment.</p>
              <p className="max-w-sm text-xs text-slate-600">
                Les pièces jointes reçues par email sont enregistrées ici automatiquement.
              </p>
            </div>
          )}

          {docs.map((d) => (
            <div
              key={d.id}
              className={`rounded-xl border bg-surface p-4 shadow-sm ${
                selected.includes(d.id) ? "border-brand/40 ring-1 ring-brand/30" : "border-line"
              }`}
            >
              <div className="flex items-start gap-3">
                <input
                  type="checkbox"
                  checked={selected.includes(d.id)}
                  onChange={() => toggleSelect(d.id)}
                  className="mt-1 h-4 w-4 shrink-0 cursor-pointer rounded border-line bg-canvas accent-brand"
                />
                <button
                  onClick={() => previewable(d) && setPreview(d)}
                  disabled={!previewable(d)}
                  title={previewable(d) ? "Aperçu" : "Aperçu indisponible"}
                  className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-raised text-brand-soft transition enabled:hover:bg-overlay disabled:opacity-60"
                >
                  <IconFile className="h-5 w-5" />
                </button>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate text-sm font-medium text-slate-100">{d.file_name}</span>
                    <span className="rounded-md border border-line bg-raised px-2 py-0.5 text-[11px] text-slate-300">
                      {d.category}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-slate-500">
                    <span className="truncate">{d.sender || "—"}</span>
                    <span>·</span>
                    <span>{docDate(d)}</span>
                    {d.size_bytes > 0 && (
                      <>
                        <span>·</span>
                        <span>{humanSize(d.size_bytes)}</span>
                      </>
                    )}
                  </div>
                  {d.subject && <div className="mt-1 truncate text-xs text-slate-400">{d.subject}</div>}

                  {d.summary ? <DocSummary text={d.summary} /> : null}

                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    {previewable(d) && (
                      <button onClick={() => setPreview(d)} className="btn btn-ghost">
                        <IconEye className="h-4 w-4" /> Aperçu
                      </button>
                    )}
                    <a href={api.documentDownloadUrl(d.id)} className="btn btn-ghost" download>
                      <IconDownload className="h-4 w-4" /> Télécharger
                    </a>
                    <button onClick={() => summarize(d.id)} disabled={busy === d.id} className="btn btn-ghost">
                      <IconSparkles className="h-4 w-4" />
                      {busy === d.id ? "…" : d.summary ? "Re-résumer" : "Résumer"}
                    </button>
                    <button
                      onClick={() => remove(d.id)}
                      disabled={busy === d.id}
                      className="btn btn-ghost text-rose-300 hover:bg-rose-500/10"
                    >
                      <IconTrash className="h-4 w-4" /> Supprimer
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {preview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setPreview(null)} />
          <div
            role="dialog"
            aria-modal="true"
            aria-label={preview.file_name}
            className="relative flex h-[85vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-panel"
          >
            <div className="flex items-center gap-3 border-b border-line px-4 py-3">
              <IconFile className="h-4 w-4 shrink-0 text-brand-soft" />
              <span className="truncate text-sm font-medium text-slate-100">{preview.file_name}</span>
              <a
                href={api.documentDownloadUrl(preview.id)}
                download
                className="ml-auto rounded-md p-1.5 text-slate-400 hover:bg-raised"
                title="Télécharger"
              >
                <IconDownload className="h-4 w-4" />
              </a>
              <button onClick={() => setPreview(null)} className="rounded-md p-1.5 text-slate-400 hover:bg-raised" aria-label="Fermer">
                <IconX className="h-4 w-4" />
              </button>
            </div>
            <div className="min-h-0 flex-1 bg-canvas">
              {(preview.mime_type || "").startsWith("image/") ||
              /\.(png|jpe?g|gif|webp)$/i.test(preview.file_name) ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={api.documentDownloadUrl(preview.id)}
                  alt={preview.file_name}
                  className="mx-auto h-full w-full object-contain"
                />
              ) : (
                <iframe src={api.documentDownloadUrl(preview.id)} title={preview.file_name} className="h-full w-full" />
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function DocSummary({ text }: { text: string }) {
  return (
    <div className="mt-3 rounded-xl border border-line/60 border-l-2 border-l-brand/50 bg-canvas/50 px-4 py-3.5">
      <RichText text={text} />
    </div>
  );
}

function Tab({
  label,
  count,
  active,
  onClick,
  onEdit,
}: {
  label: string;
  count?: number;
  active: boolean;
  onClick: () => void;
  onEdit?: () => void;
}) {
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1 text-xs transition ${
        active ? "bg-brand text-white" : "bg-raised text-slate-400 hover:text-slate-200"
      }`}
    >
      <button onClick={onClick} className="inline-flex items-center gap-1.5">
        {label}
        {typeof count === "number" && (
          <span className={active ? "text-white/70" : "text-slate-500"}>{count}</span>
        )}
      </button>
      {onEdit && active && (
        <button onClick={onEdit} title="Renommer / fusionner" className="text-white/70 hover:text-white">
          <IconPencil className="h-3 w-3" />
        </button>
      )}
    </span>
  );
}
