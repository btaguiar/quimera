import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ResultPanel } from "@/components/ResultPanel";
import { SqlBlock } from "@/components/SqlBlock";
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
    render(<ResultPanel data={base} browserSeconds={1.2} />);
    expect(screen.getByText(/interpretação/i)).toBeInTheDocument();
    expect(screen.getByText("Santo André")).toBeInTheDocument();
    expect(screen.getByText("8630-5/01")).toBeInTheDocument();
    expect(screen.getByText("8630-5/01")).toHaveClass("font-mono");
    expect(screen.getByText(/0,920/)).toBeInTheDocument();
    expect(screen.getByText(/SELECT \* FROM/)).toBeInTheDocument();
    expect(screen.getByText("2026-09-01")).toBeInTheDocument();
    expect(screen.getByText(/em cache/i)).toBeInTheDocument();
  });

  it("renderiza ressalvas quando houver", () => {
    render(<ResultPanel data={base} browserSeconds={1.2} />);
    expect(screen.getByText(/9% dos estabelecimentos/)).toBeInTheDocument();
  });

  it("sem CNAEs não quebra", () => {
    render(<ResultPanel data={{ ...base, cnae_matches: [] }} browserSeconds={1.2} />);
    expect(screen.getByText(/interpretação/i)).toBeInTheDocument();
    expect(screen.queryByText(/classificação/i)).not.toBeInTheDocument();
  });

  it("sem filters esconde a seção de interpretação", () => {
    render(<ResultPanel data={{ ...base, filters: null }} browserSeconds={1.2} />);
    expect(screen.queryByText(/interpretação/i)).not.toBeInTheDocument();
  });
});

function stubClipboard(writeText: ReturnType<typeof vi.fn>) {
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
    writable: true,
  });
}

afterEach(() => {
  Reflect.deleteProperty(navigator, "clipboard");
});

describe("SqlBlock", () => {
  it("mostra 'copiado' após cópia bem-sucedida", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);
    render(<SqlBlock sql="SELECT 1" />);
    fireEvent.click(screen.getByRole("button", { name: /copiar sql/i }));
    expect(await screen.findByText("copiado")).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith("SELECT 1");
  });

  it("mostra falha em pt-BR quando a cópia é rejeitada", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("negado"));
    stubClipboard(writeText);
    render(<SqlBlock sql="SELECT 1" />);
    fireEvent.click(screen.getByRole("button", { name: /copiar sql/i }));
    expect(
      await screen.findByText(/não foi possível copiar — selecione o SQL manualmente/),
    ).toBeInTheDocument();
    expect(screen.queryByText("copiado")).not.toBeInTheDocument();
  });

  it("mostra falha quando clipboard não existe", () => {
    stubClipboard(undefined as unknown as ReturnType<typeof vi.fn>);
    Reflect.deleteProperty(navigator, "clipboard");
    render(<SqlBlock sql="SELECT 1" />);
    fireEvent.click(screen.getByRole("button", { name: /copiar sql/i }));
    expect(
      screen.getByText(/não foi possível copiar — selecione o SQL manualmente/),
    ).toBeInTheDocument();
  });

  it("troca de sql reinicia o rótulo do botão", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);
    const { rerender } = render(<SqlBlock sql="SELECT 1" />);
    fireEvent.click(screen.getByRole("button", { name: /copiar sql/i }));
    expect(await screen.findByText("copiado")).toBeInTheDocument();
    rerender(<SqlBlock sql="SELECT 2" />);
    expect(screen.getByRole("button", { name: /copiar sql/i })).toBeInTheDocument();
    expect(screen.queryByText("copiado")).not.toBeInTheDocument();
    expect(screen.queryByText(/não foi possível copiar/)).not.toBeInTheDocument();
  });
});
