import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { RankingTable } from "@/components/RankingTable";
import { CostSummary } from "@/components/CostSummary";
import type { LeadRow, LeadsResponse } from "@/lib/types";

const rows: LeadRow[] = [
  {
    razao_social: "CLINICA ALFA",
    nome_fantasia: null,
    sigla_uf: "SP",
    municipio: "Santo André",
    cnae_fiscal_principal: "8630-5/01",
    data_inicio_atividade: "2015-01-10",
    capital_social: 100000,
    porte: "pequena",
    score: 87,
    motivos_score: ["idade 11 anos"],
  },
  {
    razao_social: "CLINICA BETA",
    nome_fantasia: "Beta Odonto",
    sigla_uf: "SP",
    municipio: "Santo André",
    cnae_fiscal_principal: "8630-5/01",
    data_inicio_atividade: "2024-01-10",
    capital_social: 1000,
    porte: "micro",
    score: 42,
    motivos_score: ["idade 2 anos"],
  },
];

describe("RankingTable", () => {
  it("ordena como chega (a ordem é a da nota) e mostra score em mono", () => {
    render(<RankingTable rows={rows} />);
    const corpo = screen.getAllByRole("rowgroup")[1];
    const linhas = within(corpo).getAllByRole("row");
    expect(linhas[0]).toHaveTextContent("CLINICA ALFA");
    expect(linhas[1]).toHaveTextContent("CLINICA BETA");
    expect(screen.getByText("87")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("10/01/2015")).toBeInTheDocument();
    expect(screen.getByText(/2 empresas/)).toBeInTheDocument();
  });

  it("vazio mostra convite, não tabela", () => {
    render(<RankingTable rows={[]} />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText(/nenhuma empresa/i)).toBeInTheDocument();
  });

  it("motivos ficam em details por linha", () => {
    render(<RankingTable rows={rows} />);
    expect(screen.getAllByText("motivos")).toHaveLength(2);
    expect(screen.getAllByText("idade 11 anos")).toHaveLength(1);
  });
});

describe("CostSummary", () => {
  it("mostra bytes, custo, latencia, timings, orcamento, modelo e cache_mode", () => {
    const data = {
      bytes_billed: 33 * 1024 ** 2,
      estimated_cost_usd: 0.000123,
      latency_ms: 4123.4,
      timings_ms: { extract: 1200.5, query: 800 },
      model: "gemini-2.5-flash",
      cache_mode: true,
      cached: false,
      warnings: [],
      rows: [],
    } as unknown as LeadsResponse;
    render(<CostSummary data={data} browserSeconds={1.23} budgetRemainingBytes={1024 ** 3} />);
    expect(screen.getByText("33,0 MB")).toBeInTheDocument();
    expect(screen.getByText("US$ 0,000123")).toBeInTheDocument();
    expect(screen.getByText("4.123 ms")).toBeInTheDocument();
    expect(screen.getByText("1,00 GB")).toBeInTheDocument();
    expect(screen.getByText("gemini-2.5-flash")).toBeInTheDocument();
    expect(screen.getByText(/modo cache/i)).toBeInTheDocument();
    expect(screen.getByText(/extract 1\.201 ms/)).toBeInTheDocument();
    expect(screen.getByText("1,2 s")).toBeInTheDocument();
  });
});
