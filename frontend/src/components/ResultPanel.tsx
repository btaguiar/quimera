import type { ReactNode } from "react";
import type { LeadsResponse } from "@/lib/types";
import { FiltersBadge } from "./FiltersBadge";
import { CnaeList } from "./CnaeList";
import { SqlBlock } from "./SqlBlock";
import { RankingTable } from "./RankingTable";
import { CostSummary } from "./CostSummary";

function Section({
  numero,
  titulo,
  children,
}: {
  numero: number;
  titulo: string;
  children: ReactNode;
}) {
  return (
    <section className="grid gap-4 border-t border-border py-8 md:grid-cols-[14rem_1fr] md:gap-8">
      <h4 className="font-display font-semibold">
        <span className="mr-2 font-mono text-sm font-normal text-accent">{numero}</span>
        {titulo}
      </h4>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

export function ResultPanel({
  data,
  browserSeconds,
  budgetRemainingBytes,
  perfil,
}: {
  data: LeadsResponse;
  browserSeconds: number;
  budgetRemainingBytes?: number | null;
  /** Nome do perfil de ICP usado no ranking (ex.: "Estabelecida (ajustado)"). */
  perfil?: string | null;
}) {
  const snapshot = data.snapshot ? Object.values(data.snapshot)[0] : null;
  let n = 0;
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="font-display text-2xl font-bold">Empresas encontradas</h3>
        {data.cached ? (
          <span className="rounded-sm bg-success/10 px-2 py-1 font-mono text-xs text-success">
            Em cache
          </span>
        ) : null}
      </div>
      <div className="mt-5 rounded-xl border border-line-strong bg-card p-4 sm:p-6">
        <RankingTable rows={data.rows} perfil={perfil} />
      </div>

      <div className="mt-16">
        <h3 className="font-display text-xl font-bold">Como a Quimera chegou nessa lista</h3>
        <p className="mt-2 max-w-2xl text-muted-foreground">
          Os filtros que ela leu, os códigos de atividade, a consulta executada e o que custou.
        </p>
        <div className="mt-6">
          {data.filters ? (
            <Section numero={++n} titulo="Interpretação do pedido">
              <FiltersBadge filters={data.filters} />
            </Section>
          ) : null}
          {data.cnae_matches.length ? (
            <Section numero={++n} titulo="Classificação CNAE">
              <CnaeList matches={data.cnae_matches} />
            </Section>
          ) : null}
          <Section numero={++n} titulo="Consulta">
            {data.query_sql ? (
              <SqlBlock sql={data.query_sql} />
            ) : (
              <p className="text-sm text-muted-foreground">Consulta não executada (ver ressalvas).</p>
            )}
            <dl className="mt-4 grid max-w-2xl grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <dt className="text-xs text-faint">Snapshot da base</dt>
                <dd className="mt-0.5 font-mono text-sm">{snapshot ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-xs text-faint">SQL</dt>
                <dd className="mt-0.5 text-sm text-muted-foreground">
                  montado pelo sistema — o modelo não escreve SQL
                </dd>
              </div>
            </dl>
          </Section>
          <Section numero={++n} titulo="Custos e latência">
            <CostSummary data={data} browserSeconds={browserSeconds} budgetRemainingBytes={budgetRemainingBytes} />
          </Section>
          {data.warnings.length ? (
            <Section numero={++n} titulo="Ressalvas">
              <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted-foreground marker:text-warning">
                {data.warnings.map((w, i) => (
                  <li key={`${i}-${w}`}>{w}</li>
                ))}
              </ul>
            </Section>
          ) : null}
        </div>
      </div>
    </div>
  );
}
