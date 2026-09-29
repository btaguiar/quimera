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

  constructor(status: number, body: ApiErrorBody | null) {
    super(body?.reason ?? `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

export class NetworkError extends Error {
  constructor() {
    super("falha de rede");
    this.name = "NetworkError";
  }
}

async function parse<T>(resp: Response): Promise<T> {
  const body = await resp.json().catch(() => null);
  if (!resp.ok) throw new ApiError(resp.status, body as ApiErrorBody | null);
  return body as T;
}

function get<T>(url: string, signal?: AbortSignal): Promise<T> {
  return fetch(url, { signal })
    .catch((err) => {
      if (err instanceof DOMException && err.name === "AbortError") throw err;
      throw new NetworkError();
    })
    .then((resp) => parse<T>(resp));
}

export function fetchConfig(): Promise<ConfigResponse> {
  return get<ConfigResponse>("/config");
}

export function fetchHealth(): Promise<HealthResponse> {
  return get<HealthResponse>("/health");
}

export function fetchMetrics(): Promise<MetricsResponse> {
  return get<MetricsResponse>("/metrics");
}

export function submitLead(
  request: string,
  turnstile: string | null,
  signal?: AbortSignal,
): Promise<LeadsResponse> {
  return fetch("/leads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(turnstile ? { request, turnstile } : { request }),
    signal,
  })
    .catch((err) => {
      if (err instanceof DOMException && err.name === "AbortError") throw err;
      throw new NetworkError();
    })
    .then((resp) => parse<LeadsResponse>(resp));
}
