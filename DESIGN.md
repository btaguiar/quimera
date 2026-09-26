<!-- SEED: established with the user before implementation; re-run /impeccable document once there's code to capture the actual tokens and components. -->

---
name: Quimera
description: Demo pública do agente de prospecção — a página é um laudo técnico numerado.
---

# Design System: Quimera

## Overview

**Creative North Star: "O Laudo Técnico"**

A demo pública do Quimera vira um documento pericial: papel branco, tinta
quase-preta, regras horizontais finas, achados numerados (1. Interpretação
do pedido → 2. Classificação CNAE → 3. Consulta → 4. Ranking → 5. Custos) e
valores medidos em monospace. O visitante lê o resultado como um laudo: cada
afirmação numerada, cada medida visível, ressalvas quando o dado impõe
limites. A confiança vem da gramática documental — não de gradientes,
sombras ou cards.

Anti-referência explícita: landing SaaS de IA (hero com gradiente, caixa de
chat central, fileira de cards de features).

**Key Characteristics:**
- Papel branco (#FFFFFF), tinta (#16181D), um único acento: azul-tinta de
  carimbo (#1F3DB3) em interação e verificação.
- Achados numerados como única estrutura de conteúdo; monospace para todo
  valor medido (bytes, custo, códigos, SQL, latências).
- Zero sombras; hierarquia por regras, peso tipográfico e numeração.
- Carimbo de validação como assinatura visual (métricas avaliadas).

## Colors

Estratégia: Restrained — neutros de documento + um acento.

### Primary
- **Azul-Tinta de Carimbo** (#1F3DB3): interação e verificação — links,
  botão principal, numeração de achados, marcas de "verificado" e o carimbo.
  Nunca como fundo de grandes áreas.

### Neutral
- **Papel** (#FFFFFF): fundo de todas as superfícies.
- **Tinta** (#16181D): texto, cabeçalhos e regras estruturais fortes.
- **Regra Fina** (#C7CAD1): hairlines de tabela, separadores, bordas de campos.
- **Suporte** (#5A5F6B): metadados, labels, notas de rodapé.

### Estados funcionais (não são acento)
- **Verificado** (#0E7A3C): confirmações (cache hit, métrica acima do limiar).
- **Erro** (#B3261E): erros e recusas.

### Named Rules
**A Regra da Tinta Única.** O azul-tinta aparece em ≤10% da área de qualquer
tela; sua raridade é o que o transforma em assinatura de validação.

## Typography

**Body Font:** pilha de sistema sem serifa (system-ui)
**Label/Mono Font:** pilha mono do sistema (ui-monospace, Consolas, Menlo,
monospace)

**Character:** Documento técnico institucional: sans de ofício público para
prosa, mono de máquina de escrever para tudo que foi medido. Nenhuma fonte
exótica — a identidade está na numeração e nas regras, não na face.

### Hierarchy
- **Display** (700, 28–34px/1.2): título do documento ("QUIMERA — LAUDO DE
  PROSPECÇÃO"), caixa alta com espaçamento.
- **Headline** (600, 15px/1.4): número + nome de cada achado ("2 —
  CLASSIFICAÇÃO CNAE"), caixa alta, tracking 0.08em.
- **Body** (400, 16px/1.6, máx. 72ch): prosa do laudo.
- **Label** (500, 12px, caixa alta, tracking 0.06em): metadados do cabeçalho
  e rótulos de campo.
- **Mono** (400, 14px/1.5): todo valor medido, código, SQL, CNPJ, latência,
  bytes.

### Named Rules
**A Regra do Valor Medido.** Se um número foi medido, ele vira mono; se não
foi medido, não aparece.

## Layout

Folha de documento: largura máxima ~880px centrada, margem interna generosa
(24–48px), moldura de hairline. Cabeçalho do laudo = bloco de metadados em
duas colunas (data, versão, modelo, política). Achados empilhados
verticalmente com numeração à esquerda em coluna própria (hanging numbers).
Tabelas largas ganham scroll horizontal com a primeira coluna visível.
Celular: a folha ocupa a largura total e o número do achado sobe para a
linha do título.

Ritmo: mais espaço acima de um achado do que abaixo — como parágrafos de
documento.

## Elevation & Depth

**Sem sombras.** A página é papel impresso: hierarquia vem de regras
(simples e dupla), peso tipográfico e numeração. Nenhum card flutua; nenhum
gradiente; nenhum vidro.

## Shapes

Formas de documento impresso: cantos retos (radius 0) em tudo, exceto o
carimbo (retângulo com borda dupla, rotação −4°). Campos de formulário têm
borda inferior grossa + hairlines laterais, como campos de formulário de
papel. Botão principal é retângulo de tinta sólida.

## Do's and Don'ts

### Do:
- **Do** numerar cada seção de resultado e referenciá-la por número.
- **Do** exibir bytes, custo, latência e códigos em mono, com unidades.
- **Do** usar o carimbo de validação (borda dupla, azul-tinta, rotação
  sutil) como assinatura das métricas medidas.
- **Do** marcar limitações de dados como "RESSALVA" numerada dentro do
  achado correspondente.

### Don't:
- **Don't** usar sombras, gradientes, cards flutuantes ou cantos arredondados
  (exceto o carimbo).
- **Don't** usar cor onde uma regra ou peso tipográfico resolve.
- **Don't** exibir número que não venha de `eval/` ou da resposta da API.
- **Don't** exibir dado pessoal de qualquer tipo — nenhuma exceção, nenhum
  estado.
