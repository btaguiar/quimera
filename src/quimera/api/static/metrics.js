/* Anexo A — métricas medidas: renderiza GET /metrics (nada escrito à mão). */
"use strict";

const fmtNum = new Intl.NumberFormat("pt-BR");
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
const fmtPct = (v) => (v == null ? "—" : `${fmtNum.format(+(v * 100).toFixed(1))}%`);
const fmtNum2 = (v) => (v == null ? "—" : fmtNum.format(v));
const ultima = (lista) => (lista && lista.length ? lista[lista.length - 1] : null);
const selectE2e = (lista) => {
  if (!lista || !lista.length) return null;
  const principal = lista.filter((e) => e && e.golden === "golden_e2e.jsonl" && (e.metrics?.n_cases ?? 0) >= 20);
  if (principal.length) return principal[principal.length - 1];
  const cheios = lista.filter((e) => (e.metrics?.n_cases ?? 0) >= 20);
  if (cheios.length) return cheios[cheios.length - 1];
  return ultima(lista);
};

function linhaPct(rotulo, medido, limiar) {
  const texto = medido == null ? "—" : fmtPct(medido);
  const lim = limiar == null ? "—" : fmtPct(limiar);
  const batido = medido != null && limiar != null && medido >= limiar;
  const status = limiar == null
    ? ""
    : batido
      ? '<span class="selo selo-limiar">≥ limiar</span>'
      : "abaixo";
  return `<tr>
    <td>${esc(rotulo)}</td>
    <td class="num">${texto}</td>
    <td class="num">${lim}</td>
    <td>${status}</td>
  </tr>`;
}

function linhaQtd(rotulo, valor) {
  return `<tr>
    <td>${esc(rotulo)}</td>
    <td class="num">${fmtNum2(valor)}</td>
    <td class="num">—</td>
    <td></td>
  </tr>`;
}

function tabela(num, titulo, caption, corpo) {
  return `<section class="achado">
    <h2><span class="num">${num}</span> ${esc(titulo)}</h2>
    <div class="tabela-wrap">
      <table>
        <caption>${esc(caption)}</caption>
        <thead><tr><th>Métrica</th><th>Medido</th><th>Limiar</th><th></th></tr></thead>
        <tbody>${corpo}</tbody>
      </table>
    </div>
  </section>`;
}

async function carregarMetricas() {
  const alvo = document.getElementById("metricas");
  const carimbo = document.getElementById("carimbo");
  try {
    const dados = await (await fetch("/metrics")).json();
    const limiares = dados.thresholds || {};
    const ext = ultima(dados.extraction);
    const cnae = ultima(dados.cnae);
    const e2e = selectE2e(dados.e2e);
    const partes = [];

    if (ext) {
      const m = ext.metrics || {};
      partes.push(tabela(1, "Extração de filtros",
        `última execução: ${ext.date || "?"} · commit ${ext.commit || "?"}`,
        linhaPct("Recusa correta (dado pessoal)", m.correct_refusal_rate, limiares.correct_refusal_rate)
        + linhaPct("Recusa indevida", m.false_refusal_rate)
        + linhaPct("Acerto por campo", m.overall_field_accuracy, limiares.overall_field_accuracy)
        + linhaPct("Acerto exato do conjunto", m.exact_match_rate)
        + linhaQtd("Casos", m.n_cases)));
    }
    if (cnae) {
      const m = cnae.metrics || {};
      partes.push(tabela(2, "Mapeamento CNAE",
        `última execução: ${cnae.date || "?"} · commit ${cnae.commit || "?"}`,
        linhaPct("Recall@1", m["recall@1"])
        + linhaPct("Recall@5", m["recall@5"], limiares.recall_at_5)
        + linhaPct("MRR", m.mrr)
        + linhaQtd("Casos", m.n_cases)));
    }
    if (e2e) {
      const m = e2e.metrics || {};
      partes.push(tabela(3, "Ponta a ponta",
        `última execução: ${e2e.date || "?"} · commit ${e2e.commit || "?"}`,
        linhaPct("Casos 100% corretos", m.case_pass_rate, limiares.e2e_case_pass_rate)
        + linhaPct("Precisão por empresa", m.row_precision, limiares.e2e_row_precision)
        + linhaPct("Recusa correta", m.e2e_correct_refusal_rate, limiares.e2e_correct_refusal_rate)
        + linhaQtd("Empresas avaliadas", m.n_rows)
        + linhaQtd("Casos", m.n_cases)));
    }
    if (!partes.length) {
      alvo.innerHTML = `<p>Sem resultados de avaliação disponíveis.</p>`;
      return;
    }
    alvo.innerHTML = partes.join("");
    const referencia = e2e || cnae || ext;
    if (carimbo && referencia) {
      carimbo.textContent = `Avaliado — ${(referencia.date || "").slice(0, 10)}`;
      carimbo.hidden = false;
    }
  } catch (_) {
    alvo.innerHTML = `<p class="carregando">Não foi possível carregar /metrics.</p>`;
  }
}

carregarMetricas();
