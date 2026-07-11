"use client";

import React from "react";

// Découpe un texte en phrases (période/point d'interrogation suivi d'un espace
// puis d'une majuscule/chiffre), sans casser les abréviations « 10.000 » ou « env. 1,5 ».
const SENTENCE_RE =
  /(?<=[.!?…])(?<!\b(?:env|art|cf|réf|ref|av|bd|Mme|MM|M|Dr|St|Ste|etc|al|pp|p|no|vol|chap)\.)\s+(?=[A-ZÀ-Þ«"'(])/u;

function splitSentences(text: string): string[] {
  return text
    .split(SENTENCE_RE)
    .map((s) => s.trim())
    .filter(Boolean);
}

// Gras markdown **…**
function inline(text: string, keyBase: string): React.ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) => {
    const m = part.match(/^\*\*([^*]+)\*\*$/);
    if (m) {
      return (
        <strong key={`${keyBase}-${i}`} className="font-semibold text-slate-100">
          {m[1]}
        </strong>
      );
    }
    return <React.Fragment key={`${keyBase}-${i}`}>{part}</React.Fragment>;
  });
}

// Détecte un préfixe « Libellé : valeur » en tête de phrase → libellé en gras.
const LABEL_RE = /^([A-Za-zÀ-ÿ'’()/\- ]{2,40}?)\s*:\s+(.+)$/s;

function renderText(text: string, keyBase: string): React.ReactNode {
  const m = text.match(LABEL_RE);
  if (m) {
    return (
      <>
        <strong className="font-semibold text-slate-100">{m[1].trim()}</strong>
        <span className="text-slate-500"> : </span>
        {inline(m[2], keyBase)}
      </>
    );
  }
  return inline(text, keyBase);
}

/**
 * Rendu structuré et lisible pour les textes de synthèse (résumés, analyses…).
 * Supporte : titres (#, ##, ###), puces (-, •, *), gras **…**, préfixes « Libellé : »,
 * et découpe automatiquement les longs paragraphes en phrases aérées.
 */
export default function RichText({ text, className = "" }: { text: string; className?: string }) {
  const lines = (text || "").replace(/\r/g, "").split("\n");
  const nodes: React.ReactNode[] = [];
  let bullets: string[] = [];
  let key = 0;

  const flushBullets = () => {
    if (!bullets.length) return;
    const items = bullets;
    bullets = [];
    nodes.push(
      <ul key={`ul-${key++}`} className="space-y-1.5">
        {items.map((b, i) => (
          <li key={i} className="flex gap-2.5">
            <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-brand-soft" />
            <span className="min-w-0 break-words">{renderText(b, `b-${key}-${i}`)}</span>
          </li>
        ))}
      </ul>,
    );
  };

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) {
      flushBullets();
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      flushBullets();
      const level = heading[1].length;
      const title = heading[2].replace(/\*\*/g, "").trim();
      nodes.push(
        level <= 2 ? (
          <h4
            key={`h-${key++}`}
            className="mt-3 text-[11px] font-semibold uppercase tracking-wider text-brand-soft first:mt-0"
          >
            {title}
          </h4>
        ) : (
          <h5 key={`h-${key++}`} className="mt-2 text-[13px] font-semibold text-slate-100">
            {title}
          </h5>
        ),
      );
      continue;
    }

    const bullet = line.match(/^[-•*]\s+(.*)$/);
    if (bullet) {
      bullets.push(bullet[1]);
      continue;
    }

    flushBullets();
    // Paragraphe : on l'aère en phrases individuelles pour éviter le « pavé ».
    for (const sentence of splitSentences(line)) {
      nodes.push(
        <p key={`p-${key++}`} className="text-[13px] leading-relaxed text-slate-300">
          {renderText(sentence, `p-${key}`)}
        </p>,
      );
    }
  }
  flushBullets();

  return <div className={`space-y-2 ${className}`}>{nodes}</div>;
}
