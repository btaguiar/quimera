import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { IcpPicker } from "@/components/IcpPicker";
import { PERFIS, copiarParams, type IcpParams } from "@/lib/icp";

function Harness({ onParams }: { onParams?: (p: IcpParams) => void }) {
  const [perfilId, setPerfilId] = useState(PERFIS[0].id);
  const [params, setParams] = useState(copiarParams(PERFIS[0].params));
  return (
    <IcpPicker
      perfilId={perfilId}
      params={params}
      onSelect={(id) => {
        setPerfilId(id);
        setParams(copiarParams(PERFIS.find((p) => p.id === id)!.params));
      }}
      onChange={(p) => {
        setParams(p);
        onParams?.(p);
      }}
    />
  );
}

describe("IcpPicker", () => {
  it("mostra os 4 perfis como rádios, com o padrão marcado", () => {
    render(<Harness />);
    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(4);
    expect(screen.getByRole("radio", { name: /estabelecida/i })).toBeChecked();
  });

  it("escolher outro perfil marca o rádio", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("radio", { name: /pequeno negócio local/i }));
    expect(screen.getByRole("radio", { name: /pequeno negócio local/i })).toBeChecked();
  });

  it("controles ficam escondidos até 'ajustar este perfil'", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const botao = screen.getByRole("button", { name: /ajustar este perfil/i });
    expect(botao).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByLabelText(/idade mínima/i)).not.toBeInTheDocument();
    await user.click(botao);
    expect(botao).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText(/idade mínima/i)).toHaveValue(2);
  });

  it("ajustar um peso marca o perfil como ajustado e 'restaurar' volta ao original", async () => {
    const user = userEvent.setup();
    const onParams = vi.fn();
    render(<Harness onParams={onParams} />);
    await user.click(screen.getByRole("button", { name: /ajustar este perfil/i }));
    const peso = screen.getByLabelText(/peso do porte/i);
    await user.clear(peso);
    await user.type(peso, "10");
    expect(onParams).toHaveBeenLastCalledWith(expect.objectContaining({ w_porte: 10 }));
    expect(screen.getByText(/ajustado/i)).toBeInTheDocument();
    expect(screen.getByText(/somam 70/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /restaurar/i }));
    expect(screen.getByLabelText(/peso do porte/i)).toHaveValue(40);
    expect(screen.queryByText(/\(ajustado\)/i)).not.toBeInTheDocument();
  });

  it("desmarcar todos os portes mostra o erro inline", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: /ajustar este perfil/i }));
    await user.click(screen.getByRole("checkbox", { name: /demais/i }));
    expect(screen.getByText(/ao menos um porte/i)).toBeInTheDocument();
  });

  it("mínimo de estabelecimentos só aparece quando rede tem peso", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: /ajustar este perfil/i }));
    expect(screen.queryByLabelText(/mínimo de estabelecimentos/i)).not.toBeInTheDocument();
    await user.type(screen.getByLabelText(/peso da rede/i), "5");
    expect(screen.getByLabelText(/mínimo de estabelecimentos/i)).toHaveValue(2);
  });
});
