---
version: 1
slug: "src-quimera-api-static-index-html"
primary_target: "src/quimera/api/static/index.html"
related_targets: []
---

Scope: página pública da demo (index) + anexo de métricas (metrics.html), servidos pela própria FastAPI em src/quimera/api/static/.
Visitor mode: Operate — o visitante completa uma tarefa (pedido -> lista ranqueada + explicação); a expressão nunca pode obscurecer tarefa, estado ou affordance.
Audience: avaliadores técnicos do portfólio (rigor, números, ceticismo) + potenciais usuários de prospecção (querem a lista rápido). Job: provar em uso que o sistema é medido e barato; ação primária: escrever um pedido e emitir o laudo.
Proof: resposta da API (filtros, CNAEs com similaridade, SQL, bytes, custo, score+motivos) e GET /metrics (eval/results + thresholds). Nada além disso.
Constraints: UI pt-BR, sem framework, arquivos estáticos, mesma origem, Turnstile no form, estados 422/401/429/503/504 + recusa + cache + ressalvas; nenhum dado pessoal; mundo visual "Laudo Técnico" (DESIGN.md seed).
Chosen direction: Laudo Técnico Numerado (roll 8ae3159d, direção 5/7, atribuída e confirmada pelo usuário; staging própria do documento: achados numerados em sequência 1-5; alternativas Factory/nixie pesadas e descartadas).
Memorable moment: o resultado CHEGA como laudo — achados numerados entrando em sequência com valores medidos em mono, e o carimbo "AVALIADO" batendo no anexo de métricas.
Unresolved decisions: copy exata dos pedidos-modelo (4 exemplos do golden e2e); rótulo do botão (EMITIR LAUDO).
