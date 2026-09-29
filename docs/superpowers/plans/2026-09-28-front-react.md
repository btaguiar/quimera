# Front React (dark, produto moderno) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir o front estático "Laudo Técnico" por uma SPA React dark (estilo Vercel/Resend) servida pela mesma FastAPI, com hero, resultado animado, página de métricas e testes (Vitest, Playwright, pytest).

**Architecture:** `frontend/` (Vite + React + TS + Tailwind v4 + shadcn customizado) builda para `src/quimera/api/static/` (package-data `static/**/*`). A FastAPI serve o bundle com SPA fallback (subclasse de `StaticFiles`) e mantém a API JSON intacta. A rota do front de métricas é `/metricas` porque `/metrics` é a rota JSON da API; `/metrics.html` redireciona para `/metricas`.

**Tech Stack:** React 19, Vite, TypeScript, Tailwind CSS v4, shadcn/ui (Radix), react-router-dom, fontes `geist` (self-hosted), Vitest + Testing Library, Playwright, FastAPI, Docker multi-stage (node:22 → python:3.12).

**Spec:** `docs/superpowers/specs/2026-09-28-front-react-design.md`

---

## File Structure

```
frontend/                       # fonte React (criada do zero)
  package.json
  tsconfig.json / tsconfig.app.json / tsconfig.node.json
  vite.config.ts                # plugins, alias @, outDir → static/, proxy dev, test config
  components.json               # shadcn
  playwright.config.ts
  index.html                    # <html class="dark">, <div id="root">
  src/
    main.tsx                    # monta App; injeta vars de fonte
    App.tsx                     # BrowserRouter: / e /metricas
    styles/globals.css          # tokens dark + mapeamento shadcn (@theme inline)
    lib/
      utils.ts                  # cn() do shadcn
      types.ts                  # contratos da API (LeadFilters, LeadsResponse, ...)
      api.ts                    # fetchConfig/fetchHealth/fetchMetrics/submitLead
      format.ts                 # fmtBytes/fmtUSD/fmtMs/fmtData/fmtPct
      turnstile.ts              # TurnstileController (reset em TODO submit)
      metrics.ts                # selectE2e (regra golden_e2e) + selectUltima
    components/
      ui/                       # gerados pelo shadcn (button, card, badge, ...)
      Hero.tsx
      ExampleChips.tsx
      RequestForm.tsx
      StatusBanner.tsx
      ResultPanel.tsx
      FiltersBadge.tsx
      CnaeList.tsx
      SqlBlock.tsx
      RankingTable.tsx
      CostSummary.tsx
      PipelineSteps.tsx
      MetricSuite.tsx
      Footer.tsx
    pages/
      Home.tsx                  # máquina de estados da busca + composição
      Metrics.tsx               # /metricas
  tests/
    setup.ts
    format.test.ts
    api.test.ts
    turnstile.test.ts
    metrics.test.ts
    request-form.test.tsx
    status-banner.test.tsx
    result-panel.test.tsx
    ranking-table.test.tsx
    metric-suite.test.tsx
  e2e/
    fixtures/
      leads-success.json
      leads-refusal.json
      metrics.json
    quimera.spec.ts
src/quimera/api/static/         # OUTPUT do build (passa a ser gitignored)
src/quimera/api/app.py          # MODIFICADO: SpaStaticFiles + redirect /metrics.html + static_dir injetável
pyproject.toml                  # MODIFICADO: package-data static/**/*
Dockerfile                      # MODIFICADO: estágio node:22 antes do pip install
.dockerignore                   # MODIFICADO: frontend/node_modules etc.
.gitignore                      # MODIFICADO: src/quimera/api/static/
tests/test_api.py               # MODIFICADO: TestFrontend reescrito + testes de fallback
```

**Regras de contrato que todo task respeita:**
- API intocada: `POST /leads`, `GET /metrics`, `GET /config`, `GET /health`.
- Todo erro da API vem em `{"error", "reason"}` — a UI mostra `reason`.
- Valor medido (bytes, custo, score, latência, CNPJ, SQL) sempre em mono.
- Nenhum dado pessoal em tela. UI em pt-BR. Sem emojis.
- Contraste AA: CTA em `#3B52E0` (branco ≥ 4,5:1); `#4F6BFF` só em acentos/glow.
- `prefers-reduced-motion` desliga animações.

---

### Task 1: Scaffold do frontend (Vite + React + TS + Tailwind v4 + fontes)

**Files:**
- Create: `frontend/package.json`, `frontend/tsconfig.json`, `frontend/tsconfig.app.json`, `frontend/tsconfig.node.json`, `frontend/vite.config.ts`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/styles/globals.css`

- [ ] **Step 1: Criar o projeto Vite (React + TS)**

```bash
cd frontend 2>/dev/null || mkdir frontend && cd frontend
npm create vite@latest . -- --template react-ts
npm install
npm install react-router-dom geist
npm install -D @types/node
npm install tailwindcss @tailwindcss/vite
```

Se o `npm create vite` reclamar de diretório não-vazio, rodar com o nome `frontend` em seguida mover os arquivos para a raiz de `frontend/`. Se o pacote `geist` não existir no registry, usar `@fontsource-variable/inter @fontsource-variable/jetbrains-mono` e trocar os `@import` do `globals.css` (Task 1 Step 4) e o `main.tsx` (Step 5) para os fontes do fontsource.

- [ ] **Step 2: Substituir `frontend/vite.config.ts`**

```ts
/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

const API = process.env.VITE_API_ORIGIN ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  build: {
    outDir: "../src/quimera/api/static",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/leads": API,
      "/health": API,
      "/config": API,
      "/metrics": API,
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
```

- [ ] **Step 3: Ajustar `frontend/tsconfig.json` para referenciar os projetos e o alias `@`**

```json
{
  "files": [],
  "references": [
    { "path": "./tsconfig.app.json" },
    { "path": "./tsconfig.node.json" }
  ]
}
```

Em `frontend/tsconfig.app.json`, garante `jsx: "react-jsx"`, `moduleResolution: "bundler"`, `strict: true`, `noEmit: true`, `types: ["vite/client"]` e:

```json
{
  "compilerOptions": {
    "baseUrl": ".",
    "paths": { "@/*": ["./src/*"] }
  }
}
```

Em `frontend/tsconfig.node.json`, garante `types: ["node"]` e `include: ["vite.config.ts", "playwright.config.ts"]`.

- [ ] **Step 4: Substituir o CSS por `frontend/src/styles/globals.css` (tokens dark + shadcn)**

```css
@import "tailwindcss";

@custom-variant dark (&:is(.dark *));

:root {
  --background: #0a0a0c;
  --foreground: #f4f4f5;
  --card: #121216;
  --card-foreground: #f4f4f5;
  --popover: #121216;
  --popover-foreground: #f4f4f5;
  --primary: #3b52e0;
  --primary-foreground: #ffffff;
  --secondary: #1a1a20;
  --secondary-foreground: #f4f4f5;
  --muted: #1a1a20;
  --muted-foreground: #a1a1aa;
  --accent: #4f6bff;
  --accent-foreground: #ffffff;
  --destructive: #e5484d;
  --destructive-foreground: #ffffff;
  --warning: #f5a524;
  --warning-foreground: #0a0a0c;
  --success: #30a46c;
  --success-foreground: #ffffff;
  --border: rgba(255, 255, 255, 0.08);
  --input: rgba(255, 255, 255, 0.08);
  --ring: #4f6bff;
  --radius: 0.75rem;
  --font-sans: var(--font-geist-sans), ui-sans-serif, system-ui, sans-serif;
  --font-mono: var(--font-geist-mono), ui-monospace, Consolas, Menlo, monospace;
}

@theme inline {
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-destructive-foreground: var(--destructive-foreground);
  --color-warning: var(--warning);
  --color-warning-foreground: var(--warning-foreground);
  --color-success: var(--success);
  --color-success-foreground: var(--success-foreground);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) + 4px);
  --font-sans: var(--font-sans);
  --font-mono: var(--font-mono);
}

@layer base {
  * {
    border-color: var(--border);
  }
  body {
    margin: 0;
    background: var(--background);
    color: var(--foreground);
    font-family: var(--font-sans);
    -webkit-font-smoothing: antialiased;
  }
  ::selection {
    background: var(--accent);
    color: var(--accent-foreground);
  }
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

- [ ] **Step 5: Substituir `frontend/src/main.tsx` e `frontend/src/App.tsx` e o `index.html`**

`frontend/index.html`:

```html
<!doctype html>
<html lang="pt-BR" class="dark">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Quimera — empresas a partir de um pedido em português</title>
    <meta
      name="description"
      content="Pedido em português vira lista ranqueada de empresas (CNPJ) com decisão explicável, bytes e custo medidos."
    />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`frontend/src/main.tsx`:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import App from "./App";
import "./styles/globals.css";

document.documentElement.classList.add(GeistSans.variable, GeistMono.variable);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

`frontend/src/App.tsx` (ainda sem rotas de páginas — Task 10/11 preenchem):

```tsx
export default function App() {
  return (
    <main className="mx-auto max-w-5xl px-6 py-16">
      <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
        Demo pública
      </p>
      <h1 className="mt-2 text-4xl font-bold tracking-tight">Quimera</h1>
    </main>
  );
}
```

- [ ] **Step 6: Rodar dev, typecheck e build**

Run: `npm run dev` → abrir `http://localhost:5173`, ver "Quimera" em fundo escuro.
Run: `npx tsc -b` → esperado: sem erros.
Run: `npm run build` → esperado: `../src/quimera/api/static/` com `index.html` e `assets/`.
Run: `git status` → `src/quimera/api/static/` deve aparecer como untracked/massivamente alterado (a Task 13 coloca no gitignore).

- [ ] **Step 7: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/tsconfig*.json frontend/vite.config.ts frontend/index.html frontend/src
git commit -m "front: scaffold React+Vite+Tailwind com tema dark e build em static/"
```

---

### Task 2: shadcn/ui + utilitário `cn`

**Files:**
- Create: `frontend/components.json`, `frontend/src/lib/utils.ts`, `frontend/src/components/ui/*` (gerados)
- Modify: `frontend/package.json` (deps do shadcn)

- [ ] **Step 1: Escrever `frontend/components.json` (evita init interativo)**

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "new-york",
  "rsc": false,
  "tsx": true,
  "tailwind": {
    "config": "",
    "css": "src/styles/globals.css",
    "baseColor": "zinc",
    "cssVariables": true,
    "prefix": ""
  },
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils",
    "ui": "@/components/ui",
    "lib": "@/lib",
    "hooks": "@/hooks"
  },
  "iconLibrary": "lucide"
}
```

- [ ] **Step 2: Adicionar componentes shadcn**

Run: `npx shadcn@latest add button card badge textarea label table separator skeleton alert -y`
Run: `npm install lucide-react`

Se o CLI pedir confirmação de paths, aceitar os defaults do `components.json` acima.

- [ ] **Step 3: Criar `frontend/src/lib/utils.ts` (se o CLI não gerou)**

```ts
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

Run: `npm install clsx tailwind-merge` (se ainda não estiverem em `package.json`).

- [ ] **Step 4: Conferir que os tokens dark batem com o globals.css**

Run: `rg "background|primary|ring" frontend/src/components/ui/button.tsx`
Esperado: classes `bg-primary text-primary-foreground`, sem cores hardcoded.

- [ ] **Step 5: Typecheck + commit**

Run: `npx tsc -b` → esperado: sem erros.

```bash
git add frontend/components.json frontend/src/lib/utils.ts frontend/src/components/ui frontend/package.json frontend/package-lock.json
git commit -m "front: shadcn/ui sobre os tokens dark do Quimera"
```

---

### Task 3: Tipos da API + formatadores + cliente (TDD)

**Files:**
- Create: `frontend/tests/setup.ts`, `frontend/src/lib/types.ts`, `frontend/src/lib/format.ts`, `frontend/src/lib/api.ts`
- Test: `frontend/tests/format.test.ts`, `frontend/tests/api.test.ts`

- [ ] **Step 1: Escrever o setup e os testes de `format.ts` que falham**

`frontend/tests/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

`frontend/tests/format.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { fmtBytes, fmtData, fmtMs, fmtNumOrDash, fmtPct, fmtUSD } from "@/lib/format";

describe("fmtBytes", () => {
  it("formata MB com uma casa", () => {
    expect(fmtBytes(33 * 1024 ** 2)).toBe("33,0 MB");
  });
  it("formata GB com duas casas", () => {
    expect(fmtBytes(1.5 * 1024 ** 3)).toBe("1,50 GB");
  });
  it("devolve traço quando ausente ou inválido", () => {
    expect(fmtBytes(null)).toBe("—");
    expect(fmtBytes(Number.NaN)).toBe("—");
  });
});

describe("fmtUSD", () => {
  it("mostra 6 casas com vírgula", () => {
    expect(fmtUSD(0.000123)).toBe("US$ 0,000123");
  });
  it("devolve traço quando ausente", () => {
    expect(fmtUSD(undefined)).toBe("—");
  });
});

describe("fmtMs", () => {
  it("arredonda e formata em pt-BR", () => {
    expect(fmtMs(4123.4)).toBe("4.123 ms");
  });
  it("devolve traço quando ausente", () => {
    expect(fmtMs(null)).toBe("—");
  });
});

describe("fmtData", () => {
  it("converte AAAAMMDD em DD/MM/AAAA", () => {
    expect(fmtData("20150110")).toBe("10/01/2015");
  });
  it("devolve traço para formato errado", () => {
    expect(fmtData("2015")).toBe("—");
    expect(fmtData(null)).toBe("—");
  });
});

describe("fmtPct", () => {
  it("mostra 0-1 como porcentagem com uma casa", () => {
    expect(fmtPct(0.955)).toBe("95,5%");
  });
});

describe("fmtNumOrDash", () => {
  it("formata inteiros e protege nulos", () => {
    expect(fmtNumOrDash(20)).toBe("20");
    expect(fmtNumOrDash(null)).toBe("—");
  });
});
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `npm test -- tests/format.test.ts`
Esperado: FAIL — `Failed to resolve import "@/lib/format"`.

- [ ] **Step 3: Implementar `frontend/src/lib/format.ts`**

```ts
const fmtNum = new Intl.NumberFormat("pt-BR");

export function fmtBytes(b: number | null | undefined): string {
  if (b == null || !Number.isFinite(b)) return "—";
  if (b >= 1024 ** 3) return `${fmtNum.format(+(b / 1024 ** 3).toFixed(2))} GB`;
  return `${fmtNum.format(+(b / 1024 ** 2).toFixed(1))} MB`;
}

export function fmtUSD(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `US$ ${v.toFixed(6).replace(".", ",")}`;
}

export function fmtMs(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${fmtNum.format(Math.round(v))} ms`;
}

export function fmtNumOrDash(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? "—" : fmtNum.format(v);
}

export function fmtData(yyyymmdd: string | null | undefined): string {
  return /^\d{8}$/.test(yyyymmdd ?? "")
    ? `${yyyymmdd!.slice(6, 8)}/${yyyymmdd!.slice(4, 6)}/${yyyymmdd!.slice(0, 4)}`
    : "—";
}

export function fmtPct(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v)
    ? "—"
    : `${fmtNum.format(+(v * 100).toFixed(1))}%`;
}
```

- [ ] **Step 4: Rodar para ver passar**

Run: `npm test -- tests/format.test.ts`
Esperado: PASS (6 suites).

- [ ] **Step 5: Escrever os testes de `types.ts` + `api.ts` que falham**

`frontend/tests/api.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, fetchMetrics, fetchHealth, submitLead } from "@/lib/api";

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("submitLead", () => {
  it("envia request e token e devolve o payload", async () => {
    const payload = { refused: false, rows: [], cached: false, cache_mode: false };
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(payload));
    const out = await submitLead("padarias em Curitiba", "tok-1");
    expect(fetch).toHaveBeenCalledWith(
      "/leads",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ request: "padarias em Curitiba", turnstile: "tok-1" }),
      }),
    );
    expect(out).toEqual(payload);
  });

  it("omite turnstile quando nulo", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ refused: false }));
    await submitLead("padarias", null);
    expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]!.body as string)).toEqual({
      request: "padarias",
    });
  });

  it("lança ApiError com o reason do servidor", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ error: "rate limit", reason: "limite de 10 requisições" }, 429),
    );
    await expect(submitLead("x", null)).rejects.toMatchObject({
      status: 429,
      body: { error: "rate limit", reason: "limite de 10 requisições" },
    });
  });

  it("lança NetworkError quando o fetch falha", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(submitLead("x", null)).rejects.toThrow("falha de rede");
  });

  it("propaga abort sem virar NetworkError", async () => {
    const abort = new DOMException("aborted", "AbortError");
    vi.mocked(fetch).mockRejectedValueOnce(abort);
    await expect(submitLead("x", null, AbortSignal.abort())).rejects.toBe(abort);
  });
});

describe("fetchHealth / fetchMetrics", () => {
  it("devolvem o JSON das rotas", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse({ status: "ok", version: "0.1.0" }))
      .mockResolvedValueOnce(jsonResponse({ thresholds: {}, extraction: [], cnae: [], e2e: [] }));
    expect((await fetchHealth()).version).toBe("0.1.0");
    expect((await fetchMetrics()).e2e).toEqual([]);
  });

  it("ApiError expõe status e body", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ error: "e", reason: "r" }, 500));
    const err = await fetchHealth().catch((e) => e as ApiError);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(500);
    expect((err as ApiError).body?.reason).toBe("r");
  });
});
```

- [ ] **Step 6: Rodar para ver falhar**

Run: `npm test -- tests/api.test.ts`
Esperado: FAIL — `Failed to resolve import "@/lib/api"`.

- [ ] **Step 7: Implementar `frontend/src/lib/types.ts` e `frontend/src/lib/api.ts`**

`frontend/src/lib/types.ts`:

```ts
export interface LeadFilters {
  cnae_query?: string | null;
  cnae_codes: string[];
  ufs: string[];
  municipio_ids: string[];
  municipio_names: string[];
  min_age_years?: number | null;
  max_age_years?: number | null;
  min_capital?: number | null;
  portes: string[];
  include_mei: boolean;
  min_estabelecimentos?: number | null;
  regimes: string[];
  bairros: string[];
  cep_centro?: string | null;
  raio_km?: number | null;
  com_dominio_proprio: boolean;
  limit: number;
}

export interface LeadRow {
  cnpj_basico?: string;
  razao_social: string;
  nome_fantasia?: string | null;
  sigla_uf?: string | null;
  id_municipio?: string | null;
  municipio?: string | null;
  cnae_fiscal_principal?: string | null;
  data_inicio_atividade?: string | null;
  capital_social?: number | null;
  porte?: string | null;
  score?: number | null;
  motivos_score?: string[];
}

export interface LeadsResponse {
  refused: boolean;
  refusal_reason: string | null;
  filters: LeadFilters | null;
  cnae_matches: [string, string, number][];
  municipio_resolution: Record<string, string[]>;
  snapshot: Record<string, string>;
  rows: LeadRow[];
  bytes_processed: number;
  bytes_billed: number;
  estimated_cost_usd: number;
  latency_ms: number;
  timings_ms: Record<string, number>;
  model: string;
  policy: string;
  request_normalized: string;
  warnings: string[];
  query_sql: string;
  cached: boolean;
  cache_mode: boolean;
}

export interface ApiErrorBody {
  error: string;
  reason: string;
}

export interface HealthResponse {
  status: string;
  version: string;
  cache_mode: boolean;
  budget_remaining_bytes: number;
}

export interface ConfigResponse {
  turnstile_site_key: string | null;
}

export interface MetricEntry {
  suite?: string;
  date?: string;
  commit?: string;
  golden?: string;
  metrics?: Record<string, number>;
}

export interface MetricsResponse {
  thresholds: Record<string, number>;
  extraction: MetricEntry[];
  cnae: MetricEntry[];
  e2e: MetricEntry[];
}
```

`frontend/src/lib/api.ts`:

```ts
import type {
  ApiErrorBody,
  ConfigResponse,
  HealthResponse,
  LeadsResponse,
  MetricsResponse,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: ApiErrorBody | null,
  ) {
    super(body?.reason ?? `HTTP ${status}`);
    this.name = "ApiError";
  }
}

export class NetworkError extends Error {
  constructor() {
    super("falha de rede");
    this.name = "NetworkError";
  }
}

async function parse<T>(resp: Response): Promise<T> {
  const body = await resp.json().catch(() => null);
  if (!resp.ok) throw new ApiError(resp.status, body as ApiErrorBody | null);
  return body as T;
}

function get<T>(url: string, signal?: AbortSignal): Promise<T> {
  return fetch(url, { signal })
    .catch((err) => {
      if (err instanceof DOMException && err.name === "AbortError") throw err;
      throw new NetworkError();
    })
    .then((resp) => parse<T>(resp));
}

export function fetchConfig(): Promise<ConfigResponse> {
  return get<ConfigResponse>("/config");
}

export function fetchHealth(): Promise<HealthResponse> {
  return get<HealthResponse>("/health");
}

export function fetchMetrics(): Promise<MetricsResponse> {
  return get<MetricsResponse>("/metrics");
}

export function submitLead(
  request: string,
  turnstile: string | null,
  signal?: AbortSignal,
): Promise<LeadsResponse> {
  return fetch("/leads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(turnstile ? { request, turnstile } : { request }),
    signal,
  })
    .catch((err) => {
      if (err instanceof DOMException && err.name === "AbortError") throw err;
      throw new NetworkError();
    })
    .then((resp) => parse<LeadsResponse>(resp));
}
```

- [ ] **Step 8: Rodar para ver passar e commitar**

Run: `npm test` → esperado: PASS (todos os arquivos atuais).
Run: `npx tsc -b` → esperado: sem erros.

```bash
git add frontend/src/lib frontend/tests
git commit -m "front: contratos da API tipados, formatadores pt-BR e cliente fetch"
```

---

### Task 4: Turnstile (reset em todo submit) + regra de métricas (TDD)

**Files:**
- Create: `frontend/src/lib/turnstile.ts`, `frontend/src/lib/metrics.ts`
- Test: `frontend/tests/turnstile.test.ts`, `frontend/tests/metrics.test.ts`

- [ ] **Step 1: Escrever os testes que falham**

`frontend/tests/turnstile.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TurnstileController } from "@/lib/turnstile";

const render = vi.fn(() => "w-1");
const reset = vi.fn();

beforeEach(() => {
  vi.stubGlobal("window", {
    ...window,
    turnstile: { render, reset },
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("TurnstileController", () => {
  it("renderiza e captura o token", () => {
    const ctl = new TurnstileController();
    const box = document.createElement("div");
    ctl.render(box, "site-key");
    expect(render).toHaveBeenCalledOnce();
    expect(ctl.status).toBe("ready");
  });

  it("consume o token e reseta — token é de uso único", () => {
    const ctl = new TurnstileController();
    ctl.render(document.createElement("div"), "site-key");
    const cb = render.mock.calls[0][1].callback as (t: string) => void;
    cb("tok-1");
    expect(ctl.consume()).toBe("tok-1");
    expect(reset).toHaveBeenCalledWith("w-1");
    expect(ctl.token).toBeNull();
  });

  it("segundo consume devolve null até novo token", () => {
    const ctl = new TurnstileController();
    ctl.render(document.createElement("div"), "site-key");
    const cb = render.mock.calls[0][1].callback as (t: string) => void;
    cb("tok-1");
    ctl.consume();
    expect(ctl.consume()).toBeNull();
  });

  it("marca indisponível sem window.turnstile", () => {
    vi.stubGlobal("window", {});
    const ctl = new TurnstileController();
    ctl.render(document.createElement("div"), "site-key");
    expect(ctl.status).toBe("unavailable");
    expect(ctl.consume()).toBeNull();
  });

  it("expired-callback limpa o token", () => {
    const ctl = new TurnstileController();
    ctl.render(document.createElement("div"), "site-key");
    const opts = render.mock.calls[0][1];
    opts.callback("tok-1");
    opts["expired-callback"]();
    expect(ctl.token).toBeNull();
  });
});
```

`frontend/tests/metrics.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { selectE2e, selectUltima } from "@/lib/metrics";
import type { MetricEntry } from "@/lib/types";

const entry = (o: Partial<MetricEntry>): MetricEntry => ({
  suite: "e2e",
  metrics: {},
  ...o,
});

describe("selectE2e", () => {
  it("prefere golden_e2e.jsonl com n_cases >= 20", () => {
    const lista = [
      entry({ golden: "outro.jsonl", metrics: { n_cases: 30 } }),
      entry({ golden: "golden_e2e.jsonl", metrics: { n_cases: 5 } }),
      entry({ golden: "golden_e2e.jsonl", metrics: { n_cases: 20 } }),
    ];
    expect(selectE2e(lista)?.metrics?.n_cases).toBe(20);
  });

  it("cai para qualquer execução com n_cases >= 20", () => {
    const lista = [
      entry({ metrics: { n_cases: 21 } }),
      entry({ metrics: { n_cases: 22 } }),
      entry({ metrics: { n_cases: 3 } }),
    ];
    expect(selectE2e(lista)?.metrics?.n_cases).toBe(22);
  });

  it("cai para a última quando nada tem 20 casos", () => {
    const lista = [entry({ metrics: { n_cases: 3 } }), entry({ metrics: { n_cases: 4 } })];
    expect(selectE2e(lista)?.metrics?.n_cases).toBe(4);
  });

  it("devolve null sem lista", () => {
    expect(selectE2e(undefined)).toBeNull();
    expect(selectE2e([])).toBeNull();
  });
});

describe("selectUltima", () => {
  it("devolve o último item", () => {
    expect(selectUltima([entry({}), entry({ commit: "abc" })])?.commit).toBe("abc");
    expect(selectUltima([])).toBeNull();
  });
});
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `npm test -- tests/turnstile.test.ts tests/metrics.test.ts`
Esperado: FAIL — imports não resolvidos.

- [ ] **Step 3: Implementar `frontend/src/lib/turnstile.ts`**

```ts
export type TurnstileStatus = "idle" | "ready" | "unavailable" | "error";

export interface TurnstileOptions {
  sitekey: string;
  callback: (token: string) => void;
  "expired-callback": () => void;
  "error-callback": () => void;
  language: string;
}

declare global {
  interface Window {
    turnstile?: {
      render: (el: HTMLElement, opts: TurnstileOptions) => string;
      reset: (widgetId?: string) => void;
    };
  }
}

export class TurnstileController {
  widgetId: string | null = null;
  token: string | null = null;
  status: TurnstileStatus = "idle";

  render(container: HTMLElement, siteKey: string): void {
    if (typeof window.turnstile?.render !== "function") {
      this.status = "unavailable";
      return;
    }
    try {
      this.widgetId = window.turnstile.render(container, {
        sitekey: siteKey,
        callback: (token: string) => {
          this.token = token;
          this.status = "ready";
        },
        "expired-callback": () => {
          this.token = null;
          this.status = "idle";
        },
        "error-callback": () => {
          this.token = null;
          this.status = "error";
        },
        language: "pt-br",
      });
    } catch {
      this.status = "unavailable";
    }
  }

  /** Token é de uso único: chamar em TODO submit, nunca reutilizar. */
  consume(): string | null {
    const token = this.token;
    this.reset();
    return token;
  }

  reset(): void {
    this.token = null;
    if (this.widgetId !== null && typeof window.turnstile?.reset === "function") {
      window.turnstile.reset(this.widgetId);
    }
  }
}
```

- [ ] **Step 4: Implementar `frontend/src/lib/metrics.ts`**

```ts
import type { MetricEntry } from "./types";

export function selectUltima(lista: MetricEntry[] | undefined): MetricEntry | null {
  return lista && lista.length ? lista[lista.length - 1] : null;
}

/** Regra do metrics.js atual: golden com 20+ casos → qualquer 20+ → última. */
export function selectE2e(lista: MetricEntry[] | undefined): MetricEntry | null {
  if (!lista || !lista.length) return null;
  const principal = lista.filter(
    (e) => e && e.golden === "golden_e2e.jsonl" && (e.metrics?.n_cases ?? 0) >= 20,
  );
  if (principal.length) return principal[principal.length - 1];
  const cheios = lista.filter((e) => e && (e.metrics?.n_cases ?? 0) >= 20);
  if (cheios.length) return cheios[cheios.length - 1];
  return selectUltima(lista);
}
```

- [ ] **Step 5: Rodar para ver passar e commitar**

Run: `npm test` → esperado: PASS.

```bash
git add frontend/src/lib/turnstile.ts frontend/src/lib/metrics.ts frontend/tests/turnstile.test.ts frontend/tests/metrics.test.ts
git commit -m "front: Turnstile de uso único (reset em todo submit) e regra de seleção de métricas"
```

---

### Task 5: Hero + ExampleChips + RequestForm (TDD)

**Files:**
- Create: `frontend/src/components/Hero.tsx`, `frontend/src/components/ExampleChips.tsx`, `frontend/src/components/RequestForm.tsx`
- Test: `frontend/tests/request-form.test.tsx`

- [ ] **Step 1: Escrever o teste que falha**

`frontend/tests/request-form.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { RequestForm } from "@/components/RequestForm";

const exemplos = ["padarias artesanais em Curitiba", "transportadoras em São Paulo"];

function renderForm(overrides: Partial<ComponentProps<typeof RequestForm>> = {}) {
  const onChange = vi.fn();
  const onSubmit = vi.fn();
  render(
    <RequestForm
      value=""
      onChange={onChange}
      onSubmit={onSubmit}
      loading={false}
      examples={exemplos}
      turnstileSlot={<div data-testid="turnstile" />}
      {...overrides}
    />,
  );
  return { onChange, onSubmit };
}

describe("RequestForm", () => {
  it("mostra contador 0/500 e envia o pedido", async () => {
    const user = userEvent.setup();
    const { onChange, onSubmit } = renderForm();
    const textarea = screen.getByLabelText(/pedido/i);
    await user.type(textarea, "padarias");
    expect(onChange).toHaveBeenLastCalledWith("padarias");
    await user.click(screen.getByRole("button", { name: /analisar/i }));
    expect(onSubmit).toHaveBeenCalledOnce();
  });

  it("chips de exemplo preenchem o textarea", async () => {
    const user = userEvent.setup();
    const { onChange } = renderForm({ value: "" });
    await user.click(screen.getByRole("button", { name: exemplos[1] }));
    expect(onChange).toHaveBeenCalledWith(exemplos[1]);
  });

  it("bloqueia envio vazio e mostra aviso", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderForm({ value: "  " });
    await user.click(screen.getByRole("button", { name: /analisar/i }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent(/escreva um pedido/i);
  });

  it("desabilita o botão durante o loading", () => {
    renderForm({ loading: true, value: "x" });
    expect(screen.getByRole("button", { name: /analisando/i })).toBeDisabled();
  });

  it("mostra o contador com o tamanho do valor", () => {
    renderForm({ value: "abc" });
    expect(screen.getByText("3/500")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `npm test -- tests/request-form.test.tsx`
Esperado: FAIL — `Failed to resolve import "@/components/RequestForm"`.

- [ ] **Step 3: Implementar `frontend/src/components/Hero.tsx`**

```tsx
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
```

- [ ] **Step 4: Implementar `frontend/src/components/ExampleChips.tsx`**

```tsx
export function ExampleChips({
  examples,
  onPick,
}: {
  examples: string[];
  onPick: (text: string) => void;
}) {
  return (
    <ul className="flex flex-wrap gap-2" aria-label="Pedidos-modelo">
      {examples.map((ex) => (
        <li key={ex}>
          <button
            type="button"
            onClick={() => onPick(ex)}
            className="rounded-full border border-border bg-secondary px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-accent hover:text-foreground"
          >
            {ex}
          </button>
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 5: Implementar `frontend/src/components/RequestForm.tsx`**

```tsx
import { useState, type FormEvent, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ExampleChips } from "./ExampleChips";

export interface RequestFormProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (value: string) => void;
  loading: boolean;
  examples: string[];
  turnstileSlot: ReactNode;
}

export function RequestForm({
  value,
  onChange,
  onSubmit,
  loading,
  examples,
  turnstileSlot,
}: RequestFormProps) {
  const [localError, setLocalError] = useState<string | null>(null);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const pedido = value.trim();
    if (!pedido) {
      setLocalError("Escreva um pedido para analisar.");
      return;
    }
    setLocalError(null);
    onSubmit(pedido);
  }

  return (
    <form onSubmit={handleSubmit} className="mt-8" noValidate>
      <label htmlFor="pedido" className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
        Pedido — o que a Quimera deve investigar
      </label>
      <Textarea
        id="pedido"
        name="request"
        value={value}
        maxLength={500}
        rows={3}
        onChange={(e) => onChange(e.target.value)}
        placeholder="ex.: clínicas odontológicas em Santo André abertas há mais de 2 anos"
        className="mt-2 border-input bg-card"
        aria-describedby="contador"
      />
      <p id="contador" className="mt-1 text-right font-mono text-xs text-muted-foreground">
        {value.length}/500
      </p>
      <div className="mt-3">
        <ExampleChips examples={examples} onPick={onChange} />
      </div>
      <div className="mt-5">{turnstileSlot}</div>
      <Button
        type="submit"
        disabled={loading}
        className="mt-5 bg-primary px-8 py-6 text-sm font-semibold uppercase tracking-widest text-primary-foreground hover:opacity-90"
      >
        {loading ? "Analisando…" : "Analisar"}
      </Button>
      <p role="status" aria-live="polite" className="mt-3 min-h-6 font-mono text-sm text-muted-foreground">
        {localError ?? ""}
      </p>
    </form>
  );
}
```

- [ ] **Step 6: Rodar para ver passar e commitar**

Run: `npm test -- tests/request-form.test.tsx`
Esperado: PASS (5 testes).

```bash
git add frontend/src/components/Hero.tsx frontend/src/components/ExampleChips.tsx frontend/src/components/RequestForm.tsx frontend/tests/request-form.test.tsx
git commit -m "front: hero, chips de pedidos-modelo e formulario do pedido"
```

---

### Task 6: StatusBanner — todos os estados da API (TDD)

**Files:**
- Create: `frontend/src/components/StatusBanner.tsx`
- Test: `frontend/tests/status-banner.test.tsx`

- [ ] **Step 1: Escrever o teste que falha**

`frontend/tests/status-banner.test.tsx`:

```tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBanner, type ErrorState } from "@/components/StatusBanner";

describe("StatusBanner", () => {
  it("401 pede novo captcha", () => {
    render(<StatusBanner error={{ kind: "http", status: 401, body: null, retryAfter: null }} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/captcha/i);
  });

  it("429 mostra Retry-After quando presente", () => {
    render(<StatusBanner error={{ kind: "http", status: 429, body: null, retryAfter: 30 }} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/30 s/i);
  });

  it("503 mostra o reason do servidor (as 4 variantes)", () => {
    const variantes = [
      "orçamento diário esgotado; apenas pedidos já vistos são respondidos",
      "orçamento diário restante não cobre esta consulta",
      "consulta excede o teto de bytes",
      "a base de empresas está sendo atualizada",
    ];
    for (const reason of variantes) {
      const { unmount } = render(
        <StatusBanner error={{ kind: "http", status: 503, body: { error: "x", reason }, retryAfter: null }} />,
      );
      expect(screen.getByRole("alert")).toHaveTextContent(reason);
      unmount();
    }
  });

  it("502 e 500 usam o reason com fallback", () => {
    render(<StatusBanner error={{ kind: "http", status: 502, body: null, retryAfter: null }} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/extração|reformular/i);
  });

  it("rede mostra botão de tentar de novo", () => {
    const onRetry = () => {};
    render(<StatusBanner error={{ kind: "network" }} onRetry={onRetry} />);
    expect(screen.getByRole("button", { name: /tentar de novo/i })).toBeInTheDocument();
  });

  it("recusa não é erro: trata informativo", () => {
    render(<StatusBanner refusal="pedido recusado: dado pessoal" />);
    expect(screen.getByRole("status")).toHaveTextContent(/dado pessoal/i);
  });
});

describe("ErrorState", () => {
  it("é um discriminated union usável pelo Home", () => {
    const e: ErrorState = { kind: "network" };
    expect(e.kind).toBe("network");
  });
});
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `npm test -- tests/status-banner.test.tsx`
Esperado: FAIL — import não resolvido.

- [ ] **Step 3: Implementar `frontend/src/components/StatusBanner.tsx`**

```tsx
import { Button } from "@/components/ui/button";
import type { ApiErrorBody } from "@/lib/types";

export type ErrorState =
  | { kind: "network" }
  | { kind: "http"; status: number; body: ApiErrorBody | null; retryAfter: number | null };

function httpMessage(state: Extract<ErrorState, { kind: "http" }>): string {
  const reason = state.body?.reason?.trim();
  if (reason) return reason;
  switch (state.status) {
    case 401:
      return "Não verificado: complete o desafio Turnstile e tente de novo.";
    case 422:
      return "Pedido inválido: escreva um pedido com até 500 caracteres.";
    case 429:
      return state.retryAfter
        ? `Muitas tentativas; aguarde ${state.retryAfter} s.`
        : "Muitas tentativas; aguarde alguns minutos.";
    case 500:
      return "Erro interno; tente de novo em instantes.";
    case 502:
      return "A extração falhou; reformule o pedido e tente de novo.";
    case 504:
      return "A execução excedeu o tempo limite; tente um pedido mais específico.";
    default:
      return `Erro ${state.status}; tente de novo.`;
  }
}

export function StatusBanner({
  error,
  refusal,
  onRetry,
}: {
  error?: ErrorState;
  refusal?: string | null;
  onRetry?: () => void;
}) {
  if (refusal) {
    return (
      <div role="status" className="rounded-xl border border-warning/40 bg-warning/10 p-5 text-warning-foreground">
        <p className="font-mono text-xs uppercase tracking-widest text-warning">Pedido não atendido</p>
        <p className="mt-2 text-sm">{refusal}</p>
        <p className="mt-2 text-sm text-muted-foreground">
          A política pública não responde pedidos de dado pessoal — de sócios, contato ou
          qualquer pessoa física.
        </p>
      </div>
    );
  }
  if (!error) return null;
  const texto = error.kind === "network" ? "Não foi possível conectar à API." : httpMessage(error);
  return (
    <div role="alert" className="rounded-xl border border-destructive/40 bg-destructive/10 p-5">
      <p className="font-mono text-xs uppercase tracking-widest text-destructive">
        Pedido não atendido
      </p>
      <p className="mt-2 text-sm">{texto}</p>
      {onRetry ? (
        <Button
          type="button"
          variant="outline"
          className="mt-4 border-border bg-transparent"
          onClick={onRetry}
        >
          Tentar de novo
        </Button>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 4: Rodar para ver passar e commitar**

Run: `npm test -- tests/status-banner.test.tsx`
Esperado: PASS.

```bash
git add frontend/src/components/StatusBanner.tsx frontend/tests/status-banner.test.tsx
git commit -m "front: banner de estados (401/422/429+Retry-After/500/502/503x4/504/rede)"
```

---

### Task 7: ResultPanel — Interpretação, CNAEs e SQL (TDD)

**Files:**
- Create: `frontend/src/components/FiltersBadge.tsx`, `frontend/src/components/CnaeList.tsx`, `frontend/src/components/SqlBlock.tsx`, `frontend/src/components/ResultPanel.tsx`
- Test: `frontend/tests/result-panel.test.tsx`

- [ ] **Step 1: Escrever o teste que falha**

`frontend/tests/result-panel.test.tsx`:

```tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ResultPanel } from "@/components/ResultPanel";
import type { LeadsResponse } from "@/lib/types";

const base: LeadsResponse = {
  refused: false,
  refusal_reason: null,
  filters: {
    cnae_query: "clínicas odontológicas",
    cnae_codes: ["8630-5/01"],
    ufs: ["SP"],
    municipio_ids: ["3547807"],
    municipio_names: ["Santo André"],
    min_age_years: 2,
    max_age_years: null,
    min_capital: null,
    portes: ["pequena"],
    include_mei: false,
    min_estabelecimentos: null,
    regimes: [],
    bairros: [],
    cep_centro: null,
    raio_km: null,
    com_dominio_proprio: false,
    limit: 50,
  },
  cnae_matches: [["8630-5/01", "Atividade médica ambulatorial odontológica", 0.92]],
  municipio_resolution: {},
  snapshot: { "quimera.leads": "2026-09-01" },
  rows: [],
  bytes_processed: 33 * 1024 ** 2,
  bytes_billed: 33 * 1024 ** 2,
  estimated_cost_usd: 0.0002,
  latency_ms: 4123.4,
  timings_ms: { extract: 1200, query: 800 },
  model: "gemini-2.5-flash",
  policy: "public",
  request_normalized: "clinicas odontologicas",
  warnings: ["Cerca de 9% dos estabelecimentos não têm coordenada."],
  query_sql: "SELECT * FROM `quimera.leads` WHERE sigla_uf = @uf",
  cached: true,
  cache_mode: false,
};

describe("ResultPanel", () => {
  it("mostra interpretação, CNAEs e SQL com valores medidos em mono", () => {
    render(<ResultPanel data={base} browserMs={1.2} />);
    expect(screen.getByText(/interpretação/i)).toBeInTheDocument();
    expect(screen.getByText("Santo André")).toBeInTheDocument();
    expect(screen.getByText("8630-5/01")).toBeInTheDocument();
    expect(screen.getByText(/0,920/)).toBeInTheDocument();
    expect(screen.getByText(/SELECT \* FROM/)).toBeInTheDocument();
    expect(screen.getByText("2026-09-01")).toBeInTheDocument();
    expect(screen.getByText(/em cache/i)).toBeInTheDocument();
  });

  it("renderiza ressalvas quando houver", () => {
    render(<ResultPanel data={base} browserMs={1.2} />);
    expect(screen.getByText(/9% dos estabelecimentos/)).toBeInTheDocument();
  });

  it("sem CNAEs não quebra", () => {
    render(<ResultPanel data={{ ...base, cnae_matches: [] }} browserMs={1.2} />);
    expect(screen.getByText(/interpretação/i)).toBeInTheDocument();
    expect(screen.queryByText(/classificação/i)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `npm test -- tests/result-panel.test.tsx`
Esperado: FAIL — import não resolvido.

- [ ] **Step 3: Implementar `frontend/src/components/FiltersBadge.tsx`**

```tsx
import { Badge } from "@/components/ui/badge";
import type { ReactNode } from "react";
import type { LeadFilters } from "@/lib/types";

function chip(label: string, valor: string) {
  return (
    <Badge
      key={label + valor}
      variant="secondary"
      className="border-border bg-secondary font-mono text-xs font-normal text-foreground"
    >
      <span className="text-muted-foreground">{label}:</span>&nbsp;{valor}
    </Badge>
  );
}

export function FiltersBadge({ filters }: { filters: LeadFilters | null }) {
  if (!filters) return null;
  const chips: ReactNode[] = [];
  if (filters.cnae_query) chips.push(chip("atividade", filters.cnae_query));
  for (const uf of filters.ufs ?? []) chips.push(chip("uf", uf));
  for (const mun of filters.municipio_names ?? []) chips.push(chip("município", mun));
  if (filters.min_age_years != null) chips.push(chip("idade mín.", `${filters.min_age_years} anos`));
  if (filters.max_age_years != null) chips.push(chip("idade máx.", `${filters.max_age_years} anos`));
  if (filters.min_capital != null) chips.push(chip("capital mín.", String(filters.min_capital)));
  for (const p of filters.portes ?? []) chips.push(chip("porte", p));
  for (const b of filters.bairros ?? []) chips.push(chip("bairro", b));
  if (filters.cep_centro) chips.push(chip("raio", `${filters.cep_centro} + ${filters.raio_km ?? 5} km`));
  if (filters.regimes?.length) chips.push(chip("regime", filters.regimes.join(", ")));
  if (filters.com_dominio_proprio) chips.push(chip("domínio próprio", "sim"));
  if (filters.min_estabelecimentos != null)
    chips.push(chip("unidades mín.", String(filters.min_estabelecimentos)));
  chips.push(chip("limite", `${filters.limit} empresas`));
  return (
    <div>
      <ul className="flex flex-wrap gap-2">{chips.map((c, i) => <li key={i}>{c}</li>)}</ul>
      <p className="mt-3 font-mono text-xs text-muted-foreground">
        filtro aplicado pela policy pública: sem MEI, sem contato, sem pessoa física.
      </p>
    </div>
  );
}
```

- [ ] **Step 4: Implementar `frontend/src/components/CnaeList.tsx` e `frontend/src/components/SqlBlock.tsx`**

`CnaeList.tsx`:

```tsx
import type { LeadsResponse } from "@/lib/types";

export function CnaeList({ matches }: { matches: LeadsResponse["cnae_matches"] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="pb-2 text-left font-mono text-xs text-muted-foreground">
          códigos escolhidos por similaridade de embeddings (top-k)
        </caption>
        <thead>
          <tr className="border-b border-foreground/20 text-left font-mono text-xs uppercase tracking-widest text-muted-foreground">
            <th className="py-2 pr-4">Código</th>
            <th className="py-2 pr-4">Descrição</th>
            <th className="py-2 text-right">Simil.</th>
          </tr>
        </thead>
        <tbody>
          {matches.map(([codigo, descricao, simil]) => (
            <tr key={codigo} className="border-b border-border">
              <td className="py-2 pr-4 font-mono">{codigo}</td>
              <td className="py-2 pr-4">{descricao}</td>
              <td className="py-2 text-right font-mono">{simil.toFixed(3).replace(".", ",")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

`SqlBlock.tsx`:

```tsx
import { useState } from "react";
import { Button } from "@/components/ui/button";

export function SqlBlock({ sql }: { sql: string }) {
  const [copiado, setCopiado] = useState(false);
  return (
    <div>
      <pre
        tabIndex={0}
        className="overflow-x-auto rounded-lg border border-border bg-card p-4 font-mono text-xs leading-relaxed"
      >
        {sql}
      </pre>
      <Button
        type="button"
        variant="outline"
        className="mt-2 border-border bg-transparent font-mono text-xs"
        onClick={() => {
          void navigator.clipboard?.writeText(sql).then(() => setCopiado(true));
        }}
      >
        {copiado ? "copiado" : "copiar SQL"}
      </Button>
    </div>
  );
}
```

- [ ] **Step 5: Implementar `frontend/src/components/ResultPanel.tsx` (parcial — RankingTable e CostSummary entram na Task 8)**

```tsx
import type { LeadsResponse } from "@/lib/types";
import { FiltersBadge } from "./FiltersBadge";
import { CnaeList } from "./CnaeList";
import { SqlBlock } from "./SqlBlock";
import { RankingTable } from "./RankingTable";
import { CostSummary } from "./CostSummary";

function Section({
  titulo,
  children,
}: {
  titulo: string;
  children: React.ReactNode;
}) {
  return (
    <section className="border-t border-border py-8 first:border-t-0">
      <h2 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
        {titulo}
      </h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}

export function ResultPanel({ data, browserMs }: { data: LeadsResponse; browserMs: number }) {
  const snapshot = data.snapshot ? Object.values(data.snapshot)[0] : null;
  return (
    <div>
      {data.cached ? (
        <p className="mb-6">
          <span className="rounded-full border border-success/50 px-3 py-1 font-mono text-xs uppercase tracking-widest text-success">
            Em cache
          </span>
        </p>
      ) : null}
      <Section titulo="1 — Interpretação do pedido">
        <FiltersBadge filters={data.filters} />
      </Section>
      {data.cnae_matches.length ? (
        <Section titulo="2 — Classificação CNAE">
          <CnaeList matches={data.cnae_matches} />
        </Section>
      ) : null}
      <Section titulo="3 — Consulta">
        {data.query_sql ? (
          <SqlBlock sql={data.query_sql} />
        ) : (
          <p className="text-sm text-muted-foreground">Consulta não executada (ver ressalvas).</p>
        )}
        <dl className="mt-4 grid max-w-2xl grid-cols-1 gap-2 font-mono text-sm sm:grid-cols-2">
          <div>
            <dt className="text-xs uppercase tracking-widest text-muted-foreground">Snapshot da base</dt>
            <dd>{snapshot ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-widest text-muted-foreground">SQL</dt>
            <dd className="text-xs text-muted-foreground">montado pelo sistema — o modelo não escreve SQL</dd>
          </div>
        </dl>
      </Section>
      <Section titulo="4 — Ranking de empresas">
        <RankingTable rows={data.rows} />
      </Section>
      <Section titulo="5 — Custos e latência">
        <CostSummary data={data} browserMs={browserMs} />
      </Section>
      {data.warnings.length ? (
        <Section titulo="6 — Ressalvas">
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            {data.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Section>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 6: Criar stubs de `RankingTable.tsx` e `CostSummary.tsx` para o teste passar (implementação completa na Task 8)**

`RankingTable.tsx` (stub mínimo por ora):

```tsx
import type { LeadRow } from "@/lib/types";

export function RankingTable({ rows }: { rows: LeadRow[] }) {
  if (!rows.length) return <p className="text-sm text-muted-foreground">Nenhuma empresa atendida ao pedido (ver ressalvas).</p>;
  return <p className="text-sm text-muted-foreground">{rows.length} empresas.</p>;
}
```

`CostSummary.tsx` (stub mínimo por ora):

```tsx
import type { LeadsResponse } from "@/lib/types";

export function CostSummary({ data, browserMs }: { data: LeadsResponse; browserMs: number }) {
  return (
    <p className="font-mono text-sm">
      {data.latency_ms} ms · {browserMs} s
    </p>
  );
}
```

- [ ] **Step 7: Rodar para ver passar e commitar**

Run: `npm test` → esperado: PASS.

```bash
git add frontend/src/components/ResultPanel.tsx frontend/src/components/FiltersBadge.tsx frontend/src/components/CnaeList.tsx frontend/src/components/SqlBlock.tsx frontend/src/components/RankingTable.tsx frontend/src/components/CostSummary.tsx frontend/tests/result-panel.test.tsx
git commit -m "front: painel de resultado (interpretacao, CNAEs, SQL) com stubs de ranking/custos"
```

---

### Task 8: RankingTable + CostSummary completos (TDD)

**Files:**
- Modify: `frontend/src/components/RankingTable.tsx`, `frontend/src/components/CostSummary.tsx`
- Test: `frontend/tests/ranking-table.test.tsx`

- [ ] **Step 1: Escrever o teste que falha**

`frontend/tests/ranking-table.test.tsx`:

```tsx
import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { RankingTable } from "@/components/RankingTable";
import { CostSummary } from "@/components/CostSummary";
import type { LeadRow, LeadsResponse } from "@/lib/types";

const rows: LeadRow[] = [
  {
    razao_social: "CLINICA ALFA",
    nome_fantasia: null,
    sigla_uf: "SP",
    municipio: "Santo André",
    cnae_fiscal_principal: "8630-5/01",
    data_inicio_atividade: "20150110",
    capital_social: 100000,
    porte: "pequena",
    score: 87,
    motivos_score: ["idade 11 anos"],
  },
  {
    razao_social: "CLINICA BETA",
    nome_fantasia: "Beta Odonto",
    sigla_uf: "SP",
    municipio: "Santo André",
    cnae_fiscal_principal: "8630-5/01",
    data_inicio_atividade: "20240110",
    capital_social: 1000,
    porte: "micro",
    score: 42,
    motivos_score: ["idade 2 anos"],
  },
];

describe("RankingTable", () => {
  it("ordena como chega (a ordem é a da nota) e mostra score em mono", () => {
    render(<RankingTable rows={rows} />);
    const corpo = screen.getAllByRole("rowgroup")[1];
    const linhas = within(corpo).getAllByRole("row");
    expect(linhas[0]).toHaveTextContent("CLINICA ALFA");
    expect(linhas[1]).toHaveTextContent("CLINICA BETA");
    expect(screen.getByText("87")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("10/01/2015")).toBeInTheDocument();
    expect(screen.getByText(/2 empresas/)).toBeInTheDocument();
  });

  it("vazio mostra convite, não tabela", () => {
    render(<RankingTable rows={[]} />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText(/nenhuma empresa/i)).toBeInTheDocument();
  });

  it("motivos ficam em details por linha", () => {
    render(<RankingTable rows={rows} />);
    expect(screen.getAllByText("motivos")).toHaveLength(2);
    expect(screen.getAllByText("idade 11 anos")).toHaveLength(1);
  });
});

describe("CostSummary", () => {
  it("mostra bytes, custo, latencia, timings, orcamento, modelo e cache_mode", () => {
    const data = {
      bytes_billed: 33 * 1024 ** 2,
      estimated_cost_usd: 0.000123,
      latency_ms: 4123.4,
      timings_ms: { extract: 1200.5, query: 800 },
      model: "gemini-2.5-flash",
      cache_mode: true,
      cached: false,
      warnings: [],
      rows: [],
    } as unknown as LeadsResponse;
    render(<CostSummary data={data} browserMs={1.23} budgetRemainingBytes={1024 ** 3} />);
    expect(screen.getByText("33,0 MB")).toBeInTheDocument();
    expect(screen.getByText("US$ 0,000123")).toBeInTheDocument();
    expect(screen.getByText("4.123 ms")).toBeInTheDocument();
    expect(screen.getByText("1,00 GB")).toBeInTheDocument();
    expect(screen.getByText("gemini-2.5-flash")).toBeInTheDocument();
    expect(screen.getByText(/modo cache/i)).toBeInTheDocument();
    expect(screen.getByText(/extract 1\.201 ms/)).toBeInTheDocument();
    expect(screen.getByText("1,2 s")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `npm test -- tests/ranking-table.test.tsx`
Esperado: FAIL — os stubs não implementam as expectativas.

- [ ] **Step 3: Substituir `frontend/src/components/RankingTable.tsx`**

```tsx
import type { LeadRow } from "@/lib/types";
import { fmtData, fmtNumOrDash } from "@/lib/format";

export function RankingTable({ rows }: { rows: LeadRow[] }) {
  if (!rows.length) {
    return (
      <p className="text-sm text-muted-foreground">
        Nenhuma empresa atendida ao pedido (ver ressalvas).
      </p>
    );
  }
  return (
    <div>
      <p className="mb-3 font-mono text-xs text-muted-foreground">
        {rows.length} empresas — ordenadas pela nota do ICP
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-foreground/20 text-left font-mono text-xs uppercase tracking-widest text-muted-foreground">
              <th className="py-2 pr-3">#</th>
              <th className="py-2 pr-3">Empresa</th>
              <th className="py-2 pr-3">Local</th>
              <th className="py-2 pr-3">CNAE</th>
              <th className="py-2 pr-3">Início</th>
              <th className="py-2 pr-3 text-right">Capital (R$)</th>
              <th className="py-2 pr-3">Porte</th>
              <th className="py-2 pr-3 text-right">Nota</th>
              <th className="py-2">
                <span className="sr-only">Motivos</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.razao_social}-${i}`} className="border-b border-border align-top">
                <td className="py-3 pr-3 font-mono text-muted-foreground">{i + 1}</td>
                <td className="py-3 pr-3">
                  <span className="font-medium">{r.razao_social}</span>
                  {r.nome_fantasia ? (
                    <span className="block text-xs text-muted-foreground">{r.nome_fantasia}</span>
                  ) : null}
                </td>
                <td className="py-3 pr-3">
                  {r.municipio ?? "—"}/{r.sigla_uf ?? "—"}
                </td>
                <td className="py-3 pr-3 font-mono text-xs">{r.cnae_fiscal_principal ?? "—"}</td>
                <td className="py-3 pr-3 font-mono text-xs">{fmtData(r.data_inicio_atividade)}</td>
                <td className="py-3 pr-3 text-right font-mono">{fmtNumOrDash(r.capital_social)}</td>
                <td className="py-3 pr-3">{r.porte ?? "—"}</td>
                <td className="py-3 pr-3 text-right">
                  <div className="flex items-center justify-end gap-2">
                    <span
                      aria-hidden
                      className="h-1.5 w-16 overflow-hidden rounded-full bg-muted"
                    >
                      <span
                        className="block h-full rounded-full bg-accent"
                        style={{ width: `${Math.max(0, Math.min(100, r.score ?? 0))}%` }}
                      />
                    </span>
                    <span className="font-mono">{fmtNumOrDash(r.score)}</span>
                  </div>
                </td>
                <td className="py-3">
                  <details>
                    <summary className="cursor-pointer font-mono text-xs text-accent">motivos</summary>
                    <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-muted-foreground">
                      {(r.motivos_score ?? []).map((m) => (
                        <li key={m}>{m}</li>
                      ))}
                    </ul>
                  </details>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Substituir `frontend/src/components/CostSummary.tsx`**

```tsx
import type { LeadsResponse } from "@/lib/types";
import { fmtBytes, fmtMs, fmtUSD } from "@/lib/format";

function Linha({ label, valor }: { label: string; valor: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-widest text-muted-foreground">{label}</dt>
      <dd className="font-mono text-sm">{valor}</dd>
    </div>
  );
}

export function CostSummary({
  data,
  browserMs,
  budgetRemainingBytes,
}: {
  data: LeadsResponse;
  browserMs: number;
  budgetRemainingBytes?: number | null;
}) {
  const etapas = Object.entries(data.timings_ms ?? {})
    .map(([etapa, ms]) => `${etapa} ${fmtMs(ms)}`)
    .join(" · ");
  return (
    <div>
      {data.cache_mode ? (
        <p className="mb-4">
          <span className="rounded-full border border-warning/50 px-3 py-1 font-mono text-xs uppercase tracking-widest text-warning">
            Modo cache — orçamento do dia esgotado
          </span>
        </p>
      ) : null}
      <dl className="grid max-w-2xl grid-cols-1 gap-4 sm:grid-cols-2">
        <Linha label="Bytes cobrados" valor={fmtBytes(data.bytes_billed)} />
        <Linha label="Custo estimado" valor={fmtUSD(data.estimated_cost_usd)} />
        <Linha label="Latência do pipeline" valor={fmtMs(data.latency_ms)} />
        <Linha label="No navegador" valor={`${browserMs.toFixed(1).replace(".", ",")} s`} />
        <Linha
          label="Orçamento diário restante"
          valor={budgetRemainingBytes == null ? "—" : fmtBytes(budgetRemainingBytes)}
        />
        <Linha label="Modelo" valor={data.model || "—"} />
      </dl>
      {etapas ? <p className="mt-4 font-mono text-xs text-muted-foreground">{etapas}</p> : null}
    </div>
  );
}
```

- [ ] **Step 5: Ajustar `ResultPanel.tsx` para repassar `budgetRemainingBytes` (prop opcional)**

Em `ResultPanel`, a assinatura vira:

```tsx
export function ResultPanel({
  data,
  browserMs,
  budgetRemainingBytes,
}: {
  data: LeadsResponse;
  browserMs: number;
  budgetRemainingBytes?: number | null;
}) {
```

e o uso em `CostSummary`:

```tsx
<CostSummary data={data} browserMs={browserMs} budgetRemainingBytes={budgetRemainingBytes} />
```

- [ ] **Step 6: Rodar para ver passar e commitar**

Run: `npm test` → esperado: PASS (os testes da Task 7 do ResultPanel continuam verdes).

```bash
git add frontend/src/components/RankingTable.tsx frontend/src/components/CostSummary.tsx frontend/src/components/ResultPanel.tsx frontend/tests/ranking-table.test.tsx
git commit -m "front: ranking denso com barra de nota e painel de custos completo"
```

---

### Task 9: PipelineSteps + Footer + montagem do Home

**Files:**
- Create: `frontend/src/components/PipelineSteps.tsx`, `frontend/src/components/Footer.tsx`, `frontend/src/pages/Home.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Implementar `frontend/src/components/PipelineSteps.tsx`**

```tsx
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
```

- [ ] **Step 2: Implementar `frontend/src/components/Footer.tsx`**

```tsx
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
```

- [ ] **Step 3: Implementar `frontend/src/pages/Home.tsx` (máquina de estados da busca)**

```tsx
import { useEffect, useRef, useState } from "react";
import { Hero } from "@/components/Hero";
import { RequestForm } from "@/components/RequestForm";
import { StatusBanner, type ErrorState } from "@/components/StatusBanner";
import { ResultPanel } from "@/components/ResultPanel";
import { PipelineSteps } from "@/components/PipelineSteps";
import { Footer } from "@/components/Footer";
import { fetchConfig, fetchHealth, submitLead } from "@/lib/api";
import type { LeadsResponse } from "@/lib/types";
import { TurnstileController } from "@/lib/turnstile";

const EXEMPLOS = [
  "clínicas odontológicas em Santo André abertas há mais de 2 anos",
  "padarias artesanais em Curitiba",
  "transportadoras de carga em São Paulo capital",
  "escritórios de contabilidade em Belo Horizonte",
];

type SearchState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success"; data: LeadsResponse; browserMs: number }
  | { kind: "refused"; data: LeadsResponse }
  | { kind: "error"; error: ErrorState };

export default function Home() {
  const [pedido, setPedido] = useState("");
  const [state, setState] = useState<SearchState>({ kind: "idle" });
  const [version, setVersion] = useState<string | null>(null);
  const [budgetRemaining, setBudgetRemaining] = useState<number | null>(null);
  const turnstile = useRef(new TurnstileController());
  const turnstileBox = useRef<HTMLDivElement | null>(null);
  const resultadoRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    fetchHealth()
      .then((h) => {
        setVersion(h.version);
        setBudgetRemaining(h.budget_remaining_bytes);
      })
      .catch(() => {});
    fetchConfig()
      .then((cfg) => {
        if (cfg.turnstile_site_key && turnstileBox.current) {
          turnstile.current.render(turnstileBox.current, cfg.turnstile_site_key);
        }
      })
      .catch(() => {});
  }, []);

  async function handleSearch(text: string) {
    setState({ kind: "loading" });
    const inicio = performance.now();
    try {
      const token = turnstile.current.consume();
      const data = await submitLead(text, token);
      const browserMs = (performance.now() - inicio) / 1000;
      if (data.refused) setState({ kind: "refused", data });
      else setState({ kind: "success", data, browserMs });
    } catch (err) {
      const error: ErrorState =
        err instanceof Error && err.name === "NetworkError"
          ? { kind: "network" }
          : {
              kind: "http",
              status: (err as { status?: number }).status ?? 0,
              body: (err as { body?: { error: string; reason: string } | null }).body ?? null,
              retryAfter: null,
            };
      setState({ kind: "error", error });
    }
  }

  return (
    <div className="min-h-screen">
      <div className="mx-auto max-w-5xl px-6">
        <Hero version={version}>
          <RequestForm
            value={pedido}
            onChange={setPedido}
            onSubmit={handleSearch}
            loading={state.kind === "loading"}
            examples={EXEMPLOS}
            turnstileSlot={<div ref={turnstileBox} className="min-h-16" />}
          />
        </Hero>

        <div
          ref={resultadoRef}
          tabIndex={-1}
          className="outline-none"
          aria-live="polite"
        >
          {state.kind === "idle" ? (
            <p className="py-16 text-center text-muted-foreground">
              Escreva um pedido acima — ou escolha um dos modelos — e a Quimera devolve o
              laudo completo da investigação.
            </p>
          ) : null}
          {state.kind === "loading" ? (
            <div className="space-y-4 py-16" aria-busy="true">
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-24 animate-pulse rounded-2xl bg-card" />
              ))}
            </div>
          ) : null}
          {state.kind === "refused" ? (
            <div className="py-10">
              <StatusBanner refusal={state.data.refusal_reason ?? "pedido recusado"} />
            </div>
          ) : null}
          {state.kind === "error" ? (
            <div className="py-10">
              <StatusBanner
                error={state.error}
                onRetry={() => void handleSearch(pedido.trim())}
              />
            </div>
          ) : null}
          {state.kind === "success" ? (
            <div className="py-10">
              <ResultPanel
                data={state.data}
                browserMs={state.browserMs}
                budgetRemainingBytes={budgetRemaining}
              />
            </div>
          ) : null}
        </div>

        <PipelineSteps />
        <Footer />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Trocar `App.tsx` para as rotas reais (com placeholder de Metrics até a Task 10)**

```tsx
import { BrowserRouter, Route, Routes } from "react-router-dom";
import Home from "./pages/Home";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
      </Routes>
    </BrowserRouter>
  );
}
```

- [ ] **Step 5: Verificar no navegador e commitar**

Run: `npm test` → esperado: PASS (nada quebrou).
Run: `npm run dev` → abrir `http://localhost:5173`: hero com glow, chips, form; sem erros no console.

```bash
git add frontend/src/components/PipelineSteps.tsx frontend/src/components/Footer.tsx frontend/src/pages/Home.tsx frontend/src/App.tsx
git commit -m "front: home completa (hero, busca, estados, pipeline, rodape)"
```

---

### Task 10: Página /metricas + MetricSuite (TDD)

**Files:**
- Create: `frontend/src/components/MetricSuite.tsx`, `frontend/src/pages/Metrics.tsx`
- Test: `frontend/tests/metric-suite.test.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Escrever o teste que falha**

`frontend/tests/metric-suite.test.tsx`:

```tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MetricSuite } from "@/components/MetricSuite";

const suite = {
  titulo: "Extração de filtros",
  meta: { date: "2026-09-28", commit: "abc1234" },
  linhas: [
    { rotulo: "Acerto por campo", medido: 0.87, limiar: 0.85 },
    { rotulo: "Recusa correta", medido: 1.0, limiar: 1.0 },
    { rotulo: "Acerto exato do conjunto", medido: 0.6, limiar: 0.9 },
    { rotulo: "Recusa indevida", medido: 0.01, limiar: null },
    { rotulo: "Casos", medido: 42, limiar: null, quantidade: true },
  ],
};

describe("MetricSuite", () => {
  it("marca acima e abaixo do limiar", () => {
    render(<MetricSuite numero={1} {...suite} />);
    expect(screen.getByText("87,0%")).toBeInTheDocument();
    expect(screen.getAllByText(/acima do limiar/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("abaixo do limiar")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText(/abc1234/)).toBeInTheDocument();
  });

  it("linha sem limiar não mostra estado", () => {
    render(<MetricSuite numero={3} titulo="Ponta a ponta" meta={{ date: "2026-09-28", commit: "x" }} linhas={[{ rotulo: "Casos", medido: 20, limiar: null, quantidade: true }]} />);
    expect(screen.queryByText(/limiar/)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `npm test -- tests/metric-suite.test.tsx`
Esperado: FAIL — import não resolvido.

- [ ] **Step 3: Implementar `frontend/src/components/MetricSuite.tsx`**

```tsx
import { fmtNumOrDash, fmtPct } from "@/lib/format";

export interface MetricLinha {
  rotulo: string;
  medido: number | null;
  limiar: number | null;
  quantidade?: boolean;
}

export function MetricSuite({
  numero,
  titulo,
  meta,
  linhas,
}: {
  numero: number;
  titulo: string;
  meta: { date?: string; commit?: string };
  linhas: MetricLinha[];
}) {
  return (
    <section className="rounded-2xl border border-border bg-card p-6">
      <h2 className="flex items-baseline gap-3 font-semibold">
        <span className="font-mono text-sm text-accent">{numero}</span>
        {titulo}
      </h2>
      <p className="mt-1 font-mono text-xs text-muted-foreground">
        execução: {meta.date ?? "?"} · commit {meta.commit ?? "?"}
      </p>
      <table className="mt-4 w-full text-sm">
        <thead>
          <tr className="border-b border-foreground/20 text-left font-mono text-xs uppercase tracking-widest text-muted-foreground">
            <th className="py-2 pr-4">Métrica</th>
            <th className="py-2 pr-4 text-right">Medido</th>
            <th className="py-2 pr-4 text-right">Limiar</th>
            <th className="py-2">
              <span className="sr-only">Estado</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {linhas.map((l) => {
            const batido = l.medido != null && l.limiar != null && l.medido >= l.limiar;
            return (
              <tr key={l.rotulo} className="border-b border-border">
                <td className="py-2 pr-4">{l.rotulo}</td>
                <td className="py-2 pr-4 text-right font-mono">
                  {l.quantidade ? fmtNumOrDash(l.medido) : fmtPct(l.medido)}
                </td>
                <td className="py-2 pr-4 text-right font-mono">
                  {l.limiar == null ? "—" : l.quantidade ? fmtNumOrDash(l.limiar) : fmtPct(l.limiar)}
                </td>
                <td className="py-2">
                  {l.limiar == null || l.medido == null ? null : batido ? (
                    <span className="rounded-full border border-success/50 px-2 py-0.5 font-mono text-xs uppercase text-success">
                      acima do limiar
                    </span>
                  ) : (
                    <span className="rounded-full border border-destructive/50 px-2 py-0.5 font-mono text-xs uppercase text-destructive">
                      abaixo do limiar
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
```

- [ ] **Step 4: Implementar `frontend/src/pages/Metrics.tsx`**

```tsx
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { MetricSuite, type MetricLinha } from "@/components/MetricSuite";
import { Footer } from "@/components/Footer";
import { fetchMetrics } from "@/lib/api";
import { selectE2e, selectUltima } from "@/lib/metrics";
import type { MetricsResponse } from "@/lib/types";

function pctLinha(rotulo: string, medido: number | undefined, limiar: number | undefined): MetricLinha {
  return { rotulo, medido: medido ?? null, limiar: limiar ?? null };
}

function qtdLinha(rotulo: string, medido: number | undefined): MetricLinha {
  return { rotulo, medido: medido ?? null, limiar: null, quantidade: true };
}

export default function Metrics() {
  const [dados, setDados] = useState<MetricsResponse | null>(null);
  const [erro, setErro] = useState(false);

  useEffect(() => {
    fetchMetrics()
      .then(setDados)
      .catch(() => setErro(true));
  }, []);

  const ext = selectUltima(dados?.extraction);
  const cnae = selectUltima(dados?.cnae);
  const e2e = selectE2e(dados?.e2e);
  const lim = dados?.thresholds ?? {};

  return (
    <div className="min-h-screen">
      <div className="mx-auto max-w-5xl px-6">
        <header className="border-b border-border py-10">
          <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
            Anexo A
          </p>
          <h1 className="mt-2 text-3xl font-bold tracking-tight">Métricas medidas</h1>
          <p className="mt-3 max-w-2xl text-muted-foreground">
            Resultados medidos em <code className="font-mono text-xs">eval/results/</code>,
            comparados aos limiares de{" "}
            <code className="font-mono text-xs">eval/thresholds.json</code>. Nenhum número é
            escrito à mão.
          </p>
          <p className="mt-4">
            <Link to="/" className="text-accent underline-offset-4 hover:underline">
              ← voltar à demo
            </Link>
          </p>
        </header>

        <main className="space-y-6 py-10">
          {erro ? (
            <p className="text-muted-foreground">Não foi possível carregar as métricas.</p>
          ) : null}
          {!dados && !erro ? (
            <p className="font-mono text-sm text-muted-foreground">Carregando métricas…</p>
          ) : null}
          {ext ? (
            <MetricSuite
              numero={1}
              titulo="Extração de filtros"
              meta={{ date: ext.date, commit: ext.commit }}
              linhas={[
                pctLinha("Recusa correta (dado pessoal)", ext.metrics?.correct_refusal_rate, lim.correct_refusal_rate),
                pctLinha("Recusa indevida", ext.metrics?.false_refusal_rate, undefined),
                pctLinha("Acerto por campo", ext.metrics?.overall_field_accuracy, lim.overall_field_accuracy),
                pctLinha("Acerto exato do conjunto", ext.metrics?.exact_match_rate, undefined),
                qtdLinha("Casos", ext.metrics?.n_cases),
              ]}
            />
          ) : null}
          {cnae ? (
            <MetricSuite
              numero={2}
              titulo="Mapeamento CNAE"
              meta={{ date: cnae.date, commit: cnae.commit }}
              linhas={[
                pctLinha("Recall@1", cnae.metrics?.["recall@1"], undefined),
                pctLinha("Recall@5", cnae.metrics?.["recall@5"], lim.recall_at_5),
                pctLinha("MRR", cnae.metrics?.mrr, undefined),
                qtdLinha("Casos", cnae.metrics?.n_cases),
              ]}
            />
          ) : null}
          {e2e ? (
            <MetricSuite
              numero={3}
              titulo="Ponta a ponta"
              meta={{ date: e2e.date, commit: e2e.commit }}
              linhas={[
                pctLinha("Casos 100% corretos", e2e.metrics?.case_pass_rate, lim.e2e_case_pass_rate),
                pctLinha("Precisão por empresa", e2e.metrics?.row_precision, lim.e2e_row_precision),
                pctLinha("Recusa correta", e2e.metrics?.e2e_correct_refusal_rate, lim.e2e_correct_refusal_rate),
                qtdLinha("Empresas avaliadas", e2e.metrics?.n_rows),
                qtdLinha("Casos", e2e.metrics?.n_cases),
              ]}
            />
          ) : null}
          {dados && !ext && !cnae && !e2e ? (
            <p className="text-muted-foreground">Sem resultados de avaliação disponíveis.</p>
          ) : null}
          {e2e || cnae || ext ? (
            <p className="inline-block rounded-lg border-2 border-double border-accent px-4 py-2 font-mono text-xs uppercase tracking-widest text-accent">
              Avaliado — {((e2e || cnae || ext)!.date ?? "").slice(0, 10)}
            </p>
          ) : null}
        </main>
        <Footer />
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Registrar a rota em `App.tsx`**

```tsx
import { BrowserRouter, Route, Routes } from "react-router-dom";
import Home from "./pages/Home";
import Metrics from "./pages/Metrics";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/metricas" element={<Metrics />} />
      </Routes>
    </BrowserRouter>
  );
}
```

- [ ] **Step 6: Rodar para ver passar e commitar**

Run: `npm test` → esperado: PASS.

```bash
git add frontend/src/components/MetricSuite.tsx frontend/src/pages/Metrics.tsx frontend/src/App.tsx frontend/tests/metric-suite.test.tsx
git commit -m "front: pagina /metricas com suites medidas e selecao golden_e2e"
```

---

### Task 11: SPA fallback + redirect no Python (TDD pytest)

**Files:**
- Modify: `src/quimera/api/app.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Escrever os testes que falham**

Adicionar ao `tests/test_api.py` (o `create_app` ainda não tem `static_dir`):

```python
class TestSpaFallback:
    @pytest.fixture()
    def static_dir(self, tmp_path):
        (tmp_path / "index.html").write_text(
            '<!doctype html><html lang="pt-BR"><body><div id="root"></div></body></html>',
            encoding="utf-8",
        )
        assets = tmp_path / "assets"
        assets.mkdir()
        (assets / "app.js").write_text("console.log('quimera')", encoding="utf-8")
        (assets / "app.css").write_text("body{}", encoding="utf-8")
        return tmp_path

    def _client(self, static_dir):
        extract, search, bq = _happy_clients()
        app = create_app(
            config=_config(),
            extract_client=extract,
            cnae_search=search,
            bq_client=bq,
            static_dir=static_dir,
        )
        return TestClient(app)

    def test_root_serves_spa_index(self, static_dir):
        resp = self._client(static_dir).get("/")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        assert 'lang="pt-BR"' in resp.text
        assert 'id="root"' in resp.text

    def test_metricas_falls_back_to_index(self, static_dir):
        resp = self._client(static_dir).get("/metricas")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        assert 'id="root"' in resp.text

    def test_metrics_html_redirects_to_metricas(self, static_dir):
        resp = self._client(static_dir).get("/metrics.html", follow_redirects=False)
        assert resp.status_code == 308
        assert resp.headers["location"] == "/metricas"

    def test_metrics_route_stays_json(self, static_dir):
        resp = self._client(static_dir).get("/metrics")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")

    def test_missing_asset_is_404_not_index(self, static_dir):
        resp = self._client(static_dir).get("/assets/nao-existe.js")
        assert resp.status_code == 404
        assert "id=\"root\"" not in resp.text

    def test_unknown_api_path_is_404_json(self, static_dir):
        resp = self._client(static_dir).get("/leads/nao-existe")
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("application/json")
        assert "error" in resp.json()
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `python -m pytest tests/test_api.py::TestSpaFallback -v`
Esperado: FAIL — `create_app() got an unexpected keyword argument 'static_dir'`.

- [ ] **Step 3: Implementar o `SpaStaticFiles` e o redirect em `src/quimera/api/app.py`**

No topo do módulo, junto aos outros imports de resposta:

```python
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
```

Remover o `from fastapi.staticfiles import StaticFiles` de dentro de `create_app` (se houver).

Adicionar a subclasse **antes** de `create_app`:

```python
class SpaStaticFiles(StaticFiles):
    """StaticFiles com fallback de SPA.

    Regras: só GET sem extensão fora dos prefixos da API recebe
    ``index.html``; path com extensão sem arquivo devolve 404; path sob
    prefixo de API sem rota casada devolve 404 JSON.
    """

    API_PREFIXES = ("/leads", "/config", "/health", "/metrics")

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code != 404 or scope.get("method") != "GET":
            return response
        request_path = scope.get("path", "")
        if self._is_api_path(request_path):
            return JSONResponse(
                status_code=404,
                content={
                    "error": "não encontrado",
                    "reason": f"rota desconhecida: {request_path}",
                },
            )
        if "." in path.rsplit("/", 1)[-1]:
            return response
        return await super().get_response("index.html", scope)

    @classmethod
    def _is_api_path(cls, request_path: str) -> bool:
        return any(
            request_path == prefix or request_path.startswith(prefix + "/")
            for prefix in cls.API_PREFIXES
        )
```

Em `create_app`, a assinatura ganha `static_dir: Path | None = None` (keyword-only, junto aos demais):

```python
def create_app(
    *,
    config: ApiConfig | None = None,
    ...
    warmup: bool = False,
    static_dir: Path | None = None,
) -> FastAPI:
```

E o mount no fim de `create_app` vira:

```python
    @app.get("/metrics.html")
    def _metrics_html_redirect():
        return RedirectResponse(url="/metricas", status_code=308)

    resolved_static = static_dir if static_dir is not None else Path(__file__).parent / "static"
    if resolved_static.is_dir():
        app.mount("/", SpaStaticFiles(directory=resolved_static, html=True), name="static")

    return app
```

- [ ] **Step 4: Rodar para ver passar**

Run: `python -m pytest tests/test_api.py::TestSpaFallback -v`
Esperado: PASS (6 testes).

Run: `python -m pytest tests/test_api.py -v`
Esperado: os 4 antigos de `TestFrontend` podem falhar (serão reescritos na Task 12); os demais PASS.

- [ ] **Step 5: Commit**

```bash
git add src/quimera/api/app.py tests/test_api.py
git commit -m "api: SPA fallback com regras e redirect de /metrics.html para /metricas"
```

---

### Task 12: Build → static/ e reescrita do TestFrontend

**Files:**
- Modify: `tests/test_api.py` (classe `TestFrontend`)
- Create: (nenhum — o bundle passa a ser artefato)

- [ ] **Step 1: Substituir a classe `TestFrontend` inteira**

Remover os 4 testes antigos (`test_root_serves_laudo_page`, `test_metrics_html_served`, `test_metrics_page_renders_from_api_json`, `test_static_assets_served`) e escrever:

```python
class TestFrontend:
    @pytest.fixture()
    def static_dir(self, tmp_path):
        (tmp_path / "index.html").write_text(
            '<!doctype html><html lang="pt-BR"><body><div id="root"></div></body></html>',
            encoding="utf-8",
        )
        assets = tmp_path / "assets"
        assets.mkdir()
        (assets / "index-abc123.js").write_text("console.log('quimera')", encoding="utf-8")
        (assets / "index-abc123.css").write_text("body{}", encoding="utf-8")
        return tmp_path

    def _client(self, static_dir):
        extract, search, bq = _happy_clients()
        app = create_app(
            config=_config(),
            extract_client=extract,
            cnae_search=search,
            bq_client=bq,
            static_dir=static_dir,
        )
        return TestClient(app)

    def test_root_serves_spa_index(self, static_dir):
        resp = self._client(static_dir).get("/")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        assert 'lang="pt-BR"' in resp.text
        assert 'id="root"' in resp.text
        assert "Quimera" in resp.text

    def test_metricas_served_via_fallback(self, static_dir):
        resp = self._client(static_dir).get("/metricas")
        assert resp.status_code == 200
        assert 'id="root"' in resp.text

    def test_metrics_html_redirects(self, static_dir):
        resp = self._client(static_dir).get("/metrics.html", follow_redirects=False)
        assert resp.status_code == 308
        assert resp.headers["location"] == "/metricas"

    def test_static_assets_served(self, static_dir):
        client = self._client(static_dir)
        js = client.get("/assets/index-abc123.js")
        css = client.get("/assets/index-abc123.css")
        assert js.status_code == 200
        assert "javascript" in js.headers["content-type"]
        assert css.status_code == 200
        assert "text/css" in css.headers["content-type"]
```

- [ ] **Step 2: Rodar a suíte de API completa**

Run: `python -m pytest tests/test_api.py -v`
Esperado: PASS (inclui `TestSpaFallback` e o novo `TestFrontend`).

Run: `python -m pytest tests -v`
Esperado: PASS (suíte inteira).

- [ ] **Step 3: Gerar o bundle real e conferir**

Run: `cd frontend && npm run build`
Esperado: `src/quimera/api/static/` contendo `index.html` e `assets/index-*.js|css`.

Run: `python -c "from pathlib import Path; p=Path('src/quimera/api/static'); print(sorted(x.name for x in p.rglob('*'))[:10])"`
Esperado: lista com `index.html` e `assets/...`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_api.py
git commit -m "test: TestFrontend reescrito para o bundle React e as regras de fallback"
```

---

### Task 13: package-data, gitignore, Dockerfile e .dockerignore

**Files:**
- Modify: `pyproject.toml`, `.gitignore`, `Dockerfile`, `.dockerignore`

- [ ] **Step 1: Corrigir o package-data em `pyproject.toml`**

```toml
[tool.setuptools.package-data]
quimera = ["data/*.jsonl", "data/*.npz"]
"quimera.api" = ["static/*", "static/**/*"]
```

(`static/**/*` é o que pega `static/assets/`; `static/*` fica para `index.html` em versões de setuptools com glob estrito.)

- [ ] **Step 2: Ignorar o bundle no git e deixar de rastrear os estáticos antigos**

Em `.gitignore`, adicionar a seção:

```gitignore
# Bundle do front (gerado por npm run build)
src/quimera/api/static/
frontend/node_modules/
frontend/dist/
frontend/playwright-report/
frontend/test-results/
```

Run: `git rm -r --cached src/quimera/api/static`
Esperado: os arquivos antigos (`app.js`, `index.html`, `style.css`, `metrics.*`) saem do índice e continuam no disco até o próximo build sobrescrever.

- [ ] **Step 3: Dockerfile multi-estágio**

Substituir o `Dockerfile` inteiro:

```dockerfile
FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# outDir do Vite é ../src/quimera/api/static (relativo a /build) → /src/quimera/api/static
RUN npm run build && mkdir -p /out && cp -r /src/quimera/api/static /out/static

FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EVAL_DIR=/app/eval

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/
COPY --from=frontend /out/static/ src/quimera/api/static/
RUN pip install --no-cache-dir ".[api,gcp]"

COPY eval/results/ eval/results/
COPY eval/thresholds.json eval/

RUN useradd --create-home quimera \
    && chown -R quimera:quimera /app
USER quimera

EXPOSE 8080
CMD ["python", "-m", "quimera.api"]
```

Critério de aceite: `assets/` presente em `src/quimera/api/static/` da imagem final
(`docker run ... curl localhost:8080/ | grep id=\"root\"`).

- [ ] **Step 4: `.dockerignore` e `.gcloudignore`**

Em `.dockerignore`, adicionar:

```
frontend/node_modules
frontend/dist
frontend/test-results
frontend/playwright-report
src/quimera/api/static
```

O `.gcloudignore` começa com `#!include:.dockerignore` — herda as mesmas exclusões; adicionar também `frontend/e2e/` se o build do Cloud reclamar do tamanho.

- [ ] **Step 5: Verificar a wheel e a imagem**

Run: `pip install build && python -m build --wheel`
Run: `python -c "import zipfile,glob; w=sorted(glob.glob('dist/*.whl'))[-1]; print([n for n in zipfile.ZipFile(w).namelist() if 'static' in n][:8])"`
Esperado: nomes com `quimera/api/static/index.html` e `quimera/api/static/assets/...`.

Run (se Docker disponível): `docker build -t quimera-demo .`
Run: `docker run --rm -p 8080:8080 quimera-demo` e `curl -s localhost:8080/ | grep id=\"root\"`
Esperado: HTML do React.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore Dockerfile .dockerignore
git commit -m "deploy: bundle do front entra na imagem (package-data, docker multi-estagio)"
```

---

### Task 14: Playwright — e2e com API mockada e screenshots

**Files:**
- Create: `frontend/playwright.config.ts`, `frontend/e2e/quimera.spec.ts`, `frontend/e2e/fixtures/leads-success.json`, `frontend/e2e/fixtures/leads-refusal.json`, `frontend/e2e/fixtures/metrics.json`
- Modify: `frontend/package.json` (script `test:e2e`)

- [ ] **Step 1: Instalar e configurar**

Run: `npm install -D @playwright/test && npx playwright install chromium`

`frontend/playwright.config.ts`:

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: {
    baseURL: "http://127.0.0.1:5173",
    colorScheme: "dark",
  },
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: true,
  },
});
```

Em `frontend/package.json`, scripts:

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "typecheck": "tsc -b",
    "test": "vitest run",
    "test:e2e": "playwright test"
  }
}
```

- [ ] **Step 2: Escrever fixtures**

`frontend/e2e/fixtures/leads-success.json` (espelha o contrato real):

```json
{
  "refused": false,
  "refusal_reason": null,
  "filters": {
    "cnae_query": "clínicas odontológicas",
    "cnae_codes": ["8630-5/01"],
    "ufs": ["SP"],
    "municipio_ids": ["3547807"],
    "municipio_names": ["Santo André"],
    "min_age_years": 2,
    "max_age_years": null,
    "min_capital": null,
    "portes": ["pequena"],
    "include_mei": false,
    "min_estabelecimentos": null,
    "regimes": [],
    "bairros": [],
    "cep_centro": null,
    "raio_km": null,
    "com_dominio_proprio": false,
    "limit": 50
  },
  "cnae_matches": [["8630-5/01", "Atividade médica ambulatorial odontológica", 0.92]],
  "municipio_resolution": {},
  "snapshot": { "quimera.leads": "2026-09-01" },
  "rows": [
    {
      "cnpj_basico": "12345678",
      "razao_social": "CLINICA ALFA",
      "nome_fantasia": null,
      "sigla_uf": "SP",
      "municipio": "Santo André",
      "cnae_fiscal_principal": "8630-5/01",
      "data_inicio_atividade": "20150110",
      "capital_social": 100000.0,
      "porte": "pequena",
      "score": 87,
      "motivos_score": ["idade 11 anos", "capital R$ 100.000"]
    }
  ],
  "bytes_processed": 34603008,
  "bytes_billed": 34603008,
  "estimated_cost_usd": 0.0002,
  "latency_ms": 4123.4,
  "timings_ms": { "extract": 1200, "cnae": 800, "query": 800, "score": 100 },
  "model": "gemini-2.5-flash",
  "policy": "public",
  "request_normalized": "clinicas odontologicas",
  "warnings": [],
  "query_sql": "SELECT * FROM `quimera.leads` WHERE sigla_uf = @uf",
  "cached": false,
  "cache_mode": false
}
```

`frontend/e2e/fixtures/leads-refusal.json`:

```json
{
  "refused": true,
  "refusal_reason": "pedido de dado pessoal (e-mail, telefone ou sócio)",
  "filters": null,
  "cnae_matches": [],
  "municipio_resolution": {},
  "snapshot": {},
  "rows": [],
  "bytes_processed": 0,
  "bytes_billed": 0,
  "estimated_cost_usd": 0,
  "latency_ms": 300,
  "timings_ms": {},
  "model": "gemini-2.5-flash",
  "policy": "public",
  "request_normalized": "e-mails de clinicas",
  "warnings": [],
  "query_sql": "",
  "cached": false,
  "cache_mode": false
}
```

`frontend/e2e/fixtures/metrics.json`:

```json
{
  "thresholds": {
    "correct_refusal_rate": 1.0,
    "overall_field_accuracy": 0.85,
    "recall_at_5": 0.9,
    "e2e_case_pass_rate": 0.9,
    "e2e_row_precision": 0.98,
    "e2e_correct_refusal_rate": 1.0
  },
  "extraction": [
    {
      "suite": "extraction",
      "date": "2026-09-28T12:00:00Z",
      "commit": "abc1234",
      "metrics": {
        "correct_refusal_rate": 1.0,
        "false_refusal_rate": 0.0,
        "overall_field_accuracy": 0.87,
        "exact_match_rate": 0.6,
        "n_cases": 42
      }
    }
  ],
  "cnae": [
    {
      "suite": "cnae",
      "date": "2026-09-28T12:00:00Z",
      "commit": "abc1234",
      "metrics": { "recall@1": 0.88, "recall@5": 0.955, "mrr": 0.92, "n_cases": 66 }
    }
  ],
  "e2e": [
    {
      "suite": "e2e",
      "golden": "golden_e2e.jsonl",
      "date": "2026-09-28T12:00:00Z",
      "commit": "abc1234",
      "metrics": {
        "case_pass_rate": 0.95,
        "row_precision": 0.997,
        "e2e_correct_refusal_rate": 1.0,
        "n_rows": 795,
        "n_cases": 20
      }
    }
  ]
}
```

- [ ] **Step 3: Escrever o spec e2e**

`frontend/e2e/quimera.spec.ts`:

```ts
import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const fixture = (nome: string) =>
  JSON.parse(readFileSync(path.join(__dirname, "fixtures", nome), "utf-8"));

async function mockarApi(page: Page, opcoes: { leads?: unknown } = {}) {
  await page.route("**/config", (r) =>
    r.fulfill({ json: { turnstile_site_key: null } }),
  );
  await page.route("**/health", (r) =>
    r.fulfill({
      json: { status: "ok", version: "0.1.0", cache_mode: false, budget_remaining_bytes: 1073741824 },
    }),
  );
  await page.route("**/metrics", (r) => r.fulfill({ json: fixture("metrics.json") }));
  await page.route("**/leads", (r) =>
    r.fulfill({ json: opcoes.leads ?? fixture("leads-success.json") }),
  );
}

test("pedido vira laudo com ranking", async ({ page }) => {
  await mockarApi(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("pedido em português");
  await page.getByLabel(/pedido/i).fill("clínicas em Santo André");
  await page.getByRole("button", { name: /analisar/i }).click();
  await expect(page.getByText(/interpretação do pedido/i)).toBeVisible();
  await expect(page.getByText("CLINICA ALFA")).toBeVisible();
  await expect(page.getByText("87")).toBeVisible();
  await expect(page.getByText(/SELECT \* FROM/)).toBeVisible();
  await expect(page.getByText("33,0 MB")).toBeVisible();
  await page.screenshot({ path: "test-results/estado-resultado.png", fullPage: true });
});

test("chips de exemplo preenchem o pedido", async ({ page }) => {
  await mockarApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: /padarias artesanais/i }).click();
  await expect(page.getByLabel(/pedido/i)).toHaveValue(/padarias artesanais/);
});

test("recusa renderiza banner com motivo", async ({ page }) => {
  await mockarApi(page, { leads: fixture("leads-refusal.json") });
  await page.goto("/");
  await page.getByLabel(/pedido/i).fill("e-mails das clínicas");
  await page.getByRole("button", { name: /analisar/i }).click();
  await expect(page.getByRole("status").first()).toContainText(/dado pessoal/i);
  await page.screenshot({ path: "test-results/estado-recusa.png", fullPage: true });
});

test("/metricas mostra suites com acima e abaixo do limiar", async ({ page }) => {
  await mockarApi(page);
  await page.goto("/metricas");
  await expect(page.getByRole("heading", { name: /métricas medidas/i })).toBeVisible();
  await expect(page.getByText(/acima do limiar/i).first()).toBeVisible();
  await expect(page.getByText("87,0%")).toBeVisible();
  await page.screenshot({ path: "test-results/estado-metricas.png", fullPage: true });
});

test("hero e empty state (baseline visual)", async ({ page }) => {
  await mockarApi(page);
  await page.goto("/");
  await expect(page.getByText(/escreva um pedido acima/i)).toBeVisible();
  await page.screenshot({ path: "test-results/estado-hero.png", fullPage: true });
});
```

- [ ] **Step 4: Rodar o Playwright**

Run: `npm run test:e2e`
Esperado: 5 testes PASS; PNGs em `frontend/test-results/`.

- [ ] **Step 5: Commit**

```bash
git add frontend/playwright.config.ts frontend/e2e frontend/package.json frontend/package-lock.json
git commit -m "test: playwright e2e com API mockada e screenshots baseline"
```

---

### Task 15: Polish final — a11y, reduced-motion, suíte completa

**Files:**
- Modify: `frontend/src/components/Home.tsx` (foco no resultado), `frontend/src/pages/Metrics.tsx` (contraste do carimbo se necessário)
- Test: ajustes finais se algo falhar

- [ ] **Step 1: Foco no resultado após a busca**

Em `frontend/src/pages/Home.tsx`, o `useEffect` após mudança de estado de `success`/`error`/`refused`:

```tsx
useEffect(() => {
  if (state.kind !== "idle" && state.kind !== "loading") {
    resultadoRef.current?.focus();
  }
}, [state]);
```

(Com `prefers-reduced-motion`, o `scrollIntoView` pode ser omitido; o foco permanece.)

- [ ] **Step 2: Conferir contraste e reduced-motion**

Run: `rg "#4f6bff|bg-primary" frontend/src`
Esperado: `#4f6bff` só em glow/bordas/anéis; o fundo do CTA é `bg-primary` (`#3b52e0`).

Run: `rg "prefers-reduced-motion" frontend/src`
Esperado: o bloco existe no `globals.css`.

- [ ] **Step 3: Suíte completa**

Run: `npm run typecheck` → sem erros.
Run: `npm test` → todos os Vitest PASS.
Run: `npm run build` → bundle em `src/quimera/api/static/`.
Run: `python -m pytest tests -v` → toda a suíte Python PASS.
Run: `npm run test:e2e` → 5 testes PASS.

- [ ] **Step 4: Commit final**

```bash
git add -A frontend/src
git commit -m "front: foco de a11y no resultado e polimento final"
```

---

## Self-Review (registro)

**1. Spec coverage:**
- Arquitetura (`frontend/`, outDir `static/`, package-data `static/**/*`, Docker node→pip, rotas `/`+`/metricas`, redirect `/metrics.html`, API intocada, TS) → Tasks 1, 11, 12, 13.
- SPA fallback com 3 regras → Task 11.
- Sistema visual (tokens dark, CTA `#3b52e0`, mono para valores medidos, glow, reduced-motion) → Tasks 1, 15 + componentes.
- Páginas (hero, form, resultado 5 seções + ressalvas, pipeline, footer, `/metricas` com seleção golden) → Tasks 5–10.
- Estados (idle/loading/recusa/401/422/429+Retry-After/500/502/503×4/504/rede/cache) → Tasks 6, 8, 9.
- Turnstile reset em todo submit → Task 4 (consumo) + Task 9 (uso no Home) + Task 14 (2º submit).
- `/health` (versão + orçamento) → Task 9.
- Testes: Vitest, Playwright, `tsc`, 4 TestFrontend reescritos → Tasks 3–10, 12, 14, 15.

**2. Placeholder scan:** nenhum TBD/TODO; todo passo de código tem o código completo; comandos têm resultado esperado.

**3. Type consistency:** `LeadsResponse`, `ErrorState`, `TurnstileController.consume`, `selectE2e`, `CostSummary(budgetRemainingBytes)` e `create_app(static_dir=...)` usam os mesmos nomes em todos os tasks que os referenciam.
