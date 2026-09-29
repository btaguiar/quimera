import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MetricSuite } from "@/components/MetricSuite";

const suite = {
  titulo: "Extração de filtros",
  meta: { date: "2026-09-28", commit: "abc1234" },
  linhas: [
    { rotulo: "Acerto por campo", medido: 0.87, limiar: 0.85 },
    { rotulo: "Recusa correta", medido: 1.0, limiar: 1.0 },
    { rotulo: "Acerto exato do conjunto", medido: 0.6, limiar: 0.9 },
    { rotulo: "Recusa indevida", medido: 0.01, limiar: null },
    { rotulo: "Casos", medido: 42, limiar: null, quantidade: true },
  ],
};

describe("MetricSuite", () => {
  it("marca acima e abaixo do limiar", () => {
    render(<MetricSuite numero={1} {...suite} />);
    expect(screen.getByText("87,0%")).toBeInTheDocument();
    expect(screen.getAllByText(/acima do limiar/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("abaixo do limiar")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText(/abc1234/)).toBeInTheDocument();
  });

  it("linha sem limiar não mostra estado", () => {
    render(<MetricSuite numero={3} titulo="Ponta a ponta" meta={{ date: "2026-09-28", commit: "x" }} linhas={[{ rotulo: "Casos", medido: 20, limiar: null, quantidade: true }]} />);
    expect(screen.queryByText(/limiar/)).not.toBeInTheDocument();
  });
});
