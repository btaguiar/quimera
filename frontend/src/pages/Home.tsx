import { useEffect, useRef, useState } from "react";
import { SiteHeader } from "@/components/SiteHeader";
import { Hero } from "@/components/Hero";
import { HowItWorks } from "@/components/HowItWorks";
import { UseCases, type CasoDeUso } from "@/components/UseCases";
import { Proof } from "@/components/Proof";
import { RequestForm } from "@/components/RequestForm";
import { StatusBanner, toErrorState, type ErrorState } from "@/components/StatusBanner";
import { ResultPanel } from "@/components/ResultPanel";
import { Footer } from "@/components/Footer";
import { IcpPicker, perfilAjustado } from "@/components/IcpPicker";
import { fetchConfig, fetchHealth, submitLead } from "@/lib/api";
import type { LeadsResponse } from "@/lib/types";
import { TurnstileController } from "@/lib/turnstile";
import { PERFIS, copiarParams, perfilPadrao, validarIcp, type IcpParams } from "@/lib/icp";

const EXEMPLOS = [
  "padarias artesanais em Curitiba",
  "oficinas mecânicas em Recife",
  "pet shops em Goiânia abertos há mais de 3 anos",
];

type SearchState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success"; data: LeadsResponse; browserSeconds: number; perfil: string }
  | { kind: "refused"; data: LeadsResponse }
  | { kind: "error"; error: ErrorState };

export default function Home() {
  const [pedido, setPedido] = useState("");
  const [perfilId, setPerfilId] = useState(perfilPadrao().id);
  const [icp, setIcp] = useState<IcpParams>(() => copiarParams(perfilPadrao().params));
  const icpErro = validarIcp(icp);
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
    if (!text || icpErro) return;
    // Captura o perfil no envio: trocar de perfil depois não reescreve o resultado.
    const nomePerfil = PERFIS.find((p) => p.id === perfilId)?.nome ?? "Perfil";
    const perfil = perfilAjustado(perfilId, icp) ? `${nomePerfil} (ajustado)` : nomePerfil;
    const icpEnviado = copiarParams(icp);
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
      const data = await submitLead(text, consumed.token, { icp: icpEnviado });
      const browserSeconds = (performance.now() - inicio) / 1000;
      if (data.refused) setState({ kind: "refused", data });
      else setState({ kind: "success", data, browserSeconds, perfil });
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

  function escolherPerfil(id: string) {
    setPerfilId(id);
    setIcp(copiarParams(PERFIS.find((p) => p.id === id)!.params));
  }

  function usarCaso(caso: CasoDeUso) {
    escolherPerfil(caso.perfilId);
    setPedido(caso.pedido);
    document.getElementById("demo")?.scrollIntoView?.({ block: "start" });
    document.getElementById("pedido")?.focus({ preventScroll: true });
  }

  return (
    <div className="min-h-screen">
      <SiteHeader />
      <main>
        <Hero version={version} />
        <HowItWorks />
        <UseCases onPick={usarCaso} />
        <Proof />

        <section id="demo" className="mx-auto max-w-6xl px-5 py-24 sm:px-8 lg:py-32">
          <div className="max-w-2xl">
            <h2 className="font-display text-[clamp(1.75rem,3.2vw,2.5rem)] leading-[1.1] font-bold">
              Teste agora com a sua frase
            </h2>
            <p className="mt-4 text-lg text-muted-foreground">
              Escolha o que define um bom cliente para você, descreva quem procura e analise. A
              resposta mostra a lista, o porquê de cada nota e o que a consulta custou.
            </p>
          </div>

          <div className="mt-12 rounded-xl border border-line-strong bg-card p-5 sm:p-8">
            <IcpPicker
              perfilId={perfilId}
              params={icp}
              onSelect={escolherPerfil}
              onChange={setIcp}
            />
            <RequestForm
              value={pedido}
              onChange={setPedido}
              onSubmit={handleSearch}
              loading={state.kind === "loading"}
              examples={EXEMPLOS}
              bloqueio={icpErro}
              turnstileSlot={turnstileOff ? null : <div ref={turnstileBox} className="min-h-16" />}
            />
          </div>

          <div ref={resultadoRef} tabIndex={-1} className="scroll-mt-24 outline-none" aria-live="polite">
            {state.kind === "idle" ? (
              <p className="mx-auto max-w-xl py-16 text-center text-muted-foreground">
                Escreva um pedido acima, ou escolha um caso de uso, e a Quimera devolve a lista com
                o motivo de cada escolha.
              </p>
            ) : null}
            {state.kind === "loading" ? (
              <div className="py-12" aria-busy="true">
                <p className="text-sm text-muted-foreground">
                  Analisando: interpretando a frase, escolhendo CNAEs, consultando a base e
                  ranqueando. Costuma levar poucos segundos.
                </p>
                <div className="mt-6 space-y-3">
                  {[0, 1, 2, 3].map((i) => (
                    <div key={i} className="h-14 animate-pulse rounded-md bg-card" />
                  ))}
                </div>
              </div>
            ) : null}
            {state.kind === "refused" ? (
              <div className="py-12">
                <StatusBanner refusal={state.data.refusal_reason || "pedido recusado"} />
              </div>
            ) : null}
            {state.kind === "error" ? (
              <div className="py-12">
                <StatusBanner
                  error={state.error}
                  onRetry={() => void handleSearch(pedido.trim())}
                />
              </div>
            ) : null}
            {state.kind === "success" ? (
              <div className="pt-12">
                <ResultPanel
                  data={state.data}
                  browserSeconds={state.browserSeconds}
                  budgetRemainingBytes={budgetRemaining}
                  perfil={state.perfil}
                />
              </div>
            ) : null}
          </div>
        </section>
      </main>
      <Footer version={version} />
    </div>
  );
}
