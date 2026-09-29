import { Link } from "react-router-dom";

export function Footer() {
  return (
    <footer className="border-t border-border py-10 text-sm text-muted-foreground">
      <p className="max-w-2xl">
        Nenhum dado pessoal é coletado ou exibido. Cada afirmação vem da resposta da API; as
        métricas do{" "}
        <Link to="/metricas" className="text-accent underline-offset-4 hover:underline">
          anexo medido
        </Link>{" "}
        vêm de <code className="font-mono text-xs">eval/</code>.
      </p>
    </footer>
  );
}
