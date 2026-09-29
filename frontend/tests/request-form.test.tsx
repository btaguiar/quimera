import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { RequestForm } from "@/components/RequestForm";

const exemplos = ["padarias artesanais em Curitiba", "transportadoras em São Paulo"];

function renderForm(overrides: Partial<ComponentProps<typeof RequestForm>> = {}) {
  const onChange = vi.fn();
  const onSubmit = vi.fn();
  render(
    <RequestForm
      value=""
      onChange={onChange}
      onSubmit={onSubmit}
      loading={false}
      examples={exemplos}
      turnstileSlot={<div data-testid="turnstile" />}
      {...overrides}
    />,
  );
  return { onChange, onSubmit };
}

describe("RequestForm", () => {
  it("digitar acumula no onChange e envia o pedido", async () => {
    const user = userEvent.setup();
    const { onChange, onSubmit } = renderForm();
    const textarea = screen.getByLabelText(/pedido/i);
    await user.type(textarea, "padarias");
    expect(onChange).toHaveBeenLastCalledWith("padarias");
    await user.click(screen.getByRole("button", { name: /analisar/i }));
    expect(onSubmit).toHaveBeenCalledOnce();
    expect(onSubmit).toHaveBeenCalledWith("padarias");
  });

  it("contador acompanha o texto digitado", async () => {
    const user = userEvent.setup();
    renderForm();
    const textarea = screen.getByLabelText(/pedido/i);
    await user.type(textarea, "padarias");
    expect(textarea).toHaveValue("padarias");
    expect(screen.getByText("8/500")).toBeInTheDocument();
  });

  it("chips longos são aparados no limite de 500", async () => {
    const user = userEvent.setup();
    const longo = "x".repeat(520);
    renderForm({ examples: [longo] });
    await user.click(screen.getByRole("button", { name: longo }));
    expect(screen.getByText("500/500")).toBeInTheDocument();
  });

  it("limpa o erro ao digitar e marca o campo como inválido", async () => {
    const user = userEvent.setup();
    renderForm({ value: "  " });
    await user.click(screen.getByRole("button", { name: /analisar/i }));
    expect(screen.getByRole("status")).toHaveTextContent(/escreva um pedido/i);
    expect(screen.getByLabelText(/pedido/i)).toHaveAttribute("aria-invalid", "true");
    await user.type(screen.getByLabelText(/pedido/i), "x");
    expect(screen.queryByText(/escreva um pedido/i)).not.toBeInTheDocument();
  });

  it("chips de exemplo preenchem o textarea", async () => {
    const user = userEvent.setup();
    const { onChange } = renderForm({ value: "" });
    await user.click(screen.getByRole("button", { name: exemplos[1] }));
    expect(onChange).toHaveBeenCalledWith(exemplos[1]);
  });

  it("bloqueia envio vazio e mostra aviso", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderForm({ value: "  " });
    await user.click(screen.getByRole("button", { name: /analisar/i }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent(/escreva um pedido/i);
  });

  it("desabilita o botão durante o loading", () => {
    renderForm({ loading: true, value: "x" });
    expect(screen.getByRole("button", { name: /analisando/i })).toBeDisabled();
  });

  it("mostra o contador com o tamanho do valor", () => {
    renderForm({ value: "abc" });
    expect(screen.getByText("3/500")).toBeInTheDocument();
  });
});
