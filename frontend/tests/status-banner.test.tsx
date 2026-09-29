import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBanner, toErrorState, type ErrorState } from "@/components/StatusBanner";
import { ApiError, NetworkError, TimeoutError } from "@/lib/api";

describe("StatusBanner", () => {
  it("401 pede novo captcha", () => {
    render(<StatusBanner error={{ kind: "http", status: 401, body: null, retryAfter: null }} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/captcha/i);
  });

  it("429 mostra Retry-After quando presente", () => {
    render(<StatusBanner error={{ kind: "http", status: 429, body: null, retryAfter: 30 }} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/30 s/i);
  });

  it("503 mostra o reason do servidor (as 4 variantes)", () => {
    const variantes = [
      "orçamento diário esgotado; apenas pedidos já vistos são respondidos",
      "orçamento diário restante não cobre esta consulta",
      "consulta excede o teto de bytes",
      "a base de empresas está sendo atualizada",
    ];
    for (const reason of variantes) {
      const { unmount } = render(
        <StatusBanner error={{ kind: "http", status: 503, body: { error: "x", reason }, retryAfter: null }} />,
      );
      expect(screen.getByRole("alert")).toHaveTextContent(reason);
      unmount();
    }
  });

  it("502 e 500 usam o reason com fallback", () => {
    render(<StatusBanner error={{ kind: "http", status: 502, body: null, retryAfter: null }} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/extração|reformular/i);
  });

  it("rede mostra botão de tentar de novo", () => {
    const onRetry = () => {};
    render(<StatusBanner error={{ kind: "network" }} onRetry={onRetry} />);
    expect(screen.getByRole("button", { name: /tentar de novo/i })).toBeInTheDocument();
  });

  it("timeout do cliente diz quanto esperou e oferece tentar de novo", () => {
    render(<StatusBanner error={{ kind: "timeout", seconds: 90 }} onRetry={() => {}} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/não respondeu em 90 s/i);
    expect(screen.getByRole("button", { name: /tentar de novo/i })).toBeInTheDocument();
  });

  it("recusa não é erro: trata informativo", () => {
    render(<StatusBanner refusal="pedido recusado: dado pessoal" />);
    expect(screen.getByRole("status")).toHaveTextContent(/dado pessoal/i);
  });

  it("reason malformado não derruba o banner e usa o fallback", () => {
    render(
      <StatusBanner
        error={{ kind: "http", status: 500, body: { error: "x", reason: 123 as never }, retryAfter: null }}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/erro interno/i);
  });

  it("429 com Retry-After zero mostra 0 s", () => {
    render(<StatusBanner error={{ kind: "http", status: 429, body: null, retryAfter: 0 }} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/aguarde 0 s/i);
  });

  it("recusa vazia mostra motivo genérico e a política", () => {
    render(<StatusBanner refusal="" />);
    expect(screen.getByRole("status")).toHaveTextContent(/pedido recusado/i);
    expect(screen.getByRole("status")).toHaveTextContent(/dado pessoal/i);
  });

  it("500 sem body mostra erro interno", () => {
    render(<StatusBanner error={{ kind: "http", status: 500, body: null, retryAfter: null }} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/erro interno/i);
  });

  it("422 sem body mostra pedido inválido", () => {
    render(<StatusBanner error={{ kind: "http", status: 422, body: null, retryAfter: null }} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/pedido inválido/i);
  });

  it("504 sem body mostra tempo limite", () => {
    render(<StatusBanner error={{ kind: "http", status: 504, body: null, retryAfter: null }} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/tempo limite/i);
  });

  it("reason do servidor vence o fallback do status", () => {
    render(
      <StatusBanner
        error={{
          kind: "http",
          status: 401,
          body: { error: "unauthorized", reason: "token expirado" },
          retryAfter: null,
        }}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("token expirado");
    expect(screen.getByRole("alert")).not.toHaveTextContent(/captcha/i);
  });

  it("reason vazio (só espaços) cai no fallback", () => {
    render(
      <StatusBanner
        error={{ kind: "http", status: 502, body: { error: "e", reason: "  " }, retryAfter: null }}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/extração|reformular/i);
  });

  it("429 sem Retry-After mostra alguns minutos", () => {
    render(<StatusBanner error={{ kind: "http", status: 429, body: null, retryAfter: null }} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/alguns minutos/i);
  });
});

describe("toErrorState", () => {
  it("NetworkError vira kind network", () => {
    expect(toErrorState(new NetworkError())).toEqual({ kind: "network" });
  });

  it("TimeoutError vira kind timeout com os segundos", () => {
    expect(toErrorState(new TimeoutError(90))).toEqual({ kind: "timeout", seconds: 90 });
  });

  it("ApiError carrega status, body e retryAfter", () => {
    const err = new ApiError(429, { error: "rate limit", reason: "limite" }, 30);
    const state: ErrorState = toErrorState(err);
    expect(state).toEqual({
      kind: "http",
      status: 429,
      body: { error: "rate limit", reason: "limite" },
      retryAfter: 30,
    });
  });

  it("erro desconhecido vira http 0 sem corpo", () => {
    expect(toErrorState(new Error("x"))).toEqual({
      kind: "http",
      status: 0,
      body: null,
      retryAfter: null,
    });
  });
});
