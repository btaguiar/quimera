import { Button } from "@/components/ui/button";
import { ApiError, NetworkError, TimeoutError } from "@/lib/api";
import type { ApiErrorBody } from "@/lib/types";

export type ErrorState =
  | { kind: "network" }
  | { kind: "timeout"; seconds: number }
  | { kind: "http"; status: number; body: ApiErrorBody | null; retryAfter: number | null };

export function toErrorState(err: unknown): ErrorState {
  if (err instanceof TimeoutError) {
    return { kind: "timeout", seconds: err.seconds };
  }
  if (err instanceof NetworkError || (err instanceof Error && err.name === "NetworkError")) {
    return { kind: "network" };
  }
  if (err instanceof ApiError || (err instanceof Error && err.name === "ApiError")) {
    const e = err as ApiError;
    return { kind: "http", status: e.status, body: e.body ?? null, retryAfter: e.retryAfter ?? null };
  }
  return { kind: "http", status: 0, body: null, retryAfter: null };
}

function httpMessage(state: Extract<ErrorState, { kind: "http" }>): string {
  const raw = state.body?.reason;
  const reason = typeof raw === "string" ? raw.trim() : "";
  if (reason) return reason;
  switch (state.status) {
    case 401:
      return "Não verificado: complete o desafio Turnstile (captcha) e tente de novo.";
    case 422:
      return "Pedido inválido: escreva um pedido com até 500 caracteres.";
    case 429:
      return state.retryAfter != null
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
  if (refusal != null) {
    return (
      <div role="status" className="rounded-lg border border-warning/30 bg-warning/[0.06] p-5 sm:p-6">
        <p className="font-display font-semibold text-warning">Pedido não atendido</p>
        <p className="mt-2 text-foreground">{refusal || "pedido recusado"}</p>
        <p className="mt-2 text-sm text-muted-foreground">
          A política pública não responde pedidos de dado pessoal — de sócios, contato ou
          qualquer pessoa física.
        </p>
      </div>
    );
  }
  if (!error) return null;
  const texto =
    error.kind === "network"
      ? "Não foi possível conectar à API."
      : error.kind === "timeout"
        ? `A API não respondeu em ${error.seconds} s. Tente de novo — pedidos mais específicos respondem mais rápido.`
        : httpMessage(error);
  return (
    <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/[0.06] p-5 sm:p-6">
      <p className="font-display font-semibold text-destructive">Pedido não atendido</p>
      <p className="mt-2 text-foreground">{texto}</p>
      {onRetry ? (
        <Button type="button" variant="outline" className="mt-4" onClick={onRetry}>
          Tentar de novo
        </Button>
      ) : null}
    </div>
  );
}
