# Design — Front novo em React (dark, produto moderno)

Data: 2026-09-28
Status: aprovado pelo Bruno em conversa
Escopo: front novo em React/Vite com visual dark de produto de IA,
substituindo os estáticos em `src/quimera/api/static/` (a estética
"Laudo Técnico" sai de cena). API inalterada; a única mudança no Python
é a rota de SPA fallback.

## Decisões confirmadas com o Bruno

1. **Stack nova:** React/Vite (não só redesenho dos estáticos atuais).
2. **Direção visual:** jogar o laudo fora — visual contemporâneo de
   produto de IA (hero, gradientes, cards), tema **escuro**
   (referência Vercel/Resend).
3. **Escopo:** mesma funcionalidade de hoje + polimento de produto:
   hero de entrada, empty states cuidados, animações de resultado,
   seção "como funciona".
4. **Impressão dominante:** "produto sério e bem-feito" — moderno e
   polido, mas com rigor/credibilidade no centro (números visíveis,
   nada de firula que atrapalhe a leitura). Não é "wow" acima de tudo.
5. **Build:** Tailwind v4 + shadcn/ui customizado (controle de tokens,
   componentes Radix acessíveis que o projeto possui), TypeScript.
6. **Testes:** Vitest + Testing Library, **Playwright** (e2e com API
   mockada + screenshots baseline) e `tsc --noEmit`.

## Arquitetura

```
frontend/                  # fonte React (novo)
  src/
    components/            # Hero, RequestForm, ResultPanel, ...
    pages/                 # Home.tsx, Metrics.tsx
    lib/                   # api.ts, types.ts, format.ts, turnstile.ts
    styles/                # tokens.css (tema dark)
  index.html
  vite.config.ts
  tests/                   # Vitest
  e2e/                     # Playwright + fixtures
src/quimera/api/static/    # OUTPUT do build (gitignored)
```

- **Build → servir:** `npm run build` gera o bundle e copia para
  `src/quimera/api/static/`. A FastAPI continua montando `StaticFiles`
  no mesmo lugar, agora com subclasse de SPA fallback.
- **package-data:** `pyproject.toml` troca `static/*` por
  `static/**/*` — sem isso o `static/assets/` do Vite não entra na
  wheel e o site sai em branco no Docker.
- **Docker/Cloud Run:** Dockerfile ganha estágio `node:22` com
  `npm ci && npm run build` **antes** do `pip install` (os estáticos
  precisam existir quando o pacote for montado); `.dockerignore` passa
  a incluir `frontend/node_modules`. Uma imagem, escala a zero, sem
  CORS — igual hoje.
- **Rotas (React Router):** `/` (home) e `/metricas` (anexo de
  métricas). **`/metrics` continua sendo a rota JSON da API** — por
  isso o front usa `/metricas`: um F5 ou link direto em `/metrics` ia
  devolver JSON cru. `/metrics.html` (URL antiga) redireciona para
  `/metricas`.
- **API inalterada:** `POST /leads`, `GET /metrics`, `GET /config`,
  `GET /health`. Nada muda no backend.
- **TypeScript** em todo o `frontend/`; contratos da API em
  `lib/types.ts`.

### SPA fallback (subclasse de `StaticFiles`)

Regras de aceite:

1. Só `GET` sem extensão no último segmento recebe `index.html`
   (`/`, `/metricas` e rotas futuras do React Router).
2. Qualquer path **com extensão** sem arquivo correspondente
   (`/assets/*` incluso) devolve **404** — nunca `index.html`.
3. Paths sob prefixos da API (`/leads`, `/config`, `/health`,
   `/metrics`) **nunca** recebem fallback: sem rota registrada casada,
   a resposta é **404 JSON**, nunca HTML.

## Sistema visual

**Thesis:** "Sistema medido, produto moderno" — dark premium de produto
de IA, com o DNA de rigor preservado: todo valor medido (bytes, custo,
score, latência) em mono; números antes de adjetivos. A seriedade vem
dos dados visíveis, não de estética de documento.

### Tokens (dark)

- Fundo `#0A0A0C`; superfícies `#121216` / `#1A1A20`; bordas
  `rgba(255,255,255,0.08)`.
- Texto `#F4F4F5`; secundário `#A1A1AA`.
- Acento **azul-elétrico `#4F6BFF`** (gradiente sutil com `#7C5CFF` em
  glow) — CTA, foco, dados de destaque; com parcimônia.
- **CTA:** fundo `#3B52E0` com texto `#FFFFFF` (contraste ≥ 4,5:1 —
  branco sobre `#4F6BFF` daria só ~4,3:1, abaixo do AA). O `#4F6BFF`
  fica para acentos, glow e elementos grandes.
- Estados: verde `#30A46C` (cache hit, acima do limiar), vermelho
  `#E5484D` (erro/recusa), âmbar `#F5A524` (warnings).

### Tipografia

- Sans **Geist** (fallback Inter): hero 56–64px bold com tracking
  negativo; títulos 24–32px; corpo 15–16px.
- Mono **Geist Mono** (fallback JetBrains Mono): todo valor medido,
  SQL, CNPJ, latência — a "regra do valor medido" sobrevive.
- Fontes self-hosted via `@fontsource` (npm) — sem CDN externo em
  runtime.

### Linguagem visual

- Cantos arredondados (12–16px cards, 8px inputs); bordas 1px
  translúcidas; elevação por contraste de superfície; sombras muito
  suaves só onde precisar.
- Glow/gradiente atrás do hero e do resultado que chega (o "momento").
- Microinterações 150–200ms (hover acende borda); `prefers-reduced-motion`
  respeitado.
- Ícones Lucide, stroke fino (1.5px).

### Herança do laudo (por rigor)

Mantém: valores medidos em mono com unidades; ressalvas visíveis quando
o dado impõe limites; métricas sempre com fonte (`eval/`). Não mantém:
papel, hairlines, achados numerados, carimbo.

## Páginas e componentes

### Home `/` (single scroll)

1. **Hero** — headline ("De um pedido em português para uma lista de
   empresas"), sublinha da proposta, input de pedido como herói (não é
   chat genérico — é o produto). Glow sutil atrás. Versão do serviço
   (`GET /health` → `version`) em metadados discretos do header.
2. **Form** — textarea (500 chars) + chips de pedidos-modelo clicáveis +
   Turnstile + CTA "Analisar" com estado de loading.
3. **Resultado** (in-place, reveal animado em cascata):
   - **Interpretação** — filtros extraídos como chips/badges.
   - **CNAEs** — código + nome + similaridade em mono.
   - **Consulta** — SQL em bloco mono com syntax highlight e copiar;
     bytes processados/cobrados e **snapshot da base** em mono.
   - **Ranking** — tabela densa: posição, CNPJ, nome, score (barra +
     número mono), motivos. É onde o rigor brilha.
   - **Custos** — custo estimado, **latência do pipeline**
     (`latency_ms`) + tempos por etapa (`timings_ms`), tempo no
     navegador, orçamento diário restante (via `GET /health`),
     modelo, cache hit, **modo cache** (`cache_mode`) e
     warnings/ressalvas.
4. **Como funciona** — 3 passos (extract → cnae/policy → query/score)
   tipo pipeline com ícones.
5. **Footer** — sem dado pessoal; link pro anexo de métricas.

### Metrics `/metricas`

- Suítes (extraction, cnae, e2e) em cards comparando valor medido ×
  limiar (barra: acima/abaixo).
- **Regra de seleção de execução** (a mesma do `metrics.js` atual):
  extraction e cnae usam a última execução de cada lista; e2e prefere
  a última com `golden == "golden_e2e.jsonl"` e `n_cases >= 20`; sem
  essa, a última com `n_cases >= 20`; sem essa, a última de todas.
- Meta: data da execução e commit — tudo de `GET /metrics`,
  nada escrito à mão.
- Badge "Avaliado" (substitui o carimbo do laudo).

### Componentes-chave

`Hero`, `RequestForm`, `ExampleChips`, `ResultPanel` (com
`FiltersBadge`, `CnaeList`, `SqlBlock`, `RankingTable`,
`CostSummary`), `StatusBanner` (recusa/429/503/etc.), `MetricSuite`,
`PipelineSteps`, `Footer`.

Empty state convidativo antes do primeiro pedido (nunca tela vazia).

## Fluxo de dados e estados

Cliente API (`lib/api.ts`) tipado, sem lib de fetch pesada:

- `GET /config` → site key do Turnstile (na montagem do form).
- `GET /health` → versão, `cache_mode` e `budget_remaining_bytes`
  (header e rodapé de custos).
- `POST /leads {request, turnstile}` → filtros, CNAEs, ranking, SQL,
  snapshot, bytes, custo, `latency_ms`, `timings_ms`, `cache_mode`,
  `refused`, warnings.
- `GET /metrics` → suítes medidas (página `/metricas`).

Sem estado global (sem Redux/Zustand/React Query) — `useState`/
`useReducer` no form + resultado.

Todo erro da API vem no envelope `{"error", "reason"}` — a UI mostra o
`reason` do servidor (com fallback por status quando não houver).

| Estado | Tratamento |
|---|---|
| `idle` | empty state convidativo no lugar do resultado |
| `carregando` | CTA em loading + skeleton no painel de resultado |
| `recusa` (`refused: true`) | banner informativo com motivo (política, não erro) |
| `401` | "valide o captcha e tente de novo" |
| `422` | erro de validação no campo, inline |
| `429` | "muitas tentativas, aguarde" + tempo sugerido pelo header `Retry-After` |
| `500` | "erro interno" — `reason` do servidor + sugestão de tentar de novo |
| `502` | extração falhou — `reason` do servidor ("reformule o pedido") |
| `503` variante `cache mode` | orçamento do dia esgotado; só pedidos já vistos |
| `503` variante `orçamento diário` | saldo não cobre a consulta; refinar filtros |
| `503` variante `teto de bytes` | consulta acima do teto; refinar filtros |
| `503` variante `dados indisponíveis` | base sendo atualizada; tentar mais tarde |
| `504` | timeout; sugestão de pedido mais específico |
| falha de rede | banner "não foi possível conectar" + tentar de novo |
| `cache hit` | badge verde no resultado |
| `cache_mode: true` | badge/banner âmbar em qualquer resposta |
| `warnings` | lista de ressalvas no CostSummary |

Turnstile: render explícito; token anexado ao POST; **reset do widget
em todo submit** (o token é de uso único — sem reset, o 2º pedido cai
em 401), além de reset em erro/expiração.

## Erros e testes

### Tratamento de erro

- Falha de rede/abort: banner "não foi possível conectar" + tentar de
  novo (AbortController com timeout próprio).
- Turnstile falhou/expirou: reset do widget + mensagem; nunca POST sem
  token.
- Resposta malformada: render defensivo (arrays vazios, fallback `—`).
- `prefers-reduced-motion`: animações desligadas.
- Resultado novo recebe foco; tabela navegável; contraste AA no dark
  (CTA em `#3B52E0`, nunca `#4F6BFF` com texto branco).

### Testes

- **Vitest + React Testing Library:** `RequestForm` (idle/loading/erro,
  reset do Turnstile em todo submit), `ResultPanel` (recusa, cache
  hit, `cache_mode`, warnings), `RankingTable` (ordem = nota, vazio),
  `MetricSuite` (acima/abaixo do limiar, regra de seleção de execução),
  `StatusBanner` (429 com `Retry-After`, variantes de 503, 502, 500).
- **Playwright** (local/manual nesta fase, sem pipeline novo de CI):
  e2e com API mockada (fixtures espelhando `/leads` e `/metrics`):
  1. home carrega, digita pedido, submete → resultado com ranking.
  2. chips de pedido-modelo preenchem o textarea.
  3. recusa renderiza banner com motivo.
  4. 2º submit consecutivo envia novo token (reset do Turnstile).
  5. `/metricas` mostra suítes com acima/abaixo do limiar.
  6. screenshots baseline dos estados principais (hero, resultado, erro).
- **`tsc --noEmit`** no build.
- **pytest:** os **4 testes da classe `TestFrontend`** serão
  reescritos (todos assertam copy/ativos do laudo — `test_root_serves_
  laudo_page`, `test_metrics_html_served`, `test_metrics_page_renders_
  from_api_json`, `test_static_assets_served`): passam a verificar o
  bundle novo, a rota `/metricas`, o redirect de `/metrics.html` e o
  SPA fallback. Testes de API intactos.

## Fora de escopo

- Mudanças na API, nas proteções ou no pipeline (o SPA fallback e o
  redirect de `/metrics.html` no `app.py` são as únicas exceções
  Python, e não alteram comportamento da API).
- Playwright em CI (baselines de screenshot ficam locais nesta fase).
- Tema claro / toggle de tema.
- Novas funcionalidades de produto (auth, billing, multi-tenant).

## Referências

- Direção visual aprovada: Vercel/Resend (dark), tom "produto sério".
- Mundo visual antigo (arquivo, não vigente): `DESIGN.md` ("Laudo
  Técnico") — substituído por este documento para o front.
- Restrições de produto que permanecem: `PRODUCT.md` (pt-BR, sem dado
  pessoal, métricas só de `eval/`).
