import type { MetricEntry } from "./types";

/** Golden gerado por eval/sintetico/gerar.py: milhares de pedidos, limiares próprios. */
export const GOLDEN_SINTETICO = "golden_e2e_sintetico.jsonl";
/** Execuções menores (pilotos de 500) não representam a rodada em escala. */
export const MIN_CASOS_SINTETICO = 1000;

export function selectUltima(lista: MetricEntry[] | undefined): MetricEntry | null {
  return lista && lista.length ? lista[lista.length - 1] : null;
}

/** Regra do metrics.js atual: golden com 20+ casos → qualquer 20+ → última.
 * O sintético fica fora: tem limiares próprios e seção própria. */
export function selectE2e(lista: MetricEntry[] | undefined): MetricEntry | null {
  if (!lista || !lista.length) return null;
  // `e &&` é uma guarda extra de segurança deliberada — o filtro legado do metrics.js não a tinha.
  const curados = lista.filter((e) => e && e.golden !== GOLDEN_SINTETICO);
  const principal = curados.filter(
    (e) => e.golden === "golden_e2e.jsonl" && (e.metrics?.n_cases ?? 0) >= 20,
  );
  if (principal.length) return principal[principal.length - 1];
  const cheios = curados.filter((e) => (e.metrics?.n_cases ?? 0) >= 20);
  if (cheios.length) return cheios[cheios.length - 1];
  return selectUltima(curados);
}

/** Última rodada do golden sintético com pelo menos MIN_CASOS_SINTETICO casos. */
export function selectSintetico(lista: MetricEntry[] | undefined): MetricEntry | null {
  const rodadas = (lista ?? []).filter(
    (e) => e && e.golden === GOLDEN_SINTETICO && (e.metrics?.n_cases ?? 0) >= MIN_CASOS_SINTETICO,
  );
  return selectUltima(rodadas);
}

/** Meia-largura do intervalo de 95% de uma proporção (aproximação normal). */
export function margem95(p: number | undefined, n: number | undefined): number | null {
  if (p == null || !n || !Number.isFinite(p)) return null;
  return 1.96 * Math.sqrt((p * (1 - p)) / n);
}
