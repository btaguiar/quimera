import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, fetchMetrics, fetchHealth, submitLead } from "@/lib/api";

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
    await expect(submitLead("x", null)).rejects.toThrow("falha de rede");
  });

  it("propaga abort sem virar NetworkError", async () => {
    const abort = new DOMException("aborted", "AbortError");
    vi.mocked(fetch).mockRejectedValueOnce(abort);
    await expect(submitLead("x", null, AbortSignal.abort())).rejects.toBe(abort);
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
