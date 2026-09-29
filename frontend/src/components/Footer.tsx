import { Link } from "react-router-dom";
import { Logo } from "./Logo";

export function Footer({ version }: { version?: string | null }) {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto grid max-w-6xl gap-10 px-5 py-14 text-sm text-muted-foreground sm:px-8 md:grid-cols-[1fr_auto]">
        <div className="max-w-md">
          <Logo className="text-foreground" />
          <p className="mt-4 leading-relaxed">
            Empresas da base pública de CNPJ da Receita Federal. Nenhum dado pessoal é coletado ou
            exibido. Cada número vem da resposta da API ou das avaliações em{" "}
            <code className="font-mono text-xs text-foreground">eval/</code>.
          </p>
        </div>
        <nav aria-label="Rodapé" className="flex flex-col gap-2 md:items-end">
          <a href="/#demo" className="hover:text-foreground">
            Testar agora
          </a>
          <a href="/#como-funciona" className="hover:text-foreground">
            Como funciona
          </a>
          <Link to="/metricas" className="hover:text-foreground">
            Métricas medidas
          </Link>
          {version ? <span className="mt-2 font-mono text-xs text-faint">v{version}</span> : null}
        </nav>
      </div>
    </footer>
  );
}
