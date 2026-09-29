import type { ReactNode } from "react";
import type { LeadFilters } from "@/lib/types";

/** Etiqueta de anotação: mesmo vocabulário do hero (rótulo tênue + valor). */
function chip(label: string, valor: string) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-sm bg-secondary px-2 py-1 font-mono text-xs">
      <span className="text-faint">{label}</span>
      <span className="text-foreground">{valor}</span>
    </span>
  );
}

export function FiltersBadge({ filters }: { filters: LeadFilters | null }) {
  if (!filters) return null;
  const chips: ReactNode[] = [];
  if (filters.cnae_query) chips.push(chip("atividade", filters.cnae_query));
  for (const uf of filters.ufs ?? []) chips.push(chip("uf", uf));
  for (const mun of filters.municipio_names ?? []) chips.push(chip("município", mun));
  if (filters.min_age_years != null) chips.push(chip("idade mín.", `${filters.min_age_years} anos`));
  if (filters.max_age_years != null) chips.push(chip("idade máx.", `${filters.max_age_years} anos`));
  if (filters.min_capital != null) chips.push(chip("capital mín.", String(filters.min_capital)));
  for (const p of filters.portes ?? []) chips.push(chip("porte", p));
  for (const b of filters.bairros ?? []) chips.push(chip("bairro", b));
  if (filters.cep_centro) chips.push(chip("raio", `${filters.cep_centro} + ${filters.raio_km ?? 5} km`));
  if (filters.regimes?.length) chips.push(chip("regime", filters.regimes.join(", ")));
  if (filters.com_dominio_proprio) chips.push(chip("domínio próprio", "sim"));
  if (filters.min_estabelecimentos != null)
    chips.push(chip("unidades mín.", String(filters.min_estabelecimentos)));
  chips.push(chip("limite", `${filters.limit} empresas`));
  return (
    <div>
      <ul className="flex flex-wrap gap-2">{chips.map((c, i) => <li key={i}>{c}</li>)}</ul>
      <p className="mt-3 text-xs text-faint">
        filtro aplicado pela policy pública: sem MEI, sem contato, sem pessoa física.
      </p>
    </div>
  );
}
