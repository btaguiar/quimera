import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBanner, type ErrorState } from "@/components/StatusBanner";

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

  it("recusa não é erro: trata informativo", () => {
    render(<StatusBanner refusal="pedido recusado: dado pessoal" />);
    expect(screen.getByRole("status")).toHaveTextContent(/dado pessoal/i);
  });
});

describe("ErrorState", () => {
  it("é um discriminated union usável pelo Home", () => {
    const e: ErrorState = { kind: "network" };
    expect(e.kind).toBe("network");
  });
});
