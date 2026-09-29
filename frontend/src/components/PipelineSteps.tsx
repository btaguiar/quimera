import { Cpu, Database, Search, Table2 } from "lucide-react";

const etapas = [
  {
    icone: Cpu,
    titulo: "Extração",
    texto: "O modelo transforma o pedido em português em filtros estruturados — e recusa pedidos de dado pessoal.",
  },
  {
    icone: Search,
    titulo: "CNAE e policy",
    texto: "Embeddings buscam os códigos de atividade; a policy pública corta o que não pode (MEI, contato, pessoa física).",
  },
  {
    icone: Database,
    titulo: "Consulta",
    texto: "SQL parametrizado — nunca escrito pelo modelo — contra a tabela própria, com estimativa e teto de bytes.",
  },
  {
    icone: Table2,
    titulo: "Ranking",
    texto: "Cada empresa recebe nota 0–100 com motivos legíveis; a lista sai ordenada pela nota.",
  },
];

export function PipelineSteps() {
  return (
    <section className="border-t border-border py-14">
      <h2 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
        Como funciona
      </h2>
      <ol className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {etapas.map(({ icone: Icone, titulo, texto }, i) => (
          <li key={titulo} className="rounded-2xl border border-border bg-card p-6">
            <div className="flex items-center gap-3">
              <span className="font-mono text-xs text-accent">0{i + 1}</span>
              <Icone className="h-5 w-5 text-accent" strokeWidth={1.5} aria-hidden />
            </div>
            <h3 className="mt-3 font-semibold">{titulo}</h3>
            <p className="mt-2 text-sm text-muted-foreground">{texto}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}
