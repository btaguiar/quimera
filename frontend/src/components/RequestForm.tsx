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
}

export function RequestForm({
  value,
  onChange,
  onSubmit,
  loading,
  examples,
  turnstileSlot,
}: RequestFormProps) {
  const [localError, setLocalError] = useState<string | null>(null);
  const [draft, setDraft] = useState(value);
  const [prevValue, setPrevValue] = useState(value);

  if (prevValue !== value) {
    setPrevValue(value);
    setDraft(value);
  }

  function applyDraft(next: string) {
    setDraft(next);
    onChange(next);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const pedido = draft.trim();
    if (!pedido) {
      setLocalError("Escreva um pedido para analisar.");
      return;
    }
    setLocalError(null);
    onSubmit(pedido);
  }

  return (
    <form onSubmit={handleSubmit} className="mt-8" noValidate>
      <label htmlFor="pedido" className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
        Pedido — o que a Quimera deve investigar
      </label>
      <Textarea
        id="pedido"
        name="request"
        value={draft}
        maxLength={500}
        rows={3}
        onChange={(e) => applyDraft(e.target.value)}
        placeholder="ex.: clínicas odontológicas em Santo André abertas há mais de 2 anos"
        className="mt-2 border-input bg-card"
        aria-describedby="contador"
      />
      <p id="contador" className="mt-1 text-right font-mono text-xs text-muted-foreground">
        {value.length}/500
      </p>
      <div className="mt-3">
        <ExampleChips examples={examples} onPick={applyDraft} />
      </div>
      <div className="mt-5">{turnstileSlot}</div>
      <Button
        type="submit"
        disabled={loading}
        className="mt-5 bg-primary px-8 py-6 text-sm font-semibold uppercase tracking-widest text-primary-foreground hover:opacity-90"
      >
        {loading ? "Analisando…" : "Analisar"}
      </Button>
      <p role="status" aria-live="polite" className="mt-3 min-h-6 font-mono text-sm text-muted-foreground">
        {localError ?? ""}
      </p>
    </form>
  );
}
