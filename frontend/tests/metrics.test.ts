import { describe, expect, it } from "vitest";
import {
  margem95,
  selectE2e,
  selectEscala,
  selectInedito,
  selectSintetico,
  selectUltima,
  varianteDoGolden,
} from "@/lib/metrics";
import type { MetricEntry } from "@/lib/types";

const entry = (o: Partial<MetricEntry>): MetricEntry => ({
  suite: "e2e",
  metrics: {},
  ...o,
});

describe("selectE2e", () => {
  it("prefere golden_e2e.jsonl com n_cases >= 20", () => {
    const lista = [
      entry({ golden: "outro.jsonl", metrics: { n_cases: 30 } }),
      entry({ golden: "golden_e2e.jsonl", metrics: { n_cases: 5 } }),
      entry({ golden: "golden_e2e.jsonl", metrics: { n_cases: 20 } }),
    ];
    expect(selectE2e(lista)?.metrics?.n_cases).toBe(20);
  });

  it("cai para qualquer execução com n_cases >= 20", () => {
    const lista = [
      entry({ metrics: { n_cases: 21 } }),
      entry({ metrics: { n_cases: 22 } }),
      entry({ metrics: { n_cases: 3 } }),
    ];
    expect(selectE2e(lista)?.metrics?.n_cases).toBe(22);
  });

  it("cai para a última quando nada tem 20 casos", () => {
    const lista = [entry({ metrics: { n_cases: 3 } }), entry({ metrics: { n_cases: 4 } })];
    expect(selectE2e(lista)?.metrics?.n_cases).toBe(4);
  });

  it("desempata goldens qualificados: o último vence", () => {
    const lista = [
      entry({ golden: "golden_e2e.jsonl", metrics: { n_cases: 25 } }),
      entry({ golden: "golden_e2e.jsonl", metrics: { n_cases: 30 } }),
    ];
    expect(selectE2e(lista)?.metrics?.n_cases).toBe(30);
  });

  it("golden com menos de 20 perde para não-golden com 20+", () => {
    const lista = [
      entry({ golden: "golden_e2e.jsonl", metrics: { n_cases: 10 } }),
      entry({ golden: "outro.jsonl", metrics: { n_cases: 21 } }),
    ];
    expect(selectE2e(lista)?.metrics?.n_cases).toBe(21);
  });

  it("devolve null sem lista", () => {
    expect(selectE2e(undefined)).toBeNull();
    expect(selectE2e([])).toBeNull();
  });
});

describe("selectUltima", () => {
  it("devolve o último item", () => {
    expect(selectUltima([entry({}), entry({ commit: "abc" })])?.commit).toBe("abc");
    expect(selectUltima([])).toBeNull();
  });
});

describe("golden sintético", () => {
  const sint = (n: number, commit = "x") =>
    entry({ golden: "golden_e2e_sintetico.jsonl", commit, metrics: { n_cases: n } });

  it("nunca ocupa o lugar do golden principal", () => {
    const lista = [entry({ golden: "golden_e2e.jsonl", metrics: { n_cases: 28 } }), sint(10000)];
    expect(selectE2e(lista)?.golden).toBe("golden_e2e.jsonl");
    expect(selectE2e([sint(10000)])).toBeNull();
  });

  it("pega a última rodada em escala e ignora pilotos pequenos", () => {
    const lista = [sint(10000, "a"), sint(500, "b")];
    expect(selectSintetico(lista)?.commit).toBe("a");
    expect(selectSintetico([sint(500)])).toBeNull();
    expect(selectSintetico(undefined)).toBeNull();
  });

  it("margem95 é a meia-largura do intervalo de 95%", () => {
    expect(margem95(0.92, 10000)).toBeCloseTo(0.0053, 4);
    expect(margem95(undefined, 10000)).toBeNull();
    expect(margem95(0.9, 0)).toBeNull();
  });
});

describe("conjunto inédito", () => {
  const rod = (golden: string, n: number, date: string) =>
    entry({ golden, date, metrics: { n_cases: n } });

  it("o painel em escala mostra a medição gerada mais recente", () => {
    const sint = rod("golden_e2e_sintetico.jsonl", 10000, "2026-09-30T02:49:23+00:00");
    const ined = rod("golden_e2e_inedito.jsonl", 1000, "2026-10-01T01:49:07+00:00");
    expect(selectEscala([ined, sint])?.golden).toBe("golden_e2e_inedito.jsonl");
    expect(selectEscala([sint])?.golden).toBe("golden_e2e_sintetico.jsonl");
    expect(selectInedito([sint])).toBeNull();
    expect(selectEscala([])).toBeNull();
  });

  it("inédito e reteste nunca ocupam o lugar do golden principal", () => {
    const lista = [
      rod("golden_e2e_inedito.jsonl", 1000, "b"),
      rod("golden_e2e_reteste.jsonl", 2800, "c"),
    ];
    expect(selectE2e(lista)).toBeNull();
  });

  it("variante escolhe os limiares certos", () => {
    expect(varianteDoGolden("golden_e2e_inedito.jsonl")).toBe("inedito");
    expect(varianteDoGolden("golden_e2e_sintetico.jsonl")).toBe("sintetico");
    expect(varianteDoGolden("golden_e2e.jsonl")).toBeNull();
  });
});
