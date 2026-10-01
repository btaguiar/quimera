import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { fetchMetrics } from "@/lib/api";
import { margem95, selectE2e, selectEscala, selectUltima, varianteDoGolden } from "@/lib/metrics";
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

const fmtPontos = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });

function LinhasMedidas({ linhas }: { linhas: Linha[] }) {
  return (
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
  );
}

function Cabecalho() {
  return (
    <div className="grid grid-cols-[1fr_auto_auto] gap-x-5 border-b border-border px-5 py-3 text-xs text-faint sm:gap-x-8">
      <span>Métrica</span>
      <span className="w-16 text-right">Medido</span>
      <span className="w-20 text-right">Meta</span>
    </div>
  );
}

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
  const escala = selectEscala(dados?.e2e);
  const variante = varianteDoGolden(escala?.golden);
  const inedito = variante === "inedito";
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

  const m = escala?.metrics;
  const margem = margem95(m?.case_pass_rate, m?.n_cases);
  const linhasEscala: Linha[] = [
    {
      rotulo: "Pedidos com a lista inteira correta",
      detalhe:
        margem == null
          ? "ponta a ponta"
          : `margem de ±${fmtPontos.format(margem * 100)} ${margem * 100 < 2 ? "ponto" : "pontos"} no intervalo de 95%`,
      medido: m?.case_pass_rate,
      meta: lim[`e2e_${variante}_case_pass_rate`],
    },
    {
      rotulo: "Empresas devolvidas que atendem ao pedido",
      detalhe: "até 200 conferidas por pedido",
      medido: m?.row_precision,
      meta: lim[`e2e_${variante}_row_precision`],
    },
    {
      rotulo: "Pedidos de dado pessoal recusados",
      detalhe: "sem exceção",
      medido: m?.e2e_correct_refusal_rate,
      meta: lim.e2e_correct_refusal_rate,
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
              <Cabecalho />
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
                <LinhasMedidas linhas={linhas} />
              )}
            </div>
            <p className="mt-3 font-mono text-xs text-faint">
              {e2e
                ? `avaliação ${fmtDataHora(e2e.date)} · ${fmtNumOrDash(e2e.metrics?.n_cases)} pedidos escritos à mão · ${fmtNumOrDash(e2e.metrics?.n_rows)} empresas conferidas · commit ${e2e.commit ?? "?"}`
                : null}
            </p>

            {escala && linhasEscala.length ? (
              <section aria-labelledby="em-escala" className="mt-10">
                <h3 id="em-escala" className="font-display text-lg font-semibold">
                  Em escala: {fmtNumOrDash(m?.n_cases)} pedidos{inedito ? " inéditos" : ""}
                </h3>
                <p className="mt-1 mb-4 text-muted-foreground">
                  {inedito
                    ? "Pedidos gerados por modelo e nunca usados para ajustar o sistema, "
                    : "Pedidos gerados por modelo, "}
                  com {fmtNumOrDash(m?.n_rows)} empresas conferidas. O gabarito sai do cadastro, não
                  de uma IA; ela só reescreve a frase.
                </p>
                <div className="rounded-xl border border-line-strong bg-card">
                  <Cabecalho />
                  <LinhasMedidas linhas={linhasEscala} />
                </div>
                <p className="mt-3 font-mono text-xs text-faint">
                  avaliação {fmtDataHora(escala.date)} · commit {escala.commit ?? "?"}
                </p>
              </section>
            ) : null}

            <div className="mt-6 flex justify-end text-sm">
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
