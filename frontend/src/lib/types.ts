import type { IcpParams } from "./icp";

export interface LeadFilters {
  cnae_query?: string | null;
  cnae_codes: string[];
  ufs: string[];
  municipio_ids: string[];
  municipio_names: string[];
  min_age_years?: number | null;
  max_age_years?: number | null;
  min_capital?: number | null;
  portes: string[];
  include_mei: boolean;
  min_estabelecimentos?: number | null;
  regimes: string[];
  bairros: string[];
  cep_centro?: string | null;
  raio_km?: number | null;
  com_dominio_proprio: boolean;
  limit: number;
}

export interface LeadRow {
  cnpj_basico?: string;
  razao_social: string;
  nome_fantasia?: string | null;
  sigla_uf?: string | null;
  id_municipio?: string | null;
  municipio?: string | null;
  cnae_fiscal_principal?: string | null;
  data_inicio_atividade?: string | null;
  capital_social?: number | null;
  porte?: string | null;
  score?: number | null;
  motivos_score?: string[];
}

export interface LeadsResponse {
  refused: boolean;
  refusal_reason: string | null;
  filters: LeadFilters | null;
  cnae_matches: [string, string, number][];
  municipio_resolution: Record<string, string[]>;
  snapshot: Record<string, string>;
  rows: LeadRow[];
  bytes_processed: number;
  bytes_billed: number;
  estimated_cost_usd: number;
  latency_ms: number;
  timings_ms: Record<string, number>;
  model: string;
  policy: string;
  request_normalized: string;
  warnings: string[];
  query_sql: string;
  cached: boolean;
  cache_mode: boolean;
  /** ICP efetivamente usado (pesos normalizados para 100). */
  icp?: IcpParams;
}

export interface ApiErrorBody {
  error: string;
  reason: string;
}

export interface HealthResponse {
  status: string;
  version: string;
  cache_mode: boolean;
  budget_remaining_bytes: number;
}

export interface ConfigResponse {
  turnstile_site_key: string | null;
}

export interface MetricEntry {
  suite?: string;
  date?: string;
  commit?: string;
  golden?: string;
  metrics?: Record<string, number>;
}

export interface MetricsResponse {
  thresholds: Record<string, number>;
  extraction: MetricEntry[];
  cnae: MetricEntry[];
  e2e: MetricEntry[];
}
