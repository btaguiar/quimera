/* Laudo de prospecção — front da demo pública (vanilla, mesma origem). */
"use strict";

const form = document.getElementById("form-laudo");
const textarea = document.getElementById("pedido");
const contador = document.getElementById("contador");
const statusEl = document.getElementById("status");
const resultado = document.getElementById("resultado");
const botaoEmitir = document.getElementById("emitir");
const turnstileBox = document.getElementById("turnstile");

let turnstileWidgetId = null;
let turnstileToken = null;

const fmtNum = new Intl.NumberFormat("pt-BR");
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
const fmtBytes = (b) => {
  const n = Number(b);
  if (b == null || !Number.isFinite(n)) return "—";
  return n >= 1024 ** 3
    ? `${fmtNum.format(+(n / 1024 ** 3).toFixed(2))} GB`
    : `${fmtNum.format(+(n / 1024 ** 2).toFixed(1))} MB`;
};
const fmtUSD = (v) => {
  const n = Number(v);
  if (v == null || !Number.isFinite(n)) return "—";
  return `US$ ${n.toFixed(6).replace(".", ",")}`;
};
const fmtMs = (v) => {
  const n = Number(v);
  if (v == null || !Number.isFinite(n)) return "—";
  return `${fmtNum.format(Math.round(n))} ms`;
};
const fmtData = (yyyymmdd) =>
  /^\d{8}$/.test(yyyymmdd || "")
    ? `${yyyymmdd.slice(6, 8)}/${yyyymmdd.slice(4, 6)}/${yyyymmdd.slice(0, 4)}`
    : "—";
const lista = (v) => (Array.isArray(v) && v.length ? v.map(esc).join(", ") : "—");
const valor = (v) => (v == null ? "—" : fmtNum.format(v));

async function carregarConfig() {
  let cfg = null;
  try {
    cfg = await (await fetch("/config")).json();
  } catch (_) { /* sem config: ambiente local sem Turnstile */ }
  if (!cfg || !cfg.turnstile_site_key) return;
  if (typeof window.turnstile?.render !== "function") {
    statusEl.textContent = "Desafio anti-bot indisponível — recarregue a página.";
    return;
  }
  try {
    turnstileWidgetId = window.turnstile.render(turnstileBox, {
      sitekey: cfg.turnstile_site_key,
      callback: (token) => { turnstileToken = token; },
      "expired-callback": () => { turnstileToken = null; },
      "error-callback": () => {
        turnstileToken = null;
        statusEl.textContent = "Desafio anti-bot falhou — recarregue a página.";
      },
      language: "pt-br",
    });
  } catch (_) {
    statusEl.textContent = "Desafio anti-bot indisponível — recarregue a página.";
  }
}

async function anotarVersao() {
  try {
    const saude = await (await fetch("/health")).json();
    const campo = document.getElementById("meta-version");
    if (campo && saude.version) campo.textContent = saude.version;
  } catch (_) { /* ignora */ }
}

async function orcamentoRestante() {
  try {
    const saude = await (await fetch("/health")).json();
    return fmtBytes(saude.budget_remaining_bytes);
  } catch (_) {
    return "—";
  }
}

textarea.addEventListener("input", () => {
  contador.textContent = `${textarea.value.length}/500`;
});

document.querySelectorAll(".exemplo").forEach((botao) => {
  botao.addEventListener("click", () => {
    textarea.value = botao.textContent.trim();
    contador.textContent = `${textarea.value.length}/500`;
    textarea.focus();
  });
});

form.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const pedido = textarea.value.trim();
  if (!pedido) {
    statusEl.textContent = "Escreva um pedido para emitir o laudo.";
    return;
  }
  botaoEmitir.disabled = true;
  resultado.hidden = true;
  resultado.textContent = "";
  const inicio = performance.now();
  const etapas = "extração → classificação → consulta → pontuação";
  statusEl.textContent = `Elaborando laudo… (${etapas})`;
  const cronometro = setInterval(() => {
    statusEl.textContent =
      `Elaborando laudo… ${((performance.now() - inicio) / 1000).toFixed(1)} s (${etapas})`;
  }, 200);
  try {
    const body = { request: pedido };
    if (turnstileToken) body.turnstile = turnstileToken;
    const resp = await fetch("/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const dados = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      renderizarErro(resp.status, dados);
      statusEl.textContent = "";
    } else {
      await renderizarLaudo(dados, (performance.now() - inicio) / 1000);
      statusEl.textContent = "";
    }
  } catch (_) {
    statusEl.textContent = "Falha de rede ao contatar a API.";
  } finally {
    clearInterval(cronometro);
    botaoEmitir.disabled = false;
    if (turnstileWidgetId !== null && typeof window.turnstile?.reset === "function") {
      turnstileToken = null;
      window.turnstile.reset(turnstileWidgetId);
    }
  }
});

function achado(num, titulo, corpoHtml) {
  return `<section class="achado">
    <h2><span class="num">${num}</span> ${esc(titulo)}</h2>
    ${corpoHtml}
  </section>`;
}

async function renderizarLaudo(dados, segundos) {
  const orcamento = await orcamentoRestante();
  const partes = [];
  let numero = 0;
  const proximo = () => ++numero;
  if (dados.cached) {
    partes.push(`<p><span class="selo selo-cache">Em cache</span></p>`);
  }
  if (dados.refused) {
    partes.push(achado(proximo(), "Indeferimento", `
      <p>${esc(dados.refusal_reason || "pedido recusado")}</p>
      <p>A política pública não responde pedidos de dado pessoal — de sócios,
      contato ou qualquer pessoa física.</p>`));
  } else {
    partes.push(...achadosDoLaudo(dados, proximo));
  }
  partes.push(rodapeCustos(dados, segundos, orcamento, proximo));
  if (Array.isArray(dados.warnings) && dados.warnings.length) {
    const itens = dados.warnings.map((w) => `<li>${esc(w)}</li>`).join("");
    partes.push(achado(proximo(), "Ressalvas", `<ol class="ressalvas">${itens}</ol>`));
  }
  resultado.innerHTML = partes.join("");
  resultado.hidden = false;
  resultado.scrollIntoView({ behavior: "smooth", block: "start" });
  resultado.focus({ preventScroll: true });
}

function achadosDoLaudo(dados, proximo) {
  const f = dados.filters || {};
  const achados = [];
  const temCnae = Array.isArray(dados.cnae_matches) && dados.cnae_matches.length > 0;
  achados.push(achado(proximo(), "Interpretação do pedido", `
    <dl class="kv">
      <div><dt>Atividade</dt><dd>${esc(f.cnae_query || "—")}</dd></div>
      <div><dt>UFs</dt><dd>${lista(f.ufs)}</dd></div>
      <div><dt>Municípios</dt><dd>${lista(f.municipio_names)}</dd></div>
      <div><dt>Idade mínima</dt><dd>${f.min_age_years == null ? "—" : `${esc(f.min_age_years)} anos`}</dd></div>
      <div><dt>Idade máxima</dt><dd>${f.max_age_years == null ? "—" : `${esc(f.max_age_years)} anos`}</dd></div>
      <div><dt>Capital mínimo</dt><dd>${f.min_capital == null ? "—" : valor(f.min_capital)}</dd></div>
      <div><dt>Portes</dt><dd>${lista(f.portes)}</dd></div>
      <div><dt>Limite</dt><dd>${f.limit == null ? "—" : `${esc(f.limit)} empresas`}</dd></div>
    </dl>
    <p class="mono">filtro aplicado pela policy pública: sem MEI, sem contato, sem pessoa física.</p>`));

  if (temCnae) {
    const linhas = dados.cnae_matches.map((m) => `
      <tr>
        <td class="mono">${esc(m[0])}</td>
        <td>${esc(m[1])}</td>
        <td class="num">${Number(m[2]).toFixed(3).replace(".", ",")}</td>
      </tr>`).join("");
    achados.push(achado(proximo(), "Classificação CNAE", `
      <div class="tabela-wrap">
        <table>
          <caption>códigos escolhidos por similaridade de embeddings (top-k)</caption>
          <thead><tr><th>Código</th><th>Descrição</th><th>Simil.</th></tr></thead>
          <tbody>${linhas}</tbody>
        </table>
      </div>`));
  }

  const snapshot = dados.snapshot && Object.values(dados.snapshot)[0];
  achados.push(achado(proximo(), "Consulta ao BigQuery", `
    ${dados.query_sql ? `<pre class="sql">${esc(dados.query_sql)}</pre>` : `<p>Consulta não executada (ver ressalvas).</p>`}
    <dl class="kv">
      <div><dt>Bytes processados</dt><dd>${fmtBytes(dados.bytes_processed)}</dd></div>
      <div><dt>Bytes cobrados</dt><dd>${fmtBytes(dados.bytes_billed)}</dd></div>
      <div><dt>Snapshot da base</dt><dd>${esc(snapshot || "—")}</dd></div>
    </dl>
    <p>SQL montado pelo sistema, parametrizado — o modelo não escreve SQL.
    Valores dos parâmetros: ${temCnae ? "achados 1 e 2" : "achado 1"}.</p>`));

  achados.push(achado(proximo(), "Ranking de empresas", tabelaRanking(dados)));
  return achados;
}

function tabelaRanking(dados) {
  const linhas = (dados.rows || []).map((r, i) => `
    <tr>
      <td class="num">${i + 1}</td>
      <td>${esc(r.razao_social)}${r.nome_fantasia ? `<br><small>${esc(r.nome_fantasia)}</small>` : ""}</td>
      <td>${esc(r.municipio || r.id_municipio || "—")}/${esc(r.sigla_uf || "—")}</td>
      <td class="mono">${esc(r.cnae_fiscal_principal || "—")}</td>
      <td class="mono">${fmtData(r.data_inicio_atividade)}</td>
      <td class="num">${r.capital_social == null ? "—" : valor(r.capital_social)}</td>
      <td>${esc(r.porte || "—")}</td>
      <td class="num">${r.score == null ? "—" : esc(r.score)}</td>
      <td>
        <details class="resumo-nota">
          <summary>motivos</summary>
          <ul class="motivos">${(r.motivos_score || []).map((m) => `<li>${esc(m)}</li>`).join("") || "<li>—</li>"}</ul>
        </details>
      </td>
    </tr>`).join("");
  if (!linhas) {
    return `<p>Nenhuma empresa atendida ao pedido (ver ressalvas).</p>`;
  }
  return `<div class="tabela-wrap">
    <table>
      <caption>${(dados.rows || []).length} empresas — ordenadas pela nota do ICP</caption>
      <thead><tr>
        <th>#</th><th>Empresa</th><th>Local</th><th>CNAE</th><th>Início</th>
        <th>Capital (R$)</th><th>Porte</th><th>Nota</th><th></th>
      </tr></thead>
      <tbody>${linhas}</tbody>
    </table>
  </div>`;
}

function rodapeCustos(dados, segundos, orcamento, proximo) {
  const etapas = Object.entries(dados.timings_ms || {})
    .map(([etapa, ms]) => `${esc(etapa)} ${fmtMs(ms)}`)
    .join(" · ");
  const modoCache = dados.cache_mode
    ? `<p><span class="selo selo-modo-cache">Modo cache — orçamento do dia esgotado</span></p>`
    : "";
  return achado(proximo(), "Custos e latência", `
    ${modoCache}
    <dl class="kv">
      <div><dt>Bytes cobrados</dt><dd>${fmtBytes(dados.bytes_billed)}</dd></div>
      <div><dt>Custo estimado</dt><dd>${fmtUSD(dados.estimated_cost_usd)}</dd></div>
      <div><dt>Latência do pipeline</dt><dd>${fmtMs(dados.latency_ms)}</dd></div>
      <div><dt>No navegador</dt><dd>${segundos.toFixed(1).replace(".", ",")} s</dd></div>
      <div><dt>Orçamento diário restante</dt><dd>${orcamento}</dd></div>
      <div><dt>Modelo</dt><dd>${esc(dados.model || "—")}</dd></div>
    </dl>
    ${etapas ? `<p class="mono">${etapas}</p>` : ""}`);
}

function renderizarErro(status, dados) {
  const mensagens = {
    401: "Não verificado: complete o desafio Turnstile e tente de novo.",
    422: `Pedido inválido: ${esc(dados.reason || "escreva um pedido com até 500 caracteres")}`,
    429: "Limite de requisições por IP atingido; aguarde alguns minutos.",
    502: `A extração falhou: ${esc(dados.reason || "tente reformular o pedido")}`,
    503: esc(dados.reason || "serviço indisponível; tente mais tarde"),
    504: esc(dados.reason || "execução excedeu o tempo limite; tente um pedido mais específico"),
  };
  const texto = mensagens[status] || esc(dados.reason || `erro ${status}`);
  resultado.innerHTML = `<section class="observacao achado">
    <h2><span class="num">!</span> Observação — pedido não atendido</h2>
    <p>${texto}</p>
  </section>`;
  resultado.hidden = false;
  resultado.scrollIntoView({ behavior: "smooth", block: "start" });
  resultado.focus({ preventScroll: true });
}

carregarConfig();
anotarVersao();
