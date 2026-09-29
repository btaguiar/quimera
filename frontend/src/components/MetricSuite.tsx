import { fmtNumOrDash, fmtPct } from "@/lib/format";

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
    <section className="rounded-2xl border border-border bg-card p-6">
      <h2 className="flex items-baseline gap-3 font-semibold">
        <span className="font-mono text-sm text-accent">{numero}</span>
        {titulo}
      </h2>
      <p className="mt-1 font-mono text-xs text-muted-foreground">
        execução: {meta.date ?? "?"} · commit {meta.commit ?? "?"}
      </p>
      <table className="mt-4 w-full text-sm">
        <thead>
          <tr className="border-b border-foreground/20 text-left font-mono text-xs uppercase tracking-widest text-muted-foreground">
            <th scope="col" className="py-2 pr-4">Métrica</th>
            <th scope="col" className="py-2 pr-4 text-right">Medido</th>
            <th scope="col" className="py-2 pr-4 text-right">Limiar</th>
            <th scope="col" className="py-2">
              <span className="sr-only">Estado</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {linhas.map((l) => {
            const batido = l.medido != null && l.limiar != null && l.medido >= l.limiar;
            return (
              <tr key={l.rotulo} className="border-b border-border">
                <td className="py-2 pr-4">{l.rotulo}</td>
                <td className="py-2 pr-4 text-right font-mono">
                  {l.quantidade ? fmtNumOrDash(l.medido) : fmtPct(l.medido)}
                </td>
                <td className="py-2 pr-4 text-right font-mono">
                  {l.limiar == null ? "—" : l.quantidade ? fmtNumOrDash(l.limiar) : fmtPct(l.limiar)}
                </td>
                <td className="py-2">
                  {l.limiar == null || l.medido == null ? null : batido ? (
                    <span className="rounded-full border border-success/50 px-2 py-0.5 font-mono text-xs uppercase text-success">
                      acima do limiar
                    </span>
                  ) : (
                    <span className="rounded-full border border-destructive/50 px-2 py-0.5 font-mono text-xs uppercase text-destructive">
                      abaixo do limiar
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
