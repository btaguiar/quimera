import type { LeadsResponse } from "@/lib/types";
import { fmtBytes, fmtMs, fmtUSD } from "@/lib/format";

function Linha({ label, valor }: { label: string; valor: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-widest text-muted-foreground">{label}</dt>
      <dd className="font-mono text-sm">{valor}</dd>
    </div>
  );
}

export function CostSummary({
  data,
  browserSeconds,
  budgetRemainingBytes,
}: {
  data: LeadsResponse;
  browserSeconds: number;
  budgetRemainingBytes?: number | null;
}) {
  const etapas = Object.entries(data.timings_ms ?? {})
    .map(([etapa, ms]) => `${etapa} ${fmtMs(ms)}`)
    .join(" · ");
  return (
    <div>
      {data.cache_mode ? (
        <p className="mb-4">
          <span className="rounded-full border border-warning/50 px-3 py-1 font-mono text-xs uppercase tracking-widest text-warning">
            Modo cache — orçamento do dia esgotado
          </span>
        </p>
      ) : null}
      <dl className="grid max-w-2xl grid-cols-1 gap-4 sm:grid-cols-2">
        <Linha label="Bytes cobrados" valor={fmtBytes(data.bytes_billed)} />
        <Linha label="Custo estimado" valor={fmtUSD(data.estimated_cost_usd)} />
        <Linha label="Latência do pipeline" valor={fmtMs(data.latency_ms)} />
        <Linha label="No navegador" valor={`${browserSeconds.toFixed(1).replace(".", ",")} s`} />
        <Linha
          label="Orçamento diário restante"
          valor={budgetRemainingBytes == null ? "—" : fmtBytes(budgetRemainingBytes)}
        />
        <Linha label="Modelo" valor={data.model || "—"} />
      </dl>
      {etapas ? <p className="mt-4 font-mono text-xs text-muted-foreground">{etapas}</p> : null}
    </div>
  );
}
