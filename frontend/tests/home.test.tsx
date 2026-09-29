import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import Home from "@/pages/Home";
import { fetchConfig, fetchHealth, submitLead } from "@/lib/api";
import { TurnstileController, type ConsumeResult } from "@/lib/turnstile";
import type { ConfigResponse, HealthResponse, LeadsResponse } from "@/lib/types";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    fetchConfig: vi.fn(),
    fetchHealth: vi.fn(),
    submitLead: vi.fn(),
  };
});

vi.mock("@/lib/turnstile", () => ({
  TurnstileController: vi.fn(),
}));

function makeLeads(overrides: Partial<LeadsResponse> = {}): LeadsResponse {
  return {
    refused: false,
    refusal_reason: null,
    filters: null,
    cnae_matches: [],
    municipio_resolution: {},
    snapshot: {},
    rows: [],
    bytes_processed: 0,
    bytes_billed: 0,
    estimated_cost_usd: 0,
    latency_ms: 0,
    timings_ms: {},
    model: "modelo-teste",
    policy: "publica",
    request_normalized: "padarias",
    warnings: [],
    query_sql: "",
    cached: false,
    cache_mode: false,
    ...overrides,
  };
}

const HEALTH: HealthResponse = {
  status: "ok",
  version: "1.0.0",
  cache_mode: false,
  budget_remaining_bytes: 1024,
};

const CONFIG: ConfigResponse = { turnstile_site_key: "site-key-teste" };

function mockTurnstile(results: ConsumeResult[]) {
  let i = 0;
  const fake = {
    render: vi.fn(async () => {}),
    consume: vi.fn((): ConsumeResult => {
      const r = results[Math.min(i, results.length - 1)];
      i += 1;
      return r;
    }),
    destroy: vi.fn(),
    reset: vi.fn(),
  };
  vi.mocked(TurnstileController).mockImplementation(function () {
    return fake as unknown as TurnstileController;
  });
  return fake;
}

function renderHome() {
  return render(
    <MemoryRouter>
      <Home />
    </MemoryRouter>,
  );
}

async function search(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/pedido/i), "padarias artesanais");
  await user.click(screen.getByRole("button", { name: /^analisar$/i }));
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchHealth).mockResolvedValue(HEALTH);
  vi.mocked(fetchConfig).mockResolvedValue(CONFIG);
  vi.mocked(submitLead).mockResolvedValue(makeLeads());
});

describe("Home — fluxo de busca", () => {
  it("2º submit consecutivo envia novo token (turnstile de uso único)", async () => {
    const user = userEvent.setup();
    const fake = mockTurnstile([
      { ok: true, token: "tok-1" },
      { ok: true, token: "tok-2" },
      { ok: false, reason: "sem token" },
    ]);
    renderHome();

    await search(user);
    await screen.findByText(/nenhuma empresa atendida/i);

    await user.click(screen.getByRole("button", { name: /^analisar$/i }));
    await screen.findByText(/nenhuma empresa atendida/i);

    expect(vi.mocked(submitLead).mock.calls.map((c) => c[1])).toEqual(["tok-1", "tok-2"]);
    expect(fake.consume).toHaveBeenCalledTimes(2);
  });

  it("não envia POST sem token (consume ok:false mostra erro 401)", async () => {
    const user = userEvent.setup();
    const fake = mockTurnstile([{ ok: false, reason: "sem token" }]);
    renderHome();

    await search(user);

    expect(vi.mocked(submitLead)).not.toHaveBeenCalled();
    expect(fake.consume).toHaveBeenCalledTimes(1);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/não verificado|turnstile/i);
  });

  it("sem site key no /config (auth desligada) envia o POST sem token", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchConfig).mockResolvedValue({ turnstile_site_key: null });
    const fake = mockTurnstile([{ ok: false, reason: "sem token" }]);
    renderHome();

    await waitFor(() => expect(vi.mocked(fetchConfig)).toHaveBeenCalled());
    await search(user);
    await screen.findByText(/nenhuma empresa atendida/i);

    expect(vi.mocked(submitLead).mock.calls.map((c) => c[1])).toEqual([null]);
    expect(fake.consume).not.toHaveBeenCalled();
  });

  it("re-busca /health após a busca (orçamento atualizado)", async () => {
    const user = userEvent.setup();
    mockTurnstile([{ ok: true, token: "tok-1" }]);
    renderHome();

    await waitFor(() => expect(vi.mocked(fetchHealth)).toHaveBeenCalledTimes(1));

    await search(user);
    await screen.findByText(/nenhuma empresa atendida/i);
    await waitFor(() => expect(vi.mocked(fetchHealth)).toHaveBeenCalledTimes(2));
  });
});
