import { useId, useState, type ReactNode } from "react";
import { SlidersHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  PERFIS,
  PORTES,
  resumoPerfil,
  somaPesos,
  validarIcp,
  type IcpParams,
  type Porte,
} from "@/lib/icp";

export interface IcpPickerProps {
  perfilId: string;
  params: IcpParams;
  onSelect: (perfilId: string) => void;
  onChange: (params: IcpParams) => void;
}

function mesmoPerfil(a: IcpParams, b: IcpParams): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function perfilAjustado(perfilId: string, params: IcpParams): boolean {
  const perfil = PERFIS.find((p) => p.id === perfilId);
  return !perfil || !mesmoPerfil(perfil.params, params);
}

function Campo({
  id,
  rotulo,
  children,
}: {
  id: string;
  rotulo: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-[13px] font-medium text-muted-foreground">
        {rotulo}
      </label>
      {children}
    </div>
  );
}

function Numero({
  id,
  valor,
  onValor,
  step = 1,
  min,
  max,
}: {
  id: string;
  valor: number;
  onValor: (v: number) => void;
  step?: number;
  min?: number;
  max?: number;
}) {
  return (
    <input
      id={id}
      type="number"
      inputMode="decimal"
      step={step}
      min={min}
      max={max}
      value={Number.isNaN(valor) ? "" : valor}
      onChange={(e) => onValor(e.target.valueAsNumber)}
      className="h-10 w-full rounded-md border border-input bg-background px-3 font-mono text-sm text-foreground transition-colors duration-150 hover:border-line-strong focus-visible:border-ring focus-visible:outline-none"
    />
  );
}

const PESOS: { chave: keyof IcpParams; rotulo: string }[] = [
  { chave: "w_porte", rotulo: "Peso do porte" },
  { chave: "w_age", rotulo: "Peso da idade" },
  { chave: "w_capital", rotulo: "Peso do capital" },
  { chave: "w_rede", rotulo: "Peso da rede" },
  { chave: "w_dominio", rotulo: "Peso do domínio" },
];

export function IcpPicker({ perfilId, params, onSelect, onChange }: IcpPickerProps) {
  const [aberto, setAberto] = useState(false);
  const base = useId();
  const ajustado = perfilAjustado(perfilId, params);
  const erro = validarIcp(params);
  const soma = somaPesos(params);
  const nomeAtual = PERFIS.find((p) => p.id === perfilId)?.nome ?? "Perfil";

  function set<K extends keyof IcpParams>(chave: K, valor: IcpParams[K]) {
    onChange({ ...params, [chave]: valor });
  }

  function alternarPorte(porte: Porte) {
    const tem = params.preferred_portes.includes(porte);
    const proximos = tem
      ? params.preferred_portes.filter((p) => p !== porte)
      : PORTES.filter((p) => p === porte || params.preferred_portes.includes(p));
    set("preferred_portes", proximos);
  }

  return (
    <section aria-labelledby={`${base}-titulo`}>
      <h3 id={`${base}-titulo`} className="font-display text-lg font-semibold">
        <span className="mr-2 font-mono text-sm font-normal text-accent">1</span>
        Perfil de cliente ideal
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">Define como a lista é ordenada.</p>
      <div role="radiogroup" aria-labelledby={`${base}-titulo`} className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {PERFIS.map((perfil) => {
          const marcado = perfil.id === perfilId;
          return (
            <label
              key={perfil.id}
              className={cn(
                "relative flex cursor-pointer flex-col rounded-lg border p-4 transition-colors duration-150",
                "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-ring",
                marcado
                  ? "border-accent bg-accent-soft"
                  : "border-border bg-background hover:border-line-strong hover:bg-surface-3/40",
              )}
            >
              <input
                type="radio"
                name={`${base}-perfil`}
                value={perfil.id}
                checked={marcado}
                onChange={() => onSelect(perfil.id)}
                className="sr-only"
                aria-describedby={`${base}-${perfil.id}-desc`}
              />
              <span className="flex items-start justify-between gap-3">
                <span className="font-medium">{perfil.nome}</span>
                <span
                  aria-hidden
                  className={cn(
                    "mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border",
                    marcado ? "border-accent" : "border-line-strong",
                  )}
                >
                  {marcado ? <span className="size-2 rounded-full bg-accent" /> : null}
                </span>
              </span>
              <span id={`${base}-${perfil.id}-desc`} className="mt-1.5 text-[13px] leading-snug text-muted-foreground">
                {perfil.descricao}
              </span>
              <ul className="mt-3 space-y-0.5 border-t border-border pt-3 font-mono text-[11px] text-faint">
                {resumoPerfil(marcado ? params : perfil.params).map((linha) => (
                  <li key={linha}>{linha}</li>
                ))}
              </ul>
            </label>
          );
        })}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
        <button
          type="button"
          aria-expanded={aberto}
          aria-controls={`${base}-ajuste`}
          onClick={() => setAberto((v) => !v)}
          className="inline-flex items-center gap-2 rounded-sm text-muted-foreground transition-colors duration-150 hover:text-foreground"
        >
          <SlidersHorizontal className="h-4 w-4 text-accent" strokeWidth={1.75} aria-hidden />
          Ajustar este perfil
        </button>
        {ajustado ? (
          <>
            <span className="rounded-sm bg-warning/10 px-2 py-0.5 font-mono text-xs text-warning">
              {nomeAtual} (ajustado)
            </span>
            <button
              type="button"
              onClick={() => onSelect(perfilId)}
              className="text-xs text-muted-foreground underline underline-offset-4 hover:text-foreground"
            >
              restaurar perfil
            </button>
          </>
        ) : null}
      </div>

      {aberto ? (
        <div id={`${base}-ajuste`} className="mt-4 space-y-6 rounded-lg border border-border bg-background p-5">
          <fieldset>
            <legend className="text-[13px] font-medium text-muted-foreground">Porte alvo</legend>
            <div className="mt-2 flex flex-wrap gap-4 text-sm">
              {PORTES.map((porte) => (
                <label key={porte} className="inline-flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={params.preferred_portes.includes(porte)}
                    onChange={() => alternarPorte(porte)}
                    className="h-4 w-4 accent-[var(--accent)]"
                  />
                  {porte}
                </label>
              ))}
            </div>
          </fieldset>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Campo id={`${base}-idade-min`} rotulo="Idade mínima (anos)">
              <Numero id={`${base}-idade-min`} valor={params.target_min_age_years} min={0} max={50}
                onValor={(v) => set("target_min_age_years", v)} />
            </Campo>
            <Campo id={`${base}-idade-plena`} rotulo="Idade plena (anos)">
              <Numero id={`${base}-idade-plena`} valor={params.target_full_age_years} min={0} max={60}
                onValor={(v) => set("target_full_age_years", v)} />
            </Campo>
            <Campo id={`${base}-cap-min`} rotulo="Capital mínimo (R$)">
              <Numero id={`${base}-cap-min`} valor={params.target_min_capital} step={1000} min={1000}
                onValor={(v) => set("target_min_capital", v)} />
            </Campo>
            <Campo id={`${base}-cap-max`} rotulo="Capital teto (R$)">
              <Numero id={`${base}-cap-max`} valor={params.target_max_capital} step={1000} min={1000}
                onValor={(v) => set("target_max_capital", v)} />
            </Campo>
          </div>

          <fieldset>
            <legend className="text-[13px] font-medium text-muted-foreground">Pesos da nota</legend>
            <div className="mt-2 grid gap-4 sm:grid-cols-3 lg:grid-cols-5">
              {PESOS.map(({ chave, rotulo }) => (
                <Campo key={chave} id={`${base}-${chave}`} rotulo={rotulo}>
                  <Numero id={`${base}-${chave}`} valor={params[chave] as number} min={0} max={100}
                    onValor={(v) => set(chave, v as never)} />
                </Campo>
              ))}
            </div>
            <p className="mt-2 font-mono text-xs text-faint">
              somam {Number.isFinite(soma) ? soma.toLocaleString("pt-BR") : "—"} — normalizados para 100 na nota
            </p>
          </fieldset>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {params.w_rede > 0 ? (
              <Campo id={`${base}-rede-min`} rotulo="Mínimo de estabelecimentos">
                <Numero id={`${base}-rede-min`} valor={params.target_min_estabelecimentos} min={2} max={100}
                  onValor={(v) => set("target_min_estabelecimentos", v)} />
              </Campo>
            ) : null}
            <Campo id={`${base}-mei`} rotulo="Fator MEI (0–1)">
              <Numero id={`${base}-mei`} valor={params.mei_factor} step={0.1} min={0} max={1}
                onValor={(v) => set("mei_factor", v)} />
            </Campo>
          </div>

          <p role="status" aria-live="polite" className="min-h-5 font-mono text-sm text-destructive">
            {erro ?? ""}
          </p>
        </div>
      ) : null}
    </section>
  );
}
