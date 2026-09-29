import type { LeadRow } from "@/lib/types";
import { fmtData, fmtNumOrDash } from "@/lib/format";

export function RankingTable({ rows }: { rows: LeadRow[] }) {
  if (!rows.length) {
    return (
      <p className="text-sm text-muted-foreground">
        Nenhuma empresa atendida ao pedido (ver ressalvas).
      </p>
    );
  }
  return (
    <div>
      <p className="mb-3 font-mono text-xs text-muted-foreground">
        {rows.length} {rows.length === 1 ? "empresa" : "empresas"} — ordenadas pela nota do ICP
      </p>
      <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Ranking de empresas">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-foreground/20 text-left font-mono text-xs uppercase tracking-widest text-muted-foreground">
              <th scope="col" className="py-2 pr-3">#</th>
              <th scope="col" className="py-2 pr-3">Empresa</th>
              <th scope="col" className="py-2 pr-3">Local</th>
              <th scope="col" className="py-2 pr-3">CNAE</th>
              <th scope="col" className="py-2 pr-3">Início</th>
              <th scope="col" className="py-2 pr-3 text-right">Capital (R$)</th>
              <th scope="col" className="py-2 pr-3">Porte</th>
              <th scope="col" className="py-2 pr-3 text-right">Nota</th>
              <th scope="col" className="py-2">
                <span className="sr-only">Motivos</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.razao_social}-${i}`} className="border-b border-border align-top">
                <td className="py-3 pr-3 font-mono text-muted-foreground">{i + 1}</td>
                <td className="py-3 pr-3">
                  <span className="font-medium">{r.razao_social}</span>
                  {r.nome_fantasia ? (
                    <span className="block text-xs text-muted-foreground">{r.nome_fantasia}</span>
                  ) : null}
                </td>
                <td className="py-3 pr-3">
                  {r.municipio ?? "—"}/{r.sigla_uf ?? "—"}
                </td>
                <td className="py-3 pr-3 font-mono text-xs">{r.cnae_fiscal_principal ?? "—"}</td>
                <td className="py-3 pr-3 font-mono text-xs">{fmtData(r.data_inicio_atividade)}</td>
                <td className="py-3 pr-3 text-right font-mono">{fmtNumOrDash(r.capital_social)}</td>
                <td className="py-3 pr-3">{r.porte ?? "—"}</td>
                <td className="py-3 pr-3 text-right">
                  {r.score == null ? (
                    <span className="font-mono">—</span>
                  ) : (
                    <div className="flex items-center justify-end gap-2">
                      <span
                        aria-hidden
                        className="h-1.5 w-16 overflow-hidden rounded-full bg-muted"
                      >
                        <span
                          className="block h-full rounded-full bg-accent"
                          style={{ width: `${Math.max(0, Math.min(100, r.score))}%` }}
                        />
                      </span>
                      <span className="font-mono">{fmtNumOrDash(r.score)}</span>
                    </div>
                  )}
                </td>
                <td className="py-3">
                  {r.motivos_score?.length ? (
                    <details>
                      <summary
                        aria-label={`motivos de ${r.razao_social}`}
                        className="cursor-pointer font-mono text-xs text-accent"
                      >
                        motivos
                      </summary>
                      <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-muted-foreground">
                        {r.motivos_score.map((m, j) => (
                          <li key={`${j}-${m}`}>{m}</li>
                        ))}
                      </ul>
                    </details>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
