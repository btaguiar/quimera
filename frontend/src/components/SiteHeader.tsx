import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { Logo } from "./Logo";

const LINKS = [
  { href: "/#como-funciona", rotulo: "Como funciona" },
  { href: "/#casos", rotulo: "Casos de uso" },
  { href: "/#numeros", rotulo: "Números" },
];

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-6 px-5 sm:px-8">
        <Link to="/" className="rounded-sm text-foreground" aria-label="Quimera — início">
          <Logo />
        </Link>
        <nav aria-label="Principal" className="flex items-center gap-1 sm:gap-2">
          <ul className="hidden items-center gap-1 md:flex">
            {LINKS.map((l) => (
              <li key={l.href}>
                <a
                  href={l.href}
                  className="rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors duration-150 hover:bg-surface-3 hover:text-foreground"
                >
                  {l.rotulo}
                </a>
              </li>
            ))}
            <li>
              <Link
                to="/metricas"
                className="rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors duration-150 hover:bg-surface-3 hover:text-foreground"
              >
                Métricas
              </Link>
            </li>
          </ul>
          <a
            href="/#demo"
            className="font-display ml-2 inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground transition-colors duration-150 [font-stretch:110%] hover:bg-accent-strong"
          >
            Testar agora
            <ArrowRight className="size-4" strokeWidth={2.25} aria-hidden />
          </a>
        </nav>
      </div>
    </header>
  );
}
