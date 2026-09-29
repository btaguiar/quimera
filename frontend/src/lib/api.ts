import type {
  ApiErrorBody,
  ConfigResponse,
  HealthResponse,
  LeadsResponse,
  MetricsResponse,
} from "./types";

export class ApiError extends Error {
  status: number;
  body: ApiErrorBody | null;
  retryAfter: number | null;

  constructor(status: number, body: ApiErrorBody | null, retryAfter: number | null = null) {
    super(body?.reason ?? `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
    this.retryAfter = retryAfter;
  }
}

export class NetworkError extends Error {
  constructor(message = "falha de rede") {
    super(message);
    this.name = "NetworkError";
  }
}

/** O cliente desistiu de esperar: nem resposta nem 504 do servidor chegaram. */
export class TimeoutError extends Error {
  seconds: number;

  constructor(seconds: number) {
    super(`sem resposta em ${seconds} s`);
    this.name = "TimeoutError";
    this.seconds = seconds;
  }
}

/** Acima do timeout do servidor (60 s): o 504 dele, com motivo, chega antes. */
export const LEADS_TIMEOUT_MS = 90_000;

function isAbortError(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

function mapFetchError(err: unknown): never {
  if (isAbortError(err)) throw err;
  throw new NetworkError();
}

function parseRetryAfter(resp: Response): number | null {
  const raw = resp.headers.get("Retry-After");
  if (raw == null) return null;
  const n = Number.parseInt(raw, 10);
  return Number.isNaN(n) ? null : n;
}

async function parse<T>(resp: Response): Promise<T> {
  let body: unknown;
  try {
    body = await resp.json();
  } catch (err) {
    if (isAbortError(err)) throw err;
    if (!resp.ok) throw new ApiError(resp.status, null, parseRetryAfter(resp));
    throw new NetworkError("JSON inválido na resposta");
  }
  if (!resp.ok) throw new ApiError(resp.status, body as ApiErrorBody | null, parseRetryAfter(resp));
  return body as T;
}

function get<T>(url: string, signal?: AbortSignal): Promise<T> {
  return fetch(url, { signal })
    .catch(mapFetchError)
    .then((resp) => parse<T>(resp));
}

export function fetchConfig(signal?: AbortSignal): Promise<ConfigResponse> {
  return get<ConfigResponse>("/config", signal);
}

export function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return get<HealthResponse>("/health", signal);
}

export function fetchMetrics(signal?: AbortSignal): Promise<MetricsResponse> {
  return get<MetricsResponse>("/metrics", signal);
}

export function submitLead(
  request: string,
  turnstile: string | null,
  signal?: AbortSignal,
  timeoutMs: number = LEADS_TIMEOUT_MS,
): Promise<LeadsResponse> {
  const ctl = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    ctl.abort();
  }, timeoutMs);
  const forwardAbort = () => ctl.abort();
  if (signal?.aborted) ctl.abort();
  else signal?.addEventListener("abort", forwardAbort, { once: true });

  return fetch("/leads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(turnstile ? { request, turnstile } : { request }),
    signal: ctl.signal,
  })
    .catch(mapFetchError)
    .then((resp) => parse<LeadsResponse>(resp))
    .catch((err: unknown) => {
      if (timedOut && isAbortError(err)) throw new TimeoutError(Math.round(timeoutMs / 1000));
      throw err;
    })
    .finally(() => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", forwardAbort);
    });
}
