import { cn } from "@/lib/utils";

/** Símbolo da Quimera: três formas fundidas num Q.
 *  Meio-disco = linguagem (LLM), quadrado = dados (BigQuery),
 *  cunha = vetor (embeddings). Mesmo desenho do public/favicon.svg. */
export function LogoSymbol({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("h-7 w-7", className)} aria-hidden focusable="false">
      <path d="M15 2 A14 14 0 0 0 15 30 Z" fill="var(--accent)" />
      <rect x="17" y="2" width="13" height="13" fill="var(--foreground)" />
      <path d="M17 17 L30 30 L17 30 Z" fill="var(--accent-strong)" />
    </svg>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoSymbol />
      <span className="font-display text-[1.35rem] leading-none font-bold [font-stretch:125%]">
        quimera
      </span>
    </span>
  );
}
