import type { LeadRow } from "@/lib/types";

export function RankingTable({ rows }: { rows: LeadRow[] }) {
  if (!rows.length) return <p className="text-sm text-muted-foreground">Nenhuma empresa atendida ao pedido (ver ressalvas).</p>;
  return <p className="text-sm text-muted-foreground">{rows.length} empresas.</p>;
}
