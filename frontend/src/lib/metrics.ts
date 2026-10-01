import type { MetricEntry } from "./types";

/** Golden gerado por eval/sintetico/gerar.py: milhares de pedidos, limiares próprios. */
export const GOLDEN_SINTETICO = "golden_e2e_sintetico.jsonl";
/** Pedidos gerados com outra semente e nunca usados para ajustar o pipeline. */
export const GOLDEN_INEDITO = "golden_e2e_inedito.jsonl";
/** Goldens gerados por modelo (inclui o reteste das falhas): seção própria,
 * nunca no lugar do golden curado. */
const GERADOS = new Set([GOLDEN_SINTETICO, GOLDEN_INEDITO, "golden_e2e_reteste.jsonl"]);
/** Execuções menores (pilotos de 500) não representam a rodada em escala. */
export const MIN_CASOS_SINTETICO = 1000;

export function selectUltima(lista: MetricEntry[] | undefined): MetricEntry | null {
  return lista && lista.length ? lista[lista.length - 1] : null;
}

/** Regra do metrics.js atual: golden com 20+ casos → qualquer 20+ → última.
 * Os goldens gerados ficam fora: têm limiares e seções próprios. */
export function selectE2e(lista: MetricEntry[] | undefined): MetricEntry | null {
  if (!lista || !lista.length) return null;
  // `e &&` é uma guarda extra de segurança deliberada — o filtro legado do metrics.js não a tinha.
  const curados = lista.filter((e) => e && !GERADOS.has(e.golden ?? ""));
  const principal = curados.filter(
    (e) => e.golden === "golden_e2e.jsonl" && (e.metrics?.n_cases ?? 0) >= 20,
  );
  if (principal.length) return principal[principal.length - 1];
  const cheios = curados.filter((e) => (e.metrics?.n_cases ?? 0) >= 20);
  if (cheios.length) return cheios[cheios.length - 1];
  return selectUltima(curados);
}

function ultimaEmEscala(lista: MetricEntry[] | undefined, golden: string): MetricEntry | null {
  const rodadas = (lista ?? []).filter(
    (e) => e && e.golden === golden && (e.metrics?.n_cases ?? 0) >= MIN_CASOS_SINTETICO,
  );
  return selectUltima(rodadas);
}

/** Última rodada do golden sintético com pelo menos MIN_CASOS_SINTETICO casos. */
export function selectSintetico(lista: MetricEntry[] | undefined): MetricEntry | null {
  return ultimaEmEscala(lista, GOLDEN_SINTETICO);
}

/** Última rodada do conjunto inédito com pelo menos MIN_CASOS_SINTETICO casos. */
export function selectInedito(lista: MetricEntry[] | undefined): MetricEntry | null {
  return ultimaEmEscala(lista, GOLDEN_INEDITO);
}

/** A medição gerada mais recente (sintético ou inédito): é a do pipeline atual. */
export function selectEscala(lista: MetricEntry[] | undefined): MetricEntry | null {
  const candidatas = [selectSintetico(lista), selectInedito(lista)].filter(
    (e): e is MetricEntry => e != null,
  );
  if (!candidatas.length) return null;
  return candidatas.reduce((a, b) => ((b.date ?? "") > (a.date ?? "") ? b : a));
}

/** Sufixo dos limiares da variante (``e2e_<variante>_case_pass_rate``). */
export function varianteDoGolden(golden: string | undefined): "sintetico" | "inedito" | null {
  if (golden === GOLDEN_SINTETICO) return "sintetico";
  if (golden === GOLDEN_INEDITO) return "inedito";
  return null;
}

/** Meia-largura do intervalo de 95% de uma proporção (aproximação normal). */
export function margem95(p: number | undefined, n: number | undefined): number | null {
  if (p == null || !n || !Number.isFinite(p)) return null;
  return 1.96 * Math.sqrt((p * (1 - p)) / n);
}
