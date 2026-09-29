import type { ReactNode } from "react";

function Etiqueta({ campo, valor }: { campo: string; valor: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-sm bg-secondary px-2 py-1 font-mono text-[11px]">
      <span className="text-faint">{campo}</span>
      <span className="text-foreground">{valor}</span>
    </span>
  );
}

const ESTAGIOS: { titulo: string; texto: string; artefato: ReactNode }[] = [
  {
    titulo: "Você descreve",
    texto:
      "Em português, como falaria com um colega: atividade, cidade, bairro, raio a partir de um CEP, porte, tempo de mercado.",
    artefato: (
      <p className="text-[15px] leading-relaxed">
        “<span className="underline decoration-accent decoration-2 underline-offset-[5px]">transportadoras</span>{" "}
        em <span className="underline decoration-accent decoration-2 underline-offset-[5px]">Campinas</span> com
        mais de uma unidade”
      </p>
    ),
  },
  {
    titulo: "A Quimera interpreta",
    texto:
      "Um modelo de linguagem extrai os filtros e embeddings acham os códigos CNAE. O modelo nunca escreve SQL: a consulta é montada pelo sistema, com teto de custo.",
    artefato: (
      <div className="flex flex-wrap gap-1.5">
        <Etiqueta campo="cnae" valor="4930-2/02" />
        <Etiqueta campo="município" valor="Campinas/SP" />
        <Etiqueta campo="unidades" valor="≥ 2" />
      </div>
    ),
  },
  {
    titulo: "Você recebe a lista",
    texto:
      "Empresas ativas da base pública da Receita, ordenadas pelo seu perfil de cliente ideal, cada uma com o motivo da nota.",
    artefato: (
      <div className="flex items-center justify-between gap-3 rounded-md bg-secondary px-3 py-2">
        <span className="truncate text-sm">Transportes Exemplo Ltda</span>
        <span className="flex items-center gap-2">
          <span className="h-1 w-12 overflow-hidden rounded-full bg-surface-3">
            <span className="block h-full w-[88%] bg-accent" />
          </span>
          <span className="font-mono text-sm text-accent">88</span>
        </span>
      </div>
    ),
  },
];

export function HowItWorks() {
  return (
    <section id="como-funciona" className="border-b border-border">
      <div className="mx-auto max-w-6xl px-5 py-24 sm:px-8 lg:py-32">
        <div className="max-w-2xl">
          <h2 className="font-display text-[clamp(1.75rem,3.2vw,2.5rem)] leading-[1.1] font-bold">
            Da frase à lista, em três passos
          </h2>
          <p className="mt-4 text-lg text-muted-foreground">
            Cada passo aparece na resposta, com os filtros, os códigos, a consulta e o custo.
            Nada fica numa caixa-preta.
          </p>
        </div>

        <ol className="relative mt-16 grid gap-12 lg:grid-cols-3 lg:gap-10">
          <span
            aria-hidden
            className="absolute top-[15px] right-[16%] left-[4%] hidden h-px bg-line-strong lg:block"
          />
          {ESTAGIOS.map((e, i) => (
            <li key={e.titulo} className="relative flex flex-col">
              <span className="relative z-10 flex size-8 items-center justify-center rounded-full border border-accent bg-background font-mono text-sm text-accent">
                {i + 1}
              </span>
              <h3 className="font-display mt-6 text-xl font-semibold">{e.titulo}</h3>
              <p className="mt-3 max-w-[38ch] leading-relaxed text-muted-foreground">{e.texto}</p>
              <div className="mt-6 border-t border-border pt-5">{e.artefato}</div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
