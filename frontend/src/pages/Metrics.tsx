import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { MetricSuite, type MetricLinha } from "@/components/MetricSuite";
import { SiteHeader } from "@/components/SiteHeader";
import { Footer } from "@/components/Footer";
import { fetchMetrics } from "@/lib/api";
import { selectE2e, selectSintetico, selectUltima } from "@/lib/metrics";
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
  const escala = selectSintetico(dados?.e2e);
  const lim = dados?.thresholds ?? {};

  return (
    <div className="min-h-screen">
      <SiteHeader />
      <div className="mx-auto max-w-6xl px-5 sm:px-8">
        <header className="border-b border-border pt-14 pb-12 lg:pt-20">
          <Link
            to="/"
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors duration-150 hover:text-foreground"
          >
            <ArrowLeft className="size-4" strokeWidth={2} aria-hidden />
            voltar à demo
          </Link>
          <h1 className="font-display mt-6 text-[clamp(2.2rem,4.5vw,3.5rem)] leading-[1.05] font-bold">
            Métricas medidas
          </h1>
          <p className="mt-5 max-w-2xl text-lg leading-relaxed text-muted-foreground">
            Resultados medidos em <code className="font-mono text-sm text-foreground">eval/results/</code>,
            comparados aos limiares de{" "}
            <code className="font-mono text-sm text-foreground">eval/thresholds.json</code>. Nenhum
            número é escrito à mão; o que fica abaixo do limiar aparece abaixo do limiar.
          </p>
        </header>

        <main className="space-y-6 py-12">
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
          {escala ? (
            <MetricSuite
              numero={4}
              titulo="Ponta a ponta em escala (golden sintético)"
              meta={{ date: escala.date, commit: escala.commit }}
              linhas={[
                pctLinha("Casos 100% corretos", escala.metrics?.case_pass_rate, lim.e2e_sintetico_case_pass_rate),
                pctLinha("Precisão por empresa", escala.metrics?.row_precision, lim.e2e_sintetico_row_precision),
                pctLinha("Recusa correta", escala.metrics?.e2e_correct_refusal_rate, lim.e2e_correct_refusal_rate),
                pctLinha("Seleção de CNAE no plano B (cota do Gemini)", escala.metrics?.cnae_fallback_rate, undefined),
                pctLinha("Casos corretos sem o plano B", escala.metrics?.case_pass_rate_sem_fallback, undefined),
                qtdLinha("Empresas avaliadas", escala.metrics?.n_rows),
                qtdLinha("Casos", escala.metrics?.n_cases),
              ]}
            />
          ) : null}
          {dados && !ext && !cnae && !e2e ? (
            <p className="text-muted-foreground">Sem resultados de avaliação disponíveis.</p>
          ) : null}
          {e2e || cnae || ext ? (
            <p className="inline-flex items-center gap-2 pt-2 font-mono text-xs text-faint">
              <span className="size-1.5 rounded-full bg-success" aria-hidden />
              Avaliado — {((e2e || cnae || ext)!.date ?? "").slice(0, 10)}
            </p>
          ) : null}
        </main>
      </div>
      <Footer />
    </div>
  );
}
