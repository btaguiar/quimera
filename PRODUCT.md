# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- Avaliadores técnicos do portfólio de AI Engineer do Bruno (recrutadores e
  engenheiros seniores) chegando pelo GitHub/README, com poucos minutos e
  ceticismo saudável. [confirmado em entrevista 2026-09-26]
- Potenciais usuários de prospecção: quem quer uma lista de empresas a partir
  de um pedido em português. [confirmado em entrevista 2026-09-26]

## Product Purpose

Quimera transforma um pedido em português ("clínicas odontológicas abertas
há mais de 2 anos em Santo André, porte médio") em uma lista ranqueada de
empresas (CNPJ), combinando LLM (extração estruturada), embeddings
(mapeamento CNAE) e BigQuery (base pública de CNPJ). A página pública da
demo existe para provar em uso real o rigor medido: cada decisão explicável
(filtros, CNAEs, SQL, bytes, custo) e cada métrica reproduzível em `eval/`.

## Positioning

Sistema avaliado com números públicos e custo limitado por design — não um
"gerador de leads" genérico. O LLM nunca escreve SQL; público vs. privado
vive em um único `policy.py`; toda afirmação do README tem métrica
reproduzível em `eval/results/` (regra de ouro do projeto).

## Operating Context

- Demo pública em Cloud Run (escala a zero, orçamento diário de bytes, rate
  limit por IP, cache com modo cache quando o orçamento estoura).
- Modo público: sem MEI, sem contato, sem pessoa física; recusa pedidos de
  dado pessoal (200 com `refused: true`).
- Latência p50 ~4 s por pedido; dry run + teto de bytes por consulta;
  Cloudflare Turnstile contra abuso.
- Métricas da Fase 2 (extraction, cnae, e2e) em `eval/results/*.json`,
  servidas por `GET /metrics`.

## Capabilities and Constraints

- UI em pt-BR, sem framework, arquivos estáticos servidos pela própria
  FastAPI, mesma origem (sem CORS).
- Estados da busca: idle, carregando, recusa, 401, 422, 429, 503 modo
  cache/orçamento, 504, cache hit, warnings de dados.
- Nenhum dado pessoal em tela, resposta ou log; nenhuma afirmação sem
  métrica correspondente em `eval/`.
- Página de métricas renderiza os JSON medidos — nada escrito à mão.

## Brand Commitments

- Nome: Quimera. Idioma: português do Brasil em toda a UI. Sem emojis.

## Evidence on Hand

- `eval/results/*.json` (extraction, cnae, e2e medidos em 2026-09-26;
  limiares em `eval/thresholds.json`), `README.md` com as tabelas,
  `docs/schema.md` com as medições de custo.
- Ausências que o trabalho futuro não pode fabricar: depoimentos, clientes,
  benchmarks de terceiros.

## Product Principles

1. Rigor mensurado acima de aparência de produto: números antes de adjetivos.
2. Explicabilidade radical: mostrar filtros, CNAEs, SQL e custo de cada resposta.
3. Custo como cidadão de primeira classe: bytes e orçamento visíveis ao visitante.
4. Sem dado pessoal, sempre, em nenhum estado da interface.
5. Simplicidade operacional: uma imagem, escala a zero, proteções na app.

## Accessibility & Inclusion

- Contraste e navegação por teclado adequados; nenhum requisito formal
  confirmado além disso.
