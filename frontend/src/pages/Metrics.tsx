import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { MetricSuite, type MetricLinha } from "@/components/MetricSuite";
import { Footer } from "@/components/Footer";
import { fetchMetrics } from "@/lib/api";
import { selectE2e, selectUltima } from "@/lib/metrics";
import type { MetricsResponse } from "@/lib/types";

function pctLinha(rotulo: string, medido: number | undefined, limiar: number | undefined): MetricLinha {
  return { rotulo, medido: medido ?? null, limiar: limiar ?? null };
}

function qtdLinha(rotulo: string, medido: number | undefined): MetricLinha {
  return { rotulo, medido: medido ?? null, limiar: null, quantidade: true };
}

export default function Metrics() {
  const [dados, setDados] = useState<MetricsResponse | null>(null);
  const [erro, setErro] = useState(false);

  useEffect(() => {
    fetchMetrics()
      .then(setDados)
      .catch(() => setErro(true));
  }, []);

  const ext = selectUltima(dados?.extraction);
  const cnae = selectUltima(dados?.cnae);
  const e2e = selectE2e(dados?.e2e);
  const lim = dados?.thresholds ?? {};

  return (
    <div className="min-h-screen">
      <div className="mx-auto max-w-5xl px-6">
        <header className="border-b border-border py-10">
          <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
            Anexo A
          </p>
          <h1 className="mt-2 text-3xl font-bold tracking-tight">Métricas medidas</h1>
          <p className="mt-3 max-w-2xl text-muted-foreground">
            Resultados medidos em <code className="font-mono text-xs">eval/results/</code>,
            comparados aos limiares de{" "}
            <code className="font-mono text-xs">eval/thresholds.json</code>. Nenhum número é
            escrito à mão.
          </p>
          <p className="mt-4">
            <Link to="/" className="text-accent underline-offset-4 hover:underline">
              ← voltar à demo
            </Link>
          </p>
        </header>

        <main className="space-y-6 py-10">
          {erro ? (
            <p className="text-muted-foreground">Não foi possível carregar as métricas.</p>
          ) : null}
          {!dados && !erro ? (
            <p className="font-mono text-sm text-muted-foreground">Carregando métricas…</p>
          ) : null}
          {ext ? (
            <MetricSuite
              numero={1}
              titulo="Extração de filtros"
              meta={{ date: ext.date, commit: ext.commit }}
              linhas={[
                pctLinha("Recusa correta (dado pessoal)", ext.metrics?.correct_refusal_rate, lim.correct_refusal_rate),
                pctLinha("Recusa indevida", ext.metrics?.false_refusal_rate, undefined),
                pctLinha("Acerto por campo", ext.metrics?.overall_field_accuracy, lim.overall_field_accuracy),
                pctLinha("Acerto exato do conjunto", ext.metrics?.exact_match_rate, undefined),
                qtdLinha("Casos", ext.metrics?.n_cases),
              ]}
            />
          ) : null}
          {cnae ? (
            <MetricSuite
              numero={2}
              titulo="Mapeamento CNAE"
              meta={{ date: cnae.date, commit: cnae.commit }}
              linhas={[
                pctLinha("Recall@1", cnae.metrics?.["recall@1"], undefined),
                pctLinha("Recall@5", cnae.metrics?.["recall@5"], lim.recall_at_5),
                pctLinha("MRR", cnae.metrics?.mrr, undefined),
                qtdLinha("Casos", cnae.metrics?.n_cases),
              ]}
            />
          ) : null}
          {e2e ? (
            <MetricSuite
              numero={3}
              titulo="Ponta a ponta"
              meta={{ date: e2e.date, commit: e2e.commit }}
              linhas={[
                pctLinha("Casos 100% corretos", e2e.metrics?.case_pass_rate, lim.e2e_case_pass_rate),
                pctLinha("Precisão por empresa", e2e.metrics?.row_precision, lim.e2e_row_precision),
                pctLinha("Recusa correta", e2e.metrics?.e2e_correct_refusal_rate, lim.e2e_correct_refusal_rate),
                qtdLinha("Empresas avaliadas", e2e.metrics?.n_rows),
                qtdLinha("Casos", e2e.metrics?.n_cases),
              ]}
            />
          ) : null}
          {dados && !ext && !cnae && !e2e ? (
            <p className="text-muted-foreground">Sem resultados de avaliação disponíveis.</p>
          ) : null}
          {e2e || cnae || ext ? (
            <p className="inline-block rounded-lg border-2 border-double border-accent px-4 py-2 font-mono text-xs uppercase tracking-widest text-accent">
              Avaliado — {((e2e || cnae || ext)!.date ?? "").slice(0, 10)}
            </p>
          ) : null}
        </main>
        <Footer />
      </div>
    </div>
  );
}
