import type { LeadRow } from "@/lib/types";
import { fmtCapital, fmtData, fmtNumOrDash } from "@/lib/format";

const TH = "py-2.5 pr-4 font-normal";

export function RankingTable({ rows, perfil }: { rows: LeadRow[]; perfil?: string | null }) {
  if (!rows.length) {
    return (
      <p className="text-muted-foreground">
        Nenhuma empresa atendida ao pedido (ver ressalvas).
      </p>
    );
  }
  return (
    <div>
      <p className="mb-4 text-sm text-muted-foreground">
        {rows.length} {rows.length === 1 ? "empresa" : "empresas"} — ordenadas pela nota do ICP{perfil ? ` «${perfil}»` : ""}
      </p>
      <div className="relative -mx-4 overflow-x-auto px-4 sm:-mx-6 sm:px-6" tabIndex={0} role="region" aria-label="Ranking de empresas">
        <table className="w-full min-w-[52rem] text-sm">
          <thead>
            <tr className="border-b border-line-strong text-left text-xs text-faint">
              <th scope="col" className={`${TH} w-8`}>#</th>
              <th scope="col" className={TH}>Empresa</th>
              <th scope="col" className={TH}>Local</th>
              <th scope="col" className={TH}>CNAE</th>
              <th scope="col" className={TH}>Início</th>
              <th scope="col" className={`${TH} text-right`}>Capital (R$)</th>
              <th scope="col" className={TH}>Porte</th>
              <th scope="col" className={`${TH} text-right`}>Nota</th>
              <th scope="col" className="py-2.5 font-normal">
                <span className="sr-only">Motivos</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr
                key={`${r.razao_social}-${i}`}
                className="border-b border-border align-top transition-colors duration-150 last:border-b-0 hover:bg-secondary/60"
              >
                <td className="py-3.5 pr-4 font-mono text-faint">{i + 1}</td>
                <td className="py-3.5 pr-4">
                  <span className="font-medium">{r.razao_social}</span>
                  {r.nome_fantasia ? (
                    <span className="block text-xs text-muted-foreground">{r.nome_fantasia}</span>
                  ) : null}
                </td>
                <td className="py-3.5 pr-4 text-muted-foreground">
                  {r.municipio ?? "—"}/{r.sigla_uf ?? "—"}
                </td>
                <td className="py-3.5 pr-4 font-mono text-xs text-muted-foreground">{r.cnae_fiscal_principal ?? "—"}</td>
                <td className="py-3.5 pr-4 font-mono text-xs text-muted-foreground">{fmtData(r.data_inicio_atividade)}</td>
                <td className="py-3.5 pr-4 text-right font-mono text-muted-foreground">{fmtCapital(r.capital_social)}</td>
                <td className="py-3.5 pr-4 text-muted-foreground">{r.porte ?? "—"}</td>
                <td className="py-3.5 pr-4 text-right">
                  {r.score == null ? (
                    <span className="font-mono">—</span>
                  ) : (
                    <div className="flex items-center justify-end gap-2.5">
                      <span aria-hidden className="h-1 w-16 overflow-hidden rounded-full bg-surface-3">
                        <span
                          className="block h-full bg-accent"
                          style={{ width: `${Math.max(0, Math.min(100, r.score))}%` }}
                        />
                      </span>
                      <span className="w-7 font-mono text-accent">{fmtNumOrDash(r.score)}</span>
                    </div>
                  )}
                </td>
                <td className="py-3.5">
                  {r.motivos_score?.length ? (
                    <details className="group">
                      <summary
                        aria-label={`motivos de ${r.razao_social}`}
                        className="cursor-pointer list-none rounded-sm font-mono text-xs text-muted-foreground transition-colors duration-150 hover:text-foreground group-open:text-accent [&::-webkit-details-marker]:hidden"
                      >
                        motivos
                      </summary>
                      <ul className="mt-2 w-56 list-disc space-y-1 pl-4 text-xs text-muted-foreground marker:text-accent">
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
