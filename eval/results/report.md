# Relatório de avaliação — Quimera

Gerado em 2026-09-26 18:27 UTC a partir de 13 resultados em `eval/results/`. Métricas 0–1; latência em ms.

## Extração de filtros

| modelo | policy | casos | acerto campos | acerto exato | recusa correta | recusa indevida | p50 (ms) | p95 (ms) | commit | data |
|---|---|---|---|---|---|---|---|---|---|---|
| gemini-2.5-flash | public | 45 | 0.899 | 0.800 | 1.000 | 0.057 | 4884 | 7027 | unknown | 2026-09-26 |
| gemini-2.5-flash | public | 45 | 0.899 | 0.778 | 1.000 | 0.000 | 4602 | 7371 | unknown | 2026-09-26 |
| gemini-2.5-flash | public | 45 | 0.937 | 0.867 | 1.000 | 0.000 | 1074 | 7434 | 4487b67 | 2026-09-26 |
| gemini-2.5-flash | public | 45 | 0.924 | 0.822 | 1.000 | 0.000 | 997 | 1902 | 686282e | 2026-09-26 |
| gemini-2.5-flash | public | 45 | 0.937 | 0.889 | 1.000 | 0.000 | 936 | 5040 | 686282e | 2026-09-26 |
| gemini-2.5-flash | public | 45 | 0.924 | 0.867 | 1.000 | 0.000 | 896 | 2357 | 686282e | 2026-09-26 |

## Mapeamento CNAE

| modelo | casos | recall@1 | recall@5 | MRR | p50 (ms) | p95 (ms) | commit | data |
|---|---|---|---|---|---|---|---|---|
| text-embedding-004 | 66 | 0.333 | 0.561 | 0.409 | 769 | 1547 | unknown | 2026-09-26 |
| text-embedding-004 | 66 | 0.424 | 0.697 | 0.518 | 803 | 1507 | unknown | 2026-09-26 |
| text-embedding-005 | 66 | 0.364 | 0.606 | 0.445 | 731 | 1435 | unknown | 2026-09-26 |
| text-embedding-005 | 66 | 0.485 | 0.742 | 0.570 | 754 | 1450 | unknown | 2026-09-26 |
| text-embedding-005 | 66 | 0.758 | 0.955 | 0.831 | 299 | 991 | 683c67e | 2026-09-26 |

## Ponta a ponta (cada empresa devolvida conferida)

| casos | empresas | casos ok | precisão/empresa | recusa correta | p50 (ms) | p95 (ms) | MB/pedido (p50) | custo total (US$) | commit | data |
|---|---|---|---|---|---|---|---|---|---|---|
| 20 | 802 | 0.750 | 0.944 | 1.000 | 3510 | 6048 | 136 | 0.0177 | 686282e | 2026-09-26 |
| 20 | 795 | 0.950 | 0.997 | 1.000 | 3698 | 6961 | 77 | 0.0174 | 686282e | 2026-09-26 |
