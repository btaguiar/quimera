import { Button } from "@/components/ui/button";
import type { ApiErrorBody } from "@/lib/types";

export type ErrorState =
  | { kind: "network" }
  | { kind: "http"; status: number; body: ApiErrorBody | null; retryAfter: number | null };

function httpMessage(state: Extract<ErrorState, { kind: "http" }>): string {
  const reason = state.body?.reason?.trim();
  if (reason) return reason;
  switch (state.status) {
    case 401:
      return "Não verificado: complete o desafio Turnstile (captcha) e tente de novo.";
    case 422:
      return "Pedido inválido: escreva um pedido com até 500 caracteres.";
    case 429:
      return state.retryAfter
        ? `Muitas tentativas; aguarde ${state.retryAfter} s.`
        : "Muitas tentativas; aguarde alguns minutos.";
    case 500:
      return "Erro interno; tente de novo em instantes.";
    case 502:
      return "A extração falhou; reformule o pedido e tente de novo.";
    case 504:
      return "A execução excedeu o tempo limite; tente um pedido mais específico.";
    default:
      return `Erro ${state.status}; tente de novo.`;
  }
}

export function StatusBanner({
  error,
  refusal,
  onRetry,
}: {
  error?: ErrorState;
  refusal?: string | null;
  onRetry?: () => void;
}) {
  if (refusal) {
    return (
      <div role="status" className="rounded-xl border border-warning/40 bg-warning/10 p-5 text-warning-foreground">
        <p className="font-mono text-xs uppercase tracking-widest text-warning">Pedido não atendido</p>
        <p className="mt-2 text-sm">{refusal}</p>
        <p className="mt-2 text-sm text-muted-foreground">
          A política pública não responde pedidos de dado pessoal — de sócios, contato ou
          qualquer pessoa física.
        </p>
      </div>
    );
  }
  if (!error) return null;
  const texto = error.kind === "network" ? "Não foi possível conectar à API." : httpMessage(error);
  return (
    <div role="alert" className="rounded-xl border border-destructive/40 bg-destructive/10 p-5">
      <p className="font-mono text-xs uppercase tracking-widest text-destructive">
        Pedido não atendido
      </p>
      <p className="mt-2 text-sm">{texto}</p>
      {onRetry ? (
        <Button
          type="button"
          variant="outline"
          className="mt-4 border-border bg-transparent"
          onClick={onRetry}
        >
          Tentar de novo
        </Button>
      ) : null}
    </div>
  );
}
