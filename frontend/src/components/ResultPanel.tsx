import type { ReactNode } from "react";
import type { LeadsResponse } from "@/lib/types";
import { FiltersBadge } from "./FiltersBadge";
import { CnaeList } from "./CnaeList";
import { SqlBlock } from "./SqlBlock";
import { RankingTable } from "./RankingTable";
import { CostSummary } from "./CostSummary";

function Section({
  titulo,
  children,
}: {
  titulo: string;
  children: ReactNode;
}) {
  return (
    <section className="border-t border-border py-8 first:border-t-0">
      <h2 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
        {titulo}
      </h2>
      <div className="mt-4">{children}</div>
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
  return (
    <div>
      {data.cached ? (
        <p className="mb-6">
          <span className="rounded-full border border-success/50 px-3 py-1 font-mono text-xs uppercase tracking-widest text-success">
            Em cache
          </span>
        </p>
      ) : null}
      {data.filters ? (
        <Section titulo="1 — Interpretação do pedido">
          <FiltersBadge filters={data.filters} />
        </Section>
      ) : null}
      {data.cnae_matches.length ? (
        <Section titulo="2 — Classificação CNAE">
          <CnaeList matches={data.cnae_matches} />
        </Section>
      ) : null}
      <Section titulo="3 — Consulta">
        {data.query_sql ? (
          <SqlBlock sql={data.query_sql} />
        ) : (
          <p className="text-sm text-muted-foreground">Consulta não executada (ver ressalvas).</p>
        )}
        <dl className="mt-4 grid max-w-2xl grid-cols-1 gap-2 font-mono text-sm sm:grid-cols-2">
          <div>
            <dt className="text-xs uppercase tracking-widest text-muted-foreground">Snapshot da base</dt>
            <dd>{snapshot ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-widest text-muted-foreground">SQL</dt>
            <dd className="text-xs text-muted-foreground">montado pelo sistema — o modelo não escreve SQL</dd>
          </div>
        </dl>
      </Section>
      <Section titulo="4 — Ranking de empresas">
        <RankingTable rows={data.rows} perfil={perfil} />
      </Section>
      <Section titulo="5 — Custos e latência">
        <CostSummary data={data} browserSeconds={browserSeconds} budgetRemainingBytes={budgetRemainingBytes} />
      </Section>
      {data.warnings.length ? (
        <Section titulo="6 — Ressalvas">
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            {data.warnings.map((w, i) => (
              <li key={`${i}-${w}`}>{w}</li>
            ))}
          </ul>
        </Section>
      ) : null}
    </div>
  );
}
