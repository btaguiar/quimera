import type { LeadsResponse } from "@/lib/types";

export function CnaeList({ matches }: { matches: LeadsResponse["cnae_matches"] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="pb-2 text-left font-mono text-xs text-muted-foreground">
          códigos escolhidos por similaridade de embeddings (top-k)
        </caption>
        <thead>
          <tr className="border-b border-foreground/20 text-left font-mono text-xs uppercase tracking-widest text-muted-foreground">
            <th className="py-2 pr-4">Código</th>
            <th className="py-2 pr-4">Descrição</th>
            <th className="py-2 text-right">Simil.</th>
          </tr>
        </thead>
        <tbody>
          {matches.map(([codigo, descricao, simil]) => (
            <tr key={codigo} className="border-b border-border">
              <td className="py-2 pr-4 font-mono">{codigo}</td>
              <td className="py-2 pr-4">{descricao}</td>
              <td className="py-2 text-right font-mono">{simil.toFixed(3).replace(".", ",")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
