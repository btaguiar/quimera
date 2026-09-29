import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { fetchMetrics } from "@/lib/api";
import { selectE2e, selectUltima } from "@/lib/metrics";
import { fmtDataHora, fmtNumOrDash, fmtPct } from "@/lib/format";
import type { MetricsResponse } from "@/lib/types";

interface Linha {
  rotulo: string;
  detalhe: string;
  medido: number | undefined;
  meta: number | undefined;
}

const COMPROMISSOS = [
  {
    titulo: "O modelo nunca escreve SQL",
    texto: "Ele só preenche filtros. A consulta é montada pelo sistema, parametrizada e com estimativa de bytes antes de rodar.",
  },
  {
    titulo: "Nenhum dado pessoal",
    texto: "Sem sócios, e-mails, telefones ou MEI. Pedidos desse tipo são recusados, e a recusa também é medida.",
  },
  {
    titulo: "Custo com teto",
    texto: "Toda consulta tem limite de bytes e mostra o que custou. A demo tem orçamento diário e cai para cache quando ele acaba.",
  },
];

export function Proof() {
  const [dados, setDados] = useState<MetricsResponse | null>(null);
  const [erro, setErro] = useState(false);

  useEffect(() => {
    const ctl = new AbortController();
    fetchMetrics(ctl.signal)
      .then(setDados)
      .catch((e: unknown) => {
        if (!(e instanceof DOMException && e.name === "AbortError")) setErro(true);
      });
    return () => ctl.abort();
  }, []);

  const ext = selectUltima(dados?.extraction);
  const cnae = selectUltima(dados?.cnae);
  const e2e = selectE2e(dados?.e2e);
  const lim = dados?.thresholds ?? {};

  const linhas: Linha[] = [
    {
      rotulo: "Empresas devolvidas que atendem ao pedido",
      detalhe: "cada empresa conferida contra os filtros",
      medido: e2e?.metrics?.row_precision,
      meta: lim.e2e_row_precision,
    },
    {
      rotulo: "Pedidos com a lista inteira correta",
      detalhe: "ponta a ponta",
      medido: e2e?.metrics?.case_pass_rate,
      meta: lim.e2e_case_pass_rate,
    },
    {
      rotulo: "Pedidos de dado pessoal recusados",
      detalhe: "ponta a ponta",
      medido: e2e?.metrics?.e2e_correct_refusal_rate,
      meta: lim.e2e_correct_refusal_rate,
    },
    {
      rotulo: "Atividade certa entre os 5 primeiros CNAEs",
      detalhe: "recall@5 dos embeddings",
      medido: cnae?.metrics?.["recall@5"],
      meta: lim.recall_at_5,
    },
    {
      rotulo: "Filtros extraídos corretamente",
      detalhe: "acerto por campo",
      medido: ext?.metrics?.overall_field_accuracy,
      meta: lim.overall_field_accuracy,
    },
  ].filter((l) => l.medido != null);

  return (
    <section id="numeros" className="border-b border-border">
      <div className="mx-auto max-w-6xl px-5 py-24 sm:px-8 lg:py-32">
        <div className="grid gap-12 lg:grid-cols-12">
          <div className="lg:col-span-5">
            <h2 className="font-display text-[clamp(1.75rem,3.2vw,2.5rem)] leading-[1.1] font-bold">
              Números medidos, não prometidos
            </h2>
            <p className="mt-4 text-lg text-muted-foreground">
              Cada número ao lado vem da última avaliação do projeto, lida ao vivo desta API. O
              que fica abaixo da meta aparece abaixo da meta.
            </p>
            <dl className="mt-10 space-y-6">
              {COMPROMISSOS.map((c) => (
                <div key={c.titulo}>
                  <dt className="font-display font-semibold">{c.titulo}</dt>
                  <dd className="mt-1 leading-relaxed text-muted-foreground">{c.texto}</dd>
                </div>
              ))}
            </dl>
          </div>

          <div className="lg:col-span-7">
            <div className="rounded-xl border border-line-strong bg-card">
              <div className="grid grid-cols-[1fr_auto_auto] gap-x-5 border-b border-border px-5 py-3 text-xs text-faint sm:gap-x-8">
                <span>Métrica</span>
                <span className="w-16 text-right">Medido</span>
                <span className="w-20 text-right">Meta</span>
              </div>
              {erro ? (
                <p className="px-5 py-8 text-muted-foreground">
                  As métricas não carregaram agora. A página de métricas tem os mesmos números.
                </p>
              ) : !dados ? (
                <ul aria-busy="true" aria-label="Carregando métricas">
                  {[0, 1, 2, 3, 4].map((i) => (
                    <li key={i} className="border-b border-border px-5 py-5 last:border-b-0">
                      <span className="block h-4 w-2/3 animate-pulse rounded-sm bg-secondary" />
                    </li>
                  ))}
                </ul>
              ) : linhas.length === 0 ? (
                <p className="px-5 py-8 text-muted-foreground">Sem avaliação publicada ainda.</p>
              ) : (
                <ul>
                  {linhas.map((l) => {
                    const batida = l.meta == null || (l.medido ?? 0) >= l.meta;
                    return (
                      <li
                        key={l.rotulo}
                        className="grid grid-cols-[1fr_auto_auto] items-baseline gap-x-5 border-b border-border px-5 py-4 last:border-b-0 sm:gap-x-8"
                      >
                        <span>
                          <span className="block">{l.rotulo}</span>
                          <span className="block text-sm text-faint">{l.detalhe}</span>
                        </span>
                        <span
                          className={`w-16 text-right font-mono text-lg ${batida ? "text-foreground" : "text-destructive"}`}
                        >
                          {fmtPct(l.medido)}
                        </span>
                        <span className="w-20 text-right font-mono text-sm text-faint">
                          {l.meta == null ? "—" : `≥ ${fmtPct(l.meta)}`}
                          <span className="sr-only">{batida ? ", meta batida" : ", abaixo da meta"}</span>
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm text-faint">
              <span className="font-mono text-xs">
                {e2e
                  ? `avaliação ${fmtDataHora(e2e.date)} · ${fmtNumOrDash(e2e.metrics?.n_rows)} empresas conferidas · commit ${e2e.commit ?? "?"}`
                  : null}
              </span>
              <Link
                to="/metricas"
                className="inline-flex items-center gap-1.5 text-accent transition-colors duration-150 hover:text-accent-strong"
              >
                Todas as métricas
                <ArrowRight className="size-4" strokeWidth={2} aria-hidden />
              </Link>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
