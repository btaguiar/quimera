import { useEffect, useRef, useState } from "react";
import { Hero } from "@/components/Hero";
import { RequestForm } from "@/components/RequestForm";
import { StatusBanner, toErrorState, type ErrorState } from "@/components/StatusBanner";
import { ResultPanel } from "@/components/ResultPanel";
import { PipelineSteps } from "@/components/PipelineSteps";
import { Footer } from "@/components/Footer";
import { fetchConfig, fetchHealth, submitLead } from "@/lib/api";
import type { LeadsResponse } from "@/lib/types";
import { TurnstileController } from "@/lib/turnstile";

const EXEMPLOS = [
  "clínicas odontológicas em Santo André abertas há mais de 2 anos",
  "padarias artesanais em Curitiba",
  "transportadoras de carga em São Paulo capital",
  "escritórios de contabilidade em Belo Horizonte",
];

type SearchState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success"; data: LeadsResponse; browserSeconds: number }
  | { kind: "refused"; data: LeadsResponse }
  | { kind: "error"; error: ErrorState };

export default function Home() {
  const [pedido, setPedido] = useState("");
  const [state, setState] = useState<SearchState>({ kind: "idle" });
  const [version, setVersion] = useState<string | null>(null);
  const [budgetRemaining, setBudgetRemaining] = useState<number | null>(null);
  // Só desliga quando o /config diz explicitamente que não há site key (auth
  // desligada no dev); enquanto não responde, nunca POST sem token.
  const [turnstileOff, setTurnstileOff] = useState(false);
  const turnstile = useRef<TurnstileController | null>(null);
  const turnstileBox = useRef<HTMLDivElement | null>(null);
  const resultadoRef = useRef<HTMLDivElement | null>(null);

  function getTurnstile(): TurnstileController {
    if (!turnstile.current) turnstile.current = new TurnstileController();
    return turnstile.current;
  }

  function refreshHealth() {
    fetchHealth()
      .then((h) => setBudgetRemaining(h.budget_remaining_bytes))
      .catch(() => {});
  }

  useEffect(() => {
    fetchHealth()
      .then((h) => {
        setVersion(h.version);
        setBudgetRemaining(h.budget_remaining_bytes);
      })
      .catch(() => {});
    fetchConfig()
      .then((cfg) => {
        if (!cfg.turnstile_site_key) {
          setTurnstileOff(true);
        } else if (turnstileBox.current) {
          void getTurnstile().render(turnstileBox.current, cfg.turnstile_site_key);
        }
      })
      .catch(() => {});
    return () => {
      turnstile.current?.destroy();
    };
  }, []);

  async function handleSearch(text: string) {
    if (!text) return;
    const consumed = turnstileOff
      ? ({ ok: true, token: null } as const)
      : getTurnstile().consume();
    if (!consumed.ok) {
      setState({
        kind: "error",
        error: {
          kind: "http",
          status: 401,
          body: {
            error: "unauthorized",
            reason:
              consumed.reason === "indisponível"
                ? "O desafio anti-bot não está disponível neste navegador — recarregue a página ou desbloqueie o Cloudflare."
                : "Não verificado: complete o desafio Turnstile (captcha) e tente de novo.",
          },
          retryAfter: null,
        },
      });
      return;
    }
    setState({ kind: "loading" });
    const inicio = performance.now();
    try {
      const data = await submitLead(text, consumed.token);
      const browserSeconds = (performance.now() - inicio) / 1000;
      if (data.refused) setState({ kind: "refused", data });
      else setState({ kind: "success", data, browserSeconds });
    } catch (err) {
      setState({ kind: "error", error: toErrorState(err) });
    } finally {
      refreshHealth();
    }
  }

  useEffect(() => {
    if (state.kind !== "idle" && state.kind !== "loading") {
      resultadoRef.current?.focus();
    }
  }, [state]);

  return (
    <div className="min-h-screen">
      <div className="mx-auto max-w-5xl px-6">
        <Hero version={version}>
          <RequestForm
            value={pedido}
            onChange={setPedido}
            onSubmit={handleSearch}
            loading={state.kind === "loading"}
            examples={EXEMPLOS}
            turnstileSlot={<div ref={turnstileBox} className="min-h-16" />}
          />
        </Hero>

        <div ref={resultadoRef} tabIndex={-1} className="outline-none" aria-live="polite">
          {state.kind === "idle" ? (
            <p className="py-16 text-center text-muted-foreground">
              Escreva um pedido acima — ou escolha um dos modelos — e a Quimera devolve o
              laudo completo da investigação.
            </p>
          ) : null}
          {state.kind === "loading" ? (
            <div className="space-y-4 py-16" aria-busy="true">
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-24 animate-pulse rounded-2xl bg-card" />
              ))}
            </div>
          ) : null}
          {state.kind === "refused" ? (
            <div className="py-10">
              <StatusBanner refusal={state.data.refusal_reason || "pedido recusado"} />
            </div>
          ) : null}
          {state.kind === "error" ? (
            <div className="py-10">
              <StatusBanner
                error={state.error}
                onRetry={() => void handleSearch(pedido.trim())}
              />
            </div>
          ) : null}
          {state.kind === "success" ? (
            <div className="py-10">
              <ResultPanel
                data={state.data}
                browserSeconds={state.browserSeconds}
                budgetRemainingBytes={budgetRemaining}
              />
            </div>
          ) : null}
        </div>

        <PipelineSteps />
        <Footer />
      </div>
    </div>
  );
}
