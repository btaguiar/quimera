import { describe, expect, it } from "vitest";
import { selectE2e, selectUltima } from "@/lib/metrics";
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
