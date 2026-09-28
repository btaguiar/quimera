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
  `src/quimera/api/static/`. A FastAPI continua montando
  `StaticFiles(html=True)` no mesmo lugar. Mudança mínima no Python:
  rota catch-all que devolve `index.html` para caminhos não-API
  (SPA fallback — `/metrics` vira rota do React Router).
- **Docker/Cloud Run:** Dockerfile ganha estágio `node:22` com
  `npm ci && npm run build` antes do estágio Python copiar os
  estáticos. Uma imagem, escala a zero, sem CORS — igual hoje.
- **Rotas (React Router):** `/` (home) e `/metrics` (anexo de métricas).
- **API inalterada:** `POST /leads`, `GET /metrics`, `GET /config`,
  `GET /health`. Nada muda no backend.
- **TypeScript** em todo o `frontend/`; contratos da API em
  `lib/types.ts`.

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
   chat genérico — é o produto). Glow sutil atrás.
2. **Form** — textarea (500 chars) + chips de pedidos-modelo clicáveis +
   Turnstile + CTA "Analisar" com estado de loading.
3. **Resultado** (in-place, reveal animado em cascata):
   - **Interpretação** — filtros extraídos como chips/badges.
   - **CNAEs** — código + nome + similaridade em mono.
   - **Consulta** — SQL em bloco mono com syntax highlight e copiar.
   - **Ranking** — tabela densa: posição, CNPJ, nome, score (barra +
     número mono), motivos. É onde o rigor brilha.
   - **Custos** — bytes, custo estimado, cache hit, warnings/ressalvas.
4. **Como funciona** — 3 passos (extract → cnae/policy → query/score)
   tipo pipeline com ícones.
5. **Footer** — sem dado pessoal; link pro anexo de métricas.

### Metrics `/metrics`

- Suítes (extraction, cnae, e2e) em cards comparando valor medido ×
  limiar (barra: acima/abaixo).
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
- `POST /leads {request, turnstile}` → filtros, CNAEs, ranking, SQL,
  bytes, custo, `refused`, warnings.
- `GET /metrics` → suítes medidas (página Metrics).

Sem estado global (sem Redux/Zustand/React Query) — `useState`/
`useReducer` no form + resultado.

| Estado | Tratamento |
|---|---|
| `idle` | empty state convidativo no lugar do resultado |
| `carregando` | CTA em loading + skeleton no painel de resultado |
| `recusa` (`refused: true`) | banner informativo com motivo (política, não erro) |
| `401` | "valide o captcha e tente de novo" |
| `422` | erro de validação no campo, inline |
| `429` | "muitas tentativas, aguarde" |
| `503` (orçamento/cache) | banner âmbar: modo cache ativo e o que isso significa |
| `504` | timeout; sugestão de pedido mais específico |
| `cache hit` | badge verde no resultado |
| `warnings` | lista de ressalvas no CostSummary |

Turnstile: render explícito, token anexado ao POST, reset em erro.

## Erros e testes

### Tratamento de erro

- Falha de rede/abort: banner "não foi possível conectar" + tentar de
  novo (AbortController com timeout próprio).
- Turnstile falhou/expirou: reset do widget + mensagem; nunca POST sem
  token.
- Resposta malformada: render defensivo (arrays vazios, fallback `—`).
- `prefers-reduced-motion`: animações desligadas.
- Resultado novo recebe foco; tabela navegável; contraste AA no dark.

### Testes

- **Vitest + React Testing Library:** `RequestForm` (idle/loading/erro),
  `ResultPanel` (recusa, cache hit, warnings), `RankingTable`
  (ordem = nota, vazio), `MetricSuite` (acima/abaixo do limiar).
- **Playwright** (local/manual nesta fase, sem pipeline novo de CI):
  e2e com API mockada (fixtures espelhando `/leads` e `/metrics`):
  1. home carrega, digita pedido, submete → resultado com ranking.
  2. chips de pedido-modelo preenchem o textarea.
  3. recusa renderiza banner com motivo.
  4. `/metrics` mostra suítes com acima/abaixo do limiar.
  5. screenshots baseline dos estados principais (hero, resultado, erro).
- **`tsc --noEmit`** no build.
- **pytest:** `TestFrontend::test_static_assets_served` atualizado pro
  bundle novo; testes de API intactos.

## Fora de escopo

- Mudanças na API, nas proteções ou no pipeline (o SPA fallback no
  `app.py` é a única exceção Python, e não altera comportamento da API).
- Playwright em CI (baselines de screenshot ficam locais nesta fase).
- Tema claro / toggle de tema.
- Novas funcionalidades de produto (auth, billing, multi-tenant).

## Referências

- Direção visual aprovada: Vercel/Resend (dark), tom "produto sério".
- Mundo visual antigo (arquivo, não vigente): `DESIGN.md` ("Laudo
  Técnico") — substituído por este documento para o front.
- Restrições de produto que permanecem: `PRODUCT.md` (pt-BR, sem dado
  pessoal, métricas só de `eval/`).
