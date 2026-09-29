/** ICP (perfil de cliente ideal) escolhido pelo visitante — contrato de POST /leads. */

export type Porte = "micro" | "pequena" | "demais";

export const PORTES: Porte[] = ["micro", "pequena", "demais"];

export interface IcpParams {
  preferred_portes: Porte[];
  target_min_age_years: number;
  target_full_age_years: number;
  target_min_capital: number;
  target_max_capital: number;
  w_porte: number;
  w_age: number;
  w_capital: number;
  w_rede: number;
  w_dominio: number;
  target_min_estabelecimentos: number;
  mei_factor: number;
}

export interface PerfilIcp {
  id: string;
  nome: string;
  descricao: string;
  params: IcpParams;
}

const MEI = 0.5;

export const PERFIS: PerfilIcp[] = [
  {
    id: "estabelecida",
    nome: "Estabelecida",
    descricao: "Porte médio ou maior, com anos de estrada e capital sólido.",
    params: {
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
      mei_factor: MEI,
    },
  },
  {
    id: "pequeno-local",
    nome: "Pequeno negócio local",
    descricao: "Micro e pequenas empresas jovens, com capital modesto.",
    params: {
      preferred_portes: ["micro", "pequena"],
      target_min_age_years: 1,
      target_full_age_years: 5,
      target_min_capital: 10_000,
      target_max_capital: 500_000,
      w_porte: 40,
      w_age: 30,
      w_capital: 30,
      w_rede: 0,
      w_dominio: 0,
      target_min_estabelecimentos: 2,
      mei_factor: MEI,
    },
  },
  {
    id: "rede",
    nome: "Rede em expansão",
    descricao: "Empresas com mais de uma unidade ativa: rede pesa mais que porte.",
    params: {
      preferred_portes: ["pequena", "demais"],
      target_min_age_years: 3,
      target_full_age_years: 15,
      target_min_capital: 100_000,
      target_max_capital: 20_000_000,
      w_porte: 20,
      w_age: 20,
      w_capital: 20,
      w_rede: 40,
      w_dominio: 0,
      target_min_estabelecimentos: 2,
      mei_factor: MEI,
    },
  },
  {
    id: "digital",
    nome: "Negócio digital",
    descricao: "E-mail em domínio próprio como sinal forte de presença digital.",
    params: {
      preferred_portes: ["pequena", "demais"],
      target_min_age_years: 1,
      target_full_age_years: 8,
      target_min_capital: 20_000,
      target_max_capital: 5_000_000,
      w_porte: 20,
      w_age: 20,
      w_capital: 20,
      w_rede: 0,
      w_dominio: 40,
      target_min_estabelecimentos: 2,
      mei_factor: MEI,
    },
  },
];

export function perfilPadrao(): PerfilIcp {
  return PERFIS[0];
}

export function copiarParams(p: IcpParams): IcpParams {
  return { ...p, preferred_portes: [...p.preferred_portes] };
}

export function somaPesos(p: IcpParams): number {
  return p.w_porte + p.w_age + p.w_capital + p.w_rede + p.w_dominio;
}

function fora(v: number, min: number, max: number): boolean {
  return !Number.isFinite(v) || v < min || v > max;
}

/** Mesmos limites de ``api/icp.py``; ``null`` quando válido. */
export function validarIcp(p: IcpParams): string | null {
  const portes = p.preferred_portes;
  if (portes.length < 1 || new Set(portes).size !== portes.length || portes.some((x) => !PORTES.includes(x))) {
    return "Escolha ao menos um porte alvo.";
  }
  if (fora(p.target_min_age_years, 0, 50) || !Number.isInteger(p.target_min_age_years)) {
    return "Idade mínima: um número inteiro de 0 a 50 anos.";
  }
  if (
    fora(p.target_full_age_years, p.target_min_age_years, 60) ||
    !Number.isInteger(p.target_full_age_years)
  ) {
    return "Idade plena: inteiro entre a idade mínima e 60 anos.";
  }
  if (fora(p.target_min_capital, 1_000, 1_000_000_000)) {
    return "Capital mínimo: de R$ 1 mil a R$ 1 bi.";
  }
  if (fora(p.target_max_capital, p.target_min_capital, 10_000_000_000)) {
    return "Capital teto: entre o capital mínimo e R$ 10 bi.";
  }
  const pesos = [p.w_porte, p.w_age, p.w_capital, p.w_rede, p.w_dominio];
  if (pesos.some((w) => fora(w, 0, 100))) return "Cada peso vai de 0 a 100.";
  if (somaPesos(p) <= 0) return "Os pesos não podem ser todos zero.";
  if (fora(p.target_min_estabelecimentos, 2, 100) || !Number.isInteger(p.target_min_estabelecimentos)) {
    return "Rede: mínimo de 2 a 100 estabelecimentos.";
  }
  if (fora(p.mei_factor, 0, 1)) return "Fator MEI: de 0 a 1.";
  return null;
}

function reaisCurto(v: number): string {
  const fmt = (n: number) => n.toLocaleString("pt-BR", { maximumFractionDigits: 1 });
  if (v >= 1_000_000_000) return `R$ ${fmt(v / 1_000_000_000)} bi`;
  if (v >= 1_000_000) return `R$ ${fmt(v / 1_000_000)} mi`;
  if (v >= 1_000) return `R$ ${fmt(v / 1_000)} mil`;
  return `R$ ${fmt(v)}`;
}

/** Linhas curtas (mono) que resumem o perfil no cartão. */
export function resumoPerfil(p: IcpParams): string[] {
  const linhas = [
    `porte ${p.preferred_portes.join(", ")}`,
    `${p.target_min_age_years}–${p.target_full_age_years} anos`,
    `${reaisCurto(p.target_min_capital)} – ${reaisCurto(p.target_max_capital)}`,
  ];
  if (p.w_rede > 0) linhas.push(`rede (${p.target_min_estabelecimentos}+ unid.)`);
  if (p.w_dominio > 0) linhas.push("domínio próprio");
  return linhas;
}
