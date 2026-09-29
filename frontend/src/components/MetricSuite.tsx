import { fmtDataHora, fmtNumOrDash, fmtPct } from "@/lib/format";

export interface MetricLinha {
  rotulo: string;
  medido: number | null;
  limiar: number | null;
  quantidade?: boolean;
}

export function MetricSuite({
  numero,
  titulo,
  meta,
  linhas,
}: {
  numero: number;
  titulo: string;
  meta: { date?: string; commit?: string };
  linhas: MetricLinha[];
}) {
  return (
    <section className="rounded-xl border border-line-strong bg-card">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b border-border px-5 py-4 sm:px-6">
        <h2 className="font-display text-lg font-semibold">
          <span className="mr-2 font-mono text-sm font-normal text-accent">{numero}</span>
          {titulo}
        </h2>
        <p className="font-mono text-xs text-faint">
          execução: {fmtDataHora(meta.date)} · commit {meta.commit ?? "?"}
        </p>
      </div>
      <div className="relative overflow-x-auto px-5 pb-2 sm:px-6">
        <table className="w-full min-w-[32rem] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-faint">
              <th scope="col" className="py-3 pr-4 font-normal">Métrica</th>
              <th scope="col" className="py-3 pr-4 text-right font-normal">Medido</th>
              <th scope="col" className="py-3 pr-4 text-right font-normal">Limiar</th>
              <th scope="col" className="py-3 font-normal">
                <span className="sr-only">Estado</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {linhas.map((l) => {
              const batido = l.medido != null && l.limiar != null && l.medido >= l.limiar;
              return (
                <tr key={l.rotulo} className="border-b border-border last:border-b-0">
                  <td className="py-3 pr-4">{l.rotulo}</td>
                  <td className="py-3 pr-4 text-right font-mono">
                    {l.quantidade ? fmtNumOrDash(l.medido) : fmtPct(l.medido)}
                  </td>
                  <td className="py-3 pr-4 text-right font-mono text-faint">
                    {l.limiar == null ? "—" : l.quantidade ? fmtNumOrDash(l.limiar) : fmtPct(l.limiar)}
                  </td>
                  <td className="py-3 text-right">
                    {l.limiar == null || l.medido == null ? null : batido ? (
                      <span className="rounded-sm bg-success/10 px-2 py-0.5 font-mono text-xs whitespace-nowrap text-success">
                        acima do limiar
                      </span>
                    ) : (
                      <span className="rounded-sm bg-destructive/10 px-2 py-0.5 font-mono text-xs whitespace-nowrap text-destructive">
                        abaixo do limiar
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
