// Petit store de notifications (pub/sub) utilisable partout sans contexte.

export type ToastKind = "ok" | "err" | "info";
export type ToastItem = { id: number; kind: ToastKind; text: string };

let counter = 0;
const listeners = new Set<(items: ToastItem[]) => void>();
let items: ToastItem[] = [];

function emit() {
  for (const l of listeners) l(items);
}

export function subscribeToasts(fn: (items: ToastItem[]) => void): () => void {
  listeners.add(fn);
  fn(items);
  return () => listeners.delete(fn);
}

export function dismissToast(id: number) {
  items = items.filter((t) => t.id !== id);
  emit();
}

export function toast(text: string, kind: ToastKind = "ok") {
  const id = ++counter;
  items = [...items, { id, kind, text }];
  emit();
  setTimeout(() => dismissToast(id), kind === "err" ? 7000 : 4000);
  return id;
}

export const toastOk = (t: string) => toast(t, "ok");
export const toastErr = (t: string) => toast(t, "err");
export const toastInfo = (t: string) => toast(t, "info");

// Enrobe une promesse : toast d'erreur automatique en cas d'échec.
export async function withToast<T>(
  p: Promise<T>,
  opts: { ok?: string; err?: string } = {},
): Promise<T | undefined> {
  try {
    const r = await p;
    if (opts.ok) toastOk(opts.ok);
    return r;
  } catch (e) {
    toastErr(opts.err || (e as Error)?.message || "Une erreur est survenue.");
    return undefined;
  }
}
