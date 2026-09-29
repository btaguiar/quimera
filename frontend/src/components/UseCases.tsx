import { ArrowDownRight } from "lucide-react";
import { PERFIS } from "@/lib/icp";

export interface CasoDeUso {
  quemVende: string;
  pedido: string;
  perfilId: string;
}

const CASOS: CasoDeUso[] = [
  {
    quemVende: "Fornecedor de produtos odontológicos",
    pedido: "clínicas odontológicas em Santo André abertas há mais de 2 anos",
    perfilId: "estabelecida",
  },
  {
    quemVende: "Rastreamento e seguro de frota",
    pedido: "transportadoras de carga em Campinas com mais de uma unidade",
    perfilId: "rede",
  },
  {
    quemVende: "Software de gestão contábil",
    pedido: "escritórios de contabilidade em Belo Horizonte de porte pequeno",
    perfilId: "pequeno-local",
  },
  {
    quemVende: "Agência de marketing digital",
    pedido: "academias em Porto Alegre com site próprio",
    perfilId: "digital",
  },
  {
    quemVende: "Distribuidor de alimentos",
    pedido: "restaurantes em Florianópolis abertos há mais de 5 anos",
    perfilId: "estabelecida",
  },
];

export function UseCases({ onPick }: { onPick: (caso: CasoDeUso) => void }) {
  return (
    <section id="casos" className="border-b border-border">
      <div className="mx-auto grid max-w-6xl gap-12 px-5 py-24 sm:px-8 lg:grid-cols-12 lg:py-32">
        <div className="lg:col-span-4">
          <h2 className="font-display text-[clamp(1.75rem,3.2vw,2.5rem)] leading-[1.1] font-bold">
            Para quem vende para empresas
          </h2>
          <p className="mt-4 text-lg text-muted-foreground">
            Escolha um ponto de partida. A frase e o perfil de cliente ideal vão direto para a
            demo; é só ajustar e analisar.
          </p>
        </div>
        <ul className="border-t border-border lg:col-span-8">
          {CASOS.map((caso) => {
            const perfil = PERFIS.find((p) => p.id === caso.perfilId)?.nome ?? "";
            return (
              <li key={caso.pedido} className="border-b border-border">
                <button
                  type="button"
                  onClick={() => onPick(caso)}
                  className="group grid w-full grid-cols-[1fr_auto] items-center gap-x-6 gap-y-1 px-1 py-5 text-left transition-colors duration-150 hover:bg-card sm:px-4"
                >
                  <span className="text-sm text-muted-foreground">{caso.quemVende}</span>
                  <ArrowDownRight
                    className="row-span-2 size-5 text-faint transition-colors duration-150 group-hover:text-accent"
                    strokeWidth={1.75}
                    aria-hidden
                  />
                  <span className="text-lg leading-snug text-foreground">
                    “{caso.pedido}”
                    <span className="ml-3 inline-block align-middle font-mono text-[11px] text-faint">
                      perfil {perfil}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}
