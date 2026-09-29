---
name: Quimera
description: Página de produto + demo ao vivo. Escuro quente, um acento âmbar-queimado, a frase anotada como assinatura.
---

# Design System: Quimera

## Overview

**Creative North Star: "A Frase Anotada"**

O mecanismo do Quimera é transformar uma frase em português numa lista de
empresas. A identidade mostra exatamente isso: trechos do pedido sublinhados
em âmbar, cada um com uma etiqueta mono do filtro que virou (atividade →
CNAE, cidade → município/UF, "há mais de 2 anos" → idade mínima). A mesma
gramática de anotação aparece no hero, no "Como funciona" e na leitura do
resultado. Produto primeiro; a transparência técnica fica a um passo, nunca
escondida.

Cena de uso: SDR, dono de agência ou avaliador técnico, no notebook, em
sessão de trabalho focada, muitas vezes à noite, com a página aberta ao lado
do CRM ou do GitHub. O escuro quente reduz o cansaço visual e faz o âmbar
funcionar como luz de sinalização: onde ele aparece, algo foi encontrado.

Anti-referências: landing de IA com glow azul-roxo, blobs desfocados, texto em
gradiente, fileira de cards de ícone + título + texto, hero de "número
gigante".

**Key Characteristics:**
- Fundo carvão quente, não preto azulado. Superfícies sobem em degraus de
  luminância, sem sombra colorida e sem vidro.
- Um acento: âmbar-queimado. Ele marca o que foi *encontrado ou decidido*:
  sublinhados de anotação, nota do ranking, ação principal.
- Display em Archivo expandido (font-stretch 112–125%); corpo em Inter; mono
  (JetBrains Mono) só para valores medidos, códigos, SQL e etiquetas de
  anotação.
- Logo: três formas fundidas num Q (meio-disco = linguagem/LLM, quadrado =
  dados/BigQuery, cunha = vetor/embeddings).

## Colors

Estratégia: Restrained. Neutros quentes e um acento.

### Neutros (tokens em `frontend/src/styles/globals.css`)
- **Carvão** `--background` #0D0B09: fundo da página.
- **Superfície 1** `--card` #15120F: blocos de conteúdo, campos.
- **Superfície 2** `--secondary` #1D1915: etiquetas, faixas de destaque.
- **Superfície 3** `--surface-3` #27211B: hover de linhas e controles.
- **Linha** `--border` rgba(245,225,200,0.10); **Linha forte** `--line-strong` rgba(245,225,200,0.20).
- **Texto** `--foreground` #F4EDE4 (branco quente).
- **Suporte** `--muted-foreground` #A69C90: prosa secundária, rótulos (7:1 no carvão).
- **Tênue** `--faint` #8A8074: metadados curtos (≥4.5:1 no carvão).

### Acento
- **Âmbar-queimado** `--accent` #F07A2A: sublinhados de anotação, barra de
  nota, links, foco, botão principal (com texto `--accent-foreground`
  #1A0D03). Hover `--accent-strong` #FF9447. Fundo suave `--accent-soft`
  rgba(240,122,42,0.12).

### Estados funcionais (não são acento)
- **Verificado** `--success` #6CC593: acima do limiar, cache.
- **Erro** `--destructive` #F0695E: erro e abaixo do limiar.
- **Atenção** `--warning` #E9C46A: perfil ajustado, modo cache, recusa.

### Named Rules
**A Regra do Âmbar Encontrado.** O âmbar só aparece onde o sistema encontrou
ou decidiu algo (ou onde o visitante age). Nunca como decoração de fundo,
nunca em gradiente.

## Typography

- **Display:** Archivo Variable, 650–750, font-stretch 118%, tracking
  -0.025em. h1 clamp(2.4rem, 5.2vw, 4.25rem)/1.02; h2 clamp(1.75rem, 3.2vw, 2.5rem)/1.1.
- **Body:** Inter Variable 400, 16–18px/1.6, medida ≤ 68ch.
- **Label:** Inter 500, 13px, sem caixa alta.
- **Mono:** JetBrains Mono Variable 400–500, 12–14px: CNAE, CNPJ, bytes,
  custo, latência, SQL, etiquetas de anotação, métricas.

### Named Rules
**A Regra do Valor Medido.** Número medido vira mono; número que não foi
medido não aparece. Mono nunca como fantasia "técnica" para prosa.
**Um kicker só.** Rótulo acima de título apenas onde carrega informação
(passo de sequência, estado); não em toda seção.

## Layout

- Container 1120px (`max-w-6xl`), gutter 20px no celular, 32px no desktop.
- Seções da landing separadas por linha de 1px e 96–128px de respiro; mais
  espaço acima do título do que abaixo.
- Hero em duas colunas iguais (texto 6/12, demonstração anotada 6/12); no
  celular a demonstração desce para baixo do CTA.
- Ordem da Home: hero → como funciona → casos de uso → números → demo
  (`#demo`) → rodapé. Todo CTA leva à demo; casos de uso preenchem frase e
  perfil e rolam até ela.
- Resultado da demo: produto primeiro (lista ranqueada no topo), depois
  "Como a Quimera chegou nessa lista" com as seções numeradas
  (interpretação, CNAE, consulta, custos, ressalvas).
- Tabelas largas rolam dentro de uma região `relative overflow-x-auto`
  (o `relative` impede que `sr-only` alargue a página).
- "Como funciona" é uma faixa horizontal de três estágios ligados por uma
  linha, cada um com um artefato real do estágio (frase, etiqueta, linha de
  ranking), não um card de ícone.
- Casos de uso são linhas de uma lista (segmento → pedido → perfil), cada
  linha é um botão que preenche a demo.
- Números viram uma ficha técnica (métrica · medido · limiar · estado),
  alimentada ao vivo por `GET /metrics`.

## Elevation & Depth

Profundidade por degrau de superfície e linha. A única sombra permitida é a
do painel de demonstração do hero: `0 24px 60px -20px rgba(0,0,0,0.6)`, com
deslocamento, sem halo colorido.

## Shapes

Raio base 6px (`--radius: 0.375rem`); etiquetas de anotação 3px; botões 6px.
Sublinhado de anotação: 2px âmbar, offset 6px. Nada de pílula grande.

## Motion

Um momento autorado: no carregamento, os sublinhados do hero se desenham em
sequência (scaleX, 420ms, ease-out exponencial, 140ms de intervalo), as
etiquetas aparecem, e as linhas do ranking sobem. Estado final visível por
padrão; `prefers-reduced-motion` mostra o estado final sem animação. Hover:
cor e fundo em 150ms. Nada mais se move.

## Components

- **Logo** (`components/Logo.tsx`): símbolo 3 partes + wordmark "quimera" em
  Archivo 125% 700 minúsculo. Favicon = só o símbolo (`public/favicon.svg`).
- **Botão principal:** fundo âmbar, texto `--accent-foreground`, Archivo 600
  110%, seta →. Secundário: linha forte, texto claro.
- **Etiqueta de anotação:** mono 11–12px, fundo `--secondary`, rótulo em
  `--faint` + valor em `--foreground`.
- **Barra de nota:** trilho `--secondary`, preenchimento âmbar, 4px.

## Do's and Don'ts

### Do:
- **Do** mostrar o mecanismo (frase → filtros → lista) em vez de adjetivos.
- **Do** rotular qualquer exemplo fictício como "ilustrativo".
- **Do** ler números da API ou de `eval/` ao vivo; mostrar limiar e estado,
  inclusive quando está abaixo.
- **Do** manter pt-BR, sem emojis.

### Don't:
- **Don't** usar glow, blobs desfocados, gradiente em texto ou vidro.
- **Don't** fazer grade de cards iguais de ícone + título + texto.
- **Don't** inventar depoimentos, logos de clientes, preços ou benchmarks.
- **Don't** exibir dado pessoal em nenhum estado.
