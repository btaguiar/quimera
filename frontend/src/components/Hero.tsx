import type { CSSProperties, ReactNode } from "react";
import { ArrowRight } from "lucide-react";

function atraso(ms: number): CSSProperties {
  return { "--atraso": `${ms}ms` } as CSSProperties;
}

function Trecho({ n, ms, children }: { n: number; ms: number; children: ReactNode }) {
  return (
    <>
      <span className="anotado" style={atraso(ms)}>
        {children}
      </span>
      <sup className="ml-0.5 font-mono text-[0.6em] font-medium text-accent">{n}</sup>
    </>
  );
}

const LEITURA = [
  { n: 1, campo: "atividade", valor: "CNAE 8630-5/04" },
  { n: 2, campo: "município", valor: "Santo André / SP" },
  { n: 3, campo: "idade mínima", valor: "2 anos" },
  { n: 4, campo: "porte", valor: "demais (médio e grande)" },
];

const LINHAS = [
  { nome: "Odonto Exemplo Ltda", motivo: "14 anos · capital R$ 400 mil", nota: 91 },
  { nome: "Clínica Modelo Sorriso", motivo: "9 anos · capital R$ 250 mil", nota: 84 },
  { nome: "Instituto Ilustrativo", motivo: "6 anos · capital R$ 120 mil", nota: 72 },
];

/** Exemplo fictício do mecanismo: frase anotada → filtros → ranking. */
function FraseAnotada() {
  return (
    <figure
      className="relative rounded-xl border border-line-strong bg-card shadow-[0_24px_60px_-20px_rgba(0,0,0,0.6)]"
      aria-label="Exemplo ilustrativo: uma frase vira filtros e uma lista ranqueada"
    >
      <div className="flex items-center justify-between border-b border-border px-5 py-3 text-xs text-faint">
        <span>Pedido</span>
        <span className="font-mono">exemplo ilustrativo</span>
      </div>

      <p className="px-5 pt-5 text-[1.3rem] leading-[1.75] text-foreground sm:text-[1.5rem]">
        <Trecho n={1} ms={250}>clínicas odontológicas</Trecho> em{" "}
        <Trecho n={2} ms={390}>Santo André</Trecho> abertas{" "}
        <Trecho n={3} ms={530}>há mais de 2 anos</Trecho>, de{" "}
        <Trecho n={4} ms={670}>porte médio</Trecho>
      </p>

      <dl className="grid gap-x-6 gap-y-2 px-5 pt-5 pb-5 font-mono text-xs sm:grid-cols-2">
        {LEITURA.map((l, i) => (
          <div key={l.n} className="surge flex gap-2" style={atraso(820 + i * 70)}>
            <dt className="shrink-0 text-accent">
              {l.n} <span className="text-faint">{l.campo}</span>
            </dt>
            <dd className="text-foreground">{l.valor}</dd>
          </div>
        ))}
      </dl>

      <div className="border-t border-border px-5 pt-4 pb-5">
        <p className="text-xs text-faint">
          Ranking pelo perfil <span className="text-muted-foreground">Estabelecida</span>
        </p>
        <ol className="mt-3 space-y-2.5">
          {LINHAS.map((l, i) => (
            <li
              key={l.nome}
              className="surge grid grid-cols-[1fr_auto] items-center gap-x-4 rounded-md bg-secondary px-3 py-2.5"
              style={atraso(1150 + i * 110)}
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{l.nome}</p>
                <p className="truncate font-mono text-[11px] text-faint">{l.motivo}</p>
              </div>
              <div className="flex items-center gap-2.5">
                <span className="hidden h-1 w-16 overflow-hidden rounded-full bg-surface-3 sm:block">
                  <span className="block h-full bg-accent" style={{ width: `${l.nota}%` }} />
                </span>
                <span className="w-6 text-right font-mono text-sm text-accent">{l.nota}</span>
              </div>
            </li>
          ))}
        </ol>
        <p className="mt-3 text-[11px] text-faint">Empresas fictícias, só para ilustrar o formato.</p>
      </div>
    </figure>
  );
}

export function Hero({ version }: { version?: string | null }) {
  return (
    <section className="relative border-b border-border">
      <div className="mx-auto grid max-w-6xl items-center gap-12 px-5 pt-14 pb-20 sm:px-8 lg:grid-cols-12 lg:gap-10 lg:pt-20 lg:pb-28">
        <div className="lg:col-span-6">
          <p className="inline-flex items-center gap-2 text-sm text-muted-foreground">
            <span className="size-1.5 rounded-full bg-success" aria-hidden />
            Demo aberta, sem cadastro
            {version ? <span className="font-mono text-xs text-faint">v{version}</span> : null}
          </p>
          <h1 className="font-display mt-5 text-[clamp(2.3rem,4.6vw,3.7rem)] leading-[1.04] font-bold">
            Um pedido em português. A lista de empresas certa.
          </h1>
          <p className="mt-6 max-w-[34rem] text-lg leading-relaxed text-muted-foreground">
            Descreva quem você quer prospectar: atividade, cidade, porte, tempo de mercado. A
            Quimera procura na base pública de CNPJ e devolve as empresas ranqueadas pelo seu
            perfil de cliente ideal, com o motivo de cada nota.
          </p>
          <div className="mt-9 flex flex-wrap items-center gap-3">
            <a
              href="#demo"
              className="font-display inline-flex h-12 items-center gap-2.5 rounded-md bg-primary px-6 text-base font-semibold text-primary-foreground transition-colors duration-150 [font-stretch:110%] hover:bg-accent-strong"
            >
              Testar com o meu pedido
              <ArrowRight className="size-4" strokeWidth={2.25} aria-hidden />
            </a>
            <a
              href="#como-funciona"
              className="inline-flex h-12 items-center rounded-md border border-line-strong px-5 text-base text-foreground transition-colors duration-150 hover:bg-surface-3"
            >
              Como funciona
            </a>
          </div>
          <ul className="mt-8 flex flex-wrap gap-x-5 gap-y-2 text-sm text-muted-foreground">
            <li>Base pública da Receita</li>
            <li>Nenhum dado pessoal</li>
            <li>Custo de cada consulta à vista</li>
          </ul>
        </div>
        <div className="lg:col-span-6">
          <FraseAnotada />
        </div>
      </div>
    </section>
  );
}
