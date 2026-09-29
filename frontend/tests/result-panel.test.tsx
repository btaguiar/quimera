import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ResultPanel } from "@/components/ResultPanel";
import type { LeadsResponse } from "@/lib/types";

const base: LeadsResponse = {
  refused: false,
  refusal_reason: null,
  filters: {
    cnae_query: "clínicas odontológicas",
    cnae_codes: ["8630-5/01"],
    ufs: ["SP"],
    municipio_ids: ["3547807"],
    municipio_names: ["Santo André"],
    min_age_years: 2,
    max_age_years: null,
    min_capital: null,
    portes: ["pequena"],
    include_mei: false,
    min_estabelecimentos: null,
    regimes: [],
    bairros: [],
    cep_centro: null,
    raio_km: null,
    com_dominio_proprio: false,
    limit: 50,
  },
  cnae_matches: [["8630-5/01", "Atividade médica ambulatorial odontológica", 0.92]],
  municipio_resolution: {},
  snapshot: { "quimera.leads": "2026-09-01" },
  rows: [],
  bytes_processed: 33 * 1024 ** 2,
  bytes_billed: 33 * 1024 ** 2,
  estimated_cost_usd: 0.0002,
  latency_ms: 4123.4,
  timings_ms: { extract: 1200, query: 800 },
  model: "gemini-2.5-flash",
  policy: "public",
  request_normalized: "clinicas odontologicas",
  warnings: ["Cerca de 9% dos estabelecimentos não têm coordenada."],
  query_sql: "SELECT * FROM `quimera.leads` WHERE sigla_uf = @uf",
  cached: true,
  cache_mode: false,
};

describe("ResultPanel", () => {
  it("mostra interpretação, CNAEs e SQL com valores medidos em mono", () => {
    render(<ResultPanel data={base} browserMs={1.2} />);
    expect(screen.getByText(/interpretação/i)).toBeInTheDocument();
    expect(screen.getByText("Santo André")).toBeInTheDocument();
    expect(screen.getByText("8630-5/01")).toBeInTheDocument();
    expect(screen.getByText(/0,920/)).toBeInTheDocument();
    expect(screen.getByText(/SELECT \* FROM/)).toBeInTheDocument();
    expect(screen.getByText("2026-09-01")).toBeInTheDocument();
    expect(screen.getByText(/em cache/i)).toBeInTheDocument();
  });

  it("renderiza ressalvas quando houver", () => {
    render(<ResultPanel data={base} browserMs={1.2} />);
    expect(screen.getByText(/9% dos estabelecimentos/)).toBeInTheDocument();
  });

  it("sem CNAEs não quebra", () => {
    render(<ResultPanel data={{ ...base, cnae_matches: [] }} browserMs={1.2} />);
    expect(screen.getByText(/interpretação/i)).toBeInTheDocument();
    expect(screen.queryByText(/classificação/i)).not.toBeInTheDocument();
  });
});
