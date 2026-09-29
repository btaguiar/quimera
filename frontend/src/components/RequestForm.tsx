import { useState, type FormEvent, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ExampleChips } from "./ExampleChips";

export interface RequestFormProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (value: string) => void;
  loading: boolean;
  examples: string[];
  turnstileSlot: ReactNode;
  /** Motivo para não enviar (ex.: ICP inválido); desabilita o Analisar. */
  bloqueio?: string | null;
}

export function RequestForm({
  value,
  onChange,
  onSubmit,
  loading,
  examples,
  turnstileSlot,
  bloqueio = null,
}: RequestFormProps) {
  const [localError, setLocalError] = useState<string | null>(null);
  const [draft, setDraft] = useState(value);
  const [prevValue, setPrevValue] = useState(value);

  if (prevValue !== value) {
    setPrevValue(value);
    setDraft(value);
  }

  function applyDraft(next: string) {
    setLocalError(null);
    const clamped = next.slice(0, 500);
    setDraft(clamped);
    onChange(clamped);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const pedido = draft.trim();
    if (bloqueio) return;
    if (!pedido) {
      setLocalError("Escreva um pedido para analisar.");
      return;
    }
    setLocalError(null);
    onSubmit(pedido);
  }

  return (
    <form onSubmit={handleSubmit} className="mt-10 border-t border-border pt-8" noValidate>
      <label htmlFor="pedido" className="font-display block text-lg font-semibold">
        <span className="mr-2 font-mono text-sm font-normal text-accent">2</span>
        Seu pedido
      </label>
      <p className="mt-1 text-sm text-muted-foreground">
        Atividade, cidade ou bairro, porte, tempo de mercado. Escreva como falaria.
      </p>
      <Textarea
        id="pedido"
        name="request"
        value={draft}
        maxLength={500}
        rows={3}
        onChange={(e) => applyDraft(e.target.value)}
        placeholder="ex.: clínicas odontológicas em Santo André abertas há mais de 2 anos"
        className="mt-4 min-h-28 rounded-md border-input bg-background px-4 py-3 text-base leading-relaxed shadow-none placeholder:text-faint hover:border-line-strong focus-visible:border-ring focus-visible:ring-0 md:text-base"
        aria-describedby="contador pedido-erro"
        aria-invalid={!!localError}
      />
      <div className="mt-3 flex flex-wrap items-start justify-between gap-3">
        <ExampleChips examples={examples} onPick={applyDraft} />
        <p id="contador" className="ml-auto font-mono text-xs text-faint">
          {draft.length}/500
        </p>
      </div>
      {turnstileSlot ? <div className="mt-5">{turnstileSlot}</div> : null}
      <div className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-3">
        <Button
          type="submit"
          disabled={loading || !!bloqueio}
          className="font-display h-12 rounded-md px-8 text-base font-semibold [font-stretch:110%]"
        >
          {loading ? "Analisando…" : "Analisar"}
        </Button>
        <p id="pedido-erro" role="status" aria-live="polite" className="text-sm text-muted-foreground">
          {localError ?? (bloqueio ? `Ajuste o perfil antes de analisar: ${bloqueio}` : "")}
        </p>
      </div>
    </form>
  );
}
