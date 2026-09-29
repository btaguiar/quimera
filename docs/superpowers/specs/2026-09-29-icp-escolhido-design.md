# Design — ICP escolhido pelo visitante da demo

Data: 2026-09-29
Status: direção aprovada pelo Bruno em conversa ("perfis prontos + ajuste")
Escopo: o visitante escolhe o perfil de cliente ideal (ICP) antes do pedido;
o ranking e a nota passam a usar esse ICP. Pipeline, policy e eval
inalterados (o eval segue com o ICP padrão).

## Por que é barato

- `pipeline.run` já recebe `icp: ICPConfig`.
- O ranking do SQL (`query._icp_ranking`) já usa todos os valores do ICP como
  parâmetros (`@icp_w_porte`, `@icp_capital_min`…): trocar o ICP por pedido
  não abre injeção de SQL nem muda bytes processados.

## Contrato da API

`POST /leads` ganha o campo opcional `icp`:

```json
{
  "request": "clínicas em Santo André",
  "turnstile": "…",
  "icp": {
    "preferred_portes": ["demais"],
    "target_min_age_years": 2,
    "target_full_age_years": 10,
    "target_min_capital": 50000,
    "target_max_capital": 10000000,
    "w_porte": 40, "w_age": 30, "w_capital": 30, "w_rede": 0, "w_dominio": 0,
    "target_min_estabelecimentos": 2,
    "mei_factor": 0.5
  }
}
```

- Sem `icp`: `ICPConfig()` padrão (comportamento de hoje).
- Com `icp`: todos os campos obrigatórios (sem mescla parcial — o front
  sempre manda o perfil inteiro), validados:

| Campo | Limite |
|---|---|
| `preferred_portes` | 1–3 valores distintos de `micro`, `pequena`, `demais` |
| `target_min_age_years` | 0–50 |
| `target_full_age_years` | ≥ mínimo, ≤ 60 |
| `target_min_capital` | R$ 1.000 – R$ 1 bi |
| `target_max_capital` | ≥ mínimo, ≤ R$ 10 bi |
| `w_*` (5 pesos) | 0–100 cada, soma > 0 |
| `target_min_estabelecimentos` | 2–100 |
| `mei_factor` | 0–1 |

- **Pesos normalizados para somar 100** no servidor: a nota fica em 0–100
  no Python e no SQL (o SQL não corta em 100). O visitante pode digitar
  pesos relativos.
- ICP inválido → 422 com `reason` apontando o campo (não a mensagem do
  campo `request`).
- **Cache:** a chave passa a ser o hash de pedido normalizado + ICP
  canônico (JSON ordenado, pesos já normalizados). Mesmo pedido com outro
  ICP não reaproveita o ranking.
- **Resposta:** ganha `icp` com o ICP efetivamente usado (pesos
  normalizados), para o front mostrar com que perfil ranqueou.
- Fixos (fora do contrato): `capital_decay_decades` e
  `porte_partial_factor`.

## Perfis prontos (front, `lib/icp.ts`)

| Perfil | Porte alvo | Idade (mín.–plena) | Capital (mín.–teto) | Pesos porte/idade/capital/rede/domínio |
|---|---|---|---|---|
| **Estabelecida** (padrão = `ICPConfig()`) | demais | 2–10 | R$ 50 mil – 10 mi | 40/30/30/0/0 |
| **Pequeno negócio local** | micro, pequena | 1–5 | R$ 10 mil – 500 mil | 40/30/30/0/0 |
| **Rede em expansão** | pequena, demais | 3–15 | R$ 100 mil – 20 mi | 20/20/20/40/0 (rede a partir de 2) |
| **Negócio digital** | pequena, demais | 1–8 | R$ 20 mil – 5 mi | 20/20/20/0/40 |

MEI com fator 0,5 em todos.

## Front

- Passo **① Perfil de cliente ideal** antes do **② Pedido**: 4 cartões
  (grupo de rádio acessível) com nome e resumo em mono.
- "Ajustar este perfil" abre os controles do perfil escolhido: portes
  (checkbox), idade mín./plena, capital mín./teto, os 5 pesos (com a soma e
  o aviso de que são normalizados para 100), mínimo de estabelecimentos
  (quando rede > 0) e fator MEI. Perfil alterado mostra "(ajustado)" e
  "restaurar".
- Validação no front espelha a da API (erro inline, "Analisar" bloqueado
  enquanto inválido).
- O resultado mostra com que perfil ranqueou ("ordenadas pela nota do ICP
  Estabelecida (ajustado)").

## Testes

- pytest: ICP validado (limites, portes, soma de pesos), pesos
  normalizados, pedido sem `icp` igual a hoje, ICP chega ao pipeline e ao
  SQL, cache separa ICPs, 422 com motivo do ICP, resposta traz `icp`.
- Vitest: perfis válidos contra os limites, normalização, `IcpPicker`
  (seleção, ajuste, restaurar, erro inline), `submitLead` envia `icp`,
  Home manda o perfil escolhido.
- Playwright: escolher perfil → pedido → POST leva o ICP.

## Fora de escopo

- Salvar perfis do visitante; ICP no eval; ICP da Turno 24 (Fase 5).
