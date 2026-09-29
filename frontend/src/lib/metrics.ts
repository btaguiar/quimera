import type { MetricEntry } from "./types";

export function selectUltima(lista: MetricEntry[] | undefined): MetricEntry | null {
  return lista && lista.length ? lista[lista.length - 1] : null;
}

/** Regra do metrics.js atual: golden com 20+ casos → qualquer 20+ → última. */
export function selectE2e(lista: MetricEntry[] | undefined): MetricEntry | null {
  if (!lista || !lista.length) return null;
  // `e &&` é uma guarda extra de segurança deliberada — o filtro legado do metrics.js não a tinha.
  const principal = lista.filter(
    (e) => e && e.golden === "golden_e2e.jsonl" && (e.metrics?.n_cases ?? 0) >= 20,
  );
  if (principal.length) return principal[principal.length - 1];
  const cheios = lista.filter((e) => e && (e.metrics?.n_cases ?? 0) >= 20);
  if (cheios.length) return cheios[cheios.length - 1];
  return selectUltima(lista);
}
