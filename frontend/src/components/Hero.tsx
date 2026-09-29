import type { ReactNode } from "react";

export function Hero({ version, children }: { version?: string | null; children: ReactNode }) {
  return (
    <header className="relative overflow-hidden border-b border-border pb-12 pt-10">
      <div
        aria-hidden
        className="pointer-events-none absolute -top-32 left-1/2 h-72 w-[42rem] -translate-x-1/2 rounded-full opacity-30 blur-3xl"
        style={{ background: "linear-gradient(90deg, #4f6bff, #7c5cff)" }}
      />
      <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
        Demo pública {version ? <span className="ml-2">v{version}</span> : null}
      </p>
      <h1 className="mt-3 max-w-3xl text-4xl font-bold tracking-tight sm:text-6xl">
        De um pedido em português para uma lista de empresas
      </h1>
      <p className="mt-4 max-w-2xl text-lg text-muted-foreground">
        A Quimera transforma o seu pedido em filtros, escolhe CNAEs, consulta a base de
        CNPJ e devolve o ranking com a explicação completa — SQL, bytes e custo medidos.
      </p>
      {children}
    </header>
  );
}
