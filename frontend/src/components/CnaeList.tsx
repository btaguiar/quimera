import type { LeadsResponse } from "@/lib/types";

export function CnaeList({ matches }: { matches: LeadsResponse["cnae_matches"] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="pb-3 text-left text-xs text-faint">
          códigos escolhidos por similaridade de embeddings (top-k)
        </caption>
        <thead>
          <tr className="border-b border-line-strong text-left text-xs text-faint">
            <th className="py-2 pr-4 font-normal" scope="col">
              Código
            </th>
            <th className="py-2 pr-4 font-normal" scope="col">
              Descrição
            </th>
            <th className="py-2 text-right font-normal" scope="col">
              Simil.
            </th>
          </tr>
        </thead>
        <tbody>
          {matches.map(([codigo, descricao, simil]) => (
            <tr key={codigo} className="border-b border-border last:border-b-0">
              <td className="py-2.5 pr-4 font-mono text-accent">{codigo}</td>
              <td className="py-2.5 pr-4 text-muted-foreground">{descricao}</td>
              <td className="py-2.5 text-right font-mono">{simil.toFixed(3).replace(".", ",")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
