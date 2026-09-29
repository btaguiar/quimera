import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  NetworkError,
  TimeoutError,
  fetchConfig,
  fetchMetrics,
  fetchHealth,
  submitLead,
} from "@/lib/api";

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("submitLead", () => {
  it("envia request e token e devolve o payload", async () => {
    const payload = { refused: false, rows: [], cached: false, cache_mode: false };
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(payload));
    const out = await submitLead("padarias em Curitiba", "tok-1");
    expect(fetch).toHaveBeenCalledWith(
      "/leads",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ request: "padarias em Curitiba", turnstile: "tok-1" }),
      }),
    );
    expect(out).toEqual(payload);
  });

  it("omite turnstile quando nulo", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ refused: false }));
    await submitLead("padarias", null);
    expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]!.body as string)).toEqual({
      request: "padarias",
    });
  });

  it("lança ApiError com o reason do servidor", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ error: "rate limit", reason: "limite de 10 requisições" }, 429),
    );
    await expect(submitLead("x", null)).rejects.toMatchObject({
      status: 429,
      body: { error: "rate limit", reason: "limite de 10 requisições" },
    });
  });

  it("lança NetworkError quando o fetch falha", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const err = await submitLead("x", null).catch((e) => e);
    expect(err).toBeInstanceOf(NetworkError);
    expect((err as NetworkError).message).toBe("falha de rede");
  });

  it("propaga abort sem virar NetworkError", async () => {
    const abort = new DOMException("aborted", "AbortError");
    vi.mocked(fetch).mockRejectedValueOnce(abort);
    await expect(submitLead("x", null, AbortSignal.abort())).rejects.toBe(abort);
  });
});

describe("submitLead — timeout do cliente", () => {
  // fetch que só termina quando o signal aborta (servidor travado).
  function hangingFetch() {
    vi.mocked(fetch).mockImplementationOnce(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        }),
    );
  }

  afterEach(() => {
    vi.useRealTimers();
  });

  it("servidor travado vira TimeoutError com os segundos do limite", async () => {
    vi.useFakeTimers();
    hangingFetch();
    const pending = submitLead("x", null, undefined, 90_000).catch((e) => e);
    await vi.advanceTimersByTimeAsync(90_000);
    const err = await pending;
    expect(err).toBeInstanceOf(TimeoutError);
    expect((err as TimeoutError).seconds).toBe(90);
  });

  it("resposta antes do limite não dispara o timeout", async () => {
    vi.useFakeTimers();
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ refused: false }));
    await expect(submitLead("x", null, undefined, 90_000)).resolves.toEqual({ refused: false });
    expect(vi.getTimerCount()).toBe(0);
  });

  it("abort de quem chama continua sendo AbortError, não timeout", async () => {
    hangingFetch();
    const ctl = new AbortController();
    const pending = submitLead("x", null, ctl.signal).catch((e) => e);
    ctl.abort();
    const err = await pending;
    expect(err).not.toBeInstanceOf(TimeoutError);
    expect((err as DOMException).name).toBe("AbortError");
  });
});

describe("fetchHealth / fetchMetrics", () => {
  it("devolvem o JSON das rotas", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse({ status: "ok", version: "0.1.0" }))
      .mockResolvedValueOnce(jsonResponse({ thresholds: {}, extraction: [], cnae: [], e2e: [] }));
    expect((await fetchHealth()).version).toBe("0.1.0");
    expect((await fetchMetrics()).e2e).toEqual([]);
  });

  it("ApiError expõe status e body", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ error: "e", reason: "r" }, 500));
    const err = await fetchHealth().catch((e) => e as ApiError);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(500);
    expect((err as ApiError).body?.reason).toBe("r");
  });
});

describe("fetchConfig", () => {
  it("devolve o JSON de /config e encaminha o signal", async () => {
    const signal = AbortSignal.abort();
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ turnstile_site_key: "site-key" }));
    const out = await fetchConfig(signal);
    expect(fetch).toHaveBeenCalledWith("/config", { signal });
    expect(out.turnstile_site_key).toBe("site-key");
  });
});

describe("parse", () => {
  it("lança NetworkError em 200 com JSON inválido (não resolve null)", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response("<html>oops</html>", { status: 200 }));
    const err = await fetchHealth().catch((e) => e);
    expect(err).toBeInstanceOf(NetworkError);
  });

  it("lança ApiError com body null quando o erro tem corpo ilegível", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response("<html>oops</html>", { status: 500 }));
    const err = await fetchHealth().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(500);
    expect((err as ApiError).body).toBeNull();
  });

  it("propaga abort que acontece durante a leitura do body", async () => {
    const abort = new DOMException("aborted", "AbortError");
    const resp = {
      ok: true,
      status: 200,
      json: () => Promise.reject(abort),
    } as unknown as Response;
    vi.mocked(fetch).mockResolvedValueOnce(resp);
    await expect(fetchHealth()).rejects.toBe(abort);
  });
});

describe("Retry-After", () => {
  it("429 com Retry-After expõe os segundos no ApiError", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ error: "rate limit", reason: "limite" }), {
        status: 429,
        headers: { "Content-Type": "application/json", "Retry-After": "30" },
      }),
    );
    const err = (await submitLead("x", null).catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.retryAfter).toBe(30);
  });

  it("sem Retry-After o campo fica null", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ error: "rate limit", reason: "limite" }, 429),
    );
    const err = (await submitLead("x", null).catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.retryAfter).toBeNull();
  });
});
