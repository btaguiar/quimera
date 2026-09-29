import { describe, expect, it } from "vitest";
import { PERFIS, perfilPadrao, resumoPerfil, somaPesos, validarIcp, type IcpParams } from "@/lib/icp";

const base = (): IcpParams => ({ ...perfilPadrao().params, preferred_portes: [...perfilPadrao().params.preferred_portes] });

describe("perfis prontos", () => {
  it("são 4, com ids únicos, e todos passam na validação da API", () => {
    expect(PERFIS).toHaveLength(4);
    expect(new Set(PERFIS.map((p) => p.id)).size).toBe(4);
    for (const p of PERFIS) expect(validarIcp(p.params), p.id).toBeNull();
  });

  it("o padrão é o Estabelecida, igual ao ICPConfig() do backend", () => {
    const p = perfilPadrao();
    expect(p.id).toBe("estabelecida");
    expect(p.params).toEqual({
      preferred_portes: ["demais"],
      target_min_age_years: 2,
      target_full_age_years: 10,
      target_min_capital: 50_000,
      target_max_capital: 10_000_000,
      w_porte: 40,
      w_age: 30,
      w_capital: 30,
      w_rede: 0,
      w_dominio: 0,
      target_min_estabelecimentos: 2,
      mei_factor: 0.5,
    });
  });
});

describe("validarIcp (espelha a API)", () => {
  it.each<[string, Partial<IcpParams>]>([
    ["porte", { preferred_portes: [] }],
    ["idade", { target_min_age_years: 51 }],
    ["idade", { target_full_age_years: 1 }],
    ["capital", { target_min_capital: 999 }],
    ["capital", { target_max_capital: 40_000 }],
    ["peso", { w_porte: 101 }],
    ["pesos", { w_porte: 0, w_age: 0, w_capital: 0 }],
    ["estabelecimentos", { target_min_estabelecimentos: 1 }],
    ["MEI", { mei_factor: 1.2 }],
    ["idade", { target_min_age_years: Number.NaN }],
  ])("rejeita %s inválido", (trecho, patch) => {
    const erro = validarIcp({ ...base(), ...patch });
    expect(erro).not.toBeNull();
    expect(erro!.toLowerCase()).toContain(trecho.toLowerCase());
  });

  it("aceita pesos relativos (não precisam somar 100)", () => {
    expect(validarIcp({ ...base(), w_porte: 2, w_age: 1, w_capital: 1 })).toBeNull();
    expect(somaPesos({ ...base(), w_porte: 2, w_age: 1, w_capital: 1 })).toBe(4);
  });
});

describe("resumoPerfil", () => {
  it("resume porte, idade e capital em pt-BR", () => {
    expect(resumoPerfil(base())).toEqual(["porte demais", "2–10 anos", "R$ 50 mil – R$ 10 mi"]);
  });

  it("cita rede e domínio quando têm peso", () => {
    const r = resumoPerfil({ ...base(), w_rede: 40, w_dominio: 10 });
    expect(r).toContain("rede (2+ unid.)");
    expect(r).toContain("domínio próprio");
  });
});
